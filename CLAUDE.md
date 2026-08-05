# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

There is no application code here yet — this repo is currently a set of planning/research markdown
documents for a two-part project:

1. **An ongoing manual research effort** to find in-house (not agency) motion design / video / art
   direction roles for the candidate described in `research_brief.md`, tracked in `role_search.md`.
2. **A spec for a not-yet-built automation app** (`app_build_spec.md`) that will eventually replace
   part of the manual research with a scheduled scraper + static site.

There are no build/lint/test commands because no code exists yet. When code is added per
`app_build_spec.md`, update this file with the real commands.

## File relationships — read in this order

- **`research_brief.md`** — the handoff brief given to a research session (human or LLM). Defines the
  candidate profile, inclusion/exclusion rules for what counts as a qualifying role, the industry
  clusters to sweep, geography priority tiers, and — critically — the maintenance rules for
  `role_search.md` (see below). Read this first to understand *why* `role_search.md` is shaped the way
  it is.
- **`role_search.md`** — the living tracker and the actual deliverable of the research effort. Organized
  by industry cluster, then by tier (Apply Now / Adjacent-Strong Fit / Monitor / De-prioritize), plus a
  peer-community section and an Archive / Dead Leads section. This file is never fully rewritten from
  scratch — it accumulates.
- **`compass_artifact_*.md`** — a snapshot research output (TL;DR + detailed findings) from an earlier
  session, seeded into `role_search.md`. Treat as historical reference, not something to keep updating.
- **`app_build_spec.md`** — the build spec for the future scraper/site. States explicit scope limits and
  non-goals; do not expand scope beyond what it describes (see below).

## Working on `role_search.md` (do this exactly — rules live in `research_brief.md`)

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
  remote/location handling) is specified in detail in `app_build_spec.md` — follow it exactly rather than
  re-deriving filter keywords.
