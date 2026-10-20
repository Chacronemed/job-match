from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Any, NamedTuple, Protocol

from job_match.domain.models import Job

RawItem = dict[str, Any]

# Adapters tag raw items with their own keys ("_jm_query", "_jm_region") to say which query
# returned them. They are ours, not the source's: the same offer found by two keywords must
# compare equal, so they are dropped before the payload is stored.
ANNOTATION_PREFIX = "_jm_"


def source_payload(raw: RawItem) -> RawItem:
    """The item as the source sent it, without the adapter's annotations."""
    if not isinstance(raw, dict):
        return raw
    return {k: v for k, v in raw.items() if not str(k).startswith(ANNOTATION_PREFIX)}


class OfferStatus(StrEnum):
    """What a source answers when asked whether a stored offer is still online.

    UNKNOWN covers every answer that is not a clear yes or no (network error, 5xx, 429
    after the retries, a refused request): the caller must change nothing on UNKNOWN.
    """

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class QueryStat(NamedTuple):
    """One source query and how many items it returned. Aggregates only, never job content."""

    query: str        # keyword, ROME code, or "no-filter"
    area: str         # department code (France Travail) or region name (Jooble, Adzuna)
    fetched: int      # items actually yielded by this query
    available: int | None  # items the source said exist (None when unknown)
    source: str = ""  # source name, so a multi-source run can group its stats


class JobSource(Protocol):
    """A job source.

    `api_calls_count`, `query_stats` and `check_offer` are optional: the pipeline reads
    them with `getattr` so a source (or a test fake) can leave them out. A source without
    `check_offer(source_job_id) -> OfferStatus` never has its stored offers re-checked;
    only the posting-age cut-off hides them.
    """

    name: str

    def fetch(self, since: datetime | None = None) -> Iterable[RawItem]: ...

    def to_job(self, raw: RawItem) -> Job: ...
