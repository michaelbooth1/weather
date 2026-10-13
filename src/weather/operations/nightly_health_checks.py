"""Nightly operator health checks and alert-folder output."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.io import read_json, write_json_atomic
from weather.paths import data_path
from weather.runtime_identity import format_runtime_identity, get_runtime_identity
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("nightly_health_checks")
DEFAULT_ALERT_ROOT = data_path("alerts")
DEFAULT_TIMEZONE = "America/Toronto"
# The taker and paper-maker bots were retired and their runtime code deleted on
# 2026-09-29.  They stay listed as RETIRED rows so the report keeps its shape,
# but nothing is read for them and no restart is ever suggested.
RETIRED_BOTS = (("maker_bot", "Maker bot"), ("taker_bot", "Taker bot"))


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


from weather.time import utc_now


def utc_iso(now=None):
    parsed = _parse_utc(now) or utc_now()
    return parsed.astimezone(timezone.utc).isoformat()


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


def _retired_bot_row(component, label, expected_target_date):
    return {
        "component": component, "label": label, "status": "RETIRED",
        "running": False, "runtime_code_state": "not_applicable",
        "expected_target_date": expected_target_date,
        "restart_command": None, "status_command": None,
    }


def load_fleet_payload(path):
    return read_json(path, default={}) or {}


def build_payload(
    *,
    fleet_payload=None,
    current_identity=None,
    now=None,
    timezone_name=DEFAULT_TIMEZONE,
    target_date=None,
):
    generated_at = utc_iso(now)
    current_identity = current_identity or get_runtime_identity()
    expected_date = target_date or _local_date(now=now, timezone_name=timezone_name)
    loop_rows, alerts = _loop_rows_and_alerts(fleet_payload or {})
    bot_rows = [
        _retired_bot_row(component, label, expected_date)
        for component, label in RETIRED_BOTS
    ]
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
        "bots": bot_rows,
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
            "running_bot_count": sum(1 for row in bot_rows if row.get("running")),
            "retired_bot_count": sum(1 for row in bot_rows if row.get("status") == "RETIRED"),
            "current_code_bot_count": sum(
                1 for row in bot_rows if row.get("runtime_code_state") == "current"
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
