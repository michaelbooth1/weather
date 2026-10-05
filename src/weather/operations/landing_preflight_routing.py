"""Landing preflight test routing owned by L-P3: ratchets, interaction tests (F6), Windows scripts.

Selection is ``-m ratchet`` from the landing tree's ci.yml (else the static
list) for ``ratchets``; F6 selection (base = ``ctx.pre_head_commit``, head =
``ctx.landing_commit``) for ``tests``.  Direct runs stay within the focused
exemption (<= 25 files, nothing that spawns PowerShell, ``--basetemp`` under
``ctx.run_dir``); larger runs go through the worktree's
``scripts/ops/workstation_heavy.ps1 -RepoRoot <wt> -Queue`` (exit 75 -> NOT_RUN).
Stubs return ERROR (fail closed) until implemented; ``--tests none`` skips.
"""

from __future__ import annotations

from weather.operations.landing_preflight import (
    ERROR,
    PHASE_TESTS,
    PHASE_WORKTREE,
    SKIP,
    CheckRegistry,
    CheckResult,
    CheckSpec,
    PreflightContext,
)

OWNER = "L-P3"


def _ratchets(ctx: PreflightContext) -> CheckResult:
    return CheckResult(ERROR, f"stub: ratchets not implemented yet ({OWNER})")


def _tests(ctx: PreflightContext) -> CheckResult:
    if ctx.options.tests == "none":
        return CheckResult(SKIP, "--tests none")
    return CheckResult(ERROR, f"stub: tests not implemented yet ({OWNER})")


def _windows_scripts(ctx: PreflightContext) -> CheckResult:
    return CheckResult(ERROR, f"stub: windows_scripts not implemented yet ({OWNER})")


def register_checks(registry: CheckRegistry) -> None:
    registry.register(CheckSpec("ratchets", PHASE_WORKTREE, _ratchets, OWNER, ("import_probe",),
                                "-m ratchet files (or the static list) direct, <= 25 files, no PowerShell spawners"))
    registry.register(CheckSpec("tests", PHASE_TESTS, _tests, OWNER, ("import_probe",),
                                "F6 interaction selection; direct or workstation_heavy -Queue; head/interaction classes"))
    registry.register(CheckSpec("windows_scripts", PHASE_TESTS, _windows_scripts, OWNER, ("import_probe",),
                                "PowerShell-spawning ratchets via the wrapper when .ps1/workflows change"))
