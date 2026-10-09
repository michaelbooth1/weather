"""Observe an explicitly selected portable attempt without loading its inputs.

Only the three fixed stage outputs are read. Manifests, launchers, credentials,
exchange APIs and live gate evaluators are deliberately outside this reader.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re

from weather.reporting.market.operator_evidence import (
    checked_local_path, freshness, parse_timestamp, read_artifact, scalar_fields,
)
from weather.schema_registry import schema_version


STAGES = (
    ("stage0", "Stage 0 · Connection", "stage0"),
    ("stage1_cancel_all", "Stage 1 · Cancel all", "stage1-cancel-all"),
    ("stage1_dead_man", "Stage 1 · Dead man", "stage1-dead-man"),
)
EVENT_FIELDS = ("recorded_at_utc", "event_type", "order_id", "phase",
                "cancellation_mode", "cleanup_succeeded", "zero_open_orders_verified",
                "zero_positions_verified")
RESULT_FIELDS = ("order_id", "order_notional_usdc", "placement_status",
                 "cancellation_observed", "zero_open_orders_verified", "zero_positions_verified",
                 "collateral_no_fill_reconciliation_verified", "market_id", "condition_id",
                 "token_id", "scoped_account_trade_count")


def _receipt(root, relative, stage, schema):
    artifact = read_artifact(root / relative, root=root)
    if not artifact["available"]:
        return artifact
    payload = artifact["payload"]
    try:
        sidecar = checked_local_path(root / (relative + ".sha256"), root=root)
        if sidecar.stat().st_size > 200:
            raise ValueError("Invalid receipt hash sidecar.")
        parts = sidecar.read_text(encoding="ascii").split()
        if parts != [artifact["sha256"], Path(relative).name]:
            raise ValueError("Receipt hash sidecar does not match.")
        if payload.get("schema_version") != schema or payload.get("stage") != stage:
            raise ValueError("Receipt schema or stage does not match.")
    except (OSError, ValueError, UnicodeError) as exc:
        artifact.update(available=False, error=f"Receipt is incomplete or invalid: {exc}")
        artifact.pop("payload", None)
    return artifact


def _journal(root, relative):
    """Read at most 128 KiB of complete trailing lines; project known columns."""
    path = root / relative
    try:
        path = checked_local_path(path, root=root)
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            start = max(0, size - 128 * 1024)
            handle.seek(start)
            raw = handle.read(128 * 1024)
        lines = raw.splitlines(keepends=True)
        if start and lines:
            lines = lines[1:]
        rows = []
        for line in lines[-101:]:
            if not line.endswith(b"\n"):
                continue  # The writer may still be completing its last event.
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError):
                return rows[-100:], "A journal event could not be read."
            if isinstance(row, dict) and row.get("schema_version") == schema_version("mm_live_lifecycle_probe_journal"):
                rows.append(scalar_fields(row, EVENT_FIELDS))
        return rows[-100:], None
    except FileNotFoundError:
        return [], None
    except (OSError, ValueError) as exc:
        return [], str(exc)


def collect_portable_session(attempt_root=None, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not attempt_root:
        return {"configured": False, "stages": [], "events": [],
                "detail": "No portable attempt connected."}
    root = Path(attempt_root)
    if not root.is_absolute() or root.is_symlink():
        return {"configured": True, "stages": [], "events": [],
                "detail": "The attempt must be an absolute local directory without links."}
    stages, events = [], []
    for stage, label, directory in STAGES:
        intent = _receipt(root, f"session/{stage}-run-intent.json", stage,
                          schema_version("international_live_session_run_intent"))
        receipt = _receipt(root, f"session/{stage}-run-receipt.json", stage,
                           schema_version("international_live_session_run"))
        intended = intent.get("payload") or {}
        terminal = receipt.get("payload") or {}
        result = read_artifact(root / directory / "result.json", root=root)
        journal, error = _journal(root, f"{directory}/lifecycle.jsonl") if stage != "stage0" else ([], None)
        for event in journal:
            events.append({"stage": label, **event})
        state = "NO RECEIPT"
        detail = "No launch has been observed for this stage."
        observed_at = None
        if intent["available"]:
            observed_at = intended.get("created_at_local")
            deadline = parse_timestamp(intended.get("run_not_after_local"))
            started = parse_timestamp(observed_at)
            if not started or started > now or not deadline or deadline <= started:
                state, detail = "INVALID", "The launch timing cannot be established."
            elif now >= deadline:
                state, detail = "OUTCOME UNKNOWN", "The launch deadline passed without a valid terminal receipt. Review cleanup evidence."
            else:
                state, detail = "LAUNCH RECORDED", "A launch intent exists; process liveness is not proved."
        if receipt["available"]:
            intent_binding = terminal.get("run_intent")
            intent_binding = intent_binding if isinstance(intent_binding, dict) else {}
            bound = (intent["available"]
                     and intent_binding.get("sha256") == intent.get("sha256")
                     and re.fullmatch(r"[0-9a-f]{64}", str(terminal.get("candidate_sha256") or "")) is not None
                     and terminal.get("candidate_sha256") == intended.get("candidate_sha256")
                     and terminal.get("execution_host_profile") == "portable_execution_v1")
            finished = parse_timestamp(terminal.get("finished_at_local"))
            started = parse_timestamp(intended.get("created_at_local"))
            status = terminal.get("status")
            if bound and finished and started and started <= finished <= now and status in {"PASS", "FAIL", "UNKNOWN", "INTERRUPTED"}:
                state = f"FINISHED · {status}"
                detail = "Terminal outcome recorded. This is historical session evidence."
                observed_at = terminal.get("finished_at_local")
            else:
                state, detail = "INVALID", "Terminal receipt identity or timing does not match the selected attempt."
        elif (root / f"session/{stage}-run-receipt.json").exists():
            detail += " The terminal receipt is incomplete or invalid."
        projection = {}
        if result["available"] and (result.get("payload") or {}).get("schema_version") == schema_version("mm_live_lifecycle_probe"):
            # A result is displayed as reported; only the terminal receipt decides
            # whether the full session has finished. Never infer current exposure.
            projection = scalar_fields(result["payload"], RESULT_FIELDS)
            notional = projection.get("order_notional_usdc")
            if isinstance(notional, bool) or not isinstance(notional, (int, float)):
                projection["order_notional_usdc"] = None
        stages.append({"stage": stage, "label": label, "state": state, "detail": detail,
                       "observed_at": observed_at, "host_id": terminal.get("execution_host_id"),
                       "result": projection, "journal_error": error,
                       "receipt_error": receipt.get("error") if (root / f"session/{stage}-run-receipt.json").exists() else None})
    return {"configured": True, "attempt": root.name, "stages": stages,
            "events": sorted(events, key=lambda row: str(row.get("recorded_at_utc") or ""), reverse=True)[:100],
            "detail": "Selected attempt only. Session outcomes do not establish current account exposure."}


def portable_host_observation(path=None, *, now=None):
    if not path:
        return {"status": "UNAVAILABLE", "detail": "No portable host receipt connected."}
    artifact = read_artifact(path)
    payload = artifact.get("payload") or {}
    if artifact["available"] and payload.get("schema_version") != schema_version("international_live_execution_host_status"):
        return {"status": "INVALID", "detail": "Unsupported portable host receipt schema."}
    age = freshness(artifact, now=now, max_age_seconds=600)
    return {**age, "recorded_status": payload.get("status"),
            "host_id": payload.get("execution_host_id"),
            "flags": payload.get("flags") if isinstance(payload.get("flags"), list) else []}
