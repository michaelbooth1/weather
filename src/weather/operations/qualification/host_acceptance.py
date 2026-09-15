"""Measured host envelopes and native phase consumption, never CI aliases.

The adopted native parent supplies the observations. This module checks their
complete retained records; a certificate, planned duration or child exit alone
cannot produce a real-host acceptance result.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .contracts import fields, record, sequence, text
from .records import digest, integer, reference, require, timestamp


PHASES = ("probes", "audit", "metadata", "teardown")
PROBES = ("isolated_imports", "configuration_overlay", "offline_environment", "duplicate_path",
          "captured_streams", "stdin_eof", "timeout_cleanup", "inherited_handles", "create_once_flush_rename")


def envelope(value, *, policy, phase):
    value = fields(value, {"seconds", "commit_bytes", "working_set_bytes", "scratch_bytes", "read_bytes"})
    limits = policy["host"]
    integer(value["seconds"], minimum=1, maximum=limits[phase + "_seconds"])
    commit = limits["probe_commit_bytes"] if phase == "probes" else limits["audit_commit_bytes"]
    working = limits["probe_commit_bytes"] if phase == "probes" else limits["audit_working_set_bytes"]
    integer(value["commit_bytes"], minimum=16 * 1024**2, maximum=commit)
    integer(value["working_set_bytes"], minimum=16 * 1024**2, maximum=min(working, value["commit_bytes"]))
    integer(value["scratch_bytes"], maximum=128 * 1024**3)
    integer(value["read_bytes"], minimum=1, maximum=1024 * 1024**3)
    return value


def native(value, *, maximum, minimum_disk_bytes):
    value = fields(value, {"completed", "failure", "exit_code", "teardown_proved", "elapsed_ms",
        "peak_private_bytes", "peak_working_set_bytes", "native_peak_commit_bytes", "system_commit_basis_points",
        "minimum_disk_bytes", "maximum_sample_gap_ms", "resource_samples"})
    require(value["completed"] is True and value["failure"] is None and value["teardown_proved"] is True and
            type(value["exit_code"]) is int and value["exit_code"] == 0, "host native execution or teardown failed")
    integer(value["elapsed_ms"], minimum=1, maximum=maximum["seconds"] * 1000)
    integer(value["peak_private_bytes"], minimum=1, maximum=maximum["commit_bytes"])
    integer(value["native_peak_commit_bytes"], minimum=1, maximum=maximum["commit_bytes"])
    integer(value["peak_working_set_bytes"], minimum=1, maximum=maximum["working_set_bytes"])
    integer(value["system_commit_basis_points"], minimum=1, maximum=6600)
    integer(value["minimum_disk_bytes"], minimum=minimum_disk_bytes)
    integer(value["maximum_sample_gap_ms"], maximum=1000)
    integer(value["resource_samples"], minimum=1)
    return value


def measurements(graph, ref, *, policy, host_plan, now=None):
    """Require reviewed actual native measurements for the exact source/host.

    Reliability scope additionally binds stable complete current-input evidence.
    Synthetic probes alone cannot qualify an unknown current corpus.
    """
    now = now or datetime.now(timezone.utc)
    value = record(graph.get(ref), "qualification_host_measurement_v2", {
        "source", "scope", "host_id", "principal_id", "environment_sha256", "configuration_sha256",
        "reviewer", "reviewed_at", "phases", "current_inputs"})
    for key in ("source", "scope", "host_id", "principal_id"):
        require(value[key] == host_plan[key], "measurement source, scope or native host differs")
    require(digest(value["environment_sha256"]) == host_plan["environment"]["sha256"] and
            digest(value["configuration_sha256"]) == host_plan["configuration"]["sha256"],
            "measurement environment/configuration differs")
    text(value["reviewer"])
    reviewed_at = timestamp(value["reviewed_at"])
    require(now - timedelta(days=7) <= reviewed_at <= now, "measurement review is stale or future-dated")
    phases = fields(value["phases"], set(PHASES))
    for name, phase in phases.items():
        fields(phase, {"maximum", "samples"})
        maximum = envelope(phase["maximum"], policy=policy, phase=name)
        require(maximum["seconds"] <= host_plan["phase_seconds"][name], "measurement exceeds the armed phase budget")
        for sample in sequence(phase["samples"], minimum=1, maximum=16):
            fields(sample, {"kind", "proof", "scratch_bytes", "read_bytes", "cpu_ms"})
            require(sample["kind"] in {"synthetic", "current"}, "unsupported measurement sample")
            native(graph.get(reference(sample["proof"])), maximum=maximum,
                   minimum_disk_bytes=policy["host"]["minimum_disk_bytes"])
            integer(sample["scratch_bytes"], maximum=maximum["scratch_bytes"])
            integer(sample["read_bytes"], minimum=1, maximum=maximum["read_bytes"])
            integer(sample["cpu_ms"], minimum=1)
    if value["scope"] == "reliability_current_inputs":
        current = record(graph.get(reference(value["current_inputs"])), "qualification_current_feasibility_v2", {
            "audit_profile_sha256", "preparation_sha256", "inputs_sha256", "completed_at", "read_bytes",
            "repeated_validation_count", "generation_unchanged", "native"})
        from .records import encode
        import hashlib
        audit_plan = graph.get(host_plan["audit"])
        # Measurement and acceptance use different fresh output namespaces.
        # Bind all computation/input/budget semantics, excluding only attempt
        # output paths and that attempt's absolute deadline.
        audit_profile = {key: val for key, val in audit_plan.items() if key not in {
            "inputs_root", "output", "receipt_root", "deadline"}}
        require(current["audit_profile_sha256"] == hashlib.sha256(encode(audit_profile)).hexdigest() and current["generation_unchanged"] is True,
                "current corpus was not measured against this complete audit plan")
        digest(current["preparation_sha256"])
        digest(current["inputs_sha256"])
        require(timestamp(current["completed_at"]) <= reviewed_at, "current-input review preceded its measurement")
        integer(current["repeated_validation_count"], minimum=3)
        integer(current["read_bytes"], minimum=1, maximum=phases["audit"]["maximum"]["read_bytes"])
        native(graph.get(reference(current["native"])), maximum=phases["audit"]["maximum"],
               minimum_disk_bytes=policy["host"]["minimum_disk_bytes"])
        require(any(sample["kind"] == "current" and sample["proof"] == current["native"]
                    for sample in phases["audit"]["samples"]), "audit has no reviewed current-corpus sample")
    else:
        require(value["current_inputs"] is None, "control-plane measurements cannot claim current-data acceptance")
    graph.fresh()
    return value


def invocation(value, *, host_plan, manifest, registration_sha256, intent_sha256):
    value = record(value, "qualification_s4u_invocation_v2", {
        "role", "host_id", "principal_id", "token", "ancestry", "task_name", "instance_guid", "engine_pid",
        "registration_receipt_sha256", "registration_intent_sha256"})
    require(value["role"] == "host" and value["host_id"] == host_plan["host_id"] and
            value["principal_id"] == host_plan["principal_id"] and
            value["task_name"] == manifest["schedule"]["host_task_name"], "native invocation belongs to another task")
    require(value["registration_receipt_sha256"] == digest(registration_sha256) and
            value["registration_intent_sha256"] == digest(intent_sha256), "native invocation registration differs")
    token = fields(value["token"], {"pid", "creation_utc_ticks", "image", "sid", "authentication_id",
                                     "logon_type", "token_type", "session", "elevated"})
    require(token["logon_type"] == 4 and type(token["logon_type"]) is int and
            token["token_type"] == 1 and type(token["token_type"]) is int and token["elevated"] is False,
            "host invocation is not unelevated primary S4U batch execution")
    integer(token["pid"], minimum=1)
    integer(token["creation_utc_ticks"], minimum=1)
    text(token["image"])
    text(token["sid"])
    text(token["authentication_id"])
    integer(token["session"])
    rows = sequence(value["ancestry"], minimum=1, maximum=3)
    for row in rows:
        fields(row, {"pid", "creation_utc_ticks"})
        integer(row["pid"], minimum=1)
        integer(row["creation_utc_ticks"], minimum=1)
    require(rows[0] == {key: token[key] for key in ("pid", "creation_utc_ticks")} and
            len({row["pid"] for row in rows}) == len(rows) and
            [row["creation_utc_ticks"] for row in rows] == sorted((row["creation_utc_ticks"] for row in rows), reverse=True),
            "native process creation lineage differs")
    require(type(value["engine_pid"]) is int and value["engine_pid"] in {row["pid"] for row in rows},
            "native scheduler engine is outside the bounded ancestry")
    import uuid
    uuid.UUID(text(value["instance_guid"]))
    return value


def validate_receipt(checked, ref, *, manifest_sha256, registration_sha256, intent_sha256, now=None):
    """Consume every host result; all mutation boundaries remain separate."""
    now = now or datetime.now(timezone.utc)
    graph, m, p, plan = checked["local"], checked["manifest"], checked["policy"], checked["host_plan"]
    value = record(graph.get(ref), "weather_integration_attempt_host_receipt_v2", {
        "status", "attempt_id", "manifest_sha256", "host_plan_sha256", "registration_receipt_sha256",
        "registration_intent_sha256", "started_at", "completed_at", "local_day", "invocation",
        "phases", "probes", "audit", "configuration_sha256", "environment_sha256", "code_sha256",
        "capture_before", "capture_after", "teardown_proved", "failure", "integration_eligible"})
    require(value["status"] == "PASS" and value["failure"] is None and value["teardown_proved"] is True and
            value["integration_eligible"] is False, "host proof is non-PASS or claims standalone merge authority")
    require(value["attempt_id"] == m["attempt_id"] and value["manifest_sha256"] == digest(manifest_sha256) and
            value["host_plan_sha256"] == m["host"]["sha256"] and value["local_day"] == plan["local_day"],
            "host receipt attempt or adoption day differs")
    require(value["registration_receipt_sha256"] == registration_sha256 and
            value["registration_intent_sha256"] == intent_sha256, "host receipt registration differs")
    start, end = timestamp(value["started_at"]), timestamp(value["completed_at"])
    require(timestamp(plan["not_before"]) <= start <= end <= timestamp(plan["deadline"]) and
            end <= now <= end + timedelta(seconds=p["validity"]["host_seconds"]), "host receipt deadline/freshness refused")
    invocation(graph.get(reference(value["invocation"])), host_plan=plan, manifest=m,
               registration_sha256=registration_sha256, intent_sha256=intent_sha256)
    measured = measurements(graph, plan["measurements"], policy=p, host_plan=plan, now=now)
    require(value["configuration_sha256"] == plan["configuration"]["sha256"] and
            value["environment_sha256"] == plan["environment"]["sha256"] and
            value["code_sha256"] == m["qualification"]["certificate"]["sha256"], "host proof dependency binding differs")
    phases = fields(value["phases"], set(PHASES))
    for name, phase in phases.items():
        native(graph.get(reference(phase)), maximum=measured["phases"][name]["maximum"],
               minimum_disk_bytes=p["host"]["minimum_disk_bytes"])
    probes = fields(value["probes"], set(PROBES))
    for name, result in probes.items():
        observed = record(graph.get(reference(result)), "qualification_host_probe_v2", {"name", "status", "detail"})
        require(observed["name"] == name and observed["status"] == "PASS", "required native probe is missing or failed")
        text(observed["detail"])
    for key in ("capture_before", "capture_after"):
        observations = sequence(value[key], minimum=3, maximum=3)
        require([item.get("name") for item in observations] == ["loop_status.json", "clob_loop_status.json",
                "observation_trigger_status.json"] and len({item.get("pid") for item in observations}) == 3,
                "host receipt does not identify the three canonical capture workers")
        for item in observations:
            fields(item, {"name", "pid", "creation_utc_ticks"})
            text(item["name"])
            integer(item["pid"], minimum=1)
            integer(item["creation_utc_ticks"], minimum=1)
    require(value["capture_before"] == value["capture_after"], "capture process generation changed during host qualification")
    if plan["scope"] == "reliability_current_inputs":
        from . import host
        audit_plan = graph.get(plan["audit"])
        result = graph.get(reference(value["audit"]))
        host.audit_completion(audit_plan, result["preparation"], result["computation"], result["current"])
    else:
        require(value["audit"] is None, "control-plane host proof cannot claim a current-input audit")
    graph.fresh()
    return value
