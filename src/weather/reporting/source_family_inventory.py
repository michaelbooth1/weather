"""Weather-input family inventory and promotion preflight.

This report is deliberately artifact-first: it reads source-status rows, raw
payload manifests, feature vectors, CLOB feature/tape evidence, and optional
settlement-scored ablation output. It does not train or replay by itself.
"""
from __future__ import annotations

import argparse
import csv
import math
import pickle
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from weather.backtesting.settled_days import folder_market_id
from weather.io import read_csv_rows, read_json, write_json_atomic
from weather.market.market_microstructure_features import CLOB_MODEL_FEATURE_COLUMNS
from weather.market.market_registry import REGISTRY
from weather.model.feature_store import (
    ECCC_GRIDDED_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    FORECAST_FEATURE_COLUMNS,
    FORECAST_PROFILE_COLUMNS,
    MARINE_CONTEXT_FEATURE_COLUMNS,
    MRMS_PRECIP_FEATURE_COLUMNS,
    REANALYSIS_SYNOPTIC_FEATURE_COLUMNS,
    US_GUIDANCE_FEATURE_COLUMNS,
)
from weather.paths import config_path, data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version

try:
    from weather.calibration.pooled_feature_model import HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS
except Exception:  # noqa: BLE001 - inventory should still run if sklearn deps are unavailable
    HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS = [
        "source_supplemental_available",
        "source_supplemental_count",
        "source_supplemental_overlap_days",
        "source_supplemental_best_mae",
        "source_supplemental_best_bucket_match",
        "source_supplemental_min_distance_km",
    ]


SCHEMA_VERSION = schema_version("source_family_inventory")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_REANALYSIS_ROOT = data_path() / "reanalysis"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "source_family_inventory.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "source_family_inventory_report.md"
DEFAULT_ABLATION_JSON = DEFAULT_BACKTEST_ROOT / "source_family_ablation.json"
DEFAULT_CANDIDATE_REPLAY_JSON = DEFAULT_BACKTEST_ROOT / "pooled_candidate_replay_latest.json"
DEFAULT_LOCATIONS_CONFIG = config_path("locations.json")

BLANK_VALUES = {"", "na", "nan", "none", "null", "n/a"}
FORECAST_PAYLOAD_SOURCES = {
    "open_meteo",
    "weather_forecast",
    "eccc_citypage",
    "eccc_gem",
    "nws_hourly",
    "nws_grid",
    "open_meteo_multimodel",
    "global_ensemble",
}
REANALYSIS_THIN_MARGIN_DELTA = 0.003


@dataclass(frozen=True)
class SourceFamilySpec:
    family_id: str
    label: str
    source_keys: tuple[str, ...]
    feature_columns: tuple[str, ...]
    lineage_artifacts: tuple[str, ...]
    ablation_variants: tuple[str, ...]
    historical_archive_status: str
    live_only_policy: str
    owner: str
    model_influence: bool = True


def _core_observation_columns():
    return tuple(
        column
        for column in FEATURE_COLUMNS
        if column
        in {
            "high_so_far",
            "current_temp",
            "rise_from_7am",
            "warming_rate_2h",
            "hours_at_peak",
            "dewpoint_c",
            "humidity",
            "pressure",
            "pressure_trend_3h",
            "wind_speed_kmh",
            "wind_gust_kmh",
            "wind_shift_3h_degrees",
            "onshore_flow",
            "onshore_wind_speed_kmh",
            "lake_breeze_proxy",
            "minutes_since_cutoff",
            "live_reading_temp",
            "live_reading_minus_high",
        }
    )


def _nws_grid_columns():
    return tuple(column for column in US_GUIDANCE_FEATURE_COLUMNS if column.startswith("nws_grid"))


def _multi_model_columns():
    prefixes = ("open_meteo_",)
    return tuple(column for column in US_GUIDANCE_FEATURE_COLUMNS if column.startswith(prefixes))


FAMILY_SPECS = (
    SourceFamilySpec(
        "settlement_observation",
        "Settlement and current observations",
        ("wu_history", "wu_current", "metar", "eccc_swob"),
        _core_observation_columns(),
        ("source_status_long.csv", "features_long.csv"),
        ("wu_history", "wu_current", "metar", "eccc_swob"),
        "available_primary_settlement_archive",
        "training_and_serving",
        "settlement and source adapters",
    ),
    SourceFamilySpec(
        "forecast_baseline",
        "Baseline high-temperature forecasts",
        ("weather_forecast", "open_meteo", "eccc_citypage"),
        tuple(column for column in FORECAST_FEATURE_COLUMNS if column not in FORECAST_PROFILE_COLUMNS),
        ("source_status_long.csv", "forecast_payloads_long.csv", "features_long.csv"),
        ("forecast_baseline", "all_forecasts", "weather_forecast", "open_meteo", "eccc_citypage"),
        "partial_forecast_history_archive",
        "training_and_serving",
        "forecast archive",
    ),
    SourceFamilySpec(
        "open_meteo_expanded",
        "Open-Meteo expanded hourly environment",
        ("open_meteo",),
        tuple(FORECAST_PROFILE_COLUMNS),
        ("source_status_long.csv", "forecast_payloads_long.csv", "features_long.csv"),
        ("open_meteo_expanded", "open_meteo"),
        "partial_forecast_history_archive",
        "parity_required_before_promotion",
        "forecast archive",
    ),
    SourceFamilySpec(
        "nws_grid",
        "NWS hourly and gridpoint guidance",
        ("nws_hourly", "nws_grid"),
        _nws_grid_columns(),
        ("source_status_long.csv", "forecast_payloads_long.csv", "features_long.csv"),
        ("official_us_guidance", "nws_grid", "nws_hourly"),
        "live_only_until_grid_archive_backfill",
        "live_only_diagnostic_until_backfilled",
        "US official guidance",
    ),
    SourceFamilySpec(
        "multi_model_guidance",
        "Open-Meteo multi-model and ensemble guidance",
        ("open_meteo_multimodel", "global_ensemble"),
        _multi_model_columns(),
        ("source_status_long.csv", "forecast_payloads_long.csv", "features_long.csv"),
        ("multi_model_guidance", "open_meteo_multimodel", "global_ensemble"),
        "live_only_until_model_run_archive_backfill",
        "live_only_diagnostic_until_backfilled",
        "forecast archive",
    ),
    SourceFamilySpec(
        "mrms_precip",
        "MRMS precipitation context",
        ("mrms_precip",),
        tuple(MRMS_PRECIP_FEATURE_COLUMNS),
        ("source_status_long.csv", "features_long.csv"),
        ("precip_context", "mrms_precip"),
        "public_archive_available_requires_product_versioning",
        "parity_required_before_promotion",
        "precip source adapter",
    ),
    SourceFamilySpec(
        "marine_context",
        "Marine and lake-breeze context",
        ("marine_context",),
        tuple(MARINE_CONTEXT_FEATURE_COLUMNS),
        ("source_status_long.csv", "features_long.csv"),
        ("coastal_context", "marine_context"),
        "station_archive_partial",
        "parity_required_before_promotion",
        "marine context",
    ),
    SourceFamilySpec(
        "eccc_gridded",
        "ECCC GEM/HRDPS Toronto gridded guidance",
        ("eccc_gem",),
        tuple(ECCC_GRIDDED_FEATURE_COLUMNS),
        ("source_status_long.csv", "forecast_payloads_long.csv", "features_long.csv"),
        ("eccc_gem", "toronto_official", "open_meteo_family"),
        "live_only_until_toronto_grid_backfill",
        "live_only_diagnostic_until_backfilled",
        "Canadian official guidance",
    ),
    SourceFamilySpec(
        "reanalysis_synoptic",
        "Reanalysis and synoptic sidecar",
        (),
        tuple(REANALYSIS_SYNOPTIC_FEATURE_COLUMNS),
        ("reanalysis_synoptic_features.csv",),
        ("reanalysis_synoptic",),
        "historical_sidecar_available",
        "historical_sidecar_required",
        "reanalysis archive",
    ),
    SourceFamilySpec(
        "nearby_station_redundancy",
        "Nearby-station redundancy and source trust",
        (),
        tuple(HISTORICAL_ONLY_SOURCE_RELIABILITY_COLUMNS),
        ("features_long.csv", "daily_source_truth.json"),
        ("nearby_station_redundancy", "source_state"),
        "historical_only_source_overlap",
        "historical_only_not_live_serving",
        "source redundancy",
    ),
    SourceFamilySpec(
        "clob_microstructure",
        "CLOB market microstructure",
        (),
        tuple(CLOB_MODEL_FEATURE_COLUMNS),
        (
            "clob_features_long.csv",
            "order_books_summary.csv",
            "price_history.csv",
            "market_ws_events.csv",
        ),
        ("clob_microstructure", "clob_microstructure_overlay"),
        "replayable_tape_required",
        "serving_replayable_tape_required",
        "market microstructure",
    ),
)


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def is_blank(value) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in BLANK_VALUES


def truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ok", "fresh", "pass"}


def cutoff_hour(row):
    value = row.get("cutoff_hour") or row.get("hour")
    if not is_blank(value):
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            pass
    for key in ("captured_at_local", "captured_at_utc", "built_at", "timestamp"):
        text = str(row.get(key) or "")
        if "T" in text:
            text = text.split("T", 1)[1]
        elif " " in text:
            text = text.split(" ", 1)[1]
        if len(text) >= 2 and text[:2].isdigit():
            return text[:2]
    return "-"


def folder_market(folder, rows=None):
    market_id = folder_market_id(folder)
    if market_id:
        return market_id
    for row in rows or []:
        value = row.get("market_id") or row.get("market")
        if value:
            return str(value)
    return "-"


def iter_snapshot_folders(snapshots_root):
    root = Path(snapshots_root)
    if not root.exists():
        return []
    folders = set()
    for filename in (
        "snapshots_long.csv",
        "features_long.csv",
        "source_status_long.csv",
        "forecast_payloads_long.csv",
        "clob_features_long.csv",
    ):
        folders.update(path.parent for path in root.glob(f"*/{filename}"))
    return sorted(folders)


def family_matches_source(spec, row):
    source = str(row.get("source") or "")
    return bool(source and source in spec.source_keys)


def family_applicable_to_market(spec, market_id):
    if not spec.source_keys:
        return market_id in REGISTRY or market_id == "-"
    spec_obj = REGISTRY.get(market_id)
    if spec_obj is None:
        return False
    return any(source in spec_obj.sources for source in spec.source_keys)


def requires_forecast_payload(spec):
    return any(source in FORECAST_PAYLOAD_SOURCES for source in spec.source_keys)


def stats_template():
    return {
        "source_status_rows": 0,
        "source_status_ok_rows": 0,
        "source_status_sources": set(),
        "source_status_folders": set(),
        "missing_source_status_folders": set(),
        "forecast_payload_rows": 0,
        "forecast_payload_sources": set(),
        "forecast_payload_folders": set(),
        "missing_forecast_payload_folders": set(),
        "feature_rows": 0,
        "feature_total_cells": 0,
        "feature_missing_cells": 0,
        "feature_columns_present": set(),
        "feature_folders": set(),
        "by_market": defaultdict(lambda: {"rows": 0, "total_cells": 0, "missing_cells": 0}),
        "by_cutoff": defaultdict(lambda: {"rows": 0, "total_cells": 0, "missing_cells": 0}),
        "artifact_folders": set(),
        "clob_raw_tape_folders": set(),
        "sample_folders": set(),
    }


def update_feature_stats(stats, spec, row, market_id, *, columns=None):
    columns = columns if columns is not None else spec.feature_columns
    present = [column for column in columns if column in row]
    if not present:
        return
    stats["feature_rows"] += 1
    stats["feature_columns_present"].update(present)
    market = market_id or row.get("market_id") or "-"
    cutoff = cutoff_hour(row)
    total = len(present)
    missing = sum(1 for column in present if is_blank(row.get(column)))
    stats["feature_total_cells"] += total
    stats["feature_missing_cells"] += missing
    market_row = stats["by_market"][market]
    market_row["rows"] += 1
    market_row["total_cells"] += total
    market_row["missing_cells"] += missing
    cutoff_row = stats["by_cutoff"][cutoff]
    cutoff_row["rows"] += 1
    cutoff_row["total_cells"] += total
    cutoff_row["missing_cells"] += missing


def read_csv_stream(path):
    path = Path(path)
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return rows, list(reader.fieldnames or [])


def scan_source_status(folder, market_id, stats_by_family):
    path = folder / "source_status_long.csv"
    rows = read_csv_rows(path)
    for spec in FAMILY_SPECS:
        if not spec.source_keys or not family_applicable_to_market(spec, market_id):
            continue
        relevant = [row for row in rows if family_matches_source(spec, row)]
        stats = stats_by_family[spec.family_id]
        if not path.exists() or not relevant:
            stats["missing_source_status_folders"].add(str(folder))
            continue
        stats["source_status_folders"].add(str(folder))
        stats["sample_folders"].add(str(folder))
        for row in relevant:
            stats["source_status_rows"] += 1
            stats["source_status_sources"].add(str(row.get("source") or ""))
            if truthy(row.get("ok")) or str(row.get("status") or "").lower() in {"fresh", "ok", "available"}:
                stats["source_status_ok_rows"] += 1


def scan_forecast_payloads(folder, market_id, stats_by_family):
    path = folder / "forecast_payloads_long.csv"
    rows = read_csv_rows(path)
    for spec in FAMILY_SPECS:
        if not spec.source_keys or not requires_forecast_payload(spec) or not family_applicable_to_market(spec, market_id):
            continue
        relevant = [row for row in rows if family_matches_source(spec, row)]
        stats = stats_by_family[spec.family_id]
        if not path.exists() or not relevant:
            stats["missing_forecast_payload_folders"].add(str(folder))
            continue
        stats["forecast_payload_folders"].add(str(folder))
        stats["sample_folders"].add(str(folder))
        for row in relevant:
            stats["forecast_payload_rows"] += 1
            stats["forecast_payload_sources"].add(str(row.get("source") or ""))


def scan_features(folder, market_id, stats_by_family):
    path = folder / "features_long.csv"
    rows, fieldnames = read_csv_stream(path)
    if not rows:
        return
    field_set = set(fieldnames)
    for spec in FAMILY_SPECS:
        if spec.family_id in {"clob_microstructure", "reanalysis_synoptic"}:
            continue
        present = [column for column in spec.feature_columns if column in field_set]
        if not present:
            continue
        stats = stats_by_family[spec.family_id]
        stats["feature_folders"].add(str(folder))
        stats["sample_folders"].add(str(folder))
        for row in rows:
            update_feature_stats(stats, spec, row, market_id, columns=present)


def scan_reanalysis_sidecars(reanalysis_root, stats_by_family):
    stats = stats_by_family["reanalysis_synoptic"]
    spec = next(item for item in FAMILY_SPECS if item.family_id == "reanalysis_synoptic")
    root = Path(reanalysis_root)
    if not root.exists():
        return
    for market_spec in sorted(REGISTRY.values(), key=lambda item: item.id):
        path = root / market_spec.icao.lower() / "features" / "reanalysis_synoptic_features.csv"
        rows, fieldnames = read_csv_stream(path)
        if not rows:
            continue
        present = [column for column in spec.feature_columns if column in set(fieldnames)]
        if not present:
            continue
        stats["feature_folders"].add(str(path.parent))
        stats["artifact_folders"].add(str(path.parent))
        stats["sample_folders"].add(str(path.parent))
        for row in rows:
            row = dict(row)
            row["market_id"] = row.get("market_id") or market_spec.id
            update_feature_stats(stats, spec, row, market_spec.id, columns=present)


def clob_raw_tape_present(folder):
    names = {
        "order_books_summary.csv",
        "order_books_long.csv",
        "order_books_long.csv.gz",
        "order_books.jsonl",
        "price_history.csv",
        "price_history.jsonl",
        "market_ws_events.csv",
        "market_ws.jsonl",
    }
    return [name for name in names if (folder / name).exists()]


def scan_clob(folder, market_id, stats_by_family):
    stats = stats_by_family["clob_microstructure"]
    raw_tapes = clob_raw_tape_present(folder)
    if raw_tapes:
        stats["clob_raw_tape_folders"].add(str(folder))
        stats["artifact_folders"].add(str(folder))
        stats["sample_folders"].add(str(folder))
    path = folder / "clob_features_long.csv"
    rows, fieldnames = read_csv_stream(path)
    if not rows:
        return
    present = [column for column in CLOB_MODEL_FEATURE_COLUMNS if column in set(fieldnames)]
    if not present:
        return
    stats["feature_folders"].add(str(folder))
    stats["artifact_folders"].add(str(folder))
    stats["sample_folders"].add(str(folder))
    for row in rows:
        update_feature_stats(stats, next(spec for spec in FAMILY_SPECS if spec.family_id == "clob_microstructure"), row, market_id, columns=present)


def missing_rate(row):
    total = row.get("total_cells", 0)
    if not total:
        return None
    return row.get("missing_cells", 0) / total


def grouped_missingness(grouped):
    rows = []
    for group, values in sorted(grouped.items()):
        rows.append({
            "group": group,
            "rows": values["rows"],
            "missing_cells": values["missing_cells"],
            "total_cells": values["total_cells"],
            "missing_rate": missing_rate(values),
        })
    return rows


def candidate_replay_evidence_by_variant(payload):
    evidence = {}
    micro = (payload or {}).get("microstructure") or {}
    micro_aggregate = micro.get("aggregate") or {}
    if micro_aggregate.get("n"):
        delta_vs_candidate = micro_aggregate.get("delta_vs_candidate")
        delta = -float(delta_vs_candidate) if delta_vs_candidate is not None else None
        evidence["clob_microstructure"] = {
            "variant": "clob_microstructure",
            "evidence_source": "pooled_candidate_replay.microstructure",
            "n": micro_aggregate.get("n"),
            "days": None,
            "delta": delta,
            "base_brier": micro_aggregate.get("candidate_brier"),
            "variant_brier": micro_aggregate.get("micro_brier"),
            "delta_vs_candidate": delta_vs_candidate,
            "delta_vs_market": micro_aggregate.get("delta_vs_market"),
        }
    source_state = (payload or {}).get("source_state_ablation") or {}
    source_state_gate = source_state.get("gate") or {}
    source_state_aggregate = source_state_gate.get("aggregate") or {}
    if source_state_aggregate.get("n"):
        delta_vs_current = source_state_aggregate.get("delta_vs_current")
        delta = -float(delta_vs_current) if delta_vs_current is not None else None
        evidence["source_state"] = {
            "variant": "source_state",
            "evidence_source": "pooled_candidate_replay.source_state_ablation",
            "n": source_state_aggregate.get("n"),
            "days": None,
            "delta": delta,
            "base_brier": source_state_aggregate.get("current_brier"),
            "variant_brier": source_state_aggregate.get("candidate_brier"),
            "delta_vs_current": delta_vs_current,
            "delta_vs_market": source_state_aggregate.get("delta_vs_market"),
        }
    return evidence


def ablation_by_variant(payload, candidate_replay_payload=None):
    by_variant = {}
    for row in (payload or {}).get("variants") or (payload or {}).get("summaries") or []:
        variant = row.get("variant")
        if variant:
            by_variant[str(variant)] = row
    by_variant.update(candidate_replay_evidence_by_variant(candidate_replay_payload))
    return by_variant


def item27_feature_gate_paths():
    paths = {}
    for spec in REGISTRY.values():
        suffix = spec.artifact_suffix
        paths[spec.id] = spec.data_root / "analysis" / f"item27_feature_value_gate{suffix}.json"
    return paths


def item27_reanalysis_ablation_evidence(paths_by_market=None, required_markets=None):
    if paths_by_market is None:
        paths_by_market = item27_feature_gate_paths()
    required = sorted(required_markets or paths_by_market)
    rows = []
    for market_id in required:
        if market_id not in paths_by_market:
            return None
        path = Path(paths_by_market[market_id])
        payload = read_json(path, default={}) or {}
        decision = next(
            (
                row for row in payload.get("promotion_decisions") or []
                if row.get("family") == "reanalysis_synoptic"
            ),
            None,
        )
        if not decision or not decision.get("n"):
            return None
        rows.append((market_id, path, decision))

    market_details = []
    for market_id, path, decision in rows:
        delta_brier = decision.get("delta_brier")
        gate = str(decision.get("decision") or "").strip().lower()
        if not gate:
            gate = "promote" if delta_brier is not None and float(delta_brier) > 0 else "block"
        market_details.append({
            "market_id": market_id,
            "path": str(path),
            "rows": int(decision.get("n") or 0),
            "full_brier": decision.get("full_brier"),
            "ablated_brier": decision.get("ablated_brier"),
            "delta_brier": delta_brier,
            "delta_logloss": decision.get("delta_logloss"),
            "decision": gate,
        })

    total_n = sum(row["rows"] for row in market_details)
    if total_n <= 0:
        return None

    def weighted(key):
        values = []
        for _, _, decision in rows:
            value = decision.get(key)
            n = int(decision.get("n") or 0)
            if value is None or n <= 0:
                continue
            values.append((float(value), n))
        if not values:
            return None
        return sum(value * n for value, n in values) / sum(n for _, n in values)

    full_brier = weighted("full_brier")
    ablated_brier = weighted("ablated_brier")
    delta = (
        ablated_brier - full_brier
        if ablated_brier is not None and full_brier is not None
        else weighted("delta_brier")
    )
    return {
        "variant": "reanalysis_synoptic",
        "evidence_source": "item27_feature_value_gate",
        "n": total_n,
        "days": len(rows),
        "delta": delta,
        "base_brier": full_brier,
        "variant_brier": ablated_brier,
        "days_source_helped": sum(
            1 for _, _, decision in rows
            if decision.get("delta_brier") is not None and float(decision["delta_brier"]) > 0.0001
        ),
        "days_source_hurt": sum(
            1 for _, _, decision in rows
            if decision.get("delta_brier") is not None and float(decision["delta_brier"]) < -0.0001
        ),
        "markets_scored": [market_id for market_id, _, _ in rows],
        "market_gate_paths": [str(path) for _, path, _ in rows],
        "market_details": market_details,
        "positive_markets": [
            row["market_id"]
            for row in market_details
            if row.get("delta_brier") is not None and float(row["delta_brier"]) > 0
        ],
        "blocked_markets": [
            row["market_id"]
            for row in market_details
            if row.get("delta_brier") is None or float(row["delta_brier"]) <= 0
        ],
    }


def ablation_for_spec(spec, ablations):
    for variant in spec.ablation_variants:
        row = ablations.get(variant)
        if row:
            return {
                "status": "PRESENT",
                "variant": variant,
                "settlement_scored": True,
                "rows": row.get("n") or row.get("rows"),
                "days": row.get("days"),
                "delta": row.get("delta"),
                "base_brier": row.get("base_brier"),
                "variant_brier": row.get("variant_brier"),
                "days_source_helped": row.get("days_source_helped"),
                "days_source_hurt": row.get("days_source_hurt"),
                "evidence_source": row.get("evidence_source"),
                "markets_scored": row.get("markets_scored"),
                "market_gate_paths": row.get("market_gate_paths"),
                "market_details": row.get("market_details"),
                "positive_markets": row.get("positive_markets"),
                "blocked_markets": row.get("blocked_markets"),
            }
    return {
        "status": "MISSING",
        "variant": next(iter(spec.ablation_variants), None),
        "settlement_scored": False,
        "rows": 0,
        "days": 0,
        "delta": None,
    }


def artifact_path_from_candidate_replay(payload):
    artifact = (payload or {}).get("artifact") or {}
    path = artifact.get("path") or artifact.get("artifact_path")
    if not path:
        return None
    return Path(path)


def _is_missing_imputer_stat(value):
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def _retained_feature_names(bundle, names):
    imputer = bundle.get("imputer") if isinstance(bundle, dict) else None
    statistics = getattr(imputer, "statistics_", None)
    if statistics is None:
        return set(names)
    stats = list(statistics)
    if len(stats) != len(names):
        return set(names)
    return {
        name
        for name, stat in zip(names, stats)
        if not _is_missing_imputer_stat(stat)
    }


def collect_artifact_feature_names(artifact):
    names = set()
    if not isinstance(artifact, dict):
        return names
    for key in ("feature_names", "feature_columns", "features", "numeric_features", "categorical_features"):
        values = artifact.get(key)
        if isinstance(values, (list, tuple, set)):
            raw_names = [str(value) for value in values if value]
            names.update(_retained_feature_names(artifact, raw_names))
    models = artifact.get("models") or {}
    if isinstance(models, dict):
        for bundle in models.values():
            if isinstance(bundle, dict):
                names.update(collect_artifact_feature_names(bundle))
    return names


def active_model_usage(candidate_replay_payload):
    path = artifact_path_from_candidate_replay(candidate_replay_payload)
    result = {
        "status": "MISSING",
        "artifact_path": str(path) if path else None,
        "feature_count": 0,
        "feature_names": [],
        "active_overlay_families": [],
        "error": None,
    }
    if path and path.exists():
        try:
            with path.open("rb") as handle:
                artifact = pickle.load(handle)
            names = collect_artifact_feature_names(artifact)
            result.update({
                "status": "PRESENT",
                "feature_count": len(names),
                "feature_names": sorted(names),
            })
        except Exception as exc:  # noqa: BLE001 - inventory should degrade conservatively
            result.update({"status": "ERROR", "error": str(exc)})

    active_overlay_families = set()
    micro = (candidate_replay_payload or {}).get("microstructure") or {}
    aggregate = micro.get("aggregate") or {}
    if aggregate.get("n"):
        active_overlay_families.add("clob_microstructure")
    result["active_overlay_families"] = sorted(active_overlay_families)
    return result


def active_family_usage(spec, usage):
    status = (usage or {}).get("status")
    overlay_families = set((usage or {}).get("active_overlay_families") or [])
    feature_names = set((usage or {}).get("feature_names") or [])
    active_features = sorted(set(spec.feature_columns) & feature_names)
    if spec.family_id in overlay_families:
        return {
            "model_influence": True,
            "active_model_feature_columns": active_features,
            "active_model_feature_count": len(active_features),
            "active_model_usage_status": "ACTIVE_OVERLAY",
        }
    if status != "PRESENT":
        return {
            "model_influence": spec.model_influence,
            "active_model_feature_columns": active_features,
            "active_model_feature_count": len(active_features),
            "active_model_usage_status": f"USAGE_{status or 'MISSING'}",
        }
    return {
        "model_influence": spec.model_influence and bool(active_features),
        "active_model_feature_columns": active_features,
        "active_model_feature_count": len(active_features),
        "active_model_usage_status": "ACTIVE_FEATURES" if active_features else "NOT_USED_BY_ACTIVE_ARTIFACT",
    }


def lineage_status(spec, stats):
    if spec.family_id == "clob_microstructure":
        if stats["feature_rows"] and stats["clob_raw_tape_folders"]:
            return "PASS"
        if stats["feature_rows"]:
            return "MISSING_RAW_CLOB_TAPES"
        if stats["clob_raw_tape_folders"]:
            return "MISSING_CLOB_FEATURES"
        return "MISSING_CLOB_LINEAGE"
    if spec.source_keys and stats["source_status_rows"] == 0:
        return "MISSING_SOURCE_STATUS"
    if spec.source_keys and stats["missing_source_status_folders"]:
        return "PARTIAL_SOURCE_STATUS"
    if requires_forecast_payload(spec) and stats["forecast_payload_rows"] == 0:
        return "MISSING_FORECAST_PAYLOADS"
    if requires_forecast_payload(spec) and stats["missing_forecast_payload_folders"]:
        return "PARTIAL_FORECAST_PAYLOADS"
    if spec.feature_columns and stats["feature_rows"] == 0:
        return "MISSING_FEATURE_ROWS"
    return "PASS"


def parity_status(spec, stats, lineage):
    feature_column_count = len(spec.feature_columns)
    present_count = len(stats["feature_columns_present"])
    if feature_column_count and present_count == 0:
        return "NO_FEATURE_COLUMNS_OBSERVED"
    if feature_column_count and present_count < feature_column_count:
        return "MISSING_FEATURE_COLUMNS"
    if spec.family_id == "clob_microstructure":
        if lineage != "PASS":
            return "LINEAGE_BLOCKED"
        if "clob_feature_available" not in stats["feature_columns_present"]:
            return "MISSING_FEATURE_COLUMNS"
        return "PASS"
    rate = missing_rate({
        "missing_cells": stats["feature_missing_cells"],
        "total_cells": stats["feature_total_cells"],
    })
    if rate is not None and rate >= 0.98:
        return "MOSTLY_MISSING"
    if rate is not None and rate >= 0.50:
        return "PARTIAL_MISSINGNESS"
    if lineage != "PASS":
        return "LINEAGE_BLOCKED"
    if "live_only" in spec.live_only_policy:
        return "LIVE_ONLY_REQUIRES_BACKFILL"
    return "PASS"


def promotion_decision(spec, lineage, parity, ablation):
    if "historical_only_not_live_serving" == spec.live_only_policy:
        return {
            "status": "HOLD_HISTORICAL_ONLY",
            "reason": "Feature family is explicitly not live-serving eligible.",
            "action": "Keep as research/backtest context until serving parity design exists.",
        }
    if lineage != "PASS":
        return {
            "status": "BLOCK_LINEAGE",
            "reason": lineage,
            "action": "Backfill or waive source-status/raw-payload lineage before promotion.",
        }
    if parity != "PASS":
        return {
            "status": "BLOCK_PARITY",
            "reason": parity,
            "action": "Backfill historical feature rows or keep the family diagnostic-only.",
        }
    if ablation.get("status") != "PRESENT":
        return {
            "status": "BLOCK_MISSING_ABLATION",
            "reason": "No settlement-scored ablation result is attached.",
            "action": "Run source-family ablation and attach data/backtest/source_family_ablation.json.",
        }
    delta = ablation.get("delta")
    if delta is not None and delta <= 0:
        return {
            "status": "HOLD_NO_LIFT",
            "reason": f"Knockout delta {delta:+.4f} does not show durable lift.",
            "action": "Keep out of promotion until a settled slice shows positive value.",
        }
    return {
        "status": "PROMOTION_CANDIDATE",
        "reason": "Lineage, parity, and settlement-scored ablation are present.",
        "action": "Eligible for candidate replay and shadow gates.",
    }


def reanalysis_promotion_lane(ablation):
    if not ablation or ablation.get("status") != "PRESENT":
        return {
            "status": "BLOCKED_MISSING_ABLATION",
            "allowed_markets": [],
            "quarantined_markets": [],
            "thin_margin_markets": [],
            "policy": "no_reanalysis_features",
            "reason": "Missing settlement-scored per-market reanalysis gates.",
            "action": "Run Item 27 reanalysis gates before enabling any lane.",
        }
    details = ablation.get("market_details") or []
    allowed = []
    quarantined = []
    thin_margin = []
    for row in details:
        market_id = row.get("market_id")
        if not market_id:
            continue
        delta = row.get("delta_brier")
        if delta is not None and float(delta) > 0:
            allowed.append(market_id)
            if float(delta) < REANALYSIS_THIN_MARGIN_DELTA:
                thin_margin.append(market_id)
        else:
            quarantined.append(market_id)
    if allowed and quarantined:
        status = "PARTIAL_POSITIVE_MARKET_SHADOW_LANE"
        policy = "positive_markets_only"
        reason = "Mixed per-market gates; only positive markets may enter candidate shadow."
    elif allowed:
        status = "BROAD_POSITIVE_MARKET_SHADOW_LANE"
        policy = "all_scored_markets"
        reason = "All scored markets have positive reanalysis gate deltas."
    else:
        status = "BLOCKED_NO_POSITIVE_MARKETS"
        policy = "no_reanalysis_features"
        reason = "No market has positive reanalysis gate evidence."
    return {
        "status": status,
        "policy": policy,
        "allowed_markets": sorted(allowed),
        "quarantined_markets": sorted(quarantined),
        "thin_margin_markets": sorted(thin_margin),
        "thin_margin_delta": REANALYSIS_THIN_MARGIN_DELTA,
        "market_count": len(details),
        "allowed_market_count": len(set(allowed)),
        "quarantined_market_count": len(set(quarantined)),
        "reason": reason,
        "action": (
            "Train or shadow only the allowed markets; keep quarantined markets "
            "on the no-reanalysis path until their Item 27 gates turn positive."
        ),
    }


def inventory_rows(stats_by_family, ablation_payload, model_usage=None):
    ablations = ablation_by_variant(ablation_payload)
    rows = []
    for spec in FAMILY_SPECS:
        stats = stats_by_family[spec.family_id]
        usage = active_family_usage(spec, model_usage or {})
        lineage = lineage_status(spec, stats)
        parity = parity_status(spec, stats, lineage)
        ablation = ablation_for_spec(spec, ablations)
        decision = promotion_decision(spec, lineage, parity, ablation)
        promotion_lane = None
        if spec.family_id == "reanalysis_synoptic":
            promotion_lane = reanalysis_promotion_lane(ablation)
        rows.append({
            "family_id": spec.family_id,
            "label": spec.label,
            "owner": spec.owner,
            "source_keys": list(spec.source_keys),
            "feature_columns": list(spec.feature_columns),
            "feature_column_count": len(spec.feature_columns),
            "feature_columns_present": sorted(stats["feature_columns_present"]),
            "missing_feature_columns": sorted(set(spec.feature_columns) - stats["feature_columns_present"]),
            "lineage_artifacts": list(spec.lineage_artifacts),
            "historical_archive_status": spec.historical_archive_status,
            "live_only": spec.live_only_policy != "training_and_serving",
            "live_only_policy": spec.live_only_policy,
            "model_influence": usage["model_influence"],
            "configured_model_influence": spec.model_influence,
            "active_model_usage_status": usage["active_model_usage_status"],
            "active_model_feature_count": usage["active_model_feature_count"],
            "active_model_feature_columns": usage["active_model_feature_columns"],
            "source_status": {
                "rows": stats["source_status_rows"],
                "ok_rows": stats["source_status_ok_rows"],
                "sources_seen": sorted(item for item in stats["source_status_sources"] if item),
                "folder_count": len(stats["source_status_folders"]),
                "missing_folder_count": len(stats["missing_source_status_folders"]),
                "missing_folder_samples": sorted(stats["missing_source_status_folders"])[:5],
            },
            "forecast_payloads": {
                "rows": stats["forecast_payload_rows"],
                "sources_seen": sorted(item for item in stats["forecast_payload_sources"] if item),
                "folder_count": len(stats["forecast_payload_folders"]),
                "missing_folder_count": len(stats["missing_forecast_payload_folders"]),
                "missing_folder_samples": sorted(stats["missing_forecast_payload_folders"])[:5],
            },
            "feature_missingness": {
                "rows": stats["feature_rows"],
                "missing_cells": stats["feature_missing_cells"],
                "total_cells": stats["feature_total_cells"],
                "missing_rate": missing_rate({
                    "missing_cells": stats["feature_missing_cells"],
                    "total_cells": stats["feature_total_cells"],
                }),
                "by_market": grouped_missingness(stats["by_market"]),
                "by_cutoff_hour": grouped_missingness(stats["by_cutoff"]),
            },
            "clob_lineage": {
                "raw_tape_folder_count": len(stats["clob_raw_tape_folders"]),
                "artifact_folder_count": len(stats["artifact_folders"]),
            },
            "lineage_status": lineage,
            "train_serve_parity_status": parity,
            "ablation": ablation,
            "promotion_decision": decision,
            "promotion_lane": promotion_lane,
            "sample_folders": sorted(stats["sample_folders"])[:5],
        })
    return rows


def score_location(location):
    settlement = location.get("settlement") or {}
    coords = location.get("coordinates") or {}
    polymarket = location.get("polymarket") or {}
    live_plan = set(location.get("live_source_plan") or [])
    checks = {
        "settlement_station": bool(settlement.get("station_id") and settlement.get("resolution_source_url")),
        "timezone": bool(location.get("timezone")),
        "market_unit": str(location.get("market_unit") or "").upper() in {"C", "F"},
        "coordinates": coords.get("lat") is not None and coords.get("lon") is not None,
        "live_source_plan": bool(live_plan & {"settlement_history", "wu_history"}) and "open_meteo" in live_plan,
        "active_or_recent_event": bool(polymarket.get("active_events") or polymarket.get("latest_event_slug")),
    }
    missing = [name for name, ok in checks.items() if not ok]
    return {
        "location_id": location.get("id"),
        "city": location.get("city"),
        "country_code": location.get("country_code"),
        "checks": checks,
        "status": "PASS" if not missing else "BLOCK",
        "missing": missing,
        "live_source_plan": sorted(live_plan),
        "settlement_source_type": settlement.get("source_type"),
    }


def market_expansion_scorecard(locations_config=DEFAULT_LOCATIONS_CONFIG):
    payload = read_json(locations_config, default={}) or {}
    active = set(REGISTRY)
    rows = [
        score_location(location)
        for location in payload.get("locations") or []
        if location.get("id") not in active
    ]
    blocked = [row for row in rows if row["status"] != "PASS"]
    return {
        "locations_config": str(Path(locations_config)),
        "active_market_ids": sorted(active),
        "candidate_count": len(rows),
        "blocked_count": len(blocked),
        "status": "PASS" if not blocked else "BLOCK",
        "blocked_samples": blocked[:10],
        "rows": rows,
    }


def promotion_preflight(rows):
    blocked = [
        row
        for row in rows
        if row.get("model_influence")
        and str((row.get("promotion_decision") or {}).get("status") or "").startswith("BLOCK")
    ]
    return {
        "status": "BLOCK" if blocked else "PASS",
        "blocked_family_count": len(blocked),
        "blocked_families": [row["family_id"] for row in blocked],
        "blocking_rows": [
            {
                "family_id": row["family_id"],
                "lineage_status": row["lineage_status"],
                "train_serve_parity_status": row["train_serve_parity_status"],
                "ablation_status": (row.get("ablation") or {}).get("status"),
                "decision": (row.get("promotion_decision") or {}).get("status"),
                "action": (row.get("promotion_decision") or {}).get("action"),
            }
            for row in blocked
        ],
        "inventory_command": (
            "python -m weather.reporting.source_family_inventory "
            "--snapshots-root data/snapshots --backtest-root data/backtest "
            "--ablation-json data/backtest/source_family_ablation.json "
            "--candidate-replay-json data/backtest/pooled_candidate_replay_latest.json"
        ),
        "ablation_command": (
            "python -m weather.backtesting.replay_ablation "
            "--json-out data/backtest/source_family_ablation.json"
        ),
    }


def build_source_family_inventory(
    *,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    reanalysis_root=DEFAULT_REANALYSIS_ROOT,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    ablation_json=DEFAULT_ABLATION_JSON,
    candidate_replay_json=DEFAULT_CANDIDATE_REPLAY_JSON,
    locations_config=DEFAULT_LOCATIONS_CONFIG,
    item27_reanalysis_paths=None,
    item27_required_markets=None,
    generated_at_utc=None,
):
    stats_by_family = {spec.family_id: stats_template() for spec in FAMILY_SPECS}
    folders = iter_snapshot_folders(snapshots_root)
    market_folder_counts = defaultdict(int)
    for folder in folders:
        initial_rows = read_csv_rows(folder / "source_status_long.csv")
        market_id = folder_market(folder, initial_rows)
        market_folder_counts[market_id] += 1
        scan_source_status(folder, market_id, stats_by_family)
        scan_forecast_payloads(folder, market_id, stats_by_family)
        scan_features(folder, market_id, stats_by_family)
        scan_clob(folder, market_id, stats_by_family)
    scan_reanalysis_sidecars(reanalysis_root, stats_by_family)
    ablation_payload = read_json(ablation_json, default={}) or {}
    candidate_replay_payload = read_json(candidate_replay_json, default={}) or {}
    model_usage = active_model_usage(candidate_replay_payload)
    item27_reanalysis = (
        item27_reanalysis_ablation_evidence(
            item27_reanalysis_paths,
            required_markets=item27_required_markets,
        )
        if item27_reanalysis_paths is not None
        else item27_reanalysis_ablation_evidence()
    )
    merged_ablation_payload = {
        "variants": list(ablation_by_variant(ablation_payload, candidate_replay_payload).values())
    }
    if item27_reanalysis:
        merged_ablation_payload["variants"].append(item27_reanalysis)
    merged_ablation_count = len(ablation_by_variant(merged_ablation_payload))
    rows = inventory_rows(stats_by_family, merged_ablation_payload, model_usage=model_usage)
    preflight = promotion_preflight(rows)
    expansion = market_expansion_scorecard(locations_config)
    blocked = preflight["blocked_family_count"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or utc_iso(),
        "snapshots_root": str(Path(snapshots_root)),
        "reanalysis_root": str(Path(reanalysis_root)),
        "backtest_root": str(Path(backtest_root)),
        "ablation_json": str(Path(ablation_json)),
        "candidate_replay_json": str(Path(candidate_replay_json)),
        "locations_config": str(Path(locations_config)),
        "status": "BLOCK" if blocked else "PASS",
        "summary": {
            "family_count": len(rows),
            "blocking_family_count": blocked,
            "snapshot_folder_count": len(folders),
            "market_folder_counts": dict(sorted(market_folder_counts.items())),
            "ablation_variant_count": merged_ablation_count,
            "market_expansion_status": expansion["status"],
            "market_expansion_candidate_count": expansion["candidate_count"],
            "active_model_usage_status": model_usage["status"],
            "active_model_feature_count": model_usage["feature_count"],
            "active_overlay_families": model_usage["active_overlay_families"],
        },
        "inventory": rows,
        "active_model_usage": model_usage,
        "promotion_preflight": preflight,
        "market_expansion_scorecard": expansion,
    }


def write_report(payload, report_out=DEFAULT_REPORT_OUT):
    report_out = Path(report_out)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    rows = payload.get("inventory") or []
    lines = [
        "# Source Family Inventory",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: {payload.get('status')}",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Families", summary.get("family_count")],
            ["Blocking families", summary.get("blocking_family_count")],
            ["Snapshot folders", summary.get("snapshot_folder_count")],
            ["Ablation variants", summary.get("ablation_variant_count")],
            ["Active model usage", summary.get("active_model_usage_status")],
            ["Active model features", summary.get("active_model_feature_count")],
            ["Active overlay families", ", ".join(summary.get("active_overlay_families") or []) or "-"],
            ["Market expansion status", summary.get("market_expansion_status")],
        ],
    )
    lines += ["", "## Inventory", ""]
    lines += markdown_table(
        [
            "Family",
            "Lineage",
            "Parity",
            "Ablation",
            "Decision",
            "Active input",
            "Active features",
            "Missing rate",
            "Live-only policy",
        ],
        [
            [
                row.get("family_id"),
                row.get("lineage_status"),
                row.get("train_serve_parity_status"),
                (row.get("ablation") or {}).get("status"),
                (row.get("promotion_decision") or {}).get("status"),
                "yes" if row.get("model_influence") else "no",
                row.get("active_model_feature_count"),
                fmt_num((row.get("feature_missingness") or {}).get("missing_rate"), 3),
                row.get("live_only_policy"),
            ]
            for row in rows
        ],
    )
    reanalysis = next((row for row in rows if row.get("family_id") == "reanalysis_synoptic"), None)
    reanalysis_lane = (reanalysis or {}).get("promotion_lane") or {}
    if reanalysis_lane:
        lines += ["", "## Reanalysis Promotion Lane", ""]
        lines += markdown_table(
            ["Field", "Value"],
            [
                ["Status", reanalysis_lane.get("status")],
                ["Policy", reanalysis_lane.get("policy")],
                ["Allowed markets", ", ".join(reanalysis_lane.get("allowed_markets") or []) or "-"],
                ["Quarantined markets", ", ".join(reanalysis_lane.get("quarantined_markets") or []) or "-"],
                ["Thin-margin markets", ", ".join(reanalysis_lane.get("thin_margin_markets") or []) or "-"],
                ["Reason", reanalysis_lane.get("reason")],
                ["Action", reanalysis_lane.get("action")],
            ],
        )
    reanalysis_details = ((reanalysis or {}).get("ablation") or {}).get("market_details") or []
    if reanalysis_details:
        lines += ["", "## Reanalysis Market Gates", ""]
        lines += markdown_table(
            ["Market", "Rows", "Full Brier", "Ablated Brier", "Delta Brier", "Gate"],
            [
                [
                    row.get("market_id"),
                    row.get("rows"),
                    fmt_num(row.get("full_brier"), 4),
                    fmt_num(row.get("ablated_brier"), 4),
                    fmt_signed(row.get("delta_brier"), 4),
                    row.get("decision"),
                ]
                for row in sorted(
                    reanalysis_details,
                    key=lambda item: (
                        float(item.get("delta_brier") or 0.0),
                        str(item.get("market_id") or ""),
                    ),
                    reverse=True,
                )
            ],
        )
    preflight = payload.get("promotion_preflight") or {}
    lines += ["", "## Promotion Preflight", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", preflight.get("status")],
            ["Blocked families", ", ".join(preflight.get("blocked_families") or []) or "-"],
            ["Inventory command", preflight.get("inventory_command")],
            ["Ablation command", preflight.get("ablation_command")],
        ],
    )
    expansion = payload.get("market_expansion_scorecard") or {}
    lines += ["", "## Market Expansion Scorecard", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", expansion.get("status")],
            ["Candidates", expansion.get("candidate_count")],
            ["Blocked", expansion.get("blocked_count")],
        ],
    )
    report_out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_out


def write_outputs(payload, *, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = write_json_atomic(json_out, payload, trailing_newline=True)
    report_path = write_report(payload, report_out)
    return json_path, report_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build weather-input source-family inventory and promotion preflight.")
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--reanalysis-root", default=str(DEFAULT_REANALYSIS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--ablation-json", default=str(DEFAULT_ABLATION_JSON))
    parser.add_argument("--candidate-replay-json", default=str(DEFAULT_CANDIDATE_REPLAY_JSON))
    parser.add_argument("--locations-config", default=str(DEFAULT_LOCATIONS_CONFIG))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    payload = build_source_family_inventory(
        snapshots_root=args.snapshots_root,
        reanalysis_root=args.reanalysis_root,
        backtest_root=args.backtest_root,
        ablation_json=args.ablation_json,
        candidate_replay_json=args.candidate_replay_json,
        locations_config=args.locations_config,
    )
    json_path, report_path = write_outputs(payload, json_out=args.json_out, report_out=args.report_out)
    print(
        f"{payload['status']}: {payload['summary']['blocking_family_count']} blocking family "
        f"row(s); wrote {json_path} and {report_path}"
    )


if __name__ == "__main__":
    main()
