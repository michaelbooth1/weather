"""Typed attempt parsing cannot reinterpret host evidence as a full suite."""

from copy import deepcopy

import pytest

from weather.operations.qualification import attempt, records
from test_qualification_evidence import NOW, SOURCE, bundle


@pytest.fixture
def split_attempt(bundle, tmp_path):
    root = tmp_path / "attempt"
    root.mkdir()
    for name in ("control", "production", "candidate"):
        (root / name).mkdir()
    # Candidate must be outside the evidence namespace in an actual attempt.
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    production = tmp_path / "production"
    production.mkdir()
    placeholder = records.publish(root, "placeholder.json", {"test_only": True})
    config = records.publish(root, "configuration.json", {
        "schema": "qualification_configuration_v2", "source": SOURCE["commit"], "baseline": SOURCE["baseline"],
        "generated": [{"path": path, "payload": placeholder, "git_blob": "f" * 40,
                       "generation": {"device": "1", "file_id": str(index), "size": placeholder["size"], "mtime_ns": 1, "ctime_ns": 1}}
                      for index, path in enumerate(("config/location_market_events.json", "config/locations.json"))],
        "dependencies": placeholder})
    control = records.publish(root, "control-closure.json", {"baseline": SOURCE["baseline"]})
    plan = {"schema": "qualification_host_plan_v2", "source": SOURCE, "scope": "control_plane",
        "host_id": "1" * 64, "principal_id": "2" * 64, "not_before": "2026-09-15T04:30:00Z",
        "deadline": "2026-09-15T05:02:00Z", "local_day": "2026-09-15",
        "phase_seconds": {"probes": 480, "audit": 1200, "metadata": 120, "teardown": 120},
        "measurements": placeholder, "configuration": config, "environment": placeholder, "audit": None, "probes": placeholder}
    plan_ref = records.publish(root, "host-plan.json", plan)
    manifest = {"schema": "weather_integration_attempt_manifest_v2", "qualification_mode": "split_v2",
        "attempt_id": "fixture", "created_at_local": "2026-09-14T09:00:00-04:00", "attempt_root": str(root),
        "repo_root": str(production), "worktree_root": str(candidate), "branch_ref": "codex/fixture",
        "expected_tip": SOURCE["commit"], "baseline": {"master": SOURCE["baseline"], "origin_master": SOURCE["baseline"]},
        "authorization": {"review_reference": "fixture review", "repair_class": "initial", "repair_of": None},
        "schedule": {"host_at_local": "2026-09-15T00:30:00-04:00", "merge_at_local": "2026-09-15T01:05:00-04:00",
                     "host_task_name": "WeatherIntegrationHost_fixture", "merge_task_name": "WeatherIntegrationMerge_fixture"},
        "orchestration": {key: {"path": str(root / "control/scripts/ops" / (name + ".ps1")), "sha256": "3" * 64}
                          for key, name in (("attempt_host", "integration_attempt_host"), ("attempt_merge", "integration_attempt_merge"),
                                            ("quiet_merge", "quiet_window_merge"), ("contract", "integration_attempt_contract"))},
        "evidence": {key: str(root / name) for key, name in attempt.EVIDENCE.items()},
        "qualification": {"root": str(bundle.root), "policy": bundle.refs["policy"], "review": bundle.refs["review"],
                          "certificate": bundle.refs["certificate"], "import": placeholder, "revocations": placeholder},
        "control": {"root": str(root / "control"), "closure": control}, "host": plan_ref}
    return root, manifest, plan


def test_typed_manifest_parsing_is_not_registration_or_integration_authority(split_attempt):
    root, value, _ = split_attempt
    checked = attempt.manifest(value, actual_root=root, now=NOW)
    assert checked["registration_eligible"] is False and checked["integration_eligible"] is False
    assert checked["host_plan"]["scope"] == "control_plane"
    assert "suite_receipt" not in checked["manifest"]["evidence"]


@pytest.mark.parametrize("mutation", ["legacy-schema", "fake-suite", "old-suite-receipt", "other-source", "other-baseline",
                                      "wrong-task", "late-host", "short-gap", "escaped-evidence", "candidate-control", "unclaimed-retry"])
def test_split_manifest_rejects_legacy_aliases_and_unbound_attempts(split_attempt, mutation):
    root, original, _ = split_attempt
    value = deepcopy(original)
    if mutation == "legacy-schema":
        value["schema"] = "weather_integration_attempt_manifest_v1"
    elif mutation == "fake-suite":
        value["suite"] = {"status": "PASS"}
    elif mutation == "old-suite-receipt":
        value["evidence"]["suite_receipt"] = str(root / "suite-receipt.json")
    elif mutation == "other-source":
        value["expected_tip"] = "f" * 40
    elif mutation == "other-baseline":
        value["baseline"]["origin_master"] = "f" * 40
    elif mutation == "wrong-task":
        value["schedule"]["host_task_name"] += "_other"
    elif mutation == "late-host":
        value["schedule"]["host_at_local"] = "2026-09-15T12:30:00-04:00"
    elif mutation == "short-gap":
        value["schedule"]["merge_at_local"] = "2026-09-15T01:00:00-04:00"
    elif mutation == "escaped-evidence":
        value["evidence"]["host_receipt"] = str(root.parent / "host-receipt.json")
    elif mutation == "candidate-control":
        value["control"]["root"] = value["worktree_root"]
    else:
        value["authorization"]["repair_class"] = "retry_unchanged"
    with pytest.raises(ValueError):
        attempt.manifest(value, actual_root=root, now=NOW)


@pytest.mark.parametrize("mutation", ["scope", "day", "budget", "deadline", "invented-current-audit"])
def test_host_plan_changes_do_not_inherit_the_original_attempt(split_attempt, mutation):
    root, value, plan = split_attempt
    changed = deepcopy(plan)
    if mutation == "scope":
        changed["scope"] = "reliability_current_inputs"
    elif mutation == "day":
        changed["local_day"] = "2026-09-16"
    elif mutation == "budget":
        changed["phase_seconds"]["audit"] = 1201
    elif mutation == "deadline":
        changed["deadline"] = "2026-09-15T08:00:00Z"
    else:
        changed["audit"] = changed["probes"]
    value["host"] = records.publish(root, mutation + ".json", changed)
    with pytest.raises(ValueError):
        attempt.manifest(value, actual_root=root, now=NOW)
