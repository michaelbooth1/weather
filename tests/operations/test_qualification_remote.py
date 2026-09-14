"""A successful summary cannot hide contradictory raw authenticated API bytes."""

from copy import deepcopy

import pytest

from tests.operations.test_qualification_evidence import NOW, bundle
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.records import QualificationError
from weather.operations.qualification.remote import endpoints, validate_pages


def pages(b):
    expected = b.values["certificate"]["run"]
    paths = endpoints(expected)
    run = {"id": 123, "run_attempt": 1, "head_sha": expected["revision"], "event": "workflow_dispatch",
           "path": expected["workflow"] + "@master", "repository": {"full_name": "owner/repo"},
           "status": "completed", "conclusion": "success"}
    jobs = [{"id": job_id, "run_id": 123, "head_sha": expected["revision"], "name": "qualification-" + role,
             "status": "completed", "conclusion": "success", "run_url": "https://api.github.com" + paths["current"],
             "started_at": "2026-09-14T10:58:00Z", "completed_at": "2026-09-14T11:10:00Z"}
            for role, job_id in (("windows", 124), ("linux", 125), ("publisher", 126))]
    archive = b.blob("archive")
    artifacts = [{"id": 127, "name": "qualification-123-1", "expired": False, "expires_at": "2026-09-20T00:00:00Z",
                  "created_at": "2026-09-14T11:15:00Z", "workflow_run": {"id": 123, "head_sha": expected["revision"]},
                  "digest": "sha256:" + archive["sha256"], "size_in_bytes": archive["size"],
                  "url": "https://api.github.com/repos/owner/repo/actions/artifacts/127",
                  "archive_download_url": "https://api.github.com/repos/owner/repo/actions/artifacts/127/zip"}]
    return {"attempt": run, "current": deepcopy(run), "jobs": {"total_count": 3, "jobs": jobs},
            "artifacts": {"total_count": 1, "artifacts": artifacts}}, archive


def validate(b, values, archive):
    expected = b.values["certificate"]["run"]
    query = b.put("query", {"schema": "qualification_remote_query_v2", "run": expected,
                            "queried_at": "2026-09-14T11:30:00Z",
                            "pages": [{"kind": kind, "endpoint": endpoint, "http_status": 200,
                                       "body": b.put(kind, values[kind])}
                                      for kind, endpoint in endpoints(expected).items()]})
    return validate_pages(Graph(b.root), query, certificate=b.values["certificate"],
                          certificate_ref=b.refs["certificate"], artifact_ref=archive, now=NOW)


def test_actual_retained_pages_bind_native_jobs_and_archive(bundle):
    values, archive = pages(bundle)
    result = validate(bundle, values, archive)
    assert [job["id"] for job in result["jobs"]] == ["124", "125", "126"]
    assert result["artifact"]["archive"] == archive


@pytest.mark.parametrize("mutate", [
    lambda v: v["current"].__setitem__("run_attempt", 2),
    lambda v: v["current"].__setitem__("conclusion", "failure"),
    lambda v: v["attempt"].__setitem__("id", 123.0),
    lambda v: v["attempt"].__setitem__("head_sha", "a" * 40),
    lambda v: v["jobs"].__setitem__("total_count", 4),
    lambda v: v["jobs"]["jobs"].pop(),
    lambda v: v["jobs"]["jobs"][0].__setitem__("id", 998),
    lambda v: v["jobs"]["jobs"][0].__setitem__("conclusion", "cancelled"),
    lambda v: v["jobs"]["jobs"][0].__setitem__("completed_at", "2026-09-14T11:00:00Z"),
    lambda v: v["artifacts"]["artifacts"][0].__setitem__("digest", "sha256:" + "f" * 64),
    lambda v: v["artifacts"]["artifacts"][0].__setitem__("expired", True),
    lambda v: v["artifacts"]["artifacts"][0].__setitem__("name", "qualification-123-2"),
    lambda v: v["artifacts"]["artifacts"][0].__setitem__("archive_download_url", "https://example.com/payload"),
])
def test_summary_cannot_hide_later_attempt_missing_tail_or_substitution(bundle, mutate):
    values, archive = pages(bundle)
    mutate(values)
    with pytest.raises(QualificationError):
        validate(bundle, values, archive)
