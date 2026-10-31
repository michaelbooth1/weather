"""Oct-Dec history LOYO batch W1 / X13 / X18 / X20 (lane L17, 2026-10-31; ledger row 95, rule A2).

Synthetic frames only, no real rows.
Guards: rule_octdec_loyo_batch A2 sections 1-4 and (a) - the nested-fit index sets (no inner fit trains on X or
Y; fold fit rows carry only the {X, Y} inner prediction); the W1 sigma' floor and the LOGMULT guard; the C-b
identity for centre and width arms; the C-c planted centre control and its negation (opposite beta, identical
d) and the planted W1 control; the placebo derangement (no fixed point, within market, hour and year); the
date-cluster bootstrap matching upstream_obs_screen.cluster_ci and its placebo-net draw; BH; the write-once out
dir below C:/t/l17/octdec; the 2021-2025 date refusal; the rule pin refusing before the out dir is touched.
"""
import importlib

import numpy as np
import pandas as pd
import pytest

try:
    ob = importlib.import_module("weather.calibration.octdec_loyo_batch")
    l6 = importlib.import_module("weather.calibration.upstream_obs_screen")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "refuse" in str(exc).lower():
        pytest.skip("research modules refuse this host by design", allow_module_level=True)
    raise

YEARS = (2021, 2022, 2023, 2024, 2025)


def toy_ctx(n_dates=40, seed=7, sig_value=2.0):
    """Two markets x hours 7-8 x 5 years x n_dates; dmax = mu0 + noise, inner centres = mu0 + small jitter."""
    rng = np.random.default_rng(seed)
    recs = []
    for y in YEARS:
        days = pd.date_range(f"{y}-10-01", periods=n_dates, freq="D").strftime("%Y-%m-%d")
        for m in ("austin", "miami"):
            for h in (7, 8):
                for d in days:
                    recs.append((m, h, y, d))
    f = pd.DataFrame(recs, columns=["market", "hour", "year", "local_date"])
    n = len(f)
    mu0 = 70.0 + rng.normal(0, 3, n)
    dmax = np.round(mu0 + rng.normal(0, 2.5, n))
    R = dmax - np.abs(np.round(rng.normal(3, 1, n)))
    year = f.year.to_numpy(int)
    inner = {}
    for pair in ob.inner_pairs(YEARS):
        v = np.full(n, np.nan)
        te = np.isin(year, tuple(pair))
        v[te] = mu0[te] + rng.normal(0, 0.3, te.sum())
        inner[pair] = v
    mu_fit = {y: ob.fold_fit_mu(year, y, inner, n) for y in YEARS}
    return {"frame": f, "mu0": mu0, "sig": np.full(n, sig_value), "ok": np.ones(n, bool), "year": year,
            "years": YEARS, "hour": f.hour.to_numpy(int), "markets": f.market.to_numpy(str),
            "dates": f.local_date.to_numpy(str), "R": R, "dmax": dmax, "v": mu0.copy(), "n_out": mu0.copy(),
            "mu_fit": mu_fit, "inner": inner}


def d_of(c, mu=None, sig=None):
    mu = c["mu0"] if mu is None else mu
    sig = c["sig"] if sig is None else sig
    return ob.brier(mu, sig, c["R"], c["dmax"]) - ob.brier(c["mu0"], c["sig"], c["R"], c["dmax"])


def resid_ref(c):
    ref = ob.per_fold_ref(c["year"], YEARS, c["mu_fit"], c["mu0"])
    return {y: c["dmax"] - ref[y] for y in YEARS}


# ----------------------------------------------------------------------------- nesting

def test_inner_fits_never_train_on_their_pair_and_fold_rows_use_only_pair_predictions():
    pairs = ob.inner_pairs(YEARS)
    assert len(pairs) == 10 and len(set(pairs)) == 10
    for pair in pairs:
        tr = ob.inner_train_years(YEARS, pair)
        assert len(tr) == 3 and not (set(tr) & pair)
    c = toy_ctx(n_dates=5)
    for y in YEARS:
        fm = c["mu_fit"][y]
        assert np.isnan(fm[c["year"] == y]).all()
        for x in YEARS:
            if x == y:
                continue
            sel = c["year"] == x
            np.testing.assert_array_equal(fm[sel], c["inner"][frozenset((x, y))][sel])
    ref = ob.per_fold_ref(c["year"], YEARS, c["mu_fit"], c["mu0"])
    for y in YEARS:
        np.testing.assert_array_equal(ref[y][c["year"] == y], c["mu0"][c["year"] == y])


# ----------------------------------------------------------------------------- W1

def test_w1_sigma_floor_is_never_weakened_and_gamma_zero_is_identity():
    sig = np.array([1.0, 1.5, 3.0])
    z, zbar = np.array([-5.0, 0.0, 4.0]), np.zeros(3)
    for g in ob.GAMMA_GRID:
        assert (ob.w1_sigma(sig, z, zbar, g) >= 1.0).all()
    np.testing.assert_array_equal(ob.w1_sigma(sig, z, zbar, 0.0), sig)
    assert ob.GAMMA_GRID[0] == 0.0 and ob.GAMMA_GRID[-1] == 1.0 and len(ob.GAMMA_GRID) == 21
    assert ob.w1_z([70.0, 70.1], [70.0, 72.0])[0] == pytest.approx(np.log(0.25))


def test_logmult_guard_zeroes_gamma_when_the_floor_makes_it_a_global_widening():
    c = toy_ctx(sig_value=1.0)  # every row on the 1 deg F floor: sigma' can only widen
    ref = resid_ref(c)
    z = {y: np.log(np.maximum(np.abs(ref[y]), 0.25)) for y in YEARS}
    sig_a, par, tr, _ = ob.w1_arm(z, c)
    guards = [g for y in YEARS for g in par[y]["logmult_guard"].values()]
    assert any(g["gamma_fitted"] > 0 for g in guards)
    assert any(g["guarded"] for g in guards)
    for y in YEARS:
        for h, g in par[y]["logmult_guard"].items():
            if g["guarded"]:
                assert par[y]["gamma"][h] == 0.0
                th = (c["year"] == y) & (c["hour"] == int(h))
                np.testing.assert_array_equal(sig_a[th], c["sig"][th])
    assert all(v["pass"] for v in tr.values())


def test_planted_w1_signal_passes_p0_and_the_gate_and_its_negation_fits_gamma_zero():
    c = toy_ctx(n_dates=60, sig_value=3.5)  # a regime where the literal LOGMULT guard does not bind
    ref = resid_ref(c)
    rng = np.random.default_rng(ob.PLANT_SEED)
    eps = rng.normal(0, 1.0, len(c["mu0"]))
    zp = {y: np.log(np.maximum(np.abs(ref[y]), 0.25)) + eps for y in YEARS}
    s_p, _, _, zc = ob.w1_arm(zp, c)
    p0 = ob.w1_p0(zc, c)
    assert p0["pass"] and p0["rho"] > 0.2
    st = ob.bootstrap(d_of(c, sig=s_p), c["dates"], draws=2000)
    assert ob.control_pass(st)
    s_n, gn, _, _ = ob.w1_arm({y: -zp[y] for y in YEARS}, c)
    for h in ("7", "8"):
        assert sum(1 for y in YEARS if gn[y]["gamma"][h] == 0.0) >= ob.W1_NEG_MIN_ZERO_FOLDS
    assert ob.bootstrap(d_of(c, sig=s_n), c["dates"], draws=2000)["ci95"][1] >= 0


def test_a_lever_fitted_to_zero_everywhere_gives_p_one_without_crashing():
    dates = np.repeat([f"2021-10-{i:02d}" for i in range(1, 11)], 3)
    st = ob.bootstrap(np.zeros(len(dates)), dates, placebos=[np.zeros(len(dates))], draws=200)
    assert st["p_one_sided"] == 1.0 and st["ci95"] == [0.0, 0.0] and st["daily_stats"] is None


def test_w1_p0_closes_a_null_signal():
    c = toy_ctx()
    rng = np.random.default_rng(3)
    zc = rng.normal(0, 1, len(c["mu0"]))
    assert not ob.w1_p0(zc, c)["pass"]


# ----------------------------------------------------------------------------- centre arms

def test_c_b_identity_for_centre_and_width_arms():
    c = toy_ctx(n_dates=10)
    rng = np.random.default_rng(1)
    X = {y: rng.normal(0, 1, (len(c["mu0"]), 3)) for y in YEARS}
    mz, par, _ = ob.centre_arm(X, c, zero=True)
    assert np.max(np.abs(d_of(c, mu=mz))) == 0.0
    assert all(not np.any(b) for p in par.values() for b, _, _ in p.values())
    z = {y: rng.normal(0, 1, len(c["mu0"])) for y in YEARS}
    sz, _, _, _ = ob.w1_arm(z, c, zero=True)
    assert np.max(np.abs(d_of(c, sig=sz))) == 0.0


def test_missing_column_keeps_a0_on_that_row():
    X = np.array([[1.0, 2.0], [np.nan, 1.0], [3.0, 0.0]])
    params = {7: (np.array([1.0, 1.0]), np.array([0.0, 0.0]), 3)}
    delta = ob.centre_shift(X, np.array([7, 7, 7]), np.ones(3, bool), params)
    np.testing.assert_array_equal(delta, [3.0, 0.0, 3.0])


def test_c_c_planted_centre_passes_and_its_negation_flips_beta_with_identical_d():
    c = toy_ctx(n_dates=60)
    ref = resid_ref(c)
    pooled = np.concatenate([ref[y][c["year"] != y] for y in YEARS])
    eps = np.random.default_rng(ob.PLANT_SEED).normal(0, float(np.std(pooled)), len(c["mu0"]))
    plant = {y: (0.5 * ref[y] + eps)[:, None] for y in YEARS}
    mu_p, par_p, tr = ob.centre_arm(plant, c)
    mu_n, par_n, _ = ob.centre_arm({y: -plant[y] for y in YEARS}, c)
    for y in YEARS:
        for h in par_p[y]:
            assert par_p[y][h][0][0] > 0 and par_n[y][h][0][0] < 0
            assert par_n[y][h][0][0] == pytest.approx(-par_p[y][h][0][0])
    d_p, d_n = d_of(c, mu=mu_p), d_of(c, mu=mu_n)
    assert np.max(np.abs(d_n - d_p)) <= ob.NEG_IDENTICAL_TOL
    assert ob.control_pass(ob.bootstrap(d_p, c["dates"], draws=2000))
    assert all(v["pass"] for v in tr.values())


# ----------------------------------------------------------------------------- placebo, statistic, BH

def test_placebo_derangement_has_no_fixed_point_and_stays_within_market_hour_year():
    c = toy_ctx(n_dates=8)
    src = ob.placebo_src(c["markets"], c["hour"], c["year"], c["dates"], ob.PLACEBO_SEED0)
    assert not (src == np.arange(len(src))).any()
    for key in ("markets", "hour", "year"):
        np.testing.assert_array_equal(c[key][src], c[key])
    assert (c["dates"][src] != c["dates"]).all()
    assert sorted(src.tolist()) == list(range(len(src)))
    np.testing.assert_array_equal(src, ob.placebo_src(c["markets"], c["hour"], c["year"], c["dates"],
                                                      ob.PLACEBO_SEED0))
    other = ob.placebo_src(c["markets"], c["hour"], c["year"], c["dates"], ob.PLACEBO_SEED0 + 1)
    assert not np.array_equal(src, other)
    with pytest.raises(ob.OctDecBatchError):
        dup = np.concatenate([c["dates"][:1], c["dates"][:-1]])
        ob.placebo_src(c["markets"], c["hour"], c["year"], dup, 1)


def test_bootstrap_matches_cluster_ci_and_nets_placebos_per_draw():
    rng = np.random.default_rng(5)
    dates = np.repeat([f"2021-10-{i:02d}" for i in range(1, 31)], 4)
    d = rng.normal(-0.01, 0.05, len(dates))
    st = ob.bootstrap(d, dates, draws=3000, seed=11)
    point, lo, hi = l6.cluster_ci(d, dates, draws=3000, seed=11)
    assert st["point"] == pytest.approx(point) and st["ci95"] == pytest.approx([lo, hi])
    keys, s, n = ob._date_sums(d, dates)
    idx = ob.boot_indices(len(s), 3000, 11)
    boot = s[idx].sum(1) / n[idx].sum(1)
    assert st["p_one_sided"] == pytest.approx((1 + (boot >= 0).sum()) / 3001)
    same = ob.bootstrap(d, dates, placebos=[d, d], draws=3000, seed=11)
    assert same["d_net"]["point"] == pytest.approx(0.0) and same["d_net"]["ci95"] == pytest.approx([0.0, 0.0])
    with pytest.raises(ob.OctDecBatchError):
        ob.bootstrap(d, dates, placebos=[d[:-1]], draws=10)


def test_bh_step_up():
    out = ob.bh_reject({"W1": 1.0, "X13": 0.01, "X18": 0.03, "X20": 0.04})
    assert out["X13"] == (pytest.approx(0.04), True)
    assert out["X18"] == (pytest.approx(0.04 * 4 / 3), True) and out["X20"] == (pytest.approx(0.04 * 4 / 3), True)
    assert out["W1"] == (1.0, False)
    assert ob.K == 4 and ob.BH_Q == 0.10


# ----------------------------------------------------------------------------- refusals

def test_out_dir_must_be_new_and_strictly_below_the_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "OUT_ROOT", tmp_path / "octdec")
    with pytest.raises(ob.OctDecBatchError):
        ob.check_out_dir(tmp_path / "octdec")
    with pytest.raises(ob.OctDecBatchError):
        ob.check_out_dir(tmp_path / "elsewhere" / "run1")
    (tmp_path / "octdec" / "run0").mkdir(parents=True)
    with pytest.raises(ob.OctDecBatchError):
        ob.check_out_dir(tmp_path / "octdec" / "run0")
    assert ob.check_out_dir(tmp_path / "octdec" / "run1") == (tmp_path / "octdec" / "run1").resolve()


def test_dates_outside_2021_2025_refuse():
    ob.check_dates(["2021-01-01", "2025-12-31"], "ok")
    for bad in ("2020-12-31", "2026-01-01", "2026-09-30"):
        with pytest.raises(ob.OctDecBatchError):
            ob.check_dates(["2023-10-01", bad], "rows")


def test_rule_pin_refuses_before_the_out_dir_is_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(ob, "OUT_ROOT", tmp_path / "octdec")
    rule = tmp_path / "rule.md"
    rule.write_text("not the rule", encoding="utf-8")
    out = tmp_path / "octdec" / "run"
    with pytest.raises(ob.OctDecBatchError, match="rule sha"):
        ob.run(research_root=tmp_path / "none", nbm_corpus=tmp_path / "none", mg2_coefficients=tmp_path / "none",
               rule=rule, c1_receipt=tmp_path / "none", out=out)
    assert not out.exists() and not (tmp_path / "octdec").exists()


def test_s1_and_gate_constants_match_the_rule():
    assert (ob.COVERAGE_MIN, ob.X20_MIN_ROWS, ob.X20_MIN_DATES, ob.X20_S_FINITE_MIN) == (0.90, 10_000, 300, 0.90)
    assert ob.X20_HOURS == (13, 14) and ob.ARMS == ("W1", "X13", "X18", "X20")
    assert (ob.BOOT_DRAWS, ob.BOOT_SEED, ob.PLACEBO_J, ob.PLACEBO_SEED0) == (10_000, 20261024, 20, 20260921)
    assert (ob.LOGMULT_MAX, ob.Z_FLOOR, ob.P0_RHO_MIN, ob.P0_MAX_OPPOSITE_YEARS) == (0.02, 0.25, 0.05, 1)
    assert (ob.VERDICT_SCREEN, ob.VERDICT_KILL) == ("SCREEN", "KILL at edge size")
