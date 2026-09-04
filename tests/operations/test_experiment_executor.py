from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from weather.operations import experiment_executor as experiment_executor_module
from tests.operations.test_experiment_contract import (
    materialized_manifest,
    valid_manifest_payload,
)
from weather.experiment_contract import (
    TERMINAL_DISPOSITIONS,
    ExperimentContractError,
    build_experiment_manifest,
    build_experiment_result,
    finalize_self_hash,
    verify_experiment_result,
)
from weather.operations.experiment_executor import (
    ExperimentExecutionError,
    _child_environment,
    _copy_file,
    _copy_tree,
    _measured_disposition,
    execute_one,
)
from weather.operations.long_job_guard import run_isolated_subprocess


QUIET_NOW = datetime(2026, 7, 14, 2, 0, tzinfo=ZoneInfo("America/Toronto"))
ARTIFACT_SCHEMA = "point_in_time_validation_plan_v0.1"
ARTIFACT_PAYLOAD = {
    "schema_version": ARTIFACT_SCHEMA,
    "status": "PASS",
    "source": "synthetic_isolated_experiment",
}
ARTIFACT_TEXT = json.dumps(ARTIFACT_PAYLOAD, sort_keys=True) + "\n"
ARTIFACT_SHA256 = hashlib.sha256(ARTIFACT_TEXT.encode("utf-8")).hexdigest()
LEGACY_STAGED_RESULT_LENGTH = 267
ATOMIC_TEMP_SUFFIX = ".12345.1234567890123456789.tmp"
REPAIRED_STAGING_PATH_SAVINGS = 76


def _admit(**kwargs):
    del kwargs
    return {
        "status": "PASS",
        "admitted": True,
        "decision": "ADMIT",
        "blockers": [],
        "configuration": {"source": "synthetic_test_admission"},
    }


def _execute(queue_path: Path, manifest: dict, repo_root: Path):
    return execute_one(
        queue_path,
        manifest["queue_id"],
        repo_root=repo_root,
        now=QUIET_NOW,
        admission_builder=_admit,
        commit_percent_fn=lambda: 50.0,
    )


def _write_worker(repo_root: Path) -> None:
    package = repo_root / "src" / "weather" / "reporting"
    package.mkdir(parents=True)
    (repo_root / "src" / "weather" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "synthetic_experiment.py").write_text(
        """from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True)
    parser.add_argument(
        "--mode",
        choices=(
            "success",
            "timeout",
            "attack",
            "read_attack",
            "input_attack",
            "io_flood",
            "noisy",
            "unexpected_directory",
        ),
        required=True,
    )
    parser.add_argument("--attack-path", default="")
    args = parser.parse_args()
    if args.mode == "timeout":
        partial = Path(args.output_root) / "partial-before-kill.txt"
        partial.write_text("untrusted partial output", encoding="utf-8")
        time.sleep(5)
        return 0
    if args.mode == "noisy":
        for _index in range(40):
            print("x" * (64 * 1024), flush=True)
        return 0
    if args.mode == "io_flood":
        payload = b"x" * (64 * 1024)
        with (Path.cwd() / "tmp" / "io-flood.bin").open("wb", buffering=0) as handle:
            while True:
                handle.write(payload)
                os.fsync(handle.fileno())
                time.sleep(0.01)
    if args.mode == "unexpected_directory":
        (Path(args.output_root) / "undeclared" / "nested").mkdir(parents=True)
    if args.mode == "attack":
        try:
            Path(args.attack_path).write_text("mutated-serving-bytes", encoding="utf-8")
        except PermissionError:
            pass
    if args.mode == "read_attack":
        try:
            Path(args.attack_path).read_text(encoding="utf-8")
        except PermissionError:
            print("UNDECLARED_READ_DENIED", flush=True)
        else:
            raise RuntimeError("sandbox allowed an undeclared external read")
    if args.mode == "input_attack":
        Path(args.attack_path).write_text("mutated-staged-corpus", encoding="utf-8")
    artifact = {
        "schema_version": "point_in_time_validation_plan_v0.1",
        "status": "PASS",
        "source": "synthetic_isolated_experiment",
    }
    output = Path(args.output_root) / "evidence.json"
    output.write_bytes((json.dumps(artifact, sort_keys=True) + "\\n").encode("utf-8"))
    observation = {
        "independent_sample_count": 14,
        "metrics": {
            "primary": {"name": "categorical_brier_delta", "value": -0.02},
            "protected": [{"name": "worst_location_delta", "value": 0.01}],
        },
    }
    print("EXPERIMENT_OBSERVATION_JSON=" + json.dumps(observation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
""",
        encoding="utf-8",
    )


def _manifest(
    repo_root: Path,
    *,
    mode: str,
    timeout_seconds: int = 5,
    io_write_mb: float = 16,
) -> dict:
    attack_path = (
        repo_root
        / "artifacts"
        / "releases"
        / "release-1"
        / "release_manifest.json"
    )

    def mutate(payload, _root):
        output_root = payload["candidate_output_root"]
        payload["argv"] = [
            "python",
            "-m",
            "weather.reporting.synthetic_experiment",
            "--output-root",
            output_root,
            "--mode",
            mode,
        ]
        if mode in {"attack", "read_attack"}:
            payload["argv"] += ["--attack-path", str(attack_path)]
        elif mode == "input_attack":
            payload["argv"] += ["--attack-path", str(payload["corpus"]["path"])]
        payload["resource_budget"] = {
            "timeout_seconds": timeout_seconds,
            "cpu_cores": 1,
            "memory_mb": 256,
            "io_read_mb": 64,
            "io_write_mb": io_write_mb,
        }
        payload["expected_artifacts"] = [
            {
                "role": "experiment_evidence",
                "path": f"{output_root}/evidence.json",
                "sha256": ARTIFACT_SHA256,
                "schema_version": ARTIFACT_SCHEMA,
            }
        ]

    return materialized_manifest(repo_root, payload_mutator=mutate)


def _write_queue(repo_root: Path, manifest: dict) -> Path:
    item = {
        "queue_id": manifest["queue_id"],
        "status": "queued",
        "eligible": True,
        "contract_status": "PASS",
        "materialization_status": "PASS",
        "contract_eligible": True,
        "materialized_executable": True,
        "command": list(manifest["argv"]),
        "argv": list(manifest["argv"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "candidate_output_root": manifest["candidate_output_root"],
        "experiment_manifest": manifest,
    }
    summary = {
        "queue_count": 1,
        "eligible_count": 1,
        "contract_eligible_count": 1,
        "materialized_executable_count": 1,
        "ineligible_count": 0,
        "blocked_count": 0,
        "verified_terminal_count": 0,
        "still_open_count": 1,
        **{f"{value}_count": 0 for value in sorted(TERMINAL_DISPOSITIONS)},
    }
    queue = finalize_self_hash(
        {
            "schema_version": "automatic_experiment_queue_v0.2",
            "status": "READY",
            "items": [item],
            "summary": summary,
        },
        hash_field="queue_sha256",
    )
    path = repo_root / "data" / "backtest" / "experiment_queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(queue, sort_keys=True), encoding="utf-8")
    return path


def _fixture(
    repo_root: Path,
    *,
    mode: str,
    timeout_seconds: int = 5,
    io_write_mb: float = 16,
):
    _write_worker(repo_root)
    manifest = _manifest(
        repo_root,
        mode=mode,
        timeout_seconds=timeout_seconds,
        io_write_mb=io_write_mb,
    )
    return manifest, _write_queue(repo_root, manifest)


def _legacy_staged_result_path(repo_root: Path) -> Path:
    candidate_output_root = Path(
        "artifacts/candidates/candidate-1/experiments/exp-1"
    )
    return (
        repo_root
        / candidate_output_root.parent
        / ".executor_runs"
        / ("0" * 16 + "-" + "0" * 32)
        / "workspace"
        / candidate_output_root
        / "experiment_result.json"
    )


def _formerly_failing_repo_root(tmp_path_factory, name: str) -> Path:
    base = tmp_path_factory.getbasetemp()
    root = base / name
    minimum_length = len(str(_legacy_staged_result_path(root)))
    if minimum_length < LEGACY_STAGED_RESULT_LENGTH:
        root = base / (name + "x" * (LEGACY_STAGED_RESULT_LENGTH - minimum_length))
    root.mkdir()
    assert len(str(_legacy_staged_result_path(root))) >= LEGACY_STAGED_RESULT_LENGTH
    return root


def _atomic_temp_shape(path: Path) -> Path:
    return path.with_name(path.name + ATOMIC_TEMP_SUFFIX)


@pytest.mark.parametrize(
    ("sample_count", "primary", "protected", "expected"),
    [
        (14, -0.02, 0.01, "resolved"),
        (14, 0.0, 0.01, "rejected"),
        (14, -0.02, 0.03, "regressed"),
        (13, -0.02, 0.01, "inconclusive"),
    ],
)
def test_predeclared_metrics_map_to_terminal_dispositions(
    sample_count,
    primary,
    protected,
    expected,
):
    manifest = build_experiment_manifest(valid_manifest_payload())
    observation = {
        "independent_sample_count": sample_count,
        "metrics": {
            "primary": {
                "name": "categorical_brier_delta",
                "value": primary,
            },
            "protected": [
                {"name": "worst_location_delta", "value": protected}
            ],
        },
    }

    assert _measured_disposition(manifest, observation) == expected


def test_host_admission_reserves_fifty_gib_plus_declared_writes(tmp_path):
    observed = {}

    def capture_admission(**kwargs):
        observed.update(kwargs)
        return _admit()

    budget = {
        "memory_mb": 256,
        "io_write_mb": 16,
    }
    proof = experiment_executor_module._host_admission(
        tmp_path,
        budget,
        now=QUIET_NOW,
        admission_builder=capture_admission,
        commit_percent_fn=lambda: 50.0,
    )

    expected = (50 * 1024**3) + (16 * 1024**2)
    assert observed["min_free_disk_bytes"] == expected
    assert proof["required_free_disk_bytes"] == expected


def test_executor_records_verified_terminal_disposition_and_declared_artifacts(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="success")

    result, result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "resolved"
    assert result["execution"]["candidate_output_committed"] is True
    assert result["execution"]["cpu_affinity"]["status"] == "PASS"
    assert result_path.is_file()
    artifact = tmp_path / manifest["expected_artifacts"][0]["path"]
    assert artifact.read_text(encoding="utf-8") == ARTIFACT_TEXT


def test_long_path_success_publishes_exact_hashed_result_without_temp(
    tmp_path_factory,
    monkeypatch,
):
    repo_root = _formerly_failing_repo_root(tmp_path_factory, "success-")
    legacy_staged_result = _legacy_staged_result_path(repo_root)
    manifest, queue_path = _fixture(repo_root, mode="success")
    observed_staged_results: list[Path] = []
    real_writer = experiment_executor_module.write_json_atomic

    def observe_staged_result(path, payload, **kwargs):
        observed_staged_results.append(Path(path))
        return real_writer(path, payload, **kwargs)

    monkeypatch.setattr(
        experiment_executor_module,
        "write_json_atomic",
        observe_staged_result,
    )

    result, result_path = _execute(queue_path, manifest, repo_root)

    expected_result = (
        repo_root / manifest["candidate_output_root"] / "experiment_result.json"
    )
    assert result_path == expected_result
    assert json.loads(result_path.read_text(encoding="utf-8")) == result
    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["execution"]["discarded_output_quarantine"] is None
    assert result["execution"]["terminal_commit"] == (
        "result_and_declared_artifacts_in_one_directory_rename"
    )
    assert len(str(legacy_staged_result)) >= LEGACY_STAGED_RESULT_LENGTH
    assert len(str(_atomic_temp_shape(legacy_staged_result))) >= 297
    assert len(observed_staged_results) == 1
    repaired_staged_result = observed_staged_results[0]
    assert len(str(repaired_staged_result)) == (
        len(str(legacy_staged_result)) - REPAIRED_STAGING_PATH_SAVINGS
    )
    assert len(str(_atomic_temp_shape(repaired_staged_result))) < 260
    scratch_root = repo_root / ".e"
    assert scratch_root.is_dir()
    assert not any(scratch_root.iterdir())
    assert scratch_root.stat().st_dev == result_path.stat().st_dev
    assert not list(repo_root.rglob("experiment_result.json.*.tmp"))
    claim_root = result_path.parent.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())


def test_long_path_failure_quarantines_and_publishes_only_terminal_result(
    tmp_path_factory,
):
    repo_root = _formerly_failing_repo_root(tmp_path_factory, "failure-")
    manifest, queue_path = _fixture(repo_root, mode="unexpected_directory")

    result, result_path = _execute(queue_path, manifest, repo_root)

    expected_result = (
        repo_root / manifest["candidate_output_root"] / "experiment_result.json"
    )
    assert result_path == expected_result
    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "untrusted_child_output"
    assert set(path.name for path in result_path.parent.iterdir()) == {
        "experiment_result.json"
    }
    scratch_root = repo_root / ".e"
    quarantine = Path(result["execution"]["discarded_output_quarantine"])
    assert quarantine.is_relative_to(scratch_root)
    assert (quarantine / "undeclared" / "nested").is_dir()
    assert not list(repo_root.rglob("experiment_result.json.*.tmp"))
    claim_root = result_path.parent.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())


def test_timeout_budget_kills_tree_and_records_unmeasured_inconclusive(tmp_path):
    manifest, queue_path = _fixture(
        tmp_path,
        mode="timeout",
        timeout_seconds=1,
    )

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "timeout_budget_exceeded"
    assert result["metrics"] == {}
    assert result["artifacts"] == []
    assert result["execution"]["termination"]["triggered"] is True
    assert not (tmp_path / manifest["expected_artifacts"][0]["path"]).exists()
    assert not (
        tmp_path / manifest["candidate_output_root"] / "partial-before-kill.txt"
    ).exists()
    contradictory = dict(result)
    contradictory.pop("result_sha256")
    contradictory["failure"] = {**result["failure"], "child_succeeded": True}
    with pytest.raises(ExperimentContractError, match="contradicts returncode"):
        build_experiment_result(contradictory, manifest=manifest)


def test_bounded_parent_capture_rejects_fast_noisy_child(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="noisy")

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "resource_budget_exceeded"
    assert result["execution"]["resource_limit_exceeded"]["resource"] == (
        "child_output_bytes"
    )
    assert len(result["execution"]["stdout_tail"].encode("utf-8")) <= 256 * 1024
    assert result["artifacts"] == []


def test_zero_exit_runner_error_records_honest_terminal_result(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="success")

    def quick_runner(_command, **kwargs):
        del kwargs
        return {
            "returncode": 0,
            "duration_seconds": 0.001,
            "stdout": "",
            "stderr": "",
            "runner_error": "working-set enforcement unavailable: no process-tree sample",
            "containment": {"status": "BLOCK"},
            "termination": {"triggered": False},
            "resource_peaks": {},
            "resource_io": {},
        }

    result, _result_path = execute_one(
        queue_path,
        manifest["queue_id"],
        repo_root=tmp_path,
        now=QUIET_NOW,
        runner=quick_runner,
        admission_builder=_admit,
        commit_percent_fn=lambda: 50.0,
    )

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"] == {
        "code": "containment_runner_error",
        "detail": "working-set enforcement unavailable: no process-tree sample",
        "child_succeeded": True,
    }


def test_zero_exit_resource_violation_records_truthful_child_status(
    tmp_path,
    monkeypatch,
):
    manifest, queue_path = _fixture(tmp_path, mode="success")
    monkeypatch.setattr(
        "weather.operations.experiment_executor._affinity_callback",
        lambda _cores: (lambda _started: None, {"status": "PASS"}),
    )

    def capped_runner(_command, **kwargs):
        del kwargs
        return {
            "returncode": 0,
            "duration_seconds": 0.001,
            "stdout": "",
            "stderr": "",
            "runner_error": None,
            "containment": {"status": "PASS"},
            "termination": {"triggered": False},
            "resource_limit_exceeded": {
                "resource": "child_output_bytes",
                "observed_bytes": 2,
                "limit_bytes": 1,
            },
            "resource_peaks": {},
            "resource_io": {},
        }

    result, _result_path = execute_one(
        queue_path,
        manifest["queue_id"],
        repo_root=tmp_path,
        now=QUIET_NOW,
        runner=capped_runner,
        admission_builder=_admit,
        commit_percent_fn=lambda: 50.0,
    )

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["failure"]["code"] == "resource_budget_exceeded"
    assert result["failure"]["child_succeeded"] is True


def test_nonempty_candidate_root_blocks_before_claim_or_execution(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="success")
    candidate_root = tmp_path / manifest["candidate_output_root"]
    (candidate_root / "operator-note.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(
        ExperimentExecutionError,
        match="candidate_output_root must be empty before the experiment is claimed",
    ):
        _execute(queue_path, manifest, tmp_path)

    assert (candidate_root / "operator-note.txt").read_text(encoding="utf-8") == "keep"
    claim_root = candidate_root.parent / ".executor_claims"
    assert not claim_root.exists() or not any(claim_root.iterdir())


def test_oversized_staged_input_is_rejected_before_copy(tmp_path, monkeypatch):
    source = tmp_path / "source.json"
    source.write_text("{}", encoding="utf-8")
    copied = False

    def forbidden_open(*_args, **_kwargs):
        nonlocal copied
        copied = True
        raise AssertionError("oversized input must not be opened for copying")

    monkeypatch.setattr(
        "weather.operations.experiment_executor.os.open",
        forbidden_open,
    )
    with pytest.raises(ExperimentExecutionError, match="before copy"):
        _copy_file(source, tmp_path / "target.json", max_bytes=1)

    assert copied is False
    assert not (tmp_path / "target.json").exists()


def test_staging_tree_entry_ceiling_blocks_single_pass_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for index in range(3):
        (source / f"entry-{index}.txt").write_text("bounded", encoding="utf-8")
    target = tmp_path / "target"

    with pytest.raises(ExperimentExecutionError, match="2-entry staging ceiling"):
        _copy_tree(
            source,
            target,
            max_bytes=1024,
            max_entries=2,
            max_depth=2,
            max_seconds=5,
        )

    assert target.is_dir()
    assert len(list(target.iterdir())) <= 2


def test_child_environment_does_not_inherit_host_secrets_or_unrelated_values(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("EXAMPLE_SECRET_TOKEN", "must-not-cross-boundary")
    monkeypatch.setenv("UNRELATED_HOST_VALUE", "must-not-cross-boundary")

    env = _child_environment(tmp_path, 1)

    assert "EXAMPLE_SECRET_TOKEN" not in env
    assert "UNRELATED_HOST_VALUE" not in env
    assert env["HOME"] == str(tmp_path / "home")
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["WEATHER_EXPERIMENT_ISOLATED"] == "1"


def test_unexpected_output_tree_is_quarantined_without_recursive_cleanup(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="unexpected_directory")

    result, result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "untrusted_child_output"
    quarantine = Path(result["execution"]["discarded_output_quarantine"])
    assert quarantine.is_dir()
    assert (quarantine / "undeclared" / "nested").is_dir()
    assert set(path.name for path in result_path.parent.iterdir()) == {
        "experiment_result.json"
    }


def test_sandbox_blocks_absolute_serving_mutation_and_original_hash_is_unchanged(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="attack")
    release_manifest = (
        tmp_path
        / "artifacts"
        / "releases"
        / manifest["release"]["release_id"]
        / "release_manifest.json"
    )
    before = hashlib.sha256(release_manifest.read_bytes()).hexdigest()

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "resolved"
    assert hashlib.sha256(release_manifest.read_bytes()).hexdigest() == before
    assert (
        result["execution"]["serving_fingerprint_before"]["sha256"]
        == result["execution"]["serving_fingerprint_after"]["sha256"]
    )


def test_sandbox_denies_undeclared_external_read_but_allows_verified_run(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="read_attack")

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "resolved"
    assert "UNDECLARED_READ_DENIED" in result["execution"]["stdout_tail"]
    read_policy = result["execution"]["staging_proof"]["read_policy"]
    assert read_policy["other_external_reads"] == "denied_by_python_audit_hook"
    assert read_policy["python_runtime_roots"]


def test_sandbox_denies_staged_input_mutation_and_parent_input_is_unchanged(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="input_attack")
    corpus_path = tmp_path / manifest["corpus"]["path"]
    before = hashlib.sha256(corpus_path.read_bytes()).hexdigest()

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "child_nonzero_exit"
    assert "outside writable roots" in result["failure"]["detail"]
    assert hashlib.sha256(corpus_path.read_bytes()).hexdigest() == before
    assert not (tmp_path / manifest["expected_artifacts"][0]["path"]).exists()
    write_policy = result["execution"]["staging_proof"]["write_policy"]
    assert write_policy["copied_source_release_and_inputs"] == (
        "read_only_by_python_audit_hook"
    )


def test_live_io_write_budget_kills_contained_experiment(tmp_path):
    manifest, queue_path = _fixture(
        tmp_path,
        mode="io_flood",
        timeout_seconds=5,
        io_write_mb=0.25,
    )

    result, _result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "resource_budget_exceeded"
    assert result["execution"]["resource_limit_exceeded"]["resource"] == (
        "io_write_bytes"
    )
    assert result["execution"]["termination"]["triggered"] is True
    assert result["execution"]["live_io_limits"]["write_max_bytes"] == 256 * 1024


def test_queue_change_before_commit_records_superseded_and_discards_output(tmp_path):
    manifest, queue_path = _fixture(tmp_path, mode="success")

    def superseding_runner(command, **kwargs):
        run = run_isolated_subprocess(command, **kwargs)
        summary = {
            "queue_count": 0,
            "eligible_count": 0,
            "contract_eligible_count": 0,
            "materialized_executable_count": 0,
            "ineligible_count": 0,
            "blocked_count": 0,
            "verified_terminal_count": 0,
            "still_open_count": 0,
            **{f"{value}_count": 0 for value in sorted(TERMINAL_DISPOSITIONS)},
        }
        queue = finalize_self_hash(
            {
                "schema_version": "automatic_experiment_queue_v0.2",
                "status": "EMPTY",
                "items": [],
                "summary": summary,
            },
            hash_field="queue_sha256",
        )
        queue_path.write_text(json.dumps(queue, sort_keys=True), encoding="utf-8")
        return run

    result, result_path = execute_one(
        queue_path,
        manifest["queue_id"],
        repo_root=tmp_path,
        now=QUIET_NOW,
        runner=superseding_runner,
        admission_builder=_admit,
        commit_percent_fn=lambda: 50.0,
    )

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "superseded"
    assert result["artifacts"] == []
    assert result_path.is_file()
    assert not (tmp_path / manifest["expected_artifacts"][0]["path"]).exists()


def test_final_serving_fingerprint_failure_terminalizes_and_releases_claim(
    tmp_path,
    monkeypatch,
):
    manifest, queue_path = _fixture(tmp_path, mode="success")
    original_fingerprint = experiment_executor_module._tree_fingerprint
    protected_fingerprint_calls = 0

    def fail_final_fingerprint(paths, *, repo_root):
        nonlocal protected_fingerprint_calls
        is_protected_parent_tree = (
            Path(repo_root) == tmp_path
            and any(Path(path).name == "current_release.json" for path in paths)
        )
        if is_protected_parent_tree:
            protected_fingerprint_calls += 1
            if protected_fingerprint_calls == 3:
                raise ExperimentExecutionError("synthetic final fingerprint failure")
        return original_fingerprint(paths, repo_root=repo_root)

    monkeypatch.setattr(
        experiment_executor_module,
        "_tree_fingerprint",
        fail_final_fingerprint,
    )

    result, result_path = _execute(queue_path, manifest, tmp_path)

    assert verify_experiment_result(result, manifest=manifest) == result
    assert result["disposition"] == "inconclusive"
    assert result["failure"]["code"] == "serving_fingerprint_failed"
    assert result["execution"]["serving_fingerprint_after"]["status"] == "BLOCK"
    assert result_path.is_file()
    claim_root = result_path.parent.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())
    quarantine = Path(result["execution"]["discarded_output_quarantine"])
    assert quarantine.is_dir()


def test_initial_serving_fingerprint_failure_blocks_before_claim(
    tmp_path,
    monkeypatch,
):
    manifest, queue_path = _fixture(tmp_path, mode="success")
    original_fingerprint = experiment_executor_module._tree_fingerprint

    def fail_initial_fingerprint(paths, *, repo_root):
        is_protected_parent_tree = (
            Path(repo_root) == tmp_path
            and any(Path(path).name == "current_release.json" for path in paths)
        )
        if is_protected_parent_tree:
            raise ExperimentExecutionError("synthetic initial fingerprint failure")
        return original_fingerprint(paths, repo_root=repo_root)

    monkeypatch.setattr(
        experiment_executor_module,
        "_tree_fingerprint",
        fail_initial_fingerprint,
    )

    with pytest.raises(
        ExperimentExecutionError,
        match="synthetic initial fingerprint failure",
    ):
        _execute(queue_path, manifest, tmp_path)

    candidate_root = tmp_path / manifest["candidate_output_root"]
    assert not any(candidate_root.iterdir())
    claim_root = candidate_root.parent / ".executor_claims"
    assert not claim_root.exists() or not any(claim_root.iterdir())
    scratch_root = tmp_path / ".e"
    assert not scratch_root.exists()


def test_claim_write_failure_removes_partial_claim_and_empty_run_root(
    tmp_path,
    monkeypatch,
):
    manifest, queue_path = _fixture(tmp_path, mode="success")

    def fail_claim_write(_descriptor, _payload):
        raise OSError("synthetic claim write failure")

    monkeypatch.setattr(experiment_executor_module.os, "write", fail_claim_write)

    with pytest.raises(OSError, match="synthetic claim write failure"):
        _execute(queue_path, manifest, tmp_path)

    candidate_root = tmp_path / manifest["candidate_output_root"]
    assert not any(candidate_root.iterdir())
    claim_root = candidate_root.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())
    scratch_root = tmp_path / ".e"
    assert scratch_root.is_dir()
    assert not any(scratch_root.iterdir())


def test_terminal_write_interruption_releases_claim_and_preserves_scratch(
    tmp_path,
    monkeypatch,
):
    manifest, queue_path = _fixture(tmp_path, mode="success")

    def interrupt_terminal_write(*_args, **_kwargs):
        raise OSError("synthetic terminal persistence interruption")

    monkeypatch.setattr(
        experiment_executor_module,
        "write_json_atomic",
        interrupt_terminal_write,
    )

    with pytest.raises(OSError, match="terminal persistence interruption"):
        _execute(queue_path, manifest, tmp_path)

    candidate_root = tmp_path / manifest["candidate_output_root"]
    claim_root = candidate_root.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())
    scratch_root = tmp_path / ".e"
    assert scratch_root.is_dir()
    assert any(scratch_root.iterdir())
    assert not any(candidate_root.iterdir())


def test_long_path_atomic_write_interruption_releases_claim_without_orphan_temp(
    tmp_path_factory,
    monkeypatch,
):
    repo_root = _formerly_failing_repo_root(tmp_path_factory, "interruption-")
    manifest, queue_path = _fixture(repo_root, mode="success")
    path_type = type(repo_root)
    real_replace = path_type.replace

    def interrupt_result_replace(self, target):
        if self.name.startswith("experiment_result.json.") and self.name.endswith(
            ".tmp"
        ):
            raise OSError("synthetic atomic result replace interruption")
        return real_replace(self, target)

    monkeypatch.setattr(path_type, "replace", interrupt_result_replace)

    with pytest.raises(OSError, match="atomic result replace interruption"):
        _execute(queue_path, manifest, repo_root)

    candidate_root = repo_root / manifest["candidate_output_root"]
    assert not any(candidate_root.iterdir())
    claim_root = candidate_root.parent / ".executor_claims"
    assert claim_root.is_dir()
    assert not any(claim_root.iterdir())
    scratch_root = repo_root / ".e"
    assert scratch_root.is_dir()
    assert any(scratch_root.iterdir())
    assert not list(repo_root.rglob("experiment_result.json.*.tmp"))
