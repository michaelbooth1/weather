"""Attended metadata-only inventory under an expiring capture-host request.

Use storage_recovery_inventory_run.ps1. This command neither opens source
payloads nor issues archive, compression, deletion or cleanup authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.operations.replay_cache_compression import (
    _utc, read_bounded_json, write_receipt,
)
from weather.operations.replay_cache_compression_admission import (
    check_capture_health, observe_capture_admission,
    set_current_process_below_normal, verify_current_lease,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version

MAX_REQUEST_BYTES = 32768
# No source staging or payload reads. Reserve 8 GiB for concurrent capture,
# plus the bounded inventory and two MiB for all other attempt evidence.
MIN_FREE_DISK_BYTES = 8 * 1024**3 + metadata.MAX_OUTPUT_BYTES + 2 * metadata.MIB
WORKLOAD = "storage_recovery_inventory"
ENV_PREFIX = "WEATHER_STORAGE_INVENTORY_"


def check_resources(*, now, available, commit, free_disk, loops):
    result = check_capture_health(now=now, available=available, commit=commit, loops=loops)
    result.update(free_disk_bytes=free_disk, minimum_free_disk_bytes=MIN_FREE_DISK_BYTES)
    if type(free_disk) is not int or free_disk < MIN_FREE_DISK_BYTES:
        result["reasons"].append("inventory_disk_reservation_unmet")
        result["status"] = "BLOCK"
    return result


def validate_request(payload, *, production_root, now):
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "production_repo_root", "execution_host_id", "operation",
        "approved_by", "approved_at_utc", "expires_at_utc", "folders",
    }:
        raise ValueError("request fields must match the exact inventory contract")
    if payload["schema_version"] != schema_version("storage_recovery_inventory_request"):
        raise ValueError("unsupported inventory request")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("production repository binding mismatch")
    if (payload["operation"] != "metadata_only"
            or not isinstance(payload["approved_by"], str)
            or not 0 < len(payload["approved_by"].strip()) <= 128):
        raise ValueError("metadata-only request requires named approval")
    if not isinstance(payload["execution_host_id"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", payload["execution_host_id"]):
        raise ValueError("exact production host identity required")
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("inventory request is expired, future-dated or overlong")
    metadata.validate_folders(payload["folders"], as_of=now.astimezone(
        ZoneInfo("America/Toronto")).date())
    return payload["folders"]


def validate_output(output, production_root):
    output = metadata.validate_root(output)
    parent = production_root / "scratch" / "storage_recovery_inventory"
    if not output.is_relative_to(parent) or output.parent != parent:
        raise ValueError("output must be one unique child of scratch/storage_recovery_inventory")
    if any(output.iterdir()):
        raise FileExistsError("spent output attempt; retain all existing evidence")


def write_inventory(path, value):
    # Bound the final serialization, including summaries, before touching disk.
    raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(raw) > metadata.MAX_OUTPUT_BYTES:
        raise ValueError("serialized inventory exceeds the hard output bound")
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest(), len(raw)


def run(args):
    if os.name != "nt":
        raise ValueError("production inventory requires native Windows")
    production_root = metadata.validate_root(Path(args.production_repo_root))
    output = Path(args.output_root)
    if not Path(args.request).is_absolute():
        raise ValueError("request must be absolute")
    for value, pattern in ((args.request_sha256, r"[0-9a-f]{64}"),
                           (args.source_git_sha, r"[0-9a-f]{40}")):
        if not re.fullmatch(pattern, value):
            raise ValueError("invalid source or request digest")
    validate_output(output, production_root)
    with PinnedNtfsDirectory(output):
        try:
            return run_pinned(args, production_root, output)
        except Exception as exc:
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RETAIN_AND_INSPECT", "error": str(exc),
                "source_git_sha": args.source_git_sha,
                "request_sha256": args.request_sha256,
                "deleted_files": 0, "reclaimed_bytes": 0, "cleanup_eligible": False,
            })
            raise


def run_pinned(args, production_root, output):
    request_path = Path(args.request)
    metadata.validate_root(request_path.parent)
    metadata.checked_stat(request_path, directory=False)
    request, raw = read_bounded_json(request_path, MAX_REQUEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("request SHA-256 mismatch")
    now = datetime.now(timezone.utc)
    folders = validate_request(request, production_root=production_root, now=now)
    source = repo_path()
    if str(source) != os.environ.get(ENV_PREFIX + "SOURCE_ROOT"):
        raise ValueError("Python imports are not bound to the wrapper source")
    for module_file in (__file__, metadata.__file__):
        if not Path(module_file).resolve().is_relative_to(source / "src" / "weather"):
            raise ValueError("inventory module import escaped the wrapper source")
    owner_pid = int(os.environ.get(ENV_PREFIX + "OWNER_PID", "0"))
    lease_path = production_root / "data" / "logs" / "heavy_workload.lock"
    lease, _ = read_bounded_json(lease_path, 16384)
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("request does not bind the actual lease host")
    verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
    set_current_process_below_normal()
    deadline = _utc(os.environ[ENV_PREFIX + "DEADLINE_UTC"])
    if not 0 < (deadline - now).total_seconds() <= 150:
        raise ValueError("wrapper deadline is missing or outside its hard interval")
    last_check, admission = 0.0, {}

    def guard(force=False):
        nonlocal last_check, admission
        current = datetime.now(timezone.utc)
        if current >= deadline or current >= _utc(request["expires_at_utc"]):
            raise metadata.InventoryRefused("inventory deadline or request expiry reached")
        if force or time.monotonic() - last_check >= 1:
            admission = observe_capture_admission(production_root, check_resources)
            last_check = time.monotonic()
            if admission["status"] != "PASS":
                raise metadata.InventoryRefused("capture admission refused: " + ",".join(admission["reasons"]))

    guard(force=True)
    write_receipt(output / "request.json", request)
    with PinnedNtfsDirectory(production_root / "data"):
        result = metadata.inventory(production_root / "data", folders,
                                    as_of=now.astimezone(ZoneInfo("America/Toronto")).date(),
                                    guard=guard)
    # Expiry, capture failure or drift after the last row invalidates the batch.
    guard(force=True)
    verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
    result.update(request_sha256=args.request_sha256, source_git_sha=args.source_git_sha,
                  execution_host_id=request["execution_host_id"],
                  module_file=str(Path(metadata.__file__).resolve()))
    digest, size = write_inventory(output / "inventory.json", result)
    receipt = {
        "schema_version": schema_version("storage_recovery_inventory_receipt"),
        "status": result["status"], "request_sha256": args.request_sha256,
        "source_git_sha": args.source_git_sha, "execution_host_id": request["execution_host_id"],
        "inventory_sha256": digest, "inventory_bytes": size,
        "complete_folder_allocated_bytes": result["complete_folder_allocated_bytes"],
        "payload_bytes_read": 0, "source_files_changed": 0, "deleted_files": 0,
        "reclaimed_bytes": 0, "cleanup_eligible": False, "final_admission": admission,
    }
    write_receipt(output / "result.json", receipt)
    print(json.dumps({key: receipt[key] for key in (
        "status", "complete_folder_allocated_bytes", "reclaimed_bytes", "cleanup_eligible")}))
    return 0 if result["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
