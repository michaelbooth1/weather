"""Lane L2 rung R-O gates 2 and 3 scorer (rule_rn.md lines 117-148), on fabricated data only.

Guards: the shift s = a + b (G - N) is zero where G or N is missing or the snapshot is out of scope; the L6_G
walk-forward uses only dates strictly before the scored date and gives (0, 0) before any prior date; the all-years
P3d_N_fix_G fit keeps the plain LOYO and nested-inner populations apart and reproduces gate 1's per-year picks and
rows; dev G is read at the pinned hour field with unparsed or out-of-window hours left without G; the scorer refuses
an unpinned population or hour field and any input whose sha256 differs from its pin before loading anything; and a
synthetic end-to-end run on fabricated tables reproduces s = 0, preserves mass, passes an informative G and closes a
noise G.
"""
import importlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise

UTC = timezone.utc


def test_shift_array_zero_where_missing_or_out_of_scope():
    g = np.array([80.0, np.nan, 82.0, 84.0])
    n = np.array([78.0, 79.0, np.nan, 80.0])
    scope = np.array([True, True, True, False])
    s = prm.ro_shift_array(0.5, 0.25, g, n, scope)
    assert s.tolist() == [1.0, 0.0, 0.0, 0.0]
    s = prm.ro_shift_array(np.array([0.5, 0.5, 0.5, np.nan]), np.array([0.25] * 4), g, n, np.ones(4, bool))
    assert s.tolist() == [1.0, 0.0, 0.0, 0.0]  # no coefficient for the row -> 0


def test_walk_forward_uses_only_prior_dates():
    good = np.ones(len(prm.RO_PAIRS))
    good[prm.RO_PAIRS.index((0.5, 0.0))] = 0.0
    later = np.ones(len(prm.RO_PAIRS))
    later[prm.RO_PAIRS.index((-1.0, 0.5))] = -10.0
    sums = {(7, "2026-08-01"): good, (7, "2026-08-02"): later}
    out = prm.ro_walk_forward(sums, ["2026-08-01", "2026-08-02", "2026-08-03"], hours=(7, 8))
    assert out[(7, "2026-08-01")] == (0.0, 0.0)  # before any prior date
    assert out[(7, "2026-08-02")] == (0.5, 0.0)  # only 08-01 is prior
    assert out[(7, "2026-08-03")] == (-1.0, 0.5)
    assert all(out[(8, d)] == (0.0, 0.0) for d in ("2026-08-01", "2026-08-02", "2026-08-03"))


def test_fit_pooled_records_training_score():
    loss = np.ones(len(prm.RO_PAIRS))
    loss[prm.RO_PAIRS.index((0.3, 0.1))] = 0.25
    fit = prm.ro_fit_pooled({9: loss})
    assert (fit[9]["a"], fit[9]["b"]) == (0.3, 0.1)
    assert fit[9]["training_score_not_worse"] and fit[9]["loss_noshift"] == 1.0


def _fake_predict(at_hour, train_years, target_year, buckets, gvals, hour):
    """Deterministic fabricated predictions: the pmf centre depends on the training years, so populations differ."""
    rows = []
    centre = 70 + (sum(train_years) % 3)
    for k, market in enumerate(("m1", "m2")):
        diff = None if (target_year + k) % 4 == 0 else float(target_year % 3) - 1.0
        dist = {centre - 1: 0.25, centre: 0.5, centre + 1: 0.25}
        actual = 71 + k
        rows.append({"market": market, "date": f"{target_year}-08-0{k + 1}", "dist": dist, "actual": actual,
                     "floor": 60.0, "diff": diff, "raw_brier": float(sum((p - (key == actual)) ** 2
                                                                      for key, p in dist.items()))})
    return rows


def _fake_frame():
    return pd.DataFrame({"hour": [h for h in (7, 8) for _ in range(3)], "year": [2021, 2022, 2023] * 2})


def test_fix_fit_populations_are_distinct_and_controls_reproduce_gate1():
    loyo, nested, by_held, rows = prm.ro_fix_fit_losses(_fake_frame(), None, None, hours=(7, 8),
                                                        predict=_fake_predict)
    assert set(loyo) == set(nested) == {7, 8}
    assert len(rows) == 2 * 3 * 2  # hours x held years x markets
    assert set(by_held) == {(y, h) for y in (2021, 2022, 2023) for h in (7, 8)}
    assert np.allclose(sum(v for (y, h), v in by_held.items() if h == 7), nested[7])
    assert not np.allclose(loyo[7], nested[7])
    # rows with a missing G contribute the same loss at every pair (s = 0)
    r = next(r for r in rows if r["gefs_minus_anchor"] is None)
    assert r["noshift_brier"] == pytest.approx(r["P3d_N_fix_brier"])
    gate1 = {f"{y}|h{h:02d}": dict(zip(("a", "b"), prm.ro_pick(v))) for (y, h), v in by_held.items()}
    assert prm.ro_check_gate1_coefficients(by_held, gate1) == 6
    bad = dict(gate1, **{"2021|h07": {"a": 2.9, "b": 1.0}})
    with pytest.raises(prm.PooledModelError):
        prm.ro_check_gate1_coefficients(by_held, bad)
    assert prm.ro_check_loyo_rows(rows, [dict(r) for r in rows]) == 0.0
    off = [dict(r) for r in rows]
    off[0]["noshift_brier"] += 1e-6
    with pytest.raises(prm.PooledModelError):
        prm.ro_check_loyo_rows(rows, off)


def _gefs_table(day, n_members=30):
    d = date.fromisoformat(day)
    cycle = datetime(d.year, d.month, d.day, 6, tzinfo=UTC)
    avail = cycle + timedelta(hours=4)
    rows = [(f"gep{k:02d}", cycle + timedelta(hours=fh), avail, 80.0 + k / 10.0)
            for k in range(1, n_members + 1) for fh in (6, 9, 12, 15, 18, 21, 24)]
    return {("nyc", day): rows}


def test_dev_gefs_reads_the_pinned_hour_field():
    snaps = pd.DataFrame({"market": ["nyc", "nyc", "nyc", "nyc", "zzz"],
                          "target_date": ["2026-08-10"] * 5,
                          "local_hour": [7, 9, 13, 5, 9], "cutoff_hour": ["7", "x", "7", "5", "9"]})
    tz = {"nyc": "America/New_York"}
    want = np.mean([80.0 + k / 10.0 for k in range(1, 31)])
    g, h = prm.ro_dev_gefs(snaps, _gefs_table("2026-08-10"), tz, "local_hour")
    assert h.tolist() == [7, 9, 13, 5, 9]
    assert g[0] == pytest.approx(want) and g[1] == pytest.approx(want)
    assert np.isnan(g[2:]).all()  # h13 / h05 out of window, unknown market
    g, h = prm.ro_dev_gefs(snaps, _gefs_table("2026-08-10"), tz, "cutoff_hour")
    assert h.tolist() == [7, -1, 7, 5, 9]
    assert g[0] == pytest.approx(want) and np.isnan(g[1]) and g[2] == pytest.approx(want)
    # the 06Z cycle lands 10Z: at 05:00 EDT (09Z) it is not yet available, so no G
    g, _ = prm.ro_dev_gefs(snaps.iloc[[3]], _gefs_table("2026-08-10"), tz, "local_hour", hours=(5,))
    assert np.isnan(g[0])
    few, _ = prm.ro_dev_gefs(snaps.iloc[[0]], _gefs_table("2026-08-10", 24), tz, "local_hour")
    assert np.isnan(few[0])


def _kwargs(tmp_path, **over):
    paths = {}
    for name in ("layout", "fix_jsonl", "coefficients", "nowcasts", "loyo_result", "loyo_rows", "parity_result",
                 "records_root", "nbm_train_corpus", "ra_loyo_rows", "gefs_corpus"):
        p = tmp_path / name
        p.write_text("fabricated", encoding="utf-8")
        paths[name] = str(p)
    paths.update(fix_fit_population="loyo", dev_hour_field="local_hour", out_path=str(tmp_path / "out" / "s.json"))
    paths.update(over)
    return paths


@pytest.mark.parametrize("over", [{"fix_fit_population": None}, {"fix_fit_population": "all"},
                                  {"dev_hour_field": None}, {"dev_hour_field": "hour"}])
def test_score_refuses_unpinned_choices(tmp_path, over):
    with pytest.raises(prm.PooledModelError, match="pinned"):
        prm.rung_o_score(**_kwargs(tmp_path, **over))
    assert not (tmp_path / "out").exists()


def test_score_refuses_unpinned_inputs_and_overwrite(tmp_path):
    with pytest.raises(prm.PooledModelError, match="sha"):
        prm.rung_o_score(**_kwargs(tmp_path))
    kw = _kwargs(tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "s.json").write_text("{}", encoding="utf-8")
    with pytest.raises(prm.PooledModelError, match="overwrite"):
        prm.rung_o_score(**kw)


def test_cli_requires_both_pins(capsys):
    argv = ["rung-o-score"] + [x for f in ("--layout", "--fix", "--coefficients", "--nowcasts", "--loyo-result",
                                             "--loyo-rows", "--parity-result", "--records", "--nbm-train-corpus",
                                             "--ra-loyo-rows", "--gefs-corpus", "--out") for x in (f, "x")]
    with pytest.raises(SystemExit):
        prm._parse(argv)
    with pytest.raises(SystemExit):
        prm._parse(argv + ["--fix-fit-population", "loyo", "--dev-hour-field", "hour"])
    args = prm._parse(argv + ["--fix-fit-population", "nested-inner", "--dev-hour-field", "cutoff_hour"])
    assert (args.fix_fit_population, args.dev_hour_field) == ("nested-inner", "cutoff_hour")


# ------------------------------------------------------------------ synthetic end-to-end (fabricated tables)

BANDS = [("lte", None, 70)] + [("eq", k, k) for k in range(71, 77)] + [("gte", 77, None)]


def _ncdf(x, mu, sd):
    return 0.5 * (1.0 + np.vectorize(math.erf)((np.asarray(x, float) - mu) / (sd * math.sqrt(2.0))))


def _band_p(mu, sd):
    out = []
    for kind, low, high in BANDS:
        up = 1.0 if kind == "gte" else _ncdf(high + 0.5, mu, sd)
        lo = 0.0 if kind == "lte" else _ncdf(low - 0.5, mu, sd)
        out.append(float(up - lo))
    return np.array(out)


def _band_p_vec(kind, low, high, mu, sd):
    up = np.where(kind == "gte", 1.0, _ncdf(np.nan_to_num(high) + 0.5, mu, sd))
    lo = np.where(kind == "lte", 0.0, _ncdf(np.nan_to_num(low) - 0.5, mu, sd))
    return np.clip(up - lo, 0.0, None)


def _fabricate(informative, seed=7):
    rng = np.random.default_rng(seed)
    dates = [(date(2026, 8, 1) + timedelta(days=i)).isoformat() for i in range(30)]
    snaps, bands, labels, market = [], [], [], []
    for d in dates:
        for m in ("m1", "m2", "m3"):
            truth = 73.5 + rng.normal(0, 1.5)
            for h in range(7, 14):
                rk = f"{m}|{d}|{h}"
                n = truth + rng.normal(0, 2.0)
                g = truth + rng.normal(0, 0.4) if informative else n + rng.normal(0, 3.0)
                snaps.append({"row_key": rk, "date": d, "target_date": d, "market": m, "local_hour": h,
                              "cutoff_hour": str(h), "n_bands": len(BANDS), "v2_mean": n, "G": g,
                              "guidance_physical_floor": 60.0, "high_so_far": np.nan,
                              "trusted_current_max": np.nan})
                y = int(math.floor(truth + 0.5))
                winner = 0 if y <= 70 else (len(BANDS) - 1 if y >= 77 else y - 70)
                labels.append({"row_key": rk, "date": d, "winner": winner})
                pm = _band_p(n, 2.2)
                for i, (kind, low, high) in enumerate(BANDS):
                    bands.append({"row_key": rk, "date": d, "band_index": i, "kind": kind,
                                  "low": np.nan if low is None else float(low),
                                  "high": np.nan if high is None else float(high), "p_served": 1.0 / len(BANDS)})
                    market.append({"row_key": rk, "date": d, "band_index": i, "p_market_yes": float(pm[i])})
    lay = SimpleNamespace(snaps=pd.DataFrame(snaps), bands=pd.DataFrame(bands), labels=pd.DataFrame(labels),
                          market=pd.DataFrame(market), dates=dates)
    dists = {}
    for r in lay.snaps.itertuples(index=False):
        keys = np.arange(55, 95)
        p = _ncdf(keys + 0.5, r.v2_mean, 2.0) - _ncdf(keys - 0.5, r.v2_mean, 2.0)
        dists[r.row_key] = {int(k): float(v) for k, v in zip(keys, p / p.sum())}
    return lay, dists


def _run_core(lay, dists, coef_fix, l6_rows_seen=None):
    from weather.calibration import r0_ols_floor_challenger as l3
    from weather.reporting.scorecards import dev_scorecard as sc

    cache = {"tab": None}

    def arm_probs(tab, arm, shift, rows):
        if arm == "P3d_N_fix":
            if cache["tab"] is not tab:
                cache.update(tab=tab, prep=prm.rm_fix_prepare(dists, tab.bands))
            pos = dict(zip(tab.snaps.row_key, range(len(tab.snaps))))
            return tab.candidate_vector(prm.rm_fix_band_probs(cache["prep"], lambda rk: shift[pos[rk]]))[0]
        keep = np.ones(len(tab.snaps), bool) if rows is None else rows
        if l6_rows_seen is not None:
            l6_rows_seen.append(int(keep.sum()))
        on = keep[tab.band_snap]
        mu = (tab.snaps.v2_mean.to_numpy(float) + shift)[tab.band_snap][on]
        b = tab.bands[on]
        frame = pd.DataFrame({"row_key": b.row_key.to_numpy(), "band_index": b.band_index.to_numpy(int),
                              "p": _band_p_vec(b.kind.to_numpy(), b.low.to_numpy(float), b.high.to_numpy(float),
                                               mu, 2.5)})
        return tab.candidate_vector(frame)[0]

    def registered(tab):
        zero = np.zeros(len(tab.snaps))
        out = {}
        for arm in ("P3d_N_fix", "L6"):
            p = arm_probs(tab, arm, zero, None)
            out[arm] = (p, np.ones(len(tab.snaps), bool), {"candidate": len(tab.snaps)})
        return out

    folds_scored = lay.dates[14:]
    return prm.ro_score_core(make_table=lambda dates: sc.Table(lay, dates), fit_dates=lay.dates,
                             scored=folds_scored, registered=registered, arm_probs=arm_probs,
                             g_of=lambda tab: tab.snaps.G.to_numpy(float),
                             n_of=lambda tab, arm: tab.snaps.v2_mean.to_numpy(float),
                             hour_of=lambda tab: tab.local_hour, coef_fix=coef_fix,
                             mg1_probs=lambda tab: tab.p_market, mg1_expected=0.0, progress=lambda m: None), l3


def test_synthetic_end_to_end_informative_g_passes(monkeypatch):
    lay, dists = _fabricate(informative=True)
    seen = []
    result, _ = _run_core(lay, dists, {h: (0.0, 1.0) for h in prm.RUNG_HOURS}, seen)
    json.dumps(result)  # serialisable
    assert result["controls"]["P3d_N_fix_s0_max_abs_diff"] == 0.0 and result["controls"]["L6_s0_max_abs_diff"] == 0.0
    assert result["controls"]["mg1_excess_07_12"] == 0.0
    assert result["population"]["n_dates"] == 16 and result["population"]["common_covered_snapshots_07_12"] == 16 * 18
    # the L6 grid only evaluates the 07-12 fit rows (h13 excluded), once per pair
    assert seen.count(30 * 3 * 6) == len(prm.RO_PAIRS)
    g = result["gates"]
    assert g["2_P3d_N_fix_G"]["pass"] and g["2_L6_G"]["pass"]
    assert len(g["2_L6_G"]["hours_lower"]) == 6
    assert g["3_P3d_N_fix_G_vs_L6"]["reading"] == "WIN" and g["3_L6_G_vs_L6"]["reading"] == "WIN"
    assert result["kill"] == "none" and result["clarification_draft_required"]
    first = result["coefficients"]["L6_G"]["h07"][lay.dates[14]]
    assert first[1] > 0.5  # walk-forward learnt a positive weight on G - N from the 14 prior dates
    assert set(result["market_excess_reported_only"]) == {"P3d_N_fix_G", "L6_G"}
    assert set(result["market_excess_reported_only"]["L6_G"]) == {"07-12"} | {f"h{h:02d}" for h in prm.RUNG_HOURS}
    assert {r["arm"] for r in result["rows"]} == {"L6", "P3d_N_fix_G", "L6_G"}


def test_synthetic_end_to_end_noise_g_closes_fixed_arm():
    lay, dists = _fabricate(informative=False, seed=11)
    result, _ = _run_core(lay, dists, {h: (0.0, 1.0) for h in prm.RUNG_HOURS})
    assert not result["gates"]["2_P3d_N_fix_G"]["pass"]
    assert "3_P3d_N_fix_G_vs_L6" not in result["gates"]
    assert result["kill"].startswith("closed")


def test_core_refuses_a_non_reproducing_zero_shift():
    lay, dists = _fabricate(informative=True)
    from weather.reporting.scorecards import dev_scorecard as sc

    def registered(tab):
        n = len(tab.snaps)
        return {a: (np.full(len(tab.bands), 1.0 / len(BANDS)), np.ones(n, bool), {}) for a in ("P3d_N_fix", "L6")}

    def arm_probs(tab, arm, shift, rows):
        return np.full(len(tab.bands), 1.0 / len(BANDS)) + (1e-6 if arm == "L6" else 0.0)

    with pytest.raises(prm.PooledModelError, match="s = 0"):
        prm.ro_score_core(make_table=lambda dates: sc.Table(lay, dates), fit_dates=lay.dates, scored=lay.dates[14:],
                          registered=registered, arm_probs=arm_probs, g_of=lambda t: t.snaps.G.to_numpy(float),
                          n_of=lambda t, a: t.snaps.v2_mean.to_numpy(float), hour_of=lambda t: t.local_hour,
                          coef_fix={}, progress=lambda m: None)
