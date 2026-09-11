"""Private file upload followed by an independent download and SHA-256 check."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time

from weather.operations import workstation_cold_archive_transfer as workstation
from weather.operations import workstation_cold_archive_io as local_io
from weather.paths import repo_path
from weather.schema_registry import schema_version

core = workstation.core
DEADLINE_SECONDS = 180


def run(*, attempt_id, expected_source_tip, bundle_path, bundle_sha256,
        rclone_executable, rclone_config, dpapi_secret, drive_remote_name, drive_root_folder_id,
        plain_file=False):
    repo = repo_path()
    core._require(core.crypt.ARCHIVE_ID_RE.fullmatch(attempt_id) is not None, "invalid backup attempt")
    deadline = time.monotonic() + (900 if plain_file else DEADLINE_SECONDS)
    with ExitStack() as stack:
        assignment, assignment_pin, assignment_identity, assignment_sha, host = workstation._assignment(repo, stack)
        identity = core.crypt._capture_tool_identity(repo)
        core._require(identity["git_commit"] == expected_source_tip
                      and identity["git_dirty"] is False, "backup source is not exact and clean")
        source = workstation._input_path(bundle_path)
        maximum = 1100 * core.MIB if plain_file else 2 * core.MIB
        if plain_file:
            core._require(source.is_relative_to(repo / "scratch" / "ac-in")
                          and source.stat().st_size <= maximum, "plain upload must be a bounded copied input")
            raw_sha = bundle_sha256
            core.archive._require_sha256(raw_sha)
        else:
            core._require(source.is_relative_to(repo / "scratch" / "ac-control")
                          and source.name.endswith("-recovery.json"), "backup accepts only campaign recovery metadata")
            bundle, raw_sha = core.archive._load(source, bundle_sha256)
            core._require(source.stat().st_size <= maximum
                          and bundle.get("contains_archive_payload") is False
                          and bundle.get("contains_credential_values") is False
                          and isinstance(bundle.get("records"), list)
                          and 1 <= len(bundle["records"]) <= 512, "invalid bounded recovery bundle")
        parent = repo / "scratch" / "ac-backup"
        if not parent.exists():
            parent.mkdir()
        core.archive._safe_path(parent, directory=True)
        stack.enter_context(core.archive._directory_pin(parent))
        attempt = parent / attempt_id
        attempt.mkdir()
        stack.enter_context(core.archive._directory_pin(attempt))
        modules = [Path(__file__), Path(workstation.__file__), Path(core.__file__),
                   Path(core.archive.__file__), Path(workstation.drive_id.__file__), Path(local_io.__file__)]
        paths = [source, *modules, Path(rclone_executable), Path(rclone_config), Path(dpapi_secret)]
        pins = [(stack.enter_context(core.bridge._file_pin(core.archive._safe_path(path))), path)
                for path in paths]
        before = [pin.metadata() for pin, _ in pins]
        def guard():
            core._require(os.environ.get(core.crypt.WRAPPER_ENV) == "1"
                          and time.monotonic() < deadline, "backup admission ended")
            core._require(assignment_pin.metadata() == assignment_identity
                          and hashlib.sha256(assignment.read_bytes()).hexdigest() == assignment_sha
                          and [pin.metadata() for pin, _ in pins] == before,
                          "backup assignment or input changed")
            return True
        arguments = dict(rclone_executable=rclone_executable, rclone_config=rclone_config,
                         dpapi_secret=dpapi_secret, drive_remote_name=drive_remote_name,
                         drive_root_folder_id=drive_root_folder_id)
        if plain_file:
            count, digest = core._sha_file(source, guard, deadline, maximum=maximum,
                                          guard_factory=local_io.ReadGuard)
            core._require(digest == raw_sha and count == source.stat().st_size,
                          "plain input hash differs before upload")
        active = workstation.prepare_credentials(
            arguments=arguments, attempt=attempt, admission=guard, deadline=deadline)
        active_pin = stack.enter_context(core.bridge._file_pin(active))
        active_identity = active_pin.metadata()
        secret, environment = None, {}
        def client_guard():
            guard()
            core._require(active_pin.metadata() == active_identity, "prepared backup credentials changed")
            return True
        try:
            secret = core.crypt._load_dpapi_secret(Path(dpapi_secret))
            environment = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith("RCLONE_")}
            environment[core.crypt.CONFIG_PASS_ENV] = secret.text()
            client = workstation.ExactNameDrive(
                rclone_executable, active, drive_remote_name, drive_root_folder_id,
                environment, client_guard, deadline)
            client.preflight()
            key = attempt_id + ("-" + source.name if plain_file else ".recovery.json")
            client.object(key, absent=True)
            size = source.stat().st_size
            client.copy(source, drive_remote_name + ":" + key, size)
            remote = client.object(key)
            core._require(remote["bytes"] == size, "backup remote size differs")
            client.committed_objects[key] = remote
            downloaded = attempt / ("downloaded-" + source.name if plain_file else "independent-recovery.json")
            client.copy(drive_remote_name + ":" + key, downloaded, size)
            count, digest = core._sha_file(
                downloaded, client_guard, deadline, maximum=maximum,
                guard_factory=local_io.ReadGuard)
            core._require(count == size and digest == raw_sha
                          and client.object(key) == remote, "independent recovery backup differs")
            client_guard()
            result = {
                "schema_version": schema_version("cold_archive_plain_upload" if plain_file else "cold_archive_campaign_backup"),
                "status": "PASS", "attempt_id": attempt_id, "source_tip": expected_source_tip,
                "execution_host_id": host, "bundle_sha256": raw_sha, "bytes": size,
                "drive": {"root_folder_id": drive_root_folder_id, **remote},
                "independent_download_verified": True, "originals_deleted": 0,
                "archive_payload_bytes_read": (3 * size if plain_file else 0),
                "payload_encryption": "none", "source_path": str(source),
                "downloaded_path": str(downloaded), "completed_at_utc": datetime.now(timezone.utc).isoformat()}
            core.archive._write(attempt / "receipt.json", core._seal(result))
            return result
        finally:
            environment.pop(core.crypt.CONFIG_PASS_ENV, None)
            if secret is not None:
                secret.wipe()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("attempt_id", "expected_source_tip", "bundle_path", "bundle_sha256",
                 "rclone_executable", "rclone_config", "dpapi_secret", "drive_remote_name", "drive_root_folder_id"):
        parser.add_argument("--" + name.replace("_", "-"), required=True)
    parser.add_argument("--plain-file", action="store_true")
    try:
        result = run(**vars(parser.parse_args(argv)))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__, "reason": str(exc)}))
        return 2
    print(json.dumps({key: result[key] for key in ("status", "attempt_id", "bundle_sha256")}))
    return 0
