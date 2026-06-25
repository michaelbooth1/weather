import csv
import json
from pathlib import Path

from weather.reporting.market.market_benchmark_residual_edge import build_report, render_report, write_outputs


FIELDS = [
    "variant_id",
    "uses_market_features",
    "claim_lane",
    "market_id",
    "target_date",
    "snapshot_id",
    "probability",
    "market_yes",
    "outcome",
    "captured_at_local",
    "book_time_utc",
    "book_age_seconds",
    "clob_token_id",
    "best_bid",
    "best_ask",
    "clob_midpoint",
    "clob_spread",
    "buy_fillable_10",
    "buy_fillable_100",
    "clob_liquidity_score",
    "clob_continuity_status",
    "cutoff_regime",
    "source_freshness_state",
    "settlement_distance_bucket",
]


def _write_rows(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _row(snapshot, probability, market_yes, outcome, *, overlay=False, cutoff="early"):
    return {
        "variant_id": "overlay_v" if overlay else "weather_v",
        "uses_market_features": str(overlay),
        "claim_lane": "market_informed_overlay" if overlay else "weather_only_core_model",
        "market_id": "atlanta",
        "target_date": "2026-06-19",
        "snapshot_id": snapshot,
        "probability": probability,
        "market_yes": market_yes,
        "outcome": outcome,
        "captured_at_local": "2026-06-19T08:00:00-04:00",
        "book_time_utc": "2026-06-19T12:00:00+00:00",
        "book_age_seconds": "12",
        "clob_token_id": f"token-{snapshot}",
        "best_bid": "0.58",
        "best_ask": "0.62",
        "clob_midpoint": market_yes,
        "clob_spread": "0.04",
        "buy_fillable_10": "10",
        "buy_fillable_100": "60",
        "clob_liquidity_score": "120",
        "clob_continuity_status": "fresh",
        "cutoff_regime": cutoff,
        "source_freshness_state": "all_fresh",
        "settlement_distance_bucket": "0" if outcome == "1" else "1",
    }


def _trading_payload():
    return {
        "taker": {
            "strategy_comparison": {
                "market_benchmark_status": "PASS",
                "promotion_evidence_basis": "settlement_scored",
                "mtm_promotion_allowed": False,
                "market_benchmark_summary": {
                    "opportunity_count": 2,
                    "no_trade_recommendation_count": 1,
                    "avoided_loss_usdc": 1.25,
                    "missed_gain_usdc": 0.5,
                },
                "by_strategy": [
                    {
                        "strategy_id": "residual_probe",
                        "fees_usdc": 0.03,
                        "slippage_usdc": 0.04,
                        "settlement_scored_net_pnl_usdc": 1.2,
                        "mark_to_market_pnl_usdc": 1.6,
                        "market_benchmark_status": "PASS",
                        "market_benchmark_no_trade_net_pnl_usdc": 0.0,
                        "market_benchmark_avoided_loss_usdc": 1.25,
                        "market_benchmark_missed_gain_usdc": 0.5,
                        "tail_fill_quality_summary": {"status": "PASS"},
                    }
                ],
            }
        }
    }


def test_market_benchmark_residual_edge_passes_with_complete_execution_contract(tmp_path):
    rows = [
        _row("s1", "0.70", "0.60", "1"),
        _row("s2", "0.20", "0.40", "0", cutoff="midday"),
        _row("s3", "0.80", "0.70", "1", overlay=True),
    ]
    shadow = tmp_path / "active_variant_shadow_long.csv"
    trading = tmp_path / "trading_evidence.json"
    _write_rows(shadow, rows)
    trading.write_text(json.dumps(_trading_payload()), encoding="utf-8")

    payload = build_report(
        active_shadow_long=shadow,
        trading_evidence=trading,
        generated_at_utc="2026-06-23T00:00:00+00:00",
    )
    report = render_report(payload)
    json_out, report_out = write_outputs(payload, tmp_path / "market.json", tmp_path / "market.md")

    assert payload["schema_version"] == "market_benchmark_residual_edge_v0.1"
    assert payload["status"] == "PASS"
    assert payload["proof_guard"]["counts_toward_weather_model_promotion"] is False
    assert payload["frozen_market_benchmark_contract"]["status"] == "PASS"
    assert payload["trading_execution"]["status"] == "PASS"
    assert payload["settlement_accuracy"]["market_informed_overlay"]["status"] == "PRESENT"
    assert payload["settlement_accuracy"]["weather_only_vs_market"]["weather_minus_market_brier"] < 0
    assert "MTM Versus Settlement" in report
    assert json_out.exists()
    assert report_out.exists()


def test_market_benchmark_residual_edge_blocks_missing_frozen_fields_and_trading_fields(tmp_path):
    shadow = tmp_path / "active_variant_shadow_long.csv"
    trading = tmp_path / "trading_evidence.json"
    _write_rows(
        shadow,
        [
            {
                **_row("s1", "0.70", "0.60", "1"),
                "best_bid": "",
                "best_ask": "",
                "buy_fillable_10": "",
            }
        ],
    )
    trading.write_text(
        json.dumps({"taker": {"strategy_comparison": {"by_strategy": [{"strategy_id": "missing"}]}}}),
        encoding="utf-8",
    )

    payload = build_report(active_shadow_long=shadow, trading_evidence=trading)
    categories = {row["category"] for row in payload["blockers"]}

    assert payload["status"] == "BLOCK"
    assert "frozen_market_contract" in categories
    assert "trading_execution" in categories
