"""Remove only verified workstation archive working copies, retaining recovery proof.

Originals, cloud objects, credentials, metadata, directories and unrelated or
failed-attempt outputs are outside this fixed selection. The native wrapper owns
the shared workstation/live mutex and complete child Job through cleanup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

from weather import cold_archive_locations as locations
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import cold_archive_native_removal as native_removal
from weather.operations import cold_archive_spool_cleanup as spool
from weather.operations import production_cold_archive_stage as archive
from weather.operations import workstation_cold_archive_transfer as workstation
from weather.paths import repo_path
from weather.schema_registry import schema_version

TOOL = "weather.operations.workstation_cold_archive_cleanup"
DEADLINE_SECONDS = 300
EVIDENCE_RESERVE_BYTES = 64 * archive.MIB


def _require(condition, message):
    catalog._require(condition, message)


def _scratch(path, repo, *, directory=False):
    path = Path(path)
    _require(path.is_absolute() and ".." not in path.parts
             and path.is_relative_to(repo / "scratch")
             and not any(part.lower() == "weather-mirror" for part in path.parts),
             "cleanup input must stay in the reviewed workstation scratch tree")
    return locations.safe_path(path, directory=directory)


def _metadata(spec, repo, stack):
    _require(isinstance(spec, dict) and set(spec) == {"path", "sha256"},
             "cleanup metadata requires an exact path and hash")
    path = _scratch(spec["path"], repo)
    stack.enter_context(bridge._file_pin(path))
    return locations.read_record(path, spec["sha256"])


def _expected_payloads(repo, entry, docs, record, ciphertext_root):
    """Derive every selectable name from successful upstream evidence."""
    archive_id = locations.archive_id(entry["archive_id"])
    root = Path(ciphertext_root)
    _require(root.parent == repo / "scratch" / "production_cold_archive_ciphertext",
             "cleanup ciphertext root is outside the fixed archive layout")
    locations.archive_id(root.name)
    crypt = docs["crypt_receipt"]
    restored = catalog._unpack(record["restore"])
    transport = catalog._unpack(record["transport"])
    restore_id = locations.archive_id(restored.get("restore_id"))
    restore_root = repo / "scratch" / "ac-rest" / restore_id
    restored_archive = restore_root / "archive" / "archive.tar.gz"
    _require(Path(restored.get("restored_archive", "")) == restored_archive,
             "cleanup restore path differs from the successful restore attempt")
    encrypted = locations.relative_path(crypt["ciphertext"]["path_relative_to_ciphertext_root"])
    restored_cipher = locations.relative_path(restored.get("restore_ciphertext_relative_path"))
    _require(len(encrypted.parts) == 2 and len(restored_cipher.parts) == 3
             and restored_cipher.parts[1:] == encrypted.parts,
             "cleanup encrypted key mapping differs from the complete restore")
    copied_archive = repo / "scratch" / "ac-in" / archive_id / "archive.tar.gz"
    downloaded = transport.get("downloaded_file", {})
    _require(downloaded.get("bytes") == entry["ciphertext"]["bytes"]
             and downloaded.get("sha256") == entry["ciphertext"]["sha256"],
             "cleanup download differs from the restored ciphertext")
    download_path = Path(downloaded.get("path", ""))
    if download_path.is_relative_to(repo):
        relative = download_path.relative_to(repo)
        _require(len(relative.parts) == 5
                 and relative.parts[:2] == ("scratch", "production_cold_archive_transport")
                 and relative.parts[-2:] == ("transfer", "downloaded-" + archive_id + ".rclone.bin"),
                 "cleanup download is outside its successful transport attempt")
        locations.archive_id(relative.parts[2])
    else:
        # Legacy production transport copied the verified download into this
        # fixed workstation inbox before restore. Its native identity is in
        # the successful workstation restore, checked below.
        production = Path(entry["source_root"]).parent
        _require(download_path.is_relative_to(production),
                 "cleanup legacy download has no bound production origin")
        relative = download_path.relative_to(production)
        _require(len(relative.parts) == 5
                 and relative.parts[:2] == ("scratch", "production_cold_archive_transfer")
                 and relative.parts[-2:] == ("transfer", "downloaded-" + archive_id + ".rclone.bin"),
                 "cleanup legacy transport path is outside its production attempt")
        locations.archive_id(relative.parts[2])
        download_path = repo / "scratch" / "ac-in" / archive_id / "downloaded.rclone.bin"
    cipher = entry["ciphertext"]
    packed = {"bytes": entry["archive_bytes"], "sha256": entry["archive_sha256"]}
    rows = [
        ("copied_archive", copied_archive, packed, None),
        ("encrypted_archive", root / encrypted, cipher, crypt["ciphertext"].get("file_identity")),
        ("downloaded_ciphertext", download_path, cipher, restored.get("downloaded_file_identity")),
        ("restore_ciphertext", root / restored_cipher, cipher, None),
        ("restored_archive", restored_archive, packed, None),
    ]
    for member in entry["files"]:
        rows.append(("restored_member", restore_root / "members" / locations.relative_path(member["path"]),
                     {"bytes": member["size_bytes"], "sha256": member["sha256"]}, None))
    _require(len({path for _, path, _, _ in rows}) == len(rows),
             "cleanup payload names overlap")
    _require(all(identity is not None for role, _, _, identity in rows
                 if role in ("encrypted_archive", "downloaded_ciphertext")),
             "cleanup ciphertext native identity is missing")
    return rows


def _identity_matches(native, expected):
    _require(isinstance(expected, dict)
             and set(expected) == {"device", "inode", "mode", "bytes", "mtime_ns"}
             and all(type(value) is int and value >= 0 for value in expected.values())
             and expected["mode"] == stat.S_IFREG,
             "cleanup saved ciphertext identity is invalid")
    _require(all(native[key] == expected[other] for key, other in (
        ("device", "device"), ("file_id", "inode"), ("size_bytes", "bytes"), ("mtime_ns", "mtime_ns"))),
        "cleanup ciphertext identity changed since successful production")


def cleanup_payloads(*, entry_path, entry_sha256, restore_record, restore_record_sha256,
                     custody_record, custody_record_sha256, ciphertext_root, attempt_id,
                     repo_root, backup_host_id, admission, deadline_monotonic,
                     now=None, removal_factory=spool._removal_pin, execution_evidence=None,
                     before_deletion=None):
    """Pin and rehash all qualified copies before any exact native deletion."""
    repo = locations.safe_path(repo_root, directory=True)
    locations.archive_id(attempt_id)
    locations.require_sha(backup_host_id)
    catalog._guard(admission, deadline_monotonic)
    _require(shutil.disk_usage(repo).free >= EVIDENCE_RESERVE_BYTES,
             "cleanup needs reserved space for durable receipts")
    parent = catalog._mkdir(repo / "scratch" / "ac-clean")
    with ExitStack() as stack:
        stack.enter_context(archive._directory_pin(parent))
        attempt = parent / attempt_id
        attempt.mkdir()  # Every started attempt is spent, even a failed preflight.
        stack.enter_context(archive._directory_pin(attempt))
        binding = {"schema_version": schema_version("workstation_cold_archive_cleanup"),
                   "attempt_id": attempt_id, "entry_sha256": entry_sha256,
                   "backup_execution_host_id": backup_host_id,
                   "originals_deleted": 0, "remote_objects_deleted": 0,
                   "archive_source_reclaimed_bytes": 0, "cleanup_eligible": False,
                   "execution_evidence": execution_evidence}
        catalog._write_record(attempt / "claim.json", {**binding, "status": "CLAIMED"})
        removed = []
        try:
            entry_spec = {"path": entry_path, "sha256": entry_sha256}
            _metadata(entry_spec, repo, stack)
            entry, entry_sha, docs = catalog._entry(entry_path, entry_sha256)
            binding["archive_id"] = entry["archive_id"]
            restore_spec = {"path": restore_record, "sha256": restore_record_sha256}
            custody_spec = {"path": custody_record, "sha256": custody_record_sha256}
            _metadata(restore_spec, repo, stack)
            _metadata(custody_spec, repo, stack)
            current = now or datetime.now(timezone.utc)
            record, restore_sha = reclaim._restore(restore_spec, stack, entry, entry_sha, current)
            custody, custody_sha = reclaim._custody(
                custody_spec, stack, entry_sha, restore_sha, backup_host_id, current)
            _require(custody["verified_backups"] == {
                "catalog_entry": {"path": str(Path(entry_path)), "sha256": entry_sha},
                "restore_record": {"path": str(Path(restore_record)), "sha256": restore_sha}},
                "cleanup must retain the actual verified workstation recovery copies")
            root = _scratch(ciphertext_root, repo, directory=True)
            stack.enter_context(archive._directory_pin(root))
            rows = _expected_payloads(repo, entry, docs, record, root)
            guard = archive._Guard(admission, deadline_monotonic, 16 * archive.MIB)
            held, planned = [], []
            for role, path, proof, identity in rows:
                guard.admit()
                pin = stack.enter_context(removal_factory(_scratch(path, repo)))
                native = pin.metadata()
                _require(native["size_bytes"] == proof["bytes"],
                         "cleanup payload length differs from verified recovery")
                if identity is not None:
                    _identity_matches(native, identity)
                _require(pin.digest(guard=guard) == proof["sha256"],
                         "cleanup payload content differs from verified recovery")
                held.append(pin)
                planned.append({"role": role, "path": path.relative_to(repo).as_posix(),
                                "sha256": proof["sha256"], **native})
            binding.update(restore_record_sha256=restore_sha, custody_record_sha256=custody_sha)
            if before_deletion is not None:
                before_deletion()
            guard.admit()
            free_before = shutil.disk_usage(repo).free
            catalog._write_record(attempt / "intent.json", {
                **binding, "status": "INTENT", "files": planned, "free_bytes_before": free_before})
            for index, (pin, row) in enumerate(zip(held, planned)):
                guard.admit()
                pin.remove()
                removed.append(row)
                catalog._write_record(attempt / (f"file-{index:05d}.json"), {
                    **binding, "status": "DELETED", "file": row})
            guard.admit()
            result, digest = catalog._write_record(attempt / "receipt.json", {
                **binding, "status": "PASS", "files": removed, "deleted_files": len(removed),
                "removed_allocated_bytes": sum(row["allocated_bytes"] for row in removed),
                "removed_logical_bytes": sum(row["size_bytes"] for row in removed),
                "free_bytes_before": free_before, "free_bytes_after": shutil.disk_usage(repo).free,
                "completed_at_utc": datetime.now(timezone.utc).isoformat()})
            return {**result, "receipt_path": str(attempt / "receipt.json"), "receipt_sha256": digest}
        except BaseException as exc:
            catalog._write_record(attempt / "failure.json", {
                **binding, "status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__,
                "confirmed_deleted_files": len(removed), "confirmed_files": removed,
                "requires_reconciliation": True})
            raise


def run_cleanup(args):
    repo = repo_path()
    deadline = time.monotonic() + DEADLINE_SECONDS
    with ExitStack() as stack:
        assignment_path, assignment_pin, assignment_identity, assignment_sha, host = workstation._assignment(repo, stack)
        identity = bridge._capture_identity(repo)
        _require(identity["git_commit"] == args.expected_source_tip and identity["git_dirty"] is False,
                 "cleanup requires the exact reviewed clean source")
        paths = [Path(module.__file__) for module in (bridge, catalog, reclaim, spool, archive, locations,
                                                     native_removal, workstation, bridge.stage)]
        paths.append(Path(__file__))
        pins = [(stack.enter_context(bridge._file_pin(path)), path) for path in paths]
        before = [pin.metadata() for pin, _ in pins]

        def guard():
            _require(os.environ.get(bridge.stage.WRAPPER_ENV) == "1" and time.monotonic() < deadline,
                     "cleanup wrapper or deadline ended")
            _require(assignment_pin.metadata() == assignment_identity
                     and hashlib.sha256(assignment_path.read_bytes()).hexdigest() == assignment_sha,
                     "cleanup workstation assignment changed")
            _require([pin.metadata() for pin, _ in pins] == before, "cleanup source changed")
            return True

        values = vars(args).copy()
        values.pop("expected_source_tip")
        def before_deletion():
            guard()
            _require(bridge._capture_identity(repo) == identity, "cleanup source identity changed")

        evidence = {"tool": TOOL, "source_git_sha": identity["git_commit"],
                    "assignment_sha256": assignment_sha,
                    "module_hashes": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                      for _, path in pins}}
        result = cleanup_payloads(**values, repo_root=repo, backup_host_id=host,
                                  admission=guard, deadline_monotonic=deadline,
                                  before_deletion=before_deletion, execution_evidence=evidence)
        guard()
        _require(bridge._capture_identity(repo) == identity, "cleanup source identity changed")
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("entry_path", "entry_sha256", "restore_record", "restore_record_sha256",
                  "custody_record", "custody_record_sha256", "ciphertext_root", "attempt_id",
                  "expected_source_tip"):
        parser.add_argument("--" + field.replace("_", "-"), required=True)
    try:
        result = run_cleanup(parser.parse_args(argv))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({key: result[key] for key in
                     ("status", "deleted_files", "removed_allocated_bytes", "receipt_path", "receipt_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
