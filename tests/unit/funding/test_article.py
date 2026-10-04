"""Tests for funding/article.py: polite fetch + trafilatura extract + short extract."""
from pathlib import Path
from unittest.mock import patch

import httpx
import respx

from job_match.adapters.http import DEFAULT_USER_AGENT, HttpClient
from job_match.funding.article import ELLIPSIS, ArticleFetcher, make_extract

FIXTURES = Path(__file__).parent.parent.parent / "fixtures"
ARTICLE_URL = "https://www.maddyness.com/2026/10/02/acme-leve-10-millions/"


def _html() -> str:
    return (FIXTURES / "article_sample.html").read_text(encoding="utf-8")


def _fetcher(rps: float = 0.0) -> ArticleFetcher:
    return ArticleFetcher(http=HttpClient(max_retries=0), requests_per_second=rps)


# ---------------------------------------------------------------------------
# make_extract
# ---------------------------------------------------------------------------

def test_make_extract_collapses_whitespace_and_keeps_short_text():
    assert make_extract("  Hello\n\n  world \t!", 100) == "Hello world !"


def test_make_extract_cuts_on_word_boundary_with_ellipsis():
    text = "alpha beta gamma delta epsilon"
    out = make_extract(text, 12)  # "alpha beta g" → back to "alpha beta"
    assert out == "alpha beta" + ELLIPSIS
    assert len(out) <= 13


def test_make_extract_exact_limit_is_not_truncated():
    assert make_extract("abc def", 7) == "abc def"


# ---------------------------------------------------------------------------
# ArticleFetcher.fetch_text
# ---------------------------------------------------------------------------

def test_fetch_text_extracts_main_content_and_drops_chrome():
    with respx.mock:
        route = respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=_html()))
        fetcher = _fetcher()
        text = fetcher.fetch_text(ARTICLE_URL)

    assert text is not None
    assert "tour de table de 10 millions d'euros" in text
    assert "Mentions légales" not in text  # footer removed
    assert "À lire aussi" not in text  # aside removed
    assert fetcher.api_calls_count == 1
    assert route.calls[0].request.headers["User-Agent"] == DEFAULT_USER_AGENT


def test_fetch_text_returns_none_on_non_200():
    with respx.mock:
        respx.get(ARTICLE_URL).mock(return_value=httpx.Response(404, text="nope"))
        assert _fetcher().fetch_text(ARTICLE_URL) is None


def test_fetch_text_returns_none_on_network_error():
    with respx.mock:
        respx.get(ARTICLE_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
        fetcher = _fetcher()
        assert fetcher.fetch_text(ARTICLE_URL) is None
    assert fetcher.api_calls_count == 0


def test_fetch_text_returns_none_when_nothing_extractable():
    with respx.mock:
        respx.get(ARTICLE_URL).mock(
            return_value=httpx.Response(200, text="<html><head></head><body></body></html>")
        )
        assert _fetcher().fetch_text(ARTICLE_URL) is None


def test_fetch_text_survives_extractor_exception():
    with respx.mock:
        respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=_html()))
        with patch("job_match.funding.article.trafilatura.extract", side_effect=RuntimeError("x")):
            assert _fetcher().fetch_text(ARTICLE_URL) is None


def test_throttle_sleeps_between_requests():
    sleeps: list[float] = []
    with respx.mock:
        respx.get(ARTICLE_URL).mock(return_value=httpx.Response(200, text=_html()))
        fetcher = _fetcher(rps=10.0)  # 100 ms min interval
        with patch("job_match.funding.article.time.sleep", side_effect=sleeps.append):
            fetcher.fetch_text(ARTICLE_URL)
            fetcher.fetch_text(ARTICLE_URL)
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 0.1
