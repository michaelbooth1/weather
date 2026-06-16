"""Settlement-scored snapshot tape transforms."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from weather.backtesting.settlement_io import (
    row_band_value_hi,
    resolve_outcome,
)
from weather.market.market_config import date_from_event_slug
from weather.model.feature_store import FEATURE_COLUMNS
from weather.scoring.metrics import (
    group_sort_key,
    missing,
    safe_float,
    score_rows,
    unique_sorted,
)
from weather.scoring.trading import pnl_for_rows, pnl_trades, trade_pnl


DEFAULT_FIXED_CUTOFF_HOURS = (9, 10, 12, 13, 15, 16, 17, 18, 20)


def parse_snapshot_time(value):
    if missing(value) or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def capture_minute(value):
    parsed = parse_snapshot_time(value)
    if not parsed:
        return None
    return parsed.hour * 60 + parsed.minute


def capture_hour(value):
    minute = capture_minute(value)
    if minute is None:
        return None
    return minute // 60


def timestamp_key(row):
    parsed = parse_snapshot_time(row.get("captured_at_local"))
    if parsed is not None:
        return parsed.timestamp()
    return float(row.get("row_order") or 0)


def bin_type(kind):
    if kind == "lte":
        return "lte"
    if kind == "gte":
        return "gte"
    return "eq"


def last_pre_close_rows(rows):
    """One row per target day and market band: the last available snapshot."""
    latest = {}
    for row in rows:
        key = (row.get("target_date"), row.get("band"))
        if key not in latest or timestamp_key(row) >= timestamp_key(latest[key]):
            latest[key] = row
    return [latest[key] for key in sorted(latest, key=lambda item: (str(item[0]), str(item[1])))]


def fixed_cutoff_rows(rows, fixed_cutoffs=DEFAULT_FIXED_CUTOFF_HOURS):
    """For each cutoff hour, pick the first row at/after that cutoff per day-band."""
    by_day_band = defaultdict(list)
    for row in rows:
        by_day_band[(row.get("target_date"), row.get("band"))].append(row)
    for group_rows in by_day_band.values():
        group_rows.sort(key=timestamp_key)

    selected = {int(cutoff): [] for cutoff in fixed_cutoffs}
    for group_rows in by_day_band.values():
        for cutoff in selected:
            cutoff_minute = int(cutoff) * 60
            candidates = [
                row for row in group_rows
                if row.get("capture_minute") is not None
                and row["capture_minute"] >= cutoff_minute
            ]
            if candidates:
                selected[cutoff].append(candidates[0])
    return selected


def grouped_scores(rows, group_key):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.get(group_key)].append(row)
    output = []
    for group, group_rows in sorted(grouped.items(), key=lambda item: group_sort_key(item[0])):
        score = score_rows(group_rows)
        if score:
            output.append({"group": group, **score})
    return output


def feature_gap_bucket(value):
    value = safe_float(value)
    if value is None:
        return "missing"
    if value <= 0:
        return "<=0C"
    if value <= 2:
        return "0-2C"
    return ">2C"


def live_reading_gap_bucket(value):
    value = safe_float(value)
    if value is None:
        return "missing"
    if value <= 0:
        return "<=0"
    if value <= 1:
        return "0-1"
    if value <= 2:
        return "1-2"
    return ">2"


def minutes_since_cutoff_bucket(value):
    value = safe_float(value)
    if value is None:
        return "missing"
    if value < 20:
        return "00-19"
    if value < 40:
        return "20-39"
    if value < 60:
        return "40-59"
    return "60+"


def load_feature_vectors(folder):
    path = Path(folder) / "features_long.csv"
    if not path.exists():
        return {}
    try:
        features = pd.read_csv(path)
    except Exception:
        return {}
    if "snapshot_id" not in features:
        return {}
    out = {}
    for _, row in features.iterrows():
        snapshot_id = row.get("snapshot_id")
        if missing(snapshot_id):
            continue
        out[str(snapshot_id)] = row.to_dict()
    return out


def attach_feature_vector(scoring_row, feature_row):
    if not feature_row:
        scoring_row["feature_schema_version"] = None
        scoring_row["feature_forecast_gap_bucket"] = "missing"
        return scoring_row
    scoring_row["feature_schema_version"] = feature_row.get("feature_schema_version")
    for column in FEATURE_COLUMNS:
        scoring_row[f"feature_{column}"] = feature_row.get(column)
    scoring_row["feature_forecast_gap_bucket"] = feature_gap_bucket(feature_row.get("forecast_gap"))
    scoring_row["feature_live_reading_gap_bucket"] = live_reading_gap_bucket(
        feature_row.get("live_reading_minus_high")
    )
    scoring_row["feature_minutes_since_cutoff_bucket"] = minutes_since_cutoff_bucket(
        feature_row.get("minutes_since_cutoff")
    )
    return scoring_row


def backtest_tape(df, settlement_bucket, thresholds, target_date=None, feature_index=None):
    """Score one market day's tape."""
    rows = []
    target_date_value = target_date.isoformat() if target_date else None
    for row_order, (_, r) in enumerate(df.iterrows()):
        mp = safe_float(r.get("model_probability"))
        my = safe_float(r.get("market_yes"))
        if mp is None or my is None:
            continue
        outcome = resolve_outcome(
            r.get("bin_kind"),
            r.get("bin_value_c"),
            settlement_bucket,
            value_hi=row_band_value_hi(r),
        )
        if outcome is None:
            continue
        captured_at = r.get("captured_at_local")
        minute = capture_minute(captured_at)
        event_slug = r.get("event_slug")
        if target_date_value is None:
            inferred = date_from_event_slug(event_slug) if not missing(event_slug) else None
            target_date_value = inferred.isoformat() if inferred else None
        scoring_row = {
            "row_order": row_order,
            "snapshot_id": r.get("snapshot_id"),
            "target_date": target_date_value,
            "event_slug": event_slug,
            "captured_at_local": captured_at,
            "capture_minute": minute,
            "cutoff_hour": minute // 60 if minute is not None else None,
            "model_version": r.get("model_version"),
            "band": r.get("range_label"),
            "bin_kind": r.get("bin_kind"),
            "bin_type": bin_type(r.get("bin_kind")),
            "bin_value_c": safe_float(r.get("bin_value_c")),
            "bin_value_hi": safe_float(row_band_value_hi(r)),
            "model_probability": mp,
            "market_yes": my,
            "market_no": safe_float(r.get("market_no")),
            "outcome": int(outcome),
        }
        attach_feature_vector(
            scoring_row,
            (feature_index or {}).get(str(r.get("snapshot_id"))),
        )
        rows.append(scoring_row)

    per_snapshot = pnl_for_rows(rows, thresholds)

    first_entry = {}
    for threshold in thresholds:
        seen, entries = set(), []
        for row in rows:
            key = (row.get("target_date"), row.get("band"))
            if key in seen:
                continue
            trade = trade_pnl(
                row["model_probability"],
                row["market_yes"],
                row.get("market_no"),
                row["outcome"],
                threshold,
            )
            if trade is not None:
                entries.append(trade)
                seen.add(key)
        first_entry[threshold] = pnl_trades(entries)

    thr0 = min(thresholds)
    persistence = []
    for band in sorted({r["band"] for r in rows}):
        band_rows = [r for r in rows if r["band"] == band]
        edges = [r["model_probability"] - r["market_yes"] for r in band_rows]
        outcome = band_rows[0]["outcome"]
        frac_pos = sum(1 for edge in edges if edge > thr0) / len(edges)
        frac_neg = sum(1 for edge in edges if edge < -thr0) / len(edges)
        mean_edge = sum(edges) / len(edges)
        persistence.append({
            "band": band,
            "snapshots": len(band_rows),
            "mean_edge": mean_edge,
            "frac_edge_up": frac_pos,
            "frac_edge_down": frac_neg,
            "settled_yes": outcome,
        })
    return rows, per_snapshot, first_entry, persistence


def feature_vector_coverage(rows):
    total = len(rows)
    with_features = [
        row for row in rows
        if not missing(row.get("feature_schema_version"))
    ]
    schema_versions = unique_sorted(row.get("feature_schema_version") for row in with_features)
    return {
        "rows": total,
        "rows_with_features": len(with_features),
        "coverage": len(with_features) / total if total else None,
        "schema_versions": schema_versions,
    }
