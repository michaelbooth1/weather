"""Executes the nightly replay export wrapper's panel gate and thread pins in Windows PowerShell; never Scheduler.

Guards: owner decisions 2 and 3 (Swarm M 2026-10-06), A-defender B1/B2 and B-defender D12 -- the wrapper refuses
UTC days 2026-09-30..2026-10-15 with exit code 3 before any lease, launch or output, launches the v0.2 exporter, and
sets the four thread pins in the child's inherited environment just before launch.
"""
from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "ops" / "replay_bundle_export_nightly.ps1"
POWERSHELL = "powershell.exe"
GATED = [(date(2026, 9, 30) + timedelta(days=n)).isoformat() for n in range(16)]
PINS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell required"), pytest.mark.spawns]


def ps(source):
    encoded = base64.b64encode((source + "\nexit 0").encode("utf-16le")).decode("ascii")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def parse(path):
    return ("$ErrorActionPreference='Stop';$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors);"
            "if(@($errors).Count){throw ($errors|Out-String)};")


def fake_repo(tmp_path):
    """A copy of the wrapper whose admission and job helpers leave a marker if they are ever reached."""
    repo = tmp_path / "repo"
    ops = repo / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / WRAPPER.name).write_bytes(WRAPPER.read_bytes())
    for name in ("workload_admission.ps1", "windows_kill_on_close_job.ps1"):
        marker = tmp_path / f"reached-{name}.txt"
        (ops / name).write_text(f"Set-Content -LiteralPath '{marker}' -Value reached\n", encoding="ascii")
    (repo / "venv" / "Scripts").mkdir(parents=True)
    (repo / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    return repo


def snapshot(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))


def run_wrapper(tmp_path, repo, day):
    wrapper = repo / "scripts" / "ops" / WRAPPER.name
    args = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
            "-RepoRoot", str(repo), "-DataRoot", str(tmp_path / "data"), "-ReleaseRoot", str(tmp_path / "releases"),
            "-OutputRoot", str(tmp_path / "out"), "-ExpectedModuleSha256", "c" * 64,
            "-ExpectedSelfSha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(), "-Day", day]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def test_wrapper_refuses_every_gated_day_with_exit_3_and_writes_nothing(tmp_path):
    repo = fake_repo(tmp_path)
    before = snapshot(tmp_path)
    for day in GATED:
        result = run_wrapper(tmp_path, repo, day)
        assert result.returncode == 3, (day, result.stdout, result.stderr)
        assert f"PANEL_GATED {day}" in result.stderr
        assert snapshot(tmp_path) == before  # no lease, marker, output folder, ledger or log


@pytest.mark.parametrize("day", ["2026-09-29", "2026-10-16"])
def test_boundary_days_pass_the_gate_and_meet_a_later_refusal(tmp_path, day):
    repo = fake_repo(tmp_path)
    result = run_wrapper(tmp_path, repo, day)
    # Outside 00:30-04:54 Toronto the window refuses; inside it, the missing data root or the open day does.
    assert result.returncode not in (0, 3), result.stdout + result.stderr
    assert "PANEL_GATED" not in result.stdout + result.stderr
    assert not (tmp_path / "out").exists() and not list(tmp_path.glob("reached-*"))


def test_gate_precedes_lease_and_pins_precede_launch():
    source = parse(WRAPPER) + """
    $commands=$ast.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst]},$true) |
        Where-Object { $p=$_.Parent; while($p -and -not ($p -is [Management.Automation.Language.FunctionDefinitionAst])){$p=$p.Parent}; -not $p } |
        Sort-Object { $_.Extent.StartOffset }
    $exit=$ast.Find({param($n) $n -is [Management.Automation.Language.ExitStatementAst]},$true)
    Write-Output ('EXIT ' + $exit.Extent.StartOffset + ' ' + $exit.Pipeline.Extent.Text)
    foreach($c in $commands){ if($c.GetCommandName()){ Write-Output ($c.GetCommandName() + ' ' + $c.Extent.StartOffset) } }
    """
    lines = [line.split() for line in ps(source).splitlines() if line.strip()]
    exit_offset, exit_value = int(lines[0][1]), lines[0][2]
    offsets = {}
    for name, offset in lines[1:]:
        offsets.setdefault(name, int(offset))
    assert exit_value == "$PanelGateExitCode"
    assert offsets["Test-ReplayExportPanelGated"] < exit_offset < offsets["Get-ReplayExportDeadline"]
    assert exit_offset < offsets["Assert-ReplayExportPath"] < offsets["Enter-WeatherHeavyWorkloadLease"]
    assert (offsets["Enter-WeatherHeavyWorkloadLease"] < offsets["Set-ReplayExportChildThreadPins"]
            < offsets["New-WeatherKillOnCloseJob"] < offsets["Start-WeatherProcessInJob"])


def test_gate_function_uses_explicit_utc_boundaries():
    source = parse(WRAPPER) + """
    $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq 'Test-ReplayExportPanelGated'},$true)
    Invoke-Expression $fn.Extent.Text
    $style=[Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    foreach($d in @('2026-09-29','2026-09-30','2026-10-15','2026-10-16')){
        $u=[DateTime]::ParseExact($d,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,$style)
        if($u.Kind -ne 'Utc'){throw 'not UTC'}
        Write-Output ($d + ' ' + (Test-ReplayExportPanelGated -UtcDay $u))
    }
    """
    assert ps(source).split() == ["2026-09-29", "False", "2026-09-30", "True", "2026-10-15", "True",
                                  "2026-10-16", "False"]


def test_thread_pins_reach_a_launched_child(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import os\nprint(','.join(os.environ.get(n, '-') for n in %r))\n" % (PINS,), encoding="ascii")
    source = parse(WRAPPER) + f"""
    foreach($n in @({','.join(repr(p) for p in PINS)})){{ [Environment]::SetEnvironmentVariable($n,'7','Process') }}
    $fn=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and
        $n.Name -eq 'Set-ReplayExportChildThreadPins'}},$true)
    Invoke-Expression $fn.Extent.Text
    Set-ReplayExportChildThreadPins
    & '{sys.executable}' '{probe}'
    """
    assert ps(source).strip() == "1,1,1,1"


def test_wrapper_launches_the_v02_exporter():
    source = parse(WRAPPER) + """
    $assign=$ast.Find({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq '$tokens'},$true)
    $Kind='night';$Day='2026-09-28';$DataRoot='D';$ReleaseRoot='R';$OutputRoot='O';$ExpectedModuleSha256='M';$budget=60
    $tokens = & ([scriptblock]::Create($assign.Right.Extent.Text))
    Write-Output ($tokens -join '|')
    """
    assert ps(source).strip() == ("-B|-m|weather.market.maker_replay_night_v02|night|--day|2026-09-28|--data-root|D|"
                                  "--release-root|R|--out|O|--expected-module-sha256|M|--max-seconds|60")
