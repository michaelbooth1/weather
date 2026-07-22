"""Resource contracts for isolated daily-refresh settlement steps."""

from __future__ import annotations

import os
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from weather.io import write_json_atomic
from weather.operations.capture_resource_gate import (
    available_memory_bytes,
    default_loop_specs,
    inspect_capture_loop,
)
from weather.operations.long_job_guard import process_is_running


MIB = 1024**2
DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB = 1536
DEFAULT_STAGE_A_MAX_COMMIT_PERCENT = 70.0


def _budget(
    timeout_minutes,
    private_mb,
    working_set_mb,
    rationale,
    admission_working_set_bytes=None,
):
    return {
        "isolation": "subprocess",
        "timeout_seconds": int(timeout_minutes * 60),
        "private_memory_max_bytes": int(private_mb * MIB),
        "working_set_max_bytes": int(working_set_mb * MIB),
        "admission_working_set_bytes": (
            None
            if admission_working_set_bytes is None
            else int(admission_working_set_bytes)
        ),
        "rationale": rationale,
    }


# The settlement stage is deliberately explicit: reviewers can tell which
# corpus-owning steps release their address space and which bounded/light steps
# remain in the orchestrator. These limits are containment ceilings, not target
# allocations and not evidence that a step is safe merely because it stayed
# below the ceiling once.
STAGE_A_STEP_RESOURCE_POLICIES = {
    "reanalysis_recent_refresh": {"isolation": "in_process", "rationale": "bounded recent range and per-request timeout"},
    "ingest_quality_gate": _budget(30, 2048, 1536, "multi-source historical quality scan"),
    "event_metadata_validation": {"isolation": "in_process", "rationale": "small configured event registry"},
    "public_wu_settlement_restore": _budget(
        60,
        4096,
        2560,
        "per-market full-history WU normalization rebuild; measured corpus requires isolation",
        admission_working_set_bytes=2048 * MIB,
    ),
    "market_day_labels_finalize": {"isolation": "in_process", "rationale": "one-day settlement finalization"},
    "exchange_economics_rule_drift": {"isolation": "in_process", "rationale": "small rule snapshot comparison"},
    "taker_finalization_watchdog": _budget(
        60,
        5120,
        2048,
        "target-day cumulative taker tapes plus seven-strategy bakeoff and settlement materialization",
    ),
    "taker_edge_permission_map": _budget(45, 2048, 1536, "cumulative taker tapes; streaming aggregation required"),
    "taker_tail_casebook": _budget(30, 2048, 1536, "multi-run taker evidence scan"),
    "maker_paper_score": _budget(
        60,
        4096,
        3072,
        "latest-14-run maker scoring under 512 MiB input preflight",
        admission_working_set_bytes=2048 * MIB,
    ),
    "settlement_source_audit": _budget(45, 3072, 2048, "fleet settlement and prediction lineage scan"),
    "trading_evidence": _budget(45, 3072, 2048, "maker/taker evidence aggregation"),
    "clob_order_book_tiering": _budget(60, 2048, 1536, "CLOB inventory and bounded archive conversion"),
    "replay_status_backfill": _budget(60, 2048, 1536, "market-day replay-status scan"),
    "closed_day_parquet_incremental": _budget(90, 3072, 2048, "incremental closed-day columnar conversion"),
    "hourly_model_performance": _budget(60, 3072, 2048, "hourly probability-row scoring"),
    "ten_minute_model_performance": _budget(60, 3072, 2048, "ten-minute probability-row scoring"),
    "price_free_model_learning": _budget(60, 3072, 2048, "settled-corpus learning summary"),
    "model_market_disagreement_rehydration": _budget(60, 3072, 2048, "disagreement corpus rehydration"),
    "settled_day_analysis_barrier": {"isolation": "in_process", "rationale": "status-only dependency barrier"},
    "runtime_identity_reconciliation": {"isolation": "in_process", "rationale": "manifest identity reconciliation"},
    "live_variant_settlement_scorecard": _budget(60, 3072, 2048, "bounded per-tape live-variant settlement scoring"),
    "fleet_observability": {"isolation": "in_process", "rationale": "reads child resource receipts for fleet status"},
}

STAGE_A_ISOLATED_STEPS = frozenset(
    name
    for name, policy in STAGE_A_STEP_RESOURCE_POLICIES.items()
    if policy.get("isolation") == "subprocess"
)


class StageAResourceDeferred(RuntimeError):
    """A settlement child was not admitted; retry is safe and bounded."""

    def __init__(self, message, payload):
        super().__init__(message)
        self.payload = payload


class StageAChildFailure(RuntimeError):
    """An isolated settlement child failed after admission."""

    def __init__(self, message, payload):
        super().__init__(message)
        self.payload = payload


def step_resource_budget(
    step_name,
    *,
    reserve_mb=DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB,
    max_commit_percent=DEFAULT_STAGE_A_MAX_COMMIT_PERCENT,
):
    reserve_mb = int(reserve_mb)
    max_commit_percent = float(max_commit_percent)
    if reserve_mb < DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB:
        raise ValueError(
            "Stage-A physical reserve may only be made stricter than the "
            f"{DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB} MiB default"
        )
    if (
        not math.isfinite(max_commit_percent)
        or max_commit_percent <= 0
        or max_commit_percent > DEFAULT_STAGE_A_MAX_COMMIT_PERCENT
    ):
        raise ValueError(
            "Stage-A commit ceiling must be finite, positive, and no higher "
            f"than {DEFAULT_STAGE_A_MAX_COMMIT_PERCENT}%"
        )
    policy = dict(STAGE_A_STEP_RESOURCE_POLICIES.get(step_name) or {})
    if policy.get("isolation") != "subprocess":
        return None
    working_set_max_bytes = int(policy["working_set_max_bytes"])
    admission_working_set_bytes = policy.get("admission_working_set_bytes")
    if admission_working_set_bytes is None:
        admission_working_set_bytes = working_set_max_bytes
    admission_working_set_bytes = int(admission_working_set_bytes)
    if not 0 <= admission_working_set_bytes <= working_set_max_bytes:
        raise AssertionError(
            "Stage-A admission working set must be non-negative and no greater "
            "than its containment ceiling"
        )
    policy["step"] = step_name
    policy["admission_working_set_bytes"] = admission_working_set_bytes
    policy["minimum_available_reserve_bytes"] = reserve_mb * MIB
    policy["maximum_host_commit_percent"] = max_commit_percent
    policy["required_available_before_start_bytes"] = (
        policy["minimum_available_reserve_bytes"]
        + admission_working_set_bytes
    )
    return policy


def bounded_resume_command(args, step_name):
    def quote(value):
        return subprocess.list2cmdline([str(value)])

    original = list(getattr(args, "_original_cli_argv", None) or [])
    if original and original[0] in {"run", "repair-stale-locks"}:
        command_args = original
        command_args[0] = "run"
    else:
        command_args = [
            "run",
            "--backtest-root",
            str(Path(args.backtest_root)),
            "--snapshots-root",
            str(Path(args.snapshots_root)),
            "--status-out",
            str(Path(getattr(args, "status_out", Path(args.backtest_root) / "daily_refresh_status.json"))),
            "--report-out",
            str(Path(getattr(args, "report_out", Path(args.backtest_root) / "daily_refresh_report.md"))),
            "--stage",
            str(getattr(args, "stage", "settlement") or "settlement"),
        ]
        target_date = str(getattr(args, "settled_analysis_target_date", "") or "")
        if target_date:
            command_args += ["--settled-analysis-target-date", target_date]

    def remove_option(row, flag, *, takes_value=True):
        cleaned = []
        index = 0
        while index < len(row):
            item = str(row[index])
            if item == flag:
                index += 2 if takes_value and index + 1 < len(row) else 1
                continue
            if takes_value and item.startswith(f"{flag}="):
                index += 1
                continue
            cleaned.append(row[index])
            index += 1
        return cleaned

    for flag in (
        "--resume-from-step",
        "--stage",
        "--settled-analysis-target-date",
        "--stage-a-min-available-reserve-mb",
        "--stage-a-max-commit-percent",
        "--maker-paper-latest-active-runs",
        "--maker-paper-max-input-bytes",
    ):
        command_args = remove_option(command_args, flag)
    for flag in (
        "--run-after-repair",
        "--heavy-step-subprocess",
        "--disable-heavy-step-subprocess",
        "--force-lock",
        "--force-long-job-lock",
    ):
        command_args = remove_option(command_args, flag, takes_value=False)
    command_args += [
        "--stage",
        str(getattr(args, "stage", "settlement") or "settlement"),
    ]
    target_date = str(getattr(args, "settled_analysis_target_date", "") or "")
    if target_date:
        command_args += ["--settled-analysis-target-date", target_date]
    command_args += [
        "--resume-from-step",
        step_name,
        "--heavy-step-subprocess",
        "--stage-a-min-available-reserve-mb",
        str(int(getattr(args, "stage_a_min_available_reserve_mb", DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB))),
        "--stage-a-max-commit-percent",
        str(float(getattr(args, "stage_a_max_commit_percent", DEFAULT_STAGE_A_MAX_COMMIT_PERCENT))),
        "--maker-paper-latest-active-runs",
        str(int(getattr(args, "maker_paper_latest_active_runs", 14))),
        "--maker-paper-max-input-bytes",
        str(int(getattr(args, "maker_paper_max_input_bytes", 512 * MIB))),
    ]
    parts = [
        sys.executable,
        "-m",
        "weather.operations.daily_refresh",
        *command_args,
    ]
    return " ".join(quote(item) for item in parts)


def _loop_receipts(args, *, now, process_checker):
    mode = str(getattr(args, "capture_resource_mode", "live") or "live")
    if mode == "offline_host":
        return [], []
    inspector = getattr(args, "_stage_a_loop_inspector", inspect_capture_loop)
    loops = [
        inspector(spec, now=now, process_checker=process_checker)
        for spec in default_loop_specs(args.snapshots_root)
    ]
    blockers = []
    for loop in loops:
        if mode == "no_live_capture":
            if loop.get("active"):
                blockers.append({
                    "code": "unexpected_live_capture_loop",
                    "loop": loop.get("name"),
                    "state": loop.get("state"),
                })
            continue
        if not loop.get("active"):
            blockers.append({
                "code": "required_capture_loop_inactive",
                "loop": loop.get("name"),
                "state": loop.get("state"),
            })
        if loop.get("degraded") or not loop.get("heartbeat_fresh"):
            blockers.append({
                "code": "capture_loop_not_fresh",
                "loop": loop.get("name"),
                "state": loop.get("state"),
                "degraded_reasons": loop.get("degraded_reasons") or [],
                "heartbeat_age_seconds": loop.get("heartbeat_age_seconds"),
            })
    return loops, blockers


def host_commit_percent():
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            limit = int(status.ullTotalPageFile)
            used = limit - int(status.ullAvailPageFile)
            return 100.0 * used / limit if limit > 0 else None
        except (AttributeError, OSError, ValueError):
            return None
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith(("CommitLimit:", "Committed_AS:")):
                key, value, *_units = line.split()
                values[key.rstrip(":")] = int(value) * 1024
        limit = values.get("CommitLimit")
        used = values.get("Committed_AS")
        return 100.0 * used / limit if limit and used is not None else None
    except (OSError, ValueError):
        return None


def build_stage_a_step_admission(args, step_name, budget, *, phase="before"):
    now = datetime.now(timezone.utc)
    memory_fn = getattr(args, "_stage_a_available_memory_fn", available_memory_bytes)
    commit_fn = getattr(args, "_stage_a_commit_percent_fn", host_commit_percent)
    process_checker = getattr(args, "_stage_a_process_checker", process_is_running)
    available = memory_fn()
    commit_percent = commit_fn()
    reserve = int(budget["minimum_available_reserve_bytes"])
    required = (
        int(budget["required_available_before_start_bytes"])
        if phase == "before"
        else reserve
    )
    blockers = []
    if available is None:
        blockers.append({
            "code": "physical_memory_measurement_unavailable",
            "required_available_bytes": required,
        })
    elif int(available) < required:
        blockers.append({
            "code": "insufficient_physical_availability",
            "available_bytes": int(available),
            "required_available_bytes": required,
            "shortfall_bytes": required - int(available),
        })
    maximum_commit = float(
        budget.get("maximum_host_commit_percent", DEFAULT_STAGE_A_MAX_COMMIT_PERCENT)
    )
    if commit_percent is None:
        blockers.append({
            "code": "host_commit_measurement_unavailable",
            "maximum_commit_percent": maximum_commit,
        })
    elif float(commit_percent) >= maximum_commit:
        blockers.append({
            "code": "host_commit_above_limit",
            "commit_percent": round(float(commit_percent), 3),
            "maximum_commit_percent": maximum_commit,
        })
    loops, loop_blockers = _loop_receipts(
        args,
        now=now,
        process_checker=process_checker,
    )
    blockers.extend(loop_blockers)
    status = "PASS" if not blockers else "BLOCK"
    return {
        "status": status,
        "decision": "ADMIT" if status == "PASS" else "DEFER",
        "phase": phase,
        "step": step_name,
        "generated_at_utc": now.isoformat(),
        "physical_memory": {
            "available_bytes": int(available) if available is not None else None,
            "required_available_bytes": required,
            "minimum_reserve_bytes": reserve,
            "admission_working_set_bytes": int(
                budget["admission_working_set_bytes"]
            ),
            "working_set_budget_bytes": int(budget["working_set_max_bytes"]),
            "decision_uses_physical_availability": True,
        },
        "host_commit": {
            "commit_percent": (
                round(float(commit_percent), 3)
                if commit_percent is not None
                else None
            ),
            "maximum_commit_percent": maximum_commit,
            "decision_uses_commit": True,
        },
        "process_budget": dict(budget),
        "capture_resource_mode": getattr(args, "capture_resource_mode", "live"),
        "capture_loops": loops,
        "blockers": blockers,
    }


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items() if not callable(item)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    if callable(value):
        return None
    return str(value)


def serializable_step_args(args):
    allowed_private = {
        "_daily_refresh_steps_so_far",
        "_daily_refresh_resource_steps",
        "_current_producer_invocation",
        "_current_producer_release_identity",
        "_current_producer_lock_proof",
    }
    return {
        key: json_safe(value)
        for key, value in vars(args).items()
        if key != "func"
        and (not key.startswith("_") or key in allowed_private)
        and not callable(value)
    }


def prepare_step_child_invocation(args, step_name, *, run_id):
    root = Path(args.backtest_root) / "daily_refresh_step_children" / str(run_id)
    arguments_path = root / f"{step_name}.args.json"
    result_path = root / f"{step_name}.result.json"
    payload = {
        "step": step_name,
        "parent_pid": os.getpid(),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "args": serializable_step_args(args),
    }
    write_json_atomic(arguments_path, payload, trailing_newline=True)
    command = [
        sys.executable,
        "-m",
        "weather.operations.daily_refresh_step_child",
        "--step",
        step_name,
        "--args-json",
        str(arguments_path),
        "--result-json",
        str(result_path),
    ]
    return {
        "command": command,
        "args_json": str(arguments_path),
        "result_json": str(result_path),
    }
