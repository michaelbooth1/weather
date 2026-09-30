"""Record the reviewed resolution of one failed nightly compression attempt.

A failed or unfinished nightly attempt blocks later automatic runs. This reads
only that attempt's retained receipts (never a source payload), proves every
started file has a VERIFIED equal-hash after-journal, and writes one create-only
resolution the scheduled runner accepts. It never deletes, renames, retries or
recompresses anything, and credits no savings to any nightly total.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from weather.operations import cold_snapshot_compression as cold
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.replay_cache_compression import IDENTITY_FIELDS
from weather.schema_registry import schema_version

RESOLUTION_DIR = "resolved-nightly"
ATTEMPT = re.compile(r"nightly-[0-9]{8}-[0-9A-Za-z-]{1,64}")
JOURNAL = re.compile(r"([0-9]{3})-(before|after)\.json")
MAX_BATCHES = 1024


def _receipt(path, maximum=cold.MAX_RECEIPT_BYTES):
    inventory.checked_stat(path, directory=False)
    payload, raw = cold.read_bounded_json(path, maximum)
    return payload, hashlib.sha256(raw).hexdigest()


def verify_batch(batch):
    """Every started file must be VERIFIED; return its per-file proof rows."""
    inventory.checked_stat(batch, directory=True)
    selection, _ = _receipt(batch / "selection.json")
    phases = {}
    for entry in batch.iterdir():
        match = JOURNAL.fullmatch(entry.name)
        if match:
            phases.setdefault(int(match.group(1)), {})[match.group(2)] = entry
        elif entry.name not in {"selection.json", "result.json"}:
            raise ValueError(f"unexpected file in {batch.name}: {entry.name}")
    if sorted(phases) != list(range(len(phases))) or len(phases) > len(selection["files"]):
        raise ValueError(f"{batch.name} journals are not a contiguous selection prefix")
    rows = []
    for ordinal in sorted(phases):
        if set(phases[ordinal]) != {"before", "after"}:
            raise ValueError(f"{batch.name}/{ordinal:03d} is unfinished; verify the retained file first")
        before, _ = _receipt(phases[ordinal]["before"])
        after, _ = _receipt(phases[ordinal]["after"])
        path = selection["files"][ordinal]["path"]
        if (before.get("path") != path or after.get("path") != path
                or before.get("action") != "COMPRESS_AND_RETAIN"
                or after.get("status") != "VERIFIED" or after.get("before") != before.get("before")
                or not re.fullmatch(r"[0-9a-f]{64}", before.get("sha256", ""))
                or after.get("sha256") != before["sha256"]
                or after["after"].get("compression_format") != 2
                or any(before["before"][key] != after["after"][key] for key in IDENTITY_FIELDS)
                or after.get("reclaimed_bytes") != (before["before"]["allocation_bytes"]
                                                    - after["after"]["allocation_bytes"])):
            raise ValueError(f"{batch.name}/{ordinal:03d} is not an equal-hash VERIFIED retained file")
        rows.append({"batch": batch.name, "ordinal": ordinal, "path": path, "sha256": before["sha256"],
                     "reclaimed_bytes": after["reclaimed_bytes"]})
    return rows


def resolve(root, name, approved_by, *, now=None):
    root = inventory.validate_root(Path(root))
    parent = inventory.validate_root(root / "scratch" / cold.WORKLOAD)
    if not isinstance(name, str) or not ATTEMPT.fullmatch(name):
        raise ValueError("attempt must be one exact nightly-YYYYMMDD-* directory name")
    if not isinstance(approved_by, str) or not 0 < len(approved_by.strip()) <= 128:
        raise ValueError("named reviewer required")
    attempt = inventory.validate_root(parent / name)
    wrapper, wrapper_sha256 = _receipt(attempt / "wrapper-result.json")
    if (wrapper.get("status") != "FAILED" or wrapper.get("teardown_proved") is not True
            or wrapper.get("hard_stop") is not False or wrapper.get("deleted_files") != 0
            or wrapper.get("cleanup_eligible") is not False):
        raise ValueError("only a torn-down FAILED attempt without a hard stop can be resolved here")
    result, result_sha256 = _receipt(attempt / "result.json")
    if (result.get("schema_version") != schema_version("cold_snapshot_nightly_receipt")
            or result.get("status") != "FAILED_RETAIN_AND_INSPECT"
            or result.get("source_git_sha") != wrapper.get("source_git_sha")
            or result.get("request_sha256") != wrapper.get("request_sha256")
            or result.get("apply") is not wrapper.get("apply")
            or result.get("deleted_files") != 0 or result.get("cleanup_eligible") is not False):
        raise ValueError("child result does not bind the failed wrapper attempt")
    batches = sorted(p for p in attempt.iterdir() if p.is_dir())
    if len(batches) > MAX_BATCHES or any(not re.fullmatch(r"batch-[0-9]{4}", p.name) for p in batches):
        raise ValueError("unexpected attempt directory layout")
    files = [row for batch in batches for row in verify_batch(batch)]
    if files and wrapper.get("apply") is not True:
        raise ValueError("a dry-run attempt cannot hold compression journals")
    target_dir = parent / RESOLUTION_DIR
    if not target_dir.exists():
        target_dir.mkdir()
    inventory.validate_root(target_dir)
    record = {
        "schema_version": schema_version("cold_snapshot_nightly_receipt"),
        "record": "failed_attempt_resolution", "status": "RESOLVED", "attempt": name,
        "wrapper_result_sha256": wrapper_sha256, "child_result_sha256": result_sha256,
        "source_git_sha": wrapper.get("source_git_sha"), "request_sha256": wrapper.get("request_sha256"),
        "execution_host_id": wrapper.get("execution_host_id"), "failure": result.get("error", ""),
        "approved_by": approved_by.strip(),
        "resolved_at_utc": (now or datetime.now(timezone.utc)).isoformat(),
        "files_verified": len(files), "files": files,
        # Reported for reconciliation only; never added to any nightly total.
        "verified_reclaimed_bytes": sum(row["reclaimed_bytes"] for row in files),
        "payload_bytes_read": 0, "source_files_changed": 0,
        "deleted_files": 0, "cleanup_eligible": False,
    }
    cold.write_receipt(target_dir / f"{name}.json", record)
    return record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-repo-root", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--approved-by", required=True)
    args = parser.parse_args(argv)
    try:
        record = resolve(args.production_repo_root, args.attempt, args.approved_by)
    except Exception as exc:
        print(f"REFUSED: {exc}")
        return 1
    print(json.dumps({key: record[key] for key in (
        "status", "attempt", "wrapper_result_sha256", "files_verified", "verified_reclaimed_bytes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
