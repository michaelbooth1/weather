"""Daily refresh adapters for the D1-09 formerly-unscheduled gate and scorecard reports.

Each report runs as an isolated child through the reporting-step heavy-child path and
is summarized from its JSON output. Split from ``daily_refresh_reporting_steps`` to keep
that module under the size-audit warning; must not import the daily_refresh facade.
"""

from __future__ import annotations

import sys

from weather.operations.daily_refresh_locks import as_path, backtest_path
from weather.operations.daily_refresh_reporting_steps import _load_child_json, _run_heavy_step_child


def _run_d1_09_report_step(args, step_name, module, json_name, report_name, output_flags):
    """Run one formerly-unscheduled report through the normal isolated child path."""
    json_out = backtest_path(args, json_name)
    report_out = backtest_path(args, report_name)
    command = [sys.executable, "-m", module, *output_flags(args, json_out, report_out)]
    child = _run_heavy_step_child(args, step_name, command)
    payload = _load_child_json(json_out, step_name)
    blockers = payload.get("blockers") or []
    summary = payload.get("summary") or {}
    return {
        "status": str(payload.get("status") or "UNKNOWN").upper(),
        "json_out": as_path(json_out),
        "report_out": as_path(report_out),
        "blocker_count": payload.get("blocker_count", len(blockers)),
        "first_blocker": payload.get("first_blocker") or (blockers[0] if blockers else None),
        "source_row_count": summary.get("source_row_count"),
        "subprocess": child,
    }


def run_per_location_artifact_quarantine_step(args):
    return _run_d1_09_report_step(
        args,
        "per_location_artifact_quarantine",
        "weather.reporting.data_quality.per_location_artifact_quarantine",
        "per_location_artifact_quarantine.json",
        "per_location_artifact_quarantine_report.md",
        lambda _args, json_out, report_out: ["--json-out", str(json_out), "--report-out", str(report_out)],
    )


def run_physical_feature_family_ratchet_step(args):
    return _run_d1_09_report_step(
        args,
        "physical_feature_family_ratchet",
        "weather.reporting.source_gates.physical_feature_family_ratchet",
        "physical_feature_family_ratchet.json",
        "physical_feature_family_ratchet.md",
        lambda args, json_out, report_out: [
            "--source-family-inventory", str(backtest_path(args, "source_family_inventory.json")),
            "--source-family-ablation", str(backtest_path(args, "source_family_ablation.json")),
            "--json-out", str(json_out), "--report-out", str(report_out),
        ],
    )


def run_pooled_f_retrain_location_gate_step(args):
    return _run_d1_09_report_step(
        args,
        "pooled_f_retrain_location_gate",
        "weather.reporting.location_analysis.pooled_f_retrain_location_gate",
        "pooled_f_retrain_location_gate.json",
        "pooled_f_retrain_location_gate_report.md",
        lambda args, json_out, report_out: [
            "--training-report", str(backtest_path(args, "f_family_pooled_band_model_v0_3_report.md")),
            "--candidate-replay", str(backtest_path(args, "pooled_candidate_replay_latest.json")),
            "--promotion-refresh", str(backtest_path(args, "f_family_promotion_refresh.json")),
            "--predawn-repair", str(backtest_path(args, "pooled_f_candidate_miami_current_fallback_predawn_weak_slot_repair.json")),
            "--bottom-location", str(backtest_path(args, "bottom_location_winner_centering.json")),
            "--exact-distance", str(backtest_path(args, "exact_band_distance_zero_calibration.json")),
            "--out", str(json_out), "--report", str(report_out),
        ],
    )


def run_served_distribution_calibration_contract_step(args):
    return _run_d1_09_report_step(
        args,
        "served_distribution_calibration_contract",
        "weather.reporting.serving_gates.served_distribution_calibration_contract",
        "served_distribution_calibration_contract.json",
        "served_distribution_calibration_contract_report.md",
        lambda args, json_out, report_out: [
            "--serving-ordinal-gate", str(backtest_path(args, "serving_ordinal_smoothing_gate.json")),
            "--retrain-location-gate", str(backtest_path(args, "pooled_f_retrain_location_gate.json")),
            "--replay", str(backtest_path(args, "pooled_f_candidate_miami_current_fallback_predawn_repair_replay_summary.json")),
            "--candidate-hourly", str(backtest_path(args, "pooled_f_candidate_miami_current_fallback_predawn_repair_hourly_candidate_performance.json")),
            "--candidate-ten-minute", str(backtest_path(args, "pooled_f_candidate_miami_current_fallback_predawn_repair_ten_minute_candidate_performance.json")),
            "--exact-distance", str(backtest_path(args, "exact_band_distance_zero_calibration.json")),
            "--bottom-location", str(backtest_path(args, "bottom_location_winner_centering.json")),
            "--promotion-refresh", str(backtest_path(args, "f_family_promotion_refresh_predawn_repair.json")),
            "--out", str(json_out), "--report", str(report_out),
        ],
    )


def run_early_hour_positive_daily_first_gate_step(args):
    return _run_d1_09_report_step(
        args,
        "early_hour_positive_daily_first_gate",
        "weather.reporting.serving_gates.early_hour_positive_daily_first_gate",
        "early_hour_positive_daily_first_gate.json",
        "early_hour_positive_daily_first_gate_report.md",
        lambda args, json_out, report_out: [
            "--progress-audit", str(backtest_path(args, "progress_audit.json")),
            "--served-distribution-contract", str(backtest_path(args, "served_distribution_calibration_contract.json")),
            "--candidate-hourly", str(backtest_path(args, "item224_active_timesplit_logistic_repair_hourly_gate.json")),
            "--candidate-ten-minute", str(backtest_path(args, "item224_active_timesplit_logistic_repair_ten_minute.json")),
            "--out", str(json_out), "--report", str(report_out),
        ],
    )


def run_weather_only_model_proof_packet_step(args):
    return _run_d1_09_report_step(
        args,
        "weather_only_model_proof_packet",
        "weather.reporting.scorecards.weather_only_model_proof_packet",
        "weather_only_model_proof_packet.json",
        "weather_only_model_proof_packet_report.md",
        lambda args, json_out, report_out: [
            "--promotion-refresh", str(backtest_path(args, "f_family_promotion_refresh.json")),
            "--hourly", str(backtest_path(args, "hourly_model_performance.json")),
            "--ten-minute", str(backtest_path(args, "ten_minute_model_performance.json")),
            "--exact-distance", str(backtest_path(args, "exact_band_distance_zero_calibration.json")),
            "--bottom-location", str(backtest_path(args, "bottom_location_winner_centering.json")),
            "--fleet-observability", str(backtest_path(args, "fleet_observability.json")),
            "--progress-audit", str(backtest_path(args, "progress_audit.json")),
            "--daily-progress", str(backtest_path(args, "daily_progress_latest.json")),
            "--served-distribution", str(backtest_path(args, "served_distribution_calibration_contract.json")),
            "--positive-daily-first", str(backtest_path(args, "early_hour_positive_daily_first_gate.json")),
            "--austin-requalification", str(backtest_path(args, "austin_hgb_requalification.json")),
            "--winner-rank-parity", str(backtest_path(args, "winner_rank_parity.json")),
            "--out", str(json_out), "--report", str(report_out),
        ],
    )


def run_market_benchmark_residual_edge_step(args):
    return _run_d1_09_report_step(
        args,
        "market_benchmark_residual_edge",
        "weather.reporting.market.market_benchmark_residual_edge",
        "market_benchmark_residual_edge.json",
        "market_benchmark_residual_edge.md",
        lambda args, json_out, report_out: [
            "--active-shadow-long", str(backtest_path(args, "active_variant_shadow_long.csv")),
            "--trading-evidence", str(backtest_path(args, "trading_evidence.json")),
            "--json-out", str(json_out), "--report-out", str(report_out),
        ],
    )
