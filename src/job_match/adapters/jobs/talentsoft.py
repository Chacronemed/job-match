"""Talentsoft (Cegid) career sites through the offers RSS feed they publish (ADR 0029).

A Talentsoft front office lists its feeds on `/offre-de-emploi/tous-les-flux-rss.aspx`; the
unfiltered one is

    GET https://<host>/handlers/offerRss.ashx?LCID=1036        (1036 = French)
    → RSS 2.0, the 20 newest offers:
      <item>
        <link>https://<host>/Pages/Offre/detailoffre.aspx?idOffre=25855&…</link>
        <category>job family</category> <category>contract</category>
        <category>site (free text: an address, a town, a site code)</category>
        <title>2026-25855 - Ingénieur DevOps F/H</title>
        <description>HTML: Métier, Type de contrat, Description du poste, Site, …</description>
        <pubDate>Fri, 20 Nov 2026 15:36:36 Z</pubDate>
      </item>

One GET per board and run, no detail call: the description is in the feed. It is a feed the
site offers for syndication, not a page: no HTML page is fetched (ADR 0020). The feed only
shows its 20 newest offers, so the listing is never complete: an offer that left the feed is
UNKNOWN to the closure check, never CLOSED, and the age cut-off hides it in the end.

This module only reads the feed and maps an item; `AtsBoardSource` (ats.py) makes the call,
so pacing, errors, request stats and `source_job_id` are the ones of every other board.
"""
import calendar
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import feedparser

from job_match.normalization.text import html_to_text

FEED_URL = "https://{host}/handlers/offerRss.ashx?LCID=1036"

_REFERENCE_PREFIX = re.compile(r"^\s*\d{4}-\d+\s*-\s*")  # "2026-25855 - " before the title
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def parse_feed(content: bytes) -> list[dict]:
    """The feed's offers as plain dicts (JSON-serializable: they are stored as raw payloads).

    Raises ValueError when the body is not a feed at all (an HTML error page). An item
    without an offer id in its link is dropped: it could not be found again."""
    feed = feedparser.parse(content)
    if not feed.get("version"):  # feedparser names the format of a real feed ("rss20")
        raise ValueError("not an RSS feed")
    items: list[dict] = []
    for entry in feed.entries:
        link = str(entry.get("link") or "")
        offer_id = _offer_id(link)
        if not offer_id:
            continue
        published = entry.get("published_parsed")
        items.append({
            "id": offer_id,
            "title": str(entry.get("title") or ""),
            "link": link,
            "summary": str(entry.get("summary") or ""),
            "categories": [str(t.get("term") or "") for t in entry.get("tags") or []],
            "published": (
                datetime.fromtimestamp(calendar.timegm(published), tz=UTC).isoformat()
                if published else None
            ),
        })
    return items


def _offer_id(link: str) -> str:
    """`…detailoffre.aspx?idOffre=25855&offerReference=2026-25855` → `25855`."""
    query = parse_qs(urlsplit(link).query)
    for key in ("idOffre", "idoffre", "offerReference"):
        value = (query.get(key) or [""])[0]
        if value:
            return _SAFE_ID.sub("", value)[:100]
    return ""


def map_item(raw: dict) -> tuple[str, str, str, str | None, str]:
    """(title, url, location, contract hint, description) of one feed item.

    The categories come as job family, contract, site, in that order; with another count
    nothing is guessed and the location stays empty (the description still carries its
    "Site :" line for whoever reads it)."""
    categories = [c for c in raw.get("categories") or [] if isinstance(c, str)]
    contract, location = (categories[1], categories[2]) if len(categories) == 3 else (None, "")
    return (
        _REFERENCE_PREFIX.sub("", str(raw.get("title") or "")).strip(),
        str(raw.get("link") or ""),
        location.strip(),
        contract or None,
        html_to_text(raw.get("summary")),
    )


__all__ = ["FEED_URL", "map_item", "parse_feed"]
