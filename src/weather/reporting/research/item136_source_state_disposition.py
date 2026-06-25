"""Disposition report for the Item 136 source-state reliability lane."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item136_source_state_disposition")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_RELIABILITY = DEFAULT_BACKTEST_ROOT / "item136_source_state_reliability.json"
DEFAULT_ITEM134 = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_disposition.json"
DEFAULT_ITEM135 = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_disposition.json"
DEFAULT_SERVED_DISTRIBUTION = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_POSITIVE_DAILY_FIRST = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item136_source_state_disposition.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item136_source_state_disposition_report.md"


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


def simple_gate_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "status": payload.get("status"),
        "disposition": payload.get("disposition"),
        "blocker_count": payload.get("blocker_count", len(payload.get("blockers") or [])),
        "first_blocker": _first_blocker(payload),
        "summary": payload.get("summary") or {},
    }


def reliability_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    variant = payload.get("variant") or {}
    acceptance = payload.get("acceptance") or {}
    quote_risk = payload.get("quote_risk_reporting") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "variant": variant,
        "daily_first": payload.get("daily_first") or {},
        "aggregate": payload.get("aggregate") or {},
        "by_source_state_slice": payload.get("by_source_state_slice") or [],
        "by_forecast_disagreement": payload.get("by_forecast_disagreement") or [],
        "market_thresholds": payload.get("market_thresholds") or [],
        "quote_risk_reporting": quote_risk,
        "acceptance": acceptance,
        "acceptance_reasons": acceptance.get("reasons") or [],
        "blocked_markets": acceptance.get("blocked_markets") or [],
    }


def build_gates(
    *,
    reliability: dict[str, Any],
    item134: dict[str, Any],
    item135: dict[str, Any],
    served_distribution: dict[str, Any],
    positive_daily_first: dict[str, Any],
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    variant = reliability.get("variant") or {}
    quote_risk = reliability.get("quote_risk_reporting") or {}
    gates.append(_gate(
        "all_hour_source_state_replay_coverage",
        "PASS" if variant.get("rows", 0) > 0 and variant.get("uses_market_features") is False else "BLOCK",
        (
            f"source-state reliability replay covered {variant.get('rows')} no-market rows"
            if variant.get("rows", 0) > 0 and variant.get("uses_market_features") is False
            else "source-state reliability replay coverage is missing or market-informed"
        ),
        variant,
    ))

    reason_surface_pass = (
        quote_risk.get("rows", 0) > 0
        and quote_risk.get("reason_field") == "source_state_reliability_reason"
        and quote_risk.get("alpha_field") == "source_state_reliability_alpha"
        and bool(quote_risk.get("top_reasons"))
    )
    gates.append(_gate(
        "explanation_and_quote_risk_reason_surface",
        "PASS" if reason_surface_pass else "BLOCK",
        (
            "source-state reliability reason and alpha fields are surfaced for explanations and quote-risk diagnostics"
            if reason_surface_pass
            else "source-state reliability reason surface is missing from report payload"
        ),
        quote_risk,
    ))

    daily_delta = _safe_float((reliability.get("daily_first") or {}).get("delta_vs_current"))
    gates.append(_gate(
        "current_replay_lift_guardrail",
        "PASS" if daily_delta is not None and daily_delta <= 0 else "BLOCK",
        (
            "daily-first reliability replay improves current"
            if daily_delta is not None and daily_delta <= 0
            else "daily-first reliability replay does not improve current"
        ),
        {"daily_first_delta_vs_current": daily_delta, "daily_first": reliability.get("daily_first") or {}},
    ))

    acceptance = reliability.get("acceptance") or {}
    gates.append(_gate(
        "source_state_reliability_thresholds",
        "PASS" if str(acceptance.get("status") or "").lower() == "pass" else "BLOCK",
        (
            "source-state reliability acceptance thresholds passed"
            if str(acceptance.get("status") or "").lower() == "pass"
            else "; ".join(reliability.get("acceptance_reasons") or ["source-state reliability acceptance is blocked"])
        ),
        acceptance,
    ))

    gates.append(_gate(
        "upstream_forecast_profile_disposition",
        "PASS" if _passes(item134.get("status")) else "BLOCK",
        (
            "upstream Item 134 forecast-profile lane is promotion-ready"
            if _passes(item134.get("status"))
            else item134.get("first_blocker") or "upstream Item 134 forecast-profile lane remains shadow-only"
        ),
        item134,
    ))
    gates.append(_gate(
        "upstream_cutoff_regime_disposition",
        "PASS" if _passes(item135.get("status")) else "BLOCK",
        (
            "upstream Item 135 cutoff-regime lane is promotion-ready"
            if _passes(item135.get("status"))
            else item135.get("first_blocker") or "upstream Item 135 cutoff-regime lane remains shadow-only"
        ),
        item135,
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
        "PASS" if variant.get("uses_market_features") is False else "BLOCK",
        (
            "source-state reliability lane remains no-market weather-model evidence"
            if variant.get("uses_market_features") is False
            else "source-state reliability replay uses market features or lacks lane metadata"
        ),
        variant,
    ))
    return gates


def build_payload(
    *,
    reliability: str | Path = DEFAULT_RELIABILITY,
    item134: str | Path = DEFAULT_ITEM134,
    item135: str | Path = DEFAULT_ITEM135,
    served_distribution: str | Path = DEFAULT_SERVED_DISTRIBUTION,
    positive_daily_first: str | Path = DEFAULT_POSITIVE_DAILY_FIRST,
) -> dict[str, Any]:
    reliability_payload = reliability_summary(reliability)
    item134_payload = simple_gate_summary(item134)
    item135_payload = simple_gate_summary(item135)
    served_payload = simple_gate_summary(served_distribution)
    positive_payload = simple_gate_summary(positive_daily_first)
    gates = build_gates(
        reliability=reliability_payload,
        item134=item134_payload,
        item135=item135_payload,
        served_distribution=served_payload,
        positive_daily_first=positive_payload,
    )
    blockers = [gate for gate in gates if gate.get("status") == "BLOCK"]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": "PASS" if not blockers else "BLOCK",
        "disposition": "KEEP_SHADOW_DIAGNOSTIC" if blockers else "PROMOTION_READY",
        "promotion_allowed": not blockers,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "inputs": {
            "reliability": str(reliability),
            "item134": str(item134),
            "item135": str(item135),
            "served_distribution": str(served_distribution),
            "positive_daily_first": str(positive_daily_first),
        },
        "reliability": reliability_payload,
        "item134": item134_payload,
        "item135": item135_payload,
        "served_distribution": served_payload,
        "positive_daily_first": positive_payload,
        "gates": gates,
        "blockers": blockers,
        "next_action": (
            "Keep Item 136 as a shadow source-state reliability diagnostic. Do not promote or use it for "
            "quote-risk permission until degraded-source/high-disagreement raw-forecast thresholds, Chicago/NYC "
            "market thresholds, upstream Item 134/135, and served-distribution gates clear."
        ),
    }


def _slice_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    return [
        [
            row.get("group") or "-",
            row.get("n", 0),
            fmt_num(row.get("candidate_brier")),
            fmt_num(row.get("raw_forecast_brier")),
            fmt_num(row.get("current_brier")),
            fmt_num(row.get("delta_vs_raw_forecast")),
            fmt_num(row.get("delta_vs_current")),
            fmt_num(row.get("delta_vs_market")),
        ]
        for row in rows
    ]


def render_report(payload: dict[str, Any]) -> str:
    reliability = payload.get("reliability") or {}
    variant = reliability.get("variant") or {}
    daily = reliability.get("daily_first") or {}
    quote_risk = reliability.get("quote_risk_reporting") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Item 136 Source-State Reliability Disposition",
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
            ["Variant", variant.get("variant_id")],
            ["Rows", variant.get("rows")],
            ["Daily-first delta vs current", fmt_num(daily.get("delta_vs_current"))],
            ["Daily-first delta vs raw forecast", fmt_num(daily.get("delta_vs_raw_forecast"))],
            ["Quote-risk status", quote_risk.get("status")],
            ["Quote-risk reason field", quote_risk.get("reason_field")],
            ["Blocked markets", ", ".join(reliability.get("blocked_markets") or []) or "-"],
            ["Acceptance reasons", "; ".join(reliability.get("acceptance_reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Source-State Slices", ""]
    lines += markdown_table(
        [
            "Group",
            "Rows",
            "Reliability Brier",
            "Raw Forecast Brier",
            "Current Brier",
            "Delta Raw",
            "Delta Current",
            "Delta Market",
        ],
        _slice_rows(reliability.get("by_source_state_slice") or []),
    )
    lines += ["", "## Forecast-Disagreement Slices", ""]
    lines += markdown_table(
        [
            "Group",
            "Rows",
            "Reliability Brier",
            "Raw Forecast Brier",
            "Current Brier",
            "Delta Raw",
            "Delta Current",
            "Delta Market",
        ],
        _slice_rows(reliability.get("by_forecast_disagreement") or []),
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
    parser = argparse.ArgumentParser(description="Build Item 136 source-state reliability disposition.")
    parser.add_argument("--reliability", default=str(DEFAULT_RELIABILITY))
    parser.add_argument("--item134", default=str(DEFAULT_ITEM134))
    parser.add_argument("--item135", default=str(DEFAULT_ITEM135))
    parser.add_argument("--served-distribution", default=str(DEFAULT_SERVED_DISTRIBUTION))
    parser.add_argument("--positive-daily-first", default=str(DEFAULT_POSITIVE_DAILY_FIRST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        reliability=args.reliability,
        item134=args.item134,
        item135=args.item135,
        served_distribution=args.served_distribution,
        positive_daily_first=args.positive_daily_first,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 136 source-state disposition: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
