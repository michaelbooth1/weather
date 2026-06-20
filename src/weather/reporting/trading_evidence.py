"""Summaries for market-making and taker paper trading evidence."""

from __future__ import annotations

import json
from pathlib import Path

from weather.paths import data_path


DEFAULT_DATA_ROOT = data_path()
DEFAULT_MM_RUNS_ROOT = DEFAULT_DATA_ROOT / "mm_runs"
DEFAULT_TAKER_RUNS_ROOT = DEFAULT_DATA_ROOT / "taker_runs"
TAKER_QUALITY_MIN_ROLLING_RUNS = 5
TAKER_QUALITY_MIN_FILLS = 100
TAKER_QUALITY_MIN_NET_PNL_USDC = 0.0
COUNTABLE_MM_EVIDENCE_MODE = "active_day_live_forward"


def _read_json(path):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _latest_run_summary(root):
    root = Path(root)
    candidates = sorted(root.glob("*/*/run_summary.json"))
    if not candidates:
        return None, None
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return latest, _read_json(latest)


def _all_run_summaries(root):
    rows = []
    for path in sorted(Path(root).glob("*/*/run_summary.json")):
        payload = _read_json(path)
        if payload:
            rows.append((path, payload))
    return rows


def _float_value(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_value(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _settled_taker_payload(summary_path):
    if not summary_path:
        return None
    return _read_json(Path(summary_path).with_name("settled_pnl.json"))


def _evidence_class(payload, class_name):
    gate = payload.get("live_forward_gate") or {}
    evidence = gate.get("evidence") or {}
    return evidence.get(class_name) or {}


def summarize_market_making_run(path, payload):
    if not payload:
        return {"exists": False}
    cumulative = payload.get("cumulative") or {}
    live_gate = payload.get("live_forward_gate") or {}
    gate_summary = live_gate.get("summary") or {}
    evidence_mode = payload.get("evidence_mode")
    evidence_mode_reason = (
        payload.get("evidence_mode_reason")
        or gate_summary.get("evidence_mode_reason")
        or ((live_gate.get("evidence_mode_gate") or {}).get("detail"))
    )
    countable_mode = evidence_mode == COUNTABLE_MM_EVIDENCE_MODE
    countable_all_markets = bool(payload.get("counts_toward_live_forward_gate"))
    return {
        "exists": True,
        "path": str(path),
        "run_folder": payload.get("run_folder"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "mode": payload.get("mode"),
        "evidence_mode": evidence_mode,
        "evidence_mode_reason": evidence_mode_reason,
        "preflight_status": payload.get("preflight_status"),
        "selected_market_count": len(payload.get("markets") or []),
        "latest_tick_quote_rows": (payload.get("latest_tick") or {}).get("quote_rows"),
        "quote_rows": payload.get("cumulative_quote_permission_rows") or cumulative.get("quote_rows"),
        "paper_posted_lifecycle_legs": (
            payload.get("cumulative_paper_posted_count")
            or cumulative.get("paper_posted_lifecycle_legs")
        ),
        "live_trade_permission_rows": (
            payload.get("cumulative_live_trade_permission_rows")
            or payload.get("live_trade_permission_rows")
            or 0
        ),
        "counts_toward_live_forward_gate": countable_all_markets,
        "countable_mode": countable_mode,
        "countability_status": "COUNTABLE" if countable_all_markets else "NON_COUNTABLE",
        "countability_blockers": [] if countable_all_markets else [
            blocker for blocker in [
                None if countable_mode else f"evidence_mode={evidence_mode}",
                None if live_gate.get("status") in {"PASS", None} else f"live_forward_gate={live_gate.get('status')}",
                None if payload.get("preflight_status") in {"PASS", None} else f"preflight={payload.get('preflight_status')}",
            ]
            if blocker
        ],
        "model_review_evidence": _evidence_class(payload, "model_review_evidence"),
        "paper_trading_evidence": _evidence_class(payload, "paper_trading_evidence"),
        "live_trade_permission_evidence": _evidence_class(payload, "live_trade_permission_evidence"),
    }


def _taker_summary_fields(payload, settled_payload=None):
    summary = payload.get("summary") or {}
    pnl = (payload.get("pnl") or {}).get("summary") or {}
    pnl_payload = payload.get("pnl") or {}
    if settled_payload:
        pnl_payload = settled_payload.get("pnl") or pnl_payload
    strategy_comparison = pnl_payload.get("strategy_comparison") or {}
    by_strategy = pnl_payload.get("by_strategy") or []
    countable_candidate = strategy_comparison.get("countable_strategy_quality_candidate") or {}
    strategy_fields = {
        "strategy_count": strategy_comparison.get("strategy_count") or len(by_strategy),
        "best_strategy_id": strategy_comparison.get("best_strategy_id"),
        "best_strategy_net_pnl_usdc": _float_value(strategy_comparison.get("best_strategy_net_pnl_usdc")),
        "best_settlement_scored_strategy_id": strategy_comparison.get("best_settlement_scored_strategy_id"),
        "best_settlement_scored_net_pnl_usdc": _float_value(
            strategy_comparison.get("best_settlement_scored_net_pnl_usdc")
        ),
        "strategy_quality_candidate_id": countable_candidate.get("strategy_id"),
        "strategy_quality_candidate_status": (
            strategy_comparison.get("countable_strategy_quality_candidate_status")
            or "MISSING_SETTLED_SAMPLE"
        ),
        "strategy_quality_candidate_net_pnl_usdc": _float_value(countable_candidate.get("net_pnl_usdc")),
        "strategy_comparison": strategy_comparison,
        "by_strategy": by_strategy,
    }
    if settled_payload:
        settled_summary = settled_payload.get("summary") or {}
        settled_pnl = (settled_payload.get("pnl") or {}).get("summary") or {}
        reconciliation = settled_payload.get("reconciliation") or {}
        warnings = reconciliation.get("warnings") or []
        return {
            "filled_orders": _int_value(settled_pnl.get("filled_order_count") or settled_summary.get("filled_order_count")),
            "budget_spent_usdc": _float_value(
                settled_pnl.get("budget_spent_usdc") or settled_summary.get("budget_spent_usdc")
            ),
            "net_pnl_usdc": _float_value(settled_pnl.get("net_pnl_usdc") or settled_summary.get("net_pnl_usdc")),
            "mark_to_market_pnl_usdc": _float_value(
                settled_pnl.get("mark_to_market_pnl_usdc") or settled_summary.get("mark_to_market_pnl_usdc")
            ),
            "settlement_pnl_usdc": _float_value(
                settled_pnl.get("settlement_pnl_usdc") or settled_summary.get("settlement_pnl_usdc")
            ),
            "settled_order_count": _int_value(
                settled_pnl.get("settled_order_count") or settled_summary.get("settled_order_count")
            ),
            "unsettled_order_count": _int_value(
                settled_pnl.get("unsettled_order_count") or settled_summary.get("unsettled_order_count")
            ),
            "reason_counts": settled_pnl.get("reason_counts") or settled_summary.get("reason_counts") or {},
            "root_cause_class": summary.get("root_cause_class"),
            "first_failing_gate": summary.get("first_failing_gate"),
            "pnl_source": settled_summary.get("pnl_source") or reconciliation.get("preferred_pnl_source"),
            "settlement_finalization_status": "available",
            "settlement_reconciliation_status": reconciliation.get("status"),
            "settlement_reconciliation_warnings": warnings,
            "settled_pnl_path": settled_payload.get("settled_pnl_path"),
            "settled_report_path": settled_payload.get("settled_report_path"),
            "reported_net_pnl_usdc": settled_summary.get("reported_net_pnl_usdc"),
            "reported_mark_to_market_pnl_usdc": settled_summary.get("reported_mark_to_market_pnl_usdc"),
            "reported_settled_order_count": settled_summary.get("reported_settled_order_count"),
            "reported_unsettled_order_count": settled_summary.get("reported_unsettled_order_count"),
            **strategy_fields,
        }
    pnl_source = (
        "settlement" if _int_value(pnl.get("settled_order_count")) > 0 else
        "mark_to_market" if _float_value(pnl.get("mark_to_market_pnl_usdc")) != 0.0 else
        "unscored"
    )
    return {
        "filled_orders": _int_value(summary.get("cumulative_filled_orders") or pnl.get("filled_order_count")),
        "budget_spent_usdc": _float_value(summary.get("budget_spent_usdc") or pnl.get("budget_spent_usdc")),
        "net_pnl_usdc": _float_value(summary.get("cumulative_net_pnl_usdc") or pnl.get("net_pnl_usdc")),
        "mark_to_market_pnl_usdc": _float_value(pnl.get("mark_to_market_pnl_usdc")),
        "settlement_pnl_usdc": _float_value(pnl.get("settlement_pnl_usdc")),
        "settled_order_count": _int_value(pnl.get("settled_order_count")),
        "unsettled_order_count": _int_value(pnl.get("unsettled_order_count")),
        "reason_counts": pnl.get("reason_counts") or summary.get("reason_counts") or {},
        "root_cause_class": summary.get("root_cause_class"),
        "first_failing_gate": summary.get("first_failing_gate"),
        "pnl_source": pnl_source,
        "settlement_finalization_status": "missing",
        "settlement_reconciliation_status": None,
        "settlement_reconciliation_warnings": [],
        "settled_pnl_path": None,
        "settled_report_path": None,
        "reported_net_pnl_usdc": None,
        "reported_mark_to_market_pnl_usdc": None,
        "reported_settled_order_count": None,
        "reported_unsettled_order_count": None,
        **strategy_fields,
    }


def summarize_taker_run(path, payload, rolling_payloads=None, settled_payload=None):
    if not payload:
        return {"exists": False}
    latest = _taker_summary_fields(payload, settled_payload=settled_payload)
    rolling_payloads = rolling_payloads or []
    rolling_fields = [
        _taker_summary_fields(
            item[0],
            settled_payload=item[1] if isinstance(item, tuple) and len(item) > 1 else None,
        )
        if isinstance(item, tuple) else _taker_summary_fields(item)
        for item in rolling_payloads
    ]
    rolling_runs = len(rolling_fields)
    rolling_fills = sum(row["filled_orders"] for row in rolling_fields)
    rolling_net_pnl = sum(row["net_pnl_usdc"] for row in rolling_fields)
    rolling_mtm_pnl = sum(row["mark_to_market_pnl_usdc"] for row in rolling_fields)
    sample_ready = rolling_runs >= TAKER_QUALITY_MIN_ROLLING_RUNS and rolling_fills >= TAKER_QUALITY_MIN_FILLS
    threshold_pass = sample_ready and rolling_net_pnl >= TAKER_QUALITY_MIN_NET_PNL_USDC
    latest_negative = latest["net_pnl_usdc"] < 0
    if threshold_pass:
        quality_status = "PASS"
    elif sample_ready:
        quality_status = "BLOCK"
    elif latest_negative:
        quality_status = "SAMPLE_PENDING_NEGATIVE_LATEST"
    else:
        quality_status = "SAMPLE_PENDING"
    return {
        "exists": True,
        "path": str(path),
        "run_folder": payload.get("run_folder"),
        "run_id": payload.get("run_id"),
        "target_date": payload.get("target_date"),
        "mode": payload.get("mode"),
        **latest,
        "quality_gate": {
            "status": quality_status,
            "sample_ready": sample_ready,
            "rolling_run_count": rolling_runs,
            "rolling_filled_orders": rolling_fills,
            "rolling_net_pnl_usdc": rolling_net_pnl,
            "rolling_mark_to_market_pnl_usdc": rolling_mtm_pnl,
            "min_rolling_runs": TAKER_QUALITY_MIN_ROLLING_RUNS,
            "min_filled_orders": TAKER_QUALITY_MIN_FILLS,
            "min_net_pnl_usdc": TAKER_QUALITY_MIN_NET_PNL_USDC,
            "latest_negative": latest_negative,
            "interpretation": (
                "rolling sample clears taker quality thresholds"
                if threshold_pass else
                "rolling sample is large enough but below taker quality thresholds"
                if sample_ready else
                "latest taker P&L is diagnostic only until the rolling sample is large enough"
            ),
        },
    }


def build_trading_evidence_summary(
    mm_runs_root=DEFAULT_MM_RUNS_ROOT,
    taker_runs_root=DEFAULT_TAKER_RUNS_ROOT,
):
    mm_path, mm_payload = _latest_run_summary(mm_runs_root)
    taker_path, taker_payload = _latest_run_summary(taker_runs_root)
    taker_settled_payload = _settled_taker_payload(taker_path)
    taker_payloads = [
        (payload, _settled_taker_payload(path))
        for path, payload in _all_run_summaries(taker_runs_root)
    ]
    return {
        "schema_version": "trading_evidence_summary_v0.1",
        "market_making": summarize_market_making_run(mm_path, mm_payload),
        "taker": summarize_taker_run(
            taker_path,
            taker_payload,
            taker_payloads,
            settled_payload=taker_settled_payload,
        ),
    }
