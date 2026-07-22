import json
from unittest.mock import patch

from weather.operations.daily_refresh_step_child import run_child
from weather.schema_registry import schema_version


def _write_args(path, step_name="maker_paper_score"):
    path.write_text(
        json.dumps({"step": step_name, "args": {}}),
        encoding="utf-8",
    )


def test_success_receipt_records_mocked_current_process_peaks(tmp_path):
    args_path = tmp_path / "step.args.json"
    result_path = tmp_path / "step.result.json"
    _write_args(args_path)

    with patch(
        "weather.operations.daily_refresh_step_child._runner_for_step",
        return_value=lambda _args: {"status": "PASS"},
    ), patch(
        "weather.operations.daily_refresh_step_child._query_current_process_memory_peaks",
        return_value={
            "peak_working_set_bytes": 2_345_678_901,
            "peak_commit_bytes": 2_987_654_321,
        },
    ):
        return_code = run_child("maker_paper_score", args_path, result_path)

    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    assert return_code == 0
    assert receipt["status"] == "ok"
    assert receipt["schema_version"] == schema_version("daily_refresh_step_child")
    assert receipt["schema_version"] == "daily_refresh_step_child_v0.2"
    assert receipt["peak_working_set_bytes"] == 2_345_678_901
    assert receipt["peak_commit_bytes"] == 2_987_654_321


def test_failure_receipt_records_mocked_current_process_peaks(tmp_path):
    args_path = tmp_path / "step.args.json"
    result_path = tmp_path / "step.result.json"
    _write_args(args_path)

    def fail_step(_args):
        raise RuntimeError("expected failure")

    with patch(
        "weather.operations.daily_refresh_step_child._runner_for_step",
        return_value=fail_step,
    ), patch(
        "weather.operations.daily_refresh_step_child._query_current_process_memory_peaks",
        return_value={
            "peak_working_set_bytes": 123_456_789,
            "peak_commit_bytes": 234_567_890,
        },
    ):
        return_code = run_child("maker_paper_score", args_path, result_path)

    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    assert return_code == 1
    assert receipt["status"] == "error"
    assert receipt["peak_working_set_bytes"] == 123_456_789
    assert receipt["peak_commit_bytes"] == 234_567_890


def test_peak_query_failure_is_nullable_and_never_fails_step(tmp_path):
    args_path = tmp_path / "step.args.json"
    result_path = tmp_path / "step.result.json"
    _write_args(args_path)

    with patch(
        "weather.operations.daily_refresh_step_child._runner_for_step",
        return_value=lambda _args: {"status": "PASS"},
    ), patch(
        "weather.operations.daily_refresh_step_child._query_current_process_memory_peaks",
        side_effect=OSError("query unavailable"),
    ):
        return_code = run_child("maker_paper_score", args_path, result_path)

    receipt = json.loads(result_path.read_text(encoding="utf-8"))
    assert return_code == 0
    assert receipt["status"] == "ok"
    assert receipt["peak_working_set_bytes"] is None
    assert receipt["peak_commit_bytes"] is None
