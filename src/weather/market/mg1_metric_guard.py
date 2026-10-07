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
window may only become narrower, and only by editing ``MG1_D0`` and ``MG1_LAST``
in ``maker_core.mg1_window`` (the single recorded copy) in a reviewed change
whose tests pin the new values. Until both are recorded, every target date on
or after ``MG1_FLOOR`` is reserved. The OD3 switch there does not affect this
guard: view-vs-outcome metrics are refused whatever the owner decides on OD3.
"""
from __future__ import annotations

from datetime import date

# The window and its constants have one recorded copy in core (the OD3 switch lives there too).
from maker_core.mg1_window import (MG1_D0, MG1_FLOOR, MG1_LAST, MG1_RESERVED_COUNT, MG1Reserved, as_date as _as_date, is_reserved, window)

__all__ = ["MG1_D0", "MG1_FLOOR", "MG1_LAST", "MG1_RESERVED_COUNT",
           "MG1Reserved", "date_range", "is_reserved", "refuse_reserved_targets", "window"]


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
