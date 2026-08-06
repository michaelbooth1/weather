from __future__ import annotations

import copy
import csv
import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.io import normalize_csv_row, sha256_file
from weather.market.market_config import date_from_event_slug
from weather.market.market_microstructure_capture import order_book_level_rows
from weather.market.market_microstructure_constants import BOOK_LEVEL_COLUMNS
from weather.market.mm_paper_constants import (
    EXECUTION_CANONICAL_TAPE_FILENAME,
    EXECUTION_RAW_TAPE_FILENAME,
    EXECUTION_SESSION_FILENAME,
)
from weather.operations import closed_day_projection_tiering as tiering
from weather.operations.closed_market_day_archive import ARTIFACT_FAMILY_NAMES
from weather.operations.event_day_manifest import manifest_content_hash
from weather.operations.storage_classes import classification_payload


SLUG = "highest-temperature-in-austin-on-june-22-2026"
AS_OF = "2026-06-23"


def _pass_manifest_validator(*_args, **_kwargs):
    return {"status": "PASS", "checks": []}


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=BOOK_LEVEL_COLUMNS,
            extrasaction="ignore",
            restval="",
        )
        writer.writeheader()
        writer.writerows(normalize_csv_row(row) for row in rows)


def _manifest_record(path: Path, snapshots_root: Path, *, rebuild_source: str) -> dict:
    relative = path.relative_to(snapshots_root).as_posix()
    classification = classification_payload(f"snapshots/{relative}")
    return {
        "path": path.name,
        "data_path": f"snapshots/{relative}",
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "row_count": 1,
        "storage_class": classification["storage_class"],
        "retention_class": classification["retention_class"],
        "artifact_family": classification["artifact_family"],
        "rebuild_source": rebuild_source,
        "validation_status": "PASS",
    }


def _write_manifest(folder: Path, snapshots_root: Path, *, status: str = "PASS") -> Path:
    source = folder / tiering.ORDER_BOOK_LONG
    raw = folder / tiering.ORDER_BOOK_RAW
    target_date = date_from_event_slug(folder.name)
    assert target_date is not None
    manifest = {
        "schema_version": "synthetic_event_day_manifest_v0.1",
        "generated_at_utc": "2026-06-23T00:00:00+00:00",
        "identity": {
            "event_slug": folder.name,
            "target_date": target_date.isoformat(),
            "local_date": target_date.isoformat(),
        },
        "validation": {"status": status, "checks": []},
        "artifact_families": [
            {
                "artifact_family": "order_books",
                "files": [
                    _manifest_record(
                        source,
                        snapshots_root,
                        rebuild_source="order_books.jsonl",
                    ),
                    _manifest_record(
                        raw,
                        snapshots_root,
                        rebuild_source="canonical raw evidence",
                    ),
                ],
            }
        ],
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    path = folder / "event_day_manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _make_fixture(
    tmp_path: Path,
    *,
    slug: str = SLUG,
) -> tuple[Path, Path, dict]:
    snapshots_root = tmp_path / "data" / "snapshots"
    folder = snapshots_root / slug
    folder.mkdir(parents=True)
    captured_at = datetime(2026, 6, 22, 17, 0, tzinfo=timezone.utc)
    token = {
        "captured_at_local": "2026-06-22T12:00:00-05:00",
        "event_slug": slug,
        "market_id": "austin",
        "polymarket_market_id": "pm-1",
        "condition_id": "condition-1",
        "range_label": "95-96",
        "outcome": "Yes",
        "clob_token_id": "token-1",
    }
    book = {
        "asset_id": "token-1",
        "market": "condition-1",
        "hash": "book-hash-1",
        "bids": [
            {"price": "0.41", "size": "5"},
            {"price": "0.40", "size": "3"},
        ],
        "asks": [
            {"price": "0.44", "size": "2"},
            {"price": "0.45", "size": "7"},
        ],
    }
    raw_record = {
        "capture_id": "capture-1",
        "captured_at_utc": captured_at.isoformat(),
        "event_slug": slug,
        "market_id": "austin",
        "clob_token_id": "token-1",
        "token": token,
        "book": book,
    }
    (folder / tiering.ORDER_BOOK_RAW).write_text(
        json.dumps(raw_record, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    expected_rows = order_book_level_rows(
        book,
        token,
        captured_at,
        raw_record["capture_id"],
    )
    source = folder / tiering.ORDER_BOOK_LONG
    _write_csv(source, expected_rows)
    _write_manifest(folder, snapshots_root)
    quiet_timestamp = time.time() - tiering.MIN_QUIET_SECONDS - 60.0
    os.utime(source, (quiet_timestamp, quiet_timestamp))
    return snapshots_root, folder, raw_record


def _build_plan(snapshots_root: Path, *slugs: str) -> dict:
    return tiering.build_plan(
        snapshots_root,
        as_of_date=AS_OF,
        event_slugs=slugs or None,
        generated_at_utc="2026-06-23T01:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
    )


def _approve(plan: dict) -> dict:
    approved = copy.deepcopy(plan)
    approved["operator_review"] = {
        "approved": True,
        "approved_by": "fixture-operator",
        "approved_at_utc": "2026-06-23T02:00:00+00:00",
        "approved_plan_hash": approved["plan_hash"],
        "note": "Reviewed exact synthetic-fixture selection.",
    }
    assert tiering.plan_hash_valid(approved)
    return approved


def _approved_identity(tmp_path: Path, plan: dict) -> dict:
    path = tmp_path / "approved-plan-for-apply.json"
    path.write_text(
        json.dumps(plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    loaded, identity = tiering._read_json_with_identity(path)
    assert loaded == plan
    return identity


def _persist_in_memory(payload: dict) -> None:
    # The mutation API requires a durable writer. Individual durability tests
    # below use the real atomic JSON+Markdown persister.
    _ = copy.deepcopy(payload)


def _refresh_fixture_manifest(
    folder: Path,
    *,
    snapshots_root: Path,
    manifest_validator,
) -> dict:
    path = folder / "event_day_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = manifest["artifact_families"][0]["files"]
    records[:] = [
        row for row in records if row.get("path") != tiering.ORDER_BOOK_LONG
    ]
    records.append(
        _manifest_record(
            folder / tiering.ORDER_BOOK_LONG_GZIP,
            snapshots_root,
            rebuild_source=tiering.ORDER_BOOK_RAW,
        )
    )
    manifest["manifest_hash"] = ""
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    validation = manifest_validator(
        manifest,
        folder,
        snapshots_root=snapshots_root,
        check_hashes=True,
        check_row_counts=True,
        fail_on_extra=True,
    )
    return {
        "status": validation["status"],
        "manifest_hash": manifest["manifest_hash"],
        "manifest": {"path": path.relative_to(snapshots_root).as_posix()},
        "validation": validation,
        "source_csv_absent": True,
        "gzip_present": True,
        "canonical_raw_present": True,
    }


def test_registry_covers_every_archive_family_and_only_long_is_eligible():
    rows = tiering.projection_family_registry()

    assert tiering.validate_projection_family_registry() == []
    assert {row["family"] for row in rows} == set(ARTIFACT_FAMILY_NAMES)
    assert [row["family"] for row in rows if row["eligible"]] == [
        "order_books_long"
    ]
    assert all(row["canonical_rebuild_sources"] for row in rows)
    assert all(row["accepted_read_representations"] for row in rows)
    assert all(row["blocker"] for row in rows if not row["eligible"])

    long_family = tiering.PROJECTION_FAMILIES_BY_NAME["order_books_long"]
    assert long_family.canonical_rebuild_sources == ("order_books.jsonl",)
    assert (
        "canonical_jsonl:order_books.jsonl"
        in long_family.accepted_read_representations
    )
    assert (
        "gzip_tiered_text:order_books_long.csv.gz"
        in long_family.accepted_read_representations
    )
    assert (
        tiering.PROJECTION_FAMILIES_BY_NAME["order_books_summary"].eligible
        is False
    )
    assert tiering.PROJECTION_FAMILIES_BY_NAME[
        "variant_predictions_long"
    ].canonical_rebuild_sources == (
        "variant_predictions.jsonl",
        "live_variant_predictions.jsonl",
    )
    maker = tiering.PROJECTION_FAMILIES_BY_NAME["maker_execution_tape"]
    dedicated_files = (
        EXECUTION_RAW_TAPE_FILENAME,
        EXECUTION_CANONICAL_TAPE_FILENAME,
        EXECUTION_SESSION_FILENAME,
    )
    assert maker.projection_files == dedicated_files
    assert maker.canonical_rebuild_sources == dedicated_files
    assert maker.eligible is False
    assert maker.blocker == (
        "canonical_evidence_is_not_a_projection_cleanup_candidate"
    )
    assert maker.accepted_read_representations == (
        f"canonical_jsonl:{EXECUTION_RAW_TAPE_FILENAME}",
        f"canonical_csv:{EXECUTION_CANONICAL_TAPE_FILENAME}",
        f"canonical_jsonl:{EXECUTION_SESSION_FILENAME}",
    )


def test_plan_is_read_only_and_requires_closed_finalized_raw_proof(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    before = {
        path.relative_to(snapshots_root).as_posix(): (
            path.stat().st_size,
            sha256_file(path),
        )
        for path in snapshots_root.rglob("*")
        if path.is_file()
    }

    plan = _build_plan(snapshots_root, folder.name)

    after = {
        path.relative_to(snapshots_root).as_posix(): (
            path.stat().st_size,
            sha256_file(path),
        )
        for path in snapshots_root.rglob("*")
        if path.is_file()
    }
    assert plan["status"] == "PASS"
    assert plan["mode"] == "dry_run"
    assert plan["summary"]["eligible_action_count"] == 1
    assert plan["actions"][0]["canonical_rebuild_source"]["path"].endswith(
        "order_books.jsonl"
    )
    closed_proof = plan["actions"][0]["closed_finalized_proof"]
    assert closed_proof["target_date"] == "2026-06-22"
    assert closed_proof["as_of_date"] == AS_OF
    assert closed_proof["closed_before_as_of"] is True
    assert closed_proof["event_manifest_current_validation"] == "PASS"
    assert closed_proof["writer_locks_absent"] is True
    assert closed_proof["source_quiescence"] == {
        "status": "PASS",
        "minimum_quiet_seconds": tiering.MIN_QUIET_SECONDS,
    }
    assert closed_proof["finalization"]["state"] == "closed_unlabeled"
    assert (
        closed_proof["finalization"]["closed_unlabeled_contract"]["status"]
        == "PASS"
    )
    assert closed_proof["finalization"]["proof_hash"]
    assert plan["operator_review"]["approved"] is False
    assert tiering.plan_hash_valid(plan)
    assert before == after
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        ("same_day", "event_day_is_not_closed_before_as_of_date"),
        ("missing_raw", "canonical_order_books_jsonl_missing"),
        ("manifest_not_pass", "event_day_manifest_not_finalized_pass"),
        ("writer_lock", "event_folder_writer_lock_present"),
        ("recently_written", "order_books_long_recently_written"),
    ],
)
def test_plan_fails_closed_without_each_required_proof(
    tmp_path,
    mutation,
    expected_blocker,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    as_of = AS_OF
    if mutation == "same_day":
        as_of = "2026-06-22"
    elif mutation == "missing_raw":
        (folder / tiering.ORDER_BOOK_RAW).unlink()
    elif mutation == "manifest_not_pass":
        _write_manifest(folder, snapshots_root, status="WARN")
    elif mutation == "writer_lock":
        (folder / tiering.RAW_TAPE_WRITER_LOCK).write_text(
            "synthetic lock\n",
            encoding="utf-8",
        )
    elif mutation == "recently_written":
        os.utime(folder / tiering.ORDER_BOOK_LONG, None)

    plan = tiering.build_plan(
        snapshots_root,
        as_of_date=as_of,
        event_slugs=[folder.name],
        manifest_validator=_pass_manifest_validator,
    )

    assert plan["status"] == "NOT_DONE"
    assert plan["actions"] == []
    assert expected_blocker in plan["folders"][0]["blockers"]
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_apply_requires_external_operator_approval(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    plan = _build_plan(snapshots_root, folder.name)

    receipt = tiering.apply_approved_plan(
        plan,
        manifest_validator=_pass_manifest_validator,
    )

    assert receipt["status"] == "BLOCK"
    assert "operator_review.approved must be true" in receipt["approval_errors"]
    assert receipt["actions"] == []
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_approved_apply_still_requires_durable_receipt_persistence(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert any(
        "durable JSON+Markdown receipt persistence" in error
        for error in receipt["approval_errors"]
    )
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_approved_apply_requires_exact_manifest_file_identity(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
    )

    assert receipt["status"] == "BLOCK"
    assert "exact approved manifest file identity is required" in (
        receipt["approval_errors"]
    )
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_apply_retains_deterministic_gzip_and_raw_then_unlinks_exact_csv(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_LONG
    source_bytes = source.read_bytes()
    plan = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, plan)
    checkpoints = []

    receipt = tiering.apply_approved_plan(
        plan,
        generated_at_utc="2026-06-23T03:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=lambda payload: checkpoints.append(copy.deepcopy(payload)),
        approved_manifest_identity=approved_identity,
    )

    gzip_path = folder / tiering.ORDER_BOOK_LONG_GZIP
    assert receipt["status"] == "PASS"
    assert receipt["summary"]["applied"] == 1
    assert not source.exists()
    assert gzip_path.exists()
    assert (folder / tiering.ORDER_BOOK_RAW).exists()
    assert gzip.decompress(gzip_path.read_bytes()) == source_bytes
    assert gzip_path.read_bytes()[4:8] == b"\x00\x00\x00\x00"
    action = receipt["actions"][0]
    assert action["cleanup_preflight"]["status"] == "PASS"
    assert action["source_quiescence"] == {
        "status": "PASS",
        "minimum_quiet_seconds": tiering.MIN_QUIET_SECONDS,
        "checked_under_raw_tape_writer_lock": True,
    }
    assert action["final_reverification"]["status"] == "PASS"
    assert action["deletion"] == {
        "status": "PASS",
        "path": f"{folder.name}/order_books_long.csv",
        "exact_file_only": True,
        "source_absent": True,
        "gzip_retained": True,
        "canonical_raw_retained": True,
    }
    assert action["event_day_manifest_refresh_required"] is False
    assert action["event_day_manifest_refresh"]["status"] == "PASS"
    assert action["raw_tape_writer_lock"]["status"] == "RELEASED"
    refreshed_manifest = json.loads(
        (folder / "event_day_manifest.json").read_text(encoding="utf-8")
    )
    refreshed_paths = {
        row["path"]
        for family in refreshed_manifest["artifact_families"]
        for row in family["files"]
    }
    assert tiering.ORDER_BOOK_LONG not in refreshed_paths
    assert tiering.ORDER_BOOK_LONG_GZIP in refreshed_paths
    checkpoint_statuses = [
        row["actions"][0]["status"]
        for row in checkpoints
        if row.get("actions")
    ]
    assert "UNLINK_PENDING" in checkpoint_statuses
    assert "APPLIED" in checkpoint_statuses
    pending_checkpoint = next(
        row
        for row in checkpoints
        if row.get("actions")
        and row["actions"][0]["status"] == "UNLINK_PENDING"
    )
    assert (
        pending_checkpoint["actions"][0]["raw_tape_writer_lock"]["status"]
        == "HELD"
    )
    assert checkpoints[-1]["status"] == "PASS"


def test_apply_reverifies_after_write_ahead_receipt_before_unlink(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_LONG
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    tampered = False

    def persist_and_tamper(payload):
        nonlocal tampered
        actions = payload.get("actions") or []
        if (
            actions
            and actions[0].get("status") == "UNLINK_PENDING"
            and not tampered
        ):
            with source.open("ab") as handle:
                handle.write(b"write-ahead-race\n")
            tampered = True

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=persist_and_tamper,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert tampered is True
    assert source.exists()
    assert "source final reverify identity changed" in (
        receipt["actions"][0]["failure"]["detail"]
    )


def test_apply_cannot_mutate_without_acquiring_shared_raw_tape_lock(
    tmp_path,
    monkeypatch,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    monkeypatch.setattr(tiering, "acquire_writer_lock", lambda *_a, **_k: None)

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert "could not acquire the shared raw-tape writer lock" in (
        receipt["actions"][0]["failure"]["detail"]
    )
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()
    assert (folder / tiering.ORDER_BOOK_RAW).exists()


def test_apply_rechecks_quiescence_under_shared_writer_lock(
    tmp_path,
    monkeypatch,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    source = folder / tiering.ORDER_BOOK_LONG
    raw = folder / tiering.ORDER_BOOK_RAW
    observed_under_lock = False

    def no_longer_quiet(path):
        nonlocal observed_under_lock
        assert Path(path) == source
        observed_under_lock = (
            folder / tiering.RAW_TAPE_WRITER_LOCK
        ).is_file()
        return False

    monkeypatch.setattr(tiering, "source_is_quiet", no_longer_quiet)

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert observed_under_lock is True
    assert source.is_file()
    assert raw.is_file()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()
    assert "no longer writer-quiescent" in (
        receipt["actions"][0]["failure"]["detail"]
    )


def test_settlement_evidence_hash_is_reverified_before_mutation(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    settlement_path = folder / "settlement.json"
    settlement_path.write_text(
        json.dumps(
            {
                "quality_grade": "complete",
                "settlement_bucket": 95,
                "settlement_source": "fixture",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    proof = approved["actions"][0]["closed_finalized_proof"]["finalization"]
    assert proof["state"] == "settled_countable"
    assert proof["evidence"][0]["sha256"] == sha256_file(settlement_path)

    settlement_path.write_text(
        json.dumps(
            {
                "quality_grade": "complete",
                "settlement_bucket": 96,
                "settlement_source": "fixture-corrected",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert "finalization evidence changed" in (
        receipt["actions"][0]["failure"]["detail"]
    )
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_immediate_reverify_blocks_unlink_if_source_changes_after_preflight(
    tmp_path,
    monkeypatch,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_LONG
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    real_prepare = tiering._prepare_gzip

    def _tamper_after_gzip(*args, **kwargs):
        result = real_prepare(*args, **kwargs)
        with source.open("ab") as handle:
            handle.write(b"post-gzip-tamper\n")
        return result

    monkeypatch.setattr(
        tiering,
        "_prepare_gzip",
        _tamper_after_gzip,
    )

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert receipt["summary"]["applied"] == 0
    assert receipt["summary"]["failed"] == 1
    assert source.exists()
    assert (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()
    assert (folder / tiering.ORDER_BOOK_RAW).exists()
    assert "source final reverify identity changed" in (
        receipt["actions"][0]["failure"]["detail"]
    )


def test_cleanup_preflight_block_causes_no_compression_mutation(
    tmp_path,
    monkeypatch,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)

    monkeypatch.setattr(
        tiering,
        "build_cleanup_preflight",
        lambda *_args, **_kwargs: {
            "status": "BLOCK",
            "delete_permission": False,
            "checks": [{"check": "fixture", "status": "BLOCK"}],
            "candidates": [],
        },
    )

    receipt = tiering.apply_approved_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()
    assert (folder / tiering.ORDER_BOOK_RAW).exists()


def test_apply_stops_on_first_failure_and_does_not_touch_later_action(tmp_path):
    snapshots_root, first, _ = _make_fixture(
        tmp_path,
        slug="highest-temperature-in-austin-on-june-21-2026",
    )
    second_root = tmp_path / "second-fixture"
    second_snapshots, second_fixture, _ = _make_fixture(
        second_root,
        slug=SLUG,
    )
    # Move the second synthetic event under the same snapshots root.
    second = snapshots_root / second_fixture.name
    second_fixture.rename(second)
    second_snapshots.rmdir()
    second_snapshots.parent.rmdir()
    second_root.rmdir()

    plan = _approve(_build_plan(snapshots_root, first.name, second.name))
    approved_identity = _approved_identity(tmp_path, plan)
    with (first / tiering.ORDER_BOOK_LONG).open("ab") as handle:
        handle.write(b"changed-after-plan\n")

    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "durable-receipts",
        stem="apply",
        protected_root=snapshots_root.parent,
    )
    receipt = tiering.apply_approved_plan(
        plan,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=persist,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert receipt["summary"]["attempted"] == 1
    assert receipt["summary"]["not_attempted"] == 1
    assert (second / tiering.ORDER_BOOK_LONG).exists()
    assert not (second / tiering.ORDER_BOOK_LONG_GZIP).exists()
    assert json_path.exists()
    assert report_path.exists()
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "BLOCK"
    assert persisted["summary"]["attempted"] == 1
    assert persisted["summary"]["not_attempted"] == 1
    assert persisted["actions"][0]["status"] == "BLOCK"


def test_signed_path_escape_is_still_rejected_before_any_mutation(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    malicious = _build_plan(snapshots_root, folder.name)
    malicious["actions"][0]["source"]["path"] = "../order_books_long.csv"
    malicious["plan_hash"] = tiering.plan_content_hash(malicious)
    malicious = _approve(malicious)
    approved_identity = _approved_identity(tmp_path, malicious)

    receipt = tiering.apply_approved_plan(
        malicious,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_manifest,
        persist_receipt=_persist_in_memory,
        approved_manifest_identity=approved_identity,
    )

    assert receipt["status"] == "BLOCK"
    assert "normalized relative path" in receipt["actions"][0]["failure"]["detail"]
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert not (folder / tiering.ORDER_BOOK_LONG_GZIP).exists()


def test_rebuild_one_proves_ordered_byte_parity_from_raw_jsonl(tmp_path):
    _, folder, _ = _make_fixture(tmp_path)
    output_root = tmp_path / "proof-output"

    receipt = tiering.rebuild_one_order_books_long(
        folder,
        output_root=output_root,
        generated_at_utc="2026-06-23T04:00:00+00:00",
    )

    rebuilt_path = Path(receipt["rebuilt"]["path"])
    assert receipt["status"] == "PASS"
    assert receipt["parity"]["status"] == "PASS"
    assert receipt["parity"]["bytes_equal"] is True
    assert receipt["parity"]["sha256_equal"] is True
    assert receipt["parity"]["ordered_columns"] == list(BOOK_LEVEL_COLUMNS)
    assert receipt["raw_record_count"] == 1
    assert receipt["rebuilt_row_count"] == 4
    assert rebuilt_path.exists()
    assert rebuilt_path.parent.is_relative_to(output_root)


def test_rebuild_one_reports_block_when_projection_does_not_match_raw(tmp_path):
    _, folder, _ = _make_fixture(tmp_path)
    with (folder / tiering.ORDER_BOOK_LONG).open("ab") as handle:
        handle.write(b"different-projection\n")

    receipt = tiering.rebuild_one_order_books_long(
        folder,
        output_root=tmp_path / "proof-output",
    )

    assert receipt["status"] == "BLOCK"
    assert receipt["parity"]["sha256_equal"] is False
    assert (folder / tiering.ORDER_BOOK_LONG).exists()
    assert (folder / tiering.ORDER_BOOK_RAW).exists()


def test_receipt_output_root_must_not_overlap_snapshot_tree(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    plan = _build_plan(snapshots_root, folder.name)

    with pytest.raises(tiering.ProjectionTieringError, match="must not overlap"):
        tiering.write_outputs(
            plan,
            output_root=snapshots_root.parent / "backtest",
            stem="fixture",
            protected_root=snapshots_root.parent,
        )


def test_receipt_output_root_must_not_overlap_any_explicit_mirror(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    plan = _build_plan(snapshots_root, folder.name)
    mirror_root = tmp_path / "weather-mirror"
    mirror_root.mkdir()

    with pytest.raises(tiering.ProjectionTieringError, match="data/mirror"):
        tiering.write_outputs(
            plan,
            output_root=mirror_root / "receipts",
            stem="fixture",
            protected_root=[snapshots_root.parent, mirror_root],
        )


def test_cli_binds_receipt_to_approved_manifest_file_identity(
    tmp_path,
    monkeypatch,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved_path = tmp_path / "approved-plan.json"
    approved_path.write_text(
        json.dumps(approved, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    captured = {}

    def _fake_apply(plan, **kwargs):
        captured["plan"] = plan
        captured["identity"] = kwargs["approved_manifest_identity"]
        payload = {
            "schema_version": tiering.RECEIPT_SCHEMA_VERSION,
            "generated_at_utc": "2026-06-23T05:00:00+00:00",
            "writer": tiering.WRITER,
            "mode": "apply",
            "status": "PASS",
            "summary": {
                "planned": 0,
                "attempted": 0,
                "applied": 0,
                "failed": 0,
                "not_attempted": 0,
            },
            "actions": [],
        }
        kwargs["persist_receipt"](payload)
        return payload

    monkeypatch.setattr(tiering, "apply_approved_plan", _fake_apply)
    output_root = tmp_path / "cli-receipts"

    result = tiering.main(
        [
            "apply",
            "--approved-manifest",
            str(approved_path),
            "--output-root",
            str(output_root),
            "--protected-root",
            str(snapshots_root.parent),
        ]
    )

    assert result == 0
    assert captured["identity"]["path"] == str(approved_path.resolve())
    assert captured["identity"]["bytes"] == approved_path.stat().st_size
    assert captured["identity"]["sha256"] == sha256_file(approved_path)
    assert (
        output_root / "closed_day_projection_tiering_apply_receipt.json"
    ).exists()
    assert (
        output_root / "closed_day_projection_tiering_apply_receipt.md"
    ).exists()


def test_cli_never_trusts_claimed_data_root_for_receipt_boundary(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_plan(snapshots_root, folder.name))
    approved["data_root"] = str(tmp_path / "fake-data-root")
    approved_path = tmp_path / "malformed-approved-plan.json"
    approved_path.write_text(
        json.dumps(approved, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(tiering.ProjectionTieringError, match="must not overlap"):
        tiering.main(
            [
                "apply",
                "--approved-manifest",
                str(approved_path),
                "--output-root",
                str(snapshots_root.parent / "backtest"),
                "--protected-root",
                str(snapshots_root.parent),
            ]
        )

    assert not (snapshots_root.parent / "backtest").exists()


def test_reparse_point_candidate_is_blocked(tmp_path, monkeypatch):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_LONG
    real_is_reparse = tiering._is_reparse_point

    monkeypatch.setattr(
        tiering,
        "_is_reparse_point",
        lambda path: Path(path) == source or real_is_reparse(Path(path)),
    )

    plan = _build_plan(snapshots_root, folder.name)

    assert plan["status"] == "NOT_DONE"
    assert plan["actions"] == []
    assert any(
        "not_regular_file" in blocker
        for blocker in plan["folders"][0]["blockers"]
    )
