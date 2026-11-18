from collections import OrderedDict
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from weather.model.toronto_model import TorontoHighTempModel


def winter_forecast(market, printed, forecast, data_root, feature=None):
    # Build the untrained empirical path with no release, fitted artifact, or
    # operational climatology. The synthetic feature arm supplies just one PMF.
    model = TorontoHighTempModel.__new__(TorontoHighTempModel)
    model.market_id = market
    model.set_target_date("2025-01-15")
    model.serving_bundle = SimpleNamespace(pointer_present=False)
    model._bound_base_model_components = None
    model._bound_base_model_shared_components = None
    model._feature_model_hgb = None
    model._feature_model_coefs = None
    model._late_day_model_coefs = None
    model.calibrated_weights = None
    model.forecast_error_model = None
    model.afternoon_residual_centering = None
    model.settlement_lag_model = None
    model.probability_calibration = None
    model.family_secondary_artifacts = {}
    if feature:
        model.predict_feature_distribution = lambda *a, **kw: (feature, "hgb", {})
    now = datetime(2025, 1, 15, 9, tzinfo=model.spec.tz)
    sources = {"weather_forecast": {"ok": True, "data": {"rows": [{"temp_native": forecast}]}}}
    if printed is not None:
        sources["wu_history"] = {"ok": True, "data": {
            "rows": [{"time": "09:00", "temp_native": printed}],
            "max_native": printed, "max_times": ["09:00"],
        }}
    with (
        patch("weather.market.market_registry.data_path", return_value=data_root),
        patch.object(TorontoHighTempModel, "_historical_target_cache", OrderedDict()),
    ):
        return model.estimate_distribution_result(sources, now=now)


@pytest.mark.parametrize("market,forecast,margin", [("toronto", 12, 5), ("nyc", 30, 9)])
@pytest.mark.parametrize("printed", [-1, 0, 1])
def test_printed_native_high_remains_in_support(market, forecast, margin, printed, tmp_path):
    result = winter_forecast(market, printed, forecast, tmp_path)
    prior = result.component_payload["components"]["climatology_prior"]
    assert result.calibration_context["observed_floor_bucket"] == printed
    assert min(prior) == printed - margin
    assert prior[printed] > 0
    assert result.distribution[printed] > 0
    assert sum(result.distribution.values()) == pytest.approx(1)
    assert sum(p for bucket, p in result.distribution.items() if bucket < printed) == 0


def test_zero_forecast_sets_support_when_observations_are_missing(tmp_path):
    result = winter_forecast("toronto", None, 0, tmp_path)
    prior = result.component_payload["components"]["climatology_prior"]
    assert result.calibration_context["observed_floor_bucket"] is None
    assert min(prior) == -5
    assert prior[0] > 0


def test_independent_feature_support_can_return_mass_on_the_printed_high(tmp_path):
    result = winter_forecast("toronto", 0, 12, tmp_path, feature={0: 0.75, 12: 0.25})
    stages = result.component_payload["components"]
    assert stages["hgb_feature_model"][0] == pytest.approx(0.75)
    assert stages["feature_blend"][0] > 0
    assert result.distribution[0] > 0
