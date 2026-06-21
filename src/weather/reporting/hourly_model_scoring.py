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

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
