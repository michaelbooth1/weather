"""Trusted source/environment witnesses and one complete serial native job.

Run only from the independently pinned producer checkout. Preparatory discovery
is separate from the reviewed plan; this producer refuses newly observed nodes,
dependencies or source bytes instead of approving them as it runs.
"""

from __future__ import annotations

from pathlib import Path

from . import coverage, environment, evidence, process, source
from .contracts import CHECKS, Graph, fields, inventory, remote_id, run, validate_trust
from .records import checked_root, publish, read, require, timestamp


def verify_environment(graph, reviewed_ref, *, platform, bindings, wheel_root, wheels):
    """Rehash every reviewed runtime/package/native file before and after a job.

    Bindings come from the trusted runner installation profile, never S. The
    interpreter and site-directory complete inventories include unexpected files;
    the selected OS-native prerequisites are the independently reviewed subset.
    """
    expected = evidence.environment(graph.get(reviewed_ref), platform)
    fields(bindings, {"interpreter", "installation", "native", "site_roots", "interpreter_exclusions"})
    roots = {key: checked_root(Path(bindings[key])) for key in ("interpreter", "installation", "native")}
    sites = [checked_root(Path(p)) for p in bindings["site_roots"]]
    distributions = environment.discover_distributions(sites)
    wheel_map = environment.bind_wheels(distributions, wheel_root, wheels)
    expected_names = {item["name"] for item in expected["distributions"]}
    require(set(distributions) == expected_names, "unexpected or missing installed dependency")
    installed_paths = set()
    for item in expected["distributions"]:
        dist = distributions[item["name"]]
        require(dist.version == item["version"] and wheel_map[item["name"]] == item["wheel"], "dependency version/wheel differs")
        actual = environment.installed_distribution(dist, roots["installation"])
        require(actual == graph.get(item["installed_files"]), "installed dependency files differ")
        installed_paths.update(file["path"] for file in actual["files"])
    # RECORDs must account for every dependency-site file, including extra .pth,
    # injected modules and cached bytecode. No candidate code has run yet.
    for site in sites:
        for path in environment.enumerate_files(site):
            relative = environment.rooted_path(roots["installation"], site / path)
            require(relative in installed_paths, "dependency site contains an unrecorded file")
    interpreter_files = inventory(graph.get(expected["python"]["runtime_files"]), "qualification_runtime_files_v2")
    actual_paths = environment.enumerate_files(roots["interpreter"], excluded_directories=bindings["interpreter_exclusions"])
    require(actual_paths == [item["path"] for item in interpreter_files["files"]], "interpreter installation topology differs")
    require(environment.files_manifest(roots["interpreter"], actual_paths, native_installation=True) == interpreter_files, "interpreter runtime bytes differ")
    native_files = inventory(graph.get(expected["native_files"]), "qualification_runtime_files_v2")
    require(environment.files_manifest(roots["native"], [item["path"] for item in native_files["files"]], native_installation=True) == native_files,
            "reviewed native prerequisite bytes differ")
    return expected


def witness(runner, graph, reviewed, *, expected_environment, environment_bindings, wheel_root, wheels):
    source.clean_checkout(runner.tool("git"), runner.candidate)
    actual_source = source.identity(runner.tool("git"), runner.candidate, source=reviewed["source"]["commit"],
                                    baseline=reviewed["source"]["baseline"])
    require(actual_source == reviewed["source"], "source identity differs")
    actual_inventory = source.inventory(runner.tool("git"), runner.candidate, actual_source["commit"], verify_working=True)
    require(actual_inventory == graph.get(reviewed["source_inventory"]), "candidate source inventory differs")
    env = verify_environment(graph, expected_environment, platform=runner.platform, bindings=environment_bindings,
                             wheel_root=wheel_root, wheels=wheels)
    require(runner.executables["python"]["sha256"] == env["python"]["executable_sha256"] and
            runner.executables["git"]["sha256"] == env["git"]["sha256"], "selected executable differs from reviewed environment")
    if runner.platform == "windows":
        require(runner.executables["powershell"]["sha256"] == env["powershell"]["sha256"], "selected native PowerShell differs")
    import_result = runner.execute("imports")
    import_ref = runner.blob(import_result["directory"] / "imports.json")
    # Native import output is deliberately an object record, never Python code.
    imports = read(runner.output, import_ref).value["imports"]
    observed = {"schema": "qualification_source_witness_v2", "source": actual_source, "platform": runner.platform,
                "source_inventory_sha256": reviewed["source_inventory"]["sha256"],
                "test_inventory_sha256": reviewed["test_inventory"]["sha256"],
                "environment_sha256": expected_environment["sha256"], "artifacts_sha256": reviewed["artifacts"]["sha256"],
                "tracked_clean": True, "untracked_files": [], "data_absent": True,
                "checkout_root": str(runner.candidate), "imports": imports}
    evidence.witness(observed, reviewed, runner.platform, expected_environment["sha256"])
    actual_files = {item["path"]: item["sha256"] for item in actual_inventory["files"]}
    require(all(actual_files.get(item["path"]) == item["sha256"] for item in imports), "import witness differs from actual Git bytes")
    source.clean_checkout(runner.tool("git"), runner.candidate)
    return observed


def run_job(runner, *, policy_ref, review_ref, run_identity, job_id, environment_bindings, wheel_root, wheels):
    graph = Graph(runner.output)
    policy, reviewed, now = validate_trust(graph, policy_ref, review_ref)
    run(run_identity, policy)
    remote_id(job_id)
    expected_plan = coverage.plan(graph.get(reviewed["plans"][runner.platform]), platform=runner.platform, reviewed=reviewed, graph=graph)
    rules = coverage.validate_collection_rules(graph.get(expected_plan["collection_rules"]))
    require(rules["plugins"] == [], "first trusted producer supports only its explicit built-in observer")
    require(reviewed["artifacts"] and graph.get(reviewed["artifacts"])["files"] == [],
            "external artifact installations need a reviewed binding before this producer can use them")
    # Baseline inventory is independently checked, not merely a list in review.
    baseline_inventory = source.inventory(runner.tool("git"), runner.candidate, reviewed["source"]["baseline"])
    require(baseline_inventory == graph.get(reviewed["baseline_inventory"]), "reviewed baseline tree inventory differs")
    start = process.utc()
    kwargs = dict(expected_environment=reviewed["environments"][runner.platform],
                  environment_bindings=environment_bindings, wheel_root=wheel_root, wheels=wheels)
    before = publish(runner.output, runner.platform + "-before.json", witness(runner, graph, reviewed, **kwargs))
    native_collection = runner.collect()
    collected = native_collection["summary"]["collected"]
    expected_nodes = [node["nodeid"] for chunk in expected_plan["chunks"] for node in chunk["nodes"]]
    require(collected == expected_nodes, "complete native collection differs from reviewed ordered coverage")
    node_pages = []
    for offset in range(0, len(collected), 128):
        node_pages.append(publish(runner.output, f"{runner.platform}-nodes-{offset:06d}.json",
                                  {"schema": "qualification_collected_nodes_v2", "nodes": collected[offset:offset + 128]}))
    collection = publish(runner.output, runner.platform + "-collection.json", {
        "schema": "qualification_collection_v2", "platform": runner.platform, "run": run_identity, "job_id": job_id,
        "exit_code": native_collection["exit_code"], "node_chunks": node_pages, "deselected": [], "errors": [],
        "ignored_files": expected_plan["uncollected_files"], "journal": native_collection["journal"],
        "transcript": native_collection["transcript"], "process": native_collection["process"]})
    chunks = [runner.chunk(expected, run=run_identity, job_id=job_id) for expected in expected_plan["chunks"]]
    checks = []
    for name in CHECKS:
        result = runner.execute(name)
        checks.append({"name": name, "status": "PASS", **{key: result[key] for key in
                       ("exit_code", "started_at", "completed_at", "transcript", "process")}})
    after = publish(runner.output, runner.platform + "-after.json", witness(runner, graph, reviewed, **kwargs))
    value = {"schema": "qualification_job_v2", "status": "PASS", "platform": runner.platform,
             "run": run_identity, "job_id": job_id, "source": reviewed["source"],
             "plan_sha256": reviewed["plans"][runner.platform]["sha256"],
             "environment_sha256": reviewed["environments"][runner.platform]["sha256"],
             "started_at": start, "completed_at": process.utc(), "before": before, "after": after,
             "chunks": chunks, "checks": checks, "collection": collection}
    graph.fresh()
    return publish(runner.output, runner.platform + "-job.json", value)


def certificate(graph, *, policy_ref, review_ref, run_identity, job_refs):
    policy, reviewed, _ = validate_trust(graph, policy_ref, review_ref)
    run(run_identity, policy)
    require(len(job_refs) == 2, "both complete native jobs required")
    values = [graph.get(ref) for ref in job_refs]
    value = {"schema": "code_qualification_v2", "status": "PASS", "policy_sha256": policy_ref["sha256"],
             "review_sha256": review_ref["sha256"], "source": reviewed["source"], "run": run_identity,
             "completed_at": max((item["completed_at"] for item in values), key=timestamp), "jobs": job_refs}
    # Validate before publication with a new temporary graph root record. This
    # function only seals code evidence; authenticated publisher state remains
    # a separate required boundary, including actual remote native job IDs.
    proposed = publish(graph.root, "proposed-code-certificate.json", value)
    evidence.validate_code(Graph(graph.root), policy_ref, review_ref, proposed)
    return publish(graph.root, "code-certificate.json", value)
