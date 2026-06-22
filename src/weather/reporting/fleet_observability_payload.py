"""Implementation slice extracted from src/weather/reporting/fleet_observability.py."""

from weather.reporting.fleet_observability_gates import *  # noqa: F403
from weather.reporting.trading_evidence import DEFAULT_MM_RUNS_ROOT, mm_evidence_starvation_summary

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
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
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
    current_code_soak = current_code_soak_summary(loop_integrity, live_forward_slo)
    mm_paper_evidence = mm_paper_evidence_summary()
    mm_starvation = mm_evidence_starvation_summary(mm_runs_root)
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
    alerts.extend(current_code_soak_alerts(current_code_soak))
    alerts.extend(mm_evidence_starvation_alerts(mm_starvation))
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
        "current_code_soak": current_code_soak,
        "live_forward_slo": live_forward_slo,
        "mm_paper_evidence": mm_paper_evidence,
        "mm_evidence_starvation": mm_starvation,
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
            "tape_backup_status": tape_backup_status.get("status"),
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
