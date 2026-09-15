"""Read-only checks called by the adopted primitive at actual Git boundaries.

The native parent owns the lease, deadlines, resource envelope and mutation.
Every invocation reopens the complete retained graph; no cached PASS token or
candidate-supplied executable can select a check or a merge resolution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import attempt, git_policy, host_acceptance, host_audit, host_runtime, merge_tree, source
from .contracts import Graph, fields
from .host_session import _raw_reference
from .records import checked_root, digest, publish, read, require, timestamp, utc_now


BOUNDARIES = ("prepare", "before-config", "prepared", "before-stage", "staged",
              "before-commit", "committed", "before-push", "published")


def tree_boundary(checked, git, *, phase, prepared_baseline):
    """Compare real index, working bytes and parents with B+Q or S+Q."""
    require(phase in BOUNDARIES, "unknown guarded merge boundary")
    m, reviewed, local = checked["manifest"], checked["review"], checked["local"]
    production, candidate = Path(m["repo_root"]), Path(m["worktree_root"])
    baseline, commit = m["baseline"]["master"], m["expected_tip"]
    configuration_ref = checked["host_plan"]["configuration"]
    preview = merge_tree.preview(git, candidate, source_commit=commit, source_tree=reviewed["source"]["tree"],
        baseline=baseline, config_graph=local, configuration_ref=configuration_ref)
    baseline_entries = merge_tree.tree_entries(git, candidate, baseline)
    for item in merge_tree.configuration(local.get(configuration_ref))["generated"]:
        require(item["path"] in baseline_entries, "generated path absent from baseline")
        baseline_entries[item["path"]] = {"mode": "100644", "oid": item["git_blob"]}
    prepared_tree = merge_tree.tree_id(baseline_entries)
    head = source.git_output(git, production, "rev-parse", "HEAD").decode("ascii").strip()
    branch = source.git_output(git, production, "symbolic-ref", "--quiet", "--short", "HEAD").decode().strip()
    require(branch == "master", "production branch differs from master")
    expected_origin = head if phase == "published" else baseline
    require(source.git_output(git, production, "rev-parse", "origin/master").decode().strip() == expected_origin,
            "published baseline moved or publication is unacknowledged")
    require(source.git_output(git, production, "rev-parse", m["branch_ref"]).decode().strip() == commit,
            "reviewed candidate ref moved")
    merged = phase in {"staged", "before-commit", "committed", "before-push", "published"}
    expected_tree = preview["tree"] if merged else prepared_tree
    if phase in {"prepare", "before-config"}:
        require(head == baseline and prepared_baseline == baseline, "baseline advanced before preparation")
        original_tree = source.git_output(git, production, "rev-parse", baseline + "^{tree}").decode().strip()
        merge_tree.staged_tree(git, production, original_tree)
    elif phase in {"prepared", "before-stage", "staged", "before-commit"}:
        require(head == digest(prepared_baseline, git=True), "prepared baseline moved")
        actual_tree = source.git_output(git, production, "rev-parse", head + "^{tree}").decode().strip()
        require(actual_tree == prepared_tree, "prepared commit differs from complete B plus Q")
        if head != baseline:
            parents = source.git_output(git, production, "rev-list", "--parents", "-n", "1", head).decode().split()
            require(parents == [head, baseline], "prepared commit is not one child of B")
        merge_tree.staged_tree(git, production, expected_tree)
    else:
        merge_tree.committed_tree(git, production, expected_tree=expected_tree,
                                 first_parent=prepared_baseline, source_commit=commit)
        merge_tree.staged_tree(git, production, expected_tree)
    merge_head = Path(source.git_output(git, production, "rev-parse", "--path-format=absolute", "--git-path",
                                      "MERGE_HEAD").decode().strip())
    if phase in {"staged", "before-commit"}:
        require(merge_head.read_bytes() == (commit + "\n").encode(), "MERGE_HEAD differs from exact S")
    else:
        require(not merge_head.exists(), "unexpected merge in progress")
    inventory = checked["graph"].get(reviewed["source_inventory"]) if merged else source.inventory(git, candidate, baseline)
    merge_tree.working_bytes(git, production, source_root=candidate, source_commit=commit if merged else baseline,
        source_inventory=inventory, config_graph=local, configuration_ref=configuration_ref)
    return {"effective_tree": preview["tree"], "prepared_tree": prepared_tree, "head": head}


def run_boundary(request_path, request_sha256):
    request_path = Path(request_path)
    output = checked_root(request_path.parent)
    request_ref = _raw_reference(output, request_path.name)
    require(request_ref["sha256"] == digest(request_sha256), "merge boundary request changed")
    request = fields(read(output, request_ref).value,
                     {"manifest_path", "manifest_sha256", "phase", "prepared_baseline", "deadline"})
    phase = request["phase"]
    require(phase in BOUNDARIES, "unsupported merge boundary")
    deadline = timestamp(request["deadline"])
    require(datetime.now(timezone.utc) < deadline, "merge boundary has no remaining budget")
    manifest_path = Path(request["manifest_path"])
    root = checked_root(manifest_path.parent)
    require(output.parent == root / "merge-work" and output.name == phase, "noncanonical merge boundary namespace")
    ref = _raw_reference(root, manifest_path.name)
    require(ref["sha256"] == request["manifest_sha256"], "merge manifest changed")
    checked = attempt.manifest(read(root, ref).value, actual_root=root)
    m, plan = checked["manifest"], checked["host_plan"]
    require(datetime.now().date().isoformat() == plan["local_day"], "merge belongs to another local day")
    selected = host_runtime.profile(checked["local"].get(plan["environment"]), checked=checked)
    git = host_runtime.verify_source(checked, selected)
    host_runtime.verify_environment(checked, selected)
    measured = host_acceptance.measurements(checked["local"], plan["measurements"], policy=checked["policy"], host_plan=plan)
    maximum = measured["phases"]["metadata"]["maximum"]
    registration = _raw_reference(root, "registration-receipt.json")
    intent = _raw_reference(root, "registration-intent.json")
    receipt = host_acceptance.validate_receipt(checked, _raw_reference(root, "host-receipt.json"),
        manifest_sha256=ref["sha256"], registration_sha256=registration["sha256"], intent_sha256=intent["sha256"])
    signature = output / "signature"
    signature.mkdir()
    code = host_runtime.verify_code_in_parent(checked, selected, scratch=signature,
                                            deadline=request["deadline"], boundary="merge")
    host_runtime.verify_configuration(checked, selected, maximum)
    trees = tree_boundary(checked, git, phase=phase, prepared_baseline=request["prepared_baseline"])
    checked["graph"].fresh()
    checked["local"].fresh()
    data_final = None
    if phase in {"before-config", "before-stage"}:
        if plan["scope"] == "reliability_current_inputs":
            audit = checked["local"].get(plan["audit"])
            result = checked["local"].get(receipt["audit"])
            inputs = Graph(Path(audit["inputs_root"]))
            prepared = host_audit.preparation(inputs, result["preparation"])
            remaining = int((deadline - datetime.now(timezone.utc)).total_seconds())
            require(remaining > 0, "final current inputs have no measured budget")
            # This is a new complete read, separately bounded by the reviewed
            # metadata envelope, while preserving the input reader's accounting.
            prior = prepared["read_bytes"]
            limits = {"seconds": min(maximum["seconds"], remaining), "files": 20000,
                      "staged_bytes": max(1, maximum["scratch_bytes"]), "read_bytes": prior + maximum["read_bytes"]}
            host_audit.revalidate(input_graph=inputs, preparation_ref=result["preparation"], roots=audit["roots"],
                                  maximum=limits, previously_read=prior)
        data_final = utc_now()
    require(datetime.now(timezone.utc) < deadline, "merge validation exceeded its native deadline")
    return publish(output, "boundary.json", {"schema": "qualification_merge_boundary_v2", "phase": phase,
        "manifest_sha256": ref["sha256"], "prepared_baseline": request["prepared_baseline"],
        "validated_at": utc_now(), "data_final": data_final, "code": code, **trees,
        "git_options": git_policy.options(checked["local"].get(m["control"]["git_policy"])),
        "native_parent_completion_required": True, "integration_eligible": False})
