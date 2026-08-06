"""Live Slack ingestion — a personal user OAuth token (xoxp-...) for
workspaces the user is already a member of, polling channels via the Slack
Web API. Not a bot installed into workspaces the user doesn't control.

Run standalone: python backend/ingest/slack.py
Requires backend/config.json's "slack" block filled in (user_token +
channel IDs to poll). Missing config is a clean no-op, not a crash.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import load_config  # noqa: E402
import db  # noqa: E402


def _cursor_key(channel_id):
    return f"slack_last_ts_{channel_id}"


def poll_once(client, channel_id):
    last_ts = db.get_setting(_cursor_key(channel_id))
    kwargs = {"channel": channel_id, "limit": 50}
    if last_ts:
        kwargs["oldest"] = last_ts
    response = client.conversations_history(**kwargs)
    messages = response.get("messages", [])
    # Slack returns newest-first; process oldest-first so the stored cursor
    # only advances past messages we've actually posted as leads.
    for message in sorted(messages, key=lambda m: m["ts"]):
        if last_ts and message["ts"] == last_ts:
            continue  # oldest= is inclusive; skip the one we already saw
        if message.get("subtype"):
            continue  # skip joins/edits/etc, only plain messages are leads
        yield message
        db.set_setting(_cursor_key(channel_id), message["ts"])


def post_lead(backend_url, source_channel, author, raw_text):
    body = json.dumps({
        "source": "slack",
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
        print(f"[slack] failed to post lead to backend: {e}", file=sys.stderr)


def main():
    cfg = load_config()
    slack_cfg = cfg.get("slack") or {}
    if not slack_cfg.get("user_token"):
        print("[slack] not configured (missing user_token in config.json) — skipping.")
        return
    channels = slack_cfg.get("channels") or []
    if not channels:
        print("[slack] no channels configured in config.json's slack.channels — nothing to watch.")
        return

    from slack_sdk import WebClient

    client = WebClient(token=slack_cfg["user_token"])
    backend_url = f"http://{cfg.get('host', '127.0.0.1')}:{cfg.get('port', 8420)}"
    interval = slack_cfg.get("poll_interval_seconds", 60)

    print(f"[slack] polling {len(channels)} channel(s) every {interval}s…")
    while True:
        for channel_id in channels:
            for message in poll_once(client, channel_id):
                post_lead(backend_url, channel_id, message.get("user", ""), message.get("text", ""))
        time.sleep(interval)


if __name__ == "__main__":
    main()
