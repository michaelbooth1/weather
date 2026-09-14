"""Actual host-consumer gates reject unknown measurements and forged cleanup."""

from copy import deepcopy

import pytest

from weather.operations.qualification import attempt, host_acceptance, records
from weather.operations.qualification.contracts import Graph
from test_qualification_attempt import split_attempt
from test_qualification_evidence import NOW, bundle


def native():
    return {"completed": True, "failure": None, "exit_code": 0, "teardown_proved": True, "elapsed_ms": 1000,
        "peak_private_bytes": 32 * 1024**2, "peak_working_set_bytes": 32 * 1024**2,
        "native_peak_commit_bytes": 32 * 1024**2, "system_commit_basis_points": 4500,
        "minimum_disk_bytes": 60 * 1024**3, "maximum_sample_gap_ms": 100, "resource_samples": 10}


@pytest.fixture
def measured(split_attempt):
    root, m, plan = split_attempt
    checked = attempt.manifest(m, actual_root=root, now=NOW)
    phases = {}
    for name in host_acceptance.PHASES:
        proof = records.publish(root, name + "-measurement.json", native())
        phases[name] = {"maximum": {"seconds": plan["phase_seconds"][name], "commit_bytes": 512 * 1024**2,
            "working_set_bytes": 512 * 1024**2, "scratch_bytes": 1024**2, "read_bytes": 1024**2},
            "samples": [{"kind": "synthetic", "proof": proof, "scratch_bytes": 256, "read_bytes": 256, "cpu_ms": 100}]}
    value = {"schema": "qualification_host_measurement_v2", **{key: plan[key] for key in ("source", "scope", "host_id", "principal_id")},
        "environment_sha256": plan["environment"]["sha256"], "configuration_sha256": plan["configuration"]["sha256"],
        "reviewer": "deterministic test fixture", "reviewed_at": NOW.isoformat().replace("+00:00", "Z"),
        "phases": phases, "current_inputs": None}
    return root, checked, plan, value


def test_complete_native_measurements_have_no_standalone_host_authority(measured):
    root, checked, plan, value = measured
    ref = records.publish(root, "measurements.json", value)
    result = host_acceptance.measurements(Graph(root), ref, policy=checked["policy"], host_plan=plan, now=NOW)
    assert result["scope"] == "control_plane"
    assert "integration_eligible" not in result


@pytest.mark.parametrize("failure", ["no-samples", "other-source", "unknown-host", "changed-environment", "future-review",
                                     "no-current-measurement", "overlong", "over-memory", "over-scratch", "partial-teardown",
                                     "lost-monitor", "capture-pressure", "low-disk", "boolean-exit", "native-failure"])
def test_measurement_refusals_reach_actual_consumer(measured, failure):
    root, checked, original_plan, original = measured
    plan, value = deepcopy(original_plan), deepcopy(original)
    if failure == "no-samples":
        value["phases"]["probes"]["samples"] = []
    elif failure == "other-source":
        value["source"]["commit"] = "f" * 40
    elif failure == "unknown-host":
        value["host_id"] = "f" * 64
    elif failure == "changed-environment":
        value["environment_sha256"] = "f" * 64
    elif failure == "future-review":
        value["reviewed_at"] = "2099-01-01T00:00:00Z"
    elif failure == "no-current-measurement":
        value["scope"] = plan["scope"] = "reliability_current_inputs"
    elif failure == "overlong":
        value["phases"]["probes"]["maximum"]["seconds"] = 481
    elif failure == "over-memory":
        value["phases"]["probes"]["maximum"]["commit_bytes"] += 1
    elif failure == "over-scratch":
        value["phases"]["probes"]["samples"][0]["scratch_bytes"] = 2 * 1024**2
    else:
        changed = native()
        key, replacement = {
            "partial-teardown": ("teardown_proved", False), "lost-monitor": ("maximum_sample_gap_ms", 1001),
            "capture-pressure": ("system_commit_basis_points", 6601), "low-disk": ("minimum_disk_bytes", 49 * 1024**3),
            "boolean-exit": ("exit_code", False), "native-failure": ("completed", False),
        }[failure]
        changed[key] = replacement
        value["phases"]["probes"]["samples"][0]["proof"] = records.publish(root, "failed-native.json", changed)
    ref = records.publish(root, "changed-measurements.json", value)
    with pytest.raises((ValueError, KeyError)):
        host_acceptance.measurements(Graph(root), ref, policy=checked["policy"], host_plan=plan, now=NOW)


def test_real_s4u_record_requires_batch_token_and_native_engine_lineage(split_attempt):
    _, m, plan = split_attempt
    value = {"schema": "qualification_s4u_invocation_v2", "role": "host", "host_id": plan["host_id"],
        "principal_id": plan["principal_id"], "task_name": m["schedule"]["host_task_name"],
        "registration_receipt_sha256": "a" * 64, "registration_intent_sha256": "b" * 64,
        "token": {"pid": 100, "creation_utc_ticks": 200, "image": "C:/Windows/powershell.exe", "sid": "S-1-5-21-1",
                  "authentication_id": "0000000000000001", "logon_type": 4, "token_type": 1, "session": 0, "elevated": False},
        "ancestry": [{"pid": 100, "creation_utc_ticks": 200}, {"pid": 99, "creation_utc_ticks": 100}],
        "engine_pid": 99, "instance_guid": "00112233-4455-6677-8899-aabbccddeeff"}
    arguments = dict(host_plan=plan, manifest=m, registration_sha256="a" * 64, intent_sha256="b" * 64)
    assert host_acceptance.invocation(value, **arguments) == value
    for key, replacement in (("logon_type", 2), ("elevated", True), ("token_type", 2)):
        changed = deepcopy(value)
        changed["token"][key] = replacement
        with pytest.raises(ValueError):
            host_acceptance.invocation(changed, **arguments)
    for key, replacement in (("engine_pid", 98), ("registration_receipt_sha256", "c" * 64)):
        with pytest.raises(ValueError):
            host_acceptance.invocation({**value, key: replacement}, **arguments)
