"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

import json
from datetime import datetime, timezone
from pathlib import Path

from weather.reporting.fleet.fleet_observability_gates import *  # noqa: F403
from weather.operations.closed_market_day_archive import DEFAULT_INCREMENTAL_JSON
from weather.operations import event_metadata_validation
from weather.reporting.market.trading_evidence import (
    DEFAULT_MM_RUNS_ROOT,
    DEFAULT_TAKER_RUNS_ROOT,
    build_trading_evidence_summary,
    mm_evidence_starvation_summary,
)
from weather.reporting.serving_gates.runtime_identity_evidence import build_runtime_identity_evidence
from weather.operations.storage_classes import CANONICAL_EVIDENCE, delete_gate_for_storage_class

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.


def mm_evidence_starvation_alerts(starvation):
    alert = (starvation or {}).get("critical_alert") or {}
    if not alert:
        return []
    detail = alert.get("detail") or {}
    return [{
        "severity": "critical",
        "market_id": "fleet",
        "category": "mm_evidence_starvation",
        "message": alert.get("message"),
        "detail": detail,
    }]


def runtime_identity_target_date(collection):
    dates = [
        str(row.get("target_date"))
        for row in (collection or {}).get("markets") or []
        if row.get("target_date")
    ]
    if not dates:
        return None
    counts = Counter(dates)
    return sorted(counts.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)[0][0]


def runtime_identity_alerts(evidence):
    if not evidence or evidence.get("status") != "BLOCK":
        return []
    return [{
        "severity": "warning",
        "market_id": "fleet",
        "category": "runtime_identity",
        "message": (
            "mixed runtime identities block unsegmented model and promotion evidence "
            f"for {evidence.get('target_date') or 'selected snapshots'}"
        ),
        "detail": {
            "blocking_reason": evidence.get("blocking_reason"),
            "runtime_identity_count": evidence.get("runtime_identity_count"),
            "snapshot_row_count": evidence.get("snapshot_row_count"),
            "reconciliation_status": evidence.get("reconciliation_status"),
        },
    }]


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


def _short_timestamp(value):
    if value in (None, ""):
        return "-"
    try:
        parsed = datetime.fromisoformat(str(value))
        return f"{parsed:%H:%M}"
    except ValueError:
        return str(value)


def _format_gap_windows(windows, limit=2):
    rows = []
    for item in (windows or [])[:limit]:
        rows.append(
            f"{_short_timestamp(item.get('after'))}->{_short_timestamp(item.get('before'))} "
            f"({float(item.get('gap_minutes') or 0):.0f}m)"
        )
    if len(windows or []) > limit:
        rows.append("...")
    return "; ".join(rows) or "-"


def _format_source_family_detail(families, limit=2):
    rows = []
    for item in (families or [])[:limit]:
        bits = [
            f"{item.get('family')}:{item.get('status')}",
            f"failed={item.get('failed_source_count', 0)}",
            f"fallback={item.get('fallback_source_count', 0)}",
            f"rate_limited={item.get('rate_limited_source_count', 0)}",
            f"expected={item.get('expected_unavailable_source_count', 0)}",
            f"cooldown={item.get('provider_cooldown_source_count', 0)}",
        ]
        cache_states = item.get("top_cache_states") or {}
        if cache_states:
            bits.append("cache=" + ",".join(f"{key}:{value}" for key, value in sorted(cache_states.items())))
        if item.get("max_retry_after_seconds") is not None:
            bits.append(f"retry_after={item.get('max_retry_after_seconds')}s")
        if item.get("max_cache_age_minutes") is not None:
            bits.append(f"cache_age={item.get('max_cache_age_minutes')}m")
        rows.append(" ".join(bits))
    if len(families or []) > limit:
        rows.append("...")
    return "; ".join(rows) or "-"


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


def cleanup_deletion_gate_summary(tape_backup_status):
    canonical_gate = delete_gate_for_storage_class(CANONICAL_EVIDENCE, tape_backup_status or {})
    return {
        "status": "PASS" if canonical_gate.get("status") == "PASS" else "BLOCK",
        "canonical_evidence": canonical_gate,
        "delete_permission": canonical_gate.get("delete_permission"),
        "missing_critical_files": canonical_gate.get("missing_critical_files"),
        "missing_critical_bytes": canonical_gate.get("missing_critical_bytes"),
        "missing_samples": canonical_gate.get("missing_samples") or [],
    }


def _parse_utc_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_hours_since(value, *, now=None):
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return round((now - parsed).total_seconds() / 3600.0, 3)


def _status_cache_error(path, status, detail, *, backup_root):
    return {
        "status": status,
        "backup_root": str(backup_root),
        "status_cache_path": str(path),
        "status_cache_loaded": False,
        "status_cache_detail": detail,
        "missing_critical_classes": [],
        "missing_critical_files": 0,
        "missing_critical_bytes": 0,
        "checksum_failures": [],
        "last_restore_drill": {},
    }


def cached_tape_backup_status(
    status_path=tape_backup.DEFAULT_STATUS_OUT,
    *,
    backup_root=tape_backup.DEFAULT_BACKUP_ROOT,
    max_age_hours=26.0,
    max_restore_age_hours=168.0,
    now=None,
):
    """Read the generated tape-backup status without rescanning the mirror.

    The full tape backup status audit can parse a large manifest and walk the
    local backup mirror. Fleet observability needs the latest generated status
    to stay visible, but it should not redo that audit on every report run.
    """
    path = Path(status_path)
    if not path.exists():
        return _status_cache_error(
            path,
            "MISSING_STATUS_CACHE",
            "status cache does not exist",
            backup_root=backup_root,
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _status_cache_error(
            path,
            "UNREADABLE_STATUS_CACHE",
            str(exc),
            backup_root=backup_root,
        )
    if not isinstance(payload, dict):
        return _status_cache_error(
            path,
            "UNREADABLE_STATUS_CACHE",
            "status cache is not a JSON object",
            backup_root=backup_root,
        )

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = dict(payload)
    status["status_cache_path"] = str(path)
    status["status_cache_loaded"] = True
    try:
        status["status_cache_mtime_utc"] = datetime.fromtimestamp(
            path.stat().st_mtime,
            timezone.utc,
        ).isoformat()
    except OSError:
        status["status_cache_mtime_utc"] = None
    status["max_age_hours"] = max_age_hours
    status["max_restore_age_hours"] = max_restore_age_hours
    if not status.get("backup_root"):
        status["backup_root"] = str(backup_root)

    age_hours = _age_hours_since(status.get("generated_at_utc"), now=now)
    if age_hours is not None:
        status["age_hours"] = age_hours

    restore = dict(status.get("last_restore_drill") or {})
    restore_age = _age_hours_since(restore.get("generated_at_utc"), now=now)
    if restore_age is not None:
        restore["age_hours"] = restore_age
    status["last_restore_drill"] = restore
    restore_status, restore_detail = tape_backup.restore_drill_sla_status(
        restore,
        manifest_hash_value=status.get("manifest_hash"),
        max_restore_age_hours=max_restore_age_hours,
    )
    status["restore_drill_sla_status"] = restore_status
    status["restore_drill_sla_detail"] = restore_detail

    base_status = status.get("status") or "UNKNOWN"
    generated_stale = age_hours is not None and age_hours > float(max_age_hours)
    recomputable_states = {
        "OK",
        "STALE",
        "RESTORE_DRILL_MISSING",
        "RESTORE_DRILL_FAIL",
        "RESTORE_DRILL_STALE",
    }
    if base_status in recomputable_states:
        if generated_stale:
            status["status"] = "STALE"
        elif restore_status != "OK":
            status["status"] = restore_status
        else:
            status["status"] = "OK"
    return status


def tape_backup_status_summary(
    *,
    backup_root=tape_backup.DEFAULT_BACKUP_ROOT,
    status_path=tape_backup.DEFAULT_STATUS_OUT,
    refresh=False,
    verify_checksums=False,
    max_age_hours=26.0,
    max_restore_age_hours=168.0,
):
    if refresh or verify_checksums:
        status = tape_backup.backup_status(
            backup_root=backup_root,
            max_age_hours=max_age_hours,
            verify_checksums=verify_checksums,
            max_restore_age_hours=max_restore_age_hours,
        )
        status["status_cache_loaded"] = False
        status["status_cache_path"] = str(status_path)
        return status
    return cached_tape_backup_status(
        status_path,
        backup_root=backup_root,
        max_age_hours=max_age_hours,
        max_restore_age_hours=max_restore_age_hours,
    )


def parquet_incremental_status(path=DEFAULT_INCREMENTAL_JSON):
    path = Path(path)
    if not path.exists():
        return {"exists": False, "path": str(path), "status": "missing", "summary": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "exists": False,
            "path": str(path),
            "status": "unreadable",
            "load_error": str(exc),
            "summary": {},
        }
    summary = payload.get("summary") or {}
    return {
        "exists": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "mode": payload.get("mode"),
        "summary": summary,
        "blocker_counts": payload.get("blocker_counts") or {},
        "family_status_counts": payload.get("family_status_counts") or {},
        "backlog_by_market": payload.get("backlog_by_market") or [],
        "remaining_scan_backlog": summary.get("remaining_scan_backlog"),
        "failed": summary.get("failed"),
        "blocked": summary.get("blocked"),
    }


def parquet_incremental_alerts(status):
    if not status or status.get("status") in {None, "missing"}:
        return []
    if status.get("status") == "BLOCK" or int(status.get("failed") or 0) > 0:
        return [{
            "severity": "warning",
            "market_id": "fleet",
            "category": "closed_day_parquet_incremental",
            "message": "closed-day parquet incremental conversion has failures",
            "detail": {
                "path": status.get("path"),
                "summary": status.get("summary") or {},
                "blocker_counts": status.get("blocker_counts") or {},
            },
        }]
    return []


def event_metadata_validation_summary(path=None):
    path = Path(path or event_metadata_validation.DEFAULT_JSON_OUT)
    payload = event_metadata_validation.load_validation_payload(path)
    if not payload:
        return {
            "exists": False,
            "path": str(path),
            "status": "missing",
            "summary": {},
        }
    return {
        "exists": True,
        "path": str(path),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "target_date": payload.get("target_date"),
        "validation_hash": payload.get("validation_hash"),
        "summary": payload.get("summary") or {},
        "validation_command": payload.get("validation_command"),
        "refresh_command": payload.get("refresh_command"),
    }


def build_observability_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    target_month=None,
    target_day=None,
    years=None,
    include_audits=True,
    tape_backup_root=tape_backup.DEFAULT_BACKUP_ROOT,
    tape_backup_status_path=tape_backup.DEFAULT_STATUS_OUT,
    refresh_tape_backup_status=False,
    verify_tape_backup_checksums=False,
    max_tape_backup_age_hours=26.0,
    max_tape_restore_age_hours=168.0,
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    taker_runs_root=DEFAULT_TAKER_RUNS_ROOT,
    parquet_incremental_path=DEFAULT_INCREMENTAL_JSON,
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
    event_metadata = event_metadata_validation_summary(
        Path(snapshots_root).parent / "backtest" / "event_metadata_validation.json"
    )
    live_forward_slo = live_forward_slo_gate(collection, clob, observation, event_metadata)
    current_code_soak = current_code_soak_summary(loop_integrity, live_forward_slo)
    clean_day_countability = clean_active_day_countability(
        collection,
        clob,
        live_forward_slo,
        current_code_soak,
    )
    mm_paper_evidence = mm_paper_evidence_summary()
    mm_starvation = mm_evidence_starvation_summary(mm_runs_root)
    trading_evidence = build_trading_evidence_summary(
        mm_runs_root=mm_runs_root,
        taker_runs_root=taker_runs_root,
    )
    runtime_evidence = build_runtime_identity_evidence(
        snapshots_root=snapshots_root,
        target_date=runtime_identity_target_date(collection),
        mm_runs_root=mm_runs_root,
        taker_runs_root=taker_runs_root,
        reconciliation_path=Path(snapshots_root).parent / "backtest" / "runtime_identity_reconciliation.json",
    )
    settled_freshness = settled_day_freshness_summary()
    parquet_incremental = parquet_incremental_status(parquet_incremental_path)
    tape_backup_status = tape_backup_status_summary(
        backup_root=tape_backup_root,
        status_path=tape_backup_status_path,
        refresh=refresh_tape_backup_status,
        verify_checksums=verify_tape_backup_checksums,
        max_age_hours=max_tape_backup_age_hours,
        max_restore_age_hours=max_tape_restore_age_hours,
    )
    cleanup_deletion_gate = cleanup_deletion_gate_summary(tape_backup_status)
    alerts = []
    alerts.extend(collection_alerts(collection))
    alerts.extend(audit_alerts(audits_json, gap_coverage=gap_coverage))
    alerts.extend(provenance_alerts(provenance))
    alerts.extend(event_metadata_alerts(event_metadata))
    alerts.extend(clob_alerts(clob))
    alerts.extend(observation_alerts(observation))
    alerts.extend(loop_integrity_alerts(loop_integrity))
    alerts.extend(current_code_soak_alerts(current_code_soak))
    alerts.extend(mm_evidence_starvation_alerts(mm_starvation))
    alerts.extend(runtime_identity_alerts(runtime_evidence))
    alerts.extend(settled_day_freshness_alerts(settled_freshness))
    alerts.extend(parquet_incremental_alerts(parquet_incremental))
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
        "event_metadata_validation": event_metadata,
        "clob": clob,
        "observation_trigger": observation,
        "loop_integrity": loop_integrity,
        "current_code_soak": current_code_soak,
        "clean_active_day_countability": clean_day_countability,
        "live_forward_slo": live_forward_slo,
        "mm_paper_evidence": mm_paper_evidence,
        "mm_evidence_starvation": mm_starvation,
        "trading_evidence": trading_evidence,
        "runtime_identity_evidence": runtime_evidence,
        "settled_day_freshness": settled_freshness,
        "closed_day_parquet_incremental": parquet_incremental,
        "tape_backup": tape_backup_status,
        "cleanup_deletion_gate": cleanup_deletion_gate,
        "alerts": alerts,
        "summary": {
            "market_count": len(collection.get("markets") or []),
            "critical_alerts": sum(1 for row in alerts if row.get("severity") == "critical"),
            "warning_alerts": sum(1 for row in alerts if row.get("severity") == "warning"),
            "live_forward_slo_status": live_forward_slo.get("status"),
            "clean_active_day_countability_status": clean_day_countability.get("status"),
            "clean_active_day_counts_toward_early_hour_evidence": (
                clean_day_countability.get("counts_toward_early_hour_evidence")
            ),
            "clean_active_day_operational_blocker_count": (
                clean_day_countability.get("operational_blocker_count")
            ),
            "early_hour_coverage_status": (
                ((collection.get("early_hour_coverage_proof") or {}).get("summary") or {}).get("status")
            ),
            "early_hour_coverage_countable_markets": (
                ((collection.get("early_hour_coverage_proof") or {}).get("summary") or {})
                .get("countable_market_count")
            ),
            "early_hour_coverage_total_snapshots": (
                ((collection.get("early_hour_coverage_proof") or {}).get("summary") or {})
                .get("total_snapshot_count")
            ),
            "event_metadata_validation_status": event_metadata.get("status"),
            "event_metadata_validation_hash": event_metadata.get("validation_hash"),
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
            "mm_countable_paper_market_day_count": mm_starvation.get("countable_paper_market_day_count"),
            "mm_starved_active_day_streak": mm_starvation.get("starved_active_day_streak"),
            "mm_unrecovered_starved_active_day_streak": mm_starvation.get(
                "unrecovered_starved_active_day_streak"
            ),
            "mm_recovered_starved_active_day_count": mm_starvation.get(
                "recovered_starved_active_day_count"
            ),
            "mm_unrecovered_starved_active_day_count": mm_starvation.get(
                "unrecovered_starved_active_day_count"
            ),
            "mm_recovery_attempted_starved_active_day_count": mm_starvation.get(
                "recovery_attempted_starved_active_day_count"
            ),
            "mm_evidence_starvation_status": mm_starvation.get("status"),
            "mm_current_high_trust_no_quote_count": (
                (trading_evidence.get("market_making") or {}).get("current_high_trust_no_quote_count")
            ),
            "taker_current_high_trust_no_trade_count": (
                (trading_evidence.get("taker") or {}).get("current_high_trust_no_trade_count")
            ),
            "runtime_identity_status": runtime_evidence.get("status"),
            "runtime_identity_mixed": runtime_evidence.get("mixed_runtime_identity"),
            "runtime_identity_count": runtime_evidence.get("runtime_identity_count"),
            "runtime_identity_snapshot_rows": runtime_evidence.get("snapshot_row_count"),
            "closed_day_parquet_incremental_status": parquet_incremental.get("status"),
            "closed_day_parquet_incremental_failed": parquet_incremental.get("failed"),
            "closed_day_parquet_incremental_blocked": parquet_incremental.get("blocked"),
            "closed_day_parquet_remaining_scan_backlog": parquet_incremental.get("remaining_scan_backlog"),
            "tape_backup_status": tape_backup_status.get("status"),
            "cleanup_deletion_gate_status": cleanup_deletion_gate.get("status"),
            "loop_integrity_status": "OK" if (loop_integrity.get("summary") or {}).get("ok") else "WARN",
            "current_code_soak_status": current_code_soak.get("status"),
            "current_code_soak_counts": current_code_soak.get("counts_toward_active_day"),
            "loop_restart_count": ((current_code_soak.get("summary") or {}).get("restart_count")),
        },
    }
    return payload

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
