"""Resource contracts for isolated daily-refresh settlement steps."""

from __future__ import annotations

import os
import math
import subprocess
import sys
import time
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
    "settlement_source_audit": _budget(45, 3072, 2048, "fleet settlement and prediction lineage scan"),
    "trading_evidence": _budget(45, 3072, 2048, "maker/taker evidence aggregation"),
    "clob_order_book_tiering": _budget(60, 2048, 1536, "CLOB inventory and bounded archive conversion"),
    "replay_status_backfill": _budget(60, 2048, 1536, "market-day replay-status scan"),
    "closed_day_parquet_incremental": _budget(90, 3072, 2048, "incremental closed-day columnar conversion"),
    "hourly_model_performance": _budget(60, 3072, 2048, "hourly probability-row scoring"),
    "ten_minute_model_performance": _budget(60, 3072, 2048, "ten-minute probability-row scoring"),
    # 2026-07-25: the child died with MemoryError at 3072 MB. This step aggregates the
    # whole settled corpus, which grows every day, so the ceiling is a moving target and
    # this raise buys weeks, not a fix -- the durable answer is a bounded/streaming
    # aggregation (the module already accepts --start-date/--end-date). Kept modest
    # deliberately: memory pressure is this host's primary streak risk, and the step is
    # a learning summary whose gates BLOCK pre-release anyway.
    "price_free_model_learning": _budget(60, 4096, 2560, "settled-corpus learning summary"),
    "model_market_disagreement_rehydration": _budget(60, 3072, 2048, "disagreement corpus rehydration"),
    "settled_day_analysis_barrier": {"isolation": "in_process", "rationale": "status-only dependency barrier"},
    "runtime_identity_reconciliation": {"isolation": "in_process", "rationale": "manifest identity reconciliation"},
    "live_variant_settlement_scorecard": _budget(60, 3072, 2048, "bounded per-tape live-variant settlement scoring"),
    "fleet_observability": _budget(
        20,
        3072,
        2048,
        "current fleet, tape, provenance, and child-resource summaries; scheduled historical audits and trust replay are disabled",
    ),
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


# Post-step transient-degradation retry (2026-10-23). A capture loop whose only
# degradation is a just-recorded loop error (consecutive_errors and/or
# last_error_present) while its heartbeat stays fresh is usually one failed
# cycle that the next cycle clears. Deferring the whole Stage-A day on that
# single sample cost 10-23 (and likely 10-21) its finalization, so the
# post-step check re-samples for a bounded time before deferring. Everything
# else -- inactive loop, stale or missing heartbeat, any other degraded reason,
# any memory/commit blocker -- still defers immediately.
TRANSIENT_CAPTURE_DEGRADED_REASONS = frozenset({"consecutive_errors", "last_error_present"})
POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS = 30.0
POST_STEP_TRANSIENT_RETRY_MAX_SECONDS = 600.0
# Mirrors scripts/ops/daily_refresh.ps1: the evidence stage tears down at
# 09:00 local, every other stage at 11:55 local, and nothing runs before 00:30.
STAGE_TEARDOWN_LOCAL_MINUTE = {"evidence": 9 * 60}
DEFAULT_STAGE_TEARDOWN_LOCAL_MINUTE = 11 * 60 + 55
STAGE_WINDOW_OPEN_LOCAL_MINUTE = 30


def transient_capture_degradation_only(admission):
    """True when the sole blockers are retryable capture-loop error flags.

    Each blocker must be ``capture_loop_not_fresh`` for a loop that is active,
    has a fresh heartbeat, and whose degraded reasons are a non-empty subset of
    ``TRANSIENT_CAPTURE_DEGRADED_REASONS``. Any other blocker, or a blocker
    without a matching loop receipt, is not transient.
    """
    blockers = list((admission or {}).get("blockers") or [])
    if not blockers:
        return False
    loops = {
        loop.get("name"): loop
        for loop in (admission or {}).get("capture_loops") or []
        if isinstance(loop, dict)
    }
    for blocker in blockers:
        if not isinstance(blocker, dict) or blocker.get("code") != "capture_loop_not_fresh":
            return False
        loop = loops.get(blocker.get("loop"))
        if loop is None:
            return False
        if loop.get("active") is not True or loop.get("heartbeat_fresh") is not True:
            return False
        for reasons in (blocker.get("degraded_reasons"), loop.get("degraded_reasons")):
            reasons = set(reasons or [])
            if not reasons or not reasons <= TRANSIENT_CAPTURE_DEGRADED_REASONS:
                return False
    return True


def stage_teardown_deadline_utc(args, now_utc):
    """The wrapper's child-tree teardown instant for this run, in UTC.

    ``args._stage_a_teardown_deadline_utc`` overrides it (tests, recovery
    slices). Outside the 00:30-deadline window the deadline is ``now_utc``
    itself, so a manual out-of-window run never waits.
    """
    override = getattr(args, "_stage_a_teardown_deadline_utc", None)
    if override is not None:
        return override
    stage = str(getattr(args, "stage", "") or "")
    deadline_minute = STAGE_TEARDOWN_LOCAL_MINUTE.get(stage, DEFAULT_STAGE_TEARDOWN_LOCAL_MINUTE)
    local_now = now_utc.astimezone()
    minute = local_now.hour * 60 + local_now.minute
    if minute < STAGE_WINDOW_OPEN_LOCAL_MINUTE or minute >= deadline_minute:
        return now_utc
    local_deadline = local_now.replace(
        hour=deadline_minute // 60,
        minute=deadline_minute % 60,
        second=0,
        microsecond=0,
    )
    return local_deadline.astimezone(timezone.utc)


def _default_retry_log(message):
    print(message, file=sys.stderr, flush=True)


def _admission_sample(attempt, at_utc, admission):
    return {
        "attempt": attempt,
        "at_utc": at_utc.isoformat(),
        "decision": admission.get("decision"),
        "blockers": [
            {
                key: blocker.get(key)
                for key in ("code", "loop", "state", "degraded_reasons", "heartbeat_age_seconds")
                if key in blocker
            }
            for blocker in admission.get("blockers") or []
            if isinstance(blocker, dict)
        ],
    }


def await_transient_capture_recovery(
    args,
    step_name,
    budget,
    admission,
    *,
    admission_fn=None,
    on_recheck=None,
):
    """Re-sample a transiently degraded post-step admission, bounded by time.

    Returns ``(final_admission, record)``. ``record`` is ``None`` when the
    admission is not eligible (already admitted, or any non-transient
    blocker), in which case ``final_admission`` is the input unchanged.
    Otherwise it re-checks every ``POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS``
    for at most ``POST_STEP_TRANSIENT_RETRY_MAX_SECONDS`` and never past the
    stage teardown deadline, stopping early on a clean admission or on any
    non-transient blocker. ``args._stage_a_now_fn`` / ``_stage_a_sleep_fn`` /
    ``_stage_a_retry_log_fn`` are injectable for tests.
    """
    if admission.get("decision") == "ADMIT" or not transient_capture_degradation_only(admission):
        return admission, None
    admission_fn = admission_fn or build_stage_a_step_admission
    now_fn = getattr(args, "_stage_a_now_fn", None) or (lambda: datetime.now(timezone.utc))
    sleep_fn = getattr(args, "_stage_a_sleep_fn", None) or time.sleep
    log_fn = getattr(args, "_stage_a_retry_log_fn", None) or _default_retry_log
    interval = float(POST_STEP_TRANSIENT_RETRY_INTERVAL_SECONDS)
    started = now_fn()
    deadline = stage_teardown_deadline_utc(args, started)
    remaining_to_deadline = max(0.0, (deadline - started).total_seconds())
    wait_budget = min(float(POST_STEP_TRANSIENT_RETRY_MAX_SECONDS), remaining_to_deadline)
    record = {
        "policy": "post_step_transient_capture_degradation_retry",
        "step": step_name,
        "started_at_utc": started.isoformat(),
        "interval_seconds": interval,
        "max_wait_seconds": float(POST_STEP_TRANSIENT_RETRY_MAX_SECONDS),
        "teardown_deadline_utc": deadline.isoformat(),
        "wait_budget_seconds": round(wait_budget, 3),
        "bounded_by_deadline": wait_budget < float(POST_STEP_TRANSIENT_RETRY_MAX_SECONDS),
        "initial": _admission_sample(0, started, admission),
        "rechecks": [],
        "outcome": None,
        "waited_seconds": 0.0,
    }
    log_fn(
        f"daily_refresh: {step_name} post-step capture check transiently degraded; "
        f"re-checking every {interval:g}s for up to {wait_budget:g}s "
        f"(teardown {deadline.isoformat()})"
    )
    current = admission
    outcome = "deadline_exhausted" if wait_budget < float(POST_STEP_TRANSIENT_RETRY_MAX_SECONDS) else "still_degraded"
    attempt = 0
    while (now_fn() - started).total_seconds() + interval <= wait_budget:
        sleep_fn(interval)
        attempt += 1
        current = admission_fn(args, step_name, budget, phase="after")
        at = now_fn()
        sample = _admission_sample(attempt, at, current)
        record["rechecks"].append(sample)
        log_fn(
            f"daily_refresh: {step_name} post-step re-check {attempt}: "
            f"{current.get('decision')} "
            f"{[blocker.get('code') for blocker in sample['blockers']]}"
        )
        if on_recheck is not None:
            on_recheck(record)
        if current.get("decision") == "ADMIT":
            outcome = "recovered"
            break
        if not transient_capture_degradation_only(current):
            outcome = "non_transient_blocker"
            break
    finished = now_fn()
    record.update({
        "outcome": outcome,
        "finished_at_utc": finished.isoformat(),
        "waited_seconds": round((finished - started).total_seconds(), 3),
        "recheck_count": attempt,
        "final_decision": current.get("decision"),
    })
    log_fn(
        f"daily_refresh: {step_name} post-step transient retry outcome={outcome} "
        f"after {attempt} re-check(s)"
    )
    return current, record


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
