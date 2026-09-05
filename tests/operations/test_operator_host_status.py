import json
import threading
import time
from unittest import mock

from weather.operations.operator_host_status import HostStatusCache, host_status_snapshot
from weather.paths import REPO_ROOT


@mock.patch("weather.operations.operator_host_status.subprocess.run")
def test_host_attention_exit_is_valid_read_only_evidence(mock_run):
    mock_run.return_value = mock.Mock(
        returncode=2,
        stdout=json.dumps({
            "verdict": "ATTENTION",
            "flags": ["capture loop down"],
        }),
        stderr="",
    )

    snapshot = host_status_snapshot(script_path="fixture-status.ps1")

    assert snapshot["available"] is True
    assert snapshot["payload"]["verdict"] == "ATTENTION"
    assert snapshot["path"] == "fixture-status.ps1"
    command = mock_run.call_args.args[0]
    assert command[command.index("-RepoRoot") + 1] == str(REPO_ROOT)
    assert mock_run.call_args.kwargs["cwd"] == REPO_ROOT
    assert mock_run.call_args.kwargs["timeout"] == 60
    assert snapshot["payload"]["checked_at_utc"].endswith("+00:00")


@mock.patch("weather.operations.operator_host_status.subprocess.run")
def test_host_status_rejects_bad_exit_or_non_object_json(mock_run):
    mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="failed")
    failed = host_status_snapshot(script_path="fixture-status.ps1")

    mock_run.return_value = mock.Mock(returncode=0, stdout="[]", stderr="")
    malformed = host_status_snapshot(script_path="fixture-status.ps1")

    assert failed["available"] is False
    assert "failed" in failed["error"]
    assert malformed["available"] is False
    assert "did not return an object" in malformed["error"]


def test_browser_polls_share_one_inflight_collection_without_blocking():
    started, release = threading.Event(), threading.Event()
    calls = []

    def collector():
        calls.append(1)
        started.set()
        assert release.wait(2)
        return {"available": True, "payload": {"checked_at_utc": "2026-09-06T14:00:00+00:00"}}

    cache = HostStatusCache(collector)
    assert cache.get()["loading"] is True
    assert started.wait(1)
    for _ in range(50):
        assert cache.get()["loading"] is True
    assert len(calls) == 1
    release.set()
    for _ in range(100):
        snapshot = cache.get()
        if not snapshot["loading"]:
            break
        time.sleep(0.01)
    assert snapshot["available"] is True
    assert len(calls) == 1
    assert cache.get()["payload"]["checked_at_utc"] == "2026-09-06T14:00:00+00:00"
