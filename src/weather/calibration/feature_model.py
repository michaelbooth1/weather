import json
import math
import os
import pickle
import numpy as np
import pandas as pd
from datetime import date, datetime
from collections import Counter, defaultdict

from weather.artifacts import writable_artifact_path
from weather.calibration.feature_probability_calibration import (
    fit_temperature_blend_grid,
    temperature_scale_distribution,
)
from weather.model.feature_store import (
    FEATURE_COLUMNS,
    FEATURE_SCHEMA_VERSION,
    FORECAST_FEATURE_COLUMNS,
    NATIVE_NAN_FEATURE_COLUMNS,
    build_historical_feature_record,
    closest_wind_direction,
    row_dewpoint_native,
    row_temp_native,
    row_value,
    row_wind_direction,
    wind_direction_delta_degrees,
)
from weather.model.toronto_model import INTRADAY_CUTOFF_HOURS, TorontoHighTempModel
from weather.sources.forecast_history import (
    daily_path_for,
    load_forecast_daily,
    load_forecast_profiles,
    long_path_for,
)

# LOO must stay ON: without it the retrain exports artifacts with no
# validation report AND flat 0.80 blend weights (the per-hour tuning only runs
# inside the LOO loop). The 2026-06-08 retrain ran with this False and shipped
# the 45-year model unvalidated -- the 2026-06-09 audit's finding #6.
RUN_LOO = True
FEATURE_MODEL_COEFS_SCHEMA_VERSION = "feature_model_coefs_v0.1"
FEATURE_MODEL_HGB_SCHEMA_VERSION = "feature_model_hgb_v0.2"
LATE_DAY_MODEL_SCHEMA_VERSION = "late_day_model_coefs_v0.1"

# Intra-hour wall offsets (item 40). Each (day, cutoff hour) trains at ONE
# deterministic offset, rotated across days, so the live-reading features see a
# spread of "minutes past the printed cutoff" without multiplying the O(n^2) LOO
# row count.
#
# Item-40 extension (2026-06-13): the afternoon ramp/peak cutoff hours serve at a
# much larger minutes_since_cutoff than the base offsets covered. When WU history
# print-lags through the 13-15h climb, the effective (last-printed) cutoff trails
# wall clock -- a frozen-corpus probe measured minutes_since_cutoff of 48-100 min
# at wall 13-14h on 2026-06-11, far outside the trained {0,15,30,45} range. The
# HGB was extrapolating on the exact feature meant to handle print-lag, so it
# under-committed to the bucket the live reading had already reached (the measured
# 13-14h winner under-call). The RAMP cutoff hours now sample offsets out to
# 105 min so the model LEARNS that regime. Morning hours (the model already beats
# the market there) and the 15h+ lock-in window keep the base offsets unchanged,
# so this cannot regress them by construction.
BASE_WALL_OFFSETS = (0, 15, 30, 45)
RAMP_WALL_OFFSETS = (0, 15, 30, 45, 60, 75, 90, 105)
RAMP_CUTOFF_HOURS = (12, 13, 14)


def wall_offset_for(local_date, hour):
    """Deterministic intra-hour wall offset (minutes past the printed cutoff)
    for one (day, cutoff hour). Afternoon ramp hours sample the extended offset
    set to cover the print-lag serving range; all other hours keep the base set,
    leaving their trained behavior byte-identical."""
    offsets = RAMP_WALL_OFFSETS if hour in RAMP_CUTOFF_HOURS else BASE_WALL_OFFSETS
    return offsets[(local_date.toordinal() + hour) % len(offsets)]

# We will use scikit-learn models
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

def round_half_up(value):
    if value is None:
        return None
    return int(math.floor(float(value) + 0.5))

def get_minute_of_day(time_str):
    try:
        h, m = time_str.split(":")
        return int(h) * 60 + int(m)
    except:
        return None

def smoothed_dist(buckets, support, alpha=0.10):
    counts = Counter(int(b) for b in buckets)
    denominator = len(buckets) + alpha * len(support)
    return {
        s: (counts.get(s, 0) + alpha) / denominator
        for s in support
    }

def blend(scores, p_blend, weight):
    if not p_blend or weight <= 0:
        return scores
    weight = min(1.0, max(0.0, weight))
    keys = set(scores.keys()) | set(p_blend.keys())
    blended = {}
    for k in keys:
        current_val = scores.get(k, 0.0)
        blend_val = float(p_blend.get(k, 0.0))
        blended[k] = (1.0 - weight) * current_val + weight * blend_val
    # normalize
    total = sum(blended.values())
    if total <= 0:
        return scores
    return {k: v / total for k, v in blended.items()}

def log_loss(prob_dict, actual_bucket):
    p = prob_dict.get(actual_bucket, 0.0)
    p = max(1e-15, min(1.0 - 1e-15, p))
    return -math.log(p)

def brier_score(prob_dict, actual_bucket):
    score = 0.0
    for k, v in prob_dict.items():
        y = 1.0 if k == actual_bucket else 0.0
        score += (v - y) ** 2
    return score

def expected_calibration_error(conf_correct, n_bins=10):
    """ECE over the predicted top-class confidence: how far the model's stated
    confidence is from its realized accuracy. 0 = perfectly calibrated."""
    if not conf_correct:
        return 0.0
    bins = [[] for _ in range(n_bins)]
    for conf, correct in conf_correct:
        idx = min(n_bins - 1, int(conf * n_bins))
        bins[idx].append((conf, correct))
    n = len(conf_correct)
    ece = 0.0
    for b in bins:
        if not b:
            continue
        avg_conf = sum(c for c, _ in b) / len(b)
        acc = sum(k for _, k in b) / len(b)
        ece += (len(b) / n) * abs(acc - avg_conf)
    return ece


FEATURE_FAMILIES = {
    "observed_temp_path": ["high_so_far", "current_temp", "rise_from_7am"],
    "atmosphere": [
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
        "wind_gust_kmh",
        "wind_shift_3h_degrees",
    ],
    "microclimate": [
        "onshore_flow",
        "onshore_wind_speed_kmh",
        "lake_breeze_proxy",
    ],
    "forecast": [
        *FORECAST_FEATURE_COLUMNS,
    ],
    "wind_regime": "wind_",
    "cloud_regime": "cloud_",
}

LATE_DAY_NUMERIC_FEATURES = [
    "time_since_reached",
    "high_so_far",
    "current_temp",
    "rise_from_7am",
    "dewpoint_c",
    "humidity",
    "pressure",
    "pressure_trend_3h",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_shift_3h_degrees",
    "forecast_high",
    "forecast_gap",
]

WIND_GROUPS = ["E-SE/onshore-ish", "S-SW", "W-NW", "N-NE", "SSE", "Other/variable"]
CLOUD_GROUPS = ["Precip", "Fog/haze", "Fair/clear", "Partly cloudy", "Mostly cloudy/overcast", "Other"]


def late_day_feature_columns(all_wind_groups, all_cloud_groups):
    return (
        list(LATE_DAY_NUMERIC_FEATURES)
        + [f"wind_{g}" for g in all_wind_groups]
        + [f"cloud_{g}" for g in all_cloud_groups]
    )


def binary_log_loss(probs, y):
    if len(probs) == 0:
        return None
    losses = []
    for prob, actual in zip(probs, y):
        p = min(1.0 - 1e-15, max(1e-15, float(prob)))
        losses.append(-(actual * math.log(p) + (1.0 - actual) * math.log(1.0 - p)))
    return float(np.mean(losses))


def binary_brier(probs, y):
    if len(probs) == 0:
        return None
    return float(np.mean([(float(prob) - float(actual)) ** 2 for prob, actual in zip(probs, y)]))


def binary_ece(probs, y, n_bins=10):
    if len(probs) == 0:
        return None
    bins = [[] for _ in range(n_bins)]
    for prob, actual in zip(probs, y):
        p = min(1.0, max(0.0, float(prob)))
        idx = min(n_bins - 1, int(p * n_bins))
        bins[idx].append((p, float(actual)))
    ece = 0.0
    n = len(probs)
    for bucket in bins:
        if not bucket:
            continue
        avg_p = sum(prob for prob, _ in bucket) / len(bucket)
        avg_y = sum(actual for _, actual in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(avg_p - avg_y)
    return float(ece)


def _predict_binary_lr(model, matrix):
    classes = list(model.classes_)
    if 1 in classes:
        return model.predict_proba(matrix)[:, classes.index(1)]
    return np.zeros(matrix.shape[0])


def _constant_probs(value, n):
    p = min(1.0 - 1e-15, max(1e-15, float(value)))
    return np.full(n, p)


def _late_day_validation_folds(ld_df, n_splits=5):
    if "date_ordinal" not in ld_df or len(ld_df) < 2:
        return [np.arange(len(ld_df))]
    max_splits = max(2, min(n_splits, len(ld_df)))
    folds = []
    for fold in range(max_splits):
        idx = np.flatnonzero((ld_df["date_ordinal"].astype(int).to_numpy() % max_splits) == fold)
        if len(idx):
            folds.append(idx)
    return folds or [np.arange(len(ld_df))]


def evaluate_late_day_records(ld_df, feature_cols, numeric_feature_count, n_splits=5):
    if ld_df.empty:
        return None, []
    X = ld_df[feature_cols].to_numpy(dtype=float)
    y = ld_df["is_extended"].to_numpy(dtype=float)
    if len(y) < 2:
        prior = float(np.mean(y)) if len(y) else 0.0
        probs = _constant_probs(prior, len(y))
        summary = {
            "n": int(len(y)),
            "event_rate": prior,
            "logloss": binary_log_loss(probs, y),
            "brier": binary_brier(probs, y),
            "ece": binary_ece(probs, y),
        }
        return summary, []

    full_probs = np.full(len(y), np.nan)
    ablated = {family: np.full(len(y), np.nan) for family in feature_family_columns(feature_cols)}
    folds = _late_day_validation_folds(ld_df, n_splits=n_splits)
    for val_idx in folds:
        train_idx = np.setdiff1d(np.arange(len(y)), val_idx)
        if len(train_idx) == 0:
            train_idx = val_idx
        X_train = X[train_idx]
        y_train = y[train_idx]
        X_val = X[val_idx]

        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        X_train_imp = imputer.fit_transform(X_train)
        X_val_imp = imputer.transform(X_val)
        scaler = StandardScaler()
        X_train_scaled = X_train_imp.copy()
        X_val_scaled = X_val_imp.copy()
        X_train_scaled[:, :numeric_feature_count] = scaler.fit_transform(
            X_train_imp[:, :numeric_feature_count]
        )
        X_val_scaled[:, :numeric_feature_count] = scaler.transform(
            X_val_imp[:, :numeric_feature_count]
        )

        if len(np.unique(y_train)) > 1:
            lr = LogisticRegression(max_iter=1000, C=0.5, random_state=42)
            lr.fit(X_train_scaled, y_train)
            full_probs[val_idx] = _predict_binary_lr(lr, X_val_scaled)
            families = feature_family_columns(feature_cols)
            for family, columns in families.items():
                X_val_ablated = np.vstack([
                    neutralize_feature_family(row.copy(), X_train, feature_cols, columns)
                    for row in X_val
                ])
                X_val_ablated_imp = imputer.transform(X_val_ablated)
                X_val_ablated_scaled = X_val_ablated_imp.copy()
                X_val_ablated_scaled[:, :numeric_feature_count] = scaler.transform(
                    X_val_ablated_imp[:, :numeric_feature_count]
                )
                ablated[family][val_idx] = _predict_binary_lr(lr, X_val_ablated_scaled)
        else:
            prior = float(np.mean(y_train))
            full_probs[val_idx] = _constant_probs(prior, len(val_idx))
            for family in ablated:
                ablated[family][val_idx] = full_probs[val_idx]

    valid = ~np.isnan(full_probs)
    summary = {
        "n": int(np.sum(valid)),
        "event_rate": float(np.mean(y[valid])) if np.any(valid) else None,
        "logloss": binary_log_loss(full_probs[valid], y[valid]),
        "brier": binary_brier(full_probs[valid], y[valid]),
        "ece": binary_ece(full_probs[valid], y[valid]),
    }
    ablation_rows = []
    for family, probs in ablated.items():
        valid_family = valid & ~np.isnan(probs)
        if not np.any(valid_family):
            continue
        full_logloss = binary_log_loss(full_probs[valid_family], y[valid_family])
        ablated_logloss = binary_log_loss(probs[valid_family], y[valid_family])
        full_brier = binary_brier(full_probs[valid_family], y[valid_family])
        ablated_brier = binary_brier(probs[valid_family], y[valid_family])
        ablation_rows.append({
            "family": family,
            "n": int(np.sum(valid_family)),
            "full_logloss": full_logloss,
            "ablated_logloss": ablated_logloss,
            "delta_logloss": ablated_logloss - full_logloss,
            "full_brier": full_brier,
            "ablated_brier": ablated_brier,
            "delta_brier": ablated_brier - full_brier,
        })
    return summary, sorted(ablation_rows, key=lambda row: row["delta_logloss"], reverse=True)


def feature_family_columns(feature_cols):
    families = {}
    for family, spec in FEATURE_FAMILIES.items():
        if isinstance(spec, str):
            columns = [column for column in feature_cols if column.startswith(spec)]
        else:
            columns = [column for column in spec if column in feature_cols]
        if columns:
            families[family] = columns
    return families


def neutralize_feature_family(row, train_matrix, feature_cols, family_columns):
    out = row.copy()
    for column in family_columns:
        idx = feature_cols.index(column)
        if column in NATIVE_NAN_FEATURE_COLUMNS:
            out[idx] = np.nan
        elif column.startswith("wind_") or column.startswith("cloud_"):
            out[idx] = 0.0
        else:
            train_values = train_matrix[:, idx]
            train_values = train_values[~np.isnan(train_values)]
            out[idx] = float(np.median(train_values)) if len(train_values) else 0.0
    return out


def summarize_ablation_by_family(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["family"]].append(row)
    summary = []
    for family, family_rows in sorted(grouped.items()):
        n = sum(row["n"] for row in family_rows)
        if n <= 0:
            continue
        summary.append({
            "family": family,
            "n": n,
            "full_logloss": sum(row["full_logloss"] * row["n"] for row in family_rows) / n,
            "ablated_logloss": sum(row["ablated_logloss"] * row["n"] for row in family_rows) / n,
            "delta_logloss": sum(row["delta_logloss"] * row["n"] for row in family_rows) / n,
            "full_brier": sum(row["full_brier"] * row["n"] for row in family_rows) / n,
            "ablated_brier": sum(row["ablated_brier"] * row["n"] for row in family_rows) / n,
            "delta_brier": sum(row["delta_brier"] * row["n"] for row in family_rows) / n,
        })
    return sorted(summary, key=lambda row: row["delta_logloss"], reverse=True)


def ablation_table_row(row, include_hour=False):
    prefix = f"| {row['hour']:02d}:00 | " if include_hour else "| "
    return (
        f"{prefix}{row['family']} | {row['n']} | "
        f"{row['full_logloss']:.4f} | {row['ablated_logloss']:.4f} | "
        f"{row['delta_logloss']:+.4f} | {row['full_brier']:.4f} | "
        f"{row['ablated_brier']:.4f} | {row['delta_brier']:+.4f} |"
    )


def train_late_day_continuation_models(
    model,
    daily,
    by_date,
    forecast_index,
    all_wind_groups=None,
    all_cloud_groups=None,
    trained_at=None,
):
    all_wind_groups = list(all_wind_groups or WIND_GROUPS)
    all_cloud_groups = list(all_cloud_groups or CLOUD_GROUPS)
    trained_at = trained_at or datetime.now().isoformat()
    late_day_info = {
        "schema_version": LATE_DAY_MODEL_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": trained_at,
    }
    late_day_validation_rows = []
    late_day_ablation_rows = []
    for H in [15, 16, 17]:
        late_day_records = []
        for local_date in sorted(daily.keys()):
            rows = by_date.get(local_date, [])
            if not rows:
                continue
            final_high = daily[local_date].get("max_temp_native")
            if final_high is None:
                continue

            obs_7am_candidates = [
                r for r in rows
                if 360 <= r["minute_of_day"] <= 480 and row_temp_native(r) is not None
            ]
            temp_7am = None
            if obs_7am_candidates:
                closest_obs_7am = min(
                    obs_7am_candidates,
                    key=lambda r: abs(r["minute_of_day"] - 420),
                )
                temp_7am = row_temp_native(closest_obs_7am)

            cutoff_minutes = H * 60
            obs_before = [r for r in rows if r["minute_of_day"] <= cutoff_minutes]
            if not obs_before:
                continue
            temps_before = [row_temp_native(r) for r in obs_before if row_temp_native(r) is not None]
            if not temps_before:
                continue
            high_so_far = max(temps_before)
            current_obs = obs_before[-1]
            current_temp = row_temp_native(current_obs)

            first_obs = None
            for r in obs_before:
                if row_temp_native(r) == high_so_far:
                    first_obs = r
                    break
            if first_obs is None:
                continue

            wall_minute = cutoff_minutes + wall_offset_for(local_date, H)
            time_since_reached = wall_minute - first_obs["minute_of_day"]

            rise_from_7am = 0.0
            if current_temp is not None and temp_7am is not None:
                rise_from_7am = current_temp - temp_7am

            dewpoint = row_dewpoint_native(current_obs)
            humidity = current_obs.get("humidity")
            pressure = current_obs.get("pressure")

            obs_3h_candidates = [
                r for r in rows
                if (cutoff_minutes - 240) <= r["minute_of_day"] <= (cutoff_minutes - 120)
                and r["pressure"] is not None
            ]
            pressure_trend_3h = 0.0
            if pressure is not None and obs_3h_candidates:
                closest_obs_3h = min(
                    obs_3h_candidates,
                    key=lambda r: abs(r["minute_of_day"] - (cutoff_minutes - 180)),
                )
                pressure_trend_3h = pressure - closest_obs_3h["pressure"]

            wind_speed = current_obs.get("wind_kmh")
            wind_gust = row_value(current_obs, "gust_kmh", "wind_gust_kmh", "wind_gust")
            wind_shift_3h = wind_direction_delta_degrees(
                row_wind_direction(current_obs),
                closest_wind_direction(rows, cutoff_minutes - 180, 60),
            )
            wind_group = model.wind_group(current_obs.get("wind"))
            cloud_group = model.cloud_group(current_obs.get("condition"), current_obs.get("clouds"))
            forecast_high = forecast_index.get(local_date.isoformat())
            forecast_gap = (
                forecast_high - high_so_far
                if forecast_high is not None and high_so_far is not None
                else None
            )

            is_extended = 1.0 if final_high > high_so_far + 0.1 else 0.0

            late_day_records.append({
                "date_ordinal": local_date.toordinal(),
                "time_since_reached": time_since_reached,
                "high_so_far": high_so_far,
                "current_temp": current_temp,
                "rise_from_7am": rise_from_7am,
                "dewpoint_c": dewpoint,
                "humidity": humidity,
                "pressure": pressure,
                "pressure_trend_3h": pressure_trend_3h,
                "wind_speed_kmh": wind_speed,
                "wind_gust_kmh": wind_gust,
                "wind_shift_3h_degrees": wind_shift_3h if wind_shift_3h is not None else 0.0,
                "forecast_high": forecast_high,
                "forecast_gap": forecast_gap,
                "wind_group": wind_group,
                "cloud_group": cloud_group,
                "is_extended": is_extended,
            })

        if not late_day_records:
            continue

        ld_df = pd.DataFrame(late_day_records)
        for g in all_wind_groups:
            ld_df[f"wind_{g}"] = (ld_df["wind_group"] == g).astype(float)
        for g in all_cloud_groups:
            ld_df[f"cloud_{g}"] = (ld_df["cloud_group"] == g).astype(float)

        ld_feature_cols = late_day_feature_columns(all_wind_groups, all_cloud_groups)
        ld_numeric_count = len(LATE_DAY_NUMERIC_FEATURES)

        ld_X = ld_df[ld_feature_cols].copy()
        ld_y = ld_df["is_extended"].copy()
        validation, ablations = evaluate_late_day_records(
            ld_df,
            ld_feature_cols,
            ld_numeric_count,
        )
        if validation:
            validation["hour"] = H
            late_day_validation_rows.append(validation)
            for row in ablations:
                copy = dict(row)
                copy["hour"] = H
                late_day_ablation_rows.append(copy)

        ld_imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        ld_X_imputed = ld_imputer.fit_transform(ld_X)
        ld_scaler = StandardScaler()
        ld_X_scaled = ld_X_imputed.copy()
        ld_X_scaled[:, :ld_numeric_count] = ld_scaler.fit_transform(
            ld_X_imputed[:, :ld_numeric_count]
        )

        ld_lr = LogisticRegression(max_iter=1000, C=0.5, random_state=42)
        if len(np.unique(ld_y)) > 1:
            ld_lr.fit(ld_X_scaled, ld_y)
            coefs = ld_lr.coef_[0].tolist()
            intercept = float(ld_lr.intercept_[0])
        else:
            coefs = [0.0] * len(ld_feature_cols)
            intercept = -10.0 if ld_y.mean() == 0 else 10.0

        prior_p = ld_y.mean()

        late_day_info[str(H)] = {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": ld_feature_cols,
            "numeric_feature_names": list(LATE_DAY_NUMERIC_FEATURES),
            "numeric_feature_count": ld_numeric_count,
            "coef": coefs,
            "intercept": intercept,
            "scaler_mean": ld_scaler.mean_[:ld_numeric_count].tolist(),
            "scaler_scale": ld_scaler.scale_[:ld_numeric_count].tolist(),
            "imputer_median": ld_imputer.statistics_.tolist(),
            "empirical_prior": float(prior_p),
        }
        print(f"  Cutoff Hour {H:02d}:00 trained. Base continuation rate: {prior_p*100:.1f}%.")

    return late_day_info, late_day_validation_rows, late_day_ablation_rows


def write_late_day_continuation_report(spec, validation_rows, ablation_rows, report_path):
    lines = [
        "# Late-Day Continuation Model Validation",
        "",
        f"Market: `{spec.id}` ({spec.unit})",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This report scores the 15:00, 16:00, and 17:00 continuation classifiers directly.",
        "The trained feature set includes `forecast_high` and `forecast_gap`.",
        "",
    ]
    if validation_rows:
        lines += [
            "| Cutoff | Rows | Continuation Rate | LogLoss | Brier | ECE |",
            "| :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in sorted(validation_rows, key=lambda item: item["hour"]):
            lines.append(
                f"| {row['hour']:02d}:00 | {row['n']} | "
                f"{row['event_rate']:.3f} | {row['logloss']:.4f} | "
                f"{row['brier']:.4f} | {row['ece']:.4f} |"
            )
    else:
        lines.append("No late-day validation rows were available.")

    if ablation_rows:
        lines += [
            "",
            "## Feature-Family Ablation",
            "",
            "Positive deltas mean the feature family helped the continuation classifier.",
            "",
            "| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in summarize_ablation_by_family(ablation_rows):
            lines.append(ablation_table_row(row))
        lines += [
            "",
            "## Ablation By Cutoff",
            "",
            "| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]
        for row in sorted(ablation_rows, key=lambda item: (item["hour"], item["family"])):
            lines.append(ablation_table_row(row, include_hour=True))

    report_path = os.fspath(report_path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return report_path


def main_late_day(market_id="toronto"):
    model = TorontoHighTempModel(market_id=market_id)
    spec = model.spec
    suffix = spec.artifact_suffix
    print(f"Training late-day continuation model for market '{spec.id}' "
          f"(unit {spec.unit}, artifacts '*{suffix}').")
    cache = model.historical_target_cache()
    daily = cache["daily"]
    by_date = cache["by_date"]
    forecast_index = load_forecast_daily(daily_path_for(spec))
    print(f"Loaded {len(daily)} target-season days and {len(forecast_index)} forecast-days.")

    late_day_info, validation_rows, ablation_rows = train_late_day_continuation_models(
        model,
        daily,
        by_date,
        forecast_index,
        WIND_GROUPS,
        CLOUD_GROUPS,
    )
    ld_coefs_path = writable_artifact_path(f"late_day_model_coefs{suffix}.json")
    with open(ld_coefs_path, "w", encoding="utf-8") as f:
        json.dump(late_day_info, f, indent=2, sort_keys=True)
    print(f"Saved final late-day model coefficients to {ld_coefs_path}")

    report_path = os.path.join(
        str(spec.data_root),
        "analysis",
        f"late_day_continuation_report{suffix}.md",
    )
    write_late_day_continuation_report(spec, validation_rows, ablation_rows, report_path)
    print(f"Saved late-day validation report to {report_path}")


def main(market_id="toronto"):
    model = TorontoHighTempModel(market_id=market_id)
    spec = model.spec
    suffix = spec.artifact_suffix
    print(f"Training feature model for market '{spec.id}' (unit {spec.unit}, "
          f"artifacts '*{suffix}').")
    print("Loading historical data cache...")
    cache = model.historical_target_cache()

    daily = cache["daily"]
    by_date = cache["by_date"]
    bucket_space = cache["bucket_space"]

    print(f"Loaded {len(daily)} target-season days with observations.")

    # Archived Open-Meteo forecasts (non-leaky); absent before 2018 -> NaN.
    # Per-market path so the F family trains on its own native-unit forecasts.
    forecast_index = load_forecast_daily(daily_path_for(spec))
    forecast_profiles = load_forecast_profiles(long_path_for(spec))
    print(f"Loaded {len(forecast_index)} historical forecast-days "
          f"(forecast feature present for those, NaN otherwise).")
    print(f"Loaded {len(forecast_profiles)} historical forecast-profile days "
          f"(profile/radiation/cloud features present where archived).")

    # Pre-extract features for all days and hours. Each (day, hour) trains at
    # ONE deterministic intra-hour wall offset (item 40): offsets are covered
    # across days without multiplying the row count, so the O(n^2) LOO cost
    # stays identical to the at-print-only training.
    print("Extracting features at each cutoff hour (sampled intra-hour offsets)...")
    raw_data = defaultdict(list)

    for local_date in sorted(daily.keys()):
        rows = by_date.get(local_date, [])
        if not rows:
            continue

        for hour in INTRADAY_CUTOFF_HOURS:
            offset = wall_offset_for(local_date, hour)
            record = build_historical_feature_record(
                local_date,
                rows,
                daily[local_date],
                hour,
                forecast_high=forecast_index.get(local_date.isoformat()),
                forecast_profile_rows=forecast_profiles.get(local_date.isoformat()),
                wind_group_fn=model.wind_group,
                cloud_group_fn=model.cloud_group,
                microclimate_feature_fn=model.microclimate_features,
                wall_minute=hour * 60 + offset,
            )
            if record:
                raw_data[hour].append(record)

    # Available wind and cloud categories for one-hot encoding consistency
    all_wind_groups = WIND_GROUPS
    all_cloud_groups = CLOUD_GROUPS

    # We will build and validate models for each hour
    print("\n--- Model Evaluation and Leave-One-Out validation ---")
    
    report_lines = [
        "# Roadmap Item 6: Feature-Based Probability Model Evaluation\n",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        "This report compares the Leave-One-Out validation performance of the empirical baseline model (Item 2) against the new feature-based ML models:\n",
        "1. **Multinomial Logistic Regression** (L2 penalty, Softmax probabilities)\n",
        "2. **HistGradientBoostingClassifier** (Non-linear decision tree ensemble)\n\n",
        "Lower log loss / Brier is better. ECE (expected calibration error over the\n"
        "top-class confidence) is reported per model below the table; lower is better.\n\n",
        "| Cutoff Hour | Base LogLoss | Base Brier | Base Acc | LR LogLoss | LR Brier | LR Acc | HGBC LogLoss | HGBC Brier | HGBC Acc |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
    ]

    # Accumulated (confidence, correct) pairs across all hours for overall ECE.
    overall_cc = {"baseline": [], "lr": [], "hgb": [], "hgb_tuned": []}
    # Per-hour climatology<->HGB blend weight, grid-searched by LOO log loss.
    tuned_blend_weight = {}
    tuned_probability_temperature = {}
    calibration_rows = []
    ablation_rows = []

    trained_at = datetime.now().isoformat()
    trained_models_info = {
        "schema_version": FEATURE_MODEL_COEFS_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": trained_at,
    }
    hgb_models_info = {
        "schema_version": FEATURE_MODEL_HGB_SCHEMA_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": trained_at,
    }

    for hour in INTRADAY_CUTOFF_HOURS:
        records = raw_data[hour]
        if not records:
            continue
            
        print(f"\nCutoff Hour {hour:02d}:00 ({len(records)} days):")
        
        # Convert list of dicts to DataFrame
        df = pd.DataFrame(records)
        
        # Preprocess features (Standard scaling and One-Hot Encoding)
        # One-hot encode wind_group
        for g in all_wind_groups:
            df[f"wind_{g}"] = (df["wind_group"] == g).astype(float)
        # One-hot encode cloud_group
        for g in all_cloud_groups:
            df[f"cloud_{g}"] = (df["cloud_group"] == g).astype(float)
            
        numeric_cols = [
            column for column in FEATURE_COLUMNS
            if column not in {"wind_group", "cloud_group"}
        ]
        n_numeric = len(numeric_cols)
        feature_cols = numeric_cols + [f"wind_{g}" for g in all_wind_groups] + [f"cloud_{g}" for g in all_cloud_groups]
        feature_families = feature_family_columns(feature_cols)

        X = df[feature_cols].copy()
        y = df["final_bucket"].copy()

        # Impute missing values (forecast features are median-filled where absent;
        # pre-archive that degenerates to a constant high / a redundant gap, so it
        # is benign, while post-archive rows carry the real forecast signal).
        imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        X_imputed = imputer.fit_transform(X)

        # Standardize the numeric columns (the leading n_numeric columns).
        scaler = StandardScaler()
        X_scaled = X_imputed.copy()
        X_scaled[:, :n_numeric] = scaler.fit_transform(X_imputed[:, :n_numeric])

        # HGB version: keep the forecast columns as native NaN where absent (pre
        # archive) instead of median-filling, so the tree learns "forecast
        # unknown" rather than splitting on a fake value. (LR can't do NaN, so it
        # keeps the imputed+scaled matrix above.)
        forecast_idx = [
            feature_cols.index(column)
            for column in NATIVE_NAN_FEATURE_COLUMNS
            if column in feature_cols
        ]
        X_hgb = X_imputed.copy()
        if forecast_idx:
            X_hgb[:, forecast_idx] = X[
                [feature_cols[index] for index in forecast_idx]
            ].to_numpy(dtype=float)

        # Run Leave-One-Out cross-validation
        n_samples = len(df)
        if not RUN_LOO:
            n_samples = 0
        
        # Baseline model weights for this hour
        weights = model.calibrated_weights.get(str(hour)) if model.calibrated_weights else None
        w_int_base = weights.get("w_intraday_base", 0.36) if weights else 0.36
        w_wnd = weights.get("w_wind", 0.14) if weights else 0.14
        w_cld = weights.get("w_cloud", 0.12) if weights else 0.12
        
        losses_baseline = []
        accs_baseline = []
        briers_baseline = []
        cc_baseline = []  # (top-class confidence, was_correct) for ECE

        losses_lr = []
        accs_lr = []
        briers_lr = []
        cc_lr = []

        losses_hgb = []
        accs_hgb = []
        briers_hgb = []
        cc_hgb = []
        hgb_fold_data = []  # (p_clim, raw_hgb_prob_dict, val_actual) for weight tuning
        ablation_losses = defaultdict(list)
        ablation_briers = defaultdict(list)

        for val_idx in range(n_samples):
            # Split train and validation
            train_mask = np.ones(n_samples, dtype=bool)
            train_mask[val_idx] = False
            
            # Validation date
            val_date = df.iloc[val_idx]["date"]
            val_actual = df.iloc[val_idx]["final_bucket"]
            
            # Get historical training subset for priors (excluding validation year's date window)
            train_df = df[train_mask]
            train_days = [d for d in records if d["date"].year != val_date.year]
            
            # --- 1. Compute Baseline predictions ---
            p_clim = smoothed_dist([d["final_bucket"] for d in train_days], bucket_space, alpha=0.10)
            
            # Intraday lookup
            p_intraday = None
            n_intraday = 0
            val_observed_bucket = round_half_up(df.iloc[val_idx]["high_so_far"])
            if val_observed_bucket is not None:
                matching_days = [d for d in train_days if round_half_up(d["high_so_far"]) == val_observed_bucket]
                n_intraday = len(matching_days)
                if n_intraday >= 8:
                    p_intraday = smoothed_dist([d["final_bucket"] for d in matching_days], bucket_space, alpha=0.05)
                    
            # Wind regime
            p_wind = None
            val_wind = df.iloc[val_idx]["wind_group"]
            if val_wind:
                matching_days = [d for d in train_days if d["wind_group"] == val_wind]
                if len(matching_days) >= 20:
                    p_wind = smoothed_dist([d["final_bucket"] for d in matching_days], bucket_space, alpha=0.10)
                    
            # Cloud regime
            p_cloud = None
            val_cloud = df.iloc[val_idx]["cloud_group"]
            if val_cloud:
                matching_days = [d for d in train_days if d["cloud_group"] == val_cloud]
                if len(matching_days) >= 20:
                    p_cloud = smoothed_dist([d["final_bucket"] for d in matching_days], bucket_space, alpha=0.10)
                    
            # Blend baseline
            scores_base = p_clim.copy()
            if p_intraday is not None and n_intraday > 0:
                w_int = w_int_base * (n_intraday / (n_intraday + 25))
                scores_base = blend(scores_base, p_intraday, w_int)
            if p_wind is not None:
                scores_base = blend(scores_base, p_wind, w_wnd)
            if p_cloud is not None:
                scores_base = blend(scores_base, p_cloud, w_cld)
                
            losses_baseline.append(log_loss(scores_base, val_actual))
            base_top = max(scores_base, key=scores_base.get)
            accs_baseline.append(1.0 if base_top == val_actual else 0.0)
            briers_baseline.append(brier_score(scores_base, val_actual))
            cc_baseline.append((scores_base[base_top], 1.0 if base_top == val_actual else 0.0))
            
            # Train and fit splits (LR uses scaled+imputed; HGB uses the
            # native-NaN matrix so it sees missing forecasts as missing).
            X_train, y_train = X_scaled[train_mask], y[train_mask]
            X_val, y_val = X_scaled[val_idx].reshape(1, -1), y[val_idx]
            X_hgb_train = X_hgb[train_mask]
            X_hgb_val = X_hgb[val_idx].reshape(1, -1)

            # --- 2. Train & Predict Logistic Regression ---
            # Using simple Logistic Regression
            lr = LogisticRegression(max_iter=1000, C=0.5, random_state=42)
            lr.fit(X_train, y_train)
            
            # Map predictions
            lr_probs_raw = lr.predict_proba(X_val)[0]
            lr_classes = lr.classes_
            lr_prob_dict = {int(c): float(p) for c, p in zip(lr_classes, lr_probs_raw)}
            # Blend LR output with climatology for smoothing (prior weight = 0.20)
            lr_prob_blended = blend(p_clim.copy(), lr_prob_dict, 0.80)
            
            losses_lr.append(log_loss(lr_prob_blended, val_actual))
            lr_top = max(lr_prob_blended, key=lr_prob_blended.get)
            accs_lr.append(1.0 if lr_top == val_actual else 0.0)
            briers_lr.append(brier_score(lr_prob_blended, val_actual))
            cc_lr.append((lr_prob_blended[lr_top], 1.0 if lr_top == val_actual else 0.0))
            
            # --- 3. Train & Predict HistGradientBoostingClassifier ---
            hgb = HistGradientBoostingClassifier(max_iter=50, max_leaf_nodes=15, learning_rate=0.05, random_state=42)
            hgb.fit(X_hgb_train, y_train)

            hgb_probs_raw = hgb.predict_proba(X_hgb_val)[0]
            hgb_classes = hgb.classes_
            hgb_prob_dict = {int(c): float(p) for c, p in zip(hgb_classes, hgb_probs_raw)}
            hgb_prob_blended = blend(p_clim.copy(), hgb_prob_dict, 0.80)
            
            losses_hgb.append(log_loss(hgb_prob_blended, val_actual))
            hgb_top = max(hgb_prob_blended, key=hgb_prob_blended.get)
            accs_hgb.append(1.0 if hgb_top == val_actual else 0.0)
            briers_hgb.append(brier_score(hgb_prob_blended, val_actual))
            cc_hgb.append((hgb_prob_blended[hgb_top], 1.0 if hgb_top == val_actual else 0.0))
            hgb_fold_data.append((p_clim, hgb_prob_dict, val_actual))

            for family, family_columns in feature_families.items():
                X_hgb_val_ablated = neutralize_feature_family(
                    X_hgb_val[0],
                    X_hgb_train,
                    feature_cols,
                    family_columns,
                ).reshape(1, -1)
                ablated_probs_raw = hgb.predict_proba(X_hgb_val_ablated)[0]
                ablated_prob_dict = {
                    int(c): float(p)
                    for c, p in zip(hgb_classes, ablated_probs_raw)
                }
                ablated_blended = blend(p_clim.copy(), ablated_prob_dict, 0.80)
                ablation_losses[family].append(log_loss(ablated_blended, val_actual))
                ablation_briers[family].append(brier_score(ablated_blended, val_actual))

        if RUN_LOO:
            # Print metrics summary
            base_ll = np.mean(losses_baseline)
            base_acc = np.mean(accs_baseline)
            base_brier = np.mean(briers_baseline)

            lr_ll = np.mean(losses_lr)
            lr_acc = np.mean(accs_lr)
            lr_brier = np.mean(briers_lr)

            hgb_ll = np.mean(losses_hgb)
            hgb_acc = np.mean(accs_hgb)
            hgb_brier = np.mean(briers_hgb)

            overall_cc["baseline"].extend(cc_baseline)
            overall_cc["lr"].extend(cc_lr)
            overall_cc["hgb"].extend(cc_hgb)

            # Grid-search the HGB probability temperature plus the
            # climatology<->HGB blend weight that minimizes LOO log loss for
            # this hour. temperature=1.00 and weight=0.80 (the old behavior)
            # are in the grids, so the tuned pair can never be worse on log loss.
            WEIGHT_GRID = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.97]
            calibration = fit_temperature_blend_grid(
                hgb_fold_data,
                blend_weights=WEIGHT_GRID,
            )
            best_t = calibration["temperature"]
            best_w = calibration["blend_weight"]
            tuned_blend_weight[str(hour)] = best_w
            tuned_probability_temperature[str(hour)] = best_t
            tuned_blended = [
                (blend(pc.copy(), temperature_scale_distribution(hd, best_t), best_w), ya)
                for pc, hd, ya in hgb_fold_data
            ]
            tuned_ll = np.mean([log_loss(pb, ya) for pb, ya in tuned_blended])
            tuned_brier = np.mean([brier_score(pb, ya) for pb, ya in tuned_blended])
            tuned_cc = [(pb[max(pb, key=pb.get)], 1.0 if max(pb, key=pb.get) == ya else 0.0)
                        for pb, ya in tuned_blended]
            overall_cc["hgb_tuned"].extend(tuned_cc)
            hour_ece_fixed = expected_calibration_error(cc_hgb)
            hour_ece_tuned = expected_calibration_error(tuned_cc)
            calibration_rows.append(
                f"| {hour:02d}:00 | {best_t:.2f} | {best_w:.2f} | {hgb_ll:.4f} | {tuned_ll:.4f} | "
                f"{hgb_ll - tuned_ll:+.4f} | {hour_ece_fixed:.4f} | {hour_ece_tuned:.4f} |"
            )
            for family in sorted(feature_families):
                ab_ll = np.mean(ablation_losses[family])
                ab_brier = np.mean(ablation_briers[family])
                ablation_rows.append({
                    "hour": hour,
                    "family": family,
                    "n": n_samples,
                    "full_logloss": hgb_ll,
                    "ablated_logloss": ab_ll,
                    "delta_logloss": ab_ll - hgb_ll,
                    "full_brier": hgb_brier,
                    "ablated_brier": ab_brier,
                    "delta_brier": ab_brier - hgb_brier,
                })

            print(f"  Baseline:  Log Loss = {base_ll:.4f}, Brier = {base_brier:.4f}, Accuracy = {base_acc*100:.2f}%")
            print(f"  LogisticR: Log Loss = {lr_ll:.4f}, Brier = {lr_brier:.4f}, Accuracy = {lr_acc*100:.2f}%")
            print(f"  HGBC:      Log Loss = {hgb_ll:.4f}, Brier = {hgb_brier:.4f}, Accuracy = {hgb_acc*100:.2f}%")
            print(f"  HGBC tuned w={best_w:.2f}: Log Loss = {tuned_ll:.4f}, Brier = {tuned_brier:.4f}")

            report_lines.append(
                f"| {hour:02d}:00 | {base_ll:.4f} | {base_brier:.4f} | {base_acc*100:.1f}% | "
                f"{lr_ll:.4f} | {lr_brier:.4f} | {lr_acc*100:.1f}% | "
                f"{hgb_ll:.4f} | {hgb_brier:.4f} | {hgb_acc*100:.1f}% |"
            )

        # Train final models on 100% of data to export coefficients
        # Impute and scale on 100% data
        final_imputer = SimpleImputer(strategy="median", keep_empty_features=True)
        X_final_imputed = final_imputer.fit_transform(X)
        final_scaler = StandardScaler()
        X_final_scaled = X_final_imputed.copy()
        X_final_scaled[:, :n_numeric] = final_scaler.fit_transform(X_final_imputed[:, :n_numeric])
        
        # Fit final Logistic Regression
        final_lr = LogisticRegression(max_iter=1000, C=0.5, random_state=42)
        final_lr.fit(X_final_scaled, y)
        
        # Export model coefficients for quick, dependency-free load in toronto_model
        # W_c^T X + intercept_c.
        trained_models_info[str(hour)] = {
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": feature_cols,
            "classes": [int(c) for c in final_lr.classes_],
            "coef": final_lr.coef_.tolist(), # Shape: (n_classes, n_features)
            "intercept": final_lr.intercept_.tolist(), # Shape: (n_classes,)
            "scaler_mean": final_scaler.mean_[:n_numeric].tolist(),
            "scaler_scale": final_scaler.scale_[:n_numeric].tolist(),
            "imputer_median": final_imputer.statistics_.tolist(),
            "blend_weight": 0.80
        }

        # Fit final HistGradientBoostingClassifier (trees need no scaling; forecast
        # columns keep native NaN where absent, matching the LOO and inference).
        X_final_hgb = X_final_imputed.copy()
        if forecast_idx:
            X_final_hgb[:, forecast_idx] = X[
                [feature_cols[index] for index in forecast_idx]
            ].to_numpy(dtype=float)
        final_hgb = HistGradientBoostingClassifier(max_iter=50, max_leaf_nodes=15, learning_rate=0.05, random_state=42)
        final_hgb.fit(X_final_hgb, y)
        
        # Export HGBC bundle (blend_weight tuned by LOO log loss; 0.80 fallback)
        hgb_models_info[str(hour)] = {
            "model": final_hgb,
            "imputer": final_imputer,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "feature_names": feature_cols,
            "all_wind_groups": all_wind_groups,
            "all_cloud_groups": all_cloud_groups,
            "blend_weight": tuned_blend_weight.get(str(hour), 0.80),
            "probability_temperature": tuned_probability_temperature.get(str(hour), 1.0),
            "probability_calibration": {
                "method": "temperature",
                "temperature": tuned_probability_temperature.get(str(hour), 1.0),
            },
        }
        
    # Write coefficients json (per-unit artifact: '' for C, '_f' for F)
    coefs_path = writable_artifact_path(f"feature_model_coefs{suffix}.json")
    with open(coefs_path, "w", encoding="utf-8") as f:
        json.dump(trained_models_info, f, indent=2, sort_keys=True)
    print(f"\nSaved final model coefficients to {coefs_path}")

    # Write HGBC pickle (per-unit artifact)
    hgb_path = writable_artifact_path(f"feature_model_hgb{suffix}.pkl")
    with open(hgb_path, "wb") as f:
        pickle.dump(hgb_models_info, f)
    print(f"Saved final HGBC models to {hgb_path}")

    # --- Train Late-Day Continuation Models ---
    print("\n--- Training Late-Day Continuation Models (Roadmap Item 8) ---")
    late_day_info, late_day_validation_rows, late_day_ablation_rows = (
        train_late_day_continuation_models(
            model,
            daily,
            by_date,
            forecast_index,
            all_wind_groups,
            all_cloud_groups,
            trained_at,
        )
    )
        
    # Save late day coefficients JSON (per-unit artifact)
    ld_coefs_path = writable_artifact_path(f"late_day_model_coefs{suffix}.json")
    with open(ld_coefs_path, "w", encoding="utf-8") as f:
        json.dump(late_day_info, f, indent=2, sort_keys=True)
    print(f"Saved final late-day model coefficients to {ld_coefs_path}")
    
    if RUN_LOO:
        # Per-hour blend-weight calibration table.
        report_lines.append("\n## HGB climatology-blend calibration (tuned by LOO log loss)\n")
        report_lines.append(
            "Temperature is multiclass probability-temperature scaling applied "
            "to the raw HGB distribution before blending. Blend weight = fraction "
            "on the calibrated HGB prediction vs the climatology prior. The legacy "
            "temperature=1.00 / weight=0.80 pair remains in the grid; the selected "
            "pair is stored in the serving bundle.\n")
        report_lines.append("| Cutoff | Temperature | Tuned w | LogLoss legacy | LogLoss tuned | Delta | ECE legacy | ECE tuned |")
        report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        report_lines.extend(calibration_rows)

        # Overall calibration (ECE) across all cutoff hours.
        base_ece = expected_calibration_error(overall_cc["baseline"])
        lr_ece = expected_calibration_error(overall_cc["lr"])
        hgb_ece = expected_calibration_error(overall_cc["hgb"])
        hgb_tuned_ece = expected_calibration_error(overall_cc["hgb_tuned"])
        print(f"\nOverall ECE  -  Baseline: {base_ece:.4f}  LR: {lr_ece:.4f}  "
              f"HGBC@0.80: {hgb_ece:.4f}  HGBC@tuned: {hgb_tuned_ece:.4f}")
        report_lines.append("\n## Overall calibration (Expected Calibration Error)\n")
        report_lines.append("| Model | ECE (top-class confidence vs accuracy) |")
        report_lines.append("| :--- | :--- |")
        report_lines.append(f"| Empirical baseline | {base_ece:.4f} |")
        report_lines.append(f"| Logistic Regression | {lr_ece:.4f} |")
        report_lines.append(f"| HGBC (fixed 0.80 blend) | {hgb_ece:.4f} |")
        report_lines.append(f"| HGBC (tuned blend) | {hgb_tuned_ece:.4f} |")

        report_lines.append("\n## Feature-family ablation (HGB LOO validation)\n")
        report_lines.append(
            "For each leave-one-out fold, the trained HGB model is held fixed and "
            "one feature family is neutralized in the validation row. Positive "
            "deltas mean the feature family helped the HGB validation score; "
            "negative deltas mean neutralizing it improved the score. This is a "
            "fast sensitivity ablation, not a full retrain-without-family study.\n"
        )
        report_lines.append("| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |")
        report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for row in summarize_ablation_by_family(ablation_rows):
            report_lines.append(ablation_table_row(row))

        report_lines.append("\n### Feature-family ablation by cutoff hour\n")
        report_lines.append("| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |")
        report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for row in sorted(ablation_rows, key=lambda item: (item["hour"], item["family"])):
            report_lines.append(ablation_table_row(row, include_hour=True))

        if late_day_validation_rows:
            report_lines.append("\n## Late-day continuation validation\n")
            report_lines.append(
                "Five-fold day-split validation for the 15:00, 16:00, and 17:00 "
                "continuation classifiers. These rows score the trained "
                "continuation component directly, including `forecast_high` and "
                "`forecast_gap` as late-day features.\n"
            )
            report_lines.append("| Cutoff | Rows | Event Rate | LogLoss | Brier | ECE |")
            report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for row in sorted(late_day_validation_rows, key=lambda item: item["hour"]):
                report_lines.append(
                    f"| {row['hour']:02d}:00 | {row['n']} | "
                    f"{row['event_rate']:.3f} | {row['logloss']:.4f} | "
                    f"{row['brier']:.4f} | {row['ece']:.4f} |"
                )

        if late_day_ablation_rows:
            report_lines.append("\n### Late-day continuation feature-family ablation\n")
            report_lines.append(
                "Positive deltas mean the family helped the continuation "
                "validation score; negative deltas mean neutralizing it improved "
                "the score for this fast sensitivity test.\n"
            )
            report_lines.append("| Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |")
            report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for row in summarize_ablation_by_family(late_day_ablation_rows):
                report_lines.append(ablation_table_row(row))
            report_lines.append("\n#### Late-day continuation ablation by cutoff hour\n")
            report_lines.append("| Cutoff | Family | Rows | Full LogLoss | Ablated LogLoss | Delta | Full Brier | Ablated Brier | Delta |")
            report_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for row in sorted(late_day_ablation_rows, key=lambda item: (item["hour"], item["family"])):
                report_lines.append(ablation_table_row(row, include_hour=True))

        # Save Report file
        report_path = os.path.join(str(spec.data_root), "analysis", f"feature_model_report{suffix}.md")
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report_lines) + "\n")
        print(f"Saved model report to {report_path}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Train the feature model for one market's unit family.")
    parser.add_argument(
        "--market", default="toronto",
        help="Registered market id (toronto -> C artifacts, nyc -> *_f artifacts).")
    parser.add_argument(
        "--skip-loo", action="store_true",
        help="Skip leave-one-out validation and only retrain final serving artifacts.")
    parser.add_argument(
        "--late-day-only", action="store_true",
        help="Only retrain late-day continuation coefficients and validation report.")
    args = parser.parse_args()
    if args.late_day_only:
        main_late_day(market_id=args.market)
        raise SystemExit(0)
    if args.skip_loo:
        RUN_LOO = False
    main(market_id=args.market)
