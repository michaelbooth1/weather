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
run inputs, the package-directory tzdata check for a sourceless install), and the R155 Fable review of 00d247bb9
(F1: a scored run's days are all sealed captures and its per-day input hashes are exactly the manifest's), and the
R155 defender-2 review of 5a7df6fb4 (D1: a scored run's windows, markets, configuration, bootstrap and registration
hash are the manifest's), and the R155 defender-3 review of 29a139083 (R1: the records replayed are bound by
identity and payload, not by count and sources).
"""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import importlib.metadata
import importlib.resources
import inspect
from pathlib import Path
import tomllib
import zoneinfo

import pytest

from maker_core.evidence.journal import canonical_bytes, digest, plain
from maker_core.replay import bundle
from maker_core.replay.engine import ReplayConfig
from maker_core.replay.bundle import TZDATA_VERSION, BundleError, RegisteredZones, sha256, time_zone
from maker_core.replay.execution_manifest import FORMAT as MANIFEST_FORMAT
from maker_core.replay.v2 import pipeline
from maker_core.replay.v2.kernel import V2Config
from maker_core.replay.v2.lockstep import record_identity, run_plan
from maker_core.replay.v2.pipeline import (RUN_BINDING_FORMAT, run_binding, run_inputs, run_passes,
                                           verify_run_binding)
from maker_core.replay.v2.report import REPORT_FORMAT, build_report
from tools.research.maker_replay_v2.dense import DenseDay
from tools.research.maker_replay_v2.sources import FIXTURE_ZONES, materialize

from .test_replay_v2_day_roll import REGISTERED, zone_pack

ROOT = Path(__file__).resolve().parents[2]
DAY = date(2026, 9, 27)
CONFIG = V2Config(hazard_per_minute=.001, debug=True)
SUMMER = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def day_source(day=DAY, provenance="synthetic", trades=200):
    """A fictional dense day; ``provenance="captured"`` makes ``build_report`` treat it as a scored replay day. A
    non-synthetic day is declared with its envelope windows, which ``manifest_for`` writes as the manifest's
    ``active_intervals`` (R155 defender-2 D1: a scored run's windows are the manifest's)."""
    source, _ = materialize(DenseDay(day, union=4, trades=trades, minutes=10))
    return replace(source, plan=replace(source.plan, provenance=provenance, declared=provenance != "synthetic"))


def small_run(time_zones=FIXTURE_ZONES, provenance="synthetic", day=DAY, trades=200):
    return run_passes([day_source(day, provenance, trades)], CONFIG, time_zones=time_zones)


def registered(zones):
    """A hand-built ``RegisteredZones`` (the class binds provenance; it does not stop forging, as documented)."""
    return RegisteredZones(zones, dict(builder="maker_core.replay.execution_manifest.market_time_zones",
                                       registry_checked=True, inventory_sha256="0" * 64, registry_sha256="1" * 64))


def manifest_for(inventory, sources=None):
    """The fields of a fictional execution manifest that the pack check reads (``verify_scored_pack``): format,
    universe, its sha (the canonical-JSON digest, which is the file sha ``pack_io.write_json`` gives), the
    tzdata record ``build_manifest`` writes, and the per-day ``input_hashes`` of ``sources`` (default: the one
    ``day_source()`` day) with the last day as ``settlement_only_date`` and the others as ``dates``, and the scope
    ``verify_scored_scope`` reads (R155 defender-2 D1): the plans' windows as ``active_intervals``, the quote-day
    markets, ``CONFIG`` as the v1 ``replay_config`` and the bootstrap these tests run (100 replicates, the default
    seed); and ``record_identity_sha256`` over the sources' records as ``build_manifest`` writes it (D2, defender-3
    R1). A real pack's verified manifest is used end to end below."""
    sources = sources or [day_source()]
    plans = [s.plan for s in sources]
    days = [p.day.isoformat() for p in plans]
    hashes = {p.day.isoformat(): dict(p.input_hashes) for p in plans}
    intervals = [dict(date=p.day.isoformat(), condition_id=cid, start=a.isoformat(), end=b.isoformat())
                 for p in plans for cid, windows in p.windows.items() for a, b in windows]
    return dict(format=MANIFEST_FORMAT, universe=inventory, universe_sha256=digest(inventory),
                tzdata=bundle.tzdata_binding(r["local_timezone"] for r in inventory),
                dates=days[:-1], settlement_only_date=days[-1], input_hashes=hashes, active_intervals=intervals,
                markets=sorted({c.market_id for p in plans[:-1] for c in p.conditions}),
                replay_config=plain(ReplayConfig(hazard_per_minute=CONFIG.hazard_per_minute)),
                bootstrap_replicates=100, bootstrap_seed=20260926,
                record_identity_sha256=digest([record_identity(r) for s in sources for r in s.records()]))


def pack(zones=FIXTURE_ZONES, registry=None, edit=lambda rows: rows, sources=None):
    """A fictional execution pack's manifest (``manifest_for``) and the domain registry, with the
    ``RegisteredZones`` that ``execution_manifest.market_time_zones`` records for them (its exact source record,
    written out here).

    One inventory row per fixture condition (every DenseDay day has the same four conditions) and one placeholder
    row for each other market of ``zones``, so the inventory's zone map is ``zones`` exactly. ``registry``
    defaults to ``zones``; ``edit`` changes the rows before the digests are taken; ``sources`` are the days whose
    input hashes, windows and records the manifest binds (``manifest_for``). Returns the zones and the
    ``build_report`` keywords."""
    rows = [dict(condition_id=c.condition_id, market_id=c.market_id, domain_id=c.domain_id,
                 target_date="2026-11-21", local_timezone=zones[c.market_id]) for c in day_source().plan.conditions]
    rows += [dict(condition_id=f"zz-placeholder-{m}", market_id=m, domain_id="fictional", target_date="2026-11-21",
                  local_timezone=z) for m, z in zones.items() if m not in {r["market_id"] for r in rows}]
    inventory = sorted(edit(rows), key=lambda r: r["condition_id"])
    registry = dict(zones if registry is None else registry)
    source = dict(builder=bundle.ZONE_MAP_BUILDER, registry_checked=True, inventory_sha256=digest(inventory),
                  registry_sha256=digest(dict(sorted(registry.items()))))
    return RegisteredZones(zones, source), dict(manifest=manifest_for(inventory, sources), registered=registry)


def scored(run):
    """The same run relabelled as non-synthetic after binding (the binding is NOT recomputed)."""
    days = tuple(replace(d, provenance="captured") for d in run.plan.days)
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
        build_report(small_run(provenance="captured"), CONFIG, replicates=100)
    zones, bound = pack()
    report, _ = build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)
    assert report["status"] == "PRE_REGISTERED_REPLAY"
    assert report["run_binding"]["time_zones_source"]["registry_checked"] is True


def test_mutant_scored_report_accepting_a_caller_map_is_caught(monkeypatch):
    """Mutant T2-M2 ``caller_map_scored``: the report verifies the binding as if it were a fixture run. The T2
    guard is now defence in depth: the pack check behind it still refuses the caller map, so the mutant is caught
    by exactly one thing, the refusal code changing from ``run_binding_unregistered_zone_map`` to
    ``run_binding_pack_required`` (Defender R155 F5: any other AssertionError would not satisfy this)."""
    original = verify_run_binding
    monkeypatch.setattr(pipeline, "verify_run_binding",
                        lambda run, config, *, scored: original(run, config, scored=False))
    with pytest.raises(AssertionError, match=r"run_binding_unregistered_zone_map(.|\n)*run_binding_pack_required"):
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
    run = small_run(registered(FIXTURE_ZONES), "captured")
    forged = rebind(run.binding, tzdata=dict(run.binding["tzdata"], version="2099.1"))
    with pytest.raises(BundleError, match="tzdata_version_unpinned"):
        build_report(replace(run, binding=forged), CONFIG, replicates=100)


def test_a_plan_with_any_captured_day_is_scored_and_every_day_must_be_captured():
    """Kills M3any (``all`` -> ``any`` in the fixture test): one synthetic and one captured day is a scored run, so
    it reaches the scored checks, and the pack check then refuses it (R155 Fable F1: a scored run's days are all
    sealed capture days). The same two days, both captured, score against a manifest binding both."""
    sources = [day_source(DAY), day_source(date(2026, 9, 28), "captured")]
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(run_passes(sources, CONFIG, time_zones=FIXTURE_ZONES), CONFIG, replicates=100)
    zones, bound = pack(sources=sources)
    with pytest.raises(BundleError, match="run_binding_pack_provenance_unsealed"):
        build_report(run_passes(sources, CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)
    sources = [day_source(DAY, "captured"), sources[1]]
    report, _ = build_report(run_passes(sources, CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)
    assert report["status"] == "PRE_REGISTERED_REPLAY"


# -- Defender F1: the binding belongs to this run ---------------------------------------------------------------
def test_a_binding_copied_from_another_run_is_refused():
    zones, bound = pack(sources=[day_source(date(2026, 11, 20), trades=50)])
    donor = small_run(zones, "captured", day=date(2026, 11, 20), trades=50)
    victim = small_run(provenance="captured")
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(victim, CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(victim, binding=donor.binding), CONFIG, replicates=100)
    report, _ = build_report(donor, CONFIG, replicates=100, **bound)  # the donor's own run still reports
    assert report["status"] == "PRE_REGISTERED_REPLAY"


def test_a_binding_is_tied_to_the_plan_provenance_and_the_report_config():
    run = small_run(registered(FIXTURE_ZONES))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(scored(run), CONFIG, replicates=100)  # relabelled captured after binding
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
    forged = small_run(RegisteredZones(FIXTURE_ZONES, source), "captured")  # bound as given, digests consistent
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(forged, CONFIG, replicates=100)
    caller = small_run(provenance="captured")  # the caller map's source rewritten, every digest recomputed
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(forge(caller, RegisteredZones(FIXTURE_ZONES, source)), CONFIG, replicates=100)


def test_the_execution_manifest_source_is_accepted_for_a_scored_report(tmp_path):
    """End to end on the fictional execution pack: ``verify_manifest`` accepts the pack's manifest, and
    ``market_time_zones`` over its bundles and universe drives a sealed run whose report verifies against that
    manifest. The run is the runner's: the declared windows (``apply_manifest``), the manifest's ``replay_config``
    and its bootstrap (R155 defender-2 D1). ``pack_check`` records the digests it bound: the manifest digest is the
    manifest file's sha, and the universe digest is both the manifest's ``universe_sha256`` (the file sha) and the
    run source's ``inventory_sha256`` (one hash). The source grafted onto another map refuses, and so does the same
    pack replayed over its bundle envelopes instead of the declared windows."""
    from maker_core.replay.execution_manifest import (PACK_CHECK, PACK_SCOPE, SCOPE_CONFIG_FIELDS, apply_manifest,
                                                      market_time_zones, verify_manifest)
    from maker_core.replay.v2.lockstep import bundle_source
    from .fixtures.execution_pack import pack as execution_pack
    doc, bundles, cb, paths, manifest_path, manifest_key = execution_pack(tmp_path)
    verified = verify_manifest(doc, bundles, cb, **paths, now=datetime(2026, 10, 15, 12, tzinfo=timezone.utc))
    registry = {"a": "UTC"}
    zones = market_time_zones(bundles, verified["universe"], registered=registry)
    source = dict(zones.source)
    config = V2Config(**{name: verified["replay_config"][name] for name in SCOPE_CONFIG_FIELDS}, debug=True)
    scope = dict(replicates=verified["bootstrap_replicates"], seed=verified["bootstrap_seed"])

    def sources_of(given):  # the fixture pack is sealed as captured (defender-2 D4): no in-memory relabel
        return [bundle_source(b) for b in given]
    assert {b.provenance for b in (*bundles, *cb)} == {"captured"}
    sources = sources_of(apply_manifest(verified, bundles))
    run = run_passes(sources, config, time_zones=zones)
    report, _ = build_report(run, config, **scope, manifest=verified, registered=registry)
    assert report["status"] == "PRE_REGISTERED_REPLAY" and report["run_binding"]["time_zones_source"] == source
    universe_file_sha = sha256(paths["inventory_path"].read_bytes())
    assert report["pack_check"] == dict(
        verifier=PACK_CHECK, manifest_format=MANIFEST_FORMAT, manifest_sha256=manifest_key, manifest_enrolled=False,
        input_hashes_sha256=digest(verified["input_hashes"]), universe_sha256=universe_file_sha,
        registry_sha256=source["registry_sha256"], tzdata_zone_files_sha256=verified["tzdata"]["zone_files_sha256"],
        scope_verifier=PACK_SCOPE, active_intervals_sha256=digest(verified["active_intervals"]),
        replay_config_sha256=digest(verified["replay_config"]), bootstrap_replicates=2000, bootstrap_seed=20260926,
        record_identity_sha256=verified["record_identity_sha256"],
        records_replayed=sum(len(b.records) for b in bundles))
    assert report["pre_registration_sha256"] == manifest_key == sha256(manifest_path.read_bytes())
    assert report["configuration"]["hazard_per_minute"] == verified["replay_config"]["hazard_per_minute"]
    assert universe_file_sha == verified["universe_sha256"] == source["inventory_sha256"]
    assert report["input_hashes"] == verified["input_hashes"] and len(verified["input_hashes"]) == 15
    with pytest.raises(BundleError, match="run_binding_zone_map_mismatch"):
        build_report(forge(run, RegisteredZones({"a": "Africa/Abidjan"}, source), config), config, **scope,
                     manifest=verified, registered=registry)
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):  # one quote day, not the pack
        build_report(run_passes(sources[:1], config, time_zones=zones), config, **scope,
                     manifest=verified, registered=registry)
    with pytest.raises(BundleError, match="run_binding_pack_windows_mismatch"):  # defender-2 P2: envelope windows
        build_report(run_passes(sources_of(bundles), config, time_zones=zones), config, **scope,
                     manifest=verified, registered=registry)
    # Defender-2 P1: the declared pack with its terms, info and outcome-view records dropped in memory, under the
    # honest labels (day, provenance, input hashes): the records replayed are not the manifest's.
    cut = [replace(b, records=tuple(r for r in b.records if r.kind not in ("terms", "info_event", "outcome_view")))
           for b in apply_manifest(verified, bundles)]
    assert sum(len(b.records) for b in cut) < sum(len(b.records) for b in bundles)
    with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
        build_report(run_passes(sources_of(cut), config, time_zones=zones), config, **scope,
                     manifest=verified, registered=registry)
    # Defender-3 P11/P13: the record count and every record's ``source_hashes`` kept (the pack's records share one),
    # with every outcome view re-priced (payload sha recomputed) or every terms record replaced by a duplicate of the
    # record before it. The identity digest differs, so both refuse.
    declared = apply_manifest(verified, bundles)
    assert len({canonical_bytes(r.source_hashes) for b in declared for r in b.records}) == 1
    for edited in (_repriced(declared, .9, rehash=True), _terms_duplicated(declared)):
        assert [len(b.records) for b in edited] == [len(b.records) for b in declared]
        with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
            build_report(run_passes(sources_of(edited), config, time_zones=zones), config, **scope,
                         manifest=verified, registered=registry)
    # Defender-3 P12: the payload edited with the sealed sha kept is refused while the run reads it.
    with pytest.raises(BundleError, match="replay_payload_hash_mismatch"):
        run_passes(sources_of(_repriced(declared, .9, rehash=False)), config, time_zones=zones)


def _reprice(record, p_yes, rehash):
    payload = plain(record.payload)
    payload["value"]["p_yes"] = p_yes
    return replace(record, payload=payload,
                   payload_sha256=sha256(canonical_bytes(payload)) if rehash else record.payload_sha256)


def _repriced(bundles, p_yes, *, rehash):
    """Every ``outcome_view`` record re-priced in memory; its ``payload_sha256`` recomputed when ``rehash``."""
    return [replace(b, records=tuple(_reprice(r, p_yes, rehash) if r.kind == "outcome_view" else r
                                     for r in b.records)) for b in bundles]


def _terms_duplicated(bundles):
    """Every ``terms`` record replaced by a duplicate of the record before it (count kept)."""
    out = []
    for b in bundles:
        records = list(b.records)
        for i, r in enumerate(records):
            if r.kind == "terms" and i:
                records[i] = records[i - 1]
        out.append(replace(b, records=tuple(records)))
    return out


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
    zones, bound = pack()
    run = small_run(zones, "captured")
    day = run.plan.days[0]
    hashes = dict(day.input_hashes)
    assert hashes, "the fixture day must bind input hashes"
    key = sorted(hashes)[0]
    hashes[key] = "e" * 64 if hashes[key] == "f" * 64 else "f" * 64
    plan = replace(run.plan, days=(replace(day, input_hashes=hashes),) + tuple(run.plan.days[1:]))
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(run, plan=plan), CONFIG, replicates=100, **bound)
    report, _ = build_report(run, CONFIG, replicates=100, **bound)
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
    zones, bound = pack()
    a = small_run(zones, "captured")
    b = small_run(KIRITIMATI, "captured")
    assert run_inputs(a.plan, a.markets, CONFIG, {}) == run_inputs(b.plan, b.markets, CONFIG, {})  # same inputs
    with pytest.raises(BundleError, match="run_binding_unregistered_zone_map"):
        build_report(b, CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_run_mismatch"):
        build_report(replace(b, binding=a.binding), CONFIG, replicates=100, **bound)
    report, _ = build_report(a, CONFIG, replicates=100, **bound)
    assert report["status"] == "PRE_REGISTERED_REPLAY"


def test_a_registered_run_driven_with_another_map_cannot_keep_its_binding():
    """The graft the other way round: A's binding stays while ``Run.time_zones`` is another map, or the same zones
    under another registry source."""
    a = small_run(registered(FIXTURE_ZONES), "captured")
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
    report, _ = build_report(forge(run, KIRITIMATI), CONFIG, replicates=100)  # a fixture forgery passes (disclosed)
    assert report["status"] == "FIXTURE_ONLY"


# -- The F2 remainder: a scored run's zone source is re-derived from the verified execution manifest's universe ---
def test_a_scored_report_needs_the_manifest_and_the_registry():
    zones, bound = pack()
    run = small_run(zones, "captured")
    for given in ({}, dict(manifest=bound["manifest"]), dict(registered=bound["registered"])):
        with pytest.raises(BundleError, match="run_binding_pack_required"):
            build_report(run, CONFIG, replicates=100, **given)
    with pytest.raises(TypeError):  # the inventory is no longer a free argument (Defender R155 F1)
        build_report(run, CONFIG, replicates=100, inventory=bound["manifest"]["universe"],
                     registered=bound["registered"])
    report, _ = build_report(small_run(), CONFIG, replicates=100)  # a fixture report does not read the pack
    assert report["status"] == "FIXTURE_ONLY" and report["pack_check"] is None
    assert report["format"] == REPORT_FORMAT == "maker_core.replay.v2.report.v0.2"


def test_a_scored_report_records_the_pack_check_and_the_digests_it_bound():
    """Defender R155 F1/F2: the report shows that the pack check ran and what it bound. ``universe_sha256`` is the
    manifest's own field, and it is the same hash as the run source's ``inventory_sha256``."""
    zones, bound = pack()
    report, _ = build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)
    manifest = bound["manifest"]
    assert report["pack_check"] == dict(
        verifier="maker_core.replay.execution_manifest.verify_scored_pack", manifest_format=MANIFEST_FORMAT,
        manifest_sha256=digest(manifest), manifest_enrolled=False,
        input_hashes_sha256=digest({DAY.isoformat(): dict(day_source().plan.input_hashes)}),
        universe_sha256=manifest["universe_sha256"],
        registry_sha256=zones.source["registry_sha256"],
        tzdata_zone_files_sha256=manifest["tzdata"]["zone_files_sha256"],
        scope_verifier="maker_core.replay.execution_manifest.verify_scored_scope",
        active_intervals_sha256=digest(manifest["active_intervals"]),
        replay_config_sha256=digest(manifest["replay_config"]), bootstrap_replicates=100, bootstrap_seed=20260926,
        record_identity_sha256=manifest["record_identity_sha256"],
        records_replayed=sum(1 for _ in day_source().records()))
    assert report["pack_check"]["universe_sha256"] == report["run_binding"]["time_zones_source"]["inventory_sha256"]
    assert report["pre_registration_sha256"] == digest(manifest)  # derived, never a free value (defender-2 D1)


def test_a_self_consistent_fake_inventory_and_registry_refuse_against_the_manifest(monkeypatch):
    """Defender R155 probes P1, P1b and P1c. The forger's run carries the honest builder record over a fake
    inventory and a fake registry that put every market in Kiritimati (P1), or the same with the honest registry
    (P1b), or over an inventory that differs from the pack's only in non-zone fields (P1c). The inventory is the
    manifest's universe, not an argument, so each refuses: P1 on the registry (the fake registry contradicts the
    manifest's universe), P1b and P1c on the source digest (the record is over another inventory).

    The residual is a forged *manifest*: ``build_report`` does not re-run ``verify_manifest``, so a caller who
    fabricates the manifest as well gets a report, but its ``pack_check.manifest_sha256`` is the fabricated
    manifest's digest, not the verified pack's, and ``manifest_enrolled`` is false (here the honest fictional
    manifest is enrolled by monkeypatch), so the substitution is visible in the report itself."""
    from maker_core.replay import approved_registrations
    _, honest = pack()
    monkeypatch.setattr(approved_registrations, "APPROVED_REGISTRATIONS",
                        {digest(honest["manifest"]): "fictional-owner"})
    zones, _ = pack()
    report, _ = build_report(small_run(zones, "captured"), CONFIG, replicates=100, **honest)
    assert report["pack_check"]["manifest_enrolled"] is True
    fake_zones, fake = pack(KIRITIMATI)                                     # P1: fake inventory + fake registry
    with pytest.raises(BundleError, match="market_time_zone_registry_mismatch"):
        build_report(small_run(fake_zones, "captured"), CONFIG, replicates=100,
                     manifest=honest["manifest"], registered=fake["registered"])
    with pytest.raises(BundleError, match="run_binding_zone_source_mismatch"):  # P1b: honest registry held fixed
        build_report(small_run(fake_zones, "captured"), CONFIG, replicates=100, **honest)
    other_zones, _ = pack(edit=lambda rows: [dict(r, domain_id="made-up", target_date="1999-01-01") for r in rows])
    with pytest.raises(BundleError, match="run_binding_zone_source_mismatch"):  # P1c
        build_report(small_run(other_zones, "captured"), CONFIG, replicates=100, **honest)
    report, _ = build_report(small_run(fake_zones, "captured"), CONFIG, replicates=100, **fake)  # forged manifest too
    assert report["pack_check"]["manifest_sha256"] == digest(fake["manifest"]) != digest(honest["manifest"])
    assert report["pack_check"]["manifest_enrolled"] is False


def test_the_manifest_must_be_an_execution_manifest_whose_universe_and_tzdata_match():
    zones, bound = pack()
    run = small_run(zones, "captured")
    manifest, registry = bound["manifest"], bound["registered"]
    for broken in ([], dict(manifest, format="maker_core.replay.execution.v1"),
                   *({k: v for k, v in manifest.items() if k != key}
                     for key in ("tzdata", "universe_sha256", "input_hashes", "dates", "settlement_only_date")),
                   dict(manifest, input_hashes=list(manifest["input_hashes"].items())),
                   dict(manifest, input_hashes={DAY.isoformat(): "0" * 64}),
                   dict(manifest, settlement_only_date=DAY), dict(manifest, owner=object())):
        with pytest.raises(BundleError, match="run_binding_pack_manifest_invalid"):
            build_report(run, CONFIG, replicates=100, manifest=broken, registered=registry)
    # Defender-3 R2: the checks read the canonical-JSON copy, so a tuple where the builder wrote a list is the same
    # content under the same digest, not another manifest.
    report, _ = build_report(run, CONFIG, replicates=100, manifest=dict(manifest, dates=tuple(manifest["dates"])),
                             registered=registry)
    assert report["pre_registration_sha256"] == digest(manifest)
    with pytest.raises(BundleError, match="run_binding_pack_universe_mismatch"):  # sha not over these rows
        build_report(run, CONFIG, replicates=100, manifest=dict(manifest, universe_sha256="0" * 64),
                     registered=registry)
    with pytest.raises(BundleError, match="run_binding_pack_universe_mismatch"):  # rows not under this sha
        build_report(run, CONFIG, replicates=100, manifest=dict(manifest, universe=manifest["universe"][1:]),
                     registered=registry)
    other = dict(manifest, tzdata=dict(manifest["tzdata"], zone_files_sha256="0" * 64))
    with pytest.raises(BundleError, match="run_binding_pack_tzdata_mismatch"):
        build_report(run, CONFIG, replicates=100, manifest=other, registered=registry)


# -- R155 Fable F1: the scored run's days and input hashes are exactly the manifest's -----------------------------
NEXT = date(2026, 9, 28)


def test_a_run_of_a_subset_of_the_manifest_days_is_refused():
    zones, bound = pack(sources=[day_source(DAY), day_source(NEXT)])
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)
    both = [day_source(DAY, "captured"), day_source(NEXT, "captured")]
    report, _ = build_report(run_passes(both, CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)
    assert report["status"] == "PRE_REGISTERED_REPLAY"
    assert report["pack_check"]["input_hashes_sha256"] == digest(bound["manifest"]["input_hashes"])


def test_a_run_of_a_superset_of_the_manifest_days_is_refused():
    zones, bound = pack()
    both = [day_source(DAY, "captured"), day_source(NEXT, "captured")]
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):
        build_report(run_passes(both, CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)


def test_one_changed_input_hash_is_refused():
    zones, bound = pack()
    manifest = bound["manifest"]
    hashes = manifest["input_hashes"][DAY.isoformat()]
    stream = sorted(hashes)[0]
    changed = dict(manifest, input_hashes={DAY.isoformat(): dict(hashes, **{stream: "0" * 64})})
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, manifest=changed,
                     registered=bound["registered"])
    extra = dict(manifest, input_hashes={DAY.isoformat(): dict(hashes, extra="0" * 64)})
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, manifest=extra,
                     registered=bound["registered"])


def test_a_re_exported_bundle_set_is_refused_with_the_same_universe():
    """The same day, conditions and universe, other bundle bytes (a re-export: the fictional source carries the
    input hashes another export of the day would have): the zone checks all pass, the input hashes do not."""
    zones, bound = pack()
    source = day_source(DAY, "captured", trades=150)
    hashes = {name: sha256(value.encode()) for name, value in source.plan.input_hashes.items()}
    source = replace(source, plan=replace(source.plan, input_hashes=hashes))
    reexport = run_passes([source], CONFIG, time_zones=zones)
    assert ({c.condition_id for c in reexport.plan.days[0].conditions}
            == {c.condition_id for c in day_source().plan.conditions})
    assert set(hashes) == set(bound["manifest"]["input_hashes"][DAY.isoformat()])
    assert hashes != bound["manifest"]["input_hashes"][DAY.isoformat()]
    with pytest.raises(BundleError, match="run_binding_pack_input_hashes_mismatch"):
        build_report(reexport, CONFIG, replicates=100, **bound)


@pytest.mark.parametrize("label", ["sealed", "Captured", "replayed", ""])
def test_a_scored_day_whose_provenance_is_not_a_sealed_capture_is_refused(label):
    zones, bound = pack()
    with pytest.raises(BundleError, match="run_binding_pack_provenance_unsealed"):
        build_report(small_run(zones, label), CONFIG, replicates=100, **bound)


def test_the_manifest_days_must_be_its_dates_and_its_settlement_day_in_order():
    zones, bound = pack(sources=[day_source(DAY), day_source(NEXT)])
    manifest = bound["manifest"]
    both = run_passes([day_source(DAY, "captured"), day_source(NEXT, "captured")], CONFIG, time_zones=zones)
    hashes = manifest["input_hashes"]
    for broken in (dict(manifest, dates=[]),
                   dict(manifest, dates=[NEXT.isoformat()], settlement_only_date=DAY.isoformat()),
                   dict(manifest, dates=[DAY.isoformat(), DAY.isoformat()]),
                   dict(manifest, input_hashes={**hashes, "2026-09-29": {}})):
        with pytest.raises(BundleError, match="run_binding_pack_days_mismatch"):
            build_report(both, CONFIG, replicates=100, manifest=broken, registered=bound["registered"])
    # Defender-3 R2: the checks read the canonical-JSON copy (sorted keys), the content the digest covers, so an
    # ``input_hashes`` mapping in another insertion order is the same manifest under the same digest.
    reordered = dict(manifest, input_hashes=dict(reversed(hashes.items())))
    assert digest(reordered) == digest(manifest)
    report, _ = build_report(both, CONFIG, replicates=100, manifest=reordered, registered=bound["registered"])
    assert report["status"] == "PRE_REGISTERED_REPLAY"


# -- R155 defender-2 D1: a scored report's scope is the manifest's -----------------------------------------------
def test_a_scored_run_whose_windows_are_not_the_manifest_intervals_is_refused():
    """Defender-2 P2: the run's day must be declared with exactly the manifest's ``active_intervals`` for it. The
    envelope (not declared), an empty interval list and one shortened interval each refuse."""
    zones, bound = pack()
    manifest = bound["manifest"]
    envelope = day_source(DAY, "captured")
    envelope = replace(envelope, plan=replace(envelope.plan, declared=False))
    with pytest.raises(BundleError, match="run_binding_pack_windows_mismatch"):
        build_report(run_passes([envelope], CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)
    run = small_run(zones, "captured")
    first = manifest["active_intervals"][0]
    shortened = dict(first, end=(datetime.fromisoformat(first["end"]) - timedelta(minutes=1)).isoformat())
    for intervals in ([], [shortened, *manifest["active_intervals"][1:]], manifest["active_intervals"][1:]):
        with pytest.raises(BundleError, match="run_binding_pack_windows_mismatch"):
            build_report(run, CONFIG, replicates=100, manifest=dict(manifest, active_intervals=intervals),
                         registered=bound["registered"])
    for broken in ({k: v for k, v in manifest.items() if k != "active_intervals"},
                   dict(manifest, active_intervals={str(i): w for i, w in enumerate(manifest["active_intervals"])}),
                   dict(manifest, active_intervals=[dict(first, start="not-a-time")])):
        with pytest.raises(BundleError, match="run_binding_pack_manifest_invalid"):
            build_report(run, CONFIG, replicates=100, manifest=broken, registered=bound["registered"])


def test_a_scored_run_under_another_configuration_is_refused():
    """Defender-2 P3: the report configuration is the manifest's ``replay_config`` (hazard, caps, book gap)."""
    zones, bound = pack()
    for other in (replace(CONFIG, hazard_per_minute=.5), replace(CONFIG, order_cap=50),
                  replace(CONFIG, max_book_gap_seconds=30)):
        with pytest.raises(BundleError, match="run_binding_pack_config_mismatch"):
            build_report(run_passes([day_source(DAY, "captured")], other, time_zones=zones), other, replicates=100,
                         **bound)
    replay_config = bound["manifest"]["replay_config"]
    for broken in ({k: v for k, v in replay_config.items() if k != "hazard_per_minute"},
                   dict(replay_config, order_cap="-1"), list(replay_config.items())):
        with pytest.raises(BundleError, match="run_binding_pack_manifest_invalid"):
            build_report(small_run(zones, "captured"), CONFIG, replicates=100,
                         manifest=dict(bound["manifest"], replay_config=broken), registered=bound["registered"])


def test_a_scored_report_under_another_bootstrap_or_registration_hash_is_refused():
    """Defender-2 P3/P4: replicates and seed are the manifest's ints, and ``registration_hash`` is either omitted or
    the manifest digest, which the report records as ``pre_registration_sha256``."""
    zones, bound = pack()
    run = small_run(zones, "captured")
    for given in (dict(replicates=2000), dict(replicates=100, seed=1), dict(replicates=100.0),
                  dict(replicates=100, seed=20260926.0)):
        with pytest.raises(BundleError, match="run_binding_pack_bootstrap_mismatch"):
            build_report(run, CONFIG, **given, **bound)
    with pytest.raises(BundleError, match="run_binding_pack_registration_mismatch"):
        build_report(run, CONFIG, replicates=100, registration_hash="f" * 64, **bound)
    report, _ = build_report(run, CONFIG, replicates=100, registration_hash=digest(bound["manifest"]), **bound)
    assert report["pre_registration_sha256"] == digest(bound["manifest"])


class _TwoFaced(dict):
    """Defender-3 P15: a ``dict`` whose stored content (what ``digest`` serialises) is the honest manifest, but whose
    ``[]`` and ``get`` answer ``forged`` values."""
    forged = {}

    def __getitem__(self, key):
        return self.forged[key] if key in self.forged else dict.__getitem__(self, key)

    def get(self, key, default=None):
        return self.forged[key] if key in self.forged else dict.get(self, key, default)


def test_a_two_faced_manifest_is_checked_on_its_digested_content():
    """Defender-3 R2/P15: a mapping that hashes as the honest manifest but answers another bootstrap, configuration
    or record digest to the checks. The checks read the canonical-JSON copy, so the off-scope run refuses, and the
    honest run scores exactly as under the plain manifest."""
    zones, bound = pack()
    manifest = bound["manifest"]
    hazard = dict(manifest["replay_config"], hazard_per_minute=.5)
    other = replace(CONFIG, hazard_per_minute=.5)
    cases = ((dict(bootstrap_seed=1, bootstrap_replicates=50), CONFIG, dict(replicates=50, seed=1),
              "run_binding_pack_bootstrap_mismatch"),
             (dict(replay_config=hazard), other, dict(replicates=100), "run_binding_pack_config_mismatch"))
    for forged, config, scope, code in cases:
        two_faced = _TwoFaced(manifest)
        two_faced.forged = forged
        assert digest(two_faced) == digest(manifest)
        assert all(two_faced[k] == v for k, v in forged.items())  # the trap is live
        run = run_passes([day_source(DAY, "captured")], config, time_zones=zones)
        with pytest.raises(BundleError, match=code):
            build_report(run, config, **scope, manifest=two_faced, registered=bound["registered"])
    run = small_run(zones, "captured")
    two_faced = _TwoFaced(manifest)
    two_faced.forged = dict(record_identity_sha256="0" * 64, input_hashes={})
    report, _ = build_report(run, CONFIG, replicates=100, manifest=two_faced, registered=bound["registered"])
    honest, _ = build_report(run, CONFIG, replicates=100, **bound)
    assert canonical_bytes(report) == canonical_bytes(honest)


def _with_days(run, days):
    """``run`` whose plan carries ``days`` as given, past ``RunPlan``'s own checks (a forged plan)."""
    plan = replace(run.plan)
    object.__setattr__(plan, "days", days)
    return replace(run, plan=plan)


def test_a_plan_with_a_repeated_day_is_refused_by_the_pack_check_not_collapsed():
    """Defender-2 N1: a repeated day used to collapse into one ``{day: hashes}`` entry and match. With every binding
    digest recomputed for the forged plan, the pack check refuses it by name."""
    from maker_core.replay.execution_manifest import verify_scored_pack
    zones, bound = pack()
    run = small_run(zones, "captured")
    day = run.plan.days[0]
    twice = forge(_with_days(run, (day, day)), zones)
    with pytest.raises(BundleError, match="run_binding_pack_duplicate_day"):
        build_report(twice, CONFIG, replicates=100, **bound)
    with pytest.raises(BundleError, match="run_binding_pack_duplicate_day"):
        verify_scored_pack(run.binding, twice.plan, run.markets, **bound)


@pytest.mark.parametrize("day", [DAY.isoformat(), datetime(2026, 9, 27, tzinfo=timezone.utc), None])
def test_a_plan_day_that_is_not_a_date_is_a_coded_refusal(day):
    """Defender-2 N2: a ``str`` (or ``datetime``, or missing) plan day refuses ``run_binding_plan_invalid`` in the
    binding check and in the pack check, never an ``AttributeError``/``TypeError``."""
    from maker_core.replay.execution_manifest import verify_scored_pack
    zones, bound = pack()
    run = small_run(zones, "captured")
    forged = _with_days(run, (replace(run.plan.days[0], day=day),))
    fixture = small_run()
    with pytest.raises(BundleError, match="run_binding_plan_invalid"):
        build_report(forged, CONFIG, replicates=100, **bound)
    with pytest.raises(BundleError, match="run_binding_plan_invalid"):  # a fixture report too
        build_report(_with_days(fixture, (replace(fixture.plan.days[0], day=day),)), CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_plan_invalid"):
        verify_scored_pack(run.binding, forged.plan, run.markets, **bound)


def test_the_record_digest_is_the_manifest_record_identity_shape():
    """``RecordDigest`` streams ``digest([record_identity(r) for r in records])``, the shape ``build_manifest``
    writes as ``record_identity_sha256``, for zero, one and many records. Defender-3 R1: the identity is the
    sequence, capture time, condition (or group), kind, payload sha and sources, not the sources alone."""
    from maker_core.replay.v2.lockstep import RecordDigest
    records = list(day_source().records()) + list(day_source(NEXT).records())
    for given in ([], records[:1], records):
        streamed = RecordDigest()
        for record in given:
            streamed.add(record)
        assert streamed.summary() == dict(record_identity_sha256=digest([record_identity(r) for r in given]),
                                          records=len(given))
    first = records[0]
    assert record_identity(first) == dict(sequence=first.sequence, captured_at=first.captured_at,
                                          condition_id=first.condition_id, kind=first.kind,
                                          payload_sha256=first.payload_sha256,
                                          source_hashes=dict(first.source_hashes))
    from maker_core.replay.bundle_v02 import GroupRecord
    group = GroupRecord(first.sequence, first.captured_at, "group-1", first.kind, first.payload,
                        first.payload_sha256, first.source_hashes)
    assert record_identity(group)["group_id"] == "group-1" and "condition_id" not in record_identity(group)


def test_the_record_digest_refuses_a_payload_that_is_not_its_sha():
    """Defender-3 R1 step 1: every record read is re-hashed against its ``payload_sha256``."""
    record = next(r for r in day_source().records() if r.kind == "outcome_view")
    edited = _reprice(record, .8, rehash=False)
    for bad in (edited, replace(record, payload_sha256="0" * 64), replace(record, payload={1: "not canonical"})):
        with pytest.raises(BundleError, match="replay_payload_hash_mismatch"):
            record_identity(bad)
    assert record_identity(_reprice(record, .8, rehash=True))["payload_sha256"] != record.payload_sha256


def _dense_edited(records, rehash):
    """Defender-3 P12b: every outcome view of the dense day re-priced to 0.8 (count and sources kept)."""
    return [_reprice(r, .8, rehash) if r.kind == "outcome_view" else r for r in records]


@pytest.mark.parametrize("rehash", [False, True])
def test_a_dense_day_with_re_priced_views_and_the_count_kept_is_refused(rehash):
    """Defender-3 P12b on DenseDay, whose records all share one ``source_hashes``: an in-memory re-price that kept
    the sealed sha refuses as the run reads it; one that recomputed the sha is another record and refuses against
    the manifest. Before the fix both scored PRE_REGISTERED_REPLAY with another band-day P&L table."""
    zones, bound = pack()
    honest = day_source(DAY, "captured")
    records = list(honest.records())
    assert len({canonical_bytes(r.source_hashes) for r in records}) == 1
    edited = _dense_edited(records, rehash)
    assert len(edited) == len(records) and edited != records
    source = replace(honest, records=lambda: iter(edited))
    if not rehash:
        with pytest.raises(BundleError, match="replay_payload_hash_mismatch"):
            run_passes([source], CONFIG, time_zones=zones)
        return
    with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
        build_report(run_passes([source], CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)


def test_a_dense_day_with_a_record_substituted_or_reordered_and_the_count_kept_is_refused():
    """Defender-3 P13 and the re-order the old docstring claimed: one record replaced by a duplicate of its
    predecessor, and two adjacent records swapped. Count and sources are kept; both refuse."""
    zones, bound = pack()
    honest = day_source(DAY, "captured")
    records = list(honest.records())
    i = next(i for i, r in enumerate(records) if i and r.kind == "terms")
    duplicated = [*records[:i], records[i - 1], *records[i + 1:]]
    j = next(j for j in range(len(records) - 1) if records[j].captured_at == records[j + 1].captured_at)
    swapped = [*records[:j], records[j + 1], records[j], *records[j + 2:]]
    for given in (duplicated, swapped):
        assert len(given) == len(records) and given != records
        source = replace(honest, records=lambda given=given: iter(given))
        with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
            build_report(run_passes([source], CONFIG, time_zones=zones), CONFIG, replicates=100, **bound)


def test_clock_rounds_that_read_re_priced_records_are_refused():
    """Defender-3 P14b: ``records()`` honest on the base drive and re-priced (sha recomputed, count and sources
    kept) on every later drive. The clock-round stability check compares identities, so it refuses."""
    honest = day_source(DAY, "captured")
    records = list(honest.records())
    edited = _dense_edited(records, True)
    calls = []

    def recs():
        calls.append(1)
        return iter(records if len(calls) == 1 else edited)
    with pytest.raises(BundleError, match="replay_records_unstable"):
        run_passes([replace(honest, records=recs)], CONFIG, time_zones=FIXTURE_ZONES)
    assert len(calls) == 2


def _replaying(source, keep):
    """``source`` with the same plan (day, provenance, input-hash labels) whose ``records()`` yields only ``keep``."""
    return replace(source, records=lambda: (r for r in source.records() if keep(r)))


def test_a_scored_run_whose_replayed_records_are_not_the_manifest_records_is_refused():
    """Defender-2 P1 on the small fixture: the honest labels over other records (one record dropped, every trade
    dropped, one record's sources changed) refuse; so does a run that carries no record digest."""
    zones, bound = pack()
    honest = day_source(DAY, "captured")
    records = list(honest.records())
    last = records[-1]
    resourced = replace(last, source_hashes={"fictional": "0" * 64})
    for source in (_replaying(honest, lambda r: r.sequence != last.sequence),
                   _replaying(honest, lambda r: r.kind != "trade"),
                   replace(honest, records=lambda: iter([*records[:-1], resourced]))):
        run = run_passes([source], CONFIG, time_zones=zones)
        assert run.replayed["record_identity_sha256"] != bound["manifest"]["record_identity_sha256"]
        with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
            build_report(run, CONFIG, replicates=100, **bound)
    run = small_run(zones, "captured")
    assert run.replayed == dict(record_identity_sha256=bound["manifest"]["record_identity_sha256"],
                                records=len(records))
    assert run.binding["records"] == run.replayed  # defender-3 R3: bound into the run binding
    for replayed in (None, {}, dict(run.replayed, records="1"), dict(run.replayed, extra=1)):
        with pytest.raises(BundleError, match="run_binding_records_mismatch"):  # Run.replayed is not the bound one
            build_report(replace(run, replayed=replayed), CONFIG, replicates=100, **bound)
        # the binding rewritten to agree, its sha recomputed: the record summary itself is malformed
        forged = replace(run, replayed=replayed, binding=rebind(run.binding, records=replayed))
        with pytest.raises(BundleError, match="run_binding_records_(mismatch|required)"):
            build_report(forged, CONFIG, replicates=100, **bound)
    with pytest.raises(BundleError, match="run_binding_pack_manifest_invalid"):
        build_report(run, CONFIG, replicates=100, registered=bound["registered"],
                     manifest={k: v for k, v in bound["manifest"].items() if k != "record_identity_sha256"})


def test_a_cut_run_carrying_an_honest_runs_record_summary_is_refused():
    """Defender-3 R3/P16: the run whose trades were cut refuses on its records; the same run with
    ``replayed`` copied from the honest run used to score, because ``Run.replayed`` was outside the binding. The
    binding now carries the record summary, so the copy refuses ``run_binding_records_mismatch``, fixture or
    scored. (Copying the honest binding as well is the disclosed recompute-everything forgery class.)"""
    zones, bound = pack()
    honest = day_source(DAY, "captured")
    run = run_passes([honest], CONFIG, time_zones=zones)
    cut = run_passes([_replaying(honest, lambda r: r.kind != "trade")], CONFIG, time_zones=zones)
    assert cut.binding["records"] != run.binding["records"]
    assert {k: v for k, v in cut.binding.items() if k not in ("records", "sha256")} == {
        k: v for k, v in run.binding.items() if k not in ("records", "sha256")}  # same inputs otherwise
    with pytest.raises(BundleError, match="run_binding_pack_records_mismatch"):
        build_report(cut, CONFIG, replicates=100, **bound)
    with pytest.raises(BundleError, match="run_binding_records_mismatch"):
        build_report(replace(cut, replayed=run.replayed), CONFIG, replicates=100, **bound)
    fixture = small_run()
    assert fixture.replayed == run.replayed  # the same dense day's records, synthetic label
    with pytest.raises(BundleError, match="run_binding_records_mismatch"):
        build_report(replace(fixture, replayed=cut.replayed), CONFIG, replicates=100)
    with pytest.raises(BundleError, match="run_binding_records_mismatch"):  # unbound: a pre-drive binding
        build_report(replace(fixture, binding=rebind(fixture.binding, records=None)), CONFIG, replicates=100)


def test_every_drive_of_a_run_must_read_the_same_records():
    """A source whose ``records()`` yields other records on a later call (a cache or pre-filter that changes between
    passes) refuses ``replay_records_unstable`` at the first matched-clock round."""
    honest = day_source(DAY, "captured")
    assert run_passes([honest], CONFIG, time_zones=FIXTURE_ZONES).trials  # the fixture has clock rounds
    count = sum(1 for _ in honest.records())
    calls = []

    def records():  # the base drive reads every record; every later drive drops the last one
        calls.append(1)
        return (r for i, r in enumerate(honest.records()) if len(calls) == 1 or i < count - 1)
    with pytest.raises(BundleError, match="replay_records_unstable"):
        run_passes([replace(honest, records=records)], CONFIG, time_zones=FIXTURE_ZONES)


def test_a_scored_run_whose_quote_markets_are_not_the_manifest_markets_is_refused():
    zones, bound = pack(sources=[day_source(DAY), day_source(NEXT)])
    both = run_passes([day_source(DAY, "captured"), day_source(NEXT, "captured")], CONFIG, time_zones=zones)
    report, _ = build_report(both, CONFIG, replicates=100, **bound)
    assert bound["manifest"]["markets"] and report["status"] == "PRE_REGISTERED_REPLAY"
    for markets in (bound["manifest"]["markets"][1:], [*bound["manifest"]["markets"], "city99"], []):
        with pytest.raises(BundleError, match="run_binding_pack_markets_mismatch"):
            build_report(both, CONFIG, replicates=100, manifest=dict(bound["manifest"], markets=markets),
                         registered=bound["registered"])


def _with_universe(rows):
    """A scored run whose honest builder record is over ``rows``, and the manifest binding exactly those rows."""
    zones, bound = pack()
    source = dict(zones.source, inventory_sha256=digest(rows))
    return small_run(RegisteredZones(FIXTURE_ZONES, source), "captured"), dict(bound, manifest=manifest_for(rows))


def test_a_malformed_unsorted_or_duplicated_universe_is_refused_on_the_report_path():
    """Defender R155 F3 (mutant MX1shape): the verify path applies the inventory shape, sort and uniqueness
    checks. A duplicate condition whose last row files it under another market must refuse as a duplicate."""
    _, bound = pack()
    rows = bound["manifest"]["universe"]
    first = rows[0]
    moved = dict(first, market_id="city01", local_timezone=FIXTURE_ZONES["city01"])
    for bad, code in ((list(reversed(rows)), "universe_not_sorted_unique"),
                      ([first, moved, *rows[1:]], "universe_not_sorted_unique"),
                      ([{k: v for k, v in first.items() if k != "domain_id"}, *rows[1:]],
                       "incomplete_universe_binding"),
                      ([], "invalid_universe_inventory")):
        run, given = _with_universe(bad)
        with pytest.raises(BundleError, match=code):
            build_report(run, CONFIG, replicates=100, **given)


def test_a_plan_condition_missing_from_the_run_markets_is_refused_with_a_code():
    """Defender R155 N1/P2: a forged run (every binding digest recomputed) whose plan keeps a condition that its
    ``markets`` and the inventory drop refuses as an inventory mismatch, before the sidecar opens."""
    base, _ = pack()
    run = small_run(base, "captured")
    dropped = sorted(run.markets)[0]
    zones, bound = pack(edit=lambda rows: [r for r in rows if r["condition_id"] != dropped])
    forged = forge(replace(run, markets={c: m for c, m in run.markets.items() if c != dropped}), zones)
    assert dropped in {c.condition_id for d in forged.plan.days for c in d.conditions}
    with pytest.raises(BundleError, match="run_binding_inventory_mismatch"):
        build_report(forged, CONFIG, replicates=100, **bound)


def test_a_registry_with_a_non_string_key_or_zone_is_refused_with_a_code():
    """Defender R155 N1/P4: not a TypeError from sorting mixed keys."""
    zones, bound = pack()
    for extra in ({7: "UTC"}, {"city99": None}):
        with pytest.raises(BundleError, match="market_time_zone_registry_invalid"):
            build_report(small_run(zones, "captured"), CONFIG, replicates=100, manifest=bound["manifest"],
                         registered={**bound["registered"], **extra})


def test_verify_registered_zones_called_directly_is_strict():
    """Defender R155 N2/P5/P6: ``registry_checked`` must be the boolean ``True`` (``1`` equals it in a dict
    comparison), and ``markets`` must be a non-empty mapping of strings that covers ``conditions``."""
    from maker_core.replay.execution_manifest import verify_registered_zones
    zones, bound = pack()
    run = small_run(zones, "captured")
    given = dict(inventory=bound["manifest"]["universe"], registered=bound["registered"])
    assert verify_registered_zones(dict(zones), dict(zones.source), run.markets, **given) == dict(zones.source)
    with pytest.raises(BundleError, match="run_binding_zone_source_mismatch"):
        verify_registered_zones(dict(zones), dict(zones.source, registry_checked=1), run.markets, **given)
    for markets, conditions in (({}, ()), (list(run.markets.items()), ()), ({1: "city00"}, ()),
                                (run.markets, ["not-a-run-condition"])):
        with pytest.raises(BundleError, match="run_binding_inventory_mismatch"):
            verify_registered_zones(dict(zones), dict(zones.source), markets, conditions=conditions, **given)


def test_a_made_up_registered_source_is_refused_against_the_pack():
    """``RegisteredZones`` constructed by hand with a well-formed but invented source (made-up digests) passes the
    integrity checks and is refused here; so is the honest builder record of another inventory or registry."""
    _, bound = pack()
    with pytest.raises(BundleError, match="run_binding_zone_source_mismatch"):
        build_report(small_run(registered(FIXTURE_ZONES), "captured"), CONFIG, replicates=100, **bound)
    other_inventory, _ = pack(edit=lambda rows: [dict(r, target_date="2026-11-22") for r in rows])
    other_registry, _ = pack(registry=dict(FIXTURE_ZONES, city99="UTC"))
    for zones in (other_inventory, other_registry):
        with pytest.raises(BundleError, match="run_binding_zone_source_mismatch"):
            build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)


def test_a_full_forgery_of_a_scored_run_with_another_map_is_refused():
    """``forge`` recomputes every binding digest and keeps the pack's honest source on another map: the integrity
    checks pass (see the fixture case above) and the pack check refuses the map."""
    zones, bound = pack()
    run = small_run(zones, "captured")
    with pytest.raises(BundleError, match="run_binding_zone_map_mismatch"):
        build_report(forge(run, RegisteredZones(KIRITIMATI, zones.source)), CONFIG, replicates=100, **bound)


def test_every_run_condition_must_be_an_inventory_row_of_its_market():
    """An honest source over an inventory that drops a run condition, or files it under another market."""
    dropped = sorted(small_run().markets)[0]
    for edit in (lambda rows: [r for r in rows if r["condition_id"] != dropped],
                 lambda rows: [dict(r, market_id="city01", local_timezone=FIXTURE_ZONES["city01"])
                               if r["condition_id"] == dropped else r for r in rows]):
        zones, bound = pack(edit=edit)
        with pytest.raises(BundleError, match="run_binding_inventory_mismatch"):
            build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)


def test_the_pack_registry_and_zone_agreement_are_re_checked():
    """The source digest binds the registry but does not check it: an inventory zone the registry names
    differently, a market missing from the registry, or a market whose rows disagree refuses with the
    ``market_time_zones`` codes."""
    zones, bound = pack(registry=dict(FIXTURE_ZONES, city00="UTC"))
    with pytest.raises(BundleError, match="market_time_zone_registry_mismatch"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)
    zones, bound = pack(registry={m: z for m, z in FIXTURE_ZONES.items() if m != "city00"})
    with pytest.raises(BundleError, match="market_time_zone_unregistered"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)
    first = sorted(small_run().markets)[0]
    zones, bound = pack(edit=lambda rows: [dict(r, local_timezone="UTC") if r["condition_id"] == first else r
                                           for r in rows])
    with pytest.raises(BundleError, match="market_time_zone_disagreement"):
        build_report(small_run(zones, "captured"), CONFIG, replicates=100, **bound)


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
