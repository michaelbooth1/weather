"""Date embargo for every dated read in the frontier package (item 330 build 3).

Every entry point that reads dated evidence calls :func:`check` before it reads a value. Three windows:

- ``RESERVED`` (2026-09-30..2026-10-15) is the reserved confirmation window. It is refused for every
  purpose, fit, descriptive and scored alike.
- A ``fit`` may only use dates on or before ``FIT_LAST`` (2026-09-29). Anything later is refused, so a fitted
  parameter never sees a day that a later read could score.
- ``descriptive`` and ``scored`` reads are refused through the shadow embargo, ``SHADOW_EMBARGO``
  (2026-09-30..2026-11-13). A scored read also needs a signed preregistration (``prereg.verify``). This
  module only owns the dates.

The scored panel ``SCORED_PANEL`` (2026-10-17..2026-11-13) is the one exception to the shadow embargo, and
only for ``scored``: it opens when the caller passes an aware ``now`` at or after ``SCORED_OPENS_AT``
(2026-11-14T00:00Z), i.e. after the panel has closed. With no ``now`` (every earlier caller) nothing changes.
The frontier CLI passes the real UTC clock; tests inject one. The reserved window never opens.

Days are UTC calendar dates. A UTC instant is checked on its UTC date, so a market whose local day is
2026-09-29 but which closes on 2026-09-30 UTC is refused. The rule is conservative on purpose. A naive
datetime is refused, as is any value that is not a date, a datetime or an ISO date string.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

RESERVED = (date(2026, 9, 30), date(2026, 10, 15))
FIT_LAST = date(2026, 9, 29)
SHADOW_EMBARGO = (date(2026, 9, 30), date(2026, 11, 13))
PURPOSES = ("fit", "descriptive", "scored")
# 10-17, not 10-16: a 10-16 bundle holds bands closing inside the reserved window, which would refuse the whole
# scored run (score never drops bands). Owner/master decision, round 3.
SCORED_PANEL = (date(2026, 10, 17), date(2026, 11, 13))
SCORED_OPENS_AT = datetime(2026, 11, 14, tzinfo=timezone.utc)


class EmbargoRefused(ValueError):
    """A dated read touched a day its purpose may not see."""


def utc_day(value) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise EmbargoRefused("naive_datetime")
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise EmbargoRefused("unparseable_date") from exc
        if len(value) == 10:
            return parsed.date()
        return utc_day(parsed)
    raise EmbargoRefused("undated_value")


def scored_panel_open(now) -> bool:
    """True when ``now`` (an aware instant) is at or after ``SCORED_OPENS_AT``; a naive ``now`` is refused."""
    if now is None:
        return False
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise EmbargoRefused("naive_or_undated_clock")
    return now >= SCORED_OPENS_AT


def check(purpose: str, *values, now=None) -> None:
    """Refuse when any value's UTC day is embargoed for ``purpose``; return None otherwise."""
    if purpose not in PURPOSES:
        raise EmbargoRefused("unknown_purpose")
    if not values:
        raise EmbargoRefused("undated_read")
    panel_open = purpose == "scored" and scored_panel_open(now)
    for value in values:
        day = utc_day(value)
        if RESERVED[0] <= day <= RESERVED[1]:
            raise EmbargoRefused("reserved_window")
        if purpose == "fit" and day > FIT_LAST:
            raise EmbargoRefused("fit_after_cutoff")
        if purpose != "fit" and SHADOW_EMBARGO[0] <= day <= SHADOW_EMBARGO[1]:
            if panel_open and SCORED_PANEL[0] <= day <= SCORED_PANEL[1]:
                continue
            raise EmbargoRefused("shadow_embargo")
