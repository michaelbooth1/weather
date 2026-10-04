"""Classification tables for snapshot source status, degradation and age (test-suite review K, role 19, A06).

These helpers label every captured source row, and the labels feed the training feature
``source_status_group``. The helpers read only their arguments, so the store is built without I/O.
"""
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from weather.collection.snapshot_store import SnapshotStore


@pytest.fixture
def store():
    return SnapshotStore.__new__(SnapshotStore)


@pytest.mark.parametrize("item,expected", [
    ({"ok": True}, "fresh"),
    ({"ok": True, "stale": True}, "stale_cache"),
    ({"ok": False, "http_status": 429}, "rate_limited"),
    ({"ok": False, "http_status": 503}, "failed"),
    ({"ok": False}, "failed"),
    ({"ok": True, "status": "fresh_cache"}, "fresh_cache"),
])
def test_source_status_table(store, item, expected):
    assert store.source_status(item) == expected


@pytest.mark.parametrize("status,item,expected", [
    ("odd_status", {"ok": False}, "failed"),
    ("stale_cache", {"ok": True}, "stale_fallback"),
    ("failed", {"ok": False, "degradation_state": "settlement_source_auth_failure"}, "settlement_source_auth_failure"),
    ("rate_limited_cache", {"ok": True}, "rate_limited_fallback"),
    ("rate_limited", {"ok": False}, "rate_limited"),
    ("fresh", {"ok": True}, "healthy"),
])
def test_source_degradation_state_table(store, status, item, expected):
    assert store.source_degradation_state(status, item) == expected


@pytest.mark.parametrize("fetched_at,expected", [
    (None, None),
    ("2026-06-13T12:35:00Z", 0.0),  # fetched after capture: clamped at zero, never negative
    ("2026-06-13T12:00:00Z", 30.0),
    ("2026-06-13T08:00:00", 30.0),  # naive means market-local (Toronto, EDT = UTC-4)
])
def test_source_age_minutes_table(store, fetched_at, expected):
    captured_at = datetime(2026, 6, 13, 12, 30, tzinfo=timezone.utc)
    client = SimpleNamespace(spec=SimpleNamespace(tz=ZoneInfo("America/Toronto")))
    assert store.source_age_minutes(fetched_at, captured_at, client) == expected
