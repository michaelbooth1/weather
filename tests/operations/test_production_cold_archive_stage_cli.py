"""Request, resource and production-boundary checks for archive staging."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import copy
import hashlib
import json
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


@pytest.mark.skipif(__import__("os").name != "nt", reason="native Windows path equivalence")
def test_windows_source_root_accepts_forward_slashes_from_approved_plan(tmp_path):
    payload = plan(tmp_path)
    payload["source_root"] = (tmp_path / "data").as_posix()
    assert subject.validate_chunk(payload, "chunk-00000", tmp_path, NOW) == payload["chunks"][0]


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


def test_approved_reserve_requires_actual_pinned_plan_bytes(tmp_path, monkeypatch):
    path = tmp_path / "plan.json"
    payload = {"selection_sha256": subject.APPROVED_ARCHIVE_SELECTION_SHA256}
    path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "APPROVED_ARCHIVE_PLAN_SHA256", digest)
    loaded, reserve = subject.load_plan_with_reserve(path, digest)
    assert loaded == payload
    assert reserve == 20 * 1024**3

    # Supplying the approved digest for different bytes cannot grant admission.
    path.write_text(json.dumps({**payload, "changed": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        subject.load_plan_with_reserve(path, digest)

    # Even an internally valid newly hashed plan retains the general floor.
    changed_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert subject.load_plan_with_reserve(path, changed_digest)[1] == 50 * 1024**3


@pytest.mark.parametrize("selection", [None, "", "a" * 64])
def test_approved_plan_without_exact_selection_keeps_general_reserve(tmp_path, monkeypatch, selection):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"selection_sha256": selection}), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "APPROVED_ARCHIVE_PLAN_SHA256", digest)
    assert subject.load_plan_with_reserve(path, digest)[1] == 50 * 1024**3


@pytest.mark.parametrize("binding", ["OVERNIGHT_PLAN_SHA256", "OVERNIGHT_DAY_PLAN_SHA256"])
@pytest.mark.parametrize("checked,expected", [
    ("2026-09-10T03:59:59+00:00", 50),
    ("2026-09-10T04:00:00+00:00", 6),
    ("2026-09-10T12:59:59+00:00", 6),
    ("2026-09-10T13:00:00+00:00", 50),
])
def test_overnight_reserve_expires_and_binds_actual_plan(tmp_path, monkeypatch, checked, expected, binding):
    path = tmp_path / "overnight.json"
    payload = {"selection_sha256": subject.OVERNIGHT_SELECTION_SHA256}
    path.write_text(json.dumps(payload), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, binding, digest)
    now = subject.datetime.fromisoformat(checked)
    assert subject.load_plan_with_reserve(path, digest, now=now)[1] == expected * 1024**3
    path.write_text(json.dumps({**payload, "changed": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        subject.load_plan_with_reserve(path, digest, now=now)
    changed = hashlib.sha256(path.read_bytes()).hexdigest()
    assert subject.load_plan_with_reserve(path, changed, now=now)[1] == 50 * 1024**3


def test_overnight_reserve_requires_exact_selection(tmp_path, monkeypatch):
    path = tmp_path / "wrong-selection.json"
    path.write_text(json.dumps({"selection_sha256": "f" * 64}), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(subject, "OVERNIGHT_PLAN_SHA256", digest)
    now = subject.datetime(2026, 9, 10, 5, tzinfo=subject.timezone.utc)
    assert subject.load_plan_with_reserve(path, digest, now=now)[1] == 50 * 1024**3


def test_overnight_staging_reserves_both_later_ciphertext_copies():
    logical = 100 * 1024**2
    cipher_bound = logical + logical // 100 + 4 * 1024**2
    assert subject.staging_reserve({"logical_bytes": logical}, subject.OVERNIGHT_RESERVE_BYTES) == (
        6 * 1024**3 + subject.EVIDENCE_RESERVE_BYTES + 2 * cipher_bound)
    assert subject.staging_reserve({"logical_bytes": logical}, 20 * 1024**3) == (
        20 * 1024**3 + subject.EVIDENCE_RESERVE_BYTES)


def test_approved_reserve_keeps_evidence_memory_and_time_guards():
    args = resources()
    args["source_reserve_bytes"] = 20 * 1024**3
    args["free_disk"] = 20 * 1024**3 + subject.EVIDENCE_RESERVE_BYTES
    result = subject.check_resources(**args)
    assert result["status"] == "PASS"
    assert result["source_disk_reserve_bytes"] == 20 * 1024**3
    args["free_disk"] -= 1
    assert subject.check_resources(**args)["status"] == "BLOCK"
    args["free_disk"] += 1
    args["now"] = NOW.replace(hour=17)
    assert subject.check_resources(**args)["status"] == "BLOCK"
    args["now"] = NOW
    args["commit"] = 70
    assert subject.check_resources(**args)["status"] == "BLOCK"
    args["commit"] = 50
    args["available"] = 4 * 1024**3 - 1
    assert subject.check_resources(**args)["status"] == "BLOCK"
