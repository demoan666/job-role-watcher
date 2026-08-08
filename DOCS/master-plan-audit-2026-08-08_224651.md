# Master Plan Audit — 2026-08-08 22:46 (Dry run, enrichment credentials, sending-profile upload pass)

Audits this session's brief, which was six independent build/report items (not a re-sweep of the
decision log or settings inventory covered by the two prior audits): dry-run mode with real mock
providers, enrichment provider credential fields, a report on industry classification, a Settings
tab-bar CSS bug, a sending-profile resume-upload/validation/restructure, and drag-to-reorder for
the enrichment provider order list. Every row below was verified against the actual code
(grep/read of `index.html` and `backend/*.py`) and, except where noted, a live round-trip against
the running backend (curl) and/or a live browser session — not from memory.

**Status legend** (same as the first two audits)
- **BUILT** — backend logic AND a visible UI element both exist
- **BACKEND-ONLY** — logic exists in code but no UI surfaces it
- **STUBBED** — UI element exists but no real logic behind it
- **NOT BUILT** — neither exists

---

## Item 1 — Dry-run mode

`dry_run_mode` already existed before this session, but only as an ad-hoc branch inside
`send_outreach` (`backend/app.py`, pre-existing code) that returned a canned response — no
`MockEmailProvider`/`MockEnrichmentProvider`, no settings UI, and enrichment wasn't covered at all.
This pass replaced that with real provider-shaped mocks and extended coverage to enrichment.

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | `MockEnrichmentProvider` — one placeholder named contact, zero external calls | Yes | N/A | `backend/providers/enrichment.py:151-163`, registered in `REGISTRY` (`:169`), excluded from `DEFAULT_ORDER` on purpose | **BUILT** — curl-verified: `POST /postings/{id}/enrich` with dry run on returned `{"name":"Dry Run Contact","role":"Hiring Manager","email":"dry-run@example.invalid","source":"mock","tier":"named_junior"}`, no scrape/API call made |
| 2 | `MockEmailProvider` — logs "would send" with full content, no real Gmail call | Yes | N/A | `backend/providers/email.py:39-53`, registered in `REGISTRY` alongside `GmailProvider` (`:56`) | **BUILT** — unit-verified directly (`providers.email.get_provider("mock").send(...)`): printed `[DRY RUN] would send to 'jane@example.com' — subject: 'Hello' ...` and returned a fake result dict, no `googleapiclient` call |
| 3 | Settings toggle "Dry run mode" — pipeline uses mocks regardless of what's configured elsewhere | Yes | Yes | `backend/pipeline.py:13-30` (`dry_run_mode` in `get_pipeline_settings`/`save_pipeline_settings`); `backend/enrichment.py:99` forces `order = ["mock"]`; `backend/app.py:556-557` selects `email_providers.get_provider("mock" if dry_run else "gmail")`; UI: `index.html:738-742` checkbox + save button in Settings > Pipeline | **BUILT** — curl-verified: `POST /settings/pipeline {"dry_run_mode":true}` → `GET /queue` immediately reflected `"dry_run_mode":true`; enrichment and outreach-send both routed through the mock providers while the toggle was on (see rows 1/2); toggle reset to `false` and test data cleaned up afterward |
| 4 | Queue items visibly labeled "DRY RUN" so they're never confused with live items | Yes | Yes | `backend/app.py:701` (`GET /queue` returns `dry_run_mode` alongside `items`); `index.html:1108` (page-level banner), `index.html:1990` (per-card badge), CSS `index.html:302-309` | **BUILT** — code-verified (browser session for this item specifically wasn't re-opened after the queue was empty in this repo's test data, but the same `dry_run_mode` flag and rendering path were exercised live for the Enrichment/Pipeline tabs in items 2/3/5 below) |
| 5 | Real job scraping and real LLM drafting stay active in dry-run — only enrichment and sending are mocked | Yes | N/A | `scripts/fetch_postings.py` untouched; `backend/app.py`'s `_draft_for_contact` (unchanged) always calls the real `llm.draft_cold_email` before the dry-run branch is reached | **BUILT** — curl-verified as a side effect of testing row 3: `POST /contacts/{id}/outreach` with dry run on still attempted the real Anthropic call first and surfaced a real 401 from the placeholder key (same account-level gap noted in the first audit's Priority 1 row 10), proving the LLM call path wasn't bypassed |

**Item 1 totals:** 5 rows — **5 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Item 2 — Enrichment provider credentials

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | One API-key field per enrichment provider (Hunter, RocketReach, Apollo, ContactOut, Snov), empty/placeholder-safe, same pattern as LLM APIs tab | Yes | Yes | `backend/config.py:161-211` (`get_enrichment_credentials`/`save_enrichment_credentials`, vault-first/config.json-fallback, same precedence as `get_llm_settings`); `backend/app.py:844-870` (`GET /settings/enrichment` now includes `provider_credentials`, new `POST /settings/enrichment/credentials`); UI: `index.html:779-782` + `renderCredentialsList`/save handler (`index.html:3303` area) | **BUILT** — curl-verified: set Hunter+RocketReach keys, confirmed masked `"••••1234"`/`"••••5678"` on re-fetch, cleared each, confirmed `"configured":false`; browser-verified separately: typed a key into the Hunter field, clicked Save, list re-rendered `"configured (••••9999)"` live. Test keys cleared afterward |
| 2 | Report which providers have zero real implementation behind them even with a key entered | N/A | Yes | `backend/providers/enrichment.py:98-149` — `HunterProvider` is a real API integration; `RocketReach`/`Apollo`/`ContactOut`/`Snov` are all `_UnimplementedEnrichmentProvider` instances (`:133-158`) whose `find_contacts()` always returns `[]` regardless of a configured key. Surfaced in the UI via `implemented_providers` (`backend/app.py:859`, `["company_page_scraper", "hunter"]`) and a per-row "(stub — no real API call yet)" note (`index.html` `renderCredentialsList`) | **BUILT** (as a reporting mechanism — the underlying stub status itself predates this session, per the first audit's decision #7 row) — browser-verified: exactly 4 stub notes rendered (RocketReach/Apollo/ContactOut/Snov), none on Hunter |

**Item 2 totals:** 2 rows — **2 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Item 3 — Industry classification report

Asked to report where/how a posting or company gets classified into an `ALL_INDUSTRIES` bucket for
the enrichment provider-order setting, and not build anything if the gap turns out to be real. It
isn't a gap — the chain already exists and works:

`data/companies.json`'s hand-set `cluster` field (verbatim strings from `DOCS/role_search.md`'s
taxonomy, e.g. `"Enterprise Software / SaaS / Fintech / B2B Tech"`) flows into
`scripts/fetch_postings.py:363` (`"cluster": company.get("cluster", "")`) → `data/postings.json` →
`backend/db.py:156` (`postings.cluster` column, synced in `sync_postings_from_json`) →
`backend/app.py:760`/`scheduler.py:72` (`enrichment.enrich_company(posting["company"],
posting["url"], industry=posting.get("cluster"))`) → `backend/enrichment.py:44-52`
(`get_provider_order(industry)` looks up `by_industry[industry]`, falling back to the global
default). The same `cluster` string also drives `scoring.py:57-60`'s `_industry_score`. The
Settings > Enrichment scope selector is populated from this exact taxonomy (`db.ALL_INDUSTRIES`,
`backend/db.py:34-64`, `GET /scope/options`, `index.html:3309-3313`) — browser-verified this
session: the dropdown listed all 29 industries verbatim.

| # | Item | Status |
|---|---|---|
| 1 | Company/posting → industry-bucket classification for enrichment provider-order overrides | **BUILT** (pre-existing, confirmed working — no code changed for this item) |

**Item 3 totals:** 1 row — **1 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Item 4 — Settings tab bar wrap CSS fix

| # | Item | Evidence | Status |
|---|---|---|---|
| 1 | Dark/empty patch when Settings subtabs wrap to two rows | Root cause: `.subtabs` (`index.html:195-206`) sets `background: Canvas` for its sticky/scroll-covering role on the main page, but `#settings-overlay .subtabs` only cancelled `position: sticky`, not that background — `Canvas` is a system color independent of `--bg-alt` (the modal panel's actual background), so the mismatched rectangle behind the subtab row became visibly obvious once 9 buttons wrapped to two rows in the modal's narrower width. Fix: `background: none` added to the existing override (`index.html:216`), one line | **BUILT** — browser-verified: opened Settings (9 subtabs genuinely wrap to two rows — LLM APIs/LLM Usage/Backend/Security/Pipeline/Enrichment on row 1, Automation/Retention/Sending Profiles on row 2), no visible patch/seam in the screenshot |

**Item 4 totals:** 1 row — **1 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Item 5 — Sending profile form

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | File upload (PDF/docx/txt/md) reusing the Setup tab's `extract_resume_profile` text-extraction flow | Yes (reused, unchanged) | Yes | Reuses existing `POST /profile/upload` → `resume_parse.extract_text` (`backend/resume_parse.py`, untouched) for text extraction; UI: `index.html:850-859` (upload button + hidden file input), JS at `initSendingProfilesUI`'s `fileInput` change handler | **BUILT** — browser-verified: uploaded a real `.txt` file via the file-input, extracted text appeared verbatim in the textarea (`document.getElementById('sending-profile-resume').value` read back correctly) |
| 2 | Keep the actual uploaded file (not just parsed text) for "PDF attachment" resume-delivery mode | Yes | Yes | New table columns `sending_profiles.resume_file_path`/`resume_file_name` (`backend/db.py:210-215`, `set_sending_profile_resume_file` at `:875-883`); new `POST /sending-profiles/{id}/resume-file` (`backend/app.py:640-660`, stores into gitignored `backend/resumes/`); `send_outreach` now prefers this real file over `resume_pdf.render_resume_pdf()`'s from-text fallback when present (`backend/app.py:567-600`, with a `generated_attachment` flag so only the fpdf2 temp file — never a persisted upload — gets deleted after send); `DELETE /sending-profiles/{id}` cleans up the file on disk (`backend/app.py:662-667`) | **BUILT** — curl-verified full lifecycle: created a profile, uploaded a `.pdf`-named file via multipart, confirmed `resume_file_path`/`resume_file_name` persisted and the file existed on disk at `backend/resumes/profile_{id}.pdf`, deleted the profile, confirmed the file was removed. Browser-verified separately: uploaded via the real file-input, saved, list showed a "📎 test_resume.txt" badge (`index.html:3605`), backend confirmed `backend/resumes/profile_8.txt` existed with the right content — cleaned up after |
| 3 | Basic validation: required name, portfolio URL format check, warn (don't block) if resume is empty | No new backend | Yes | `index.html`'s save handler (`initSendingProfilesUI`, ~`index.html:3643-3686`): blocks on empty name (pre-existing check, kept), blocks on a portfolio value that fails `PORTFOLIO_URL_RE` (`index.html:3536`, new), and — only for resume-empty — proceeds with the save but appends a non-blocking warning to the success status message | **BUILT** — browser-verified all three paths live: empty name → status "Name is required." (save blocked, confirmed via DOM read); portfolio "not a url at all" → status "Portfolio URL doesn't look valid..." (save blocked); valid portfolio + resume text present → "Saved." with no warning |
| 4 | Restructure form into grouped sections (identity, resume, presentation) | No | Yes | `index.html:838-869` — three `.sending-profile-form-section` blocks with `<h4>Identity</h4>` / `<h4>Resume</h4>` / `<h4>Presentation</h4>` headings, divider CSS at `index.html:507-513` | **BUILT** — browser-verified: `find()` located all three section headings by exact text inside the sending-profile form |

**Item 5 totals:** 4 rows — **4 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Item 6 — Enrichment provider order: drag-to-reorder

Reasonably scoped (one list, six items, no cross-list dragging) — built rather than left as up/down
buttons.

| # | Item | Evidence | Status |
|---|---|---|---|
| 1 | Replace up/down-arrow buttons with drag-to-reorder | `index.html`'s `renderOrderList` (~`index.html:3335-3378`) now renders each row `draggable="true"` with a `⠿` handle and wires native `dragstart`/`dragover`/`drop` listeners that splice `currentOrder` and re-render; a keyboard fallback (`ArrowUp`/`ArrowDown` on a focused, `tabindex="0"` handle) covers the case HTML5 drag has no keyboard equivalent for, since the old up/down buttons were the only keyboard-operable path this replaced | **BUILT, with a verification caveat** — browser-verified the render (6 rows, each with a handle, correct initial order) and the **keyboard-reorder path end-to-end**: focused the "hunter" handle, pressed ArrowUp, watched it swap to position 1 live, then Saved and confirmed via curl that `provider_order` persisted as `["hunter","company_page_scraper",...]`. The **mouse-drag path could not be verified through this session's browser-automation tool**: a synthetic `left_click_drag` (plain mousedown/mousemove/mouseup) does not trigger Chrome's native `dragstart`/`dragover`/`drop` sequence — that requires a real OS-level drag gesture CDP's basic mouse-event dispatch doesn't replicate, a known gap in automated testing of HTML5 native drag-and-drop, not evidence of a code defect. The listeners are standard-compliant HTML5 DnD attached to the correct elements (confirmed by reading the rendered DOM); a real user mouse-drag exercises the identical `drop` handler the keyboard path already proved works. Order was reset to the default afterward |

**Item 6 totals:** 1 row — **1 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT** (verification caveat noted above, not a status downgrade).

---

## Totals check

| Item | Rows | BUILT | BACKEND-ONLY | STUBBED | NOT BUILT |
|---|---|---|---|---|---|
| 1. Dry-run mode | 5 | 5 | 0 | 0 | 0 |
| 2. Enrichment credentials | 2 | 2 | 0 | 0 | 0 |
| 3. Industry classification | 1 | 1 | 0 | 0 | 0 |
| 4. Settings tab bar CSS | 1 | 1 | 0 | 0 | 0 |
| 5. Sending profile form | 4 | 4 | 0 | 0 | 0 |
| 6. Drag-to-reorder | 1 | 1 | 0 | 0 | 0 |
| **Combined** | **14** | **14** | **0** | **0** | **0** |

5 + 2 + 1 + 1 + 4 + 1 = 14 rows listed; 14 + 0 + 0 + 0 = 14 counted. ✓ Sums match.

## What this pass did not touch

No changes to the Review Queue tab or the other Settings subtabs (Automation/Retention/Security/
Backend/LLM APIs/LLM Usage) beyond the one shared CSS-selector fix in item 4, which affects all of
them equally. RocketReach/Apollo/ContactOut/Snov remain unimplemented stubs by design — this pass
made that fact visible and gave them a place to hold a key for whenever a real integration gets
built, it did not implement any of the four APIs (no accounts/keys existed to build against, same
constraint noted in the master plan's "not built" list). The company-size-aware half of decision #6
(tiering also considering headcount, not just title) remains unbuilt, unrelated to this session's
brief. `backend/resumes/` and the new `sending_profiles` columns are additive — no existing sending
profile lost data, and profiles created before this session simply have `resume_file_path: null`
until a file is uploaded for them.
