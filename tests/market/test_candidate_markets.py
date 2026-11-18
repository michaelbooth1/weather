"""Candidate market registry is inactive for every production path.

Guards: M1 new-city lane deliverable 1 (2026-10-23) -- candidate rows in
config/candidate_markets.json never reach all_specs(), capture loops,
supervisors, serving or release code; their station, zone and unit match the
venue metadata and the location registry; the KDEN Denver candidate (owner
10-23) leaves the live KBKF Denver market untouched; the METAR print-cutoff rule matches
the model's WU cutoff constants.
"""

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from weather.market import market_registry
from weather.market.candidate_markets import (
    CANDIDATE_REGISTRY_PATH,
    CandidateRegistryError,
    load_candidate_registry,
    parse_candidate_registry,
)
from weather.model.model_base import SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES
from weather.model.model_constants import INTRADAY_CUTOFF_HOURS
from weather.operations.landing_preflight_rollclass_graph import (
    EDGE_DEFERRED,
    EDGE_MODULE,
    GraphOptions,
    LOOP_ENTRY_MODULES,
    TreeView,
    static_closure_files,
)
from weather.paths import REPO_ROOT, config_path


EUROPE_FIRST = {"london", "paris", "munich", "madrid"}
CANDIDATES = EUROPE_FIRST | {"denver-kden", "seoul", "tokyo", "shanghai"}
CANDIDATE_MODULES = {
    "src/weather/market/candidate_markets.py",
    "src/weather/calibration/new_city_corpus.py",
}
PRODUCTION_ENTRIES = LOOP_ENTRY_MODULES + (
    "weather.operations.supervisor",
    "weather.operations.thin_ensure",
    "weather.operations.daily_refresh",
    "weather.market.maker_evidence_capture",
    "weather.release_serving",
)


def _payload():
    return json.loads(CANDIDATE_REGISTRY_PATH.read_text(encoding="utf-8"))


def test_checked_in_registry_is_the_europe_first_candidate_tranche():
    registry = load_candidate_registry()

    assert set(registry) == CANDIDATES
    assert {row["lifecycle"] for row in _payload()["markets"]} == {"candidate"}
    assert {item.label_source.name for item in registry.values()} == {"iem_metar"}
    assert {item.open_meteo_model for item in registry.values()} == {"gfs_seamless"}


def test_default_registry_and_slug_lookup_never_see_a_candidate():
    candidates = load_candidate_registry()
    default = market_registry.build_registry()

    assert not set(candidates) & set(default)
    assert not set(candidates) & {spec.id for spec in market_registry.all_specs()}
    assert market_registry.DEFAULT_EXTERNAL_REGISTRY_PATH != CANDIDATE_REGISTRY_PATH
    for item in candidates.values():
        resolved = market_registry.spec_for_slug(f"{item.spec.slug_prefix}-october-23-2026")
        if item.replaces_builtin:
            assert resolved is market_registry.spec_for_id(item.replaces_builtin)
        else:
            assert resolved is None
        with pytest.raises(ValueError):
            market_registry.spec_for_id(item.id)


def test_candidates_load_only_through_the_explicit_external_override():
    with_override = market_registry.build_registry(extra_path=CANDIDATE_REGISTRY_PATH)

    assert CANDIDATES <= set(with_override)
    assert {spec.id for spec in market_registry.BUILTIN_SPECS} <= set(with_override)
    assert market_registry.validate_market_registry(with_override) == []


def test_station_zone_and_unit_match_venue_metadata_and_location_registry():
    events = json.loads(config_path("location_market_events.json").read_text(encoding="utf-8"))
    locations = json.loads(config_path("locations.json").read_text(encoding="utf-8"))
    events_by_id = {row["location_id"]: row for row in events["locations"]}
    locations_by_id = {row["id"]: row for row in locations["locations"]}

    for item in load_candidate_registry().values():
        venue_ids = set()
        for event in events_by_id[item.location_id]["active_events"]:
            url = urlparse(event.get("resolution_source_url") or "")
            if url.netloc == "aviationweather.gov":
                venue_ids.update(parse_qs(url.query)["ids"])
        assert venue_ids == {item.spec.icao}, item.id
        location = locations_by_id[item.location_id]
        if item.replaces_builtin:
            assert location["timezone"] == item.spec.timezone
            assert location["market_unit"] == item.spec.display_unit
            continue
        assert location["settlement"]["station_id"] == item.spec.icao
        assert location["timezone"] == item.spec.timezone
        assert location["market_unit"] == item.spec.display_unit
        assert (location["coordinates"]["lat"], location["coordinates"]["lon"]) == (item.spec.lat, item.spec.lon)
        assert events_by_id[item.location_id]["event_slug_prefix"] == item.spec.slug_prefix


def test_kden_candidate_leaves_the_live_kbkf_denver_market_unchanged():
    kden = load_candidate_registry()["denver-kden"]
    live = market_registry.spec_for_id("denver")
    with_override = market_registry.build_registry(extra_path=CANDIDATE_REGISTRY_PATH)

    assert kden.replaces_builtin == "denver"
    assert (kden.spec.icao, live.icao) == ("KDEN", "KBKF")
    assert live == market_registry.DENVER
    assert with_override["denver"] == market_registry.DENVER
    first_slug_match = next(
        spec for spec in with_override.values() if spec.slug_prefix in "highest-temperature-in-denver-on-october-23-2026"
    )
    assert first_slug_match.id == "denver"


def test_metar_print_cutoff_rule_matches_the_wu_cutoff_constants():
    for item in load_candidate_registry().values():
        assert item.print_cutoff.cutoff_hours_local == tuple(INTRADAY_CUTOFF_HOURS)
        assert item.print_cutoff.alias_window_minutes == SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda p: p["markets"][0].update(lifecycle="active"), "lifecycle must be"),
        (lambda p: p["markets"][0].update(enabled=True), "unknown fields enabled"),
        (lambda p: p["markets"][0].update(id="nyc"), "collides with a built-in"),
        (lambda p: p["markets"][1].update(icao="KLGA"), "collides with a built-in"),
        (lambda p: p["markets"][1].update(id="london"), "duplicate id"),
        (lambda p: p["markets"][0].update(slug_prefix="highest-temperature-in-nyc-on"), "collides with a built-in"),
        (lambda p: p["markets"][4].update(replaces_builtin="nyc"), "collides with a built-in"),
        (lambda p: p["markets"][4].update(replaces_builtin="boston"), "is not a built-in market"),
        (lambda p: p["markets"][4].update(icao="KBKF"), "collides with a built-in"),
        (lambda p: p["markets"][4].update(display_unit="C"), "unit differs"),
        (lambda p: p["markets"][0].update(label_source="wu"), "unknown label_source"),
        (lambda p: p["markets"][0].update(resolution_source="nws_hourly"), "resolution_source is not listed"),
        (lambda p: p.update(status="active_registry"), "status must be"),
        (lambda p: p.update(markets=[]), "has no rows"),
    ],
)
def test_parser_refuses_activation_and_collisions(mutate, reason):
    payload = _payload()
    mutate(payload)

    with pytest.raises(CandidateRegistryError, match=reason):
        parse_candidate_registry(payload)


def _working_tree_view():
    paths = {}
    for path in (REPO_ROOT / "src").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        paths[rel] = rel
    return TreeView(label="worktree", paths=paths, reader=lambda rel: (REPO_ROOT / rel).read_bytes())


def test_no_production_entry_reaches_the_candidate_modules_even_through_deferred_imports():
    view = _working_tree_view()
    assert CANDIDATE_MODULES <= set(view.paths)
    options = GraphOptions(
        loop_entries=PRODUCTION_ENTRIES,
        include_execution_tape=True,
        edge_kinds=(EDGE_MODULE, EDGE_DEFERRED),
    )

    closure = static_closure_files(view, options)

    assert "src/weather/market/market_registry.py" in closure
    assert not CANDIDATE_MODULES & set(closure)


def test_only_candidate_modules_name_the_candidate_registry():
    pattern = re.compile(r"candidate_markets")
    allowed = CANDIDATE_MODULES
    hits = []
    for root in ("src", "app", "scripts"):
        for path in (REPO_ROOT / root).rglob("*"):
            if path.suffix not in {".py", ".ps1", ".psm1", ".cmd", ".bat"} or not path.is_file():
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in allowed:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                hits.append(rel)
    scheduled = config_path("scheduled_tasks.json").read_text(encoding="utf-8")

    assert hits == []
    assert "candidate_markets" not in scheduled
    assert "WEATHER_MARKET_REGISTRY" not in scheduled
