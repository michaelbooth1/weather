"""Price-free settled model diagnostics for inactive or no-market days."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from weather.backtesting.settlement_io import row_band_value_hi, resolve_outcome
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.paths import data_path, relative_to_repo
from weather.reporting.formatting import markdown_table
from weather.reporting.hourly_model_performance import (
    DEFAULT_LABELS_CSV,
    DEFAULT_QUALITY_GRADES,
    DEFAULT_SNAPSHOTS_ROOT,
    HOUR_REGIME_LABELS,
    discover_labeled_folders,
    parse_csv_values,
    parse_quality_grades,
)
from weather.reporting.model_scoring_liveness import attach_scoring_liveness, build_rerun_command
from weather.schema_registry import schema_version
from weather.scoring.metrics import binary_log_loss, brier, expected_calibration_error, missing, safe_float


SCHEMA_VERSION = schema_version("price_free_model_learning")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "price_free_model_learning.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "price_free_model_learning_report.md"
DEFAULT_HOURLY_CSV_OUT = DEFAULT_BACKTEST_ROOT / "price_free_model_learning_by_hour.csv"
DEFAULT_CURRENT_MAX_CSV_OUT = DEFAULT_BACKTEST_ROOT / "price_free_model_learning_current_max_carryover.csv"
EARLY_GAP_HOUR_MAX = 12
CURRENT_MAX_GAP_THRESHOLD = 10.0

RAW_DRIVER_COLUMNS = (
    "wu_history_high_native",
    "wu_history_high",
    "wu_history_high_c",
    "wu_current_native",
    "wu_current",
    "wu_current_c",
    "wu_max_since_7am_native",
    "wu_max_since_7am",
    "wu_max_since_7am_c",
    "eccc_swob_max_c",
    "weather_forecast_max_c",
    "open_meteo_max_c",
    "eccc_forecast_high_c",
)


def utc_now():
    return datetime.now(timezone.utc)


def safe_int(value):
    number = safe_float(value)
    if number is None:
        return None
    return int(number)


def parse_iso_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def parse_snapshot_time(value):
    if missing(value) or value == "":
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def capture_minute(value):
    parsed = parse_snapshot_time(value)
    if parsed is None:
        return None
    return parsed.hour * 60 + parsed.minute


def timestamp_key(row):
    parsed = parse_snapshot_time(row.get("captured_at_local"))
    if parsed is not None:
        return parsed.timestamp()
    return float(row.get("row_order") or 0)


def read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def row_date(row):
    parsed = parse_iso_date(row.get("target_date"))
    if parsed:
        return parsed
    return date_from_event_slug(row.get("event_slug"))


def first_numeric(row, *columns):
    for column in columns:
        value = safe_float(row.get(column))
        if value is not None:
            return value
    return None


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
    cleaned = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(number):
            cleaned.append(number)
    return sum(cleaned) / len(cleaned) if cleaned else None


def source_usage_reasons(tape_rows):
    if not tape_rows:
        return ["missing_snapshot_rows"]
    reasons = []
    market_yes_values = [safe_float(row.get("market_yes")) for row in tape_rows]
    if all(value is None for value in market_yes_values):
        reasons.append("absent_market_prices")
    statuses = {
        str(row.get("market_status") or "").strip().lower()
        for row in tape_rows
        if str(row.get("market_status") or "").strip()
    }
    if statuses and statuses <= {"inactive", "closed", "resolved", "archived", "unavailable", "none"}:
        reasons.append("inactive_market")
    token_columns = (
        "clob_token_id",
        "yes_token_id",
        "no_token_id",
        "token_id",
        "condition_id",
    )
    if not any(any(str(row.get(column) or "").strip() for column in token_columns) for row in tape_rows):
        reasons.append("missing_token_map")
    book_columns = ("best_bid", "best_ask", "market_yes", "market_no")
    if not any(any(safe_float(row.get(column)) is not None for column in book_columns) for row in tape_rows):
        reasons.append("missing_clob_book")
    return reasons or ["market_prices_available_but_not_used"]


def classify_current_max_state(
    *,
    current_max,
    wu_history_high,
    current_temp,
    cutoff_hour,
    final_high,
    reset_hour=7,
    gap_threshold=CURRENT_MAX_GAP_THRESHOLD,
    eps=1e-9,
):
    pre_reset = cutoff_hour is not None and int(cutoff_hour) < int(reset_hour)
    gap_to_history = None if current_max is None or wu_history_high is None else current_max - wu_history_high
    gap_to_current = None if current_max is None or current_temp is None else current_max - current_temp
    gap_to_final = None if current_max is None or final_high is None else current_max - final_high

    if current_max is None:
        state = "missing_current_max"
        disposition = "missing"
    elif pre_reset:
        state = "pre_reset_current_max_null"
        disposition = "null_before_reset"
    elif final_high is not None and current_max > final_high + eps:
        state = "above_final_high"
        disposition = "support_only"
    elif wu_history_high is None:
        state = "missing_wu_history_high"
        disposition = "support_only"
    elif gap_to_history is not None and gap_to_history >= float(gap_threshold):
        state = (
            "early_current_max_history_gap"
            if cutoff_hour is not None and int(cutoff_hour) <= EARLY_GAP_HOUR_MAX
            else "current_max_history_gap"
        )
        disposition = "support_only"
    elif gap_to_history is not None and gap_to_history > eps:
        state = "current_max_above_history_minor_gap"
        disposition = "support_only"
    else:
        state = "wu_history_validated_current_max"
        disposition = "validated"

    return {
        "current_max_state": state,
        "feature_disposition": disposition,
        "pre_reset": bool(pre_reset),
        "gap_to_wu_history": gap_to_history,
        "gap_to_current_temp": gap_to_current,
        "gap_to_final_high": gap_to_final,
        "reset_hour": int(reset_hour),
        "gap_threshold": float(gap_threshold),
    }


def current_max_row(row, label):
    minute = capture_minute(row.get("captured_at_local"))
    cutoff_hour = minute // 60 if minute is not None else None
    settlement_bucket = safe_float(label.get("settlement_high"))
    if settlement_bucket is None:
        settlement_bucket = safe_float(label.get("settlement_bucket"))
    current_max = first_numeric(row, "wu_max_since_7am_native", "wu_max_since_7am", "wu_max_since_7am_c")
    history_high = first_numeric(row, "wu_history_high_native", "wu_history_high", "wu_history_high_c")
    current_temp = first_numeric(row, "wu_current_native", "wu_current", "wu_current_c")
    classified = classify_current_max_state(
        current_max=current_max,
        wu_history_high=history_high,
        current_temp=current_temp,
        cutoff_hour=cutoff_hour,
        final_high=settlement_bucket,
    )
    return {
        "market_id": label.get("market_id"),
        "event_slug": label.get("event_slug") or row.get("event_slug"),
        "target_date": label.get("target_date"),
        "snapshot_id": row.get("snapshot_id"),
        "captured_at_local": row.get("captured_at_local"),
        "cutoff_hour": cutoff_hour,
        "wu_max_since_7am": current_max,
        "wu_history_high": history_high,
        "wu_current": current_temp,
        "final_high": settlement_bucket,
        **classified,
    }


def current_max_rows_from_tape(tape_rows, label):
    first_by_snapshot = {}
    for row in tape_rows:
        snapshot_id = str(row.get("snapshot_id") or "")
        if not snapshot_id:
            continue
        if snapshot_id not in first_by_snapshot:
            first_by_snapshot[snapshot_id] = row
    return [
        current_max_row(row, label)
        for _, row in sorted(first_by_snapshot.items(), key=lambda item: timestamp_key(item[1]))
    ]


def attach_raw_drivers(scoring_row, raw_row):
    for column in RAW_DRIVER_COLUMNS:
        value = raw_row.get(column)
        if not missing(value) and value != "":
            scoring_row[f"raw_{column}"] = value
    return scoring_row


def score_folder(folder, label):
    folder = Path(folder)
    tape = folder / "snapshots_long.csv"
    tape_rows = read_csv_rows(tape)
    slug = label.get("event_slug") or folder.name
    spec = spec_for_slug(slug)
    target_date = row_date(label) or date_from_event_slug(slug)
    settlement_bucket = safe_int(label.get("settlement_bucket"))
    if settlement_bucket is None:
        return [], [], {
            "folder": str(folder),
            "event_slug": slug,
            "market_id": label.get("market_id") or (spec.id if spec else None),
            "rows": 0,
            "skipped": "missing_settlement",
            "price_free_reasons": source_usage_reasons(tape_rows),
        }

    rows = []
    skipped = Counter()
    target_date_value = target_date.isoformat() if target_date else label.get("target_date")
    for row_order, raw in enumerate(tape_rows):
        model_probability = safe_float(raw.get("model_probability"))
        if model_probability is None:
            skipped["missing_model_probability"] += 1
            continue
        outcome = resolve_outcome(
            raw.get("bin_kind"),
            safe_float(raw.get("bin_value_c")),
            settlement_bucket,
            value_hi=row_band_value_hi(raw),
        )
        if outcome is None:
            skipped["missing_outcome"] += 1
            continue
        minute = capture_minute(raw.get("captured_at_local"))
        scoring_row = {
            "row_order": row_order,
            "market_id": label.get("market_id") or (spec.id if spec else None),
            "city": label.get("city") or (spec.city_label if spec else None),
            "quality_grade": label.get("quality_grade"),
            "target_date": target_date_value,
            "event_slug": slug,
            "snapshot_id": raw.get("snapshot_id"),
            "captured_at_local": raw.get("captured_at_local"),
            "captured_at_utc": raw.get("captured_at_utc"),
            "capture_minute": minute,
            "cutoff_hour": minute // 60 if minute is not None else None,
            "model_version": raw.get("model_version"),
            "band": raw.get("range_label"),
            "bin_kind": raw.get("bin_kind"),
            "bin_value_c": safe_float(raw.get("bin_value_c")),
            "bin_value_hi": safe_float(row_band_value_hi(raw)),
            "settlement_bucket": settlement_bucket,
            "settlement_unit": label.get("settlement_unit") or (spec.display_unit if spec else None),
            "model_probability": max(0.0, min(1.0, model_probability)),
            "outcome": int(outcome),
            "model_brier_component": brier(max(0.0, min(1.0, model_probability)), int(outcome)),
            "model_logloss_component": binary_log_loss(max(0.0, min(1.0, model_probability)), int(outcome)),
            "market_yes_available": safe_float(raw.get("market_yes")) is not None,
            "market_status": raw.get("market_status"),
        }
        attach_raw_drivers(scoring_row, raw)
        rows.append(scoring_row)

    max_rows = current_max_rows_from_tape(tape_rows, {
        **label,
        "event_slug": slug,
        "target_date": target_date_value,
        "market_id": label.get("market_id") or (spec.id if spec else None),
    })
    reasons = source_usage_reasons(tape_rows)
    day = {
        "folder": str(folder),
        "event_slug": slug,
        "market_id": label.get("market_id") or (spec.id if spec else None),
        "target_date": target_date_value,
        "quality_grade": label.get("quality_grade"),
        "settlement_bucket": settlement_bucket,
        "settlement_unit": label.get("settlement_unit") or (spec.display_unit if spec else None),
        "snapshot_count": len({row.get("snapshot_id") for row in tape_rows if row.get("snapshot_id")}),
        "band_count": len({row.get("range_label") for row in tape_rows if row.get("range_label")}),
        "rows": len(rows),
        "skipped_rows": dict(sorted(skipped.items())),
        "price_free_reasons": reasons,
        "market_price_row_count": sum(1 for row in tape_rows if safe_float(row.get("market_yes")) is not None),
        "market_status_counts": dict(sorted(Counter(row.get("market_status") or "-" for row in tape_rows).items())),
    }
    return rows, max_rows, day


def hourly_checkpoint_rows(rows):
    selected = {}
    for row in rows:
        hour = row.get("cutoff_hour")
        if hour is None:
            continue
        key = (row.get("market_id"), row.get("target_date"), row.get("band"), int(hour))
        if key not in selected or timestamp_key(row) < timestamp_key(selected[key]):
            selected[key] = row
    return [
        selected[key]
        for key in sorted(key for key in selected)
    ]


def rows_for_group(rows, key):
    grouped = defaultdict(list)
    for row in rows:
        group = key(row) if callable(key) else row.get(key)
        grouped[group].append(row)
    return grouped


def band_sort_key(row):
    return (
        safe_float(row.get("bin_value_c")) is None,
        safe_float(row.get("bin_value_c")) or 0.0,
        safe_float(row.get("bin_value_hi")) or safe_float(row.get("bin_value_c")) or 0.0,
        safe_int(row.get("row_order")) or 0,
    )


def probability_partition_metrics(group_rows):
    rows = list(group_rows)
    probabilities = [max(0.0, safe_float(row.get("model_probability")) or 0.0) for row in rows]
    total = sum(probabilities)
    if not rows or total <= 0:
        return {}
    normalized = [probability / total for probability in probabilities]
    entropy = -sum(probability * math.log(probability) for probability in normalized if probability > 0)
    top_index = max(range(len(rows)), key=lambda index: probabilities[index])
    winner_indexes = [index for index, row in enumerate(rows) if row.get("outcome") == 1]
    winner_index = winner_indexes[0] if winner_indexes else None
    ranked_indexes = sorted(range(len(rows)), key=lambda index: probabilities[index], reverse=True)
    result = {
        "model_total_probability": total,
        "model_norm_entropy": entropy / math.log(len(rows)) if len(rows) > 1 else 0.0,
        "model_effective_bands": math.exp(entropy),
        "model_top_probability": max(probabilities),
        "model_top_share": max(normalized),
        "model_top_band": rows[top_index].get("band"),
        "model_top_is_winner": None,
        "model_winner_probability": None,
        "model_winner_rank": None,
        "model_winner_band": None,
        "model_adjacent_winner_mass": None,
    }
    if winner_index is not None:
        sorted_rows = sorted(enumerate(rows), key=lambda item: band_sort_key(item[1]))
        sorted_original_indexes = [index for index, _ in sorted_rows]
        winner_position = sorted_original_indexes.index(winner_index)
        adjacent_indexes = {
            sorted_original_indexes[position]
            for position in range(max(0, winner_position - 1), min(len(sorted_original_indexes), winner_position + 2))
        }
        result.update({
            "model_top_is_winner": 1.0 if top_index == winner_index else 0.0,
            "model_winner_probability": probabilities[winner_index],
            "model_winner_rank": ranked_indexes.index(winner_index) + 1,
            "model_winner_band": rows[winner_index].get("band"),
            "model_adjacent_winner_mass": sum(probabilities[index] for index in adjacent_indexes),
        })
    return result


def snapshot_partition_stats(rows):
    grouped = rows_for_group(
        rows,
        lambda row: (
            row.get("market_id"),
            row.get("target_date"),
            row.get("snapshot_id"),
            row.get("cutoff_hour"),
        ),
    )
    output = []
    for key, group_rows in grouped.items():
        metrics = probability_partition_metrics(group_rows)
        if not metrics:
            continue
        output.append({
            "market_id": key[0],
            "target_date": key[1],
            "snapshot_id": key[2],
            "cutoff_hour": key[3],
            "band_count": len(group_rows),
            **metrics,
        })
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
        "partition_model_norm_entropy": partition_mean(stats, "model_norm_entropy"),
        "partition_model_top_probability": partition_mean(stats, "model_top_probability"),
        "partition_model_winner_probability": partition_mean(stats, "model_winner_probability"),
        "partition_model_winner_rank": partition_mean(stats, "model_winner_rank"),
        "partition_model_top_is_winner_rate": partition_mean(stats, "model_top_is_winner"),
        "partition_model_adjacent_winner_mass": partition_mean(stats, "model_adjacent_winner_mass"),
    }


def distinct_count(rows, key):
    return len({row.get(key) for row in rows if row.get(key) not in (None, "")})


def model_score_rows(rows):
    rows = list(rows)
    if not rows:
        return None
    winners = [row for row in rows if row.get("outcome") == 1]
    losers = [row for row in rows if row.get("outcome") == 0]
    summary = {
        "n": len(rows),
        "model_brier": mean(brier(row["model_probability"], row["outcome"]) for row in rows),
        "model_logloss": mean(binary_log_loss(row["model_probability"], row["outcome"]) for row in rows),
        "base_rate": mean(row.get("outcome") for row in rows),
        "market_days": len({(row.get("market_id"), row.get("target_date")) for row in rows}),
        "markets": distinct_count(rows, "market_id"),
        "snapshots": distinct_count(rows, "snapshot_id"),
        "model_ece": expected_calibration_error(rows, "model_probability"),
        "mean_model_probability": mean(row.get("model_probability") for row in rows),
        "winner_rows": len(winners),
        "winner_model_probability": mean(row.get("model_probability") for row in winners),
        "loser_model_probability": mean(row.get("model_probability") for row in losers),
    }
    summary.update(summarize_partitions(rows))
    return summary


def summarize_by_hour(rows):
    output = []
    for hour, hour_rows in sorted(rows_for_group(rows, "cutoff_hour").items(), key=lambda item: int(item[0]) if item[0] is not None else 99):
        if hour is None:
            continue
        summary = model_score_rows(hour_rows)
        if not summary:
            continue
        summary["hour"] = int(hour)
        summary["hour_label"] = f"{int(hour):02d}:00"
        summary["hour_regime"] = hour_regime(hour)
        output.append(summary)
    return output


def summarize_by_market(rows):
    output = []
    for market_id, market_rows in sorted(rows_for_group(rows, "market_id").items(), key=lambda item: str(item[0])):
        summary = model_score_rows(market_rows)
        if summary:
            summary["market_id"] = market_id
            output.append(summary)
    return output


def current_max_group_rows(rows, fields):
    grouped = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        grouped[key].append(row)
    output = []
    for key, group_rows in grouped.items():
        item = summarize_current_max_rows(group_rows)
        for field, value in zip(fields, key):
            item[field] = value
        output.append(item)
    return sorted(output, key=lambda row: tuple(str(row.get(field) or "") for field in fields))


def summarize_current_max_rows(rows):
    rows = list(rows)
    disposition_counts = Counter(row.get("feature_disposition") for row in rows)
    state_counts = Counter(row.get("current_max_state") for row in rows)
    risky = [
        row for row in rows
        if row.get("feature_disposition") in {"null_before_reset", "support_only"}
    ]
    early_gap = [
        row for row in rows
        if row.get("current_max_state") == "early_current_max_history_gap"
    ]
    gaps = [row.get("gap_to_wu_history") for row in rows if row.get("gap_to_wu_history") is not None]
    return {
        "snapshot_rows": len(rows),
        "with_current_max": sum(1 for row in rows if row.get("wu_max_since_7am") is not None),
        "pre_reset_null_count": disposition_counts.get("null_before_reset", 0),
        "support_only_count": disposition_counts.get("support_only", 0),
        "validated_count": disposition_counts.get("validated", 0),
        "risky_or_guarded_count": len(risky),
        "early_large_gap_count": len(early_gap),
        "max_gap_to_wu_history": max(gaps) if gaps else None,
        "mean_gap_to_wu_history": mean(gaps),
        "state_counts": dict(sorted(state_counts.items())),
        "feature_disposition_counts": dict(sorted(disposition_counts.items())),
    }


def build_current_max_payload(rows):
    rows = list(rows)
    focused = [
        row for row in rows
        if row.get("pre_reset")
        or row.get("current_max_state") == "early_current_max_history_gap"
        or (
            row.get("cutoff_hour") is not None
            and int(row.get("cutoff_hour")) <= EARLY_GAP_HOUR_MAX
            and (row.get("gap_to_wu_history") or 0.0) >= CURRENT_MAX_GAP_THRESHOLD
        )
    ]
    examples = sorted(
        focused,
        key=lambda row: (
            row.get("gap_to_wu_history") is None,
            -(row.get("gap_to_wu_history") or -9999.0),
            str(row.get("market_id") or ""),
            str(row.get("captured_at_local") or ""),
        ),
    )[:30]
    return {
        "summary": summarize_current_max_rows(rows),
        "by_market_hour": current_max_group_rows(focused, ("market_id", "cutoff_hour")),
        "examples": examples,
        "rows": rows,
        "focused_row_count": len(focused),
        "focus_definition": (
            "pre-reset current max rows plus early snapshots with current max at least "
            f"{CURRENT_MAX_GAP_THRESHOLD:g} degrees above WU history high"
        ),
    }


def build_price_free_learning(
    labels_csv=DEFAULT_LABELS_CSV,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    quality_grades=DEFAULT_QUALITY_GRADES,
    markets=None,
    start_date=None,
    end_date=None,
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
    all_current_max_rows = []
    days = []
    score_errors = []
    reason_counts = Counter()
    for item in labels:
        try:
            rows, current_max_rows, day = score_folder(item["folder"], item["label"])
        except Exception as exc:  # pragma: no cover - durable report surface
            score_errors.append({"folder": str(item["folder"]), "error": str(exc)})
            continue
        all_rows.extend(rows)
        all_current_max_rows.extend(current_max_rows)
        days.append(day)
        reason_counts.update(day.get("price_free_reasons") or [])

    checkpoint_rows = hourly_checkpoint_rows(all_rows)
    by_hour = summarize_by_hour(checkpoint_rows)
    all_snapshot_by_hour = summarize_by_hour(all_rows)
    overall_checkpoint = model_score_rows(checkpoint_rows) or {}
    overall_all_snapshots = model_score_rows(all_rows) or {}
    current_max = build_current_max_payload(all_current_max_rows)
    status = "OK" if all_rows else "NO_SCORED_ROWS"

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now().isoformat(),
        "status": status,
        "evidence_classification": {
            "lane": "diagnostic_price_free_not_promotion_evidence",
            "uses_market_prices": False,
            "counts_toward_polymarket_benchmark": False,
            "counts_toward_retrain_input": bool(all_rows),
        },
        "inputs": {
            "labels_csv": str(Path(labels_csv)),
            "snapshots_root": str(Path(snapshots_root)),
            "quality_grades": list(quality_grades or []),
            "markets": list(markets or []),
            "start_date": str(start_date) if start_date else None,
            "end_date": str(end_date) if end_date else None,
        },
        "corpus": {
            "selected_label_count": len(labels),
            "scored_market_days": sum(1 for day in days if day.get("rows")),
            "markets": sorted({day.get("market_id") for day in days if day.get("market_id")}),
            "date_min": min((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "date_max": max((day.get("target_date") for day in days if day.get("target_date")), default=None),
            "all_snapshot_rows": len(all_rows),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "price_free_reason_counts": dict(sorted(reason_counts.items())),
            "skipped_labels": skipped,
            "score_errors": score_errors,
        },
        "days": days,
        "overall": {
            "hourly_checkpoint": overall_checkpoint,
            "all_snapshots": overall_all_snapshots,
        },
        "by_hour": by_hour,
        "by_market": summarize_by_market(checkpoint_rows),
        "all_snapshot_by_hour": all_snapshot_by_hour,
        "snapshot_partitions": snapshot_partition_stats(checkpoint_rows),
        "current_max_carryover": current_max,
        "daily_summary": {
            "status": status,
            "scored_market_days": sum(1 for day in days if day.get("rows")),
            "hourly_checkpoint_rows": len(checkpoint_rows),
            "final_top_hit_rate": overall_checkpoint.get("partition_model_top_is_winner_rate"),
            "final_winner_probability": overall_checkpoint.get("partition_model_winner_probability"),
            "current_max_guarded_count": (current_max.get("summary") or {}).get("risky_or_guarded_count", 0),
        },
    }
    rerun_command = build_rerun_command(
        "weather.reporting.price_free_model_learning",
        labels_csv=labels_csv,
        snapshots_root=snapshots_root,
        quality_grades=quality_grades,
        markets=markets,
        start_date=start_date,
        end_date=end_date,
    )
    return attach_scoring_liveness(
        payload,
        artifact_name="price_free_model_learning",
        labels_csv=labels_csv,
        quality_grades=quality_grades,
        last_scored_target_date=(payload.get("corpus") or {}).get("date_max"),
        rerun_command=rerun_command,
    )


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


def hour_table_rows(rows):
    return [
        [
            row.get("hour_label"),
            row.get("n"),
            row.get("market_days"),
            row.get("markets"),
            fmt_num(row.get("model_brier")),
            fmt_num(row.get("model_logloss")),
            fmt_num(row.get("model_ece")),
            fmt_pct(row.get("partition_model_top_is_winner_rate")),
            fmt_pct(row.get("partition_model_winner_probability")),
            fmt_num(row.get("partition_model_winner_rank"), 2),
            fmt_num(row.get("partition_model_effective_bands"), 2),
        ]
        for row in rows
    ]


def current_max_table_rows(rows):
    return [
        [
            row.get("market_id"),
            row.get("cutoff_hour"),
            row.get("snapshot_rows"),
            row.get("pre_reset_null_count"),
            row.get("support_only_count"),
            row.get("validated_count"),
            row.get("early_large_gap_count"),
            fmt_num(row.get("max_gap_to_wu_history"), 2),
        ]
        for row in rows
    ]


def render_report(payload):
    corpus = payload.get("corpus") or {}
    inputs = payload.get("inputs") or {}
    overall = ((payload.get("overall") or {}).get("hourly_checkpoint") or {})
    current_max = payload.get("current_max_carryover") or {}
    current_summary = current_max.get("summary") or {}
    liveness = payload.get("scoring_liveness") or {}
    rerun = ".\\venv\\Scripts\\python.exe -m weather.reporting.price_free_model_learning"
    if inputs.get("quality_grades") != list(DEFAULT_QUALITY_GRADES):
        rerun += f" --quality-grades {','.join(inputs.get('quality_grades') or [])}"
    lines = [
        "# Price-Free Model Learning Audit",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        f"Status: `{payload.get('status')}`",
        "",
        "This artifact is diagnostic weather-model evidence. It does not compare against Polymarket prices and does not count as promotion evidence versus the market benchmark.",
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
            ["Scoring liveness", liveness.get("status") or "-"],
            ["Last scored target date", liveness.get("last_scored_target_date") or "-"],
            ["Latest settled label date", liveness.get("latest_settled_label_date") or "-"],
            ["All snapshot rows", corpus.get("all_snapshot_rows", 0)],
            ["Hourly checkpoint rows", corpus.get("hourly_checkpoint_rows", 0)],
            ["Price-free reasons", json.dumps(corpus.get("price_free_reason_counts") or {}, sort_keys=True)],
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
        "## Model-Only Score",
        "",
    ]
    lines += markdown_table(
        ["Scope", "Rows", "Market-days", "Model Brier", "Model LogLoss", "Model ECE", "Top Hit", "Winner P", "Winner Rank"],
        [[
            "Hourly checkpoints",
            overall.get("n", 0),
            overall.get("market_days", 0),
            fmt_num(overall.get("model_brier")),
            fmt_num(overall.get("model_logloss")),
            fmt_num(overall.get("model_ece")),
            fmt_pct(overall.get("partition_model_top_is_winner_rate")),
            fmt_pct(overall.get("partition_model_winner_probability")),
            fmt_num(overall.get("partition_model_winner_rank"), 2),
        ]],
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
            "Model LogLoss",
            "Model ECE",
            "Top Hit",
            "Winner P",
            "Winner Rank",
            "Eff Bands",
        ],
        hour_table_rows(payload.get("by_hour") or []),
    )
    lines += [
        "",
        "## Current-Max Carryover Guard",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Snapshot rows", current_summary.get("snapshot_rows", 0)],
            ["Pre-reset null rows", current_summary.get("pre_reset_null_count", 0)],
            ["Support-only rows", current_summary.get("support_only_count", 0)],
            ["Validated rows", current_summary.get("validated_count", 0)],
            ["Early large history-gap rows", current_summary.get("early_large_gap_count", 0)],
            ["Max gap to WU history", fmt_num(current_summary.get("max_gap_to_wu_history"), 2)],
            ["State counts", json.dumps(current_summary.get("state_counts") or {}, sort_keys=True)],
            ["Feature disposition counts", json.dumps(current_summary.get("feature_disposition_counts") or {}, sort_keys=True)],
        ],
    )
    lines += [
        "",
        "### Focused Market-Hour Slice",
        "",
    ]
    lines += markdown_table(
        [
            "Market",
            "Hour",
            "Snapshots",
            "Pre-reset null",
            "Support-only",
            "Validated",
            "Early large gaps",
            "Max WU gap",
        ],
        current_max_table_rows(current_max.get("by_market_hour") or []),
    )
    examples = current_max.get("examples") or []
    if examples:
        lines += [
            "",
            "### Largest Current-Max Gaps",
            "",
        ]
        lines += markdown_table(
            ["Market", "Hour", "Snapshot", "Current max", "WU history", "Gap", "Disposition", "State"],
            [
                [
                    row.get("market_id"),
                    row.get("cutoff_hour"),
                    row.get("snapshot_id"),
                    fmt_num(row.get("wu_max_since_7am"), 2),
                    fmt_num(row.get("wu_history_high"), 2),
                    fmt_num(row.get("gap_to_wu_history"), 2),
                    row.get("feature_disposition"),
                    row.get("current_max_state"),
                ]
                for row in examples[:20]
            ],
        )
    lines += [
        "",
        "## Caveats",
        "",
        "- This report intentionally ignores market prices even when some are present.",
        "- Top-hit and winner-rank metrics are per model partition, not tradeable edge.",
        "- Current-max classification is post-settlement audit metadata; pre-7 AM rows are treated as null-before-reset evidence.",
        "",
    ]
    return "\n".join(lines)


HOURLY_CSV_COLUMNS = [
    "hour",
    "hour_label",
    "hour_regime",
    "n",
    "market_days",
    "markets",
    "snapshots",
    "model_brier",
    "model_logloss",
    "model_ece",
    "base_rate",
    "winner_model_probability",
    "loser_model_probability",
    "partition_snapshots",
    "partition_mean_band_count",
    "partition_model_effective_bands",
    "partition_model_norm_entropy",
    "partition_model_top_probability",
    "partition_model_winner_probability",
    "partition_model_winner_rank",
    "partition_model_top_is_winner_rate",
    "partition_model_adjacent_winner_mass",
]

CURRENT_MAX_CSV_COLUMNS = [
    "market_id",
    "event_slug",
    "target_date",
    "snapshot_id",
    "captured_at_local",
    "cutoff_hour",
    "wu_max_since_7am",
    "wu_history_high",
    "wu_current",
    "final_high",
    "current_max_state",
    "feature_disposition",
    "pre_reset",
    "gap_to_wu_history",
    "gap_to_current_temp",
    "gap_to_final_high",
    "reset_hour",
    "gap_threshold",
]


def write_csv_dicts(path, rows, columns):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_outputs(
    payload,
    json_out=DEFAULT_JSON_OUT,
    report_out=DEFAULT_REPORT_OUT,
    hourly_csv_out=DEFAULT_HOURLY_CSV_OUT,
    current_max_csv_out=DEFAULT_CURRENT_MAX_CSV_OUT,
):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    hourly_csv = write_csv_dicts(hourly_csv_out, payload.get("by_hour") or [], HOURLY_CSV_COLUMNS)
    current_max_csv = write_csv_dicts(
        current_max_csv_out,
        ((payload.get("current_max_carryover") or {}).get("rows") or []),
        CURRENT_MAX_CSV_COLUMNS,
    )
    return json_out, report_out, hourly_csv, current_max_csv


def build_parser():
    parser = argparse.ArgumentParser(description="Score settled model output without requiring market prices.")
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument(
        "--quality-grades",
        default=",".join(DEFAULT_QUALITY_GRADES),
        help="Comma-separated settlement quality grades to include.",
    )
    parser.add_argument("--markets", default="", help="Comma-separated market IDs to include.")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--hourly-csv-out", default=str(DEFAULT_HOURLY_CSV_OUT))
    parser.add_argument("--current-max-csv-out", default=str(DEFAULT_CURRENT_MAX_CSV_OUT))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    payload = build_price_free_learning(
        labels_csv=args.labels_csv,
        snapshots_root=args.snapshots_root,
        quality_grades=parse_quality_grades(args.quality_grades),
        markets=parse_csv_values(args.markets),
        start_date=args.start_date,
        end_date=args.end_date,
    )
    json_out, report_out, hourly_csv, current_max_csv = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        hourly_csv_out=args.hourly_csv_out,
        current_max_csv_out=args.current_max_csv_out,
    )
    print(f"Wrote {relative_to_repo(json_out)}")
    print(f"Wrote {relative_to_repo(report_out)}")
    print(f"Wrote {relative_to_repo(hourly_csv)}")
    print(f"Wrote {relative_to_repo(current_max_csv)}")
    summary = payload.get("daily_summary") or {}
    print(
        "price_free_status={status} scored_market_days={days} hourly_checkpoint_rows={rows}".format(
            status=payload.get("status"),
            days=summary.get("scored_market_days", 0),
            rows=summary.get("hourly_checkpoint_rows", 0),
        )
    )


if __name__ == "__main__":
    main()
