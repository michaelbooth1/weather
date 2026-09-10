"""Catalog, full-restore bindings, bounded cache and cleanup on synthetic files."""
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import gzip
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import production_cold_archive_stage as archive
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.schema_registry import schema_version


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, field="receipt_hash"):
    value = dict(value)
    value.pop(field, None)
    archive._write(path, archive._seal(value, field))
    return sha(path)


def metadata(path):
    info = Path(path).stat()
    return {"size_bytes": info.st_size, "mtime_ns": info.st_mtime_ns,
            "device": info.st_dev, "file_id": info.st_ino, "allocated_bytes": info.st_size}


class FixturePin:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def metadata(self):
        return metadata(self.path)


@pytest.fixture
def corpus(tmp_path, monkeypatch, request):
    monkeypatch.setattr(archive, "_source_pin", FixturePin)
    monkeypatch.setattr(bridge, "_file_pin", FixturePin)
    monkeypatch.setattr(archive, "_directory_pin", lambda path: nullcontext())
    root = tmp_path / "data"
    day = root / "snapshots" / "highest-temperature-in-toronto-on-june-15-2026"
    day.mkdir(parents=True)
    contents = getattr(request, "param", {"order_books_long.csv": b"a,b\n" + b"1,2\n" * 8,
                "order_books_long.csv.gz": gzip.compress(b"a,b\n" + b"1,2\n" * 8)})
    for name, content in contents.items():
        (day / name).write_bytes(content)
    rows = [{"path": path.relative_to(root).as_posix(), **metadata(path)}
            for path in sorted(day.iterdir())]
    selection = {"schema_version": schema_version("large_archive_candidate_selection"),
                 "status": "MEASURED_CANDIDATE_NOT_DELETE_AUTHORITY", "source_root": str(root),
                 "files": rows, "file_count": len(rows),
                 "logical_bytes": sum(row["size_bytes"] for row in rows),
                 "allocated_bytes": sum(row["allocated_bytes"] for row in rows)}
    selection_path, plan_path = tmp_path / "selection.json", tmp_path / "plan.json"
    selection_path.write_text(json.dumps(selection))
    archive.plan_selection(selection_path, sha(selection_path), plan_path,
                           chunk_grouping=archive.SELECTIVE_GROUPING)
    admission = lambda: True
    deadline = time.monotonic() + 30
    archive.stage_chunk(plan_path, sha(plan_path), "chunk-00000", tmp_path / "stage",
                        source_root=root, admission=admission, deadline_monotonic=deadline,
                        free_space_reserve_bytes=0)
    manifest_path, stage_path = tmp_path / "stage/manifest.json", tmp_path / "stage/receipt.json"
    manifest = json.loads(manifest_path.read_text())
    archive_id = "catalog-fixture-a1"
    crypt_path, upload_path = tmp_path / "crypt.json", tmp_path / "upload.json"
    tool = {"tool": bridge.TOOL, "module_sha256": "1" * 64, "module_bytes": 1,
            "git_commit": "2" * 40, "git_tree": "3" * 40, "git_branch": "fixture",
            "git_dirty": False, "python": "3.12"}
    cipher = {"bytes": 128, "sha256": "a" * 64,
              "path_relative_to_ciphertext_root": "directory/object",
              "file_identity": {"device": 1, "inode": 2, "mode": 0o100000, "bytes": 128, "mtime_ns": 3}}
    bound = {"archive_id": archive_id, "chunk_id": "chunk-00000", "plan_sha256": sha(plan_path),
             "production_manifest_sha256": sha(manifest_path), "production_receipt_sha256": sha(stage_path)}
    crypt = {"schema_version": schema_version("production_cold_archive_crypt_receipt"),
             "status": "PASS", **bound, **bridge.RETENTION,
             "archive_bytes": manifest["archive_bytes"], "archive_sha256": manifest["archive_sha256"],
             "checks": dict.fromkeys(bridge.ENCRYPT_CHECKS, "PASS"), "ciphertext": cipher,
             "tool_identity": tool}
    crypt_sha = save(crypt_path, crypt)
    bound.update(crypt_receipt_sha256=crypt_sha)
    folder = "fixture_private_folder_1234"

    def remote(kind, suffix, path=None):
        return {"kind": kind, "object_id": "fixture_object_" + kind,
                "remote_key": archive_id + suffix, "bytes": path.stat().st_size if path else 128,
                "hashes": {}, "sha256": sha(path) if path else cipher["sha256"]}

    encrypted_object = remote("ciphertext", ".rclone.bin")
    encrypted_object.pop("kind")
    uploaded = {
        "schema_version": schema_version("production_cold_archive_upload_receipt"),
        "status": "PASS", "phase": "upload_only", **bound,
        "ciphertext": {key: cipher[key] for key in ("bytes", "sha256")},
        "source_retained": True, "cleanup_eligible": False, "deletion_authorized": False,
        "deleted_files": 0, "reclaimed_bytes": 0, "upload_performed": True,
        "independent_download": False, "remote_side_effect_possible": True,
        "drive": {"root_folder_id": folder, **encrypted_object},
        "metadata_objects": [remote("production_manifest", ".manifest.json", manifest_path),
                             remote("production_receipt", ".stage.json", stage_path),
                             remote("crypt_receipt", ".crypt.json", crypt_path)],
        "completed_at_utc": datetime.now(timezone.utc).isoformat()}
    upload_sha = save(upload_path, uploaded)
    args = dict(source_root=root, production_manifest=manifest_path,
                production_manifest_sha256=sha(manifest_path), production_receipt=stage_path,
                production_receipt_sha256=sha(stage_path), crypt_receipt=crypt_path,
                crypt_receipt_sha256=crypt_sha, upload_receipt=upload_path, upload_receipt_sha256=upload_sha,
                admission=admission, deadline_monotonic=deadline)
    return SimpleNamespace(root=root, day=day, tmp=tmp_path, contents=contents, manifest=manifest,
                           uploaded=uploaded, args=args, cipher=cipher, bound=bound, tool=tool)


def register(corpus):
    result = catalog.publish_upload(**corpus.args)
    corpus.entry_path = Path(result["entry_path"])
    corpus.entry_sha = result["entry_sha256"]
    return result


def recovery(corpus):
    register(corpus)
    uploaded = corpus.uploaded
    transport = {"schema_version": schema_version("production_cold_archive_transport_receipt"),
                 "status": "PASS", "phase": "download_and_verify", **corpus.bound,
                 "source_retained": True, "cleanup_eligible": False, "deletion_authorized": False,
                 "upload_receipt_sha256": corpus.args["upload_receipt_sha256"],
                 "independent_download": True, "upload_performed": False,
                 "ciphertext": uploaded["ciphertext"],
                 "drive": {key: uploaded["drive"][key] for key in ("root_folder_id", "object_id", "remote_key")},
                 "metadata_objects": [{**row, "downloaded_path": "C:/fixture/" + row["remote_key"]}
                                      for row in uploaded["metadata_objects"]]}
    transport_path, restore_path = corpus.tmp / "transport.json", corpus.tmp / "restore.json"
    transport_sha = save(transport_path, transport)
    restored = {"schema_version": schema_version("production_cold_archive_restore_receipt"),
                "status": "PASS", **corpus.bound, **bridge.RETENTION, "tool_identity": corpus.tool,
                "checks": dict.fromkeys(bridge.RESTORE_CHECKS, "PASS"), "restore_performed": True,
                "verified_file_count": len(corpus.contents), "transport_receipt_sha256": transport_sha,
                "ciphertext": corpus.cipher, "drive": transport["drive"],
                "restored_members": [{"path": row["path"], "bytes": row["size_bytes"], "sha256": row["sha256"]}
                                     for row in corpus.manifest["files"]]}
    restore_sha = save(restore_path, restored)
    return dict(entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
                transport_receipt=transport_path, transport_receipt_sha256=transport_sha,
                restore_receipt=restore_path, restore_receipt_sha256=restore_sha,
                admission=lambda: True, deadline_monotonic=time.monotonic() + 30)


def cached(corpus, **changes):
    restored = catalog.publish_restore(**recovery(corpus))
    members = corpus.tmp / "restored-members"
    for row in corpus.manifest["files"]:
        path = members / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(corpus.contents[Path(row["path"]).name])
    args = dict(entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
                restore_record=Path(restored["record_path"]), restore_record_sha256=restored["record_sha256"],
                restored_members_root=members, cache_id="cache-fixture-a1", admission=lambda: True,
                deadline_monotonic=time.monotonic() + 30, free_space_reserve_bytes=0)
    args.update(changes)
    return args




def test_shared_csv_reader_uses_verified_cache_and_keeps_logical_identity(corpus):
    from weather.io import read_csv_rows_with_diagnostics
    original = corpus.day / "order_books_long.csv"
    catalog.publish_cache(**cached(corpus))
    original.unlink()
    rows, diagnostics = read_csv_rows_with_diagnostics(original)
    assert len(rows) == 8
    assert rows[0] == {"a": "1", "b": "2"}
    assert diagnostics["path"] == str(original)


def test_missing_archived_csv_is_not_silently_empty(corpus):
    from weather.io import iter_csv_rows, read_csv_rows_with_diagnostics
    register(corpus)
    original = corpus.day / "order_books_long.csv"
    original.unlink()
    with pytest.raises(locations.ArchivedInputRequired):
        read_csv_rows_with_diagnostics(original)
    with pytest.raises(locations.ArchivedInputRequired):
        list(iter_csv_rows(original))


def test_housekeeping_preserves_manifest_and_complete_parquet(corpus):
    import pandas as pd
    from weather.operations import closed_market_day_archive as closed
    from weather.operations import event_day_manifest as events
    original = corpus.day / "order_books_long.csv"
    snapshots = corpus.root / "snapshots"
    manifest = events.build_event_day_manifest(corpus.day, snapshots_root=snapshots)
    events._atomic_write_json(events.event_day_manifest_path(corpus.day), manifest)
    original_manifest_bytes = events.event_day_manifest_path(corpus.day).read_bytes()
    archive_root = corpus.tmp.parent / ("arc-" + hashlib.sha256(str(corpus.tmp).encode()).hexdigest()[:8])
    partition = closed.archive_partition_path("2026-06-15", "toronto", corpus.day.name, root=archive_root)
    parquet = closed.family_dataset_path(partition, "order_books_long")
    parquet.parent.mkdir(parents=True)
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_parquet(parquet)
    before_parquet = parquet.read_bytes()
    archive_manifest = closed.manifest_path_for_partition(partition)
    archive_manifest.write_bytes(b'{"preserved_evidence":true}\n')
    before_archive = archive_manifest.read_bytes()
    signature = closed.incremental_folder_signature(corpus.day, snapshots_root=snapshots,
                                                     as_of_date="2026-09-09")
    register(corpus)
    original.unlink()
    changed = closed.incremental_folder_signature(corpus.day, snapshots_root=snapshots,
                                                   as_of_date="2026-09-09")
    assert changed["signature_hash"] != signature["signature_hash"]
    assert changed == closed.incremental_folder_signature(corpus.day, snapshots_root=snapshots,
                                                           as_of_date="2026-09-09")
    plan = closed.plan_market_day(corpus.day, snapshots_root=snapshots, archive_root=archive_root,
                                  as_of_date="2026-09-09")
    assert plan["action"] == "preserve_archived_sources"
    applied = closed.apply_market_day(plan, snapshots_root=snapshots, archive_root=archive_root)
    assert applied["status"] == "skipped"
    result = events.build_backfill_payload(snapshots_root=snapshots, mode="apply", incremental=True)
    assert result["summary"]["written_count"] == 0
    assert result["summary"]["archived_preserved_count"] == 1
    assert result["market_days"][0]["action"] == "preserve_original_manifest"
    assert events.event_day_manifest_path(corpus.day).read_bytes() == original_manifest_bytes
    assert parquet.read_bytes() == before_parquet
    assert len(pd.read_parquet(parquet)) == 3
    assert archive_manifest.read_bytes() == before_archive
    strict = events.validate_event_day_manifest(manifest, corpus.day, snapshots_root=snapshots)
    assert strict["status"] == "BLOCK"
    assert any(row["check"] == "archived_restore_required" for row in strict["checks"])
    with pytest.raises(locations.ArchivedInputRequired):
        closed._read_source_frame(original)
    assert original in closed._find_paths(corpus.day, ("order_books_long.csv",))


def test_verified_cache_preserves_event_manifest_original_mtime_and_classification(corpus):
    from weather.operations import event_day_manifest as events
    original = corpus.day / "order_books_long.csv"
    snapshots = corpus.root / "snapshots"
    before = events._file_record(original, folder=corpus.day, snapshots_root=snapshots)
    catalog.publish_cache(**cached(corpus))
    original.unlink()
    after = events._file_record(original, folder=corpus.day, snapshots_root=snapshots)
    assert after == before
    family = next(row for row in events.EVENT_DAY_ARTIFACT_FAMILIES
                  if events._matches_family(original, row))
    assert original in events._iter_family_files(corpus.day, family)


@pytest.mark.parametrize("corpus", [{
    "order_books.jsonl": b'{"original":"canonical"}\n',
    "order_books.jsonl.gz": gzip.compress(b'{"original":"canonical"}\n'),
}], indirect=True)
def test_full_book_reader_can_use_retained_canonical_gzip_but_not_partial_csv(corpus):
    from weather.market.order_book_tape import resolve_full_book_representation
    register(corpus)
    (corpus.day / "order_books.jsonl").unlink()
    result = resolve_full_book_representation(corpus.day)
    assert result.canonical and result.representation == "raw_jsonl_gzip"
    (corpus.day / "order_books.jsonl.gz").unlink()
    (corpus.day / "order_books_long.csv").write_bytes(b"partial,projection\n")
    with pytest.raises(locations.ArchivedInputRequired):
        resolve_full_book_representation(corpus.day)


@pytest.mark.parametrize("corpus", [{"variant_predictions.jsonl": b'{"value":1}\n'}], indirect=True)
def test_archived_jsonl_reader_requires_cache(corpus):
    from weather.io import read_jsonl, read_jsonl_tail_with_diagnostics
    catalog.publish_cache(**cached(corpus))
    original = corpus.day / "variant_predictions.jsonl"
    original.unlink()
    assert read_jsonl(original) == [{"value": 1}]
    assert read_jsonl_tail_with_diagnostics(original, max_bytes=1024)[0] == [{"value": 1}]




def test_archived_audit_inputs_have_locations_and_restore_commands(corpus):
    from weather.reporting.data_quality import clob_coverage_audit as coverage
    register(corpus)
    for name in corpus.contents:
        (corpus.day / name).unlink()
    info = coverage.file_info(corpus.day, tuple(corpus.contents))
    assert all(row["exists"] is False and row["bytes"] == 0 for row in info)
    assert all(row["archive_id"] == "catalog-fixture-a1" for row in info)
    assert all(row["archived_bytes"] > 0 for row in info)
    result = coverage.audit_folder(corpus.day)
    assert len(result["archived_inputs"]) == 2


@pytest.mark.parametrize("corpus", [{"snapshot_explanations_long.csv": b"a,b\n1,2\n"}], indirect=True)
def test_archived_explanations_are_restored_instead_of_backfilled(corpus):
    from weather.reporting.data_quality import data_layer_audit_collectors as audit
    register(corpus)
    (corpus.day / "snapshot_explanations_long.csv").unlink()
    location = locations.archived_inputs(corpus.day)[0]
    row = {"folder": str(corpus.day), "artifact_presence": {
        "snapshots_jsonl": True, "snapshot_explanations": False},
        "artifact_locations": {"snapshot_explanations": location}}
    eligibility = audit.sidecar_eligibility_for_folder(row, settled_scope_ready=True)
    assert eligibility["labels"]["explanation_ready"] is False
    assert eligibility["restore_commands"][0]["archive_id"] == "catalog-fixture-a1"
    assert "cold_archive_catalog locate" in eligibility["restore_commands"][0]["command"]
    assert not any(command["artifact"] == "snapshot_explanations"
                   for command in eligibility["backfill_commands"])




def test_location_repair_completes_an_interrupted_publication_without_changing_sources(corpus):
    register(corpus)
    source = corpus.day / "order_books_long.csv"
    marker = locations.marker_path(source)
    marker.unlink()  # Synthetic interrupted publication: catalog exists, one marker is absent.
    args = dict(entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
                admission=lambda: True, deadline_monotonic=time.monotonic() + 30)
    result = catalog.repair_locations(**args)
    assert result["markers_created"] == 1
    assert locations.load_location(source).entry_sha256 == corpus.entry_sha
    assert source.read_bytes() == corpus.contents[source.name]
    assert catalog.repair_locations(**args)["markers_created"] == 0


def test_location_repair_refuses_a_changed_original(corpus):
    register(corpus)
    source = corpus.day / "order_books_long.csv"
    locations.marker_path(source).unlink()
    source.write_bytes(b"changed")
    with pytest.raises(locations.CatalogIntegrityError, match="unchanged retained"):
        catalog.repair_locations(entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
                                 admission=lambda: True, deadline_monotonic=time.monotonic() + 30)
    assert not locations.marker_path(source).exists()


def test_recovery_export_survives_loss_of_every_original_proof_file(corpus):
    register(corpus)
    for name in ("production_manifest", "production_receipt", "crypt_receipt", "upload_receipt"):
        Path(corpus.args[name]).unlink()
    result = catalog.export_recovery_proofs(
        entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
        output_root=corpus.tmp / "recovered-proofs", admission=lambda: True,
        deadline_monotonic=time.monotonic() + 30)
    for name, proof in result["proof_files"].items():
        assert sha(proof["path"]) == corpus.args[name + "_sha256"]
    assert result["objects"][0]["object_id"] == corpus.uploaded["drive"]["object_id"]
    with pytest.raises(locations.CatalogIntegrityError, match="already exists"):
        catalog.export_recovery_proofs(
            entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
            output_root=corpus.tmp / "recovered-proofs", admission=lambda: True,
            deadline_monotonic=time.monotonic() + 30)


def test_inventory_pointer_updates_and_retains_previous_snapshot(corpus):
    register(corpus)
    first = catalog.write_inventory(source_root=corpus.root, admission=lambda: True,
                                    deadline_monotonic=time.monotonic() + 30)
    first_bytes = Path(first["snapshot_path"]).read_bytes()
    assert b"LOCAL_WITH_CLOUD_COPY" in first_bytes
    (corpus.day / "order_books_long.csv").unlink()
    second = catalog.write_inventory(source_root=corpus.root, admission=lambda: True,
                                     deadline_monotonic=time.monotonic() + 30)
    assert first["snapshot_path"] != second["snapshot_path"]
    assert Path(first["snapshot_path"]).read_bytes() == first_bytes
    assert b"| ARCHIVED |" in Path(second["inventory_path"]).read_bytes()
    assert sha(second["inventory_path"]) == second["sha256"]


def test_upload_job_publishes_exact_locations_and_persistent_inventory(corpus):
    from weather.operations.production_cold_archive_transfer import publish_upload_location
    request = {"publish_catalog": True, "operation": "upload_only"}
    for name in ("production_manifest", "production_receipt", "crypt_receipt"):
        request[name + "_path"] = corpus.args[name]
        request[name + "_sha256"] = corpus.args[name + "_sha256"]
    result = publish_upload_location(
        request, corpus.args["upload_receipt"], corpus.args["upload_receipt_sha256"],
        source_root=corpus.root, admission=lambda: True, deadline_monotonic=time.monotonic() + 30)
    assert result["status"] == "UPLOADED"
    assert Path(result["inventory"]["inventory_path"]).is_file()
    assert all(locations.load_location(corpus.day / name) is not None for name in corpus.contents)




def test_catalog_can_restore_to_a_separate_local_data_layout(corpus):
    args = cached(corpus)
    local_root = corpus.tmp / "recovered-data"
    local_root.mkdir()
    imported = catalog.import_locations(
        entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha, local_source_root=local_root,
        admission=lambda: True, deadline_monotonic=time.monotonic() + 30)
    assert imported["original_source_root"] == str(corpus.root)
    assert sha(imported["entry_path"]) == corpus.entry_sha
    args["entry_path"] = Path(imported["entry_path"])
    catalog.publish_cache(**args)
    for row in corpus.manifest["files"]:
        logical = local_root / row["path"]
        assert not logical.exists()
        restored = locations.resolve_local_path(logical)
        assert restored.is_relative_to(local_root / "cold_archive/restore_cache")
        assert sha(restored) == row["sha256"]
        assert locations.load_location(logical).entry["source_root"] == str(corpus.root)


def test_catalog_import_refuses_to_cover_existing_unverified_local_inputs(corpus):
    register(corpus)
    local_root = corpus.tmp / "recovered-data"
    local_root.mkdir()
    source = local_root / corpus.manifest["files"][0]["path"]
    source.parent.mkdir(parents=True)
    source.write_bytes(b"unverified local bytes")
    with pytest.raises(locations.CatalogIntegrityError, match="must not contain original"):
        catalog.import_locations(
            entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha, local_source_root=local_root,
            admission=lambda: True, deadline_monotonic=time.monotonic() + 30)
    assert source.read_bytes() == b"unverified local bytes"


def test_upload_keeps_all_originals_and_records_exact_remote_locations(corpus):
    result = register(corpus)
    assert result["cleanup_eligible"] is False
    for name, content in corpus.contents.items():
        original = corpus.day / name
        assert original.read_bytes() == content
        location = locations.load_location(original)
        assert location.entry_sha256 == result["entry_sha256"]
        assert location.member["sha256"] == sha(original)
        assert len(location.entry["objects"]) == 4
        for proof in location.entry["proofs"].values():
            assert isinstance(catalog._unpack(proof), dict)
        described = catalog.describe(original)
        assert described["status"] == "LOCAL_WITH_CLOUD_COPY"
        assert described["objects"][0]["object_id"] == corpus.uploaded["drive"]["object_id"]
    markdown = catalog.render_inventory(corpus.root)
    assert "fixture_private_folder_1234" in markdown
    assert all(name in markdown for name in corpus.contents)


def test_archived_source_is_discoverable_and_never_an_empty_missing_file(corpus):
    register(corpus)
    original = corpus.day / "order_books_long.csv"
    original.unlink()
    assert original in locations.registered_sources(corpus.day, "*.csv")
    with pytest.raises(locations.ArchivedInputRequired) as caught:
        locations.resolve_local_path(original)
    assert not isinstance(caught.value, (FileNotFoundError, OSError))
    assert caught.value.archive_id == "catalog-fixture-a1"
    assert catalog.describe(original)["status"] == "ARCHIVED_RESTORE_REQUIRED"
    unknown = corpus.day / "never-recorded.jsonl"
    assert locations.resolve_local_path(unknown) == unknown


def test_complete_restore_and_verified_cache_preserve_both_representations(corpus):
    result = catalog.publish_cache(**cached(corpus))
    assert result["status"] == "PASS" and result["files"] == 2
    originals = [corpus.day / name for name in corpus.contents]
    for original in originals:
        original.unlink()
    resolved = locations.require_local_inputs(originals)
    for original, path in zip(originals, resolved):
        assert path != original
        assert path.read_bytes() == corpus.contents[original.name]
        assert catalog.describe(original)["status"] == "VERIFIED_LOCAL_CACHE"


@pytest.mark.parametrize("kind", ["cipher_object", "metadata_object", "proof_hash", "partial_upload"])
def test_invalid_cloud_proof_cannot_publish_source_markers(corpus, kind):
    value = dict(corpus.uploaded)
    if kind == "cipher_object":
        value["drive"] = {**value["drive"], "object_id": "bad"}
    elif kind == "metadata_object":
        value["metadata_objects"] = value["metadata_objects"][:-1]
    elif kind == "proof_hash":
        corpus.args["production_manifest_sha256"] = "0" * 64
    else:
        value["status"] = "FAIL_CLOSED"
    new_path = corpus.tmp / "changed-upload.json"
    corpus.args.update(upload_receipt=new_path, upload_receipt_sha256=save(new_path, value))
    with pytest.raises((ValueError, locations.CatalogIntegrityError)):
        catalog.publish_upload(**corpus.args)
    assert not (corpus.day / locations.MARKER_DIRECTORY).exists()


@pytest.mark.parametrize("kind", ["changed_source", "lost_source", "admission"])
def test_catalog_rejects_source_drift_or_lost_admission(corpus, kind):
    source = corpus.day / "order_books_long.csv"
    if kind == "changed_source":
        source.write_bytes(b"changed")
    elif kind == "lost_source":
        source.unlink()
    else:
        corpus.args["admission"] = lambda: False
    with pytest.raises((OSError, ValueError, locations.CatalogIntegrityError)):
        catalog.publish_upload(**corpus.args)
    assert not (corpus.day / locations.MARKER_DIRECTORY).exists()


@pytest.mark.parametrize("kind", ["checks", "members", "cloud", "upload_hash"])
def test_recovery_receipt_requires_complete_corresponding_proof(corpus, kind):
    args = recovery(corpus)
    key = "transport_receipt" if kind == "upload_hash" else "restore_receipt"
    value = json.loads(args[key].read_text())
    if kind == "checks":
        value["checks"]["materialized_members"] = "NOT_RUN"
    elif kind == "members":
        value["restored_members"] = value["restored_members"][:-1]
    elif kind == "cloud":
        value["drive"]["object_id"] = "another_object"
    else:
        value["upload_receipt_sha256"] = "0" * 64
    path = corpus.tmp / "changed-recovery.json"
    args[key], args[key + "_sha256"] = path, save(path, value)
    with pytest.raises(locations.CatalogIntegrityError):
        catalog.publish_restore(**args)
    assert not (corpus.entry_path.parent / "restores").exists()


def test_cache_quota_refuses_before_claim(corpus):
    args = cached(corpus, cache_limit_bytes=1)
    with pytest.raises(locations.CatalogIntegrityError, match="quota"):
        catalog.publish_cache(**args)
    assert not (corpus.root / "cold_archive/restore_cache/cache-fixture-a1").exists()
    assert not (corpus.entry_path.parent / "cache.json").exists()


def test_cache_rejects_corrupt_restored_bytes_and_preserves_partial_attempt(corpus):
    args = cached(corpus)
    (args["restored_members_root"] / corpus.manifest["files"][0]["path"]).write_bytes(b"changed")
    with pytest.raises(locations.CatalogIntegrityError, match="size changed"):
        catalog.publish_cache(**args)
    assert (corpus.root / "cold_archive/restore_cache/cache-fixture-a1/claim.json").is_file()
    assert not (corpus.entry_path.parent / "cache.json").exists()


@pytest.mark.parametrize("keep_mtime", [False, True])
def test_cache_change_is_detected_even_after_a_successful_read(corpus, keep_mtime):
    catalog.publish_cache(**cached(corpus))
    original = corpus.day / "order_books_long.csv"
    original.unlink()
    path = locations.resolve_local_path(original)
    before = path.stat()
    path.write_bytes(b"x" * before.st_size)
    if keep_mtime:
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(locations.CatalogIntegrityError):
        locations.resolve_local_path(original)


def test_missing_cache_requests_restore_and_retains_cloud_identity(corpus):
    catalog.publish_cache(**cached(corpus))
    original = corpus.day / "order_books_long.csv"
    original.unlink()
    location = locations.load_location(original)
    locations.cached_path(location).unlink()
    with pytest.raises(locations.ArchivedInputRequired):
        locations.resolve_local_path(original)
    assert locations.load_location(original).entry_sha256 == corpus.entry_sha


@pytest.mark.parametrize("kind", ["wrong_entry_hash", "other_path", "cache_escape"])
def test_location_and_cache_paths_cannot_be_redirected(corpus, kind):
    catalog.publish_cache(**cached(corpus))
    original = corpus.day / "order_books_long.csv"
    original.unlink()
    path = locations.marker_path(original)
    if kind == "cache_escape":
        path = corpus.entry_path.parent / "cache.json"
    value = json.loads(path.read_text())
    if kind == "wrong_entry_hash":
        value["entry_sha256"] = "0" * 64
    elif kind == "other_path":
        value["source_path"] = "snapshots/another-day/order_books_long.csv"
    else:
        value["files"][0]["cache_path"] = "../outside.csv"
    path.unlink()  # Fixture-only hostile replacement of metadata.
    save(path, value)
    with pytest.raises(locations.CatalogIntegrityError):
        locations.resolve_local_path(original)


def test_reused_catalog_publication_never_overwrites_proof(corpus):
    register(corpus)
    before = corpus.entry_path.read_bytes()
    with pytest.raises(locations.CatalogIntegrityError, match="already"):
        catalog.publish_upload(**corpus.args)
    assert corpus.entry_path.read_bytes() == before


def test_duplicate_json_key_is_rejected(tmp_path):
    path = tmp_path / "bad.json"
    path.write_bytes(b'{"a":1,"a":2,"receipt_hash":"bad"}')
    with pytest.raises(locations.CatalogIntegrityError):
        locations.read_record(path)

# Cache cleanup tests deliberately use synthetic members only.
class FixtureRemoval(FixturePin):
    def metadata(self):
        return metadata(self.path)

    def digest(self, *, guard):
        guard.admit()
        return sha(self.path)

    def remove(self):
        self.path.unlink()


def cleanup_args(corpus, monkeypatch, *, native=False):
    from weather.operations import cold_archive_cache_cleanup as cleanup
    if not native:
        monkeypatch.setattr(cleanup, "_removal_pin", FixtureRemoval)
    args = cached(corpus)
    result = catalog.publish_cache(**args)
    return cleanup, dict(entry_path=corpus.entry_path, entry_sha256=corpus.entry_sha,
                         cache_id=args["cache_id"], cache_sha256=result["cache_sha256"],
                         attempt_id="clear-fixture-a1", admission=lambda: True,
                         deadline_monotonic=time.monotonic() + 30)


def test_cache_cleanup_preserves_originals_catalog_and_restore_receipts(corpus, monkeypatch):
    cleanup, args = cleanup_args(corpus, monkeypatch)
    original = corpus.day / "order_books_long.csv"
    expected = locations.cached_path(locations.load_location(original))
    catalog_before = {str(path): sha(path) for path in corpus.entry_path.parent.rglob("*.json")}
    result = cleanup.clear_cache(**args)
    assert result["status"] == "PASS" and result["deleted_files"] == len(corpus.contents)
    assert not expected.exists() and original.read_bytes() == corpus.contents[original.name]
    assert all(sha(Path(path)) == digest for path, digest in catalog_before.items())
    assert locations.cached_path(locations.load_location(original)) is None
    assert Path(result["receipt_path"]).exists()


@pytest.mark.parametrize("fault", ["changed", "missing", "escaped", "wrong_hash", "expired"])
def test_cache_cleanup_refuses_before_removing_any_member(corpus, monkeypatch, fault):
    cleanup, args = cleanup_args(corpus, monkeypatch)
    cache_record = corpus.entry_path.parent / "caches" / (args["cache_id"] + ".json")
    cache = json.loads(cache_record.read_bytes())
    member = corpus.root / cache["files"][-1]["cache_path"]
    first = corpus.root / cache["files"][0]["cache_path"]
    if fault == "changed":
        before = member.stat()
        member.write_bytes(b"x" * before.st_size)
        os.utime(member, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif fault == "missing":
        member.unlink()
    elif fault == "escaped":
        cache["files"][-1]["cache_path"] = cache["files"][-1]["source_path"]
        cache_record.write_bytes(locations.canonical(locations.sealed(cache)) + b"\n")
        args["cache_sha256"] = sha(cache_record)
    elif fault == "wrong_hash":
        args["cache_sha256"] = "0" * 64
    elif fault == "expired":
        args["deadline_monotonic"] = time.monotonic() - 1
    with pytest.raises((locations.CatalogIntegrityError, OSError)):
        cleanup.clear_cache(**args)
    assert first.exists()
    assert not (corpus.entry_path.parent / "cache_cleanup").exists()
    assert all((corpus.day / name).exists() for name in corpus.contents)


def test_cache_cleanup_partial_failure_keeps_intent_and_completed_file_receipt(corpus, monkeypatch):
    cleanup, args = cleanup_args(corpus, monkeypatch)

    class InterruptedRemoval(FixtureRemoval):
        calls = 0
        def remove(self):
            type(self).calls += 1
            if self.calls == 2:
                raise OSError("synthetic interruption")
            super().remove()

    monkeypatch.setattr(cleanup, "_removal_pin", InterruptedRemoval)
    with pytest.raises(OSError, match="synthetic interruption"):
        cleanup.clear_cache(**args)
    attempt = corpus.entry_path.parent / "cache_cleanup" / args["attempt_id"]
    assert (attempt / "intent.json").exists()
    assert (attempt / "file-00000.json").exists()
    assert not (attempt / "receipt.json").exists()
    assert all((corpus.day / name).exists() for name in corpus.contents)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS removal requires Windows")
def test_native_cache_cleanup_removes_only_verified_cache_members(corpus, monkeypatch):
    cleanup, args = cleanup_args(corpus, monkeypatch, native=True)
    result = cleanup.clear_cache(**args)
    assert result["status"] == "PASS" and result["deleted_files"] == len(corpus.contents)
    assert all((corpus.day / name).exists() for name in corpus.contents)


@pytest.mark.skipif(os.name != "nt", reason="native NTFS sharing requires Windows")
def test_native_cache_cleanup_refuses_an_open_reader_before_any_removal(corpus, monkeypatch):
    cleanup, args = cleanup_args(corpus, monkeypatch, native=True)
    cache, _ = locations.read_record(corpus.entry_path.parent / "caches" / (args["cache_id"] + ".json"))
    paths = [corpus.root / row["cache_path"] for row in cache["files"]]
    with paths[-1].open("rb") as reader:
        with pytest.raises(OSError):
            cleanup.clear_cache(**args)
        assert reader.read(1)
    assert all(path.exists() for path in paths)
    assert not (corpus.entry_path.parent / "cache_cleanup").exists()


@pytest.mark.skipif(os.name != "nt", reason="native NTFS removal requires Windows")
def test_native_removal_rejects_hardlinks_and_ancestor_replacement(tmp_path):
    from weather.operations.cold_archive_native_removal import ExactNtfsRemoval
    source = tmp_path / "member"
    source.write_bytes(b"synthetic file")
    linked = tmp_path / "hardlink"
    os.link(source, linked)
    with pytest.raises((ValueError, OSError)):
        with ExactNtfsRemoval(source):
            pytest.fail("hardlinked source was admitted")
    linked.unlink()
    with ExactNtfsRemoval(source) as pin:
        guard = archive._Guard(lambda: True, time.monotonic() + 10, 16 * archive.MIB)
        assert pin.digest(guard=guard) == hashlib.sha256(b"synthetic file").hexdigest()
        with pytest.raises(OSError):
            source.parent.rename(source.parent.with_name(source.parent.name + "-moved"))
    assert source.exists()
