from collections.abc import Iterable
from datetime import datetime
from typing import Any, NamedTuple, Protocol

from job_match.domain.models import Job

RawItem = dict[str, Any]


class QueryStat(NamedTuple):
    """One source query and how many items it returned. Aggregates only, never job content."""

    query: str        # keyword, ROME code, or "no-filter"
    department: str   # department code, or "all"
    fetched: int      # items actually yielded by this query
    available: int | None  # items the source said exist (None when unknown)


class JobSource(Protocol):
    name: str

    def fetch(self, since: datetime | None = None) -> Iterable[RawItem]: ...

    def to_job(self, raw: RawItem) -> Job: ...
