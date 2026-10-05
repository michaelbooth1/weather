"""Read-only old-vs-new late-day lock-in replay (weather.backtesting.lockin_anchor_replay).

Guards: read-only closed-date replay contract of weather.backtesting.lockin_anchor_replay (docs/architecture.md, late-day lock-in anchor; PR #191 floor check).
"""
import json
from datetime import datetime, timezone

import pytest

from weather.backtesting import lockin_anchor_replay as replay_cmd
from weather.backtesting.replay import REPLAY_INPUTS_FILENAME
from weather.model.toronto_model import TorontoHighTempModel
from weather.paths import data_path

SLUG = "highest-temperature-in-atlanta-on-september-20-2026"
READINGS_C = ((7, 22.0), (11, 28.0), (13, 30.0), (15, 31.7), (17, 30.0), (19, 27.8),
              (21, 25.6), (23, 24.4))
FEATURE_VECTOR = {84: 0.1, 86: 0.2, 88: 0.3, 89: 0.2, 90: 0.1, 92: 0.1}


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


def _record(snapshot_id, hour, target="2026-09-20"):
    model = TorontoHighTempModel(market_id="atlanta", target_date=target)
    year, month, day = (int(part) for part in target.split("-"))
    payload = []
    for report_hour, temp in READINGS_C:
        if report_hour > hour:
            continue
        local = datetime(year, month, day, report_hour, 52, tzinfo=model.spec.tz)
        payload.append({
            "reportTime": local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temp": temp,
            "icaoId": "KATL",
        })
    rows = model.parse_metar_payload(payload)
    latest = rows[-1]
    metar = {
        "station_id": "KATL", "rows": rows, "latest": latest, "target_date_match": True,
        "temp_native": latest["temp_native"], "temp_c": latest["temp_native"],
        "max_since_7am_native": model.station_max_since_7am_from_rows(rows),
        "same_day_max_native": max(row["temp_native"] for row in rows),
    }
    built_at = datetime(year, month, day, hour, 55, tzinfo=model.spec.tz)
    return {
        "snapshot_id": snapshot_id,
        "target_date": target,
        "built_at": built_at.isoformat(),
        "sources": {"metar": {"ok": True, "data": metar}},
    }


def _write_folder(root, slug, records):
    folder = root / slug
    folder.mkdir(parents=True)
    with (folder / REPLAY_INPUTS_FILENAME).open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return folder


def test_replay_compares_old_and_new_vectors_per_snapshot(tmp_path):
    root = tmp_path / "snapshots"
    _write_folder(root, SLUG, [_record("s-morning", 10), _record("s-evening", 23)])
    folders = replay_cmd.select_folders([], root)
    out = tmp_path / "out" / "replay.jsonl"

    summary = replay_cmd.run(folders, out, model_factory=_model_factory)

    rows = {row["snapshot_id"]: row for row in map(json.loads, out.read_text().splitlines())}
    morning, evening = rows["s-morning"], rows["s-evening"]
    assert morning["l1_new_vs_old"] == 0.0
    assert morning["old_final"] == morning["new_final"]
    assert evening["lockin_anchor"]["source"] == "observed_station_rows"
    assert evening["lockin_anchor"]["bucket"] == 89
    assert evening["old_lockin_strength"] == 0.0
    assert evening["new_lockin_strength"] == pytest.approx(1.0)
    assert evening["new_mass_above_anchor"] < evening["old_mass_above_anchor"]
    assert evening["l1_new_vs_old"] > 0.0
    blocks = {block["block"]: block for block in summary["blocks"]}
    assert blocks["00-12"]["changed"] == 0
    assert blocks["17-23"]["changed"] == 1
    assert summary["snapshots"] == 2


def test_scan_skips_dates_after_cutoff_and_explicit_late_folder_is_refused(tmp_path):
    root = tmp_path / "snapshots"
    _write_folder(root, SLUG, [_record("a", 23)])
    late = _write_folder(
        root,
        "highest-temperature-in-atlanta-on-september-30-2026",
        [_record("b", 23, target="2026-09-30")],
    )
    selected = replay_cmd.select_folders([], root)
    assert [folder.name for folder, _, _ in selected] == [SLUG]
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.select_folders([str(late)], root)
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.select_folders([], root, through_date=replay_cmd.date(2026, 9, 30))


def test_record_dated_after_cutoff_is_refused(tmp_path):
    record = _record("late", 23, target="2026-10-01")
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.compare_record(_model_factory("atlanta"), record, "atlanta")


def test_out_path_must_be_new_and_outside_data(tmp_path):
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.check_out_path(data_path() / "backtest" / "lockin.jsonl")
    existing = tmp_path / "exists.jsonl"
    existing.write_text("", encoding="utf-8")
    with pytest.raises(replay_cmd.ReplayRefused):
        replay_cmd.check_out_path(existing)


def test_main_exits_2_on_refusal(tmp_path, capsys):
    code = replay_cmd.main([
        "--snapshots-root", str(tmp_path),
        "--through-date", "2026-09-30",
        "--out", str(tmp_path / "x.jsonl"),
    ])
    assert code == 2
    assert "refused" in capsys.readouterr().err
    assert not (tmp_path / "x.jsonl").exists()


def test_summary_counts_rows_with_more_mass_below_the_anchor(tmp_path):
    root = tmp_path / "snapshots"
    _write_folder(root, SLUG, [_record("s-evening", 23)])
    summary = replay_cmd.run(
        replay_cmd.select_folders([], root), tmp_path / "ok.jsonl", model_factory=_model_factory,
    )
    assert summary["rows_new_below_anchor_exceeds_old"] == 0
    assert summary["floor_check"] == "PASS"

    row = {"hour": 18, "l1_new_vs_old": 0.5, "l1_old_vs_recorded": None,
           "old_mass_above_anchor": 0.8, "new_mass_above_anchor": 0.0,
           "old_mass_below_anchor": 0.14, "new_mass_below_anchor": 0.92}
    failing = replay_cmd.summarize([row])
    assert failing["rows_new_below_anchor_exceeds_old"] == 1
    assert failing["floor_check"] == "FAIL"


def test_main_exits_3_when_the_floor_check_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(replay_cmd, "select_folders", lambda *a, **k: [])
    monkeypatch.setattr(replay_cmd, "run", lambda *a, **k: {
        "snapshots": 1, "blocks": [], "rows_new_below_anchor_exceeds_old": 2,
        "floor_check": "FAIL", "old_vs_recorded_l1_max": None, "old_vs_recorded_rows": 0,
    })
    code = replay_cmd.main(["--snapshots-root", str(tmp_path), "--out", str(tmp_path / "y.jsonl")])
    assert code == replay_cmd.FLOOR_CHECK_FAILED_EXIT
    assert "floor check FAILED" in capsys.readouterr().err
