"""Validate exact collected nodes and terminal reports against a reviewed plan."""

from __future__ import annotations

from .contracts import PLATFORMS, interval, record, remote_id, sequence, text
from .records import digest, fields, identifier, integer, reference, relative_path, require


def node_id(value):
    text(value, maximum=4096)
    path, separator, _ = value.partition("::")
    relative_path(path)
    require(path.startswith("tests/") and path.endswith(".py") and separator,
            "invalid collected node ID")
    return value


def plan(value, *, platform, reviewed, graph):
    value = record(value, "qualification_coverage_plan_v2", {
        "platform", "source_inventory_sha256", "test_inventory_sha256", "collection_rules",
        "reviewed_changes", "chunks", "uncollected_files"})
    require(value["platform"] == platform and platform in PLATFORMS, "wrong plan platform")
    for key in ("source_inventory", "test_inventory"):
        require(digest(value[key + "_sha256"]) == reviewed[key]["sha256"], "plan inventory mismatch")
    reference(value["collection_rules"])
    reference(value["reviewed_changes"])
    for item in sequence(value["uncollected_files"]):
        fields(item, {"path", "reason", "owner"})
        relative_path(item["path"])
        text(item["reason"])
        text(item["owner"])
    seen_chunks, seen_nodes = set(), set()
    expanded = []
    for chunk_ref in sequence(value["chunks"], minimum=1, maximum=2048):
        chunk = record(graph.get(chunk_ref), "qualification_chunk_plan_v2", {"id", "nodes"})
        expanded.append(chunk)
        require(identifier(chunk["id"]) not in seen_chunks, "duplicate planned chunk")
        seen_chunks.add(chunk["id"])
        for node in sequence(chunk["nodes"], minimum=1):
            fields(node, {"nodeid", "disposition", "reason", "owner", "covered_by"})
            name = node_id(node["nodeid"])
            require(name not in seen_nodes, "duplicate planned node")
            seen_nodes.add(name)
            disposition = node["disposition"]
            require(disposition in {"execute", "skip", "xfail"}, "unreviewed test disposition")
            if disposition == "execute":
                require(node["reason"] is None and node["owner"] is None and node["covered_by"] is None,
                        "executed test cannot carry an exception")
            else:
                text(node["reason"], maximum=4096)
                text(node["owner"])
                if disposition == "skip":
                    covered = fields(node["covered_by"], {"platform", "nodeid"})
                    require(covered["platform"] in {*PLATFORMS, "host"} and covered["platform"] != platform,
                            "skip needs distinct native execution")
                    node_id(covered["nodeid"])
                else:
                    require(node["covered_by"] is None, "expected failure is a retained limitation")
    return {**value, "chunks": expanded}


def validate_collection_rules(value):
    value = record(value, "qualification_collection_rules_v2", {"files", "arguments", "plugins"})
    # Arguments are metadata only. Execution uses the trusted runner's fixed invocation.
    require(value["arguments"] == ["tests", "--strict-config", "--strict-markers"],
            "collection overrides are not supported")
    for item in sequence(value["files"], minimum=1):
        fields(item, {"path", "sha256"})
        relative_path(item["path"])
        digest(item["sha256"])
    names = []
    for item in sequence(value["plugins"]):
        fields(item, {"distribution", "version", "sha256"})
        names.append(text(item["distribution"]))
        text(item["version"])
        digest(item["sha256"])
    require(len(names) == len(set(names)), "duplicate collection plugin")
    return value


def validate_reviewed_changes(value):
    value = record(value, "qualification_test_changes_v2", {"baseline", "source", "changes", "reviewer"})
    digest(value["baseline"], git=True)
    digest(value["source"], git=True)
    text(value["reviewer"])
    paths = []
    for change in sequence(value["changes"]):
        fields(change, {"path", "kind", "disposition"})
        paths.append(relative_path(change["path"]))
        require(change["kind"] in {"added", "modified", "deleted", "type_changed"}, "unsupported test change")
        text(change["disposition"])
    require(len(paths) == len({path.casefold() for path in paths}), "duplicate test change")
    return value


def validate_chunk(value, expected, *, platform, run, job_id, now, skew):
    value = record(value, "qualification_chunk_v2", {
        "id", "platform", "run", "job_id", "started_at", "completed_at", "exit_code", "status",
        "collected", "deselected", "collection_errors", "started", "completed", "results",
        "journal", "junit", "transcript", "process"})
    require(value["id"] == expected["id"] and value["platform"] == platform, "unexpected chunk")
    require(value["run"] == run and remote_id(value["job_id"]) == job_id, "mixed job/run attempt")
    interval(value, now, skew)
    require(value["status"] == "PASS" and integer(value["exit_code"]) == 0, "chunk did not finish successfully")
    reference(value["process"])
    nodes = [node["nodeid"] for node in expected["nodes"]]
    require(value["collected"] == nodes, "collection differs from reviewed nodes/order")
    require(value["deselected"] == [] and value["collection_errors"] == [], "hidden deselection/collection error")
    require(value["started"] == nodes and value["completed"] == nodes, "missing/duplicate test start or tail")
    results = sequence(value["results"], minimum=1)
    require(len(results) == len(nodes), "contradictory test totals")
    counts = {name: 0 for name in ("pass", "skip", "xfail")}
    for actual, planned in zip(results, expected["nodes"], strict=True):
        fields(actual, {"nodeid", "outcome", "reason", "phases"})
        require(actual["nodeid"] == planned["nodeid"], "test result order mismatch")
        outcome = {"execute": "pass", "skip": "skip", "xfail": "xfail"}[planned["disposition"]]
        require(actual["outcome"] == outcome and actual["reason"] == planned["reason"],
                "unreviewed skip/xfail or failed test")
        phases = sequence(actual["phases"], minimum=2, maximum=3)
        phase_names = []
        for phase in phases:
            fields(phase, {"when", "outcome", "wasxfail"})
            require(type(phase["wasxfail"]) is bool, "invalid xfail flag")
            require(phase["outcome"] in {"passed", "skipped", "failed"}, "invalid phase outcome")
            phase_names.append(phase["when"])
        require(phase_names in (["setup", "call", "teardown"], ["setup", "teardown"]),
                "missing/duplicate test phase")
        require(phases[-1] == {"when": "teardown", "outcome": "passed", "wasxfail": False},
                "test teardown did not pass")
        failures = [phase for phase in phases if phase["outcome"] == "failed"]
        skips = [phase for phase in phases if phase["outcome"] == "skipped"]
        require(not failures, "contradictory failed phase")
        if outcome == "pass":
            require(phase_names == ["setup", "call", "teardown"] and
                    all(phase["outcome"] == "passed" and not phase["wasxfail"] for phase in phases),
                    "pass lacks complete successful phases")
        else:
            require(len(skips) == 1 and skips[0]["wasxfail"] == (outcome == "xfail"),
                    "exception lacks corresponding native report")
            require(all(phase["wasxfail"] is False for phase in phases if phase not in skips),
                    "contradictory expected failure")
        counts[outcome] += 1
    for key in ("journal", "junit", "transcript"):
        # These are byte references, never commands or import paths.
        fields(value[key], {"path", "sha256", "size"})
        relative_path(value[key]["path"])
        digest(value[key]["sha256"])
        integer(value[key]["size"], minimum=1, maximum=128 * 1024**2)
    return counts


def validate_cross_platform(plans, host_nodes=()):
    indexed = {platform: {node["nodeid"]: node for chunk in p["chunks"] for node in chunk["nodes"]}
               for platform, p in plans.items()}
    for platform, nodes in indexed.items():
        for node in nodes.values():
            if node["disposition"] == "skip":
                target = node["covered_by"]
                if target["platform"] == "host":
                    require(target["nodeid"] in host_nodes, "unbound production-native coverage")
                else:
                    other = indexed[target["platform"]].get(target["nodeid"])
                    require(other is not None and other["disposition"] == "execute", "missing native execution")
            elif node["disposition"] == "execute":
                other_platform = "linux" if platform == "windows" else "windows"
                require(node["nodeid"] in indexed[other_platform], "portable node absent on other platform")
