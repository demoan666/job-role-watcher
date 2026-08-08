"""FastAPI backend for the job-search command center.

Binds to 127.0.0.1 only — single-user, local-only for v1 (see plan doc).
This assumption breaks the moment this moves to a cloud VM; a real auth
token will be needed at that point, not just localhost binding.
"""

import os

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import re

import db
import gmail
import llm
import resume_parse
import scoring
import vault
from config import (
    delete_custom_provider,
    get_llm_settings,
    load_config,
    mask_key,
    save_custom_provider,
    save_llm_settings,
)

app = FastAPI(title="job-search backend")

# The frontend is served from GitHub Pages (a different origin) but talks to
# this backend on localhost, on the same machine the user is browsing from.
# Allow any origin — this process only ever binds to 127.0.0.1, so the only
# way to reach it at all is already from the user's own machine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    db.init_db()
    try:
        db.sync_postings_from_json()
    except Exception:
        pass  # data/postings.json may not exist yet on a fresh checkout — not fatal


@app.get("/health")
def health():
    return {"status": "ok"}


class VaultInit(BaseModel):
    password: str
    migrate: bool = True


class VaultUnlock(BaseModel):
    password: str


class VaultChangePassword(BaseModel):
    new_password: str


@app.get("/vault/status")
def vault_status():
    return {"initialized": vault.is_initialized(), "unlocked": vault.is_unlocked()}


@app.post("/vault/init")
def vault_init(body: VaultInit):
    """First-time setup. Optionally (default True) migrates existing
    plaintext secrets — config.json's LLM keys and backend/client_secret.json
    — into the newly-created vault, per decision #24. Refuses to run twice;
    use /vault/unlock on an already-initialized vault instead."""
    if vault.is_initialized():
        raise HTTPException(status_code=409, detail="Vault already initialized.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Master password must be at least 8 characters.")
    vault.init_vault(body.password)
    migrated = vault.migrate_plaintext_secrets() if body.migrate else []
    return {"status": "initialized", "migrated_secrets": migrated}


@app.post("/vault/unlock")
def vault_unlock(body: VaultUnlock):
    if not vault.is_initialized():
        raise HTTPException(status_code=404, detail="Vault not initialized yet.")
    if not vault.unlock(body.password):
        raise HTTPException(status_code=401, detail="Incorrect master password.")
    return {"status": "unlocked"}


@app.post("/vault/lock")
def vault_lock():
    vault.lock()
    return {"status": "locked"}


@app.post("/vault/change-password")
def vault_change_password(body: VaultChangePassword):
    if not vault.is_unlocked():
        raise HTTPException(status_code=423, detail="Unlock the vault first.")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Master password must be at least 8 characters.")
    vault.change_password(body.new_password)
    return {"status": "changed"}


class ResumeText(BaseModel):
    resume_text: str


class ProfileSave(BaseModel):
    resume_text: str
    extracted: dict
    manual_tags: list[str] = []


@app.post("/profile/extract")
def extract_profile(body: ResumeText):
    """Preview only — runs the LLM extraction but does not save. The user
    reviews/edits the result client-side before POSTing it to /profile."""
    try:
        return llm.extract_resume_profile(body.resume_text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}")


@app.post("/profile/upload")
async def upload_resume(file: UploadFile):
    """Text extraction only — does not run LLM extraction or save. Returns
    the raw text for the user to review/edit in the textarea, same as if
    they'd pasted it, before calling /profile/extract."""
    content = await file.read()
    try:
        text = resume_parse.extract_text(file.filename, content)
    except resume_parse.UnsupportedFileType as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"resume_text": text}


@app.get("/profile")
def get_profile():
    return db.get_profile() or {}


@app.post("/profile")
def save_profile(body: ProfileSave):
    db.save_profile(body.resume_text, body.extracted, body.manual_tags)
    return {"status": "saved"}


class LLMSettingsSave(BaseModel):
    keys: dict[str, str] = {}
    assignments: dict[str, dict] = {}


@app.get("/settings/llm")
def get_llm_settings_endpoint():
    """Provider/task metadata (labels, curated model lists, tooltip
    descriptions — static for built-ins, user-supplied for custom providers)
    plus which providers currently have a key configured — never the key
    itself, only a masked preview and a boolean."""
    settings = get_llm_settings()
    providers_out = {}
    for provider_id, meta in llm.get_all_providers().items():
        api_key = (settings["providers"].get(provider_id) or {}).get("api_key") or ""
        providers_out[provider_id] = {
            "label": meta["label"],
            "models": meta["models"],
            "configured": bool(api_key),
            "masked_key": mask_key(api_key),
            "custom": bool(meta.get("custom")),
        }
    assignments_out = {}
    for task_id, meta in llm.TASKS.items():
        assignment = settings["assignments"].get(task_id) or llm.DEFAULT_ASSIGNMENT
        assignments_out[task_id] = {
            "provider": assignment["provider"],
            "model": assignment["model"],
            "label": meta["label"],
            "description": meta["description"],
        }
    return {"providers": providers_out, "assignments": assignments_out}


@app.post("/settings/llm")
def save_llm_settings_endpoint(body: LLMSettingsSave):
    save_llm_settings(keys=body.keys, assignments=body.assignments)
    return {"status": "saved"}


class ModelSpec(BaseModel):
    id: str
    label: str


class CustomProviderSave(BaseModel):
    label: str
    base_url: str
    api_key: str = ""
    models: list[ModelSpec] = []


@app.post("/settings/llm/custom-provider")
def add_custom_provider(body: CustomProviderSave):
    """Adds a user-defined OpenAI-API-compatible provider (Groq, DeepSeek,
    OpenRouter, a local Ollama server, etc.) — anything not in llm.PROVIDERS.
    provider_id is slugified from the label, de-duplicated against existing
    provider ids (built-in or custom) if it collides."""
    if not body.label.strip() or not body.base_url.strip() or not body.models:
        raise HTTPException(status_code=400, detail="Label, base URL, and at least one model are required.")
    slug = re.sub(r"[^a-z0-9]+", "-", body.label.strip().lower()).strip("-") or "custom"
    existing_ids = set(llm.get_all_providers().keys())
    provider_id = f"custom_{slug}"
    n = 2
    while provider_id in existing_ids:
        provider_id = f"custom_{slug}-{n}"
        n += 1
    save_custom_provider(
        provider_id, body.label.strip(), body.base_url.strip(),
        [m.model_dump() for m in body.models], body.api_key.strip(),
    )
    return {"status": "saved", "provider_id": provider_id}


@app.delete("/settings/llm/custom-provider/{provider_id}")
def remove_custom_provider(provider_id: str):
    delete_custom_provider(provider_id)
    return {"status": "deleted"}


@app.get("/usage/llm")
def get_llm_usage(since: str | None = None):
    """Real token counts (from each provider's own response) plus an
    estimated $ cost where backend/llm.py has verified pricing for that
    provider/model — see llm.PROVIDERS. `since` (ISO timestamp) adds a
    "session" window scoped to whatever the caller considers a session —
    the frontend passes its own page-load time, since this single-user
    local backend has no server-side session concept of its own."""
    return db.get_llm_usage_summary(since=since)


class CompanyToggle(BaseModel):
    name: str
    enabled: bool


class ScopeSave(BaseModel):
    active_ats: list[str]
    contract_modes: list[str]
    companies: list[CompanyToggle] = []
    industries: list[str] = []
    countries: list[str] = []


@app.get("/scope")
def get_scope():
    return db.get_scope()


@app.get("/scope/options")
def get_scope_options():
    """Static reference lists the Setup tab renders checkboxes from —
    kept server-side so the frontend and role_search.md's taxonomy can't
    drift independently."""
    return {"industries": db.ALL_INDUSTRIES}


@app.post("/scope")
def save_scope(body: ScopeSave):
    db.save_scope(
        body.active_ats, body.contract_modes, [c.model_dump() for c in body.companies],
        industries=body.industries, countries=body.countries,
    )
    return {"status": "saved"}


class ScopePresetSave(BaseModel):
    name: str


@app.get("/scope/presets")
def list_scope_presets():
    return {"presets": db.list_scope_presets()}


@app.post("/scope/presets")
def save_scope_preset(body: ScopePresetSave):
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Preset name is required.")
    preset = db.save_scope_preset(body.name.strip())
    return {"status": "saved", "preset": preset}


@app.post("/scope/presets/{preset_id}/apply")
def apply_scope_preset(preset_id: str):
    scope = db.apply_scope_preset(preset_id)
    if scope is None:
        raise HTTPException(status_code=404, detail="Preset not found.")
    return {"status": "applied", "scope": scope}


@app.delete("/scope/presets/{preset_id}")
def delete_scope_preset(preset_id: str):
    db.delete_scope_preset(preset_id)
    return {"status": "deleted"}


class LeadCapture(BaseModel):
    source: str  # "discord" | "whatsapp" | "telegram" | "slack" | other free text
    source_channel: str = ""
    author: str = ""
    raw_text: str


@app.post("/leads/capture")
def capture_lead(body: LeadCapture):
    """Single entry point for every lead, live-ingested or manually pasted —
    triage/notification logic downstream doesn't care which path it came
    through. Triage failure (e.g. no API key configured yet) still stores
    the raw lead rather than dropping it."""
    try:
        triage = llm.triage_message(body.raw_text, body.source)
    except Exception:
        triage = None
    lead_id = db.insert_lead(body.source, body.source_channel, body.author, body.raw_text, triage)
    return {"id": lead_id, "triage": triage}


@app.get("/leads")
def list_leads():
    leads = db.get_leads()
    last_seen = db.get_last_seen()
    unread_count = sum(1 for lead in leads if not last_seen or lead["created_at"] > last_seen)
    return {"leads": leads, "unread_count": unread_count}


@app.post("/leads/seen")
def mark_leads_seen():
    db.mark_seen()
    return {"status": "ok"}


class ContactCreate(BaseModel):
    company: str = ""
    name: str = ""
    role: str = ""
    email: str
    source_type: str = ""
    source_id: str = ""


class ContactStatus(BaseModel):
    status: str


class OutreachRequest(BaseModel):
    lead_id: int | None = None
    context_note: str = ""


@app.post("/contacts")
def create_contact(body: ContactCreate):
    contact_id = db.insert_contact(
        body.company, body.name, body.role, body.email, body.source_type, body.source_id
    )
    return {"id": contact_id}


@app.get("/contacts")
def list_contacts():
    return db.get_contacts()


@app.patch("/contacts/{contact_id}/status")
def set_contact_status(contact_id: int, body: ContactStatus):
    db.update_contact_status(contact_id, body.status)
    return {"status": "ok"}


@app.post("/contacts/{contact_id}/outreach")
def send_outreach(contact_id: int, body: OutreachRequest):
    """Fully automated draft + send — no review step, per the user's explicit
    choice. Safety nets stay in place regardless: one automated email per
    contact ever (has_sent_to_contact), and a daily send cap."""
    contact = db.get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    if db.has_sent_to_contact(contact_id):
        return {"status": "skipped", "reason": "already emailed this contact"}

    cfg = load_config()
    gmail_cfg = cfg.get("gmail") or {}
    cap = gmail_cfg.get("daily_send_cap", 20)
    if db.count_sent_today() >= cap:
        return {"status": "skipped", "reason": f"daily send cap ({cap}) reached"}

    profile = db.get_profile()
    extracted = (profile or {}).get("extracted") or {}
    context = {"resume_summary": extracted.get("summary", ""), "context_note": body.context_note}
    try:
        draft = llm.draft_cold_email(
            {"company": contact["company"], "name": contact["name"], "role": contact["role"]}, context
        )
    except Exception as e:
        return {"status": "failed", "reason": f"drafting failed: {e}"}

    client_secret_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        gmail_cfg.get("client_secret_path", "client_secret.json"),
    )
    try:
        gmail.send_email(client_secret_path, contact["email"], draft["subject"], draft["body"])
    except Exception as e:
        return {"status": "failed", "reason": f"send failed: {e}"}

    db.insert_sent_email(contact_id, body.lead_id, draft["subject"], draft["body"])
    db.update_contact_status(contact_id, "sent")
    return {"status": "sent", "subject": draft["subject"], "body": draft["body"]}


@app.get("/sent-emails")
def list_sent_emails():
    return db.get_sent_emails()


class PostingUpdate(BaseModel):
    archived: bool | None = None
    pinned: bool | None = None


@app.get("/postings")
def list_postings():
    """Live, scored version of what data/postings.json + archive.json used
    to serve directly to the frontend (Phase 1 — see master plan §5). Syncs
    from those files first so a fetch_postings.py run picked up since the
    last sync (or the last profile edit, which changes scoring) is
    reflected immediately rather than waiting for the next backend restart."""
    try:
        db.sync_postings_from_json()
    except Exception:
        pass
    return db.get_postings()


@app.post("/postings/sync")
def sync_postings():
    return db.sync_postings_from_json()


@app.patch("/postings/{posting_id}")
def update_posting(posting_id: str, body: PostingUpdate):
    updated = db.update_posting(posting_id, archived=body.archived, pinned=body.pinned)
    if updated is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return updated


class WorkModeWeights(BaseModel):
    remote: float = 0.6
    hybrid: float = 0.3
    onsite: float = 0.1


@app.get("/scoring/work-mode-weights")
def get_work_mode_weights():
    return scoring.get_work_mode_weights()


@app.post("/scoring/work-mode-weights")
def save_work_mode_weights(body: WorkModeWeights):
    scoring.save_work_mode_weights(body.model_dump())
    db.sync_postings_from_json()  # re-score immediately so the change is visible without a manual refresh
    return {"status": "saved"}


@app.get("/glance")
def glance():
    """One aggregated call for the landing view — new postings, new leads,
    and outreach that's gone quiet — instead of three separate round trips."""
    return db.get_glance()


@app.post("/glance/seen-postings")
def mark_postings_seen():
    db.mark_postings_seen()
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run("app:app", host=cfg.get("host", "127.0.0.1"), port=cfg.get("port", 8420))
