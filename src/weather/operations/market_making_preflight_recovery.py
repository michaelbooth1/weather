"""Close out market-making preflight remediation incidents.

The command records the supervisor repair commands surfaced by
preflight_remediation.json, optionally executes the allowlisted commands, and
reruns the market-making preflight as a post-repair proof.
"""

from __future__ import annotations

import argparse
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from weather.market.market_making_evidence import EVIDENCE_MODE_AUTO, EVIDENCE_MODE_CHOICES
from weather.market.market_making_run import build_run_once
from weather.market.market_making_run_support import make_run_id, read_json, write_json
from weather.market.mm_policy import utc_now


CLOSEOUT_SCHEMA_VERSION = "mm_preflight_recovery_closeout_v0.1"
CLOSEOUT_FILENAME = "preflight_recovery_closeout.json"
POST_REPAIR_PREFLIGHT_FILENAME = "post_repair_preflight.json"
ALLOWED_COMMAND_PREFIXES = (
    "python -m weather.collection.snapshot_tracker",
    "python -m weather.market.market_microstructure",
    "python -m weather.operations.observation_trigger",
    "python -m weather.reporting.promotion.promotion_refresh",
    "python -m weather.reporting.data_quality.data_layer_audit",
)
OUTPUT_LIMIT = 20000


def _utc_iso(value=None):
    return utc_now(value).astimezone(timezone.utc).isoformat()


def _read_run_artifacts(run_folder):
    run_folder = Path(run_folder)
    run_summary = read_json(run_folder / "run_summary.json", {}) or {}
    run_config = read_json(run_folder / "run_config.json", {}) or {}
    preflight_path = Path(run_summary.get("preflight_path") or run_folder / "preflight.json")
    remediation_path = Path(
        run_summary.get("preflight_remediation_path") or run_folder / "preflight_remediation.json"
    )
    return {
        "run_folder": run_folder,
        "run_summary": run_summary,
        "run_config": run_config,
        "preflight_path": preflight_path,
        "preflight": read_json(preflight_path, {}) or {},
        "remediation_path": remediation_path,
        "remediation": read_json(remediation_path, {}) or {},
    }


def _incident_key(incident):
    parts = [
        incident.get("market_id") or "market",
        incident.get("gate") or "gate",
        incident.get("root_cause") or "root_cause",
    ]
    return ":".join(str(part) for part in parts)


def _group_incident_commands(incidents):
    groups = OrderedDict()
    for incident in incidents:
        command = str(incident.get("suggested_command") or "").strip()
        key = command or "<missing command>"
        group = groups.setdefault(
            key,
            {
                "suggested_command": command,
                "incident_keys": [],
                "market_ids": [],
                "gates": [],
                "root_causes": [],
            },
        )
        group["incident_keys"].append(_incident_key(incident))
        for field, output in (
            ("market_id", "market_ids"),
            ("gate", "gates"),
            ("root_cause", "root_causes"),
        ):
            value = incident.get(field)
            if value and value not in group[output]:
                group[output].append(value)
    return list(groups.values())


def _command_allowed(command):
    return any(str(command or "").startswith(prefix) for prefix in ALLOWED_COMMAND_PREFIXES)


def _trim_output(value):
    text = "" if value is None else str(value)
    if len(text) <= OUTPUT_LIMIT:
        return text
    return text[:OUTPUT_LIMIT] + "\n...[truncated]"


def _command_result(command_group, *, execute, timeout_seconds, cwd):
    command = command_group.get("suggested_command")
    base = {
        **command_group,
        "incident_count": len(command_group.get("incident_keys") or []),
        "allowlisted": _command_allowed(command),
        "execution_requested": bool(execute),
    }
    if not command:
        return {
            **base,
            "action": "skipped",
            "status": "SKIPPED",
            "returncode": None,
            "skip_reason": "preflight remediation did not provide a command",
            "stdout": "",
            "stderr": "",
        }
    if not execute:
        return {
            **base,
            "action": "skipped",
            "status": "SKIPPED",
            "returncode": None,
            "skip_reason": "execution not requested; dry-run closeout recorded the surfaced command",
            "stdout": "",
            "stderr": "",
        }
    if not _command_allowed(command):
        return {
            **base,
            "action": "skipped",
            "status": "SKIPPED",
            "returncode": None,
            "skip_reason": "command is not in the MM preflight recovery allowlist",
            "stdout": "",
            "stderr": "",
        }

    started = _utc_iso()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            shell=True,
            capture_output=True,
            text=True,
            timeout=float(timeout_seconds),
        )
        finished = _utc_iso()
        return {
            **base,
            "action": "executed",
            "status": "PASS" if completed.returncode == 0 else "FAIL",
            "returncode": completed.returncode,
            "started_at_utc": started,
            "finished_at_utc": finished,
            "skip_reason": None,
            "stdout": _trim_output(completed.stdout),
            "stderr": _trim_output(completed.stderr),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            **base,
            "action": "executed",
            "status": "TIMEOUT",
            "returncode": None,
            "started_at_utc": started,
            "finished_at_utc": _utc_iso(),
            "skip_reason": None,
            "stdout": _trim_output(exc.stdout),
            "stderr": _trim_output(exc.stderr),
        }


def _markets_from_run(run_config, run_summary):
    markets = run_config.get("markets")
    if markets:
        return list(markets)
    rows = run_summary.get("markets") or ((run_summary.get("preflight") or {}).get("markets") or [])
    market_ids = [row.get("market_id") for row in rows if row.get("market_id")]
    return market_ids or None


def _post_repair_run_id(original_run_id, now):
    base = str(original_run_id or "mm-run")
    stamp = make_run_id(now)
    return f"{base}-postrepair-{stamp}"


def _path_arg(payload, key):
    value = payload.get(key)
    return Path(value) if value else None


def _post_repair_kwargs(artifacts, now, *, allow_live_pilot):
    run_folder = artifacts["run_folder"]
    run_config = artifacts["run_config"]
    run_summary = artifacts["run_summary"]
    mode = run_config.get("mode") or run_summary.get("mode") or "shadow"
    if mode == "live-pilot" and not allow_live_pilot:
        return None, "live-pilot post-repair rerun requires --allow-live-pilot-rerun"

    evidence_mode = run_config.get("evidence_mode") or run_summary.get("evidence_mode") or EVIDENCE_MODE_AUTO
    if evidence_mode not in EVIDENCE_MODE_CHOICES:
        evidence_mode = EVIDENCE_MODE_AUTO

    kwargs = {
        "mode": mode,
        "markets": _markets_from_run(run_config, run_summary),
        "runs_root": run_folder.parent.parent,
        "run_id": _post_repair_run_id(run_summary.get("run_id") or run_config.get("run_id") or run_folder.name, now),
        "policy_config": run_config.get("policy_config") or {},
        "now": now,
        "evidence_mode": evidence_mode,
    }
    path_map = {
        "snapshots_root": "snapshots_root",
        "promotion_refresh": "promotion_refresh",
        "known_edge_map": "known_edge_map",
        "observation_status_path": "observation_status_path",
    }
    for arg_name, config_key in path_map.items():
        path = _path_arg(run_config, config_key)
        if path is not None:
            kwargs[arg_name] = path
    budget = run_config.get("budget_usdc") or run_summary.get("budget_usdc") or 0.0
    target_date = run_config.get("target_date") or run_summary.get("target_date")
    return {
        "target_date": target_date,
        "budget_usdc": float(budget),
        "kwargs": kwargs,
    }, None


def _summarize_post_repair(post_payload):
    if not post_payload:
        return {}
    return {
        "run_id": post_payload.get("run_id"),
        "target_date": post_payload.get("target_date"),
        "run_folder": post_payload.get("run_folder"),
        "preflight_path": post_payload.get("preflight_path"),
        "preflight_status": post_payload.get("preflight_status"),
        "live_forward_gate_status": post_payload.get("live_forward_gate_status"),
        "counts_toward_live_forward_gate": post_payload.get("counts_toward_live_forward_gate"),
        "quote_permission_rows": post_payload.get("quote_permission_rows"),
        "live_trade_permission_rows": post_payload.get("live_trade_permission_rows"),
        "preflight_remediation": post_payload.get("preflight_remediation"),
    }


def _write_post_repair_artifact(run_folder, closeout_now, original_run_id, post_payload):
    post_summary = _summarize_post_repair(post_payload)
    preflight = read_json(post_summary.get("preflight_path"), {}) if post_summary.get("preflight_path") else {}
    artifact = {
        "schema_version": CLOSEOUT_SCHEMA_VERSION,
        "generated_at_utc": closeout_now,
        "original_run_id": original_run_id,
        "post_repair_run": post_summary,
        "preflight": preflight or {},
    }
    path = Path(run_folder) / POST_REPAIR_PREFLIGHT_FILENAME
    write_json(path, artifact)
    return str(path), artifact


def _closeout_status(incident_count, post_repair, rerun_skip_reason):
    if not incident_count:
        return "NO_INCIDENTS"
    if rerun_skip_reason:
        return "RECOVERY_COMMANDS_RECORDED_NO_RERUN"
    if not post_repair:
        return "RECOVERY_COMMANDS_RECORDED_NO_RERUN"
    if post_repair.get("counts_toward_live_forward_gate") and post_repair.get("preflight_status") == "PASS":
        return "RECOVERED"
    return "ATTEMPTED_UNRECOVERED"


def close_out_preflight_recovery(
    run_folder,
    *,
    execute_remediation=False,
    rerun_preflight=True,
    now=None,
    timeout_seconds=300,
    allow_live_pilot=False,
):
    """Write a closeout artifact for a failed MM preflight run."""

    artifacts = _read_run_artifacts(run_folder)
    run_folder = artifacts["run_folder"]
    run_summary = artifacts["run_summary"]
    closeout_now_dt = utc_now(now)
    closeout_now = closeout_now_dt.astimezone(timezone.utc).isoformat()
    incidents = artifacts["remediation"].get("incidents") or []
    command_groups = _group_incident_commands(incidents)
    command_results = [
        _command_result(
            command_group,
            execute=execute_remediation,
            timeout_seconds=timeout_seconds,
            cwd=Path.cwd(),
        )
        for command_group in command_groups
    ]

    post_repair_payload = None
    post_repair_artifact_path = None
    rerun_skip_reason = None
    if incidents and rerun_preflight:
        post_args, rerun_skip_reason = _post_repair_kwargs(
            artifacts,
            closeout_now_dt,
            allow_live_pilot=allow_live_pilot,
        )
        if post_args and post_args.get("target_date"):
            post_repair_payload = build_run_once(
                post_args["target_date"],
                post_args["budget_usdc"],
                **post_args["kwargs"],
            )
            post_repair_artifact_path, _artifact = _write_post_repair_artifact(
                run_folder,
                closeout_now,
                run_summary.get("run_id") or artifacts["run_config"].get("run_id") or run_folder.name,
                post_repair_payload,
            )
        elif rerun_skip_reason is None:
            rerun_skip_reason = "run config did not include a target date"
    elif incidents:
        rerun_skip_reason = "post-repair rerun disabled by operator"
    else:
        rerun_skip_reason = "no preflight remediation incidents to close out"

    post_repair = _summarize_post_repair(post_repair_payload)
    status = _closeout_status(len(incidents), post_repair, rerun_skip_reason if not post_repair else None)
    recovered = status == "RECOVERED"
    closeout_path = run_folder / CLOSEOUT_FILENAME
    payload = {
        "schema_version": CLOSEOUT_SCHEMA_VERSION,
        "generated_at_utc": closeout_now,
        "run_folder": str(run_folder),
        "run_id": run_summary.get("run_id") or artifacts["run_config"].get("run_id") or run_folder.name,
        "target_date": run_summary.get("target_date") or artifacts["run_config"].get("target_date"),
        "original_preflight_path": str(artifacts["preflight_path"]),
        "original_preflight_status": artifacts["preflight"].get("status") or run_summary.get("preflight_status"),
        "preflight_remediation_path": str(artifacts["remediation_path"]),
        "preflight_remediation_status": artifacts["remediation"].get("status"),
        "incident_count": len(incidents),
        "execution_requested": bool(execute_remediation),
        "command_results": command_results,
        "post_repair_rerun_requested": bool(rerun_preflight),
        "post_repair_rerun_skip_reason": rerun_skip_reason if not post_repair else None,
        "post_repair_preflight_artifact_path": post_repair_artifact_path,
        "post_repair_run": post_repair,
        "status": status,
        "recovered": recovered,
        "unrecovered": bool(len(incidents) and not recovered),
    }
    write_json(closeout_path, payload)

    if run_summary:
        run_summary["preflight_recovery_closeout_path"] = str(closeout_path)
        run_summary["post_repair_preflight_path"] = post_repair_artifact_path
        run_summary["preflight_recovery_closeout"] = {
            "schema_version": CLOSEOUT_SCHEMA_VERSION,
            "generated_at_utc": closeout_now,
            "status": status,
            "recovered": recovered,
            "unrecovered": bool(len(incidents) and not recovered),
            "incident_count": len(incidents),
            "command_count": len(command_results),
            "execution_requested": bool(execute_remediation),
            "path": str(closeout_path),
            "post_repair_preflight_artifact_path": post_repair_artifact_path,
            "post_repair_run": post_repair,
        }
        write_json(run_folder / "run_summary.json", run_summary)

    return payload


def build_parser():
    parser = argparse.ArgumentParser(
        description="Close out an MM preflight remediation run and rerun post-repair preflight."
    )
    parser.add_argument("--run-folder", required=True, help="Original MM run folder to close out.")
    parser.add_argument(
        "--execute-remediation",
        action="store_true",
        help="Execute allowlisted surfaced remediation commands instead of recording a dry-run skip.",
    )
    parser.add_argument("--no-rerun", action="store_true", help="Record commands without rerunning MM preflight.")
    parser.add_argument("--now", default=None, help="Testing/replay timestamp for the closeout and rerun.")
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument(
        "--allow-live-pilot-rerun",
        action="store_true",
        help="Allow a post-repair rerun when the original run mode was live-pilot.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = close_out_preflight_recovery(
        args.run_folder,
        execute_remediation=args.execute_remediation,
        rerun_preflight=not args.no_rerun,
        now=args.now,
        timeout_seconds=args.timeout_seconds,
        allow_live_pilot=args.allow_live_pilot_rerun,
    )
    print(
        "MM preflight recovery closeout: "
        f"{payload['status']} -> {Path(payload['run_folder']) / CLOSEOUT_FILENAME}"
    )
    return payload


if __name__ == "__main__":
    main()
