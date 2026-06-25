import importlib

from weather.paths import config_path, data_path, docs_path


def test_default_runtime_paths_are_repo_absolute_from_other_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    daily_refresh = importlib.import_module("weather.operations.daily_refresh")
    nightly_retrain = importlib.import_module("weather.operations.nightly_retrain")
    observation_trigger = importlib.import_module("weather.operations.observation_trigger")
    market_making_constants = importlib.import_module("weather.market.market_making_run_constants")
    progress_audit = importlib.import_module("weather.reporting.scorecards.progress_audit")
    variant_registry = importlib.import_module("weather.reporting.variant_registry")
    market_making_dashboard = importlib.import_module("weather.reporting.market.market_making_dashboard")

    assert daily_refresh.DEFAULT_BACKTEST_ROOT == data_path("backtest")
    assert nightly_retrain.DEFAULT_SNAPSHOTS_ROOT == data_path("snapshots")
    assert observation_trigger.DEFAULT_BACKTEST_ROOT == data_path("backtest")
    assert market_making_constants.DEFAULT_RUNS_ROOT == data_path("mm_runs")
    assert progress_audit.DEFAULT_ROADMAP == docs_path("roadmap", "ROADMAP.md")
    assert variant_registry.DEFAULT_REGISTRY_PATH == config_path("model_variant_registry.json")
    assert market_making_dashboard.RUNS_ROOT == data_path("mm_runs")


def test_tape_backup_default_root_uses_repo_data_when_env_is_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("WEATHER_TAPE_BACKUP_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    tape_backup = importlib.import_module("weather.operations.tape_backup")
    tape_backup = importlib.reload(tape_backup)

    assert tape_backup.DEFAULT_BACKUP_ROOT == data_path("tape_backups")
