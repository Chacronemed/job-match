"""config/ats_boards.yaml: the shipped file loads, bad entries are refused early."""
from pathlib import Path

import pytest

from job_match.config.loader import load_ats_boards
from job_match.config.schema import ConfigError


def test_the_shipped_boards_file_loads_61_boards_of_six_ats():
    boards = load_ats_boards(Path("config/ats_boards.yaml"))
    assert len(boards) == 61
    assert {b.ats for b in boards} == {
        "greenhouse", "lever", "ashby", "smartrecruiters", "workday", "talentsoft"}
    assert len({(b.ats, b.slug) for b in boards}) == 61  # no duplicate board
    assert len({b.company for b in boards}) == 61  # Padok / Theodo Cloud: one Theodo board


def test_the_boards_verified_on_2026_11_20_are_listed():
    """docs/diagnostics/2026-11-20-coverage.md: the ten Workday tenants kept their slug,
    Murex joined them, Sopra Steria and Inetum are on SmartRecruiters (not Workday), Air
    France is read through its Talentsoft feed."""
    boards = {b.company: (b.ats, b.slug) for b in load_ats_boards(Path("config/ats_boards.yaml"))}
    assert boards["Murex"] == ("workday", "murex.wd3.myworkdayjobs.com/murex/MurexCareerPage1")
    assert boards["Euronext"] == (
        "workday", "hrhub.wd3.myworkdayjobs.com/hrhub/Euronext_Career_Page")
    assert boards["Sopra Steria"] == ("smartrecruiters", "SopraSteria1")
    assert boards["Inetum"] == ("smartrecruiters", "Inetum2")
    assert boards["Air France"] == ("talentsoft", "recrutement.airfrance.com")
    assert sum(ats == "workday" for ats, _ in boards.values()) == 11


def test_talentsoft_slug_is_the_career_site_host(tmp_path):
    path = tmp_path / "ats_boards.yaml"
    path.write_text("boards:\n  - {company: X, ats: talentsoft, slug: recrutement.example.com}\n",
                    encoding="utf-8")
    (board,) = load_ats_boards(path)
    assert (board.ats, board.slug) == ("talentsoft", "recrutement.example.com")


def test_workday_slug_and_max_postings(tmp_path):
    path = tmp_path / "ats_boards.yaml"
    path.write_text("boards:\n  - {company: X, ats: workday, max_postings: 40,\n"
                    "     slug: x.wd3.myworkdayjobs.com/x/Careers}\n", encoding="utf-8")
    (board,) = load_ats_boards(path)
    assert (board.slug, board.max_postings) == ("x.wd3.myworkdayjobs.com/x/Careers", 40)


def test_missing_file_means_no_boards(tmp_path):
    assert load_ats_boards(tmp_path / "none.yaml") == []


@pytest.mark.parametrize("body", [
    "boards:\n  - {company: X, ats: taleo, slug: x}\n",       # unsupported ATS
    "boards:\n  - {company: X, ats: workday, slug: x}\n",     # not host/tenant/site
    "boards:\n  - {company: X, ats: workday, slug: 'evil.com/a/b'}\n",  # not Workday's host
    "boards:\n  - {company: X, ats: talentsoft, slug: 'example.com/path'}\n",  # host only
    "boards:\n  - {company: X, ats: talentsoft, slug: '10.0.0.1'}\n",          # not an IP
    "boards:\n  - {company: X, ats: talentsoft, slug: localhost}\n",           # no bare name
    "boards:\n  - {company: X, ats: lever, slug: x, max_postings: 0}\n",
    "boards:\n  - {company: X, ats: lever, slug: 'a/b'}\n",   # not URL-safe
    "boards:\n  - {company: '', ats: lever, slug: ok}\n",     # no company
    "boards: {a: 1}\n",                                       # not a list
])
def test_invalid_entries_are_refused(tmp_path, body):
    path = tmp_path / "ats_boards.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_ats_boards(path)
