"""Market-beating objective scoreboard and anti-anchoring gate."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from weather.paths import data_path
from weather.reporting.formatting import fmt_num, fmt_signed, markdown_table
from weather.schema_registry import schema_version


SCHEMA_VERSION = schema_version("market_beating_objective_scoreboard")
DEFAULT_BACKTEST_ROOT = data_path("backtest")
DEFAULT_PROOF_PACKET = DEFAULT_BACKTEST_ROOT / "weather_only_model_proof_packet.json"
DEFAULT_SCORECARD = DEFAULT_BACKTEST_ROOT / "proper_scoring_reliability_scorecard.json"
DEFAULT_RESIDUAL_EDGE = DEFAULT_BACKTEST_ROOT / "market_benchmark_residual_edge.json"
DEFAULT_WINNER_RANK_PARITY = DEFAULT_BACKTEST_ROOT / "winner_rank_parity.json"
DEFAULT_DAILY_PROGRESS = DEFAULT_BACKTEST_ROOT / "daily_progress_latest.json"
DEFAULT_TRADING_EVIDENCE = DEFAULT_BACKTEST_ROOT / "trading_evidence.json"
DEFAULT_JSON_OUT = DEFAULT_BACKTEST_ROOT / "market_beating_objective_scoreboard.json"
DEFAULT_REPORT_OUT = DEFAULT_BACKTEST_ROOT / "market_beating_objective_scoreboard.md"

REQUIRED_INPUTS = {
    "weather_only_model_proof_packet",
    "proper_scoring_reliability_scorecard",
    "market_benchmark_residual_edge",
    "winner_rank_parity",
    "trading_evidence",
}
PASS_STATUSES = {"PASS", "OK", "PROVEN"}


def _utc_iso():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}


def _float(value, default=None):
    if value in (None, ""):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number):
        return default
    return number


def _int(value, default=0):
    number = _float(value)
    if number is None:
        return default
    return int(number)


def _bool_true(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _status(value):
    return str(value or "").strip().upper()


def _is_pass(value):
    return _status(value) in PASS_STATUSES


def _blocker(category, detail, *, source=None, gate=None, lane=None):
    row = {"category": category, "detail": detail}
    if source:
        row["source"] = source
    if gate:
        row["gate"] = gate
    if lane:
        row["lane"] = lane
    return row


def _first_blocker(blockers):
    return (blockers or [{}])[0] if blockers else {}


def _input_record(name, path, payload, *, required=True):
    path = Path(path)
    exists = path.exists()
    return {
        "name": name,
        "path": str(path),
        "required": bool(required),
        "exists": exists,
        "schema_version": payload.get("schema_version"),
        "status": payload.get("status") or ((payload.get("summary") or {}).get("status")),
        "generated_at_utc": payload.get("generated_at_utc"),
    }


def _input_blockers(inputs):
    blockers = []
    for name, row in inputs.items():
        if not row.get("required"):
            continue
        if not row.get("exists") or not row.get("schema_version"):
            blockers.append(_blocker(
                "missing_required_input",
                f"{name} is missing or unreadable",
                source=name,
            ))
    return blockers


def _gate(payload, gate_name):
    gates = payload.get("gates") or []
    if isinstance(gates, dict):
        row = gates.get(gate_name) or {}
        return row if isinstance(row, dict) else {}
    for row in gates:
        if not isinstance(row, dict):
            continue
        if row.get("gate") == gate_name or row.get("name") == gate_name:
            return row
    return {}


def _lane_row(scorecard, lane_name):
    for row in scorecard.get("lanes") or []:
        if isinstance(row, dict) and row.get("lane") == lane_name:
            return row
    section = (scorecard.get("lane_sections") or {}).get(lane_name)
    if isinstance(section, dict):
        return section
    if isinstance(section, list):
        for row in section:
            if isinstance(row, dict) and row.get("lane") == lane_name:
                return row
        return section[0] if section and isinstance(section[0], dict) else {}
    return {}


def _parity_status(parity):
    gate = parity.get("parity_gate") or {}
    summary = parity.get("summary") or {}
    return (
        gate.get("status")
        or summary.get("parity_gate_status")
        or parity.get("status")
    )


def _parity_first_blocker(parity):
    gate = parity.get("parity_gate") or {}
    first = gate.get("first_blocker") or parity.get("first_blocker")
    if isinstance(first, dict):
        return first
    if first:
        return {"detail": str(first), "source": "winner_rank_parity"}
    blockers = gate.get("blockers") or []
    return blockers[0] if blockers else {}


def _daily_baseline_status(daily_progress, proof):
    if daily_progress:
        return (
            daily_progress.get("evidence_independent_baseline_status")
            or daily_progress.get("evidence_frozen_baseline_status")
            or "MISSING"
        )
    proof_daily = (((proof.get("broad_claim") or {}).get("daily_progress") or {}))
    if proof_daily.get("exists"):
        return "PRESENT"
    return "MISSING"


def _lane_contamination(status, checks):
    blockers = [row for row in checks if row.get("status") != "PASS"]
    return {
        "status": "BLOCK" if blockers else status,
        "checks": checks,
        "blocker_count": len(blockers),
        "first_blocker": _first_blocker(blockers),
    }


def _weather_only_decision(proof, scorecard, parity, residual, daily_progress):
    blockers = []
    proof_status = proof.get("status")
    scorecard_status = scorecard.get("status")
    lane_separation = _gate(proof, "weather_only_lane_separation")
    parity_gate_status = _parity_status(parity)
    weather_lane = _lane_row(scorecard, "weather_only")
    market_lane = _lane_row(scorecard, "market_only")
    residual_weather = ((residual.get("settlement_accuracy") or {}).get("weather_only_vs_market") or {})
    weather_brier = _float(weather_lane.get("brier"), _float(residual_weather.get("weather_only_brier")))
    market_brier = _float(market_lane.get("brier"), _float(residual_weather.get("market_only_brier")))
    gap = (
        weather_brier - market_brier
        if weather_brier is not None and market_brier is not None
        else None
    )
    baseline_status = _daily_baseline_status(daily_progress, proof)

    if not _is_pass(scorecard_status):
        blockers.append(_blocker(
            "proper_scoring_not_pass",
            f"proper-scoring scorecard status is {scorecard_status or 'MISSING'}",
            source="proper_scoring_reliability_scorecard",
        ))
    if not _is_pass(proof_status):
        first = proof.get("first_blocker") or "weather-only proof packet is not pass"
        detail = first.get("detail") if isinstance(first, dict) else str(first)
        blockers.append(_blocker(
            "proof_packet_not_pass",
            detail,
            source="weather_only_model_proof_packet",
        ))
    if _status(lane_separation.get("status")) != "PASS":
        blockers.append(_blocker(
            "weather_only_lane_separation_not_pass",
            lane_separation.get("detail") or "weather-only lane separation is not pass",
            source="weather_only_model_proof_packet",
            gate="weather_only_lane_separation",
            lane="weather_only",
        ))
    if _status(parity_gate_status) != "PASS":
        first = _parity_first_blocker(parity)
        blockers.append(_blocker(
            "winner_rank_parity_not_pass",
            first.get("detail") or f"winner-rank parity status is {parity_gate_status or 'MISSING'}",
            source="winner_rank_parity",
            gate="winner_rank_parity_gate",
            lane="weather_only",
        ))
    if gap is None:
        blockers.append(_blocker(
            "weather_market_brier_missing",
            "weather-only and market-only Brier values are required",
            source="proper_scoring_reliability_scorecard",
            lane="weather_only",
        ))
    elif gap >= 0:
        blockers.append(_blocker(
            "weather_only_trails_market",
            f"weather-only Brier trails market by {gap:+.6f}",
            source="proper_scoring_reliability_scorecard",
            lane="weather_only",
        ))
    if baseline_status != "PRESENT":
        blockers.append(_blocker(
            "independent_baseline_missing",
            f"independent or frozen baseline status is {baseline_status}",
            source="daily_progress_latest",
            lane="weather_only",
        ))

    contamination = _lane_contamination(
        "PASS",
        [
            {
                "check": "weather_only_lane_separation",
                "status": "PASS" if _status(lane_separation.get("status")) == "PASS" else "BLOCK",
                "detail": lane_separation.get("detail") or "weather-only lane separation must pass",
            },
            {
                "check": "scorecard_uses_weather_only_lane",
                "status": "PASS" if weather_lane.get("lane") == "weather_only" else "BLOCK",
                "detail": "headline weather-only evidence must come from the weather_only scorecard lane",
            },
            {
                "check": "market_only_is_benchmark",
                "status": "PASS" if market_lane.get("lane") == "market_only" else "BLOCK",
                "detail": "market-only lane is a benchmark, not weather-model proof",
            },
        ],
    )
    status = "PASS" if not blockers and contamination["status"] == "PASS" else "BLOCK"
    return {
        "status": status,
        "counts_toward_headline": status == "PASS",
        "lane": "weather_only",
        "evidence_basis": "weather_only_model_proof_packet+proper_scoring+winner_rank_parity",
        "metrics": {
            "weather_only_brier": weather_brier,
            "market_only_brier": market_brier,
            "weather_minus_market_brier": gap,
            "proof_status": proof_status,
            "proper_scoring_status": scorecard_status,
            "winner_rank_parity_status": parity_gate_status,
            "independent_baseline_status": baseline_status,
        },
        "lane_contamination": contamination,
        "blocker_count": len(blockers),
        "first_blocker": _first_blocker(blockers),
        "blockers": blockers,
    }


def _residual_winning_slices(residual):
    settlement = residual.get("settlement_accuracy") or {}
    weather = settlement.get("weather_only_vs_market") or {}
    rows = []
    aggregate_delta = _float(weather.get("weather_minus_market_brier"))
    aggregate_edge_rows = _int(weather.get("residual_edge_row_count"), 0)
    if aggregate_edge_rows > 0 and aggregate_delta is not None and aggregate_delta < 0:
        rows.append({
            "slice": "aggregate",
            "group": "all",
            "weather_minus_market_brier": aggregate_delta,
            "residual_edge_row_count": aggregate_edge_rows,
            "positive_residual_edge_hit_rate": _float(weather.get("positive_residual_edge_hit_rate")),
        })
    for row in settlement.get("slices") or []:
        if not isinstance(row, dict):
            continue
        delta = _float(row.get("weather_minus_market_brier"))
        edge_rows = _int(row.get("residual_edge_row_count"), 0)
        if edge_rows > 0 and delta is not None and delta < 0:
            rows.append({
                "slice": row.get("slice"),
                "group": row.get("group"),
                "weather_minus_market_brier": delta,
                "residual_edge_row_count": edge_rows,
                "positive_residual_edge_hit_rate": _float(row.get("positive_residual_edge_hit_rate")),
            })
    return rows


def _residual_decision(residual):
    blockers = []
    status_value = residual.get("status")
    summary = residual.get("summary") or {}
    proof_guard = residual.get("proof_guard") or {}
    contract = residual.get("frozen_market_benchmark_contract") or {}
    trading = residual.get("trading_execution") or {}
    trading_summary = trading.get("summary") or {}
    winning_slices = _residual_winning_slices(residual)

    if not _is_pass(status_value):
        blockers.append(_blocker(
            "residual_lane_not_pass",
            f"residual-edge artifact status is {status_value or 'MISSING'}",
            source="market_benchmark_residual_edge",
            lane="residual_edge",
        ))
    if proof_guard.get("counts_toward_weather_model_promotion") is not False:
        blockers.append(_blocker(
            "residual_counts_toward_weather_proof",
            "residual and market-informed evidence must remain blocked from weather-model promotion proof",
            source="market_benchmark_residual_edge",
            gate="proof_guard",
            lane="residual_edge",
        ))
    if not winning_slices:
        blockers.append(_blocker(
            "no_residual_slice_beats_market",
            "no residual disagreement slice has negative weather-minus-market Brier",
            source="market_benchmark_residual_edge",
            lane="residual_edge",
        ))
    if _status(contract.get("status")) != "PASS":
        blockers.append(_blocker(
            "frozen_market_contract_not_pass",
            "frozen CLOB executable-price contract is not pass",
            source="market_benchmark_residual_edge",
            gate="frozen_market_benchmark_contract",
            lane="residual_edge",
        ))
    if _status(trading.get("status")) != "PASS":
        blockers.append(_blocker(
            "residual_trading_execution_not_pass",
            "residual trading execution benchmark is incomplete or blocked",
            source="market_benchmark_residual_edge",
            gate="trading_execution",
            lane="residual_edge",
        ))
    if _bool_true(trading_summary.get("mtm_promotion_allowed")):
        blockers.append(_blocker(
            "mtm_promotion_allowed",
            "mark-to-market evidence cannot count as residual executable edge",
            source="market_benchmark_residual_edge",
            gate="trading_execution",
            lane="residual_edge",
        ))
    if _status(trading_summary.get("promotion_evidence_basis")) not in {"SETTLEMENT_SCORED", ""}:
        blockers.append(_blocker(
            "residual_not_settlement_scored",
            f"residual trading evidence basis is {trading_summary.get('promotion_evidence_basis')}",
            source="market_benchmark_residual_edge",
            gate="trading_execution",
            lane="residual_edge",
        ))

    contamination = _lane_contamination(
        "PASS",
        [
            {
                "check": "residual_not_weather_proof",
                "status": "PASS" if proof_guard.get("counts_toward_weather_model_promotion") is False else "BLOCK",
                "detail": proof_guard.get("detail") or "residual evidence must not satisfy weather-only proof",
            },
            {
                "check": "frozen_executable_price_contract",
                "status": "PASS" if _status(contract.get("status")) == "PASS" else "BLOCK",
                "detail": "residual edge must use executable, fresh, token-mapped CLOB prices",
            },
        ],
    )
    status = "PASS" if not blockers and contamination["status"] == "PASS" else "BLOCK"
    return {
        "status": status,
        "counts_toward_headline": status == "PASS",
        "lane": "residual_edge",
        "evidence_basis": "market_benchmark_residual_edge",
        "metrics": {
            "artifact_status": status_value,
            "summary_weather_minus_market_brier": summary.get("weather_minus_market_brier"),
            "winning_slice_count": len(winning_slices),
            "contract_status": contract.get("status"),
            "trading_execution_status": trading.get("status"),
            "promotion_evidence_basis": trading_summary.get("promotion_evidence_basis"),
            "mtm_promotion_allowed": trading_summary.get("mtm_promotion_allowed"),
        },
        "winning_slices": winning_slices[:20],
        "lane_contamination": contamination,
        "blocker_count": len(blockers),
        "first_blocker": _first_blocker(blockers),
        "blockers": blockers,
    }


def _positive(value):
    number = _float(value)
    return number is not None and number > 0


def _taker_profit(trading):
    taker = trading.get("taker") or {}
    for key in (
        "settlement_scored_net_pnl_usdc",
        "strategy_quality_candidate_net_pnl_usdc",
        "best_settlement_scored_net_pnl_usdc",
        "settlement_pnl_usdc",
    ):
        value = _float(taker.get(key))
        if value is not None:
            return value
    if _status(taker.get("pnl_evidence_status")) == "SETTLEMENT_SCORED":
        return _float(taker.get("net_pnl_usdc"))
    return None


def _taker_market_benchmark_status(taker):
    comparison = taker.get("strategy_comparison") or {}
    return (
        taker.get("market_benchmark_status")
        or comparison.get("market_benchmark_status")
    )


def _executable_profitability_decision(trading):
    blockers = []
    taker = trading.get("taker") or {}
    mm = trading.get("market_making") or {}
    exchange = trading.get("exchange_economics") or {}
    quality = taker.get("quality_gate") or {}
    evidence_status = _status(taker.get("pnl_evidence_status"))
    trading_status = trading.get("status")
    taker_profit = _taker_profit(trading)
    taker_benchmark = _taker_market_benchmark_status(taker)
    taker_countable = (
        _status(quality.get("status")) == "PASS"
        or _status(taker.get("strategy_quality_candidate_status")).startswith("COUNTABLE")
    )
    taker_settled_orders = _int(taker.get("settled_order_count"), 0)
    taker_mtm_allowed = _bool_true(taker.get("mtm_promotion_allowed"))
    taker_basis = _status(taker.get("promotion_evidence_basis"))
    taker_pnl_source = _status(taker.get("pnl_source"))

    taker_blocks = []
    if taker_mtm_allowed or evidence_status == "PROVISIONAL_MTM_ONLY" or taker_pnl_source == "MARK_TO_MARKET":
        taker_blocks.append("mark-to-market evidence cannot promote")
    if evidence_status != "SETTLEMENT_SCORED":
        taker_blocks.append("taker PnL is not settlement-scored")
    if not _positive(taker_profit):
        taker_blocks.append("taker settlement-scored net PnL is not positive")
    if _status(taker_benchmark) != "PASS":
        taker_blocks.append("taker market/no-trade benchmark status is not pass")
    if not taker_countable:
        taker_blocks.append("taker strategy quality is not countable")
    if taker_settled_orders <= 0:
        taker_blocks.append("taker has no settled orders")
    if taker_basis not in {"SETTLEMENT_SCORED", ""}:
        taker_blocks.append(f"taker promotion evidence basis is {taker.get('promotion_evidence_basis')}")
    if _status(exchange.get("status")) == "BLOCK":
        taker_blocks.append("exchange economics snapshot is not current")

    maker_net = _float(mm.get("paper_score_net_pnl_after_fees_incentives_usdc"))
    maker_baseline = mm.get("market_benchmark_status") or mm.get("paper_score_benchmark_status")
    maker_blocks = []
    if _status(mm.get("countability_status")) != "COUNTABLE":
        maker_blocks.append("maker evidence is not countable")
    if mm.get("counts_toward_live_forward_gate") is not True:
        maker_blocks.append("maker evidence does not count toward live-forward gate")
    if _status(mm.get("paper_score_gate_status")) != "PASS":
        maker_blocks.append("maker paper-score gate is not pass")
    if not _positive(maker_net):
        maker_blocks.append("maker after-fee/incentive net PnL is not positive")
    if _status(maker_baseline) != "PASS":
        maker_blocks.append("maker market/no-trade benchmark status is not pass")
    if _status(exchange.get("status")) == "BLOCK":
        maker_blocks.append("exchange economics snapshot is not current")

    taker_pass = not taker_blocks
    maker_pass = not maker_blocks
    if not _is_pass(trading_status):
        blockers.append(_blocker(
            "trading_evidence_not_pass",
            f"trading evidence status is {trading_status or 'MISSING'}",
            source="trading_evidence",
            lane="executable_profitability",
        ))
    if not taker_pass and not maker_pass:
        blockers.append(_blocker(
            "no_countable_profitable_execution_lane",
            "; ".join(taker_blocks[:3] + maker_blocks[:3]) or "no countable profitability lane",
            source="trading_evidence",
            lane="executable_profitability",
        ))

    contamination = _lane_contamination(
        "PASS",
        [
            {
                "check": "settlement_scored_profitability",
                "status": "PASS" if evidence_status == "SETTLEMENT_SCORED" or maker_pass else "BLOCK",
                "detail": "profitability success requires settlement-scored taker PnL or countable maker score",
            },
            {
                "check": "mtm_not_promotion_evidence",
                "status": "PASS" if not taker_mtm_allowed and evidence_status != "PROVISIONAL_MTM_ONLY" else "BLOCK",
                "detail": "mark-to-market PnL is diagnostic only",
            },
            {
                "check": "market_or_no_trade_benchmark",
                "status": "PASS" if _status(taker_benchmark) == "PASS" or _status(maker_baseline) == "PASS" else "BLOCK",
                "detail": "profitability must beat no-trade and market benchmarks",
            },
        ],
    )
    status = "PASS" if not blockers and contamination["status"] == "PASS" else "BLOCK"
    return {
        "status": status,
        "counts_toward_headline": status == "PASS",
        "lane": "executable_profitability",
        "evidence_basis": "trading_evidence",
        "metrics": {
            "trading_status": trading_status,
            "taker_pnl_evidence_status": taker.get("pnl_evidence_status"),
            "taker_settlement_scored_net_pnl_usdc": taker_profit,
            "taker_market_benchmark_status": taker_benchmark,
            "taker_quality_status": quality.get("status"),
            "taker_settled_order_count": taker_settled_orders,
            "taker_mtm_promotion_allowed": taker.get("mtm_promotion_allowed"),
            "maker_countability_status": mm.get("countability_status"),
            "maker_net_after_fees_incentives_usdc": maker_net,
            "maker_market_benchmark_status": maker_baseline,
            "exchange_economics_status": exchange.get("status"),
            "exchange_economics_evidence_basis": exchange.get("evidence_basis"),
        },
        "taker_blockers": taker_blocks,
        "maker_blockers": maker_blocks,
        "lane_contamination": contamination,
        "blocker_count": len(blockers),
        "first_blocker": _first_blocker(blockers),
        "blockers": blockers,
    }


def _anti_anchoring_checks(proof, scorecard, residual, trading):
    lane_separation = _gate(proof, "weather_only_lane_separation")
    proof_guard = residual.get("proof_guard") or {}
    weather_lane = _lane_row(scorecard, "weather_only")
    market_lane = _lane_row(scorecard, "market_only")
    overlay_lane = _lane_row(scorecard, "market_informed_overlay")
    residual_trading = ((residual.get("trading_execution") or {}).get("summary") or {})
    taker = trading.get("taker") or {}
    checks = [
        {
            "check": "weather_only_lane_separation",
            "status": "PASS" if _status(lane_separation.get("status")) == "PASS" else "BLOCK",
            "detail": lane_separation.get("detail") or "weather-only proof must exclude market-informed and trading lanes",
        },
        {
            "check": "residual_blocked_from_weather_proof",
            "status": "PASS" if proof_guard.get("counts_toward_weather_model_promotion") is False else "BLOCK",
            "detail": proof_guard.get("detail") or "residual evidence must not count toward weather-model promotion",
        },
        {
            "check": "scorecard_lane_separation",
            "status": "PASS" if weather_lane and market_lane else "BLOCK",
            "detail": "scorecard must expose separate weather_only and market_only lanes",
            "weather_lane": weather_lane.get("lane"),
            "market_lane": market_lane.get("lane"),
            "overlay_lane": overlay_lane.get("lane"),
        },
        {
            "check": "mtm_not_promotion_evidence",
            "status": (
                "PASS"
                if not _bool_true(taker.get("mtm_promotion_allowed"))
                and not _bool_true(residual_trading.get("mtm_promotion_allowed"))
                else "BLOCK"
            ),
            "detail": "mark-to-market PnL cannot satisfy market-beating objective evidence",
        },
    ]
    blockers = [
        _blocker(
            "anti_anchoring",
            row.get("detail") or row.get("check"),
            source=row.get("check"),
        )
        for row in checks
        if row.get("status") != "PASS"
    ]
    return {
        "status": "BLOCK" if blockers else "PASS",
        "checks": checks,
        "blocker_count": len(blockers),
        "first_blocker": _first_blocker(blockers),
        "blockers": blockers,
    }


def build_scoreboard(
    *,
    backtest_root=DEFAULT_BACKTEST_ROOT,
    proof_packet=None,
    proper_scoring=None,
    residual_edge=None,
    winner_rank_parity=None,
    daily_progress=None,
    trading_evidence=None,
    generated_at_utc=None,
):
    backtest_root = Path(backtest_root)
    paths = {
        "weather_only_model_proof_packet": Path(proof_packet) if proof_packet else backtest_root / "weather_only_model_proof_packet.json",
        "proper_scoring_reliability_scorecard": Path(proper_scoring) if proper_scoring else backtest_root / "proper_scoring_reliability_scorecard.json",
        "market_benchmark_residual_edge": Path(residual_edge) if residual_edge else backtest_root / "market_benchmark_residual_edge.json",
        "winner_rank_parity": Path(winner_rank_parity) if winner_rank_parity else backtest_root / "winner_rank_parity.json",
        "daily_progress_latest": Path(daily_progress) if daily_progress else backtest_root / "daily_progress_latest.json",
        "trading_evidence": Path(trading_evidence) if trading_evidence else backtest_root / "trading_evidence.json",
    }
    artifacts = {name: _read_json(path) for name, path in paths.items()}
    inputs = {
        name: _input_record(
            name,
            paths[name],
            artifacts[name],
            required=name in REQUIRED_INPUTS,
        )
        for name in paths
    }
    input_blockers = _input_blockers(inputs)
    proof = artifacts["weather_only_model_proof_packet"]
    scorecard = artifacts["proper_scoring_reliability_scorecard"]
    residual = artifacts["market_benchmark_residual_edge"]
    parity = artifacts["winner_rank_parity"]
    daily = artifacts["daily_progress_latest"]
    trading = artifacts["trading_evidence"]

    decisions = {
        "weather_only_market_beating": _weather_only_decision(proof, scorecard, parity, residual, daily),
        "residual_edge": _residual_decision(residual),
        "executable_profitability": _executable_profitability_decision(trading),
    }
    anti_anchoring = _anti_anchoring_checks(proof, scorecard, residual, trading)
    success_lanes = [
        name for name, row in decisions.items()
        if row.get("status") == "PASS" and row.get("counts_toward_headline")
    ]
    decision_blockers = [
        blocker
        for row in decisions.values()
        for blocker in row.get("blockers") or []
    ]
    headline_status = "PASS" if success_lanes and not input_blockers and anti_anchoring.get("status") == "PASS" else "BLOCK"
    blockers = input_blockers + anti_anchoring.get("blockers", [])
    if headline_status != "PASS":
        blockers += decision_blockers
    if not success_lanes and not input_blockers and anti_anchoring.get("status") == "PASS":
        blockers.append(_blocker(
            "no_market_beating_lane",
            "no weather-only, residual-edge, or executable-profitability lane clears countable market-beating evidence",
        ))
    first = _first_blocker(blockers)
    headline = {
        "status": headline_status,
        "success_lanes": success_lanes,
        "first_success_lane": success_lanes[0] if success_lanes else None,
        "first_blocker": first,
        "summary": (
            f"PASS via {success_lanes[0]}"
            if headline_status == "PASS"
            else first.get("detail") or "market-beating objective is blocked"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _utc_iso(),
        "status": headline_status,
        "inputs": inputs,
        "headline": headline,
        "decisions": decisions,
        "anti_anchoring": anti_anchoring,
        "blockers": blockers,
        "summary": {
            "headline_status": headline_status,
            "first_success_lane": headline.get("first_success_lane"),
            "first_blocker": headline.get("first_blocker"),
            "weather_only_status": decisions["weather_only_market_beating"].get("status"),
            "residual_edge_status": decisions["residual_edge"].get("status"),
            "executable_profitability_status": decisions["executable_profitability"].get("status"),
            "anti_anchoring_status": anti_anchoring.get("status"),
            "blocker_count": len(blockers),
        },
    }


def _first_detail(row):
    first = row.get("first_blocker") or {}
    if isinstance(first, dict):
        return first.get("detail") or "-"
    return str(first) if first else "-"


def render_report(payload):
    headline = payload.get("headline") or {}
    decisions = payload.get("decisions") or {}
    anti = payload.get("anti_anchoring") or {}
    lines = [
        "# Market-Beating Objective Scoreboard",
        "",
        f"Generated: {payload.get('generated_at_utc')}",
        f"Status: **{payload.get('status')}**",
        "",
        "## Headline",
        "",
    ]
    lines += markdown_table(
        ["Field", "Value"],
        [
            ["Status", headline.get("status")],
            ["First success lane", headline.get("first_success_lane") or "-"],
            ["First blocker", _first_detail(headline)],
            ["Summary", headline.get("summary") or "-"],
        ],
    )
    lines += ["", "## Decisions", ""]
    lines += markdown_table(
        ["Decision", "Status", "Counts", "Key metric", "First blocker"],
        [
            [
                "weather_only_market_beating",
                (decisions.get("weather_only_market_beating") or {}).get("status"),
                (decisions.get("weather_only_market_beating") or {}).get("counts_toward_headline"),
                fmt_signed(
                    (((decisions.get("weather_only_market_beating") or {}).get("metrics") or {}).get("weather_minus_market_brier")),
                    6,
                ),
                _first_detail(decisions.get("weather_only_market_beating") or {}),
            ],
            [
                "residual_edge",
                (decisions.get("residual_edge") or {}).get("status"),
                (decisions.get("residual_edge") or {}).get("counts_toward_headline"),
                ((decisions.get("residual_edge") or {}).get("metrics") or {}).get("winning_slice_count"),
                _first_detail(decisions.get("residual_edge") or {}),
            ],
            [
                "executable_profitability",
                (decisions.get("executable_profitability") or {}).get("status"),
                (decisions.get("executable_profitability") or {}).get("counts_toward_headline"),
                fmt_num(
                    (((decisions.get("executable_profitability") or {}).get("metrics") or {}).get("taker_settlement_scored_net_pnl_usdc")),
                    4,
                ),
                _first_detail(decisions.get("executable_profitability") or {}),
            ],
        ],
    )
    lines += ["", "## Anti-Anchoring Checks", ""]
    lines += markdown_table(
        ["Check", "Status", "Detail"],
        [
            [row.get("check"), row.get("status"), row.get("detail")]
            for row in anti.get("checks") or []
        ],
    )
    lines += [
        "",
        "## Inputs",
        "",
    ]
    lines += markdown_table(
        ["Input", "Required", "Exists", "Status", "Schema"],
        [
            [
                row.get("name"),
                row.get("required"),
                row.get("exists"),
                row.get("status") or "-",
                row.get("schema_version") or "-",
            ]
            for row in (payload.get("inputs") or {}).values()
        ],
    )
    blockers = payload.get("blockers") or []
    lines += ["", "## Blockers", ""]
    if blockers:
        lines += markdown_table(
            ["Category", "Source", "Detail"],
            [
                [row.get("category"), row.get("source") or "-", row.get("detail")]
                for row in blockers[:40]
            ],
        )
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_outputs(payload, json_out=DEFAULT_JSON_OUT, report_out=DEFAULT_REPORT_OUT):
    json_path = Path(json_out)
    report_path = Path(report_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_path.write_text(render_report(payload), encoding="utf-8")
    return json_path, report_path


def build_parser():
    parser = argparse.ArgumentParser(description="Build the market-beating objective scoreboard.")
    parser.add_argument("--backtest-root", default=str(DEFAULT_BACKTEST_ROOT))
    parser.add_argument("--proof-packet", default="")
    parser.add_argument("--proper-scoring", default="")
    parser.add_argument("--residual-edge", default="")
    parser.add_argument("--winner-rank-parity", default="")
    parser.add_argument("--daily-progress", default="")
    parser.add_argument("--trading-evidence", default="")
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    parser.add_argument("--report-out", default=str(DEFAULT_REPORT_OUT))
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    payload = build_scoreboard(
        backtest_root=args.backtest_root,
        proof_packet=args.proof_packet or None,
        proper_scoring=args.proper_scoring or None,
        residual_edge=args.residual_edge or None,
        winner_rank_parity=args.winner_rank_parity or None,
        daily_progress=args.daily_progress or None,
        trading_evidence=args.trading_evidence or None,
    )
    json_out, report_out = write_outputs(payload, args.json_out, args.report_out)
    print(f"Market-beating objective scoreboard: {payload.get('status')}")
    print(f"JSON written to {json_out}")
    print(f"Report written to {report_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
