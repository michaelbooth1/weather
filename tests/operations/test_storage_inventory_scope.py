"""Immediate-file inventories stay complete within their explicitly smaller scope."""
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from argparse import Namespace

import pytest

from weather.operations import storage_recovery_inventory as metadata
from weather.operations import storage_recovery_inventory_cli as cli
from weather.operations import storage_recovery_batch_plan as planner
from weather.operations import cold_snapshot_compression as compression
from weather.paths import repo_path
from weather.schema_registry import schema_version


FOLDER = "snapshots/highest-temperature-in-atlanta-on-july-1-2026"
NOW = datetime(2026, 9, 8, 5, tzinfo=timezone.utc)
SHA = "a" * 40


def setup(tmp_path):
    root = tmp_path / "data"
    folder = root / FOLDER
    nested = folder / "raw"
    nested.mkdir(parents=True)
    (folder / "snapshots.jsonl").write_bytes(b"{}\n")
    (nested / "blob.json").write_bytes(b"{}\n")
    return root, folder, nested


def request(root, now=NOW):
    return {"schema_version": schema_version("storage_recovery_inventory_request"),
            "production_repo_root": str(root), "execution_host_id": "a" * 64,
            "operation": "metadata_only", "approved_by": "fixture owner",
            "approved_at_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_at_utc": (now + timedelta(hours=1)).isoformat(), "folders": [FOLDER],
            "traversal_scope": "immediate_files"}


def test_immediate_selection_never_scans_nested_directory_or_claims_whole_folder(tmp_path, monkeypatch):
    root, folder, nested = setup(tmp_path)
    real_scan = os.scandir
    def bounded_scan(path):
        assert Path(path) != nested, "nested source was outside the requested scope"
        return real_scan(path)
    monkeypatch.setattr(os, "scandir", bounded_scan)
    result = metadata.inventory(root, [FOLDER], as_of=NOW.date(), guard=lambda: None,
                                allocation=lambda p, s: 4096, traversal_scope="immediate_files")
    assert result["status"] == "PASS" and result["traversal_scope"] == "immediate_files"
    assert result["complete_selection_allocated_bytes"] == 4096
    assert result["complete_selection_logical_bytes"] == 3
    assert result["complete_folder_allocated_bytes"] == result["complete_folder_logical_bytes"] == 0
    assert result["folders"][0]["unvisited_subdirectories"] == 1
    assert [row["path"] for row in result["files"]] == [FOLDER + "/snapshots.jsonl"]
    assert result["payload_bytes_read"] == result["deleted_files"] == result["reclaimed_bytes"] == 0


def test_immediate_scope_retains_entry_limit_and_drift_refusals(tmp_path):
    root, folder, _ = setup(tmp_path)
    result = metadata.inventory(root, [FOLDER], as_of=NOW.date(), guard=lambda: None,
                                allocation=lambda p, s: 4096, traversal_scope="immediate_files",
                                limits=metadata.Limits(directory_entries=1))
    assert result["status"] == "PARTIAL" and result["complete_selection_allocated_bytes"] == 0
    def drift(path, info):
        path.write_bytes(b"changed")
        return 4096
    result = metadata.inventory(root, [FOLDER], as_of=NOW.date(), guard=lambda: None,
                                allocation=drift, traversal_scope="immediate_files")
    assert result["status"] == "PARTIAL" and result["complete_selection_allocated_bytes"] == 0


@pytest.mark.parametrize("scope", ["all", "", None, [], True])
def test_invalid_scope_rejected_in_request_and_inventory(tmp_path, scope):
    payload = request(tmp_path)
    payload["traversal_scope"] = scope
    with pytest.raises(ValueError):
        cli.validate_request(payload, production_root=tmp_path, now=NOW)
    with pytest.raises(ValueError):
        metadata.inventory(tmp_path, [FOLDER], as_of=NOW.date(), guard=lambda: None,
                           traversal_scope=scope)


def test_exact_request_accepts_immediate_scope(tmp_path):
    assert cli.validate_request(request(tmp_path), production_root=tmp_path, now=NOW) == [FOLDER]


@pytest.mark.parametrize("fault", ["none", "nested", "folder_scope", "unknown_scope"])
def test_compression_and_planning_honor_completed_scope(tmp_path, monkeypatch, fault):
    row = {"path": FOLDER + "/source.jsonl", "size_bytes": 2 * 1024**2,
           "allocated_bytes": 2 * 1024**2, "attributes": 32, "device": "1", "file_id": "2",
           "mtime_ns": str(int((NOW - timedelta(days=45)).timestamp()) * 10**9)}
    bound = {"status": "PASS", "source_git_sha": SHA, "request_sha256": "b" * 64,
             "execution_host_id": "a" * 64, "cleanup_eligible": False}
    manifest = {**bound, "schema_version": schema_version("storage_recovery_inventory"),
                "data_root": str(tmp_path / "data"), "traversal_scope": "immediate_files",
                "folders": [{"path": FOLDER, "status": "COMPLETE", "traversal_scope": "immediate_files"}],
                "files": [row]}
    if fault == "nested": row["path"] = FOLDER + "/raw/source.jsonl"
    if fault == "folder_scope": manifest["folders"][0]["traversal_scope"] = "recursive"
    if fault == "unknown_scope": manifest["traversal_scope"] = "unknown"
    payload = {**request(tmp_path), "schema_version": schema_version("cold_snapshot_compression_request"),
               "operation": "compress_and_retain", "files": [row],
               "inventory_wrapper_sha256": "c" * 64,
               "inventory_wrapper_receipt": str(tmp_path / "scratch/storage_recovery_inventory/one/wrapper-result.json")}
    del payload["folders"], payload["traversal_scope"]
    receipts = {"wrapper-result.json": {**bound, "hard_stop": False, "teardown_proved": True,
                                        "deleted_files": 0, "reclaimed_bytes": 0, "child_result_sha256": "c" * 64},
                "result.json": {**bound, "inventory_sha256": "c" * 64}, "inventory.json": manifest}
    monkeypatch.setattr(compression, "PinnedNtfsDirectory", lambda p: nullcontext())
    monkeypatch.setattr(compression, "_read_receipt", lambda p, *a: receipts[p.name])
    def read():
        return compression.read_inventory(payload, [row], production_root=tmp_path, source_git_sha=SHA)
    def plan():
        context = {key: value for key, value in payload.items() if key != "files"}
        return planner.prepare(manifest, context, production_root=tmp_path, now=NOW, mode="pilot")
    if fault == "none":
        assert read() == manifest
        assert plan()["selected_file_count"] == 1
    else:
        with pytest.raises(ValueError): read()
        with pytest.raises(ValueError): plan()


@pytest.mark.skipif(os.name != "nt", reason="native complete inventory CLI receipt")
def test_native_cli_binds_scope_and_selected_capacity(tmp_path, monkeypatch):
    root, _, nested = setup(tmp_path)
    now = datetime.now(timezone.utc)
    payload = request(tmp_path, now)
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps(payload))
    output = tmp_path / "scratch/storage_recovery_inventory/one"
    output.mkdir(parents=True)
    lease = root / "logs/heavy_workload.lock"
    lease.parent.mkdir()
    lease.write_text(json.dumps({"execution_host_id": "a" * 64}))
    monkeypatch.setenv(cli.ENV_PREFIX + "SOURCE_ROOT", str(repo_path()))
    monkeypatch.setenv(cli.ENV_PREFIX + "OWNER_PID", "1")
    monkeypatch.setenv(cli.ENV_PREFIX + "DEADLINE_UTC", (now + timedelta(seconds=60)).isoformat())
    monkeypatch.setattr(cli, "verify_current_lease", lambda *a, **k: None)
    monkeypatch.setattr(cli, "observe_capture_admission", lambda *a: {"status": "PASS"})
    monkeypatch.setattr(cli, "set_current_process_below_normal", lambda: None)
    args = Namespace(production_repo_root=str(tmp_path), request=str(approved),
                     request_sha256=hashlib.sha256(approved.read_bytes()).hexdigest(),
                     source_git_sha=SHA, output_root=str(output))
    assert cli.run(args) == 0
    receipt = json.loads((output / "result.json").read_text())
    manifest = json.loads((output / "inventory.json").read_text())
    assert receipt["traversal_scope"] == manifest["traversal_scope"] == "immediate_files"
    assert receipt["complete_folder_allocated_bytes"] == 0
    assert receipt["complete_selection_allocated_bytes"] == manifest["files"][0]["allocated_bytes"]
    assert len(manifest["files"]) == 1
