import importlib

from weather.paths import config_path, data_path, docs_path


def test_default_runtime_paths_are_repo_absolute_from_other_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    daily_refresh = importlib.import_module("weather.operations.daily_refresh")
    forecast_payload_cas = importlib.import_module("weather.collection.forecast_payload_cas")
    nightly_retrain = importlib.import_module("weather.operations.nightly_retrain")
    observation_trigger = importlib.import_module("weather.operations.observation_trigger")
    market_making_constants = importlib.import_module("weather.market.market_making_run_constants")
    progress_audit = importlib.import_module("weather.reporting.scorecards.progress_audit")
    variant_registry = importlib.import_module("weather.reporting.candidate_lifecycle.variant_registry")
    operator_control_room = importlib.import_module(
        "weather.reporting.market.operator_control_room"
    )

    assert daily_refresh.DEFAULT_BACKTEST_ROOT == data_path("backtest")
    assert forecast_payload_cas.SHARED_FORECAST_PAYLOAD_CAS_ROOT == data_path("forecast_payload_cas")
    assert nightly_retrain.DEFAULT_SNAPSHOTS_ROOT == data_path("snapshots")
    assert observation_trigger.DEFAULT_BACKTEST_ROOT == data_path("backtest")
    assert market_making_constants.DEFAULT_RUNS_ROOT == data_path("mm_runs")
    assert progress_audit.DEFAULT_ROADMAP == docs_path("roadmap", "ROADMAP.md")
    assert variant_registry.DEFAULT_REGISTRY_PATH == config_path("model_variant_registry.json")
    assert operator_control_room.RUNS_ROOT == data_path("mm_runs")
