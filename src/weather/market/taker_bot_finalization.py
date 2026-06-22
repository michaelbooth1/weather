"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_bakeoff import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

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
    lines.extend(["", "## P&L", ""])
    lines.extend(markdown_table(
        ["Component", "USDC"],
        [
            ["Gross cost", fmt_num(pnl_summary.get("gross_cost_usdc"), 4)],
            ["Fees", fmt_num(pnl_summary.get("fees_usdc"), 4)],
            ["Settlement payout", fmt_num(pnl_summary.get("settlement_payout_usdc"), 4)],
            ["Settlement P&L", fmt_num(pnl_summary.get("settlement_pnl_usdc"), 4)],
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


def _canary_gate_status(active_id, active_gate, bakeoff, run_config):
    label_summary = (bakeoff or {}).get("label_summary") or {}
    blockers = _blocker_codes(bakeoff)
    policy = run_config.get("policy_config") or {}
    canary = run_config.get("active_strategy_canary") or {}
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
    failed_gates = list((active_gate or {}).get("failed_gates") or [])
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
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_collect_complete_labels",
            "reason": "active canary has no settlement-scored bakeoff yet",
        }
    if not complete_label_gate:
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_until_complete_labels",
            "reason": "active canary has only partial or missing complete-label bakeoff evidence",
        }
    if not sample_gate:
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "candidate_canary",
            "promotion_eligible": False,
            "next_action": "continue_canary_until_minimum_sample",
            "reason": (
                f"active canary has {active_settled} settled orders; "
                f"{min_settled} required before promotion"
            ),
        }
    if (active_gate or {}).get("status") == "PASS":
        return {
            "status": "PASS",
            "active_strategy_lifecycle_status": "promoted_default",
            "promotion_eligible": True,
            "next_action": "promote_default",
            "reason": "active canary has complete-label sample and passed settlement gates",
        }
    return {
        "status": "BLOCK",
        "active_strategy_lifecycle_status": "blocked",
        "promotion_eligible": False,
        "next_action": "rollback_or_block_canary",
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
    canary_decision = None
    if active_lifecycle == "candidate_canary":
        canary_decision = _canary_gate_status(
            active_id,
            gates_by_strategy.get(active_id) or {},
            bakeoff,
            run_config,
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
    return {
        "status": status,
        "active_strategy_id": active_id,
        "active_strategy_lifecycle": active_lifecycle,
        "active_strategy_lifecycle_status": (
            (canary_decision or {}).get("active_strategy_lifecycle_status") or active_lifecycle
        ),
        "promotion_eligible": bool((canary_decision or {}).get("promotion_eligible")),
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
        "canary_failed_gates": (gates_by_strategy.get(active_id) or {}).get("failed_gates") or [],
        "reason": reason,
    }


def finalize_taker_run(run_folder, labels_csv=DEFAULT_LABELS_CSV, now=None):
    run_folder = Path(run_folder)
    order_path = run_folder / "orders_long.csv"
    if not order_path.exists():
        raise FileNotFoundError(f"missing taker orders tape: {order_path}")
    now = utc_now(now)
    run_summary = read_json(run_folder / "run_summary.json", {}) or {}
    daily_pnl = read_json(run_folder / "daily_pnl.json", {}) or {}
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

    labels = load_settlement_labels(labels_csv)
    raw_orders = read_order_rows(order_path)
    scored_orders, label_summary = score_orders_against_labels(raw_orders, labels)
    run_config = read_json(run_folder / "run_config.json", {}) or {}
    pnl_payload = build_pnl_payload(
        scored_orders,
        budget_usdc,
        run_id,
        target_date,
        now=now,
        policy_config=run_config.get("policy_config") or {},
    )
    reported_summary = reported_taker_pnl_summary(run_summary, daily_pnl)
    reconciliation = build_settlement_reconciliation(pnl_payload.get("summary") or {}, reported_summary)
    settled_orders_path = run_folder / "settled_orders_long.csv"
    settled_pnl_path = run_folder / "settled_pnl.json"
    settled_report_path = run_folder / "settled_report.md"
    settled_strategy_summary_path = run_folder / "settled_strategy_summary.json"
    settled_strategy_report_path = run_folder / "settled_strategy_report.md"
    strategy_summary = build_strategy_summary_payload(
        pnl_payload,
        run_config=read_json(run_folder / "run_config.json", {}) or {},
        run_id=run_id,
        target_date=target_date,
        now=now,
    )
    bakeoff = read_json(run_folder / "strategy_bakeoff.json", {}) or {}
    next_gate = next_run_policy_gate(strategy_summary, run_config=run_config, bakeoff=bakeoff)
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
        "settled_orders_path": str(settled_orders_path),
        "settled_report_path": str(settled_report_path),
        "settled_strategy_summary_path": str(settled_strategy_summary_path),
        "settled_strategy_report_path": str(settled_strategy_report_path),
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
        "strategy_summary": strategy_summary,
        "next_run_policy_gate": next_gate,
        "reconciliation": reconciliation,
        "warnings": reconciliation.get("warnings") or [],
    }
    write_csv_rows(settled_orders_path, ORDER_COLUMNS, scored_orders)
    write_json(settled_pnl_path, payload)
    write_json(settled_strategy_summary_path, strategy_summary)
    settled_report_path.write_text(render_settlement_report(payload), encoding="utf-8")
    settled_strategy_report_path.write_text(render_strategy_report(strategy_summary), encoding="utf-8")
    return payload


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
):
    now = utc_now(now)
    folders = [Path(run_folder)] if run_folder else taker_run_folders(runs_root, target_date=target_date)
    payloads = [finalize_taker_run(folder, labels_csv=labels_csv, now=now) for folder in folders]
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
