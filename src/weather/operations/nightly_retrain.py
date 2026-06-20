"""Nightly retrain -> validate -> promote orchestration."""

from __future__ import annotations

from weather.operations.windows_silent import apply_windows_silent_subprocess_defaults

apply_windows_silent_subprocess_defaults()

import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from weather.paths import data_path

from weather.artifacts import DEFAULT_ARTIFACT_REGISTRY_PATH, writable_artifact_path
from weather.backtesting.settlement_ledger import DEFAULT_LABELS_CSV, DEFAULT_LEDGER_ROOT
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("nightly_retrain")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_SNAPSHOTS_ROOT = data_path() / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_report.md"
DEFAULT_FAMILY_SECONDARY_MANIFEST = writable_artifact_path("f_family_secondary_artifacts.json")
DEFAULT_POOLED_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_v0_3.pkl")
DEFAULT_DAILY_LEARNING_OUT = DEFAULT_BACKTEST_ROOT / "daily_learning.json"
DEFAULT_DAILY_LEARNING_REPORT = DEFAULT_BACKTEST_ROOT / "daily_learning_report.md"
DEFAULT_SETTLED_DAY_FRESHNESS_OUT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness.json"
DEFAULT_SETTLED_DAY_FRESHNESS_REPORT = DEFAULT_BACKTEST_ROOT / "settled_day_freshness_report.md"
DEFAULT_TASK_NAME = "WeatherNightlyRetrainValidatePromote"
DEFAULT_SCHEDULE_LOCAL_TIME = "03:30"
DEFAULT_SCHEDULE_TIMEZONE = "America/Toronto"
DEFAULT_MISSED_RUN_GRACE_MINUTES = 120
DEFAULT_SLA_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_sla_status.json"
DEFAULT_SLA_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_sla_status_report.md"
DEFAULT_STEP_TIMEOUT_SECONDS = 60 * 60


def utc_iso():
    return datetime.now(timezone.utc).isoformat()


def backtest_path(args, name):
    return str(Path(args.backtest_root) / name)


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return path


def read_json(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_schedule_time(value):
    try:
        hour, minute = str(value).split(":", 1)
        return datetime_time(hour=int(hour), minute=int(minute))
    except (TypeError, ValueError):
        return datetime_time(hour=3, minute=30)


def latest_scheduled_window(
    *,
    now=None,
    schedule_local_time=DEFAULT_SCHEDULE_LOCAL_TIME,
    schedule_timezone=DEFAULT_SCHEDULE_TIMEZONE,
):
    zone = ZoneInfo(schedule_timezone)
    if now is None:
        local_now = datetime.now(timezone.utc).astimezone(zone)
    else:
        local_now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        local_now = local_now.astimezone(zone)
    scheduled_time = parse_schedule_time(schedule_local_time)
    due = datetime.combine(local_now.date(), scheduled_time, tzinfo=zone)
    if local_now < due:
        due -= timedelta(days=1)
    return local_now, due


def run_subprocess_step(command, *, timeout_seconds=DEFAULT_STEP_TIMEOUT_SECONDS):
    started = time.time()
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "duration_seconds": round(time.time() - started, 3),
    }


def family_secondary_command(args):
    return [
        sys.executable,
        "-m",
        "weather.calibration.family_secondary_artifacts",
        "train",
        "--family-unit",
        args.family_unit,
        "--snapshots-root",
        args.snapshots_root,
        "--quality-grades",
        args.quality_grades,
        "--min-trust",
        str(args.min_trust),
        "--min-settled-days",
        str(args.min_settled_days),
        "--out",
        args.family_secondary_out,
        "--report",
        backtest_path(args, "f_family_secondary_artifacts_report.md"),
    ]


def settled_day_freshness_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.operations.settled_day_freshness",
        "repair",
        "--snapshots-root",
        args.snapshots_root,
        "--labels-csv",
        args.labels_csv,
        "--ledger-root",
        args.ledger_root,
        "--json-out",
        args.settled_day_freshness_out,
        "--report-out",
        args.settled_day_freshness_report,
    ]
    if args.settled_day_target_date:
        command += ["--target-date", args.settled_day_target_date]
    if args.settled_day_as_of:
        command += ["--as-of", args.settled_day_as_of]
    if args.settled_day_markets:
        command += ["--markets", args.settled_day_markets]
    if args.skip_settled_day_polymarket_reconciliation:
        command.append("--skip-polymarket-reconciliation")
    return command


def daily_learning_command(args):
    return [
        sys.executable,
        "-m",
        "weather.reporting.daily_learning",
        "--backtest-root",
        args.backtest_root,
        "--snapshots-root",
        args.snapshots_root,
        "--json-out",
        args.daily_learning_out,
        "--report-out",
        args.daily_learning_report,
    ]


def pooled_feature_command(args):
    return [
        sys.executable,
        "-m",
        "weather.calibration.pooled_feature_model",
        "--family-unit",
        args.family_unit,
        "--objective",
        "band",
        "--holdout-year",
        str(args.holdout_year),
        "--artifact",
        args.pooled_band_artifact,
        "--out",
        backtest_path(args, "f_family_pooled_band_model_v0_3_report.md"),
    ]


def artifact_registry_command(args):
    return [
        sys.executable,
        "-m",
        "weather.artifacts",
        "registry",
        "--out",
        args.artifact_registry,
    ]


def promotion_refresh_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.promotion_refresh",
        "--family-unit",
        args.family_unit,
        "--snapshots-root",
        args.snapshots_root,
        "--quality-grades",
        args.quality_grades,
        "--artifact",
        args.pooled_band_artifact,
        "--out",
        args.promotion_out,
        "--report",
        args.promotion_report,
        "--long-job-state",
        str(args.long_job_state),
        "--long-job-lock",
        str(args.long_job_lock),
        "--long-job-priority",
        args.long_job_priority,
    ]
    if args.include_reconstructed:
        command.append("--include-reconstructed")
    if args.allow_unsettled:
        command.append("--allow-unsettled")
    if args.require_exact_identity:
        command.append("--require-exact-identity")
    if args.require_all_markets:
        command.append("--require-all-markets")
    if args.no_baseline:
        command.append("--no-baseline")
    return command


def shadow_ab_monitor_command(args):
    command = [
        sys.executable,
        "-m",
        "weather.reporting.shadow_ab_monitor",
        "--promotion-refresh",
        args.promotion_out,
        "--candidate-replay",
        str(Path(args.backtest_root) / "pooled_candidate_replay_latest.json"),
        "--json-out",
        args.shadow_ab_out,
        "--report-out",
        args.shadow_ab_report,
        "--current-tol",
        str(args.ab_current_tol),
        "--market-tol",
        str(args.ab_market_tol),
    ]
    if args.fail_on_shadow_ab_alert:
        command.append("--fail-on-alert")
    return command


def planned_steps(args):
    steps = []
    if not args.skip_settled_day_freshness:
        steps.append(("settled_day_freshness", settled_day_freshness_command(args)))
    if not args.skip_daily_learning:
        steps.append(("daily_learning", daily_learning_command(args)))
    if not args.skip_family_secondary:
        steps.append(("family_secondary_artifacts", family_secondary_command(args)))
    if not args.skip_pooled_feature:
        steps.append(("pooled_feature_model_band", pooled_feature_command(args)))
    if not args.skip_artifact_registry:
        steps.append(("artifact_registry", artifact_registry_command(args)))
    if not args.skip_promotion_refresh:
        steps.append(("promotion_refresh", promotion_refresh_command(args)))
    if not args.skip_shadow_ab_monitor:
        steps.append(("shadow_ab_monitor", shadow_ab_monitor_command(args)))
    return steps


def run_step(name, command, args, runner):
    started = time.time()
    step = {
        "name": name,
        "command": command,
        "started_at_utc": utc_iso(),
        "finished_at_utc": None,
        "duration_seconds": None,
        "status": "running",
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    try:
        result = runner(command, timeout_seconds=args.step_timeout_seconds)
        step.update(result or {})
        step["returncode"] = int(step.get("returncode") or 0)
        step["status"] = "ok" if step["returncode"] == 0 else "error"
    except Exception as exc:  # noqa: BLE001
        step["status"] = "error"
        step["returncode"] = -1
        step["stderr"] = f"{type(exc).__name__}: {exc}"
        step["traceback"] = traceback.format_exc()
    step["finished_at_utc"] = utc_iso()
    step["duration_seconds"] = round(time.time() - started, 3)
    return step


def promotion_summary(path):
    payload = read_json(path)
    decisions = payload.get("decisions") or {}
    readiness = payload.get("readiness") or {}
    promote = decisions.get("promote_markets") or []
    shadow = decisions.get("shadow_markets") or []
    blocked = decisions.get("blocked_markets") or []
    if not payload:
        verdict = "missing"
    elif blocked:
        verdict = "blocked"
    elif promote:
        verdict = "promote_ready"
    else:
        verdict = "shadow"
    return {
        "path": str(path),
        "exists": bool(payload),
        "verdict": verdict,
        "readiness_status": readiness.get("status"),
        "promote_markets": promote,
        "shadow_markets": shadow,
        "blocked_markets": blocked,
        "market_count": len((decisions.get("markets") or [])),
        "serving_gauntlet_verdict": (payload.get("serving_gauntlet") or {}).get("verdict"),
    }


def promotion_not_run_summary(path, reason):
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "verdict": "not_run",
        "reason": reason,
        "readiness_status": None,
        "promote_markets": [],
        "shadow_markets": [],
        "blocked_markets": [],
        "market_count": 0,
        "serving_gauntlet_verdict": None,
    }


def daily_learning_summary(path):
    payload = read_json(path)
    summary = payload.get("summary") or {}
    retrain_plan = payload.get("retrain_plan") or {}
    broad_slo = retrain_plan.get("broad_live_forward_slo") or (
        ((payload.get("scorecard") or {}).get("fleet") or {}).get("live_forward_slo") or {}
    )
    variant_learning_gate = retrain_plan.get("variant_learning_gate") or (
        (payload.get("scorecard") or {}).get("variant_learning_gate") or {}
    )
    blockers = [
        {
            "priority": row.get("priority"),
            "category": row.get("category"),
            "source": row.get("source"),
            "signal": row.get("signal"),
            "action": row.get("action"),
        }
        for row in payload.get("learnings") or []
        if row.get("blocker")
    ]
    return {
        "path": str(path),
        "exists": bool(payload),
        "status": payload.get("status") if payload else "missing",
        "run_date": payload.get("run_date"),
        "learning_count": summary.get("learning_count"),
        "blocker_count": summary.get("blocker_count"),
        "high_priority_learning_count": summary.get("high_priority_learning_count"),
        "retrain_input_count": summary.get("retrain_input_count"),
        "training_ready": retrain_plan.get("training_ready"),
        "promotion_ready": retrain_plan.get("promotion_ready"),
        "broad_live_forward_slo": broad_slo,
        "variant_learning_gate": variant_learning_gate,
        "blockers": blockers,
    }


def settled_day_freshness_summary(path):
    payload = read_json(path)
    summary = payload.get("summary") or {}
    first_missing = next(
        (
            row
            for row in payload.get("markets") or []
            if not row.get("canonical_complete")
        ),
        {},
    )
    return {
        "path": str(path),
        "exists": bool(payload),
        "status": payload.get("status") if payload else "missing",
        "target_date": payload.get("target_date"),
        "expected_market_count": summary.get("expected_market_count"),
        "complete_market_count": summary.get("complete_market_count"),
        "incomplete_market_count": summary.get("incomplete_market_count"),
        "needs_finalization_count": summary.get("needs_finalization_count"),
        "needs_replay_status_repair_count": summary.get("needs_replay_status_repair_count"),
        "missing_label_count": summary.get("missing_label_count"),
        "missing_ledger_count": summary.get("missing_ledger_count"),
        "missing_settlement_json_count": summary.get("missing_settlement_json_count"),
        "missing_replay_status_count": summary.get("missing_replay_status_count"),
        "missing_replay_inputs_count": summary.get("missing_replay_inputs_count"),
        "missing_source_status_count": summary.get("missing_source_status_count"),
        "missing_tape_count": summary.get("missing_tape_count"),
        "source_lag_warning_count": summary.get("source_lag_warning_count"),
        "repair_command": payload.get("repair_command"),
        "replay_status_repair_command": payload.get("replay_status_repair_command"),
        "first_missing": {
            "market_id": first_missing.get("market_id"),
            "event_slug": first_missing.get("event_slug"),
            "missing_requirements": first_missing.get("missing_requirements") or [],
        },
    }


def nightly_run_sla_status(
    *,
    status_path=DEFAULT_STATUS_OUT,
    status_payload=None,
    task_name=DEFAULT_TASK_NAME,
    task_status=None,
    now=None,
    schedule_local_time=DEFAULT_SCHEDULE_LOCAL_TIME,
    schedule_timezone=DEFAULT_SCHEDULE_TIMEZONE,
    missed_run_grace_minutes=DEFAULT_MISSED_RUN_GRACE_MINUTES,
):
    status_path = Path(status_path)
    status_payload = status_payload if status_payload is not None else read_json(status_path)
    local_now, latest_due = latest_scheduled_window(
        now=now,
        schedule_local_time=schedule_local_time,
        schedule_timezone=schedule_timezone,
    )
    grace_deadline = latest_due + timedelta(minutes=float(missed_run_grace_minutes))
    run_generated = parse_datetime(
        (status_payload or {}).get("finished_at_utc")
        or (status_payload or {}).get("generated_at_utc")
        or (status_payload or {}).get("started_at_utc")
    )
    fresh = bool(run_generated and run_generated.astimezone(latest_due.tzinfo) >= latest_due)
    age_hours = None
    if run_generated:
        age_hours = round(
            (
                local_now.astimezone(timezone.utc)
                - run_generated.astimezone(timezone.utc)
            ).total_seconds() / 3600.0,
            3,
        )

    run_status = (status_payload or {}).get("status") if status_payload else "missing"
    learning = (status_payload or {}).get("daily_learning") or {}
    blockers = learning.get("blockers") or []
    first_blocker = blockers[0] if blockers else {}
    broad_slo = learning.get("broad_live_forward_slo") or {}
    broad_first_blocker = broad_slo.get("first_blocker") or next(
        iter(broad_slo.get("recovery_checklist") or []),
        {},
    )
    task_registered = None if task_status is None else bool(task_status.get("Registered"))
    alerts = []
    if task_registered is False:
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_task",
            "message": f"{task_name} is not registered",
        })
    if local_now >= grace_deadline and not fresh:
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_missed_run",
            "message": f"no fresh nightly status exists after the {schedule_local_time} scheduled window",
        })
    if fresh and run_status == "error":
        alerts.append({
            "severity": "critical",
            "category": "nightly_retrain_error",
            "message": "latest nightly self-improvement run ended in error",
        })

    if any(row.get("severity") == "critical" for row in alerts):
        state = "CRITICAL"
    elif fresh and run_status == "blocked":
        state = "BLOCKED"
    elif not fresh:
        state = "PENDING"
    elif fresh and run_status in {"promote_ready", "shadow", "dry_run"}:
        state = "OK"
    else:
        state = str(run_status or "unknown").upper()

    return {
        "schema_version": "nightly_retrain_sla_status_v0.1",
        "generated_at_utc": utc_iso(),
        "state": state,
        "task_name": task_name,
        "task_registered": task_registered,
        "task_state": (task_status or {}).get("State"),
        "task_last_run": (task_status or {}).get("Last Run"),
        "task_next_run": (task_status or {}).get("Next Run"),
        "task_result": (task_status or {}).get("Result"),
        "status_path": str(status_path),
        "status_exists": bool(status_payload),
        "run_status": run_status,
        "run_generated_at_utc": run_generated.astimezone(timezone.utc).isoformat() if run_generated else None,
        "run_age_hours": age_hours,
        "fresh_for_latest_window": fresh,
        "schedule_local_time": schedule_local_time,
        "schedule_timezone": schedule_timezone,
        "latest_due_local": latest_due.isoformat(),
        "grace_deadline_local": grace_deadline.isoformat(),
        "missed_run_grace_minutes": missed_run_grace_minutes,
        "daily_learning_status": learning.get("status"),
        "daily_learning_blocker_count": learning.get("blocker_count"),
        "p0_gate": first_blocker.get("signal") or (alerts[0]["message"] if alerts else None),
        "p0_action": first_blocker.get("action"),
        "broad_live_forward_slo_status": broad_slo.get("status"),
        "broad_live_forward_slo_counts": broad_slo.get("counts_toward_live_forward_gate"),
        "broad_live_forward_first_blocker": broad_first_blocker,
        "blockers": blockers,
        "alerts": alerts,
        "remediation_command": (
            "python -m weather.operations.nightly_retrain run "
            "--fail-on-daily-learning-blocker"
        ),
    }


def pipeline_status(steps, promotion, daily_learning=None, *, fail_on_daily_learning_blocker=False):
    if any(step.get("status") == "error" for step in steps):
        return "error"
    if (
        fail_on_daily_learning_blocker
        and (daily_learning or {}).get("status") == "BLOCKED"
    ):
        return "blocked"
    verdict = promotion.get("verdict")
    if verdict in {"promote_ready", "shadow", "blocked"}:
        return verdict
    return "blocked"


def _markdown_cell(value):
    if value in (None, ""):
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(":---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_markdown_cell(value) for value in row) + " |")
    return lines


def render_report(payload):
    promotion = payload.get("promotion") or {}
    learning = payload.get("daily_learning") or {}
    settled = payload.get("settled_day_freshness") or {}
    sla = payload.get("nightly_sla") or {}
    lines = [
        "# Nightly Retrain Validate Promote",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Nightly SLA: `{sla.get('state') or '-'}`",
        f"Settled-day freshness: `{settled.get('status') or '-'}`",
        f"Promotion verdict: `{promotion.get('verdict') or '-'}`",
        f"Daily learning: `{learning.get('status') or '-'}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Return Code | Duration |",
        "| :--- | :--- | ---: | ---: |",
    ]
    for step in payload.get("steps") or []:
        lines.append(
            f"| {step.get('name')} | {step.get('status')} | "
            f"{step.get('returncode')} | {step.get('duration_seconds')} |"
        )
    lines += [
        "",
        "## Promotion",
        "",
        f"- Reason: {promotion.get('reason') or '-'}",
        f"- Promote-ready markets: {', '.join(promotion.get('promote_markets') or []) or '-'}",
        f"- Shadow markets: {', '.join(promotion.get('shadow_markets') or []) or '-'}",
        f"- Blocked markets: {', '.join(promotion.get('blocked_markets') or []) or '-'}",
        f"- Serving gauntlet: {promotion.get('serving_gauntlet_verdict') or '-'}",
        "",
        "## Settled-Day Freshness",
        "",
        f"- Target date: {settled.get('target_date') or '-'}",
        f"- Expected markets: {settled.get('expected_market_count') if settled.get('expected_market_count') is not None else '-'}",
        f"- Complete markets: {settled.get('complete_market_count') if settled.get('complete_market_count') is not None else '-'}",
        f"- Incomplete markets: {settled.get('incomplete_market_count') if settled.get('incomplete_market_count') is not None else '-'}",
        f"- Needs finalization: {settled.get('needs_finalization_count') if settled.get('needs_finalization_count') is not None else '-'}",
        f"- Needs replay-status repair: {settled.get('needs_replay_status_repair_count') if settled.get('needs_replay_status_repair_count') is not None else '-'}",
        f"- Source-lag warnings: {settled.get('source_lag_warning_count') if settled.get('source_lag_warning_count') is not None else '-'}",
        f"- Report: {payload.get('config', {}).get('settled_day_freshness_report') or '-'}",
        f"- Repair command: {settled.get('repair_command') or '-'}",
        f"- Replay-status repair command: {settled.get('replay_status_repair_command') or '-'}",
        "",
        "### First Missing Market",
        "",
    ]
    first_missing = settled.get("first_missing") or {}
    lines += _markdown_table(
        ["Market", "Event", "Missing"],
        [[
            first_missing.get("market_id") or "-",
            first_missing.get("event_slug") or "-",
            ", ".join(first_missing.get("missing_requirements") or []) or "-",
        ]],
    )
    lines += [
        "",
        "## Daily Log Learning",
        "",
        f"- Run date: {learning.get('run_date') or '-'}",
        f"- Learnings: {learning.get('learning_count') if learning.get('learning_count') is not None else '-'}",
        f"- High-priority learnings: {learning.get('high_priority_learning_count') if learning.get('high_priority_learning_count') is not None else '-'}",
        f"- Blockers: {learning.get('blocker_count') if learning.get('blocker_count') is not None else '-'}",
        f"- Training ready: {learning.get('training_ready') if learning.get('training_ready') is not None else '-'}",
        f"- Promotion ready: {learning.get('promotion_ready') if learning.get('promotion_ready') is not None else '-'}",
        f"- Report: {payload.get('config', {}).get('daily_learning_report') or '-'}",
        "",
    ]
    blockers = learning.get("blockers") or []
    if blockers:
        lines += [
            "### Daily-Learning Blockers",
            "",
        ]
        lines += _markdown_table(
            ["Priority", "Category", "Source", "Signal", "Action"],
            [
                [
                    row.get("priority"),
                    row.get("category"),
                    row.get("source"),
                    row.get("signal"),
                    row.get("action"),
                ]
                for row in blockers[:10]
            ],
        )
        lines.append("")
    broad_slo = learning.get("broad_live_forward_slo") or {}
    if broad_slo:
        first = broad_slo.get("first_blocker") or next(
            iter(broad_slo.get("recovery_checklist") or []),
            {},
        )
        lines += [
            "## Broad Live-Forward SLO",
            "",
        ]
        lines += _markdown_table(
            ["Field", "Value"],
            [
                ["Status", broad_slo.get("status") or "-"],
                ["Counts toward live-forward gate", broad_slo.get("counts_toward_live_forward_gate")],
                ["Reason", broad_slo.get("reason") or "-"],
                ["First market", first.get("market_id") or "-"],
                ["First component", first.get("component") or "-"],
                ["First gate", first.get("gate") or "-"],
                ["Owner", first.get("owner") or "-"],
                ["Repair command", first.get("repair_command") or "-"],
                ["Rerun command", broad_slo.get("rerun_command") or first.get("verification_command") or "-"],
            ],
        )
        recovery_rows = [
            [
                row.get("market_id"),
                row.get("component"),
                row.get("gate"),
                row.get("owner"),
                row.get("repair_command"),
            ]
            for row in broad_slo.get("recovery_checklist") or []
        ]
        if recovery_rows:
            lines += ["", "### Recovery Checklist", ""]
            lines += _markdown_table(
                ["Market", "Component", "Gate", "Owner", "Repair Command"],
                recovery_rows[:20],
            )
            lines.append("")
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
    return path


def render_sla_report(payload):
    lines = [
        "# Nightly Retrain SLA Status",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"State: **{payload.get('state')}**",
        f"Task: `{payload.get('task_name')}`",
        f"Status file: `{payload.get('status_path')}`",
        f"Run status: `{payload.get('run_status')}`",
        f"Run generated: `{payload.get('run_generated_at_utc') or '-'}`",
        f"Latest due: `{payload.get('latest_due_local')}`",
        f"Grace deadline: `{payload.get('grace_deadline_local')}`",
        f"P0 gate: `{payload.get('p0_gate') or '-'}`",
        f"Action: `{payload.get('p0_action') or payload.get('remediation_command')}`",
        "",
        "## Alerts",
        "",
    ]
    alerts = payload.get("alerts") or []
    if alerts:
        lines += _markdown_table(
            ["Severity", "Category", "Message"],
            [[row.get("severity"), row.get("category"), row.get("message")] for row in alerts],
        )
    else:
        lines.append("- none")
    blockers = payload.get("blockers") or []
    if blockers:
        lines += ["", "## Daily-Learning Blockers", ""]
        lines += _markdown_table(
            ["Priority", "Category", "Source", "Signal", "Action"],
            [
                [
                    row.get("priority"),
                    row.get("category"),
                    row.get("source"),
                    row.get("signal"),
                    row.get("action"),
                ]
                for row in blockers[:10]
            ],
        )
    lines.append("")
    return "\n".join(lines)


def write_sla_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_sla_report(payload), encoding="utf-8")
    return path


def run_nightly_retrain(args, runner=run_subprocess_step):
    guard_enabled = (
        not getattr(args, "dry_run", False)
        and not getattr(args, "disable_long_job_guard", False)
    )
    with long_job_guard(
        "nightly_retrain",
        state_path=getattr(args, "long_job_state", DEFAULT_LONG_JOB_STATE_PATH),
        lock_path=getattr(args, "long_job_lock", DEFAULT_LONG_JOB_LOCK_PATH),
        priority=getattr(args, "long_job_priority", "below_normal"),
        enabled=guard_enabled,
        force_lock=getattr(args, "force_long_job_lock", False),
    ) as guard:
        return _run_nightly_retrain_guarded(args, runner=runner, long_job_guard_info=guard)


def _run_nightly_retrain_guarded(args, runner=run_subprocess_step, long_job_guard_info=None):
    started = time.time()
    steps = []
    plan = planned_steps(args)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runner": "nightly_retrain",
        "status": "running",
        "generated_at_utc": None,
        "started_at_utc": utc_iso(),
        "finished_at_utc": None,
        "duration_seconds": None,
        "dry_run": bool(args.dry_run),
        "config": {
            "family_unit": args.family_unit,
            "snapshots_root": args.snapshots_root,
            "backtest_root": args.backtest_root,
            "quality_grades": args.quality_grades,
            "pooled_band_artifact": args.pooled_band_artifact,
            "promotion_out": args.promotion_out,
            "labels_csv": args.labels_csv,
            "ledger_root": args.ledger_root,
            "settled_day_freshness_out": args.settled_day_freshness_out,
            "settled_day_freshness_report": args.settled_day_freshness_report,
            "daily_learning_out": args.daily_learning_out,
            "daily_learning_report": args.daily_learning_report,
            "long_job_guard": long_job_guard_info or {},
        },
        "steps": steps,
        "promotion": {},
        "settled_day_freshness": {},
        "daily_learning": {},
        "nightly_sla": {},
    }
    if args.dry_run:
        steps.extend(
            {
                "name": name,
                "command": command,
                "status": "planned",
                "returncode": None,
                "duration_seconds": 0.0,
            }
            for name, command in plan
        )
        payload["status"] = "dry_run"
    else:
        for name, command in plan:
            step = run_step(name, command, args, runner)
            steps.append(step)
            if step["status"] == "error" and not args.continue_on_error:
                break
            if name == "daily_learning" and args.fail_on_daily_learning_blocker:
                payload["daily_learning"] = daily_learning_summary(args.daily_learning_out)
                if payload["daily_learning"].get("status") == "BLOCKED":
                    break
        payload["settled_day_freshness"] = settled_day_freshness_summary(args.settled_day_freshness_out)
        payload["daily_learning"] = daily_learning_summary(args.daily_learning_out)
        ran_steps = {step.get("name") for step in steps}
        if "promotion_refresh" in ran_steps:
            payload["promotion"] = promotion_summary(args.promotion_out)
        else:
            reason = (
                "daily_learning_blocked"
                if payload["daily_learning"].get("status") == "BLOCKED"
                else "promotion_refresh_not_run"
            )
            payload["promotion"] = promotion_not_run_summary(args.promotion_out, reason)
        payload["status"] = pipeline_status(
            steps,
            payload["promotion"],
            payload["daily_learning"],
            fail_on_daily_learning_blocker=args.fail_on_daily_learning_blocker,
        )
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["nightly_sla"] = nightly_run_sla_status(
        status_path=args.status_out,
        status_payload=payload,
        missed_run_grace_minutes=args.missed_run_grace_minutes,
    )
    payload["nightly_sla"]["generated_at_utc"] = payload["generated_at_utc"]
    status_path = write_json(args.status_out, payload)
    report_path = write_report(args.report_out, payload)
    return payload, status_path, report_path


def build_run_parser(parser):
    parser.add_argument("--family-unit", default="F", choices=["F"])
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--status-out", default=str(DEFAULT_STATUS_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--quality-grades", default="complete,manual_override")
    parser.add_argument("--min-trust", type=int, default=25)
    parser.add_argument("--min-settled-days", type=int, default=2)
    parser.add_argument("--holdout-year", type=int, default=2025)
    parser.add_argument("--family-secondary-out", default=str(DEFAULT_FAMILY_SECONDARY_MANIFEST))
    parser.add_argument("--pooled-band-artifact", default=str(DEFAULT_POOLED_BAND_ARTIFACT))
    parser.add_argument("--artifact-registry", default=str(DEFAULT_ARTIFACT_REGISTRY_PATH))
    parser.add_argument("--promotion-out", default=str(DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"))
    parser.add_argument("--promotion-report", default=str(DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh_report.md"))
    parser.add_argument("--daily-learning-out", default=str(DEFAULT_DAILY_LEARNING_OUT))
    parser.add_argument("--daily-learning-report", default=str(DEFAULT_DAILY_LEARNING_REPORT))
    parser.add_argument("--labels-csv", default=str(DEFAULT_LABELS_CSV))
    parser.add_argument("--ledger-root", default=str(DEFAULT_LEDGER_ROOT))
    parser.add_argument("--settled-day-freshness-out", default=str(DEFAULT_SETTLED_DAY_FRESHNESS_OUT))
    parser.add_argument("--settled-day-freshness-report", default=str(DEFAULT_SETTLED_DAY_FRESHNESS_REPORT))
    parser.add_argument("--settled-day-target-date", default="")
    parser.add_argument("--settled-day-as-of", default="")
    parser.add_argument("--settled-day-markets", default="")
    parser.add_argument("--shadow-ab-out", default=str(DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor.json"))
    parser.add_argument("--shadow-ab-report", default=str(DEFAULT_BACKTEST_ROOT / "shadow_ab_monitor_report.md"))
    parser.add_argument("--ab-current-tol", type=float, default=0.003)
    parser.add_argument("--ab-market-tol", type=float, default=0.003)
    parser.add_argument("--step-timeout-seconds", type=float, default=DEFAULT_STEP_TIMEOUT_SECONDS)
    parser.add_argument("--include-reconstructed", action="store_true")
    parser.add_argument("--allow-unsettled", action="store_true")
    parser.add_argument("--require-exact-identity", action="store_true")
    parser.add_argument("--require-all-markets", action="store_true")
    parser.add_argument("--no-baseline", action="store_true")
    parser.add_argument("--skip-family-secondary", action="store_true")
    parser.add_argument("--skip-settled-day-freshness", action="store_true")
    parser.add_argument("--skip-settled-day-polymarket-reconciliation", action="store_true")
    parser.add_argument("--skip-daily-learning", action="store_true")
    parser.add_argument("--skip-pooled-feature", action="store_true")
    parser.add_argument("--skip-artifact-registry", action="store_true")
    parser.add_argument("--skip-promotion-refresh", action="store_true")
    parser.add_argument("--skip-shadow-ab-monitor", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.set_defaults(fail_on_daily_learning_blocker=True)
    parser.add_argument("--fail-on-daily-learning-blocker", dest="fail_on_daily_learning_blocker", action="store_true")
    parser.add_argument("--no-fail-on-daily-learning-blocker", dest="fail_on_daily_learning_blocker", action="store_false")
    parser.add_argument("--fail-on-shadow-ab-alert", action="store_true")
    parser.add_argument("--missed-run-grace-minutes", type=float, default=DEFAULT_MISSED_RUN_GRACE_MINUTES)
    parser.add_argument("--long-job-state", default=str(DEFAULT_LONG_JOB_STATE_PATH))
    parser.add_argument("--long-job-lock", default=str(DEFAULT_LONG_JOB_LOCK_PATH))
    parser.add_argument("--long-job-priority", default="below_normal", choices=["normal", "below_normal", "idle"])
    parser.add_argument("--disable-long-job-guard", action="store_true")
    parser.add_argument("--force-long-job-lock", action="store_true")
    return parser


def cmd_run(args):
    payload, status_path, report_path = run_nightly_retrain(args)
    print(f"Nightly retrain: {payload['status']}")
    print(f"Status written to {status_path}")
    print(f"Report written to {report_path}")
    if payload["status"] == "error":
        return 1
    if args.fail_on_block and payload["status"] in {"blocked", "shadow"}:
        return 2
    return 0


def cmd_status(args):
    payload = nightly_run_sla_status(
        status_path=args.status_path,
        task_name=args.task_name,
        schedule_local_time=args.schedule_local_time,
        schedule_timezone=args.schedule_timezone,
        missed_run_grace_minutes=args.missed_run_grace_minutes,
    )
    json_path = write_json(args.out, payload)
    report_path = write_sla_report(args.report, payload)
    print(f"Nightly retrain SLA: {payload['state']}")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 2 if payload["state"] == "CRITICAL" else 0


def build_parser():
    parser = argparse.ArgumentParser(description="Run nightly retrain, validation, and promotion decision refresh.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = build_run_parser(sub.add_parser("run"))
    run.set_defaults(func=cmd_run)
    status = sub.add_parser("status")
    status.add_argument("--status-path", default=str(DEFAULT_STATUS_OUT))
    status.add_argument("--task-name", default=DEFAULT_TASK_NAME)
    status.add_argument("--schedule-local-time", default=DEFAULT_SCHEDULE_LOCAL_TIME)
    status.add_argument("--schedule-timezone", default=DEFAULT_SCHEDULE_TIMEZONE)
    status.add_argument("--missed-run-grace-minutes", type=float, default=DEFAULT_MISSED_RUN_GRACE_MINUTES)
    status.add_argument("--out", default=str(DEFAULT_SLA_STATUS_OUT))
    status.add_argument("--report", default=str(DEFAULT_SLA_REPORT_OUT))
    status.set_defaults(func=cmd_status)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
