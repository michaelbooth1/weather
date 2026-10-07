"""Universe inventory for maker replay v2, from sealed v0.2 bundles (W7; registration draft §4).

The v0.2 sibling of ``maker_replay_universe`` (left unchanged for the v1 path). Each discovered
condition is bound to its registered city, target date and IANA timezone from the captured
descriptor's event slug and the built-in market registry. Only each bundle's ``bundle.json`` (pass one
hashes every stream) and ``descriptor.jsonl`` are parsed. Every condition is listed, excluded ones
included; the owner exclusion and the universe rule act later, in ``maker_core.replay.v2.intervals``.

Caps (A-defender M10): at most 16 panel bundles (14 quote and 2 settlement-only dates) and at most 3
calibration bundles, 19 in all.
"""
from __future__ import annotations

from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits
from maker_core.replay.bundle_v02 import open_stream_bundle
from maker_core.replay.v2.universe_v02 import decoded, descriptors
from weather.market.maker_plugin.inputs import event_identity

MAX_PANEL_BUNDLES = 16
MAX_CALIBRATION_BUNDLES = 3
MAX_BUNDLES = MAX_PANEL_BUNDLES + MAX_CALIBRATION_BUNDLES
MAX_ROWS = 30000


def rows_of(bundles, *, check=lambda: None):
    """Inventory rows for already-opened v0.2 bundles."""
    rows = {}
    for bundle in bundles:
        markets = {c.condition_id: c.market_id for c in bundle.conditions}
        described = set()
        for record in descriptors(bundle):
            check()
            value = decoded(record)
            if value is None:
                continue
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


def universe(panel_paths, calibration_paths=(), *, check=lambda: None):
    """Sorted inventory rows over the panel and calibration bundle folders."""
    panel_paths, calibration_paths = list(panel_paths), list(calibration_paths)
    if (not 1 <= len(panel_paths) + len(calibration_paths) <= MAX_BUNDLES
            or len(panel_paths) > MAX_PANEL_BUNDLES or len(calibration_paths) > MAX_CALIBRATION_BUNDLES):
        raise ValueError("invalid_bundle_inventory")
    limits = Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS)
    bundles = [open_stream_bundle(path, limits=limits) for path in (*panel_paths, *calibration_paths)]
    return rows_of(bundles, check=check)
