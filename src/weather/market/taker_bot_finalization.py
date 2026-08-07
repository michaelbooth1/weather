"""Implementation slice extracted from src/weather/market/taker_bot.py."""

import gc
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from weather.market.taker_bot_bakeoff import *  # noqa: F403
from weather.market.taker_bot_aggregation import (
    DeferredTakerPayload,
    TakerRunAggregation,
)
from weather.market.taker_bot_artifact_projection import (
    DEFAULT_PROJECTION_MAX_BYTES,
    load_bakeoff_ledger_projection,
    load_settled_finalization_projection,
    write_settled_finalization_projection,
)
from weather.market.worker_release_binding import worker_tape_columns_from_rows
from weather.io import (
    read_pretty_json_top_level_values,
    write_csv_rows_atomic,
    write_text_atomic,
)
from weather.operations.bot_run_liveness import DEFAULT_MIN_FREE_BYTES, disk_capacity_preflight

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

DEFAULT_FINALIZATION_SLA_HOURS = 4.0
DEFAULT_FINALIZATION_RETENTION_DAYS = 14
DEFAULT_RETENTION_CANDIDATE_MIN_BYTES = 100_000_000
DEFAULT_STREAMING_SCORE_BATCH_ROWS = 512


def write_settled_worker_tape(path, base_columns, rows):
    """Write a settled projection without dropping verified worker lineage."""

    if not isinstance(rows, (list, tuple)) and not getattr(rows, "is_spilled_rows", False):
        rows = list(rows)
    columns = worker_tape_columns_from_rows(base_columns, rows)
    return write_csv_rows_atomic(path, columns, rows)


def _stream_score_order_tape(
    path,
    labels,
    target_rows,
    exchange_fields,
    *,
    counterfactual=False,
    batch_rows=DEFAULT_STREAMING_SCORE_BATCH_ROWS,
):
    """Score a tape in fixed batches and spill rows in original source order."""

    batch_rows = max(1, int(batch_rows))
    batch = []
    matched = 0
    unmatched = 0

    def flush():
        nonlocal matched, unmatched
        if not batch:
            return
        scored, score_summary = score_orders_against_labels(batch, labels)
        _annotate_rows_with_exchange_fields(scored, exchange_fields)
        if counterfactual:
            for row in scored:
                row["counterfactual_pnl_source"] = (
                    row.get("pnl_source")
                    or row.get("counterfactual_pnl_source")
                    or ""
                )
        target_rows.extend(scored)
        matched += int(score_summary.get("matched_filled_orders") or 0)
        unmatched += int(score_summary.get("unmatched_filled_orders") or 0)
        batch.clear()

    for row in iter_order_rows(path):
        batch.append(row)
        if len(batch) >= batch_rows:
            flush()
    flush()
    target_rows.connection.commit()
    return {
        "matched_filled_orders": matched,
        "unmatched_filled_orders": unmatched,
        "label_count": len(labels.get("by_event_slug", {})),
    }


def _bounded_bakeoff_gate_payload(path):
    """Load the compact bakeoff projection, with a small-artifact fallback."""

    path = Path(path)
    projection = load_bakeoff_ledger_projection(
        path,
        expected_bakeoff_schema_version=STRATEGY_BAKEOFF_SCHEMA_VERSION,
    )
    if projection is not None:
        return projection
    try:
        if path.stat().st_size > DEFAULT_PROJECTION_MAX_BYTES:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def _read_small_artifact_json(path):
    """Read only JSON artifacts whose encoded size has a fixed upper bound."""

    path = Path(path)
    try:
        if path.stat().st_size > DEFAULT_PROJECTION_MAX_BYTES:
            return {}
    except OSError:
        return {}
    return read_json(path, {}) or {}


def _read_taker_summary_artifact(path):
    """Read only finalization metadata from a potentially huge run artifact."""

    path = Path(path)
    try:
        stat = path.stat()
    except OSError:
        return {}
    if stat.st_size <= DEFAULT_PROJECTION_MAX_BYTES:
        return read_json(path, {}) or {}
    return _read_large_taker_summary_artifact(
        str(path),
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )


@lru_cache(maxsize=128)
def _read_large_taker_summary_artifact(path, _size_bytes, _mtime_ns):
    return read_pretty_json_top_level_values(
        Path(path),
        ("budget_usdc", "run_id", "summary", "target_date"),
    )


def _exchange_fields_from_run_config(run_config):
    gate = (run_config or {}).get("exchange_economics_gate") or {}
    fields = exchange_economics.exchange_economics_artifact_fields(gate)
    if not fields.get("exchange_economics_snapshot_id"):
        fields = {
            key: (run_config or {}).get(key)
            for key in fields
        }
    return gate, fields


def _exchange_fields_for_finalization(
    run_config,
    target_date=None,
    now=None,
    *,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    if exchange_economics_snapshot_path is None and exchange_economics_required is None:
        return _exchange_fields_from_run_config(run_config)
    required = bool(exchange_economics_required) if exchange_economics_required is not None else True
    gate = exchange_economics.load_exchange_economics_gate(
        exchange_economics_snapshot_path or exchange_economics.DEFAULT_SNAPSHOT,
        target_date,
        platform=exchange_economics_platform,
        now=now,
        required=required,
    )
    return gate, exchange_economics.exchange_economics_artifact_fields(gate)


def _run_config_with_exchange_fields(run_config, exchange_gate, exchange_fields):
    return {
        **(run_config or {}),
        "exchange_economics_gate": exchange_gate or {},
        **(exchange_fields or {}),
    }


def _annotate_rows_with_exchange_fields(rows, fields):
    for row in rows or []:
        row.update({
            "exchange_economics_snapshot_id": fields.get("exchange_economics_snapshot_id"),
            "exchange_economics_hash": fields.get("exchange_economics_hash"),
            "exchange_economics_evidence_basis": fields.get("exchange_economics_evidence_basis"),
        })
    return rows


def _annotate_pnl_with_exchange_fields(pnl_payload, gate, fields):
    pnl_payload = pnl_payload or {}
    pnl_payload["exchange_economics_gate"] = gate
    pnl_payload.update(fields)
    pnl_payload.setdefault("summary", {}).update({
        "exchange_economics_gate_status": gate.get("status") or (fields.get("exchange_economics_status")),
        "exchange_economics_gate_reason": gate.get("reason"),
        **fields,
    })
    for row in pnl_payload.get("by_strategy") or []:
        row.update({
            "exchange_economics_gate_status": gate.get("status") or fields.get("exchange_economics_status"),
            **fields,
        })
    return pnl_payload


def first_numeric(*values, default=None):
    for value in values:
        number = maybe_float(value)
        if number is not None:
            return number
    return default


def first_int(*values, default=0):
    number = first_numeric(*values, default=None)
    return int(number) if number is not None else int(default)


def reported_taker_pnl_summary(run_summary=None, daily_pnl=None):
    run_summary = run_summary or {}
    daily_pnl = daily_pnl or {}
    summary = run_summary.get("summary") or {}
    run_pnl = (run_summary.get("pnl") or {}).get("summary") or {}
    daily_summary = daily_pnl.get("summary") or {}
    return {
        "reported_filled_order_count": first_int(
            summary.get("cumulative_filled_orders"),
            run_pnl.get("filled_order_count"),
            daily_summary.get("filled_order_count"),
        ),
        "reported_unsettled_order_count": first_int(
            run_pnl.get("unsettled_order_count"),
            daily_summary.get("unsettled_order_count"),
        ),
        "reported_settled_order_count": first_int(
            run_pnl.get("settled_order_count"),
            daily_summary.get("settled_order_count"),
        ),
        "reported_net_pnl_usdc": first_numeric(
            summary.get("cumulative_net_pnl_usdc"),
            run_pnl.get("net_pnl_usdc"),
            daily_summary.get("net_pnl_usdc"),
        ),
        "reported_mark_to_market_pnl_usdc": first_numeric(
            run_pnl.get("mark_to_market_pnl_usdc"),
            daily_summary.get("mark_to_market_pnl_usdc"),
        ),
        "reported_settlement_pnl_usdc": first_numeric(
            run_pnl.get("settlement_pnl_usdc"),
            daily_summary.get("settlement_pnl_usdc"),
        ),
    }


def reconciliation_warning(code, detail, **values):
    out = {"code": code, "detail": detail}
    for key, value in values.items():
        if isinstance(value, float):
            out[key] = compact_float(value)
        else:
            out[key] = value
    return out


def build_settlement_reconciliation(final_summary, reported_summary, threshold_usdc=RECONCILIATION_WARNING_USDC):
    final_summary = final_summary or {}
    reported_summary = reported_summary or {}
    settled_orders = int(final_summary.get("settled_order_count") or 0)
    unsettled_orders = int(final_summary.get("unsettled_order_count") or 0)
    final_net = first_numeric(final_summary.get("net_pnl_usdc"), default=0.0)
    final_settlement = first_numeric(final_summary.get("settlement_pnl_usdc"), default=0.0)
    reported_net = first_numeric(reported_summary.get("reported_net_pnl_usdc"), default=None)
    reported_mtm = first_numeric(reported_summary.get("reported_mark_to_market_pnl_usdc"), default=None)
    reported_unsettled = int(reported_summary.get("reported_unsettled_order_count") or 0)
    gross_cost = first_numeric(final_summary.get("gross_cost_usdc"), default=0.0)
    warnings = []

    if settled_orders > 0 and reported_unsettled > 0:
        warnings.append(reconciliation_warning(
            "reported_unsettled_after_labels_available",
            "Run summary still treated filled orders as unsettled after finalized labels were available.",
            reported_unsettled_order_count=reported_unsettled,
            finalized_settled_order_count=settled_orders,
        ))
    if settled_orders > 0 and reported_mtm is not None:
        diff_mtm = final_net - reported_mtm
        if abs(diff_mtm) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "reported_mark_to_market_diverges_from_settlement",
                "Reported mark-to-market P&L differs materially from settlement-finalized P&L.",
                difference_usdc=diff_mtm,
                reported_mark_to_market_pnl_usdc=reported_mtm,
                finalized_net_pnl_usdc=final_net,
            ))
        if gross_cost > 0 and abs(reported_mtm) > max(threshold_usdc, gross_cost * 2.0):
            warnings.append(reconciliation_warning(
                "resolved_mark_to_market_outlier",
                "Resolved-day mark-to-market was too large relative to filled cost; treat it as stale CLOB mark evidence.",
                reported_mark_to_market_pnl_usdc=reported_mtm,
                finalized_gross_cost_usdc=gross_cost,
            ))
        if final_settlement != 0 and reported_mtm * final_settlement < 0 and abs(diff_mtm) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "resolved_mark_to_market_sign_flip",
                "Reported mark-to-market and settlement-finalized P&L have opposite signs.",
                reported_mark_to_market_pnl_usdc=reported_mtm,
                settlement_pnl_usdc=final_settlement,
            ))
    if settled_orders > 0 and reported_net is not None:
        diff_net = final_net - reported_net
        if abs(diff_net) > threshold_usdc:
            warnings.append(reconciliation_warning(
                "reported_net_pnl_diverges_from_settlement",
                "Reported net P&L differs materially from settlement-finalized P&L.",
                difference_usdc=diff_net,
                reported_net_pnl_usdc=reported_net,
                finalized_net_pnl_usdc=final_net,
            ))

    if settled_orders > 0 and unsettled_orders == 0:
        preferred = "settlement_finalization"
    elif settled_orders > 0:
        preferred = "mixed_settlement_and_unscored"
    elif reported_mtm is not None:
        preferred = "mark_to_market"
    else:
        preferred = "unscored"
    return {
        "status": "WARN" if warnings else "PASS",
        "preferred_pnl_source": preferred,
        "large_difference_threshold_usdc": threshold_usdc,
        "reported": reported_summary,
        "finalized": {
            "settled_order_count": settled_orders,
            "unsettled_order_count": unsettled_orders,
            "net_pnl_usdc": compact_float(final_net),
            "settlement_pnl_usdc": compact_float(final_settlement),
        },
        "differences": {
            "net_minus_reported_net_usdc": (
                compact_float(final_net - reported_net) if reported_net is not None else None
            ),
            "net_minus_reported_mark_to_market_usdc": (
                compact_float(final_net - reported_mtm) if reported_mtm is not None else None
            ),
        },
        "warnings": warnings,
    }


def render_settlement_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    pnl_summary = pnl.get("summary") or {}
    reconciliation = payload.get("reconciliation") or {}
    warnings = reconciliation.get("warnings") or []
    lines = [
        "# Taker Settlement Finalization Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Source run folder: `{payload.get('run_folder')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Filled orders", pnl_summary.get("filled_order_count")],
            ["Settled / unsettled", f"{pnl_summary.get('settled_order_count')} / {pnl_summary.get('unsettled_order_count')}"],
            ["P&L source", summary.get("pnl_source")],
            ["Reconciliation status", reconciliation.get("status")],
            ["Next-run policy status", (payload.get("next_run_policy_gate") or {}).get("status")],
            ["Warnings", len(warnings)],
            ["Labels CSV", payload.get("labels_csv")],
        ],
    ))
    counterfactual = payload.get("counterfactual") or {}
    counterfactual_summary = counterfactual.get("summary") or {}
    if counterfactual:
        lines.extend(["", "## Counterfactual Learning", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", counterfactual.get("status")],
                ["Rows", counterfactual_summary.get("row_count")],
                ["Would-buy rows", counterfactual_summary.get("would_buy_count")],
                ["Settled would-buy rows", counterfactual_summary.get("settled_would_buy_count")],
                ["Zero-real-fill learning", str(counterfactual_summary.get("zero_real_fill_learning")).lower()],
                ["Best strategy", counterfactual_summary.get("best_counterfactual_strategy_id") or "-"],
                ["Report", counterfactual.get("settled_counterfactual_report_path") or "-"],
            ],
        ))
        no_side_campaign = counterfactual.get("no_side_campaign") or {}
        if no_side_campaign:
            lines.extend(["", "## NO-Side Counterfactual Evidence", ""])
            lines.extend(markdown_table(
                ["Metric", "Value"],
                [
                    ["Status", no_side_campaign.get("status")],
                    ["NO-side rows", no_side_campaign.get("no_side_row_count")],
                    ["Real NO-book rows", no_side_campaign.get("real_no_book_row_count")],
                    ["Synthetic NO-book rows", no_side_campaign.get("synthetic_no_book_row_count")],
                    ["Stale NO-book rows", no_side_campaign.get("stale_no_book_row_count")],
                    ["NO-side would-buy rows", no_side_campaign.get("no_side_would_buy_count")],
                    ["Countable would-buy rows", no_side_campaign.get("countable_no_side_would_buy_count")],
                    ["Settled countable would-buy rows", no_side_campaign.get("settled_countable_no_side_would_buy_count")],
                    ["Countable NO-side net P&L", fmt_num(no_side_campaign.get("countable_no_side_net_pnl_usdc"), 4)],
                    ["Delta vs no-trade", fmt_num(no_side_campaign.get("delta_vs_no_trade_net_pnl_usdc"), 4)],
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
            ["Executable net P&L", fmt_num(pnl_summary.get("executable_net_pnl_usdc"), 4)],
            ["Finalized net P&L", fmt_num(pnl_summary.get("net_pnl_usdc"), 4)],
            ["Reported net P&L", fmt_num(summary.get("reported_net_pnl_usdc"), 4)],
            ["Reported mark-to-market P&L", fmt_num(summary.get("reported_mark_to_market_pnl_usdc"), 4)],
        ],
    ))
    lines.extend(["", "## Reconciliation", ""])
    lines.extend(markdown_table(
        ["Check", "Value"],
        [
            ["Status", reconciliation.get("status")],
            ["Net minus reported net", fmt_num((reconciliation.get("differences") or {}).get("net_minus_reported_net_usdc"), 4)],
            [
                "Net minus reported MTM",
                fmt_num((reconciliation.get("differences") or {}).get("net_minus_reported_mark_to_market_usdc"), 4),
            ],
        ],
    ))
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(markdown_table(
            ["Code", "Detail"],
            [[row.get("code"), row.get("detail")] for row in warnings],
        ))
    next_gate = payload.get("next_run_policy_gate") or {}
    if next_gate:
        lines.extend(["", "## Next-Run Policy Gate", ""])
        lines.extend(markdown_table(
            ["Field", "Value"],
            [
                ["Status", next_gate.get("status")],
                ["Active strategy", next_gate.get("active_strategy_id")],
                ["Lifecycle", next_gate.get("active_strategy_lifecycle")],
                ["Lifecycle status", next_gate.get("active_strategy_lifecycle_status")],
                ["Paper-only", next_gate.get("paper_only")],
                ["Paper-only reason", next_gate.get("paper_only_reason") or "-"],
                ["Requalification required", next_gate.get("requalification_required")],
                ["Requalification route", next_gate.get("requalification_route") or "-"],
                ["Operator review required", next_gate.get("operator_review_required")],
                ["Operator review status", next_gate.get("operator_review_status") or "-"],
                ["Operator review reason", next_gate.get("operator_review_reason") or "-"],
                ["Demotion code", next_gate.get("demotion_code") or "-"],
                ["After-fee required", next_gate.get("canary_after_fee_required")],
                ["After-fee evidence", next_gate.get("canary_after_fee_evidence")],
                ["Recommended strategy", next_gate.get("recommended_strategy_id") or "-"],
                ["Complete-label sample", next_gate.get("complete_label_sample_count")],
                ["Canary settled orders", next_gate.get("canary_settled_order_count")],
                ["Next action", next_gate.get("next_action")],
                ["Reason", next_gate.get("reason")],
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
    if pnl.get("by_strategy"):
        lines.extend(["", "## Strategies", ""])
        lines.extend(markdown_table(
            ["Strategy", "Filled", "Settled", "Unsettled", "Spent", "Settlement P&L", "Net P&L", "Countable"],
            [
                [
                    row.get("strategy_id"),
                    row.get("filled_order_count"),
                    row.get("settled_order_count"),
                    row.get("unsettled_order_count"),
                    fmt_num(row.get("spent_usdc"), 2),
                    fmt_num(row.get("settlement_pnl_usdc"), 4),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    str(row.get("quality_candidate_countable")).lower(),
                ]
                for row in pnl.get("by_strategy") or []
            ],
        ))
    lines.append("")
    return "\n".join(lines)


def _blocker_codes(bakeoff):
    return {row.get("code") for row in (bakeoff or {}).get("blockers") or [] if row.get("code")}


def _gate_by_strategy(bakeoff):
    return {
        row.get("strategy_id"): row
        for row in (bakeoff or {}).get("promotion_gates") or []
        if row.get("strategy_id")
    }


def _after_fee_pnl_evidence(active_gate):
    gate = active_gate or {}
    basis = str(
        gate.get("pnl_fee_basis")
        or gate.get("net_pnl_fee_basis")
        or gate.get("after_fee_pnl_basis")
        or ""
    ).strip().lower()
    return (
        bool_value(gate.get("after_fee_pnl_scored"), False)
        or basis in {"after_fee", "fees_included", "net_after_fee"}
    )


def _operator_review_decision(run_config, strategy_id, action="promote_default", required=True):
    review = (
        (run_config or {}).get("operator_review")
        or (run_config or {}).get("live_size_operator_review")
        or {}
    )
    if not required:
        return {
            "operator_review_required": False,
            "operator_review_status": "NOT_REQUIRED",
            "operator_review_approved": True,
            "operator_review_reason": "operator review is not required by policy",
        }
    status = str(review.get("status") or review.get("decision") or "").strip().upper()
    approved = status in {"APPROVED", "PASS", "ACCEPTED"}
    approved_strategy = (
        review.get("approved_strategy_id")
        or review.get("strategy_id")
        or review.get("active_strategy_id")
        or ""
    )
    approved_action = (
        review.get("approved_action")
        or review.get("action")
        or review.get("change_type")
        or ""
    )
    if not approved:
        reason = "missing_operator_review" if not status else "operator_review_not_approved"
    elif approved_strategy and approved_strategy != strategy_id:
        approved = False
        reason = "operator_review_strategy_mismatch"
    elif approved_action and approved_action not in {action, "live_size_change", "increase_live_size", "enable_live"}:
        approved = False
        reason = "operator_review_action_mismatch"
    elif not approved_action:
        approved = False
        reason = "operator_review_action_missing"
    else:
        reason = "operator_review_approved"
    return {
        "operator_review_required": True,
        "operator_review_status": status or "MISSING",
        "operator_review_approved": bool(approved),
        "operator_review_reason": reason,
        "operator_review_strategy_id": approved_strategy,
        "operator_review_action": approved_action,
        "operator_review_reviewer": review.get("reviewer") or review.get("operator") or "",
        "operator_reviewed_at_utc": review.get("reviewed_at_utc") or review.get("approved_at_utc") or "",
    }


def _canary_gate_status(active_id, active_gate, bakeoff, run_config, strategy_row=None, strategy_comparison=None):
    label_summary = (bakeoff or {}).get("label_summary") or {}
    blockers = _blocker_codes(bakeoff)
    policy = run_config.get("policy_config") or {}
    canary = run_config.get("active_strategy_canary") or {}
    strategy_row = strategy_row or {}
    strategy_comparison = strategy_comparison or {}
    min_settled = int(
        policy.get("canary_min_settled_orders")
        or canary.get("min_settled_orders")
        or DEFAULT_CANARY_MIN_SETTLED_ORDERS
    )
    min_complete = int(
        policy.get("canary_min_complete_label_days")
        or canary.get("min_complete_label_days")
        or DEFAULT_CANARY_MIN_COMPLETE_LABEL_DAYS
    )
    total_labels = int(label_summary.get("label_rows") or 0)
    complete_labels = int(label_summary.get("complete_rows") or 0)
    active_settled = int((active_gate or {}).get("settled_order_count") or 0)
    active_unsettled = int((active_gate or {}).get("unsettled_order_count") or 0)
    active_unscored = int((active_gate or {}).get("unscored_order_count") or 0)
    failed_gates = list((active_gate or {}).get("failed_gates") or [])
    failed_gate_set = set(failed_gates)
    max_tail_fraction = maybe_float(policy.get("promotion_max_tail_fill_fraction"))
    if max_tail_fraction is None:
        max_tail_fraction = DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION
    tail_fraction = maybe_float((active_gate or {}).get("low_price_tail_fill_fraction")) or 0.0
    tail_summary = strategy_row.get("tail_fill_quality_summary") or {}
    tail_status = str(
        (active_gate or {}).get("tail_fill_quality_status")
        or tail_summary.get("status")
        or strategy_row.get("tail_fill_quality_status")
        or ""
    ).strip()
    strategy_quality_status = str(
        strategy_comparison.get("countable_strategy_quality_candidate_status") or ""
    ).strip()
    age_days = int(canary.get("age_days") or 0)
    missing_settlement_block_age = int(policy.get("canary_missing_settlement_blocks_after_age_days") or 1)
    hard_reasons = []
    if active_unsettled + active_unscored > 0 or "no_unresolved_orders" in failed_gate_set:
        hard_reasons.append("unresolved_or_unscored_orders")
    if tail_fraction > float(max_tail_fraction) or "max_tail_fill_fraction" in failed_gate_set:
        hard_reasons.append("excessive_low_tail_fraction")
    if failed_gate_set & {"non_negative_settled_roi", "no_resolved_stale_mark_sign_flips"}:
        hard_reasons.extend(sorted(failed_gate_set & {"non_negative_settled_roi", "no_resolved_stale_mark_sign_flips"}))
    high_tail_missing_settlement = (
        age_days >= missing_settlement_block_age
        and
        (
            tail_status == "WARN_HIGH_TAIL_SHARE"
            or tail_fraction > float(max_tail_fraction)
            or "max_tail_fill_fraction" in failed_gate_set
        )
        and (
            active_settled == 0
            or "min_settled_sample" in failed_gate_set
            or strategy_quality_status == "MISSING_SETTLED_SAMPLE"
        )
    )
    complete_label_gate = bool(
        total_labels > 0
        and complete_labels >= total_labels
        and complete_labels >= min_complete
        and "partial_target_date_labels" not in blockers
        and "missing_target_date_labels" not in blockers
        and "unmatched_filled_orders" not in blockers
    )
    sample_gate = active_settled >= min_settled
    if not bakeoff:
        if age_days >= missing_settlement_block_age:
            return {
                "status": "BLOCK",
                "active_strategy_lifecycle_status": "blocked",
                "promotion_eligible": False,
                "next_action": "rollback_or_block_canary",
                "paper_only": True,
                "requalification_required": True,
                "reason": "active canary has no settlement-scored bakeoff after canary cutover",
            }
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_collect_complete_labels",
            "paper_only": True,
            "requalification_required": True,
            "reason": "active canary has no settlement-scored bakeoff yet",
        }
    if high_tail_missing_settlement:
        return {
            "status": "BLOCK",
            "active_strategy_lifecycle_status": "blocked",
            "promotion_eligible": False,
            "next_action": "route_to_post_fix_requalification_campaign",
            "paper_only": True,
            "paper_only_reason": "warn_high_tail_share_missing_settled_sample",
            "requalification_required": True,
            "requalification_route": "post_fix_taker_campaign",
            "demotion_code": "WARN_HIGH_TAIL_SHARE_MISSING_SETTLED_SAMPLE",
            "reason": (
                "active canary demoted: WARN_HIGH_TAIL_SHARE with MISSING_SETTLED_SAMPLE; "
                "requires settled after-fee requalification and acceptable tail exposure"
            ),
        }
    if hard_reasons and age_days >= missing_settlement_block_age:
        return {
            "status": "BLOCK",
            "active_strategy_lifecycle_status": "blocked",
            "promotion_eligible": False,
            "next_action": "rollback_or_block_canary",
            "paper_only": True,
            "paper_only_reason": "hard_demotion_gate",
            "requalification_required": True,
            "reason": "active canary violated demotion gates: " + ", ".join(dict.fromkeys(hard_reasons)),
        }
    if active_settled == 0 and age_days >= missing_settlement_block_age:
        return {
            "status": "BLOCK",
            "active_strategy_lifecycle_status": "blocked",
            "promotion_eligible": False,
            "next_action": "rollback_or_block_canary",
            "paper_only": True,
            "paper_only_reason": "missing_settlement_scored_evidence",
            "requalification_required": True,
            "reason": "active canary has no settlement-scored evidence after canary cutover",
        }
    if not complete_label_gate:
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_until_complete_labels",
            "paper_only": True,
            "requalification_required": True,
            "reason": "active canary has only partial or missing complete-label bakeoff evidence",
        }
    if not sample_gate:
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_until_minimum_sample",
            "paper_only": True,
            "requalification_required": True,
            "reason": (
                f"active canary has {active_settled} settled orders; "
                f"{min_settled} required before promotion"
            ),
        }
    if (active_gate or {}).get("status") == "PASS":
        if bool_value(policy.get("canary_require_after_fee_pnl"), True) and not _after_fee_pnl_evidence(active_gate):
            return {
                "status": "PASS",
                "active_strategy_lifecycle_status": "candidate_canary",
                "promotion_eligible": False,
                "next_action": "continue_canary_until_after_fee_scoring",
                "paper_only": True,
                "requalification_required": True,
                "reason": "active canary passed settlement gates but lacks after-fee PnL evidence",
            }
        operator_review = _operator_review_decision(
            run_config,
            active_id,
            action="promote_default",
            required=bool_value(
                policy.get("canary_require_operator_review_before_live_size_change"),
                True,
            ),
        )
        if not operator_review.get("operator_review_approved"):
            return {
                "status": "PASS",
                "active_strategy_lifecycle_status": "candidate_canary",
                "promotion_eligible": False,
                "next_action": "operator_review_live_size_change",
                "paper_only": True,
                "paper_only_reason": "operator_review_required",
                "requalification_required": False,
                "reason": "active canary passed settlement gates but needs explicit operator review before live-size change",
                **operator_review,
            }
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "promoted_default",
            "promotion_eligible": True,
            "next_action": "promote_default",
            "paper_only": False,
            "requalification_required": False,
            "reason": "active canary has complete-label sample and passed settlement gates",
            **operator_review,
        }
    return {
        "status": "BLOCK",
        "active_strategy_lifecycle_status": "blocked",
        "promotion_eligible": False,
        "next_action": "rollback_or_block_canary",
        "paper_only": True,
        "requalification_required": True,
        "reason": "active canary failed complete-label settlement gates: " + (", ".join(failed_gates) or "unknown"),
    }


def next_run_policy_gate(strategy_summary, run_config=None, bakeoff=None):
    run_config = run_config or {}
    strategy_summary = strategy_summary or {}
    bakeoff = bakeoff or {}
    strategy_ids = run_config.get("strategy_ids") or []
    active_id = run_config.get("active_strategy_id") or (strategy_ids[0] if len(strategy_ids) == 1 else None)
    comparison = strategy_summary.get("comparison") or {}
    strategies = {
        row.get("strategy_id"): row
        for row in (strategy_summary.get("strategies") or [])
        if row.get("strategy_id")
    }
    bakeoff_pnl = {
        row.get("strategy_id"): row
        for row in ((bakeoff.get("pnl") or {}).get("by_strategy") or [])
        if row.get("strategy_id")
    }
    pass_ids = {
        row.get("strategy_id")
        for row in (bakeoff.get("promotion_gates") or [])
        if row.get("status") == "PASS" and row.get("strategy_id")
    }
    gates_by_strategy = _gate_by_strategy(bakeoff)
    recommended_id = None
    if pass_ids:
        recommended = max(
            (bakeoff_pnl.get(strategy_id, {"strategy_id": strategy_id}) for strategy_id in pass_ids),
            key=lambda row: maybe_float(row.get("net_pnl_usdc")) or 0.0,
            default=None,
        )
        recommended_id = (recommended or {}).get("strategy_id")
    elif comparison.get("best_settlement_scored_strategy_id"):
        recommended_id = comparison.get("best_settlement_scored_strategy_id")
    active_row = bakeoff_pnl.get(active_id) or strategies.get(active_id) or {}
    active_net = maybe_float(active_row.get("net_pnl_usdc"))
    recommended_row = bakeoff_pnl.get(recommended_id) or strategies.get(recommended_id) or {}
    recommended_net = maybe_float(recommended_row.get("net_pnl_usdc"))
    active_lifecycle = (
        run_config.get("active_strategy_lifecycle")
        or active_strategy_lifecycle_for_spec((run_config.get("strategies") or [{}])[0], run_config.get("policy_config") or {})
    )
    exchange_gate = (run_config.get("exchange_economics_gate") or bakeoff.get("exchange_economics_gate") or {})
    exchange_fields = exchange_economics.exchange_economics_artifact_fields(exchange_gate)
    exchange_blocks = bool(exchange_gate.get("status") == "BLOCK" or exchange_gate.get("ok") is False)
    canary_decision = None
    if active_lifecycle == "candidate_canary":
        canary_decision = _canary_gate_status(
            active_id,
            gates_by_strategy.get(active_id) or {},
            bakeoff,
            run_config,
            strategy_row=strategies.get(active_id) or {},
            strategy_comparison=comparison,
        )
        status = canary_decision["status"]
        reason = canary_decision["reason"]
        if status == "BLOCK" and recommended_id and recommended_id != active_id:
            canary_decision["next_action"] = f"rollback_to_{recommended_id}"
    elif active_id == DEFAULT_CONTROL_STRATEGY_ID:
        if not bakeoff:
            status = "BLOCK"
            reason = "raw-edge control is active and no settlement-scored bakeoff artifact was available"
        elif DEFAULT_CONTROL_STRATEGY_ID not in pass_ids:
            status = "BLOCK"
            reason = "raw-edge control did not pass settlement-scored bakeoff gates"
        elif recommended_id and recommended_id != active_id and recommended_net is not None and active_net is not None and recommended_net > active_net:
            status = "BLOCK"
            reason = "raw-edge control underperformed a passed safer strategy arm"
        elif active_net is not None and active_net < 0:
            status = "BLOCK"
            reason = "raw-edge control has negative settlement-scored P&L"
        else:
            status = "PASS"
            reason = "raw-edge control passed available settlement-scored gates"
    elif active_id and recommended_id and active_id != recommended_id and recommended_net is not None and active_net is not None and recommended_net > active_net:
        status = "WARN"
        reason = "active arm trails a higher-P&L passed bakeoff arm"
    elif active_id:
        status = "PASS"
        reason = "active arm is explicit and not blocked by available settlement-scored evidence"
    else:
        status = "WARN"
        reason = "multiple or missing active strategy arms; operator review required"
    if exchange_blocks:
        status = "BLOCK"
        reason = exchange_gate.get("reason") or "exchange economics snapshot is not current"
    return {
        "status": status,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "active_strategy_id": active_id,
        "active_strategy_lifecycle": active_lifecycle,
        "active_strategy_lifecycle_status": (
            (canary_decision or {}).get("active_strategy_lifecycle_status") or active_lifecycle
        ),
        "promotion_eligible": bool((canary_decision or {}).get("promotion_eligible")) and not exchange_blocks,
        "paper_only": bool((canary_decision or {}).get("paper_only")),
        "paper_only_reason": (canary_decision or {}).get("paper_only_reason") or "",
        "requalification_required": bool((canary_decision or {}).get("requalification_required")),
        "requalification_route": (canary_decision or {}).get("requalification_route") or "",
        "operator_review_required": bool((canary_decision or {}).get("operator_review_required")),
        "operator_review_status": (canary_decision or {}).get("operator_review_status") or "",
        "operator_review_approved": bool((canary_decision or {}).get("operator_review_approved")),
        "operator_review_reason": (canary_decision or {}).get("operator_review_reason") or "",
        "operator_review_strategy_id": (canary_decision or {}).get("operator_review_strategy_id") or "",
        "operator_review_action": (canary_decision or {}).get("operator_review_action") or "",
        "operator_review_reviewer": (canary_decision or {}).get("operator_review_reviewer") or "",
        "operator_reviewed_at_utc": (canary_decision or {}).get("operator_reviewed_at_utc") or "",
        "demotion_code": (canary_decision or {}).get("demotion_code") or "",
        "next_action": (canary_decision or {}).get("next_action") or ("keep_active_strategy" if status == "PASS" else "operator_review"),
        "recommended_strategy_id": recommended_id,
        "active_net_pnl_usdc": compact_float(active_net),
        "recommended_net_pnl_usdc": compact_float(recommended_net),
        "bakeoff_available": bool(bakeoff),
        "passed_bakeoff_strategy_ids": sorted(pass_ids),
        "complete_label_sample_count": int(((bakeoff.get("label_summary") or {}).get("complete_rows")) or 0),
        "total_label_sample_count": int(((bakeoff.get("label_summary") or {}).get("label_rows")) or 0),
        "canary_settled_order_count": int(((gates_by_strategy.get(active_id) or {}).get("settled_order_count")) or 0),
        "canary_min_settled_orders": int(
            ((run_config.get("active_strategy_canary") or {}).get("min_settled_orders"))
            or ((run_config.get("policy_config") or {}).get("canary_min_settled_orders"))
            or DEFAULT_CANARY_MIN_SETTLED_ORDERS
        ),
        "canary_settled_market_count": int(((gates_by_strategy.get(active_id) or {}).get("settled_market_count")) or 0),
        "canary_min_settled_markets": int(
            ((run_config.get("policy_config") or {}).get("promotion_min_settled_markets"))
            or DEFAULT_PROMOTION_MIN_SETTLED_MARKETS
        ),
        "canary_tail_fill_fraction": compact_float(
            (gates_by_strategy.get(active_id) or {}).get("low_price_tail_fill_fraction")
        ),
        "canary_max_tail_fill_fraction": compact_float(
            ((run_config.get("policy_config") or {}).get("promotion_max_tail_fill_fraction"))
            or DEFAULT_PROMOTION_MAX_TAIL_FILL_FRACTION
        ),
        "canary_age_days": (run_config.get("active_strategy_canary") or {}).get("age_days"),
        "canary_after_fee_required": bool_value(
            ((run_config.get("policy_config") or {}).get("canary_require_after_fee_pnl")),
            True,
        ),
        "canary_after_fee_evidence": _after_fee_pnl_evidence(gates_by_strategy.get(active_id) or {}),
        "canary_failed_gates": (gates_by_strategy.get(active_id) or {}).get("failed_gates") or [],
        "reason": reason,
    }


def _path_mtime_utc(path):
    path = Path(path)
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _time_age_hours(value, now):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (now - value.astimezone(timezone.utc)).total_seconds() / 3600.0)


def _dir_size_bytes(path):
    total = 0
    for item in Path(path).rglob("*"):
        if not item.is_file():
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def taker_artifact_retention_plan(
    runs_root=DEFAULT_RUNS_ROOT,
    *,
    now=None,
    retention_days=DEFAULT_FINALIZATION_RETENTION_DAYS,
    min_candidate_bytes=DEFAULT_RETENTION_CANDIDATE_MIN_BYTES,
    max_candidates=50,
):
    now = utc_now(now)
    root = Path(runs_root)
    candidates = []
    if not root.exists():
        return {
            "status": "NO_RUNS_ROOT",
            "runs_root": str(root),
            "retention_days": int(retention_days),
            "min_candidate_bytes": int(min_candidate_bytes),
            "candidate_count": 0,
            "candidate_bytes": 0,
            "candidates": [],
            "recommended_action": "create runs root or verify configured taker runs path",
        }
    for folder in sorted(root.glob("*/*")):
        if not folder.is_dir():
            continue
        latest = max(
            (
                value for value in (
                    _path_mtime_utc(folder / "orders_long.csv"),
                    _path_mtime_utc(folder / COUNTERFACTUAL_TAPE_FILENAME),
                    _path_mtime_utc(folder / "run_summary.json"),
                    _path_mtime_utc(folder / "settled_pnl.json"),
                    _path_mtime_utc(folder / SETTLED_COUNTERFACTUAL_TAPE_FILENAME),
                    _path_mtime_utc(folder / "settled_counterfactual_pnl.json"),
                )
                if value is not None
            ),
            default=None,
        )
        age_days = (_time_age_hours(latest, now) or 0.0) / 24.0 if latest else None
        if age_days is None or age_days < float(retention_days):
            continue
        size = _dir_size_bytes(folder)
        if size < int(min_candidate_bytes):
            continue
        candidates.append({
            "run_folder": str(folder),
            "target_date": folder.parent.name,
            "run_id": folder.name,
            "latest_artifact_at_utc": latest.isoformat() if latest else None,
            "age_days": round(age_days, 3) if age_days is not None else None,
            "size_bytes": int(size),
            "recommended_action": "move to cold storage or archive after settled_pnl.json is present",
        })
    candidates = sorted(candidates, key=lambda row: row.get("size_bytes") or 0, reverse=True)[:int(max_candidates)]
    return {
        "status": "CANDIDATES" if candidates else "OK",
        "runs_root": str(root),
        "retention_days": int(retention_days),
        "min_candidate_bytes": int(min_candidate_bytes),
        "candidate_count": len(candidates),
        "candidate_bytes": sum(int(row.get("size_bytes") or 0) for row in candidates),
        "candidates": candidates,
        "recommended_action": "archive candidates before launching large backtests or finalization batches",
    }


def _exchange_gate_identity(gate):
    gate = gate or {}
    return {
        "status": gate.get("status"),
        "snapshot_id": gate.get("snapshot_id") or gate.get("exchange_economics_snapshot_id"),
        "snapshot_hash": gate.get("snapshot_hash") or gate.get("exchange_economics_hash"),
        "verified_for_target_date": gate.get("verified_for_target_date"),
        "evidence_basis": gate.get("evidence_basis") or gate.get("exchange_economics_evidence_basis"),
    }


def _exchange_gate_from_finalized_payload(payload):
    payload = payload or {}
    gate = payload.get("exchange_economics_gate")
    if gate:
        return gate
    summary = payload.get("summary") or {}
    strategy_summary = payload.get("strategy_summary") or {}
    strategy_gate = strategy_summary.get("exchange_economics_gate")
    if strategy_gate:
        return strategy_gate
    return {
        "status": (
            payload.get("exchange_economics_status")
            or summary.get("exchange_economics_gate_status")
            or strategy_summary.get("exchange_economics_status")
        ),
        "snapshot_id": (
            payload.get("exchange_economics_snapshot_id")
            or summary.get("exchange_economics_snapshot_id")
            or strategy_summary.get("exchange_economics_snapshot_id")
        ),
        "snapshot_hash": (
            payload.get("exchange_economics_hash")
            or summary.get("exchange_economics_hash")
            or strategy_summary.get("exchange_economics_hash")
        ),
        "verified_for_target_date": (
            payload.get("exchange_economics_verified_for_target_date")
            or summary.get("exchange_economics_verified_for_target_date")
            or strategy_summary.get("exchange_economics_verified_for_target_date")
        ),
        "evidence_basis": (
            payload.get("exchange_economics_evidence_basis")
            or summary.get("exchange_economics_evidence_basis")
            or strategy_summary.get("exchange_economics_evidence_basis")
        ),
    }


def _finalized_exchange_economics_refresh_state(
    settled_pnl_path,
    target_date,
    now,
    *,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    if exchange_economics_snapshot_path is None and exchange_economics_required is None:
        return {"status": "NOT_CHECKED", "needs_refresh": False}
    current_gate, _fields = _exchange_fields_for_finalization(
        {},
        target_date=target_date,
        now=now,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
    )
    current_identity = _exchange_gate_identity(current_gate)
    if not current_gate.get("ok"):
        return {
            "status": "CURRENT_GATE_BLOCK",
            "needs_refresh": False,
            "current_gate": current_identity,
            "reason": current_gate.get("reason"),
        }
    settled_pnl_path = Path(settled_pnl_path)
    strategy_summary_path = settled_pnl_path.with_name("settled_strategy_summary.json")
    payload = load_settled_finalization_projection(settled_pnl_path) or {}
    if not payload and strategy_summary_path.exists():
        payload = _read_small_artifact_json(strategy_summary_path)
    if not payload and settled_pnl_path.exists():
        payload = _read_small_artifact_json(settled_pnl_path)
    if not payload:
        return {
            "status": "MISSING_FINALIZED_PAYLOAD",
            "needs_refresh": True,
            "current_gate": current_identity,
            "reason": "settled_pnl_missing_or_invalid",
        }
    finalized_identity = _exchange_gate_identity(_exchange_gate_from_finalized_payload(payload))
    required_matches = (
        ("status", current_identity.get("status")),
        ("snapshot_id", current_identity.get("snapshot_id")),
        ("snapshot_hash", current_identity.get("snapshot_hash")),
        ("verified_for_target_date", current_identity.get("verified_for_target_date")),
    )
    mismatches = [
        name
        for name, expected in required_matches
        if expected and finalized_identity.get(name) != expected
    ]
    if mismatches:
        return {
            "status": "STALE",
            "needs_refresh": True,
            "current_gate": current_identity,
            "finalized_gate": finalized_identity,
            "mismatches": mismatches,
            "reason": "settled exchange-economics proof does not match current target-date snapshot",
        }
    return {
        "status": "CURRENT",
        "needs_refresh": False,
        "current_gate": current_identity,
        "finalized_gate": finalized_identity,
    }


def finalization_state_for_run(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    *,
    now=None,
    sla_hours=DEFAULT_FINALIZATION_SLA_HOURS,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    now = utc_now(now)
    run_folder = Path(run_folder)
    order_path = run_folder / "orders_long.csv"
    settled_pnl_path = run_folder / "settled_pnl.json"
    settled_report_path = run_folder / "settled_report.md"
    run_summary = _read_taker_summary_artifact(run_folder / "run_summary.json")
    daily_pnl = _read_taker_summary_artifact(run_folder / "daily_pnl.json")
    target_date = (
        run_summary.get("target_date")
        or daily_pnl.get("target_date")
        or run_folder.parent.name
    )
    run_id = run_summary.get("run_id") or daily_pnl.get("run_id") or run_folder.name
    labels = load_settlement_labels(labels_csv)
    target_label_summary = label_summary_for_target(labels_csv, target_date)
    target_labels_complete = bool(
        int(target_label_summary.get("label_rows") or 0) > 0
        and int(target_label_summary.get("complete_rows") or 0) >= int(target_label_summary.get("label_rows") or 0)
    )
    filled_order_count = 0
    labelable_count = 0
    settlement_scoreable_order_count = 0
    for row in (iter_order_rows(order_path) if order_path.exists() else ()):
        label = settlement_label_for_order(row, labels)
        scoreable = settlement_outcome_for_order(row, label) is not None
        if scoreable:
            settlement_scoreable_order_count += 1
        if str(row.get("order_status") or "").upper() == "FILLED":
            filled_order_count += 1
            if scoreable:
                labelable_count += 1
    counterfactual_path = run_folder / COUNTERFACTUAL_TAPE_FILENAME
    settlement_scoreable_counterfactual_count = 0
    for row in (iter_order_rows(counterfactual_path) if counterfactual_path.exists() else ()):
        label = settlement_label_for_order(row, labels)
        if settlement_outcome_for_order(row, label) is not None:
            settlement_scoreable_counterfactual_count += 1
    unmatched_filled = max(0, filled_order_count - labelable_count)
    zero_fill_labels_available = bool(
        not filled_order_count
        and target_labels_complete
        and (settlement_scoreable_order_count > 0 or settlement_scoreable_counterfactual_count > 0)
    )
    labels_available = labelable_count > 0 or zero_fill_labels_available
    labels_mtime = _path_mtime_utc(labels_csv)
    orders_mtime = _path_mtime_utc(order_path)
    settled_mtime = _path_mtime_utc(settled_pnl_path)
    freshness_cutoff = max((value for value in (labels_mtime, orders_mtime) if value is not None), default=None)
    finalization_fresh = bool(
        settled_mtime is not None
        and (freshness_cutoff is None or settled_mtime >= freshness_cutoff)
    )
    exchange_refresh = _finalized_exchange_economics_refresh_state(
        settled_pnl_path,
        target_date,
        now,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
    )
    finalization_fresh = finalization_fresh and not exchange_refresh.get("needs_refresh")
    label_available_at = labels_mtime if labels_available else None
    availability_age_hours = _time_age_hours(label_available_at, now)
    needs_finalization = bool(labels_available and not finalization_fresh)
    if not order_path.exists():
        status = "MISSING_ORDERS"
        sla_status = "NOT_LABELABLE"
    elif labels_available and finalization_fresh:
        status = "FINALIZED"
        sla_status = "PASS"
    elif not filled_order_count and not labels_available:
        status = "NO_FILLED_ORDERS"
        sla_status = "NOT_LABELABLE"
    elif not labels_available:
        status = "WAITING_FOR_LABELS"
        sla_status = "WAITING"
    elif availability_age_hours is not None and availability_age_hours > float(sla_hours):
        status = "LABELS_AVAILABLE_NO_FINALIZATION"
        sla_status = "BREACH"
    else:
        status = "LABELS_AVAILABLE_PENDING_FINALIZATION"
        sla_status = "PENDING"
    return {
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "run_folder": str(run_folder),
        "orders_path": str(order_path),
        "settled_pnl_path": str(settled_pnl_path),
        "settled_report_path": str(settled_report_path),
        "status": status,
        "sla_status": sla_status,
        "sla_hours": float(sla_hours),
        "needs_finalization": needs_finalization,
        "labels_available": labels_available,
        "label_available_at_utc": label_available_at.isoformat() if label_available_at else None,
        "label_availability_age_hours": round(availability_age_hours, 3) if availability_age_hours is not None else None,
        "target_label_rows": target_label_summary.get("label_rows"),
        "target_complete_label_rows": target_label_summary.get("complete_rows"),
        "target_labels_complete": target_labels_complete,
        "filled_order_count": filled_order_count,
        "labelable_filled_order_count": labelable_count,
        "unmatched_filled_order_count": unmatched_filled,
        "settlement_scoreable_order_count": settlement_scoreable_order_count,
        "settlement_scoreable_counterfactual_order_count": settlement_scoreable_counterfactual_count,
        "zero_fill_labels_available": zero_fill_labels_available,
        "settled_pnl_exists": settled_pnl_path.exists(),
        "settled_report_exists": settled_report_path.exists(),
        "finalization_fresh": finalization_fresh,
        "exchange_economics_finalization_status": exchange_refresh.get("status"),
        "exchange_economics_finalization_needs_refresh": exchange_refresh.get("needs_refresh"),
        "exchange_economics_finalization_reason": exchange_refresh.get("reason"),
        "exchange_economics_finalization_mismatches": exchange_refresh.get("mismatches") or [],
        "current_exchange_economics_gate": exchange_refresh.get("current_gate") or {},
        "finalized_exchange_economics_gate": exchange_refresh.get("finalized_gate") or {},
        "orders_modified_at_utc": orders_mtime.isoformat() if orders_mtime else None,
        "labels_modified_at_utc": labels_mtime.isoformat() if labels_mtime else None,
        "settled_pnl_modified_at_utc": settled_mtime.isoformat() if settled_mtime else None,
    }


def finalization_watchdog(
    target_date=None,
    runs_root=DEFAULT_RUNS_ROOT,
    labels_csv=DEFAULT_LABELS_CSV,
    run_folder=None,
    *,
    now=None,
    sla_hours=DEFAULT_FINALIZATION_SLA_HOURS,
    finalize_missing=True,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    retention_days=DEFAULT_FINALIZATION_RETENTION_DAYS,
    retention_min_candidate_bytes=DEFAULT_RETENTION_CANDIDATE_MIN_BYTES,
    ensure_bakeoff=True,
    bakeoff_strategies=DEFAULT_BAKEOFF_STRATEGIES,
    champion_strategy_id=ACTIVE_DEFAULT_STRATEGY_ID,
    champion_min_complete_label_days=DEFAULT_CHAMPION_MIN_COMPLETE_LABEL_DAYS,
    champion_min_settled_orders=DEFAULT_CHAMPION_MIN_SETTLED_ORDERS,
    champion_ledger_out=None,
    champion_ledger_report_out=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    now = utc_now(now)
    folders = [Path(run_folder)] if run_folder else taker_run_folders(runs_root, target_date=target_date)
    ledger_runs_root = Path(run_folder).parent.parent if run_folder else Path(runs_root)
    disk_preflight = disk_capacity_preflight(
        Path(run_folder) if run_folder else runs_root,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    rows = []
    finalized = []
    alerts = []
    for folder in folders:
        state = finalization_state_for_run(
            folder,
            labels_csv=labels_csv,
            now=now,
            sla_hours=sla_hours,
            exchange_economics_snapshot_path=exchange_economics_snapshot_path,
            exchange_economics_platform=exchange_economics_platform,
            exchange_economics_required=exchange_economics_required,
        )
        bakeoff_action = "not_labelable"
        bakeoff_path = str(Path(folder) / "strategy_bakeoff.json")
        if state.get("labels_available") and ensure_bakeoff:
            if not disk_preflight.get("ok"):
                bakeoff_action = "blocked_disk_capacity"
            else:
                bakeoff_state = ensure_taker_strategy_bakeoff(
                    folder,
                    labels_csv=labels_csv,
                    strategies=bakeoff_strategies,
                    now=now,
                    min_free_bytes=min_free_bytes,
                    disk_usage_fn=disk_usage_fn,
                    exchange_economics_snapshot_path=exchange_economics_snapshot_path,
                    exchange_economics_platform=exchange_economics_platform,
                    exchange_economics_required=exchange_economics_required,
                    stream_tapes=True,
                    materialize_output_rows=False,
                    include_payload=False,
                )
                bakeoff_action = bakeoff_state.get("action")
                bakeoff_path = bakeoff_state.get("strategy_bakeoff_path")
        elif state.get("labels_available"):
            bakeoff_action = "disabled"
        action = "noop"
        if state.get("needs_finalization") and finalize_missing:
            if not disk_preflight.get("ok"):
                action = "blocked_disk_capacity"
                state["sla_status"] = "BREACH" if state.get("sla_status") == "BREACH" else "PENDING"
                state["status"] = "DISK_BLOCKED_FINALIZATION"
                state["disk_capacity_preflight"] = disk_preflight
            else:
                payload = finalize_taker_run(
                    folder,
                    labels_csv=labels_csv,
                    now=now,
                    min_free_bytes=min_free_bytes,
                    disk_usage_fn=disk_usage_fn,
                    exchange_economics_snapshot_path=exchange_economics_snapshot_path,
                    exchange_economics_platform=exchange_economics_platform,
                    exchange_economics_required=exchange_economics_required,
                    stream_tapes=True,
                    materialize_output_rows=False,
                )
                try:
                    finalized.append({
                        "run_id": payload.get("run_id"),
                        "target_date": payload.get("target_date"),
                        "run_folder": payload.get("run_folder"),
                        "settled_pnl_path": payload.get("settled_pnl_path"),
                        "settled_report_path": payload.get("settled_report_path"),
                        "settled_order_count": (payload.get("summary") or {}).get("settled_order_count"),
                        "unsettled_order_count": (payload.get("summary") or {}).get("unsettled_order_count"),
                        "net_pnl_usdc": (payload.get("summary") or {}).get("net_pnl_usdc"),
                    })
                finally:
                    close_payload = getattr(payload, "close", None)
                    if close_payload:
                        close_payload()
                    del payload
                state = finalization_state_for_run(
                    folder,
                    labels_csv=labels_csv,
                    now=now,
                    sla_hours=sla_hours,
                    exchange_economics_snapshot_path=exchange_economics_snapshot_path,
                    exchange_economics_platform=exchange_economics_platform,
                    exchange_economics_required=exchange_economics_required,
                )
                action = "finalized"
        elif state.get("needs_finalization"):
            action = "would_finalize"
        state["bakeoff_action"] = bakeoff_action
        state["strategy_bakeoff_path"] = bakeoff_path
        state["action"] = action
        if state.get("sla_status") in {"BREACH", "PENDING"} and state.get("needs_finalization"):
            alerts.append({
                "run_id": state.get("run_id"),
                "target_date": state.get("target_date"),
                "status": state.get("status"),
                "sla_status": state.get("sla_status"),
                "action": action,
                "run_folder": state.get("run_folder"),
            })
        rows.append(state)
        # Break cycles and return transient row batches before the next run.
        gc.collect()
    retention = taker_artifact_retention_plan(
        runs_root=ledger_runs_root,
        now=now,
        retention_days=retention_days,
        min_candidate_bytes=retention_min_candidate_bytes,
    )
    bakeoff_paths = [
        Path(row.get("strategy_bakeoff_path"))
        for row in rows
        if row.get("strategy_bakeoff_path") and Path(row.get("strategy_bakeoff_path")).exists()
    ]
    if champion_ledger_out:
        champion_ledger = write_champion_challenger_ledger(
            out_json=Path(champion_ledger_out),
            out_report=Path(champion_ledger_report_out) if champion_ledger_report_out else None,
            min_free_bytes=min_free_bytes,
            disk_usage_fn=disk_usage_fn,
            runs_root=ledger_runs_root,
            target_date=target_date,
            bakeoff_paths=bakeoff_paths,
            champion_strategy_id=champion_strategy_id,
            now=now,
            min_complete_label_days=champion_min_complete_label_days,
            min_settled_orders=champion_min_settled_orders,
        )
    else:
        champion_ledger = build_champion_challenger_ledger(
            runs_root=ledger_runs_root,
            target_date=target_date,
            bakeoff_paths=bakeoff_paths,
            champion_strategy_id=champion_strategy_id,
            now=now,
            min_complete_label_days=champion_min_complete_label_days,
            min_settled_orders=champion_min_settled_orders,
        )
    summary = {
        "run_count": len(rows),
        "labelable_run_count": sum(1 for row in rows if row.get("labels_available")),
        "needs_finalization_count": sum(1 for row in rows if row.get("needs_finalization")),
        "finalized_run_count": len(finalized),
        "sla_breach_count": sum(1 for row in rows if row.get("sla_status") == "BREACH"),
        "pending_finalization_count": sum(1 for row in rows if row.get("sla_status") == "PENDING"),
        "bakeoff_created_count": sum(1 for row in rows if row.get("bakeoff_action") == "created"),
        "bakeoff_fresh_count": sum(1 for row in rows if row.get("bakeoff_action") == "fresh"),
        "disk_capacity_status": disk_preflight.get("status"),
        "retention_candidate_count": retention.get("candidate_count"),
        "champion_decision": champion_ledger.get("promotion_decision"),
        "champion_recommended_strategy_id": champion_ledger.get("recommended_strategy_id"),
    }
    return {
        "schema_version": "taker_settlement_finalization_watchdog_v0.1",
        "generated_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat() if target_date else None,
        "runs_root": str(runs_root),
        "labels_csv": str(labels_csv),
        "sla_hours": float(sla_hours),
        "finalize_missing": bool(finalize_missing),
        "ensure_bakeoff": bool(ensure_bakeoff),
        "bakeoff_strategies": bakeoff_strategies,
        "summary": summary,
        "disk_capacity_preflight": disk_preflight,
        "retention_plan": retention,
        "champion_challenger_ledger": champion_ledger,
        "alerts": alerts,
        "finalized_runs": finalized,
        "runs": rows,
    }


def render_finalization_watchdog_report(payload):
    summary = payload.get("summary") or {}
    lines = [
        "# Taker Settlement Finalization Watchdog",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Target date: `{payload.get('target_date') or 'all'}`",
        f"Labels CSV: `{payload.get('labels_csv')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Runs scanned", summary.get("run_count")],
            ["Labelable runs", summary.get("labelable_run_count")],
            ["Needs finalization", summary.get("needs_finalization_count")],
            ["Finalized runs", summary.get("finalized_run_count")],
            ["SLA breaches", summary.get("sla_breach_count")],
            ["Pending finalization", summary.get("pending_finalization_count")],
            ["Bakeoffs created", summary.get("bakeoff_created_count")],
            ["Bakeoffs fresh", summary.get("bakeoff_fresh_count")],
            ["Champion decision", summary.get("champion_decision")],
            ["Recommended strategy", summary.get("champion_recommended_strategy_id")],
            ["Disk capacity", summary.get("disk_capacity_status")],
            ["Retention candidates", summary.get("retention_candidate_count")],
        ],
    ))
    lines.extend(["", "## Runs", ""])
    lines.extend(markdown_table(
        ["Run", "Date", "Status", "SLA", "Bakeoff", "Action", "Filled", "Labelable"],
        [
            [
                row.get("run_id"),
                row.get("target_date"),
                row.get("status"),
                row.get("sla_status"),
                row.get("bakeoff_action"),
                row.get("action"),
                row.get("filled_order_count"),
                row.get("labelable_filled_order_count"),
            ]
            for row in payload.get("runs") or []
        ],
    ))
    alerts = payload.get("alerts") or []
    if alerts:
        lines.extend(["", "## Alerts", ""])
        lines.extend(markdown_table(
            ["Run", "Date", "SLA", "Action", "Folder"],
            [
                [
                    row.get("run_id"),
                    row.get("target_date"),
                    row.get("sla_status"),
                    row.get("action"),
                    row.get("run_folder"),
                ]
                for row in alerts
            ],
        ))
    lines.append("")
    return "\n".join(lines)


def render_counterfactual_settlement_report(payload):
    summary = payload.get("summary") or {}
    lift_rows = payload.get("strategy_lift") or []
    slice_summaries = payload.get("slice_summaries") or {}
    no_side_campaign = payload.get("no_side_campaign") or {}
    lines = [
        "# Taker Counterfactual Settlement Report",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Run ID: `{payload.get('run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Counterfactual tape: `{payload.get('counterfactual_orders_path')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Counterfactual rows", summary.get("row_count")],
            ["Would-buy rows", summary.get("would_buy_count")],
            ["Settled would-buy rows", summary.get("settled_would_buy_count")],
            ["Real filled matches", summary.get("real_filled_match_count")],
            ["Zero-real-fill learning", str(summary.get("zero_real_fill_learning")).lower()],
            ["Best strategy", summary.get("best_counterfactual_strategy_id") or "-"],
            ["Best net P&L", fmt_num(summary.get("best_counterfactual_net_pnl_usdc"), 4)],
        ],
    ))
    if no_side_campaign:
        lines.extend(["", "## NO-Side Campaign", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", no_side_campaign.get("status")],
                ["NO-side rows", no_side_campaign.get("no_side_row_count")],
                ["Real NO-book rows", no_side_campaign.get("real_no_book_row_count")],
                ["Real NO-book eligible rows", no_side_campaign.get("real_no_book_depth_eligible_row_count")],
                ["Synthetic NO-book rows", no_side_campaign.get("synthetic_no_book_row_count")],
                ["Stale NO-book rows", no_side_campaign.get("stale_no_book_row_count")],
                ["NO-side would-buy rows", no_side_campaign.get("no_side_would_buy_count")],
                ["Countable would-buy rows", no_side_campaign.get("countable_no_side_would_buy_count")],
                ["Settled countable would-buy rows", no_side_campaign.get("settled_countable_no_side_would_buy_count")],
                ["Countable NO-side net P&L", fmt_num(no_side_campaign.get("countable_no_side_net_pnl_usdc"), 4)],
                ["Delta vs no-trade", fmt_num(no_side_campaign.get("delta_vs_no_trade_net_pnl_usdc"), 4)],
            ],
        ))
        for slice_name, label in (("by_market", "NO-Side by Market"), ("by_hour", "NO-Side by Hour")):
            rows = no_side_campaign.get(slice_name) or []
            if rows:
                lines.extend(["", f"## {label}", ""])
                lines.extend(markdown_table(
                    ["Value", "NO Rows", "Real Book", "Would Buy", "Countable", "Settled", "Net P&L"],
                    [
                        [
                            row.get("value"),
                            row.get("no_side_row_count"),
                            row.get("real_no_book_row_count"),
                            row.get("no_side_would_buy_count"),
                            row.get("countable_no_side_would_buy_count"),
                            row.get("settled_countable_no_side_would_buy_count"),
                            fmt_num(row.get("countable_net_pnl_usdc"), 4),
                        ]
                        for row in rows
                    ],
                ))
        strategy_rows = no_side_campaign.get("by_strategy") or []
        if strategy_rows:
            lines.extend(["", "## NO-Side by Strategy", ""])
            lines.extend(markdown_table(
                [
                    "Strategy",
                    "Family",
                    "NO Rows",
                    "Countable",
                    "Settled",
                    "NO Net P&L",
                    "Vs No-Trade",
                    "Strategy Vs Market Top",
                    "Gate",
                ],
                [
                    [
                        row.get("strategy_id"),
                        row.get("strategy_family"),
                        row.get("no_side_row_count"),
                        row.get("countable_no_side_would_buy_count"),
                        row.get("settled_countable_no_side_would_buy_count"),
                        fmt_num(row.get("countable_net_pnl_usdc"), 4),
                        fmt_num(row.get("delta_vs_no_trade_net_pnl_usdc"), 4),
                        fmt_num(row.get("strategy_delta_vs_market_top_net_pnl_usdc"), 4),
                        row.get("settlement_promotion_gate_status") or "-",
                    ]
                    for row in strategy_rows
                ],
            ))
    if lift_rows:
        lines.extend(["", "## Strategy Lift", ""])
        lines.extend(markdown_table(
            [
                "Strategy",
                "Family",
                "Would Buy",
                "Settled",
                "Net P&L",
                "Vs Active",
                "Vs No-Trade",
                "Vs Market Top",
                "Gate",
            ],
            [
                [
                    row.get("strategy_id"),
                    row.get("strategy_family"),
                    row.get("would_buy_count"),
                    row.get("settled_would_buy_count"),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_vs_active_policy_net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_vs_no_trade_net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_vs_market_top_net_pnl_usdc"), 4),
                    row.get("settlement_promotion_gate_status") or "-",
                ]
                for row in lift_rows
            ],
        ))
    if slice_summaries:
        lines.extend(["", "## Slice Coverage", ""])
        lines.extend(markdown_table(
            ["Slice", "Groups", "Would Buy", "Settled"],
            [
                [
                    name,
                    len(rows or []),
                    sum(int(row.get("would_buy_count") or 0) for row in rows or []),
                    sum(int(row.get("settled_would_buy_count") or 0) for row in rows or []),
                ]
                for name, rows in sorted(slice_summaries.items())
            ],
        ))
    model_bakeoff = payload.get("model_variant_bakeoff") or {}
    if model_bakeoff:
        lines.extend(["", "## Model Variants", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", model_bakeoff.get("status")],
                ["Pairs", model_bakeoff.get("pair_count")],
                ["Comparisons", model_bakeoff.get("comparison_count")],
                ["Multiple-testing method", model_bakeoff.get("multiple_testing_method")],
                ["Adjusted alpha", model_bakeoff.get("adjusted_alpha")],
                ["Recommended variant", model_bakeoff.get("recommended_model_variant_id") or "-"],
            ],
        ))
        lines.extend(["", "## Model Variant Pairs", ""])
        lines.extend(markdown_table(
            ["Variant", "Strategy", "Would Buy", "Settled", "Net P&L", "Delta vs Served", "Status"],
            [
                [
                    row.get("model_variant_id"),
                    row.get("strategy_id"),
                    row.get("would_buy_count"),
                    row.get("settled_would_buy_count"),
                    fmt_num(row.get("net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_vs_served_current_net_pnl_usdc"), 4),
                    row.get("variant_selection_status"),
                ]
                for row in model_bakeoff.get("pairs") or []
            ],
        ))
    clustered_gate = payload.get("clustered_promotion_gate" ) or {}
    if clustered_gate:
        lines.extend(["", "## Clustered Promotion Gate", ""])
        lines.extend(markdown_table(
            ["Metric", "Value"],
            [
                ["Status", clustered_gate.get("status")],
                ["Cluster key", clustered_gate.get("cluster_key")],
                ["Pairs", clustered_gate.get("pair_count")],
                ["Pass pairs", clustered_gate.get("pass_pair_count")],
                ["Adjusted alpha", clustered_gate.get("adjusted_alpha")],
                ["Min target days", clustered_gate.get("min_independent_target_days")],
                ["Min markets", clustered_gate.get("min_independent_markets")],
            ],
        ))
    lines.append("")
    return "\n".join(lines)


def _finalize_counterfactual_tape_impl(
    run_folder,
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    now=None,
    budget_usdc=0.0,
    run_id=None,
    target_date=None,
    run_config=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    aggregation=None,
):
    run_folder = Path(run_folder)
    counterfactual_path = run_folder / COUNTERFACTUAL_TAPE_FILENAME
    if not counterfactual_path.exists():
        return {
            "status": "MISSING",
            "counterfactual_orders_path": str(counterfactual_path),
            "detail": "no counterfactual tape found for this run",
        }
    now = utc_now(now)
    run_config = run_config or {}
    exchange_gate, exchange_fields = _exchange_fields_for_finalization(
        run_config,
        target_date=target_date or run_folder.parent.name,
        now=now,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
    )
    scoring_run_config = _run_config_with_exchange_fields(run_config, exchange_gate, exchange_fields)
    labels = load_settlement_labels(labels_csv)
    if aggregation is None:
        rows = read_order_rows(counterfactual_path)
        scored_rows, label_summary = score_orders_against_labels(rows, labels)
        _annotate_rows_with_exchange_fields(scored_rows, exchange_fields)
        for row in scored_rows:
            row["counterfactual_pnl_source"] = (
                row.get("pnl_source")
                or row.get("counterfactual_pnl_source")
                or ""
            )
    else:
        scored_rows = aggregation.scored_counterfactual_rows
        label_summary = _stream_score_order_tape(
            counterfactual_path,
            labels,
            scored_rows,
            exchange_fields,
            counterfactual=True,
        )
    strategy_count = len({strategy_id_for_row(row) for row in scored_rows}) or 1
    pnl_payload = build_pnl_payload(
        scored_rows,
        float(budget_usdc or 0.0) * strategy_count,
        run_id or run_folder.name,
        target_date or run_folder.parent.name,
        now=now,
        policy_config=scoring_run_config.get("policy_config") or {},
    )
    pnl_payload = _annotate_pnl_with_exchange_fields(pnl_payload, exchange_gate, exchange_fields)
    active_strategy_id = scoring_run_config.get("active_strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    strategy_lift = counterfactual_strategy_lift_rows(
        pnl_payload,
        active_strategy_id=active_strategy_id,
    )
    slice_summaries = counterfactual_slice_summaries(scored_rows)
    no_side_campaign = no_side_campaign_summary(scored_rows, pnl_payload=pnl_payload)
    model_variant_bakeoff = model_variant_strategy_bakeoff(scored_rows)
    policy_config = scoring_run_config.get("policy_config") or {}
    clustered_gate = clustered_taker_promotion_statistics(
        scored_rows,
        alpha=maybe_float(policy_config.get("promotion_cluster_alpha")) or 0.05,
        min_independent_target_days=int(policy_config.get("promotion_min_independent_target_days") or 3),
        min_independent_markets=int(policy_config.get("promotion_min_independent_markets") or 2),
    )
    summary = counterfactual_learning_summary(scored_rows, pnl_payload=pnl_payload)
    summary.update({
        "active_policy_strategy_id": active_strategy_id,
        "label_count": label_summary.get("label_count"),
        "matched_would_buy_orders": label_summary.get("matched_filled_orders"),
        "unmatched_would_buy_orders": label_summary.get("unmatched_filled_orders"),
        "no_side_campaign_status": no_side_campaign.get("status"),
        "no_side_row_count": no_side_campaign.get("no_side_row_count"),
        "no_side_would_buy_count": no_side_campaign.get("no_side_would_buy_count"),
        "countable_no_side_would_buy_count": no_side_campaign.get("countable_no_side_would_buy_count"),
        "settled_countable_no_side_would_buy_count": no_side_campaign.get("settled_countable_no_side_would_buy_count"),
        "exchange_economics_gate_status": exchange_gate.get("status") or exchange_fields.get("exchange_economics_status"),
        **exchange_fields,
    })
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=scoring_run_config,
        run_id=run_id or run_folder.name,
        target_date=target_date or run_folder.parent.name,
        now=now,
    )
    settled_counterfactual_path = run_folder / SETTLED_COUNTERFACTUAL_TAPE_FILENAME
    settled_pnl_path = run_folder / "settled_counterfactual_pnl.json"
    settled_report_path = run_folder / "settled_counterfactual_report.md"
    settled_strategy_summary_path = run_folder / "settled_counterfactual_strategy_summary.json"
    settled_strategy_report_path = run_folder / "settled_counterfactual_strategy_report.md"
    payload = {
        "schema_version": COUNTERFACTUAL_TAPE_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "status": "SCORED",
        "run_id": run_id or run_folder.name,
        "target_date": ensure_date(target_date or run_folder.parent.name).isoformat(),
        "run_folder": str(run_folder),
        "counterfactual_orders_path": str(counterfactual_path),
        "settled_counterfactual_orders_path": str(settled_counterfactual_path),
        "settled_counterfactual_pnl_path": str(settled_pnl_path),
        "settled_counterfactual_report_path": str(settled_report_path),
        "settled_counterfactual_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_counterfactual_strategy_report_path": str(settled_strategy_report_path),
        "labels_csv": str(labels_csv),
        "label_summary": label_summary,
        "summary": summary,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "strategy_lift": strategy_lift,
        "slice_summaries": slice_summaries,
        "no_side_campaign": no_side_campaign,
        "model_variant_bakeoff": model_variant_bakeoff,
        "clustered_promotion_gate": clustered_gate,
        "pnl": pnl_payload,
        "strategy_summary": strategy_summary,
        "retention": {
            "policy": "daily_roll_target_date_and_file_mtime_cutoff",
            "enforced_by": "weather.operations.taker_bot_daily_roll",
            "retention_days": int(
                (run_config.get("policy_config") or {}).get("counterfactual_retention_days")
                or DEFAULT_FINALIZATION_RETENTION_DAYS
            ),
            "settlement_summary_required": False,
            "retained_after_tape_expiry": [
                "settled_counterfactual_pnl.json",
                "settled_counterfactual_report.md",
                "settled_counterfactual_strategy_summary.json",
                "settled_counterfactual_strategy_report.md",
            ],
        },
    }
    write_settled_worker_tape(
        settled_counterfactual_path,
        COUNTERFACTUAL_ORDER_COLUMNS,
        scored_rows,
    )
    write_json(settled_strategy_summary_path, strategy_summary)
    write_text_atomic(
        settled_report_path,
        render_counterfactual_settlement_report(payload),
    )
    write_text_atomic(
        settled_strategy_report_path,
        render_strategy_report(strategy_summary),
    )
    # The canonical counterfactual payload is the freshness receipt.
    write_json(settled_pnl_path, payload)
    return payload


def finalize_counterfactual_tape(
    run_folder,
    *,
    labels_csv=DEFAULT_LABELS_CSV,
    now=None,
    budget_usdc=0.0,
    run_id=None,
    target_date=None,
    run_config=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    stream_tapes=True,
    materialize_output_rows=True,
    _aggregation=None,
):
    """Finalize one counterfactual tape with bounded, disposable row state."""

    aggregation = _aggregation
    owns_aggregation = bool(stream_tapes and aggregation is None)
    if owns_aggregation:
        aggregation = TakerRunAggregation()
    try:
        payload = _finalize_counterfactual_tape_impl(
            run_folder,
            labels_csv=labels_csv,
            now=now,
            budget_usdc=budget_usdc,
            run_id=run_id,
            target_date=target_date,
            run_config=run_config,
            exchange_economics_snapshot_path=exchange_economics_snapshot_path,
            exchange_economics_platform=exchange_economics_platform,
            exchange_economics_required=exchange_economics_required,
            aggregation=aggregation if stream_tapes else None,
        )
        if not owns_aggregation:
            return payload
        if materialize_output_rows:
            return aggregation.materialize(payload)
        return DeferredTakerPayload(payload, aggregation)
    except BaseException:
        if owns_aggregation:
            aggregation.close()
        raise
    finally:
        if owns_aggregation and materialize_output_rows:
            aggregation.close()


def _finalize_taker_run_impl(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    now=None,
    *,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    aggregation=None,
):
    run_folder = Path(run_folder)
    order_path = run_folder / "orders_long.csv"
    if not order_path.exists():
        raise FileNotFoundError(f"missing taker orders tape: {order_path}")
    now = utc_now(now)
    run_summary = _read_taker_summary_artifact(run_folder / "run_summary.json")
    daily_pnl = _read_taker_summary_artifact(run_folder / "daily_pnl.json")
    target_date = (
        run_summary.get("target_date")
        or daily_pnl.get("target_date")
        or run_folder.parent.name
    )
    run_id = run_summary.get("run_id") or daily_pnl.get("run_id") or run_folder.name
    summary = run_summary.get("summary") or {}
    daily_summary = daily_pnl.get("summary") or {}
    budget_usdc = first_numeric(
        summary.get("budget_usdc"),
        daily_summary.get("budget_usdc"),
        run_summary.get("budget_usdc"),
        default=0.0,
    )

    run_config = read_json(run_folder / "run_config.json", {}) or {}
    exchange_gate, exchange_fields = _exchange_fields_for_finalization(
        run_config,
        target_date=target_date,
        now=now,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
    )
    scoring_run_config = _run_config_with_exchange_fields(run_config, exchange_gate, exchange_fields)
    labels = load_settlement_labels(labels_csv)
    if aggregation is None:
        raw_orders = read_order_rows(order_path)
        scored_orders, label_summary = score_orders_against_labels(raw_orders, labels)
        _annotate_rows_with_exchange_fields(scored_orders, exchange_fields)
    else:
        scored_orders = aggregation.scored_rows
        label_summary = _stream_score_order_tape(
            order_path,
            labels,
            scored_orders,
            exchange_fields,
        )
    pnl_payload = build_pnl_payload(
        scored_orders,
        budget_usdc,
        run_id,
        target_date,
        now=now,
        policy_config=scoring_run_config.get("policy_config") or {},
    )
    pnl_payload = _annotate_pnl_with_exchange_fields(pnl_payload, exchange_gate, exchange_fields)
    reported_summary = reported_taker_pnl_summary(run_summary, daily_pnl)
    reconciliation = build_settlement_reconciliation(pnl_payload.get("summary") or {}, reported_summary)
    settled_orders_path = run_folder / "settled_orders_long.csv"
    settled_pnl_path = run_folder / "settled_pnl.json"
    settled_report_path = run_folder / "settled_report.md"
    settled_strategy_summary_path = run_folder / "settled_strategy_summary.json"
    settled_strategy_report_path = run_folder / "settled_strategy_report.md"
    disk_preflight = disk_capacity_preflight(
        run_folder,
        min_free_bytes=min_free_bytes,
        usage_fn=disk_usage_fn,
    )
    if not disk_preflight.get("ok"):
        raise RuntimeError(
            "insufficient free disk for taker settlement finalization: "
            f"free={disk_preflight.get('free_bytes')} required={disk_preflight.get('required_free_bytes')}"
        )
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=scoring_run_config,
        run_id=run_id,
        target_date=target_date,
        now=now,
    )
    bakeoff = _bounded_bakeoff_gate_payload(run_folder / "strategy_bakeoff.json")
    counterfactual = finalize_counterfactual_tape(
        run_folder,
        labels_csv=labels_csv,
        now=now,
        budget_usdc=budget_usdc,
        run_id=run_id,
        target_date=target_date,
        run_config=scoring_run_config,
        exchange_economics_snapshot_path=exchange_economics_snapshot_path,
        exchange_economics_platform=exchange_economics_platform,
        exchange_economics_required=exchange_economics_required,
        stream_tapes=aggregation is not None,
        materialize_output_rows=False,
        _aggregation=aggregation,
    )
    next_gate = next_run_policy_gate(strategy_summary, run_config=scoring_run_config, bakeoff=bakeoff)
    final_summary = {
        **(pnl_payload.get("summary") or {}),
        "pnl_source": reconciliation.get("preferred_pnl_source"),
        "reconciliation_status": reconciliation.get("status"),
        "reconciliation_warning_count": len(reconciliation.get("warnings") or []),
        "next_run_policy_status": next_gate.get("status"),
        "next_run_policy_reason": next_gate.get("reason"),
        "active_strategy_id": next_gate.get("active_strategy_id"),
        "active_strategy_lifecycle": next_gate.get("active_strategy_lifecycle"),
        "active_strategy_lifecycle_status": next_gate.get("active_strategy_lifecycle_status"),
        "active_strategy_promotion_eligible": next_gate.get("promotion_eligible"),
        "active_strategy_paper_only": next_gate.get("paper_only"),
        "active_strategy_paper_only_reason": next_gate.get("paper_only_reason"),
        "active_strategy_requalification_required": next_gate.get("requalification_required"),
        "active_strategy_requalification_route": next_gate.get("requalification_route"),
        "active_strategy_operator_review_required": next_gate.get("operator_review_required"),
        "active_strategy_operator_review_status": next_gate.get("operator_review_status"),
        "active_strategy_operator_review_approved": next_gate.get("operator_review_approved"),
        "active_strategy_operator_review_reason": next_gate.get("operator_review_reason"),
        "active_strategy_operator_review_action": next_gate.get("operator_review_action"),
        "active_strategy_operator_review_reviewer": next_gate.get("operator_review_reviewer"),
        "active_strategy_operator_reviewed_at_utc": next_gate.get("operator_reviewed_at_utc"),
        "active_strategy_demotion_code": next_gate.get("demotion_code"),
        "active_strategy_next_action": next_gate.get("next_action"),
        "active_strategy_complete_label_sample_count": next_gate.get("complete_label_sample_count"),
        "active_strategy_total_label_sample_count": next_gate.get("total_label_sample_count"),
        "active_strategy_canary_settled_order_count": next_gate.get("canary_settled_order_count"),
        "active_strategy_canary_min_settled_orders": next_gate.get("canary_min_settled_orders"),
        "active_strategy_canary_settled_market_count": next_gate.get("canary_settled_market_count"),
        "active_strategy_canary_min_settled_markets": next_gate.get("canary_min_settled_markets"),
        "active_strategy_canary_tail_fill_fraction": next_gate.get("canary_tail_fill_fraction"),
        "active_strategy_canary_max_tail_fill_fraction": next_gate.get("canary_max_tail_fill_fraction"),
        "active_strategy_canary_age_days": next_gate.get("canary_age_days"),
        "active_strategy_canary_after_fee_required": next_gate.get("canary_after_fee_required"),
        "active_strategy_canary_after_fee_evidence": next_gate.get("canary_after_fee_evidence"),
        "disk_capacity_status": disk_preflight.get("status"),
        "exchange_economics_gate_status": exchange_gate.get("status") or exchange_fields.get("exchange_economics_status"),
        "exchange_economics_gate_reason": exchange_gate.get("reason"),
        **exchange_fields,
        "disk_free_bytes": disk_preflight.get("free_bytes"),
        "disk_required_free_bytes": disk_preflight.get("required_free_bytes"),
        "settled_orders_path": str(settled_orders_path),
        "settled_report_path": str(settled_report_path),
        "settled_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_strategy_report_path": str(settled_strategy_report_path),
        "counterfactual_status": counterfactual.get("status"),
        "counterfactual_row_count": (counterfactual.get("summary") or {}).get("row_count"),
        "counterfactual_would_buy_count": (counterfactual.get("summary") or {}).get("would_buy_count"),
        "counterfactual_settled_would_buy_count": (counterfactual.get("summary") or {}).get("settled_would_buy_count"),
        "counterfactual_zero_real_fill_learning": (counterfactual.get("summary") or {}).get("zero_real_fill_learning"),
        "counterfactual_no_side_campaign_status": (counterfactual.get("no_side_campaign") or {}).get("status"),
        "counterfactual_no_side_row_count": (counterfactual.get("no_side_campaign") or {}).get("no_side_row_count"),
        "counterfactual_no_side_would_buy_count": (counterfactual.get("no_side_campaign") or {}).get("no_side_would_buy_count"),
        "counterfactual_countable_no_side_would_buy_count": (
            counterfactual.get("no_side_campaign") or {}
        ).get("countable_no_side_would_buy_count"),
        "counterfactual_settled_countable_no_side_would_buy_count": (
            counterfactual.get("no_side_campaign") or {}
        ).get("settled_countable_no_side_would_buy_count"),
        "model_variant_bakeoff_status": (counterfactual.get("model_variant_bakeoff") or {}).get("status"),
        "model_variant_bakeoff_pair_count": (counterfactual.get("model_variant_bakeoff") or {}).get("pair_count"),
        "model_variant_recommended_variant_id": (
            counterfactual.get("model_variant_bakeoff") or {}
        ).get("recommended_model_variant_id"),
        "clustered_promotion_gate_status": (counterfactual.get("clustered_promotion_gate") or {}).get("status"),
        "clustered_promotion_gate_pair_count": (counterfactual.get("clustered_promotion_gate") or {}).get("pair_count"),
        "clustered_promotion_gate_pass_pair_count": (counterfactual.get("clustered_promotion_gate") or {}).get("pass_pair_count"),
        "settled_counterfactual_orders_path": counterfactual.get("settled_counterfactual_orders_path"),
        "settled_counterfactual_pnl_path": counterfactual.get("settled_counterfactual_pnl_path"),
        "settled_counterfactual_report_path": counterfactual.get("settled_counterfactual_report_path"),
        **reported_summary,
    }
    payload = {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": run_id,
        "target_date": ensure_date(target_date).isoformat(),
        "run_folder": str(run_folder),
        "orders_path": str(order_path),
        "settled_orders_path": str(settled_orders_path),
        "settled_pnl_path": str(settled_pnl_path),
        "settled_report_path": str(settled_report_path),
        "settled_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_strategy_report_path": str(settled_strategy_report_path),
        "labels_csv": str(Path(labels_csv)),
        "label_summary": label_summary,
        "summary": final_summary,
        "pnl": pnl_payload,
        "exchange_economics_gate": exchange_gate,
        **exchange_fields,
        "strategy_summary": strategy_summary,
        "counterfactual": counterfactual,
        "next_run_policy_gate": next_gate,
        "reconciliation": reconciliation,
        "disk_capacity_preflight": disk_preflight,
        "warnings": reconciliation.get("warnings") or [],
    }
    write_settled_worker_tape(settled_orders_path, ORDER_COLUMNS, scored_orders)
    write_json(settled_strategy_summary_path, strategy_summary)
    write_text_atomic(settled_report_path, render_settlement_report(payload))
    write_text_atomic(
        settled_strategy_report_path,
        render_strategy_report(strategy_summary),
    )
    # Publish the canonical payload before its stat-bound compact projection.
    write_json(settled_pnl_path, payload)
    write_settled_finalization_projection(settled_pnl_path, payload)
    return payload


def finalize_taker_run(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    now=None,
    *,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
    stream_tapes=True,
    materialize_output_rows=True,
):
    """Finalize one run while retaining at most one fixed scoring batch in RAM."""

    aggregation = TakerRunAggregation() if stream_tapes else None
    try:
        payload = _finalize_taker_run_impl(
            run_folder,
            labels_csv=labels_csv,
            now=now,
            min_free_bytes=min_free_bytes,
            disk_usage_fn=disk_usage_fn,
            exchange_economics_snapshot_path=exchange_economics_snapshot_path,
            exchange_economics_platform=exchange_economics_platform,
            exchange_economics_required=exchange_economics_required,
            aggregation=aggregation,
        )
        if aggregation is None:
            return payload
        if materialize_output_rows:
            return aggregation.materialize(payload)
        return DeferredTakerPayload(payload, aggregation)
    except BaseException:
        if aggregation is not None:
            aggregation.close()
        raise
    finally:
        if aggregation is not None and materialize_output_rows:
            aggregation.close()


def taker_run_folders(runs_root=DEFAULT_RUNS_ROOT, target_date=None):
    root = Path(runs_root)
    if target_date:
        pattern_root = root / ensure_date(target_date).isoformat()
        candidates = sorted(pattern_root.glob("*"))
    else:
        candidates = sorted(root.glob("*/*"))
    return [path for path in candidates if path.is_dir() and (path / "orders_long.csv").exists()]


def finalize_taker_runs(
    target_date=None,
    runs_root=DEFAULT_RUNS_ROOT,
    labels_csv=DEFAULT_LABELS_CSV,
    run_folder=None,
    now=None,
    *,
    min_free_bytes=DEFAULT_MIN_FREE_BYTES,
    disk_usage_fn=None,
    exchange_economics_snapshot_path=None,
    exchange_economics_platform=exchange_economics.DEFAULT_PLATFORM,
    exchange_economics_required=None,
):
    now = utc_now(now)
    folders = [Path(run_folder)] if run_folder else taker_run_folders(runs_root, target_date=target_date)
    payloads = [
        finalize_taker_run(
            folder,
            labels_csv=labels_csv,
            now=now,
            min_free_bytes=min_free_bytes,
            disk_usage_fn=disk_usage_fn,
            exchange_economics_snapshot_path=exchange_economics_snapshot_path,
            exchange_economics_platform=exchange_economics_platform,
            exchange_economics_required=exchange_economics_required,
        )
        for folder in folders
    ]
    return {
        "schema_version": FINALIZATION_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "target_date": ensure_date(target_date).isoformat() if target_date else None,
        "run_count": len(payloads),
        "runs": [
            {
                "run_id": payload.get("run_id"),
                "target_date": payload.get("target_date"),
                "run_folder": payload.get("run_folder"),
                "settled_pnl_path": payload.get("settled_pnl_path"),
                "settled_report_path": payload.get("settled_report_path"),
                "net_pnl_usdc": (payload.get("summary") or {}).get("net_pnl_usdc"),
                "settled_order_count": (payload.get("summary") or {}).get("settled_order_count"),
                "unsettled_order_count": (payload.get("summary") or {}).get("unsettled_order_count"),
                "reconciliation_status": (payload.get("reconciliation") or {}).get("status"),
            }
            for payload in payloads
        ],
    }

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
