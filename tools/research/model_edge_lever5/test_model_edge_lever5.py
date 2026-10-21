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
    assert [r["kind"] for r in rows] == ["header", "folder_error"]
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


def test_folder_error_is_retried_on_resume_without_duplicating_done_rows(tmp_path, roots, monkeypatch):
    monkeypatch.setattr(l5, "climatology_error", lambda model: None)
    broken = {"2026-09-21"}
    monkeypatch.setattr(l5, "hgb_error", lambda model: (
        "hgb_artifact_unavailable" if model.target_date.isoformat() in broken else None))
    snaps, out = tmp_path / "snaps", tmp_path / "out.jsonl"
    _folder(snaps, 20, (9,))
    _folder(snaps, 21, (9, 16))

    def run_once():
        return l5.run(l5.select_folders(snaps), out, ["nbm_removed"], model_factory=_factory,
                      emit=lambda line: None)

    first = run_once()
    assert first["folder_errors"] == 1 and first["snapshots"] == 1
    assert [r["folder"] for r in _rows(out) if r["kind"] == "folder_done"] == [SLUG.format(day=20)]
    broken.clear()  # e.g. git lfs checkout done
    second = run_once()
    assert second["status"]["folders_done_before"] == 1 and second["status"]["folders_run"] == 1
    assert second["folder_errors"] == 0 and second["snapshots"] == 3
    rows = _rows(out)
    keys = [(r["folder"], r["snapshot_id"]) for r in rows if r["kind"] == "snapshot"]
    assert len(keys) == len(set(keys)) == 3
    assert sorted(r["folder"] for r in rows if r["kind"] == "folder_done") == [
        SLUG.format(day=20), SLUG.format(day=21)]
    third = run_once()
    assert third["status"]["folders_done_before"] == 2 and third["status"]["folders_run"] == 0
    assert third["snapshots"] == 3 and third["folder_errors"] == 0


def test_root_info_records_serving_checkout_paths(roots):
    from pathlib import Path

    import weather

    info = l5.root_info()
    assert info["weather_module_file"] == str(Path(weather.__file__).resolve())
    assert info["stage_replay_file"] == str(Path(l5.__file__).resolve())
    assert Path(info["stage_replay_file"]).is_file()
    assert Path(info["weather_module_file"]).is_absolute()


# --- the three variants that read 0.000 on Toronto: live wiring vs structural --

def _late_record(swob_max=None):
    from weather.backtesting.replay import parse_built_at

    record = _record("late", 17)
    if swob_max is not None:
        record["sources"]["eccc_swob"] = {"ok": True, "data": {
            "same_day_max_native": swob_max, "same_day_max_c": swob_max}}
    model = _factory("atlanta")
    model.set_target_date(datetime(2026, 9, 20).date())
    return model, record, parse_built_at(record)


def _variant_tv(model, record, now, variant):
    base, _ = l5._run(model, record["sources"], now)
    with l5.variant_context(model, variant, record["sources"], now) as srcs:
        alt, _ = l5._run(model, srcs, now)
    return l5._delta(alt, base)["tv"]


def test_wu_residual_variant_can_change_the_served_vector(roots):
    # Station high 89.06F (bucket 89); a SWOB same-day max of 96F leads it, so the
    # observed-floor stage pushes bucket 89 below the 0.001 residual and the
    # repointed residual restores it. Without a leading support source: no-op.
    model, record, now = _late_record(swob_max=96.0)
    assert l5._station_high(model, record["sources"], now) == pytest.approx(89.06)
    assert _variant_tv(model, record, now, "wu_residual_repointed") > 1e-4
    model, record, now = _late_record()
    assert _variant_tv(model, record, now, "wu_residual_repointed") == 0.0


def test_metar_signal_and_intraday_tail_shims_reach_the_call_site(roots):
    model, record, now = _late_record()
    seen = {}

    def metar_spy(metar_temp, history_max, hour=None):
        seen.setdefault("metar", []).append(history_max)
        return (95.0, 1.0, 1.0)  # a forced strong vote

    def tail_spy(scores, *, observed_bucket, intraday, **kwargs):
        seen.setdefault("tail", []).append((observed_bucket, intraday))
        return scores

    model.learned_metar_live_signal = metar_spy
    model.distribution_intraday_tail_stage = tail_spy
    with l5.variant_context(model, "metar_live_signal_repointed", record["sources"], now) as srcs:
        l5._run(model, srcs, now)
    with l5.variant_context(model, "intraday_tail_repointed", record["sources"], now) as srcs:
        l5._run(model, srcs, now)
    # the shim delivers the station high, so neither variant is a wiring no-op ...
    assert seen["metar"][0] == pytest.approx(89.06)  # repointed call (WU history is empty)
    assert seen["metar"][1] is None  # the unshimmed call in the tail run
    assert seen["tail"] == [(None, None), (89, None)]
    # ... but on the feature (hgb) path the METAR vote is discarded (the feature
    # live-signal list never includes it) and the tail has no intraday input.
    base_model, record, now = _late_record()
    base, _ = l5._run(base_model, record["sources"], now)
    forced_model, _, _ = _late_record()
    forced_model.learned_metar_live_signal = lambda *a, **k: (95.0, 1.0, 1.0)
    forced, _ = l5._run(forced_model, record["sources"], now)
    assert l5._delta(forced, base)["tv"] == 0.0


def test_intraday_tail_shim_changes_the_stage_when_intraday_exists(roots):
    model, record, now = _late_record()
    scores = {b: 1.0 for b in range(80, 100)}
    kwargs = dict(intraday={"probabilities": {89: 0.9, 90: 0.1}}, hour=15,
                  weather_forecast_max=None, open_meteo_max=None, nws_forecast_max=None,
                  global_ensemble_max=None, eccc_forecast_high=None)
    base = model.distribution_intraday_tail_stage(dict(scores), observed_bucket=None, **kwargs)
    with l5.variant_context(model, "intraday_tail_repointed", record["sources"], now):
        alt = model.distribution_intraday_tail_stage(dict(scores), observed_bucket=None, **kwargs)
    assert l5._delta(model.normalize_scores(alt), model.normalize_scores(base))["tv"] > 1e-3


# --- M8 served-vector reproduction ------------------------------------------

def test_served_repro_compares_recorded_distribution(tmp_path, roots, climatology_ok):
    from tools.research.model_edge_lever5 import served_repro as sr
    from weather.backtesting.replay import parse_built_at

    model = _factory("atlanta")
    exact, shifted = _record("exact", 16), _record("shifted", 16)
    model.set_target_date(datetime(2026, 9, 20).date())
    served, _ = l5._run(model, exact["sources"], parse_built_at(exact))
    exact["recorded_distribution"] = {str(k): v for k, v in served.items()}
    moved = dict(served)
    top = max(moved, key=moved.get)
    moved[top] -= 0.01
    moved[top + 1] = moved.get(top + 1, 0.0) + 0.01
    shifted["recorded_distribution"] = {str(k): v for k, v in moved.items()}
    folder = tmp_path / "snaps" / SLUG.format(day=20)
    folder.mkdir(parents=True)
    with (folder / "replay_inputs.jsonl").open("w", encoding="utf-8") as handle:
        for record in (exact, shifted, _record("none", 9)):
            handle.write(json.dumps(record) + "\n")
    summary = sr.run(l5.select_folders(tmp_path / "snaps"), tmp_path / "served.jsonl",
                     model_factory=_factory, emit=lambda line: None)
    market = summary["markets"]["atlanta"]
    assert market["n"] == 3 and market["errors"] == 1  # "none" has no recorded_distribution
    assert market["mismatches"] == 1 and market["share_within_tol"] == 0.5
    assert market["max_max_abs"] == pytest.approx(0.01)
    rows = {r["snapshot_id"]: r for r in _rows(tmp_path / "served.jsonl") if r.get("kind") == "snapshot"}
    assert rows["exact"]["max_abs"] <= sr.TOL and rows["none"]["error"] == "no_recorded_distribution"
    assert sr.identity_reasons(None, {}) == ["recorded_identity_missing"]
    recorded = {"model_version": "a", "active_model_kind": "hgb", "code_hash": "x", "artifact_hash": "y",
                "code_files": [{"path": "src/m.py", "sha256": "1"}], "artifact_files": []}
    replayed = dict(recorded, code_hash="z", code_files=[{"path": "src/m.py", "sha256": "2"}])
    assert sr.identity_reasons(recorded, replayed) == ["code_changed:src/m.py"]
    assert sr.identity_reasons(recorded, dict(recorded)) == []
