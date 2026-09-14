"""Decisions exercise real graph validation, with an independently pinned review."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest

from weather.operations.qualification import records
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.evidence import validate_code


NOW = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
SOURCE = {"commit": "a" * 40, "tree": "b" * 40, "baseline": "c" * 40}
NODE = "tests/test_example.py::test_example"


class Bundle:
    def __init__(self, root):
        self.root, self.counter, self.refs, self.values = root, 0, {}, {}

    def put(self, key, value):
        self.counter += 1
        ref = records.publish(self.root, f"{self.counter}-{key}.json", value)
        self.refs[key], self.values[key] = ref, deepcopy(value)
        return ref

    def blob(self, key, raw=b"native test transcript\n"):
        self.counter += 1
        name = f"{self.counter}-{key}.txt"
        (self.root / name).write_bytes(raw)
        return {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}

    def replace(self, key, mutate):
        value = deepcopy(self.values[key])
        mutate(value)
        return self.put(key, value)

    def validate(self, **kwargs):
        return validate_code(Graph(self.root), self.refs["policy"], self.refs["review"],
                             self.refs["certificate"], now=kwargs.get("now", NOW))


def native_blobs(b, platform, *, collect_only=False):
    checkout = "C:/fixture/source" if platform == "windows" else "/fixture/source"
    events = [{"event": "session_start", "root": checkout, "invocation": ["tests"]},
              {"event": "collected_node", "nodeid": NODE}, {"event": "collection_finish", "count": 1},
              {"event": "test_start", "nodeid": NODE},
              *({"event": "test_phase", "nodeid": NODE, "when": when, "outcome": "passed",
                 "wasxfail": False, "reason": None} for when in ("setup", "call", "teardown")),
              {"event": "test_finish", "nodeid": NODE},
              {"event": "session_finish", "exit_code": 0, "tests_collected": 1, "tests_failed": 0}]
    if collect_only:
        events = events[:3] + events[-1:]
    raw = b"".join((json.dumps({"ordinal": number, "monotonic_ns": number, **event}) + "\n").encode()
                   for number, event in enumerate(events, 1))
    xml = (b'<testsuites><testsuite tests="1" failures="0" errors="0" skipped="0">'
           b'<testcase classname="tests.test_example" name="test_example"/></testsuite></testsuites>')
    return b.blob(platform + "-journal", raw), b.blob(platform + "-junit", xml)


def native_process(b, platform, transcript):
    native = {"completed": True, "failure": None, "exit_code": 0, "teardown_proved": True,
              "elapsed_ms": 60000, "peak_working_set_bytes": 10485760, "maximum_sample_gap_ms": 100,
              "resource_samples": 600, "minimum_disk_bytes": 10 * 1024**3,
              "started_at": "2026-09-14T11:00:00Z", "completed_at": "2026-09-14T11:01:00Z"}
    if platform == "windows":
        native.update(peak_private_bytes=10485760, native_peak_commit_bytes=10485760, system_commit_basis_points=4000)
    return b.put(platform + "-process", {"schema": "qualification_process_v2", "platform": platform,
                 "argv_sha256": "f" * 64, "native": native, "transcript": transcript,
                 "limits": {"seconds": 1200, "teardown_seconds": 30, "memory_bytes": 4 * 1024**3,
                            "output_bytes": 128 * 1024**2, "minimum_disk_bytes": 2 * 1024**3}})


def native_check(b, platform, check):
    transcript = b.blob(f"{platform}-{check}")
    return {"name": check, "status": "PASS", "exit_code": 0, "started_at": "2026-09-14T11:00:00Z",
            "completed_at": "2026-09-14T11:02:00Z", "transcript": transcript,
            "process": native_process(b, platform, transcript)}


@pytest.fixture
def bundle(tmp_path):
    b = Bundle(tmp_path)
    root = b.put("root", {"trustedRoot": "fixture only; structural tests do not authenticate"})
    p = {
        "schema": "qualification_policy_v2", "revision": "test-1", "repository": "owner/repo",
        "producer": {"workflow": ".github/workflows/qualification.yml", "revision": "d" * 40},
        "verifier": {"gh_sha256": "e" * 64, "trusted_root": root, "root_valid_until": "2026-10-01T00:00:00Z"},
        "platforms": ["windows", "linux"],
        "validity": {"code_seconds": 604800, "remote_seconds": 86400, "arming_seconds": 3600,
                     "host_seconds": 1800, "clock_skew_seconds": 120},
        "host": {"profile": "capture_s4u_split_v2", "probes_seconds": 480, "audit_seconds": 1200,
                 "metadata_seconds": 120, "teardown_seconds": 120, "probe_commit_bytes": 512 * 1024**2,
                 "audit_commit_bytes": 2 * 1024**3, "audit_working_set_bytes": 1536 * 1024**2,
                 "minimum_disk_bytes": 50 * 1024**3, "mutation_delay_ms": 5000},
    }
    policy = b.put("policy", p)
    source_files = [{"path": path, "sha256": "f" * 64, "size": 10, "mode": "100644"} for path in
                    ("pytest.ini", "src/weather/paths.py", "tests/test_example.py", "weather/__init__.py")]
    source = b.put("source", {"schema": "qualification_source_inventory_v2", "files": source_files})
    tests = b.put("tests", {"schema": "qualification_test_inventory_v2", "files": [source_files[2]]})
    artifacts = b.put("artifacts", {"schema": "qualification_artifacts_v2", "files": []})
    file_inventory = b.put("runtime", {"schema": "qualification_runtime_files_v2", "files": [
        {"path": "runtime.bin", "sha256": "f" * 64, "size": 10, "mode": "100644"}]})
    changes = b.put("changes", {"schema": "qualification_test_changes_v2", "baseline": SOURCE["baseline"],
                               "source": SOURCE["commit"], "changes": [], "reviewer": "fixture reviewer"})
    rules = b.put("rules", {"schema": "qualification_collection_rules_v2", "files": [
        {"path": "pytest.ini", "sha256": "f" * 64}],
        "arguments": ["tests", "--strict-config", "--strict-markers"], "plugins": []})
    envs, plans = {}, {}
    for platform in ("windows", "linux"):
        envs[platform] = b.put(f"{platform}-environment", {
            "schema": "qualification_environment_v2", "platform": platform, "architecture": "AMD64",
            "python": {"implementation": "CPython", "version": "3.11.9", "executable_sha256": "f" * 64,
                       "runtime_files": file_inventory},
            "powershell": ({"version": "5.1.22621.1", "edition": "Desktop", "sha256": "f" * 64}
                           if platform == "windows" else None),
            "git": {"version": "2.49.0", "sha256": "f" * 64}, "native_files": file_inventory,
            "distributions": [{"name": "pytest", "version": "8.4.2", "installed_files": file_inventory,
                               "wheel": {"filename": "pytest-8.4.2-py3-none-any.whl", "sha256": "f" * 64, "size": 100}}],
        })
        plans[platform] = b.put(f"{platform}-plan", {
            "schema": "qualification_coverage_plan_v2", "platform": platform,
            "source_inventory_sha256": source["sha256"], "test_inventory_sha256": tests["sha256"],
            "collection_rules": rules, "reviewed_changes": changes, "uncollected_files": [],
            "chunks": [b.put(f"{platform}-chunk-plan", {"schema": "qualification_chunk_plan_v2", "id": "chunk-1",
                       "nodes": [{"nodeid": NODE, "disposition": "execute", "reason": None, "owner": None,
                                  "covered_by": None}]})],
        })
    review = b.put("review", {"schema": "qualification_review_v2", "policy_sha256": policy["sha256"],
        "source": SOURCE, "source_inventory": source, "baseline_inventory": source, "test_inventory": tests, "plans": plans,
        "environments": envs, "artifacts": artifacts, "checks": ["compile", "agent_docs_audit", "roadmap_lint"],
        "reviewer": "fixture reviewer", "reviewed_at": "2026-09-14T10:00:00Z", "scope": "control_plane"})
    run = {"repository": p["repository"], "run_id": "123", "attempt": "1", "event": "workflow_dispatch",
           **p["producer"]}
    jobs = []
    for platform, job_id in (("windows", "124"), ("linux", "125")):
        journal_ref, junit_ref = native_blobs(b, platform)
        collection_journal, _ = native_blobs(b, platform, collect_only=True)
        transcript = b.blob(f"{platform}-transcript")
        process_ref = native_process(b, platform, transcript)
        witness = b.put(f"{platform}-witness", {"schema": "qualification_source_witness_v2", "source": SOURCE,
            "source_inventory_sha256": source["sha256"], "test_inventory_sha256": tests["sha256"],
            "environment_sha256": envs[platform]["sha256"], "artifacts_sha256": artifacts["sha256"],
            "tracked_clean": True, "untracked_files": [], "data_absent": True, "platform": platform,
            "checkout_root": "C:/fixture/source" if platform == "windows" else "/fixture/source",
            "imports": [{"module": module, "root": "candidate", "path": path, "sha256": "f" * 64}
                        for module, path in (("weather", "weather/__init__.py"),
                                             ("weather.paths", "src/weather/paths.py"))]})
        collection = b.put(f"{platform}-collection", {"schema": "qualification_collection_v2",
            "platform": platform, "run": run, "job_id": job_id, "exit_code": 0,
            "node_chunks": [b.put(f"{platform}-collected-nodes", {"schema": "qualification_collected_nodes_v2", "nodes": [NODE]})],
            "deselected": [], "errors": [], "ignored_files": [], "journal": collection_journal, "transcript": transcript, "process": process_ref})
        chunk = b.put(f"{platform}-chunk", {"schema": "qualification_chunk_v2", "id": "chunk-1",
            "platform": platform, "run": run, "job_id": job_id, "started_at": "2026-09-14T11:00:00Z",
            "completed_at": "2026-09-14T11:01:00Z", "exit_code": 0, "status": "PASS", "collected": [NODE],
            "deselected": [], "collection_errors": [], "started": [NODE], "completed": [NODE],
            "results": [{"nodeid": NODE, "outcome": "pass", "reason": None, "phases": [
                {"when": when, "outcome": "passed", "wasxfail": False} for when in ("setup", "call", "teardown")]}],
            "journal": journal_ref, "junit": junit_ref,
            "transcript": transcript, "process": process_ref})
        jobs.append(b.put(f"{platform}-job", {"schema": "qualification_job_v2", "status": "PASS",
            "platform": platform, "run": run, "job_id": job_id, "source": SOURCE,
            "plan_sha256": plans[platform]["sha256"], "environment_sha256": envs[platform]["sha256"],
            "started_at": "2026-09-14T10:59:00Z", "completed_at": "2026-09-14T11:02:00Z",
            "before": witness, "after": witness, "chunks": [chunk], "collection": collection,
            "checks": [native_check(b, platform, check) for check in ("compile", "agent_docs_audit", "roadmap_lint")]}))
    b.put("certificate", {"schema": "code_qualification_v2", "status": "PASS", "policy_sha256": policy["sha256"],
        "review_sha256": review["sha256"], "source": SOURCE, "run": run,
        "completed_at": "2026-09-14T11:02:00Z", "jobs": jobs})
    return b


def rebind_job(b, *, chunk_mutation=None, job_mutation=None, witness_mutation=None, collection_mutation=None):
    replacements = {}
    for key, mutate in (("chunk", chunk_mutation), ("witness", witness_mutation), ("collection", collection_mutation)):
        if mutate:
            replacements[key] = b.replace(f"windows-{key}", mutate)
    def update(job):
        for key, ref in replacements.items():
            if key == "chunk":
                job["chunks"] = [ref]
            elif key == "witness":
                job["after"] = ref
            else:
                job[key] = ref
        if job_mutation:
            job_mutation(job)
    job = b.replace("windows-job", update)
    b.replace("certificate", lambda cert: cert["jobs"].__setitem__(0, job))


def test_complete_structural_graph_still_requires_authentication(bundle):
    result = bundle.validate()
    assert result["status"] == "PASS"
    assert result["eligible_to_arm"] is False
    assert result["authentication_required"] is True
    assert result["counts"] == {platform: {"pass": 1, "skip": 0, "xfail": 0} for platform in ("windows", "linux")}


@pytest.mark.parametrize("field,value", [
    ("source", {**SOURCE, "commit": "0" * 40}), ("review_sha256", "0" * 64),
    ("policy_sha256", "0" * 64), ("status", "FAIL"), ("status", "BLOCKED"),
    ("completed_at", "2026-09-14T11:03:00Z"), ("jobs", []), ("unknown", True),
])
def test_certificate_cannot_rebind_authority(bundle, field, value):
    bundle.replace("certificate", lambda cert: cert.__setitem__(field, value))
    with pytest.raises(records.QualificationError):
        bundle.validate()


@pytest.mark.parametrize("field,value", [("workflow", ".github/workflows/other.yml"),
    ("revision", "0" * 40), ("event", "pull_request"), ("run_id", 123), ("attempt", "0")])
def test_wrong_producer_or_untyped_run_id(bundle, field, value):
    bundle.replace("certificate", lambda cert: cert["run"].__setitem__(field, value))
    with pytest.raises(records.QualificationError):
        bundle.validate()


@pytest.mark.parametrize("mutate", [
    lambda c: c.__setitem__("completed", []),
    lambda c: c.__setitem__("started", [NODE, NODE]),
    lambda c: c.__setitem__("collected", []),
    lambda c: c.__setitem__("deselected", [NODE]),
    lambda c: c.__setitem__("collection_errors", ["native dependency missing"]),
    lambda c: c.__setitem__("exit_code", True),
    lambda c: c.__setitem__("status", "CANCELLED"),
    lambda c: c["run"].__setitem__("attempt", "2"),
    lambda c: c["results"][0].__setitem__("outcome", "skip"),
    lambda c: c["results"][0].__setitem__("phases", []),
    lambda c: c["results"][0]["phases"][-1].__setitem__("outcome", "failed"),
    lambda c: c.__setitem__("completed_at", "2026-09-14T12:01:00Z"),
])
def test_forged_junit_or_incomplete_native_reports_do_not_pass(bundle, mutate):
    rebind_job(bundle, chunk_mutation=mutate)
    with pytest.raises(records.QualificationError):
        bundle.validate()


@pytest.mark.parametrize("mutate", [
    lambda j: j.__setitem__("chunks", []),
    lambda j: j.__setitem__("chunks", j["chunks"] * 2),
    lambda j: j.__setitem__("checks", j["checks"][:-1]),
    lambda j: j.__setitem__("environment_sha256", "0" * 64),
    lambda j: j.__setitem__("job_id", "125"),
    lambda j: j.__setitem__("platform", "linux"),
])
def test_job_aggregation_is_complete_and_native(bundle, mutate):
    rebind_job(bundle, job_mutation=mutate)
    with pytest.raises(records.QualificationError):
        bundle.validate()


@pytest.mark.parametrize("mutate", [
    lambda w: w.__setitem__("tracked_clean", False),
    lambda w: w.__setitem__("data_absent", False),
    lambda w: w.__setitem__("untracked_files", ["injected.py"]),
    lambda w: w["imports"][0].__setitem__("root", "production"),
    lambda w: w["imports"][0].__setitem__("sha256", "0" * 64),
    lambda w: w["source"].__setitem__("tree", "0" * 40),
])
def test_import_and_post_run_source_witness_is_bound(bundle, mutate):
    rebind_job(bundle, witness_mutation=mutate)
    with pytest.raises(records.QualificationError):
        bundle.validate()


def test_full_collection_cannot_hide_extra_node(bundle):
    extra = bundle.put("extra-nodes", {"schema": "qualification_collected_nodes_v2", "nodes": [NODE + "_hidden"]})
    rebind_job(bundle, collection_mutation=lambda c: c["node_chunks"].append(extra))
    with pytest.raises(records.QualificationError, match="complete collection"):
        bundle.validate()


def test_artifact_bytes_are_checked_not_just_reported(bundle):
    ref = bundle.values["windows-chunk"]["junit"]
    (bundle.root / ref["path"]).write_bytes(b"<testsuite failures='0'/>\n")
    with pytest.raises(records.QualificationError, match="artifact"):
        bundle.validate()


def test_expired_code_and_trust_are_rejected(bundle):
    with pytest.raises(records.QualificationError, match="expired"):
        bundle.validate(now=NOW + timedelta(days=8))
    with pytest.raises(records.QualificationError, match="trusted root expired"):
        bundle.validate(now=NOW + timedelta(days=20))


def test_graph_limits_and_conflicting_aliases(bundle):
    graph = Graph(bundle.root, maximum_records=1)
    graph.get(bundle.refs["policy"])
    with pytest.raises(records.QualificationError, match="record limit"):
        graph.get(bundle.refs["review"])
    graph = Graph(bundle.root)
    graph.get(bundle.refs["policy"])
    with pytest.raises(records.QualificationError, match="conflicting reference"):
        graph.get({**bundle.refs["policy"], "sha256": "0" * 64})
    with pytest.raises(records.QualificationError, match="byte limit"):
        Graph(bundle.root, maximum_bytes=1).get(bundle.refs["policy"])


@pytest.mark.parametrize("field,value", [
    ("teardown_proved", False), ("completed", False), ("failure", "lost child"),
    ("exit_code", 7), ("resource_samples", 0), ("maximum_sample_gap_ms", 1001),
    ("native_peak_commit_bytes", 8 * 1024**3), ("minimum_disk_bytes", 1),
])
def test_passing_journal_cannot_hide_native_process_failure(bundle, field, value):
    b = bundle
    process_ref = b.values["windows-chunk"]["process"]
    process_record = deepcopy(Graph(b.root).get(process_ref))
    process_record["native"][field] = value
    replacement = b.put("broken-native-process", process_record)
    rebind_job(b, chunk_mutation=lambda item: item.update(process=replacement))
    with pytest.raises(records.QualificationError):
        b.validate()


def test_no_process_record_is_not_legacy_v2_success(bundle):
    rebind_job(bundle, chunk_mutation=lambda item: item.pop("process"))
    with pytest.raises(records.QualificationError):
        bundle.validate()
