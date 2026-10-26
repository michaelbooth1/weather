"""Research-only R0 full-year vs windowed scorer (weather.calibration.r0_full_year).

Guards: lane L1 pre-declared full-year pick rule; blocked leave-one-year-out validation; PIT corpus cutoff 2026-09-29.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from weather.calibration import feature_model as fm
from weather.calibration import r0_full_year as fy

ROOT = Path(__file__).resolve().parents[2]
CENTRE = date(2026, 11, 24)


def test_window_matches_the_trainer_test():
    assert fy.in_window(date(2023, 11, 17), CENTRE)
    assert fy.in_window(date(2023, 12, 1), CENTRE)
    assert not fy.in_window(date(2023, 11, 16), CENTRE)
    assert not fy.in_window(date(2023, 12, 2), CENTRE)
    assert fy.in_window(date(2024, 2, 29), date(2026, 3, 1))


def test_seasonal_pair_is_on_the_unit_circle():
    for day in (date(2022, 1, 1), date(2024, 2, 29), date(2025, 7, 4)):
        f = fy.seasonal_features(day)
        assert math.isclose(f["doy_sin"] ** 2 + f["doy_cos"] ** 2, 1.0)
    assert len(fy.dates_in_years([2024])) == 366


def test_seasonal_plan_inserts_after_numeric_and_refuses_a_clash():
    plan = {"numeric_feature_names": ["a", "b"], "feature_names": ["a", "b", "wind_X"]}
    out = fy.seasonal_allowlist_plan(plan)
    assert out["feature_names"] == ["a", "b", "doy_sin", "doy_cos", "wind_X"]
    assert out["numeric_feature_names"] == ["a", "b", "doy_sin", "doy_cos"]
    assert plan["feature_names"] == ["a", "b", "wind_X"]
    with pytest.raises(fy.FullYearError):
        fy.seasonal_allowlist_plan({"numeric_feature_names": ["doy_sin"], "feature_names": ["doy_sin"]})


def _write_corpus(tmp_path, name, dates, *, contract="c1"):
    folder = tmp_path / name
    folder.mkdir()
    (folder / "plan.json").write_text(json.dumps({"expected_dates_by_year": {"x": dates}}), encoding="utf-8")
    manifest = {
        "corpus_id": name, "manifest_sha256": name * 2, "market_ids": ["atlanta"], "years": [2023],
        "schema_version": "s", "target_year": 2026, "source_fields": ["temperature_2m"],
        "cutoff_hours_local": [7, 8], "issue_contract": contract, "normalizer_version": "n",
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder / "manifest.json"


class _Reader:
    def __init__(self, path, market):
        self.path = Path(path)
        self.missing = {("2023-03-02", 8)}

    def resolve(self, day, hour):
        if (day, hour) in self.missing:
            raise ValueError("absent")
        return {"forecast_high": 1.0, "profile_rows": [], "corpus": self.path.parent.name}


def _union(paths):
    return fy.SeasonCorpusUnion(
        paths, "atlanta", target_year=2026, required_cutoff_hours=[7, 8],
        reader_factory=_Reader, preflight=lambda *a, **k: {"preflight_sha256": "p"},
        verify=lambda p: json.loads(Path(p).read_text(encoding="utf-8")),
    )


def test_season_union_dispatches_by_date_and_fails_closed(tmp_path):
    a = _write_corpus(tmp_path, "spring", ["2023-03-01", "2023-03-02"])
    b = _write_corpus(tmp_path, "autumn", ["2023-11-20"])
    union = _union([a, b])
    assert union.resolve("2023-11-20", 7)["corpus"] == "autumn"
    assert union.resolve(date(2023, 3, 1), 8)["corpus"] == "spring"
    assert union.covers("2023-03-01") and not union.covers("2023-03-02") and not union.covers("2023-06-01")
    with pytest.raises(Exception, match="ambient fallback is not allowed"):
        union.resolve("2023-06-01", 7)
    assert len(union.record()["union_sha256"]) == 64
    c = _write_corpus(tmp_path, "overlap", ["2023-11-20"])
    with pytest.raises(fy.FullYearError, match="overlap"):
        _union([a, b, c])
    d = _write_corpus(tmp_path, "other", ["2023-05-01"], contract="c2")
    with pytest.raises(fy.FullYearError, match="incompatible"):
        _union([a, d])
    with pytest.raises(fy.FullYearError, match="twice"):
        _union([a, a])


def _synthetic_records():
    rng = np.random.default_rng(7)
    records = []
    for year in (2021, 2022, 2023):
        day = date(year, 1, 1)
        while day.year == year:
            if day.day % 3 == 0 or fy.in_window(day, CENTRE):
                x = float(rng.normal())
                season = math.cos(2 * math.pi * day.timetuple().tm_yday / 365.25)
                bucket = int(round(60 + 15 * season + 3 * x + rng.normal()))
                records.append({"target_date": day, "x": x, "final_bucket": bucket})
            day += timedelta(days=1)
    return records


def _frame(rows, plan):
    df = pd.DataFrame(rows)
    for column in plan["feature_names"]:
        if column not in df:
            df[column] = np.nan
    return df, list(plan["feature_names"])


PLAN = {"numeric_feature_names": ["x"], "feature_names": ["x"]}


def test_windowed_arm_equals_the_trainers_per_row_refit():
    records = _synthetic_records()
    window_rows = [r for r in records if fy.in_window(r["target_date"], CENTRE)]
    buckets = sorted({r["final_bucket"] for r in window_rows})
    ours = fy.score_hour(records, arm=fy.ARM_WINDOWED, leaf=5, centre=CENTRE, bucket_space=buckets,
                         frame_builder=_frame, plan=PLAN, fm=fm)
    # The trainer's loop: one refit per validation row on the blocked split.
    df, cols = _frame(window_rows, PLAN)
    X, y = df[cols], df["final_bucket"]
    split = fm.feature_blocked_validation_plan(window_rows)["train_indices_by_validation_index"]
    expected = {}
    for val_idx in range(len(window_rows)):
        train = split[val_idx]
        p_clim = fm.smoothed_dist([window_rows[i]["final_bucket"] for i in train], buckets, alpha=0.10)
        m = fm.fold_local_feature_matrices(X, train, [val_idx], cols, 1)
        hgb = fy.make_hgb(5).fit(m["hgb_train"], y.iloc[train])
        dist = {int(c): float(p) for c, p in zip(hgb.classes_, hgb.predict_proba(m["hgb_validation"])[0])}
        expected[str(window_rows[val_idx]["target_date"])] = fm.log_loss(
            fm.blend(p_clim.copy(), dist, 0.80), int(y.iloc[val_idx]))
    assert len(ours) == len(expected) == len(window_rows)
    for row in ours:
        assert row["hgb_log_loss"] == pytest.approx(expected[row["validation_date"]], abs=1e-12)


def test_full_year_arm_scores_the_same_rows_with_more_training_data():
    records = _synthetic_records()
    buckets = sorted({r["final_bucket"] for r in records if fy.in_window(r["target_date"], CENTRE)})
    kwargs = dict(leaf=5, centre=CENTRE, bucket_space=buckets, frame_builder=_frame, plan=PLAN, fm=fm)
    windowed = fy.score_hour(records, arm=fy.ARM_WINDOWED, **kwargs)
    full = fy.score_hour(records, arm=fy.ARM_FULL_YEAR, **kwargs)
    assert [r["validation_date"] for r in windowed] == [r["validation_date"] for r in full]
    assert all(f["n_train"] > w["n_train"] for w, f in zip(windowed, full))
    assert all(f["n_train_window"] == w["n_train_window"] == w["n_train"] for w, f in zip(windowed, full))
    with pytest.raises(fy.FullYearError):
        fy.score_hour(records, arm="nope", **kwargs)


def _rows(arm, leaf, shift):
    out = []
    for market in ("atlanta", "austin"):
        for hour in (7, 8, 12, 13):
            for k in range(12):
                day = f"2023-11-{17 + k % 12:02d}"
                out.append({"market": market, "hour": hour, "validation_date": day, "arm": arm, "leaf": leaf,
                            "hgb_log_loss": 3.0 + shift + 0.01 * k, "train_in_sample_log_loss": 2.0, "n_train": 10})
    return out


def test_rule_wins_adopts_and_picks(tmp_path):
    rows = _rows("windowed", 20, 0.0) + _rows("full_year", 20, -0.2) + _rows("full_year", 10, -0.3) + _rows("full_year", 5, 0.1)
    deltas, unpaired = fy.paired_deltas(rows, ("windowed", 20), ("full_year", 20))
    assert unpaired == 0 and all(v == pytest.approx(-0.2) for v in deltas.values())
    lo, hi = fy.bootstrap_ci(deltas, fy.HEADLINE_HOURS)
    assert lo == pytest.approx(-0.2) and hi == pytest.approx(-0.2)
    verdict = fy.evaluate_arm(deltas, [7, 8, 12, 13])
    assert verdict["adoptable"] and verdict["headline_07_12"]["win"]
    worse = fy.evaluate_arm(fy.paired_deltas(rows, ("windowed", 20), ("full_year", 5))[0], [7, 8, 12, 13])
    assert not worse["adoptable"] and worse["per_hour"][13]["worse"]
    arms = {"full_year:20": verdict, "full_year:10": fy.evaluate_arm(
        fy.paired_deltas(rows, ("windowed", 20), ("full_year", 10))[0], [7, 8, 12, 13]), "full_year:5": worse}
    assert fy.pick(arms) == "full_year:10"
    assert fy.pick({"full_year:5": worse}) is None


def test_bootstrap_matches_the_scalar_definition():
    rng = np.random.default_rng(1)
    deltas = {(m, h, f"d{d}"): float(rng.normal()) for m in ("a", "b") for h in (7, 8) for d in range(9)}
    dates = sorted({k[2] for k in deltas})
    weights = fy.bootstrap_weights(dates, draws=50, seed=3)
    scalar = [fy.market_mean_delta(deltas, [7, 8], dict(zip(dates, w))) for w in weights]
    lo, hi = fy.bootstrap_ci(deltas, [7, 8], draws=50, seed=3)
    assert lo == pytest.approx(np.percentile(scalar, 2.5)) and hi == pytest.approx(np.percentile(scalar, 97.5))


def test_reproduction_check_requires_identical_rows():
    ours = [{"market": "atlanta", "arm": "windowed", "leaf": 20, "hour": 7, "validation_date": "2021-11-17",
             "hgb_log_loss": 4.0}]
    ref = [{"hour": 7, "validation_date": "2021-11-17", "hgb_log_loss": 4.0}]
    assert fy.reproduction_check(ours, ref, "atlanta")["pass"]
    assert not fy.reproduction_check(ours, [dict(ref[0], hgb_log_loss=4.1)], "atlanta")["pass"]
    assert not fy.reproduction_check(ours, ref + [dict(ref[0], hour=8)], "atlanta")["pass"]


def test_output_root_refuses_data_and_artifacts():
    from weather.paths import ARTIFACTS_ROOT, DATA_ROOT

    for protected in (DATA_ROOT / "x", ARTIFACTS_ROOT / "models" / "x"):
        with pytest.raises(fy.FullYearError):
            fy._guard_output_root(protected)


def test_no_other_module_imports_the_research_scorer():
    """The served trainer and every serving path stay byte-identical: nothing imports this module."""
    offenders = []
    for path in (ROOT / "src").rglob("*.py"):
        if path.name == "r0_full_year.py":
            continue
        if "r0_full_year" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


@pytest.mark.spawns
def test_production_import_fails_closed():
    result = subprocess.run(
        [sys.executable, "-c", "import weather.calibration.r0_full_year"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0
    assert "research-only" in result.stderr


def test_hard_floor_matches_the_served_stage():
    probs = {60: 0.5, 61: 0.3, 62: 0.2}
    out = fy.hard_floor(probs, 61)
    assert out[60] == pytest.approx(0.5e-6 / (0.5e-6 + 0.5))
    assert sum(out.values()) == pytest.approx(1.0)
    assert fy.hard_floor(probs, 61, 0.0)[60] == 0.0
    assert fy.hard_floor(probs, 70, 0.0) == {60: 0.0, 61: 0.0, 62: 0.0, 70: 1.0}
    assert fy.hard_floor(probs, None) == probs
    assert fy.observed_floor(61.5) == 62 and fy.observed_floor(None) is None


def test_compare_fair_gates_on_parity_and_needs_all_markets(tmp_path):
    rows_root, l3_root = tmp_path / "rows", tmp_path / "l3"
    l3_root.mkdir()
    for market in ("atlanta", "austin"):
        (rows_root / market).mkdir(parents=True)
        ours, l3 = [], []
        for hour in (7, 12, 13):
            for k in range(10):
                day = f"2023-11-{17 + k:02d}"
                base = {"market": market, "hour": hour, "validation_date": day, "leaf": 20}
                ours.append(dict(base, arm="windowed", hgb_log_loss=4.0))
                ours.append(dict(base, arm="full_year", hgb_log_loss=3.0, hgb_floor_log_loss=2.0 + 0.01 * k,
                                 hgb_floor0_log_loss=2.0))
                l3.append({"market_id": market, "hour": hour, "validation_date": day, "r0_repro_log_loss": 4.0,
                           "r0_baseline_floor_log_loss": 3.5, "bias_corrected_forecast_floor_log_loss": 2.5,
                           "ols_floor_log_loss": 1.5 + 0.01 * k})
        (rows_root / market / f"r0_full_year_rows_{market}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in ours), encoding="utf-8")
        if market == "austin":
            l3[0]["r0_repro_log_loss"] = 4.1  # parity break
        (l3_root / f"challenger_rows_{market}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in l3), encoding="utf-8")
    result = fy.compare_fair(rows_root, l3_root, ["atlanta", "austin"])
    assert result["markets_scored"] == ["atlanta"]
    assert result["status"] == "PROVISIONAL" and not result["adopt_full_year"]
    assert result["comparisons"]["FYF_vs_f_bias_corrected_forecast_floor"]["beats"]
    assert not result["comparisons"]["FYF_vs_ols_floor"]["beats"]
    assert result["comparisons"]["FYF_vs_ols_floor"]["headline_07_12"]["delta"] == pytest.approx(0.5)
    full = fy.compare_fair(rows_root, l3_root, ["atlanta"])
    assert full["status"] == "FINAL" and full["beats_decisive"] == {
        "f_bias_corrected_forecast_floor": True, "ols_floor": False} and not full["adopt_full_year"]
