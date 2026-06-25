"""Disposition report for the Item 134 forecast-profile calibration lane."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item134_forecast_profile_disposition")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_REPLAY = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_all_hours_replay.json"
DEFAULT_SERVED_DISTRIBUTION = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_POSITIVE_DAILY_FIRST = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_disposition.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_disposition_report.md"
DEFAULT_CURRENT_TOL = 0.003
DEFAULT_MARKET_TOL = 0.003


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


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
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


def _by_group(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("group")): row for row in rows if row.get("group") is not None}


def _market_sets(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups = {"promote": [], "shadow": [], "blocked": []}
    for row in rows:
        market = row.get("market_id")
        if not market:
            continue
        verdict = str(row.get("verdict") or "").upper()
        if verdict == "PASS":
            groups["promote"].append(str(market))
        elif verdict == "SHADOW":
            groups["shadow"].append(str(market))
        else:
            groups["blocked"].append(str(market))
    return {key: sorted(set(values)) for key, values in groups.items()}


def replay_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    artifact = payload.get("artifact") or {}
    coverage = payload.get("coverage") or {}
    shadow = payload.get("candidate_shadow_variants") or {}
    blocked_validation = payload.get("blocked_validation") or {}
    daily_first = payload.get("daily_first") or {}
    guardrails = payload.get("forecast_profile_guardrails") or {}
    by_cutoff = payload.get("by_cutoff_regime") or []
    by_disagreement = payload.get("by_forecast_disagreement") or []
    markets = _market_sets(payload.get("market_rows") or [])
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "generated_at": payload.get("generated_at"),
        "verdict": payload.get("verdict"),
        "candidate_market_verdict": payload.get("candidate_market_verdict"),
        "cutover_decision": payload.get("cutover_decision"),
        "artifact_schema_version": artifact.get("schema_version"),
        "artifact_feature_schema_version": artifact.get("feature_schema_version"),
        "feature_subset": artifact.get("feature_subset"),
        "hour_models": artifact.get("hour_models") or [],
        "variant_id": shadow.get("variant_id"),
        "variant_family": shadow.get("variant_family"),
        "uses_market_features": shadow.get("uses_market_features"),
        "coverage": coverage,
        "aggregate": payload.get("aggregate") or {},
        "daily_first": daily_first,
        "blocked_validation": {
            "passed": blocked_validation.get("passed"),
            "verdict": blocked_validation.get("verdict"),
            "reasons": blocked_validation.get("reasons") or [],
            "daily_first_delta_vs_market": (blocked_validation.get("daily_first") or {}).get("delta_vs_market"),
        },
        "by_cutoff_regime": by_cutoff,
        "by_forecast_disagreement": by_disagreement,
        "high_disagreement": _by_group(by_disagreement).get("high_disagreement") or {},
        "forecast_profile_guardrails": {
            "schema_version": guardrails.get("schema_version"),
            "tolerance": guardrails.get("tolerance"),
            "blocked_markets": sorted(guardrails.get("blocked_markets") or []),
            "rows": guardrails.get("rows") or [],
        },
        "promote_markets": markets["promote"],
        "shadow_markets": markets["shadow"],
        "blocked_markets": markets["blocked"],
    }


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "blocker_count": payload.get("blocker_count", len(payload.get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "summary": payload.get("summary") or {},
    }


def build_gates(
    *,
    replay: dict[str, Any],
    served_distribution: dict[str, Any],
    positive_daily_first: dict[str, Any],
    current_tol: float,
    market_tol: float,
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    gates.append(_gate(
        "forecast_profile_subset_contract",
        "PASS" if replay.get("feature_subset") == "forecast_profile" else "BLOCK",
        (
            "candidate artifact is the forecast_profile feature subset"
            if replay.get("feature_subset") == "forecast_profile"
            else "candidate artifact is not the forecast_profile feature subset"
        ),
        replay,
    ))

    coverage = replay.get("coverage") or {}
    hour_models = sorted(int(hour) for hour in replay.get("hour_models") or [] if str(hour).isdigit())
    expected_hours = list(range(7, 21))
    full_coverage = (
        coverage.get("candidate_rows", 0) > 0
        and coverage.get("candidate_rows") == coverage.get("family_rows")
        and coverage.get("missing_candidate_rows") == 0
        and hour_models == expected_hours
    )
    gates.append(_gate(
        "all_hour_replay_coverage",
        "PASS" if full_coverage else "BLOCK",
        (
            f"all-hour replay covered {coverage.get('candidate_rows')} rows with zero missing candidates"
            if full_coverage
            else "all-hour replay coverage is incomplete or missing"
        ),
        {"coverage": coverage, "hour_models": hour_models},
    ))

    aggregate_delta = _safe_float((replay.get("aggregate") or {}).get("delta_vs_current"))
    cutoff_regimes = _by_group(replay.get("by_cutoff_regime") or [])
    slice_regressions = []
    for label in ("early", "midday", "late"):
        delta = _safe_float((cutoff_regimes.get(label) or {}).get("delta_vs_current"))
        if delta is None or delta > current_tol:
            slice_regressions.append(label)
    current_lift_pass = aggregate_delta is not None and aggregate_delta <= 0 and not slice_regressions
    gates.append(_gate(
        "current_replay_lift_guardrail",
        "PASS" if current_lift_pass else "BLOCK",
        (
            f"aggregate and cutoff slices improve current replay within {current_tol:.4f}"
            if current_lift_pass
            else "current replay lift is missing or a cutoff slice regresses: " + ", ".join(slice_regressions or ["aggregate"])
        ),
        {"aggregate_delta_vs_current": aggregate_delta, "by_cutoff_regime": replay.get("by_cutoff_regime") or []},
    ))

    daily_gap = _safe_float((replay.get("daily_first") or {}).get("delta_vs_market"))
    blocked_validation = replay.get("blocked_validation") or {}
    gates.append(_gate(
        "daily_first_market_tolerance",
        "PASS" if blocked_validation.get("passed") is True and daily_gap is not None and daily_gap <= market_tol else "BLOCK",
        (
            f"daily-first market gap {daily_gap:+.4f} <= {market_tol:.4f}"
            if blocked_validation.get("passed") is True and daily_gap is not None and daily_gap <= market_tol
            else "daily-first blocked validation is not within market tolerance"
        ),
        {"daily_first_delta_vs_market": daily_gap, "blocked_validation": blocked_validation},
    ))

    guardrails = replay.get("forecast_profile_guardrails") or {}
    guardrail_blocked = guardrails.get("blocked_markets") or []
    gates.append(_gate(
        "high_disagreement_guardrail",
        "PASS" if not guardrail_blocked else "BLOCK",
        (
            "no high-disagreement markets blocked the forecast-profile lane"
            if not guardrail_blocked
            else "high-disagreement markets blocked: " + ", ".join(guardrail_blocked)
        ),
        guardrails,
    ))

    market_blockers = list(replay.get("blocked_markets") or []) + list(replay.get("shadow_markets") or [])
    cutover_ready = replay.get("candidate_market_verdict") == "PASS" and replay.get("cutover_decision") != "DO_NOT_CUT_OVER"
    gates.append(_gate(
        "per_market_promotion_gate",
        "PASS" if cutover_ready and not market_blockers else "BLOCK",
        (
            "all market rows are promotion-ready"
            if cutover_ready and not market_blockers
            else "market rows still require block/shadow handling: " + ", ".join(sorted(set(market_blockers)) or ["global cutover blocked"])
        ),
        {
            "candidate_market_verdict": replay.get("candidate_market_verdict"),
            "cutover_decision": replay.get("cutover_decision"),
            "blocked_markets": replay.get("blocked_markets") or [],
            "shadow_markets": replay.get("shadow_markets") or [],
            "promote_markets": replay.get("promote_markets") or [],
        },
    ))

    gates.append(_gate(
        "served_distribution_contract",
        "PASS" if _passes(served_distribution.get("status")) else "BLOCK",
        (
            "served-distribution calibration contract passed"
            if _passes(served_distribution.get("status"))
            else served_distribution.get("first_blocker") or "served-distribution calibration contract is not clear"
        ),
        served_distribution,
    ))
    gates.append(_gate(
        "positive_daily_first_gate",
        "PASS" if _passes(positive_daily_first.get("status")) else "BLOCK",
        (
            "positive daily-first gate passed"
            if _passes(positive_daily_first.get("status"))
            else positive_daily_first.get("first_blocker") or "positive daily-first gate is not clear"
        ),
        positive_daily_first,
    ))
    gates.append(_gate(
        "lane_separation",
        "PASS" if replay.get("uses_market_features") is False else "BLOCK",
        (
            "forecast-profile lane remains no-market weather-model evidence"
            if replay.get("uses_market_features") is False
            else "forecast-profile replay uses market features or lacks lane metadata"
        ),
        replay,
    ))
    return gates


def build_payload(
    *,
    replay: str | Path = DEFAULT_REPLAY,
    served_distribution: str | Path = DEFAULT_SERVED_DISTRIBUTION,
    positive_daily_first: str | Path = DEFAULT_POSITIVE_DAILY_FIRST,
    current_tol: float = DEFAULT_CURRENT_TOL,
    market_tol: float = DEFAULT_MARKET_TOL,
) -> dict[str, Any]:
    replay_payload = replay_summary(replay)
    served_payload = simple_gate_summary(served_distribution)
    positive_payload = simple_gate_summary(positive_daily_first)
    gates = build_gates(
        replay=replay_payload,
        served_distribution=served_payload,
        positive_daily_first=positive_payload,
        current_tol=current_tol,
        market_tol=market_tol,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    disposition = "KEEP_SHADOW_DIAGNOSTIC" if blockers else "PROMOTION_READY"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "disposition": disposition,
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "replay": str(replay),
            "served_distribution": str(served_distribution),
            "positive_daily_first": str(positive_daily_first),
        },
        "replay": replay_payload,
        "served_distribution": served_payload,
        "positive_daily_first": positive_payload,
        "gates": gates,
        "blockers": blockers,
        "next_action": (
            "Keep Item 134 as a shadow forecast-profile diagnostic. Do not promote or rerun the broad "
            "forecast-profile lane until daily-first market tolerance, high-disagreement markets, and the "
            "served-distribution/positive daily-first gates are clear."
        ),
    }


def _slice_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("group") or "-",
            row.get("n", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("market_brier")),
            fmt_num(row.get("delta_vs_current")),
            fmt_num(row.get("delta_vs_market")),
        ]
        for row in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    replay = payload.get("replay") or {}
    first = payload.get("first_blocker") or {}
    coverage = replay.get("coverage") or {}
    daily = replay.get("daily_first") or {}
    lines = [
        "# Item 134 Forecast-Profile Disposition",
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
            ["Disposition", payload.get("disposition")],
            ["Promotion allowed", payload.get("promotion_allowed")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Replay verdict", replay.get("verdict")],
            ["Candidate market verdict", replay.get("candidate_market_verdict")],
            ["Cutover decision", replay.get("cutover_decision")],
            ["Feature subset", replay.get("feature_subset")],
            ["Variant", replay.get("variant_id")],
            ["Rows", coverage.get("candidate_rows")],
            ["Missing candidate rows", coverage.get("missing_candidate_rows")],
            ["Daily-first delta vs current", fmt_num(daily.get("delta_vs_current"))],
            ["Daily-first delta vs market", fmt_num(daily.get("delta_vs_market"))],
            ["High-disagreement blocked markets", ", ".join((replay.get("forecast_profile_guardrails") or {}).get("blocked_markets") or []) or "-"],
            ["Per-market blocked", ", ".join(replay.get("blocked_markets") or []) or "-"],
            ["Per-market shadow", ", ".join(replay.get("shadow_markets") or []) or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Cutoff-Regime Replay", ""]
    lines += markdown_table(
        ["Regime", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        _slice_rows(replay.get("by_cutoff_regime") or []),
    )
    lines += ["", "## Forecast-Disagreement Replay", ""]
    lines += markdown_table(
        ["Group", "Rows", "Candidate Brier", "Current Brier", "Market Brier", "Delta Current", "Delta Market"],
        _slice_rows(replay.get("by_forecast_disagreement") or []),
    )
    lines += ["", "## Next Action", "", payload.get("next_action") or "-"]
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
    parser = argparse.ArgumentParser(description="Build Item 134 forecast-profile calibration disposition.")
    parser.add_argument("--replay", default=str(DEFAULT_REPLAY))
    parser.add_argument("--served-distribution", default=str(DEFAULT_SERVED_DISTRIBUTION))
    parser.add_argument("--positive-daily-first", default=str(DEFAULT_POSITIVE_DAILY_FIRST))
    parser.add_argument("--current-tol", type=float, default=DEFAULT_CURRENT_TOL)
    parser.add_argument("--market-tol", type=float, default=DEFAULT_MARKET_TOL)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        replay=args.replay,
        served_distribution=args.served_distribution,
        positive_daily_first=args.positive_daily_first,
        current_tol=args.current_tol,
        market_tol=args.market_tol,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 134 forecast-profile disposition: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
