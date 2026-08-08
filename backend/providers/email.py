"""EmailProvider — wraps the existing Gmail integration behind the same
provider shape as the other categories (decision #8: every external
dependency goes through a swappable adapter). Gmail via the user's own
OAuth client is the only real implementation right now; decision #11 defers
Workspace-domain sending until DNS/warm-up is actually set up, but adding it
later is a second class with this same interface, not a rearchitecture.
"""

from abc import ABC, abstractmethod

import gmail


class EmailProvider(ABC):
    id = None

    @abstractmethod
    def send(self, client_secret_path, to, subject, body, attachment_path=None, attachment_name=None):
        raise NotImplementedError

    @abstractmethod
    def check_replies(self, client_secret_path, subject, sent_after_epoch_seconds):
        raise NotImplementedError


class GmailProvider(EmailProvider):
    id = "gmail"

    def send(self, client_secret_path, to, subject, body, attachment_path=None, attachment_name=None):
        return gmail.send_email(
            client_secret_path, to, subject, body,
            attachment_path=attachment_path, attachment_name=attachment_name,
        )

    def check_replies(self, client_secret_path, subject, sent_after_epoch_seconds):
        return gmail.check_replies(client_secret_path, subject, sent_after_epoch_seconds)


class MockEmailProvider(EmailProvider):
    """Dry-run stand-in (Settings > Pipeline > "Dry run mode"). Never touches
    the network or an OAuth token — just logs what would have been sent.
    app.py's send_outreach selects this in place of GmailProvider whenever
    dry_run_mode is on, regardless of which real provider is configured."""
    id = "mock"

    def send(self, client_secret_path, to, subject, body, attachment_path=None, attachment_name=None):
        print(
            f"[DRY RUN] would send to {to!r} — subject: {subject!r}\n{body}"
            + (f"\n[would attach: {attachment_path}]" if attachment_path else "")
        )
        return {"id": "dry-run", "to": to, "subject": subject}

    def check_replies(self, client_secret_path, subject, sent_after_epoch_seconds):
        return None


REGISTRY = {"gmail": GmailProvider(), "mock": MockEmailProvider()}


def get_provider(provider_id="gmail"):
    return REGISTRY.get(provider_id)
