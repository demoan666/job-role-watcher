"""Unified send pipeline (plan Phase 3): merges scored postings + leads into
one review-ready queue, auto-selects a sending-profile alias per item
(decision #23), and centralizes the daily-quota / job-vs-outreach split
settings (decisions #10/#15) that both the postings and leads send paths
now share.
"""

import json

import db


def get_pipeline_settings():
    quota = int(db.get_setting("pipeline_daily_quota", "10"))
    split_raw = db.get_setting("pipeline_split_ratio")
    split = json.loads(split_raw) if split_raw else {"postings": 0.5, "leads": 0.5}
    delivery_raw = db.get_setting("pipeline_resume_delivery")
    resume_delivery = json.loads(delivery_raw) if delivery_raw else {
        "cold_intro": "html", "job_application": "pdf",
    }
    return {"daily_quota": quota, "split_ratio": split, "resume_delivery": resume_delivery}


def save_pipeline_settings(daily_quota=None, split_ratio=None, resume_delivery=None):
    if daily_quota is not None:
        db.set_setting("pipeline_daily_quota", str(daily_quota))
    if split_ratio is not None:
        db.set_setting("pipeline_split_ratio", json.dumps(split_ratio, ensure_ascii=False))
    if resume_delivery is not None:
        db.set_setting("pipeline_resume_delivery", json.dumps(resume_delivery, ensure_ascii=False))


def select_sending_profile(item_type, is_freelance_shaped=False):
    """Rule-based default (decision #23): Studio for freelance/project-shaped
    leads if one is defined, else Individual; job applications default to
    Individual. Always overridable per item by the caller (this is just the
    default suggestion, not an enforced choice). Returns None if no sending
    profiles have been created yet — callers fall back to the single legacy
    `profile` table's extracted summary, same as before Phase 3."""
    profiles = db.list_sending_profiles()
    if not profiles:
        return None
    by_name = {p["name"].strip().lower(): p for p in profiles}
    if item_type == "lead" and is_freelance_shaped and "studio" in by_name:
        return by_name["studio"]
    if "individual" in by_name:
        return by_name["individual"]
    return next((p for p in profiles if p["is_default"]), profiles[0])


def _not_snoozed(record):
    """Review Queue's "snooze" action (decision #17) — a snoozed_until in
    the future hides the item from the queue without touching archived
    (Search Results / the postings list are unaffected — see
    backend/db.py's schema note on this column)."""
    snoozed_until = record.get("snoozed_until")
    return not snoozed_until or snoozed_until <= db.now_iso()


def get_queue(limit=None):
    """Merges top-scored active postings that already have a resolved
    contact with leads flagged as real opportunities, applying the daily
    quota + postings/leads split ratio. Read-only — doesn't itself consume
    quota or mark anything as sent; that happens at actual send time via the
    existing per-contact dedup + daily cap checks."""
    settings = get_pipeline_settings()
    quota = settings["daily_quota"]
    split = settings["split_ratio"]
    posting_slots = round(quota * split.get("postings", 0.5))
    lead_slots = max(0, quota - posting_slots)

    posting_items = []
    for posting in db.get_postings()["active"]:
        if not _not_snoozed(posting):
            continue
        contacts = db.get_contacts_for_posting(posting["id"])
        if not contacts:
            continue
        posting_items.append({
            "type": "posting", "posting": posting, "contact": contacts[0],
            "score": posting.get("score") or 0,
        })
    posting_items.sort(key=lambda item: item["score"], reverse=True)

    lead_items = [
        {"type": "lead", "lead": lead, "score": None}
        for lead in db.get_leads() if lead.get("is_opportunity") and _not_snoozed(lead)
    ]

    return (posting_items[:posting_slots] + lead_items[:lead_slots])[:limit] if limit else \
        posting_items[:posting_slots] + lead_items[:lead_slots]
