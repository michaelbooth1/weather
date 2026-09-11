"""Retry only bounded, transient archive status-sharing failures."""
from types import SimpleNamespace
import pytest
from weather.operations import replay_cache_compression_admission as admission

@pytest.mark.parametrize("name,failures,archive,expected_calls,expected_sleeps,raises", [
    ("loop_status.json", 2, True, 3, [0.05, 0.1], False),
    ("loop_status.json", 9, True, 3, [0.05, 0.1], True),
    ("loop_status.json", 1, False, 1, [], True),
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
        assert admission.observe_capture_admission(root, object(), memory_reader=object()) == {
            "status": "BLOCK", "reasons": ["capture_unhealthy:snapshot"]}
    assert len(calls) == expected_calls and sleeps == expected_sleeps
