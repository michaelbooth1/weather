"""Executes the binding roll_verdict.ps1 on a dummy schema-family diff (Data Layer v2 PL-2).

Guards: docs/operations/DATA_LAYER_V2_PLAN.md S3 verify "dummy family diff -> ROLL-FREE" and
AGENTS.md "Get the verdict from scripts\\ops\\roll_verdict.ps1 -Branch <b>; never derive it by hand".

The fixture repository carries the real ``scripts/ops/roll_verdict.ps1``, the real
``config/capture_families.json`` closure registry (DLv2 S1) and four fresh capture
closure status files whose ``source_scope_files`` are the static loop closure of this checkout
(which includes the ``schema_registry*`` core). A branch that only adds
``src/weather/schema_families/<family>.py`` must be ROLL-FREE (exit 0); a branch that adds the same
SchemaSpec to the core must be ROLL-SENSITIVE (exit 3).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from weather.operations.landing_preflight_rollclass_graph import GraphOptions, TreeView, static_closure_files

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "roll_verdict.ps1"
REGISTRY = REPO_ROOT / "config" / "capture_families.json"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or POWERSHELL is None or shutil.which("git") is None,
    reason="Windows PowerShell 5.1 and git are required",
)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "GIT_CONFIG_NOSYSTEM": "1"}

# The workstation may or may not have the execution-tape task; the fixture has no such loop.
WRAPPER = """function global:Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName) return }
& $env:FAKE_SCRIPT @args
exit $LASTEXITCODE
"""

STATUS_FILES = (
    "loop_supervisor_status.json",
    "clob_loop_supervisor_status.json",
    "observation_trigger_supervisor_status.json",
    "clob_enrichment_status.json",
)
CORE_FILES = (
    "src/weather/schema_registry.py",
    "src/weather/schema_registry_data.py",
    "src/weather/schema_registry_recent_data.py",
    "src/weather/schema_registry_types.py",
)
FAMILY_FILE = "src/weather/schema_families/dummy_capture.py"
FAMILY_TEXT = """from weather.schema_registry_types import SchemaSpec

SCHEMAS = (SchemaSpec("dummy_capture_rows", "dummy_capture_rows_v0.1", "weather.dummy_capture", "active"),)
"""


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                            env=dict(os.environ, **GIT_ENV))
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr.strip()}"
    return result.stdout.strip()


def _loop_closure() -> list[str]:
    paths = {}
    for base in ("src", "weather"):
        for file in (REPO_ROOT / base).rglob("*.py"):
            rel = file.relative_to(REPO_ROOT).as_posix()
            if "__pycache__" not in rel:
                paths[rel] = rel
    view = TreeView("worktree", paths, lambda key: (REPO_ROOT / key).read_bytes())
    return sorted(static_closure_files(view, GraphOptions()))


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts" / "ops").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "scripts" / "ops" / "roll_verdict.ps1")
    # Since DLv2 S1 the closure list is read from the registry; without it the verdict is UNDECIDABLE.
    (repo / "config").mkdir()
    shutil.copy2(REGISTRY, repo / "config" / "capture_families.json")
    for rel in (*CORE_FILES, "src/weather/schema_families/__init__.py"):
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, target)
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    closure = _loop_closure()
    assert set(CORE_FILES) <= set(closure)
    assert not [path for path in closure if path.startswith("src/weather/schema_families/")]
    snapshots = repo / "data" / "snapshots"  # untracked runtime state, as on the host
    snapshots.mkdir(parents=True)
    for name in STATUS_FILES:
        (snapshots / name).write_text(json.dumps({
            "state": "RUNNING",
            "current_runtime_identity": {"source_scope_files": closure},
        }), encoding="utf-8")

    _git(repo, "checkout", "-q", "-b", "dummy-family")
    (repo / FAMILY_FILE).write_text(FAMILY_TEXT, encoding="utf-8")
    _git(repo, "add", "-A", "src")
    _git(repo, "commit", "-q", "-m", "add a dummy capture family schema")

    _git(repo, "checkout", "-q", "-b", "core-edit", "master")
    core = repo / "src/weather/schema_registry_recent_data.py"
    text = core.read_text(encoding="utf-8")
    edited = text.replace(
        "RECENT_REGISTERED_SCHEMAS = (\n",
        'RECENT_REGISTERED_SCHEMAS = (\n    SchemaSpec("dummy_capture_rows", "dummy_capture_rows_v0.1", "o", "active"),\n', 1)
    assert edited != text
    core.write_text(edited, encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "add the same schema to the core")
    _git(repo, "checkout", "-q", "master")
    return repo


def _verdict(repo: Path, branch: str) -> tuple[int, str, dict]:
    wrapper = repo.parent / "wrapper.ps1"
    wrapper.write_text(WRAPPER, encoding="utf-8")
    out = repo.parent / f"{branch}.json"
    env = dict(os.environ, FAKE_SCRIPT=str(repo / "scripts" / "ops" / "roll_verdict.ps1"), **GIT_ENV)
    proc = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
         "-Branch", branch, "-JsonOut", str(out)],
        cwd=repo, capture_output=True, text=True, env=env, timeout=180,
    )
    payload = json.loads(out.read_text(encoding="utf-8-sig")) if out.exists() else {}
    return proc.returncode, proc.stdout + proc.stderr, payload


@pytest.mark.spawns
def test_dummy_family_schema_diff_is_roll_free_and_a_core_addition_rolls(repo: Path):
    code, output, payload = _verdict(repo, "dummy-family")
    assert code == 0, output
    assert "VERDICT: ROLL-FREE" in output
    assert payload["verdict"] == "ROLL-FREE"
    assert [row["file"] for row in payload["files"]] == [FAMILY_FILE]
    assert payload["files"][0]["rolls"] is False

    code, output, payload = _verdict(repo, "core-edit")
    assert code == 3, output
    assert payload["verdict"] == "ROLL-SENSITIVE"
    (row,) = payload["files"]
    assert row["file"] == "src/weather/schema_registry_recent_data.py" and row["rolls"] is True
    assert len(row["closures"]) == len(STATUS_FILES)
