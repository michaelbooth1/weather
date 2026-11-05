"""Shared proof that a registrar test reached only its Scheduler stubs, never the real Task Scheduler.

Registrar tests define PowerShell functions named like the ScheduledTasks commands and then run the
real registrar. That is only safe while every call resolves to the stub. The real commands are CDXML
functions that autoload from the ScheduledTasks module, so a missing or misspelled stub silently
reaches the host scheduler (the earlier CDXML autoload incident).

Use it in two steps:

* Put :func:`prologue` at the top of the harness, before the stubs. It sets ``WEATHER_TASK_TEST``,
  so the registrars' ``Assert-WeatherScheduledTaskTestIsolation`` refuses any non-stub, and it sets
  a command breakpoint on every Scheduler command. Each invocation appends one JSON line to the
  ledger: the command name, whether a module-less stub was defined when it ran, the owning module,
  and whether the ScheduledTasks module had been loaded.
* After the child exits, call :func:`assert_only_stubs_invoked` with the exact set of commands the
  case must have reached.
* A refusal test drops one stub and adds :func:`module_lookalike` for it. Never drop a stub without
  a lookalike: a regressed guard would then reach the real Task Scheduler.

This module only builds text and reads the ledger. The caller starts the process, so the caller
keeps ``@pytest.mark.spawns``.
"""

from __future__ import annotations

import json
from pathlib import Path

TEST_ENV = "WEATHER_TASK_TEST"
GUARD_SCRIPT = "scheduled_task_test_guard.ps1"
SCHEDULER_COMMANDS = (
    "Register-ScheduledTask",
    "Unregister-ScheduledTask",
    "Get-ScheduledTask",
    "Get-ScheduledTaskInfo",
    "Export-ScheduledTask",
    "Disable-ScheduledTask",
    "Enable-ScheduledTask",
    "Set-ScheduledTask",
    "Start-ScheduledTask",
    "Stop-ScheduledTask",
)


def _quote(text: str) -> str:
    return "'" + str(text).replace("'", "''") + "'"


def prologue(ledger: Path) -> str:
    """PowerShell to place before the stubs: the test env guard plus one breakpoint per command."""
    names = ",".join(_quote(name) for name in SCHEDULER_COMMANDS)
    return (
        f"$env:{TEST_ENV} = '1'\n"
        f"$weatherStubLedger = {_quote(ledger)}\n"
        f"foreach ($weatherStubName in @({names})) {{\n"
        "    $weatherStubAction = [scriptblock]::Create(\n"
        "        '$f = Get-Item -LiteralPath ''function:\\' + $weatherStubName + ''' -ErrorAction SilentlyContinue; ' +\n"
        "        '$row = [ordered]@{command=''' + $weatherStubName + '''; stub=($null -ne $f -and ' +\n"
        "        '[string]::IsNullOrEmpty([string]$f.ModuleName)); module=[string]$f.ModuleName; ' +\n"
        "        'scheduled_tasks_loaded=[bool](Get-Module ScheduledTasks)}; ' +\n"
        "        'Add-Content -LiteralPath ''' + $weatherStubLedger.Replace(\"'\", \"''\") + ''' ' +\n"
        "        '-Value ($row | ConvertTo-Json -Compress) -Encoding UTF8')\n"
        "    $null = Set-PSBreakpoint -Command $weatherStubName -Action $weatherStubAction\n"
        "}\n"
    )


def module_lookalike(name: str) -> str:
    """PowerShell that defines ``name`` as a function owned by a dynamic module, the shape of the real
    CDXML command. A refusal test drops its stub and adds this instead, so the guard has a non-stub to
    refuse and a regressed guard still reaches only this harmless function, never the host scheduler."""
    return ("$null = New-Module -Name WeatherFakeScheduledTasks -ScriptBlock { function " + name +
            " { $global:weatherFakeRealCommandReached = $true }; Export-ModuleMember -Function * } | Import-Module\n")


def ledger_rows(ledger: Path) -> list[dict]:
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def assert_only_stubs_invoked(ledger: Path, expected: set[str] | frozenset[str]) -> list[dict]:
    """Every Scheduler call hit a module-less stub, the real module never loaded, and the set of
    commands reached is exactly ``expected``."""
    rows = ledger_rows(ledger)
    real = [row for row in rows if not row["stub"] or row["module"] or row["scheduled_tasks_loaded"]]
    assert real == [], f"a Scheduler call did not resolve to a test stub: {real}"
    invoked = {row["command"] for row in rows}
    assert invoked == set(expected), f"Scheduler stubs reached {sorted(invoked)}, expected {sorted(expected)}"
    return rows
