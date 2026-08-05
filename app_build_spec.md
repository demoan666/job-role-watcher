# app_build_spec.md — In-House Motion Role Watcher

## Companion files
Read `role_search.md` and `research_brief.md` first — they define the candidate profile, target companies, and inclusion/exclusion rules this app encodes. This file is the build spec only; it does not restate candidate context.

## Premise (read before building — do not expand scope)
This app does **not** aggregate all companies in `role_search.md`. It only covers companies whose careers site runs on one of three ATS platforms with a public, unauthenticated JSON API:
- **Greenhouse** — `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs`
- **Lever** — `https://api.lever.co/v0/postings/{slug}?mode=json`
- **SmartRecruiters** — `https://api.smartrecruiters.com/v1/companies/{slug}/postings`

Companies on Workday or bespoke/custom career portals (most large industrials — ABB, Siemens, Schneider, Ericsson, etc.) are **out of scope** for this app. Those stay on manual/Research-tool sweeps. Do not attempt to add scraping for them — that's a different, much more fragile project.

**Goal:** a repo that runs on a schedule, checks the covered companies for new postings matching the candidate's profile, and keeps a running diff — so the candidate sees new listings without re-running manual searches.

## Non-goals
- No login/auth, no user accounts — single user (repo owner).
- No email/push notifications in v1 — output is a committed file + rendered page the user checks manually.
- No attempt to verify "named in-house studio" status automatically — that judgment call stays manual, recorded in `role_search.md` by a human/LLM session, not by this app.
- No headless browser / scraping of JS-rendered career pages in v1.

## Company seed list
Build `companies.json` seeded from every company in `role_search.md` that is confirmed or suspected to run one of the three ATS platforms. Where the ATS slug is unknown, leave it blank and flag `"ats_slug_needed": true` rather than guessing — a wrong slug returns a 404 or someone else's postings.

Schema:
```json
{
  "name": "Storyblok",
  "ats": "greenhouse",
  "slug": "storyblok",
  "cluster": "Enterprise Software / SaaS / Fintech / B2B Tech"
}
```

Start with companies already flagged Apply Now / Adjacent / Monitor in `role_search.md` for the Enterprise Software / SaaS / Fintech cluster — that's the cluster most likely to run Greenhouse/Lever. Confirm each slug by hand (visit the careers page, check the network tab or URL pattern) before adding it — do not assume a slug from the company name.

## Filtering logic
For each fetched posting, match on:
- **Include** if title or description contains (case-insensitive): `motion`, `video editor`, `video producer`, `animator`, `animation`, `art director`, `creative director`, `motion graphics`, `brand designer` (only if description also mentions video/motion/animation — "brand designer" alone is too broad).
- **Exclude always**, regardless of other matches: `cameraman`, `cinematographer`, `videographer` *only when* paired with `wedding`, `event photography`, or `live broadcast` in the description (plain "videographer" at a B2B company can be legitimate — don't blanket-exclude it).
- **Exclude** postings whose location/remote field indicates the role is not EU/EEA-hireable and not remote — flag rather than silently drop, since remote-classification from raw ATS location strings is unreliable.

## Output
- `data/postings.json` — current snapshot, one entry per matched posting: company, title, location, remote flag, URL, first_seen date, ATS source.
- `data/archive.json` — postings that disappeared from a subsequent fetch (role closed/filled), moved here with a `closed_date` — mirrors the Archive section convention in `role_search.md`.
- On each run, diff new fetch against previous `postings.json`: anything new gets `first_seen = today`; anything missing moves to archive.

## Automation
- GitHub Actions workflow, scheduled daily (`cron: '0 7 * * *'` or similar).
- Script commits `data/postings.json` and `data/archive.json` back to the repo if changed.
- No secrets needed — all three APIs are public/unauthenticated.

## Frontend
- Single static `index.html`, no build step, no framework — fetch `data/postings.json` client-side and render a sortable/filterable table (company, title, location, remote, first_seen, link).
- Group by cluster (matches `role_search.md` structure) so it's visually consistent with the manual tracker.
- Served via GitHub Pages from the same repo — zero extra hosting.

## Stack
- **Script language:** Python (stdlib `urllib`/`requests` + `json` — no need for anything heavier; this is a handful of HTTP GETs and a diff).
- **Repo layout:**
```
/scripts/fetch_postings.py
/data/companies.json
/data/postings.json
/data/archive.json
/index.html
/.github/workflows/fetch.yml
```

## Build order (for the 2-hour budget)
1. `companies.json` with 5–8 confirmed Greenhouse/Lever slugs (verify manually first — this is the step most likely to eat time if rushed).
2. `fetch_postings.py` — fetch, filter, diff, write JSON. Test locally against 1–2 companies before wiring up all of them.
3. `index.html` — static table reading the JSON.
4. GitHub Actions workflow — schedule + commit-back step.
5. Manual test run end-to-end before calling it done.

Do not start on the GitHub Actions workflow until step 2 runs correctly locally — automating a broken fetch script just automates the breakage.
