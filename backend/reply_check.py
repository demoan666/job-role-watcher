"""Reply loop + compliance (plan Phase 5, decisions #19/#20).

Checks each contact currently in "sent" status via the narrow gmail.readonly
scope (backend/gmail.py's check_replies — subject + after: query on a single
thread, never a full-inbox scan), advances sent -> replied on any match, and
auto-suppresses a contact whose reply classifies as negative sentiment
(explicit opt-out/hostile). Suppression is never silent or permanent — a
suppressed contact stays visible and can be manually re-approached via the
existing PATCH /contacts/{id}/status route (no new endpoint needed for that
half of decision #20).
"""

import os
from datetime import datetime

import db
import gmail
import llm
from config import load_config


def _iso_to_epoch(iso_str):
    return datetime.fromisoformat(iso_str).timestamp()


def check_all_replies():
    cfg = load_config()
    gmail_cfg = cfg.get("gmail") or {}
    client_secret_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), gmail_cfg.get("client_secret_path", "client_secret.json"),
    )

    checked = 0
    replied = 0
    suppressed = 0
    for sent in db.get_sent_emails():
        contact = db.get_contact(sent["contact_id"])
        if not contact or contact["status"] != "sent":
            continue
        try:
            reply = gmail.check_replies(client_secret_path, sent["subject"], _iso_to_epoch(sent["sent_at"]))
        except Exception:
            continue  # no gmail.readonly consent yet, or a transient API error — leave status as-is
        checked += 1
        if not reply:
            continue

        replied += 1
        db.update_contact_status(contact["id"], "replied")
        try:
            sentiment = llm.classify_sentiment(reply["snippet"])
        except Exception:
            sentiment = None
        if sentiment and sentiment.get("sentiment") == "negative":
            db.update_contact_status(contact["id"], "suppressed")
            suppressed += 1

    return {"checked": checked, "replied": replied, "suppressed": suppressed}
