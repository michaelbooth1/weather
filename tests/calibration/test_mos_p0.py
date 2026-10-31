"""MOS against the market P0 (lane L3, 2026-10-30; rule 952cfc52 + amendment 1 eafbfca4, ledger row 89).

Guards: the archive filter (runtime >= 2026-09-30 dropped, out-of-range and unavailable rows dropped); the
selection (the latest run available by capture for ftime (D + 1) 00Z at the market's station, the +1 h lag, hours
outside 07..12); the archive and station pins; the constants and the 07-12 block; and the whole run on a synthetic
table (a planted type C signal survives both arms and reaches the w gate, a null is a KILL, a sensitivity flip is
flagged, not a KILL (amendment 1), a main-arm KILL stays a KILL, per-market rows, no overwrite).
"""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    mp = importlib.import_module("weather.calibration.mos_p0")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

MARKETS = ("atlanta", "nyc", "miami", "houston", "seattle")
KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])


def _mos(rows):
    return pd.DataFrame(rows, columns=["station", "runtime", "ftime", "n_x", "available_utc"])


def test_load_mos_filters(tmp_path):
    g = _mos([["KLGA", "2026-08-20T00:00Z", "2026-08-21T00:00Z", 80, "2026-08-20T04:30Z"],
              ["KLGA", "2026-09-30T00:00Z", "2026-10-01T00:00Z", 70, "2026-09-30T04:30Z"],  # after the window
              ["KLGA", "2026-08-20T06:00Z", "2026-08-21T00:00Z", 150, "2026-08-20T10:30Z"],  # out of range
              ["KLGA", "2026-08-20T12:00Z", "2026-08-21T00:00Z", 81, None],                  # no availability
              ["KLGA", "2026-08-20T18:00Z", "2026-08-21T00:00Z", None, "2026-08-20T22:30Z"]])  # no value
    g.to_parquet(tmp_path / "mos_GFS.parquet", index=False)
    out = mp.load_mos(tmp_path, "GFS")
    assert out.value.tolist() == [80.0] and str(out.runtime.dtype) == mp.NS_UTC


def test_select_values_latest_available_and_lag():
    g = _mos([["KLGA", "2026-08-20T00:00Z", "2026-08-21T00:00Z", 80, "2026-08-20T04:30Z"],
              ["KLGA", "2026-08-20T06:00Z", "2026-08-21T00:00Z", 82, "2026-08-20T10:30Z"],
              ["KLGA", "2026-08-20T12:00Z", "2026-08-21T00:00Z", 84, "2026-08-20T16:30Z"],
              ["KLGA", "2026-08-19T06:00Z", "2026-08-20T00:00Z", 70, "2026-08-19T10:30Z"]])  # another target day
    for c in ("runtime", "ftime", "available_utc"):
        g[c] = pd.to_datetime(g[c], utc=True).astype(mp.NS_UTC)
    g["value"] = g.n_x.astype(float)
    snaps = pd.DataFrame({"market": ["nyc", "nyc", "nyc", "nyc", "toronto"],
                          "date": ["2026-08-20"] * 5,
                          "captured_at_utc": ["2026-08-20T11:00:00Z", "2026-08-20T10:00:00Z",
                                              "2026-08-20T03:00:00Z", "2026-08-20T11:00:00Z",
                                              "2026-08-20T11:00:00Z"]})
    hours = np.array([7, 7, 7, 13, 7])
    v, rt, av = mp.select_values(snaps, hours, g)
    assert v[0] == 82 and v[1] == 80 and np.isnan(v[2]) and np.isnan(v[3]) and np.isnan(v[4])
    assert str(rt.iloc[0]) == "2026-08-20 06:00:00+00:00" and av.iloc[0] <= pd.Timestamp("2026-08-20T11:00Z")
    v1, _, _ = mp.select_values(snaps, hours, g, lag=mp.SENS_LAG)
    assert v1[0] == 80 and v1[1] == 80  # 10:30 + 1 h is after an 11:00 capture


def test_archive_and_station_pins(tmp_path):
    with pytest.raises(mp.MosError, match="missing"):
        mp.verify_mos(tmp_path)
    (tmp_path / "MANIFEST.json").write_text("{}", encoding="utf-8")
    with pytest.raises(mp.MosError, match="pinned"):
        mp.verify_mos(tmp_path, {"MANIFEST.json": "0" * 64})
    lay = tmp_path / "lay"
    lay.mkdir()
    pd.DataFrame({"market": ["nyc", "nyc", "toronto"], "station": ["KLGA", "KJFK", "CYYZ"]}).to_parquet(
        lay / "inputs_snapshots.parquet", index=False)
    with pytest.raises(mp.MosError, match="stations differ"):
        mp.check_stations(lay)
    pd.DataFrame({"market": ["nyc", "toronto"], "station": ["KLGA", "CYYZ"]}).to_parquet(
        lay / "inputs_snapshots.parquet", index=False)
    assert mp.check_stations(lay) == {"nyc": "KLGA"}


def test_constants_and_block():
    assert mp.RULE_SHA256.startswith("952cfc52") and mp.LEDGER_ROW == 89
    assert [c[0] for c in mp.CANDIDATES] == ["MOS-GFS", "MOS-NAM"] and {c[1] for c in mp.CANDIDATES} == {"C"}
    assert mp.mg.BLOCKS["07-12"] == (7, 12) == mp.HOURS and mp.SENS_LAG == pd.Timedelta(hours=1)
    assert mp.RUNTIME_END == pd.Timestamp("2026-09-30T00:00Z")
    assert mp.AMENDMENT_1_SHA256.startswith("eafbfca4") and mp.RECORDER_COMMIT.startswith("841fb604")


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
            for hour in range(5, 15):
                pm = np.array([0.1, 0.2, 0.4, 0.2, 0.1]) * rng.uniform(0.9, 1.1, 5)
                pm /= pm.sum()
                winner = int(rng.choice(5, p=[0.1, 0.2, 0.4, 0.2, 0.1]))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm,
                             "winner": winner, "x_info": Z[winner] + rng.normal(0, 0.7)})
    return pd.DataFrame(rows)


def _run(tmp_path, monkeypatch, main, sens, out):
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    lay = type("Lay", (), {"manifest_sha256": "f" * 64})()
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(mp.ls, "code_state", lambda *a: clean)
    monkeypatch.setattr(mp.mg, "build_tables", lambda layout: (lay, [], dates[:7], dates[7:], fit_t, score_t))
    monkeypatch.setattr(mp.mg, "market_controls", lambda f, s: {"served": {"verdict": "PASS"}})
    monkeypatch.setattr(mp, "verify_mos", lambda root: {"MANIFEST.json": "x"})
    monkeypatch.setattr(mp, "check_stations", lambda layout: {m: mp.STATIONS[m] for m in MARKETS})
    monkeypatch.setattr(mp, "load_mos", lambda root, model: model)
    hours = (fit_t.local_hour >= 7) & (fit_t.local_hour <= 12)

    def fake_select(snaps, local_hour, mos, lag=pd.Timedelta(0)):
        v = (sens if lag > pd.Timedelta(0) else main)(fit_t, mos)
        v = np.where(hours, v, np.nan)
        t = pd.Series(pd.to_datetime(snaps.captured_at_utc.to_numpy(), utc=True))
        return v, t, t

    monkeypatch.setattr(mp, "select_values", fake_select)
    monkeypatch.setattr(mp.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    return mp.run(layout=tmp_path / "lay", out_dir=tmp_path / out, mos_root=tmp_path / "mos"), fit_t


def _null(t, model):
    return np.random.default_rng(5 if model == "GFS" else 6).normal(62.5, 2.5, len(t.snaps))


def _planted_gfs(t, model):
    return t.x_info if model == "GFS" else _null(t, model)


def test_run_planted_survives_null_killed_and_flip_flagged(tmp_path, monkeypatch):
    rec, fit_t = _run(tmp_path, monkeypatch, _planted_gfs, _planted_gfs, "out")
    g, n = rec["results"]["MOS-GFS"], rec["results"]["MOS-NAM"]
    assert g["verdict"] == "SURVIVE" and "w_gate" in g and n["verdict"] == "KILL" and "w_gate" not in n
    assert g["sensitivity_lag_plus_1h"]["flips_verdict"] is False
    assert rec["controls"]["w0_identity_MOS-GFS"]["verdict"] == "PASS"
    in_block = int(((fit_t.local_hour >= 7) & (fit_t.local_hour <= 12)).sum())
    assert g["coverage"]["fit_covered_snapshots"] == in_block
    rows = [json.loads(x) for x in (tmp_path / "out" / "mos_p0_rows.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {r["market"] for r in rows if r.get("candidate") == "MOS-GFS" and "market" in r} == set(MARKETS)
    assert rec["lines"][0].startswith("SURVIVE: MOS-GFS delta +")
    feats = pd.read_parquet(tmp_path / "out" / "features.parquet")
    assert {"GFS_value", "GFS_value_lag1h", "NAM_runtime"} <= set(feats.columns)
    with pytest.raises(mp.MosError, match="overwrite"):
        mp.run(layout=tmp_path / "lay", out_dir=tmp_path / "out", mos_root=tmp_path / "mos")
    flip, _ = _run(tmp_path, monkeypatch, _planted_gfs, _null, "out2")
    fg = flip["results"]["MOS-GFS"]  # amendment 1: report-only, the flip is flagged and the verdict stands
    assert fg["survive"] and fg["verdict"] == "SURVIVE (sensitivity flip)" and "w_gate" in fg
    assert fg["sensitivity_lag_plus_1h"]["flips_verdict"] is True and flip["lines"][0].endswith("+1 h flips")
    null, _ = _run(tmp_path, monkeypatch, _null, _planted_gfs, "out3")
    assert null["results"]["MOS-GFS"]["verdict"] == "KILL"
    assert null["results"]["MOS-GFS"]["sensitivity_lag_plus_1h"]["flips_verdict"] is False  # a main KILL stays
