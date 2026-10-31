"""Pooled sub-bar P0-only read (lane L17, 2026-10-31; dev-window ledger row 94, rule A3).

Synthetic frames only, no real rows.
Guards: rule_pooled_subbar_wgate A3 - the equal-weight log pool (renormalisation to the market's mass, impossible
bands at 0, the intersection rule, the market elsewhere); the C3 w = 0 identity on a pool; the C5 planted
Gaussian SYN+ / SYN- signs on a toy market (and a null planted control FAILS); the A3 labels ("KILL at edge
size" iff the wider 95% upper bound < rho 0.2236, else "P0 survivor; w untested (underpowered)"); refusal of an
unpinned / non-capture-time / sha-mismatched member and of any date after 2026-09-29; the write-once out dir;
the rule pin refusing before any layout is read; and the B-bound pin check.
"""
import importlib
import types

import numpy as np
import pandas as pd
import pytest

try:
    ps = importlib.import_module("weather.calibration.pooled_subbar_wgate")
    sw = importlib.import_module("weather.calibration.mr_sweep")
    mb = importlib.import_module("weather.calibration.market_blend")
    sc = importlib.import_module("weather.reporting.scorecards.dev_scorecard")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

KINDS, LOWS, HIGHS = ["lte", "eq", "eq", "eq", "gte"], [59, 60, 62, 64, 66], [59, 61, 63, 65, 66]


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
        self.keys = sorted(set(zip(f.date, f.market)))
        pos = {k: i for i, k in enumerate(self.keys)}
        self.cell = np.array([pos[k] for k in zip(f.date, f.market)], int)


def _frame(seed=11, n_dates=34, n_markets=10, hours=range(17)):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(1, n_dates + 1):
        day = f"2026-08-{d:02d}"
        for i in range(n_markets):
            market = f"m{i:02d}"
            for hour in hours:
                pm = rng.dirichlet(np.ones(5) * 2)
                # concentration 2: the toy market is a weak forecast, so the rule-fixed C5 plant (0.5 of the gap)
                # clears edge rho 0.2236 in every block; at 4 two blocks sit just below it (disclosed in the report)
                q = rng.dirichlet(pm * 2 + 1e-3)
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
    counts = sw.boot_counts(len(score_dates), draws=1000)
    bcounts = ps.block_counts(len(score_dates), draws=1000)
    donors = {seed: sw.donor_positions(fit_t, seed) for seed in sw.PLACEBO_SEEDS}
    return fit_t, score_t, geo, score_dates, counts, bcounts, donors


# ----------------------------------------------------------------------------- the log pool

def _mass(t, v):
    return np.bincount(t.band_snap, weights=v, minlength=len(t.snaps))


def test_log_pool_geometric_mean_renormalised_and_intersection(toy):
    t = toy[0]
    rng = np.random.default_rng(5)
    a = np.concatenate([rng.dirichlet(np.ones(5)) for _ in range(len(t.snaps))])
    b = np.concatenate([rng.dirichlet(np.ones(5)) for _ in range(len(t.snaps))])
    ca = rng.random(len(t.snaps)) < 0.7
    cb = rng.random(len(t.snaps)) < 0.7
    c, cov = ps.log_pool(t, [a, b], [ca, cb])
    np.testing.assert_array_equal(cov, ca & cb)
    np.testing.assert_allclose(_mass(t, c), _mass(t, t.p_market))
    on = np.repeat(cov, t.n)
    np.testing.assert_array_equal(c[~on], t.p_market[~on])  # the market off the intersection
    g = np.sqrt(np.clip(a, ps.EPS, 1) * np.clip(b, ps.EPS, 1))
    i = int(np.flatnonzero(cov)[0])
    sl = slice(t.offsets[i], t.offsets[i] + 5)
    np.testing.assert_allclose(c[sl], g[sl] * t.p_market[sl].sum() / g[sl].sum())


def test_log_pool_zeroes_impossible_bands_and_identical_members_are_one_member(toy):
    t = toy[0]
    v = np.concatenate([np.full(5, 0.2)] * len(t.snaps))
    cov = np.ones(len(t.snaps), bool)
    one, _ = ps.log_pool(t, [v], [cov])
    three, _ = ps.log_pool(t, [v, v, v], [cov, cov, cov])
    np.testing.assert_allclose(one, three)
    imp = t.impossible.copy()
    t.impossible = np.zeros_like(imp)
    t.impossible[0] = True
    try:
        c, _ = ps.log_pool(t, [v], [cov])
        assert c[0] == 0.0
        np.testing.assert_allclose(c[1:5].sum(), t.p_market[:5].sum())
    finally:
        t.impossible = imp
    with pytest.raises(ps.PoolError):
        ps.log_pool(t, [], [])


def test_c3_w0_identity_on_a_pool(toy):
    fit_t, score_t = toy[0], toy[1]
    v = np.concatenate([np.full(5, 0.2)] * len(fit_t.snaps))
    c, _ = ps.log_pool(fit_t, [v], [np.ones(len(fit_t.snaps), bool)])
    rec = mb.w0_identity(score_t, mb.restrict(fit_t, score_t, c))
    assert rec["verdict"] == "PASS"


# ----------------------------------------------------------------------------- C5 planted control and labels

def test_planted_control_signs(toy):
    fit_t, score_t, geo, score_dates, counts, bcounts, donors = toy
    out = ps.synthetic_controls(fit_t, score_t, geo, counts, bcounts, score_dates, donors,
                                {"POOL-0712": 5, "F2-1316": 1, "POOL-0006": 2})
    assert set(out) == set(ps.BLOCKS)
    for block, rec in out.items():
        assert rec["label"] == "CONTROL" and rec["SYN+"]["label"] == "CONTROL" and rec["SYN-"]["label"] == "CONTROL"
        assert rec["SYN+"]["testable"] and rec["SYN-"]["testable"], block
        assert rec["SYN+"]["delta"] > 0 and rec["SYN+"]["ci95"][0] > 0, block
        assert max(rec["SYN+"]["ci95"][1], rec["SYN+"]["ci95_block3"][1]) >= ps.EDGE_RHO, block
        assert rec["SYN-"]["delta"] < 0, block
        assert rec["verdict"] == "PASS", block


def test_planted_control_fails_on_a_null_signal(toy, monkeypatch):
    fit_t, score_t, geo, score_dates, counts, bcounts, donors = toy
    rng = np.random.default_rng(3)

    def null(table, geo_, mask, sign, seed=ps.SYN_SEED):
        v = np.concatenate([rng.dirichlet(np.ones(5)) for _ in range(len(table.snaps))])
        return v, np.asarray(mask, bool)

    monkeypatch.setattr(ps, "planted", null)
    out = ps.synthetic_controls(fit_t, score_t, geo, counts, bcounts, score_dates, donors,
                                {"POOL-0712": 5, "F2-1316": 1, "POOL-0006": 2})
    assert all(rec["verdict"] == "FAIL" for rec in out.values())


def test_decide_labels():
    def res(lo, up, up3, p=0.01, testable=True):
        return {"testable": testable, "p0": {"p_one_sided": p, "ci95": [lo, up]}, "p0_block3": {"ci95": [lo, up3]}}

    r = ps.decide({"POOL-0712": res(-0.01, 0.10, 0.12), "F2-1316": res(0.01, 0.20, 0.25),
                   "POOL-0006": res(None, None, None, 1.0, False)})
    assert r["POOL-0712"]["verdict"] == ps.VERDICT_KILL == "KILL at edge size"
    assert r["F2-1316"]["verdict"] == ps.VERDICT_SURVIVOR == "P0 survivor; w untested (underpowered)"
    assert r["F2-1316"]["wider_upper_95"] == 0.25  # the wider of date and block-3
    assert r["POOL-0006"]["verdict"] == "UNTESTABLE"
    assert all("bh_q_context" in v for v in r.values())


def test_block_counts_sum_to_n():
    c = ps.block_counts(43, draws=50)
    assert c.shape == (50, 43) and (c.sum(axis=1) == 43).all()


# ----------------------------------------------------------------------------- refusals

def test_member_pins(tmp_path):
    assert ps.member_status(("X", "POOL-0712", None, None, False)) == (False, "no A3-pinned dev band emit")
    f = tmp_path / "e.jsonl"
    f.write_text("{}\n", encoding="utf-8")
    ok, why = ps.member_status(("X", "POOL-0712", str(f), "0" * 64, False))
    assert not ok and "capture-time" in why
    with pytest.raises(ps.PoolError, match="A3 pin"):
        ps.member_status(("X", "POOL-0712", str(f), "0" * 64, True))
    assert ps.member_status(("X", "POOL-0712", str(f), ps._sha(f), True)) == (True, "pinned")
    assert ps.member_status(("X", "POOL-0712", str(tmp_path / "gone"), "0" * 64, True))[0] is False
    assert {m[0] for m in ps.MEMBERS} == {"R-Q A", "R-I", "X17", "A2", "ASOS", "F2", "R-PD", "R-N"}
    assert {m[1] for m in ps.MEMBERS} == set(ps.BLOCKS) and ps.K == len(ps.BLOCKS) == 3


def test_dates_after_cutoff_refuse():
    ps.check_dates(["2026-09-29", "2026-08-15"])
    with pytest.raises(ps.PoolError, match="after 2026-09-29"):
        ps.check_dates(["2026-09-30"])


def test_out_dir_guard(tmp_path):
    with pytest.raises(ps.PoolError, match="outside"):
        ps.check_out_dir(tmp_path / "x", root=tmp_path / "root")
    (tmp_path / "root" / "taken").mkdir(parents=True)
    with pytest.raises(ps.PoolError, match="overwrite"):
        ps.check_out_dir(tmp_path / "root" / "taken", root=tmp_path / "root")
    assert ps.check_out_dir(tmp_path / "root" / "new", root=tmp_path / "root").name == "new"


def test_run_refuses_wrong_rule_before_layout(tmp_path):
    rule = tmp_path / ps.RULE_PATH
    rule.parent.mkdir(parents=True)
    rule.write_text("not the rule\n", encoding="utf-8")
    with pytest.raises(ps.PoolError, match="pinned A3 rule"):
        ps.run(layout=tmp_path / "no-layout", out_dir=tmp_path / "x", allow_dirty=True, repo_root=tmp_path)


def test_bbound_check(tmp_path):
    f = tmp_path / "src" / "dev_scorecard.py"
    f.parent.mkdir(parents=True)
    f.write_text("x = 1\n", encoding="utf-8")
    mods = {"m": types.SimpleNamespace(__file__=str(f)), "other": types.SimpleNamespace(__file__=None)}
    with pytest.raises(ps.PoolError, match="without an A3 pin"):
        ps.bbound_check(tmp_path, pins={}, modules=mods)
    with pytest.raises(ps.PoolError, match="differ"):
        ps.bbound_check(tmp_path, pins={"src/dev_scorecard.py": "0" * 64}, modules=mods)
    assert ps.bbound_check(tmp_path, pins={"src/dev_scorecard.py": ps._sha(f)}, modules=mods) == {
        "src/dev_scorecard.py": ps._sha(f)}
    with pytest.raises(ps.PoolError, match="outside the run tree"):
        ps.bbound_check(tmp_path / "src" / "nested", pins={}, modules=mods)


def test_bbound_pins_match_this_tree():
    from pathlib import Path

    root = Path(ps.__file__).resolve().parents[3]
    assert ps.bbound_check(root) == {k: v for k, v in ps.BBOUND_PINS.items() if k in ps.bbound_check(root)}
    for rel, sha in ps.BBOUND_PINS.items():
        assert ps._sha(root / rel) == sha, rel
