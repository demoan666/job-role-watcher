"""Sends a notification via the user's own Telegram account — decision #27:
batch-ready / integration-failure notifications reuse the app's existing
Telegram account infra (backend/ingest/telegram.py's session), no separate
bot or phone number needed. Defaults to "me" (Saved Messages). Same
fail-closed convention as every other integration point in this app: no
session yet (Telegram never set up) is a clean no-op with a stderr log, not
a crash.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def get_notify_target():
    """DB setting takes precedence over config.json's telegram.notify_chat
    (kept as the fallback for anyone who set it there before this settings
    field existed) — Settings > Notifications UI writes only to the DB."""
    import db
    db_value = db.get_setting("notify_telegram_chat")
    if db_value:
        return db_value
    try:
        from config import load_config
        return (load_config().get("telegram") or {}).get("notify_chat", "me")
    except FileNotFoundError:
        return "me"


def save_notify_target(target):
    import db
    db.set_setting("notify_telegram_chat", target or "")


def send_notification(message):
    from config import load_config
    try:
        cfg = load_config()
    except FileNotFoundError:
        print(f"[notify_telegram] no config.json — would have sent: {message}", file=sys.stderr)
        return False

    tg_cfg = cfg.get("telegram") or {}
    if not tg_cfg.get("api_id") or not tg_cfg.get("api_hash") or not tg_cfg.get("session_name"):
        print(f"[notify_telegram] Telegram not configured — would have sent: {message}", file=sys.stderr)
        return False

    session_path = os.path.join(BACKEND_DIR, tg_cfg["session_name"])
    if not os.path.exists(session_path + ".session"):
        print(
            f"[notify_telegram] no session file yet (run backend/ingest/telegram.py once to "
            f"log in) — would have sent: {message}", file=sys.stderr,
        )
        return False

    from telethon import TelegramClient  # lazy import — same reasoning as ingest/telegram.py

    target = get_notify_target()
    client = TelegramClient(session_path, tg_cfg["api_id"], tg_cfg["api_hash"])
    try:
        with client:
            client.send_message(target, message)
        return True
    except Exception as e:
        print(f"[notify_telegram] failed to send: {e}", file=sys.stderr)
        return False
