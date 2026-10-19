"""`_print_summary`: the closure counts, on the jobs run only."""
from job_match.cli import _print_summary
from job_match.domain.models import RunSummary


def test_jobs_summary_prints_checked_and_closed(capsys):
    _print_summary(RunSummary(pipeline="jobs", fetched=3, checked=12, closed=4))
    out = capsys.readouterr().out
    assert "checked:    12" in out
    assert "closed:     4" in out


def test_reprocess_summary_has_no_closure_lines(capsys):
    _print_summary(RunSummary(pipeline="jobs_reprocess", fetched=3))
    out = capsys.readouterr().out
    assert "checked:" not in out and "closed:" not in out
