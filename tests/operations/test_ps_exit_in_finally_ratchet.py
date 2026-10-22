"""Exit codes of ops scripts stopped by Ctrl+C under Windows PowerShell 5.1.

Guards: a Ctrl+C-stopped PS 5.1 -File ops script keeps the exit code of its final finally or trap (workstation pre-gate FAIL receipt with exit 0, 2026-10-22).

Measured on PS 5.1 (2026-10-22, scratch scripts, console Ctrl+C under ``-File``):

* An *advanced* script (``[CmdletBinding()]`` or any ``[Parameter()]``
  attribute) that is stopped runs its ``finally`` blocks, but the code of an
  ``exit`` issued there is dropped and the process exits 0. A plain script keeps
  it. Calling ``$Host.SetShouldExit(<code>)`` immediately before the ``exit``
  keeps the code. The same holds for an ``exit`` inside a same-file function
  that a ``finally`` calls.
* A ``trap`` also runs during the stop, in any script, but it cannot start a
  command: the first command (a cmdlet or a function such as a refusal helper)
  ends the trap and the process exits 0. A bare ``exit`` in a trap survives.
  ``$Host.SetShouldExit(<code>)`` as the trap's first statement is a method
  call, so it runs and the code survives.
* ``catch`` blocks do not run for a stop, so an ``exit`` there needs nothing.

So this ratchet requires, over every ``scripts/ops/*.ps1``:

* in an advanced script, every ``exit`` lexically inside a ``finally`` (at any
  nesting) or inside a same-file function reachable from a ``finally`` is
  immediately preceded by ``$Host.SetShouldExit(<the same code>)``;
* in any script, every ``trap`` that can exit (directly or through a reachable
  same-file function) starts with ``$Host.SetShouldExit(...)``.

``SetShouldExit`` sets the *host's* exit code: a script that carries it ends an
interactive or line-by-line host session it was invoked in-process from, so
these scripts are run with ``powershell.exe -File`` (or from a fresh shell).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
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

# Fixed on its own branch (claude/fix-interrupted-pregate-exit-20261022,
# f23cb43bda269e656349b1374db12e3cbbec8bf1); tolerated whether or not that fix
# has landed. Remove the entry once it is on master.
PENDING_ELSEWHERE = {"workstation_pregate.ps1"}

_SCAN = r"""
$ErrorActionPreference = 'Stop'
function Test-IsAdvanced($paramBlock) {
    if (-not $paramBlock) { return $false }
    foreach ($a in $paramBlock.Attributes) {
        if ($a.TypeName.Name -in @('CmdletBinding', 'System.Management.Automation.CmdletBindingAttribute')) { return $true }
    }
    foreach ($p in $paramBlock.Parameters) {
        foreach ($a in $p.Attributes) {
            if ($a -is [System.Management.Automation.Language.AttributeAst] -and
                $a.TypeName.Name -in @('Parameter', 'System.Management.Automation.ParameterAttribute')) { return $true }
        }
    }
    return $false
}
function Get-HostExitArgument($statement) {
    # The argument text of a `$Host.SetShouldExit(<arg>)` statement, else $null.
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
    return $call.Arguments[0].Extent.Text
}
function Get-Exits($node) {
    @($node.FindAll({ param($n) $n -is [System.Management.Automation.Language.ExitStatementAst] }, $true))
}
function Get-ReachableFunctions($roots, $functions) {
    # Same-file functions called (transitively) from the given ASTs.
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
    $functions = @{}
    foreach ($definition in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        $key = $definition.Name.ToLowerInvariant()
        if (-not $functions.ContainsKey($key)) { $functions[$key] = @() }
        $functions[$key] += $definition
    }
    if (Test-IsAdvanced $ast.ParamBlock) {
        $finallyBlocks = @($ast.FindAll({ param($n)
            $n -is [System.Management.Automation.Language.TryStatementAst] -and $n.Finally }, $true) | ForEach-Object { $_.Finally })
        $exits = @()
        foreach ($block in $finallyBlocks) { $exits += Get-Exits $block }
        foreach ($name in (Get-ReachableFunctions $finallyBlocks $functions)) {
            foreach ($definition in $functions[$name]) { $exits += Get-Exits $definition.Body }
        }
        $reported = @{}
        foreach ($exit in $exits) {
            $id = $exit.Extent.StartOffset
            if ($reported.ContainsKey($id)) { continue }
            $reported[$id] = $true
            $expected = if ($exit.Pipeline) { $exit.Pipeline.Extent.Text } else { '0' }
            $statements = @($exit.Parent.Statements)
            $index = [array]::IndexOf($statements, $exit)
            $hostArgument = if ($index -gt 0) { Get-HostExitArgument $statements[$index - 1] } else { $null }
            if ($hostArgument -ne $expected) {
                "${path}:$($exit.Extent.StartLineNumber) finally exit '$($exit.Extent.Text)' is not immediately preceded by `$Host.SetShouldExit($expected)"
            }
        }
    }
    foreach ($trap in $ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.TrapStatementAst] }, $true)) {
        $canExit = (Get-Exits $trap.Body).Count -gt 0
        if (-not $canExit) {
            foreach ($name in (Get-ReachableFunctions @($trap.Body) $functions)) {
                foreach ($definition in $functions[$name]) { if ((Get-Exits $definition.Body).Count) { $canExit = $true } }
            }
        }
        if (-not $canExit) { continue }
        $first = @($trap.Body.Statements) | Select-Object -First 1
        if ($null -eq $first -or $null -eq (Get-HostExitArgument $first)) {
            "${path}:$($trap.Extent.StartLineNumber) trap can exit but does not start with `$Host.SetShouldExit(...)"
        }
    }
}
"""


def _scan(paths: list[Path], tmp_path: Path) -> list[str]:
    assert WINDOWS_POWERSHELL is not None
    script = tmp_path / f"exit_scan_{hashlib.sha256(_SCAN.encode()).hexdigest()[:12]}.ps1"
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


FIXTURES = {
    # Flagged.
    "bad_finally_cmdlet.ps1": "[CmdletBinding()]\nparam()\ntry { 1 } finally { exit 1 }\n",
    "bad_finally_nested.ps1": (
        "param([Parameter()][string]$X)\n$c = 2\n"
        "try { 1 } finally { try { 2 } finally { if ($c) { exit $c } } }\n"
    ),
    "bad_finally_function.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Leave($c) { Write-Output $c; exit $c }\n"
        "function Close { Leave 3 }\ntry { 1 } finally { Close }\n"
    ),
    "bad_finally_wrong_code.ps1": (
        "[CmdletBinding()]\nparam()\n$c = 4\ntry { 1 } finally { $Host.SetShouldExit(1); exit $c }\n"
    ),
    "bad_finally_not_adjacent.ps1": (
        "[CmdletBinding()]\nparam()\n$c = 5\ntry { 1 } finally { $Host.SetShouldExit($c); Write-Host x; exit $c }\n"
    ),
    "bad_trap_plain.ps1": "param()\ntrap { Write-Error x -ErrorAction Continue; exit 1 }\n1\n",
    "bad_trap_function.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Refuse { $Host.SetShouldExit(1); exit 1 }\ntrap { Refuse }\n1\n"
    ),
    # Spared.
    "plain_finally.ps1": "param([string]$X)\ntry { 1 } finally { exit 1 }\n",
    "fixed_finally.ps1": (
        "[CmdletBinding()]\nparam()\n$c = 6\ntry { 1 } finally { Write-Host x; $Host.SetShouldExit($c); exit $c }\n"
    ),
    "fixed_finally_function.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Leave($c) { $Host.SetShouldExit($c); exit $c }\ntry { 1 } finally { Leave 7 }\n"
    ),
    "fixed_trap.ps1": (
        "[CmdletBinding()]\nparam()\nfunction Refuse { exit 1 }\ntrap { $Host.SetShouldExit(1); Refuse }\n1\n"
    ),
    "catch_exit.ps1": "[CmdletBinding()]\nparam()\ntry { 1 } catch { exit 1 }\n",
    "trap_without_exit.ps1": "[CmdletBinding()]\nparam()\ntrap { Write-Host x; continue }\n1\n",
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
    # One hit per defect: the shared helper in bad_finally_function is reported once.
    assert len(hits) == len(flagged), hits


@pytest.mark.spawns
def test_no_ops_script_loses_its_exit_code_when_stopped(tmp_path: Path) -> None:
    paths = sorted(OPS.glob("*.ps1"))
    assert len(paths) > 50, "expected to scan the ops PowerShell scripts"
    hits = [hit for hit in _scan(paths, tmp_path)
            if Path(re.match(r"^(.*?\.ps1):\d+ ", hit).group(1)).name not in PENDING_ELSEWHERE]
    assert hits == [], (
        "A Ctrl+C-stopped Windows PowerShell 5.1 -File script exits 0 instead of the code of an "
        "`exit` in an advanced script's finally, or of any trap that starts a command first. "
        "Put `$Host.SetShouldExit(<code>)` immediately before the finally exit, or first in the trap:\n"
        + "\n".join(hits)
    )
