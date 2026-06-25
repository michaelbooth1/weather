import csv
import json
from pathlib import Path

from weather.reporting.candidate_lifecycle.model_market_disagreement_audit import (
    DEFAULT_GAP_THRESHOLD_POINTS,
    build_audit_records,
    ensure_audit_record_saved,
    load_audit_index,
    read_audit_log,
    read_snapshot_rows,
    run_audit,
    audit_saved_for_row,
)


SNAPSHOT_COLUMNS = [
    "snapshot_id",
    "captured_at_utc",
    "captured_at_local",
    "event_slug",
    "model_version",
    "range_label",
    "bin_kind",
    "bin_value_c",
    "bin_value_hi_c",
    "model_probability",
    "market_yes",
    "market_no",
    "edge",
]


def write_snapshot_folder(root, *, slug, rows, settlement_bucket=None):
    folder = Path(root) / slug
    folder.mkdir(parents=True)
    with (folder / "snapshots_long.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SNAPSHOT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if settlement_bucket is not None:
        (folder / "settlement.json").write_text(
            json.dumps({
                "event_slug": slug,
                "market_id": "nyc",
                "settlement_bucket": settlement_bucket,
                "settlement_high": settlement_bucket,
                "settlement_unit": "F",
                "winning_band": f"{settlement_bucket}-{settlement_bucket + 1} F",
                "quality_grade": "complete",
                "settlement_source": "daily_summary",
                "reconciliation_status": "match",
            }),
            encoding="utf-8",
        )
    return folder


def snapshot_row(snapshot_id, label, low, high, model, market):
    return {
        "snapshot_id": snapshot_id,
        "captured_at_utc": "2099-06-23T14:00:00+00:00",
        "captured_at_local": "2099-06-23T10:00:00-04:00",
        "event_slug": "highest-temperature-in-nyc-on-june-23-2099",
        "model_version": "test-model",
        "range_label": label,
        "bin_kind": "eq",
        "bin_value_c": low,
        "bin_value_hi_c": high,
        "model_probability": model,
        "market_yes": market,
        "market_no": 1.0 - market,
        "edge": model - market,
    }


def test_audit_uses_full_percentage_point_threshold_and_scores_settlement(tmp_path):
    slug = "highest-temperature-in-nyc-on-june-23-2099"
    rows = [
        snapshot_row("s1", "70-71 F", 70, 71, 0.05, 0.86),
        snapshot_row("s1", "72-73 F", 72, 73, 0.55, 0.05),
        snapshot_row("s1", "74-75 F", 74, 75, 0.10, 0.55),
    ]
    folder = write_snapshot_folder(tmp_path, slug=slug, rows=rows, settlement_bucket=70)

    records = build_audit_records(
        [folder],
        latest_only=False,
        gap_threshold_points=50.0,
        run_id="test-run",
        audited_at_utc="2099-06-24T00:00:00+00:00",
    )

    by_label = {record["range_label"]: record for record in records}
    assert set(by_label) == {"70-71 F", "72-73 F"}
    nyc_record = by_label["70-71 F"]
    assert nyc_record["gap_points"] == 81.0
    assert nyc_record["fair_value_percent"] == 100.0
    assert nyc_record["closer_source"] == "market"
    assert nyc_record["model_distance_points"] == 95.0
    assert nyc_record["market_distance_points"] == 14.0

    exact_threshold = by_label["72-73 F"]
    assert exact_threshold["gap_points"] == 50.0
    assert exact_threshold["fair_value_percent"] == 0.0
    assert exact_threshold["closer_source"] == "market"


def test_default_audit_threshold_is_thirty_percentage_points(tmp_path):
    slug = "highest-temperature-in-nyc-on-june-23-2099"
    rows = [
        snapshot_row("s1", "70-71 F", 70, 71, 0.40, 0.72),
        snapshot_row("s1", "72-73 F", 72, 73, 0.40, 0.69),
    ]
    folder = write_snapshot_folder(tmp_path, slug=slug, rows=rows, settlement_bucket=70)

    records = build_audit_records(
        [folder],
        latest_only=False,
        run_id="test-run",
        audited_at_utc="2099-06-24T00:00:00+00:00",
    )

    assert DEFAULT_GAP_THRESHOLD_POINTS == 30.0
    assert [record["range_label"] for record in records] == ["70-71 F"]
    assert records[0]["gap_threshold_points"] == 30.0


def test_run_audit_writes_idempotent_log_and_resolves_later_settlement(tmp_path):
    slug = "highest-temperature-in-nyc-on-june-23-2099"
    rows = [snapshot_row("s1", "70-71 F", 70, 71, 0.05, 0.86)]
    folder = write_snapshot_folder(tmp_path, slug=slug, rows=rows, settlement_bucket=None)
    log_path = tmp_path / "model_market_disagreement_audit.jsonl"

    first = run_audit([folder], log_path=log_path, gap_threshold_points=50.0)
    assert first["candidate_count"] == 1
    assert first["written_count"] == 1
    assert first["pending_settlement_count"] == 1

    second = run_audit([folder], log_path=log_path, gap_threshold_points=50.0)
    assert second["written_count"] == 0
    assert second["skipped_duplicate_count"] == 1

    (folder / "settlement.json").write_text(
        json.dumps({
            "event_slug": slug,
            "market_id": "nyc",
            "settlement_bucket": 70,
            "settlement_high": 70,
            "settlement_unit": "F",
            "winning_band": "70-71 F",
            "quality_grade": "complete",
            "settlement_source": "daily_summary",
        }),
        encoding="utf-8",
    )

    third = run_audit([folder], log_path=log_path, gap_threshold_points=50.0)
    rows = read_audit_log(log_path)
    assert third["written_count"] == 1
    assert len(rows) == 2
    assert rows[-1]["audit_revision"] == 2
    assert rows[-1]["status"] == "resolved"
    assert rows[-1]["fair_value_percent"] == 100.0
    assert rows[-1]["closer_source"] == "market"


def test_audit_saved_for_row_matches_logged_snapshot_band(tmp_path):
    slug = "highest-temperature-in-nyc-on-june-23-2099"
    rows = [snapshot_row("s1", "70-71 F", 70, 71, 0.05, 0.86)]
    folder = write_snapshot_folder(tmp_path, slug=slug, rows=rows, settlement_bucket=70)
    log_path = tmp_path / "audit.jsonl"
    run_audit([folder], log_path=log_path, gap_threshold_points=50.0)

    audit_index = load_audit_index(log_path)
    row = read_snapshot_rows(folder)[0]

    assert audit_saved_for_row(row, audit_index=audit_index, gap_threshold_points=50.0)
    assert audit_saved_for_row(row, audit_index=audit_index, gap_threshold_points=60.0)
    assert not audit_saved_for_row(row, audit_index=audit_index, gap_threshold_points=90.0)


def test_ensure_audit_record_saved_writes_positive_and_negative_gap_directions(tmp_path):
    slug = "highest-temperature-in-nyc-on-june-23-2099"
    rows = [
        snapshot_row("s1", "70-71 F", 70, 71, 0.05, 0.86),
        snapshot_row("s1", "84-85 F", 84, 85, 0.76, 0.10),
    ]
    folder = write_snapshot_folder(tmp_path, slug=slug, rows=rows, settlement_bucket=None)
    log_path = tmp_path / "audit.jsonl"
    audit_index = {}

    latest_rows = read_snapshot_rows(folder, latest_only=False)
    negative = ensure_audit_record_saved(
        latest_rows[0],
        folder=folder,
        log_path=log_path,
        audit_index=audit_index,
        gap_threshold_points=50.0,
    )
    positive = ensure_audit_record_saved(
        latest_rows[1],
        folder=folder,
        log_path=log_path,
        audit_index=audit_index,
        gap_threshold_points=50.0,
    )

    rows = read_audit_log(log_path)
    assert negative["triggered"] is True
    assert negative["saved"] is True
    assert positive["triggered"] is True
    assert positive["saved"] is True
    assert len(rows) == 2
    assert rows[0]["model_minus_market_points"] < -50.0
    assert rows[1]["model_minus_market_points"] > 50.0
    assert len(audit_index) == 2
