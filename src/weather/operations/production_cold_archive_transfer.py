"""Production-admitted transfer of one already-encrypted cold archive chunk.

Only the reviewed wrapper may run this command. It has no source deletion lane.
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

from weather.operations import cold_archive_catalog as catalog
from weather.operations import production_cold_archive_stage_cli as staging
from weather.operations import production_cold_archive_transfer_core as transfer
from weather.operations import storage_recovery_inventory as metadata
from weather.operations.ntfs_file_compression import PinnedNtfsDirectory
from weather.operations.replay_cache_compression import _utc, read_bounded_json, write_receipt
from weather.operations.replay_cache_compression_admission import (
    observe_capture_admission, set_current_process_below_normal, verify_current_lease)
from weather.paths import repo_path
from weather.schema_registry import schema_version

WORKLOAD = "production_cold_archive_transfer"
MODES = {"transfer": "upload_and_independent_download",
         "upload": "upload_only", "download": "download_and_verify",
         "publish": "publish_uploaded"}
PATH_FIELDS = ("ciphertext_path", "crypt_receipt_path", "production_manifest_path",
               "production_receipt_path", "rclone_executable", "rclone_config", "dpapi_secret")
HASH_FIELDS = ("plan_sha256", "crypt_receipt_sha256", "production_manifest_sha256",
               "production_receipt_sha256")


def validate_request(payload, *, production_root, now, source_git_sha):
    publication = isinstance(payload, dict) and payload.get("operation") == MODES["publish"]
    required = {"schema_version", "production_repo_root", "execution_host_id", "operation",
                "approved_by", "approved_at_utc", "expires_at_utc", "plan_path", "chunk_id",
                "source_git_sha", "archive_id", "drive_remote_name", "drive_root_folder_id",
                *PATH_FIELDS, *HASH_FIELDS}
    if publication:
        required.difference_update({"ciphertext_path", "rclone_executable", "rclone_config",
                                    "dpapi_secret", "drive_remote_name"})
        required.add("publish_catalog")
    if isinstance(payload, dict) and payload.get("operation") in (MODES["download"], MODES["publish"]):
        required.update({"upload_receipt_path", "upload_receipt_sha256"})
        if "ciphertext_path" not in payload:
            required.discard("ciphertext_path")
    if isinstance(payload, dict) and "publish_catalog" in payload:
        required.add("publish_catalog")
        if payload["publish_catalog"] is not True or payload.get("operation") not in (MODES["upload"], MODES["publish"]):
            raise ValueError("catalog publication requires an explicit upload-only or publish-uploaded request")
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("request fields differ from the archive-transfer contract")
    if (payload["schema_version"] != schema_version("production_cold_archive_transfer_request")
            or payload["operation"] not in MODES.values()):
        raise ValueError("unsupported archive-transfer request")
    if Path(payload["production_repo_root"]) != production_root or payload["source_git_sha"] != source_git_sha:
        raise ValueError("request source or production root mismatch")
    if not isinstance(payload["approved_by"], str) or not 0 < len(payload["approved_by"].strip()) <= 128:
        raise ValueError("named owner approval is required")
    extra_hashes = ("upload_receipt_sha256",) if payload["operation"] in (MODES["download"], MODES["publish"]) else ()
    for field in (*HASH_FIELDS, *extra_hashes):
        transfer.archive._require_sha256(payload[field])
    for field, pattern in (("execution_host_id", r"[0-9a-f]{64}"),
                           ("source_git_sha", r"[0-9a-f]{40}"), ("chunk_id", r"chunk-[0-9]{5}"),
                           ("archive_id", r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}"),
                           ("drive_remote_name", transfer.REMOTE_RE.pattern),
                           ("drive_root_folder_id", transfer.ID_RE.pattern)):
        if publication and field == "drive_remote_name":
            continue
        if not isinstance(payload[field], str) or re.fullmatch(pattern, payload[field]) is None:
            raise ValueError("invalid transfer request " + field)
    approved, expires = _utc(payload["approved_at_utc"]), _utc(payload["expires_at_utc"])
    if not approved <= now < expires or expires - approved > timedelta(hours=72):
        raise ValueError("transfer request is expired, future-dated or overlong")
    extra_paths = ("upload_receipt_path",) if payload["operation"] in (MODES["download"], MODES["publish"]) else ()
    for field in (*(name for name in PATH_FIELDS if name in payload), "plan_path", *extra_paths):
        if not isinstance(payload[field], str) or not Path(payload[field]).is_absolute():
            raise ValueError("transfer paths must be absolute")
    return payload


def validate_manifest_plan(manifest, plan, chunk):
    """Bind the staged member identities to the actual approved plan bytes."""
    if (manifest.get("plan_hash") != plan.get("plan_hash")
            or Path(manifest.get("source_root", "")) != Path(plan.get("source_root", ""))
            or manifest.get("chunk_id") != chunk.get("chunk_id")
            or not transfer.archive._matches_staged_rows(chunk["files"], manifest.get("files"))):
        raise ValueError("staged manifest does not match the approved chunk")


def publish_upload_location(request, receipt_path, receipt_sha256, *, source_root,
                            admission, deadline_monotonic):
    """Publish location metadata inside the upload job's unchanged admission."""
    if request.get("publish_catalog") is not True:
        return None
    if request.get("operation") not in (MODES["upload"], MODES["publish"]):
        raise ValueError("catalog publication is bound to upload-only or publish-uploaded")
    result = catalog.publish_upload(
        source_root=source_root,
        production_manifest=request["production_manifest_path"],
        production_manifest_sha256=request["production_manifest_sha256"],
        production_receipt=request["production_receipt_path"],
        production_receipt_sha256=request["production_receipt_sha256"],
        crypt_receipt=request["crypt_receipt_path"],
        crypt_receipt_sha256=request["crypt_receipt_sha256"],
        upload_receipt=receipt_path, upload_receipt_sha256=receipt_sha256,
        admission=admission, deadline_monotonic=deadline_monotonic)
    inventory = catalog.write_inventory(source_root=source_root, admission=admission,
                                        deadline_monotonic=deadline_monotonic)
    return {**result, "inventory": inventory}


def committed_upload(request):
    """Read an exact prior upload; never initialize a client or open payloads."""
    result, raw = staging._read_pinned_json(
        Path(request["upload_receipt_path"]), staging.MAX_PLAN_BYTES,
        request["upload_receipt_sha256"])
    transfer.archive._check_seal(result, "receipt_hash")
    if (result.get("schema_version") != schema_version("production_cold_archive_upload_receipt")
            or result.get("status") != "PASS" or result.get("phase") != MODES["upload"]
            or result.get("upload_performed") is not True
            or result.get("independent_download") is not False
            or result.get("drive", {}).get("root_folder_id") != request["drive_root_folder_id"]
            or any(result.get(key) != request[key] for key in
                   ("archive_id", "chunk_id", *HASH_FIELDS))):
        raise ValueError("committed upload differs from the publication request")
    return result, raw


def run_transfer(args):
    if os.name != "nt":
        raise ValueError("production transfer requires native Windows")
    root = metadata.validate_root(Path(args.production_repo_root))
    output = metadata.validate_root(Path(args.output_root))
    if output.parent != root / "scratch" / WORKLOAD or any(output.iterdir()):
        raise ValueError("output must be a new empty immediate transfer attempt")
    if not re.fullmatch(r"[0-9a-f]{64}", args.request_sha256) or not re.fullmatch(r"[0-9a-f]{40}", args.source_git_sha):
        raise ValueError("invalid request or source-code digest")
    request_path = Path(args.request)
    if not request_path.is_absolute():
        raise ValueError("request path must be absolute")
    with PinnedNtfsDirectory(output):
        try:
            return _run_pinned(args, root, output, request_path)
        except BaseException as exc:
            write_receipt(output / "refusal.json", {
                "status": "REFUSED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__,
                "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
                "source_retained": True, "deleted_files": 0, "reclaimed_bytes": 0,
                "cleanup_eligible": False, "upload_performed": False if args.operation == "publish" else None,
                "remote_side_effect_possible": args.operation != "publish"})
            raise


def _run_pinned(args, root, output, request_path):
    request, raw = staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
    now = datetime.now(timezone.utc)
    validate_request(request, production_root=root, now=now, source_git_sha=args.source_git_sha)
    if request["operation"] != MODES[args.operation]:
        raise ValueError("wrapper operation differs from the approved request")
    workload = WORKLOAD if args.operation == "transfer" else WORKLOAD + "_" + args.operation
    source = repo_path()
    if str(source) != os.environ.get(staging.ENV_PREFIX + "SOURCE_ROOT"):
        raise ValueError("Python import root is not wrapper-bound")
    for module in (__file__, staging.__file__, transfer.__file__, transfer.archive.__file__,
                   transfer.bridge.__file__, transfer.crypt.__file__, metadata.__file__,
                   catalog.__file__, catalog.locations.__file__):
        if not Path(module).resolve().is_relative_to(source / "src" / "weather"):
            raise ValueError("transfer module escaped the exact source checkout")
    owner = int(os.environ.get(staging.ENV_PREFIX + "OWNER_PID", "0"))
    lease_path = root / "data" / "logs" / "heavy_workload.lock"
    lease, _ = read_bounded_json(lease_path, 16384)
    if lease.get("execution_host_id") != request["execution_host_id"]:
        raise ValueError("transfer requires its exact host lease")
    verify_current_lease(lease, owner, lease_path, workload=workload)
    exception = staging.verify_archive_exception(lease, now)
    set_current_process_below_normal()
    deadline = _utc(os.environ[staging.ENV_PREFIX + "DEADLINE_UTC"])
    staging.verify_archive_deadline(deadline, now, exception)
    plan_path = Path(request["plan_path"])
    plan, reserve = staging.load_plan_with_reserve(
        plan_path, request["plan_sha256"], owner_approved_exception=exception)
    chunk = staging.validate_chunk(plan, request["chunk_id"], root, now)
    manifest = transfer._read_bound(request["production_manifest_path"], request["production_manifest_sha256"])
    validate_manifest_plan(manifest, plan, chunk)
    crypt_receipt = transfer._read_bound(request["crypt_receipt_path"], request["crypt_receipt_sha256"])
    if crypt_receipt.get("chunk_id") != request["chunk_id"]:
        raise ValueError("encrypted archive differs from the request chunk")
    last_check, last_admission = 0.0, {}

    def guard(force=False):
        nonlocal last_check, last_admission
        current = datetime.now(timezone.utc)
        if current >= deadline or current >= _utc(request["expires_at_utc"]):
            raise ValueError("transfer deadline or request expiry reached")
        if force or time.monotonic() - last_check >= 1:
            last_admission = observe_capture_admission(
                root, lambda **observed: staging.check_resources(
                    output_reservation=0, source_reserve_bytes=reserve,
                                               owner_approved_exception=exception, **observed),
                memory_reader=staging.resource_policy.read_host_memory)
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
    expected_upload = args.operation not in ("download", "publish")
    expected_download = args.operation not in ("upload", "publish")
    if args.operation == "publish":
        result, receipt_raw = committed_upload(request)
        receipt_path = Path(request["upload_receipt_path"])
    else:
        result = transfer.transfer_chunk(
            **{key: request[key] for key in (
                "crypt_receipt_path", "crypt_receipt_sha256",
                "production_manifest_path", "production_manifest_sha256",
                "production_receipt_path", "production_receipt_sha256",
                "plan_sha256", "archive_id", "rclone_executable", "rclone_config", "dpapi_secret",
                "drive_remote_name", "drive_root_folder_id")},
            ciphertext_path=request.get("ciphertext_path"),
            output_root=output / "transfer", protected_root=root / "data", admission=guard,
            deadline_monotonic=time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds(),
            free_space_reserve_bytes=reserve + staging.EVIDENCE_RESERVE_BYTES,
            phase=request["operation"],
            **({key: request[key] for key in ("upload_receipt_path", "upload_receipt_sha256")}
               if args.operation == "download" else {}))
        guard(force=True)
        verify_current_lease(lease, owner, lease_path, workload=workload)
        staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
        staging._read_pinned_json(plan_path, staging.MAX_PLAN_BYTES, request["plan_sha256"])
        receipt_path = output / "transfer" / "receipt.json"
        reread, receipt_raw = read_bounded_json(receipt_path, staging.MAX_PLAN_BYTES)
        if (reread != result or result.get("status") != "PASS"
                or result.get("phase") != request["operation"]
                or result.get("independent_download") is not expected_download
                or result.get("upload_performed") is not expected_upload):
            raise ValueError("transfer receipt readback mismatch")
    guard(force=True)
    verify_current_lease(lease, owner, lease_path, workload=workload)
    staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
    staging._read_pinned_json(plan_path, staging.MAX_PLAN_BYTES, request["plan_sha256"])
    catalog_result = publish_upload_location(
        request, receipt_path, hashlib.sha256(receipt_raw).hexdigest(),
        source_root=root / "data", admission=guard,
        deadline_monotonic=time.monotonic() + (deadline - datetime.now(timezone.utc)).total_seconds())
    guard(force=True)
    verify_current_lease(lease, owner, lease_path, workload=workload)
    proof_kind = "upload" if args.operation in ("upload", "publish") else "transport"
    final = {"schema_version": schema_version("production_cold_archive_transfer_execution_receipt"),
             "status": "PASS", "operation": request["operation"], "source_git_sha": args.source_git_sha,
             "request_sha256": args.request_sha256, "execution_host_id": request["execution_host_id"],
             "plan_sha256": request["plan_sha256"], "chunk_id": result["chunk_id"],
             "archive_id": result["archive_id"], "ciphertext_bytes": result["ciphertext"]["bytes"],
             "crypt_receipt_sha256": request["crypt_receipt_sha256"],
             proof_kind + "_receipt_sha256": hashlib.sha256(receipt_raw).hexdigest(),
             proof_kind + "_receipt_path": str(receipt_path), "source_retained": True,
             "deleted_files": 0, "reclaimed_bytes": 0, "cleanup_eligible": False,
             "upload_performed": expected_upload, "independent_download": expected_download,
             "final_admission": last_admission}
    if catalog_result is not None:
        final["catalog"] = catalog_result
    if args.operation == "publish":
        final["remote_side_effect_possible"] = False
        final["committed_upload_reused"] = True
    write_receipt(output / "result.json", final)
    print(json.dumps({key: final[key] for key in
                      ("status", "chunk_id", "archive_id", "ciphertext_bytes",
                       "source_retained", "cleanup_eligible", "independent_download")}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=list(MODES))
    for field in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args(argv)
    try:
        return run_transfer(args)
    except Exception as exc:
        print("REFUSED: " + type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
