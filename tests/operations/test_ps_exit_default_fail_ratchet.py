"""Default-fail exit codes for the critical ops wrappers under Windows PowerShell 5.1.

Guards: a critical ops wrapper (quiet-window merge, docs light path, workstation heavy, bounded suite, integration-attempt suite, training window, daily refresh) never exits 0 after an error or a Ctrl+C stop (exit-0-after-stop finding, 2026-10-22).

Measured on PS 5.1 (2026-10-22, scratch scripts, console Ctrl+C under ``-File``):
a stopped script runs its ``finally`` blocks but nothing after them and no
``catch``, so it exits 0 unless the code is issued from a ``finally``; an
advanced script also drops the code of that ``exit`` unless
``$Host.SetShouldExit(<code>)`` runs immediately before it. An ``exit`` inside
the ``try`` runs the ``finally`` too, so the ``finally``'s own ``exit`` decides
the process code.

So, for each script in ``CRITICAL``, this ratchet requires:

* the script's last top-level statement is a ``try`` with a ``finally`` whose
  last two statements are ``$Host.SetShouldExit($<var>)`` and ``exit $<var>``;
* ``$<var>`` is assigned a non-zero integer literal at top level before that
  ``try`` (default-fail);
* every ``exit`` in the ``try`` body, its ``catch`` clauses, or a same-file
  function reachable from them is immediately preceded by an assignment of the
  same code to ``$<var>`` (or ``$script:<var>``), so the ``finally`` re-issues it,
  and none of them is a literal ``exit 0`` (success is ``$<var> = 0`` then
  ``exit $<var>``, only on the proven-success path);
* no script-level ``return`` (one not inside a function definition or a script
  block expression) appears in the ``try`` body or its ``catch`` clauses: it
  leaves without recording a code, so the outcome would rest on whatever
  ``$<var>`` last held.

``tests/operations/test_ps_exit_in_finally_ratchet.py`` (a separate branch)
covers every ``exit`` in any ``finally`` and every exiting ``trap``.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
WINDOWS_POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None,
    reason="the stop/exit-code rule is specific to Windows PowerShell 5.1",
)

CRITICAL = (
    "quiet_window_merge.ps1",
    "docs_light_path.ps1",
    "workstation_heavy.ps1",
    "bounded_worktree_test_suite.ps1",
    "integration_attempt_suite.ps1",
    "training_window.ps1",
    "daily_refresh.ps1",
)

_SCAN = r"""
$ErrorActionPreference = 'Stop'
function Get-HostExitVariable($statement) {
    # The variable name in a `$Host.SetShouldExit($name)` statement, else $null.
    if ($statement -isnot [System.Management.Automation.Language.PipelineAst]) { return $null }
    if ($statement.PipelineElements.Count -ne 1) { return $null }
    $element = $statement.PipelineElements[0]
    if ($element -isnot [System.Management.Automation.Language.CommandExpressionAst]) { return $null }
    $call = $element.Expression
    if ($call -isnot [System.Management.Automation.Language.InvokeMemberExpressionAst]) { return $null }
    if ($call.Static -or $call.Member.Extent.Text -ne 'SetShouldExit') { return $null }
    if ($call.Expression -isnot [System.Management.Automation.Language.VariableExpressionAst] -or
        $call.Expression.VariablePath.UserPath -ne 'Host') { return $null }
    if (@($call.Arguments).Count -ne 1) { return $null }
    $argument = $call.Arguments[0]
    if ($argument -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $null }
    return $argument.VariablePath.UserPath
}
function Get-ExitVariable($statement) {
    # The variable name in an `exit $name` statement, else $null.
    if ($statement -isnot [System.Management.Automation.Language.ExitStatementAst] -or -not $statement.Pipeline) { return $null }
    $pipeline = $statement.Pipeline
    if ($pipeline -isnot [System.Management.Automation.Language.PipelineAst] -or $pipeline.PipelineElements.Count -ne 1) { return $null }
    $element = $pipeline.PipelineElements[0]
    if ($element -isnot [System.Management.Automation.Language.CommandExpressionAst]) { return $null }
    if ($element.Expression -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $null }
    return $element.Expression.VariablePath.UserPath
}
function Get-AssignedName($statement) {
    # ($name, rhsText) for `$name = rhs` or `$script:name = rhs`, else $null.
    if ($statement -isnot [System.Management.Automation.Language.AssignmentStatementAst]) { return $null }
    if ($statement.Operator -ne 'Equals') { return $null }
    $left = $statement.Left
    if ($left -isnot [System.Management.Automation.Language.VariableExpressionAst]) { return $null }
    $name = $left.VariablePath.UserPath -replace '^script:', ''
    return ,@($name, $statement.Right.Extent.Text.Trim())
}
function Get-IntLiteral($text) {
    $value = 0
    if ([int]::TryParse($text, [ref]$value)) { return $value }
    return $null
}
function Get-ReachableFunctions($roots, $functions) {
    $seen = @{}
    $queue = New-Object System.Collections.Queue
    foreach ($root in $roots) { $queue.Enqueue($root) }
    while ($queue.Count) {
        $node = $queue.Dequeue()
        foreach ($command in $node.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true)) {
            $name = [string]$command.GetCommandName()
            if (-not $name) { continue }
            $key = $name.ToLowerInvariant()
            if ($functions.ContainsKey($key) -and -not $seen.ContainsKey($key)) {
                $seen[$key] = $true
                foreach ($definition in $functions[$key]) { $queue.Enqueue($definition.Body) }
            }
        }
    }
    return @($seen.Keys)
}
foreach ($path in (Get-Content -LiteralPath $env:SCAN_LIST)) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { "${path}:0 parse error: $($errors[0].Message)"; continue }
    $top = @($ast.EndBlock.Statements)
    $try = if ($top.Count) { $top[-1] } else { $null }
    if ($try -isnot [System.Management.Automation.Language.TryStatementAst] -or -not $try.Finally) {
        "${path}:0 last top-level statement is not a try with a finally"
        continue
    }
    $final = @($try.Finally.Statements)
    $var = if ($final.Count) { Get-ExitVariable $final[-1] } else { $null }
    if (-not $var) {
        "${path}:$($try.Finally.Extent.EndLineNumber) final finally does not end in exit `$<var>"
        continue
    }
    if ($final.Count -lt 2 -or (Get-HostExitVariable $final[-2]) -ne $var) {
        "${path}:$($final[-1].Extent.StartLineNumber) exit `$$var is not immediately preceded by `$Host.SetShouldExit(`$$var)"
    }
    $initial = $null
    for ($i = 0; $i -lt $top.Count - 1; $i++) {
        $assigned = Get-AssignedName $top[$i]
        if ($assigned -and $assigned[0] -eq $var) { $initial = $assigned[1] }
    }
    $initialValue = if ($null -ne $initial) { Get-IntLiteral $initial } else { $null }
    if ($null -eq $initialValue -or $initialValue -eq 0) {
        "${path}:$($try.Extent.StartLineNumber) `$$var is not initialised to a non-zero integer literal before the try (found '$initial')"
    }
    $functions = @{}
    foreach ($definition in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        $key = $definition.Name.ToLowerInvariant()
        if (-not $functions.ContainsKey($key)) { $functions[$key] = @() }
        $functions[$key] += $definition
    }
    $roots = @($try.Body) + @($try.CatchClauses | ForEach-Object { $_.Body })
    $scopes = @($roots)
    foreach ($name in (Get-ReachableFunctions $roots $functions)) {
        foreach ($definition in $functions[$name]) { $scopes += $definition.Body }
    }
    $reported = @{}
    foreach ($scope in $scopes) {
        foreach ($exit in $scope.FindAll({ param($n) $n -is [System.Management.Automation.Language.ExitStatementAst] }, $true)) {
            $id = $exit.Extent.StartOffset
            if ($reported.ContainsKey($id)) { continue }
            $reported[$id] = $true
            $argument = if ($exit.Pipeline) { $exit.Pipeline.Extent.Text.Trim() } else { '0' }
            if ((Get-IntLiteral $argument) -eq 0 -and $null -ne (Get-IntLiteral $argument)) {
                "${path}:$($exit.Extent.StartLineNumber) literal '$($exit.Extent.Text)' inside the default-fail try"
                continue
            }
            $statements = @($exit.Parent.Statements)
            $index = [array]::IndexOf($statements, $exit)
            $assigned = if ($index -gt 0) { Get-AssignedName $statements[$index - 1] } else { $null }
            $exitVariable = Get-ExitVariable $exit
            $ok = $assigned -and $assigned[0] -eq $var -and (
                $assigned[1] -ceq $argument -or ($exitVariable -replace '^script:', '') -eq $var
            )
            if (-not $ok) {
                "${path}:$($exit.Extent.StartLineNumber) '$($exit.Extent.Text)' is not immediately preceded by `$$var = <the same code>, so the finally would replace its code"
            }
        }
    }
    foreach ($root in $roots) {
        foreach ($return in $root.FindAll({ param($n) $n -is [System.Management.Automation.Language.ReturnStatementAst] }, $true)) {
            $scriptLevel = $true
            for ($node = $return.Parent; $node -and $node -ne $try; $node = $node.Parent) {
                if ($node -is [System.Management.Automation.Language.FunctionDefinitionAst] -or
                    $node -is [System.Management.Automation.Language.ScriptBlockExpressionAst]) { $scriptLevel = $false; break }
            }
            if ($scriptLevel) {
                "${path}:$($return.Extent.StartLineNumber) script-level '$($return.Extent.Text)' inside the default-fail try; leave through `$$var = <code>; exit `$$var instead"
            }
        }
    }
}
"""


def _scan(paths: list[Path], tmp_path: Path) -> list[str]:
    assert WINDOWS_POWERSHELL is not None
    script = tmp_path / f"default_fail_scan_{hashlib.sha256(_SCAN.encode()).hexdigest()[:12]}.ps1"
    script.write_text(_SCAN, encoding="utf-8-sig")
    scan_list = tmp_path / "scan_list.txt"
    scan_list.write_text("\n".join(str(path) for path in paths), encoding="utf-8")
    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "SCAN_LIST": str(scan_list)},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line for line in result.stdout.splitlines() if line.strip()]


_GOOD_TAIL = "finally { Write-Host x; $Host.SetShouldExit($rc); exit $rc }\n"
FIXTURES = {
    # Flagged.
    "bad_no_try.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\nexit $rc\n",
    "bad_no_finally_exit.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { $rc = 0 } finally { Write-Host x }\nexit $rc\n",
    "bad_no_host_exit.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { $rc = 0 } finally { exit $rc }\n",
    "bad_default_zero.ps1": "[CmdletBinding()]\nparam()\n$rc = 0\ntry { 1 } " + _GOOD_TAIL,
    "bad_default_missing.ps1": "[CmdletBinding()]\nparam()\ntry { $rc = 0 } " + _GOOD_TAIL,
    "bad_literal_exit_zero.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { $rc = 0; exit 0 } " + _GOOD_TAIL,
    "bad_unrecorded_exit.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { if ($x) { exit 3 } } " + _GOOD_TAIL,
    "bad_wrong_code.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { $rc = 2; exit 3 } " + _GOOD_TAIL,
    "bad_function_exit.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Leave { exit 4 }\nfunction Fail { Leave }\n$rc = 1\n"
        "try { Fail } " + _GOOD_TAIL
    ),
    "bad_catch_exit.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { 1 } catch { exit 5 } " + _GOOD_TAIL,
    "bad_script_return.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { if ($x) { $rc = 0; return } } " + _GOOD_TAIL,
    "bad_catch_return.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { 1 } catch { return } " + _GOOD_TAIL,
    # Spared.
    "good_minimal.ps1": "[CmdletBinding()]\nparam()\n$rc = 1\ntry { $rc = 0 } " + _GOOD_TAIL,
    "good_nested_returns.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Probe { return 1 }\n$rc = 1\n"
        "try { function Inner { return 2 }; @(1) | ForEach-Object { return }; $null = Probe; $rc = 0 } " + _GOOD_TAIL
    ),
    "good_negative_default.ps1": "[CmdletBinding()]\nparam()\n$rc = -1\ntry { $rc = 0 } " + _GOOD_TAIL,
    "good_recorded_exits.ps1": (
        "[CmdletBinding()]\nparam()\n"
        "function Leave([int]$c) { $script:rc = $c; exit $c }\n"
        "function Refuse { $script:rc = 1\n exit 1 }\n"
        "exit 0\n"  # pre-flight, outside the try
        "$rc = 1\n"
        "try { if ($a) { Refuse }; if ($b) { Leave 4 }; if ($c) { $rc = 3; exit 3 }; $rc = 0; exit $rc }\n"
        "catch { $rc = 1; exit 1 }\n" + _GOOD_TAIL
    ),
}


@pytest.mark.spawns
def test_detector_flags_each_defect_and_spares_the_fixes(tmp_path: Path) -> None:
    paths = []
    for name, text in FIXTURES.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    hits = _scan(paths, tmp_path)
    flagged = {name for name in FIXTURES if any(f"{name}:" in hit for hit in hits)}
    assert flagged == {name for name in FIXTURES if name.startswith("bad_")}, hits


@pytest.mark.spawns
def test_critical_ops_wrappers_default_fail_their_exit_code(tmp_path: Path) -> None:
    paths = [OPS / name for name in CRITICAL]
    assert all(path.is_file() for path in paths), [str(path) for path in paths if not path.is_file()]
    hits = _scan(paths, tmp_path)
    assert hits == [], (
        "These wrappers must issue a default-fail exit code from their final finally: initialise the code "
        "variable to a non-zero literal before the try, record each exit's code in it first, set 0 only on "
        "the proven-success path, and end the finally with `$Host.SetShouldExit($<var>); exit $<var>`:\n"
        + "\n".join(hits)
    )
