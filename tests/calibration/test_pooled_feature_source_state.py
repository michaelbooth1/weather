from weather.calibration import pooled_feature_model
from weather.calibration.pooled_feature_source_state import (
    add_dynamic_source_state_features,
    dynamic_source_state_features,
    feature_names_need_dynamic_source_state,
)


def test_dynamic_source_state_owner_matches_facade_exports():
    assert pooled_feature_model.dynamic_source_state_features is dynamic_source_state_features
    assert pooled_feature_model.add_dynamic_source_state_features is add_dynamic_source_state_features
    assert pooled_feature_model.feature_names_need_dynamic_source_state is feature_names_need_dynamic_source_state


def test_dynamic_source_state_features_capture_failed_stale_and_ages():
    features = dynamic_source_state_features(
        sources={
            "wu_history": {
                "ok": True,
                "fetched_at": "2026-06-20T12:00:00+00:00",
                "data": {"rows": [{"time": "09:30"}]},
            },
            "metar": {"stale": True, "age_minutes": 45},
            "open_meteo": {"status": "failed"},
        },
        captured_at="2026-06-20T12:30:00+00:00",
        base_features={"forecast_disagreement": 1.25},
    )

    assert features["source_wu_history_fresh"] == 1.0
    assert features["source_wu_history_age_minutes"] == 30.0
    assert features["source_wu_history_latest_minute"] == 570
    assert features["source_metar_stale"] == 1.0
    assert features["source_forecast_failed_count"] == 1.0
    assert features["source_cross_source_max_disagreement"] == 1.25
    assert "failed:" in features["source_status_group"]
    assert "stale:metar" in features["source_status_group"]


def test_dynamic_source_state_can_derive_from_source_status_rows():
    features = dynamic_source_state_features(
        source_status_rows=[
            {"source": "wu_history", "ok": True, "row_count": 3, "age_minutes": 5},
            {"source": "metar", "ok": True, "age_minutes": 2},
        ],
    )

    assert features["source_status_group"] == "all_fresh"
    assert features["source_wu_history_row_count"] == 3.0
    assert features["source_wu_history_age_minutes"] == 5.0
