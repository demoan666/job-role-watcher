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
import enrichment
import gmail
import llm
import notify_telegram
import pipeline
import reply_check
import resume_parse
import resume_pdf
import retention
import scheduler
import scoring
import vault
from providers import enrichment as enrichment_providers
from providers import group_discovery as group_discovery_providers
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
    if scheduler.is_enabled():
        scheduler.start()


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


class LeadRetention(BaseModel):
    archived: bool | None = None
    pinned: bool | None = None
    # Review Queue's "snooze" action (decision #17) — ISO timestamp to hide
    # this lead from GET /queue until; "" clears an existing snooze.
    snoozed_until: str | None = None


@app.patch("/leads/{lead_id}/retention")
def set_lead_retention(lead_id: int, body: LeadRetention):
    db.update_lead(lead_id, archived=body.archived, pinned=body.pinned, snoozed_until=body.snoozed_until)
    return {"status": "ok"}


@app.delete("/leads/{lead_id}")
def delete_lead(lead_id: int):
    db.delete_lead(lead_id)
    return {"status": "deleted"}


@app.post("/leads/bulk-delete")
def bulk_delete_leads(body: BulkIds):
    for lead_id in body.ids:
        db.delete_lead(int(lead_id))
    return {"status": "deleted", "count": len(body.ids)}


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
    # Pre-drafted subject/body (Review Queue's "edit before send" action —
    # see draft_outreach_preview below): when both are given, send_outreach
    # skips its own LLM draft call entirely and sends exactly this text,
    # so an edit made after previewing is never silently overwritten.
    subject: str | None = None
    body: str | None = None


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
    """Also the manual "re-approach" action for a suppressed contact
    (decision #20) — set status back to not_contacted, no separate
    endpoint needed."""
    db.update_contact_status(contact_id, body.status)
    return {"status": "ok"}


class ContactRetention(BaseModel):
    archived: bool | None = None
    pinned: bool | None = None


@app.patch("/contacts/{contact_id}/retention")
def set_contact_retention(contact_id: int, body: ContactRetention):
    db.update_contact(contact_id, archived=body.archived, pinned=body.pinned)
    return {"status": "ok"}


@app.delete("/contacts/{contact_id}")
def delete_contact(contact_id: int):
    db.delete_contact(contact_id)
    return {"status": "deleted"}


@app.post("/contacts/bulk-delete")
def bulk_delete_contacts(body: BulkIds):
    for contact_id in body.ids:
        db.delete_contact(int(contact_id))
    return {"status": "deleted", "count": len(body.ids)}


def _resolve_send_context(contact, context_note):
    """Shared by send_outreach and draft_outreach_preview so a preview and
    the actual send always compute resume_text/delivery-mode the same way.
    Returns (resume_text, context, is_job_application, sending_profile)."""
    is_job_application = bool(contact.get("posting_id"))
    item_type = "posting" if is_job_application else "lead"
    sending_profile = pipeline.select_sending_profile(item_type)

    if sending_profile:
        resume_text = sending_profile.get("resume_text") or ""
        context = {
            "resume_summary": resume_text[:2000], "context_note": context_note,
            "tone": sending_profile.get("tone"), "portfolio_url": sending_profile.get("portfolio_url"),
        }
    else:
        profile = db.get_profile()
        extracted = (profile or {}).get("extracted") or {}
        resume_text = (profile or {}).get("resume_text") or ""
        context = {"resume_summary": extracted.get("summary", ""), "context_note": context_note}
    return resume_text, context, is_job_application, sending_profile


def _draft_for_contact(contact, context_note):
    """Runs the LLM draft + signature append — the part of send_outreach
    that draft_outreach_preview also needs, without sending anything."""
    resume_text, context, is_job_application, sending_profile = _resolve_send_context(contact, context_note)
    draft = llm.draft_cold_email(
        {"company": contact["company"], "name": contact["name"], "role": contact["role"]}, context
    )
    if sending_profile and sending_profile.get("signature"):
        draft["body"] = draft["body"].rstrip() + "\n\n" + sending_profile["signature"]
    return draft, resume_text, is_job_application


@app.post("/contacts/{contact_id}/draft-preview")
def draft_outreach_preview(contact_id: int, body: OutreachRequest):
    """Review Queue's "edit message before send" action (plan decision #17)
    — added as an explicit, minimal exception to this pass's "wire existing
    routes only" scope, since no route previously separated drafting from
    sending. Runs the same LLM draft (and costs the same tokens) send_outreach
    would, but never sends or touches sent_emails/contact status — the
    frontend shows the result in an editable textarea, then POSTs the
    (possibly edited) subject/body back to /contacts/{id}/outreach."""
    contact = db.get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    try:
        draft, _, _ = _draft_for_contact(contact, body.context_note)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"drafting failed: {e}")
    return draft


@app.post("/contacts/{contact_id}/outreach")
def send_outreach(contact_id: int, body: OutreachRequest):
    """Fully automated draft + send — no review step, per the user's explicit
    choice. Safety nets stay in place regardless: one automated email per
    contact ever (has_sent_to_contact), and a daily send cap — now the lower
    of the legacy per-integration gmail cap and the pipeline-wide daily quota
    (decision #15), since both a job-application and a cold-outreach send
    now go through this same path (plan §2: "both terminate in the same
    action"). Generalized for Phase 3: picks a sending-profile alias
    (decision #23) when any have been configured, and honors the configured
    resume-delivery mode (HTML body / PDF attachment / both — decision
    #21), falling back to the pre-Phase-3 behavior (single legacy profile,
    HTML-only) when no sending profiles exist yet.

    body.subject/body.body (Review Queue's "edit before send"): when both
    are given, this skips its own draft call entirely and sends exactly
    that text — see draft_outreach_preview above."""
    contact = db.get_contact(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    if db.has_sent_to_contact(contact_id):
        return {"status": "skipped", "reason": "already emailed this contact"}

    cfg = load_config()
    gmail_cfg = cfg.get("gmail") or {}
    gmail_cap = gmail_cfg.get("daily_send_cap", 20)
    pipeline_settings = pipeline.get_pipeline_settings()
    cap = min(gmail_cap, pipeline_settings["daily_quota"])
    if db.count_sent_today() >= cap:
        return {"status": "skipped", "reason": f"daily send cap ({cap}) reached"}

    if body.subject and body.body:
        draft = {"subject": body.subject, "body": body.body}
        resume_text, _, is_job_application, _ = _resolve_send_context(contact, body.context_note)
    else:
        try:
            draft, resume_text, is_job_application = _draft_for_contact(contact, body.context_note)
        except Exception as e:
            return {"status": "failed", "reason": f"drafting failed: {e}"}

    if db.get_setting("dry_run_mode", "false") == "true":
        # Plan Phase 7, flagged as "recommended, not yet confirmed" (Open
        # Risk #6): simulates the full pipeline without an actual send —
        # deliberately does NOT call insert_sent_email/update_contact_status,
        # so a dry run never consumes the one-send-per-contact guarantee.
        return {"status": "dry_run", "subject": draft["subject"], "body": draft["body"]}

    delivery_key = "job_application" if is_job_application else "cold_intro"
    delivery_mode = pipeline_settings["resume_delivery"].get(delivery_key, "html")
    attachment_path = None
    try:
        if delivery_mode in ("pdf", "both") and resume_text:
            attachment_path = resume_pdf.render_resume_pdf(resume_text)

        client_secret_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            gmail_cfg.get("client_secret_path", "client_secret.json"),
        )
        try:
            gmail.send_email(
                client_secret_path, contact["email"], draft["subject"], draft["body"],
                attachment_path=attachment_path,
            )
        except Exception as e:
            return {"status": "failed", "reason": f"send failed: {e}"}
    finally:
        if attachment_path and os.path.exists(attachment_path):
            os.remove(attachment_path)

    db.insert_sent_email(contact_id, body.lead_id, draft["subject"], draft["body"])
    db.update_contact_status(contact_id, "sent")
    return {"status": "sent", "subject": draft["subject"], "body": draft["body"]}


class SendingProfileSave(BaseModel):
    name: str
    resume_text: str = ""
    portfolio_url: str = ""
    tone: str = ""
    signature: str = ""
    is_default: bool = False


@app.get("/sending-profiles")
def list_sending_profiles():
    return db.list_sending_profiles()


@app.post("/sending-profiles")
def create_sending_profile(body: SendingProfileSave):
    profile_id = db.create_sending_profile(
        body.name, body.resume_text, body.portfolio_url, body.tone, body.signature, body.is_default
    )
    return {"id": profile_id}


@app.patch("/sending-profiles/{profile_id}")
def update_sending_profile(profile_id: int, body: SendingProfileSave):
    db.update_sending_profile(profile_id, **body.model_dump())
    return {"status": "saved"}


@app.delete("/sending-profiles/{profile_id}")
def delete_sending_profile(profile_id: int):
    db.delete_sending_profile(profile_id)
    return {"status": "deleted"}


class PipelineSettingsSave(BaseModel):
    daily_quota: int | None = None
    split_ratio: dict[str, float] | None = None
    resume_delivery: dict[str, str] | None = None


@app.get("/settings/pipeline")
def get_pipeline_settings():
    return pipeline.get_pipeline_settings()


@app.post("/settings/pipeline")
def save_pipeline_settings(body: PipelineSettingsSave):
    pipeline.save_pipeline_settings(
        daily_quota=body.daily_quota, split_ratio=body.split_ratio, resume_delivery=body.resume_delivery
    )
    return {"status": "saved"}


@app.get("/queue")
def get_queue():
    """Unified review queue (Phase 3, plan §2: postings and leads "share one
    contact-resolution step, one send engine, and one ledger") — scored
    postings that already have a resolved contact, merged with real leads,
    capped by the daily quota and postings/leads split ratio."""
    return {"items": pipeline.get_queue()}


@app.get("/sent-emails")
def list_sent_emails():
    return db.get_sent_emails()


class PostingUpdate(BaseModel):
    archived: bool | None = None
    pinned: bool | None = None
    # Review Queue's "snooze" action (decision #17) — ISO timestamp to hide
    # this posting from GET /queue until; "" clears an existing snooze.
    snoozed_until: str | None = None


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
    updated = db.update_posting(posting_id, archived=body.archived, pinned=body.pinned, snoozed_until=body.snoozed_until)
    if updated is None:
        raise HTTPException(status_code=404, detail="posting not found")
    return updated


@app.delete("/postings/{posting_id}")
def delete_posting(posting_id: str):
    db.delete_posting(posting_id)
    return {"status": "deleted"}


class BulkIds(BaseModel):
    ids: list[str]


@app.post("/postings/bulk-delete")
def bulk_delete_postings(body: BulkIds):
    for posting_id in body.ids:
        db.delete_posting(posting_id)
    return {"status": "deleted", "count": len(body.ids)}


class RetentionSettings(BaseModel):
    retention_days: int


@app.get("/settings/retention")
def get_retention_settings():
    return {"retention_days": retention.get_retention_days()}


@app.post("/settings/retention")
def save_retention_settings(body: RetentionSettings):
    retention.save_retention_days(body.retention_days)
    return {"status": "saved"}


@app.post("/retention/sweep")
def run_retention_sweep():
    return retention.sweep()


@app.get("/export")
def export_data():
    return db.export_all_data()


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


@app.post("/postings/{posting_id}/enrich")
def enrich_posting(posting_id: str):
    """Runs the contact-resolution chain for a posting's company (Phase 2)
    and inserts any newly-found contacts, skipping ones already known for
    this (company, email) pair (decision #13). Returns both the newly
    inserted contacts and how many were skipped as already-known."""
    posting = db.get_posting(posting_id)
    if not posting:
        raise HTTPException(status_code=404, detail="posting not found")

    found = enrichment.enrich_company(posting["company"], posting["url"], industry=posting.get("cluster"))
    inserted = []
    skipped = 0
    for contact in found:
        if db.contact_exists(posting["company"], contact.get("email")):
            skipped += 1
            continue
        contact_id = db.insert_contact(
            posting["company"], contact.get("name"), contact.get("role"), contact.get("email"),
            source_type="enrichment:" + contact.get("source", "unknown"), source_id=posting_id,
            tier=contact.get("tier"), posting_id=posting_id,
        )
        inserted.append(dict(contact, id=contact_id))
    return {"inserted": inserted, "skipped_existing": skipped}


class DecisionMakerTitles(BaseModel):
    titles: list[str]


class SizeThresholds(BaseModel):
    small_max: int
    large_min: int


class EnrichmentProviderOrder(BaseModel):
    order: list[str]
    industry: str | None = None


@app.get("/settings/enrichment")
def get_enrichment_settings():
    return {
        "decision_maker_titles": enrichment.get_decision_maker_titles(),
        "size_thresholds": enrichment.get_size_thresholds(),
        "provider_order": enrichment.get_provider_order(),
        "available_providers": list(enrichment_providers.REGISTRY.keys()),
    }


@app.post("/settings/enrichment/decision-maker-titles")
def save_decision_maker_titles(body: DecisionMakerTitles):
    enrichment.save_decision_maker_titles(body.titles)
    return {"status": "saved"}


@app.post("/settings/enrichment/size-thresholds")
def save_size_thresholds(body: SizeThresholds):
    enrichment.save_size_thresholds({"small_max": body.small_max, "large_min": body.large_min})
    return {"status": "saved"}


@app.post("/settings/enrichment/provider-order")
def save_provider_order(body: EnrichmentProviderOrder):
    enrichment.save_provider_order(body.order, industry=body.industry)
    return {"status": "saved"}


class SchedulerSettings(BaseModel):
    enabled: bool
    mode: str = "daily"
    times_per_day: int = 1
    every_n_days: int = 1


@app.get("/settings/scheduler")
def get_scheduler_settings():
    return {
        "enabled": scheduler.is_enabled(),
        **scheduler.get_cadence_settings(),
        "last_run_at": db.get_setting("scheduler_last_run_at"),
    }


@app.post("/settings/scheduler")
def save_scheduler_settings(body: SchedulerSettings):
    """Toggling this on runs real enrichment scrapes and sends a real
    Telegram message on a timer (see scheduler.py's module docstring) —
    it's opt-in via this route, never auto-started just because the backend
    booted, unless a previous session already enabled it."""
    scheduler.set_enabled(body.enabled)
    scheduler.save_cadence_settings(body.mode, body.times_per_day, body.every_n_days)
    if body.enabled:
        scheduler.start()
        scheduler.reschedule()
    else:
        scheduler.stop()
    return {"status": "saved"}


@app.post("/scheduler/run-now")
def run_scheduler_now():
    return scheduler.run_daily_batch()


class NotificationSettings(BaseModel):
    telegram_chat: str


@app.get("/settings/notifications")
def get_notification_settings():
    """Decision #27's notification target — previously config.json-only
    (telegram.notify_chat), given a real settings field per this pass's
    explicit ask. See notify_telegram.get_notify_target for the
    DB-setting-first/config.json-fallback precedence."""
    return {"telegram_chat": notify_telegram.get_notify_target()}


@app.post("/settings/notifications")
def save_notification_settings(body: NotificationSettings):
    notify_telegram.save_notify_target(body.telegram_chat.strip())
    return {"status": "saved"}


@app.post("/reply-check/run")
def run_reply_check():
    """Manual trigger for Phase 5's reply loop (decision #19) — also run as
    part of the scheduled daily batch when the scheduler is enabled (see
    scheduler.run_daily_batch)."""
    return reply_check.check_all_replies()


class GroupDiscoveryScan(BaseModel):
    keyword: str
    providers: list[str] = ["telegram_directory", "discord_directory"]


@app.post("/group-discovery/scan")
def scan_group_discovery(body: GroupDiscoveryScan):
    """Discovery only (decision #9) — never joins anything. Results are
    stored for manual review; the WhatsApp/Slack quick-capture box in the
    Leads tab remains the only path for those two (no public directory
    exists for either)."""
    if not body.keyword.strip():
        raise HTTPException(status_code=400, detail="keyword is required")
    found = []
    for provider_id in body.providers:
        provider = group_discovery_providers.get_provider(provider_id)
        if not provider:
            continue
        try:
            results = provider.search(body.keyword.strip())
        except Exception:
            results = []
        for r in results:
            r["keyword"] = body.keyword.strip()
        found.extend(results)
    inserted = db.insert_discovered_channels(found)
    return {"found": len(found), "inserted": inserted}


@app.get("/group-discovery/channels")
def list_discovered_channels():
    return db.get_discovered_channels()


class DiscoveredChannelStatus(BaseModel):
    status: str


@app.patch("/group-discovery/channels/{channel_id}")
def update_discovered_channel(channel_id: int, body: DiscoveredChannelStatus):
    db.update_discovered_channel_status(channel_id, body.status)
    return {"status": "ok"}


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
