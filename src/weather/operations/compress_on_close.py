"""Bounded CLOB token NTFS compression after market-local close and writer release.

Run with cold_snapshot_compression_run.ps1 -CompressOnClose. Reuses the
handle-bound retained-byte verifier; never renames or removes a source file.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from functools import partial
import hashlib
import os
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

from weather.io import acquire_writer_lock, release_writer_lock
from weather.market.market_registry import spec_for_slug
from weather.operations import cold_snapshot_compression as cold
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.ntfs_file_compression import LockedNtfsFile, MIB, PinnedNtfsDirectory
from weather.paths import repo_path
from weather.schema_registry import schema_version

MAX_FILE_BYTES = 256 * MIB
MAX_BATCH_BYTES = 1024 * MIB
MAX_FOLDERS = 10000
QUIET_SECONDS = 7200
LARGE_OPENER = partial(LockedNtfsFile, max_file_bytes=MAX_FILE_BYTES)


def validate_policy(policy, root, now):
    fields = {"schema_version", "production_repo_root", "execution_host_id", "approved_by",
              "approved_at_utc", "expires_at_utc", "operation", "max_bytes"}
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError("exact compress-on-close policy required")
    if policy["schema_version"] != schema_version("compress_on_close_policy"):
        raise ValueError("unsupported compress-on-close policy")
    if Path(policy["production_repo_root"]) != root or policy["operation"] != "compress_and_retain":
        raise ValueError("policy root or operation mismatch")
    if not isinstance(policy["execution_host_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", policy["execution_host_id"]):
        raise ValueError("exact execution host required")
    if not isinstance(policy["approved_by"], str) or not 0 < len(policy["approved_by"].strip()) <= 128:
        raise ValueError("named owner approval required")
    approved, expires = cold._utc(policy["approved_at_utc"]), cold._utc(policy["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(days=31):
        raise ValueError("policy expired, future or overlong")
    if type(policy["max_bytes"]) is not int or not 0 < policy["max_bytes"] <= MAX_BATCH_BYTES:
        raise ValueError("batch budget must be positive and at most one GiB")
    return policy["max_bytes"]


def closed(folder, now):
    spec = spec_for_slug(folder.name)
    return bool(spec and inventory.EVENT.fullmatch(folder.name)
                and inventory.event_date(folder.name) < now.astimezone(ZoneInfo(spec.timezone)).date())


def eligible(info, now):
    return (0 < info.st_size <= MAX_FILE_BYTES
            and now.timestamp() - info.st_mtime >= QUIET_SECONDS
            and not getattr(info, "st_file_attributes", 0) & ~(0x20 | 0x80))


def candidates(data_root, now, guard):
    snapshots = inventory.validate_root(data_root / "snapshots")
    folders = []
    with PinnedNtfsDirectory(snapshots), os.scandir(snapshots) as entries:
        for index, entry in enumerate(entries):
            guard()
            if index >= MAX_FOLDERS:
                raise ValueError("snapshot folder bound exceeded")
            folder = Path(entry.path)
            if closed(folder, now):
                inventory.checked_stat(folder, directory=True)
                folders.append(folder)
    # Largest growth first across the whole selection, CSV only afterwards.
    for name in ("clob_tokens.jsonl", "clob_tokens.csv"):
        for folder in sorted(folders):
            guard()
            path = folder / name
            if path.exists() and eligible(inventory.checked_stat(path, directory=False), now):
                yield path


def compress_released(path, root, *, now, remaining, apply, guard, journal,
                      opener=LARGE_OPENER):
    guard()
    if path.name not in {"clob_tokens.jsonl", "clob_tokens.csv"} or not closed(path.parent, now):
        raise ValueError("not an exact closed token tape")
    lock = acquire_writer_lock(path.parent / "clob_raw_tape", attempts=1,
                               owner={"operation": "compress_on_close"})
    if lock is None:
        raise ValueError("CLOB writer has not released the event day")
    try:
        # Handle ownership and metadata are checked again by compress_candidate.
        info = inventory.checked_stat(path, directory=False)
        if not eligible(info, now) or info.st_size > remaining:
            raise ValueError("candidate changed, not quiet, or exceeds remaining budget")
        allocated = inventory.native_allocation(path, info)
        row = {"path": path.relative_to(root / "data").as_posix(), "size_bytes": info.st_size,
               "mtime_ns": str(info.st_mtime_ns), "device": str(info.st_dev),
               "file_id": str(info.st_ino), "attributes": info.st_file_attributes,
               "allocated_bytes": allocated}
        result = cold.compress_candidate(path, row, apply=apply, guard=guard,
                                         journal=journal, opener=opener)
        return result, info.st_size
    finally:
        release_writer_lock(lock)


def run(args):
    root = inventory.validate_root(Path(args.production_repo_root))
    output = inventory.validate_root(Path(args.output_root))
    if output.parent != root / "scratch" / cold.WORKLOAD or any(output.iterdir()):
        raise ValueError("output must be a new empty wrapper attempt")
    policy, raw = cold.read_bounded_json(Path(args.request), cold.MAX_REQUEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("policy hash mismatch")
    now = datetime.now(timezone.utc)
    budget = validate_policy(policy, root, now)
    if (str(repo_path()) != os.environ.get(cold.ENV_PREFIX + "SOURCE_ROOT")
            or not Path(__file__).resolve().is_relative_to(repo_path() / "src/weather")):
        raise ValueError("wrapper source binding mismatch")
    if os.environ.get(cold.ENV_PREFIX + "OWNER_APPROVED_EXCEPTION"):
        raise ValueError("compress-on-close has no daytime exception")
    lease_path = root / "data/logs/heavy_workload.lock"
    lease, _ = cold.read_bounded_json(lease_path, 16384)
    owner = int(os.environ.get(cold.ENV_PREFIX + "OWNER_PID", "0"))
    if lease.get("execution_host_id") != policy["execution_host_id"]:
        raise ValueError("policy host differs from lease")
    deadline = cold._utc(os.environ[cold.ENV_PREFIX + "DEADLINE_UTC"])
    if not 0 < (deadline - now).total_seconds() <= 600:
        raise ValueError("missing or overlong wrapper deadline")
    cold.set_current_process_below_normal()
    checked = 0.0
    def guard():
        nonlocal checked
        current = datetime.now(timezone.utc)
        local = current.astimezone(ZoneInfo("America/Toronto"))
        minute = local.hour * 60 + local.minute
        if (current >= deadline or current >= cold._utc(policy["expires_at_utc"])
                or not 30 <= minute < 540 or 285 <= minute < 405):
            raise ValueError("deadline, approval or compression window ended")
        if time.monotonic() - checked >= 1:
            cold.verify_current_lease(lease, owner, lease_path, workload=cold.WORKLOAD)
            admission = cold.observe_capture_admission(root, cold.check_resources)
            if admission["status"] != "PASS" or admission["free_disk_bytes"] < 50 * 1024**3:
                raise ValueError("capture resources or 50 GiB disk floor refused")
            checked = time.monotonic()
    receipt = {"schema_version": schema_version("compress_on_close_receipt"),
               "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
               "execution_host_id": policy["execution_host_id"], "owner_approved_exception": "",
               "apply": args.apply, "deleted_files": 0, "cleanup_eligible": False,
               "reclaimed_bytes": 0, "logical_bytes_processed": 0, "results": [],
               "status": "FAILED_RETAIN_AND_INSPECT"}
    with PinnedNtfsDirectory(output):
        cold.write_receipt_bytes(output / "request.json", raw)
        try:
            for index, path in enumerate(candidates(root / "data", now, guard)):
                if index >= 32 or receipt["logical_bytes_processed"] >= budget:
                    break
                remaining = budget - receipt["logical_bytes_processed"]
                if path.stat().st_size > remaining:
                    continue
                def journal(phase, row, index=index):
                    cold.write_receipt(output / f"{index:03d}-{phase}.json", {**receipt, **row})
                result, amount = compress_released(path, root, now=now, remaining=remaining,
                    apply=args.apply, guard=guard, journal=journal)
                receipt["results"].append(result)
                receipt["logical_bytes_processed"] += amount
                receipt["reclaimed_bytes"] += result["reclaimed_bytes"]
            guard()
            receipt["status"] = "PASS"
        except Exception as exc:
            receipt["error"] = str(exc)
        cold.write_receipt(output / "result.json", receipt)
    return 0 if receipt["status"] == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--apply", action="store_true")
    try:
        return run(parser.parse_args(argv))
    except Exception as exc:
        print(f"REFUSED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
