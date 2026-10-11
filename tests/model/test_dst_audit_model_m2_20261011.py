"""DST tests for the last-good source cache age (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md finding DST-M2 (``cache_age_minutes``
subtracted two datetimes that share ``spec.tz``, i.e. on the wall clock).

The transition cases were ``xfail(strict=True, raises=AssertionError)`` while the defect was on
master; branch ``claude/dst-m2-cache-age-utc-20261011`` retired the marker (held for the owner:
the age also reaches the ``source_*_age_minutes`` features of the live
``pooled_f_dynamic_source_state_v0_1`` shadow variant, because ``pooled_feature_source_state.
source_age_minutes`` reads ``cache_age_minutes`` first). The ordinary-day controls pin that the
fix returns byte-identical ages to the former wall-clock formula whenever no transition lies
between the fetch and the read. No network: the clock is frozen and no fetch is made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import weather.model.model_sources as model_sources

TORONTO = ZoneInfo("America/Toronto")
ZONES = tuple(
    ZoneInfo(name)
    for name in ("America/Toronto", "America/New_York", "America/Chicago", "Europe/London", "Asia/Seoul")
)


def _freeze(monkeypatch, now_local):
    now_utc = now_local.astimezone(timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz is not None else now_utc.replace(tzinfo=None)

    monkeypatch.setattr(model_sources, "datetime", _Frozen)


def _cache_age(monkeypatch, fetched_local, now_local, tz=TORONTO, fetched_at=None):
    _freeze(monkeypatch, now_local)
    client = SimpleNamespace(spec=SimpleNamespace(tz=tz))
    # ``fetched_at`` is written as ``datetime.now(spec.tz).isoformat()``.
    if fetched_at is None:
        fetched_at = fetched_local.isoformat()
    return model_sources.SourceFetchMixin.cache_age_minutes(client, fetched_at)


def _former_wall_clock_age(fetched_at, now_local, tz):
    """The pre-fix formula, kept only as the ordinary-day reference."""
    parsed = datetime.fromisoformat(str(fetched_at))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return max(0.0, (now_local.astimezone(tz) - parsed.astimezone(tz)).total_seconds() / 60.0)


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


@pytest.mark.parametrize(
    ("fetched", "now", "age"),
    [
        # A stale cache fetched the evening before is read after fall-back: 5 real hours (defect: 4).
        (datetime(2026, 10, 31, 23, 0, tzinfo=TORONTO), datetime(2026, 11, 1, 3, 0, tzinfo=TORONTO), 300.0),
        # Spring-forward, long span: 23:00 EST -> 04:00 EDT is 4 real hours (defect: 5).
        (datetime(2027, 3, 13, 23, 0, tzinfo=TORONTO), datetime(2027, 3, 14, 4, 0, tzinfo=TORONTO), 240.0),
        # Both stamps inside the repeated hour, EDT then EST: 50 real minutes (defect: 0, clamped from -10).
        (datetime(2026, 11, 1, 1, 35, tzinfo=TORONTO), datetime(2026, 11, 1, 1, 25, tzinfo=TORONTO, fold=1), 50.0),
    ],
)
def test_cache_age_spanning_a_transition_is_elapsed_time(monkeypatch, fetched, now, age):
    assert _cache_age(monkeypatch, fetched, now) == pytest.approx(age)


def test_fall_back_ttl_decision_rejects_a_cache_older_than_its_ttl(monkeypatch):
    """The primary model's last-good reuse: a 35-minute-old cache is past a 30-minute TTL."""

    fetched = datetime(2026, 11, 1, 1, 50, tzinfo=TORONTO)
    now = datetime(2026, 11, 1, 1, 25, tzinfo=TORONTO, fold=1)
    _freeze(monkeypatch, now)
    client = SimpleNamespace(
        spec=SimpleNamespace(tz=TORONTO),
        target_date=now.date(),
        load_last_good_sources=lambda: {
            "wu_history": {"target_date": "2026-11-01", "fetched_at": fetched.isoformat(), "data": {"rows": []}}
        },
    )
    client.cache_age_minutes = lambda value: model_sources.SourceFetchMixin.cache_age_minutes(client, value)
    assert model_sources.SourceFetchMixin.cached_source_for_reuse(client, "wu_history", 30) is None
    reused = model_sources.SourceFetchMixin.cached_source_for_reuse(client, "wu_history", 40)
    assert reused is not None and reused["cache_age_minutes"] == pytest.approx(35.0)


def _ordinary_day_cases():
    """Fetch/read pairs in five zones with no UTC-offset change between them."""

    cases = []
    for tz in ZONES:
        for day in (datetime(2026, 1, 15), datetime(2026, 7, 15), datetime(2026, 10, 11), datetime(2027, 2, 2)):
            for fetch_minute in range(0, 24 * 60, 97):
                fetched = (day + timedelta(minutes=fetch_minute, seconds=13, microseconds=250_001)).replace(tzinfo=tz)
                for delta in (timedelta(0), timedelta(seconds=59), timedelta(minutes=35), timedelta(hours=3, minutes=7)):
                    now = (fetched.replace(tzinfo=None) + delta).replace(tzinfo=tz)
                    if fetched.utcoffset() != now.utcoffset():
                        continue
                    cases.append((tz, fetched, now))
    return cases


def test_ordinary_day_ages_are_byte_identical_to_the_former_formula(monkeypatch):
    cases = _ordinary_day_cases()
    assert len(cases) > 500
    for tz, fetched, now in cases:
        for fetched_at in (
            fetched.isoformat(),
            fetched.astimezone(timezone.utc).isoformat(),
            fetched.replace(tzinfo=None).isoformat(),
        ):
            got = _cache_age(monkeypatch, fetched, now, tz=tz, fetched_at=fetched_at)
            want = _former_wall_clock_age(fetched_at, now, tz)
            assert repr(got) == repr(want), (tz, fetched_at, now, got, want)


def test_future_fetch_and_unparseable_stamps_are_unchanged(monkeypatch):
    now = datetime(2026, 7, 15, 12, 0, tzinfo=TORONTO)
    assert _cache_age(monkeypatch, now + timedelta(minutes=5), now) == 0.0
    assert _cache_age(monkeypatch, now, now, fetched_at="not-a-time") is None
    assert _cache_age(monkeypatch, now, now, fetched_at="") is None
