"""Lossless NTFS compression of exact, inventoried cold snapshot files.

All source paths and logical bytes are retained. No archive or cleanup
authority is issued. Run through cold_snapshot_compression_run.ps1.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from zoneinfo import ZoneInfo

from weather.operations import storage_recovery_inventory as inventory
from weather.operations.ntfs_file_compression import (
    LockedNtfsFile, MAX_FILE_BYTES, MIB, PinnedNtfsDirectory,
)
from weather.operations.replay_cache_compression import _utc, read_bounded_json, IDENTITY_FIELDS
from weather.operations.replay_cache_compression_admission import (
    check_capture_health, observe_capture_admission, set_current_process_below_normal,
    verify_current_lease, verify_storage_exception,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version

MAX_FILES = 256
MAX_BATCH_BYTES = 1024 * MIB
MAX_REQUEST_BYTES = 128 * 1024
MAX_RECEIPT_BYTES = 2 * MIB
MAX_IO_BYTES_PER_SECOND = 16 * MIB
# Two possible 64 MiB file images plus 8 MiB of attempt evidence.
# The reservation is specific to sequential compress-and-retain; no staging.
MIN_FREE_DISK_BYTES = 8 * 1024**3 + 2 * MAX_FILE_BYTES + 8 * MIB
WORKLOAD = "cold_snapshot_compression"
ENV_PREFIX = "WEATHER_COLD_SNAPSHOT_COMPRESSION_"


def check_resources(*, now, available, commit, free_disk, loops, owner_approved_exception=""):
    result = check_capture_health(now=now, available=available, commit=commit, loops=loops,
                                  owner_approved_exception=owner_approved_exception)
    result.update(free_disk_bytes=free_disk, minimum_free_disk_bytes=MIN_FREE_DISK_BYTES)
    if type(free_disk) is not int or free_disk < MIN_FREE_DISK_BYTES:
        result["reasons"].append("cold_snapshot_compression_disk_reservation_unmet")
        result["status"] = "BLOCK"
    return result


def validate_request(payload, *, production_root, now):
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "production_repo_root", "execution_host_id", "operation",
        "approved_by", "approved_at_utc", "expires_at_utc", "files",
        "inventory_wrapper_receipt", "inventory_wrapper_sha256",
    }:
        raise ValueError("request fields must match the exact cold snapshot contract")
    if payload["schema_version"] != schema_version("cold_snapshot_compression_request"):
        raise ValueError("unsupported cold snapshot request")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("production repository binding mismatch")
    if (payload["operation"] != "compress_and_retain"
            or not isinstance(payload["approved_by"], str)
            or not 0 < len(payload["approved_by"].strip()) <= 128):
        raise ValueError("explicit compress-and-retain approval is required")
    for key in ("execution_host_id", "inventory_wrapper_sha256"):
        if not isinstance(payload[key], str) or not re.fullmatch(r"[0-9a-f]{64}", payload[key]):
            raise ValueError("exact host and inventory receipt identities required")
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("request is expired, future-dated or overlong")
    candidates = payload["files"]
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_FILES:
        raise ValueError("request must name one to 256 exact files")
    seen, total = set(), 0
    as_of = now.astimezone(ZoneInfo("America/Toronto")).date()
    for row in candidates:
        if not isinstance(row, dict) or set(row) != {
            "path", "size_bytes", "mtime_ns", "device", "file_id", "allocated_bytes", "attributes",
        }:
            raise ValueError("candidate must be an exact inventory file record")
        relative = row["path"]
        if not isinstance(relative, str) or any(c in relative for c in ("\\", ":", "\x00")):
            raise ValueError("noncanonical source path")
        parts = PurePosixPath(relative).parts
        if (len(parts) < 3 or parts[0] != "snapshots"
                or PurePosixPath(relative).as_posix() != relative
                or any(part.startswith(".") for part in parts)
                or PurePosixPath(relative).suffix not in {".json", ".jsonl", ".csv"}):
            raise ValueError("only ordinary cold snapshot JSON, JSONL or CSV files are eligible")
        inventory.validate_folders(["/".join(parts[:2])], as_of=as_of)
        if relative.casefold() in seen:
            raise ValueError("duplicate candidate path")
        seen.add(relative.casefold())
        if type(row["size_bytes"]) is not int or not 0 < row["size_bytes"] <= MAX_FILE_BYTES:
            raise ValueError("candidate exceeds the 64 MiB file bound")
        if type(row["allocated_bytes"]) is not int or row["allocated_bytes"] <= 0:
            raise ValueError("candidate lacks positive physical allocation")
        if type(row["attributes"]) is not int or row["attributes"] & ~(0x20 | 0x80):
            raise ValueError("candidate is already compressed or has unsupported attributes")
        for key in ("mtime_ns", "device", "file_id"):
            if not isinstance(row[key], str) or not re.fullmatch(r"[0-9]{1,24}", row[key]):
                raise ValueError("native identity must use exact decimal strings")
        modified = datetime.fromtimestamp(int(row["mtime_ns"]) / 1_000_000_000, timezone.utc)
        if now - modified < timedelta(days=30):
            raise ValueError("file has not been unchanged for thirty days")
        total += row["size_bytes"]
    if total > MAX_BATCH_BYTES:
        raise ValueError("request exceeds the one GiB batch bound")
    return candidates


def write_receipt(path, payload):
    raw = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt exceeds its hard bound")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _read_receipt(path, expected_hash, maximum=MAX_RECEIPT_BYTES):
    inventory.validate_root(path.parent)
    inventory.checked_stat(path, directory=False)
    payload, raw = read_bounded_json(path, maximum)
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("inventory receipt hash mismatch")
    return payload


def read_inventory(request, candidates, *, production_root, source_git_sha):
    path = Path(request["inventory_wrapper_receipt"])
    parent = production_root / "scratch" / "storage_recovery_inventory"
    if not path.is_absolute() or path.parent.parent != parent or path.name != "wrapper-result.json":
        raise ValueError("inventory wrapper must be one exact completed production attempt")
    with PinnedNtfsDirectory(path.parent):
        wrapper = _read_receipt(path, request["inventory_wrapper_sha256"])
        if (wrapper.get("status") != "PASS" or wrapper.get("hard_stop") is not False
                or wrapper.get("teardown_proved") is not True
                or wrapper.get("source_git_sha") != source_git_sha
                or wrapper.get("execution_host_id") != request["execution_host_id"]
                or wrapper.get("deleted_files") != 0 or wrapper.get("reclaimed_bytes") != 0
                or wrapper.get("cleanup_eligible") is not False):
            raise ValueError("inventory wrapper is incomplete, failed or differently bound")
        result = _read_receipt(path.parent / "result.json", wrapper["child_result_sha256"])
        if (result.get("status") != "PASS" or result.get("source_git_sha") != source_git_sha
                or result.get("request_sha256") != wrapper.get("request_sha256")
                or result.get("execution_host_id") != request["execution_host_id"]
                or result.get("cleanup_eligible") is not False):
            raise ValueError("inventory result is not a matching PASS")
        manifest = _read_receipt(path.parent / "inventory.json", result["inventory_sha256"],
                                 inventory.MAX_OUTPUT_BYTES)
    if (manifest.get("schema_version") != schema_version("storage_recovery_inventory")
            or manifest.get("status") != "PASS" or manifest.get("source_git_sha") != source_git_sha
            or manifest.get("request_sha256") != wrapper.get("request_sha256")
            or manifest.get("execution_host_id") != request["execution_host_id"]
            or Path(manifest.get("data_root", "")) != production_root / "data"
            or manifest.get("cleanup_eligible") is not False):
        raise ValueError("inventory manifest is not a matching PASS")
    complete = {row["path"] for row in manifest["folders"] if row.get("status") == "COMPLETE"}
    rows = manifest["files"]
    indexed = {row["path"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("inventory has duplicate file rows")
    for candidate in candidates:
        folder = "/".join(PurePosixPath(candidate["path"]).parts[:2])
        if folder not in complete or indexed.get(candidate["path"]) != candidate:
            raise ValueError("candidate is absent, incomplete or changed from the inventory")
    return manifest


def compress_candidate(path, expected, *, apply, guard, journal, opener=LockedNtfsFile,
                       bytes_per_second=MAX_IO_BYTES_PER_SECOND):
    """Pin one original, journal its preimage, then verify the retained result."""
    guard()
    with opener(path, writable=apply) as opened:
        before = opened.metadata()
        expected_native = {
            "size_bytes": expected["size_bytes"], "mtime_ns": int(expected["mtime_ns"]),
            "volume_serial": int(expected["device"]), "file_index": int(expected["file_id"]),
            "allocation_bytes": expected["allocated_bytes"], "attributes": expected["attributes"],
        }
        if any(before[key] != value for key, value in expected_native.items()):
            raise ValueError("candidate native identity changed since inventory")
        if before["compression_format"] != 0:
            raise ValueError("candidate is already compressed")
        # A dry run validates native metadata and writer exclusion without reading
        # payloads. Apply binds its own durable preimage while this handle is held.
        if not apply:
            return {"path": expected["path"], "before": before, "status": "PLANNED",
                    "reclaimed_bytes": 0}
        digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        if opened.metadata() != before:
            raise ValueError("candidate drifted while its preimage was read")
        preimage = {"path": expected["path"], "before": before, "sha256": digest,
                    "action": "COMPRESS_AND_RETAIN"}
        journal("before", preimage)
        guard()
        opened.compress()
        after_digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        after = opened.metadata()
        if (digest != after_digest or after["compression_format"] != 2
                or any(before[key] != after[key] for key in IDENTITY_FIELDS)):
            raise ValueError("post-compression content or native identity mismatch")
        result = {**preimage, "after": after, "status": "VERIFIED",
                  "reclaimed_bytes": before["allocation_bytes"] - after["allocation_bytes"]}
        journal("after", result)
        if result["reclaimed_bytes"] <= 0:
            raise ValueError("no positive allocated-byte savings; stop before expanding")
        return result


def run(args):
    if os.name != "nt":
        raise ValueError("cold snapshot compression requires native Windows")
    production_root = inventory.validate_root(Path(args.production_repo_root))
    output = inventory.validate_root(Path(args.output_root))
    if output.parent != production_root / "scratch" / WORKLOAD or any(output.iterdir()):
        raise ValueError("output must be a new direct child of scratch/cold_snapshot_compression")
    with PinnedNtfsDirectory(output):
        try:
            return run_pinned(args, production_root, output)
        except Exception as exc:
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RETAIN_AND_INSPECT", "error": str(exc),
                "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
                "deleted_files": 0, "cleanup_eligible": False,
            })
            raise


def run_pinned(args, production_root, output):
    request_path = Path(args.request)
    inventory.validate_root(request_path.parent)
    inventory.checked_stat(request_path, directory=False)
    request, raw = read_bounded_json(request_path, MAX_REQUEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("request SHA-256 mismatch")
    now = datetime.now(timezone.utc)
    candidates = validate_request(request, production_root=production_root, now=now)
    source = repo_path()
    if str(source) != os.environ.get(ENV_PREFIX + "SOURCE_ROOT"):
        raise ValueError("Python imports are not bound to the wrapper source")
    if not Path(__file__).resolve().is_relative_to(source / "src" / "weather"):
        raise ValueError("compression import escaped the wrapper source")
    lease_path = production_root / "data/logs/heavy_workload.lock"
    lease, _ = read_bounded_json(lease_path, 16384)
    owner_pid = int(os.environ.get(ENV_PREFIX + "OWNER_PID", "0"))
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("request does not bind the lease host")
    verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
    exception = os.environ.get(ENV_PREFIX + "OWNER_APPROVED_EXCEPTION", "")
    verify_storage_exception(lease, exception, now)
    set_current_process_below_normal()
    deadline = _utc(os.environ[ENV_PREFIX + "DEADLINE_UTC"])
    if not 0 < (deadline - now).total_seconds() <= 600:
        raise ValueError("wrapper deadline is missing or outside its hard interval")
    last_check, admission = 0.0, {}

    def guard(force=False):
        nonlocal last_check, admission
        current = datetime.now(timezone.utc)
        if current >= deadline or current >= _utc(request["expires_at_utc"]):
            raise ValueError("compression deadline or request expiry reached")
        if force or time.monotonic() - last_check >= 1:
            verify_storage_exception(lease, exception, current)
            admission = observe_capture_admission(
                production_root, lambda **observed: check_resources(
                    owner_approved_exception=exception, **observed))
            last_check = time.monotonic()
            if admission["status"] != "PASS":
                raise ValueError("capture admission refused: " + ",".join(admission["reasons"]))

    guard(force=True)
    read_inventory(request, candidates, production_root=production_root, source_git_sha=args.source_git_sha)
    write_receipt(output / "request.json", request)
    results = []
    receipt = {"schema_version": schema_version("cold_snapshot_compression_receipt"),
               "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
               "execution_host_id": request["execution_host_id"],
               "inventory_wrapper_sha256": request["inventory_wrapper_sha256"],
               "owner_approved_exception": exception,
               "apply": args.apply, "deleted_files": 0, "cleanup_eligible": False,
               "reclaimed_bytes": 0}
    try:
        for index, candidate in enumerate(candidates):
            def journal(phase, row, index=index):
                write_receipt(output / f"{index:03d}-{phase}.json", {**receipt, **row})
            guard(force=True)
            row = compress_candidate(production_root / "data" / candidate["path"], candidate,
                                     apply=args.apply, guard=guard, journal=journal)
            results.append(row)
        guard(force=True)
        verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
        receipt.update(status="PASS", results=results,
                       reclaimed_bytes=sum(row["reclaimed_bytes"] for row in results),
                       final_admission=admission)
        code = 0
    except Exception as exc:
        receipt.update(status="FAILED_RETAIN_AND_INSPECT", error=str(exc), results=results,
                       reclaimed_bytes=sum(row["reclaimed_bytes"] for row in results),
                       final_admission=admission)
        code = 1
    write_receipt(output / "result.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "reclaimed_bytes", "deleted_files")}))
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
