"""Independently approved first landing, separate from ordinary v2 acceptance.

The native installer owns the adopted lease, process tree and mutations. This
module only validates its exact closed envelope and the real merge boundaries.
Direct owner review of retained off-host evidence is the bootstrap trust root;
a certificate produced by the candidate cannot approve its own installation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from . import bootstrap_probe, environment, frozen, git_policy, host_runtime, merge_session, merge_tree, source
from .contracts import Graph, fields, inventory, record, validate_trust
from .host_session import _raw_reference
from .records import checked_root, digest, integer, publish, read, reference, require, timestamp, utc_now


SCHEMA = "qualification_bootstrap_install_envelope_v1"
MAXIMUM_SECONDS = 2700
BOOTSTRAP_ONLY_MARKER = b'{"schema":"qualification_bootstrap_install_only_v1"}\n'
REQUIRED_ADAPTER = {
    "bootstrap-install-only.json",
    "scripts/ops/bootstrap_qualification_install.ps1",
    "scripts/ops/close_bootstrap_qualification_install.ps1",
    "scripts/ops/qualification_bootstrap_install_child.ps1",
    "scripts/ops/qualification_bootstrap_install_contract.ps1",
    "scripts/ops/qualification_bootstrap_install_control.py",
    "scripts/ops/qualification_bootstrap_install_domain.py",
    "scripts/ops/qualification_bootstrap_probe_contract.ps1",
    "scripts/ops/qualification_host_identity.ps1",
    "scripts/ops/qualification_process.ps1",
    "scripts/ops/windows_kill_on_close_job.ps1",
    "scripts/ops/quiet_window_merge.ps1",
    "scripts/ops/roll_verdict.ps1",
}


def context(value, root, *, now=None):
    value = record(value, SCHEMA, {
        "bootstrap_id", "operation", "repo_root", "candidate", "baseline", "source", "branch_ref",
        "qualification", "control", "baseline_control", "environment", "configuration", "effective_tree",
        "host", "task", "not_before", "deadline", "limits", "adopted_helpers", "review_evidence",
        "approval", "probe", "rollback", "evidence_root"})
    require(type(value["bootstrap_id"]) is str and
            re.fullmatch(r"[A-Za-z0-9]{1,40}", value["bootstrap_id"]) is not None, "invalid installation identity")
    require(value["operation"] == "install_control_plane_K_once", "not a first-landing installation")
    require(type(value["branch_ref"]) is str and
            re.fullmatch(r"refs/remotes/origin/codex/[A-Za-z0-9_./-]{1,180}", value["branch_ref"]) is not None and
            ".." not in value["branch_ref"] and "//" not in value["branch_ref"], "invalid exact candidate ref")
    now = now or datetime.now(timezone.utc)
    start, end = timestamp(value["not_before"]), timestamp(value["deadline"])
    require(start <= now < end and 120 < (end - start).total_seconds() <= MAXIMUM_SECONDS,
            "installation is outside its bounded interval")
    limits = fields(value["limits"], {"commit_bytes", "working_set_bytes", "scratch_bytes", "read_bytes",
                                      "metadata_seconds", "metadata_read_bytes", "teardown_seconds"})
    integer(limits["commit_bytes"], minimum=64 * 1024**2, maximum=2 * 1024**3)
    integer(limits["working_set_bytes"], minimum=64 * 1024**2, maximum=min(limits["commit_bytes"], 1536 * 1024**2))
    integer(limits["scratch_bytes"], minimum=1024**2, maximum=128 * 1024**2)
    integer(limits["read_bytes"], minimum=1024**2, maximum=64 * 1024**3)
    integer(limits["metadata_seconds"], minimum=10, maximum=120)
    integer(limits["metadata_read_bytes"], minimum=1024**2, maximum=min(limits["read_bytes"], 4 * 1024**3))
    integer(limits["teardown_seconds"], minimum=10, maximum=60)
    root = checked_root(Path(root))
    require(checked_root(Path(value["evidence_root"])) == root, "installation evidence location differs")
    production, candidate = (checked_root(Path(value[key])) for key in ("repo_root", "candidate"))
    control = fields(value["control"], {"root", "closure", "git_policy"})
    baseline_control = fields(value["baseline_control"], {"root", "closure"})
    authority, adopted = (checked_root(Path(obj["root"])) for obj in (control, baseline_control))
    for left, right in ((root, production), (root, candidate), (root, authority), (root, adopted),
                        (authority, production), (authority, candidate), (authority, adopted),
                        (adopted, production), (adopted, candidate)):
        require(not left.is_relative_to(right) and not right.is_relative_to(left), "installation roots overlap")
    require(production != candidate and not production.is_relative_to(candidate), "candidate is not isolated")
    q = fields(value["qualification"], {"root", "policy", "review"})
    graph, local = Graph(Path(q["root"])), Graph(root)
    policy, reviewed, _ = validate_trust(graph, q["policy"], q["review"], now=now)
    require(reviewed["scope"] == "control_plane" and reviewed["source"] == value["source"],
            "first landing is restricted to exactly reviewed control-plane K")
    require(digest(value["baseline"], git=True) == reviewed["source"]["baseline"], "installation baseline differs")
    require(limits["commit_bytes"] <= policy["host"]["audit_commit_bytes"] and
            limits["working_set_bytes"] <= policy["host"]["audit_working_set_bytes"] and
            limits["metadata_seconds"] <= policy["host"]["metadata_seconds"], "installation exceeds reviewed host policy")
    digest(value["effective_tree"], git=True)
    host = fields(value["host"], {"host_id", "principal_id", "user_sid"})
    digest(host["host_id"])
    digest(host["principal_id"])
    require(type(host["user_sid"]) is str and re.fullmatch(r"S-1-[0-9-]{1,180}", host["user_sid"]) is not None,
            "invalid installation SID")
    require(fields(value["task"], {"name"})["name"] == "WeatherQualificationBootstrapInstall_" + value["bootstrap_id"],
            "wrong installation task")
    approval = fields(value["approval"], {"owner", "approved_at", "replaces_full_host_suite_for_K_only"})
    require(type(approval["owner"]) is str and bool(approval["owner"].strip()) and
            approval["replaces_full_host_suite_for_K_only"] is True and timestamp(approval["approved_at"]) <= start,
            "explicit separate owner acceptance of the K-only prerequisite replacement is missing")
    rollback = fields(value["rollback"], {"baseline", "generated_configuration", "mode", "after_commit"})
    require(rollback == {"baseline": value["baseline"], "generated_configuration": value["configuration"],
            "mode": "guarded_abort_restore_and_prove_capture", "after_commit": "preserve_and_reconcile"},
            "rollback must preserve B/Q and uncertain committed state")
    for ref in (value["environment"], value["configuration"], value["review_evidence"],
                control["closure"], control["git_policy"], baseline_control["closure"]):
        reference(ref)
    helpers = inventory(value["adopted_helpers"], "qualification_runtime_files_v2")
    require([row["path"] for row in helpers["files"]] == list(bootstrap_probe.ADOPTED_HELPERS), "wrong adopted helpers")
    closure = inventory(local.get(control["closure"]), "qualification_runtime_files_v2")
    require(REQUIRED_ADAPTER <= {row["path"] for row in closure["files"]}, "installation adapter closure is incomplete")
    require(len(closure["files"]) <= 512 and sum(row["size"] for row in closure["files"]) <= 8 * 1024**2,
            "installation adapter closure exceeds its fixed bound")
    review = record(local.get(value["review_evidence"]), "qualification_bootstrap_install_review_v1",
                    {"source", "policy_sha256", "adapter_closure_sha256", "baseline_closure_sha256",
                     "workflow_revision", "windows", "linux", "diff_review", "rollback_review"})
    require(review["source"] == value["source"] and review["policy_sha256"] == q["policy"]["sha256"] and
            review["adapter_closure_sha256"] == control["closure"]["sha256"] and
            review["baseline_closure_sha256"] == baseline_control["closure"]["sha256"], "independent installation review differs")
    digest(review["workflow_revision"], git=True)
    # These are directly owner-reviewed records, not a certificate minted by K.
    # The independent reviewer retains authenticated exact-attempt artifacts.
    for platform in ("windows", "linux"):
        result = fields(review[platform], {"status", "run_id", "attempt", "coverage", "logs", "artifacts"})
        require(result["status"] == "PASS", "off-host review is incomplete")
        for key in ("run_id", "attempt"):
            require(type(result[key]) is str and result[key].isascii() and result[key].isdigit() and
                    int(result[key]) > 0, "invalid exact off-host run attempt")
        for key in ("coverage", "logs", "artifacts"):
            local.blob(reference(result[key]), maximum=128 * 1024**2)
    for key in ("diff_review", "rollback_review"):
        local.blob(reference(review[key]))
    m = {"repo_root": str(production), "worktree_root": str(candidate), "control": control, "qualification": q,
         "baseline": {"master": value["baseline"]}, "expected_tip": value["source"]["commit"], "branch_ref": value["branch_ref"]}
    checked = {"envelope": value, "manifest": m, "graph": graph, "local": local, "policy": policy, "review": reviewed,
               "host_plan": {"configuration": value["configuration"], "environment": value["environment"]}}
    validate_probe(checked, now=now)
    return checked


def validate_probe(checked, *, now):
    value, local = checked["envelope"], checked["local"]
    probe = fields(value["probe"], {"root", "envelope", "result", "review", "task_xml_sha256"})
    probe_graph = Graph(checked_root(Path(probe["root"])))
    require(probe_graph.root != local.root and not probe_graph.root.is_relative_to(local.root) and
            not local.root.is_relative_to(probe_graph.root), "probe and installation namespaces overlap")
    p = probe_graph.get(reference(probe["envelope"]))
    # Validate the original probe's own interval, then require that it completed
    # before the separately approved installation. Do not rerun expired probes.
    bootstrap_probe.context(p, probe_graph.root, now=timestamp(p["not_before"]))
    for key in ("repo_root", "candidate", "baseline", "source", "qualification", "host", "adopted_helpers"):
        require(p[key] == value[key], "installation differs from independently reviewed probes")
    for key in ("environment", "configuration"):
        require(probe_graph.get(p[key]) == local.get(value[key]), "probe configuration/environment differs")
    require(timestamp(p["deadline"]) <= timestamp(value["approval"]["approved_at"]), "probes did not precede owner approval")
    result = record(probe_graph.get(reference(probe["result"])), "qualification_bootstrap_probe_result_v1",
        {"status", "envelope_sha256", "adapter_sha256", "outer_teardown_proved", "child_exit_code",
         "preflight_read_bytes", "observation", "native_read_bytes", "scratch_bytes",
         "integration_eligible", "full_suite_replacement", "review_required"})
    require(result["status"] == "PROBES_RECORDED" and result["envelope_sha256"] == probe["envelope"]["sha256"] and
            result["outer_teardown_proved"] is True and type(result["child_exit_code"]) is int and result["child_exit_code"] == 0 and
            result["integration_eligible"] is False and result["full_suite_replacement"] is False and
            result["review_required"] is True, "probe parent result is incomplete or has false authority")
    integer(result["preflight_read_bytes"], maximum=256 * 1024**2)
    integer(result["native_read_bytes"], maximum=p["limits"]["read_bytes"])
    integer(result["scratch_bytes"], maximum=p["limits"]["scratch_bytes"])
    closure = probe_graph.get(p["control"]["closure"])
    entry = next(row for row in closure["files"] if row["path"] == "scripts/ops/bootstrap_qualification_probe.ps1")
    require(result["adapter_sha256"] == entry["sha256"], "probe used another adapter")
    require(result["observation"]["path"] == "probe-work/observations/observation.json", "wrong probe observation path")
    observation = record(probe_graph.get(result["observation"]), bootstrap_probe.RESULT_SCHEMA,
        {"envelope_sha256", "started_at", "completed_at", "source", "configuration", "results", "markets",
         "native_parent_completion_required", "integration_eligible", "full_suite_replacement"})
    require(observation["source"] == value["source"] and observation["envelope_sha256"] == result["envelope_sha256"] and
            observation["native_parent_completion_required"] is True and observation["integration_eligible"] is False and
            observation["full_suite_replacement"] is False and
            timestamp(p["not_before"]) <= timestamp(observation["started_at"]) <= timestamp(observation["completed_at"]) <
            timestamp(p["deadline"]) <= now, "probe observation identity/interval differs")
    names = {"isolated_imports", "configuration_overlay", "offline_environment", "duplicate_path", "stdin_eof",
             "create_once_flush_rename", "captured_streams", "timeout_cleanup", "inherited_handles"}
    fields(observation["results"], names)
    observations = Graph(probe_graph.root / "probe-work/observations")
    for name, ref in observation["results"].items():
        prefix = "" if name in {"captured_streams", "timeout_cleanup", "inherited_handles"} else "candidate/"
        require(ref["path"] == prefix + name + ".json", "probe selected another result")
        item = record(observations.get(ref), "qualification_host_probe_v2", {"name", "status", "detail"})
        require(item["name"] == name and item["status"] == "PASS", "fixed probe did not pass")
    reviewed = record(local.get(reference(probe["review"])), "qualification_bootstrap_probe_review_v1",
                      {"envelope_sha256", "result_sha256", "source", "reviewer", "reviewed_at", "decision"})
    require(reviewed["envelope_sha256"] == probe["envelope"]["sha256"] and
            reviewed["result_sha256"] == probe["result"]["sha256"] and reviewed["source"] == value["source"] and
            type(reviewed["reviewer"]) is str and bool(reviewed["reviewer"].strip()) and
            reviewed["decision"] == "ACCEPT_FIXED_PROBES_FOR_K" and
            timestamp(p["deadline"]) <= timestamp(reviewed["reviewed_at"]) <= timestamp(value["approval"]["approved_at"]),
            "independent probe review does not bind this installation")
    invocation = probe_graph.get(_raw_reference(probe_graph.root, "probe-work/invocation.json"))
    require(hashlib.sha256(invocation["task_xml"].encode("utf-8")).hexdigest() == digest(probe["task_xml_sha256"]),
            "completed probe task definition differs")
    probe_graph.fresh()
    observations.fresh()
    checked["probe_envelope"] = p
    checked["probe_configuration"] = observation["configuration"]


def verify_inputs(checked):
    value, m = checked["envelope"], checked["manifest"]
    local, graph = checked["local"], checked["graph"]
    selected = host_runtime.profile(local.get(value["environment"]), checked=checked)
    host_runtime.verify_environment(checked, selected)
    git = host_runtime.tool(selected, "git")
    production, candidate = Path(m["repo_root"]), Path(m["worktree_root"])
    options = git_policy.validate(local.get(m["control"]["git_policy"]), git=git,
        production=production, candidate=candidate, baseline=value["baseline"], commit=m["expected_tip"],
        graph=graph, environment_ref=selected["environment"], bindings=selected["bindings"])
    source.bind_host_git_policy(options)
    require(source.identity(git, candidate, source=m["expected_tip"], baseline=value["baseline"]) == value["source"],
            "installation candidate identity differs")
    source.clean_checkout(git, candidate)
    require(source.inventory(git, candidate, m["expected_tip"], verify_working=True) ==
            graph.get(checked["review"]["source_inventory"]), "installation candidate working bytes differ")
    before = merge_tree.tree_entries(git, candidate, value["baseline"])
    after = merge_tree.tree_entries(git, candidate, m["expected_tip"])
    require(all(before[path] == after[path] for path in merge_tree.GENERATED), "K may not edit generated configuration")
    # K is also the legacy-boot-safe sentinel while commit invocation is
    # ambiguous: it must never be a config-only preparation child of B.
    require(any(before.get(path) != after.get(path) for path in set(before) | set(after)
                if path not in merge_tree.GENERATED), "first landing has no control-plane change")
    authority = Path(m["control"]["root"])
    closure = local.get(m["control"]["closure"])
    paths = [row["path"] for row in closure["files"]]
    require(environment.enumerate_files(authority) == paths and environment.files_manifest(authority, paths) == closure,
            "independently reviewed installation adapter changed")
    require((authority / "bootstrap-install-only.json").read_bytes() == BOOTSTRAP_ONLY_MARKER,
            "temporary guarded primitive is not bootstrap-only")
    adopted = value["baseline_control"]
    baseline_closure = frozen.validate(git, production, value["baseline"], destination=Path(adopted["root"]),
                                      value=local.get(adopted["closure"]))
    pins = {row["path"]: row for row in baseline_closure["files"]}
    for helper in value["adopted_helpers"]["files"]:
        require(all(pins[helper["path"]][key] == helper[key] for key in ("sha256", "size", "mode")),
                "admission/containment is not adopted B")
    # The temporary copy adds only explicit root routing to B's classifier.
    # Its verdict algorithm cannot be replaced by a candidate-owned check.
    roll_path = "scripts/ops/roll_verdict.ps1"
    adopted_roll = (Path(adopted["root"]) / roll_path).read_text(encoding="utf-8")
    adapted_roll = adopted_roll.replace('    [string]$JsonOut = ""\n',
        '    [string]$JsonOut = "",\n    [string]$RepoRoot = (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent)\n', 1)
    adapted_roll = adapted_roll.replace('$repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent\n',
        '$repo = (Resolve-Path -LiteralPath $RepoRoot -ErrorAction Stop).Path\n', 1)
    require((authority / roll_path).read_text(encoding="utf-8") == adapted_roll,
            "bootstrap roll verdict changed beyond explicit B root routing")
    maximum = {"seconds": value["limits"]["metadata_seconds"], "read_bytes": value["limits"]["metadata_read_bytes"],
               "scratch_bytes": value["limits"]["scratch_bytes"]}
    configuration = host_runtime.verify_configuration(checked, selected, maximum)
    require(configuration == checked["probe_configuration"], "configuration acceptance differs from the reviewed probes")
    preview = merge_tree.preview(git, candidate, source_commit=m["expected_tip"], source_tree=value["source"]["tree"],
        baseline=value["baseline"], config_graph=local, configuration_ref=value["configuration"])
    require(preview["tree"] == value["effective_tree"], "installation effective tree differs from owner approval")
    return selected, git, configuration


def run_boundary(request_path, request_sha256):
    path = Path(request_path)
    output = checked_root(path.parent)
    request_ref = _raw_reference(output, path.name)
    require(request_ref["sha256"] == digest(request_sha256), "installation request changed")
    request = fields(read(output, request_ref).value,
                     {"envelope_path", "envelope_sha256", "phase", "prepared_baseline", "deadline"})
    phase = request["phase"]
    require(phase in merge_session.BOUNDARIES, "unsupported installation boundary")
    deadline = timestamp(request["deadline"])
    require(datetime.now(timezone.utc) < deadline, "installation boundary expired")
    envelope_path = Path(request["envelope_path"])
    root = checked_root(envelope_path.parent)
    require(output == root / "install-work/merge-work" / phase, "noncanonical installation boundary")
    ref = _raw_reference(root, envelope_path.name)
    require(ref["sha256"] == digest(request["envelope_sha256"]), "installation envelope changed")
    checked = context(read(root, ref).value, root)
    selected, git, configuration = verify_inputs(checked)
    trees = merge_session.tree_boundary(checked, git, phase=phase, prepared_baseline=request["prepared_baseline"])
    checked["local"].fresh()
    checked["graph"].fresh()
    require(datetime.now(timezone.utc) < deadline, "installation boundary exceeded its deadline")
    return publish(output, "boundary.json", {"schema": "qualification_bootstrap_install_boundary_v1",
        "envelope_sha256": ref["sha256"], "phase": phase, "prepared_baseline": request["prepared_baseline"],
        "validated_at": utc_now(), "data_final": utc_now() if phase in {"before-config", "before-stage"} else None,
        "configuration": configuration, **trees,
        "git_options": git_policy.options(checked["local"].get(checked["manifest"]["control"]["git_policy"])),
        "native_parent_completion_required": True, "integration_eligible": False})
