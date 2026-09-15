"""Publisher decisions consume data only and actual authenticated job state."""

from __future__ import annotations

from datetime import datetime, timezone

from . import producer, remote
from .contracts import Graph, PLATFORMS, run, validate_trust
from .records import decode, publish_raw, require, timestamp


def require_publishing_jobs(raw, *, expected_run, certificate_jobs, publisher_job_id, now):
    page = decode(raw)
    jobs = remote._complete_page(page, "jobs", maximum=3)
    indexed = {item.get("name"): item for item in jobs}
    require(set(indexed) == {"qualification-windows", "qualification-linux", "qualification-publisher"}, "unexpected publisher job set")
    for platform, expected in zip(PLATFORMS, certificate_jobs, strict=True):
        actual = indexed["qualification-" + platform]
        require(remote.api_id(actual.get("id")) == expected["job_id"] and
                remote.api_id(actual.get("run_id")) == expected_run["run_id"] and
                actual.get("head_sha") == expected_run["revision"] and actual.get("status") == "completed" and
                actual.get("conclusion") == "success", "native job did not complete in this exact producer attempt")
        require(timestamp(actual.get("started_at")) <= timestamp(expected["started_at"]) <=
                timestamp(expected["completed_at"]) <= timestamp(actual.get("completed_at")) <= now,
                "native job interval is not observed remote completion")
    publisher = indexed["qualification-publisher"]
    require(remote.api_id(publisher.get("id")) == publisher_job_id and
            remote.api_id(publisher.get("run_id")) == expected_run["run_id"] and
            publisher.get("head_sha") == expected_run["revision"] and publisher.get("status") == "in_progress" and
            publisher.get("conclusion") is None, "this is not the selected running publisher")


def seal(graph, *, client, policy_ref, review_ref, run_identity, job_refs, publisher_job_id):
    policy, _, now = validate_trust(graph, policy_ref, review_ref)
    run(run_identity, policy)
    require(client.repository == policy["repository"], "publisher authenticated repository differs")
    path = remote.endpoints(run_identity)["jobs"]
    raw = client.json(path)
    require_publishing_jobs(raw, expected_run=run_identity, certificate_jobs=[graph.get(ref) for ref in job_refs],
                            publisher_job_id=publisher_job_id, now=datetime.now(timezone.utc))
    # The API response is retained for review; the importer separately requires
    # the publisher's completed-success state after upload and attestation.
    publish_raw(graph.root, "publisher-observed-jobs.json", raw)
    graph.fresh()
    return producer.certificate(graph, policy_ref=policy_ref, review_ref=review_ref,
                                run_identity=run_identity, job_refs=job_refs)
