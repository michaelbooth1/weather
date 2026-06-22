"""Source-adapter orchestration primitives."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


FETCH_META_KEY = "_source_fetch_meta"


class SourceProviderRateLimited(RuntimeError):
    """Raised when a shared provider cooldown blocks a live source fetch."""

    def __init__(
        self,
        message,
        *,
        source_family=None,
        retry_after_seconds=None,
        http_status=429,
        cache_status="provider_cooldown",
    ):
        super().__init__(message)
        self.status = "rate_limited"
        self.source_family = source_family
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status
        self.degradation_state = "rate_limited"
        self.cache_status = cache_status


class SourceExpectedUnavailable(RuntimeError):
    """Raised when a source is expected to be unavailable for the target context."""

    def __init__(
        self,
        message,
        *,
        status="expected_unavailable",
        source_family=None,
        http_status=None,
        degradation_state="expected_unavailable",
        cache_status="expected_unavailable",
        fallback_source=None,
    ):
        super().__init__(message)
        self.status = status
        self.source_family = source_family
        self.http_status = http_status
        self.degradation_state = degradation_state
        self.cache_status = cache_status
        self.fallback_source = fallback_source


@dataclass(frozen=True)
class SourceAdapter:
    name: str
    fetch: object


def retry_after_seconds(response):
    if response is None:
        return None
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value in (None, ""):
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())


def source_fetch_metadata(data):
    if not isinstance(data, dict):
        return data, {}
    metadata = data.get(FETCH_META_KEY)
    if not isinstance(metadata, dict):
        return data, {}
    cleaned = dict(data)
    cleaned.pop(FETCH_META_KEY, None)
    return cleaned, dict(metadata)


def source_exception_metadata(exc):
    metadata = {}
    for key in (
        "status",
        "source_family",
        "http_status",
        "retry_after_seconds",
        "degradation_state",
        "cache_status",
        "fallback_source",
    ):
        value = getattr(exc, key, None)
        if value not in (None, ""):
            metadata[key] = value
    response = getattr(exc, "response", None)
    http_status = getattr(response, "status_code", None)
    if http_status is not None:
        metadata["http_status"] = http_status
    retry_after = retry_after_seconds(response)
    if retry_after is not None:
        metadata["retry_after_seconds"] = retry_after
    if metadata.get("http_status") == 429:
        metadata.setdefault("status", "rate_limited")
        metadata.setdefault("degradation_state", "rate_limited")
    return metadata


def fetch_source(name, fetcher, *, fetched_at, clock=time.perf_counter):
    started = clock()
    try:
        data, metadata = source_fetch_metadata(fetcher())
        payload = {
            "ok": True,
            "data": data,
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": fetched_at,
        }
        payload.update(metadata)
        return name, {
            **payload,
        }
    except Exception as exc:  # noqa: BLE001 - source failures are surfaced as data
        payload = {
            "ok": False,
            "error": str(exc),
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": fetched_at,
        }
        payload.update(source_exception_metadata(exc))
        return name, payload


def fetch_source_group(fetchers, *, timezone, now_fn=None, max_workers=None):
    fetchers = dict(fetchers or {})
    if not fetchers:
        return {}
    now_fn = now_fn or (lambda: datetime.now(timezone))
    fetched_at = now_fn().isoformat()
    results = {}
    workers = max_workers or len(fetchers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_source, name, fetcher, fetched_at=fetched_at): name
            for name, fetcher in fetchers.items()
        }
        for future in as_completed(futures):
            name, payload = future.result()
            results[name] = payload
    return results
