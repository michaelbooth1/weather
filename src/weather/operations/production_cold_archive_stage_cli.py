"""Admitted production staging for one exact cold-archive chunk.

Planning reads retained metadata only. Staging must run through
production_cold_archive_run.ps1 and never uploads or deletes source files.
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

from weather.operations import production_cold_archive_stage as stage
from weather.operations import cold_archive_resource_policy as resource_policy
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.operations.replay_cache_compression import _utc, read_bounded_json, write_receipt
from weather.operations.replay_cache_compression_admission import (
    check_capture_health, observe_capture_admission, set_current_process_below_normal,
    verify_current_lease, verify_storage_exception, storage_daytime_authorized,
    ARCHIVE_DAYTIME_EXCEPTION, ARCHIVE_DAYTIME_END, ARCHIVE_EXCEPTION_ENDS,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version

ENV_PREFIX = "WEATHER_PRODUCTION_ARCHIVE_"
WORKLOAD = "production_cold_archive_stage"
GIB = 1024**3
MAX_PLAN_BYTES = 8 * 1024**2
MAX_REQUEST_BYTES = 32768
MAX_SECONDS = 300
SOURCE_RESERVE_BYTES = 50 * GIB
# Owner decision 2026-09-09: only the reviewed July 16-31 archive may use 20 GiB.
APPROVED_ARCHIVE_PLAN_SHA256 = "b2f94bbe51ff31b40b1d43d5737f96ef721a3858bd37fdd460c9dcb66adf2b30"
APPROVED_ARCHIVE_SELECTION_SHA256 = "ba1f3a81d083db6bb85141c0a867d0afa4508c66bb0b88dfd6c18437d7c0c8db"
APPROVED_ARCHIVE_RESERVE_BYTES = 20 * GIB
# Owner 2026-09-10: bounded overnight recovery using existing disk only.
OVERNIGHT_PLAN_SHA256 = "41ee8e81d795e56213c1d2ee3a73ef78049c6425e659b66d9e5b6c5a15738a4c"
OVERNIGHT_DAY_PLAN_SHA256 = "96105932f57c12943de26c51e0a33c6ec6082dea20adcbcb4a9bcfe1fa0fe16b"
OVERNIGHT_PACKED_PLAN_SHA256 = "d96e680cf1c9df62d4d8929ef8b6efd5b8e98b137e5f661a5313887156a88c26"
OVERNIGHT_SELECTION_SHA256 = "566e0fd15a0095c131068cc4ef3cf09e715ca570b1205286e6e6fd6927f607c9"
OVERNIGHT_RESERVE_BYTES = 6 * GIB
EVIDENCE_RESERVE_BYTES = 16 * 1024**2
MAX_CHUNK_BYTES = GIB


def validate_request(payload, *, production_root, now, source_git_sha):
    required = {
        "schema_version", "production_repo_root", "execution_host_id", "operation",
        "approved_by", "approved_at_utc", "expires_at_utc", "plan_path",
        "plan_sha256", "chunk_id", "source_git_sha",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("request fields differ from the exact archive-stage contract")
    if payload["schema_version"] != schema_version("production_cold_archive_request"):
        raise ValueError("unsupported production archive request")
    if payload["operation"] != "stage_only":
        raise ValueError("only source-retaining staging is supported")
    if Path(payload["production_repo_root"]) != production_root:
        raise ValueError("request production root mismatch")
    if payload["source_git_sha"] != source_git_sha:
        raise ValueError("request source-code identity mismatch")
    if not isinstance(payload["approved_by"], str) or not 0 < len(payload["approved_by"].strip()) <= 128:
        raise ValueError("named owner approval is required")
    for field, pattern in (("execution_host_id", r"[0-9a-f]{64}"),
                           ("plan_sha256", r"[0-9a-f]{64}"),
                           ("source_git_sha", r"[0-9a-f]{40}"),
                           ("chunk_id", r"chunk-[0-9]{5}")):
        if not isinstance(payload[field], str) or not re.fullmatch(pattern, payload[field]):
            raise ValueError("invalid request " + field)
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("archive request is expired, future-dated or overlong")
    if not isinstance(payload["plan_path"], str) or not Path(payload["plan_path"]).is_absolute():
        raise ValueError("archive plan path must be absolute")
    return payload


def validate_chunk(plan, chunk_id, production_root, now):
    if not isinstance(plan.get("source_root"), str) or Path(plan["source_root"]) != production_root / "data":
        raise ValueError("plan source root differs from production data")
    chunks = plan.get("chunks")
    if not isinstance(chunks, list) or not 1 <= len(chunks) <= 20000:
        raise ValueError("invalid plan chunk list")
    matches = [chunk for chunk in chunks if isinstance(chunk, dict) and chunk.get("chunk_id") == chunk_id]
    if len(matches) != 1:
        raise ValueError("chunk identity is missing or ambiguous")
    chunk = matches[0]
    files = chunk.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= 256:
        raise ValueError("chunk must contain one to 256 whole files")
    logical = 0
    today = now.astimezone(ZoneInfo("America/Toronto")).date()
    for row in files:
        name = row.get("path")
        if not isinstance(name, str):
            raise ValueError("source path missing")
        parts = PurePosixPath(name).parts
        if (len(parts) != 3 or parts[0] != "snapshots" or
                PurePosixPath(name).as_posix() != name or "\\" in name or ":" in name or
                any(part in (".", "..") for part in parts)):
            raise ValueError("only exact immediate market-day source files are supported")
        if metadata.event_date(parts[1]) >= today - timedelta(days=30):
            raise ValueError("source event is inside the thirty-day hot window")
        size = row.get("size_bytes")
        if type(size) is not int or not 0 <= size <= MAX_CHUNK_BYTES:
            raise ValueError("source file exceeds the whole-file chunk bound")
        logical += size
    if type(chunk.get("logical_bytes")) is not int or logical != chunk["logical_bytes"] or logical > MAX_CHUNK_BYTES:
        raise ValueError("chunk byte accounting mismatch")
    return chunk


def check_resources(*, now, available, commit, free_disk, loops, output_reservation,
                    source_reserve_bytes=SOURCE_RESERVE_BYTES, owner_approved_exception=""):
    if owner_approved_exception and owner_approved_exception not in ARCHIVE_EXCEPTION_ENDS:
        raise ValueError("archive lane cannot claim another workload exception")
    result = check_capture_health(now=now, available=available, commit=commit, loops=loops,
                                  owner_approved_exception=owner_approved_exception,
                                  maximum_commit_percent=resource_policy.MAX_COMMIT_PERCENT,
                                  allow_planned_snapshot_sleep=True)
    minimum = source_reserve_bytes + EVIDENCE_RESERVE_BYTES + output_reservation
    result.update(free_disk_bytes=free_disk, minimum_free_disk_bytes=minimum,
                  source_disk_reserve_bytes=source_reserve_bytes)
    if type(free_disk) is not int or free_disk < minimum:
        result["reasons"].append("archive_disk_reservation_unmet")
        result["status"] = "BLOCK"
    return result


def _read_pinned_json(path, maximum, expected_hash):
    metadata.validate_root(path.parent)
    metadata.checked_stat(path, directory=False)
    value, raw = read_bounded_json(path, maximum)
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError("pinned metadata digest mismatch")
    return value, raw


def load_plan_with_reserve(path, expected_hash, *, now=None, owner_approved_exception=""):
    # Verify actual bytes before granting the exception; a claimed digest is
    # insufficient. Every different or regenerated plan retains the normal floor.
    plan, _ = _read_pinned_json(path, MAX_PLAN_BYTES, expected_hash)
    reserve = SOURCE_RESERVE_BYTES
    if (expected_hash == APPROVED_ARCHIVE_PLAN_SHA256 and
            plan.get("selection_sha256") == APPROVED_ARCHIVE_SELECTION_SHA256):
        reserve = APPROVED_ARCHIVE_RESERVE_BYTES
    current = now or datetime.now(timezone.utc)
    if (expected_hash in (OVERNIGHT_PLAN_SHA256, OVERNIGHT_DAY_PLAN_SHA256, OVERNIGHT_PACKED_PLAN_SHA256)
            and plan.get("selection_sha256") == OVERNIGHT_SELECTION_SHA256
            and (
                datetime(2026, 9, 10, 4, tzinfo=timezone.utc) <= current
                < datetime(2026, 9, 10, 13, tzinfo=timezone.utc)
                # Owner renewal: the same plans, September 11 only.
                or datetime(2026, 9, 11, 4, 30, tzinfo=timezone.utc) <= current
                < datetime(2026, 9, 11, 13, tzinfo=timezone.utc)
            )):
        reserve = OVERNIGHT_RESERVE_BYTES
    if owner_approved_exception:
        if (owner_approved_exception not in ARCHIVE_EXCEPTION_ENDS
                or not storage_daytime_authorized(current, owner_approved_exception)
                or expected_hash not in (OVERNIGHT_PLAN_SHA256, OVERNIGHT_DAY_PLAN_SHA256,
                                        OVERNIGHT_PACKED_PLAN_SHA256)
                or plan.get("selection_sha256") != OVERNIGHT_SELECTION_SHA256):
            raise ValueError("daytime archive authority requires the exact approved plan and selection")
        reserve = OVERNIGHT_RESERVE_BYTES
    return plan, reserve


def verify_archive_exception(lease, now, *, exception=None):
    """Require the explicit wrapper token and its independently verified live lease."""
    if exception is None:
        exception = os.environ.get(ENV_PREFIX + "OWNER_EXCEPTION", "")
    if exception:
        if exception not in ARCHIVE_EXCEPTION_ENDS:
            raise ValueError("archive exception is not authorized")
        verify_storage_exception(lease, exception, now)
    elif lease.get("policy_window") != "agent_heavy":
        raise ValueError("archive requires its ordinary overnight lease or explicit dated exception")
    return exception


def verify_archive_deadline(deadline, now, exception):
    if not 0 < (deadline - now).total_seconds() <= MAX_SECONDS:
        raise ValueError("wrapper deadline is outside its bounded interval")
    if exception and deadline > ARCHIVE_EXCEPTION_ENDS[exception] - timedelta(seconds=15):
        raise ValueError("archive exception deadline does not reserve teardown")


def staging_reserve(chunk, source_reserve_bytes):
    """Reserve capture space and both subsequent worst-case ciphertext copies."""
    reserve = source_reserve_bytes + EVIDENCE_RESERVE_BYTES
    if source_reserve_bytes == OVERNIGHT_RESERVE_BYTES:
        ciphertext_bound = chunk["logical_bytes"] + chunk["logical_bytes"] // 100 + 4 * stage.MIB
        reserve += 2 * ciphertext_bound
    return reserve


def run_staging(args):
    if os.name != "nt":
        raise ValueError("production archive staging requires native Windows")
    production_root = metadata.validate_root(Path(args.production_repo_root))
    output = metadata.validate_root(Path(args.output_root))
    allowed_parent = production_root / "scratch" / "production_cold_archive"
    if output.parent != allowed_parent or any(output.iterdir()):
        raise ValueError("output must be a new empty immediate archive-attempt directory")
    for value, pattern in ((args.request_sha256, r"[0-9a-f]{64}"),
                           (args.source_git_sha, r"[0-9a-f]{40}")):
        if not re.fullmatch(pattern, value):
            raise ValueError("invalid request or source-code digest")
    request_path = Path(args.request)
    if not request_path.is_absolute():
        raise ValueError("request path must be absolute")
    with PinnedNtfsDirectory(output):
        try:
            return _run_pinned(args, production_root, output, request_path)
        except Exception as exc:
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RETAIN_AND_INSPECT",
                "error_type": type(exc).__name__, "error": str(exc),
                "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
                "source_retained": True, "deleted_files": 0, "reclaimed_bytes": 0,
                "cleanup_eligible": False, "upload_performed": False,
            })
            raise


def _run_pinned(args, production_root, output, request_path):
    request, request_raw = _read_pinned_json(request_path, MAX_REQUEST_BYTES, args.request_sha256)
    now = datetime.now(timezone.utc)
    validate_request(request, production_root=production_root, now=now, source_git_sha=args.source_git_sha)
    source_root = repo_path()
    if str(source_root) != os.environ.get(ENV_PREFIX + "SOURCE_ROOT"):
        raise ValueError("Python import root is not bound to its wrapper")
    for module in (__file__, stage.__file__, metadata.__file__):
        if not Path(module).resolve().is_relative_to(source_root / "src" / "weather"):
            raise ValueError("archive module escaped its exact source checkout")
    owner_pid = int(os.environ.get(ENV_PREFIX + "OWNER_PID", "0"))
    lease_path = production_root / "data" / "logs" / "heavy_workload.lock"
    lease, _ = read_bounded_json(lease_path, 16384)
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("request does not bind the actual lease host")
    verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
    exception = verify_archive_exception(lease, now)
    set_current_process_below_normal()
    deadline = _utc(os.environ[ENV_PREFIX + "DEADLINE_UTC"])
    verify_archive_deadline(deadline, now, exception)
    plan_path = Path(request["plan_path"])
    plan, source_reserve_bytes = load_plan_with_reserve(
        plan_path, request["plan_sha256"], owner_approved_exception=exception)
    chunk = validate_chunk(plan, request["chunk_id"], production_root, now)
    # The core reserves its complete worst-case output before opening a source
    # and enforces the remaining reserve on every write. Ongoing health probes
    # retain the fixed capture reserve without double-counting written output.
    output_reservation = 0
    last_check = 0.0
    last_admission = {}

    def guard(force=False):
        nonlocal last_check, last_admission
        current = datetime.now(timezone.utc)
        if current >= deadline or current >= _utc(request["expires_at_utc"]):
            raise ValueError("archive deadline or request expiry reached")
        if force or time.monotonic() - last_check >= 1:
            last_admission = observe_capture_admission(
                production_root,
                lambda **observed: check_resources(output_reservation=output_reservation,
                                                  source_reserve_bytes=source_reserve_bytes,
                                                  owner_approved_exception=exception, **observed),
                memory_reader=resource_policy.read_host_memory,
            )
            last_check = time.monotonic()
            if last_admission["status"] != "PASS":
                write_receipt(output / "admission-refusal.json", last_admission)
                raise ValueError("capture admission refused: " + ",".join(last_admission["reasons"]))
        return True

    guard(force=True)
    # Preserve exact authority bytes rather than reserializing the request.
    with (output / "request.json").open("xb") as stream:
        stream.write(request_raw)
        stream.flush()
        os.fsync(stream.fileno())
    with PinnedNtfsDirectory(production_root / "data"):
        receipt = stage.stage_chunk(
            plan_path, request["plan_sha256"], request["chunk_id"], output / "stage",
            source_root=production_root / "data", admission=guard,
            deadline_monotonic=time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds(),
            rate_bytes_per_second=16 * 1024**2,
            free_space_reserve_bytes=staging_reserve(chunk, source_reserve_bytes),
        )
    guard(force=True)
    verify_current_lease(lease, owner_pid, lease_path, workload=WORKLOAD)
    _read_pinned_json(request_path, MAX_REQUEST_BYTES, args.request_sha256)
    _read_pinned_json(plan_path, MAX_PLAN_BYTES, request["plan_sha256"])
    if receipt.get("status") != "PASS" or receipt.get("source_retained") is not True or receipt.get("cleanup_eligible") is not False:
        raise ValueError("core staging did not produce retained-source PASS evidence")
    core_receipt_path = output / "stage" / "receipt.json"
    core_receipt, core_raw = read_bounded_json(core_receipt_path, MAX_PLAN_BYTES)
    if core_receipt != receipt:
        raise ValueError("core staging receipt readback mismatch")
    result = {
        "schema_version": schema_version("production_cold_archive_execution_receipt"),
        "status": "PASS", "source_git_sha": args.source_git_sha,
        "request_sha256": args.request_sha256, "plan_sha256": request["plan_sha256"],
        "execution_host_id": request["execution_host_id"], "chunk_id": request["chunk_id"],
        "core_receipt_path": str(core_receipt_path),
        "core_receipt_sha256": hashlib.sha256(core_raw).hexdigest(),
        "logical_source_bytes": chunk["logical_bytes"], "source_file_count": len(chunk["files"]),
        "source_retained": True, "deleted_files": 0, "reclaimed_bytes": 0,
        "cleanup_eligible": False, "upload_performed": False, "final_admission": last_admission,
    }
    write_receipt(output / "result.json", result)
    print(json.dumps({key: result[key] for key in (
        "status", "chunk_id", "logical_source_bytes", "source_file_count",
        "source_retained", "cleanup_eligible",
    )}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    plan = sub.add_parser("plan", help="Build deterministic chunks from retained metadata only.")
    for name in ("selection", "selection-sha256", "output-path"):
        plan.add_argument("--" + name, required=True)
    plan.add_argument("--chunk-grouping", choices=stage.CHUNK_GROUPINGS, default=stage.LEGACY_GROUPING)
    plan.add_argument("--isolate-event", action="append", default=[])
    run = sub.add_parser("stage", help="Stage one request-bound chunk through the production wrapper.")
    for name in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        run.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        if args.operation == "plan":
            result = stage.plan_selection(Path(args.selection), args.selection_sha256,
                                          Path(args.output_path), chunk_grouping=args.chunk_grouping,
                                          isolated_events=sorted(set(args.isolate_event)))
            print(json.dumps({"status": "PLANNED", "chunks": len(result["chunks"]),
                              "files": result["file_count"], "cleanup_eligible": False}))
            return 0
        return run_staging(args)
    except Exception as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
