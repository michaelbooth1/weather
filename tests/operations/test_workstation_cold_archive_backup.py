"""Recovery metadata backup has independent bytes and create-only remote objects."""
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import pytest
from weather.operations import workstation_cold_archive_backup as backup
from test_production_cold_archive_transfer import FixturePin, transfer_fixture


def setup(f, tmp_path, monkeypatch):
    repo = tmp_path / "repository"
    control = repo / "scratch/ac-control/fixture"; control.mkdir(parents=True)
    bundle = control / "archive-recovery.json"
    bundle.write_text(json.dumps({"contains_archive_payload": False, "contains_credential_values": False,
                                 "records": [{"path": "synthetic.json", "sha256": "a" * 64, "base64": "e30="}]}))
    assignment = repo / "assignment.json"; assignment.write_text("{}")
    def proof(repo, stack):
        pin = stack.enter_context(FixturePin(assignment))
        return assignment, pin, pin.metadata(), hashlib.sha256(assignment.read_bytes()).hexdigest(), "f" * 64
    monkeypatch.setattr(backup, "repo_path", lambda: repo)
    monkeypatch.setattr(backup.workstation, "_assignment", proof)
    monkeypatch.setattr(backup.core.crypt, "_capture_tool_identity",
                        lambda repo: {"git_commit": "a" * 40, "git_dirty": False})
    monkeypatch.setenv(backup.core.crypt.WRAPPER_ENV, "1")
    monkeypatch.setattr(backup.core.crypt, "_load_dpapi_secret", f.args["secret_loader"])
    def prepare(*, arguments, attempt, **kwargs):
        parent = attempt / "credentials"; parent.mkdir()
        destination = parent / "drive.conf"
        shutil.copyfile(arguments["rclone_config"], destination)
        return destination
    monkeypatch.setattr(backup.workstation, "prepare_credentials", prepare)
    f.drive.committed_objects = {}
    monkeypatch.setattr(backup.workstation, "ExactNameDrive", f.drive.factory)
    return dict(
        attempt_id="backup-a1", expected_source_tip="a" * 40,
        bundle_path=str(bundle), bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        **{key: f.args[key] for key in ("rclone_executable", "rclone_config", "dpapi_secret",
                                      "drive_remote_name", "drive_root_folder_id")})


def test_backup_verifies_independent_download_and_preserves_input(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    args = setup(f, tmp_path, monkeypatch)
    before = Path(args["bundle_path"]).read_bytes()
    result = backup.run(**args)
    assert result["independent_download_verified"] and result["archive_payload_bytes_read"] == 0
    assert result["bundle_sha256"] == args["bundle_sha256"]
    assert Path(args["bundle_path"]).read_bytes() == before
    assert f.secret.wiped
    assert sum(call[0] == "upload" for call in f.drive.calls) == 1
    with pytest.raises(FileExistsError):
        backup.run(**args)
    assert sum(call[0] == "upload" for call in f.drive.calls) == 1


def test_changed_download_does_not_qualify_backup(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    args = setup(f, tmp_path, monkeypatch)
    f.drive.corrupt_suffix = ".recovery.json"
    with pytest.raises(backup.core.TransferError):
        backup.run(**args)
    assert Path(args["bundle_path"]).is_file()
    assert f.secret.wiped


def plain_args(f, tmp_path, monkeypatch):
    args = setup(f, tmp_path, monkeypatch)
    source = tmp_path / "repository/scratch/ac-in/batch/tape.jsonl"
    source.parent.mkdir(parents=True)
    source.write_bytes(b'{"original":true}\n' * 100)
    args.update(bundle_path=str(source), bundle_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                plain_file=True)
    return args

def test_plain_file_uploaded_without_encryption_and_download_verified(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    args = plain_args(f, tmp_path, monkeypatch)
    original = Path(args["bundle_path"]).read_bytes()
    result = backup.run(**args)
    assert result["payload_encryption"] == "none" and result["independent_download_verified"]
    assert f.drive.objects["backup-a1-tape.jsonl"] == original
    assert Path(result["downloaded_path"]).read_bytes() == original
    assert Path(args["bundle_path"]).read_bytes() == original
    assert f.secret.wiped

def test_plain_file_bad_download_retains_original_and_refuses_pass(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    args = plain_args(f, tmp_path, monkeypatch)
    f.drive.corrupt_suffix = ".jsonl"
    with pytest.raises(backup.core.TransferError, match="independent"):
        backup.run(**args)
    assert Path(args["bundle_path"]).exists()

def test_plain_file_wrong_input_hash_never_uploads(transfer_fixture, tmp_path, monkeypatch):
    f = transfer_fixture
    args = plain_args(f, tmp_path, monkeypatch)
    args["bundle_sha256"] = "f" * 64
    with pytest.raises(backup.core.TransferError, match="input hash"):
        backup.run(**args)
    assert not any(call[0] == "upload" for call in f.drive.calls)
