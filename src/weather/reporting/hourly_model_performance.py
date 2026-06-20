"""Hour-by-hour settlement-scored model performance audit.

The broad backtest report already contains a capture-hour table.  This module
turns that slice into a repeatable audit surface with stable JSON/CSV/Markdown
outputs and driver summaries for the best and worst hours.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from weather.backtesting.settlement_io import load_market_day_label
from weather.backtesting.tape_scoring import (
    backtest_tape,
    load_feature_vectors,
    timestamp_key,
)
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path, relative_to_repo
from weather.reporting.formatting import markdown_table
from weather.scoring.metrics import (
    binary_log_loss,
    brier,
    expected_calibration_error,
    missing,
    safe_float,
    score_rows,
    winner_band_catchup,
)


SCHEMA_VERSION = "hourly_model_performance_v0.3"
HOURLY_GATE_SCHEMA_VERSION = "hourly_performance_gate_v0.1"
REMEDIATION_REGISTRY_SCHEMA_VERSION = "hourly_remediation_registry_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_LABELS_CSV = DEFAULT_BACKTEST_ROOT / "market_day_labels.csv"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "hourly_model_performance.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "hourly_model_performance_report.md"
DEFAULT_CSV_OUT = DEFAULT_BACKTEST_ROOT / "hourly_model_performance_by_hour.csv"
DEFAULT_CUTOFF_REGIME_CONTEXT = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_weighting.json"
DEFAULT_FORECAST_PROFILE_CONTEXT = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_calibration.json"
DEFAULT_QUALITY_GRADES = ("complete", "manual_override")
DEFAULT_THRESHOLDS = (0.05, 0.10, 0.15)
DEFAULT_TOP_HOURS = 3
DEFAULT_MIN_ROWS = 30
DEFAULT_MIN_REGIME_MARKET_DAYS = 10
DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE = 0.003
DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE = 0.01
DEFAULT_EARLY_ECE_MAX = 0.12
MARKET_BLEND_GRID = (0.0, 0.25, 0.50, 0.75, 1.0)
PARTITION_POWER_GRID = (0.75, 1.0, 1.25, 1.50, 2.0)
FORECAST_CENTERING_BLEND_GRID = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50)
FORECAST_CENTERING_SIGMA = 1.25

RAW_DRIVER_COLUMNS = (
    "wu_history_high_c",
    "wu_history_high",
    "wu_history_high_native",
    "wu_current_c",
    "wu_current",
    "wu_current_native",
    "wu_max_since_7am_c",
    "wu_max_since_7am",
    "wu_max_since_7am_native",
    "eccc_swob_max_c",
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "eccc_forecast_high_c",
)

DRIVER_NUMERIC_FIELDS = (
    "feature_high_so_far",
    "feature_current_temp",
    "feature_rise_from_7am",
    "feature_forecast_high",
    "feature_forecast_gap",
    "feature_live_reading_minus_high",
    "feature_minutes_since_cutoff",
    "raw_wu_history_high_c",
    "raw_wu_current_c",
    "raw_wu_max_since_7am_c",
    "raw_weather_forecast_max_c",
    "raw_open_meteo_max_c",
)

HOUR_REGIME_LABELS = {
    "early_morning": "00:00-08:00",
    "ramp_midday": "09:00-14:00",
    "late_day": "15:00-19:00",
    "lock_in": "20:00-23:00",
}


def utc_now():
    return datetime.now(timezone.utc)


def parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def parse_csv_values(value):
    if value in (None, ""):
        return []
    if isinstance(value, (tuple, list, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


def parse_quality_grades(value):
    parsed = parse_csv_values(value)
    return tuple(parsed) if parsed else tuple(DEFAULT_QUALITY_GRADES)


def safe_int(value):
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def hour_regime(hour):
    if hour is None:
        return None
    hour = int(hour)
    if 0 <= hour <= 8:
        return "early_morning"
    if 9 <= hour <= 14:
        return "ramp_midday"
    if 15 <= hour <= 19:
        return "late_day"
    if 20 <= hour <= 23:
        return "lock_in"
    return None


def mean(values):
    cleaned = [float(value) for value in values if value is not None and not math.isnan(float(value))]
    return sum(cleaned) / len(cleaned) if cleaned else None


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def row_date(row):
    value = row.get("target_date")
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None
    return date_from_event_slug(row.get("event_slug"))


def label_folder(row, snapshots_root=DEFAULT_SNAPSHOTS_ROOT):
    tape_path = row.get("snapshot_tape_path")
    if tape_path:
        path = Path(tape_path)
        if path.exists():
            return path.parent
    slug = row.get("event_slug")
    if not slug:
        return None
    return Path(snapshots_root) / slug


def label_from_folder(folder):
    label = load_market_day_label(folder)
    if label:
        return label
    return {}


def discover_labeled_folders(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
    markets=None,
    start_date=None,
    end_date=None,
):
    labels_csv = Path(labels_csv)
    snapshots_root = Path(snapshots_root)
    allowed_quality = set(quality_grades or [])
    allowed_markets = set(markets or [])
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    selected = []
    skipped = Counter()
    seen = set()

    if labels_csv.exists():
        candidates = read_csv_rows(labels_csv)
    else:
        candidates = []
        for tape in sorted(snapshots_root.glob("*/snapshots_long.csv")):
            label = label_from_folder(tape.parent)
            if label:
                candidates.append(label)

    for row in candidates:
        slug = row.get("event_slug")
        market_id = row.get("market_id")
        if not slug:
            skipped["missing_slug"] += 1
            continue
        if allowed_markets and market_id not in allowed_markets:
            skipped["market"] += 1
            continue
        quality = row.get("quality_grade")
        if allowed_quality and quality not in allowed_quality:
            skipped["quality"] += 1
            continue
        if row.get("settlement_bucket") in (None, ""):
            skipped["missing_settlement"] += 1
            continue
        target_date = row_date(row)
        if start and (target_date is None or target_date < start):
            skipped["start_date"] += 1
            continue
        if end and (target_date is None or target_date > end):
            skipped["end_date"] += 1
            continue
        folder = label_folder(row, snapshots_root)
        if not folder or not (folder / "snapshots_long.csv").exists():
            skipped["missing_tape"] += 1
            continue
        key = str((folder / "snapshots_long.csv").resolve())
        if key in seen:
            skipped["duplicate"] += 1
            continue
        seen.add(key)
        selected.append({"folder": folder, "label": row})

    selected.sort(key=lambda item: (item["label"].get("market_id") or "", item["label"].get("target_date") or ""))
    return selected, dict(skipped)


def first_present(row, *keys):
    for key in keys:
        if key in row and not missing(row.get(key)) and row.get(key) != "":
            return row.get(key)
    return None


def attach_raw_drivers(scoring_row, raw_row):
    for column in RAW_DRIVER_COLUMNS:
        value = raw_row.get(column)
        if not missing(value) and value != "":
            scoring_row[f"raw_{column}"] = value

    scoring_row["model_edge"] = scoring_row["model_probability"] - scoring_row["market_yes"]
    scoring_row["model_brier_component"] = brier(scoring_row["model_probability"], scoring_row["outcome"])
    scoring_row["market_brier_component"] = brier(scoring_row["market_yes"], scoring_row["outcome"])
    scoring_row["model_logloss_component"] = binary_log_loss(
        scoring_row["model_probability"],
        scoring_row["outcome"],
    )
    scoring_row["market_logloss_component"] = binary_log_loss(
        scoring_row["market_yes"],
        scoring_row["outcome"],
    )
    scoring_row["raw_current_high"] = first_present(
        scoring_row,
        "raw_wu_max_since_7am_c",
        "raw_wu_history_high_c",
        "raw_wu_max_since_7am",
        "raw_wu_history_high",
        "feature_high_so_far",
    )
    return scoring_row


def score_folder(folder, label, thresholds=DEFAULT_THRESHOLDS):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    frame = pd.read_csv(tape)
    slug = label.get("event_slug") or folder.name
    target_date = row_date(label) or date_from_event_slug(slug)
    settlement_bucket = safe_int(label.get("settlement_bucket"))
    if settlement_bucket is None:
        return [], {"folder": str(folder), "rows": 0, "skipped": "missing_settlement"}

    rows, _, _, _ = backtest_tape(
        frame,
        settlement_bucket,
        thresholds,
        target_date=target_date,
        feature_index=load_feature_vectors(folder),
    )
    spec = spec_for_slug(slug)
    for row in rows:
        raw = frame.iloc[int(row["row_order"])].to_dict()
        row["market_id"] = label.get("market_id") or (spec.id if spec else None)
        row["city"] = label.get("city") or (spec.city_label if spec else None)
        row["quality_grade"] = label.get("quality_grade")
        row["settlement_bucket"] = settlement_bucket
        row["settlement_unit"] = label.get("settlement_unit") or (spec.display_unit if spec else None)
        row["settlement_source"] = label.get("settlement_source")
        row["snapshot_count_for_day"] = safe_int(label.get("snapshot_count"))
        row["band_count_for_day"] = safe_int(label.get("band_count"))
        row["coverage_clean"] = label.get("coverage_clean")
        row["capture_ratio"] = safe_float(label.get("capture_ratio"))
        attach_raw_drivers(row, raw)

    return rows, {
        "folder": str(folder),
        "event_slug": slug,
        "market_id": label.get("market_id") or (spec.id if spec else None),
        "target_date": target_date.isoformat() if target_date else None,
        "quality_grade": label.get("quality_grade"),
        "settlement_bucket": settlement_bucket,
        "settlement_unit": label.get("settlement_unit") or (spec.display_unit if spec else None),
        "snapshot_count": int(frame["snapshot_id"].nunique()) if "snapshot_id" in frame else None,
        "band_count": int(frame["range_label"].nunique()) if "range_label" in frame else None,
        "rows": len(rows),
    }


def hourly_checkpoint_rows(rows):
    """First available row per market-day-band-hour.

    Snapshot loops can capture multiple times per hour.  For the headline audit,
    each local hour gets at most one observation per market-day-band so cadence
    changes do not dominate the hour ranking.
    """
    selected = {}
    for row in rows:
        hour = row.get("cutoff_hour")
        if hour is None:
            continue
        key = (row.get("market_id"), row.get("target_date"), row.get("band"), int(hour))
        if key not in selected or timestamp_key(row) < timestamp_key(selected[key]):
            selected[key] = row
    return [selected[key] for key in sorted(selected, key=lambda item: (str(item[0]), str(item[1]), str(item[2]), int(item[3])))]


def rows_for_group(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        group = key(row) if callable(key) else row.get(key)
        grouped[group].append(row)
    return grouped


def numeric_mean(rows, key):
    return mean(safe_float(row.get(key)) for row in rows)


def distinct_count(rows, key):
    return len({row.get(key) for row in rows if row.get(key) not in (None, "")})


def probability_means(rows):
    winners = [row for row in rows if row.get("outcome") == 1]
    losers = [row for row in rows if row.get("outcome") == 0]
    return {
        "winner_model_probability": numeric_mean(winners, "model_probability"),
        "winner_market_probability": numeric_mean(winners, "market_yes"),
        "loser_model_probability": numeric_mean(losers, "model_probability"),
        "loser_market_probability": numeric_mean(losers, "market_yes"),
    }


def snapshot_key(row):
    return (
        row.get("market_id"),
        row.get("target_date"),
        row.get("snapshot_id"),
        row.get("cutoff_hour"),
    )


def band_sort_key(row):
    return (
        safe_float(row.get("bin_value_c")) is None,
        safe_float(row.get("bin_value_c")) or 0.0,
        safe_float(row.get("bin_value_hi")) or safe_float(row.get("bin_value_c")) or 0.0,
        safe_int(row.get("row_order")) or 0,
    )


def probability_partition_metrics(group_rows, probability_key):
    rows = list(group_rows)
    probabilities = [max(0.0, safe_float(row.get(probability_key)) or 0.0) for row in rows]
    total = sum(probabilities)
    if not rows or total <= 0:
        return {}

    normalized = [probability / total for probability in probabilities]
    entropy = -sum(probability * math.log(probability) for probability in normalized if probability > 0)
    normalized_entropy = entropy / math.log(len(rows)) if len(rows) > 1 else 0.0
    top_index = max(range(len(rows)), key=lambda index: probabilities[index])
    winner_indexes = [index for index, row in enumerate(rows) if row.get("outcome") == 1]
    winner_index = winner_indexes[0] if winner_indexes else None
    ranked_indexes = sorted(range(len(rows)), key=lambda index: probabilities[index], reverse=True)
    winner_rank = None
    top_is_winner = None
    winner_probability = None
    adjacent_winner_mass = None

    if winner_index is not None:
        winner_probability = probabilities[winner_index]
        winner_rank = ranked_indexes.index(winner_index) + 1
        top_is_winner = 1.0 if top_index == winner_index else 0.0

        sorted_rows = sorted(enumerate(rows), key=lambda item: band_sort_key(item[1]))
        sorted_original_indexes = [index for index, _ in sorted_rows]
        winner_position = sorted_original_indexes.index(winner_index)
        adjacent_indexes = {
            sorted_original_indexes[position]
            for position in range(max(0, winner_position - 1), min(len(sorted_original_indexes), winner_position + 2))
        }
        adjacent_winner_mass = sum(probabilities[index] for index in adjacent_indexes)

    prefix = "model" if probability_key == "model_probability" else "market"
    return {
        f"{prefix}_total_probability": total,
        f"{prefix}_norm_entropy": normalized_entropy,
        f"{prefix}_effective_bands": math.exp(entropy),
        f"{prefix}_top_probability": max(probabilities),
        f"{prefix}_top_share": max(normalized),
        f"{prefix}_winner_probability": winner_probability,
        f"{prefix}_winner_rank": winner_rank,
        f"{prefix}_top_is_winner": top_is_winner,
        f"{prefix}_adjacent_winner_mass": adjacent_winner_mass,
    }


def snapshot_partition_stats(rows):
    grouped = rows_for_group(rows, snapshot_key)
    output = []
    for key, group_rows in grouped.items():
        if not group_rows:
            continue
        model = probability_partition_metrics(group_rows, "model_probability")
        market = probability_partition_metrics(group_rows, "market_yes")
        if not model and not market:
            continue
        row = {
            "market_id": key[0],
            "target_date": key[1],
            "snapshot_id": key[2],
            "cutoff_hour": key[3],
            "band_count": len(group_rows),
        }
        row.update(model)
        row.update(market)
        if row.get("model_effective_bands") is not None and row.get("market_effective_bands") is not None:
            row["effective_band_gap"] = row["model_effective_bands"] - row["market_effective_bands"]
        if row.get("model_norm_entropy") is not None and row.get("market_norm_entropy") is not None:
            row["norm_entropy_gap"] = row["model_norm_entropy"] - row["market_norm_entropy"]
        if row.get("model_top_probability") is not None and row.get("market_top_probability") is not None:
            row["top_probability_gap"] = row["model_top_probability"] - row["market_top_probability"]
        if row.get("model_winner_probability") is not None and row.get("market_winner_probability") is not None:
            row["winner_probability_gap"] = row["model_winner_probability"] - row["market_winner_probability"]
        if row.get("model_winner_rank") is not None and row.get("market_winner_rank") is not None:
            row["winner_rank_gap"] = row["model_winner_rank"] - row["market_winner_rank"]
        if row.get("model_adjacent_winner_mass") is not None and row.get("market_adjacent_winner_mass") is not None:
            row["adjacent_winner_mass_gap"] = row["model_adjacent_winner_mass"] - row["market_adjacent_winner_mass"]
        output.append(row)
    return output


def partition_mean(stats, key):
    return mean(stat.get(key) for stat in stats)


def summarize_partitions(rows):
    stats = snapshot_partition_stats(rows)
    if not stats:
        return {}
    return {
        "partition_snapshots": len(stats),
        "partition_mean_band_count": partition_mean(stats, "band_count"),
        "partition_model_effective_bands": partition_mean(stats, "model_effective_bands"),
        "partition_market_effective_bands": partition_mean(stats, "market_effective_bands"),
        "partition_effective_band_gap": partition_mean(stats, "effective_band_gap"),
        "partition_model_norm_entropy": partition_mean(stats, "model_norm_entropy"),
        "partition_market_norm_entropy": partition_mean(stats, "market_norm_entropy"),
        "partition_norm_entropy_gap": partition_mean(stats, "norm_entropy_gap"),
        "partition_model_top_probability": partition_mean(stats, "model_top_probability"),
        "partition_market_top_probability": partition_mean(stats, "market_top_probability"),
        "partition_top_probability_gap": partition_mean(stats, "top_probability_gap"),
        "partition_model_winner_probability": partition_mean(stats, "model_winner_probability"),
        "partition_market_winner_probability": partition_mean(stats, "market_winner_probability"),
        "partition_winner_probability_gap": partition_mean(stats, "winner_probability_gap"),
        "partition_model_winner_rank": partition_mean(stats, "model_winner_rank"),
        "partition_market_winner_rank": partition_mean(stats, "market_winner_rank"),
        "partition_winner_rank_gap": partition_mean(stats, "winner_rank_gap"),
        "partition_model_top_is_winner_rate": partition_mean(stats, "model_top_is_winner"),
        "partition_market_top_is_winner_rate": partition_mean(stats, "market_top_is_winner"),
        "partition_model_adjacent_winner_mass": partition_mean(stats, "model_adjacent_winner_mass"),
        "partition_market_adjacent_winner_mass": partition_mean(stats, "market_adjacent_winner_mass"),
        "partition_adjacent_winner_mass_gap": partition_mean(stats, "adjacent_winner_mass_gap"),
    }


def summarize_rows(rows):
    score = score_rows(rows)
    if not score:
        return None
    summary = dict(score)
    summary.update({
        "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
        "markets": distinct_count(rows, "market_id"),
        "snapshots": distinct_count(rows, "snapshot_id"),
        "model_ece": expected_calibration_error(rows, "model_probability"),
        "market_ece": expected_calibration_error(rows, "market_yes"),
        "mean_model_probability": numeric_mean(rows, "model_probability"),
        "mean_market_probability": numeric_mean(rows, "market_yes"),
        "mean_edge": numeric_mean(rows, "model_edge"),
        "mean_abs_edge": mean(abs(safe_float(row.get("model_edge"))) for row in rows if safe_float(row.get("model_edge")) is not None),
    })
    summary.update(probability_means(rows))
    summary.update(summarize_partitions(rows))
    summary.update(winner_band_catchup(rows))
    for field in DRIVER_NUMERIC_FIELDS:
        value = numeric_mean(rows, field)
        if value is not None:
            summary[f"mean_{field}"] = value
    return summary


def summarize_by_hour(rows):
    output = []
    grouped = rows_for_group(rows, "cutoff_hour")
    for hour, hour_rows in sorted(grouped.items(), key=lambda item: int(item[0]) if item[0] is not None else 99):
        if hour is None:
            continue
        summary = summarize_rows(hour_rows)
        if summary:
            summary["hour"] = int(hour)
            summary["hour_label"] = f"{int(hour):02d}:00"
            output.append(summary)
    return output


def summarize_by_hour_regime(rows):
    output = []
    grouped = rows_for_group(rows, lambda row: hour_regime(row.get("cutoff_hour")))
    order = list(HOUR_REGIME_LABELS)
    for regime in order:
        regime_rows = grouped.get(regime, [])
        summary = summarize_rows(regime_rows)
        if summary:
            summary["regime"] = regime
            summary["regime_label"] = HOUR_REGIME_LABELS[regime]
            output.append(summary)
    return output


def rank_hours(by_hour, min_rows=DEFAULT_MIN_ROWS, top_hours=DEFAULT_TOP_HOURS):
    eligible = [row for row in by_hour if int(row.get("n") or 0) >= int(min_rows)]
    best = sorted(
        eligible,
        key=lambda row: (row.get("model_brier", math.inf), row.get("model_logloss", math.inf), -int(row.get("n") or 0)),
    )[:top_hours]
    worst = sorted(
        eligible,
        key=lambda row: (row.get("model_brier", -math.inf), row.get("model_logloss", -math.inf), int(row.get("n") or 0)),
        reverse=True,
    )[:top_hours]
    return best, worst


def clamp_probability(value):
    return max(0.0, min(1.0, float(value)))


def rows_with_probability(rows, probability_fn):
    output = []
    for row in rows:
        copy = dict(row)
        probability = probability_fn(row)
        if probability is None:
            continue
        copy["model_probability"] = clamp_probability(probability)
        output.append(copy)
    return output


def market_blend_rows(rows, alpha):
    alpha = max(0.0, min(1.0, float(alpha)))
    return rows_with_probability(
        rows,
        lambda row: (
            (1.0 - alpha) * float(row["model_probability"])
            + alpha * float(row["market_yes"])
        ),
    )


def partition_power_rows(rows, gamma):
    """Normalize each snapshot's band partition after applying p**gamma.

    This is a pure model-output probe.  It deliberately does not use market
    prices or outcomes at serving time, but it can reveal whether the hour's
    failure is mostly calibration/sharpness versus the distribution being
    centered on the wrong band.
    """
    gamma = max(0.05, float(gamma))
    output = [dict(row) for row in rows]
    grouped = defaultdict(list)
    for index, row in enumerate(output):
        grouped[(
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("cutoff_hour"),
        )].append(index)
    for indexes in grouped.values():
        weights = [
            max(1e-12, float(output[index]["model_probability"])) ** gamma
            for index in indexes
        ]
        total = sum(weights)
        if total <= 0:
            continue
        for index, weight in zip(indexes, weights):
            output[index]["model_probability"] = weight / total
    return output


def normal_cdf(value, mean_value, sigma):
    sigma = max(0.05, float(sigma))
    z = (float(value) - float(mean_value)) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def forecast_anchor_probability(row, sigma=FORECAST_CENTERING_SIGMA):
    forecast_high = first_present(
        row,
        "feature_forecast_high",
        "raw_weather_forecast_max_c",
        "raw_open_meteo_max_c",
    )
    value = safe_float(row.get("bin_value_c"))
    value_hi = safe_float(row.get("bin_value_hi"))
    if forecast_high is None or value is None:
        return None
    forecast_high = safe_float(forecast_high)
    if forecast_high is None:
        return None
    value_hi = value if value_hi is None else value_hi
    kind = row.get("bin_type") or row.get("bin_kind") or "eq"
    if kind == "lte":
        probability = normal_cdf(value + 0.5, forecast_high, sigma)
    elif kind == "gte":
        probability = 1.0 - normal_cdf(value - 0.5, forecast_high, sigma)
    else:
        lo = min(value, value_hi)
        hi = max(value, value_hi)
        probability = normal_cdf(hi + 0.5, forecast_high, sigma) - normal_cdf(lo - 0.5, forecast_high, sigma)
    return clamp_probability(probability)


def forecast_centering_rows(rows, alpha):
    """Blend model probabilities toward a forecast-high anchored band projection.

    This is a no-market probe for Item 147. It uses only serve-time forecast
    geometry, not outcomes or market prices, to test whether early-hour failure
    is mostly poor centering around the forecast anchor.
    """
    alpha = max(0.0, min(1.0, float(alpha)))
    def probability(row):
        anchor_probability = forecast_anchor_probability(row)
        if anchor_probability is None:
            return float(row["model_probability"])
        return (1.0 - alpha) * float(row["model_probability"]) + alpha * float(anchor_probability)

    return rows_with_probability(rows, probability)


def score_variant_by_hour(rows, transform_fn, parameter_values):
    by_hour_rows = rows_for_group(rows, "cutoff_hour")
    output = []
    for hour, hour_rows in sorted(by_hour_rows.items(), key=lambda item: int(item[0]) if item[0] is not None else 99):
        if hour is None:
            continue
        base = score_rows(hour_rows)
        if not base:
            continue
        variants = []
        for value in parameter_values:
            variant_rows = transform_fn(hour_rows, value)
            score = score_rows(variant_rows)
            if not score:
                continue
            variants.append({
                "parameter": value,
                "model_brier": score["model_brier"],
                "model_logloss": score["model_logloss"],
                "brier_delta_vs_base": score["model_brier"] - base["model_brier"],
                "logloss_delta_vs_base": score["model_logloss"] - base["model_logloss"],
            })
        if variants:
            best = min(variants, key=lambda row: (row["model_brier"], row["model_logloss"]))
            output.append({
                "hour": int(hour),
                "hour_label": f"{int(hour):02d}:00",
                "base_model_brier": base["model_brier"],
                "base_model_logloss": base["model_logloss"],
                "best": best,
                "variants": variants,
            })
    return output


def remediation_candidates(rows):
    market_blend = score_variant_by_hour(
        rows,
        lambda hour_rows, alpha: market_blend_rows(hour_rows, alpha),
        MARKET_BLEND_GRID,
    )
    partition_power = score_variant_by_hour(
        rows,
        lambda hour_rows, gamma: partition_power_rows(hour_rows, gamma),
        PARTITION_POWER_GRID,
    )
    forecast_centering = score_variant_by_hour(
        rows,
        lambda hour_rows, alpha: forecast_centering_rows(hour_rows, alpha),
        FORECAST_CENTERING_BLEND_GRID,
    )
    early_hours = {0, 1, 2, 3, 4, 5, 6, 7, 8}
    return {
        "market_blend": {
            "description": "Blend model probability toward market yes price: (1-alpha)*model + alpha*market.",
            "uses_market_prices": True,
            "grid": list(MARKET_BLEND_GRID),
            "by_hour": market_blend,
            "early_hours": [row for row in market_blend if row["hour"] in early_hours],
        },
        "partition_power": {
            "description": "Normalize each snapshot partition after p**gamma; gamma < 1 softens, gamma > 1 sharpens.",
            "uses_market_prices": False,
            "grid": list(PARTITION_POWER_GRID),
            "by_hour": partition_power,
            "early_hours": [row for row in partition_power if row["hour"] in early_hours],
        },
        "forecast_centering": {
            "description": (
                "Blend model probability toward a forecast-high anchored Gaussian "
                "band projection; no market prices are used."
            ),
            "uses_market_prices": False,
            "grid": list(FORECAST_CENTERING_BLEND_GRID),
            "sigma": FORECAST_CENTERING_SIGMA,
            "by_hour": forecast_centering,
            "early_hours": [row for row in forecast_centering if row["hour"] in early_hours],
        },
    }


def _weighted_mean(items, value_key, weight_key="n"):
    total_weight = 0.0
    total = 0.0
    for item in items:
        value = safe_float(item.get(value_key))
        weight = safe_float(item.get(weight_key)) or 0.0
        if value is None or weight <= 0:
            continue
        total += value * weight
        total_weight += weight
    return total / total_weight if total_weight else None


def _remediation_owner(probe_name, uses_market_prices):
    if uses_market_prices:
        return {
            "owner": "market-making risk overlay",
            "claim_lane": "quote_risk_control_only",
            "counts_toward_weather_model_promotion": False,
        }
    if probe_name == "partition_power":
        return {
            "owner": "model calibration",
            "claim_lane": "weather_model_output_shape",
            "counts_toward_weather_model_promotion": True,
        }
    if probe_name == "forecast_centering":
        return {
            "owner": "early-hour forecast-centering candidate",
            "claim_lane": "weather_model_forecast_relative_centering",
            "counts_toward_weather_model_promotion": True,
        }
    return {
        "owner": "model remediation",
        "claim_lane": "weather_model_candidate",
        "counts_toward_weather_model_promotion": True,
    }


def _interpret_remediation(probe_name, delta, uses_market_prices):
    if delta is None:
        return "no comparable rows"
    if uses_market_prices:
        if delta < -0.003:
            return "risk overlay reduces error but cannot count as weather-model promotion evidence"
        if delta <= 0.003:
            return "risk overlay is inconclusive for this regime"
        return "risk overlay worsens this regime"
    if delta < -0.003:
        return "weather-only probe improves this regime and should be promoted to a candidate lane"
    if delta <= 0.003:
        return "weather-only probe is too small to explain the timing failure"
    return "weather-only probe regresses this regime"


def build_remediation_registry(remediation, by_hour):
    hour_summary = {int(row["hour"]): row for row in by_hour if row.get("hour") is not None}
    rows = []
    for probe_name, probe in sorted((remediation or {}).items()):
        uses_market_prices = bool(probe.get("uses_market_prices"))
        owner = _remediation_owner(probe_name, uses_market_prices)
        by_hour_rows = {int(row["hour"]): row for row in probe.get("by_hour") or []}
        for regime, label in HOUR_REGIME_LABELS.items():
            hours = [
                hour for hour in by_hour_rows
                if hour_regime(hour) == regime and hour in hour_summary
            ]
            if not hours:
                continue
            joined = []
            best_parameters = []
            for hour in sorted(hours):
                probe_row = by_hour_rows[hour]
                summary = hour_summary[hour]
                best = probe_row.get("best") or {}
                joined.append({
                    "hour": hour,
                    "n": summary.get("n"),
                    "markets": summary.get("markets"),
                    "market_days": summary.get("market_days"),
                    "brier_delta_vs_base": best.get("brier_delta_vs_base"),
                    "logloss_delta_vs_base": best.get("logloss_delta_vs_base"),
                })
                best_parameters.append(best.get("parameter"))
            brier_delta = _weighted_mean(joined, "brier_delta_vs_base")
            logloss_delta = _weighted_mean(joined, "logloss_delta_vs_base")
            rows.append({
                "schema_version": REMEDIATION_REGISTRY_SCHEMA_VERSION,
                "probe_name": probe_name,
                "hour_regime": regime,
                "hour_regime_label": label,
                "metric": "model_brier",
                "metric_delta": brier_delta,
                "logloss_delta": logloss_delta,
                "market_count": max((safe_int(row.get("markets")) or 0 for row in joined), default=0),
                "market_day_count": max((safe_int(row.get("market_days")) or 0 for row in joined), default=0),
                "row_count": sum(safe_int(row.get("n")) or 0 for row in joined),
                "hour_count": len(joined),
                "hours": [row["hour"] for row in joined],
                "best_parameters": best_parameters,
                "uses_market_prices": uses_market_prices,
                "owner": owner["owner"],
                "claim_lane": owner["claim_lane"],
                "counts_toward_weather_model_promotion": owner["counts_toward_weather_model_promotion"],
                "interpretation": _interpret_remediation(probe_name, brier_delta, uses_market_prices),
            })
    return {
        "schema_version": REMEDIATION_REGISTRY_SCHEMA_VERSION,
        "rows": rows,
        "summary": {
            "row_count": len(rows),
            "probe_names": sorted({row["probe_name"] for row in rows}),
            "hour_regimes": sorted({row["hour_regime"] for row in rows}),
            "market_price_probe_count": sum(1 for row in rows if row.get("uses_market_prices")),
            "weather_model_probe_count": sum(1 for row in rows if not row.get("uses_market_prices")),
        },
    }


def hourly_performance_gate(
    by_hour_regime,
    corpus,
    *,
    min_regime_market_days=DEFAULT_MIN_REGIME_MARKET_DAYS,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    early_ece_max=DEFAULT_EARLY_ECE_MAX,
):
    by_regime = {row.get("regime"): row for row in by_hour_regime or []}
    early = by_regime.get("early_morning") or {}
    blockers = []
    market_days = safe_int(early.get("market_days"))
    if not early:
        blockers.append({
            "gate": "early_hour_regime_missing",
            "detail": "no early 00:00-08:00 hourly-regime evidence is available",
            "remediation_command": "python -m weather.reporting.hourly_model_performance",
        })
    elif market_days < int(min_regime_market_days):
        blockers.append({
            "gate": "early_hour_min_market_days",
            "detail": (
                f"early-hour regime has {market_days} market-days; "
                f"requires at least {int(min_regime_market_days)}"
            ),
            "remediation_command": "collect more settled early-hour market-day evidence",
        })

    brier_delta = safe_float(early.get("brier_delta"))
    if brier_delta is not None and brier_delta < -float(early_brier_regression_tolerance):
        blockers.append({
            "gate": "early_hour_brier_regression",
            "detail": (
                "early-hour model Brier trails market by "
                f"{abs(brier_delta):.4f} > {float(early_brier_regression_tolerance):.4f}"
            ),
            "remediation_command": "keep promotion blocked; run early-hour remediation candidate or quote-risk guardrail",
        })
    logloss_delta = safe_float(early.get("logloss_delta"))
    if logloss_delta is not None and logloss_delta < -float(early_logloss_regression_tolerance):
        blockers.append({
            "gate": "early_hour_logloss_regression",
            "detail": (
                "early-hour model log-loss trails market by "
                f"{abs(logloss_delta):.4f} > {float(early_logloss_regression_tolerance):.4f}"
            ),
            "remediation_command": "keep promotion blocked; inspect early-hour probability tails",
        })
    ece = safe_float(early.get("model_ece"))
    if ece is not None and ece > float(early_ece_max):
        blockers.append({
            "gate": "early_hour_calibration_error",
            "detail": f"early-hour ECE {ece:.4f} exceeds {float(early_ece_max):.4f}",
            "remediation_command": "add early-hour calibration remediation before promotion",
        })
    status = "BLOCK" if blockers else "PASS"
    return {
        "schema_version": HOURLY_GATE_SCHEMA_VERSION,
        "status": status,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else {},
        "blockers": blockers,
        "thresholds": {
            "min_regime_market_days": int(min_regime_market_days),
            "early_brier_regression_tolerance": float(early_brier_regression_tolerance),
            "early_logloss_regression_tolerance": float(early_logloss_regression_tolerance),
            "early_ece_max": float(early_ece_max),
        },
        "early_morning": early,
        "corpus_market_days": (corpus or {}).get("scored_market_days", 0),
    }


def hourly_daily_summary(best_hours, worst_hours, remediation_registry, gate):
    owners = sorted({
        row.get("owner")
        for row in (remediation_registry.get("rows") or [])
        if row.get("hour_regime") == "early_morning" and row.get("owner")
    })
    return {
        "status": gate.get("status"),
        "best_hours": [row.get("hour_label") for row in best_hours or []],
        "worst_hours": [row.get("hour_label") for row in worst_hours or []],
        "active_remediation_owners": owners,
        "first_blocker": gate.get("first_blocker") or {},
    }


def read_json_file(path):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def load_cutoff_regime_context(context_root=DEFAULT_BACKTEST_ROOT):
    path = Path(context_root) / DEFAULT_CUTOFF_REGIME_CONTEXT.name
    payload = read_json_file(path)
    if not payload:
        return {"available": False, "path": str(path)}

    replay_by_regime = {
        row.get("group"): row
        for row in (
            payload.get("daily_first_by_cutoff_regime")
            or payload.get("by_cutoff_regime")
            or []
        )
    }
    threshold_by_regime = {
        row.get("regime"): row
        for row in payload.get("regime_thresholds") or []
    }
    weights = []
    for row in payload.get("regime_family_weights") or []:
        regime = row.get("regime")
        replay = replay_by_regime.get(regime) or {}
        threshold = threshold_by_regime.get(regime) or {}
        weights.append({
            "regime": regime,
            "evidence_status": row.get("evidence_status"),
            "forecast_component_weight": row.get("forecast_component_weight"),
            "observed_component_weight": row.get("observed_component_weight"),
            "forecast_family_weight": (row.get("family_weights") or {}).get("open_meteo_forecast_profile"),
            "observed_path_weight": (row.get("family_weights") or {}).get("observed_temp_path"),
            "source_state_weight": (row.get("family_weights") or {}).get("forecast_source_state"),
            "time_context_weight": (row.get("family_weights") or {}).get("time_context"),
            "surface_weight": (row.get("family_weights") or {}).get("surface_weather"),
            "forecast_family_delta_mae": (row.get("family_delta_mae") or {}).get("open_meteo_forecast_profile"),
            "observed_path_delta_mae": (row.get("family_delta_mae") or {}).get("observed_temp_path"),
            "source_state_delta_mae": (row.get("family_delta_mae") or {}).get("forecast_source_state"),
            "candidate_delta_vs_current": replay.get("delta_vs_current"),
            "candidate_delta_vs_market": replay.get("delta_vs_market"),
            "candidate_brier": replay.get("candidate_brier"),
            "current_brier": replay.get("current_brier"),
            "market_brier": replay.get("market_brier"),
            "n_days": replay.get("n_days"),
            "n": replay.get("n"),
            "status": threshold.get("status"),
            "reasons": threshold.get("reasons") or [],
        })
    return {
        "available": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "acceptance": payload.get("acceptance") or {},
        "no_leakage_audit": payload.get("no_leakage_audit") or {},
        "regime_family_weights": weights,
    }


def load_forecast_profile_context(context_root=DEFAULT_BACKTEST_ROOT):
    path = Path(context_root) / DEFAULT_FORECAST_PROFILE_CONTEXT.name
    payload = read_json_file(path)
    if not payload:
        return {"available": False, "path": str(path)}

    acceptance = payload.get("acceptance") or {}
    required_slices = []
    for regime, row in sorted((acceptance.get("required_slices") or {}).items()):
        required_slices.append({
            "regime": regime,
            "candidate_brier": row.get("candidate_brier"),
            "current_brier": row.get("current_brier"),
            "market_brier": row.get("market_brier"),
            "delta_vs_current": row.get("delta_vs_current"),
            "delta_vs_market": row.get("delta_vs_market"),
            "n": row.get("n"),
        })

    subfamilies = sorted(
        payload.get("subfamilies") or [],
        key=lambda row: safe_float(row.get("positive_delta_mae_sum")) or 0.0,
        reverse=True,
    )
    return {
        "available": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": acceptance.get("status"),
        "reasons": acceptance.get("reasons") or [],
        "required_slices": required_slices,
        "top_subfamilies": [
            {
                "subfamily": row.get("subfamily"),
                "positive_delta_mae_sum": row.get("positive_delta_mae_sum"),
                "best_feature": row.get("best_feature"),
                "best_feature_delta_mae": row.get("best_feature_delta_mae"),
                "min_hgb_importance_q": row.get("min_hgb_importance_q"),
            }
            for row in subfamilies[:5]
        ],
    }


def load_variable_weight_context(context_root=DEFAULT_BACKTEST_ROOT):
    return {
        "cutoff_regime_weighting": load_cutoff_regime_context(context_root),
        "forecast_profile_calibration": load_forecast_profile_context(context_root),
    }


def delta(value, baseline):
    if value is None or baseline is None:
        return None
    return value - baseline


def direction_text(value, good_when_negative=False, decimals=4):
    if value is None:
        return "unavailable"
    direction = "lower" if value < 0 else "higher"
    if good_when_negative and value < 0:
        direction = "better/lower"
    if good_when_negative and value > 0:
        direction = "worse/higher"
    return f"{abs(value):.{decimals}f} {direction}"


def explain_hour(row, overall, best=True):
    hour = row.get("hour_label")
    brier_delta = delta(row.get("model_brier"), overall.get("model_brier"))
    winner_delta = delta(row.get("winner_model_probability"), overall.get("winner_model_probability"))
    loser_delta = delta(row.get("loser_model_probability"), overall.get("loser_model_probability"))
    forecast_gap_delta = delta(row.get("mean_feature_forecast_gap"), overall.get("mean_feature_forecast_gap"))
    market_delta = delta(row.get("market_brier"), overall.get("market_brier"))
    effective_band_gap = row.get("partition_effective_band_gap")
    winner_rank_gap = row.get("partition_winner_rank_gap")
    bits = [
        f"{hour}: model Brier is {direction_text(brier_delta, good_when_negative=True)} than the headline checkpoint average",
    ]
    if winner_delta is not None:
        bits.append(f"realized winner probability is {direction_text(winner_delta, decimals=3)}")
    if loser_delta is not None:
        bits.append(f"probability left on losing bands is {direction_text(loser_delta, decimals=3)}")
    if forecast_gap_delta is not None:
        bits.append(f"forecast-gap feature is {direction_text(forecast_gap_delta, decimals=2)}")
    if market_delta is not None:
        bits.append(f"market Brier is {direction_text(market_delta, good_when_negative=True)}")
    if effective_band_gap is not None:
        bits.append(f"model effective-band spread is {direction_text(effective_band_gap, decimals=2)} than market")
    if winner_rank_gap is not None:
        bits.append(f"winner rank is {direction_text(winner_rank_gap, decimals=2)} than market")
    text = "; ".join(bits) + "."
    if best and row.get("hour") is not None and int(row["hour"]) >= 18:
        text += " This is also a late-day hour, when observed highs and market resolution state are usually much more constrained."
    if not best and row.get("hour") is not None and 10 <= int(row["hour"]) <= 16:
        text += " This sits in the heating/peak-discovery window, where the final high is often not settled yet."
    return text


def driver_notes(best_hours, worst_hours, overall):
    notes = {"best": [], "worst": []}
    for row in best_hours:
        notes["best"].append(explain_hour(row, overall, best=True))
    for row in worst_hours:
        notes["worst"].append(explain_hour(row, overall, best=False))
    return notes


def build_hourly_performance(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    context_root=DEFAULT_BACKTEST_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
    markets=None,
    start_date=None,
    end_date=None,
    min_rows=DEFAULT_MIN_ROWS,
    top_hours=DEFAULT_TOP_HOURS,
    min_regime_market_days=DEFAULT_MIN_REGIME_MARKET_DAYS,
    early_brier_regression_tolerance=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    early_logloss_regression_tolerance=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    early_ece_max=DEFAULT_EARLY_ECE_MAX,
):
    labels, skipped = discover_labeled_folders(
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
    )
    all_rows = []
    days = []
    score_errors = []
    for item in labels:
        try:
            rows, day = score_folder(item["folder"], item["label"])
        except Exception as exc:  # pragma: no cover - defensive report surface
            score_errors.append({"folder": str(item["folder"]), "error": str(exc)})
            continue
        all_rows.extend(rows)
        days.append(day)

    checkpoint_rows = hourly_checkpoint_rows(all_rows)
    by_hour = summarize_by_hour(checkpoint_rows)
    by_hour_regime = summarize_by_hour_regime(checkpoint_rows)
    all_snapshot_by_hour = summarize_by_hour(all_rows)
    overall_checkpoint = summarize_rows(checkpoint_rows) or {}
    overall_all_snapshots = summarize_rows(all_rows) or {}
    best_hours, worst_hours = rank_hours(by_hour, min_rows=min_rows, top_hours=top_hours)
    notes = driver_notes(best_hours, worst_hours, overall_checkpoint) if overall_checkpoint else {"best": [], "worst": []}
    remediation = remediation_candidates(checkpoint_rows)
    remediation_registry = build_remediation_registry(remediation, by_hour)
    gate = hourly_performance_gate(
        by_hour_regime,
        {
            "scored_market_days": len(days),
        },
        min_regime_market_days=min_regime_market_days,
        early_brier_regression_tolerance=early_brier_regression_tolerance,
        early_logloss_regression_tolerance=early_logloss_regression_tolerance,
        early_ece_max=early_ece_max,
    )
    daily_summary = hourly_daily_summary(best_hours, worst_hours, remediation_registry, gate)
    variable_weight_context = load_variable_weight_context(context_root)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "inputs": {
            "labels_csv": str(Path(labels_csv)),
            "snapshots_root": str(Path(snapshots_root)),
            "context_root": str(Path(context_root)),
            "quality_grades": list(quality_grades or []),
            "markets": list(markets or []),
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
            "min_rows": int(min_rows),
            "top_hours": int(top_hours),
            "min_regime_market_days": int(min_regime_market_days),
            "early_brier_regression_tolerance": float(early_brier_regression_tolerance),
            "early_logloss_regression_tolerance": float(early_logloss_regression_tolerance),
            "early_ece_max": float(early_ece_max),
        },
        "corpus": {
            "selected_label_count": len(labels),
            "scored_market_days": len(days),
            "markets": sorted({day.get("market_id") for day in days if day.get("market_id")}),
            "date_min": min((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "date_max": max((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "all_snapshot_rows": len(all_rows),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "skipped_labels": skipped,
            "score_errors": score_errors,
        },
        "days": days,
        "overall": {
            "hourly_checkpoint": overall_checkpoint,
            "all_snapshots": overall_all_snapshots,
        },
        "by_hour": by_hour,
        "by_hour_regime": by_hour_regime,
        "all_snapshot_by_hour": all_snapshot_by_hour,
        "best_hours": best_hours,
        "worst_hours": worst_hours,
        "driver_notes": notes,
        "remediation_candidates": remediation,
        "remediation_registry": remediation_registry,
        "hourly_performance_gate": gate,
        "daily_summary": daily_summary,
        "deep_diagnostics": {
            "hour_regime_labels": HOUR_REGIME_LABELS,
            "variable_weight_context": variable_weight_context,
        },
    }


def fmt_num(value, decimals=4):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value):.{decimals}f}"


def fmt_pct(value):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value) * 100:.1f}%"


def fmt_signed(value, decimals=4):
    if value is None:
        return "-"
    try:
        if math.isnan(float(value)):
            return "-"
    except (TypeError, ValueError):
        return "-"
    return f"{float(value):+.{decimals}f}"


def hour_table_rows(rows):
    return [
        [
            row.get("hour_label"),
            row.get("n"),
            row.get("market_days"),
            row.get("markets"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_num(row.get("model_logloss")),
            fmt_signed(row.get("logloss_delta")),
            fmt_num(row.get("model_ece")),
            fmt_pct(row.get("winner_model_probability")),
            fmt_pct(row.get("loser_model_probability")),
            fmt_num(row.get("mean_feature_forecast_gap"), 2),
        ]
        for row in rows
    ]


def remediation_table_rows(rows, parameter_label):
    output = []
    for row in rows:
        best = row.get("best") or {}
        output.append([
            row.get("hour_label"),
            fmt_num(row.get("base_model_brier")),
            best.get("parameter"),
            fmt_num(best.get("model_brier")),
            fmt_signed(best.get("brier_delta_vs_base")),
            fmt_num(best.get("model_logloss")),
            fmt_signed(best.get("logloss_delta_vs_base")),
            parameter_label,
        ])
    return output


def regime_table_rows(rows):
    return [
        [
            row.get("regime_label"),
            row.get("n"),
            row.get("market_days"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("brier_delta")),
            fmt_signed(row.get("partition_winner_probability_gap")),
            fmt_num(row.get("partition_model_effective_bands"), 2),
            fmt_num(row.get("partition_market_effective_bands"), 2),
            fmt_signed(row.get("partition_effective_band_gap"), 2),
            fmt_pct(row.get("partition_model_top_probability")),
            fmt_pct(row.get("partition_market_top_probability")),
        ]
        for row in rows
    ]


def spread_table_rows(rows):
    return [
        [
            row.get("hour_label"),
            fmt_num(row.get("partition_model_effective_bands"), 2),
            fmt_num(row.get("partition_market_effective_bands"), 2),
            fmt_signed(row.get("partition_effective_band_gap"), 2),
            fmt_pct(row.get("partition_model_top_probability")),
            fmt_pct(row.get("partition_market_top_probability")),
            fmt_signed(row.get("partition_top_probability_gap"), 3),
            fmt_pct(row.get("partition_model_top_is_winner_rate")),
            fmt_pct(row.get("partition_market_top_is_winner_rate")),
            fmt_signed(row.get("partition_winner_rank_gap"), 2),
        ]
        for row in rows
    ]


def cutoff_context_table_rows(rows):
    return [
        [
            row.get("regime"),
            row.get("evidence_status"),
            fmt_pct(row.get("forecast_component_weight")),
            fmt_pct(row.get("observed_component_weight")),
            fmt_pct(row.get("forecast_family_weight")),
            fmt_pct(row.get("observed_path_weight")),
            fmt_pct(row.get("source_state_weight")),
            fmt_signed(row.get("candidate_delta_vs_current")),
            fmt_signed(row.get("candidate_delta_vs_market")),
            row.get("status") or "-",
        ]
        for row in rows
    ]


def forecast_profile_slice_rows(rows):
    return [
        [
            row.get("regime"),
            row.get("n"),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_signed(row.get("delta_vs_current")),
            fmt_signed(row.get("delta_vs_market")),
        ]
        for row in rows
    ]


def forecast_profile_subfamily_rows(rows):
    return [
        [
            row.get("subfamily"),
            fmt_num(row.get("positive_delta_mae_sum"), 4),
            row.get("best_feature"),
            fmt_num(row.get("best_feature_delta_mae"), 4),
            fmt_num(row.get("min_hgb_importance_q"), 4),
        ]
        for row in rows
    ]


def _row_by_key(rows, key, value):
    for row in rows:
        if row.get(key) == value:
            return row
    return None


def generated_interpretation(payload):
    diagnostics = payload.get("deep_diagnostics") or {}
    variable_context = diagnostics.get("variable_weight_context") or {}
    regimes = payload.get("by_hour_regime") or []
    early = _row_by_key(regimes, "regime", "early_morning")
    lock_in = _row_by_key(regimes, "regime", "lock_in")
    worst = payload.get("worst_hours") or []
    notes = []

    if early and lock_in:
        notes.append(
            "Early morning trails the market because winner recognition is weak before the day develops: "
            f"the model gives the eventual winner {fmt_pct(early.get('partition_model_winner_probability'))} "
            f"versus the market's {fmt_pct(early.get('partition_market_winner_probability'))}, "
            f"and ranks the winner {fmt_signed(early.get('partition_winner_rank_gap'), 2)} bands worse."
        )
        notes.append(
            "The spread story is mixed: early model effective bands are "
            f"{fmt_num(early.get('partition_model_effective_bands'), 2)} versus market "
            f"{fmt_num(early.get('partition_market_effective_bands'), 2)} "
            f"({fmt_signed(early.get('partition_effective_band_gap'), 2)}). "
            "So the question is not just whether probabilities are sharper; it is whether the partition is centered on the right bands."
        )
        notes.append(
            "The best late hours are best because the model itself has mostly collapsed to a narrow partition "
            f"({fmt_num(lock_in.get('partition_model_effective_bands'), 2)} effective bands) with high top probability "
            f"({fmt_pct(lock_in.get('partition_model_top_probability'))}), even though market prices are still more certain."
        )

    if worst:
        worst_labels = ", ".join(row.get("hour_label") for row in worst)
        worst_gap = mean(row.get("partition_winner_probability_gap") for row in worst)
        worst_rank = mean(row.get("partition_winner_rank_gap") for row in worst)
        notes.append(
            f"The worst hours ({worst_labels}) show the market assigning more probability to the eventual winner "
            f"({fmt_signed(worst_gap, 3)} model-minus-market winner gap) and ranking the winner "
            f"{fmt_signed(worst_rank, 2)} bands worse on average."
        )

    remediation = payload.get("remediation_candidates") or {}
    partition_rows = (remediation.get("partition_power") or {}).get("early_hours") or []
    if partition_rows:
        best_delta = mean((row.get("best") or {}).get("brier_delta_vs_base") for row in partition_rows)
        notes.append(
            "The partition-power probe remains the falsification test for simple reshaping: "
            f"average early-hour Brier change is only {fmt_signed(best_delta)}, so broad sharpening/softening is not the main fix."
        )

    cutoff = variable_context.get("cutoff_regime_weighting") or {}
    if cutoff.get("available"):
        weights = cutoff.get("regime_family_weights") or []
        early_weight = _row_by_key(weights, "regime", "early")
        late_weight = _row_by_key(weights, "regime", "late")
        if early_weight and late_weight:
            notes.append(
                "Variable weight should change through the day: companion evidence assigns "
                f"{fmt_pct(early_weight.get('forecast_component_weight'))} forecast weight early and "
                f"{fmt_pct(late_weight.get('observed_component_weight'))} observed-path weight late."
            )
        acceptance = cutoff.get("acceptance") or {}
        if acceptance.get("status"):
            notes.append(
                "The current regime-weighted candidate is still "
                f"{acceptance.get('status')}: it improves current Brier modestly but remains outside the market tolerance."
            )

    forecast_profile = variable_context.get("forecast_profile_calibration") or {}
    if forecast_profile.get("available"):
        top_subfamilies = forecast_profile.get("top_subfamilies") or []
        if top_subfamilies:
            names = ", ".join(row.get("subfamily") for row in top_subfamilies[:3])
            notes.append(
                "Within the forecast lane, the useful signal is concentrated in "
                f"{names}; low-marginal subfamilies should adjust confidence rather than override forecast_high."
            )

    return notes


def render_report(payload):
    corpus = payload.get("corpus") or {}
    inputs = payload.get("inputs") or {}
    overall = ((payload.get("overall") or {}).get("hourly_checkpoint") or {})
    best = payload.get("best_hours") or []
    worst = payload.get("worst_hours") or []
    notes = payload.get("driver_notes") or {}
    remediation = payload.get("remediation_candidates") or {}
    remediation_registry = payload.get("remediation_registry") or {}
    hourly_gate = payload.get("hourly_performance_gate") or {}
    daily_summary = payload.get("daily_summary") or {}
    diagnostics = payload.get("deep_diagnostics") or {}
    variable_context = diagnostics.get("variable_weight_context") or {}
    rerun = (
        ".\\venv\\Scripts\\python.exe -m weather.reporting.hourly_model_performance"
    )
    if inputs.get("quality_grades") != list(DEFAULT_QUALITY_GRADES):
        rerun += f" --quality-grades {','.join(inputs.get('quality_grades') or [])}"

    lines = [
        "# Hourly Model Performance Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Corpus",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Labels selected", corpus.get("selected_label_count", 0)],
            ["Scored market-days", corpus.get("scored_market_days", 0)],
            ["Markets", ", ".join(corpus.get("markets") or []) or "-"],
            ["Date range", f"{corpus.get('date_min') or '-'} to {corpus.get('date_max') or '-'}"],
            ["Quality grades", ", ".join(inputs.get("quality_grades") or []) or "-"],
            ["All snapshot rows", corpus.get("all_snapshot_rows", 0)],
            ["Hourly checkpoint rows", corpus.get("hourly_checkpoint_rows", 0)],
            ["Skipped labels", json.dumps(corpus.get("skipped_labels") or {}, sort_keys=True)],
            ["Score errors", len(corpus.get("score_errors") or [])],
        ],
    )

    lines += [
        "",
        "## How To Rerun",
        "",
        "```powershell",
        rerun,
        "```",
        "",
        (
            "Headline rows use the first available snapshot in each local hour for each "
            "market-day-band. This avoids overweighting hours that happened to collect "
            "more snapshots."
        ),
        "",
        "## Headline Score",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Rows", "Market-days", "Model Brier", "Market Brier", "Brier Delta", "Model LogLoss", "LogLoss Delta", "Model ECE"],
        [[
            "Hourly checkpoints",
            overall.get("n", 0),
            overall.get("market_days", 0),
            fmt_num(overall.get("model_brier")),
            fmt_num(overall.get("market_brier")),
            fmt_signed(overall.get("brier_delta")),
            fmt_num(overall.get("model_logloss")),
            fmt_signed(overall.get("logloss_delta")),
            fmt_num(overall.get("model_ece")),
        ]],
    )
    lines += [
        "",
        "## Hourly Performance Gate",
        "",
    ]
    first_blocker = hourly_gate.get("first_blocker") or {}
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Status", hourly_gate.get("status") or "-"],
            ["Blockers", hourly_gate.get("blocker_count", 0)],
            ["First blocker", first_blocker.get("gate") or "-"],
            ["First blocker detail", first_blocker.get("detail") or "-"],
            ["Best hours", ", ".join(daily_summary.get("best_hours") or []) or "-"],
            ["Worst hours", ", ".join(daily_summary.get("worst_hours") or []) or "-"],
            ["Active remediation owners", ", ".join(daily_summary.get("active_remediation_owners") or []) or "-"],
        ],
    )
    blockers = hourly_gate.get("blockers") or []
    if blockers:
        lines += ["", "### Gate Blockers", ""]
        lines += markdown_table(
            ["Gate", "Detail", "Remediation"],
            [
                [
                    row.get("gate"),
                    row.get("detail"),
                    row.get("remediation_command"),
                ]
                for row in blockers
            ],
        )

    lines += [
        "",
        "## Hour By Hour",
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Rows",
            "Days",
            "Markets",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Model LogLoss",
            "LogLoss Delta",
            "Model ECE",
            "Winner Model P",
            "Loser Model P",
            "Mean Forecast Gap",
        ],
        hour_table_rows(payload.get("by_hour") or []),
    )

    lines += [
        "",
        "## Best Hours",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Rows", "Days", "Model Brier", "Market Brier", "Winner Model P", "Loser Model P", "Mean Forecast Gap"],
        [
            [
                row.get("hour_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_pct(row.get("winner_model_probability")),
                fmt_pct(row.get("loser_model_probability")),
                fmt_num(row.get("mean_feature_forecast_gap"), 2),
            ]
            for row in best
        ],
    )

    lines += [
        "",
        "## Worst Hours",
        "",
    ]
    lines += markdown_table(
        ["Hour", "Rows", "Days", "Model Brier", "Market Brier", "Winner Model P", "Loser Model P", "Mean Forecast Gap"],
        [
            [
                row.get("hour_label"),
                row.get("n"),
                row.get("market_days"),
                fmt_num(row.get("model_brier")),
                fmt_num(row.get("market_brier")),
                fmt_pct(row.get("winner_model_probability")),
                fmt_pct(row.get("loser_model_probability")),
                fmt_num(row.get("mean_feature_forecast_gap"), 2),
            ]
            for row in worst
        ],
    )

    lines += ["", "## Driver Notes", ""]
    if notes.get("best"):
        lines.append("Best-hour drivers:")
        lines.extend(f"- {item}" for item in notes["best"])
        lines.append("")
    if notes.get("worst"):
        lines.append("Worst-hour drivers:")
        lines.extend(f"- {item}" for item in notes["worst"])
        lines.append("")
    if not notes.get("best") and not notes.get("worst"):
        lines.append("No hours met the minimum-row threshold for driver notes.")
        lines.append("")

    interpretation = generated_interpretation(payload)
    lines += ["## Deep Diagnostics", ""]
    if interpretation:
        lines.append("Generated interpretation:")
        lines.extend(f"- {item}" for item in interpretation)
        lines.append("")

    lines += [
        "### Hour Regimes",
        "",
    ]
    lines += markdown_table(
        [
            "Window",
            "Rows",
            "Days",
            "Model Brier",
            "Market Brier",
            "Brier Delta",
            "Winner P Gap",
            "Model Eff Bands",
            "Market Eff Bands",
            "Eff Gap",
            "Model Top P",
            "Market Top P",
        ],
        regime_table_rows(payload.get("by_hour_regime") or []),
    )

    lines += [
        "",
        "### Spread And Winner Recognition",
        "",
        (
            "Effective bands are computed per snapshot after normalizing the partition. "
            "Higher effective bands means probability is spread over more bands. "
            "Winner rank gap is model rank minus market rank, so positive means the model ranks the eventual winner worse."
        ),
        "",
    ]
    lines += markdown_table(
        [
            "Hour",
            "Model Eff Bands",
            "Market Eff Bands",
            "Eff Gap",
            "Model Top P",
            "Market Top P",
            "Top P Gap",
            "Model Top Winner",
            "Market Top Winner",
            "Winner Rank Gap",
        ],
        spread_table_rows(payload.get("by_hour") or []),
    )

    cutoff_context = variable_context.get("cutoff_regime_weighting") or {}
    forecast_context = variable_context.get("forecast_profile_calibration") or {}
    lines += [
        "",
        "### Variable Weight Evidence",
        "",
    ]
    if cutoff_context.get("available"):
        lines.append(
            "Cutoff-regime context from "
            f"`{relative_to_repo(cutoff_context.get('path'))}`."
        )
        lines.append("")
        lines += markdown_table(
            [
                "Regime",
                "Evidence",
                "Forecast Wt",
                "Observed Wt",
                "Forecast Family",
                "Observed Path",
                "Source State",
                "Delta Current",
                "Delta Market",
                "Status",
            ],
            cutoff_context_table_rows(cutoff_context.get("regime_family_weights") or []),
        )
        reasons = (cutoff_context.get("acceptance") or {}).get("reasons") or []
        if reasons:
            lines.append("")
            lines.append("Cutoff-regime blockers:")
            lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append(f"Cutoff-regime context not found at `{cutoff_context.get('path')}`.")

    lines += ["", "Forecast-profile candidate context:", ""]
    if forecast_context.get("available"):
        status = forecast_context.get("status") or "-"
        reasons = forecast_context.get("reasons") or []
        lines.append(
            f"Status `{status}` from `{relative_to_repo(forecast_context.get('path'))}`."
        )
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        lines.append("")
        lines += markdown_table(
            ["Regime", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
            forecast_profile_slice_rows(forecast_context.get("required_slices") or []),
        )
        lines += ["", "Top forecast-profile subfamilies after the forecast_high anchor:", ""]
        lines += markdown_table(
            ["Subfamily", "Positive Delta MAE", "Best Feature", "Best Delta MAE", "Min q"],
            forecast_profile_subfamily_rows(forecast_context.get("top_subfamilies") or []),
        )
    else:
        lines.append(f"Forecast-profile context not found at `{forecast_context.get('path')}`.")
    lines.append("")

    market_blend = remediation.get("market_blend") or {}
    partition_power = remediation.get("partition_power") or {}
    lines += [
        "## Remediation Probes",
        "",
        (
            "These are replay-only probes. They do not change serving behavior; "
            "they indicate which remediation families are worth promoting into a "
            "candidate lane."
        ),
        "",
        "### Market-Price Blend",
        "",
        (
            "This is an operational de-risking probe, not a pure weather-model "
            "improvement. It uses market prices, so a high alpha reduces model "
            "error by leaning toward the benchmark we are trying to beat."
        ),
        "",
    ]
    lines += markdown_table(
        ["Hour", "Base Brier", "Best Alpha", "Best Brier", "Brier Change", "Best LogLoss", "LogLoss Change", "Parameter"],
        remediation_table_rows(market_blend.get("early_hours") or [], "alpha"),
    )
    lines += [
        "",
        "### Remediation Registry",
        "",
    ]
    registry_rows = []
    for row in remediation_registry.get("rows") or []:
        registry_rows.append([
            row.get("probe_name"),
            row.get("hour_regime"),
            row.get("row_count"),
            row.get("market_count"),
            fmt_signed(row.get("metric_delta")),
            fmt_signed(row.get("logloss_delta")),
            row.get("uses_market_prices"),
            row.get("owner"),
            row.get("interpretation"),
        ])
    lines += markdown_table(
        ["Probe", "Regime", "Rows", "Markets", "Brier Delta", "LogLoss Delta", "Uses Market", "Owner", "Interpretation"],
        registry_rows,
    )
    lines += [
        "",
        "### Partition Power",
        "",
        (
            "This pure model-output probe asks whether the issue is just "
            "distribution sharpness. `gamma < 1` softens the partition and "
            "`gamma > 1` sharpens it."
        ),
        "",
    ]
    lines += markdown_table(
        ["Hour", "Base Brier", "Best Gamma", "Best Brier", "Brier Change", "Best LogLoss", "LogLoss Change", "Parameter"],
        remediation_table_rows(partition_power.get("early_hours") or [], "gamma"),
    )

    lines += [
        "",
        "## Caveats",
        "",
        "- Default scope includes only complete/manual-override settlement labels.",
        "- Intraday rows from the same market day remain correlated even after hourly checkpointing.",
        "- Temperature and forecast-gap driver averages are native-unit fields across mixed C/F markets, so use them directionally.",
        "- `Brier Delta` is market Brier minus model Brier, so positive means the model beat the market benchmark.",
        "",
    ]
    return "\n".join(lines)


CSV_COLUMNS = [
    "hour",
    "hour_label",
    "n",
    "market_days",
    "markets",
    "snapshots",
    "model_brier",
    "market_brier",
    "brier_delta",
    "brier_skill_score",
    "model_logloss",
    "market_logloss",
    "logloss_delta",
    "model_ece",
    "market_ece",
    "base_rate",
    "winner_model_probability",
    "winner_market_probability",
    "loser_model_probability",
    "loser_market_probability",
    "partition_snapshots",
    "partition_mean_band_count",
    "partition_model_effective_bands",
    "partition_market_effective_bands",
    "partition_effective_band_gap",
    "partition_model_norm_entropy",
    "partition_market_norm_entropy",
    "partition_norm_entropy_gap",
    "partition_model_top_probability",
    "partition_market_top_probability",
    "partition_top_probability_gap",
    "partition_winner_probability_gap",
    "partition_model_winner_rank",
    "partition_market_winner_rank",
    "partition_winner_rank_gap",
    "partition_model_top_is_winner_rate",
    "partition_market_top_is_winner_rate",
    "partition_model_adjacent_winner_mass",
    "partition_market_adjacent_winner_mass",
    "partition_adjacent_winner_mass_gap",
    "mean_feature_forecast_gap",
    "mean_feature_high_so_far",
    "mean_feature_current_temp",
]


def write_hour_csv(rows, path=DEFAULT_CSV_OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_outputs(
    payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    csv_out=DEFAULT_CSV_OUT,
):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    csv_path = write_hour_csv(payload.get("by_hour") or [], csv_out)
    return json_out, report_out, csv_path


def build_parser():
    parser = argparse.ArgumentParser(description="Audit settlement-scored model performance by local capture hour.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument(
        "--context-root",
        default=str(DEFAULT_BACKTEST_ROOT),
        help="Directory containing companion analysis JSON files used for variable-weight context.",
    )
    parser.add_argument(
        "--quality-grades",
        default=",".join(DEFAULT_QUALITY_GRADES),
        help="Comma-separated settlement quality grades to include.",
    )
    parser.add_argument("--markets", default="", help="Comma-separated market IDs to include.")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--min-rows", type=int, default=DEFAULT_MIN_ROWS)
    parser.add_argument("--top-hours", type=int, default=DEFAULT_TOP_HOURS)
    parser.add_argument("--min-regime-market-days", type=int, default=DEFAULT_MIN_REGIME_MARKET_DAYS)
    parser.add_argument(
        "--early-brier-regression-tolerance",
        type=float,
        default=DEFAULT_EARLY_BRIER_REGRESSION_TOLERANCE,
    )
    parser.add_argument(
        "--early-logloss-regression-tolerance",
        type=float,
        default=DEFAULT_EARLY_LOGLOSS_REGRESSION_TOLERANCE,
    )
    parser.add_argument("--early-ece-max", type=float, default=DEFAULT_EARLY_ECE_MAX)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--csv-out", default=str(DEFAULT_CSV_OUT))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    quality_grades = parse_quality_grades(args.quality_grades)
    markets = parse_csv_values(args.markets)
    payload = build_hourly_performance(
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        context_root=args.context_root,
        quality_grades=quality_grades,
        markets=markets,
        start_date=args.start_date,
        end_date=args.end_date,
        min_rows=args.min_rows,
        top_hours=args.top_hours,
        min_regime_market_days=args.min_regime_market_days,
        early_brier_regression_tolerance=args.early_brier_regression_tolerance,
        early_logloss_regression_tolerance=args.early_logloss_regression_tolerance,
        early_ece_max=args.early_ece_max,
    )
    json_out, report_out, csv_out = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        csv_out=args.csv_out,
    )
    print(f"Wrote {relative_to_repo(json_out)}")
    print(f"Wrote {relative_to_repo(report_out)}")
    print(f"Wrote {relative_to_repo(csv_out)}")
    overall = payload.get("overall", {}).get("hourly_checkpoint") or {}
    if overall:
        print(
            "Hourly checkpoint model Brier "
            f"{overall['model_brier']:.4f} vs market {overall['market_brier']:.4f} "
            f"(delta {overall['brier_delta']:+.4f})"
        )
    if payload.get("best_hours"):
        print("Best hours: " + ", ".join(row["hour_label"] for row in payload["best_hours"]))
    if payload.get("worst_hours"):
        print("Worst hours: " + ", ".join(row["hour_label"] for row in payload["worst_hours"]))
    gate = payload.get("hourly_performance_gate") or {}
    if gate:
        print(f"Hourly performance gate: {gate.get('status')} ({gate.get('blocker_count', 0)} blocker(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
