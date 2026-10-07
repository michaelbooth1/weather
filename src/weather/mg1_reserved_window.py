"""MG-1 reserved window: refuse NBM-guidance-to-band scoring on reserved target dates.

``docs/operations/reserved-confirmation-window.md`` (MG-1, signed 2026-10-04)
holds out the first 45 promotion-countable local target dates on or after D0
(D0 >= 2026-10-15, not yet dated) against every candidate that reads NBM
station guidance into band probabilities: such a candidate may not be scored,
have its outcomes enumerated, or be joined to an outcome on those dates. The
item-190 settlement scorer (``nbm_probabilistic_tmax_settlement_scoring``)
reads the NBM percentile curve into band probabilities. Its whole-history
run (``build_payload``) drops reserved target dates with
``drop_reserved_targets`` before any folder is scored or joined to an outcome,
and discloses only the counts dropped (owner decision OD31, 2026-10-07). A
direct single-folder call (``score_folder``) on a reserved date is refused
with ``refuse_nbm_band_scoring``.

Window semantics (identical to ``maker_core.mg1_window`` on the maker-replay
build line, unit U7):
- every target date on or after ``MG1_FLOOR`` is reserved while ``MG1_D0`` and
  ``MG1_LAST`` are None;
- the window narrows only by a reviewed edit recording both constants; an
  inconsistent recording (D0 before the floor, last earlier than D0 + 44 days,
  only one set, a datetime) fails wide, back to ``[MG1_FLOOR, open)``;
- the constants are recorded in the same commit that dates the status line of
  ``reserved-confirmation-window.md`` (``MG-1 D0 = YYYY-MM-DD``,
  ``MG-1 last = YYYY-MM-DD``); a test binds the two (owner decision OD32);
- an unreadable target date is refused, or dropped by the filter.

There is no override argument and no environment variable. The single
exception is the registered MG-1 confirmation look itself:
``MG1_CONFIRMATION_ENTRY_POINTS`` maps the look's module name, as run with
``python -m``, to the SHA-256 of that module's source bytes. A process is
admitted only when its ``__main__`` module has exactly that name and those
bytes. The MG-1 pre-registration names no look entry point yet, so the
allowlist is empty and every caller is refused. Adding the look is an explicit,
reviewed, tested edit of that constant.

Convergence: when U7 lands on master, ``maker_core.mg1_window`` becomes the one
recorded copy of the window constants. This module should then import
``MG1_FLOOR``, ``MG1_D0``, ``MG1_LAST``, ``window`` and ``is_reserved`` from it,
keeping only the NBM allowlist here. Until then, both copies must be edited
together.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import sys


MG1_FLOOR = date(2026, 10, 15)
# Recorded only from reserved-confirmation-window.md once D0 is dated and the
# 45 promotion-countable dates are computed. Both None: open-ended from the floor.
MG1_D0: date | None = None
MG1_LAST: date | None = None
MG1_RESERVED_COUNT = 45
# module name (as run with ``python -m``) -> SHA-256 of its source bytes. Empty:
# the MG-1 confirmation look is not yet registered as code.
MG1_CONFIRMATION_ENTRY_POINTS: dict[str, str] = {}


class MG1Reserved(ValueError):
    """NBM-guidance-to-band scoring was requested for an MG-1 reserved target date."""


def window(d0=None, last=None):
    """Return the inclusive reserved range ``(start, end)``; ``end`` None is open-ended.

    Arguments exist only so the narrowing invariant can be tested; callers use
    the recorded constants.
    """
    d0 = MG1_D0 if d0 is None else d0
    last = MG1_LAST if last is None else last
    if d0 is None or last is None:
        return MG1_FLOOR, None
    if (not (isinstance(d0, date) and isinstance(last, date))
            or isinstance(d0, datetime) or isinstance(last, datetime)
            or d0 < MG1_FLOOR or last < d0 + timedelta(days=MG1_RESERVED_COUNT - 1)):
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


def registered_confirmation_entry() -> str | None:
    """Return the running registered MG-1 look's module name, or None.

    Matches the ``__main__`` module's spec name exactly and the SHA-256 of its
    source bytes; a lookalike name or edited bytes are not admitted.
    """
    main = sys.modules.get("__main__")
    spec = getattr(main, "__spec__", None)
    name = getattr(spec, "name", None)
    expected = MG1_CONFIRMATION_ENTRY_POINTS.get(name) if isinstance(name, str) else None
    origin = getattr(spec, "origin", None)
    if not expected or not origin:
        return None
    try:
        with open(origin, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None
    return name if actual == expected else None


def refuse_nbm_band_scoring(targets, *, entry: str) -> None:
    """Raise ``MG1Reserved`` if any target date is reserved or unreadable.

    The registered MG-1 confirmation look is admitted for reserved dates; an
    unreadable date is refused even then.
    """
    targets = list(targets)
    days = [as_date(t) for t in targets]
    if registered_confirmation_entry() is not None:
        return
    for day in days:
        if is_reserved(day):
            raise MG1Reserved(f"mg1_reserved_target_date:{entry}:{day.isoformat()}")


def drop_reserved_targets(items, *, target_of):
    """Split ``items`` before any outcome join: return ``(kept, counts)``.

    ``target_of(item)`` gives the item's local target date, or a list of every
    date the item could stand for (all must be readable and unreserved).
    Reserved items are dropped unless the registered MG-1 look is running;
    items with any unreadable date are always dropped. ``counts`` holds counts
    only, never dates.
    """
    registered = registered_confirmation_entry() is not None
    kept, reserved, unreadable = [], 0, 0
    for item in items:
        target = target_of(item)
        try:
            days = [as_date(t) for t in (target if isinstance(target, list) else [target])]
        except MG1Reserved:
            unreadable += 1
            continue
        if not days:
            unreadable += 1
            continue
        if any(is_reserved(day) for day in days) and not registered:
            reserved += 1
            continue
        kept.append(item)
    return kept, {"reserved_dropped": reserved, "unreadable_dropped": unreadable}
