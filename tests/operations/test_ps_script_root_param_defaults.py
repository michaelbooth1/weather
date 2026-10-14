"""Repository-root defaults of advanced ops scripts under Windows PowerShell 5.1.

Guards: repository-root param defaults of advanced ops scripts under Windows PowerShell 5.1 -File (production incident 2026-10-04 03:36, quiet_window_merge.ps1).

In an *advanced* script (``[CmdletBinding()]`` or any ``[Parameter()]``
attribute), Windows PowerShell 5.1 leaves ``$PSScriptRoot`` and
``$PSCommandPath`` empty while it evaluates ``param()`` defaults under
``powershell.exe -File``. A default such as
``(Split-Path -Parent (Split-Path -Parent $PSScriptRoot))`` then fails binding or
binds an empty root (production, 2026-10-04 03:36, ``quiet_window_merge.ps1``).
The fix keeps the parameter optional with an empty default and derives the root
in the script body from ``$PSCommandPath``; an explicit argument always wins.

Two kinds of test live here:

* ``test_exec_*``: binding-only ``-File`` runs, from a different working
  directory, of the scripts that are scheduled or used for landing. Each run
  executes a *binding probe*: the script's own bytes up to the end of its
  ``param()`` block, plus its first body statement when that statement is the
  root derivation, followed by one line that prints the bound root and exits.
  The probe is placed at ``<fixture repo>/scripts/ops/<name>.ps1`` so the
  expected root is the fixture repository. Nothing past the root derivation
  runs: the probe is asserted to call no command other than ``Split-Path`` and
  ``Join-Path``, so it cannot reach the Scheduler, a lease, git, Python or any
  production path, and the real paths below are fingerprinted unchanged.
* ``test_no_advanced_script_derives_a_param_default_from_the_script_location``:
  an AST ratchet over every tracked ``.ps1``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS = REPO_ROOT / "scripts" / "ops"
WINDOWS_POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(
    os.name != "nt" or WINDOWS_POWERSHELL is None,
    reason="PS 5.1 -File root-binding tests require Windows PowerShell 5.1",
)

# Scheduled, landing-path and live execution-host scripts: name -> root parameter.
BINDING_TARGETS = {
    "daily_refresh.ps1": "RepoRoot",
    "suite_gated_quiet_merge.ps1": "RepoRoot",
    "merge_queue_driver.ps1": "RepoRoot",
    "new_integration_attempt.ps1": "RepoRoot",
    "register_boot_recovery.ps1": "RepoRoot",
    "register_clob_enrichment.ps1": "RepoRoot",
    "register_cold_snapshot_nightly.ps1": "ProductionRepoRoot",
    "register_daily_refresh.ps1": "RepoRoot",
    "register_health_watchdog.ps1": "RepoRoot",
    "register_integration_attempt.ps1": "RepoRoot",
    "register_maker_evidence_capture.ps1": "RepoRoot",
    "register_maker_shadow_runner.ps1": "RepoRoot",
    "register_nightly_retrain.ps1": "RepoRoot",
    "register_training_window.ps1": "RepoRoot",
    "register_wallet_reader_logon_task.ps1": "RepoRoot",
    # Portable live execution-host status; its default was GetFullPath(Join-Path $PSScriptRoot "..\..").
    "international_live_execution_host_status.ps1": "RepoRoot",
}

# A binding probe may call nothing but path arithmetic.
PROBE_ALLOWED_COMMANDS = {"split-path", "join-path"}

PRODUCTION_CHECKOUT = Path(r"C:\Users\micha\Desktop\github\weather")
REAL_GUARDED_PATHS = (
    REPO_ROOT / ".git",
    REPO_ROOT / "data" / "logs" / "heavy_workload.lock",
    REPO_ROOT / "data" / "alerts",
    REPO_ROOT / "data" / "integration_attempts",
    PRODUCTION_CHECKOUT / "data" / "logs" / "heavy_workload.lock",
    PRODUCTION_CHECKOUT / "data" / "alerts",
)

_PS_HELPERS = r"""
$ErrorActionPreference = 'Stop'
$L = 'System.Management.Automation.Language'
function Get-IsAdvanced($paramBlock) {
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
"""

_PROBE_BUILDER = _PS_HELPERS + r"""
$requests = Get-Content -LiteralPath $env:PROBE_REQUESTS -Raw | ConvertFrom-Json
$out = @()
foreach ($request in $requests) {
    $tokens = $null; $errors = $null
    $text = [IO.File]::ReadAllText($request.path)
    $ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "$($request.path): $($errors[0].Message)" }
    $block = $ast.ParamBlock
    $rootName = [string]$request.root
    $end = $block.Extent.EndOffset
    $first = @($ast.EndBlock.Statements | Where-Object { $_.Extent.StartOffset -ge $end }) | Select-Object -First 1
    $derivation = $false
    if ($first -is [System.Management.Automation.Language.IfStatementAst]) {
        $assigns = @($first.FindAll({ param($n)
            $n -is [System.Management.Automation.Language.AssignmentStatementAst] -and
            $n.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $n.Left.VariablePath.UserPath -eq $rootName }, $true))
        if ($assigns.Count) { $derivation = $true; $end = $first.Extent.EndOffset }
    }
    $probe = $text.Substring(0, $end) + "`r`n[Console]::Out.Write('BOUND_ROOT=' + `$$rootName)`r`nexit 0`r`n"
    $probeAst = [System.Management.Automation.Language.Parser]::ParseInput($probe, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw "probe for $($request.path): $($errors[0].Message)" }
    $commands = @($probeAst.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) |
        ForEach-Object { [string]$_.GetCommandName() })
    $parameters = @()
    foreach ($p in $block.Parameters) {
        $mandatorySets = @(); $optional = $true; $validateSet = @(); $pattern = $null; $range = $null
        foreach ($a in $p.Attributes) {
            if ($a -isnot [System.Management.Automation.Language.AttributeAst]) { continue }
            switch ($a.TypeName.Name) {
                'Parameter' {
                    $mandatory = $false; $set = '__AllParameterSets'
                    foreach ($n in $a.NamedArguments) {
                        if ($n.ArgumentName -eq 'Mandatory') {
                            $mandatory = ($n.ExpressionOmitted -or $n.Argument.Extent.Text -eq '$true')
                        }
                        if ($n.ArgumentName -eq 'ParameterSetName') { $set = [string]$n.Argument.Value }
                    }
                    if ($mandatory) { $mandatorySets += $set }
                }
                'ValidateSet' { $validateSet = @($a.PositionalArguments | ForEach-Object { [string]$_.Value }) }
                'ValidatePattern' { $pattern = [string]$a.PositionalArguments[0].Value }
                'ValidateRange' { $range = @($a.PositionalArguments | ForEach-Object { $_.Extent.Text }) }
            }
        }
        $parameters += [pscustomobject]@{
            name = $p.Name.VariablePath.UserPath
            type = [string]$p.StaticType.Name
            mandatory_sets = $mandatorySets
            validate_set = $validateSet
            pattern = $pattern
            range = $range
        }
    }
    $defaultSet = $null
    foreach ($a in $block.Attributes) {
        foreach ($n in $a.NamedArguments) {
            if ($n.ArgumentName -eq 'DefaultParameterSetName') { $defaultSet = [string]$n.Argument.Value }
        }
    }
    $out += [pscustomobject]@{
        path = $request.path
        advanced = (Get-IsAdvanced $block)
        derivation = $derivation
        probe = $probe
        commands = $commands
        parameters = $parameters
        default_set = $defaultSet
    }
}
[IO.File]::WriteAllText($env:PROBE_OUTPUT, (ConvertTo-Json -InputObject @($out) -Depth 6), [Text.UTF8Encoding]::new($false))
"""

_RATCHET_SCAN = _PS_HELPERS + r"""
$paths = Get-Content -LiteralPath $env:SCAN_LIST
$hits = @()
foreach ($path in $paths) {
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    if (-not $ast.ParamBlock -or -not (Get-IsAdvanced $ast.ParamBlock)) { continue }
    foreach ($p in $ast.ParamBlock.Parameters) {
        if (-not $p.DefaultValue) { continue }
        $refs = @($p.DefaultValue.FindAll({ param($n)
            $n -is [System.Management.Automation.Language.VariableExpressionAst] -and
            $n.VariablePath.UserPath -in @('PSScriptRoot', 'PSCommandPath') }, $true))
        if ($refs.Count) { $hits += "${path}:$($p.Extent.StartLineNumber) -$($p.Name.VariablePath.UserPath) = $($p.DefaultValue.Extent.Text)" }
    }
}
$hits
"""


def _run_powershell_source(source: str, tmp_path: Path, env_extra: dict[str, str]) -> str:
    assert WINDOWS_POWERSHELL is not None
    script = tmp_path / f"helper_{hashlib.sha256(source.encode()).hexdigest()[:12]}.ps1"
    script.write_text(source, encoding="utf-8-sig")
    result = subprocess.run(
        [WINDOWS_POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, **env_extra},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _sample_value(parameter: dict[str, Any]) -> str | None:
    """A value that satisfies the parameter's declared validation (binding only)."""
    kind = parameter["type"].lower()
    if kind == "switchparameter":
        return None
    if parameter["validate_set"]:
        return str(parameter["validate_set"][0])
    if parameter["range"]:
        return str(parameter["range"][0]).strip("'\"")
    if kind == "datetime":
        return "2026-10-05T01:00:00"
    if kind in {"int32", "int64", "double"}:
        return "1"
    pattern = parameter["pattern"]
    if pattern:
        for candidate in ("a" * 64, "a" * 40, "2026-10-05T01:00:00", "2026-10-05", "x"):
            if re.search(pattern, candidate, flags=re.IGNORECASE):
                return candidate
        raise AssertionError(f"no sample value matches {parameter['name']} pattern {pattern}")
    return "binding-probe"


def _mandatory_arguments(info: dict[str, Any], root_name: str) -> list[str]:
    chosen_set = info["default_set"]
    arguments: list[str] = []
    for parameter in info["parameters"]:
        if parameter["name"] == root_name:
            continue
        sets = set(parameter["mandatory_sets"] or [])
        if not sets or not ({"__AllParameterSets", chosen_set} & sets):
            continue
        arguments.append(f"-{parameter['name']}")
        value = _sample_value(parameter)
        if value is not None:
            arguments.append(value)
    return arguments


def _fingerprint(path: Path) -> Any:
    if not path.exists():
        return None
    if path.is_file():
        stat = path.stat()
        return ("file", stat.st_size, stat.st_mtime_ns)
    stat = path.stat()
    return ("dir", stat.st_mtime_ns, sorted(child.name for child in path.iterdir()))


def _real_state() -> dict[str, Any]:
    state: dict[str, Any] = {str(path): _fingerprint(path) for path in REAL_GUARDED_PATHS}
    for name in BINDING_TARGETS:
        state[name] = hashlib.sha256((OPS / name).read_bytes()).hexdigest()
    return state


@pytest.fixture(scope="module")
def probes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    work = tmp_path_factory.mktemp("probe_builder")
    requests = [{"path": str(OPS / name), "root": root} for name, root in BINDING_TARGETS.items()]
    request_file = work / "requests.json"
    request_file.write_text(json.dumps(requests), encoding="utf-8")
    output = work / "probes.json"
    _run_powershell_source(
        _PROBE_BUILDER, work, {"PROBE_REQUESTS": str(request_file), "PROBE_OUTPUT": str(output)}
    )
    built = json.loads(output.read_text(encoding="utf-8-sig"))
    return {Path(item["path"]).name: item for item in built}


def _run_probe(
    info: dict[str, Any], name: str, root_name: str, tmp_path: Path, explicit_root: Path | None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    assert WINDOWS_POWERSHELL is not None
    fixture_repo = tmp_path / "fixture repo"
    script = fixture_repo / "scripts" / "ops" / name
    script.parent.mkdir(parents=True)
    script.write_text(info["probe"], encoding="utf-8-sig")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    command = [
        WINDOWS_POWERSHELL,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        *_mandatory_arguments(info, root_name),
    ]
    if explicit_root is not None:
        command += [f"-{root_name}", str(explicit_root)]
    result = subprocess.run(
        command, cwd=elsewhere, capture_output=True, text=True, timeout=120, check=False
    )
    return result, fixture_repo


def _bound_root(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(r"BOUND_ROOT=(.*)$", result.stdout.strip())
    assert match, f"probe printed no bound root\nstdout:{result.stdout}\nstderr:{result.stderr}"
    return match.group(1).strip()


def _same_dir(actual: str, expected: Path) -> bool:
    return bool(actual) and os.path.normcase(os.path.abspath(actual)) == os.path.normcase(str(expected))


def _assert_probe_isolated(info: dict[str, Any]) -> None:
    assert info["advanced"], "binding target is no longer an advanced script; drop it from BINDING_TARGETS"
    called = {str(name).lower() for name in info["commands"]}
    assert called <= PROBE_ALLOWED_COMMANDS, f"binding probe would call {sorted(called)}"


@pytest.mark.parametrize(("name", "root_name"), sorted(BINDING_TARGETS.items()))
@pytest.mark.spawns
def test_exec_default_root_binds_the_scripts_own_checkout_under_file(
    probes: dict[str, dict[str, Any]], name: str, root_name: str, tmp_path: Path
) -> None:
    info = probes[name]
    _assert_probe_isolated(info)
    before = _real_state()
    result, fixture_repo = _run_probe(info, name, root_name, tmp_path, explicit_root=None)
    assert _real_state() == before
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr.strip() == ""
    bound = _bound_root(result)
    assert _same_dir(bound, fixture_repo), (
        f"-{root_name} bound {bound!r}, expected the script's checkout {fixture_repo}"
    )
    assert info["derivation"], "the root must be derived as the first body statement"


@pytest.mark.parametrize(("name", "root_name"), sorted(BINDING_TARGETS.items()))
@pytest.mark.spawns
def test_exec_explicit_root_takes_precedence_under_file(
    probes: dict[str, dict[str, Any]], name: str, root_name: str, tmp_path: Path
) -> None:
    info = probes[name]
    _assert_probe_isolated(info)
    explicit = tmp_path / "explicit root"
    explicit.mkdir()
    before = _real_state()
    result, _ = _run_probe(info, name, root_name, tmp_path, explicit_root=explicit)
    assert _real_state() == before
    assert result.returncode == 0, result.stdout + result.stderr
    bound = _bound_root(result)
    assert _same_dir(bound, explicit), f"-{root_name} bound {bound!r}, expected explicit {explicit}"


def _tracked_ps1() -> list[Path]:
    git = shutil.which("git")
    if git is None:
        return sorted(REPO_ROOT.glob("**/*.ps1"))
    listed = subprocess.run(
        [git, "-C", str(REPO_ROOT), "ls-files", "-z", "--", "*.ps1"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [REPO_ROOT / item for item in listed.split("\0") if item]


def _ratchet_hits(paths: list[Path], tmp_path: Path) -> list[str]:
    scan_list = tmp_path / "scan_list.txt"
    scan_list.write_text("\n".join(str(path) for path in paths), encoding="utf-8")
    output = _run_powershell_source(_RATCHET_SCAN, tmp_path, {"SCAN_LIST": str(scan_list)})
    return [line for line in output.splitlines() if line.strip()]


@pytest.mark.spawns
def test_ratchet_detector_flags_the_defect_and_spares_the_fix(tmp_path: Path) -> None:
    bad_cmdlet = tmp_path / "bad_cmdlet.ps1"
    bad_cmdlet.write_text(
        "[CmdletBinding()]\nparam([string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))\n",
        encoding="utf-8",
    )
    bad_attribute = tmp_path / "bad_attribute.ps1"
    bad_attribute.write_text(
        "param([Parameter(Mandatory = $true)][string]$X, [string]$Here = $PSCommandPath)\n", encoding="utf-8"
    )
    simple = tmp_path / "simple.ps1"
    simple.write_text("param([string]$RepoRoot = (Split-Path -Parent $PSScriptRoot))\n", encoding="utf-8")
    fixed = tmp_path / "fixed.ps1"
    fixed.write_text(
        "[CmdletBinding()]\nparam([string]$RepoRoot = \"\")\n"
        "if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $PSCommandPath }\n",
        encoding="utf-8",
    )
    hits = _ratchet_hits([bad_cmdlet, bad_attribute, simple, fixed], tmp_path)
    flagged = {name for name in ("bad_cmdlet.ps1", "bad_attribute.ps1", "simple.ps1", "fixed.ps1")
               if any(f"{name}:" in hit for hit in hits)}
    assert flagged == {"bad_cmdlet.ps1", "bad_attribute.ps1"}, hits
    assert len(hits) == 2, hits


@pytest.mark.spawns
def test_no_advanced_script_derives_a_param_default_from_the_script_location(tmp_path: Path) -> None:
    paths = _tracked_ps1()
    assert len(paths) > 50, "expected to scan the repository's PowerShell scripts"
    hits = _ratchet_hits(paths, tmp_path)
    assert hits == [], (
        "Windows PowerShell 5.1 leaves $PSScriptRoot/$PSCommandPath empty in an advanced "
        "script's param() defaults under -File. Use an empty default and derive the value "
        "in the body (an explicit argument must still win):\n" + "\n".join(hits)
    )
