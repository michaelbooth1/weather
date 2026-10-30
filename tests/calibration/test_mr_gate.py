"""MR gate (lane L3, 2026-10-30; rule 37cb46be, dev-window ledger rows 74-76).

Guards: the market-residual P0 statistic and its date-clustered bootstrap (null covers 0, a candidate that knows
the market's error gives a lower bound above 0, the seed fixes the interval); the paired date-clustered difference;
the pre-registered PASS/KILL logic; and, end to end on a synthetic table through ``market_blend``'s unchanged
pool, an informative candidate passes while a market-copy-plus-noise candidate is killed. Candidate files are
sha-pinned and an unknown candidate or an existing receipt refuses before any layout is read.
"""
import importlib

import numpy as np
import pandas as pd
import pytest

try:
    mr = importlib.import_module("weather.calibration.mr_gate")
    mb = importlib.import_module("weather.calibration.market_blend")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise


def _entries(informative, n_dates=40, per_date=60, seed=3):
    rng = np.random.default_rng(seed)
    m = rng.uniform(0.05, 0.6, n_dates * per_date)
    y = (rng.uniform(size=m.size) < np.clip(m + rng.normal(0, 0.15, m.size), 0, 1)).astype(float)
    c = m + (0.3 * (y - m) if informative else 0.0) + rng.normal(0, 0.05, m.size)
    dates = np.repeat([f"2026-08-{d % 28 + 1:02d}#{d}" for d in range(n_dates)], per_date)
    return c, m, y, dates


def test_residual_rho_null_planted_and_seed():
    null = mr.residual_rho(*_entries(False), draws=500, seed=5)
    assert null["ci95"][0] < 0 < null["ci95"][1]
    planted = mr.residual_rho(*_entries(True), draws=500, seed=5)
    assert planted["ci95"][0] > 0 and planted["n_dates"] == 40
    assert mr.residual_rho(*_entries(True), draws=500, seed=5) == planted
    assert mr.residual_rho(*_entries(True), draws=500, seed=6)["ci95"] != planted["ci95"]
    with pytest.raises(mr.GateError):
        mr.residual_rho([], [], [], [])


def test_pass_logic():
    p0 = {"rho": 0.1, "ci95": [0.02, 0.2]}
    assert mr.p0_pass(p0, {"ci95": [-0.01, 0.01]})
    assert not mr.p0_pass(p0, {"ci95": [0.001, 0.02]})  # a placebo that does not cover 0 voids P0
    assert not mr.p0_pass({"rho": 0.0, "ci95": [-0.01, 0.2]}, {"ci95": [-0.01, 0.01]})
    good = mr.w_checks(0.2, {"ci95_date": [0.95, 0.99]}, {"ci95_date": [-0.003, -0.001]},
                       {"ci95_date": [-0.002, -0.0001]})
    assert all(good.values())
    assert not mr.w_checks(0.04, {"ci95_date": [0.95, 0.99]}, {"ci95_date": [-0.003, -0.001]},
                           {"ci95_date": [-0.002, -0.0001]})["mean_w_at_least_0.05"]
    assert not mr.w_checks(0.2, {"ci95_date": [0.95, 0.99]}, {"ci95_date": [-0.003, -0.001]},
                           {"ci95_date": [-0.002, 0.0001]})["blend_minus_floor_only_date_upper_below_0"]


# ----------------------------------------------------------------------------- a synthetic scorecard table

class FakeTable:
    brier = sc.Table.brier
    log_score = sc.Table.log_score
    cells = sc.Table.cells

    def __init__(self, frame, dates):
        f = frame[frame.date.isin(dates)].reset_index(drop=True)
        self.snaps = f[["row_key", "date", "captured_at_utc", "market", "local_hour"]].copy()
        self.n = np.full(len(f), 5)
        self.offsets = np.arange(len(f)) * 5
        self.band_snap = np.repeat(np.arange(len(f)), 5)
        self.snap_pos = pd.Series(np.arange(len(f)), index=f.row_key.to_numpy())
        self.bands = pd.DataFrame({"band_index": np.tile(np.arange(5), len(f))})
        self.p_market = np.concatenate(f.pm.to_list())
        self.p_cand = {k: np.concatenate(f[k].to_list()) for k in ("pc_info", "pc_noise")}
        self.y = np.concatenate([np.eye(5)[w] for w in f.winner])
        self.impossible = np.zeros(len(self.y), bool)
        self.local_hour = f.local_hour.to_numpy(int)
        self.markets = f.market.to_numpy()
        keys = sorted(set(zip(f.date, f.market)))
        index = {k: i for i, k in enumerate(keys)}
        self.keys = keys
        self.cell = np.array([index[k] for k in zip(f.date, f.market)], int)
        self.w = sc.crossed_weights([k[0] for k in keys], [k[1] for k in keys])
        self.w_date = sc.crossed_weights([k[0] for k in keys], ["all"] * len(keys))


def _frame(seed=11):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(1, 31):
        day = f"2026-08-{d:02d}"
        for market in ("atlanta", "nyc", "miami"):
            for hour in range(7, 13):
                # a calibrated market (E[q | pm] = pm), so a date-deranged placebo carries no residual signal
                pm = rng.dirichlet(np.ones(5) * 2)
                q = rng.dirichlet(pm * 4 + 1e-3)
                winner = int(rng.choice(5, p=q / q.sum()))
                info = 0.5 * pm + 0.5 * q
                noise = np.exp(np.log(pm) + rng.normal(0, 0.4, 5))
                rows.append({"row_key": f"{day}|{market}|{hour}", "date": day, "market": market, "local_hour": hour,
                             "captured_at_utc": f"{day}T{hour:02d}:30:00Z", "pm": pm, "winner": winner,
                             "pc_info": info, "pc_noise": noise / noise.sum()})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def tables():
    frame = _frame()
    dates = sorted(frame.date.unique())
    return FakeTable(frame, dates), FakeTable(frame, [d for d in dates if d >= "2026-08-08"])


def test_gate_candidate_passes_an_informative_candidate_and_kills_noise(tables):
    fit_t, score_t = tables
    cov = np.ones(len(fit_t.snaps), bool)
    info = mr.gate_candidate("info", "07-12", fit_t, score_t, fit_t.p_cand["pc_info"], cov)
    assert info["p0"]["pass"] and info["w"]["summary"]["mean"] >= 0.05 and info["verdict"] == "PASS"
    assert info["line"].startswith("PASS: info P0 rho +")
    assert info["coverage"]["covered_share"] == 1.0 and set(info["per_hour"]) == {f"h{h:02d}" for h in range(7, 13)}
    noise = mr.gate_candidate("noise", "07-12", fit_t, score_t, fit_t.p_cand["pc_noise"], cov)
    assert noise["verdict"] == "KILL" and not noise["p0"]["pass"]
    again = mr.gate_candidate("info", "07-12", fit_t, score_t, fit_t.p_cand["pc_info"], cov)
    assert again["line"] == info["line"] and again["w"]["w_by_date"] == info["w"]["w_by_date"]


def test_gate_candidate_scores_only_covered_snapshots(tables):
    fit_t, score_t = tables
    cov = fit_t.local_hour != 7
    res = mr.gate_candidate("info", "07-12", fit_t, score_t, fit_t.p_cand["pc_info"], cov)
    assert "h07" not in res["per_hour"] and res["coverage"]["covered_share"] == pytest.approx(5 / 6)
    with pytest.raises(mr.GateError, match="no covered snapshot"):
        mr.gate_candidate("info", "13-16", fit_t, score_t, fit_t.p_cand["pc_info"], cov)


def test_run_refuses_before_reading_the_layout(tmp_path, monkeypatch):
    clean = {"git_head": "c" * 40, "worktree": "w", "dirty": False, "dirty_paths": []}
    monkeypatch.setattr(mr.ls, "code_state", lambda *a: clean)
    with pytest.raises(mr.GateError, match="no rule row"):
        mr.run(layout=tmp_path / "absent", out_dir=tmp_path, candidates={"GEFS": "x"})
    wrong = tmp_path / "wrong.jsonl"
    wrong.write_text("{}\n", encoding="utf-8")
    with pytest.raises(mr.GateError, match="not the pinned dev emit"):
        mr.run(layout=tmp_path / "absent", out_dir=tmp_path / "o", candidates={"R-R": str(wrong)})
    (tmp_path / "o2").mkdir()
    (tmp_path / "o2" / "mr_gate.json").write_text("{}", encoding="utf-8")
    with pytest.raises(mr.GateError, match="overwrite"):
        mr.run(layout=tmp_path / "absent", out_dir=tmp_path / "o2", candidates={"R-R": str(wrong)})
    monkeypatch.setattr(mr.ls, "code_state", lambda *a: dict(clean, dirty=True, dirty_paths=["?? x"]))
    with pytest.raises(mr.ls.ScreenError, match="dirty tree"):
        mr.run(layout=tmp_path / "absent", out_dir=tmp_path / "o3")
