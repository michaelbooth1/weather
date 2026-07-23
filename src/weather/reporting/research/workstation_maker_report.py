"""Aggregation and Markdown rendering for workstation maker research."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


MARKOUT_LABELS = ("1m", "5m", "30m")
ADDITIVE_METRICS = (
    "conservative_fill_count",
    "filled_shares",
    "gross_spread_capture_usdc",
    "markout_1m_usdc",
    "markout_5m_usdc",
    "markout_30m_usdc",
    "adverse_selection_loss_30m_usdc",
    "modeled_flattening_cost_usdc",
    "modeled_flattening_cost_30m_complete_usdc",
    "theoretical_maker_fee_equivalent_usdc",
    "theoretical_maker_rebate_usdc",
    "theoretical_maker_rebate_30m_complete_usdc",
    "net_after_modeled_costs_30m_usdc",
    "net_with_theoretical_rebate_30m_usdc",
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _sum(rows: Sequence[Mapping[str, Any]], key: str) -> float:
    return sum(_finite(row.get(key)) for row in rows)


def _rounded(value: float, digits: int = 9) -> float:
    return round(float(value), digits)


def summarize_quote_run_classes(
    day_rows: Sequence[Mapping[str, Any]],
    diagnostics: Sequence[Mapping[str, Any]],
    *,
    tune_end: str,
) -> dict[str, Any]:
    """Keep forward, drill, and proof evidence in distinct pools."""

    classes = sorted({str(row["run_class"]) for row in diagnostics})
    class_rows = []
    for run_class in classes:
        rows = [row for row in day_rows if row.get("run_class") == run_class]
        runs = [row for row in diagnostics if row.get("run_class") == run_class]
        item = {
            "run_class": run_class,
            "run_count": len(runs),
            "market_days": len(rows),
            "target_dates": sorted({str(row["target_date"]) for row in rows}),
            "quote_rows": int(_sum(rows, "quote_rows")),
            "quote_permission_rows": int(_sum(rows, "quote_permission_rows")),
            "quote_legs": int(_sum(rows, "quote_legs")),
            "validated_ws_market_days": sum(
                str(row.get("coverage_status") or "").startswith("validated_ws")
                for row in rows
            ),
            "no_valid_ws_trade_tape_market_days": sum(
                row.get("coverage_status") == "no_valid_ws_trade_tape"
                for row in rows
            ),
        }
        for metric in ADDITIVE_METRICS:
            value = _sum(rows, metric)
            item[metric] = (
                int(value) if metric == "conservative_fill_count" else _rounded(value)
            )
        for label in MARKOUT_LABELS:
            item[f"markout_{label}_complete_fill_count"] = int(
                _sum(rows, f"markout_{label}_complete_fill_count")
            )
        class_rows.append(item)
    primary = next(
        (row for row in class_rows if row["run_class"] == "primary_forward"), None
    )
    primary_holdout_dates = [
        date for date in (primary or {}).get("target_dates", []) if date > tune_end
    ]
    return {
        "classes": class_rows,
        "pooling_rule": "primary_forward is headline; drills and proofs remain separate",
        "primary_quote_policy_holdout_gate": {
            "status": "BLOCK",
            "reason": "approved recorded quote runs do not provide an independent locked holdout",
            "primary_holdout_dates": primary_holdout_dates,
        },
        "actual_rebate_payout_available": False,
        "actual_liquidity_reward_payout_available": False,
    }


def summarize_ws_validation(
    diagnostics: Sequence[Mapping[str, Any]], *, books_only_folders: int
) -> dict[str, Any]:
    event_types: Counter[str] = Counter()
    for row in diagnostics:
        event_types.update(row.get("event_types") or {})
    unknown = sum(int(row.get("unknown_ws_event_rows") or 0) for row in diagnostics)
    invalid_binding = sum(
        int(row.get("invalid_event_slug_rows") or 0) for row in diagnostics
    )
    missing_time = sum(
        int(row.get("missing_received_at_rows") or 0) for row in diagnostics
    )
    return {
        "status": (
            "PASS" if not unknown and not invalid_binding and not missing_time else "BLOCK"
        ),
        "validated_market_days": len(diagnostics),
        "books_only_market_days_excluded_from_toxicity": int(books_only_folders),
        "total_ws_rows": sum(event_types.values()),
        "event_type_counts": dict(sorted(event_types.items())),
        "price_change_rows_not_treated_as_trades": event_types.get("price_change", 0),
        "explicit_last_trade_price_rows": event_types.get("last_trade_price", 0),
        "sized_explicit_last_trade_price_rows": sum(
            int(row.get("sized_last_trade_price_rows") or 0) for row in diagnostics
        ),
        "side_supported_explicit_last_trade_price_rows": sum(
            int(row.get("side_supported_last_trade_price_rows") or 0)
            for row in diagnostics
        ),
        "unknown_ws_event_rows": unknown,
        "invalid_event_slug_rows": invalid_binding,
        "missing_received_at_rows": missing_time,
        "trade_event_contract": "last_trade_price",
    }


def summarize_selected_holdout_fills(
    fills: Sequence[Mapping[str, Any]],
    *,
    selected_policy_id: str | None,
    tune_end: str,
) -> dict[str, Any]:
    """Post-hoc loss decomposition; never used to select another policy."""

    selected = [
        row
        for row in fills
        if selected_policy_id
        and row.get("policy_id") == selected_policy_id
        and str(row.get("target_date") or "") > tune_end
    ]

    def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        complete = [row for row in rows if row.get("markout_30m_usdc") is not None]
        return {
            "fills": len(rows),
            "filled_shares": _rounded(_sum(rows, "fill_size")),
            "gross_spread_capture_usdc": _rounded(
                _sum(rows, "gross_spread_capture_usdc")
            ),
            "markout_30m_complete_fills": sum(
                _finite(row.get("markout_30m_usdc"), float("nan"))
                == _finite(row.get("markout_30m_usdc"), float("nan"))
                for row in rows
            ),
            "markout_30m_usdc": _rounded(_sum(rows, "markout_30m_usdc")),
            "adverse_selection_loss_30m_usdc": _rounded(
                _sum(rows, "adverse_selection_loss_30m_usdc")
            ),
            "modeled_flattening_cost_usdc": _rounded(
                _sum(rows, "modeled_flattening_cost_usdc")
            ),
            "modeled_flattening_cost_30m_complete_usdc": _rounded(
                _sum(complete, "modeled_flattening_cost_usdc")
            ),
            "net_after_modeled_costs_30m_usdc": _rounded(
                _sum(rows, "net_after_modeled_costs_30m_usdc")
            ),
            "theoretical_maker_rebate_usdc": _rounded(
                _sum(rows, "theoretical_maker_rebate_usdc")
            ),
        }

    def grouped(key: str) -> list[dict[str, Any]]:
        values: dict[str, list[Mapping[str, Any]]] = {}
        for row in selected:
            values.setdefault(str(row.get(key) or "unknown"), []).append(row)
        return [
            {key: value, **aggregate(rows)}
            for value, rows in sorted(values.items())
        ]

    by_market = grouped("market_id")
    by_side = grouped("passive_side")
    by_date = grouped("target_date")
    return {
        "status": "AVAILABLE" if selected else "NO_SELECTED_HOLDOUT_FILLS",
        "selected_policy_id": selected_policy_id,
        "interpretation": "post-hoc diagnosis only; not a new tuning surface",
        "totals": aggregate(selected),
        "by_market": by_market,
        "by_passive_side": by_side,
        "worst_fleet_dates": sorted(
            by_date,
            key=lambda row: row["net_after_modeled_costs_30m_usdc"],
        )[:5],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reconcile_historical_reports(
    paths: Sequence[str | Path], *, current_explicit_quote_fills: int
) -> dict[str, Any]:
    reports = []
    for raw_path in paths:
        path = Path(raw_path).resolve()
        if not path.is_file():
            reports.append({"path": str(path), "exists": False})
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        summary = payload.get("summary") or {}
        stat = path.stat()
        reports.append(
            {
                "path": str(path),
                "exists": True,
                "file": {
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "sha256": _sha256_file(path),
                },
                "schema_version": payload.get("schema_version"),
                "generated_at_utc": payload.get("generated_at_utc"),
                "run_folders": summary.get("run_folders"),
                "quote_rows": summary.get("quote_rows"),
                "quote_permission_rows": summary.get("quote_permission_rows"),
                "quote_legs": summary.get("quote_legs"),
                "reported_conservative_fills": summary.get("conservative_fills"),
                "reported_conservative_filled_shares": summary.get(
                    "conservative_filled_shares"
                ),
                "latest_covered_active_day": summary.get(
                    "latest_covered_active_day"
                ),
                "gate_status": summary.get("gate_status"),
                "fill_evidence_completeness_status": summary.get(
                    "fill_evidence_completeness_status"
                ),
                "exchange_economics_gate_status": summary.get(
                    "exchange_economics_gate_status"
                ),
                "actual_payout_evidence": summary.get("actual_payout_evidence"),
                "clob_recon_exists": bool((payload.get("clob_recon") or {}).get("exists")),
            }
        )
    return {
        "reports": reports,
        "current_approved_run_explicit_trade_fill_count": int(
            current_explicit_quote_fills
        ),
        "comparability": (
            "not like-for-like: historical reports use different run selections and the "
            "legacy scorer's tape loader does not require event_type=last_trade_price"
        ),
        "legacy_method_warning": (
            "Historical conservative-fill counts cannot establish toxicity under the "
            "current contract because priced price_change rows were admissible to the "
            "legacy trade loader; this warning does not assert every historical fill was false."
        ),
        "current_method": (
            "Only normalized WebSocket rows explicitly labeled last_trade_price, with "
            "recorded positive size, can trigger strict-through fills."
        ),
    }


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    def cell(value: Any) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:.6f}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
        *[
            "| " + " | ".join(cell(value) for value in row) + " |"
            for row in rows
        ],
    ]


def render_report(payload: Mapping[str, Any]) -> str:
    coverage = payload["coverage"]
    ws = payload["ws_validation"]["summary"]
    synthetic = payload["synthetic_policy_evidence"]
    lines = [
        "# Workstation Maker Research",
        "",
        f"Generated: `{payload['generated_at_utc']}`",
        "",
        f"Decision: **{synthetic['decision']}**. This is research-only evidence; no serving, promotion, or live-trading change is authorized.",
        "",
        "## Evidence boundary",
        "",
        "Only normalized WebSocket rows explicitly labeled `last_trade_price` are trade evidence. `price_change` rows are book updates, never fills or toxicity observations. Reconstruction is one market-day at a time; approved maker folders are classified before scoring, and drills/proofs are not pooled into the forward headline.",
        "",
        "Gross spread, adverse-selection markouts, flattening cost, and theoretical rebate fields are separate. Actual maker-rebate and liquidity-reward payouts are unavailable, so no realized incentive claim is made.",
        "",
        "## Coverage and protocol validation",
        "",
    ]
    lines += _markdown_table(
        ["Field", "Value"],
        [
            ["Coverage-audited WS market-days", coverage["ws_market_days"]],
            ["WS date range", f"{coverage['coverage_start']} to {coverage['coverage_end']}"],
            ["Books-only market-days", coverage["books_only_market_days"]],
            ["Books-only date range", f"{coverage['books_only_start']} to {coverage['books_only_end']}"],
            ["WS validation", ws["status"]],
            ["Total WS rows", ws["total_ws_rows"]],
            ["Book events", ws["event_type_counts"].get("book", 0)],
            ["Price changes excluded as trades", ws["price_change_rows_not_treated_as_trades"]],
            ["Explicit last-trade events", ws["explicit_last_trade_price_rows"]],
            ["Sized explicit last-trade events", ws["sized_explicit_last_trade_price_rows"]],
            ["Unknown event rows", ws["unknown_ws_event_rows"]],
        ],
    )
    lines += [
        "",
        "The books-only window supports spread/depth inspection only and is excluded from fill/toxicity claims.",
        "",
        "## Spread, depth, and explicit-trade markouts",
        "",
    ]
    micro = payload["microstructure"]
    lines += _markdown_table(
        ["Split", "Fleet dates", "Market-days", "Mean spread", "Top depth", "Depth 1%", "Matched trades"],
        [
            [
                split,
                micro[split]["fleet_dates"],
                micro[split]["market_days"],
                micro[split]["book_metrics"]["mean_spread"]["equal_fleet_date"]["mean"],
                micro[split]["book_metrics"]["mean_top_depth"]["equal_fleet_date"]["mean"],
                micro[split]["book_metrics"]["mean_depth_1pct"]["equal_fleet_date"]["mean"],
                micro[split]["book_matched_explicit_trade_rows"],
            ]
            for split in ("tune", "holdout")
        ],
    )
    lines += ["", "Fleet-date clustered explicit-trade markouts (negative is adverse to the inferred passive side):", ""]
    mark_rows = []
    for split in ("tune", "holdout"):
        for label in MARKOUT_LABELS:
            item = micro[split]["trade_markouts"][f"markout_{label}_per_share"]
            ci = item["equal_supported_fleet_date"]
            mark_rows.append(
                [split, label, item["explicit_trade_rows"], ci["n"], ci["mean"], ci["ci_low"], ci["ci_high"], f"{ci['positive_count']}/{ci['negative_count']}/{ci['tie_count']}"]
            )
    lines += _markdown_table(
        ["Split", "Horizon", "Trades", "Supported dates", "Mean", "CI low", "CI high", "+/-/tie"],
        mark_rows,
    )
    lines += [
        "",
        "## Synthetic quoting policies",
        "",
        "Policies use a 60-second quote lifetime, five-share displayed size, and strict trade-through against explicit sized last trades. Queue priority is not modeled, so these are bounded counterfactuals, not executable P&L.",
        "",
        "Absolute economics are not additive: the future-midpoint markout already contains entry spread. `Net` uses only 30-minute-complete fills and equals their markout less their net-basis flattening cost. All-fill flattening cost is separate. Theoretical rebate is excluded from selection.",
        "",
    ]
    economic_rows = []
    for split in ("tune", "holdout"):
        for row in synthetic[split]["policy_summaries"]:
            totals = row["totals"]
            economic_rows.append(
                [split, row["policy_id"], totals["conservative_fill_count"], row["markout_30m_complete_fill_count"], totals["gross_spread_capture_usdc"], totals["markout_30m_usdc"], totals["adverse_selection_loss_30m_usdc"], totals["modeled_flattening_cost_usdc"], totals["modeled_flattening_cost_30m_complete_usdc"], totals["net_after_modeled_costs_30m_usdc"], totals["theoretical_maker_rebate_usdc"]]
            )
    lines += _markdown_table(
        ["Split", "Policy", "Fills", "30m fills", "Gross spread", "30m markout", "Adverse loss", "All-fill flatten", "Net-basis flatten", "Net", "Theory rebate"],
        economic_rows,
    )
    lines += ["", "Tune paired deltas versus `at_touch` (theoretical incentives excluded):", ""]
    tune_rows = []
    for row in synthetic["tune"]["paired_vs_baseline"]:
        ci = row["fleet_date_cluster_delta"]
        tune_rows.append(
            [row["variant_policy_id"], row["variant_complete_fills"], row["variant_active_fill_fleet_dates"], ci["mean"], ci["ci_low"], ci["ci_high"], f"{ci['positive_count']}/{ci['negative_count']}/{ci['tie_count']}", row["support_status"]]
        )
    lines += _markdown_table(
        ["Variant", "30m fills", "Active dates", "Mean delta", "CI low", "CI high", "+/-/tie", "Support"],
        tune_rows,
    )
    lines += ["", f"Tune selection: **{synthetic['selection']['status']}**; selected `{synthetic['selection']['selected_policy_id'] or 'none'}`.", ""]
    holdout = synthetic["holdout"].get("selected_vs_baseline")
    if holdout:
        ci = holdout["fleet_date_cluster_delta"]
        lines += _markdown_table(
            ["Selected", "Paired dates", "30m fills", "Mean delta", "CI low", "CI high", "+/-/tie", "Gate"],
            [[holdout["variant_policy_id"], holdout["paired_fleet_dates"], holdout["variant_complete_fills"], ci["mean"], ci["ci_low"], ci["ci_high"], f"{ci['positive_count']}/{ci['negative_count']}/{ci['tie_count']}", holdout["confirmation_gate"]["status"]]],
        )
    else:
        lines.append("No policy entered the locked holdout because the tune gate failed closed.")
    posthoc = synthetic.get("posthoc_holdout_diagnostics") or {}
    if posthoc.get("status") == "AVAILABLE":
        lines += [
            "",
            "Post-hoc holdout loss decomposition by market (diagnostic only; not a new tuning surface):",
            "",
        ]
        lines += _markdown_table(
            ["Market", "Fills", "30m fills", "Gross spread", "30m markout", "Adverse loss", "All-fill flatten", "Net-basis flatten", "Net"],
            [
                [row["market_id"], row["fills"], row["markout_30m_complete_fills"], row["gross_spread_capture_usdc"], row["markout_30m_usdc"], row["adverse_selection_loss_30m_usdc"], row["modeled_flattening_cost_usdc"], row["modeled_flattening_cost_30m_complete_usdc"], row["net_after_modeled_costs_30m_usdc"]]
                for row in posthoc.get("by_market") or []
            ],
        )
    lines += ["", "## Approved recorded quote runs", ""]
    quote_rows = []
    for row in payload["recorded_quote_evidence"]["summary"]["classes"]:
        quote_rows.append(
            [row["run_class"], row["run_count"], row["market_days"], row["validated_ws_market_days"], row["quote_permission_rows"], row["quote_legs"], row["conservative_fill_count"], row["markout_30m_complete_fill_count"], row["net_after_modeled_costs_30m_usdc"]]
        )
    lines += _markdown_table(
        ["Class", "Runs", "Market-days", "WS days", "Permitted rows", "Legs", "Explicit fills", "30m fills", "Net"],
        quote_rows,
    )
    quote_gate = payload["recorded_quote_evidence"]["summary"]["primary_quote_policy_holdout_gate"]
    lines += ["", f"Recorded quote holdout gate: **{quote_gate['status']}** - {quote_gate['reason']}.", "", "## Reconciliation with June/July reports", ""]
    history_rows = [
        [Path(row["path"]).name, row.get("generated_at_utc"), row.get("quote_rows"), row.get("quote_legs"), row.get("reported_conservative_fills"), row.get("gate_status"), row.get("exchange_economics_gate_status")]
        for row in payload["historical_reconciliation"]["reports"]
    ]
    lines += _markdown_table(
        ["Report", "Generated", "Quote rows", "Quote legs", "Reported fills", "Gate", "Economics"],
        history_rows,
    )
    lines += [
        "",
        payload["historical_reconciliation"]["legacy_method_warning"],
        "",
        "## Blocking and negative evidence",
        "",
        "- Explicit trades are sparse relative to book updates; unsupported days remain zeros or are excluded from toxicity intervals, as labeled.",
        "- Strict trade-through avoids optimistic touch fills but does not reconstruct queue priority, between-capture cancellations, latency, inventory constraints, or settlement P&L.",
        "- Actual rebate and liquidity-reward payouts are absent. Repository fee/rebate defaults are theoretical and stale, and are excluded from selection.",
        "- Approved recorded quote runs furnish no independent held-out forward period. Drills and proofs are not promoted into the primary pool.",
        "- July 12-21 has order-book summaries but no normalized/raw WS tapes, so it cannot support fills or adverse-selection claims.",
        "- Any positive mean that fails minimum support or whose fleet-date interval touches zero is a no-go.",
        "",
        "## Reproducibility",
        "",
        f"Input manifest hash: `{payload['manifest_hash']}`. Bootstrap seed: `{payload['bootstrap']['seed']}`; replicates: `{payload['bootstrap']['replicates']}`.",
        "",
        "All outputs are scratch artifacts. Root `data/` was read-only.",
    ]
    return "\n".join(lines) + "\n"
