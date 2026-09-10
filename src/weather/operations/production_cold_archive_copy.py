"""Copy only a verified archive's scratch files between its two approved PCs.

The production wrapper owns the capture lease, memory ceiling and complete child
Job. SCP uses a literal private address, strict pinned host keys, no configuration
or forwarding, and an 8 MiB/s ceiling. Every attempt and destination is fresh.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time

from weather.operations import bulk_cold_archive_crypt as bridge
from weather.operations import production_cold_archive_stage_cli as staging
from weather.operations import production_cold_archive_transfer as transfer
from weather.operations import production_cold_archive_stage as archive
from weather.operations.replay_cache_compression import _utc, read_bounded_json, write_receipt
from weather.operations.replay_cache_compression_admission import (
    observe_capture_admission, verify_current_lease, set_current_process_below_normal,
)
from weather.paths import repo_path
from weather.schema_registry import schema_version

WORKLOAD = "production_cold_archive_copy"
MAX_BYTES = 1100 * archive.MIB
BASE_FIELDS = {
    "schema_version", "production_repo_root", "execution_host_id", "operation",
    "approved_by", "approved_at_utc", "expires_at_utc", "plan_path",
    "plan_sha256", "chunk_id", "source_git_sha",
}
COPY_FIELDS = {
    "archive_id", "direction", "production_manifest_path", "production_manifest_sha256",
    "production_receipt_path", "production_receipt_sha256", "workstation_root",
    "remote_host", "remote_user", "private_key", "known_hosts", "known_hosts_sha256",
    "ssh_executable", "scp_executable", "files",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def remote_path(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z]:/[A-Za-z0-9_./-]+", value)
            and all(part not in {"", ".", ".."} for part in value.split("/")[1:])
            and not any(part.lower() in {"data", "weather-mirror"} for part in value.split("/")),
            "remote path must be a literal isolated Windows scratch path")
    return value


def validate_request(request, root, now, source_tip):
    require(isinstance(request, dict), "copy request must be an object")
    require(set(request) == BASE_FIELDS | COPY_FIELDS, "copy request fields differ")
    require(request["schema_version"] == schema_version("production_cold_archive_copy_request")
            and request["operation"] == "copy"
            and request["direction"] == "to_workstation", "unsupported archive copy")
    base = {name: request[name] for name in BASE_FIELDS}
    base.update(schema_version=schema_version("production_cold_archive_request"), operation="stage_only")
    staging.validate_request(base, production_root=root, now=now, source_git_sha=source_tip)
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", request["archive_id"]) is not None,
            "invalid archive identity")
    remote_path(request["workstation_root"])
    address = ipaddress.IPv4Address(request["remote_host"])
    require(address.is_private and not address.is_loopback and not address.is_multicast
            and not address.is_unspecified, "copy target must be an approved private IPv4 address")
    require(isinstance(request["remote_user"], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["remote_user"]) is not None,
            "invalid literal remote principal")
    for field in ("private_key", "known_hosts", "ssh_executable", "scp_executable"):
        path = Path(request[field])
        require(path.is_absolute() and ".." not in path.parts, "transport files must be absolute")
        archive._safe_path(path)
    native = Path(os.environ["WINDIR"]) / "System32" / "OpenSSH"
    require(Path(request["ssh_executable"]) == native / "ssh.exe"
            and Path(request["scp_executable"]) == native / "scp.exe",
            "archive copy requires the native system OpenSSH executables")
    rows = request["files"]
    require(isinstance(rows, list) and len(rows) == 3, "copy needs three exact stage files")
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"local", "remote", "bytes", "sha256"},
                "copy file fields differ")
        require(type(row["bytes"]) is int and 0 < row["bytes"] <= MAX_BYTES, "copy file exceeds bound")
        archive._require_sha256(row["sha256"])
        remote_path(row["remote"])
        require(Path(row["local"]).is_absolute() and ".." not in Path(row["local"]).parts,
                "local copy path must be absolute")
    require(sum(row["bytes"] for row in rows) <= MAX_BYTES, "copy total exceeds bound")
    require(len({row["local"].lower() for row in rows}) == len(rows)
            and len({row["remote"].lower() for row in rows}) == len(rows), "copy paths overlap")
    return request


def bound_rows(request, root, plan, chunk, stack):
    """Derive the only selectable files from sealed production archive evidence."""
    manifest_path = Path(request["production_manifest_path"])
    stage_dir = manifest_path.parent
    require(manifest_path.name == "manifest.json" and stage_dir.name == "stage"
            and stage_dir.parent.parent == root / "scratch" / "production_cold_archive"
            and re.fullmatch(re.escape(request["archive_id"]) + r"s[1-9][0-9]*", stage_dir.parent.name),
            "copy source is outside the exact archive staging attempt")
    receipt_path = Path(request["production_receipt_path"])
    require(receipt_path == stage_dir / "receipt.json", "stage receipt path differs")
    proof = {}
    for role, path, digest in (
        ("manifest", manifest_path, request["production_manifest_sha256"]),
        ("receipt", receipt_path, request["production_receipt_sha256"]),
    ):
        stack.enter_context(bridge._file_pin(archive._safe_path(path)))
        proof[role], _ = staging._read_pinned_json(path, 2 * archive.MIB, digest)
    manifest, receipt = proof["manifest"], proof["receipt"]
    archive._check_seal(manifest, "manifest_hash")
    archive._check_seal(receipt, "receipt_hash")
    transfer.validate_manifest_plan(manifest, plan, chunk)
    require(manifest["plan_sha256"] == request["plan_sha256"]
            and receipt.get("status") == "PASS" and receipt.get("source_retained") is True
            and receipt.get("manifest_hash") == manifest["manifest_hash"]
            and receipt.get("plan_sha256") == request["plan_sha256"]
            and receipt.get("chunk_id") == request["chunk_id"]
            and receipt.get("verification", {}).get("archive_sha256") == manifest["archive_sha256"],
            "copy staging proof differs")
    ws = request["workstation_root"]
    hashes = {"archive.tar.gz": manifest["archive_sha256"],
              "manifest.json": request["production_manifest_sha256"],
              "receipt.json": request["production_receipt_sha256"]}
    expected = [{
        "local": str(stage_dir / name),
        "remote": ws + "/scratch/ac-in/" + request["archive_id"] + "/" + name,
        "bytes": manifest["archive_bytes"] if name == "archive.tar.gz" else (stage_dir / name).stat().st_size,
        "sha256": digest,
    } for name, digest in hashes.items()]
    normalize = lambda row: {**row, "local": str(Path(row["local"]))}
    require([normalize(row) for row in request["files"]] == expected,
            "selected copy files differ from the verified archive evidence")
    return expected


def transport_arguments(request, executable):
    return [request[executable], "-F", "none", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", "PermitLocalCommand=no",
            "-o", "ProxyCommand=none", "-o", "ProxyJump=none",
            "-o", "ClearAllForwardings=yes", "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=10", "-i", request["private_key"],
            "-o", "UserKnownHostsFile=" + request["known_hosts"]]


def run_child(arguments, log_path, guard, *, timeout=300):
    """The outer native wrapper owns all descendant teardown, including failures."""
    end = time.monotonic() + timeout
    with log_path.open("xb") as log:
        child = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=log,
                                 stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while child.poll() is None:
                guard()
                require(transfer.transfer._client_memory_ok(child), "copy child memory exceeds 384 MiB")
                require(time.monotonic() < end and log_path.stat().st_size <= 65536,
                        "copy child deadline or output bound reached")
                time.sleep(0.25)
            require(child.wait() == 0, "copy transport or destination preflight failed")
            require(log_path.stat().st_size <= 65536, "copy child output exceeded bound")
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def destination_command(request):
    """One create-only archive directory; spent namespaces are never reused."""
    parent = request["workstation_root"] + "/scratch/ac-in"
    destination = parent + "/" + request["archive_id"]
    remote_path(destination)
    code = ("$ErrorActionPreference='Stop'; "
            f"$p='{parent}'; "
            "while($p){$i=Get-Item -LiteralPath $p -Force; "
            "if(-not $i.PSIsContainer -or ($i.Attributes -band [IO.FileAttributes]::ReparsePoint)){exit 3}; "
            "$p=Split-Path -Parent $p}; "
            f"if(Test-Path -LiteralPath '{destination}'){{exit 2}}; "
            f"$null=New-Item -ItemType Directory -Path '{destination}'; "
            "exit 0")
    return [*transport_arguments(request, "ssh_executable"), "-T", "-n",
            "-l", request["remote_user"], request["remote_host"],
            "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-NoProfile", "-NonInteractive", "-EncodedCommand",
            base64.b64encode(code.encode("utf-16le")).decode("ascii")]


def execute_copy(request, rows, output, guard, stack, *, child_runner=run_child):
    completed = []
    digest_guard = archive._Guard(guard, time.monotonic() + staging.MAX_SECONDS, 16 * archive.MIB)
    for row in rows:
        local = Path(row["local"])
        stack.enter_context(archive._directory_pin(archive._safe_path(local.parent, directory=True)))
        stack.enter_context(bridge._file_pin(archive._safe_path(local)))
        require(archive._hash(local, digest_guard) == (row["bytes"], row["sha256"]),
                "outbound source content changed")
    guard()
    child_runner(destination_command(request), output / "destination.log", guard, timeout=15)
    for index, row in enumerate(rows):
        guard()
        operands = [row["local"], request["remote_user"] + "@" + request["remote_host"] + ":" + row["remote"]]
        child_runner([*transport_arguments(request, "scp_executable"), "-q", "-l", "65536", *operands],
                     output / f"copy-{index}.log", guard)
        guard()
        completed.append(row)
        write_receipt(output / f"file-{index:03d}.json", {"status": "COPIED", "file": row})
    return completed


class _BinaryPin(bridge._Pin):
    """Keep the system image read-pinned, including its Windows servicing link."""
    def metadata(self):
        info, standard = archive._FileInformation(), archive._StandardInformation()
        self._check(self._kernel.GetFileInformationByHandle(self.handle, ctypes.byref(info)))
        self._check(self._kernel.GetFileInformationByHandleEx(
            self.handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)))
        size = (int(info.size_high) << 32) | int(info.size_low)
        require(not info.attributes & ~(0x1 | 0x20 | 0x80 | archive.COMPRESSED)
                and info.links == standard.links >= 1 and not standard.delete_pending
                and not standard.directory and 0 < size <= 16 * archive.MIB,
                "unsupported native transport binary")
        return {"size_bytes": size}


def run_copy(args):
    require(os.name == "nt", "archive scratch copy requires native Windows")
    root, output = Path(args.production_repo_root), Path(args.output_root)
    require(output.parent == root / "scratch" / WORKLOAD and output.is_dir() and not any(output.iterdir()),
            "copy requires a fresh immediate attempt")
    source = repo_path()
    require(all(Path(module).resolve().is_relative_to(source / "src" / "weather") for module in
                (__file__, staging.__file__, transfer.__file__, archive.__file__, bridge.__file__)),
            "copy dependency escaped reviewed source")
    require(str(source) == os.environ.get(staging.ENV_PREFIX + "SOURCE_ROOT")
            and Path(__file__).resolve().is_relative_to(source / "src" / "weather"),
            "copy module is not bound to its source wrapper")
    with ExitStack() as stack:
        stack.enter_context(archive._directory_pin(archive._safe_path(output, directory=True)))
        request_path = archive._safe_path(Path(args.request))
        stack.enter_context(bridge._file_pin(request_path))
        request, raw = staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
        now = datetime.now(timezone.utc)
        validate_request(request, root, now, args.source_git_sha)
        lease_path = root / "data" / "logs" / "heavy_workload.lock"
        lease, _ = read_bounded_json(lease_path, 16384)
        owner = int(os.environ[staging.ENV_PREFIX + "OWNER_PID"])
        require(lease.get("execution_host_id") == request["execution_host_id"], "copy host lease differs")
        verify_current_lease(lease, owner, lease_path, workload=WORKLOAD)
        exception = staging.verify_archive_exception(lease, now)
        deadline = _utc(os.environ[staging.ENV_PREFIX + "DEADLINE_UTC"])
        staging.verify_archive_deadline(deadline, now, exception)
        plan_path = archive._safe_path(Path(request["plan_path"]))
        stack.enter_context(bridge._file_pin(plan_path))
        plan, reserve = staging.load_plan_with_reserve(
            plan_path, request["plan_sha256"], owner_approved_exception=exception)
        chunk = staging.validate_chunk(plan, request["chunk_id"], root, now)
        known = archive._safe_path(Path(request["known_hosts"]))
        stack.enter_context(bridge._file_pin(known))
        stack.enter_context(bridge._file_pin(Path(request["private_key"])))
        for name in ("ssh_executable", "scp_executable"):
            stack.enter_context(_BinaryPin(Path(request[name])))
        require(known.stat().st_size <= 65536 and hashlib.sha256(known.read_bytes()).hexdigest()
                == request["known_hosts_sha256"], "SSH host-key trust changed")
        rows = bound_rows(request, root, plan, chunk, stack)
        reservation = 0
        last_check, admission = 0.0, {}
        set_current_process_below_normal()

        def guard():
            nonlocal last_check, admission
            current = datetime.now(timezone.utc)
            require(current < deadline and current < _utc(request["expires_at_utc"]), "copy request or job expired")
            if time.monotonic() - last_check >= 1:
                verify_current_lease(lease, owner, lease_path, workload=WORKLOAD)
                admission = observe_capture_admission(root, lambda **values: staging.check_resources(
                    output_reservation=reservation, source_reserve_bytes=reserve,
                    owner_approved_exception=exception, **values))
                last_check = time.monotonic()
                if admission["status"] != "PASS":
                    write_receipt(output / "admission-refusal.json", admission)
                    raise ValueError("copy capture admission refused")
            return True

        guard()
        with (output / "request.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        completed = execute_copy(request, rows, output, guard, stack)
        staging._read_pinned_json(request_path, staging.MAX_REQUEST_BYTES, args.request_sha256)
        guard()
        result = {"schema_version": schema_version("production_cold_archive_copy_execution_receipt"),
                  "status": "PASS", "operation": "copy", "direction": request["direction"],
                  "source_git_sha": args.source_git_sha, "request_sha256": args.request_sha256,
                  "execution_host_id": request["execution_host_id"], "archive_id": request["archive_id"],
                  "chunk_id": request["chunk_id"], "files": completed, "copied_files": len(completed),
                  "copied_bytes": sum(row["bytes"] for row in completed), "source_retained": True,
                  "deleted_files": 0, "reclaimed_bytes": 0, "cleanup_eligible": False,
                  "upload_performed": False, "remote_side_effect_possible": True,
                  "destination_hash_verified": False, "final_admission": admission,
                  "completed_at_utc": datetime.now(timezone.utc).isoformat()}
        write_receipt(output / "result.json", result)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["copy"])
    for name in ("production-repo-root", "request", "request-sha256", "output-root", "source-git-sha"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_copy(args)
    except Exception as exc:
        output = Path(args.output_root)
        if output.is_dir():
            write_receipt(output / "refusal.json", {"status": "FAILED_RETAIN_AND_INSPECT",
                          "error_type": type(exc).__name__,
                          "error": str(exc) if isinstance(exc, ValueError) else "archive scratch copy failed",
                          "source_retained": True, "deleted_files": 0, "cleanup_eligible": False,
                          "copied_files": None, "copied_bytes": None, "remote_side_effect_possible": True})
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps({name: result[name] for name in ("status", "direction", "copied_files", "copied_bytes")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
