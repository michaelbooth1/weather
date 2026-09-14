"""Attended import of exact GitHub evidence into a new local namespace.

The actual contained signature invocation is supplied by the adopted controller
as an object, never by a downloaded record or command path. This importer has
no Scheduler, installation, merge or capture authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path

from . import archive, authentication, evidence, remote
from .contracts import Graph, identifier, validate_trust
from .records import checked_root, decode, digest, open_record, publish, require, utc_now


def _retain_raw(root, name, raw):
    """Preserve actual response bytes; partial names remain spent on failure."""
    from .records import publish_raw

    return publish_raw(root, name, raw)


def _copy_blob(source_root, ref, destination, name):
    target = destination / name
    checked_root(target.parent)
    hasher, count = hashlib.sha256(), 0
    with open_record(source_root, ref["path"]) as original, target.open("xb") as output:
        while block := original.read(min(1024 * 1024, ref["size"] + 1 - count)):
            count += len(block)
            require(count <= ref["size"], "import source grew")
            hasher.update(block)
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    require(count == ref["size"] and hasher.hexdigest() == ref["sha256"], "import source bytes differ")
    return {**ref, "path": name}


def import_bundle(*, client, output_root, policy_ref, review_ref, certificate_ref, attestation_ref,
                  run_identity, importer_id, verifier):
    """Only references from the attended caller's reviewed authority are inputs.

    `verifier.verify` is the adopted, hash-pinned contained implementation. It
    receives validated argument-independent references and returns actual native
    stdout/exit/cleanup; a path named in evidence cannot replace that method.
    """
    identifier(importer_id)
    root = Path(output_root)
    checked_root(root.parent)
    require(not root.exists(), "import destination was already spent")
    root.mkdir()
    paths = remote.endpoints(run_identity)
    raw_artifacts = client.json(paths["artifacts"])
    artifacts = remote._complete_page(decode(raw_artifacts), "artifacts", maximum=10)
    expected_name = "qualification-" + run_identity["run_id"] + "-" + run_identity["attempt"]
    selected = [item for item in artifacts if item.get("name") == expected_name]
    require(len(selected) == 1 and selected[0].get("expired") is False, "exact import artifact missing/expired")
    selected = selected[0]
    raw_digest = selected.get("digest", "")
    require(type(raw_digest) is str and raw_digest.startswith("sha256:"), "GitHub artifact digest missing")
    digest(raw_digest[7:])
    archive_ref = client.artifact(remote.api_id(selected["id"]), root=root, name="artifact.zip",
                                  sha256=raw_digest[7:], size=selected.get("size_in_bytes"))
    destination = root / "evidence"
    archive.extract(root, archive_ref, destination)
    graph = Graph(destination)
    policy, review, now = validate_trust(graph, policy_ref, review_ref)
    require(policy["repository"] == client.repository, "authenticated importer repository differs")
    evidence.validate_code(graph, policy_ref, review_ref, certificate_ref, now=now)
    certificate = graph.get(certificate_ref)
    require(certificate["run"] == run_identity, "imported certificate belongs to another run")
    graph.blob(attestation_ref, maximum=2 * 1024**2)
    # Store the fetched ZIP within the graph so offline consumers can rehash the
    # exact archive authenticated by REST, without following an outside path.
    transport = destination / "transport"
    require(not transport.exists(), "artifact preoccupied importer-owned namespace")
    transport.mkdir()
    retained_archive = _copy_blob(root, archive_ref, destination, "transport/artifact.zip")
    pages = []
    for kind, endpoint in paths.items():
        raw = client.json(endpoint)
        ref = _retain_raw(destination, "transport/" + kind + ".json", raw)
        pages.append({"kind": kind, "endpoint": endpoint, "http_status": 200, "body": ref})
    query_ref = publish(destination, "remote-query.json", {"schema": "qualification_remote_query_v2",
                        "run": run_identity, "pages": pages, "queried_at": utc_now()})
    now = datetime.now(timezone.utc)
    observed = remote.validate_pages(graph, query_ref, certificate=certificate, certificate_ref=certificate_ref,
                                      artifact_ref=retained_archive, now=now)
    native = verifier.verify(graph=Graph(destination), policy_ref=policy_ref, review_ref=review_ref,
                             certificate_ref=certificate_ref, bundle_ref=attestation_ref)
    require(native["teardown_proved"] is True, "offline signature verifier left descendants")
    authentication.validate_verified_output(native["stdout"], native["exit_code"], expected_policy=policy,
                                              certificate=certificate, certificate_ref=certificate_ref, now=now)
    result = {"schema": "qualification_import_v2", "status": "PASS", "policy_sha256": policy_ref["sha256"],
              "review_sha256": review_ref["sha256"], "certificate": certificate_ref, "attestation": attestation_ref,
              "run": run_identity, "remote_query": query_ref, "importer": importer_id, "imported_at": utc_now(),
              **{key: observed[key] for key in ("query", "jobs", "artifact", "queried_at")}}
    graph.fresh()
    authentication.validate_import(result, p=policy, policy_ref=policy_ref, review_ref=review_ref,
                                   certificate_ref=certificate_ref, certificate=certificate,
                                   now=datetime.now(timezone.utc), boundary="arm")
    ref = publish(destination, "import.json", result)
    authentication.validate_import_graph(Graph(destination), ref, p=policy, policy_ref=policy_ref,
                                           review_ref=review_ref, certificate_ref=certificate_ref,
                                           certificate=certificate, now=datetime.now(timezone.utc), boundary="arm")
    return {"root": str(destination), "receipt": ref}
