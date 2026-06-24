"""Nightly operator health checks and alert-folder output."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.io import read_json, write_json_atomic
from weather.operations import market_making_daily_roll, taker_bot_daily_roll
from weather.operations.bot_run_liveness import (
    DEFAULT_MAX_ACTIVITY_AGE_SECONDS,
    DEFAULT_STARTUP_GRACE_SECONDS as BOT_STARTUP_GRACE_SECONDS,
    RUNNING_STATUSES,
)
from weather.paths import data_path
from weather.runtime_identity import format_runtime_identity, get_runtime_identity, identities_match
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("nightly_health_checks")
DEFAULT_ALERT_ROOT = data_path("alerts")
DEFAULT_TIMEZONE = "America/Toronto"
DEFAULT_MAX_BOT_ACTIVITY_AGE_SECONDS = DEFAULT_MAX_ACTIVITY_AGE_SECONDS
DEFAULT_STARTUP_GRACE_SECONDS = BOT_STARTUP_GRACE_SECONDS


def _parse_utc(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc)


def utc_iso(now=None):
    parsed = _parse_utc(now) or utc_now()
    return parsed.astimezone(timezone.utc).isoformat()


def _age_seconds(value, *, now):
    parsed = _parse_utc(value)
    if parsed is None:
        return None
    current = _parse_utc(now) or utc_now()
    return max(0.0, (current - parsed).total_seconds())


def _mtime_row(path, *, now):
    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {"exists": False, "path": str(path)}
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    current = _parse_utc(now) or utc_now()
    return {
        "exists": True,
        "path": str(path),
        "modified_at_utc": modified.isoformat(),
        "age_seconds": round(max(0.0, (current - modified).total_seconds()), 3),
        "size_bytes": int(getattr(stat, "st_size", 0) or 0),
    }


def _local_date(now=None, timezone_name=DEFAULT_TIMEZONE):
    parsed = _parse_utc(now)
    tz = ZoneInfo(timezone_name)
    return (parsed or utc_now()).astimezone(tz).date().isoformat()


def _severity_counts(alerts):
    return dict(sorted(Counter(row.get("severity") or "unknown" for row in alerts).items()))


def _overall_status(alerts):
    if any(row.get("severity") == "critical" for row in alerts):
        return "CRITICAL"
    if any(row.get("severity") == "warning" for row in alerts):
        return "WARN"
    return "OK"


def _runtime_code_state(runtime_identity, current_identity):
    if not runtime_identity:
        return "unknown"
    return "current" if identities_match(runtime_identity, current_identity) else "stale_code"


def _alert(severity, component, category, message, detail=None, remediation_command=None):
    payload = {
        "severity": severity,
        "market_id": "fleet",
        "component": component,
        "category": category,
        "message": message,
        "detail": detail or {},
    }
    if remediation_command:
        payload["remediation_command"] = remediation_command
        payload["detail"]["remediation_command"] = remediation_command
    return payload


def _display_command(command):
    if not command:
        return None
    if isinstance(command, str):
        return command
    return " ".join(str(item) for item in command)


def _loop_rows_and_alerts(fleet_payload):
    alerts = []
    soak = (fleet_payload or {}).get("current_code_soak") or {}
    if not soak:
        alerts.append(_alert(
            "critical",
            "loops",
            "loop_current_code_soak",
            "current-code loop soak payload is missing",
            {"expected_source": "fleet_observability.current_code_soak"},
            "python -m weather.reporting.fleet.fleet_observability",
        ))
        return [], alerts

    rows = []
    for row in soak.get("loops") or []:
        normalized = {
            "name": row.get("name"),
            "status": row.get("status"),
            "state": row.get("state"),
            "pid": row.get("pid"),
            "runtime_code_state": row.get("runtime_code_state"),
            "running_code": row.get("running_code"),
            "current_code": row.get("current_code"),
            "single_writer": row.get("single_writer"),
            "restart_count": row.get("restart_count"),
            "restart_budget": row.get("restart_budget"),
            "blocking_reasons": row.get("blocking_reasons") or [],
            "immediate_repair_commands": row.get("immediate_repair_commands") or [],
            "status_path": row.get("status_path"),
            "diagnostics_path": row.get("diagnostics_path"),
        }
        rows.append(normalized)
        if row.get("status") != "PASS":
            reason = "; ".join(row.get("blocking_reasons") or []) or row.get("state") or "loop is not countable"
            command = next((item for item in row.get("immediate_repair_commands") or [] if item), None)
            alerts.append(_alert(
                "critical",
                str(row.get("name") or "loop"),
                "loop_current_code_soak",
                f"{row.get('name') or 'loop'} health is {row.get('status') or 'UNKNOWN'}: {reason}",
                {
                    "state": row.get("state"),
                    "runtime_code_state": row.get("runtime_code_state"),
                    "single_writer": row.get("single_writer"),
                    "restart_count": row.get("restart_count"),
                    "restart_budget": row.get("restart_budget"),
                    "blocking_reasons": row.get("blocking_reasons") or [],
                    "status_path": row.get("status_path"),
                },
                command,
            ))
    if soak.get("status") != "PASS" and not alerts:
        summary = soak.get("summary") or {}
        alerts.append(_alert(
            "critical",
            "loops",
            "loop_current_code_soak",
            f"current-code loop soak is {soak.get('status') or 'UNKNOWN'}",
            {"summary": summary},
            summary.get("first_immediate_repair_command") or soak.get("verification_command"),
        ))
    return rows, alerts


def _run_summary_candidates(runs_root, target_date):
    day_root = Path(runs_root) / str(target_date)
    if not day_root.exists():
        return []
    candidates = []
    try:
        folders = list(day_root.iterdir())
    except OSError:
        return []
    for folder in folders:
        if not folder.is_dir() or folder.name.startswith(".") or folder.name == "_quarantine":
            continue
        summary_path = folder / "run_summary.json"
        if summary_path.exists():
            candidates.append(summary_path)
    return candidates


def latest_maker_run_summary(runs_root, target_date, *, now=None):
    candidates = _run_summary_candidates(runs_root, target_date)
    if not candidates:
        return {
            "exists": False,
            "path": None,
            "run_folder": None,
            "status": "missing",
        }
    latest = max(candidates, key=lambda path: (path.stat().st_mtime, path.parent.name))
    payload = read_json(latest, default={}) or {}
    liveness = payload.get("useful_work_liveness") or {}
    return {
        **_mtime_row(latest, now=now),
        "run_folder": str(latest.parent),
        "status": "ok",
        "run_id": payload.get("run_id"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "preflight_status": payload.get("preflight_status"),
        "live_forward_gate_status": payload.get("live_forward_gate_status"),
        "quote_permission_rows": payload.get("quote_permission_rows"),
        "row_count": payload.get("row_count"),
        "useful_work_liveness": {
            "status": liveness.get("status"),
            "reason": liveness.get("reason"),
            "blocker_count": liveness.get("blocker_count"),
            "root_cause_counts": liveness.get("root_cause_counts") or {},
            "first_blocker": (liveness.get("blockers") or [{}])[0] if liveness.get("blockers") else {},
        },
    }


def _status_exists(status):
    if not status:
        return False
    return bool(status.get("exists", True))


def _bot_row_and_alerts(
    *,
    component,
    label,
    status,
    expected_target_date,
    current_identity,
    now,
    status_command,
    restart_command,
    maker_run_summary=None,
    max_activity_age_seconds=DEFAULT_MAX_BOT_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
):
    status = dict(status or {})
    alerts = []
    exists = _status_exists(status)
    status_value = status.get("status") if exists else "missing"
    running = bool(exists and status_value in RUNNING_STATUSES)
    runtime_identity = status.get("runtime_identity") or {}
    runtime_state = _runtime_code_state(runtime_identity, current_identity)
    target_date = status.get("target_date")
    target_matches = bool(expected_target_date and target_date == expected_target_date)
    started_age = _age_seconds(status.get("started_at_utc") or status.get("generated_at_utc"), now=now)
    activity_status = None
    latest_activity_age = None
    useful_work_status = None

    if not exists:
        alerts.append(_alert(
            "critical",
            component,
            "bot_status_file",
            f"{label} daily-roll status file is missing",
            {"status_path": status.get("path")},
            status_command,
        ))
    elif not running:
        alerts.append(_alert(
            "critical",
            component,
            "bot_liveness",
            f"{label} is not running: status={status_value}",
            {
                "status": status_value,
                "pid": status.get("pid"),
                "target_date": target_date,
                "root_cause_class": status.get("root_cause_class"),
                "first_failing_gate": status.get("first_failing_gate"),
                "status_path": status.get("path") or status.get("status_path"),
            },
            status.get("remediation_command") or restart_command,
        ))
    if exists and expected_target_date and not target_matches:
        alerts.append(_alert(
            "critical",
            component,
            "bot_target_date",
            f"{label} target date is {target_date or 'unknown'}, expected {expected_target_date}",
            {"target_date": target_date, "expected_target_date": expected_target_date},
            restart_command,
        ))
    if exists and runtime_state == "stale_code":
        alerts.append(_alert(
            "critical",
            component,
            "bot_runtime_identity",
            f"{label} is running stale code",
            {
                "running_code": format_runtime_identity(runtime_identity),
                "current_code": format_runtime_identity(current_identity),
                "status_path": status.get("path") or status.get("status_path"),
            },
            restart_command,
        ))
    elif exists and runtime_state == "unknown":
        alerts.append(_alert(
            "warning",
            component,
            "bot_runtime_identity",
            f"{label} status does not include runtime identity",
            {"status_path": status.get("path") or status.get("status_path")},
            status_command,
        ))

    artifact = status.get("artifact_liveness") or {}
    if artifact:
        activity_status = artifact.get("status")
        latest_activity_age = (
            (artifact.get("latest_useful_artifact") or {}).get("age_seconds")
            or artifact.get("latest_useful_write_age_seconds")
        )
        if artifact.get("ok") is False:
            alerts.append(_alert(
                "critical",
                component,
                "bot_activity",
                f"{label} artifact liveness is {artifact.get('status')}",
                {
                    "root_cause_class": artifact.get("root_cause_class"),
                    "detail": artifact.get("detail"),
                    "latest_run_folder": artifact.get("latest_run_folder"),
                    "latest_useful_artifact": artifact.get("latest_useful_artifact"),
                },
                status.get("remediation_command") or restart_command,
            ))

    if maker_run_summary is not None:
        activity_status = maker_run_summary.get("status")
        latest_activity_age = maker_run_summary.get("age_seconds")
        useful_work = maker_run_summary.get("useful_work_liveness") or {}
        useful_work_status = useful_work.get("status")
        if not maker_run_summary.get("exists"):
            if running and (started_age is None or started_age > float(startup_grace_seconds)):
                alerts.append(_alert(
                    "critical",
                    component,
                    "bot_activity",
                    f"{label} has no latest run_summary.json for {expected_target_date}",
                    {
                        "runs_root": status.get("runs_root"),
                        "target_date": expected_target_date,
                        "started_age_seconds": round(started_age, 3) if started_age is not None else None,
                    },
                    restart_command,
                ))
        elif latest_activity_age is not None and latest_activity_age > float(max_activity_age_seconds):
            alerts.append(_alert(
                "critical",
                component,
                "bot_activity",
                f"{label} run_summary.json is stale",
                {
                    "run_summary_path": maker_run_summary.get("path"),
                    "age_seconds": latest_activity_age,
                    "max_activity_age_seconds": float(max_activity_age_seconds),
                },
                restart_command,
            ))
        if useful_work_status == "BLOCK":
            first = useful_work.get("first_blocker") or {}
            alerts.append(_alert(
                "critical",
                component,
                "bot_useful_work",
                f"{label} useful-work liveness is BLOCK",
                {
                    "reason": useful_work.get("reason"),
                    "blocker_count": useful_work.get("blocker_count"),
                    "root_cause_counts": useful_work.get("root_cause_counts") or {},
                    "first_blocker": first,
                },
                first.get("suggested_command") or first.get("remediation_command") or restart_command,
            ))

    row = {
        "component": component,
        "label": label,
        "status": status_value,
        "running": running,
        "pid": status.get("pid"),
        "target_date": target_date,
        "expected_target_date": expected_target_date,
        "target_date_matches": target_matches,
        "runtime_code_state": runtime_state,
        "running_code": format_runtime_identity(runtime_identity),
        "current_code": format_runtime_identity(current_identity),
        "started_at_utc": status.get("started_at_utc"),
        "started_age_seconds": round(started_age, 3) if started_age is not None else None,
        "activity_status": activity_status,
        "latest_activity_age_seconds": latest_activity_age,
        "useful_work_status": useful_work_status,
        "status_path": status.get("path") or status.get("status_path"),
        "restart_command": restart_command,
        "status_command": status_command,
        "maker_run_summary": maker_run_summary or {},
        "artifact_liveness": artifact,
    }
    return row, alerts


def load_fleet_payload(path):
    return read_json(path, default={}) or {}


def build_payload(
    *,
    fleet_payload=None,
    maker_status=None,
    taker_status=None,
    maker_run_summary=None,
    current_identity=None,
    now=None,
    timezone_name=DEFAULT_TIMEZONE,
    target_date=None,
    maker_status_path=market_making_daily_roll.DEFAULT_STATUS_PATH,
    taker_status_path=taker_bot_daily_roll.DEFAULT_STATUS_PATH,
    max_bot_activity_age_seconds=DEFAULT_MAX_BOT_ACTIVITY_AGE_SECONDS,
    startup_grace_seconds=DEFAULT_STARTUP_GRACE_SECONDS,
):
    generated_at = utc_iso(now)
    current_identity = current_identity or get_runtime_identity()
    expected_date = target_date or _local_date(now=now, timezone_name=timezone_name)
    if maker_status is None:
        maker_status = market_making_daily_roll.load_status(maker_status_path, now=now)
    if taker_status is None:
        taker_status = taker_bot_daily_roll.load_status(
            taker_status_path,
            now=now,
            max_activity_age_seconds=max_bot_activity_age_seconds,
            startup_grace_seconds=startup_grace_seconds,
        )
    if maker_run_summary is None:
        maker_root = (maker_status or {}).get("runs_root") or market_making_daily_roll.DEFAULT_RUNS_ROOT
        maker_run_summary = latest_maker_run_summary(maker_root, expected_date, now=now)

    loop_rows, alerts = _loop_rows_and_alerts(fleet_payload or {})
    maker_row, maker_alerts = _bot_row_and_alerts(
        component="maker_bot",
        label="Maker bot",
        status=maker_status,
        expected_target_date=expected_date,
        current_identity=current_identity,
        now=now,
        status_command="python -m weather.operations.market_making_daily_roll status",
        restart_command="python -m weather.operations.market_making_daily_roll start --force",
        maker_run_summary=maker_run_summary,
        max_activity_age_seconds=max_bot_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
    )
    taker_row, taker_alerts = _bot_row_and_alerts(
        component="taker_bot",
        label="Taker bot",
        status=taker_status,
        expected_target_date=expected_date,
        current_identity=current_identity,
        now=now,
        status_command="python -m weather.operations.taker_bot_daily_roll status",
        restart_command="python -m weather.operations.taker_bot_daily_roll start --force",
        max_activity_age_seconds=max_bot_activity_age_seconds,
        startup_grace_seconds=startup_grace_seconds,
    )
    alerts.extend(maker_alerts)
    alerts.extend(taker_alerts)
    status = _overall_status(alerts)
    fleet_summary = (fleet_payload or {}).get("summary") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at,
        "alert_date": expected_date,
        "timezone": timezone_name,
        "status": status,
        "current_identity": current_identity,
        "current_code": format_runtime_identity(current_identity),
        "target_dates": {
            "maker_bot": expected_date,
            "taker_bot": expected_date,
        },
        "loops": loop_rows,
        "bots": [maker_row, taker_row],
        "fleet_observability": {
            "status": (fleet_payload or {}).get("status"),
            "generated_at_utc": (fleet_payload or {}).get("generated_at_utc"),
            "summary": fleet_summary,
            "alert_count": len((fleet_payload or {}).get("alerts") or []),
            "current_code_soak_status": ((fleet_payload or {}).get("current_code_soak") or {}).get("status"),
            "live_forward_slo_status": ((fleet_payload or {}).get("live_forward_slo") or {}).get("status"),
        },
        "alerts": alerts,
        "summary": {
            "status": status,
            "alert_count": len(alerts),
            "critical_alerts": sum(1 for row in alerts if row.get("severity") == "critical"),
            "warning_alerts": sum(1 for row in alerts if row.get("severity") == "warning"),
            "severity_counts": _severity_counts(alerts),
            "loop_count": len(loop_rows),
            "blocking_loop_count": sum(1 for row in loop_rows if row.get("status") != "PASS"),
            "running_bot_count": sum(1 for row in [maker_row, taker_row] if row.get("running")),
            "current_code_bot_count": sum(
                1 for row in [maker_row, taker_row] if row.get("runtime_code_state") == "current"
            ),
            "first_alert": alerts[0] if alerts else {},
        },
    }


def render_report(payload):
    alerts = payload.get("alerts") or []
    lines = [
        "# Nightly Health Checks",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Alert date: `{payload.get('alert_date')}`",
        f"Status: **{payload.get('status')}**",
        f"Current code: `{payload.get('current_code') or '-'}`",
        "",
        "## Alerts",
        "",
    ]
    if not alerts:
        lines.append("No alerts.")
    else:
        lines += [
            "| Severity | Component | Category | Message | Remediation |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for alert in alerts:
            lines.append(
                "| "
                f"{alert.get('severity')} | "
                f"{alert.get('component') or '-'} | "
                f"{alert.get('category') or '-'} | "
                f"{alert.get('message') or '-'} | "
                f"`{alert.get('remediation_command') or '-'}` |"
            )
    lines += [
        "",
        "## Loop Checks",
        "",
        "| Loop | Status | State | Code | Single Writer | Restarts | Blocking Reasons | Repair |",
        "| :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |",
    ]
    for row in payload.get("loops") or []:
        lines.append(
            "| "
            f"{row.get('name') or '-'} | "
            f"{row.get('status') or '-'} | "
            f"{row.get('state') or '-'} | "
            f"{row.get('runtime_code_state') or '-'} | "
            f"{row.get('single_writer')} | "
            f"{row.get('restart_count') if row.get('restart_count') is not None else '-'} | "
            f"{'; '.join(row.get('blocking_reasons') or []) or '-'} | "
            f"`{'; '.join(row.get('immediate_repair_commands') or []) or '-'}` |"
        )
    lines += [
        "",
        "## Bot Checks",
        "",
        "| Bot | Status | Running | Target | Code | Activity | Age s | Useful Work | Repair |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | ---: | :--- | :--- |",
    ]
    for row in payload.get("bots") or []:
        lines.append(
            "| "
            f"{row.get('label') or row.get('component') or '-'} | "
            f"{row.get('status') or '-'} | "
            f"{row.get('running')} | "
            f"{row.get('target_date') or '-'} -> {row.get('expected_target_date') or '-'} | "
            f"{row.get('runtime_code_state') or '-'} | "
            f"{row.get('activity_status') or '-'} | "
            f"{row.get('latest_activity_age_seconds') if row.get('latest_activity_age_seconds') is not None else '-'} | "
            f"{row.get('useful_work_status') or '-'} | "
            f"`{row.get('restart_command') or '-'}` |"
        )
    fleet = payload.get("fleet_observability") or {}
    lines += [
        "",
        "## Fleet Context",
        "",
        "| Field | Value |",
        "| :--- | :--- |",
        f"| Fleet status | {fleet.get('status') or '-'} |",
        f"| Fleet generated | {fleet.get('generated_at_utc') or '-'} |",
        f"| Current-code soak | {fleet.get('current_code_soak_status') or '-'} |",
        f"| Live-forward SLO | {fleet.get('live_forward_slo_status') or '-'} |",
        f"| Fleet alert count | {fleet.get('alert_count', 0)} |",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(payload.get("summary") or {}, indent=2, sort_keys=True, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def write_outputs(payload, *, alert_root=DEFAULT_ALERT_ROOT):
    root = Path(alert_root)
    alert_date = payload.get("alert_date") or str(payload.get("generated_at_utc") or "")[:10] or "unknown-date"
    daily_dir = root / alert_date
    json_out = write_json_atomic(daily_dir / "nightly_health.json", payload, trailing_newline=True)
    report_out = write_report(daily_dir / "nightly_health_report.md", payload)
    latest_json_out = write_json_atomic(root / "nightly_health_latest.json", payload, trailing_newline=True)
    latest_report_out = write_report(root / "nightly_health_latest.md", payload)
    return {
        "json_out": str(json_out),
        "report_out": str(report_out),
        "latest_json_out": str(latest_json_out),
        "latest_report_out": str(latest_report_out),
        "alert_root": str(root),
    }
