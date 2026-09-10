"""Move already staged ciphertext through Drive on the admitted workstation.

The wrapper owns the non-capture host/principal lease and Windows Job. The
existing transfer core owns native pins, byte/memory/rate bounds and receipts.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

from weather import execution_host
from weather.operations import workstation_cold_archive_io as local_io
from weather.operations import cold_archive_drive_id as drive_id
from weather.operations import production_cold_archive_transfer_core as core
from weather.paths import REPO_ROOT
from weather.schema_registry import schema_version

DEADLINE_SECONDS = 900
WORKSTATION_RESERVE_BYTES = 20 * 1024**3
PATH_FIELDS = ("ciphertext_path", "crypt_receipt_path", "production_manifest_path",
               "production_receipt_path", "rclone_executable", "rclone_config",
               "dpapi_secret", "upload_receipt_path")


class ExactNameDrive(core.GuardedClient):
    """Require complete name absence, then retain immutable object IDs."""

    def _names(self, key):
        self.guard()
        core._require(drive_id.KEY.fullmatch(key) is not None, "invalid Drive key")
        query = f"'{self.root_folder_id}' in parents and trashed = false and name = '{key}'"
        url = "https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode({
            "pageSize": "2", "spaces": "drive", "q": query,
            "fields": "files(id,name),nextPageToken,incompleteSearch"})
        access = drive_id.token(self)
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + access, "Accept-Encoding": "identity"}, method="GET")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), drive_id.NoRedirect())
        try:
            with opener.open(request, timeout=min(10, max(.1, self.deadline - time.monotonic()))) as response:
                core._require(response.status == 200 and response.geturl() == url,
                              "unexpected Drive name response")
                raw = response.read(drive_id.MAX_METADATA + 1)
            core._require(len(raw) <= drive_id.MAX_METADATA, "Drive name response too large")
            value = json.loads(raw, object_pairs_hook=core.archive._pairs)
            core._require(isinstance(value, dict) and set(value) == {"files", "incompleteSearch"}
                          and value["incompleteSearch"] is False
                          and isinstance(value["files"], list) and len(value["files"]) <= 1,
                          "complete unambiguous Drive name lookup required")
            for row in value["files"]:
                core._require(isinstance(row, dict) and set(row) == {"id", "name"}
                              and row["name"] == key and isinstance(row["id"], str)
                              and drive_id.ID.fullmatch(row["id"]) is not None,
                              "Drive name identity differs")
            self.guard()
            return value["files"]
        except Exception:
            raise core.TransferError("complete Drive name lookup failed") from None
        finally:
            request.remove_header("Authorization")
            access = ""

    def object(self, key, *, absent=False):
        if not absent and key in self.committed_objects:
            return super().object(key)
        rows = self._names(key)
        if absent:
            core._require(not rows, "remote object absence not proved")
            return None
        core._require(len(rows) == 1, "uploaded object identity unavailable")
        value = drive_id.object_metadata(self, key, rows[0]["id"])
        self.committed_objects[key] = value
        return value


class _RefreshClient(core.GuardedClient):
    # Metadata-only refresh operates on a fresh encrypted copy, before payload work.
    ALLOWED_COMMANDS = core.GuardedClient.ALLOWED_COMMANDS | {("about",)}


def prepare_credentials(*, arguments, attempt, admission, deadline):
    """Refresh a new encrypted config; never mutate the supplied credential file."""
    source = Path(arguments["rclone_config"])
    executable = Path(arguments["rclone_executable"])
    secret_path = Path(arguments["dpapi_secret"])
    credential_root = attempt / "credentials"
    admission()
    credential_root.mkdir()
    active = credential_root / "drive.conf"
    secret, environment = None, {}
    with ExitStack() as stack:
        stack.enter_context(core.archive._directory_pin(credential_root))
        paths = (source, executable, secret_path)
        pins = [(stack.enter_context(core.bridge._file_pin(path)), path) for path in paths]
        before = [pin.metadata() for pin, _ in pins]
        def guard():
            core._require(admission() is True and time.monotonic() < deadline,
                          "credential preparation admission ended")
            core._require([pin.metadata() for pin, _ in pins] == before,
                          "credential preparation inputs changed")
            return True
        raw = core.crypt._read_stable_bytes(
            source, label="encrypted credential source", maximum_bytes=core.MAX_CONFIG_BYTES)
        try:
            with active.open("xb") as target:
                core._require(target.write(raw) == len(raw), "short credential copy")
                target.flush()
                os.fsync(target.fileno())
        finally:
            raw.clear()
        try:
            secret = core.crypt._load_dpapi_secret(secret_path)
            environment = {key: value for key, value in os.environ.items()
                           if not key.upper().startswith("RCLONE_")}
            environment[core.crypt.CONFIG_PASS_ENV] = secret.text()
            client = _RefreshClient(
                executable, active, arguments["drive_remote_name"],
                arguments["drive_root_folder_id"], environment, guard,
                min(deadline, time.monotonic() + 45))
            client.preflight()
            code, _ = client.run(["about", client.remote + ":", "--json"])
            core._require(code == 0, "metadata credential refresh failed")
            # Enough validity for the complete phase plus teardown. Failure is
            # before payload work and leaves both encrypted copies for inspection.
            access = drive_id.token(client, minimum_remaining_seconds=DEADLINE_SECONDS + 30)
            access = ""
            guard()
            core.archive._safe_path(active)
            config = core.crypt._read_stable_bytes(
                active, label="prepared encrypted credentials", maximum_bytes=core.MAX_CONFIG_BYTES)
            try:
                digest = hashlib.sha256(config).hexdigest()
            finally:
                config.clear()
            core.archive._write(credential_root / "receipt.json", core._seal({
                "status": "PASS", "config_sha256": digest,
                "source_config_unchanged": True, "archive_payload_bytes_read": 0,
                "minimum_remaining_seconds": DEADLINE_SECONDS + 30,
                "completed_at_utc": datetime.now(timezone.utc).isoformat()}))
            return active
        finally:
            environment.pop(core.crypt.CONFIG_PASS_ENV, None)
            if secret is not None:
                secret.wipe()


def _assignment(repo, stack):
    core._require(os.name == "nt" and os.environ.get(core.crypt.WRAPPER_ENV) == "1",
                  "native workstation wrapper required")
    path = repo / execution_host.EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
    pin = stack.enter_context(core.bridge._file_pin(core.archive._safe_path(path)))
    identity = pin.metadata()
    core._require(path.stat().st_size <= 16384, "host assignment exceeds bound")
    raw = path.read_bytes()
    value = json.loads(raw, object_pairs_hook=core.archive._pairs)
    host = execution_host.current_execution_host_id()
    principal = execution_host.current_execution_principal_id()
    core._require(value.get("schema_version") == execution_host.EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION
                  and value.get("assignment_status") == "ASSIGNED"
                  and value.get("active_portable_execution_host_id") == host
                  and value.get("active_portable_execution_principal_id") == principal
                  and value.get("dedicated_capture_execution_host_id") != host,
                  "assigned non-capture workstation required")
    return path, pin, identity, hashlib.sha256(raw).hexdigest(), host


def _input_path(value):
    path = Path(value)
    # Check names before touching a mirror. Recovery metadata is first exported
    # into scratch; no data tree is an input to this transport.
    core._require(not any(part.casefold() in {"data", "weather-mirror"} for part in path.parts),
                  "transfer inputs must be outside data and mirrors")
    return core.archive._safe_path(path)


def run(*, attempt_id, expected_source_tip, repo_root=REPO_ROOT, **arguments):
    repo = core.archive._safe_path(Path(repo_root), directory=True)
    core._require(re.fullmatch(r"[0-9a-f]{40}", expected_source_tip) is not None,
                  "exact source commit required")
    core._require(core.crypt.ARCHIVE_ID_RE.fullmatch(attempt_id) is not None,
                  "invalid transfer attempt")
    core._require(arguments.get("phase") in {"upload_only", "download_and_verify"},
                  "separate upload or download phase required")
    deadline = time.monotonic() + DEADLINE_SECONDS
    with ExitStack() as stack:
        assignment_path, assignment_pin, assignment_identity, assignment_sha, host = _assignment(repo, stack)
        identity = core.crypt._capture_tool_identity(repo)
        core._require(identity["git_commit"] == expected_source_tip, "reviewed source tip differs")
        for name in PATH_FIELDS:
            if arguments.get(name) is not None:
                arguments[name] = _input_path(arguments[name])
        parent = core.archive._safe_path(repo / "scratch" / "production_cold_archive_transport", directory=True)
        protected = core.archive._safe_path(repo / "data", directory=True)
        stack.enter_context(core.archive._directory_pin(parent))
        attempt = parent / attempt_id
        core._require(not attempt.exists(), "spent transfer attempt")
        attempt.mkdir()
        stack.enter_context(core.archive._directory_pin(attempt))
        modules = (Path(__file__), Path(core.__file__), Path(drive_id.__file__),
                   Path(core.crypt.__file__), Path(core.bridge.__file__), Path(core.archive.__file__),
                   Path(local_io.__file__))
        pins = [(stack.enter_context(core.bridge._file_pin(path)), path) for path in modules]
        before = [pin.metadata() for pin, _ in pins]
        claim = {
            "schema_version": schema_version("workstation_cold_archive_transfer_execution"),
            "status": "CLAIMED", "attempt_id": attempt_id, "archive_id": arguments["archive_id"],
            "phase": arguments["phase"], "source_git_sha": expected_source_tip,
            "execution_host_id": host, "assignment_sha256": assignment_sha,
            "tool_identity": identity,
            "module_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for _, p in pins},
            "source_retained": True, "deleted_files": 0, "reclaimed_bytes": 0,
            "cleanup_eligible": False, "started_at_utc": datetime.now(timezone.utc).isoformat()}
        core.archive._write(attempt / "claim.json", core._seal(dict(claim)))

        def guard():
            core._require(os.environ.get(core.crypt.WRAPPER_ENV) == "1" and time.monotonic() < deadline,
                          "workstation wrapper or transfer deadline ended")
            core._require(assignment_pin.metadata() == assignment_identity
                          and hashlib.sha256(assignment_path.read_bytes()).hexdigest() == assignment_sha,
                          "workstation assignment changed")
            core._require([pin.metadata() for pin, _ in pins] == before, "transfer source changed")
            return True

        try:
            guard()
            arguments["rclone_config"] = prepare_credentials(
                arguments=arguments, attempt=attempt, admission=guard, deadline=deadline)
            result = core.transfer_chunk(
                **arguments, output_root=attempt / "transfer", protected_root=protected,
                admission=guard, deadline_monotonic=deadline,
                free_space_reserve_bytes=WORKSTATION_RESERVE_BYTES,
                client_factory=ExactNameDrive, secret_loader=core.crypt._load_dpapi_secret,
                read_guard_factory=local_io.ReadGuard,
                hash_rate_bytes_per_second=local_io.READ_BYTES_PER_SECOND,
                network_rate_bytes_per_second=local_io.NETWORK_BUDGET_BYTES_PER_SECOND)
            guard()
            core._require(core.crypt._capture_tool_identity(repo) == identity, "source identity drift")
            receipt = attempt / "transfer" / "receipt.json"
            raw = receipt.read_bytes()
            core._require(json.loads(raw) == result and result["status"] == "PASS",
                          "transfer receipt readback mismatch")
            final = {**claim, "status": "PASS", "receipt_path": str(receipt),
                     "receipt_sha256": hashlib.sha256(raw).hexdigest(),
                     "upload_performed": result["upload_performed"],
                     "independent_download": result["independent_download"],
                     "completed_at_utc": datetime.now(timezone.utc).isoformat()}
            core.archive._write(attempt / "result.json", core._seal(final))
            return final
        except BaseException as exc:
            core.archive._write(attempt / "failure.json", core._seal({
                **claim, "status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__,
                "completed_at_utc": datetime.now(timezone.utc).isoformat()}))
            raise core.TransferError("workstation transfer failed; inspect retained receipts") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("upload_only", "download_and_verify"))
    required = ("attempt_id", "expected_source_tip", "crypt_receipt_path", "crypt_receipt_sha256",
                "production_manifest_path", "production_manifest_sha256", "production_receipt_path",
                "production_receipt_sha256", "plan_sha256", "archive_id", "rclone_executable",
                "rclone_config", "dpapi_secret", "drive_remote_name", "drive_root_folder_id")
    for field in required:
        parser.add_argument("--" + field.replace("_", "-"), required=True)
    for field in ("ciphertext_path", "upload_receipt_path", "upload_receipt_sha256"):
        parser.add_argument("--" + field.replace("_", "-"))
    try:
        result = run(**vars(parser.parse_args(argv)))
    except Exception as exc:
        print(json.dumps({"status": "FAILED_RETAIN_AND_INSPECT", "error_type": type(exc).__name__}))
        return 2
    print(json.dumps({key: result[key] for key in ("status", "attempt_id", "receipt_path", "receipt_sha256")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
