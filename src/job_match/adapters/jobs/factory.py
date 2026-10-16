"""Builds the enabled job sources from settings plus the environment.

Credentials come from the environment only, never from a config file. A source that is
enabled but has no credentials is skipped with a single WARNING and the run continues on
whatever is left: a missing Jooble key must not cost us the France Travail run.
"""
import logging
import os

from job_match.adapters.jobs.base import JobSource
from job_match.config.schema import Profile, Settings

logger = logging.getLogger(__name__)

# source name → the env vars it cannot run without
REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "france_travail": ("FT_CLIENT_ID", "FT_CLIENT_SECRET"),
    "jooble": ("JOOBLE_API_KEY",),
    "adzuna": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
}

KNOWN_SOURCES = tuple(REQUIRED_ENV)


def missing_env(name: str) -> list[str]:
    """Env vars required by `name` that are unset or empty."""
    return [var for var in REQUIRED_ENV.get(name, ()) if not os.environ.get(var)]


def build_sources(
    profile: Profile,
    settings: Settings,
    *,
    limit: int | None = None,
) -> list[JobSource]:
    """The sources listed in `settings.sources.enabled` that have credentials.

    `limit` is a per-query cap, not a global one: France Travail applies it to every
    (keyword, department) query, the quota-light sources to every (keyword, region) query.
    """
    # Imported here so a missing optional source never breaks `job-match --help`.
    from job_match.adapters.jobs.adzuna import AdzunaSource
    from job_match.adapters.jobs.france_travail import FranceTravailSource
    from job_match.adapters.jobs.jooble import JoobleSource

    sources: list[JobSource] = []
    for name in settings.sources.enabled:
        if name not in REQUIRED_ENV:
            logger.warning("unknown source %r in sources.enabled — skipped", name)
            continue

        missing = missing_env(name)
        if missing:
            logger.warning(
                "%s: skipped, missing %s (set it in .env or as an env var)",
                name, ", ".join(missing),
            )
            continue

        regions = list(settings.sources.regions)
        max_calls = settings.sources.max_calls(name)

        if name == "france_travail":
            kwargs = {} if limit is None else {"max_results": limit}
            sources.append(
                FranceTravailSource(
                    profile,
                    requests_per_second=settings.ft_requests_per_second,
                    **kwargs,
                )
            )
        elif name == "jooble":
            sources.append(
                JoobleSource(
                    profile,
                    api_key=os.environ["JOOBLE_API_KEY"],
                    regions=regions,
                    max_calls_per_run=max_calls,
                    **({} if limit is None else {"max_results": limit}),
                )
            )
        elif name == "adzuna":
            sources.append(
                AdzunaSource(
                    profile,
                    app_id=os.environ["ADZUNA_APP_ID"],
                    app_key=os.environ["ADZUNA_APP_KEY"],
                    regions=regions,
                    max_calls_per_run=max_calls,
                    **({} if limit is None else {"max_results": limit}),
                )
            )

    return sources
