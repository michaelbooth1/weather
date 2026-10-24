"""Lane L2 pooled residual research model: fold hygiene, floor, scoring and the decision rule.

Guards: L2 pre-declared rule (C:/t/l2/rule.md) - in-fold bias and normals, the hard observed floor,
probability mass, R0-identical row keys, date-clustered bootstrap, fail-closed import off the capture
host and no output inside the repository.
"""
import importlib
import json
import math

import numpy as np
import pandas as pd
import pytest

try:
    prm = importlib.import_module("weather.calibration.pooled_residual_model")
except ImportError as exc:  # pragma: no cover - only on the capture host
    if "pooled_residual_model refuses" in str(exc):
        pytest.skip("research module refuses this host by design", allow_module_level=True)
    raise


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

    def fake(market, centre, manifests, out_root):
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
