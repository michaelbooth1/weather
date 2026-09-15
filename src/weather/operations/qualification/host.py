"""Fixed host audit orchestration and cumulative evidence checks.

The native adopted parent owns admission, S4U identity and acceptance. These
functions build only its three fixed audit commands and check actual outputs;
they cannot turn an audit result into integration authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import host_audit
from .contracts import Graph, fields, inventory, record, sequence
from .records import checked_root, digest, integer, reference, require, timestamp


AUDIT_MODULES = ("__init__", "contracts", "records", "inputs", "settlement_inputs", "host_audit", "offline_guard")
AUDIT_PHASES = ("stage", "audit", "current")


def audit_plan(value):
    """An independently pinned local plan, never a command from a certificate."""
    value = record(value, "qualification_host_audit_plan_v2", {
        "candidate", "trusted_root", "trusted_modules", "sites", "authority_root", "source_inventory",
        "inputs_root", "roots", "output", "receipt_root", "maximum", "labels", "ledgers", "markets", "deadline", "child_sha256"})
    roots = {key: checked_root(Path(value[key])) for key in
             ("candidate", "trusted_root", "authority_root", "inputs_root", "output", "receipt_root")}
    # Candidate execution must not have a write grant over any trusted or
    # canonical source directory, including through a parent alias.
    for writable in (roots["inputs_root"], roots["output"], roots["receipt_root"]):
        for protected in (roots["candidate"], roots["trusted_root"], roots["authority_root"]):
            require(not protected.is_relative_to(writable) and not writable.is_relative_to(protected),
                    "host audit output overlaps protected source")
    from itertools import combinations
    for left, right in combinations((roots["inputs_root"], roots["output"], roots["receipt_root"]), 2):
        require(not left.is_relative_to(right) and not right.is_relative_to(left),
                "audit input/output/parent receipt roots overlap")
    fields(value["trusted_modules"], set(AUDIT_MODULES))
    for pin in value["trusted_modules"].values():
        digest(pin)
    for site in sequence(value["sites"], minimum=1, maximum=4):
        site = checked_root(Path(site))
        require(not site.is_relative_to(roots["candidate"]) and
                not site.is_relative_to(roots["inputs_root"]) and not site.is_relative_to(roots["output"]) and
                not site.is_relative_to(roots["receipt_root"]),
                "audit dependencies overlap candidate or output")
    reference(value["source_inventory"])
    inventory(Graph(roots["authority_root"]).get(value["source_inventory"]), "qualification_source_inventory_v2")
    sources = host_audit.source_roots(value["roots"])
    for live in sources.roots.values():
        require(all(not path.is_relative_to(live) and not live.is_relative_to(path)
                    for path in roots.values()), "host audit roots overlap mutable evidence")
    sources.locate(value["labels"])
    sources.locate(value["ledgers"])
    markets = sequence(value["markets"], minimum=1, maximum=128)
    from .records import relative_path
    require(len(markets) == len(set(markets)) and markets == sorted(markets), "noncanonical market inventory")
    for market in markets:
        require("/" not in relative_path(market), "invalid market directory")
    host_audit.limits(value["maximum"])
    digest(value["child_sha256"])
    timestamp(value["deadline"])
    return value


def audit_request(plan, phase, *, preparation=None, computation=None, now=None):
    """Fixed requests with one absolute deadline and cumulative read accounting."""
    plan = audit_plan(plan)
    require(phase in AUDIT_PHASES, "unsupported host audit phase")
    now = now or datetime.now(timezone.utc)
    remaining = int((timestamp(plan["deadline"]) - now).total_seconds())
    require(remaining > 0, "host audit absolute budget exhausted")
    maximum = {**plan["maximum"], "seconds": min(plan["maximum"]["seconds"], remaining)}
    common = {key: plan[key] for key in ("candidate", "trusted_root", "trusted_modules", "sites", "authority_root",
                                       "source_inventory", "inputs_root", "roots", "output")}
    common.update({"phase": phase, "maximum": maximum,
                   "trusted_root": str(Path(plan["trusted_root"]) / "src/weather/operations/qualification")})
    if phase == "stage":
        require(preparation is None and computation is None, "staging cannot reuse earlier evidence")
        return {**common, **{key: plan[key] for key in ("labels", "ledgers", "markets")}}
    reference(preparation)
    prepared = host_audit.preparation(Graph(Path(plan["inputs_root"])), preparation)
    require(prepared["preparation"]["labels_identity"] == plan["labels"] and
            prepared["preparation"]["ledger_root_identity"] == plan["ledgers"] and
            prepared["preparation"]["markets"] == plan["markets"], "staged input topology differs from host plan")
    if phase == "audit":
        require(computation is None, "audit cannot reuse an earlier computation")
        return {**common, "preparation": preparation}
    computed = audit_computation(Graph(Path(plan["output"])), computation, prepared, preparation, maximum)
    return {**common, "preparation": preparation, "computation": computation, "previously_read": computed["read_bytes"]}


def audit_computation(graph, ref, prepared, preparation_ref, maximum):
    value = record(graph.get(ref), "qualification_audit_computation_v2", {
        "started_at", "completed_at", "preparation_sha256", "inputs_sha256", "audit", "consumer",
        "counts", "read_bytes", "current_validation_required"})
    require(timestamp(prepared["completed_at"]) <= timestamp(value["started_at"]) <= timestamp(value["completed_at"]),
            "audit preceded complete staging")
    require(value["preparation_sha256"] == preparation_ref["sha256"] and
            value["inputs_sha256"] == prepared["inputs"]["sha256"] and
            value["current_validation_required"] is True, "audit input binding differs")
    integer(value["read_bytes"], minimum=prepared["read_bytes"], maximum=maximum["read_bytes"])
    fields(value["counts"], {"row_count", "semantic_status", "blocked_rows"})
    require(value["counts"]["row_count"] == prepared["preparation"]["counts"]["merged_rows"], "audit full row count differs")
    # Raw output rehashing is charged to the same cumulative budget. The parent
    # carries the returned count into the final current-input validation.
    budget = host_audit.new_budget(maximum, previously_read=value["read_bytes"])
    payload = host_audit.read_payload(graph.root, value["audit"], budget)
    require(host_audit.validate_counts(payload, value["counts"]["row_count"]) == value["counts"],
            "audit raw output contradicts computation")
    host_audit.read_payload(graph.root, value["consumer"], budget)
    return {**value, "read_bytes": budget.observed_bytes}


def audit_completion(plan, preparation_ref, computation_ref, current_ref):
    """Check all three actual phase outputs; retain semantic BLOCK outcomes."""
    plan = audit_plan(plan)
    inputs = Graph(Path(plan["inputs_root"]))
    outputs = Graph(Path(plan["output"]))
    prepared = host_audit.preparation(inputs, preparation_ref)
    computed = audit_computation(outputs, computation_ref, prepared, preparation_ref, plan["maximum"])
    receipts = Graph(Path(plan["receipt_root"]))
    current = record(receipts.get(current_ref), "qualification_audit_current_v2", {
        "preparation_sha256", "inputs_sha256", "computation_sha256", "started_at", "completed_at", "read_bytes"})
    require(current["preparation_sha256"] == preparation_ref["sha256"] and
            current["inputs_sha256"] == prepared["inputs"]["sha256"] and
            current["computation_sha256"] == computation_ref["sha256"], "final current validation belongs to another audit")
    require(timestamp(prepared["completed_at"]) <= timestamp(computed["started_at"]) <=
            timestamp(computed["completed_at"]) <= timestamp(current["started_at"]) <=
            timestamp(current["completed_at"]) <= timestamp(plan["deadline"]), "host audit phase interval/deadline differs")
    require((timestamp(current["completed_at"]) - timestamp(prepared["started_at"])).total_seconds() <=
            plan["maximum"]["seconds"], "combined staging/audit/current envelope exceeded")
    integer(current["read_bytes"], minimum=computed["read_bytes"], maximum=plan["maximum"]["read_bytes"])
    inputs.fresh()
    outputs.fresh()
    receipts.fresh()
    return {"preparation": preparation_ref, "computation": computation_ref, "current": current_ref,
            "inputs": prepared["inputs"], "counts": computed["counts"], "read_bytes": current["read_bytes"],
            "started_at": prepared["started_at"], "completed_at": current["completed_at"], "integration_eligible": False}


def run_audit(plan, *, scratch):
    """Actual serial stage -> isolated candidate audit -> current validation.

    The native parent contains this controller and all descendants together.
    Timeout or any exception propagates; it cannot publish completion and the
    native parent must still kill/drain the entire tree before releasing lease.
    """
    import hashlib
    import subprocess
    import sys

    from .records import open_record, publish

    plan = audit_plan(plan)
    scratch = checked_root(scratch)
    first = audit_request(plan, "stage")
    prepared = host_audit.stage(output=Path(plan["inputs_root"]), roots=plan["roots"], labels=plan["labels"],
                                ledgers=plan["ledgers"], markets=plan["markets"], maximum=first["maximum"])
    request = audit_request(plan, "audit", preparation=prepared)
    request_ref = publish(scratch, "candidate-audit-request.json", request)
    relative = "scripts/ops/qualification_host_child.py"
    with open_record(Path(plan["trusted_root"]), relative) as handle:
        raw = handle.read(2 * 1024**2 + 1)
    require(len(raw) <= 2 * 1024**2 and hashlib.sha256(raw).hexdigest() == plan["child_sha256"],
            "fixed candidate audit launcher drift")
    child = Path(plan["trusted_root"]) / relative
    # The outer controller already has a credential-free environment; pass an
    # explicit allowlist again so neither CI identity nor ambient controls leak.
    import os
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE", "PATHEXT", "PATH", "TEMP", "TMP", "TMPDIR",
        "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "WEATHER_INTEGRATION_TEST_OFFLINE": "1",
                "PSModuleAnalysisCachePath": os.devnull})
    # Candidate temporary files belong only to its writable output namespace.
    for key in ("TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
        env[key] = plan["output"]
    remaining = (timestamp(plan["deadline"]) - datetime.now(timezone.utc)).total_seconds()
    require(remaining > 0, "audit preparation exhausted the absolute deadline")
    native = subprocess.run([sys.executable, "-I", "-S", "-B", str(child),
                             str(scratch / request_ref["path"]), request_ref["sha256"]],
                            executable=sys.executable, cwd=plan["candidate"], env=env, stdin=subprocess.DEVNULL,
                            timeout=remaining, check=False)
    require(native.returncode == 0, "isolated candidate audit failed")
    # Read a fixed output path, not a child-selected external reference.
    with open_record(Path(plan["output"]), "audit-computation.json") as handle:
        raw = handle.read(2 * 1024**2 + 1)
    require(0 < len(raw) <= 2 * 1024**2, "audit computation record exceeds metadata bound")
    computation = {"path": "audit-computation.json", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    current_request = audit_request(plan, "current", preparation=prepared, computation=computation)
    current = host_audit.revalidate(input_graph=Graph(Path(plan["inputs_root"])), preparation_ref=prepared,
        roots=plan["roots"], maximum=current_request["maximum"], previously_read=current_request["previously_read"])
    prepared_value = Graph(Path(plan["inputs_root"])).get(prepared)
    current_ref = publish(Path(plan["receipt_root"]), "audit-current.json", {"schema": "qualification_audit_current_v2",
        "preparation_sha256": prepared["sha256"], "inputs_sha256": prepared_value["inputs"]["sha256"],
        "computation_sha256": computation["sha256"], **current})
    result = audit_completion(plan, prepared, computation, current_ref)
    return publish(Path(plan["receipt_root"]), "audit-pipeline.json", {"schema": "qualification_audit_pipeline_v2", **result})
