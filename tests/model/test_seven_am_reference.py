"""The 07:00 reference belongs to the printed observation path."""
from datetime import date, timezone
from types import SimpleNamespace

import pytest

from weather.model.feature_store import build_historical_feature_record


def observation(minute, value):
    return {
        "time": f"{minute // 60:02}:{minute % 60:02}",
        "minute_of_day": minute,
        "temp_native": value,
        "dewpoint_native": value - 2,
        "wind_group": "calm",
        "cloud_group": "clear",
    }


@pytest.mark.parametrize("unit,early,later", [("F", 40, 55), ("C", -2, 3)])
def test_training_and_live_use_the_printed_reference_at_seven(unit, early, later, monkeypatch, tmp_path):
    monkeypatch.setenv("WEATHER_MARKET_REGISTRY", str(tmp_path / "absent.json"))
    from weather.model.toronto_model import TorontoHighTempModel

    model = object.__new__(TorontoHighTempModel)
    model.market_id = "synthetic"
    model.target_date = date(2000, 1, 1)
    model.spec = SimpleNamespace(
        display_unit=unit,
        tz=timezone.utc,
        sources=(),
        scale_delta=lambda value: value * (1.8 if unit == "F" else 1),
    )
    rows = [observation(400, early), observation(425, later)]
    for wall in (420, 450):
        record = build_historical_feature_record(
            model.target_date, rows, {}, 7, wall_minute=wall, unit=unit,
        )
        assert record["current_temp"] == early
        assert record["rise_from_7am"] == 0
    for surface in ("wu_history", "station_observations"):
        sources = {
            surface: {"ok": True, "data": {"rows": rows}},
            "wu_current": {"ok": True, "data": {"temp_native": early}},
        }
        assert model.extract_live_features(sources, 7)["rise_from_7am"] == 0


def test_future_only_reference_keeps_missingness_and_strict_admission():
    rows = [observation(359, 5), observation(421, 20)]
    assert build_historical_feature_record("2000-01-01", rows, {}, 7)["rise_from_7am"] is None
    assert build_historical_feature_record("2000-01-01", rows, {}, 7, strict=True) is None
    rows.insert(1, observation(360, 8))
    assert build_historical_feature_record("2000-01-01", rows, {}, 7, strict=True)["rise_from_7am"] == 0


def test_eight_o_clock_keeps_both_sides_and_existing_tie_order():
    rows = [observation(400, 40), observation(425, 55), observation(480, 61)]
    assert build_historical_feature_record("2000-01-01", rows, {}, 8)["rise_from_7am"] == 6
    rows[0] = observation(415, 40)
    assert build_historical_feature_record("2000-01-01", rows, {}, 8)["rise_from_7am"] == 21
