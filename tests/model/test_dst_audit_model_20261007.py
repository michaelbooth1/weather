"""Failing-first DST tests for the model capture path (DST audit 2026-10-07).

Guards: docs/roadmap/audits/dst-audit-2026-10-07.md finding DST-C2 (METAR look-back loses the first
local hour on the 25-hour fall-back day; repair is PR #196).

Each test pins the correct behaviour and is marked
``xfail(strict=True, raises=AssertionError)`` while the defect is on master (a
broken precondition raises ``RuntimeError`` and fails instead). When the repair
lands the test passes, strict xfail turns that into an error, and the marker
must be removed in the fixing change.
No network: the clock is frozen and no fetch is made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import weather.model.model_sources as model_sources
from weather.model.toronto_model import TorontoHighTempModel

# One market per DST zone the model registry serves.
DST_MARKETS = ("toronto", "nyc", "chicago", "denver", "los-angeles")
FALL_BACK_DAY = "2026-11-01"


def _freeze_now(monkeypatch, now_utc):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now_utc.astimezone(tz) if tz is not None else now_utc.replace(tzinfo=None)

    monkeypatch.setattr(model_sources, "datetime", _Frozen)


def _local_midnight_utc(model, day):
    return datetime(day.year, day.month, day.day, tzinfo=model.spec.tz).astimezone(timezone.utc)


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason="DST audit 2026-10-07: DST-C2 (fixed by PR #196)"
)
@pytest.mark.parametrize("market_id", DST_MARKETS)
def test_fall_back_day_late_metar_look_back_reaches_local_midnight(monkeypatch, market_id):
    model = TorontoHighTempModel(target_date=FALL_BACK_DAY, market_id=market_id)
    start_utc = _local_midnight_utc(model, model.target_date)
    end_utc = _local_midnight_utc(model, model.target_date + timedelta(days=1))
    if end_utc - start_utc != timedelta(hours=25):
        raise RuntimeError("precondition: the fall-back local day is 25 hours long")

    now_utc = end_utc - timedelta(minutes=5)  # 23:55 local standard time
    _freeze_now(monkeypatch, now_utc)
    hours = model.metar_query_hours()

    # The AWC window [now - hours, now] must include local 00:00, otherwise the
    # 00:xx SPECI and the 00:51 routine report leave every late fetch's rows.
    assert now_utc - timedelta(hours=hours) <= start_utc, (
        f"{market_id}: hours={hours} starts at "
        f"{(now_utc - timedelta(hours=hours)).astimezone(model.spec.tz).isoformat()}"
    )
