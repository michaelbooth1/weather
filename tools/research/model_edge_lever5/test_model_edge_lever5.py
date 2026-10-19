"""Synthetic checks for the lever-5 stage replay (no captured data)."""
import json
from datetime import datetime, timezone

import pytest

import weather.paths
from tools.research.model_edge_lever5 import stage_replay as l5
from weather.model.toronto_model import TorontoHighTempModel

READINGS = ((7, 22.0), (11, 28.0), (13, 30.0), (15, 31.7), (17, 30.0), (19, 27.8), (21, 25.6))
FEATURE = {84: 0.1, 86: 0.2, 88: 0.3, 89: 0.2, 90: 0.1, 92: 0.1}
SLUG = "highest-temperature-in-atlanta-on-september-{day}-2026"


def _factory(market_id):
    model = TorontoHighTempModel(market_id=market_id)
    model.calibrated_weights = None
    model.predict_feature_distribution = lambda sources, cutoff_hour, now: (dict(FEATURE), "hgb")
    model.predict_late_day_continuation = lambda sources, cutoff_hour, now: None
    return model


def _record(sid, hour, target="2026-09-20"):
    model = TorontoHighTempModel(market_id="atlanta", target_date=target)
    y, m, d = (int(p) for p in target.split("-"))
    payload = [{
        "reportTime": datetime(y, m, d, h, 52, tzinfo=model.spec.tz)
        .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "temp": t, "icaoId": "KATL",
    } for h, t in READINGS if h <= hour]
    rows = model.parse_metar_payload(payload)
    metar = {"station_id": "KATL", "rows": rows, "latest": rows[-1], "target_date_match": True,
             "temp_native": rows[-1]["temp_native"], "temp_c": rows[-1]["temp_native"],
             "max_since_7am_native": model.station_max_since_7am_from_rows(rows),
             "same_day_max_native": max(r["temp_native"] for r in rows)}
    nbm = {"available": True, "station_id": "KATL", "target_date": target,
           "percentiles": {"10": 85.0, "25": 87.0, "50": 89.0, "75": 91.0, "90": 93.0},
           "mean_native": 89.0, "stddev_native": 2.5}
    return {"snapshot_id": sid, "target_date": target,
            "built_at": datetime(y, m, d, hour, 55, tzinfo=model.spec.tz).isoformat(),
            "sources": {"metar": {"ok": True, "data": metar},
                        "nbm_probabilistic_tmax": {"ok": True, "data": nbm}}}


def _folder(root, day, hours):
    folder = root / SLUG.format(day=day)
    folder.mkdir(parents=True)
    with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
        for hour in hours:
            handle.write(json.dumps(_record(f"s{hour}", hour, target=f"2026-09-{day}")) + "\n")
    return folder


@pytest.fixture
def roots(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "wunderground").mkdir(parents=True)
    monkeypatch.setattr(weather.paths, "DATA_ROOT", data)
    return data


@pytest.fixture
def climatology_ok(monkeypatch):
    monkeypatch.setattr(l5, "climatology_error", lambda model: None)
    monkeypatch.setattr(l5, "hgb_error", lambda model: None)


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_nbm_never_reaches_post_processing_and_centering_acts_only_in_window(
        tmp_path, roots, climatology_ok):
    _folder(tmp_path / "snaps", 20, (9, 16, 21))
    lines = []
    summary = l5.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "out.jsonl",
                     list(l5.VARIANTS), model_factory=_factory, emit=lines.append)
    assert summary["snapshots"] == 3 and summary["nbm_present_snapshots"] == 3
    for variant in ("nbm_removed", "nbm_perturbed", "wu_residual_repointed",
                    "metar_live_signal_repointed", "intraday_tail_repointed"):
        block = summary["variants"][variant]["all"]
        assert block["errors"] == 0 and block["max_tv"] == 0.0, variant
    rows = {r["hour"]: r for r in _rows(tmp_path / "out.jsonl") if r["kind"] == "snapshot"}
    assert rows[9]["variants"]["centering_reenabled"]["tv"] == 0.0
    assert rows[21]["variants"]["centering_reenabled"]["tv"] == 0.0
    assert len(lines) == 1 and lines[0].startswith(
        f"TIMING folder={SLUG.format(day=20)} snapshots=3 seconds=")
    assert " cumulative=" in lines[0]


def test_data_root_is_required_and_must_hold_climatology(tmp_path):
    with pytest.raises(l5.Refused):
        l5.configure_roots(None)
    with pytest.raises(l5.Refused):
        l5.configure_roots(tmp_path)  # no wunderground/


@pytest.mark.parametrize("summary_csv", [None, "local_date,row_count\n"])
def test_empty_climatology_fails_closed_per_folder(tmp_path, roots, summary_csv, monkeypatch):
    monkeypatch.setattr(l5, "hgb_error", lambda model: None)
    if summary_csv is not None:
        daily = roots / "wunderground" / "katl" / "daily"
        daily.mkdir(parents=True)
        (daily / "daily_summary.csv").write_text(summary_csv)
    _folder(tmp_path / "snaps", 20, (16,))
    summary = l5.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "out.jsonl",
                     ["nbm_removed"], model_factory=_factory, emit=lambda line: None)
    rows = _rows(tmp_path / "out.jsonl")
    assert [r["kind"] for r in rows] == ["header", "folder_error", "folder_done"]
    assert summary["folder_errors"] == 1 and summary["snapshots"] == 0
    assert rows[1]["error"].startswith(("missing_climatology_summary", "empty_climatology_cache"))


def test_base_failure_is_an_error_row_and_the_run_continues(tmp_path, roots, climatology_ok):
    _folder(tmp_path / "snaps", 20, (9, 16))

    def factory(market_id):
        model = _factory(market_id)
        original = model.estimate_distribution_result

        def flaky(sources, now=None):
            if now.hour == 9:
                raise RuntimeError("boom")
            return original(sources, now=now)

        model.estimate_distribution_result = flaky
        return model

    summary = l5.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "out.jsonl",
                     ["nbm_removed"], model_factory=factory, emit=lambda line: None)
    assert summary["snapshots"] == 2 and summary["snapshot_base_errors"] == 1
    assert summary["variants"]["nbm_removed"]["all"]["snapshots"] == 1


def test_outputs_inside_data_tree_are_refused(tmp_path, roots, climatology_ok):
    _folder(tmp_path / "snaps", 20, (9,))
    folders = l5.select_folders(tmp_path / "snaps")
    with pytest.raises(l5.Refused):
        l5.run(folders, tmp_path / "out.jsonl", ["nbm_removed"], model_factory=_factory,
               summary_path=roots / "summary.json", emit=lambda line: None)
    with pytest.raises(l5.Refused):
        l5.run(folders, roots / "out.jsonl", ["nbm_removed"], model_factory=_factory,
               emit=lambda line: None)


def test_resume_skips_done_folders_and_refuses_mismatched_header(tmp_path, roots, climatology_ok):
    snaps = tmp_path / "snaps"
    _folder(snaps, 20, (9,))
    out, summary_path = tmp_path / "out.jsonl", tmp_path / "summary.json"
    l5.run(l5.select_folders(snaps), out, ["nbm_removed"], model_factory=_factory,
           summary_path=summary_path, emit=lambda line: None)
    _folder(snaps, 21, (9, 16))
    lines = []
    summary = l5.run(l5.select_folders(snaps), out, ["nbm_removed"], model_factory=_factory,
                     summary_path=summary_path, emit=lines.append)
    assert summary["status"]["folders_done_before"] == 1 and summary["status"]["folders_run"] == 1
    assert summary["snapshots"] == 3 and len(lines) == 1
    assert json.loads(summary_path.read_text())["snapshots"] == 3
    with pytest.raises(l5.Refused):
        l5.run(l5.select_folders(snaps), out, ["nbm_perturbed"], model_factory=_factory,
               emit=lambda line: None)
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"kind": "something-else"}\n')
    with pytest.raises(l5.Refused):
        l5.run(l5.select_folders(snaps), bad, ["nbm_removed"], model_factory=_factory,
               emit=lambda line: None)


def test_market_and_max_folders_filter_and_budget(tmp_path, roots, climatology_ok):
    snaps = tmp_path / "snaps"
    for day in (20, 21, 22):
        _folder(snaps, day, (9,))
    (snaps / "highest-temperature-in-nyc-on-september-20-2026").mkdir()
    assert len(l5.select_folders(snaps)) == 4
    assert [m for _, m in l5.select_folders(snaps, market="atlanta")] == ["atlanta"] * 3
    assert len(l5.select_folders(snaps, market="atlanta", max_folders=2)) == 2
    ticks = iter(range(0, 10_000, 100))
    summary = l5.run(l5.select_folders(snaps, market="atlanta"), tmp_path / "out.jsonl",
                     ["nbm_removed"], model_factory=_factory, budget_minutes=1,
                     clock=lambda: next(ticks), emit=lambda line: None)
    assert summary["status"]["folders_run"] == 1
    assert summary["status"]["folders_skipped_budget"] == 2


def test_out_of_window_dates_are_refused(roots):
    with pytest.raises(l5.Refused):
        l5.compare_record(_factory("atlanta"), _record("late", 21, target="2026-09-30"),
                          "atlanta", ["nbm_removed"])


def test_unloadable_hgb_fails_closed(tmp_path, roots, monkeypatch):
    monkeypatch.setattr(l5, "climatology_error", lambda model: None)

    def factory(market_id):
        model = _factory(market_id)
        model.load_feature_model_hgb = lambda: None
        return model

    _folder(tmp_path / "snaps", 20, (9,))
    summary = l5.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "out.jsonl",
                     ["nbm_removed"], model_factory=factory, emit=lambda line: None)
    assert summary["folder_errors"] == 1 and summary["snapshots"] == 0
