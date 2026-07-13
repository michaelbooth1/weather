"""Snapshot collectors and low-fill classifiers for the data-layer audit."""

from __future__ import annotations

import csv
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from weather.collection.collection_health import summarize_folder
from weather.io import read_csv_rows as io_read_csv_rows, read_json as io_read_json
from weather.market.market_config import date_from_event_slug
from weather.market.market_registry import spec_for_slug
from weather.model.toronto_model import TORONTO_TZ
from weather.paths import data_path
from weather.reporting.data_quality.feature_quality_quarantine import audit_folder_feature_quality


DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
SNAPSHOT_LONG = "snapshots_long.csv"
SNAPSHOT_OPTIONAL_ARTIFACTS = {
    "snapshots_jsonl": "snapshots.jsonl",
    "replay_inputs": "replay_inputs.jsonl",
    "replay_input_status": "replay_input_status_long.csv",
    "source_status": "source_status_long.csv",
    "features": "features_long.csv",
    "features_raw": "features.jsonl",
    "components": "components_long.csv",
    "components_raw": "components.jsonl",
    "snapshot_explanations": "snapshot_explanations_long.csv",
    "forecasts": "forecasts_long.csv",
    "forecast_payloads": "forecast_payloads_long.csv",
    "observation_payloads": "observation_payloads_long.csv",
    "variant_predictions": "variant_predictions_long.csv",
    "variant_predictions_raw": "variant_predictions.jsonl",
    "clob_features": "clob_features_long.csv",
    "clob_capture_status": "clob_capture_status.jsonl",
    "clob_tokens": "clob_tokens.csv",
    "clob_tokens_raw": "clob_tokens.jsonl",
    "order_books_summary": "order_books_summary.csv",
    "order_books_raw": "order_books.jsonl",
    "order_books_long": "order_books_long.csv",
    "order_books_long_gzip": "order_books_long.csv.gz",
    "price_history": "price_history.csv",
    "price_history_raw": "price_history.jsonl",
    "market_ws_events": "market_ws_events.csv",
    "market_ws_raw": "market_ws.jsonl",
    "settlement": "settlement.json",
}
CLOB_TOKEN_ARTIFACT_KEYS = ("clob_tokens", "clob_tokens_raw")
CLOB_RAW_BOOK_ARTIFACT_KEYS = (
    "order_books_summary",
    "order_books_raw",
    "order_books_long",
    "order_books_long_gzip",
)
OBSERVATION_PAYLOAD_SOURCE_NAMES = {
    "wu_history",
    "wu_current",
    "metar",
    "eccc_swob",
    "eccc_hourly",
    "nws_observations",
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
    "snapshot_explanations",
)
FORECAST_PAYLOAD_ARTIFACT = "forecast_payloads"
OBSERVATION_PAYLOAD_ARTIFACT = "observation_payloads"
CORE_TRAINING_ELIGIBILITY_ARTIFACTS = (
    "replay_inputs",
    "replay_input_status",
    "source_status",
    "features",
    "components",
    "forecasts",
)
EXPLANATION_ELIGIBILITY_ARTIFACTS = CORE_TRAINING_ELIGIBILITY_ARTIFACTS + (
    "snapshot_explanations",
)
MARKET_AWARE_ELIGIBILITY_ARTIFACTS = CORE_TRAINING_ELIGIBILITY_ARTIFACTS + (
    "clob_features",
    "clob_tokens",
    "order_books_summary",
    "price_history",
    "market_ws_events",
)
ACTIVE_DAY_REQUIRED_SIDECARS = (
    "replay_inputs",
    "replay_input_status",
    "source_status",
    "features",
    "components",
    "snapshot_explanations",
    "forecasts",
    "forecast_payloads",
    "observation_payloads",
    "variant_predictions",
)
ACTIVE_DAY_OPTIONAL_MARKET_SIDECARS = (
    "clob_features",
    "clob_capture_status",
    "clob_tokens",
    "order_books_summary",
    "price_history",
    "market_ws_events",
)
DEFAULT_AUDIT_THRESHOLDS = {
    "min_snapshot_field_fill_rate": 0.90,
    "required_artifact_rate": 1.0,
    "forecast_payload_artifact_rate": 1.0,
    "max_source_stale_or_failed_rate": 0.05,
    "max_reanalysis_raw_only_days": 0,
    "max_quarantined_impossible_observations": 0,
}

REQUIRED_LOW_FILL_FIELDS = {
    "best_ask",
    "last_trade_price",
    "feature_schema_version",
    "snapshot_cadence_quality_state",
    "snapshot_cadence_gap_count",
    "snapshot_cadence_last_model_age_seconds",
    "snapshot_cadence_confidence_multiplier",
    "snapshot_cadence_permission",
    "snapshot_cadence_reason",
}
INTENTIONALLY_SPARSE_LOW_FILL_FIELDS = {
    "snapshot_cadence_max_gap_seconds",
}
OPTIONAL_MARKET_MICROSTRUCTURE_LOW_FILL_FIELDS = {
    "best_bid",
}
INTENTIONALLY_SPARSE_LOW_FILL_PREFIXES = (
    "official_canadian_",
    "eccc_",
    "nws_",
    "trigger_",
)
RETIRED_LOW_FILL_FIELDS = {
    "bin_value_hi_c",
}
RETIRED_LOW_FILL_PREFIXES = (
    "runtime_",
)

def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


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
    try:
        return io_read_csv_rows(path, attach_diagnostics=True)
    except OSError:
        return []


def read_json_dict(path):
    return io_read_json(path, default={})


def truthy(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


AUTH_FAILURE_RECENT_DATA_DAYS = 2


def _recent_auth_failure_markets(market_latest_failure_dates, folder_rows):
    """Markets whose newest auth-failure day is within the newest data days.

    Recency is measured against the newest target_date in the scanned folders
    rather than the wall clock: if collection itself stops, the failure days
    stay the newest data and the gate keeps failing closed.
    """
    if not market_latest_failure_dates:
        return []
    newest = max(
        (str(row.get("target_date")) for row in folder_rows if row.get("target_date")),
        default=None,
    )
    if newest is None:
        return sorted(market_latest_failure_dates)
    try:
        cutoff = (
            date.fromisoformat(newest) - timedelta(days=AUTH_FAILURE_RECENT_DATA_DAYS - 1)
        ).isoformat()
    except ValueError:
        return sorted(market_latest_failure_dates)
    return sorted(
        market
        for market, latest in market_latest_failure_dates.items()
        if latest >= cutoff
    )


def source_status_summary_for_folder(folder):
    rows = read_csv_dicts(Path(folder) / "source_status_long.csv")
    settlement_auth_failures = [
        row for row in rows
        if str(row.get("status") or "").lower() == "settlement_source_auth_failure"
        or str(row.get("degradation_state") or "").lower() == "settlement_source_auth_failure"
        or (
            str(row.get("source_family") or row.get("source") or "").lower() == "wu_history"
            and str(row.get("http_status") or "").strip() in {"401", "403"}
        )
    ]
    stale_or_failed = [
        row for row in rows
        if truthy(row.get("stale"))
        or str(row.get("status") or "").lower() in {"failed", "error", "stale_cache"}
        or row in settlement_auth_failures
        or str(row.get("ok") or "").lower() == "false"
    ]
    by_status = Counter(row.get("status") or "unknown" for row in rows)
    return {
        "row_count": len(rows),
        "source_count": len({row.get("source") for row in rows if row.get("source")}),
        "stale_or_failed_rows": len(stale_or_failed),
        "settlement_source_auth_failure_rows": len(settlement_auth_failures),
        "settlement_source_auth_failure_sources": sorted({
            row.get("source") for row in settlement_auth_failures if row.get("source")
        }),
        "status_counts": dict(sorted(by_status.items())),
    }


def forecast_payload_summary_for_folder(folder):
    rows = read_csv_dicts(Path(folder) / "forecast_payloads_long.csv")
    logical_bytes = sum(
        int(
            safe_float(row.get("logical_referenced_bytes"))
            or safe_float(row.get("payload_bytes"))
            or 0
        )
        for row in rows
    )
    physical_bytes = sum(
        int(
            safe_float(row.get("physical_bytes_written"))
            or (
                safe_float(row.get("payload_bytes"))
                if truthy(row.get("payload_blob_created"))
                else 0
            )
            or 0
        )
        for row in rows
    )
    avoided_bytes = sum(
        int(
            safe_float(row.get("avoided_bytes"))
            or (
                safe_float(row.get("payload_bytes"))
                if truthy(row.get("payload_blob_reused"))
                else 0
            )
            or 0
        )
        for row in rows
    )
    return {
        "row_count": len(rows),
        "source_count": len({row.get("source") for row in rows if row.get("source")}),
        "payload_bytes": logical_bytes,
        "logical_referenced_bytes": logical_bytes,
        "physical_bytes_written": physical_bytes,
        "avoided_bytes": avoided_bytes,
        "created_blob_count": sum(
            1 for row in rows if truthy(row.get("payload_blob_created"))
        ),
        "reused_blob_count": sum(
            1 for row in rows if truthy(row.get("payload_blob_reused"))
        ),
        "shared_manifest_row_count": sum(
            1
            for row in rows
            if row.get("payload_storage_scope") == "shared_market_invariant"
        ),
        "unique_payload_count": len(
            {row.get("payload_hash") for row in rows if row.get("payload_hash")}
        ),
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
        "folder_status": summary.get("folder_status"),
        "captured_count": summary.get("captured_count"),
        "reconstructed_count": summary.get("reconstructed_count"),
        "evaluation_only_count": summary.get("evaluation_only_count"),
        "status_counts": status or {},
    }


def missing_artifacts(artifact_presence, names):
    return [name for name in names if not artifact_presence.get(name)]


def forecast_payload_observation_source_rows(folder):
    path = Path(folder) / "forecast_payloads_long.csv"
    rows = read_csv_dicts(path)
    return sum(1 for row in rows if row.get("source") in OBSERVATION_PAYLOAD_SOURCE_NAMES)


def sidecar_backfill_commands(folder, artifact_presence):
    folder_text = str(folder)
    commands = []
    if (
        not artifact_presence.get("replay_input_status")
        or not artifact_presence.get("replay_inputs")
    ):
        commands.append({
            "artifact": "replay_input_status",
            "command": (
                "python -m weather.operations.replay_status_backfill "
                f"\"{folder_text}\" --reconstruct-missing"
            ),
            "reconstructable": True,
        })
    if (
        (not artifact_presence.get("features") or not artifact_presence.get("components"))
        and artifact_presence.get("snapshots_jsonl")
    ):
        commands.append({
            "artifact": "features_components",
            "command": f"python -m weather.collection.snapshot_store backfill-core-sidecars \"{folder_text}\"",
            "reconstructable": True,
        })
    if not artifact_presence.get("snapshot_explanations") and artifact_presence.get("snapshots_jsonl"):
        commands.append({
            "artifact": "snapshot_explanations",
            "command": f"python -m weather.collection.snapshot_store backfill-explanations \"{folder_text}\"",
            "reconstructable": True,
        })
    if not artifact_presence.get("observation_payloads") and artifact_presence.get("forecast_payloads"):
        observation_source_rows = forecast_payload_observation_source_rows(folder)
        if observation_source_rows:
            commands.append({
                "artifact": "observation_payloads",
                "command": f"python -m weather.collection.snapshot_store backfill-observation-payloads \"{folder_text}\"",
                "reconstructable": True,
            })
        else:
            commands.append({
                "artifact": "observation_payloads",
                "command": "restart live snapshot loop with observation raw payload persistence enabled",
                "reconstructable": False,
                "reason": "forecast_payloads_long.csv contains no observation-source payload rows",
            })
    has_raw_books = any(artifact_presence.get(name) for name in CLOB_RAW_BOOK_ARTIFACT_KEYS)
    if not artifact_presence.get("clob_features") and has_raw_books:
        commands.append({
            "artifact": "clob_features",
            "command": f"python -m weather.market.market_microstructure_features \"{folder_text}\" --json",
            "reconstructable": True,
        })
    return commands


def sidecar_eligibility_for_folder(row, *, settled_scope_ready=False, active_day=False):
    artifact_presence = row.get("artifact_presence") or {}
    replay = row.get("replay_input_status") or {}
    feature_quality = row.get("feature_quality") or {}
    feature_quality_training_excluded_rows = int(feature_quality.get("training_excluded_row_count") or 0)
    feature_quality_training_excluded = feature_quality_training_excluded_rows > 0
    replay_evaluation_only = replay.get("folder_status") == "evaluation_only"
    core_missing = missing_artifacts(artifact_presence, CORE_TRAINING_ELIGIBILITY_ARTIFACTS)
    explanation_missing = missing_artifacts(artifact_presence, EXPLANATION_ELIGIBILITY_ARTIFACTS)
    market_missing = missing_artifacts(artifact_presence, MARKET_AWARE_ELIGIBILITY_ARTIFACTS)
    labels = {
        "score_only": True,
        "replay_only": not replay_evaluation_only and not missing_artifacts(
            artifact_presence,
            ("replay_inputs", "replay_input_status"),
        ),
        "training_ready": bool(
            settled_scope_ready
            and not replay_evaluation_only
            and not core_missing
            and not feature_quality_training_excluded
        ),
        "explanation_ready": False,
        "market_aware_ready": False,
        "variant_ready": False,
    }
    labels["explanation_ready"] = bool(labels["training_ready"] and not explanation_missing)
    labels["market_aware_ready"] = bool(labels["training_ready"] and not market_missing)
    labels["variant_ready"] = bool(labels["training_ready"] and artifact_presence.get("variant_predictions"))
    if labels["market_aware_ready"]:
        primary = "market_aware_ready"
    elif labels["explanation_ready"]:
        primary = "explanation_ready"
    elif labels["training_ready"]:
        primary = "training_ready"
    elif labels["replay_only"]:
        primary = "replay_only"
    else:
        primary = "score_only"

    evaluation_only_reasons = []
    if replay_evaluation_only:
        evaluation_only_reasons.append("replay_input_status_marked_evaluation_only")
    if not settled_scope_ready:
        evaluation_only_reasons.append(row.get("training_ready_reason") or "not_in_settled_training_scope")
    if not labels["replay_only"]:
        evaluation_only_reasons.extend(
            f"missing_{name}" for name in missing_artifacts(artifact_presence, ("replay_inputs", "replay_input_status"))
        )
    if labels["replay_only"] and not labels["training_ready"]:
        evaluation_only_reasons.extend(f"missing_{name}" for name in core_missing)
    if feature_quality_training_excluded:
        evaluation_only_reasons.append(
            f"feature_quality_training_excluded_rows:{feature_quality_training_excluded_rows}"
        )

    non_reconstructable = []
    for name in missing_artifacts(
        artifact_presence,
        ("clob_tokens", "order_books_summary", "price_history", "market_ws_events", "variant_predictions"),
    ):
        non_reconstructable.append({
            "artifact": name,
            "reason": "live_capture_only_or_not_serialized_in_legacy_snapshot_jsonl",
        })

    active_missing = []
    if active_day:
        active_missing = missing_artifacts(
            artifact_presence,
            ACTIVE_DAY_REQUIRED_SIDECARS + ACTIVE_DAY_OPTIONAL_MARKET_SIDECARS,
        )

    return {
        "primary_label": primary,
        "labels": labels,
        "missing_core_artifacts": core_missing,
        "missing_explanation_artifacts": explanation_missing,
        "missing_market_aware_artifacts": market_missing,
        "promotion_exclusion_reasons": [] if labels["training_ready"] else sorted(set(evaluation_only_reasons)),
        "market_aware_exclusion_reasons": [
            f"missing_{name}" for name in market_missing
        ],
        "evaluation_only_reasons": sorted(set(evaluation_only_reasons)),
        "non_reconstructable_gaps": non_reconstructable,
        "backfill_commands": sidecar_backfill_commands(row.get("folder"), artifact_presence),
        "active_day_sidecar_regression": bool(active_missing),
        "active_day_missing_sidecars": active_missing,
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
    feature_quality = audit_folder_feature_quality(folder)
    feature_quality_summary = dict(feature_quality.get("summary") or {})
    feature_quality_summary["sample_rows"] = (feature_quality.get("rows") or [])[:10]
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
        "feature_quality": feature_quality_summary,
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
    source_status_settlement_auth_failure_rows = 0
    source_status_settlement_auth_failure_markets = set()
    source_status_settlement_auth_failure_market_dates = {}
    source_status_counts = Counter()
    forecast_payload_rows = 0
    forecast_payload_bytes = 0
    forecast_payload_physical_bytes = 0
    forecast_payload_avoided_bytes = 0
    forecast_payload_created_blobs = 0
    forecast_payload_reused_blobs = 0
    forecast_payload_shared_rows = 0
    clob_feature_rows = 0
    clob_book_available_rows = 0
    clob_price_history_available_rows = 0
    clob_ws_event_window_rows = 0
    clob_capture_status_days = 0
    clob_token_artifact_days = 0
    clob_raw_book_artifact_days = 0
    training_ready_clob_capture_status_days = 0
    training_ready_clob_token_artifact_days = 0
    training_ready_clob_raw_book_artifact_days = 0
    replay_status_counts = Counter()
    eligibility_label_counts = Counter()
    primary_eligibility_counts = Counter()
    eligibility_missing_artifact_counts = Counter()
    eligibility_non_reconstructable_counts = Counter()
    backfill_command_counts = Counter()
    active_day_sidecar_regression_count = 0
    eligibility_exclusion_samples = []
    feature_quality_reason_counts = Counter()
    feature_quality_disposition_counts = Counter()
    feature_quality_source_file_counts = Counter()
    feature_quality_quarantine_rows = 0
    feature_quality_training_excluded_rows = 0
    feature_quality_promotion_excluded_rows = 0
    feature_quality_backfill_candidate_rows = 0
    feature_quality_raw_evidence_absent_rows = 0
    feature_quality_replay_impacted_rows = 0
    feature_quality_affected_folders = 0
    feature_quality_affected_markets = set()
    feature_quality_samples = []
    for row in folder_rows:
        by_market[row.get("market_id")].append(row)
        target_date = parse_date(row.get("target_date"))
        replay = row.get("replay_input_status") or {}
        replay_folder_status = replay.get("folder_status")
        training_ready = bool(target_date and target_date < training_ready_cutoff)
        if training_ready and replay_folder_status == "evaluation_only":
            training_ready = False
            row["training_ready_reason"] = "replay_status_evaluation_only"
        elif training_ready:
            row["training_ready_reason"] = "target_date_before_cutoff"
        else:
            row["training_ready_reason"] = "not_settled_cutoff"
        row["training_ready"] = training_ready
        eligibility = sidecar_eligibility_for_folder(
            row,
            settled_scope_ready=training_ready,
            active_day=bool(target_date and target_date >= training_ready_cutoff),
        )
        row["sidecar_eligibility"] = eligibility
        artifact_scope_ready = bool((eligibility.get("labels") or {}).get("training_ready"))
        primary_eligibility_counts[eligibility.get("primary_label") or "unknown"] += 1
        for label, enabled in (eligibility.get("labels") or {}).items():
            if enabled:
                eligibility_label_counts[label] += 1
        for name in (
            (eligibility.get("missing_core_artifacts") or [])
            + (eligibility.get("missing_explanation_artifacts") or [])
            + (eligibility.get("missing_market_aware_artifacts") or [])
        ):
            eligibility_missing_artifact_counts[name] += 1
        for item in eligibility.get("non_reconstructable_gaps") or []:
            eligibility_non_reconstructable_counts[item.get("artifact") or "unknown"] += 1
        for item in eligibility.get("backfill_commands") or []:
            backfill_command_counts[item.get("artifact") or "unknown"] += 1
        if eligibility.get("active_day_sidecar_regression"):
            active_day_sidecar_regression_count += 1
        if eligibility.get("promotion_exclusion_reasons") or eligibility.get("market_aware_exclusion_reasons"):
            eligibility_exclusion_samples.append({
                "folder": row.get("folder"),
                "market_id": row.get("market_id"),
                "target_date": row.get("target_date"),
                "primary_label": eligibility.get("primary_label"),
                "promotion_exclusion_reasons": eligibility.get("promotion_exclusion_reasons") or [],
                "market_aware_exclusion_reasons": eligibility.get("market_aware_exclusion_reasons") or [],
                "backfill_commands": eligibility.get("backfill_commands") or [],
            })
        feature_quality = row.get("feature_quality") or {}
        quarantine_count = int(feature_quality.get("quarantine_row_count") or 0)
        if quarantine_count:
            feature_quality_affected_folders += 1
            if row.get("market_id"):
                feature_quality_affected_markets.add(row.get("market_id"))
        feature_quality_quarantine_rows += quarantine_count
        feature_quality_training_excluded_rows += int(feature_quality.get("training_excluded_row_count") or 0)
        feature_quality_promotion_excluded_rows += int(feature_quality.get("promotion_excluded_row_count") or 0)
        feature_quality_backfill_candidate_rows += int(feature_quality.get("backfill_candidate_row_count") or 0)
        feature_quality_raw_evidence_absent_rows += int(feature_quality.get("raw_evidence_absent_row_count") or 0)
        feature_quality_replay_impacted_rows += int(feature_quality.get("replay_input_impacted_count") or 0)
        feature_quality_reason_counts.update(feature_quality.get("reason_counts") or {})
        feature_quality_disposition_counts.update(feature_quality.get("disposition_counts") or {})
        feature_quality_source_file_counts.update(feature_quality.get("source_file_counts") or {})
        if feature_quality.get("sample_rows"):
            feature_quality_samples.extend(feature_quality.get("sample_rows") or [])
        if artifact_scope_ready:
            training_ready_folder_count += 1
        field_nonempty.update(row.get("nonempty") or {})
        field_totals.update(row.get("field_totals") or {})
        for name, present in (row.get("artifact_presence") or {}).items():
            if present:
                artifact_totals[name] += 1
                if artifact_scope_ready:
                    training_ready_artifact_totals[name] += 1
        artifact_presence = row.get("artifact_presence") or {}
        if artifact_presence.get("clob_capture_status"):
            clob_capture_status_days += 1
            if artifact_scope_ready:
                training_ready_clob_capture_status_days += 1
        has_clob_token_artifact = any(
            bool(artifact_presence.get(name)) for name in CLOB_TOKEN_ARTIFACT_KEYS
        )
        has_clob_raw_book_artifact = any(
            bool(artifact_presence.get(name)) for name in CLOB_RAW_BOOK_ARTIFACT_KEYS
        )
        if has_clob_token_artifact:
            clob_token_artifact_days += 1
            if artifact_scope_ready:
                training_ready_clob_token_artifact_days += 1
        if has_clob_raw_book_artifact:
            clob_raw_book_artifact_days += 1
            if artifact_scope_ready:
                training_ready_clob_raw_book_artifact_days += 1
        status = row.get("source_status") or {}
        source_status_rows += int(status.get("row_count") or 0)
        source_status_stale_or_failed_rows += int(status.get("stale_or_failed_rows") or 0)
        auth_failure_rows = int(status.get("settlement_source_auth_failure_rows") or 0)
        source_status_settlement_auth_failure_rows += auth_failure_rows
        if auth_failure_rows and row.get("market_id"):
            source_status_settlement_auth_failure_markets.add(row.get("market_id"))
            if row.get("target_date"):
                existing = source_status_settlement_auth_failure_market_dates.get(row.get("market_id"))
                if existing is None or str(row.get("target_date")) > existing:
                    source_status_settlement_auth_failure_market_dates[row.get("market_id")] = str(
                        row.get("target_date")
                    )
        source_status_counts.update(status.get("status_counts") or {})
        payloads = row.get("forecast_payloads") or {}
        forecast_payload_rows += int(payloads.get("row_count") or 0)
        forecast_payload_bytes += int(payloads.get("payload_bytes") or 0)
        forecast_payload_physical_bytes += int(payloads.get("physical_bytes_written") or 0)
        forecast_payload_avoided_bytes += int(payloads.get("avoided_bytes") or 0)
        forecast_payload_created_blobs += int(payloads.get("created_blob_count") or 0)
        forecast_payload_reused_blobs += int(payloads.get("reused_blob_count") or 0)
        forecast_payload_shared_rows += int(payloads.get("shared_manifest_row_count") or 0)
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
    low_fill_classifications = classify_low_fill_fields(low_fill[:25])
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
            "snapshot_explanation_days": sum(
                1 for row in rows
                if (row.get("artifact_presence") or {}).get("snapshot_explanations")
            ),
            "forecast_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("forecasts")),
            "forecast_payload_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("forecast_payloads")),
            "observation_payload_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("observation_payloads")),
            "clob_feature_days": sum(1 for row in rows if (row.get("artifact_presence") or {}).get("clob_features")),
            "clob_capture_status_days": sum(
                1 for row in rows
                if (row.get("artifact_presence") or {}).get("clob_capture_status")
            ),
            "clob_token_artifact_days": sum(
                1 for row in rows
                if any((row.get("artifact_presence") or {}).get(name) for name in CLOB_TOKEN_ARTIFACT_KEYS)
            ),
            "clob_raw_book_artifact_days": sum(
                1 for row in rows
                if any((row.get("artifact_presence") or {}).get(name) for name in CLOB_RAW_BOOK_ARTIFACT_KEYS)
            ),
            "training_ready_label_days": sum(
                1 for row in rows
                if ((row.get("sidecar_eligibility") or {}).get("labels") or {}).get("training_ready")
            ),
            "explanation_ready_days": sum(
                1 for row in rows
                if ((row.get("sidecar_eligibility") or {}).get("labels") or {}).get("explanation_ready")
            ),
            "market_aware_ready_days": sum(
                1 for row in rows
                if ((row.get("sidecar_eligibility") or {}).get("labels") or {}).get("market_aware_ready")
            ),
            "variant_ready_days": sum(
                1 for row in rows
                if ((row.get("sidecar_eligibility") or {}).get("labels") or {}).get("variant_ready")
            ),
            "feature_quality_quarantined_rows": sum(
                int((row.get("feature_quality") or {}).get("quarantine_row_count") or 0)
                for row in rows
            ),
            "feature_quality_training_excluded_rows": sum(
                int((row.get("feature_quality") or {}).get("training_excluded_row_count") or 0)
                for row in rows
            ),
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
            "settlement_source_auth_failure_rows": source_status_settlement_auth_failure_rows,
            # The fail-closed gate reads the market list/count, so they cover
            # only the two newest data days: source-status rows are immutable
            # capture history, and a repaired outage (e.g. June 26-30 WU auth)
            # must not keep failing the gate until its folders age out of the
            # scan. Keyed off data recency, not the wall clock, so a total
            # collection outage still fails closed. Full-window detail stays in
            # *_window fields.
            "settlement_source_auth_failure_market_count": len(
                _recent_auth_failure_markets(
                    source_status_settlement_auth_failure_market_dates, folder_rows
                )
            ),
            "settlement_source_auth_failure_markets": _recent_auth_failure_markets(
                source_status_settlement_auth_failure_market_dates, folder_rows
            ),
            "settlement_source_auth_failure_window_market_count": len(
                source_status_settlement_auth_failure_markets
            ),
            "settlement_source_auth_failure_window_markets": sorted(
                source_status_settlement_auth_failure_markets
            ),
            "settlement_source_auth_failure_market_latest_dates": dict(
                sorted(source_status_settlement_auth_failure_market_dates.items())
            ),
            "status_counts": dict(sorted(source_status_counts.items())),
        },
        "forecast_payloads": {
            "row_count": forecast_payload_rows,
            "payload_bytes": forecast_payload_bytes,
            "logical_referenced_bytes": forecast_payload_bytes,
            "physical_bytes_written": forecast_payload_physical_bytes,
            "avoided_bytes": forecast_payload_avoided_bytes,
            "created_blob_count": forecast_payload_created_blobs,
            "reused_blob_count": forecast_payload_reused_blobs,
            "shared_manifest_row_count": forecast_payload_shared_rows,
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
        "clob_raw_artifacts": {
            "capture_status_days": clob_capture_status_days,
            "token_artifact_days": clob_token_artifact_days,
            "raw_book_artifact_days": clob_raw_book_artifact_days,
            "training_ready_capture_status_days": training_ready_clob_capture_status_days,
            "training_ready_token_artifact_days": training_ready_clob_token_artifact_days,
            "training_ready_raw_book_artifact_days": training_ready_clob_raw_book_artifact_days,
        },
        "replay_input_status": {
            "status_counts": dict(sorted(replay_status_counts.items())),
        },
        "feature_quality_quarantine": {
            "schema_version": "feature_quality_quarantine_summary_v0.1",
            "quarantine_row_count": feature_quality_quarantine_rows,
            "training_excluded_row_count": feature_quality_training_excluded_rows,
            "promotion_excluded_row_count": feature_quality_promotion_excluded_rows,
            "backfill_candidate_row_count": feature_quality_backfill_candidate_rows,
            "raw_evidence_absent_row_count": feature_quality_raw_evidence_absent_rows,
            "replay_input_impacted_count": feature_quality_replay_impacted_rows,
            "affected_folder_count": feature_quality_affected_folders,
            "affected_market_count": len(feature_quality_affected_markets),
            "reason_counts": dict(sorted(feature_quality_reason_counts.items())),
            "disposition_counts": dict(sorted(feature_quality_disposition_counts.items())),
            "source_file_counts": dict(sorted(feature_quality_source_file_counts.items())),
            "sample_rows": feature_quality_samples[:20],
        },
        "sidecar_eligibility": {
            "schema_version": "snapshot_sidecar_eligibility_v0.1",
            "label_counts": dict(sorted(eligibility_label_counts.items())),
            "primary_label_counts": dict(sorted(primary_eligibility_counts.items())),
            "missing_artifact_counts": dict(sorted(eligibility_missing_artifact_counts.items())),
            "non_reconstructable_gap_counts": dict(sorted(eligibility_non_reconstructable_counts.items())),
            "backfill_command_counts": dict(sorted(backfill_command_counts.items())),
            "backfill_candidate_folder_count": sum(
                1 for row in folder_rows
                if ((row.get("sidecar_eligibility") or {}).get("backfill_commands") or [])
            ),
            "active_day_sidecar_regression_count": active_day_sidecar_regression_count,
            "promotion_exclusion_sample": eligibility_exclusion_samples[:20],
        },
        "low_fill_fields": low_fill[:25],
        "low_fill_field_classifications": low_fill_classifications,
        "has_market_token_ids": any(row.get("rows_with_market_token_ids", 0) > 0 for row in folder_rows),
        "by_market": market_rows,
        "folders": folder_rows,
    }


def classify_low_fill_field(row):
    field = row.get("field") or ""
    if field in REQUIRED_LOW_FILL_FIELDS:
        classification = "required"
        owner = "feature contract"
        action = (
            "Backfill the field from canonical artifacts or remove it from the "
            "serving/training contract before using it for broad promotion."
        )
    elif field in OPTIONAL_MARKET_MICROSTRUCTURE_LOW_FILL_FIELDS:
        classification = "market_microstructure_optional"
        owner = "market microstructure"
        action = (
            "Use canonical CLOB/book artifacts for executable bid-side evidence; "
            "one-sided snapshot rows may legitimately have no best_bid."
        )
    elif field in RETIRED_LOW_FILL_FIELDS or any(field.startswith(prefix) for prefix in RETIRED_LOW_FILL_PREFIXES):
        classification = "retired"
        owner = "feature contract"
        action = "Keep this field out of model inputs and remove it from required schema checks."
    elif (
        field in INTENTIONALLY_SPARSE_LOW_FILL_FIELDS
        or any(field.startswith(prefix) for prefix in INTENTIONALLY_SPARSE_LOW_FILL_PREFIXES)
    ):
        classification = "intentionally_sparse"
        owner = "source coverage"
        action = "Document the market/provider scope and keep the field model-exempt outside that scope."
    else:
        classification = "required"
        owner = "feature contract"
        action = "Classify this field explicitly, then backfill it or remove it from model inputs."
    return {
        **row,
        "classification": classification,
        "owner": owner,
        "action": action,
    }


def classify_low_fill_fields(rows):
    return [classify_low_fill_field(row) for row in rows or []]
