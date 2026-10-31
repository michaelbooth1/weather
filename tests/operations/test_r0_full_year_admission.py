"""Lane L1 adds exactly one offline research module to the workstation allowlist.

Guards: workstation offline-module allowlist (HOST_LOAD_POLICY workstation scope; master pre-authorisation
2026-10-24) - workload_admission.ps1 and the Codex hook list the same modules, pinned here in full.
"""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULE = "weather.calibration.r0_full_year"
PINNED = [
    "maker_core.replay.toxicity",
    "maker_core.replay.v2.transfer_cli",
    "tools.research.guidance_all_hours.run",
    "tools.research.missing_information.run",
    "tools.research.morning_guidance.run",
    "tools.research.nbm_target_trace.run",
    "tools.research.nbm_target_fix",
    "weather.backtesting.backtest",
    "weather.backtesting.replay",
    "weather.backtesting.replay_ablation",
    "weather.backtesting.replay_backtest",
    "weather.backtesting.snapshot_analytics",
    "weather.backtesting.tape_scoring",
    "weather.calibration.feature_model",
    "weather.calibration.gap_to_market_atlas",
    "weather.calibration.l5_subset_scores",
    "weather.calibration.market_blend",
    "weather.calibration.dead_bucket",
    "weather.calibration.dead_bucket_toronto",
    "weather.calibration.new_city_corpus",
    "weather.calibration.ols_floor_ladder",
    "weather.calibration.pooled_candidate_replay",
    "weather.calibration.pooled_candidate_replay_diagnostics",
    "weather.calibration.pooled_candidate_replay_report",
    MODULE,
    "weather.calibration.upstream_obs_screen",
    "weather.calibration.pooled_residual_model",
    "weather.calibration.r0_ols_floor_challenger",
    # Reviewed additions after this pin was written (L8 ratchet fix, 2026-10-27); each has its own admission test.
    "weather.calibration.high_so_far_parity_shadow",  # L8 shadow parity scorer (ea449e9cc, 10-24)
    "weather.calibration.mg2_composite",  # MG-2 binding module: emit, check, bind-release (2c80a3262, 10-25)
    "weather.calibration.mg2_inputs",  # MG-2 input-transfer receiver and label-free builder (fe4782e66, 10-25)
    "weather.calibration.mg2_p3d_n",  # MG-2 P3d_N serve and dev-fit control (9f7e1b9b8, 10-25)
    "weather.calibration.b_scorer",  # Rule B-1 scorer: control and the one look (b5c2108b3, 10-25)
    "weather.calibration.l6_own_state",  # L3's one-time L6 own-state fit, master D2 (i) (1d69a87f1, 10-26)
    "weather.calibration.pooled_subbar_wgate",  # L17 P5 (a) row 94 pooled sub-bar P0 vs market (10-31)
    "weather.calibration.loyo_screen",  # unlanded allowlist commit on this branch's base (run-branch PINNED rule)
    "weather.calibration.spread_information_rung",  # unlanded allowlist commit on this branch's base (same rule)
    "weather.market.maker_evidence_inspect",
    "weather.market.maker_counterfactual_tape",
    "weather.operations.base_retrain",
    "weather.operations.density_live_replay_parity",
    "weather.operations.nightly_retrain",
    "weather.operations.replay_status_backfill",
    "weather.operations.workstation_cold_archive_stage",
    "weather.operations.workstation_cold_archive_restore",
    "weather.reporting.scorecards.dev_scorecard",
    "weather.reporting.scorecards.loss_atlas",
    "weather.reporting.scorecards.train_serve_feature_parity",
    "weather.sources.forecast_training_corpus",
]


def _hook():
    spec = importlib.util.spec_from_file_location("fy_hook", ROOT / ".codex/hooks/pre_tool_use_host_load.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def test_admission_list_is_pinned_and_mirrored():
    # Mirror equality with Get-WeatherWorkstationOfflineModule is proved by executing it in
    # tests/operations/test_loss_atlas_admission.py; here the hook mirror pins this module.
    assert _hook()._OFFLINE_WEATHER_MODULES == frozenset(PINNED)


def test_hook_admits_the_scorer_exactly():
    hook = _hook()
    for near in (MODULE + ".child", MODULE + "_x", "weather.calibration.r0_full"):
        assert near not in hook._OFFLINE_WEATHER_MODULES
    assert hook.evaluate({"tool_name": "Bash", "tool_input": {
        "command": f'& "{sys.executable}" -m {MODULE} run --market atlanta'
    }}, constrained_capture_host=False) is not None
