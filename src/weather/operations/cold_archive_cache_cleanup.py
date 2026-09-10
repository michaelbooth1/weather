"""Exact, journaled cleanup of fully published restore-cache payloads.

Callers must own the host workload lease through completion. Originals, cloud
objects, location markers, claims and all verification receipts are retained.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import production_cold_archive_stage as archive
from weather.operations.cold_archive_native_removal import ExactNtfsRemoval
from weather.schema_registry import schema_version


def _removal_pin(path):
    return ExactNtfsRemoval(path)


def clear_cache(*, entry_path, entry_sha256, cache_id, cache_sha256, attempt_id,
                admission, deadline_monotonic):
    """Remove only unchanged verified members from one published cache.

    Every member is exclusively pinned and rehashed before any removal. A
    partial failure leaves its immutable intent and per-file results for
    explicit reconciliation; neither retries nor directory removal are implied.
    """
    catalog._guard(admission, deadline_monotonic)
    locations.archive_id(cache_id)
    locations.archive_id(attempt_id)
    with ExitStack() as stack:
        stack.enter_context(bridge._file_pin(locations.safe_path(entry_path)))
        entry, digest, _ = catalog._entry(entry_path, entry_sha256)
        root = catalog._local_catalog_root(entry_path, entry)
        cache_path = Path(entry_path).parent / "caches" / (cache_id + ".json")
        stack.enter_context(bridge._file_pin(locations.safe_path(cache_path)))
        cache, cache_digest = locations.read_record(cache_path, cache_sha256)
        catalog._require(cache.get("schema_version") == schema_version("cold_archive_cache")
                         and cache.get("status") == "PASS" and cache.get("entry_sha256") == digest
                         and cache.get("cache_id") == cache_id and cache.get("cleanup_eligible") is False,
                         "cleanup requires the exact published cache")
        members = cache.get("files")
        catalog._require(isinstance(members, list) and len(members) == len(entry["files"]),
                         "cleanup cache inventory mismatch")
        managed = root / "cold_archive" / "restore_cache" / cache_id
        stack.enter_context(archive._directory_pin(locations.safe_path(managed, directory=True)))
        claim_path = managed / "claim.json"
        stack.enter_context(bridge._file_pin(locations.safe_path(claim_path)))
        claim, _ = locations.read_record(claim_path)
        catalog._require(claim.get("status") == "CLAIMED" and claim.get("cache_id") == cache_id
                         and claim.get("entry_sha256") == digest
                         and claim.get("schema_version") == schema_version("cold_archive_cache"),
                         "cleanup cache claim mismatch")
        guard = archive._Guard(admission, deadline_monotonic, 16 * archive.MIB)
        held, planned = [], []
        for member, original in zip(members, entry["files"]):
            expected = (managed / "members").joinpath(*locations.relative_path(original["path"]).parts)
            relative = locations.relative_path(member.get("cache_path"))
            path = root.joinpath(*relative.parts)
            catalog._require(path == expected and member.get("source_path") == original["path"]
                             and member.get("sha256") == original["sha256"],
                             "cleanup member escaped the exact managed cache")
            locations.safe_path(path)
            # Stat before the exclusive handle; opening that handle freezes this identity.
            identity = locations.file_identity(path)
            catalog._require(identity == member.get("identity") and identity["bytes"] == original["size_bytes"],
                             "cleanup cache member identity changed")
            pin = stack.enter_context(_removal_pin(path))
            native = pin.metadata()
            catalog._require(native["size_bytes"] == identity["bytes"]
                             and native["mtime_ns"] == identity["mtime_ns"]
                             and native["device"] == identity["device"]
                             and native["file_id"] == identity["inode"],
                             "cleanup native file identity differs")
            catalog._require(pin.digest(guard=guard) == original["sha256"],
                             "cleanup cache member content changed")
            held.append(pin)
            planned.append({"cache_path": relative.as_posix(), "source_path": original["path"],
                            "sha256": original["sha256"], **native})
        parent = catalog._mkdir(Path(entry_path).parent / "cache_cleanup")
        stack.enter_context(archive._directory_pin(parent))
        attempt = parent / attempt_id
        attempt.mkdir()  # Create-only: failed and successful attempts are never reused.
        stack.enter_context(archive._directory_pin(attempt))
        base = {"schema_version": schema_version("cold_archive_cache_cleanup"),
                "archive_id": entry["archive_id"], "entry_sha256": digest,
                "cache_id": cache_id, "cache_sha256": cache_digest, "attempt_id": attempt_id,
                "originals_deleted": 0, "remote_objects_deleted": 0,
                "created_at_utc": datetime.now(timezone.utc).isoformat()}
        guard.admit()
        catalog._write_record(attempt / "intent.json", {**base, "status": "INTENT", "files": planned})
        removed = []
        for index, (pin, row) in enumerate(zip(held, planned)):
            guard.admit()
            pin.remove()
            result = {**base, "status": "DELETED", "file": row}
            catalog._write_record(attempt / (f"file-{index:05d}.json"), result)
            removed.append(row)
        result, receipt_sha = catalog._write_record(attempt / "receipt.json", {
            **base, "status": "PASS", "files": removed, "deleted_files": len(removed),
            "removed_logical_bytes": sum(row["size_bytes"] for row in removed),
            "removed_allocated_bytes": sum(row["allocated_bytes"] for row in removed)})
        return {**result, "receipt_path": str(attempt / "receipt.json"), "receipt_sha256": receipt_sha}
