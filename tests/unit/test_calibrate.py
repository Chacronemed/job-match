"""`job-match calibrate`: verdicts vs scores. Suggests, never writes config."""
import argparse
from datetime import UTC, datetime

from job_match.calibration.report import (
    MIN_DECISIONS,
    DecidedJob,
    best_threshold,
    build_report,
    format_report,
    label_stats,
    rule_lifts,
)
from job_match.domain.models import (
    ContractType,
    Eligibility,
    ExperienceStatus,
    Job,
    ScoringBreakdown,
    WorkplaceType,
)
from job_match.persistence.db import Database
from job_match.persistence.repositories import ApplicationRepository, JobRepository


def _good(score, *pos):
    return DecidedJob("good_fit", score, positive=pos)


def _off(score, *pos):
    return DecidedJob("off_topic", score, positive=pos)


def test_label_stats_buckets_and_median():
    s = label_stats("good_fit", [_good(55), _good(72), _good(100), DecidedJob("good_fit", None)])
    assert (s.n, s.scored, s.min, s.median, s.max) == (4, 3, 55, 72, 100)
    assert s.buckets == (0, 0, 0, 0, 0, 1, 0, 1, 0, 1)  # 100 lands in the 90+ band


def test_rule_lift_ranks_rules_seen_on_off_topic_jobs():
    rows = ([_off(70, "java")] * 3 + [_off(65, "docker")] * 3 + [_good(80, "docker")] * 3
            + [DecidedJob("off_topic", 60, negative=("sap",))] * 2)
    lifts = rule_lifts(rows)
    assert [r.rule for r in lifts] == ["+java", "+docker"]  # "-sap": under the support
    assert lifts[0].good_fit == 0 and lifts[0].lift > lifts[1].lift


def test_best_threshold_keeps_half_of_the_good_fits():
    rows = [_good(80), _good(75), _good(60), _good(55), _off(70), _off(50), _off(40)]
    # t=75: precision 1.0, recall 2/4 = 0.5 -> best; t=80 keeps only 1/4.
    assert best_threshold(rows) == 75
    assert best_threshold([_off(70)]) is None


def test_report_suggests_only_with_enough_decisions():
    few = build_report([_good(80), _off(75, "java")], strong_threshold=70)
    assert few.suggestions == ()
    assert (few.strong_decided, few.strong_good, few.strong_precision) == (2, 1, 0.5)
    assert "Not enough decisions (2 < 10)" in format_report(few)

    rows = ([_good(85, "kubernetes")] * 4 + [_off(72, "java")] * 4
            + [DecidedJob("missing_skill", 66, unlisted=("kafka",))] * 3)
    assert len(rows) >= MIN_DECISIONS
    report = build_report(rows, strong_threshold=70)
    text = "\n".join(report.suggestions)
    assert "strong_threshold: 70 -> 75" in text
    assert "lower the weight of preferred skill 'java'" in text
    assert "consider adding 'kafka'" in text
    assert "Suggestions (nothing is changed" in format_report(report)


def test_latest_decision_per_job_is_joined_to_the_breakdown():
    now = datetime(2026, 10, 21, tzinfo=UTC)
    with Database(path=":memory:") as db:
        bd = ScoringBreakdown(eligible=True, experience=ExperienceStatus.ELIGIBLE, score=74,
                              positive_matches=("kubernetes",), unlisted={"helm": "Helm"})
        JobRepository(db.conn).save(Job(
            source="france_travail", source_job_id="A1", title="DevOps", company="Acme",
            location="75 - Paris", workplace_type=WorkplaceType.UNKNOWN,
            contract_type=ContractType.CDI, description="", url="https://x.test/1",
            collected_at=now, eligibility=Eligibility.ELIGIBLE, score=74, scoring_breakdown=bd,
        ))
        ApplicationRepository(db.conn).replace_all([], [
            {"id": 1, "job_key": "france_travail:A1", "label": "off_topic",
             "score_at_decision": 74, "created_at": "2026-10-20T08:00:00Z"},
            {"id": 2, "job_key": "france_travail:A1", "label": "good_fit",
             "score_at_decision": 74, "created_at": "2026-10-21T08:00:00Z"},
            {"id": 3, "job_key": "adzuna:gone", "label": "too_senior",
             "score_at_decision": None, "created_at": "2026-10-19T08:00:00Z"},
        ])
        repo = ApplicationRepository(db.conn)
        rows = repo.list_latest_decisions()
        assert [(label, score) for label, score, _ in rows] == [
            ("good_fit", 74), ("too_senior", None)
        ]
        assert rows[0][2].unlisted == {"helm": "Helm"} and rows[1][2] is None
        assert len(repo.list_latest_decisions(datetime(2026, 10, 20).date())) == 1


def test_cli_prints_the_report(tmp_path, monkeypatch, capsys):
    from job_match.cli import _cmd_calibrate

    data = tmp_path / "data"
    data.mkdir()
    with Database(path=str(data / "jobs.sqlite")):
        pass
    monkeypatch.setenv("JOB_MATCH_DATA_DIR", str(data))
    _cmd_calibrate(argparse.Namespace(since=None))
    out = capsys.readouterr().out
    assert out.startswith("Decisions: 0")
    assert "Precision of strong" in out
