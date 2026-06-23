import json

from weather.reporting.market_beating_objective_scoreboard import (
    build_scoreboard,
    render_report,
    write_outputs,
)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _proof(status="PASS", lane_separation="PASS"):
    return {
        "schema_version": "weather_only_model_proof_packet_v0.1",
        "status": status,
        "first_blocker": {"detail": "proof stack blocked"} if status != "PASS" else {},
        "gates": [
            {
                "gate": "weather_only_lane_separation",
                "status": lane_separation,
                "detail": "market-informed and trading proof packets remain outside the weather-only lane",
            }
        ],
        "weather_only_lane": "weather_only_core_model",
    }


def _scorecard(weather_brier=0.04, market_brier=0.03, overlay_brier=0.02, status="PASS"):
    return {
        "schema_version": "proper_scoring_reliability_scorecard_v0.1",
        "status": status,
        "lanes": [
            {"lane": "weather_only", "status": "PASS", "brier": weather_brier, "row_count": 100},
            {"lane": "market_only", "status": "PASS", "brier": market_brier, "row_count": 100},
            {"lane": "market_informed_overlay", "status": "PASS", "brier": overlay_brier, "row_count": 100},
        ],
        "summary": {"lane_statuses": {"weather_only": "PASS", "market_only": "PASS"}},
    }


def _parity(status="PASS"):
    return {
        "schema_version": "winner_rank_parity_v0.1",
        "status": status,
        "parity_gate": {
            "status": status,
            "first_blocker": {"detail": "market top-hit rate beats model"} if status != "PASS" else {},
        },
        "summary": {"parity_gate_status": status},
    }


def _daily_progress(baseline_status="PRESENT"):
    return {
        "schema_version": "daily_progress_ledger_v0.1",
        "evidence_independent_baseline_status": baseline_status,
    }


def _residual(status="BLOCK", proof_counts=False, winning_slice=False, trading_status="PASS"):
    slices = []
    if winning_slice:
        slices.append({
            "slice": "market",
            "group": "atlanta",
            "residual_edge_row_count": 12,
            "weather_minus_market_brier": -0.01,
            "positive_residual_edge_hit_rate": 0.67,
        })
    return {
        "schema_version": "market_benchmark_residual_edge_v0.1",
        "status": status,
        "proof_guard": {
            "counts_toward_weather_model_promotion": proof_counts,
            "detail": "Market-only, market-informed overlay, and residual-edge evidence cannot satisfy weather-only proof-packet blockers.",
        },
        "summary": {
            "weather_minus_market_brier": -0.01 if winning_slice else 0.02,
            "contract_status": "PASS",
            "trading_status": trading_status,
        },
        "settlement_accuracy": {
            "weather_only_vs_market": {
                "weather_only_brier": 0.02 if winning_slice else 0.04,
                "market_only_brier": 0.03,
                "weather_minus_market_brier": -0.01 if winning_slice else 0.01,
                "residual_edge_row_count": 12 if winning_slice else 0,
            },
            "slices": slices,
        },
        "frozen_market_benchmark_contract": {"status": "PASS"},
        "trading_execution": {
            "status": trading_status,
            "summary": {
                "market_benchmark_status": "PASS",
                "promotion_evidence_basis": "settlement_scored",
                "mtm_promotion_allowed": False,
            },
        },
    }


def _trading(status="OK", mtm_only=False, profitable=False):
    return {
        "schema_version": "trading_evidence_summary_v0.1",
        "status": status,
        "taker": {
            "pnl_evidence_status": "PROVISIONAL_MTM_ONLY" if mtm_only else ("SETTLEMENT_SCORED" if profitable else "UNSCORED"),
            "pnl_source": "mark_to_market" if mtm_only else "settlement_finalization",
            "settlement_scored_net_pnl_usdc": 2.5 if profitable else 0.0,
            "settled_order_count": 3 if profitable else 0,
            "mtm_promotion_allowed": mtm_only,
            "promotion_evidence_basis": "settlement_scored",
            "market_benchmark_status": "PASS",
            "quality_gate": {"status": "PASS" if profitable else "SAMPLE_PENDING"},
            "strategy_quality_candidate_status": "COUNTABLE_SETTLED" if profitable else "MISSING_SETTLED_SAMPLE",
        },
        "market_making": {
            "countability_status": "NON_COUNTABLE",
            "counts_toward_live_forward_gate": False,
        },
    }


def _write_standard_inputs(root, *, proof=None, scorecard=None, residual=None, parity=None, progress=None, trading=None):
    _write(root / "weather_only_model_proof_packet.json", proof or _proof())
    _write(root / "proper_scoring_reliability_scorecard.json", scorecard or _scorecard())
    _write(root / "market_benchmark_residual_edge.json", residual or _residual())
    _write(root / "winner_rank_parity.json", parity or _parity())
    _write(root / "daily_progress_latest.json", progress or _daily_progress())
    _write(root / "trading_evidence.json", trading or _trading())


def test_weather_only_market_beating_passes_when_proof_and_scorecard_clear(tmp_path):
    _write_standard_inputs(
        tmp_path,
        scorecard=_scorecard(weather_brier=0.02, market_brier=0.03, overlay_brier=0.019),
    )

    payload = build_scoreboard(backtest_root=tmp_path, generated_at_utc="2026-06-23T00:00:00+00:00")
    report = render_report(payload)
    json_out, report_out = write_outputs(payload, tmp_path / "scoreboard.json", tmp_path / "scoreboard.md")

    assert payload["schema_version"] == "market_beating_objective_scoreboard_v0.1"
    assert payload["status"] == "PASS"
    assert payload["headline"]["first_success_lane"] == "weather_only_market_beating"
    assert payload["decisions"]["weather_only_market_beating"]["lane_contamination"]["status"] == "PASS"
    assert "Market-Beating Objective Scoreboard" in report
    assert json_out.exists()
    assert report_out.exists()


def test_market_informed_convergence_does_not_clear_weather_only_success(tmp_path):
    _write_standard_inputs(
        tmp_path,
        scorecard=_scorecard(weather_brier=0.05, market_brier=0.03, overlay_brier=0.01),
    )

    payload = build_scoreboard(backtest_root=tmp_path)
    weather = payload["decisions"]["weather_only_market_beating"]

    assert payload["status"] == "BLOCK"
    assert weather["status"] == "BLOCK"
    assert weather["metrics"]["weather_minus_market_brier"] > 0
    assert weather["first_blocker"]["category"] == "weather_only_trails_market"
    assert payload["anti_anchoring"]["status"] == "PASS"


def test_residual_edge_cannot_count_when_guard_allows_weather_promotion(tmp_path):
    _write_standard_inputs(
        tmp_path,
        proof=_proof(status="BLOCK"),
        scorecard=_scorecard(weather_brier=0.05, market_brier=0.03),
        residual=_residual(status="PASS", proof_counts=True, winning_slice=True, trading_status="PASS"),
    )

    payload = build_scoreboard(backtest_root=tmp_path)

    assert payload["status"] == "BLOCK"
    assert payload["decisions"]["residual_edge"]["status"] == "BLOCK"
    assert payload["decisions"]["residual_edge"]["first_blocker"]["category"] == "residual_counts_toward_weather_proof"
    assert payload["anti_anchoring"]["status"] == "BLOCK"


def test_executable_profitability_blocks_mtm_only_pnl(tmp_path):
    _write_standard_inputs(
        tmp_path,
        proof=_proof(status="BLOCK"),
        scorecard=_scorecard(weather_brier=0.05, market_brier=0.03),
        trading=_trading(status="OK", mtm_only=True, profitable=False),
    )

    payload = build_scoreboard(backtest_root=tmp_path)
    executable = payload["decisions"]["executable_profitability"]

    assert payload["status"] == "BLOCK"
    assert executable["status"] == "BLOCK"
    assert "mark-to-market evidence cannot promote" in executable["first_blocker"]["detail"]
    assert executable["lane_contamination"]["status"] == "BLOCK"
