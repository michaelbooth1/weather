"""Read-only code certificate verification; authority inputs are explicit."""

from __future__ import annotations

from datetime import timedelta

from . import journal, junit
from .runner import validate_process
from .contracts import (CHECKS, PLATFORMS, Graph, fields, interval, inventory, pass_result, record,
                        remote_id, run, sequence, text, validate_trust)
from .coverage import (plan, validate_chunk, validate_collection_rules,
                       validate_cross_platform, validate_reviewed_changes)
from .records import (digest, integer, open_record, reference, relative_path,
                      require, timestamp)


def verify_blob(graph: Graph, ref, *, maximum=128 * 1024**2):
    graph.blob(ref, maximum=maximum)


def environment(value, platform):
    value = record(value, "qualification_environment_v2", {
        "platform", "architecture", "python", "powershell", "git", "distributions", "native_files"})
    require(value["platform"] == platform, "environment platform mismatch")
    require(value["architecture"] == "AMD64", "unapproved interpreter architecture")
    python = fields(value["python"], {"implementation", "version", "executable_sha256", "runtime_files"})
    require(python["implementation"] == "CPython", "unapproved interpreter")
    text(python["version"])
    require(len(python["version"].split(".")) == 3, "exact interpreter patch required")
    digest(python["executable_sha256"])
    reference(python["runtime_files"])
    native = fields(value["git"], {"version", "sha256"})
    text(native["version"])
    digest(native["sha256"])
    if platform == "windows":
        native = fields(value["powershell"], {"version", "sha256", "edition"})
        require(text(native["version"]).startswith("5.1.") and native["edition"] == "Desktop",
                "native Windows PowerShell 5.1 required")
        digest(native["sha256"])
    else:
        require(value["powershell"] is None, "Linux must not claim native Windows PowerShell")
    names = []
    for dist in sequence(value["distributions"], minimum=1):
        fields(dist, {"name", "version", "wheel", "installed_files"})
        names.append(text(dist["name"]).lower().replace("_", "-"))
        text(dist["version"])
        fields(dist["wheel"], {"filename", "sha256", "size"})
        relative_path(dist["wheel"]["filename"])
        require("/" not in dist["wheel"]["filename"] and dist["wheel"]["filename"].endswith(".whl"),
                "resolved wheel required")
        digest(dist["wheel"]["sha256"])
        integer(dist["wheel"]["size"], minimum=1)
        reference(dist["installed_files"])
    require(len(names) == len(set(names)), "duplicate installed distribution")
    reference(value["native_files"])
    return value


def witness(value, reviewed, platform, expected_environment):
    value = record(value, "qualification_source_witness_v2", {
        "source", "source_inventory_sha256", "test_inventory_sha256", "environment_sha256",
        "artifacts_sha256", "tracked_clean", "untracked_files", "imports", "platform", "data_absent", "checkout_root"})
    require(value["source"] == reviewed["source"] and value["platform"] == platform, "wrong tested source")
    for key in ("source_inventory", "test_inventory", "artifacts"):
        require(digest(value[key + "_sha256"]) == reviewed[key]["sha256"], "tested inventory mismatch")
    require(digest(value["environment_sha256"]) == expected_environment, "installed environment drift")
    require(value["tracked_clean"] is True and value["untracked_files"] == [] and value["data_absent"] is True,
            "source not a clean isolated checkout")
    journal.execution_root(value["checkout_root"], platform)
    imports = sequence(value["imports"], minimum=2)
    names = []
    for item in imports:
        fields(item, {"module", "root", "path", "sha256"})
        names.append(text(item["module"]))
        require(item["root"] == "candidate", "import escaped candidate checkout")
        require(relative_path(item["path"]).startswith(("src/weather/", "weather/")), "unexpected package path")
        digest(item["sha256"])
    require(len(names) == len(set(names)) and {"weather", "weather.paths"} <= set(names),
            "missing or duplicate import witness")
    return value


def _job(graph, ref, reviewed, p, expected_run, expected_plan, platform, now):
    job = record(graph.get(ref), "qualification_job_v2", {
        "status", "platform", "run", "job_id", "source", "plan_sha256", "environment_sha256",
        "started_at", "completed_at", "before", "after", "chunks", "checks", "collection"})
    pass_result(job["status"])
    require(job["platform"] == platform and job["run"] == expected_run and job["source"] == reviewed["source"],
            "job identity mismatch")
    remote_id(job["job_id"])
    require(digest(job["plan_sha256"]) == reviewed["plans"][platform]["sha256"], "unreviewed job plan")
    require(digest(job["environment_sha256"]) == reviewed["environments"][platform]["sha256"],
            "unreviewed job environment")
    skew = p["validity"]["clock_skew_seconds"]
    start, end = interval(job, now, skew)
    source_files = {item["path"]: item for item in graph.get(reviewed["source_inventory"])["files"]}
    checkout_roots = []
    for key in ("before", "after"):
        seen = witness(graph.get(job[key]), reviewed, platform, job["environment_sha256"])
        checkout_roots.append(seen["checkout_root"])
        for item in seen["imports"]:
            require(item["path"] in source_files and source_files[item["path"]]["sha256"] == item["sha256"],
                    "import bytes differ from source inventory")
    require(checkout_roots[0] == checkout_roots[1], "candidate root changed during job")
    collection = record(graph.get(job["collection"]), "qualification_collection_v2", {
        "platform", "run", "job_id", "exit_code", "node_chunks", "deselected", "errors", "ignored_files", "journal", "transcript", "process"})
    require(collection["platform"] == platform and collection["run"] == expected_run and
            collection["job_id"] == job["job_id"] and integer(collection["exit_code"]) == 0,
            "collection identity/failure")
    expected_nodes = [node["nodeid"] for chunk in expected_plan["chunks"] for node in chunk["nodes"]]
    collected_nodes = []
    for ref in sequence(collection["node_chunks"], minimum=1, maximum=2048):
        node_chunk = record(graph.get(ref), "qualification_collected_nodes_v2", {"nodes"})
        collected_nodes.extend(sequence(node_chunk["nodes"], minimum=1))
    require(collected_nodes == expected_nodes and collection["deselected"] == [] and
            collection["errors"] == [] and collection["ignored_files"] == expected_plan["uncollected_files"],
            "complete collection differs from reviewed plan")
    validate_process(graph, collection["process"], platform=platform, transcript=collection["transcript"])
    verify_blob(graph, collection["journal"])
    native_collection = journal.consume(graph.root, collection["journal"], candidate_root=checkout_roots[0],
                                        native_exit_code=collection["exit_code"], collect_only=True, platform=platform)
    require(native_collection["status"] == "PASS" and native_collection["collected"] == collected_nodes,
            "collection summary contradicts native collection journal")
    chunk_refs = sequence(job["chunks"], minimum=1)
    require(len(chunk_refs) == len(expected_plan["chunks"]), "missing or extra planned chunks")
    totals = {"pass": 0, "skip": 0, "xfail": 0}
    previous_end = start
    for chunk_ref, expected in zip(chunk_refs, expected_plan["chunks"], strict=True):
        chunk = graph.get(chunk_ref)
        counts = validate_chunk(chunk, expected, platform=platform, run=expected_run,
                                job_id=job["job_id"], now=now, skew=skew)
        chunk_start, chunk_end = interval(chunk, now, skew)
        require(previous_end <= chunk_start <= chunk_end <= end, "nonserial/out-of-job chunk interval")
        previous_end = chunk_end
        for name, count in counts.items():
            totals[name] += count
        for key in ("journal", "junit", "transcript"):
            verify_blob(graph, chunk[key])
        validate_process(graph, chunk["process"], platform=platform, transcript=chunk["transcript"])
        native = journal.consume(graph.root, chunk["journal"], candidate_root=checkout_roots[0],
                                 native_exit_code=chunk["exit_code"], platform=platform)
        require(all(chunk[key] == native[key] for key in native), "chunk summary contradicts native journal")
        junit.verify(graph.root, chunk["junit"], native["results"])
    checks = sequence(job["checks"], minimum=len(CHECKS), maximum=len(CHECKS))
    require([item.get("name") for item in checks if type(item) is dict] == list(CHECKS), "required checks absent")
    for check in checks:
        fields(check, {"name", "status", "exit_code", "started_at", "completed_at", "transcript", "process"})
        pass_result(check["status"])
        require(integer(check["exit_code"]) == 0, "repository check failed")
        check_start, check_end = interval(check, now, skew)
        require(start <= check_start <= check_end <= end, "repository check outside job")
        verify_blob(graph, check["transcript"])
        validate_process(graph, check["process"], platform=platform, transcript=check["transcript"])

    return job, totals


def validate_code(graph, policy_ref, review_ref, certificate_ref, *, now=None):
    """Structural/coverage proof only; caller must additionally authenticate bytes.

    Deliberately returns eligibility=false. A JSON certificate (including this
    function's output) is never a substitute for offline signature verification
    and the independently sealed remote-state import at consumption.
    """
    p, reviewed, now = validate_trust(graph, policy_ref, review_ref, now=now)
    cert = record(graph.get(certificate_ref), "code_qualification_v2", {
        "status", "policy_sha256", "review_sha256", "source", "run", "completed_at", "jobs"})
    pass_result(cert["status"])
    require(cert["policy_sha256"] == policy_ref["sha256"] and cert["review_sha256"] == review_ref["sha256"] and
            cert["source"] == reviewed["source"], "certificate policy/review/source mismatch")
    expected_run = run(cert["run"], p)
    plans = {}
    for platform in PLATFORMS:
        plans[platform] = plan(graph.get(reviewed["plans"][platform]), platform=platform, reviewed=reviewed, graph=graph)
        rules = validate_collection_rules(graph.get(plans[platform]["collection_rules"]))
        source_files = {item["path"]: item for item in graph.get(reviewed["source_inventory"])["files"]}
        baseline_files = {item["path"]: item for item in graph.get(reviewed["baseline_inventory"])["files"]}
        expected_rules = {path: item["sha256"] for path, item in source_files.items()
                          if path in {"pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"}
                          or path.endswith("/conftest.py")}
        require({item["path"]: item["sha256"] for item in rules["files"]} == expected_rules and
                len(rules["files"]) == len(expected_rules), "collection rules differ from tracked inventory")
        test_paths = {item["path"] for item in graph.get(reviewed["test_inventory"])["files"]}
        collected_paths = {node["nodeid"].partition("::")[0]
                           for chunk in plans[platform]["chunks"] for node in chunk["nodes"]}
        uncollected_paths = [item["path"] for item in plans[platform]["uncollected_files"]]
        require(len(uncollected_paths) == len(set(uncollected_paths)) and
                not collected_paths.intersection(uncollected_paths) and
                collected_paths.union(uncollected_paths) == test_paths,
                "test files absent from reviewed collection dispositions")
        changes = validate_reviewed_changes(graph.get(plans[platform]["reviewed_changes"]))
        require(changes["baseline"] == reviewed["source"]["baseline"] and
                changes["source"] == reviewed["source"]["commit"], "test review source mismatch")
        expected_changes = {}
        for path in sorted(set(source_files) | set(baseline_files)):
            relevant = (path.startswith("tests/") or path in {"pytest.ini", "pyproject.toml", "setup.cfg", "conftest.py"}
                        or path.endswith("/conftest.py"))
            if relevant and source_files.get(path) != baseline_files.get(path):
                expected_changes[path] = ("added" if path not in baseline_files else
                                          "deleted" if path not in source_files else
                                          "type_changed" if source_files[path]["mode"] != baseline_files[path]["mode"]
                                          else "modified")
        require({item["path"]: item["kind"] for item in changes["changes"]} == expected_changes,
                "test/collection changes lack explicit review")
        env = environment(graph.get(reviewed["environments"][platform]), platform)
        for ref in [env["python"]["runtime_files"], env["native_files"],
                    *(dist["installed_files"] for dist in env["distributions"])]:
            inventory(graph.get(ref), "qualification_runtime_files_v2")
    validate_cross_platform(plans)
    job_refs = sequence(cert["jobs"], minimum=2, maximum=2)
    jobs, counts = [], {}
    for platform, job_ref in zip(PLATFORMS, job_refs, strict=True):
        job, totals = _job(graph, job_ref, reviewed, p, expected_run, plans[platform], platform, now)
        jobs.append(job)
        counts[platform] = totals
    require(len({job["job_id"] for job in jobs}) == len(jobs), "same job reused for native platforms")
    completed = max(timestamp(job["completed_at"]) for job in jobs)
    require(timestamp(cert["completed_at"]) == completed, "certificate completion is not latest required job")
    require(now - completed <= timedelta(seconds=p["validity"]["code_seconds"]), "code certificate expired")
    graph.fresh()
    return {"status": "PASS", "eligible_to_arm": False, "authentication_required": True,
            "source": reviewed["source"], "run": expected_run, "counts": counts,
            "completed_at": cert["completed_at"]}
