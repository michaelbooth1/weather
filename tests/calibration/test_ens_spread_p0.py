"""ENS member spread P0 (lane L17, 2026-10-31; dev-window ledger row 93, rule A2).

Synthetic frames only, no real rows.
Guards: rule_ens_spread_p0 A2 sections 4, 8 and (a) - the covered-iff rule (receipt after capture, n_members != 51, a
non-finite value, the block, D vs D-1 run selection); the ICAO-to-market map (toronto uncovered, an unknown
market refuses); the points pin (a wrong sha refuses, rows after 2026-09-29 never reach the reader); the
write-once out dir below C:/t/l17/ens; the rule pin refusing before any layout is read; the A2 verdict labels;
and the A4 synthetic sign control on a toy market (SYN+ survives, its negation SYN- reads Delta < 0, both
labelled CONTROL).
"""
import importlib

import numpy as np
import pandas as pd
import pytest

try:
    ens = importlib.import_module("weather.calibration.ens_spread_p0")
    sw = importlib.import_module("weather.calibration.mr_sweep")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]
Z = np.array([58.0, 60.5, 62.5, 64.5, 67.0])


# ----------------------------------------------------------------------------- covered-iff and the station map

def _points(rows):
    df = pd.DataFrame(rows, columns=["run", "station", "target_date", "ens_sd_f", "n_members", "available_utc"])
    df["available_utc"] = pd.to_datetime(df.available_utc, utc=True)
    return df


def _snaps(rows):
    return pd.DataFrame(rows, columns=["row_key", "date", "captured_at_utc", "market", "local_hour"])


def test_covered_iff_and_run_selection():
    pts = _points([
        ("2026-08-20", "KATL", "2026-08-20", 2.0, 51, "2026-08-20T09:00:00Z"),  # 0712 run of D
        ("2026-08-19", "KATL", "2026-08-20", 3.0, 51, "2026-08-19T09:00:00Z"),  # 0006 run of D-1
        ("2026-08-21", "KATL", "2026-08-21", 4.0, 50, "2026-08-21T09:00:00Z"),  # 50 members: uncovered
        ("2026-08-22", "KATL", "2026-08-22", np.nan, 51, "2026-08-22T09:00:00Z"),  # NaN: uncovered
    ])
    snaps = _snaps([
        ("atlanta|a", "2026-08-20", "2026-08-20T13:00:00Z", "atlanta", 9),   # 07-12, covered, value 2.0
        ("atlanta|b", "2026-08-20", "2026-08-20T08:30:00Z", "atlanta", 4),   # 00-06, D-1 run, value 3.0
        ("atlanta|c", "2026-08-20", "2026-08-20T08:59:00Z", "atlanta", 7),   # 07-12 but receipt after capture
        ("atlanta|d", "2026-08-20", "2026-08-20T19:00:00Z", "atlanta", 15),  # outside both blocks
        ("atlanta|e", "2026-08-21", "2026-08-21T14:00:00Z", "atlanta", 10),  # 50 members
        ("atlanta|f", "2026-08-22", "2026-08-22T14:00:00Z", "atlanta", 10),  # NaN value
        ("toronto|g", "2026-08-20", "2026-08-20T14:00:00Z", "toronto", 10),  # no ENS row
    ])
    smap = {"atlanta": "KATL", "toronto": None}
    vals, feats = ens.candidate_values(snaps, snaps.market.to_numpy(), snaps.local_hour.to_numpy(), pts, smap)
    a, b = vals["ENS-SD-0712"], vals["ENS-SD-0006"]
    assert a[0] == 2.0 and np.isnan(a[1]) and np.isnan(a[2]) and np.isnan(a[3])
    assert np.isnan(a[4]) and np.isnan(a[5]) and np.isnan(a[6])
    assert b[1] == 3.0 and np.isnan(b[0]) and np.isnan(b[3])
    assert np.isnan(np.concatenate([a, b])).sum() == 14 - 2
    f = feats.set_index(["candidate", "row_key"])
    assert f.loc[("ENS-SD-0006", "atlanta|b"), "run"] == "2026-08-19"
    assert f.loc[("ENS-SD-0712", "atlanta|a"), "run"] == "2026-08-20"
    assert not f.loc[("ENS-SD-0712", "atlanta|c"), "covered"]
    assert ("ENS-SD-0712", "toronto|g") not in f.index


def test_post_cutoff_snapshot_refuses():
    pts = _points([("2026-09-30", "KATL", "2026-09-30", 2.0, 51, "2026-09-30T09:00:00Z")])
    snaps = _snaps([("atlanta|a", "2026-09-30", "2026-09-30T13:00:00Z", "atlanta", 9)])
    with pytest.raises(ens.EnsError, match="after 2026-09-29"):
        ens.candidate_values(snaps, snaps.market.to_numpy(), snaps.local_hour.to_numpy(), pts, {"atlanta": "KATL"})


def test_station_map():
    m = ens.station_map(["atlanta", "nyc", "toronto", "los-angeles"])
    assert m == {"atlanta": "KATL", "los-angeles": "KLAX", "nyc": "KLGA", "toronto": None}
    with pytest.raises(ens.EnsError, match="no US station"):
        ens.station_map(["atlantis"])


def test_points_pin_and_cutoff_filter(tmp_path):
    pts = _points([
        ("2026-09-29", "KATL", "2026-09-29", 2.0, 51, "2026-09-29T09:00:00Z"),
        ("2026-09-29", "KATL", "2026-09-30", 2.5, 51, "2026-09-29T09:00:00Z"),
        ("2025-08-01", "KATL", "2025-08-01", 1.0, 51, "2025-08-01T09:00:00Z"),
    ])
    path = tmp_path / "points.parquet"
    pts.to_parquet(path, index=False)
    with pytest.raises(ens.EnsError, match="not the pinned"):
        ens.load_points(path)
    got, sha = ens.load_points(path, expected_sha=ens.ls.sha256_file(path))
    assert list(got.target_date) == ["2026-09-29"] and sha == ens.ls.sha256_file(path)


def test_out_dir_guard(tmp_path):
    root = tmp_path / "t" / "l17" / "ens"
    root.mkdir(parents=True)
    assert ens.check_out_dir(root / "run1", root) == (root / "run1").resolve()
    with pytest.raises(ens.EnsError, match="outside"):
        ens.check_out_dir(tmp_path / "elsewhere", root)
    with pytest.raises(ens.EnsError, match="outside"):
        ens.check_out_dir(root, root)
    (root / "run2").mkdir()
    with pytest.raises(ens.EnsError, match="overwrite"):
        ens.check_out_dir(root / "run2", root)


def test_run_refuses_wrong_rule_before_layout(tmp_path):
    rule = tmp_path / ens.RULE_PATH
    rule.parent.mkdir(parents=True)
    rule.write_text("not the rule\n", encoding="utf-8")
    with pytest.raises(ens.EnsError, match="pinned A2 rule"):
        ens.run(layout=tmp_path / "no-layout", out_dir=tmp_path / "x", allow_dirty=True, repo_root=tmp_path)


def test_decide_labels():
    def res(p, lo, testable=True):
        return {"testable": testable, "p0": {"p_one_sided": p, "ci95": [lo, 0.5]}}

    r = ens.decide({"ENS-SD-0712": res(0.001, 0.01), "ENS-SD-0006": res(0.4, -0.02)})
    assert r["ENS-SD-0712"]["verdict"] == "SCREEN"
    assert r["ENS-SD-0006"]["verdict"] == "KILL at edge size"
    r = ens.decide({"ENS-SD-0712": res(1.0, None, False), "ENS-SD-0006": res(0.001, -0.01)})
    assert r["ENS-SD-0712"]["verdict"] == "UNTESTABLE"
    assert r["ENS-SD-0006"]["verdict"] == "KILL at edge size"  # lower bound <= 0 never survives


# ----------------------------------------------------------------------------- A4 synthetic control on a toy market

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
        self.impossible = np.zeros(len(self.y), bool)
        keys = sorted(set(zip(f.date, f.market)))
        self.keys = keys


def _frame(seed=11, n_dates=34, markets=("atlanta", "nyc", "miami", "austin", "dallas", "chicago")):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(1, n_dates + 1):
        day = f"2026-08-{d:02d}"
        for market in markets:
            for hour in range(13):
                pm = rng.dirichlet(np.ones(5) * 2)
                q = rng.dirichlet(pm * 4 + 1e-3)
                winner = int(rng.choice(5, p=q / q.sum()))
                rows.append({"row_key": f"{market}|{day}T{hour:02d}", "date": day, "market": market,
                             "local_hour": hour, "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm,
                             "winner": winner})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def toy():
    frame = _frame()
    dates = sorted(frame.date.unique())
    fit_t, score_t = FakeTable(frame, dates), FakeTable(frame, dates[4:])
    geo = sw.band_geometry(fit_t)
    score_dates = np.array(sorted(set(score_t.snaps.date)))
    counts = sw.boot_counts(len(score_dates), draws=2000)
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    return fit_t, score_t, geo, score_dates, counts, donors


def test_synthetic_values_are_negations_and_block_limited(toy):
    fit_t, _, geo, *_ = toy
    mask = (fit_t.local_hour >= 7) & (fit_t.local_hour <= 12)
    plus, minus = ens.synthetic_values(fit_t, geo, mask)
    assert np.isnan(plus[~mask]).all() and np.isfinite(plus[mask]).all()
    np.testing.assert_array_equal(minus[mask], -plus[mask])
    again, _ = ens.synthetic_values(fit_t, geo, mask)
    np.testing.assert_array_equal(again[mask], plus[mask])  # seeded


def test_synthetic_control_signs(toy):
    fit_t, score_t, geo, score_dates, counts, donors = toy
    masks = {"07-12": (fit_t.local_hour >= 7) & (fit_t.local_hour <= 12),
             "00-06": fit_t.local_hour <= 6}
    out = ens.synthetic_controls(fit_t, score_t, geo, counts, score_dates, donors, masks)
    for block, rec in out.items():
        assert rec["label"] == "CONTROL" and rec["SYN+"]["label"] == "CONTROL" and rec["SYN-"]["label"] == "CONTROL"
        assert rec["SYN+"]["testable"] and rec["SYN-"]["testable"], block
        assert rec["SYN+"]["delta"] > 0 and rec["SYN+"]["ci95"][0] > 0, block
        assert rec["SYN-"]["delta"] < 0, block
        assert rec["verdict"] == "PASS", block


def test_synthetic_control_fails_on_a_null_signal(toy, monkeypatch):
    """A control that cannot see the outcome must FAIL (the control is not vacuous)."""
    fit_t, score_t, geo, score_dates, counts, donors = toy
    rng = np.random.default_rng(3)

    def null_values(table, geo_, mask, seed=ens.SYN_SEED):
        v = np.where(mask, rng.normal(size=len(table.snaps)), np.nan)
        return v, -v

    monkeypatch.setattr(ens, "synthetic_values", null_values)
    out = ens.synthetic_controls(fit_t, score_t, geo, counts, score_dates, donors,
                                 {"07-12": (fit_t.local_hour >= 7) & (fit_t.local_hour <= 12)})
    assert out["07-12"]["verdict"] == "FAIL"
