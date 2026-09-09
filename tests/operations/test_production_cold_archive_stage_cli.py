"""Request, resource and production-boundary checks for archive staging."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import pytest

from weather.operations import production_cold_archive_stage_cli as subject
from weather.paths import repo_path
from weather.schema_registry import schema_version

NOW = datetime(2026, 9, 9, 5, tzinfo=timezone.utc)
TIP = "b" * 40
FILE = "snapshots/highest-temperature-in-toronto-on-july-16-2026/replay_inputs.jsonl"


def request(root):
    return {
        "schema_version": schema_version("production_cold_archive_request"),
        "production_repo_root": str(root), "execution_host_id": "a" * 64,
        "operation": "stage_only", "approved_by": "fixture owner",
        "approved_at_utc": (NOW - timedelta(hours=1)).isoformat(),
        "expires_at_utc": (NOW + timedelta(hours=1)).isoformat(),
        "plan_path": str(root / "plan.json"), "plan_sha256": "c" * 64,
        "chunk_id": "chunk-00000", "source_git_sha": TIP,
    }


def resources():
    return dict(now=NOW, available=8 * 1024**3, commit=50,
                free_disk=subject.SOURCE_RESERVE_BYTES + subject.EVIDENCE_RESERVE_BYTES,
                output_reservation=0,
                loops=[{"name": name, "active": True, "degraded": False,
                        "heartbeat_fresh": True, "pid_agreement": True,
                        "heartbeat_age_seconds": 1, "last_clean_iteration_age_seconds": 60,
                        "process_identity_matches_lock": True,
                        "process_diagnostics": {"status_pid_alive": True, "lock_pid_alive": True}}
                       for name in ("snapshot", "clob", "observation_trigger")])


def test_exact_owner_request():
    root = repo_path()
    assert subject.validate_request(request(root), production_root=root, now=NOW,
                                    source_git_sha=TIP) == request(root)


@pytest.mark.parametrize("key,value", [
    ("operation", "delete"), ("operation", "upload"), ("schema_version", "unknown"),
    ("approved_by", ""), ("execution_host_id", "invalid"), ("plan_sha256", ""),
    ("source_git_sha", "d" * 40), ("chunk_id", "chunk-1"), ("plan_path", "relative.json"),
    ("approved_at_utc", (NOW + timedelta(seconds=1)).isoformat()),
    ("expires_at_utc", NOW.isoformat()),
    ("expires_at_utc", (NOW + timedelta(hours=73)).isoformat()),
])
def test_request_refuses_scope_and_binding_changes(tmp_path, key, value):
    payload = request(tmp_path)
    payload[key] = value
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW, source_git_sha=TIP)


def test_unknown_request_fields_and_root_refused(tmp_path):
    payload = request(tmp_path)
    payload["owner_approved_exception"] = "daytime"
    with pytest.raises(ValueError):
        subject.validate_request(payload, production_root=tmp_path, now=NOW, source_git_sha=TIP)
    with pytest.raises(ValueError):
        subject.validate_request(request(tmp_path), production_root=tmp_path / "other",
                                 now=NOW, source_git_sha=TIP)


def test_resources_do_not_double_reserve_written_output():
    args = resources()
    assert subject.check_resources(**args)["status"] == "PASS"
    args["free_disk"] -= 1
    assert subject.check_resources(**args)["status"] == "BLOCK"


@pytest.mark.parametrize("key,value", [
    ("now", NOW.replace(hour=17)), ("now", NOW.replace(hour=9)),
    ("commit", 70), ("commit", float("nan")), ("available", 4 * 1024**3 - 1),
    ("free_disk", None), ("free_disk", True), ("free_disk", 21 * 1024**3), ("loops", []),
])
def test_capture_time_and_resources_refuse(key, value):
    args = resources()
    args[key] = value
    assert subject.check_resources(**args)["status"] == "BLOCK"


def plan(root):
    return {"source_root": str(root / "data"), "chunks": [{
        "chunk_id": "chunk-00000", "logical_bytes": 4,
        "files": [{"path": FILE, "size_bytes": 4}],
    }]}


def test_exact_immediate_old_whole_file_chunk(tmp_path):
    payload = plan(tmp_path)
    assert subject.validate_chunk(payload, "chunk-00000", tmp_path, NOW) == payload["chunks"][0]


@pytest.mark.parametrize("path", [
    "../replay_inputs.jsonl", "snapshots/x", FILE + "/child", FILE.replace("july", "september"),
    FILE.replace("toronto", "unknown"), FILE.replace("replay_inputs.jsonl", "../file"),
])
def test_hot_nested_unknown_or_traversing_source_refused(tmp_path, path):
    payload = plan(tmp_path)
    payload["chunks"][0]["files"][0]["path"] = path
    with pytest.raises(ValueError):
        subject.validate_chunk(payload, "chunk-00000", tmp_path, NOW)


def test_chunk_accounting_and_ambiguous_identity_refused(tmp_path):
    payload = plan(tmp_path)
    payload["chunks"][0]["logical_bytes"] = 3
    with pytest.raises(ValueError):
        subject.validate_chunk(payload, "chunk-00000", tmp_path, NOW)
    payload = plan(tmp_path)
    payload["chunks"].append(copy.deepcopy(payload["chunks"][0]))
    with pytest.raises(ValueError):
        subject.validate_chunk(payload, "chunk-00000", tmp_path, NOW)


def test_exact_worktree_imports():
    assert Path(subject.__file__).resolve().is_relative_to(repo_path("src/weather"))
    assert Path(subject.stage.__file__).resolve().is_relative_to(repo_path("src/weather"))
