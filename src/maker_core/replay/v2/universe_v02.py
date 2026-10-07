"""The v0.2 universe inventory check over descriptor streams (maker replay v2 W7, registration draft §4).

``check_inventory`` is the frozen ``execution_manifest._inventory`` rule applied to v0.2 bundles: the
inventory lists exactly the discovered conditions, each with its cluster identity (market and domain),
local target date and IANA timezone; every condition is described; and every captured descriptor agrees
with its row (domain, local close at midnight after the target date, horizon equal to the local-date
distance at capture). A descriptor that does not decode refuses (``universe_descriptor_undecodable``),
as v1's ``_inventory`` does (master-agent steer, U1 Defender MF1): nothing is skipped silently. The
neutral core never parses slugs: target and timezone come from the weather
producer (``weather.market.maker_replay_universe_v02``) and are checked here against descriptors.

``descriptors`` reads one bundle's descriptor stream alone (pass one must already have hashed it: the
bundle comes from ``open_stream_bundle``). No other stream of the bundle is opened. Both grouped formats
are read: v0.2 (``descriptor.jsonl``) and X1's gzip v0.3 (``descriptor.jsonl.gz``), through X1's public,
format-blind accessor ``bundle_v02.stream_records(bundle, "descriptor")`` (U1 Defender r2 C1); no private
reader symbol is used. The read is one pass under the bundle's run budget: the ONE ``RunBudget`` the caller
opened every bundle of the run with (U1 Defender r2 C2), or else the bundle's own lifetime fallback.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from maker_core.replay.bundle import BundleError
from maker_core.replay.bundle_v02 import FORMAT_V02, stream_records
from maker_core.replay.payloads import decode

DESCRIPTOR_STEM = "descriptor"  # descriptor.jsonl (v0.2) or descriptor.jsonl.gz (v0.3, X1)
STREAM_FORMATS = (FORMAT_V02, "maker_core.replay.bundle.v0.3")
MAX_ROWS = 30000
FIELDS = frozenset({"condition_id", "market_id", "domain_id", "target_date", "local_timezone"})


def descriptors(bundle):
    """The bundle's descriptor records in ``(captured_at, sequence)`` order; only that stream is read."""
    if bundle.format not in STREAM_FORMATS:
        raise BundleError("v02_bundle_required")
    if bundle.stream(DESCRIPTOR_STEM) is None:
        raise BundleError("universe_descriptor_stream_missing")
    records = []
    for record in stream_records(bundle, DESCRIPTOR_STEM):
        if record.kind != "descriptor":
            raise BundleError("descriptor_stream_holds_other_kind")
        records.append(record)
    return records


def day_inputs(bundles):
    """``[(bundle, descriptor records)]`` for ``check_inventory`` and ``intervals.active_intervals``."""
    return [(bundle, descriptors(bundle)) for bundle in sorted(bundles, key=lambda b: b.day)]


def decoded(record):
    """A descriptor record's typed value; one that does not decode refuses, never skipped."""
    try:
        return decode(record)
    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
        raise BundleError("universe_descriptor_undecodable") from exc


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise BundleError("universe_unknown_timezone") from exc


def check_inventory(days, inventory, *, check=lambda: None):
    """Validate ``inventory`` against ``days`` (``[(bundle-like, descriptor records)]``); returns rows by ID."""
    if not isinstance(inventory, list) or not inventory or len(inventory) > MAX_ROWS:
        raise BundleError("invalid_universe_inventory")
    if any(not isinstance(r, dict) or set(r) != FIELDS or any(not isinstance(v, str) or not v for v in r.values())
           for r in inventory):
        raise BundleError("incomplete_universe_binding")
    if [r["condition_id"] for r in inventory] != sorted({r["condition_id"] for r in inventory}):
        raise BundleError("universe_not_sorted_unique")
    by_id = {r["condition_id"]: r for r in inventory}
    for row in inventory:
        try:
            target = date.fromisoformat(row["target_date"])
        except ValueError as exc:
            raise BundleError("universe_invalid_target_date") from exc
        if target.isoformat() != row["target_date"]:
            raise BundleError("universe_invalid_target_date")
        _zone(row["local_timezone"])
    discovered = {c.condition_id for day, _ in days for c in day.conditions}
    if set(by_id) != discovered:
        raise BundleError("universe_discovery_mismatch")
    described = set()
    for day, records in days:
        for c in day.conditions:
            item = by_id[c.condition_id]
            if (item["market_id"], item["domain_id"]) != (c.market_id, c.domain_id):
                raise BundleError("universe_cluster_mismatch")
        for record in records:
            check()
            if record.kind != "descriptor":
                raise BundleError("descriptor_stream_holds_other_kind")
            desc, item = decoded(record), by_id[record.condition_id]
            target = date.fromisoformat(item["target_date"])
            zone = _zone(item["local_timezone"])
            close = desc.market.close_at_utc.astimezone(zone)
            if (desc.market.domain_id != item["domain_id"]
                    or close.date() != target + timedelta(days=1) or close.time() != datetime.min.time()
                    or (target - record.captured_at.astimezone(zone).date()).days != desc.horizon_days):
                raise BundleError("universe_target_descriptor_mismatch")
            described.add(record.condition_id)
    if discovered != described:
        raise BundleError("universe_descriptor_missing")
    return by_id
