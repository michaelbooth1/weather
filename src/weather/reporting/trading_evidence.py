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


def _taker_summary_fields(payload):
    summary = payload.get("summary") or {}
    pnl = (payload.get("pnl") or {}).get("summary") or {}
    return {
        "filled_orders": int(summary.get("cumulative_filled_orders") or pnl.get("filled_order_count") or 0),
        "budget_spent_usdc": float(summary.get("budget_spent_usdc") or pnl.get("budget_spent_usdc") or 0.0),
        "net_pnl_usdc": float(summary.get("cumulative_net_pnl_usdc") or pnl.get("net_pnl_usdc") or 0.0),
        "mark_to_market_pnl_usdc": float(pnl.get("mark_to_market_pnl_usdc") or 0.0),
        "settlement_pnl_usdc": float(pnl.get("settlement_pnl_usdc") or 0.0),
        "settled_order_count": int(pnl.get("settled_order_count") or 0),
        "unsettled_order_count": int(pnl.get("unsettled_order_count") or 0),
        "reason_counts": pnl.get("reason_counts") or summary.get("reason_counts") or {},
        "root_cause_class": summary.get("root_cause_class"),
        "first_failing_gate": summary.get("first_failing_gate"),
    }


def summarize_taker_run(path, payload, rolling_payloads=None):
    if not payload:
        return {"exists": False}
    latest = _taker_summary_fields(payload)
    rolling_payloads = rolling_payloads or []
    rolling_fields = [_taker_summary_fields(item) for item in rolling_payloads]
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
    taker_payloads = [payload for _path, payload in _all_run_summaries(taker_runs_root)]
    return {
        "schema_version": "trading_evidence_summary_v0.1",
        "market_making": summarize_market_making_run(mm_path, mm_payload),
        "taker": summarize_taker_run(taker_path, taker_payload, taker_payloads),
    }
