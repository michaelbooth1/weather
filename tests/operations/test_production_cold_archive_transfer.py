"""Synthetic transfer fixtures; no network, credentials, or production tape reads."""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from weather.operations import production_cold_archive_transfer as cli
from weather.operations import production_cold_archive_transfer_core as core
from weather.schema_registry import schema_version


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_evidence(path, value, field="receipt_hash"):
    value = dict(value)
    value.pop(field, None)
    core.archive._seal(value, field)
    Path(path).write_bytes(core.archive._canonical(value) + b"\n")
    return sha(path)


class FixturePin:
    """Metadata stand-in only; native pin/Job semantics have separate tests."""

    active = set()

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.active.add(self.path)
        return self

    def __exit__(self, *args):
        self.active.remove(self.path)

    def metadata(self):
        info = self.path.stat()
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


class FixtureSecret:
    def __init__(self):
        self.wiped = False

    def text(self):
        return "synthetic-passphrase"

    def wipe(self):
        self.wiped = True


class MemoryDrive:
    """Four opaque in-memory objects, independently materialized on download."""

    def __init__(self):
        self.objects = {}
        self.calls = []
        self.preflights = 0
        self.corrupt_suffix = None
        self.fail_upload = False
        self.fail_preflight = False
        self.refresh_config = False
        self.refuse_final_admission = False
        self.admitted = True
        self.environment = None

    def factory(self, executable, config, remote, root_folder_id, environment, admission, deadline):
        assert Path(config) in FixturePin.active
        assert remote == "archive_drive"
        assert root_folder_id == "fixture_root_12345"
        assert {key for key in environment if key.upper().startswith("RCLONE_")} == {"RCLONE_CONFIG_PASS"}
        assert environment["RCLONE_CONFIG_PASS"] == "synthetic-passphrase"
        self.config, self.environment, self.guard = Path(config), environment, admission
        return self

    def preflight(self):
        self.calls.append(("preflight",))
        self.preflights += 1
        if self.fail_preflight:
            raise core.TransferError("synthetic credential refusal")
        assert self.config in FixturePin.active
        if self.refresh_config:
            raise PermissionError("simulated native pinned-config sharing violation")
        if self.refuse_final_admission and self.preflights == 2:
            self.admitted = False

    def bind_uploaded_objects(self, records):
        assert len(records) == 4

    def object(self, key, *, absent=False):
        self.calls.append(("absence" if absent else "stat", key))
        if absent:
            if key in self.objects:
                raise core.TransferError("remote object absence not proved")
            return None
        raw = self.objects[key]
        return {"object_id": "object_" + hashlib.sha256(key.encode()).hexdigest()[:20],
                "remote_key": key, "bytes": len(raw), "hashes": {}}

    def copy(self, source, destination, maximum):
        if str(destination).startswith("archive_drive:"):
            key = str(destination).split(":", 1)[1]
            self.calls.append(("upload", key))
            assert key not in self.objects
            raw = Path(source).read_bytes()
            assert len(raw) <= maximum
            self.objects[key] = raw
            if self.fail_upload:
                raise core.TransferError("synthetic network failure after remote side effect")
        else:
            key = str(source).split(":", 1)[1]
            self.calls.append(("download", key))
            raw = self.objects[key]
            if self.corrupt_suffix and key.endswith(self.corrupt_suffix):
                raw = raw[:-1] + bytes([raw[-1] ^ 1])
            with Path(destination).open("xb") as stream:
                stream.write(raw)


@pytest.fixture
def transfer_fixture(tmp_path, monkeypatch):
    FixturePin.active = set()
    monkeypatch.setattr(core.bridge, "_file_pin", FixturePin)
    monkeypatch.setattr(core.archive, "_directory_pin", lambda path: nullcontext())
    monkeypatch.setenv("RCLONE_CONFIG", "ambient-config-must-not-leak")
    monkeypatch.setenv("RCLONE_PASSWORD_COMMAND", "ambient-command-must-not-run")
    inbox, support, output_parent, protected = [tmp_path / name for name in ("inbox", "support", "out", "data")]
    for path in (inbox, support, output_parent, protected):
        path.mkdir()
    paths = {}
    for key in ("rclone_executable", "rclone_config", "dpapi_secret"):
        paths[key] = support / key
        paths[key].write_bytes(b"synthetic encrypted fixture support")
    paths["ciphertext_path"] = inbox / "ciphertext.bin"
    paths["ciphertext_path"].write_bytes(b"RCLONE\0\0" + bytes(24) + b"opaque-ciphertext" * 32)
    paths["production_manifest_path"] = inbox / "manifest.json"
    paths["production_receipt_path"] = inbox / "stage.json"
    paths["crypt_receipt_path"] = inbox / "crypt.json"
    manifest = {
        "schema_version": schema_version("production_cold_archive_manifest"),
        "format": core.archive.FORMAT, "plan_sha256": "b" * 64, "plan_hash": "a" * 64,
        "chunk_id": "chunk-00000", "source_root": str(protected),
        "source_proof": "native_pinned_bytes_during_staging",
        "archive_sha256": "c" * 64, "archive_bytes": 128,
        "files": [{"path": "fixture/tape.jsonl", "size_bytes": 8, "mtime_ns": 1,
                   "device": 1, "file_id": 1, "allocated_bytes": 4096, "sha256": "d" * 64}],
        **core.archive.RETENTION}
    manifest_sha = write_evidence(paths["production_manifest_path"], manifest, "manifest_hash")
    manifest = json.loads(paths["production_manifest_path"].read_text())
    production = {
        "schema_version": schema_version("production_cold_archive_receipt"),
        "status": "PASS", "plan_sha256": "b" * 64, "plan_hash": "a" * 64,
        "chunk_id": "chunk-00000", "manifest_hash": manifest["manifest_hash"],
        "verification": {"status": "PASS", "file_count": 1, "archive_sha256": "c" * 64},
        **core.archive.RETENTION}
    production_sha = write_evidence(paths["production_receipt_path"], production)
    crypt = {
        "schema_version": schema_version("production_cold_archive_crypt_receipt"),
        "status": "PASS", "plan_sha256": "b" * 64, "archive_id": "fixture-archive-a1",
        "chunk_id": "chunk-00000", "production_manifest_sha256": manifest_sha,
        "production_receipt_sha256": production_sha, "archive_sha256": "c" * 64,
        "archive_bytes": 128, "source_retained": True, "cleanup_eligible": False,
        **core.bridge.RETENTION,
        "checks": {key: "PASS" for key in core.bridge.ENCRYPT_CHECKS},
        "tool_identity": {"tool": core.bridge.TOOL, "module_sha256": "1" * 64, "module_bytes": 1,
                          "git_commit": "2" * 40, "git_tree": "3" * 40,
                          "git_branch": "fixture", "git_dirty": False, "python": "3.12"},
        "ciphertext": {"bytes": paths["ciphertext_path"].stat().st_size,
                       "sha256": sha(paths["ciphertext_path"]),
                       "path_relative_to_ciphertext_root": "cipher-directory/cipher-object",
                       "file_identity": {"device": 1, "inode": 2, "mode": 0o100600,
                                         "bytes": paths["ciphertext_path"].stat().st_size, "mtime_ns": 3}}}
    crypt_sha = write_evidence(paths["crypt_receipt_path"], crypt)
    drive, secret = MemoryDrive(), FixtureSecret()
    args = dict(**paths, crypt_receipt_sha256=crypt_sha,
                production_manifest_sha256=manifest_sha, production_receipt_sha256=production_sha,
                plan_sha256="b" * 64, archive_id="fixture-archive-a1",
                drive_remote_name="archive_drive", drive_root_folder_id="fixture_root_12345",
                output_root=output_parent / "attempt", protected_root=protected,
                admission=lambda: drive.admitted, deadline_monotonic=time.monotonic() + 250,
                free_space_reserve_bytes=0, client_factory=drive.factory,
                secret_loader=lambda path: secret)
    return SimpleNamespace(args=args, drive=drive, secret=secret, paths=paths)


def retained_receipt(fixture):
    value = json.loads((fixture.args["output_root"] / "receipt.json").read_text())
    core.archive._check_seal(value, "receipt_hash")
    assert value["source_retained"] is True
    assert value["cleanup_eligible"] is value["deletion_authorized"] is False
    assert value["deleted_files"] == value["reclaimed_bytes"] == 0
    return value




def test_bound_object_read_retries_transient_absence_without_accepting_absence(tmp_path, monkeypatch):
    client = core.GuardedClient(tmp_path / "rclone.exe", tmp_path / "client.conf",
                                "archive_drive", "fixture_root_12345", {}, lambda: True,
                                time.monotonic() + 250)
    replies = iter([(3, b""), (1, b"null"), (1, b""), (0, json.dumps({
        "Name": "bound.bin", "IsDir": False, "Size": 7, "ID": "fixture_object_12345",
        "Hashes": {"sha256": "a" * 64}}).encode())])
    calls = []
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    def run(tokens, *, capture=False):
        calls.append(tokens)
        return next(replies)
    monkeypatch.setattr(client, "run", run)
    assert client.object("bound.bin")["object_id"] == "fixture_object_12345"
    assert len(calls) == 4


@pytest.mark.parametrize("code", [1, 3])
def test_bound_object_read_stops_after_four_absent_results(tmp_path, monkeypatch, code):
    client = core.GuardedClient(tmp_path / "rclone.exe", tmp_path / "client.conf",
                                "archive_drive", "fixture_root_12345", {}, lambda: True,
                                time.monotonic() + 250)
    calls = []
    monkeypatch.setattr(core.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(client, "run", lambda *args, **kwargs: (calls.append(1) or code, b""))
    with pytest.raises(core.TransferError, match="metadata unavailable"):
        client.object("bound.bin")
    assert len(calls) == 4


def test_download_retry_never_overwrites_a_partially_created_destination(tmp_path, monkeypatch):
    client = core.GuardedClient(tmp_path / "rclone.exe", tmp_path / "client.conf",
                                "archive_drive", "fixture_root_12345", {}, lambda: True,
                                time.monotonic() + 250)
    target = tmp_path / "download.bin"
    calls = []
    def run(tokens, *, capture=False):
        calls.append(tokens)
        target.write_bytes(b"partial")
        client.last_failure = {"exit_code": 3, "stderr_bytes": 0}
        return 3, b""
    monkeypatch.setattr(client, "run", run)
    with pytest.raises(core.TransferError, match="create-only transfer failed"):
        client.copy("archive_drive:bound.bin", target, 20)
    assert len(calls) == 1
    assert target.read_bytes() == b"partial"


def test_upload_is_never_automatically_retried(tmp_path, monkeypatch):
    client = core.GuardedClient(tmp_path / "rclone.exe", tmp_path / "client.conf",
                                "archive_drive", "fixture_root_12345", {}, lambda: True,
                                time.monotonic() + 250)
    calls = []
    def run(tokens, *, capture=False):
        calls.append(tokens)
        client.last_failure = {"exit_code": 3, "stderr_bytes": 0}
        return 3, b""
    monkeypatch.setattr(client, "run", run)
    with pytest.raises(core.TransferError, match="create-only transfer failed"):
        client.copy(tmp_path / "input.bin", "archive_drive:bound.bin", 20)
    assert len(calls) == 1


def test_four_object_roundtrip_retains_sources_and_clears_private_secret(transfer_fixture):
    f = transfer_fixture
    before = {name: path.read_bytes() for name, path in f.paths.items()}
    result = core.transfer_chunk(**f.args)
    assert result == retained_receipt(f)
    assert result["status"] == "PASS"
    assert result["phase"] == "upload_and_independent_download"
    assert result["upload_performed"] is result["independent_download"] is True
    assert len(result["metadata_objects"]) == 3
    assert {item["kind"] for item in result["metadata_objects"]} == {
        "production_manifest", "production_receipt", "crypt_receipt"}
    assert Path(result["downloaded_file"]["path"]).read_bytes() == before["ciphertext_path"]
    assert sum(call[0] == "upload" for call in f.drive.calls) == 4
    assert sum(call[0] == "download" for call in f.drive.calls) == 4
    first_upload = next(index for index, call in enumerate(f.drive.calls) if call[0] == "upload")
    assert sum(call[0] == "absence" for call in f.drive.calls[:first_upload]) == 4
    assert {name: path.read_bytes() for name, path in f.paths.items()} == before
    assert f.secret.wiped
    assert "RCLONE_CONFIG_PASS" not in f.drive.environment
    assert "synthetic-passphrase" not in json.dumps(result)
    assert not FixturePin.active


@pytest.mark.parametrize("suffix", [".rclone.bin", ".manifest.json", ".stage.json", ".crypt.json"])
def test_any_corrupt_independent_download_fails_and_retains_attempt(transfer_fixture, suffix):
    f = transfer_fixture
    f.drive.corrupt_suffix = suffix
    with pytest.raises(core.TransferError, match="independent download mismatch"):
        core.transfer_chunk(**f.args)
    receipt = retained_receipt(f)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["upload_performed"] is None
    assert receipt["remote_side_effect_possible"] is True
    assert receipt["independent_download"] is False
    assert f.secret.wiped


def test_last_metadata_namespace_collision_refuses_before_first_upload(transfer_fixture):
    f = transfer_fixture
    key = f.args["archive_id"] + ".crypt.json"
    f.drive.objects[key] = b"retained-existing-object"
    with pytest.raises(core.TransferError, match="absence"):
        core.transfer_chunk(**f.args)
    assert f.drive.objects == {key: b"retained-existing-object"}
    assert not any(call[0] == "upload" for call in f.drive.calls)
    assert retained_receipt(f)["upload_performed"] is False


def test_network_failure_preserves_unknown_upload_state(transfer_fixture):
    f = transfer_fixture
    f.drive.fail_upload = True
    with pytest.raises(core.TransferError, match="network failure"):
        core.transfer_chunk(**f.args)
    receipt = retained_receipt(f)
    assert receipt["upload_performed"] is None
    assert receipt["remote_side_effect_possible"] is True
    assert receipt["independent_download"] is False
    assert len(f.drive.objects) == 1
    assert "network failure" not in json.dumps(receipt)


@pytest.mark.parametrize("failure", ["secret", "preflight"])
def test_credential_preflight_precedes_ciphertext_content_reads(transfer_fixture, monkeypatch, failure):
    f = transfer_fixture
    original_open = Path.open
    reads = []

    def checked_open(path, *args, **kwargs):
        if path == f.paths["ciphertext_path"]:
            reads.append(path)
            pytest.fail("ciphertext content opened before credential preflight")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    if failure == "secret":
        def refuse(path):
            raise core.TransferError("synthetic secret refusal")
        f.args["secret_loader"] = refuse
    else:
        f.drive.fail_preflight = True
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**f.args)
    assert not reads
    assert not any(call[0] == "upload" for call in f.drive.calls)
    assert retained_receipt(f)["upload_performed"] is False


def test_final_admission_refusal_cannot_publish_pass(transfer_fixture):
    f = transfer_fixture
    f.drive.refuse_final_admission = True
    with pytest.raises(core.TransferError, match="admission"):
        core.transfer_chunk(**f.args)
    receipt = retained_receipt(f)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["upload_performed"] is None
    assert receipt["independent_download"] is False


def test_token_refresh_fails_closed_while_source_and_attempt_configs_are_pinned(transfer_fixture):
    f = transfer_fixture
    original = f.paths["rclone_config"].read_bytes()
    f.drive.refresh_config = True
    with pytest.raises(PermissionError, match="pinned-config"):
        core.transfer_chunk(**f.args)
    assert f.paths["rclone_config"].read_bytes() == original
    assert f.drive.config == f.args["output_root"] / "client.conf"
    assert f.drive.config.read_bytes() == original
    assert not any(call[0] == "upload" for call in f.drive.calls)
    assert retained_receipt(f)["status"] == "FAIL_CLOSED"
    assert not FixturePin.active


@pytest.mark.parametrize("phase", ["upload_and_independent_download", "download_and_verify"])
def test_downloads_remain_pinned_until_final_receipt_is_written(transfer_fixture, monkeypatch, phase):
    f = transfer_fixture
    if phase == "download_and_verify":
        prepare_download(f)
    original_write = core.archive._write
    observed = []

    def checked_write(path, value):
        if Path(path).name == "receipt.json" and value["status"] == "PASS":
            expected = {f.args["output_root"] / ("downloaded-" + key) for key in f.drive.objects}
            assert len(expected) == 4
            assert expected <= FixturePin.active
            assert f.drive.config in FixturePin.active
            if phase == "download_and_verify":
                assert f.args["upload_receipt_path"] in FixturePin.active
            observed.append(True)
        return original_write(path, value)

    monkeypatch.setattr(core.archive, "_write", checked_write)
    core.transfer_chunk(**f.args)
    assert observed == [True]
    assert not FixturePin.active


def test_spent_local_attempt_cannot_be_reused(transfer_fixture):
    f = transfer_fixture
    core.transfer_chunk(**f.args)
    calls = list(f.drive.calls)
    with pytest.raises(core.TransferError, match="attempt must be new"):
        core.transfer_chunk(**f.args)
    assert f.drive.calls == calls
    assert retained_receipt(f)["status"] == "PASS"


@pytest.mark.parametrize("field", ["crypt_receipt_sha256", "production_manifest_sha256",
                                  "production_receipt_sha256", "plan_sha256", "archive_id"])
def test_bound_input_mismatch_refuses_before_credentials(transfer_fixture, field):
    f = transfer_fixture
    f.args[field] = "other-archive" if field == "archive_id" else "0" * 64
    with pytest.raises(ValueError):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls
    assert not f.args["output_root"].exists()


@pytest.mark.parametrize("field,value", [("schema_version", "unsupported"),
    ("status", "FAIL_CLOSED"), ("source_retained", False), ("cleanup_eligible", True),
    ("deletion_authorized", True), ("source_retained", 1)])
def test_crypt_schema_and_retention_are_typed_authority(transfer_fixture, field, value):
    f = transfer_fixture
    path = f.paths["crypt_receipt_path"]
    receipt = json.loads(path.read_text())
    receipt[field] = value
    f.args["crypt_receipt_sha256"] = write_evidence(path, receipt)
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls


@pytest.mark.parametrize("kind", ["missing_check", "extra_check", "failed_check", "bad_tool",
                                  "dirty_tool", "fresh_identity", "cipher_identity", "cipher_path"])
def test_crypt_requires_complete_checks_and_recorded_tool_and_cipher_identity(transfer_fixture, kind):
    f = transfer_fixture
    path = f.paths["crypt_receipt_path"]
    receipt = json.loads(path.read_text())
    if kind == "missing_check":
        receipt["checks"].pop(core.bridge.ENCRYPT_CHECKS[0])
    elif kind == "extra_check":
        receipt["checks"]["invented"] = "PASS"
    elif kind == "failed_check":
        receipt["checks"]["cryptcheck"] = "FAIL"
    elif kind == "bad_tool":
        receipt["tool_identity"]["tool"] = "unqualified"
    elif kind == "dirty_tool":
        receipt["tool_identity"]["git_dirty"] = True
    elif kind == "fresh_identity":
        receipt["fresh_production_identity_proved"] = True
    elif kind == "cipher_identity":
        receipt["ciphertext"]["file_identity"]["bytes"] += 1
    else:
        receipt["ciphertext"]["path_relative_to_ciphertext_root"] = "../escape"
    f.args["crypt_receipt_sha256"] = write_evidence(path, receipt)
    with pytest.raises((core.TransferError, core.crypt.ArchiveStageError)):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls


@pytest.mark.parametrize("kind,field,value", [
    ("manifest", "schema_version", "unsupported"),
    ("manifest", "source_proof", "unproved"),
    ("manifest", "source_retained", False),
    ("stage", "schema_version", "unsupported"),
    ("stage", "cleanup_eligible", True),
])
def test_production_evidence_schema_and_proof_are_required(transfer_fixture, kind, field, value):
    f = transfer_fixture
    manifest_path, stage_path, crypt_path = (f.paths[key] for key in (
        "production_manifest_path", "production_receipt_path", "crypt_receipt_path"))
    manifest, stage, crypt = [json.loads(path.read_text()) for path in (manifest_path, stage_path, crypt_path)]
    (manifest if kind == "manifest" else stage)[field] = value
    manifest_sha = write_evidence(manifest_path, manifest, "manifest_hash")
    stage["manifest_hash"] = json.loads(manifest_path.read_text())["manifest_hash"]
    stage_sha = write_evidence(stage_path, stage)
    crypt.update(production_manifest_sha256=manifest_sha, production_receipt_sha256=stage_sha)
    f.args.update(production_manifest_sha256=manifest_sha, production_receipt_sha256=stage_sha,
                  crypt_receipt_sha256=write_evidence(crypt_path, crypt))
    with pytest.raises((core.TransferError, core.crypt.ArchiveStageError)):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls


def test_modified_ciphertext_refuses_before_upload(transfer_fixture):
    f = transfer_fixture
    with f.paths["ciphertext_path"].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(core.TransferError, match="ciphertext input mismatch"):
        core.transfer_chunk(**f.args)
    assert not any(call[0] == "upload" for call in f.drive.calls)


def test_transfer_budget_covers_two_hashes_two_transfers_and_teardown():
    size = 1024 * core.MIB
    assert core.required_transfer_seconds(size) == pytest.approx(429)
    assert core.required_transfer_seconds(size, initial_hash_done=True) == pytest.approx(365)


def test_infeasible_deadline_refuses_before_claim_or_credentials(transfer_fixture):
    f = transfer_fixture
    f.args["deadline_monotonic"] = time.monotonic() + 44
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**f.args)
    assert not f.args["output_root"].exists()
    assert not f.drive.calls


def test_budget_rechecked_after_hash_and_all_absence_checks(transfer_fixture, monkeypatch):
    f = transfer_fixture
    clock = [time.monotonic()]
    monkeypatch.setattr(core.time, "monotonic", lambda: clock[0])
    f.args["deadline_monotonic"] = clock[0] + 250
    original_object = f.drive.object

    def slow_absence(key, *, absent=False):
        result = original_object(key, absent=absent)
        if absent and key.endswith(".crypt.json"):
            clock[0] = f.args["deadline_monotonic"] - 44
        return result

    monkeypatch.setattr(f.drive, "object", slow_absence)
    # Avoid a stationary fake clock inside the real bandwidth sleeping loop.
    def fixture_hash(path, admit, deadline, maximum=core.MAX_CIPHERTEXT_BYTES):
        assert admit() is True
        raw = Path(path).read_bytes()
        assert len(raw) <= maximum
        return len(raw), hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(core, "_sha_file", fixture_hash)
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**f.args)
    assert not any(call[0] == "upload" for call in f.drive.calls)
    assert retained_receipt(f)["upload_performed"] is False


@pytest.fixture
def request_fixture(transfer_fixture, tmp_path):
    f = transfer_fixture
    now = datetime.now(timezone.utc)
    root = tmp_path / "production"
    root.mkdir()
    request = {
        "schema_version": schema_version("production_cold_archive_transfer_request"),
        "production_repo_root": str(root), "execution_host_id": "e" * 64,
        "operation": "upload_and_independent_download", "approved_by": "fixture owner",
        "approved_at_utc": (now - timedelta(minutes=1)).isoformat(),
        "expires_at_utc": (now + timedelta(hours=1)).isoformat(),
        "plan_path": str(tmp_path / "plan.json"), "chunk_id": "chunk-00000",
        "source_git_sha": "f" * 40, "archive_id": f.args["archive_id"],
        "drive_remote_name": f.args["drive_remote_name"],
        "drive_root_folder_id": f.args["drive_root_folder_id"],
        **{key: str(f.args[key]) for key in cli.PATH_FIELDS},
        **{key: f.args[key] for key in cli.HASH_FIELDS}}
    return request, root, now


def test_transfer_request_accepts_exact_bound_contract(request_fixture):
    request, root, now = request_fixture
    assert cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40) == request


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unsupported"), ("operation", "delete"),
    ("extra", "not-allowed"), ("source_git_sha", "0" * 40),
    ("approved_by", " "), ("plan_sha256", "B" * 64),
    ("execution_host_id", "bad"), ("chunk_id", "chunk-1"),
    ("drive_remote_name", "remote:path"), ("drive_root_folder_id", "short"),
    ("ciphertext_path", "relative.bin"), ("plan_path", "../plan.json"),
    ("production_repo_root", "different-root"),
])
def test_transfer_request_rejects_schema_paths_and_bindings(request_fixture, field, value):
    request, root, now = request_fixture
    request[field] = value
    with pytest.raises(ValueError):
        cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)


@pytest.mark.parametrize("kind", ["expired", "future", "overlong", "missing"])
def test_transfer_request_requires_current_complete_approval(request_fixture, kind):
    request, root, now = request_fixture
    if kind == "expired":
        request["expires_at_utc"] = now.isoformat()
    elif kind == "future":
        request["approved_at_utc"] = (now + timedelta(minutes=1)).isoformat()
    elif kind == "overlong":
        request["expires_at_utc"] = (now + timedelta(days=4)).isoformat()
    else:
        request.pop("dpapi_secret")
    with pytest.raises(ValueError):
        cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)


def test_cli_rejects_changed_raw_request_before_lease_or_transfer(request_fixture, tmp_path, monkeypatch):
    request, root, _ = request_fixture
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    approved_sha = sha(path)
    path.write_text(json.dumps({**request, "approved_by": "changed"}))
    args = SimpleNamespace(request_sha256=approved_sha, source_git_sha="f" * 40)
    calls = []
    monkeypatch.setattr(core, "transfer_chunk", lambda **kwargs: calls.append(kwargs))
    with pytest.raises(ValueError, match="digest mismatch"):
        cli._run_pinned(args, root, tmp_path, path)
    assert not calls


@pytest.mark.parametrize("scope,kind,encrypted", [
    ("drive.file", "drive", True), ("drive", "drive", True),
    ("drive.file", "s3", True), ("drive.file", "drive", False),
])
def test_client_preflight_requires_encrypted_restricted_drive_config(tmp_path, monkeypatch, scope, kind, encrypted):
    client = core.GuardedClient(tmp_path / "rclone.exe", tmp_path / "client.conf",
                                "archive_drive", "fixture_root_12345", {}, lambda: True,
                                time.monotonic() + 250)
    calls = []

    def run(tokens, *, capture=False):
        calls.append(tokens)
        if tokens == ["config", "encryption", "check"]:
            return (0 if encrypted else 1), b""
        assert tokens == ["config", "redacted", "archive_drive"]
        return 0, f"[archive_drive]\ntype = {kind}\nscope = {scope}\n".encode()

    monkeypatch.setattr(client, "run", run)
    if encrypted and scope == "drive.file" and kind == "drive":
        client.preflight()
    else:
        with pytest.raises(core.TransferError):
            client.preflight()
    assert calls[0] == ["config", "encryption", "check"]
    if not encrypted:
        assert len(calls) == 1



def prepare_download(fixture):
    upload_args = {**fixture.args, "phase": "upload_only"}
    uploaded = core.transfer_chunk(**upload_args)
    path = fixture.args["output_root"] / "receipt.json"
    fixture.args.update(phase="download_and_verify", upload_receipt_path=path,
                        upload_receipt_sha256=sha(path),
                        output_root=fixture.args["output_root"].parent / "download-attempt",
                        deadline_monotonic=time.monotonic() + 250)
    fixture.drive.calls.clear()
    fixture.drive.preflights = 0
    fixture.secret = FixtureSecret()
    fixture.args["secret_loader"] = lambda path: fixture.secret
    return uploaded, path


@pytest.mark.parametrize("omit_path", [False, True])
def test_download_survives_original_ciphertext_removal(transfer_fixture, omit_path):
    f = transfer_fixture
    uploaded, _ = prepare_download(f)
    f.paths["ciphertext_path"].unlink()
    if omit_path:
        f.args.pop("ciphertext_path")
    result = core.transfer_chunk(**f.args)
    assert result["status"] == "PASS"
    assert result["independent_download"] is True and result["upload_performed"] is False
    assert sha(Path(result["downloaded_file"]["path"])) == uploaded["ciphertext"]["sha256"]
    assert not any(call[0] == "upload" for call in f.drive.calls)


def test_download_without_original_still_rejects_corruption(transfer_fixture):
    f = transfer_fixture
    prepare_download(f)
    f.args.pop("ciphertext_path").unlink()
    f.drive.corrupt_suffix = ".rclone.bin"
    with pytest.raises(core.TransferError, match="independent download mismatch"):
        core.transfer_chunk(**f.args)
    assert retained_receipt(f)["status"] == "FAIL_CLOSED"


def test_download_request_can_omit_original_ciphertext(request_fixture):
    request, root, now = request_fixture
    request.update(operation="download_and_verify", upload_receipt_path=str(root / "upload.json"),
                   upload_receipt_sha256="a" * 64)
    request.pop("ciphertext_path")
    assert cli.validate_request(request, production_root=root, now=now,
                                source_git_sha="f" * 40) == request
    request.update(operation="upload_only")
    request.pop("upload_receipt_path")
    request.pop("upload_receipt_sha256")
    with pytest.raises(ValueError, match="fields"):
        cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)


def test_upload_only_commits_four_identities_without_downloading(transfer_fixture):
    f = transfer_fixture
    result = core.transfer_chunk(**{**f.args, "phase": "upload_only"})
    assert result == retained_receipt(f)
    assert result["schema_version"] == schema_version("production_cold_archive_upload_receipt")
    assert result["phase"] == "upload_only"
    assert result["status"] == "PASS"
    assert result["upload_performed"] is True
    assert result["independent_download"] is False
    assert "downloaded_file" not in result
    assert not list(f.args["output_root"].glob("downloaded-*"))
    assert sum(call[0] == "upload" for call in f.drive.calls) == 4
    assert not any(call[0] == "download" for call in f.drive.calls)
    assert result["drive"]["bytes"] == f.paths["ciphertext_path"].stat().st_size
    assert result["drive"]["sha256"] == sha(f.paths["ciphertext_path"])
    assert result["drive"]["hashes"] == {}
    assert len(result["metadata_objects"]) == 3
    ids = {result["drive"]["object_id"], *(item["object_id"] for item in result["metadata_objects"])}
    assert len(ids) == 4
    for record in result["metadata_objects"]:
        assert set(record) == {"kind", "object_id", "remote_key", "bytes", "hashes", "sha256"}
        assert hashlib.sha256(f.drive.objects[record["remote_key"]]).hexdigest() == record["sha256"]
        assert len(f.drive.objects[record["remote_key"]]) == record["bytes"]
    assert not FixturePin.active


def test_split_download_uses_bound_objects_without_reading_original_cipher(transfer_fixture, monkeypatch):
    f = transfer_fixture
    uploaded, upload_path = prepare_download(f)
    original_open = Path.open
    hash_paths = []
    original_hash = core._sha_file

    def checked_open(path, *args, **kwargs):
        if path == f.paths["ciphertext_path"]:
            pytest.fail("download-only opened the original ciphertext for content")
        return original_open(path, *args, **kwargs)

    def checked_hash(path, *args, **kwargs):
        assert Path(path) != f.paths["ciphertext_path"]
        hash_paths.append(Path(path))
        return original_hash(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    monkeypatch.setattr(core, "_sha_file", checked_hash)
    result = core.transfer_chunk(**f.args)
    assert result == retained_receipt(f)
    assert result["schema_version"] == schema_version("production_cold_archive_transport_receipt")
    assert result["phase"] == "download_and_verify"
    assert result["upload_performed"] is False
    assert result["independent_download"] is True
    assert result["upload_receipt_sha256"] == sha(upload_path)
    assert result["drive"]["object_id"] == uploaded["drive"]["object_id"]
    assert sum(call[0] == "download" for call in f.drive.calls) == 4
    assert not any(call[0] in {"upload", "absence"} for call in f.drive.calls)
    assert len(hash_paths) == 4
    assert {path.name for path in hash_paths} == {"downloaded-" + key for key in f.drive.objects}
    assert not FixturePin.active


@pytest.mark.parametrize("phase", ["upload_only", "download_and_verify"])
def test_split_phase_budget_includes_one_hash_and_one_copy(phase):
    assert core.required_transfer_seconds(1024 * core.MIB, phase=phase) == pytest.approx(237)
    if phase == "upload_only":
        assert core.required_transfer_seconds(1024 * core.MIB, phase=phase,
                                              initial_hash_done=True) == pytest.approx(173)
    else:
        with pytest.raises(core.TransferError, match="cannot be skipped"):
            core.required_transfer_seconds(1024 * core.MIB, phase=phase, initial_hash_done=True)


@pytest.mark.parametrize("phase", ["upload_only", "download_and_verify"])
def test_split_phase_refuses_infeasible_budget_before_claim(transfer_fixture, phase):
    f = transfer_fixture
    if phase == "download_and_verify":
        prepare_download(f)
    f.args.update(phase=phase, deadline_monotonic=time.monotonic() + 44)
    with pytest.raises(core.TransferError, match="remaining transfer deadline"):
        core.transfer_chunk(**f.args)
    assert not f.args["output_root"].exists()
    assert not f.drive.calls


@pytest.mark.parametrize("phase", ["upload_only", "download_and_verify"])
def test_split_phase_rechecks_budget_before_any_copy(transfer_fixture, monkeypatch, phase):
    f = transfer_fixture
    if phase == "download_and_verify":
        prepare_download(f)
    f.args["phase"] = phase
    clock = [time.monotonic()]
    f.args["deadline_monotonic"] = clock[0] + 250
    monkeypatch.setattr(core.time, "monotonic", lambda: clock[0])
    original_object = f.drive.object

    def slow_probe(key, *, absent=False):
        result = original_object(key, absent=absent)
        if key.endswith(".crypt.json"):
            clock[0] = f.args["deadline_monotonic"] - 44
        return result

    def bounded_fixture_hash(path, admit, deadline, maximum=core.MAX_CIPHERTEXT_BYTES):
        assert admit() is True
        raw = Path(path).read_bytes()
        assert len(raw) <= maximum
        return len(raw), hashlib.sha256(raw).hexdigest()

    monkeypatch.setattr(f.drive, "object", slow_probe)
    monkeypatch.setattr(core, "_sha_file", bounded_fixture_hash)
    with pytest.raises(core.TransferError, match="remaining transfer"):
        core.transfer_chunk(**f.args)
    assert not any(call[0] in {"upload", "download"} for call in f.drive.calls)
    assert retained_receipt(f)["status"] == "FAIL_CLOSED"


@pytest.mark.parametrize("phase,path,digest", [
    ("download_and_verify", None, None), ("download_and_verify", "given", None),
    ("download_and_verify", None, "a" * 64), ("upload_only", "given", "a" * 64),
    ("upload_and_independent_download", "given", "a" * 64), ("unsupported", None, None),
])
def test_phase_requires_exact_upload_receipt_arguments(transfer_fixture, phase, path, digest):
    f = transfer_fixture
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**{**f.args, "phase": phase, "upload_receipt_path": path,
                               "upload_receipt_sha256": digest})
    assert not f.drive.calls
    assert not f.args["output_root"].exists()


def test_download_refuses_changed_raw_upload_receipt_before_client(transfer_fixture):
    f = transfer_fixture
    prepare_download(f)
    f.args["upload_receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls
    assert not f.args["output_root"].exists()


@pytest.mark.parametrize("field,value", [
    ("schema_version", "unsupported"), ("phase", "upload_and_independent_download"),
    ("status", "FAIL_CLOSED"), ("archive_id", "different-archive"), ("chunk_id", "chunk-00001"),
    ("plan_sha256", "0" * 64), ("crypt_receipt_sha256", "0" * 64),
    ("production_manifest_sha256", "0" * 64), ("production_receipt_sha256", "0" * 64),
    ("source_retained", False), ("cleanup_eligible", True), ("deletion_authorized", True),
    ("deleted_files", 1), ("reclaimed_bytes", 1), ("upload_performed", False),
    ("independent_download", True), ("remote_side_effect_possible", False),
])
def test_download_upload_receipt_common_bindings_are_exact(transfer_fixture, field, value):
    f = transfer_fixture
    uploaded, _ = prepare_download(f)
    changed = dict(uploaded)
    changed[field] = value
    path = f.paths["crypt_receipt_path"].parent / "changed-upload.json"
    f.args.update(upload_receipt_path=path, upload_receipt_sha256=write_evidence(path, changed))
    with pytest.raises(core.TransferError, match="upload receipt binding"):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls
    assert not f.args["output_root"].exists()


@pytest.mark.parametrize("kind", [
    "root", "cipher_size", "cipher_sha", "cipher_key", "missing_metadata",
    "extra_metadata", "duplicate_kind", "duplicate_id", "metadata_size",
    "metadata_sha", "metadata_key", "nonstring_id", "bad_hashes",
])
def test_download_requires_exact_complete_upload_object_set(transfer_fixture, kind):
    f = transfer_fixture
    uploaded, _ = prepare_download(f)
    changed = json.loads(json.dumps(uploaded))
    if kind == "root":
        changed["drive"]["root_folder_id"] = "different_root_12345"
    elif kind == "cipher_size":
        changed["drive"]["bytes"] += 1
    elif kind == "cipher_sha":
        changed["drive"]["sha256"] = "0" * 64
    elif kind == "cipher_key":
        changed["drive"]["remote_key"] = "different.bin"
    elif kind == "missing_metadata":
        changed["metadata_objects"].pop()
    elif kind == "extra_metadata":
        changed["metadata_objects"].append(dict(changed["metadata_objects"][0]))
    elif kind == "duplicate_kind":
        changed["metadata_objects"][1]["kind"] = changed["metadata_objects"][0]["kind"]
    elif kind == "duplicate_id":
        changed["metadata_objects"][0]["object_id"] = changed["drive"]["object_id"]
    elif kind == "metadata_size":
        changed["metadata_objects"][0]["bytes"] += 1
    elif kind == "metadata_sha":
        changed["metadata_objects"][0]["sha256"] = "0" * 64
    elif kind == "metadata_key":
        changed["metadata_objects"][0]["remote_key"] = "wrong.json"
    elif kind == "nonstring_id":
        changed["metadata_objects"][0]["object_id"] = 12345678901
    else:
        changed["metadata_objects"][0]["hashes"] = ["untrusted"]
    path = f.paths["crypt_receipt_path"].parent / "changed-upload.json"
    f.args.update(upload_receipt_path=path, upload_receipt_sha256=write_evidence(path, changed))
    with pytest.raises(core.TransferError):
        core.transfer_chunk(**f.args)
    assert not f.drive.calls
    assert not f.args["output_root"].exists()


@pytest.mark.parametrize("suffix", [".rclone.bin", ".manifest.json", ".stage.json", ".crypt.json"])
def test_split_download_refuses_remote_identity_change_before_any_copy(transfer_fixture, monkeypatch, suffix):
    f = transfer_fixture
    prepare_download(f)
    original_object = f.drive.object

    def replaced_object(key, *, absent=False):
        result = original_object(key, absent=absent)
        if key.endswith(suffix):
            result["object_id"] = "replacement_object_12345"
        return result

    monkeypatch.setattr(f.drive, "object", replaced_object)
    with pytest.raises(core.TransferError, match="committed upload object changed"):
        core.transfer_chunk(**f.args)
    assert not any(call[0] in {"upload", "download"} for call in f.drive.calls)
    assert retained_receipt(f)["status"] == "FAIL_CLOSED"


def test_download_rechecks_committed_id_immediately_before_each_copy(transfer_fixture, monkeypatch):
    f = transfer_fixture
    prepare_download(f)
    original_object = f.drive.object
    seen = {}

    def replaced_after_initial_probe(key, *, absent=False):
        result = original_object(key, absent=absent)
        seen[key] = seen.get(key, 0) + 1
        if key.endswith(".manifest.json") and seen[key] == 2:
            result["object_id"] = "replacement_object_12345"
        return result

    monkeypatch.setattr(f.drive, "object", replaced_after_initial_probe)
    with pytest.raises(core.TransferError, match="committed upload object changed"):
        core.transfer_chunk(**f.args)
    assert sum(call[0] == "download" for call in f.drive.calls) == 1
    assert not any(call[0] == "upload" for call in f.drive.calls)
    assert retained_receipt(f)["independent_download"] is False


@pytest.mark.parametrize("suffix", [".rclone.bin", ".manifest.json", ".stage.json", ".crypt.json"])
def test_split_download_rejects_corrupt_bytes_without_upload(transfer_fixture, suffix):
    f = transfer_fixture
    prepare_download(f)
    f.drive.corrupt_suffix = suffix
    with pytest.raises(core.TransferError, match="independent download mismatch"):
        core.transfer_chunk(**f.args)
    receipt = retained_receipt(f)
    assert receipt["upload_performed"] is None
    assert receipt["independent_download"] is False
    assert not any(call[0] == "upload" for call in f.drive.calls)


def test_upload_only_network_failure_never_becomes_committed_receipt(transfer_fixture):
    f = transfer_fixture
    f.drive.fail_upload = True
    with pytest.raises(core.TransferError, match="network failure"):
        core.transfer_chunk(**{**f.args, "phase": "upload_only"})
    receipt = retained_receipt(f)
    assert receipt["schema_version"] == schema_version("production_cold_archive_upload_receipt")
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["upload_performed"] is None
    assert receipt["independent_download"] is False


def test_upload_only_rejects_reused_remote_namespace_in_new_attempt(transfer_fixture):
    f = transfer_fixture
    core.transfer_chunk(**{**f.args, "phase": "upload_only"})
    f.args.update(phase="upload_only", output_root=f.args["output_root"].parent / "second-attempt")
    f.drive.calls.clear()
    with pytest.raises(core.TransferError, match="absence"):
        core.transfer_chunk(**f.args)
    assert not any(call[0] == "upload" for call in f.drive.calls)


@pytest.mark.parametrize("phase", ["upload_only", "download_and_verify"])
def test_request_accepts_split_transfer_phase(request_fixture, phase):
    request, root, now = request_fixture
    request["operation"] = phase
    if phase == "download_and_verify":
        request.update(upload_receipt_path=str(root / "upload-receipt.json"),
                       upload_receipt_sha256="a" * 64)
    assert cli.validate_request(request, production_root=root, now=now,
                                source_git_sha="f" * 40) == request


@pytest.mark.parametrize("kind", ["missing_path", "missing_sha", "relative_path", "bad_sha", "extra"])
def test_download_request_requires_exact_receipt_binding(request_fixture, kind):
    request, root, now = request_fixture
    request.update(operation="download_and_verify", upload_receipt_path=str(root / "upload.json"),
                   upload_receipt_sha256="a" * 64)
    if kind == "missing_path":
        request.pop("upload_receipt_path")
    elif kind == "missing_sha":
        request.pop("upload_receipt_sha256")
    elif kind == "relative_path":
        request["upload_receipt_path"] = "upload.json"
    elif kind == "bad_sha":
        request["upload_receipt_sha256"] = "A" * 64
    else:
        request["unexpected"] = True
    with pytest.raises(ValueError):
        cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)


@pytest.mark.parametrize("value,phase,accepted", [
    (True, "upload_only", True), (False, "upload_only", False),
    (1, "upload_only", False), ("true", "upload_only", False),
    (True, "upload_and_independent_download", False)])
def test_catalog_publication_requires_explicit_upload_request(request_fixture, value, phase, accepted):
    request, root, now = request_fixture
    request.update(operation=phase, publish_catalog=value)
    if accepted:
        assert cli.validate_request(request, production_root=root, now=now,
                                    source_git_sha="f" * 40) == request
    else:
        with pytest.raises(ValueError, match="catalog publication"):
            cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)


def test_upload_request_rejects_download_receipt_fields(request_fixture):
    request, root, now = request_fixture
    request.update(operation="upload_only", upload_receipt_path=str(root / "upload.json"),
                   upload_receipt_sha256="a" * 64)
    with pytest.raises(ValueError):
        cli.validate_request(request, production_root=root, now=now, source_git_sha="f" * 40)



def test_upload_only_refuses_late_remote_identity_change_before_commit(transfer_fixture, monkeypatch):
    f = transfer_fixture
    original_object = f.drive.object
    stats = {}

    def changed_after_later_uploads(key, *, absent=False):
        result = original_object(key, absent=absent)
        if not absent:
            stats[key] = stats.get(key, 0) + 1
            if key.endswith(".rclone.bin") and stats[key] == 2:
                result["object_id"] = "changed_before_commit_123"
        return result

    monkeypatch.setattr(f.drive, "object", changed_after_later_uploads)
    with pytest.raises(core.TransferError, match="before upload commit"):
        core.transfer_chunk(**{**f.args, "phase": "upload_only"})
    receipt = retained_receipt(f)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["upload_performed"] is None
    assert receipt["independent_download"] is False
    assert sum(call[0] == "upload" for call in f.drive.calls) == 4


def test_download_receipt_failure_does_not_modify_committed_remote_objects(transfer_fixture, monkeypatch):
    f = transfer_fixture
    prepare_download(f)
    before = dict(f.drive.objects)
    original_copy = f.drive.copy

    def interrupted_download(source, destination, maximum):
        assert str(source).startswith("archive_drive:")
        original_copy(source, destination, maximum)
        raise core.TransferError("synthetic download network interruption")

    monkeypatch.setattr(f.drive, "copy", interrupted_download)
    with pytest.raises(core.TransferError, match="download network interruption"):
        core.transfer_chunk(**f.args)
    assert f.drive.objects == before
    receipt = retained_receipt(f)
    assert receipt["status"] == "FAIL_CLOSED"
    assert receipt["upload_performed"] is None
    assert receipt["independent_download"] is False
    assert not FixturePin.active
