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
