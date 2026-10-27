"""L3 challenger: mass-preserving floored bucket distributions, R0 parity joins and the pre-declared rule.

Guards: probability mass and the hard floor (AGENT_CONTEXT "Settlement and units"; lane B's
OLS + floor contract), identical-row comparison against R0 (lane rules "same rows as R0"),
fail-closed import on the capture host (master pre-authorisation 2026-10-24).
"""
import math
from pathlib import Path

import pytest

from weather.calibration import feature_model as fm

from tests.host_guard import import_or_skip_on_capture_host

ch = import_or_skip_on_capture_host("weather.calibration.r0_ols_floor_challenger")

ROOT = Path(__file__).resolve().parents[2]


def test_discretised_normal_preserves_mass_and_folds_tails():
    probs = ch.discretised_normal(50.0, 3.0, 40, 60)
    assert set(probs) == set(range(40, 61))
    assert math.isclose(sum(probs.values()), 1.0, abs_tol=1e-12)
    # The far tails land on the end buckets instead of leaving the grid.
    far = ch.discretised_normal(100.0, 2.0, 40, 60)
    assert far[60] > 0.999 and math.isclose(sum(far.values()), 1.0, abs_tol=1e-12)
    # Symmetric about the mean.
    assert math.isclose(probs[48], probs[52], rel_tol=1e-9)


def test_floor_removes_all_mass_below_and_keeps_the_floor_bucket():
    probs = ch.discretised_normal(50.0, 3.0, 40, 60, floor=52)
    assert all(probs[b] == 0.0 for b in range(40, 52))
    assert probs[52] > 0.0
    assert math.isclose(sum(probs.values()), 1.0, abs_tol=1e-12)
    # Truncated and renormalised: above the floor the ratios are unchanged.
    free = ch.discretised_normal(50.0, 3.0, 40, 60)
    assert math.isclose(probs[55] / probs[54], free[55] / free[54], rel_tol=1e-9)
    # The floor bucket holds [floor - 0.5, floor + 0.5) only, not the cut tail.
    assert probs[52] / probs[53] == pytest.approx(free[52] / free[53], rel=1e-9)


def test_floor_one_below_the_mean_and_far_above_it():
    at = ch.discretised_normal(50.0, 1.0, 40, 60, floor=50)
    assert at[49] == 0.0 and at[50] > at[51]
    above = ch.discretised_normal(10.0, 0.3, 40, 60, floor=58)
    assert above[58] == pytest.approx(1.0) and above[57] == 0.0


def test_sd_floor_applies():
    assert ch.discretised_normal(50.0, 0.0, 40, 60) == ch.discretised_normal(50.0, ch.SD_FLOOR, 40, 60)


def test_bucket_grid_extends_to_a_floor_outside_the_support():
    assert ch.bucket_grid([43, 45, 50]) == (43, 50)
    assert ch.bucket_grid([43, 45, 50], floor=52) == (43, 52)
    assert ch.bucket_grid([43, 45, 50], floor=40) == (40, 50)


def test_scores_match_the_trainer_metrics():
    probs = ch.discretised_normal(50.2, 2.5, 44, 56, floor=47)
    for actual in (47, 50, 56):
        assert ch.log_loss(probs, actual) == pytest.approx(fm.log_loss(probs, actual))
        assert ch.brier(probs, actual) == pytest.approx(fm.brier_score(probs, actual))
    assert ch.log_loss(probs, 45) == pytest.approx(-math.log(1e-15))


def _records(n_years=5, per_year=15):
    import numpy as np

    rng = np.random.default_rng(1)
    out = []
    for year in range(2021, 2021 + n_years):
        for day in range(per_year):
            fc = 60 + rng.normal(0, 6)
            hsf = fc - 8 + rng.normal(0, 1)
            final = round(0.8 * fc + 0.2 * hsf + 3 + rng.normal(0, 1.5))
            out.append({"target_date": f"{year}-11-{10 + day:02d}", "forecast_high": fc,
                        "high_so_far": hsf, "current_temp": hsf - 1, "final_bucket": int(max(final, round(hsf)))})
    return out


def test_fit_fold_recovers_the_linear_structure_and_floors():
    records = _records()
    fit = ch.fit_fold(records)
    assert fit["n_train"] == len(records) and fit["dropped_no_forecast"] == 0
    assert 0.5 < fit["beta"][1] < 1.1
    assert 0.8 < fit["ols_sd"] < 2.5
    val = dict(records[0], high_so_far=records[0]["final_bucket"] + 0.2)
    dists, detail = ch.challenger_distributions(fit, val, range(40, 90))
    floor = detail["floor"]
    for arm in ("ols_floor", "ols_floor_resid_hgb"):
        assert math.isclose(sum(dists[arm].values()), 1.0, abs_tol=1e-12)
        assert all(p == 0.0 for b, p in dists[arm].items() if b < floor)
    assert any(p > 0 for b, p in dists["bias_corrected_forecast"].items() if b < floor)


def test_missing_observations_fall_back_to_the_forecast_and_drop_the_floor():
    rec = {"forecast_high": 61.0, "high_so_far": None, "current_temp": float("nan"), "final_bucket": 60}
    assert ch.feature_vector(rec) == [61.0, 61.0, 61.0]
    assert ch.floor_of(rec) is None
    assert ch.floor_of({"high_so_far": 54.5}) == 55


def _row(hour, d, base, r0=None, ols=0.0):
    row = {"hour": hour, "validation_date": d, "r0_baseline_log_loss": base,
           "ols_floor_log_loss": ols}
    return row, {"hour": hour, "validation_date": d, "baseline_log_loss": base,
                 "hgb_log_loss": r0 if r0 is not None else base, "hgb_brier": 1.0}


def test_join_refuses_row_set_or_baseline_mismatch():
    a1, b1 = _row(7, "2021-11-17", 4.0)
    a2, b2 = _row(8, "2021-11-17", 3.0)
    joined, parity = ch.join_r0([a1, a2], [b1, b2])
    assert parity["max_baseline_abs_diff"] == 0.0 and joined[0]["r0_log_loss"] == 4.0
    assert parity["lane_d_floored"] is False and ch.LANE_D_FLOORED + "_log_loss" not in joined[0]
    with pytest.raises(ch.ChallengerError, match="row sets differ"):
        ch.join_r0([a1], [b1, b2])
    bad = dict(b2, baseline_log_loss=3.0 + 1e-6)
    with pytest.raises(ch.ChallengerError, match="baseline parity"):
        ch.join_r0([a1, a2], [b1, bad])
    ok = dict(b2, baseline_log_loss=3.0 + 1e-10)
    assert ch.join_r0([a1, a2], [b1, ok])[1]["max_baseline_abs_diff"] < ch.PARITY_TOLERANCE


def test_join_attaches_lane_d_floored_rows_and_checks_the_repro():
    a, b = _row(7, "2021-11-17", 4.0, r0=3.5)
    a.update(r0_repro_log_loss=3.5, r0_floor_log_loss=2.0, r0_floor_served_log_loss=2.1)
    b.update(hgb_floored_log_loss=2.1, hgb_floored_brier=0.7)
    joined, parity = ch.join_r0([a], [b])
    assert joined[0][ch.LANE_D_FLOORED + "_log_loss"] == 2.1
    assert parity["r0_repro_ok"] is True and parity["lane_d_floored"] is True
    assert parity["max_floored_vs_served_floor_abs_diff"] == 0.0
    assert parity["max_floored_vs_zero_floor_abs_diff"] == pytest.approx(0.1)
    a["r0_repro_log_loss"] = 3.6
    assert ch.join_r0([a], [b])[1]["r0_repro_ok"] is False


def test_apply_hard_floor_zero_and_served_multiplier():
    probs = {48: 0.2, 50: 0.3, 51: 0.5}
    zero = ch.apply_hard_floor(probs, 50)
    assert zero[48] == 0.0 and zero[50] == pytest.approx(0.375) and sum(zero.values()) == pytest.approx(1.0)
    served = ch.apply_hard_floor(probs, 50, ch.SERVED_FLOOR_MULTIPLIER)
    assert 0 < served[48] < 1e-6 and sum(served.values()) == pytest.approx(1.0)
    assert ch.apply_hard_floor(probs, 49) == pytest.approx({48: 0.0, 50: 0.375, 51: 0.625})
    assert ch.apply_hard_floor(probs, None) == probs
    # All mass below the floor: it moves to the floor bucket, even one outside the keys.
    moved = ch.apply_hard_floor(probs, 53)
    assert moved[53] == 1.0 and sum(moved.values()) == 1.0
    assert ch.observed_floor_bucket(52.5) == 53 and ch.observed_floor_bucket(None) is None


def _market_rows(delta_by_date, hours=(7, 8)):
    rows = []
    for d, delta in delta_by_date.items():
        for h in hours:
            rows.append({"hour": h, "validation_date": d, "a_log_loss": 1.0 + delta, "ref_log_loss": 1.0})
    return rows


def test_bootstrap_pooled_is_the_equal_weight_market_mean_and_deterministic():
    dates = [f"2021-11-{i:02d}" for i in range(1, 31)]
    by_market = {
        "m1": _market_rows({d: -0.5 + 0.01 * i for i, d in enumerate(dates)}),
        "m2": _market_rows({d: -0.1 for d in dates[:10]}),
    }
    out = ch.bootstrap_delta(by_market, "a", "ref", "log_loss", (7, 8))
    m1 = sum(-0.5 + 0.01 * i for i in range(30)) / 30
    assert out["per_market"]["m1"]["delta"] == pytest.approx(m1)
    assert out["per_market"]["m2"]["delta"] == pytest.approx(-0.1)
    assert out["pooled"]["delta"] == pytest.approx((m1 - 0.1) / 2)
    assert out == ch.bootstrap_delta(by_market, "a", "ref", "log_loss", (7, 8))
    lo, hi = out["per_market"]["m1"]["ci95"]
    assert lo < m1 < hi
    # Hours outside the window do not count.
    assert ch.bootstrap_delta(by_market, "a", "ref", "log_loss", (9,)) is None


def test_verdict_needs_a_pooled_ci_below_zero_and_no_market_worse():
    good = {"pooled": {"delta": -0.2, "ci95": [-0.3, -0.1]},
            "per_market": {"a": {"ci95": [-0.4, -0.1]}, "b": {"ci95": [-0.1, 0.05]}}}
    assert ch.verdict(good)
    crosses = {"pooled": {"delta": -0.2, "ci95": [-0.3, 0.01]}, "per_market": good["per_market"]}
    assert not ch.verdict(crosses)
    worse = {"pooled": good["pooled"],
             "per_market": {"a": {"ci95": [-0.4, -0.1]}, "b": {"ci95": [0.001, 0.2]}}}
    assert not ch.verdict(worse)
    edge = {"pooled": good["pooled"], "per_market": {"b": {"ci95": [0.0, 0.2]}}}
    assert ch.verdict(edge)


def test_compare_is_provisional_until_every_required_market_has_rows():
    dates = [f"2021-11-{i:02d}" for i in range(1, 21)]
    rows = []
    for d in dates:
        for h in (7, 12):
            row = {"hour": h, "validation_date": d, "r0_log_loss": 4.0, "r0_brier": 1.0}
            for arm in ("ols_floor", "ols_floor_resid_hgb", "bias_corrected_forecast", "r0_baseline"):
                row[f"{arm}_log_loss"] = 2.0 if arm.startswith("ols") else 3.0
                row[f"{arm}_brier"] = 0.9
            rows.append(row)
    partial = ch.compare({"atlanta": rows}, reference="r0", markets=ch.PRIMARY_MARKETS,
                         required_markets=ch.PRIMARY_MARKETS)
    assert partial["verdict"].startswith("PROVISIONAL")
    assert partial["headline"]["ols_floor"]["passes_two_criteria"] is None
    full = ch.compare({m: rows for m in ch.PRIMARY_MARKETS}, reference="r0",
                      markets=ch.PRIMARY_MARKETS, required_markets=ch.PRIMARY_MARKETS)
    # Both challengers tie on every row; the rule then picks the simpler arm.
    assert full["verdict"] == "ols_floor passes against r0"
    assert ch.compare({}, reference="r0", markets=ch.PRIMARY_MARKETS,
                      required_markets=ch.PRIMARY_MARKETS) is None


def test_import_refuses_on_the_capture_host_or_without_identity():
    ch.refuse_production_import(os_name="posix")
    ch.refuse_production_import(os_name="nt", identity=lambda: ("work", "capture"))
    with pytest.raises(ImportError, match="capture host"):
        ch.refuse_production_import(os_name="nt", identity=lambda: ("capture", "capture"))
    with pytest.raises(ImportError, match="capture host"):
        ch.refuse_production_import(os_name="nt", identity=lambda: ("", "capture"))

    def unreadable():
        raise OSError("registry unreadable")

    with pytest.raises(ImportError, match="not provable"):
        ch.refuse_production_import(os_name="nt", identity=unreadable)


def test_no_production_code_imports_the_challenger():
    hits = []
    for top in ("src", "app", "scripts"):
        for path in (ROOT / top).rglob("*"):
            if path.suffix not in {".py", ".ps1"} or path.name == "r0_ols_floor_challenger.py":
                continue
            if "r0_ols_floor_challenger" in path.read_text(encoding="utf-8", errors="replace"):
                hits.append(path.relative_to(ROOT).as_posix())
    # Every allowed importer, with its reason; any other module that names the challenger fails this test.
    ws_only = ("WS-only scorer, scores host-exported bundles; cannot import on the capture host by design "
               "(master ruling 2026-10-26)")
    expected = {
        "scripts/ops/workload_admission.ps1": "the workstation allowlist names the module (it admits it)",
        "src/weather/calibration/b_scorer.py": ws_only,
        "src/weather/calibration/mg2_composite.py": ws_only,
        "src/weather/calibration/mg2_p3d_n.py": ws_only,
        "src/weather/calibration/ols_floor_ladder.py": "lane L9's ladder, research-only, same capture-host guard",
        "src/weather/calibration/pooled_residual_model.py": "lane L2, lazily, only in its research dev emitters",
        "src/weather/calibration/r0_ols_floor_devfit.py": "its own dev-fit companion, research-only",
        # L3's rz scorer reuses the challenger's date-cluster bootstrap weights lazily inside _cell_ratio;
        # research-only, never imported by serving code.
        "src/weather/calibration/rz_hrrr_spread.py": "L3's offline rz scorer, lazily, for _date_weights only",
    }
    assert sorted(hits) == sorted(expected)


def _metar(nominal, raw_time, temp):
    return {"datetime": nominal, "raw": f"METAR KATL {raw_time} 27006KT 10SM 32/23 A3020", "temp_native": temp}


def test_metar_rows_key_on_the_raw_observation_time_not_the_nominal_hour():
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    instant, basis = ch.metar_observation_instant(_metar("2026-08-10T13:00:00-04:00", "101652Z", 89.0), tz)
    assert basis == "raw_ddhhmmz" and instant == datetime(2026, 8, 10, 12, 52, tzinfo=tz)
    # Month-boundary DD group: a 31st 23:52Z report filed as the 1st's 00:00Z nominal hour.
    instant, _ = ch.metar_observation_instant(_metar("2026-08-01T00:00:00+00:00", "312352Z", 80.0), tz)
    assert instant.astimezone(ZoneInfo("UTC")) == datetime(2026, 7, 31, 23, 52, tzinfo=ZoneInfo("UTC"))
    assert ch.metar_observation_instant({"datetime": "2026-08-10T13:00:00-04:00", "raw": ""}, tz)[1] == "nominal_datetime"

    rows = [
        _metar("2026-08-10T00:00:00-04:00", "100352Z", 82.0),  # D-1 23:52 local, carried as 00:00: excluded
        _metar("2026-08-10T01:00:00-04:00", "100452Z", 80.0),
        _metar("2026-08-10T10:00:00-04:00", "101352Z", 84.0),
        _metar("2026-08-10T11:00:00-04:00", "101452Z", 86.0),  # observed 10:52, after a 10:00 cutoff
    ]
    current, high, n = ch.observations_at_cutoff(rows, date(2026, 8, 10), 10, tz)
    assert (current, high, n) == (84.0, 84.0, 2)
    assert ch.observations_at_cutoff(rows, date(2026, 8, 10), 11, tz)[:2] == (86.0, 86.0)
    assert ch.observations_at_cutoff(rows[:1], date(2026, 8, 10), 10, tz) == (None, None, 0)


def test_dev_verdict_needs_07_12_below_zero_and_no_standard_block_worse():
    def row(group, lo, hi, est=-0.1):
        return {"market": "ALL", "group": group,
                "dR_crossed": {"estimate": est, "ci95": [lo, hi]},
                "dR_date_clustered": {"estimate": est, "ci95": [lo, hi]}}

    good = [row("07-12", -0.2, -0.05)] + [row(g, -0.1, 0.05) for g in ch.DEV_STANDARD_BLOCKS]
    bad_block = [row("07-12", -0.2, -0.05)] + [row(g, -0.1, 0.05) for g in ch.DEV_STANDARD_BLOCKS[:-1]] + [
        row("all", 0.01, 0.2, 0.1)]
    crossing = [row("07-12", -0.2, 0.01)] + [row(g, -0.1, 0.05) for g in ch.DEV_STANDARD_BLOCKS]
    scores = {"candidates": {"ols_floor": {"rows": good}, "ols_floor_resid_hgb": {"rows": bad_block},
                             "x": {"rows": crossing}}}
    out = ch.dev_verdict(scores, arms=("ols_floor", "ols_floor_resid_hgb", "x"))
    assert out["ols_floor"]["dR_crossed"]["beats_served"] is True
    assert out["ols_floor_resid_hgb"]["dR_crossed"]["blocks_worse"] == ["all"]
    assert out["ols_floor_resid_hgb"]["dR_crossed"]["beats_served"] is False
    assert out["x"]["dR_date_clustered"]["beats_served"] is False


def test_dev_verdict_reads_only_served_blended_rows():
    def row(group, lo, hi, reference="served", scope="blended"):
        return {"market": "ALL", "group": group, "reference": reference, "scope": scope,
                "dR_crossed": {"estimate": -0.1, "ci95": [lo, hi]},
                "dR_date_clustered": {"estimate": -0.1, "ci95": [lo, hi]}}

    rows = [row("07-12", -0.2, -0.05)] + [row(g, -0.1, 0.05) for g in ch.DEV_STANDARD_BLOCKS]
    rows += [row("07-12", 0.1, 0.2, "mg1"), row("all", 0.1, 0.2, "served", "covered")]
    out = ch.dev_verdict({"candidates": {"ols_floor": {"rows": rows}}}, arms=("ols_floor",))
    assert out["ols_floor"]["dR_date_clustered"]["beats_served"] is True


def test_dev_mg1_gate_fails_on_any_ci_worse_block_and_needs_the_control():
    def row(group, lo, hi, kind_lo=None):
        crossed = [lo, hi] if kind_lo is None else [kind_lo, hi]
        return {"market": "ALL", "group": group, "reference": "mg1", "scope": "blended",
                "dR_crossed": {"estimate": 0.0, "ci95": crossed},
                "dR_date_clustered": {"estimate": 0.0, "ci95": [lo, hi]}}

    ok = [row(g, -0.1, 0.1) for g in ch.DEV_MG1_GATE_BLOCKS]
    worse = ok[:-1] + [row("all", -0.1, 0.3, kind_lo=0.01)]
    scores = {"mg1_control": {"passed": True},
              "candidates": {"a": {"rows": ok}, "b": {"rows": worse}}}
    assert ch.dev_mg1_gate(scores, "a")["no_worse_than_mg1"] is True
    out = ch.dev_mg1_gate(scores, "b")
    assert out["no_worse_than_mg1"] is False and out["ci_worse"] == ["all:dR_crossed"]
    scores["mg1_control"]["passed"] = False
    assert ch.dev_mg1_gate(scores, "a")["no_worse_than_mg1"] is None


def test_dev_variants_default_excludes_the_l8_variant_and_it_keeps_the_main_features():
    assert ch.L8_VARIANT not in ch.DEV_DEFAULT_VARIANTS
    assert ch.DEV_VARIANTS[ch.L8_VARIANT] == ch.DEV_VARIANTS["main"]


def test_dev_pick_refuses_unpinned_rule_and_missing_parity(tmp_path):
    rule = tmp_path / "rule.md"
    rule.write_text("not the pinned rule\n", encoding="utf-8")
    with pytest.raises(ch.ChallengerError, match="pick rule sha"):
        ch.dev_pick("layout", "a.jsonl", {"a_prime": "b.jsonl"}, {"a_prime": True}, rule)


def test_nbm_hist_variant_adds_the_nbm_mean_regressor():
    features, source = ch.DEV_VARIANTS[ch.NBM_VARIANT]
    assert features == ch.FEATURES + ("nbm_mean",) and source == "pit_2026"
    # A missing NBM mean is imputed with forecast_high, as in training (L9's IMPUTE rule).
    assert ch.feature_vector({"forecast_high": 80.0, "high_so_far": 75.0, "current_temp": 74.0,
                              "nbm_mean": None}, features) == [80.0, 75.0, 74.0, 80.0]


def test_nbm_n2_variant_replaces_the_forecast_with_the_captured_nbm_mean():
    features, source = ch.DEV_VARIANTS[ch.N2_VARIANT]
    assert features == ("nbm_mean", "high_so_far", "current_temp") and source == "captured_nbm"
    assert ch.N2_VARIANT in ch.NBM_VARIANTS


def test_parse_captured_metar_matches_the_iem_fields():
    from datetime import datetime, timezone

    anchor = datetime(2026, 8, 10, 17, 10, tzinfo=timezone.utc)
    row = ch.parse_captured_metar("METAR KATL 101652Z 27006KT 10SM SCT045 BKN250 32/23 A3001 RMK AO2 T03170228", anchor)
    assert row["valid"] == datetime(2026, 8, 10, 16, 52, tzinfo=timezone.utc)
    assert math.isclose(row["temp"], 31.7 * 9 / 5 + 32) and math.isclose(row["dwpf"], 22.8 * 9 / 5 + 32)
    assert row["drct"] == 270.0 and row["sknt"] == 6.0 and row["cover"] == 0.75 and row["ceiling_ft"] == 25000.0
    assert not row["is_cor"]


def test_routine_dmax_needs_twenty_modal_minute_rows():
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    start = datetime(2026, 8, 9, 4, 52, tzinfo=timezone.utc)
    rows = [{"valid": start + timedelta(hours=i), "temp": 70.0 + i, "is_cor": False} for i in range(20)]
    assert ch.routine_dmax(rows, tz, "2026-08-09") == 89.0
    assert ch.routine_dmax(rows[:19], tz, "2026-08-09") is None
