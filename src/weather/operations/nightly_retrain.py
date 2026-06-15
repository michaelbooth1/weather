"""Nightly retrain -> validate -> promote orchestration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from weather.artifacts import DEFAULT_ARTIFACT_REGISTRY_PATH, writable_artifact_path
from weather.operations.long_job_guard import (
    DEFAULT_LOCK_PATH as DEFAULT_LONG_JOB_LOCK_PATH,
    DEFAULT_STATE_PATH as DEFAULT_LONG_JOB_STATE_PATH,
    long_job_guard,
)
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("nightly_retrain")
DEFAULT_BACKTEST_ROOT = Path("data") / "backtest"
DEFAULT_SNAPSHOTS_ROOT = Path("data") / "snapshots"
DEFAULT_STATUS_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_status.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "nightly_retrain_report.md"
DEFAULT_FAMILY_SECONDARY_MANIFEST = writable_artifact_path("f_family_secondary_artifacts.json")
DEFAULT_POOLED_BAND_ARTIFACT = writable_artifact_path("feature_model_hgb_f_pooled_v0_3.pkl")
DEFAULT_TASK_NAME = "WeatherNightlyRetrainValidatePromote"
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
        "src.family_secondary_artifacts",
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


def pooled_feature_command(args):
    return [
        sys.executable,
        "-m",
        "src.pooled_feature_model",
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
        "src.artifacts",
        "registry",
        "--out",
        args.artifact_registry,
    ]


def promotion_refresh_command(args):
    command = [
        sys.executable,
        "-m",
        "src.promotion_refresh",
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
        "src.shadow_ab_monitor",
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


def pipeline_status(steps, promotion):
    if any(step.get("status") == "error" for step in steps):
        return "error"
    verdict = promotion.get("verdict")
    if verdict in {"promote_ready", "shadow", "blocked"}:
        return verdict
    return "blocked"


def render_report(payload):
    promotion = payload.get("promotion") or {}
    lines = [
        "# Nightly Retrain Validate Promote",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: `{payload.get('status')}`",
        f"Promotion verdict: `{promotion.get('verdict') or '-'}`",
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
        f"- Promote-ready markets: {', '.join(promotion.get('promote_markets') or []) or '-'}",
        f"- Shadow markets: {', '.join(promotion.get('shadow_markets') or []) or '-'}",
        f"- Blocked markets: {', '.join(promotion.get('blocked_markets') or []) or '-'}",
        f"- Serving gauntlet: {promotion.get('serving_gauntlet_verdict') or '-'}",
        "",
    ]
    return "\n".join(lines)


def write_report(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(payload), encoding="utf-8")
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
            "long_job_guard": long_job_guard_info or {},
        },
        "steps": steps,
        "promotion": {},
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
        payload["promotion"] = promotion_summary(args.promotion_out)
        payload["status"] = pipeline_status(steps, payload["promotion"])
    payload["finished_at_utc"] = utc_iso()
    payload["generated_at_utc"] = payload["finished_at_utc"]
    payload["duration_seconds"] = round(time.time() - started, 3)
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
    parser.add_argument("--skip-pooled-feature", action="store_true")
    parser.add_argument("--skip-artifact-registry", action="store_true")
    parser.add_argument("--skip-promotion-refresh", action="store_true")
    parser.add_argument("--skip-shadow-ab-monitor", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--fail-on-block", action="store_true")
    parser.add_argument("--fail-on-shadow-ab-alert", action="store_true")
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


def build_parser():
    parser = argparse.ArgumentParser(description="Run nightly retrain, validation, and promotion decision refresh.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = build_run_parser(sub.add_parser("run"))
    run.set_defaults(func=cmd_run)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
