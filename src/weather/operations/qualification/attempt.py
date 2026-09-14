"""Typed split-attempt manifest and offline code-consumption gates.

Scheduler mutation, workload admission, native observations and Git mutation
belong to the adopted PowerShell parent. Parsing or even authenticating this
record never authorizes registration or adoption on its own.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from . import authentication, evidence, frozen, host, merge_tree
from .contracts import Graph, fields, record, sequence, text, validate_trust
from .records import checked_root, digest, identifier, integer, reference, require, timestamp


EVIDENCE = {
    "host_receipt": "host-receipt.json", "host_log": "host.log",
    "merge_receipt": "merge-receipt.json", "quiet_merge_report": "quiet-merge-report.json",
    "registration_intent": "registration-intent.json", "registration_receipt": "registration-receipt.json",
    "closure_receipt": "closure-receipt.json", "recovery_dispatch": "recovery-dispatch.json",
    "reconciliation_receipt": "reconciliation-receipt.json",
}
PHASES = ("probes", "audit", "metadata", "teardown")


def absolute(value):
    text(value, maximum=4096)
    path = Path(value)
    require(path.is_absolute(), "absolute local attempt path required")
    return path


def qualification(value):
    fields(value, {"root", "policy", "review", "certificate", "import", "revocations"})
    checked_root(absolute(value["root"]))
    for name in ("policy", "review", "certificate", "import", "revocations"):
        reference(value[name])
    return value


def host_plan(value, *, policy, reviewed):
    value = record(value, "qualification_host_plan_v2", {
        "source", "scope", "host_id", "principal_id", "not_before", "deadline", "local_day",
        "phase_seconds", "measurements", "configuration", "environment", "audit", "probes"})
    require(value["source"] == reviewed["source"] and value["scope"] == reviewed["scope"], "host plan source/scope differs")
    for name in ("host_id", "principal_id"):
        digest(value[name])
    require(timestamp(value["not_before"]) < timestamp(value["deadline"]), "host plan has no execution window")
    require(re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", text(value["local_day"])) is not None,
            "explicit local adoption day required")
    datetime.strptime(value["local_day"], "%Y-%m-%d")
    phases = fields(value["phase_seconds"], set(PHASES))
    for name in PHASES:
        integer(phases[name], minimum=1, maximum=policy["host"][name + "_seconds"])
    require((timestamp(value["deadline"]) - timestamp(value["not_before"])).total_seconds() <= sum(phases.values()),
            "host absolute deadline exceeds all reviewed phases")
    for name in ("measurements", "configuration", "environment", "probes"):
        reference(value[name])
    if value["scope"] == "reliability_current_inputs":
        reference(value["audit"])
    else:
        require(value["audit"] is None, "control-plane bootstrap cannot invent a current-data acceptance")
    return value


def manifest(value, *, actual_root, now=None):
    value = record(value, "weather_integration_attempt_manifest_v2", {
        "qualification_mode", "attempt_id", "created_at_local", "attempt_root", "repo_root", "worktree_root",
        "branch_ref", "expected_tip", "baseline", "authorization", "schedule", "orchestration", "evidence",
        "qualification", "control", "host"})
    require(value["qualification_mode"] == "split_v2", "unsupported qualification mode")
    attempt_id = identifier(value["attempt_id"])
    require(len(attempt_id) <= 48, "attempt ID exceeds Scheduler binding limit")
    actual_root = checked_root(actual_root)
    require(checked_root(absolute(value["attempt_root"])) == actual_root, "manifest namespace differs")
    production = checked_root(absolute(value["repo_root"]))
    candidate = checked_root(absolute(value["worktree_root"]))
    require(production != candidate and not candidate.is_relative_to(production / "src"), "candidate is not isolated")
    require(not actual_root.is_relative_to(candidate) and not candidate.is_relative_to(actual_root),
            "attempt namespace overlaps candidate source")
    require(not actual_root.is_relative_to(production) and not production.is_relative_to(actual_root),
            "split attempt namespace must be outside the production checkout")
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", text(value["branch_ref"])) is not None and
            ".." not in value["branch_ref"] and not value["branch_ref"].endswith("/"), "unsafe candidate ref")
    digest(value["expected_tip"], git=True)
    fields(value["baseline"], {"master", "origin_master"})
    baseline = digest(value["baseline"]["master"], git=True)
    require(value["baseline"]["origin_master"] == baseline and baseline != value["expected_tip"],
            "attempt baseline is not synchronized or does not advance")
    authorization = fields(value["authorization"], {"review_reference", "repair_class", "repair_of"})
    text(authorization["review_reference"], maximum=4096)
    require(authorization["repair_class"] in {"initial", "retry_unchanged", "schema_registry", "ownership_metadata",
                                              "orchestration_wrapper", "manual_reviewed_change"}, "unsupported repair class")
    require((authorization["repair_of"] is None) == (authorization["repair_class"] == "initial"),
            "repair must bind its immutable predecessor; shared lifecycle validates the actual claim")
    schedule = fields(value["schedule"], {"host_at_local", "merge_at_local", "host_task_name", "merge_task_name"})
    for phase, title in (("host", "Host"), ("merge", "Merge")):
        require(schedule[phase + "_task_name"] == "WeatherIntegration" + title + "_" + attempt_id,
                "attempt task name is not canonical")
        text(schedule[phase + "_at_local"])
    # Native TimeZoneInfo and the existing local-time reader must additionally
    # reject DST gaps/ambiguities on the actual Scheduler host.
    start, merge = [datetime.fromisoformat(schedule[key]) for key in ("host_at_local", "merge_at_local")]
    require(start.date() == merge.date() and 30 <= start.hour * 60 + start.minute < 540 and
            60 <= merge.hour * 60 + merge.minute < 220 and merge - start >= timedelta(minutes=34),
            "split host/merge schedule violates the existing quiet-window reserve")
    text(value["created_at_local"])
    fields(value["evidence"], set(EVIDENCE))
    for key, name in EVIDENCE.items():
        require(absolute(value["evidence"][key]) == actual_root / name, "noncanonical attempt evidence path")
    control = fields(value["control"], {"root", "closure", "git_policy"})
    control_root = checked_root(absolute(control["root"]))
    reference(control["closure"])
    reference(control["git_policy"])
    require(control_root == actual_root / "control" and not candidate.is_relative_to(control_root),
            "adopted control copy must have its unique attempt-local namespace")
    orchestration = value["orchestration"]
    require(type(orchestration) is dict and {"attempt_host", "attempt_merge", "quiet_merge", "contract"} <= set(orchestration),
            "required adopted orchestration bindings missing")
    for item in orchestration.values():
        fields(item, {"path", "sha256"})
        relative = absolute(item["path"]).relative_to(control_root).as_posix()
        require(frozen.selected(relative), "orchestration escaped the adopted control closure")
        digest(item["sha256"])
    q = qualification(value["qualification"])
    require(not Path(q["root"]).is_relative_to(candidate), "candidate owns its own qualification evidence")
    graph = Graph(Path(q["root"]))
    p, reviewed, _ = validate_trust(graph, q["policy"], q["review"], now=now)
    require(reviewed["source"]["commit"] == value["expected_tip"] and reviewed["source"]["baseline"] == baseline,
            "attempt source differs from the independently reviewed certificate graph")
    reference(value["host"])
    local = Graph(actual_root)
    planned = host_plan(local.get(value["host"]), policy=p, reviewed=reviewed)
    require(planned["local_day"] == start.date().isoformat(), "host plan belongs to another adoption day")
    closure = local.get(control["closure"])
    require(closure.get("baseline") == baseline, "control copy is not from the adopted baseline")
    config = merge_tree.configuration(local.get(planned["configuration"]))
    require(config["source"] == value["expected_tip"] and config["baseline"] == baseline,
            "configuration belongs to another candidate")
    if planned["audit"] is not None:
        audit = host.audit_plan(local.get(planned["audit"]))
        require(audit["candidate"] == value["worktree_root"] and audit["trusted_root"] == str(control_root) and
                audit["source_inventory"] == reviewed["source_inventory"] and audit["authority_root"] == q["root"],
                "host audit is not bound to the exact candidate and adopted control copy")
        require(Path(audit["receipt_root"]) == actual_root / "audit-receipts",
                "noncanonical host audit receipt namespace")
    return {"manifest": value, "policy": p, "review": reviewed, "host_plan": planned,
            "graph": graph, "local": local, "registration_eligible": False, "integration_eligible": False}


def consume_code(checked, *, boundary, verifier, now=None):
    """Actual native signature verification plus the complete retained graph.

    The adopted parent constructs the verifier implementation; downloaded data
    cannot choose a class, executable, plugin or network transport. The caller
    still owns native host proof and the final freshness/mutation boundary.
    """
    now = now or datetime.now(timezone.utc)
    require(boundary in {"arm", "launch", "merge"}, "unknown attempt consumption boundary")
    m, graph = checked["manifest"], checked["graph"]
    q = m["qualification"]
    p, reviewed, _ = validate_trust(graph, q["policy"], q["review"], now=now)
    evidence.validate_code(graph, q["policy"], q["review"], q["certificate"], now=now)
    certificate = graph.get(q["certificate"])
    imported = authentication.validate_import_graph(graph, q["import"], p=p, policy_ref=q["policy"],
        review_ref=q["review"], certificate_ref=q["certificate"], certificate=certificate, now=now, boundary=boundary)
    authentication.validate_revocations(graph.get(q["revocations"]), policy_sha256=q["policy"]["sha256"],
        certificate_sha256=q["certificate"]["sha256"], source_commit=reviewed["source"]["commit"],
        now=now, skew=p["validity"]["clock_skew_seconds"])
    native = verifier.verify(graph=graph, policy_ref=q["policy"], review_ref=q["review"],
                             certificate_ref=q["certificate"], bundle_ref=imported["attestation"])
    require(native["teardown_proved"] is True, "certificate verifier lacks native zero-child proof")
    verified = authentication.validate_verified_output(native["stdout"], native["exit_code"], expected_policy=p,
        certificate=certificate, certificate_ref=q["certificate"], now=now)
    graph.fresh()
    checked["local"].fresh()
    return {"certificate_sha256": q["certificate"]["sha256"], "verified_output_sha256": verified["verified_output_sha256"],
            "integration_eligible": False}
