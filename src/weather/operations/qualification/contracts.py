"""Closed v2 data contracts. None of these records is its own trust anchor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import re

from .records import (MAX_ITEMS, digest, distinct_paths, fields, identifier,
                      integer, open_record, read, reference, relative_path, require, timestamp)


PLATFORMS = ("windows", "linux")
CHECKS = ("compile", "agent_docs_audit", "roadmap_lint")
RESULTS = {"PASS", "FAIL", "BLOCKED", "CANCELLED", "INDETERMINATE"}
REMOTE_ID = re.compile(r"[1-9][0-9]{0,19}\Z")


def record(value, schema, names):
    value = fields(value, {"schema", *names}, label=schema)
    require(value["schema"] == schema, "unsupported record schema")
    return value


def sequence(value, *, minimum=0, maximum=MAX_ITEMS, label="list"):
    require(type(value) is list and minimum <= len(value) <= maximum, f"{label}: invalid list")
    return value


def remote_id(value):
    require(type(value) is str and REMOTE_ID.fullmatch(value) is not None, "invalid remote ID")
    return value


def text(value, *, maximum=1024):
    require(type(value) is str and 0 < len(value) <= maximum and
            all(ord(char) >= 32 for char in value), "invalid text")
    return value


def instant(value, now: datetime, skew: int):
    parsed = timestamp(value)
    require(parsed <= now + timedelta(seconds=skew), "future-dated evidence")
    return parsed


def interval(value, now, skew):
    start = instant(value["started_at"], now, skew)
    end = instant(value["completed_at"], now, skew)
    require(start <= end, "reversed evidence interval")
    return start, end


def pass_result(value):
    require(value in RESULTS, "unsupported phase result")
    require(value == "PASS", "dependency is not PASS")


def source(value):
    value = fields(value, {"commit", "tree", "baseline"}, label="source")
    for item in value.values():
        digest(item, git=True)
    require(value["commit"] != value["baseline"], "candidate must advance baseline")
    return value


def policy(value):
    value = record(value, "qualification_policy_v2", {
        "revision", "repository", "producer", "verifier", "platforms", "validity", "host"})
    identifier(value["revision"])
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text(value["repository"])) is not None,
            "invalid repository identity")
    producer = fields(value["producer"], {"workflow", "revision"})
    path = relative_path(producer["workflow"])
    require(path.startswith(".github/workflows/") and path.endswith(".yml"), "invalid producer workflow")
    digest(producer["revision"], git=True)
    verifier = fields(value["verifier"], {"gh_sha256", "trusted_root", "root_valid_until"})
    digest(verifier["gh_sha256"])
    reference(verifier["trusted_root"])
    timestamp(verifier["root_valid_until"])
    require(value["platforms"] == list(PLATFORMS), "both native platforms required in canonical order")
    validity = fields(value["validity"], {"code_seconds", "remote_seconds", "arming_seconds",
                                        "host_seconds", "clock_skew_seconds"})
    for name, maximum in (("code_seconds", 604800), ("remote_seconds", 86400),
                          ("arming_seconds", 3600), ("host_seconds", 1800),
                          ("clock_skew_seconds", 120)):
        integer(validity[name], minimum=0 if name == "clock_skew_seconds" else 1, maximum=maximum)
    host = fields(value["host"], {"profile", "probes_seconds", "audit_seconds", "metadata_seconds",
                                 "teardown_seconds", "probe_commit_bytes", "audit_commit_bytes",
                                 "audit_working_set_bytes", "minimum_disk_bytes", "mutation_delay_ms"})
    require(host["profile"] == "capture_s4u_split_v2", "unsupported host profile")
    for name, maximum in (("probes_seconds", 480), ("audit_seconds", 1200), ("metadata_seconds", 120),
                          ("teardown_seconds", 120), ("probe_commit_bytes", 512 * 1024**2),
                          ("audit_commit_bytes", 2 * 1024**3), ("audit_working_set_bytes", 1536 * 1024**2),
                          ("mutation_delay_ms", 5000)):
        integer(host[name], minimum=1, maximum=maximum)
    integer(host["minimum_disk_bytes"], minimum=50 * 1024**3)
    return value


def review(value, policy_sha256):
    value = record(value, "qualification_review_v2", {
        "policy_sha256", "source", "source_inventory", "test_inventory", "plans", "environments",
        "artifacts", "checks", "reviewer", "reviewed_at", "scope", "baseline_inventory"})
    require(digest(value["policy_sha256"]) == policy_sha256, "review policy mismatch")
    source(value["source"])
    for key in ("source_inventory", "test_inventory", "artifacts", "baseline_inventory"):
        reference(value[key])
    for key in ("plans", "environments"):
        fields(value[key], set(PLATFORMS))
        for ref in value[key].values():
            reference(ref)
    require(value["checks"] == list(CHECKS), "required repository checks missing")
    text(value["reviewer"])
    timestamp(value["reviewed_at"])
    require(value["scope"] in {"control_plane", "reliability_current_inputs"}, "unsupported acceptance scope")
    return value


def run(value, expected_policy):
    value = fields(value, {"repository", "run_id", "attempt", "event", "workflow", "revision"})
    require(value["repository"] == expected_policy["repository"], "wrong repository")
    for name in ("run_id", "attempt"):
        remote_id(value[name])
    require(value["event"] == "workflow_dispatch", "unsupported qualification event")
    for name in ("workflow", "revision"):
        require(value[name] == expected_policy["producer"][name], "unapproved producer revision/workflow")
    return value


def inventory(value, schema):
    value = record(value, schema, {"files"})
    files = sequence(value["files"], minimum=0 if schema == "qualification_artifacts_v2" else 1)
    distinct_paths([fields(item, {"path", "sha256", "size", "mode"})["path"] for item in files])
    for item in files:
        digest(item["sha256"])
        integer(item["size"])
        require(item["mode"] in {"100644", "100755"}, "unapproved file mode/link")
    return value


class Graph:
    """Read only a bounded acyclic graph beneath one externally chosen root."""

    def __init__(self, root: Path, *, maximum_records=4096, maximum_bytes=64 * 1024**2, maximum_blob_bytes=2 * 1024**3):
        self.root = root
        self.maximum_records = maximum_records
        self.maximum_bytes = maximum_bytes
        self.records = {}
        self.paths = {}
        self.total_bytes = 0
        self.maximum_blob_bytes = maximum_blob_bytes
        self.blob_bytes = 0
        self.blobs = {}

    def get(self, ref):
        reference(ref)
        key = ref["path"].casefold()
        previous = self.paths.get(key)
        require(previous is None or previous == ref, "graph path alias or conflicting reference")
        if key not in self.records:
            require(len(self.records) < self.maximum_records, "graph record limit exceeded")
            require(self.total_bytes + ref["size"] <= self.maximum_bytes, "graph byte limit exceeded")
            item = read(self.root, ref)
            self.records[key] = item
            self.paths[key] = dict(ref)
            self.total_bytes += ref["size"]
        return self.records[key].value

    def blob(self, ref, *, maximum=128 * 1024**2, refresh=False):
        fields(ref, {"path", "sha256", "size"})
        key = relative_path(ref["path"]).casefold()
        digest(ref["sha256"])
        integer(ref["size"], minimum=1, maximum=maximum)
        previous = self.paths.get(key)
        require(previous is None or previous == ref, "graph path alias or conflicting reference")
        if key in self.blobs and not refresh:
            return
        if key not in self.blobs:
            require(len(self.blobs) < 8192 and self.blob_bytes + ref["size"] <= self.maximum_blob_bytes,
                    "graph artifact limit exceeded")
        hasher, count = hashlib.sha256(), 0
        with open_record(self.root, ref["path"]) as handle:
            while block := handle.read(min(1024 * 1024, ref["size"] + 1 - count)):
                count += len(block)
                require(count <= ref["size"], "artifact grew or exceeds bound")
                hasher.update(block)
        require(count == ref["size"] and hasher.hexdigest() == ref["sha256"], "artifact bytes differ")
        if key not in self.blobs:
            self.blob_bytes += count
        self.blobs[key] = (dict(ref), maximum)
        self.paths[key] = dict(ref)

    def fresh(self):
        """Do not carry an earlier byte observation across a consumption boundary."""
        for ref, maximum in tuple(self.blobs.values()):
            self.blob(ref, maximum=maximum, refresh=True)
        for key, previous in self.records.items():
            current = read(self.root, self.paths[key])
            require(current.sha256 == previous.sha256, "retained graph changed")


def validate_trust(graph, policy_ref, review_ref, *, now=None):
    # Both references must come from reviewed/adopted local authority, not a certificate.
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and now.utcoffset() == timedelta(0), "UTC validation clock required")
    p = policy(graph.get(policy_ref))
    r = review(graph.get(review_ref), policy_ref["sha256"])
    require(now < timestamp(p["verifier"]["root_valid_until"]), "trusted root expired")
    instant(r["reviewed_at"], now, p["validity"]["clock_skew_seconds"])
    inventories = {}
    for key, schema in (("source_inventory", "qualification_source_inventory_v2"),
                        ("test_inventory", "qualification_test_inventory_v2"),
                        ("artifacts", "qualification_artifacts_v2"),
                        ("baseline_inventory", "qualification_source_inventory_v2")):
        inventories[key] = inventory(graph.get(r[key]), schema)
    all_files = {item["path"]: item for item in inventories["source_inventory"]["files"]}
    tests = {path: item for path, item in all_files.items() if path.startswith("tests/")}
    require(list(tests.values()) == inventories["test_inventory"]["files"], "incomplete tracked tests inventory")
    return p, r, now
