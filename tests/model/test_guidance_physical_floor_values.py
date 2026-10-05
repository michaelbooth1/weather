"""Value table for ``guidance_physical_floor`` (test-suite review K, role 19, probability-mass floor family).

The live-feature fixture in test_forecast_feature.py makes every floor candidate equal, so min, max and a
dropped candidate all give the same answer there. Here each candidate is uniquely the highest once, so the
floor must be the maximum over every source it reads. Train/serve parity cannot catch a regression here
because both paths call this one function.

Guards: probability mass and physical floor contract (AGENTS.md model changes) - the guidance floor is the
  maximum over every candidate source it reads.
"""
import pytest

from weather.model.toronto_model import TorontoHighTempModel


def _model():
    return TorontoHighTempModel(target_date="2026-06-22", market_id="toronto")


@pytest.mark.parametrize("kwargs,expected", [
    ({"high_so_far": 20, "current_temp": 21}, 21.0),
    ({"high_so_far": 21, "current_temp": 20}, 21.0),
    ({"high_so_far": 20, "live_reading": 23}, 23.0),
    ({"high_so_far": 20, "sources": {"eccc_swob": {"ok": True, "data": {"temp_native": 24.0}}}}, 24.0),
    ({"high_so_far": 20, "sources": {"metar": {"ok": True, "data": {
        "rows": [{"time": "10:00", "temp_native": 25.0}, {"time": "11:00", "temp_native": 22.0}],
        "temp_native": 22.0,
    }}}}, 25.0),
])
def test_guidance_physical_floor_is_the_highest_candidate(kwargs, expected):
    assert _model().guidance_physical_floor(**kwargs) == expected
