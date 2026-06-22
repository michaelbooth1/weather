import csv
import json

from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.reporting.current_max_trust_retrain_gate import (
    SCHEMA_VERSION,
    build_payload,
    write_outputs,
)


CURRENT_MAX_FIELDS = [
    "market_id",
    "target_date",
    "snapshot_id",
    "cutoff_hour",
    "current_max_state",
    "feature_disposition",
    "pre_reset",
    "gap_to_current_temp",
]


def write_current_max(path):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CURRENT_MAX_FIELDS)
        writer.writeheader()
        writer.writerows([
            {
                "market_id": "nyc",
                "target_date": "2026-06-20",
                "snapshot_id": "s1",
                "cutoff_hour": "6",
                "current_max_state": "pre_reset_current_max_null",
                "feature_disposition": "null_before_reset",
                "pre_reset": "True",
                "gap_to_current_temp": "11",
            },
            {
                "market_id": "nyc",
                "target_date": "2026-06-20",
                "snapshot_id": "s2",
                "cutoff_hour": "8",
                "current_max_state": "wu_history_validated_current_max",
                "feature_disposition": "validated",
                "pre_reset": "False",
                "gap_to_current_temp": "0",
            },
        ])


def write_feature_quality(path):
    path.write_text(
        json.dumps({
            "schema_version": "feature_quality_quarantine_v0.1",
            "summary": {
                "schema_version": "feature_quality_quarantine_summary_v0.1",
                "scanned_feature_row_count": 20,
                "quarantine_row_count": 2,
                "training_excluded_row_count": 2,
                "raw_evidence_absent_row_count": 2,
                "reason_counts": {
                    "current_max_exceeds_observed_support": 2,
                },
            },
        }),
        encoding="utf-8",
    )


def write_root_cause(path):
    path.write_text(
        json.dumps({
            "schema_version": "settled_day_root_cause_v0.1",
            "target_date": "2026-06-20",
            "status": "ACTIONABLE",
            "summary": {
                "snapshot_count": 10,
                "issue_count": 3,
                "issue_counts": {
                    "WU_CURRENT_MAX_ANOMALY": 2,
                    "RAMP_WINDOW_WARM_TAIL_SPREAD": 1,
                    "TAKER_BOUGHT_WARM_TAIL": 1,
                    "LATE_DAY_LOCKIN_UNDER_COVERAGE": 0,
                },
            },
        }),
        encoding="utf-8",
    )


def test_gate_blocks_without_retrained_artifact_evidence(tmp_path):
    current_max = tmp_path / "current_max.csv"
    feature_quality = tmp_path / "feature_quality.json"
    root_cause = tmp_path / "root_cause.json"
    write_current_max(current_max)
    write_feature_quality(feature_quality)
    write_root_cause(root_cause)

    payload = build_payload(
        current_max_csv=current_max,
        feature_quality_json=feature_quality,
        root_cause_json=root_cause,
    )
    json_out, report_out = write_outputs(payload, tmp_path / "out.json", tmp_path / "out.md")
    report = report_out.read_text(encoding="utf-8")

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["status"] == "BLOCK"
    assert payload["current_max_carryover"]["row_count"] == 2
    assert payload["june20_root_cause"]["wu_current_max_anomaly_count"] == 2
    assert any(gate["gate"] == "retrained_artifact_evidence" for gate in payload["blockers"])
    assert json_out.exists()
    assert "Current-Max Trust Retrain Gate" in report


def test_gate_passes_with_matching_retrain_and_ablation_report(tmp_path):
    current_max = tmp_path / "current_max.csv"
    feature_quality = tmp_path / "feature_quality.json"
    root_cause = tmp_path / "root_cause.json"
    retrain = tmp_path / "retrain.json"
    write_current_max(current_max)
    write_feature_quality(feature_quality)
    write_root_cause(root_cause)
    retrain.write_text(
        json.dumps({
            "schema_version": "fake_training_report_v0.1",
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "current_max_trust_ablation": {
                "status": "PASS",
                "trust_weighted_delta_vs_raw": -0.01,
            },
        }),
        encoding="utf-8",
    )

    payload = build_payload(
        current_max_csv=current_max,
        feature_quality_json=feature_quality,
        root_cause_json=root_cause,
        retrain_report_json=retrain,
    )

    assert payload["status"] == "PASS"
    assert payload["blocker_count"] == 0
