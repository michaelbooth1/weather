import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ops" / "staleness_sweep.ps1"


def test_historical_operations_evidence_is_not_reported_as_unreachable_canonical_docs():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert "$historicalUnindexedNames" in text
    assert '"OVERNIGHT_BRIEFINGS.md"' in text
    assert "(?:19|20)\\d{2}[-_]\\d{2}[-_]\\d{2}" in text


def test_state_of_play_does_not_need_to_copy_historical_mission_references():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Add-Finding "docs/in_flight_drift"' not in text
    assert "recently commissioned" not in text


def test_settlement_freshness_requires_real_content_not_a_none_row():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert '$row.settlement_source' in text
    assert '$row.PSObject.Properties["settlement_high"]' in text
    assert '$source -in @("none", "null")' in text
    assert "latest real settlement target" in text


def test_legacy_archive_warning_tracks_the_training_hold_switch():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Get-ScheduledTask -TaskName "WeatherTrainingWindow"' in text
    assert '$trainingHeld' in text
    assert '"WARN"' in text


def test_unapproved_remote_branches_do_not_imply_an_armed_merge_queue():
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert 'Add-Finding "git/no_merge_trigger"' not in text
    assert "branch -r --no-merged origin/master" not in text
    assert 'Add-Finding "git/unmerged_branches" "OK"' in text
    assert "only an explicit immutable exact-tip queue authorizes integration" in text


ALWAYS_CLOSURES = {
    "snapshot": "data\\snapshots\\loop_supervisor_status.json",
    "clob": "data\\snapshots\\clob_loop_supervisor_status.json",
    "observation-trigger": "data\\snapshots\\observation_trigger_supervisor_status.json",
    "clob-enrichment": "data\\snapshots\\clob_enrichment_status.json",
}
EXECUTION_TAPE = {"execution-tape": "data\\snapshots\\execution_tape_supervisor_status.json"}

# Runs the shipped closure-list block (from "$closureFiles = [ordered]@{}" up to
# "function Get-ClosureStatus") against a fixture repo, with Add-Finding and Get-ScheduledTask
# stubbed, so the registry read is executed rather than matched as text.
CLOSURE_BLOCK_RUNNER = r"""
$ErrorActionPreference = 'Stop'
$text = Get-Content -LiteralPath $env:SW_SCRIPT -Raw
$start = $text.IndexOf('$closureFiles = [ordered]@{}')
$end = $text.IndexOf('function Get-ClosureStatus')
if ($start -lt 0 -or $end -le $start) { throw 'closure block markers not found' }
$block = $text.Substring($start, $end - $start)
$global:findings = @()
function Add-Finding { $global:findings += [pscustomobject]@{ check = [string]$args[0]; severity = [string]$args[1]; detail = [string]$args[2] } }
function Get-ScheduledTask {
    [CmdletBinding()]
    param([string]$TaskName)
    if ($env:SW_TASK_STATE -and $TaskName -eq 'WeatherExecutionTapeSupervisor') {
        return [pscustomobject]@{ TaskName = $TaskName; State = $env:SW_TASK_STATE }
    }
    return $null
}
$results = @()
$cases = Get-Content -LiteralPath $env:SW_CASES -Raw | ConvertFrom-Json
foreach ($case in $cases) {
    $repo = [string]$case.repo
    $env:SW_TASK_STATE = [string]$case.task_state
    $global:findings = @()
    . ([scriptblock]::Create($block))
    $results += [pscustomobject]@{ id = $case.id; closures = $closureFiles; findings = @($global:findings) }
}
ConvertTo-Json -InputObject @($results) -Depth 5 | Set-Content -LiteralPath $env:SW_RESULTS -Encoding utf8
"""


@pytest.mark.spawns
@pytest.mark.skipif(os.name != "nt" or shutil.which("powershell") is None, reason="requires Windows PowerShell")
def test_closure_list_comes_from_the_registry_and_the_execution_tape_only_while_armed_or_active(tmp_path):
    registry = (REPO_ROOT / "config" / "capture_families.json").read_text(encoding="utf-8")
    snap = "data/snapshots/"
    no_task_doc = json.loads(registry)
    no_task_doc["platform"]["roll_closures"][4].pop("task")
    no_task_registry = json.dumps(no_task_doc)
    cases = {
        # id: (task state, raw files, expected closure ids or None for registry failure)
        "unarmed": ("", {}, ALWAYS_CLOSURES),
        "task_ready": ("Ready", {}, {**ALWAYS_CLOSURES, **EXECUTION_TAPE}),
        "task_disabled": ("Disabled", {}, ALWAYS_CLOSURES),
        "writer_lock": ("", {snap + ".execution_tape_status.json.writer.lock": ""}, {**ALWAYS_CLOSURES, **EXECUTION_TAPE}),
        "worker_running": ("", {snap + "execution_tape_status.json": '{"state": "RUNNING"}'}, {**ALWAYS_CLOSURES, **EXECUTION_TAPE}),
        "worker_stopped": ("", {snap + "execution_tape_status.json": '{"state": "STOPPED"}'}, ALWAYS_CLOSURES),
        "worker_unreadable": ("", {snap + "execution_tape_status.json": "{not json"}, ALWAYS_CLOSURES),
        "registry_broken": ("", {"config/capture_families.json": '{"families": {}}'}, None),
        "optional_without_task": ("", {"config/capture_families.json": no_task_registry}, None),
    }
    payload = []
    for case_id, (task_state, raw, _expected) in cases.items():
        repo = tmp_path / case_id
        (repo / "config").mkdir(parents=True)
        (repo / "config" / "capture_families.json").write_text(registry, encoding="utf-8")
        for rel, text in raw.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text, encoding="utf-8")
        payload.append({"id": case_id, "repo": str(repo), "task_state": task_state})
    (tmp_path / "cases.json").write_text(json.dumps(payload), encoding="utf-8")
    env = dict(
        os.environ, SW_SCRIPT=str(SCRIPT), SW_CASES=str(tmp_path / "cases.json"), SW_RESULTS=str(tmp_path / "out.json")
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", CLOSURE_BLOCK_RUNNER],
        env=env, check=True, capture_output=True, timeout=300,
    )
    results = {row["id"]: row for row in json.loads((tmp_path / "out.json").read_text(encoding="utf-8-sig"))}

    for case_id, (_state, _raw, expected) in cases.items():
        row = results[case_id]
        if expected is None:
            assert row["closures"] == {}
            assert [(f["check"], f["severity"]) for f in row["findings"]] == [("closure/registry", "CRITICAL")]
            continue
        assert row["closures"] == expected, case_id
        assert list(row["closures"]) == list(expected), case_id
        assert row["findings"] == [], case_id
