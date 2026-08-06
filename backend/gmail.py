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
import os
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_PATH = os.path.join(BACKEND_DIR, "token.json")


def _get_credentials(client_secret_path):
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                raise FileNotFoundError(
                    f"{client_secret_path} not found — see backend/gmail.py's docstring "
                    "for the one-time Google Cloud OAuth client setup."
                )
            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser tab, one-time only
        with open(TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def send_email(client_secret_path, to, subject, body):
    creds = _get_credentials(client_secret_path)
    service = build("gmail", "v1", credentials=creds)
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return service.users().messages().send(userId="me", body={"raw": raw}).execute()
