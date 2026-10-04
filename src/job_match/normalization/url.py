from urllib.parse import parse_qs, urlencode, urlparse

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "fbclid", "gclid", "msclkid",
})


def normalize_url(url: str) -> str:
    """Strip tracking query parameters."""
    try:
        p = urlparse(url)
        clean = {
            k: v
            for k, v in parse_qs(p.query, keep_blank_values=True).items()
            if k not in _TRACKING_PARAMS
        }
        return p._replace(query=urlencode(clean, doseq=True)).geturl()
    except Exception:
        return url


def normalize_article_url(url: str) -> str:
    """Stable dedup key for an article: tracking params stripped, lowercase scheme and
    host, no fragment, no trailing slash on the path."""
    try:
        p = urlparse(normalize_url(url.strip()))
        path = p.path.rstrip("/") or "/"
        return p._replace(
            scheme=p.scheme.lower(), netloc=p.netloc.lower(), path=path, fragment=""
        ).geturl()
    except Exception:
        return url.strip()
