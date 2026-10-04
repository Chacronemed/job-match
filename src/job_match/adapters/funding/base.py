from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


class FeedError(RuntimeError):
    """Raised when a feed cannot be fetched or parsed at all."""


@dataclass(frozen=True, slots=True)
class ArticleRef:
    """A pointer to an article discovered in a feed. Source-independent."""

    url: str
    title: str
    published_at: datetime | None = None
    summary: str | None = None


@runtime_checkable
class FundingSource(Protocol):
    name: str

    def fetch_articles(self, since: datetime | None = None) -> Iterable[ArticleRef]: ...
