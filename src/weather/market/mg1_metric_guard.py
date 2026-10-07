"""MG-1 metric refusal: no view-vs-outcome metric on reserved target dates.

``docs/operations/reserved-confirmation-window.md`` (MG-1, signed 2026-10-04)
holds out the first 45 promotion-countable local target dates on or after D0
(D0 >= 2026-10-15, not yet dated) against every candidate that reads NBM
station guidance into band probabilities: they may not be scored, have their
outcomes enumerated, or be joined to an outcome. The plugin's lead-1/lead-2
NBP view is such a candidate; its lead-1 fallback is treated the same way,
conservatively, so every plugin fair-value view is covered.

Every entry point that judges a fair-value VIEW against an outcome (Brier,
reliability, PIT, markout-vs-settlement of the view) calls
``refuse_reserved_targets`` as its first statement, before any outcome or
settlement is opened. MM paper scoring of fills, quoting, and outcome-blind
checks (coverage, replay reproduction, parser version) are exempt and never
call it.

There is deliberately no override argument and no environment variable. The
window may only become narrower, and only by editing the two constants below
in a reviewed change whose tests pin the new values: ``MG1_D0`` (the recorded
first eligible date, never before ``MG1_FLOOR``) and ``MG1_LAST`` (the recorded
45th promotion-countable date). Until both are recorded, every target date on
or after ``MG1_FLOOR`` is reserved.
"""
from __future__ import annotations

from datetime import date, datetime


MG1_FLOOR = date(2026, 10, 15)
# Recorded only from reserved-confirmation-window.md once D0 is dated and the
# 45 promotion-countable dates are computed. Both None: open-ended from the floor.
MG1_D0: date | None = None
MG1_LAST: date | None = None
MG1_RESERVED_COUNT = 45


class MG1Reserved(ValueError):
    """A view-vs-outcome metric was requested for an MG-1 reserved target date."""


def window(d0=None, last=None):
    """Return the inclusive reserved range ``(start, end)``; ``end`` None is open-ended.

    Arguments exist only so the narrowing invariant can be tested; callers use
    the recorded constants. An inconsistent recording fails closed to the
    widest window rather than narrowing it.
    """
    d0 = MG1_D0 if d0 is None else d0
    last = MG1_LAST if last is None else last
    if d0 is None or last is None:
        return MG1_FLOOR, None
    if not (isinstance(d0, date) and isinstance(last, date)) or d0 < MG1_FLOOR or last < d0:
        return MG1_FLOOR, None
    return d0, last


def _as_date(value):
    if isinstance(value, datetime):
        raise MG1Reserved("mg1_target_date_unparseable:datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise MG1Reserved(f"mg1_target_date_unparseable:{value!r}"[:120])


def is_reserved(target) -> bool:
    """True when ``target`` (a date or ISO date string) is inside the MG-1 window."""
    start, end = window()
    day = _as_date(target)
    return start <= day and (end is None or day <= end)


def refuse_reserved_targets(targets, *, entry: str) -> None:
    """Raise ``MG1Reserved`` if any target date is reserved or unreadable.

    ``targets`` is every local target date the caller might score. An
    unparseable or missing date is refused: the guard cannot prove it is safe.
    """
    for target in targets:
        if is_reserved(target):
            raise MG1Reserved(f"mg1_reserved_target_date:{entry}:{_as_date(target).isoformat()}")


def date_range(start: date, end: date):
    """Inclusive calendar range, for callers that declare a frozen target panel."""
    return [date.fromordinal(n) for n in range(start.toordinal(), end.toordinal() + 1)]
