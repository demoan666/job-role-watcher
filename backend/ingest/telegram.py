"""Live Telegram ingestion — the user's own account session, listening to
channels/groups already joined. This is legitimate personal use (reading
your own chats), not scraping; there is no "discover and join without an
invite" capability here or anywhere else in this app.

Run standalone: python backend/ingest/telegram.py
Requires backend/config.json's "telegram" block filled in (api_id/api_hash
from https://my.telegram.org, one-time interactive login on first run to
create the session file). Missing config is a clean no-op, not a crash —
this lets the rest of the app run before Telegram is set up.
"""

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config  # noqa: E402


def post_lead(backend_url, source_channel, author, raw_text):
    body = json.dumps({
        "source": "telegram",
        "source_channel": source_channel,
        "author": author,
        "raw_text": raw_text,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{backend_url}/leads/capture", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except urllib.error.URLError as e:
        print(f"[telegram] failed to post lead to backend: {e}", file=sys.stderr)


def main():
    cfg = load_config()
    tg_cfg = cfg.get("telegram") or {}
    if not tg_cfg.get("api_id") or not tg_cfg.get("api_hash"):
        print("[telegram] not configured (missing api_id/api_hash in config.json) — skipping.")
        return

    # Imported lazily: telethon pulls in its own event loop machinery, no
    # need to pay that cost when Telegram isn't configured at all.
    from telethon import TelegramClient, events

    backend_url = f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8420)}"
    channels = tg_cfg.get("channels") or []
    if not channels:
        print("[telegram] no channels configured in config.json's telegram.channels — nothing to watch.")
        return

    session_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", tg_cfg["session_name"])
    client = TelegramClient(session_path, tg_cfg["api_id"], tg_cfg["api_hash"])

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        sender = await event.get_sender()
        author = getattr(sender, "username", None) or getattr(sender, "first_name", "") or ""
        chat = await event.get_chat()
        channel_name = getattr(chat, "title", None) or getattr(chat, "username", "") or str(event.chat_id)
        post_lead(backend_url, channel_name, author, event.raw_text or "")

    print(f"[telegram] listening on {len(channels)} channel(s)/group(s)…")
    client.start()  # first run: interactive phone/code prompt, then session is saved
    client.run_until_disconnected()


if __name__ == "__main__":
    main()
