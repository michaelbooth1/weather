"""Execute the real fixed child and platform-native controller in scratch."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from weather.operations.qualification import environment, process, runner
from weather.operations.qualification.contracts import Graph
from weather.operations.qualification.records import QualificationError


ROOT = Path(__file__).resolve().parents[2]


def tool_pin(path):
    path = Path(path).resolve()
    item = environment.file_identity(path.parent, path.name, native_installation=True)
    return {"root": str(path.parent), **{key: item[key] for key in ("path", "sha256", "size")}}


@pytest.fixture
def native_runner(tmp_path):
    trusted, candidate, outputs, scratch = (tmp_path / name for name in ("trusted", "candidate", "outputs", "scratch"))
    for path in (trusted, candidate, outputs, scratch):
        path.mkdir()
    files = set(runner.TRUSTED_PYTHON.values()) | (set(runner.TRUSTED_WINDOWS) if os.name == "nt" else set())
    pins = {}
    for name in files:
        target = trusted / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
        identity = environment.file_identity(trusted, name)
        pins[name] = {key: identity[key] for key in ("sha256", "size")}
    (candidate / "tests").mkdir()
    (candidate / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (candidate / "tests/test_example.py").write_text(
        "import os\n"
        "def test_example(tmp_path):\n"
        "    assert not any(name in os.environ for name in ['OPENAI_API_KEY', 'GITHUB_TOKEN', 'GITHUB_ACTIONS'])\n"
        "    (tmp_path / 'output.txt').write_text('fixture')\n", encoding="utf-8")
    tools = {"python": tool_pin(sys.executable), "git": tool_pin(shutil.which("git"))}
    if os.name == "nt":
        tools["powershell"] = tool_pin(Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe")
    return runner.Runner(trusted_root=trusted, candidate_root=candidate, output_root=outputs, scratch_root=scratch,
                         trusted_files=pins, executables=tools, site_roots=[Path(pytest.__file__).resolve().parents[1]],
                         seconds=120, memory_bytes=1024**3)


def test_actual_native_collection_and_chunk_have_verified_cleanup(native_runner, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-never-forward-this")
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-never-forward-this")
    try:
        collected = native_runner.collect()
    except Exception:
        for output in native_runner.output.glob("*/*"):
            if output.name in {"native.json", "transcript.txt"}:
                print(output.name, output.read_text(errors="replace")[:16384])
        for output in native_runner.scratch.glob("*/controller.log"):
            print(output.name, output.read_text(errors="replace")[:16384])
        raise
    nodes = collected["summary"]["collected"]
    assert nodes == ["tests/test_example.py::test_example"]
    expected = {"id": "chunk-1", "nodes": [{"nodeid": nodes[0], "disposition": "execute", "reason": None,
                                            "owner": None, "covered_by": None}]}
    ref = native_runner.chunk(expected, run={"run_id": "1", "attempt": "1"}, job_id="2")
    graph = Graph(native_runner.output)
    chunk = graph.get(ref)
    receipt = runner.validate_process(graph, chunk["process"], platform=native_runner.platform, transcript=chunk["transcript"])
    assert receipt["native"]["teardown_proved"] is True
    assert receipt["native"]["resource_samples"] > 0
    assert chunk["results"][0]["outcome"] == "pass"


def test_changed_trusted_observer_refuses_before_native_launch(native_runner):
    observer = native_runner.trusted / runner.TRUSTED_PYTHON["observer"]
    observer.write_text(observer.read_text() + "\n# changed\n")
    with pytest.raises(QualificationError, match="dependency drift"):
        native_runner.collect()
    assert list(native_runner.output.iterdir()) == []


def test_candidate_cannot_write_outside_scratch(native_runner):
    outside = native_runner.candidate.parent / "outside.txt"
    source = native_runner.candidate / "tests/test_example.py"
    source.write_text("from pathlib import Path\ndef test_example():\n    Path(" + repr(str(outside)) + ").write_text('bad')\n")
    with pytest.raises(QualificationError, match="native"):
        native_runner.execute("tests", nodes=["tests/test_example.py::test_example"])
    assert not outside.exists()
    transcripts = list(native_runner.output.glob("*/transcript.txt"))
    assert len(transcripts) == 1 and "qualification offline file access refused" in transcripts[0].read_text(errors="replace")
    assert not list(native_runner.output.glob("*/chunk.json"))


def test_clean_environment_is_an_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("UNKNOWN_NEW_PROVIDER_AUTH", "never-forward")
    monkeypatch.setenv("PYTHONPATH", "candidate-selected")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--ignore=tests")
    env = process.clean_environment(scratch=tmp_path, executable_paths=[Path(sys.executable).absolute()])
    assert not {"UNKNOWN_NEW_PROVIDER_AUTH", "PYTHONPATH", "PYTEST_ADDOPTS"}.intersection(env)
    assert env["HOME"] == str(tmp_path)


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux subreaper; Windows has its Job tests")
@pytest.mark.parametrize("body, expected", [
    ("print('complete')", True),
    ("raise SystemExit(7)", False),
    ("import time; time.sleep(30)", False),
    ("import os\nwhile True: os.write(1, b'x' * 65536)\n", False),
])
def test_native_linux_exit_timeout_and_output(tmp_path, body, expected):
    child = tmp_path / "child.py"
    child.write_text(body)
    result = process.linux_run([str(Path(sys.executable).resolve()), "-I", str(child)], cwd=tmp_path,
                               env=process.clean_environment(scratch=tmp_path, executable_paths=[Path(sys.executable)]),
                               transcript=tmp_path / "output.log", seconds=2, teardown_seconds=3,
                               memory_bytes=1024**3, output_bytes=4096, minimum_disk_bytes=1)
    assert result["completed"] is expected
    assert result["teardown_proved"] is True
    assert (tmp_path / "output.log").stat().st_size <= 4096
    assert not process._descendants(process._linux_processes(), os.getpid())


@pytest.mark.skipif(sys.platform != "linux", reason="native Linux subreaper; Windows has its Job tests")
def test_linux_double_fork_new_session_is_owned_until_cleanup(tmp_path):
    child = tmp_path / "child.py"
    child.write_text("import os, time\nif os.fork() == 0:\n    os.setsid()\n    time.sleep(30)\nelse:\n    time.sleep(.2)\n")
    result = process.linux_run([str(Path(sys.executable).resolve()), "-I", str(child)], cwd=tmp_path,
                               env=process.clean_environment(scratch=tmp_path, executable_paths=[Path(sys.executable)]),
                               transcript=tmp_path / "output.log", seconds=2, teardown_seconds=3,
                               memory_bytes=1024**3, output_bytes=4096, minimum_disk_bytes=1)
    assert result["teardown_proved"] is True
    assert not process._descendants(process._linux_processes(), os.getpid())


def test_native_installation_hardlinks_do_not_weaken_retained_evidence(tmp_path):
    import os
    from weather.operations.qualification import environment
    source = tmp_path / "native.exe"
    source.write_bytes(b"native fixture")
    os.link(source, tmp_path / "native-alias.exe")
    with pytest.raises(QualificationError, match="hard-linked"):
        environment.file_identity(tmp_path, source.name)
    observed = environment.file_identity(tmp_path, source.name, native_installation=True)
    assert observed["size"] == len(b"native fixture")
