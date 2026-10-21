import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from job_match.domain.models import RunSummary

_logger = logging.getLogger(__name__)


def _quiet_http_logs() -> None:
    """Keep httpx's request log above INFO.

    It prints the full URL, and for Jooble that URL carries the API key in its path
    (Adzuna puts credentials in the query string). `job-match run` output goes to a
    public Actions log, so the secret must never be written there. Errors still surface:
    adapters log their own aggregate line per query, with the URL redacted.
    """
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _config_dir() -> Path:
    """Config directory: $JOB_MATCH_CONFIG_DIR or ./config (relative to CWD)."""
    env = os.environ.get("JOB_MATCH_CONFIG_DIR")
    return Path(env) if env else Path("config")


def _data_dir() -> Path:
    """Data directory: $JOB_MATCH_DATA_DIR or ./data (relative to CWD)."""
    env = os.environ.get("JOB_MATCH_DATA_DIR")
    return Path(env) if env else Path("data")


def main() -> None:
    # Load .env without overriding env vars already set (CI secrets win).
    load_dotenv(override=False)

    parser = argparse.ArgumentParser(prog="job-match", description="Job intelligence pipeline")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    run_p = sub.add_parser("run", help="Fetch and process jobs from France Travail")
    run_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="Maximum offers per keyword x department query "
                            "(not a global cap: every query still runs)")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Run the full pipeline but write nothing to the database")

    rep_p = sub.add_parser(
        "reprocess",
        help="Re-apply the gate and scorer to jobs already in the DB (no API calls)",
    )
    rep_p.add_argument("--since", metavar="YYYY-MM-DD",
                       help="Only jobs collected on or after this date")
    rep_p.add_argument("--limit", type=int, default=None, metavar="N",
                       help="Show at most N top strong titles (0 for none; default 10)")
    rep_p.add_argument("--dry-run", action="store_true",
                       help="Report what would change without writing to the database")

    digest_p = sub.add_parser("digest", help="Send email digest of unnotified jobs")
    digest_p.add_argument(
        "--dry-run", action="store_true",
        help="Render HTML to data/digest_preview.html instead of sending",
    )
    digest_p.add_argument(
        "--resend-since", metavar="YYYY-MM-DD",
        help="Reset notified flag for jobs notified on or after this date, then send normally",
    )

    dash_p = sub.add_parser(
        "dashboard", help="Write the static dashboard (index.html + data.json) from the DB",
    )
    dash_p.add_argument("--out", default="site", metavar="DIR",
                        help="Output directory (default: site)")

    cal_p = sub.add_parser(
        "calibrate",
        help="Compare dashboard verdicts with scores; suggests changes, never applies them",
    )
    cal_p.add_argument("--since", metavar="YYYY-MM-DD",
                       help="Only verdicts given on/after this date")

    tracking_p = sub.add_parser("tracking", help="Application tracking mirror (D1 -> jobs DB)")
    tracking_sub = tracking_p.add_subparsers(dest="tracking_command", metavar="SUBCOMMAND")
    timp_p = tracking_sub.add_parser(
        "import", help="Replace the local mirror with `wrangler d1 execute --json` exports",
    )
    timp_p.add_argument("--applications", required=True, metavar="PATH",
                        help="Export of SELECT * FROM applications")
    timp_p.add_argument("--decisions", required=True, metavar="PATH",
                        help="Export of SELECT * FROM decisions")
    timp_p.add_argument("--skill-overrides", metavar="PATH",
                        help="Export of SELECT * FROM skill_overrides "
                             "(default: keep the current mirror)")

    funding_p = sub.add_parser("funding", help="Funding / news pipeline")
    funding_sub = funding_p.add_subparsers(dest="funding_command", metavar="SUBCOMMAND")
    frun_p = funding_sub.add_parser("run", help="Ingest articles from RSS feeds")
    frun_p.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of feed entries to process")
    frun_p.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but write nothing to the database")
    frep_p = funding_sub.add_parser(
        "reprocess", help="Refetch stored articles and (re)run funding extraction",
    )
    frep_p.add_argument("--since", metavar="YYYY-MM-DD",
                        help="Re-extract every article collected on/after this date "
                             "(default: only articles never processed)")
    frep_p.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Maximum number of articles to reprocess")
    frep_p.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but write nothing to the database")

    args = parser.parse_args()

    if args.command == "run":
        _cmd_run(args)
    elif args.command == "reprocess":
        _cmd_reprocess(args)
    elif args.command == "digest":
        _cmd_digest(args)
    elif args.command == "dashboard":
        _cmd_dashboard(args)
    elif args.command == "calibrate":
        _cmd_calibrate(args)
    elif args.command == "tracking":
        if args.tracking_command == "import":
            _cmd_tracking_import(args)
        else:
            tracking_p.print_help()
            sys.exit(1)
    elif args.command == "funding":
        if args.funding_command == "run":
            _cmd_funding_run(args)
        elif args.funding_command == "reprocess":
            _cmd_funding_reprocess(args)
        else:
            funding_p.print_help()
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


def _cmd_reprocess(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _quiet_http_logs()

    from datetime import UTC, datetime

    from job_match.config.loader import (
        load_aliases,
        load_profile,
        load_settings,
        load_skill_vocabulary,
    )
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository
    from job_match.pipelines.jobs import reprocess_jobs

    cfg = _config_dir()
    data_dir = _data_dir()
    profile = load_profile(cfg / "profile.yaml")
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    vocabulary = load_skill_vocabulary(cfg / "skill_vocabulary.yaml")

    since = None
    if args.since:
        try:
            since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            sys.exit(1)

    db_path = data_dir / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)

    with Database(path=str(db_path)) as db:
        profile = _with_skill_overrides(profile, settings, db)
        summary = reprocess_jobs(
            profile, settings, db, aliases,
            since=since, dry_run=args.dry_run, vocabulary=vocabulary,
        )
        top = JobRepository(db.conn).list_eligible(min_score=settings.strong_threshold)

    _print_reprocess_summary(summary, top, limit=args.limit, dry_run=args.dry_run)


def _print_reprocess_summary(
    summary: RunSummary, top: list, *, limit: int | None, dry_run: bool
) -> None:
    """Aggregate counts, then the N best scores.

    `--limit 0` prints the counts alone: the daily workflow runs this step in a public
    Actions log, where individual postings have no business being.
    """
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nReprocess complete{tag}")
    print(f"  jobs read:  {summary.fetched}")
    print(f"  rejected:   {summary.rejected_jobs} jobs")
    if summary.rejected_by_reason:
        print("  reason breakdown (may sum > jobs; a job can fail multiple gates):")
        for reason, count in sorted(summary.rejected_by_reason.items()):
            print(f"    {reason}: {count}")
    print(f"  eligible:   {summary.eligible}")
    print(f"  strong:     {summary.strong}")
    print(f"  stretch:    {summary.stretch}  (experience within stretch_years; never strong)")
    if summary.rqth_recruiter:
        print(
            f"  RQTH recruiter offers: {summary.rqth_recruiter}"
            f" (end client named: {summary.rqth_end_client})"
        )
    print(f"  new duplicate links: {summary.duplicates}")
    print(f"  links removed:       {summary.stale_links_dropped}  (rules no longer match)")
    if summary.self_links_dropped:
        print(f"  self-links dropped:  {summary.self_links_dropped}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
    if summary.by_department:
        _print_top_departments(summary.by_department)

    n = 10 if limit is None else limit
    if top and n > 0:
        print(f"\n  top {min(n, len(top))} strong titles:")
        for job in top[:n]:
            print(f"    {job.score:>3}  {job.title}  —  {job.company}")


def _cmd_digest(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, date, datetime

    from job_match.config.loader import load_settings
    from job_match.notification.assemble import build_digest
    from job_match.notification.digest import render_html
    from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository, LeadRepository

    cfg = _config_dir()
    data_dir = _data_dir()
    settings = load_settings(cfg / "settings.yaml")
    db_path = str(data_dir / "jobs.sqlite")

    if args.resend_since:
        try:
            since = date.fromisoformat(args.resend_since)
        except ValueError:
            print(
                f"Invalid date {args.resend_since!r} — expected YYYY-MM-DD",
                file=sys.stderr,
            )
            sys.exit(1)
        with Database(path=db_path) as db:
            n_jobs = JobRepository(db.conn).reset_notified_since(since)
            n_leads = LeadRepository(db.conn).reset_notified_since(since)
        print(f"  Reset notified_at for {n_jobs} job(s) and {n_leads} lead(s) since {since}")

    with Database(path=db_path) as db:
        batch = build_digest(db, settings, datetime.now(UTC))
    data = batch.data

    print(
        f"Digest: {len(batch.job_ids)} unnotified jobs ({len(data.strong)} strong, "
        f"{len(data.eligible)} eligible, {len(data.stretch)} stretch), "
        f"{len(batch.lead_ids)} funding leads, {len(data.followups)} follow-ups due"
    )
    print(
        f"  held back (stay unnotified): {batch.jobs_below_min_score} jobs below "
        f"min_score {settings.digest.min_score}; leads filtered "
        f"{dict(sorted(batch.leads_filtered.items())) or '{}'}, "
        f"{batch.leads_overflow} over max_leads {settings.digest.max_leads}"
    )

    if args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)
        preview = data_dir / "digest_preview.html"
        preview.write_text(render_html(data), encoding="utf-8")
        print(f"  [DRY RUN] HTML written to {preview}")
        return

    if batch.is_empty:
        print("  No new jobs, leads or follow-ups to send.")
        return

    try:
        notifier = EmailNotifier.from_env()
    except SmtpConfigError as exc:
        print(f"SMTP not configured: {exc}", file=sys.stderr)
        sys.exit(1)

    if not notifier.send(data):
        print("  Send failed — see logs. Nothing marked as notified.", file=sys.stderr)
        sys.exit(1)

    # Mark only after a successful send, so a failed send is retried next run.
    sent_at = datetime.now(UTC)
    with Database(path=db_path) as db:
        JobRepository(db.conn).mark_notified(list(batch.job_ids), sent_at)
        LeadRepository(db.conn).mark_notified(list(batch.lead_ids), sent_at)
    print(f"  Sent. {len(batch.job_ids)} jobs and {len(batch.lead_ids)} leads marked as notified.")


def _cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    _quiet_http_logs()

    from job_match.adapters.jobs.factory import build_sources, missing_env
    from job_match.config.loader import (
        load_aliases,
        load_profile,
        load_settings,
        load_skill_vocabulary,
    )
    from job_match.persistence.db import Database
    from job_match.pipelines.jobs import run_jobs

    cfg = _config_dir()
    data_dir = _data_dir()
    profile_path = cfg / "profile.yaml"
    profile = load_profile(profile_path)
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    vocabulary = load_skill_vocabulary(cfg / "skill_vocabulary.yaml")
    print(f"profile: {profile_path} (experience_years={profile.candidate.experience_years})")

    if not args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)

    # Each enabled source with credentials runs; the others are skipped with a warning
    # inside build_sources. Only an empty result is fatal.
    sources = build_sources(profile, settings, limit=args.limit)
    if not sources:
        print("No job source could run. Missing credentials:", file=sys.stderr)
        for name in settings.sources.enabled:
            for var in missing_env(name):
                print(f"  {name}: {var}", file=sys.stderr)
        print("Set them in .env or as env vars (see .env.example).", file=sys.stderr)
        sys.exit(1)
    print(f"sources: {', '.join(s.name for s in sources)}")

    db_path = ":memory:" if args.dry_run else str(data_dir / "jobs.sqlite")

    # A dry run reads an empty in-memory DB, so it runs without the skill overrides.
    with Database(path=db_path) as db:
        profile = _with_skill_overrides(profile, settings, db)
        summary = run_jobs(
            sources, profile, settings, db, aliases,
            dry_run=args.dry_run, vocabulary=vocabulary,
        )

    _print_summary(summary, dry_run=args.dry_run)


def _build_funding_sources(names: list[str]) -> list:
    from job_match.adapters.funding.frenchweb import FrenchWebSource
    from job_match.adapters.funding.maddyness import MaddynessSource

    registry = {"maddyness": MaddynessSource, "frenchweb": FrenchWebSource}
    sources = []
    for name in names:
        cls = registry.get(name)
        if cls is None:
            print(f"Unknown funding source {name!r} in settings.yaml "
                  f"(known: {', '.join(sorted(registry))})", file=sys.stderr)
            sys.exit(1)
        sources.append(cls())
    return sources


def _cmd_tracking_import(args: argparse.Namespace) -> None:
    """Mirror the D1 tracking tables. Prints counts only: notes and links are private and
    the CI log is public."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.config.loader import load_skill_vocabulary
    from job_match.persistence.db import Database
    from job_match.tracking.mirror import MirrorFormatError, import_tracking

    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    overrides_arg = getattr(args, "skill_overrides", None)
    overrides_path = Path(overrides_arg) if overrides_arg else None
    vocabulary = load_skill_vocabulary(_config_dir() / "skill_vocabulary.yaml")
    with Database(path=str(db_path)) as db:
        try:
            result = import_tracking(
                db.conn, Path(args.applications), Path(args.decisions),
                overrides_path, vocabulary,
            )
        except MirrorFormatError as exc:
            print(f"Tracking export rejected ({exc}); previous mirror kept.", file=sys.stderr)
            sys.exit(1)
    print(
        f"Tracking mirror: {result.applications} applications, {result.decisions} decisions,"
        f" {result.skill_overrides} skill overrides"
        f"{' (changed)' if result.overrides_changed else ''},"
        f" {result.skipped} invalid rows skipped"
    )
    # The daily workflow reprocesses stored jobs only when the overrides changed.
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as fh:
            changed = "true" if result.overrides_changed else "false"
            fh.write(f"overrides_changed={changed}\n")


def _cmd_calibrate(args: argparse.Namespace) -> None:
    """Local only: the report names skills, so it never runs in the public CI log."""
    from datetime import date

    from job_match.calibration.report import DecidedJob, build_report, format_report
    from job_match.config.loader import load_settings
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import ApplicationRepository

    since = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"--since must be YYYY-MM-DD, got {args.since!r}", file=sys.stderr)
            sys.exit(1)
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)
    settings = load_settings(_config_dir() / "settings.yaml")
    with Database(path=str(db_path)) as db:
        decided = ApplicationRepository(db.conn).list_latest_decisions(since)
    rows = [
        DecidedJob(
            label=label,
            score=score,
            positive=bd.positive_matches if bd else (),
            negative=bd.negative_matches if bd else (),
            unlisted=tuple(bd.unlisted) if bd else (),
        )
        for label, score, bd in decided
    ]
    print(format_report(build_report(rows, settings.strong_threshold)))


def _with_skill_overrides(profile, settings, db):
    """The profile plus the mirrored "je maîtrise" skills. Logs the count, never names."""
    from job_match.config.loader import apply_skill_overrides
    from job_match.persistence.repositories import ApplicationRepository

    overrides = ApplicationRepository(db.conn).list_skill_overrides()
    if overrides:
        print(f"skill overrides: {len(overrides)}")
    return apply_skill_overrides(profile, overrides, settings.scoring.override_weight)


def _cmd_dashboard(args: argparse.Namespace) -> None:
    """Write the static dashboard. Prints counts only: the CI log is public."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, datetime

    from job_match.config.loader import load_settings
    from job_match.dashboard.data import build_dashboard_data
    from job_match.dashboard.render import write_site
    from job_match.persistence.db import Database

    settings = load_settings(_config_dir() / "settings.yaml")
    db_path = _data_dir() / "jobs.sqlite"
    if not db_path.exists():
        print(f"No database at {db_path}: run `job-match run` first.", file=sys.stderr)
        sys.exit(1)

    with Database(path=str(db_path)) as db:
        data = build_dashboard_data(db, settings, datetime.now(UTC))
    write_site(data, Path(args.out))

    by_section = {s: 0 for s in ("strong", "eligible", "stretch")}
    for job in data["jobs"]:
        by_section[job["section"]] += 1
    print(
        f"Dashboard: {len(data['jobs'])} jobs ({by_section['strong']} strong, "
        f"{by_section['eligible']} eligible, {by_section['stretch']} stretch), "
        f"{len(data['leads'])} leads, {len(data['runs'])} runs -> {args.out}"
    )


def _cmd_funding_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.config.loader import load_settings
    from job_match.funding.article import ArticleFetcher
    from job_match.persistence.db import Database
    from job_match.pipelines.funding import run_funding

    cfg = _config_dir()
    data_dir = _data_dir()
    settings = load_settings(cfg / "settings.yaml")
    sources = _build_funding_sources(settings.funding.sources)
    fetcher = ArticleFetcher(requests_per_second=settings.funding.requests_per_second)

    if args.dry_run:
        db_path = ":memory:"
        print("[DRY RUN] in-memory DB: every article counts as new, nothing is written")
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(data_dir / "jobs.sqlite")

    with Database(path=db_path) as db:
        summary = run_funding(
            sources, settings, db, fetcher, limit=args.limit, dry_run=args.dry_run,
        )

    _print_funding_summary(summary, dry_run=args.dry_run)


def _cmd_funding_reprocess(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import date

    from job_match.config.loader import load_settings
    from job_match.funding.article import ArticleFetcher
    from job_match.persistence.db import Database
    from job_match.pipelines.funding import reprocess_funding

    since: date | None = None
    if args.since:
        try:
            since = date.fromisoformat(args.since)
        except ValueError:
            print(f"Invalid date {args.since!r} — expected YYYY-MM-DD", file=sys.stderr)
            sys.exit(1)

    cfg = _config_dir()
    settings = load_settings(cfg / "settings.yaml")
    fetcher = ArticleFetcher(requests_per_second=settings.funding.requests_per_second)
    db_path = str(_data_dir() / "jobs.sqlite")  # reprocess always reads the real DB

    if args.dry_run:
        print("[DRY RUN] extraction runs on stored articles, nothing is written")

    with Database(path=db_path) as db:
        summary = reprocess_funding(
            settings, db, fetcher, since=since, limit=args.limit, dry_run=args.dry_run,
        )

    _print_funding_summary(summary, dry_run=args.dry_run, kind="reprocess")


def _print_funding_summary(
    summary: RunSummary, *, dry_run: bool = False, kind: str = "run"
) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nFunding {kind} complete{tag}")
    if kind == "run":
        print(f"  feeds:      {summary.feeds}")
        print(f"  found:      {summary.fetched}")
        print(f"  new:        {summary.articles}")
        print(f"  skipped:    {summary.duplicates}  (already seen)")
    else:
        print(f"  selected:   {summary.fetched}")
        print(f"  processed:  {summary.articles}")
    print(f"  errors:     {summary.errors}")
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    print(f"  funding:    {summary.funding_articles}  "
          f"(articles, no company: {summary.funding_no_company})")
    print(f"  events:     {summary.funding_events}")
    print(f"  leads:      {summary.leads}  (deduped: {summary.leads_deduped})")
    if summary.by_source:
        print("  by source:")
        for name in sorted(summary.by_source):
            b = summary.by_source[name]
            print(f"    {name:<12} articles={b.get('articles', 0)} funding={b.get('funding', 0)} "
                  f"events={b.get('events', 0)} leads={b.get('leads', 0)}")


def _print_top_departments(by_department: dict[str, int], top: int = 10) -> None:
    """Where the offers are, biggest first. "?" = no single department (region or unknown)."""
    ranked = sorted(by_department.items(), key=lambda kv: (-kv[1], kv[0]))
    print(f"  fetched per department, from the offer location (top {top}):")
    for dept, count in ranked[:top]:
        print(f"    {dept}: {count}")
    if len(ranked) > top:
        rest = sum(count for _dept, count in ranked[top:])
        print(f"    +{len(ranked) - top} more departments: {rest}")


def _print_summary(summary: RunSummary, *, dry_run: bool = False) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nJobs run complete{tag}")
    print(f"  queries:    {summary.queries}  (keyword x area)")
    print(f"  fetched:    {summary.fetched}")
    print(f"  normalized: {summary.normalized}")
    print(f"  rejected:   {summary.rejected_jobs} jobs")  # unique jobs, not reason count
    if summary.rejected_by_reason:
        print("  reason breakdown (may sum > jobs; a job can fail multiple gates):")
        for reason, count in sorted(summary.rejected_by_reason.items()):
            print(f"    {reason}: {count}")
    print(f"  duplicates: {summary.duplicates}")
    print(f"  eligible:   {summary.eligible}")
    print(f"  strong:     {summary.strong}")
    print(f"  stretch:    {summary.stretch}  (experience within stretch_years; never strong)")
    if summary.rqth_recruiter:
        print(
            f"  RQTH recruiter offers: {summary.rqth_recruiter}"
            f" (end client named: {summary.rqth_end_client})"
        )
    if summary.pipeline == "jobs":
        print(f"  checked:    {summary.checked}  (stored offers re-checked at the source)")
        print(f"  closed:     {summary.closed}  (hidden from the digest and the dashboard)")
        print(f"  raw payloads: stored {summary.raw_stored} (new or changed),"
              f" pruned {summary.raw_pruned}")
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
    if summary.by_source:
        print("  per source (fetched / eligible / duplicates / api calls):")
        for name in sorted(summary.by_source):
            c = summary.by_source[name]
            print(
                f"    {name:<16} {c.get('fetched', 0):>5} / {c.get('eligible', 0):>4}"
                f" / {c.get('duplicates', 0):>4} / {c.get('calls', 0):>4}"
            )
    if summary.by_area:
        print("  fetched per queried area:")
        for area, count in sorted(summary.by_area.items()):
            print(f"    {area}: {count}")
    if summary.by_department:
        _print_top_departments(summary.by_department)
    if summary.by_keyword:
        # Query keywords come from the private profile and this output lands in a public
        # CI log: departments are printed, the per-keyword breakdown stays at DEBUG.
        _logger.debug(
            "fetched per keyword: %s",
            ", ".join(f"{kw}={count}" for kw, count in sorted(summary.by_keyword.items())),
        )
