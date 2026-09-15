"""Prepare inert configuration and attempt records inside an admitted parent.

The two fixed operations read Git/configuration and write only a fresh evidence
namespace. They cannot install dependencies, register tasks, arm or merge. A
draft still requires the creator's independent native preparation proof.
"""

from __future__ import annotations

from pathlib import Path
import re

from . import attempt, frozen, git_policy, host_configuration, host_runtime, inputs, merge_tree, source
from .contracts import Graph, fields, record, validate_trust
from .host_audit import new_budget
from .records import checked_root, publish, read, require, timestamp, utc_now


def configuration(git, production, candidate, *, baseline, commit, output, maximum):
    output, production, candidate = map(checked_root, (output, production, candidate))
    require(not output.is_relative_to(production) and not output.is_relative_to(candidate),
            "configuration evidence must be outside both source checkouts")
    budget = new_budget(maximum)
    required, optional = host_configuration.required_paths(git, candidate, production, source_commit=commit,
                                                          baseline=baseline, budget=budget)
    roots = inputs.SourceRoots({"production": production}, {"production": ["config", "artifacts"]},
                               relative_root="production")
    stager = inputs.Stager(roots, output, budget, maximum_files=maximum["files"], maximum_bytes=maximum["staged_bytes"])
    generated = []
    for path in sorted([*required, *optional]):
        entry = stager.stage(path, mandatory=path in required, kind="config")
        if path in merge_tree.GENERATED:
            with inputs.verified_input(output, entry["staged"], budget) as handle:
                raw = handle.read()
            generated.append({"path": path, "payload": entry["staged"], "generation": entry["generation"],
                              "git_blob": merge_tree.object_id("blob", raw)})
    ref = publish(output, "configuration.json", {"schema": "qualification_configuration_v2", "source": commit,
        "baseline": baseline, "generated": generated, "dependencies": stager.seal("configuration-inputs.json")})
    graph = Graph(output)
    result = host_configuration.validate(git, production, candidate=candidate, source_commit=commit,
                                         baseline=baseline, graph=graph, configuration_ref=ref, budget=budget)
    return {"configuration": ref, "validation": result, "read_bytes": budget.observed_bytes,
            "staged_bytes": stager.total_bytes, "integration_eligible": False}


def orchestration(control, closure):
    """Read the one code-owned literal map; never execute metadata as PowerShell."""
    path = control / "scripts/ops/qualification_attempt_contract.ps1"
    raw = path.read_text(encoding="utf-8")
    match = re.search(r"function Get-WeatherQualificationOrchestrationNames\s*\{\s*return \[ordered\]@\{([^{}]+)\}\s*\}", raw)
    require(match is not None, "adopted orchestration map is not a literal record")
    body = match[1]
    pairs = re.findall(r"([a-z_]+)\s*=\s*'([a-z_]+\.ps1)'", body)
    require(re.sub(r"([a-z_]+)\s*=\s*'([a-z_]+\.ps1)'", "", body).strip(" \r\n\t;") == "" and
            len(pairs) == len({key for key, _ in pairs}), "orchestration map contains an expression or duplicate key")
    lookup = {row["path"]: row for row in closure["files"]}
    return {key: {"path": str(control / "scripts/ops" / name), "sha256": lookup["scripts/ops/" + name]["sha256"]}
            for key, name in pairs}


def prepare_control(git, *, output, production, candidate, reviewed, qualification, environment):
    baseline, commit = reviewed["source"]["baseline"], reviewed["source"]["commit"]
    control = output / "control"
    closure_ref = frozen.freeze(git, production, baseline, destination=control, evidence_root=output)
    hooks = output / "empty-hooks"
    hooks.mkdir()
    policy = git_policy.capture(git, production, candidate, baseline=baseline, commit=commit,
        hooks=hooks, graph=Graph(Path(qualification["root"])), environment_ref=environment["environment"], bindings=environment["bindings"])
    return {"root": str(control), "closure": closure_ref, "git_policy": publish(output, "git-policy.json", policy)}


def measurement_draft(git, *, output, production, candidate, reviewed, qualification, environment, metadata):
    from .measurement import context
    fields(metadata, {"measurement_id", "plan", "task"})
    control = prepare_control(git, output=output, production=production, candidate=candidate,
        reviewed=reviewed, qualification=qualification, environment=environment)
    value = {"schema": "qualification_measurement_request_v2", **metadata, "repo_root": str(production),
        "candidate": str(candidate), "qualification": qualification, "control": control}
    # Validate the planned interval without granting authority before its start.
    context(value, output, now=timestamp(metadata["plan"]["not_before"]))
    return publish(output, "measurement-request.json", value)


def draft(git, *, output, production, candidate, reviewed, qualification, environment, metadata):
    """Construct all controller bindings from B; supplied metadata cannot pick them."""
    fields(metadata, {"attempt_id", "created_at_local", "branch_ref", "authorization", "schedule", "host"})
    source_commit, baseline = reviewed["source"]["commit"], reviewed["source"]["baseline"]
    bound_control = prepare_control(git, output=output, production=production, candidate=candidate,
        reviewed=reviewed, qualification=qualification, environment=environment)
    control = Path(bound_control["root"])
    closure = Graph(output).get(bound_control["closure"])
    value = {"schema": "weather_integration_attempt_manifest_v2", "qualification_mode": "split_v2", **metadata,
        "attempt_root": str(output), "repo_root": str(production), "worktree_root": str(candidate),
        "expected_tip": source_commit, "baseline": {"master": baseline, "origin_master": baseline},
        "orchestration": orchestration(control, closure), "evidence": {key: str(output / name) for key, name in attempt.EVIDENCE.items()},
        "qualification": qualification, "control": bound_control}
    attempt.manifest(value, actual_root=output)
    return publish(output, "prepared-manifest.json", value)


def run(request_path, expected_sha256):
    request_path = Path(request_path)
    output = checked_root(request_path.parent)
    from .host_session import _raw_reference
    ref = _raw_reference(output, request_path.name)
    require(ref["sha256"] == expected_sha256, "planning request changed")
    request = record(read(output, ref).value, "qualification_planning_request_v2", {
        "operation", "repo_root", "candidate", "qualification", "environment", "maximum", "metadata", "deadline"})
    require(request["operation"] in {"configuration", "draft", "measurement-draft"}, "unknown fixed planning operation")
    require(timestamp(utc_now()) < timestamp(request["deadline"]), "planning deadline elapsed")
    production, candidate = checked_root(Path(request["repo_root"])), checked_root(Path(request["candidate"]))
    require(not output.is_relative_to(production) and not production.is_relative_to(output) and
            not output.is_relative_to(candidate) and not candidate.is_relative_to(output), "planning source/evidence roots overlap")
    graph, local = Graph(Path(request["qualification"]["root"])), Graph(output)
    policy, reviewed, _ = validate_trust(graph, request["qualification"]["policy"], request["qualification"]["review"])
    checked = {"manifest": {"worktree_root": str(candidate)}, "review": reviewed, "policy": policy, "graph": graph}
    selected = host_runtime.profile(local.get(request["environment"]), checked=checked)
    host_runtime.verify_environment(checked, selected)
    git = host_runtime.tool(selected, "git")
    baseline, commit = reviewed["source"]["baseline"], reviewed["source"]["commit"]
    for name in ("HEAD", "master", "origin/master"):
        require(source.git_output(git, production, "rev-parse", name).decode().strip() == baseline,
                "planning production baseline is not synchronized")
    require(source.identity(git, candidate, source=commit, baseline=baseline) == reviewed["source"], "planning source differs")
    source.clean_checkout(git, candidate)
    if request["operation"] == "configuration":
        require(request["metadata"] is None, "configuration preparation cannot supply a manifest")
        result = configuration(git, production, candidate, baseline=baseline, commit=commit, output=output, maximum=request["maximum"])
    elif request["operation"] == "measurement-draft":
        result = {"measurement_request": measurement_draft(git, output=output, production=production, candidate=candidate,
            reviewed=reviewed, qualification=request["qualification"], environment=selected, metadata=request["metadata"]),
            "integration_eligible": False}
    else:
        result = {"manifest": draft(git, output=output, production=production, candidate=candidate, reviewed=reviewed,
            qualification=request["qualification"], environment=selected, metadata=request["metadata"]), "integration_eligible": False}
    graph.fresh()
    local.fresh()
    require(timestamp(utc_now()) < timestamp(request["deadline"]), "planning exceeded admitted deadline")
    return publish(output, request["operation"] + "-planning.json", {
        "schema": "qualification_planning_result_v2", "request_sha256": expected_sha256,
        "completed_at": utc_now(), "native_parent_completion_required": True, **result})
