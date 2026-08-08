"""Gmail send integration — installed-app OAuth flow (gmail.send scope
only, not full mailbox access). One-time interactive consent on first send;
after that, the refresh token in token.json (gitignored) is reused.

Setup (one-time, by the user, not this code):
1. Google Cloud Console -> new project -> enable the Gmail API.
2. OAuth consent screen -> External or Internal, add yourself as a test user.
3. Credentials -> Create OAuth client ID -> Desktop app -> download the JSON,
   save it as backend/client_secret.json (gitignored).
"""

import base64
import json
import os
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

import vault

SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
# Narrow read scope for reply detection (plan decision #19) — thread search
# only, never full mailbox access. Both scopes are requested together so a
# single OAuth consent covers send + reply-check; re-consent is required
# once for existing token.json files that predate this scope (Google will
# prompt again the first time READ_SCOPE is actually used).
READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = [SEND_SCOPE, READ_SCOPE]
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BACKEND_DIR, "token.json")


def _client_config_or_path(client_secret_path):
    """Vault-first: if the vault is initialized and unlocked and holds a
    migrated gmail_client_secret_json secret, use that (in-memory dict, no
    file needed). Otherwise falls back to the plaintext client_secret_path
    file exactly as before — same backward-compat pattern as config.py."""
    if vault.is_initialized() and vault.is_unlocked():
        raw = vault.get_secret("gmail_client_secret_json")
        if raw:
            return json.loads(raw), None
    return None, client_secret_path


def _get_credentials(client_secret_path):
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            client_config, path = _client_config_or_path(client_secret_path)
            if client_config is not None:
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            else:
                if not os.path.exists(path):
                    raise FileNotFoundError(
                        f"{path} not found — see backend/gmail.py's docstring "
                        "for the one-time Google Cloud OAuth client setup."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(path, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser tab, one-time only
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def send_email(client_secret_path, to, subject, body, attachment_path=None, attachment_name=None):
    """attachment_path (decision #21's PDF resume-delivery mode): when given,
    sends a multipart message with the file attached instead of a plain
    MIMEText — otherwise behaves exactly as before (HTML-in-body-only mode
    stays the default, no attachment)."""
    creds = _get_credentials(client_secret_path)
    service = build("gmail", "v1", credentials=creds)

    if attachment_path:
        message = MIMEMultipart()
        message.attach(MIMEText(body))
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
        part.add_header(
            "Content-Disposition", "attachment",
            filename=attachment_name or os.path.basename(attachment_path),
        )
        message.attach(part)
    else:
        message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()


def check_replies(client_secret_path, subject, sent_after_epoch_seconds):
    """Narrow reply-check for one sent thread (plan decision #19): searches
    only for messages whose subject matches (Gmail auto-prefixes replies
    with "Re: ", so we match on the bare subject as a substring) received
    after the original send time — never a full-inbox scan. Returns True if
    at least one matching message exists that isn't the original sent one.
    Requires gmail.readonly consent (see READ_SCOPE) — raises the same way
    send_email does if that hasn't been granted yet (fails closed, caller
    treats an exception as "couldn't check, leave status as-is")."""
    creds = _get_credentials(client_secret_path)
    service = build("gmail", "v1", credentials=creds)
    query = f'subject:"{subject}" after:{int(sent_after_epoch_seconds)} -in:sent'
    result = service.users().messages().list(userId="me", q=query, maxResults=5).execute()
    return bool(result.get("messages"))
