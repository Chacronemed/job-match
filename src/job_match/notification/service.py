"""NotificationService protocol — satisfied by EmailNotifier and any future notifier."""
from typing import Protocol, runtime_checkable

from job_match.notification.digest import DigestData


@runtime_checkable
class NotificationService(Protocol):
    def send(self, data: DigestData) -> bool:
        """Send the digest. Returns True on success, False on failure."""
        ...
