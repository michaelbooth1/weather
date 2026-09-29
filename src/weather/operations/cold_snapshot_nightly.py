"""Budgeted nightly NTFS compress-and-retain through the capture-host wrapper.

Only immediate text files of built-in snapshot event folders are eligible.
No campaign, mm_runs, payload, ledger, archive or nested directory is traversed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from functools import partial
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
from zoneinfo import ZoneInfo

from weather.operations import cold_snapshot_compression as cold
from weather.operations import storage_recovery_inventory as inventory
from weather.operations.ntfs_file_compression import LockedNtfsFile, MIB, PinnedNtfsDirectory
from weather.paths import repo_path
from weather.schema_registry import schema_version

MAX_FILE_BYTES = 256 * MIB
MAX_NIGHT_BYTES = 32 * 1024 * MIB
MAX_EVENT_FOLDERS = 10000
MAX_FILES_PER_NIGHT = 8192
MAX_INVENTORY_BYTES = 64 * MIB
MIN_FREE_DISK_BYTES = 8 * 1024**3 + 2 * MAX_FILE_BYTES + 128 * MIB
LARGE_OPENER = partial(LockedNtfsFile, max_file_bytes=MAX_FILE_BYTES)


def validate_policy(policy, root, now):
    fields = {"schema_version", "production_repo_root", "execution_host_id", "operation",
              "approved_by", "approved_at_utc", "expires_at_utc", "nightly_budget_bytes"}
    if not isinstance(policy, dict) or set(policy) != fields:
        raise ValueError("nightly policy fields do not match the exact contract")
    if policy["schema_version"] != schema_version("cold_snapshot_nightly_policy"):
        raise ValueError("unsupported nightly policy")
    if Path(policy["production_repo_root"]) != root or policy["operation"] != "compress_and_retain":
        raise ValueError("nightly root or operation mismatch")
    if not isinstance(policy["execution_host_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", policy["execution_host_id"]):
        raise ValueError("exact capture host identity required")
    if not isinstance(policy["approved_by"], str) or not 0 < len(policy["approved_by"].strip()) <= 128:
        raise ValueError("named approval required")
    approved, expires = cold._utc(policy["approved_at_utc"]), cold._utc(policy["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(days=31):
        raise ValueError("nightly approval is expired, future or longer than 31 days")
    budget = policy["nightly_budget_bytes"]
    if type(budget) is not int or not 0 < budget <= MAX_NIGHT_BYTES:
        raise ValueError("nightly byte budget must be positive and at most 32 GiB")
    return budget


def closed_folders(data_root, as_of, guard):
    snapshots = inventory.validate_root(data_root / "snapshots")
    selected = []
    with PinnedNtfsDirectory(snapshots), os.scandir(snapshots) as entries:
        for index, entry in enumerate(entries):
            guard()
            if index >= MAX_EVENT_FOLDERS:
                raise ValueError("snapshot root entry bound exceeded")
            if not inventory.EVENT.fullmatch(entry.name):
                continue
            day = inventory.event_date(entry.name)
            if day >= as_of - timedelta(days=14):
                continue
            inventory.checked_stat(Path(entry.path), directory=True)
            selected.append((day, "snapshots/" + entry.name))
    return [name for _, name in sorted(selected)]


def eligible(row, *, now):
    parts = PurePosixPath(row["path"]).parts
    if (len(parts) != 3 or parts[0] != "snapshots" or parts[-1].startswith(".")
            or PurePosixPath(parts[-1]).suffix not in {".json", ".jsonl", ".csv"}):
        return False
    inventory.validate_folders(["/".join(parts[:2])],
        as_of=now.astimezone(ZoneInfo("America/Toronto")).date(), min_age_days=14)
    # Closed-day identity plus a full fourteen days without a write. A later
    # backfill is retained untouched until its own cold interval has elapsed.
    return (0 < row["size_bytes"] <= MAX_FILE_BYTES and row["allocated_bytes"] > 0
            and not row["attributes"] & ~(0x20 | 0x80)
            and now.timestamp() - int(row["mtime_ns"]) / 1e9 >= 14 * 86400)


def plan_batches(rows, remaining, *, now, remaining_files=MAX_FILES_PER_NIGHT):
    """Deterministic exact-file budgets; compressed files never count twice."""
    batch, size, used = [], 0, 0
    for row in sorted(rows, key=lambda row: row["path"]):
        if not eligible(row, now=now):
            continue
        amount = row["size_bytes"]
        if amount > remaining or used >= remaining_files:
            break
        if batch and (size + amount > cold.MAX_BATCH_BYTES or len(batch) >= cold.MAX_FILES):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += amount
        remaining -= amount
        used += 1
    if batch:
        yield batch


def execute_batch(rows, root, output, *, apply, guard, compress=cold.compress_candidate):
    results = []
    for index, row in enumerate(rows):
        guard()
        def journal(phase, record, index=index):
            cold.write_receipt(output / f"{index:03d}-{phase}.json", record)
        result = compress(root / "data" / row["path"], row, apply=apply, guard=guard,
                          journal=journal, opener=LARGE_OPENER)
        results.append(result)
    return results


def run(args):
    if os.name != "nt":
        raise ValueError("nightly compression requires native Windows")
    root = inventory.validate_root(Path(args.production_repo_root))
    output = inventory.validate_root(Path(args.output_root))
    if output.parent != root / "scratch" / cold.WORKLOAD or any(output.iterdir()):
        raise ValueError("nightly output must be a new empty compression attempt")
    inventory.validate_root(Path(args.request).parent)
    inventory.checked_stat(Path(args.request), directory=False)
    policy, raw = cold.read_bounded_json(Path(args.request), cold.MAX_REQUEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("nightly policy hash mismatch")
    now = datetime.now(timezone.utc)
    budget = validate_policy(policy, root, now)
    source = repo_path()
    if (str(source) != os.environ.get(cold.ENV_PREFIX + "SOURCE_ROOT")
            or not Path(__file__).resolve().is_relative_to(source / "src/weather")):
        raise ValueError("nightly import escaped the wrapper source")
    lease_path = root / "data/logs/heavy_workload.lock"
    lease, _ = cold.read_bounded_json(lease_path, 16384)
    owner = int(os.environ.get(cold.ENV_PREFIX + "OWNER_PID", "0"))
    if lease.get("execution_host_id") != policy["execution_host_id"]:
        raise ValueError("nightly policy does not bind the leased host")
    cold.verify_current_lease(lease, owner, lease_path, workload=cold.WORKLOAD)
    deadline = cold._utc(os.environ[cold.ENV_PREFIX + "DEADLINE_UTC"])
    if not 0 < (deadline - now).total_seconds() <= 15300:
        raise ValueError("nightly deadline is outside its hard bound")
    cold.set_current_process_below_normal()
    last_check = 0.0

    def guard():
        nonlocal last_check
        current = datetime.now(timezone.utc)
        local = current.astimezone(ZoneInfo("America/Toronto"))
        if (current >= deadline or current >= cold._utc(policy["expires_at_utc"])
                or not 30 <= local.hour * 60 + local.minute < 285):
            raise ValueError("nightly deadline, approval or 00:30-04:45 window ended")
        if time.monotonic() - last_check >= 1:
            def resources(**observed):
                result = cold.check_resources(**observed)
                if observed["free_disk"] < MIN_FREE_DISK_BYTES:
                    result["status"] = "BLOCK"
                    result["reasons"].append("large_file_disk_reservation_unmet")
                return result
            admission = cold.observe_capture_admission(root, resources)
            if admission["status"] != "PASS":
                raise ValueError("nightly capture admission refused: " + ",".join(admission["reasons"]))
            cold.verify_current_lease(lease, owner, lease_path, workload=cold.WORKLOAD)
            last_check = time.monotonic()

    receipt = {"schema_version": schema_version("cold_snapshot_nightly_receipt"),
        "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
        "execution_host_id": policy["execution_host_id"], "owner_approved_exception": "",
        "apply": args.apply, "deleted_files": 0, "cleanup_eligible": False,
        "reclaimed_bytes": 0, "logical_bytes_processed": 0, "files_processed": 0,
        "nightly_budget_bytes": budget, "batches": [], "status": "FAILED_RETAIN_AND_INSPECT"}
    with PinnedNtfsDirectory(output):
        cold.write_receipt_bytes(output / "request.json", raw, cold.MAX_REQUEST_BYTES)
        try:
            guard()
            as_of = now.astimezone(ZoneInfo("America/Toronto")).date()
            inventory_bytes = 0
            for number, folder in enumerate(closed_folders(root / "data", as_of, guard)):
                guard()
                if receipt["logical_bytes_processed"] >= budget or receipt["files_processed"] >= MAX_FILES_PER_NIGHT:
                    break
                manifest = inventory.inventory(root / "data", [folder], as_of=as_of, guard=guard,
                    traversal_scope="immediate_files", min_age_days=14)
                manifest.update(source_git_sha=args.source_git_sha, request_sha256=args.request_sha256,
                                execution_host_id=policy["execution_host_id"])
                manifest_path = output / f"inventory-{number:04d}.json"
                manifest_raw = (json.dumps(manifest, sort_keys=True) + "\n").encode()
                inventory_bytes += len(manifest_raw)
                if inventory_bytes > MAX_INVENTORY_BYTES:
                    raise ValueError("nightly inventory evidence budget exceeded")
                cold.write_receipt_bytes(manifest_path, manifest_raw, inventory.MAX_OUTPUT_BYTES)
                if manifest["status"] != "PASS":
                    raise ValueError("incomplete nightly inventory; retain and inspect")
                for rows in plan_batches(manifest["files"], budget - receipt["logical_bytes_processed"], now=now,
                                         remaining_files=MAX_FILES_PER_NIGHT - receipt["files_processed"]):
                    batch_path = output / f"batch-{len(receipt['batches']):04d}"
                    batch_path.mkdir()
                    selection = {"inventory": manifest_path.name,
                        "inventory_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(), "files": rows}
                    cold.write_receipt(batch_path / "selection.json", selection)
                    results = execute_batch(rows, root, batch_path, apply=args.apply, guard=guard)
                    cold.write_receipt(batch_path / "result.json", {"status": "PASS", "results": results})
                    logical = sum(row["size_bytes"] for row in rows)
                    saved = sum(row["reclaimed_bytes"] for row in results)
                    receipt["logical_bytes_processed"] += logical
                    receipt["files_processed"] += len(results)
                    receipt["reclaimed_bytes"] += saved
                    receipt["batches"].append({"path": batch_path.name, "files": len(results),
                                               "logical_bytes": logical, "verified_savings_bytes": saved})
            guard()
            receipt["status"] = "PASS"
        except Exception as exc:
            receipt["error"] = str(exc)
        cold.write_receipt(output / "result.json", receipt)
    print(json.dumps(receipt))
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
