"""Diagnostics for blocked promotion markets.

The report consumes Item-69-style variant row exports and identifies whether a
blocked market is mostly a current-fallback problem or a direct winner/market
underpricing problem. It is development evidence only; it does not select or
serve a candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.reporting.multi_variant_shadow import (
    comparison,
    daily_first_comparison,
    grouped_comparison,
)


SCHEMA_VERSION = "blocked_market_repair_diagnostics_v0.1"
DEFAULT_BACKTEST_ROOT = data_path() / "backtest"
DEFAULT_OUT = DEFAULT_BACKTEST_ROOT / "item147_blocked_market_repair_diagnostics.json"
DEFAULT_REPORT = DEFAULT_BACKTEST_ROOT / "item147_blocked_market_repair_diagnostics_report.md"
DEFAULT_SLICE_KEYS = (
    "cutoff_hour",
    "cutoff_regime",
    "bin_type",
    "settlement_distance_bucket",
    "source_freshness_state",
    "forecast_disagreement_bucket",
    "forecast_bucket_pressure",
)


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _valid_row(row: dict[str, Any]) -> bool:
    return (
        _safe_float(row.get("probability")) is not None
        and _safe_float(row.get("current_probability")) is not None
        and _safe_float(row.get("market_yes")) is not None
        and _safe_int(row.get("outcome")) is not None
        and bool(row.get("market_id"))
        and bool(row.get("target_date"))
    )


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    for key in ("probability", "current_probability", "recorded_probability", "market_yes"):
        value = _safe_float(row.get(key))
        if value is not None:
            normalized[key] = value
    outcome = _safe_int(row.get("outcome"))
    if outcome is not None:
        normalized["outcome"] = outcome
    return normalized


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [normalize_row(row) for row in rows if _valid_row(row)]


def read_variant_rows(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        with Path(path).open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if _valid_row(row):
                    rows.append(normalize_row(row))
    return rows


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def winner_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [row for row in rows if _safe_int(row.get("outcome")) == 1]
    variant = [
        float(row["probability"])
        for row in winners
        if _safe_float(row.get("probability")) is not None
    ]
    current = [
        float(row["current_probability"])
        for row in winners
        if _safe_float(row.get("current_probability")) is not None
    ]
    market = [
        float(row["market_yes"])
        for row in winners
        if _safe_float(row.get("market_yes")) is not None
    ]
    variant_mean = _mean(variant)
    current_mean = _mean(current)
    market_mean = _mean(market)
    return {
        "winner_rows": len(winners),
        "variant_winner_probability": variant_mean,
        "current_winner_probability": current_mean,
        "market_winner_probability": market_mean,
        "variant_winner_gap_vs_market": (
            variant_mean - market_mean
            if variant_mean is not None and market_mean is not None
            else None
        ),
        "variant_winner_gap_vs_current": (
            variant_mean - current_mean
            if variant_mean is not None and current_mean is not None
            else None
        ),
    }


def current_fallback_share(rows: list[dict[str, Any]], tolerance: float = 1e-12) -> float | None:
    checked = 0
    fallback = 0
    for row in rows:
        probability = _safe_float(row.get("probability"))
        current = _safe_float(row.get("current_probability"))
        if probability is None or current is None:
            continue
        checked += 1
        if abs(probability - current) <= tolerance:
            fallback += 1
    return fallback / checked if checked else None


def classify_market(rows: list[dict[str, Any]], market_tol: float = 0.003) -> str:
    rows = normalize_rows(rows)
    comp = comparison(rows) or {}
    winners = winner_summary(rows)
    fallback_share = current_fallback_share(rows) or 0.0
    market_gap = comp.get("delta_vs_market")
    winner_gap = winners.get("variant_winner_gap_vs_market")
    if fallback_share >= 0.95 and market_gap is not None and market_gap > market_tol:
        return "current_fallback_trails_market"
    if winner_gap is not None and winner_gap < -0.05:
        return "winner_underpricing_vs_market"
    if market_gap is not None and market_gap > market_tol:
        return "market_gap_without_clear_winner_signal"
    return "monitor"


def slice_diagnostics(
    rows: list[dict[str, Any]],
    slice_keys: tuple[str, ...] = DEFAULT_SLICE_KEYS,
    min_rows: int = 200,
    market_tol: float = 0.003,
    limit: int = 8,
) -> list[dict[str, Any]]:
    rows = normalize_rows(rows)
    output: list[dict[str, Any]] = []
    for key in slice_keys:
        for row in grouped_comparison(rows, key):
            if row.get("n", 0) < min_rows:
                continue
            delta_vs_market = row.get("delta_vs_market")
            if delta_vs_market is None:
                continue
            group_rows = [
                source
                for source in rows
                if str(source.get(key) or "") == str(row.get("group") or "")
            ]
            output.append({
                "slice": key,
                "group": row.get("group"),
                "n": row.get("n", 0),
                "variant_brier": row.get("variant_brier"),
                "current_brier": row.get("current_brier"),
                "market_brier": row.get("market_brier"),
                "delta_vs_current": row.get("delta_vs_current"),
                "delta_vs_market": delta_vs_market,
                "weighted_market_gap": max(0.0, float(delta_vs_market) - float(market_tol)) * row.get("n", 0),
                "winner": winner_summary(group_rows),
            })
    output.sort(key=lambda row: (row["weighted_market_gap"], row.get("n", 0)), reverse=True)
    return output[:limit]


def repair_actions_for_market(
    market: dict[str, Any],
    market_tol: float = 0.003,
    current_tol: float = 0.0005,
) -> list[dict[str, Any]]:
    daily = market.get("daily_first") or {}
    winner = market.get("winner") or {}
    top_slices = market.get("top_gap_slices") or []
    classification = market.get("classification")
    market_gap = _safe_float(daily.get("delta_vs_market"))
    current_gap = _safe_float(daily.get("delta_vs_current"))
    winner_gap = _safe_float(winner.get("variant_winner_gap_vs_market"))
    actions: list[dict[str, Any]] = []

    if current_gap is not None and current_gap > float(current_tol):
        actions.append({
            "action": "add_current_regression_guard",
            "priority": "P0",
            "detail": (
                "Candidate regresses incumbent on daily-first evidence; hold this "
                "market on current or force current-blend alpha 0 until a later-date "
                "candidate beats current."
            ),
        })

    if classification == "current_fallback_trails_market":
        actions.append({
            "action": "add_non_current_market_signal",
            "priority": "P0",
            "detail": (
                "Candidate is effectively incumbent/current fallback while market "
                "prices remain better; a promotion lane needs independent forecast, "
                "source-state, or microstructure signal rather than another current clone."
            ),
        })
    elif classification == "winner_underpricing_vs_market":
        actions.append({
            "action": "repair_winner_probability_mass",
            "priority": "P0",
            "detail": (
                "Winner rows are underpriced versus market; focus settlement-distance-0 "
                "and EQ/range winner mass before broad blending or rank sharpening."
            ),
        })
    elif market_gap is not None and market_gap > float(market_tol):
        actions.append({
            "action": "repair_largest_market_gap_slice",
            "priority": "P1",
            "detail": (
                "Market gap persists without a single fallback/winner failure mode; "
                "repair should target the highest weighted inference-time slice."
            ),
        })

    if top_slices:
        top = top_slices[0]
        actions.append({
            "action": "target_top_weighted_slice",
            "priority": "P1",
            "detail": (
                f"Top slice is {top.get('slice')}={top.get('group')} with "
                f"weighted market gap {fmt_num(top.get('weighted_market_gap'))}."
            ),
        })

    if winner_gap is not None and winner_gap < -0.05 and not any(
        action.get("action") == "repair_winner_probability_mass"
        for action in actions
    ):
        actions.append({
            "action": "audit_winner_underpricing",
            "priority": "P1",
            "detail": (
                "Winner probability is materially below market even though this is "
                "not the primary classification."
            ),
        })

    return actions


def market_diagnostics(
    rows: list[dict[str, Any]],
    market_tol: float = 0.003,
    current_tol: float = 0.0005,
    min_slice_rows: int = 200,
    top_slices: int = 8,
) -> list[dict[str, Any]]:
    rows = normalize_rows(rows)
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_market[str(row["market_id"])].append(row)

    output: list[dict[str, Any]] = []
    for market_id, market_rows in sorted(by_market.items()):
        comp = comparison(market_rows) or {}
        daily = daily_first_comparison(market_rows) or {}
        market = {
            "market_id": market_id,
            "rows": len(market_rows),
            "target_dates": sorted({row.get("target_date") for row in market_rows if row.get("target_date")}),
            "classification": classify_market(market_rows, market_tol=market_tol),
            "current_fallback_share": current_fallback_share(market_rows),
            "aggregate": comp,
            "daily_first": daily,
            "winner": winner_summary(market_rows),
            "top_gap_slices": slice_diagnostics(
                market_rows,
                min_rows=min_slice_rows,
                market_tol=market_tol,
                limit=top_slices,
            ),
        }
        market["blocks_market"] = (
            (market.get("daily_first") or {}).get("delta_vs_market") is not None
            and (market["daily_first"]["delta_vs_market"] > market_tol)
        )
        market["candidate_regresses_current"] = (
            (market.get("daily_first") or {}).get("delta_vs_current") is not None
            and (market["daily_first"]["delta_vs_current"] > current_tol)
        )
        market["repair_actions"] = repair_actions_for_market(
            market,
            market_tol=market_tol,
            current_tol=current_tol,
        )
        market["primary_repair_action"] = (
            market["repair_actions"][0]["action"]
            if market.get("repair_actions")
            else "monitor"
        )
        output.append(market)
    return output


def build_payload(
    rows_paths: list[str | Path],
    market_tol: float = 0.003,
    current_tol: float = 0.0005,
    min_slice_rows: int = 200,
    top_slices: int = 8,
) -> dict[str, Any]:
    rows = read_variant_rows(rows_paths)
    markets = market_diagnostics(
        rows,
        market_tol=market_tol,
        current_tol=current_tol,
        min_slice_rows=min_slice_rows,
        top_slices=top_slices,
    )
    blocked = [
        market
        for market in markets
        if (market.get("daily_first") or {}).get("delta_vs_market") is not None
        and (market["daily_first"]["delta_vs_market"] > market_tol)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows_paths": [str(path) for path in rows_paths],
        "row_count": len(rows),
        "market_tol": float(market_tol),
        "current_tol": float(current_tol),
        "min_slice_rows": int(min_slice_rows),
        "evidence_classification": "development_diagnostic_not_promotion_evidence",
        "summary": {
            "markets": len(markets),
            "blocked_markets": [market["market_id"] for market in blocked],
            "current_regression_markets": [
                market["market_id"]
                for market in markets
                if market.get("candidate_regresses_current")
            ],
            "primary_repair_actions": {
                market["market_id"]: market.get("primary_repair_action")
                for market in markets
                if market.get("blocks_market")
            },
            "current_fallback_markets": [
                market["market_id"]
                for market in markets
                if market.get("classification") == "current_fallback_trails_market"
            ],
            "winner_underpricing_markets": [
                market["market_id"]
                for market in markets
                if market.get("classification") == "winner_underpricing_vs_market"
            ],
        },
        "markets": markets,
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _overview_rows(markets: list[dict[str, Any]]) -> list[list[Any]]:
    rows = []
    for market in markets:
        daily = market.get("daily_first") or {}
        winner = market.get("winner") or {}
        rows.append([
            market.get("market_id"),
            market.get("classification"),
            fmt_num(market.get("current_fallback_share")),
            fmt_num(daily.get("variant_brier")),
            fmt_num(daily.get("current_brier")),
            fmt_num(daily.get("market_brier")),
            fmt_signed(daily.get("delta_vs_market")),
            "yes" if market.get("candidate_regresses_current") else "no",
            fmt_signed(winner.get("variant_winner_gap_vs_market")),
            market.get("primary_repair_action") or "monitor",
        ])
    return rows


def _slice_rows(market: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for item in market.get("top_gap_slices") or []:
        winner = item.get("winner") or {}
        rows.append([
            item.get("slice"),
            item.get("group"),
            item.get("n"),
            fmt_num(item.get("variant_brier")),
            fmt_num(item.get("market_brier")),
            fmt_signed(item.get("delta_vs_market")),
            fmt_num(item.get("weighted_market_gap")),
            fmt_signed(winner.get("variant_winner_gap_vs_market")),
        ])
    return rows


def _repair_rows(market: dict[str, Any]) -> list[list[Any]]:
    rows = []
    for action in market.get("repair_actions") or []:
        rows.append([
            action.get("priority"),
            action.get("action"),
            action.get("detail"),
        ])
    return rows


def write_markdown_report(path: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(path)
    lines = [
        "# Blocked Market Repair Diagnostics",
        "",
        f"Generated: `{payload.get('generated_at')}`",
        "",
        "Evidence classification: development diagnostic, not promotion evidence.",
        "",
        "## Overview",
        "",
        *markdown_table(
            [
                "Market",
                "Classification",
                "Current fallback share",
                "Daily candidate",
                "Daily current",
                "Daily market",
                "Daily gap vs market",
                "Regresses current",
                "Winner gap vs market",
                "Primary repair",
            ],
            _overview_rows(payload.get("markets") or []),
        ),
        "",
    ]
    for market in payload.get("markets") or []:
        lines.extend([
            f"## {market.get('market_id')}",
            "",
            "Recommended repairs:",
            "",
            *markdown_table(
                ["Priority", "Action", "Detail"],
                _repair_rows(market),
            ),
            "",
            *markdown_table(
                [
                    "Slice",
                    "Group",
                    "Rows",
                    "Candidate",
                    "Market",
                    "Gap vs market",
                    "Weighted gap",
                    "Winner gap vs market",
                ],
                _slice_rows(market),
            ),
            "",
        ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score blocked-market repair slices from variant rows.")
    parser.add_argument("rows", nargs="+", help="Variant row CSV exports.")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--market-tol", type=float, default=0.003)
    parser.add_argument("--current-tol", type=float, default=0.0005)
    parser.add_argument("--min-slice-rows", type=int, default=200)
    parser.add_argument("--top-slices", type=int, default=8)
    args = parser.parse_args(argv)

    payload = build_payload(
        args.rows,
        market_tol=args.market_tol,
        current_tol=args.current_tol,
        min_slice_rows=args.min_slice_rows,
        top_slices=args.top_slices,
    )
    out_path = write_json(args.out, payload)
    report_path = write_markdown_report(args.report, payload)
    print(
        f"Blocked-market repair diagnostics: {len(payload.get('markets') or [])} markets, "
        f"{payload.get('row_count', 0)} rows"
    )
    print(f"JSON written to {out_path}")
    print(f"Report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
