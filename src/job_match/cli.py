import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from job_match.domain.models import RunSummary

_FT_VARS = ("FT_CLIENT_ID", "FT_CLIENT_SECRET")


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
                       help="Maximum number of items to process")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Run the full pipeline but write nothing to the database")

    digest_p = sub.add_parser("digest", help="Send email digest of unnotified jobs")
    digest_p.add_argument(
        "--dry-run", action="store_true",
        help="Render HTML to data/digest_preview.html instead of sending",
    )
    digest_p.add_argument(
        "--resend-since", metavar="YYYY-MM-DD",
        help="Reset notified flag for jobs notified on or after this date, then send normally",
    )

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
    elif args.command == "digest":
        _cmd_digest(args)
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


def _cmd_digest(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from datetime import UTC, date, datetime

    from job_match.config.loader import load_settings
    from job_match.notification.digest import DigestData, render_html
    from job_match.notification.email_notifier import EmailNotifier, SmtpConfigError
    from job_match.persistence.db import Database
    from job_match.persistence.repositories import JobRepository

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
            n = JobRepository(db.conn).reset_notified_since(since)
        print(f"  Reset notified_at for {n} job(s) notified since {since}")

    with Database(path=db_path) as db:
        job_repo = JobRepository(db.conn)
        jobs = job_repo.list_unnotified()

    strong = tuple(j for j in jobs if j.score is not None and j.score >= settings.strong_threshold)
    eligible = tuple(j for j in jobs if j not in strong)

    data = DigestData(
        strong=strong,
        eligible=eligible,
        generated_at=datetime.now(UTC),
    )

    total = len(strong) + len(eligible)
    print(f"Digest: {total} unnotified jobs ({len(strong)} strong, {len(eligible)} eligible)")

    if args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)
        preview = data_dir / "digest_preview.html"
        preview.write_text(render_html(data), encoding="utf-8")
        print(f"  [DRY RUN] HTML written to {preview}")
        return

    if total == 0:
        print("  No new jobs to send.")
        return

    try:
        notifier = EmailNotifier.from_env()
    except SmtpConfigError as exc:
        print(f"SMTP not configured: {exc}", file=sys.stderr)
        sys.exit(1)

    ok = notifier.send(data)
    if ok:
        with Database(path=db_path) as db:
            job_repo = JobRepository(db.conn)
            job_ids = [j.id for j in jobs if j.id is not None]
            job_repo.mark_notified(job_ids, datetime.now(UTC))
        print(f"  Sent. {total} jobs marked as notified.")
    else:
        print("  Send failed — see logs. Jobs not marked as notified.", file=sys.stderr)
        sys.exit(1)


def _cmd_run(args: argparse.Namespace) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    from job_match.adapters.jobs.france_travail import FranceTravailSource
    from job_match.config.loader import load_aliases, load_profile, load_settings
    from job_match.persistence.db import Database
    from job_match.pipelines.jobs import run_jobs

    cfg = _config_dir()
    data_dir = _data_dir()
    profile_path = cfg / "profile.yaml"
    profile = load_profile(profile_path)
    settings = load_settings(cfg / "settings.yaml")
    aliases = load_aliases(cfg / "aliases.yaml")
    print(f"profile: {profile_path} (experience_years={profile.candidate.experience_years})")

    if not args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)

    missing = [v for v in _FT_VARS if not os.environ.get(v)]
    if missing:
        for var in missing:
            print(f"Missing {var}: set it in .env or as an env var", file=sys.stderr)
        sys.exit(1)

    db_path = ":memory:" if args.dry_run else str(data_dir / "jobs.sqlite")
    source = FranceTravailSource(profile, requests_per_second=settings.ft_requests_per_second)

    with Database(path=db_path) as db:
        summary = run_jobs(
            source, profile, settings, db, aliases,
            limit=args.limit,
            dry_run=args.dry_run,
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


def _print_summary(summary: RunSummary, *, dry_run: bool = False) -> None:
    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nJobs run complete{tag}")
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
    if summary.api_calls:
        print(f"  api_calls:  {summary.api_calls}")
    if summary.errors:
        print(f"  errors:     {summary.errors}")
