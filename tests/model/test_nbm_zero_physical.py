from types import SimpleNamespace

import pytest

from weather.model.toronto_model import TorontoHighTempModel


@pytest.mark.parametrize(
    ("p90", "mean", "representative", "status"),
    [
        (0, -5, 0, "fresh_but_partially_impossible"),
        (None, 0, 0, "fresh_but_partially_impossible"),
        (None, -5, -5, "fresh_but_impossible"),
        (None, None, -6, "fresh_but_impossible"),
        (4, 0, 4, "fresh_but_partially_impossible"),
    ],
)
def test_status_and_feature_gap_agree_on_first_available_temperature(p90, mean, representative, status):
    model = object.__new__(TorontoHighTempModel)
    model.spec = SimpleNamespace(scale_delta=lambda degrees_c: degrees_c * 9 / 5)
    data = {
        "percentiles": {"10": -12, "25": -9, "50": -6, "75": -2, "90": p90},
        "mean_native": mean,
        "stddev_native": 4,
    }
    floor = 0
    states = model.guidance_physical_states(
        {"nbm_probabilistic_tmax": {"ok": True, "data": data}}, observed_floor_native=floor
    )
    features = model.us_guidance_features(nbm_probabilistic_tmax=data, observed_floor_native=floor)

    state = states["nbm_probabilistic_tmax"]
    assert state["physical_validity_status"] == status
    assert state["representative_high"] == representative
    assert state["floor_gap"] == features["nbm_prob_tmax_floor_gap"] == representative - floor
    assert features["nbm_prob_tmax_p90"] == p90
    assert features["nbm_prob_tmax_mean"] == (0 if mean == 0 else None)
    assert features["nbm_prob_tmax_p50"] is None
    assert features["nbm_prob_tmax_stddev"] == 4
