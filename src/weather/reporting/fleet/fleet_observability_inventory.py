"""Fleet-wide data integrity and observability report.

Item 31 needs one answer to: are all markets complete, fresh, auditable, and
safe to train/serve from? This module combines collection health, historical
data audits, artifact provenance, trust readiness, and alert severity into a
CI-friendly report.
"""
import argparse
import hashlib
import json
import pickle
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from weather.backtesting.settlement_io import DEFAULT_SNAPSHOTS_ROOT
from weather.reporting.formatting import markdown_table
from weather.collection.snapshot_tracker import SNAPSHOT_SUPERVISOR
from weather.collection.collection_health import (
    SNAPSHOT_FLEET_VERIFY_COMMAND,
    SNAPSHOT_RESTART_COMMAND,
    SNAPSHOT_STATUS_COMMAND,
    fleet_collection_health,
)
from weather.market.market_making_preflight import REMEDIATION_RULES
from weather.market.market_microstructure import (
    BOOK_AUDIT_MAX_GAP_SECONDS,
    CLOB_SUPERVISOR,
    clob_loop_health,
    fleet_book_audit,
    read_clob_loop_status,
)
from weather.market.market_registry import all_specs
from weather.runtime_identity import format_runtime_identity, get_runtime_identity, identities_match
from weather.operations.observation_trigger import OBSERVATION_SUPERVISOR
from weather.operations.observation_trigger import STATUS_PATH as OBSERVATION_STATUS_PATH
from weather.operations.observation_trigger import read_status as read_observation_status
from weather.operations.observation_trigger import watcher_health
from weather.operations import tape_backup
from weather.artifacts import resolve_artifact_path
from weather.paths import relative_to_repo, data_path
from weather.reporting.data_quality.data_auditor import MIN_HOURLY_OBS, audit_fleet_historical_data, jsonable_result
from weather.reporting.location_trust import score_all_markets
from weather.reporting.source_redundancy import (
    FALLBACK_ORDER,
    PRIMARY_SOURCE,
    source_daily_indexes,
    source_values_for_day,
)


SCHEMA_VERSION = "fleet_observability_v0.1"
PROVENANCE_SCHEMA_VERSION = "artifact_provenance_manifest_v0.1"
DEFAULT_JSON_OUT = data_path() / "backtest" / "fleet_observability.json"
DEFAULT_REPORT = data_path() / "backtest" / "fleet_observability_report.md"
DEFAULT_PROVENANCE_OUT = data_path() / "backtest" / "artifact_provenance_manifest.json"
DEFAULT_MM_PAPER_REPORT = data_path() / "backtest" / "mm_paper_report.json"
DEFAULT_SETTLED_DAY_FRESHNESS = data_path() / "backtest" / "settled_day_freshness.json"
DEFAULT_MIN_TRUST = 25
DEFAULT_MIN_SETTLED_DAYS = 2
BROAD_SLO_VERIFY_COMMAND = SNAPSHOT_FLEET_VERIFY_COMMAND
BROAD_SLO_REQUIRED_GATES = (
    "snapshot_coverage_gap",
    "latest_model_row_freshness",
    "variant_prediction_freshness",
    "source_status_freshness",
    "clob_discovery",
    "clob_book_freshness",
    "observation_trigger_health",
    "afternoon_window_coverage",
)
BROAD_SLO_RULES = {
    "snapshot_collection": {
        "root_cause": "snapshot_collection_blocked",
        "owner": "weather snapshot/model loop",
        "suggested_command": SNAPSHOT_RESTART_COMMAND,
        "recoverable_same_day": True,
    },
    "snapshot_coverage_gap": {
        "root_cause": "snapshot_capture_gap",
        "owner": "weather snapshot/model loop",
        "suggested_command": SNAPSHOT_RESTART_COMMAND,
        "recoverable_same_day": True,
    },
    "latest_model_row_freshness": {
        "root_cause": "stale_model_row",
        "owner": "weather snapshot/model loop",
        "suggested_command": SNAPSHOT_RESTART_COMMAND,
        "recoverable_same_day": True,
    },
    "source_status_freshness": {
        "root_cause": "stale_or_degraded_source_status",
        "owner": "snapshot source-status writer",
        "suggested_command": (
            "python -m weather.collection.snapshot_tracker "
            "--backfill-source-status --overwrite-source-status"
        ),
        "recoverable_same_day": True,
    },
    "variant_prediction_freshness": {
        "root_cause": "stale_or_missing_live_variant_prediction_tape",
        "owner": "weather snapshot/model loop",
        "suggested_command": SNAPSHOT_RESTART_COMMAND,
        "recoverable_same_day": True,
    },
    "afternoon_window_coverage": {
        "root_cause": "afternoon_window_incomplete",
        "owner": "weather snapshot/model loop",
        "suggested_command": SNAPSHOT_RESTART_COMMAND,
        "recoverable_same_day": True,
    },
    "clob_book_freshness": {
        "root_cause": "stale_clob_book_tape",
        "owner": "CLOB book supervisor",
        "suggested_command": "python -m weather.market.market_microstructure ensure",
        "recoverable_same_day": True,
    },
    "clob_discovery": {
        "root_cause": "blank_or_inactive_clob_discovery",
        "owner": "CLOB token discovery / Gamma event discovery",
        "suggested_command": "python -m weather.market.market_microstructure capture --market all",
        "recoverable_same_day": True,
    },
    "observation_trigger_health": {
        "root_cause": "watcher_stale",
        "owner": "observation-trigger supervisor",
        "suggested_command": "python -m weather.operations.observation_trigger ensure",
        "recoverable_same_day": True,
    },
}
SOURCE_STATUS_BACKFILL_COMMAND = BROAD_SLO_RULES["source_status_freshness"]["suggested_command"]
SOURCE_PROVIDER_STATUS_COMMAND = SNAPSHOT_STATUS_COMMAND
CURRENT_CODE_SOAK_SCHEMA_VERSION = "loop_current_code_soak_v0.1"
LOOP_RESTART_BUDGETS = {
    "snapshot_capture": 6,
    "clob_capture": 12,
    "observation_trigger": 12,
}
LOOP_RESTART_BUDGET_WINDOW_HOURS = 24.0
LOOP_DIAGNOSTIC_WINDOW_DAYS = 7
COUNTABLE_SOAK_STATES = {"RUNNING"}


MARKET_ARTIFACT_TEMPLATES = {
    "calibrated_weights": "calibrated_weights{suffix}.json",
    "feature_model_coefs": "feature_model_coefs{suffix}.json",
    "feature_model_hgb": "feature_model_hgb{suffix}.pkl",
    "late_day_model": "late_day_model_coefs{suffix}.json",
    "probability_calibration": "probability_calibration{suffix}.json",
    "forecast_error": "forecast_error_model{suffix}.json",
    "settlement_lag": "settlement_lag_model{suffix}.json",
}

FAMILY_ARTIFACTS = {
    "f_family_gate": "f_family_secondary_artifacts.json",
    "f_family_probability_calibration": "probability_calibration_f_family.json",
    "f_family_forecast_error": "forecast_error_model_f_family.json",
    "f_family_settlement_lag": "settlement_lag_model_f_family.json",
    "f_family_pooled_band_model": "feature_model_hgb_f_pooled_v0_2.pkl",
}

LEGACY_ARTIFACT_SCHEMA_BY_KIND = {
    "calibrated_weights": "calibrated_weights_v0.1",
    "feature_model_coefs": "feature_model_coefs_v0.1",
    "feature_model_hgb": "feature_model_hgb_v0.1",
    "late_day_model": "late_day_model_coefs_v0.1",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    path = Path(path)
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _artifact_payload(path):
    path = Path(path)
    if not path.exists():
        return None
    if path.suffix == ".json":
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"_load_error": str(exc)}
    if path.suffix == ".pkl":
        try:
            with path.open("rb") as handle:
                payload = pickle.load(handle)
            return payload if isinstance(payload, dict) else {"_type": type(payload).__name__}
        except Exception as exc:  # noqa: BLE001
            return {"_load_error": str(exc)}
    return {}


def _first_nested_value(payload, key):
    if not isinstance(payload, dict):
        return None
    if payload.get(key) not in (None, ""):
        return payload.get(key)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get(key) not in (None, ""):
        return metadata.get(key)
    for value in payload.values():
        if isinstance(value, dict) and value.get(key) not in (None, ""):
            return value.get(key)
    return None


def _recognized_legacy_schema(payload, kind):
    if not isinstance(payload, dict):
        return None
    if kind == "calibrated_weights" and isinstance(payload.get("hours"), dict):
        return LEGACY_ARTIFACT_SCHEMA_BY_KIND[kind]
    if kind in {"feature_model_coefs", "feature_model_hgb", "late_day_model"}:
        if _first_nested_value(payload, "feature_schema_version"):
            return LEGACY_ARTIFACT_SCHEMA_BY_KIND[kind]
    return None


def artifact_metadata(path, kind=None):
    path = Path(path)
    row = {
        "kind": kind or path.stem,
        "path": relative_to_repo(path),
        "exists": path.exists(),
        "size": None,
        "sha256": None,
        "schema_version": None,
        "feature_schema_version": None,
        "generated_at": None,
        "trained_at": None,
        "version": None,
        "load_error": None,
        "schema_status": "missing_file",
    }
    if not path.exists():
        return row
    stat = path.stat()
    row["size"] = stat.st_size
    row["sha256"] = sha256_file(path)
    payload = _artifact_payload(path)
    if isinstance(payload, dict):
        row["load_error"] = payload.get("_load_error")
        row["schema_version"] = payload.get("schema_version") or _recognized_legacy_schema(payload, kind)
        row["feature_schema_version"] = _first_nested_value(payload, "feature_schema_version")
        row["generated_at"] = _first_nested_value(payload, "generated_at_utc") or _first_nested_value(payload, "generated_at")
        row["trained_at"] = _first_nested_value(payload, "trained_at")
        row["version"] = _first_nested_value(payload, "version")
    if row["load_error"]:
        row["schema_status"] = "unreadable"
    elif row["schema_version"] or row["feature_schema_version"] or row["version"]:
        row["schema_status"] = "ok"
    else:
        row["schema_status"] = "external_manifest_only"
    return row


def artifact_inventory():
    markets = {}
    for spec in all_specs():
        market_rows = {}
        for kind, template in MARKET_ARTIFACT_TEMPLATES.items():
            market_rows[kind] = artifact_metadata(
                resolve_artifact_path(template.format(suffix=spec.artifact_suffix)),
                kind=kind,
            )
        markets[spec.id] = {
            "city": spec.city_label,
            "unit": spec.display_unit,
            "artifacts": market_rows,
        }
    family = {
        kind: artifact_metadata(resolve_artifact_path(filename), kind=kind)
        for kind, filename in FAMILY_ARTIFACTS.items()
    }
    return {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "markets": markets,
        "family_artifacts": family,
    }


def add_alert(alerts, severity, market_id, category, message, detail=None):
    alerts.append({
        "severity": severity,
        "market_id": market_id,
        "category": category,
        "message": message,
        "detail": detail or {},
    })


def _issue_days(audit, key):
    values = audit.get(key) or []
    if key == "sparse_days":
        return [row[0] for row in values if row]
    return list(values)


def _complete_redundant_sources(values, min_hourly_obs=MIN_HOURLY_OBS):
    sources = []
    for source in FALLBACK_ORDER:
        row = values.get(source)
        if not row:
            continue
        if row.get("high") is None:
            continue
        if int(row.get("row_count") or 0) < int(min_hourly_obs):
            continue
        sources.append(source)
    return sources


def historical_gap_coverage(audits, min_hourly_obs=MIN_HOURLY_OBS):
    """Map raw WU audit gaps to unresolved multi-source historical gaps."""
    markets = {}
    for spec in all_specs():
        audit = (audits or {}).get(spec.id) or {}
        missing_days = sorted(set(_issue_days(audit, "missing_days")))
        sparse_days = sorted(set(_issue_days(audit, "sparse_days")))
        issue_days = sorted(set(missing_days) | set(sparse_days))
        indexes = source_daily_indexes(spec)
        day_rows = []
        for day in issue_days:
            values = source_values_for_day(indexes, day)
            covering_sources = _complete_redundant_sources(values, min_hourly_obs=min_hourly_obs)
            day_rows.append({
                "local_date": day,
                "wu_missing": day in missing_days,
                "wu_sparse": day in sparse_days,
                "covering_sources": covering_sources,
                "covered": bool(covering_sources),
                "primary_available": PRIMARY_SOURCE in values,
            })
        markets[spec.id] = {
            "issue_days": len(issue_days),
            "covered_issue_days": sum(1 for row in day_rows if row["covered"]),
            "unresolved_issue_days": [row["local_date"] for row in day_rows if not row["covered"]],
            "unresolved_missing_days": [
                row["local_date"] for row in day_rows
                if row["wu_missing"] and not row["covered"]
            ],
            "unresolved_sparse_days": [
                row["local_date"] for row in day_rows
                if row["wu_sparse"] and not row["covered"]
            ],
            "days": day_rows,
        }
    return {
        "min_hourly_obs": int(min_hourly_obs),
        "markets": markets,
        "summary": {
            "markets_with_unresolved_gaps": sum(
                1 for row in markets.values() if row["unresolved_issue_days"]
            ),
            "unresolved_issue_days": sum(len(row["unresolved_issue_days"]) for row in markets.values()),
            "covered_issue_days": sum(row["covered_issue_days"] for row in markets.values()),
        },
    }


def audit_alerts(audits, gap_coverage=None):
    alerts = []
    coverage = (gap_coverage or {}).get("markets") or {}
    for market_id, result in (audits or {}).items():
        if not result:
            add_alert(alerts, "critical", market_id, "data_audit", "historical audit missing")
            continue
        coverage_row = coverage.get(market_id)
        if result.get("duplicate_timestamps"):
            add_alert(
                alerts,
                "critical",
                market_id,
                "data_audit",
                "duplicate historical timestamps",
                {"count": len(result["duplicate_timestamps"])},
            )
        if result.get("impossible_values"):
            add_alert(
                alerts,
                "critical",
                market_id,
                "data_audit",
                "impossible historical values",
                {"count": len(result["impossible_values"])},
            )
        if coverage_row is None:
            unresolved_missing = result.get("missing_days") or []
            unresolved_sparse = _issue_days(result, "sparse_days")
        else:
            unresolved_missing = coverage_row.get("unresolved_missing_days") or []
            unresolved_sparse = coverage_row.get("unresolved_sparse_days") or []
        if unresolved_missing:
            add_alert(
                alerts,
                "warning",
                market_id,
                "data_audit",
                "uncovered target-window historical missing days",
                {"count": len(unresolved_missing), "days": unresolved_missing[:20]},
            )
        if unresolved_sparse:
            add_alert(
                alerts,
                "warning",
                market_id,
                "data_audit",
                "uncovered target-window historical sparse days",
                {"count": len(unresolved_sparse), "days": unresolved_sparse[:20]},
            )
    return alerts


def collection_alerts(collection):
    alerts = []
    for row in (collection or {}).get("markets") or []:
        if row.get("action_required"):
            add_alert(
                alerts,
                "critical",
                row.get("market_id"),
                "collection",
                row.get("reason") or "collection needs attention",
                {"state": row.get("state"), "event_slug": row.get("event_slug")},
            )
    return alerts


def provenance_alerts(provenance):
    alerts = []
    for market_id, market in (provenance.get("markets") or {}).items():
        for kind, artifact in (market.get("artifacts") or {}).items():
            if not artifact.get("exists"):
                add_alert(alerts, "critical", market_id, "artifact", f"missing {kind} artifact")
            elif artifact.get("schema_status") != "ok":
                add_alert(
                    alerts,
                    "warning",
                    market_id,
                    "artifact",
                    f"{kind} artifact lacks internal schema metadata",
                    {"path": artifact.get("path"), "schema_status": artifact.get("schema_status")},
                )
    for kind, artifact in (provenance.get("family_artifacts") or {}).items():
        if not artifact.get("exists"):
            add_alert(alerts, "critical", "fleet", "artifact", f"missing {kind} artifact")
        elif artifact.get("schema_status") != "ok":
            add_alert(
                alerts,
                "warning",
                "fleet",
                "artifact",
                f"{kind} artifact lacks internal schema metadata",
                {"path": artifact.get("path"), "schema_status": artifact.get("schema_status")},
            )
    return alerts


def clob_summary(snapshots_root=DEFAULT_SNAPSHOTS_ROOT, now=None, max_gap_seconds=BOOK_AUDIT_MAX_GAP_SECONDS):
    """CLOB book-loop health plus the active-day book-tape cadence audit."""
    loop = clob_loop_health(read_clob_loop_status(), now=now)
    books = fleet_book_audit(
        snapshots_root=snapshots_root,
        now=now,
        max_gap_seconds=max_gap_seconds,
    )
    return {"loop": loop, "books": books}


def clob_alerts(clob):
    """Book capture is unbackfillable evidence, so failures alert like
    snapshot-collection failures: a dead recorder or a tape gap is critical."""
    alerts = []
    clob = clob or {}
    loop = clob.get("loop") or {}
    state = loop.get("state")
    loop_detail = {
        "state": state,
        "pid": loop.get("pid"),
        "heartbeat_age_seconds": loop.get("heartbeat_age_seconds"),
        "last_raw_books_age_seconds": loop.get("last_raw_books_age_seconds"),
        "last_derived_features_age_seconds": loop.get("last_derived_features_age_seconds"),
        "derived_feature_error_markets": loop.get("derived_feature_error_markets"),
        "last_error": loop.get("last_error"),
        "discovery_sanity": loop.get("discovery_sanity"),
    }
    if state in ("DEAD", "UNKNOWN", "ERRORING"):
        add_alert(alerts, "critical", "fleet", "clob", f"CLOB book loop is {state}", loop_detail)
    elif state in ("PAUSED", "DEGRADED"):
        add_alert(alerts, "warning", "fleet", "clob", f"CLOB book loop is {state}", loop_detail)
    discovery = loop.get("discovery_sanity") or {}
    if discovery and not discovery.get("ok", True):
        add_alert(
            alerts,
            "critical",
            "fleet",
            "clob",
            discovery.get("reason") or "CLOB discovery sanity gate failed",
            discovery,
        )
    loop_down = state not in ("RUNNING", "DEGRADED")
    for row in (clob.get("books") or {}).get("markets") or []:
        if row.get("ok"):
            continue
        detail = {
            "event_slug": row.get("event_slug"),
            "captures": row.get("captures"),
            "max_gap_seconds": row.get("max_gap_seconds"),
            "gaps_over_threshold": row.get("gaps_over_threshold"),
            "trailing_age_seconds": row.get("trailing_age_seconds"),
        }
        if loop_down and not row.get("captures"):
            # The loop-level critical already covers a fully missing tape.
            continue
        add_alert(
            alerts,
            "critical",
            row.get("market_id"),
            "clob",
            row.get("reason") or "book tape needs attention",
            detail,
        )
    return alerts


def observation_summary(status_path=OBSERVATION_STATUS_PATH, now=None):
    return watcher_health(read_observation_status(status_path), now=now)


def observation_alerts(observation):
    alerts = []
    observation = observation or {}
    state = observation.get("state")
    detail = {
        "state": state,
        "pid": observation.get("pid"),
        "heartbeat_age_seconds": observation.get("heartbeat_age_seconds"),
        "consecutive_errors": observation.get("consecutive_errors"),
        "last_error": observation.get("last_error"),
    }
    if state in ("DEAD", "UNKNOWN", "ERRORING"):
        add_alert(
            alerts,
            "critical",
            "fleet",
            "observation_trigger",
            f"observation trigger watcher is {state}",
            detail,
        )
    elif state in ("PAUSED", "DEGRADED"):
        add_alert(
            alerts,
            "warning",
            "fleet",
            "observation_trigger",
            f"observation trigger watcher is {state}",
            detail,
        )
    return alerts

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
