"""Bounded HTTP for evidence families: free public endpoints only, one connection at a time.

Every request is counted against the family's hourly request budget and its bytes recorded in
telemetry. A response larger than ``max_bytes`` is refused rather than buffered. HTTP errors come
back as a :class:`Response` (the family writes a gap row); network failures raise
:class:`FetchError`.
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_BYTES = 8 * 1024**2


class FetchError(OSError):
    pass


class RequestBudgetExceeded(RuntimeError):
    pass


@dataclass
class Response:
    url: str
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)


def urllib_transport(url, headers, timeout, max_bytes) -> Response:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:  # noqa: S310 - fixed https hosts
            body = reply.read(max_bytes + 1)
            return Response(url, int(reply.status), body, {k.lower(): v for k, v in reply.headers.items()})
    except urllib.error.HTTPError as exc:
        return Response(url, int(exc.code), b"", {k.lower(): v for k, v in (exc.headers or {}).items()})
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from None


class Fetcher:
    def __init__(self, *, user_agent, request_budget_per_hour, telemetry=None, transport=urllib_transport,
                 clock=time.time, timeout=DEFAULT_TIMEOUT_SECONDS, max_bytes=DEFAULT_MAX_BYTES):
        self.user_agent = user_agent
        self.budget = int(request_budget_per_hour)
        self.telemetry = telemetry
        self.transport = transport
        self.clock = clock
        self.timeout, self.max_bytes = timeout, max_bytes
        self.hour_key, self.hour_count = None, 0

    def get(self, url, *, headers=None, max_bytes=None) -> Response:
        if not str(url).startswith("https://"):
            raise ValueError("evidence fetches use https only")
        hour = int(self.clock() // 3600)
        if hour != self.hour_key:
            self.hour_key, self.hour_count = hour, 0
        if self.hour_count >= self.budget:
            raise RequestBudgetExceeded(f"{self.budget} requests this hour")
        self.hour_count += 1
        limit = int(max_bytes or self.max_bytes)
        try:
            response = self.transport(url, {"User-Agent": self.user_agent, **(headers or {})}, self.timeout, limit)
        except FetchError:
            if self.telemetry is not None:
                self.telemetry.request(0, error=True)
            raise
        if len(response.body) > limit:
            if self.telemetry is not None:
                self.telemetry.request(len(response.body), error=True, status=response.status)
            raise FetchError(f"response over {limit} bytes")
        if self.telemetry is not None:
            self.telemetry.request(len(response.body), error=response.status >= 400, status=response.status)
        return response
