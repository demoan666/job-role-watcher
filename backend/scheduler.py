"""Scheduled batch generation (plan Phase 4, decisions #15/#16/#27).

Runs the daily job: re-sync+re-score postings, enrich a bounded number of
newly-scored postings that still lack a resolved contact, and notify via
Telegram when the batch is ready or when the run failed. Cadence is
user-configurable (per day / N times per day / every N days — decision
#15); a missed run (laptop asleep/off at the scheduled time) auto-runs on
next boot/wake instead of waiting for the next cycle (decision #16).

Disabled by default (scheduler_enabled setting) — this runs real enrichment
scrapes and sends a real Telegram message on an automatic timer, so it's an
opt-in via Setup, not something that starts silently the first time the
backend happens to boot.
"""

import json
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

import db
import enrichment
import notify_telegram
import pipeline
import reply_check

_scheduler = None
ENRICH_CAP_PER_RUN = 20


def is_enabled():
    return db.get_setting("scheduler_enabled", "false") == "true"


def set_enabled(enabled):
    db.set_setting("scheduler_enabled", "true" if enabled else "false")


def get_cadence_settings():
    raw = db.get_setting("scheduler_cadence")
    return json.loads(raw) if raw else {"mode": "daily", "times_per_day": 1, "every_n_days": 1}


def save_cadence_settings(mode, times_per_day=1, every_n_days=1):
    db.set_setting(
        "scheduler_cadence",
        json.dumps({"mode": mode, "times_per_day": times_per_day, "every_n_days": every_n_days}),
    )


def _interval_seconds():
    cadence = get_cadence_settings()
    if cadence["mode"] == "times_per_day":
        return max(1, 86400 // max(1, cadence["times_per_day"]))
    if cadence["mode"] == "every_n_days":
        return max(1, cadence["every_n_days"]) * 86400
    return 86400  # "daily" default


def run_daily_batch():
    """The scheduled job body — also safe to call directly for a missed-run
    catch-up or a manual "run now" trigger."""
    try:
        sync_result = db.sync_postings_from_json()

        enriched = 0
        for posting in db.get_postings()["active"]:
            if enriched >= ENRICH_CAP_PER_RUN:
                break
            if db.get_contacts_for_posting(posting["id"]):
                continue
            found = enrichment.enrich_company(posting["company"], posting["url"], industry=posting.get("cluster"))
            for contact in found:
                if db.contact_exists(posting["company"], contact.get("email")):
                    continue
                db.insert_contact(
                    posting["company"], contact.get("name"), contact.get("role"), contact.get("email"),
                    source_type="enrichment:" + contact.get("source", "unknown"), source_id=posting["id"],
                    tier=contact.get("tier"), posting_id=posting["id"],
                )
                enriched += 1

        queue = pipeline.get_queue()

        try:
            reply_result = reply_check.check_all_replies()
        except Exception:
            reply_result = {"checked": 0, "replied": 0, "suppressed": 0}  # e.g. gmail.readonly not consented yet

        db.set_setting("scheduler_last_run_at", db.now_iso())
        notify_telegram.send_notification(
            f"Job Watcher: daily batch ready — {sync_result['synced']} posting(s) synced, "
            f"{enriched} new contact(s) found, {len(queue)} item(s) in the review queue, "
            f"{reply_result['replied']} new repl{'y' if reply_result['replied'] == 1 else 'ies'} "
            f"({reply_result['suppressed']} auto-suppressed)."
        )
        return {
            "status": "ok", "synced": sync_result["synced"], "enriched": enriched,
            "queue_size": len(queue), "replies": reply_result,
        }
    except Exception as e:
        db.set_setting("scheduler_last_run_at", db.now_iso())
        notify_telegram.send_notification(f"Job Watcher: daily batch FAILED — {e}")
        return {"status": "failed", "reason": str(e)}


def _missed_run():
    last_run = db.get_setting("scheduler_last_run_at")
    if not last_run:
        return True
    return (datetime.now(timezone.utc) - datetime.fromisoformat(last_run)).total_seconds() >= _interval_seconds()


def start():
    global _scheduler
    if _scheduler is not None:
        return
    if _missed_run():
        run_daily_batch()
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(run_daily_batch, "interval", seconds=_interval_seconds(), id="daily_batch")
    _scheduler.start()


def reschedule():
    """Call after cadence settings change so a running scheduler picks up
    the new interval without an app restart."""
    if _scheduler is not None:
        _scheduler.reschedule_job("daily_batch", trigger="interval", seconds=_interval_seconds())


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
