"""Combined METAR v4 re-parse + lockin-anchor-v3 replay (weather.backtesting.metar_v4_lockin_replay).

Fixtures are written with the production writers: the METAR source block is
built by ``metar_data_from_payload`` under the retired ``reportTime`` keying
(what a ``metar-parser-v3`` capture served), wrapped by ``fetch_source``, and
persisted by ``SnapshotStore.write_observation_payloads`` (content-addressed
raw blob + manifest) and ``SnapshotStore.write_replay_input`` (stripped
replay record).

Guards: read-only combined v4 re-parse + lockin-anchor-v3 acceptance replay (docs/architecture.md; PRs #189 and #191, floor check exit 3).
"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from weather.backtesting import metar_v4_lockin_replay as replay_cmd
from weather.collection.snapshot_store import SnapshotStore
from weather.market.market_config import config_for_date
from weather.model.model_sources import METAR_KEYING_REPORT_TIME
from weather.model.source_adapters import fetch_source
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import data_path

MARKET = "austin"
FEATURE_VECTOR = {88: 0.1, 90: 0.2, 92: 0.3, 93: 0.2, 94: 0.1, 96: 0.1}
V3_CONTRACT = {"parser_version": "metar-parser-v3", "payload_schema_version": "metar-payload-v1"}


def _model_factory(market_id):
    model = TorontoHighTempModel(market_id=market_id)
    model.calibrated_weights = None
    model.settlement_lag_model = {
        "component": {"min_context_n": 20},
        "revision_contexts": {"hour=20": {"n": 600, "revision_up_rate": 0.003}},
    }
    model.predict_feature_distribution = lambda sources, cutoff_hour, now: (
        dict(FEATURE_VECTOR), "hgb",
    )
    model.predict_late_day_continuation = lambda sources, cutoff_hour, now: None
    return model


def awc_row(obs_utc, temp_c, *, report_utc=None):
    """One AWC JSON row; a routine report's reportTime is the next nominal hour."""
    obs = datetime.fromisoformat(obs_utc.replace("Z", "+00:00"))
    report = (
        datetime.fromisoformat(report_utc.replace("Z", "+00:00")) if report_utc
        else obs.replace(minute=0) + timedelta(hours=1)
    )
    return {
        "icaoId": "KAUS",
        "obsTime": int(obs.timestamp()),
        "reportTime": report.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "metarType": "METAR",
        "temp": temp_c,
        "dewp": 20.0,
        "rawOb": f"METAR KAUS {obs:%d%H%M}Z 18008KT 10SM CLR {round(temp_c):02d}/20 A3000",
    }


def day_rows(target, readings):
    """Routine :53 reports of local day ``target`` (America/Chicago, CDT = UTC-5)."""
    rows = []
    for local_hour, temp_c in readings:
        local = datetime(target.year, target.month, target.day, local_hour, 53)
        utc = local.replace(tzinfo=timezone.utc) + timedelta(hours=5)
        rows.append(awc_row(utc.strftime("%Y-%m-%dT%H:%M:00Z"), temp_c))
    return rows


def capture(root, target, snapshots):
    """Capture snapshots the way a v3 build served and stored them."""
    slug = config_for_date(target, MARKET).event_slug
    store = SnapshotStore(root=root / slug, event_slug=slug)
    for snapshot_id, built_local, payload in snapshots:
        model = TorontoHighTempModel(target_date=target.isoformat(), market_id=MARKET)
        _, item = fetch_source(
            "metar",
            lambda model=model, payload=payload: model.with_source_fetch_meta(
                {"url": "https://aviationweather.gov/api/data/metar",
                 **model.metar_data_from_payload(payload, keying=METAR_KEYING_REPORT_TIME)},
                V3_CONTRACT,
            ),
            fetched_at=built_local.isoformat(),
        )
        sources = {"metar": item}
        station = model.derive_station_observations_source(sources)
        if station:
            sources["station_observations"] = station
        store.write_observation_payloads(sources, snapshot_id, built_local, "model-v")
        store.write_replay_input(
            snapshot_id, built_local,
            {"sources": sources, "built_at": built_local.isoformat(), "distribution": {}},
            model, "model-v",
            model_identity={}, release_lineage={"release_identity_status": "unavailable"},
        )
    return root / slug


TZ = TorontoHighTempModel(market_id=MARKET).spec.tz
CARRY_DAY = date(2026, 8, 25)
# D-1's 23:53 CDT report (35.0 C) has reportTime 05:00Z of D: v3 keyed it into D.
CARRIED = awc_row("2026-08-25T04:53:00Z", 35.0)
CARRY_DAY_ROWS = day_rows(CARRY_DAY, ((7, 26.0), (11, 30.0), (14, 33.9), (16, 33.3), (17, 32.2)))
NORMAL_DAY = date(2026, 8, 26)
NORMAL_DAY_ROWS = day_rows(NORMAL_DAY, ((0, 27.0), (7, 26.0), (11, 30.0), (14, 33.9), (16, 33.3),
                                        (17, 32.2)))


@pytest.fixture
def snapshots_root(tmp_path):
    root = tmp_path / "snapshots"
    capture(root, CARRY_DAY, [
        ("c-18", datetime(2026, 8, 25, 18, 5, tzinfo=TZ), [CARRIED, *CARRY_DAY_ROWS]),
    ])
    capture(root, NORMAL_DAY, [
        ("n-18", datetime(2026, 8, 26, 18, 5, tzinfo=TZ), NORMAL_DAY_ROWS),
    ])
    return root


def _run(root, tmp_path, name="replay.jsonl"):
    out = tmp_path / "out" / name
    summary = replay_cmd.run(replay_cmd.select_folders([], root), out, model_factory=_model_factory)
    rows = {row["snapshot_id"]: row for row in map(json.loads, out.read_text().splitlines())}
    return summary, rows


def test_carry_over_case_v4_drops_prior_day_row_and_the_floor(snapshots_root, tmp_path):
    before = sorted(p.relative_to(snapshots_root) for p in snapshots_root.rglob("*"))
    summary, rows = _run(snapshots_root, tmp_path)
    assert sorted(p.relative_to(snapshots_root) for p in snapshots_root.rglob("*")) == before

    carry = rows["c-18"]
    assert carry["status"] == "ok"
    assert carry["recorded_parser_version"] == "metar-parser-v3"
    assert [r["obs_time"] for r in carry["carried_prior_day_rows"]] == ["2026-08-25T04:53:00Z"]
    assert carry["guidance_physical_floor_captured"] == pytest.approx(95.0)
    assert carry["guidance_physical_floor_reparsed"] == pytest.approx(33.9 * 9 / 5 + 32)
    assert carry["floor_changed_by_reparse"] is True
    assert carry["floor_dropped_by_reparse"] is True
    # lockin-anchor-v3 already excluded the carried report from the anchor itself.
    assert carry["lockin_anchor"]["source"] == "observed_station_rows"
    assert carry["lockin_anchor"]["bucket"] == 93
    assert carry["lockin_anchor_v3_captured"]["excluded_prior_day_rows"] == 1
    assert carry["lockin_anchor"]["excluded_prior_day_rows"] == 0
    assert carry["new_mass_below_anchor"] <= carry["old_mass_below_anchor"] + 1e-9

    assert summary["status"] == {"ok": 2}
    assert summary["floor_check"] == "PASS"
    assert summary["carry_over_rows"] == 1
    assert summary["carry_over_floor_dropped"] == 1
    blocks = {block["block"]: block for block in summary["blocks"]}
    assert [block["block"] for block in summary["blocks"]] == [
        "00-05", "06-09", "10-12", "13-16", "17-23",
    ]
    assert blocks["17-23"]["snapshots"] == 2
    assert blocks["17-23"]["carry_over_rows"] == 1
    assert blocks["17-23"]["floor_dropped_by_reparse"] == 1
    assert blocks["00-05"]["snapshots"] == 0


def test_normal_day_floor_and_anchor_unchanged_by_v4(snapshots_root, tmp_path):
    _, rows = _run(snapshots_root, tmp_path)
    normal = rows["n-18"]
    assert normal["status"] == "ok"
    assert normal["carried_prior_day_rows"] == []
    assert normal["floor_changed_by_reparse"] is False
    assert normal["anchor_changed_by_reparse"] is False
    assert normal["guidance_physical_floor_reparsed"] == pytest.approx(33.9 * 9 / 5 + 32)
    assert normal["lockin_anchor"]["bucket"] == 93
    assert normal["l1_new_vs_v3_captured"] == pytest.approx(0.0, abs=1e-12)
    assert normal["l1_new_vs_old"] > 0.0  # the v3 lock-in itself still acts


def test_pre_lockin_floor_comparison_is_inert_without_the_switch(snapshots_root, tmp_path):
    """On code without the lockin-anchor-v4 floor the switch changes nothing and is restored."""
    out = tmp_path / "out" / "b.jsonl"
    models = {}

    def factory(market_id):
        models[market_id] = _model_factory(market_id)
        return models[market_id]

    summary = replay_cmd.run(replay_cmd.select_folders([], snapshots_root), out,
                             model_factory=factory, compare_pre_lockin_floor=True)
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert all(row["l1_new_vs_b_off"] == pytest.approx(0.0, abs=1e-12) for row in rows)
    assert all(row["b_off_final"] == row["new_final"] for row in rows)
    assert summary["pre_lockin_floor"]["rows"] == 2
    assert summary["pre_lockin_floor"]["rows_changed"] == 0
    assert set(summary["anchor_versions"]) == {rows[0]["anchor_version"]}
    assert all(replay_cmd.PRE_LOCKIN_FLOOR_SWITCH not in vars(m) for m in models.values())


def test_pre_lockin_floor_effect_summary_on_synthetic_rows():
    base = {"hour": 4, "l1_new_vs_old": 0.2, "l1_new_vs_v3_captured": 0.2,
            "old_mass_above_anchor": 0.7, "new_mass_above_anchor": 0.7,
            "old_mass_below_anchor": 0.0, "new_mass_below_anchor": 0.0,
            "floor_changed_by_reparse": False, "floor_dropped_by_reparse": False,
            "anchor_changed_by_reparse": False, "carried_prior_day_rows": []}
    moved = {**base, "b_off_mass_below_anchor": 0.28, "l1_new_vs_b_off": 0.56,
             "mean_shift_new_vs_b_off": 1.4}
    untouched = {**base, "b_off_mass_below_anchor": 0.0, "l1_new_vs_b_off": 0.0,
                 "mean_shift_new_vs_b_off": 0.0}
    effect = replay_cmd.summarize([moved, untouched])["pre_lockin_floor"]
    assert effect["rows"] == 2 and effect["rows_changed"] == 1
    assert effect["rows_b_off_below_anchor_positive"] == 1
    assert effect["max_mass_moved_onto_anchor"] == 0.28
    assert effect["mean_mass_moved_onto_anchor"] == pytest.approx(0.14)
    assert effect["max_shift_new_vs_b_off"] == 1.4
    block = {b["block"]: b for b in replay_cmd.summarize([moved])["blocks"]}["00-05"]
    assert block["pre_lockin_floor"]["rows_changed"] == 1
    assert "pre_lockin_floor" not in replay_cmd.summarize([base])  # not requested, not reported


def test_tampered_blob_is_reported_and_not_replayed(snapshots_root, tmp_path):
    blob = next((snapshots_root).rglob("observation_payloads/sha256/*/*.json"))
    blob.write_bytes(blob.read_bytes().replace(b"KAUS", b"KXXX", 1))
    summary, rows = _run(snapshots_root, tmp_path)
    statuses = sorted(row["status"] for row in rows.values())
    assert "hash_mismatch" in statuses
    assert summary["snapshots"] == 1
    assert summary["status"]["hash_mismatch"] == 1


def test_floor_check_fires_on_a_synthetic_bad_row():
    row = {"hour": 18, "l1_new_vs_old": 0.5, "l1_new_vs_v3_captured": 0.1,
           "old_mass_above_anchor": 0.8, "new_mass_above_anchor": 0.0,
           "old_mass_below_anchor": 0.14, "new_mass_below_anchor": 0.92,
           "floor_changed_by_reparse": True, "floor_dropped_by_reparse": True,
           "anchor_changed_by_reparse": True, "carried_prior_day_rows": [{"obs_time": "x"}]}
    failing = replay_cmd.summarize([{**row, "carried_prior_day_rows": []}])
    assert failing["rows_new_below_anchor_exceeds_old"] == 1
    assert failing["floor_check"] == "FAIL"
    assert failing["rows_new_below_anchor_positive"] == 1
    assert failing["max_new_mass_below_anchor"] == 0.92
    block = {b["block"]: b for b in failing["blocks"]}["17-23"]
    assert block["rows_new_below_anchor_exceeds_old"] == 1


def test_carry_over_rows_are_a_defect_baseline_class_and_never_fail_the_check():
    """The old vector of a carry row was propped by the D-1 report v4 removes."""
    carry = {"hour": 4, "l1_new_vs_old": 0.3, "l1_new_vs_v3_captured": 0.3,
             "old_mass_above_anchor": 0.9, "new_mass_above_anchor": 0.7,
             "old_mass_below_anchor": 0.0, "new_mass_below_anchor": 0.28,
             "floor_changed_by_reparse": True, "floor_dropped_by_reparse": True,
             "anchor_changed_by_reparse": True, "carried_prior_day_rows": [{"obs_time": "x"}]}
    summary = replay_cmd.summarize([carry])
    assert summary["floor_check"] == "PASS"
    assert summary["rows_new_below_anchor_exceeds_old"] == 0
    assert summary["defect_baseline_below_increase"] == 1
    assert summary["rows_new_below_anchor_positive"] == 1  # still visible in the absolute count
    block = {b["block"]: b for b in summary["blocks"]}["00-05"]
    assert block["defect_baseline_below_increase"] == 1
    assert block["carry_over_anchor_changed"] == 1
    # Mutant: the same row without carry-over fails the check.
    assert replay_cmd.summarize([{**carry, "carried_prior_day_rows": []}])["floor_check"] == "FAIL"


def test_main_exits_3_when_the_floor_check_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(replay_cmd, "select_folders", lambda *a, **k: [])
    monkeypatch.setattr(replay_cmd, "run", lambda *a, **k: replay_cmd.summarize([{
        "hour": 18, "l1_new_vs_old": 0.5, "l1_new_vs_v3_captured": 0.0,
        "old_mass_above_anchor": 0.8, "new_mass_above_anchor": 0.0,
        "old_mass_below_anchor": 0.1, "new_mass_below_anchor": 0.9,
        "floor_changed_by_reparse": False, "floor_dropped_by_reparse": False,
        "anchor_changed_by_reparse": False, "carried_prior_day_rows": [],
    }]))
    code = replay_cmd.main(["--snapshots-root", str(tmp_path), "--out", str(tmp_path / "y.jsonl")])
    assert code == replay_cmd.FLOOR_CHECK_FAILED_EXIT
    assert "floor check FAILED" in capsys.readouterr().err


def test_refuses_late_dates_data_tree_and_existing_out(tmp_path, capsys):
    late = tmp_path / "snapshots" / config_for_date(date(2026, 9, 30), MARKET).event_slug
    late.mkdir(parents=True)
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.select_folders([str(late)], tmp_path / "snapshots")
    assert replay_cmd.select_folders([], tmp_path / "snapshots") == []
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.check_out_path(data_path() / "backtest" / "v4v3.jsonl")
    existing = tmp_path / "exists.jsonl"
    existing.write_text("", encoding="utf-8")
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.check_out_path(existing)
    code = replay_cmd.main([
        "--snapshots-root", str(tmp_path / "snapshots"),
        "--through-date", "2026-09-30", "--out", str(tmp_path / "x.jsonl"),
    ])
    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "x.jsonl").exists()
