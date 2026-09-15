"""Bounded feasibility observations before a reviewed host plan exists.

Measurement has its own request and evidence namespace. It validates the same
code/source/environment graph as acceptance but consumes declared policy-capped
limits instead of a previous measurement. Its output has no attempt authority.
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from . import host, host_acceptance, host_audit, host_runtime, source
from .contracts import Graph, fields, record, validate_trust
from .host_session import _probes, _raw_reference
from .records import checked_root, digest, encode, publish, read, require, timestamp, utc_now


def context(value, root, *, now=None):
    now = now or datetime.now(timezone.utc)
    value = record(value, "qualification_measurement_request_v2", {
        "measurement_id", "repo_root", "candidate", "qualification", "control", "plan", "task"})
    require(type(value["measurement_id"]) is str and value["measurement_id"].isascii() and value["measurement_id"].isalnum() and 1 <= len(value["measurement_id"]) <= 40,
            "invalid measurement identity")
    q = fields(value["qualification"], {"root", "policy", "review", "certificate", "import", "revocations"})
    graph, local = Graph(Path(q["root"])), Graph(root)
    policy, reviewed, _ = validate_trust(graph, q["policy"], q["review"], now=now)
    plan = fields(value["plan"], {"source", "scope", "host_id", "principal_id", "not_before", "deadline",
        "configuration", "environment", "audit", "maximums"})
    require(plan["source"] == reviewed["source"] and plan["scope"] in {"control_plane", "reliability_current_inputs"},
            "measurement source/scope differs")
    digest(plan["host_id"])
    digest(plan["principal_id"])
    start, end = timestamp(plan["not_before"]), timestamp(plan["deadline"])
    require(start <= now < end and 0 < (end - start).total_seconds() <= 1920,
            "measurement is outside its absolute 32-minute interval")
    maximums = fields(plan["maximums"], set(host_acceptance.PHASES))
    for phase, maximum in maximums.items():
        host_acceptance.envelope(maximum, policy=policy, phase=phase)
    require(sum(row["seconds"] for row in maximums.values()) + 2 <= (end - start).total_seconds(),
            "measurement phases leave no final publication reserve")
    require((plan["audit"] is not None) is (plan["scope"] == "reliability_current_inputs"),
            "measurement audit does not match scope")
    production, candidate = checked_root(Path(value["repo_root"])), checked_root(Path(value["candidate"]))
    for source_root in (production, candidate):
        require(not root.is_relative_to(source_root) and not source_root.is_relative_to(root),
                "measurement evidence overlaps a source checkout")
    control = fields(value["control"], {"root", "closure", "git_policy"})
    require(Path(control["root"]) == root / "control", "measurement control namespace differs")
    fields(value["task"], {"name", "user_sid"})
    require(value["task"]["name"] == "WeatherQualificationMeasure_" + value["measurement_id"],
            "measurement task name differs")
    require(type(value["task"]["user_sid"]) is str and value["task"]["user_sid"].startswith("S-1-"), "invalid measurement principal SID")
    m = {"repo_root": str(production), "worktree_root": str(candidate), "expected_tip": reviewed["source"]["commit"],
        "baseline": {"master": reviewed["source"]["baseline"]}, "qualification": q, "control": control}
    return {"manifest": m, "host_plan": plan, "graph": graph, "local": local, "policy": policy, "review": reviewed}


def run_phase(request_path, request_sha256, phase):
    require(phase in host_acceptance.PHASES, "unknown measurement phase")
    request_path = Path(request_path)
    root = checked_root(request_path.parent)
    ref = _raw_reference(root, request_path.name)
    require(ref["sha256"] == digest(request_sha256), "measurement request changed")
    checked = context(read(root, ref).value, root)
    plan = checked["host_plan"]
    output = checked_root(root / "measurement-work" / phase)
    require(not (output / "observation.json").exists(), "measurement phase already spent")
    maximum = plan["maximums"][phase]
    selected = host_runtime.profile(checked["local"].get(plan["environment"]), checked=checked)
    git = host_runtime.verify_source(checked, selected)
    for name in ("HEAD", "master", "origin/master"):
        require(source.git_output(git, Path(checked["manifest"]["repo_root"]), "rev-parse", name).decode().strip() ==
                checked["review"]["source"]["baseline"], "measurement baseline is not synchronized")
    host_runtime.verify_environment(checked, selected)
    configuration = host_runtime.verify_configuration(checked, selected, maximum)
    signature = output / "signature"
    signature.mkdir()
    host_runtime.verify_code_in_parent(checked, selected, scratch=signature, deadline=plan["deadline"], boundary="launch")
    result = {"probes": None, "audit": None, "current": None, "markets": None}
    read_bytes = configuration["read_bytes"]
    if phase == "probes":
        result["probes"], result["markets"] = _probes(checked, selected, output, plan["deadline"])
    elif phase == "audit" and plan["scope"] == "reliability_current_inputs":
        audit_plan = checked["local"].get(plan["audit"])
        require(Path(audit_plan["receipt_root"]) == root / "audit-receipts", "measurement audit receipt root differs")
        observed = read(root / "measurement-work/probes", {**_raw_reference(root / "measurement-work/probes", "observation.json")}).value
        require(observed["markets"] == audit_plan["markets"], "measurement omits actual candidate markets")
        result["audit"] = host.run_audit(audit_plan, scratch=output)
        audit_graph = Graph(Path(audit_plan["receipt_root"]))
        audit = audit_graph.get(result["audit"])
        inputs = Graph(Path(audit_plan["inputs_root"]))
        prepared = host_audit.preparation(inputs, audit["preparation"])
        used = audit["read_bytes"]
        # The pipeline already performs one full final current validation.
        # Repeat twice within this same admitted native phase and read budget.
        for _ in range(2):
            current = host_audit.revalidate(input_graph=inputs, preparation_ref=audit["preparation"],
                roots=audit_plan["roots"], maximum=audit_plan["maximum"], previously_read=used)
            used = current["read_bytes"]
        read_bytes += used
        profile = {key: val for key, val in audit_plan.items() if key not in {"inputs_root", "output", "receipt_root", "deadline"}}
        result["current"] = {"audit_profile_sha256": hashlib.sha256(encode(profile)).hexdigest(),
            "preparation_sha256": audit["preparation"]["sha256"], "inputs_sha256": prepared["inputs"]["sha256"],
            "completed_at": utc_now(), "read_bytes": used, "repeated_validation_count": 3, "generation_unchanged": True}
    require(read_bytes <= maximum["read_bytes"] and timestamp(utc_now()) < timestamp(plan["deadline"]),
            "measurement exceeded complete read/deadline budget")
    checked["graph"].fresh()
    checked["local"].fresh()
    return publish(output, "observation.json", {"schema": "qualification_measurement_observation_v2", "phase": phase,
        "request_sha256": ref["sha256"], "read_bytes": read_bytes, "completed_at": utc_now(),
        "native_parent_completion_required": True, "integration_eligible": False, **result})
