"""Prepare bounded cold-compression requests from completed metadata receipts.

This planner reads retained receipts only and never opens source payloads,
compresses files, deletes data, or launches a workload.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re

from weather.operations import cold_snapshot_compression as compression
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.schema_registry import schema_version

MAX_BATCHES = 8
MIN_CANDIDATE_BYTES = metadata.MIB


def pilot_files(path, expected_hash, *, production_root, source_git_sha, context):
    path = Path(path)
    if (not path.is_absolute() or path.name != "wrapper-result.json"
            or path.parent.parent != production_root / "scratch/cold_snapshot_compression"):
        raise ValueError("pilot must be one exact completed compression wrapper")
    with PinnedNtfsDirectory(path.parent):
        wrapper = compression._read_receipt(path, expected_hash)
        if (wrapper.get("status") != "PASS" or wrapper.get("apply") is not True
                or wrapper.get("teardown_proved") is not True or wrapper.get("hard_stop") is not False
                or wrapper.get("source_git_sha") != source_git_sha
                or wrapper.get("execution_host_id") != context["execution_host_id"]
                or wrapper.get("deleted_files") != 0 or wrapper.get("cleanup_eligible") is not False):
            raise ValueError("expansion requires a matching completed apply pilot")
        result = compression._read_receipt(path.parent / "result.json", wrapper["child_result_sha256"])
    if (result.get("status") != "PASS" or result.get("apply") is not True
            or result.get("source_git_sha") != source_git_sha
            or result.get("request_sha256") != wrapper.get("request_sha256")
            or result.get("execution_host_id") != context["execution_host_id"]
            or result.get("inventory_wrapper_sha256") != context["inventory_wrapper_sha256"]
            or result.get("deleted_files") != 0 or result.get("cleanup_eligible") is not False):
        raise ValueError("pilot result binding mismatch")
    rows = result.get("results")
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("expansion requires a single-file pilot")
    row = rows[0]
    before, after = row.get("before", {}), row.get("after", {})
    if (row.get("status") != "VERIFIED" or row.get("action") != "COMPRESS_AND_RETAIN"
            or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
            or before.get("compression_format") != 0 or after.get("compression_format") != 2
            or any(before.get(key) is None or before.get(key) != after.get(key)
                   for key in compression.IDENTITY_FIELDS)
            or type(row.get("reclaimed_bytes")) is not int or row["reclaimed_bytes"] <= 0
            or before.get("allocation_bytes", 0) - after.get("allocation_bytes", 0) != row["reclaimed_bytes"]
            or result.get("reclaimed_bytes") != row["reclaimed_bytes"]
            or wrapper.get("reclaimed_bytes") != row["reclaimed_bytes"]):
        raise ValueError("pilot lacks verified positive allocation savings")
    return [row["path"]]


def prepare(manifest, context, *, production_root, now, mode, start_index=0,
            max_batches=MAX_BATCHES, pilot_paths=()):
    if mode not in {"pilot", "expand"}:
        raise ValueError("unsupported planning mode")
    if type(start_index) is not int or start_index < 0:
        raise ValueError("start index must be a nonnegative integer")
    if type(max_batches) is not int or not 1 <= max_batches <= MAX_BATCHES:
        raise ValueError("one to eight batches per plan")
    if mode == "pilot" and (start_index or pilot_paths):
        raise ValueError("pilot starts at the first eligible file without predecessor paths")
    if mode == "expand" and len(pilot_paths) != 1:
        raise ValueError("expansion requires the validated single-file pilot path")
    scope = metadata.validate_scope(manifest.get("traversal_scope", "recursive"))
    complete = {row["path"] for row in manifest["folders"] if row["status"] == "COMPLETE"
                and row.get("traversal_scope", "recursive") == scope}
    eligible, excluded = [], Counter()
    for row in manifest["files"]:
        if scope == "immediate_files" and len(Path(row["path"]).as_posix().split("/")) != 3:
            excluded["outside_immediate_files_scope"] += 1
            continue
        folder = "/".join(Path(row["path"]).as_posix().split("/")[:2])
        if folder not in complete:
            excluded["incomplete_folder"] += 1
            continue
        if row["path"] in pilot_paths:
            excluded["already_compressed_pilot"] += 1
            continue
        try:
            compression.validate_request({**context, "files": [row]}, production_root=production_root, now=now)
            if row["size_bytes"] < MIN_CANDIDATE_BYTES:
                raise ValueError("under_one_MiB_planning_floor")
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            excluded[str(exc)] += 1
            continue
        eligible.append(row)
    eligible.sort(key=lambda row: (-row["allocated_bytes"], row["path"]))
    if len({row["path"] for row in eligible}) != len(eligible):
        raise ValueError("duplicate eligible inventory path")
    if mode == "expand" and any(path not in {r["path"] for r in manifest["files"]} for path in pilot_paths):
        raise ValueError("pilot path is outside this inventory")
    if start_index >= len(eligible):
        raise ValueError("no eligible candidates at the requested cursor")
    batches, cursor = [], start_index
    if mode == "pilot":
        batches, cursor = [[eligible[0]]], 1
    else:
        while cursor < len(eligible) and len(batches) < max_batches:
            rows, size = [], 0
            while cursor < len(eligible):
                row = eligible[cursor]
                if rows and (len(rows) >= compression.MAX_FILES
                             or size + row["size_bytes"] > compression.MAX_BATCH_BYTES):
                    break
                rows.append(row)
                size += row["size_bytes"]
                cursor += 1
            batches.append(rows)
    requests = [{**context, "files": rows} for rows in batches]
    for request in requests:
        compression.validate_request(request, production_root=production_root, now=now)
    return {"mode": mode, "start_index": start_index, "traversal_scope": scope,
            "next_index": cursor if mode == "expand" else 0,
            "has_more": cursor < len(eligible),
            "eligible_file_count": len(eligible),
            "eligible_allocated_bytes": sum(row["allocated_bytes"] for row in eligible),
            "selected_file_count": sum(len(rows) for rows in batches),
            "selected_allocated_bytes": sum(row["allocated_bytes"] for rows in batches for row in rows),
            "excluded_counts": dict(excluded), "requests": requests,
            "estimated_reclaimed_bytes": None, "reclaimed_bytes": 0, "cleanup_eligible": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("production-repo-root", "inventory-wrapper-receipt", "inventory-wrapper-sha256",
                 "source-git-sha", "execution-host-id", "approved-by", "expires-at-utc", "output-root"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--mode", choices=("pilot", "expand"), default="pilot")
    parser.add_argument("--pilot-wrapper-receipt")
    parser.add_argument("--pilot-wrapper-sha256")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--max-batches", type=int, default=MAX_BATCHES)
    args = parser.parse_args(argv)
    try:
        production_root = metadata.validate_root(Path(args.production_repo_root))
        output = Path(args.output_root)
        if (not output.is_absolute() or output.parent != production_root / "scratch/storage_recovery_plans"
                or output.exists() or output.is_symlink()):
            raise ValueError("output must be a new direct child of scratch/storage_recovery_plans")
        metadata.validate_root(output.parent)
        now = datetime.now(timezone.utc)
        if not re.fullmatch(r"[0-9a-f]{40}", args.source_git_sha):
            raise ValueError("exact reviewed source tip required")
        context = {"schema_version": schema_version("cold_snapshot_compression_request"),
                   "production_repo_root": str(production_root), "execution_host_id": args.execution_host_id,
                   "operation": "compress_and_retain", "approved_by": args.approved_by,
                   "approved_at_utc": now.isoformat(), "expires_at_utc": args.expires_at_utc,
                   "inventory_wrapper_receipt": args.inventory_wrapper_receipt,
                   "inventory_wrapper_sha256": args.inventory_wrapper_sha256}
        manifest = compression.read_inventory(context, [], production_root=production_root,
                                              source_git_sha=args.source_git_sha)
        pilot = []
        if args.mode == "expand":
            if not args.pilot_wrapper_receipt or not args.pilot_wrapper_sha256:
                raise ValueError("expansion requires an exact pilot receipt and SHA-256")
            pilot = pilot_files(args.pilot_wrapper_receipt, args.pilot_wrapper_sha256,
                                production_root=production_root, source_git_sha=args.source_git_sha,
                                context=context)
        elif args.pilot_wrapper_receipt or args.pilot_wrapper_sha256:
            raise ValueError("pilot mode does not consume a previous pilot")
        result = prepare(manifest, context, production_root=production_root, now=now, mode=args.mode,
                         start_index=args.start_index, max_batches=args.max_batches, pilot_paths=pilot)
        with PinnedNtfsDirectory(output.parent):
            output.mkdir()
            with PinnedNtfsDirectory(output):
                requests = result.pop("requests")
                receipts = []
                for index, request in enumerate(requests):
                    path = output / f"request-{index:02d}.json"
                    raw = (json.dumps(request, sort_keys=True, indent=2) + "\n").encode()
                    if len(raw) > compression.MAX_REQUEST_BYTES:
                        raise ValueError("planned request exceeds the consumer bound")
                    with path.open("xb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                    receipts.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                                     "files": len(request["files"]),
                                     "logical_bytes": sum(row["size_bytes"] for row in request["files"])})
                result.update(schema_version=schema_version("storage_recovery_batch_plan"),
                              source_git_sha=args.source_git_sha, requests=receipts,
                              inventory_wrapper_sha256=args.inventory_wrapper_sha256,
                              pilot_wrapper_sha256=args.pilot_wrapper_sha256)
                compression.write_receipt(output / "plan.json", result)
        print(json.dumps({key: result[key] for key in (
            "mode", "selected_file_count", "selected_allocated_bytes", "next_index", "has_more")}))
        return 0
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
