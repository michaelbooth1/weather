"""The MG-2 input bundle allow-list: stdlib-only, outcome-free, identical on host exporter and receiver.

Guards: MG-2 binding plan section 9 input transfer (docs/research/mg2-composite-binding-2026-10-25/binding-plan.md)
and master rulings 2026-10-25 (outcome-free bundle contract; allowlist_sha256 parity): no label, settlement or
price field travels.
"""
import ast
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.calibration import mg2_input_allowlist as allow

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src/weather/calibration/mg2_input_allowlist.py"
D = date(2026, 11, 2)
SHA = "8a" + "0" * 62
TZ = {"atlanta": "America/New_York", "austin": "America/Chicago", "chicago": "America/Chicago",
      "dallas": "America/Chicago", "denver": "America/Denver", "houston": "America/Chicago",
      "los-angeles": "America/Los_Angeles", "miami": "America/New_York", "nyc": "America/New_York",
      "san-francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles"}


def _host_replay_record():
    utc = "2026-11-02T19:07:00+00:00"
    return {"schema_version": 1, "snapshot_id": "s1", "captured_at_utc": utc,
            "captured_at_local": "2026-11-02T14:07:00-05:00", "event_slug": allow.slug_for("nyc", D),
            "target_date": D.isoformat(), "model_version": "v", "captured_input_hash": "c" * 64,
            "recorded_distribution": {"80-81": 1.0},
            "sources": {
                "metar": {"ok": True, "status": "fresh", "stale": False, "fetched_at": utc,
                          "data": {"rows": [{"raw": "METAR KLGA 021851Z", "temp_native": 70.0}], "station_id": "KLGA",
                                   "target_date_match": True, "report_time": utc, "raw": "x", "temp_native": 70.0}},
                "open_meteo_multimodel": {"ok": True, "fetched_at": utc, "data": {
                    "day_model_highs": {"gfs_seamless": 84.0, "ncep_hrrr_conus": 85.0}, "fetched_at": utc,
                    "target_date_match": True}},
                "wu_history": {"ok": True, "data": {"rows": [{"temp_native": 99.0}]}},
                "wu_current": {"ok": True, "data": {}}, "local_history": {"ok": True, "data": {}},
                "station_observations": {"ok": True, "data": {"rows": [],
                                                              "station_observation_source": "wu_history"}}}}


def test_allowlist_sha_is_the_canonical_contract_hash():
    blob = json.dumps(allow.contract(), sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert allow.allowlist_sha256() == hashlib.sha256(blob).hexdigest() == allow.allowlist_sha256()


def test_forbidden_set_covers_labels_prices_wu_and_every_station_surface():
    # the dev scorecard's LABELISH set (weather.reporting.scorecards.dev_scorecard_data, on the binding branch)
    labelish = {"winner", "settlement_high", "settlement_bucket", "settlement_source", "is_winner", "p_market_yes",
                "best_bid", "best_ask", "market_mid", "promotion_countable", "label_source"}
    assert labelish <= allow.FORBIDDEN_KEYS
    for key in ("wu_history", "wu_current", "local_history", "station_observations", "station",
                "station_observation_source", "recorded_distribution", "market_yes", "best_bid",
                "reanalysis_prev_high", "wu_anything", "settlement_authority"):
        assert allow.forbidden(key), key
    for key in ("metar", "rows", "temp_native", "snapshot_id", "payload_hash"):
        assert not allow.forbidden(key), key
    assert not set(allow.REPLAY_SOURCES) & allow.FORBIDDEN_KEYS


def test_forbidden_paths_are_found_at_any_depth():
    record = {"a": [{"b": {"winner": 1}}, {"wu_x": 2}], "ok": 1}
    assert allow.forbidden_paths(record) == ["a[0].b.winner", "a[1].wu_x"]


def test_markets_and_slugs_match_the_registry():
    from weather.market.market_config import event_slug_for_date
    from weather.market.market_registry import spec_for_id

    for market in allow.MARKETS:
        assert spec_for_id(market).display_unit == "F"
        assert spec_for_id(market).timezone == TZ[market]
        for day in (D, date(2026, 12, 31), date(2027, 1, 9)):
            assert allow.slug_for(market, day) == event_slug_for_date(day, market)
            assert allow.parse_slug(allow.slug_for(market, day)) == (market, day)
    assert allow.parse_slug("highest-temperature-in-toronto-on-november-2-2026") is None
    assert allow.parse_slug("highest-temperature-in-nyc-on-november-02-2026") is None
    assert allow.parse_slug("highest-temperature-in-nyc-on-february-30-2027") is None


def test_export_cut_is_midnight_ending_d_in_the_westernmost_market():
    cut = allow.export_cut_utc(D)
    assert cut == datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)  # PST, after 2026-11-01
    assert allow.export_cut_utc(date(2026, 10, 15)) == datetime(2026, 10, 16, 7, 0, tzinfo=timezone.utc)
    for market in allow.MARKETS:
        assert cut.astimezone(ZoneInfo(TZ[market])).date() > D


@pytest.mark.parametrize("rel,kind", [
    ("manifest.json", "manifest"),
    ("manifest.json.sha256", "manifest"),
    (f"snapshots/{allow.slug_for('nyc', D)}/replay_inputs.jsonl", "replay_inputs"),
    (f"snapshots/{allow.slug_for('nyc', D)}/snapshots_long.csv", "snapshots_long"),
    (f"snapshots/{allow.slug_for('nyc', D)}/features_long.csv", "features_long"),
    (f"snapshots/{allow.slug_for('seattle', date(2026, 11, 1))}/forecast_payloads.jsonl", "nbm_manifest"),
    (f"snapshots/{allow.slug_for('seattle', date(2026, 11, 3))}/forecast_payloads.jsonl", "nbm_manifest"),
    (f"prev_day/{allow.slug_for('denver', date(2026, 11, 1))}/metar_rows.jsonl", "prev_day_metar"),
    (f"forecast_payload_cas/{allow.blob_ref(SHA)}", "nbm_blob"),
])
def test_allowed_paths_classify(rel, kind):
    assert allow.classify_path(rel, D)[0] == kind


@pytest.mark.parametrize("rel", [
    f"snapshots/{allow.slug_for('nyc', D)}/settlement.json",
    f"snapshots/{allow.slug_for('nyc', D)}/snapshots_wide.csv",
    f"snapshots/{allow.slug_for('nyc', date(2026, 11, 1))}/replay_inputs.jsonl",
    f"snapshots/{allow.slug_for('nyc', date(2026, 11, 4))}/forecast_payloads.jsonl",
    f"prev_day/{allow.slug_for('nyc', D)}/metar_rows.jsonl",
    "snapshots/highest-temperature-in-toronto-on-november-2-2026/replay_inputs.jsonl",
    "settlements/ledger.jsonl",
    "forecast_payload_cas/sha256/8b/" + SHA + ".blob",
    "forecast_payload_cas/sha256/8a/" + SHA + ".json",
    "forecast_payload_cas/../manifest.json",
    "labels.parquet",
])
def test_everything_else_is_unlisted(rel):
    assert allow.classify_path(rel, D) is None


def test_projection_keeps_only_listed_fields():
    record = _host_replay_record()
    projected = allow.project_replay_record(record)
    assert allow.replay_record_problems(projected) == []
    assert set(projected["sources"]) == {"metar", "open_meteo_multimodel"}
    assert projected["sources"]["open_meteo_multimodel"]["data"]["day_model_highs"] == {"gfs_seamless": 84.0}
    assert set(projected["sources"]["metar"]["data"]) == {"rows", "station_id", "target_date_match", "report_time"}
    assert "recorded_distribution" not in projected
    problems = allow.replay_record_problems(record)
    for name in ("recorded_distribution", "sources.wu_history", "sources.station_observations"):
        assert any(p.startswith(f"forbidden:{name}") for p in problems), name
    assert "unlisted:sources.metar.data.raw" in problems


def test_prev_day_and_nbm_projections():
    record = _host_replay_record()
    prev = allow.project_prev_day_record(record)
    assert set(prev) <= set(allow.PREV_DAY_TOP) and prev["rows"] == record["sources"]["metar"]["data"]["rows"]
    assert allow.prev_day_record_problems(prev) == []
    assert allow.prev_day_record_problems({**prev, "settlement_high": 80}) == ["forbidden:settlement_high",
                                                                              "unlisted:settlement_high"]
    row = {k: "x" for k in allow.NBM_FIELDS}
    row["source"] = allow.NBM_SOURCE
    assert allow.nbm_row_problems(row) == []
    assert "nbm_row_not_nbm_source" in allow.nbm_row_problems({**row, "source": "open_meteo_multimodel"})
    assert "unlisted:market_yes" in allow.nbm_row_problems({**row, "market_yes": 0.5})
    assert allow.project_row({**row, "market_yes": 0.5}, allow.NBM_FIELDS) == row


def test_module_is_pure_stdlib_and_does_no_io():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
             and n.module != "__future__"}
    assert mods <= {"hashlib", "json", "re", "datetime", "zoneinfo"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not {"open", "exec", "eval", "__import__"} & names
    assert not {"read_text", "read_bytes", "write_text", "write_bytes", "urlopen"} & attrs
    assert "://" not in MODULE.read_text(encoding="utf-8")
