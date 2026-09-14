"""Interpret complete retained GitHub API pages, including exact run attempts.

Only the separately reviewed authenticated importer may seal these pages. This
module proves consistency with their actual bytes; it does not authenticate an
arbitrary downloaded JSON document or execute fields found in one.
"""

from __future__ import annotations

from .contracts import PLATFORMS, fields, record, remote_id, sequence
from .records import digest, integer, require, timestamp


ROLES = ("windows", "linux", "publisher")


def api_id(value):
    # GitHub's REST JSON IDs are integers; our retained authority records use
    # decimal strings. Reject bools/floats before the explicit representation change.
    return remote_id(str(integer(value, minimum=1, maximum=2**63 - 1)))


def endpoints(run):
    base = "/repos/" + run["repository"] + "/actions/runs/" + remote_id(run["run_id"])
    exact = base + "/attempts/" + remote_id(run["attempt"])
    return {"attempt": exact, "current": base,
            "jobs": exact + "/jobs?per_page=100&page=1",
            "artifacts": base + "/artifacts?per_page=100&page=1"}


def _run(value, expected):
    require(type(value) is dict, "missing remote run")
    require(api_id(value.get("id")) == expected["run_id"] and
            api_id(value.get("run_attempt")) == expected["attempt"], "remote run/attempt changed")
    require(value.get("head_sha") == expected["revision"] and value.get("event") == expected["event"],
            "remote producer source/event differs")
    path = value.get("path")
    require(type(path) is str and path.partition("@")[0] == expected["workflow"], "remote workflow differs")
    require(type(value.get("repository")) is dict and
            value["repository"].get("full_name") == expected["repository"], "remote repository differs")
    require(value.get("status") == "completed" and value.get("conclusion") == "success",
            "remote run is not successful")
    return value


def _complete_page(value, key, *, maximum):
    require(type(value) is dict, "invalid remote listing")
    total = integer(value.get("total_count"), minimum=1, maximum=maximum)
    values = sequence(value.get(key), minimum=1, maximum=maximum)
    require(total == len(values), "remote listing is truncated")
    ids = [api_id(item.get("id")) for item in values if type(item) is dict]
    require(len(ids) == len(values) and len(set(ids)) == len(ids), "duplicate/malformed remote listing")
    return values


def validate_pages(graph, query_ref, *, certificate, certificate_ref, artifact_ref, now):
    """Require observed API bytes to agree with the sealed importer summary."""
    query = record(graph.get(query_ref), "qualification_remote_query_v2", {"run", "pages", "queried_at"})
    expected = certificate["run"]
    require(query["run"] == expected, "query run differs from certificate")
    timestamp(query["queried_at"])
    paths = endpoints(expected)
    pages = sequence(query["pages"], minimum=4, maximum=4)
    require([item.get("kind") for item in pages if type(item) is dict] == list(paths),
            "remote query is incomplete or reordered")
    observed = {}
    for item in pages:
        fields(item, {"kind", "endpoint", "http_status", "body"})
        require(item["endpoint"] == paths[item["kind"]] and
                integer(item["http_status"]) == 200, "wrong authenticated endpoint or response status")
        observed[item["kind"]] = graph.get(item["body"])
    for kind in ("attempt", "current"):
        _run(observed[kind], expected)
    raw_jobs = _complete_page(observed["jobs"], "jobs", maximum=3)
    by_name = {job.get("name"): job for job in raw_jobs}
    require(set(by_name) == {"qualification-" + role for role in ROLES}, "unexpected remote job set")
    result_jobs = []
    for role in ROLES:
        job = by_name["qualification-" + role]
        require(api_id(job.get("run_id")) == expected["run_id"] and job.get("head_sha") == expected["revision"],
                "remote job source/run differs")
        require(job.get("status") == "completed" and job.get("conclusion") == "success",
                "required remote job did not succeed")
        require(job.get("run_url") == "https://api.github.com" + paths["current"], "remote job URL mismatch")
        started, finished = timestamp(job.get("started_at")), timestamp(job.get("completed_at"))
        require(started <= finished <= now, "invalid remote job completion interval")
        job_id = api_id(job["id"])
        if role in PLATFORMS:
            native = graph.get(certificate["jobs"][PLATFORMS.index(role)])
            require(native["job_id"] == job_id and started <= timestamp(native["started_at"]) <=
                    timestamp(native["completed_at"]) <= finished, "certificate uses another job or test interval")
        else:
            require(timestamp(certificate["completed_at"]) <= finished, "publisher completed before tests")
        result_jobs.append({"id": job_id, "role": role, "status": "completed", "conclusion": "success",
                            "run_id": expected["run_id"], "attempt": expected["attempt"]})
    raw_artifacts = _complete_page(observed["artifacts"], "artifacts", maximum=10)
    name = "qualification-" + expected["run_id"] + "-" + expected["attempt"]
    selected = [item for item in raw_artifacts if item.get("name") == name]
    require(len(selected) == 1, "missing or ambiguous exact-attempt artifact")
    item = selected[0]
    require(item.get("expired") is False and timestamp(item.get("expires_at")) > now, "remote artifact expired")
    remote_run = item.get("workflow_run")
    require(type(remote_run) is dict and api_id(remote_run.get("id")) == expected["run_id"] and
            remote_run.get("head_sha") == expected["revision"], "artifact belongs to another source/run")
    created = timestamp(item.get("created_at"))
    require(timestamp(certificate["completed_at"]) <= created <= timestamp(query["queried_at"]),
            "artifact creation differs from completed attempt")
    require(item.get("digest") == "sha256:" + digest(artifact_ref["sha256"]) and
            integer(item.get("size_in_bytes"), minimum=1) == artifact_ref["size"],
            "authenticated artifact digest/size mismatch")
    artifact_id = api_id(item["id"])
    artifact_path = "/repos/" + expected["repository"] + "/actions/artifacts/" + artifact_id
    require(item.get("url") == "https://api.github.com" + artifact_path and
            item.get("archive_download_url") == "https://api.github.com" + artifact_path + "/zip",
            "artifact retrieval endpoint mismatch")
    graph.blob(artifact_ref, maximum=512 * 1024**2)
    return {"query": {"raw_pages": [page["body"] for page in pages], "status": "completed", "conclusion": "success",
                       "head_sha": expected["revision"], "run_id": expected["run_id"], "attempt": expected["attempt"],
                       "workflow": expected["workflow"], "event": expected["event"], "repository": expected["repository"],
                       "total_jobs": len(raw_jobs), "total_artifacts": len(raw_artifacts)},
            "jobs": result_jobs,
            "artifact": {"id": artifact_id, "name": name, "run_id": expected["run_id"], "attempt": expected["attempt"],
                         "expired": False, "archive": artifact_ref},
            "queried_at": query["queried_at"], "certificate_sha256": certificate_ref["sha256"]}
