import csv
import gc
import inspect
import json
import tracemalloc

from weather.model.feature_store import FEATURE_SCHEMA_VERSION
from weather.reporting.candidate_lifecycle.current_max_trust_retrain_gate import (
    SCHEMA_VERSION,
    _iter_csv_rows,
    build_payload,
    current_max_summary,
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


def test_current_max_csv_summary_streams_in_source_order_with_equivalent_payload(tmp_path):
    current_max = tmp_path / "current_max.csv"
    rows = [
        {
            "market_id": "nyc",
            "target_date": "2026-06-21",
            "snapshot_id": "s3",
            "cutoff_hour": "8",
            "current_max_state": "wu_history_validated_current_max",
            "feature_disposition": "validated",
            "pre_reset": "False",
            "gap_to_current_temp": "0",
        },
        {
            "market_id": "nyc",
            "target_date": "2026-06-20",
            "snapshot_id": "s1",
            "cutoff_hour": "6",
            "current_max_state": "pre_reset_current_max_null",
            "feature_disposition": "null_before_reset",
            "pre_reset": "TRUE",
            "gap_to_current_temp": "11",
        },
        {
            "market_id": "toronto",
            "target_date": "2026-06-20",
            "snapshot_id": "s2",
            "cutoff_hour": "",
            "current_max_state": "",
            "feature_disposition": "",
            "pre_reset": "",
            "gap_to_current_temp": "not-a-number",
        },
    ]
    with current_max.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CURRENT_MAX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    assert inspect.isgeneratorfunction(_iter_csv_rows)
    assert [
        row["snapshot_id"]
        for row in _iter_csv_rows(current_max)
    ] == ["s3", "s1", "s2"]

    summary = current_max_summary(
        _iter_csv_rows(current_max),
        spill_directory=tmp_path,
    )

    assert summary == {
        "row_count": 3,
        "market_count": 2,
        "target_date_count": 2,
        "state_counts": {
            "pre_reset_current_max_null": 1,
            "unknown": 1,
            "wu_history_validated_current_max": 1,
        },
        "disposition_counts": {
            "null_before_reset": 1,
            "unknown": 1,
            "validated": 1,
        },
        "cutoff_hour_counts": {"": 1, "6": 1, "8": 1},
        "pre_reset_count": 1,
        "risky_or_guarded_count": 1,
        "max_gap_to_current_temp": 11.0,
    }
    assert not list(tmp_path.glob("current-max-trust-summary-*"))


def _write_memory_fixture(path, row_count):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CURRENT_MAX_FIELDS)
        writer.writeheader()
        for index in range(row_count):
            writer.writerow({
                "market_id": "nyc",
                "target_date": f"unique-target-date-{index:08d}",
                "snapshot_id": f"snapshot-{index:08d}",
                "cutoff_hour": "8",
                "current_max_state": "wu_history_validated_current_max",
                "feature_disposition": "validated",
                "pre_reset": "False",
                "gap_to_current_temp": "0",
            })


def _streamed_summary_peak(root, row_count):
    root.mkdir()
    current_max = root / "current_max.csv"
    _write_memory_fixture(current_max, row_count)
    gc.collect()
    tracemalloc.start()
    try:
        summary = current_max_summary(
            _iter_csv_rows(current_max),
            spill_directory=root,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak, summary


def test_current_max_summary_peak_memory_stays_bounded_as_distinct_dates_grow(tmp_path):
    small_peak, small_summary = _streamed_summary_peak(tmp_path / "small", 1_000)
    large_peak, large_summary = _streamed_summary_peak(tmp_path / "large", 25_000)

    assert small_summary["row_count"] == 1_000
    assert small_summary["target_date_count"] == 1_000
    assert large_summary["row_count"] == 25_000
    assert large_summary["target_date_count"] == 25_000
    assert large_peak <= small_peak + 1024 * 1024


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


def test_current_max_treatments_remove_or_promote_raw_values():
    from weather.reporting.candidate_lifecycle.current_max_trust_retrain_evidence import (
        raw_current_max_value,
        transform_current_max_row,
    )

    row = {
        "trusted_current_max": None,
        "support_only_current_max": 84.0,
        "quarantined_current_max": 91.0,
        "current_max_trusted_flag": 0.0,
        "current_max_support_only_flag": 1.0,
        "current_max_quarantined_flag": 1.0,
        "current_max_gap_to_history": 8.0,
        "current_max_gap_to_current_temp": 10.0,
        "current_max_state": "current_max_history_gap",
        "current_max_disposition": "quarantined",
        "current_max_quarantine_reason": "large_gap_to_wu_history",
    }

    assert raw_current_max_value(row) == 91.0

    no_current = transform_current_max_row(row, "no_current_max")
    assert no_current["trusted_current_max"] is None
    assert no_current["support_only_current_max"] is None
    assert no_current["quarantined_current_max"] is None
    assert no_current["current_max_trusted_flag"] == 0.0
    assert no_current["current_max_gap_to_history"] is None
    assert no_current["current_max_state"] == "missing_current_max"
    assert no_current["current_max_disposition"] == "missing"

    raw = transform_current_max_row(row, "raw_current_max")
    assert raw["trusted_current_max"] == 91.0
    assert raw["support_only_current_max"] is None
    assert raw["quarantined_current_max"] is None
    assert raw["current_max_trusted_flag"] == 1.0
    assert raw["current_max_support_only_flag"] == 0.0
    assert raw["current_max_quarantined_flag"] == 0.0
    assert raw["current_max_state"] == "raw_current_max_promoted"
    assert raw["current_max_disposition"] == "validated"


def test_artifact_trust_field_summary_requires_trainable_trust_values():
    from weather.reporting.candidate_lifecycle.current_max_trust_retrain_evidence import (
        artifact_trust_field_summary,
    )

    class FakeImputer:
        statistics_ = [
            float("nan"),
            float("nan"),
            float("nan"),
            0.0,
            0.0,
            0.0,
            float("nan"),
            float("nan"),
        ]

    artifact = {
        "models": {
            "7": {
                "feature_names": [
                    "trusted_current_max",
                    "support_only_current_max",
                    "quarantined_current_max",
                    "current_max_trusted_flag",
                    "current_max_support_only_flag",
                    "current_max_quarantined_flag",
                    "current_max_gap_to_history",
                    "current_max_gap_to_current_temp",
                ],
                "imputer": FakeImputer(),
            }
        }
    }

    summary = artifact_trust_field_summary(artifact)

    assert summary["all_hours_have_trust_fields"] is True
    assert summary["all_hours_have_trust_value_statistics"] is False
    assert summary["hours_without_trust_value_statistics"]["7"] == [
        "trusted_current_max",
        "support_only_current_max",
        "quarantined_current_max",
        "current_max_gap_to_history",
        "current_max_gap_to_current_temp",
    ]


def _score(candidate_brier, candidate_logloss=None, current_brier=None, current_logloss=None, n=100):
    candidate_logloss = candidate_logloss if candidate_logloss is not None else candidate_brier
    current_brier = current_brier if current_brier is not None else candidate_brier + 0.01
    current_logloss = current_logloss if current_logloss is not None else candidate_logloss + 0.01
    return {
        "n": n,
        "candidate_brier": candidate_brier,
        "candidate_logloss": candidate_logloss,
        "current_brier": current_brier,
        "current_logloss": current_logloss,
        "delta_vs_current": candidate_brier - current_brier,
    }


def test_current_max_ablation_decision_requires_no_regression():
    from weather.reporting.candidate_lifecycle.current_max_trust_retrain_evidence import (
        current_max_trust_ablation_decision,
    )

    mode_scores = {
        "trust_weighted": {
            "risky_current_max": _score(0.05),
            "warm_tail": _score(0.06),
            "early_hour": _score(0.07, 0.2),
            "late_lock_in": _score(0.01),
            "daily_first": _score(0.04),
        },
        "raw_current_max": {
            "risky_current_max": _score(0.08),
            "warm_tail": _score(0.07),
            "early_hour": _score(0.071, 0.201),
            "late_lock_in": _score(0.011),
            "daily_first": _score(0.041),
        },
        "no_current_max": {
            "daily_first": _score(0.042),
        },
    }
    passing = current_max_trust_ablation_decision(mode_scores)
    assert passing["status"] == "PASS"

    mode_scores["trust_weighted"]["early_hour"] = _score(0.08, 0.25)
    blocked = current_max_trust_ablation_decision(mode_scores)
    assert blocked["status"] == "BLOCK"
    assert any(check["check"] == "early_hour_brier_vs_raw" for check in blocked["failed_checks"])


def test_current_max_ablation_decision_blocks_flat_or_warm_tail_regression():
    from weather.reporting.candidate_lifecycle.current_max_trust_retrain_evidence import (
        current_max_trust_ablation_decision,
    )

    flat_score = _score(0.05)
    mode_scores = {
        "trust_weighted": {
            "risky_current_max": flat_score,
            "warm_tail": _score(0.06, current_brier=0.059),
            "early_hour": flat_score,
            "late_lock_in": flat_score,
            "daily_first": flat_score,
        },
        "raw_current_max": {
            "risky_current_max": flat_score,
            "warm_tail": _score(0.06, current_brier=0.059),
            "early_hour": flat_score,
            "late_lock_in": flat_score,
            "daily_first": flat_score,
        },
        "no_current_max": {
            "daily_first": flat_score,
        },
    }

    blocked = current_max_trust_ablation_decision(mode_scores)

    assert blocked["status"] == "BLOCK"
    failed = {check["check"] for check in blocked["failed_checks"]}
    assert "warm_tail_brier_vs_current" in failed
    assert "current_max_ablation_mode_sensitivity" in failed
