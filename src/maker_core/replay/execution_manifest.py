"""Exact execution-pack bindings. Verification here is preflight, never enrollment."""
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import time
from types import MappingProxyType

from maker_core.evidence.journal import digest, plain
from maker_core.replay import authorization
from maker_core.replay.bundle import BundleError, Limits, _Reader, sha256, time_zone, timestamp
from maker_core.replay import ceilings as ceiling_rule
from maker_core.replay.calibration import calibrate
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.pack_io import read_json
from maker_core.replay.payloads import decode

# Clarification 2 (v2): manifest-only intervals, measured ceilings, rule-derived
# quote markets, look protection. Built on or after the scoring date once settlement seals.
FORMAT = "maker_core.replay.execution.v2"
# v3 adds Clarification 3 (reporting only); v2 stays buildable until production revokes it.
AUTHORIZATION_IDS = ("maker-replay-2026-10-15-v2", "maker-replay-2026-10-15-v3")
QUOTE_DATES = tuple(date(2026, 9, 30)+timedelta(days=i) for i in range(14))
SETTLEMENT_DATE = date(2026, 10, 14)
# max_events and max_outputs are the measured ceilings, not frozen values.
FROZEN_CONFIG = dict(policy="informed-v0", initial_cash="100", band_cap="100", order_cap="60",
                     wallet_cap="100", event_cap="100", factor_cap="100", max_book_gap_seconds=60,
                     fill_bound="strictly_through", clock_pulls=())
CEILING_FIELDS = {"max_input_bytes", "max_records", "max_seconds", "max_output_bytes", "max_memory_bytes"}
HURDLES = dict(primary_fill_bound="strictly_through", primary_metric="modeled_net_k1",
               economic_baselines=["blind_re1", "no_quote"], economic_lower_bound_strictly_above=0,
               quote_dates=14, min_dates=10, min_markets=10, min_valid_replicates=100,
               pull_point_ratio_at_least=2, pull_minimum_denominators=1, clock_removed_minimum=1,
               pull_minute_match_tolerance=1, move_threshold=.05, move_seconds=300,
               sensitivity_fill_bound="at_price", sensitivity_metric="modeled_net_k05")


def source_hashes(*, check=lambda: None):
    root = Path(__file__).resolve().parents[3]
    # Enrollment cannot hash itself. Its only effect is permission to use the
    # already-built manifest; all verifier, engine, policy and scorer bytes bind.
    paths = sorted(set((root/"src/maker_core").rglob("*.py")) |
                   set((root/"src/weather/market/maker_plugin").rglob("*.py")) |
                   {root/"pyproject.toml"} | {root/"src/weather/market"/name for name in (
                       "maker_plugin_runner.py", "maker_plugin_capture.py", "maker_plugin_sources.py", "maker_replay_bundle.py")})
    reader = _Reader(Limits(8*1024**2, 1, 30), time.monotonic)
    result = {}
    for path in paths:
        check()
        if path == root/"src/maker_core/replay/approved_registrations.py":
            continue
        result[path.relative_to(root).as_posix()] = sha256(reader.read(path, 1024**2))
    if not result or not any("/maker_plugin/" in p for p in result):
        raise BundleError("missing_executable_source_inventory")
    return result


def _inventory(bundles, inventory, *, check):
    if not isinstance(inventory, list) or not inventory or len(inventory) > 30000:
        raise BundleError("invalid_universe_inventory")
    fields = {"condition_id", "market_id", "domain_id", "target_date", "local_timezone"}
    if any(not isinstance(r, dict) or set(r) != fields or any(not isinstance(v, str) or not v for v in r.values()) for r in inventory):
        raise BundleError("incomplete_universe_binding")
    if [r["condition_id"] for r in inventory] != sorted({r["condition_id"] for r in inventory}):
        raise BundleError("universe_not_sorted_unique")
    by_id = {r["condition_id"]: r for r in inventory}
    discovered = {c.condition_id for b in bundles for c in b.conditions}
    if set(by_id) != discovered:
        raise BundleError("universe_discovery_mismatch")
    descriptors = set()
    for bundle in bundles:
        for c in bundle.conditions:
            item = by_id[c.condition_id]
            if (item["market_id"], item["domain_id"]) != (c.market_id, c.domain_id):
                raise BundleError("universe_cluster_mismatch")
        for row in bundle.records:
            check()
            if row.kind != "descriptor":
                continue
            desc, item = decode(row), by_id[row.condition_id]
            target = date.fromisoformat(item["target_date"])
            zone = time_zone(item["local_timezone"])  # coded and strict on every platform
            # Target is supplied by the domain export, not parsed from slugs or
            # inferred with UTC dates. Check its local calendar binding.
            close = desc.market.close_at_utc.astimezone(zone)
            if (desc.market.domain_id != item["domain_id"] or target.isoformat() != item["target_date"]
                    or close.date() != target+timedelta(days=1) or close.time() != datetime.min.time()
                    or (target-row.captured_at.astimezone(zone).date()).days != desc.horizon_days):
                raise BundleError("universe_target_descriptor_mismatch")
            descriptors.add(row.condition_id)
    if discovered != descriptors:
        raise BundleError("universe_descriptor_missing")
    return by_id


def market_time_zones(bundles, inventory, *, registered, check=lambda: None):
    """market_id -> IANA zone for the local-midnight horizon refresh (registration C13; owner Gate Q1, 2026-10-07).

    Read from the bound universe inventory's ``local_timezone``, which ``_inventory`` has already checked against
    every descriptor's ``close_at_utc`` (local midnight after the target) and ``horizon_days``. A market whose
    conditions name different zones is refused rather than resolved; names are compared as strings, so aliases
    (``GB`` vs ``Europe/London``) count as a disagreement.

    That descriptor check is offset-only: a wrong zone with the same UTC offset at each close (``Africa/Abidjan``
    for a London market in November) passes it and would give a wrong local midnight across a DST change. So the
    zone is also checked by name against ``registered`` (market_id -> zone), the domain's own market registry
    supplied by the caller (the neutral core reads no domain registry; for weather it is
    ``weather.market.maker_replay_universe.registered_time_zones``). A market missing from it is refused."""
    zones = {}
    for row in _inventory(bundles, inventory, check=check).values():
        if zones.setdefault(row["market_id"], row["local_timezone"]) != row["local_timezone"]:
            raise BundleError("market_time_zone_disagreement")
    registered = dict(registered)
    for market, zone in zones.items():
        if market not in registered:
            raise BundleError("market_time_zone_unregistered")
        if registered[market] != zone:
            raise BundleError("market_time_zone_registry_mismatch")
    return MappingProxyType(dict(sorted(zones.items())))


def active_intervals(bundles, inventory, *, check=lambda: None):
    by_id = _inventory(bundles, inventory, check=check)
    windows, excluded = [], []
    for bundle in bundles:
        start = datetime.combine(bundle.day, datetime.min.time(), tzinfo=timezone.utc)
        maintenance_start, maintenance_end = start+timedelta(hours=5), start+timedelta(hours=8)
        for c in bundle.conditions:
            check()
            item = by_id[c.condition_id]
            if bundle.day == SETTLEMENT_DATE or date.fromisoformat(item["target_date"]) > SETTLEMENT_DATE:
                excluded.append(dict(date=bundle.day.isoformat(), condition_id=c.condition_id,
                                     reason="settlement_only" if bundle.day == SETTLEMENT_DATE else "target_after_settlement_only"))
                continue
            for low, high in ((c.active_from, min(c.active_until, maintenance_start)),
                              (max(c.active_from, maintenance_end), c.active_until)):
                if low < high:
                    windows.append(dict(date=bundle.day.isoformat(), condition_id=c.condition_id,
                                        start=low.isoformat(), end=high.isoformat()))
    return windows, excluded


def quote_market_rule(calibration_bundles):
    """Cities with at least one 88a-captured band on a calibration date; no hand list.

    A weather condition enters a bundle only with a captured book (the descriptor
    needs both token books), so this is the sealed per-date captured-band inventory.
    """
    return sorted({c.market_id for b in calibration_bundles for c in b.conditions})


def measured_limits(measurement):
    """Validate the resource-only measurement and re-apply the fixed rule."""
    if not isinstance(measurement, dict) or measurement.get("format") != ceiling_rule.FORMAT:
        raise BundleError("invalid_ceiling_measurement")
    derived = ceiling_rule.derive(measurement.get("per_date"))
    if measurement.get("derived") != derived:
        raise BundleError("ceiling_derivation_mismatch")
    return ceiling_rule.run_limits(derived)


def build_manifest(bundles, calibration_bundles, calibration, inventory, owner_decision, measurement, *,
                   calibration_sha256, inventory_sha256, quote_inventory_sha256, measurement_sha256,
                   check=lambda: None):
    bundles = tuple(sorted(bundles, key=lambda b: b.day))
    if tuple(b.day for b in bundles) != (*QUOTE_DATES, SETTLEMENT_DATE):
        raise BundleError("manifest_requires_fourteen_quote_dates_and_settlement_only")
    run = measured_limits(measurement)
    if not isinstance(calibration, dict):
        raise BundleError("invalid_calibration_json")
    all_bundles = (*bundles, *calibration_bundles)
    if (sum(b.input_bytes for b in all_bundles) > run["max_input_bytes"]
            or sum(len(b.records) for b in all_bundles) > run["max_records"]):
        raise BundleError("manifest_input_ceiling")
    if calibration.get("quote_markets") != quote_market_rule(calibration_bundles):
        raise BundleError("quote_markets_rule_mismatch")
    recomputed = calibrate(calibration_bundles, calibration.get("quote_markets"), check=check)
    recomputed["quote_inventory_sha256"] = quote_inventory_sha256
    if calibration != recomputed:
        raise BundleError("calibration_recomputation_mismatch")
    # Ceilings were rehearsed against one calibration; it must be the sealed one bound here.
    if measurement.get("calibration_sha256") != calibration_sha256:
        raise BundleError("ceiling_measurement_calibration_mismatch")
    # Calibration freezes M before scoring; do not silently add a newly found city.
    quote_markets = sorted({c.market_id for b in bundles if b.day in QUOTE_DATES for c in b.conditions})
    if sorted(set(quote_markets) | {c.market_id for b in calibration_bundles for c in b.conditions}) != calibration["markets"]:
        raise BundleError("calibration_city_union_mismatch")
    if (not isinstance(owner_decision, dict) or owner_decision.get("authorization_id") not in AUTHORIZATION_IDS
            or set(owner_decision) != authorization.DECISION_FIELDS | set(
                authorization.CLARIFIED_IDS[owner_decision["authorization_id"]])
            or owner_decision["scoring_date"] != "2026-10-15" or owner_decision["owner"] != "michaelbooth1"):
        raise BundleError("clarified_owner_decision_required")
    windows, exclusions = active_intervals(bundles, inventory, check=check)
    if {f.name for f in fields(ReplayConfig)} != set(FROZEN_CONFIG) | {"hazard_per_minute", "max_events", "max_outputs"}:
        raise BundleError("new_config_field_requires_prospective_addendum")
    config = ReplayConfig(**FROZEN_CONFIG, hazard_per_minute=float(calibration["hazard_per_minute"]),
                          max_events=run["max_events"], max_outputs=run["max_outputs"])
    return dict(format=FORMAT, owner=owner_decision["owner"], signed_at=owner_decision["signed_at"],
                owner_decision=owner_decision, hurdles=HURDLES, policies=list(authorization.POLICIES),
                clusters=["date", "date_x_market"], dates=[d.isoformat() for d in QUOTE_DATES],
                settlement_only_date=SETTLEMENT_DATE.isoformat(), markets=quote_markets,
                metrics=["modeled_net_k1", "modeled_net_k05"], replay_config=plain(config),
                bootstrap_replicates=2000, bootstrap_seed=20260926, universe=inventory,
                universe_sha256=inventory_sha256, active_intervals=windows, exclusions=exclusions,
                maintenance_utc=["05:00", "08:00"], input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
                record_sources_sha256=digest([dict(r.source_hashes) for b in bundles for r in b.records]),
                calibration=calibration, calibration_sha256=calibration_sha256,
                source_hashes=source_hashes(check=check), quote_market_rule="captured_band_on_any_calibration_date",
                ceiling_measurement=measurement, ceiling_measurement_sha256=measurement_sha256,
                ceilings=dict(max_input_bytes=run["max_input_bytes"], max_records=run["max_records"],
                              max_seconds=run["max_seconds"], max_output_bytes=run["max_output_bytes"],
                              max_memory_bytes=run["max_memory_bytes"]))


def verify_manifest(doc, bundles, calibration_bundles, *, calibration_path, inventory_path,
                    quote_inventory_path, measurement_path, decision_log, frozen_protocol, execution_addendum,
                    clarification, clarification_2, now, clarification_3=None, check=lambda: None):
    reader = _Reader(Limits(458752, 1, 5), time.monotonic)
    authorization._verify_decision(doc, reader, decision_log, frozen_protocol, execution_addendum, now,
                                   clarification, require_scoring_date=False, clarification_2=clarification_2,
                                   clarification_3=clarification_3)
    calibration, calibration_hash = read_json(calibration_path)
    inventory, inventory_hash = read_json(inventory_path, 8*1024**2)
    quote_inventory, quote_hash = read_json(quote_inventory_path)
    measurement, measurement_hash = read_json(measurement_path)
    if not isinstance(calibration, dict):
        raise BundleError("invalid_calibration_json")
    if quote_inventory != calibration.get("quote_markets"):
        raise BundleError("quote_inventory_mismatch")
    if set(doc.get("ceilings", {})) != CEILING_FIELDS:
        raise BundleError("incomplete_ceiling_bindings")
    expected = build_manifest(bundles, calibration_bundles, calibration, inventory, doc["owner_decision"], measurement,
        calibration_sha256=calibration_hash, inventory_sha256=inventory_hash, quote_inventory_sha256=quote_hash,
        measurement_sha256=measurement_hash, check=check)
    if doc != expected:
        raise BundleError("execution_manifest_binding_mismatch")
    return expected


def apply_manifest(doc, bundles):
    """Project declared inactive intervals without discarding settlement or carried lots."""
    return tuple(replace(b, active_intervals=tuple((w["condition_id"], timestamp(w["start"]), timestamp(w["end"]))
        for w in doc["active_intervals"] if w["date"] == b.day.isoformat())) for b in bundles)
