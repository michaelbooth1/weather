"""Source-adapter orchestration primitives."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone

from weather.io import http_retry_after_response_seconds


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


class SourceSettlementAuthFailure(RuntimeError):
    """Raised when the canonical settlement source rejects authentication."""

    def __init__(
        self,
        message,
        *,
        source_family="wu_history",
        http_status=None,
    ):
        super().__init__(message)
        self.status = "settlement_source_auth_failure"
        self.source_family = source_family
        self.http_status = http_status
        self.degradation_state = "settlement_source_auth_failure"
        self.cache_status = "auth_failure"
        self.fallback_source = None


@dataclass(frozen=True)
class SourceAdapter:
    name: str
    fetch: object


def retry_after_seconds(response):
    """Compatibility wrapper for the shared Retry-After parser."""
    return http_retry_after_response_seconds(response)


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


def _attempt_timestamp(now_fn=None, fallback=None):
    if now_fn is not None:
        value = now_fn()
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if fallback not in (None, ""):
        return str(fallback)
    return datetime.now(timezone.utc).isoformat()


def fetch_source(
    name,
    fetcher,
    *,
    fetched_at=None,
    now_fn=None,
    clock=time.perf_counter,
):
    request_started_at = _attempt_timestamp(now_fn, fetched_at)
    started = clock()
    try:
        data, metadata = source_fetch_metadata(fetcher())
        response_received_at = _attempt_timestamp(now_fn, fetched_at)
        payload = {
            "ok": True,
            "data": data,
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": response_received_at,
        }
        payload.update(metadata)
        # A fetcher that legitimately reuses an earlier physical response may
        # supply the original attempt boundaries in its private metadata.
        # Ordinary fetchers have no such metadata and retain these wrapper
        # timestamps.
        if payload.get("request_started_at") in (None, ""):
            payload["request_started_at"] = request_started_at
        if payload.get("response_received_at") in (None, ""):
            payload["response_received_at"] = response_received_at
        return name, {
            **payload,
        }
    except Exception as exc:  # noqa: BLE001 - source failures are surfaced as data
        response_received_at = _attempt_timestamp(now_fn, fetched_at)
        payload = {
            "ok": False,
            "error": str(exc),
            "latency_ms": round((clock() - started) * 1000.0, 1),
            "fetched_at": response_received_at,
        }
        payload.update(source_exception_metadata(exc))
        payload["request_started_at"] = request_started_at
        payload["response_received_at"] = response_received_at
        return name, payload


def fetch_source_group(fetchers, *, timezone, now_fn=None, max_workers=None):
    fetchers = dict(fetchers or {})
    if not fetchers:
        return {}
    now_fn = now_fn or (lambda: datetime.now(timezone))
    results = {}
    workers = max_workers or len(fetchers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_source, name, fetcher, now_fn=now_fn): name
            for name, fetcher in fetchers.items()
        }
        for future in as_completed(futures):
            name, payload = future.result()
            results[name] = payload
    return results
