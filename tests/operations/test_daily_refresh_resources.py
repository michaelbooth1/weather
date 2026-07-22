import json
import tempfile
import unittest
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from weather.operations.daily_refresh import _run_isolated_stage_a_step
from weather.operations.daily_refresh_resources import (
    MIB,
    STAGE_A_ISOLATED_STEPS,
    STAGE_A_STEP_RESOURCE_POLICIES,
    StageAChildFailure,
    bounded_resume_command,
    build_stage_a_step_admission,
    prepare_step_child_invocation,
    step_resource_budget,
)
from weather.operations.daily_refresh_step_child import _runner_for_step
from weather.operations.daily_refresh_steps import DEFAULT_RUNNERS


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
        self.assertIn("public_wu_settlement_restore", STAGE_A_ISOLATED_STEPS)
        self.assertIn("taker_finalization_watchdog", STAGE_A_ISOLATED_STEPS)
        maker = step_resource_budget("maker_paper_score", reserve_mb=1536)
        self.assertEqual(maker["private_memory_max_bytes"], 4096 * MIB)
        self.assertEqual(maker["working_set_max_bytes"], 3072 * MIB)
        # Phase 2: measured peak working set is ~687 MiB, so admission is gated on
        # 2048 MiB rather than the 3072 MiB containment ceiling.
        self.assertEqual(maker["admission_working_set_bytes"], 2048 * MIB)
        self.assertEqual(
            maker["required_available_before_start_bytes"],
            (1536 + 2048) * MIB,
        )
        wu_restore = step_resource_budget(
            "public_wu_settlement_restore",
            reserve_mb=1536,
        )
        self.assertEqual(wu_restore["timeout_seconds"], 60 * 60)
        self.assertEqual(wu_restore["private_memory_max_bytes"], 4096 * MIB)
        self.assertEqual(wu_restore["working_set_max_bytes"], 2560 * MIB)
        self.assertEqual(wu_restore["admission_working_set_bytes"], 2048 * MIB)
        self.assertEqual(
            wu_restore["required_available_before_start_bytes"],
            (1536 + 2048) * MIB,
        )
        watchdog = step_resource_budget(
            "taker_finalization_watchdog",
            reserve_mb=1536,
        )
        self.assertEqual(watchdog["timeout_seconds"], 60 * 60)
        self.assertEqual(watchdog["private_memory_max_bytes"], 5120 * MIB)
        self.assertEqual(watchdog["working_set_max_bytes"], 2048 * MIB)
        self.assertEqual(
            watchdog["required_available_before_start_bytes"],
            3584 * MIB,
        )

    def test_unset_admission_working_sets_preserve_existing_byte_requirements(self):
        # Steps with a measured peak carry an explicit admission working set; every
        # other isolated step must still admit against its full containment ceiling.
        measured_admission_working_sets = {
            "maker_paper_score": 2048 * MIB,
            "public_wu_settlement_restore": 2048 * MIB,
        }
        for step_name in STAGE_A_ISOLATED_STEPS:
            configured = STAGE_A_STEP_RESOURCE_POLICIES[step_name]
            budget = step_resource_budget(step_name, reserve_mb=1536)
            if step_name in measured_admission_working_sets:
                expected = measured_admission_working_sets[step_name]
                self.assertEqual(
                    configured["admission_working_set_bytes"],
                    expected,
                    msg=step_name,
                )
                self.assertEqual(
                    budget["admission_working_set_bytes"],
                    expected,
                    msg=step_name,
                )
                self.assertEqual(
                    budget["required_available_before_start_bytes"],
                    1536 * MIB + expected,
                    msg=step_name,
                )
                continue
            self.assertIsNone(
                configured["admission_working_set_bytes"],
                msg=step_name,
            )
            self.assertEqual(
                budget["admission_working_set_bytes"],
                budget["working_set_max_bytes"],
                msg=step_name,
            )
            self.assertEqual(
                budget["required_available_before_start_bytes"],
                1536 * MIB + budget["working_set_max_bytes"],
                msg=step_name,
            )

    def test_explicit_admission_working_set_drives_physical_gate_only(self):
        configured = dict(STAGE_A_STEP_RESOURCE_POLICIES["maker_paper_score"])
        configured["admission_working_set_bytes"] = 2304 * MIB
        with patch.dict(
            STAGE_A_STEP_RESOURCE_POLICIES,
            {"maker_paper_score": configured},
        ), tempfile.TemporaryDirectory() as tmp:
            budget = step_resource_budget("maker_paper_score", reserve_mb=1536)
            required = (1536 + 2304) * MIB
            args = _args(tmp)
            args._stage_a_available_memory_fn = lambda: required - 1
            blocked = build_stage_a_step_admission(
                args,
                "maker_paper_score",
                budget,
            )
            args._stage_a_available_memory_fn = lambda: required
            admitted = build_stage_a_step_admission(
                args,
                "maker_paper_score",
                budget,
            )

        self.assertEqual(budget["admission_working_set_bytes"], 2304 * MIB)
        self.assertEqual(budget["working_set_max_bytes"], 3072 * MIB)
        self.assertEqual(budget["required_available_before_start_bytes"], required)
        self.assertEqual(blocked["decision"], "DEFER")
        self.assertEqual(admitted["decision"], "ADMIT")
        self.assertEqual(
            admitted["physical_memory"]["admission_working_set_bytes"],
            2304 * MIB,
        )
        self.assertEqual(
            admitted["physical_memory"]["working_set_budget_bytes"],
            3072 * MIB,
        )

    def test_admission_working_set_never_exceeds_containment_ceiling(self):
        for step_name in STAGE_A_ISOLATED_STEPS:
            budget = step_resource_budget(step_name)
            self.assertLessEqual(
                budget["admission_working_set_bytes"],
                budget["working_set_max_bytes"],
                msg=step_name,
            )

        configured = dict(STAGE_A_STEP_RESOURCE_POLICIES["maker_paper_score"])
        configured["admission_working_set_bytes"] = (
            configured["working_set_max_bytes"] + 1
        )
        with patch.dict(
            STAGE_A_STEP_RESOURCE_POLICIES,
            {"maker_paper_score": configured},
        ), self.assertRaisesRegex(AssertionError, "containment ceiling"):
            step_resource_budget("maker_paper_score")

    def test_public_wu_restore_is_child_compatible_and_preserves_arguments(self):
        self.assertIs(
            _runner_for_step("public_wu_settlement_restore"),
            dict(DEFAULT_RUNNERS)["public_wu_settlement_restore"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            invocation = prepare_step_child_invocation(
                _args(
                    tmp,
                    wu_settlement_restore_markets="nyc,toronto",
                    wu_settlement_restore_sleep=0.25,
                    wu_settlement_restore_timeout=12.5,
                    wu_settlement_restore_skip_existing=False,
                    wu_settlement_restore_continue_on_error=False,
                ),
                "public_wu_settlement_restore",
                run_id="wu-isolation",
            )
            manifest = json.loads(
                Path(invocation["args_json"]).read_text(encoding="utf-8")
            )

        self.assertEqual(manifest["step"], "public_wu_settlement_restore")
        self.assertEqual(
            manifest["args"]["wu_settlement_restore_markets"],
            "nyc,toronto",
        )
        self.assertEqual(manifest["args"]["wu_settlement_restore_sleep"], 0.25)
        self.assertEqual(manifest["args"]["wu_settlement_restore_timeout"], 12.5)
        self.assertFalse(manifest["args"]["wu_settlement_restore_skip_existing"])
        self.assertFalse(
            manifest["args"]["wu_settlement_restore_continue_on_error"]
        )

    def test_taker_watchdog_is_child_compatible_and_preserves_arguments(self):
        self.assertIs(
            _runner_for_step("taker_finalization_watchdog"),
            dict(DEFAULT_RUNNERS)["taker_finalization_watchdog"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            invocation = prepare_step_child_invocation(
                _args(
                    tmp,
                    taker_finalization_date="2026-07-13",
                    taker_finalization_sla_hours=7.5,
                    taker_finalization_min_free_bytes=123456789,
                    taker_finalization_no_finalize=True,
                    skip_taker_bakeoff=False,
                    taker_bakeoff_strategies="raw_edge_control,edge_band_v1",
                    taker_champion_strategy_id="raw_edge_control",
                    taker_champion_min_complete_label_days=4,
                    taker_champion_min_settled_orders=9,
                ),
                "taker_finalization_watchdog",
                run_id="taker-finalization-isolation",
            )
            manifest = json.loads(
                Path(invocation["args_json"]).read_text(encoding="utf-8")
            )

        child_args = manifest["args"]
        self.assertEqual(child_args["taker_finalization_date"], "2026-07-13")
        self.assertEqual(child_args["taker_finalization_sla_hours"], 7.5)
        self.assertEqual(
            child_args["taker_finalization_min_free_bytes"],
            123456789,
        )
        self.assertTrue(child_args["taker_finalization_no_finalize"])
        self.assertFalse(child_args["skip_taker_bakeoff"])
        self.assertEqual(
            child_args["taker_bakeoff_strategies"],
            "raw_edge_control,edge_band_v1",
        )
        self.assertEqual(
            child_args["taker_champion_strategy_id"],
            "raw_edge_control",
        )
        self.assertEqual(
            child_args["taker_champion_min_complete_label_days"],
            4,
        )
        self.assertEqual(child_args["taker_champion_min_settled_orders"], 9)

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
        self.assertEqual(
            admitted["physical_memory"]["admission_working_set_bytes"],
            budget["working_set_max_bytes"],
        )
        self.assertEqual(
            admitted["physical_memory"]["working_set_budget_bytes"],
            budget["working_set_max_bytes"],
        )
        self.assertTrue(admitted["host_commit"]["decision_uses_commit"])
        self.assertEqual(commit_blocked["decision"], "DEFER")
        self.assertEqual(commit_blocked["blockers"][0]["code"], "host_commit_above_limit")

    def test_restart_then_clean_iteration_admits_without_weakening_error_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(
                tmp,
                capture_resource_mode="live",
                _stage_a_process_checker=lambda _pid: True,
            )
            snapshots_root = Path(args.snapshots_root)
            snapshots_root.mkdir(parents=True, exist_ok=True)
            now = datetime.now(timezone.utc)
            status_paths = {
                "snapshot": snapshots_root / "loop_status.json",
                "clob": snapshots_root / "clob_loop_status.json",
                "observation_trigger": snapshots_root / "observation_trigger_status.json",
            }

            def write_loop(name, pid, *, errors=0, last_error=None, iterations=1):
                path = status_paths[name]
                path.write_text(
                    json.dumps({
                        "pid": pid,
                        "started_at": now.isoformat(),
                        "last_heartbeat": now.isoformat(),
                        "interval_seconds": 60,
                        "iterations": iterations,
                        "consecutive_errors": errors,
                        "last_error": last_error,
                        "paused": False,
                    }),
                    encoding="utf-8",
                )
                path.with_name(f".{path.name}.writer.lock").write_text(
                    json.dumps({
                        "pid": pid,
                        "loop": name,
                        "acquired_at_utc": now.isoformat(),
                    }),
                    encoding="utf-8",
                )

            write_loop(
                "snapshot",
                101,
                errors=1,
                last_error="los-angeles: capture_process_error: returncode=137",
            )
            write_loop("clob", 102)
            write_loop("observation_trigger", 103)
            budget = step_resource_budget("hourly_model_performance")

            degraded = build_stage_a_step_admission(
                args,
                "hourly_model_performance",
                budget,
            )
            snapshot_blocker = next(
                blocker
                for blocker in degraded["blockers"]
                if blocker.get("loop") == "snapshot"
            )

            # A subsequent fully completed, error-free iteration clears the
            # current latch. Cadence health alone is deliberately insufficient.
            write_loop("snapshot", 101, iterations=2)
            admitted = build_stage_a_step_admission(
                args,
                "hourly_model_performance",
                budget,
            )

        self.assertEqual(degraded["decision"], "DEFER")
        self.assertEqual(snapshot_blocker["code"], "capture_loop_not_fresh")
        self.assertEqual(
            set(snapshot_blocker["degraded_reasons"]),
            {"consecutive_errors", "last_error_present"},
        )
        self.assertEqual(admitted["decision"], "ADMIT")
        self.assertEqual(admitted["blockers"], [])

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
            captured_limits = {}
            configured = dict(
                STAGE_A_STEP_RESOURCE_POLICIES["taker_edge_permission_map"]
            )
            configured["admission_working_set_bytes"] = 1024 * MIB

            def fake_run(command, **kwargs):
                captured_limits["working_set_max_bytes"] = kwargs[
                    "working_set_max_bytes"
                ]
                kwargs["on_started"]({
                    "pid": 43210,
                    "started_before_user_code": True,
                })
                saved = json.loads(Path(args.status_out).read_text(encoding="utf-8"))
                observed.update(saved)
                result_path = Path(command[command.index("--result-json") + 1])
                result_path.write_text(
                    json.dumps({
                        "schema_version": "daily_refresh_step_child_v0.2",
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

            with patch.dict(
                STAGE_A_STEP_RESOURCE_POLICIES,
                {"taker_edge_permission_map": configured},
            ), patch(
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
        self.assertEqual(captured_limits["working_set_max_bytes"], 1536 * MIB)
        self.assertEqual(
            result["resource_execution"]["budget"][
                "admission_working_set_bytes"
            ],
            1024 * MIB,
        )
        self.assertEqual(
            result["resource_execution"]["budget"][
                "working_set_max_bytes"
            ],
            1536 * MIB,
        )
        self.assertEqual(payload["status"], "running")

    def test_launcher_shim_child_receipt_pid_is_accepted_one_hop(self):
        # venv\Scripts\python.exe spawns the real interpreter as its child, so
        # the receipt's os.getpid() differs from the recorded spawn PID. The
        # 2026-07-13 production run discarded a successful hourly child for
        # exactly this reason; one launcher hop must validate, nothing looser.
        for parent_pid, expect_ok in ((43210, True), (11111, False)):
            with tempfile.TemporaryDirectory() as tmp:
                args = _args(tmp)
                payload = _parent_payload()

                def fake_run(command, **kwargs):
                    kwargs["on_started"]({
                        "pid": 43210,
                        "started_before_user_code": True,
                    })
                    result_path = Path(command[command.index("--result-json") + 1])
                    result_path.write_text(
                        json.dumps({
                            "schema_version": "daily_refresh_step_child_v0.2",
                            "status": "ok",
                            "step": "taker_edge_permission_map",
                            "pid": 99999,
                            "parent_pid": parent_pid,
                            "finished_at_utc": "2026-07-13T14:00:01+00:00",
                            "result": {"status": "PASS"},
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
                    if expect_ok:
                        result = _run_isolated_stage_a_step(
                            args,
                            payload,
                            "taker_edge_permission_map",
                            run_id="test-run",
                        )
                        validation = result["resource_execution"][
                            "child_terminal_validation"
                        ]
                        self.assertEqual(result["resource_execution"]["status"], "ok")
                        self.assertTrue(validation["pid_matches"])
                        self.assertEqual(
                            validation["pid_match_mode"], "launcher_parent"
                        )
                    else:
                        with self.assertRaises(StageAChildFailure) as raised:
                            _run_isolated_stage_a_step(
                                args,
                                payload,
                                "taker_edge_permission_map",
                                run_id="test-run",
                            )
                        self.assertIn(
                            "invalid_or_error_child_terminal",
                            str(raised.exception),
                        )

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
                        "schema_version": "daily_refresh_step_child_v0.2",
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
