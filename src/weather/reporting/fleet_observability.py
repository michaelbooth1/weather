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
from datetime import datetime, timezone
from pathlib import Path

from weather.backtesting.settlement_io import DEFAULT_SNAPSHOTS_ROOT
from weather.reporting.formatting import markdown_table
from weather.collection.snapshot_tracker import SNAPSHOT_SUPERVISOR
from weather.collection.collection_health import fleet_collection_health
from weather.market.market_making_preflight import REMEDIATION_RULES
from weather.market.market_microstructure import (
    BOOK_AUDIT_MAX_GAP_SECONDS,
    CLOB_SUPERVISOR,
    clob_loop_health,
    fleet_book_audit,
    read_clob_loop_status,
)
from weather.market.market_registry import all_specs
from weather.operations.supervisor import jsonl_integrity, read_writer_lock
from weather.operations.observation_trigger import OBSERVATION_SUPERVISOR
from weather.operations.observation_trigger import STATUS_PATH as OBSERVATION_STATUS_PATH
from weather.operations.observation_trigger import read_status as read_observation_status
from weather.operations.observation_trigger import watcher_health
from weather.operations import tape_backup
from weather.artifacts import resolve_artifact_path
from weather.paths import relative_to_repo, data_path
from weather.reporting.data_auditor import MIN_HOURLY_OBS, audit_fleet_historical_data, jsonable_result
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
BROAD_SLO_VERIFY_COMMAND = (
    "python -m weather.reporting.fleet_observability report "
    "--out data/backtest/fleet_observability.json "
    "--report data/backtest/fleet_observability_report.md"
)
BROAD_SLO_REQUIRED_GATES = (
    "snapshot_coverage_gap",
    "latest_model_row_freshness",
    "source_status_freshness",
    "clob_book_freshness",
    "observation_trigger_health",
    "afternoon_window_coverage",
)
BROAD_SLO_RULES = {
    "snapshot_collection": {
        "root_cause": "snapshot_collection_blocked",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker status",
        "recoverable_same_day": True,
    },
    "snapshot_coverage_gap": {
        "root_cause": "snapshot_capture_gap",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker status",
        "recoverable_same_day": True,
    },
    "latest_model_row_freshness": {
        "root_cause": "stale_model_row",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker status",
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
    "afternoon_window_coverage": {
        "root_cause": "afternoon_window_incomplete",
        "owner": "weather snapshot/model loop",
        "suggested_command": "python -m weather.collection.snapshot_tracker status",
        "recoverable_same_day": True,
    },
    "clob_book_freshness": {
        "root_cause": "stale_clob_book_tape",
        "owner": "CLOB book supervisor",
        "suggested_command": "python -m weather.market.market_microstructure ensure",
        "recoverable_same_day": True,
    },
    "observation_trigger_health": {
        "root_cause": "watcher_stale",
        "owner": "observation-trigger supervisor",
        "suggested_command": "python -m weather.operations.observation_trigger ensure",
        "recoverable_same_day": True,
    },
}


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
        "last_error": loop.get("last_error"),
    }
    if state in ("DEAD", "UNKNOWN", "ERRORING"):
        add_alert(alerts, "critical", "fleet", "clob", f"CLOB book loop is {state}", loop_detail)
    elif state in ("PAUSED", "DEGRADED"):
        add_alert(alerts, "warning", "fleet", "clob", f"CLOB book loop is {state}", loop_detail)
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


def loop_artifact_integrity():
    rows = []

    def _repair_command(*paths):
        usable = [str(path) for path in paths if path]
        return "python -m weather.operations.loop_jsonl_repair repair " + " ".join(usable)

    for spec in (SNAPSHOT_SUPERVISOR, CLOB_SUPERVISOR, OBSERVATION_SUPERVISOR):
        status = {}
        status_path = Path(spec.status_path)
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            status = {}
        writer = read_writer_lock(spec.status_path)
        status_writer = status.get("status_writer") or {}
        active_pid = str(writer.get("pid")) if writer.get("exists") and writer.get("pid") is not None else None
        status_pid = str(status_writer.get("pid")) if status_writer.get("pid") is not None else None
        duplicate_writer = bool(active_pid and status_pid and active_pid != status_pid)
        diagnostics = jsonl_integrity(spec.diagnostics_path)
        console = jsonl_integrity(spec.console_log_path)
        malformed_lines = int(diagnostics.get("malformed_lines") or 0) + int(console.get("malformed_lines") or 0)
        malformed_samples = []
        for source, payload in (("diagnostics", diagnostics), ("console", console)):
            for sample in payload.get("examples") or []:
                malformed_samples.append({
                    "source": source,
                    "path": payload.get("path"),
                    **sample,
                })
        repair_paths = [
            payload.get("path")
            for payload in (diagnostics, console)
            if int(payload.get("malformed_lines") or 0)
        ]
        rows.append({
            "name": spec.name,
            "status_path": str(spec.status_path),
            "diagnostics_path": str(spec.diagnostics_path),
            "console_log_path": str(spec.console_log_path),
            "writer_lock": writer,
            "status_writer": status_writer,
            "duplicate_writer": duplicate_writer,
            "diagnostics_integrity": diagnostics,
            "console_integrity": console,
            "malformed_lines": malformed_lines,
            "malformed_samples": malformed_samples,
            "repair_command": _repair_command(*repair_paths) if repair_paths else None,
            "ok": malformed_lines == 0 and not duplicate_writer,
        })
    return {
        "schema_version": "loop_artifact_integrity_v0.1",
        "generated_at_utc": utc_now(),
        "rows": rows,
        "summary": {
            "loop_count": len(rows),
            "malformed_lines": sum(row["malformed_lines"] for row in rows),
            "duplicate_writer_count": sum(1 for row in rows if row.get("duplicate_writer")),
            "ok": all(row.get("ok") for row in rows),
        },
    }


def loop_integrity_alerts(integrity):
    alerts = []
    for row in (integrity or {}).get("rows") or []:
        if row.get("duplicate_writer"):
            add_alert(
                alerts,
                "critical",
                "fleet",
                "loop_integrity",
                f"{row.get('name')} status writer lock does not match status owner",
                {
                    "status_writer": row.get("status_writer"),
                    "writer_lock": row.get("writer_lock"),
                },
            )
        malformed = int(row.get("malformed_lines") or 0)
        if malformed:
            add_alert(
                alerts,
                "warning",
                "fleet",
                "loop_integrity",
                f"{row.get('name')} has {malformed} malformed JSONL/log lines",
                {
                    "diagnostics": row.get("diagnostics_integrity"),
                    "console": row.get("console_integrity"),
                    "samples": row.get("malformed_samples"),
                    "repair_command": row.get("repair_command"),
                },
            )
    return alerts


def _gate_from_alerts(name, alerts):
    if any(row.get("severity") == "critical" for row in alerts):
        severity = "critical"
    elif alerts:
        severity = "warning"
    else:
        severity = "ok"
    return {
        "name": name,
        "ok": not alerts,
        "severity": severity,
        "messages": [row.get("message") for row in alerts],
    }


def _broad_slo_rule(gate_name):
    rule = BROAD_SLO_RULES.get(gate_name) or REMEDIATION_RULES.get(gate_name) or {}
    return {
        "root_cause": rule.get("root_cause") or gate_name or "unknown_broad_slo_failure",
        "owner": rule.get("owner") or "unknown",
        "suggested_command": rule.get("suggested_command") or BROAD_SLO_VERIFY_COMMAND,
        "recoverable_same_day": bool(rule.get("recoverable_same_day", False)),
    }


def _recovery_row(component, gate, market, detail, before):
    rule = _broad_slo_rule(gate)
    return {
        "component": component,
        "gate": gate,
        "status": "BLOCK",
        "market_id": market.get("market_id") or "fleet",
        "event_slug": market.get("event_slug"),
        "target_date": market.get("target_date"),
        "owner": rule["owner"],
        "root_cause": rule["root_cause"],
        "repair_command": rule["suggested_command"],
        "suggested_command": rule["suggested_command"],
        "recoverable_same_day": rule["recoverable_same_day"],
        "before": before,
        "after": "rerun broad live-forward SLO and require PASS before broad countability",
        "verification_command": BROAD_SLO_VERIFY_COMMAND,
        "detail": detail,
    }


def _unique_gates(gates):
    seen = set()
    ordered = []
    for gate in gates:
        if gate in seen:
            continue
        seen.add(gate)
        ordered.append(gate)
    return ordered


def _collection_recovery_gates(row):
    reason = str(row.get("reason") or "").lower()
    gates = []
    if not row.get("snapshots") or "no snapshot" in reason or "no captures" in reason:
        gates.append("snapshot_collection")
    if "gap" in reason:
        gates.append("snapshot_coverage_gap")
    if "afternoon window" in reason or "window close" in reason or "window start" in reason:
        gates.append("afternoon_window_coverage")
    if "latest capture" in reason:
        gates.append("latest_model_row_freshness")
    if not gates:
        gates.append("snapshot_collection")
    return _unique_gates(gates)


def _source_status_recovery_detail(source_status):
    if not source_status:
        return None
    if source_status.get("available") is False:
        return source_status.get("reason") or "source_status_long.csv unavailable"
    if source_status.get("trading_evidence_allowed") is False:
        families = source_status.get("families") or {}
        affected = [
            name
            for name, row in sorted(families.items())
            if row.get("status") != "healthy"
        ]
        if affected:
            return "source-status degraded families: " + ", ".join(affected)
        return "source-status degradation blocks trading-grade broad evidence"
    return None


def _collection_recovery_rows(collection):
    rows = []
    for row in (collection or {}).get("markets") or []:
        if row.get("action_required"):
            before = (
                f"state={row.get('state')}; snapshots={row.get('snapshots')}; "
                f"latest_age_minutes={row.get('latest_age_minutes')}; reason={row.get('reason')}"
            )
            for gate in _collection_recovery_gates(row):
                rows.append(_recovery_row(
                    "snapshot_collection",
                    gate,
                    row,
                    row.get("reason") or "snapshot collection needs attention",
                    before,
                ))
        source_detail = _source_status_recovery_detail(row.get("source_family_degradation") or {})
        if source_detail:
            before = (
                f"snapshot_id={(row.get('source_family_degradation') or {}).get('snapshot_id')}; "
                f"affected_family_count={(row.get('source_family_degradation') or {}).get('affected_family_count')}; "
                f"failed_source_count={(row.get('source_family_degradation') or {}).get('failed_source_count')}; "
                f"fallback_source_count={(row.get('source_family_degradation') or {}).get('fallback_source_count')}"
            )
            rows.append(_recovery_row(
                "source_status",
                "source_status_freshness",
                row,
                source_detail,
                before,
            ))
    return rows


def _clob_recovery_rows(clob):
    rows = []
    clob = clob or {}
    loop = clob.get("loop") or {}
    state = loop.get("state")
    if state in ("DEAD", "UNKNOWN", "ERRORING", "PAUSED", "DEGRADED"):
        rows.append(_recovery_row(
            "clob_book_capture",
            "clob_book_freshness",
            {"market_id": "fleet"},
            f"CLOB book loop is {state}",
            (
                f"state={state}; heartbeat_age_seconds={loop.get('heartbeat_age_seconds')}; "
                f"last_books_age_seconds={loop.get('last_books_age_seconds')}; last_error={loop.get('last_error')}"
            ),
        ))
    for row in (clob.get("books") or {}).get("markets") or []:
        if row.get("ok"):
            continue
        rows.append(_recovery_row(
            "clob_book_capture",
            "clob_book_freshness",
            row,
            row.get("reason") or "CLOB book tape needs attention",
            (
                f"captures={row.get('captures')}; trailing_age_seconds={row.get('trailing_age_seconds')}; "
                f"gaps_over_threshold={row.get('gaps_over_threshold')}; max_gap_seconds={row.get('max_gap_seconds')}"
            ),
        ))
    return rows


def _observation_recovery_rows(observation):
    alerts = observation_alerts(observation)
    if not alerts:
        return []
    observation = observation or {}
    return [
        _recovery_row(
            "observation_trigger",
            "observation_trigger_health",
            {"market_id": "fleet"},
            alerts[0].get("message") or "observation trigger watcher needs attention",
            (
                f"state={observation.get('state')}; heartbeat_age_seconds={observation.get('heartbeat_age_seconds')}; "
                f"consecutive_errors={observation.get('consecutive_errors')}; last_error={observation.get('last_error')}"
            ),
        )
    ]


def broad_live_forward_recovery_rows(collection, clob, observation):
    return (
        _collection_recovery_rows(collection)
        + _clob_recovery_rows(clob)
        + _observation_recovery_rows(observation)
    )


def _concrete_broad_slo_gates(recovery_rows):
    counts = Counter(row.get("gate") for row in recovery_rows if row.get("gate"))
    gate_names = list(BROAD_SLO_REQUIRED_GATES)
    gate_names.extend(sorted(name for name in counts if name not in BROAD_SLO_REQUIRED_GATES))
    rows_by_gate = {}
    for row in recovery_rows:
        rows_by_gate.setdefault(row.get("gate"), []).append(row)
    gates = []
    for gate_name in gate_names:
        rows = rows_by_gate.get(gate_name) or []
        gates.append({
            "name": gate_name,
            "ok": not rows,
            "severity": "critical" if rows else "ok",
            "messages": [row.get("detail") for row in rows],
            "blocked_market_count": len({row.get("market_id") for row in rows}),
            "owner": (rows[0].get("owner") if rows else _broad_slo_rule(gate_name)["owner"]),
            "repair_command": (rows[0].get("repair_command") if rows else None),
        })
    return gates


def _broad_slo_summary(recovery_rows):
    first = recovery_rows[0] if recovery_rows else {}
    return {
        "recovery_row_count": len(recovery_rows),
        "first_blocking_market": first.get("market_id"),
        "first_blocking_component": first.get("component"),
        "first_blocking_gate": first.get("gate"),
        "first_blocking_owner": first.get("owner"),
        "first_repair_command": first.get("repair_command"),
        "blocking_gate_counts": dict(sorted(Counter(row.get("gate") for row in recovery_rows).items())),
        "blocking_component_counts": dict(sorted(Counter(row.get("component") for row in recovery_rows).items())),
    }


def live_forward_slo_gate(collection, clob, observation):
    """Single fail-closed gate for live-forward MM evidence.

    A paper/live day can count only when the slow weather snapshot tape, fast
    CLOB book tape, and observation-trigger watcher are all fresh and gap-free.
    """
    gates = [
        _gate_from_alerts("snapshot_collection", collection_alerts(collection)),
        _gate_from_alerts("clob_book_capture", clob_alerts(clob)),
        _gate_from_alerts("observation_trigger", observation_alerts(observation)),
    ]
    recovery_rows = broad_live_forward_recovery_rows(collection, clob, observation)
    concrete_gates = _concrete_broad_slo_gates(recovery_rows)
    blockers = [
        message
        for gate in gates
        if not gate["ok"]
        for message in gate.get("messages") or []
    ]
    source_status_blockers = [
        row.get("detail")
        for row in recovery_rows
        if row.get("component") == "source_status"
    ]
    blockers.extend([detail for detail in source_status_blockers if detail not in blockers])
    ok = not blockers and not recovery_rows
    first_blocker = recovery_rows[0] if recovery_rows else {}
    reason = (
        "all broad live-forward gates are countable"
        if ok
        else (
            f"{first_blocker.get('gate')} blocks broad live-forward SLO for "
            f"{first_blocker.get('market_id')}: {first_blocker.get('detail')}"
            if first_blocker
            else "; ".join(blockers[:3])
        )
    )
    return {
        "schema_version": "live_forward_slo_v0.1",
        "status": "PASS" if ok else "BLOCK",
        "ok": ok,
        "counts_toward_live_forward_gate": ok,
        "reason": reason,
        "gates": gates,
        "concrete_gates": concrete_gates,
        "blockers": blockers,
        "first_blocker": first_blocker,
        "recovery_checklist": recovery_rows,
        "rerun_command": BROAD_SLO_VERIFY_COMMAND,
        "summary": _broad_slo_summary(recovery_rows),
    }


def mm_paper_evidence_summary(path=DEFAULT_MM_PAPER_REPORT):
    path = Path(path)
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "by_class": {},
            "credit_rows": [],
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {
            "exists": False,
            "path": str(path),
            "load_error": "unreadable mm paper report",
            "by_class": {},
            "credit_rows": [],
        }
    by_class = ((payload.get("summary") or {}).get("per_market_live_forward_evidence") or {})
    return {
        "exists": True,
        "path": str(path),
        "generated_at_utc": payload.get("generated_at_utc"),
        "by_class": by_class,
        "credit_rows": payload.get("per_market_evidence_credits") or [],
    }


def settled_day_freshness_summary(path=DEFAULT_SETTLED_DAY_FRESHNESS):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path), "status": "missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {"exists": False, "path": str(path), "status": "unreadable"}
    return {
        "exists": True,
        "path": str(path),
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "summary": payload.get("summary") or {},
        "repair_command": payload.get("repair_command"),
        "replay_status_repair_command": payload.get("replay_status_repair_command"),
    }


def settled_day_freshness_alerts(freshness):
    if not freshness or not freshness.get("exists"):
        return []
    status = freshness.get("status")
    if status not in {"FAIL", "WARN"}:
        return []
    summary = freshness.get("summary") or {}
    severity = "critical" if status == "FAIL" else "warning"
    commands = [
        command
        for command in [
            freshness.get("repair_command"),
            freshness.get("replay_status_repair_command"),
        ]
        if command
    ]
    return [{
        "severity": severity,
        "market_id": "fleet",
        "category": "settled_day_freshness",
        "message": (
            f"settled-day freshness {status} for {freshness.get('target_date')}: "
            f"{summary.get('incomplete_market_count')} incomplete market(s)"
        ),
        "detail": {
            "summary": summary,
            "repair_commands": commands,
            "path": freshness.get("path"),
        },
    }]


def trust_readiness(trust_rows, min_trust=DEFAULT_MIN_TRUST, min_days=DEFAULT_MIN_SETTLED_DAYS):
    rows = {}
    for row in trust_rows:
        rows[row["market"]] = {
            **row,
            "min_trust_score": min_trust,
            "min_settled_days": min_days,
            "trust_gap": max(0, int(min_trust) - int(row.get("trust_score") or 0)),
            "settled_day_gap": max(0, int(min_days) - int(row.get("settled_days") or 0)),
        }
    return rows


def overall_status(alerts):
    if any(row.get("severity") == "critical" for row in alerts):
        return "CRITICAL"
    if any(row.get("severity") == "warning" for row in alerts):
        return "WARN"
    return "OK"


def build_observability_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    target_month=None,
    target_day=None,
    years=None,
    include_audits=True,
    tape_backup_root=tape_backup.DEFAULT_BACKUP_ROOT,
    verify_tape_backup_checksums=False,
):
    collection = fleet_collection_health(
        snapshots_root=snapshots_root,
        interval_minutes=interval_minutes,
        tolerance=tolerance,
        live=True,
    )
    audits = (
        audit_fleet_historical_data(
            target_month=target_month,
            target_day=target_day,
            years=years,
            quiet=True,
        )
        if include_audits else {}
    )
    audits_json = {
        market_id: jsonable_result(result)
        for market_id, result in audits.items()
    }
    provenance = artifact_inventory()
    gap_coverage = historical_gap_coverage(audits_json) if include_audits else {}
    trust = trust_readiness(score_all_markets(root=snapshots_root))
    clob = clob_summary(snapshots_root=snapshots_root)
    observation = observation_summary()
    loop_integrity = loop_artifact_integrity()
    live_forward_slo = live_forward_slo_gate(collection, clob, observation)
    mm_paper_evidence = mm_paper_evidence_summary()
    settled_freshness = settled_day_freshness_summary()
    tape_backup_status = tape_backup.backup_status(
        backup_root=tape_backup_root,
        verify_checksums=verify_tape_backup_checksums,
    )
    alerts = []
    alerts.extend(collection_alerts(collection))
    alerts.extend(audit_alerts(audits_json, gap_coverage=gap_coverage))
    alerts.extend(provenance_alerts(provenance))
    alerts.extend(clob_alerts(clob))
    alerts.extend(observation_alerts(observation))
    alerts.extend(loop_integrity_alerts(loop_integrity))
    alerts.extend(settled_day_freshness_alerts(settled_freshness))
    alerts.extend(tape_backup.backup_alerts(tape_backup_status))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": overall_status(alerts),
        "snapshots_root": str(snapshots_root),
        "collection": collection,
        "historical_audits": audits_json,
        "historical_gap_coverage": gap_coverage,
        "artifact_provenance": provenance,
        "trust_readiness": trust,
        "clob": clob,
        "observation_trigger": observation,
        "loop_integrity": loop_integrity,
        "live_forward_slo": live_forward_slo,
        "mm_paper_evidence": mm_paper_evidence,
        "settled_day_freshness": settled_freshness,
        "tape_backup": tape_backup_status,
        "alerts": alerts,
        "summary": {
            "market_count": len(collection.get("markets") or []),
            "critical_alerts": sum(1 for row in alerts if row.get("severity") == "critical"),
            "warning_alerts": sum(1 for row in alerts if row.get("severity") == "warning"),
            "live_forward_slo_status": live_forward_slo.get("status"),
            "mm_paper_model_review_countable_markets": (
                (mm_paper_evidence.get("by_class") or {})
                .get("model_review_evidence", {})
                .get("countable_market_count")
            ),
            "mm_paper_paper_trading_countable_markets": (
                (mm_paper_evidence.get("by_class") or {})
                .get("paper_trading_evidence", {})
                .get("countable_market_count")
            ),
            "tape_backup_status": tape_backup_status.get("status"),
            "loop_integrity_status": "OK" if (loop_integrity.get("summary") or {}).get("ok") else "WARN",
        },
    }
    return payload


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_markdown(path, payload):
    collection_rows = []
    trust = payload.get("trust_readiness") or {}
    for row in (payload.get("collection") or {}).get("markets") or []:
        trust_row = trust.get(row["market_id"]) or {}
        collection_rows.append([
            row["market_id"],
            row.get("state"),
            row.get("snapshots"),
            row.get("reason"),
            trust_row.get("trust_score"),
            trust_row.get("settled_days"),
            trust_row.get("trust_gap"),
            trust_row.get("settled_day_gap"),
        ])
    audit_rows = []
    gap_coverage = (payload.get("historical_gap_coverage") or {}).get("markets") or {}
    for market_id, audit in sorted((payload.get("historical_audits") or {}).items()):
        coverage_row = gap_coverage.get(market_id) or {}
        audit_rows.append([
            market_id,
            len(audit.get("missing_days") or []) if audit else "-",
            len(audit.get("sparse_days") or []) if audit else "-",
            coverage_row.get("covered_issue_days", "-"),
            len(coverage_row.get("unresolved_issue_days") or []),
            len(audit.get("duplicate_timestamps") or []) if audit else "-",
            len(audit.get("impossible_values") or []) if audit else "-",
            audit.get("hourly_days_audited") if audit else "-",
        ])
    artifact_rows = []
    provenance = payload.get("artifact_provenance") or {}
    for market_id, market in sorted((provenance.get("markets") or {}).items()):
        artifacts = market.get("artifacts") or {}
        artifact_rows.append([
            market_id,
            sum(1 for item in artifacts.values() if item.get("exists")),
            sum(1 for item in artifacts.values() if item.get("schema_status") == "ok"),
            sum(1 for item in artifacts.values() if item.get("schema_status") != "ok"),
        ])
    alert_rows = [
        [
            row.get("severity"),
            row.get("market_id"),
            row.get("category"),
            row.get("message"),
        ]
        for row in payload.get("alerts") or []
    ]
    lines = [
        "# Fleet Observability Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        f"Critical alerts: `{(payload.get('summary') or {}).get('critical_alerts')}`",
        f"Warning alerts: `{(payload.get('summary') or {}).get('warning_alerts')}`",
        "",
        "## Collection And Trust",
        "",
    ]
    lines += markdown_table(
        ["Market", "State", "Snapshots", "Reason", "Trust", "Days", "Trust Gap", "Day Gap"],
        collection_rows,
    )
    lines += ["", "## Historical Data Audits", ""]
    lines += markdown_table(
        [
            "Market", "WU Missing", "WU Sparse", "Redundant Covered",
            "Unresolved", "Duplicates", "Impossible", "Hourly Days",
        ],
        audit_rows,
    )
    lines += ["", "## Artifact Provenance", ""]
    lines += markdown_table(
        ["Market", "Artifacts", "Internal Schema OK", "Needs Schema/Manifest Attention"],
        artifact_rows,
    )
    clob = payload.get("clob") or {}
    clob_loop = clob.get("loop") or {}
    clob_rows = [
        [
            row.get("market_id"),
            "OK" if row.get("ok") else "GAP",
            row.get("captures"),
            row.get("median_gap_seconds"),
            row.get("max_gap_seconds"),
            row.get("startup_gaps_ignored") or 0,
            row.get("trailing_age_seconds"),
            row.get("reason") or "-",
        ]
        for row in (clob.get("books") or {}).get("markets") or []
    ]
    lines += [
        "",
        "## CLOB Book Capture",
        "",
        f"Loop state: **{clob_loop.get('state')}** "
        f"(heartbeat age {clob_loop.get('heartbeat_age_seconds')}s, "
        f"last books age {clob_loop.get('last_books_age_seconds')}s)",
        "",
    ]
    lines += markdown_table(
        ["Market", "Tape", "Captures", "Median Gap s", "Max Gap s", "Startup Ignored", "Trailing s", "Reason"],
        clob_rows,
    )
    observation = payload.get("observation_trigger") or {}
    live_forward_slo = payload.get("live_forward_slo") or {}
    slo_rows = [
        [
            row.get("name"),
            "PASS" if row.get("ok") else "BLOCK",
            row.get("severity"),
            "; ".join(row.get("messages") or []) or "ok",
        ]
        for row in live_forward_slo.get("gates") or []
    ]
    concrete_slo_rows = [
        [
            row.get("name"),
            "PASS" if row.get("ok") else "BLOCK",
            row.get("blocked_market_count"),
            row.get("owner") or "-",
            row.get("repair_command") or "-",
            "; ".join(row.get("messages") or []) or "ok",
        ]
        for row in live_forward_slo.get("concrete_gates") or []
    ]
    recovery_rows = [
        [
            row.get("market_id"),
            row.get("component"),
            row.get("gate"),
            row.get("owner"),
            row.get("before"),
            row.get("repair_command"),
            row.get("verification_command"),
            row.get("after"),
        ]
        for row in live_forward_slo.get("recovery_checklist") or []
    ]
    first_slo_blocker = live_forward_slo.get("first_blocker") or {}
    lines += [
        "",
        "## Live-Forward SLO Gate",
        "",
        f"Status: **{live_forward_slo.get('status')}**",
        f"Counts toward live-forward gate: `{live_forward_slo.get('counts_toward_live_forward_gate')}`",
        f"Reason: {live_forward_slo.get('reason') or '-'}",
        f"Observation watcher: **{observation.get('state')}** "
        f"(heartbeat age {observation.get('heartbeat_age_seconds')}s)",
        "",
    ]
    lines += markdown_table(
        ["Gate", "Verdict", "Severity", "Detail"],
        slo_rows,
    )
    lines += ["", "### Broad Recovery Gates", ""]
    lines += markdown_table(
        ["Concrete Gate", "Verdict", "Blocked Markets", "Owner", "Repair Command", "Detail"],
        concrete_slo_rows,
    )
    lines += [
        "",
        "### Broad Recovery Checklist",
        "",
        f"First blocker: `{first_slo_blocker.get('market_id') or '-'}` "
        f"`{first_slo_blocker.get('component') or '-'}` "
        f"`{first_slo_blocker.get('gate') or '-'}`",
        f"First repair command: `{first_slo_blocker.get('repair_command') or '-'}`",
        f"Rerun command: `{live_forward_slo.get('rerun_command') or BROAD_SLO_VERIFY_COMMAND}`",
        "",
    ]
    lines += markdown_table(
        ["Market", "Component", "Gate", "Owner", "Before", "Repair Command", "Verification", "After"],
        recovery_rows,
    )
    mm_paper = payload.get("mm_paper_evidence") or {}
    mm_classes = mm_paper.get("by_class") or {}
    if mm_classes:
        lines += [
            "",
            "## Per-Market MM Paper Evidence",
            "",
            f"Source: `{mm_paper.get('path')}`",
            "",
        ]
        lines += markdown_table(
            ["Evidence Class", "Countable", "Blocked", "All Selected Count", "First Blocked", "Owner"],
            [
                [
                    evidence_class,
                    row.get("countable_market_count"),
                    row.get("blocked_market_count"),
                    row.get("all_selected_markets_count"),
                    row.get("first_blocked_market") or "-",
                    row.get("first_blocked_owner") or "-",
                ]
                for evidence_class, row in sorted(mm_classes.items())
            ],
        )
    loop_integrity = payload.get("loop_integrity") or {}
    integrity_rows = [
        [
            row.get("name"),
            "OK" if row.get("ok") else "CHECK",
            row.get("malformed_lines"),
            row.get("duplicate_writer"),
            (row.get("writer_lock") or {}).get("pid") or "-",
            (row.get("status_writer") or {}).get("pid") or "-",
            row.get("repair_command") or "-",
        ]
        for row in loop_integrity.get("rows") or []
    ]
    sample_rows = []
    for row in loop_integrity.get("rows") or []:
        for sample in row.get("malformed_samples") or []:
            sample_rows.append([
                row.get("name"),
                sample.get("source"),
                sample.get("path"),
                sample.get("line"),
                sample.get("classification"),
                sample.get("text"),
            ])
    lines += [
        "",
        "## Loop Artifact Integrity",
        "",
        f"Malformed lines: `{(loop_integrity.get('summary') or {}).get('malformed_lines')}`",
        f"Duplicate writers: `{(loop_integrity.get('summary') or {}).get('duplicate_writer_count')}`",
        "",
    ]
    lines += markdown_table(
        ["Loop", "Status", "Malformed Lines", "Duplicate Writer", "Lock PID", "Status PID", "Repair Command"],
        integrity_rows,
    )
    if sample_rows:
        lines += ["", "### Malformed Line Samples", ""]
        lines += markdown_table(
            ["Loop", "Source", "Path", "Line", "Class", "Sample"],
            sample_rows[:12],
        )
    backup = payload.get("tape_backup") or {}
    restore = backup.get("last_restore_drill") or {}
    backup_rows = [
        ["Status", backup.get("status")],
        ["Backup root", backup.get("backup_root")],
        ["Manifest age hours", backup.get("age_hours")],
        ["Files", backup.get("file_count")],
        ["Missing critical classes", ", ".join(backup.get("missing_critical_classes") or []) or "-"],
        ["Checksum failures", len(backup.get("checksum_failures") or [])],
        ["Restore SLA", backup.get("restore_drill_sla_status") or "-"],
        ["Restore SLA detail", backup.get("restore_drill_sla_detail") or "-"],
        ["Last restore drill", restore.get("status") or "-"],
        ["Restore generated", restore.get("generated_at_utc") or "-"],
    ]
    lines += ["", "## Tape Backup And Restore", ""]
    lines += markdown_table(["Metric", "Value"], backup_rows)
    lines += ["", "## Alerts", ""]
    lines += markdown_table(
        ["Severity", "Market", "Category", "Message"],
        alert_rows,
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def cmd_report(args):
    years = [int(item) for item in args.years.split(",") if item.strip()] if args.years else None
    payload = build_observability_payload(
        snapshots_root=Path(args.snapshots_root),
        interval_minutes=args.interval_minutes,
        tolerance=args.tolerance,
        target_month=args.target_month,
        target_day=args.target_day,
        years=years,
        include_audits=not args.skip_audits,
        tape_backup_root=args.tape_backup_root,
        verify_tape_backup_checksums=args.verify_tape_backup_checksums,
    )
    json_path = write_json(args.out, payload)
    report_path = write_markdown(args.report, payload)
    provenance_path = write_json(args.provenance_out, payload["artifact_provenance"])
    print(f"Fleet observability: {payload['status']}")
    print(f"Wrote JSON to {json_path}")
    print(f"Wrote report to {report_path}")
    print(f"Wrote artifact provenance manifest to {provenance_path}")
    if args.strict and payload["status"] == "CRITICAL":
        sys.exit(2)


def build_parser():
    parser = argparse.ArgumentParser(description="Build fleet data-integrity and observability reports.")
    sub = parser.add_subparsers(dest="command", required=True)
    report = sub.add_parser("report")
    report.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    report.add_argument("--interval-minutes", type=float, default=10.0)
    report.add_argument("--tolerance", type=float, default=1.5)
    report.add_argument("--target-month", type=int, default=None)
    report.add_argument("--target-day", type=int, default=None)
    report.add_argument("--years", default="", help="Comma-separated audit years; default 2000-2025.")
    report.add_argument("--skip-audits", action="store_true")
    report.add_argument("--tape-backup-root", default=str(tape_backup.DEFAULT_BACKUP_ROOT))
    report.add_argument("--verify-tape-backup-checksums", action="store_true")
    report.add_argument("--strict", action="store_true", help="Exit 2 when critical alerts are present.")
    report.add_argument("--out", default=str(DEFAULT_JSON_OUT))
    report.add_argument("--report", default=str(DEFAULT_REPORT))
    report.add_argument("--provenance-out", default=str(DEFAULT_PROVENANCE_OUT))
    report.set_defaults(func=cmd_report)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
