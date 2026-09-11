"""Small fixtures for sealed-file selection and source-retaining PC copy."""
import base64
from contextlib import ExitStack, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from weather.operations import production_cold_archive_copy as copy
from weather.operations import production_cold_archive_stage as archive
from weather.schema_registry import schema_version

pytestmark = pytest.mark.skipif(os.name != "nt", reason="native Windows path and source pins")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    root = tmp_path / "production"
    stage = root / "scratch/production_cold_archive/fixture01s1/stage"
    stage.mkdir(parents=True)
    payload = stage / "archive.tar.gz"
    payload.write_bytes(b"small sealed archive fixture")
    row = {"path": "snapshots/example-2026-06-15/market_ws.jsonl",
           "size_bytes": 27, "mtime_ns": 42, "device": 7, "file_id": 18, "allocated_bytes": 4096}
    plan = {"plan_hash": "a" * 64, "source_root": str(root / "data")}
    chunk = {"chunk_id": "chunk-00000", "files": [row]}
    manifest = archive._seal({
        **plan, "plan_sha256": "b" * 64, "chunk_id": chunk["chunk_id"],
        "files": [{**row, "sha256": "c" * 64}],
        "archive_bytes": payload.stat().st_size, "archive_sha256": sha(payload)}, "manifest_hash")
    receipt = archive._seal({
        "status": "PASS", "source_retained": True, "manifest_hash": manifest["manifest_hash"],
        "plan_sha256": "b" * 64, "chunk_id": chunk["chunk_id"],
        "verification": {"archive_sha256": sha(payload)}}, "receipt_hash")
    for name, value in (("manifest.json", manifest), ("receipt.json", receipt)):
        (stage / name).write_text(json.dumps(value), encoding="utf-8")
    transport = tmp_path / "transport"
    transport.mkdir()
    for name in ("ssh.exe", "scp.exe", "key", "known_hosts"):
        (transport / name).write_text("fixture only")
    ws = (tmp_path / "workstation").as_posix()
    (Path(ws) / "scratch/ac-in").mkdir(parents=True)
    request = {
        "schema_version": schema_version("production_cold_archive_copy_request"),
        "production_repo_root": str(root), "execution_host_id": "e" * 64,
        "operation": "copy", "approved_by": "fixture owner",
        "approved_at_utc": "2026-09-10T17:30:00Z", "expires_at_utc": "2026-09-10T22:00:00Z",
        "plan_path": str(root / "plan.json"), "plan_sha256": "b" * 64,
        "chunk_id": chunk["chunk_id"], "source_git_sha": "f" * 40,
        "archive_id": "fixture01", "direction": "to_workstation",
        "production_manifest_path": str(stage / "manifest.json"),
        "production_manifest_sha256": sha(stage / "manifest.json"),
        "production_receipt_path": str(stage / "receipt.json"),
        "production_receipt_sha256": sha(stage / "receipt.json"),
        "workstation_root": ws, "remote_host": "192.168.1.106", "remote_user": "Fixture",
        "private_key": str(transport / "key"), "known_hosts": str(transport / "known_hosts"),
        "known_hosts_sha256": sha(transport / "known_hosts"),
        "ssh_executable": str(Path(os.environ["WINDIR"]) / "System32/OpenSSH/ssh.exe"),
        "scp_executable": str(Path(os.environ["WINDIR"]) / "System32/OpenSSH/scp.exe"),
        "files": [{"local": str(stage / name), "remote": ws + "/scratch/ac-in/fixture01/" + name,
                   "bytes": (stage / name).stat().st_size, "sha256": sha(stage / name)}
                  for name in ("archive.tar.gz", "manifest.json", "receipt.json")],
    }
    return request, root, plan, chunk


def validate(request, root):
    return copy.validate_request(request, root, datetime(2026, 9, 10, 18, tzinfo=timezone.utc), "f" * 40)


def test_sealed_manifest_derives_exact_three_files(fixture):
    request, root, plan, chunk = fixture
    validate(request, root)
    with ExitStack() as stack:
        assert copy.bound_rows(request, root, plan, chunk, stack) == request["files"]


@pytest.mark.parametrize("change", [
    {"direction": "from_workstation"}, {"remote_host": "8.8.8.8"},
    {"remote_host": "127.0.0.1"}, {"remote_user": "name;exit"},
    {"archive_id": "../outside"}, {"workstation_root": "C:/temp/../data"},
    {"expires_at_utc": "2026-09-10T17:00:00Z"}, {"source_git_sha": "a" * 40},
    {"extra": True},
])
def test_copy_request_refuses_scope_and_authority_changes(fixture, change):
    request, root, _, _ = fixture
    request.update(change)
    with pytest.raises((ValueError, TypeError)):
        validate(request, root)


@pytest.mark.parametrize("field,value", [("bytes", True), ("sha256", "bad"),
    ("local", "relative/file"), ("remote", "C:/scratch/$(bad)"), ("bytes", 2 * 1024**3)])
def test_copy_rows_refuse_unbounded_or_ambiguous_operands(fixture, field, value):
    request, root, _, _ = fixture
    request["files"][0][field] = value
    with pytest.raises(ValueError):
        validate(request, root)


@pytest.mark.parametrize("field", ["local", "remote", "bytes", "sha256"])
def test_labels_cannot_select_another_file(fixture, field):
    request, root, plan, chunk = fixture
    row = request["files"][0]
    row[field] = row[field] + 1 if field == "bytes" else row[field] + "x"
    with ExitStack() as stack, pytest.raises(ValueError, match="selected copy files differ"):
        copy.bound_rows(request, root, plan, chunk, stack)


def test_changed_stage_proof_refuses_before_copy(fixture):
    request, root, plan, chunk = fixture
    Path(request["production_receipt_path"]).write_text("{}")
    with ExitStack() as stack, pytest.raises(ValueError, match="digest"):
        copy.bound_rows(request, root, plan, chunk, stack)


def test_changed_payload_refuses_before_destination_creation(fixture, tmp_path):
    request, _, _, _ = fixture
    Path(request["files"][0]["local"]).write_bytes(b"changed")
    calls = []
    with ExitStack() as stack, pytest.raises(ValueError, match="content changed"):
        copy.execute_copy(request, request["files"], tmp_path, lambda: True, stack,
                          child_runner=lambda *args, **kwargs: calls.append(args))
    assert calls == []


def test_partial_copy_records_only_completed_file_and_retains_every_source(fixture, tmp_path):
    request, _, _, _ = fixture
    calls = []
    def child(arguments, log, guard, **kwargs):
        guard()
        calls.append(arguments)
        if len(calls) == 3:
            raise ValueError("fixture transfer refused")
    with ExitStack() as stack, pytest.raises(ValueError, match="fixture transfer refused"):
        copy.execute_copy(request, request["files"], tmp_path, lambda: True, stack, child_runner=child)
    assert (tmp_path / "file-000.json").is_file()
    assert not (tmp_path / "file-001.json").exists()
    assert all(Path(row["local"]).is_file() for row in request["files"])
    assert calls[1][calls[1].index("-l") + 1] == "131072"


def test_admission_failure_prevents_transport(fixture, tmp_path):
    request, _, _, _ = fixture
    calls = []
    def denied():
        raise ValueError("fixture resource refusal")
    with ExitStack() as stack, pytest.raises(ValueError, match="resource refusal"):
        copy.execute_copy(request, request["files"], tmp_path, denied, stack,
                          child_runner=lambda *args, **kwargs: calls.append(args))
    assert calls == []


def test_destination_creation_is_native_create_only(fixture):
    request, _, _, _ = fixture
    args = copy.destination_command(request)
    script = base64.b64decode(args[-1]).decode("utf-16le")
    assert "ReparsePoint" in script and "while($p)" in script
    local = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", args[-1]]
    first = subprocess.run(local, capture_output=True, timeout=15)
    assert first.returncode == 0, first.stderr
    destination = Path(request["workstation_root"]) / "scratch/ac-in/fixture01"
    protected = destination / "archive.tar.gz"
    protected.write_bytes(b"retained failed attempt")
    second = subprocess.run(local, capture_output=True, timeout=15)
    assert second.returncode != 0
    assert protected.read_bytes() == b"retained failed attempt"


def test_transport_arguments_forbid_ambient_configuration(fixture):
    args = copy.transport_arguments(fixture[0], "scp_executable")
    for token in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ProxyCommand=none",
                  "ProxyJump=none", "ClearAllForwardings=yes", "IdentitiesOnly=yes"):
        assert token in args
    assert args[args.index("-F") + 1] == "none"


def test_system_binary_pins_accept_windows_servicing_hardlinks(fixture):
    request = fixture[0]
    for field in ("ssh_executable", "scp_executable"):
        with copy._BinaryPin(Path(request[field])) as pin:
            assert pin.metadata()["size_bytes"] > 0


def test_non_system_transport_binary_is_rejected(fixture):
    request, root, _, _ = fixture
    request["ssh_executable"] = str(Path(request["private_key"]).parent / "ssh.exe")
    with pytest.raises(ValueError, match="native system"):
        validate(request, root)
