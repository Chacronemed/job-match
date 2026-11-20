import logging
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "job-match/0.1 (+https://github.com/Chacronemed/job-match)"


def retry_after_seconds(resp: httpx.Response, now: datetime | None = None) -> float | None:
    """What the response's `Retry-After` asks for, in seconds; None without a usable one.

    Both forms of RFC 9110 are read: a number of seconds, or an HTTP date (then the wait is
    the time left until it, never negative)."""
    header = (resp.headers.get("Retry-After") or "").strip()
    if not header:
        return None
    try:
        return max(float(header), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - (now or datetime.now(UTC))).total_seconds(), 0.0)


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    asked = retry_after_seconds(resp)
    return asked if asked is not None else min(2**attempt, 60)


class HttpClient:
    def __init__(
        self,
        timeout_connect: float = 5.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
        user_agent: str = DEFAULT_USER_AGENT,
        follow_redirects: bool = False,
    ) -> None:
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=timeout_connect, read=timeout_read, write=10.0, pool=5.0
            ),
            headers={"User-Agent": user_agent},
            follow_redirects=follow_redirects,
        )

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *args: object) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        return self._request("GET", url, headers=headers, params=params)

    def post(
        self,
        url: str,
        *,
        data: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """`data` form-encodes (France Travail OAuth2), `json` sends a JSON body (Jooble)."""
        kwargs: dict[str, object] = {"headers": headers, "params": params}
        if json is not None:
            kwargs["json"] = json
        else:
            kwargs["data"] = data
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: object) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
            except httpx.TimeoutException:
                if attempt == self._max_retries:
                    raise
                wait = min(2**attempt, 60)
                logger.warning(
                    "timeout on attempt %d/%d, retrying in %.1fs",
                    attempt + 1,
                    self._max_retries + 1,
                    wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code == 429:
                if attempt == self._max_retries:
                    resp.raise_for_status()
                wait = _retry_after(resp, attempt)
                logger.warning(
                    "rate limited on attempt %d/%d, waiting %.1fs",
                    attempt + 1,
                    self._max_retries + 1,
                    wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                if attempt == self._max_retries:
                    resp.raise_for_status()
                wait = min(2**attempt, 60)
                logger.warning(
                    "server error %d on attempt %d/%d, retrying in %.1fs",
                    resp.status_code,
                    attempt + 1,
                    self._max_retries + 1,
                    wait,
                )
                time.sleep(wait)
                continue

            return resp

        raise RuntimeError("retry loop exhausted without returning")  # pragma: no cover
