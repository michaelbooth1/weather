import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.market.market_registry import all_specs
from weather.model.feature_store import FEATURE_COLUMNS
from weather.reporting.scorecards.train_serve_feature_parity import (
    CASE_SCHEMA_VERSION,
    REPORT_SCHEMA_VERSION,
    TrainServeFeatureParityError,
    compare_feature_records,
    evaluate_manifest,
    main,
    render_markdown,
    write_outputs,
)


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "train_serve_feature_parity_known_defects_v0.1.json"
)


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_known_defect_proof_covers_all_markets_and_features(tmp_path):
    report = evaluate_manifest(
        _fixture(),
        run_root=tmp_path,
        generated_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
    )

    expected_markets = sorted(spec.id for spec in all_specs())
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["status"] == "BLOCK"
    assert report["coverage"]["expected_market_ids"] == expected_markets
    assert report["coverage"]["full_schema_market_ids"] == expected_markets
    assert report["coverage"]["feature_names"] == list(FEATURE_COLUMNS)
    assert report["summary"]["coverage_blocker_count"] == 0
    assert report["summary"]["all_known_defects_rediscovered"] is True
    assert report["summary"]["known_defects_rediscovered"] == 4
    assert len(report["input_identity"]["case_manifest_sha256"]) == 64

    by_id = {row["defect_id"]: row for row in report["known_defect_proof"]}
    assert set(by_id) == {
        "nine_empty_base_features_09_to_14",
        "stitched_forecast_high_without_issue_time",
        "forecast_profile_provenance_discarded_by_loader",
        "wu_surface_payload_not_known_at_cutoff",
    }
    assert all(row["rediscovered"] for row in by_id.values())
    assert set(by_id["nine_empty_base_features_09_to_14"]["found_markets"]) == set(expected_markets)
    assert set(by_id["wu_surface_payload_not_known_at_cutoff"]["found_fields"]) >= {
        "rise_from_7am",
        "warming_rate_2h",
        "hours_at_peak",
        "dewpoint_c",
        "humidity",
        "pressure",
        "pressure_trend_3h",
        "wind_speed_kmh",
        "wind_group",
        "cloud_group",
    }
    assert {
        (row["field"], row["dimension"])
        for row in report["unexpected_findings"]
    } == {
        ("wind_gust_kmh", "missingness"),
        ("wind_shift_3h_degrees", "missingness"),
    }
    assert {
        row["market_id"] for row in report["unexpected_findings"]
    } == set(expected_markets)


def test_findings_name_field_market_cutoff_dimension_and_direction(tmp_path):
    report = evaluate_manifest(_fixture(), run_root=tmp_path)
    finding = next(
        row for row in report["findings"]
        if row.get("known_defect_id") == "nine_empty_base_features_09_to_14"
    )
    assert finding["market_id"]
    assert finding["field"]
    assert finding["cutoff_at"]
    assert finding["dimension"] == "missingness"
    assert finding["direction"].startswith("training=")
    assert "serving=" in finding["direction"]


def test_four_dimensions_plus_availability_and_provenance_are_independent():
    feature = "wind_group"
    case = {
        "case_id": "dimension-proof",
        "kind": "unit_test",
        "market_id": "toronto",
        "market_unit": "C",
        "cutoff_at": "2025-06-15T14:00:00-04:00",
    }
    train_record = {feature: "W-NW"}
    serve_record = {feature: "S-SW"}
    train_meta = {feature: {
        "source_id": "train-source",
        "available_at": "2025-06-15T13:55:00-04:00",
        "provenance_state": "verified",
        "unit": "canonical_category",
    }}
    serve_meta = {feature: {
        "source_id": None,
        "available_at": "2025-06-15T14:05:00-04:00",
        "provenance_state": "discarded",
        "unit": "raw_provider_category",
    }}

    findings, coverage = compare_feature_records(
        case=case,
        training_record=train_record,
        serving_record=serve_record,
        training_metadata=train_meta,
        serving_metadata=serve_meta,
        features=(feature,),
    )

    assert not coverage
    dimensions = {row["dimension"] for row in findings}
    assert dimensions == {"value", "unit", "category", "availability", "provenance"}


def test_missingness_does_not_get_mislabeled_as_value_or_provenance():
    feature = "pressure"
    case = {
        "case_id": "missing-proof",
        "kind": "unit_test",
        "market_id": "toronto",
        "market_unit": "C",
        "cutoff_at": "2025-06-15T14:00:00-04:00",
    }
    metadata = {feature: {
        "source_id": "wu_history",
        "available_at": "2025-06-15T13:55:00-04:00",
        "provenance_state": "verified",
    }}
    findings, _ = compare_feature_records(
        case=case,
        training_record={feature: 1014.0},
        serving_record={feature: None},
        training_metadata=metadata,
        serving_metadata={feature: {}},
        features=(feature,),
    )
    assert [row["dimension"] for row in findings] == ["missingness"]


def test_floor_exception_is_exact_and_does_not_suppress_known_defects(tmp_path):
    report = evaluate_manifest(_fixture(), run_root=tmp_path)
    exceptions = report["false_positive_characterization"]["explicit_exception_findings"]
    assert len(exceptions) == 1
    assert exceptions[0]["case_id"] == "trusted-floor-exception"
    assert exceptions[0]["field"] == "high_so_far"
    assert exceptions[0]["dimension"] == "value"
    assert report["summary"]["blocking_finding_count"] > 0


def test_rejects_wildcard_exception(tmp_path):
    payload = _fixture()
    payload["exceptions"][0]["field"] = "*"
    with pytest.raises(TrainServeFeatureParityError, match="exceptions must be exact"):
        evaluate_manifest(payload, run_root=tmp_path)


def test_rejects_output_under_data(tmp_path, monkeypatch):
    forbidden = tmp_path / "data"
    monkeypatch.setattr(
        "weather.reporting.scorecards.train_serve_feature_parity.data_path",
        lambda *parts: forbidden.joinpath(*parts),
    )
    with pytest.raises(TrainServeFeatureParityError, match="outside data"):
        evaluate_manifest(_fixture(), run_root=forbidden / "report")


def test_output_and_markdown_preserve_machine_readable_verdict(tmp_path):
    report = evaluate_manifest(_fixture(), run_root=tmp_path)
    json_path, markdown_path = write_outputs(report, run_root=tmp_path)
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert persisted["report_sha256"] == report["report_sha256"]
    assert "## Previously unknown findings" in markdown
    assert "4 / 4 known defects rediscovered" in markdown
    assert render_markdown(report) == markdown


def test_proof_mode_exits_zero_for_a_red_gate_that_rediscovers_the_defects(tmp_path):
    assert main([
        "--input",
        str(FIXTURE),
        "--run-root",
        str(tmp_path),
        "--proof-mode",
    ]) == 0
    assert (tmp_path / "train-serve-feature-parity.json").exists()
    assert (tmp_path / "train-serve-feature-parity.md").exists()


def test_manifest_schema_is_registered():
    assert CASE_SCHEMA_VERSION == "train_serve_feature_parity_case_v0.1"
    assert REPORT_SCHEMA_VERSION == "train_serve_feature_parity_v0.1"
