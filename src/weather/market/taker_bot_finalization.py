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
    pnl_payload = build_pnl_payload(scored_orders, budget_usdc, run_id, target_date, now=now)
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
    final_summary = {
        **(pnl_payload.get("summary") or {}),
        "pnl_source": reconciliation.get("preferred_pnl_source"),
        "reconciliation_status": reconciliation.get("status"),
        "reconciliation_warning_count": len(reconciliation.get("warnings") or []),
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
