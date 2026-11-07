"""HTTP GET with retries, backoff, and conditional requests.

Error text never includes the query string, so a NASA API key in the URL
cannot land in a log or a raised message.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

USER_AGENT = "LaunchPad/0.1 (satellite-anomaly-dashboard)"
# These statuses are usually temporary. Other 4xx responses are not retried.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

Opener = Callable[[str, dict[str, str], float], tuple[int, object, bytes]]


@dataclass(frozen=True)
class Conditional:
    """Validators from the last good response. Both are optional."""

    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class HttpResult:
    status: int
    body: bytes
    etag: str | None
    last_modified: str | None
    not_modified: bool


class HttpFailed(Exception):
    """The URL could not be fetched. `reason` is a short code, not a URL."""


class HttpClient:
    def __init__(
        self,
        *,
        attempts: int = 3,
        timeout: float = 20.0,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
        opener: Opener | None = None,
    ) -> None:
        self.attempts = attempts
        self.timeout = timeout
        self.sleep = sleep
        self.rng = rng
        self.opener = opener or _urlopen

    def fetch(self, url: str, conditional: Conditional | None = None) -> HttpResult:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain",
        }
        if conditional and conditional.etag:
            headers["If-None-Match"] = _quote_etag(conditional.etag)
        if conditional and conditional.last_modified:
            headers["If-Modified-Since"] = conditional.last_modified

        last_reason = "unreachable"
        for attempt in range(1, self.attempts + 1):
            try:
                status, response_headers, body = self.opener(url, headers, self.timeout)
            except TimeoutError:
                last_reason = "timeout"
                self._pause_before_retry(attempt)
                continue
            except OSError:
                last_reason = "network"
                self._pause_before_retry(attempt)
                continue

            if status == 304:
                return HttpResult(
                    status=304,
                    body=b"",
                    etag=_header(response_headers, "ETag") or (conditional.etag if conditional else None),
                    last_modified=_header(response_headers, "Last-Modified")
                    or (conditional.last_modified if conditional else None),
                    not_modified=True,
                )
            if status in RETRY_STATUSES:
                last_reason = f"status_{status}"
                self._pause_before_retry(attempt)
                continue
            if status >= 400:
                # A bad key or a missing catalog number will not start working
                # if we call again immediately.
                raise HttpFailed(f"status_{status}")
            return HttpResult(
                status=status,
                body=body,
                etag=_header(response_headers, "ETag"),
                last_modified=_header(response_headers, "Last-Modified"),
                not_modified=False,
            )

        raise HttpFailed(last_reason)

    def _pause_before_retry(self, attempt: int) -> None:
        if attempt >= self.attempts:
            return
        # 0.5s, 1s, 2s, ... capped at 8s, plus a little jitter.
        base = min(8.0, 0.5 * (2 ** (attempt - 1)))
        self.sleep(base + (self.rng() * 0.25))


def _quote_etag(etag: str) -> str:
    if etag.startswith("W/") or etag.startswith('"'):
        return etag
    return f'"{etag}"'


def _header(headers: object, name: str) -> str | None:
    getter = getattr(headers, "get", None)
    if getter is None:
        return None
    value = getter(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _urlopen(url: str, headers: dict[str, str], timeout: float) -> tuple[int, object, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        # urllib raises for every status >= 400, including 304.
        return exc.code, exc.headers, exc.read()
    except urllib.error.URLError as exc:
        # Drop the URL. The caller only needs to know the attempt failed.
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError("timeout") from exc
        raise OSError("network") from exc


def host_of(url: str) -> str:
    """Host only, for logs. The query string may contain the NASA key."""

    return urlparse(url).netloc
