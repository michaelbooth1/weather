"""F-family pooled feature model starter.

This is the Roadmap item 33 research path: train one shared native-unit model
across all Fahrenheit markets with city/context features. It deliberately writes
a separate artifact and report; live serving remains per-market until the
promotion gauntlet proves a pooled candidate market by market.
"""
import argparse
import json
import math
import pickle
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

SRC_ROOT = Path(__file__).resolve().parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtest import binary_log_loss, brier, fmt_num, markdown_table
from feature_store import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION, build_historical_feature_record
from forecast_history import daily_path_for, load_forecast_daily
from market_registry import all_specs
from model_constants import INTRADAY_CUTOFF_HOURS
from source_redundancy import FALLBACK_ORDER, PRIMARY_SOURCE, bias_stats_for_source, source_daily_indexes
from toronto_model import TorontoHighTempModel

DEFAULT_REPORT = Path("data") / "backtest" / "f_family_pooled_model_report.md"
DEFAULT_ARTIFACT = Path("src") / "feature_model_hgb_f_pooled.pkl"
DEFAULT_BAND_REPORT = Path("data") / "backtest" / "f_family_pooled_band_model_v0_3_report.md"
DEFAULT_BAND_ARTIFACT = Path("src") / "feature_model_hgb_f_pooled_v0_3.pkl"

WIND_GROUPS = ["E-SE/onshore-ish", "S-SW", "W-NW", "N-NE", "SSE", "Other/variable"]
CLOUD_GROUPS = ["Precip", "Fog/haze", "Fair/clear", "Partly cloudy", "Mostly cloudy/overcast", "Other"]
BAND_KINDS = ("eq", "lte", "gte")
BAND_NUMERIC_COLUMNS = [
    "band_value",
    "band_value_hi",
    "band_width",
    "band_mid",
    "band_minus_high_so_far",
    "band_hi_minus_high_so_far",
    "band_mid_minus_high_so_far",
    "band_mid_minus_forecast",
    "band_mid_minus_live_reading",
    "band_mid_anomaly",
    "band_below_floor",
    "band_contains_floor",
    "band_above_floor",
    "late_lockin_strength",
]
SOURCE_RELIABILITY_COLUMNS = [
    "source_redundant_streams",
    "source_overlap_days",
    "source_best_bucket_match",
    "source_best_mae",
    "source_metar_bias",
    "source_metar_mae",
    "source_metar_bucket_match",
    "source_ghcnh_bias",
    "source_ghcnh_mae",
    "source_ghcnh_bucket_match",
    "source_reanalysis_bias",
    "source_reanalysis_mae",
    "source_reanalysis_bucket_match",
]


def round_half_up(value):
    if value is None:
        return None
    try:
        return int(math.floor(float(value) + 0.5))
    except (TypeError, ValueError):
        return None


def sigmoid(value):
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def clip_probability(value, epsilon=1e-6):
    if value is None:
        return None
    return max(epsilon, min(1.0 - epsilon, float(value)))


def temperature_scale_probability(value, temperature=1.0):
    value = clip_probability(value)
    temperature = max(0.05, float(temperature or 1.0))
    logit = math.log(value / (1.0 - value))
    return clip_probability(sigmoid(logit / temperature))


def late_lockin_strength_from_features(record):
    """Serving-side late lock-in proxy for the pooled band candidate.

    It mirrors the production heuristic from ``DistributionMixin`` without
    needing settlement-lag artifacts in this research artifact. The direct band
    model also sees this value as a feature, and replay postprocessing uses it
    to concentrate late, cooling days onto the printed high.
    """
    try:
        hour = int(record.get("cutoff_hour"))
    except (TypeError, ValueError):
        return 0.0
    high = record.get("high_so_far")
    current = record.get("live_reading_temp")
    if current is None:
        current = record.get("current_temp")
    if high is None or current is None:
        return 0.0
    try:
        high = float(high)
        current = float(current)
    except (TypeError, ValueError):
        return 0.0
    if hour <= 15:
        time_factor = 0.0
    elif hour >= 17:
        time_factor = 1.0
    else:
        time_factor = (hour - 15) / 2.0
    drop = high - current
    if drop <= 0:
        peak_factor = 0.0
    elif drop >= 2.0:
        peak_factor = 1.0
    else:
        peak_factor = drop / 2.0
    return max(0.0, min(1.0, time_factor * peak_factor))


def band_outcome(kind, value, final_bucket, value_hi=None):
    if value is None or final_bucket is None:
        return None
    try:
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
        final = int(float(final_bucket))
    except (TypeError, ValueError):
        return None
    if kind == "lte":
        return 1 if final <= lo else 0
    if kind == "gte":
        return 1 if final >= lo else 0
    return 1 if lo <= final <= hi else 0


def hard_floor_probability(kind, value, floor_bucket, value_hi=None):
    """Deterministic probabilities implied by the printed WU high."""
    if floor_bucket is None or value is None:
        return None
    try:
        floor_bucket = int(float(floor_bucket))
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None
    if kind == "gte" and floor_bucket >= lo:
        return 1.0
    if kind == "lte" and floor_bucket > lo:
        return 0.0
    if kind not in {"gte", "lte"} and hi < floor_bucket:
        return 0.0
    return None


def support_floor_cap(kind, value, support_bucket, value_hi=None, one_below_cap=0.08, decay=0.25):
    """Soft cap from non-resolution live support such as METAR/current temp.

    Unlike the WU-history printed high this is not a hard settlement floor, but
    a band entirely below a live observed support bucket should not keep a high
    candidate probability.
    """
    if support_bucket is None or value is None:
        return None
    try:
        support_bucket = int(float(support_bucket))
        lo = int(float(value))
        hi = int(float(value_hi)) if value_hi is not None else lo
    except (TypeError, ValueError):
        return None
    if kind == "gte" and support_bucket >= lo:
        return None
    if kind == "lte" and support_bucket > lo:
        gap = max(1, support_bucket - lo)
        return float(one_below_cap) * (float(decay) ** (gap - 1))
    if kind not in {"gte", "lte"} and hi < support_bucket:
        gap = max(1, support_bucket - hi)
        return float(one_below_cap) * (float(decay) ** (gap - 1))
    return None


def late_lockin_target(kind, value, floor_bucket, value_hi=None):
    """Band probability if the day resolves exactly at the printed high."""
    if floor_bucket is None:
        return None
    return float(band_outcome(kind, value, floor_bucket, value_hi=value_hi))


def family_specs(unit="F"):
    return [spec for spec in all_specs() if spec.display_unit == unit]


def market_climate_stats(cache):
    buckets = [row.get("bucket") for row in (cache.get("daily") or {}).values()]
    buckets = [float(value) for value in buckets if value is not None]
    if not buckets:
        return {"climate_normal": None, "climate_std": None}
    mean = sum(buckets) / len(buckets)
    if len(buckets) < 2:
        std = 0.0
    else:
        std = math.sqrt(sum((value - mean) ** 2 for value in buckets) / (len(buckets) - 1))
    return {"climate_normal": mean, "climate_std": std}


def market_source_reliability(spec):
    """Static per-market source-quality priors for pooled training.

    These are learned from available daily-source overlaps versus WU, not from
    the same intraday record being scored. They give the pooled model a compact
    city/source trust context without using final redundant-source highs as
    same-day features.
    """
    try:
        indexes = source_daily_indexes(spec)
    except Exception:  # noqa: BLE001 - pooled training should survive missing optional stores
        indexes = {}
    primary_rows = indexes.get(PRIMARY_SOURCE) or {}
    reliability = {column: None for column in SOURCE_RELIABILITY_COLUMNS}
    if not primary_rows:
        reliability["source_redundant_streams"] = 0.0
        reliability["source_overlap_days"] = 0.0
        return reliability

    overlap_days = 0
    streams = 0
    best_match = None
    best_mae = None
    for source in FALLBACK_ORDER:
        source_rows = indexes.get(source) or {}
        days = sorted(set(primary_rows) & set(source_rows))
        if not days:
            continue
        streams += 1
        overlap_days += len(days)
        truth_rows = []
        for local_date in days:
            truth_rows.append({
                "source_values": {
                    PRIMARY_SOURCE: primary_rows[local_date],
                    source: source_rows[local_date],
                },
            })
        stats = bias_stats_for_source(truth_rows, source)
        prefix = {
            "metar": "source_metar",
            "ghcnh": "source_ghcnh",
            "reanalysis": "source_reanalysis",
        }.get(source)
        if not prefix:
            continue
        match = stats.get("exact_bucket_match_rate")
        mae = stats.get("mae_vs_wu")
        reliability[f"{prefix}_bias"] = stats.get("bias_source_minus_wu")
        reliability[f"{prefix}_mae"] = mae
        reliability[f"{prefix}_bucket_match"] = match
        if match is not None:
            best_match = match if best_match is None else max(best_match, match)
        if mae is not None:
            best_mae = mae if best_mae is None else min(best_mae, mae)
    reliability["source_redundant_streams"] = float(streams)
    reliability["source_overlap_days"] = float(overlap_days)
    reliability["source_best_bucket_match"] = best_match
    reliability["source_best_mae"] = best_mae
    return reliability


def add_city_features(record, spec, climate, source_reliability=None):
    normal = climate.get("climate_normal")
    high_so_far = record.get("high_so_far")
    forecast_high = record.get("forecast_high")
    record.update({
        "market_id": spec.id,
        "city": spec.city_label,
        "latitude": spec.lat,
        "longitude": spec.lon,
        "coastal": 1.0 if spec.coastal else 0.0,
        "climate_normal": normal,
        "climate_std": climate.get("climate_std"),
        "high_so_far_anomaly": high_so_far - normal
        if high_so_far is not None and normal is not None else None,
        "forecast_anomaly": forecast_high - normal
        if forecast_high is not None and normal is not None else None,
    })
    for column in SOURCE_RELIABILITY_COLUMNS:
        record[column] = (source_reliability or {}).get(column)
    return record


def plausible_native_bucket(bucket, unit):
    if bucket is None:
        return False
    try:
        bucket = int(bucket)
    except (TypeError, ValueError):
        return False
    if unit == "F":
        return 30 <= bucket <= 125
    return -45 <= bucket <= 55


def build_market_records(spec, cutoff_hours=INTRADAY_CUTOFF_HOURS, max_days=None):
    model = TorontoHighTempModel(market_id=spec.id)
    cache = model.historical_target_cache()
    daily = cache.get("daily") or {}
    by_date = cache.get("by_date") or {}
    forecast_index = load_forecast_daily(daily_path_for(spec))
    climate = market_climate_stats(cache)
    source_reliability = market_source_reliability(spec)
    dates = sorted(daily.keys())
    if max_days and max_days > 0:
        dates = dates[-int(max_days):]

    records = []
    wall_offsets = (0, 15, 30, 45)
    for local_date in dates:
        rows = by_date.get(local_date, [])
        if not rows:
            continue
        for hour in cutoff_hours:
            offset = wall_offsets[(local_date.toordinal() + int(hour)) % len(wall_offsets)]
            record = build_historical_feature_record(
                local_date,
                rows,
                daily[local_date],
                int(hour),
                forecast_high=forecast_index.get(local_date.isoformat()),
                wind_group_fn=model.wind_group,
                cloud_group_fn=model.cloud_group,
                wall_minute=int(hour) * 60 + offset,
            )
            if not record or record.get("final_bucket") is None:
                continue
            if not plausible_native_bucket(record.get("final_bucket"), spec.display_unit):
                continue
            add_city_features(record, spec, climate, source_reliability=source_reliability)
            record["cutoff_hour"] = int(hour)
            record["year"] = int(local_date.year)
            records.append(record)
    return records


def build_family_dataset(unit="F", cutoff_hours=INTRADAY_CUTOFF_HOURS, max_days_per_market=None):
    specs = family_specs(unit)
    records = []
    counts = {}
    for spec in specs:
        market_records = build_market_records(
            spec,
            cutoff_hours=cutoff_hours,
            max_days=max_days_per_market,
        )
        counts[spec.id] = len(market_records)
        records.extend(market_records)
    return records, counts


def feature_frame(records, feature_names=None):
    frame = pd.DataFrame(records)
    base_numeric = [
        column for column in FEATURE_COLUMNS
        if column not in ("wind_group", "cloud_group")
    ]
    city_numeric = [
        "latitude",
        "longitude",
        "coastal",
        "climate_normal",
        "climate_std",
        "high_so_far_anomaly",
        "forecast_anomaly",
        *SOURCE_RELIABILITY_COLUMNS,
    ]
    use = base_numeric + city_numeric + ["wind_group", "cloud_group", "market_id"]
    for column in use:
        if column not in frame:
            frame[column] = None
    features = pd.get_dummies(frame[use], columns=["wind_group", "cloud_group", "market_id"], dtype=float)
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


def band_prediction_record(record, kind, value, value_hi=None):
    """Add market-band context to one pooled feature row.

    The v0.2 candidate predicts the binary market contract directly. These
    features tell the model where the band sits relative to the printed floor,
    forecast, live reading, and city climate.
    """
    out = dict(record)
    kind = kind or "eq"
    try:
        lo = float(value)
        hi = float(value_hi) if value_hi is not None else lo
    except (TypeError, ValueError):
        lo = None
        hi = None
    high_so_far = record.get("high_so_far")
    forecast_high = record.get("forecast_high")
    live_reading = record.get("live_reading_temp")
    if live_reading is None:
        live_reading = record.get("current_temp")
    normal = record.get("climate_normal")
    floor_bucket = round_half_up(high_so_far)
    support_bucket = record.get("observed_support_bucket")
    if support_bucket is None:
        support_bucket = floor_bucket
    else:
        support_bucket = round_half_up(support_bucket)
    mid = ((lo + hi) / 2.0) if lo is not None and hi is not None else None

    def diff(left, right):
        if left is None or right is None:
            return None
        try:
            return float(left) - float(right)
        except (TypeError, ValueError):
            return None

    out.update({
        "band_kind": kind,
        "band_value": lo,
        "band_value_hi": hi,
        "band_width": (hi - lo + 1.0) if lo is not None and hi is not None else None,
        "band_mid": mid,
        "band_minus_high_so_far": diff(lo, high_so_far),
        "band_hi_minus_high_so_far": diff(hi, high_so_far),
        "band_mid_minus_high_so_far": diff(mid, high_so_far),
        "band_mid_minus_forecast": diff(mid, forecast_high),
        "band_mid_minus_live_reading": diff(mid, live_reading),
        "band_mid_anomaly": diff(mid, normal),
        "band_below_floor": (
            1.0 if hi is not None and floor_bucket is not None and hi < floor_bucket else 0.0
        ),
        "band_contains_floor": (
            1.0 if lo is not None and hi is not None and floor_bucket is not None
            and lo <= floor_bucket <= hi else 0.0
        ),
        "band_above_floor": (
            1.0 if lo is not None and floor_bucket is not None and lo > floor_bucket else 0.0
        ),
        "late_lockin_strength": late_lockin_strength_from_features(record),
        "observed_floor_bucket": floor_bucket,
        "observed_support_bucket": support_bucket,
    })
    return out


def band_feature_frame(records, feature_names=None):
    frame = pd.DataFrame(records)
    base_numeric = [
        column for column in FEATURE_COLUMNS
        if column not in ("wind_group", "cloud_group")
    ]
    city_numeric = [
        "latitude",
        "longitude",
        "coastal",
        "climate_normal",
        "climate_std",
        "high_so_far_anomaly",
        "forecast_anomaly",
        *SOURCE_RELIABILITY_COLUMNS,
    ]
    use = (
        base_numeric
        + city_numeric
        + BAND_NUMERIC_COLUMNS
        + ["wind_group", "cloud_group", "market_id", "band_kind"]
    )
    for column in use:
        if column not in frame:
            frame[column] = None
    features = pd.get_dummies(
        frame[use],
        columns=["wind_group", "cloud_group", "market_id", "band_kind"],
        dtype=float,
    )
    if feature_names is not None:
        features = features.reindex(columns=feature_names, fill_value=0.0)
    return features


def synthetic_band_rows_for_record(record, support, exact_radius=7, tail_stride=1):
    final = round_half_up(record.get("final_bucket"))
    if final is None:
        return []
    support = sorted(int(value) for value in support)
    centers = [
        value for value in (
            final,
            round_half_up(record.get("high_so_far")),
            round_half_up(record.get("forecast_high")),
            round_half_up(record.get("live_reading_temp")),
            round_half_up(record.get("climate_normal")),
        )
        if value is not None
    ]
    if not centers:
        centers = [final]
    low = max(min(support), min(centers) - exact_radius)
    high = min(max(support), max(centers) + exact_radius)
    rows = []

    def add(kind, value, value_hi=None):
        band = band_prediction_record(record, kind, value, value_hi=value_hi)
        outcome = band_outcome(kind, value, final, value_hi=value_hi)
        if outcome is None:
            return
        band["outcome"] = outcome
        distance = 0
        if kind == "lte":
            distance = max(0, final - int(value))
        elif kind == "gte":
            distance = max(0, int(value) - final)
        else:
            hi = int(value_hi) if value_hi is not None else int(value)
            distance = 0 if int(value) <= final <= hi else min(abs(final - int(value)), abs(final - hi))
        band["settlement_distance"] = distance
        # The replay blocker was overwhelmingly exact winning buckets and
        # late-day lock-in, so positives and late rows receive extra weight.
        weight = 1.0
        if outcome:
            weight *= 4.0 if kind == "eq" else 2.0
        if distance == 0:
            weight *= 1.5
        if int(record.get("cutoff_hour") or 0) >= 16:
            weight *= 2.0
        band["_sample_weight"] = weight
        rows.append(band)

    for value in range(low, high + 1):
        add("eq", value)
    for value in range(low, high):
        add("eq", value, value_hi=value + 1)
    for value in range(low, high + 1, max(1, int(tail_stride))):
        add("lte", value)
        add("gte", value)
    return rows


def build_band_rows(records, support):
    rows = []
    for record in records:
        rows.extend(synthetic_band_rows_for_record(record, support))
    return rows


def train_hour_model(train_rows, feature_names=None):
    train_frame = feature_frame(train_rows, feature_names=feature_names)
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([int(row["final_bucket"]) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=80,
        max_leaf_nodes=21,
        learning_rate=0.05,
        random_state=42,
    )
    model.fit(x_train, y_train)
    return model, imputer, feature_names


def predict_rows(model, imputer, feature_names, rows, support=None, epsilon=1e-4):
    frame = feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    probabilities = model.predict_proba(x_eval)
    classes = [int(value) for value in model.classes_]
    support = sorted(set(support or classes) | set(classes))
    output = []
    for row in probabilities:
        dist = {bucket: float(epsilon) for bucket in support}
        for bucket, probability in zip(classes, row):
            dist[int(bucket)] = dist.get(int(bucket), 0.0) + float(probability)
        total = sum(dist.values())
        output.append({bucket: probability / total for bucket, probability in dist.items()})
    return output


def distribution_probability(distribution, bucket):
    return float(distribution.get(int(bucket), 0.0))


def evaluate_distributions(rows, distributions):
    if not rows:
        return None
    losses = []
    briers = []
    classes = sorted({int(row["final_bucket"]) for row in rows} | {
        bucket for dist in distributions for bucket in dist
    })
    for row, dist in zip(rows, distributions):
        y_bucket = int(row["final_bucket"])
        probs = [float(dist.get(bucket, 0.0)) for bucket in classes]
        total = sum(probs)
        if total <= 0:
            probs = [1.0 / len(classes)] * len(classes)
        else:
            probs = [p / total for p in probs]
        p_true = max(1e-15, probs[classes.index(y_bucket)])
        losses.append(-math.log(p_true))
        briers.append(brier(distribution_probability(dist, y_bucket), 1.0))
    return {
        "n": len(rows),
        "logloss": sum(losses) / len(losses),
        "winning_bucket_brier": sum(briers) / len(briers),
    }


def train_band_hour_model(train_rows, feature_names=None):
    train_frame = band_feature_frame(train_rows, feature_names=feature_names)
    feature_names = list(train_frame.columns)
    imputer = SimpleImputer(strategy="median")
    x_train = imputer.fit_transform(train_frame)
    y_train = np.array([int(row["outcome"]) for row in train_rows])
    weights = np.array([float(row.get("_sample_weight", 1.0)) for row in train_rows])
    model = HistGradientBoostingClassifier(
        max_iter=90,
        max_leaf_nodes=31,
        learning_rate=0.05,
        random_state=42,
    )
    model.fit(x_train, y_train, sample_weight=weights)
    return model, imputer, feature_names


def predict_band_probabilities(model, imputer, feature_names, rows, temperature=1.0):
    if not rows:
        return []
    frame = band_feature_frame(rows, feature_names=feature_names)
    x_eval = imputer.transform(frame)
    probabilities = model.predict_proba(x_eval)
    classes = [int(value) for value in model.classes_]
    if 1 not in classes:
        return [1.0 if classes and classes[0] == 1 else 0.0 for _ in rows]
    idx = classes.index(1)
    return [
        temperature_scale_probability(float(row[idx]), temperature=temperature)
        for row in probabilities
    ]


def apply_band_postprocessing(probability, row, config=None):
    """Hard floor first, then calibrated live-floor postprocessing."""
    config = config or {}
    kind = row.get("band_kind")
    value = row.get("band_value")
    value_hi = row.get("band_value_hi")
    floor_bucket = row.get("observed_floor_bucket")
    hard = hard_floor_probability(kind, value, floor_bucket, value_hi=value_hi)
    if hard is not None:
        return hard
    p = clip_probability(probability)
    if config.get("support_floor_enabled", True):
        cap = support_floor_cap(
            kind,
            value,
            row.get("observed_support_bucket"),
            value_hi=value_hi,
            one_below_cap=config.get("support_floor_one_below_cap", 0.08),
            decay=config.get("support_floor_decay", 0.25),
        )
        if cap is not None:
            p = min(p, clip_probability(cap))
    if config.get("late_lockin_enabled", True):
        strength = max(0.0, min(1.0, float(row.get("late_lockin_strength") or 0.0)))
        if strength > 0:
            target = late_lockin_target(kind, value, floor_bucket, value_hi=value_hi)
            if target is not None:
                max_strength = max(0.0, min(1.0, float(config.get("late_lockin_max_strength", 0.85))))
                effective = min(strength, max_strength)
                p = clip_probability((1.0 - effective) * p + effective * target)
    if config.get("adjacent_calibration_enabled", False):
        p = apply_adjacent_calibration(p, row, config=config)
    return clip_probability(p)


def calibration_hour_bucket(hour):
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return "na"
    if hour <= 8:
        return "07-08"
    if hour <= 13:
        return "09-13"
    if hour <= 16:
        return "14-16"
    return "17-20"


def calibration_gap_bucket(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "na"
    if value < -0.5:
        return "below"
    if value < 0.5:
        return "0"
    if value < 1.5:
        return "+1"
    if value < 2.5:
        return "+2"
    if value < 3.5:
        return "+3"
    return "+4"


def _band_width_label(row):
    try:
        lo = float(row.get("band_value"))
        hi = float(row.get("band_value_hi"))
    except (TypeError, ValueError):
        return "single"
    return "range" if hi > lo else "single"


def adjacent_calibration_contexts(row):
    """Context fallbacks for market-specific above-floor eq/range leakage."""
    if row.get("band_kind") != "eq":
        return []
    try:
        if float(row.get("band_contains_floor") or 0.0) >= 0.5:
            return []
        if float(row.get("band_below_floor") or 0.0) >= 0.5:
            return []
    except (TypeError, ValueError):
        return []
    market_id = row.get("market_id") or "unknown"
    hour_bucket = calibration_hour_bucket(row.get("cutoff_hour") or row.get("candidate_cutoff_hour"))
    floor_gap = calibration_gap_bucket(row.get("band_mid_minus_high_so_far"))
    width = _band_width_label(row)
    return [
        f"market={market_id}|hour={hour_bucket}|width={width}|floor_gap={floor_gap}",
        f"market={market_id}|hour={hour_bucket}|floor_gap={floor_gap}",
        f"market={market_id}|floor_gap={floor_gap}",
        f"hour={hour_bucket}|floor_gap={floor_gap}",
        f"floor_gap={floor_gap}",
    ]


def fit_adjacent_calibration(
    rows,
    probabilities,
    min_rows=80,
    prior_rows=120.0,
    factor_min=0.15,
    factor_max=2.50,
):
    """Fit multiplicative calibration factors for above-floor eq/range bands."""
    stats = defaultdict(lambda: {"n": 0, "outcome_sum": 0.0, "prob_sum": 0.0})
    for row, probability in zip(rows, probabilities):
        contexts = adjacent_calibration_contexts(row)
        if not contexts:
            continue
        try:
            probability = clip_probability(probability)
            outcome = float(row.get("outcome") or 0.0)
        except (TypeError, ValueError):
            continue
        for context in contexts:
            stats[context]["n"] += 1
            stats[context]["outcome_sum"] += outcome
            stats[context]["prob_sum"] += probability

    contexts = {}
    for context, stat in sorted(stats.items()):
        n = int(stat["n"])
        if n < int(min_rows):
            continue
        prob_sum = float(stat["prob_sum"])
        if prob_sum <= 0:
            continue
        mean_probability = prob_sum / n
        # Smooth toward factor 1.0 by adding prior rows with the model's own
        # mean probability. This keeps sparse city/hour cells from becoming a
        # second model trained on noise.
        smoothed_observed = (
            float(stat["outcome_sum"]) + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        smoothed_predicted = (
            prob_sum + mean_probability * float(prior_rows)
        ) / (n + float(prior_rows))
        if smoothed_predicted <= 0:
            continue
        factor = smoothed_observed / smoothed_predicted
        factor = max(float(factor_min), min(float(factor_max), factor))
        contexts[context] = {
            "factor": factor,
            "n": n,
            "observed_rate": float(stat["outcome_sum"]) / n,
            "mean_probability": mean_probability,
        }

    return {
        "version": "adjacent_market_hour_floor_gap_v1",
        "min_rows": int(min_rows),
        "prior_rows": float(prior_rows),
        "factor_min": float(factor_min),
        "factor_max": float(factor_max),
        "context_count": len(contexts),
        "contexts": contexts,
    }


def adjacent_calibration_factor(row, config=None):
    config = config or {}
    calibration = config.get("adjacent_calibration") or config
    contexts = calibration.get("contexts") or {}
    if not contexts:
        return 1.0
    for context in adjacent_calibration_contexts(row):
        entry = contexts.get(context)
        if entry is None:
            continue
        if isinstance(entry, dict):
            return float(entry.get("factor", 1.0))
        return float(entry)
    return 1.0


def apply_adjacent_calibration(probability, row, config=None):
    factor = adjacent_calibration_factor(row, config=config)
    if factor == 1.0:
        return clip_probability(probability)
    return clip_probability(float(probability) * factor)


def predict_band_rows_for_bundle(bundle, rows, postprocess=True):
    probabilities = predict_band_probabilities(
        bundle["model"],
        bundle["imputer"],
        bundle["feature_names"],
        rows,
        temperature=bundle.get("temperature", 1.0),
    )
    if not postprocess:
        return probabilities
    config = bundle.get("postprocess") or {}
    return [
        apply_band_postprocessing(probability, row, config=config)
        for row, probability in zip(rows, probabilities)
    ]


def evaluate_band_predictions(rows, probabilities):
    if not rows:
        return None
    losses = [
        brier(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    log_losses = [
        binary_log_loss(float(probability), int(row["outcome"]))
        for row, probability in zip(rows, probabilities)
    ]
    positives = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row["outcome"]) == 1
    ]
    exact_winners = [
        (row, probability)
        for row, probability in positives
        if row.get("band_kind") == "eq" and int(row.get("settlement_distance") or 0) == 0
    ]
    late_rows = [
        (row, probability)
        for row, probability in zip(rows, probabilities)
        if int(row.get("cutoff_hour") or 0) >= 16
    ]
    return {
        "n": len(rows),
        "base_rate": sum(int(row["outcome"]) for row in rows) / len(rows),
        "brier": sum(losses) / len(losses),
        "logloss": sum(log_losses) / len(log_losses),
        "positive_mean_p": (
            sum(float(probability) for _, probability in positives) / len(positives)
            if positives else None
        ),
        "exact_winner_mean_p": (
            sum(float(probability) for _, probability in exact_winners) / len(exact_winners)
            if exact_winners else None
        ),
        "late_brier": (
            sum(brier(float(probability), int(row["outcome"])) for row, probability in late_rows) / len(late_rows)
            if late_rows else None
        ),
    }


def tune_temperature(rows, raw_probabilities):
    if not rows:
        return 1.0, None
    grid = [0.45, 0.55, 0.65, 0.75, 0.85, 1.0, 1.15, 1.30, 1.50, 1.75, 2.0]
    best = (1.0, float("inf"))
    for temperature in grid:
        probs = [temperature_scale_probability(p, temperature=temperature) for p in raw_probabilities]
        score = sum(brier(p, int(row["outcome"])) for row, p in zip(rows, probs)) / len(rows)
        if score < best[1]:
            best = (temperature, score)
    return best[0], best[1]


def train_pooled_models(records, holdout_year=None):
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    artifact = {
        "schema_version": "pooled_feature_hgb_v0.1",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "trained_at": datetime.now().isoformat(),
        "support": sorted({int(row["final_bucket"]) for row in records}),
        "models": {},
    }
    support = artifact["support"]
    validation_rows = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_rows = hour_rows
            eval_rows = []
        else:
            train_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        if len(train_rows) < 50:
            continue
        model, imputer, feature_names = train_hour_model(train_rows)
        eval_score = None
        market_scores = []
        if eval_rows:
            predictions = predict_rows(model, imputer, feature_names, eval_rows, support=support)
            eval_score = evaluate_distributions(eval_rows, predictions)
            for market_id in sorted({row["market_id"] for row in eval_rows}):
                market_eval = [row for row in eval_rows if row["market_id"] == market_id]
                market_predictions = [
                    pred for row, pred in zip(eval_rows, predictions)
                    if row["market_id"] == market_id
                ]
                score = evaluate_distributions(market_eval, market_predictions)
                if score:
                    market_scores.append({"market_id": market_id, **score})

        final_model, final_imputer, final_feature_names = train_hour_model(hour_rows)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(hour_rows),
        }
        validation_rows.append({
            "hour": hour,
            "train_rows": len(train_rows),
            "eval_rows": len(eval_rows),
            "eval_score": eval_score,
            "market_scores": market_scores,
        })
    return artifact, validation_rows


def train_pooled_band_models(records, holdout_year=None):
    by_hour = defaultdict(list)
    for row in records:
        by_hour[int(row["cutoff_hour"])].append(row)

    support = sorted({int(row["final_bucket"]) for row in records})
    artifact = {
        "schema_version": "pooled_feature_band_hgb_v0.3",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "family_unit": "F",
        "prediction_mode": "band_binary",
        "objective": "binary_market_band_brier_source_reliability",
        "trained_at": datetime.now().isoformat(),
        "support": support,
        "models": {},
        "postprocess": {
            "hard_floor_enabled": True,
            "support_floor_enabled": True,
            "support_floor_one_below_cap": 0.08,
            "support_floor_decay": 0.25,
            "late_lockin_enabled": True,
            "late_lockin_max_strength": 0.85,
            "adjacent_calibration_enabled": True,
            "adjacent_calibration": {},
            "partition_normalization_enabled": True,
            "partition_normalization_gamma": 1.25,
            "current_blend_enabled": True,
            "current_blend_default_alpha": 1.0,
            "current_blend_market_alpha": {
                "dallas": 0.0,
                "denver": 0.20,
                "houston": 0.20,
                "los-angeles": 0.20,
                "nyc": 0.20,
                "seattle": 0.20,
            },
        },
    }
    validation_rows = []
    calibration_rows = []
    calibration_probabilities = []
    for hour, hour_rows in sorted(by_hour.items()):
        if holdout_year is None:
            train_source_rows = hour_rows
            eval_source_rows = []
        else:
            train_source_rows = [row for row in hour_rows if int(row["year"]) != int(holdout_year)]
            eval_source_rows = [row for row in hour_rows if int(row["year"]) == int(holdout_year)]
        train_band_rows = build_band_rows(train_source_rows, support)
        if len(train_band_rows) < 200 or len({row["outcome"] for row in train_band_rows}) < 2:
            continue

        model, imputer, feature_names = train_band_hour_model(train_band_rows)
        eval_score = None
        raw_eval_score = None
        temperature = 1.0
        tuned_brier = None
        market_scores = []
        eval_band_rows = []
        post_probs = []
        if eval_source_rows:
            eval_band_rows = build_band_rows(eval_source_rows, support)
            if eval_band_rows:
                raw_probs = predict_band_probabilities(
                    model,
                    imputer,
                    feature_names,
                    eval_band_rows,
                    temperature=1.0,
                )
                raw_eval_score = evaluate_band_predictions(eval_band_rows, raw_probs)
                temperature, tuned_brier = tune_temperature(eval_band_rows, raw_probs)
                tuned_probs = [
                    temperature_scale_probability(probability, temperature=temperature)
                    for probability in raw_probs
                ]
                post_probs = [
                    apply_band_postprocessing(
                        probability,
                        row,
                        config=artifact["postprocess"],
                    )
                    for row, probability in zip(eval_band_rows, tuned_probs)
                ]
                calibration_rows.extend(eval_band_rows)
                calibration_probabilities.extend(post_probs)
                eval_score = evaluate_band_predictions(eval_band_rows, post_probs)
                for market_id in sorted({row["market_id"] for row in eval_band_rows}):
                    subset = [
                        (row, probability)
                        for row, probability in zip(eval_band_rows, post_probs)
                        if row["market_id"] == market_id
                    ]
                    score = evaluate_band_predictions(
                        [row for row, _ in subset],
                        [probability for _, probability in subset],
                    )
                    if score:
                        market_scores.append({"market_id": market_id, **score})

        final_band_rows = build_band_rows(hour_rows, support)
        final_model, final_imputer, final_feature_names = train_band_hour_model(final_band_rows)
        artifact["models"][str(hour)] = {
            "model": final_model,
            "imputer": final_imputer,
            "feature_names": final_feature_names,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "classes": [int(value) for value in final_model.classes_],
            "train_rows": len(final_band_rows),
            "source_rows": len(hour_rows),
            "temperature": temperature,
            "postprocess": dict(artifact["postprocess"]),
        }
        validation_rows.append({
            "hour": hour,
            "source_train_rows": len(train_source_rows),
            "band_train_rows": len(train_band_rows),
            "source_eval_rows": len(eval_source_rows),
            "temperature": temperature,
            "tuned_brier": tuned_brier,
            "raw_eval_score": raw_eval_score,
            "eval_score": eval_score,
            "market_scores": market_scores,
            "_eval_band_rows": eval_band_rows if eval_source_rows else [],
            "_post_probs": post_probs if eval_source_rows else [],
        })
    calibration = fit_adjacent_calibration(calibration_rows, calibration_probabilities)
    artifact["postprocess"]["adjacent_calibration"] = calibration
    for validation in validation_rows:
        eval_band_rows = validation.pop("_eval_band_rows", [])
        post_probs = validation.pop("_post_probs", [])
        if not eval_band_rows or not post_probs:
            continue
        calibrated_probs = [
            apply_adjacent_calibration(
                probability,
                row,
                config=artifact["postprocess"],
            )
            for row, probability in zip(eval_band_rows, post_probs)
        ]
        validation["eval_score"] = evaluate_band_predictions(eval_band_rows, calibrated_probs)
        market_scores = []
        for market_id in sorted({row["market_id"] for row in eval_band_rows}):
            subset = [
                (row, probability)
                for row, probability in zip(eval_band_rows, calibrated_probs)
                if row["market_id"] == market_id
            ]
            score = evaluate_band_predictions(
                [row for row, _ in subset],
                [probability for _, probability in subset],
            )
            if score:
                market_scores.append({"market_id": market_id, **score})
        validation["market_scores"] = market_scores
    for bundle in artifact["models"].values():
        bundle["postprocess"] = dict(artifact["postprocess"])
    return artifact, validation_rows


def write_artifact(artifact, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        pickle.dump(artifact, handle)
    return path


def write_report(path, records, counts, validation_rows, holdout_year, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# F-Family Pooled Feature Model",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total rows: {len(records)}",
        "",
        "## Hourly Validation",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Train Rows", "Eval Rows", "Eval LogLoss", "Winning-Bucket Brier"],
        [
            [
                f"{row['hour']:02d}:00",
                row["train_rows"],
                row["eval_rows"],
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("winning_bucket_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("logloss")),
                fmt_num(score.get("winning_bucket_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "LogLoss", "Winning-Bucket Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_band_report(path, records, counts, validation_rows, holdout_year, artifact_path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# F-Family Pooled Band Model v0.3",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"Artifact: `{artifact_path}`",
        f"Holdout year: {holdout_year or '-'}",
        "",
        "## Objective",
        "",
        "This candidate trains a binary model directly on market-band outcomes",
        "(`eq`/range, `lte`, and `gte`) instead of training an exact-bucket",
        "classifier and summing it after the fact. Training rows are generated",
        "from historical WU feature records and synthetic market-style bands;",
        "the pinned promotion corpus remains out-of-sample replay evidence.",
        "",
        "Hard WU-floor rules are applied deterministically, and a late-day",
        "lock-in blend concentrates probabilities toward the printed high when",
        "the day is late and cooling.",
        "",
        "v0.3 adds static per-market source-reliability priors learned from",
        "WU-vs-METAR/ASOS/GHCNh/reanalysis daily overlaps. These are source",
        "trust features, not same-day final redundant highs, so the candidate",
        "does not leak settlement information into intraday training rows.",
        "",
        "## Dataset",
        "",
    ]
    lines += markdown_table(
        ["Market", "Source Rows"],
        [[market_id, count] for market_id, count in sorted(counts.items())],
    )
    lines += [
        "",
        f"Total source rows: {len(records)}",
        "",
        "## Hourly Holdout Validation",
        "",
    ]
    lines += markdown_table(
        [
            "Hour", "Source Train", "Band Train", "Source Eval",
            "Temp", "Raw Brier", "Post Brier", "LogLoss",
            "Positive Mean P", "Exact Winner Mean P", "Late Brier",
        ],
        [
            [
                f"{row['hour']:02d}:00",
                row["source_train_rows"],
                row["band_train_rows"],
                row["source_eval_rows"],
                fmt_num(row.get("temperature")),
                fmt_num((row.get("raw_eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("brier")),
                fmt_num((row.get("eval_score") or {}).get("logloss")),
                fmt_num((row.get("eval_score") or {}).get("positive_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("exact_winner_mean_p")),
                fmt_num((row.get("eval_score") or {}).get("late_brier")),
            ]
            for row in validation_rows
        ],
    )
    lines += ["", "## Holdout By Market", ""]
    market_rows = []
    for row in validation_rows:
        for score in row.get("market_scores") or []:
            market_rows.append([
                score["market_id"],
                f"{row['hour']:02d}:00",
                score["n"],
                fmt_num(score.get("brier")),
                fmt_num(score.get("logloss")),
                fmt_num(score.get("positive_mean_p")),
                fmt_num(score.get("exact_winner_mean_p")),
                fmt_num(score.get("late_brier")),
            ])
    lines += markdown_table(
        ["Market", "Hour", "Rows", "Brier", "LogLoss", "Positive Mean P",
         "Exact Winner Mean P", "Late Brier"],
        market_rows,
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def parse_hours(value):
    if not value:
        return tuple(INTRADAY_CUTOFF_HOURS)
    return tuple(int(item.strip()) for item in str(value).split(",") if item.strip())


def main():
    parser = argparse.ArgumentParser(description="Train the F-family pooled feature model starter.")
    parser.add_argument("--family-unit", default="F", choices=["F"])
    parser.add_argument("--objective", default="bucket", choices=["bucket", "band"],
                        help="bucket=v0.1 exact-bucket classifier; band=v0.2 direct market-band classifier.")
    parser.add_argument("--hours", default=",".join(str(hour) for hour in INTRADAY_CUTOFF_HOURS))
    parser.add_argument("--max-days-per-market", type=int, default=0,
                        help="Optional newest-day cap for quick research/smoke runs; 0 uses all days.")
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--artifact", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    records, counts = build_family_dataset(
        unit=args.family_unit,
        cutoff_hours=parse_hours(args.hours),
        max_days_per_market=args.max_days_per_market or None,
    )
    if not records:
        raise SystemExit("No pooled family records available.")
    if args.objective == "band":
        artifact_path_arg = args.artifact or str(DEFAULT_BAND_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_BAND_REPORT)
        artifact, validation_rows = train_pooled_band_models(records, holdout_year=args.holdout_year)
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_band_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
        )
    else:
        artifact_path_arg = args.artifact or str(DEFAULT_ARTIFACT)
        report_path_arg = args.out or str(DEFAULT_REPORT)
        artifact, validation_rows = train_pooled_models(records, holdout_year=args.holdout_year)
        artifact_path = write_artifact(artifact, artifact_path_arg)
        report_path = write_report(
            report_path_arg,
            records,
            counts,
            validation_rows,
            args.holdout_year,
            artifact_path,
        )
    print(
        f"Wrote pooled {args.family_unit}-family {args.objective} artifact to {artifact_path} "
        f"and report to {report_path} over {len(records)} rows."
    )


if __name__ == "__main__":
    main()
