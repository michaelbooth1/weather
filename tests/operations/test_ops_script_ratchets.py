"""Repository-wide PowerShell binding and task-inventory ratchets."""
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell AST")
def test_all_ops_scripts_parse_and_do_not_bind_operators_as_parameters():
    source = r"""
$ErrorActionPreference = 'Stop'
$operators = @('split','replace','match','notmatch','like','notlike','eq','ne','gt','ge','lt','le',
'join','contains','notcontains','in','notin','is','isnot','as','f','shl','shr','band','bor','bxor',
'and','bnot','ccontains','ceq','cge','cgt','cin','cle','clike','clt','cmatch','cne','cnotcontains',
'cnotin','cnotlike','cnotmatch','creplace','csplit','icontains','ieq','ige','igt','iin','ile',
'ilike','ilt','imatch','ine','inotcontains','inotin','inotlike','inotmatch','ireplace','isplit','not','or','xor')
function Find-BindingDefects($ast) {
    @($ast.FindAll({param($n)
        ($n -is [System.Management.Automation.Language.CommandParameterAst] -and
            $operators -contains $n.ParameterName.ToLowerInvariant()) -or
        ($n -is [System.Management.Automation.Language.BinaryExpressionAst] -and
            $n.Operator -eq 'Plus' -and
            $n.Right -is [System.Management.Automation.Language.BinaryExpressionAst] -and
            $n.Right.Operator -eq 'Format')
    }, $true))
}
$failures = @()
$files = @(Get-ChildItem -LiteralPath $env:FIXTURE_OPS -Filter '*.ps1' -Recurse -File)
foreach ($path in $files) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path.FullName,[ref]$tokens,[ref]$errors)
    foreach ($error in $errors) { $failures += "$($path.Name): $($error.Message)" }
    foreach ($hit in (Find-BindingDefects $ast)) {
        $failures += "$($path.Name):$($hit.Extent.StartLineNumber): $($hit.Extent.Text)"
    }
}
$controls = @()
foreach ($text in @('Read-Example -Path x -ireplace y', '"bad {0}" + "suffix" -f 3',
    '("good {0}" + "suffix") -f 3', '"prefix" + ("good {0}" -f 3)')) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$errors)
    $controls += @(Find-BindingDefects $ast).Count
}
@{failures=$failures;controls=$controls;count=$files.Count} | ConvertTo-Json -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", source],
        env={**os.environ, "FIXTURE_OPS": str(OPS)}, capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == len(list(OPS.rglob("*.ps1")))
    assert payload["controls"] == [1, 1, 0, 0]
    assert payload["failures"] == []


def test_all_ops_paths_and_push_identities_have_no_new_host_literals():
    # Exact existing exceptions; count may shrink, never grow. Incident push bindings
    # remain frozen pending the separately reviewed identity-consolidation decision.
    allowed = {
        "boot_recovery.ps1": (1, "deployed bootstrap, separate pinned adoption"),
        "mm_countability_report.ps1": (1, "legacy report root"),
        "production_baseline_scheduler_rpc.ps1": (2, "spent incident identity must stay frozen"),
        "quiet_window_merge.ps1": (4, "reviewed push identity, owner decision to consolidate"),
        "reconcile_integration_attempt.ps1": (2, "reviewed push identity, owner decision to consolidate"),
        "streak_capture_monitor.ps1": (1, "host-local monitor deployment unverified"),
        "verify_mirror_restore.ps1": (4, "paused mirror, credential-path contract; never read credentials"),
    }
    pattern = re.compile(r"""C:\\Users\\micha|["']micha["']|push-oneshot\.log""", re.I)
    for path in OPS.rglob("*.ps1"):
        lines = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if pattern.search(line)]
        assert len(lines) <= allowed.get(path.name, (0, ""))[0], (path.name, lines)


def inventory():
    return json.loads((ROOT / "config" / "scheduled_tasks.json").read_text())["tasks"]


def test_task_inventory_covers_registrars_status_and_generated_docs():
    from weather.operations.operating_reference import collect_constants, render_markdown
    rows = inventory()
    names = {row["name"] for row in rows}
    assert len(names) == len(rows)
    for row in rows:
        assert row["state"] in {"active", "retired", "one-shot"}
        assert isinstance(row["expected_disabled"], bool)
        assert (ROOT / row["owner"]).is_file()
        assert row["registrar"] is None or (ROOT / row["registrar"]).is_file()
        assert row["registration_evidence"]
    for path in OPS.glob("register_*.ps1"):
        source = path.read_text(encoding="utf-8-sig")
        if "Register-ScheduledTask" not in source:
            continue
        defaults = re.findall(r"""\$\w*taskname\s*=\s*["'](Weather[\w-]+)["']""", source, re.I)
        for name in defaults:
            assert name in names, (path, name)
            assert next(row for row in rows if row["name"] == name)["registrar"] == path.relative_to(ROOT).as_posix()
    status = (OPS / "status.ps1").read_text(encoding="utf-8-sig")
    disabled = status.split("$expDisabled = @(", 1)[1].split("\n)", 1)[0]
    disabled_names = set(re.findall(r'"(Weather[\w-]+)"', disabled))
    assert disabled_names == {row["name"] for row in rows if row["expected_disabled"]}
    nonzero = status.split("$expNonZero = @{", 1)[1].split("\n}", 1)[0]
    actual = {name: re.findall(r'"(0x[\w]+)"', codes) for name, codes in
              re.findall(r'"(Weather[\w-]+)"\s*=\s*@\(([^)]+)\)', nonzero)}
    assert actual == {row["name"]: row["expected_nonzero"] for row in rows if row["expected_nonzero"]}
    # All complete Weather literals, including status classifications, must be owned.
    # Project/mutex identities and the all-task selection wildcard are not tasks.
    non_tasks = {"WeatherProject", "WeatherHeavyWorkloadMutexPoisoned", "Weather*"}
    for path in OPS.glob("*.ps1"):
        literals = re.findall(r"""["'](Weather[\w*-]+)["']""", path.read_text(encoding="utf-8-sig"))
        for name in literals:
            if name in non_tasks:
                continue
            assert any(fnmatch.fnmatchcase(name, pattern) for pattern in names), (path, name)
    markdown = render_markdown(collect_constants())
    assert markdown == (ROOT / "docs/operations/OPERATING_REFERENCE.md").read_text(encoding="utf-8")
    assert all(name in markdown for name in names)
    assert "MM quoting" not in markdown and "taker/MM daily roll-over" not in markdown


RETIRED_REGISTRARS = [
    "register_clob_enrichment.ps1", "register_model_market_disagreement_analysis.ps1",
]
# Retired 2026-09-29 (110o part 3): runtime code and registrars deleted. The host
# tasks stay known as retired/expected-Disabled so status keeps classifying them.
DELETED_RETIRED_TASKS = {
    "WeatherTakerBotDailyRoll": "register_taker_bot_daily_roll.ps1",
    "WeatherTakerBotDailyRollSupervisor": "register_taker_bot_daily_roll_supervisor.ps1",
    "WeatherMarketMakingDailyRoll": "register_market_making_daily_roll.ps1",
    "WeatherMarketMakingDailyRollSupervisor": "register_market_making_daily_roll_supervisor.ps1",
}


def test_deleted_bot_tasks_stay_classified_without_a_registrar():
    rows = {row["name"]: row for row in inventory()}
    status = (OPS / "status.ps1").read_text(encoding="utf-8-sig")
    disabled = status.split("$expDisabled = @(", 1)[1].split("\n)", 1)[0]
    for name, registrar in DELETED_RETIRED_TASKS.items():
        row = rows[name]
        assert row["state"] == "retired"
        assert row["expected_disabled"] is True
        assert row["registrar"] is None
        assert f'"{name}"' in disabled
        assert not (OPS / registrar).exists()
    assert not (OPS / "market_making_daily_roll_task.ps1").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell fixture")
@pytest.mark.parametrize("name", RETIRED_REGISTRARS)
@pytest.mark.parametrize("acknowledge", [False, True])
def test_retired_registrars_refuse_before_any_scheduler_action(tmp_path, name, acknowledge):
    from tests.operations.test_ops_alarm_path import run_ps
    (tmp_path / "venv/Scripts").mkdir(parents=True)
    (tmp_path / "venv/Scripts/pythonw.exe").touch()
    (tmp_path / "scripts/ops").mkdir(parents=True)
    result = run_ps(r"""
$ErrorActionPreference = 'Stop'
function New-ScheduledTaskAction { throw 'ACKNOWLEDGED_NO_SCHEDULER_CALL' }
function Register-ScheduledTask { throw 'UNEXPECTED_SCHEDULER_MUTATION' }
$failure = ''
try {
    $arguments = @{RepoRoot=$env:FIXTURE_ROOT}
    if ($env:FIXTURE_ACK -eq 'yes') { $arguments.AcknowledgeRetired = $true }
    $null = & (Join-Path $env:FIXTURE_OPS $env:FIXTURE_NAME) @arguments
} catch { $failure=$_.Exception.Message }
@{error=$failure} | ConvertTo-Json -Compress
""", FIXTURE_ROOT=str(tmp_path), FIXTURE_NAME=name, FIXTURE_ACK="yes" if acknowledge else "no")
    assert ("ACKNOWLEDGED_NO_SCHEDULER_CALL" if acknowledge else "requires explicit -AcknowledgeRetired") in result["error"]
