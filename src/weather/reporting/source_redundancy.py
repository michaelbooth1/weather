"""Fleet source redundancy, daily truth, and gap-fill planning.

Item 30 asks for no single weather feed to be a single point of failure. This
module keeps WU as the settlement-aligned primary, compares it against redundant
observation streams, learns source bias/lead versus WU, emits a provenance-safe
daily truth table, and produces targeted refetch/fill plans. It also summarizes
forecast-source ensemble/disagreement features from archived forecast tapes.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from weather.paths import data_path

from weather.backtesting.settlement_io import DEFAULT_SNAPSHOTS_ROOT
from weather.reporting.formatting import markdown_table
from weather.market.market_config import config_for_date, date_from_event_slug
from weather.market.market_registry import all_specs, spec_for_id, spec_for_slug
from weather.model.feature_store import row_forecast_high_native, row_temp_native
from weather.sources.daily_summary import native_bucket, native_high, row_count, row_unit
from weather.sources.supplemental_station_validation import (
    DEFAULT_OUT as DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
    load_validation_report,
    promotion_gate_for_source,
    validation_row_for_source,
)
from weather.sources.supplemental_stations import load_registry, source_root, supplemental_sources
from weather.sources.wu_history import parse_date


SCHEMA_VERSION = "source_redundancy_v0.3"
TRUTH_SCHEMA_VERSION = "daily_source_truth_v0.3"
FORECAST_ENSEMBLE_SCHEMA_VERSION = "forecast_ensemble_features_v0.1"

DEFAULT_JSON_OUT = data_path() / "backtest" / "source_redundancy.json"
DEFAULT_REPORT = data_path() / "backtest" / "source_redundancy_report.md"
DEFAULT_TRUTH_OUT = data_path() / "backtest" / "source_truth_daily.csv"
DEFAULT_FORECAST_OUT = data_path() / "backtest" / "forecast_ensemble_features.csv"

OBS_SOURCES = ("wu", "metar", "swob", "ghcnh", "reanalysis")
PRIMARY_SOURCE = "wu"
# Keep this model-facing order stable: pooled_feature_model imports it for
# static reliability priors and currently has trained columns for these sources.
FALLBACK_ORDER = ("metar", "ghcnh", "reanalysis")
TRUTH_FALLBACK_ORDER = ("metar", "swob", "ghcnh", "reanalysis")
SOURCE_ROOTS = {
    "wu": data_path() / "wunderground",
    "metar": data_path() / "metar",
    "swob": data_path() / "eccc_swob",
    "ghcnh": data_path() / "noaa_ghcnh",
    "reanalysis": data_path() / "reanalysis",
}
SOURCE_LABELS = {
    "wu": "Weather.com/WU primary",
    "metar": "METAR/ASOS station",
    "swob": "ECCC SWOB station",
    "ghcnh": "NOAA GHCNh station",
    "reanalysis": "Open-Meteo ERA5 reanalysis",
}
DISAGREEMENT_THRESHOLD = 1.5
SUPPLEMENTAL_SOURCE_PREFIX = "ghcnh_supplemental__"
SUPPLEMENTAL_FEATURE_FAMILY = "nearby_station_historical_only"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def iter_dates(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def split_date_runs(days):
    days = sorted({date.fromisoformat(day) if isinstance(day, str) else day for day in days})
    if not days:
        return []
    runs = []
    start = prev = days[0]
    for current in days[1:]:
        if current == prev + timedelta(days=1):
            prev = current
            continue
        runs.append((start, prev))
        start = prev = current
    runs.append((start, prev))
    return runs


def to_float(value):
    if value in (None, "", "None", "null", "NaN", "MSNG"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def round_half_up(value):
    value = to_float(value)
    if value is None:
        return None
    return int(math.floor(value + 0.5))


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def root_for_source(source, roots=None):
    roots = roots or {}
    return Path(roots.get(source) or SOURCE_ROOTS[source])


def daily_path_for_source(spec, source, roots=None):
    return root_for_source(source, roots) / spec.icao.lower() / "daily" / "daily_summary.csv"


def supplemental_source_key(source):
    return f"{SUPPLEMENTAL_SOURCE_PREFIX}{source.get('source_id')}"


def source_daily_path(path):
    return Path(path) / "daily" / "daily_summary.csv"


def obs_sources_for_spec(spec):
    declared = set(getattr(spec, "sources", ()) or ())
    return tuple(
        source for source in OBS_SOURCES
        if source != "swob" or "eccc_swob" in declared
    )


def earliest_minute(times_text):
    minutes = []
    for part in str(times_text or "").split("|"):
        if not part or ":" not in part:
            continue
        try:
            hour, minute = [int(item) for item in part[:5].split(":")]
        except ValueError:
            continue
        minutes.append(hour * 60 + minute)
    return min(minutes) if minutes else None


def read_daily_source(spec, source, roots=None):
    path = daily_path_for_source(spec, source, roots)
    return read_daily_path(spec, source, SOURCE_LABELS[source], path)


def read_daily_path(spec, source, source_label, path, metadata=None):
    metadata = metadata or {}
    rows = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            local_date = row.get("local_date")
            if not local_date:
                continue
            high = native_high(row)
            bucket = native_bucket(row)
            if high is None and bucket is None:
                continue
            rows[local_date] = {
                "source": source,
                "source_label": source_label,
                "path": str(path),
                "market_id": spec.id,
                "local_date": local_date,
                "unit": row_unit(row) or spec.display_unit,
                "high": high,
                "bucket": bucket if bucket is not None else round_half_up(high),
                "row_count": row_count(row),
                "first_time": row.get("first_time"),
                "last_time": row.get("last_time"),
                "max_times": row.get("max_temp_times"),
                "peak_minute": earliest_minute(row.get("max_temp_times")),
                **metadata,
            }
    return rows


def _wu_target_metrics(validation_row):
    return (((validation_row or {}).get("references") or {}).get("wu") or {}).get("metrics", {}).get("target_season") or {}


def read_supplemental_daily_sources(spec, registry=None, validation_report=None):
    if validation_report is None:
        validation_report = load_validation_report(DEFAULT_SUPPLEMENTAL_VALIDATION_OUT)
    rows = {}
    for source in supplemental_sources(spec.id, source_type="noaa_ghcnh", registry=registry):
        gate = promotion_gate_for_source(
            source,
            validation_report=validation_report,
            validation_path=DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
        )
        if not gate.get("ok"):
            continue
        validation_row = validation_row_for_source(validation_report, source.get("source_id"))
        wu_metrics = _wu_target_metrics(validation_row)
        key = supplemental_source_key(source)
        metadata = {
            "source_role": "supplemental",
            "supplemental_source_id": source.get("source_id"),
            "supplemental_station_id": source.get("station_id"),
            "supplemental_distance_km": source.get("distance_from_canonical_km"),
            "supplemental_validation_status": source.get("validation_status"),
            "supplemental_promotion_state": gate.get("promotion_state"),
            "supplemental_historical_bias_vs_wu": wu_metrics.get("mean_bias"),
            "supplemental_historical_mae_vs_wu": wu_metrics.get("mae"),
            "supplemental_historical_bucket_match_rate": wu_metrics.get("bucket_match_rate"),
            "historical_only_feature": True,
            "live_serving_eligible": False,
            "feature_family": SUPPLEMENTAL_FEATURE_FAMILY,
        }
        rows[key] = read_daily_path(
            spec,
            key,
            f"Validated nearby GHCNh station {source.get('station_id')}",
            source_daily_path(source_root(source)),
            metadata=metadata,
        )
    return rows


def source_daily_indexes(
    spec,
    roots=None,
    registry=None,
    validation_report=None,
    include_supplemental=True,
):
    indexes = {
        source: read_daily_source(spec, source, roots=roots)
        for source in obs_sources_for_spec(spec)
    }
    if include_supplemental:
        indexes.update(read_supplemental_daily_sources(
            spec,
            registry=registry,
            validation_report=validation_report,
        ))
    return indexes


def source_values_for_day(indexes, local_date):
    values = {}
    for source, rows in indexes.items():
        if local_date in rows:
            values[source] = rows[local_date]
    return values


def selected_truth(values):
    if PRIMARY_SOURCE in values:
        return values[PRIMARY_SOURCE], "primary"
    for source in TRUTH_FALLBACK_ORDER:
        if source in values:
            return values[source], "filled_from_redundant"
    return None, "missing_all_sources"


def source_spread(values):
    highs = [row.get("high") for row in values.values() if row.get("high") is not None]
    if len(highs) < 2:
        return None
    return max(highs) - min(highs)


def primary_disagreement(values):
    primary = values.get(PRIMARY_SOURCE)
    if not primary or primary.get("high") is None:
        return None
    diffs = [
        abs(row["high"] - primary["high"])
        for source, row in values.items()
        if source != PRIMARY_SOURCE and row.get("high") is not None
    ]
    return max(diffs) if diffs else None


def consensus_high(values):
    highs = [row.get("high") for row in values.values() if row.get("high") is not None]
    return statistics.median(highs) if highs else None


def supplemental_values(values):
    return {
        source: row for source, row in values.items()
        if source.startswith(SUPPLEMENTAL_SOURCE_PREFIX)
    }


def supplemental_feature_values(values):
    supplemental = supplemental_values(values)
    primary = values.get(PRIMARY_SOURCE)
    same_day_deltas = []
    same_day_bucket_matches = []
    source_ids = []
    distances = []
    validation_states = []
    bias_values = []
    mae_values = []
    bucket_rates = []
    for source, row in sorted(supplemental.items()):
        source_ids.append(row.get("supplemental_source_id") or source)
        if row.get("supplemental_distance_km") is not None:
            distances.append(to_float(row.get("supplemental_distance_km")))
        if row.get("supplemental_promotion_state"):
            validation_states.append(row.get("supplemental_promotion_state"))
        if row.get("supplemental_historical_bias_vs_wu") is not None:
            bias_values.append(to_float(row.get("supplemental_historical_bias_vs_wu")))
        if row.get("supplemental_historical_mae_vs_wu") is not None:
            mae_values.append(to_float(row.get("supplemental_historical_mae_vs_wu")))
        if row.get("supplemental_historical_bucket_match_rate") is not None:
            bucket_rates.append(to_float(row.get("supplemental_historical_bucket_match_rate")))
        if primary and primary.get("high") is not None and row.get("high") is not None:
            same_day_deltas.append(float(row["high"]) - float(primary["high"]))
        if primary and primary.get("bucket") is not None and row.get("bucket") is not None:
            same_day_bucket_matches.append(int(row["bucket"]) == int(primary["bucket"]))
    best_delta = None
    if same_day_deltas:
        best_delta = min(same_day_deltas, key=lambda value: abs(value))
    return {
        "supplemental_source_available": bool(supplemental),
        "supplemental_source_count": len(supplemental),
        "supplemental_source_ids": source_ids,
        "supplemental_distance_km": min(distances) if distances else None,
        "supplemental_validation_status": "|".join(sorted(set(validation_states))) if validation_states else "",
        "supplemental_historical_bias_vs_wu": mean(bias_values),
        "supplemental_historical_mae_vs_wu": mean(mae_values),
        "supplemental_historical_bucket_match_rate": mean(bucket_rates),
        "supplemental_same_day_delta_vs_primary": best_delta,
        "supplemental_same_day_bucket_match": (
            any(same_day_bucket_matches) if same_day_bucket_matches else None
        ),
        "supplemental_historical_only_feature": bool(supplemental),
        "supplemental_live_serving_eligible": False,
        "supplemental_feature_family": SUPPLEMENTAL_FEATURE_FAMILY if supplemental else "",
    }


def truth_row(spec, local_date, values, disagreement_threshold=DISAGREEMENT_THRESHOLD):
    selected, status = selected_truth(values)
    spread = source_spread(values)
    primary_diff = primary_disagreement(values)
    redundant_sources = [source for source in values if source != PRIMARY_SOURCE]
    selected_source = selected.get("source") if selected else None
    selected_high = selected.get("high") if selected else None
    selected_bucket = selected.get("bucket") if selected else None
    consensus = consensus_high(values)
    consensus_sources = [
        source for source, row in sorted(values.items())
        if row.get("high") is not None
    ]
    return {
        "schema_version": TRUTH_SCHEMA_VERSION,
        "market_id": spec.id,
        "city": spec.city_label,
        "local_date": local_date,
        "unit": spec.display_unit,
        "status": status,
        "selected_source": selected_source,
        "selected_high": selected_high,
        "selected_bucket": selected_bucket,
        "consensus_high": consensus,
        "consensus_bucket": round_half_up(consensus),
        "consensus_source_count": len(consensus_sources),
        "consensus_sources": consensus_sources,
        "primary_available": PRIMARY_SOURCE in values,
        "source_count": len(values),
        "redundant_source_count": len(redundant_sources),
        "redundant_sources": redundant_sources,
        "source_values": {
            source: {
                "high": row.get("high"),
                "bucket": row.get("bucket"),
                "row_count": row.get("row_count"),
                "peak_minute": row.get("peak_minute"),
                "source_role": row.get("source_role", "canonical"),
                "supplemental_source_id": row.get("supplemental_source_id"),
                "supplemental_distance_km": row.get("supplemental_distance_km"),
                "supplemental_promotion_state": row.get("supplemental_promotion_state"),
                "historical_only_feature": row.get("historical_only_feature", False),
                "live_serving_eligible": row.get("live_serving_eligible", True),
            }
            for source, row in sorted(values.items())
        },
        "source_spread": spread,
        "max_abs_diff_vs_primary": primary_diff,
        "disagreement_alert": (
            primary_diff is not None and primary_diff > float(disagreement_threshold)
        ),
        "fill_candidate": status == "filled_from_redundant",
        "missing_sources": [source for source in obs_sources_for_spec(spec) if source not in values],
        **supplemental_feature_values(values),
    }


def build_truth_rows(spec, start_date, end_date, roots=None,
                     disagreement_threshold=DISAGREEMENT_THRESHOLD,
                     registry=None,
                     validation_report=None,
                     include_supplemental=True):
    indexes = source_daily_indexes(
        spec,
        roots=roots,
        registry=registry,
        validation_report=validation_report,
        include_supplemental=include_supplemental,
    )
    rows = []
    for day in iter_dates(start_date, end_date):
        day_text = day.isoformat()
        values = source_values_for_day(indexes, day_text)
        rows.append(truth_row(spec, day_text, values, disagreement_threshold))
    return rows


def bias_stats_for_source(rows, source):
    diffs = []
    bucket_diffs = []
    lead_minutes = []
    for row in rows:
        values = row.get("source_values") or {}
        primary = values.get(PRIMARY_SOURCE)
        other = values.get(source)
        if not primary or not other:
            continue
        if primary.get("high") is None or other.get("high") is None:
            continue
        diff = other["high"] - primary["high"]
        diffs.append(diff)
        if primary.get("bucket") is not None and other.get("bucket") is not None:
            bucket_diffs.append(int(other["bucket"]) - int(primary["bucket"]))
        if primary.get("peak_minute") is not None and other.get("peak_minute") is not None:
            lead_minutes.append(int(other["peak_minute"]) - int(primary["peak_minute"]))
    if not diffs:
        return {
            "source": source,
            "n": 0,
            "bias_source_minus_wu": None,
            "mae_vs_wu": None,
            "rmse_vs_wu": None,
            "exact_bucket_match_rate": None,
            "source_exceeds_wu_rate": None,
            "source_misses_wu_rate": None,
            "mean_peak_time_lead_minutes": None,
        }
    return {
        "source": source,
        "n": len(diffs),
        "bias_source_minus_wu": mean(diffs),
        "mae_vs_wu": mean([abs(diff) for diff in diffs]),
        "rmse_vs_wu": math.sqrt(mean([diff * diff for diff in diffs])),
        "exact_bucket_match_rate": (
            sum(1 for diff in bucket_diffs if diff == 0) / len(bucket_diffs)
            if bucket_diffs else None
        ),
        "source_exceeds_wu_rate": sum(1 for diff in diffs if diff > 0) / len(diffs),
        "source_misses_wu_rate": sum(1 for diff in diffs if diff < 0) / len(diffs),
        "mean_peak_time_lead_minutes": mean(lead_minutes),
    }


def bias_stats(rows, sources=None):
    sources = [source for source in (sources or TRUTH_FALLBACK_ORDER) if source != PRIMARY_SOURCE]
    return {
        source: bias_stats_for_source(rows, source)
        for source in sources
    }


def command_for_source(source, market_id, start_date, end_date):
    start_text = start_date.isoformat()
    end_text = end_date.isoformat()
    if source == "wu":
        return (
            f".\\venv\\Scripts\\python.exe -m weather.sources.wu_history --market {market_id} "
            f"backfill --start {start_text} --end {end_text} "
            "--skip-existing --continue-on-error"
        )
    if source == "ghcnh":
        return (
            f".\\venv\\Scripts\\python.exe -m weather.sources.noaa_ghcnh_history --market {market_id} "
            f"backfill --start-year {start_date.year} --end-year {end_date.year} --skip-existing"
        )
    if source == "metar":
        return (
            f".\\venv\\Scripts\\python.exe -m weather.sources.metar_history --market {market_id} "
            f"backfill --start {start_text} --end {end_text} --skip-existing"
        )
    if source == "swob":
        return (
            f".\\venv\\Scripts\\python.exe -m weather.sources.eccc_swob_history run "
            f"--start {start_text} --end {end_text}"
        )
    if source == "reanalysis":
        return (
            f".\\venv\\Scripts\\python.exe -m weather.sources.reanalysis_history --market {market_id} "
            f"backfill --start {start_text} --end {end_text} --skip-existing"
        )
    raise ValueError(f"Unknown source {source}")


def gap_fill_plan(spec, rows):
    missing_by_source = defaultdict(list)
    fill_candidates = []
    disagreement_days = []
    for row in rows:
        day = row["local_date"]
        for source in row.get("missing_sources") or []:
            missing_by_source[source].append(day)
        if row.get("fill_candidate"):
            fill_candidates.append({
                "local_date": day,
                "selected_source": row.get("selected_source"),
                "selected_high": row.get("selected_high"),
                "selected_bucket": row.get("selected_bucket"),
                "available_sources": sorted((row.get("source_values") or {}).keys()),
                "note": "Primary WU missing; use only with provenance as redundant-source fill.",
            })
        if row.get("disagreement_alert"):
            disagreement_days.append({
                "local_date": day,
                "max_abs_diff_vs_primary": row.get("max_abs_diff_vs_primary"),
                "source_values": row.get("source_values"),
            })

    refetch_commands = []
    for source, days in sorted(missing_by_source.items()):
        for start, end in split_date_runs(days):
            refetch_commands.append({
                "source": source,
                "market_id": spec.id,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "command": command_for_source(source, spec.id, start, end),
            })
    return {
        "fill_candidates": fill_candidates,
        "disagreement_days": disagreement_days,
        "refetch_commands": refetch_commands,
    }


def market_summary(rows):
    return {
        "days": len(rows),
        "primary_days": sum(1 for row in rows if row.get("primary_available")),
        "redundant_days": sum(1 for row in rows if row.get("redundant_source_count", 0) >= 1),
        "two_plus_source_days": sum(1 for row in rows if row.get("source_count", 0) >= 2),
        "supplemental_source_days": sum(1 for row in rows if row.get("supplemental_source_available")),
        "supplemental_same_day_primary_overlap_days": sum(
            1 for row in rows
            if row.get("supplemental_same_day_delta_vs_primary") is not None
        ),
        "filled_days": sum(1 for row in rows if row.get("fill_candidate")),
        "missing_all_sources_days": sum(1 for row in rows if row.get("status") == "missing_all_sources"),
        "disagreement_alert_days": sum(1 for row in rows if row.get("disagreement_alert")),
        "median_source_spread": median([row.get("source_spread") for row in rows]),
        "max_source_spread": max(
            [row.get("source_spread") for row in rows if row.get("source_spread") is not None],
            default=None,
        ),
    }


def median(values):
    values = [value for value in values if value is not None]
    return statistics.median(values) if values else None


def forecast_value(row):
    high = row_forecast_high_native(row)
    if high is not None:
        return high
    return row_temp_native(row)


def forecast_rows_from_folder(folder):
    folder = Path(folder)
    path = folder / "forecasts_long.csv"
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))
    except csv.Error:
        return []


def forecast_ensemble_features(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, market_ids=None):
    ids = set(market_ids or [])
    grouped = {}
    for path in sorted(Path(snapshots_root).glob("*/forecasts_long.csv")):
        folder = path.parent
        spec = spec_for_slug(folder.name)
        if spec is None or (ids and spec.id not in ids):
            continue
        rows = forecast_rows_from_folder(folder)
        by_snapshot = defaultdict(lambda: defaultdict(list))
        snapshot_meta = {}
        for row in rows:
            snapshot_id = row.get("snapshot_id")
            source = row.get("source")
            value = forecast_value(row)
            if not snapshot_id or not source or value is None:
                continue
            by_snapshot[snapshot_id][source].append(value)
            snapshot_meta[snapshot_id] = {
                "snapshot_id": snapshot_id,
                "captured_at_local": row.get("captured_at_local"),
                "captured_at_utc": row.get("captured_at_utc"),
                "event_slug": row.get("event_slug") or folder.name,
                "target_date": row.get("target_date") or target_date_for_folder(folder),
                "market_id": spec.id,
                "unit": spec.display_unit,
            }
        for snapshot_id, source_values in by_snapshot.items():
            values = {
                source: max(items)
                for source, items in source_values.items()
                if items
            }
            highs = list(values.values())
            if not highs:
                continue
            grouped[(spec.id, folder.name, snapshot_id)] = {
                **snapshot_meta[snapshot_id],
                "schema_version": FORECAST_ENSEMBLE_SCHEMA_VERSION,
                "forecast_source_count": len(highs),
                "forecast_sources": sorted(values),
                "ensemble_forecast_high": statistics.median(highs),
                "mean_forecast_high": mean(highs),
                "forecast_disagreement": max(highs) - min(highs) if len(highs) >= 2 else 0.0,
                "source_values": values,
            }
    return list(grouped.values())


def target_date_for_folder(folder):
    target = date_from_event_slug(Path(folder).name)
    return target.isoformat() if target else ""


def forecast_summary(rows):
    by_market = defaultdict(list)
    sources = Counter()
    for row in rows:
        by_market[row["market_id"]].append(row)
        sources.update(row.get("forecast_sources") or [])
    market_rows = {}
    for market_id, items in sorted(by_market.items()):
        market_rows[market_id] = {
            "snapshot_count": len(items),
            "two_plus_source_snapshots": sum(1 for row in items if row["forecast_source_count"] >= 2),
            "avg_source_count": mean([row["forecast_source_count"] for row in items]),
            "avg_forecast_disagreement": mean([row["forecast_disagreement"] for row in items]),
            "max_forecast_disagreement": max([row["forecast_disagreement"] for row in items], default=None),
        }
    return {
        "schema_version": FORECAST_ENSEMBLE_SCHEMA_VERSION,
        "snapshot_count": len(rows),
        "two_plus_source_snapshots": sum(1 for row in rows if row["forecast_source_count"] >= 2),
        "sources": dict(sorted(sources.items())),
        "by_market": market_rows,
    }


def build_payload(
    market_ids=None,
    start_date=None,
    end_date=None,
    source_roots=None,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    disagreement_threshold=DISAGREEMENT_THRESHOLD,
    registry=None,
    supplemental_validation_report=None,
    supplemental_validation_path=DEFAULT_SUPPLEMENTAL_VALIDATION_OUT,
    include_supplemental=True,
):
    if start_date is None or end_date is None:
        target = config_for_date().target_date
        start_date = target - timedelta(days=7)
        end_date = target + timedelta(days=7)
    ids = set(market_ids or [])
    registry = registry if registry is not None else load_registry()
    supplemental_validation_report = (
        supplemental_validation_report
        if supplemental_validation_report is not None
        else load_validation_report(supplemental_validation_path)
    )
    markets = {}
    all_truth_rows = []
    for spec in all_specs():
        if ids and spec.id not in ids:
            continue
        rows = build_truth_rows(
            spec,
            start_date,
            end_date,
            roots=source_roots,
            disagreement_threshold=disagreement_threshold,
            registry=registry,
            validation_report=supplemental_validation_report,
            include_supplemental=include_supplemental,
        )
        all_truth_rows.extend(rows)
        markets[spec.id] = {
            "city": spec.city_label,
            "unit": spec.display_unit,
            "summary": market_summary(rows),
            "source_bias_vs_wu": bias_stats(rows, sources=obs_sources_for_spec(spec)),
            "supplemental_source_bias_vs_wu": bias_stats(
                rows,
                sources=sorted({
                    source
                    for row in rows
                    for source in (row.get("source_values") or {})
                    if source.startswith(SUPPLEMENTAL_SOURCE_PREFIX)
                }),
            ),
            "gap_fill": gap_fill_plan(spec, rows),
            "daily_truth": rows,
        }
    forecast_rows = forecast_ensemble_features(
        snapshots_root=snapshots_root,
        market_ids=market_ids,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "window": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "days": (end_date - start_date).days + 1,
        },
        "observation_sources": {
            source: {
                "label": SOURCE_LABELS[source],
                "role": "primary" if source == PRIMARY_SOURCE else "redundant",
            }
            for source in OBS_SOURCES
        },
        "markets": markets,
        "summary": fleet_summary(markets),
        "forecast_ensemble": forecast_summary(forecast_rows),
        "forecast_ensemble_rows": forecast_rows,
        "supplemental_nearby_features": supplemental_feature_summary(markets),
    }


def fleet_summary(markets):
    summaries = [market["summary"] for market in markets.values()]
    return {
        "market_count": len(markets),
        "days": sum(item["days"] for item in summaries),
        "primary_days": sum(item["primary_days"] for item in summaries),
        "two_plus_source_days": sum(item["two_plus_source_days"] for item in summaries),
        "supplemental_source_days": sum(item.get("supplemental_source_days", 0) for item in summaries),
        "supplemental_same_day_primary_overlap_days": sum(
            item.get("supplemental_same_day_primary_overlap_days", 0) for item in summaries
        ),
        "filled_days": sum(item["filled_days"] for item in summaries),
        "missing_all_sources_days": sum(item["missing_all_sources_days"] for item in summaries),
        "disagreement_alert_days": sum(item["disagreement_alert_days"] for item in summaries),
    }


def supplemental_feature_summary(markets):
    feature_columns = [
        "supplemental_source_available",
        "supplemental_source_count",
        "supplemental_source_ids",
        "supplemental_distance_km",
        "supplemental_validation_status",
        "supplemental_historical_bias_vs_wu",
        "supplemental_historical_mae_vs_wu",
        "supplemental_historical_bucket_match_rate",
        "supplemental_same_day_delta_vs_primary",
        "supplemental_same_day_bucket_match",
    ]
    rows = []
    for market_id, market in sorted((markets or {}).items()):
        daily_rows = market.get("daily_truth") or []
        supplemental_rows = [row for row in daily_rows if row.get("supplemental_source_available")]
        overlap_rows = [
            row for row in supplemental_rows
            if row.get("supplemental_same_day_delta_vs_primary") is not None
        ]
        deltas = [row.get("supplemental_same_day_delta_vs_primary") for row in overlap_rows]
        bucket_matches = [
            row.get("supplemental_same_day_bucket_match")
            for row in overlap_rows
            if row.get("supplemental_same_day_bucket_match") is not None
        ]
        source_ids = sorted({
            source_id
            for row in supplemental_rows
            for source_id in (row.get("supplemental_source_ids") or [])
        })
        two_plus_with = sum(1 for row in daily_rows if row.get("source_count", 0) >= 2)
        two_plus_without = 0
        redundant_with = sum(1 for row in daily_rows if row.get("redundant_source_count", 0) >= 1)
        redundant_without = 0
        for row in daily_rows:
            values = row.get("source_values") or {}
            non_supplemental = [
                source for source in values
                if not source.startswith(SUPPLEMENTAL_SOURCE_PREFIX)
            ]
            if len(non_supplemental) >= 2:
                two_plus_without += 1
            if any(source != PRIMARY_SOURCE for source in non_supplemental):
                redundant_without += 1
        rows.append({
            "market_id": market_id,
            "feature_family": SUPPLEMENTAL_FEATURE_FAMILY,
            "historical_only": True,
            "live_serving_eligible": False,
            "source_ids": source_ids,
            "supplemental_source_days": len(supplemental_rows),
            "same_day_primary_overlap_days": len(overlap_rows),
            "two_plus_source_day_delta": two_plus_with - two_plus_without,
            "redundant_source_day_delta": redundant_with - redundant_without,
            "same_day_mae_vs_primary": mean([abs(value) for value in deltas]),
            "same_day_bucket_match_rate": (
                sum(1 for value in bucket_matches if value) / len(bucket_matches)
                if bucket_matches else None
            ),
            "feature_columns": feature_columns,
        })
    return {
        "feature_family": SUPPLEMENTAL_FEATURE_FAMILY,
        "historical_only": True,
        "live_serving_eligible": False,
        "train_serve_parity": {
            "status": "historical_only_excluded_from_live_serving",
            "training_columns": feature_columns,
            "serving_columns": [],
            "reason": (
                "Supplemental nearby rows are daily historical source-trust evidence; "
                "no live-compatible same-day source exists for serving yet."
            ),
        },
        "ablation": {
            "status": "diagnostic_ablation_ready",
            "effect_metrics": [
                "two_plus_source_day_delta",
                "redundant_source_day_delta",
                "same_day_mae_vs_primary",
                "same_day_bucket_match_rate",
            ],
            "settlement_scored_replay_status": "not_run_historical_only_excluded_from_live_serving",
            "decision": (
                "Do not claim Brier/log-loss lift until a training experiment opts into "
                "the historical-only columns and runs settlement-scored replay."
            ),
        },
        "markets": rows,
    }


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def truth_csv_rows(payload):
    for market in (payload.get("markets") or {}).values():
        for row in market.get("daily_truth") or []:
            out = dict(row)
            out["redundant_sources"] = "|".join(row.get("redundant_sources") or [])
            out["consensus_sources"] = "|".join(row.get("consensus_sources") or [])
            out["missing_sources"] = "|".join(row.get("missing_sources") or [])
            out["supplemental_source_ids"] = "|".join(row.get("supplemental_source_ids") or [])
            out["source_values"] = json.dumps(row.get("source_values") or {}, sort_keys=True)
            yield out


def write_csv(path, rows, fieldnames):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


TRUTH_COLUMNS = [
    "schema_version",
    "market_id",
    "city",
    "local_date",
    "unit",
    "status",
    "selected_source",
    "selected_high",
    "selected_bucket",
    "consensus_high",
    "consensus_bucket",
    "consensus_source_count",
    "consensus_sources",
    "primary_available",
    "source_count",
    "redundant_source_count",
    "redundant_sources",
    "source_spread",
    "max_abs_diff_vs_primary",
    "disagreement_alert",
    "fill_candidate",
    "missing_sources",
    "supplemental_source_available",
    "supplemental_source_count",
    "supplemental_source_ids",
    "supplemental_distance_km",
    "supplemental_validation_status",
    "supplemental_historical_bias_vs_wu",
    "supplemental_historical_mae_vs_wu",
    "supplemental_historical_bucket_match_rate",
    "supplemental_same_day_delta_vs_primary",
    "supplemental_same_day_bucket_match",
    "supplemental_historical_only_feature",
    "supplemental_live_serving_eligible",
    "supplemental_feature_family",
    "source_values",
]

FORECAST_COLUMNS = [
    "schema_version",
    "market_id",
    "event_slug",
    "target_date",
    "snapshot_id",
    "captured_at_local",
    "captured_at_utc",
    "unit",
    "forecast_source_count",
    "forecast_sources",
    "ensemble_forecast_high",
    "mean_forecast_high",
    "forecast_disagreement",
    "source_values",
]


def write_truth_csv(path, payload):
    return write_csv(path, list(truth_csv_rows(payload)), TRUTH_COLUMNS)


def forecast_csv_rows(payload):
    for row in payload.get("forecast_ensemble_rows") or []:
        out = dict(row)
        out["forecast_sources"] = "|".join(row.get("forecast_sources") or [])
        out["source_values"] = json.dumps(row.get("source_values") or {}, sort_keys=True)
        yield out


def write_forecast_csv(path, payload):
    return write_csv(path, list(forecast_csv_rows(payload)), FORECAST_COLUMNS)


def fmt_num(value, decimals=2, suffix=""):
    if value is None:
        return "-"
    return f"{float(value):.{decimals}f}{suffix}"


def fmt_int(value):
    return "-" if value is None else str(int(value))


def write_markdown(path, payload):
    summary = payload.get("summary") or {}
    rows = []
    bias_rows = []
    gap_rows = []
    for market_id, market in sorted((payload.get("markets") or {}).items()):
        s = market.get("summary") or {}
        rows.append([
            market_id,
            s.get("days"),
            s.get("primary_days"),
            s.get("two_plus_source_days"),
            s.get("supplemental_source_days"),
            s.get("filled_days"),
            s.get("missing_all_sources_days"),
            s.get("disagreement_alert_days"),
            fmt_num(s.get("median_source_spread")),
            fmt_num(s.get("max_source_spread")),
        ])
        for source, stats in (market.get("source_bias_vs_wu") or {}).items():
            bias_rows.append([
                market_id,
                source,
                stats.get("n"),
                fmt_num(stats.get("bias_source_minus_wu")),
                fmt_num(stats.get("mae_vs_wu")),
                fmt_num(stats.get("rmse_vs_wu")),
                fmt_num(stats.get("exact_bucket_match_rate"), suffix=""),
                fmt_num(stats.get("mean_peak_time_lead_minutes"), suffix=" min"),
            ])
        for source, stats in (market.get("supplemental_source_bias_vs_wu") or {}).items():
            bias_rows.append([
                market_id,
                source,
                stats.get("n"),
                fmt_num(stats.get("bias_source_minus_wu")),
                fmt_num(stats.get("mae_vs_wu")),
                fmt_num(stats.get("rmse_vs_wu")),
                fmt_num(stats.get("exact_bucket_match_rate"), suffix=""),
                fmt_num(stats.get("mean_peak_time_lead_minutes"), suffix=" min"),
            ])
        for command in (market.get("gap_fill") or {}).get("refetch_commands") or []:
            gap_rows.append([
                market_id,
                command.get("source"),
                command.get("start"),
                command.get("end"),
                command.get("command"),
            ])
    forecast = payload.get("forecast_ensemble") or {}
    supplemental_feature = payload.get("supplemental_nearby_features") or {}
    supplemental_rows = []
    for item in supplemental_feature.get("markets") or []:
        supplemental_rows.append([
            item.get("market_id"),
            "|".join(item.get("source_ids") or []) or "-",
            item.get("supplemental_source_days"),
            item.get("same_day_primary_overlap_days"),
            item.get("two_plus_source_day_delta"),
            item.get("redundant_source_day_delta"),
            fmt_num(item.get("same_day_mae_vs_primary")),
            fmt_num(item.get("same_day_bucket_match_rate")),
            item.get("historical_only"),
            item.get("live_serving_eligible"),
        ])
    forecast_rows = []
    for market_id, item in sorted((forecast.get("by_market") or {}).items()):
        forecast_rows.append([
            market_id,
            item.get("snapshot_count"),
            item.get("two_plus_source_snapshots"),
            fmt_num(item.get("avg_source_count")),
            fmt_num(item.get("avg_forecast_disagreement")),
            fmt_num(item.get("max_forecast_disagreement")),
        ])
    lines = [
        "# Source Redundancy And Gap-Filling Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Window: `{(payload.get('window') or {}).get('start')}` to `{(payload.get('window') or {}).get('end')}`",
        "",
        "## Fleet Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Markets", summary.get("market_count")],
            ["Market-days", summary.get("days")],
            ["WU primary days", summary.get("primary_days")],
            ["Two-plus-source days", summary.get("two_plus_source_days")],
            ["Supplemental nearby days", summary.get("supplemental_source_days")],
            ["Supplemental/WU overlap days", summary.get("supplemental_same_day_primary_overlap_days")],
            ["Redundant fill days", summary.get("filled_days")],
            ["Missing all sources", summary.get("missing_all_sources_days")],
            ["Disagreement alerts", summary.get("disagreement_alert_days")],
        ],
    )
    lines += ["", "## Observation Redundancy By Market", ""]
    lines += markdown_table(
        [
            "Market", "Days", "WU", "2+ Src", "Supp Days", "Fill",
            "Missing", "Disagree", "Median Spread", "Max Spread",
        ],
        rows,
    )
    lines += ["", "## Source Bias vs WU", ""]
    lines += markdown_table(
        ["Market", "Source", "N", "Bias", "MAE", "RMSE", "Bucket Match", "Peak Lead"],
        bias_rows,
    )
    lines += ["", "## Supplemental Nearby Feature Family", ""]
    lines += markdown_table(
        [
            "Market", "Source IDs", "Supp Days", "WU Overlap", "2+ Delta",
            "Redundant Delta", "Same-Day MAE", "Bucket Match", "Historical Only",
            "Live Eligible",
        ],
        supplemental_rows,
    )
    lines += ["", "## Forecast Ensemble Features", ""]
    lines += markdown_table(
        ["Market", "Snapshots", "2+ Src", "Avg Src", "Avg Disagree", "Max Disagree"],
        forecast_rows,
    )
    lines += ["", "## Targeted Refetch Commands", ""]
    lines += markdown_table(
        ["Market", "Source", "Start", "End", "Command"],
        gap_rows,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _market_ids(value):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _source_roots(args):
    roots = {}
    if args.wu_root:
        roots["wu"] = args.wu_root
    if args.metar_root:
        roots["metar"] = args.metar_root
    if args.ghcnh_root:
        roots["ghcnh"] = args.ghcnh_root
    if args.reanalysis_root:
        roots["reanalysis"] = args.reanalysis_root
    return roots


def cmd_report(args):
    market_ids = _market_ids(args.markets)
    for market_id in market_ids:
        spec_for_id(market_id)
    start = parse_date(args.start) if args.start else None
    end = parse_date(args.end) if args.end else None
    if (start is None) != (end is None):
        raise SystemExit("--start and --end must be supplied together")
    payload = build_payload(
        market_ids=market_ids,
        start_date=start,
        end_date=end,
        source_roots=_source_roots(args),
        snapshots_root=Path(args.snapshots_root),
        disagreement_threshold=args.disagreement_threshold,
        supplemental_validation_path=(
            Path(args.supplemental_validation) if args.supplemental_validation else None
        ),
        include_supplemental=not args.skip_supplemental,
    )
    json_path = write_json(args.out, payload)
    report_path = write_markdown(args.report, payload)
    truth_path = write_truth_csv(args.truth_out, payload)
    forecast_path = write_forecast_csv(args.forecast_out, payload)
    print(f"Source redundancy: {payload['summary']['market_count']} markets")
    print(f"Wrote JSON to {json_path}")
    print(f"Wrote report to {report_path}")
    print(f"Wrote daily truth CSV to {truth_path}")
    print(f"Wrote forecast ensemble CSV to {forecast_path}")
    if args.strict and (
        payload["summary"]["missing_all_sources_days"] > 0
        or payload["summary"]["filled_days"] > 0
        or payload["summary"]["disagreement_alert_days"] > 0
    ):
        sys.exit(2)


def build_parser():
    parser = argparse.ArgumentParser(description="Build fleet source redundancy and gap-fill reports.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--markets", default="", help="Comma-separated registered market ids.")
    report.add_argument("--start", default="", help="YYYY-MM-DD; default current target +/- 7 days.")
    report.add_argument("--end", default="", help="YYYY-MM-DD; default current target +/- 7 days.")
    report.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    report.add_argument("--wu-root", default="")
    report.add_argument("--metar-root", default="")
    report.add_argument("--ghcnh-root", default="")
    report.add_argument("--reanalysis-root", default="")
    report.add_argument(
        "--supplemental-validation",
        default=str(DEFAULT_SUPPLEMENTAL_VALIDATION_OUT),
        help="Supplemental nearby station validation JSON artifact.",
    )
    report.add_argument(
        "--skip-supplemental",
        action="store_true",
        help="Disable validated supplemental nearby-history feature rows.",
    )
    report.add_argument("--disagreement-threshold", type=float, default=DISAGREEMENT_THRESHOLD)
    report.add_argument("--strict", action="store_true", help="Exit 2 on missing/fill/disagreement days.")
    report.add_argument("--out", default=str(DEFAULT_JSON_OUT))
    report.add_argument("--report", default=str(DEFAULT_REPORT))
    report.add_argument("--truth-out", default=str(DEFAULT_TRUTH_OUT))
    report.add_argument("--forecast-out", default=str(DEFAULT_FORECAST_OUT))
    report.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
