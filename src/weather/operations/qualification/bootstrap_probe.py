"""Fixed first-landing probes, authorized by an externally pinned envelope.

This is a temporary adapter, not the v2 acceptance gate. Its source closure and
input digest must be reviewed independently. It consumes no self-issued code
certificate, and none of its outputs can authorize installation or a merge.
The PowerShell parent owns admission, the actual S4U invocation and teardown.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from . import environment, git_policy, host_runtime, source
from .contracts import Graph, fields, inventory, record, validate_trust
from .host_session import _probes, _raw_reference
from .records import checked_root, digest, integer, publish, read, reference, require, timestamp, utc_now


SCHEMA = "qualification_bootstrap_probe_envelope_v1"
RESULT_SCHEMA = "qualification_bootstrap_probe_observation_v1"
ADOPTED_HELPERS = ("scripts/ops/windows_kill_on_close_job.ps1", "scripts/ops/workload_admission.ps1")
NATIVE_HELPERS = ("scripts/ops/windows_kill_on_close_job.ps1", "scripts/ops/qualification_process.ps1")
MAXIMUM_SECONDS = 480


def context(value, root, *, now=None):
    """Validate the closed probe-only request; this function grants no authority."""
    value = record(value, SCHEMA, {
        "bootstrap_id", "operation", "repo_root", "candidate", "baseline", "source", "qualification",
        "control", "environment", "configuration", "host", "task", "not_before", "deadline", "limits",
        "adopted_helpers", "review_evidence", "integration_eligible", "full_suite_replacement", "evidence_root"})
    require(type(value["bootstrap_id"]) is str and
            re.fullmatch(r"[A-Za-z0-9]{1,40}", value["bootstrap_id"]) is not None, "invalid bootstrap identity")
    require(value["operation"] == "fixed_control_plane_probes" and
            value["integration_eligible"] is False and value["full_suite_replacement"] is False,
            "bootstrap probe envelope cannot supply acceptance or installation authority")
    now = now or datetime.now(timezone.utc)
    start, end = timestamp(value["not_before"]), timestamp(value["deadline"])
    require(start <= now < end and 0 < (end - start).total_seconds() <= MAXIMUM_SECONDS,
            "bootstrap probes are outside their absolute eight-minute interval")
    limits = fields(value["limits"], {"commit_bytes", "working_set_bytes", "scratch_bytes", "read_bytes", "teardown_seconds"})
    integer(limits["commit_bytes"], minimum=64 * 1024**2, maximum=512 * 1024**2)
    integer(limits["working_set_bytes"], minimum=64 * 1024**2, maximum=limits["commit_bytes"])
    integer(limits["scratch_bytes"], minimum=1024**2, maximum=64 * 1024**2)
    integer(limits["read_bytes"], minimum=1024**2, maximum=2 * 1024**3)
    integer(limits["teardown_seconds"], minimum=10, maximum=60)
    require((end - start).total_seconds() > limits["teardown_seconds"] + 5, "bootstrap has no execution reserve")
    host = fields(value["host"], {"host_id", "principal_id", "user_sid"})
    digest(host["host_id"])
    digest(host["principal_id"])
    require(type(host["user_sid"]) is str and re.fullmatch(r"S-1-[0-9-]{1,180}", host["user_sid"]) is not None,
            "invalid bootstrap principal SID")
    task = fields(value["task"], {"name"})
    require(task["name"] == "WeatherQualificationBootstrapProbe_" + value["bootstrap_id"], "wrong bootstrap task name")
    root = checked_root(Path(root))
    require(checked_root(Path(value["evidence_root"])) == root, "bootstrap evidence location differs")
    production, candidate = (checked_root(Path(value[key])) for key in ("repo_root", "candidate"))
    control = fields(value["control"], {"root", "closure", "git_policy"})
    authority = checked_root(Path(control["root"]))
    # Retained envelopes and frozen adapter code are separate from both source
    # checkouts. The only writable directory is created below the envelope.
    for left, right in ((root, production), (root, candidate), (root, authority),
                        (authority, production), (authority, candidate)):
        require(not left.is_relative_to(right) and not right.is_relative_to(left), "bootstrap roots overlap")
    require(production != candidate and not production.is_relative_to(candidate), "bootstrap candidate is not isolated")
    q = fields(value["qualification"], {"root", "policy", "review"})
    graph, local = Graph(Path(q["root"])), Graph(root)
    policy, reviewed, _ = validate_trust(graph, q["policy"], q["review"], now=now)
    require(reviewed["scope"] == "control_plane" and reviewed["source"] == value["source"],
            "bootstrap scope/source differs from directly reviewed evidence")
    require(digest(value["baseline"], git=True) == reviewed["source"]["baseline"], "bootstrap baseline differs")
    for key in ("environment", "configuration", "review_evidence"):
        reference(value[key])
    reference(control["closure"])
    reference(control["git_policy"])
    helpers = inventory(value["adopted_helpers"], "qualification_runtime_files_v2")["files"]
    require([row["path"] for row in helpers] == list(ADOPTED_HELPERS), "bootstrap must use the two exact adopted helpers")
    # The parent additionally holds these files open against replacement. This
    # record deliberately pins the adapter independently of candidate S.
    closure = inventory(local.get(control["closure"]), "qualification_runtime_files_v2")
    paths = [row["path"] for row in closure["files"]]
    require(set(NATIVE_HELPERS) <= set(paths) and
            "scripts/ops/qualification_bootstrap_probe_control.py" in paths and
            "scripts/ops/bootstrap_qualification_probe.ps1" in paths and
            "scripts/ops/qualification_bootstrap_probe_child.ps1" in paths,
            "bootstrap adapter closure is incomplete")
    reviewed_evidence = local.get(value["review_evidence"])
    require(type(reviewed_evidence) is dict and bool(reviewed_evidence), "direct bootstrap review evidence is missing")
    m = {"repo_root": str(production), "worktree_root": str(candidate), "control": control,
         "qualification": q, "baseline": {"master": value["baseline"]}, "expected_tip": value["source"]["commit"]}
    return {"envelope": value, "manifest": m, "graph": graph, "local": local,
            "policy": policy, "review": reviewed,
            "host_plan": {"configuration": value["configuration"], "environment": value["environment"]}}


def verify_inputs(checked):
    """Recheck reviewed native inputs without a candidate-produced certificate."""
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
    require(source.git_output(git, production, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
            == value["baseline"], "adopted baseline changed")
    require(source.identity(git, candidate, source=m["expected_tip"], baseline=value["baseline"]) == value["source"],
            "bootstrap candidate identity differs")
    for pin in value["adopted_helpers"]["files"]:
        raw = source.git_output(git, production, "cat-file", "blob", value["baseline"] + ":" + pin["path"])
        require(len(raw) == pin["size"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
                "bootstrap native helper differs from adopted baseline")
    source.clean_checkout(git, candidate)
    require(source.inventory(git, candidate, m["expected_tip"], verify_working=True) ==
            graph.get(checked["review"]["source_inventory"]), "bootstrap candidate working bytes differ")
    frozen = Path(m["control"]["root"])
    closure = local.get(m["control"]["closure"])
    paths = [row["path"] for row in closure["files"]]
    require(environment.enumerate_files(frozen) == paths and environment.files_manifest(frozen, paths) == closure,
            "independently reviewed adapter closure changed")
    maximum = {"seconds": MAXIMUM_SECONDS, "read_bytes": value["limits"]["read_bytes"],
               "scratch_bytes": value["limits"]["scratch_bytes"]}
    configuration = host_runtime.verify_configuration(checked, selected, maximum)
    return selected, configuration


def run(envelope_path, expected_sha256):
    """Run only the existing nine fixed probes inside the native parent's Job."""
    path = Path(envelope_path)
    root = checked_root(path.parent)
    ref = _raw_reference(root, path.name)
    require(ref["sha256"] == digest(expected_sha256), "bootstrap envelope changed")
    checked = context(read(root, ref).value, root)
    selected, before = verify_inputs(checked)
    output = checked_root(root / "probe-work" / "observations")
    require(not any(output.iterdir()), "bootstrap observation namespace is spent")
    started = utc_now()
    results, markets = _probes(checked, selected, output, checked["envelope"]["deadline"])
    _, after = verify_inputs(checked)
    require(before == after, "bootstrap current configuration changed during probes")
    require(timestamp(utc_now()) < timestamp(checked["envelope"]["deadline"]), "bootstrap probe deadline expired")
    checked["local"].fresh()
    checked["graph"].fresh()
    return publish(output, "observation.json", {"schema": RESULT_SCHEMA,
        "envelope_sha256": expected_sha256, "started_at": started, "completed_at": utc_now(),
        "source": checked["envelope"]["source"], "configuration": after, "results": results, "markets": markets,
        "native_parent_completion_required": True, "integration_eligible": False, "full_suite_replacement": False})
