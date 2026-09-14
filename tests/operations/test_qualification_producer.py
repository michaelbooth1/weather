"""Actual producer decisions reject unreviewed environments and remote jobs."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from tests.operations.test_qualification_environment import installation
from tests.operations.test_qualification_evidence import NOW, bundle
from tests.operations.test_qualification_remote import pages
from weather.operations.qualification import environment, producer, publisher, records
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.installation import lock, prepare


@pytest.fixture
def dependency_lock(tmp_path):
    root = tmp_path / "wheels"
    root.mkdir()
    raw = b"retained wheel bytes; install plan fixture does not execute pip"
    name = "example_dependency-1.2.3-py3-none-any.whl"
    (root / name).write_bytes(raw)
    python = tmp_path / "python.exe"
    python.write_bytes(b"reviewed interpreter fixture")
    value = {"schema": "qualification_dependency_lock_v2", "platform": "windows", "python_version": "3.11.0",
             "python_sha256": hashlib.sha256(python.read_bytes()).hexdigest(),
             "wheels": [{"name": "example-dependency", "version": "1.2.3", "filename": name,
                         "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}]}
    return value, root, python


def test_install_plan_is_fixed_offline_and_destination_single_use(dependency_lock, tmp_path):
    value, root, python = dependency_lock
    destination = tmp_path / "install"
    argv = prepare(value, wheel_root=root, destination=destination, python_path=python)
    assert argv[:7] == [str(python), "-I", "-B", "-m", "pip", "--isolated", "--disable-pip-version-check"]
    assert {"--no-index", "--no-deps", "--require-hashes", "--no-compile", "--only-binary=:all:"} <= set(argv)
    assert "--upgrade" not in argv
    assert (destination / "reviewed-requirements.txt").read_text().endswith(" --hash=sha256:" + value["wheels"][0]["sha256"] + "\n")
    with pytest.raises(records.QualificationError, match="namespace spent"):
        prepare(value, wheel_root=root, destination=destination, python_path=python)


@pytest.mark.parametrize("mutation", [
    lambda value: value["wheels"].append(value["wheels"][0]),
    lambda value: value["wheels"][0].update(filename="../unreviewed.whl"),
    lambda value: value["wheels"][0].update(version="1.2.3 --index-url evil"),
    lambda value: value["wheels"][0].update(size=True),
    lambda value: value.update(extra="unreviewed"),
])
def test_dependency_lock_has_no_resolution_or_argument_escape(dependency_lock, mutation):
    value, _, _ = dependency_lock
    mutation(value)
    with pytest.raises(records.QualificationError):
        lock(value)


def test_changed_wheel_refuses_before_installation_namespace(dependency_lock, tmp_path):
    value, root, python = dependency_lock
    (root / value["wheels"][0]["filename"]).write_bytes(b"changed")
    with pytest.raises(records.QualificationError, match="wheel differs"):
        prepare(value, wheel_root=root, destination=tmp_path / "install", python_path=python)
    assert not (tmp_path / "install").exists()


def test_actual_installed_environment_rejects_extra_site_file(installation, tmp_path):
    root, site, _ = installation
    interpreter, native, wheels, graph_root = (tmp_path / name for name in ("interpreter", "native", "wheels", "graph"))
    for path in (interpreter, native, wheels, graph_root):
        path.mkdir()
    (interpreter / "python.exe").write_bytes(b"interpreter")
    (native / "git.exe").write_bytes(b"native prerequisite")
    (wheels / "example_dependency-1.2.3-py3-none-any.whl").write_bytes(b"wheel fixture")
    wheel = environment.file_identity(wheels, "example_dependency-1.2.3-py3-none-any.whl")
    wheel = {"filename": wheel["path"], "sha256": wheel["sha256"], "size": wheel["size"]}
    pins = [{"name": "example-dependency", "version": "1.2.3", **wheel}]
    dist = environment.discover_distributions([site])["example-dependency"]
    dependencies = records.publish(graph_root, "dist.json", environment.installed_distribution(dist, root))
    runtime = records.publish(graph_root, "runtime.json", environment.files_manifest(interpreter, ["python.exe"]))
    natives = records.publish(graph_root, "native.json", environment.files_manifest(native, ["git.exe"]))
    value = {"schema": "qualification_environment_v2", "platform": "linux", "architecture": "AMD64",
             "python": {"implementation": "CPython", "version": "3.11.0", "executable_sha256": "a" * 64, "runtime_files": runtime},
             "powershell": None, "git": {"version": "2.55.0", "sha256": "b" * 64}, "native_files": natives,
             "distributions": [{"name": "example-dependency", "version": "1.2.3", "wheel": wheel, "installed_files": dependencies}]}
    env_ref = records.publish(graph_root, "environment.json", value)
    bindings = {"interpreter": str(interpreter), "installation": str(root), "native": str(native),
                "site_roots": [str(site)], "interpreter_exclusions": []}
    assert producer.verify_environment(Graph(graph_root), env_ref, platform="linux", bindings=bindings, wheel_root=wheels, wheels=pins) == value
    (site / "injected.pth").write_text("import unreviewed_module\n")
    with pytest.raises(records.QualificationError, match="unrecorded file"):
        producer.verify_environment(Graph(graph_root), env_ref, platform="linux", bindings=bindings, wheel_root=wheels, wheels=pins)


def publishing_values(b):
    values, _ = pages(b)
    jobs = values["jobs"]
    jobs["jobs"][2].update(status="in_progress", conclusion=None, completed_at=None)
    return jobs


def test_publisher_requires_both_actual_native_jobs_and_its_running_identity(bundle):
    jobs = publishing_values(bundle)
    publisher.require_publishing_jobs(json.dumps(jobs).encode(), expected_run=bundle.values["certificate"]["run"],
                                      certificate_jobs=[bundle.values["windows-job"], bundle.values["linux-job"]],
                                      publisher_job_id="126", now=NOW)


@pytest.mark.parametrize("mutation", [
    lambda page: page["jobs"][0].update(conclusion="failure"),
    lambda page: page["jobs"][1].update(id=999),
    lambda page: page["jobs"][2].update(status="completed", conclusion="success"),
    lambda page: page["jobs"].pop(),
    lambda page: page["jobs"][0].update(head_sha="c" * 40),
])
def test_publisher_rejects_missing_failed_or_wrong_native_completion(bundle, mutation):
    jobs = publishing_values(bundle)
    mutation(jobs)
    with pytest.raises(records.QualificationError):
        publisher.require_publishing_jobs(json.dumps(jobs).encode(), expected_run=bundle.values["certificate"]["run"],
                                          certificate_jobs=[bundle.values["windows-job"], bundle.values["linux-job"]],
                                          publisher_job_id="126", now=NOW)


def test_raw_api_bytes_are_not_reserialized_before_binding(tmp_path):
    raw = b'{ "original" : [1, 2] }\n'
    ref = records.publish_raw(tmp_path, "response.json", raw)
    assert (tmp_path / ref["path"]).read_bytes() == raw
    assert ref["sha256"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(records.QualificationError):
        records.publish_raw(tmp_path, "duplicate.json", b'{"x":1,"x":2}')
