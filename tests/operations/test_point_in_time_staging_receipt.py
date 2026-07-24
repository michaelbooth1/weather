import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from weather.backtesting.settlement_ledger import upsert_ledger_record
from weather.operations.point_in_time_staging_receipt import (
    SOURCE_MANIFEST_ARTIFACT_TYPE,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    StagingReceiptError,
    _canonical_json,
    _self_hash,
    verify_staging_receipt,
    write_staging_receipt,
)
from weather.reporting.promotion.promotion_corpus import (
    PROMOTION_CORPUS_SCHEMA_VERSION,
    corpus_hash,
)


def _write_complete_toronto_day(ledger_root: Path, target_date: str, bucket: int) -> dict:
    label = {
        "schema_version": "settlement_ledger_v2",
        "event_slug": f"toronto-lock-{target_date}",
        "market_id": "toronto",
        "target_date": target_date,
        "settlement_bucket": bucket,
        "settlement_source": "wu_history",
        "quality_grade": "complete",
        "finalized_at_utc": f"{target_date}T23:59:00+00:00",
        "evidence": {
            "five_time_provenance": {},
            "raw_resolution_hashes": {"wu": target_date},
            "override_provenance": {},
        },
    }
    upsert_ledger_record(label, ledger_root)
    return label


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label_hash(target_date: str) -> str:
    return hashlib.sha256(f"F-label:{target_date}".encode("utf-8")).hexdigest()


def _write_staged_manifests(
    *,
    corpus: Path,
    manifest: Path,
    replay: Path,
    target_dates: list[str],
) -> None:
    entries = []
    for target_date in target_dates:
        event_slug = f"nyc-high-{target_date}"
        snapshot_id = "08:00"
        entries.append(
            {
                "event_slug": event_slug,
                "market_id": "nyc",
                "target_date": target_date,
                "folder": str(manifest.parent / "snapshots" / event_slug),
                "folder_name": event_slug,
                "folder_relative_to_snapshots_root": event_slug,
                "settlement_bucket": 80,
                "settlement_unit": "F",
                "settlement_source": "wu_history",
                "winning_band": "low",
                "quality_grade": "complete",
                "admitted_by": "quality_grade",
                "snapshot_ids": [snapshot_id],
                "snapshot_count": 1,
                "row_count": 2,
                "replay_record_hashes": {
                    snapshot_id: hashlib.sha256(
                        f"replay:{target_date}".encode("utf-8")
                    ).hexdigest()
                },
                "tape_row_hashes": {
                    snapshot_id: hashlib.sha256(
                        f"tape:{target_date}".encode("utf-8")
                    ).hexdigest()
                },
                "label_hash": _label_hash(target_date),
            }
        )
    replay_payload = {
        "schema_version": PROMOTION_CORPUS_SCHEMA_VERSION,
        "generated_at_utc": "2026-07-15T10:00:00+00:00",
        "as_of": "2026-07-15",
        "snapshots_root": str(manifest.parent / "snapshots"),
        "quality_grades": ["complete", "manual_override"],
        "include_reconstructed": False,
        "allow_unsettled": False,
        "admit_promotion_countable": False,
        "entries": entries,
        "summary": {"market_day_count": len(entries)},
    }
    replay_payload["corpus_hash"] = corpus_hash(entries)
    replay.write_text(
        json.dumps(replay_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    source_payload = {
        "schema_version": SOURCE_MANIFEST_SCHEMA_VERSION,
        "artifact_type": SOURCE_MANIFEST_ARTIFACT_TYPE,
        "generated_at_utc": "2026-07-15T10:00:00+00:00",
        "status": "PASS",
        "candidate_dependent_fields_included": [],
        "derived_artifact": {
            "path": str(corpus),
            "sha256": _sha256_file(corpus),
            "row_count": len(entries) * 2,
            "bytes": corpus.stat().st_size,
        },
        "source_replay_manifest": {
            "path": str(replay),
            "sha256": _sha256_file(replay),
            "corpus_hash": replay_payload["corpus_hash"],
        },
        "counts": {
            "market_days_read": len(entries),
            "accepted_rows": len(entries) * 2,
        },
        "inputs": [
            {
                "event_slug": entry["event_slug"],
                "target_date": entry["target_date"],
                "market_id": entry["market_id"],
                "row_count": entry["row_count"],
                "snapshot_count": entry["snapshot_count"],
                "label_hash": entry["label_hash"],
            }
            for entry in entries
        ],
    }
    source_payload["manifest_hash"] = hashlib.sha256(
        _canonical_json(source_payload).encode("utf-8")
    ).hexdigest()
    manifest.write_text(
        json.dumps(source_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _staged_source(
    tmp_path: Path,
    *,
    write_receipt: bool = True,
) -> tuple[Path, Path, Path, Path, Path]:
    source = tmp_path / "staged"
    source.mkdir()
    corpus = source / "preselection-source.parquet"
    manifest = source / "preselection-source-manifest.json"
    replay = source / "replay_manifest.json"
    receipt = source / "staging-receipt.json"
    corpus.write_bytes(b"parquet-fixture")
    ledger_root = tmp_path / "settlements"
    start = date(2026, 7, 1)
    for offset in range(14):
        target = (start + timedelta(days=offset)).isoformat()
        _write_complete_toronto_day(ledger_root, target, 20 + offset)
    source_start = start - timedelta(days=4)
    _write_staged_manifests(
        corpus=corpus,
        manifest=manifest,
        replay=replay,
        target_dates=[
            (source_start + timedelta(days=offset)).isoformat()
            for offset in range(18)
        ],
    )
    if write_receipt:
        write_staging_receipt(
            receipt_path=receipt,
            corpus_path=corpus,
            manifest_path=manifest,
            replay_manifest_path=replay,
            ledger_root=ledger_root,
            generated_at_utc="2026-07-15T12:00:00+00:00",
        )
    return receipt, corpus, manifest, replay, ledger_root


def _rewrite_staged_dates(
    paths: tuple[Path, Path, Path, Path, Path],
    *,
    day_shift: int,
) -> None:
    _, corpus, manifest, replay, _ = paths
    replay_payload = json.loads(replay.read_text(encoding="utf-8"))
    shifted_dates = [
        (
            date.fromisoformat(entry["target_date"]) + timedelta(days=day_shift)
        ).isoformat()
        for entry in replay_payload["entries"]
    ]
    _write_staged_manifests(
        corpus=corpus,
        manifest=manifest,
        replay=replay,
        target_dates=shifted_dates,
    )


def _rebind_receipt_trio(
    paths: tuple[Path, Path, Path, Path, Path],
) -> None:
    receipt, corpus, manifest, replay, _ = paths
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    by_role = {
        "preselection_source_corpus": corpus,
        "preselection_source_manifest": manifest,
        "source_replay_manifest": replay,
    }
    for row in payload["staged_source_trio"]:
        path = by_role[row["role"]]
        row["sha256"] = _sha256_file(path)
        row["bytes"] = path.stat().st_size
    payload["receipt_sha256"] = _self_hash(payload)
    receipt.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_source_payload(path: Path, payload: dict) -> None:
    payload.pop("manifest_hash", None)
    payload["manifest_hash"] = hashlib.sha256(
        _canonical_json(payload).encode("utf-8")
    ).hexdigest()
    path.write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _reseal_manifest_pair(
    paths: tuple[Path, Path, Path, Path, Path],
    replay_payload: dict,
    *,
    sync_inventory: bool = False,
) -> None:
    _, _, manifest, replay, _ = paths
    replay_payload["corpus_hash"] = corpus_hash(replay_payload["entries"])
    replay.write_text(
        json.dumps(replay_payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_payload = json.loads(manifest.read_text(encoding="utf-8"))
    if sync_inventory:
        source_payload["inputs"] = [
            {
                "event_slug": entry["event_slug"],
                "target_date": entry["target_date"],
                "market_id": entry["market_id"],
                "row_count": entry["row_count"],
                "snapshot_count": entry["snapshot_count"],
                "label_hash": entry["label_hash"],
            }
            for entry in replay_payload["entries"]
        ]
    source_payload["source_replay_manifest"]["sha256"] = _sha256_file(replay)
    source_payload["source_replay_manifest"]["corpus_hash"] = replay_payload[
        "corpus_hash"
    ]
    _write_source_payload(manifest, source_payload)


def _verify(paths: tuple[Path, Path, Path, Path, Path]) -> dict:
    receipt, corpus, manifest, replay, ledger_root = paths
    return verify_staging_receipt(
        receipt_path=receipt,
        corpus_path=corpus,
        manifest_path=manifest,
        replay_manifest_path=replay,
        ledger_root=ledger_root,
    )


def test_staging_receipt_binds_portable_trio_and_exact_latest_revisions(tmp_path):
    paths = _staged_source(tmp_path)

    verified = _verify(paths)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))

    assert verified["status"] == "PASS"
    assert verified["target_dates"] == [
        (date(2026, 7, 1) + timedelta(days=offset)).isoformat()
        for offset in range(14)
    ]
    assert [row["relative_path"] for row in payload["staged_source_trio"]] == [
        "preselection-source.parquet",
        "preselection-source-manifest.json",
        "replay_manifest.json",
    ]
    assert all(
        not Path(row["relative_path"]).is_absolute()
        for row in payload["staged_source_trio"]
    )
    assert {
        row["target_date"]: (row["revision_id"], row["label_hash"])
        for row in verified["latest_revisions"]
    } == {
        row["target_date"]: (row["revision_id"], row["label_hash"])
        for row in payload["toronto_lock"]["latest_revisions"]
    }


def test_staging_receipt_rejects_latest_ledger_revision_change(tmp_path):
    paths = _staged_source(tmp_path)
    _write_complete_toronto_day(
        paths[4],
        "2026-07-14",
        99,
    )

    with pytest.raises(StagingReceiptError, match="latest Toronto lock revisions"):
        _verify(paths)


def test_staging_receipt_rejects_one_byte_trio_mutation(tmp_path):
    paths = _staged_source(tmp_path)
    paths[3].write_bytes(paths[3].read_bytes()[:-1] + b" ")

    with pytest.raises(StagingReceiptError, match="source identity mismatch"):
        _verify(paths)


def test_staging_receipt_rejects_stale_lock_dates(tmp_path):
    paths = _staged_source(tmp_path)
    _write_complete_toronto_day(paths[4], "2026-07-15", 35)

    with pytest.raises(StagingReceiptError, match="latest Toronto lock revisions"):
        _verify(paths)


def test_staging_receipt_creation_rejects_stale_consistent_f_trio(tmp_path):
    paths = _staged_source(tmp_path, write_receipt=False)
    _rewrite_staged_dates(paths, day_shift=-1)

    with pytest.raises(
        StagingReceiptError,
        match="latest 14 fleet dates do not match",
    ):
        write_staging_receipt(
            receipt_path=paths[0],
            corpus_path=paths[1],
            manifest_path=paths[2],
            replay_manifest_path=paths[3],
            ledger_root=paths[4],
        )

    assert not paths[0].exists()


def test_staging_receipt_verification_rejects_resealed_stale_consistent_f_trio(
    tmp_path,
):
    paths = _staged_source(tmp_path)
    _rewrite_staged_dates(paths, day_shift=-1)
    _rebind_receipt_trio(paths)

    with pytest.raises(
        StagingReceiptError,
        match="latest 14 fleet dates do not match",
    ):
        _verify(paths)


def test_staging_receipt_rejects_source_replay_inventory_disagreement(tmp_path):
    paths = _staged_source(tmp_path, write_receipt=False)
    source_payload = json.loads(paths[2].read_text(encoding="utf-8"))
    source_payload["inputs"][0]["label_hash"] = "f" * 64
    _write_source_payload(paths[2], source_payload)

    with pytest.raises(StagingReceiptError, match="inventories differ"):
        write_staging_receipt(
            receipt_path=paths[0],
            corpus_path=paths[1],
            manifest_path=paths[2],
            replay_manifest_path=paths[3],
            ledger_root=paths[4],
        )


def test_staging_receipt_rejects_resealed_corpus_tamper(tmp_path):
    paths = _staged_source(tmp_path)
    paths[1].write_bytes(paths[1].read_bytes() + b"-tampered")
    _rebind_receipt_trio(paths)

    with pytest.raises(
        StagingReceiptError,
        match="corpus binding or inventory counts",
    ):
        _verify(paths)


@pytest.mark.parametrize(
    ("field_path", "replacement"),
    [
        (("derived_artifact", "row_count"), 37),
        (("counts", "accepted_rows"), 37),
        (("counts", "market_days_read"), 19),
    ],
)
def test_staging_receipt_rejects_resealed_inventory_count_tamper(
    tmp_path,
    field_path,
    replacement,
):
    paths = _staged_source(tmp_path)
    source_payload = json.loads(paths[2].read_text(encoding="utf-8"))
    source_payload[field_path[0]][field_path[1]] = replacement
    _write_source_payload(paths[2], source_payload)
    _rebind_receipt_trio(paths)

    with pytest.raises(
        StagingReceiptError,
        match="corpus binding or inventory counts",
    ):
        _verify(paths)


@pytest.mark.parametrize(
    "flag",
    [
        "admit_promotion_countable",
        "include_reconstructed",
        "allow_unsettled",
    ],
)
def test_staging_receipt_rejects_unsafe_replay_admission_flags(tmp_path, flag):
    paths = _staged_source(tmp_path, write_receipt=False)
    replay_payload = json.loads(paths[3].read_text(encoding="utf-8"))
    replay_payload[flag] = True
    _reseal_manifest_pair(paths, replay_payload)

    with pytest.raises(StagingReceiptError, match="not production-safe"):
        write_staging_receipt(
            receipt_path=paths[0],
            corpus_path=paths[1],
            manifest_path=paths[2],
            replay_manifest_path=paths[3],
            ledger_root=paths[4],
        )


@pytest.mark.parametrize("semantics", ["promotion_admission", "celsius_market"])
def test_staging_receipt_rejects_non_f_family_or_non_grade_inventory(
    tmp_path,
    semantics,
):
    paths = _staged_source(tmp_path, write_receipt=False)
    replay_payload = json.loads(paths[3].read_text(encoding="utf-8"))
    if semantics == "promotion_admission":
        replay_payload["entries"][0]["admitted_by"] = "promotion_countable"
        sync_inventory = False
    else:
        replay_payload["entries"][0]["market_id"] = "toronto"
        replay_payload["entries"][0]["settlement_unit"] = "C"
        sync_inventory = True
    _reseal_manifest_pair(
        paths,
        replay_payload,
        sync_inventory=sync_inventory,
    )

    with pytest.raises(
        StagingReceiptError,
        match="grade-only registered F-family",
    ):
        write_staging_receipt(
            receipt_path=paths[0],
            corpus_path=paths[1],
            manifest_path=paths[2],
            replay_manifest_path=paths[3],
            ledger_root=paths[4],
        )


@pytest.mark.parametrize("mutation", ["reordered", "duplicated"])
def test_staging_receipt_rejects_reordered_or_duplicated_dates(tmp_path, mutation):
    paths = _staged_source(tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    dates = payload["toronto_lock"]["target_dates"]
    if mutation == "reordered":
        dates[0], dates[1] = dates[1], dates[0]
    else:
        dates[-1] = dates[-2]
    payload["receipt_sha256"] = _self_hash(payload)
    paths[0].write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    with pytest.raises(
        StagingReceiptError,
        match="missing, duplicated, or reordered",
    ):
        _verify(paths)
