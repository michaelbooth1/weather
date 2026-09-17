"""Bounded status-sharing retries apply to archive and compression callers."""
from types import SimpleNamespace
import pytest
from weather.operations import replay_cache_compression_admission as admission

@pytest.mark.parametrize("name,failures,archive,expected_calls,expected_sleeps,raises", [
    ("loop_status.json", 2, True, 3, [0.05, 0.1], False),
    ("loop_status.json", 9, True, 3, [0.05, 0.1], True),
    ("loop_status.json", 1, False, 2, [0.05], False),
    ("loop_status.json", 2, False, 3, [0.05, 0.1], False),
    ("loop_status.json", 9, False, 3, [0.05, 0.1], True),
    (".loop_status.json.writer.lock", 2, False, 3, [0.05, 0.1], False),
    ("unrelated.json", 1, False, 1, [], True),
    ("unrelated.json", 1, True, 1, [], True),
    (".loop_status.json.writer.lock", 1, True, 2, [0.05], False),
])
def test_bounded_status_retry_preserves_refusals(monkeypatch, tmp_path, name, failures, archive,
                                                expected_calls, expected_sleeps, raises):
    root = tmp_path / "production"
    path = root / "data" / "snapshots" / name
    monkeypatch.setattr(admission, "default_loop_specs",
                        lambda folder: [SimpleNamespace(status_path=folder / "loop_status.json")])
    calls, sleeps = [], []
    def observe(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) <= failures:
            raise PermissionError(13, "sharing violation", str(path))
        return {"status": "BLOCK", "reasons": ["capture_unhealthy:snapshot"]}
    monkeypatch.setattr(admission, "_observe_capture_admission_once", observe)
    monkeypatch.setattr(admission.time, "sleep", sleeps.append)
    if raises:
        with pytest.raises(PermissionError):
            admission.observe_capture_admission(root, object(), memory_reader=object() if archive else None)
    else:
        assert admission.observe_capture_admission(root, object(), memory_reader=object() if archive else None) == {
            "status": "BLOCK", "reasons": ["capture_unhealthy:snapshot"]}
    assert len(calls) == expected_calls and sleeps == expected_sleeps

    assert all((row["memory_reader"] is not None) is archive for row in calls)


@pytest.mark.parametrize("failure", [
    PermissionError(13, "unidentified permission failure"),
    FileNotFoundError(2, "status missing"),
    ValueError("invalid capture status"),
])
def test_other_read_failures_are_never_retried(monkeypatch, tmp_path, failure):
    calls, sleeps = [], []
    def observe(*args, **kwargs):
        calls.append(kwargs)
        raise failure
    monkeypatch.setattr(admission, "_observe_capture_admission_once", observe)
    monkeypatch.setattr(admission.time, "sleep", sleeps.append)
    with pytest.raises(type(failure)):
        admission.observe_capture_admission(tmp_path, object())
    assert len(calls) == 1 and sleeps == []


def test_default_compression_retries_real_status_read_then_rechecks_health(monkeypatch, tmp_path):
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    folder = tmp_path / "data" / "snapshots"
    folder.mkdir(parents=True)
    specs = [SimpleNamespace(status_path=folder / (name + ".json"), name=name)
             for name in ("snapshot", "clob", "observation_trigger")]
    now = datetime.now(timezone.utc).isoformat()
    for index, spec in enumerate(specs, 1):
        spec.status_path.write_text(json.dumps({
            "pid": index, "consecutive_errors": 0, "paused": False,
            "last_heartbeat": now, "last_clean_iteration_at": now,
        }))
        spec.status_path.with_name("." + spec.status_path.name + ".writer.lock").write_text(
            json.dumps({"pid": index, "managed_process": {"pid": index, "creation_time_token": str(index)}}))
    original_open = Path.open
    reads, sleeps, checked = [], [], []
    def open_status(path, *args, **kwargs):
        reads.append(path.name)
        if path == specs[1].status_path and reads.count(path.name) == 1:
            raise PermissionError(13, "sharing violation", str(path))
        return original_open(path, *args, **kwargs)
    def pause_capture(delay):
        sleeps.append(delay)
        with original_open(specs[0].status_path, "r") as stream:
            status = json.load(stream)
        status["paused"] = True
        with original_open(specs[0].status_path, "w") as stream:
            json.dump(status, stream)
    def checker(**kwargs):
        checked.append(kwargs)
        return {"status": "BLOCK", "reasons": ["capture_unhealthy:snapshot"]}
    monkeypatch.setattr(Path, "open", open_status)
    monkeypatch.setattr(admission, "default_loop_specs", lambda root: specs)
    monkeypatch.setattr(admission, "observe_process_identity",
                        lambda pid: {"state": "running", "creation_time_token": str(pid)})
    monkeypatch.setattr(admission, "inspect_capture_loop", lambda spec, **kwargs: {
        "name": spec.name, "status_pid": specs.index(spec) + 1, "degraded": False})
    monkeypatch.setattr(admission.time, "sleep", pause_capture)
    monkeypatch.setattr(admission, "available_memory_bytes", lambda: 5 * admission.GIB)
    monkeypatch.setattr(admission, "host_commit_percent", lambda: 60)
    monkeypatch.setattr(admission, "process_memory_bytes", lambda: {"private_bytes": 1024})
    monkeypatch.setattr(admission, "current_process_priority", lambda: 0x4000)
    result = admission.observe_capture_admission(tmp_path, checker)
    assert result["status"] == "BLOCK" and sleeps == [0.05]
    assert reads.count("snapshot.json") == 2
    assert len(checked) == 1 and checked[0]["loops"][0]["degraded"] is True
    assert checked[0]["available"] == 5 * admission.GIB and checked[0]["commit"] == 60
