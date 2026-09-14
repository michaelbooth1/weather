"""Read-only native-host source, environment, configuration and signature work.

Every entry runs as a child of the adopted admitted Windows parent. Returned
data deliberately has no native-cleanup or integration authority; only that
parent can observe and certify the complete process tree after this child exits.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys

from . import authentication, environment, evidence, frozen, host_acceptance, host_configuration, producer, source
from .contracts import Graph, fields, record, validate_trust
from .records import checked_root, digest, encode, integer, open_record, publish, reference, require, timestamp


def profile(value, *, checked):
    value = record(value, "qualification_host_environment_v2", {
        "environment", "bindings", "wheel_root", "wheels", "tools", "verifier_runtime"})
    require(value["environment"] == checked["review"]["environments"]["windows"],
            "host environment differs from qualified native Windows environment")
    fields(value["tools"], {"python", "git", "powershell", "gh"})
    for tool in value["tools"].values():
        fields(tool, {"root", "path", "sha256", "size"})
        root = checked_root(Path(tool["root"]))
        from .records import relative_path
        relative_path(tool["path"])
        digest(tool["sha256"])
        integer(tool["size"], minimum=1)
        require(not root.is_relative_to(Path(checked["manifest"]["worktree_root"])), "candidate supplied a native tool")
    fields(value["verifier_runtime"], {"root", "files", "exclusions"})
    reference(value["verifier_runtime"]["files"])
    checked_root(Path(value["wheel_root"]))
    return value


def tool(profile, name):
    item = profile["tools"][name]
    actual = environment.file_identity(Path(item["root"]), item["path"], native_installation=True)
    require(actual["sha256"] == item["sha256"] and actual["size"] == item["size"], "native host executable drift")
    return Path(item["root"]) / item["path"]


def verify_environment(checked, selected):
    expected = producer.verify_environment(checked["graph"], selected["environment"], platform="windows",
        bindings=selected["bindings"], wheel_root=Path(selected["wheel_root"]), wheels=selected["wheels"])
    for name, expected_sha in (("python", expected["python"]["executable_sha256"]),
                               ("git", expected["git"]["sha256"]), ("powershell", expected["powershell"]["sha256"]),
                               ("gh", checked["policy"]["verifier"]["gh_sha256"])):
        tool(selected, name)
        require(selected["tools"][name]["sha256"] == expected_sha, "selected native host tool is not qualified")
    require(Path(sys.executable).resolve() == tool(selected, "python").resolve(), "host child used another interpreter")
    return expected


def verify_source(checked, selected):
    m, reviewed = checked["manifest"], checked["review"]
    git, candidate, production = tool(selected, "git"), Path(m["worktree_root"]), Path(m["repo_root"])
    frozen.validate(git, production, m["baseline"]["master"], destination=Path(m["control"]["root"]),
                    value=checked["local"].get(m["control"]["closure"]))
    require(source.identity(git, candidate, source=m["expected_tip"], baseline=m["baseline"]["master"]) == reviewed["source"],
            "native host candidate identity differs")
    source.clean_checkout(git, candidate)
    require(source.inventory(git, candidate, m["expected_tip"], verify_working=True) ==
            checked["graph"].get(reviewed["source_inventory"]), "native host candidate bytes differ")
    return git


def verify_configuration(checked, selected, maximum):
    from .host_audit import new_budget
    m = checked["manifest"]
    budget = new_budget({"read_bytes": maximum["read_bytes"], "staged_bytes": max(1, maximum["scratch_bytes"]),
                         "files": 20000, "seconds": maximum["seconds"]})
    return host_configuration.validate(tool(selected, "git"), Path(m["repo_root"]), candidate=Path(m["worktree_root"]),
        source_commit=m["expected_tip"], baseline=m["baseline"]["master"], graph=checked["local"],
        configuration_ref=checked["host_plan"]["configuration"], budget=budget)


def verify_code_in_parent(checked, selected, *, scratch, deadline, boundary):
    """Actual offline gh verification inside the parent's already owned tree.

    This does not use the off-host dispatcher and never invents teardown proof.
    The native parent must retain its lease through exit, EOF and zero children.
    """
    from datetime import datetime, timezone
    from . import process
    from .verifier import CHILD

    scratch = checked_root(scratch)
    graph, m = checked["graph"], checked["manifest"]
    q = m["qualification"]
    policy, reviewed, now = validate_trust(graph, q["policy"], q["review"])
    evidence.validate_code(graph, q["policy"], q["review"], q["certificate"], now=now)
    certificate = graph.get(q["certificate"])
    imported = authentication.validate_import_graph(graph, q["import"], p=policy, policy_ref=q["policy"],
        review_ref=q["review"], certificate_ref=q["certificate"], certificate=certificate, now=now, boundary=boundary)
    authentication.validate_revocations(graph.get(q["revocations"]), policy_sha256=q["policy"]["sha256"],
        certificate_sha256=q["certificate"]["sha256"], source_commit=reviewed["source"]["commit"],
        now=now, skew=policy["validity"]["clock_skew_seconds"])
    gh, python = tool(selected, "gh"), tool(selected, "python")
    runtime = selected["verifier_runtime"]
    runtime_root = checked_root(Path(runtime["root"]))
    require(python.is_relative_to(runtime_root), "offline verifier interpreter escaped reviewed runtime")
    expected_files = graph.get(runtime["files"])
    paths = environment.enumerate_files(runtime_root, excluded_directories=runtime["exclusions"])
    require(environment.files_manifest(runtime_root, paths, native_installation=True) == expected_files,
            "offline verifier runtime changed")
    command = authentication.verifier_command(graph, q["policy"], q["review"], q["certificate"], imported["attestation"], gh)
    request = {"command": command, "gh_sha256": selected["tools"]["gh"]["sha256"],
               "output": str(scratch / "stdout.json"), "stderr": str(scratch / "stderr.log"),
               "result": str(scratch / "exit.json")}
    ref = publish(scratch, "request.json", request)
    child = Path(m["control"]["root"]) / CHILD
    closure = checked["local"].get(m["control"]["closure"])
    pin = next(row for row in closure["files"] if row["path"] == CHILD)
    require(environment.file_identity(Path(m["control"]["root"]), CHILD)["sha256"] == pin["sha256"],
            "adopted offline verifier child changed")
    remaining = (timestamp(deadline) - datetime.now(timezone.utc)).total_seconds()
    require(remaining > 0, "offline verifier has no remaining host budget")
    with (scratch / "child.log").open("xb") as log:
        result = subprocess.run([str(python), "-I", "-S", "-B", str(child), str(scratch / ref["path"]), ref["sha256"]],
            executable=str(python), env=process.clean_environment(scratch=scratch, executable_paths=[python, gh]),
            cwd=Path(m["control"]["root"]), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            timeout=min(60, remaining), check=False)
    require(result.returncode == 0, "native offline signature verifier failed")
    with open_record(scratch, "stdout.json") as handle:
        raw = handle.read(2 * 1024**2 + 1)
    require(0 < len(raw) <= 2 * 1024**2, "offline verifier stdout outside bound")
    verified = authentication.validate_verified_output(raw, 0, expected_policy=policy,
        certificate=certificate, certificate_ref=q["certificate"], now=datetime.now(timezone.utc))
    require(environment.files_manifest(runtime_root, paths, native_installation=True) == expected_files and
            environment.enumerate_files(runtime_root, excluded_directories=runtime["exclusions"]) == paths,
            "offline verifier runtime changed during execution")
    graph.fresh()
    return {"certificate_sha256": q["certificate"]["sha256"], "verified_output_sha256": verified["verified_output_sha256"],
            "integration_eligible": False, "native_parent_completion_required": True}
