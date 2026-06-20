"""Estimate weather input-variable significance from settled snapshot logs.

This is a research/audit CLI, not serving code. It joins per-snapshot feature
records to settlement labels, standardizes targets within each market, and
scores feature value in several complementary ways:

* univariate row-level and day-level associations;
* bootstrapped regularized linear coefficients;
* grouped cross-validated HGB permutation importance;
* family-level grouped permutation importance.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pandas.errors import PerformanceWarning
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupKFold

try:
    from weather.model.feature_store import FEATURE_COLUMNS
except Exception:  # pragma: no cover - fallback for ad hoc research runs.
    FEATURE_COLUMNS = []


RANDOM_SEED = 90210
MIN_ROWS = 100
MIN_DAYS = 10
ML_MIN_ROWS = 250
ML_MIN_DAYS = 15
BOOTSTRAPS = 40
PERM_REPEATS = 1
HGB_MAX_ITER = 80

METADATA_COLUMNS = {
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "target_date",
    "model_version",
    "feature_schema_version",
    "market_id",
    "city",
    "settlement_high",
    "settlement_unit",
    "market_day",
    "folder",
    "winning_band_value",
    "winning_band_value_hi",
    "settlement_status",
    "feature_source",
}

DIAGNOSTIC_COLUMNS = {
    "latest_wu_history_time",
    "latest_wu_history_minute",
    "latest_wu_history_temp",
}

CATEGORICAL_FEATURES = ["wind_group", "cloud_group"]

CONTEXT_FEATURES = ["cutoff_hour"]

warnings.simplefilter("ignore", PerformanceWarning)


@dataclass
class LoadedFolder:
    folder: str
    rows: int
    feature_source: str
    status: str
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots-root", default="data/snapshots")
    parser.add_argument("--output-dir", default="data/backtest")
    parser.add_argument("--prefix", default="input_variable_significance_2026_06_18")
    parser.add_argument("--include-mismatches", action="store_true")
    parser.add_argument("--include-diagnostics", action="store_true")
    parser.add_argument("--max-hgb-features", type=int, default=45)
    parser.add_argument("--bootstraps", type=int, default=BOOTSTRAPS)
    parser.add_argument("--perm-repeats", type=int, default=PERM_REPEATS)
    parser.add_argument("--hgb-max-iter", type=int, default=HGB_MAX_ITER)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def settlement_status(settlement: dict[str, Any]) -> str:
    return str(
        settlement.get("reconciliation_status")
        or (settlement.get("polymarket_reconciliation") or {}).get("status")
        or ((settlement.get("evidence") or {}).get("polymarket_reconciliation") or {}).get("status")
        or ""
    ).lower()


def settlement_high(settlement: dict[str, Any]) -> float | None:
    for key in ("settlement_high", "actual_high", "settled_high", "rounded_high", "max_temp", "high"):
        value = settlement.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def load_feature_records(folder: Path) -> tuple[pd.DataFrame, str, str]:
    jsonl_path = folder / "features.jsonl"
    if jsonl_path.exists():
        records = read_jsonl(jsonl_path)
        if records:
            return pd.DataFrame(records), "features.jsonl", ""

    csv_path = folder / "features_long.csv"
    if not csv_path.exists():
        return pd.DataFrame(), "missing", "no feature tape"
    try:
        return pd.read_csv(csv_path), "features_long.csv", ""
    except Exception as exc:
        try:
            frame = pd.read_csv(csv_path, engine="python", on_bad_lines="skip")
            return frame, "features_long.csv:on_bad_lines_skip", str(exc)
        except Exception as fallback_exc:
            return pd.DataFrame(), "unreadable", f"{exc}; fallback={fallback_exc}"


def load_dataset(
    snapshots_root: Path,
    include_mismatches: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    load_rows: list[LoadedFolder] = []

    for folder in sorted(path for path in snapshots_root.iterdir() if path.is_dir()):
        settlement_path = folder / "settlement.json"
        if not settlement_path.exists():
            load_rows.append(LoadedFolder(folder.name, 0, "none", "unsettled", "no settlement.json"))
            continue
        settlement = read_json(settlement_path)
        status = settlement_status(settlement)
        if status != "match" and not include_mismatches:
            load_rows.append(LoadedFolder(folder.name, 0, "none", status or "unknown", "excluded"))
            continue
        high = settlement_high(settlement)
        if high is None:
            load_rows.append(LoadedFolder(folder.name, 0, "none", status, "missing settlement high"))
            continue

        features, feature_source, note = load_feature_records(folder)
        if features.empty:
            load_rows.append(LoadedFolder(folder.name, 0, feature_source, status, note or "no feature rows"))
            continue

        market_id = settlement.get("market_id") or str(features.get("event_slug", pd.Series([folder.name])).iloc[0])
        target_date = settlement.get("target_date") or str(features.get("target_date", pd.Series([""])).iloc[0])
        market_day = f"{market_id}|{target_date}"
        extra = {
            "market_id": market_id,
            "city": settlement.get("city"),
            "settlement_high": high,
            "settlement_unit": settlement.get("settlement_unit"),
            "market_day": market_day,
            "folder": folder.name,
            "winning_band_value": settlement.get("winning_band_value"),
            "winning_band_value_hi": settlement.get("winning_band_value_hi"),
            "settlement_status": status,
            "feature_source": feature_source,
        }
        for key, value in extra.items():
            features[key] = value
        frames.append(features)
        load_rows.append(LoadedFolder(folder.name, len(features), feature_source, status, note))

    if not frames:
        return pd.DataFrame(), pd.DataFrame([row.__dict__ for row in load_rows])

    data = pd.concat(frames, ignore_index=True, sort=False)
    data = data.drop_duplicates(subset=["folder", "snapshot_id"], keep="last")
    data["cutoff_hour"] = pd.to_numeric(data.get("cutoff_hour"), errors="coerce")
    data["captured_at_utc_dt"] = pd.to_datetime(data.get("captured_at_utc"), errors="coerce", utc=True)
    data["time_slice"] = pd.cut(
        data["cutoff_hour"],
        bins=[-np.inf, 10, 14, np.inf],
        labels=["early", "midday", "late"],
    ).astype("string")
    return data, pd.DataFrame([row.__dict__ for row in load_rows])


def candidate_features(data: pd.DataFrame, include_diagnostics: bool) -> list[str]:
    if FEATURE_COLUMNS:
        base = [column for column in FEATURE_COLUMNS if column in data.columns]
    else:
        excluded = set(METADATA_COLUMNS)
        excluded.update({"captured_at_utc_dt", "time_slice"})
        if not include_diagnostics:
            excluded.update(DIAGNOSTIC_COLUMNS)
        base = [column for column in data.columns if column not in excluded]
    for column in CONTEXT_FEATURES:
        if column in data.columns and column not in base:
            base.append(column)
    if include_diagnostics:
        for column in DIAGNOSTIC_COLUMNS:
            if column in data.columns and column not in base:
                base.append(column)
    return base


def fdr_bh(p_values: pd.Series) -> pd.Series:
    values = pd.to_numeric(p_values, errors="coerce")
    out = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna()
    if valid.empty:
        return out
    order = valid.sort_values().index
    ranked = valid.loc[order].to_numpy()
    n = len(ranked)
    adjusted = ranked * n / np.arange(1, n + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    out.loc[order] = np.clip(adjusted, 0.0, 1.0)
    return out


def add_standardized_target(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    day_targets = data[["market_day", "market_id", "settlement_high"]].drop_duplicates()
    market_stats = day_targets.groupby("market_id")["settlement_high"].agg(["mean", "std"])
    market_stats["std"] = market_stats["std"].replace(0, np.nan)
    data = data.join(market_stats, on="market_id", rsuffix="_market")
    data["target_market_z"] = (data["settlement_high"] - data["mean"]) / data["std"]
    data = data.drop(columns=["mean", "std"])
    return data


def numeric_feature_frame(data: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, list[str], list[str]]:
    categorical = [column for column in CATEGORICAL_FEATURES if column in features and column in data.columns]
    numeric = [column for column in features if column not in categorical and column in data.columns]
    numeric_frame = pd.DataFrame(index=data.index)
    for column in numeric:
        numeric_frame[column] = pd.to_numeric(data[column], errors="coerce")
    return numeric_frame, numeric, categorical


def within_market_z(data: pd.DataFrame, numeric_frame: pd.DataFrame) -> pd.DataFrame:
    z_frame = pd.DataFrame(index=data.index)
    groups = data["market_id"]
    for column in numeric_frame.columns:
        values = numeric_frame[column]
        means = values.groupby(groups).transform("mean")
        stds = values.groupby(groups).transform("std").replace(0, np.nan)
        z_frame[column] = (values - means) / stds
    return z_frame


def coverage_table(
    data: pd.DataFrame,
    numeric_frame: pd.DataFrame,
    z_frame: pd.DataFrame,
    categorical: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for column in numeric_frame.columns:
        raw = numeric_frame[column]
        z = z_frame[column]
        valid = raw.notna()
        rows.append(
            {
                "feature": column,
                "kind": "numeric",
                "family": feature_family(column),
                "n_rows_non_missing": int(valid.sum()),
                "row_coverage": float(valid.mean()),
                "n_days_non_missing": int(data.loc[valid, "market_day"].nunique()),
                "n_markets_non_missing": int(data.loc[valid, "market_id"].nunique()),
                "n_unique_raw": int(raw.nunique(dropna=True)),
                "n_rows_within_market_variation": int(z.notna().sum()),
                "analyzable": bool(z.notna().sum() >= MIN_ROWS and data.loc[z.notna(), "market_day"].nunique() >= MIN_DAYS),
            }
        )
    for column in categorical:
        valid = data[column].notna()
        rows.append(
            {
                "feature": column,
                "kind": "categorical",
                "family": feature_family(column),
                "n_rows_non_missing": int(valid.sum()),
                "row_coverage": float(valid.mean()),
                "n_days_non_missing": int(data.loc[valid, "market_day"].nunique()),
                "n_markets_non_missing": int(data.loc[valid, "market_id"].nunique()),
                "n_unique_raw": int(data[column].nunique(dropna=True)),
                "n_rows_within_market_variation": int(valid.sum()),
                "analyzable": bool(valid.sum() >= MIN_ROWS and data.loc[valid, "market_day"].nunique() >= MIN_DAYS),
            }
        )
    return pd.DataFrame(rows)


def safe_pearson(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    if len(x) < 3 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return math.nan, math.nan
    try:
        result = stats.pearsonr(x, y)
        return float(result.statistic), float(result.pvalue)
    except Exception:
        return math.nan, math.nan


def safe_spearman(x: pd.Series, y: pd.Series) -> tuple[float, float]:
    if len(x) < 3 or x.nunique(dropna=True) < 2 or y.nunique(dropna=True) < 2:
        return math.nan, math.nan
    try:
        result = stats.spearmanr(x, y)
        return float(result.statistic), float(result.pvalue)
    except Exception:
        return math.nan, math.nan


def bootstrap_corr_p(day_values: pd.DataFrame, rng: np.random.Generator) -> tuple[float, float, float]:
    if len(day_values) < MIN_DAYS:
        return math.nan, math.nan, math.nan
    observed, _ = safe_pearson(day_values["x"], day_values["y"])
    if not np.isfinite(observed):
        return math.nan, math.nan, math.nan
    boot = []
    n = len(day_values)
    values = day_values[["x", "y"]].to_numpy()
    for _ in range(BOOTSTRAPS):
        idx = rng.integers(0, n, size=n)
        sample = values[idx]
        if np.std(sample[:, 0]) <= 1e-12 or np.std(sample[:, 1]) <= 1e-12:
            continue
        boot.append(float(np.corrcoef(sample[:, 0], sample[:, 1])[0, 1]))
    if not boot:
        return math.nan, math.nan, math.nan
    boot_arr = np.asarray(boot)
    if observed >= 0:
        p = 2.0 * min(float(np.mean(boot_arr <= 0.0)), float(np.mean(boot_arr >= 0.0)))
    else:
        p = 2.0 * min(float(np.mean(boot_arr >= 0.0)), float(np.mean(boot_arr <= 0.0)))
    return float(np.quantile(boot_arr, 0.025)), float(np.quantile(boot_arr, 0.975)), min(1.0, p)


def latest_per_day(frame: pd.DataFrame, x: pd.Series) -> pd.DataFrame:
    working = pd.DataFrame(
        {
            "market_day": frame["market_day"],
            "captured_at_utc_dt": frame["captured_at_utc_dt"],
            "x": x,
            "y": frame["target_market_z"],
        }
    ).dropna(subset=["x", "y"])
    if working.empty:
        return working
    working = working.sort_values(["market_day", "captured_at_utc_dt"])
    return working.groupby("market_day", as_index=False).tail(1)


def univariate_analysis(
    data: pd.DataFrame,
    z_frame: pd.DataFrame,
    categorical: list[str],
    coverage: pd.DataFrame,
) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    rows: list[dict[str, Any]] = []
    slices: dict[str, pd.Series] = {
        "all": pd.Series(True, index=data.index),
        "early": data["time_slice"].eq("early"),
        "midday": data["time_slice"].eq("midday"),
        "late": data["time_slice"].eq("late"),
    }
    analyzable = set(coverage.loc[coverage["analyzable"], "feature"])
    for slice_name, mask in slices.items():
        frame = data.loc[mask].copy()
        if frame.empty:
            continue
        for column in z_frame.columns:
            if column not in analyzable:
                continue
            x = z_frame.loc[mask, column]
            valid = x.notna() & frame["target_market_z"].notna()
            n_rows = int(valid.sum())
            n_days = int(frame.loc[valid, "market_day"].nunique())
            if n_rows < MIN_ROWS or n_days < MIN_DAYS:
                continue
            pearson_r, pearson_p = safe_pearson(x.loc[valid], frame.loc[valid, "target_market_z"])
            spearman_r, spearman_p = safe_spearman(x.loc[valid], frame.loc[valid, "target_market_z"])
            day_values = latest_per_day(frame, x)
            day_pearson_r, day_pearson_p = safe_pearson(day_values["x"], day_values["y"])
            day_spearman_r, day_spearman_p = safe_spearman(day_values["x"], day_values["y"])
            ci_low, ci_high, boot_p = bootstrap_corr_p(day_values, rng)
            rows.append(
                {
                    "slice": slice_name,
                    "feature": column,
                    "kind": "numeric",
                    "family": feature_family(column),
                    "n_rows": n_rows,
                    "n_days": n_days,
                    "row_pearson_r": pearson_r,
                    "row_pearson_p_naive": pearson_p,
                    "row_spearman_r": spearman_r,
                    "row_spearman_p_naive": spearman_p,
                    "daily_latest_pearson_r": day_pearson_r,
                    "daily_latest_pearson_p": day_pearson_p,
                    "daily_latest_spearman_r": day_spearman_r,
                    "daily_latest_spearman_p": day_spearman_p,
                    "cluster_bootstrap_pearson_ci_low": ci_low,
                    "cluster_bootstrap_pearson_ci_high": ci_high,
                    "cluster_bootstrap_sign_p": boot_p,
                }
            )
        for column in categorical:
            if column not in analyzable or column not in frame.columns:
                continue
            day_values = frame[["market_day", "captured_at_utc_dt", "target_market_z", column]].dropna()
            if day_values.empty:
                continue
            day_values = day_values.sort_values(["market_day", "captured_at_utc_dt"]).groupby("market_day", as_index=False).tail(1)
            groups = [
                part["target_market_z"].to_numpy()
                for _, part in day_values.groupby(column)
                if len(part) >= 2
            ]
            p = math.nan
            stat = math.nan
            if len(groups) >= 2:
                try:
                    result = stats.kruskal(*groups)
                    stat = float(result.statistic)
                    p = float(result.pvalue)
                except Exception:
                    pass
            rows.append(
                {
                    "slice": slice_name,
                    "feature": column,
                    "kind": "categorical",
                    "family": feature_family(column),
                    "n_rows": int(frame[column].notna().sum()),
                    "n_days": int(day_values["market_day"].nunique()),
                    "row_pearson_r": math.nan,
                    "row_pearson_p_naive": math.nan,
                    "row_spearman_r": math.nan,
                    "row_spearman_p_naive": math.nan,
                    "daily_latest_pearson_r": math.nan,
                    "daily_latest_pearson_p": math.nan,
                    "daily_latest_spearman_r": stat,
                    "daily_latest_spearman_p": p,
                    "cluster_bootstrap_pearson_ci_low": math.nan,
                    "cluster_bootstrap_pearson_ci_high": math.nan,
                    "cluster_bootstrap_sign_p": p,
                }
            )
    result = pd.DataFrame(rows)
    if not result.empty:
        for slice_name, idx in result.groupby("slice").groups.items():
            result.loc[idx, "cluster_bootstrap_sign_q"] = fdr_bh(result.loc[idx, "cluster_bootstrap_sign_p"])
            result.loc[idx, "daily_latest_spearman_q"] = fdr_bh(result.loc[idx, "daily_latest_spearman_p"])
    return result


def feature_family(feature: str) -> str:
    if feature in {"cutoff_hour", "minutes_since_cutoff"}:
        return "time_context"
    if feature in {
        "high_so_far",
        "current_temp",
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "live_reading_temp",
        "live_reading_minus_high",
    }:
        return "observed_temp_path"
    if feature in {"forecast_source_count", "forecast_disagreement"}:
        return "forecast_source_state"
    if feature.startswith("forecast_"):
        return "open_meteo_forecast_profile"
    if feature.startswith("nws_grid_") or feature.startswith("open_meteo_") or feature.startswith("eccc_gem_"):
        return "official_multimodel_guidance"
    if feature.startswith("marine_") or feature in {
        "onshore_flow",
        "onshore_wind_speed_kmh",
        "lake_breeze_proxy",
    }:
        return "marine_microclimate"
    if feature.startswith("mrms_"):
        return "radar_precip"
    if feature.startswith("reanalysis_"):
        return "reanalysis_synoptic"
    if feature in {
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
        "wind_gust_kmh",
        "wind_shift_3h_degrees",
        "wind_group",
        "cloud_group",
    }:
        return "surface_weather"
    if feature in DIAGNOSTIC_COLUMNS:
        return "source_diagnostics"
    return "other"


def select_ml_features(coverage: pd.DataFrame, max_features: int) -> list[str]:
    candidates = coverage[
        (coverage["analyzable"])
        & (coverage["n_rows_non_missing"] >= ML_MIN_ROWS)
        & (coverage["n_days_non_missing"] >= ML_MIN_DAYS)
    ].copy()
    if candidates.empty:
        return []
    candidates["coverage_rank"] = candidates["row_coverage"].rank(ascending=False, method="first")
    candidates["days_rank"] = candidates["n_days_non_missing"].rank(ascending=False, method="first")
    candidates = candidates.sort_values(["n_days_non_missing", "n_rows_non_missing"], ascending=False)
    return candidates.head(max_features)["feature"].tolist()


def build_ml_matrix(
    data: pd.DataFrame,
    z_frame: pd.DataFrame,
    features: list[str],
    categorical: list[str],
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    columns: list[pd.Series] = []
    names: list[str] = []
    feature_to_columns: dict[str, list[str]] = defaultdict(list)

    for feature in features:
        if feature in categorical:
            dummies = pd.get_dummies(data[feature].astype("string").fillna("MISSING"), prefix=feature, dtype=float)
            for dummy_col in dummies.columns:
                columns.append(dummies[dummy_col])
                names.append(dummy_col)
                feature_to_columns[feature].append(dummy_col)
            continue
        if feature not in z_frame.columns:
            continue
        raw = z_frame[feature]
        value_col = f"{feature}__z"
        columns.append(raw.fillna(0.0).astype(float))
        names.append(value_col)
        feature_to_columns[feature].append(value_col)
        missing_rate = float(raw.isna().mean())
        if 0.02 <= missing_rate <= 0.98:
            missing_col = f"{feature}__missing"
            columns.append(raw.isna().astype(float))
            names.append(missing_col)
            feature_to_columns[feature].append(missing_col)

    if not columns:
        return pd.DataFrame(index=data.index), {}
    matrix = pd.concat(columns, axis=1)
    matrix.columns = names
    return matrix, dict(feature_to_columns)


def grouped_cv_splits(groups: pd.Series, max_splits: int = 5):
    unique_groups = groups.dropna().unique()
    n_splits = min(max_splits, len(unique_groups))
    if n_splits < 2:
        return []
    splitter = GroupKFold(n_splits=n_splits)
    dummy = np.zeros(len(groups))
    return list(splitter.split(dummy, groups=groups))


def linear_bootstrap_analysis(
    data: pd.DataFrame,
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    feature_to_columns: dict[str, list[str]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if X.empty:
        return pd.DataFrame(), {}
    alpha = 10.0
    x_np = X.to_numpy(dtype=float)
    y_np = y.to_numpy(dtype=float)
    unique_groups = np.array(sorted(groups.dropna().unique()))
    group_to_indices = {group: np.flatnonzero(groups.to_numpy() == group) for group in unique_groups}

    splits = grouped_cv_splits(groups, max_splits=5)
    cv_metrics = []
    for train_idx, test_idx in splits:
        model = Ridge(alpha=alpha)
        model.fit(x_np[train_idx], y_np[train_idx])
        preds = model.predict(x_np[test_idx])
        cv_metrics.append(
            {
                "mae": float(mean_absolute_error(y_np[test_idx], preds)),
                "r2": float(r2_score(y_np[test_idx], preds)),
                "n_train": int(len(train_idx)),
                "n_test": int(len(test_idx)),
            }
        )

    rng = np.random.default_rng(RANDOM_SEED)
    coef_by_feature: dict[str, list[float]] = defaultdict(list)
    selected_by_feature: dict[str, list[int]] = defaultdict(list)
    col_index = {column: i for i, column in enumerate(X.columns)}
    numeric_feature_single_col = {
        feature: columns[0]
        for feature, columns in feature_to_columns.items()
        if len(columns) >= 1 and columns[0].endswith("__z")
    }

    for _ in range(BOOTSTRAPS):
        sampled_groups = rng.choice(unique_groups, size=len(unique_groups), replace=True)
        sample_indices = np.concatenate([group_to_indices[group] for group in sampled_groups])
        model = Ridge(alpha=alpha)
        model.fit(x_np[sample_indices], y_np[sample_indices])
        coefs = model.coef_
        for feature, columns in feature_to_columns.items():
            idxs = [col_index[col] for col in columns if col in col_index]
            if not idxs:
                continue
            values = coefs[idxs]
            selected_by_feature[feature].append(int(np.any(np.abs(values) > 0.01)))
            single = numeric_feature_single_col.get(feature)
            if single and single in col_index:
                coef_by_feature[feature].append(float(coefs[col_index[single]]))
            else:
                coef_by_feature[feature].append(float(np.linalg.norm(values, ord=2)))

    rows = []
    full_model = Ridge(alpha=alpha)
    full_model.fit(x_np, y_np)
    full_coefs = full_model.coef_
    for feature, columns in feature_to_columns.items():
        idxs = [col_index[col] for col in columns if col in col_index]
        if not idxs:
            continue
        full_values = full_coefs[idxs]
        boot_values = np.asarray(coef_by_feature.get(feature, []), dtype=float)
        selected = np.asarray(selected_by_feature.get(feature, []), dtype=float)
        full_coef = float(full_values[0]) if len(full_values) and columns[0].endswith("__z") else float(np.linalg.norm(full_values, ord=2))
        sign_p = math.nan
        ci_low = math.nan
        ci_high = math.nan
        if len(boot_values):
            ci_low = float(np.quantile(boot_values, 0.025))
            ci_high = float(np.quantile(boot_values, 0.975))
            if columns[0].endswith("__z"):
                pos = float(np.mean(boot_values >= 0.0))
                neg = float(np.mean(boot_values <= 0.0))
                sign_p = min(1.0, 2.0 * min(pos, neg))
        rows.append(
            {
                "feature": feature,
                "family": feature_family(feature),
                "elastic_net_full_coef_or_l2": full_coef,
                "bootstrap_coef_ci_low": ci_low,
                "bootstrap_coef_ci_high": ci_high,
                "bootstrap_sign_p": sign_p,
                "selection_frequency": float(np.mean(selected)) if len(selected) else math.nan,
                "n_encoded_columns": len(idxs),
                "alpha": alpha,
                "regularized_model": "ridge",
            }
        )
    result = pd.DataFrame(rows)
    if not result.empty:
        result["bootstrap_sign_q"] = fdr_bh(result["bootstrap_sign_p"])
    metrics = {
        "regularized_model": "ridge",
        "ridge_alpha": alpha,
        "cv_mae_mean": float(np.mean([m["mae"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_r2_mean": float(np.mean([m["r2"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_folds": cv_metrics,
    }
    return result, metrics


def ridge_coefficient_analysis(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    feature_to_columns: dict[str, list[str]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if X.empty:
        return pd.DataFrame(), {}
    x_np = X.to_numpy(dtype=float)
    y_np = y.to_numpy(dtype=float)
    splits = grouped_cv_splits(groups, max_splits=5)
    cv_metrics = []
    coefs_by_fold = []
    for train_idx, test_idx in splits:
        model = Ridge(alpha=10.0)
        model.fit(x_np[train_idx], y_np[train_idx])
        preds = model.predict(x_np[test_idx])
        cv_metrics.append(
            {
                "mae": float(mean_absolute_error(y_np[test_idx], preds)),
                "r2": float(r2_score(y_np[test_idx], preds)),
            }
        )
        coefs_by_fold.append(model.coef_)
    full_model = Ridge(alpha=10.0)
    full_model.fit(x_np, y_np)
    col_index = {column: i for i, column in enumerate(X.columns)}
    rows = []
    for feature, columns in feature_to_columns.items():
        idxs = [col_index[col] for col in columns if col in col_index]
        if not idxs:
            continue
        full_values = full_model.coef_[idxs]
        fold_scores = []
        for coefs in coefs_by_fold:
            values = coefs[idxs]
            score = float(values[0]) if columns[0].endswith("__z") else float(np.linalg.norm(values, ord=2))
            fold_scores.append(score)
        rows.append(
            {
                "feature": feature,
                "family": feature_family(feature),
                "ridge_full_coef_or_l2": float(full_values[0]) if columns[0].endswith("__z") else float(np.linalg.norm(full_values, ord=2)),
                "ridge_fold_mean_coef_or_l2": float(np.mean(fold_scores)) if fold_scores else math.nan,
                "ridge_fold_sd": float(np.std(fold_scores, ddof=1)) if len(fold_scores) > 1 else math.nan,
                "n_encoded_columns": len(idxs),
            }
        )
    metrics = {
        "ridge_alpha": 10.0,
        "cv_mae_mean": float(np.mean([m["mae"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_r2_mean": float(np.mean([m["r2"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_folds": cv_metrics,
    }
    return pd.DataFrame(rows), metrics


def hgb_permutation_analysis(
    X: pd.DataFrame,
    y: pd.Series,
    groups: pd.Series,
    feature_to_columns: dict[str, list[str]],
    features: list[str],
    label: str,
    include_variable_importance: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if X.empty:
        return pd.DataFrame(), pd.DataFrame(), {}
    x_np = X.to_numpy(dtype=float)
    y_np = y.to_numpy(dtype=float)
    col_index = {column: i for i, column in enumerate(X.columns)}
    rng = np.random.default_rng(RANDOM_SEED)
    splits = grouped_cv_splits(groups, max_splits=5)
    variable_deltas: dict[str, list[float]] = defaultdict(list)
    family_deltas: dict[str, list[float]] = defaultdict(list)
    cv_metrics = []

    family_to_features: dict[str, list[str]] = defaultdict(list)
    for feature in features:
        family_to_features[feature_family(feature)].append(feature)

    for fold_id, (train_idx, test_idx) in enumerate(splits):
        model = HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=HGB_MAX_ITER,
            max_leaf_nodes=31,
            l2_regularization=0.05,
            random_state=RANDOM_SEED + fold_id,
        )
        model.fit(x_np[train_idx], y_np[train_idx])
        baseline_preds = model.predict(x_np[test_idx])
        baseline_mae = mean_absolute_error(y_np[test_idx], baseline_preds)
        baseline_r2 = r2_score(y_np[test_idx], baseline_preds)
        cv_metrics.append({"mae": float(baseline_mae), "r2": float(baseline_r2), "n_test": int(len(test_idx))})
        x_val = x_np[test_idx]
        if include_variable_importance:
            for feature in features:
                cols = [col_index[col] for col in feature_to_columns.get(feature, []) if col in col_index]
                if not cols:
                    continue
                for _ in range(PERM_REPEATS):
                    permuted = x_val.copy()
                    order = rng.permutation(permuted.shape[0])
                    permuted[:, cols] = permuted[order][:, cols]
                    preds = model.predict(permuted)
                    variable_deltas[feature].append(float(mean_absolute_error(y_np[test_idx], preds) - baseline_mae))
        for family, family_features in family_to_features.items():
            cols = [
                col_index[col]
                for feature in family_features
                for col in feature_to_columns.get(feature, [])
                if col in col_index
            ]
            if not cols:
                continue
            for _ in range(PERM_REPEATS):
                permuted = x_val.copy()
                order = rng.permutation(permuted.shape[0])
                permuted[:, cols] = permuted[order][:, cols]
                preds = model.predict(permuted)
                family_deltas[family].append(float(mean_absolute_error(y_np[test_idx], preds) - baseline_mae))

    variable_rows = []
    for feature, deltas in variable_deltas.items():
        arr = np.asarray(deltas, dtype=float)
        p = math.nan
        if len(arr) > 1 and np.std(arr) > 1e-12:
            try:
                p = float(stats.ttest_1samp(arr, 0.0, alternative="greater").pvalue)
            except TypeError:
                t_stat, two_sided = stats.ttest_1samp(arr, 0.0)
                p = float(two_sided / 2.0 if t_stat > 0 else 1.0 - two_sided / 2.0)
        variable_rows.append(
            {
                "slice": label,
                "feature": feature,
                "family": feature_family(feature),
                "hgb_delta_mae_mean": float(np.mean(arr)),
                "hgb_delta_mae_sd": float(np.std(arr, ddof=1)) if len(arr) > 1 else math.nan,
                "hgb_delta_mae_ci_low": float(np.quantile(arr, 0.025)),
                "hgb_delta_mae_ci_high": float(np.quantile(arr, 0.975)),
                "hgb_importance_p": p,
                "n_permutations": int(len(arr)),
            }
        )
    variable_result = pd.DataFrame(variable_rows)
    if not variable_result.empty:
        variable_result["hgb_importance_q"] = fdr_bh(variable_result["hgb_importance_p"])

    family_rows = []
    for family, deltas in family_deltas.items():
        arr = np.asarray(deltas, dtype=float)
        p = math.nan
        if len(arr) > 1 and np.std(arr) > 1e-12:
            try:
                p = float(stats.ttest_1samp(arr, 0.0, alternative="greater").pvalue)
            except TypeError:
                t_stat, two_sided = stats.ttest_1samp(arr, 0.0)
                p = float(two_sided / 2.0 if t_stat > 0 else 1.0 - two_sided / 2.0)
        family_rows.append(
            {
                "slice": label,
                "family": family,
                "hgb_delta_mae_mean": float(np.mean(arr)),
                "hgb_delta_mae_sd": float(np.std(arr, ddof=1)) if len(arr) > 1 else math.nan,
                "hgb_delta_mae_ci_low": float(np.quantile(arr, 0.025)),
                "hgb_delta_mae_ci_high": float(np.quantile(arr, 0.975)),
                "hgb_importance_p": p,
                "n_permutations": int(len(arr)),
                "n_features": int(len(family_to_features[family])),
            }
        )
    family_result = pd.DataFrame(family_rows)
    if not family_result.empty:
        family_result["hgb_importance_q"] = fdr_bh(family_result["hgb_importance_p"])
    metrics = {
        "slice": label,
        "cv_mae_mean": float(np.mean([m["mae"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_r2_mean": float(np.mean([m["r2"] for m in cv_metrics])) if cv_metrics else math.nan,
        "cv_folds": cv_metrics,
    }
    return variable_result, family_result, metrics


def consensus_summary(
    coverage: pd.DataFrame,
    univariate: pd.DataFrame,
    linear: pd.DataFrame,
    ridge: pd.DataFrame,
    permutation: pd.DataFrame,
) -> pd.DataFrame:
    summary = coverage.copy()
    all_uni = univariate[univariate["slice"].eq("all")].copy() if not univariate.empty else pd.DataFrame()
    if not all_uni.empty:
        all_uni["univariate_abs_daily_r"] = all_uni["daily_latest_pearson_r"].abs()
        summary = summary.merge(
            all_uni[
                [
                    "feature",
                    "daily_latest_pearson_r",
                    "daily_latest_spearman_r",
                    "cluster_bootstrap_sign_p",
                    "cluster_bootstrap_sign_q",
                    "univariate_abs_daily_r",
                ]
            ],
            on="feature",
            how="left",
        )
    if not linear.empty:
        linear = linear.copy()
        linear["linear_abs_coef"] = linear["elastic_net_full_coef_or_l2"].abs()
        summary = summary.merge(
            linear[
                [
                    "feature",
                    "elastic_net_full_coef_or_l2",
                    "bootstrap_sign_p",
                    "bootstrap_sign_q",
                    "selection_frequency",
                    "linear_abs_coef",
                ]
            ],
            on="feature",
            how="left",
        )
    if not ridge.empty:
        ridge = ridge.copy()
        ridge["ridge_abs_coef"] = ridge["ridge_full_coef_or_l2"].abs()
        summary = summary.merge(
            ridge[["feature", "ridge_full_coef_or_l2", "ridge_fold_mean_coef_or_l2", "ridge_abs_coef"]],
            on="feature",
            how="left",
        )
    all_perm = permutation[permutation["slice"].eq("all")].copy() if not permutation.empty else pd.DataFrame()
    if not all_perm.empty:
        summary = summary.merge(
            all_perm[["feature", "hgb_delta_mae_mean", "hgb_importance_p", "hgb_importance_q"]],
            on="feature",
            how="left",
        )

    rank_columns = []
    for metric, ascending in [
        ("univariate_abs_daily_r", False),
        ("linear_abs_coef", False),
        ("ridge_abs_coef", False),
        ("hgb_delta_mae_mean", False),
        ("selection_frequency", False),
    ]:
        if metric in summary.columns:
            rank_col = f"{metric}_rank"
            summary[rank_col] = summary[metric].rank(ascending=ascending, na_option="bottom", method="average")
            rank_columns.append(rank_col)
    if rank_columns:
        summary["consensus_rank_score"] = summary[rank_columns].mean(axis=1)
    else:
        summary["consensus_rank_score"] = math.nan
    summary["consensus_tier"] = pd.cut(
        summary["consensus_rank_score"].rank(method="first"),
        bins=[0, 10, 25, 50, np.inf],
        labels=["top_10", "top_25", "top_50", "lower"],
    ).astype("string")
    return summary.sort_values(["consensus_rank_score", "feature"], na_position="last")


def fmt(value: Any, digits: int = 4) -> str:
    try:
        if value is None or not np.isfinite(float(value)):
            return "NA"
        return f"{float(value):.{digits}g}"
    except Exception:
        return str(value)


def markdown_table(frame: pd.DataFrame, columns: list[str], limit: int = 15) -> str:
    if frame.empty:
        return "_No rows._"
    subset = frame.loc[:, columns].head(limit).copy()
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for _, row in subset.iterrows():
        values = [fmt(row[col]) if isinstance(row[col], (float, int, np.floating, np.integer)) else str(row[col]) for col in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(
    output_dir: Path,
    prefix: str,
    data: pd.DataFrame,
    load_log: pd.DataFrame,
    coverage: pd.DataFrame,
    univariate: pd.DataFrame,
    linear: pd.DataFrame,
    ridge: pd.DataFrame,
    permutation: pd.DataFrame,
    families: pd.DataFrame,
    summary: pd.DataFrame,
    metrics: dict[str, Any],
) -> Path:
    report_path = output_dir / f"{prefix}_report.md"
    top_summary = summary[summary["analyzable"]].copy()
    top_summary = top_summary.sort_values(["consensus_rank_score", "feature"]).head(20)
    top_hgb = permutation[permutation["slice"].eq("all")].sort_values("hgb_delta_mae_mean", ascending=False).head(15)
    top_family = families[families["slice"].eq("all")].sort_values("hgb_delta_mae_mean", ascending=False)
    early_uni = univariate[univariate["slice"].eq("early")].copy()
    if not early_uni.empty:
        early_uni["abs_r"] = early_uni["daily_latest_pearson_r"].abs()
        early_uni = early_uni.sort_values(["abs_r", "cluster_bootstrap_sign_p"], ascending=[False, True]).head(12)

    loaded = load_log["status"].value_counts(dropna=False).to_dict() if not load_log.empty else {}
    feature_sources = load_log["feature_source"].value_counts(dropna=False).to_dict() if not load_log.empty else {}
    day_count = int(data["market_day"].nunique())
    market_count = int(data["market_id"].nunique())
    row_count = int(len(data))
    excluded = load_log[load_log["rows"].eq(0)] if not load_log.empty else pd.DataFrame()
    malformed = load_log[load_log["feature_source"].str.contains("skip|unreadable", na=False)] if not load_log.empty else pd.DataFrame()

    lines = [
        "# Input Variable Significance Analysis",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Corpus",
        "",
        f"- Settled feature rows analyzed: {row_count:,}",
        f"- Matched market-days analyzed: {day_count:,}",
        f"- Markets analyzed: {market_count:,}",
        f"- Feature variables considered: {len(coverage):,}; analyzable after coverage/variation filters: {int(coverage['analyzable'].sum()):,}",
        f"- Load statuses: `{json.dumps(loaded, sort_keys=True)}`",
        f"- Feature sources: `{json.dumps(feature_sources, sort_keys=True)}`",
        "",
        "Rows are clustered by `market_day`; row-level p-values are included only as a naive diagnostic. The report emphasizes day-level latest-snapshot associations, market-day bootstrap intervals, and grouped cross-validation.",
        "",
        "## Method Summary",
        "",
        "- Univariate: within-market standardized feature values vs within-market standardized settlement high, with row-level Pearson/Spearman, latest-row-per-market-day tests, and market-day bootstrap sign p-values.",
        "- Linear: ridge regression with grouped CV, plus market-day bootstrap coefficient sign p-values and thresholded stability frequency. A second ridge fold check is included for coefficient stability.",
        "- Nonlinear: HistGradientBoostingRegressor with GroupKFold by market-day and grouped permutation importance; p-values are one-sided t-tests over fold/repeat permutation deltas.",
        "- Families: HGB permutation of all encoded variables in each feature family.",
        "",
        "## Top Consensus Variables",
        "",
        markdown_table(
            top_summary,
            [
                "feature",
                "family",
                "row_coverage",
                "daily_latest_pearson_r",
                "cluster_bootstrap_sign_q",
                "selection_frequency",
                "hgb_delta_mae_mean",
                "hgb_importance_q",
                "consensus_tier",
            ],
            limit=20,
        ),
        "",
        "## Nonlinear Permutation Importance",
        "",
        markdown_table(
            top_hgb,
            [
                "feature",
                "family",
                "hgb_delta_mae_mean",
                "hgb_delta_mae_ci_low",
                "hgb_delta_mae_ci_high",
                "hgb_importance_q",
            ],
            limit=15,
        ),
        "",
        "## Family Importance",
        "",
        markdown_table(
            top_family,
            [
                "family",
                "hgb_delta_mae_mean",
                "hgb_delta_mae_ci_low",
                "hgb_delta_mae_ci_high",
                "hgb_importance_q",
                "n_features",
            ],
            limit=20,
        ),
        "",
        "## Early-Day Associations",
        "",
        "This slice matters for tuning because late-day observation-path variables are expected to dominate once the realized high has mostly occurred.",
        "",
        markdown_table(
            early_uni,
            [
                "feature",
                "family",
                "n_days",
                "daily_latest_pearson_r",
                "cluster_bootstrap_pearson_ci_low",
                "cluster_bootstrap_pearson_ci_high",
                "cluster_bootstrap_sign_q",
            ],
            limit=12,
        ),
        "",
        "## Model Fit Diagnostics",
        "",
        f"- Regularized linear grouped-CV MAE/R2: {fmt(metrics.get('elastic_net', {}).get('cv_mae_mean'))} / {fmt(metrics.get('elastic_net', {}).get('cv_r2_mean'))}",
        f"- Ridge grouped-CV MAE/R2: {fmt(metrics.get('ridge', {}).get('cv_mae_mean'))} / {fmt(metrics.get('ridge', {}).get('cv_r2_mean'))}",
        f"- HGB all-row grouped-CV MAE/R2: {fmt(metrics.get('hgb_all', {}).get('cv_mae_mean'))} / {fmt(metrics.get('hgb_all', {}).get('cv_r2_mean'))}",
        "",
        "## Data Quality Notes",
        "",
    ]
    if not malformed.empty:
        lines.append(f"- Malformed feature CSV fallbacks/skips recorded for {len(malformed)} folders. The primary loader prefers `features.jsonl`, which avoided the June 8 schema-width issue when present.")
    if not excluded.empty:
        excluded_status = excluded["status"].value_counts(dropna=False).to_dict()
        lines.append(f"- Excluded/unusable folders: `{json.dumps(excluded_status, sort_keys=True)}`")
    sparse = coverage[(coverage["row_coverage"] > 0) & (~coverage["analyzable"])].sort_values("row_coverage", ascending=False).head(15)
    if not sparse.empty:
        lines.append("- Highest-coverage variables not analyzed because of insufficient within-market variation or days:")
        lines.append("")
        lines.append(markdown_table(sparse, ["feature", "family", "row_coverage", "n_days_non_missing", "n_unique_raw"], limit=15))
    lines.extend(
        [
            "",
            "## Tuning Implications",
            "",
            "- Treat observed temperature path and time-context variables as baseline state. They are strongly significant, especially late day, but they should not be allowed to mask early-day forecast skill.",
            "- Prioritize features that survive both early-day univariate tests and grouped permutation importance; these are more likely to help before the market has learned the day from observations.",
            "- Features with sparse coverage but strong family-level importance should be promoted only through blocked replay, because their apparent value can be a source-availability proxy.",
            "- Use family ablation/permutation as the safer gate for highly collinear forecast profile variables; individual p-values inside the same forecast family are unstable.",
            "",
            "## Output Files",
            "",
            f"- `{prefix}_variable_summary.csv`",
            f"- `{prefix}_univariate.csv`",
            f"- `{prefix}_linear_bootstrap.csv`",
            f"- `{prefix}_ridge.csv`",
            f"- `{prefix}_hgb_permutation.csv`",
            f"- `{prefix}_family_permutation.csv`",
            f"- `{prefix}_coverage.csv`",
            f"- `{prefix}_metadata.json`",
            f"- `{prefix}_top_importance.png`",
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def write_plot(output_dir: Path, prefix: str, summary: pd.DataFrame, families: pd.DataFrame) -> Path:
    path = output_dir / f"{prefix}_top_importance.png"
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))

    top_vars = summary.sort_values("consensus_rank_score").head(15).iloc[::-1]
    axes[0].barh(top_vars["feature"], top_vars.get("hgb_delta_mae_mean", pd.Series(np.nan, index=top_vars.index)).fillna(0.0))
    axes[0].set_title("Top variables by HGB permutation delta MAE")
    axes[0].set_xlabel("Delta MAE in target z")

    top_families = families[families["slice"].eq("all")].sort_values("hgb_delta_mae_mean", ascending=False).head(12).iloc[::-1]
    axes[1].barh(top_families["family"], top_families["hgb_delta_mae_mean"])
    axes[1].set_title("Feature-family permutation importance")
    axes[1].set_xlabel("Delta MAE in target z")

    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main() -> int:
    args = parse_args()
    global BOOTSTRAPS, PERM_REPEATS, HGB_MAX_ITER
    BOOTSTRAPS = max(20, int(args.bootstraps))
    PERM_REPEATS = max(1, int(args.perm_repeats))
    HGB_MAX_ITER = max(50, int(args.hgb_max_iter))
    snapshots_root = Path(args.snapshots_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Loading settled feature corpus...", flush=True)
    data, load_log = load_dataset(snapshots_root, include_mismatches=args.include_mismatches)
    if data.empty:
        raise SystemExit("No analyzable settled feature rows found.")

    print(f"Loaded {len(data):,} rows across {data['market_day'].nunique():,} market-days.", flush=True)
    data = add_standardized_target(data)
    features = candidate_features(data, include_diagnostics=args.include_diagnostics)
    numeric_frame, numeric, categorical = numeric_feature_frame(data, features)
    z_frame = within_market_z(data, numeric_frame)
    coverage = coverage_table(data, numeric_frame, z_frame, categorical)

    print("Running univariate/day-level significance tests...", flush=True)
    univariate = univariate_analysis(data, z_frame, categorical, coverage)
    ml_features = select_ml_features(coverage, args.max_hgb_features)
    print(f"Building grouped ML matrix with {len(ml_features)} features...", flush=True)
    ml_categorical = [feature for feature in categorical if feature in ml_features]
    X, feature_to_columns = build_ml_matrix(data, z_frame, ml_features, ml_categorical)
    y = data["target_market_z"].astype(float)
    valid_y = y.notna()
    X = X.loc[valid_y]
    y = y.loc[valid_y]
    groups = data.loc[valid_y, "market_day"]

    print("Running regularized linear bootstrap...", flush=True)
    linear, linear_metrics = linear_bootstrap_analysis(data.loc[valid_y], X, y, groups, feature_to_columns)
    print("Running ridge coefficient check...", flush=True)
    ridge, ridge_metrics = ridge_coefficient_analysis(X, y, groups, feature_to_columns)
    print("Running all-row HGB permutation importance...", flush=True)
    hgb_perm, family_perm, hgb_metrics = hgb_permutation_analysis(X, y, groups, feature_to_columns, ml_features, "all")

    family_slice_frames = [family_perm]
    hgb_slice_metrics = {"all": hgb_metrics}
    for slice_name in ["early", "midday", "late"]:
        mask = data.loc[valid_y, "time_slice"].eq(slice_name)
        if int(mask.sum()) < 500 or groups.loc[mask].nunique() < 20:
            continue
        print(f"Running {slice_name} family-level HGB permutation...", flush=True)
        _, family_slice, metrics = hgb_permutation_analysis(
            X.loc[mask],
            y.loc[mask],
            groups.loc[mask],
            feature_to_columns,
            ml_features,
            slice_name,
            include_variable_importance=False,
        )
        family_slice_frames.append(family_slice)
        hgb_slice_metrics[slice_name] = metrics
    family_perm = pd.concat([frame for frame in family_slice_frames if not frame.empty], ignore_index=True)

    print("Writing analysis artifacts...", flush=True)
    summary = consensus_summary(coverage, univariate, linear, ridge, hgb_perm)

    prefix = args.prefix
    coverage.to_csv(output_dir / f"{prefix}_coverage.csv", index=False)
    load_log.to_csv(output_dir / f"{prefix}_load_log.csv", index=False)
    univariate.to_csv(output_dir / f"{prefix}_univariate.csv", index=False)
    linear.to_csv(output_dir / f"{prefix}_linear_bootstrap.csv", index=False)
    ridge.to_csv(output_dir / f"{prefix}_ridge.csv", index=False)
    hgb_perm.to_csv(output_dir / f"{prefix}_hgb_permutation.csv", index=False)
    family_perm.to_csv(output_dir / f"{prefix}_family_permutation.csv", index=False)
    summary.to_csv(output_dir / f"{prefix}_variable_summary.csv", index=False)

    metrics = {
        "rows": int(len(data)),
        "market_days": int(data["market_day"].nunique()),
        "markets": int(data["market_id"].nunique()),
        "features_considered": int(len(coverage)),
        "features_analyzable": int(coverage["analyzable"].sum()),
        "ml_features": ml_features,
        "elastic_net": linear_metrics,
        "ridge": ridge_metrics,
        "hgb_all": hgb_metrics,
        "hgb_slices": hgb_slice_metrics,
    }
    (output_dir / f"{prefix}_metadata.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    plot_path = write_plot(output_dir, prefix, summary, family_perm)
    report_path = write_report(
        output_dir,
        prefix,
        data,
        load_log,
        coverage,
        univariate,
        linear,
        ridge,
        hgb_perm,
        family_perm,
        summary,
        metrics,
    )

    print(f"Wrote {report_path}")
    print(f"Wrote {plot_path}")
    print(f"Rows={len(data):,} market_days={data['market_day'].nunique():,} analyzable_features={int(coverage['analyzable'].sum()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
