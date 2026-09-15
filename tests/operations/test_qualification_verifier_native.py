"""Real gh protocol fixture through the contained parent on both native OSes.

The fixture is signed in a separate job without a candidate checkout. It has
no production authority. Code-certificate graph validation has separate tests;
this test substitutes only that graph-to-argv step to exercise the real binary,
runtime inventories, native parent, separated streams and signature refusal.
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from weather.operations.qualification import authentication, environment, records
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.verifier import CHILD, ContainedVerifier
from weather.operations.qualification.runner import TRUSTED_WINDOWS


pytestmark = pytest.mark.skipif(not os.environ.get("WEATHER_QUALIFICATION_PROTOCOL_ROOT"),
                                reason="requires the separately signed native CI protocol fixture")


def pin(path):
    path = Path(path).resolve()
    value = environment.file_identity(path.parent, path.name, native_installation=True)
    return {"root": str(path.parent), "path": path.name, "sha256": value["sha256"], "size": value["size"]}


@pytest.fixture
def native_verifier(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    tools = {"python": pin(sys.executable), "gh": pin(shutil.which("gh"))}
    if os.name == "nt":
        tools["powershell"] = pin(shutil.which("powershell.exe"))
    files = {}
    for name in (CHILD, *(TRUSTED_WINDOWS if os.name == "nt" else ())):
        value = environment.file_identity(repo, name)
        files[name] = {key: value[key] for key in ("sha256", "size")}
    root = Path(sys.base_prefix).resolve()
    # Discovery is a test fixture, not automatic policy approval. Exclude exact
    # package sites and unused native aliases; retain real native files/stdlib.
    exclusions = []
    for directory, directories, names in os.walk(root, followlinks=False):
        for name in [*directories, *names]:
            path = Path(directory) / name
            if path.is_symlink() or name == "site-packages":
                exclusions.append(path.relative_to(root).as_posix())
        directories[:] = [name for name in directories if name != "site-packages" and not (Path(directory) / name).is_symlink()]
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    manifest = environment.files_manifest(root, environment.enumerate_files(root, excluded_directories=exclusions),
                                           native_installation=True)
    runtime = {"root": str(root), "files": records.publish(evidence, "runtime.json", manifest), "exclusions": exclusions}
    graph = Graph(evidence)
    verifier = ContainedVerifier(trusted_root=repo, scratch=tmp_path / "verify", files=files, tools=tools,
                                 runtime=runtime, trust_graph=graph)
    fixture = Path(os.environ["WEATHER_QUALIFICATION_PROTOCOL_ROOT"])
    gh = Path(tools["gh"]["root"]) / tools["gh"]["path"]
    command = [str(gh), "attestation", "verify", str(fixture / "fixture.json"),
               "--repo", os.environ["GITHUB_REPOSITORY"], "--bundle", str(fixture / "attestation.jsonl"),
               "--custom-trusted-root", str(fixture / "trusted-root.jsonl"),
               "--signer-workflow", os.environ["GITHUB_REPOSITORY"] + "/.github/workflows/qualification-bootstrap.yml",
               "--signer-digest", os.environ["GITHUB_WORKFLOW_SHA"], "--source-digest", os.environ["GITHUB_SHA"],
               "--cert-oidc-issuer", authentication.ISSUER, "--deny-self-hosted-runners", "--hostname", "github.com",
               "--predicate-type", authentication.PREDICATE, "--format", "json"]
    monkeypatch.setattr(authentication, "verifier_command", lambda *args, **kwargs: command)
    return verifier, graph, command, fixture


def test_real_offline_gh_stdout_is_separate_and_native_cleanup_proved(native_verifier):
    verifier, graph, _, fixture = native_verifier
    result = verifier.verify(graph=graph, policy_ref=None, review_ref=None, certificate_ref=None, bundle_ref=None)
    values = json.loads(result["stdout"])
    verified = values[0]["verificationResult"]
    assert verified["signature"]["certificate"]["buildSignerDigest"] == os.environ["GITHUB_WORKFLOW_SHA"]
    assert verified["statement"]["subject"][0]["digest"]["sha256"] == hashlib.sha256((fixture / "fixture.json").read_bytes()).hexdigest()
    assert result["exit_code"] == 0 and result["teardown_proved"]
    assert (verifier.scratch / "stderr.log").is_file()
    # The standard strict graph JSON parser accepts the actual gh JSON shape.
    assert records.decode(b'{"verified":' + result["stdout"] + b'}')["verified"] == values


def test_real_offline_gh_rejects_another_producer_revision(native_verifier):
    verifier, graph, command, _ = native_verifier
    command[13] = "0" * 40
    with pytest.raises(records.QualificationError, match="native"):
        verifier.verify(graph=graph, policy_ref=None, review_ref=None, certificate_ref=None, bundle_ref=None)
