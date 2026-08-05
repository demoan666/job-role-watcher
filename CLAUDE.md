# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

This repo has two parts:

1. **An ongoing manual research effort** to find in-house (not agency) motion design / video / art
   direction roles for the candidate described in `DOCS/research_brief.md`, tracked in
   `DOCS/role_search.md`.
2. **The automation app** (`scripts/fetch_postings.py` + `index.html`, built per `app_build_spec.md`)
   that fetches postings from companies confirmed to run Greenhouse/Lever/SmartRecruiters, filters
   them, and renders a static page. Built and live as of 2026-08-05.

Research/planning docs live under `DOCS/` (published as part of this public repo — the candidate
consented to that; see git history if that ever needs revisiting). App code lives at repo root
(`scripts/`, `data/`, `index.html`, `.github/workflows/`) so `CLAUDE.md` stays discoverable from
the root by tooling.

Run the fetch script with `python scripts/fetch_postings.py` (stdlib only, no install step). No
lint/test suite exists — see "Known gaps / things to revisit" below for what hasn't been verified.

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

## The planned automation app (`app_build_spec.md`) — scope constraints

If asked to start building this app, respect these constraints exactly; they're deliberate, not
oversights:

- **Only covers companies on Greenhouse, Lever, or SmartRecruiters** (the three ATS platforms with public,
  unauthenticated JSON APIs). Workday and bespoke career portals are explicitly out of scope — do not add
  scraping for them, even if a company in `role_search.md` seems like a good candidate. That's a
  separate, more fragile project.
- No auth/accounts (single user), no email/push notifications in v1 — output is a committed JSON file +
  a static page the user checks manually.
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
