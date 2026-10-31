"""Marine market-residual P0 (lane L3, 2026-10-30; rule a374f771, dev-window ledger row 87).

Guards: the CO-OPS and NDBC parsers (no-data replies, missing codes, gzip); the onshore value (inclusive sector,
wrap-around, NaN on a missing speed or direction); the as-of rule (obs + lag <= capture, obs >= capture - 6 h,
nothing at or after 2026-09-30); the station priority fallback and the population (six markets, 07..12); the
registry pin; the raw manifest check; and the whole run on a synthetic table (both-lag survival, per-market rows,
no overwrite).
"""
import gzip
import hashlib
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    mp = importlib.import_module("weather.calibration.marine_p0")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])
NDBC_TEXT = ("#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS  TIDE\n"
             "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC   mi    ft\n"
             "2026 08 01 00 50 250  5.0  6.0  0.5  8.0  5.0 999 1015.0  20.0  18.5  15.0 99.0 99.00\n"
             "2026 08 01 01 50 999 99.0  6.0  0.5  8.0  5.0 999 1015.0  20.0 999.0  15.0 99.0 99.00\n"
             "2026 09 30 00 50 250  5.0  6.0  0.5  8.0  5.0 999 1015.0  20.0  18.5  15.0 99.0 99.00\n")


def test_parse_coops_and_no_data_reply():
    w = mp.parse_coops("Date Time, Speed, Direction, Direction, Gust, X, R \n2026-08-01 00:00,5.2,96.0,E,7.0,0,0\n")
    assert w.wspd.tolist() == [5.2] and w.wdir.tolist() == [96.0]
    t = mp.parse_coops("Date Time, Water Temperature, X, N, R \n2026-08-01 00:00,6.3,0,0,0\n")
    assert t.wtmp.tolist() == [6.3] and str(t.t.iloc[0]) == "2026-08-01 00:00:00"
    empty = mp.parse_coops("Date Time, Water Temperature, X, N, R \nError: No data was found. This product may not be"
                           " offered at this station at the requested time.\n")
    assert empty.empty


def test_parse_ndbc_missing_codes_and_gzip():
    d = mp.parse_ndbc(gzip.compress(NDBC_TEXT.encode()))
    assert len(d) == 3 and d.wtmp.iloc[0] == 18.5 and np.isnan(d.wtmp.iloc[1])
    assert np.isnan(d.wspd.iloc[1]) and np.isnan(d.wdir.iloc[1]) and d.wdir.iloc[0] == 250.0


def test_load_station_truncates_at_end_utc(tmp_path):
    (tmp_path / "raw" / "ndbc" / "46026").mkdir(parents=True)
    (tmp_path / "raw" / "ndbc" / "46026" / "Sep_46026.txt").write_text(NDBC_TEXT, encoding="ascii")
    d = mp.load_station([tmp_path / "raw"], "ndbc", "46026")
    assert len(d) == 2 and d.t.max() < pd.Timestamp("2026-09-30")
    assert mp.load_station([tmp_path / "raw"], "coops", "0000000").empty


def test_onshore_sector_inclusive_wrap_and_missing():
    v = mp.onshore([5.0, 5.0, 5.0, np.nan, 5.0], [220.0, 320.0, 100.0, 250.0, np.nan], (220.0, 320.0))
    assert v[:3].tolist() == [5.0, 5.0, 0.0] and np.isnan(v[3]) and np.isnan(v[4])
    assert mp.onshore([3.0, 3.0], [350.0, 180.0], (300.0, 30.0)).tolist() == [3.0, 0.0]


def test_asof_lag_and_staleness():
    t = np.array(["2026-08-01T00:00", "2026-08-01T01:00", "2026-08-01T02:00"], "datetime64[ns]")
    v = np.array([1.0, np.nan, 3.0])
    cap = np.array(["2026-08-01T03:29", "2026-08-01T03:30", "2026-08-01T09:00", "2026-08-01T00:30"],
                   "datetime64[ns]")
    val, obs = mp.asof(cap, t, v, 90)
    assert val[0] == 1.0 and val[1] == 3.0  # 02:00 + 90 min = 03:30 qualifies, the NaN row is skipped
    assert np.isnan(val[2]) and np.isnat(obs[2])  # older than 6 h
    assert np.isnan(val[3])  # nothing old enough
    val180, _ = mp.asof(cap[:2], t, v, 180)
    assert val180.tolist() == [1.0, 1.0]
    none, _ = mp.asof(cap, t[:0], v[:0], 90)
    assert np.isnan(none).all()


def test_marine_values_priority_and_population():
    snaps = pd.DataFrame({"captured_at_utc": ["2026-08-01T12:00:00Z"] * 4})
    hours = np.array([8, 8, 6, 8])
    markets = np.array(["nyc", "nyc", "nyc", "atlanta"])
    t = np.array(["2026-08-01T09:00"], "datetime64[ns]")
    series = {(mk, v): [] for mk in mp.MARKETS for v in ("sst", "onshore")}
    series[("nyc", "sst")] = [("coops:8518750", t[:0], np.array([])), ("ndbc:44065", t, np.array([21.0]))]
    series[("nyc", "onshore")] = [("ndbc:44065", t, np.array([4.0]))]
    out = mp.marine_values(snaps, hours, markets, series, 90)
    val, src, _ = out["sst"]
    assert val[0] == 21.0 and src[0] == "ndbc:44065"  # falls back past the empty primary
    assert np.isnan(val[2]) and np.isnan(val[3])  # hour 06 and a non-coastal market are outside the population
    assert out["onshore"][0][1] == 4.0


def test_registry_pin_and_constants():
    mp._check_registry()
    assert mp.RULE_SHA256.startswith("a374f771") and mp.LEDGER_ROW == 87 and mp.LAGS == (90, 180)
    assert [c[2] for c in mp.CANDIDATES] == [1, -1] and len(mp.CANDIDATES) == 2
    assert mp.STATIONS["seattle"]["sst"][-1] == ("ndbc", "46088")


def test_verify_raw_refuses_a_changed_file(tmp_path):
    root = tmp_path / "raw"
    (root / "a").mkdir(parents=True)
    (root / "a" / "f.txt").write_bytes(b"abc")
    rec = {"path": "a/f.txt", "status": 200, "bytes": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}
    (tmp_path / "raw_manifest.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert str(root) in mp.verify_raw([root])
    (root / "a" / "f.txt").write_bytes(b"abd")
    with pytest.raises(mp.MarineError, match="manifest"):
        mp.verify_raw([root])


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


def _frame(seed=9, n_dates=40):
    rng = np.random.default_rng(seed)
    rows = []
    for day in (str(x.date()) for x in pd.date_range("2026-08-01", periods=n_dates)):
        for market in mp.MARKETS:
            for hour in range(5, 14):
                pm = rng.dirichlet(np.ones(5) * 2)
                q = rng.dirichlet(pm * 4 + 1e-3)
                winner = int(rng.choice(5, p=q / q.sum()))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm,
                             "winner": winner, "x_info": Z[winner] + rng.normal(0, 1.5),
                             "x_null": 62 + rng.normal(0, 3)})
    return pd.DataFrame(rows)


def test_run_end_to_end_on_a_synthetic_table(tmp_path, monkeypatch):
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    lay = type("Lay", (), {"manifest_sha256": "f" * 64})()
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(mp.ls, "code_state", lambda *a: clean)
    monkeypatch.setattr(mp, "verify_raw", lambda roots: {"r": "a" * 64})
    monkeypatch.setattr(mp.mg, "build_tables", lambda layout: (lay, [], dates[:7], dates[7:], fit_t, score_t))
    monkeypatch.setattr(mp.mg, "market_controls", lambda f, s: {"served": {"verdict": "PASS"}})
    monkeypatch.setattr(mp, "station_series", lambda roots, mk, v: [])
    monkeypatch.setattr(mp.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    pop = (fit_t.local_hour >= 7) & (fit_t.local_hour <= 12)

    def fake_values(snaps, hours, markets, series, lag):
        src = np.where(pop, "ndbc:x", "").astype(object)
        obs = np.full(len(snaps), np.datetime64("NaT", "ns"))
        null = fit_t.x_null if lag == 90 else fit_t.x_info  # ONSHORE survives only at L = 180 -> KILL overall
        return {"sst": (np.where(pop, fit_t.x_info, np.nan), src, obs), "onshore": (np.where(pop, -null, np.nan), src, obs)}

    monkeypatch.setattr(mp, "marine_values", fake_values)
    rec = mp.run(layout=tmp_path / "lay", raw_roots=[tmp_path / "raw"], out_dir=tmp_path / "out")
    assert rec["final"]["MAR-SST"]["verdict"] == "SURVIVE" and "w_gate" in rec["final"]["MAR-SST"]
    assert rec["final"]["MAR-ONSHORE"]["by_lag"]["90"] == "KILL"
    assert rec["final"]["MAR-ONSHORE"]["verdict"] == "KILL"
    assert rec["lines"][0].startswith("SURVIVE: MAR-SST; L90 SURVIVE delta +")
    rows = [json.loads(x) for x in (tmp_path / "out" / "marine_p0_rows.jsonl").read_text(encoding="utf-8").splitlines()]
    pooled = [r for r in rows if "market" not in r]
    assert len(pooled) == 2 * 2 * len(dates[7:]) and {r["lag_minutes"] for r in pooled} == {90, 180}
    assert {r["market"] for r in rows if "market" in r} == set(mp.MARKETS)
    feats = pd.read_parquet(tmp_path / "out" / "features.parquet")
    assert set(feats.local_hour) == set(range(7, 13)) and set(feats.lag_minutes) == {90, 180}
    with pytest.raises(mp.MarineError, match="overwrite"):
        mp.run(layout=tmp_path / "lay", raw_roots=[tmp_path / "raw"], out_dir=tmp_path / "out")
