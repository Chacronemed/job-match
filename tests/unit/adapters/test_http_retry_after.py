"""`Retry-After` as a source sends it: seconds, an HTTP date, or nothing usable."""
from datetime import UTC, datetime

import httpx
import pytest

from job_match.adapters.http import retry_after_seconds

NOW = datetime(2026, 11, 20, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(("header", "expected"), [
    ("7", 7.0),
    ("0", 0.0),
    ("1.5", 1.5),
    ("-3", 0.0),                                   # never a negative wait
    ("Fri, 20 Nov 2026 12:00:30 GMT", 30.0),       # an HTTP date: the time left until it
    ("Fri, 20 Nov 2026 11:00:00 GMT", 0.0),        # already past
    ("soon", None),                                # unreadable: the caller's own backoff
    ("", None),
])
def test_retry_after_seconds(header, expected):
    resp = httpx.Response(429, headers={"Retry-After": header} if header else {})
    assert retry_after_seconds(resp, now=NOW) == expected
