"""Dedup when France Travail hides the employer.

The digest showed "Ingenieur DevOps - Rennes" twice: two postings of the same offer, same
location, no company name. Dedup blocks on the normalized company, so an empty name and a
real one are different blocks and the two rows were never compared -- the fuzzy comparison
was not wrong, it never ran.

With no employer name the block is the normalized title plus the department instead, and
the descriptions decide as before. Two different departments are two different offers.
"""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from job_match.config.schema import (
    Candidate,
    Filters,
    FTSearch,
    Profile,
    ScoringConfig,
    Settings,
    Skills,
    SkillWeight,
)
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobRepository
from job_match.pipelines.jobs import run_jobs

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"
_NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)

DESC = (
    "Au sein de notre equipe infrastructure vous administrez nos clusters Kubernetes, "
    "nos pipelines CI/CD et notre IaC Terraform. Astreintes partagees."
)
DESC_REWORDED = DESC + " Poste a pourvoir immediatement, remuneration selon profil."
DESC_OTHER = (
    "Kubernetes. Vous gerez le parc bureautique, les imprimantes, la telephonie et les "
    "sauvegardes des postes utilisateurs sur site, avec deplacements hebdomadaires."
)


def _profile() -> Profile:
    return Profile(
        candidate=Candidate(experience_years=3.0),
        skills=Skills(preferred=[SkillWeight(name="kubernetes", weight=25)], negative=[]),
        filters=Filters(contract_types=[ContractType.CDI], locations=[]),
        ft_search=FTSearch(keywords=["devops"], departments=[]),
        scoring=ScoringConfig(),
    )


def _settings() -> Settings:
    return Settings(strong_threshold=70, base_score=50, title_bonus=0)


def _job(sid: str, **overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id=sid,
        title="Ingenieur DevOps (H/F)",
        company="",  # the employer is hidden
        location="35 - Rennes",
        workplace_type=WorkplaceType.ONSITE,
        contract_type=ContractType.CDI,
        description=DESC,
        url=f"https://candidat.francetravail.fr/offres/{sid}",
        collected_at=_NOW,
    )
    return Job(**{**defaults, **overrides})


class FakeSource:
    name = "france_travail"

    def __init__(self, jobs: list[Job]) -> None:
        self._jobs = jobs

    def fetch(self, since):
        return iter(self._jobs)

    def to_job(self, raw: Job) -> Job:
        return raw


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _links(db) -> list[tuple[int, int]]:
    return [
        (r["canonical_job_id"], r["duplicate_job_id"])
        for r in db.conn.execute(
            "SELECT canonical_job_id, duplicate_job_id FROM job_duplicates"
        )
    ]


def _run(db, jobs: list[Job]):
    return run_jobs(FakeSource(jobs), _profile(), _settings(), db, {})


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------

def test_two_employer_hidden_postings_in_one_department_are_deduped(db):
    summary = _run(db, [_job("FT-1"), _job("FT-2", description=DESC_REWORDED)])

    assert summary.duplicates == 1
    assert summary.eligible == 1
    (canonical, duplicate), = _links(db)
    assert canonical != duplicate
    assert len(JobRepository(db.conn).list_unnotified()) == 1  # the digest sends one


def test_the_same_title_in_two_departments_is_kept_twice(db):
    """Same offer wording, two cities: two offers. The department is part of the block."""
    summary = _run(db, [_job("FT-1"), _job("FT-2", location="75 - Paris")])

    assert summary.duplicates == 0
    assert summary.eligible == 2
    assert _links(db) == []
    assert len(JobRepository(db.conn).list_unnotified()) == 2


# ---------------------------------------------------------------------------
# A hidden employer on one side only
# ---------------------------------------------------------------------------

def test_a_hidden_posting_is_linked_to_the_named_one(db):
    summary = _run(
        db,
        [
            _job("FT-1", company="Acme Corp"),
            _job("FT-2", description=DESC_REWORDED),
        ],
    )

    assert summary.duplicates == 1


def test_a_named_posting_is_linked_to_the_hidden_one(db):
    """The reverse arrival order must behave the same, or the fix depends on luck."""
    summary = _run(
        db,
        [
            _job("FT-1"),
            _job("FT-2", company="Acme Corp", description=DESC_REWORDED),
        ],
    )

    assert summary.duplicates == 1


def test_two_named_employers_are_not_deduped_on_title_and_department(db):
    """Only a hidden employer justifies looking across companies."""
    summary = _run(
        db,
        [
            _job("FT-1", company="Acme Corp"),
            _job("FT-2", company="Globex", description=DESC_REWORDED),
        ],
    )

    assert summary.duplicates == 0
    assert summary.eligible == 2


# ---------------------------------------------------------------------------
# The description still decides
# ---------------------------------------------------------------------------

def test_two_hidden_postings_with_unrelated_descriptions_stay_separate(db):
    summary = _run(db, [_job("FT-1"), _job("FT-2", description=DESC_OTHER)])

    assert summary.duplicates == 0
    assert summary.eligible == 2


def test_the_block_works_across_source_location_formats(db):
    """Jooble writes "Rennes, France" where France Travail writes "35 - Rennes"."""
    jooble = type("JoobleSource", (FakeSource,), {"name": "jooble"})
    summary = run_jobs(
        [
            FakeSource([_job("FT-1")]),
            jooble(
                [
                    _job(
                        "JB-1",
                        source="jooble",
                        location="Rennes, France",
                        description=DESC_REWORDED,
                        url="https://jooble.org/jdp/1",
                    )
                ]
            ),
        ],
        _profile(),
        _settings(),
        db,
        {},
    )

    assert summary.duplicates == 1


def test_a_hidden_posting_is_never_linked_to_a_rejected_one(db):
    """A rejected canonical would hide the eligible job from the digest for good."""
    rejected = _job("FT-1", contract_type=ContractType.CDD)  # filters want CDI
    summary = _run(db, [rejected, _job("FT-2", description=DESC_REWORDED)])

    assert summary.rejected_jobs == 1
    assert summary.duplicates == 0
    assert summary.eligible == 1
    assert _links(db) == []
    assert len(JobRepository(db.conn).list_unnotified()) == 1


def test_the_dedup_window_still_applies(db):
    """An old posting is out of the window, so the new one stands on its own."""
    old = _job("FT-1", collected_at=_NOW - timedelta(days=90))
    _run(db, [old])
    summary = _run(db, [_job("FT-2", description=DESC_REWORDED)])

    assert summary.duplicates == 0


# ---------------------------------------------------------------------------
# One employer, two departments
# ---------------------------------------------------------------------------

def test_one_employer_in_two_departments_is_two_offers(db):
    """THALES hiring in Lille and near Paris: two jobs, however identical the ads read.

    The company block used to ignore the location entirely, so the Lille posting was hidden
    behind the one in Yvelines and never reached the digest.
    """
    summary = _run(
        db,
        [
            _job("FT-59", company="THALES", location="59 - Lambersart"),
            _job("FT-78", company="THALES", location="78 - Velizy-Villacoublay"),
        ],
    )

    assert summary.duplicates == 0
    assert summary.eligible == 2
    assert _links(db) == []
    assert len(JobRepository(db.conn).list_unnotified()) == 2


def test_one_employer_twice_in_one_department_is_a_duplicate(db):
    summary = _run(
        db,
        [
            _job("FT-78a", company="THALES", location="78 - Velizy-Villacoublay"),
            _job(
                "FT-78b",
                company="THALES",
                location="78 - Velizy-Villacoublay",
                description=DESC_REWORDED,
            ),
        ],
    )

    assert summary.duplicates == 1
    (canonical, duplicate), = _links(db)
    assert canonical != duplicate


def test_an_unreadable_location_does_not_split_a_company_block(db):
    """Jooble often says only "France": unknown must not pass for a different place."""
    jooble = type("JoobleSource", (FakeSource,), {"name": "jooble"})
    summary = run_jobs(
        [
            FakeSource([_job("FT-1", company="THALES", location="78 - Velizy-Villacoublay")]),
            jooble(
                [
                    _job(
                        "JB-1",
                        source="jooble",
                        company="THALES",
                        location="France",
                        description=DESC_REWORDED,
                        url="https://jooble.org/jdp/2",
                    )
                ]
            ),
        ],
        _profile(),
        _settings(),
        db,
        {},
    )

    assert summary.duplicates == 1
