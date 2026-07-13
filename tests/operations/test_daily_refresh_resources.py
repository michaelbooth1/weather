import json
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.daily_refresh import _run_isolated_stage_a_step
from weather.operations.daily_refresh_resources import (
    MIB,
    STAGE_A_ISOLATED_STEPS,
    StageAChildFailure,
    bounded_resume_command,
    build_stage_a_step_admission,
    step_resource_budget,
)


def _args(tmp, **overrides):
    root = Path(tmp)
    values = {
        "backtest_root": str(root / "backtest"),
        "snapshots_root": str(root / "snapshots"),
        "status_out": str(root / "backtest" / "daily_refresh_status.json"),
        "long_job_state": str(root / "backtest" / "long_job_guard_status.json"),
        "capture_resource_mode": "offline_host",
        "stage": "settlement",
        "stage_a_min_available_reserve_mb": 1536,
        "maker_paper_latest_active_runs": 14,
        "maker_paper_max_input_bytes": 512 * MIB,
        "_stage_a_available_memory_fn": lambda: 16 * 1024**3,
        "_stage_a_commit_percent_fn": lambda: 10.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _parent_payload():
    return {
        "status": "running",
        "terminal": False,
        "started_at_utc": "2026-07-13T14:00:00+00:00",
        "steps": [],
        "resource_steps": [],
    }


class TestDailyRefreshResources(unittest.TestCase):
    def test_high_risk_stage_a_inventory_is_explicit(self):
        self.assertIn("taker_edge_permission_map", STAGE_A_ISOLATED_STEPS)
        self.assertIn("maker_paper_score", STAGE_A_ISOLATED_STEPS)
        self.assertIn("closed_day_parquet_incremental", STAGE_A_ISOLATED_STEPS)
        maker = step_resource_budget("maker_paper_score", reserve_mb=1536)
        self.assertEqual(maker["private_memory_max_bytes"], 4096 * MIB)
        self.assertEqual(maker["working_set_max_bytes"], 3072 * MIB)
        self.assertEqual(
            maker["required_available_before_start_bytes"],
            (1536 + 3072) * MIB,
        )

    def test_physical_availability_is_required_in_addition_to_child_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            budget = step_resource_budget("taker_edge_permission_map", reserve_mb=1536)
            required = budget["required_available_before_start_bytes"]
            args._stage_a_available_memory_fn = lambda: required - 1
            blocked = build_stage_a_step_admission(
                args,
                "taker_edge_permission_map",
                budget,
            )
            args._stage_a_available_memory_fn = lambda: required
            admitted = build_stage_a_step_admission(
                args,
                "taker_edge_permission_map",
                budget,
            )
            args._stage_a_commit_percent_fn = lambda: 70.0
            commit_blocked = build_stage_a_step_admission(
                args,
                "taker_edge_permission_map",
                budget,
            )

        self.assertEqual(blocked["decision"], "DEFER")
        self.assertEqual(blocked["blockers"][0]["code"], "insufficient_physical_availability")
        self.assertEqual(admitted["decision"], "ADMIT")
        self.assertTrue(
            admitted["physical_memory"]["decision_uses_physical_availability"]
        )
        self.assertTrue(admitted["host_commit"]["decision_uses_commit"])
        self.assertEqual(commit_blocked["decision"], "DEFER")
        self.assertEqual(commit_blocked["blockers"][0]["code"], "host_commit_above_limit")

    def test_resource_gate_overrides_can_only_be_stricter(self):
        with self.assertRaisesRegex(ValueError, "reserve"):
            step_resource_budget("maker_paper_score", reserve_mb=1535)
        with self.assertRaisesRegex(ValueError, "finite"):
            step_resource_budget(
                "maker_paper_score",
                reserve_mb=1536,
                max_commit_percent=float("nan"),
            )
        with self.assertRaisesRegex(ValueError, "no higher"):
            step_resource_budget(
                "maker_paper_score",
                reserve_mb=1536,
                max_commit_percent=70.1,
            )

    def test_child_pid_and_terminal_resume_fallback_persist_before_user_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload = _parent_payload()
            observed = {}

            def fake_run(command, **kwargs):
                kwargs["on_started"]({
                    "pid": 43210,
                    "started_before_user_code": True,
                })
                saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))
                observed.update(saved)
                result_path = Path(command[command.index("--result-json") + 1])
                result_path.write_text(
                    json.dumps({
                        "schema_version": "daily_refresh_step_child_v0.1",
                        "status": "ok",
                        "step": "taker_edge_permission_map",
                        "pid": 43210,
                        "finished_at_utc": "2026-07-13T14:00:01+00:00",
                        "result": {
                            "status": "PASS",
                            "input_row_count": 12,
                            "summary": {"selected_input_bytes": 4096},
                        },
                    }),
                    encoding="utf-8",
                )
                return {
                    "command": command,
                    "pid": 43210,
                    "returncode": 0,
                    "timed_out": False,
                    "duration_seconds": 0.1,
                    "working_set_limit": {"requested": True},
                    "resource_peaks": {
                        "private_memory_peak_bytes": 64 * MIB,
                        "working_set_peak_bytes": 32 * MIB,
                    },
                    "resource_io": {"read_bytes": 4096, "write_bytes": 1024},
                    "resource_limit_exceeded": None,
                    "containment": {"status": "PASS"},
                    "termination": {"triggered": False},
                    "runner_error": None,
                }

            with patch(
                "weather.operations.daily_refresh.run_isolated_subprocess",
                side_effect=fake_run,
            ):
                result = _run_isolated_stage_a_step(
                    args,
                    payload,
                    "taker_edge_permission_map",
                    run_id="test-run",
                )

        self.assertEqual(observed["status"], "interrupted")
        self.assertTrue(observed["terminal"])
        self.assertEqual(observed["current_step"]["child_pid"], 43210)
        self.assertTrue(
            observed["current_step"]["child_started_before_user_code"]
        )
        self.assertIn(
            "--resume-from-step taker_edge_permission_map",
            observed["current_step"]["resume_command"],
        )
        self.assertEqual(result["resource_execution"]["status"], "ok")
        self.assertEqual(
            result["resource_execution"]["result_metrics"]["input_row_count"],
            12,
        )
        self.assertEqual(
            result["resource_execution"]["result_metrics"][
                "summary.selected_input_bytes"
            ],
            4096,
        )
        self.assertEqual(
            result["resource_execution"]["subprocess"]["resource_io"]["read_bytes"],
            4096,
        )
        self.assertEqual(payload["status"], "running")

    def test_budget_failure_leaves_terminal_resumable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload = _parent_payload()

            def fake_run(_command, **kwargs):
                kwargs["on_started"]({
                    "pid": 7654,
                    "started_before_user_code": True,
                })
                return {
                    "command": ["child"],
                    "pid": 7654,
                    "returncode": 137,
                    "timed_out": False,
                    "duration_seconds": 0.2,
                    "working_set_limit": {"requested": True},
                    "resource_peaks": {
                        "private_memory_peak_bytes": 2048 * MIB,
                        "working_set_peak_bytes": 1536 * MIB,
                    },
                    "resource_limit_exceeded": {
                        "resource": "private_memory_bytes",
                        "limit_bytes": 2048 * MIB,
                    },
                    "containment": {"status": "PASS"},
                    "termination": {
                        "triggered": True,
                        "reason": "resource_budget_exceeded",
                    },
                    "runner_error": None,
                }

            with patch(
                "weather.operations.daily_refresh.run_isolated_subprocess",
                side_effect=fake_run,
            ):
                with self.assertRaises(StageAChildFailure) as raised:
                    _run_isolated_stage_a_step(
                        args,
                        payload,
                        "taker_edge_permission_map",
                        run_id="test-run",
                    )
            saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))

        self.assertEqual(saved["status"], "interrupted")
        self.assertTrue(saved["terminal"])
        self.assertEqual(saved["current_step"]["status"], "error")
        self.assertEqual(saved["current_step"]["child_pid"], 7654)
        self.assertTrue(raised.exception.payload["hard_stop_pipeline"])
        self.assertEqual(
            saved["current_step"]["failure_reason"],
            "resource_budget_exceeded",
        )
        self.assertIn("--heavy-step-subprocess", saved["current_step"]["resume_command"])

    def test_bounded_resume_keeps_fail_closed_maker_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                settled_analysis_target_date="2026-07-12",
                _original_cli_argv=[
                    "run",
                    "--backtest-root",
                    str(Path(tmp) / "backtest"),
                    "--snapshots-root",
                    str(Path(tmp) / "snapshots"),
                    "--status-out",
                    str(Path(tmp) / "custom-status.json"),
                    "--stage",
                    "settlement",
                    "--resume-from-step",
                    "maker_paper_score",
                    "--disable-heavy-step-subprocess",
                    "--force-lock",
                ],
            )
            command = bounded_resume_command(args, "settlement_source_audit")
        self.assertIn(str(Path(sys.executable)), command)
        self.assertIn("--stage settlement", command)
        self.assertIn("--status-out", command)
        self.assertIn("custom-status.json", command)
        self.assertIn("--settled-analysis-target-date 2026-07-12", command)
        self.assertIn("--resume-from-step settlement_source_audit", command)
        self.assertNotIn("--force-lock", command)
        self.assertNotIn("--disable-heavy-step-subprocess", command)
        self.assertIn("--maker-paper-latest-active-runs 14", command)
        self.assertIn(f"--maker-paper-max-input-bytes {512 * MIB}", command)

    def test_completed_child_with_blocked_postcheck_resumes_at_next_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            payload = _parent_payload()

            def fake_run(command, **kwargs):
                kwargs["on_started"]({
                    "pid": 9001,
                    "started_before_user_code": True,
                })
                result_path = Path(command[command.index("--result-json") + 1])
                result_path.write_text(
                    json.dumps({
                        "schema_version": "daily_refresh_step_child_v0.1",
                        "status": "ok",
                        "step": "maker_paper_score",
                        "pid": 9001,
                        "finished_at_utc": "2026-07-13T15:00:00+00:00",
                        "result": {"status": "PASS", "input_file_count": 2},
                    }),
                    encoding="utf-8",
                )
                return {
                    "command": command,
                    "pid": 9001,
                    "returncode": 0,
                    "timed_out": False,
                    "duration_seconds": 1.0,
                    "working_set_limit": {"requested": True},
                    "resource_peaks": {},
                    "resource_io": {},
                    "resource_limit_exceeded": None,
                    "containment": {"status": "PASS"},
                    "termination": {"triggered": False},
                    "runner_error": None,
                }

            admissions = [
                {"status": "PASS", "decision": "ADMIT"},
                {"status": "BLOCK", "decision": "DEFER", "blockers": [{"code": "capture_loop_not_fresh"}]},
            ]
            with patch(
                "weather.operations.daily_refresh.build_stage_a_step_admission",
                side_effect=admissions,
            ), patch(
                "weather.operations.daily_refresh.run_isolated_subprocess",
                side_effect=fake_run,
            ):
                result = _run_isolated_stage_a_step(
                    args,
                    payload,
                    "maker_paper_score",
                    run_id="test-run",
                )

        self.assertEqual(
            result["resource_execution"]["status"],
            "ok_postcheck_deferred",
        )
        self.assertEqual(payload["current_step"]["name"], "settlement_source_audit")
        self.assertIn(
            "--resume-from-step settlement_source_audit",
            payload["current_step"]["resume_command"],
        )


if __name__ == "__main__":
    unittest.main()
