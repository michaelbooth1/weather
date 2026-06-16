"""Fleet data-layer audit.

This report answers a broader question than collection health: are we capturing
the right data, often enough, with enough history to improve the model? It
combines snapshot cadence/completeness, historical source coverage, loop state,
and known market-microstructure gaps into one durable artifact.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

from weather.reporting.formatting import (
    fmt_num,
    markdown_table,
)
from weather.collection.collection_health import summarize_folder
from weather.collection.snapshot_tracker import LOOP_STATUS_PATH, loop_health
from weather.market.market_config import date_from_event_slug
from weather.market.market_microstructure import CLOB_LOOP_STATUS_PATH, clob_loop_health
from weather.market.market_registry import all_specs, spec_for_slug
from weather.model.toronto_model import TORONTO_TZ
from weather.sources.canonical_history_guardrails import canonical_guardrail_report
from weather.sources.daily_summary import native_bucket, native_high
from weather.sources.reanalysis_history import ReanalysisStore
from weather.sources.supplemental_station_validation import (
    DEFAULT_OUT as DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
    load_validation_report,
    promotion_gate_for_source,
)
from weather.sources.supplemental_stations import guard_not_canonical_root, source_root, supplemental_sources


SCHEMA_VERSION = "data_layer_audit_v0.3"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_OUT = data_path() / "backtest" / "data_layer_audit.json"
DEFAULT_REPORT = data_path() / "backtest" / "data_layer_audit_report.md"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"

SNAPSHOT_LONG = "snapshots_long.csv"
SNAPSHOT_OPTIONAL_ARTIFACTS = {
    "replay_inputs": "replay_inputs.jsonl",
    "replay_input_status": "replay_input_status_long.csv",
    "source_status": "source_status_long.csv",
    "features": "features_long.csv",
    "components": "components_long.csv",
    "forecasts": "forecasts_long.csv",
    "forecast_payloads": "forecast_payloads_long.csv",
    "clob_features": "clob_features_long.csv",
    "settlement": "settlement.json",
}
REQUIRED_SNAPSHOT_ARTIFACTS = (
    "replay_input_status",
    "forecasts",
    "clob_features",
)
WARN_SNAPSHOT_ARTIFACTS = (
    "replay_inputs",
    "source_status",
    "features",
    "components",
)
FORECAST_PAYLOAD_ARTIFACT = "forecast_payloads"
DEFAULT_AUDIT_THRESHOLDS = {
    "min_snapshot_field_fill_rate": 0.90,
    "required_artifact_rate": 1.0,
    "forecast_payload_artifact_rate": 1.0,
    "max_source_stale_or_failed_rate": 0.05,
    "max_reanalysis_raw_only_days": 0,
    "max_quarantined_impossible_observations": 0,
}

HISTORICAL_SOURCE_ROOTS = {
    "wu": data_path() / "wunderground",
    "metar": data_path() / "metar",
    "ghcnh": data_path() / "noaa_ghcnh",
    "reanalysis": data_path() / "reanalysis",
}

MICROSTRUCTURE_DOCS = [
    {
        "name": "Polymarket CLOB order book",
        "url": "https://docs.polymarket.com/api-reference/market-data/get-order-book",
        "why": "Read-only endpoint returns current bids/asks, market details, and last trade price.",
    },
    {
        "name": "Polymarket market WebSocket",
        "url": "https://docs.polymarket.com/api-reference/wss/market",
        "why": "Public stream for real-time orderbook, price, and market lifecycle updates.",
    },
    {
        "name": "Polymarket price history",
        "url": "https://docs.polymarket.com/api-reference/markets/get-prices-history",
        "why": "Read-only historical price series by token with configurable fidelity.",
    },
]


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def iter_dates(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def season_dates(start, end, start_month=5, start_day=20, end_month=6, end_day=30):
    days = []
    for year in range(start.year, end.year + 1):
        lo = max(start, date(year, start_month, start_day))
        hi = min(end, date(year, end_month, end_day))
        if lo <= hi:
            days.extend(iter_dates(lo, hi))
    return days


def safe_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def safe_max(values):
    values = [value for value in values if value is not None]
    return max(values) if values else None


def pct(part, total):
    return (float(part) / float(total)) if total else None


def read_loop_status(path=LOOP_STATUS_PATH):
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def loop_summary(path=LOOP_STATUS_PATH, interval_minutes=10.0):
    status = read_loop_status(path)
    health = loop_health(status, datetime.now(TORONTO_TZ), interval_minutes)
    return {
        "status_path": str(path),
        "state": health.get("state"),
        "pid": health.get("pid"),
        "configured_interval_minutes": (status or {}).get("interval_minutes"),
        "heartbeat_age_min": health.get("heartbeat_age_min"),
        "last_snapshot_age_min": health.get("last_snapshot_age_min"),
        "consecutive_errors": health.get("consecutive_errors"),
        "last_error": health.get("last_error"),
        "started_at": health.get("started_at"),
    }


def clob_loop_summary(path=CLOB_LOOP_STATUS_PATH, interval_seconds=60.0):
    status = read_loop_status(path)
    health = clob_loop_health(status, datetime.now(timezone.utc), interval_seconds)
    return {
        "status_path": str(path),
        "state": health.get("state"),
        "pid": health.get("pid"),
        "configured_interval_seconds": (status or {}).get("interval_seconds"),
        "fast_interval_seconds": (status or {}).get("fast_interval_seconds"),
        "heartbeat_age_seconds": health.get("heartbeat_age_seconds"),
        "last_books_age_seconds": health.get("last_books_age_seconds"),
        "consecutive_errors": health.get("consecutive_errors"),
        "error_markets": health.get("error_markets"),
        "last_error": health.get("last_error"),
        "last_mode": health.get("last_mode"),
        "last_sleep_seconds": health.get("last_sleep_seconds"),
        "started_at": health.get("started_at"),
    }


def parse_snapshot_times(path):
    times = {}
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            sid = row.get("snapshot_id")
            ts = row.get("captured_at_local")
            if not sid or sid in times or not ts:
                continue
            try:
                times[sid] = datetime.fromisoformat(ts)
            except ValueError:
                continue
    ordered = sorted(times.values())
    gaps = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(ordered, ordered[1:])
    ]
    return ordered, gaps


def scan_snapshot_csv(path):
    row_count = 0
    field_totals = {}
    nonempty = {}
    market_rows_with_token = 0
    fields = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        for field in fields:
            field_totals[field] = 0
            nonempty[field] = 0
        for row in reader:
            row_count += 1
            for field in fields:
                field_totals[field] += 1
                if row.get(field) not in (None, ""):
                    nonempty[field] += 1
            if (
                row.get("clob_token_id")
                or row.get("clob_yes_token_id")
                or row.get("clob_no_token_id")
                or row.get("condition_id")
            ):
                market_rows_with_token += 1
    return {
        "row_count": row_count,
        "fields": fields,
        "field_totals": field_totals,
        "nonempty": nonempty,
        "rows_with_market_token_ids": market_rows_with_token,
    }


def read_csv_dicts(path):
    path = Path(path)
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except (OSError, csv.Error):
        return []


def read_json_dict(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def truthy(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def source_status_summary_for_folder(folder):
    rows = read_csv_dicts(Path(folder) / "source_status_long.csv")
    stale_or_failed = [
        row for row in rows
        if truthy(row.get("stale"))
        or str(row.get("status") or "").lower() in {"failed", "error", "stale_cache"}
        or str(row.get("ok") or "").lower() == "false"
    ]
    by_status = Counter(row.get("status") or "unknown" for row in rows)
    return {
        "row_count": len(rows),
        "source_count": len({row.get("source") for row in rows if row.get("source")}),
        "stale_or_failed_rows": len(stale_or_failed),
        "status_counts": dict(sorted(by_status.items())),
    }


def forecast_payload_summary_for_folder(folder):
    rows = read_csv_dicts(Path(folder) / "forecast_payloads_long.csv")
    return {
        "row_count": len(rows),
        "source_count": len({row.get("source") for row in rows if row.get("source")}),
        "payload_bytes": sum(int(safe_float(row.get("payload_bytes")) or 0) for row in rows),
    }


def clob_feature_summary_for_folder(folder):
    rows = read_csv_dicts(Path(folder) / "clob_features_long.csv")
    available = 0
    price_available = 0
    ws_rows = 0
    for row in rows:
        if safe_float(row.get("clob_feature_available")):
            available += 1
        if safe_float(row.get("clob_price_history_available")):
            price_available += 1
        if (safe_float(row.get("clob_ws_event_count_300s")) or 0.0) > 0:
            ws_rows += 1
    return {
        "row_count": len(rows),
        "book_available_rows": available,
        "price_history_available_rows": price_available,
        "ws_event_window_rows": ws_rows,
    }


def replay_status_summary_for_folder(folder):
    summary = read_json_dict(Path(folder) / "replay_input_status.json")
    rows = read_csv_dicts(Path(folder) / "replay_input_status_long.csv")
    status = summary.get("status_counts") if isinstance(summary.get("status_counts"), dict) else None
    if status is None and isinstance(summary.get("counts"), dict):
        status = summary.get("counts")
    if status is None and rows:
        status = dict(sorted(Counter(
            row.get("replay_input_status") or row.get("status") or "unknown"
            for row in rows
        ).items()))
    return {
        "row_count": len(rows),
        "status_counts": status or {},
    }


def snapshot_folder_audit(folder, interval_minutes=10.0, tolerance=1.5):
    folder = Path(folder)
    path = folder / SNAPSHOT_LONG
    spec = spec_for_slug(folder.name)
    target_date = date_from_event_slug(folder.name)
    times, gaps = parse_snapshot_times(path)
    scanned = scan_snapshot_csv(path)
    try:
        coverage = summarize_folder(
            folder,
            interval_minutes=interval_minutes,
            tolerance=tolerance,
            live=False,
        )
    except Exception as exc:  # noqa: BLE001 - audit should survive one bad tape
        coverage = {"clean": False, "reason": f"{type(exc).__name__}: {exc}"}
    artifact_presence = {
        name: (folder / filename).exists()
        for name, filename in SNAPSHOT_OPTIONAL_ARTIFACTS.items()
    }
    source_status = source_status_summary_for_folder(folder)
    forecast_payloads = forecast_payload_summary_for_folder(folder)
    clob_features = clob_feature_summary_for_folder(folder)
    replay_status = replay_status_summary_for_folder(folder)
    return {
        "folder": str(folder),
        "event_slug": folder.name,
        "market_id": spec.id if spec else None,
        "city": spec.city_label if spec else None,
        "target_date": target_date.isoformat() if target_date else None,
        "snapshot_count": len(times),
        "band_row_count": scanned["row_count"],
        "first_capture": times[0].isoformat() if times else None,
        "last_capture": times[-1].isoformat() if times else None,
        "median_gap_minutes": safe_median(gaps),
        "max_gap_minutes": safe_max(gaps),
        "coverage_clean": bool(coverage.get("clean")),
        "coverage_reason": coverage.get("reason"),
        "capture_ratio": coverage.get("capture_ratio"),
        "artifact_presence": artifact_presence,
        "source_status": source_status,
        "forecast_payloads": forecast_payloads,
        "clob_features": clob_features,
        "replay_input_status": replay_status,
        "fields": scanned["fields"],
        "field_totals": scanned["field_totals"],
        "nonempty": scanned["nonempty"],
        "rows_with_market_token_ids": scanned["rows_with_market_token_ids"],
    }


def snapshot_audit(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, interval_minutes=10.0, tolerance=1.5):
    folders = sorted(Path(snapshots_root).glob(f"*/{SNAPSHOT_LONG}"))
    folder_rows = [
        snapshot_folder_audit(path.parent, interval_minutes=interval_minutes, tolerance=tolerance)
        for path in folders
    ]
    by_market = defaultdict(list)
    field_nonempty = Counter()
    field_totals = Counter()
    artifact_totals = Counter()
    training_ready_artifact_totals = Counter()
    training_ready_folder_count = 0
    training_ready_cutoff = datetime.now(TORONTO_TZ).date()
    source_status_rows = 0
    source_status_stale_or_failed_rows = 0
    source_status_counts = Counter()
    forecast_payload_rows = 0
    forecast_payload_bytes = 0
    clob_feature_rows = 0
    clob_book_available_rows = 0
    clob_price_history_available_rows = 0
    clob_ws_event_window_rows = 0
    replay_status_counts = Counter()
    for row in folder_rows:
        by_market[row.get("market_id")].append(row)
        target_date = parse_date(row.get("target_date"))
        training_ready = bool(target_date and target_date < training_ready_cutoff)
        row["training_ready"] = training_ready
        if training_ready:
            training_ready_folder_count += 1
        field_nonempty.update(row.get("nonempty") or {})
        field_totals.update(row.get("field_totals") or {})
        for name, present in (row.get("artifact_presence") or {}).items():
            if present:
                artifact_totals[name] += 1
                if training_ready:
                    training_ready_artifact_totals[name] += 1
        status = row.get("source_status") or {}
        source_status_rows += int(status.get("row_count") or 0)
        source_status_stale_or_failed_rows += int(status.get("stale_or_failed_rows") or 0)
        source_status_counts.update(status.get("status_counts") or {})
        payloads = row.get("forecast_payloads") or {}
        forecast_payload_rows += int(payloads.get("row_count") or 0)
        forecast_payload_bytes += int(payloads.get("payload_bytes") or 0)
        clob = row.get("clob_features") or {}
        clob_feature_rows += int(clob.get("row_count") or 0)
        clob_book_available_rows += int(clob.get("book_available_rows") or 0)
        clob_price_history_available_rows += int(clob.get("price_history_available_rows") or 0)
        clob_ws_event_window_rows += int(clob.get("ws_event_window_rows") or 0)
        replay = row.get("replay_input_status") or {}
        replay_status_counts.update(replay.get("status_counts") or {})
    low_fill = []
    for field, total in sorted(field_totals.items()):
        filled = field_nonempty[field]
        rate = pct(filled, total)
        if rate is not None and rate < 0.90:
            low_fill.append({
                "field": field,
                "nonempty": filled,
                "total": total,
                "fill_rate": rate,
            })
    low_fill.sort(key=lambda item: (item["fill_rate"], item["field"]))
    market_rows = []
    for market_id, rows in sorted(by_market.items()):
        if market_id is None:
            continue
        market_rows.append({
            "market_id": market_id,
            "market_day_count": len(rows),
            "settled_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("settlement")),
            "clean_days": sum(1 for row in rows if row.get("coverage_clean")),
            "replay_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("replay_inputs")),
            "replay_status_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("replay_input_status")),
            "source_status_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("source_status")),
            "feature_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("features")),
            "component_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("components")),
            "forecast_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("forecasts")),
            "forecast_payload_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("forecast_payloads")),
            "clob_feature_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("clob_features")),
            "median_snapshots_per_day": safe_median([row.get("snapshot_count") for row in rows]),
            "median_gap_minutes": safe_median([row.get("median_gap_minutes") for row in rows]),
            "max_gap_minutes": safe_max([row.get("max_gap_minutes") for row in rows]),
            "latest_target_date": max([row.get("target_date") for row in rows if row.get("target_date")], default=None),
        })
    return {
        "snapshots_root": str(snapshots_root),
        "folder_count": len(folder_rows),
        "total_snapshots": sum(row.get("snapshot_count") or 0 for row in folder_rows),
        "total_band_rows": sum(row.get("band_row_count") or 0 for row in folder_rows),
        "clean_folder_count": sum(1 for row in folder_rows if row.get("coverage_clean")),
        "median_snapshots_per_folder": safe_median([row.get("snapshot_count") for row in folder_rows]),
        "median_capture_gap_minutes": safe_median([row.get("median_gap_minutes") for row in folder_rows]),
        "max_capture_gap_minutes": safe_max([row.get("max_gap_minutes") for row in folder_rows]),
        "artifact_day_counts": dict(sorted(artifact_totals.items())),
        "training_ready_folder_count": training_ready_folder_count,
        "artifact_training_ready_day_counts": dict(sorted(training_ready_artifact_totals.items())),
        "source_status": {
            "row_count": source_status_rows,
            "stale_or_failed_rows": source_status_stale_or_failed_rows,
            "stale_or_failed_rate": pct(source_status_stale_or_failed_rows, source_status_rows),
            "status_counts": dict(sorted(source_status_counts.items())),
        },
        "forecast_payloads": {
            "row_count": forecast_payload_rows,
            "payload_bytes": forecast_payload_bytes,
        },
        "clob_features": {
            "row_count": clob_feature_rows,
            "book_available_rows": clob_book_available_rows,
            "book_available_rate": pct(clob_book_available_rows, clob_feature_rows),
            "price_history_available_rows": clob_price_history_available_rows,
            "price_history_available_rate": pct(clob_price_history_available_rows, clob_feature_rows),
            "ws_event_window_rows": clob_ws_event_window_rows,
            "ws_event_window_rate": pct(clob_ws_event_window_rows, clob_feature_rows),
        },
        "replay_input_status": {
            "status_counts": dict(sorted(replay_status_counts.items())),
        },
        "low_fill_fields": low_fill[:25],
        "has_market_token_ids": any(row.get("rows_with_market_token_ids", 0) > 0 for row in folder_rows),
        "by_market": market_rows,
        "folders": folder_rows,
    }


def daily_dates_from_csv(path):
    path = Path(path)
    if not path.exists():
        return set()
    dates = set()
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("local_date") or row.get("date")
            if not value:
                continue
            try:
                dates.add(date.fromisoformat(str(value)[:10]))
            except ValueError:
                continue
    return dates


def daily_value_rows_from_csv(path):
    path = Path(path)
    if not path.exists():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            value = row.get("local_date") or row.get("date")
            if not value:
                continue
            try:
                local_date = date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
            high = native_high(row)
            if high is None:
                high = safe_float(row.get("high"))
            bucket = native_bucket(row)
            if bucket is None:
                bucket = safe_float(row.get("bucket"))
            if high is not None:
                rows[local_date] = {
                    "high": high,
                    "bucket": int(bucket) if bucket is not None else None,
                }
    return rows


def source_daily_summary_path(source, spec):
    station = spec.icao.lower()
    if source == "wu":
        return data_path() / "wunderground" / station / "daily" / "daily_summary.csv"
    if source == "metar":
        return data_path() / "metar" / station / "daily" / "daily_summary.csv"
    if source == "ghcnh":
        return data_path() / "noaa_ghcnh" / station / "daily" / "daily_summary.csv"
    if source == "reanalysis":
        return data_path() / "reanalysis" / station / "daily" / "daily_summary.csv"
    raise KeyError(source)


def station_distance_km(spec, station):
    lat = safe_float((station or {}).get("LATITUDE") or (station or {}).get("latitude"))
    lon = safe_float((station or {}).get("LONGITUDE") or (station or {}).get("longitude"))
    if lat is None or lon is None:
        return None
    radius_km = 6371.0
    lat1 = math.radians(float(spec.lat))
    lat2 = math.radians(lat)
    dlat = lat2 - lat1
    dlon = math.radians(lon - float(spec.lon))
    hav = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return round(radius_km * 2.0 * math.asin(min(1.0, math.sqrt(hav))), 3)


def station_metadata(root):
    root = Path(root)
    station = read_json_dict(root / "station.json")
    if station:
        return station
    manifest = read_json_dict(root / "manifest.json")
    station = (manifest.get("metadata") or {}).get("station")
    return station if isinstance(station, dict) else {}


def supplemental_ghcnh_sources(spec, registry=None):
    return supplemental_sources(spec.id, source_type="noaa_ghcnh", registry=registry)


def source_root_path(source, spec):
    station = spec.icao.lower()
    if source == "wu":
        return data_path() / "wunderground" / station
    if source == "metar":
        return data_path() / "metar" / station
    if source == "ghcnh":
        return data_path() / "noaa_ghcnh" / station
    if source == "reanalysis":
        return data_path() / "reanalysis" / station
    raise KeyError(source)


def manifest_quality(source, spec):
    manifest = read_json_dict(source_root_path(source, spec) / "manifest.json")
    if not manifest:
        return {
            "manifest_exists": False,
            "quarantined_raw_observations": 0,
        }
    return {
        "manifest_exists": True,
        "quarantined_raw_observations": int(manifest.get("quarantined_raw_observations") or 0),
    }


def coverage_for_dates(covered, expected):
    expected_set = set(expected)
    covered_expected = covered & expected_set
    missing = sorted(expected_set - covered)
    return {
        "expected_days": len(expected_set),
        "covered_days": len(covered_expected),
        "missing_days": len(missing),
        "coverage_rate": pct(len(covered_expected), len(expected_set)),
        "first_covered": min(covered).isoformat() if covered else None,
        "last_covered": max(covered).isoformat() if covered else None,
        "sample_missing": [item.isoformat() for item in missing[:10]],
    }


def compare_high_rows(candidate, reference, expected_dates=None):
    expected_set = set(expected_dates or [])
    overlap = sorted(set(candidate) & set(reference) & (expected_set or set(candidate) | set(reference)))
    high_pairs = [
        (candidate[local_date].get("high"), reference[local_date].get("high"))
        for local_date in overlap
    ]
    diffs = [
        float(candidate_high) - float(reference_high)
        for candidate_high, reference_high in high_pairs
        if candidate_high is not None and reference_high is not None
    ]
    if not diffs:
        return {"days": 0}
    bucket_matches = []
    for local_date in overlap:
        candidate_row = candidate[local_date]
        reference_row = reference[local_date]
        candidate_bucket = candidate_row.get("bucket")
        reference_bucket = reference_row.get("bucket")
        if candidate_bucket is None and candidate_row.get("high") is not None:
            candidate_bucket = round(candidate_row.get("high"))
        if reference_bucket is None and reference_row.get("high") is not None:
            reference_bucket = round(reference_row.get("high"))
        if candidate_bucket is not None and reference_bucket is not None:
            bucket_matches.append(candidate_bucket == reference_bucket)
    return {
        "days": len(diffs),
        "mean_bias": round(sum(diffs) / len(diffs), 4),
        "mae": round(sum(abs(diff) for diff in diffs) / len(diffs), 4),
        "max_abs": round(max(abs(diff) for diff in diffs), 4),
        "candidate_exceeds_rate": round(sum(1 for diff in diffs if diff > 0) / len(diffs), 4),
        "candidate_misses_rate": round(sum(1 for diff in diffs if diff < 0) / len(diffs), 4),
        "bucket_match_rate": (
            round(sum(1 for match in bucket_matches if match) / len(bucket_matches), 4)
            if bucket_matches else None
        ),
    }


def nearby_history_audit(
    spec,
    canonical_sources,
    expected_period,
    expected_season,
    registry=None,
    validation_report=None,
):
    canonical_ghcnh_dates = daily_dates_from_csv(source_daily_summary_path("ghcnh", spec))
    wu_highs = daily_value_rows_from_csv(source_daily_summary_path("wu", spec))
    metar_highs = daily_value_rows_from_csv(source_daily_summary_path("metar", spec))
    supplemental_sources = []
    supplemental_dates_union = set()
    eligible_supplemental_dates_union = set()
    for source in supplemental_ghcnh_sources(spec, registry=registry):
        guard_not_canonical_root(source, spec)
        root = source_root(source)
        path = root / "daily" / "daily_summary.csv"
        dates = daily_dates_from_csv(path)
        highs = daily_value_rows_from_csv(path)
        if not dates:
            continue
        station = station_metadata(root)
        added_period = sorted((dates - canonical_ghcnh_dates) & set(expected_period))
        added_season = sorted((dates - canonical_ghcnh_dates) & set(expected_season))
        supplemental_dates_union |= dates
        promotion_gate = promotion_gate_for_source(
            source,
            validation_report=validation_report,
            validation_path=DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
            intended_start=min(expected_period) if expected_period else None,
            intended_end=max(expected_period) if expected_period else None,
        )
        if promotion_gate.get("ok"):
            eligible_supplemental_dates_union |= dates
        supplemental_sources.append({
            "source": "ghcnh_supplemental",
            "source_type": source.get("source_type"),
            "source_id": source.get("source_id"),
            "source_role": source.get("source_role"),
            "canonical_market_id": source.get("canonical_market_id") or spec.id,
            "root": str(root),
            "path": str(path),
            "exists": path.exists(),
            "station": source.get("station_id") or station.get("GHCN_ID") or station.get("ID") or root.name,
            "station_name": source.get("station_name") or station.get("NAME") or station.get("Station_name"),
            "latitude": source.get("latitude") if source.get("latitude") is not None else station.get("LATITUDE"),
            "longitude": source.get("longitude") if source.get("longitude") is not None else station.get("LONGITUDE"),
            "elevation_m": source.get("elevation_m"),
            "distance_km": (
                source.get("distance_from_canonical_km")
                if source.get("distance_from_canonical_km") is not None
                else station_distance_km(spec, station)
            ),
            "validation_status": source.get("validation_status"),
            "promotion_state": promotion_gate.get("promotion_state"),
            "promotion_gate": promotion_gate,
            "eligible_for_training": promotion_gate.get("eligible_for_training"),
            "eligible_for_source_trust_features": promotion_gate.get("eligible_for_source_trust_features"),
            "adopted_date_windows": source.get("adopted_date_windows"),
            "reason_for_adoption": source.get("reason_for_adoption"),
            "daily_days": len(dates),
            "period": coverage_for_dates(dates, expected_period),
            "target_season": coverage_for_dates(dates, expected_season),
            "adds_period_days": len(added_period),
            "adds_target_season_days": len(added_season),
            "sample_added_target_season_days": [item.isoformat() for item in added_season[:10]],
            "bias_vs_wu": {
                "all": compare_high_rows(highs, wu_highs),
                "target_season": compare_high_rows(highs, wu_highs, expected_season),
            },
            "bias_vs_metar": {
                "all": compare_high_rows(highs, metar_highs),
                "target_season": compare_high_rows(highs, metar_highs, expected_season),
            },
        })
    composite_dates = canonical_ghcnh_dates | eligible_supplemental_dates_union
    composite = {
        "source": "ghcnh_canonical_plus_validated_supplemental",
        "period": coverage_for_dates(composite_dates, expected_period),
        "target_season": coverage_for_dates(composite_dates, expected_season),
        "canonical_target_season_days": (
            (canonical_sources.get("ghcnh") or {}).get("target_season") or {}
        ).get("covered_days"),
        "supplemental_target_season_added_days": len(
            (eligible_supplemental_dates_union - canonical_ghcnh_dates) & set(expected_season)
        ),
        "candidate_supplemental_target_season_added_days": len(
            (supplemental_dates_union - canonical_ghcnh_dates) & set(expected_season)
        ),
    }
    return {
        "supplemental_sources": supplemental_sources,
        "composite": composite,
        "usefulness": (
            "validated_supplemental_available"
            if eligible_supplemental_dates_union
            else "blocked_until_validated"
            if supplemental_sources
            else "not_evaluated"
        ),
    }


def historical_source_audit(spec, source, expected_period, expected_season):
    path = source_daily_summary_path(source, spec)
    covered = daily_dates_from_csv(path)
    row = {
        "source": source,
        "path": str(path),
        "exists": path.exists(),
        "daily_days": len(covered),
        "period": coverage_for_dates(covered, expected_period),
        "target_season": coverage_for_dates(covered, expected_season),
        "quality": manifest_quality(source, spec),
    }
    if source == "reanalysis":
        start = min(expected_period) if expected_period else None
        end = max(expected_period) if expected_period else None
        row["archive_coverage"] = ReanalysisStore(spec).coverage(start, end)
    return row


def historical_audit(start, end, registry=None, validation_report=None):
    expected_period = list(iter_dates(start, end))
    expected_season = season_dates(start, end)
    markets = []
    for spec in all_specs():
        sources = {
            source: historical_source_audit(spec, source, expected_period, expected_season)
            for source in ("wu", "metar", "ghcnh", "reanalysis")
        }
        nearby_history = nearby_history_audit(
            spec,
            sources,
            expected_period,
            expected_season,
            registry=registry,
            validation_report=validation_report,
        )
        markets.append({
            "market_id": spec.id,
            "city": spec.city_label,
            "station": spec.icao,
            "unit": spec.display_unit,
            "sources": sources,
            "nearby_history": nearby_history,
        })
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "period_expected_days": len(expected_period),
        "target_season_expected_days": len(expected_season),
        "target_season_window": "May 20 through June 30 each year",
        "markets": markets,
        "canonical_guardrails": canonical_guardrail_report(registry=registry),
    }


def source_inventory():
    return {
        "live_weather_sources": [
            {
                "source": "wu_history",
                "role": "settlement-source intraday high and rows",
                "utility": "highest; this is the source hierarchy anchor",
            },
            {
                "source": "wu_current",
                "role": "current Weather.com station reading and since-7am max",
                "utility": "high; useful live support but not a hard settlement source",
            },
            {
                "source": "metar",
                "role": "airport observation cross-check",
                "utility": "high for US markets and Toronto source redundancy",
            },
            {
                "source": "weather_forecast/open_meteo/nws_hourly/global_ensemble/eccc_citypage",
                "role": "forecast distribution, disagreement, and remaining-heat signal",
                "utility": "high, but issue-time fidelity and raw payload retention can improve",
            },
            {
                "source": "eccc_swob",
                "role": "Toronto official observation lead signal",
                "utility": "Toronto-only, useful as a soft lead source",
            },
        ],
        "market_sources": [
            {
                "source": "Polymarket Gamma event markets",
                "captured": "yes/no prices, bid/ask, last, volume, liquidity, status",
                "gap": "metadata only; CLOB recorder is the canonical depth stream",
            },
            {
                "source": "Polymarket CLOB book recorder",
                "captured": "token ids, condition ids, raw books, book levels, depth summaries, optional price history, WebSocket events",
                "gap": "must stay supervised because missing book-depth history cannot be reconstructed",
            },
        ],
        "derived_artifacts": [
            "snapshots_long/wide",
            "snapshots.jsonl",
            "replay_inputs.jsonl",
            "features_long/jsonl",
            "components_long/jsonl",
            "forecasts_long/jsonl",
            "settlement.json and settlement ledger",
            "source redundancy truth table",
        ],
    }


def latest_source_alternate_probe(backtest_root=DEFAULT_BACKTEST_ROOT):
    root = Path(backtest_root)
    probes = sorted(root.glob("source_alternate_probe_*.json"))
    bias_reports = sorted(root.glob("toronto_alt_ghcnh_*_bias_*.json"))
    toronto_bias = {}
    if bias_reports:
        bias_payload = read_json_dict(bias_reports[-1])
        comparisons = {}
        for item in bias_payload.get("comparisons") or []:
            comparisons[item.get("source")] = {
                "all": item.get("all") or {},
                "target_season": item.get("target_season") or {},
            }
        toronto_bias = {
            "path": str(bias_reports[-1]),
            "generated_at_utc": bias_payload.get("generated_at_utc"),
            "alternate_station": bias_payload.get("alternate_station"),
            "alternate_days": bias_payload.get("alternate_days"),
            "comparisons": comparisons,
        }
    if not probes:
        return {
            "exists": False,
            "path": None,
            "toronto_available_ghcnh_candidates": [],
            "us_available_wu_candidates": [],
            "toronto_alt_ghcnh_bias": toronto_bias,
        }
    path = probes[-1]
    payload = read_json_dict(path)
    toronto_candidates = []
    for item in payload.get("toronto_ghcnh_candidates") or []:
        available_years = [
            row.get("year")
            for row in item.get("probe_years") or []
            if row.get("available")
        ]
        if available_years:
            toronto_candidates.append({
                "station": item.get("station") or {},
                "available_years": available_years,
                "distance2": item.get("distance2"),
            })
    wu_candidates = []
    for market in payload.get("us_wu_candidates") or []:
        for item in market.get("candidates") or []:
            if item.get("available"):
                wu_candidates.append({
                    "market_id": market.get("market_id"),
                    "history_id": item.get("history_id"),
                    "observation_count": item.get("observation_count"),
                    "date": item.get("date"),
                    "distance2": item.get("distance2"),
                })
    return {
        "exists": True,
        "path": str(path),
        "generated_at_utc": payload.get("generated_at_utc"),
        "toronto_available_ghcnh_candidates": toronto_candidates,
        "us_available_wu_candidates": wu_candidates,
        "toronto_candidate_count": len(payload.get("toronto_ghcnh_candidates") or []),
        "us_market_count": len(payload.get("us_wu_candidates") or []),
        "toronto_alt_ghcnh_bias": toronto_bias,
    }


def gate(name, severity, ok, evidence, threshold=None, action=None):
    return {
        "name": name,
        "severity": severity,
        "status": "PASS" if ok else severity.upper(),
        "ok": bool(ok),
        "threshold": threshold,
        "evidence": evidence,
        "action": action,
    }


def artifact_gate(snapshot, name, expected_count=None, thresholds=None, severity="fail"):
    thresholds = thresholds or DEFAULT_AUDIT_THRESHOLDS
    scoped_counts = snapshot.get("artifact_training_ready_day_counts")
    scoped_expected = snapshot.get("training_ready_folder_count")
    if scoped_counts is not None and scoped_expected is not None:
        counts = scoped_counts
        default_expected = scoped_expected
        scope = "training-ready "
    else:
        counts = snapshot.get("artifact_day_counts", {})
        default_expected = snapshot.get("folder_count", 0)
        scope = ""
    expected = default_expected if expected_count is None else expected_count
    present = counts.get(name, 0)
    rate = pct(present, expected)
    required_rate = thresholds["required_artifact_rate"]
    return gate(
        f"snapshot_artifact_{name}",
        severity,
        rate is not None and rate >= required_rate,
        f"{present}/{expected} {scope}folders have {SNAPSHOT_OPTIONAL_ARTIFACTS.get(name, name)}.",
        threshold=f">= {required_rate:.1%}",
        action="Backfill or regenerate the missing snapshot artifact before using the folder for training.",
    )


def build_gates(snapshot, historical, thresholds=None):
    thresholds = {**DEFAULT_AUDIT_THRESHOLDS, **(thresholds or {})}
    gates = []
    low_fill = snapshot.get("low_fill_fields") or []
    below_fill = [
        row for row in low_fill
        if row.get("fill_rate") is not None
        and float(row.get("fill_rate")) < float(thresholds["min_snapshot_field_fill_rate"])
    ]
    gates.append(gate(
        "snapshot_low_fill_fields",
        "warn",
        not below_fill,
        f"{len(below_fill)} fields are below {thresholds['min_snapshot_field_fill_rate']:.0%} fill.",
        threshold=f">= {thresholds['min_snapshot_field_fill_rate']:.1%}",
        action="Inspect low-fill fields and either backfill, replace with canonical artifacts, or remove them from model inputs.",
    ))

    for name in REQUIRED_SNAPSHOT_ARTIFACTS:
        gates.append(artifact_gate(snapshot, name, thresholds=thresholds, severity="fail"))
    for name in WARN_SNAPSHOT_ARTIFACTS:
        gates.append(artifact_gate(snapshot, name, thresholds=thresholds, severity="warn"))

    forecast_days = snapshot.get("artifact_day_counts", {}).get("forecasts", 0)
    if forecast_days:
        forecast_payload_days = snapshot.get("artifact_day_counts", {}).get(FORECAST_PAYLOAD_ARTIFACT, 0)
        rate = pct(forecast_payload_days, forecast_days)
        required_rate = thresholds["forecast_payload_artifact_rate"]
        gates.append(gate(
            "forecast_payload_artifact_rate",
            "warn",
            rate is not None and rate >= required_rate,
            f"{forecast_payload_days}/{forecast_days} forecast folders have raw payload manifests.",
            threshold=f">= {required_rate:.1%}",
            action="Regenerate forecast payload manifests or rerun captures with raw payload persistence enabled.",
        ))

    source_status = snapshot.get("source_status") or {}
    stale_rate = source_status.get("stale_or_failed_rate")
    max_stale_rate = thresholds["max_source_stale_or_failed_rate"]
    gates.append(gate(
        "source_status_stale_or_failed_rate",
        "warn",
        stale_rate is not None and float(stale_rate) <= float(max_stale_rate),
        (
            f"{source_status.get('stale_or_failed_rows', 0)}/"
            f"{source_status.get('row_count', 0)} source-status rows are stale or failed."
        ),
        threshold=f"<= {max_stale_rate:.1%}",
        action="Use source-status rows to isolate persistent stale sources before training on the affected captures.",
    ))

    reanalysis_raw_only_normalizable = 0
    reanalysis_raw_only_source_lag = 0
    for market in historical.get("markets") or []:
        item = ((market.get("sources") or {}).get("reanalysis") or {}).get("archive_coverage") or {}
        reanalysis_raw_only_normalizable += int(
            item.get("raw_only_normalizable_day_count", item.get("raw_only_day_count") or 0) or 0
        )
        reanalysis_raw_only_source_lag += int(item.get("raw_only_source_lag_day_count") or 0)
    gates.append(gate(
        "reanalysis_raw_only_days",
        "warn",
        reanalysis_raw_only_normalizable <= int(thresholds["max_reanalysis_raw_only_days"]),
        (
            f"{reanalysis_raw_only_normalizable} normalizable reanalysis days have raw payloads "
            f"but no normalized daily row; {reanalysis_raw_only_source_lag} raw-only days "
            "are all-null source-lag payloads."
        ),
        threshold=f"<= {thresholds['max_reanalysis_raw_only_days']}",
        action="Rebuild normalized reanalysis outputs when normalizable raw-only days appear.",
    ))

    quarantined = 0
    for market in historical.get("markets") or []:
        for source_row in (market.get("sources") or {}).values():
            quality = source_row.get("quality") or {}
            quarantined += int(quality.get("quarantined_raw_observations") or 0)
    gates.append(gate(
        "quarantined_impossible_observations",
        "warn",
        quarantined <= int(thresholds["max_quarantined_impossible_observations"]),
        f"{quarantined} raw observations are quarantined by source manifests.",
        threshold=f"<= {thresholds['max_quarantined_impossible_observations']}",
        action="Review quarantines and data-auditor output; do not train on impossible raw rows.",
    ))

    supplemental_rows = []
    for market in historical.get("markets") or []:
        nearby = market.get("nearby_history") or {}
        for source_row in nearby.get("supplemental_sources") or []:
            supplemental_rows.append((market, source_row))
    if supplemental_rows:
        blocked = [
            (market, source_row)
            for market, source_row in supplemental_rows
            if not ((source_row.get("promotion_gate") or {}).get("ok"))
        ]
        blocked_sample = ", ".join(
            f"{market.get('market_id')}:{source_row.get('source_id')}"
            for market, source_row in blocked[:6]
        )
        gates.append(gate(
            "supplemental_station_validation",
            "fail",
            not blocked,
            (
                f"{len(supplemental_rows) - len(blocked)}/{len(supplemental_rows)} "
                "registered supplemental nearby stations are validation-promoted"
                + (f"; blocked sample: {blocked_sample}." if blocked_sample else ".")
            ),
            threshold="promotion_state == validated_supplemental with a current artifact",
            action=(
                "Run supplemental_station_validation and keep blocked nearby sources out of "
                "training/source-trust features until their validation gates pass."
            ),
        ))

    canonical_guardrails = historical.get("canonical_guardrails") or {}
    canonical_violation_count = int((canonical_guardrails.get("summary") or {}).get("violation_count") or 0)
    gates.append(gate(
        "canonical_history_provenance",
        "fail",
        canonical_violation_count == 0,
        f"{canonical_violation_count} canonical history provenance/station violations detected.",
        threshold="0 violations",
        action=(
            "Keep supplemental station rows out of canonical daily summaries; rebuild canonical roots "
            "from the registered canonical station and use explicit composite views for blended coverage."
        ),
    ))
    return gates


def gate_summary(gates):
    status = "PASS"
    if any(row.get("status") == "FAIL" for row in gates):
        status = "FAIL"
    elif any(row.get("status") == "WARN" for row in gates):
        status = "WARN"
    return {
        "status": status,
        "fail_count": sum(1 for row in gates if row.get("status") == "FAIL"),
        "warn_count": sum(1 for row in gates if row.get("status") == "WARN"),
        "pass_count": sum(1 for row in gates if row.get("status") == "PASS"),
    }


def recommendation(priority, title, evidence, action, roadmap_item=None):
    return {
        "priority": priority,
        "title": title,
        "evidence": evidence,
        "action": action,
        "roadmap_item": roadmap_item,
    }


def build_recommendations(snapshot, historical, loop, clob_loop=None, historical_gap_investigation=None):
    recs = []
    historical_gap_investigation = historical_gap_investigation or {}
    clob_summary = snapshot.get("clob_features") or {}
    if not snapshot.get("has_market_token_ids"):
        recs.append(recommendation(
            "P0",
            "Persist CLOB token IDs and full order-book snapshots",
            "Snapshot tapes currently keep shallow Gamma price fields but no condition/token ids or order-book levels.",
            (
                "Add a market microstructure capture artifact per event: token ids, book timestamp/hash, "
                "top levels, cumulative depth, spread, midpoint, imbalance, executable price for fixed sizes, "
                "and last trade metadata. Use Gamma's clobTokenIds for discovery."
            ),
            "Item 38 / data layer",
        ))
    best_bid = next((row for row in snapshot.get("low_fill_fields") or [] if row.get("field") == "best_bid"), None)
    if best_bid and not clob_summary.get("row_count"):
        recs.append(recommendation(
            "P0",
            "Stop relying on Gamma best bid as the bid-side market signal",
            f"best_bid fill rate is {best_bid['fill_rate']:.1%} across snapshot rows.",
            "Use CLOB /books or the market WebSocket as the canonical bid/ask/depth source; keep Gamma as metadata.",
            "Item 38",
        ))
    clob_loop = clob_loop or {}
    clob_state = clob_loop.get("state")
    clob_managed = clob_state in ("RUNNING", "PAUSED", "DEGRADED", "ERRORING")
    interval = safe_float(loop.get("configured_interval_minutes"))
    if (interval is None or interval >= 10) and not clob_managed:
        recs.append(recommendation(
            "P0",
            "Split weather/model cadence from market-book cadence",
            f"The managed loop interval is {loop.get('configured_interval_minutes')} minutes.",
            (
                "Keep full weather/model snapshots at 5-10 minutes, but capture Polymarket books every "
                "30-60 seconds or subscribe to the public market WebSocket. Near close or when edge changes, "
                "increase market-book capture to 10-15 seconds without refetching every weather source."
            ),
            "Item 37 / Item 38",
        ))
    if clob_loop and not clob_managed:
        recs.append(recommendation(
            "P0",
            "Start and supervise the CLOB book loop",
            f"CLOB loop state is {clob_state}; status path is {clob_loop.get('status_path')}.",
            (
                "Run `weather.market.market_microstructure start-detached` and register "
                "`scripts/register_clob_supervisor.ps1` so book-depth history is "
                "captured continuously and restarted after crashes or reboots."
            ),
            "Item 37 / Item 38",
        ))
    elif clob_state in ("DEGRADED", "ERRORING"):
        recs.append(recommendation(
            "P1",
            "Investigate CLOB loop degraded markets",
            f"CLOB loop state is {clob_state}; error markets: {', '.join(clob_loop.get('error_markets') or [])}.",
            "Check `data/snapshots/clob_diagnostics.jsonl` and Polymarket event availability for the failing markets.",
            "Item 37",
        ))

    low_sources = []
    for market in historical.get("markets") or []:
        nearby = market.get("nearby_history") or {}
        composite_season = ((nearby.get("composite") or {}).get("target_season") or {})
        for source, source_row in (market.get("sources") or {}).items():
            season = source_row.get("target_season") or {}
            if season.get("coverage_rate") is not None and season["coverage_rate"] < 0.95:
                if (
                    source == "ghcnh"
                    and composite_season.get("coverage_rate") is not None
                    and composite_season["coverage_rate"] >= 0.95
                ):
                    continue
                low_sources.append((market["market_id"], source, season["covered_days"], season["expected_days"]))
    if low_sources:
        sample = ", ".join(f"{m}:{s} {c}/{e}" for m, s, c, e in low_sources[:8])
        recs.append(recommendation(
            "P1",
            "Deep-fill redundant historical weather sources for the target season",
            f"Target-season coverage below 95% for {len(low_sources)} market/source pairs; sample: {sample}.",
            (
                "Backfill METAR/ASOS, GHCNh, and reanalysis for at least May 20-June 30 across all markets "
                "from 1995 forward, then widen to April-September. Keep WU as settlement primary."
            ),
            "Items 5, 29, 30, 33",
        ))

    replay_days = snapshot.get("artifact_day_counts", {}).get("replay_inputs", 0)
    if replay_days < snapshot.get("folder_count", 0):
        recs.append(recommendation(
            "P1",
            "Reconstruct or mark legacy days without replay inputs",
            f"{replay_days}/{snapshot.get('folder_count', 0)} snapshot folders have replay_inputs.jsonl.",
            "For old useful tapes, run a deterministic replay-input backfill where possible; otherwise label them evaluation-only.",
            "Item 36",
        ))

    forecast_days = snapshot.get("artifact_day_counts", {}).get("forecasts", 0)
    forecast_payload_days = snapshot.get("artifact_day_counts", {}).get("forecast_payloads", 0)
    if forecast_days and forecast_payload_days < forecast_days:
        recs.append(recommendation(
            "P1",
            "Archive forecast raw payloads and issue-time metadata",
            f"{forecast_payload_days}/{forecast_days} forecast folders have forecast_payloads_long.csv.",
            (
                "Persist raw forecast payload hashes/files for each source and capture provider issue/update time when available. "
                "This lets future models distinguish source update lag from true forecast changes."
            ),
            "Items 3, 22, 30",
        ))
    source_status_days = snapshot.get("artifact_day_counts", {}).get("source_status", 0)
    if source_status_days < snapshot.get("folder_count", 0):
        recs.append(recommendation(
            "P2",
            "Add source-status and latency rows per capture",
            f"{source_status_days}/{snapshot.get('folder_count', 0)} snapshot folders have source_status_long.csv.",
            (
                "Write source_status_long.csv with source id, ok/stale/error, fetched_at, age, latency, payload hash, "
                "and row counts. This makes stale-source behavior trainable and alertable."
            ),
            "Item 17 / Item 37",
        ))
    useful_nearby = []
    for market in historical.get("markets") or []:
        nearby = market.get("nearby_history") or {}
        composite = nearby.get("composite") or {}
        season = composite.get("target_season") or {}
        added = int(composite.get("supplemental_target_season_added_days") or 0)
        if added and season.get("coverage_rate") is not None and season["coverage_rate"] >= 0.95:
            useful_nearby.append((
                market.get("market_id"),
                added,
                season.get("covered_days"),
                season.get("expected_days"),
            ))
    if useful_nearby:
        sample = ", ".join(
            f"{market} +{added} days -> {covered}/{expected}"
            for market, added, covered, expected in useful_nearby[:6]
        )
        recs.append(recommendation(
            "P1",
            "Promote validated nearby station history as supplemental data",
            f"Nearby GHCNh sources lift canonical target-season coverage for {len(useful_nearby)} market(s); sample: {sample}.",
            (
                "Keep supplemental station roots provenance-labelled and train them as redundant history/source-trust features, "
                "not as silent replacements for canonical settlement stations."
            ),
            "Items 27, 29, 30",
        ))
    nearby_station_ids = {
        item.get("station")
        for market in historical.get("markets") or []
        for item in ((market.get("nearby_history") or {}).get("supplemental_sources") or [])
        if item.get("station")
    }
    toronto_candidates = historical_gap_investigation.get("toronto_available_ghcnh_candidates") or []
    if toronto_candidates:
        station = (toronto_candidates[0].get("station") or {}).get("GHCN_ID")
        years = ",".join(str(year) for year in toronto_candidates[0].get("available_years") or [])
        bias = historical_gap_investigation.get("toronto_alt_ghcnh_bias") or {}
        wu_target = (((bias.get("comparisons") or {}).get("wu") or {}).get("target_season") or {})
        if station in nearby_station_ids:
            pass
        elif bias and wu_target.get("days"):
            recs.append(recommendation(
                "P1",
                "Promote validated Toronto alternate GHCNh station as redundant history",
                (
                    f"{station} has {bias.get('alternate_days')} daily rows; target-season WU overlap "
                    f"{wu_target.get('days')} days, MAE {wu_target.get('mae_c')} C, "
                    f"bucket match {float(wu_target.get('bucket_match_rate')):.1%}."
                ),
                (
                    "Wire the alternate station in as a provenance-labelled redundant source for Toronto 2000-2012, "
                    "rather than overwriting the canonical station root."
                ),
                "Items 7, 29",
            ))
        else:
            recs.append(recommendation(
                "P1",
                "Backfill validated Toronto alternate GHCNh station",
                f"Alternate station {station} has available probe years {years}.",
                (
                    "Backfill the alternate station under a separate root, compare daily high bias against overlapping WU/SWOB/METAR, "
                    "then adopt it only as a provenance-labelled redundant source if the bias is acceptable."
                ),
                "Items 7, 29",
            ))
    us_wu_candidates = historical_gap_investigation.get("us_available_wu_candidates") or []
    us_wu_low = []
    for market in historical.get("markets") or []:
        if market.get("market_id") == "toronto":
            continue
        period = (((market.get("sources") or {}).get("wu") or {}).get("period") or {})
        rate = period.get("coverage_rate")
        if rate is not None and float(rate) < 0.95:
            us_wu_low.append(market)
    if us_wu_low and not us_wu_candidates and historical_gap_investigation.get("exists"):
        recs.append(recommendation(
            "P2",
            "Treat pre-2015 US Weather.com history as provider-unavailable",
            (
                f"{len(us_wu_low)} US markets have long-period WU coverage below 95%, and the latest alternate-ID probe "
                "found no available ICAO:9:US candidates."
            ),
            (
                "Keep WU as the settlement-style primary where available, but train older US years from METAR/GHCNh/reanalysis "
                "with explicit source provenance instead of retrying known-unavailable Weather.com IDs."
            ),
            "Items 6, 29",
        ))
    return recs


def build_audit(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    historical_start=None,
    historical_end=None,
    thresholds=None,
    supplemental_validation_path=DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
):
    historical_start = historical_start or date(1995, 5, 20)
    historical_end = historical_end or datetime.now(TORONTO_TZ).date()
    loop = loop_summary(interval_minutes=interval_minutes)
    clob_loop = clob_loop_summary(interval_seconds=60.0)
    snapshot = snapshot_audit(snapshots_root, interval_minutes=interval_minutes, tolerance=tolerance)
    supplemental_validation = load_validation_report(supplemental_validation_path)
    historical = historical_audit(
        historical_start,
        historical_end,
        validation_report=supplemental_validation,
    )
    historical_gap_investigation = latest_source_alternate_probe(backtest_root)
    gates = build_gates(snapshot, historical, thresholds=thresholds)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_inventory": source_inventory(),
        "loop": loop,
        "clob_loop": clob_loop,
        "snapshots": snapshot,
        "historical": historical,
        "historical_gap_investigation": historical_gap_investigation,
        "supplemental_station_validation": supplemental_validation or {
            "schema_version": None,
            "artifact_path": str(supplemental_validation_path) if supplemental_validation_path else None,
            "loaded": False,
        },
        "gates": gates,
        "gate_summary": gate_summary(gates),
        "gate_thresholds": {**DEFAULT_AUDIT_THRESHOLDS, **(thresholds or {})},
        "microstructure_reference": MICROSTRUCTURE_DOCS,
    }
    payload["recommendations"] = build_recommendations(
        snapshot,
        historical,
        loop,
        clob_loop,
        historical_gap_investigation=historical_gap_investigation,
    )
    return payload


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path



try:
    from .data_layer_audit_report import write_report  # noqa: E402
except ImportError:  # pragma: no cover - direct src compatibility
    from data_layer_audit_report import write_report  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Audit capture cadence, data usefulness, and historical coverage.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--interval-minutes", type=float, default=10.0)
    parser.add_argument("--tolerance", type=float, default=1.5)
    parser.add_argument("--historical-start", default="1995-05-20")
    parser.add_argument("--historical-end", default="")
    parser.add_argument(
        "--supplemental-validation",
        default=str(DEFAULT_SUPPLEMENTAL_VALIDATION_OUT),
        help="Supplemental nearby station validation JSON artifact.",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--strict", action="store_true", help="Exit 2 when any audit gate fails.")
    parser.add_argument("--fail-on-warn", action="store_true", help="Exit 2 when any audit gate warns or fails.")
    args = parser.parse_args(argv)

    payload = build_audit(
        snapshots_root=Path(args.snapshots_root),
        backtest_root=Path(args.backtest_root),
        interval_minutes=args.interval_minutes,
        tolerance=args.tolerance,
        historical_start=parse_date(args.historical_start),
        historical_end=parse_date(args.historical_end),
        supplemental_validation_path=Path(args.supplemental_validation) if args.supplemental_validation else None,
    )
    out_path = write_json(args.out, payload)
    report_path = write_report(args.report, payload)
    print(f"Wrote data layer audit JSON to {out_path}")
    print(f"Wrote data layer audit report to {report_path}")
    rec_counts = Counter(item.get("priority") for item in payload.get("recommendations") or [])
    print("Recommendations: " + ", ".join(f"{key}={value}" for key, value in sorted(rec_counts.items())))
    gate_status = (payload.get("gate_summary") or {}).get("status")
    print(f"Gate status: {gate_status}")
    if args.fail_on_warn and gate_status in {"WARN", "FAIL"}:
        return 2
    if args.strict and gate_status == "FAIL":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
