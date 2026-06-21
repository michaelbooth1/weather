"""Implementation slice extracted from src/weather/market/taker_bot.py."""

from weather.market.taker_bot_reporting import *  # noqa: F403

# The extracted functions below intentionally resolve globals from the
# previous slice to preserve the original module namespace.

def replay_input_key_payload(row):
    kind, value, value_hi = band_key(row)
    return {
        "target_date": row.get("target_date") or "",
        "market_id": row.get("market_id") or "",
        "event_slug": row.get("event_slug") or "",
        "snapshot_id": row.get("snapshot_id") or "",
        "captured_at_utc": row.get("captured_at_utc") or "",
        "range_label": row.get("range_label") or "",
        "bin_kind": kind or "",
        "bin_value": value,
        "bin_value_hi": value_hi,
        "clob_token_id": row.get("clob_token_id") or row.get("clob_yes_token_id") or "",
        "fair_probability": compact_float(row.get("fair_probability")),
        "best_ask": compact_float(first_present(row, "best_ask", "clob_best_ask")),
    }


def replay_input_key(row):
    return stable_hash(replay_input_key_payload(row), length=24)


def replay_input_rows_from_orders(order_rows):
    by_key = {}
    for row in order_rows or []:
        key = replay_input_key(row)
        if key not in by_key:
            by_key[key] = dict(row)
    return list(by_key.values())


def replay_tick_sort_key(row):
    timestamp = parse_time(first_present(row, "captured_at_utc", "generated_at_utc"))
    return (
        timestamp.isoformat() if timestamp else "",
        row.get("snapshot_id") or "",
        row.get("market_id") or "",
        row.get("event_slug") or "",
    )


def replay_input_ticks(replay_inputs):
    ticks = []
    current_key = None
    current_rows = []
    for row in sorted(replay_inputs or [], key=replay_tick_sort_key):
        key = (
            row.get("captured_at_utc") or row.get("generated_at_utc") or "",
            row.get("snapshot_id") or "",
        )
        if current_key is not None and key != current_key:
            ticks.append(current_rows)
            current_rows = []
        current_key = key
        current_rows.append(row)
    if current_rows:
        ticks.append(current_rows)
    return ticks


def strategy_filled_rows(order_rows, strategy_id):
    return [
        row for row in order_rows or []
        if strategy_id_for_row(row) == strategy_id and str(row.get("order_status") or "").upper() == "FILLED"
    ]


def cumulative_drawdown_usdc(rows):
    ordered = sorted(
        rows or [],
        key=lambda row: (
            row.get("generated_at_utc") or "",
            row.get("captured_at_utc") or "",
            row.get("order_id") or "",
        ),
    )
    cumulative = 0.0
    peak = 0.0
    drawdown = 0.0
    for row in ordered:
        pnl = maybe_float(row.get("net_pnl_usdc"))
        if pnl is None:
            continue
        cumulative += pnl
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return round(drawdown, 6)


def source_mark_sign_flip_count(source_rows, scored_rows, strategy_id):
    source_marks = {}
    for row in source_rows or []:
        if str(row.get("order_status") or "").upper() != "FILLED":
            continue
        mark = maybe_float(row.get("mark_pnl_usdc"))
        if mark is None and row.get("pnl_source") == "mark_to_market":
            mark = maybe_float(row.get("net_pnl_usdc"))
        if mark is not None:
            source_marks[replay_input_key(row)] = mark
    count = 0
    for row in strategy_filled_rows(scored_rows, strategy_id):
        mark = source_marks.get(replay_input_key(row))
        settled = maybe_float(first_present(row, "settlement_pnl_usdc", "net_pnl_usdc"))
        if mark is not None and settled is not None and mark * settled < 0:
            count += 1
    return count


def strategy_concentration_summary(rows, strategy_id):
    filled = strategy_filled_rows(rows, strategy_id)
    by_market = defaultdict(float)
    by_token = defaultdict(float)
    by_cluster = defaultdict(float)
    by_opinion = Counter()
    total = 0.0
    low_tail = 0.0
    for row in filled:
        spent = maybe_float(row.get("total_spent_usdc")) or 0.0
        total += spent
        by_market[row.get("market_id") or "unknown"] += spent
        by_token[row.get("clob_token_id") or row.get("order_id") or "unknown"] += spent
        by_cluster[row.get("adjacent_bin_cluster_key") or adjacent_bin_cluster_key(row)] += spent
        by_opinion[independent_opinion_key(row)] += 1
        if bool_value(row.get("low_price_tail"), False):
            low_tail += spent
    top_market_id, top_market_spent = max(by_market.items(), key=lambda item: item[1], default=("", 0.0))
    top_token_id, top_token_spent = max(by_token.items(), key=lambda item: item[1], default=("", 0.0))
    top_cluster_key, top_cluster_spent = max(by_cluster.items(), key=lambda item: item[1], default=("", 0.0))
    repeated_opinion_count = sum(max(0, count - 1) for count in by_opinion.values())
    return {
        "spent_usdc": round(total, 6),
        "top_market_id": top_market_id,
        "top_market_spent_usdc": round(top_market_spent, 6),
        "top_market_spend_share": compact_float(top_market_spent / total if total > 0 else 0.0),
        "top_token_id": top_token_id,
        "top_token_spent_usdc": round(top_token_spent, 6),
        "top_token_spend_share": compact_float(top_token_spent / total if total > 0 else 0.0),
        "top_adjacent_cluster_key": top_cluster_key,
        "top_adjacent_cluster_spent_usdc": round(top_cluster_spent, 6),
        "top_adjacent_cluster_spend_share": compact_float(top_cluster_spent / total if total > 0 else 0.0),
        "low_price_tail_spent_usdc": round(low_tail, 6),
        "low_price_tail_spend_share": compact_float(low_tail / total if total > 0 else 0.0),
        "repeated_opinion_count": repeated_opinion_count,
    }


def label_summary_for_target(labels_csv, target_date):
    target = ensure_date(target_date).isoformat()
    rows = [
        row for row in read_csv_rows(labels_csv, attach_diagnostics=True)
        if row.get("target_date") == target
    ]
    quality_counts = Counter(row.get("quality_grade") or "unknown" for row in rows)
    return {
        "target_date": target,
        "label_rows": len(rows),
        "complete_rows": quality_counts.get("complete", 0),
        "partial_rows": quality_counts.get("partial", 0),
        "quality_counts": dict(sorted(quality_counts.items())),
    }


def strategy_gate_for_bakeoff(
    strategy_row,
    scored_rows,
    source_rows,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
):
    strategy_id = strategy_row.get("strategy_id") or DEFAULT_CONTROL_STRATEGY_ID
    filled = strategy_filled_rows(scored_rows, strategy_id)
    settled = int(strategy_row.get("settled_order_count") or 0)
    unsettled = int(strategy_row.get("unsettled_order_count") or 0)
    unscored = int(strategy_row.get("unscored_order_count") or 0)
    clob_failures = int(strategy_row.get("clob_continuity_fail_count") or 0)
    mark_outliers = int(strategy_row.get("mark_sanity_outlier_count") or 0)
    spent = maybe_float(strategy_row.get("spent_usdc")) or 0.0
    net = maybe_float(strategy_row.get("net_pnl_usdc")) or 0.0
    roi = net / spent if spent > 0 else None
    drawdown = cumulative_drawdown_usdc(filled)
    sign_flips = source_mark_sign_flip_count(source_rows, scored_rows, strategy_id)
    concentration = strategy_concentration_summary(scored_rows, strategy_id)
    gates = [
        {
            "name": "min_settled_sample",
            "ok": settled >= int(min_settled_orders),
            "value": settled,
            "threshold": int(min_settled_orders),
        },
        {
            "name": "non_negative_settled_roi",
            "ok": settled >= int(min_settled_orders) and roi is not None and roi >= 0 and net >= 0,
            "value": compact_float(roi),
            "threshold": 0.0,
        },
        {
            "name": "max_drawdown",
            "ok": drawdown <= float(max_drawdown_usdc),
            "value": compact_float(drawdown),
            "threshold": float(max_drawdown_usdc),
        },
        {
            "name": "no_unresolved_orders",
            "ok": unsettled == 0 and unscored == 0,
            "value": unsettled + unscored,
            "threshold": 0,
        },
        {
            "name": "no_resolved_stale_mark_sign_flips",
            "ok": sign_flips == 0,
            "value": sign_flips,
            "threshold": 0,
        },
        {
            "name": "no_clob_continuity_failures",
            "ok": clob_failures == 0,
            "value": clob_failures,
            "threshold": 0,
        },
        {
            "name": "no_mark_sanity_outliers",
            "ok": mark_outliers == 0,
            "value": mark_outliers,
            "threshold": 0,
        },
    ]
    failed = [row["name"] for row in gates if not row["ok"]]
    return {
        "strategy_id": strategy_id,
        "strategy_family": strategy_row.get("strategy_family") or "unknown",
        "status": "PASS" if not failed else "BLOCK",
        "failed_gates": failed,
        "filled_order_count": int(strategy_row.get("filled_order_count") or 0),
        "settled_order_count": settled,
        "unsettled_order_count": unsettled,
        "unscored_order_count": unscored,
        "spent_usdc": compact_float(spent),
        "net_pnl_usdc": compact_float(net),
        "roi": compact_float(roi),
        "max_drawdown_usdc": compact_float(drawdown),
        "stale_mark_sign_flip_count": sign_flips,
        "clob_continuity_fail_count": clob_failures,
        "mark_sanity_outlier_count": mark_outliers,
        "concentration": concentration,
        "gates": gates,
    }


def paired_strategy_comparisons(strategy_rows, promotion_gates, control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID):
    by_strategy = {row.get("strategy_id"): row for row in strategy_rows or []}
    by_gate = {row.get("strategy_id"): row for row in promotion_gates or []}
    control = by_strategy.get(control_strategy_id) or {}
    control_spent = maybe_float(control.get("spent_usdc")) or 0.0
    control_net = maybe_float(control.get("net_pnl_usdc")) or 0.0
    control_roi = control_net / control_spent if control_spent > 0 else None
    comparisons = []
    for row in strategy_rows or []:
        strategy_id = row.get("strategy_id")
        if strategy_id == control_strategy_id:
            continue
        spent = maybe_float(row.get("spent_usdc")) or 0.0
        net = maybe_float(row.get("net_pnl_usdc")) or 0.0
        roi = net / spent if spent > 0 else None
        comparisons.append({
            "control_strategy_id": control_strategy_id,
            "candidate_strategy_id": strategy_id,
            "candidate_strategy_family": row.get("strategy_family") or "unknown",
            "control_status": (by_gate.get(control_strategy_id) or {}).get("status"),
            "candidate_status": (by_gate.get(strategy_id) or {}).get("status"),
            "control_net_pnl_usdc": compact_float(control_net),
            "candidate_net_pnl_usdc": compact_float(net),
            "delta_net_pnl_usdc": compact_float(net - control_net),
            "control_roi": compact_float(control_roi),
            "candidate_roi": compact_float(roi),
            "delta_roi": compact_float(roi - control_roi) if roi is not None and control_roi is not None else None,
            "control_filled_order_count": int(control.get("filled_order_count") or 0),
            "candidate_filled_order_count": int(row.get("filled_order_count") or 0),
            "control_spent_usdc": compact_float(control_spent),
            "candidate_spent_usdc": compact_float(spent),
        })
    return comparisons


def render_bakeoff_report(payload):
    summary = payload.get("summary") or {}
    pnl = payload.get("pnl") or {}
    strategies = pnl.get("by_strategy") or []
    gates = payload.get("promotion_gates") or []
    comparisons = payload.get("paired_comparisons") or []
    blockers = payload.get("blockers") or []
    gate_by_strategy = {row.get("strategy_id"): row for row in gates}
    lines = [
        "# Settlement-Scored Taker Strategy Bakeoff",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Source run: `{payload.get('source_run_id')}`",
        f"Target date: `{payload.get('target_date')}`",
        f"Input orders: `{payload.get('input_orders_path')}`",
        f"Labels: `{payload.get('labels_csv')}`",
        "",
        "## Summary",
        "",
    ]
    lines.extend(markdown_table(
        ["Metric", "Value"],
        [
            ["Strategy count", summary.get("strategy_count")],
            ["Replay input rows", summary.get("replay_input_rows")],
            ["Replay ticks", summary.get("replay_tick_count")],
            ["Scored order rows", summary.get("scored_order_rows")],
            ["Label rows for date", (payload.get("label_summary") or {}).get("label_rows")],
            ["Blockers", len(blockers)],
        ],
    ))
    if blockers:
        lines.extend(["", "## Blockers", ""])
        lines.extend(markdown_table(
            ["Code", "Detail"],
            [[row.get("code"), row.get("detail")] for row in blockers],
        ))
    lines.extend(["", "## Strategy Results", ""])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Family",
            "Filled",
            "Settled",
            "Unresolved",
            "Expected P&L",
            "Risk-Adj Exp P&L",
            "Net P&L",
            "ROI",
            "Drawdown",
            "Tail Spent",
            "Top Market Share",
            "Gate",
        ],
        [
            [
                row.get("strategy_id"),
                row.get("strategy_family"),
                row.get("filled_order_count"),
                row.get("settled_order_count"),
                row.get("unsettled_order_count"),
                fmt_num(row.get("expected_pnl_usdc"), 4),
                fmt_num(row.get("risk_adjusted_expected_pnl_usdc"), 4),
                fmt_num(row.get("net_pnl_usdc"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("roi"), 4),
                fmt_num((gate_by_strategy.get(row.get("strategy_id")) or {}).get("max_drawdown_usdc"), 4),
                fmt_num(row.get("low_price_tail_spent_usdc"), 2),
                fmt_num(
                    ((gate_by_strategy.get(row.get("strategy_id")) or {}).get("concentration") or {}).get(
                        "top_market_spend_share"
                    ),
                    4,
                ),
                (gate_by_strategy.get(row.get("strategy_id")) or {}).get("status"),
            ]
            for row in strategies
        ],
    ))
    if comparisons:
        lines.extend(["", "## Paired Against Control", ""])
        lines.extend(markdown_table(
            ["Candidate", "Status", "Delta Net P&L", "Delta ROI", "Candidate Spent", "Control Spent"],
            [
                [
                    row.get("candidate_strategy_id"),
                    row.get("candidate_status"),
                    fmt_num(row.get("delta_net_pnl_usdc"), 4),
                    fmt_num(row.get("delta_roi"), 4),
                    fmt_num(row.get("candidate_spent_usdc"), 2),
                    fmt_num(row.get("control_spent_usdc"), 2),
                ]
                for row in comparisons
            ],
        ))
    lines.extend(["", "## Promotion Gates", ""])
    gate_rows = []
    for row in gates:
        gate_rows.append([
            row.get("strategy_id"),
            row.get("status"),
            ", ".join(row.get("failed_gates") or []) or "-",
            row.get("settled_order_count"),
            fmt_num(row.get("net_pnl_usdc"), 4),
            fmt_num(row.get("roi"), 4),
            fmt_num(row.get("max_drawdown_usdc"), 4),
            row.get("stale_mark_sign_flip_count"),
            row.get("clob_continuity_fail_count"),
            row.get("mark_sanity_outlier_count"),
        ])
    lines.extend(markdown_table(
        [
            "Strategy",
            "Status",
            "Failed Gates",
            "Settled",
            "Net P&L",
            "ROI",
            "Drawdown",
            "Sign Flips",
            "CLOB Fails",
            "Mark Outliers",
        ],
        gate_rows,
    ))
    lines.append("")
    return "\n".join(lines)


def run_taker_strategy_bakeoff(
    run_folder,
    labels_csv=DEFAULT_LABELS_CSV,
    strategies=DEFAULT_BAKEOFF_STRATEGIES,
    budget_usdc=None,
    out_json=None,
    out_report=None,
    now=None,
    experiment_id=None,
    config=None,
    min_settled_orders=DEFAULT_BAKEOFF_MIN_SETTLED_ORDERS,
    max_drawdown_usdc=DEFAULT_BAKEOFF_MAX_DRAWDOWN_USDC,
):
    now = utc_now(now)
    run_folder = Path(run_folder)
    labels_csv = Path(labels_csv)
    input_orders_path = run_folder / "orders_long.csv"
    source_rows = read_order_rows(input_orders_path)
    replay_inputs = replay_input_rows_from_orders(source_rows)
    run_config = read_json(run_folder / "run_config.json", {}) or {}
    source_summary = read_json(run_folder / "run_summary.json", {}) or {}
    target = ensure_date(
        run_config.get("target_date")
        or source_summary.get("target_date")
        or (source_rows[0].get("target_date") if source_rows else None)
        or run_folder.parent.name
    )
    source_run_id = (
        run_config.get("run_id")
        or source_summary.get("run_id")
        or (source_rows[0].get("run_id") if source_rows else None)
        or run_folder.name
    )
    base_config = {
        **DEFAULT_CONFIG,
        **(run_config.get("policy_config") or {}),
        **(config or {}),
    }
    budget = float(
        budget_usdc
        if budget_usdc is not None
        else run_config.get("budget_usdc")
        or ((source_summary.get("summary") or {}).get("budget_usdc"))
        or 100.0
    )
    strategy_specs = selected_strategy_specs(strategies, base_config=base_config)
    strategy_ids = [row["strategy_id"] for row in strategy_specs]
    experiment_id = experiment_id or default_experiment_id(target, strategy_ids)
    bakeoff_run_id = f"{source_run_id}-bakeoff"
    replay_ticks = replay_input_ticks(replay_inputs)
    generated_rows = []
    budget_ledger = []
    for strategy in strategy_specs:
        strategy_existing_fills = []
        for tick_rows in replay_ticks:
            rows, ledger = apply_taker_budget(
                tick_rows,
                strategy_existing_fills,
                strategy.get("budget_usdc") or budget,
                bakeoff_run_id,
                target,
                now,
                strategy["config"],
                strategy=strategy,
                experiment_id=experiment_id,
            )
            strategy_existing_fills.extend(
                row for row in rows
                if str(row.get("order_status") or "").upper() == "FILLED"
            )
            generated_rows.extend(rows)
            budget_ledger.extend(ledger)
    labels = load_settlement_labels(labels_csv)
    scored_rows, score_summary = score_orders_against_labels(generated_rows, labels)
    total_budget_usdc = sum(float(item.get("budget_usdc") or budget) for item in strategy_specs)
    pnl_payload = build_pnl_payload(scored_rows, total_budget_usdc, bakeoff_run_id, target, now=now)
    label_summary = label_summary_for_target(labels_csv, target)
    promotion_gates = [
        strategy_gate_for_bakeoff(
            row,
            scored_rows,
            source_rows,
            min_settled_orders=min_settled_orders,
            max_drawdown_usdc=max_drawdown_usdc,
        )
        for row in pnl_payload.get("by_strategy") or []
    ]
    paired = paired_strategy_comparisons(
        pnl_payload.get("by_strategy") or [],
        promotion_gates,
        control_strategy_id=DEFAULT_CONTROL_STRATEGY_ID,
    )
    blockers = []
    if not source_rows:
        blockers.append({
            "code": "missing_orders_tape",
            "detail": f"No orders_long.csv rows found at {input_orders_path}",
        })
    if label_summary["label_rows"] == 0:
        blockers.append({
            "code": "missing_target_date_labels",
            "detail": f"No settlement labels for {target.isoformat()} in {labels_csv}",
        })
    elif label_summary["complete_rows"] < label_summary["label_rows"]:
        blockers.append({
            "code": "partial_target_date_labels",
            "detail": (
                f"{label_summary['label_rows'] - label_summary['complete_rows']} of "
                f"{label_summary['label_rows']} settlement labels for {target.isoformat()} "
                "are partial-quality labels; do not promote from this bakeoff alone"
            ),
        })
    if score_summary.get("unmatched_filled_orders"):
        blockers.append({
            "code": "unmatched_filled_orders",
            "detail": (
                f"{score_summary['unmatched_filled_orders']} filled replay orders had no settlement label"
            ),
        })
    out_json = Path(out_json) if out_json else run_folder / "strategy_bakeoff.json"
    out_report = Path(out_report) if out_report else run_folder / "strategy_bakeoff.md"
    payload = {
        "schema_version": STRATEGY_BAKEOFF_SCHEMA_VERSION,
        "generated_at_utc": now.isoformat(),
        "run_id": bakeoff_run_id,
        "source_run_id": source_run_id,
        "target_date": target.isoformat(),
        "input_run_folder": str(run_folder),
        "input_orders_path": str(input_orders_path),
        "labels_csv": str(labels_csv),
        "output_json_path": str(out_json),
        "output_report_path": str(out_report),
        "experiment_id": experiment_id,
        "control_strategy_id": DEFAULT_CONTROL_STRATEGY_ID,
        "strategy_ids": strategy_ids,
        "budget_per_strategy_usdc": compact_float(budget),
        "budget_scope": "per_strategy",
        "strategy_registry": strategy_registry_payload(),
        "strategies": [
            {
                key: value
                for key, value in item.items()
                if key not in {"config"}
            }
            for item in strategy_specs
        ],
        "label_summary": label_summary,
        "score_summary": score_summary,
        "summary": {
            "strategy_count": len(strategy_specs),
            "source_order_rows": len(source_rows),
            "replay_input_rows": len(replay_inputs),
            "replay_tick_count": len(replay_ticks),
            "generated_order_rows": len(generated_rows),
            "scored_order_rows": len(scored_rows),
            "promotion_pass_count": sum(1 for row in promotion_gates if row.get("status") == "PASS"),
            "promotion_block_count": sum(1 for row in promotion_gates if row.get("status") != "PASS"),
        },
        "pnl": pnl_payload,
        "promotion_gates": promotion_gates,
        "paired_comparisons": paired,
        "budget_ledger": budget_ledger,
        "blockers": blockers,
    }
    write_json(out_json, payload)
    out_report.parent.mkdir(parents=True, exist_ok=True)
    out_report.write_text(render_bakeoff_report(payload), encoding="utf-8")
    return payload

# Re-export imported dependency names as well because later slices intentionally
# share the original module global namespace while the public facade remains stable.
__all__ = [name for name in globals() if not name.startswith("__")]
