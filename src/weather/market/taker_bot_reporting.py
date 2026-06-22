"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_scoring import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def fmt_num(value, digits=4):
    number = maybe_float(value)
    return "-" if number is None else f"{number:.{digits}f}"


def render_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    pnl_summary = pnl.get("summary") or {}
    tape_integrity = payload.get("tape_integrity") or summary.get("tape_integrity") or {}
    lines = [
        "# Taker Bot Paper Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Budget USDC", fmt_num(summary.get("budget_usdc"), 2)],
            ["Budget spent USDC", fmt_num(summary.get("budget_spent_usdc"), 2)],
            ["Budget remaining USDC", fmt_num(summary.get("budget_remaining_usdc"), 2)],
            ["Active strategy", summary.get("active_strategy_id") or "-"],
            ["Active strategy lifecycle", summary.get("active_strategy_lifecycle") or "-"],
            ["Canary sample target", (summary.get("active_strategy_canary") or {}).get("min_settled_orders") or "-"],
            ["Weak-slot gate", summary.get("weak_slot_gate_status") or "-"],
            ["Weak-slot blocked rows", summary.get("weak_slot_blocked_rows")],
            ["Market-centered warm-tail rows", summary.get("market_centered_warm_tail_rows")],
            ["Warm-tail blocked/capped rows", summary.get("market_centered_warm_tail_blocked_rows")],
            ["Next-run policy status", summary.get("next_run_policy_status") or "-"],
            ["Latest tick rows", summary.get("latest_tick_rows")],
            ["New filled buys", summary.get("latest_tick_filled_orders")],
            ["Cumulative filled buys", pnl_summary.get("filled_order_count")],
            ["Zero-trade root cause", summary.get("root_cause_class")],
            ["First failing gate", summary.get("first_failing_gate") or "-"],
            ["Zero trades expected", str(summary.get("zero_trades_expected")).lower()],
            [
                "Tape integrity",
                (
                    f"{tape_integrity.get('status') or '-'} "
                    f"({tape_integrity.get('actual_rows', 0)}/{tape_integrity.get('expected_rows', 0)} rows)"
                ),
            ],
            ["Settled / unsettled", f"{pnl_summary.get('settled_order_count')} / {pnl_summary.get('unsettled_order_count')}"],
            ["Net P&L USDC", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## P&L", ""])
    lines.extend(markdown_table(
        ["Component", "USDC"],
        [
            ["Gross cost", fmt_num(pnl_summary.get("gross_cost_usdc"), 4)],
            ["Fees", fmt_num(pnl_summary.get("fees_usdc"), 4)],
            ["Settlement payout", fmt_num(pnl_summary.get("settlement_payout_usdc"), 4)],
            ["Settlement P&L", fmt_num(pnl_summary.get("settlement_pnl_usdc"), 4)],
            ["Mark-to-market P&L", fmt_num(pnl_summary.get("mark_to_market_pnl_usdc"), 4)],
            ["Net P&L", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## Markets", ""])
    lines.extend(markdown_table(
        ["Market", "Filled", "Shares", "Spent", "Net P&L"],
        [
            [
                row.get("market_id"),
                row.get("filled_order_count"),
                fmt_num(row.get("filled_shares"), 3),
                fmt_num(row.get("spent_usdc"), 2),
                fmt_num(row.get("net_pnl_usdc"), 4),
            ]
            for row in pnl.get("by_market") or []
        ],
    ))
    strategy_rows = pnl.get("by_strategy") or []
    if strategy_rows:
        lines.extend(["", "## Strategies", ""])
        lines.extend(markdown_table(
            ["Strategy", "Family", "Orders", "Filled", "Opinions", "Spent", "Net P&L", "P&L Source"],
            [
                [
                    row.get("strategy_id"),
                    row.get("strategy_family"),
                    row.get("order_rows"),
                    row.get("filled_order_count"),
                    row.get("independent_opinion_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    row.get("pnl_source"),
                ]
                for row in strategy_rows
            ],
        ))
    high_rows = [
        (row.get("market_id"), row.get("current_high_assessment") or {})
        for row in payload.get("markets") or []
        if row.get("current_high_assessment")
    ]
    if high_rows:
        lines.extend(["", "## Current High Assessment", ""])
        lines.extend(markdown_table(
            [
                "Market",
                "Raw high",
                "Settlement high",
                "Raw prob",
                "Settlement prob",
                "Revision",
                "Current max state",
                "Trusted",
            ],
            [
                [
                    market_id,
                    assessment.get("raw_current_high"),
                    assessment.get("settlement_current_high"),
                    assessment.get("probability_on_raw_current_high"),
                    assessment.get("probability_on_settlement_current_high"),
                    assessment.get("revision_state") or "-",
                    assessment.get("current_max_state") or "-",
                    str(assessment.get("current_high_trusted")).lower(),
                ]
                for market_id, assessment in high_rows
            ],
        ))
    lines.extend(["", "## Reasons", ""])
    lines.extend(markdown_table(
        ["Reason", "Rows"],
        [[key, value] for key, value in sorted((pnl_summary.get("reason_counts") or {}).items())],
    ))
    lines.append("")
    return "\n".join(lines)


def build_strategy_summary_payload(pnl_payload, run_config=None, run_id=None, target_date=None, now=None):
    now = utc_now(now)
    return {
        "schema_version": STRATEGY_REPORT_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id or (pnl_payload or {}).get("run_id"),
        "target_date": ensure_date(target_date or (pnl_payload or {}).get("target_date")),
        "experiment_id": (run_config or {}).get("experiment_id"),
        "control_strategy_id": (run_config or {}).get("control_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_registry": (run_config or {}).get("strategy_registry") or strategy_registry_payload(),
        "strategies": (pnl_payload or {}).get("by_strategy") or [],
        "comparison": (pnl_payload or {}).get("strategy_comparison") or {},
    }


def render_strategy_report(payload):
    comparison = payload.get("comparison") or {}
    strategies = payload.get("strategies") or []
    lines = [
        "# Taker Strategy Comparison Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Experiment ID: `{payload.get('experiment_id') or '-'}`",
        f"Control strategy: `{payload.get('control_strategy_id') or DEFAULT_CONTROL_STRATEGY_ID}`",
        "",
        "## Comparison",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Strategy count", comparison.get("strategy_count")],
            ["Best strategy by net P&L", comparison.get("best_strategy_id") or "-"],
            ["Best strategy net P&L", fmt_num(comparison.get("best_strategy_net_pnl_usdc"), 4)],
            ["Best settlement-scored strategy", comparison.get("best_settlement_scored_strategy_id") or "-"],
            ["Settlement-scored candidate status", comparison.get("countable_strategy_quality_candidate_status")],
        ],
    ))
    lines.extend(["", "## Strategies", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Family",
            "Orders",
            "Filled",
            "Opinions",
            "Settled",
            "Unsettled",
            "Spent",
            "Expected P&L",
            "Risk-Adj Exp P&L",
            "Settlement P&L",
            "MTM P&L",
            "Net P&L",
            "Realized - Expected",
            "Tail Fills",
            "Countable",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("order_rows"),
                row.get("filled_order_count"),
                row.get("independent_opinion_count"),
                row.get("settled_order_count"),
                row.get("unsettled_order_count"),
                fmt_num(row.get("spent_usdc"), 2),
                fmt_num(row.get("expected_pnl_usdc"), 4),
                fmt_num(row.get("risk_adjusted_expected_pnl_usdc"), 4),
                fmt_num(row.get("settlement_pnl_usdc"), 4),
                fmt_num(row.get("mark_to_market_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                fmt_num(row.get("realized_minus_expected_pnl_usdc"), 4),
                row.get("low_price_tail_fill_count"),
                str(row.get("quality_candidate_countable")).lower(),
            ]
            for row in strategies
        ],
    ))
    lines.append("")
    return "\n".join(lines)

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
