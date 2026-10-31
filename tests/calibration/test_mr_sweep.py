"""MR P0 sweep (lane L3, 2026-10-30; rule 85f8192c, dev-window ledger row 78).

Guards: Benjamini-Hochberg adjusted q-values; the band representative z and the market moments; the reviewer's
disagreement placebo (clip to [EPS, 1], renormalise to sum(m), a different-date donor, identity when c = m); the
tilt (mass preserved, the market on uncovered snapshots); capture-time coverage (a receipt after capture, a METAR
report after capture, a non-matching METAR date and a non-``ok`` source are uncovered); the replay extraction; the
paired P0 (a planted signal survives, a null signal does not, the run is deterministic, thin coverage is
UNTESTABLE); and the run refuses a dirty tree, a missing SHA256SUMS or an existing receipt before reading a layout.
"""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    sw = importlib.import_module("weather.calibration.mr_sweep")
    mb = importlib.import_module("weather.calibration.market_blend")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])


class FakeTable:
    brier = sc.Table.brier
    log_score = sc.Table.log_score
    cells = sc.Table.cells

    def __init__(self, frame, dates):
        f = frame[frame.date.isin(dates)].reset_index(drop=True)
        self.snaps = f[["row_key", "date", "captured_at_utc", "market", "local_hour"]].copy()
        k = len(f)
        self.n = np.full(k, 5)
        self.offsets = np.arange(k) * 5
        self.band_snap = np.repeat(np.arange(k), 5)
        self.snap_pos = pd.Series(np.arange(k), index=f.row_key.to_numpy())
        self.bands = pd.DataFrame({"band_index": np.tile(np.arange(5), k), "kind": KINDS * k,
                                   "low": LOWS * k, "high": HIGHS * k})
        self.p_market = np.concatenate(f.pm.to_list())
        self.y = np.concatenate([np.eye(5)[w] for w in f.winner])
        self.local_hour = f.local_hour.to_numpy(int)
        self.markets = f.market.to_numpy()
        self.x_info = f.x_info.to_numpy(float)
        self.x_null = f.x_null.to_numpy(float)
        self.impossible = np.zeros(len(self.y), bool)
        keys = sorted(set(zip(f.date, f.market)))
        index = {key: i for i, key in enumerate(keys)}
        self.keys = keys
        self.cell = np.array([index[key] for key in zip(f.date, f.market)], int)
        self.w = sc.crossed_weights([key[0] for key in keys], [key[1] for key in keys])
        self.w_date = sc.crossed_weights([key[0] for key in keys], ["all"] * len(keys))


def _frame(seed=7, n_dates=30, hours=range(24), scale=0.98):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(1, n_dates + 1):
        day = f"2026-08-{d:02d}"
        for market in ("atlanta", "nyc", "miami"):
            for hour in hours:
                pm = rng.dirichlet(np.ones(5) * 2)
                q = rng.dirichlet(pm * 4 + 1e-3)  # calibrated: E[q | pm] = pm
                winner = int(rng.choice(5, p=q / q.sum()))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm * scale,
                             "winner": winner, "x_info": Z[winner] + rng.normal(0, 1.5),
                             "x_null": 62 + rng.normal(0, 3)})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def tables():
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t = FakeTable(frame, dates)
    score_t = FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    score_dates = np.array(sorted(score_t.snaps.date.unique()))
    return fit_t, score_t, score_dates, sw.boot_counts(len(score_dates), draws=1000, seed=3)


def test_bh_adjust_matches_hand_values():
    adj, rej = sw.bh_adjust([0.01, 0.04, 0.03, 0.005])
    assert adj.tolist() == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert rej.all()
    adj, rej = sw.bh_adjust([0.2, 0.01, 0.9], q=0.05)
    assert adj.tolist() == pytest.approx([0.3, 0.03, 0.9]) and rej.tolist() == [False, True, False]
    assert sw.bh_adjust([1.0] * 17)[0].max() == 1.0


def test_band_geometry_representatives_and_moments(tables):
    fit_t = tables[0]
    geo = sw.band_geometry(fit_t)
    assert geo["z"][:5].tolist() == Z.tolist()
    mt = fit_t.p_market[:5] / fit_t.p_market[:5].sum()
    assert geo["mu"][0] == pytest.approx(float(mt @ Z))
    assert geo["var"][0] == pytest.approx(max(float(mt @ (Z - mt @ Z) ** 2), sw.SIGMA2_FLOOR))
    assert geo["tot"][0] == pytest.approx(0.98)


def test_tilt_preserves_mass_and_leaves_uncovered_snapshots(tables):
    fit_t = tables[0]
    geo = sw.band_geometry(fit_t)
    cov = fit_t.local_hour != 3
    s = sw.band_signal("C", 1, np.where(cov, fit_t.x_info, np.nan), fit_t, geo)
    c, sd = sw.tilt(fit_t, geo, s, cov)
    sums = np.bincount(fit_t.band_snap, weights=c)
    assert np.allclose(sums, geo["tot"]) and sd > 0
    unc = ~cov[fit_t.band_snap]
    assert np.array_equal(c[unc], fit_t.p_market[unc]) and not np.allclose(c[~unc], fit_t.p_market[~unc])
    for kind in ("S", "D"):
        s2 = sw.band_signal(kind, -1, np.where(cov, fit_t.x_null, np.nan), fit_t, geo)
        assert np.isfinite(s2[~unc]).all() and np.isnan(s2[unc]).all()


def test_disagreement_placebo_clips_renormalises_and_uses_other_dates(tables):
    fit_t = tables[0]
    m = fit_t.p_market
    same, _ = sw.disagreement_placebo(fit_t, m.copy(), seed=20260921)
    assert np.allclose(same, m)
    rng = np.random.default_rng(1)
    c = m + rng.normal(0, 0.3, m.size)  # pushes some entries outside [EPS, 1]
    pl, meta = sw.disagreement_placebo(fit_t, c, seed=20260921)
    assert np.allclose(np.bincount(fit_t.band_snap, weights=pl), np.bincount(fit_t.band_snap, weights=m))
    assert pl.min() > 0 and meta["same_date_donors"] == 0
    donor, _ = mb.placebo_vector(fit_t, c - m, seed=20260921)
    raw = np.clip(m + donor, mb.EPS, 1.0)
    assert pl[:5] == pytest.approx(raw[:5] * m[:5].sum() / raw[:5].sum())
    pos, _ = sw.donor_positions(fit_t, 20260925)
    assert np.array_equal(c[pos], mb.placebo_vector(fit_t, c, seed=20260925)[0])
    cached, _ = sw.disagreement_placebo(fit_t, c, 20260925, sw.donor_positions(fit_t, 20260925))
    assert np.array_equal(cached, sw.disagreement_placebo(fit_t, c, seed=20260925)[0])


def _snaps():
    return pd.DataFrame({"row_key": ["nyc|a", "nyc|b", "nyc|c", "nyc|d"],
                         "captured_at_utc": ["2026-08-20T04:00:50+00:00"] * 4,
                         "v2_p10": [60, 60, 60, 60], "v2_p50": [62, 62, 62, 62], "v2_p90": [66, 66, 60, 66],
                         "v2_status": ["available"] * 4,
                         "v2_available_basis": ["response_received_at"] * 3 + ["other"],
                         "v2_available_at": ["2026-08-20T03:00:00Z", "2026-08-20T05:00:00Z",
                                             "2026-08-20T03:00:00Z", "2026-08-20T03:00:00Z"]})


def _record(sid, fetched="2026-08-20T00:00:38.270278-04:00", report="2026-08-20T04:00:00.000Z", match=True,
            om_ok=True):
    return {"snapshot_id": sid, "captured_at_utc": "2026-08-20T04:00:30Z", "sources": {
        "open_meteo_multimodel": {"ok": om_ok, "fetched_at": fetched, "data": {
            "day_model_highs": {"gfs_seamless": 70.0, "ncep_hrrr_conus": 71.0, "ncep_nam_conus": None},
            "day_high_spread": 2.0}},
        "open_meteo": {"ok": True, "fetched_at": fetched, "data": {"day_max_native": 69.5}},
        "global_ensemble": {"ok": True, "fetched_at": fetched,
                            "data": {"day_max_native": 68.0, "day_member_high_p10": 65.0, "day_member_high_p90": 71.0}},
        "metar": {"ok": True, "fetched_at": fetched, "data": {
            "temp_native": 66.0, "same_day_max_native": 68.0, "dewpoint_native": 50.0, "cover": "BKN030",
            "report_time": report, "target_date_match": match}}}}


def test_record_features_and_capture_time_coverage():
    f = sw.record_features(_record("a"))
    assert f["mm_gfs_seamless"] == 70.0 and np.isnan(f["mm_ncep_nam_conus"]) and f["ge_centre"] == 68.0
    assert f["met_cooling"] == -2.0 and f["met_dewdep"] == 16.0 and f["met_cover"] == 3.0
    assert np.isnan(f["gm_ecmwf_ifs025"]) and f["rc_gm"] is None  # source absent
    assert np.isnan(sw.record_features(_record("x", om_ok=False))["mm_gfs_seamless"])
    assert np.isnan(sw.record_features(_record("x", match=False))["met_max"])
    assert sw._cover("OVC") == 4 and sw._cover("CLR") == 0 and np.isnan(sw._cover("???")) and np.isnan(sw._cover(None))
    feats = pd.DataFrame([{"row_key": "nyc|a", **sw.record_features(_record("a"))},
                          {"row_key": "nyc|b", **sw.record_features(_record("b", fetched="2026-08-20T00:01:00-04:00"))},
                          {"row_key": "nyc|c", **sw.record_features(_record("c", report="2026-08-20T04:05:00Z"))}])
    v = sw.candidate_values(_snaps(), feats)
    assert v["OM-GFS"][:3].tolist()[0] == 70.0 and np.isnan(v["OM-GFS"][1]) and v["OM-GFS"][2] == 70.0
    assert np.isnan(v["OM-GFS"][3])  # no replay record
    assert v["MET-MAX"][0] == 68.0 and np.isnan(v["MET-MAX"][2])  # report after capture
    assert v["NBM-SKEW"][0] == pytest.approx((66 + 60 - 2 * 62) / (66 - 60))
    assert np.isnan(v["NBM-SKEW"][1]) and np.isnan(v["NBM-SKEW"][2]) and np.isnan(v["NBM-SKEW"][3])


def test_extract_features_reads_only_layout_snapshots(tmp_path):
    folder = tmp_path / "snapshots" / "highest-temperature-in-nyc-on-august-20-2026"
    folder.mkdir(parents=True)
    other = tmp_path / "snapshots" / "highest-temperature-in-toronto-on-august-20-2026"
    other.mkdir()
    (folder / "replay_inputs.jsonl").write_text(
        "".join(json.dumps(_record(s)) + "\n" for s in ("a", "b", "zz")) + json.dumps(_record("b"))[:200] + "\n",
        encoding="utf-8")
    (other / "replay_inputs.jsonl").write_text(json.dumps(_record("a")) + "\n", encoding="utf-8")
    feats, n, bad = sw.extract_features(tmp_path, {"nyc|a", "nyc|b"})
    assert n == 2 and sorted(feats.row_key) == ["nyc|a", "nyc|b"]  # the truncated duplicate of b is skipped
    assert len(bad) == 1 and bad[0]["line"] == 4 and bad[0]["snapshot_ids"] == ["b"]
    assert feats.set_index("row_key").loc["nyc|b", "mm_gfs_seamless"] == 70.0
    with pytest.raises(sw.SweepError):
        sw.extract_features(tmp_path, {"nyc|q"})


def test_p0_planted_signal_survives_and_null_does_not(tables):
    fit_t, score_t, score_dates, counts = tables
    geo = sw.band_geometry(fit_t)
    info, vecs = sw.p0_candidate("info", "C", 1, fit_t.x_info, fit_t, score_t, geo, counts, score_dates)
    assert info["testable"] and info["p0"]["ci95"][0] > 0 and info["p0"]["p_one_sided"] < 0.01
    assert abs(info["p0"]["rho_pl_mean"]) < info["p0"]["rho_c"] and len(info["p0"]["rho_pl_by_seed"]) == 20
    assert set(info["by_block"]) == {"00-05", "06-09", "10-12", "13-16", "17-23"}
    assert len(info["_rows"]) == len(score_dates) and len(info["_rows"][0]["sums_pl"]) == 20
    assert sum(r["n_snapshots"] for r in info["_rows"]) == info["coverage"]["population_snapshots"]
    assert vecs["c_fit"].shape == fit_t.p_market.shape
    null, _ = sw.p0_candidate("null", "C", 1, fit_t.x_null, fit_t, score_t, geo, counts, score_dates)
    assert null["testable"] and null["p0"]["ci95"][0] <= 0 and null["p0"]["p_one_sided"] > 0.05
    again, _ = sw.p0_candidate("info", "C", 1, fit_t.x_info, fit_t, score_t, geo, counts, score_dates)
    assert again["p0"] == info["p0"]
    thin = np.where(fit_t.local_hour < 2, fit_t.x_info, np.nan)
    res, vec = sw.p0_candidate("thin", "C", 1, thin, fit_t, score_t, geo, counts, score_dates)
    assert not res["testable"] and res["p0"]["p_one_sided"] == 1.0 and vec is None


def test_paired_delta_pairs_draw_b_with_seed_b_mod_j():
    rng = np.random.default_rng(0)
    didx = np.repeat(np.arange(10), 40)
    e = rng.normal(size=didx.size)

    def sums(k):
        return sw.date_sums(k * e + rng.normal(size=didx.size), e, didx, 10)

    sums_c, sums_pl = sums(0.3), [sums(0.0) for _ in range(3)]
    counts = sw.boot_counts(10, draws=200, seed=1)
    r = sw.paired_delta(sums_c, sums_pl, counts)
    boot_c = sw.mg._rho(*(counts @ sums_c.T).T)
    boot_pl = np.array([sw.mg._rho(*(counts[i] @ sums_pl[i % 3].T)) for i in range(200)])
    delta_b = boot_c - boot_pl
    assert r["valid_draws"] == 200 and r["p_one_sided"] == (1 + np.sum(delta_b <= 0)) / 201
    assert r["ci95"] == pytest.approx(np.quantile(delta_b, [0.025, 0.975]).tolist())
    rho_pl = [float(sw.mg._rho(*s.sum(axis=1))) for s in sums_pl]
    assert r["delta"] == pytest.approx(float(sw.mg._rho(*sums_c.sum(axis=1))) - np.mean(rho_pl))


def test_run_refuses_before_reading_the_layout(tmp_path, monkeypatch):
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(sw.ls, "code_state", lambda *a: clean)
    with pytest.raises(sw.SweepError, match="SHA256SUMS"):
        sw.run(layout=tmp_path / "absent", out_dir=tmp_path / "o", replay_root=tmp_path)
    (tmp_path / "o2").mkdir()
    (tmp_path / "o2" / "mr_sweep.json").write_text("{}", encoding="utf-8")
    with pytest.raises(sw.SweepError, match="overwrite"):
        sw.run(layout=tmp_path / "absent", out_dir=tmp_path / "o2", replay_root=tmp_path)
    monkeypatch.setattr(sw.ls, "code_state", lambda *a: dict(clean, dirty=True, dirty_paths=["?? x"]))
    with pytest.raises(sw.ls.ScreenError, match="dirty tree"):
        sw.run(layout=tmp_path / "absent", out_dir=tmp_path / "o3", replay_root=tmp_path)


def test_rule_constants():
    assert len(sw.CANDIDATES) == 17 and len({c[0] for c in sw.CANDIDATES}) == 17
    assert sw.RULE_SHA256.startswith("85f8192c") and sw.DRAWS == 10_000 and sw.SEED == 20261024
    assert sw.PLACEBO_SEEDS == tuple(range(20260921, 20260941)) and sw.BH_Q == 0.10
    assert [c[2] for c in sw.CANDIDATES if c[0] == "MET-COVER"] == [-1]


def test_run_end_to_end_on_a_synthetic_table(tmp_path, monkeypatch):
    """The whole run on a fake table: one planted candidate survives and reaches the w gate, the rest do not."""
    frame = _frame(seed=9, scale=1.0)
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    lay = type("Lay", (), {"manifest_sha256": "f" * 64})()
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(sw.ls, "code_state", lambda *a: clean)
    monkeypatch.setattr(sw.mg, "build_tables", lambda layout: (lay, [], dates[:7], dates[7:], fit_t, score_t))
    monkeypatch.setattr(sw.mg, "market_controls", lambda f, s: {"served": {"verdict": "PASS"}})
    monkeypatch.setattr(sw, "extract_features", lambda root, keys: (pd.DataFrame({"row_key": sorted(keys)}), 7, []))
    values = {c[0]: np.where(fit_t.local_hour < 1, fit_t.x_null, np.nan) for c in sw.CANDIDATES}
    values["OM-GFS"] = fit_t.x_info
    values["OM-NAM"] = fit_t.x_null
    monkeypatch.setattr(sw, "candidate_values", lambda snaps, feats: values)
    monkeypatch.setattr(sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    (tmp_path / "replay").mkdir()
    (tmp_path / "replay" / "SHA256SUMS").write_text("x", encoding="utf-8")
    rec = sw.run(layout=tmp_path / "lay", out_dir=tmp_path / "out", replay_root=tmp_path / "replay")
    res = rec["results"]
    assert res["OM-GFS"]["verdict"] == "SURVIVE" and "w_gate" in res["OM-GFS"]
    assert res["OM-NAM"]["verdict"] == "KILL" and res["OM-HRRR"]["verdict"] == "UNTESTABLE"
    assert rec["controls"]["w0_identity_OM-GFS"]["verdict"] == "PASS"
    assert len(rec["lines"]) == 17 and rec["lines"][0].startswith("SURVIVE: OM-GFS delta +")
    rows = [json.loads(x) for x in (tmp_path / "out" / "mr_sweep_rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["candidate"] for r in rows} == {"OM-GFS", "OM-NAM"} and len(rows) == 2 * len(dates[7:])
    assert all("w" in r and "paired_brier" in r for r in rows if r["candidate"] == "OM-GFS")
    assert (tmp_path / "out" / "features.parquet").exists() and rec["rows_sha256"]
    with pytest.raises(sw.SweepError, match="overwrite"):
        sw.run(layout=tmp_path / "lay", out_dir=tmp_path / "out", replay_root=tmp_path / "replay")
