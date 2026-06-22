"""End-of-day flow analysis across model, ops, and trading logs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.io import read_json, read_jsonl, write_json_atomic
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("daily_flow_analysis")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_SNAPSHOTS_ROOT = data_path("snapshots")
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "daily_flow_analysis.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "daily_flow_analysis_report.md"
DEFAULT_ACTIONS_OUT = DEFAULT_BACKTEST_ROOT / "daily_flow_analysis_actions.csv"

ARTIFACT_FILES = {
    "daily_refresh_status": "daily_refresh_status.json",
    "daily_learning": "daily_learning.json",
    "settled_day_root_cause": "settled_day_root_cause.json",
    "daily_progress_latest": "daily_progress_latest.json",
    "fleet_observability": "fleet_observability.json",
    "data_layer_audit": "data_layer_audit.json",
    "snapshot_evaluation": "snapshot_evaluation.json",
    "promotion_refresh": "f_family_promotion_refresh.json",
    "hourly_model_performance": "hourly_model_performance.json",
    "ten_minute_model_performance": "ten_minute_model_performance.json",
    "price_free_model_learning": "price_free_model_learning.json",
    "model_variant_evidence_growth": "model_variant_evidence_growth.json",
}
ARTIFACT_FALLBACK_GLOBS = {
    "settled_day_root_cause": ("settled_day_root_cause_*.json",),
}

PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
ACTION_COLUMNS = [
    "priority",
    "area",
    "owner",
    "source",
    "signal",
    "action",
    "blocks",
    "evidence",
]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def maybe_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_int(value: Any) -> int | None:
    number = maybe_float(value)
    if number is None:
        return None
    return int(round(number))


def _json_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return parsed if isinstance(parsed, list) else [parsed]
    return [value]


def _status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("status")
    if isinstance(value, dict):
        return value.get("status")
    return value


def _artifact_record(name: str, path: Path, payload: Any) -> dict[str, Any]:
    return {
        "name": name,
        "path": str(path),
        "exists": payload is not None,
        "schema_version": payload.get("schema_version") if isinstance(payload, dict) else None,
        "generated_at_utc": payload.get("generated_at_utc") if isinstance(payload, dict) else None,
        "status": _status(payload),
    }


def _latest_matching_artifact(root: Path, pattern: str) -> Path | None:
    candidates = [path for path in root.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def _load_artifact(root: Path, name: str, filename: str) -> tuple[Path, Any]:
    path = root / filename
    payload = read_json(path, default=None)
    if payload is not None:
        return path, payload
    for pattern in ARTIFACT_FALLBACK_GLOBS.get(name, ()):
        fallback_path = _latest_matching_artifact(root, pattern)
        if fallback_path is None:
            continue
        payload = read_json(fallback_path, default=None)
        if payload is not None:
            return fallback_path, payload
    return path, None


def load_inputs(backtest_root=DEFAULT_BACKTEST_ROOT) -> tuple[dict[str, Any], dict[str, Any]]:
    root = Path(backtest_root)
    payloads: dict[str, Any] = {}
    artifacts: dict[str, Any] = {}
    for name, filename in ARTIFACT_FILES.items():
        path, payload = _load_artifact(root, name, filename)
        payloads[name] = payload or {}
        artifacts[name] = _artifact_record(name, path, payload)
    ledger_path = root / "daily_progress_ledger.jsonl"
    ledger_rows = read_jsonl(ledger_path)
    payloads["daily_progress_ledger"] = ledger_rows
    artifacts["daily_progress_ledger"] = {
        "name": "daily_progress_ledger",
        "path": str(ledger_path),
        "exists": bool(ledger_rows),
        "schema_version": ledger_rows[-1].get("schema_version") if ledger_rows else None,
        "generated_at_utc": ledger_rows[-1].get("generated_at_utc") if ledger_rows else None,
        "status": "OK" if ledger_rows else None,
        "row_count": len(ledger_rows),
    }
    return payloads, artifacts


def _priority(value: Any, default: str = "P2") -> str:
    priority = str(value or default).upper()
    return priority if priority in PRIORITY_ORDER else default


def _action(
    priority: str,
    area: str,
    owner: str,
    source: str,
    signal: str,
    action: str,
    *,
    blocks: bool = False,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "priority": _priority(priority),
        "area": area,
        "owner": owner,
        "source": source,
        "signal": signal,
        "action": action,
        "blocks": bool(blocks),
        "evidence": evidence or {},
    }


def _owner_for_learning(row: dict[str, Any]) -> str:
    category = str(row.get("category") or "")
    source = str(row.get("source") or "")
    if "data" in category or "source" in category or source in {"data_layer_audit", "source_family_inventory"}:
        return "data/source owner"
    if "trading" in category or "taker" in category:
        return "trading owner"
    if "market_making" in category or source.startswith("market_making"):
        return "market-making owner"
    if "operational" in category or "slo" in category or source == "fleet_observability":
        return "ops owner"
    if "variant" in category or "experiment" in category:
        return "variant/evidence owner"
    return "model owner"


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    output = []
    for row in sorted(actions, key=lambda item: (PRIORITY_ORDER.get(item.get("priority"), 9), item.get("area", ""))):
        key = (
            row.get("priority"),
            row.get("area"),
            row.get("source"),
            row.get("signal"),
            row.get("action"),
        )
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def _add_daily_learning_actions(actions: list[dict[str, Any]], daily_learning: dict[str, Any]) -> None:
    for row in daily_learning.get("learnings") or []:
        priority = _priority(row.get("priority"))
        if not row.get("blocker") and priority not in {"P0", "P1"}:
            continue
        category = row.get("category") or "daily_learning"
        actions.append(_action(
            priority,
            category,
            _owner_for_learning(row),
            row.get("source") or "daily_learning",
            row.get("signal") or "daily learning signal",
            row.get("action") or "Review daily learning artifact.",
            blocks=bool(row.get("blocker")),
            evidence=row.get("evidence") or {},
        ))


def _add_refresh_step_actions(
    actions: list[dict[str, Any]],
    *,
    daily_refresh: dict[str, Any],
    daily_refresh_steps: list[dict[str, Any]] | None,
) -> None:
    steps = list(daily_refresh_steps or daily_refresh.get("steps") or [])
    for step in steps:
        if step.get("status") != "error":
            continue
        result = step.get("result") or {}
        name = step.get("name") or "unknown_step"
        resume = result.get("resume_command") or f"python -m weather.operations.daily_refresh run --resume-from-step {name}"
        actions.append(_action(
            "P0",
            "refresh_error",
            "ops owner",
            "daily_refresh",
            f"{name} failed: {step.get('error') or step.get('root_cause_class') or 'unknown error'}",
            resume,
            blocks=True,
            evidence={
                "step": name,
                "error": step.get("error"),
                "root_cause_class": step.get("root_cause_class"),
            },
        ))


def _add_progress_actions(actions: list[dict[str, Any]], daily_progress: dict[str, Any]) -> None:
    if not daily_progress:
        return
    failures = _json_list(daily_progress.get("broad_improvement_claim_failures"))
    if daily_progress.get("broad_improvement_claim_allowed") is False and failures:
        actions.append(_action(
            "P1",
            "broad_claim_gate",
            "model/ops owner",
            "daily_progress_latest",
            "Broad improvement claim is not allowed: " + ", ".join(str(item) for item in failures[:6]),
            "Clear the listed claim gates before using broad day-over-day improvement language.",
            blocks=False,
            evidence={"failures": failures},
        ))
    disk_status = daily_progress.get("ops_disk_preflight_status")
    if disk_status == "BLOCK":
        actions.append(_action(
            "P0",
            "disk_headroom",
            "ops owner",
            "daily_progress_latest",
            "Daily refresh disk preflight is BLOCK.",
            "Run data retention cleanup or move artifacts, then rerun daily refresh from the blocked step.",
            blocks=True,
            evidence={
                "free_bytes": daily_progress.get("ops_disk_free_bytes"),
                "required_free_bytes": daily_progress.get("ops_disk_required_free_bytes"),
                "headroom_bytes": daily_progress.get("ops_disk_headroom_bytes"),
            },
        ))


def _add_root_cause_actions(actions: list[dict[str, Any]], root_cause: dict[str, Any]) -> None:
    summary = root_cause.get("summary") or {}
    for row in root_cause.get("new_roadmap_item_candidates") or []:
        actions.append(_action(
            "P1",
            "root_cause_recurrence",
            "roadmap owner",
            "settled_day_root_cause",
            f"{row.get('issue_code')} recurred {row.get('count')} time(s): {row.get('detail') or row.get('classification')}",
            f"Create or reopen owner item: {row.get('suggested_title') or row.get('issue_code')}",
            blocks=False,
            evidence=row,
        ))
    issue_counts = summary.get("issue_counts") or {}
    if root_cause.get("status") == "ACTIONABLE" and issue_counts:
        top_issue, top_count = max(issue_counts.items(), key=lambda item: item[1])
        actions.append(_action(
            "P1",
            "settled_day_root_cause",
            "model/trading owner",
            "settled_day_root_cause",
            f"Top settled-day issue is {top_issue} ({top_count}).",
            "Inspect settled_day_root_cause_report.md and attach the highest-severity evidence to the active owner item.",
            blocks=False,
            evidence={
                "target_date": root_cause.get("target_date"),
                "issue_counts": issue_counts,
            },
        ))


def _add_artifact_gap_actions(actions: list[dict[str, Any]], artifacts: dict[str, Any]) -> None:
    required = ("daily_learning", "daily_refresh_status")
    missing = [name for name in required if not (artifacts.get(name) or {}).get("exists")]
    if missing:
        actions.append(_action(
            "P1",
            "analysis_input_gap",
            "ops owner",
            "daily_flow_analysis",
            "Missing required daily analysis inputs: " + ", ".join(missing),
            "Run python -m weather.operations.daily_refresh run and verify daily_learning.json is produced.",
            blocks=False,
            evidence={"missing_inputs": missing},
        ))


def _step_runtime(steps: list[dict[str, Any]]) -> dict[str, Any]:
    durations = [
        {
            "name": step.get("name"),
            "status": step.get("status"),
            "duration_seconds": maybe_float(step.get("duration_seconds")) or 0.0,
            "error": step.get("error"),
        }
        for step in steps
    ]
    total = sum(row["duration_seconds"] for row in durations)
    slow_steps = sorted(durations, key=lambda item: item["duration_seconds"], reverse=True)[:5]
    status_counts = Counter(row["status"] or "unknown" for row in durations)
    return {
        "step_count": len(durations),
        "total_step_seconds": round(total, 3),
        "status_counts": dict(sorted(status_counts.items())),
        "slow_steps": slow_steps,
        "error_steps": [row for row in durations if row.get("status") == "error"],
    }


def _decision_record(
    *,
    daily_learning: dict[str, Any],
    daily_progress: dict[str, Any],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    retrain = daily_learning.get("retrain_plan") or {}
    scorecard = daily_learning.get("scorecard") or {}
    fleet = scorecard.get("fleet") or {}
    trading = scorecard.get("trading_evidence") or {}
    taker = trading.get("taker") or {}
    mm = trading.get("market_making") or {}
    first_blocker = next((row for row in actions if row.get("blocks")), None)
    first_action = actions[0] if actions else {}
    next_command = (
        (first_blocker or first_action).get("action")
        if actions
        else "python -m weather.operations.nightly_retrain run"
        if retrain.get("training_ready")
        else "python -m weather.operations.daily_refresh run"
    )
    return {
        "training_ready": bool(retrain.get("training_ready")),
        "promotion_ready": bool(retrain.get("promotion_ready")),
        "broad_improvement_claim_allowed": daily_progress.get("broad_improvement_claim_allowed"),
        "live_forward_slo_status": (fleet.get("live_forward_slo") or {}).get("status"),
        "ops_fleet_status": fleet.get("status"),
        "mm_evidence_mode": mm.get("evidence_mode"),
        "mm_counts_toward_live_forward": mm.get("counts_toward_live_forward_gate"),
        "taker_quality_status": (taker.get("quality_gate") or {}).get("status"),
        "taker_net_pnl_usdc": taker.get("net_pnl_usdc"),
        "next_command": next_command,
        "first_blocker": first_blocker or {},
    }


def _area_rollups(actions: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(row.get("area") or "unknown" for row in actions)
    blocking_counts = Counter(row.get("area") or "unknown" for row in actions if row.get("blocks"))
    return {
        "action_counts": dict(sorted(counts.items())),
        "blocking_counts": dict(sorted(blocking_counts.items())),
    }


def _summary(actions: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    priority_counts = Counter(row.get("priority") or "P2" for row in actions)
    blockers = [row for row in actions if row.get("blocks")]
    missing_inputs = [
        name for name, row in artifacts.items()
        if name in {"daily_learning", "daily_refresh_status"} and not row.get("exists")
    ]
    highest = min((row.get("priority") for row in actions), key=lambda item: PRIORITY_ORDER.get(item, 9), default=None)
    return {
        "action_count": len(actions),
        "blocker_count": len(blockers),
        "p0_count": priority_counts.get("P0", 0),
        "p1_count": priority_counts.get("P1", 0),
        "priority_counts": dict(sorted(priority_counts.items())),
        "highest_priority": highest,
        "missing_input_count": len(missing_inputs),
        "missing_inputs": missing_inputs,
        "primary_blocker": blockers[0] if blockers else {},
        **_area_rollups(actions),
    }


def _overall_status(actions: list[dict[str, Any]], artifacts: dict[str, Any]) -> str:
    if not any(row.get("exists") for row in artifacts.values()):
        return "MISSING_INPUTS"
    if any(row.get("blocks") for row in actions):
        return "BLOCKED"
    if actions:
        return "ACTIONABLE"
    return "OK"


def _runbook(actions: list[dict[str, Any]], decision_record: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, row in enumerate(actions[:8], start=1):
        rows.append({
            "order": index,
            "priority": row.get("priority"),
            "area": row.get("area"),
            "command_or_action": row.get("action"),
            "verification": "Rerun python -m weather.operations.daily_refresh run or inspect the linked report.",
        })
    if not rows and decision_record.get("training_ready"):
        rows.append({
            "order": 1,
            "priority": "P2",
            "area": "nightly_retrain",
            "command_or_action": "python -m weather.operations.nightly_retrain run",
            "verification": "Review nightly_retrain status and candidate replay outputs.",
        })
    return rows


def build_flow_analysis(
    *,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    snapshots_root=DEFAULT_SNAPSHOTS_ROOT,
    run_date=None,
    generated_at_utc=None,
    daily_refresh_steps: list[dict[str, Any]] | None = None,
    daily_refresh_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payloads, artifacts = load_inputs(backtest_root)
    daily_refresh = payloads.get("daily_refresh_status") or {}
    daily_learning = payloads.get("daily_learning") or {}
    root_cause = payloads.get("settled_day_root_cause") or {}
    daily_progress = payloads.get("daily_progress_latest") or {}
    steps = list(daily_refresh_steps or daily_refresh.get("steps") or [])

    actions: list[dict[str, Any]] = []
    _add_artifact_gap_actions(actions, artifacts)
    _add_refresh_step_actions(actions, daily_refresh=daily_refresh, daily_refresh_steps=steps)
    _add_daily_learning_actions(actions, daily_learning)
    _add_progress_actions(actions, daily_progress)
    _add_root_cause_actions(actions, root_cause)
    actions = _dedupe_actions(actions)

    generated = generated_at_utc or utc_iso()
    decision_record = _decision_record(
        daily_learning=daily_learning,
        daily_progress=daily_progress,
        actions=actions,
    )
    summary = _summary(actions, artifacts)
    status = _overall_status(actions, artifacts)
    if daily_refresh_summary:
        payloads["daily_refresh_summary"] = daily_refresh_summary
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated,
        "run_date": run_date
        or str(daily_learning.get("run_date") or daily_progress.get("run_date") or generated)[:10],
        "status": status,
        "backtest_root": str(Path(backtest_root)),
        "snapshots_root": str(Path(snapshots_root)),
        "summary": summary,
        "decision_record": decision_record,
        "runtime": _step_runtime(steps),
        "actions": actions,
        "overnight_runbook": _runbook(actions, decision_record),
        "input_artifacts": artifacts,
        "source_rollups": {
            "daily_learning": {
                "status": daily_learning.get("status"),
                "summary": daily_learning.get("summary") or {},
                "retrain_plan": daily_learning.get("retrain_plan") or {},
            },
            "daily_progress_latest": daily_progress,
            "settled_day_root_cause": {
                "status": root_cause.get("status"),
                "target_date": root_cause.get("target_date"),
                "summary": root_cause.get("summary") or {},
                "new_roadmap_item_candidates": root_cause.get("new_roadmap_item_candidates") or [],
            },
            "daily_refresh_summary": daily_refresh_summary or daily_refresh.get("summary") or {},
        },
    }


def _summary_rows(payload: dict[str, Any]) -> list[list[Any]]:
    summary = payload.get("summary") or {}
    decision = payload.get("decision_record") or {}
    return [
        ["Status", payload.get("status")],
        ["Actions", summary.get("action_count")],
        ["Blockers", summary.get("blocker_count")],
        ["P0 / P1", f"{summary.get('p0_count', 0)} / {summary.get('p1_count', 0)}"],
        ["Training ready", decision.get("training_ready")],
        ["Promotion ready", decision.get("promotion_ready")],
        ["Broad claim allowed", decision.get("broad_improvement_claim_allowed")],
        ["Live-forward SLO", decision.get("live_forward_slo_status") or "-"],
        ["Taker quality", decision.get("taker_quality_status") or "-"],
        ["Taker net PnL", fmt_signed(decision.get("taker_net_pnl_usdc"), 2) if decision.get("taker_net_pnl_usdc") is not None else "-"],
        ["Next command/action", decision.get("next_command") or "-"],
    ]


def _action_rows(actions: list[dict[str, Any]], limit: int = 20) -> list[list[Any]]:
    return [
        [
            row.get("priority"),
            row.get("area"),
            row.get("owner"),
            row.get("source"),
            row.get("signal"),
            row.get("action"),
        ]
        for row in actions[:limit]
    ]


def _runtime_rows(runtime: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            row.get("name"),
            row.get("status"),
            fmt_num(row.get("duration_seconds"), 2),
            row.get("error") or "-",
        ]
        for row in runtime.get("slow_steps") or []
    ]


def _runbook_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("order"),
            row.get("priority"),
            row.get("area"),
            row.get("command_or_action"),
            row.get("verification"),
        ]
        for row in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    actions = payload.get("actions") or []
    runtime = payload.get("runtime") or {}
    root = ((payload.get("source_rollups") or {}).get("settled_day_root_cause") or {})
    root_summary = root.get("summary") or {}
    artifacts = payload.get("input_artifacts") or {}
    lines = [
        "# Daily Flow Analysis",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run date: {payload.get('run_date')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Decision Record",
        "",
        *markdown_table(["Field", "Value"], _summary_rows(payload)),
        "",
        "## Priority Action Queue",
        "",
    ]
    if actions:
        lines += markdown_table(
            ["Priority", "Area", "Owner", "Source", "Signal", "Action"],
            _action_rows(actions),
        )
    else:
        lines.append("No blocking or high-priority daily-flow actions were detected.")
    lines += [
        "",
        "## Overnight Runbook",
        "",
    ]
    runbook = payload.get("overnight_runbook") or []
    if runbook:
        lines += markdown_table(
            ["Order", "Priority", "Area", "Command Or Action", "Verification"],
            _runbook_rows(runbook),
        )
    else:
        lines.append("No runbook actions were generated.")
    lines += [
        "",
        "## Settled-Day Root Cause",
        "",
        *markdown_table(
            ["Metric", "Value"],
            [
                ["Status", root.get("status") or "-"],
                ["Target date", root.get("target_date") or "-"],
                ["Issues", root_summary.get("issue_count", 0)],
                ["Issue counts", root_summary.get("issue_counts") or {}],
                ["New roadmap candidates", len(root.get("new_roadmap_item_candidates") or [])],
                ["Taker net PnL", fmt_signed(root_summary.get("taker_net_pnl_usdc"), 2) if root_summary.get("taker_net_pnl_usdc") is not None else "-"],
            ],
        ),
        "",
        "## Runtime",
        "",
        *markdown_table(
            ["Field", "Value"],
            [
                ["Steps", runtime.get("step_count", 0)],
                ["Total step seconds", fmt_num(runtime.get("total_step_seconds"), 2)],
                ["Status counts", runtime.get("status_counts") or {}],
                ["Error steps", len(runtime.get("error_steps") or [])],
            ],
        ),
        "",
        "Slowest steps:",
        "",
        *markdown_table(["Step", "Status", "Seconds", "Error"], _runtime_rows(runtime)),
        "",
        "## Input Artifacts",
        "",
        *markdown_table(
            ["Artifact", "Exists", "Status", "Generated", "Path"],
            [
                [
                    row.get("name"),
                    row.get("exists"),
                    row.get("status") or "-",
                    row.get("generated_at_utc") or "-",
                    row.get("path"),
                ]
                for _name, row in sorted(artifacts.items())
            ],
        ),
        "",
    ]
    return "\n".join(lines)


def write_actions_csv(path: str | Path, actions: list[dict[str, Any]]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTION_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in actions:
            output = dict(row)
            output["evidence"] = json.dumps(output.get("evidence") or {}, sort_keys=True, default=str)
            writer.writerow(output)
    return path


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_JSON_OUT,
    report_out: str | Path = DEFAULT_REPORT_OUT,
    actions_out: str | Path = DEFAULT_ACTIONS_OUT,
) -> tuple[Path, Path, Path]:
    json_path = write_json_atomic(json_out, payload, trailing_newline=True)
    report_path = Path(report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(payload), encoding="utf-8")
    actions_path = write_actions_csv(actions_out, payload.get("actions") or [])
    return json_path, report_path, actions_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the end-of-day flow analysis artifact.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--snapshots-root", default=str(DEFAULT_SNAPSHOTS_ROOT))
    parser.add_argument("--run-date", default="")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    parser.add_argument("--actions-out", default=str(DEFAULT_ACTIONS_OUT))
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_flow_analysis(
        backtest_root=args.backtest_root,
        snapshots_root=args.snapshots_root,
        run_date=args.run_date or None,
    )
    json_out, report_out, actions_out = write_outputs(
        payload,
        json_out=args.json_out,
        report_out=args.report_out,
        actions_out=args.actions_out,
    )
    print(f"Daily flow analysis: {payload['status']}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    print(f"Actions written to {actions_out}")
    return 1 if payload["status"] == "MISSING_INPUTS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
