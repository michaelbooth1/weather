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

from weather.operations.ntfs_file_compression import (
    LockedNtfsFile, MAX_FILE_BYTES, MIB, PinnedNtfsDirectory,
)
from weather.operations.replay_cache_compression_admission import (
    capture_admission, set_current_process_below_normal, verify_current_lease,
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
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "production_repo_root", "approved_by", "operation",
        "execution_host_id", "approved_at_utc", "expires_at_utc", "files",
    }:
        raise ValueError("request fields must match the exact compression contract")
    if payload.get("schema_version") != schema_version("replay_cache_compression_request"):
        raise ValueError("unsupported compression request")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("production repository binding mismatch")
    if (not isinstance(payload.get("approved_by"), str) or not payload["approved_by"].strip()
            or len(payload["approved_by"]) > 128 or payload.get("operation") != "compress_and_retain"):
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
        if not isinstance(candidate, dict) or set(candidate) != {"path", "size_bytes", "mtime_ns"}:
            raise ValueError("candidate fields must match the exact file contract")
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
                       bytes_per_second=8 * MIB, baseline=None):
    if apply and baseline is None:
        raise ValueError("apply requires the reviewed plan preimage")
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
        if baseline is not None and (
            baseline["sha256"] != digest
            or any(baseline["before"][field] != before[field] for field in IDENTITY_FIELDS)
        ):
            raise ValueError("candidate bytes or native identity changed since the reviewed plan")
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
    if (not root.is_absolute() or root.resolve() != root
            or not root.is_relative_to(production_root / "scratch" / "storage_reclaim")
            or root == production_root / "scratch" / "storage_reclaim"):
        raise ValueError("evidence must be under production scratch/storage_reclaim")
    for candidate in (root, *root.parents):
        if candidate.exists() and (candidate.is_symlink() or getattr(candidate.stat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("evidence path contains a link or reparse point")


def read_reviewed_plan(args, request, candidates, production_root, output):
    """Accept only a hash-bound, successfully torn-down plan for this request."""
    path, expected_hash = getattr(args, "plan_receipt", None), getattr(args, "plan_receipt_sha256", None)
    if not args.apply:
        if path or expected_hash:
            raise ValueError("a plan cannot consume another plan receipt")
        return None
    if not path or not re.fullmatch(r"[0-9a-f]{64}", expected_hash or ""):
        raise ValueError("apply requires an exact reviewed plan wrapper receipt and SHA-256")
    path = Path(path)
    if path.name != "wrapper-result.json" or path.parent == output:
        raise ValueError("apply requires a distinct completed plan attempt")
    _validate_output(path.parent, production_root)
    with PinnedNtfsDirectory(path.parent):
        wrapper, raw = read_bounded_json(path, MAX_RECEIPT_BYTES)
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise ValueError("reviewed plan wrapper SHA-256 mismatch")
        if (wrapper.get("status") != "PASS" or wrapper.get("apply") is not False
                or wrapper.get("teardown_proved") is not True
                or wrapper.get("hard_stop") is not False
                or wrapper.get("source_git_sha") != args.source_git_sha
                or wrapper.get("request_sha256") != args.request_sha256
                or wrapper.get("execution_host_id") != request["execution_host_id"]):
            raise ValueError("reviewed plan wrapper is failed, incomplete or differently bound")
        plan, raw = read_bounded_json(path.parent / "result.json", MAX_RECEIPT_BYTES)
        if hashlib.sha256(raw).hexdigest() != wrapper.get("child_result_sha256"):
            raise ValueError("reviewed plan child receipt SHA-256 mismatch")
    if (plan.get("schema_version") != schema_version("replay_cache_compression_receipt")
            or plan.get("status") != "PASS" or plan.get("apply") is not False
            or plan.get("source_git_sha") != args.source_git_sha
            or plan.get("request_sha256") != args.request_sha256
            or plan.get("deleted_files") != 0 or plan.get("reclaimed_bytes") != 0):
        raise ValueError("reviewed plan child receipt is not a successful matching plan")
    rows = plan.get("results")
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError("reviewed plan candidate list mismatch")
    for row, candidate in zip(rows, candidates):
        before = row.get("before", {})
        if (row.get("path") != candidate["path"] or row.get("status") != "PLANNED"
                or row.get("action") != "PLAN_ONLY" or row.get("reclaimed_bytes") != 0
                or not re.fullmatch(r"[0-9a-f]{64}", row.get("sha256", ""))
                or any(type(before.get(field)) is not int for field in IDENTITY_FIELDS)
                or before.get("compression_format") != 0
                or before.get("size_bytes") != candidate["size_bytes"]
                or before.get("mtime_ns") != int(candidate["mtime_ns"])):
            raise ValueError("reviewed plan preimage does not match the approved candidate")
    return rows


def run(args):
    if os.name != "nt":
        raise ValueError("production compression runs only on native Windows")
    production_root, output = Path(args.production_repo_root), Path(args.output_root)
    if (not production_root.is_absolute() or production_root.resolve() != production_root
            or not Path(args.request).is_absolute() or not output.is_absolute()):
        raise ValueError("absolute normalized paths are required")
    _validate_output(output, production_root)
    with PinnedNtfsDirectory(output):
        if any((output / name).exists() for name in (
                "request.json", "result.json", "refusal.json", "wrapper-result.json")):
            raise FileExistsError("spent output attempt; existing evidence is immutable")
        try:
            return _run_pinned(args, production_root, output)
        except Exception as exc:
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RETAIN_AND_INSPECT", "source_git_sha": args.source_git_sha,
                "request_sha256": args.request_sha256, "error": f"{type(exc).__name__}: {exc}",
            })
            raise


def _run_pinned(args, production_root, output):
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
    verify_current_lease(lease, owner_pid, production_root / "data/logs/heavy_workload.lock")
    # The venv redirector may spawn its real interpreter before the parent can
    # lower the redirector's priority. Set and verify the worker itself.
    set_current_process_below_normal()
    baselines = read_reviewed_plan(args, request, candidates, production_root, output)
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
               "reviewed_plan_receipt_sha256": getattr(args, "plan_receipt_sha256", None),
               "apply": args.apply, "deleted_files": 0, "reclaimed_bytes": 0}
    try:
        for index, candidate in enumerate(candidates):
            def journal(phase, row, index=index):
                write_receipt(output / f"{index:02d}-{phase}.json", {**receipt, **row})
            guard(force=True)
            row = compress_candidate(production_root / "data" / candidate["path"], candidate,
                                     apply=args.apply, guard=guard, journal=journal,
                                     baseline=baselines[index] if baselines else None)
            results.append(row)
        guard(force=True)
        receipt.update(status="PASS", results=results,
                       reclaimed_bytes=sum(row["reclaimed_bytes"] for row in results),
                       final_admission=admission)
        return_code = 0
    except Exception as exc:
        receipt.update(status="FAILED_RETAIN_AND_INSPECT", results=results,
                       reclaimed_bytes=sum(row["reclaimed_bytes"] for row in results),
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
    parser.add_argument("--plan-receipt")
    parser.add_argument("--plan-receipt-sha256")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
