from typing import Protocol, runtime_checkable

from job_match.config.schema import Profile, Settings
from job_match.domain.models import Job, ScoreResult


@runtime_checkable
class Scorer(Protocol):
    @property
    def name(self) -> str: ...

    def score(self, job: Job, profile: Profile, settings: Settings) -> ScoreResult: ...
