"""Guard the boundary of the shared PowerShell host (tests/powershell_host.py).

Inside the shared host ``$PID`` is the long-lived host process, not a fresh child, and an
``exit N`` is swallowed. A test that depends on process identity or exit codes must keep
a real ``powershell.exe`` child. These guards find every shared-host call site by AST and
fail if its function:

* carries PowerShell text that names the process identity (``$PID``, ``Get-Process``,
  ``GetCurrentProcess``, ``StartTime``, ``Win32_Process``) -- checked everywhere;
* asserts a non-zero ``returncode`` -- checked everywhere;
* invokes, directly or transitively, an ``scripts/ops`` PowerShell function that reads
  ``$PID``, queries processes, or calls ``exit`` -- checked with the PowerShell parser on
  Windows.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
OPS = ROOT / "scripts" / "ops"
HOST_FUNCTIONS = {"run_command", "run_powershell_command"}
IDENTITY_TEXT = re.compile(
    r"\$PID\b|Get-Process|GetCurrentProcess|StartTime|Win32_Process", re.IGNORECASE
)


def _shared_host_sites() -> list[tuple[str, str, ast.FunctionDef]]:
    sites = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name in {"powershell_host.py", Path(__file__).name}:
            continue
        source = path.read_text(encoding="utf-8")
        if "powershell_host" not in source:
            continue
        tree = ast.parse(source)
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            calls = [
                node
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in HOST_FUNCTIONS
            ]
            if calls:
                sites.append((path.relative_to(ROOT).as_posix(), function.name, function))
    return sites


def _strings(function: ast.FunctionDef) -> list[str]:
    return [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _asserts_nonzero_returncode(function: ast.FunctionDef) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        if not any(
            isinstance(item, ast.Attribute) and item.attr == "returncode" for item in operands
        ):
            continue
        for operator, right in zip(node.ops, node.comparators):
            if isinstance(operator, ast.NotEq):
                return True
            if (
                isinstance(operator, ast.Eq)
                and isinstance(right, ast.Constant)
                and right.value != 0
            ):
                return True
    return False


def test_shared_host_call_sites_exist() -> None:
    assert _shared_host_sites(), "no shared-host call site found; the guard is vacuous"


def test_shared_host_sites_never_name_the_process_identity() -> None:
    offenders = [
        f"{path}::{name}: {match.group(0)}"
        for path, name, function in _shared_host_sites()
        for text in _strings(function)
        for match in IDENTITY_TEXT.finditer(text)
    ]
    assert offenders == []


def test_shared_host_sites_never_assert_an_exit_code() -> None:
    offenders = [
        f"{path}::{name}"
        for path, name, function in _shared_host_sites()
        if _asserts_nonzero_returncode(function)
    ]
    assert offenders == []


_CLOSURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$definitions = @{}
foreach ($file in Get-ChildItem -LiteralPath $env:GUARD_OPS -Filter '*.ps1' -Recurse -File) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $file.FullName, [ref]$tokens, [ref]$errors)
    foreach ($function in $ast.FindAll({ param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        if (-not $definitions.ContainsKey($function.Name)) {
            $definitions[$function.Name] = New-Object System.Collections.ArrayList
        }
        [void]$definitions[$function.Name].Add($function)
    }
}
$processCommands = @('Get-Process', 'Stop-Process', 'Wait-Process', 'Get-CimInstance', 'Get-WmiObject')
$report = [ordered]@{}
foreach ($site in (Get-Content -Raw -LiteralPath $env:GUARD_SITES | ConvertFrom-Json)) {
    $roots = New-Object System.Collections.ArrayList
    foreach ($text in @($site.strings)) {
        $tokens = $null; $errors = $null
        $parsed = [System.Management.Automation.Language.Parser]::ParseInput(
            [string]$text, [ref]$tokens, [ref]$errors)
        foreach ($command in $parsed.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.CommandAst] }, $true)) {
            # Python constants such as an expected 'FAIL' parse as bare commands; real
            # ops functions are Verb-Noun.
            if ([string]$command.GetCommandName() -match '\A[A-Za-z]+-[A-Za-z0-9]+\z') {
                [void]$roots.Add([string]$command.GetCommandName())
            }
        }
        foreach ($constant in $parsed.FindAll({ param($node)
            $node -is [System.Management.Automation.Language.StringConstantExpressionAst] }, $true)) {
            # Function names passed as data (the status helpers extract functions by
            # name); only Verb-Noun strings, so words like 'FAIL' are not names.
            if ([string]$constant.Value -match '\A[A-Za-z]+-[A-Za-z0-9]+\z') {
                [void]$roots.Add([string]$constant.Value)
            }
        }
    }
    $seen = @{}
    $queue = New-Object System.Collections.Queue
    foreach ($name in $roots) { if ($name -and $definitions.ContainsKey($name)) { $queue.Enqueue($name) } }
    $findings = New-Object System.Collections.ArrayList
    while ($queue.Count) {
        $name = $queue.Dequeue()
        if ($seen.ContainsKey($name)) { continue }
        $seen[$name] = $true
        foreach ($body in $definitions[$name]) {
            foreach ($command in $body.FindAll({ param($node)
                $node -is [System.Management.Automation.Language.CommandAst] }, $true)) {
                $called = $command.GetCommandName()
                if ($called -and $definitions.ContainsKey($called)) { $queue.Enqueue($called) }
                if ($called -in $processCommands) { [void]$findings.Add("$name calls $called") }
            }
            foreach ($variable in $body.FindAll({ param($node)
                $node -is [System.Management.Automation.Language.VariableExpressionAst] -and
                $node.VariablePath.UserPath -ieq 'PID' }, $true)) {
                [void]$findings.Add("$name reads `$PID")
            }
            foreach ($exit in $body.FindAll({ param($node)
                $node -is [System.Management.Automation.Language.ExitStatementAst] }, $true)) {
                [void]$findings.Add("$name calls exit")
            }
        }
    }
    $report[[string]$site.id] = [ordered]@{ reached = $seen.Count; findings = @($findings) }
}
$report | ConvertTo-Json -Depth 4 -Compress
"""


@pytest.mark.skipif(os.name != "nt", reason="requires the Windows PowerShell parser")
def test_shared_host_sites_never_reach_process_identity_or_exit_in_ops_scripts(
    tmp_path: Path,
) -> None:
    sites = [
        {"id": f"{path}::{name}", "strings": _strings(function)}
        for path, name, function in _shared_host_sites()
    ]
    # Negative control: this helper names its temporary file with $PID, which is why
    # the manifest test keeps a real child. The analysis must flag it.
    control = {
        "id": "control::immutable_writer",
        "strings": [". $env:X\nWrite-WeatherIntegrationImmutableJson -Path a -Payload @{}"],
    }
    sites_path = tmp_path / "sites.json"
    sites_path.write_text(json.dumps([*sites, control]), encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CLOSURE_SCRIPT],
        env={**os.environ, "GUARD_OPS": str(OPS), "GUARD_SITES": str(sites_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report) == {site["id"] for site in sites} | {control["id"]}
    assert "Write-WeatherIntegrationImmutableJson reads $PID" in report.pop(control["id"])[
        "findings"
    ]
    # The status helpers must resolve their extracted functions, or the closure is empty.
    assert any(
        entry["reached"] > 10 for site, entry in report.items() if "test_status_script" in site
    ), report
    offenders = {site: entry["findings"] for site, entry in report.items() if entry["findings"]}
    assert offenders == {}
