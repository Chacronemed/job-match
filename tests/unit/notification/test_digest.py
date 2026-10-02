"""Tests for DigestData rendering (HTML and plain-text)."""
from datetime import datetime

from job_match.domain.models import (
    ContractType,
    ExperienceStatus,
    Job,
    ScoringBreakdown,
    WorkplaceType,
)
from job_match.notification.digest import DigestData, render_html, render_text

_TS = datetime(2026, 10, 2, 9, 0, 0)


def _job(
    job_id: int,
    title: str = "DevOps Engineer",
    company: str = "Acme",
    score: int = 75,
    positive: tuple[str, ...] = ("kubernetes", "terraform"),
) -> Job:
    bd = ScoringBreakdown(
        eligible=True,
        experience=ExperienceStatus.ELIGIBLE,
        score=score,
        positive_matches=positive,
    )
    return Job(
        id=job_id,
        source="france_travail",
        source_job_id=f"FT-{job_id:03}",
        title=title,
        company=company,
        location="Paris",
        workplace_type=WorkplaceType.HYBRID,
        contract_type=ContractType.CDI,
        description="desc",
        url=f"https://candidat.francetravail.fr/offres/recherche/detail/FT{job_id:03}",
        collected_at=_TS,
        score=score,
        scoring_breakdown=bd,
    )


def _data(strong=(), eligible=()) -> DigestData:
    return DigestData(strong=tuple(strong), eligible=tuple(eligible), generated_at=_TS)


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def test_render_html_contains_job_title():
    data = _data(strong=[_job(1, title="Platform Engineer")])
    out = render_html(data)
    assert "Platform Engineer" in out


def test_render_html_contains_job_url():
    job = _job(1)
    data = _data(strong=[job])
    out = render_html(data)
    assert job.url in out


def test_render_html_contains_score():
    data = _data(strong=[_job(1, score=87)])
    out = render_html(data)
    assert "87" in out


def test_render_html_contains_positive_matches():
    data = _data(eligible=[_job(1, positive=("ansible", "docker"))])
    out = render_html(data)
    assert "ansible" in out
    assert "docker" in out


def test_render_html_escapes_title():
    """Job titles from external APIs must be HTML-escaped."""
    evil_title = "<script>alert('xss')</script>"
    data = _data(strong=[_job(1, title=evil_title)])
    out = render_html(data)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_render_html_escapes_company():
    evil_co = 'Acme & <Sons> "Ltd"'
    data = _data(strong=[_job(1, company=evil_co)])
    out = render_html(data)
    assert evil_co not in out
    assert "&amp;" in out


def test_render_html_empty_digest():
    data = _data()
    out = render_html(data)
    assert "0 unnotified jobs" in out
    assert "none" in out.lower() or "No" in out


def test_render_html_run_stats():
    data = DigestData(
        strong=(), eligible=(),
        run_stats={"fetched": 50, "eligible": 6, "rejected": 44},
        generated_at=_TS,
    )
    out = render_html(data)
    assert "fetched" in out
    assert "50" in out


def test_render_html_is_valid_html():
    data = _data(strong=[_job(1)], eligible=[_job(2, score=60)])
    out = render_html(data)
    assert out.startswith("<!doctype html>")
    assert out.strip().endswith("</html>")


# ---------------------------------------------------------------------------
# Plain-text rendering
# ---------------------------------------------------------------------------

def test_render_text_contains_job_title():
    data = _data(strong=[_job(1, title="Cloud SRE")])
    out = render_text(data)
    assert "Cloud SRE" in out


def test_render_text_contains_score():
    data = _data(strong=[_job(1, score=77)])
    out = render_text(data)
    assert "77" in out


def test_render_text_contains_url():
    job = _job(1)
    data = _data(eligible=[job])
    out = render_text(data)
    assert job.url in out


def test_render_text_empty_shows_none():
    data = _data()
    out = render_text(data)
    assert "(none)" in out


def test_render_text_strong_section_before_eligible():
    data = _data(strong=[_job(1, title="STRONG")], eligible=[_job(2, title="ELIGIBLE")])
    out = render_text(data)
    assert out.index("STRONG") < out.index("ELIGIBLE")


def test_render_text_run_stats():
    data = DigestData(
        strong=(), eligible=(),
        run_stats={"fetched": 50, "strong": 3},
        generated_at=_TS,
    )
    out = render_text(data)
    assert "fetched" in out
    assert "strong" in out


# ---------------------------------------------------------------------------
# Empty digest behaviour (0 jobs)
# ---------------------------------------------------------------------------

def test_digest_data_empty_total_is_zero():
    data = _data()
    assert len(data.strong) + len(data.eligible) == 0


def test_render_html_empty_digest_valid_html():
    """An all-empty digest must still produce valid HTML without crashing."""
    out = render_html(_data())
    assert out.startswith("<!doctype html>")
    assert "0 unnotified jobs" in out


def test_render_text_empty_digest_no_crash():
    out = render_text(_data())
    assert "0 unnotified jobs" in out
    assert "(none)" in out
