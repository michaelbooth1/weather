"""Universe inventory for the replay execution manifest, from sealed panel bundles.

The neutral core never parses weather slugs; this weather-domain producer binds
each discovered condition to its registered city, target date and IANA timezone
from the captured descriptor's event slug and the built-in market registry.
Every condition in every supplied bundle is listed, excluded ones included.
"""
from __future__ import annotations

from maker_core.replay.bundle import HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS, Limits, load_bundle
from maker_core.replay.payloads import decode
from weather.market.maker_plugin.inputs import event_identity

MAX_BUNDLES = 15
MAX_ROWS = 30000


def universe(paths, *, check=lambda: None):
    if not 1 <= len(paths) <= MAX_BUNDLES:
        raise ValueError("invalid_bundle_inventory")
    rows = {}
    for path in paths:
        bundle = load_bundle(path, limits=Limits(HOST_MAX_BYTES, HOST_MAX_RECORDS, HOST_MAX_SECONDS))
        markets = {c.condition_id: c.market_id for c in bundle.conditions}
        described = set()
        for record in bundle.records:
            check()
            if record.kind != "descriptor":
                continue
            descriptor = decode(record).market
            spec, target = event_identity(descriptor.event_id)
            if spec.id != markets[record.condition_id]:
                raise ValueError("descriptor_city_mismatch")
            row = dict(condition_id=record.condition_id, market_id=spec.id, domain_id=descriptor.domain_id,
                       target_date=target.isoformat(), local_timezone=spec.timezone)
            if rows.setdefault(record.condition_id, row) != row:
                raise ValueError("condition_universe_binding_changed")
            described.add(record.condition_id)
        if described != set(markets):
            raise ValueError("condition_without_descriptor")
        if len(rows) > MAX_ROWS:
            raise ValueError("universe_row_cap")
    return [rows[cid] for cid in sorted(rows)]
