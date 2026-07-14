import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from weather.collection.snapshot_store import SnapshotStore
from weather.operations.event_day_manifest import _payload_blob_link_validation
from weather.operations.forecast_payload_cas_migration import (
    build_migration_dry_run,
    main as migration_main,
    render_markdown,
)
from weather.sources.nbm_probabilistic_tmax import parse_nbp_station_tmax


NBP_TEXT = """
 KLGA    NBM V5.0 NBP GUIDANCE    5/30/2026  0000 UTC
FHR    24  36| 48  60
TXNMN  84  68| 79  68
TXNSD   2   2|  4   3
TXNP1  81  64| 73  63
TXNP2  82  66| 76  66
TXNP5  84  68| 80  69
TXNP7  85  69| 82  71
TXNP9  86  70| 84  72
"""


def test_migration_is_inventory_only_and_proves_restore_hash_and_replay(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": {
                    "raw_payload": {
                        "schema_version": "nbm_probabilistic_tmax_v0.1",
                        "source": "nbm_probabilistic_tmax",
                        "source_kind": "nbp_station_text",
                        "station_id": "KLGA",
                        "target_date": "2026-05-30",
                        "source_url": "https://example.test/legacy",
                        "fetched_at": "2026-05-30T01:00:00+00:00",
                        "text": NBP_TEXT,
                    }
                }
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
    )[0]
    legacy_path = Path(row["raw_payload_path"])
    before = legacy_path.read_bytes()

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["mode"] == "inventory_dry_run"
    assert report["mutation_performed"] is False
    assert report["deletion_enabled"] is False
    assert report["summary"]["candidate_row_count"] == 1
    assert report["summary"]["verified_candidate_row_count"] == 1
    assert report["summary"]["unique_shared_payload_count"] == 1
    assert report["candidates"][0]["restore_hash_status"] == "PASS"
    assert report["candidates"][0]["replay_status"] == "PASS"
    assert report["candidates"][0]["would_copy"] is True
    assert report["candidates"][0]["would_rewrite_manifest"] is False
    assert report["candidates"][0]["would_delete_legacy_blob"] is False
    assert legacy_path.read_bytes() == before
    assert not shared.exists()


def test_migration_reports_corrupt_legacy_blob_without_mutation(tmp_path):
    event = tmp_path / "snapshots" / "event"
    event.mkdir(parents=True)
    blob = event / "forecast_payloads" / "sha256" / ("a" * 2) / f"{'a' * 64}.json"
    blob.parent.mkdir(parents=True)
    blob.write_text(json.dumps({"text": NBP_TEXT}) + "\n", encoding="utf-8")
    manifest = event / "forecast_payloads.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "forecast_payload_manifest_v1",
                "snapshot_id": "s1",
                "event_slug": "event",
                "source": "nbm_probabilistic_tmax",
                "payload_hash": "a" * 64,
                "payload_bytes": 1,
                "raw_payload_path": str(blob),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before = blob.read_bytes()

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=tmp_path / "shared",
    )

    assert report["summary"]["blocked_candidate_row_count"] == 1
    assert "legacy_hash_or_restore_failed" in report["candidates"][0]["issues"][0]
    assert blob.read_bytes() == before
    assert not (tmp_path / "shared").exists()


def test_event_day_payload_validation_accepts_and_verifies_shared_reference(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": parse_nbp_station_tmax(
                    NBP_TEXT,
                    "KLGA",
                    "2026-05-30",
                    source_url=(
                        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
                        "blend.20260530/00/text/blend_nbptx.t00z"
                    ),
                )
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
    )[0]

    validation = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family for family in validation["families"]
        if family["artifact_family"] == "forecast_payloads"
    )
    assert forecast["status"] == "PASS"
    assert forecast["shared_linked_blob_count"] == 1
    assert forecast["blob_count"] == 0

    Path(row["raw_payload_path"]).write_bytes(b"corrupt")
    corrupt = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family for family in corrupt["families"]
        if family["artifact_family"] == "forecast_payloads"
    )
    assert forecast["status"] == "BLOCK"
    assert any(
        issue["code"] == "raw_payload_blob_hash_mismatch"
        for issue in forecast["issues"]
    )


def test_event_day_validation_rejects_matching_blob_outside_expected_cas_root(tmp_path):
    event, shared, row = _write_shared_row(tmp_path)
    expected = Path(row["raw_payload_path"])
    rogue = (
        tmp_path
        / "rogue-cas"
        / "sha256"
        / row["payload_hash"][:2]
        / f"{row['payload_hash']}.blob"
    )
    rogue.parent.mkdir(parents=True)
    shutil.copy2(expected, rogue)
    row["raw_payload_path"] = str(rogue)
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    validation = _payload_blob_link_validation(event, shared_cas_root=shared)
    forecast = next(
        family
        for family in validation["families"]
        if family["artifact_family"] == "forecast_payloads"
    )

    assert forecast["status"] == "BLOCK"
    assert any(
        issue["code"] == "shared_payload_reference_invalid"
        for issue in forecast["issues"]
    )


def _write_shared_row(tmp_path):
    event = tmp_path / "snapshots" / "event"
    shared = tmp_path / "shared-cas"
    store = SnapshotStore(
        root=event,
        event_slug="event",
        shared_forecast_payload_cas_root=shared,
    )
    store.root.mkdir(parents=True)
    row = store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": parse_nbp_station_tmax(
                    NBP_TEXT,
                    "KLGA",
                    "2026-05-30",
                    source_url=(
                        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
                        "blend.20260530/00/text/blend_nbptx.t00z"
                    ),
                    fetched_at="2026-05-30T01:00:00+00:00",
                )
            }
        },
        "s1",
        datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
        "model-v",
        config_identity={"market_id": "nyc", "target_date": "2026-05-30"},
    )[0]
    return event, shared, row


def test_migration_shared_reachability_is_verified_and_partial_only(tmp_path):
    _event, shared, row = _write_shared_row(tmp_path)

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["inventory_scope"] == "snapshot_forecast_payload_jsonl_only"
    assert report["authoritative_for_garbage_collection"] is False
    assert report["reachability"]["status"] == "PARTIAL_INVENTORY_ONLY"
    assert report["reachability"]["authoritative_for_garbage_collection"] is False
    assert report["reachability"]["delete_candidates"] == []
    assert report["summary"]["candidate_row_count"] == 0
    assert report["summary"]["verified_shared_reference_row_count"] == 1
    assert report["summary"]["blocked_shared_reference_row_count"] == 0
    assert report["reachability"]["verified_active_shared_digests"] == [
        row["payload_hash"]
    ]
    assert "unreachable_candidate_digests" not in report["reachability"]
    markdown = render_markdown(report)
    assert "partial inventory only" in markdown
    assert "Authoritative for garbage collection: False" in markdown


@pytest.mark.parametrize(
    "tamper",
    [
        "ref",
        "size",
        "identity",
        "schema",
        "media",
        "retained",
        "blob",
        "request",
        "cycle",
        "market_station",
    ],
)
def test_migration_never_counts_unverified_shared_reference(tmp_path, tamper):
    event, shared, row = _write_shared_row(tmp_path)
    if tamper == "ref":
        row["payload_ref"] = f"sha256/ff/{'f' * 64}.blob"
    elif tamper == "size":
        row["payload_bytes"] += 1
    elif tamper == "identity":
        row["extraction_identity"] = "{}"
    elif tamper == "schema":
        row["extraction_schema"] = "unknown_extraction_v1"
    elif tamper == "media":
        row["payload_media_type"] = "application/octet-stream"
    elif tamper == "retained":
        row["raw_payload_retained"] = False
    elif tamper == "blob":
        Path(row["raw_payload_path"]).write_bytes(b"corrupt")
    elif tamper == "request":
        row["request_key"] = "nbm_probabilistic_tmax:GET:sha256:" + "f" * 64
    elif tamper == "cycle":
        row["cycle_key"] = "nbm-nbp:19990101T00Z"
    elif tamper == "market_station":
        row["market_id"] = "austin"
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps(row, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report = build_migration_dry_run(
        snapshot_root=tmp_path / "snapshots",
        shared_cas_root=shared,
    )

    assert report["summary"]["verified_shared_reference_row_count"] == 0
    assert report["summary"]["blocked_shared_reference_row_count"] == 1
    assert report["reachability"]["verified_active_shared_digests"] == []
    assert report["reachability"]["delete_candidates"] == []


def _write_legacy_inventory_row(snapshot_root, event_name, captured_at):
    event = snapshot_root / event_name
    store = SnapshotStore(
        root=event,
        event_slug=event_name,
        shared_forecast_payload_cas_root=snapshot_root.parent / "shared",
    )
    store.root.mkdir(parents=True)
    return store.write_forecast_payloads(
        {
            "nbm_probabilistic_tmax": {
                "data": {
                    "raw_payload": {
                        "schema_version": "nbm_probabilistic_tmax_v0.1",
                        "source": "nbm_probabilistic_tmax",
                        "source_kind": "nbp_station_text",
                        "station_id": "KLGA",
                        "target_date": "2026-05-30",
                        "source_url": "https://example.test/legacy",
                        "fetched_at": "2026-05-30T01:00:00+00:00",
                        "text": NBP_TEXT,
                    }
                }
            }
        },
        f"snapshot-{event_name}",
        captured_at,
        "model-v",
    )[0]


def test_bounded_inventory_reports_verified_legacy_duplicate_bytes_by_month(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    _write_legacy_inventory_row(
        snapshot_root,
        "2026-01-a",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    _write_legacy_inventory_row(
        snapshot_root,
        "2026-01-b",
        datetime(2026, 1, 6, 1, tzinfo=timezone.utc),
    )
    _write_legacy_inventory_row(
        snapshot_root,
        "2026-02-a",
        datetime(2026, 2, 5, 1, tzinfo=timezone.utc),
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        candidate_detail_limit=1,
    )

    assert report["schema_version"] == "forecast_payload_cas_migration_dry_run_v0.2"
    assert report["bounds"]["status"] == "COMPLETE"
    assert report["bounds"]["observed"]["candidate_detail_count"] == 1
    assert report["bounds"]["observed"]["candidate_detail_omitted_count"] == 2
    assert report["summary"]["candidate_row_count"] == 3
    assert report["summary"]["verified_candidate_row_count"] == 3
    assert report["summary"]["verified_legacy_stored_bytes"] > 0
    assert report["summary"]["projected_reclaimable_legacy_bytes"] > 0
    by_month = {
        row["month"]: row
        for row in report["legacy_duplicate_bytes_by_month"]
    }
    assert by_month["2026-01"]["candidate_row_count"] == 2
    assert by_month["2026-02"]["candidate_row_count"] == 1
    assert by_month["2026-01"]["projected_reclaimable_legacy_bytes"] > 0
    assert sum(
        row["verified_legacy_stored_bytes"]
        for row in report["legacy_duplicate_bytes_by_month"]
    ) == report["summary"]["verified_legacy_stored_bytes"]
    assert sum(
        row["projected_shared_physical_bytes"]
        for row in report["legacy_duplicate_bytes_by_month"]
    ) > report["summary"]["projected_physical_bytes"]
    markdown = render_markdown(report)
    assert "Legacy Duplicate Bytes By Month" in markdown
    assert "Monthly one-copy projections are not additive" in markdown
    assert "| 2026-01 | 2 | 2 | 0 |" in markdown


def test_inventory_manifest_row_bound_stops_with_resume_cursor(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    _write_legacy_inventory_row(
        snapshot_root,
        "a",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    _write_legacy_inventory_row(
        snapshot_root,
        "b",
        datetime(2026, 1, 6, 1, tzinfo=timezone.utc),
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_manifest_row_count=1,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_manifest_row_count"]
    assert report["bounds"]["resume_cursor"]["line_number"] == 1
    assert report["summary"]["candidate_row_count"] == 1
    assert report["reachability"]["status"] == "BOUNDED_PARTIAL_INVENTORY_ONLY"
    assert report["deletion_enabled"] is False


def test_inventory_payload_read_bound_stops_before_touching_legacy_blob(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    row = _write_legacy_inventory_row(
        snapshot_root,
        "a",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    blob = Path(row["raw_payload_path"])
    before = blob.read_bytes()

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_payload_bytes_read=1,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_payload_bytes_read"]
    assert report["summary"]["candidate_row_count"] == 0
    assert report["bounds"]["observed"]["payload_bytes_read_estimate"] == 0
    assert blob.read_bytes() == before
    assert not (tmp_path / "shared").exists()


def test_inventory_month_filter_reads_only_selected_month(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    _write_legacy_inventory_row(
        snapshot_root,
        "jan",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    _write_legacy_inventory_row(
        snapshot_root,
        "feb",
        datetime(2026, 2, 5, 1, tzinfo=timezone.utc),
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        month="2026-02",
    )

    assert report["month_filter"] == "2026-02"
    assert report["bounds"]["status"] == "COMPLETE"
    assert report["summary"]["candidate_row_count"] == 1
    assert report["summary"]["filtered_relevant_row_count"] == 1
    assert [row["month"] for row in report["legacy_duplicate_bytes_by_month"]] == [
        "2026-02"
    ]


def test_inventory_rejects_invalid_month_without_scanning(tmp_path):
    with pytest.raises(ValueError, match="YYYY-MM"):
        build_migration_dry_run(
            snapshot_root=tmp_path / "snapshots",
            shared_cas_root=tmp_path / "shared",
            month="2026-13",
        )


def test_inventory_blocks_legacy_payload_outside_snapshot_root_without_reading_it(
    tmp_path,
):
    snapshot_root = tmp_path / "snapshots"
    row = _write_legacy_inventory_row(
        snapshot_root,
        "event",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    manifest = snapshot_root / "event" / "forecast_payloads.jsonl"
    outside = tmp_path / "outside" / "payload.json"
    outside.parent.mkdir(parents=True)
    shutil.copy2(Path(row["raw_payload_path"]), outside)
    row["raw_payload_path"] = str(outside)
    manifest.write_text(json.dumps(row) + "\n", encoding="utf-8")

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert report["summary"]["blocked_candidate_row_count"] == 1
    assert report["bounds"]["observed"]["payload_bytes_read"] == 0
    assert "legacy_path_outside_snapshot_root" in report["candidates"][0][
        "issues"
    ][0]


def test_inventory_counts_repeated_manifest_references_as_one_physical_legacy_blob(
    tmp_path,
):
    snapshot_root = tmp_path / "snapshots"
    row = _write_legacy_inventory_row(
        snapshot_root,
        "event",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    manifest = snapshot_root / "event" / "forecast_payloads.jsonl"
    first = dict(row, snapshot_id="s-jan", captured_at_utc="2026-01-05T01:00:00Z")
    second = dict(row, snapshot_id="s-feb", captured_at_utc="2026-02-05T01:00:00Z")
    manifest.write_text(
        json.dumps(first) + "\n" + json.dumps(second) + "\n",
        encoding="utf-8",
    )
    physical_bytes = Path(row["raw_payload_path"]).stat().st_size

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert report["summary"]["verified_candidate_row_count"] == 2
    assert report["summary"]["unique_legacy_physical_blob_count"] == 1
    assert report["summary"]["verified_legacy_stored_bytes"] == physical_bytes
    assert sum(
        item["verified_legacy_stored_bytes"]
        for item in report["legacy_duplicate_bytes_by_month"]
    ) == physical_bytes


def test_inventory_jsonl_line_bound_truncates_before_parsing_oversized_record(
    tmp_path,
):
    snapshot_root = tmp_path / "snapshots"
    event = snapshot_root / "event"
    event.mkdir(parents=True)
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps({"padding": "x" * 256}) + "\n",
        encoding="utf-8",
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_jsonl_line_bytes=32,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_jsonl_line_bytes"]
    assert report["bounds"]["resume_cursor"]["line_number"] == 1
    assert report["bounds"]["observed"]["manifest_bytes_read"] == 32
    assert report["summary"]["scanned_manifest_row_count"] == 0


def test_inventory_deadline_applies_even_when_tree_contains_no_matching_files(
    tmp_path,
):
    snapshot_root = tmp_path / "snapshots"
    (snapshot_root / "a" / "b").mkdir(parents=True)
    ticks = 0.0

    def advancing_monotonic():
        nonlocal ticks
        ticks += 0.5
        return ticks

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_elapsed_seconds=2.25,
        monotonic_fn=advancing_monotonic,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_elapsed_seconds"]
    assert report["summary"]["manifest_count"] == 0
    assert report["bounds"]["resume_cursor"]["tree_entry_path"]


def test_inventory_single_payload_bound_stops_before_read(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    row = _write_legacy_inventory_row(
        snapshot_root,
        "event",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_single_payload_bytes=Path(row["raw_payload_path"]).stat().st_size - 1,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_single_payload_bytes"]
    assert report["bounds"]["observed"]["payload_bytes_read"] == 0
    assert report["summary"]["candidate_row_count"] == 0


@pytest.mark.parametrize("trailing_newline", [True, False])
def test_inventory_manifest_byte_bound_accepts_exact_eof(
    tmp_path,
    trailing_newline,
):
    snapshot_root = tmp_path / "snapshots"
    event = snapshot_root / "event"
    event.mkdir(parents=True)
    text = json.dumps({"source": "irrelevant"})
    encoded = (text + ("\n" if trailing_newline else "")).encode("utf-8")
    (event / "forecast_payloads.jsonl").write_bytes(encoded)

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_manifest_bytes_read=len(encoded),
    )

    assert report["bounds"]["status"] == "COMPLETE"
    assert report["bounds"]["observed"]["manifest_bytes_read"] == len(encoded)
    assert report["summary"]["scanned_manifest_row_count"] == 1


def test_inventory_terminal_clock_crossing_is_reported_as_partial(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    ticks = 0.0

    def advancing_monotonic():
        nonlocal ticks
        ticks += 0.25
        return ticks

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
        max_elapsed_seconds=1.75,
        monotonic_fn=advancing_monotonic,
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["max_elapsed_seconds"]
    assert report["bounds"]["resume_cursor"] == {"phase": "finalize"}
    assert report["bounds"]["observed"]["elapsed_seconds"] == 1.75


def test_inventory_blocks_all_rows_when_one_physical_identity_changes(
    tmp_path,
    monkeypatch,
):
    snapshot_root = tmp_path / "snapshots"
    first = _write_legacy_inventory_row(
        snapshot_root,
        "first",
        datetime(2026, 1, 5, 1, tzinfo=timezone.utc),
    )
    second = _write_legacy_inventory_row(
        snapshot_root,
        "second",
        datetime(2026, 1, 6, 1, tzinfo=timezone.utc),
    )
    second_blob = Path(second["raw_payload_path"])
    wrapper = json.loads(second_blob.read_text(encoding="utf-8"))
    wrapper["source_url"] = "https://example.test/different-wrapper"
    canonical = json.dumps(
        wrapper,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    second_blob.write_bytes(canonical + b"\n")
    second["payload_hash"] = hashlib.sha256(canonical).hexdigest()
    second["payload_bytes"] = len(canonical)
    (snapshot_root / "second" / "forecast_payloads.jsonl").write_text(
        json.dumps(second) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "weather.operations.forecast_payload_cas_migration._legacy_physical_blob_key",
        lambda _path, _stat: "simulated-reused-identity",
    )

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert first["payload_hash"] != second["payload_hash"]
    assert report["summary"]["verified_candidate_row_count"] == 0
    assert report["summary"]["blocked_candidate_row_count"] == 2
    assert report["summary"]["inconsistent_legacy_physical_blob_count"] == 1
    assert report["summary"]["verified_legacy_stored_bytes"] == 0
    assert all(
        "legacy_physical_identity_changed_during_inventory" in item["issues"]
        for item in report["candidates"]
    )


def test_inventory_ignores_invalid_physical_blob_digest_names(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    junk = tmp_path / "shared" / "sha256" / "zz" / f"{'z' * 64}.blob"
    junk.parent.mkdir(parents=True)
    junk.write_bytes(b"junk")

    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert report["summary"]["physical_shared_blob_count"] == 0
    assert report["bounds"]["observed"]["invalid_physical_blob_name_count"] == 1
    assert report["reachability"][
        "unreferenced_within_scanned_scope_observations"
    ] == []


def test_inventory_reports_tree_scan_errors_as_partial(tmp_path, monkeypatch):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()

    def denied(_path):
        raise PermissionError("denied for test")

    monkeypatch.setattr(
        "weather.operations.forecast_payload_cas_migration.os.scandir",
        denied,
    )
    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == ["tree_scan_error"]
    assert report["bounds"]["resume_cursor"]["error_type"] == "PermissionError"


def test_inventory_reports_disappearing_tree_entry_as_partial(tmp_path, monkeypatch):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()

    class DisappearedEntry:
        name = "forecast_payloads.jsonl"
        path = str(snapshot_root / name)

        @staticmethod
        def stat(*, follow_symlinks):
            assert follow_symlinks is False
            raise FileNotFoundError("disappeared for test")

    class EntryContext:
        def __enter__(self):
            return iter([DisappearedEntry()])

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        "weather.operations.forecast_payload_cas_migration.os.scandir",
        lambda _path: EntryContext(),
    )
    report = build_migration_dry_run(
        snapshot_root=snapshot_root,
        shared_cas_root=tmp_path / "shared",
    )

    assert report["bounds"]["status"] == "TRUNCATED"
    assert report["bounds"]["stop_reasons"] == [
        "tree_changed_during_inventory"
    ]
    assert report["bounds"]["resume_cursor"]["tree_entry_path"].endswith(
        "forecast_payloads.jsonl"
    )


def test_migration_cli_wires_all_inventory_bounds(tmp_path):
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir()
    json_out = tmp_path / "report.json"
    markdown_out = tmp_path / "report.md"

    assert migration_main([
        "--snapshot-root", str(snapshot_root),
        "--shared-cas-root", str(tmp_path / "shared"),
        "--json-out", str(json_out),
        "--report-out", str(markdown_out),
        "--max-directories", "10",
        "--max-tree-entries", "20",
        "--max-jsonl-line-bytes", "64",
        "--max-manifest-bytes-read", "128",
        "--max-single-payload-bytes", "256",
    ]) == 0

    configured = json.loads(json_out.read_text(encoding="utf-8"))["bounds"][
        "configured"
    ]
    assert configured["max_directory_count"] == 10
    assert configured["max_tree_entry_count"] == 20
    assert configured["max_jsonl_line_bytes"] == 64
    assert configured["max_manifest_bytes_read"] == 128
    assert configured["max_single_payload_bytes"] == 256
    assert markdown_out.exists()


def test_migration_cli_returns_nonzero_and_exposes_partial_bounds(tmp_path, capsys):
    snapshot_root = tmp_path / "snapshots"
    event = snapshot_root / "event"
    event.mkdir(parents=True)
    (event / "forecast_payloads.jsonl").write_text(
        json.dumps({"padding": "x" * 100}) + "\n",
        encoding="utf-8",
    )
    json_out = tmp_path / "report.json"

    returncode = migration_main([
        "--snapshot-root", str(snapshot_root),
        "--shared-cas-root", str(tmp_path / "shared"),
        "--json-out", str(json_out),
        "--report-out", str(tmp_path / "report.md"),
        "--max-jsonl-line-bytes", "16",
    ])

    terminal = json.loads(capsys.readouterr().out)
    assert returncode == 2
    assert terminal["status"] == "partial"
    assert terminal["bounds_status"] == "TRUNCATED"
    assert terminal["stop_reasons"] == ["max_jsonl_line_bytes"]
    assert json.loads(json_out.read_text(encoding="utf-8"))["bounds"][
        "status"
    ] == "TRUNCATED"
