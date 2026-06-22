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
    event_gate = summary.get("event_gate_score") or {}
    clob_recon = summary.get("clob_recon") or {}
    live_forward_evidence = summary.get("per_market_live_forward_evidence") or {}
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
            ["Excluded run folders", summary.get("excluded_run_folders")],
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
