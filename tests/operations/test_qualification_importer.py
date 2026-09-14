"""Exercise real import decisions with data-only transport/signature fixtures.

The verifier stub is not cryptographic evidence. Native signature verification
has a separate pinned-executable acceptance requirement.
"""

from datetime import datetime
import hashlib
import json
import zipfile

import pytest

from tests.operations.test_qualification_evidence import NOW, bundle
from tests.operations.test_qualification_authentication import verified_output
from tests.operations.test_qualification_remote import pages
from weather.operations.qualification import importer, records, remote
from weather.operations.qualification.contracts import Graph, validate_trust


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


def source(b):
    attestation = b.put("attestation", {"fixture": "not a cryptographic signature"})
    archive = b.root / "bundle.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(b.root.iterdir()):
            if path.suffix in {".json", ".txt"}:
                output.write(path, path.name)
    raw = archive.read_bytes()
    values, _ = pages(b)
    values["artifacts"]["artifacts"][0].update(digest="sha256:" + hashlib.sha256(raw).hexdigest(), size_in_bytes=len(raw))
    return raw, values, attestation


def client(b, raw, values):
    class FixtureClient:
        repository = "owner/repo"

        def json(self, endpoint):
            endpoints = remote.endpoints(b.values["certificate"]["run"])
            key = next(key for key, path in endpoints.items() if path == endpoint)
            return json.dumps(values[key]).encode()

        def artifact(self, artifact_id, *, root, name, sha256, size):
            assert artifact_id == "127" and sha256 == hashlib.sha256(raw).hexdigest() and size == len(raw)
            (root / name).write_bytes(raw)
            return {"path": name, "sha256": sha256, "size": size}

    return FixtureClient()


def run_import(b, tmp_path, monkeypatch, *, mutate=None, broken_verifier=False):
    raw, values, attestation = source(b)
    if mutate:
        mutate(values)
    monkeypatch.setattr(importer, "datetime", FrozenDateTime)
    monkeypatch.setattr(importer, "utc_now", lambda: "2026-09-14T12:00:00Z")
    monkeypatch.setattr(importer, "validate_trust", lambda graph, policy, review: validate_trust(graph, policy, review, now=NOW))

    class FixtureVerifier:
        def verify(self, **kwargs):
            return {"teardown_proved": not broken_verifier, "exit_code": 0,
                    "stdout": json.dumps(verified_output(b)).encode()}

    return importer.import_bundle(client=client(b, raw, values), output_root=tmp_path / "imported",
                                  policy_ref=b.refs["policy"], review_ref=b.refs["review"],
                                  certificate_ref=b.refs["certificate"], attestation_ref=attestation,
                                  run_identity=b.values["certificate"]["run"], importer_id="fixture-principal",
                                  verifier=FixtureVerifier())


def test_complete_import_rechecks_actual_archive_pages_and_receipt(bundle, tmp_path, monkeypatch):
    result = run_import(bundle, tmp_path, monkeypatch)
    from pathlib import Path
    root = Path(result["root"])
    receipt = Graph(root).get(result["receipt"])
    assert receipt["status"] == "PASS" and receipt["run"]["attempt"] == "1"
    assert (root / "transport/artifact.zip").is_file()
    assert (root / "transport/current.json").read_text().startswith('{"id": 123')


@pytest.mark.parametrize("mutation", [lambda page: page["current"].update(run_attempt=2),
                                       lambda page: page["jobs"]["jobs"][2].update(conclusion="failure")])
def test_late_remote_failure_never_publishes_import_pass(bundle, tmp_path, monkeypatch, mutation):
    with pytest.raises(records.QualificationError):
        run_import(bundle, tmp_path, monkeypatch, mutate=mutation)
    assert not (tmp_path / "imported/evidence/import.json").exists()


def test_unproved_signature_child_cleanup_never_publishes_import_pass(bundle, tmp_path, monkeypatch):
    with pytest.raises(records.QualificationError, match="left descendants"):
        run_import(bundle, tmp_path, monkeypatch, broken_verifier=True)
    assert not (tmp_path / "imported/evidence/import.json").exists()
