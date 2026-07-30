import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from weather.backtesting.settlement_ledger import upsert_ledger_record
from weather.captured_input_hash import captured_input_payload_sha256
from weather.operations.release_admissibility_clock import (
    CLOCK_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    collapse_receipts,
    grade_market_day,
)
from weather.release_artifacts import canonical_payload_sha256


TARGET = date(2026, 7, 24)
SLUG = "highest-temperature-in-toronto-on-july-24-2026"


def _write_pass_fixture(root: Path) -> tuple[Path, Path, Path]:
    snapshots_root = root / "snapshots"
    ledger_root = root / "settlements"
    folder = snapshots_root / SLUG
    folder.mkdir(parents=True)
    snapshot_path = folder / "snapshots_long.csv"
    with snapshot_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "snapshot_id",
                "captured_at_utc",
                "captured_at_local",
                "event_slug",
                "target_date",
                "range_label",
                "bin_kind",
                "bin_value_c",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "snapshot_id": "s1",
                "captured_at_utc": "2026-07-24T12:00:00+00:00",
                "captured_at_local": "2026-07-24T08:00:00-04:00",
                "event_slug": SLUG,
                "target_date": TARGET.isoformat(),
                "range_label": "25 C",
                "bin_kind": "eq",
                "bin_value_c": "25",
            }
        )
    snapshot_sha = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    label = {
        "schema_version": "settlement_ledger_v2",
        "event_slug": SLUG,
        "market_id": "toronto",
        "target_date": TARGET.isoformat(),
        "settlement_bucket": 25,
        "settlement_unit": "C",
        "settlement_source": "wu_history",
        "winning_band": "25 C",
        "winning_band_kind": "eq",
        "winning_band_value": 25,
        "winning_band_value_hi": 25,
        "quality_grade": "complete",
        "row_count": 1,
        "snapshot_count": 1,
        "band_count": 1,
        "finalized_at_utc": "2026-07-25T04:00:00+00:00",
        "evidence": {
            "five_time_provenance": {},
            "raw_resolution_hashes": {"snapshot_tape_sha256": snapshot_sha},
            "override_provenance": {},
        },
    }
    upsert_ledger_record(label, ledger_root)
    (folder / "settlement.json").write_text(
        json.dumps(label, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    status = {
        "schema_version": "replay_input_status_v0.1",
        "snapshot_count": 1,
        "captured_count": 1,
        "evaluation_only_count": 0,
        "reconstructed_count": 0,
        "counts": {"captured": 1},
    }
    (folder / "replay_input_status.json").write_text(
        json.dumps(status, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (folder / "replay_input_status_long.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "snapshot_id",
                "captured_at_utc",
                "captured_at_local",
                "event_slug",
                "replay_input_status",
                "replay_input_source",
                "reason",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "snapshot_id": "s1",
                "captured_at_utc": "2026-07-24T12:00:00+00:00",
                "captured_at_local": "2026-07-24T08:00:00-04:00",
                "event_slug": SLUG,
                "replay_input_status": "captured",
                "replay_input_source": "replay_inputs.jsonl",
                "reason": "full replay input captured",
            }
        )
    record = {
        "schema_version": "toronto_replay_inputs_v0.2",
        "snapshot_id": "s1",
        "event_slug": SLUG,
        "target_date": TARGET.isoformat(),
        "recorded_distribution": {25: 1.0},
    }
    record["captured_input_hash"] = captured_input_payload_sha256(
        record,
        persisted=False,
    )
    (folder / "replay_inputs.jsonl").write_text(
        json.dumps(record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshots_root, ledger_root, folder


def test_complete_day_emits_self_hashed_pass_receipt(tmp_path):
    snapshots_root, ledger_root, _folder = _write_pass_fixture(tmp_path)
    receipt_path = tmp_path / "receipts" / f"{TARGET.isoformat()}.json"

    receipt = grade_market_day(
        target_date=TARGET,
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        receipt_path=receipt_path,
    )

    assert receipt["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert receipt["status"] == "PASS"
    assert receipt["inventory"]["release_admissible_snapshot_count"] == 1
    assert receipt["receipt_sha256"] == canonical_payload_sha256(
        receipt,
        omit=("receipt_sha256",),
    )
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt


def test_malformed_replay_blocks_and_persists_reason(tmp_path):
    snapshots_root, ledger_root, folder = _write_pass_fixture(tmp_path)
    (folder / "replay_inputs.jsonl").write_text('{"snapshot_id":"s1"\n', encoding="utf-8")
    receipt_path = tmp_path / "receipts" / f"{TARGET.isoformat()}.json"

    receipt = grade_market_day(
        target_date=TARGET,
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        receipt_path=receipt_path,
    )

    assert receipt["status"] == "BLOCK"
    assert receipt["reason"]["code"] == "replay_invalid_jsonl"
    assert {
        row["role"] for row in receipt["inputs"]
    } >= {"settlement_ledger", "snapshot_tape", "captured_input_tape"}
    assert receipt_path.exists()


def test_collapse_reads_receipts_and_ignores_unsettled_tail(tmp_path):
    snapshots_root, ledger_root, _folder = _write_pass_fixture(tmp_path)
    receipt_root = tmp_path / "receipts"
    grade_market_day(
        target_date=TARGET,
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        receipt_path=receipt_root / f"{TARGET.isoformat()}.json",
    )
    grade_market_day(
        target_date=date(2026, 7, 25),
        snapshots_root=snapshots_root,
        ledger_root=ledger_root,
        receipt_path=receipt_root / "2026-07-25.json",
    )

    clock = collapse_receipts(
        receipt_root=receipt_root,
        clock_path=tmp_path / "clock.json",
        as_of=date(2026, 7, 25),
    )

    assert clock["schema_version"] == CLOCK_SCHEMA_VERSION
    assert clock["evaluation_end_date"] == TARGET.isoformat()
    assert clock["contiguous_pass_days"] == 1
    assert clock["latest_status"] == "PASS"
    assert clock["clock_sha256"] == canonical_payload_sha256(
        clock,
        omit=("clock_sha256",),
    )
