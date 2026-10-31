"""Pooled sub-bar P0-only read (lane L17, 2026-10-31; dev-window ledger row 94, rule A3).

Synthetic frames only, no real rows.
Guards: rule_pooled_subbar_wgate A3 - the equal-weight log pool (renormalisation to the market's mass, impossible
bands at 0, the intersection rule, the market elsewhere); the C3 w = 0 identity on a pool; the C5 planted
Gaussian SYN+ / SYN- control on the toy market at concentration 4 with the frozen plant scale 0.75 and the
Clarification 1 pass rule (SYN+ lower > 0, SYN+ wider upper >= 0.2236, SYN- upper < 0; a null planted control
FAILS); the A3 labels ("KILL at edge size" iff the wider 95% upper bound < rho 0.2236, else "P0 survivor; w
untested (underpowered)"); the C3 REV-2 circular block-3 counts (c3_kill_tier.block_counts verbatim, B 2,000,
seed 20261024); Clarification 1 C4 - a member is testable only through a passing C4 receipt of the pinned
replay harness with a matching emit sha (failures drop, forgeries refuse), and a block with fewer than 2 C4
survivors is UNTESTABLE (POOL-0712 and F2-1316 as built); refusal of any date after 2026-09-29; the write-once
out dir; the rule pin refusing before any layout is read; and the B-bound pin check.
"""
import hashlib
import importlib
import json
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
                # market concentration 4 (Clarification 1 calibration toy; the frozen plant 0.75 passes C5 here)
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
    counts = sw.boot_counts(len(score_dates), draws=1000)
    bcounts = ps.block_counts(len(score_dates))
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
        sp, sm = rec["SYN+"], rec["SYN-"]
        assert min(sp["ci95"][0], sp["ci95_block3"][0]) > 0, block
        assert max(sp["ci95"][1], sp["ci95_block3"][1]) >= ps.EDGE_RHO, block
        assert max(sm["ci95"][1], sm["ci95_block3"][1]) < 0, block
        assert all(rec["checks"].values()) and rec["verdict"] == "PASS", block


def test_c5_pass_rule_uses_the_wider_bounds():
    def r(lo, up, lo3, up3, testable=True):
        return {"testable": testable, "ci95": [lo, up], "ci95_block3": [lo3, up3]}

    good = ps.c5_checks(r(0.10, 0.30, 0.09, 0.31), r(-0.30, -0.10, -0.31, -0.09))
    assert all(good.values())
    assert not ps.c5_checks(r(0.10, 0.30, -0.01, 0.31), r(-0.3, -0.1, -0.3, -0.1))["syn_plus_lower_above_0"]
    assert ps.c5_checks(r(0.10, 0.20, 0.09, 0.2236068), r(-0.3, -0.1, -0.3, -0.1))[
        "syn_plus_wider_upper_at_least_edge"]
    assert not ps.c5_checks(r(0.10, 0.20, 0.09, 0.22), r(-0.3, -0.1, -0.3, -0.1))[
        "syn_plus_wider_upper_at_least_edge"]
    assert not ps.c5_checks(r(0.1, 0.3, 0.1, 0.3), r(-0.30, -0.10, -0.31, 0.001))["syn_minus_upper_below_0"]
    assert not any(ps.c5_checks(r(None, None, None, None, False), r(None, None, None, None, False)).values())
    assert ps.SYN_SHRINK == 0.75


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


def test_block_counts_are_the_rev2_circular_counts():
    def c3(n_dates, b=2000, seed=20261024, length=3):  # c3_kill_tier.block_counts at b1d8e65f, verbatim
        k = -(-n_dates // length)
        starts = np.random.default_rng(seed).integers(n_dates, size=(b, k))
        idx = ((starts[:, :, None] + np.arange(length)) % n_dates).reshape(b, -1)[:, :n_dates]
        return np.stack([np.bincount(r, minlength=n_dates) for r in idx]).astype(float)

    c = ps.block_counts(43)
    assert c.shape == (2000, 43) and (c.sum(axis=1) == 43).all()
    np.testing.assert_array_equal(c, c3(43))
    starts = np.random.default_rng(20261024).integers(43, size=(2000, 15))
    assert (starts >= 41).any()  # some blocks start in the last two dates and wrap to date 0
    assert ps.REV2_B == 2000 and ps.REV2_SEED == 20261024 and ps.BLOCK_LEN == 3


# ----------------------------------------------------------------------------- refusals

def _receipt(tmp_path, name="R-PD", est_diff=0.0, **over):
    emit = tmp_path / f"emit_{name}.parquet"
    emit.write_bytes(b"emit " + name.encode())
    sha_rec, est = ps.C4_RECORDED[name]
    rec = {"schema": ps.HARNESS_SCHEMA, "member": name, "module_sha256": ps.HARNESS_SHA256,
           "run_env_commit": ps.HARNESS_RUN_ENV, "recorded_gate2_sha256": sha_rec,
           "c4": {"pass": est_diff <= ps.C4_TOL, "recorded": {"estimate": est, "ci95": [0, 0]},
                  "abs_diff": {"estimate": est_diff, "ci95_lo": 0.0, "ci95_hi": 0.0}},
           "emit": {"path": str(emit), "sha256": hashlib.sha256(emit.read_bytes()).hexdigest()}}
    rec.update(over)
    path = tmp_path / f"c4_{name}.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path, emit


def test_members_and_blocks_as_built():
    assert {m[0] for m in ps.MEMBERS} == {"R-Q A", "R-I", "X17", "A2", "ASOS", "F2", "R-PD", "R-N"}
    assert {m[1] for m in ps.MEMBERS} == set(ps.BLOCKS) and ps.K == len(ps.BLOCKS) == 3
    assert {m[0] for m in ps.MEMBERS if m[2] is None} == set(ps.C4_RECORDED) == {"R-PD", "R-N"}
    for spec in ps.MEMBERS:
        if spec[1] == "POOL-0712":
            ok, why, _, _ = ps.member_status(spec)
            assert not ok and "X17 per-snapshot vector" in why
        if spec[1] == "F2-1316":
            assert "by construction" in ps.member_status(spec)[1]


def test_c4_receipt_gate(tmp_path):
    spec = ("R-PD", "POOL-0006", None)
    assert ps.member_status(spec) == (False, "no C4 receipt (member not replayed)", None, None)
    path, emit = _receipt(tmp_path)
    ok, why, got_path, got_sha = ps.member_status(spec, path)
    assert ok and why == "C4 PASS" and got_path == str(emit) and got_sha == ps._sha(emit)
    (tmp_path / "f").mkdir()
    bad, _ = _receipt(tmp_path / "f", est_diff=2e-9)
    assert ps.member_status(spec, bad)[:2] == (False, "C4 FAIL (replayed headline differs from the recorded one "
                                                     "beyond 1e-9)")
    for over in ({"module_sha256": "0" * 64}, {"run_env_commit": "0" * 40}, {"member": "R-N"},
                 {"recorded_gate2_sha256": "0" * 64}, {"schema": "other/1"}):
        d = tmp_path / str(len(list(tmp_path.iterdir())))
        d.mkdir()
        forged, _ = _receipt(d, **over)
        with pytest.raises(ps.PoolError):
            ps.member_status(spec, forged)
    d = tmp_path / "sha"
    d.mkdir()
    path2, emit2 = _receipt(d)
    emit2.write_bytes(b"changed")
    with pytest.raises(ps.PoolError, match="sha256"):
        ps.member_status(spec, path2)
    emit2.unlink()
    assert ps.member_status(spec, path2)[0] is False


def test_a_block_needs_two_c4_survivors():
    status = {m[0]: (False, "x", None, None) for m in ps.MEMBERS}
    status["R-PD"] = (True, "C4 PASS", "e", "s")
    assert ps.block_testable(status)["POOL-0006"] == (False, 1)
    status["R-N"] = (True, "C4 PASS", "e", "s")
    got = ps.block_testable(status)
    assert got == {"POOL-0712": (False, 0), "F2-1316": (False, 0), "POOL-0006": (True, 2)}
    assert ps.MIN_C4_SURVIVORS == 2


def test_run_refuses_receipts_for_unharnessed_members_before_anything_is_read(tmp_path):
    for name in ("X17", "F2", "nobody"):
        with pytest.raises(ps.PoolError, match="without a harness"):
            ps.run(layout=tmp_path / "no-layout", out_dir=tmp_path / "x", c4_receipts={name: "r.json"},
                   allow_dirty=True, repo_root=tmp_path)


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
