"""Forward-look venue-label refresh, freeze and counts-only audit (R24).

Guards: master ruling R24 (2026-11-01; docs/operations/venue-rule-labels.md "Forward-look labels"):
the audit and receipts never emit a label value, bucket or winner; predicted refusals equal the
label reader's on synthetic fixtures; fetches are serial and 5 s apart, include KDEN and never a
non-built-in ICAO; STATION_DRIFT exits non-zero; runs and frozen looks never share a folder; the
module never imports the reader or opens the reserved window. Fixtures only: no network, no data/.
"""

import ast
import csv
import functools
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.backtesting import venue_label_audit as vla
from weather.backtesting import venue_label_reader as vlr
from weather.backtesting import venue_rule_labels as vrl
from weather.market.market_registry import BUILTIN_SPECS, spec_for_id
from weather.operations.module_size_audit import DEFAULT_WARNING_LINES
from weather.paths import REPO_ROOT
from weather.schema_families import schema_version
from weather.schema_registry_families import load_families

START = date(2026, 10, 22)
THROUGH = date(2026, 10, 25)
TODAY = date(2026, 10, 26)
NOW = datetime(2026, 10, 26, 11, 15, tzinfo=timezone.utc)
CANARY_C = "41.3"  # 106.34 F, band 106; Toronto band 41
CANARY_NUMBERS = {106, 106.34, 41, 41.3}
CANARY_TEXT = ("106.3", "41.3")
REGISTRY_ICAOS = sorted(spec.icao for spec in BUILTIN_SPECS)
WU_COLUMNS = ["local_date", "temperature_unit", "row_count", "max_temp_native", "max_temp_bucket_native"]
MODULE = Path(vla.__file__)


class FakeClient:
    """IEM-shaped routine CSV: one report per hour at :51 UTC, every report at the canary temperature."""

    def __init__(self, log):
        self.log = log

    def fetch(self, icao, start, end, report_types=None, include_metar_text=False):
        self.log.append(("fetch", icao, tuple(report_types or ()), include_metar_text))
        lines = ["station,valid,tmpf,tmpc,metar"]
        moment = datetime(start.year, start.month, start.day, tzinfo=timezone.utc) - timedelta(hours=23, minutes=9)
        while moment.date() <= end + timedelta(days=1):
            stamp = moment.strftime("%d%H%M")
            raw = f"{icao} {stamp}Z 22003KT 10SM FEW021 41/10 A2987 RMK AO2 SLP115 T04130100"
            lines.append(f"{icao[1:]},{moment:%Y-%m-%d %H:%M},106.34,{CANARY_C},{raw}")
            moment += timedelta(hours=1)
        return "\n".join(lines) + "\n"


def _event(slug, day, icao):
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=raw" if icao else ""
    return {"event_slug": f"{slug}{day}", "event_date": day, "resolution_source_url": url}


def _events(path, extra=()):
    events = [
        _event("highest-temperature-in-nyc-on-", "2026-10-24", "KLGA"),
        _event("highest-temperature-in-denver-on-", "2026-10-22", "KBKF"),
        _event("highest-temperature-in-denver-on-", "2026-10-24", "KDEN"),
        _event("highest-temperature-in-amsterdam-on-", "2026-10-24", "EHAM"),
        *extra,
    ]
    path.write_text(json.dumps({"locations": [{"location_id": "x", "active_events": events}]}), encoding="utf-8")
    return path


def _station_config(path):
    path.write_text(json.dumps({
        "schema_version": vrl.STATION_CONFIG_SCHEMA,
        "markets": {"denver": [{"effective_from": "2026-10-23", "station_icao": "KDEN"}]},
    }), encoding="utf-8")
    return path


def _write_wu(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=WU_COLUMNS)
        writer.writeheader()
        for day, count in rows:
            writer.writerow({"local_date": day, "temperature_unit": "F", "row_count": count,
                             "max_temp_native": 106.34, "max_temp_bucket_native": 106})
    return path


@pytest.fixture
def world(tmp_path):
    log = []
    wu = {spec.id: _write_wu(tmp_path / "wu" / spec.id / "daily_summary.csv",
                             [(START.isoformat(), 24), ("2026-10-23", 24)]) for spec in BUILTIN_SPECS}
    kwargs = dict(
        start=START, label_root=tmp_path / "labels", events_path=_events(tmp_path / "events.json"),
        station_config_path=_station_config(tmp_path / "stations.json"), wu_daily_summaries=wu,
        client=FakeClient(log), sleep=lambda seconds: log.append(("sleep", seconds)), now=NOW, today=TODAY,
    )
    return {"tmp": tmp_path, "log": log, "kwargs": kwargs}


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield path + "/" + str(key), key
            yield from _walk(item, path + "/" + str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
    else:
        yield path, value


def _assert_no_label_values(payload):
    for where, value in _walk(payload):
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            assert value not in CANARY_NUMBERS, where
            continue
        text = str(value)
        if re.fullmatch(r"[0-9a-f]{64}", text):
            continue
        lowered = text.lower()
        assert "max_temp" not in lowered and "bucket" not in lowered and "winner" not in lowered, where
        assert not any(canary in text for canary in CANARY_TEXT), where


def test_refresh_fetches_serially_5s_apart_with_kden_and_never_a_foreign_icao(world):
    run_dir, receipt, _ = vla.refresh(THROUGH, **world["kwargs"])
    log = world["log"]
    fetched = [entry[1] for entry in log if entry[0] == "fetch"]
    assert fetched == sorted(set(REGISTRY_ICAOS) | {"KDEN"})
    assert "EHAM" not in fetched and len(fetched) == 13
    # Strictly alternating fetch / 5 s sleep: one fetch at a time, never two back to back.
    assert [entry[0] for entry in log] == ["fetch"] + ["sleep", "fetch"] * 12
    assert all(entry[1] == vla.FETCH_SPACING_SECONDS == 5.0 for entry in log if entry[0] == "sleep")
    assert all(entry[2] == (vrl.IEM_REPORT_TYPE_ROUTINE,) and entry[3] is True for entry in log if entry[0] == "fetch")
    assert receipt["stations"] == fetched
    assert all(Path(item["path"]).is_relative_to(run_dir) and item["sha256"] for item in receipt["fetches"])
    assert json.loads((run_dir / "location_market_events.json").read_text(encoding="utf-8")) == json.loads(
        world["kwargs"]["events_path"].read_text(encoding="utf-8"))


def test_a_built_in_event_station_is_fetched_but_a_foreign_one_never(world):
    _events(world["kwargs"]["events_path"], extra=[_event("highest-temperature-in-chicago-on-", "2026-10-24", "KMDW"),
                                                   _event("highest-temperature-in-paris-on-", "2026-10-24", "LFPG")])
    vla.refresh(THROUGH, **world["kwargs"])
    fetched = [entry[1] for entry in world["log"] if entry[0] == "fetch"]
    assert "KMDW" in fetched and "LFPG" not in fetched and "EHAM" not in fetched


def test_canary_label_values_never_appear_in_stdout_receipts_or_audit(world, monkeypatch, capsys):
    kwargs = dict(world["kwargs"])
    label_root = kwargs.pop("label_root")
    monkeypatch.setattr(vla, "refresh", functools.partial(vla.refresh, **kwargs))
    assert vla.main(["--label-root", str(label_root), "freeze", "--look", "mg1", "--through", THROUGH.isoformat()]) == 0
    stdout = json.loads(capsys.readouterr().out)
    run_dir = vla.latest_run(label_root)
    look_dir = label_root / "frozen" / "mg1"
    # Not vacuous: the canary is in the built labels themselves.
    assert "106.3" in (run_dir / "labels" / "nyc" / "daily" / "daily_summary.csv").read_text(encoding="utf-8")
    for payload in (stdout, *(json.loads(path.read_text(encoding="utf-8")) for path in (
            run_dir / "refresh_receipt.json", run_dir / "audit.json", look_dir / "freeze_receipt.json"))):
        _assert_no_label_values(payload)
    assert vla.main(["--label-root", str(label_root), "audit"]) == 0
    _assert_no_label_values(json.loads(capsys.readouterr().out))


def _venue(day, count=24, source=vrl.LABEL_SOURCE_METAR, version=vrl.VENUE_RULE_VERSION, high=106.34, station="KLGA"):
    return {"local_date": day, "temperature_unit": "F", "row_count": count, "max_temp": high,
            "max_temp_bucket": "" if high == "" else 106, "label_source": source, "label_station": station,
            "label_station_basis": vrl.STATION_BASIS_REGISTRY, "label_rule_version": version,
            "label_cutover_date": vrl.VENUE_RULE_CUTOVER_DATE.isoformat(), "label_value_basis": "t_group"}


SYNTHETIC = {
    "nyc": [_venue("2026-10-22", source=vrl.LABEL_SOURCE_WU), _venue("2026-10-23"),
            _venue("2026-10-24", count=vlr.COMPLETE_DAY_MIN_ROWS - 1), _venue("2026-10-25", version="v0")],
    "chicago": [_venue("2026-10-23", source=vrl.LABEL_SOURCE_WU_FALLBACK), _venue("2026-10-24", high=""),
                _venue("2026-10-25", source=vrl.LABEL_SOURCE_WU)],
    "denver": [_venue("2026-10-23", station="KDEN"), _venue("2026-10-24", station="KDEN", count=vlr.COMPLETE_DAY_MIN_ROWS)],
    "toronto": None,  # no CSV at all
}


@pytest.mark.parametrize("market_id", sorted(SYNTHETIC))
@pytest.mark.parametrize("model_scoring", [False, True])
def test_predicted_refusals_equal_the_reader_on_synthetic_fixtures(tmp_path, market_id, model_scoring):
    spec = spec_for_id(market_id)
    root = tmp_path / "labels"
    wu = _write_wu(tmp_path / "wu.csv", [("2026-10-23", 24)] + ([("2026-10-22", 24)] if market_id != "chicago" else []))
    if SYNTHETIC[market_id] is not None:
        vrl.write_label_csv(vrl.default_label_path(spec, root), SYNTHETIC[market_id])
    targets = [START + timedelta(days=offset) for offset in range(4)]
    _, expected = vlr.read_venue_labels(market_id, targets, read_through=THROUGH, allow_reserved_window=True,
                                        model_scoring=model_scoring, label_root=root, wu_daily_summary=wu)
    venue_rows = vla.read_dated_rows(vrl.default_label_path(spec, root), START, THROUGH)
    predicted = vla.predicted_refusals(market_id, targets, venue_rows, vla.read_dated_rows(wu, START, THROUGH),
                                       model_scoring=model_scoring)
    assert predicted == expected
    vrl.default_manifest_path(spec, root).parent.mkdir(parents=True, exist_ok=True)
    vrl.default_manifest_path(spec, root).write_text(json.dumps({"wu_daily_summary": str(wu)}), encoding="utf-8")
    counts = vla.audit_market(spec, root, START, THROUGH, "x")
    key = "predicted_refusal_counts_model_scoring" if model_scoring else "predicted_refusal_counts"
    assert counts[key] == dict(Counter(expected.values()))


def test_the_synthetic_fixtures_reach_every_reader_refusal():
    reasons = set()
    for market_id, rows in SYNTHETIC.items():
        venue = {row["local_date"]: row for row in rows} if rows is not None else None
        wu = {"2026-10-22": {"max_temp_native": 1, "max_temp_bucket_native": 1}} if market_id != "chicago" else {}
        for scoring in (False, True):
            targets = [START + timedelta(days=offset) for offset in range(4)]
            reasons |= set(vla.predicted_refusals(market_id, targets, venue, wu, model_scoring=scoring).values())
    assert reasons == {vlr.REFUSED_NO_WU_ROW, vlr.REFUSED_NO_VENUE_CSV, vlr.REFUSED_NO_VENUE_ROW,
                       vlr.REFUSED_THIN_VENUE_ROW, vlr.REFUSED_BAD_VENUE_ROW, vlr.REFUSED_MODEL_SCORING_EXCLUDED}


def test_refusal_reasons_mirror_the_reader_constants():
    for name in ("REFUSED_MODEL_SCORING_EXCLUDED", "REFUSED_NO_WU_ROW", "REFUSED_NO_VENUE_CSV",
                 "REFUSED_NO_VENUE_ROW", "REFUSED_THIN_VENUE_ROW", "REFUSED_BAD_VENUE_ROW"):
        assert getattr(vla, name) == getattr(vlr, name)
    assert vla.MODEL_SCORING_EXCLUDED_FROM == vlr.MODEL_SCORING_EXCLUDED_FROM


def test_audit_counts_on_a_clean_run(world):
    _, _, audit = vla.refresh(THROUGH, **world["kwargs"])
    assert audit["status"] == "OK" and audit["station_drift"] == []
    nyc, denver = audit["markets"]["nyc"], audit["markets"]["denver"]
    assert nyc["predicted_refusal_counts"] == {} and nyc["thin_row_count"] == 0 and nyc["body_basis_row_count"] == 0
    assert nyc["label_source_counts"] == {vrl.LABEL_SOURCE_METAR: 3, vrl.LABEL_SOURCE_WU: 1}
    assert nyc["pre_cutover_rows"] == 1 and nyc["pre_cutover_pass_through_mismatches"] == 0
    assert nyc["output_sha256_matches_manifest"] and nyc["metar_inputs_without_sha256"] == 0
    assert denver["denver_kden_config_override_rows"] == 3 and denver["denver_fallback_rows"] == 0
    assert denver["predicted_refusal_counts_model_scoring"] == {vlr.REFUSED_MODEL_SCORING_EXCLUDED: 3}
    assert nyc["denver_kden_config_override_rows"] is None


def test_station_drift_exits_non_zero_and_a_matching_event_does_not(world, monkeypatch, capsys):
    kwargs = dict(world["kwargs"])
    label_root = kwargs.pop("label_root")
    monkeypatch.setattr(vla, "refresh", functools.partial(vla.refresh, **kwargs))
    assert vla.main(["--label-root", str(label_root), "refresh", "--through", THROUGH.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "OK"
    _events(kwargs["events_path"], extra=[_event("highest-temperature-in-chicago-on-", "2026-10-24", "KMDW"),
                                          _event("highest-temperature-in-denver-on-", "2026-10-25", "KBKF")])
    kwargs["now"] = NOW + timedelta(minutes=1)
    monkeypatch.setattr(vla, "refresh", functools.partial(vla.refresh.func, **kwargs))
    assert vla.main(["--label-root", str(label_root), "refresh", "--through", THROUGH.isoformat()]) == vla.EXIT_STATION_DRIFT != 0
    drift = json.loads(capsys.readouterr().out)["audit"]["station_drift"]
    assert [(row["market_id"], row["event_icao"], row["expected_icao"]) for row in drift] == [
        ("chicago", "KMDW", "KORD"), ("denver", "KBKF", "KDEN")]
    assert vla.main(["--label-root", str(label_root), "audit"]) == vla.EXIT_STATION_DRIFT


def test_events_before_start_or_without_a_station_are_not_drift(world):
    config = vrl.load_station_config(world["kwargs"]["station_config_path"])
    payload = {"locations": [{"active_events": [
        _event("highest-temperature-in-chicago-on-", "2026-10-21", "KMDW"),
        _event("highest-temperature-in-chicago-on-", "2026-10-24", ""),
    ]}]}
    assert vla.station_drift(payload, config, START) == ([], 1)


def test_runs_and_frozen_looks_never_share_a_folder(world):
    first, _, _ = vla.refresh(THROUGH, **world["kwargs"])
    with pytest.raises(vla.AuditRefused, match="never reused"):
        vla.refresh(THROUGH, **world["kwargs"])
    second, _, _ = vla.refresh(THROUGH, **{**world["kwargs"], "now": NOW + timedelta(seconds=1)})
    assert first != second and first.parent == second.parent
    assert vla.latest_run(world["kwargs"]["label_root"]) == second
    kwargs = {**world["kwargs"], "now": NOW + timedelta(seconds=2)}
    vla.freeze("b", THROUGH, **kwargs)
    with pytest.raises(vla.AuditRefused, match="frozen once"):
        vla.freeze("b", THROUGH, **{**kwargs, "now": NOW + timedelta(seconds=3)})
    with pytest.raises(vla.AuditRefused, match="--look"):
        vla.freeze("../b", THROUGH, **{**kwargs, "now": NOW + timedelta(seconds=4)})


def test_through_after_today_is_refused_before_any_folder_or_fetch(world):
    with pytest.raises(vla.AuditRefused, match="after today"):
        vla.refresh(TODAY + timedelta(days=1), **world["kwargs"])
    assert world["log"] == [] and not (world["kwargs"]["label_root"] / "runs").exists()


def test_the_frozen_copy_is_a_reader_label_root(world):
    look_dir, receipt, _ = vla.freeze("mg1", THROUGH, **world["kwargs"])
    entry = receipt["markets"]["nyc"]
    assert entry["label_csv_matches_manifest"] and entry["wu_daily_summary_matches_manifest"]
    assert Path(entry["label_csv"]["path"]) == vrl.default_label_path(spec_for_id("nyc"), look_dir)
    wu_copy = look_dir / "nyc" / "wu" / "daily_summary.csv"
    targets = [START + timedelta(days=offset) for offset in range(4)]
    records, refusals = vlr.read_venue_labels("nyc", targets, read_through=THROUGH, allow_reserved_window=True,
                                              label_root=look_dir, wu_daily_summary=wu_copy)
    assert refusals == {} and len(records) == 4
    assert records["2026-10-23"]["source_sha256"] == entry["label_csv"]["sha256"]
    assert records["2026-10-22"]["source_sha256"] == entry["wu_daily_summary"]["sha256"]


def test_module_never_imports_the_reader_or_opens_the_reserved_window():
    source = MODULE.read_text(encoding="utf-8")
    for token in ("read_venue_labels", "venue_label_reader", "allow_reserved_window", "Path.cwd", "getcwd"):
        assert token not in source
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert not any("venue_label_reader" in name for name in imported)
    assert {name for name in imported if name.startswith("weather")} <= {
        "weather.backtesting.settlement_ledger", "weather.backtesting.venue_rule_labels",
        "weather.market.market_registry", "weather.paths", "weather.schema_families", "weather.sources.daily_summary"}


def test_module_size_schema_and_docs():
    assert len(MODULE.read_text(encoding="utf-8").splitlines()) < DEFAULT_WARNING_LINES // 4
    registry = load_families()
    assert registry.errors == ()
    for name, constant in (("venue_label_refresh_receipt", vla.REFRESH_RECEIPT_SCHEMA),
                           ("venue_label_freeze_receipt", vla.FREEZE_RECEIPT_SCHEMA),
                           ("venue_label_audit", vla.AUDIT_SCHEMA)):
        assert registry.family_of(name) == "venue_labels"
        assert schema_version(name) == constant == f"{name}_v1"
    doc = (REPO_ROOT / "docs" / "operations" / "venue-rule-labels.md").read_text(encoding="utf-8")
    section = doc.split("## Forward-look labels", 1)[1].split("\n## ", 1)[0]
    for needle in ("python -m weather.backtesting.venue_label_audit", "refresh", "freeze", "audit", "STATION_DRIFT"):
        assert needle in section
