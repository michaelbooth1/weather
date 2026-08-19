"""Inclusive runner and receipt contracts for bounded daily-refresh recovery."""

from __future__ import annotations

from weather.operations.daily_refresh_registry import (
    STEP_ORDER,
    filter_runners_for_resume,
    filter_runners_through_step,
)


def select_bounded_runners(stage_runners, *, resume_from="", stop_after=""):
    resume_from = resume_from or ""
    stop_after = stop_after or ""
    if stop_after and resume_from and (
        STEP_ORDER.index(stop_after) < STEP_ORDER.index(resume_from)
    ):
        raise ValueError(
            f"stop-after step {stop_after} precedes resume step {resume_from}"
        )
    bounded_stage = filter_runners_through_step(stage_runners, stop_after)
    selected = filter_runners_for_resume(bounded_stage, resume_from)
    names = [name for name, _runner in selected] if stop_after else []
    return bounded_stage, selected, names


def bounded_planned_steps(all_planned_steps, selected_runners):
    planned_by_name = {step["name"]: step for step in all_planned_steps}
    return [
        planned_by_name[name]
        for name, _runner in selected_runners
        if name in planned_by_name
    ]


def build_bounded_recovery_receipt(
    payload,
    *,
    step_names,
    resume_from,
    stop_after,
    dry_run,
):
    step_statuses = []
    for name in step_names:
        step = next(
            (
                row
                for row in reversed(payload.get("steps") or [])
                if row.get("name") == name
            ),
            {},
        )
        step_statuses.append(
            {"name": name, "status": str(step.get("status") or "missing").lower()}
        )
    terminal = next(
        (
            row
            for row in reversed(payload.get("steps") or [])
            if row.get("name") == stop_after
        ),
        {},
    )
    terminal_status = str(terminal.get("status") or "missing").lower()
    all_ok = bool(step_statuses) and all(row["status"] == "ok" for row in step_statuses)
    all_planned = bool(step_statuses) and all(
        row["status"] == "planned" for row in step_statuses
    )
    status = (
        "PLANNED"
        if dry_run and all_planned
        else "PASS"
        if terminal_status == "ok" and all_ok
        else "BLOCK"
    )
    return {
        "status": status,
        "resume_from_step": resume_from,
        "stop_after_step": stop_after,
        "terminal_step_status": terminal_status,
        "step_statuses": step_statuses,
        "daily_progress_ledger_written": False,
        "stage_manifest_written": False,
        "evidence_triggered": False,
        "production_readiness_run": False,
    }


def bounded_trigger_skip(config):
    stop_after = (config or {}).get("stop_after_step")
    if not stop_after:
        return None
    return {
        "status": "SKIPPED",
        "reason": "bounded_recovery_run",
        "stop_after_step": stop_after,
    }
