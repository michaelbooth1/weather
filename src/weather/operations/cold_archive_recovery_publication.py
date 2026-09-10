"""Publish complete archive recovery and verified off-host metadata custody."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import time

from weather import cold_archive_locations as locations
from weather import execution_host
from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import cold_archive_catalog as catalog
from weather.paths import repo_path
from weather.schema_registry import schema_version


def _load(path, digest, stack):
    path = locations.safe_path(path)
    stack.enter_context(bridge._file_pin(path))
    catalog._require(path.stat().st_size <= locations.MAX_METADATA_BYTES, "recovery input metadata exceeds bound")
    return catalog._proof(path, digest)[0]


def _key_custody(value):
    fields = {"schema_version", "confirmed", "outside_both_pcs", "approved_by",
              "confirmed_at_utc", "storage_reference"}
    catalog._require(isinstance(value, dict) and set(value) == fields
                     and value["schema_version"] == schema_version("cold_archive_key_custody")
                     and value["confirmed"] is True and value["outside_both_pcs"] is True,
                     "recovery-key custody requires the owner's exact external-storage confirmation")
    for key, limit in (("approved_by", 128), ("storage_reference", 512)):
        catalog._require(isinstance(value[key], str) and 0 < len(value[key].strip()) <= limit,
                         "recovery-key custody location or owner is missing")
    confirmed = datetime.fromisoformat(str(value["confirmed_at_utc"]).replace("Z", "+00:00"))
    catalog._require(confirmed.tzinfo is not None and confirmed <= datetime.now(timezone.utc),
                     "recovery-key custody confirmation is future-dated or lacks a timezone")
    return {key: value[key] for key in fields if key != "schema_version"}


def publish_recovery(*, entry_path, entry_sha256, transport_receipt, transport_receipt_sha256,
                     restore_receipt, restore_receipt_sha256, key_custody, key_custody_sha256,
                     recovery_data_root, attempt_id, repo_root, backup_host_id,
                     admission, deadline_monotonic):
    """Write a create-only metadata handback in an isolated workstation layout."""
    locations.require_sha(backup_host_id)
    locations.archive_id(attempt_id)
    root = locations.safe_path(recovery_data_root, directory=True)
    repo = locations.safe_path(repo_root, directory=True)
    catalog._require(root.name == "data"
                     and root.parent.parent == repo / "scratch" / "production_cold_archive_recovery",
                     "recovery publication must use its dedicated scratch data layout")
    locations.archive_id(root.parent.name)
    catalog._guard(admission, deadline_monotonic)
    with ExitStack() as stack:
        stack.enter_context(bridge.core._directory_pin(root.parent))
        for path, digest in ((entry_path, entry_sha256), (transport_receipt, transport_receipt_sha256),
                             (restore_receipt, restore_receipt_sha256)):
            _load(path, digest, stack)
        key = _key_custody(_load(key_custody, key_custody_sha256, stack))
        entry, digest, _ = catalog._entry(entry_path, entry_sha256)
        handback_root = root.parent / "handbacks" / attempt_id
        future = [root / "cold_archive" / "catalog" / "archives" / entry["archive_id"] / "restores" / (restore_receipt_sha256 + ".json"),
                  handback_root / (".pending-" + "0" * 32)]
        for row in entry["files"]:
            marker = locations.marker_path(root.joinpath(*locations.relative_path(row["path"]).parts))
            future.extend((marker, marker.parent / (".pending-" + "0" * 32)))
        catalog._require(os.name != "nt" or all(len(str(path).encode("utf-16-le")) // 2 < 260 for path in future),
                         "recovery publication needs shorter Windows paths")
        handbacks = catalog._mkdir(root.parent / "handbacks")
        stack.enter_context(bridge.core._directory_pin(handbacks))
        attempt = handbacks / attempt_id
        attempt.mkdir()
        stack.enter_context(bridge.core._directory_pin(attempt))
        binding = {"schema_version": schema_version("cold_archive_recovery_publication"),
                   "archive_id": entry["archive_id"], "entry_sha256": digest,
                   "attempt_id": attempt_id, "backup_execution_host_id": backup_host_id,
                   "key_custody_confirmation_sha256": key_custody_sha256,
                   "originals_deleted": 0, "remote_objects_deleted": 0}
        catalog._write_record(attempt / "claim.json", {**binding, "status": "CLAIMED"})
        try:
            copied = catalog.import_locations(
                entry_path=entry_path, entry_sha256=digest, local_source_root=root,
                admission=admission, deadline_monotonic=deadline_monotonic)
            restored = catalog.publish_restore(
                entry_path=copied["entry_path"], entry_sha256=digest,
                transport_receipt=transport_receipt, transport_receipt_sha256=transport_receipt_sha256,
                restore_receipt=restore_receipt, restore_receipt_sha256=restore_receipt_sha256,
                admission=admission, deadline_monotonic=deadline_monotonic)
            locations.read_record(copied["entry_path"], digest)
            locations.read_record(restored["record_path"], restored["record_sha256"])
            catalog._guard(admission, deadline_monotonic)
            verified = {
                "catalog_entry": {"path": copied["entry_path"], "sha256": digest},
                "restore_record": {"path": restored["record_path"], "sha256": restored["record_sha256"]}}
            custody_path = attempt / "custody.json"
            _, custody_sha = catalog._write_record(custody_path, {
                "schema_version": schema_version("cold_archive_custody"), "status": "PASS",
                "entry_sha256": digest, "restore_record_sha256": restored["record_sha256"],
                "backup_execution_host_id": backup_host_id, "verified_backups": verified,
                "recovery_key_custody": key, "key_custody_confirmation_sha256": key_custody_sha256,
                "verified_at_utc": datetime.now(timezone.utc).isoformat()})
            inventory = catalog.write_inventory(source_root=root, admission=admission,
                                                deadline_monotonic=deadline_monotonic)
            catalog._guard(admission, deadline_monotonic)
            result, result_sha = catalog._write_record(attempt / "receipt.json", {
                **binding, "status": "PUBLISHED_RECOVERY", **verified,
                "custody_record": {"path": str(custody_path), "sha256": custody_sha},
                "inventory": inventory, "completed_at_utc": datetime.now(timezone.utc).isoformat()})
            return {**result, "receipt_path": str(attempt / "receipt.json"), "receipt_sha256": result_sha}
        except BaseException as exc:
            catalog._write_record(attempt / "failure.json", {
                **binding, "status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__})
            raise


def run_publication(args):
    if os.name != "nt" or os.environ.get(bridge.stage.WRAPPER_ENV) != "1":
        raise ValueError("recovery publication requires the native workstation wrapper")
    root = repo_path()
    deadline = time.monotonic() + 60
    with ExitStack() as stack:
        assignment_path = root / execution_host.EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
        stack.enter_context(bridge._file_pin(locations.safe_path(assignment_path)))
        catalog._require(assignment_path.stat().st_size <= 16384, "host assignment exceeds bound")
        assignment_digest = hashlib.sha256(assignment_path.read_bytes()).hexdigest()
        assignment, _ = catalog._proof(assignment_path, assignment_digest)
        backup_host = execution_host.current_execution_host_id()
        principal = execution_host.current_execution_principal_id()
        catalog._require(assignment.get("schema_version") == execution_host.EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION
                         and assignment.get("assignment_status") == "ASSIGNED"
                         and assignment.get("active_portable_execution_host_id") == backup_host
                         and assignment.get("active_portable_execution_principal_id") == principal
                         and assignment.get("dedicated_capture_execution_host_id") != backup_host,
                         "recovery publication is restricted to the assigned non-capture workstation")
        def guard():
            catalog._require(os.environ.get(bridge.stage.WRAPPER_ENV) == "1"
                             and time.monotonic() < deadline,
                             "recovery publication wrapper or deadline ended")
            catalog._proof(assignment_path, assignment_digest)
            return True
        return publish_recovery(**vars(args), repo_root=root, backup_host_id=backup_host,
                                admission=guard, deadline_monotonic=deadline)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("entry_path", "entry_sha256", "transport_receipt", "transport_receipt_sha256",
                  "restore_receipt", "restore_receipt_sha256", "key_custody", "key_custody_sha256",
                  "recovery_data_root", "attempt_id"):
        parser.add_argument("--" + field.replace("_", "-"), required=True)
    args = parser.parse_args(argv)
    try:
        result = run_publication(args)
    except Exception as exc:
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({key: result[key] for key in
                      ("status", "catalog_entry", "restore_record", "custody_record", "receipt_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
