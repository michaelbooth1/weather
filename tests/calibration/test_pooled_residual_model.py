"""Lane L2 pooled residual research model: fold hygiene, floor, scoring and the decision rule.

Guards: L2 pre-declared rule (C:/t/l2/rule.md) - in-fold bias and normals, the hard observed floor,
probability mass, R0-identical row keys, date-clustered bootstrap, fail-closed import off the capture
host and no output inside the repository.
"""
import json
import math

import numpy as np
import pandas as pd
import pytest

from tests.host_guard import import_or_skip_on_capture_host

prm = import_or_skip_on_capture_host("weather.calibration.pooled_residual_model")


def _frame(n_days=12, years=(2021, 2022, 2023, 2024), markets=("atlanta", "nyc"), hour=10, seed=0):
    rng = np.random.default_rng(seed)
    rows = []
    for market in markets:
        offset = 10.0 if market == "nyc" else 0.0
        for year in years:
            for d in range(n_days):
                fh = 60.0 + offset + rng.normal(0, 4)
                y = round(fh + 2.0 + rng.normal(0, 1.5))
                F = y - abs(round(rng.normal(0, 2)))
                rows.append({
                    "market": market, "centre": prm.VALIDATION_CENTRE, "season": "oct_dec", "hour": hour,
                    "target_date": f"{year}-11-{17 + d % 14:02d}", "year": year, "y": float(y), "F": float(F),
                    "fh": fh, "lat": 33.6, "lon": -84.4, "elev": 300.0, "doy_sin": 0.0, "doy_cos": 1.0,
                    "x_high_so_far": float(F), "x_current_temp": float(F) - 1.0,
                    "market_code": float(prm.R0_MARKETS.index(market)),
                })
    return pd.DataFrame(rows)


def test_import_fails_closed_on_the_capture_host(monkeypatch):
    import weather.execution_host as host

    capture = json.loads(host.DEFAULT_EXECUTION_HOST_ASSIGNMENT_PATH.read_text(encoding="utf-8"))[
        "dedicated_capture_execution_host_id"]
    monkeypatch.setattr(host, "current_execution_host_id", lambda: capture)
    with pytest.raises(prm.ProductionImportRefused, match="capture host"):
        prm._refuse_production_import()
    monkeypatch.setattr(host, "current_execution_host_id", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(prm.ProductionImportRefused, match="not provably"):
        prm._refuse_production_import()
    monkeypatch.setattr(host, "current_execution_host_id", lambda: "0" * 64)
    prm._refuse_production_import()


def test_output_inside_the_repository_is_refused(tmp_path):
    with pytest.raises(prm.PooledModelError):
        prm.require_output_outside_repo(prm.REPO_ROOT / "data" / "x")
    assert prm.require_output_outside_repo(tmp_path / "out") == (tmp_path / "out").resolve()


def test_distribution_is_normalised_and_censored_at_the_floor():
    z = np.array([-1.5, -0.5, 0.0, 0.4, 1.2])
    clim = {k: 1.0 / 41 for k in range(40, 81)}
    dist = prm.predictive_distribution(61.0, 3.0, 62.0, z, list(clim), clim)
    assert math.isclose(sum(dist.values()), 1.0, rel_tol=1e-12)
    below = sum(v for k, v in dist.items() if k < 62)
    assert 0 < below <= prm.FLOOR_MIX_CLIM + 1e-12
    # Mass under the floor is moved onto the floor bucket, not spread upward.
    unfloored = prm.predictive_distribution(61.0, 3.0, float("nan"), z, list(clim), clim)
    assert dist[62] > unfloored[62] + 0.2
    assert dist[66] == pytest.approx(unfloored[66], rel=1e-9)


def test_fold_fits_never_see_the_held_out_year():
    frame = _frame()
    train = frame[frame["year"] != 2024].reset_index(drop=True)
    model = prm.MeanModel(market_id=False, doy=False).fit(train)
    expected = (train["y"] - train["fh"])[train["market"] == "nyc"].mean()
    assert model.bias[("nyc", "oct_dec")] == pytest.approx(expected)
    poisoned = frame.copy()
    poisoned.loc[poisoned["year"] == 2024, "y"] += 50.0
    again = prm.MeanModel(market_id=False, doy=False).fit(
        poisoned[poisoned["year"] != 2024].reset_index(drop=True))
    assert again.bias == model.bias and again.normal == model.normal


def test_pooled_arm_scores_every_validation_row_once_with_proper_losses():
    frame = _frame()
    payloads = [{"market": m, "bucket_space": list(range(40, 100))} for m in ("atlanta", "nyc")]
    rows = prm.score_pooled_arm("P0", frame, payloads)
    keys = {(r["market"], r["hour"], r["validation_date"], r["validation_year"]) for r in rows}
    assert len(rows) == len(frame) == len(keys)
    assert all(math.isfinite(r["P0_log_loss"]) and r["P0_log_loss"] >= 0 for r in rows)
    # The mean tracks the bias-corrected forecast (truth: fh + 2 with a floor).
    truth = {(m, d): y for m, d, y in zip(frame["market"], frame["target_date"], frame["y"])}
    err = np.mean([abs(r["P0_mean"] - truth[(r["market"], r["validation_date"])]) for r in rows])
    assert err < 3.0


def _rows(delta_by_market, n_dates=30, hours=(7, 8, 13)):
    rng = np.random.default_rng(1)
    out = []
    for market, delta in delta_by_market.items():
        for d in range(n_dates):
            for hour in hours:
                base = 3.0 + rng.normal(0, 0.3)
                out.append({"market": market, "hour": hour, "validation_date": f"2022-11-{d % 28 + 1:02d}-{d}",
                            "R0_log_loss": base, "P0_log_loss": base + delta + rng.normal(0, 0.05),
                            "R0_brier": 0.9, "P0_brier": 0.8})
    return out


def test_decision_passes_a_uniform_gain_and_fails_a_market_worse_beyond_its_ci():
    verdicts, pick = prm.decide(_rows({"atlanta": -0.4, "nyc": -0.3, "miami": -0.5}), ["P0"])
    assert pick == "P0" and verdicts["P0"]["passes"]
    verdicts, pick = prm.decide(_rows({"atlanta": -0.8, "nyc": -0.8, "miami": +0.2}), ["P0"])
    assert verdicts["P0"]["fleet_delta"] < 0 and verdicts["P0"]["markets_worse"] == ["miami"]
    assert pick is None and not verdicts["P0"]["passes"]


def test_hour_13_never_enters_the_window_metric():
    rows = _rows({"atlanta": -0.4})
    for r in rows:
        if r["hour"] == 13:
            r["P0_log_loss"] += 100.0
    boot = prm.bootstrap_deltas(rows, "P0")
    assert boot["fleet"] == pytest.approx(-0.4, abs=0.05)


def test_merge_refuses_rows_that_differ_from_r0():
    r0 = [{"market": "a", "hour": 7, "validation_date": "2022-11-20", "R0_log_loss": 1.0}]
    with pytest.raises(prm.PooledModelError):
        prm.merge_rows(r0, {"P0": []})
    merged = prm.merge_rows(r0, {"P0": [dict(r0[0], P0_log_loss=0.5, R0_log_loss=9.0)]})
    assert merged[0]["R0_log_loss"] == 1.0 and merged[0]["P0_log_loss"] == 0.5


def test_r0_parity_reports_key_mismatch_and_max_difference(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({"hour": 7, "validation_date": "2022-11-20", "hgb_log_loss": 2.0}) + "\n")
    ours = [{"hour": 7, "validation_date": "2022-11-20", "R0_log_loss": 2.0 + 1e-12}]
    assert prm.r0_parity(ours, path) == {"keys_match": True, "rows": 1, "max_abs_diff": pytest.approx(1e-12)}
    assert prm.r0_parity(ours + [dict(ours[0], hour=8)], path)["keys_match"] is False


def test_station_coordinates_cover_the_us_11():
    coords = prm.station_coordinates()
    assert set(coords) == set(prm.R0_MARKETS)
    assert all(-130 < lon < -60 and 20 < lat < 50 for lat, lon, _ in coords.values())


def test_a_fail_closed_corpus_gap_skips_the_pair_and_drops_the_centre(tmp_path, monkeypatch):
    from weather.sources.forecast_training_corpus import CorpusVerificationError

    def fake(market, centre, manifests, out_root, training_years=None):
        if market == "nyc" and centre == "2026-12-24":
            raise CorpusVerificationError("no cutoff-valid PIT daily forecast")
        path = prm.records_path(out_root, market, centre)
        path.write_bytes(b"x")
        return path, {"days_by_year": {}, "union_sha256": "u"}

    monkeypatch.setattr(prm, "extract_market", fake)
    failed = prm.extract_many(["atlanta", "nyc"], ["2026-11-24", "2026-12-24"], [], tmp_path)
    assert [(m, c) for m, c, _ in failed] == [("nyc", "2026-12-24")]
    kept, dropped = prm.complete_centres(tmp_path, ["atlanta", "nyc"], ["2026-11-24", "2026-12-24"])
    assert (kept, dropped) == (["2026-11-24"], ["2026-12-24"])


def test_u0_fits_each_market_alone():
    frame = _frame()
    payloads = [{"market": m, "bucket_space": list(range(40, 100))} for m in ("atlanta", "nyc")]
    rows = prm.score_pooled_arm("U0", frame, payloads)
    assert len(rows) == len(frame)
    # Poisoning one market's training labels cannot move the other market's U0 predictions.
    poisoned = frame.copy()
    poisoned.loc[(poisoned["market"] == "nyc") & (poisoned["year"] != 2021), "y"] += 30.0
    again = prm.score_pooled_arm("U0", poisoned, payloads)
    def atl(rs, arm="U0"):
        return sorted((r["validation_date"], r[f"{arm}_mean"]) for r in rs if r["market"] == "atlanta")

    assert atl(rows) == atl(again)
    # The pooled arm does move: the control has teeth.
    assert atl(prm.score_pooled_arm("P0", poisoned, payloads), "P0") != atl(prm.score_pooled_arm("P0", frame, payloads), "P0")


def test_l3_row_gate_needs_identical_keys_and_r0_reproduction():
    r0 = [{"market": "a", "hour": 7, "validation_date": "2022-11-20", "R0_log_loss": 4.0}]
    l3 = [{"market": "a", "hour": 7, "validation_date": "2022-11-20", "l3r0_log_loss": 4.0}]
    assert prm.l3_parity(r0, l3)["ok"]
    assert not prm.l3_parity(r0, [dict(l3[0], l3r0_log_loss=4.1)])["ok"]
    assert not prm.l3_parity(r0, [dict(l3[0], hour=8)])["ok"]


def test_headline_verdict_words():
    rows = _rows({"atlanta": -0.4, "nyc": -0.3})
    for r in rows:
        r["a_log_loss"] = r.pop("R0_log_loss")
        r["P3_log_loss"] = r.pop("P0_log_loss")
    assert prm.headline_verdict(rows, "P3", "a")["verdict"] == "P3 beats a"
    for r in rows:
        r["P3_log_loss"] = r["a_log_loss"] + 0.5
    assert prm.headline_verdict(rows, "P3", "a")["verdict"] == "P3 is worse than a"


def test_dev_fits_use_only_parity_inputs_and_split_per_market_for_u0():
    frame = _frame(years=(2021, 2022, 2023, 2024, 2025))
    frame["centre"] = "2026-09-07"
    frame["season"] = "aug_sep"
    fits = prm.dev_fits(frame, "P3d")
    assert set(fits) == {(10, None)}
    assert fits[(10, None)]["fit"]["mean"].x_columns == []
    u0 = prm.dev_fits(frame, "U0d")
    assert set(u0) == {(10, "atlanta"), (10, "nyc")}
    assert set(u0[(10, "nyc")]["train_y"]) == {"nyc"}


def test_nearest_centre_by_month_day():
    assert prm.nearest_centre("2026-07-31") == "2026-08-08"
    assert prm.nearest_centre("2026-08-30") == "2026-08-23"
    assert prm.nearest_centre("2026-09-29") == "2026-09-22"


def test_season_blocks_and_centre_bias():
    assert [prm.season_of(c) for c in ("2026-01-08", "2026-07-22", "2026-08-08", "2026-12-09")] == [
        "jan_jul", "jan_jul", "aug_sep", "oct_dec"]
    frame = _frame()
    frame.loc[frame["year"] == 2022, "centre"] = "2026-01-08"
    model = prm.MeanModel(market_id=False, doy=True, bias_by="centre").fit(frame)
    assert ("atlanta", "2026-01-08") in model.bias and ("atlanta", prm.VALIDATION_CENTRE) in model.bias


def test_covered_years_excludes_a_year_with_one_missing_cell(tmp_path):
    rows = []
    for year in (2022, 2024):
        for d in prm.window_days("2026-01-08", year):
            for h in range(7, 21):
                if year == 2024 and d.day == 3 and h == 9:
                    continue
                rows.append({"market_id": "atlanta", "target_date": d.isoformat(), "cutoff_hour_local": h,
                             "status": "complete"})
    (tmp_path / "coverage.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "manifest.json").write_text(json.dumps({"years": [2022, 2024]}))
    assert prm.covered_years("2026-01-08", [tmp_path / "manifest.json"], markets=("atlanta",)) == [2022]


@pytest.mark.parametrize("head", ["P3", "P3F"])
def test_headline_markdown_renders_for_both_heads(tmp_path, head):
    rows = _rows({"atlanta": -0.4, "nyc": -0.3}, hours=(7, 12, 15))
    for r in rows:
        for k in ("R0", "P3", "P3F", "U0", "a", "e", "f", "r0floor"):
            r[f"{k}_log_loss"] = r["P0_log_loss"] + (0.1 if k in ("a", "f") else 0.0)
            r[f"{k}_brier"] = 0.8
    rule = tmp_path / "rule.md"
    rule.write_text("x")
    text = prm.headline_markdown(rows, rule, {"ok": True}, head=head)
    assert f"| {head} - a |" in text and "**(12)**" in text and f"{head} beats a" in text


def test_dev_verdict_markdown_applies_l3_rule(tmp_path):
    def ri(est, lo, hi):
        return {"estimate": est, "ci95": [lo, hi]}

    def row(market, group, est, lo, hi):
        return {"market": market, "group": group, "n_market_days": 10, "R_candidate": ri(1.2, 1.1, 1.3),
                "R_served": ri(1.4, 1.3, 1.5), "dR_crossed": ri(est, lo, hi), "dR_date_clustered": ri(est, lo, hi)}

    groups = ["00-05", "06-09", "10-12", "13-16", "17-23", "00-16", "all", "07-12", "h12"]
    good = [row("ALL", g, -0.1, -0.2, -0.05) for g in groups] + [row("atlanta", "07-12", -0.1, -0.3, 0.1)]
    bad = [row("ALL", g, -0.1, -0.2, -0.05) for g in groups if g != "13-16"] + [row("ALL", "13-16", 0.2, 0.1, 0.3)]
    scores = {"population": {}, "candidates": {"P3d": {"rows": good}, "U0d": {"rows": bad}}}
    rule = tmp_path / "rule.md"
    rule.write_text("x")
    text, verdict = prm.dev_verdict_markdown(scores, rule)
    assert verdict["P3d"]["dR_date_clustered"]["beats_served"] is True
    assert verdict["U0d"]["dR_date_clustered"]["blocks_worse"] == ["13-16"]
    assert "**(12)**" in text and "| atlanta |" in text


def test_attach_training_nbm_replaces_anchor_and_imputes_forecast():
    frame = _frame(n_days=2, years=(2021,), markets=("atlanta",))
    calls = []

    def fake_at_cutoff(table, market, day, hour, tz):
        calls.append((market, day, hour, tz))
        return (None, None) if day.endswith("-17") else (70.5, "07")

    out, stats = prm.attach_training_nbm(frame, {}, fake_at_cutoff, {"atlanta": "America/New_York"})
    imputed = out["target_date"].str.endswith("-17").to_numpy()
    assert np.allclose(out.loc[~imputed, "fh"], 70.5)
    assert np.allclose(out.loc[imputed, "fh"], frame.loc[imputed, "fh"])  # L9 IMPUTE "fc"
    assert stats == {"train_nbm_imputed_forecast": int(imputed.sum()), "train_nbm_cycle_07": int((~imputed).sum())}
    assert np.allclose(frame["fh"], _frame(n_days=2, years=(2021,), markets=("atlanta",))["fh"])  # input untouched
    assert calls[0] == ("atlanta", frame.at[0, "target_date"], 10, "America/New_York")


def test_running_max_without_metar_only_switch_is_refused():
    def old(station, metar, *, target_date, tz, unit, cutoff_hour, now=None):
        return None, None

    def new(station, metar, *, target_date, tz, unit, cutoff_hour, now=None, metar_only=False):
        return None, None

    with pytest.raises(prm.PooledModelError):
        prm._require_metar_only(old)
    assert prm._require_metar_only(new) is new


def test_scan_replay_n_uses_last_snapshot_of_the_hour_and_metar_only(tmp_path):
    from datetime import date as _date
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    lines = [
        {"captured_at_local": "2026-08-20T13:05:00-04:00", "snapshot_id": "a", "sources": {"metar": {"data": {"rows": [1]}}}},
        {"captured_at_local": "2026-08-20T13:55:00-04:00", "snapshot_id": "b", "sources": {"metar": {"data": {"rows": [2]}}}},
        {"captured_at_local": "2026-08-20T14:10:00-04:00", "snapshot_id": "c", "sources": {"metar": {"data": {"rows": [3]}}}},
        {"captured_at_local": "2026-08-21T13:10:00-04:00", "snapshot_id": "d", "sources": {"metar": {"data": {"rows": [4]}}}},
    ]
    (tmp_path / "replay_inputs.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    seen = []

    def running_max(station, metar, *, target_date, tz, unit, cutoff_hour, now=None, metar_only=False):
        seen.append((station, metar["rows"][0], cutoff_hour, now.minute, metar_only, unit))
        return 90.0 + metar["rows"][0], 600

    def obs_at_cutoff(rows, target_date, hour, tz):
        return 80.0 + rows[0], 88.0 + rows[0], 1

    out = prm.scan_replay_n(tmp_path, "nyc", _date(2026, 8, 20), tz, {13, 14}, "F", running_max, obs_at_cutoff)
    assert out[13]["replay_snapshot_id"] == "b" and out[14]["replay_snapshot_id"] == "c"
    assert out[13]["high_so_far"] == 92.0 and out[13]["current_temp"] == 82.0 and out[13]["main_high_so_far"] == 90.0
    assert all(s[0] == {} and s[4] is True and s[5] == "F" for s in seen)
    assert (2, 13, 55) in [(s[1], s[2], s[3]) for s in seen]


@pytest.mark.parametrize("tenths_c, expected", [
    (133, {"half_up": 56, "half_even": 56, "half_down": 56, "floor": 55, "ceil": 56}),   # 55.94 F
    (25, {"half_up": 37, "half_even": 36, "half_down": 36, "floor": 36, "ceil": 37}),    # 36.5 F exactly
    (75, {"half_up": 46, "half_even": 46, "half_down": 45, "floor": 45, "ceil": 46}),    # 45.5 F exactly
    (-25, {"half_up": 28, "half_even": 28, "half_down": 27, "floor": 27, "ceil": 28}),   # 27.5 F exactly
])
def test_wu_rounding_candidates_on_exact_tgroup_values(tenths_c, expected):
    value_f = 32 + tenths_c * 9 / 50  # the float the capture stores
    exact = prm.exact_tgroup_f(value_f)
    assert exact * 50 == 1600 + 9 * tenths_c
    for rule, want in expected.items():
        assert prm.round_candidate(exact, rule) == want
    assert prm.wu_whole_f(value_f, "half_up") == float(expected["half_up"])
    assert prm.wu_whole_f(None) is None and prm.wu_whole_f(float("nan")) is None


def test_frozen_state_features_reproduce_mean_model():
    frame = _frame(n_days=10, years=(2021, 2022, 2023), markets=("atlanta", "nyc"), hour=13)
    frame["season"] = "aug_sep"
    frame["centre"] = "2026-08-23"
    doy = pd.to_datetime(frame["target_date"]).dt.dayofyear
    frame["doy_sin"] = np.sin(2 * math.pi * doy / 365.25)
    frame["doy_cos"] = np.cos(2 * math.pi * doy / 365.25)
    frame = frame.drop(columns=[c for c in frame.columns if c.startswith("x_") and c not in prm.DEV_KEEP_X])
    fitted = prm.fit_pooled(frame, market_id=False, doy=True, raw_columns=False, bias_by="season")
    state = {
        "centres": ["2026-08-23"], "season_of": {f"{m:02d}": prm.season_of(f"2026-{m:02d}-01") for m in range(1, 13)},
        "coords": {"atlanta": [33.6, -84.4, 300.0], "nyc": [33.6, -84.4, 300.0]},
        "constants": {"levels": ["high_so_far", "current_temp"]},
        "conversion": {"enabled": False, "rule_id": None, "rule": None},
        "hours": {13: {"mean": prm.state_mean_dict(fitted["mean"])}},
    }
    pred, X_ref = fitted["mean"].predict(frame)
    from datetime import date as _date

    for i in (0, 7, len(frame) - 1):
        row = frame.iloc[i]
        X, mu0, g, _ = prm.state_features(state, 13, market=row["market"],
                                          target_date=_date.fromisoformat(row["target_date"]),
                                          high_so_far=row["F"], current_temp=row["x_current_temp"], nbm_mean=row["fh"])
        assert np.allclose(X, X_ref[i], atol=0, rtol=0) or np.max(np.abs(X - X_ref[i])) < 1e-12
        m = state["hours"][13]["mean"]
        yhat = mu0 + np.array([1.0, g, max(g, 0.0)]) @ m["ols"] + m["hgb"].predict(X)[0]
        assert abs(yhat - pred[i]) < 1e-9


def test_rung_latest_snapshot_at_or_before_own_capture_time():
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    index = [(t0 + timedelta(minutes=m), m, 1) for m in (0, 10, 50)]
    assert prm.latest_at_or_before(index, t0 + timedelta(minutes=9))[1] == 0
    assert prm.latest_at_or_before(index, t0 + timedelta(minutes=10))[1] == 10
    assert prm.latest_at_or_before(index, t0 + timedelta(minutes=49))[1] == 10  # never the later 50
    assert prm.latest_at_or_before(index, t0 - timedelta(minutes=1)) is None


def test_rung_simple_baseline_is_ols_only_with_constant_scale():
    frame = _frame()
    fitted = prm.fit_pooled(frame, market_id=False, doy=True, raw_columns=False, simple=True)
    assert fitted["mean"].hgb is None
    assert isinstance(fitted["scale"], prm.ConstantScale)
    yhat, X = fitted["mean"].predict(frame)
    mu0, g, _, _ = fitted["mean"]._anchors(frame)
    design = np.column_stack([np.ones_like(g), g, np.maximum(g, 0.0)])
    assert np.allclose(yhat, mu0 + design @ fitted["mean"].ols)
    s = fitted["scale"].predict(X)
    assert np.all(s == s[0])


def test_rung_blend_weight_is_exact_brier_minimiser_and_walk_forward():
    a = np.array([0.9, 0.1, 0.8, 0.2])
    b = np.array([0.5, 0.5, 0.5, 0.5])
    y = np.array([1.0, 0.0, 1.0, 0.0])
    offsets, n = np.array([0, 2]), np.array([2, 2])
    A, B = prm.blend_weight(a, b, y, offsets, n)
    w = prm.solve_weight(A, B)
    grid = np.linspace(0, 1, 1001)
    losses = [np.mean(((g * a + (1 - g) * b) - y) ** 2) for g in grid]
    assert abs(w - grid[int(np.argmin(losses))]) < 1e-3
    dates = np.array(["2026-08-01", "2026-08-02"])
    hours = np.array([7, 7])
    ws = prm.walk_forward_weights(dates, hours, np.array([True, True]), A, B, ["2026-08-01", "2026-08-02"],
                                  hour_set=(7,))
    assert ws[(7, "2026-08-01")] == 0.0  # nothing strictly before the first date
    assert ws[(7, "2026-08-02")] == prm.solve_weight(A[:1], B[:1])


def test_rung_rf_l6_frozen_state_refuses_a_changed_coefficient_part(tmp_path):
    part = {"coef": {"7": [0.1, 0.5, 10]}, "column": "n_own"}
    path = tmp_path / "coef.json"
    path.write_text(json.dumps({"l6_stack": part}), encoding="utf-8")
    sha = hashlib.sha256(json.dumps(part, sort_keys=True, separators=(",", ":"), allow_nan=False)
                         .encode("utf-8")).hexdigest()
    state, got = prm.l6_frozen_state(path, expected=sha)
    assert got == sha and state == {"coef": {7: (0.1, 0.5, 10)}, "column": "n_own"}
    with pytest.raises(prm.PooledModelError):
        prm.l6_frozen_state(path)  # the real frozen sha does not match this toy part


def test_rung_g_trajectory_features_use_only_reports_at_or_before_capture():
    from datetime import date as _date

    day = _date(2025, 8, 10).toordinal()
    instants = [0.0, 3600.0, 5400.0, 7200.0, 9000.0]
    temps = [70.0, 72.0, 73.0, 74.0, 99.0]  # the last report is after capture and must be ignored
    days = [day - 1, day, day, day, day]
    out = prm.trajectory_features(instants, temps, days, 7200.0, day)
    assert out["overnight_min"] == 72.0  # the previous local day's 70 is not overnight
    assert abs(out["trend3"] - 2.0) < 1e-9  # 72, 73, 74 at half-hour steps
    assert out["n_3h"] == 4
    sparse = prm.trajectory_features([0.0, 3600.0, 20000.0], [60.0, 61.0, 62.0], [day] * 3, 20000.0, day)
    assert sparse["trend3"] is None  # the last three span more than 3 h


def test_rung_g_extra_ols_columns_enter_the_baseline_design():
    rng = np.random.default_rng(0)
    n = 400
    frame = pd.DataFrame({
        "market": "atlanta", "centre": "2026-08-23", "season": "aug_sep", "year": np.repeat([2021, 2022], n // 2),
        "F": rng.normal(80, 3, n), "fh": rng.normal(85, 3, n), "lat": 33.6, "lon": -84.4, "elev": 300.0,
        "doy_sin": 0.0, "doy_cos": 1.0, "t_x": rng.normal(0, 1, n)})
    frame["y"] = frame["fh"] + 3.0 * frame["t_x"]
    base = prm.MeanModel(market_id=False, doy=True, raw_columns=False, use_hgb=False).fit(frame)
    extra = prm.MeanModel(market_id=False, doy=True, raw_columns=False, use_hgb=False, extra_ols=("t_x",)).fit(frame)
    err_base = np.mean((base.predict(frame)[0] - frame["y"]) ** 2)
    err_extra = np.mean((extra.predict(frame)[0] - frame["y"]) ** 2)
    assert len(extra.ols) == 4 and err_extra < 0.1 * err_base


def test_rung_h_regime_tags_use_only_reports_at_or_before_capture():
    def row(direction, speed, pressure, cover):
        return {"wind_dir": direction, "wind_speed": speed, "pressure_hpa": pressure, "cover": cover}

    obs = [(0.0, row(200, 8, 1012.0, "CLR")), (3 * 3600.0, row(320, 10, 1012.5, "OVC")),
           (4 * 3600.0, row(250, 9, 1008.0, "BKN"))]
    at_3h = prm.rh_obs_tags(obs, 3 * 3600.0, "los-angeles")
    # wind shift 200 -> 320 (120 deg, both >= 6 kt) over 3 h is a front; the 4 h report is not visible yet
    assert at_3h == {"front": "front", "cloud": "overcast", "onshore": "not_onshore"}
    assert prm.rh_obs_tags(obs, 4 * 3600.0, "los-angeles")["onshore"] == "onshore"
    assert prm.rh_obs_tags(obs, 4 * 3600.0, "chicago")["onshore"] == "n/a"
    assert prm.rh_obs_tags(obs, -1.0, "los-angeles")["front"] == "unknown"
    assert prm._bin(2.0, -2.0, 2.0) == "warm" and prm._bin(float("nan"), -2.0, 2.0) == "unknown"


def test_rung_i_temperature_keeps_zero_bands_and_mass_and_ties_go_to_one():
    p = np.array([0.0, 0.2, 0.5, 0.3, 0.1, 0.9])
    offsets, n = np.array([0, 4]), np.array([4, 2])
    q = prm.ri_temper(p, offsets, n, np.full(6, 2.0))
    assert q[0] == 0.0
    assert abs(q[:4].sum() - 1.0) < 1e-12 and abs(q[4:].sum() - 1.0) < 1e-12
    assert q[2] > p[2]  # tau > 1 sharpens toward the mode
    assert np.allclose(prm.ri_temper(p, offsets, n, np.ones(6)), np.r_[p[:4], p[4:] / p[4:].sum()])
    assert prm.ri_pick_tau([3.0] * len(prm.RI_TAU_GRID)) == 1.0
    losses = prm._ri_dict_losses([0.2, 0.6, 0.2], 1)
    assert losses[prm.RI_TAU_GRID.index(1.0)] == pytest.approx(0.04 + 0.16 + 0.04)
    assert prm.ri_pick_tau(losses) > 1.0


def test_rung_i_recentre_moves_median_to_reference_and_respects_impossible_bands():
    p = np.array([0.6, 0.3, 0.1, 0.0])
    ref = np.array([0.0, 0.1, 0.2, 0.7])
    out = prm.ri_recentre(p, ref, np.array([0]), np.array([4]), np.array([True, False, False, False]))
    assert out[0] == 0.0 and abs(out.sum() - 1.0) < 1e-12
    assert int(np.argmax(np.cumsum(out) >= 0.5)) == 3


def test_rung_j_loyo_summary_pools_only_the_gate_hours():
    rows = [{"hour": h, "date": f"2021-08-0{d}", "B_G_brier": 1.0 - (0.1 if h in (13, 14) else -0.1),
             "B_N_brier": 1.0, "B_G_log": 0.0, "B_N_log": 0.0} for h in (13, 14, 15, 16) for d in (1, 2, 3)]
    out = prm.rg_loyo_summary(rows, pairs=(("B_G", "B_N"),), pooled=(prm.RJ_GATE, prm.RJ_SECONDARY))
    assert out["B_G-B_N|13-14|brier"]["estimate"] == pytest.approx(-0.1)
    assert out["B_G-B_N|15-16|brier"]["estimate"] == pytest.approx(0.1)
    assert out["B_G-B_N|13-14|brier"]["n"] == 6
    default = prm.rg_loyo_summary(rows, pairs=(("B_G", "B_N"),))
    assert default["B_G-B_N|07-12|brier"]["n"] == len(rows)  # R-G's pooled label still means every row


def test_p3dn_diag_summary_flags_receipt_lookahead_and_share_keeps_negative_denominators():
    def row(hour, orig_snap, cap, f_o, f_f, c_o, c_f):
        return {"hour": hour, "differing_columns": [c for c, d in (("F", f_o != f_f), ("x_high_so_far", f_o != f_f),
                                                                    ("x_current_temp", c_o != c_f)) if d],
                "captured_utc": cap, "orig_snapshot_local": orig_snap, "fix_snapshot_local": "2026-08-20T13:00:00+00:00",
                "orig_snapshot_after_capture": orig_snap > cap, "orig_obs_after_capture": False,
                "orig_latest_obs_local": "2026-08-20T12:55:00+00:00", "fix_latest_obs_local": "2026-08-20T12:55:00+00:00",
                "orig_n_rows": 9, "fix_n_rows": 8, "orig_F": f_o, "fix_F": f_f, "orig_x_current_temp": c_o,
                "fix_x_current_temp": c_f, "fix_raw_high": f_f, "fix_raw_current": c_f}

    rows = [row(13, "2026-08-20T13:50:00+00:00", "2026-08-20T13:10:00+00:00", 81.0, 80.0, 79.0, 79.0),
            row(14, "2026-08-20T14:00:00+00:00", "2026-08-20T14:30:00+00:00", 82.0, 82.0, 80.5, 81.0)]
    out = prm.p3dn_input_summary(rows)
    assert out["13-14"]["rows"] == 2 and out["13-14"]["orig_snapshot_after_capture"] == 1
    assert out["13-14"]["orig_snapshot_minutes_after_capture"]["max"] == 40.0
    assert out["13"]["columns"]["F"]["rows_differing"] == 1 and out["14"]["columns"]["F"]["rows_differing"] == 0
    assert out["14"]["columns"]["x_current_temp"]["mean_orig_minus_fix"] == -0.5
    w = np.array([[1.0, 0.0], [0.0, 1.0]])
    share = prm._share_interval(w, np.array([1.0, 1.0]), np.array([2.0, -1.0]))
    assert share["estimate"] == 2.0 and share["draws_denominator_le_0"] == 1
    assert share["ci95"][0] < 0 < share["ci95"][1]
