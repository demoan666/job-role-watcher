# Job Watcher — Master Plan

Prepared for execution by Claude CLI on top of the existing repo at
`Dev_jobSearch`. This is a plan, not code. Preserve existing UI/styling and
reuse inventoried components (buttons, tabs, forms, card renderers) wherever
a new feature maps onto an existing pattern instead of introducing a new one.

---

## 1. Current state (audited, not assumed)

- **Frontend**: single `index.html`, vanilla JS, no framework, no build step.
  `BACKEND` URL hardcoded to `127.0.0.1:8420`. Tabs: Setup, Leads, Outreach
  (all fully wired), Search Results (reads static `data/postings.json` /
  `archive.json` directly — bypasses backend entirely).
- **Backend**: FastAPI, 27 routes, raw `sqlite3` (no ORM). DB `backend/app.db`:
  tables `profile` (single-row, `CHECK(id=1)`), `contacts`, `leads`,
  `sent_emails`, `settings`, `llm_usage`.
- **LLM layer** (`backend/llm.py`): already a proper swappable-provider
  dispatch — Anthropic / OpenAI / Google + user-added custom OpenAI-compatible
  providers, keys in `backend/config.json` (gitignored). **This is the pattern
  every new provider category below replicates.**
- **Outreach pipeline (live)**: Telegram (own account, Telethon) + Slack
  (user token, polling) → `POST /leads/capture` → `llm.triage_message()` →
  DB. Manual per-contact: `POST /contacts/{id}/outreach` → dedup + daily cap
  check → `llm.draft_cold_email()` → Gmail API (OAuth, send-only scope) →
  logged in `sent_emails`.
- **Postings pipeline (disconnected)**: `scripts/fetch_postings.py`, run
  daily via GitHub Actions cron, pulls Greenhouse/Lever/SmartRecruiters public
  JSON APIs for companies listed in `data/companies.json`, regex-based
  include/exclude filtering (no scoring, no LLM), writes static JSON files
  read directly by the frontend. No DB row, no state, no backend route.
- **Gaps confirmed by audit**: no job-source or enrichment provider
  abstraction, no contact-enrichment integration, no bulk-send system, no
  scheduler, no scoring/ranking, single hardcoded profile row.

---

## 2. What changed the whole shape of the plan

Original framing assumed the app would submit applications through employer
ATS portals (Greenhouse forms, LinkedIn Easy Apply, etc.). **That's now out
of scope entirely.** The actual intent: use portals and job boards purely as
*discovery* — find the posting, find the company, find a specific human
decision-maker — then apply by **emailing that person directly from your own
system**, bypassing the employer's application portal completely on every
channel, not just LinkedIn.

Effect: there is no ATS-form-filling problem to solve (removes the single
most fragile, most bot-detectable piece of the original scope). Job
applications and cold outreach are no longer two systems — both terminate in
the same action (find person → tailor message → send → log), so they share
one contact-resolution step, one send engine, and one ledger.

---

## 3. Decision log

| # | Decision | Locked answer |
|---|---|---|
| 1 | Job source scope | Mainstream job portals only for v1; source list dynamic, sortable, user-selectable |
| 2 | Source types included | ATS JSON feeds (Greenhouse/Lever/SmartRecruiters/etc, expandable) + niche remote-job APIs. LinkedIn/Indeed **not scraped automatically** — see Open Risks §7, flagged, not silently assumed |
| 3 | Application method | Never through the employer's portal, on any source. Always: discover → find contact → send direct email from the app |
| 4 | Contact discovery | Actively hunt named individuals (LinkedIn + other public sources), fall back to info@/careers@/team-page names only if hunting fails |
| 5 | Contact tiers shown | All tiers always shown in queue (named decision-maker / named-junior / generic inbox), sorted so named contacts fill quota first — never silently filtered |
| 6 | Decision-maker targeting | Size-aware: small company → founder/owner, large company → department head. Title list and size thresholds both user-editable in Settings. Company size added as a search-criteria filter |
| 7 | Enrichment services | Company "team" page scrape first (free) → paid enrichment API chain (Hunter.io free tier default, RocketReach/Apollo/ContactOut/Snov as alternates) — fully pluggable per industry, selectable in Settings |
| 8 | No hardcoded services | Every external dependency (LLM, enrichment, job source, email, group discovery) goes through a swappable Provider adapter, same shape as the existing `llm.py` |
| 9 | Group source automation | Telegram + Discord: automated discovery scan against public directories (t.me, Disboard/top.gg), keyword-based. WhatsApp + Slack: manual-add only (no public directory exists for either) |
| 10 | Daily quota | User-set number, not hardcoded. Split ratio between job-postings and cold-outreach also user-set, not hardcoded |
| 11 | Sender infrastructure | Google Workspace on owned domain (not personal Gmail), same Gmail API code path, with SPF/DKIM/DMARC configured and a 2–3 week warm-up ramp before reaching full quota |
| 12 | Work-mode priority | Normalized 3-way slider (remote/hybrid/onsite weights sum to 1) feeding the scoring formula — not a hard filter |
| 13 | Dedup/suppression scope | Block on (company + specific contact person) pair, not company-level. A new named person or a materially different role is a legitimate new contact |
| 14 | Scoring method | Hybrid: cheap rule-based weighted filter narrows the pool → LLM scores/ranks the shortlist for nuance. Settings toggle to run rule-based-only (skips LLM, for cost control) |
| 15 | Run cadence | Fixed scheduled batch generation, frequency user-configurable (per day / twice daily / every N days). Quota resets each cycle, unused slots do not carry forward |
| 16 | Missed run | If the scheduled trigger is missed (laptop asleep/off), the batch auto-runs on next boot/wake rather than waiting for the next cycle |
| 17 | Review queue actions | Edit message/resume before sending, snooze (doesn't burn a quota slot), reject = discard only (no auto-suppression on reject) |
| 18 | Message tailoring | LLM-tailored per send by default (reuses `llm.draft_cold_email()` pattern). Falls back to templated mail-merge only when rule-based-only mode is on |
| 19 | Reply detection | Narrow Gmail read scope — read-only on threads matching sent-message subjects, not full inbox. Auto-updates status sent → replied → interview |
| 20 | Compliance / opt-out | Negative-sentiment replies auto-classified (LLM) and auto-suppress that contact. Fully overridable — suppressed contacts stay visible, flagged, with a manual "re-approach" action |
| 21 | Resume delivery | Per send-type default: HTML-in-body only for cold intros, PDF attachment for direct job applications, "both" available. Always overridable per item, with a detach option |
| 22 | Candidate model | One consolidated **Profile** (combobox-driven: skills, industries, keywords, location/visa, work-mode) drives search/matching. Separate, multiple **Sending Profiles / Aliases** (e.g. Individual, Studio) each carry their own resume, portfolio, tone, and signature — created via a Settings form, own DB table |
| 23 | Alias selection | Rule-based default (Studio for freelance/project-shaped leads if one is defined, else Individual; job applications default Individual). Always overridable per item |
| 24 | Security | Master-password vault encrypting all stored credentials (Gmail OAuth, LLM keys, enrichment keys) — one password unlocks the app each session |
| 25 | Data location | Repo + working folder stays in the Google Drive–synced path (user's explicit call — see Open Risks §1 for the trade-off this carries) |
| 26 | Hosting | Runs on the user's own laptop for now (24/7, Task Scheduler wakes it for the scheduled batch). Cloud VM deferred until the system proves valuable |
| 27 | Notifications | Telegram message (via the app's existing Telegram account, no phone number needed) when the daily batch is ready, and on scraper/integration failures |
| 28 | Dedup of duplicate postings | Confidence-tiered auto-merge: high-confidence (same company + near-identical title/location) auto-merges; medium-confidence flags for manual review via a "merged entries" view; low-confidence stays separate |
| 29 | Data retention | Auto-archive on expiry/rejection → 30-day default auto-delete (user-configurable) → keep-forever pin available → individual delete, export-to-file, delete-all, and multi-select delete all present |
| 30 | Failure visibility | Broken scraper / expired token / failed integration surfaces via the same Telegram channel, not silent |

---

## 4. Provider categories (all new, following the existing `llm.py` shape)

| Category | Status | Implementations |
|---|---|---|
| `LLMProvider` | Exists, reuse as-is | Anthropic, OpenAI, Google, custom OpenAI-compatible |
| `JobSourceProvider` | New — generalize existing hardcoded fetchers | Greenhouse, Lever, SmartRecruiters (already exist as functions, wrap as adapters), + niche APIs, source list user-editable |
| `EnrichmentProvider` | New | Company-page scraper (free, tried first), Hunter.io, RocketReach, Apollo, ContactOut, Snov/FindyMail — selectable/orderable per industry |
| `EmailProvider` | New — wrap existing Gmail code | Google Workspace via Gmail API (initial/only real implementation, but built behind the interface so it's swappable later) |
| `GroupDiscoveryProvider` | New | Telegram public-directory scanner, Discord public-directory scanner |

---

## 5. New/changed data model (conceptual — not schema DDL)

- **`postings`** (new table) — gives postings the state `leads` already has:
  score, work-mode tag, company-size tag, contact-tier, merge/dedupe status,
  archive/retention flags. Backend gains a real `/postings` route; frontend
  Search Results tab switches from static JSON to this route.
- **`sending_profiles`** (new table) — aliases (Individual, Studio, etc.),
  each with resume, portfolio, tone, signature. Separate from the existing
  single-row `profile`, which stays as the one candidate-identity/search
  driver.
- **Unified send ledger** (new, or `sent_emails` extended) — one shared log
  across both postings and leads, keyed by (company, contact), holding
  status timeline (sent → replied → interview → suppressed) — this is what
  makes the cross-pipeline dedup rule (decision #13) actually enforceable.
- **`profile`** — no structural change needed; visa/location/work-mode
  become combobox fields already read by matching.
- **Settings** — extended per the inventory in §6.

---

## 6. Settings inventory (every user-adjustable value locked in this plan)

- Job source list (add/remove/enable/sort)
- Enrichment provider order/selection (global default + per-industry override)
- Daily quota (number)
- Job-application vs cold-outreach split ratio
- Decision-maker title list + company-size thresholds
- Work-mode priority sliders (remote/hybrid/onsite, normalized to 1)
- Rule-based-only mode toggle (disables LLM scoring + LLM tailoring, falls
  back to templated messages)
- Run cadence (per day / N times per day / every N days)
- Resume-delivery default per send-type (HTML-body / PDF / both)
- Retention: auto-delete period (default 30 days), keep-forever pin
- Notification channel target (Telegram)
- Sending profiles/aliases (create/edit via form)

---

## 7. Build sequence

**Phase 0 — Foundations**
Master-password vault wrapping all existing + new credentials. Nightly local
DB backup (load-bearing — see Open Risks §1). Scaffold the four new provider
interfaces even before every implementation exists.
*Start Workspace domain + DNS (SPF/DKIM/DMARC) setup here in parallel — DNS
propagation takes time and nothing else blocks on it.*

**Phase 1 — Postings join the backend**
New `postings` table + `/postings` route. `fetch_postings.py` writes to DB
instead of/alongside static JSON. Frontend Search Results tab switches to
live route. Rule-based weighted scoring (replacing binary regex) with
configurable weights, including the work-mode sliders.

**Phase 2 — Contact resolution**
Company-page scraper first, then `EnrichmentProvider` chain (Hunter.io free
tier default). Contact-tier labeling. Decision-maker title/size-threshold
logic.

**Phase 3 — Unified send pipeline**
Merge postings + leads into one centralized review queue. Unified send
ledger with (company, contact) dedup. LLM tailoring generalized from
`draft_cold_email()`. Resume-delivery mode logic. Cut over to Workspace
domain sending with warm-up ramp. Quota + split-ratio enforcement. Alias
auto-selection logic.

**Phase 4 — Scheduling & notifications**
Scheduled batch generation (Task Scheduler, wake-on-schedule + missed-run
catch-up). Telegram notification bot for "batch ready" and failures. Queue
actions: edit, snooze, reject. Recommended: short grace-window undo before
a send actually fires (not yet explicitly confirmed — flag for a quick yes/no
before building).

**Phase 5 — Reply loop & compliance**
Narrow Gmail read-scope reply detection. Sentiment auto-suppression with
manual override/re-approach. Funnel status tracking.

**Phase 6 — Group discovery automation**
Telegram + Discord public-directory scanners. Manual-add lists for
WhatsApp/Slack.

**Phase 7 — Retention & polish**
Archive bin, auto-delete timer, pin, manual/bulk delete, export-to-file.
Recommended, not yet confirmed: dry-run/test mode (simulate full pipeline,
no real sends) and a monthly LLM/enrichment spend cap — flag for quick
confirmation before or during this phase.

---

## 8. Frontend/library notes

Keep the current zero-build-step vanilla JS approach — it's a real strength,
not a limitation to fix. Pull in small targeted libraries via CDN only where
hand-rolling is genuinely painful:
- A data-table library once the review queue is regularly showing 50+ scored
  items with sort/filter (current hand-written table won't scale well past
  that).
- A PDF-generation library if/when the HTML-resume needs a PDF fallback path.

Backend gains new Python dependencies (not CDN): an encryption library for
the credential vault, a scheduler library for the batch job, possibly a
headless-browser library for Discord/Telegram directory scanning.

---

## 9. Services & budget tracker

*Verify current pricing at signup — noted where figures are from an earlier
live check in this session vs. general estimate.*

| Service | Purpose | Est. cost | Notes |
|---|---|---|---|
| Google Workspace | Domain email sending | ~$6–12/mo (1 seat) | Required for sender reputation — do not skip |
| Domain registration | Required for Workspace | ~$10–15/yr | One-time-ish, renews annually |
| Hunter.io | Contact enrichment | Free tier (25–50/mo) → $34/mo Starter (2,000 credits) if outgrown | Checked live this session; realistic volume likely stays on free tier |
| RocketReach / Apollo / ContactOut / Snov | Alternate/industry-specific enrichment | Verify at signup | Only add if Hunter's hit rate is weak for your specific industry |
| LLM API (scoring + tailoring) | Anthropic/OpenAI/Google, already pluggable | ~$1–5/mo budget-tier models, ~$12–18/mo mid-tier, at ~50 tailored sends/day | Scoring pass is cheaper — only runs on the rule-filtered shortlist |
| Cloud VM (deferred) | Later, always-on hosting | ~$5–6/mo (Hetzner/DigitalOcean) | Not needed for laptop-based v1 |
| Telegram / Discord | Notifications + group scanning | Free | Uses existing account infra |
| WhatsApp Business API | Excluded by decision | N/A | Rejected — cost + account-ban risk not worth it |

**Revisit for bundling**: some sales/enrichment platforms (Apollo in
particular) bundle contact database + email sending/sequencing in one
subscription. Worth reassessing once real usage volume is known, per your
request to circle back on this.

---

## 10. Open risks (explicit, not buried)

1. **Google Drive sync stays on, by your choice.** The live SQLite DB and
   (soon) the encrypted credential vault sit in a folder Google Drive
   actively re-uploads on every write. Risk: sync-timing corruption of the
   DB, and secrets being copied to Drive's cloud + any other device on that
   account (the vault encryption limits exposure of the *contents*, but not
   the fact that the file itself is being synced). Mitigation in place:
   nightly local backup — now load-bearing, not optional.
2. **LinkedIn scraping was flagged as excluded from automation (Q3, "no bot
   detection risk"), but that decision was made before the apply-method
   pivot.** As currently locked, LinkedIn postings are not automatically
   scraped at all — confirm this is still what you want, since scraping
   (reading) and applying (acting) carry different risk profiles and the
   earlier answer was specifically about applying.
3. **Deliverability is an ongoing risk, not a one-time fix.** Domain +
   SPF/DKIM/DMARC + warm-up ramp gets you a real shot at inbox placement,
   but sustained 50/day-equivalent volume to strangers is something Gmail's
   spam systems watch continuously — this needs monitoring, not just setup.
4. **"Apply via portal only" employers.** Some job postings will explicitly
   state applications must go through their portal. Bypassing that is a
   per-company judgment call the queue should surface (e.g. a visible flag),
   not something the system silently decides for you.
5. **Group-discovery scraping (Telegram/Discord public directories) is
   inherently less stable than API-based sources** — directory sites can
   change layout or rate-limit, same fragility class as the original
   HTML-fallback scraper concern.
6. **Two items from Phase 4/7 are recommendations, not yet explicitly
   locked**: send grace-window undo, dry-run/test mode, monthly spend cap.
   Flagged here so they don't get built (or skipped) on an assumption.
