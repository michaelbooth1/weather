"""MRMS echo against the market P0 (lane L3, 2026-10-30; rule b0f170a5, ledger row 91).

Guards: the archive filter (valid >= 2026-09-30 dropped); F2's join (valid + 5 min <= capture, age <= 40 min, the
market's station, hours outside 13..16); the constructs (-99 -> 0 dBZ, the 35 dBZ flag); the zero-tilt rule for a
market with sd < 1e-9; the pins and the 13-16 block; and the whole run on a synthetic table (a planted type D
signal with sign -1 survives and reaches the w gate, a null is a KILL, the descriptive arm takes no decision,
per-market rows, no overwrite).
"""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    mr = importlib.import_module("weather.calibration.mrms_p0")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

MARKETS = ("atlanta", "nyc", "miami", "houston", "seattle")
KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])


def _refl(rows):
    r = pd.DataFrame(rows, columns=["station", "valid_utc", "max_dbz_25km", "max_dbz_50km"])
    r["cover_25km"], r["cover_50km"] = 1.0, 1.0
    return r


def test_load_refl_filters(tmp_path):
    _refl([["KLGA", "2026-08-20T17:58Z", 40, 45], ["KLGA", "2026-09-30T17:58Z", 40, 45]]).to_parquet(
        tmp_path / "r.parquet", index=False)
    out = mr.load_refl(tmp_path / "r.parquet")
    assert len(out) == 1 and str(out.valid_utc.dtype) == mr.NS_UTC


def test_select_slots_join_and_constructs():
    r = _refl([["KLGA", "2026-08-20T16:58Z", 50, 50], ["KLGA", "2026-08-20T17:28Z", -99, 20],
               ["KLGA", "2026-08-20T17:58Z", 36, 36], ["KMIA", "2026-08-20T17:28Z", 60, 60]])
    r["valid_utc"] = pd.to_datetime(r.valid_utc, utc=True).astype(mr.NS_UTC)
    snaps = pd.DataFrame({"market": ["nyc", "nyc", "nyc", "nyc", "nyc", "toronto"],
                          "captured_at_utc": ["2026-08-20T17:40:00Z",   # 17:28 slot (17:58 + 5 min is later)
                                              "2026-08-20T18:03:00Z",   # 17:58 + 5 min = 18:03 <= capture
                                              "2026-08-20T18:02:00Z",   # not yet: back to 17:28
                                              "2026-08-20T19:00:00Z",   # newest 17:58 is 62 min old -> none
                                              "2026-08-20T17:40:00Z",   # hour 12 -> outside the block
                                              "2026-08-20T17:40:00Z"]})
    hours = np.array([13, 14, 14, 15, 12, 13])
    s = mr.select_slots(snaps, hours, r)
    d = s.max_dbz_25km.to_numpy()
    assert d[0] == -99 and d[1] == 36 and d[2] == -99 and np.isnan(d[3]) and np.isnan(d[4]) and np.isnan(d[5])
    assert str(s.valid_utc.iloc[1]) == "2026-08-20 17:58:00+00:00" and pd.isna(s.valid_utc.iloc[3])
    a = mr.candidate_value(s, "maxdbz", 25)
    b = mr.candidate_value(s, "echo35", 25)
    assert a[0] == 0 and a[1] == 36 and np.isnan(a[3]) and b[0] == 0 and b[1] == 1 and np.isnan(b[3])
    assert mr.candidate_value(s, "maxdbz", 50)[0] == 20


def test_zscore_zero_tilt_market():
    v = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 2.0, np.nan])
    m = np.array(["sf", "sf", "sf", "mia", "mia", "mia", "mia"])
    z, deg = mr.zscore(v, m)
    assert deg == ["sf"] and (z[:3] == 0).all() and np.isnan(z[6])
    assert abs(z[3:6].mean()) < 1e-12 and abs(z[3:6].std() - 1) < 1e-12
    assert np.allclose(mr.sw.standardise(z, m)[:6], z[:6])  # idempotent under the sweep's standardise


def test_clip_amendment_1_and_type_c_identity():
    """A planted |g_z| > 3 is clipped (counted per market); the type C route equals the type D signal exactly."""
    m = np.array(["sf"] * 400 + ["mia"] * 4)
    g = np.r_[np.zeros(397), np.ones(3), [0.0, 1.0, 0.0, 1.0]]
    gz, deg = mr.zscore(g, m)
    assert deg == [] and gz[399] > 3  # the SFO-like rare echo
    gc, n = mr.clip_gz(gz, m)
    assert gc.max() == 3.0 and n == {"mia": 0, "sf": 3} and np.array_equal(gc[:397], gz[:397])
    rng = np.random.default_rng(1)
    k, nb = len(m), 5
    table = type("T", (), {"n": np.full(k, nb), "markets": m})()
    geo = {"mu": rng.normal(62, 2, k), "var": rng.uniform(0.3, 9, k)}
    geo["dz"] = rng.normal(0, 3, k * nb)
    s_c = mr.sw.band_signal("C", 1, mr.as_type_c(gc, -1, geo), table, geo)
    s_d = -np.repeat(gc, nb) * geo["dz"] / np.sqrt(np.repeat(geo["var"], nb))
    assert np.allclose(s_c, s_d)
    s_unclipped = mr.sw.band_signal("D", -1, gz, table, geo)  # the descriptive arm's path re-standardises
    assert np.allclose(s_unclipped, -np.repeat(gz, nb) * geo["dz"] / np.sqrt(np.repeat(geo["var"], nb)))
    assert not np.allclose(s_unclipped, s_c)
    assert {c[0] for c in mr.DESCRIPTIVE} >= {"MRMS-MAXDBZ25-UNCLIPPED", "MRMS-ECHO35-UNCLIPPED"}


def test_pins_and_constants(tmp_path):
    with pytest.raises(mr.MrmsError, match="missing"):
        mr.verify_refl(tmp_path / "x.parquet")
    (tmp_path / "x.parquet").write_bytes(b"x")
    with pytest.raises(mr.MrmsError, match="pinned"):
        mr.verify_refl(tmp_path / "x.parquet")
    assert mr.RULE_SHA256.startswith("b0f170a5") and mr.LEDGER_ROW == 91
    assert mr.REFL_SHA256.startswith("3446d1a6") and mr.mg.BLOCKS["13-16"] == (13, 16) == mr.HOURS
    assert [c[0] for c in mr.CANDIDATES] == ["MRMS-MAXDBZ25", "MRMS-ECHO35"]
    assert {(c[1], c[2], c[4]) for c in mr.CANDIDATES} == {("D", -1, 25)}
    assert {c[4] for c in mr.DESCRIPTIVE} == {25, 50} and mr.CLIP == 3 and mr.SYNTH_SEED == 20261031
    assert mr.LAG == pd.Timedelta(minutes=5) and mr.MAX_AGE == pd.Timedelta(minutes=40) and mr.ECHO_DBZ == 35


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
        self.impossible = np.zeros(len(self.y), bool)
        keys = sorted(set(zip(f.date, f.market)))
        index = {key: i for i, key in enumerate(keys)}
        self.keys = keys
        self.cell = np.array([index[key] for key in zip(f.date, f.market)], int)
        self.w = sc.crossed_weights([key[0] for key in keys], [key[1] for key in keys])
        self.w_date = sc.crossed_weights([key[0] for key in keys], ["all"] * len(keys))


def _frame(seed=11, n_dates=48):
    """Calibrated-looking markets; x_info sits near the winner's band centre (a centre signal the market lacks)."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in (str(x.date()) for x in pd.date_range("2026-08-01", periods=n_dates)):
        for market in MARKETS:
            for hour in range(11, 18):
                pm = np.array([0.1, 0.2, 0.4, 0.2, 0.1]) * rng.uniform(0.9, 1.1, 5)
                pm /= pm.sum()
                winner = int(rng.choice(5, p=[0.1, 0.2, 0.4, 0.2, 0.1]))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm,
                             "winner": winner, "x_info": Z[winner] + rng.normal(0, 0.7)})
    return pd.DataFrame(rows)


def _run(tmp_path, monkeypatch, dbz, out):
    frame = _frame(n_dates=70)
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    lay = type("Lay", (), {"manifest_sha256": "f" * 64})()
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(mr.ls, "code_state", lambda *a: clean)
    monkeypatch.setattr(mr.mg, "build_tables", lambda layout: (lay, [], dates[:7], dates[7:], fit_t, score_t))
    monkeypatch.setattr(mr.mg, "market_controls", lambda f, s: {"served": {"verdict": "PASS"}})
    monkeypatch.setattr(mr, "verify_refl", lambda p: "x")
    monkeypatch.setattr(mr.mp, "check_stations", lambda layout: {m: mr.STATIONS[m] for m in MARKETS})
    monkeypatch.setattr(mr, "load_refl", lambda p: None)
    hours = (fit_t.local_hour >= 13) & (fit_t.local_hour <= 16)

    def fake_select(snaps, local_hour, refl):
        d = np.where(hours, dbz(fit_t), np.nan)
        return pd.DataFrame({"valid_utc": pd.to_datetime(snaps.captured_at_utc.to_numpy(), utc=True),
                             "max_dbz_25km": d, "max_dbz_50km": d, "cover_25km": 1.0, "cover_50km": 1.0})

    monkeypatch.setattr(mr, "select_slots", fake_select)
    monkeypatch.setattr(mr.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    return mr.run(layout=tmp_path / "lay", out_dir=tmp_path / out, refl_path=tmp_path / "r.parquet"), fit_t


def _planted(t):
    """High echo when the winner is a low band (sign -1 is right); seattle never echoes (zero-tilt market)."""
    d = np.where(t.x_info < 61.5, 50.0, -99.0)
    return np.where(t.markets == "seattle", -99.0, d)


def _null(t):
    return np.random.default_rng(5).choice([-99.0, 20.0, 40.0], len(t.snaps))


def test_run_planted_survives_null_killed(tmp_path, monkeypatch):
    rec, fit_t = _run(tmp_path, monkeypatch, _planted, "out")
    a, b = rec["results"]["MRMS-MAXDBZ25"], rec["results"]["MRMS-ECHO35"]
    assert a["verdict"] == "SURVIVE" and b["verdict"] == "SURVIVE" and "w_gate" in a
    assert a["zero_tilt_markets"] == ["seattle"]
    assert rec["controls"]["w0_identity_MRMS-MAXDBZ25"]["verdict"] == "PASS"
    assert set(rec["descriptive"]) == {"MRMS-MAXDBZ50", "MRMS-ECHO35-50", "MRMS-MAXDBZ25-UNCLIPPED",
                                       "MRMS-ECHO35-UNCLIPPED"}
    assert a["type"] == "D" and a["sign"] == -1 and set(a["clipped_snapshots"]) == set(MARKETS)
    assert rec["amendment_1_sha256"].startswith("cb30891f")
    assert rec["controls"]["synthetic_sign_pos"]["verdict"] == "PASS"
    assert rec["controls"]["synthetic_sign_pos"]["p0"]["delta"] > 0
    assert rec["controls"]["synthetic_sign_neg"]["verdict"] == "PASS"
    assert rec["controls"]["synthetic_sign_neg"]["p0"]["delta"] < 0
    assert all("verdict" not in r and "w_gate" not in r for r in rec["descriptive"].values())
    in_block = int(((fit_t.local_hour >= 13) & (fit_t.local_hour <= 16)).sum())
    assert a["coverage"]["fit_covered_snapshots"] == in_block
    rows = [json.loads(x) for x in (tmp_path / "out" / "mrms_p0_rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["market"] for r in rows if r.get("candidate") == "MRMS-ECHO35" and "market" in r} == set(MARKETS)
    assert rec["lines"][0].startswith("SURVIVE: MRMS-MAXDBZ25 delta +") and rec["qc"]["cover_25km_below_1"] == 0
    feats = pd.read_parquet(tmp_path / "out" / "features.parquet")
    assert {"MRMS-ECHO35_g", "MRMS-ECHO35_gz", "cover_25km", "slot_valid_utc"} <= set(feats.columns)
    with pytest.raises(mr.MrmsError, match="overwrite"):
        mr.run(layout=tmp_path / "lay", out_dir=tmp_path / "out", refl_path=tmp_path / "r.parquet")
    null, _ = _run(tmp_path, monkeypatch, _null, "out2")
    assert {r["verdict"] for r in null["results"].values()} == {"KILL"}
    assert all("w_gate" not in r for r in null["results"].values())


def test_synthetic_sign_control_failure_voids_the_run(tmp_path, monkeypatch):
    """Amendment 1 A4: a synthetic control that cannot pass (pure noise) makes the run VOID before any candidate."""
    def noise(fit_t, geo, covered, seed=mr.SYNTH_SEED):
        g = np.where(covered, np.random.default_rng(seed).normal(0, 1, len(covered)), np.nan)
        return g, -g

    monkeypatch.setattr(mr, "synthetic_residual", noise)
    with pytest.raises(mr.MrmsError, match="VOID"):
        _run(tmp_path, monkeypatch, _planted, "void")
    rec = json.loads((tmp_path / "void" / "mrms_p0.json").read_text(encoding="utf-8"))
    assert rec["verdict"] == "VOID" and "results" not in rec and "synthetic_sign_pos" in rec["void_controls"]
