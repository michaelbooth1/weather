from datetime import datetime, timezone

import pytest

from weather.calibration import pooled_band_training, pooled_density_training, pooled_feature_cli
from weather.collection.live_variant_predictions import trace_pooled_band_binary_probabilities
from weather.model import variant_prediction_runtime as runtime
from weather.model.feature_store import build_historical_feature_record
from weather.model.model_distribution import DistributionMixin


@pytest.mark.parametrize("primary,alternate,bucket,alpha", [
    (0, None, "07-08", 0.8),
    ("0", None, "07-08", 0.8),
    (0, 17, "07-08", 0.8),
    (None, 0, "07-08", 0.8),
    ("", 17, "17-20", 0.4),
    (7, 17, "07-08", 0.6),
    (None, None, "na", 0.1),
])
def test_band_and_density_use_recorded_cutoff(primary, alternate, bucket, alpha):
    row = {"market_id": "nyc", "band_kind": "eq", "cutoff_hour": primary,
           "candidate_cutoff_hour": alternate}
    expected = f"|hour={bucket}|"
    for contexts in (runtime.adjacent_calibration_contexts, runtime.market_bias_calibration_contexts,
                     runtime.exact_winner_catchup_contexts, runtime.density_forecast_relative_contexts,
                     pooled_density_training.density_forecast_relative_contexts):
        assert expected in contexts(row)[0]
    assert runtime.forecast_centering_alpha(row, {
        "forecast_centering_alpha_by_hour": {"0": 0.8, "17": 0.4},
        "forecast_centering_early_alpha": 0.6, "forecast_centering_default_alpha": 0.1,
    }) == alpha


def test_custom_cli_hour_reaches_calibration_but_live_midnight_uses_seven():
    hour, = pooled_feature_cli.parse_hours("0")
    record = build_historical_feature_record(
        "2025-01-03", [{"minute_of_day": 0, "temp_native": 40.0}],
        {"bucket": 45}, hour, unit="F",
    )
    assert hour == 0 and record["final_bucket"] == 45
    assert DistributionMixin.intraday_cutoff_hour(None, datetime(2025, 1, 3, 0, 5)) == 7
    # build_market_records stamps this requested hour after extracting historical features.
    row = runtime.band_prediction_record({**record, "market_id": "nyc", "cutoff_hour": hour}, "eq", 42)
    config = {"market_bias_calibration_enabled": True, "market_bias_calibration": {
        "enabled": True, "contexts": {"market=nyc|hour=07-08|kind=eq": 3.0},
    }}
    assert runtime.apply_band_postprocessing(0.2, row, config) == pytest.approx(0.6)
    assert pooled_band_training._band_validation_partition_key(row)[-1] == 0
    assert pooled_band_training._band_validation_partition_key({})[-1] == "unknown"


@pytest.mark.parametrize("feature_hour,model_hour", [(0, "0"), ("0", "0"), (None, "17"), ("", "17")])
def test_explicit_midnight_selects_its_own_artifact(monkeypatch, feature_hour, model_hour):
    artifact = {"models": {"0": {"prob": 0.2}, "17": {"prob": 0.8}},
                "postprocess": {"partition_normalization_enabled": False}}
    monkeypatch.setattr(runtime, "predict_band_rows_for_bundle",
                        lambda bundle, rows, postprocess: [bundle["prob"]] * len(rows))
    trace = trace_pooled_band_binary_probabilities(
        artifact, {"cutoff_hour": feature_hour}, [{"bin_kind": "eq", "bin_value_c": 42}],
        {"captured_at": datetime(2025, 1, 3, 17, tzinfo=timezone.utc)},
    )
    assert trace["cutoff_hour"] == model_hour
    assert list(trace["probabilities"].values()) == [artifact["models"][model_hour]["prob"]]
