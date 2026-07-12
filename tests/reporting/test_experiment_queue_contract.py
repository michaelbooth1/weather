import pytest

from tests.operations.test_experiment_contract import (
    materialized_manifest,
    valid_manifest_payload,
    valid_result_payload,
)
from weather.experiment_contract import (
    ExperimentContractError,
    build_experiment_manifest,
    build_experiment_result,
    finalize_self_hash,
    verify_automatic_experiment_queue,
    verify_self_hash,
)
from weather.reporting.daily.daily_learning_scorecard import (
    _build_experiment_queue,
    _queue_item_from_learning,
)


def _learning(manifest=None, *, queue_id=None):
    evidence = {
        "queue_id": queue_id,
        "slice": "settlement_distance=0",
        "experiment_command": ["python", "-m", "legacy.inferred_or_unfrozen"],
    }
    if manifest is not None:
        evidence["experiment_manifest"] = manifest
    return {
        "source": "test",
        "category": "experiment",
        "priority": "P1",
        "retrain_input": True,
        "hypothesis": "legacy hypothesis",
        "evidence": evidence,
    }


def test_legacy_queue_item_remains_visible_but_cannot_execute():
    item = _queue_item_from_learning(
        _learning(queue_id="legacy-1"),
        0,
        generated_at_utc="2026-07-11T12:00:00+00:00",
    )

    assert item["queue_id"] == "legacy-1"
    assert item["status"] == "ineligible_incomplete_contract"
    assert item["eligible"] is False
    assert item["contract_status"] == "BLOCK"
    assert item["command"] == []
    assert item["legacy"]["command"] == ["python", "-m", "legacy.inferred_or_unfrozen"]


def test_structural_manifest_is_not_materialized_or_executable_without_repo_root():
    manifest = build_experiment_manifest(valid_manifest_payload())
    queue = _build_experiment_queue(
        [_learning(manifest), _learning(queue_id="legacy-1")],
        {},
        {},
        generated_at_utc="2026-07-11T12:00:00+00:00",
        run_date="2026-07-11",
    )

    verify_self_hash(queue, hash_field="queue_sha256")
    by_id = {item["queue_id"]: item for item in queue["items"]}
    assert queue["schema_version"] == "automatic_experiment_queue_v0.2"
    assert queue["summary"]["contract_eligible_count"] == 1
    assert queue["summary"]["eligible_count"] == 0
    assert by_id["exp-1"]["contract_status"] == "PASS"
    assert by_id["exp-1"]["eligible"] is False
    assert by_id["exp-1"]["command"] == []
    assert by_id["exp-1"]["manifest_argv"] == manifest["argv"]
    assert by_id["exp-1"]["materialization_blockers"]
    assert by_id["legacy-1"]["eligible"] is False
    assert queue["eligibility_contract"]["commands_or_hashes_inferred"] is False
    assert queue["eligibility_contract"]["operational_execution_claimed"] is False


def test_materialized_manifest_is_the_only_eligible_queue_item(tmp_path):
    manifest = materialized_manifest(tmp_path)
    queue = _build_experiment_queue(
        [_learning(manifest), _learning(queue_id="legacy-1")],
        {},
        {},
        generated_at_utc="2026-07-11T12:00:00+00:00",
        run_date="2026-07-11",
        repo_root=tmp_path,
    )

    assert verify_automatic_experiment_queue(queue, repo_root=tmp_path) == queue
    by_id = {item["queue_id"]: item for item in queue["items"]}
    assert queue["summary"]["eligible_count"] == 1
    assert queue["summary"]["still_open_count"] == 1
    assert queue["summary"]["blocked_count"] == 1
    assert by_id["exp-1"]["eligible"] is True
    assert by_id["exp-1"]["command"] == manifest["argv"]
    assert by_id["exp-1"]["materialization_status"] == "PASS"


def test_verified_terminal_result_is_consumed_into_queue_metrics(tmp_path):
    manifest = materialized_manifest(tmp_path)
    result = build_experiment_result(valid_result_payload(manifest), manifest=manifest)
    queue = _build_experiment_queue(
        [_learning(manifest)],
        {"experiment_queue_results": {"results": [result]}},
        {},
        generated_at_utc="2026-07-11T13:00:00+00:00",
        run_date="2026-07-11",
        repo_root=tmp_path,
    )

    item = queue["items"][0]
    assert item["status"] == "resolved"
    assert item["eligible"] is False
    assert item["last_result"]["contract_status"] == "PASS"
    assert queue["summary"]["resolved_count"] == 1
    assert queue["summary"]["verified_terminal_count"] == 1
    assert queue["summary"]["still_open_count"] == 0
    assert queue["summary"]["blocked_count"] == 0


def test_invalid_result_never_surfaces_claimed_scientific_status(tmp_path):
    manifest = materialized_manifest(tmp_path)
    invalid = {
        "queue_id": manifest["queue_id"],
        "status": "executed",
        "resolution_status": "resolved",
        "disposition": "regressed",
        "returncode": 0,
    }
    queue = _build_experiment_queue(
        [_learning(manifest)],
        {"experiment_queue_results": {"results": [invalid]}},
        {},
        generated_at_utc="2026-07-11T13:00:00+00:00",
        run_date="2026-07-11",
        repo_root=tmp_path,
    )

    item = queue["items"][0]
    assert item["status"] == "ineligible_invalid_result"
    assert item["status"] not in {"resolved", "regressed", "rejected"}
    assert item["last_result"]["claimed_resolution_status"] == "resolved"
    assert item["last_result"]["claimed_disposition"] == "regressed"
    assert queue["summary"]["verified_terminal_count"] == 0
    assert queue["summary"]["blocked_count"] == 1


def test_duplicate_queue_or_result_ids_are_rejected(tmp_path):
    manifest = materialized_manifest(tmp_path)
    with pytest.raises(ExperimentContractError, match="duplicate experiment queue_id"):
        _build_experiment_queue(
            [_learning(manifest), _learning(manifest)],
            {},
            {},
            generated_at_utc="2026-07-11T13:00:00+00:00",
            repo_root=tmp_path,
        )

    result = build_experiment_result(valid_result_payload(manifest), manifest=manifest)
    with pytest.raises(ExperimentContractError, match="duplicate experiment result"):
        _build_experiment_queue(
            [_learning(manifest)],
            {"experiment_queue_results": {"results": [result, result]}},
            {},
            generated_at_utc="2026-07-11T13:00:00+00:00",
            repo_root=tmp_path,
        )


def test_queue_verifier_rejects_self_consistent_semantic_tampering(tmp_path):
    manifest = materialized_manifest(tmp_path)
    queue = _build_experiment_queue(
        [_learning(manifest)],
        {},
        {},
        generated_at_utc="2026-07-11T13:00:00+00:00",
        repo_root=tmp_path,
    )

    command_tamper = finalize_self_hash(queue, hash_field="queue_sha256")
    command_tamper["items"][0]["command"] = ["python", "-c", "print('tampered')"]
    command_tamper = finalize_self_hash(command_tamper, hash_field="queue_sha256")
    with pytest.raises(ExperimentContractError, match="command/argv"):
        verify_automatic_experiment_queue(command_tamper, repo_root=tmp_path)

    ineligible_tamper = finalize_self_hash(queue, hash_field="queue_sha256")
    ineligible_tamper["items"][0]["eligible"] = False
    ineligible_tamper = finalize_self_hash(ineligible_tamper, hash_field="queue_sha256")
    with pytest.raises(ExperimentContractError, match="ineligible.*command"):
        verify_automatic_experiment_queue(ineligible_tamper, repo_root=tmp_path)

    duplicate_tamper = finalize_self_hash(queue, hash_field="queue_sha256")
    duplicate_tamper["items"].append(dict(duplicate_tamper["items"][0]))
    duplicate_tamper["summary"]["queue_count"] = 2
    duplicate_tamper = finalize_self_hash(duplicate_tamper, hash_field="queue_sha256")
    with pytest.raises(ExperimentContractError, match="duplicate experiment queue_id"):
        verify_automatic_experiment_queue(duplicate_tamper, repo_root=tmp_path)
