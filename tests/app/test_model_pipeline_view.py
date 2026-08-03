from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.table_utils import csv_data_row_count
from app.views.model_pipeline import (
    floor_binding_summary,
    pipeline_distribution_frame,
    pipeline_stage_rows,
)


def _model_fixture():
    return {
        "distribution_components": {
            "cutoff_hour": 12,
            "observed_floor_bucket": 69,
            "components": {
                "climatology_prior": {"68": 0.20, "69": 0.50, "70": 0.30},
                "hgb_feature_model": {"68": 0.10, "69": 0.35, "70": 0.55},
                "post_live_signals": {"68": 0.30, "69": 0.40, "70": 0.30},
                "settlement_lag_adjusted": {"68": 0.000001, "69": 0.55, "70": 0.449999},
                "current_observed_floor": {"68": 0.000001, "69": 0.54, "70": 0.459999},
                "wu_floor_residual": {"68": 0.000001, "69": 0.53, "70": 0.469999},
                "pre_calibration_model": {"68": 0.000001, "69": 0.52, "70": 0.479999},
                "overconfidence_calibration": {"68": 0.000001, "69": 0.49, "70": 0.509999},
                "final_model": {"68": 0.000001, "69": 0.48, "70": 0.519999},
            },
        },
        "model_rows": [
            {
                "Range": "68 F",
                "Model": "0.0%",
                "Market yes": "4.0%",
                "Edge": "-4.0%",
                "Market status": "active",
            },
            {
                "Range": "69 F",
                "Model": "48.0%",
                "Market yes": "44.0%",
                "Edge": "+4.0%",
                "Market status": "active",
            },
        ],
    }


def test_pipeline_rows_keep_absent_stages_and_expose_floor_binding():
    model = _model_fixture()
    payload = model["distribution_components"]

    floor = floor_binding_summary(payload)
    rows = pipeline_stage_rows(payload, unit="F")
    by_key = {row["Stage key"]: row for row in rows}

    assert floor["status"] == "BINDING"
    assert floor["pre_floor_mass_below"] == 0.30
    assert floor["final_mass_below"] == 0.000001
    assert by_key["feature_blend"]["Snapshot"] == "Absent"
    assert by_key["feature_blend"]["Centre"] == "-"
    assert by_key["hgb_feature_model"]["Snapshot"] == "Present"
    assert by_key["trusted_observed_high_floor"]["Snapshot"] == "Unavailable"
    assert "30.00% pre-floor mass" in by_key["trusted_observed_high_floor"]["Detail"]
    assert by_key["final_model"]["Centre"].endswith(" F")
    assert [row["Order"] for row in rows] == list(range(1, len(rows) + 1))


def test_pipeline_distribution_matrix_contains_only_recorded_states():
    frame = pipeline_distribution_frame(
        _model_fixture()["distribution_components"],
        unit="F",
    )

    assert list(frame.index) == ["68 F", "69 F", "70 F"]
    assert "Base climatology" in frame.columns
    assert "HGB feature model" in frame.columns
    assert "Final served distribution" in frame.columns
    assert "Feature-model blend" not in frame.columns
    assert frame.loc["69 F", "Final served distribution"] == 0.48


def test_pipeline_panel_visible_behavior_uses_recorded_cutoff_floor_and_market_rows():
    script = "\n".join((
        "from app.views.model_pipeline import render_pipeline_model_view",
        f"model = {_model_fixture()!r}",
        "render_pipeline_model_view(model, market_label='Fixture City', unit='F')",
    ))
    app_test = AppTest.from_string(script).run()

    assert not app_test.exception
    assert "Pipeline Centre Movement" in [item.value for item in app_test.subheader]
    assert any(
        "Final served distribution vs market implied distribution" in item.value
        for item in app_test.markdown
    )
    metrics = {item.label: item.value for item in app_test.metric}
    assert metrics["Effective cutoff"] == "12:00"
    assert metrics["Trusted floor"] == "69 F"
    assert metrics["Floor state"] == "BINDING"
    assert metrics["Pre-floor mass truncated"] == "30.00%"
    assert len(app_test.dataframe) >= 2


def test_csv_data_row_count_distinguishes_empty_missing_and_unreadable(tmp_path, monkeypatch):
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")

    assert csv_data_row_count(csv_path) == 2
    assert csv_data_row_count(tmp_path / "missing.csv") == 0

    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("locked")))
    assert csv_data_row_count(csv_path) is None
