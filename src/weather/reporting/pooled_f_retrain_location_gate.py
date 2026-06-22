"""Broad-claim gate for the active pooled F retrain/re-export lane."""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.calibration.pooled_feature_model import DEFAULT_BAND_ARTIFACT
from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("pooled_f_retrain_location_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_TRAINING_REPORT = DEFAULT_BACKTEST_ROOT / "f_family_pooled_band_model_v0_3_report.md"
DEFAULT_CANDIDATE_REPLAY = DEFAULT_BACKTEST_ROOT / "pooled_candidate_replay_latest.json"
DEFAULT_PROMOTION_REFRESH = DEFAULT_BACKTEST_ROOT / "f_family_promotion_refresh.json"
DEFAULT_PREDAWN_REPAIR = DEFAULT_BACKTEST_ROOT / "pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair.json"
DEFAULT_BOTTOM_LOCATION = DEFAULT_BACKTEST_ROOT / "bottom_location_winner_centering.json"
DEFAULT_EXACT_DISTANCE = DEFAULT_BACKTEST_ROOT / "exact_band_distance_zero_calibration.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "pooled_f_retrain_location_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "pooled_f_retrain_location_gate_report.md"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_mtime_utc(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


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


def _read_text(path: str | Path | None) -> str:
    if not path:
        return ""
    path = Path(path)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


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


def _status_from_payload(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    for key in ("status", "verdict", "gate_status"):
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _passes_status(status: str | None) -> bool:
    return str(status or "").upper() in {"PASS", "READY", "ALLOW", "ALLOWED"}


def _first_blocker_detail(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    first = payload.get("first_blocker") or {}
    if isinstance(first, dict) and first.get("detail"):
        return str(first.get("detail"))
    blockers = payload.get("blockers") or []
    if blockers and isinstance(blockers[0], dict):
        return str(blockers[0].get("detail") or blockers[0].get("category") or "")
    return ""


def _gate(name: str, status: str, detail: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "gate": name,
        "status": status,
        "detail": detail,
        "evidence": evidence or {},
    }


def artifact_summary(artifact_path: str | Path) -> dict[str, Any]:
    path = Path(artifact_path)
    artifact = _read_pickle_dict(path)
    blocked_validation = (artifact or {}).get("blocked_validation") or {}
    models = (artifact or {}).get("models") or {}
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
        "modified_at_utc": _path_mtime_utc(path),
        "loaded": bool(artifact),
        "schema_version": (artifact or {}).get("schema_version"),
        "feature_schema_version": (artifact or {}).get("feature_schema_version"),
        "active_feature_schema_version": FEATURE_SCHEMA_VERSION,
        "trained_at": (artifact or {}).get("trained_at"),
        "family_unit": (artifact or {}).get("family_unit"),
        "objective": (artifact or {}).get("objective"),
        "prediction_mode": (artifact or {}).get("prediction_mode"),
        "hour_models": sorted(str(hour) for hour in models.keys()),
        "blocked_validation": blocked_validation,
    }


def training_report_summary(report_path: str | Path) -> dict[str, Any]:
    path = Path(report_path)
    text = _read_text(path)
    has_blocked_validation = "Blocked Validation Audit" in text
    has_pass = "| PASS |" in text or "Audit |" in text and "PASS" in text
    return {
        "path": str(path),
        "exists": path.exists(),
        "modified_at_utc": _path_mtime_utc(path),
        "has_blocked_validation_section": has_blocked_validation,
        "mentions_pass": has_pass,
    }


def replay_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    artifact = (payload or {}).get("artifact") or {}
    blocked_validation = (payload or {}).get("blocked_validation") or artifact.get("blocked_validation") or {}
    aggregate = (payload or {}).get("aggregate") or {}
    daily_first = (payload or {}).get("daily_first") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at": (payload or {}).get("generated_at") or (payload or {}).get("generated_at_utc"),
        "verdict": (payload or {}).get("verdict"),
        "candidate_market_verdict": (payload or {}).get("candidate_market_verdict"),
        "cutover_decision": (payload or {}).get("cutover_decision"),
        "artifact_hash": artifact.get("artifact_hash"),
        "artifact_path": artifact.get("path") or artifact.get("artifact_path"),
        "artifact_feature_schema_version": artifact.get("feature_schema_version"),
        "blocked_validation_verdict": blocked_validation.get("verdict"),
        "blocked_validation_reasons": blocked_validation.get("reasons") or [],
        "aggregate_delta_vs_current": aggregate.get("delta_vs_current"),
        "aggregate_delta_vs_market": aggregate.get("delta_vs_market"),
        "daily_first_delta_vs_current": daily_first.get("delta_vs_current"),
        "daily_first_delta_vs_market": daily_first.get("delta_vs_market"),
    }


def promotion_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    readiness = (payload or {}).get("readiness") or {}
    claims = ((payload or {}).get("model_skill_claims") or {}).get("weather_only_core_model") or {}
    early = (payload or {}).get("early_hour_promotion_blocker") or {}
    source_gate = (payload or {}).get("source_missingness_location_gate") or {}
    decisions = (payload or {}).get("decisions") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "readiness_status": readiness.get("status"),
        "readiness_blocker_count": len(readiness.get("blockers") or []),
        "first_readiness_blocker": _first_blocker_detail(readiness),
        "broad_market_skill_claim_allowed": claims.get("broad_market_skill_claim_allowed"),
        "claim_reason": claims.get("reason"),
        "claim_delta_vs_market": claims.get("delta_vs_market"),
        "claim_daily_first_passed": claims.get("daily_first_passed"),
        "early_hour_status": early.get("status"),
        "early_hour_promotion_allowed": early.get("promotion_allowed"),
        "early_hour_blocker_count": early.get("blocker_count"),
        "first_early_hour_blocker": _first_blocker_detail(early),
        "source_missingness_status": source_gate.get("status"),
        "source_missingness_blocker_count": len(source_gate.get("blockers") or []),
        "first_source_missingness_blocker": _first_blocker_detail(source_gate),
        "decision_action_counts": decisions.get("action_counts") or {},
        "blocked_markets": decisions.get("blocked_markets") or [],
        "promote_markets": decisions.get("promote_markets") or [],
    }


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": (payload or {}).get("schema_version"),
        "generated_at_utc": (payload or {}).get("generated_at_utc"),
        "status": _status_from_payload(payload),
        "blocker_count": (payload or {}).get("blocker_count", len((payload or {}).get("blockers") or [])),
        "first_blocker": _first_blocker_detail(payload),
        "summary": (payload or {}).get("summary") or {},
    }


def build_gates(
    *,
    artifact: dict[str, Any],
    training_report: dict[str, Any],
    replay: dict[str, Any],
    promotion: dict[str, Any],
    predawn_repair: dict[str, Any],
    bottom_location: dict[str, Any],
    exact_distance: dict[str, Any],
) -> list[dict[str, Any]]:
    gates = []
    artifact_schema = artifact.get("feature_schema_version")
    active_schema = artifact.get("active_feature_schema_version")
    gates.append(_gate(
        "artifact_runtime_schema",
        "PASS" if artifact.get("loaded") and artifact_schema == active_schema else "BLOCK",
        (
            f"artifact feature schema matches active runtime schema {active_schema}"
            if artifact.get("loaded") and artifact_schema == active_schema
            else f"artifact feature schema {artifact_schema or 'missing'} does not match active runtime schema {active_schema}"
        ),
        {
            "artifact_path": artifact.get("path"),
            "artifact_feature_schema_version": artifact_schema,
            "active_feature_schema_version": active_schema,
            "trained_at": artifact.get("trained_at"),
        },
    ))

    blocked_validation = artifact.get("blocked_validation") or {}
    validation_ok = bool(blocked_validation.get("ok") is True)
    report_ok = bool(training_report.get("exists") and training_report.get("has_blocked_validation_section"))
    gates.append(_gate(
        "training_validation_provenance",
        "PASS" if validation_ok and report_ok else "BLOCK",
        (
            "artifact and training report include blocked-validation provenance"
            if validation_ok and report_ok
            else "missing artifact/report blocked-validation provenance"
        ),
        {
            "artifact_blocked_validation_ok": blocked_validation.get("ok"),
            "training_report": training_report,
        },
    ))

    replay_pass = replay.get("verdict") == "PASS" and replay.get("blocked_validation_verdict") == "PASS"
    gates.append(_gate(
        "paired_candidate_replay",
        "PASS" if replay_pass else "BLOCK",
        (
            "paired replay and daily-first blocked validation passed"
            if replay_pass
            else (
                f"candidate replay verdict={replay.get('verdict') or 'missing'}, "
                f"blocked_validation={replay.get('blocked_validation_verdict') or 'missing'}, "
                f"cutover={replay.get('cutover_decision') or 'missing'}"
            )
        ),
        replay,
    ))

    broad_allowed = promotion.get("broad_market_skill_claim_allowed") is True
    readiness_pass = _passes_status(promotion.get("readiness_status"))
    gates.append(_gate(
        "promotion_refresh_broad_claim",
        "PASS" if broad_allowed and readiness_pass else "BLOCK",
        (
            "promotion refresh allows the weather-only broad skill claim"
            if broad_allowed and readiness_pass
            else promotion.get("claim_reason")
            or promotion.get("first_readiness_blocker")
            or "promotion refresh does not allow broad weather-only claims"
        ),
        promotion,
    ))

    early_pass = _passes_status(promotion.get("early_hour_status")) and promotion.get("early_hour_promotion_allowed") is not False
    gates.append(_gate(
        "hourly_ten_minute_weak_slot_gate",
        "PASS" if early_pass else "BLOCK",
        (
            "hourly and ten-minute weak-slot promotion gate passed"
            if early_pass
            else promotion.get("first_early_hour_blocker") or "hourly/ten-minute weak-slot promotion gate is not clear"
        ),
        {
            "early_hour_status": promotion.get("early_hour_status"),
            "early_hour_promotion_allowed": promotion.get("early_hour_promotion_allowed"),
            "early_hour_blocker_count": promotion.get("early_hour_blocker_count"),
        },
    ))

    gates.append(_gate(
        "predawn_repair_gate",
        "PASS" if _passes_status(predawn_repair.get("status")) else "BLOCK",
        (
            "predawn weak-slot repair gate passed"
            if _passes_status(predawn_repair.get("status"))
            else predawn_repair.get("first_blocker") or "predawn weak-slot repair gate is not clear"
        ),
        predawn_repair,
    ))

    gates.append(_gate(
        "bottom_location_gate",
        "PASS" if _passes_status(bottom_location.get("status")) else "BLOCK",
        (
            "bottom-location winner-centering gate passed"
            if _passes_status(bottom_location.get("status"))
            else bottom_location.get("first_blocker") or "bottom-location winner-centering gate is not clear"
        ),
        bottom_location,
    ))

    gates.append(_gate(
        "exact_band_distance_zero_gate",
        "PASS" if _passes_status(exact_distance.get("status")) else "BLOCK",
        (
            "exact-band and settlement-distance-0 gate passed"
            if _passes_status(exact_distance.get("status"))
            else exact_distance.get("first_blocker") or "exact-band and settlement-distance-0 gate is not clear"
        ),
        exact_distance,
    ))

    gates.append(_gate(
        "source_missingness_location_gate",
        "PASS" if _passes_status(promotion.get("source_missingness_status")) else "BLOCK",
        (
            "source/missingness location gate passed"
            if _passes_status(promotion.get("source_missingness_status"))
            else promotion.get("first_source_missingness_blocker") or "source/missingness location gate is not clear"
        ),
        {
            "status": promotion.get("source_missingness_status"),
            "blocker_count": promotion.get("source_missingness_blocker_count"),
            "first_blocker": promotion.get("first_source_missingness_blocker"),
        },
    ))
    return gates


def build_payload(
    *,
    artifact_path: str | Path = DEFAULT_BAND_ARTIFACT,
    training_report: str | Path = DEFAULT_TRAINING_REPORT,
    candidate_replay: str | Path = DEFAULT_CANDIDATE_REPLAY,
    promotion_refresh: str | Path = DEFAULT_PROMOTION_REFRESH,
    predawn_repair: str | Path = DEFAULT_PREDAWN_REPAIR,
    bottom_location: str | Path = DEFAULT_BOTTOM_LOCATION,
    exact_distance: str | Path = DEFAULT_EXACT_DISTANCE,
) -> dict[str, Any]:
    artifact = artifact_summary(artifact_path)
    training = training_report_summary(training_report)
    replay = replay_summary(candidate_replay)
    promotion = promotion_summary(promotion_refresh)
    predawn = simple_gate_summary(predawn_repair)
    bottom = simple_gate_summary(bottom_location)
    exact = simple_gate_summary(exact_distance)
    gates = build_gates(
        artifact=artifact,
        training_report=training,
        replay=replay,
        promotion=promotion,
        predawn_repair=predawn,
        bottom_location=bottom,
        exact_distance=exact,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "broad_core_model_claim_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "artifact_path": str(artifact_path),
            "training_report": str(training_report),
            "candidate_replay": str(candidate_replay),
            "promotion_refresh": str(promotion_refresh),
            "predawn_repair": str(predawn_repair),
            "bottom_location": str(bottom_location),
            "exact_distance": str(exact_distance),
        },
        "artifact": artifact,
        "training_report": training,
        "candidate_replay": replay,
        "promotion_refresh": promotion,
        "predawn_repair": predawn,
        "bottom_location": bottom,
        "exact_band_distance_zero": exact,
        "gates": gates,
        "blockers": blockers,
    }


def render_report(payload: dict[str, Any]) -> str:
    artifact = payload.get("artifact") or {}
    replay = payload.get("candidate_replay") or {}
    promotion = payload.get("promotion_refresh") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Pooled F Retrain/Re-Export Location Gate",
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
            ["Broad core-model claim allowed", payload.get("broad_core_model_claim_allowed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Artifact feature schema", artifact.get("feature_schema_version")],
            ["Active feature schema", artifact.get("active_feature_schema_version")],
            ["Artifact trained at", artifact.get("trained_at")],
            ["Replay verdict", replay.get("verdict")],
            ["Replay delta vs current", fmt_num(replay.get("aggregate_delta_vs_current"))],
            ["Replay delta vs market", fmt_num(replay.get("aggregate_delta_vs_market"))],
            ["Promotion readiness", promotion.get("readiness_status")],
            ["Weather-only broad claim", promotion.get("broad_market_skill_claim_allowed")],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Downstream Evidence", ""]
    lines += markdown_table(
        ["Artifact", "Status", "Blockers", "First blocker"],
        [
            [
                "predawn_weak_slot_repair",
                (payload.get("predawn_repair") or {}).get("status"),
                (payload.get("predawn_repair") or {}).get("blocker_count"),
                (payload.get("predawn_repair") or {}).get("first_blocker"),
            ],
            [
                "bottom_location_winner_centering",
                (payload.get("bottom_location") or {}).get("status"),
                (payload.get("bottom_location") or {}).get("blocker_count"),
                (payload.get("bottom_location") or {}).get("first_blocker"),
            ],
            [
                "exact_band_distance_zero_calibration",
                (payload.get("exact_band_distance_zero") or {}).get("status"),
                (payload.get("exact_band_distance_zero") or {}).get("blocker_count"),
                (payload.get("exact_band_distance_zero") or {}).get("first_blocker"),
            ],
            [
                "source_missingness_location_gate",
                promotion.get("source_missingness_status"),
                promotion.get("source_missingness_blocker_count"),
                promotion.get("first_source_missingness_blocker"),
            ],
        ],
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
    parser = argparse.ArgumentParser(description="Gate broad claims for the active pooled F retrain/re-export lane.")
    parser.add_argument("--artifact", default=str(DEFAULT_BAND_ARTIFACT))
    parser.add_argument("--training-report", default=str(DEFAULT_TRAINING_REPORT))
    parser.add_argument("--candidate-replay", default=str(DEFAULT_CANDIDATE_REPLAY))
    parser.add_argument("--promotion-refresh", default=str(DEFAULT_PROMOTION_REFRESH))
    parser.add_argument("--predawn-repair", default=str(DEFAULT_PREDAWN_REPAIR))
    parser.add_argument("--bottom-location", default=str(DEFAULT_BOTTOM_LOCATION))
    parser.add_argument("--exact-distance", default=str(DEFAULT_EXACT_DISTANCE))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        artifact_path=args.artifact,
        training_report=args.training_report,
        candidate_replay=args.candidate_replay,
        promotion_refresh=args.promotion_refresh,
        predawn_repair=args.predawn_repair,
        bottom_location=args.bottom_location,
        exact_distance=args.exact_distance,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Pooled F retrain/location gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
