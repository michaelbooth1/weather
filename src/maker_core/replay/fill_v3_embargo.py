"""Date embargo for every dated read of the fill model v3 and its reconciliation (item 330 build 1).

Two windows, both UTC calendar days and both refused in code with no override parameter, environment variable
or flag:

- **Reserved window** 2026-09-30..2026-10-15 (``docs/operations/reserved-confirmation-window.md``; the unread
  replay-v2 panel and its settlement-only dates; the LFC agent read clearance). Every read is refused,
  descriptive or scored.
- **Shadow/panel scoring embargo** through 2026-11-13 (the maker shadow panel's desk-study end). A *scored* read
  of any day 2026-09-30..2026-11-13 is refused. A descriptive read of a day after the reserved window is allowed
  here; both descriptive readers add the LFC panel-exclusion rule on top for local quote dates
  ``PANEL_FIRST..PANEL_LAST`` (``fill_v3_reconcile.admit`` for journaled legs, ``fill_v3.check_panel`` for
  ``EngineV3`` plans): such a band-day is read only when an LFC ``panel_exclusions.jsonl`` lists it.

A scored v3 read additionally needs a signed registration
(``docs/research/maker-fill-v3-replay-registration-DRAFT-2026-10-16.md``). ``SIGNED_REGISTRATION_SHA256`` stays
``None`` until the owner signs and a reviewed code change sets it, so every scored read is refused today.

A ``datetime`` is converted to its UTC date (a naive one is refused); a local date is checked as given, so a
caller that knows a band's local quote date checks that date as well as the UTC instants.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

RESERVED_FIRST = date(2026, 9, 30)
RESERVED_LAST = date(2026, 10, 15)
SCORED_EMBARGO_LAST = date(2026, 11, 13)
PANEL_FIRST = RESERVED_LAST + timedelta(days=1)  # the shadow/panel window of local quote dates
PANEL_LAST = SCORED_EMBARGO_LAST
PURPOSES = ("descriptive", "scored")
SIGNED_REGISTRATION_SHA256: str | None = None

REFUSAL_CODES = (
    "v3_embargo_day_required",
    "v3_embargo_naive_instant",
    "v3_embargo_unknown_purpose",
    "v3_reserved_window_refused",
    "v3_scored_embargo_refused",
    "v3_scored_requires_signed_registration",
)


class EmbargoRefused(ValueError):
    """A dated read touched an embargoed day; ``code`` is one of ``REFUSAL_CODES``."""

    def __init__(self, code, day=None):
        super().__init__(code if day is None else f"{code}: {day.isoformat()}")
        self.code, self.day = code, day


def as_day(value) -> date:
    """The UTC calendar date of ``value``: a ``date``, a tz-aware ``datetime`` or a canonical ISO string."""
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise EmbargoRefused("v3_embargo_naive_instant")
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        instant = None
        try:
            if len(value) == 10:
                parsed = date.fromisoformat(value)
                if parsed.isoformat() == value:
                    return parsed
            elif len(value) > 10 and value[10] in "T " and date.fromisoformat(value[:10]).isoformat() == value[:10]:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            instant = None
        if instant is not None:
            return as_day(instant)
    raise EmbargoRefused("v3_embargo_day_required")


def reason(value, purpose) -> str | None:
    """The refusal code for reading ``value`` for ``purpose``, or None when the read is allowed."""
    if purpose not in PURPOSES:
        return "v3_embargo_unknown_purpose"
    day = as_day(value)
    if RESERVED_FIRST <= day <= RESERVED_LAST:
        return "v3_reserved_window_refused"
    if purpose == "scored":
        if RESERVED_FIRST <= day <= SCORED_EMBARGO_LAST:
            return "v3_scored_embargo_refused"
        if SIGNED_REGISTRATION_SHA256 is None:
            return "v3_scored_requires_signed_registration"
    return None


def check(value, purpose) -> date:
    """Return the UTC day of ``value`` when it may be read for ``purpose``; otherwise raise ``EmbargoRefused``."""
    if purpose not in PURPOSES:
        raise EmbargoRefused("v3_embargo_unknown_purpose")
    code = reason(value, purpose)
    if code is not None:
        raise EmbargoRefused(code, as_day(value))
    return as_day(value)


def check_all(values, purpose) -> tuple:
    """``check`` every value (instants, dates or strings); the first refusal raises."""
    return tuple(check(v, purpose) for v in values)


def local_dates(start: datetime, end: datetime, zone) -> tuple:
    """ISO local dates in ``zone`` from ``start`` through ``end`` (both tz-aware instants), inclusive."""
    first, last = start.astimezone(zone).date(), end.astimezone(zone).date()
    return tuple((first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1))


def window_days(first: date, last: date):
    return tuple(first + timedelta(days=n) for n in range((last - first).days + 1))
