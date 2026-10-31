"""Ruling (b) post-look analysis on synthetic per-date paths only (no repository data is read)."""

from __future__ import annotations

import ast
import json
import math
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import t as student_t

from weather.calibration import b_post_look_serial as pl

D0 = date(2027, 1, 1)
B_BOUND = ("b_scorer", "mg2_composite", "dev_scorecard", "loss_atlas", "mg2_inputs", "mg2_input_allowlist",
           "guidance_extract_parser", "pooled_residual_model", "mg_serve_core", "mg2_p3d_n", "l6_stack", "mg1")


def ar1(n, rho, sd, rng):
    x = np.empty(n)
    x[0] = rng.normal(0, sd)
    innov = sd * math.sqrt(1 - rho ** 2)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + rng.normal(0, innov)
    return x


def table(x, mu=0.0, cells=None, dates=None):
    cells = [3] * len(x) if cells is None else list(cells)
    dates = [D0 + timedelta(days=i) for i in range(len(x))] if dates is None else dates
    return [{"date": d.isoformat(), "S": float(n * (mu + v)), "n": int(n)} for d, v, n in zip(dates, x, cells)]


def decision(rows, verdict="PASS", label="edge"):
    delta = sum(r["S"] for r in rows) / sum(r["n"] for r in rows)
    return {"decision": {"verdict": verdict, "label": label, "estimate": delta, "ci95": [delta - 1, delta + 1]}}


def reference(rows, delta):
    """Independent numpy statement of master's parameters (equal-cells-free, consecutive-date pairs)."""
    dates = np.array([date.fromisoformat(r["date"]).toordinal() for r in rows])
    s = np.array([r["S"] for r in rows])
    n = np.array([r["n"] for r in rows], dtype=float)
    e = (s - delta * n) / n.mean()
    ec = e - e.mean()
    ok = np.diff(dates) == 1
    rho = np.mean(ec[:-1][ok] * ec[1:][ok]) / np.mean(ec ** 2)
    ru = min(0.9, max(rho, 0.22))
    bm = np.convolve(e, np.ones(3) / 3, mode="valid")
    ratio_sq = 3 * bm.var() / e.var()
    vif = max(1.0, (1 + ru) / (1 - ru), ratio_sq)
    k = len(e)
    return rho, delta + student_t.ppf(0.975, k - 1) * e.std(ddof=1) / math.sqrt(k) * math.sqrt(vif)


# ----------------------------------------------------------------------------- the formula

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_matches_independent_reference_with_unequal_cells_and_a_gap(seed):
    rng = np.random.default_rng(seed)
    x = ar1(40, 0.3, 0.01, rng)
    dates = [D0 + timedelta(days=i + (5 if i >= 20 else 0)) for i in range(40)]
    rows = table(x, mu=0.002, cells=rng.integers(1, 9, size=40), dates=dates)
    out = pl.analyse(rows, decision(rows))
    rho, u = reference(rows, out["b_estimate"])
    assert out["n_pairs"] == 38
    assert out["rho_hat"] == pytest.approx(rho, rel=1e-10)
    assert out["u_adj"] == pytest.approx(u, rel=1e-10)
    assert out["t_df"] == 39 and out["t_quantile"] == pytest.approx(student_t.ppf(0.975, 39))


def test_equal_cells_reduce_to_date_mean_minus_delta():
    rng = np.random.default_rng(7)
    rows = table(rng.normal(0.001, 0.01, 30), cells=[4] * 30)
    delta = sum(r["S"] for r in rows) / sum(r["n"] for r in rows)
    e, n_bar = pl.linearised(pl.per_date_rows(rows), delta)
    assert n_bar == 4
    assert e == pytest.approx([r["S"] / r["n"] - delta for r in rows])


def test_unequal_cells_weight_by_cell_count():
    rows = [{"date": "2027-01-01", "S": 0.6, "n": 6}, {"date": "2027-01-02", "S": 0.0, "n": 2},
            {"date": "2027-01-03", "S": 0.2, "n": 4}]
    delta = 0.8 / 12
    e, n_bar = pl.linearised(pl.per_date_rows(rows), delta)
    assert n_bar == 4
    assert e == pytest.approx([(0.6 - 6 * delta) / 4, (0.0 - 2 * delta) / 4, (0.2 - 4 * delta) / 4])
    assert sum(e) == pytest.approx(0.0, abs=1e-15)


def test_iid_long_path_floors_rho_at_022():
    rng = np.random.default_rng(11)
    rows = table(rng.normal(0, 0.01, 6000), cells=rng.integers(2, 7, size=6000))
    out = pl.analyse(rows, decision(rows))
    assert abs(out["rho_hat"]) < 0.04
    assert out["rho_used"] == 0.22
    assert out["vif"]["block3_ratio_sq"] == pytest.approx(1.0, abs=0.08)
    assert out["vif"]["used"] == pytest.approx(1.22 / 0.78)


@pytest.mark.parametrize("rho", [0.22, 0.5])
def test_ar1_long_path_recovers_rho(rho):
    rng = np.random.default_rng(int(rho * 100))
    rows = table(ar1(8000, rho, 0.01, rng))
    out = pl.analyse(rows, decision(rows))
    assert out["rho_hat"] == pytest.approx(rho, abs=0.03)
    assert out["vif"]["used"] == pytest.approx(max(1.22 / 0.78, (1 + out["rho_hat"]) / (1 - out["rho_hat"])))
    assert out["vif"]["used"] >= out["vif"]["block3_ratio_sq"]


def test_rho_is_capped_at_09():
    rows = table(ar1(4000, 0.97, 0.01, np.random.default_rng(5)))
    out = pl.analyse(rows, decision(rows))
    assert out["rho_hat"] > 0.9 and out["rho_used"] == 0.9
    assert out["vif"]["ar1"] == pytest.approx(19.0)


def test_block_ratio_is_the_exact_recentred_moving_block_variance():
    # Runs of three: moving block-3 means cycle 1, 1/3, -1/3, -1, -1/3, 1/3 (variance 22/54), iid variance 1.
    e = list(np.tile([1.0, 1.0, 1.0, -1.0, -1.0, -1.0], 10))
    means = np.convolve(e, np.ones(3) / 3, mode="valid")
    assert pl.block_ratio_sq(e) == pytest.approx(3 * means.var())
    assert pl.block_ratio_sq(e) == pytest.approx(3 * (22 / 54) / 1.0, rel=0.05)


def test_vif_takes_the_block_ratio_when_it_is_largest(monkeypatch):
    rows = _rows(30)
    monkeypatch.setattr(pl, "block_ratio_sq", lambda e: 5.0)
    out = pl.analyse(rows, decision(rows))
    assert out["vif"]["used"] == 5.0 and out["vif"]["block3_ratio_sq"] == 5.0
    monkeypatch.setattr(pl, "block_ratio_sq", lambda e: 0.5)
    assert pl.analyse(rows, decision(rows))["vif"]["used"] == pytest.approx(max(1.0, pl.analyse(
        rows, decision(rows))["vif"]["ar1"]))


@pytest.mark.parametrize("rho,limit", [(0.0, 0.05), (0.22, 0.06), (0.5, 0.09)])
def test_null_paths_rarely_give_a_robust_pass(rho, limit):
    """At n = 45 under a zero mean, U_adj < 0 is the 'not fragile' event; it stays near its one-sided 0.025."""
    rng = np.random.default_rng(20260921 + int(rho * 100))
    hits = 0
    for _ in range(400):
        rows = table(ar1(45, rho, 0.0105, rng), cells=rng.integers(3, 6, size=45))
        hits += pl.analyse(rows, decision(rows))["u_adj"] < 0
    assert hits / 400 < limit


# ----------------------------------------------------------------------------- row 84's VAR(1) case

def row84_var1(n, rng):
    """Row 84's joint three-range VAR(1): diagonal AR, marginal SDs and correlations, innovations clipped PSD."""
    a = np.diag([0.219, 0.118, 0.310])
    sd = np.array([0.0105, 0.0101, 0.0127])
    corr = np.array([[1, 0.956, 0.927], [0.956, 1, 0.777], [0.927, 0.777, 1]])
    sigma = corr * np.outer(sd, sd)
    q = sigma - a @ sigma @ a.T
    w, v = np.linalg.eigh(q)
    q = v @ np.diag(np.clip(w, 0, None)) @ v.T
    chol = np.linalg.cholesky(q + 1e-14 * np.eye(3))
    x = np.empty((n, 3))
    x[0] = np.linalg.cholesky(sigma) @ rng.normal(size=3)
    for i in range(1, n):
        x[i] = a @ x[i - 1] + chol @ rng.normal(size=3)
    return x


def test_row84_var1_descriptive_fit_recovers_the_diagonal():
    x = row84_var1(20000, np.random.default_rng(84))
    primary, early, late = (table(x[:, j]) for j in range(3))
    out = pl.analyse(primary, decision(primary), {"07-12": early, "13-16": late})
    var1 = out["var1_descriptive"]
    assert var1["status"] == "fitted" and var1["ranges"] == ["07-16", "07-12", "13-16"]
    assert var1["sd"]["07-16"] == pytest.approx(0.0105, rel=0.05)
    assert out["rho_hat"] == pytest.approx(0.219, abs=0.03)
    assert out["vif"]["used"] >= 1.22 / 0.78
    # VAR(1) is descriptive: the label and U_adj do not depend on the split tables.
    assert pl.analyse(primary, decision(primary))["u_adj"] == out["u_adj"]


def test_row84_var1_null_at_45_dates_keeps_robust_pass_near_nominal():
    rng = np.random.default_rng(20260921)
    hits = 0
    for _ in range(400):
        rows = table(row84_var1(45, rng)[:, 0])
        hits += pl.analyse(rows, decision(rows))["u_adj"] < 0
    assert hits / 400 < 0.06


# ----------------------------------------------------------------------------- labels

def _scaled(mu, verdict, label):
    rng = np.random.default_rng(3)
    rows = table(rng.normal(0, 0.005, 45), mu=mu)
    return pl.analyse(rows, decision(rows, verdict, label))


def test_pass_is_fragile_iff_u_adj_at_least_zero():
    fragile = _scaled(0.0, "PASS", "edge")
    assert fragile["u_adj"] >= 0 and fragile["fragile_label"] == pl.PASS_FRAGILE
    robust = _scaled(-0.01, "PASS", "edge")
    assert robust["u_adj"] < 0 and robust["fragile_label"] is None
    assert fragile["b_verdict"] == robust["b_verdict"] == "PASS" and fragile["b_label"] == "edge"


def test_not_worse_is_fragile_iff_u_adj_at_least_margin():
    fragile = _scaled(0.004, "INCONCLUSIVE", "NOT-WORSE")
    assert fragile["u_adj"] >= 0.0027 and fragile["fragile_label"] == pl.NOT_WORSE_FRAGILE
    robust = _scaled(-0.004, "INCONCLUSIVE", "NOT-WORSE")
    assert robust["u_adj"] < 0.0027 and robust["fragile_label"] is None
    assert fragile["b_label"] == "NOT-WORSE" and fragile["b_verdict"] == "INCONCLUSIVE"


@pytest.mark.parametrize("verdict,label", [("FAIL", "kill_edge_claim"), ("INCONCLUSIVE", None)])
def test_fail_and_other_inconclusive_pass_through(verdict, label):
    for mu in (-0.01, 0.0, 0.01):
        out = _scaled(mu, verdict, label)
        assert out["fragile_label"] is None and out["b_verdict"] == verdict and out["b_label"] == label


def test_label_boundaries_are_inclusive():
    assert pl.fragile_label({"verdict": "PASS"}, 0.0) == pl.PASS_FRAGILE
    assert pl.fragile_label({"verdict": "INCONCLUSIVE", "label": "NOT-WORSE"}, 0.0027) == pl.NOT_WORSE_FRAGILE
    assert pl.fragile_label({"verdict": "INCONCLUSIVE", "label": "NOT-WORSE"}, 0.00269) is None


def test_decision_object_alone_is_accepted_and_never_mutated():
    rows = table(np.random.default_rng(1).normal(0, 0.01, 20))
    look = decision(rows)
    before = json.dumps(look, sort_keys=True)
    assert pl.analyse(rows, look["decision"])["u_adj"] == pl.analyse(rows, look)["u_adj"]
    assert json.dumps(look, sort_keys=True) == before


# ----------------------------------------------------------------------------- refusals

def _rows(n=10):
    return table(np.random.default_rng(2).normal(0, 0.01, n))


@pytest.mark.parametrize("mutate,match", [
    (lambda r: r.append(dict(r[0])), "repeats"),
    (lambda r: r[0].update(n=0), "positive integer"),
    (lambda r: r[0].update(n=2.5), "positive integer"),
    (lambda r: r[0].update(n=True), "positive integer"),
    (lambda r: r[0].update(S=float("nan")), "not finite"),
    (lambda r: r[0].update(S="x"), "not a number"),
    (lambda r: r[0].update(date="01/01/2027"), "ISO date"),
])
def test_bad_rows_refuse(mutate, match):
    rows = _rows()
    look = decision(rows)
    mutate(rows)
    with pytest.raises(pl.PostLookRefused, match=match):
        pl.analyse(rows, look)


def test_too_few_dates_refuse():
    rows = _rows(2)
    with pytest.raises(pl.PostLookRefused, match="dates"):
        pl.analyse(rows, decision(rows))


def test_too_few_consecutive_pairs_refuse():
    rows = table([0.01, -0.02, 0.005, 0.0], dates=[D0, D0 + timedelta(days=1), D0 + timedelta(days=5),
                                                   D0 + timedelta(days=9)])
    with pytest.raises(pl.PostLookRefused, match="consecutive-date pairs"):
        pl.analyse(rows, decision(rows))


def test_zero_variance_refuses():
    rows = table([0.25] * 10)
    with pytest.raises(pl.PostLookRefused, match="zero variance"):
        pl.analyse(rows, decision(rows))


def test_estimate_that_is_not_the_cell_mean_refuses():
    rows = _rows()
    look = decision(rows)
    look["decision"]["estimate"] += 1e-4
    with pytest.raises(pl.PostLookRefused, match="cell mean"):
        pl.analyse(rows, look)


@pytest.mark.parametrize("verdict", ["VOID", "ABORTED", None, "pass"])
def test_non_scored_verdicts_refuse(verdict):
    rows = _rows()
    look = decision(rows, verdict=verdict)
    with pytest.raises(pl.PostLookRefused, match="verdict"):
        pl.analyse(rows, look)


def test_cells_helper_sums_per_date():
    cells = [{"date": "2027-01-01", "diff": 0.1}, {"date": "2027-01-01", "diff": -0.3},
             {"date": "2027-01-02", "diff": 0.2}]
    assert sorted(pl.per_date_from_cells(cells), key=lambda r: r["date"]) == [
        {"date": "2027-01-01", "S": pytest.approx(-0.2), "n": 2}, {"date": "2027-01-02", "S": 0.2, "n": 1}]


# ----------------------------------------------------------------------------- CLI and isolation

def test_cli_writes_once_and_refuses_overwrite(tmp_path):
    rows = _rows(15)
    (tmp_path / "per_date.json").write_text(json.dumps({"primary": rows}), encoding="utf-8")
    (tmp_path / "b_look.json").write_text(json.dumps(decision(rows)), encoding="utf-8")
    argv = ["--per-date", str(tmp_path / "per_date.json"), "--b-look", str(tmp_path / "b_look.json"),
            "--out", str(tmp_path / "out.json")]
    assert pl.main(argv) == 0
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out["schema"] == pl.SCHEMA and out["module_sha256"] == pl.module_sha256()
    with pytest.raises(SystemExit, match="exists"):
        pl.main(argv)


def test_module_imports_nothing_b_bound():
    tree = ast.parse(Path(pl.__file__).read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(a.name for a in node.names)
    assert not [n for n in names for b in B_BOUND if b in n]
    assert not [n for n in names if n.startswith("weather")]
