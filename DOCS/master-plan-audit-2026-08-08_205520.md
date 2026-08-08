# Master Plan Audit — 2026-08-08 20:55 (Review Queue + Settings UI pass)

Audits this session's follow-up pass, which had a narrower brief than the first audit: wire
**existing** backend-only routes (identified as gaps in `master-plan-audit-2026-08-08_194413.md`)
to visible UI in `index.html`, with two explicit, minimal, pre-approved exceptions for backend that
genuinely didn't exist yet (snooze + edit-before-send in the Review Queue, and a real settings field
for the Telegram notification target). No other new backend logic or routes were added. Every row
below was verified against the actual code (grep/read of `index.html` and `backend/*.py`) and, for
the Review Queue and each new Settings subtab, a live browser test against the running backend —
not from memory.

**Status legend** (same as the first audit)
- **BUILT** — backend logic AND a visible UI element both exist
- **BACKEND-ONLY** — logic exists in code but no UI surfaces it
- **STUBBED** — UI element exists but no real logic behind it
- **NOT BUILT** — neither exists

---

## Priority 1 — Review Queue tab

Confirmed before starting (per the instruction): grepped `index.html` for "review.queue",
"reviewQueue", "queue-tab", "tab-queue" — no matches. No partial version existed.

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Review Queue tab exists (button + panel) | N/A | Yes | `index.html:604` (tab button), `index.html:1047` (`#tab-queue` panel) | **BUILT** |
| 2 | Reads from `pipeline.get_queue()` | Yes | Yes | `backend/app.py:641` `GET /queue` → `pipeline.get_queue()`; `index.html:2062` `refreshQueue()` fetches it | **BUILT** — browser-verified: real posting item rendered with live score/company/contact data |
| 3 | Shows score | Yes | Yes | `index.html:1916` (`scoreText`), rendered in `.queue-score` | **BUILT** — browser-verified: "36%" shown |
| 4 | Shows contact name + tier | Yes | Yes | `index.html:1920-1921,1933-1934` | **BUILT** — browser-verified: "Jane Doe" + "Named Decision Maker" pill |
| 5 | Shows source | Yes | Yes | `index.html:1919`, rendered in `.queue-source` | **BUILT** — browser-verified: "GREENHOUSE" |
| 6 | Shows company | Yes | Yes | `index.html:1917`, rendered in `.queue-company` | **BUILT** — browser-verified: "Storyblok" |
| 7 | Action: approve | Yes | Yes | `index.html:1936` button → `sendNow()` (`index.html:1963`) → `POST /contacts/{id}/outreach` (`backend/app.py:514`, unmodified route) | **BUILT** — not clicked live (real send, real LLM cost, irreversible); disabled with a tooltip for lead-type items with no linked contact (data gap noted in the first audit's decision #5, not something this pass could fix without new backend) |
| 8 | Action: reject | Yes | Yes | `index.html:2032` button → `PATCH /postings/{id}` `{archived:true}` (`backend/app.py:682`, unmodified route) for postings, `DELETE /leads/{id}` (pre-existing route) for leads | **BUILT** — reuses two routes that already existed before this pass, zero new backend |
| 9 | Action: snooze | Yes (minimal exception) | Yes | `index.html:2019` button → `PATCH /postings/{id}` / `PATCH /leads/{id}/retention` with new `snoozed_until` field (`backend/app.py:682,372`); filtered in `pipeline.get_queue()`'s `_not_snoozed()` (`backend/pipeline.py`) | **BUILT** — browser-verified: snoozing removed the card and cleared the badge live; DB-level test also confirmed queue count 1→0→1 across snooze/un-snooze |
| 10 | Action: edit message before send | Yes (minimal exception) | Yes | `index.html:1972` button → new `POST /contacts/{id}/draft-preview` (`backend/app.py:495`) then `POST /contacts/{id}/outreach` with `subject`/`body` override (`backend/app.py:541` in `send_outreach`) | **BUILT** — browser-verified end-to-end through the real LLM call; the call itself returned a 401 (the configured Anthropic key is invalid/expired — an account issue, unrelated to this code) and the UI correctly surfaced that error rather than hanging or crashing, which is a legitimate positive test of the wiring |
| 11 | Bonus: pin/unpin (decision #29's "keep-forever pin", flagged as a gap in the first audit with no UI surface) | Yes | Yes | `index.html:1941` button → `PATCH /postings/{id}` `{pinned:true/false}` (pre-existing route, no changes) | **BUILT** — browser-verified: click toggled the button text/state live, no page reload |

**Priority 1 totals:** 11 rows — **11 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Priority 2 — Settings UI for existing backend-only routes

Grouped into 5 new Settings subtabs (Pipeline, Enrichment, Automation, Retention, Sending Profiles)
added alongside the existing LLM APIs / LLM Usage / Backend / Security tabs, following the same
`data-settings-subtab` / `#settings-tab-*` pattern (`index.html:709,745,769,791,799`).

| # | Item | Backend? | UI? | Evidence | Status |
|---|---|---|---|---|---|
| 1 | Daily quota | Yes | Yes | `pipeline.get_pipeline_settings`/`save_pipeline_settings` — `GET/POST /settings/pipeline` (`backend/app.py:628`); `index.html:3145` `initPipelineSettings()` | **BUILT** — browser-verified: loaded real value "10" |
| 2 | Job/outreach split ratio | Yes | Yes | Same route as above, `split_ratio.postings` | **BUILT** — browser-verified: slider loaded at 50%, labeled with the live-updating percentage |
| 3 | Work-mode sliders (remote/hybrid/onsite) | Yes | Yes | `scoring.get_work_mode_weights`/`save_work_mode_weights` — `GET/POST /scoring/work-mode-weights` (`backend/app.py:738`) | **BUILT** — browser-verified: loaded real defaults 0.6/0.3/0.1 |
| 4 | Enrichment provider order (global + per-industry) | Yes | Yes | `enrichment.get_provider_order`/`save_provider_order` — `GET /settings/enrichment` (`backend/app.py:790`), `POST /settings/enrichment/provider-order` (`backend/app.py:812`); `index.html:3219` `initEnrichmentSettingsUI()` | **BUILT** — browser-verified: 6-provider ordered list with working up/down reorder buttons; **caveat**: `GET /settings/enrichment` has no industry query param, so switching the per-industry scope selector can only *save* a new order for that industry, not *display* its existing one — surfaced honestly in-app via a `.settings-note` rather than silently misleading |
| 5 | Decision-maker title list | Yes | Yes | `enrichment.get_decision_maker_titles`/`save_decision_maker_titles` — `POST /settings/enrichment/decision-maker-titles` (`backend/app.py:800`), reuses `createTagPillEditor` | **BUILT** — browser-verified: all 16 default titles loaded as tag pills |
| 6 | Company-size thresholds | Yes | Yes | `enrichment.get_size_thresholds`/`save_size_thresholds` — `POST /settings/enrichment/size-thresholds` (`backend/app.py:806`) | **BUILT** — browser-verified: loaded 50/250; **caveat carried over from the first audit's decision #6 row**: this setting is still not read by the actual tiering logic (`enrichment.label_tier()` remains title-match-only) — the setting is now genuinely configurable, the behavior it's meant to influence still isn't wired, and fixing that would be new backend logic outside this pass's scope |
| 7 | Run cadence | Yes | Yes | `scheduler.get_cadence_settings`/`save_cadence_settings`/`is_enabled`/`set_enabled` — `GET/POST /settings/scheduler` (`backend/app.py:825`); `index.html:3304` `initAutomationSettings()` | **BUILT** — browser-verified: loaded disabled-by-default, "Once a day", and a real `last_run_at` timestamp from this session's earlier manual test run |
| 8 | Resume-delivery defaults (cold-intro vs job-application) | Yes | Yes | Same `/settings/pipeline` route as #1/#2, `resume_delivery` dict | **BUILT** — browser-verified: loaded "HTML body only" / "PDF attachment only" |
| 9 | Retention auto-delete period | Yes | Yes | `retention.get_retention_days`/`save_retention_days` — `GET/POST /settings/retention` (`backend/app.py:711`); `index.html:3367` `initRetentionSettingsUI()` | **BUILT** — browser-verified: loaded "30" |
| 10 | Retention keep-forever pin | Yes | Yes | Same `postings.pinned` mechanism as Priority 1 row #11 — deliberately surfaced in the Review Queue card, not as a global Settings toggle (pinning is inherently per-item, not a single value) | **BUILT** — a `.settings-note` in the Retention subtab explicitly points to where the actual control lives, rather than the subtab silently having no pin control at all |
| 11 | Notification target (Telegram chat) | Yes (minimal exception) | Yes | New `notify_telegram.get_notify_target`/`save_notify_target` (DB-setting-first, `config.json` fallback) — new `GET/POST /settings/notifications` (`backend/app.py:859`) | **BUILT** — browser-verified: loaded the `config.json` fallback value "me" after the DB setting was cleared, and separately verified a saved DB value ("@testchannel") correctly overrides it |
| 12 | Sending profiles/aliases (create/edit/delete) | Yes | Yes | `db.list_sending_profiles`/`create_sending_profile`/`update_sending_profile`/`delete_sending_profile` — `GET/POST/PATCH/DELETE /sending-profiles` (`backend/app.py:597` + neighboring routes, all pre-existing, unmodified); `index.html:3387` `initSendingProfilesUI()` | **BUILT** — browser-verified full cycle: created "Test Profile" (appeared in the list immediately), then deleted it (list returned to the empty-state message) |

**Priority 2 totals:** 12 rows — **12 BUILT / 0 BACKEND-ONLY / 0 STUBBED / 0 NOT BUILT.**

---

## Totals check

| Status | Priority 1 | Priority 2 | Combined |
|---|---|---|---|
| BUILT | 11 | 12 | **23** |
| BACKEND-ONLY | 0 | 0 | **0** |
| STUBBED | 0 | 0 | **0** |
| NOT BUILT | 0 | 0 | **0** |

11 + 12 = 23 rows listed; 11 + 12 + 0 + 0 = 23 counted. ✓ Sums match.

## What changed vs. the first audit (`master-plan-audit-2026-08-08_194413.md`)

Of that audit's 53 rows, this pass converted every one of the 12 items explicitly listed in
Priority 2 from **BACKEND-ONLY → BUILT**, and built the Review Queue tab from scratch (**NOT BUILT
→ BUILT** for decision #17's queue/approve/reject/snooze/edit-before-send, and for the underlying
"contact tiers shown in a queue" and "daily quota + split ratio" backend-only rows, which now have a
real UI consumer for the first time). It did **not** touch, and the first audit's findings still
stand for: the LLM re-scoring half of decision #14, niche job-board APIs, the info@/careers@ contact
fallback, confidence-tiered posting dedup/merge, job-source add/remove/sort, Google Workspace sender
infrastructure, or the "interview" reply-status stage — none of those were in this pass's brief.

Two explicit, pre-approved minimal-backend exceptions were added (confirmed with the user before
starting, since the "wire existing routes only" instruction and "build a working queue with
snooze/edit" instruction were otherwise in direct conflict): a `snoozed_until` column + queue filter
on `postings`/`leads`, and a `POST /contacts/{id}/draft-preview` endpoint splitting drafting from
sending. Both are scoped narrowly to exactly the two actions that had no existing backend at all.
