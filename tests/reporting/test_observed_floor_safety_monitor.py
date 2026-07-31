import csv
import json
from pathlib import Path

from weather.reporting.source_gates.observed_floor_safety_monitor import (
    build_payload,
    main,
    render_report,
)


TARGET_DATE = "2026-07-30"


def _write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_market(root, *, market_id, settlement_bucket, contexts):
    folder = Path(root) / market_id
    tape = folder / "snapshots_long.csv"
    _write_csv(
        tape,
        [
            {"snapshot_id": snapshot_id, "range_label": label}
            for snapshot_id in contexts
            for label in ("low", "high")
        ],
    )
    explanations = []
    for snapshot_id, context in contexts.items():
        explanations.append({
            "snapshot_id": snapshot_id,
            "market_id": market_id,
            "target_date": TARGET_DATE,
            "explanations": {"probability_calibration_context": context},
        })
    (folder / "snapshot_explanations.jsonl").write_text(
        "\n".join(json.dumps(row) for row in explanations) + "\n",
        encoding="utf-8",
    )
    return {
        "event_slug": f"{market_id}-{TARGET_DATE}",
        "market_id": market_id,
        "target_date": TARGET_DATE,
        "settlement_bucket": str(settlement_bucket),
        "settlement_source": "daily_summary",
        "snapshot_tape_path": str(tape),
    }


def test_monitor_passes_complete_c_and_f_evidence_with_zero_overshoot(tmp_path):
    labels = [
        _write_market(
            tmp_path,
            market_id="dallas",
            settlement_bucket=97,
            contexts={
                "f1": {
                    "observed_floor_bucket": 97,
                    "effective_observed_floor_bucket": 97,
                    "effective_observed_high_source": "current_or_station_max_since_7am",
                },
                "f2": {
                    "observed_floor_bucket": None,
                    "effective_observed_floor_bucket": None,
                    "effective_observed_high_source": None,
                },
            },
        ),
        _write_market(
            tmp_path,
            market_id="toronto",
            settlement_bucket=27,
            contexts={
                "c1": {
                    "observed_floor_bucket": 26,
                    "effective_observed_floor_bucket": 26,
                    "effective_observed_high_source": "cutoff_aligned_current_observation",
                }
            },
        ),
    ]
    labels_csv = tmp_path / "labels.csv"
    _write_csv(labels_csv, labels)

    payload = build_payload(
        labels_csv=labels_csv,
        target_date=TARGET_DATE,
        generated_at_utc="2026-07-31T12:00:00+00:00",
    )

    assert payload["schema_version"] == "observed_floor_safety_monitor_v0.1"
    assert payload["status"] == "PASS"
    assert payload["enforcement_mode"] == "alert_only"
    assert payload["hard_stop_pipeline"] is False
    assert payload["summary"] == {
        "label_count": 2,
        "snapshot_count": 3,
        "enforced_floor_count": 2,
        "floorless_snapshot_count": 1,
        "over_final_count": 0,
        "evidence_blocker_count": 0,
        "rescue_source_counts": {
            "current_or_station_max_since_7am": 1,
            "cutoff_aligned_current_observation": 1,
        },
    }
    assert payload["alerts"] == []


def test_single_over_final_floor_is_a_loud_alert(tmp_path):
    label = _write_market(
        tmp_path,
        market_id="toronto",
        settlement_bucket=27,
        contexts={
            "c1": {
                "observed_floor_bucket": 28,
                "effective_observed_floor_bucket": 28,
                "effective_observed_high_source": "current_or_station_max_since_7am",
            }
        },
    )
    labels_csv = tmp_path / "labels.csv"
    _write_csv(labels_csv, [label])

    payload = build_payload(labels_csv=labels_csv, target_date=TARGET_DATE)
    report = render_report(payload)

    assert payload["status"] == "ALERT"
    assert payload["enforcement_mode"] == "alert_only"
    assert payload["hard_stop_pipeline"] is False
    assert payload["summary"]["over_final_count"] == 1
    assert payload["alerts"] == [{
        "market_id": "toronto",
        "event_slug": f"toronto-{TARGET_DATE}",
        "target_date": TARGET_DATE,
        "snapshot_id": "c1",
        "floor_bucket": 28,
        "settlement_bucket": 27,
        "rescue_source": "current_or_station_max_since_7am",
        "overshoot_buckets": 1,
        "over_final": True,
    }]
    assert "OVER-FINAL ALERTS" in report
    assert "| toronto | 2026-07-30 | c1 | 28 | 27 |" in report

    fail_closed = build_payload(
        labels_csv=labels_csv,
        target_date=TARGET_DATE,
        fail_closed=True,
    )
    assert fail_closed["status"] == "ALERT"
    assert fail_closed["enforcement_mode"] == "fail_closed"
    assert fail_closed["hard_stop_pipeline"] is True


def test_missing_explanation_is_a_visible_evidence_blocker(tmp_path):
    label = _write_market(
        tmp_path,
        market_id="dallas",
        settlement_bucket=97,
        contexts={
            "f1": {
                "observed_floor_bucket": 97,
                "effective_observed_floor_bucket": 97,
                "effective_observed_high_source": "wu_history",
            }
        },
    )
    folder = Path(label["snapshot_tape_path"]).parent
    _write_csv(
        label["snapshot_tape_path"],
        [{"snapshot_id": "f1"}, {"snapshot_id": "f2"}],
    )
    labels_csv = tmp_path / "labels.csv"
    _write_csv(labels_csv, [label])

    payload = build_payload(labels_csv=labels_csv, target_date=TARGET_DATE)

    assert payload["status"] == "BLOCK"
    assert payload["enforcement_mode"] == "alert_only"
    assert payload["hard_stop_pipeline"] is False
    assert payload["summary"]["evidence_blocker_count"] == 1
    assert payload["evidence_blockers"][0]["reason"] == "snapshot_explanation_missing"
    assert payload["evidence_blockers"][0]["snapshot_id"] == "f2"
    assert (folder / "snapshot_explanations.jsonl").exists()


def test_cli_alert_only_and_explicit_fail_closed_exit_codes(tmp_path):
    label = _write_market(
        tmp_path,
        market_id="dallas",
        settlement_bucket=96,
        contexts={
            "f1": {
                "observed_floor_bucket": 97,
                "effective_observed_floor_bucket": 97,
                "effective_observed_high_source": "cutoff_aligned_current_observation",
            }
        },
    )
    labels_csv = tmp_path / "labels.csv"
    _write_csv(labels_csv, [label])
    json_out = tmp_path / "monitor.json"
    report_out = tmp_path / "monitor.md"

    returncode = main([
        "--labels-csv",
        str(labels_csv),
        "--target-date",
        TARGET_DATE,
        "--json-out",
        str(json_out),
        "--report-out",
        str(report_out),
    ])

    assert returncode == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["status"] == "ALERT"
    assert "OVER-FINAL ALERTS" in report_out.read_text(encoding="utf-8")

    returncode = main([
        "--labels-csv",
        str(labels_csv),
        "--target-date",
        TARGET_DATE,
        "--json-out",
        str(json_out),
        "--report-out",
        str(report_out),
        "--fail-closed",
    ])

    assert returncode == 1
    assert json.loads(json_out.read_text(encoding="utf-8"))["enforcement_mode"] == "fail_closed"
