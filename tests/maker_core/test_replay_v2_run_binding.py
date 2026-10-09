"""Owner T1(a), T2(a) and T3(a) (2026-10-09): pinned tzdata, the v2 run binding, and the required zone registry.

Fictional fixtures only (2026-09-27, 2026-09-28 and 2026-11-20; nothing captured is read). Each owner ruling has a
named mutant that one test here kills; the mutant tests apply the mutant with ``monkeypatch`` and expect the guarding
test to fail.

Guards: owner decisions T1(a) (tzdata pinned, scored runs use only it, version and zone-file sha bound), T2(a)
(refresh flag, zone map sha and its source bound into the run digest) and T3(a) (``registered=`` required in
``execution_manifest.market_time_zones``), registration C13, Delta Defender c70581325 notes N2 and N3, and
GATELOGIC-T1T3 Defender 4f3ca7c03 findings F1-F6 (binding tied to the run, full registry source, tzdata block
recomputed from the one installed package, zone-map snapshot, mutants M1cov/M2ver/M3any), and GATELOGIC-T1T3
delta review 1 at a66a5b492 (findings 1-3: mutants D2markets/D4hashes/D6fields, the driven zone map bound into the
run inputs, the package-directory tzdata check for a sourceless install).
"""
from dataclasses import replace
from datetime import date, datetime, timezone
import importlib.metadata
import importlib.resources
import inspect
from pathlib import Path
import tomllib
import zoneinfo

import pytest

from maker_core.evidence.journal import digest
from maker_core.replay import bundle
from maker_core.replay.bundle import TZDATA_VERSION, BundleError, RegisteredZones, sha256, time_zone
from maker_core.replay.v2 import pipeline
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import run_plan
from maker_core.replay.v2.pipeline import (RUN_BINDING_FORMAT, run_binding, run_inputs, run_passes,
                                           verify_run_binding)
from maker_core.replay.v2.report import build_report
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, materialize

from .test_replay_v2_day_roll import REGISTERED, zone_pack

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 9, 27)
CONFIG = V2Config(hazard_per_minute=.001, debug=True)
SUMMER = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def day_source(day=DAY, provenance="synthetic", trades=200):
    """A fictional dense day; ``provenance="sealed"`` makes ``build_report`` treat it as a scored replay day."""
    source, _ = materialize(DenseDay(day, union=4, trades=trades, minutes=10))
    return replace(source, plan=replace(source.plan, provenance=provenance))


def small_run(time_zones=FIXTURE_ZONES, provenance="synthetic", day=DAY, trades=200):
    return run_passes([day_source(day, provenance, trades)], CONFIG, time_zones=time_zones)


def registered(zones):
    """A hand-built ``RegisteredZones`` (the class binds provenance; it does not stop forging, as documented)."""
    return RegisteredZones(zones, dict(builder="maker_core.replay.execution_manifest.market_time_zones",
                                       registry_checked=True, inventory_sha256="0" * 64, registry_sha256="1" * 64))


def scored(run):
    """The same run relabelled as non-synthetic after binding (the binding is NOT recomputed)."""
    days = tuple(replace(d, provenance="sealed") for d in run.plan.days)
    return replace(run, plan=replace(run.plan, days=days))


@pytest.fixture
def unpinned(monkeypatch):
    """An installed tzdata of another release: its metadata and its module ``__version__`` both say 2099.1."""
    import tzdata
    real = importlib.metadata.version
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2099.1" if name == "tzdata" else real(name))
    monkeypatch.setattr(tzdata, "__version__", "2099.1")


def rebind(binding, **changes):
    body = {k: v for k, v in binding.items() if k != "sha256"}
    body.update(changes)
    return dict(body, sha256=digest(body))


def forge(run, time_zones, config=CONFIG, **changes):
    """``run`` relabelled as driven with ``time_zones``, its binding rewritten to match with EVERY digest recomputed
    (zone map, its sha, source, tzdata block, run inputs): a deliberate forgery, used to reach one later guard."""
    pairs = [[m, z] for m, z in sorted(dict(time_zones).items())]
    source = dict(time_zones.source) if isinstance(time_zones, RegisteredZones) else dict(pipeline.CALLER_ZONE_MAP)
    body = dict(time_zones=dict(pairs), time_zones_sha256=digest(pairs), time_zones_source=source,
                tzdata=bundle.tzdata_binding(z for _, z in pairs),
                run_inputs_sha256=digest(run_inputs(run.plan, run.markets, config, time_zones)))
    body.update(changes)
    return replace(run, binding=rebind(run.binding, **body), time_zones=time_zones)


# -- T1(a): tzdata is pinned, loaded only from the package, and bound ------------------------------------------
def test_tzdata_pin_is_declared_in_both_dependency_files():
    pin = "tzdata==" + TZDATA_VERSION
    assert pin in tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    assert pin in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def hostile_tzpath(tmp_path):
    """A platform TZPATH whose ``Europe/London`` is really UTC and which lists an extra zone ``Mars/Olympus_Mons``."""
    utc = importlib.resources.files("tzdata").joinpath("zoneinfo", "UTC").read_bytes()
    for name in ("Europe/London", "Mars/Olympus_Mons"):
        path = tmp_path.joinpath(*name.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(utc)
    saved = zoneinfo.TZPATH
    zoneinfo.reset_tzpath(to=[str(tmp_path)])
    zoneinfo.ZoneInfo.clear_cache()
    bundle.pinned_zone.cache_clear()
    bundle._zone_names.cache_clear()
    try:
        assert zoneinfo.ZoneInfo.no_cache("Europe/London").utcoffset(SUMMER).total_seconds() == 0  # the trap is live
        yield
    finally:
        zoneinfo.reset_tzpath(to=saved)
        zoneinfo.ZoneInfo.clear_cache()
        bundle.pinned_zone.cache_clear()
        bundle._zone_names.cache_clear()


def test_zones_come_only_from_the_pinned_tzdata_not_the_platform_tzpath(hostile_tzpath):
    assert time_zone("Europe/London").utcoffset(SUMMER).total_seconds() == 3600  # BST from tzdata, not the trap
    with pytest.raises(BundleError, match="unknown_time_zone"):
        time_zone("Mars/Olympus_Mons")  # listed by the platform TZPATH, not by the pinned tzdata


def test_mutant_platform_tzpath_lookup_is_caught(hostile_tzpath, monkeypatch):
    """Mutant T1-M1 ``platform_tzpath``: ``pinned_zone`` goes back to ``ZoneInfo(name)`` (TZPATH first)."""
    # ``hostile_tzpath`` is set up first so ``monkeypatch`` restores ``pinned_zone`` before its teardown clears caches.
    monkeypatch.setattr(bundle, "pinned_zone", zoneinfo.ZoneInfo)
    with pytest.raises(AssertionError):
        test_zones_come_only_from_the_pinned_tzdata_not_the_platform_tzpath(None)


def test_run_binding_carries_the_tzdata_version_and_the_zone_file_shas():
    tz = small_run().binding["tzdata"]
    names = sorted(set(FIXTURE_ZONES.values()))
    files = [[n, sha256(importlib.resources.files("tzdata").joinpath("zoneinfo", *n.split("/")).read_bytes())]
             for n in names]
    import tzdata
    assert tz == dict(package="tzdata", version=TZDATA_VERSION, iana_version=tzdata.IANA_VERSION, tzpath_used=False,
                      zone_files=files, zone_files_sha256=bundle.sha256(bundle.canonical_bytes(files)))


def test_an_unpinned_tzdata_is_refused_before_any_engine_runs(unpinned):
    with pytest.raises(BundleError, match="tzdata_version_unpinned"):
        small_run()
    with pytest.raises(BundleError, match="tzdata_version_unpinned"):
        bundle.tzdata_binding(["UTC"])


def test_mutant_unchecked_tzdata_version_is_caught(unpinned, monkeypatch):
    """Mutant T1-M3 ``tzdata_unchecked``: the binding records whatever tzdata is installed instead of refusing."""
    original = bundle.tzdata_binding

    def mutant(names):
        saved = bundle.TZDATA_VERSION
        bundle.TZDATA_VERSION = importlib.metadata.version("tzdata")
        try:
            return original(names)
        finally:
            bundle.TZDATA_VERSION = saved
    monkeypatch.setattr(bundle, "tzdata_binding", mutant)
    with pytest.raises(pytest.fail.Exception):
        test_an_unpinned_tzdata_is_refused_before_any_engine_runs(None)


# -- T2(a): refresh flag, zone map sha and its source in the run digest -----------------------------------------
def test_run_passes_binds_refresh_zone_map_and_source():
    run = small_run()
    b = run.binding
    pairs = [[m, z] for m, z in sorted(FIXTURE_ZONES.items())]
    assert b["format"] == RUN_BINDING_FORMAT and b["day_roll_refresh"] is True
    assert b["time_zones"] == dict(pairs) and b["time_zones_sha256"] == digest(pairs)
    assert b["time_zones_source"] == dict(builder="caller", registry_checked=False)
    assert b["sha256"] == digest({k: v for k, v in b.items() if k != "sha256"})
    report, _ = build_report(run, CONFIG, replicates=100)
    assert report["status"] == "FIXTURE_ONLY" and report["run_binding"] == b


def test_the_binding_changes_no_decision_or_pnl_digest():
    """Adding the binding is deliberate and moves only ``run_binding``; the pass digests are unchanged."""
    caller, bound = small_run(), small_run(registered(FIXTURE_ZONES))
    assert caller.binding["sha256"] != bound.binding["sha256"]
    for b in caller.passes:
        for policy in caller.passes[b]:
            one, two = caller.passes[b][policy].engine.summary(), bound.passes[b][policy].engine.summary()
            assert one["decision_sha256"] == two["decision_sha256"]
            assert one == two


def test_a_run_that_bypasses_run_passes_yields_no_report():
    run = replace(small_run(), binding=None)  # e.g. lockstep.drive with NO_REFRESH and a hand-assembled Run
    with pytest.raises(BundleError, match="run_binding_required"):
        build_report(run, CONFIG, replicates=100)


def test_a_refresh_off_binding_is_refused_even_with_a_recomputed_digest():
    run = small_run()
    with pytest.raises(BundleError, match="day_roll_refresh_required"):
        build_report(replace(run, binding=rebind(run.binding, day_roll_refresh=False)), CONFIG, replicates=100)


def test_mutant_refresh_flag_unchecked_is_caught(monkeypatch):
    """Mutant T2-M1 ``refresh_unbound``: the verifier ignores ``day_roll_refresh``."""
    original = verify_run_binding

    def mutant(run, config, *, scored):
        b = run.binding
        if isinstance(b, dict) and b.get("day_roll_refresh") is False:
            run = replace(run, binding=rebind(b, day_roll_refresh=True))
        original(run, config, scored=scored)
        return b
    monkeypatch.setattr(pipeline, "verify_run_binding", mutant)
    with pytest.raises(pytest.fail.Exception):
        test_a_refresh_off_binding_is_refused_even_with_a_recomputed_digest()


def test_a_swapped_zone_map_is_refused():
    run = small_run()
    swapped = dict(run.binding["time_zones"])
    swapped[next(iter(swapped))] = "Africa/Abidjan"
    with pytest.raises(BundleError, match="run_binding_digest_mismatch"):
        build_report(replace(run, binding=rebind(run.binding, time_zones=swapped)), CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_digest_mismatch"):
        build_report(replace(run, binding=dict(run.binding, time_zones=swapped)), CONFIG, replicates=100)


def test_a_scored_report_refuses_a_hand_made_zone_map():
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(small_run(provenance="sealed"), CONFIG, replicates=100)
    report, _ = build_report(small_run(registered(FIXTURE_ZONES), "sealed"), CONFIG, replicates=100)
    assert report["status"] == "PRE_REGISTERED_REPLAY"
    assert report["run_binding"]["time_zones_source"]["registry_checked"] is True


def test_mutant_scored_report_accepting_a_caller_map_is_caught(monkeypatch):
    """Mutant T2-M2 ``caller_map_scored``: the report verifies the binding as if it were a fixture run."""
    original = verify_run_binding
    monkeypatch.setattr(pipeline, "verify_run_binding",
                        lambda run, config, *, scored: original(run, config, scored=False))
    with pytest.raises(pytest.fail.Exception):
        test_a_scored_report_refuses_a_hand_made_zone_map()


def test_market_time_zones_records_its_source_for_the_binding(tmp_path):
    from maker_core.replay.execution_manifest import ZONE_MAP_BUILDER, market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    zones = market_time_zones(bundles, inventory, registered=REGISTERED)
    assert isinstance(zones, RegisteredZones) and dict(zones) == {"a": "Europe/London"}
    assert dict(zones.source) == dict(builder=ZONE_MAP_BUILDER, registry_checked=True,
                                      inventory_sha256=digest(inventory), registry_sha256=digest(dict(REGISTERED)))
    plan = run_plan([day_source()])
    markets = {c.condition_id: "a" for day in plan.days for c in day.conditions}
    assert run_binding(zones, plan, markets, CONFIG)["time_zones_source"] == dict(zones.source)


# -- T3(a): ``registered=`` is required and fails closed ---------------------------------------------------------
def test_registered_is_a_required_keyword_and_none_fails_closed(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    parameter = inspect.signature(market_time_zones).parameters["registered"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Parameter.empty
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    with pytest.raises(TypeError):
        market_time_zones(bundles, inventory)
    for value in (None, [("a", "Europe/London")], "a"):
        with pytest.raises(BundleError, match="market_time_zone_registry_required"):
            market_time_zones(bundles, inventory, registered=value)


def test_mutant_optional_registry_is_caught(monkeypatch, tmp_path):
    """Mutant T3-M1 ``registered_optional``: ``registered=None`` by default, and a missing registry skips the check."""
    from maker_core.replay import execution_manifest
    original = execution_manifest.market_time_zones

    def mutant(bundles, inventory, *, registered=None, check=lambda: None):
        if not isinstance(registered, dict):
            registered = {r["market_id"]: r["local_timezone"] for r in inventory}  # no registry: check skipped
        return original(bundles, inventory, registered=registered, check=check)
    monkeypatch.setattr(execution_manifest, "market_time_zones", mutant)
    with pytest.raises(AssertionError):
        test_registered_is_a_required_keyword_and_none_fails_closed(tmp_path)


# -- Defender 4f3ca7c03 finding 6: the three surviving verifier mutants ------------------------------------------
def test_a_binding_without_one_of_the_run_markets_is_refused():
    """Kills M1cov (the verifier's market-coverage check deleted): a fully consistent binding that drops a market."""
    run = small_run()
    dropped = sorted(set(run.markets.values()))[0]
    zones = {m: z for m, z in run.binding["time_zones"].items() if m != dropped}
    with pytest.raises(BundleError, match="market_time_zone_unknown"):
        build_report(forge(run, zones), CONFIG, replicates=100)


def test_a_report_refuses_a_binding_recorded_under_another_tzdata_version():
    """Kills M2ver (the report-time version check deleted): the refusal is the version code, at ``build_report``."""
    run = small_run(registered(FIXTURE_ZONES), "sealed")
    forged = rebind(run.binding, tzdata=dict(run.binding["tzdata"], version="2099.1"))
    with pytest.raises(BundleError, match="tzdata_version_unpinned"):
        build_report(replace(run, binding=forged), CONFIG, replicates=100)


def test_a_plan_with_any_sealed_day_is_scored():
    """Kills M3any (``all`` -> ``any`` in the fixture test): one synthetic and one sealed day is a scored report."""
    sources = [day_source(DAY), day_source(date(2026, 9, 28), "sealed")]
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(run_passes(sources, CONFIG, time_zones=FIXTURE_ZONES), CONFIG, replicates=100)
    report, _ = build_report(run_passes(sources, CONFIG, time_zones=registered(FIXTURE_ZONES)), CONFIG, replicates=100)
    assert report["status"] == "PRE_REGISTERED_REPLAY"


# -- Defender F1: the binding belongs to this run ---------------------------------------------------------------
def test_a_binding_copied_from_another_run_is_refused():
    donor = small_run(registered(FIXTURE_ZONES), "sealed", day=date(2026, 11, 20), trades=50)
    victim = small_run(provenance="sealed")
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(victim, CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(victim, binding=donor.binding), CONFIG, replicates=100)
    report, _ = build_report(donor, CONFIG, replicates=100)  # the donor's own run still reports
    assert report["status"] == "PRE_REGISTERED_REPLAY"


def test_a_binding_is_tied_to_the_plan_provenance_and_the_report_config():
    run = small_run(registered(FIXTURE_ZONES))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(scored(run), CONFIG, replicates=100)  # relabelled sealed after binding
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(run, replace(CONFIG, hazard_per_minute=.002), replicates=100)
    report, _ = build_report(run, replace(CONFIG, debug=False), replicates=100)  # debug is not a report setting
    assert report["status"] == "FIXTURE_ONLY"


# -- Defender F2: a scored report needs the full registry source ------------------------------------------------
@pytest.mark.parametrize("source", [
    {"registry_checked": True},
    dict(builder="caller", registry_checked=True, inventory_sha256="0" * 64, registry_sha256="1" * 64),
    dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked=True),
    dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked=True, inventory_sha256="0" * 64),
    dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked=True, inventory_sha256="x" * 64, registry_sha256="1" * 64),
    dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked="yes", inventory_sha256="0" * 64, registry_sha256="1" * 64),
    dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked=True, inventory_sha256="0" * 64, registry_sha256="1" * 64,
         extra=1),
])
def test_a_scored_report_refuses_an_incomplete_or_rewritten_source(source):
    forged = small_run(RegisteredZones(FIXTURE_ZONES, source), "sealed")  # bound as given, digests consistent
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(forged, CONFIG, replicates=100)
    caller = small_run(provenance="sealed")  # the caller map's source rewritten, every digest recomputed
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(forge(caller, RegisteredZones(FIXTURE_ZONES, source)), CONFIG, replicates=100)


def test_the_execution_manifest_source_is_accepted_for_a_scored_report(tmp_path):
    from maker_core.replay.execution_manifest import market_time_zones
    bundles, inventory = zone_pack(tmp_path, ["Europe/London"])
    source = dict(market_time_zones(bundles, inventory, registered=REGISTERED).source)
    report, _ = build_report(small_run(RegisteredZones(FIXTURE_ZONES, source), "sealed"), CONFIG, replicates=100)
    assert report["status"] == "PRE_REGISTERED_REPLAY" and report["run_binding"]["time_zones_source"] == source


# -- Defender F3/F5: the tzdata block is recomputed at report time, from the one installed package ---------------
@pytest.mark.parametrize("change", [
    dict(zone_files=[["X", "0" * 64]]), dict(zone_files_sha256="f" * 64), dict(iana_version="1999z"),
    dict(tzpath_used=True), dict(package="pytz"),
])
def test_a_forged_tzdata_block_is_refused_at_report_time(change):
    run = small_run()
    forged = rebind(run.binding, tzdata=dict(run.binding["tzdata"], **change))
    with pytest.raises(BundleError, match="run_binding_tzdata_mismatch"):
        build_report(replace(run, binding=forged), CONFIG, replicates=100)


def test_a_zone_file_sha_is_recomputed_from_the_loaded_bytes(monkeypatch):
    """The report recomputes each zone-file sha from the bytes this process loads, not from the binding."""
    run = small_run()
    real = bundle.zone_file_bytes
    monkeypatch.setattr(bundle, "zone_file_bytes", lambda name: real(name) + b"\0")
    with pytest.raises(BundleError, match="run_binding_tzdata_mismatch"):
        build_report(run, CONFIG, replicates=100)


def test_a_tzdata_module_whose_version_differs_from_its_metadata_is_refused(monkeypatch):
    run = small_run()
    import tzdata
    monkeypatch.setattr(tzdata, "__version__", "2026.2")
    with pytest.raises(BundleError, match="tzdata_package_mismatch"):
        bundle.tzdata_binding(["UTC"])
    with pytest.raises(BundleError, match="tzdata_package_mismatch"):
        build_report(run, CONFIG, replicates=100)


def test_a_shadowing_tzdata_package_is_refused(tmp_path, monkeypatch):
    """A ``tzdata`` directory earlier on ``sys.path`` (no dist-info) that claims the pinned version: its file is not
    the installed distribution's, so neither the binding nor a zone load accepts its bytes (London as UTC here)."""
    import sys
    real = importlib.resources.files("tzdata")
    shadow = tmp_path / "tzdata"
    (shadow / "zoneinfo" / "Europe").mkdir(parents=True)
    (shadow / "__init__.py").write_text('IANA_VERSION = "fake"\n__version__ = "%s"\n' % TZDATA_VERSION)
    (shadow / "zones").write_text("Europe/London\nUTC\n")
    utc = real.joinpath("zoneinfo", "UTC").read_bytes()
    (shadow / "zoneinfo" / "Europe" / "London").write_bytes(utc)
    (shadow / "zoneinfo" / "UTC").write_bytes(utc)
    caches = (bundle._zone_names, bundle.zone_file_bytes, bundle.pinned_zone)
    monkeypatch.delitem(sys.modules, "tzdata")
    monkeypatch.syspath_prepend(str(tmp_path))
    for cache in caches:
        cache.cache_clear()
    try:
        with pytest.raises(BundleError, match="tzdata_package_mismatch"):
            bundle.tzdata_binding(["Europe/London"])
        with pytest.raises(BundleError, match="tzdata_package_mismatch"):
            time_zone("Europe/London")
    finally:
        for cache in caches:
            cache.cache_clear()


# -- Defender F4: one snapshot of the zone map is bound and driven -----------------------------------------------
def test_run_passes_binds_and_drives_one_snapshot_of_the_zone_map(monkeypatch):
    zones = dict(FIXTURE_ZONES)
    first = next(iter(zones))
    seen = []
    real = pipeline.drive

    def spy(sources, engines, *, time_zones, **kw):
        seen.append(time_zones)
        return real(sources, engines, time_zones=time_zones, **kw)

    def progress(*_):
        zones[first] = "Pacific/Kiritimati"
    monkeypatch.setattr(pipeline, "drive", spy)
    run = run_passes([day_source()], CONFIG, time_zones=zones, progress=progress)
    assert zones[first] == "Pacific/Kiritimati" and len(seen) >= 2
    assert run.binding["time_zones"] == dict(FIXTURE_ZONES)
    assert all(z is seen[0] and dict(z) == dict(FIXTURE_ZONES) for z in seen)
    with pytest.raises(TypeError):
        seen[0][first] = "UTC"


# -- Delta review 1 finding 1: every run input is bound (mutants D2markets, D4hashes, D6fields) -----------------
def _other_bound_market(run, condition):
    return next(m for m in sorted(run.binding["time_zones"]) if m != run.markets[condition])


def test_a_condition_remapped_to_another_bound_market_after_binding_is_refused():
    """Kills D2markets (``run_inputs`` drops the condition -> market map): only one condition's market changes, to
    another market the bound zone map covers."""
    run = small_run(registered(FIXTURE_ZONES))
    condition = sorted(run.markets)[0]
    markets = {**run.markets, condition: _other_bound_market(run, condition)}
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(run, markets=markets), CONFIG, replicates=100)
    report, _ = build_report(run, CONFIG, replicates=100)
    assert report["status"] == "FIXTURE_ONLY"


def test_a_run_whose_markets_change_after_binding_is_refused():
    """A condition dropped from ``run.markets`` after binding (every market left is still covered by the map)."""
    run = small_run(registered(FIXTURE_ZONES))
    markets = dict(run.markets)
    markets.pop(sorted(markets)[-1])
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(run, markets=markets), CONFIG, replicates=100)


def test_a_plan_day_whose_input_hashes_change_after_binding_is_refused():
    """Kills D4hashes (``run_inputs`` drops ``input_hashes``): only one day's input hashes change."""
    run = small_run(registered(FIXTURE_ZONES), "sealed")
    day = run.plan.days[0]
    hashes = dict(day.input_hashes)
    assert hashes, "the fixture day must bind input hashes"
    key = sorted(hashes)[0]
    hashes[key] = "e" * 64 if hashes[key] == "f" * 64 else "f" * 64
    plan = replace(run.plan, days=(replace(day, input_hashes=hashes),) + tuple(run.plan.days[1:]))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(run, plan=plan), CONFIG, replicates=100)
    report, _ = build_report(run, CONFIG, replicates=100)
    assert report["status"] == "PRE_REGISTERED_REPLAY"


def test_a_binding_with_an_extra_or_missing_field_is_refused():
    """Kills D6fields (the exact ``BINDING_FIELDS`` check deleted): the outer sha is recomputed over the change."""
    run = small_run()
    with pytest.raises(BundleError, match="run_binding_required"):
        build_report(replace(run, binding=rebind(run.binding, extra=1)), CONFIG, replicates=100)
    short = {k: v for k, v in run.binding.items() if k not in ("day_roll_refresh", "sha256")}
    with pytest.raises(BundleError, match="run_binding_required"):
        build_report(replace(run, binding=dict(short, sha256=digest(short))), CONFIG, replicates=100)


# -- Delta review 1 finding 2: the zone map the run drove with is on ``Run`` and in the run inputs ---------------
KIRITIMATI = {market: "Pacific/Kiritimati" for market in FIXTURE_ZONES}


def test_run_keeps_the_snapshot_it_drove_with(monkeypatch):
    seen = []
    real = pipeline.drive

    def spy(sources, engines, *, time_zones, **kw):
        seen.append(time_zones)
        return real(sources, engines, time_zones=time_zones, **kw)
    monkeypatch.setattr(pipeline, "drive", spy)
    run = run_passes([day_source()], CONFIG, time_zones=registered(FIXTURE_ZONES))
    assert seen and all(z is run.time_zones for z in seen)
    assert isinstance(run.time_zones, RegisteredZones) and dict(run.time_zones) == dict(FIXTURE_ZONES)
    assert run.binding["run_inputs_sha256"] == digest(run_inputs(run.plan, run.markets, CONFIG, run.time_zones))


def test_a_binding_grafted_from_a_same_inputs_run_with_another_zone_map_is_refused():
    """The delta reviewer's copy-binding scenario: run B (same sealed day, markets and config as run A) is driven
    with a hand-made map. On its own it refuses as unregistered; with A's registered binding grafted on it must not
    become a PRE_REGISTERED_REPLAY."""
    a = small_run(registered(FIXTURE_ZONES), "sealed")
    b = small_run(KIRITIMATI, "sealed")
    assert run_inputs(a.plan, a.markets, CONFIG, {}) == run_inputs(b.plan, b.markets, CONFIG, {})  # same inputs
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(b, CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(b, binding=a.binding), CONFIG, replicates=100)
    report, _ = build_report(a, CONFIG, replicates=100)
    assert report["status"] == "PRE_REGISTERED_REPLAY"


def test_a_registered_run_driven_with_another_map_cannot_keep_its_binding():
    """The graft the other way round: A's binding stays while ``Run.time_zones`` is another map, or the same zones
    under another registry source."""
    a = small_run(registered(FIXTURE_ZONES), "sealed")
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(a, time_zones=registered(KIRITIMATI)), CONFIG, replicates=100)
    other_source = RegisteredZones(FIXTURE_ZONES, dict(a.time_zones.source, inventory_sha256="2" * 64))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(a, time_zones=other_source), CONFIG, replicates=100)


def test_the_binding_map_must_be_the_driven_map_even_with_every_binding_digest_recomputed():
    """Only the binding's map is rewritten (its sha, tzdata block and outer sha recomputed; run inputs kept): the
    driven map on ``Run`` still disagrees, so the report refuses. Kills dropping the direct map comparison."""
    run = small_run()
    pairs = [[m, z] for m, z in sorted(KIRITIMATI.items())]
    forged = rebind(run.binding, time_zones=dict(pairs), time_zones_sha256=digest(pairs),
                    tzdata=bundle.tzdata_binding(KIRITIMATI.values()))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(run, binding=forged), CONFIG, replicates=100)


def test_the_run_inputs_digest_covers_the_driven_map():
    """``Run.time_zones`` and the binding's map are relabelled consistently, but ``run_inputs_sha256`` is the
    original run's: the run-input digest must still refuse. Kills dropping the map from ``run_inputs``."""
    run = small_run()
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(forge(run, KIRITIMATI, run_inputs_sha256=run.binding["run_inputs_sha256"]), CONFIG,
                     replicates=100)
    report, _ = build_report(forge(run, KIRITIMATI), CONFIG, replicates=100)  # a full forgery passes (disclosed)
    assert report["status"] == "FIXTURE_ONLY"


def test_a_run_without_its_driven_map_yields_no_report():
    with pytest.raises(BundleError, match="run_binding_required"):
        build_report(replace(small_run(), time_zones=None), CONFIG, replicates=100)


# -- Delta review 1 finding 3: the tzdata location check compares package directories ----------------------------
def test_a_sourceless_tzdata_install_is_accepted(monkeypatch):
    """A .pyc-only (``compileall -b``) install: ``__file__`` is ``tzdata/__init__.pyc`` in the installed package
    directory. The package is accepted and the binding still builds."""
    import tzdata
    installed = Path(importlib.metadata.distribution("tzdata").locate_file("tzdata"))
    monkeypatch.setattr(tzdata, "__file__", str(installed / "__init__.pyc"))
    assert bundle.tzdata_package() is tzdata
    assert bundle.tzdata_binding(["UTC"])["version"] == TZDATA_VERSION


@pytest.mark.parametrize("where", ["sibling", "nested", "none"])
def test_a_tzdata_module_outside_the_installed_package_directory_is_refused(monkeypatch, tmp_path, where):
    """Shadowing stays refused with the directory check: a module file in another ``tzdata`` directory, in a
    subdirectory of the installed one, or with no ``__file__`` (a namespace package)."""
    import tzdata
    installed = Path(importlib.metadata.distribution("tzdata").locate_file("tzdata"))
    file = dict(sibling=str(tmp_path / "tzdata" / "__init__.pyc"),
                nested=str(installed / "zoneinfo" / "__init__.py"), none=None)[where]
    monkeypatch.setattr(tzdata, "__file__", file)
    with pytest.raises(BundleError, match="tzdata_package_mismatch"):
        bundle.tzdata_package()
