"""Exact execution-pack bindings. Verification here is preflight, never enrollment."""
from collections.abc import Mapping
from dataclasses import fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import time

from maker_core.evidence.journal import digest, plain
from maker_core.replay import authorization
from maker_core.replay.bundle import (ZONE_MAP_BUILDER, BundleError, Limits, RegisteredZones, _Reader, sha256, time_zone,
                                      timestamp, tzdata_binding)
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


def _inventory_rows(inventory):
    """condition_id -> row of a well-formed universe inventory (shape, sorted and unique; no bundle checks)."""
    if not isinstance(inventory, list) or not inventory or len(inventory) > 30000:
        raise BundleError("invalid_universe_inventory")
    fields = {"condition_id", "market_id", "domain_id", "target_date", "local_timezone"}
    if any(not isinstance(r, dict) or set(r) != fields or any(not isinstance(v, str) or not v for v in r.values()) for r in inventory):
        raise BundleError("incomplete_universe_binding")
    if [r["condition_id"] for r in inventory] != sorted({r["condition_id"] for r in inventory}):
        raise BundleError("universe_not_sorted_unique")
    return {r["condition_id"]: r for r in inventory}


def _inventory(bundles, inventory, *, check):
    by_id = _inventory_rows(inventory)
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


def _zones(by_id):
    """market_id -> zone name from the validated inventory rows; a market whose conditions disagree is refused."""
    zones = {}
    for row in by_id.values():
        if zones.setdefault(row["market_id"], row["local_timezone"]) != row["local_timezone"]:
            raise BundleError("market_time_zone_disagreement")
    return zones


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
    ``weather.market.maker_replay_universe.registered_time_zones``). A market missing from it is refused.

    ``registered`` is required (owner T3(a), 2026-10-09): omitting it is a TypeError, and ``None`` or a value that
    is not a mapping refuses ``market_time_zone_registry_required`` (never a silent skip). The result is a
    ``RegisteredZones`` whose ``source`` (this builder plus the inventory and registry digests) binds into the v2
    run digest (owner T2(a); ``pipeline.run_binding``)."""
    if not isinstance(registered, Mapping):
        raise BundleError("market_time_zone_registry_required")
    zones = _zones(_inventory(bundles, inventory, check=check))
    return RegisteredZones(zones, _registry_source(zones, inventory, registered))


def _registry_source(zones, inventory, registered):
    """Check ``zones`` by name against the registry and return the ``RegisteredZones.source`` record."""
    if not isinstance(registered, Mapping):
        raise BundleError("market_time_zone_registry_required")
    registered = dict(registered)
    if not all(isinstance(m, str) and isinstance(z, str) for m, z in registered.items()):
        raise BundleError("market_time_zone_registry_invalid")  # coded, not a TypeError from sorting mixed keys
    for market, zone in zones.items():
        if market not in registered:
            raise BundleError("market_time_zone_unregistered")
        if registered[market] != zone:
            raise BundleError("market_time_zone_registry_mismatch")
    return dict(builder=ZONE_MAP_BUILDER, registry_checked=True, inventory_sha256=digest(inventory),
                registry_sha256=digest(dict(sorted(registered.items()))))


def verify_registered_zones(time_zones, source, markets, *, inventory, registered, conditions=()):
    """A scored run's zone map, re-derived from an inventory and a registry (the F2 remainder).

    ``pipeline.verify_run_binding`` checks integrity only: a caller can construct ``RegisteredZones`` with a made-up
    ``source`` or recompute every digest. This recomputes what ``market_time_zones`` would return from
    ``inventory`` and ``registered`` (the domain registry), and refuses unless
    - ``inventory`` and ``registered`` are both given (``run_binding_pack_required``);
    - the rows are well formed, each market names one zone and every zone is registered under that name (the
      ``_inventory_rows``, ``_zones`` and registry codes);
    - ``source`` is exactly the recomputed record, ``registry_checked`` the boolean ``True`` (not ``1``), so
      ``inventory_sha256`` is ``digest(inventory)`` and ``registry_sha256`` the registry's digest
      (``run_binding_zone_source_mismatch``);
    - the bound map ``time_zones`` equals the inventory's map exactly (``run_binding_zone_map_mismatch``);
    - ``markets`` is a non-empty condition -> market mapping, every one of ``conditions`` (the plan's condition ids)
      is in it, and every run condition is an inventory row of the same market (``run_binding_inventory_mismatch``).
    It does not by itself say where ``inventory`` came from: ``verify_scored_pack`` (what ``report.build_report``
    calls) takes it from the verified execution manifest. The bundle-level descriptor checks of ``_inventory`` ran
    when the pack was built and verified (``verify_manifest``); the report sees the plan, not the bundles."""
    if inventory is None or registered is None:
        raise BundleError("run_binding_pack_required")
    by_id = _inventory_rows(inventory)
    zones = _zones(by_id)
    expected = _registry_source(zones, inventory, registered)
    if (not isinstance(source, Mapping) or dict(source) != expected or source["registry_checked"] is not True
            or not all(type(source[k]) is str for k in ("builder", "inventory_sha256", "registry_sha256"))):
        raise BundleError("run_binding_zone_source_mismatch")
    if not isinstance(time_zones, Mapping) or dict(time_zones) != zones:
        raise BundleError("run_binding_zone_map_mismatch")
    if (not isinstance(markets, Mapping) or not markets
            or not all(isinstance(c, str) and isinstance(m, str) for c, m in markets.items())
            or any(c not in markets for c in conditions)):
        raise BundleError("run_binding_inventory_mismatch")
    for condition, market in markets.items():
        row = by_id.get(condition)
        if row is None or row["market_id"] != market:
            raise BundleError("run_binding_inventory_mismatch")
    return expected


PACK_CHECK = "maker_core.replay.execution_manifest.verify_scored_pack"


# The only non-synthetic provenance the sealed bundle readers accept (``bundle.load_bundle``, ``bundle_v02``); the
# exporters write it into every sealed capture bundle. A scored report's days must all carry it (R155 Fable F1).
SEALED_PROVENANCE = "captured"
_PACK_FIELDS = {"universe", "universe_sha256", "tzdata", "input_hashes", "dates", "settlement_only_date"}


def _pack_days(manifest):
    """The manifest's ``input_hashes`` as a plain dict, checked against its own ``dates`` and ``settlement_only_date``:
    exactly one entry per quote date and one for the settlement-only date, in that (ISO, so calendar) order."""
    hashes, dates, settlement = manifest["input_hashes"], manifest["dates"], manifest["settlement_only_date"]
    if (not isinstance(hashes, Mapping) or not isinstance(dates, list) or not isinstance(settlement, str)
            or not all(isinstance(d, str) for d in dates)
            or not all(isinstance(k, str) and isinstance(v, Mapping) for k, v in hashes.items())):
        raise BundleError("run_binding_pack_manifest_invalid")
    days = [*dates, settlement]
    if list(hashes) != days or days != sorted(set(days)):
        raise BundleError("run_binding_pack_days_mismatch")
    return {day: dict(value) for day, value in hashes.items()}


def verify_scored_pack(run_binding, plan, markets, *, manifest, registered):
    """The pack check of a scored v2 report: bind the run's days, inputs and zone map to the verified manifest.

    ``manifest`` is the execution manifest document that ``verify_manifest`` returned for this pack (the runner
    verifies it; this function does not re-run ``verify_manifest``, which needs the bundles and the signed
    documents). ``registered`` is the domain registry (for weather,
    ``weather.market.maker_replay_universe.registered_time_zones()``; the neutral core reads no domain registry).
    ``plan`` is the run's ``lockstep.RunPlan``. The inventory is never a free argument: it is
    ``manifest["universe"]``. Refuses unless
    - both are given (``run_binding_pack_required``) and ``manifest`` is an execution manifest of this ``FORMAT``
      carrying ``universe``, ``universe_sha256``, ``tzdata``, ``input_hashes``, ``dates`` and
      ``settlement_only_date`` of the right types (``run_binding_pack_manifest_invalid``);
    - every plan day is a sealed capture day, provenance ``SEALED_PROVENANCE``
      (``run_binding_pack_provenance_unsealed``): a plan that mixes synthetic and captured days is not a scored run
      of the pack;
    - the manifest's ``input_hashes`` has exactly one entry per ``dates`` entry plus the ``settlement_only_date``, in
      that order (``run_binding_pack_days_mismatch``; ``build_manifest`` writes it so and ``verify_manifest`` pins
      the dates), and the plan's ``{day: input_hashes}`` equals it exactly: every quote day and the settlement day,
      no subset, no superset, no other bundle-file hashes (``run_binding_pack_input_hashes_mismatch``). A
      re-exported bundle set has other input hashes and refuses here even with an identical universe. These are
      labels copied from the loaded bundles; the records actually replayed are bound by ``verify_scored_records``;
    - ``digest(manifest["universe"])`` equals ``manifest["universe_sha256"]`` (``run_binding_pack_universe_mismatch``).
      The manifest binds the universe file's sha; the file is written as canonical JSON (``pack_io.write_json``),
      so that sha *is* ``digest`` of its rows, the same hash as the run's ``time_zones_source.inventory_sha256``.
      One hash, compared like with like; a non-canonical universe file refuses here;
    - ``verify_registered_zones`` accepts the run's map and source against that universe and ``registered``, with
      every plan condition in ``markets``;
    - the run's tzdata block equals the manifest's ``tzdata`` record (``run_binding_pack_tzdata_mismatch``): both are
      ``bundle.tzdata_binding`` over the same zones once the map equals the universe's.
    Returns the report's ``pack_check`` record: this verifier, the manifest's ``digest`` (equal to the manifest
    file's sha, and so to the v1 ``pre_registration_sha256``, only when the file was written by
    ``pack_io.write_json``; this function reads no file, so for other file bytes the binding is this canonical digest
    plus the enrollment lookup, not the file's sha: R155 defender-2 D3),
    whether that digest is enrolled in ``approved_registrations.APPROVED_REGISTRATIONS``, the digest of the
    ``input_hashes`` it matched, the universe and registry digests, and the tzdata zone-file digest it bound.
    Enrollment is recorded, not enforced: the runner reads the
    manifest through ``authorization.read_authorization`` (which refuses an unenrolled hash) and ``verify_manifest``
    before it builds the report. A fabricated manifest therefore still yields a report, but one whose
    ``manifest_sha256`` is not the verified pack's and whose ``manifest_enrolled`` is false."""
    if manifest is None or registered is None:
        raise BundleError("run_binding_pack_required")
    if not isinstance(manifest, Mapping) or manifest.get("format") != FORMAT or not _PACK_FIELDS <= set(manifest):
        raise BundleError("run_binding_pack_manifest_invalid")
    input_hashes = _pack_days(manifest)
    if any(d.provenance != SEALED_PROVENANCE for d in plan.days):
        raise BundleError("run_binding_pack_provenance_unsealed")
    if {d.day.isoformat(): dict(d.input_hashes) for d in plan.days} != input_hashes:
        raise BundleError("run_binding_pack_input_hashes_mismatch")
    conditions = [c.condition_id for d in plan.days for c in d.conditions]
    inventory = manifest["universe"]
    if digest(inventory) != manifest["universe_sha256"]:
        raise BundleError("run_binding_pack_universe_mismatch")
    expected = verify_registered_zones(run_binding["time_zones"], run_binding["time_zones_source"], markets,
                                       inventory=inventory, registered=registered, conditions=conditions)
    if manifest["tzdata"] != run_binding["tzdata"]:
        raise BundleError("run_binding_pack_tzdata_mismatch")
    from maker_core.replay import approved_registrations
    manifest_sha256 = digest(manifest)
    return dict(verifier=PACK_CHECK, manifest_format=FORMAT, manifest_sha256=manifest_sha256,
                manifest_enrolled=manifest_sha256 in approved_registrations.APPROVED_REGISTRATIONS,
                input_hashes_sha256=digest(input_hashes), universe_sha256=manifest["universe_sha256"], registry_sha256=expected["registry_sha256"],
                tzdata_zone_files_sha256=manifest["tzdata"]["zone_files_sha256"])


PACK_SCOPE = "maker_core.replay.execution_manifest.verify_scored_scope"
_SCOPE_FIELDS = {"dates", "active_intervals", "markets", "replay_config", "bootstrap_replicates", "bootstrap_seed"}
# The v1 ``replay_config`` fields a v2 run is scored under (``kernel.V2Config`` has the same names): caps, cash, the
# hazard scalar and the book-gap limit. ``policy``, ``fill_bound`` and ``clock_pulls`` are per pass (the report runs
# every policy and bound); ``max_events``/``max_outputs`` are resource ceilings, which refuse a run, never re-score it.
SCOPE_CONFIG_FIELDS = ("initial_cash", "band_cap", "order_cap", "wallet_cap", "event_cap", "factor_cap",
                       "hazard_per_minute", "max_book_gap_seconds")


def _scope_windows(plan, manifest):
    """Every plan day is declared, with exactly ``apply_manifest``'s windows for that day (an empty map for a day
    with no active interval, such as the settlement-only day)."""
    from maker_core.replay.v2.lockstep import windows_of
    intervals = manifest["active_intervals"]
    keys = {"date", "condition_id", "start", "end"}
    if not isinstance(intervals, list) or not all(isinstance(w, Mapping) and keys <= set(w) for w in intervals):
        raise BundleError("run_binding_pack_manifest_invalid")
    for day in plan.days:
        iso = day.day.isoformat()
        try:
            expected = windows_of(day.conditions, tuple((w["condition_id"], timestamp(w["start"]), timestamp(w["end"]))
                                                        for w in intervals if w["date"] == iso))
        except (BundleError, TypeError, ValueError):
            raise BundleError("run_binding_pack_manifest_invalid") from None
        if day.declared is not True or not isinstance(day.windows, Mapping) or dict(day.windows) != dict(expected):
            raise BundleError("run_binding_pack_windows_mismatch")


def _scope_markets(plan, manifest):
    """The quote-day markets of the plan are the manifest's ``markets`` (as ``build_manifest`` derives them)."""
    quote = manifest["dates"]
    markets = sorted({c.market_id for d in plan.days if d.day.isoformat() in quote for c in d.conditions})
    if not isinstance(manifest["markets"], list) or markets != manifest["markets"]:
        raise BundleError("run_binding_pack_markets_mismatch")


def _scope_config(config, manifest):
    """The report configuration equals the manifest's ``replay_config`` on ``SCOPE_CONFIG_FIELDS``, both normalised
    through ``V2Config`` (so ``"100"`` and ``Decimal(100)`` agree; a hazard of 0.5 against 1.0 does not)."""
    from maker_core.replay.v2.kernel import V2Config
    replay_config = manifest["replay_config"]
    if not isinstance(replay_config, Mapping) or not set(SCOPE_CONFIG_FIELDS) <= set(replay_config):
        raise BundleError("run_binding_pack_manifest_invalid")
    try:
        expected = V2Config(**{name: replay_config[name] for name in SCOPE_CONFIG_FIELDS})
    except (BundleError, TypeError, ValueError, ArithmeticError):
        raise BundleError("run_binding_pack_manifest_invalid") from None
    if any(type(getattr(config, name, None)) is bool
           or plain(getattr(config, name, None)) != plain(getattr(expected, name)) for name in SCOPE_CONFIG_FIELDS):
        raise BundleError("run_binding_pack_config_mismatch")


def _scope_bootstrap(replicates, seed, manifest):
    if (type(replicates) is not int or type(seed) is not int or replicates != manifest["bootstrap_replicates"]
            or seed != manifest["bootstrap_seed"]):
        raise BundleError("run_binding_pack_bootstrap_mismatch")


def _scope_registration(registration_hash, manifest_sha256):
    if registration_hash is not None and registration_hash != manifest_sha256:
        raise BundleError("run_binding_pack_registration_mismatch")


def verify_scored_scope(plan, config, *, manifest, replicates, seed, registration_hash, manifest_sha256):
    """The scope of a scored v2 report is the enrolled manifest's (R155 defender-2 D1), as v1's runner binds it
    (``authorization.bind_scope`` and ``ReplayConfig(**registration["replay_config"])``). Called by
    ``report.build_report`` after ``verify_scored_pack`` accepted ``manifest``; refuses unless
    - every plan day is declared and its windows are exactly the manifest's ``active_intervals`` for that day, as
      ``apply_manifest`` projects them (``run_binding_pack_windows_mismatch``): envelope windows, empty windows or
      any other interval set refuse;
    - the plan's quote-day markets are the manifest's ``markets`` (``run_binding_pack_markets_mismatch``);
    - ``config`` equals the manifest's ``replay_config`` on ``SCOPE_CONFIG_FIELDS`` (``run_binding_pack_config_mismatch``);
    - ``replicates`` and ``seed`` are the ints ``bootstrap_replicates`` and ``bootstrap_seed``
      (``run_binding_pack_bootstrap_mismatch``);
    - ``registration_hash`` is ``None`` or ``manifest_sha256`` (``run_binding_pack_registration_mismatch``); the
      report's ``pre_registration_sha256`` is then ``manifest_sha256``, never a free value.
    A malformed scope field refuses ``run_binding_pack_manifest_invalid``. Returns the scope fields the report's
    ``pack_check`` adds: the digests of the manifest's ``active_intervals`` and ``replay_config``, and the bootstrap
    replicates and seed."""
    if not _SCOPE_FIELDS <= set(manifest):
        raise BundleError("run_binding_pack_manifest_invalid")
    _scope_windows(plan, manifest)
    _scope_markets(plan, manifest)
    _scope_config(config, manifest)
    _scope_bootstrap(replicates, seed, manifest)
    _scope_registration(registration_hash, manifest_sha256)
    return dict(scope_verifier=PACK_SCOPE, active_intervals_sha256=digest(manifest["active_intervals"]),
                replay_config_sha256=digest(manifest["replay_config"]), bootstrap_replicates=replicates,
                bootstrap_seed=seed)


def verify_scored_records(replayed, *, manifest):
    """The records a scored run actually replayed are the manifest's (R155 defender-2 D2).

    ``replayed`` is ``Run.replayed``, the ``lockstep.RecordDigest`` summary of every record the run's drives read.
    The plan's ``input_hashes`` are labels copied from the loaded bundles; a ``DaySource`` or ``Bundle`` can carry
    other records under them. So the digest of the records read, ``digest([dict(r.source_hashes) ...])`` in day
    order, must equal the manifest's ``record_sources_sha256`` (``build_manifest`` writes the same shape over the
    same bundles' records): a dropped, added or re-ordered record, or one whose sources differ, refuses
    ``run_binding_pack_records_mismatch``. A run without the summary refuses ``run_binding_records_required``.
    This binds the record sequence and each record's ``source_hashes``, not its payload: a record whose payload is
    edited in memory with its ``source_hashes`` kept is not caught here (the sealed readers re-hash every payload
    against ``payload_sha256`` at load). Returns the ``pack_check`` fields: the digest and the record count."""
    if (not isinstance(replayed, Mapping) or set(replayed) != {"record_sources_sha256", "records"}
            or type(replayed["record_sources_sha256"]) is not str or type(replayed["records"]) is not int):
        raise BundleError("run_binding_records_required")
    if not isinstance(manifest.get("record_sources_sha256"), str):
        raise BundleError("run_binding_pack_manifest_invalid")
    if replayed["record_sources_sha256"] != manifest["record_sources_sha256"]:
        raise BundleError("run_binding_pack_records_mismatch")
    return dict(record_sources_sha256=replayed["record_sources_sha256"], records_replayed=replayed["records"])


def active_intervals(bundles, inventory, *, check=lambda: None):
    """Declared active intervals and the exclusion inventory (registration draft §4; owner Q2(a), 2026-10-08).

    A condition is active while all hold: the latest **captured or derived** descriptor at or before t has
    ``horizon_days`` 1 or 2 (``maker_core.replay.v2.horizon``, which replays the panel's descriptors through the
    engine's own ``day_roll.DayRoll`` with the inventory's zones, carried across the panel's days in date order);
    t is inside the bundle's envelope for the condition; t is outside 05:00-08:00 UTC; the day is a quote date and
    the target is on or before the settlement-only date. So an interval ends at the local midnight at which the
    band passes from lead 1 to lead 0, and the engine withdraws its legs there (interval end is a wake).

    Exclusions: every whole-condition exclusion as before (``settlement_only``, ``target_after_settlement_only``),
    plus each envelope run outside the clause with ``start``/``end`` and reason ``horizon_outside_1_2`` (a
    descriptor holds a lead other than 1 or 2) or ``missing_descriptor`` (no valid descriptor yet). Those minutes
    are inactive, so they are exclusions, never NO_QUOTE minutes. Exclusion takes precedence over maintenance: an
    exclusion row spans any 05:00-08:00 UTC minutes inside its run, and the maintenance split applies only to the
    eligible runs. The maintenance window stays declared by ``maintenance_utc`` and is not repeated here."""
    from maker_core.replay.v2 import horizon
    from maker_core.replay.v2.lockstep import bundle_source

    by_id = _inventory(bundles, inventory, check=check)
    bundles = sorted(bundles, key=lambda b: b.day)
    lines = horizon.timelines([bundle_source(b) for b in bundles], _zones(by_id))
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
            for low, high, reason in horizon.runs(lines.get(c.condition_id, ()), c.active_from, c.active_until):
                if reason is not None:
                    excluded.append(dict(date=bundle.day.isoformat(), condition_id=c.condition_id, reason=reason,
                                         start=low.isoformat(), end=high.isoformat()))
                    continue
                for a, b in ((low, min(high, maintenance_start)), (max(low, maintenance_end), high)):
                    if a < b:
                        windows.append(dict(date=bundle.day.isoformat(), condition_id=c.condition_id,
                                            start=a.isoformat(), end=b.isoformat()))
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
    # F5b (owner T1(a)): the manifest records the pinned tzdata block (version, IANA release, ``tzpath_used=False``
    # and the sha of every inventory zone file, ``bundle.tzdata_binding``) its intervals were derived with.
    # ``verify_manifest`` rebuilds the manifest, so a manifest built under another tzdata or other zone bytes
    # refuses (``tzdata_version_unpinned`` or ``execution_manifest_binding_mismatch``).
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
                maintenance_utc=["05:00", "08:00"], tzdata=tzdata_binding(r["local_timezone"] for r in inventory),
                input_hashes={b.day.isoformat(): dict(b.input_hashes) for b in bundles},
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
