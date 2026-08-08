"""SQLite schema and access helpers for the job-search backend.

Single-user, local file DB. Schema covers all four modes up front
(profile, contacts, leads, sent_emails, settings) so later phases don't
need migrations — most tables just stay empty until their phase lands.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BACKEND_DIR)
DB_PATH = os.path.join(BACKEND_DIR, "app.db")
SEARCH_PROFILE_PATH = os.path.join(REPO_ROOT, "data", "search_profile.json")
SEARCH_SCOPE_PATH = os.path.join(REPO_ROOT, "data", "search_scope.json")
COMPANIES_PATH = os.path.join(REPO_ROOT, "data", "companies.json")
POSTINGS_PATH = os.path.join(REPO_ROOT, "data", "postings.json")
ARCHIVE_PATH = os.path.join(REPO_ROOT, "data", "archive.json")
STALE_OUTREACH_DAYS = 7
ALL_ATS = ["greenhouse", "lever", "smartrecruiters"]
ALL_CONTRACT_MODES = ["full-time", "contract", "freelance", "internship"]

# Verbatim from DOCS/role_search.md — the 3 clusters already established there
# (have manual tracker entries; only the first has any companies.json/ATS
# coverage) plus the 26 clusters listed under "Industry Clusters Not Yet
# Swept" (which itself already reconciled the naming overlap between
# research_brief.md's raw list and the established clusters — e.g.
# "Cybersecurity" is kept distinct from "Enterprise Software / SaaS /
# Fintech / B2B Tech"). Keep this in sync with role_search.md by hand if
# that file's cluster list changes — don't let it silently drift.
ALL_INDUSTRIES = [
    "Enterprise Software / SaaS / Fintech / B2B Tech",
    "Nordic Industrial / Energy / Pharma",
    "DACH / Benelux Large Enterprise",
    "Pharma & biotech",
    "HR/PEO/workforce platforms",
    "Industrial machinery (general)",
    "Medical equipment manufacturers",
    "Machine tools manufacturers",
    "Elevators & escalators",
    "Robotics & industrial automation",
    "Mining & construction equipment",
    "Agricultural machinery",
    "Print/packaging machinery",
    "Textile machinery",
    "Test/measurement/scientific instruments",
    "Process industries/chemicals/materials",
    "Aerospace & defense",
    "Maritime/shipbuilding + classification societies",
    "Rail & mobility infrastructure",
    "Cybersecurity (separate from general enterprise SaaS above)",
    "Flavors/fragrances/food ingredients",
    "Testing/certification/compliance",
    "Data center/power infrastructure",
    "Insurance & reinsurance",
    "Water & environmental tech",
    "Medical devices/diagnostics/dental",
    "Renewable energy & utilities (beyond Ørsted)",
    "Staffing & workforce solutions",
    "Semiconductor equipment (beyond ASML)",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  resume_text TEXT,
  extracted_json TEXT,
  manual_tags_json TEXT DEFAULT '[]',
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company TEXT,
  name TEXT,
  role TEXT,
  email TEXT,
  source_type TEXT,
  source_id TEXT,
  status TEXT NOT NULL DEFAULT 'not_contacted',
  tier TEXT,
  posting_id TEXT REFERENCES postings(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_channel TEXT,
  author TEXT,
  raw_text TEXT NOT NULL,
  is_opportunity INTEGER,
  point_of_contact TEXT,
  triage_json TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sent_emails (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact_id INTEGER NOT NULL REFERENCES contacts(id),
  lead_id INTEGER REFERENCES leads(id),
  subject TEXT,
  body TEXT,
  sent_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  estimated_cost_usd REAL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovered_channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  description TEXT,
  source TEXT NOT NULL,
  keyword TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  discovered_at TEXT NOT NULL,
  UNIQUE(url)
);

CREATE TABLE IF NOT EXISTS sending_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  resume_text TEXT,
  portfolio_url TEXT,
  tone TEXT,
  signature TEXT,
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS postings (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  cluster TEXT,
  title TEXT NOT NULL,
  location TEXT,
  remote INTEGER NOT NULL DEFAULT 0,
  eu_hireable_or_remote INTEGER NOT NULL DEFAULT 0,
  url TEXT,
  ats TEXT,
  contract_type TEXT,
  first_seen TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  closed_date TEXT,
  score REAL,
  score_breakdown_json TEXT,
  work_mode_tag TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  pinned INTEGER NOT NULL DEFAULT 0,
  synced_at TEXT NOT NULL
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        try:
            conn.execute("ALTER TABLE profile ADD COLUMN manual_tags_json TEXT DEFAULT '[]'")
        except sqlite3.OperationalError:
            pass  # column already exists (pre-existing DB file from before this field was added)
        for stmt in [
            "ALTER TABLE contacts ADD COLUMN tier TEXT",
            "ALTER TABLE contacts ADD COLUMN posting_id TEXT REFERENCES postings(id)",
            "ALTER TABLE contacts ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE contacts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN archived INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE leads ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0",
            # snoozed_until (Review Queue's "snooze" action): an ISO timestamp
            # a posting/lead is hidden from pipeline.get_queue() until, per
            # decision #17 ("snooze doesn't burn a quota slot"). Explicit,
            # minimal exception to the "wire existing routes only" scope for
            # this pass — nothing else previously modeled a snooze concept.
            "ALTER TABLE postings ADD COLUMN snoozed_until TEXT",
            "ALTER TABLE leads ADD COLUMN snoozed_until TEXT",
        ]:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists on a pre-existing DB file
        conn.commit()
    finally:
        conn.close()


def get_setting(key, default=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key, value):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def get_profile():
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT resume_text, extracted_json, manual_tags_json, updated_at FROM profile WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        return {
            "resume_text": row["resume_text"],
            "extracted": json.loads(row["extracted_json"]) if row["extracted_json"] else None,
            "manual_tags": json.loads(row["manual_tags_json"]) if row["manual_tags_json"] else [],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


def save_profile(resume_text, extracted, manual_tags=None):
    manual_tags = manual_tags or []
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO profile (id, resume_text, extracted_json, manual_tags_json, updated_at) "
            "VALUES (1, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET resume_text = excluded.resume_text, "
            "extracted_json = excluded.extracted_json, manual_tags_json = excluded.manual_tags_json, "
            "updated_at = excluded.updated_at",
            (resume_text, json.dumps(extracted, ensure_ascii=False),
             json.dumps(manual_tags, ensure_ascii=False), now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    export_search_profile(extracted, manual_tags)


def export_search_profile(extracted, manual_tags=None):
    """Writes the derived keywords/industries (not raw resume text) to the
    committed data/ dir so fetch_postings.py (run by GitHub Actions, no
    access to this local DB) can read them. Deliberately excludes resume
    text/summary/skills — this repo is public; only the matching-relevant
    fields belong in it.

    manual_tags are user-added (not LLM-extracted) and are unioned into the
    exported keywords so they immediately affect posting matching without
    requiring a resume re-extraction — case-insensitive dedup, first-seen
    casing wins.
    """
    os.makedirs(os.path.dirname(SEARCH_PROFILE_PATH), exist_ok=True)
    keywords = list(extracted.get("keywords", []))
    seen_lower = {kw.lower() for kw in keywords}
    for tag in (manual_tags or []):
        if tag.lower() not in seen_lower:
            keywords.append(tag)
            seen_lower.add(tag.lower())
    payload = {
        "keywords": keywords,
        "industries": extracted.get("industries", []),
        "updated_at": now_iso(),
    }
    with open(SEARCH_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_scope():
    return {
        "active_ats": json.loads(get_setting("scope_active_ats", "null") or "null") or ALL_ATS,
        "contract_modes": json.loads(get_setting("scope_contract_modes", "null") or "null") or ALL_CONTRACT_MODES,
        # industries/countries default to [] (not "everything"), unlike
        # active_ats/contract_modes above — an empty list here means "no
        # preference recorded yet / no restriction", not "all 29 industries"
        # or "all ~195 countries". fetch_postings.py treats an empty/absent
        # countries list as "fall back to the existing hardcoded allowlist".
        "industries": json.loads(get_setting("scope_industries", "null") or "null") or [],
        "countries": json.loads(get_setting("scope_countries", "null") or "null") or [],
    }


def save_scope(active_ats, contract_modes, companies, industries=None, countries=None):
    """Persists ATS/contract-mode/industry/country toggles to settings +
    exports search_scope.json, and rewrites companies.json's `enabled`
    flags in place (matched by name) — never touches ats/slug/cluster
    fields, those stay hand-verified per app_build_spec.md's rule against
    guessed slugs.
    """
    industries = industries or []
    countries = countries or []
    set_setting("scope_active_ats", json.dumps(active_ats, ensure_ascii=False))
    set_setting("scope_contract_modes", json.dumps(contract_modes, ensure_ascii=False))
    set_setting("scope_industries", json.dumps(industries, ensure_ascii=False))
    set_setting("scope_countries", json.dumps(countries, ensure_ascii=False))

    os.makedirs(os.path.dirname(SEARCH_SCOPE_PATH), exist_ok=True)
    with open(SEARCH_SCOPE_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "active_ats": active_ats,
                "contract_modes": contract_modes,
                "industries": industries,
                "countries": countries,
                "updated_at": now_iso(),
            },
            f, indent=2, ensure_ascii=False,
        )
        f.write("\n")

    if companies is not None and os.path.exists(COMPANIES_PATH):
        with open(COMPANIES_PATH, "r", encoding="utf-8") as f:
            existing = json.load(f)
        enabled_by_name = {c["name"]: c.get("enabled", True) for c in companies}
        for entry in existing:
            if entry["name"] in enabled_by_name:
                entry["enabled"] = enabled_by_name[entry["name"]]
        with open(COMPANIES_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
            f.write("\n")


def list_scope_presets():
    return json.loads(get_setting("scope_presets", "[]") or "[]")


def save_scope_preset(name):
    """Snapshots the currently *saved* live scope (not a client-sent payload)
    under a new name, so there's no race with the frontend's debounced scope
    autosave. Deliberately excludes the company enable/disable toggles — see
    apply_scope_preset."""
    scope = get_scope()
    preset = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "active_ats": scope["active_ats"],
        "contract_modes": scope["contract_modes"],
        "industries": scope["industries"],
        "countries": scope["countries"],
        "created_at": now_iso(),
    }
    presets = list_scope_presets()
    presets.append(preset)
    set_setting("scope_presets", json.dumps(presets, ensure_ascii=False))
    return preset


def delete_scope_preset(preset_id):
    presets = [p for p in list_scope_presets() if p["id"] != preset_id]
    set_setting("scope_presets", json.dumps(presets, ensure_ascii=False))


def apply_scope_preset(preset_id):
    """Restores a saved preset as the new live scope. companies=None so
    save_scope() leaves company enable/disable toggles exactly as they are —
    a preset is a "search criteria" snapshot, not a fetch-infra one."""
    preset = next((p for p in list_scope_presets() if p["id"] == preset_id), None)
    if not preset:
        return None
    save_scope(
        preset["active_ats"], preset["contract_modes"], companies=None,
        industries=preset["industries"], countries=preset["countries"],
    )
    return get_scope()


def insert_lead(source, source_channel, author, raw_text, triage):
    """triage is the dict from llm.triage_message (or None if triage failed —
    stored untriaged rather than dropped, since a missed opportunity is worse
    than a noisy one)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO leads (source, source_channel, author, raw_text, is_opportunity, "
            "point_of_contact, triage_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source, source_channel, author, raw_text,
                int(triage["is_opportunity"]) if triage else None,
                triage.get("point_of_contact") if triage else None,
                json.dumps(triage, ensure_ascii=False) if triage else None,
                now_iso(),
            ),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


def get_leads(limit=200):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_last_seen(key="leads_last_seen_at"):
    return get_setting(key, None)


def mark_seen(key="leads_last_seen_at"):
    set_setting(key, now_iso())


def insert_contact(company, name, role, email, source_type, source_id, tier=None, posting_id=None):
    conn = get_connection()
    try:
        ts = now_iso()
        conn.execute(
            "INSERT INTO contacts (company, name, role, email, source_type, source_id, "
            "status, tier, posting_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'not_contacted', ?, ?, ?, ?)",
            (company, name, role, email, source_type, source_id, tier, posting_id, ts, ts),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


def contact_exists(company, email):
    """Dedup rule (decision #13): block on (company, specific contact
    person) pair, keyed here by (company, email) since email is the stable
    per-person identifier the pipeline actually has. A new named person or a
    materially different email at the same company is a legitimate new
    contact, not a duplicate."""
    if not email:
        return False
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM contacts WHERE company = ? AND email = ? LIMIT 1", (company, email)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def get_contacts():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM contacts ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_contact(contact_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_contact_status(contact_id, status):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE contacts SET status = ?, updated_at = ? WHERE id = ?",
            (status, now_iso(), contact_id),
        )
        conn.commit()
    finally:
        conn.close()


def has_sent_to_contact(contact_id):
    """Dedup rule: at most one automated outreach email per contact, ever.
    A contact needing genuine follow-up is a manual reply in the user's own
    Gmail, not another automated send."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM sent_emails WHERE contact_id = ? LIMIT 1", (contact_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def count_sent_today():
    conn = get_connection()
    try:
        today = now_iso()[:10]
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sent_emails WHERE substr(sent_at, 1, 10) = ?", (today,)
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


def insert_sent_email(contact_id, lead_id, subject, body):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sent_emails (contact_id, lead_id, subject, body, sent_at) VALUES (?, ?, ?, ?, ?)",
            (contact_id, lead_id, subject, body, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_sent_emails():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM sent_emails ORDER BY sent_at DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_stale_outreach(days=STALE_OUTREACH_DAYS):
    """Contacts sent to and not marked otherwise (replied/etc via the manual
    status endpoint) after `days` — there's no Gmail inbox read integration
    (only gmail.send scope), so "no reply" is inferred from the status
    never having been updated past 'sent', not from actually checking replies."""
    conn = get_connection()
    try:
        cutoff = (datetime.now(timezone.utc).timestamp() - days * 86400)
        rows = conn.execute("SELECT * FROM contacts WHERE status = 'sent'").fetchall()
        stale = []
        for row in rows:
            updated_ts = datetime.fromisoformat(row["updated_at"]).timestamp()
            if updated_ts <= cutoff:
                stale.append(dict(row))
        return stale
    finally:
        conn.close()


def get_glance():
    postings = []
    if os.path.exists(POSTINGS_PATH):
        with open(POSTINGS_PATH, "r", encoding="utf-8") as f:
            postings = json.load(f)
    postings_last_seen = get_setting("postings_last_seen_at")
    new_postings_count = sum(
        1 for p in postings if not postings_last_seen or p.get("first_seen", "") > postings_last_seen
    )

    leads = get_leads()
    leads_last_seen = get_last_seen()
    new_leads_count = sum(
        1 for lead in leads if not leads_last_seen or lead["created_at"] > leads_last_seen
    )

    return {
        "new_postings_count": new_postings_count,
        "total_postings_count": len(postings),
        "new_leads_count": new_leads_count,
        "stale_outreach": get_stale_outreach(),
    }


def mark_postings_seen():
    set_setting("postings_last_seen_at", now_iso())


def get_monthly_llm_cost():
    """Sum of estimated_cost_usd for calls in the current calendar month —
    None-priced calls (see log_llm_usage's docstring) are excluded from the
    sum, same convention as get_llm_usage_summary. Backs the optional
    monthly spend cap (plan Phase 7, flagged as "recommended, not yet
    confirmed" — default cap is 0/disabled so this is a no-op until a user
    explicitly sets one)."""
    conn = get_connection()
    try:
        month = now_iso()[:7]
        rows = conn.execute(
            "SELECT estimated_cost_usd FROM llm_usage WHERE substr(created_at, 1, 7) = ? "
            "AND estimated_cost_usd IS NOT NULL",
            (month,),
        ).fetchall()
        return sum(r["estimated_cost_usd"] for r in rows)
    finally:
        conn.close()


def log_llm_usage(task, provider, model, input_tokens, output_tokens, estimated_cost_usd):
    """estimated_cost_usd is None when llm.py has no verified per-token pricing
    for this provider/model — token counts (real, from the provider's own
    response) are still logged so usage is visible even before pricing exists."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO llm_usage (task, provider, model, input_tokens, output_tokens, "
            "estimated_cost_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task, provider, model, input_tokens, output_tokens, estimated_cost_usd, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_llm_usage_summary(since=None):
    """Returns {"today": W, "week": W, "all_time": W, "session": W or absent},
    each W = {"summary": {...}, "by_provider": {provider_id: {...}}}. Each
    stats dict has calls/input_tokens/output_tokens (always real counts) and
    estimated_cost_usd (None if every call in that window used a provider/
    model with no known pricing — distinct from a real $0) plus
    cost_unavailable_calls, the count of calls excluded from the cost total
    for that reason. "session" is only included when `since` (an ISO
    timestamp — the frontend passes its own page-load time) is given, since
    there's no server-side session concept in this single-user local app."""
    conn = get_connection()
    try:
        def summarize(where_sql, params):
            rows = conn.execute(
                f"SELECT provider, input_tokens, output_tokens, estimated_cost_usd FROM llm_usage {where_sql}",
                params,
            ).fetchall()

            def stats_for(rows):
                priced = [r for r in rows if r["estimated_cost_usd"] is not None]
                return {
                    "calls": len(rows),
                    "input_tokens": sum(r["input_tokens"] for r in rows),
                    "output_tokens": sum(r["output_tokens"] for r in rows),
                    "estimated_cost_usd": sum(r["estimated_cost_usd"] for r in priced) if priced else None,
                    "cost_unavailable_calls": len(rows) - len(priced),
                }

            by_provider = {}
            for provider in {r["provider"] for r in rows}:
                by_provider[provider] = stats_for([r for r in rows if r["provider"] == provider])
            return {"summary": stats_for(rows), "by_provider": by_provider}

        now = now_iso()
        today = now[:10]
        week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")

        result = {
            "today": summarize("WHERE substr(created_at, 1, 10) = ?", (today,)),
            "week": summarize("WHERE created_at >= ?", (week_cutoff,)),
            "all_time": summarize("", ()),
        }
        if since:
            result["session"] = summarize("WHERE created_at >= ?", (since,))
        return result
    finally:
        conn.close()


def sync_postings_from_json():
    """Upserts data/postings.json (active) + data/archive.json (closed) into
    the postings table, scoring each against the current profile (plan
    Phase 1). Cheap enough to just re-run in full rather than diff — scoring
    is a pure function of (posting, profile, work-mode weights), and
    archived/pinned (user-set retention flags, not present in the source
    JSON) are deliberately left out of the UPDATE clause below so a re-sync
    never clobbers them; new rows get their schema default of 0."""
    import scoring  # local import — avoids a circular import at module load

    profile = get_profile() or {}
    extracted = profile.get("extracted") or {}
    keywords = extracted.get("keywords", [])
    industries = extracted.get("industries", [])
    weights = scoring.get_work_mode_weights()

    active = load_json_list(POSTINGS_PATH)
    archived = load_json_list(ARCHIVE_PATH)

    conn = get_connection()
    try:
        synced = 0
        for posting, status in [(p, "active") for p in active] + [(p, "closed") for p in archived]:
            score, breakdown = scoring.score_posting(posting, keywords, industries, weights)
            conn.execute(
                "INSERT INTO postings (id, company, cluster, title, location, remote, "
                "eu_hireable_or_remote, url, ats, contract_type, first_seen, status, closed_date, "
                "score, score_breakdown_json, work_mode_tag, synced_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET company=excluded.company, cluster=excluded.cluster, "
                "title=excluded.title, location=excluded.location, remote=excluded.remote, "
                "eu_hireable_or_remote=excluded.eu_hireable_or_remote, url=excluded.url, ats=excluded.ats, "
                "contract_type=excluded.contract_type, first_seen=excluded.first_seen, status=excluded.status, "
                "closed_date=excluded.closed_date, score=excluded.score, "
                "score_breakdown_json=excluded.score_breakdown_json, work_mode_tag=excluded.work_mode_tag, "
                "synced_at=excluded.synced_at",
                (
                    posting["id"], posting.get("company"), posting.get("cluster"), posting.get("title"),
                    posting.get("location"), int(bool(posting.get("remote"))),
                    int(bool(posting.get("eu_hireable_or_remote"))), posting.get("url"), posting.get("ats"),
                    posting.get("contract_type"), posting.get("first_seen"), status, posting.get("closed_date"),
                    score, json.dumps(breakdown, ensure_ascii=False), breakdown["work_mode_tag"], now_iso(),
                ),
            )
            synced += 1
        conn.commit()
        return {"synced": synced}
    finally:
        conn.close()


def load_json_list(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _posting_row_to_dict(row):
    d = dict(row)
    d["remote"] = bool(d["remote"])
    d["eu_hireable_or_remote"] = bool(d["eu_hireable_or_remote"])
    d["archived"] = bool(d["archived"])
    d["pinned"] = bool(d["pinned"])
    d["score_breakdown"] = json.loads(d.pop("score_breakdown_json")) if d.get("score_breakdown_json") else None
    return d


def get_postings():
    """Returns {"active": [...], "archive": [...]} — same two-list shape the
    frontend already renders from data/postings.json + archive.json
    (backend/CLAUDE.md's Search Results tab), plus extra score/work_mode_tag/
    archived/pinned fields the existing renderer just ignores."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM postings WHERE archived = 0 ORDER BY score DESC"
        ).fetchall()
        active = [_posting_row_to_dict(r) for r in rows if r["status"] == "active"]
        closed = [_posting_row_to_dict(r) for r in rows if r["status"] == "closed"]
        return {"active": active, "archive": closed}
    finally:
        conn.close()


def insert_discovered_channels(channels):
    """Idempotent on url (UNIQUE constraint) — re-running a scan over the
    same keyword just no-ops on channels already known, per decision #9's
    "discovery only" framing: this never joins anything, it only accumulates
    a review list. Returns how many were newly inserted."""
    conn = get_connection()
    try:
        inserted = 0
        for ch in channels:
            cur = conn.execute(
                "INSERT OR IGNORE INTO discovered_channels (name, url, description, source, keyword, "
                "status, discovered_at) VALUES (?, ?, ?, ?, ?, 'new', ?)",
                (ch.get("name"), ch.get("url"), ch.get("description"), ch.get("source"), ch.get("keyword"), now_iso()),
            )
            inserted += cur.rowcount
        conn.commit()
        return inserted
    finally:
        conn.close()


def get_discovered_channels():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM discovered_channels ORDER BY discovered_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_discovered_channel_status(channel_id, status):
    conn = get_connection()
    try:
        conn.execute("UPDATE discovered_channels SET status = ? WHERE id = ?", (status, channel_id))
        conn.commit()
    finally:
        conn.close()


def list_sending_profiles():
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM sending_profiles ORDER BY is_default DESC, name").fetchall()
        return [dict(r, is_default=bool(r["is_default"])) for r in rows]
    finally:
        conn.close()


def get_sending_profile(profile_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM sending_profiles WHERE id = ?", (profile_id,)).fetchone()
        return dict(row, is_default=bool(row["is_default"])) if row else None
    finally:
        conn.close()


def create_sending_profile(name, resume_text, portfolio_url, tone, signature, is_default=False):
    conn = get_connection()
    try:
        ts = now_iso()
        if is_default:
            conn.execute("UPDATE sending_profiles SET is_default = 0")
        conn.execute(
            "INSERT INTO sending_profiles (name, resume_text, portfolio_url, tone, signature, "
            "is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, resume_text, portfolio_url, tone, signature, int(is_default), ts, ts),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()


def update_sending_profile(profile_id, **fields):
    allowed = {"name", "resume_text", "portfolio_url", "tone", "signature", "is_default"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return
    conn = get_connection()
    try:
        if updates.get("is_default"):
            conn.execute("UPDATE sending_profiles SET is_default = 0")
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = [int(v) if k == "is_default" else v for k, v in updates.items()]
        conn.execute(
            f"UPDATE sending_profiles SET {set_clause}, updated_at = ? WHERE id = ?",
            params + [now_iso(), profile_id],
        )
        conn.commit()
    finally:
        conn.close()


def delete_sending_profile(profile_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM sending_profiles WHERE id = ?", (profile_id,))
        conn.commit()
    finally:
        conn.close()


def get_contacts_for_posting(posting_id):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM contacts WHERE posting_id = ? ORDER BY "
            "CASE tier WHEN 'named_decision_maker' THEN 0 WHEN 'named_junior' THEN 1 ELSE 2 END",
            (posting_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def archive_expired_postings(cutoff_date):
    """Auto-archives closed (no longer live) postings whose closed_date is
    older than cutoff_date, skipping anything pinned (decision #29: a pin
    always wins over auto-archival) or already archived. Returns the count
    archived."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE postings SET archived = 1 WHERE status = 'closed' AND archived = 0 "
            "AND pinned = 0 AND closed_date IS NOT NULL AND closed_date < ?",
            (cutoff_date,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_expired_archived_postings(delete_cutoff_date):
    """Second, longer grace period (decision #29's "auto-delete" half) —
    only rows already archived AND closed before delete_cutoff_date
    (further back than the archive cutoff) are actually removed. A pin
    still wins even after archival."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM postings WHERE archived = 1 AND pinned = 0 "
            "AND closed_date IS NOT NULL AND closed_date < ?",
            (delete_cutoff_date,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def delete_posting(posting_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM postings WHERE id = ?", (posting_id,))
        conn.commit()
    finally:
        conn.close()


def update_contact(contact_id, archived=None, pinned=None):
    conn = get_connection()
    try:
        if archived is not None:
            conn.execute("UPDATE contacts SET archived = ? WHERE id = ?", (int(archived), contact_id))
        if pinned is not None:
            conn.execute("UPDATE contacts SET pinned = ? WHERE id = ?", (int(pinned), contact_id))
        conn.commit()
    finally:
        conn.close()


def delete_contact(contact_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
        conn.commit()
    finally:
        conn.close()


def update_lead(lead_id, archived=None, pinned=None, snoozed_until=None):
    conn = get_connection()
    try:
        if archived is not None:
            conn.execute("UPDATE leads SET archived = ? WHERE id = ?", (int(archived), lead_id))
        if pinned is not None:
            conn.execute("UPDATE leads SET pinned = ? WHERE id = ?", (int(pinned), lead_id))
        if snoozed_until is not None:
            conn.execute("UPDATE leads SET snoozed_until = ? WHERE id = ?", (snoozed_until, lead_id))
        conn.commit()
    finally:
        conn.close()


def delete_lead(lead_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.commit()
    finally:
        conn.close()


def export_all_data():
    """Full JSON export (decision #29's "export-to-file") — everything the
    user might want a copy of before a retention sweep runs, or just as a
    backup independent of backend/backup.py's raw DB-file copy."""
    conn = get_connection()
    try:
        return {
            "exported_at": now_iso(),
            "postings": [dict(r) for r in conn.execute("SELECT * FROM postings").fetchall()],
            "contacts": [dict(r) for r in conn.execute("SELECT * FROM contacts").fetchall()],
            "leads": [dict(r) for r in conn.execute("SELECT * FROM leads").fetchall()],
            "sent_emails": [dict(r) for r in conn.execute("SELECT * FROM sent_emails").fetchall()],
        }
    finally:
        conn.close()


def get_posting(posting_id):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM postings WHERE id = ?", (posting_id,)).fetchone()
        return _posting_row_to_dict(row) if row else None
    finally:
        conn.close()


def update_posting(posting_id, archived=None, pinned=None, snoozed_until=None):
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM postings WHERE id = ?", (posting_id,)).fetchone()
        if not row:
            return None
        if archived is not None:
            conn.execute("UPDATE postings SET archived = ? WHERE id = ?", (int(archived), posting_id))
        if pinned is not None:
            conn.execute("UPDATE postings SET pinned = ? WHERE id = ?", (int(pinned), posting_id))
        if snoozed_until is not None:
            conn.execute("UPDATE postings SET snoozed_until = ? WHERE id = ?", (snoozed_until, posting_id))
        conn.commit()
        updated = conn.execute("SELECT * FROM postings WHERE id = ?", (posting_id,)).fetchone()
        return _posting_row_to_dict(updated)
    finally:
        conn.close()
