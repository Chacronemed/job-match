from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.dedup.fingerprint import compute_fingerprint
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.normalization.company import normalize_company
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobDuplicateRepository, JobRepository

MIGRATIONS = Path(__file__).parent.parent.parent.parent / "src" / "job_match" / "migrations"

_NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=UTC)
_LATER = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def db():
    with Database(migrations_dir=MIGRATIONS) as d:
        yield d


def _job(sid: str, **overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id=sid,
        title="DevOps Engineer",
        company="Acme Corp",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="Looking for a DevOps engineer with Kubernetes experience.",
        url=f"https://example.com/jobs/{sid}",
        collected_at=_NOW,
    )
    defaults.update(overrides)
    j = Job(**defaults)
    fp = compute_fingerprint(j)
    kwargs = {k: getattr(j, k) for k in j.__slots__ if k != "fingerprint"}
    return Job(fingerprint=fp, **kwargs)


# ---------------------------------------------------------------------------
# get_by_fingerprint
# ---------------------------------------------------------------------------

def test_get_by_fingerprint_returns_saved_job(db):
    repo = JobRepository(db.conn)
    job = _job("FT-001")
    saved = repo.save(job)
    results = repo.get_by_fingerprint(saved.fingerprint)
    assert len(results) == 1
    assert results[0].source_job_id == "FT-001"


def test_get_by_fingerprint_empty_when_no_match(db):
    repo = JobRepository(db.conn)
    assert repo.get_by_fingerprint("nonexistent") == []


def test_get_by_fingerprint_finds_same_content_different_source(db):
    repo = JobRepository(db.conn)
    j1 = _job("FT-001", source="france_travail")
    j2 = _job("AZ-001", source="adzuna")
    # Same content → same fingerprint
    j2_same_fp = Job(
        fingerprint=j1.fingerprint,
        source="adzuna", source_job_id="AZ-001",
        title=j1.title, company=j1.company, location=j1.location,
        workplace_type=j1.workplace_type, contract_type=j1.contract_type,
        description=j1.description, url=j2.url, collected_at=j1.collected_at,
    )
    repo.save(j1)
    repo.save(j2_same_fp)
    results = repo.get_by_fingerprint(j1.fingerprint)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# list_by_block
# ---------------------------------------------------------------------------

def test_list_by_block_finds_matching_jobs(db):
    repo = JobRepository(db.conn)
    job = _job("FT-001")
    repo.save(job)
    company_n = normalize_company(job.company)
    results = repo.list_by_block(company_n, job.contract_type, _NOW)
    assert len(results) == 1


def test_list_by_block_excludes_different_contract(db):
    repo = JobRepository(db.conn)
    repo.save(_job("FT-001", contract_type=ContractType.CDI))
    repo.save(_job("FT-002", contract_type=ContractType.CDD))
    company_n = normalize_company("Acme Corp")
    results = repo.list_by_block(company_n, ContractType.CDI, _NOW)
    assert all(j.contract_type == ContractType.CDI for j in results)
    assert len(results) == 1


def test_list_by_block_respects_since(db):
    repo = JobRepository(db.conn)
    old_job = _job("FT-001", collected_at=datetime(2026, 9, 1, tzinfo=UTC))
    repo.save(old_job)
    company_n = normalize_company("Acme Corp")
    results = repo.list_by_block(company_n, ContractType.CDI, _NOW)
    assert results == []


# ---------------------------------------------------------------------------
# JobDuplicateRepository
# ---------------------------------------------------------------------------

def test_save_link_and_get_canonical(db):
    job_repo = JobRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)

    canonical = job_repo.save(_job("FT-001"))
    duplicate = job_repo.save(_job("FT-002", url="https://example.com/jobs/ft-002"))

    dup_repo.save_link(canonical.id, duplicate.id, "exact_fingerprint", 1.0)

    assert dup_repo.get_canonical_id(duplicate.id) == canonical.id


def test_save_link_idempotent(db):
    job_repo = JobRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)

    j1 = job_repo.save(_job("FT-001"))
    j2 = job_repo.save(_job("FT-002", url="https://example.com/jobs/ft-002"))

    dup_repo.save_link(j1.id, j2.id, "fuzzy", 0.92)
    dup_repo.save_link(j1.id, j2.id, "fuzzy", 0.92)  # second call must not raise

    assert dup_repo.get_canonical_id(j2.id) == j1.id


def test_list_duplicates_of(db):
    job_repo = JobRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)

    canonical = job_repo.save(_job("FT-001"))
    d1 = job_repo.save(_job("FT-002", url="https://example.com/jobs/ft-002"))
    d2 = job_repo.save(_job("FT-003", url="https://example.com/jobs/ft-003"))

    dup_repo.save_link(canonical.id, d1.id, "exact_fingerprint", 1.0)
    dup_repo.save_link(canonical.id, d2.id, "fuzzy", 0.88)

    dups = dup_repo.list_duplicates_of(canonical.id)
    assert set(dups) == {d1.id, d2.id}


def test_get_canonical_returns_none_for_non_duplicate(db):
    job_repo = JobRepository(db.conn)
    dup_repo = JobDuplicateRepository(db.conn)
    job = job_repo.save(_job("FT-001"))
    assert dup_repo.get_canonical_id(job.id) is None


def test_company_normalized_stored(db):
    repo = JobRepository(db.conn)
    job = _job("FT-001", company="Acme SAS")
    repo.save(job)
    # Verify company_normalized is stored via list_by_block
    results = repo.list_by_block("acme", ContractType.CDI, _NOW)
    assert len(results) == 1
