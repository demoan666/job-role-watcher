"""Retention sweep (plan Phase 7, decision #29): auto-archives closed
postings past a configurable retention window (default 30 days) and
hard-deletes items already archived for a second, longer grace period —
"archived" and "gone forever" are never the same moment. A pin always wins
over both steps, at any point in the pipeline.
"""

from datetime import datetime, timedelta, timezone

import db

DEFAULT_RETENTION_DAYS = 30


def get_retention_days():
    return int(db.get_setting("retention_days", str(DEFAULT_RETENTION_DAYS)))


def save_retention_days(days):
    db.set_setting("retention_days", str(days))


def sweep():
    days = get_retention_days()
    archive_cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    delete_cutoff = (datetime.now(timezone.utc) - timedelta(days=days * 2)).date().isoformat()

    archived = db.archive_expired_postings(archive_cutoff)
    deleted = db.delete_expired_archived_postings(delete_cutoff)
    return {"archived": archived, "deleted": deleted, "retention_days": days}
