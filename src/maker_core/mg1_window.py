"""MG-1 reserved window: the single recorded copy, shared by core and plugin callers.

``docs/operations/reserved-confirmation-window.md`` (MG-1, signed 2026-10-04)
reserves the first 45 promotion-countable local target dates on or after D0
(D0 >= 2026-10-15, not yet dated). ``weather.market.mg1_metric_guard`` refuses
view-vs-outcome metrics on these dates; this module owns the window itself and
the paper-scoring side, because ``maker_core`` may not import ``weather``.

The window narrows only by a reviewed edit of ``MG1_D0`` and ``MG1_LAST``
(both must be recorded; an inconsistent recording fails wide). There is no
override argument and no environment variable.

OD3 (owner decision pending): ``MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT`` is
the one switch for the requested exemption of quoting and MM paper scoring.
True keeps paper fill settlement and P&L working on reserved dates; False makes
every paper-scoring entry point refuse any fill or settlement dated inside the
window. A "no" from the owner is a one-line change here.
"""
from __future__ import annotations

from datetime import date, datetime


MG1_FLOOR = date(2026, 10, 15)
# Recorded only from reserved-confirmation-window.md once D0 is dated and the
# 45 promotion-countable dates are computed. Both None: open-ended from the floor.
MG1_D0: date | None = None
MG1_LAST: date | None = None
MG1_RESERVED_COUNT = 45
# OD3 is NOT yet approved by the owner; see the module docstring.
MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT = True


class MG1Reserved(ValueError):
    """A use of an MG-1 reserved date that its current exemption does not cover."""


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


def as_date(value):
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
    day = as_date(target)
    return start <= day and (end is None or day <= end)


def refuse_paper_scoring(days, *, entry: str) -> None:
    """Paper-scoring guard: a no-op while OD3 exempts paper scoring; otherwise refuse reserved days.

    ``days`` are the UTC dates of every fill and settlement fact the scorer may
    join. Core has no local target date, so both are checked conservatively.
    """
    if MG1_OD3_QUOTING_AND_PAPER_SCORING_EXEMPT is True:
        return
    for day in days:
        if is_reserved(day):
            raise MG1Reserved(f"mg1_reserved_paper_scoring:{entry}:{as_date(day).isoformat()}")
