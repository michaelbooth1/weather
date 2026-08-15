"""Bounded, content-bound exchange-economics evidence for maker runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from weather.io import write_json_atomic


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _canonical_json_bytes(payload):
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def bind_legs_to_run_snapshots(legs, *, required, platform):
    """Bind legs in two bounded passes to the snapshot frozen by each run."""

    from weather.market import exchange_economics as core

    run_states = {}
    total = 0
    for leg in legs or []:
        total += 1
        folder_text = str(leg.get("run_folder") or "")
        state = run_states.setdefault(folder_text, {
            "leg_count": 0,
            "target_date": None,
            "single_target_date": True,
            "snapshot_id": None,
            "single_snapshot_id": True,
            "snapshot_hash": None,
            "single_snapshot_hash": True,
            "generated_at_utc": None,
            "receipt": None,
        })
        state["leg_count"] += 1
        observations = (
            ("target_date", "single_target_date", str(leg.get("target_date") or "")),
            (
                "snapshot_id",
                "single_snapshot_id",
                str(leg.get("exchange_economics_snapshot_id") or ""),
            ),
            (
                "snapshot_hash",
                "single_snapshot_hash",
                str(leg.get("exchange_economics_hash") or ""),
            ),
        )
        for value_key, consistency_key, observed in observations:
            if state[value_key] is None:
                state[value_key] = observed
            elif state[value_key] != observed:
                state[consistency_key] = False
        if state["generated_at_utc"] is None:
            state["generated_at_utc"] = leg.get("generated_at_utc")

    def load_run_context(folder_text):
        state = run_states[folder_text]
        run_config = (
            _load_json(Path(folder_text) / "run_config.json")
            if folder_text
            else None
        ) or {}
        target_date = (
            state["target_date"]
            if state["single_target_date"] and state["target_date"]
            else None
        )
        captured_path = (
            Path(folder_text) / core.RUN_CAPTURE_FILENAME
            if folder_text
            else Path("__missing_run_folder__") / core.RUN_CAPTURE_FILENAME
        )
        observed_file_sha256 = (
            hashlib.sha256(captured_path.read_bytes()).hexdigest()
            if captured_path.is_file()
            else None
        )
        gate = core.load_exchange_economics_gate(
            captured_path,
            target_date,
            platform=platform,
            now=(run_config.get("created_at_utc") or state["generated_at_utc"]),
            required=required,
        )
        payload = _load_json(captured_path) or {}
        capture = dict(run_config.get("exchange_economics_capture") or {})
        binding_checks = {
            "single_target_date": target_date is not None,
            "capture_declared": (
                capture.get("captured") is True
                and capture.get("status") == "CAPTURED"
                and capture.get("filename") == core.RUN_CAPTURE_FILENAME
            ),
            "capture_file_hash_matches": (
                bool(observed_file_sha256)
                and observed_file_sha256 == capture.get("file_sha256")
            ),
            "capture_snapshot_id_matches": (
                state["single_snapshot_id"]
                and bool(state["snapshot_id"])
                and state["snapshot_id"] == gate.get("snapshot_id")
                and capture.get("snapshot_id") == gate.get("snapshot_id")
            ),
            "capture_snapshot_hash_matches": (
                state["single_snapshot_hash"]
                and bool(state["snapshot_hash"])
                and state["snapshot_hash"]
                == (gate.get("snapshot_hash") or gate.get("exchange_economics_hash"))
                and capture.get("snapshot_hash")
                == (gate.get("snapshot_hash") or gate.get("exchange_economics_hash"))
            ),
            "capture_source_hash_matches": (
                bool(capture.get("source_hash"))
                and capture.get("source_hash") == gate.get("source_hash")
            ),
        }
        if required and not all(binding_checks.values()):
            gate = {
                **gate,
                "required": True,
                "ok": False,
                "status": "BLOCK",
                "evidence_basis": core.STALE_EVIDENCE_BASIS,
                "reason": "paper run lacks an exact content-bound economics capture",
                "missing": [
                    key for key, valid in binding_checks.items() if not valid
                ],
            }
        receipt = state["receipt"]
        if receipt is None:
            receipt = {
                "run_folder": folder_text,
                "target_date": target_date,
                "capture_path": str(captured_path),
                "capture_file_sha256": observed_file_sha256,
                "gate_status": gate.get("status"),
                "gate_reason": gate.get("reason"),
                "binding_checks": binding_checks,
                "leg_count": state["leg_count"],
                "bound_leg_count": 0,
                "missing_leg_count": 0,
            }
            state["receipt"] = receipt
        return payload, gate, receipt

    missing_tokens = set()
    bound = 0
    missing = 0
    source_gate_ok = True
    current_folder = None
    current_context = None

    def bind_one(leg):
        nonlocal bound, current_context, current_folder, missing, source_gate_ok
        folder_text = str(leg.get("run_folder") or "")
        if current_context is None or folder_text != current_folder:
            current_folder = folder_text
            current_context = load_run_context(folder_text)
        payload, gate, receipt = current_context
        coverage = core.bind_legs_to_market_economics([leg], payload, gate=gate)
        bound_count = int(coverage.get("bound_leg_count") or 0)
        missing_count = int(coverage.get("missing_leg_count") or 0)
        bound += bound_count
        missing += missing_count
        source_gate_ok = source_gate_ok and bool(coverage.get("source_gate_ok"))
        receipt["bound_leg_count"] += bound_count
        receipt["missing_leg_count"] += missing_count
        for token_id in coverage.get("missing_token_ids") or []:
            if len(missing_tokens) < 50:
                missing_tokens.add(token_id)

    update_each = getattr(legs, "update_each", None)
    if update_each:
        update_each(bind_one)
    else:
        for leg in legs or []:
            bind_one(leg)
    receipts = [
        state["receipt"]
        for state in run_states.values()
        if state.get("receipt") is not None
    ]
    return {
        "required": bool(required),
        "source_gate_ok": source_gate_ok,
        "platform": platform,
        "run_count": len(run_states),
        "leg_count": total,
        "bound_leg_count": bound,
        "missing_leg_count": missing,
        "missing_token_ids": sorted(missing_tokens),
        "run_receipts": receipts,
        "ok": source_gate_ok and missing == 0,
    }


def capture_run_snapshot(snapshot_path, run_folder, gate):
    """Atomically freeze one validated snapshot inside a maker run."""

    from weather.market import exchange_economics as core

    gate = dict(gate or {})
    if gate.get("required") and not gate.get("ok"):
        return {
            "status": "BLOCK",
            "captured": False,
            "reason": "required exchange-economics gate is not passing",
            "path": None,
        }
    source_path = Path(snapshot_path) if snapshot_path else None
    payload = _load_json(source_path) if source_path else None
    if payload is None:
        return {
            "status": "NOT_CAPTURED",
            "captured": False,
            "reason": "exchange-economics snapshot is unavailable",
            "path": None,
        }

    observed = {
        "snapshot_id": core.snapshot_id(payload),
        "snapshot_hash": core.snapshot_hash(payload),
        "source_hash": core.source_proof_hash(payload),
    }
    expected = {
        "snapshot_id": gate.get("snapshot_id"),
        "snapshot_hash": (
            gate.get("snapshot_hash") or gate.get("exchange_economics_hash")
        ),
        "source_hash": gate.get("source_hash"),
    }
    if gate.get("required") and observed != expected:
        raise RuntimeError(
            "exchange-economics gate identity differs from the snapshot being captured"
        )

    capture_path = Path(run_folder) / core.RUN_CAPTURE_FILENAME
    if capture_path.exists():
        existing = _load_json(capture_path)
        if (
            existing is None
            or _canonical_json_bytes(existing) != _canonical_json_bytes(payload)
        ):
            raise RuntimeError(
                "maker run already binds a different exchange-economics snapshot"
            )
    else:
        write_json_atomic(capture_path, payload, trailing_newline=True)
    return {
        "status": "CAPTURED",
        "captured": True,
        "path": str(capture_path),
        "filename": core.RUN_CAPTURE_FILENAME,
        **observed,
        "file_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
    }
