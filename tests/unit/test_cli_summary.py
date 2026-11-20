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


def test_jobs_summary_prints_each_workday_board_and_the_blocked_counter(capsys):
    boards = [
        {"board": "workday:ag.Airbus", "company": "Airbus", "status": "blocked", "calls": 1,
         "listed": 0, "fetched": 0, "due_in": 0},
        {"board": "workday:thales.Careers", "company": "Thales", "status": "skipped",
         "calls": 0, "listed": 0, "fetched": 0, "due_in": 3},
        {"board": "workday:sanofi.SanofiCareers", "company": "Sanofi", "status": "ok",
         "calls": 9, "listed": 14, "fetched": 4, "due_in": 0},
    ]
    _print_summary(RunSummary(pipeline="jobs", workday_boards=boards, workday_blocked=1))
    out = capsys.readouterr().out
    assert "workday:    1 OK · 1 sauté par fréquence · 1 bloqué anti-robot  (10 calls)" in out
    assert "workday blocked (anti-robot, not retried): 1" in out
    assert "Airbus           bloqué anti-robot · 1 calls, 0 listed, 0 read" in out
    assert "Thales           sauté par fréquence (prochaine lecture dans 3 j)" in out
    assert "Sanofi           OK · 9 calls, 14 listed, 4 read" in out


def test_a_run_without_workday_boards_prints_no_workday_line(capsys):
    _print_summary(RunSummary(pipeline="jobs", fetched=3))
    assert "workday" not in capsys.readouterr().out
