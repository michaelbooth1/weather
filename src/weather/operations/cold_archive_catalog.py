"""Publish and inspect an immutable catalog for verified cold archives.

Writers are orchestration APIs: callers must own the host workload lease and
provide its live admission/deadline callback. The CLI is read-only. No function
in this module deletes an original source, cloud object, or failed attempt.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from weather import cold_archive_locations as locations
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import production_cold_archive_stage as archive
from weather.operations import production_cold_archive_transfer_core as transfer
from weather.paths import DATA_ROOT
from weather.schema_registry import schema_version

MAX_CACHE_BYTES = 4 * 1024**3
DEFAULT_CACHE_BYTES = 2 * 1024**3


def _require(condition, message):
    locations._require(condition, message)


def _guard(admission, deadline):
    _require(callable(admission) and time.monotonic() < deadline
             and admission() is True, "catalog admission or deadline refused")


def _mkdir(path):
    path = Path(path)
    if not path.exists():
        _mkdir(path.parent)
        path.mkdir()
    return locations.safe_path(path, directory=True)


def _write_record(path, value, *, replace_sha256=None):
    """Publish complete metadata atomically, retaining every prior cache record."""
    path = Path(path)
    locations.safe_path(path.parent, directory=True)
    value = locations.sealed(value)
    raw = locations.canonical(value) + b"\n"
    _require(len(raw) <= locations.MAX_METADATA_BYTES, "catalog record exceeds byte bound")
    if replace_sha256 is None:
        _require(not path.exists(), "catalog destination already exists")
    else:
        locations.read_record(path, replace_sha256)
    temporary = path.parent / (".pending-" + uuid.uuid4().hex)
    with temporary.open("xb") as stream:
        _require(stream.write(raw) == len(raw), "short catalog write")
        stream.flush()
        os.fsync(stream.fileno())
    # Hard-link publication is atomic and create-only on NTFS and POSIX.
    # The temporary link is removed before any record can be accepted by readers.
    if replace_sha256 is None:
        os.link(temporary, path)
        temporary.unlink()
    else:
        locations.read_record(path, replace_sha256)
        os.replace(temporary, path)
    result, digest = locations.read_record(path, hashlib.sha256(raw).hexdigest())
    _require(result == value, "catalog publication readback mismatch")
    return result, digest


def _proof(path, digest):
    archive._require_sha256(digest)
    value, _ = archive._load(path, digest)
    _require(Path(path).stat().st_size <= locations.MAX_METADATA_BYTES,
             "catalog proof exceeds metadata bound")
    raw = Path(path).read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == digest, "catalog proof changed")
    return value, {"sha256": digest, "bytes": len(raw),
                   "base64": base64.b64encode(raw).decode("ascii")}


def _unpack(proof):
    _require(isinstance(proof, dict) and set(proof) == {"sha256", "bytes", "base64"},
             "catalog proof fields invalid")
    archive._require_sha256(proof["sha256"])
    _require(type(proof["bytes"]) is int and 0 < proof["bytes"] <= locations.MAX_METADATA_BYTES
             and isinstance(proof["base64"], str)
             and len(proof["base64"]) <= 2 * locations.MAX_METADATA_BYTES,
             "catalog proof byte bound invalid")
    try:
        raw = base64.b64decode(proof["base64"], validate=True)
        value = json.loads(raw, object_pairs_hook=archive._pairs)
    except (ValueError, TypeError) as exc:
        raise locations.CatalogIntegrityError("catalog proof encoding invalid") from exc
    _require(len(raw) == proof["bytes"] and hashlib.sha256(raw).hexdigest() == proof["sha256"]
             and isinstance(value, dict), "catalog proof hash or type mismatch")
    return value


def _validated_upload(proofs, source_root):
    _require(set(proofs) == {"production_manifest", "production_receipt", "crypt_receipt",
                             "upload_receipt"}, "catalog needs exactly four upstream proofs")
    docs = {name: _unpack(proof) for name, proof in proofs.items()}
    manifest, production, crypt, uploaded = (docs[name] for name in (
        "production_manifest", "production_receipt", "crypt_receipt", "upload_receipt"))
    bridge.validate_production_evidence(manifest, production, manifest.get("plan_sha256"))
    _require(manifest.get("source_proof") == "native_pinned_bytes_during_staging"
             and os.path.normcase(str(source_root)) == os.path.normcase(manifest["source_root"]),
             "catalog production source identity mismatch")
    for row in manifest["files"]:
        parts = locations.relative_path(row["path"]).parts
        _require(len(parts) == 3 and parts[0] == "snapshots",
                 "catalog supports exact immediate snapshot source files")
    archive_id = locations.archive_id(crypt.get("archive_id"))
    cipher = transfer.validate_crypt_receipt(
        crypt, plan_sha256=manifest["plan_sha256"], archive_id=archive_id,
        manifest_sha256=proofs["production_manifest"]["sha256"],
        production_receipt_sha256=proofs["production_receipt"]["sha256"])
    _require(crypt.get("chunk_id") == manifest["chunk_id"]
             and crypt.get("archive_bytes") == manifest["archive_bytes"]
             and crypt.get("archive_sha256") == manifest["archive_sha256"],
             "catalog encrypted archive differs from the staged archive")
    bound = {"archive_id": archive_id, "chunk_id": manifest["chunk_id"],
             "plan_sha256": manifest["plan_sha256"],
             "crypt_receipt_sha256": proofs["crypt_receipt"]["sha256"],
             "production_manifest_sha256": proofs["production_manifest"]["sha256"],
             "production_receipt_sha256": proofs["production_receipt"]["sha256"],
             "ciphertext": {key: cipher[key] for key in ("bytes", "sha256")}}
    files = [("ciphertext", archive_id + ".rclone.bin", cipher["sha256"], cipher["bytes"])]
    for kind, suffix in (("production_manifest", ".manifest.json"),
                         ("production_receipt", ".stage.json"), ("crypt_receipt", ".crypt.json")):
        files.append((kind, archive_id + suffix, proofs[kind]["sha256"], proofs[kind]["bytes"]))
    folder = uploaded.get("drive", {}).get("root_folder_id")
    _require(isinstance(folder, str) and transfer.ID_RE.fullmatch(folder) is not None,
             "catalog cloud folder identity invalid")
    objects = transfer._validate_upload_receipt(uploaded, bindings=bound,
                                                root_folder_id=folder, files=files)
    _require(folder not in {record["object_id"] for record in objects.values()},
             "catalog folder and object identities collide")
    return docs, bound, [{"kind": name, **objects[name], "sha256": digest}
                        for name, _, digest, _ in files]


def publish_upload(*, source_root, production_manifest, production_manifest_sha256,
                   production_receipt, production_receipt_sha256, crypt_receipt,
                   crypt_receipt_sha256, upload_receipt, upload_receipt_sha256,
                   admission, deadline_monotonic):
    """Document a complete upload before reclaim; every source must still exist."""
    _guard(admission, deadline_monotonic)
    root = locations.safe_path(source_root, directory=True)
    inputs = {"production_manifest": (production_manifest, production_manifest_sha256),
              "production_receipt": (production_receipt, production_receipt_sha256),
              "crypt_receipt": (crypt_receipt, crypt_receipt_sha256),
              "upload_receipt": (upload_receipt, upload_receipt_sha256)}
    with ExitStack() as stack:
        stack.enter_context(archive._directory_pin(root))
        proofs = {}
        for name, (path, digest) in inputs.items():
            stack.enter_context(bridge._file_pin(locations.safe_path(path)))
            _, proofs[name] = _proof(path, digest)
        docs, bound, objects = _validated_upload(proofs, root)
        manifest = docs["production_manifest"]
        sources = []
        for row in manifest["files"]:
            path = root.joinpath(*locations.relative_path(row["path"]).parts)
            pin = stack.enter_context(archive._source_pin(locations.safe_path(path)))
            _require(pin.metadata() == {key: row[key] for key in archive._rows([row])[0] if key != "path"},
                     "catalog source differs from the staged file identity")
            sources.append(path)
        catalog = _mkdir(root / "cold_archive" / "catalog")
        entry_dir = _mkdir(catalog / "archives" / bound["archive_id"])
        stack.enter_context(archive._directory_pin(entry_dir))
        markers = [locations.marker_path(path) for path in sources]
        for marker in markers:
            _mkdir(marker.parent)
            stack.enter_context(archive._directory_pin(marker.parent))
            _require(not marker.exists(), "source already has an archive location")
        entry = {
            "schema_version": schema_version("cold_archive_catalog_entry"), "status": "UPLOADED",
            **bound, "source_root": str(root), "files": manifest["files"],
            "archive_sha256": manifest["archive_sha256"], "archive_bytes": manifest["archive_bytes"],
            "drive_root_folder_id": docs["upload_receipt"]["drive"]["root_folder_id"],
            "objects": objects, "proofs": proofs, "published_at_utc": datetime.now(timezone.utc).isoformat(),
            "cleanup_eligible": False, "deletion_authorized": False}
        _guard(admission, deadline_monotonic)
        entry_path = entry_dir / "upload.json"
        entry, digest = _write_record(entry_path, entry)
        for path, marker, row in zip(sources, markers, manifest["files"]):
            _guard(admission, deadline_monotonic)
            _write_record(marker, {
                "schema_version": schema_version("cold_archive_location"),
                "source_path": row["path"], "archive_id": bound["archive_id"],
                "entry_sha256": digest, "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
            _require(locations.load_location(path).entry_sha256 == digest, "location readback mismatch")
        return {"status": "UPLOADED", "entry_path": str(entry_path), "entry_sha256": digest,
                "files": len(markers), "cleanup_eligible": False}


def _entry(path, digest):
    entry, actual = locations.read_record(path, digest)
    _require(entry.get("schema_version") == schema_version("cold_archive_catalog_entry")
             and entry.get("status") == "UPLOADED", "unsupported catalog entry")
    docs, bound, objects = _validated_upload(entry.get("proofs", {}), Path(entry.get("source_root", "")))
    _require(entry.get("files") == docs["production_manifest"]["files"]
             and entry.get("objects") == objects
             and all(entry.get(key) == value for key, value in bound.items())
             and entry.get("drive_root_folder_id") == docs["upload_receipt"]["drive"]["root_folder_id"]
             and all(entry.get(key) == docs["production_manifest"][key]
                     for key in ("archive_sha256", "archive_bytes"))
             and entry.get("cleanup_eligible") is False and entry.get("deletion_authorized") is False,
             "catalog entry differs from its proof bytes")
    return entry, actual, docs


def publish_restore(*, entry_path, entry_sha256, transport_receipt, transport_receipt_sha256,
                    restore_receipt, restore_receipt_sha256, admission, deadline_monotonic):
    """Retain complete recovery proof independently of transient local cache copies."""
    _guard(admission, deadline_monotonic)
    with ExitStack() as stack:
        for path in (entry_path, transport_receipt, restore_receipt):
            stack.enter_context(bridge._file_pin(locations.safe_path(path)))
        entry, digest, docs = _entry(entry_path, entry_sha256)
        transport, transport_proof = _proof(transport_receipt, transport_receipt_sha256)
        restored, restore_proof = _proof(restore_receipt, restore_receipt_sha256)
        archive._check_seal(transport, "receipt_hash")
        archive._check_seal(restored, "receipt_hash")
        _require(transport.get("schema_version") == schema_version("production_cold_archive_transport_receipt")
                 and transport.get("status") == "PASS"
                 and transport.get("phase") == "download_and_verify"
                 and transport.get("independent_download") is True
                 and transport.get("upload_performed") is False
                 and transport.get("upload_receipt_sha256") == entry["proofs"]["upload_receipt"]["sha256"],
                 "catalog requires an independent download of the committed upload")
        _require(restored.get("schema_version") == schema_version("production_cold_archive_restore_receipt")
                 and restored.get("status") == "PASS" and restored.get("restore_performed") is True
                 and restored.get("verified_file_count") == len(entry["files"])
                 and restored.get("checks") == dict.fromkeys(bridge.RESTORE_CHECKS, "PASS"),
                 "catalog restore proof is incomplete")
        bridge._identity(restored.get("tool_identity"))
        for proof in (transport, restored):
            _require(all(proof.get(key) == entry[key] for key in (
                "archive_id", "chunk_id", "plan_sha256", "production_manifest_sha256",
                "production_receipt_sha256", "crypt_receipt_sha256")),
                "catalog recovery proof belongs to a different archive")
            _require(proof.get("source_retained") is True and proof.get("cleanup_eligible") is False
                     and proof.get("deletion_authorized") is False,
                     "catalog recovery proof retention differs")
        _require(restored.get("transport_receipt_sha256") == transport_receipt_sha256
                 and restored.get("ciphertext") == docs["crypt_receipt"]["ciphertext"]
                 and restored.get("restored_members") == [
                     {"path": row["path"], "bytes": row["size_bytes"], "sha256": row["sha256"]}
                     for row in entry["files"]], "catalog materialized member proof differs")
        expected_drive = {key: docs["upload_receipt"]["drive"][key]
                          for key in ("root_folder_id", "object_id", "remote_key")}
        _require(transport.get("drive") == expected_drive and restored.get("drive") == expected_drive
                 and transport.get("ciphertext") == entry["ciphertext"],
                 "catalog download cloud identity differs from the upload")
        metadata = transport.get("metadata_objects")
        expected = docs["upload_receipt"]["metadata_objects"]
        _require(isinstance(metadata, list) and len(metadata) == len(expected),
                 "catalog downloaded metadata is incomplete")
        for actual, original in zip(metadata, expected):
            _require(isinstance(actual, dict) and isinstance(actual.get("downloaded_path"), str)
                     and {key: value for key, value in actual.items() if key != "downloaded_path"} == original,
                     "catalog downloaded metadata differs from the upload")
        record = {
            "schema_version": schema_version("cold_archive_catalog_restore"),
            "status": "RESTORE_VERIFIED", "entry_sha256": digest, "archive_id": entry["archive_id"],
            "transport": transport_proof, "restore": restore_proof,
            "verified_file_count": len(entry["files"]), "cleanup_eligible": False,
            "published_at_utc": datetime.now(timezone.utc).isoformat()}
        parent = _mkdir(Path(entry_path).parent / "restores")
        stack.enter_context(archive._directory_pin(parent))
        _guard(admission, deadline_monotonic)
        path = parent / (restore_receipt_sha256 + ".json")
        _, record_sha = _write_record(path, record)
        return {"status": "RESTORE_VERIFIED", "record_path": str(path),
                "record_sha256": record_sha, "cleanup_eligible": False}



def import_locations(*, entry_path, entry_sha256, local_source_root,
                     admission, deadline_monotonic):
    """Install exact catalog bytes and markers in an empty recovery data layout.

    The entry retains its original production source root. This local layout is
    for explicit restored inputs and conveys no source identity or reclaim proof.
    """
    _guard(admission, deadline_monotonic)
    with ExitStack() as stack:
        stack.enter_context(bridge._file_pin(locations.safe_path(entry_path)))
        entry, digest, _ = _entry(entry_path, entry_sha256)
        root = locations.safe_path(local_source_root, directory=True)
        stack.enter_context(archive._directory_pin(root))
        sources = [root.joinpath(*locations.relative_path(row["path"]).parts) for row in entry["files"]]
        _require(all(not source.exists() and not source.is_symlink() for source in sources),
                 "recovery layout must not contain original source files")
        destination = _mkdir(root / "cold_archive" / "catalog" / "archives" / entry["archive_id"])
        stack.enter_context(archive._directory_pin(destination))
        output_entry = destination / "upload.json"
        if output_entry.exists():
            locations.read_record(output_entry, digest)
        else:
            _, copied_sha = _write_record(output_entry, entry)
            _require(copied_sha == digest, "imported entry bytes differ")
        for source, row in zip(sources, entry["files"]):
            _guard(admission, deadline_monotonic)
            _mkdir(source.parent)
            marker = locations.marker_path(source)
            _mkdir(marker.parent)
            stack.enter_context(archive._directory_pin(marker.parent))
            if marker.exists():
                _require(locations.load_location(source).entry_sha256 == digest,
                         "recovery cannot replace another location")
                continue
            _write_record(marker, {
                "schema_version": schema_version("cold_archive_location"),
                "source_path": row["path"], "archive_id": entry["archive_id"],
                "entry_sha256": digest, "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
            _require(locations.load_location(source).entry_sha256 == digest, "import readback differs")
        return {"status": "IMPORTED_LOCATIONS", "entry_path": str(output_entry),
                "entry_sha256": digest, "local_source_root": str(root),
                "original_source_root": entry["source_root"], "cleanup_eligible": False}


def _local_catalog_root(entry_path, entry):
    path = Path(entry_path)
    expected = ("cold_archive", "catalog", "archives", entry["archive_id"], "upload.json")
    _require(len(path.parts) > len(expected) and tuple(path.parts[-5:]) == expected,
             "cache entry is outside the documented local catalog layout")
    return locations.safe_path(path.parents[4], directory=True)


def cache_usage(root):
    """Bounded metadata-only accounting of this managed cache, including partials."""
    root = Path(root)
    if not root.exists():
        return 0
    total, visited, pending = 0, 0, [root]
    while pending:
        directory = locations.safe_path(pending.pop(), directory=True)
        for path in directory.iterdir():
            visited += 1
            _require(visited <= 10000, "managed restore cache entry bound exceeded")
            if path.is_dir():
                locations.safe_path(path, directory=True)
                pending.append(path)
            else:
                locations.safe_path(path)
                total += path.stat().st_size
    return total


def publish_cache(*, entry_path, entry_sha256, restore_record, restore_record_sha256,
                  restored_members_root, cache_id, admission, deadline_monotonic,
                  free_space_reserve_bytes, cache_limit_bytes=DEFAULT_CACHE_BYTES):
    """Copy fully restored members into a fresh bounded cache; keep all partials."""
    _guard(admission, deadline_monotonic)
    locations.archive_id(cache_id)
    _require(type(cache_limit_bytes) is int and 0 < cache_limit_bytes <= MAX_CACHE_BYTES,
             "cache byte limit invalid")
    reserve = archive._integer(free_space_reserve_bytes, "cache disk reserve")
    with ExitStack() as stack:
        for path in (entry_path, restore_record):
            stack.enter_context(bridge._file_pin(locations.safe_path(path)))
        entry, digest, _ = _entry(entry_path, entry_sha256)
        record, _ = locations.read_record(restore_record, restore_record_sha256)
        _require(record.get("schema_version") == schema_version("cold_archive_catalog_restore")
                 and record.get("status") == "RESTORE_VERIFIED"
                 and record.get("entry_sha256") == digest,
                 "cache requires catalog-bound full restore proof")
        restored = _unpack(record["restore"])
        _require(restored.get("status") == "PASS"
                 and restored.get("checks") == dict.fromkeys(bridge.RESTORE_CHECKS, "PASS")
                 and restored.get("restored_members") == [
                     {"path": row["path"], "bytes": row["size_bytes"], "sha256": row["sha256"]}
                     for row in entry["files"]], "cache restored member proof mismatch")
        source = locations.safe_path(restored_members_root, directory=True)
        root = _local_catalog_root(entry_path, entry)
        managed = root / "cold_archive" / "restore_cache"
        _require(not source.is_relative_to(managed) and not managed.is_relative_to(source),
                 "restore source and cache overlap")
        stack.enter_context(archive._directory_pin(source))
        parent = _mkdir(managed)
        stack.enter_context(archive._directory_pin(parent))
        needed = sum(row["size_bytes"] for row in entry["files"]) + 2 * archive.MIB
        _require(cache_usage(parent) + needed <= cache_limit_bytes
                 and shutil.disk_usage(parent).free >= reserve + needed,
                 "restore cache quota or free-space reserve refused")
        attempt = parent / cache_id
        attempt.mkdir()
        stack.enter_context(archive._directory_pin(attempt))
        _write_record(attempt / "claim.json", {
            "schema_version": schema_version("cold_archive_cache"), "status": "CLAIMED",
            "entry_sha256": digest, "cache_id": cache_id, "cleanup_eligible": False})
        output = _mkdir(attempt / "members")
        files, held_pins = [], []
        guard = archive._Guard(admission, deadline_monotonic, 16 * archive.MIB)
        for row in entry["files"]:
            relative = locations.relative_path(row["path"])
            original = source.joinpath(*relative.parts)
            destination = output.joinpath(*relative.parts)
            _mkdir(destination.parent)
            with bridge._file_pin(locations.safe_path(original)) as pin:
                before = pin.metadata()
                _require(original.stat().st_size == row["size_bytes"], "restore member size changed")
                with original.open("rb") as incoming, destination.open("xb") as outgoing:
                    reader = archive._Reader(incoming, guard)
                    writer = archive._Writer(outgoing, guard, row["size_bytes"], parent, reserve)
                    while block := reader.read(archive.MIB):
                        writer.write(block)
                    outgoing.flush()
                    os.fsync(outgoing.fileno())
                _require(pin.metadata() == before and reader.bytes == row["size_bytes"]
                         and reader.digest.hexdigest() == row["sha256"], "restore member content changed")
            cache_pin = stack.enter_context(bridge._file_pin(locations.safe_path(destination)))
            held_pins.append((cache_pin, cache_pin.metadata()))
            count, actual = transfer._sha_file(destination, admission, deadline_monotonic,
                                                maximum=max(row["size_bytes"], 1))
            _require((count, actual) == (row["size_bytes"], row["sha256"]),
                     "cache member readback differs")
            files.append({"source_path": row["path"], "cache_path": destination.relative_to(root).as_posix(),
                          "sha256": actual, "identity": locations.file_identity(destination)})
        _require(all(pin.metadata() == before for pin, before in held_pins), "cache member changed before publication")
        cache = {"schema_version": schema_version("cold_archive_cache"), "status": "PASS",
                 "entry_sha256": digest, "cache_id": cache_id, "files": files,
                 "restore_record_sha256": restore_record_sha256, "cleanup_eligible": False}
        record_path = Path(entry_path).parent / "caches"
        _mkdir(record_path)
        _guard(admission, deadline_monotonic)
        _, cache_sha = _write_record(record_path / (cache_id + ".json"), cache)
        pointer = Path(entry_path).parent / "cache.json"
        previous = locations.read_record(pointer)[1] if pointer.exists() else None
        _write_record(pointer, cache, replace_sha256=previous)
        return {"status": "PASS", "cache_id": cache_id, "cache_sha256": cache_sha,
                "files": len(files), "logical_bytes": needed - 2 * archive.MIB,
                "cleanup_eligible": False}



def repair_locations(*, entry_path, entry_sha256, admission, deadline_monotonic):
    """Finish interrupted marker publication while every original is retained."""
    _guard(admission, deadline_monotonic)
    with ExitStack() as stack:
        stack.enter_context(bridge._file_pin(locations.safe_path(entry_path)))
        entry, digest, _ = _entry(entry_path, entry_sha256)
        root = locations.safe_path(entry["source_root"], directory=True)
        _require(Path(entry_path) == root / "cold_archive" / "catalog" / "archives"
                 / entry["archive_id"] / "upload.json", "repair entry is outside its source catalog")
        stack.enter_context(archive._directory_pin(root))
        pending = []
        for row in entry["files"]:
            source = root.joinpath(*locations.relative_path(row["path"]).parts)
            pin = stack.enter_context(archive._source_pin(locations.safe_path(source)))
            _require(pin.metadata() == {
                key: row[key] for key in archive._rows([row])[0] if key != "path"},
                "repair requires unchanged retained originals")
            marker = locations.marker_path(source)
            _mkdir(marker.parent)
            stack.enter_context(archive._directory_pin(marker.parent))
            if marker.exists():
                _require(locations.load_location(source).entry_sha256 == digest,
                         "repair cannot replace another archive location")
            else:
                pending.append((source, marker, row))
        for source, marker, row in pending:
            _guard(admission, deadline_monotonic)
            _write_record(marker, {
                "schema_version": schema_version("cold_archive_location"),
                "source_path": row["path"], "archive_id": entry["archive_id"],
                "entry_sha256": digest, "sha256": row["sha256"], "size_bytes": row["size_bytes"]})
            _require(locations.load_location(source).entry_sha256 == digest, "repair readback differs")
        return {"status": "PASS", "entry_sha256": digest, "markers_created": len(pending),
                "cleanup_eligible": False}


def export_recovery_proofs(*, entry_path, entry_sha256, output_root,
                           admission, deadline_monotonic):
    """Recover exact original proof files from a retained catalog into a new attempt."""
    _guard(admission, deadline_monotonic)
    with ExitStack() as stack:
        stack.enter_context(bridge._file_pin(locations.safe_path(entry_path)))
        entry, digest, _ = _entry(entry_path, entry_sha256)
        output = Path(output_root)
        locations.safe_path(output.parent, directory=True)
        _require(not output.exists(), "recovery proof output already exists")
        output.mkdir()
        stack.enter_context(archive._directory_pin(output))
        files = {}
        for name, proof in entry["proofs"].items():
            _guard(admission, deadline_monotonic)
            _unpack(proof)
            path = output / (name + ".json")
            raw = base64.b64decode(proof["base64"], validate=True)
            with path.open("xb") as stream:
                _require(stream.write(raw) == len(raw), "short recovery metadata write")
                stream.flush()
                os.fsync(stream.fileno())
            _require(hashlib.sha256(path.read_bytes()).hexdigest() == proof["sha256"],
                     "recovery metadata readback differs")
            files[name] = {"path": str(path), "sha256": proof["sha256"]}
        result, result_sha = _write_record(output / "catalog-recovery.json", {
            "schema_version": schema_version("cold_archive_recovery_export"),
            "status": "EXPORTED_RECOVERY_PROOFS", "entry_sha256": digest,
            "archive_id": entry["archive_id"], "drive_root_folder_id": entry["drive_root_folder_id"],
            "objects": entry["objects"], "proof_files": files, "cleanup_eligible": False})
        return {**result, "export_receipt_sha256": result_sha}


def write_inventory(*, source_root=DATA_ROOT, admission, deadline_monotonic):
    """Keep an immutable Markdown snapshot and update its human-readable pointer."""
    _guard(admission, deadline_monotonic)
    root = locations.safe_path(source_root, directory=True)
    parent = _mkdir(root / "cold_archive")
    with archive._directory_pin(parent):
        output = parent / "WHERE_DATA_IS.md"
        if output.exists():
            locations.safe_path(output)
        raw = render_inventory(root).encode("utf-8")
        _require(len(raw) <= locations.MAX_METADATA_BYTES, "inventory Markdown exceeds byte bound")
        snapshots = _mkdir(parent / "catalog" / "inventories")
        snapshot_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
        path = snapshots / (snapshot_id + ".md")
        with path.open("xb") as stream:
            _require(stream.write(raw) == len(raw), "short inventory snapshot write")
            stream.flush()
            os.fsync(stream.fileno())
        digest = hashlib.sha256(raw).hexdigest()
        _require(hashlib.sha256(path.read_bytes()).hexdigest() == digest, "inventory readback differs")
        _guard(admission, deadline_monotonic)
        pending = parent / (".pending-inventory-" + uuid.uuid4().hex)
        with pending.open("xb") as stream:
            _require(stream.write(raw) == len(raw), "short inventory pointer write")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, output)
        _require(hashlib.sha256(output.read_bytes()).hexdigest() == digest, "inventory pointer differs")
        return {"status": "PASS", "inventory_path": str(output), "snapshot_path": str(path),
                "sha256": digest, "cleanup_eligible": False}


def describe(source_path):
    location = locations.load_location(source_path)
    if location is None:
        return {"source_path": str(Path(source_path).absolute()),
                "status": "LOCAL" if Path(source_path).is_file() else "UNKNOWN_MISSING"}
    cached = None if location.local else locations.cached_path(location)
    entry = location.entry
    return {"source_path": str(location.source_path), "original_relative_path": location.member["path"],
            "status": "LOCAL_WITH_CLOUD_COPY" if location.local else (
                "VERIFIED_LOCAL_CACHE" if cached else "ARCHIVED_RESTORE_REQUIRED"),
            "cache_path": str(cached) if cached else None, "sha256": location.member["sha256"],
            "size_bytes": location.member["size_bytes"], "archive_id": entry["archive_id"],
            "entry_path": str(location.entry_path), "entry_sha256": location.entry_sha256,
            "drive_root_folder_id": entry["drive_root_folder_id"], "objects": entry["objects"],
            "restore_instructions": "docs/operations/cold-archive-locations.md",
            "cleanup_eligible": False}


def render_inventory(source_root=DATA_ROOT):
    """Produce a human-readable inventory; hashes and exact IDs stay in each entry."""
    root = Path(source_root)
    catalog = root / "cold_archive" / "catalog"
    lines = ["# Where archived data is", "",
             "Generated from immutable archive catalog entries. Original paths remain logical identities.",
             "Catalog paths below are relative to data/cold_archive.",
             "UPLOADED alone does not prove restore or authorize deletion.", "",
             "| Original path | State | Bytes | Archive | Cloud folder | Catalog entry |",
             "| --- | --- | ---: | --- | --- | --- |"]
    archives = catalog / "archives"
    if not archives.exists():
        return "\n".join(lines + ["", "No archived files have been registered.", ""])
    for index, directory in enumerate(sorted(archives.iterdir())):
        _require(index < 10000, "catalog archive count exceeds bound")
        locations.archive_id(directory.name)
        entry_path = directory / "upload.json"
        if not entry_path.exists():
            continue  # Interrupted publication retains an incomplete directory.
        entry, _ = locations.read_record(entry_path)
        for row in entry["files"]:
            source = root.joinpath(*locations.relative_path(row["path"]).parts)
            # Inventory is metadata-only. Detailed locate verifies cache content.
            state = "LOCAL_WITH_CLOUD_COPY" if source.is_file() else "ARCHIVED"
            folder = entry["drive_root_folder_id"]
            lines.append(f'| {row["path"]} | {state} | {row["size_bytes"]} | {entry["archive_id"]} | '
                         f'[Private Drive folder](https://drive.google.com/drive/folders/{folder}) | '
                         f'`catalog/archives/{entry["archive_id"]}/upload.json` |')
    return "\n".join(lines + ["", "Restore: docs/operations/cold-archive-locations.md", ""])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    locate = sub.add_parser("locate", help="Show exact original identity and cloud objects.")
    locate.add_argument("--source-path", required=True)
    inventory = sub.add_parser("inventory", help="Print the complete archive inventory as Markdown.")
    inventory.add_argument("--source-root", default=str(DATA_ROOT))
    args = parser.parse_args(argv)
    if args.operation == "locate":
        print(json.dumps(describe(args.source_path), indent=2))
    else:
        print(render_inventory(args.source_root), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
