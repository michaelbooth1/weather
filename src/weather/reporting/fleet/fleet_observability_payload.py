"""Implementation slice extracted from src/weather/reporting/fleet/fleet_observability.py."""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
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

DEFAULT_DAILY_REFRESH_STATUS = data_path() / "backtest" / "daily_refresh_status.json"


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


def _build_trust_readiness(snapshots_root, *, include_trust_replay=True):
    if not include_trust_replay:
        return {}, {
            "status": "SKIPPED",
            "reason": "scheduled_bounded_mode",
            "trust_readiness_omitted": True,
            "score_all_markets_called": False,
        }
    rows = score_all_markets(root=snapshots_root)
    return trust_readiness(rows), {
        "status": "COMPLETED",
        "reason": "full_trust_replay",
        "trust_readiness_omitted": False,
        "score_all_markets_called": True,
        "market_count": len(rows),
    }


def _build_runtime_identity_observability(
    *,
    snapshots_root,
    target_date,
    mm_runs_root,
    taker_runs_root,
    reconciliation_path,
    include_runtime_identity_replay=True,
):
    if not include_runtime_identity_replay:
        return {}, {
            "status": "SKIPPED",
            "reason": "scheduled_bounded_mode",
            "runtime_identity_evidence_omitted": True,
            "build_runtime_identity_evidence_called": False,
            "target_date": target_date,
        }
    evidence = build_runtime_identity_evidence(
        snapshots_root=snapshots_root,
        target_date=target_date,
        mm_runs_root=mm_runs_root,
        taker_runs_root=taker_runs_root,
        reconciliation_path=reconciliation_path,
    )
    return evidence, {
        "status": "COMPLETED",
        "reason": "full_runtime_identity_replay",
        "runtime_identity_evidence_omitted": False,
        "build_runtime_identity_evidence_called": True,
        "target_date": target_date,
    }


def _build_trading_observability(
    mm_runs_root,
    taker_runs_root,
    *,
    include_trading_replay=True,
):
    if not include_trading_replay:
        return {}, {}, {
            "status": "SKIPPED",
            "reason": "scheduled_bounded_mode",
            "trading_evidence_omitted": True,
            "mm_evidence_starvation_summary_called": False,
            "build_trading_evidence_summary_called": False,
        }
    starvation = mm_evidence_starvation_summary(mm_runs_root)
    evidence = build_trading_evidence_summary(
        mm_runs_root=mm_runs_root,
        taker_runs_root=taker_runs_root,
    )
    return starvation, evidence, {
        "status": "COMPLETED",
        "reason": "full_mm_taker_run_replay",
        "trading_evidence_omitted": False,
        "mm_evidence_starvation_summary_called": True,
        "build_trading_evidence_summary_called": True,
    }


def overall_status(alerts):
    if any(row.get("severity") == "critical" for row in alerts):
        return "CRITICAL"
    if any(row.get("severity") == "warning" for row in alerts):
        return "WARN"
    return "OK"


def cleanup_deletion_gate_summary():
    canonical_gate = delete_gate_for_storage_class(CANONICAL_EVIDENCE)
    return {
        "status": canonical_gate.get("status"),
        "canonical_evidence": canonical_gate,
        "delete_permission": canonical_gate.get("delete_permission"),
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


def daily_refresh_resource_summary(rows):
    rows = list(rows or [])
    statuses = Counter(str(row.get("status") or "unknown") for row in rows)
    private_peaks = [
        int((((row.get("subprocess") or {}).get("resource_peaks") or {}).get("private_memory_peak_bytes") or 0))
        for row in rows
    ]
    working_set_peaks = [
        int((((row.get("subprocess") or {}).get("resource_peaks") or {}).get("working_set_peak_bytes") or 0))
        for row in rows
    ]
    return {
        "status": (
            "ERROR"
            if statuses.get("error")
            else "DEFERRED"
            if statuses.get("deferred") or statuses.get("ok_postcheck_deferred")
            else "OK"
            if rows
            else "NOT_RUN"
        ),
        "step_count": len(rows),
        "status_counts": dict(statuses),
        "private_memory_peak_bytes": max(private_peaks, default=0),
        "working_set_peak_bytes": max(working_set_peaks, default=0),
        "budget_decisions": [
            {
                "step": row.get("step"),
                "status": row.get("status"),
                "child_pid": row.get("child_pid"),
                "before": (row.get("admission_before") or {}).get("decision"),
                "after": (row.get("admission_after") or {}).get("decision"),
                "private_memory_max_bytes": (row.get("budget") or {}).get("private_memory_max_bytes"),
                "working_set_max_bytes": (row.get("budget") or {}).get("working_set_max_bytes"),
                "timeout_seconds": (row.get("budget") or {}).get("timeout_seconds"),
                "private_memory_peak_bytes": (((row.get("subprocess") or {}).get("resource_peaks") or {}).get("private_memory_peak_bytes")),
                "working_set_peak_bytes": (((row.get("subprocess") or {}).get("resource_peaks") or {}).get("working_set_peak_bytes")),
                "read_bytes": (((row.get("subprocess") or {}).get("resource_io") or {}).get("read_bytes")),
                "write_bytes": (((row.get("subprocess") or {}).get("resource_io") or {}).get("write_bytes")),
                "duration_seconds": (row.get("subprocess") or {}).get("duration_seconds"),
                "result_metric_count": len(row.get("result_metrics") or {}),
                "failure_reason": row.get("failure_reason") or row.get("post_step_failure_reason"),
            }
            for row in rows
        ],
    }


def load_daily_refresh_resource_rows(path=DEFAULT_DAILY_REFRESH_STATUS):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    return list(payload.get("resource_steps") or [])


def build_observability_payload(
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    interval_minutes=10.0,
    tolerance=1.5,
    target_month=None,
    target_day=None,
    years=None,
    include_audits=True,
    include_trust_replay=True,
    include_runtime_identity_replay=True,
    include_trading_replay=True,
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    taker_runs_root=DEFAULT_TAKER_RUNS_ROOT,
    parquet_incremental_path=DEFAULT_INCREMENTAL_JSON,
    daily_refresh_resources=None,
    daily_refresh_status_path=DEFAULT_DAILY_REFRESH_STATUS,
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
    historical_audit_execution = {
        "status": "COMPLETED" if include_audits else "SKIPPED",
        "reason": "full_historical_audit" if include_audits else "scheduled_bounded_mode",
        "historical_audits_omitted": not include_audits,
        "market_count": len(audits_json),
    }
    provenance = artifact_inventory()
    gap_coverage = historical_gap_coverage(audits_json) if include_audits else {}
    trust, trust_execution = _build_trust_readiness(
        snapshots_root,
        include_trust_replay=include_trust_replay,
    )
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
    mm_starvation, trading_evidence, trading_replay_execution = (
        _build_trading_observability(
            mm_runs_root,
            taker_runs_root,
            include_trading_replay=include_trading_replay,
        )
    )
    runtime_evidence, runtime_identity_execution = _build_runtime_identity_observability(
        snapshots_root=snapshots_root,
        target_date=runtime_identity_target_date(collection),
        mm_runs_root=mm_runs_root,
        taker_runs_root=taker_runs_root,
        reconciliation_path=Path(snapshots_root).parent / "backtest" / "runtime_identity_reconciliation.json",
        include_runtime_identity_replay=include_runtime_identity_replay,
    )
    settled_freshness = settled_day_freshness_summary()
    parquet_incremental = parquet_incremental_status(parquet_incremental_path)
    cleanup_deletion_gate = cleanup_deletion_gate_summary()
    refresh_resource_rows = (
        load_daily_refresh_resource_rows(daily_refresh_status_path)
        if daily_refresh_resources is None
        else daily_refresh_resources
    )
    refresh_resources = daily_refresh_resource_summary(refresh_resource_rows)
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
    bounded_omissions = [
        name
        for name, execution in (
            ("historical_audit", historical_audit_execution),
            ("trust_replay", trust_execution),
            ("runtime_identity_replay", runtime_identity_execution),
            ("trading_replay", trading_replay_execution),
        )
        if execution.get("status") == "SKIPPED"
    ]
    if bounded_omissions:
        alerts.append({
            "severity": "warning",
            "market_id": "fleet",
            "category": "scheduled_bounded_omission",
            "message": (
                "scheduled fleet mode omitted full-corpus evidence; "
                "promotion must remain fail-closed"
            ),
            "detail": {"omitted": bounded_omissions},
        })
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_now(),
        "status": overall_status(alerts),
        "snapshots_root": str(snapshots_root),
        "collection": collection,
        "historical_audits": audits_json,
        "historical_audit_execution": historical_audit_execution,
        "historical_gap_coverage": gap_coverage,
        "artifact_provenance": provenance,
        "trust_readiness": trust,
        "trust_readiness_execution": trust_execution,
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
        "trading_replay_execution": trading_replay_execution,
        "runtime_identity_evidence": runtime_evidence,
        "runtime_identity_execution": runtime_identity_execution,
        "settled_day_freshness": settled_freshness,
        "closed_day_parquet_incremental": parquet_incremental,
        "cleanup_deletion_gate": cleanup_deletion_gate,
        "daily_refresh_resources": refresh_resources,
        "alerts": alerts,
        "summary": {
            "market_count": len(collection.get("markets") or []),
            "critical_alerts": sum(1 for row in alerts if row.get("severity") == "critical"),
            "warning_alerts": sum(1 for row in alerts if row.get("severity") == "warning"),
            "scheduled_bounded_omissions": bounded_omissions,
            "historical_audit_execution_status": historical_audit_execution.get(
                "status"
            ),
            "historical_audits_omitted": historical_audit_execution.get(
                "historical_audits_omitted"
            ),
            "trust_readiness_execution_status": trust_execution.get("status"),
            "trust_readiness_omitted": trust_execution.get(
                "trust_readiness_omitted"
            ),
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
            "trading_replay_execution_status": trading_replay_execution.get(
                "status"
            ),
            "trading_evidence_omitted": trading_replay_execution.get(
                "trading_evidence_omitted"
            ),
            "mm_current_high_trust_no_quote_count": (
                (trading_evidence.get("market_making") or {}).get("current_high_trust_no_quote_count")
            ),
            "taker_current_high_trust_no_trade_count": (
                (trading_evidence.get("taker") or {}).get("current_high_trust_no_trade_count")
            ),
            "runtime_identity_status": runtime_evidence.get("status"),
            "runtime_identity_execution_status": runtime_identity_execution.get(
                "status"
            ),
            "runtime_identity_evidence_omitted": runtime_identity_execution.get(
                "runtime_identity_evidence_omitted"
            ),
            "runtime_identity_mixed": runtime_evidence.get("mixed_runtime_identity"),
            "runtime_identity_count": runtime_evidence.get("runtime_identity_count"),
            "runtime_identity_snapshot_rows": runtime_evidence.get("snapshot_row_count"),
            "closed_day_parquet_incremental_status": parquet_incremental.get("status"),
            "closed_day_parquet_incremental_failed": parquet_incremental.get("failed"),
            "closed_day_parquet_incremental_blocked": parquet_incremental.get("blocked"),
            "closed_day_parquet_remaining_scan_backlog": parquet_incremental.get("remaining_scan_backlog"),
            "cleanup_deletion_gate_status": cleanup_deletion_gate.get("status"),
            "loop_integrity_status": "OK" if (loop_integrity.get("summary") or {}).get("ok") else "WARN",
            "current_code_soak_status": current_code_soak.get("status"),
            "current_code_soak_counts": current_code_soak.get("counts_toward_active_day"),
            "loop_restart_count": ((current_code_soak.get("summary") or {}).get("restart_count")),
            "daily_refresh_resource_status": refresh_resources.get("status"),
            "daily_refresh_private_memory_peak_bytes": refresh_resources.get("private_memory_peak_bytes"),
            "daily_refresh_working_set_peak_bytes": refresh_resources.get("working_set_peak_bytes"),
        },
    }
    return payload

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
