"""Universe inventory for maker replay v2, from sealed v0.2 bundles (W7; registration draft §4).

The v0.2 sibling of ``maker_replay_universe`` (left unchanged for the v1 path). Each discovered
condition is bound to its registered city, target date and IANA timezone from the captured
descriptor's event slug and the built-in market registry. Only each bundle's ``bundle.json`` (pass one
hashes every stream) and ``descriptor.jsonl`` are parsed. Every condition is listed, excluded ones
included; the owner exclusion and the universe rule act later, in ``maker_core.replay.v2.intervals``.

Caps (A-defender M10): at most 16 panel bundles (14 quote and 2 settlement-only dates) and at most 3
calibration bundles, 19 in all. Panel days must be unique gated days and calibration days unique
calibration dates; a calibration-kind (hazard) export is not a universe input: the calibration universe
comes from the night-format export of each calibration date (U1 Defender MF6). The two sets are opened
separately; ``intervals.evaluate`` needs one panel's inventory at a time.

Limits (U1 Defender r2 C2): each bundle is opened under X1's ``V2Limits`` (default per-bundle stored,
decoded, record and per-pass caps) and every open and descriptor read of one ``universe`` call shares ONE
``RunBudget``: the run's deadline (default 32,768 s, reg §8) and stored-input total (default 16 GiB). The
caller may pass its own run (a look or rehearsal that also opens the bundles elsewhere); otherwise one is
built per call on ``clock``. A run over 19 bundles is therefore bounded by that one budget, not by 19
separate 32,768 s bundle lifetimes.
"""
from __future__ import annotations

import time

from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2.limits import RunBudget, V2Limits
from maker_core.replay.v2.panel import CALIBRATION_DATES, GATED_DAYS
from maker_core.replay.v2.universe_v02 import decoded, descriptors
from weather.market.maker_plugin.inputs import event_identity

MAX_PANEL_BUNDLES = 16
MAX_CALIBRATION_BUNDLES = 3
MAX_BUNDLES = MAX_PANEL_BUNDLES + MAX_CALIBRATION_BUNDLES
MAX_ROWS = 30000
HAZARD_KINDS = frozenset({"descriptor", "coverage", "trade"})  # a calibration-kind (P2) export's streams


def rows_of(bundles, *, check=lambda: None):
    """Inventory rows for already-opened v0.2 bundles."""
    rows = {}
    for bundle in bundles:
        markets = {c.condition_id: c.market_id for c in bundle.conditions}
        described = set()
        for record in descriptors(bundle):
            check()
            value = decoded(record)
            spec, target = event_identity(value.market.event_id)
            if spec.id != markets[record.condition_id]:
                raise ValueError("descriptor_city_mismatch")
            row = dict(condition_id=record.condition_id, market_id=spec.id, domain_id=value.market.domain_id,
                       target_date=target.isoformat(), local_timezone=spec.timezone)
            if rows.setdefault(record.condition_id, row) != row:
                raise ValueError("condition_universe_binding_changed")
            described.add(record.condition_id)
        if described != set(markets):
            raise ValueError("condition_without_descriptor")
        if len(rows) > MAX_ROWS:
            raise ValueError("universe_row_cap")
    return [rows[cid] for cid in sorted(rows)]


def universe(panel_paths, calibration_paths=(), *, check=lambda: None, limits=None, run=None,
             clock=time.monotonic):
    """Sorted inventory rows over the panel and calibration bundle folders, under one shared run budget."""
    panel_paths, calibration_paths = list(panel_paths), list(calibration_paths)
    if (not 1 <= len(panel_paths) + len(calibration_paths) <= MAX_BUNDLES
            or len(panel_paths) > MAX_PANEL_BUNDLES or len(calibration_paths) > MAX_CALIBRATION_BUNDLES):
        raise ValueError("invalid_bundle_inventory")
    limits = V2Limits() if limits is None else limits
    if type(limits) is not V2Limits or (run is not None and not isinstance(run, RunBudget)):
        raise ValueError("invalid_universe_limits")
    run = RunBudget(clock=clock) if run is None else run
    panel_bundles = [open_stream_bundle(path, limits=limits, clock=clock, run=run) for path in panel_paths]
    calibration_bundles = [open_stream_bundle(path, limits=limits, clock=clock, run=run)
                           for path in calibration_paths]
    for bundles, allowed in ((panel_bundles, GATED_DAYS), (calibration_bundles, CALIBRATION_DATES)):
        days = [b.day for b in bundles]
        if len(set(days)) != len(days) or any(day not in allowed for day in days):
            raise ValueError("invalid_bundle_inventory")
        if any({ref.name.split(".")[0] for ref in b.streams} <= HAZARD_KINDS for b in bundles):
            raise ValueError("calibration_kind_bundle_not_a_universe_input")
    return rows_of((*panel_bundles, *calibration_bundles), check=check)
