"""Reviewed installation and data-only publisher boundaries, without host IO."""

from copy import deepcopy
import hashlib
from pathlib import Path
import zipfile

import pytest

from tests.operations.test_qualification_producer import dependency_lock
from weather.operations.qualification import cli, environment, installation, records, workflow
from weather.operations.qualification.contracts import Graph


@pytest.fixture
def installer(tmp_path):
    root, candidate, evidence = (tmp_path / name for name in ("python", "candidate", "evidence"))
    for path in (root, candidate, evidence):
        path.mkdir()
    site = root / "sites"
    (site / "pip").mkdir(parents=True)
    (site / "pip/__main__.py").write_text("raise SystemExit(0)\n")
    (root / "python.exe").write_bytes(b"reviewed native interpreter fixture")
    manifest = environment.files_manifest(root, environment.enumerate_files(root))
    ref = records.publish(evidence, "installer.json", manifest)
    profile = {"root": str(root), "files": ref, "exclusions": [], "sites": ["sites"]}
    return Graph(evidence), profile, candidate


def test_installer_requires_complete_reviewed_bytes_before_import(installer):
    graph, profile, candidate = installer
    assert installation.verify_installer(graph, profile, candidate=candidate) == [str(Path(profile["root"]) / "sites")]
    (Path(profile["root"]) / "sites/pip/__main__.py").write_text("raise SystemExit(1)\n")
    with pytest.raises(records.QualificationError, match="runtime/pip bytes differ"):
        installation.verify_installer(graph, profile, candidate=candidate)


def test_extra_base_site_hook_invalidates_installer(installer):
    graph, profile, candidate = installer
    (Path(profile["root"]) / "sites/startup.pth").write_text("import unreviewed\n")
    with pytest.raises(records.QualificationError, match="runtime/pip bytes differ"):
        installation.verify_installer(graph, profile, candidate=candidate)


def test_candidate_cannot_be_installer_authority(installer):
    graph, profile, _ = installer
    with pytest.raises(records.QualificationError, match="outside candidate"):
        installation.verify_installer(graph, profile, candidate=Path(profile["root"]).parent)


def test_dispatch_rejects_an_unreviewed_installer_shape(installer):
    graph, installer_profile, _ = installer
    ref = installer_profile["files"]
    profile = {"environment_bindings": {}, "dependency_lock": ref,
               "wheel_artifact": {"id": "42", "sha256": "a" * 64, "size": 123},
               "executables": {}, "site_roots": [], "installer": installer_profile}
    value = {"schema": "qualification_dispatch_v2", "source": "a" * 40, "baseline": "b" * 40,
             "policy": ref, "review": ref, "profiles": {"windows": deepcopy(profile), "linux": deepcopy(profile)}}
    assert workflow.dispatch(value, producer_revision="c" * 40, repository="owner/repo") == value
    value["profiles"]["windows"]["installer"]["command"] = "unreviewed"
    with pytest.raises(records.QualificationError, match="fields"):
        workflow.dispatch(value, producer_revision="c" * 40, repository="owner/repo")


def test_wheel_zip_must_contain_exact_reviewed_set(dependency_lock, tmp_path):
    value, wheel_root, _ = dependency_lock
    root = tmp_path / "archive"
    root.mkdir()
    packed = root / "wheels.zip"
    with zipfile.ZipFile(packed, "x") as output:
        output.write(wheel_root / value["wheels"][0]["filename"], value["wheels"][0]["filename"])
        output.writestr("startup.py", "import unreviewed")
    raw = packed.read_bytes()
    ref = {"path": packed.name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    with pytest.raises(records.QualificationError, match="reviewed complete set"):
        workflow.extract_wheels(root, ref, destination=root / "expanded", lock_value=value)
    assert not (root / "expanded").exists()


def test_publisher_export_excludes_executable_payload_and_refuses_conflict(tmp_path):
    native, export = tmp_path / "native", tmp_path / "export"
    native.mkdir()
    (native / "proof.json").write_bytes(b'{"status":"FAIL"}\n')
    (native / "candidate.py").write_text("raise RuntimeError('must never execute')")
    cli._copy_data(native, export)
    assert list(export.iterdir()) == [export / "proof.json"]
    cli._merge_data(native, export)
    (native / "proof.json").write_bytes(b'{"status":"PASS"}\n')
    with pytest.raises(records.QualificationError, match="disagree"):
        cli._merge_data(native, export)


def test_job_selection_requires_actual_exact_running_role():
    run = {"repository": "owner/repo", "run_id": "41", "attempt": "2", "revision": "a" * 40}
    value = {"total_count": 1, "jobs": [{"id": 51, "run_id": 41, "head_sha": "a" * 40,
                                       "name": "qualification-windows", "status": "in_progress", "conclusion": None}]}

    class Client:
        def json(self, path):
            assert path == "/repos/owner/repo/actions/runs/41/attempts/2/jobs?per_page=100&page=1"
            return records.encode(value)

    assert workflow.select_job(Client(), run_identity=run, platform="windows") == "51"
    value["jobs"][0]["conclusion"] = "failure"
    with pytest.raises(records.QualificationError, match="reviewed producer invocation"):
        workflow.select_job(Client(), run_identity=run, platform="windows")


def test_production_entry_rejects_unhosted_execution_before_other_io(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(records.QualificationError, match="reviewed hosted workflow"):
        cli._hosted(tmp_path)
