from __future__ import annotations

import copy
import csv
import gzip
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from weather.io import normalize_csv_row, sha256_file
from weather.market.market_config import date_from_event_slug
from weather.market.market_microstructure_capture import order_book_level_rows
from weather.market.market_microstructure_constants import BOOK_LEVEL_COLUMNS
from weather.operations import closed_day_projection_tiering as tiering
from weather.operations import event_day_manifest as event_manifest_module
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


def _write_required_event_day_evidence(folder: Path) -> None:
    payload = {
        "schema_version": "synthetic_event_evidence_v0.1",
        "release_id": "synthetic-release",
        "runtime_identity": {
            "git_commit": "synthetic-commit",
            "source_fingerprint": "synthetic-source",
        },
    }
    line = json.dumps(payload, sort_keys=True) + "\n"
    for name in (
        "snapshots.jsonl",
        "forecast_payloads.jsonl",
        "observation_payloads.jsonl",
        "source_status.jsonl",
        "replay_inputs.jsonl",
        "clob_capture_status.jsonl",
    ):
        (folder / name).write_text(line, encoding="utf-8")
    observation_root = folder / "observation_payloads"
    observation_root.mkdir()
    (observation_root / "synthetic.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _pass_payload_blob_links(*_args, **_kwargs) -> dict:
    return {
        "status": "PASS",
        "families": [],
        "shared_dependencies": [],
        "summary": {
            "manifest_row_count": 2,
            "blob_count": 0,
            "linked_blob_count": 0,
            "shared_linked_blob_count": 0,
            "shared_dependency_count": 0,
            "issue_count": 0,
        },
    }


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
    if not raw.exists():
        raw = folder / tiering.ORDER_BOOK_RAW_GZIP
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
        "validation": {
            "status": status,
            "checks": [
                {
                    "check": "shared_payload_backup_restore",
                    "status": "PASS",
                },
                {"check": "off_machine_backup", "status": "PASS"},
                {"check": "restore_proof", "status": "PASS"},
            ],
        },
        "protection": {
            "status": "PASS",
            "backup": {
                "status": "PASS",
                "backup_root": "synthetic-off-machine-backup",
                "proof_id": "synthetic-backup-proof",
            },
            "restore": {
                "status": "PASS",
                "proof_id": "synthetic-restore-proof",
            },
        },
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
    raw = folder / tiering.ORDER_BOOK_RAW
    os.utime(raw, (quiet_timestamp, quiet_timestamp))
    return snapshots_root, folder, raw_record


def _build_plan(snapshots_root: Path, *slugs: str) -> dict:
    return tiering.build_plan(
        snapshots_root,
        as_of_date=AS_OF,
        event_slugs=slugs or None,
        generated_at_utc="2026-06-23T01:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
    )


def _build_warm_plan(
    snapshots_root: Path,
    slug: str = SLUG,
    *,
    age_days: int = tiering.DEFAULT_HOT_WINDOW_DAYS,
    hot_window_days: int = tiering.DEFAULT_HOT_WINDOW_DAYS,
) -> dict:
    target_date = date_from_event_slug(slug)
    assert target_date is not None
    return tiering.build_warm_plan(
        snapshots_root,
        as_of_date=(target_date + timedelta(days=age_days)).isoformat(),
        hot_window_days=hot_window_days,
        event_slugs=[slug],
        generated_at_utc="2026-07-22T01:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
        today_utc=date(2026, 7, 29),
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


def _refresh_fixture_warm_manifest(
    folder: Path,
    *,
    snapshots_root: Path,
    manifest_validator,
    action: dict,
) -> dict:
    path = folder / "event_day_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    records = manifest["artifact_families"][0]["files"]
    records[:] = [
        row for row in records if row.get("path") != tiering.ORDER_BOOK_RAW
    ]
    records.append(
        _manifest_record(
            folder / tiering.ORDER_BOOK_RAW_GZIP,
            snapshots_root,
            rebuild_source="canonical raw evidence",
        )
    )
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    tiering._rebind_warm_manifest_protection(
        manifest,
        action,
        gzip_identity=tiering._file_identity(
            gzip_path,
            root=snapshots_root,
        ),
        gzip_payload=tiering._gzip_payload_identity(gzip_path),
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
        "plain_source_absent": True,
        "canonical_gzip_present": True,
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
    assert long_family.canonical_rebuild_sources == (
        "order_books.jsonl",
        "order_books.jsonl.gz",
    )
    assert (
        "canonical_jsonl:order_books.jsonl"
        in long_family.accepted_read_representations
    )
    assert (
        "canonical_jsonl_gzip:order_books.jsonl.gz"
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


def test_warm_registry_is_distinct_ordered_and_only_raw_books_are_eligible():
    rows = tiering.warm_compression_family_registry()

    assert tiering.validate_warm_compression_family_registry() == []
    assert [row["source_file"] for row in rows] == [
        "order_books.jsonl",
        "clob_tokens.jsonl",
        "replay_inputs.jsonl",
        "variant_predictions.jsonl",
        "order_books_summary.csv",
        "clob_tokens.csv",
    ]
    assert [row["source_file"] for row in rows if row["eligible"]] == [
        tiering.ORDER_BOOK_RAW
    ]
    assert all(row["readers"] for row in rows)
    assert all(
        row["blocker"] for row in rows if not row["eligible"]
    )
    assert len(
        {row["blocker"] for row in rows if not row["eligible"]}
    ) == 5
    raw_books = tiering.WARM_COMPRESSION_FAMILIES_BY_SOURCE_FILE[
        tiering.ORDER_BOOK_RAW
    ]
    assert raw_books.gzip_file == tiering.ORDER_BOOK_RAW_GZIP
    assert raw_books.reader_boundary == "weather.io.open_tiered_text"
    assert raw_books.blocker is None
    assert tiering.warm_compression_registry_hash()


def test_warm_registry_reader_inventory_is_complete():
    expected = {
        "order_books.jsonl": tuple(
            """
            content:weather.market.order_book_tape.iter_raw_jsonl_level_rows
            content:weather.operations.closed_day_projection_tiering.rebuild_one_order_books_long
            content:weather.operations.event_day_manifest._inspect_file
            content:weather.operations.event_day_manifest._row_count
            delegated:weather.market.order_book_tape.iter_full_book_rows
            delegated:weather.market.order_book_tape.rebuild_long_csv
            discovery:weather.market.order_book_tape.resolve_full_book_representation
            discovery:weather.operations.closed_day_projection_tiering._plan_folder
            discovery:weather.operations.closed_day_projection_tiering._plan_warm_folder
            discovery:weather.operations.closed_day_projection_tiering._assert_action_shape
            discovery:weather.operations.closed_day_projection_tiering._assert_action_current_before_compression
            discovery:weather.operations.closed_day_projection_tiering._refresh_and_validate_event_manifest
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive._planned_family
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.operations.clob_order_book_tiering.discover_rows
            discovery:weather.reporting.data_quality.clob_coverage_audit.audit_folder
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            discovery:weather.reporting.source_gates.source_family_inventory.clob_raw_tape_present
            discovery:weather.reporting.source_gates.source_family_inventory.scan_clob
            writer:weather.market.market_microstructure_capture.MarketMicrostructureStore.write_books
            """.split()
        ),
        "clob_tokens.jsonl": tuple(
            """
            content:weather.operations.event_day_manifest._inspect_file
            content:weather.operations.event_day_manifest._row_count
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive._planned_family
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.operations.clob_order_book_tiering.discover_rows
            discovery:weather.reporting.data_quality.clob_coverage_audit.audit_folder
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            writer:weather.market.market_microstructure_capture.MarketMicrostructureStore.write_token_rows
            """.split()
        ),
        "replay_inputs.jsonl": tuple(
            """
            content:weather.backtesting.replay._read_jsonl
            content:weather.calibration.pooled_candidate_replay._bounded_preselection_file_bytes
            content:weather.calibration.pooled_candidate_replay._bounded_preselection_replay_records
            content:weather.calibration.residual_distribution_corpus.read_jsonl
            content:weather.collection.snapshot_store.SnapshotStore.read_jsonl
            content:weather.collection.snapshot_tracker.read_jsonl_records
            content:weather.market.worker_release_binding._matching_replay_inputs
            content:weather.operations.density_live_replay_parity._read_jsonl_prefix
            content:weather.operations.observation_trigger.read_jsonl
            content:weather.reporting.casebooks.disagreement_casebook.read_jsonl
            content:weather.reporting.data_quality.feature_quality_quarantine.annotate_replay_presence
            content:weather.reporting.scorecards.captured_input_parity_evidence._read_rows_strict
            content:weather.sources.official_guidance_collection.collect_official_guidance_from_replay_inputs
            delegated:weather.backtesting.replay.load_replay_records
            delegated:weather.backtesting.replay_backtest.run_replay_backtest
            delegated:weather.backtesting.replay_ablation.run_ablation
            delegated:weather.calibration.pooled_candidate_replay.load_bounded_preselection_folder_inputs
            delegated:weather.calibration.pooled_candidate_replay.iter_bounded_preselection_source_market_days
            delegated:weather.collection.snapshot_store.SnapshotStore.replay_inputs_by_snapshot
            delegated:weather.collection.snapshot_tracker.backfill_source_status_for_folder
            delegated:weather.collection.snapshot_tracker.backfill_forecast_payloads_for_folder
            delegated:weather.reporting.promotion.promotion_corpus.build_promotion_corpus
            delegated:weather.reporting.validation.wu_max_since_7_validation.collect_validation_rows
            discovery:weather.calibration.residual_distribution_corpus._folder_input_lineage
            discovery:weather.calibration.residual_distribution_corpus.materialize_market_day_rows
            discovery:weather.collection.snapshot_tracker.replay_inputs_path_for_folder
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive.read_market_day_artifact
            discovery:weather.operations.closed_market_day_archive._read_source_frame
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.replay_cache_retention._stable_source
            discovery:weather.operations.replay_status_backfill.folder_evidence
            discovery:weather.operations.settled_day_freshness.market_row
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            discovery:weather.reporting.scorecards.snapshot_evaluation.snapshot_folder_summary
            discovery:weather.sources.official_guidance_collection._replay_paths
            writer:weather.collection.snapshot_store.SnapshotStore.write
            writer:weather.collection.snapshot_store.SnapshotStore.write_replay_input
            """.split()
        ),
        "variant_predictions.jsonl": tuple(
            """
            content:weather.calibration.residual_distribution_corpus.captured_comparator_probabilities
            content:weather.calibration.residual_distribution_corpus.read_jsonl
            content:weather.operations.density_live_replay_parity._read_variant_rows
            content:weather.reporting.scorecards.captured_input_parity_evidence._read_rows_strict
            discovery:weather.calibration.residual_distribution_corpus._folder_input_lineage
            discovery:weather.calibration.residual_distribution_corpus.materialize_market_day_rows
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive._planned_family
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            writer:weather.collection.snapshot_store.SnapshotStore.write
            """.split()
        ),
        "order_books_summary.csv": tuple(
            """
            content:weather.market.clob_recon.load_book_rows
            content:weather.market.market_latest_inputs.load_latest_market_inputs
            content:weather.market.market_making_run_support.latest_book_rows
            content:weather.market.market_making_run_support.preflight_csv_encoding_diagnostics
            content:weather.market.market_microstructure.book_capture_times
            content:weather.market.market_microstructure_features.clob_feature_rows_for_folder
            content:weather.market.mm_paper_scoring.load_book_rows
            content:weather.market.mm_paper_scoring.load_mark_rows
            content:weather.market.taker_bot_scoring.load_mark_rows
            content:weather.reporting.casebooks.disagreement_casebook.load_clob_context
            delegated:weather.calibration.pooled_candidate_replay.build_clob_feature_index
            delegated:weather.market.market_making_run_support.preflight_market
            delegated:weather.market.mm_paper.load_or_build_clob_recon
            discovery:weather.market.clob_recon.discover_snapshot_folders
            discovery:weather.market.market_making_preflight.remediation_last_good_artifact
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive.read_market_day_artifact
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.clob_order_book_tiering.discover_rows
            discovery:weather.operations.market_making_tape_encoding.discover_files
            discovery:weather.operations.replay_cache_retention.OPTIONAL_EVENT_REBUILD_INPUTS
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.reporting.data_quality.clob_coverage_audit.audit_folder
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            discovery:weather.reporting.scorecards.snapshot_evaluation.snapshot_folder_summary
            discovery:weather.reporting.source_gates.source_family_inventory.clob_raw_tape_present
            writer:weather.market.market_microstructure_capture.MarketMicrostructureStore.write_books
            """.split()
        ),
        "clob_tokens.csv": tuple(
            """
            content:weather.market.market_latest_inputs.load_latest_market_inputs
            content:weather.market.market_making_run_support.preflight_csv_encoding_diagnostics
            content:weather.market.market_making_run_support.preflight_market
            content:weather.market.taker_bot_strategy_evaluation.preflight_summary_for_market
            discovery:weather.market.market_making_preflight.remediation_last_good_artifact
            discovery:weather.operations.closed_market_day_archive.ARTIFACT_FAMILIES
            discovery:weather.operations.closed_market_day_archive.read_market_day_artifact
            discovery:weather.operations.event_day_manifest.EVENT_DAY_ARTIFACT_FAMILIES
            discovery:weather.operations.event_day_manifest._iter_family_files
            discovery:weather.operations.clob_order_book_tiering.discover_rows
            discovery:weather.operations.market_making_tape_encoding.discover_files
            discovery:weather.operations.storage_classes.ARTIFACT_FAMILIES
            discovery:weather.reporting.data_quality.clob_coverage_audit.audit_folder
            discovery:weather.reporting.data_quality.data_layer_audit_collectors.snapshot_folder_audit
            writer:weather.market.market_microstructure_capture.MarketMicrostructureStore.write_token_rows
            """.split()
        ),
    }
    actual = {
        row["source_file"]: tuple(row["readers"])
        for row in tiering.warm_compression_family_registry()
    }

    assert actual == expected


def test_warm_plan_is_read_only_and_persists_hot_window_derivation(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    before = {
        path.relative_to(snapshots_root).as_posix(): (
            path.stat().st_size,
            sha256_file(path),
        )
        for path in snapshots_root.rglob("*")
        if path.is_file()
    }

    plan = _build_warm_plan(snapshots_root, folder.name)

    after = {
        path.relative_to(snapshots_root).as_posix(): (
            path.stat().st_size,
            sha256_file(path),
        )
        for path in snapshots_root.rglob("*")
        if path.is_file()
    }
    assert plan["schema_version"] == tiering.WARM_PLAN_SCHEMA_VERSION
    assert plan["plan_kind"] == "canonical_warm_compression"
    assert plan["mode"] == "dry_run"
    assert plan["status"] == "PASS"
    assert plan["summary"]["eligible_action_count"] == 1
    assert plan["actions"][0]["source"]["path"].endswith(
        tiering.ORDER_BOOK_RAW
    )
    assert plan["actions"][0]["gzip"]["path"].endswith(
        tiering.ORDER_BOOK_RAW_GZIP
    )
    assert plan["actions"][0]["gzip"]["deterministic_mtime"] == 0
    assert plan["actions"][0]["reader_boundary"] == (
        "weather.io.open_tiered_text"
    )
    assert plan["hot_window"] == {
        "configured_hot_window_days": 30,
        "effective_warm_age_days": 30,
        "minimum_warm_age_days": 21,
        "default_hot_window_days": 30,
        "default_recovery_margin_days": 9,
        "binding_consumer": "production_point_in_time_evaluation_window",
        "derivation": {
            "contiguous_window_days": 14,
            "maximum_latest_target_age_days": 7,
            "minimum_warm_age_formula": (
                "contiguous_window_days + maximum_latest_target_age_days"
            ),
            "minimum_warm_age_days": 21,
            "default_hot_window_formula": (
                "minimum_warm_age_days + default_recovery_margin_days"
            ),
            "default_hot_window_days": 30,
            "code_evidence": [
                (
                    "weather.point_in_time_contract:"
                    "canonical_contiguous_14_day_window"
                ),
                (
                    "weather.reporting.validation.point_in_time_evaluation:"
                    "PRODUCTION_MAX_LATEST_TARGET_AGE_DAYS"
                ),
            ],
        },
    }
    proof = plan["actions"][0]["closed_finalized_proof"]
    assert proof["age_days"] == 30
    assert proof["closed_before_as_of"] is True
    assert proof["writer_locks_absent"] is True
    assert proof["source_quiescence"]["status"] == "PASS"
    assert proof["finalization"]["state"] == "closed_unlabeled"
    assert plan["operator_review"]["approved"] is False
    assert tiering.plan_hash_valid(plan)
    assert before == after
    assert not (folder / tiering.ORDER_BOOK_RAW_GZIP).exists()


@pytest.mark.parametrize(
    ("age_days", "expected_status", "expected_folder_status"),
    [
        (20, "NOT_DONE", "WAIT_HOT_WINDOW"),
        (21, "PASS", "ELIGIBLE"),
    ],
)
def test_warm_plan_enforces_code_derived_minimum_age_20_21(
    tmp_path,
    age_days,
    expected_status,
    expected_folder_status,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)

    plan = _build_warm_plan(
        snapshots_root,
        folder.name,
        age_days=age_days,
        hot_window_days=tiering.MIN_WARM_AGE_DAYS,
    )

    assert plan["status"] == expected_status
    assert plan["folders"][0]["status"] == expected_folder_status
    assert plan["hot_window"]["minimum_warm_age_days"] == 21
    assert plan["hot_window"]["configured_hot_window_days"] == 21
    assert len(plan["actions"]) == (1 if age_days == 21 else 0)


@pytest.mark.parametrize(
    ("age_days", "expected_status", "expected_folder_status"),
    [
        (29, "NOT_DONE", "WAIT_HOT_WINDOW"),
        (30, "PASS", "ELIGIBLE"),
    ],
)
def test_warm_plan_enforces_default_hot_window_29_30(
    tmp_path,
    age_days,
    expected_status,
    expected_folder_status,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)

    plan = _build_warm_plan(
        snapshots_root,
        folder.name,
        age_days=age_days,
    )

    assert plan["status"] == expected_status
    assert plan["folders"][0]["status"] == expected_folder_status
    assert plan["hot_window"]["default_hot_window_days"] == 30
    assert plan["hot_window"]["configured_hot_window_days"] == 30
    assert len(plan["actions"]) == (1 if age_days == 30 else 0)


def test_warm_plan_rejects_a_configured_window_below_minimum(tmp_path):
    snapshots_root, _, _ = _make_fixture(tmp_path)

    with pytest.raises(
        tiering.ProjectionTieringError,
        match="minimum warm age of 21 days",
    ):
        _build_warm_plan(
            snapshots_root,
            age_days=21,
            hot_window_days=20,
        )


def test_warm_window_requires_a_strict_integer():
    with pytest.raises(
        tiering.ProjectionTieringError,
        match="must be an integer",
    ):
        tiering.warm_window_derivation(21.0)


def test_warm_plan_rejects_a_future_as_of_date(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)

    with pytest.raises(
        tiering.ProjectionTieringError,
        match="as_of_date cannot be in the future",
    ):
        tiering.build_warm_plan(
            snapshots_root,
            as_of_date="2026-07-30",
            event_slugs=[folder.name],
            manifest_validator=_pass_manifest_validator,
            today_utc=date(2026, 7, 29),
        )


def test_order_books_raw_deterministic_gzip_round_trip(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_RAW
    first = folder / "first-order-books.jsonl.gz"
    second = folder / "second-order-books.jsonl.gz"

    tiering._write_deterministic_gzip(source, first)
    tiering._write_deterministic_gzip(source, second)

    source_identity = tiering._file_identity(source)
    first_payload = tiering._gzip_payload_identity(first)
    assert first_payload["payload_bytes"] == source_identity["bytes"]
    assert first_payload["payload_sha256"] == source_identity["sha256"]
    assert gzip.decompress(first.read_bytes()) == source.read_bytes()
    assert first.read_bytes() == second.read_bytes()
    assert int.from_bytes(first.read_bytes()[4:8], "little") == 0
    assert snapshots_root.exists()


def test_warm_plan_accepts_identical_transition_and_blocks_conflict(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_RAW
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    tiering._write_deterministic_gzip(source, gzip_path)
    quiet_timestamp = time.time() - tiering.MIN_QUIET_SECONDS - 60.0
    os.utime(gzip_path, (quiet_timestamp, quiet_timestamp))

    identical = _build_warm_plan(snapshots_root, folder.name)

    assert identical["status"] == "PASS"
    assert len(identical["actions"]) == 1
    assert (
        identical["actions"][0]["action"]
        == "remove_verified_identical_plain_peer"
    )
    assert identical["actions"][0]["gzip"]["preexisting"] is True
    assert (
        identical["folders"][0]["status"]
        == "ELIGIBLE_IDENTICAL_TRANSITION"
    )
    assert (
        identical["folders"][0]["representation"]["transitional_pair"]
        is True
    )
    with gzip_path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            mtime=0,
        ) as handle:
            handle.write(b'{"different":true}\n')
    os.utime(gzip_path, (quiet_timestamp, quiet_timestamp))

    conflict = _build_warm_plan(snapshots_root, folder.name)

    assert conflict["status"] == "BLOCK"
    assert conflict["actions"] == []
    assert conflict["folders"][0]["status"] == "BLOCK"
    assert any(
        blocker.startswith("tiered_text_conflict:")
        for blocker in conflict["folders"][0]["blockers"]
    )


@pytest.mark.parametrize(
    ("mutation", "expected_blocker"),
    [
        ("manifest_not_pass", "event_day_manifest_not_finalized_pass"),
        ("writer_lock", "event_folder_writer_lock_present"),
        ("recently_written", "order_books.jsonl_recently_written"),
    ],
)
def test_warm_plan_fails_closed_on_manifest_writer_and_quiescence_gates(
    tmp_path,
    mutation,
    expected_blocker,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    if mutation == "manifest_not_pass":
        _write_manifest(folder, snapshots_root, status="WARN")
    elif mutation == "writer_lock":
        (folder / tiering.RAW_TAPE_WRITER_LOCK).write_text(
            "synthetic lock\n",
            encoding="utf-8",
        )
    elif mutation == "recently_written":
        os.utime(folder / tiering.ORDER_BOOK_RAW, None)

    plan = _build_warm_plan(snapshots_root, folder.name)

    assert plan["status"] == "BLOCK"
    assert plan["actions"] == []
    assert expected_blocker in plan["folders"][0]["blockers"]
    assert not (folder / tiering.ORDER_BOOK_RAW_GZIP).exists()


def test_warm_apply_requires_external_approval_and_durable_receipt(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    plan = _build_warm_plan(snapshots_root, folder.name)

    receipt = tiering.apply_approved_warm_plan(
        plan,
        manifest_validator=_pass_manifest_validator,
        today_utc=date(2026, 7, 29),
    )

    assert receipt["status"] == "BLOCK"
    assert "operator_review.approved must be true" in (
        receipt["approval_errors"]
    )
    assert (folder / tiering.ORDER_BOOK_RAW).exists()
    assert not (folder / tiering.ORDER_BOOK_RAW_GZIP).exists()


def test_warm_apply_rejects_a_non_durable_receipt_callback(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    receipt_root = tmp_path / "receipts"

    with pytest.raises(
        tiering.ProjectionTieringError,
        match="checkpoint could not be re-read",
    ):
        tiering.apply_approved_warm_plan(
            approved,
            manifest_validator=_pass_manifest_validator,
            manifest_refresher=_refresh_fixture_warm_manifest,
            persist_receipt=lambda _payload: None,
            receipt_json_path=receipt_root / "missing-receipt.json",
            receipt_report_path=receipt_root / "missing-receipt.md",
            approved_manifest_identity=approved_identity,
            today_utc=date(2026, 7, 29),
        )

    assert (folder / tiering.ORDER_BOOK_RAW).exists()
    assert not (folder / tiering.ORDER_BOOK_RAW_GZIP).exists()


def test_warm_apply_replaces_only_plain_representation_after_checkpoint(
    tmp_path,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_RAW
    source_bytes = source.read_bytes()
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )

    receipt = tiering.apply_approved_warm_plan(
        approved,
        generated_at_utc="2026-07-22T03:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )

    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    assert receipt["status"] == "PASS"
    assert receipt["summary"]["applied"] == 1
    assert not source.exists()
    assert gzip_path.is_file()
    assert gzip.decompress(gzip_path.read_bytes()) == source_bytes
    assert gzip_path.read_bytes()[4:8] == b"\x00\x00\x00\x00"
    action = receipt["actions"][0]
    assert action["cleanup_preflight"]["status"] == "PASS"
    assert action["final_reverification"]["status"] == "PASS"
    assert action["durable_pre_unlink_checkpoint"]["path"] == str(
        json_path.resolve()
    )
    assert action["representation_replacement"]["status"] == "PASS"
    assert action["event_day_manifest_refresh_required"] is False
    assert action["raw_tape_writer_lock"]["status"] == "RELEASED"
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "PASS"
    assert report_path.stat().st_size > 0
    manifest = json.loads(
        (folder / "event_day_manifest.json").read_text(encoding="utf-8")
    )
    manifest_paths = {
        row["path"]
        for family in manifest["artifact_families"]
        for row in family["files"]
    }
    assert tiering.ORDER_BOOK_RAW not in manifest_paths
    assert tiering.ORDER_BOOK_RAW_GZIP in manifest_paths


def test_default_warm_manifest_refresh_rebinds_exact_protection_proof(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        event_manifest_module,
        "_payload_blob_link_validation",
        _pass_payload_blob_links,
    )
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    _write_required_event_day_evidence(folder)
    source = folder / tiering.ORDER_BOOK_RAW
    source_bytes = source.read_bytes()
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_action = approved["actions"][0]
    approved_protection = approved_action["event_manifest"]["protection"]
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-default-refresh-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )

    receipt = tiering.apply_approved_warm_plan(
        approved,
        generated_at_utc="2026-07-22T03:00:00+00:00",
        manifest_validator=_pass_manifest_validator,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )

    assert receipt["status"] == "PASS"
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    assert not source.exists()
    assert gzip.decompress(gzip_path.read_bytes()) == source_bytes
    manifest = json.loads(
        (folder / "event_day_manifest.json").read_text(encoding="utf-8")
    )
    protection = manifest["protection"]
    rebind = protection["warm_representation_rebind"]
    assert protection["status"] == "PASS"
    assert (
        protection["pre_replacement_protection"]
        == approved_protection
    )
    assert (
        protection["backup"]["pre_replacement_proof"]
        == approved_protection["backup"]
    )
    assert (
        protection["restore"]["pre_replacement_proof"]
        == approved_protection["restore"]
    )
    assert rebind["protected_plain_source"] == approved_action["source"]
    assert rebind["semantic_identity"] == {
        "bytes": len(source_bytes),
        "sha256": approved_action["source"]["sha256"],
    }
    assert rebind["retained_gzip_decompressed_payload"][
        "payload_sha256"
    ] == approved_action["source"]["sha256"]
    rebind_check = next(
        check
        for check in manifest["validation"]["checks"]
        if check.get("check") == "canonical_warm_representation_rebind"
    )
    assert rebind["proof_hash"] == rebind_check["proof_hash"]

    retried = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        existing_receipt=receipt,
        today_utc=date(2026, 7, 29),
    )

    assert retried["status"] == "PASS"
    assert retried["actions"][0][
        "completed_state_reverification"
    ]["protection_rebind"]["proof_hash"] == rebind["proof_hash"]


def test_warm_apply_does_not_trust_a_custom_refresh_pass(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-unverified-refresh-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )

    def unverified_refresh(*_args, **_kwargs):
        return {"status": "PASS"}

    receipt = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=unverified_refresh,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )

    assert receipt["status"] == "BLOCK"
    assert "post-refresh warm manifest representation" in (
        receipt["actions"][0]["failure"]["detail"]
    )
    assert not (folder / tiering.ORDER_BOOK_RAW).exists()
    assert (folder / tiering.ORDER_BOOK_RAW_GZIP).is_file()


def test_warm_apply_recovers_manifest_refresh_after_exact_unlink(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        event_manifest_module,
        "_payload_blob_link_validation",
        _pass_payload_blob_links,
    )
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    _write_required_event_day_evidence(folder)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-recovery-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )

    def interrupted_refresh(*_args, **_kwargs):
        raise RuntimeError("synthetic interruption before manifest refresh")

    interrupted = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=interrupted_refresh,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )

    assert interrupted["status"] == "BLOCK"
    assert interrupted["actions"][0]["resume_state"] == (
        "MANIFEST_REFRESH_PENDING"
    )
    assert not (folder / tiering.ORDER_BOOK_RAW).exists()
    assert (folder / tiering.ORDER_BOOK_RAW_GZIP).is_file()
    existing = json.loads(json_path.read_text(encoding="utf-8"))

    recovered = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        existing_receipt=existing,
        today_utc=date(2026, 7, 29),
    )

    assert recovered["status"] == "PASS"
    action = recovered["actions"][0]
    assert action["status"] == "APPLIED"
    assert action["representation_replacement"][
        "recovered_after_interruption"
    ] is True
    assert action["event_day_manifest_refresh_required"] is False
    assert action["event_day_manifest_refresh"][
        "protection_rebind"
    ]["status"] == "PASS"
    assert not (folder / tiering.ORDER_BOOK_RAW).exists()
    assert (folder / tiering.ORDER_BOOK_RAW_GZIP).is_file()


def test_warm_plan_reports_gzip_only_canonical_evidence_as_already_warm(
    tmp_path,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_RAW
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    tiering._write_deterministic_gzip(source, gzip_path)
    source.unlink()
    _write_manifest(folder, snapshots_root)
    quiet_timestamp = time.time() - tiering.MIN_QUIET_SECONDS - 60.0
    os.utime(gzip_path, (quiet_timestamp, quiet_timestamp))

    plan = _build_warm_plan(snapshots_root, folder.name)

    assert plan["status"] == "NOT_DONE"
    assert plan["actions"] == []
    assert plan["folders"][0]["status"] == "ALREADY_WARM"
    assert (
        plan["folders"][0]["representation"]["selected_representation"]
        == "gzip"
    )


def test_warm_plan_blocks_identical_but_nondeterministic_gzip(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    source = folder / tiering.ORDER_BOOK_RAW
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    with gzip_path.open("wb") as raw_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_handle,
            mtime=1,
        ) as handle:
            handle.write(source.read_bytes())
    quiet_timestamp = time.time() - tiering.MIN_QUIET_SECONDS - 60.0
    os.utime(gzip_path, (quiet_timestamp, quiet_timestamp))

    plan = _build_warm_plan(snapshots_root, folder.name)

    assert plan["status"] == "BLOCK"
    assert plan["actions"] == []
    assert (
        "preexisting_gzip_is_not_the_deterministic_mtime_zero_representation"
        in plan["folders"][0]["blockers"]
    )


def test_warm_apply_adopts_exact_gzip_after_compression_pending_checkpoint(
    tmp_path,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    action = approved["actions"][0]
    gzip_path = folder / tiering.ORDER_BOOK_RAW_GZIP
    tiering._write_deterministic_gzip(
        folder / tiering.ORDER_BOOK_RAW,
        gzip_path,
    )
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-intent-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )
    existing = {
        "schema_version": tiering.WARM_RECEIPT_SCHEMA_VERSION,
        "generated_at_utc": "2026-07-22T03:00:00+00:00",
        "writer": tiering.WRITER,
        "mode": "warm_apply",
        "status": "RUNNING",
        "plan_hash": approved["plan_hash"],
        "snapshots_root": approved["snapshots_root"],
        "approved_manifest_identity": approved_identity,
        "operator_review": approved["operator_review"],
        "approval_errors": [],
        "stop_on_first_failure": True,
        "actions": [
            {
                "action_id": action["action_id"],
                "warm_family": action["warm_family"],
                "source": action["source"],
                "status": "COMPRESSION_PENDING",
                "compression_intent": tiering._warm_compression_intent(
                    action
                ),
            }
        ],
    }
    tiering._update_warm_apply_summary(existing, planned=1)
    persist(existing)

    receipt = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        existing_receipt=existing,
        today_utc=date(2026, 7, 29),
    )

    assert receipt["status"] == "PASS"
    assert receipt["actions"][0]["compression"][
        "adopted_from_durable_intent"
    ] is True
    assert not (folder / tiering.ORDER_BOOK_RAW).exists()
    assert gzip_path.is_file()


def test_warm_apply_reverifies_completed_action_and_blocks_a_stale_lock(
    tmp_path,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-completed-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )
    completed = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )
    assert completed["status"] == "PASS"
    (folder / tiering.RAW_TAPE_WRITER_LOCK).write_text(
        "synthetic stale lock\n",
        encoding="utf-8",
    )
    existing = json.loads(json_path.read_text(encoding="utf-8"))

    retried = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        existing_receipt=existing,
        today_utc=date(2026, 7, 29),
    )

    assert retried["status"] == "BLOCK"
    assert "writer lock" in retried["actions"][0]["failure"]["detail"]
    (folder / tiering.RAW_TAPE_WRITER_LOCK).unlink()
    retry_after_lock = json.loads(json_path.read_text(encoding="utf-8"))

    recovered = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=persist,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        existing_receipt=retry_after_lock,
        today_utc=date(2026, 7, 29),
    )

    assert recovered["status"] == "PASS"
    assert recovered["actions"][0]["status"] == "APPLIED"
    assert recovered["actions"][0]["completed_state_reverification"][
        "status"
    ] == "PASS"


def test_warm_apply_releases_raw_lock_when_checkpoint_fails_after_acquire(
    tmp_path,
):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    durable, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-flaky-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )
    calls = 0

    def fail_once_after_lock(payload):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic post-lock receipt failure")
        durable(payload)

    receipt = tiering.apply_approved_warm_plan(
        approved,
        manifest_validator=_pass_manifest_validator,
        manifest_refresher=_refresh_fixture_warm_manifest,
        persist_receipt=fail_once_after_lock,
        receipt_json_path=json_path,
        receipt_report_path=report_path,
        approved_manifest_identity=approved_identity,
        today_utc=date(2026, 7, 29),
    )

    assert receipt["status"] == "BLOCK"
    assert not (folder / tiering.RAW_TAPE_WRITER_LOCK).exists()
    assert (folder / tiering.ORDER_BOOK_RAW).is_file()
    assert not (folder / tiering.ORDER_BOOK_RAW_GZIP).exists()


def test_warm_apply_refuses_to_overwrite_unbound_existing_receipt(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    approved = _approve(_build_warm_plan(snapshots_root, folder.name))
    approved_identity = _approved_identity(tmp_path, approved)
    persist, json_path, report_path = tiering.make_receipt_persister(
        output_root=tmp_path / "warm-unbound-receipts",
        stem="warm-apply",
        protected_root=snapshots_root.parent,
    )
    existing = {
        "schema_version": tiering.WARM_RECEIPT_SCHEMA_VERSION,
        "generated_at_utc": "2026-07-22T03:00:00+00:00",
        "writer": tiering.WRITER,
        "mode": "warm_apply",
        "status": "RUNNING",
        "plan_hash": "not-the-approved-plan",
        "snapshots_root": approved["snapshots_root"],
        "approved_manifest_identity": approved_identity,
        "operator_review": approved["operator_review"],
        "approval_errors": [],
        "stop_on_first_failure": True,
        "actions": [],
        "summary": {},
    }
    persist(existing)
    before_json = json_path.read_bytes()
    before_report = report_path.read_bytes()

    with pytest.raises(
        tiering.ProjectionTieringError,
        match="refusing to overwrite unbound existing warm receipt",
    ):
        tiering.apply_approved_warm_plan(
            approved,
            persist_receipt=persist,
            receipt_json_path=json_path,
            receipt_report_path=report_path,
            approved_manifest_identity=approved_identity,
            existing_receipt=existing,
            today_utc=date(2026, 7, 29),
        )

    assert json_path.read_bytes() == before_json
    assert report_path.read_bytes() == before_report


def test_warm_cli_parser_and_report_expose_the_separate_surface(tmp_path):
    parser = tiering.build_parser()
    args = parser.parse_args(
        [
            "warm-plan",
            "--snapshots-root",
            str(tmp_path / "snapshots"),
            "--as-of-date",
            "2026-07-29",
            "--output-root",
            str(tmp_path / "out"),
            "--protected-root",
            str(tmp_path / "data"),
        ]
    )

    assert args.command == "warm-plan"
    assert args.hot_window_days == tiering.DEFAULT_HOT_WINDOW_DAYS
    report = tiering.render_report(
        {
            "mode": "dry_run",
            "plan_kind": "canonical_warm_compression",
            "status": "NOT_DONE",
            "generated_at_utc": "2026-07-29T00:00:00+00:00",
            "writer": tiering.WRITER,
            "summary": {},
            "warm_compression_family_registry": (
                tiering.warm_compression_family_registry()
            ),
            "hot_window": tiering.warm_window_derivation(),
            "folders": [],
        }
    )
    assert "# Closed-Day Warm Tiering - dry_run" in report
    assert "## Hot-window proof" in report
    assert "order_books_jsonl" in report


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
        ("missing_raw", "canonical_order_books_tiered_text_missing"),
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


def test_projection_plan_and_rebuild_accept_gzip_canonical_raw(tmp_path):
    snapshots_root, folder, _ = _make_fixture(tmp_path)
    raw = folder / tiering.ORDER_BOOK_RAW
    raw_gzip = folder / tiering.ORDER_BOOK_RAW_GZIP
    tiering._write_deterministic_gzip(raw, raw_gzip)
    raw.unlink()
    _write_manifest(folder, snapshots_root)
    plan = _build_plan(snapshots_root, folder.name)

    receipt = tiering.rebuild_one_order_books_long(
        folder,
        output_root=tmp_path / "gzip-raw-proof",
        generated_at_utc="2026-06-23T04:00:00+00:00",
    )

    assert plan["status"] == "PASS"
    assert plan["actions"][0]["canonical_rebuild_source"][
        "path"
    ].endswith(tiering.ORDER_BOOK_RAW_GZIP)
    assert receipt["status"] == "PASS"
    assert receipt["canonical_rebuild_source"]["path"].endswith(
        tiering.ORDER_BOOK_RAW_GZIP
    )


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
