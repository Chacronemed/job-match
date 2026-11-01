"""`job-match ai-report`: disagreements + my Tri verdicts -> a correction prompt, never a
config change."""
import json
from datetime import date

from job_match.ai.report import build_report, format_report, rank
from job_match.config.schema import Settings, TitleRelevanceConfig
from job_match.persistence.db import Database
from job_match.persistence.repositories import AiRepository, AiRun, Disagreement

SINCE = date(2026, 10, 18)
TODAY = date(2026, 10, 25)
HASH = "a" * 64


def _row(key, kind, py, ai, level, decision=None, title="Ingénieur DevOps", positive=()):
    return Disagreement(
        job_key=key, kind=kind, python_score=py,
        python_section="strong" if py >= 80 else "eligible", ai_score=ai, ai_level=level,
        created_at="2026-10-24T07:30:00Z", title=title,
        company="Acme", positive=tuple(positive), reasons=("Support N2 déguisé.",),
        red_flags=("Astreinte.",), decision=decision,
    )


def _settings():
    return Settings(title_relevance=TitleRelevanceConfig(core=["devops"], near=["systèmes"]))


def test_rank_puts_off_topic_strong_first_then_the_largest_gap():
    rows = [
        _row("ft:1", "gap", 60, 90, "fort", "good_fit"),
        _row("ft:2", "off_topic_strong", 85, 20, "hors_sujet", "off_topic"),
        _row("ft:3", "gap", 58, 95, "fort", "too_senior", title="Administrateur systèmes"),
        _row("ft:4", "gap", 70, 40, "tenter", "location", title=None),
    ]
    ranked = rank(rows, _settings())
    assert [x.row.job_key for x in ranked] == ["ft:2", "ft:3", "ft:1", "ft:4"]
    assert [x.sides_with for x in ranked] == ["ia", "python", "ia", None]
    assert [x.family for x in ranked] == ["core", "near", "core", "?"]


def test_report_counts_and_the_prompt_names_the_offers_but_applies_nothing():
    rows = [
        _row("ft:1", "gap", 60, 90, "fort", "good_fit", positive=["kubernetes", "terraform"]),
        _row("ft:2", "off_topic_strong", 85, 20, "hors_sujet", positive=["kubernetes"]),
    ]
    usage = {"anthropic": {"calls": 40, "tokens_in": 100_000, "tokens_out": 6_000}}
    report = build_report(rows, usage, _settings(), SINCE, TODAY)
    assert (report.total, report.with_decision) == (2, 1)
    assert report.by_kind == {"gap": 1, "off_topic_strong": 1}
    assert report.sides == {"ia": 1, "python": 0, "none": 1}
    assert report.skills[0] == ("kubernetes", 2)
    assert report.estimated_usd == 0.013  # 100k * 0.10/M + 6k * 0.50/M
    text = format_report(report)
    assert "1. Ingénieur DevOps — Acme" in text
    assert "Python 85 (strong) · IA 20 (hors_sujet)" in text
    assert "IA : Support N2 déguisé." in text
    assert "Ne l'applique pas" in text
    assert "0.0130 $" in text


def test_an_empty_week_says_so():
    report = build_report([], {}, _settings(), SINCE, TODAY)
    assert report.total == 0 and report.notes
    assert "Aucun désaccord" in format_report(report)


def test_stopped_runs_are_named_with_their_status_only():
    runs = [
        AiRun(2, "2026-10-24T09:30:00Z", "stopped", 404, "anthropic", {"scored": 0}),
        AiRun(1, "2026-10-24T07:30:00Z", "ok", None, "anthropic", {"scored": 12}),
    ]
    report = build_report([], {}, _settings(), SINCE, TODAY, runs=runs)
    text = format_report(report)
    assert "1 passage(s) de l'IA en échec : 2026-10-24T09:30 stopped HTTP 404." in text
    assert "2026-10-24T07:30 ok (12 jugées)" in text


def test_the_repository_joins_offers_reasons_and_my_latest_verdict(seed_dashboard):
    with Database(path=":memory:") as db:
        seed = seed_dashboard(db)
        src, sid = db.conn.execute(
            "SELECT source_id, source_job_id FROM jobs WHERE id = ?", (seed.strong,)
        ).fetchone()
        key = f"{src}:{sid}"
        repo = AiRepository(db.conn)
        repo.replace_all(
            [{"id": 1, "job_key": key, "hash": HASH, "provider": "anthropic", "model": "m",
              "prompt_version": "1", "score": 20, "level": "hors_sujet",
              "reasons": json.dumps(["Support N2."]), "red_flags": "[]",
              "created_at": "2026-10-24T07:30:00Z"}],
            [{"day": "2026-10-24", "provider": "anthropic", "calls": 3, "tokens_in": 300,
              "tokens_out": 30}],
            [{"id": 1, "job_key": key, "hash": HASH, "python_score": 85,
              "python_section": "strong", "ai_score": 20, "ai_level": "hors_sujet",
              "kind": "off_topic_strong", "created_at": "2026-10-24T07:30:00Z"},
             {"id": 2, "job_key": "ft:gone", "hash": HASH, "python_score": 60,
              "python_section": "eligible", "ai_score": 90, "ai_level": "fort",
              "kind": "gap", "created_at": "2026-10-01T07:30:00Z"}],
        )
        db.conn.execute(
            "INSERT INTO decisions(id, job_key, label, score_at_decision, created_at)"
            " VALUES (1, ?, 'good_fit', 85, '2026-10-24T09:00:00Z'),"
            " (2, ?, 'off_topic', 85, '2026-10-24T10:00:00Z')", (key, key)
        )
        rows = repo.list_disagreements(SINCE)
        assert len(rows) == 1  # the October 1st row is before `since`
        row = rows[0]
        assert row.title == seed.xss_title and row.company == "Acme"
        assert row.positive == ("kubernetes", "terraform")
        assert row.reasons == ("Support N2.",) and row.decision == "off_topic"
        assert repo.usage_since(SINCE) == {
            "anthropic": {"calls": 3, "tokens_in": 300, "tokens_out": 30}
        }
        assert repo.count() == (1, 1, 2, 0)
        repo.replace_all([], [], [], [
            {"id": 1, "started_at": "2026-10-24T07:30:00Z", "finished_at": "2026-10-24T07:31:00Z",
             "outcome": "stopped", "http_status": 404, "provider": "anthropic",
             "counters": '{"scored": 0}'},
            {"id": 2, "started_at": "2026-10-01T07:30:00Z", "finished_at": "2026-10-01T07:31:00Z",
             "outcome": "ok", "http_status": None, "provider": None, "counters": "not json"},
        ])
        runs = repo.list_runs(SINCE)
        assert [(r.outcome, r.http_status, r.counters) for r in runs] == [
            ("stopped", 404, {"scored": 0})
        ]
