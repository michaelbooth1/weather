"""The shipped global artifact must leave served afternoon probabilities alone."""
from datetime import datetime
from types import SimpleNamespace

import pytest

from weather.model.model_distribution import DistributionPipelineState
from weather.model.toronto_model import TorontoHighTempModel


@pytest.mark.parametrize("market_id,buckets", [("toronto", (23, 24, 25)), ("nyc", (87, 88, 89))])
@pytest.mark.parametrize("hour", [15, 16, 17, 18])
@pytest.mark.parametrize("minute", [0, 59])
def test_shipped_centering_leaves_served_distribution_unchanged(market_id, buckets, hour, minute):
    # Exercise the real serving loader and distribution stage without constructing
    # unrelated fitted models, fetching sources, or accessing a settlement ledger.
    model = TorontoHighTempModel.__new__(TorontoHighTempModel)
    model.market_id = market_id
    model.set_target_date("2026-09-26")
    model.serving_bundle = SimpleNamespace(pointer_present=False)
    model._bound_base_model_shared_components = None
    model.afternoon_residual_centering = model.load_afternoon_residual_centering()
    scores = dict(zip(buckets, (0.25, 0.5, 0.25)))
    before = dict(scores)
    pipeline = DistributionPipelineState()
    now = datetime(2026, 9, 26, hour, minute, tzinfo=model.spec.tz)

    out, context = model.distribution_afternoon_residual_centering_stage(
        scores, hour=now.hour, forecast_context={"forecast_disagreement": 9.0}, pipeline=pipeline,
    )

    assert model.afternoon_residual_centering["component"]["enabled"] is False
    assert context["reason"] == "artifact_disabled"
    assert context["active"] is False
    assert context["shift"] == context["spread_blend_weight"] == 0.0
    assert context["mean_before"] == context["mean_after"]
    assert out == before == scores
    assert sum(out.values()) == 1.0
    assert "afternoon_residual_centering" not in pipeline.components
