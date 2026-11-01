"""DSC-NWS P0 at 07-12 (ruling R28a, lane L40; rule aaa8d5f3).

Guards: the label-free stage 1 table equals ``dev_scorecard.Table`` on everything but the labels; the replay
extraction keeps the last record per snapshot, counts malformed lines and refuses a file whose sha differs from
SHA256SUMS; the capture-time gates (METAR report after capture, NWS receipt after capture, a non-available NBM v2)
uncover the arm; the rebuilt per-date sums reproduce ``p0_candidate``; the wider interval takes min / max; C5's
planted SYN+ passes on an informative table; the section 5.1 verdict order; stage 2 refuses a wrong stage 1 sha
and a second look.
"""
import hashlib
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    dsc = importlib.import_module("weather.calibration.dsc_nws_p0")
    sw = importlib.import_module("weather.calibration.mr_sweep")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
    data = importlib.import_module("weather.reporting.scorecards.dev_scorecard_data")
    from tests.calibration.test_mr_sweep import FakeTable, _frame
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise


@pytest.fixture(scope="module")
def tables():
    frame = _frame(seed=11, n_dates=26)
    dates = sorted(frame.date.unique())
    fit_t = FakeTable(frame, dates)
    score_t = FakeTable(frame, [d for d in dates if d >= "2026-08-05"])
    score_dates = np.array(sorted(score_t.snaps.date.unique()))
    return fit_t, score_t, score_dates, sw.boot_counts(len(score_dates), draws=1000, seed=3)


def test_label_free_table_matches_scorecard_table():
    rng = np.random.default_rng(1)
    snaps, bands, market, labels = [], [], [], []
    for d in ("2026-08-01", "2026-08-02", "2026-08-03"):
        for i in range(4):
            rk = f"nyc|{d}-{i}"
            snaps.append({"row_key": rk, "date": d, "market": "nyc", "local_hour": 7 + i, "n_bands": 3,
                          "captured_at_utc": f"{d}T1{i}:00:00Z", **{f: 70.0 for f in data.FLOOR_FIELDS}})
            pm = rng.dirichlet(np.ones(3))
            for b in range(3):
                bands.append({"row_key": rk, "band_index": b, "kind": ["lte", "eq", "gte"][b], "low": 60 + 2 * b,
                              "high": 61 + 2 * b, "p_served": 1 / 3})
                market.append({"row_key": rk, "band_index": b, "p_market_yes": pm[b]})
            labels.append({"row_key": rk, "winner": i % 3})
    lay = data.Layout(snaps=pd.DataFrame(snaps), bands=pd.DataFrame(bands), labels=pd.DataFrame(labels),
                      market=pd.DataFrame(market), manifest_sha256="x", file_sha256={}, label_source="t")
    dates = ["2026-08-02", "2026-08-03"]
    full = sc.Table(lay, dates)
    free = dsc.LabelFreeTable(lay.snaps, lay.bands, lay.market, dates)
    assert not hasattr(free, "y")
    assert free.snaps.row_key.tolist() == full.snaps.row_key.tolist()
    for attr in ("n", "offsets", "band_snap", "p_market", "local_hour", "markets"):
        assert np.array_equal(getattr(free, attr), getattr(full, attr)), attr
    assert free.snap_pos.equals(full.snap_pos)


def _write_replay(root, lines):
    folder = root / "snapshots" / "highest-temperature-in-nyc-on-august-2-2026"
    folder.mkdir(parents=True)
    f = folder / "replay_inputs.jsonl"
    f.write_bytes("".join(lines).encode("utf-8"))
    sums = f"{hashlib.sha256(f.read_bytes()).hexdigest()}  snapshots/{folder.name}/replay_inputs.jsonl\n"
    (root / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return f


def _rec(sid, nws=75.0, report="2026-08-02T13:00:00Z"):
    return json.dumps({"snapshot_id": sid, "captured_at_utc": "2026-08-02T12:30:00Z", "sources": {
        "nws_grid": {"ok": True, "fetched_at": "2026-08-02T12:00:00Z", "data": {"day_rows": [
            {"max_temp_native": nws}]}},
        "metar": {"ok": True, "fetched_at": "2026-08-02T12:10:00Z",
                  "data": {"report_time": report, "target_date_match": True}}}}) + "\n"


def test_extract_replay_keep_last_malformed_and_sha(tmp_path, monkeypatch):
    lines = [_rec("a", 70.0), '{"snapshot_id": "a", "sources": {"nws_grid": {trunc\n', _rec("a", 71.0),
             _rec("zz", 99.0)]
    _write_replay(tmp_path, lines)
    monkeypatch.setattr(dsc, "REPLAY_SUMS_SHA256", hashlib.sha256((tmp_path / "SHA256SUMS").read_bytes()).hexdigest())
    snaps = pd.DataFrame({"market": ["nyc"], "snapshot_id": ["a"], "row_key": ["nyc|a"]})
    frame, stats = dsc.extract_replay(tmp_path, snaps)
    assert frame.nws_max.tolist() == [71.0] and stats["records_matched"] == 2
    assert len(stats["malformed_lines"]) == 1 and stats["row_keys_matched"] == 1
    (tmp_path / "snapshots" / "highest-temperature-in-nyc-on-august-2-2026" / "replay_inputs.jsonl").write_bytes(
        "".join(lines[:1]).encode("utf-8"))
    with pytest.raises(dsc.DscError, match="differs from SHA256SUMS"):
        dsc.extract_replay(tmp_path, snaps)


def test_capture_time_gates_uncover_the_arms():
    cap = "2026-08-02T12:30:00Z"
    snaps = pd.DataFrame({"row_key": ["k1", "k2", "k3", "k4"], "captured_at_utc": [cap] * 4, "local_hour": [9] * 4,
                          "v2_mean": [74.0] * 4, "v2_status": ["available", "available", "available", "missing"],
                          "v2_available_basis": ["response_received_at"] * 4,
                          "v2_available_at": ["2026-08-02T11:00:00Z"] * 4})
    feats = pd.DataFrame([
        {"row_key": "k1", **dsc.record_fields(json.loads(_rec("x", report="2026-08-02T12:00:00Z")))},
        {"row_key": "k2", **dsc.record_fields(json.loads(_rec("x", report="2026-08-02T13:00:00Z")))},
        {"row_key": "k3", **dsc.record_fields(json.loads(_rec("x", report="2026-08-02T12:00:00Z")))},
        {"row_key": "k4", **dsc.record_fields(json.loads(_rec("x", report="2026-08-02T12:00:00Z")))}])
    feats.loc[2, "nws_fetched_at"] = "2026-08-02T12:45:00Z"  # NWS received after capture
    nowcast = pd.DataFrame({"row_key": ["k1", "k2", "k3", "k4"], "n_own": [76.0] * 4}).set_index("row_key")
    values, _, diag = dsc.arm_values(snaps, feats, nowcast, np.full(4, 73.0))
    w1, fade, gap = values["W1-0712"], values["NWS-FADE-0712"], values["NWS-GAP-0712"]
    assert w1[0] == pytest.approx(np.log(2.0)) and np.isnan(w1[1]) and np.isnan(w1[3])
    assert diag["w1_metar_gate_drops"]["report_after_cap"] == 1
    assert fade[0] == pytest.approx(2.0) and np.isnan(fade[2]) and fade[3] == pytest.approx(2.0)
    assert gap[0] == pytest.approx(-1.0) and np.isnan(gap[2]) and np.isnan(gap[3])


def test_wider_interval_reproduces_p0_and_c5_runs(tables):
    fit_t, score_t, score_dates, counts = tables
    geo = sw.band_geometry(fit_t)
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    vals = np.where(fit_t.local_hour != 8, fit_t.x_info - geo["mu"], np.nan)
    res, vecs = sw.p0_candidate("T", "D", 1, vals, fit_t, score_t, geo, counts, score_dates, donors)
    rows = res["_rows"]
    sums_c = np.array([r["sums_c"] for r in rows], float).T
    sums_pl = [np.array([r["sums_pl"][j] for r in rows], float).T for j in range(len(sw.PLACEBO_SEEDS))]
    iv = dsc.wider_interval(sums_c, sums_pl, counts)
    assert iv["delta"] == res["p0"]["delta"] and iv["ci95_date_clustered"] == res["p0"]["ci95"]
    assert iv["ci95_wider"][0] == min(iv["ci95_date_clustered"][0], iv["ci95_block3"][0])
    assert iv["ci95_wider"][1] == max(iv["ci95_date_clustered"][1], iv["ci95_block3"][1])
    assert iv["se_wider"] == max(iv["se_date_clustered"], iv["se_block3"]) and 0 <= iv["power_at_edge"] <= 1
    sc2, sp2, n_snaps, n_dates = dsc.sums_for_vector(vecs["c_fit"], vecs["covered"], fit_t, score_t, score_dates,
                                                     donors)
    assert np.array_equal(sc2, sums_c) and n_snaps == res["coverage"]["population_snapshots"]
    c5 = dsc.control_c5("T", np.isfinite(vals), fit_t, score_t, geo, score_dates, donors, counts)
    assert c5["SYN+"]["testable"] and c5["SYN+"]["delta"] > 0 > c5["SYN-"]["delta"]
    assert c5["verdict"] in ("PASS", "FAIL")
    json.dumps(c5, default=dsc.mg._default)


def test_verdict_order():
    v = dsc.verdict_for
    assert v(False, False, None, None, None, True) == dsc.LABEL_UNTESTABLE
    assert v(True, False, 1.0, 0.1, 0.05, True) == dsc.LABEL_UNTESTABLE_C5
    assert v(True, True, 0.4, 0.1, 0.05, True) == dsc.LABEL_UNTESTABLE_POWER
    assert v(True, True, 0.9, 0.2235, 0.05, True) == dsc.LABEL_KILL
    assert v(True, True, 0.9, 0.30, 0.05, True) == dsc.LABEL_SURVIVOR
    assert v(True, True, 0.9, 0.30, -0.01, True) == dsc.LABEL_INCONCLUSIVE
    assert v(True, True, 0.9, 0.30, 0.05, False) == dsc.LABEL_INCONCLUSIVE


def test_stage1_load_refuses_wrong_sha_and_marker_blocks_second_look(tmp_path):
    pq = tmp_path / dsc.STAGE1_PARQUET
    pd.DataFrame({"row_key": ["a"]}).to_parquet(pq, index=False)
    rec = {"c0": {"verdict": "PASS"}, "stage1_parquet_sha256": hashlib.sha256(pq.read_bytes()).hexdigest()}
    (tmp_path / dsc.STAGE1_RECEIPT).write_text(json.dumps(rec), encoding="utf-8")
    good = hashlib.sha256((tmp_path / dsc.STAGE1_RECEIPT).read_bytes()).hexdigest()
    with pytest.raises(dsc.DscError, match="--stage1-sha"):
        dsc._load_stage1(tmp_path, "0" * 64)
    assert dsc._load_stage1(tmp_path, good)[1].row_key.tolist() == ["a"]
    dsc.write_exclusive(tmp_path / dsc.LOOK_MARKER, "{}")
    with pytest.raises(FileExistsError):
        dsc.write_exclusive(tmp_path / dsc.LOOK_MARKER, "{}")


def test_machinery_pins_and_out_dir(tmp_path):
    rec = dsc.check_machinery()
    assert rec["rule_sha256"] == dsc.RULE_SHA256 and rec["git_blobs"] == dsc.PINNED_BLOBS
    (tmp_path / "exists").mkdir()
    with pytest.raises(dsc.DscError, match="already exists"):
        dsc.check_out_dir(tmp_path / "exists")
