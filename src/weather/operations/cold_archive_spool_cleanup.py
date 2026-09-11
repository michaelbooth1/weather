"""Exact temporary archive payload cleanup after independent recovery proof.

This helper owns no deletion authority. The original-reclaim executor supplies
its reviewed approval, custody, native pins and shared workload lease. Recovery
metadata, source data and remote objects are never selected here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from weather import cold_archive_locations as locations
from weather.operations import cold_archive_catalog as catalog
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import production_cold_archive_stage as archive
from weather.operations.cold_archive_native_removal import ExactNtfsRemoval
from weather.schema_registry import schema_version

ROLES = ("staged_archive", "upload_ciphertext", "downloaded_ciphertext")


def _require(condition, message):
    locations._require(condition, message)


class _SpoolRemoval(ExactNtfsRemoval):
    def metadata(self):
        # Temporary ciphertext includes bounded compression/encryption overhead.
        return bridge._Pin.metadata(self)


def _removal_pin(path):
    return _SpoolRemoval(path)


def prepare_spool(inventory, *, entry, entry_sha256, restore_record, production_root, stack, guard):
    """Pin every reviewed local payload and prove its exact recovery bindings."""
    _require(inventory.get("schema_version") == schema_version("cold_archive_spool_inventory")
             and inventory.get("archive_id") == entry["archive_id"]
             and inventory.get("entry_sha256") == entry_sha256,
             "temporary inventory belongs to a different archive")
    docs, _, _ = catalog._validated_upload(entry["proofs"], Path(entry["source_root"]))
    manifest, receipt = docs["production_manifest"], docs["production_receipt"]
    transport = catalog._unpack(restore_record["transport"])
    downloaded = transport.get("downloaded_file")
    _require(isinstance(downloaded, dict)
             and downloaded.get("sha256") == entry["ciphertext"]["sha256"]
             and downloaded.get("bytes") == entry["ciphertext"]["bytes"],
             "temporary cleanup requires the exact independently downloaded payload")

    root = Path(production_root)
    stage_path = Path(receipt.get("attempt_root", "")) / "archive.tar.gz"
    stage_relative = stage_path.relative_to(root)
    _require(len(stage_relative.parts) == 5
             and stage_relative.parts[:2] == ("scratch", "production_cold_archive")
             and stage_relative.parts[-2:] == ("stage", "archive.tar.gz"),
             "temporary stage path is outside its fixed production layout")
    locations.archive_id(stage_relative.parts[2])
    download_path = Path(downloaded.get("path", ""))
    if download_path.is_relative_to(root):
        download_root, layout, roles = root, "production_cold_archive_transfer", ROLES
    else:
        # The caller has verified complete restore and custody on the separate
        # host. Derive its root from that successful restore, never a supplied
        # cleanup destination. No workstation path is accessed or selected here.
        restored = catalog._unpack(restore_record["restore"])
        restored_path = Path(restored.get("restored_archive", ""))
        _require(restored_path.is_absolute() and ".." not in restored_path.parts
                 and len(restored_path.parents) >= 5,
                 "temporary cleanup workstation restore path is invalid")
        download_root = restored_path.parents[4]
        restore_id = locations.archive_id(restored.get("restore_id"))
        _require(restored_path == download_root / "scratch" / "ac-rest" / restore_id / "archive" / "archive.tar.gz"
                 and download_root != root,
                 "temporary cleanup requires the fixed separate workstation restore layout")
        layout, roles = "production_cold_archive_transport", ROLES[:2]
    _require(download_path.is_absolute() and ".." not in download_path.parts
             and download_path.is_relative_to(download_root),
             "temporary cleanup download does not match its recovery host")
    download_relative = download_path.relative_to(download_root)
    _require(len(download_relative.parts) == 5
             and download_relative.parts[:2] == ("scratch", layout)
             and download_relative.parts[-2:] == ("transfer", "downloaded-" + entry["archive_id"] + ".rclone.bin"),
             "temporary download path is outside its fixed recovery layout")
    locations.archive_id(download_relative.parts[2])
    rows = inventory.get("files")
    cipher_path = (root / "scratch" / "production_cold_archive_ingress"
                   / entry["archive_id"] / "archive.rclone.bin")
    if download_root != root and isinstance(rows, list) and len(rows) == 1:
        # A workstation upload need not copy ciphertext back to production.
        # Preserve the two-spool contract whenever a local ciphertext exists.
        try:
            cipher_path.lstat()
        except FileNotFoundError:
            roles = ROLES[:1]
    _require(isinstance(rows, list) and len(rows) == len(roles)
             and all(isinstance(row, dict) for row in rows)
             and [row.get("role") for row in rows] == list(roles),
             "temporary inventory requires exactly the ordered payload roles on this production host")
    expected = (
        (stage_path, manifest["archive_bytes"], manifest["archive_sha256"]),
        (cipher_path, entry["ciphertext"]["bytes"], entry["ciphertext"]["sha256"]),
    )
    if len(roles) == 3:
        expected += ((download_path, downloaded["bytes"], downloaded["sha256"]),)
    maximum = archive.MAX_CHUNK_BYTES + archive.MAX_CHUNK_BYTES // 100 + 4 * archive.MIB
    pins, planned = [], []
    for row, (expected_path, expected_bytes, expected_sha) in zip(rows, expected):
        guard.admit()
        relative = locations.relative_path(row.get("path"))
        path = root.joinpath(*relative.parts)
        _require(path == expected_path and row.get("sha256") == expected_sha
                 and type(row.get("size_bytes")) is int
                 and row["size_bytes"] == expected_bytes and 0 < expected_bytes <= maximum,
                 "temporary payload path, content or size differs from its recovery proof")
        expected_native = {key: archive._integer(row.get(key), key, maximum=maximum if key == "size_bytes" else None)
                           for key in ("size_bytes", "mtime_ns", "device", "file_id", "allocated_bytes")}
        pin = stack.enter_context(_removal_pin(locations.safe_path(path)))
        _require(pin.metadata() == expected_native, "temporary payload native identity or allocation changed")
        _require(pin.digest(guard=guard) == expected_sha, "temporary payload content changed")
        pins.append(pin)
        planned.append({"role": row["role"], "path": relative.as_posix(),
                        "sha256": expected_sha, **expected_native})
    return pins, planned


def remove_prepared(pins, files, *, attempt, binding, inventory_sha256, guard):
    """Journal and remove only already-pinned payloads; preserve every directory."""
    parent = Path(attempt)  # Already held by the caller; avoid another long Windows path component.
    base = {**binding, "schema_version": schema_version("cold_archive_spool_cleanup"),
            "spool_inventory_sha256": inventory_sha256, "originals_deleted": 0,
            "remote_objects_deleted": 0, "created_at_utc": datetime.now(timezone.utc).isoformat()}
    guard.admit()
    catalog._write_record(parent / "spool-intent.json", {**base, "status": "INTENT", "files": files})
    removed = []
    for index, (pin, row) in enumerate(zip(pins, files)):
        guard.admit()
        pin.remove()
        catalog._write_record(parent / f"spool-file-{index:05d}.json",
                              {**base, "status": "DELETED", "file": row})
        removed.append(row)
    result, digest = catalog._write_record(parent / "spool-receipt.json", {
        **base, "status": "PASS", "files": removed, "deleted_files": len(removed),
        "removed_allocated_bytes": sum(row["allocated_bytes"] for row in removed),
        "removed_logical_bytes": sum(row["size_bytes"] for row in removed)})
    return {**result, "receipt_path": str(parent / "spool-receipt.json"), "receipt_sha256": digest}
