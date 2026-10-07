"""Registered panel constants for maker replay v2 (registration draft §2, §4; owner decisions 14 and 15).

Plain literals, so any module (the export gate, the universe rule, the manifest) can import them without
importing code that reads data. Nothing here is a parameter: ``intervals.active_intervals`` and the
manifest resolve a panel name (``"registered"`` or ``"calibration"``) to these constants and accept no
other value, so a caller cannot redefine the dates, the maintenance hours or the owner exclusions.

- ``QUOTE_DATES``: the fourteen quote-panel UTC dates, 2026-09-30..2026-10-13.
- ``SETTLEMENT_ONLY_DATES``: 2026-10-14 and 2026-10-15 (change C9). No active interval, no date cluster;
  their settlements are consumed.
- ``GATED_DAYS``: every panel date, quote plus settlement-only (2026-09-30..2026-10-15, 16 days). No
  data of these dates may be exported or read before the registration is signed (reg §2, decision 3).
  The gate itself lives in the export-gate module; this is only the date set.
- ``LAST_TARGET_DATE``: a condition whose local target date is later is ``TARGET_AFTER_PANEL``.
- ``CALIBRATION_DATES``: 2026-09-27..29, equal to ``maker_core.replay.calibration.CALIBRATION_DATES``
  (pinned by test).
- ``MAINTENANCE_UTC``: the minutes [05:00, 08:00) UTC of every date are inactive.
- ``OWNER_EXCLUSIONS``: owner-excluded market-dates. Each row carries two independent keys: the
  inventory key ``(market_id, target_date)`` and the descriptor key ``close_at_utc`` (the local midnight
  that ends the target date: Austin is America/Chicago, CDT = UTC-5, so target 2026-10-03 closes at
  2026-10-04T05:00Z). Both must select the same conditions (A-defender M4).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import NamedTuple

QUOTE_DATES = tuple(date(2026, 9, 30) + timedelta(days=i) for i in range(14))
SETTLEMENT_ONLY_DATES = (date(2026, 10, 14), date(2026, 10, 15))
GATED_DAYS = QUOTE_DATES + SETTLEMENT_ONLY_DATES
GATED_FIRST, GATED_LAST = GATED_DAYS[0], GATED_DAYS[-1]
LAST_TARGET_DATE = date(2026, 10, 14)
CALIBRATION_DATES = (date(2026, 9, 27), date(2026, 9, 28), date(2026, 9, 29))
MAINTENANCE_UTC = (time(5, 0), time(8, 0))


class OwnerExclusion(NamedTuple):
    market_id: str
    target_date: date
    close_at_utc: datetime
    reason: str
    source: str


OWNER_EXCLUSIONS = (
    OwnerExclusion("austin", date(2026, 10, 3), datetime(2026, 10, 4, 5, 0, tzinfo=timezone.utc),
                   "OWNER_EXCLUDED_PRIOR_READ", "DECISION_LOG 2026-10-05"),
)

# Panel names accepted by the universe rule; each resolves to the constants above.
PANELS = ("registered", "calibration")
