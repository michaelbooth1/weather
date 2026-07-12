import json
import pickle
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from weather.operations.nightly_retrain import (  # noqa: E402
    build_parser,
    default_settled_day_target_date,
    execute_experiment_queue,
    nightly_run_sla_status,
    run_nightly_retrain,
    settled_day_freshness_command,
)
from tests.operations.test_experiment_contract import materialized_manifest
from weather.reporting.daily.daily_learning_scorecard import _build_experiment_queue


def _write_base_model_fixture(root: Path, market_id: str = "nyc") -> None:
    suffix = "" if market_id == "toronto" else f"_{market_id}"
    artifacts = root / "artifacts"
    hgb = artifacts / "models" / "hgb" / f"feature_model_hgb{suffix}.pkl"
    hgb.parent.mkdir(parents=True, exist_ok=True)
    with hgb.open("wb") as handle:
        pickle.dump({"12": {"feature_names": ["forecast_high", "high_so_far"]}}, handle)
    json_paths = {
        "feature_lr_coefficients": (
            artifacts / "models" / "coefs" / f"feature_model_coefs{suffix}.json"
        ),
        "late_day_lr_coefficients": (
            artifacts / "models" / "coefs" / f"late_day_model_coefs{suffix}.json"
        ),
        "calibrated_weights": artifacts / "calibration" / f"calibrated_weights{suffix}.json",
        "probability_calibration": (
            artifacts / "calibration" / f"probability_calibration{suffix}.json"
        ),
        "forecast_error_model": (
            artifacts / "calibration" / f"forecast_error_model{suffix}.json"
        ),
        "settlement_lag_model": (
            artifacts / "calibration" / f"settlement_lag_model{suffix}.json"
        ),
        "afternoon_residual_centering": (
            artifacts / "misc" / "afternoon_residual_centering.json"
        ),
    }
    for component, path in json_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fixture_component": component, "market_id": market_id}),
            encoding="utf-8",
        )


def _args(tmp, *extra):
    root = Path(tmp)
    config = root / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "model_variant_registry.json").write_text(
        json.dumps(
            {
                "schema_version": "model_variant_registry_v0.1",
                "variants": [
                    {
                        "variant_id": "pooled_candidate",
                        "feature_manifest": {"feature_families": ["forecast_profile"]},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config / "locations.json").write_text(
        json.dumps(
            {
                "schema_version": "locations_v0.1",
                "locations": [
                    {
                        "id": "nyc",
                        "market_unit": "F",
                        "polymarket": {
                            "event_slug_prefix": "highest-temperature-in-nyc-on"
                        },
                        "settlement": {
                            "unit": "F",
                            "precision": "whole_degree",
                            "source_type": "wunderground_history",
                            "station_id": "KLGA",
                            "resolution_source_url": "https://example.test/KLGA",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (config / "location_market_events.json").write_text(
        '{"schema_version":"location_market_events_v0.1","locations":[]}',
        encoding="utf-8",
    )
    (config / "markets.json").write_text(
        '{"schema_version":"market_registry_v0.1","markets":[]}',
        encoding="utf-8",
    )
    _write_base_model_fixture(root)
    candidate = root / "artifacts" / "candidates" / "test-nightly"
    return build_parser().parse_args([
        "run",
        "--snapshots-root", str(root / "snapshots"),
        "--backtest-root", str(root / "backtest"),
        "--status-out", str(root / "backtest" / "nightly_retrain_status.json"),
        "--report-out", str(root / "backtest" / "nightly_retrain_report.md"),
        "--family-secondary-out", str(candidate / "calibration" / "f_family_secondary_artifacts.json"),
        "--pooled-band-artifact", str(candidate / "model" / "feature_model_hgb_f_pooled_v0_3.pkl"),
        "--artifact-registry", str(candidate / "config" / "model_artifact_registry.json"),
        "--candidate-id", "test-nightly",
        "--candidates-root", str(root / "artifacts" / "candidates"),
        "--releases-root", str(root / "artifacts" / "releases"),
        "--release-pointer", str(root / "artifacts" / "releases" / "current_release.json"),
        "--repo-root", str(root),
        "--skip-candidate-release-build",
        "--promotion-out", str(root / "backtest" / "f_family_promotion_refresh.json"),
        "--promotion-report", str(root / "backtest" / "f_family_promotion_refresh_report.md"),
        "--daily-learning-out", str(root / "backtest" / "daily_learning.json"),
        "--daily-learning-report", str(root / "backtest" / "daily_learning_report.md"),
        "--experiment-queue-results-out", str(root / "backtest" / "experiment_queue_results.json"),
        "--labels-csv", str(root / "backtest" / "market_day_labels.csv"),
        "--ledger-root", str(root / "settlements"),
        "--settled-day-freshness-out", str(root / "backtest" / "settled_day_freshness.json"),
        "--settled-day-freshness-report", str(root / "backtest" / "settled_day_freshness_report.md"),
        "--shadow-ab-out", str(root / "backtest" / "shadow_ab_monitor.json"),
        "--shadow-ab-report", str(root / "backtest" / "shadow_ab_monitor_report.md"),
        "--long-job-state", str(root / "backtest" / "long_job_guard_status.json"),
        "--long-job-lock", str(root / "backtest" / "long_job_guard.lock"),
        "--long-job-priority", "normal",
        "--capture-resource-mode", "offline_host",
        "--capture-resource-disk-path", str(root),
        "--capture-resource-out", str(root / "backtest" / "capture_resource_gate.json"),
        "--capture-resource-report", str(root / "backtest" / "capture_resource_gate.md"),
        "--capture-resource-min-free-memory-bytes", "0",
        "--capture-resource-min-free-disk-bytes", "0",
        "--skip-captured-input-replay-parity",
        "--skip-production-readiness-gate",
        *extra,
    ])


def _write_promotion(path, *, promote=None, shadow=None, blocked=None):
    payload = {
        "readiness": {"status": "READY"},
        "serving_gauntlet": {"verdict": "PASS_WITH_SHADOWS"},
        "decisions": {
            "promote_markets": promote or [],
            "shadow_markets": shadow or [],
            "blocked_markets": blocked or [],
            "markets": [
                {"market_id": market_id}
                for market_id in [*(promote or []), *(shadow or []), *(blocked or [])]
            ],
        },
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _materializing_runner(command, *, promotion="promote", **_kwargs):
    if "weather.calibration.family_secondary_artifacts" in command:
        out = Path(command[command.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"calibration":"candidate"}\n', encoding="utf-8")
    elif "weather.calibration.pooled_feature_model" in command:
        artifact = Path(command[command.index("--artifact") + 1])
        artifact.parent.mkdir(parents=True, exist_ok=True)
        bundle = {
            "schema_version": "pooled_feature_band_hgb_v0.1",
            "feature_schema_version": "toronto_feature_store_v1.6",
            "family_unit": "F",
            "prediction_mode": "band_binary",
            "feature_subset": "all",
            "feature_subset_contract": {"feature_families": ["forecast_profile"]},
            "models": {
                "8": {
                    "feature_names": ["forecast_high", "band_mid_minus_forecast"],
                    "feature_schema_version": "toronto_feature_store_v1.6",
                    "imputer": {"statistics": [80.0, 0.0]},
                    "temperature": 1.0,
                }
            },
            "postprocess": {},
            "corpus_lineage": {
                "selection_training": {
                    "row_count": 20,
                    "sha256": "1" * 64,
                    "target_date_min": "2024-06-01",
                    "target_date_max": "2024-07-01",
                },
                "evaluation": {
                    "row_count": 10,
                    "sha256": "2" * 64,
                    "target_date_min": "2025-06-01",
                    "target_date_max": "2025-07-01",
                },
                "final_refit": {
                    "row_count": 30,
                    "sha256": "3" * 64,
                    "target_date_min": "2024-06-01",
                    "target_date_max": "2025-07-01",
                },
                "model_input_fields": ["forecast_high", "band_mid_minus_forecast"],
                "evaluation_only_label_fields": ["outcome"],
            },
        }
        with artifact.open("wb") as handle:
            pickle.dump(bundle, handle)
    elif "weather.artifacts" in command and "registry" in command:
        out = Path(command[command.index("--out") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text('{"registry":"candidate"}\n', encoding="utf-8")
    elif "weather.reporting.promotion.promotion_refresh" in command:
        out = command[command.index("--out") + 1]
        if promotion == "promote":
            _write_promotion(out, promote=["nyc"])
        elif promotion == "shadow":
            _write_promotion(out, shadow=["nyc"])
        else:
            _write_promotion(out, blocked=["nyc"])
    return {"returncode": 0, "stdout": "ok", "stderr": ""}


def _clean_code_identity(*, repo_root):
    del repo_root
    return {
        "git_commit": "d" * 40,
        "git_branch": "main",
        "git_dirty": False,
        "dirty_fingerprint": None,
        "dirty_entry_count": 0,
    }


class TestNightlyRetrain(unittest.TestCase):
    def test_cli_defaults_capture_resource_admission_to_live_host(self):
        args = build_parser().parse_args(["run"])

        self.assertEqual(args.capture_resource_mode, "live")
        self.assertFalse(args.skip_captured_input_replay_parity)
        self.assertFalse(args.skip_production_readiness_gate)

    def test_dry_run_plans_candidate_only_outputs_and_manual_release_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status, _report = run_nightly_retrain(
                _args(tmp, "--build-candidate-release", "--dry-run"),
                runner=lambda *_args, **_kwargs: self.fail("dry run executed a subprocess"),
            )
            release_dir = Path(tmp) / "artifacts" / "releases" / "test-nightly"
            release_exists = release_dir.exists()

        guard = payload["config"]["candidate_output_guard"]
        self.assertEqual(guard["status"], "PASS")
        self.assertTrue(guard["release_eligible"])
        self.assertTrue(all(row["status"] == "CANDIDATE_ONLY" for row in guard["outputs"]))
        self.assertEqual(payload["candidate_release"]["status"], "PLANNED")
        self.assertEqual(payload["steps"][-1]["name"], "candidate_release_build")
        self.assertFalse(release_exists)

    def test_default_training_outputs_are_derived_inside_the_run_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status, _report = run_nightly_retrain(
                _args(
                    tmp,
                    "--pooled-band-artifact",
                    "",
                    "--family-secondary-out",
                    "",
                    "--artifact-registry",
                    "",
                    "--candidate-id",
                    "defaults-r1",
                    "--build-candidate-release",
                    "--dry-run",
                )
            )

        outputs = {
            row["attribute"]: Path(row["path"]).as_posix()
            for row in payload["config"]["candidate_output_guard"]["outputs"]
        }
        self.assertTrue(outputs["pooled_band_artifact"].endswith("defaults-r1/model/feature_model_hgb_f_pooled_v0_3.pkl"))
        self.assertTrue(outputs["family_secondary_out"].endswith("defaults-r1/calibration/f_family_secondary_artifacts.json"))
        self.assertTrue(outputs["artifact_registry"].endswith("defaults-r1/config/model_artifact_registry.json"))

    def test_invalid_candidate_id_fails_preflight_before_any_training(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            payload, _status, _report = run_nightly_retrain(
                _args(tmp, "--candidate-id", "../escape", "--build-candidate-release"),
                runner=lambda command, **_kwargs: calls.append(command),
            )

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["config"]["candidate_output_guard"]["status"], "BLOCK")
        self.assertTrue(
            any(
                failure["attribute"] == "candidate_id"
                for failure in payload["config"]["candidate_output_guard"]["failures"]
            )
        )
        self.assertEqual(calls, [])

    def test_live_capture_denial_stops_before_candidate_preflight_or_training(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            snapshots = root / "snapshots"
            snapshots.mkdir(parents=True)
            now = datetime.now(timezone.utc).isoformat()
            status = snapshots / "loop_status.json"
            status.write_text(
                json.dumps(
                    {
                        "pid": 999_999,
                        "last_heartbeat": now,
                        "interval_seconds": 600,
                        "consecutive_errors": 0,
                    }
                ),
                encoding="utf-8",
            )
            status.with_name(f".{status.name}.writer.lock").write_text(
                json.dumps(
                    {
                        "pid": 999_999,
                        "loop": "snapshot",
                        "module": "weather.collection.snapshot_tracker",
                        "acquired_at_utc": now,
                    }
                ),
                encoding="utf-8",
            )
            args = _args(tmp, "--capture-resource-mode", "live")
            with patch(
                "weather.operations.nightly_retrain.prepare_candidate_outputs",
                side_effect=AssertionError(
                    "candidate output preparation started after admission denial"
                ),
            ):
                payload, status_path, _report_path = run_nightly_retrain(
                    args,
                    runner=lambda command, **_kwargs: calls.append(command),
                )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            proof = json.loads(
                Path(args.capture_resource_out).read_text(encoding="utf-8")
            )

        self.assertEqual(calls, [])
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["steps"][0]["name"], "capture_resource_admission")
        self.assertEqual(payload["steps"][0]["status"], "blocked")
        self.assertEqual(saved["status"], "blocked")
        self.assertFalse(proof["admitted"])
        self.assertEqual(proof["decision"], "DEFER")
        self.assertIn(
            "live_capture_loop_active",
            {row["code"] for row in proof["blockers"]},
        )

    def test_missing_replay_blocks_nightly_children_and_final_gate_is_read_only(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            served = root / "captured" / "served.json"
            served.parent.mkdir(parents=True)
            served.write_text("[]\n", encoding="utf-8")
            args = _args(tmp)
            args.skip_captured_input_replay_parity = False
            args.captured_input_parity_served = [str(served)]
            args.captured_input_parity_replay = [
                str(root / "captured" / "replay.json")
            ]
            args.captured_input_parity_out = str(
                root / "backtest" / "live_variant_replay_parity.json"
            )
            args.captured_input_parity_report = str(
                root / "backtest" / "live_variant_replay_parity.md"
            )
            args.skip_production_readiness_gate = False
            args.production_readiness_evidence = []
            args.production_readiness_served_artifact = []
            args.production_readiness_served_route = ""
            args.production_readiness_out = str(
                root / "backtest" / "production_readiness_gate.json"
            )
            args.production_readiness_report = str(
                root / "backtest" / "production_readiness_gate.md"
            )
            with (
                patch(
                    "weather.operations.nightly_retrain.producer_release_proof",
                    return_value={
                        "status": "PASS",
                        "release_id": "active-r1",
                        "release_manifest_sha256": "a" * 64,
                    },
                ),
                patch(
                    "weather.operations.nightly_retrain.prepare_candidate_outputs",
                    side_effect=AssertionError(
                        "candidate preparation started after parity block"
                    ),
                ),
            ):
                payload, status_path, _report_path = run_nightly_retrain(
                    args,
                    runner=lambda command, **_kwargs: calls.append(command),
                )
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            parity = json.loads(
                Path(args.captured_input_parity_out).read_text(encoding="utf-8")
            )
            gate = json.loads(
                Path(args.production_readiness_out).read_text(encoding="utf-8")
            )
            parity_report_exists = Path(args.captured_input_parity_report).is_file()
            gate_report_exists = Path(args.production_readiness_report).is_file()
            pointer_exists = Path(args.release_pointer).exists()

        self.assertEqual(calls, [])
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["steps"][0]["name"], "captured_input_replay_parity")
        self.assertEqual(payload["steps"][0]["status"], "blocked")
        self.assertIn(
            "generate exact captured-input replay rows",
            payload["steps"][0]["next_action"],
        )
        self.assertEqual(payload["candidate_release"]["status"], "BLOCK")
        self.assertEqual(payload["steps"][-1]["name"], "production_readiness_gate")
        self.assertEqual(payload["steps"][-1]["status"], "ok")
        self.assertEqual(payload["production_readiness"]["status"], "BLOCK")
        self.assertTrue(payload["production_readiness"]["read_only"])
        self.assertFalse(payload["production_readiness"]["pointer_mutated"])
        self.assertEqual(saved["status"], "blocked")
        self.assertEqual(parity["status"], "BLOCK")
        self.assertEqual(gate["status"], "BLOCK")
        self.assertTrue(parity_report_exists)
        self.assertTrue(gate_report_exists)
        self.assertFalse(pointer_exists)

    def test_parity_exception_persists_block_and_final_readiness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = _args(tmp)
            args.skip_captured_input_replay_parity = False
            args.skip_production_readiness_gate = False
            with (
                patch(
                    "weather.operations.nightly_retrain.live_variant_settlement_scorecard.persist_captured_input_replay_parity",
                    side_effect=ValueError("bad parity configuration"),
                ),
                patch(
                    "weather.operations.nightly_retrain.prepare_candidate_outputs",
                    side_effect=AssertionError("candidate preparation started"),
                ),
            ):
                payload, _status, _report = run_nightly_retrain(
                    args,
                    runner=lambda *_args, **_kwargs: self.fail("child started"),
                )
            parity_path = root / "backtest" / "live_variant_replay_parity.json"
            parity = json.loads(parity_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["steps"][-1]["name"], "production_readiness_gate")
        self.assertEqual(parity["first_mismatch"]["code"], "parity_preflight_exception")
        parity_step = next(row for row in payload["steps"] if row["name"] == "captured_input_replay_parity")
        self.assertEqual(parity_step["proof_path"], str(parity_path))

    def test_readiness_block_policy_marks_nightly_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            args.skip_production_readiness_gate = False
            args.fail_on_production_readiness_block = True
            payload, _status, _report = run_nightly_retrain(
                args,
                runner=_materializing_runner,
            )

        self.assertEqual(payload["production_readiness"]["status"], "BLOCK")
        self.assertEqual(payload["status"], "blocked")

    def test_legacy_output_fails_before_training_by_default(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "artifacts" / "models" / "active.pkl"
            payload, _status, _report = run_nightly_retrain(
                _args(tmp, "--pooled-band-artifact", str(legacy), "--build-candidate-release"),
                runner=lambda command, **_kwargs: calls.append(command),
            )
            legacy_exists = legacy.exists()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["config"]["candidate_output_guard"]["status"], "BLOCK")
        self.assertEqual(payload["steps"][0]["name"], "candidate_output_preflight")
        self.assertEqual(calls, [])
        self.assertFalse(legacy_exists)

    def test_legacy_compatibility_is_quarantined_and_cannot_build_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "artifacts" / "models" / "active.pkl"
            payload, _status, _report = run_nightly_retrain(
                _args(
                    tmp,
                    "--pooled-band-artifact",
                    str(legacy),
                    "--allow-legacy-serving-output",
                    "--build-candidate-release",
                ),
                runner=_materializing_runner,
                release_builder=lambda **_kwargs: self.fail("quarantined outputs built a release"),
                code_identity_provider=_clean_code_identity,
            )
            release_exists = (root / "artifacts" / "releases" / "test-nightly").exists()

        self.assertEqual(payload["config"]["candidate_output_guard"]["status"], "QUARANTINED_LEGACY_OUTPUT")
        self.assertEqual(payload["candidate_release"]["reason"], "legacy_training_output_quarantined")
        self.assertEqual(payload["status"], "blocked")
        pooled_step = next(step for step in payload["steps"] if step["name"] == "pooled_feature_model_band")
        self.assertIn("--allow-legacy-serving-output", pooled_step["command"])
        self.assertFalse(release_exists)

    def test_passed_gates_build_inactive_immutable_release_without_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, _status, report_path = run_nightly_retrain(
                _args(tmp, "--build-candidate-release"),
                runner=_materializing_runner,
                code_identity_provider=_clean_code_identity,
            )
            release_dir = root / "artifacts" / "releases" / "test-nightly"
            manifest = json.loads((release_dir / "release_manifest.json").read_text(encoding="utf-8"))
            report = Path(report_path).read_text(encoding="utf-8")
            pointer_exists = (release_dir.parent / "current_release.json").exists()

        self.assertEqual(payload["status"], "promote_ready")
        self.assertTrue(payload["capture_resource_admission"]["admitted"])
        self.assertEqual(
            payload["capture_resource_admission"]["decision"],
            "ADMIT",
        )
        self.assertEqual(payload["candidate_release"]["status"], "CREATED")
        self.assertEqual(payload["candidate_release"]["activation"], "MANUAL_POINTER_ONLY")
        self.assertTrue(payload["candidate_release"]["active_pointer_unchanged"])
        self.assertEqual(manifest["release_id"], "test-nightly")
        self.assertEqual(manifest["state"], "IMMUTABLE_CANDIDATE")
        self.assertEqual(manifest["code"]["git_dirty"], False)
        self.assertEqual(manifest["artifacts"]["file_count"], 25)
        self.assertEqual(
            {
                row["role"]: row["kind"]
                for row in manifest["artifacts"]["inventory"]
                if row["declared"]
            }["semantic_serving_contract"],
            "contract",
        )
        self.assertFalse(pointer_exists)
        self.assertIn("MANUAL_POINTER_ONLY", report)

    def test_shadow_gate_keeps_candidate_mutable_and_does_not_build_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def runner(command, **kwargs):
                return _materializing_runner(command, promotion="shadow", **kwargs)

            payload, _status, _report = run_nightly_retrain(
                _args(tmp, "--build-candidate-release"),
                runner=runner,
                code_identity_provider=_clean_code_identity,
            )
            release_exists = (root / "artifacts" / "releases" / "test-nightly").exists()

        self.assertEqual(payload["status"], "shadow")
        self.assertEqual(payload["candidate_release"]["status"], "NOT_BUILT")
        self.assertEqual(payload["steps"][-1]["status"], "skipped")
        self.assertFalse(release_exists)

    def test_dirty_source_blocks_release_build_after_gates_without_creating_release(self):
        def dirty_code_identity(*, repo_root):
            del repo_root
            return {
                "git_commit": "e" * 40,
                "git_branch": "main",
                "git_dirty": True,
                "dirty_fingerprint": "f" * 64,
                "dirty_entry_count": 1,
            }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload, _status, _report = run_nightly_retrain(
                _args(tmp, "--build-candidate-release"),
                runner=_materializing_runner,
                code_identity_provider=dirty_code_identity,
            )
            release_exists = (root / "artifacts" / "releases" / "test-nightly").exists()

        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["candidate_release"]["status"], "BLOCK")
        self.assertIn("clean source tree", payload["candidate_release"]["error"])
        self.assertFalse(release_exists)

    def test_run_executes_steps_and_reports_promote_ready_status(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.promotion.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, promote=["nyc"], shadow=["denver"])
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            args.producer_sla_seconds = 8 * 60 * 60
            args._producer_invocation = {
                "status": "PASS",
                "mode": "scheduled",
                "scheduler_attested": True,
                "task_name": "WeatherNightlyRetrainValidatePromote",
                "task_definition_sha256": "a" * 64,
                "manual_intervention": False,
                "manual_intervention_reasons": [],
                "resume_from_step": "",
                "resumed": False,
                "dry_run": False,
                "contract": {"status": "PASS", "contract_sha256": "b" * 64},
                "task_run_correlation": {"status": "PASS"},
            }
            args._producer_release_identity = {
                "status": "PASS",
                "served_bindings_verified": True,
                "release_id": "release-fixture",
                "release_manifest_sha256": "c" * 64,
            }
            payload, status_path, report_path = run_nightly_retrain(args, runner=runner)
            saved = json.loads(Path(status_path).read_text(encoding="utf-8"))
            guard_state = json.loads((Path(tmp) / "backtest" / "long_job_guard_status.json").read_text(encoding="utf-8"))
            report_exists = Path(report_path).exists()

        self.assertEqual([step["name"] for step in payload["steps"]], [
            "settled_day_freshness",
            "daily_learning",
            "experiment_queue",
            "family_secondary_artifacts",
            "pooled_feature_model_band",
            "artifact_registry",
            "promotion_refresh",
            "shadow_ab_monitor",
        ])
        self.assertEqual(len(calls), 7)
        self.assertIn("weather.operations.settled_day_freshness", calls[0])
        self.assertEqual(payload["status"], "promote_ready")
        self.assertEqual(saved["promotion"]["promote_markets"], ["nyc"])
        self.assertTrue(saved["config"]["long_job_guard"]["enabled"])
        self.assertEqual(saved["invocation"]["status"], "PASS")
        self.assertEqual(saved["lock_proof"]["status"], "PASS")
        self.assertEqual(saved["sla"]["status"], "PASS")
        self.assertEqual(saved["release_identity"]["status"], "PASS")
        self.assertEqual(saved["release_id"], "release-fixture")
        self.assertEqual(guard_state["status"], "complete")
        self.assertTrue(report_exists)

    def test_run_marks_blocked_when_promotion_blocks_markets(self):
        def runner(command, **_kwargs):
            if "weather.reporting.promotion.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, blocked=["miami"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["promotion"]["blocked_markets"], ["miami"])

    def test_run_stops_on_step_failure_by_default(self):
        def runner(command, **_kwargs):
            if "weather.calibration.pooled_feature_model" in command:
                return {"returncode": 2, "stdout": "", "stderr": "training failed"}
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "error")
        self.assertEqual([step["name"] for step in payload["steps"]], [
            "settled_day_freshness",
            "daily_learning",
            "experiment_queue",
            "family_secondary_artifacts",
            "pooled_feature_model_band",
        ])
        self.assertEqual(payload["steps"][-1]["returncode"], 2)

    def test_dry_run_records_plan_without_running_steps(self):
        def runner(_command, **_kwargs):
            raise AssertionError("dry run should not execute commands")

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(
                _args(tmp, "--dry-run"),
                runner=runner,
            )

        self.assertEqual(payload["status"], "dry_run")
        self.assertEqual([step["status"] for step in payload["steps"]], ["planned"] * 8)
        self.assertFalse(payload["config"]["long_job_guard"]["enabled"])

    def test_legacy_nonempty_experiment_queue_blocks_before_later_training(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "ACTIONABLE",
                        "run_date": "2026-06-24",
                        "summary": {"learning_count": 1, "blocker_count": 0},
                        "retrain_plan": {
                            "training_ready": True,
                            "retrain_recommendation": {
                                "recommended": True,
                                "status": "RECOMMENDED",
                                "scheduled_fallback": False,
                                "reasons": [{"code": "eligible_experiment_queue"}],
                            },
                        },
                        "experiment_queue": {
                            "status": "READY",
                            "summary": {"queue_count": 1, "eligible_count": 1},
                            "items": [
                                {
                                    "queue_id": "item301:2026-06-23:seattle:cold_miss",
                                    "status": "queued",
                                    "priority": "P1",
                                    "source": "june23_location_bias_repair_packet",
                                    "category": "june23_location_bias_repair",
                                    "slice": "market_id=seattle;bias=cold_miss",
                                    "hypothesis": "repair seattle cold miss",
                                    "artifact_path": "data/backtest/june23_location_bias_repair_packet.json",
                                    "clearance_rule": "protect winners",
                                    "command": ["python", "-m", "weather.reporting.location_analysis.june23_location_bias_repair"],
                                }
                            ],
                        },
                        "learnings": [],
                    }),
                    encoding="utf-8",
                )
            if "weather.reporting.promotion.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, shadow=["nyc"])
            return {"returncode": 0, "stdout": "ok", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)
            results = json.loads((Path(tmp) / "backtest" / "experiment_queue_results.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(results["schema_version"], "experiment_queue_results_v0.1")
        self.assertEqual(results["status"], "BLOCK")
        self.assertEqual(results["reason"], "experiment_queue_contract_invalid")
        self.assertEqual(results["executed_count"], 0)
        self.assertEqual(results["results"], [])
        self.assertEqual(payload["steps"][-1]["name"], "experiment_queue")
        self.assertEqual(payload["steps"][-1]["status"], "blocked")
        self.assertTrue(payload["steps"][-1]["result"]["hard_stop_pipeline"])
        self.assertNotIn("family_secondary_artifacts", {step["name"] for step in payload["steps"]})
        self.assertFalse(
            any(
                "weather.reporting.location_analysis.june23_location_bias_repair"
                in command
                for command in calls
            )
        )

    def test_self_hash_bad_ineligible_command_is_blocked_and_never_runs(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            args = _args(tmp)
            Path(args.daily_learning_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.daily_learning_out).write_text(
                json.dumps(
                    {
                        "experiment_queue": {
                            "schema_version": "automatic_experiment_queue_v0.2",
                            "queue_sha256": "0" * 64,
                            "status": "READY",
                            "summary": {"queue_count": 1, "eligible_count": 0},
                            "items": [
                                {
                                    "queue_id": "tampered",
                                    "status": "queued",
                                    "eligible": False,
                                    "command": ["python", "-c", "print('must not run')"],
                                    "argv": [],
                                }
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )

            result, _out = execute_experiment_queue(
                args,
                runner=lambda command, **_kwargs: calls.append(command),
            )

        self.assertEqual(calls, [])
        self.assertEqual(result["status"], "BLOCK")
        self.assertEqual(result["reason"], "experiment_queue_contract_invalid")
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["results"], [])

    def test_verified_materialized_experiment_is_deferred_without_execution(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = _args(tmp)
            manifest = materialized_manifest(root)
            learning = {
                "source": "test",
                "category": "experiment",
                "priority": "P1",
                "retrain_input": True,
                "blocker": False,
                "evidence": {
                    "queue_id": manifest["queue_id"],
                    "slice": "settlement_distance=0",
                    "experiment_manifest": manifest,
                },
            }
            queue = _build_experiment_queue(
                [learning],
                {},
                {},
                generated_at_utc="2026-07-11T12:00:00+00:00",
                run_date="2026-07-11",
                repo_root=root,
            )
            Path(args.daily_learning_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.daily_learning_out).write_text(
                json.dumps({"experiment_queue": queue}),
                encoding="utf-8",
            )

            with patch("weather.operations.nightly_retrain.REPO_ROOT", root):
                result, _out = execute_experiment_queue(
                    args,
                    runner=lambda command, **_kwargs: calls.append(command),
                )

        self.assertEqual(calls, [])
        self.assertEqual(result["status"], "DEFERRED")
        self.assertEqual(
            result["reason"],
            "isolated_experiment_executor_not_implemented",
        )
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(result["deferred_queue_ids"], [manifest["queue_id"]])
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual(result["results"], [])

    def test_no_retrain_recommendation_can_skip_expensive_steps_without_disabling_default_schedule(self):
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "ACTIONABLE",
                        "run_date": "2026-06-24",
                        "summary": {"learning_count": 0, "blocker_count": 0},
                        "retrain_plan": {
                            "training_ready": True,
                            "retrain_recommendation": {
                                "recommended": False,
                                "status": "NOT_RECOMMENDED",
                                "scheduled_fallback": False,
                                "reasons": [{"code": "no_new_drift_or_novelty"}],
                            },
                        },
                        "experiment_queue": {
                            "status": "EMPTY",
                            "summary": {"queue_count": 0, "eligible_count": 0},
                            "items": [],
                        },
                        "learnings": [],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(
                _args(tmp, "--skip-when-no-retrain-recommendation"),
                runner=runner,
            )

        self.assertEqual(payload["status"], "skipped_no_retrain_recommendation")
        self.assertEqual(payload["promotion"]["reason"], "retrain_not_recommended")
        self.assertIn("retrain_recommendation_gate", [step["name"] for step in payload["steps"]])
        self.assertFalse(any("weather.calibration.family_secondary_artifacts" in command for command in calls))

    def test_daily_learning_input_integrity_failure_marks_run_blocked(self):
        # Garbage-in still aborts: inconsistent/stale critical inputs mean the
        # queue and retrain would act on a corrupted picture.
        calls = []

        def runner(command, **_kwargs):
            calls.append(command)
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-16",
                        "summary": {"learning_count": 2, "blocker_count": 1},
                        "retrain_plan": {"training_ready": False},
                        "input_gate": {
                            "status": "FAIL",
                            "consistency": {"status": "FAIL", "failed_invariants": ["promotion_corpus_vs_settled_labels"]},
                            "freshness": {"status": "PASS"},
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "input_inconsistency",
                                "source": "daily_learning",
                                "signal": "Daily analysis input inconsistency.",
                                "action": "Regenerate upstream artifacts.",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            if "weather.reporting.promotion.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, shadow=["nyc"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_nightly_retrain(_args(tmp), runner=runner)
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["daily_learning"]["status"], "BLOCKED")
        self.assertEqual(payload["promotion"]["verdict"], "not_run")
        self.assertEqual(payload["promotion"]["reason"], "daily_learning_input_gate_blocked")
        self.assertEqual(
            [step["name"] for step in payload["steps"]],
            ["settled_day_freshness", "daily_learning", "daily_learning_input_gate"],
        )
        self.assertEqual(payload["steps"][-1]["reason"], "input_consistency_fail")
        self.assertEqual(len(calls), 2)
        self.assertEqual(payload["nightly_sla"]["state"], "BLOCKED")
        self.assertIn("daily_learning_input_gate_blocked", report)

    def test_headline_blocked_daily_learning_with_clean_inputs_still_runs_queue(self):
        # Regression (2026-07-05): the queue starved June 24 -> July 5 because
        # the run broke on the headline BLOCKED status, which includes the very
        # skill gates the queued experiments exist to repair. Policy blockers
        # must not stop the queue/retrain
        # when the input gate itself is clean.
        def runner(command, **_kwargs):
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-16",
                        "summary": {"learning_count": 2, "blocker_count": 1},
                        "retrain_plan": {"training_ready": False},
                        "input_gate": {
                            "status": "PASS",
                            "consistency": {"status": "PASS"},
                            "freshness": {"status": "WARN"},
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "hourly_performance_gate",
                                "source": "hourly_model_performance",
                                "signal": "early-hour model trails market",
                                "action": "Run predawn repair experiments.",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            if "weather.reporting.promotion.promotion_refresh" in command:
                out = command[command.index("--out") + 1]
                _write_promotion(out, shadow=["nyc"])
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        step_names = [step["name"] for step in payload["steps"]]
        self.assertIn("experiment_queue", step_names)
        self.assertIn("promotion_refresh", step_names)
        self.assertNotIn("daily_learning_input_gate", step_names)
        self.assertEqual(payload["daily_learning"]["status"], "BLOCKED")
        self.assertEqual(payload["status"], "shadow")

    def test_nightly_report_surfaces_broad_live_forward_slo_recovery(self):
        def runner(command, **_kwargs):
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-17",
                        "summary": {"learning_count": 1, "blocker_count": 1},
                        "retrain_plan": {
                            "training_ready": False,
                            "promotion_ready": False,
                            "broad_live_forward_slo": {
                                "status": "BLOCK",
                                "counts_toward_live_forward_gate": False,
                                "reason": "clob_book_freshness blocks broad live-forward SLO for nyc",
                                "first_blocker": {
                                    "market_id": "nyc",
                                    "component": "clob_book_capture",
                                    "gate": "clob_book_freshness",
                                    "owner": "CLOB book supervisor",
                                    "repair_command": "python -m weather.market.market_microstructure ensure",
                                    "verification_command": "python -m weather.reporting.fleet.fleet_observability report",
                                },
                                "recovery_checklist": [
                                    {
                                        "market_id": "nyc",
                                        "component": "clob_book_capture",
                                        "gate": "clob_book_freshness",
                                        "owner": "CLOB book supervisor",
                                        "repair_command": "python -m weather.market.market_microstructure ensure",
                                    }
                                ],
                                "rerun_command": "python -m weather.reporting.fleet.fleet_observability report",
                            },
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "collection_health",
                                "source": "fleet_observability",
                                "signal": "clob_book_freshness blocks broad live-forward SLO for nyc",
                                "action": "python -m weather.market.market_microstructure ensure",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, report_path = run_nightly_retrain(_args(tmp), runner=runner)
            report = Path(report_path).read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(
            payload["daily_learning"]["broad_live_forward_slo"]["first_blocker"]["gate"],
            "clob_book_freshness",
        )
        self.assertEqual(payload["nightly_sla"]["broad_live_forward_slo_counts"], False)
        self.assertIn("## Broad Live-Forward SLO", report)
        self.assertIn("clob_book_freshness", report)
        self.assertIn("weather.market.market_microstructure ensure", report)

    def test_nightly_status_carries_variant_learning_gate_from_daily_learning(self):
        def runner(command, **_kwargs):
            if "weather.reporting.daily.daily_learning" in command:
                out = command[command.index("--json-out") + 1]
                Path(out).parent.mkdir(parents=True, exist_ok=True)
                Path(out).write_text(
                    json.dumps({
                        "status": "BLOCKED",
                        "run_date": "2026-06-18",
                        "summary": {"learning_count": 1, "blocker_count": 1},
                        "retrain_plan": {
                            "training_ready": False,
                            "variant_learning_gate": {
                                "status": "BLOCK",
                                "first_blocker": {
                                    "gate": "variant_evidence_sla",
                                    "detail": "no independent growth",
                                    "remediation_command": "Collect new settled labels.",
                                },
                            },
                        },
                        "learnings": [
                            {
                                "priority": "P0",
                                "category": "variant_learning_operational_gate",
                                "source": "daily_refresh_status",
                                "signal": "Variant learning operational gate blocked.",
                                "action": "Collect new settled labels.",
                                "blocker": True,
                            }
                        ],
                    }),
                    encoding="utf-8",
                )
            return {"returncode": 0, "stdout": "", "stderr": ""}

        with tempfile.TemporaryDirectory() as tmp:
            payload, _status_path, _report_path = run_nightly_retrain(_args(tmp), runner=runner)

        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["daily_learning"]["variant_learning_gate"]["status"], "BLOCK")
        self.assertEqual(
            payload["daily_learning"]["variant_learning_gate"]["first_blocker"]["gate"],
            "variant_evidence_sla",
        )

    def test_nightly_run_sla_flags_missed_run_after_scheduled_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            sla = nightly_run_sla_status(
                status_path=Path(tmp) / "missing_status.json",
                task_status={"Registered": True, "State": "Ready"},
                now=datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(sla["state"], "CRITICAL")
        self.assertFalse(sla["fresh_for_latest_window"])
        self.assertEqual(sla["alerts"][0]["category"], "nightly_retrain_missed_run")

    def test_nightly_run_sla_surfaces_first_daily_learning_blocker(self):
        status_payload = {
            "status": "blocked",
            "generated_at_utc": "2026-06-17T08:00:00+00:00",
            "daily_learning": {
                "status": "BLOCKED",
                "blocker_count": 1,
                "blockers": [
                    {
                        "priority": "P0",
                        "category": "collection_health",
                        "source": "fleet_observability",
                        "signal": "Fleet status CRITICAL",
                        "action": "Repair collection loops.",
                    }
                ],
            },
        }

        sla = nightly_run_sla_status(
            status_payload=status_payload,
            task_status={"Registered": True, "State": "Ready"},
            now=datetime(2026, 6, 17, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(sla["state"], "BLOCKED")
        self.assertTrue(sla["fresh_for_latest_window"])
        self.assertEqual(sla["p0_gate"], "Fleet status CRITICAL")
        self.assertEqual(sla["p0_action"], "Repair collection loops.")

    def test_status_command_is_read_only_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "nightly_retrain_sla_status.json"
            report = root / "nightly_retrain_sla_status_report.md"
            args = build_parser().parse_args([
                "status",
                "--status-path",
                str(root / "nightly_retrain_status.json"),
                "--out",
                str(out),
                "--report",
                str(report),
            ])
            with patch(
                "weather.operations.nightly_retrain.nightly_run_sla_status",
                return_value={"schema_version": "nightly_retrain_sla_status_v0.1", "state": "BLOCKED"},
            ):
                code = args.func(args)

        self.assertEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertFalse(report.exists())

    def test_default_settled_day_target_skips_unfinalizable_yesterday_overnight(self):
        # 03:30 ET scheduled run: yesterday's labels are only finalized by the
        # 09:30 daily refresh later that morning, so the gate targets date-2.
        overnight = datetime(2026, 7, 1, 7, 30, tzinfo=timezone.utc)  # 03:30 ET
        self.assertEqual(default_settled_day_target_date(now=overnight), "2026-06-29")

        # After the finalize window completes, yesterday is the right target.
        afternoon = datetime(2026, 7, 1, 19, 0, tzinfo=timezone.utc)  # 15:00 ET
        self.assertEqual(default_settled_day_target_date(now=afternoon), "2026-06-30")

    def test_settled_day_freshness_command_defaults_to_finalizable_target_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = settled_day_freshness_command(_args(tmp))
            self.assertIn("--target-date", command)
            self.assertEqual(
                command[command.index("--target-date") + 1],
                default_settled_day_target_date(),
            )

            explicit = settled_day_freshness_command(
                _args(tmp, "--settled-day-target-date", "2026-06-15")
            )
            self.assertEqual(explicit[explicit.index("--target-date") + 1], "2026-06-15")

            as_of_only = settled_day_freshness_command(
                _args(tmp, "--settled-day-as-of", "2026-07-01T12:00:00+00:00")
            )
            self.assertNotIn("--target-date", as_of_only)
            self.assertIn("--as-of", as_of_only)


if __name__ == "__main__":
    unittest.main()
