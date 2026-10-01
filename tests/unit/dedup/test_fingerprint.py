from datetime import UTC, datetime

from job_match.dedup.fingerprint import compute_fingerprint
from job_match.domain.models import ContractType, Job, WorkplaceType

_NOW = datetime(2026, 10, 1, tzinfo=UTC)


def _job(**overrides) -> Job:
    defaults = dict(
        source="france_travail",
        source_job_id="1",
        title="DevOps Engineer H/F",
        company="Acme SAS",
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="We need a DevOps engineer with Kubernetes experience.",
        url="https://example.com/job/1",
        collected_at=_NOW,
    )
    return Job(**{**defaults, **overrides})


def test_fingerprint_is_hex_string():
    fp = compute_fingerprint(_job())
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_same_inputs_same_fingerprint():
    assert compute_fingerprint(_job()) == compute_fingerprint(_job())


def test_different_source_job_id_same_fingerprint():
    # fingerprint is content-based, not source-id-based
    j1 = _job(source_job_id="1")
    j2 = _job(source_job_id="2")
    assert compute_fingerprint(j1) == compute_fingerprint(j2)


def test_gender_marker_stripped_from_fingerprint():
    j1 = _job(title="DevOps Engineer H/F")
    j2 = _job(title="DevOps Engineer F/H")
    assert compute_fingerprint(j1) == compute_fingerprint(j2)


def test_company_suffix_stripped():
    j1 = _job(company="Acme SAS")
    j2 = _job(company="Acme SA")
    assert compute_fingerprint(j1) == compute_fingerprint(j2)


def test_different_company_different_fingerprint():
    j1 = _job(company="Acme SAS")
    j2 = _job(company="Beta Corp")
    assert compute_fingerprint(j1) != compute_fingerprint(j2)


def test_different_description_different_fingerprint():
    j1 = _job(description="A" * 600)
    j2 = _job(description="B" * 600)
    assert compute_fingerprint(j1) != compute_fingerprint(j2)


def test_description_truncated_at_500():
    # Two jobs with same prefix (500 chars) but different suffixes share fingerprint
    prefix = "x" * 500
    j1 = _job(description=prefix + "AAA")
    j2 = _job(description=prefix + "BBB")
    assert compute_fingerprint(j1) == compute_fingerprint(j2)
