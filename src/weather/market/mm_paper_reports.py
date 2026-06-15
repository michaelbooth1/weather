"""Report rendering and known-edge map helpers for MM paper scoring."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from .mm_paper_constants import (
        DEFAULT_CONFIG,
        DEFAULT_PROMOTION_REFRESH,
        KNOWN_EDGE_SCHEMA_VERSION,
    )
    from .mm_policy import maybe_float, parse_time
except ImportError:  # pragma: no cover - compatibility-wrapper execution
    from mm_paper_constants import (
        DEFAULT_CONFIG,
        DEFAULT_PROMOTION_REFRESH,
        KNOWN_EDGE_SCHEMA_VERSION,
    )
    from mm_policy import maybe_float, parse_time


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
    evidence = summary.get("trade_evidence_gaps") or {}
    anti = summary.get("anti_overfit") or {}
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
            ["Quote rows / legs", f"{summary.get('quote_rows')} / {summary.get('quote_legs')}"],
            ["Conservative fills", summary.get("conservative_fills")],
            ["Conservative filled shares", fmt_num(summary.get("conservative_filled_shares"), 3)],
            ["Queue-estimated fill legs", summary.get("queue_estimated_fill_legs")],
            ["Queue-estimated shares", fmt_num(summary.get("queue_estimated_filled_shares"), 3)],
            ["Gate status", summary.get("gate_status")],
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
    lines.extend(["", "## Queue Companion", ""])
    lines.extend(markdown_table(
        ["Status", "Legs"],
        [[key, value] for key, value in sorted((summary.get("queue_status_counts") or {}).items())],
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
    for row in ((payload.get("decisions") or {}).get("markets") or []):
        market_id = row.get("market_id")
        if not market_id:
            continue
        metrics = row.get("metrics") or {}
        records[market_id] = {
            "market_id": market_id,
            "base_permission": promotion_state_from_action(row.get("action"), row.get("verdict")),
            "action": row.get("action"),
            "verdict": row.get("verdict"),
            "reason": row.get("reason"),
            "delta_vs_market": metrics.get("delta_vs_market"),
            "candidate_brier": metrics.get("candidate_brier"),
            "market_brier": metrics.get("market_brier"),
            "candidate_days": row.get("candidate_days"),
            "settled_days_in_corpus": row.get("settled_days_in_corpus"),
            "market_evidence_ok": (finite_float(metrics.get("delta_vs_market"), 1.0) or 1.0) <= 0.0,
        }
    return records, payload


def permission_for_record(base_permission, paper_slice, promotion, paper_summary, config):
    if base_permission == "BLOCK":
        return "no_quote", "promotion_block"
    if base_permission == "SHADOW":
        return "harvest_only", "promotion_shadow"
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


def source_freshness_gap_records(promotion_payload, paper_summary):
    records = []
    slices = ((promotion_payload.get("candidate") or {}).get("slices") or {}).get("by_source_freshness") or []
    for item in slices:
        delta_vs_market = finite_float(item.get("delta_vs_market"))
        if delta_vs_market is None or delta_vs_market <= 0.0:
            continue
        group = item.get("group") or "unknown"
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


def build_known_edge_map(paper_payload, promotion_refresh=DEFAULT_PROMOTION_REFRESH, config=None, now=None):
    config = {**DEFAULT_CONFIG, **(config or {})}
    promotions, promotion_payload = load_promotion_records(promotion_refresh)
    paper_summary = paper_payload.get("summary") or {}
    records = source_freshness_gap_records(promotion_payload, paper_summary)
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
            "source_freshness_rows": (record.get("source_freshness_evidence") or {}).get("n"),
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
        "policy": {
            "block": "BLOCK promotion maps to no_quote.",
            "shadow": "SHADOW promotion maps to harvest_only.",
            "pass": "PASS promotion needs positive conservative paper markouts before edge_research and 14 locked live-forward days before edge_allowed.",
            "edge_allowed_disabled_when_market_gap_open": True,
        },
        "summary": {
            "record_count": len(records),
            "permission_counts": dict(sorted(counts.items())),
            "active_model_gap_cell_count": len(active_gap_cells),
            "promotion_market_count": len(promotions),
            "paper_fill_count": paper_summary.get("conservative_fills", 0),
        },
        "records": records,
        "active_model_gap_cells": active_gap_cells,
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
        lines.extend(["", "## Source Freshness Gap Cells", ""])
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
