"""Dynamic source-state feature helpers for pooled feature artifacts."""

from __future__ import annotations

import math
from datetime import datetime


DYNAMIC_SOURCE_TRACKED_SOURCES = (
    "wu_history",
    "wu_current",
    "metar",
    "weather_forecast",
    "open_meteo",
    "nws_hourly",
    "global_ensemble",
    "eccc_citypage",
)
DYNAMIC_SOURCE_FORECAST_SOURCES = (
    "weather_forecast",
    "open_meteo",
    "nws_hourly",
    "global_ensemble",
    "eccc_citypage",
)
DYNAMIC_SOURCE_NUMERIC_COLUMNS = [
    "source_state_all_fresh",
    "source_state_missing_sources",
    "source_failed_count",
    "source_stale_count",
    "source_unknown_count",
    "source_wu_history_fresh",
    "source_wu_history_stale",
    "source_wu_history_failed",
    "source_wu_history_age_minutes",
    "source_wu_history_latest_minute",
    "source_wu_history_row_count",
    "source_metar_stale",
    "source_metar_failed",
    "source_metar_age_minutes",
    "source_forecast_failed_count",
    "source_forecast_stale_count",
    "source_forecast_payload_age_minutes",
    "source_forecast_max_age_minutes",
    "source_cross_source_max_disagreement",
]
DYNAMIC_SOURCE_CATEGORICAL_COLUMNS = ["source_status_group"]


def boolish(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def finite_float(value):
    if value in (None, ""):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def minute_of_day(value):
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if ":" not in text:
        return None
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (TypeError, ValueError, IndexError):
        return None
    return hour * 60 + minute


def source_status_kind(item):
    item = item or {}
    status = str(item.get("status") or "").strip().lower()
    ok = boolish(item.get("ok"))
    stale = boolish(item.get("stale"))
    if ok is False or status in {"failed", "error", "missing"}:
        return "failed"
    if stale is True or status in {"stale", "stale_cache", "expired"}:
        return "stale"
    if ok is True or status in {"fresh", "ok", "available"}:
        return "fresh"
    return "unknown"


def source_row_count(item):
    item = item or {}
    explicit = finite_float(item.get("row_count"))
    if explicit is not None:
        return explicit
    data = item.get("data")
    if data is None:
        return 0.0
    if isinstance(data, list):
        return float(len(data))
    if not isinstance(data, dict):
        return 1.0
    for key in ("rows", "observations", "periods", "forecasts", "history"):
        value = data.get(key)
        if isinstance(value, list):
            return float(len(value))
    if data.get("available") is False:
        return 0.0
    return 1.0 if data else 0.0


def source_age_minutes(item, captured_at=None):
    item = item or {}
    for key in ("age_minutes", "cache_age_minutes"):
        value = finite_float(item.get(key))
        if value is not None:
            return value
    if captured_at is None:
        return None
    fetched = parse_iso_datetime(item.get("fetched_at"))
    if fetched is None:
        return None
    captured = captured_at
    if isinstance(captured, str):
        captured = parse_iso_datetime(captured)
    if captured is None:
        return None
    if fetched.tzinfo is None or captured.tzinfo is None:
        return None
    return max(0.0, (captured - fetched).total_seconds() / 60.0)


def latest_source_minute(item):
    item = item or {}
    data = item.get("data")
    rows = []
    if isinstance(data, dict):
        rows = data.get("rows") or data.get("observations") or data.get("history") or []
    elif isinstance(data, list):
        rows = data
    minutes = [
        minute
        for minute in (minute_of_day(row.get("time") or row.get("local_time")) for row in rows)
        if minute is not None
    ]
    return max(minutes) if minutes else None


def source_list_label(sources, limit=3):
    names = sorted(str(source) for source in sources if source not in (None, ""))
    if len(names) <= limit:
        return ",".join(names)
    head = ",".join(names[:limit])
    return f"{head},+{len(names) - limit}"


def source_status_group_from_items(items):
    if not items:
        return "missing_sources"
    by_state = {}
    for source, item in sorted(items.items()):
        state = source_status_kind(item)
        if state == "fresh":
            continue
        by_state.setdefault(state, []).append(source)
    parts = []
    for state in ("failed", "stale", "unknown"):
        if by_state.get(state):
            parts.append(f"{state}:{source_list_label(by_state[state])}")
    return ";".join(parts) if parts else "all_fresh"


def source_items_from_status_rows(rows):
    output = {}
    for row in rows or []:
        source = row.get("source") or "unknown"
        output[source] = {
            "ok": row.get("ok"),
            "status": row.get("status"),
            "stale": row.get("stale"),
            "age_minutes": row.get("age_minutes"),
            "fetched_at": row.get("fetched_at"),
            "row_count": row.get("row_count"),
        }
    return output


def default_dynamic_source_state_features(row=None):
    row = row or {}
    cutoff_hour = finite_float(row.get("cutoff_hour")) or 0.0
    minutes_since_cutoff = finite_float(row.get("minutes_since_cutoff")) or 0.0
    latest_minute = int(cutoff_hour) * 60
    forecast_disagreement = finite_float(row.get("forecast_disagreement")) or 0.0
    features = {
        column: 0.0
        for column in DYNAMIC_SOURCE_NUMERIC_COLUMNS
    }
    features.update({
        "source_status_group": "all_fresh",
        "source_state_all_fresh": 1.0,
        "source_state_missing_sources": 0.0,
        "source_wu_history_fresh": 1.0,
        "source_wu_history_age_minutes": minutes_since_cutoff,
        "source_wu_history_latest_minute": float(latest_minute),
        "source_wu_history_row_count": 1.0,
        "source_forecast_payload_age_minutes": 0.0,
        "source_forecast_max_age_minutes": 0.0,
        "source_cross_source_max_disagreement": forecast_disagreement,
    })
    return features


def dynamic_source_state_features(
    sources=None,
    source_status_rows=None,
    captured_at=None,
    base_features=None,
):
    items = source_items_from_status_rows(source_status_rows) if source_status_rows is not None else {}
    if not items:
        items = {
            source: (sources or {}).get(source) or {}
            for source in DYNAMIC_SOURCE_TRACKED_SOURCES
            if source in (sources or {})
        }
    if not items:
        features = default_dynamic_source_state_features(base_features)
        features["source_status_group"] = "missing_sources"
        features["source_state_all_fresh"] = 0.0
        features["source_state_missing_sources"] = 1.0
        return features

    features = {
        column: 0.0
        for column in DYNAMIC_SOURCE_NUMERIC_COLUMNS
    }
    status_group = source_status_group_from_items(items)
    features["source_status_group"] = status_group
    features["source_state_all_fresh"] = 1.0 if status_group == "all_fresh" else 0.0
    features["source_state_missing_sources"] = 0.0

    state_by_source = {source: source_status_kind(item) for source, item in items.items()}
    features["source_failed_count"] = float(sum(1 for state in state_by_source.values() if state == "failed"))
    features["source_stale_count"] = float(sum(1 for state in state_by_source.values() if state == "stale"))
    features["source_unknown_count"] = float(sum(1 for state in state_by_source.values() if state == "unknown"))

    wu_history = items.get("wu_history") or {}
    wu_state = state_by_source.get("wu_history", "unknown")
    features["source_wu_history_fresh"] = 1.0 if wu_state == "fresh" else 0.0
    features["source_wu_history_stale"] = 1.0 if wu_state == "stale" else 0.0
    features["source_wu_history_failed"] = 1.0 if wu_state == "failed" else 0.0
    features["source_wu_history_row_count"] = source_row_count(wu_history)
    latest_minute = finite_float((base_features or {}).get("latest_wu_history_minute"))
    if latest_minute is None:
        latest_minute = latest_source_minute(wu_history)
    features["source_wu_history_latest_minute"] = latest_minute
    age = source_age_minutes(wu_history, captured_at=captured_at)
    if age is None and latest_minute is not None:
        cutoff_hour = finite_float((base_features or {}).get("cutoff_hour")) or 0.0
        minutes_since_cutoff = finite_float((base_features or {}).get("minutes_since_cutoff")) or 0.0
        wall_minute = int(cutoff_hour) * 60 + minutes_since_cutoff
        age = max(0.0, wall_minute - float(latest_minute))
    features["source_wu_history_age_minutes"] = age

    metar = items.get("metar") or {}
    metar_state = state_by_source.get("metar", "unknown")
    features["source_metar_stale"] = 1.0 if metar_state == "stale" else 0.0
    features["source_metar_failed"] = 1.0 if metar_state == "failed" else 0.0
    features["source_metar_age_minutes"] = source_age_minutes(metar, captured_at=captured_at)

    forecast_ages = []
    for source in DYNAMIC_SOURCE_FORECAST_SOURCES:
        item = items.get(source) or {}
        state = state_by_source.get(source)
        if state == "failed":
            features["source_forecast_failed_count"] += 1.0
        elif state == "stale":
            features["source_forecast_stale_count"] += 1.0
        age = source_age_minutes(item, captured_at=captured_at)
        if age is not None:
            forecast_ages.append(age)
    if forecast_ages:
        features["source_forecast_payload_age_minutes"] = min(forecast_ages)
        features["source_forecast_max_age_minutes"] = max(forecast_ages)
    forecast_disagreement = finite_float((base_features or {}).get("forecast_disagreement"))
    features["source_cross_source_max_disagreement"] = (
        forecast_disagreement if forecast_disagreement is not None else 0.0
    )
    return features


def add_dynamic_source_state_features(
    record,
    sources=None,
    source_status_rows=None,
    captured_at=None,
    historical_default=False,
):
    features = (
        default_dynamic_source_state_features(record)
        if historical_default
        else dynamic_source_state_features(
            sources=sources,
            source_status_rows=source_status_rows,
            captured_at=captured_at,
            base_features=record,
        )
    )
    record.update(features)
    return record


def feature_names_need_dynamic_source_state(feature_names):
    if not feature_names:
        return False
    dynamic_names = set(DYNAMIC_SOURCE_NUMERIC_COLUMNS + DYNAMIC_SOURCE_CATEGORICAL_COLUMNS)
    return any(
        name in dynamic_names or str(name).startswith("source_status_group_")
        for name in feature_names
    )
