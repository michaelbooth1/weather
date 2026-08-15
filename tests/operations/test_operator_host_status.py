import json
from unittest import mock

from weather.operations.operator_host_status import host_status_snapshot


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
