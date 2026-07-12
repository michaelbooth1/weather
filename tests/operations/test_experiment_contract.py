from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from weather.experiment_contract import (
    ExperimentContractError,
    build_experiment_manifest,
    build_experiment_result,
    finalize_self_hash,
    verify_automatic_experiment_queue,
    verify_experiment_manifest,
    verify_experiment_result,
    verify_materialized_experiment_manifest,
)


def valid_manifest_payload():
    output_root = "artifacts/candidates/candidate-1/experiments/exp-1"
    return {
        "queue_id": "exp-1",
        "candidate_id": "candidate-1",
        "created_at_utc": "2026-07-11T12:00:00+00:00",
        "owner": "model-research",
        "hypothesis": "regularized residual calibration lowers equal-market-day Brier",
        "terminal_dispositions": [
            "inconclusive",
            "regressed",
            "rejected",
            "resolved",
            "superseded",
        ],
        "argv": [
            "python",
            "-m",
            "weather.reporting.research.exact_band_distance_zero_calibration",
            "--output-root",
            output_root,
        ],
        "candidate_output_root": output_root,
        "release": {"release_id": "release-1", "manifest_sha256": "1" * 64},
        "corpus": {
            "path": "data/analysis/point_in_time/corpus.parquet",
            "sha256": "2" * 64,
            "schema_version": "point_in_time_analytical_contract_v0.1",
        },
        "inputs": [
            {
                "role": "validation_plan",
                "path": "data/backtest/point_in_time_validation_plan.json",
                "sha256": "3" * 64,
                "schema_version": "point_in_time_validation_plan_v0.1",
            }
        ],
        "primary_metric": {
            "name": "categorical_brier_delta",
            "direction": "minimize",
            "aggregation": "equal_market_day",
        },
        "protected_metrics": [
            {"name": "worst_location_delta", "operator": "<=", "threshold": 0.02}
        ],
        "minimum_independent_sample": {"unit": "fleet_target_date", "count": 14},
        "decision_rule": {
            "rule": "primary improves while protected location regression stays bounded",
            "metric": "categorical_brier_delta",
            "operator": "<=",
            "threshold": -0.01,
        },
        "expected_artifacts": [
            {
                "role": "experiment_result",
                "path": f"{output_root}/result.json",
                "sha256": "4" * 64,
                "schema_version": "executable_experiment_result_v0.1",
            }
        ],
        "resource_budget": {
            "timeout_seconds": 600,
            "cpu_cores": 2,
            "memory_mb": 2048,
            "io_read_mb": 1024,
            "io_write_mb": 256,
        },
    }


def valid_result_payload(manifest, *, disposition="resolved"):
    return {
        "result_id": "result-1",
        "queue_id": manifest["queue_id"],
        "manifest_sha256": manifest["manifest_sha256"],
        "started_at_utc": "2026-07-11T12:01:00+00:00",
        "finished_at_utc": "2026-07-11T12:02:00+00:00",
        "returncode": 0,
        "disposition": disposition,
        "disposition_reason": "predeclared primary and protected rules evaluated",
        "independent_sample_count": 14,
        "metrics": {
            "primary": {"name": "categorical_brier_delta", "value": -0.02},
            "protected": [{"name": "worst_location_delta", "value": 0.01}],
        },
        "artifacts": deepcopy(manifest["expected_artifacts"]),
        "resource_usage": {
            "duration_seconds": 60,
            "cpu_seconds": 100,
            "peak_memory_mb": 512,
            "io_read_mb": 100,
            "io_write_mb": 10,
        },
    }


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def materialized_manifest(repo_root, *, payload_mutator=None):
    root = Path(repo_root)
    payload = valid_manifest_payload()
    corpus = root / payload["corpus"]["path"]
    corpus.parent.mkdir(parents=True, exist_ok=True)
    corpus.write_bytes(b"bounded point-in-time parquet fixture")
    payload["corpus"]["sha256"] = _sha256(corpus)

    input_row = payload["inputs"][0]
    input_path = root / input_row["path"]
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(
        json.dumps(
            {
                "schema_version": input_row["schema_version"],
                "status": "PASS",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    input_row["sha256"] = _sha256(input_path)

    release_path = (
        root
        / "artifacts"
        / "releases"
        / payload["release"]["release_id"]
        / "release_manifest.json"
    )
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release = finalize_self_hash(
        {
            "schema_version": "release_manifest_v0.1",
            "release_id": payload["release"]["release_id"],
            "state": "IMMUTABLE_CANDIDATE",
        },
        hash_field="manifest_sha256",
    )
    release_path.write_text(json.dumps(release, sort_keys=True), encoding="utf-8")
    payload["release"]["manifest_sha256"] = release["manifest_sha256"]

    (root / payload["candidate_output_root"]).mkdir(parents=True, exist_ok=True)
    if payload_mutator is not None:
        payload_mutator(payload, root)
    return build_experiment_manifest(payload)


def test_manifest_is_self_hashed_and_exactly_verifiable():
    manifest = build_experiment_manifest(valid_manifest_payload())

    assert verify_experiment_manifest(manifest) == manifest
    assert len(manifest["manifest_sha256"]) == 64


@pytest.mark.parametrize(
    "mutation, match",
    [
        (lambda row: row.update(argv="python -m unsafe"), "argv must be"),
        (lambda row: row.update(candidate_output_root="artifacts/models/active"), "candidate_output_root"),
        (lambda row: row["corpus"].update(sha256="unknown"), "lowercase SHA-256"),
        (lambda row: row["inputs"].clear(), "inputs must be a non-empty list"),
    ],
)
def test_manifest_rejects_shell_strings_active_outputs_and_missing_immutable_inputs(
    mutation, match
):
    payload = valid_manifest_payload()
    mutation(payload)

    with pytest.raises(ExperimentContractError, match=match):
        build_experiment_manifest(payload)


def test_manifest_and_result_tampering_fail_closed():
    manifest = build_experiment_manifest(valid_manifest_payload())
    tampered_manifest = deepcopy(manifest)
    tampered_manifest["owner"] = "attacker"
    with pytest.raises(ExperimentContractError, match="manifest_sha256"):
        verify_experiment_manifest(tampered_manifest)

    result = build_experiment_result(valid_result_payload(manifest), manifest=manifest)
    assert verify_experiment_result(result, manifest=manifest) == result
    tampered_result = deepcopy(result)
    tampered_result["disposition_reason"] = "changed"
    with pytest.raises(ExperimentContractError, match="result_sha256"):
        verify_experiment_result(tampered_result, manifest=manifest)


def test_result_disposition_must_match_metrics_sample_and_budget():
    manifest = build_experiment_manifest(valid_manifest_payload())
    contradictory = valid_result_payload(manifest, disposition="rejected")

    with pytest.raises(ExperimentContractError, match="contradicts"):
        build_experiment_result(contradictory, manifest=manifest)


def test_materialized_manifest_verifies_release_inputs_hashes_command_and_absent_outputs(
    tmp_path,
):
    manifest = materialized_manifest(tmp_path)

    assert verify_materialized_experiment_manifest(
        manifest,
        repo_root=tmp_path,
    ) == manifest


@pytest.mark.parametrize(
    "mutation, match",
    [
        (
            lambda payload, _root: payload.update(
                argv=[
                    "python",
                    "-c",
                    "open('artifacts/models/active.pkl','wb').write(b'x')",
                    "--output-root",
                    payload["candidate_output_root"],
                ]
            ),
            "Python -c",
        ),
        (
            lambda payload, _root: payload.update(
                argv=[
                    "python",
                    "-m",
                    "foreign.experiment",
                    "--output-root",
                    payload["candidate_output_root"],
                ]
            ),
            "weather",
        ),
        (
            lambda payload, _root: payload.update(
                argv=[
                    "python",
                    "-m",
                    "weather.safe_but_unbound",
                    payload["candidate_output_root"],
                ]
            ),
            "--output-root",
        ),
    ],
)
def test_materialized_manifest_rejects_unsafe_or_unbound_commands(
    tmp_path,
    mutation,
    match,
):
    manifest = materialized_manifest(tmp_path, payload_mutator=mutation)

    with pytest.raises(ExperimentContractError, match=match):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)


def test_materialized_manifest_rejects_missing_or_tampered_inputs(tmp_path):
    manifest = materialized_manifest(tmp_path)
    corpus = tmp_path / manifest["corpus"]["path"]
    corpus.write_bytes(b"tampered after manifest creation")

    with pytest.raises(ExperimentContractError, match="materialized bytes"):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)

    corpus.unlink()
    with pytest.raises(ExperimentContractError, match="does not resolve"):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)


def test_materialized_manifest_rejects_json_schema_and_release_identity_mismatch(
    tmp_path,
):
    def wrong_schema(payload, root):
        path = root / payload["inputs"][0]["path"]
        path.write_text(
            json.dumps({"schema_version": "active_release_pointer_v0.1"}),
            encoding="utf-8",
        )
        payload["inputs"][0]["sha256"] = _sha256(path)

    manifest = materialized_manifest(tmp_path, payload_mutator=wrong_schema)
    with pytest.raises(ExperimentContractError, match="embedded schema_version"):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)

    clean_root = tmp_path / "release-mismatch"
    clean = materialized_manifest(clean_root)
    release_path = (
        clean_root
        / "artifacts"
        / "releases"
        / clean["release"]["release_id"]
        / "release_manifest.json"
    )
    release = json.loads(release_path.read_text(encoding="utf-8"))
    release["release_id"] = "different-release"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    with pytest.raises(ExperimentContractError, match="release_id disagree"):
        verify_materialized_experiment_manifest(clean, repo_root=clean_root)


def test_materialized_manifest_rejects_existing_expected_output(tmp_path):
    manifest = materialized_manifest(tmp_path)
    output = tmp_path / manifest["expected_artifacts"][0]["path"]
    output.write_text("pre-existing output", encoding="utf-8")

    with pytest.raises(ExperimentContractError, match="already exists"):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)


def test_materialized_manifest_rejects_candidate_root_symlink(tmp_path):
    manifest = materialized_manifest(tmp_path)
    output = tmp_path / manifest["candidate_output_root"]
    outside = tmp_path / "outside"
    outside.mkdir()
    output.rmdir()
    try:
        os.symlink(outside, output, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks are unavailable on this host")

    with pytest.raises(ExperimentContractError, match="symlink"):
        verify_materialized_experiment_manifest(manifest, repo_root=tmp_path)
