"""config/ats_boards.yaml: the shipped file loads, bad entries are refused early."""
from pathlib import Path

import pytest

from job_match.config.loader import load_ats_boards
from job_match.config.schema import ConfigError


def test_the_shipped_boards_file_loads_57_boards_of_five_ats():
    boards = load_ats_boards(Path("config/ats_boards.yaml"))
    assert len(boards) == 57
    assert {b.ats for b in boards} == {
        "greenhouse", "lever", "ashby", "smartrecruiters", "workday"}
    assert len({(b.ats, b.slug) for b in boards}) == 57  # no duplicate board
    assert len({b.company for b in boards}) == 57  # Padok / Theodo Cloud: one Theodo board


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
