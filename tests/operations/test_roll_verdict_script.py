"""roll_verdict.ps1 executes identically before and after the closure list moved to the registry.

Guards: docs/operations/DATA_LAYER_V2_CONTRACT.md "Roll closures" (data layer v2 S1): the
registry-driven script must print the same verdict, warnings and exit code as the pre-registry
script (frozen byte-for-byte in tests/fixtures/roll_verdict/) for every closure-evidence shape,
including the optional execution-tape producer and sparse statuses under inherited strict mode,
and must refuse (UNDECIDABLE, exit 1) rather than judge from an unreadable registry.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "roll_verdict.ps1"
BASELINE = REPO_ROOT / "tests" / "fixtures" / "roll_verdict" / "pre_registry_roll_verdict.ps1.txt"
BASELINE_SHA256 = "f2808c6bd3ae85b2087a9ef1d52bd8488c4ea149ca672d226a5964667f786c93"
REGISTRY = REPO_ROOT / "config" / "capture_families.json"

pytestmark = [
    pytest.mark.spawns,
    pytest.mark.skipif(
        os.name != "nt" or shutil.which("powershell") is None or shutil.which("git") is None,
        reason="requires Windows PowerShell and git",
    ),
]

# One child runs every case under inherited strict mode. The Get-ScheduledTask stub makes the
# optional execution-tape producer's task state a fixture instead of a property of this host.
RUNNER = r"""
Set-StrictMode -Version Latest
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    if ($env:RV_STUB_TASK_STATE -and $TaskName -eq 'WeatherExecutionTapeSupervisor') {
        return [pscustomobject]@{ TaskName = $TaskName; State = $env:RV_STUB_TASK_STATE }
    }
    return $null
}
$results = @()
$cases = Get-Content -LiteralPath $env:RV_CASES -Raw | ConvertFrom-Json
foreach ($case in $cases) {
    $env:RV_STUB_TASK_STATE = [string]$case.task_state
    $global:LASTEXITCODE = $null
    try {
        $out = (& $case.script -Branch $case.branch 2>&1 | Out-String)
        $rc = $LASTEXITCODE
    }
    catch { $out = "THREW: " + $_.Exception.Message; $rc = -1 }
    $results += [pscustomobject]@{ id = $case.id; script = $case.script; rc = $rc; out = $out }
}
$results | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $env:RV_RESULTS -Encoding utf8
"""

FILES = {
    "src/weather/a.py": "A = 1\n",
    "src/weather/b.py": "B = 1\n",
    "src/weather/c.py": "C = 1\n",
    "docs/x.md": "x\n",
}
BRANCH_EDITS = {
    "roll": "src/weather/a.py",
    "docs": "docs/x.md",
    "other": "src/weather/c.py",
}
SNAP = "data/snapshots/"
FRESH = {
    SNAP + "loop_supervisor_status.json": {
        "state": "RUNNING", "ensure_status": "OK", "reason": "",
        "current_runtime_identity": {"source_scope_files": ["src/weather/a.py", "src/weather/b.py"]},
    },
    SNAP + "clob_loop_supervisor_status.json": {"runtime_identity": {"source_scope_files": ["src/weather/b.py"]}},
    SNAP + "observation_trigger_supervisor_status.json": {"runtime_identity": {"source_scope_files": ["src/weather/b.py"]}},
    SNAP + "clob_enrichment_status.json": {"runtime_identity": {"source_scope_files": ["src/weather/b.py"]}},
}
EXEC_STATUS = {SNAP + "execution_tape_supervisor_status.json": {"runtime_identity": {"source_scope_files": ["src/weather/c.py"]}}}
OLD = 48 * 3600


def _with(base: dict, **changes) -> dict:
    out = dict(base)
    for key, value in changes.items():
        path = SNAP + key + ".json"
        if value is None:
            out.pop(path, None)
        else:
            out[path] = value
    return out


# id -> (status documents, files aged past MaxStatusAgeHours, extra raw files, branch, task state, expected rc)
CASES = {
    "fresh_roll": (FRESH, (), {}, "roll", "", 3),
    "fresh_docs": (FRESH, (), {}, "docs", "", 0),
    "fresh_other_py": (FRESH, (), {}, "other", "", 0),
    "dormant_unique": (
        _with(FRESH, clob_enrichment_status={"runtime_identity": {"source_scope_files": ["src/weather/c.py"]}}),
        (SNAP + "clob_enrichment_status.json",), {}, "other", "", 2,
    ),
    "dormant_subsumed": (FRESH, (SNAP + "clob_enrichment_status.json",), {}, "roll", "", 3),
    "missing_status": (_with(FRESH, observation_trigger_supervisor_status=None), (), {}, "roll", "", 3),
    "tombstone": (
        _with(FRESH, observation_trigger_supervisor_status={"state": "DEAD", "reason": "retired", "runtime_identity": {"source_scope_files": ["src/weather/b.py"]}}),
        (), {}, "docs", "", 0,
    ),
    "no_scope_files": (_with(FRESH, clob_loop_supervisor_status={"runtime_identity": {"source_scope_files": []}}), (), {}, "roll", "", 3),
    "writer_lock_without_status": (FRESH, (), {SNAP + ".execution_tape_status.json.writer.lock": ""}, "other", "", 0),
    "worker_running": ({**FRESH, **EXEC_STATUS}, (), {SNAP + "execution_tape_status.json": '{"state": "RUNNING"}'}, "other", "", 3),
    "worker_stopped": ({**FRESH, **EXEC_STATUS}, (), {SNAP + "execution_tape_status.json": '{"state": "STOPPED"}'}, "other", "", 0),
    "worker_sparse": ({**FRESH, **EXEC_STATUS}, (), {SNAP + "execution_tape_status.json": "{}"}, "other", "", 0),
    "worker_unreadable": ({**FRESH, **EXEC_STATUS}, (), {SNAP + "execution_tape_status.json": "{not json"}, "other", "", 0),
    "task_ready": ({**FRESH, **EXEC_STATUS}, (), {}, "other", "Ready", 3),
    "task_disabled": ({**FRESH, **EXEC_STATUS}, (), {}, "other", "Disabled", 0),
    "no_evidence": ({}, (), {}, "roll", "", 1),
}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.autocrlf=false", *args],
        cwd=cwd, check=True, capture_output=True, timeout=60,
    )


def _template(root: Path, registry_text: str) -> Path:
    repo = root / "template"
    (repo / "scripts" / "ops").mkdir(parents=True)
    shutil.copyfile(SCRIPT, repo / "scripts" / "ops" / "roll_verdict.ps1")
    shutil.copyfile(BASELINE, repo / "scripts" / "ops" / "roll_verdict_pre_registry.ps1")
    (repo / "config").mkdir()
    (repo / "config" / "capture_families.json").write_text(registry_text, encoding="utf-8", newline="\n")
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "init", "-q", "-b", "master")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    for branch, rel in BRANCH_EDITS.items():
        _git(repo, "checkout", "-q", "-b", branch, "master")
        (repo / rel).write_text("changed\n", encoding="utf-8", newline="\n")
        _git(repo, "commit", "-q", "-am", branch)
    _git(repo, "checkout", "-q", "master")
    return repo


def _materialise(template: Path, target: Path, statuses: dict, aged: tuple, raw: dict) -> Path:
    shutil.copytree(template, target)
    now = time.time()
    for rel, doc in statuses.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc), encoding="utf-8")
        if rel in aged:
            os.utime(path, (now - OLD, now - OLD))
    for rel, text in raw.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return target


def _run(tmp_path: Path, cases: list[dict]) -> dict[tuple[str, str], dict]:
    cases_file = tmp_path / "cases.json"
    results_file = tmp_path / "results.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    env = dict(os.environ, RV_CASES=str(cases_file), RV_RESULTS=str(results_file))
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", RUNNER],
        env=env, check=True, capture_output=True, timeout=600,
    )
    rows = json.loads(results_file.read_text(encoding="utf-8-sig"))
    rows = rows if isinstance(rows, list) else [rows]
    return {(row["id"], Path(row["script"]).name): row for row in rows}


def test_baseline_fixture_is_the_pre_registry_script() -> None:
    assert hashlib.sha256(BASELINE.read_bytes()).hexdigest() == BASELINE_SHA256


def test_registry_script_reproduces_the_pre_registry_verdict_for_every_evidence_shape(tmp_path: Path) -> None:
    template = _template(tmp_path, REGISTRY.read_text(encoding="utf-8"))
    cases = []
    for case_id, (statuses, aged, raw, branch, task_state, _rc) in CASES.items():
        repo = _materialise(template, tmp_path / case_id, statuses, aged, raw)
        for name in ("roll_verdict_pre_registry.ps1", "roll_verdict.ps1"):
            cases.append({
                "id": case_id, "branch": branch, "task_state": task_state,
                "script": str(repo / "scripts" / "ops" / name),
            })
    results = _run(tmp_path, cases)

    for case_id, (*_unused, expected_rc) in CASES.items():
        before = results[(case_id, "roll_verdict_pre_registry.ps1")]
        after = results[(case_id, "roll_verdict.ps1")]
        assert before["rc"] == expected_rc, (case_id, before["out"])
        assert (after["rc"], after["out"]) == (before["rc"], before["out"]), case_id


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda doc: doc.pop("platform"), id="no_platform_block"),
        pytest.param(lambda doc: doc["platform"].update(roll_closures=[]), id="empty_closures"),
        pytest.param(lambda doc: doc["platform"]["roll_closures"][0].update(status_path="data/../x.json"), id="escaping_path"),
        pytest.param(lambda doc: doc["platform"]["roll_closures"][4].update(arming="sometimes"), id="unknown_arming"),
    ],
)
def test_unreadable_registry_is_undecidable_not_a_shorter_list(tmp_path: Path, mutate) -> None:
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    mutate(doc)
    template = _template(tmp_path, json.dumps(doc))
    repo = _materialise(template, tmp_path / "case", FRESH, (), {})
    results = _run(tmp_path, [{
        "id": "bad", "branch": "docs", "task_state": "", "script": str(repo / "scripts" / "ops" / "roll_verdict.ps1"),
    }])
    row = results[("bad", "roll_verdict.ps1")]
    assert row["rc"] == 1
    assert row["out"].startswith("UNDECIDABLE: capture closure registry unreadable: config\\capture_families.json")
