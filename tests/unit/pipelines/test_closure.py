"""M20: `check_closed` — what gets asked, what gets written, what never does."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.adapters.jobs.base import OfferStatus
from job_match.config.schema import JobsConfig, Settings
from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository
from job_match.pipelines.closure import RECHECK_AFTER, ClosureStats, check_closed

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
NOW = datetime(2026, 10, 19, 7, 0, 0, tzinfo=UTC)
SETTINGS = Settings(jobs=JobsConfig(max_age_days=45))


class CheckingSource:
    """A source whose `check_offer` answers from a script and records what it was asked."""

    name = "france_travail"

    def __init__(self, answers: dict[str, OfferStatus | Exception]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def fetch(self, since=None):
        return iter(())

    def to_job(self, raw):
        return raw

    def check_offer(self, source_job_id: str) -> OfferStatus:
        self.asked.append(source_job_id)
        answer = self.answers[source_job_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


class PlainSource:
    """No `check_offer`: Jooble-like."""

    name = "jooble"

    def fetch(self, since=None):
        return iter(())

    def to_job(self, raw):
        return raw


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _job(sid, source="france_travail", **overrides) -> Job:
    defaults = dict(
        source=source, source_job_id=sid, title=f"DevOps {sid}", company="Acme",
        location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
        contract_type=ContractType.CDI, description="Kubernetes.",
        url=f"https://x.test/{sid}", collected_at=NOW, eligibility=Eligibility.ELIGIBLE,
        score=75,
    )
    return Job(**{**defaults, **overrides})


def _cols(db, job_id):
    row = db.conn.execute(
        "SELECT closed_at, last_checked_at FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return row["closed_at"], row["last_checked_at"]


def test_closed_open_and_unknown_answers(db):
    repo = JobRepository(db.conn)
    gone = repo.save(_job("GONE"))
    live = repo.save(_job("LIVE", eligibility=Eligibility.STRETCH))
    unclear = repo.save(_job("UNCLEAR"))
    source = CheckingSource({
        "GONE": OfferStatus.CLOSED, "LIVE": OfferStatus.OPEN, "UNCLEAR": OfferStatus.UNKNOWN,
    })

    stats = check_closed([source], SETTINGS, db, NOW)

    assert stats == ClosureStats(checked=3, closed=1, errors=1)
    assert sorted(source.asked) == ["GONE", "LIVE", "UNCLEAR"]
    assert _cols(db, gone.id) == (NOW.isoformat(), NOW.isoformat())
    assert _cols(db, live.id) == (None, NOW.isoformat())
    assert _cols(db, unclear.id) == (None, None)  # asked again next run


def test_only_sources_with_check_offer_are_asked(db):
    repo = JobRepository(db.conn)
    jooble_job = repo.save(_job("J1", source="jooble"))
    ft_job = repo.save(_job("F1"))
    source = CheckingSource({"F1": OfferStatus.CLOSED})

    stats = check_closed([PlainSource(), source], SETTINGS, db, NOW)

    assert stats == ClosureStats(checked=1, closed=1, errors=0)
    assert source.asked == ["F1"]
    assert _cols(db, jooble_job.id) == (None, None)
    assert _cols(db, ft_job.id)[0] == NOW.isoformat()


def test_no_checking_source_means_no_work(db):
    JobRepository(db.conn).save(_job("A"))
    assert check_closed([PlainSource()], SETTINGS, db, NOW) == ClosureStats()


def test_dry_run_asks_but_writes_nothing(db):
    repo = JobRepository(db.conn)
    gone = repo.save(_job("GONE"))
    source = CheckingSource({"GONE": OfferStatus.CLOSED})

    stats = check_closed([source], SETTINGS, db, NOW, dry_run=True)

    assert stats.checked == 1 and stats.closed == 1
    assert _cols(db, gone.id) == (None, None)


def test_a_job_checked_within_24h_is_not_asked_again(db):
    repo = JobRepository(db.conn)
    fresh = repo.save(_job("FRESH"))
    due = repo.save(_job("DUE"))
    repo.mark_checked([fresh.id], NOW - timedelta(hours=23))
    repo.mark_checked([due.id], NOW - RECHECK_AFTER - timedelta(minutes=1))
    source = CheckingSource({"DUE": OfferStatus.OPEN})

    stats = check_closed([source], SETTINGS, db, NOW)

    assert source.asked == ["DUE"] and stats.checked == 1


def test_hidden_jobs_are_never_asked(db):
    repo = JobRepository(db.conn)
    repo.save(_job("REJ", eligibility=Eligibility.REJECTED, score=None))
    repo.save(_job("OLD", published_at=NOW - timedelta(days=46)))
    closed = repo.save(_job("CLOSED"))
    repo.mark_closed([closed.id], NOW - timedelta(days=2))
    source = CheckingSource({})

    assert check_closed([source], SETTINGS, db, NOW) == ClosureStats()
    assert source.asked == []


def test_a_source_that_cannot_be_asked_stops_the_check_without_closing_anything(db):
    repo = JobRepository(db.conn)
    a = repo.save(_job("A"))
    b = repo.save(_job("B"))
    source = CheckingSource({"A": RuntimeError("no token"), "B": OfferStatus.CLOSED})

    stats = check_closed([source], SETTINGS, db, NOW)

    assert stats == ClosureStats(checked=1, closed=0, errors=1)
    assert source.asked == ["A"]  # stopped after the first failure
    assert _cols(db, a.id) == (None, None) and _cols(db, b.id) == (None, None)
