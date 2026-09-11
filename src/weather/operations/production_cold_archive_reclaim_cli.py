"""Attended host-bound reclaim of exactly restored and approved archive sources."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time

from weather.operations import cold_archive_reclaim as reclaim
from weather.operations import cold_archive_plain as plain
from weather.operations import cold_archive_native_removal as native
from weather.operations import production_cold_archive_stage_cli as staging
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.operations.replay_cache_compression import _utc, read_bounded_json, write_receipt
from weather.operations.replay_cache_compression_admission import (
    observe_capture_admission, set_current_process_below_normal, verify_current_lease)
from weather.paths import repo_path
from weather.schema_registry import schema_version

WORKLOAD = "production_cold_archive_reclaim"
EVIDENCE_FIELDS = ("catalog_entry", "owner_approval", "proposal", "selection", "plan",
                   "source_review", "restore_record", "custody_record")


def _failure_locations(exc):
    trace, frames = exc.__traceback__, []
    while trace is not None and len(frames) < 16:
        frames.append({"module": Path(trace.tb_frame.f_code.co_filename).name,
                       "line": trace.tb_lineno})
        trace = trace.tb_next
    return frames


def validate_request(payload, *, production_root, now, source_git_sha):
    is_plain = isinstance(payload, dict) and payload.get("schema_version") == schema_version(
        "production_cold_archive_plain_reclaim_request")
    evidence = plain.EVIDENCE_FIELDS if is_plain else EVIDENCE_FIELDS
    required = {"schema_version", "production_repo_root", "execution_host_id", "operation",
                "approved_by", "approved_at_utc", "expires_at_utc", "source_git_sha",
                "attempt_id", *evidence}
    if is_plain:
        required.update({"payload_encryption", "archive_id"})
    elif isinstance(payload, dict) and "spool_inventory" in payload:
        required.add("spool_inventory")
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("request fields differ from the exact archive reclaim contract")
    expected_schema = schema_version("production_cold_archive_plain_reclaim_request" if is_plain
                                     else "production_cold_archive_reclaim_request")
    if payload["schema_version"] != expected_schema or payload["operation"] != "reclaim":
        raise ValueError("unsupported archive reclaim request")
    if is_plain:
        if payload["payload_encryption"] != "none":
            raise ValueError("plain reclaim requires an explicit unencrypted payload")
        reclaim.locations.archive_id(payload["archive_id"])
    if (not isinstance(payload["production_repo_root"], str)
            or Path(payload["production_repo_root"]) != production_root
            or payload["source_git_sha"] != source_git_sha):
        raise ValueError("reclaim source or production root mismatch")
    for field, pattern in (("execution_host_id", r"[0-9a-f]{64}"),
                           ("source_git_sha", r"[0-9a-f]{40}"),
                           ("attempt_id", reclaim.locations.ARCHIVE_ID_RE.pattern)):
        if not isinstance(payload[field], str) or re.fullmatch(pattern, payload[field]) is None:
            raise ValueError("invalid reclaim request " + field)
    if not isinstance(payload["approved_by"], str) or not 0 < len(payload["approved_by"].strip()) <= 128:
        raise ValueError("named reclaim owner is required")
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("reclaim request is expired, future-dated or overlong")
    evidence_fields = evidence + (("spool_inventory",) if "spool_inventory" in payload else ())
    for field in evidence_fields:
        spec = payload[field]
        if (not isinstance(spec, dict) or set(spec) != {"path", "sha256"}
                or not isinstance(spec["path"], str) or not Path(spec["path"]).is_absolute()):
            raise ValueError("reclaim evidence requires an absolute path and SHA-256")
        reclaim.locations.require_sha(spec["sha256"])
    return payload


def run_reclaim(args):
    if os.name != "nt":
        raise ValueError("production reclaim requires native Windows")
    root = metadata.validate_root(Path(args.production_repo_root))
    output = metadata.validate_root(Path(args.output_root))
    if output.parent != root / "scratch" / WORKLOAD or any(output.iterdir()):
        raise ValueError("output must be a new empty immediate reclaim attempt")
    if not re.fullmatch(r"[0-9a-f]{64}", args.request_sha256) or not re.fullmatch(r"[0-9a-f]{40}", args.source_git_sha):
        raise ValueError("invalid reclaim request or source digest")
    request_path = Path(args.request)
    if not request_path.is_absolute():
        raise ValueError("request path must be absolute")
    with PinnedNtfsDirectory(output):
        try:
            with ExitStack() as stack:
                return _run_pinned(args, root, output, request_path, stack)
        except BaseException as exc:
            # An interrupted child cannot prove how many dispositions completed.
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RECONCILE_EXACT_ATTEMPT", "error_type": type(exc).__name__,
                "failure_locations": _failure_locations(exc),
                "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
                "source_retained": None, "deleted_files": None, "reclaimed_bytes": None,
                "cleanup_eligible": False, "upload_performed": False})
            raise


def _run_pinned(args, root, output, request_path, stack):
    stack.enter_context(reclaim.bridge._file_pin(reclaim.locations.safe_path(request_path)))
    request, raw = staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
    now = datetime.now(timezone.utc)
    validate_request(request, production_root=root, now=now, source_git_sha=args.source_git_sha)
    source = repo_path()
    if str(source) != os.environ.get(staging.ENV_PREFIX + "SOURCE_ROOT"):
        raise ValueError("Python import root is not wrapper-bound")
    for module in (__file__, reclaim.__file__, plain.__file__, native.__file__, reclaim.archive.__file__,
                   reclaim.bridge.__file__, reclaim.catalog.__file__, reclaim.locations.__file__,
                   reclaim.spool.__file__,
                   staging.__file__, metadata.__file__):
        if not Path(module).resolve().is_relative_to(source / "src" / "weather"):
            raise ValueError("reclaim module escaped the reviewed source checkout")
    assignment_path = source / "config" / "international_live_execution_host.json"
    stack.enter_context(reclaim.bridge._file_pin(reclaim.locations.safe_path(assignment_path)))
    assignment, _ = read_bounded_json(assignment_path, 32768)
    backup_host = assignment.get("active_portable_execution_host_id")
    reclaim.locations.require_sha(backup_host)
    if (assignment.get("assignment_status") != "ASSIGNED"
            or assignment.get("dedicated_capture_execution_host_id") != request["execution_host_id"]
            or backup_host == request["execution_host_id"]):
        raise ValueError("reclaim host assignment differs")
    owner = int(os.environ.get(staging.ENV_PREFIX + "OWNER_PID", "0"))
    lease_path = root / "data" / "logs" / "heavy_workload.lock"
    lease, _ = read_bounded_json(lease_path, 16384)
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("reclaim requires its exact host lease")
    verify_current_lease(lease, owner, lease_path, workload=WORKLOAD)
    exception = staging.verify_archive_exception(lease, now)
    set_current_process_below_normal()
    deadline = _utc(os.environ[staging.ENV_PREFIX + "DEADLINE_UTC"])
    staging.verify_archive_deadline(deadline, now, exception)
    plan_spec = request["plan"]
    stack.enter_context(reclaim.bridge._file_pin(reclaim.locations.safe_path(plan_spec["path"])))
    _, reserve = staging.load_plan_with_reserve(
        Path(plan_spec["path"]), plan_spec["sha256"], owner_approved_exception=exception)
    last_check, last_admission, capture_loops = 0.0, {}, []

    def resource_check(**observed):
        nonlocal capture_loops
        capture_loops = observed["loops"]
        return staging.check_resources(output_reservation=0, source_reserve_bytes=reserve,
                                               owner_approved_exception=exception, **observed)

    def guard(force=False):
        nonlocal last_check, last_admission
        current = datetime.now(timezone.utc)
        if current >= deadline or current >= _utc(request["expires_at_utc"]):
            raise ValueError("reclaim deadline or request expiry reached")
        if force or time.monotonic() - last_check >= 1:
            verify_current_lease(lease, owner, lease_path, workload=WORKLOAD)
            last_admission = observe_capture_admission(
                root, resource_check, memory_reader=staging.resource_policy.read_host_memory)
            last_check = time.monotonic()
            if last_admission["status"] != "PASS":
                write_receipt(output / "admission-refusal.json", last_admission)
                raise ValueError("capture resource admission refused")
        return True

    guard(force=True)
    with (output / "request.json").open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if request.get("payload_encryption") == "none":
        request = plain.prepare_request(
            request, production_root=root, backup_host_id=backup_host, output_root=output,
            admission=guard, deadline_monotonic=time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds())
    result = reclaim.reclaim_chunk(
        request=request, source_root=source, production_root=root, backup_host_id=backup_host,
        capture_loops=capture_loops, admission=guard,
        deadline_monotonic=time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds())
    guard(force=True)
    reread, digest = reclaim.locations.read_record(result["receipt_path"], result["receipt_sha256"])
    if (reread.get("status") != "PASS" or reread.get("attempt_id") != request["attempt_id"]
            or reread.get("files") != result["files"] or digest != result["receipt_sha256"]):
        raise ValueError("reclaim receipt readback differs")
    final = {"schema_version": schema_version("production_cold_archive_reclaim_execution_receipt"),
             "status": "PASS", "operation": "reclaim", "source_git_sha": args.source_git_sha,
             "request_sha256": args.request_sha256, "execution_host_id": request["execution_host_id"],
             "attempt_id": request["attempt_id"], "archive_id": result["archive_id"],
             "chunk_id": result["chunk_id"], "deleted_files": result["deleted_files"],
             "reclaimed_bytes": result["reclaimed_allocated_bytes"],
             "source_retained": result["source_retained"], "cleanup_eligible": False,
             "spool_cleanup": result.get("spool_cleanup"),
             "upload_performed": False, "reclaim_receipt_path": result["receipt_path"],
             "reclaim_receipt_sha256": result["receipt_sha256"], "final_admission": last_admission}
    write_receipt(output / "result.json", final)
    print(json.dumps({key: final[key] for key in
                      ("status", "archive_id", "deleted_files", "reclaimed_bytes")}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["reclaim"])
    for field in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args(argv)
    try:
        return run_reclaim(args)
    except Exception as exc:
        print("REFUSED: " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
