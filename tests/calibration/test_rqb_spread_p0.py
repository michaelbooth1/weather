"""R-Q B captured GEFS spread market-residual P0 (lane L3, 2026-10-30; rule 844c2eb5, dev-window ledger row 88).

Guards: the record reader (a non-``ok`` source gives no value); capture-time coverage (a receipt after capture,
a missing receipt, hours outside 00..06); the replay scan (only the layout's snapshots, a truncated line skipped);
the 00-06 w block; the constants; and the whole run on a synthetic table (a planted type S signal survives and
reaches the w gate, a null one is a KILL, per-market rows, no overwrite).
"""
import importlib
import json

import numpy as np
import pandas as pd
import pytest

try:
    rq = importlib.import_module("weather.calibration.rqb_spread_p0")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

MARKETS = ("atlanta", "nyc", "miami", "houston", "seattle")
KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]


def _rec(sid, spread=6.5, fetched="2026-08-20T00:00:33-04:00", ok=True):
    return {"snapshot_id": sid, "captured_at_utc": "2026-08-20T05:00:00Z",
            "sources": {"global_ensemble": {"ok": ok, "fetched_at": fetched,
                                            "data": {"day_member_high_spread_80": spread,
                                                     "day_mean_member_spread": 99.0}}}}


def test_record_spread_reads_the_pinned_field_only():
    assert rq.record_spread(_rec("a")) == (6.5, "2026-08-20T00:00:33-04:00")
    v, rc = rq.record_spread(_rec("a", ok=False))
    assert np.isnan(v) and rc is None
    assert np.isnan(rq.record_spread({"sources": {}})[0])


def test_spread_values_coverage_rules():
    snaps = pd.DataFrame({"row_key": ["m|a", "m|b", "m|c", "m|d", "m|e"],
                          "captured_at_utc": ["2026-08-20T05:00:00Z"] * 5})
    feats = pd.DataFrame({"row_key": ["m|a", "m|b", "m|c", "m|d"], "spread80": [6.5, 6.5, 6.5, np.nan],
                          "rc_ge": ["2026-08-20T00:00:33-04:00", "2026-08-20T02:00:00-04:00", None,
                                    "2026-08-20T00:00:33-04:00"]})
    v = rq.spread_values(snaps, np.array([3, 3, 3, 3, 3]), feats)
    assert v[0] == 6.5 and np.isnan(v[1]) and np.isnan(v[2]) and np.isnan(v[3]) and np.isnan(v[4])
    assert np.isnan(rq.spread_values(snaps, np.array([7] * 5), feats)[0])  # 07 is outside 00..06


def test_extract_spread_reads_only_layout_snapshots(tmp_path):
    d = tmp_path / "snapshots" / "highest-temperature-in-nyc-on-august-20-2026"
    d.mkdir(parents=True)
    lines = [json.dumps(_rec("s1", 5.0)), json.dumps(_rec("s2", 7.0)), '{"snapshot_id": "s1", "trunc',
             json.dumps(_rec("s1", 6.0))]
    (d / "replay_inputs.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    frame, seen, malformed = rq.extract_spread(tmp_path, {"nyc|s1"})
    assert frame.spread80.tolist() == [6.0] and seen == 2 and len(malformed) == 1
    with pytest.raises(rq.RqbError, match="no replay record"):
        rq.extract_spread(tmp_path, {"miami|s1"})


def test_constants_and_block():
    assert rq.RULE_SHA256.startswith("844c2eb5") and rq.LEDGER_ROW == 88
    assert rq.CANDIDATE == ("GEFS-SPREAD80", "S", 1)
    assert rq.FIELD == "day_member_high_spread_80" and rq.mg.BLOCKS["00-06"] == (0, 6) == rq.HOURS


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


def _frame(seed=11, n_dates=40):
    """Calibrated-looking markets whose winner is far from the centre when x_info is high (a spread signal)."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in (str(x.date()) for x in pd.date_range("2026-08-01", periods=n_dates)):
        for market in MARKETS:
            for hour in range(0, 10):
                pm = np.array([0.1, 0.2, 0.4, 0.2, 0.1]) * rng.uniform(0.9, 1.1, 5)
                pm /= pm.sum()
                wide = rng.random() < 0.5
                q = np.array([0.3, 0.1, 0.2, 0.1, 0.3]) if wide else np.array([0.02, 0.18, 0.6, 0.18, 0.02])
                winner = int(rng.choice(5, p=q))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm,
                             "winner": winner, "x_info": (8.0 if wide else 3.0) + rng.normal(0, 1.0)})
    return pd.DataFrame(rows)


def _run(tmp_path, monkeypatch, column, out):
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])
    lay = type("Lay", (), {"manifest_sha256": "f" * 64})()
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(rq.ls, "code_state", lambda *a: clean)
    monkeypatch.setattr(rq.mg, "build_tables", lambda layout: (lay, [], dates[:7], dates[7:], fit_t, score_t))
    monkeypatch.setattr(rq.mg, "market_controls", lambda f, s: {"served": {"verdict": "PASS"}})
    vals = column(fit_t)
    feats = pd.DataFrame({"row_key": fit_t.snaps.row_key.to_numpy(), "spread80": vals,
                          "rc_ge": fit_t.snaps.captured_at_utc.to_numpy()})
    monkeypatch.setattr(rq, "extract_spread", lambda root, keys: (feats, len(feats), []))
    monkeypatch.setattr(rq.sw, "boot_counts", lambda n: np.random.default_rng(2).multinomial(
        n, np.ones(n) / n, size=500))
    (tmp_path / "replay").mkdir(exist_ok=True)
    (tmp_path / "replay" / "SHA256SUMS").write_text("x", encoding="utf-8")
    return rq.run(layout=tmp_path / "lay", out_dir=tmp_path / out, replay_root=tmp_path / "replay"), fit_t


def test_run_planted_spread_survives_and_null_is_killed(tmp_path, monkeypatch):
    rec, fit_t = _run(tmp_path, monkeypatch, lambda t: t.x_info, "out")
    r = rec["result"]
    assert r["verdict"] == "SURVIVE" and "w_gate" in r
    assert rec["controls"]["w0_identity_GEFS-SPREAD80"]["verdict"] == "PASS"
    assert r["coverage"]["fit_covered_snapshots"] == int(((fit_t.local_hour <= 6)).sum())
    text = (tmp_path / "out" / "rqb_spread_p0_rows.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(x) for x in text.splitlines()]
    assert {r_["market"] for r_ in rows if "market" in r_} == set(MARKETS)
    assert rec["line"].startswith("SURVIVE: GEFS-SPREAD80 delta +")
    with pytest.raises(rq.RqbError, match="overwrite"):
        rq.run(layout=tmp_path / "lay", out_dir=tmp_path / "out", replay_root=tmp_path / "replay")
    null, _ = _run(tmp_path, monkeypatch, lambda t: np.random.default_rng(5).normal(5, 2, len(t.snaps)), "out2")
    assert null["result"]["verdict"] == "KILL" and "w_gate" not in null["result"]
