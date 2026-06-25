"""Settlement-scored Item 186 soil/antecedent-water promotion lane."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.market.market_registry import REGISTRY
from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_pct, fmt_signed, markdown_table
from weather.reporting.research.item186_soil_antecedent_gate import DEFAULT_REANALYSIS_ROOT, coverage_summary
from weather.reporting.source_family_inventory import item27_reanalysis_ablation_evidence
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("item186_soil_antecedent_settlement_gate")
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item186_soil_antecedent_settlement_gate.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item186_soil_antecedent_settlement_gate_report.md"
DEFAULT_MIN_MARKETS = 12
THIN_MARGIN_DELTA = 0.003


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coverage_by_market(coverage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("market_id")): row
        for row in coverage.get("sidecars") or []
        if row.get("market_id")
    }


def _lane_for_markets(markets: list[dict[str, Any]]) -> dict[str, Any]:
    allowed = sorted(row["market_id"] for row in markets if row.get("decision") == "promote")
    quarantined = sorted(row["market_id"] for row in markets if row.get("decision") != "promote")
    thin = sorted(
        row["market_id"]
        for row in markets
        if row.get("decision") == "promote"
        and _safe_float(row.get("delta_brier")) is not None
        and float(row["delta_brier"]) < THIN_MARGIN_DELTA
    )
    if allowed and quarantined:
        status = "PARTIAL_POSITIVE_MARKET_SHADOW_LANE"
        policy = "positive_markets_only"
        reason = "Mixed settlement-scored market gates; only positive markets may use soil/antecedent-water features."
    elif allowed:
        status = "BROAD_POSITIVE_MARKET_SHADOW_LANE"
        policy = "all_scored_markets"
        reason = "All settlement-scored markets have positive soil/antecedent-water lane evidence."
    else:
        status = "BLOCKED_NO_POSITIVE_MARKETS"
        policy = "no_soil_antecedent_water_features"
        reason = "No market has positive settlement-scored soil/antecedent-water lane evidence."
    return {
        "status": status,
        "policy": policy,
        "allowed_markets": allowed,
        "quarantined_markets": quarantined,
        "thin_margin_markets": thin,
        "thin_margin_delta": THIN_MARGIN_DELTA,
        "market_count": len(markets),
        "allowed_market_count": len(allowed),
        "quarantined_market_count": len(quarantined),
        "reason": reason,
        "action": (
            "Allow only positive markets into shadow or promotion lanes; keep every blocked market on the "
            "no-soil/antecedent-water path until its settlement-scored gate turns positive."
        ),
    }


def _market_rows(evidence: dict[str, Any], coverage: dict[str, Any]) -> list[dict[str, Any]]:
    by_market = _coverage_by_market(coverage)
    rows = []
    for detail in evidence.get("market_details") or []:
        market_id = str(detail.get("market_id") or "")
        if not market_id:
            continue
        sidecar = by_market.get(market_id) or {}
        soil_rows = int(sidecar.get("soil_complete_rows") or 0)
        water_rows = int(sidecar.get("water_complete_rows") or 0)
        delta = _safe_float(detail.get("delta_brier"))
        coverage_ok = soil_rows > 0 and water_rows > 0
        positive = delta is not None and delta > 0
        decision = "promote" if coverage_ok and positive else "block"
        reason = (
            "positive settlement-scored reanalysis delta with soil and antecedent-water coverage"
            if decision == "promote"
            else "missing soil/water coverage" if not coverage_ok
            else "non-positive settlement-scored reanalysis delta"
        )
        rows.append({
            "market_id": market_id,
            "decision": decision,
            "reason": reason,
            "rows": int(detail.get("rows") or 0),
            "full_brier": detail.get("full_brier"),
            "ablated_brier": detail.get("ablated_brier"),
            "delta_brier": detail.get("delta_brier"),
            "delta_logloss": detail.get("delta_logloss"),
            "item27_gate_path": detail.get("path"),
            "soil_complete_rows": soil_rows,
            "water_complete_rows": water_rows,
            "sidecar_path": sidecar.get("path"),
        })
    return rows


def build_payload(
    *,
    reanalysis_root: str | Path = DEFAULT_REANALYSIS_ROOT,
    feature_gate_paths: dict[str, str | Path] | None = None,
    required_markets: list[str] | None = None,
    min_markets: int = DEFAULT_MIN_MARKETS,
) -> dict[str, Any]:
    markets_required = sorted(required_markets or REGISTRY.keys())
    coverage = coverage_summary(reanalysis_root)
    evidence = item27_reanalysis_ablation_evidence(
        paths_by_market=feature_gate_paths,
        required_markets=markets_required,
    )
    blockers = []
    settlement_scored = bool(evidence)
    if not evidence:
        blockers.append({
            "blocker": "missing_item27_reanalysis_market_gates",
            "detail": "Item 27 settlement-scored reanalysis market gates are missing or incomplete.",
        })
        evidence = evidence or {}

    markets = _market_rows(evidence, coverage)
    scored = {row.get("market_id") for row in markets}
    missing_scored = sorted(set(markets_required) - scored)
    missing_coverage = sorted(
        row["market_id"]
        for row in markets
        if int(row.get("soil_complete_rows") or 0) <= 0 or int(row.get("water_complete_rows") or 0) <= 0
    )
    if coverage.get("sidecar_count", 0) < int(min_markets):
        blockers.append({
            "blocker": "sidecar_market_count",
            "detail": f"found {coverage.get('sidecar_count', 0)} sidecars; need {int(min_markets)}",
        })
    if missing_scored:
        blockers.append({
            "blocker": "missing_scored_markets",
            "detail": "one or more required markets are missing Item 27 settlement-scored gates",
            "markets": missing_scored,
        })
    if missing_coverage:
        blockers.append({
            "blocker": "missing_soil_or_water_coverage",
            "detail": "one or more scored markets lack complete soil or antecedent-water rows",
            "markets": missing_coverage,
        })

    lane = _lane_for_markets(markets)
    if not lane.get("allowed_markets"):
        blockers.append({
            "blocker": "no_positive_markets",
            "detail": "no market has positive settlement-scored soil/antecedent-water lane evidence",
        })

    status = "PASS" if not blockers else "BLOCK"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": utc_iso(),
        "status": status,
        "settlement_scored": settlement_scored,
        "blocker_count": len(blockers),
        "first_blocker": blockers[0] if blockers else None,
        "blockers": blockers,
        "inputs": {
            "reanalysis_root": str(reanalysis_root),
            "required_markets": markets_required,
            "min_markets": int(min_markets),
        },
        "summary": {
            "settlement_scored": settlement_scored,
            "markets_scored": len(markets),
            "allowed_market_count": len(lane.get("allowed_markets") or []),
            "quarantined_market_count": len(lane.get("quarantined_markets") or []),
            "water_complete_rows": coverage.get("water_complete_rows"),
            "soil_complete_rows": coverage.get("soil_complete_rows"),
            "source_evidence": evidence.get("evidence_source"),
            "source_variant": evidence.get("variant"),
        },
        "promotion_lane": lane,
        "markets": markets,
        "source_item27_evidence": evidence,
        "coverage": coverage,
    }


def render_report(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lane = payload.get("promotion_lane") or {}
    first = payload.get("first_blocker") or {}
    lines = [
        "# Item 186 Soil Antecedent-Water Settlement Gate",
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
            ["Settlement scored", payload.get("settlement_scored")],
            ["Blockers", payload.get("blocker_count")],
            ["First blocker", first.get("detail") or "-"],
            ["Source evidence", summary.get("source_evidence") or "-"],
            ["Markets scored", summary.get("markets_scored")],
            ["Allowed markets", ", ".join(lane.get("allowed_markets") or []) or "-"],
            ["Quarantined markets", ", ".join(lane.get("quarantined_markets") or []) or "-"],
            ["Thin-margin markets", ", ".join(lane.get("thin_margin_markets") or []) or "-"],
            ["Soil complete rows", summary.get("soil_complete_rows")],
            ["Water complete rows", summary.get("water_complete_rows")],
        ],
    )
    lines += ["", "## Promotion Lane", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", lane.get("status")],
            ["Policy", lane.get("policy")],
            ["Reason", lane.get("reason")],
            ["Action", lane.get("action")],
        ],
    )
    if payload.get("blockers"):
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Blocker", "Detail"],
            [[row.get("blocker"), row.get("detail")] for row in payload.get("blockers") or []],
        )
    lines += ["", "## Market Gates", ""]
    lines += markdown_table(
        [
            "Market",
            "Decision",
            "Rows",
            "Full Brier",
            "Ablated Brier",
            "Delta Brier",
            "Soil Rows",
            "Water Rows",
            "Reason",
        ],
        [
            [
                row.get("market_id"),
                row.get("decision"),
                row.get("rows"),
                fmt_num(row.get("full_brier"), 4),
                fmt_num(row.get("ablated_brier"), 4),
                fmt_signed(row.get("delta_brier"), 4),
                row.get("soil_complete_rows"),
                row.get("water_complete_rows"),
                row.get("reason"),
            ]
            for row in payload.get("markets") or []
        ],
    )
    coverage = payload.get("coverage") or {}
    lines += ["", "## Coverage", ""]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Sidecars", coverage.get("sidecar_count")],
            ["Soil coverage", fmt_pct(coverage.get("soil_coverage"))],
            ["Water coverage", fmt_pct(coverage.get("water_coverage"))],
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Item 186 soil/antecedent-water settlement gate.")
    parser.add_argument("--reanalysis-root", default=str(DEFAULT_REANALYSIS_ROOT))
    parser.add_argument("--min-markets", type=int, default=DEFAULT_MIN_MARKETS)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(
        reanalysis_root=args.reanalysis_root,
        min_markets=args.min_markets,
    )
    json_path, report_path = write_outputs(payload, args.out, args.report)
    print(f"Item 186 soil/antecedent-water settlement gate: {payload['status']} ({payload['blocker_count']} blocker(s))")
    print(f"JSON written to {json_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
