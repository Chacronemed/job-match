"""Golden scores: 80 synthetic postings (tests/fixtures/golden_jobs.json) through the real
pipeline with the committed config give exactly tests/fixtures/golden_scores.json.

The guard for the performance work: an optimisation that changes one verdict, one score or one
duplicate link fails here. A deliberate rule or weight change regenerates the file with
`JM_UPDATE_GOLDEN=1 pytest tests/unit/pipelines/test_golden_scores.py` and the diff is reviewed
like code.
"""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from job_match.config.loader import (
    load_aliases,
    load_profile,
    load_settings,
    load_skill_vocabulary,
)
from job_match.domain.models import ContractType, Job, WorkplaceType
from job_match.normalization.contract import parse_contract_type
from job_match.persistence.db import Database
from job_match.persistence.repositories import JobDuplicateRepository, JobRepository
from job_match.pipelines.jobs import run_jobs

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
CONFIG = Path(__file__).resolve().parents[3] / "config"
NOW = datetime(2026, 11, 4, 7, 0, tzinfo=UTC)


class GoldenSource:
    """The fixture's items as one source; `source` is carried by each item."""

    name = "golden"

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    def fetch(self, since=None):
        yield from self._items

    def to_job(self, raw: dict) -> Job:
        published = datetime.fromisoformat(raw["published_at"]) if raw.get("published_at") else None
        return Job(
            source=self.name,
            source_job_id=raw["id"],
            title=raw["title"],
            company=raw["company"],
            location=raw["location"],
            workplace_type=WorkplaceType.UNKNOWN,
            contract_type=parse_contract_type(raw["contract"], raw["title"], raw["description"]),
            description=raw["description"],
            url=raw["url"],
            published_at=published,
            collected_at=NOW,
            search_query="devops",
        )


def run_golden(items: list[dict]) -> dict[str, dict]:
    profile = load_profile(CONFIG / "profile.example.yaml")
    settings = load_settings(CONFIG / "settings.yaml")
    aliases = load_aliases(CONFIG / "aliases.yaml")
    vocabulary = load_skill_vocabulary(CONFIG / "skill_vocabulary.yaml")
    with Database(path=":memory:") as db:
        run_jobs(GoldenSource(items), profile, settings, db, aliases, vocabulary=vocabulary)
        jobs = JobRepository(db.conn)
        dups = JobDuplicateRepository(db.conn)
        by_id = {j.id: j for j in jobs.list_all()}
        out = {}
        for j in sorted(by_id.values(), key=lambda j: j.source_job_id):
            canonical = dups.get_canonical_id(j.id)
            bd = j.scoring_breakdown
            out[j.source_job_id] = {
                "eligibility": j.eligibility.value if j.eligibility else None,
                "rejection_reason": j.rejection_reason,
                "score": j.score,
                "contract": j.contract_type.value,
                "positive": list(bd.positive_matches) if bd else [],
                "negative": list(bd.negative_matches) if bd else [],
                "explanations": list(bd.explanations) if bd else [],
                "duplicate_of": by_id[canonical].source_job_id if canonical else None,
            }
        return out


def test_the_golden_fixture_scores_exactly_as_recorded():
    items = json.loads((FIXTURES / "golden_jobs.json").read_text(encoding="utf-8"))
    got = run_golden(items)
    expected_path = FIXTURES / "golden_scores.json"
    if os.environ.get("JM_UPDATE_GOLDEN"):
        expected_path.write_text(
            json.dumps(got, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        pytest.skip("golden_scores.json regenerated")
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    assert got == expected
    # the fixture exercises the paths that matter: rejections of several kinds, scores and
    # duplicate links (exact and fuzzy)
    assert {v["eligibility"] for v in got.values()} >= {"REJECTED", "ELIGIBLE"}
    assert len({v["rejection_reason"] for v in got.values()}) > 4
    assert any(v["duplicate_of"] for v in got.values())
    assert ContractType.CDI.value in {v["contract"] for v in got.values()}
