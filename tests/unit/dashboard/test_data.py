"""`build_dashboard_data`: shape, tiers, what is kept out, what is never invented."""
import json
from datetime import UTC, datetime

import pytest

from job_match.config.schema import Settings
from job_match.dashboard.data import (
    RUN_LIMIT,
    build_dashboard_data,
    required_years,
    safe_url,
)
from job_match.persistence.db import Database

JOB_KEYS = {
    "id", "section", "title", "company", "department", "location", "contract", "source",
    "score", "required_years", "experience_status", "collected_at", "published_at", "url",
    "explanations", "positive", "negative", "missing",
}
RUN_KEYS = {
    "id", "pipeline", "started_at", "finished_at", "fetched", "normalized",
    "rejected_by_reason", "duplicates", "self_links_dropped", "stale_links_dropped",
    "eligible", "strong", "stretch", "errors", "api_calls", "by_source", "rejected",
}


def _by_id(data, job_id):
    return next(j for j in data["jobs"] if j["id"] == job_id)


def test_top_level_shape_and_thresholds(dashboard_data):
    data, seed = dashboard_data
    assert set(data) == {"generated_at", "thresholds", "jobs", "leads", "runs"}
    assert data["thresholds"] == {"strong": 70, "min_score": 60}
    assert data["generated_at"] == seed.now.isoformat()
    json.dumps(data)  # serialisable as-is


def test_jobs_are_canonical_eligible_or_stretch_only(dashboard_data):
    data, seed = dashboard_data
    listed = {j["id"] for j in data["jobs"]}
    assert listed == {seed.strong, seed.eligible, seed.stretch}
    assert seed.duplicate not in listed and seed.rejected not in listed
    # best score first, like the digest
    assert [j["score"] for j in data["jobs"]] == [85, 72, 65]


def test_sections_follow_the_digest_split(dashboard_data):
    data, seed = dashboard_data
    assert _by_id(data, seed.strong)["section"] == "strong"
    assert _by_id(data, seed.eligible)["section"] == "eligible"
    # a stretch job scores above the strong threshold and is still never strong
    assert _by_id(data, seed.stretch)["section"] == "stretch"


def test_job_entry_keys_and_fields(dashboard_data):
    data, seed = dashboard_data
    strong = _by_id(data, seed.strong)
    assert set(strong) == JOB_KEYS
    assert strong["title"] == seed.xss_title  # verbatim: the page escapes, the data does not
    assert strong["department"] == "75"
    assert strong["contract"] == "CDI"
    assert strong["url"] == "https://example.test/strong"
    assert strong["explanations"] == ["+15 kubernetes (title)", "+10 terraform"]
    assert strong["positive"] == ["kubernetes", "terraform"]
    assert strong["missing"] == ["aws"]
    assert strong["collected_at"] == seed.now.isoformat()


def test_required_years_is_the_stored_number_or_the_stretch_note_or_null(dashboard_data):
    data, seed = dashboard_data
    assert _by_id(data, seed.strong)["required_years"] == 2
    assert _by_id(data, seed.stretch)["required_years"] == 3.0
    assert _by_id(data, seed.eligible)["required_years"] is None
    assert _by_id(data, seed.stretch)["experience_status"] == "UNKNOWN"


def test_unreadable_department_is_null(dashboard_data):
    data, seed = dashboard_data
    assert _by_id(data, seed.eligible)["department"] is None


def test_descriptions_and_search_keywords_never_leave_the_db(dashboard_data):
    data, seed = dashboard_data
    blob = json.dumps(data, ensure_ascii=False)
    assert "Secret description" not in blob
    assert seed.secret_keyword not in blob
    assert "by_keyword" not in blob and "queries" not in blob and "search_query" not in blob


def test_javascript_urls_are_dropped(dashboard_data):
    data, seed = dashboard_data
    assert _by_id(data, seed.eligible)["url"] is None


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://a.b/c?d=1", "https://a.b/c?d=1"),
        ("http://a.b", "http://a.b"),
        ("javascript:alert(1)", None),
        ("JAVASCRIPT:alert(1)", None),
        ("data:text/html,hi", None),
        ("ftp://a.b/x", None),
        ("", None),
        (None, None),
        ("https:///nohost", None),
    ],
)
def test_safe_url(url, expected):
    assert safe_url(url) == expected


def test_required_years_without_breakdown_is_none():
    from job_match.domain.models import ContractType, Eligibility, Job, WorkplaceType

    job = Job(
        source="x", source_job_id="1", title="t", company="c", location="l",
        workplace_type=WorkplaceType.UNKNOWN, contract_type=ContractType.UNKNOWN,
        description="", url="", collected_at=datetime(2026, 10, 18, tzinfo=UTC),
        eligibility=Eligibility.STRETCH,
    )
    assert required_years(job) is None


def test_leads_include_notified_ones_with_evidence(dashboard_data):
    data, seed = dashboard_data
    assert len(data["leads"]) == 1
    lead = data["leads"][0]
    assert lead["id"] == seed.lead
    assert lead["company"] == "Acme" and lead["priority"] == "high"
    assert lead["evidence"]["hiring"] == "Acme veut recruter 30 personnes."
    assert lead["amount"] == 1.1e7 and lead["round"] == "series a"
    assert lead["investors"] == ["Shift4Good"]
    assert lead["article_url"] == "https://www.maddyness.com/acme-leve"
    assert lead["open_jobs"] == 1  # the strong Acme job; the duplicate is not counted


def test_runs_are_the_last_thirty_job_runs_newest_first(dashboard_data):
    data, _ = dashboard_data
    runs = data["runs"]
    assert len(runs) == RUN_LIMIT
    assert {r["pipeline"] for r in runs} <= {"jobs", "jobs_reprocess"}
    assert runs[0]["pipeline"] == "jobs_reprocess"  # 2026-10-18 09:00 is the newest
    starts = [r["started_at"] for r in runs]
    assert starts == sorted(starts, reverse=True)
    assert set(runs[1]) == RUN_KEYS


def test_run_funnel_counts(dashboard_data):
    data, _ = dashboard_data
    run = next(r for r in data["runs"] if r["pipeline"] == "jobs")
    # 100+ fetched = rejected + 5 duplicates + 20 eligible + 3 stretch
    assert run["rejected"] == run["fetched"] - 5 - 20 - 3
    assert run["rejected_by_reason"] == {"EXPERIENCE": 50, "CONTRACT": 30, "NOT_RELEVANT": 10}
    assert run["strong"] == 8 and run["stretch"] == 3
    assert run["by_source"]["france_travail"]["calls"] == 13


def test_empty_database_gives_empty_lists():
    with Database(path=":memory:") as db:
        data = build_dashboard_data(db, Settings(), datetime(2026, 10, 18, tzinfo=UTC))
    assert data["jobs"] == [] and data["leads"] == [] and data["runs"] == []
