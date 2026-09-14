"""Use actual pytest child processes, then corrupt the retained protocol."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from weather.operations.qualification import journal, pytest_observer
from weather.operations.qualification.records import QualificationError


@pytest.fixture
def observed(tmp_path):
    candidate = tmp_path / "candidate"
    (candidate / "tests").mkdir(parents=True)
    (candidate / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (candidate / "tests" / "test_example.py").write_text(
        "import pytest\n"
        "def test_pass(): assert True\n"
        "@pytest.mark.skip(reason='native counterpart')\n"
        "def test_skip(): assert False\n"
        "@pytest.mark.xfail(reason='reviewed limitation', strict=True)\n"
        "def test_xfail(): assert False\n", encoding="utf-8")
    driver = tmp_path / "driver.py"
    driver.write_text(
        "import importlib.util, sys, pytest\n"
        "spec = importlib.util.spec_from_file_location('qualification_observer', sys.argv[1])\n"
        "plugin = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(plugin)\n"
        "raise SystemExit(pytest.main(['tests', '-q', '--junitxml=' + sys.argv[2]], plugins=[plugin]))\n", encoding="utf-8")
    path = tmp_path / "journal.jsonl"
    env = {key: value for key, value in os.environ.items() if key not in {"PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONPATH"}}
    env.update({"WEATHER_QUALIFICATION_JOURNAL": str(path), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"})
    child = subprocess.run([sys.executable, "-I", str(driver), str(Path(pytest_observer.__file__).resolve()), str(tmp_path / "run.xml")],
                           cwd=candidate, env=env, capture_output=True, timeout=30, check=False)
    assert child.returncode == 0, (child.stdout + child.stderr).decode(errors="replace")
    raw = path.read_bytes()
    ref = {"path": path.name, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    return tmp_path, candidate, ref, [json.loads(line) for line in raw.splitlines()]


def rewrite(observed, mutate):
    root, candidate, _, events = observed
    mutate(events)
    raw = b"".join((json.dumps(event) + "\n").encode() for event in events)
    (root / "changed.jsonl").write_bytes(raw)
    return root, candidate, {"path": "changed.jsonl", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}


def test_actual_pytest_reports_have_complete_native_tail(observed):
    root, candidate, ref, _ = observed
    result = journal.consume(root, ref, candidate_root=candidate, native_exit_code=0)
    assert result["status"] == "PASS"
    assert result["collected"] == result["started"] == result["completed"]
    assert [item["outcome"] for item in result["results"]] == ["pass", "skip", "xfail"]
    assert [item["reason"] for item in result["results"]] == [None, "native counterpart", "reviewed limitation"]


@pytest.mark.parametrize("mutate", [
    lambda events: events.pop(),
    lambda events: events.append(events[-1]),
    lambda events: events[2].__setitem__("ordinal", 1),
    lambda events: events[-1].__setitem__("tests_collected", 99),
    lambda events: events[-1].__setitem__("exit_code", 1),
    lambda events: next(event for event in events if event["event"] == "test_finish").__setitem__("nodeid", "other"),
    lambda events: next(event for event in events if event["event"] == "test_phase").__setitem__("when", "call"),
])
def test_missing_or_contradictory_stream_cannot_complete(observed, mutate):
    root, candidate, ref = rewrite(observed, mutate)
    with pytest.raises(QualificationError):
        journal.consume(root, ref, candidate_root=candidate, native_exit_code=0)


def test_wrong_native_exit_or_source_root_is_rejected(observed):
    root, candidate, ref, _ = observed
    with pytest.raises(QualificationError, match="native exit"):
        journal.consume(root, ref, candidate_root=candidate, native_exit_code=1)
    with pytest.raises(QualificationError, match="source root"):
        journal.consume(root, ref, candidate_root=root, native_exit_code=0)


def test_partial_last_record_is_never_a_tail(observed):
    root, candidate, ref, _ = observed
    raw = (root / ref["path"]).read_bytes()[:-1]
    (root / "partial.jsonl").write_bytes(raw)
    partial = {"path": "partial.jsonl", "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    with pytest.raises(QualificationError, match="partial"):
        journal.consume(root, partial, candidate_root=candidate, native_exit_code=0)
