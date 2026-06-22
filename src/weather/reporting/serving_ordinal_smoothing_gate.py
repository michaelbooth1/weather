"""Validation gate for the serving ordinal-smoothing train/serve skew fix."""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("serving_ordinal_smoothing_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_PREDAWN_REPAIR = DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair.json"
DEFAULT_CANDIDATE_HOURLY = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json"
)
DEFAULT_CANDIDATE_TEN_MINUTE = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_performance.json"
)
DEFAULT_REPLAY_SUMMARY = (
    DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json"
)
DEFAULT_RETRAIN_LOCATION_GATE = DEFAULT_BACKTEST_ROOT / "pooled_f_retrain_location_gate.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "serving_ordinal_smoothing_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "serving_ordinal_smoothing_gate_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_pickle_dict(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            payload = pickle.load(handle)
    except (OSError, pickle.PickleError, AttributeError, EOFError, ModuleNotFoundError, ImportError):
        return None
    return payload if isinstance(payload, dict) else None


def _mtime_utc(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _status(payload: dict[str, Any] | None, *keys: str) -> str | None:
    payload = payload or {}
    for key in keys or ("status", "verdict"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _passes(value: Any) -> bool:
    return str(value or "").upper() in {"PASS", "READY", "ALLOW", "ALLOWED"}


def _first_blocker(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("gate") or blockers[0].get("category") or "")
    return ""


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def artifact_smoothing_summary(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    artifact = _read_pickle_dict(path)
    models = (artifact or {}).get("models") or {}
    configs: list[dict[str, Any]] = []
    top_config = (artifact or {}).get("ordinal_smoothing")
    if isinstance(top_config, dict):
        configs.append({"scope": "artifact", **top_config})
    for hour, bundle in sorted(models.items(), key=lambda item: str(item[0])):
        config = (bundle or {}).get("ordinal_smoothing") if isinstance(bundle, dict) else None
        if isinstance(config, dict):
            configs.append({"scope": f"hour:{hour}", **config})
    enabled = [config for config in configs if config.get("enabled") is True]
    unsafe = [
        config for config in enabled
        if config.get("sigma") is None or config.get("blend_weight") is None
    ]
    absent_means_disabled = not configs
    return {
        "path": str(path),
        "exists": path.exists(),
        "loaded": bool(artifact),
        "modified_at_utc": _mtime_utc(path),
        "schema_version": (artifact or {}).get("schema_version"),
        "feature_schema_version": (artifact or {}).get("feature_schema_version"),
        "trained_at": (artifact or {}).get("trained_at"),
        "config_count": len(configs),
        "enabled_config_count": len(enabled),
        "unsafe_enabled_config_count": len(unsafe),
        "absent_means_disabled": absent_means_disabled,
        "configs": configs,
    }


def predawn_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    guardrails = list((payload or {}).get("guardrails") or [])
    relevant_guardrails = [
        row for row in guardrails
        if row.get("regime") in {"ramp_midday", "late_day", "lock_in"}
    ]
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": _status(payload),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "guardrails": guardrails,
        "ramp_late_guardrails": relevant_guardrails,
        "ramp_late_guardrails_pass": bool(relevant_guardrails) and all(_passes(row.get("status")) for row in relevant_guardrails),
        "weak_slot_summary": (payload or {}).get("weak_slot_summary") or {},
    }


def candidate_hourly_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_hourly_gate") or {}
    early = gate.get("early_morning") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "variant_ids": (payload or {}).get("variant_ids") or [],
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "early_delta_vs_current": early.get("delta_vs_current"),
        "early_delta_vs_market": early.get("delta_vs_market"),
        "early_logloss_delta_vs_market": early.get("logloss_delta_vs_market"),
        "early_winner_variant_probability": early.get("winner_variant_probability"),
        "early_winner_market_probability": early.get("winner_market_probability"),
    }


def candidate_ten_minute_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    gate = (payload or {}).get("candidate_ten_minute_gate") or {}
    overlap = gate.get("weak_slot_overlap") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "variant_ids": (payload or {}).get("variant_ids") or gate.get("variant_ids") or [],
        "status": gate.get("status"),
        "blocker_count": gate.get("blocker_count", len(gate.get("blockers") or [])),
        "first_blocker": _first_blocker(gate),
        "weak_delta_vs_current": overlap.get("delta_vs_current"),
        "weak_delta_vs_market": overlap.get("delta_vs_market"),
        "weak_logloss_delta_vs_market": overlap.get("logloss_delta_vs_market"),
        "weak_winner_variant_probability": overlap.get("winner_variant_probability"),
        "weak_winner_market_probability": overlap.get("winner_market_probability"),
    }


def replay_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    aggregate = (payload or {}).get("aggregate") or {}
    source = (payload or {}).get("source") or {}
    source_text = source if isinstance(source, str) else ""
    source_dict = source if isinstance(source, dict) else {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "verdict": (payload or {}).get("verdict"),
        "cutover_decision": (payload or {}).get("cutover_decision"),
        "row_export_surrogate": (
            source_dict.get("validation_mode") == "row_export_surrogate"
            or "row_export" in source_text
        ),
        "delta_vs_current": aggregate.get("delta_vs_current"),
        "delta_vs_market": aggregate.get("delta_vs_market"),
        "logloss_delta_vs_market": aggregate.get("logloss_delta_vs_market"),
    }


def retrain_location_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": (payload or {}).get("status"),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "broad_core_model_claim_allowed": (payload or {}).get("broad_core_model_claim_allowed"),
    }


def build_gates(
    *,
    artifact: dict[str, Any],
    predawn: dict[str, Any],
    hourly: dict[str, Any],
    ten_minute: dict[str, Any],
    replay: dict[str, Any],
    retrain_location: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = []
    smoothing_ok = (
        artifact.get("loaded")
        and artifact.get("enabled_config_count", 0) == 0
        and artifact.get("unsafe_enabled_config_count", 0) == 0
    )
    gates.append(_gate(
        "artifact_smoothing_policy",
        "PASS" if smoothing_ok else "BLOCK",
        (
            "artifact has no enabled serving-only ordinal smoothing"
            if smoothing_ok
            else "artifact has enabled or unreadable ordinal smoothing config outside validation evidence"
        ),
        artifact,
    ))

    gates.append(_gate(
        "predawn_weak_slot_repair",
        "PASS" if _passes(predawn.get("status")) and _passes(ten_minute.get("status")) else "BLOCK",
        (
            "predawn repair and candidate 10-minute weak-slot gate passed"
            if _passes(predawn.get("status")) and _passes(ten_minute.get("status"))
            else predawn.get("first_blocker") or ten_minute.get("first_blocker") or "predawn weak-slot evidence is not clear"
        ),
        {
            "predawn_status": predawn.get("status"),
            "candidate_ten_minute_status": ten_minute.get("status"),
            "weak_delta_vs_current": ten_minute.get("weak_delta_vs_current"),
            "weak_delta_vs_market": ten_minute.get("weak_delta_vs_market"),
        },
    ))

    gates.append(_gate(
        "ramp_late_guardrails",
        "PASS" if predawn.get("ramp_late_guardrails_pass") else "BLOCK",
        (
            "ramp, late-day, and lock-in guardrails passed"
            if predawn.get("ramp_late_guardrails_pass")
            else "ramp/late/lock-in guardrails are missing or blocked"
        ),
        {"guardrails": predawn.get("ramp_late_guardrails") or []},
    ))

    gates.append(_gate(
        "candidate_hourly_early_gate",
        "PASS" if _passes(hourly.get("status")) else "BLOCK",
        (
            "candidate hourly early gate passed"
            if _passes(hourly.get("status"))
            else hourly.get("first_blocker") or "candidate hourly early gate is not clear"
        ),
        hourly,
    ))

    replay_pass = replay.get("verdict") == "PASS" and replay.get("cutover_decision") != "DO_NOT_CUT_OVER"
    gates.append(_gate(
        "active_replay_contract",
        "PASS" if replay_pass else "BLOCK",
        (
            "active replay/export contract passed"
            if replay_pass
            else (
                f"replay verdict={replay.get('verdict') or 'missing'}, "
                f"cutover={replay.get('cutover_decision') or 'missing'}"
            )
        ),
        replay,
    ))

    gates.append(_gate(
        "broad_retrain_location_gate",
        "PASS" if _passes(retrain_location.get("status")) and retrain_location.get("broad_core_model_claim_allowed") else "BLOCK",
        (
            "pooled F retrain/location broad-claim gate passed"
            if _passes(retrain_location.get("status")) and retrain_location.get("broad_core_model_claim_allowed")
            else retrain_location.get("first_blocker") or "pooled F retrain/location gate is not clear"
        ),
        retrain_location,
    ))
    return gates


def build_payload(
    *,
    artifact_path: str | Path = DEFAULT_BAND_ARTIFACT,
    predawn_repair: str | Path = DEFAULT_PREDAWN_REPAIR,
    candidate_hourly: str | Path = DEFAULT_CANDIDATE_HOURLY,
    candidate_ten_minute: str | Path = DEFAULT_CANDIDATE_TEN_MINUTE,
    replay: str | Path = DEFAULT_REPLAY_SUMMARY,
    retrain_location_gate: str | Path = DEFAULT_RETRAIN_LOCATION_GATE,
) -> dict[str, Any]:
    artifact = artifact_smoothing_summary(artifact_path)
    predawn = predawn_summary(predawn_repair)
    hourly = candidate_hourly_summary(candidate_hourly)
    ten_minute = candidate_ten_minute_summary(candidate_ten_minute)
    replay_payload = replay_summary(replay)
    retrain_location = retrain_location_summary(retrain_location_gate)
    gates = build_gates(
        artifact=artifact,
        predawn=predawn,
        hourly=hourly,
        ten_minute=ten_minute,
        replay=replay_payload,
        retrain_location=retrain_location,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "ordinal_smoothing_train_serve_skew_fixed": any(
            gate.get("gate") == "artifact_smoothing_policy" and gate.get("status") == "PASS"
            for gate in gates
        ),
        "acceptance_passed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "artifact_path": str(artifact_path),
            "predawn_repair": str(predawn_repair),
            "candidate_hourly": str(candidate_hourly),
            "candidate_ten_minute": str(candidate_ten_minute),
            "replay": str(replay),
            "retrain_location_gate": str(retrain_location_gate),
        },
        "artifact": artifact,
        "predawn_repair": predawn,
        "candidate_hourly": hourly,
        "candidate_ten_minute": ten_minute,
        "replay": replay_payload,
        "retrain_location_gate": retrain_location,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    first = payload.get("first_blocker") or {}
    artifact = payload.get("artifact") or {}
    ten_minute = payload.get("candidate_ten_minute") or {}
    hourly = payload.get("candidate_hourly") or {}
    replay = payload.get("replay") or {}
    lines = [
        "# Serving Ordinal Smoothing Gate",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Schema: `{payload.get('schema_version')}`",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", payload.get("status")],
            ["Ordinal train/serve skew fixed", payload.get("ordinal_smoothing_train_serve_skew_fixed")],
            ["Acceptance passed", payload.get("acceptance_passed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Artifact trained at", artifact.get("trained_at")],
            ["Enabled smoothing configs", artifact.get("enabled_config_count")],
            ["Candidate 10-minute status", ten_minute.get("status")],
            ["Weak-slot delta vs current", fmt_num(ten_minute.get("weak_delta_vs_current"))],
            ["Weak-slot delta vs market", fmt_num(ten_minute.get("weak_delta_vs_market"))],
            ["Candidate hourly status", hourly.get("status")],
            ["Early-hour delta vs market", fmt_num(hourly.get("early_delta_vs_market"))],
            ["Replay verdict", replay.get("verdict")],
            ["Replay delta vs market", fmt_num(replay.get("delta_vs_market"))],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    return "\n".join(lines) + "\n"


def write_outputs(
    payload: dict[str, Any],
    json_out: str | Path = DEFAULT_OUT,
    report_out: str | Path = DEFAULT_REPORT,
) -> tuple[Path, Path]:
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gate serving ordinal-smoothing parity and validation evidence.")
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--predawn-repair", default=str(DEFAULT_PREDAWN_REPAIR))
    parser.add_argument("--candidate-hourly", default=str(DEFAULT_CANDIDATE_HOURLY))
    parser.add_argument("--candidate-ten-minute", default=str(DEFAULT_CANDIDATE_TEN_MINUTE))
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY_SUMMARY))
    parser.add_argument("--retrain-location-gate", default=str(DEFAULT_RETRAIN_LOCATION_GATE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        artifact_path=args.artifact,
        predawn_repair=args.predawn_repair,
        candidate_hourly=args.candidate_hourly,
        candidate_ten_minute=args.candidate_ten_minute,
        replay=args.replay,
        retrain_location_gate=args.retrain_location_gate,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Serving ordinal smoothing gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
