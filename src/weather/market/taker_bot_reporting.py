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
    no_side_campaign = summary.get("no_side_campaign") or {}
    counterfactual_no_side_campaign = summary.get("counterfactual_no_side_campaign") or {}
    edge_permission = summary.get("taker_edge_permission_coverage") or {}
    scoring_liveness = summary.get("latest_tick_scoring_liveness") or {}
    last_nonzero_tick = summary.get("last_nonzero_scored_tick") or scoring_liveness.get("last_nonzero_scored_tick") or {}
    upstream = summary.get("upstream_dependency_status") or {}
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
            ["Exchange economics", summary.get("exchange_economics_gate_status") or "-"],
            ["Exchange snapshot", summary.get("exchange_economics_snapshot_id") or "-"],
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
            ["Last nonzero scored tick rows", last_nonzero_tick.get("row_count") or "-"],
            ["Last nonzero scored tick generated", last_nonzero_tick.get("generated_at_utc") or "-"],
            ["Edge-permission allowed rows", edge_permission.get("edge_allowed_rows")],
            ["Edge-permission denied/observe rows", edge_permission.get("not_edge_allowed_rows")],
            ["After-cost EV skipped rows", edge_permission.get("after_cost_ev_skipped_rows")],
            ["Adverse-selection blocked rows", edge_permission.get("adverse_selection_blocked_rows")],
            ["Counterfactual rows", summary.get("latest_tick_counterfactual_rows")],
            ["Counterfactual would-buy rows", summary.get("latest_tick_counterfactual_would_buy_count")],
            ["Latest-tick scoring liveness", scoring_liveness.get("status") or "-"],
            ["Taker day classification", summary.get("taker_day_classification") or "-"],
            ["Zero would-buy classification", summary.get("zero_would_buy_classification") or "-"],
            ["Taker evidence countability", summary.get("taker_evidence_countability_status") or "-"],
            ["Upstream dependency status", upstream.get("status") or "-"],
            ["First failing dependency", upstream.get("first_failing_dependency") or "-"],
            ["Newest snapshot", upstream.get("newest_snapshot_timestamp_utc") or "-"],
            ["Latest source status", upstream.get("latest_source_status_utc") or "-"],
            ["NO-side campaign status", counterfactual_no_side_campaign.get("status") or no_side_campaign.get("status") or "-"],
            ["NO-side real-book rows", counterfactual_no_side_campaign.get("real_no_book_row_count") or no_side_campaign.get("real_no_book_row_count") or 0],
            ["NO-side countable would-buy rows", counterfactual_no_side_campaign.get("countable_no_side_would_buy_count") or no_side_campaign.get("countable_no_side_would_buy_count") or 0],
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
            [
                "Counterfactual tape integrity",
                (
                    f"{(summary.get('counterfactual_tape_integrity') or {}).get('status') or '-'} "
                    f"({(summary.get('counterfactual_tape_integrity') or {}).get('actual_rows', 0)}/"
                    f"{(summary.get('counterfactual_tape_integrity') or {}).get('expected_rows', 0)} rows)"
                ),
            ],
            ["Settled / unsettled", f"{pnl_summary.get('settled_order_count')} / {pnl_summary.get('unsettled_order_count')}"],
            ["Net P&L USDC", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
            ["Executable net P&L", fmt_num(pnl_summary.get("executable_net_pnl_usdc"), 4)],
            ["Live profitability basis", pnl_summary.get("live_profitability_evidence_basis") or "-"],
        ],
    ))
    if no_side_campaign or counterfactual_no_side_campaign:
        lines.extend(["", "## NO-Side Campaign", ""])
        lines.extend(markdown_table(
            [
                "Source",
                "Status",
                "NO Rows",
                "Real Book",
                "Synthetic",
                "Stale",
                "Would Buy",
                "Countable Would Buy",
                "Net P&L",
            ],
            [
                [
                    "Actual",
                    no_side_campaign.get("status") or "-",
                    no_side_campaign.get("no_side_row_count") or 0,
                    no_side_campaign.get("real_no_book_row_count") or 0,
                    no_side_campaign.get("synthetic_no_book_row_count") or 0,
                    no_side_campaign.get("stale_no_book_row_count") or 0,
                    no_side_campaign.get("no_side_would_buy_count") or 0,
                    no_side_campaign.get("countable_no_side_would_buy_count") or 0,
                    fmt_num(no_side_campaign.get("countable_no_side_net_pnl_usdc"), 4),
                ],
                [
                    "Counterfactual",
                    counterfactual_no_side_campaign.get("status") or "-",
                    counterfactual_no_side_campaign.get("no_side_row_count") or 0,
                    counterfactual_no_side_campaign.get("real_no_book_row_count") or 0,
                    counterfactual_no_side_campaign.get("synthetic_no_book_row_count") or 0,
                    counterfactual_no_side_campaign.get("stale_no_book_row_count") or 0,
                    counterfactual_no_side_campaign.get("no_side_would_buy_count") or 0,
                    counterfactual_no_side_campaign.get("countable_no_side_would_buy_count") or 0,
                    fmt_num(counterfactual_no_side_campaign.get("countable_no_side_net_pnl_usdc"), 4),
                ],
            ],
        ))
    lines.extend(["", "## P&L", ""])
    lines.extend(markdown_table(
        ["Component", "USDC"],
        [
            ["Gross cost", fmt_num(pnl_summary.get("gross_cost_usdc"), 4)],
            ["Frictionless cost", fmt_num(pnl_summary.get("frictionless_cost_usdc"), 4)],
            ["Fees", fmt_num(pnl_summary.get("fees_usdc"), 4)],
            ["Slippage", fmt_num(pnl_summary.get("slippage_usdc"), 4)],
            ["Settlement payout", fmt_num(pnl_summary.get("settlement_payout_usdc"), 4)],
            ["Gross P&L", fmt_num(pnl_summary.get("gross_pnl_usdc"), 4)],
            ["Fee P&L", fmt_num(pnl_summary.get("fee_pnl_usdc"), 4)],
            ["Slippage P&L", fmt_num(pnl_summary.get("slippage_pnl_usdc"), 4)],
            ["Settlement P&L", fmt_num(pnl_summary.get("settlement_pnl_usdc"), 4)],
            ["Mark-to-market P&L", fmt_num(pnl_summary.get("mark_to_market_pnl_usdc"), 4)],
            ["Executable net P&L", fmt_num(pnl_summary.get("executable_net_pnl_usdc"), 4)],
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
            ["Strategy", "Family", "Orders", "Filled", "Opinions", "Spent", "Fees", "Slippage", "Executable Net", "Net P&L", "Live Basis", "P&L Source"],
            [
                [
                    row.get("strategy_id"),
                    row.get("strategy_family"),
                    row.get("order_rows"),
                    row.get("filled_order_count"),
                    row.get("independent_opinion_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("fees_usdc"), 4),
                    fmt_num(row.get("slippage_usdc"), 4),
                    fmt_num(row.get("executable_net_pnl_usdc"), 4),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    row.get("live_profitability_evidence_basis") or "-",
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
        "tail_fill_quality": (pnl_payload or {}).get("tail_fill_quality") or {},
        "taker_edge_permission_coverage": (run_config or {}).get("taker_edge_permission_coverage") or {},
        "exchange_economics_gate": (run_config or {}).get("exchange_economics_gate") or (pnl_payload or {}).get("exchange_economics_gate") or {},
        **{
            key: (run_config or {}).get(key) or (pnl_payload or {}).get(key)
            for key in (
                "exchange_economics_status",
                "exchange_economics_evidence_basis",
                "exchange_economics_snapshot_id",
                "exchange_economics_hash",
                "exchange_economics_source_hash",
                "exchange_economics_verified_at_utc",
                "exchange_economics_effective_date",
                "exchange_economics_platform",
            )
        },
    }


def render_strategy_report(payload):
    comparison = payload.get("comparison") or {}
    strategies = payload.get("strategies") or []
    edge_permission = payload.get("taker_edge_permission_coverage") or {}
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
            ["Promotion evidence basis", comparison.get("promotion_evidence_basis") or "-"],
            ["Exchange economics", (payload.get("exchange_economics_gate") or {}).get("status") or payload.get("exchange_economics_status") or "-"],
            ["Exchange snapshot", payload.get("exchange_economics_snapshot_id") or "-"],
            ["Market benchmark status", comparison.get("market_benchmark_status") or "-"],
            ["MTM can promote", str(bool(comparison.get("mtm_promotion_allowed"))).lower()],
        ],
    ))
    if edge_permission:
        lines.extend(["", "## Taker Edge Permission", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Enabled", str(edge_permission.get("enabled")).lower()],
                ["Map path", edge_permission.get("map_path") or "-"],
                ["Latest rows", edge_permission.get("row_count")],
                ["Edge allowed rows", edge_permission.get("edge_allowed_rows")],
                ["Not edge allowed rows", edge_permission.get("not_edge_allowed_rows")],
                ["Missing evidence rows", edge_permission.get("missing_evidence_rows")],
                ["Market no-trade rows", edge_permission.get("market_no_trade_rows")],
                ["After-cost EV skipped rows", edge_permission.get("after_cost_ev_skipped_rows")],
                ["Adverse-selection blocked rows", edge_permission.get("adverse_selection_blocked_rows")],
                ["Permission counts", edge_permission.get("permission_counts")],
                ["Evidence counts", edge_permission.get("evidence_status_counts")],
                ["Adverse-selection counts", edge_permission.get("adverse_selection_counts")],
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
            "Fees",
            "Slippage",
            "Executable Net",
            "Net P&L",
            "Live Basis",
            "Market Benchmark",
            "Realized - Expected",
            "Tail Fills",
            "Tail Fraction",
            "Tail Gate",
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
                fmt_num(row.get("fees_usdc"), 4),
                fmt_num(row.get("slippage_usdc"), 4),
                fmt_num(row.get("executable_net_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                row.get("live_profitability_evidence_basis") or "-",
                row.get("market_benchmark_status") or "-",
                fmt_num(row.get("realized_minus_expected_pnl_usdc"), 4),
                row.get("low_price_tail_fill_count"),
                fmt_num(row.get("low_price_tail_fill_fraction"), 4),
                (row.get("tail_fill_quality_summary") or {}).get("status") or "-",
                str(row.get("quality_candidate_countable")).lower(),
            ]
            for row in strategies
        ],
    ))
    tail_quality = payload.get("tail_fill_quality") or {}
    tail_summary = tail_quality.get("summary") or {}
    if tail_summary:
        lines.extend(["", "## Tail Fill Quality", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", tail_summary.get("status") or "-"],
                ["Tail fills", tail_summary.get("low_price_tail_fill_count")],
                ["Tail fill fraction", fmt_num(tail_summary.get("low_price_tail_fill_fraction"), 4)],
                ["Max tail fill fraction", fmt_num(tail_summary.get("max_tail_fill_fraction"), 4)],
                ["Settled / unsettled tail fills", f"{tail_summary.get('settled_tail_fill_count')}/{tail_summary.get('unsettled_tail_fill_count')}"],
                ["Tail settlement P&L", fmt_num(tail_summary.get("tail_settlement_pnl_usdc"), 4)],
                ["Tail MTM P&L", fmt_num(tail_summary.get("tail_mark_to_market_pnl_usdc"), 4)],
                ["Alerts", tail_summary.get("alert_count")],
            ],
        ))
    tail_rows = tail_quality.get("by_market_range") or []
    if tail_rows:
        lines.extend(["", "## Tail Fills By Market And Range", ""])
        lines.extend(markdown_table(
            ["Strategy", "Market", "Range", "Fills", "Settled", "Wins", "Losses", "Spent", "Net P&L"],
            [
                [
                    row.get("strategy_id"),
                    row.get("market_id"),
                    row.get("range_label"),
                    row.get("fill_count"),
                    row.get("settled_count"),
                    row.get("win_count"),
                    row.get("loss_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                ]
                for row in tail_rows
            ],
        ))
    benchmark = payload.get("market_benchmark_scoreboard") or {}
    benchmark_summary = benchmark.get("summary") or {}
    if benchmark_summary:
        lines.extend(["", "## Market Benchmark", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Opportunities", benchmark_summary.get("opportunity_count")],
                ["Market-smarter slices", benchmark_summary.get("market_smarter_slice_count")],
                ["No-trade recommendations", benchmark_summary.get("no_trade_recommendation_count")],
                ["Traded P&L", fmt_num(benchmark_summary.get("traded_pnl_usdc"), 4)],
                ["Avoided loss", fmt_num(benchmark_summary.get("avoided_loss_usdc"), 4)],
                ["Missed gain", fmt_num(benchmark_summary.get("missed_gain_usdc"), 4)],
            ],
        ))
    lines.append("")
    return "\n".join(lines)

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
