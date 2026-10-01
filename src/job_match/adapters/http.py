import logging
import time

import httpx

logger = logging.getLogger(__name__)


def _retry_after(resp: httpx.Response, attempt: int) -> float:
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return min(2**attempt, 60)


class HttpClient:
    def __init__(
        self,
        timeout_connect: float = 5.0,
        timeout_read: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._max_retries = max_retries
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=timeout_connect, read=timeout_read, write=10.0, pool=5.0
            )
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
        headers: dict | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        return self._request("POST", url, headers=headers, data=data, params=params)

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
