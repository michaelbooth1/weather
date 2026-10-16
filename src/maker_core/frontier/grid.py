"""The frozen informed-v1 candidate grid (item 330 build 3).

There are four axes. Every point quotes symmetrically about the size-qualified mid; there is no centre skew
toward the model, because established findings §1b retracted that idea. The fair value may only gate a band.

- ``width_cents``: the distance of each BUY leg from its side's size-qualified centre;
- ``size``: shares per leg;
- ``band_rule``: which bands may be quoted;
    - ``depth_only``: the common gates and displayed depth;
    - ``depth_share``: also an instantaneous no-reaction share in [0.15, 0.70];
    - ``depth_share_fv``: also a valid fair value within one stdev of the mid;
- ``inventory``: ``hold_to_settlement`` or ``resting_sell``. With ``resting_sell``, after a fill the
  filled shares are offered at the entry price plus twice the width, and any unsold remainder is held.

``FIXED`` holds the rules every point shares. ``BASELINES`` are compared against every point and are not
grid points. The grid hash is SHA-256 over the canonical JSON of the axes, fixed rules, baselines and
sorted points, so it does not depend on the order in which values are supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import product

from maker_core.evidence.journal import canonical_bytes, digest

GRID_FORMAT = "maker-core.frontier-grid.informed-v1.0"
BAND_RULES = ("depth_only", "depth_share", "depth_share_fv")
INVENTORY = ("hold_to_settlement", "resting_sell")
AXES = {
    "width_cents": ("1.0", "1.5", "2.0", "2.5", "3.0"),
    "size": (20, 30, 50, 75),
    "band_rule": BAND_RULES,
    "inventory": INVENTORY,
}
FIXED = {
    "centre": "size_qualified_mid",
    "skew": "none",
    "legs": "yes_and_no_buy_equal_size",
    "horizons_days": [1, 2],
    "mid_range": ["0.2", "0.8"],
    "no_quote_before_close_hours": 3,
    "min_displayed_depth": "max(75, size) per side within max spread",
    "share_range_for_share_rules": ["0.15", "0.70"],
    "event_gates": "decided>=0.5 or pull hint stops quoting",
    "first_fill_ends_band_day": True,
    "resting_sell_offset": "2 x width_cents",
    "quote_hold_seconds_without_book": 120,
    "per_leg_cash_cap": "60",
    "per_band_cash_cap": "100",
}
BASELINES = ("no-quote", "blind_re1", "informed-v0")


@dataclass(frozen=True, order=True)
class GridPoint:
    width_cents: Decimal
    size: int
    band_rule: str
    inventory: str

    @property
    def label(self):
        return "w%s-s%d-%s-%s" % (self.width_cents, self.size, self.band_rule, self.inventory)


def _axis(name, values):
    if name == "width_cents":
        out = sorted({Decimal(str(v)) for v in values})
        if not out or any(not Decimal("0.5") <= v <= Decimal("5") for v in out):
            raise ValueError("width_out_of_range")
        return out
    if name == "size":
        out = sorted({int(v) for v in values})
        if not out or any(v <= 0 for v in out):
            raise ValueError("size_out_of_range")
        return out
    allowed = BAND_RULES if name == "band_rule" else INVENTORY
    chosen = set(values)
    if not chosen or any(v not in allowed for v in chosen):
        raise ValueError("unknown_" + name)
    return sorted(chosen, key=allowed.index)


def build(axes=None) -> tuple[GridPoint, ...]:
    """Every combination of the axes in canonical order; repeated or reordered values collapse."""
    axes = AXES if axes is None else axes
    if set(axes) != set(AXES):
        raise ValueError("grid_axes_mismatch")
    columns = [_axis(name, axes[name]) for name in AXES]
    return tuple(sorted(GridPoint(*values) for values in product(*columns)))


def manifest(points=None) -> dict:
    points = build() if points is None else tuple(sorted(points))
    return {"format": GRID_FORMAT, "fixed": FIXED, "baselines": list(BASELINES),
            "axes": {name: sorted({str(getattr(p, name)) for p in points}) for name in AXES},
            "points": [[str(p.width_cents), p.size, p.band_rule, p.inventory] for p in points]}


def grid_hash(points=None) -> str:
    return digest(manifest(points))


def manifest_bytes(points=None) -> bytes:
    return canonical_bytes(manifest(points))


GRID = build()
GRID_HASH = grid_hash(GRID)
