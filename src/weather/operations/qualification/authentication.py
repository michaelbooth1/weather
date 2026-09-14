"""Pinned offline GitHub provenance checks and sealed remote-state freshness.

The workflow runs at its approved producer revision and explicitly checks out
the reviewed candidate in unprivileged jobs. OIDC source/signer digests therefore
bind the producer, while the signed certificate graph binds the tested source.
No downloaded executable, shell command, URL, or predicate grants authority.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
from pathlib import Path

from .contracts import (fields, instant, pass_result, record, remote_id, run, sequence,
                        validate_trust)
from .evidence import validate_code, verify_blob
from .records import (MAX_RECORD_BYTES, decode, digest, identifier, integer,
                      open_record, reference, require, timestamp)


PREDICATE = "https://slsa.dev/provenance/v1"
ISSUER = "https://token.actions.githubusercontent.com"


def verifier_command(graph, policy_ref, review_ref, certificate_ref, bundle_ref, gh_path, *, now=None):
    """Return a fixed native argv for an adopted contained launcher, never a shell.

    The launcher must keep this pinned executable/closure immutable, run within
    its existing Windows Job, bound output to 2 MiB, scrub credentials and use an
    empty GH_CONFIG_DIR. The command is strictly offline. Preparing argv alone
    is non-authorizing; validate_verified_output consumes its actual result.
    """
    p, reviewed, now = validate_trust(graph, policy_ref, review_ref, now=now)
    # Validate all certificate bytes before the native parser sees its subject.
    validate_code(graph, policy_ref, review_ref, certificate_ref, now=now)
    require(Path(gh_path).is_absolute(), "verifier executable must be an absolute adopted path")
    gh_path = Path(gh_path)
    hasher, count = hashlib.sha256(), 0
    with open_record(gh_path.parent, gh_path.name) as handle:
        while block := handle.read(1024 * 1024):
            count += len(block)
            require(count <= 256 * 1024**2, "native verifier exceeds reviewed bound")
            hasher.update(block)
    require(hasher.hexdigest() == p["verifier"]["gh_sha256"], "native verifier bytes changed")
    root_ref = p["verifier"]["trusted_root"]
    for ref in (bundle_ref, root_ref):
        reference(ref)
        require(Path(ref["path"]).suffix in {".json", ".jsonl"}, "unsupported offline trust file")
        verify_blob(graph, ref, maximum=MAX_RECORD_BYTES)
    return [str(gh_path), "attestation", "verify", str(graph.root / certificate_ref["path"]),
            "--repo", p["repository"], "--bundle", str(graph.root / bundle_ref["path"]),
            "--custom-trusted-root", str(graph.root / root_ref["path"]),
            "--signer-workflow", p["repository"] + "/" + p["producer"]["workflow"],
            "--signer-digest", p["producer"]["revision"], "--source-digest", p["producer"]["revision"],
            "--cert-oidc-issuer", ISSUER, "--deny-self-hosted-runners", "--hostname", "github.com",
            "--predicate-type", PREDICATE, "--format", "json"]


def validate_verified_output(raw, exit_code, *, expected_policy, certificate, certificate_ref, now):
    """Validate output received directly from the pinned verifier invocation.

    This function is not a signature implementation. An arbitrary saved JSON
    file must never be passed here in place of that invocation's stdout.
    """
    require(integer(exit_code, minimum=-(2**31)) == 0, "offline signature verification failed")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_RECORD_BYTES - 20, "verifier output limit")
    decoded = decode(b'{"verified":' + raw + b'}')["verified"]
    entries = sequence(decoded, minimum=1, maximum=16)
    p = expected_policy
    expected_run = run(certificate["run"], p)
    repo_uri = "https://github.com/" + p["repository"]
    invocation_uri = repo_uri + "/actions/runs/" + expected_run["run_id"] + "/attempts/" + expected_run["attempt"]
    for entry in entries:
        fields(entry, {"attestation", "verificationResult"})
        result = entry["verificationResult"]
        require(type(result) is dict, "missing cryptographic verification result")
        signature = result.get("signature")
        require(type(signature) is dict and type(signature.get("certificate")) is dict,
                "verified X.509 certificate required")
        cert = signature["certificate"]
        expected = {"issuer": ISSUER, "sourceRepositoryURI": repo_uri,
                    "sourceRepositoryDigest": p["producer"]["revision"],
                    "buildSignerDigest": p["producer"]["revision"], "buildTrigger": "workflow_dispatch",
                    "runnerEnvironment": "github-hosted", "runInvocationURI": invocation_uri}
        require(all(cert.get(name) == value for name, value in expected.items()),
                "authenticated producer/run binding mismatch")
        signer = cert.get("buildSignerURI")
        require(type(signer) is str and signer.startswith(repo_uri + "/" + p["producer"]["workflow"] + "@") and
                len(signer.partition("@")[2]) > 0, "authenticated signer workflow mismatch")
        times = sequence(result.get("verifiedTimestamps"), minimum=1, maximum=16)
        for verified in times:
            require(type(verified) is dict and "timestamp" in verified, "verified timestamp missing")
            witnessed = instant(verified["timestamp"], now, p["validity"]["clock_skew_seconds"])
            require(witnessed + timedelta(seconds=p["validity"]["clock_skew_seconds"]) >=
                    timestamp(certificate["completed_at"]), "signature predates completed tests")
        statement = result.get("statement")
        require(type(statement) is dict and statement.get("predicateType") == PREDICATE and
                statement.get("_type") == "https://in-toto.io/Statement/v1", "unexpected attested statement")
        subjects = sequence(statement.get("subject"), minimum=1, maximum=1)
        subject = fields(subjects[0], {"name", "digest"})
        require(subject["name"] == Path(certificate_ref["path"]).name and
                subject["digest"] == {"sha256": certificate_ref["sha256"]}, "attestation subject substitution")
    return {"run": expected_run, "certificate_sha256": certificate_ref["sha256"],
            "verified_output_sha256": hashlib.sha256(raw).hexdigest()}


def validate_import(value, *, p, policy_ref, review_ref, certificate_ref, certificate, now, boundary):
    """Consume an independently pinned importer receipt, not certificate metadata."""
    value = record(value, "qualification_import_v2", {
        "policy_sha256", "review_sha256", "certificate", "attestation", "run", "queried_at",
        "query", "jobs", "artifact", "importer", "imported_at", "status", "remote_query"})
    pass_result(value["status"])
    require(value["policy_sha256"] == policy_ref["sha256"] and value["review_sha256"] == review_ref["sha256"] and
            value["certificate"] == certificate_ref and value["run"] == certificate["run"], "import binding mismatch")
    reference(value["attestation"])
    reference(value["remote_query"])
    identifier(value["importer"])
    skew = p["validity"]["clock_skew_seconds"]
    queried = instant(value["queried_at"], now, skew)
    imported = instant(value["imported_at"], now, skew)
    require(timestamp(certificate["completed_at"]) <= queried <= imported, "invalid authenticated query time")
    require(boundary in {"arm", "launch", "merge"}, "unknown consumption boundary")
    maximum = p["validity"]["arming_seconds" if boundary == "arm" else "remote_seconds"]
    require(now - queried <= timedelta(seconds=maximum), "authenticated remote state expired")
    query = fields(value["query"], {"raw_pages", "status", "conclusion", "head_sha", "run_id", "attempt",
                                     "workflow", "event", "repository", "total_jobs", "total_artifacts"})
    require(query["status"] == "completed" and query["conclusion"] == "success", "remote run not successful")
    for name in ("run_id", "attempt", "workflow", "event", "repository"):
        require(query[name] == certificate["run"][name], "remote query identity mismatch")
    require(query["head_sha"] == p["producer"]["revision"], "remote producer revision mismatch")
    for ref in sequence(query["raw_pages"], minimum=3, maximum=100):
        reference(ref)
    jobs = sequence(value["jobs"], minimum=3, maximum=3)
    require(integer(query["total_jobs"]) == len(jobs), "remote jobs were truncated or unexpected")
    require([job.get("role") for job in jobs if type(job) is dict] == ["windows", "linux", "publisher"],
            "remote job coverage mismatch")
    for job in jobs:
        fields(job, {"id", "role", "status", "conclusion", "run_id", "attempt"})
        remote_id(job["id"])
        require(job["status"] == "completed" and job["conclusion"] == "success" and
                job["run_id"] == certificate["run"]["run_id"] and job["attempt"] == certificate["run"]["attempt"],
                "remote job failure or mixed attempt")
    require(len({job["id"] for job in jobs}) == len(jobs), "duplicate remote job")
    artifact = fields(value["artifact"], {"id", "run_id", "attempt", "expired", "archive", "name"})
    remote_id(artifact["id"])
    require(artifact["expired"] is False and artifact["run_id"] == certificate["run"]["run_id"] and
            artifact["attempt"] == certificate["run"]["attempt"], "wrong/expired remote artifact")
    fields(artifact["archive"], {"path", "sha256", "size"})
    from .records import relative_path
    relative_path(artifact["archive"]["path"])
    digest(artifact["archive"]["sha256"])
    integer(artifact["archive"]["size"], minimum=1, maximum=512 * 1024**2)
    identifier(artifact["name"])
    integer(query["total_artifacts"], minimum=1, maximum=10)
    return value


def validate_import_graph(graph, import_ref, *, p, policy_ref, review_ref, certificate_ref, certificate, now, boundary):
    """Validate both importer summary and complete retained authenticated pages.

    import_ref must itself be bound by the adopted controller/attempt authority.
    This is deliberately separate from signature verification of the producer.
    """
    from .remote import validate_pages

    receipt = validate_import(graph.get(import_ref), p=p, policy_ref=policy_ref, review_ref=review_ref,
                              certificate_ref=certificate_ref, certificate=certificate, now=now, boundary=boundary)
    observed = validate_pages(graph, receipt["remote_query"], certificate=certificate,
                              certificate_ref=certificate_ref, artifact_ref=receipt["artifact"]["archive"], now=now)
    require(all(receipt[key] == observed[key] for key in ("query", "jobs", "artifact", "queried_at")),
            "import summary contradicts retained remote pages")
    graph.blob(receipt["attestation"], maximum=MAX_RECORD_BYTES)
    graph.fresh()
    return receipt

def validate_revocations(value, *, policy_sha256, certificate_sha256, source_commit, now, skew):
    value = record(value, "qualification_revocations_v2", {"revision", "updated_at", "revoked"})
    identifier(value["revision"])
    instant(value["updated_at"], now, skew)
    for item in sequence(value["revoked"]):
        fields(item, {"kind", "digest", "reason"})
        require(item["kind"] in {"policy", "certificate", "source"}, "unsupported revocation kind")
        digest(item["digest"], git=item["kind"] == "source")
        require(type(item["reason"]) is str and len(item["reason"]) > 0, "revocation reason missing")
        targets = {"policy": policy_sha256, "certificate": certificate_sha256, "source": source_commit}
        require(item["digest"] != targets[item["kind"]], "qualification locally revoked")
    return value
