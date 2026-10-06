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
# Owner decision 2026-09-30: a closed market-day is selectable once it is at
# least two local days old (strictly older than a one-day hot window) and each
# file has been unchanged for two days.
HOT_WINDOW_DAYS = 1
UNCHANGED_SECONDS = 2 * 86400
# NTFS cannot shrink a file that fits in one 4 KiB cluster (or is resident in
# its MFT record); such files are skipped at selection, never compressed.
CLUSTER_BYTES = 4096
# The capture loops atomically replace their status files. An admission read
# that lands inside a replace meets a delete-pending file (PermissionError) or,
# through the tolerant loop reader, an unreadable row (BLOCK). One fresh complete
# observation after a short pause decides; the admission criteria are unchanged.
ADMISSION_RETRY_SECONDS = 0.25
# Owner decision 2026-10-05: the nightly runs 06:50-09:00 America/Toronto, after
# the 04:45-06:45 tiering jobs, so 01:00-04:00 stays free for roll-sensitive merges.
WINDOW_START_MINUTE = 6 * 60 + 50
WINDOW_END_MINUTE = 9 * 60
# No new batch (at most 1 GiB, about 3.5 min at the 2026-10-02 rate) starts in the
# last SOFT_STOP_RESERVE_SECONDS before the child deadline: the night ends PASS with
# the work done, like the byte budget, instead of a deadline failure mid-file.
SOFT_STOP_RESERVE_SECONDS = 600
MAX_ADMISSION_NOTES = 32


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
    """Closed built-in event folders, oldest first.

    Root entries are classified by name only. Live status files, locks and hot
    event folders are never stat'ed or opened, so a producer replacing one cannot
    fail selection; only selected closed-day folders are checked, and an error on
    one of those refuses.
    """
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
            if day >= as_of - timedelta(days=HOT_WINDOW_DAYS):
                continue
            inventory.checked_stat(Path(entry.path), directory=True)
            selected.append((day, "snapshots/" + entry.name))
    return [name for _, name in sorted(selected)]


def observe_admission(root, resources, notes, *, observe=None, sleep=time.sleep):
    """Capture admission, re-observed once after a transient status-read race."""
    observe = observe or cold.observe_capture_admission
    try:
        admission = observe(root, resources)
        if admission["status"] == "PASS":
            return admission
        first = "BLOCK: " + ",".join(admission["reasons"])
    except PermissionError as exc:
        first = f"PermissionError: {exc}"
    notes["admission_retries"] += 1
    if len(notes["admission_retry_notes"]) < MAX_ADMISSION_NOTES:
        notes["admission_retry_notes"].append({
            "observed_at_utc": datetime.now(timezone.utc).isoformat(), "first_observation": first[:512]})
    sleep(ADMISSION_RETRY_SECONDS)
    return observe(root, resources)


def eligible(row, *, now):
    parts = PurePosixPath(row["path"]).parts
    if (len(parts) != 3 or parts[0] != "snapshots" or parts[-1].startswith(".")
            or PurePosixPath(parts[-1]).suffix not in {".json", ".jsonl", ".csv"}):
        return False
    inventory.validate_folders(["/".join(parts[:2])],
        as_of=now.astimezone(ZoneInfo("America/Toronto")).date(), min_age_days=HOT_WINDOW_DAYS)
    # Closed-day identity plus two full days without a write. A later
    # backfill is retained untouched until its own cold interval has elapsed.
    return (0 < row["size_bytes"] <= MAX_FILE_BYTES and row["allocated_bytes"] > 0
            and not row["attributes"] & ~(0x20 | 0x80)
            and now.timestamp() - int(row["mtime_ns"]) / 1e9 >= UNCHANGED_SECONDS)


def unshrinkable(row):
    """Reason an eligible file cannot reclaim a cluster, or None."""
    if row["size_bytes"] < CLUSTER_BYTES:
        return "logical_size_below_one_cluster"
    if row["allocated_bytes"] <= CLUSTER_BYTES:
        return "allocation_not_above_one_cluster"
    return None


def plan_batches(rows, remaining, *, now, remaining_files=MAX_FILES_PER_NIGHT, skipped=None):
    """Deterministic exact-file budgets; compressed files never count twice.

    Unshrinkable files are appended to ``skipped`` with a reason and consume no
    budget. Every selected file keeps the positive-savings stop rule.
    """
    batch, size, used = [], 0, 0
    for row in sorted(rows, key=lambda row: row["path"]):
        if not eligible(row, now=now):
            continue
        reason = unshrinkable(row)
        if reason:
            if skipped is not None:
                skipped.append({"path": row["path"], "size_bytes": row["size_bytes"],
                                "allocated_bytes": row["allocated_bytes"], "reason": reason})
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


def in_window(local: datetime) -> bool:
    """True inside the 06:50-09:00 America/Toronto nightly window."""
    return WINDOW_START_MINUTE <= local.hour * 60 + local.minute < WINDOW_END_MINUTE


def soft_stop_reached(now: datetime, deadline: datetime) -> bool:
    """True once a new batch could no longer finish before the child deadline."""
    return (deadline - now).total_seconds() < SOFT_STOP_RESERVE_SECONDS


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
                or not in_window(local)):
            raise ValueError("nightly deadline, approval or 06:50-09:00 window ended")
        if time.monotonic() - last_check >= 1:
            def resources(**observed):
                result = cold.check_resources(**observed)
                if observed["free_disk"] < MIN_FREE_DISK_BYTES:
                    result["status"] = "BLOCK"
                    result["reasons"].append("large_file_disk_reservation_unmet")
                return result
            admission = observe_admission(root, resources, receipt)
            if admission["status"] != "PASS":
                raise ValueError("nightly capture admission refused: " + ",".join(admission["reasons"]))
            cold.verify_current_lease(lease, owner, lease_path, workload=cold.WORKLOAD)
            last_check = time.monotonic()

    receipt = {"schema_version": schema_version("cold_snapshot_nightly_receipt"),
        "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
        "execution_host_id": policy["execution_host_id"], "owner_approved_exception": "",
        "apply": args.apply, "deleted_files": 0, "cleanup_eligible": False,
        "reclaimed_bytes": 0, "logical_bytes_processed": 0, "files_processed": 0,
        "files_skipped_unshrinkable": 0, "admission_retries": 0, "admission_retry_notes": [],
        "nightly_budget_bytes": budget, "batches": [], "stopped_at_soft_deadline": False,
        "status": "FAILED_RETAIN_AND_INSPECT"}
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
                if soft_stop_reached(datetime.now(timezone.utc), deadline):
                    receipt["stopped_at_soft_deadline"] = True
                    break
                manifest = inventory.inventory(root / "data", [folder], as_of=as_of, guard=guard,
                    traversal_scope="immediate_files", min_age_days=HOT_WINDOW_DAYS)
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
                manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                skipped = []
                batches = list(plan_batches(manifest["files"], budget - receipt["logical_bytes_processed"],
                    now=now, remaining_files=MAX_FILES_PER_NIGHT - receipt["files_processed"], skipped=skipped))
                if skipped:
                    skipped_raw = (json.dumps({"inventory": manifest_path.name, "inventory_sha256": manifest_sha256,
                                               "files": skipped}, sort_keys=True) + "\n").encode()
                    inventory_bytes += len(skipped_raw)
                    if inventory_bytes > MAX_INVENTORY_BYTES:
                        raise ValueError("nightly inventory evidence budget exceeded")
                    cold.write_receipt_bytes(output / f"skipped-{number:04d}.json", skipped_raw,
                                             inventory.MAX_OUTPUT_BYTES)
                    receipt["files_skipped_unshrinkable"] += len(skipped)
                for rows in batches:
                    if soft_stop_reached(datetime.now(timezone.utc), deadline):
                        receipt["stopped_at_soft_deadline"] = True
                        break
                    batch_path = output / f"batch-{len(receipt['batches']):04d}"
                    batch_path.mkdir()
                    selection = {"inventory": manifest_path.name, "inventory_sha256": manifest_sha256, "files": rows}
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
                if receipt.get("stopped_at_soft_deadline"):
                    break
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
