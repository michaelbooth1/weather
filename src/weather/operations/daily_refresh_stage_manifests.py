"""Stage-manifest publication and Stage-B binding for daily refresh."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from weather.io import write_json_atomic
from weather.operations.daily_refresh_lanes import (
    chain_target_settlement_coverage,
    lane_summary,
    promotion_lane_outcome_blocker,
)
from weather.operations.daily_refresh_locks import as_path
from weather.operations.daily_refresh_registry import (
    LANE_PROMOTION,
    STEP_ORDER,
    STEP_PROMOTION_GATES,
    STAGE_EVIDENCE,
    STAGE_SETTLEMENT,
    step_names_for_stage,
)
from weather.operations.daily_refresh_settled_day import settled_analysis_target_date
from weather.paths import data_path
from weather.schema_registry import schema_version


DEFAULT_EVIDENCE_TASK_NAME = "WeatherEveningEvidenceRefresh"
DEFAULT_STAGE_A_MANIFEST = (
    data_path() / "backtest" / "daily_refresh_settlement_truth_manifest.json"
)
DEFAULT_STAGE_B_MANIFEST = (
    data_path() / "backtest" / "daily_refresh_evidence_learning_manifest.json"
)
STAGE_MANIFEST_SCHEMA_VERSION = schema_version("daily_refresh_stage_manifest")


def _stage_manifest_path(args, stage):
    if stage == STAGE_SETTLEMENT:
        return Path(getattr(args, "stage_a_manifest", DEFAULT_STAGE_A_MANIFEST))
    if stage == STAGE_EVIDENCE:
        return Path(getattr(args, "stage_b_manifest", DEFAULT_STAGE_B_MANIFEST))
    return None


def _read_json_payload(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _step_by_name(steps, name):
    return next((step for step in steps or [] if step.get("name") == name), {})


def _stage_barrier_summary(payload):
    barrier_step = _step_by_name(
        payload.get("steps"),
        "settled_day_analysis_barrier",
    )
    result = barrier_step.get("result") or {}
    return {
        "step_status": barrier_step.get("status"),
        "status": result.get("status"),
        "target_date": result.get("target_date"),
        "blocker_count": result.get("blocker_count", 0),
        "json_out": result.get("json_out"),
    }


def _stage_a_binding(manifest):
    return str(
        (manifest or {}).get("run_id")
        or (manifest or {}).get("completed_at_utc")
        or (manifest or {}).get("started_at_utc")
        or ""
    )


def _expected_overnight_stage_a_target(args):
    """Return the only Stage-A target valid for this overnight Stage B."""

    return (settled_analysis_target_date(args) - timedelta(days=1)).isoformat()


def _promotion_receipts_before(step_name, *, names=None):
    end = STEP_ORDER.index(step_name)
    allowed = set(STEP_ORDER[:end] if names is None else names)
    return tuple(
        name
        for name in STEP_ORDER[:end]
        if name in allowed and STEP_PROMOTION_GATES.get(name, False)
    )


def _stage_a_trigger_disposition(args):
    task_name = (
        getattr(args, "evidence_task_name", DEFAULT_EVIDENCE_TASK_NAME)
        or DEFAULT_EVIDENCE_TASK_NAME
    )
    if getattr(args, "disable_stage_trigger", False):
        return {
            "status": "SKIPPED",
            "reason": "disable_stage_trigger",
            "task_name": task_name,
        }
    return {
        "status": "PENDING",
        "reason": "waiting_for_daily_lock_release",
        "task_name": task_name,
    }


def _stage_manifest_payload(
    args,
    payload,
    *,
    stage,
    status_path=None,
    report_path=None,
):
    target_date = getattr(args, "settled_analysis_target_date", "") or ""
    stage_label = (
        "settlement_truth"
        if stage == STAGE_SETTLEMENT
        else "evidence_learning"
    )
    execution_failures = [
        step.get("name")
        for step in payload.get("steps") or []
        if not step.get("carried_forward")
        and step.get("status") in {"error", "deferred"}
    ]
    manifest_status = (
        "INCOMPLETE"
        if stage == STAGE_EVIDENCE and execution_failures
        else "COMPLETED"
        if payload.get("status") in {"ok", "critical"}
        else str(payload.get("status") or "unknown").upper()
    )
    stage_gate = (payload.get("config") or {}).get("stage_gate") or {}
    return {
        "schema_version": STAGE_MANIFEST_SCHEMA_VERSION,
        "run_id": payload.get("run_id") or "",
        "stage": stage,
        "stage_label": stage_label,
        "status": manifest_status,
        "payload_status": payload.get("status"),
        "execution_failure_steps": execution_failures,
        "source_stage_a_binding": (
            stage_gate.get("stage_a_binding") if stage == STAGE_EVIDENCE else ""
        ),
        "target_date": target_date,
        "started_at_utc": payload.get("started_at_utc"),
        "completed_at_utc": payload.get("finished_at_utc"),
        "status_out": as_path(status_path or getattr(args, "status_out", "")),
        "report_out": as_path(report_path or getattr(args, "report_out", "")),
        "step_count": len(payload.get("steps") or []),
        "completed_steps": [
            step.get("name")
            for step in payload.get("steps") or []
            if step.get("status") not in {"error", "deferred", "blocked"}
        ],
        "barrier": _stage_barrier_summary(payload),
        "lanes": payload.get("lanes")
        or lane_summary(args, payload.get("steps") or []),
        "steps": payload.get("steps") or [],
        "invocation": payload.get("invocation") or {},
        "lock_proof": payload.get("lock_proof") or {},
        "sla": payload.get("sla") or {},
        "inside_sla": (payload.get("sla") or {}).get("status") == "PASS",
        "release_identity": payload.get("release_identity") or {},
        "release_id": payload.get("release_id") or "",
        "release_manifest_sha256": payload.get("release_manifest_sha256") or "",
        "release_identity_status": (
            payload.get("release_identity_status") or "unverified"
        ),
    }


def _write_stage_manifest(
    args,
    payload,
    *,
    stage,
    status_path=None,
    report_path=None,
):
    path = _stage_manifest_path(args, stage)
    if path is None:
        return None
    manifest = _stage_manifest_payload(
        args,
        payload,
        stage=stage,
        status_path=status_path,
        report_path=report_path,
    )
    if stage == STAGE_SETTLEMENT and payload.get("status") in {"ok", "critical"}:
        manifest["evidence_trigger"] = _stage_a_trigger_disposition(args)
    write_json_atomic(path, manifest, trailing_newline=True)
    return path, manifest


def _stage_b_start_gate(args):
    target_date = getattr(args, "settled_analysis_target_date", "") or ""
    stage_a_path = Path(
        getattr(args, "stage_a_manifest", DEFAULT_STAGE_A_MANIFEST)
    )
    stage_b_path = Path(
        getattr(args, "stage_b_manifest", DEFAULT_STAGE_B_MANIFEST)
    )
    stage_a = _read_json_payload(stage_a_path)
    if not stage_a:
        return {
            "status": "BLOCK",
            "skip_reason": "missing_stage_a_manifest",
            "target_date": target_date,
            "stage_a_manifest": str(stage_a_path),
        }
    if (
        stage_a.get("schema_version") != STAGE_MANIFEST_SCHEMA_VERSION
        or stage_a.get("stage") != STAGE_SETTLEMENT
    ):
        return {
            "status": "BLOCK",
            "skip_reason": "invalid_stage_a_manifest",
            "target_date": target_date,
            "stage_a_schema_version": stage_a.get("schema_version"),
            "stage_a_stage": stage_a.get("stage"),
            "stage_a_manifest": str(stage_a_path),
        }
    if stage_a.get("target_date") != target_date:
        return {
            "status": "BLOCK",
            "skip_reason": "stale_stage_a_manifest",
            "target_date": target_date,
            "stage_a_target_date": stage_a.get("target_date"),
            "stage_a_manifest": str(stage_a_path),
        }
    if stage_a.get("status") != "COMPLETED":
        return {
            "status": "BLOCK",
            "skip_reason": "stage_a_not_completed",
            "target_date": target_date,
            "stage_a_status": stage_a.get("status"),
            "stage_a_manifest": str(stage_a_path),
        }
    trigger_status = (stage_a.get("evidence_trigger") or {}).get("status")
    if trigger_status == "PENDING":
        return {
            "status": "BLOCK",
            "skip_reason": "stage_a_trigger_disposition_pending",
            "target_date": target_date,
            "stage_a_manifest": str(stage_a_path),
        }
    barrier = stage_a.get("barrier") or {}
    stage_a_binding = _stage_a_binding(stage_a)
    if not stage_a_binding:
        return {
            "status": "BLOCK",
            "skip_reason": "stage_a_binding_missing",
            "target_date": target_date,
            "stage_a_manifest": str(stage_a_path),
        }
    required_stage_a_receipts = tuple(
        name
        for name in step_names_for_stage(STAGE_SETTLEMENT)
        if STEP_PROMOTION_GATES.get(name, False)
    )
    stage_a_promotion_blocker = promotion_lane_outcome_blocker(
        stage_a.get("steps") or [],
        required_names=required_stage_a_receipts,
        target_date=target_date,
    )
    stage_a_target_coverage = chain_target_settlement_coverage(
        args,
        stage_a.get("steps") or [],
    )
    stage_b = _read_json_payload(stage_b_path)
    if (
        stage_b.get("target_date") == target_date
        and stage_b.get("status") == "COMPLETED"
        and stage_b.get("source_stage_a_binding") == stage_a_binding
    ):
        return {
            "status": "SKIP",
            "skip_reason": "stage_b_already_completed",
            "target_date": target_date,
            "stage_b_manifest": str(stage_b_path),
            "completed_at_utc": stage_b.get("completed_at_utc"),
            "completed_status_out": stage_b.get("status_out"),
            "completed_report_out": stage_b.get("report_out"),
        }
    return {
        "status": "RUN",
        "target_date": target_date,
        "stage_a_manifest": str(stage_a_path),
        "stage_b_manifest": str(stage_b_path),
        "stage_a_binding": stage_a_binding,
        "barrier": barrier,
        "promotion_blocker": stage_a_promotion_blocker,
        "target_settlement_coverage": stage_a_target_coverage,
        "required_stage_a_promotion_receipts": list(required_stage_a_receipts),
        "promotion_lane_status": (
            "BLOCKED"
            if stage_a_promotion_blocker
            or (
                ((stage_a.get("lanes") or {}).get(LANE_PROMOTION) or {}).get(
                    "status"
                )
                == "BLOCKED"
            )
            else "OPEN"
        ),
        "learning_mode": stage_a_target_coverage.get(
            "coverage_status",
            "UNKNOWN",
        ),
    }
