"""Report rendering and known-edge map helpers for MM paper scoring."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from weather.market.mm_paper_constants import (
    DEFAULT_CONFIG,
    DEFAULT_PROMOTION_REFRESH,
    KNOWN_EDGE_SCHEMA_VERSION,
)
from weather.market.mm_policy import maybe_float, parse_time


def utc_now():
    return datetime.now(timezone.utc)


def generated_at_iso(now=None):
    parsed = parse_time(now) if now is not None else None
    return (parsed or utc_now()).astimezone(timezone.utc).isoformat()


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def finite_float(value, default=None):
    number = maybe_float(value)
    return default if number is None else number

def fmt_num(value, digits=4):
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) if value not in (None, "") else "-" for value in row) + " |")
    return lines


def render_paper_report(payload):
    summary = payload["summary"]
    pnl = summary.get("pnl") or {}
    guardrail = summary.get("early_hour_guardrail_shadow") or {}
    guardrail_exposure = guardrail.get("quote_exposure") or {}
    evidence = summary.get("trade_evidence_gaps") or {}
    anti = summary.get("anti_overfit") or {}
    freshness = summary.get("paper_score_freshness") or {}
    exchange_gate = summary.get("exchange_economics_gate") or payload.get("exchange_economics_gate") or {}
    event_gate = summary.get("event_gate_score") or {}
    clob_recon = summary.get("clob_recon") or {}
    live_forward_evidence = summary.get("per_market_live_forward_evidence") or {}
    fill_evidence = payload.get("fill_evidence_completeness") or summary.get("fill_evidence_completeness") or {}
    selection = summary.get("run_folder_selection") or payload.get("run_folder_selection") or {}
    reward_score = payload.get("reward_score_diagnostics") or summary.get("reward_score_diagnostics") or {}
    quote_blockers = payload.get("quote_blocker_diagnostics") or summary.get("quote_blocker_diagnostics") or {}
    model_variant = payload.get("model_variant_bakeoff") or {}
    model_variant_summary = summary.get("model_variant_bakeoff") or {}
    lines = [
        "# Market-Making Paper Report",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Run folders", summary.get("run_folders")],
            ["Candidate run folders", summary.get("candidate_run_folders")],
            ["Available before selection", summary.get("available_run_folders_before_selection")],
            ["Run-folder selection", selection.get("mode") or "full"],
            ["Selection warning", selection.get("warning") or "-"],
            ["Excluded run folders", summary.get("excluded_run_folders")],
            ["Quote rows / legs", f"{summary.get('quote_rows')} / {summary.get('quote_legs')}"],
            [
                "Fill simulation",
                f"{summary.get('fill_simulation_status') or '-'}"
                f" ({summary.get('fill_simulation_reason') or 'included'})",
            ],
            [
                "Model-variant quote rows / legs",
                f"{summary.get('model_variant_quote_rows', 0)} / {summary.get('model_variant_quote_legs', 0)}",
            ],
            [
                "Model-variant scoring",
                f"{summary.get('model_variant_scoring_status') or '-'}"
                f" ({summary.get('model_variant_scoring_reason') or 'included'})",
            ],
            ["Conservative fills", summary.get("conservative_fills")],
            ["Conservative filled shares", fmt_num(summary.get("conservative_filled_shares"), 3)],
            ["Queue-estimated fill legs", summary.get("queue_estimated_fill_legs")],
            ["Queue-estimated shares", fmt_num(summary.get("queue_estimated_filled_shares"), 3)],
            ["Gate status", summary.get("gate_status")],
            ["Exchange economics", exchange_gate.get("status") or summary.get("exchange_economics_gate_status") or "-"],
            ["Exchange snapshot", summary.get("exchange_economics_snapshot_id") or "-"],
            ["Paper-score freshness", freshness.get("status") or "-"],
            ["Fill evidence completeness", fill_evidence.get("status") or "-"],
            ["Latest completed active day", freshness.get("latest_completed_active_day") or "-"],
            ["Latest covered active day", freshness.get("latest_covered_active_day") or "-"],
            ["Locked policy params", anti.get("locked_policy_params")],
            ["Live-forward paper days", len(anti.get("live_forward_days") or [])],
            ["Missing-size trade rows", evidence.get("missing_size_trade_rows")],
        ],
    ))
    lines.extend([
        "",
        "## P&L Decomposition",
        "",
        "Reward and rebate estimates are shown after toxic markout and flattening costs; they do not make a losing markout acceptable.",
        "",
    ])
    lines.extend(markdown_table(
        ["Component", "USDC"],
        [
            ["Spread capture", fmt_num(pnl.get("spread_capture_usdc"), 4)],
            ["Adverse-selection markout 30m", fmt_num(pnl.get("adverse_selection_30m_usdc"), 4)],
            ["Settlement P&L", fmt_num(pnl.get("settlement_pnl_usdc"), 4)],
            ["Maker fee-equivalent", fmt_num(pnl.get("maker_fee_equivalent_usdc"), 4)],
            ["Maker rebate estimate", fmt_num(pnl.get("maker_rebate_estimate_usdc"), 4)],
            ["Liquidity reward estimate", fmt_num(pnl.get("liquidity_reward_estimate_usdc"), 4)],
            ["Flattening fee estimate", fmt_num(pnl.get("flattening_fee_estimate_usdc"), 4)],
            ["Net after fees/incentives", fmt_num(pnl.get("net_pnl_after_fees_incentives_usdc"), 4)],
        ],
    ))
    if reward_score:
        lines.extend([
            "",
            "## Reward Score Diagnostics",
            "",
            "Reward score is reported separately from expected reward dollars. Bounded or incomplete reports remain diagnostic.",
            "",
        ])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", reward_score.get("status") or "-"],
                ["Score basis", reward_score.get("score_basis") or "-"],
                ["Platform", reward_score.get("platform") or "-"],
                ["Exchange economics", reward_score.get("exchange_economics_status") or "-"],
                ["Discount factor", fmt_num(reward_score.get("discount_factor"), 4)],
                ["Tick size", fmt_num(reward_score.get("tick_size"), 4)],
                ["Min order size", fmt_num(reward_score.get("min_order_size"), 4)],
                ["Target size contracts", fmt_num(reward_score.get("target_size_contracts"), 2)],
                ["Campaign pool USDC", fmt_num(reward_score.get("campaign_pool_usdc"), 2)],
                ["Min payout USDC", fmt_num(reward_score.get("min_payout_usdc"), 2)],
                ["Assumed competitor score", fmt_num(reward_score.get("assumed_competitor_score"), 4)],
                ["Quote permission rows", reward_score.get("quote_permission_rows", 0)],
                ["Quoted legs", reward_score.get("quoted_legs", 0)],
                ["Positive-score legs", reward_score.get("positive_score_legs", 0)],
                ["Unscored legs", reward_score.get("unscored_legs", 0)],
                ["Total reward score", fmt_num(reward_score.get("total_reward_score"), 6)],
                ["Score / target-size", fmt_num(reward_score.get("score_to_target_size_fraction"), 8)],
                ["Target size met", reward_score.get("score_at_or_above_target_size")],
                ["Counterfactual score share", fmt_num(reward_score.get("counterfactual_score_share"), 8)],
                [
                    "Counterfactual reward before min payout",
                    fmt_num(reward_score.get("counterfactual_reward_before_min_payout_usdc"), 4),
                ],
                ["Counterfactual reward USDC", fmt_num(reward_score.get("counterfactual_reward_usdc"), 4)],
                ["Counterfactual status", reward_score.get("counterfactual_reward_status") or "-"],
                ["Actual payout evidence", reward_score.get("actual_payout_evidence")],
                ["Changes P&L", not reward_score.get("does_not_change_pnl", True)],
            ],
        ))
        groups = reward_score.get("score_attribution_top_groups") or []
        if groups:
            lines.extend(["", "### Reward Score Attribution", ""])
            lines.extend(markdown_table(
                ["Market", "Range", "Hour", "Side", "Legs", "Score", "Own-score share", "Counterfactual USDC"],
                [
                    [
                        row.get("market_id"),
                        row.get("range_label"),
                        row.get("hour_utc"),
                        row.get("side"),
                        row.get("quoted_legs", 0),
                        fmt_num(row.get("reward_score"), 6),
                        fmt_num(row.get("share_of_own_score"), 8),
                        fmt_num(row.get("counterfactual_reward_usdc"), 4),
                    ]
                    for row in groups[:10]
                ],
            ))
        blocker_counts = reward_score.get("blocker_counts") or {}
        if blocker_counts:
            lines.extend(["", "### Reward Score Blockers", ""])
            lines.extend(markdown_table(
                ["Blocker", "Count"],
                [[key, value] for key, value in sorted(blocker_counts.items())],
            ))
        no_quote_counts = reward_score.get("no_quote_reason_counts") or {}
        if no_quote_counts:
            lines.extend(["", "### No-Quote Reasons", ""])
            lines.extend(markdown_table(
                ["Reason", "Rows"],
                [[key, value] for key, value in sorted(no_quote_counts.items())],
            ))
    if quote_blockers:
        lines.extend([
            "",
            "## Quote Blocker Diagnostics",
            "",
            "Blocked rows are quote-intent rows that did not produce a quoted leg. This section is diagnostic and does not relax policy gates.",
            "",
        ])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Quote rows", quote_blockers.get("quote_rows", 0)],
                ["Quote-permission rows", quote_blockers.get("quote_permission_rows", 0)],
                ["Blocked rows", quote_blockers.get("blocked_rows", 0)],
                ["Blocked fraction", fmt_num(quote_blockers.get("blocked_fraction"), 6)],
                ["Known-edge permission-blocked rows", quote_blockers.get(
                    "known_edge_permission_blocked_rows",
                    quote_blockers.get("known_edge_blocked_rows", 0),
                )],
                ["Known-edge state rows", quote_blockers.get("known_edge_state_rows", 0)],
                ["Known-edge allowed=false rows", quote_blockers.get("known_edge_allowed_false_rows", 0)],
                ["Harvest-only suppressed by other gate rows", quote_blockers.get(
                    "harvest_only_suppressed_by_other_gate_rows",
                    0,
                )],
                ["Event-gate suppressed rows", quote_blockers.get("event_gate_suppressed_rows", 0)],
            ],
        ))
        market_reasons = quote_blockers.get("top_market_reasons") or []
        if market_reasons:
            lines.extend(["", "### Top Market Reasons", ""])
            lines.extend(markdown_table(
                ["Market", "Reason", "Rows"],
                [
                    [row.get("market_id"), row.get("reason_code"), row.get("rows", 0)]
                    for row in market_reasons[:12]
                ],
            ))
        known_edge_rows = quote_blockers.get("top_known_edge_states") or []
        if known_edge_rows:
            lines.extend(["", "### Top Known-Edge States", ""])
            lines.extend(markdown_table(
                ["Known-edge reason", "Permission", "Promotion", "Rows"],
                [
                    [
                        row.get("known_edge_reason"),
                        row.get("known_edge_permission"),
                        row.get("promotion_state"),
                        row.get("rows", 0),
                    ]
                    for row in known_edge_rows[:12]
                ],
            ))
        event_rows = quote_blockers.get("top_event_gate_states") or []
        if event_rows:
            lines.extend(["", "### Top Event-Gate States", ""])
            lines.extend(markdown_table(
                ["Status", "Action", "Reason", "Class", "Rows"],
                [
                    [
                        row.get("event_gate_status"),
                        row.get("event_gate_action"),
                        row.get("event_gate_reason_code"),
                        row.get("event_gate_event_class"),
                        row.get("rows", 0),
                    ]
                    for row in event_rows[:12]
                ],
            ))
        blocked_cells = quote_blockers.get("top_blocked_cells") or []
        if blocked_cells:
            lines.extend(["", "### Top Blocked Cells", ""])
            lines.extend(markdown_table(
                ["Market", "Range", "Reason", "Known-edge reason", "Promotion", "Rows"],
                [
                    [
                        row.get("market_id"),
                        row.get("range_label"),
                        row.get("reason_code"),
                        row.get("known_edge_reason"),
                        row.get("promotion_state"),
                        row.get("rows", 0),
                    ]
                    for row in blocked_cells[:20]
                ],
            ))
    if model_variant:
        gate = model_variant.get("promotion_gate") or {}
        lines.extend([
            "",
            "## Model-Variant Bakeoff",
            "",
            "Counterfactual model-version rows are scored through the same conservative fill simulator as served maker quotes.",
            "",
        ])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", model_variant.get("status") or "-"],
                ["Reason", model_variant.get("reason") or "-"],
                ["Score basis", model_variant.get("score_basis") or "-"],
                ["Quote rows", model_variant.get("quote_rows", 0)],
                ["Conservative fills", model_variant.get("conservative_fills", 0)],
                ["Policy pairs", model_variant.get("policy_pair_count", 0)],
                ["Promotion gate", gate.get("status") or model_variant_summary.get("promotion_gate_status") or "-"],
                ["Promotion gate method", gate.get("method") or model_variant_summary.get("promotion_gate_method") or "-"],
                ["Promotion pass pairs", gate.get("pass_pair_count") or model_variant_summary.get("promotion_gate_pass_pair_count") or 0],
                ["Adjusted alpha", gate.get("adjusted_alpha") or "-"],
                ["Min market-day clusters", gate.get("min_market_day_clusters") or "-"],
            ],
        ))
        if gate.get("pairs"):
            lines.extend([
                "",
                "| Variant | Policy | Gate | Scope | Clusters | Days | Markets | Fills | Delta net mean | Delta net lower | Failed gates |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ])
            for row in gate.get("pairs") or []:
                delta_net = (
                    row.get("delta_vs_served_current_cluster_metrics") or {}
                ).get("net_pnl_after_fees_incentives_usdc") or {}
                lines.append(
                    f"| {row.get('model_variant_id')} | {row.get('policy_id')} | "
                    f"{row.get('status')} | {row.get('claim_scope')} | "
                    f"{row.get('cluster_count', 0)} | {row.get('independent_target_day_count', 0)} | "
                    f"{row.get('independent_market_count', 0)} | {row.get('conservative_fills', 0)} | "
                    f"{fmt_num(delta_net.get('mean'), 4)} | {fmt_num(delta_net.get('mean_lower'), 4)} | "
                    f"{', '.join(row.get('failed_gates') or []) or '-'} |"
                )
        variant_rows = model_variant.get("model_variant_by_policy") or []
        if variant_rows:
            lines.extend([
                "",
                "| Variant | Policy | Quote rows | Fills | Net P&L | Delta net vs served | Settlement P&L |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ])
            for row in variant_rows:
                lines.append(
                    f"| {row.get('model_variant_id')} | {row.get('policy_id')} | "
                    f"{row.get('quote_rows', 0)} | {row.get('conservative_fills', 0)} | "
                    f"{fmt_num(row.get('net_pnl_after_fees_incentives_usdc'), 4)} | "
                    f"{fmt_num(row.get('delta_net_pnl_vs_served_current_usdc'), 4)} | "
                    f"{fmt_num(row.get('settlement_pnl_usdc'), 4)} |"
                )
    lines.extend([
        "",
        "## Early-Hour Market-Aware Guardrail",
        "",
        "Market-aware probabilities are risk overlays only; no-market fair probabilities remain separate promotion evidence.",
        "",
    ])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Status", guardrail.get("status") or "-"],
            ["Early-hour fill rows", guardrail.get("early_hour_fill_rows", 0)],
            ["Live-forward fill rows", guardrail.get("live_forward_fill_rows", 0)],
            ["Settlement fill rows", guardrail.get("settlement_fill_rows", 0)],
            ["Early-hour base net", fmt_num(guardrail.get("early_hour_base_net_pnl_usdc"), 4)],
            ["Early-hour capped net", fmt_num(guardrail.get("early_hour_capped_net_pnl_usdc"), 4)],
            ["Early-hour market-aware net", fmt_num(guardrail.get("early_hour_market_aware_net_pnl_usdc"), 4)],
            ["Capped delta vs base", fmt_num(guardrail.get("early_hour_capped_delta_vs_base_usdc"), 4)],
            ["Market-aware delta vs base", fmt_num(guardrail.get("early_hour_market_aware_delta_vs_base_usdc"), 4)],
            ["Early-hour base loss", fmt_num(guardrail.get("early_hour_base_loss_usdc"), 4)],
            ["Early-hour capped loss", fmt_num(guardrail.get("early_hour_capped_loss_usdc"), 4)],
            ["Early-hour market-aware loss", fmt_num(guardrail.get("early_hour_market_aware_loss_usdc"), 4)],
            ["Market overlay risk-only", guardrail.get("market_overlay_is_risk_only", True)],
            ["No-market probability preserved", guardrail.get("no_market_probability_preserved", True)],
        ],
    ))
    lines.extend(["", "### Early-Hour Exposure", ""])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Quote permission rows", guardrail_exposure.get("quote_permission_rows", 0)],
            ["Early-hour quote rows", guardrail_exposure.get("early_hour_quote_rows", 0)],
            ["Active guardrail rows", guardrail_exposure.get("early_hour_active_guardrail_rows", 0)],
            ["Override rows", guardrail_exposure.get("early_hour_override_rows", 0)],
            ["Market-aware stand-down rows", guardrail_exposure.get("market_aware_standdown_rows", 0)],
            ["Early-hour base quote size", fmt_num(guardrail_exposure.get("early_hour_base_quote_size"), 4)],
            ["Early-hour capped quote size", fmt_num(guardrail_exposure.get("early_hour_capped_quote_size"), 4)],
            ["Market-aware quote size", fmt_num(guardrail_exposure.get("market_aware_guardrail_quote_size"), 4)],
        ],
    ))
    lines.extend(["", "## Queue Companion", ""])
    lines.extend(markdown_table(
        ["Status", "Legs"],
        [[key, value] for key, value in sorted((summary.get("queue_status_counts") or {}).items())],
    ))
    lines.extend(["", "## Fill Evidence Completeness", ""])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Status", fill_evidence.get("status") or "-"],
            ["Promotion grade", fill_evidence.get("promotion_grade")],
            ["Blockers", ", ".join(fill_evidence.get("blockers") or []) or "-"],
            ["Missing-size trade rows", fill_evidence.get("missing_size_trade_rows", 0)],
            ["Missing-book queue legs", fill_evidence.get("missing_book_queue_legs", 0)],
            ["Missing-trade-size queue legs", fill_evidence.get("missing_trade_size_queue_legs", 0)],
            ["Unresolved resting quotes", fill_evidence.get("unresolved_resting_quote_count", 0)],
            ["CLOB recon book rows", fill_evidence.get("clob_recon_book_rows", 0)],
            ["CLOB recon slices", fill_evidence.get("clob_recon_slice_rows", 0)],
            ["CLOB recon source", fill_evidence.get("clob_recon_coverage_source") or "-"],
        ],
    ))
    if fill_evidence.get("by_market_hour_token"):
        lines.extend([
            "",
            "| Market | Hour | Token | Quote legs | Strict fills | Missing book | Missing size | Queue fill legs | No touch | Incomplete frac |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ])
        for row in (fill_evidence.get("by_market_hour_token") or [])[:30]:
            lines.append(
                f"| {row.get('market_id')} | {row.get('hour_utc')} | {row.get('clob_token_id')} | "
                f"{row.get('quote_legs', 0)} | {row.get('strict_trade_through_fills', 0)} | "
                f"{row.get('missing_book_queue_legs', 0)} | {row.get('missing_trade_size_queue_legs', 0)} | "
                f"{row.get('queue_estimated_fill_legs', 0)} | {row.get('no_touch_queue_legs', 0)} | "
                f"{fmt_num(row.get('incomplete_market_data_leg_fraction'), 3)} |"
            )
    lines.extend(["", "## CLOB Recon", ""])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Book rows", clob_recon.get("book_rows", 0)],
            ["Recon slices", clob_recon.get("slice_rows", 0)],
            ["Mean reward qualifying size", fmt_num(clob_recon.get("mean_reward_qualifying_size"), 4)],
            ["Mean spread", fmt_num(clob_recon.get("mean_spread"), 4)],
            ["Mean 300s passive markout", fmt_num(clob_recon.get("mean_passive_markout_300s"), 4)],
            ["Policy suggestions", json.dumps(clob_recon.get("policy_parameter_suggestions") or {}, sort_keys=True)],
        ],
    ))
    lines.extend(["", "## Information Event Gate", ""])
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Suppressed rows", event_gate.get("suppressed_rows", 0)],
            ["Widen rows", event_gate.get("widen_rows", 0)],
            ["Exception rows", event_gate.get("exception_rows", 0)],
            ["Suppressed opportunity cost USDC", fmt_num(event_gate.get("suppressed_opportunity_cost_usdc"), 4)],
            ["Avoided toxicity USDC", fmt_num(event_gate.get("avoided_toxicity_usdc"), 4)],
            ["Avoided-toxicity evidence rows", event_gate.get("avoided_toxicity_evidence_rows", 0)],
            ["Exception negative-markout fills", event_gate.get("exception_negative_markout_fills", 0)],
            ["Narrowing gate", event_gate.get("narrowing_gate") or "-"],
        ],
    ))
    lines.extend(["", "## Markout Slices", ""])
    slice_rows = []
    for row in payload.get("markout_slices", [])[:40]:
        slice_rows.append([
            row.get("market_id"),
            row.get("hour_utc"),
            row.get("band_distance_bucket"),
            row.get("band_type"),
            row.get("regime"),
            row.get("source_fresh"),
            row.get("source_freshness_state"),
            row.get("book_imbalance_bucket"),
            row.get("casebook_taxonomy"),
            row.get("fill_count"),
            fmt_num(row.get("mean_markout_30m_per_share"), 4),
            fmt_num(row.get("markout_30m_ci_low"), 4),
            fmt_num(row.get("net_pnl_after_fees_incentives_usdc"), 4),
        ])
    lines.extend(markdown_table(
        [
            "Market",
            "Hour",
            "Band Distance",
            "Band Type",
            "Regime",
            "Fresh",
            "Fresh State",
            "Imbalance",
            "Taxonomy",
            "Fills",
            "Mean 30m",
            "CI Low",
            "Net",
        ],
        slice_rows,
    ))
    lines.extend([
        "",
        "## Anti-Overfit Discipline",
        "",
    ])
    lines.extend(markdown_table(
        ["Check", "Value"],
        [
            ["Frozen replay days", ", ".join(anti.get("frozen_replay_days") or []) or "-"],
            ["Held-out validation days", ", ".join(anti.get("heldout_validation_days") or []) or "-"],
            ["Live-forward days", ", ".join(anti.get("live_forward_days") or []) or "-"],
            ["Policy hashes", ", ".join(anti.get("policy_hashes") or []) or "-"],
            ["CI method", anti.get("confidence_interval_method")],
            ["Multiple-test adjustment", anti.get("multiple_test_adjustment")],
        ],
    ))
    if live_forward_evidence:
        lines.extend([
            "",
            "## Per-Market Live-Forward Evidence",
            "",
        ])
        lines.extend(markdown_table(
            [
                "Evidence Class",
                "Countable",
                "Blocked",
                "All Selected Count",
                "First Blocked Market",
                "First Gate",
                "Owner",
                "Command",
            ],
            [
                [
                    evidence_class,
                    row.get("countable_market_count"),
                    row.get("blocked_market_count"),
                    row.get("all_selected_markets_count"),
                    row.get("first_blocked_market") or "-",
                    row.get("first_blocked_gate") or "-",
                    row.get("first_blocked_owner") or "-",
                    row.get("first_blocked_command") or "-",
                ]
                for evidence_class, row in sorted(live_forward_evidence.items())
            ],
        ))
        credit_rows = payload.get("per_market_evidence_credits") or []
        blocked_rows = [row for row in credit_rows if not row.get("counts")]
        if blocked_rows:
            lines.extend(["", "### Blocked Per-Market Evidence Rows", ""])
            lines.extend(markdown_table(
                ["Market", "Class", "Gate", "Owner", "Command"],
                [
                    [
                        row.get("market_id"),
                        row.get("evidence_class"),
                        row.get("first_failing_gate") or ",".join(row.get("blocking_gates") or []) or "-",
                        row.get("owner") or "-",
                        row.get("suggested_command") or "-",
                    ]
                    for row in blocked_rows[:20]
                ],
            ))
    excluded_rows = []
    for row in payload.get("excluded_run_folders") or []:
        excluded_rows.append([
            row.get("run_id"),
            row.get("schema_version"),
            ", ".join(row.get("non_scoreable_reasons") or []) or "-",
            row.get("run_folder"),
        ])
    if excluded_rows:
        lines.extend([
            "",
            "## Excluded Runs",
            "",
            "These runs are quarantined from paper scoring and promotion decisions.",
            "",
        ])
        lines.extend(markdown_table(
            ["Run", "Schema", "Reason", "Folder"],
            excluded_rows,
        ))
    lines.extend([
        "",
        "## Evidence Gaps",
        "",
    ])
    lines.extend(markdown_table(
        ["Gap", "Value"],
        [
            ["Missing-size trade rows", evidence.get("missing_size_trade_rows")],
            ["Events without trade rows", ", ".join(evidence.get("events_without_trade_rows") or []) or "-"],
            ["Unresolved resting quote audit count", (summary.get("decisive_resting_audit") or {}).get("unresolved_resting_quote_count")],
        ],
    ))
    lines.append("")
    return "\n".join(lines)


def promotion_state_from_action(action, verdict=None):
    action = str(action or "").upper()
    verdict = str(verdict or "").upper()
    if action == "PROMOTE_CANDIDATE" or verdict == "PASS":
        return "PASS"
    if action == "BLOCK_CANDIDATE" or verdict == "BLOCK":
        return "BLOCK"
    if action == "KEEP_SHADOW" or verdict == "SHADOW":
        return "SHADOW"
    return "BLOCK"


def load_promotion_records(path):
    payload = read_json(path, {}) or {}
    records = {}
    allowlist_rows = ((payload.get("promotion_allowlist") or {}).get("markets") or [])
    decision_rows = ((payload.get("decisions") or {}).get("markets") or [])
    rows = allowlist_rows or decision_rows
    for row in rows:
        market_id = row.get("market_id")
        if not market_id:
            continue
        metrics = row.get("metrics") or {}
        if not metrics:
            metrics = {
                "candidate_brier": row.get("candidate_brier"),
                "current_brier": row.get("current_brier"),
                "market_brier": row.get("market_brier"),
                "delta_vs_market": row.get("delta_vs_market"),
            }
        action = row.get("action")
        verdict = row.get("verdict")
        records[market_id] = {
            "market_id": market_id,
            "base_permission": promotion_state_from_action(action, verdict),
            "action": action,
            "verdict": verdict,
            "reason": row.get("blocker_reason") or row.get("reason"),
            "delta_vs_market": metrics.get("delta_vs_market"),
            "candidate_brier": metrics.get("candidate_brier"),
            "market_brier": metrics.get("market_brier"),
            "candidate_days": row.get("candidate_days"),
            "settled_days_in_corpus": row.get("settled_days_in_corpus"),
            "market_evidence_ok": (finite_float(metrics.get("delta_vs_market"), 1.0) or 1.0) <= 0.0,
            "candidate_id": row.get("candidate_id") or (payload.get("promotion_allowlist") or {}).get("candidate_id"),
            "candidate_serving_allowed": row.get("candidate_serving_allowed"),
            "candidate_permission_allowed": row.get("candidate_permission_allowed"),
            "promotion_allowlist_enforced": bool(allowlist_rows),
        }
    return records, payload


def permission_for_record(base_permission, paper_slice, promotion, paper_summary, config):
    if base_permission == "BLOCK":
        return "no_quote", "promotion_block"
    if base_permission == "SHADOW":
        return "harvest_only", "promotion_shadow"
    if (paper_summary.get("exchange_economics_gate") or {}).get("status") == "BLOCK":
        return "harvest_only", "paper_stale_exchange_economics"
    if paper_summary.get("exchange_economics_gate_status") == "BLOCK":
        return "harvest_only", "paper_stale_exchange_economics"
    fill_count = int(paper_slice.get("fill_count") or 0) if paper_slice else 0
    ci_low = finite_float((paper_slice or {}).get("markout_30m_ci_low"))
    net = finite_float((paper_slice or {}).get("net_pnl_after_fees_incentives_usdc"), 0.0) or 0.0
    live_days = len((paper_summary.get("anti_overfit") or {}).get("live_forward_days") or [])
    if fill_count <= 0:
        return "harvest_only", "awaiting_paper_markouts"
    if ci_low is None or ci_low <= 0.0 or net <= 0.0:
        return "harvest_only", "paper_markout_not_positive"
    if not promotion.get("market_evidence_ok"):
        return "edge_research", "paper_positive_but_market_brier_gap_open"
    if (
        live_days >= int(config["min_edge_allowed_live_days"])
        and fill_count >= int(config["min_edge_allowed_fills"])
    ):
        return "edge_allowed", "live_forward_paper_gate_clear"
    return "edge_research", "positive_paper_needs_live_forward_days"


def _is_degraded_source_freshness_state(group):
    group = str(group or "")
    return group != "all_fresh" and any(token in group for token in ("failed", "stale", "unknown"))


def source_freshness_gap_records(promotion_payload, paper_summary):
    records = []
    slices = ((promotion_payload.get("candidate") or {}).get("slices") or {}).get("by_source_freshness") or []
    for item in slices:
        delta_vs_market = finite_float(item.get("delta_vs_market"))
        if delta_vs_market is None or delta_vs_market <= 0.0:
            continue
        group = item.get("group") or "unknown"
        if not _is_degraded_source_freshness_state(group):
            continue
        records.append({
            "market_id": "*",
            "cutoff": "*",
            "hour_utc": "*",
            "band_distance_bucket": "*",
            "band_type": "*",
            "casebook_taxonomy": "*",
            "regime": "*",
            "source_fresh": "*",
            "source_freshness_state": group,
            "book_imbalance_bucket": "*",
            "base_permission": "SOURCE_FRESHNESS_GAP",
            "permission": "harvest_only",
            "reason": "source_freshness_model_gap",
            "promotion": None,
            "paper_evidence": None,
            "source_freshness_evidence": item,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    return records


def dynamic_source_success_records(promotion_payload, paper_summary):
    records = []
    slices = ((promotion_payload.get("candidate") or {}).get("slices") or {}).get("by_source_freshness") or []
    for item in slices:
        group = item.get("group") or "unknown"
        if not _is_degraded_source_freshness_state(group):
            continue
        delta_vs_current = finite_float(item.get("delta_vs_current"))
        if delta_vs_current is None or delta_vs_current >= 0.0:
            continue
        records.append({
            "market_id": "*",
            "cutoff": "*",
            "hour_utc": "*",
            "band_distance_bucket": "*",
            "band_type": "*",
            "casebook_taxonomy": "*",
            "regime": "*",
            "source_fresh": "*",
            "source_freshness_state": group,
            "book_imbalance_bucket": "*",
            "base_permission": "DYNAMIC_SOURCE_REPLAY_CLEAR",
            "permission": "edge_research",
            "reason": "dynamic_source_state_replay_gate_clear",
            "promotion": None,
            "paper_evidence": None,
            "source_freshness_evidence": item,
            "uses_market_features": False,
            "market_informed": False,
            "weather_model_promotion_evidence": True,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    return records


def _clob_overlay_gate_has_quote_guardrails(gate):
    return all(
        gate.get(key) not in (None, "")
        for key in (
            "max_logloss_delta_vs_candidate",
            "max_ece",
            "max_overconfident_error_rate",
        )
    )


def _clob_overlay_decision_passes_quote_guardrails(decision, gate):
    if not decision.get("allowed"):
        return False
    rows = int(decision.get("rows") or 0)
    if rows < int(gate.get("min_rows") or 0):
        return False

    checks = [
        ("delta_vs_candidate", "max_delta_vs_candidate"),
        ("delta_vs_market", "max_delta_vs_market"),
        ("micro_ece", "max_ece"),
        ("micro_overconfident_error_rate", "max_overconfident_error_rate"),
    ]
    for metric_key, limit_key in checks:
        value = finite_float(decision.get(metric_key))
        limit = finite_float(gate.get(limit_key))
        if value is None or limit is None or value > limit + 1e-12:
            return False

    micro_logloss = finite_float(decision.get("micro_logloss"))
    candidate_logloss = finite_float(decision.get("candidate_logloss"))
    max_logloss_delta = finite_float(gate.get("max_logloss_delta_vs_candidate"))
    if micro_logloss is None or candidate_logloss is None or max_logloss_delta is None:
        return False
    return (micro_logloss - candidate_logloss) <= max_logloss_delta + 1e-12


def clob_overlay_gate_records(promotion_payload, paper_summary):
    records = []
    gate = (((promotion_payload.get("candidate") or {}).get("microstructure") or {}).get("gate") or {})
    diagnostics = {
        "gate_present": bool(gate),
        "quote_guardrails_present": _clob_overlay_gate_has_quote_guardrails(gate),
        "allowed_taxonomies": [],
        "blocked_taxonomies": [
            item.get("taxonomy")
            for item in gate.get("decisions") or []
            if item.get("taxonomy") and not item.get("allowed")
        ],
    }
    if not gate or not diagnostics["quote_guardrails_present"]:
        return records, diagnostics

    gate_evidence = {
        "schema_version": gate.get("schema_version"),
        "policy": gate.get("policy"),
        "min_rows": gate.get("min_rows"),
        "max_delta_vs_candidate": gate.get("max_delta_vs_candidate"),
        "max_delta_vs_market": gate.get("max_delta_vs_market"),
        "max_logloss_delta_vs_candidate": gate.get("max_logloss_delta_vs_candidate"),
        "max_ece": gate.get("max_ece"),
        "max_overconfident_error_rate": gate.get("max_overconfident_error_rate"),
        "target_taxonomies": gate.get("target_taxonomies") or [],
    }
    for item in gate.get("decisions") or []:
        taxonomy = item.get("taxonomy")
        if not taxonomy or not _clob_overlay_decision_passes_quote_guardrails(item, gate):
            continue
        diagnostics["allowed_taxonomies"].append(taxonomy)
        records.append({
            "market_id": "*",
            "cutoff": "*",
            "hour_utc": "*",
            "band_distance_bucket": "*",
            "band_type": "*",
            "casebook_taxonomy": taxonomy,
            "regime": "*",
            "source_fresh": "*",
            "source_freshness_state": "*",
            "book_imbalance_bucket": "*",
            "base_permission": "CLOB_OVERLAY_MARKET_INFORMED",
            "permission": "edge_research",
            "reason": "clob_overlay_market_informed_replay_gate_clear",
            "promotion": None,
            "paper_evidence": None,
            "clob_overlay_evidence": item,
            "clob_overlay_gate": gate_evidence,
            "uses_market_features": True,
            "market_informed": True,
            "quote_time_only": True,
            "weather_model_promotion_evidence": False,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    return records, diagnostics


def build_known_edge_map(paper_payload, promotion_refresh=DEFAULT_PROMOTION_REFRESH, config=None, now=None):
    config = {**DEFAULT_CONFIG, **(config or {})}
    promotions, promotion_payload = load_promotion_records(promotion_refresh)
    paper_summary = paper_payload.get("summary") or {}
    records = source_freshness_gap_records(promotion_payload, paper_summary)
    dynamic_source_records = dynamic_source_success_records(promotion_payload, paper_summary)
    records.extend(dynamic_source_records)
    clob_overlay_records, clob_overlay_diag = clob_overlay_gate_records(
        promotion_payload,
        paper_summary,
    )
    records.extend(clob_overlay_records)
    clob_recon_payload = paper_payload.get("clob_recon") or {}
    for item in (clob_recon_payload.get("slices") or [])[:200]:
        market_id = item.get("market_id") or "unknown"
        permission = item.get("recommended_permission") or "harvest_only"
        records.append({
            "market_id": market_id,
            "cutoff": "clob_recon",
            "hour_utc": item.get("hour_utc") or "*",
            "band_distance_bucket": "*",
            "band_type": item.get("side") or "*",
            "casebook_taxonomy": "*",
            "regime": "*",
            "source_fresh": "*",
            "source_freshness_state": "*",
            "book_imbalance_bucket": "*",
            "base_permission": "CLOB_RECON",
            "permission": permission,
            "reason": "clob_recon_" + str(item.get("permission_reason") or "measured_book"),
            "promotion": promotions.get(market_id),
            "paper_evidence": None,
            "clob_recon_evidence": item,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    seen_markets = set()
    for item in paper_payload.get("markout_slices") or []:
        market_id = item.get("market_id") or "unknown"
        promotion = promotions.get(market_id, {"base_permission": "BLOCK", "market_id": market_id})
        permission, reason = permission_for_record(
            promotion.get("base_permission", "BLOCK"),
            item,
            promotion,
            paper_summary,
            config,
        )
        seen_markets.add(market_id)
        records.append({
            "market_id": market_id,
            "cutoff": "paper_slice",
            "hour_utc": item.get("hour_utc"),
            "band_distance_bucket": item.get("band_distance_bucket"),
            "band_type": item.get("band_type"),
            "casebook_taxonomy": item.get("casebook_taxonomy"),
            "regime": item.get("regime"),
            "source_fresh": item.get("source_fresh"),
            "source_freshness_state": item.get("source_freshness_state") or "*",
            "book_imbalance_bucket": item.get("book_imbalance_bucket"),
            "base_permission": promotion.get("base_permission", "BLOCK"),
            "permission": permission,
            "reason": reason,
            "promotion": promotion,
            "paper_evidence": item,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    for market_id, promotion in sorted(promotions.items()):
        if market_id in seen_markets:
            continue
        permission, reason = permission_for_record(
            promotion.get("base_permission", "BLOCK"),
            None,
            promotion,
            paper_summary,
            config,
        )
        records.append({
            "market_id": market_id,
            "cutoff": "*",
            "hour_utc": "*",
            "band_distance_bucket": "*",
            "band_type": "*",
            "casebook_taxonomy": "*",
            "regime": "*",
            "source_fresh": "*",
            "source_freshness_state": "*",
            "book_imbalance_bucket": "*",
            "base_permission": promotion.get("base_permission", "BLOCK"),
            "permission": permission,
            "reason": reason,
            "promotion": promotion,
            "paper_evidence": None,
            "requires_policy_hash": (paper_summary.get("anti_overfit") or {}).get("policy_hashes") or [],
        })
    active_gap_cells = [
        {
            "market_id": record["market_id"],
            "reason": record["reason"],
            "base_permission": record["base_permission"],
            "permission": record["permission"],
            "delta_vs_market": (record.get("promotion") or {}).get("delta_vs_market"),
            "source_freshness_state": record.get("source_freshness_state"),
            "source_freshness_delta_vs_market": (record.get("source_freshness_evidence") or {}).get("delta_vs_market"),
            "source_freshness_delta_vs_current": (record.get("source_freshness_evidence") or {}).get("delta_vs_current"),
            "source_freshness_rows": (record.get("source_freshness_evidence") or {}).get("n"),
            "clob_overlay_taxonomy": (record.get("clob_overlay_evidence") or {}).get("taxonomy"),
            "clob_overlay_rows": (record.get("clob_overlay_evidence") or {}).get("rows"),
            "clob_overlay_delta_vs_candidate": (record.get("clob_overlay_evidence") or {}).get("delta_vs_candidate"),
            "clob_overlay_delta_vs_market": (record.get("clob_overlay_evidence") or {}).get("delta_vs_market"),
            "market_informed": record.get("market_informed", False),
            "paper_fill_count": ((record.get("paper_evidence") or {}).get("fill_count") or 0),
        }
        for record in records
        if record["permission"] != "edge_allowed"
    ]
    counts = Counter(record["permission"] for record in records)
    return {
        "schema_version": KNOWN_EDGE_SCHEMA_VERSION,
        "generated_at_utc": generated_at_iso(now),
        "promotion_refresh": str(promotion_refresh),
        "paper_report_schema_version": paper_payload.get("schema_version"),
        "exchange_economics_gate": paper_payload.get("exchange_economics_gate") or paper_summary.get("exchange_economics_gate"),
        "exchange_economics_snapshot_id": paper_summary.get("exchange_economics_snapshot_id"),
        "exchange_economics_hash": paper_summary.get("exchange_economics_hash"),
        "exchange_economics_evidence_basis": paper_summary.get("exchange_economics_evidence_basis"),
        "policy": {
            "block": "BLOCK promotion maps to no_quote.",
            "shadow": "SHADOW promotion maps to harvest_only.",
            "pass": "PASS promotion needs positive conservative paper markouts before edge_research and 14 locked live-forward days before edge_allowed.",
            "edge_allowed_disabled_when_market_gap_open": True,
            "clob_recon_consumed": bool((paper_payload.get("clob_recon") or {}).get("exists")),
            "clob_overlay_market_informed_consumed": bool(clob_overlay_records),
            "clob_overlay_records_do_not_count_as_no_market_promotion": True,
            "dynamic_source_success_cells_are_research_only": True,
            "promotion_allowlist_enforced": bool(((promotion_payload.get("promotion_allowlist") or {}).get("markets") or [])),
        },
        "summary": {
            "record_count": len(records),
            "permission_counts": dict(sorted(counts.items())),
            "active_model_gap_cell_count": len(active_gap_cells),
            "promotion_market_count": len(promotions),
            "paper_fill_count": paper_summary.get("conservative_fills", 0),
            "exchange_economics_gate_status": paper_summary.get("exchange_economics_gate_status"),
            "exchange_economics_snapshot_id": paper_summary.get("exchange_economics_snapshot_id"),
            "clob_overlay_quote_guardrails_present": clob_overlay_diag.get("quote_guardrails_present", False),
            "clob_overlay_allowed_taxonomy_count": len(clob_overlay_diag.get("allowed_taxonomies") or []),
            "clob_overlay_blocked_taxonomy_count": len(clob_overlay_diag.get("blocked_taxonomies") or []),
            "clob_overlay_allowed_taxonomies": clob_overlay_diag.get("allowed_taxonomies") or [],
            "clob_overlay_blocked_taxonomies": clob_overlay_diag.get("blocked_taxonomies") or [],
            "dynamic_source_success_cell_count": len(dynamic_source_records),
            "clob_recon_slice_count": ((paper_payload.get("clob_recon") or {}).get("summary") or {}).get("slice_rows", 0),
        },
        "records": records,
        "active_model_gap_cells": active_gap_cells,
        "clob_overlay_summary": clob_overlay_diag,
        "promotion_summary": {
            "verdict": ((promotion_payload.get("decisions") or {}).get("verdict")),
            "action_counts": ((promotion_payload.get("decisions") or {}).get("action_counts")),
        },
    }


def render_known_edge_report(payload):
    lines = [
        "# Market-Making Known Edge Map",
        "",
        f"Generated: {payload['generated_at_utc']}",
        "",
        "## Summary",
        "",
    ]
    summary = payload.get("summary") or {}
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Records", summary.get("record_count")],
            ["Promotion markets", summary.get("promotion_market_count")],
            ["Paper fills", summary.get("paper_fill_count")],
            ["Active model-gap cells", summary.get("active_model_gap_cell_count")],
        ],
    ))
    lines.extend(["", "## Permissions", ""])
    lines.extend(markdown_table(
        ["Permission", "Records"],
        [[key, value] for key, value in sorted((summary.get("permission_counts") or {}).items())],
    ))
    source_rows = []
    for record in payload.get("records") or []:
        evidence = record.get("source_freshness_evidence") or {}
        if not evidence:
            continue
        source_rows.append([
            record.get("source_freshness_state"),
            evidence.get("n"),
            fmt_num(evidence.get("candidate_brier"), 4),
            fmt_num(evidence.get("market_brier"), 4),
            fmt_num(evidence.get("delta_vs_current"), 4),
            fmt_num(evidence.get("delta_vs_market"), 4),
            record.get("permission"),
            record.get("reason"),
        ])
    if source_rows:
        lines.extend(["", "## Source Freshness Replay Cells", ""])
        lines.extend(markdown_table(
            [
                "Freshness State",
                "Rows",
                "Candidate Brier",
                "Market Brier",
                "Delta Current",
                "Delta Market",
                "Permission",
                "Reason",
            ],
            source_rows,
        ))
    clob_overlay_rows = []
    for record in payload.get("records") or []:
        evidence = record.get("clob_overlay_evidence") or {}
        if not evidence:
            continue
        clob_overlay_rows.append([
            evidence.get("taxonomy"),
            evidence.get("rows"),
            fmt_num(evidence.get("micro_brier"), 4),
            fmt_num(evidence.get("candidate_brier"), 4),
            fmt_num(evidence.get("market_brier"), 4),
            fmt_num(evidence.get("delta_vs_candidate"), 4),
            fmt_num(evidence.get("delta_vs_market"), 4),
            fmt_num(evidence.get("micro_ece"), 4),
            fmt_num(evidence.get("micro_logloss"), 4),
            record.get("permission"),
            record.get("reason"),
        ])
    if clob_overlay_rows:
        lines.extend(["", "## CLOB Overlay Quote Permissions", ""])
        lines.extend(markdown_table(
            [
                "Taxonomy",
                "Rows",
                "Overlay Brier",
                "Candidate Brier",
                "Market Brier",
                "Delta Candidate",
                "Delta Market",
                "ECE",
                "Log Loss",
                "Permission",
                "Reason",
            ],
            clob_overlay_rows,
        ))
    lines.extend(["", "## Records", ""])
    rows = []
    for record in (payload.get("records") or [])[:80]:
        rows.append([
            record.get("market_id"),
            record.get("hour_utc"),
            record.get("band_distance_bucket"),
            record.get("band_type"),
            record.get("casebook_taxonomy"),
            record.get("regime"),
            record.get("source_fresh"),
            record.get("source_freshness_state"),
            record.get("base_permission"),
            record.get("permission"),
            record.get("reason"),
            ((record.get("paper_evidence") or {}).get("fill_count") or 0),
        ])
    lines.extend(markdown_table(
        [
            "Market",
            "Hour",
            "Band Distance",
            "Band Type",
            "Taxonomy",
            "Regime",
            "Fresh",
            "Fresh State",
            "Base",
            "Permission",
            "Reason",
            "Fills",
        ],
        rows,
    ))
    lines.append("")
    return "\n".join(lines)
