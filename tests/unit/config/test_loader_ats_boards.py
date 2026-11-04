"""config/ats_boards.yaml: the shipped file loads, bad entries are refused early."""
from pathlib import Path

import pytest

from job_match.config.loader import load_ats_boards
from job_match.config.schema import ConfigError


def test_the_shipped_boards_file_loads_30_boards_of_three_ats():
    boards = load_ats_boards(Path("config/ats_boards.yaml"))
    assert len(boards) == 30
    assert {b.ats for b in boards} == {"greenhouse", "lever", "ashby"}
    assert len({(b.ats, b.slug) for b in boards}) == 30  # no duplicate board


def test_missing_file_means_no_boards(tmp_path):
    assert load_ats_boards(tmp_path / "none.yaml") == []


@pytest.mark.parametrize("body", [
    "boards:\n  - {company: X, ats: workday, slug: x}\n",     # unsupported ATS
    "boards:\n  - {company: X, ats: lever, slug: 'a/b'}\n",   # not URL-safe
    "boards:\n  - {company: '', ats: lever, slug: ok}\n",     # no company
    "boards: {a: 1}\n",                                       # not a list
])
def test_invalid_entries_are_refused(tmp_path, body):
    path = tmp_path / "ats_boards.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_ats_boards(path)
