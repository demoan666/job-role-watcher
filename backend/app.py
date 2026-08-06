"""FastAPI backend for the job-search command center.

Binds to 127.0.0.1 only — single-user, local-only for v1 (see plan doc).
This assumption breaks the moment this moves to a cloud VM; a real auth
token will be needed at that point, not just localhost binding.
"""

import os

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db
import gmail
import llm
import resume_parse
from config import load_config

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


@app.get("/health")
def health():
    return {"status": "ok"}


class ResumeText(BaseModel):
    resume_text: str


class ProfileSave(BaseModel):
    resume_text: str
    extracted: dict


@app.post("/profile/extract")
def extract_profile(body: ResumeText):
    """Preview only — runs the LLM extraction but does not save. The user
    reviews/edits the result client-side before POSTing it to /profile."""
    return llm.extract_resume_profile(body.resume_text)


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
    db.save_profile(body.resume_text, body.extracted)
    return {"status": "saved"}


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
