"""Disposition report for the Item 135 cutoff-regime weighting lane."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item135_cutoff_regime_disposition")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_WEIGHTING = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_weighting_all_hours.json"
DEFAULT_ITEM134 = DEFAULT_BACKTEST_ROOT / "item134_forecast_profile_disposition.json"
DEFAULT_SERVED_DISTRIBUTION = DEFAULT_BACKTEST_ROOT / "served_distribution_calibration_contract.json"
DEFAULT_POSITIVE_DAILY_FIRST = DEFAULT_BACKTEST_ROOT / "early_hour_positive_daily_first_gate.json"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_disposition.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item135_cutoff_regime_disposition_report.md"


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


def weighting_summary(path: str | Path) -> dict[str, Any]:
    payload = _read_json(path) or {}
    variant = payload.get("variant") or {}
    audit = payload.get("no_leakage_audit") or {}
    thresholds = payload.get("regime_thresholds") or []
    by_regime = {row.get("regime"): row for row in thresholds if row.get("regime")}
    acceptance = payload.get("acceptance") or {}
    return {
        "path": str(path),
        "exists": Path(path).exists(),
        "schema_version": payload.get("schema_version"),
        "generated_at_utc": payload.get("generated_at_utc"),
        "variant": variant,
        "aggregate": payload.get("aggregate") or {},
        "daily_first": payload.get("daily_first") or {},
        "no_leakage_audit": audit,
        "regime_thresholds": thresholds,
        "acceptance": acceptance,
        "blocked_regimes": acceptance.get("blocked_regimes") or [],
        "acceptance_reasons": acceptance.get("reasons") or [],
        "final_lock_in": by_regime.get("final_lock_in") or {},
    }


def build_gates(
    *,
    weighting: dict[str, Any],
    item134: dict[str, Any],
    served_distribution: dict[str, Any],
    positive_daily_first: dict[str, Any],
) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    variant = weighting.get("variant") or {}
    audit = weighting.get("no_leakage_audit") or {}
    thresholds = weighting.get("regime_thresholds") or []
    required_regimes = {"early", "midday", "late", "final_lock_in"}
    present_regimes = {row.get("regime") for row in thresholds}
    coverage_pass = (
        variant.get("rows", 0) > 0
        and variant.get("uses_market_features") is False
        and audit.get("status") == "PASS"
        and required_regimes.issubset(present_regimes)
        and (audit.get("market_days") or 0) >= 2
    )
    gates.append(_gate(
        "all_hour_regime_replay_coverage",
        "PASS" if coverage_pass else "BLOCK",
        (
            f"all-hour regime replay covered {variant.get('rows')} rows across {audit.get('market_days')} market-days"
            if coverage_pass
            else "all-hour regime replay coverage, leakage audit, or regime coverage is incomplete"
        ),
        {"variant": variant, "no_leakage_audit": audit, "present_regimes": sorted(r for r in present_regimes if r)},
    ))

    aggregate_delta = _safe_float((weighting.get("aggregate") or {}).get("delta_vs_current"))
    daily_delta = _safe_float((weighting.get("daily_first") or {}).get("delta_vs_current"))
    current_lift_pass = aggregate_delta is not None and aggregate_delta <= 0 and daily_delta is not None and daily_delta <= 0
    gates.append(_gate(
        "current_replay_lift_guardrail",
        "PASS" if current_lift_pass else "BLOCK",
        (
            "aggregate and daily-first regime replay improve current"
            if current_lift_pass
            else "aggregate or daily-first current replay lift is missing or regresses"
        ),
        {"aggregate_delta_vs_current": aggregate_delta, "daily_first_delta_vs_current": daily_delta},
    ))

    final = weighting.get("final_lock_in") or {}
    gates.append(_gate(
        "final_lock_in_threshold",
        "PASS" if str(final.get("status") or "").lower() == "pass" else "BLOCK",
        (
            "final-lock-in threshold passed on all-hour rows"
            if str(final.get("status") or "").lower() == "pass"
            else "final-lock-in threshold is missing or blocked"
        ),
        final,
    ))

    blocked_regimes = weighting.get("blocked_regimes") or []
    gates.append(_gate(
        "regime_thresholds",
        "PASS" if not blocked_regimes and str((weighting.get("acceptance") or {}).get("status") or "").lower() == "pass" else "BLOCK",
        (
            "all separate regime thresholds passed"
            if not blocked_regimes and str((weighting.get("acceptance") or {}).get("status") or "").lower() == "pass"
            else "blocked regimes remain: " + ", ".join(blocked_regimes or ["acceptance blocked"])
        ),
        {"blocked_regimes": blocked_regimes, "reasons": weighting.get("acceptance_reasons") or []},
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
            "regime-weighted lane remains no-market weather-model evidence"
            if variant.get("uses_market_features") is False
            else "regime-weighted replay uses market features or lacks lane metadata"
        ),
        variant,
    ))
    return gates


def build_payload(
    *,
    weighting: str | Path = DEFAULT_WEIGHTING,
    item134: str | Path = DEFAULT_ITEM134,
    served_distribution: str | Path = DEFAULT_SERVED_DISTRIBUTION,
    positive_daily_first: str | Path = DEFAULT_POSITIVE_DAILY_FIRST,
) -> dict[str, Any]:
    weighting_payload = weighting_summary(weighting)
    item134_payload = simple_gate_summary(item134)
    served_payload = simple_gate_summary(served_distribution)
    positive_payload = simple_gate_summary(positive_daily_first)
    gates = build_gates(
        weighting=weighting_payload,
        item134=item134_payload,
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
            "weighting": str(weighting),
            "item134": str(item134),
            "served_distribution": str(served_distribution),
            "positive_daily_first": str(positive_daily_first),
        },
        "weighting": weighting_payload,
        "item134": item134_payload,
        "served_distribution": served_payload,
        "positive_daily_first": positive_payload,
        "gates": gates,
        "blockers": blockers,
        "next_action": (
            "Keep Item 135 as a shadow cutoff-regime diagnostic. Do not promote the broad regime-weighted "
            "lane until early, midday, and late market gaps clear together with upstream Item 134 and the "
            "served-distribution/positive daily-first gates."
        ),
    }


def render_report(payload: dict[str, Any]) -> str:
    weighting = payload.get("weighting") or {}
    variant = weighting.get("variant") or {}
    audit = weighting.get("no_leakage_audit") or {}
    daily = weighting.get("daily_first") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Item 135 Cutoff-Regime Disposition",
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
            ["Market-days", audit.get("market_days")],
            ["Leakage audit", audit.get("status")],
            ["Daily-first delta vs current", fmt_num(daily.get("delta_vs_current"))],
            ["Daily-first delta vs market", fmt_num(daily.get("delta_vs_market"))],
            ["Blocked regimes", ", ".join(weighting.get("blocked_regimes") or []) or "-"],
            ["Acceptance reasons", "; ".join(weighting.get("acceptance_reasons") or []) or "-"],
        ],
    )
    lines += ["", "## Gates", ""]
    lines += markdown_table(
        ["Gate", "Status", "Detail"],
        [[row.get("gate"), row.get("status"), row.get("detail")] for row in payload.get("gates") or []],
    )
    lines += ["", "## Regime Thresholds", ""]
    lines += markdown_table(
        ["Regime", "Status", "Rows", "Market-days", "Delta Current", "Delta Market", "Reasons"],
        [
            [
                row.get("regime"),
                row.get("status"),
                (row.get("daily_first") or {}).get("n", 0),
                (row.get("daily_first") or {}).get("n_days", 0),
                fmt_num((row.get("daily_first") or {}).get("delta_vs_current")),
                fmt_num((row.get("daily_first") or {}).get("delta_vs_market")),
                "; ".join(row.get("reasons") or []) or "-",
            ]
            for row in weighting.get("regime_thresholds") or []
        ],
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
    parser = argparse.ArgumentParser(description="Build Item 135 cutoff-regime weighting disposition.")
    parser.add_argument("--weighting", default=str(DEFAULT_WEIGHTING))
    parser.add_argument("--item134", default=str(DEFAULT_ITEM134))
    parser.add_argument("--served-distribution", default=str(DEFAULT_SERVED_DISTRIBUTION))
    parser.add_argument("--positive-daily-first", default=str(DEFAULT_POSITIVE_DAILY_FIRST))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    payload = build_payload(
        weighting=args.weighting,
        item134=args.item134,
        served_distribution=args.served_distribution,
        positive_daily_first=args.positive_daily_first,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 135 cutoff-regime disposition: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
