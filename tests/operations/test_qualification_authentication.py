"""Authentication boundary tests; fixtures intentionally contain no signatures."""

from copy import deepcopy
from datetime import timedelta
import json

import pytest

from tests.operations.test_qualification_evidence import NOW, SOURCE, bundle
from weather.operations.qualification.authentication import (
    validate_import, validate_revocations, validate_verified_output, verifier_command,
)
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.records import QualificationError


def verified_output(b):
    p, cert = b.values["policy"], b.values["certificate"]
    return [{"attestation": {}, "verificationResult": {
        "signature": {"certificate": {
            "issuer": "https://token.actions.githubusercontent.com", "sourceRepositoryURI": "https://github.com/owner/repo",
            "sourceRepositoryDigest": p["producer"]["revision"], "buildSignerDigest": p["producer"]["revision"],
            "buildTrigger": "workflow_dispatch", "runnerEnvironment": "github-hosted",
            "runInvocationURI": "https://github.com/owner/repo/actions/runs/123/attempts/1",
            "buildSignerURI": "https://github.com/owner/repo/.github/workflows/qualification.yml@refs/heads/master"}},
        "verifiedTimestamps": [{"timestamp": "2026-09-14T11:03:00Z", "type": "tlog"}],
        "statement": {"_type": "https://in-toto.io/Statement/v1", "predicateType": "https://slsa.dev/provenance/v1",
                      "subject": [{"name": b.refs["certificate"]["path"], "digest": {"sha256": b.refs["certificate"]["sha256"]}}],
                      "predicate": {"source": cert["source"]}},
    }}]


def validate(b, value, exit_code=0):
    return validate_verified_output(json.dumps(value).encode(), exit_code, expected_policy=b.values["policy"],
        certificate=b.values["certificate"], certificate_ref=b.refs["certificate"], now=NOW)


def test_output_policy_binds_producer_and_actual_invocation(bundle):
    result = validate(bundle, verified_output(bundle))
    assert result["certificate_sha256"] == bundle.refs["certificate"]["sha256"]
    assert "eligible_to_arm" not in result


@pytest.mark.parametrize("name,value", [
    ("issuer", "https://example.com"), ("runnerEnvironment", "self-hosted"),
    ("sourceRepositoryDigest", SOURCE["commit"]), ("buildSignerDigest", SOURCE["commit"]),
    ("sourceRepositoryURI", "https://github.com/attacker/repo"),
    ("runInvocationURI", "https://github.com/owner/repo/actions/runs/123/attempts/2"),
    ("buildTrigger", "pull_request_target"),
    ("buildSignerURI", "https://github.com/owner/repo/.github/workflows/unapproved.yml@refs/heads/master"),
])
def test_workflow_predicate_cannot_override_authenticated_identity(bundle, name, value):
    output = verified_output(bundle)
    result = output[0]["verificationResult"]
    result["statement"]["predicate"][name] = result["signature"]["certificate"][name]
    result["signature"]["certificate"][name] = value
    with pytest.raises(QualificationError):
        validate(bundle, output)


@pytest.mark.parametrize("mutate", [
    lambda r: r.__setitem__("verifiedTimestamps", []),
    lambda r: r["verifiedTimestamps"][0].__setitem__("timestamp", "2026-09-14T10:00:00Z"),
    lambda r: r["verifiedTimestamps"][0].__setitem__("timestamp", "2026-09-14T13:00:00Z"),
    lambda r: r.__setitem__("signature", {}),
    lambda r: r["statement"].__setitem__("subject", []),
    lambda r: r["statement"]["subject"][0].__setitem__("name", "other.json"),
    lambda r: r["statement"]["subject"][0].__setitem__("digest", {"sha256": "0" * 64}),
])
def test_missing_crypto_output_or_subject_tampering(bundle, mutate):
    output = verified_output(bundle)
    mutate(output[0]["verificationResult"])
    with pytest.raises(QualificationError):
        validate(bundle, output)


def test_native_verifier_failure_and_junit_only_output_do_not_pass(bundle):
    with pytest.raises(QualificationError, match="signature verification failed"):
        validate(bundle, verified_output(bundle), exit_code=1)
    with pytest.raises(QualificationError):
        validate(bundle, [{"testsuite": {"failures": 0}}])
    with pytest.raises(QualificationError):
        validate(bundle, [])


def import_receipt(b):
    run = b.values["certificate"]["run"]
    page = b.put("remote-page", {"retained": "authenticated API bytes are interpreted by the trusted importer"})
    return {"schema": "qualification_import_v2", "policy_sha256": b.refs["policy"]["sha256"],
        "review_sha256": b.refs["review"]["sha256"], "certificate": b.refs["certificate"], "attestation": b.refs["root"],
        "run": run, "queried_at": "2026-09-14T11:30:00Z", "imported_at": "2026-09-14T11:31:00Z",
        "importer": "reviewed-controller", "status": "PASS", "remote_query": page,
        "query": {"raw_pages": [page, page, page], "status": "completed", "conclusion": "success",
                  "head_sha": run["revision"], "run_id": run["run_id"], "attempt": run["attempt"],
                  "workflow": run["workflow"], "event": run["event"], "repository": run["repository"],
                  "total_jobs": 3, "total_artifacts": 3},
        "jobs": [{"id": job_id, "role": role, "status": "completed", "conclusion": "success",
                  "run_id": run["run_id"], "attempt": run["attempt"]}
                 for job_id, role in (("124", "windows"), ("125", "linux"), ("126", "publisher"))],
        "artifact": {"id": "127", "run_id": run["run_id"], "attempt": run["attempt"], "expired": False,
                     "archive": page, "name": "qualification-123-1"}}


def consume(b, receipt, *, now=NOW, boundary="arm"):
    return validate_import(receipt, p=b.values["policy"], policy_ref=b.refs["policy"], review_ref=b.refs["review"],
        certificate_ref=b.refs["certificate"], certificate=b.values["certificate"], now=now, boundary=boundary)


def test_remote_state_age_at_each_consumption_boundary(bundle):
    receipt = import_receipt(bundle)
    assert consume(bundle, receipt)["status"] == "PASS"
    with pytest.raises(QualificationError, match="remote state expired"):
        consume(bundle, receipt, now=NOW + timedelta(hours=1), boundary="arm")
    assert consume(bundle, receipt, now=NOW + timedelta(hours=12), boundary="launch")
    with pytest.raises(QualificationError, match="remote state expired"):
        consume(bundle, receipt, now=NOW + timedelta(hours=24), boundary="merge")


@pytest.mark.parametrize("mutate", [
    lambda r: r.__setitem__("queried_at", "2026-09-14T13:00:00Z"),
    lambda r: r.__setitem__("queried_at", "2026-09-14T11:40:00Z"),
    lambda r: r["query"].__setitem__("head_sha", SOURCE["commit"]),
    lambda r: r["query"].__setitem__("conclusion", "failure"),
    lambda r: r["query"].__setitem__("total_jobs", 4),
    lambda r: r["jobs"][0].__setitem__("attempt", "2"),
    lambda r: r["jobs"][1].__setitem__("id", "124"),
    lambda r: r["artifact"].__setitem__("expired", True),
])
def test_remote_failure_or_mixed_attempt_overrides_local_success(bundle, mutate):
    receipt = import_receipt(bundle)
    mutate(receipt)
    with pytest.raises(QualificationError):
        consume(bundle, receipt)


@pytest.mark.parametrize("kind", ["policy", "certificate", "source"])
def test_adopted_local_revocation_is_immediate(bundle, kind):
    targets = {"policy": bundle.refs["policy"]["sha256"], "certificate": bundle.refs["certificate"]["sha256"],
               "source": SOURCE["commit"]}
    record = {"schema": "qualification_revocations_v2", "revision": "r2", "updated_at": "2026-09-14T11:59:00Z",
              "revoked": [{"kind": kind, "digest": targets[kind], "reason": "reviewed revocation"}]}
    with pytest.raises(QualificationError, match="locally revoked"):
        validate_revocations(record, policy_sha256=targets["policy"], certificate_sha256=targets["certificate"],
                             source_commit=targets["source"], now=NOW, skew=120)


def test_command_refuses_changed_native_executable_before_launch(bundle, tmp_path):
    executable = tmp_path / "gh.exe"
    executable.write_bytes(b"not an approved executable")
    with pytest.raises(QualificationError, match="native verifier bytes changed"):
        verifier_command(Graph(bundle.root), bundle.refs["policy"], bundle.refs["review"], bundle.refs["certificate"],
                         bundle.refs["root"], executable, now=NOW)
