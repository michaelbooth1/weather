"""Workstation transport tests use synthetic Drive objects and no credentials."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import time

import pytest
from weather import execution_host
from weather.operations import workstation_cold_archive_transfer as transport
from weather.operations import workstation_cold_archive_stage as stage
from weather.operations import production_cold_archive_transfer_core as core
from test_production_cold_archive_transfer import FixturePin, transfer_fixture


def test_import_is_the_reviewed_checkout():
    print("workstation transfer module:", transport.__file__)
    assert Path(transport.__file__).resolve() == transport.REPO_ROOT / "src/weather/operations/workstation_cold_archive_transfer.py"


def client(tmp_path):
    return transport.ExactNameDrive(tmp_path / "rclone", tmp_path / "config",
        "archive_drive", "fixture_root_12345", {}, lambda: True, time.monotonic() + 200)


@pytest.mark.parametrize("value", [
    {"files": [], "incompleteSearch": True},
    {"files": [], "incompleteSearch": False, "nextPageToken": "more"},
    {"files": []},
    {"files": [{"id": "fixture_object_1234", "name": "wrong.bin"}], "incompleteSearch": False},
    {"files": [{"id": "fixture_object_1234", "name": "payload.bin"}] * 2, "incompleteSearch": False},
])
def test_ambiguous_or_incomplete_listing_cannot_prove_absence(tmp_path, monkeypatch, value):
    c = client(tmp_path)
    monkeypatch.setattr(transport.drive_id, "token", lambda c: "fixture-access")
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return self.url
        def read(self, count): return json.dumps(value).encode()
    def open_request(request, timeout):
        r = Response(); r.url = request.full_url
        assert r.url.startswith("https://www.googleapis.com/drive/v3/files?")
        assert 0 < timeout <= 10
        return r
    monkeypatch.setattr(transport.urllib.request, "build_opener",
                        lambda *args: SimpleNamespace(open=open_request))
    with pytest.raises(core.TransferError):
        c.object("payload.bin", absent=True)


def test_presence_refuses_upload_and_followup_reads_bind_id(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setattr(c, "_names", lambda key: [{"id": "fixture_object_1234", "name": key}])
    with pytest.raises(core.TransferError, match="absence"):
        c.object("payload.bin", absent=True)
    seen = []
    value = {"object_id": "fixture_object_1234", "remote_key": "payload.bin", "bytes": 8, "hashes": {}}
    monkeypatch.setattr(transport.drive_id, "object_metadata",
                        lambda c, key, object_id: seen.append(object_id) or dict(value))
    assert c.object("payload.bin") == value
    monkeypatch.setattr(c, "_names", lambda key: pytest.fail("must use committed ID"))
    assert c.object("payload.bin") == value
    assert seen == ["fixture_object_1234"] * 2


@pytest.mark.parametrize("path", ["/workstation/data/file", "/workstation/weather-mirror/file"])
def test_mirror_refusal_precedes_any_file_read(monkeypatch, path):
    monkeypatch.setattr(core.archive, "_safe_path", lambda *a, **k: pytest.fail("mirror touched"))
    with pytest.raises(core.TransferError, match="outside data"):
        transport._input_path(path)


def test_production_wrapper_environment_does_not_admit_capture_host(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    path = repo / execution_host.EXECUTION_HOST_ASSIGNMENT_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "schema_version": execution_host.EXECUTION_HOST_ASSIGNMENT_SCHEMA_VERSION,
        "assignment_status": "ASSIGNED", "active_portable_execution_host_id": "same",
        "active_portable_execution_principal_id": "principal", "dedicated_capture_execution_host_id": "same"}))
    monkeypatch.setattr(transport, "os", SimpleNamespace(name="nt", environ={stage.WRAPPER_ENV: "1"}))
    monkeypatch.setattr(core.bridge, "_file_pin", FixturePin)
    monkeypatch.setattr(execution_host, "current_execution_host_id", lambda: "same")
    monkeypatch.setattr(execution_host, "current_execution_principal_id", lambda: "principal")
    with ExitStack() as stack, pytest.raises(core.TransferError, match="non-capture"):
        transport._assignment(repo, stack)


def test_no_wrapper_refuses_before_assignment_access(tmp_path, monkeypatch):
    monkeypatch.delenv(stage.WRAPPER_ENV, raising=False)
    with ExitStack() as stack, pytest.raises(core.TransferError, match="wrapper"):
        transport._assignment(tmp_path, stack)


def setup_run(f, tmp_path, monkeypatch):
    repo = tmp_path / "workstation"; repo.mkdir()
    (repo / "data").mkdir()
    (repo / "scratch/production_cold_archive_transport").mkdir(parents=True)
    assignment = repo / "assignment.json"; assignment.write_bytes(b"fixture assignment")
    def assignment_proof(repo, stack):
        pin = stack.enter_context(FixturePin(assignment))
        return assignment, pin, pin.metadata(), hashlib.sha256(assignment.read_bytes()).hexdigest(), "f" * 64
    monkeypatch.setattr(transport, "_assignment", assignment_proof)
    monkeypatch.setattr(core.crypt, "_capture_tool_identity", lambda repo: {"git_commit": "2" * 40})
    monkeypatch.setattr(transport, "ExactNameDrive", f.drive.factory)
    monkeypatch.setattr(transport, "prepare_credentials",
                        lambda **kw: kw["arguments"]["rclone_config"])
    monkeypatch.setattr(core.crypt, "_load_dpapi_secret", f.args["secret_loader"])
    monkeypatch.setattr(core.shutil, "disk_usage", lambda p: SimpleNamespace(free=30 * 1024**3))
    monkeypatch.setenv(stage.WRAPPER_ENV, "1")
    omitted = {"output_root", "protected_root", "admission", "deadline_monotonic",
               "free_space_reserve_bytes", "client_factory", "secret_loader"}
    args = {k: v for k, v in f.args.items() if k not in omitted}
    return repo, dict(args, expected_source_tip="2" * 40, repo_root=repo)


def test_admitted_upload_then_independent_download_retains_source(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    repo, args = setup_run(f, tmp_path, monkeypatch)
    before = f.paths["ciphertext_path"].read_bytes()
    upload = transport.run(**args, attempt_id="upload-a1", phase="upload_only")
    assert upload["status"] == "PASS" and not upload["independent_download"]
    assert upload["reclaimed_bytes"] == 0
    download = transport.run(**args, attempt_id="download-a1", phase="download_and_verify",
                             upload_receipt_path=upload["receipt_path"],
                             upload_receipt_sha256=upload["receipt_sha256"])
    result = json.loads(Path(download["receipt_path"]).read_text())
    assert download["independent_download"] and not download["upload_performed"]
    assert Path(result["downloaded_file"]["path"]).read_bytes() == before
    assert f.paths["ciphertext_path"].read_bytes() == before
    assert f.secret.wiped
    with pytest.raises(core.TransferError, match="spent"):
        transport.run(**args, attempt_id="upload-a1", phase="upload_only")


def test_failed_upload_retains_core_and_execution_failure_without_retry(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    repo, args = setup_run(f, tmp_path, monkeypatch)
    f.drive.fail_upload = True
    with pytest.raises(core.TransferError, match="retained"):
        transport.run(**args, attempt_id="failure-a1", phase="upload_only")
    root = repo / "scratch/production_cold_archive_transport/failure-a1"
    result = json.loads((root / "transfer/receipt.json").read_text())
    assert result["remote_side_effect_possible"] and result["source_retained"]
    assert (root / "failure.json").exists()
    assert sum(call[0] == "upload" for call in f.drive.calls) == 1


def test_stage_routes_only_explicit_transfer_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(transport, "main", lambda args: seen.append(args) or 2)
    assert stage.main(["--production-transfer", "upload_only"]) == 2
    assert seen == [["upload_only"]]


def test_credential_failure_precedes_payload_transfer(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    repo, args = setup_run(f, tmp_path, monkeypatch)
    def refuse(**kwargs):
        raise ValueError("credential lifetime unavailable")
    monkeypatch.setattr(transport, "prepare_credentials", refuse)
    with pytest.raises(core.TransferError, match="retained"):
        transport.run(**args, attempt_id="credential-a1", phase="upload_only")
    assert not f.drive.calls
    assert not (repo / "scratch/production_cold_archive_transport/credential-a1/transfer").exists()


def test_fresh_encrypted_credentials_leave_source_unchanged(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    attempt = tmp_path / "credential"; attempt.mkdir()
    args = {**f.args}
    before = Path(args["rclone_config"]).read_bytes()
    events = []
    class Client:
        def __init__(self, executable, config, remote, folder, environment, admission, deadline):
            self.config, self.remote, self.admission = config, remote, admission
        def preflight(self):
            events.append("preflight")
        def run(self, tokens):
            assert tokens == ["about", self.remote + ":", "--json"]
            assert self.admission()
            self.config.write_bytes(b"encrypted refreshed fixture")
            events.append("refresh")
            return 0, b""
    monkeypatch.setattr(transport, "_RefreshClient", Client)
    monkeypatch.setattr(core.crypt, "_load_dpapi_secret", f.args["secret_loader"])
    def token(client, *, minimum_remaining_seconds):
        assert minimum_remaining_seconds == 930
        events.append("lifetime")
        return "synthetic"
    monkeypatch.setattr(transport.drive_id, "token", token)
    active = transport.prepare_credentials(
        arguments=args, attempt=attempt, admission=lambda: True, deadline=time.monotonic() + 60)
    assert active.read_bytes() == b"encrypted refreshed fixture"
    assert Path(args["rclone_config"]).read_bytes() == before
    assert events == ["preflight", "refresh", "lifetime"]
    assert f.secret.wiped
    proof = json.loads((active.parent / "receipt.json").read_text())
    assert proof["archive_payload_bytes_read"] == 0 and proof["source_config_unchanged"]


def test_production_client_cannot_use_refresh_command(tmp_path):
    c = core.GuardedClient(tmp_path / "rclone", tmp_path / "config", "r",
                          "fixture_root_12345", {}, lambda: True, time.monotonic() + 10)
    with pytest.raises(core.TransferError, match="allowlist"):
        c.run(["about", "r:", "--json"])
