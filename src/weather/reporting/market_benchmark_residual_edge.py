"""Market benchmark and residual-edge research lane.

This artifact answers two separate questions:
1. whether market prices improve settlement probability forecasts, and
2. whether any residual edge is executable after depth, fees, slippage,
   no-trade baselines, tail losses, and MTM-vs-settlement reconciliation.

It is explicitly not weather-only promotion evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_benchmark_residual_edge")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_ACTIVE_SHADOW_LONG = DEFAULT_BACKTEST_ROOT / "active_variant_shadow_long.csv"
DEFAULT_TRADING_EVIDENCE = DEFAULT_BACKTEST_ROOT / "trading_evidence.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "market_benchmark_residual_edge.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "market_benchmark_residual_edge.md"
EDGE_THRESHOLD = 0.03

CONTRACT_ALIASES = {
    "snapshot_timestamp": ("captured_at_local", "captured_at_utc"),
    "market_timestamp": ("book_time_utc", "book_timestamp", "event_updated_at"),
    "book_age": ("book_age_seconds", "clob_book_age_seconds"),
    "token_mapping": ("clob_token_id", "clob_yes_token_id", "clob_no_token_id", "clob_token_ids"),
    "bid": ("best_bid", "bid_price", "market_bid"),
    "ask": ("best_ask", "ask_price", "market_ask"),
    "midpoint": ("clob_midpoint", "market_yes", "market_mid"),
    "spread": ("clob_spread", "spread", "market_spread"),
    "executable_size": ("buy_fillable_10", "ask_size_at_best", "ask_depth_1pct", "executable_size"),
    "depth_tier": ("buy_fillable_100", "ask_depth_5pct", "clob_liquidity_score", "depth_tier"),
    "freshness_state": ("clob_continuity_status", "quote_risk_gate_reason", "clob_feature_available"),
}

TRADING_REQUIRED_FIELDS = (
    "fees_usdc",
    "slippage_usdc",
    "settlement_scored_net_pnl_usdc",
    "mark_to_market_pnl_usdc",
    "market_benchmark_status",
    "market_benchmark_no_trade_net_pnl_usdc",
    "market_benchmark_avoided_loss_usdc",
    "market_benchmark_missed_gain_usdc",
)


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _boolish(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _first(row, names):
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def _brier(rows, probability_key):
    values = []
    for row in rows:
        probability = _float(row.get(probability_key))
        outcome = _float(row.get("outcome"))
        if probability is None or outcome not in {0.0, 1.0}:
            continue
        values.append((probability - outcome) ** 2)
    return sum(values) / len(values) if values else None


def _score_rows(rows):
    scored = []
    for row in rows:
        probability = _float(row.get("probability"))
        market = _float(row.get("market_yes") or row.get("clob_midpoint"))
        outcome = _float(row.get("outcome"))
        if probability is None or market is None or outcome not in {0.0, 1.0}:
            continue
        scored.append({
            **row,
            "_weather_probability": probability,
            "_market_probability": market,
            "_model_minus_market": probability - market,
            "_outcome": outcome,
            "_weather_brier": (probability - outcome) ** 2,
            "_market_brier": (market - outcome) ** 2,
        })
    return scored


def _lane_metrics(rows):
    weather_brier = (
        sum(row["_weather_brier"] for row in rows) / len(rows)
        if rows else None
    )
    market_brier = (
        sum(row["_market_brier"] for row in rows) / len(rows)
        if rows else None
    )
    edge_rows = [
        row for row in rows
        if abs(row["_model_minus_market"]) >= EDGE_THRESHOLD
    ]
    positive_edges = [row for row in edge_rows if row["_model_minus_market"] > 0]
    edge_hit_rate = (
        sum(1 for row in positive_edges if row["_outcome"] == 1.0) / len(positive_edges)
        if positive_edges else None
    )
    return {
        "row_count": len(rows),
        "weather_only_brier": weather_brier,
        "market_only_brier": market_brier,
        "weather_minus_market_brier": (
            weather_brier - market_brier
            if weather_brier is not None and market_brier is not None
            else None
        ),
        "residual_edge_row_count": len(edge_rows),
        "mean_model_minus_market": (
            sum(row["_model_minus_market"] for row in rows) / len(rows)
            if rows else None
        ),
        "mean_abs_model_minus_market": (
            sum(abs(row["_model_minus_market"]) for row in rows) / len(rows)
            if rows else None
        ),
        "positive_residual_edge_hit_rate": edge_hit_rate,
    }


def _overlay_metrics(rows):
    overlay_rows = [
        row for row in rows
        if _boolish(row.get("uses_market_features")) or "market" in str(row.get("claim_lane") or "").lower()
    ]
    return {
        "row_count": len(overlay_rows),
        "brier": _brier(overlay_rows, "probability"),
        "status": "PRESENT" if overlay_rows else "MISSING",
    }


def _slice_key(row, name):
    if name == "market":
        return row.get("market_id") or "unknown"
    if name == "cutoff_regime":
        return row.get("cutoff_regime") or row.get("cutoff_hour") or "unknown"
    if name == "liquidity_state":
        value = _float(row.get("clob_liquidity_score"))
        if value is None:
            return "unknown"
        if value >= 100:
            return "deep"
        if value > 0:
            return "thin"
        return "empty"
    if name == "source_health":
        return row.get("source_freshness_state") or row.get("quote_risk_gate_reason") or "unknown"
    if name == "tail_risk":
        return row.get("settlement_distance_bucket") or "unknown"
    return "unknown"


def _slices(rows):
    output = []
    for name in ("market", "cutoff_regime", "liquidity_state", "source_health", "tail_risk"):
        groups = defaultdict(list)
        for row in rows:
            groups[_slice_key(row, name)].append(row)
        for group, group_rows in sorted(groups.items()):
            output.append({
                "slice": name,
                "group": group,
                **_lane_metrics(group_rows),
            })
    return output


def _field_contract(rows):
    field_rows = []
    blockers = []
    columns = set()
    non_empty_by_field = Counter()
    for row in rows:
        columns.update(row)
        for field, aliases in CONTRACT_ALIASES.items():
            if _first(row, aliases) not in (None, ""):
                non_empty_by_field[field] += 1
    for field, aliases in CONTRACT_ALIASES.items():
        present_aliases = sorted(alias for alias in aliases if alias in columns)
        non_empty = non_empty_by_field[field]
        status = "PASS" if present_aliases and non_empty else "BLOCK"
        detail = (
            f"{non_empty} non-empty rows via {', '.join(present_aliases)}"
            if status == "PASS"
            else f"missing non-empty field aliases: {', '.join(aliases)}"
        )
        row = {
            "field": field,
            "status": status,
            "aliases": list(aliases),
            "present_aliases": present_aliases,
            "non_empty_rows": non_empty,
            "detail": detail,
        }
        field_rows.append(row)
        if status != "PASS":
            blockers.append(row)
    return {
        "status": "PASS" if not blockers else "BLOCK",
        "row_count": len(rows),
        "fields": field_rows,
        "blockers": blockers,
    }


def _strategy_rows_from_trading_evidence(payload):
    taker = payload.get("taker") or {}
    comparison = taker.get("strategy_comparison") or {}
    return comparison.get("by_strategy") or taker.get("by_strategy") or []


def _trading_reconciliation(payload):
    taker = payload.get("taker") or {}
    comparison = taker.get("strategy_comparison") or {}
    strategy_rows = _strategy_rows_from_trading_evidence(payload)
    missing = []
    rows = []
    for strategy in strategy_rows:
        missing_fields = [
            field for field in TRADING_REQUIRED_FIELDS
            if strategy.get(field) in (None, "")
        ]
        if missing_fields:
            missing.append({
                "strategy_id": strategy.get("strategy_id") or strategy.get("id") or "unknown",
                "missing_fields": missing_fields,
            })
        rows.append({
            "strategy_id": strategy.get("strategy_id") or strategy.get("id") or "unknown",
            "fees_usdc": strategy.get("fees_usdc"),
            "slippage_usdc": strategy.get("slippage_usdc"),
            "settlement_scored_net_pnl_usdc": strategy.get("settlement_scored_net_pnl_usdc"),
            "mark_to_market_pnl_usdc": strategy.get("mark_to_market_pnl_usdc"),
            "mtm_minus_settlement_usdc": (
                _float(strategy.get("mark_to_market_pnl_usdc"), 0.0)
                - _float(strategy.get("settlement_scored_net_pnl_usdc"), 0.0)
            ),
            "market_benchmark_status": strategy.get("market_benchmark_status"),
            "no_trade_net_pnl_usdc": strategy.get("market_benchmark_no_trade_net_pnl_usdc"),
            "avoided_loss_usdc": strategy.get("market_benchmark_avoided_loss_usdc"),
            "missed_gain_usdc": strategy.get("market_benchmark_missed_gain_usdc"),
            "tail_bucket": (strategy.get("tail_fill_quality_summary") or {}).get("status"),
        })
    summary = {
        "strategy_count": len(rows),
        "missing_required_field_strategy_count": len(missing),
        "market_benchmark_status": comparison.get("market_benchmark_status") or taker.get("market_benchmark_status"),
        "market_benchmark_summary": (
            comparison.get("market_benchmark_summary")
            or taker.get("market_benchmark_summary")
            or {}
        ),
        "mtm_promotion_allowed": bool(comparison.get("mtm_promotion_allowed")),
        "promotion_evidence_basis": comparison.get("promotion_evidence_basis"),
    }
    if not rows:
        missing.append({"strategy_id": "all", "missing_fields": ["strategy_rows"]})
    status = "PASS" if not missing and summary["market_benchmark_status"] not in {None, "BLOCK_MARKET_SMARTER"} else "BLOCK"
    return {
        "status": status,
        "summary": summary,
        "strategy_rows": rows,
        "missing_required_fields": missing,
    }


def build_report(
    *,
    active_shadow_long=DEFAULT_ACTIVE_SHADOW_LONG,
    trading_evidence=DEFAULT_TRADING_EVIDENCE,
    generated_at_utc=None,
):
    rows = _read_csv(active_shadow_long)
    scored_rows = _score_rows(rows)
    contract = _field_contract(rows)
    settlement = {
        "weather_only_vs_market": _lane_metrics(scored_rows),
        "market_informed_overlay": _overlay_metrics(scored_rows),
        "slices": _slices(scored_rows),
    }
    trading_payload = _read_json(trading_evidence)
    trading = _trading_reconciliation(trading_payload)
    blockers = []
    if not scored_rows:
        blockers.append({"category": "settlement_scoring", "detail": "no scored market benchmark rows"})
    if contract["status"] != "PASS":
        blockers.append({"category": "frozen_market_contract", "detail": "frozen CLOB fields are missing"})
    if trading["status"] != "PASS":
        blockers.append({"category": "trading_execution", "detail": "trading-facing benchmark fields are incomplete or blocked"})
    proof_guard = {
        "counts_toward_weather_model_promotion": False,
        "status": "BLOCKED_FROM_WEATHER_PROOF",
        "detail": "Market-only, market-informed overlay, and residual-edge evidence cannot satisfy weather-only proof-packet blockers.",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": "BLOCK" if blockers else "PASS",
        "inputs": {
            "active_shadow_long": str(active_shadow_long),
            "trading_evidence": str(trading_evidence),
        },
        "summary": {
            "source_row_count": len(rows),
            "scored_row_count": len(scored_rows),
            "contract_status": contract["status"],
            "trading_status": trading["status"],
            "blocker_count": len(blockers),
            "weather_minus_market_brier": settlement["weather_only_vs_market"].get("weather_minus_market_brier"),
            "overlay_status": settlement["market_informed_overlay"].get("status"),
        },
        "proof_guard": proof_guard,
        "frozen_market_benchmark_contract": contract,
        "settlement_accuracy": settlement,
        "trading_execution": trading,
        "blockers": blockers,
    }


def render_report(payload):
    summary = payload.get("summary") or {}
    settlement = payload.get("settlement_accuracy") or {}
    weather = settlement.get("weather_only_vs_market") or {}
    overlay = settlement.get("market_informed_overlay") or {}
    trading = payload.get("trading_execution") or {}
    trading_summary = trading.get("summary") or {}
    lines = [
        "# Market Benchmark And Residual Edge Research Lane",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Proof Guard",
        "",
        (payload.get("proof_guard") or {}).get("detail") or "-",
        "",
        "## Summary",
        "",
    ]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Source rows", summary.get("source_row_count")],
            ["Scored rows", summary.get("scored_row_count")],
            ["Frozen market contract", summary.get("contract_status")],
            ["Trading execution", summary.get("trading_status")],
            ["Weather minus market Brier", fmt_signed(summary.get("weather_minus_market_brier"), 4)],
            ["Overlay status", summary.get("overlay_status")],
            ["Blockers", summary.get("blocker_count")],
        ],
    )
    lines += ["", "## Settlement Accuracy", ""]
    lines += markdown_table(
        ["Lane", "Rows", "Brier / Delta", "Detail"],
        [
            [
                "weather_only",
                weather.get("row_count"),
                fmt_num(weather.get("weather_only_brier"), 4),
                f"delta_vs_market={fmt_signed(weather.get('weather_minus_market_brier'), 4)}",
            ],
            [
                "market_only",
                weather.get("row_count"),
                fmt_num(weather.get("market_only_brier"), 4),
                "Polymarket midpoint/market_yes benchmark",
            ],
            [
                "market_informed_overlay",
                overlay.get("row_count"),
                fmt_num(overlay.get("brier"), 4),
                overlay.get("status"),
            ],
            [
                "residual_edge",
                weather.get("residual_edge_row_count"),
                fmt_num(weather.get("mean_abs_model_minus_market"), 4),
                f"positive_edge_hit_rate={fmt_num(weather.get('positive_residual_edge_hit_rate'), 3)}",
            ],
        ],
    )
    lines += ["", "## Frozen Market Contract", ""]
    contract = payload.get("frozen_market_benchmark_contract") or {}
    lines += markdown_table(
        ["Field", "Status", "Non-Empty Rows", "Detail"],
        [
            [row.get("field"), row.get("status"), row.get("non_empty_rows"), row.get("detail")]
            for row in contract.get("fields") or []
        ],
    )
    lines += ["", "## Trading Execution", ""]
    lines += markdown_table(
        ["Metric", "Value"],
        [
            ["Status", trading.get("status")],
            ["Strategies", trading_summary.get("strategy_count")],
            ["Missing required fields", trading_summary.get("missing_required_field_strategy_count")],
            ["Market benchmark status", trading_summary.get("market_benchmark_status")],
            ["MTM promotion allowed", trading_summary.get("mtm_promotion_allowed")],
            ["Promotion evidence basis", trading_summary.get("promotion_evidence_basis")],
        ],
    )
    strategy_rows = trading.get("strategy_rows") or []
    if strategy_rows:
        lines += ["", "### MTM Versus Settlement", ""]
        lines += markdown_table(
            ["Strategy", "Fees", "Slippage", "Settlement PnL", "MTM PnL", "MTM-Settlement", "No-Trade", "Benchmark"],
            [
                [
                    row.get("strategy_id"),
                    fmt_num(row.get("fees_usdc"), 4),
                    fmt_num(row.get("slippage_usdc"), 4),
                    fmt_num(row.get("settlement_scored_net_pnl_usdc"), 4),
                    fmt_num(row.get("mark_to_market_pnl_usdc"), 4),
                    fmt_signed(row.get("mtm_minus_settlement_usdc"), 4),
                    fmt_num(row.get("no_trade_net_pnl_usdc"), 4),
                    row.get("market_benchmark_status") or "-",
                ]
                for row in strategy_rows[:20]
            ],
        )
    slices = settlement.get("slices") or []
    if slices:
        lines += ["", "## Residual Edge Slices", ""]
        lines += markdown_table(
            ["Slice", "Group", "Rows", "Weather-Market Brier", "Mean Abs Edge"],
            [
                [
                    row.get("slice"),
                    row.get("group"),
                    row.get("row_count"),
                    fmt_signed(row.get("weather_minus_market_brier"), 4),
                    fmt_num(row.get("mean_abs_model_minus_market"), 4),
                ]
                for row in slices[:80]
            ],
        )
    blockers = payload.get("blockers") or []
    if blockers:
        lines += ["", "## Blockers", ""]
        lines += markdown_table(
            ["Category", "Detail"],
            [[row.get("category"), row.get("detail")] for row in blockers],
        )
    return "\n".join(lines) + "\n"


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_out = Path(json_out)
    report_out = Path(report_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    report_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_out.write_text(render_report(payload), encoding="utf-8")
    return json_out, report_out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build market benchmark and residual-edge research report.")
    parser.add_argument("--active-shadow-long", default=str(DEFAULT_ACTIVE_SHADOW_LONG))
    parser.add_argument("--trading-evidence", default=str(DEFAULT_TRADING_EVIDENCE))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    args = parser.parse_args(argv)
    payload = build_report(
        active_shadow_long=args.active_shadow_long,
        trading_evidence=args.trading_evidence,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Market benchmark residual-edge lane: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return payload


if __name__ == "__main__":
    main()
