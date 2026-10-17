"""Date embargo for every dated read in the frontier package (item 330 build 3).

Every entry point that reads dated evidence calls :func:`check` before it reads a value. Three windows:

- ``RESERVED`` (2026-09-30..2026-10-15) is the reserved confirmation window. It is refused for every
  purpose, fit, descriptive and scored alike.
- A ``fit`` may only use dates on or before ``FIT_LAST`` (2026-09-29). Anything later is refused, so a fitted
  parameter never sees a day that a later read could score.
- ``descriptive`` and ``scored`` reads are refused through the shadow embargo, ``SHADOW_EMBARGO``
  (2026-09-30..2026-11-13). A scored read also needs a signed preregistration (``prereg.verify``). This
  module only owns the dates.

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


def check(purpose: str, *values) -> None:
    """Refuse when any value's UTC day is embargoed for ``purpose``; return None otherwise."""
    if purpose not in PURPOSES:
        raise EmbargoRefused("unknown_purpose")
    if not values:
        raise EmbargoRefused("undated_read")
    for value in values:
        day = utc_day(value)
        if RESERVED[0] <= day <= RESERVED[1]:
            raise EmbargoRefused("reserved_window")
        if purpose == "fit" and day > FIT_LAST:
            raise EmbargoRefused("fit_after_cutoff")
        if purpose != "fit" and SHADOW_EMBARGO[0] <= day <= SHADOW_EMBARGO[1]:
            raise EmbargoRefused("shadow_embargo")
