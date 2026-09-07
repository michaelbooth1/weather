"""Bounded, journaled NTFS compression of explicitly approved cold cache files.

This operation retains all files and all logical bytes. The production CLI
requires the capture wrapper's live lease and checks admission independently.
It never scans a directory, deletes a cache, changes a reader, or decompresses.
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

from weather.operations.ntfs_file_compression import LockedNtfsFile, MAX_FILE_BYTES, MIB
from weather.operations.replay_cache_compression_admission import (
    capture_admission, verify_current_lease,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version


MAX_BATCH_BYTES = 512 * MIB
MAX_FILES = 10
MAX_REQUEST_BYTES = 32 * 1024
MAX_RECEIPT_BYTES = 64 * 1024
CACHE_PATH = re.compile(
    r"backtest/replay_cache/[a-z0-9-]+/"
    r"[a-z0-9_]+__[0-9a-f]{12}__[0-9a-f]{12}__[0-9a-f]{12}\.json\Z"
)
IDENTITY_FIELDS = ("size_bytes", "volume_serial", "file_index", "mtime_ns", "creation_filetime")


def _utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamps require an explicit timezone")
    return result.astimezone(timezone.utc)


def _object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON key")
        result[name] = value
    return result


def read_bounded_json(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("JSON input exceeds its bound")
    return json.loads(raw, object_pairs_hook=_object), raw


def validate_request(payload, *, production_root, now):
    if payload.get("schema_version") != schema_version("replay_cache_compression_request"):
        raise ValueError("unsupported compression request")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("production repository binding mismatch")
    if not payload.get("approved_by") or payload.get("operation") != "compress_and_retain":
        raise ValueError("explicit compression-and-retention approval is required")
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("compression request is expired, future-dated or overlong")
    if not re.fullmatch(r"[0-9a-f]{64}", payload.get("execution_host_id", "")):
        raise ValueError("exact production host identity required")
    candidates = payload.get("files")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= MAX_FILES:
        raise ValueError("request must name between one and ten files")
    seen, total = set(), 0
    for candidate in candidates:
        relative = candidate.get("path", "")
        if not CACHE_PATH.fullmatch(relative) or PurePosixPath(relative).is_absolute():
            raise ValueError("candidate is outside the exact replay-cache path contract")
        if relative.casefold() in seen:
            raise ValueError("duplicate candidate path")
        seen.add(relative.casefold())
        size = candidate.get("size_bytes")
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
            raise ValueError("candidate exceeds the 64 MiB file bound")
        stamp = candidate.get("mtime_ns")
        if not isinstance(stamp, str) or not re.fullmatch(r"[0-9]{16,20}", stamp):
            raise ValueError("mtime_ns must be an exact decimal string")
        modified = datetime.fromtimestamp(int(stamp) / 1_000_000_000, timezone.utc)
        if now - modified < timedelta(days=30):
            raise ValueError("candidate has not been cold for thirty days")
        total += size
    if total > MAX_BATCH_BYTES:
        raise ValueError("request exceeds the 512 MiB batch bound")
    return candidates


def write_receipt(path, payload):
    content = (json.dumps(payload, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if len(content) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt exceeds its size bound")
    # A crash leaves an immutable incomplete artifact; it never licenses retry.
    with Path(path).open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def compress_candidate(path, expected, *, apply, guard, journal, opener=LockedNtfsFile,
                       bytes_per_second=8 * MIB):
    guard()
    with opener(path, writable=apply) as opened:
        before = opened.metadata()
        if (before["size_bytes"] != expected["size_bytes"]
                or before["mtime_ns"] != int(expected["mtime_ns"])):
            raise ValueError("candidate changed since the approved request")
        if before["compression_format"] != 0:
            raise ValueError("candidate already has a compression representation; replan")
        digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        guard()
        if opened.metadata() != before:
            raise ValueError("candidate metadata drifted during its preimage read")
        preimage = {"path": expected["path"], "before": before, "sha256": digest,
                    "action": "COMPRESS_AND_RETAIN" if apply else "PLAN_ONLY"}
        journal("before", preimage)
        guard()  # A slow flush may have consumed the admission/deadline budget.
        if not apply:
            return {**preimage, "status": "PLANNED", "reclaimed_bytes": 0}
        opened.compress()
        after_digest = opened.digest(guard=guard, bytes_per_second=bytes_per_second)
        after = opened.metadata()
        if (digest != after_digest or after["compression_format"] != 2
                or any(before[name] != after[name] for name in IDENTITY_FIELDS)):
            raise ValueError("post-compression content, identity or timestamp mismatch")
        result = {**preimage, "after": after, "status": "VERIFIED",
                  "reclaimed_bytes": before["allocation_bytes"] - after["allocation_bytes"]}
        journal("after", result)
        if result["reclaimed_bytes"] <= 0:
            raise ValueError("no positive allocated-byte reclaim; stop before expanding")
        return result


def _validate_output(root, production_root):
    if not root.is_absolute() or not root.is_relative_to(production_root / "scratch" / "storage_reclaim"):
        raise ValueError("evidence must be under production scratch/storage_reclaim")
    for candidate in (root, *root.parents):
        if candidate.exists() and (candidate.is_symlink() or candidate.stat().st_file_attributes & 0x400):
            raise ValueError("evidence path contains a link or reparse point")


def run(args):
    if os.name != "nt":
        raise ValueError("production compression runs only on native Windows")
    production_root, output = Path(args.production_repo_root), Path(args.output_root)
    if (not production_root.is_absolute() or production_root.resolve() != production_root
            or not Path(args.request).is_absolute() or not output.is_absolute()):
        raise ValueError("absolute normalized paths are required")
    _validate_output(output, production_root)
    request, raw = read_bounded_json(args.request, MAX_REQUEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != args.request_sha256:
        raise ValueError("request SHA-256 mismatch")
    candidates = validate_request(request, production_root=production_root,
                                  now=datetime.now(timezone.utc))
    if str(repo_path()) != os.environ.get("WEATHER_CACHE_COMPRESSION_SOURCE_ROOT"):
        raise ValueError("Python imports are not bound to the wrapper's source checkout")
    owner_pid = int(os.environ.get("WEATHER_CACHE_COMPRESSION_OWNER_PID", "0"))
    lease, _ = read_bounded_json(production_root / "data/logs/heavy_workload.lock", 16 * 1024)
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("request does not bind the actual lease host")
    verify_current_lease(lease, owner_pid)
    deadline = _utc(os.environ["WEATHER_CACHE_COMPRESSION_DEADLINE_UTC"])
    if not 0 < (deadline - datetime.now(timezone.utc)).total_seconds() <= 600:
        raise ValueError("wrapper deadline is missing or outside the bounded interval")
    last_check, admission = 0.0, {}

    def guard(force=False):
        nonlocal last_check, admission
        now = datetime.now(timezone.utc)
        if now >= deadline or now >= _utc(request["expires_at_utc"]):
            raise ValueError("compression deadline reached")
        if force or time.monotonic() - last_check >= 1:
            admission = capture_admission(production_root)
            last_check = time.monotonic()
            if admission["status"] != "PASS":
                raise ValueError("capture admission refused: " + ",".join(admission["reasons"]))

    guard(force=True)
    # The wrapper creates this unique attempt directory before dispatch. The
    # create-only request is the child claim: a spent attempt cannot be reused.
    write_receipt(output / "request.json", request)
    results = []
    receipt = {"schema_version": schema_version("replay_cache_compression_receipt"),
               "request_sha256": args.request_sha256, "source_git_sha": args.source_git_sha,
               "apply": args.apply, "deleted_files": 0, "reclaimed_bytes": 0}
    try:
        for index, candidate in enumerate(candidates):
            def journal(phase, row, index=index):
                write_receipt(output / f"{index:02d}-{phase}.json", {**receipt, **row})
            guard(force=True)
            row = compress_candidate(production_root / "data" / candidate["path"], candidate,
                                     apply=args.apply, guard=guard, journal=journal)
            results.append(row)
        guard(force=True)
        receipt.update(status="PASS", results=results,
                       reclaimed_bytes=sum(row["reclaimed_bytes"] for row in results),
                       final_admission=admission)
        return_code = 0
    except Exception as exc:
        receipt.update(status="FAILED_RETAIN_AND_INSPECT", results=results,
                       error=f"{type(exc).__name__}: {exc}", final_admission=admission)
        return_code = 1
    write_receipt(output / "result.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "reclaimed_bytes", "deleted_files")}, sort_keys=True))
    return return_code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-repo-root", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--request-sha256", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--source-git-sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
