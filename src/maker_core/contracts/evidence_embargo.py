"""Evidence embargo for counterfactual toxicity work, enforced in code.

Additive contracts module (no existing module imports it). It holds dates only:
no IO, no prices, no domain logic. Every dated entry point of the toxicity
build calls :func:`refuse` before it reads, fits on or scores a record.

Windows (owner instructions for item 330 build 2, 2026-10-16):

- ``EXAM_EMBARGO``: 2026-09-30..2026-10-15 inclusive. The maker replay v2 exam
  panel (09-30..10-13), its settlement (10-14) and the 10-15 read. No purpose may
  read a record dated inside it.
- ``FIT_LAST_DATE``: 2026-09-29. A fit refuses any record dated after it.
- ``SCORED_PANEL``: 2026-09-30..2026-11-13 inclusive. The desk-study decision
  panel's embargo end is 11-13; a scored read of a date inside it is refused.

A record may carry several dates (event date, fill clock, mark clocks); callers
pass every one of them. Dates are compared as calendar dates. An aware
``datetime`` (or ISO string with an offset) is converted to UTC and reduced to
its UTC date; a naive one cannot be placed on the calendar and is refused
(:class:`EmbargoRefused`), as is ``None``: an undated value is never admitted.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

EXAM_EMBARGO = (date(2026, 9, 30), date(2026, 10, 15))
FIT_LAST_DATE = date(2026, 9, 29)
SCORED_PANEL = (date(2026, 9, 30), date(2026, 11, 13))
PURPOSES = ("read", "fit", "scored")


class EmbargoRefused(ValueError):
    """A dated read, fit or scored read touched an embargoed date."""


def as_date(value) -> date:
    if value is None:
        raise EmbargoRefused("EMBARGO_UNDATED:None")
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise EmbargoRefused(f"EMBARGO_NAIVE_DATETIME:{value.isoformat()}")
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return as_date(parsed)
    raise TypeError("a date, UTC datetime or ISO string is required")


def refusal(value, purpose: str) -> str | None:
    """Return the refusal code for one date and purpose, or None if allowed."""
    if purpose not in PURPOSES:
        raise ValueError("unknown embargo purpose")
    day = as_date(value)
    if EXAM_EMBARGO[0] <= day <= EXAM_EMBARGO[1]:
        return f"EMBARGO_EXAM_WINDOW:{day.isoformat()}"
    if purpose == "fit" and day > FIT_LAST_DATE:
        return f"EMBARGO_FIT_AFTER_{FIT_LAST_DATE.isoformat()}:{day.isoformat()}"
    if purpose == "scored" and SCORED_PANEL[0] <= day <= SCORED_PANEL[1]:
        return f"EMBARGO_SCORED_PANEL:{day.isoformat()}"
    return None


def refuse(*values, purpose: str) -> None:
    """Raise :class:`EmbargoRefused` if any supplied date is embargoed for ``purpose``."""
    if purpose not in PURPOSES:
        raise ValueError("unknown embargo purpose")
    for value in values:
        code = refusal(value, purpose)
        if code:
            raise EmbargoRefused(code)
