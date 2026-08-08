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
    def send(self, client_secret_path, to, subject, body):
        raise NotImplementedError

    @abstractmethod
    def check_replies(self, client_secret_path, subject, sent_after_epoch_seconds):
        raise NotImplementedError


class GmailProvider(EmailProvider):
    id = "gmail"

    def send(self, client_secret_path, to, subject, body):
        return gmail.send_email(client_secret_path, to, subject, body)

    def check_replies(self, client_secret_path, subject, sent_after_epoch_seconds):
        return gmail.check_replies(client_secret_path, subject, sent_after_epoch_seconds)


REGISTRY = {"gmail": GmailProvider()}


def get_provider(provider_id="gmail"):
    return REGISTRY.get(provider_id)
