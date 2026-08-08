# Master Plan Audit — 2026-08-08 19:44

Audits `DOCS/job-watcher-master-plan.md`'s §3 decision log (30 items) and §6
settings inventory (decomposed into 23 atomic controls) against the actual
code as of this date, following the merge/push of the Phase 0-7 execution
work. Every row was verified by grepping/reading the actual backend routes,
DB schema, and `index.html` — not from memory.

**Status legend**
- **BUILT** — backend logic AND a visible UI element both exist
- **BACKEND-ONLY** — logic exists in code but no UI surfaces it (invisible
  to the user even though it "exists"; API/curl-reachable only)
- **STUBBED** — UI element exists but no real logic behind it
- **NOT BUILT** — neither exists

---

## Decision Log Audit (plan §3) — 30 rows

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Job source scope (dynamic/sortable/user-selectable) | Partial | Partial | `data/companies.json` (4 hand-edited entries); enable/disable toggle: `backend/db.py:315` `save_scope`, `index.html:810,1842,2183` `#scope-companies` checkboxes | **BUILT** (enable/disable only — add/remove/sort do not exist anywhere; `companies.json` stays hand-edited per CLAUDE.md's own pre-existing convention) |
| 2 | Source types (ATS feeds + niche remote APIs); LinkedIn/Indeed unscraped, "flagged" | Partial | None | `backend/providers/job_source.py` (Greenhouse/Lever/SmartRecruiters only, no niche API); no LinkedIn/Indeed code anywhere (correct by omission); no "flag" mechanism found | **NOT BUILT** (niche-API half never attempted — not blocked by a key, just not attempted; the "flag" requirement has no surfaced warning anywhere) |
| 3 | Application method — never via portal, always email | N/A | N/A | No ATS-submission code exists anywhere in the repo; `/contacts/{id}/outreach` (`app.py:451`) always sends email | **BACKEND-ONLY** (true by architecture/absence — no UI applicable, this isn't a togglable setting) |
| 4 | Contact discovery — hunt named individuals, fallback to info@/careers@ | Partial | None | Hunting: `backend/enrichment.py` (`CompanyPageScraperProvider`, `HunterProvider`); fallback synthesis: grepped for `info@`/`careers@` — no matches anywhere | **BACKEND-ONLY** (hunting logic real; the info@/careers@ fallback specifically named in the decision was never built — not attempted) |
| 5 | Contact tiers shown — all tiers, named fill quota first | Yes | None | `backend/db.py` `get_contacts_for_posting` orders by tier; `pipeline.get_queue` (`pipeline.py`) never drops a tier | **BACKEND-ONLY** (no queue UI exists to see this at all) |
| 6 | Decision-maker targeting — size-aware, titles+thresholds editable | Partial | None | `label_tier` is title-match only, `backend/enrichment.py:71-84` (docstring explicitly says size-aware part not implemented); titles/thresholds editable via `enrichment.py:26,35` + `app.py:746,752` | **BACKEND-ONLY** (settings exist backend-only; the "size-aware" half of the decision itself was never wired) |
| 7 | Enrichment services — free scrape first → paid chain, per-industry selectable | Yes | None | `backend/providers/enrichment.py`, `backend/enrichment.py:44` `get_provider_order(industry)`, `app.py:758` | **BACKEND-ONLY** |
| 8 | No hardcoded services — swappable Provider adapter for everything | Yes | N/A | `backend/providers/{job_source,enrichment,email,group_discovery}.py` — 4 ABCs | **BACKEND-ONLY** (pure architecture decision — no UI applicable) |
| 9 | Group source automation — TG/Discord auto-scan; WhatsApp/Slack manual-add | Yes | Partial | Scan: `backend/providers/group_discovery.py`, `app.py:814` `/group-discovery/scan`; manual-add: `index.html:846-852` (pre-existing, not built this session) | **BACKEND-ONLY** (auto-scan half has zero UI; manual-add half already had UI before this session) |
| 10 | Daily quota + job/outreach split ratio, user-set | Yes | None | `backend/pipeline.py:13` `get_pipeline_settings`, `app.py:577,582` | **BACKEND-ONLY** |
| 11 | Sender infra — Workspace domain, SPF/DKIM/DMARC, warm-up | No | No | Grep for workspace/spf/dkim/dmarc: no matches; `gmail.py` still personal-OAuth-only | **NOT BUILT** — blocked by needing a real paid domain + Google Workspace signup (explicitly stated, not just unattempted) |
| 12 | Work-mode 3-way slider feeding scoring | Yes | None | `backend/scoring.py:20` `get_work_mode_weights` (normalizes to 1); `app.py:684,689` | **BACKEND-ONLY** |
| 13 | Dedup on (company, contact) pair | Yes | N/A | `backend/db.py:456` `contact_exists(company, email)` | **BACKEND-ONLY** (automatic behavior, no UI applicable) |
| 14 | Scoring — hybrid rule-based + LLM re-rank, rule-based-only toggle | Partial | None | Rule-based exists (`scoring.py`); grep for `score_posting`/LLM ranking task in `llm.py`: none; grep for `rule_based_only` toggle: none | **NOT BUILT** (the decision's defining feature — the LLM half and the toggle — is absent; plain rule-based scoring is covered separately under Phase 1/settings #14 below) |
| 15 | Run cadence, user-configurable | Yes | None | `backend/scheduler.py:39` `get_cadence_settings`, `app.py:771,780` | **BACKEND-ONLY** |
| 16 | Missed run auto-catches-up | Yes | N/A | `backend/scheduler.py:107` `_missed_run` | **BACKEND-ONLY** (automatic, no UI applicable) |
| 17 | Review queue actions — edit/snooze/reject | No | No | Grep for snooze/reject/edit-draft: no matches anywhere | **NOT BUILT** — not attempted (no external blocker, purely a build gap) |
| 18 | Message tailoring — LLM by default, templated fallback in rule-based-only mode | Partial | Partial | LLM-by-default: `llm.draft_cold_email` (pre-existing), UI in Settings > LLM APIs (pre-existing); templated fallback: no rule-based-only mode exists at all | **BUILT** for the default-LLM half (pre-existing); fallback half is **NOT BUILT** — noted, not double-counted |
| 19 | Reply detection — sent→replied→interview | Partial | None | `backend/gmail.py` `check_replies` (readonly scope); `backend/reply_check.py:26` advances sent→replied; grep for "interview" status: no matches | **BACKEND-ONLY** (sent→replied works backend-only; the "interview" stage was never implemented) |
| 20 | Compliance — negative-sentiment auto-suppress, manual re-approach | Yes | Partial | `backend/reply_check.py` + `llm.classify_sentiment`; override path reuses pre-existing `PATCH /contacts/{id}/status` (`app.py:418`); status shown as plain text (`index.html:1661`) but no dedicated "re-approach" button | **BACKEND-ONLY** (contact stays visible via the existing generic status text, but no purpose-built re-approach UI exists) |
| 21 | Resume delivery — HTML/PDF/both, overridable per item, detach option | Partial | None | Delivery-mode logic: `app.py:514` reads `pipeline_resume_delivery` setting; per-item override param: not found in `/contacts/{id}/outreach`'s body; "detach": no matches anywhere | **BACKEND-ONLY** (default-mode logic works backend-only; override-per-item and detach were never built) |
| 22 | Candidate model — Profile + separate Sending Profiles table | Yes | None | `backend/db.py` `sending_profiles` table (new); pre-existing `profile` table unchanged | **BACKEND-ONLY** |
| 23 | Alias selection — rule-based default, overridable per item | Partial | None | Default logic: `backend/pipeline.py:33` `select_sending_profile`; override param: not found in outreach endpoint | **BACKEND-ONLY** (default rule works backend-only; per-item override was never built) |
| 24 | Security — master-password vault | Yes | Yes | `backend/vault.py:71,88`; UI: Setup > Security subtab + blocking unlock modal, `index.html:2692-2790` | **BUILT** (not activated by default — that's intentional — but the feature itself is real, backend+UI) |
| 25 | Data location — stays in Drive-synced path | N/A | N/A | Repo is literally at `H:\My Drive\Dev\Dev_jobSearch` (confirmed by this session's own Drive-lock incident) | **BACKEND-ONLY** (operational fact, not a code feature — no backend/UI genuinely applicable) |
| 26 | Hosting — laptop now, cloud VM deferred | Yes | N/A | `app.py` binds `127.0.0.1` only (pre-existing); no VM/deploy code (correctly deferred) | **BACKEND-ONLY** (operational decision — deferral is correct per plan, not a gap) |
| 27 | Notifications — Telegram, batch-ready + failures | Yes | None | `backend/notify_telegram.py`; called from `scheduler.py:91,103` | **BACKEND-ONLY** |
| 28 | Dedup of duplicate postings — confidence-tiered auto-merge | No | No | Grep for merge/duplicate/confidence logic in `db.py`/`scoring.py`: no real implementation found | **NOT BUILT** — not attempted (no external blocker; needs fuzzy title/location matching, a build task) |
| 29 | Data retention — archive→delete→pin→delete/export | Yes | No | `backend/retention.py:23` `sweep`; routes `app.py:657-679,380,444,646,673` | **BACKEND-ONLY** |
| 30 | Failure visibility — broken scraper/token/integration via Telegram | Partial | None | `scheduler.run_daily_batch` (`scheduler.py:60`) notifies on whole-batch exceptions only; individual integration failures (single outreach send, ingest scripts) still just print to stderr, no Telegram alert | **BACKEND-ONLY** (partial coverage — only scheduled-batch-level failures are surfaced, not every integration failure point) |

---

## Settings Inventory Audit (plan §6, decomposed into 23 atomic controls)

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Job source list — add | No | No | No route/UI found | **NOT BUILT** — not attempted |
| 2 | Job source list — remove | No | No | No route/UI found | **NOT BUILT** — not attempted |
| 3 | Job source list — enable/disable | Yes | Yes | `db.py:315` `save_scope`; `index.html:810,1842,2183` | **BUILT** (pre-existing, not from this session) |
| 4 | Job source list — sort/reorder | No | No | No route/UI found | **NOT BUILT** — not attempted |
| 5 | Enrichment provider order — global default | Yes | No | `enrichment.py:44` `get_provider_order()`; `app.py:758` | **BACKEND-ONLY** |
| 6 | Enrichment provider order — per-industry override | Yes | No | `enrichment.py:44` (`industry` param); `app.py:758` | **BACKEND-ONLY** |
| 7 | Daily quota (number) | Yes | No | `pipeline.py:13`; `app.py:577,582` | **BACKEND-ONLY** |
| 8 | Job-application vs cold-outreach split ratio | Yes | No | `pipeline.py:13` `split_ratio`; `app.py:577,582` | **BACKEND-ONLY** |
| 9 | Decision-maker title list | Yes | No | `enrichment.py:26`; `app.py:746` | **BACKEND-ONLY** |
| 10 | Company-size thresholds | Yes | No | `enrichment.py:35`; `app.py:752` | **BACKEND-ONLY** (also unused by the actual tiering logic — see decision #6) |
| 11 | Work-mode slider — remote weight | Yes | No | `scoring.py:20`; `app.py:684,689` | **BACKEND-ONLY** |
| 12 | Work-mode slider — hybrid weight | Yes | No | same as above | **BACKEND-ONLY** |
| 13 | Work-mode slider — onsite weight | Yes | No | same as above | **BACKEND-ONLY** |
| 14 | Rule-based-only mode toggle | No | No | Grep for `rule_based_only`/equivalent: no matches | **NOT BUILT** — not attempted |
| 15 | Run cadence (per day / N×day / every N days) | Yes | No | `scheduler.py:39`; `app.py:771,780` | **BACKEND-ONLY** |
| 16 | Resume-delivery default — cold-intro | Yes | No | `pipeline.py` `resume_delivery` dict; `app.py:514,577,582` | **BACKEND-ONLY** |
| 17 | Resume-delivery default — job-application | Yes | No | same as above | **BACKEND-ONLY** |
| 18 | Retention — auto-delete period (days) | Yes | No | `retention.py:15,23`; `app.py:657,662` | **BACKEND-ONLY** |
| 19 | Retention — keep-forever pin | Yes | No | `db.py` `postings.pinned` column, checked by `archive_expired_postings`/`delete_expired_archived_postings`; `app.py:628` PATCH | **BACKEND-ONLY** |
| 20 | Notification channel target (Telegram) | Partial | No | `backend/config.example.json` `telegram.notify_chat`; `notify_telegram.py:39` — config-file only, no settings route or UI at all | **BACKEND-ONLY** (not even API-reachable — config.json edit only) |
| 21 | Sending profiles/aliases — create | Yes | No | `db.py` `create_sending_profile`; `app.py:551` | **BACKEND-ONLY** |
| 22 | Sending profiles/aliases — edit | Yes | No | `db.py` `update_sending_profile`; `app.py:559` | **BACKEND-ONLY** |
| 23 | Sending profiles/aliases — delete | Yes | No | `db.py` `delete_sending_profile`; `app.py:565` | **BACKEND-ONLY** |

---

## Totals

**Decisions (30):** BUILT = 3 (#1, #18, #24) · BACKEND-ONLY = 22 (#3,4,5,6,7,8,9,10,12,13,15,16,19,20,21,22,23,25,26,27,29,30) · STUBBED = 0 · NOT BUILT = 5 (#2,11,14,17,28)
→ 3 + 22 + 0 + 5 = 30 ✓

**Settings (23):** BUILT = 1 (#3) · BACKEND-ONLY = 18 (#5-13,15-23) · STUBBED = 0 · NOT BUILT = 4 (#1,2,4,14)
→ 1 + 18 + 0 + 4 = 23 ✓

**Grand total — 53 rows** (§6's 12 bullets decompose to 23 atomic items, not 25 as estimated; not forced to match):

| Status | Count |
|---|---|
| BUILT | 4 |
| BACKEND-ONLY | 40 |
| STUBBED | 0 |
| NOT BUILT | 9 |

4 + 40 + 0 + 9 = **53**, matching the 30 + 23 rows actually printed above.

## Bottom line

The overwhelming majority of what shipped in the Phase 0-7 execution pass is
real, working backend logic with **zero settings UI** — everything beyond
the vault unlock flow and the live Search Results tab is curl/API-reachable
only, not clickable anywhere in `index.html`. Nothing audited is a UI-only
stub (0 STUBBED is a genuine finding, not an omission). Of the 9 NOT BUILT
items, only 1 (#11, Google Workspace sender infrastructure) is blocked by a
real external requirement (a paid domain + Workspace signup); the other 8
(niche job-board APIs, info@/careers@ contact fallback, review-queue
edit/snooze/reject, the rule-based-only toggle, LLM posting re-scoring,
confidence-tiered posting dedup/merge, and job-source add/remove/sort) were
simply never attempted — no credential or account stood in the way.
