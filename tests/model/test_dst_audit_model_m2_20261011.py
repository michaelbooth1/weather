"""Failing-first DST tests for the last-good source cache age (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md finding DST-M2 (``cache_age_minutes``
subtracts two datetimes that share ``spec.tz``, i.e. on the wall clock).

The transition cases are ``xfail(strict=True, raises=AssertionError)`` while the defect is on
master. The fix is held: the age also reaches the ``source_*_age_minutes`` features of the live
``pooled_f_dynamic_source_state_v0_1`` shadow variant (``pooled_feature_source_state.
source_age_minutes`` reads ``cache_age_minutes`` first), so it needs an owner decision. The
fixing change must remove the marker. No network: the clock is frozen and no fetch is made.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import weather.model.model_sources as model_sources

TORONTO = ZoneInfo("America/Toronto")


def _cache_age(monkeypatch, fetched_local, now_local):
    now_utc = now_local.astimezone(timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz is not None else now_utc.replace(tzinfo=None)

    monkeypatch.setattr(model_sources, "datetime", _Frozen)
    client = SimpleNamespace(spec=SimpleNamespace(tz=TORONTO))
    # ``fetched_at`` is written as ``datetime.now(spec.tz).isoformat()``.
    return model_sources.SourceFetchMixin.cache_age_minutes(client, fetched_local.isoformat())


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-M2")
@pytest.mark.parametrize(
    ("fetched", "now", "age"),
    [
        # Fall-back: fetched 01:50 EDT, read 01:25 EST -> 35 real minutes (defect: 0).
        (datetime(2026, 11, 1, 1, 50, tzinfo=TORONTO), datetime(2026, 11, 1, 1, 25, tzinfo=TORONTO, fold=1), 35.0),
        # Spring-forward: fetched 01:55 EST, read 03:05 EDT -> 10 real minutes (defect: 70).
        (datetime(2027, 3, 14, 1, 55, tzinfo=TORONTO), datetime(2027, 3, 14, 3, 5, tzinfo=TORONTO), 10.0),
    ],
)
def test_cache_age_is_elapsed_time_across_dst(monkeypatch, fetched, now, age):
    assert _cache_age(monkeypatch, fetched, now) == pytest.approx(age)


@pytest.mark.parametrize(
    ("fetched", "now", "age"),
    [
        (datetime(2026, 7, 15, 1, 50, tzinfo=TORONTO), datetime(2026, 7, 15, 2, 25, tzinfo=TORONTO), 35.0),
        (datetime(2026, 1, 15, 1, 55, tzinfo=TORONTO), datetime(2026, 1, 15, 2, 5, tzinfo=TORONTO), 10.0),
    ],
)
def test_cache_age_on_ordinary_days(monkeypatch, fetched, now, age):
    assert _cache_age(monkeypatch, fetched, now) == pytest.approx(age)
