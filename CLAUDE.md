# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This repo has three parts:

1. **An ongoing manual research effort** to find in-house (not agency) motion design / video / art
   direction roles for the candidate described in `DOCS/research_brief.md`, tracked in
   `DOCS/role_search.md`.
2. **The v1 automation app** (`scripts/fetch_postings.py` + the "Search" tab of `index.html`, built
   per `app_build_spec.md`) that fetches postings from companies confirmed to run
   Greenhouse/Lever/SmartRecruiters, filters them, and renders a static page. Built and live as of
   2026-08-05. Still the only piece that runs unattended (GitHub Actions cron + GitHub Pages).
3. **The v2 job-search command center** (`backend/` + the Leads/Outreach/Setup/Glance tabs of
   `index.html`) — a local FastAPI+SQLite backend adding resume-driven search config, a
   Telegram/Slack/manual-capture leads pipeline, and an LLM-drafted, auto-sent cold-email CRM. This
   deliberately reverses several of `app_build_spec.md`'s v1 non-goals (no backend, no auth, no
   email) — see "v2: Job Search Command Center" below for what changed and why.

Research/planning docs live under `DOCS/` (published as part of this public repo — the candidate
consented to that; see git history if that ever needs revisiting). App code lives at repo root
(`scripts/`, `data/`, `index.html`, `.github/workflows/`, `backend/`) so `CLAUDE.md` stays
discoverable from the root by tooling.

Run the v1 fetch script with `python scripts/fetch_postings.py` (stdlib only, no install step). Run
the v2 backend from the repo-root `.venv` (see "v2" section below) — it's a separate, heavier
dependency set (FastAPI, Anthropic SDK, Telethon, etc.), kept out of the stdlib-only v1 script
deliberately. No lint/test suite exists — see "Known gaps / things to revisit" below for what
hasn't been verified.

## File relationships — read in this order

- **`DOCS/research_brief.md`** — the handoff brief given to a research session (human or LLM). Defines
  the candidate profile, inclusion/exclusion rules for what counts as a qualifying role, the industry
  clusters to sweep, geography priority tiers, and — critically — the maintenance rules for
  `DOCS/role_search.md` (see below). Read this first to understand *why* `role_search.md` is shaped the
  way it is.
- **`DOCS/role_search.md`** — the living tracker and the actual deliverable of the research effort.
  Organized by industry cluster, then by tier (Apply Now / Adjacent-Strong Fit / Monitor /
  De-prioritize), plus a peer-community section and an Archive / Dead Leads section. This file is never
  fully rewritten from scratch — it accumulates.
- **`DOCS/compass_artifact_*.md`** — a snapshot research output (TL;DR + detailed findings) from an
  earlier session, seeded into `role_search.md`. Treat as historical reference, not something to keep
  updating.
- **`app_build_spec.md`** — the build spec the app was built from. States explicit scope limits and
  non-goals; do not expand scope beyond what it describes without revisiting them deliberately (see
  below).

## Working on `DOCS/role_search.md` (do this exactly — rules live in `DOCS/research_brief.md`)

If asked to continue the research sweep, or if any task touches `role_search.md`, follow these rules
from `research_brief.md` precisely:

1. Read the current `role_search.md` in full first — do not re-derive companies/roles already recorded.
2. Append new findings into the correct **industry cluster** section, in the correct **tier**
   (Apply Now / Adjacent-Strong Fit / Monitor / De-prioritize).
3. Never delete a stale entry — move it to **Archive / Dead Leads** with a one-line reason and the date.
4. If a previously "Apply Now" role is found to be no longer live, move it to Archive in the same pass
   you discover that — don't leave stale entries in an active tier.
5. Deliver the full updated file, not a diff or a prose summary of changes.
6. Preserve the existing structure: cluster first, tier second — this keeps the file diffable over time.

Scope rules that define what belongs in the tracker (from `research_brief.md`):
- **In scope:** in-house roles at companies whose core business is not creative/marketing services, with
  a self-sufficient internal creative/motion/video team. Named internal studios (e.g. Ericsson's "M&C
  Hub," Experian's "In-House Creative Studio") are the strongest signal — actively hunt for the name, not
  just job titles.
- **Out of scope / excluded entirely:** agency jobs, cameraman/cinematographer roles (never surface these,
  not even as Monitor). Staffing-firm placements (e.g. Williams Lea) into an in-house studio are
  borderline — flag explicitly as "staffing placement," don't merge into direct in-house findings.
  Companies whose flagship creative work is fully outsourced to an agency of record go in
  **De-prioritize**, not Monitor.
- Geography: Nordics are Tier 1 priority; Luxembourg/Belgium/NL/DE/CH Tier 2; UK Tier 3; US Tier 4
  (only if remote-hireable into the EU or realistic relocation). Fully remote/EU-hireable roles are a
  separate category evaluated independently of geographic tier and should be surfaced regardless of
  company HQ.

## The v1 automation app (`app_build_spec.md`) — scope constraints

These constraints governed the original build and still apply to `scripts/fetch_postings.py`
specifically (it stays stdlib-only, unattended, GitHub Actions-driven). The "no auth / no email /
no backend" constraints below were **v1-only** and have been deliberately superseded for the parts
of the app now living in `backend/` — see "v2: Job Search Command Center" further down. Don't
"fix" the v2 backend back toward these just because this section says so.

- **Only covers companies on Greenhouse, Lever, or SmartRecruiters** (the three ATS platforms with public,
  unauthenticated JSON APIs). Workday and bespoke career portals are explicitly out of scope — do not add
  scraping for them, even if a company in `role_search.md` seems like a good candidate. That's a
  separate, more fragile project.
- No auth/accounts (single user), no email/push notifications in **`fetch_postings.py`/GitHub
  Actions specifically** — that piece's output is still a committed JSON file + a static page.
- No headless browser / JS-rendered page scraping in v1.
- Stack is intentionally minimal: Python stdlib (`urllib`/`requests` + `json`) for the fetch script, no
  framework for the frontend (`index.html` fetches `data/postings.json` client-side), GitHub Actions for
  the daily schedule, GitHub Pages for hosting. Don't introduce a framework or build step unless the spec
  is revised first.
- Planned layout (none of this exists yet):
  ```
  /scripts/fetch_postings.py
  /data/companies.json
  /data/postings.json
  /data/archive.json
  /index.html
  /.github/workflows/fetch.yml
  ```
- `companies.json` ATS slugs must be verified by hand against the live careers page before being added —
  never guess a slug from the company name (a wrong slug 404s or silently returns a different company's
  postings). If a slug is unknown, seed the entry with `"ats_slug_needed": true` rather than guessing.
- Build order matters: get `fetch_postings.py` working correctly against 1–2 companies locally before
  wiring up the full company list, and before touching the GitHub Actions workflow — automating a broken
  fetch script just automates the breakage.
- Filtering logic (title/description keyword matching, exclusion rules for cameraman/videographer terms,
  remote/location handling) is specified in detail in `app_build_spec.md`, with one deliberate deviation
  — see "Known gaps / things to revisit" below.

## v2: Job Search Command Center (`backend/`)

Built to turn the passive v1 watcher into an active command center: resume-driven search
config, industry/contract-mode/source selection, a community leads feed, and an LLM-assisted,
auto-sent cold-email CRM. Key decisions (confirmed with the user, not casual scope creep):

- **Backend is a real local FastAPI+SQLite service, local-only for v1** — runs on the user's own
  Windows machine ("on when the PC is on"), binds to `127.0.0.1` only, no auth beyond that binding.
  Explicit intent to migrate to a small always-on cloud VM later; the code avoids hardcoding
  local-only assumptions where it's cheap not to (host/port/paths are all config-driven).
- **No automated "joining groups without invitations"** — there's no legitimate API for that, and
  automating WhatsApp via unofficial libraries risks account bans. Instead: **live ingestion for
  Telegram** (`backend/ingest/telegram.py`, the user's own account session via Telethon, channels
  already joined) **and Slack** (`backend/ingest/slack.py`, a personal user OAuth token, workspaces
  already joined); **Discord and WhatsApp get a manual quick-capture box** in the Leads tab feeding
  the same pipeline.
- **Cold email sends fully automatically** (not draft-and-review) — the user's explicit choice.
  Safety nets exist anyway: at most one automated email per contact ever
  (`db.has_sent_to_contact`), a configurable daily send cap, and a full `sent_emails` log.
- **LLM access is a real Anthropic API key** (pay-per-token, `backend/config.json`, gitignored) —
  not a ChatGPT/Claude.ai consumer subscription login, which doesn't exist as a programmatic
  integration path.
- **Notifications are in-app only** — an unread/new-since-last-visit badge (Leads tab) and a
  unified Glance tab (new postings / new leads / stale outreach), not OS/mobile push.

### Layout
```
backend/
  app.py            — FastAPI app (127.0.0.1 only), all endpoints
  db.py             — SQLite schema + access (profile, contacts, leads, sent_emails, settings,
                      postings, sending_profiles, discovered_channels); also holds ALL_INDUSTRIES
                      (the 29-cluster taxonomy, verbatim from role_search.md — keep in sync by
                      hand if that file's clusters change)
  llm.py            — multi-provider wrapper: extract_resume_profile / triage_message /
                      draft_cold_email / classify_sentiment; monthly spend cap (0 = disabled)
  vault.py          — opt-in master-password credential vault (PBKDF2+Fernet), encrypts LLM keys
                      + the Gmail client secret once a user sets a password via Setup > Security.
                      NOT auto-initialized — until then, config.json plaintext keeps working
                      exactly as before (see config.py's vault-first/plaintext-fallback reads)
  scoring.py        — rule-based weighted posting scorer (keyword/industry/work-mode/recency)
  enrichment.py     — contact-resolution orchestrator: walks providers/enrichment.py's chain,
                      labels tier (named_decision_maker / named_junior / generic_inbox)
  pipeline.py        — unified queue (scored postings w/ contacts + real leads), sending-profile
                      alias auto-selection, daily quota / split-ratio / resume-delivery settings
  resume_pdf.py      — fpdf2 plain-text-to-PDF for the "PDF attachment" resume-delivery mode
  scheduler.py       — APScheduler daily-batch job (sync+score+enrich+reply-check+notify);
                      disabled by default (scheduler_enabled setting) — opt-in via Setup
  notify_telegram.py — sends batch-ready/failure notifications via the user's own Telegram
                      session (reuses ingest/telegram.py's session file, "me"/Saved Messages
                      by default)
  reply_check.py     — narrow gmail.readonly reply-check per sent thread, sentiment-based
                      auto-suppression (manual re-approach = PATCH /contacts/{id}/status)
  retention.py       — auto-archive/auto-delete sweep for closed postings (pins always win)
  backup.py          — nightly app.db + vault.dat backup into backend/backups/ (gitignored),
                      mitigating the Drive-sync corruption risk noted below
  providers/          — provider ABCs matching llm.py's dispatch shape (job_source, enrichment,
                      email, group_discovery); see "Provider categories" note below
  gmail.py           — Gmail OAuth (installed-app flow; gmail.send + gmail.readonly scopes) + send
                      (with optional PDF attachment) + check_replies
  resume_parse.py   — extension-dispatch text extraction for uploaded resumes (.txt/.md/.pdf/.docx;
                      legacy .doc rejected — no clean pure-Python parser for it)
  ingest/
    telegram.py     — standalone script, posts to /leads/capture
    slack.py        — standalone script, polls + posts to /leads/capture
  config.example.json — template; copy to config.json (gitignored) and fill in real secrets
```

Provider categories (`backend/providers/`, plan §4) — same ABC-plus-implementations shape as
`llm.py`'s dispatch, so a new source/vendor is additive, never a rewrite of a call site:
- `job_source.py` — Greenhouse/Lever/SmartRecruiters, wrapping `scripts/fetch_postings.py`'s
  existing fetchers (that script itself is untouched, still stdlib-only, still GH-Actions-driven).
- `enrichment.py` — `CompanyPageScraperProvider` (real, free, tried first — but sequentially
  checks up to 6 team-page-style paths per company with a 10s timeout each, so a full chain over
  several companies with no hits can take tens of seconds; this is what makes `/postings/{id}/enrich`
  and the scheduler's per-run enrichment step slow, not a bug) and `HunterProvider` (real API,
  needs a key). RocketReach/Apollo/ContactOut/Snov are registered but unimplemented placeholders
  (`_UnimplementedEnrichmentProvider`, returns `[]`) — no accounts/keys existed to build against.
- `email.py` — wraps `gmail.py`.
- `group_discovery.py` — `TelegramDirectoryProvider`/`DiscordDirectoryProvider` scrape t.me /
  Disboard's public pages; selectors are best-effort, not verified against live markup this
  session — expect a touch-up the first time either is actually run.
data/
  search_profile.json — resume-derived keywords/industries only (no raw resume text — repo is public)
  search_scope.json   — Setup tab toggles: active_ats, contract_modes, industries (forward-looking
                        preference from ALL_INDUSTRIES, doesn't hard-filter fetches), countries
                        (ISO codes — restricts the location "verify" flag; empty = no restriction)
  freelance_sources.json — curated gig-platform list, same "flag don't guess" convention as
    companies.json's `ats_slug_needed`; none currently have a public API (integration_needed: true)
  world-map.svg, country-codes.json — vendored from github.com/flekschas/simple-world-map
    (CC BY-SA 3.0, attribution in data/world-map.svg.LICENSE.txt) — 197-territory SVG map +
    175-entry ISO code -> name mapping, powering the Setup tab's country picker
```
`companies.json` gained an `enabled` field (Setup tab can disable a company's fetch without
deleting the entry) and postings gained `contract_type` (from Lever's `categories.commitment` /
SmartRecruiters' `typeOfEmployment`; Greenhouse has no such field, stays `null`/"unknown" —
never guessed).

`scripts/fetch_postings.py`'s location matching (`_effective_countries()`) keeps its original
curated EU/EEA+UK+CH allowlist as the **default** when no countries are selected in Setup — that
default does not expand just because the map/mapping file supports more countries. Only an
explicit Setup-tab country selection reaches beyond the default set, and when it does, it's
resolved against the full 175-country `data/country-codes.json` mapping, not the narrow default
list — so picking any country in the world (not just the original ~31) works correctly for both
name-based (Greenhouse) and code-based (SmartRecruiters) location matching.

The vendored SVG mixes two shapes per country: most are a single `<path id="xx">`, but ~37
multi-territory countries (Sweden, Norway, Denmark, etc.) are a `<path>`-wrapped `<g id="xx">`
instead. `index.html`'s map JS (and its CSS) handles both — a selector that only matches `path[id]`
will silently miss those 37 countries (this bit a first draft of the Nordics quick-select button).

`data/country-codes.json`'s `continent` field is merged in from a second vendored source
(github.com/lukes/ISO-3166-Countries-with-Regional-Codes, CC BY-SA 4.0, also credited in
`data/world-map.svg.LICENSE.txt`) — the Setup tab's country list groups by this field into
Europe/Asia/Africa/Americas/Oceania row sections instead of one flat alphabetical list. Two
entries (`_somaliland`, `tw`/Taiwan) have no ISO/UN region assignment upstream and were set by
hand on plain geography, not a political claim.

The map supports zoom (buttons + ctrl/cmd+scroll-wheel) via a CSS `transform: scale()` on
`#country-map-container` inside a fixed-height, `overflow: auto` viewport — panning is just native
scrollbars once zoomed in, no custom drag logic. Plain scroll-wheel over the map still scrolls the
page/panel normally; only ctrl/cmd+wheel zooms, so the map doesn't trap scrolling.

The Setup tab's extracted skills/industries/keywords are edited as removable tag pills
(`createTagPillEditor` in `index.html`), not comma-separated text fields. Keywords specifically get
a second, richer view: the resume text is rendered read-only with every current keyword
highlighted inline (`highlightKeywords`) — clicking a highlighted phrase untags it, and selecting
any other span of resume text surfaces a "+ Tag selected text" button to tag it. A plain type-and-
Enter input on the keyword pill editor itself covers tags that aren't literally in the resume text
at all. All three editors (skills/industries/keywords) share one `createTagPillEditor` instance
each; the keyword editor's `onChange` callback re-renders the highlighted resume view so the two
stay in sync regardless of which side a tag was added/removed from.

### One-time setup required before v2 features work
- `backend/config.json` (copy from `config.example.json`): real Anthropic API key required for
  resume extraction / message triage / email drafting to do anything but fail gracefully.
- Telegram: `api_id`/`api_hash` from https://my.telegram.org + `channels` list; first run is an
  interactive phone/code login that creates a session file (gitignored).
- Slack: a personal user OAuth token (`xoxp-...`) + channel IDs to poll.
- Gmail: a Google Cloud OAuth Desktop client (`backend/client_secret.json`, gitignored) — see the
  setup steps in `backend/gmail.py`'s docstring. First send opens an interactive browser consent.
- None of these being configured causes a crash — every integration point (`llm.py` calls,
  `gmail.send_email`, the ingest scripts) fails closed with a clear message/no-op rather than
  breaking the rest of the app.

### Run it
```
cd backend && ../.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8420
```
Then open `index.html` (locally or via the live GitHub Pages URL — CORS is wide open since the
backend only ever binds to localhost, so the only thing that can reach it is the user's own
browser on the same machine). Telegram/Slack ingestion run as separate long-lived processes:
`python backend/ingest/telegram.py` / `python backend/ingest/slack.py`.

## Master plan execution status (`DOCS/job-watcher-master-plan.md`)

Phases 0-7 of the master plan have real, working backend code behind them (verified via direct
HTTP round-trips against the running backend, not just unit-level checks) — but the frontend was
deliberately NOT built out to match every new setting; most of what's below is API/curl-reachable
only. Building the corresponding Setup-tab UI (a data-table-scale review queue, sending-profile
CRUD forms, enrichment/scheduler/retention settings panels, group-discovery review list) is the
next real chunk of work, not a small polish pass — treat it as its own phase, not a quick add-on.

Also not built (needs real external accounts/decisions this session had neither the credentials
nor the standing to make unilaterally): Google Workspace domain sending (still personal Gmail
OAuth — decision #11's DNS/warm-up work needs the user to actually register a domain), RocketReach/
Apollo/ContactOut/Snov enrichment (placeholders only, see above), and the credential vault is
built but **not activated** — it stays opt-in via Setup > Security precisely because this repo's
own `config.json` already had real working keys in it going in, and auto-enabling encryption
behind a password of my choosing would have locked the user out of their own setup. Same reasoning
for the scheduler (`scheduler_enabled` defaults false) — it runs real scrapes and sends a real
Telegram message on a timer, so it needs an explicit opt-in, not just a backend restart.

## Known gaps / things to revisit

- **Seed list ceiling is 4 companies, not a bug.** `data/companies.json` currently holds Storyblok,
  Adyen, Experian, Wise. All 29 companies in `role_search.md`'s three swept clusters (Enterprise
  Software, Nordic Industrial, DACH/Benelux) were checked against Greenhouse/Lever/SmartRecruiters; only
  these 4 are on a supported platform. The other 25 lean Workday/SuccessFactors/bespoke. Growing this
  list requires either sweeping new industry clusters in `role_search.md` (per `research_brief.md`) and
  checking their ATS platform, or accepting the app stays small. Don't assume a short seed list means the
  fetch/filter logic is broken.
- **Filtering deviates from `app_build_spec.md`'s literal wording on purpose.** The spec says match
  include-keywords against "title or description." In practice, bare single words `motion` and
  `animation` false-matched unrelated SaaS jargon in description text (e.g. "sales motions",
  "implementation motion"). Fix applied in `scripts/fetch_postings.py`: those two words match
  **title-only**; multi-word specific phrases (`video editor`, `art director`, `motion graphics`, etc.)
  still match title-or-description. All matching uses word boundaries. If recall seems too low, this is
  the first place to reconsider — not a full rewrite.
- **`eu_hireable_or_remote` is a soft flag, not a hard filter**, per spec ("flag rather than silently
  drop"). It checks the location string against a hireable-country list (EU/EEA + UK + CH, matching
  `research_brief.md`'s own geography tiers) and remote hints. City-only location strings with no country
  (e.g. Greenhouse sometimes returns just `"Amsterdam"`) will flag `false` even for genuinely fine
  postings — that's expected ambiguity to resolve by eye, not a parsing bug.
- **SmartRecruiters fetches are slow** (~2–3 min per company with hundreds of postings, since the list
  endpoint doesn't include full descriptions — one detail call per posting is needed for accurate
  filtering). Fine for a daily GitHub Actions cron; would need rethinking if the seed list grows large.
- **Repo lives inside a Google-Drive-synced folder** (`H:\My Drive\Dev\Dev_jobSearch`). This was a
  known-risk decision (Drive's file locking can occasionally corrupt `.git` mid-write) — accepted
  deliberately, not an oversight. If `.git` ever gets corrupted, that's the likely cause.
- **v2 backend is built and verified end-to-end with a placeholder Anthropic key** (every endpoint
  round-trip tested via curl + a Playwright browser smoke test), but **not yet live-tested against
  real credentials** — no real Anthropic key, Telegram session, Slack token, or Gmail OAuth client
  existed at build time. Expect first-run friction there, not in the endpoint/DB/UI wiring itself.
- **"Outreach gone quiet" (`db.get_stale_outreach`) is a status heuristic, not a real reply check.**
  The Gmail integration only has `gmail.send` scope (deliberately, to keep the OAuth consent
  narrow) — there's no inbox-read integration, so "no reply after 7 days" actually means "contact
  status is still `sent` and hasn't been manually updated" via the Outreach/Glance "mark handled"
  action. A genuine reply sitting unread in Gmail won't clear this on its own.
- **`data/search_profile.json`/`search_scope.json` are written by the local backend, not the daily
  GitHub Actions cron** — they only update when the user runs the Setup tab locally and commits the
  result themselves (same manual-commit pattern as hand-editing `companies.json` already was).
  `fetch_postings.py` reads them additively/defensively so a missing file is a no-op, not a crash.
