"""Bounded JSON HTTP transport. Callers own retries and response-shape checks."""
from __future__ import annotations

from functools import lru_cache
from http.client import HTTPException
import json
import math
import re
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from weather.paths import REPO_ROOT


class JsonRequestError(RuntimeError):
    """A transport, status, size or decoding failure with bounded diagnostics."""

    def __init__(self, reason: str, *, status: int | None, body: bytes = b""):
        self.status = status
        self.body_preview = body.decode("utf-8", errors="replace")[:200]
        super().__init__(f"{reason}; status={status}; body={self.body_preview}")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect())


@lru_cache(maxsize=1)
def _short_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short=9", "HEAD"],
            capture_output=True, text=True, check=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = result.stdout.strip()
        if re.fullmatch(r"[0-9a-f]{7,40}", value):
            return value
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def user_agent(component: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]+", component):
        raise ValueError("component must be a lowercase HTTP token")
    return f"weather/{component}/{_short_commit()}"


def json_request(url, *, method, body=None, timeout, max_bytes, headers=None):
    """Make exactly one request; require HTTP 200, bounded UTF-8 JSON.

    ``body`` is a JSON-serializable value. Redirects are failures, not extra
    requests. No retry or consumer-specific shape validation is performed.
    """
    if isinstance(timeout, bool) or not math.isfinite(float(timeout)) or not 0 < float(timeout) <= 60:
        raise ValueError("timeout must be finite and in (0, 60]")
    if type(max_bytes) is not int or not 1 <= max_bytes <= 32 * 1024 * 1024:
        raise ValueError("max_bytes must be an integer in [1, 33554432]")
    outgoing = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    agent = outgoing.get("user-agent", user_agent("json"))
    if not re.fullmatch(r"weather/[a-z0-9-]+/(?:[0-9a-f]{7,40}|unknown)", agent):
        raise ValueError("User-Agent must come from weather.http.user_agent")
    outgoing["user-agent"] = agent
    outgoing["accept"] = "application/json"
    data = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
    if data is not None:
        outgoing["content-type"] = "application/json"
    request = Request(url, method=method, data=data, headers=outgoing)
    try:
        response = _OPENER.open(request, timeout=float(timeout))
    except HTTPError as exc:
        try:
            preview = exc.read(min(max_bytes + 1, 800))
        except (OSError, HTTPException) as read_error:
            preview = getattr(read_error, "partial", b"")
        finally:
            exc.close()
        raise JsonRequestError("HTTP failure", status=exc.code, body=preview) from exc
    except (URLError, OSError, HTTPException) as exc:
        raise JsonRequestError("transport failure", status=None) from exc
    status = None
    try:
        with response:
            status = response.status
            raw = response.read(max_bytes + 1)
    except (OSError, URLError, HTTPException) as exc:
        raise JsonRequestError("response read failure", status=status,
                               body=getattr(exc, "partial", b"")) from exc
    if status != 200:
        raise JsonRequestError("HTTP failure", status=status, body=raw)
    if len(raw) > max_bytes:
        raise JsonRequestError("response too large", status=status, body=raw)
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonRequestError("invalid JSON", status=status, body=raw) from exc
