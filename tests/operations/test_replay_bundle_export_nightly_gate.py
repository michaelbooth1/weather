"""Executes the nightly replay export wrapper's gate, layout, admission and Job limits in Windows PowerShell.

Guards: owner decisions 2 and 3 (Swarm M 2026-10-06), A-defender B1/B2, B-defender D12 and P-v2 Defender NB1/NB2/M2 --
the wrapper refuses UTC days 2026-09-30..2026-10-15 with exit code 3 before any lease, launch or output; runs the v0.2
exporter from the deploy tree with the production interpreter behind a __file__ probe; admits each export only with
-MinAvailableMiB available; and enforces the 2 GiB ceiling and BelowNormal priority on every Job member, including the
interpreter the venv redirector starts. Never touches Scheduler.
"""
from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "scripts" / "ops"
WRAPPER = OPS / "replay_bundle_export_nightly.ps1"
JOB_HELPER = OPS / "replay_export_limited_job.ps1"
POWERSHELL = "powershell.exe"
GATED = [(date(2026, 9, 30) + timedelta(days=n)).isoformat() for n in range(16)]
PINS = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
MEMORY_LIMIT_EXIT = 0xE0E0E0E0
pytestmark = [pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell required"), pytest.mark.spawns]


def ps(source, timeout=120):
    encoded = base64.b64encode((source + "\nexit 0").encode("utf-16le")).decode("ascii")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def parse(path):
    return ("$ErrorActionPreference='Stop';$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$tokens,[ref]$errors);"
            "if(@($errors).Count){throw ($errors|Out-String)};")


def function(name):
    return (f"$fn=$ast.Find({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and "
            f"$n.Name -eq '{name}'}},$true); Invoke-Expression $fn.Extent.Text;")


def fake_trees(tmp_path):
    """A deploy copy of the wrapper plus a production tree whose helpers leave a marker if ever reached."""
    deploy, production = tmp_path / "deploy", tmp_path / "production"
    ops = deploy / "scripts" / "ops"
    ops.mkdir(parents=True)
    (ops / WRAPPER.name).write_bytes(WRAPPER.read_bytes())
    for root, name in ((production, "workload_admission.ps1"), (deploy, "windows_kill_on_close_job.ps1"),
                       (deploy, "replay_export_limited_job.ps1")):
        (root / "scripts" / "ops").mkdir(parents=True, exist_ok=True)
        marker = tmp_path / f"reached-{name}.txt"
        (root / "scripts" / "ops" / name).write_text(f"Set-Content -LiteralPath '{marker}' -Value reached\n",
                                                    encoding="ascii")
    (production / "venv" / "Scripts").mkdir(parents=True)
    (production / "venv" / "Scripts" / "python.exe").write_bytes(b"")
    return deploy, production


def snapshot(root):
    return sorted((p.relative_to(root).as_posix(), p.stat().st_size if p.is_file() else -1) for p in root.rglob("*"))


def run_wrapper(tmp_path, deploy, production, day):
    wrapper = deploy / "scripts" / "ops" / WRAPPER.name
    args = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(wrapper),
            "-DeployRoot", str(deploy), "-ProductionRoot", str(production), "-DataRoot", str(tmp_path / "data"),
            "-ReleaseRoot", str(tmp_path / "releases"), "-OutputRoot", str(tmp_path / "out"),
            "-ExpectedModuleSha256", "0" * 64, "-ExpectedSelfSha256", hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            "-MinAvailableMiB", "4096", "-Day", day]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


def test_wrapper_refuses_every_gated_day_with_exit_3_and_writes_nothing(tmp_path):
    deploy, production = fake_trees(tmp_path)
    before = snapshot(tmp_path)
    for day in GATED:
        result = run_wrapper(tmp_path, deploy, production, day)
        assert result.returncode == 3, (day, result.stdout, result.stderr)
        assert result.stderr.startswith(f"REFUSED: PANEL_GATED {day}")
        assert snapshot(tmp_path) == before  # no lease, marker, output folder, ledger or log


@pytest.mark.parametrize("day", ["2026-09-29", "2026-10-16"])
def test_boundary_days_pass_the_gate_and_meet_a_later_refusal(tmp_path, day):
    deploy, production = fake_trees(tmp_path)
    result = run_wrapper(tmp_path, deploy, production, day)
    # Outside 00:30-04:54 Toronto the window refuses; inside it, the missing data root or the open day does.
    assert result.returncode not in (0, 3), result.stdout + result.stderr
    assert "PANEL_GATED" not in result.stdout + result.stderr
    assert not (tmp_path / "out").exists() and not list(tmp_path.glob("reached-*"))


def test_script_level_order_gate_lease_pins_probe_admission_job_launch():
    source = parse(WRAPPER) + """
    $outside={param($n) $p=$n.Parent; while($p -and -not ($p -is [Management.Automation.Language.FunctionDefinitionAst])){$p=$p.Parent}; -not $p}
    $commands=$ast.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst]},$true) |
        Where-Object { & $outside $_ } | Sort-Object { $_.Extent.StartOffset }
    $exit=$ast.Find({param($n) $n -is [Management.Automation.Language.ExitStatementAst]},$true)
    Write-Output ('EXIT ' + $exit.Extent.StartOffset + ' ' + $exit.Pipeline.Extent.Text)
    foreach($c in $commands){ if($c.GetCommandName()){ Write-Output ($c.GetCommandName() + ' ' + $c.Extent.StartOffset) } }
    $members=$ast.FindAll({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst]},$true) |
        Where-Object { & $outside $_ }
    foreach($m in $members){ Write-Output ('.' + $m.Member.Extent.Text + ' ' + $m.Extent.StartOffset) }
    $env=$ast.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq '$env:PYTHONPATH'},$true) | Where-Object { & $outside $_ }
    foreach($e in $env){ Write-Output ('PYTHONPATH= ' + $e.Extent.StartOffset + ' ' + $e.Right.Extent.Text) }
    """
    lines = [line.split() for line in ps(source).splitlines() if line.strip()]
    exit_offset, exit_value = int(lines[0][1]), lines[0][2]
    offsets, pythonpath = {}, []
    for parts in lines[1:]:
        if parts[0] == "PYTHONPATH=":
            pythonpath.append((int(parts[1]), parts[2]))
        else:
            offsets.setdefault(parts[0], int(parts[1]))
    assert exit_value == "$PanelGateExitCode"
    assert offsets["Test-ReplayExportPanelGated"] < exit_offset < offsets["Get-ReplayExportDeadline"]
    assert exit_offset < offsets["Assert-ReplayExportPath"] < offsets["Enter-WeatherHeavyWorkloadLease"]
    order = ["Enter-WeatherHeavyWorkloadLease", "Set-ReplayExportChildThreadPins", "Invoke-ReplayExportImportProbe",
             ".AvailablePhysicalMiB", "Assert-ReplayExportAdmission", "New-ReplayExportLimitedJob", ".StartAssigned"]
    assert [offsets[name] for name in order] == sorted(offsets[name] for name in order)
    assert pythonpath == [(pythonpath[0][0], "$deploySrc")]
    assert offsets["Set-ReplayExportChildThreadPins"] < pythonpath[0][0] < offsets["Invoke-ReplayExportImportProbe"]
    # The retired shared Job and per-process polling are gone.
    for retired in ("New-WeatherKillOnCloseJob", "Start-WeatherProcessInJob"):
        assert retired not in offsets


def test_gate_function_uses_explicit_utc_boundaries():
    source = parse(WRAPPER) + function("Test-ReplayExportPanelGated") + """
    $style=[Globalization.DateTimeStyles]::AssumeUniversal -bor [Globalization.DateTimeStyles]::AdjustToUniversal
    foreach($d in @('2026-09-29','2026-09-30','2026-10-15','2026-10-16')){
        $u=[DateTime]::ParseExact($d,'yyyy-MM-dd',[Globalization.CultureInfo]::InvariantCulture,$style)
        if($u.Kind -ne 'Utc'){throw 'not UTC'}
        Write-Output ($d + ' ' + (Test-ReplayExportPanelGated -UtcDay $u))
    }
    """
    assert ps(source).split() == ["2026-09-29", "False", "2026-09-30", "True", "2026-10-15", "True",
                                  "2026-10-16", "False"]


def test_deploy_and_production_trees_must_be_disjoint():
    source = parse(WRAPPER) + function("Test-ReplayExportPathInside") + r"""
    foreach($pair in @(@('C:\d\deploy','C:\d\production'),@('C:\d\prod\deploy','C:\d\prod'),
                       @('C:\d\prod','C:\d\prod\'),@('C:\d\prodx','C:\d\prod'))){
        Write-Output ([string](Test-ReplayExportPathInside $pair[0] $pair[1]))
    }
    """
    assert ps(source).split() == ["False", "True", "True", "False"]
    text = WRAPPER.read_text(encoding="ascii")
    assert "'DeployRoot and ProductionRoot must be disjoint trees'" in text
    assert "Join-Path $ProductionRoot 'venv\\Scripts\\python.exe'" in text
    assert "Join-Path $ProductionRoot 'data\\logs\\memory_commit_guard_status.json'" in text
    assert "RepoRoot $RepoRoot" not in text and "$RepoRoot" not in text


@pytest.mark.parametrize("available, refused", [(4095, True), (4096, False), (12000, False)])
def test_admission_refuses_below_min_available_without_waiting(available, refused):
    source = parse(WRAPPER) + function("Assert-ReplayExportAdmission") + f"""
    $clock=[Diagnostics.Stopwatch]::StartNew()
    try {{ Assert-ReplayExportAdmission -MinimumMiB 4096 -AvailableMiB {available}; Write-Output 'ADMITTED' }}
    catch {{ Write-Output ('REFUSED ' + $_.Exception.Message) }}
    if($clock.Elapsed.TotalSeconds -gt 2){{throw 'admission waited'}}
    """
    out = ps(source).strip()
    assert out.startswith("REFUSED") == refused, out
    if refused:
        assert "below -MinAvailableMiB 4096; not waiting" in out


def _job_source(script, limit_mib, wait_seconds, priority="BelowNormal"):
    return f"""
    $ErrorActionPreference='Stop'
    . '{JOB_HELPER}'
    . '{OPS / "windows_kill_on_close_job.ps1"}'
    $job=New-ReplayExportLimitedJob -JobMemoryLimitBytes ({limit_mib}MB) -ProcessMemoryLimitBytes ({limit_mib}MB) -PriorityClass {priority}
    $root=$job.StartAssigned('{sys.executable}', (ConvertTo-WeatherWindowsArgumentString -Tokens @('-c', '{script}')), '{ROOT}')
    $seen=@{{}}; $priorities=@{{}}
    $clock=[Diagnostics.Stopwatch]::StartNew()
    while(-not $root.HasExited -and $clock.Elapsed.TotalSeconds -lt {wait_seconds}){{
        foreach($id in $job.ProcessIds()){{
            $seen[[string]$id]=$true
            $p=Get-Process -Id $id -ErrorAction SilentlyContinue
            # An empty PriorityClass means the member exited between the listing and the read: not a sample.
            if($p){{ try {{ $c=[string]$p.PriorityClass; if($c){{ $priorities[[string]$id]=$c }} }} catch {{ }} }}
        }}
        Start-Sleep -Milliseconds 50; $root.Refresh()
    }}
    $exited=$root.HasExited
    if($exited){{ $root.WaitForExit() }}
    Start-Sleep -Milliseconds 300  # let the completion port deliver the last NEW_PROCESS/limit messages
    $members=@($job.MemberProcessIds() | % {{ [string]$_ }})
    $result=[ordered]@{{ exited=$exited; exit_code=$(if($exited){{[int64]$root.ExitCode}}else{{$null}});
        root_pid=$root.Id; seen=@($seen.Keys); members=$members; priorities=$priorities; hit=$job.MemoryLimitHit;
        kind=$job.MemoryLimitKind; hit_pid=$job.MemoryLimitProcessId; peak=$job.PeakJobMemoryUsed;
        job_limit=$job.JobMemoryLimit; process_limit=$job.ProcessMemoryLimit; priority_class=$job.PriorityClass;
        seconds=$clock.Elapsed.TotalSeconds;
        stuck=@(if(-not $exited){{ foreach($id in $job.ProcessIds()){{ $p=Get-Process -Id $id -ErrorAction SilentlyContinue;
            if($p){{ "$id cpu_ms=$($p.TotalProcessorTime.TotalMilliseconds) waits=$(($p.Threads | % {{ [string]$_.WaitReason }}) -join '/')" }} }} }}) }}
    $job.TerminateAndWait(5000); $root.Dispose(); $job.Dispose()
    Write-Output ($result | ConvertTo-Json -Compress -Depth 4)
    """


def test_job_limit_kills_the_redirected_interpreter_that_overallocates():
    """A real venv python.exe (redirector) whose interpreter child allocates past 256 MiB: the Job kills the tree.

    Normal priority here: the kill is independent of priority, and a BelowNormal member can be starved for a long
    time on a loaded workstation (the next test covers BelowNormal with a long wait).
    """
    code = ("import time\nblocks=[]\ntry:\n    for _ in range(64): blocks.append(bytearray(16*1024*1024))\n"
            "except MemoryError:\n    pass\ntime.sleep(60)\n")
    result = json.loads(ps(_job_source(code.replace("'", "''"), 256, 240, "Normal"), timeout=360).strip().splitlines()[-1])
    assert result["hit"] is True and result["kind"] in ("JOB_MEMORY_LIMIT", "PROCESS_MEMORY_LIMIT"), result
    assert result["exited"] is True and (result["exit_code"] & 0xFFFFFFFF) == MEMORY_LIMIT_EXIT, result
    assert result["job_limit"] == result["process_limit"] == 256 * 1024**2
    assert result["peak"] <= 256 * 1024**2
    # Exact membership from JOB_OBJECT_MSG_NEW_PROCESS: a short-lived member can fall between polling samples.
    assert str(result["root_pid"]) in result["members"], result
    assert str(result["hit_pid"]) in result["members"], result
    if len(result["members"]) > 1:  # the venv redirector started the real interpreter: the grandchild is named
        assert result["hit_pid"] != result["root_pid"], result


def test_every_job_member_runs_below_normal():
    code = "import subprocess,sys,time\nsubprocess.run([sys.executable,'-c','import time; time.sleep(2)'])\n"
    # Generous: BelowNormal members wait behind any Normal-priority load on the workstation.
    result = json.loads(ps(_job_source(code.replace("'", "''"), 512, 300), timeout=420).strip().splitlines()[-1])
    assert result["exited"] is True and result["exit_code"] == 0 and result["hit"] is False, result
    assert result["priority_class"] == 0x4000
    assert len(result["priorities"]) >= 2, result  # redirector, interpreter and its child
    assert set(result["priorities"].values()) == {"BelowNormal"}, result


def test_import_probe_requires_every_module_inside_the_deploy_src(tmp_path):
    src = ROOT / "src"
    other = tmp_path / "other-src"
    other.mkdir()
    source = parse(WRAPPER) + function("Invoke-ReplayExportImportProbe") + f"""
    . '{JOB_HELPER}'
    . '{OPS / "windows_kill_on_close_job.ps1"}'
    $JobMemoryLimitBytes=2GB
    $modules=@('weather.market.maker_replay_night_v02','maker_core.replay.export_gate',
        'maker_core.replay.v2.writer','maker_core.replay.v2.threads')
    foreach($n in @({','.join(repr(p) for p in PINS)})){{ [Environment]::SetEnvironmentVariable($n,'1','Process') }}
    $env:PYTHONPATH='{src}'
    Invoke-ReplayExportImportProbe -Python '{sys.executable}' -Src '{src}' -WorkingDirectory '{ROOT}' -Modules $modules
    Write-Output 'INSIDE-OK'
    try {{ Invoke-ReplayExportImportProbe -Python '{sys.executable}' -Src '{other}' -WorkingDirectory '{ROOT}' -Modules $modules
          Write-Output 'OUTSIDE-ACCEPTED' }}
    catch {{ Write-Output ('OUTSIDE-REFUSED ' + $_.Exception.Message) }}
    """
    out = ps(source, timeout=300)
    assert "INSIDE-OK" in out and "OUTSIDE-REFUSED module-path probe failed: exit 3" in out, out


def test_thread_pins_reach_a_launched_child(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("import os\nprint(','.join(os.environ.get(n, '-') for n in %r))\n" % (PINS,), encoding="ascii")
    source = parse(WRAPPER) + f"""
    foreach($n in @({','.join(repr(p) for p in PINS)})){{ [Environment]::SetEnvironmentVariable($n,'7','Process') }}
    """ + function("Set-ReplayExportChildThreadPins") + f"""
    Set-ReplayExportChildThreadPins
    & '{sys.executable}' '{probe}'
    """
    assert ps(source).strip() == "1,1,1,1"


def test_wrapper_launches_the_v02_exporter_isolated():
    source = parse(WRAPPER) + """
    $assign=$ast.Find({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and
        $n.Left.Extent.Text -eq '$tokens'},$true)
    $Kind='night';$Day='2026-09-28';$DataRoot='D';$ReleaseRoot='R';$OutputRoot='O';$ExpectedModuleSha256='M';$budget=60
    $tokens = & ([scriptblock]::Create($assign.Right.Extent.Text))
    Write-Output ($tokens -join '|')
    """
    assert ps(source).strip() == ("-P|-B|-m|weather.market.maker_replay_night_v02|night|--day|2026-09-28|--data-root|D|"
                                  "--release-root|R|--out|O|--expected-module-sha256|M|--max-seconds|60")
