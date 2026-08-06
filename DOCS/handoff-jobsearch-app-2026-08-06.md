# Handoff: Job Search Command Center — v2 build + Setup UI enhancements

**Date:** 2026-08-06
**Working directory:** `H:\My Drive\Dev\Dev_jobSearch` (Google Drive-synced — known `.git` corruption risk, accepted deliberately, see `CLAUDE.md`)
**Repo:** https://github.com/demoan666/job-role-watcher (public)

## What this session did

Two chunks of work, both complete and verified, **neither committed yet**:

1. **Built the entire v2 "job search command center"** on top of the v1 static watcher
   (`scripts/fetch_postings.py` + `index.html`): a local FastAPI+SQLite backend (`backend/`) adding
   resume-driven search config, industry/contract-mode/source selection, a Telegram+Slack+manual
   leads pipeline, and an LLM-drafted auto-sent cold-email CRM. Five phases, all built and
   Playwright-verified against a mocked/placeholder-key backend.
2. **Follow-up UI enhancements** to the Setup tab: a real file-upload dropzone for resumes
   (PDF/DOCX/TXT/MD), the full 29-cluster industry taxonomy as checkboxes, a clickable world map +
   synced country checklist (grouped by continent, with zoom), and LinkedIn-style tag-pill editors
   for skills/industries/keywords (including click-to-untag highlighted phrases directly in the
   resume text, and select-text-to-tag).

**Everything is documented in detail in `CLAUDE.md`'s "v2: Job Search Command Center" section** —
read that first, don't re-derive the architecture from scratch. It covers: the confirmed
architecture decisions (local-only backend, no group auto-join, fully-automated email with safety
nets, real API key not a chat subscription, in-app-only notifications), the full `backend/` layout,
the `data/` schema additions, the vendored map/country-code assets and their licenses (CC BY-SA
3.0/4.0, attribution in `data/world-map.svg.LICENSE.txt`), the `<path>` vs `<g>` SVG quirk, and the
tag-pill editor architecture. This handoff intentionally does not repeat that content.

The most recent plan file, `C:\Users\dell\.claude\plans\handoff-jobsearch-app-2026-08-05-md-read-merry-lovelace.md`,
documents **only the second chunk** (Setup UI enhancements) — it was overwritten from an earlier
plan that covered chunk 1 (the v2 architecture), so don't expect it to describe the whole session.
Chunk 1's plan content is fully superseded by what's now in `CLAUDE.md`.

## Current repo state — nothing committed

```
git status --short
 M .gitignore
 M CLAUDE.md
 M app_build_spec.md
 M data/companies.json
 M data/postings.json
 M index.html
 M scripts/fetch_postings.py
?? DOCS/handoff-jobsearch-app-2026-08-05.md   (from the *previous* session, pre-existing)
?? backend/
?? data/country-codes.json
?? data/freelance_sources.json
?? data/search_scope.json
?? data/world-map.svg
?? data/world-map.svg.LICENSE.txt
```

The user has not asked for a commit yet. **Do not commit without asking** — there's a lot of new
surface area (a whole `backend/` service) and the user should review before it goes in, especially
since this repo is public.

## What's verified vs. not

Verified end-to-end this session (curl + Playwright browser tests, screenshots taken, cleaned up
after): every backend endpoint, the full Setup tab (upload, industries, map, tag editors), Leads
tab (manual capture + triage), Outreach tab (contact CRUD, dedup/cap logic), Glance tab, and
`fetch_postings.py`'s new profile-keyword and country-scope filtering (tested against the real 4
companies with a real restricted scope, then restored to the correct unrestricted state — verify
`data/postings.json`/`data/archive.json` still look right if you touch scope-related code again).

**Not verified — needs real credentials the session never had:**
- Anthropic API key (LLM calls fail closed with a clear error today — `backend/config.json` exists
  locally with placeholder values only, gitignored, not committed)
- Telegram `api_id`/`api_hash` + session login (`backend/ingest/telegram.py`)
- Slack user OAuth token (`backend/ingest/slack.py`)
- Google Cloud OAuth client for Gmail send (`backend/gmail.py`)

All four fail gracefully (logged no-op or a clean JSON error) rather than crashing — this was
deliberately tested. `backend/config.json` locally is missing the `"gmail"` block that
`backend/config.example.json` now has (added after the local file was created) — merge that in
when real Gmail credentials are configured.

## Known non-bugs (already investigated, don't re-open)

- A screenshot during map testing briefly showed Russia/China-area highlighted blue, looking like
  an unwanted selection. Confirmed via direct DOM query (`.selected` was empty) and a fresh
  mouse-away screenshot that it was a transient CSS `:hover` artifact from the screenshot capture
  itself, not a real selection bug. No code changed for this.

## Known real bug fixed this session (for context, not to redo)

~37 multi-territory countries (Sweden, Norway, Denmark, etc.) are `<g id="xx">` elements in the
vendored map SVG, not `<path id="xx">` like most countries. A first draft only wired up
`path[id]` selectors and silently dropped those countries from map clicks, checkbox sync, and the
Nordics quick-select button. Fixed by handling both shapes everywhere (`path[id], g[id]`
selectors, `.selected` CSS on both). If you touch the map JS/CSS again, grep for `g[id]` in
`index.html` before assuming `path` alone is sufficient.

## Suggested skills for the next session

- **`run`** — to launch and click through the app in a browser if verifying any further UI
  changes; this session used the "browser-driven" pattern (Playwright + chromium via a scratch
  install at `C:\Users\dell\AppData\Local\Temp\pw-test`, since no `chromium-cli` was available).
  That scratch install may still exist and can be reused rather than reinstalled.
- **`code-review`** — worth a pass over `backend/` before it's trusted with real credentials
  (Gmail send, Telegram/Slack live ingestion) — none of it has had independent review yet, only
  self-testing by the session that wrote it.
- **`security-review`** — specifically worth running before real Gmail OAuth + auto-send goes
  live, given it emails third parties automatically with no human review step (explicit user
  choice, but worth a second look at the dedup/rate-cap safety nets in `backend/db.py` /
  `backend/app.py`'s `/contacts/{id}/outreach` endpoint).
- **`grilling`** — if the user wants to resume stress-testing `DOCS/research_brief.md`'s research
  *methodology* (separate from the app) — four unanswered questions from an earlier session are
  listed in `DOCS/handoff-jobsearch-app-2026-08-05.md`'s "Not addressed this session" section.

## Local environment notes

- Python venv at repo-root `.venv/` (gitignored) — all backend deps installed
  (`backend/requirements.txt`). Run backend with:
  `cd backend && ../.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8420`
- `reportlab` is installed in the venv but **not** in `requirements.txt` — it was added ad hoc to
  generate test PDF/DOCX fixtures during this session, not a real app dependency. Safe to leave or
  remove.
- Playwright scratch install at `C:\Users\dell\AppData\Local\Temp\pw-test` (Windows path:
  `C:/Users/dell/AppData/Local/Temp/pw-test`) — reuse via
  `require('C:/Users/dell/AppData/Local/Temp/pw-test/node_modules/playwright')` rather than
  reinstalling.
- No secrets were exposed or logged this session — every real-looking credential in `backend/`
  config files is a placeholder (`sk-ant-...`, `xoxp-...`, `null`).
