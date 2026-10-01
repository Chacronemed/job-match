from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from job_match.domain.models import Job

RawItem = dict[str, Any]


class JobSource(Protocol):
    name: str

    def fetch(self, since: datetime | None = None) -> Iterable[RawItem]: ...

    def to_job(self, raw: RawItem) -> Job: ...
