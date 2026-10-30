# L13 recorder keepalive: the action of a 15-minute task (also safe to run by hand). Light: no fetches of its own.
# For each workstation forward recorder it checks liveness the way that recorder's own launcher does (the PID in
# <OutDir>\recorder.pid is alive and its CommandLine matches the recorder module), and when one is down it runs that
# recorder's EXISTING launcher from its pinned worktree, which keeps its own blob pin, STOP-file and alive checks and
# starts the recorder WMI-detached with --wait-lock-seconds 120. Before running a launcher the keepalive checks the
# launcher's sha256 against the pin below and refuses on a mismatch. A recorder with a STOP file in its OutDir is never
# restarted. HRRR is check-only: its own keepalive task ("L13 HRRR forward recorder keepalive (launcher)") restarts it,
# so this one logs its state but never starts it (no double start).
# One JSON line per recorder per run goes to <LogDir>\keepalive_<yyyyMM>.jsonl: the per-recorder gap list.
# -CheckOnly logs every state and what would be done, and starts nothing.
# <LogDir>\STOP stops the keepalive itself (one line logged, nothing checked). Research/shadow only: no capture-host,
# Scheduler, credential, exchange or order access; it starts only the launchers pinned here.
param(
    [string]$LogDir = 'C:\t\recorder_keepalive',
    [string]$RegistryPath = '',
    [int]$LauncherTimeoutSeconds = 90,
    [string]$PowerShellExe = (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'),
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'

# Pinned registry: the live worktree, launcher (relative to it), output directory, CommandLine match (as the
# launcher's own alive check) and launcher sha256 of each recorder, as running on 2026-10-30.
$DefaultRegistry = @(
    @{ name = 'ecmwf_ens'; worktree = 'C:\wt\l13ens'; launcher = 'tools\research\ecmwf_ens_forward_recorder_launch.ps1'
       outdir = 'C:\t\ecmwf_ens\forward'; match = 'ecmwf_ens_forward_recorder'; restart = $true
       sha256 = '3fdc70a42ea68e275a0ff9eaa8e26d7c6cf6b19352f4d3f246b0ae37bfeb70fa' },
    @{ name = 'eccc_gem'; worktree = 'C:\wt\l13gem'; launcher = 'tools\research\eccc_gem_forward_recorder_launch.ps1'
       outdir = 'C:\t\eccc_gem\forward'; match = 'eccc_gem_forward_recorder'; restart = $true
       sha256 = 'dd6f202e4e02400edc95ccbbe46a1cbdcc06a1ef03d6e3074cd520b76a81bfda' },
    @{ name = 'gefs_00_12_18z'; worktree = 'C:\wt\l13gc'; launcher = 'tools\research\gefs_cycles_forward_recorder_launch.ps1'
       outdir = 'C:\t\gefs_cycles\forward'; match = 'gefs_cycles_forward_recorder'; restart = $true
       sha256 = '868d2afceab195215d009f9c6d3a7885aefb032cf2889a9fe48756d1f236d706' },
    @{ name = 'gefs_06z'; worktree = 'C:\wt\l13g'; launcher = 'tools\research\gefs_forward_recorder_launch.ps1'
       outdir = 'C:\t\l6g\forward\gefs'; match = 'gefs_forward_recorder'; restart = $true
       sha256 = '730aaa6c7cd2111e61ee5bf27b03a02d89c99c8e2811978d31c88dc7f228938e' },
    @{ name = 'hrrr'; worktree = 'C:\wt\l13'; launcher = 'tools\research\hrrr_forward_recorder_launch.ps1'
       outdir = 'C:\t\l13\hrrr_forward'; match = 'hrrr_forward_recorder'; restart = $false
       sha256 = '3bd1bc07fd894e0db9d8af9b948ae8843da818e4604252e7614827d7c40d63b2' },
    @{ name = 'mosmix'; worktree = 'C:\wt\l13mx'; launcher = 'tools\research\mosmix_forward_recorder_launch.ps1'
       outdir = 'C:\t\mosmix\forward'; match = 'mosmix_forward_recorder'; restart = $true
       sha256 = 'f9191fc0e069c9a01f931dfa472bde6f2c3a87158aac1a20bdae5b75e44e797b' },
    @{ name = 'nbm_text'; worktree = 'C:\wt\l13nbm'; launcher = 'tools\research\nbm_text_forward_recorder_launch.ps1'
       outdir = 'C:\t\nbm_text\forward'; match = 'nbm_text_forward_recorder'; restart = $true
       sha256 = '7df8eb7ca11553dfa087aa700173872e6ce4d3ff1bed543b53f17132e7a8a9ae' },
    @{ name = 'l3_t1_price'; worktree = 'C:\wt\l3t1rec'; launcher = 'tools\research\t1_price_forward_recorder_launch.ps1'
       outdir = 'C:\t\t1_prices\forward'; match = 't1_price_forward_recorder'; restart = $true
       sha256 = '1170a7fefdfa15622e32816be67302855b3b2ce9f8bd0d5222b8e180b9053007' },
    @{ name = 'l8_om_prev_runs'; worktree = 'C:\wt\omprevrec'; launcher = 'tools\research\om_prev_runs_forward_recorder_launch.ps1'
       outdir = 'C:\t\om_prev_runs\forward'; match = 'om_prev_runs_forward_recorder'; restart = $true
       sha256 = 'c22d0893bdf40b6286e5b561b57917a3fc3ca242c82914ad45b61f7b2aef7add' },
    @{ name = 'iem_mos'; worktree = 'C:\wt\l13iem'; launcher = 'tools\research\iem_mos_forward_recorder_launch.ps1'
       outdir = 'C:\t\iem_mos\forward'; match = 'iem_mos_forward_recorder'; restart = $true
       sha256 = '47d11d5c73f0ba2f3b414c0289f4eb6504d48039a74986c6cc023e5c2a2767be' }
)

if ($RegistryPath) {
    # Windows PowerShell 5.1 emits a JSON array as ONE pipeline object, so enumerate it explicitly.
    $items = Get-Content -LiteralPath $RegistryPath -Raw | ConvertFrom-Json
    $Registry = @(foreach ($i in $items) {
        @{ name = $i.name; worktree = $i.worktree; launcher = $i.launcher; outdir = $i.outdir; match = $i.match
           restart = [bool]$i.restart; sha256 = $i.sha256 } })
} else {
    # Tests always pass a fixture registry; refuse to act on the real recorders under the test guard.
    if ($env:WEATHER_TASK_TEST -eq '1') { throw 'WEATHER_TASK_TEST=1 and no -RegistryPath: refusing the real registry' }
    $Registry = $DefaultRegistry
}

New-Item -ItemType Directory -Force $LogDir | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)
function Write-KeepaliveLine($fields) {
    $now = (Get-Date).ToUniversalTime()
    $line = [ordered]@{ at_utc = $now.ToString('yyyy-MM-ddTHH:mm:ssZ') }
    foreach ($k in $fields.Keys) { $line[$k] = $fields[$k] }
    $path = Join-Path $LogDir ('keepalive_{0}.jsonl' -f $now.ToString('yyyyMM'))
    [IO.File]::AppendAllText($path, (([pscustomobject]$line | ConvertTo-Json -Compress) + "`n"), $utf8)
}
function Get-Sha256([string]$path) {
    # Get-FileHash honours -WhatIf in some hosts; hash directly.
    $sha = [Security.Cryptography.SHA256]::Create()
    return (($sha.ComputeHash([IO.File]::ReadAllBytes($path)) | ForEach-Object { $_.ToString('x2') }) -join '')
}
function Get-AlivePid([hashtable]$r) {
    # Same test as the recorder launchers: the PID in recorder.pid is alive and its CommandLine has the module name.
    $pidFile = Join-Path $r.outdir 'recorder.pid'
    if (-not (Test-Path -LiteralPath $pidFile)) { return $null }
    $text = "$(Get-Content -LiteralPath $pidFile -TotalCount 1)".Trim()
    $n = 0
    if (-not [int]::TryParse($text, [ref]$n) -or $n -le 0) { return $null }
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$n" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like "*$($r.match)*") { return $n }
    return $null
}

$mutex = New-Object Threading.Mutex($false, 'Local\L13RecorderKeepalive')
$owned = $false
try { $owned = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) { Write-KeepaliveLine @{ recorder = '_keepalive'; state = 'busy'; action = 'none'; detail = 'another keepalive run holds the mutex' }; exit 0 }
try {
    if (Test-Path -LiteralPath (Join-Path $LogDir 'STOP')) {
        Write-KeepaliveLine @{ recorder = '_keepalive'; state = 'stopped'; action = 'none'; detail = "STOP file in $LogDir" }
        exit 0
    }
    foreach ($r in $Registry) {
        $out = [ordered]@{ recorder = $r.name; state = 'unknown'; pid = $null; action = 'none'; detail = '' }
        try {
            if (Test-Path -LiteralPath (Join-Path $r.outdir 'STOP')) {
                $out.state = 'stopped'; $out.detail = 'STOP file; never restarted'
            } elseif ($null -ne ($alive = Get-AlivePid $r)) {
                $out.state = 'alive'; $out.pid = $alive
            } else {
                $out.state = 'dead'
                $launcher = Join-Path $r.worktree $r.launcher
                if (-not $r.restart) {
                    $out.action = 'not_restarted'; $out.detail = 'check-only: restarted by its own keepalive task'
                } elseif (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
                    $out.action = 'refused'; $out.detail = "launcher missing: $launcher"
                } elseif (($got = Get-Sha256 $launcher) -ne $r.sha256) {
                    $out.action = 'refused'; $out.detail = "launcher sha256 $got != pinned $($r.sha256)"
                } elseif ($CheckOnly) {
                    $out.action = 'would_launch'; $out.detail = '-CheckOnly: nothing started'
                } else {
                    $args_ = @('-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-ExecutionPolicy', 'Bypass',
                               '-File', "`"$launcher`"")
                    $p = Start-Process -FilePath $PowerShellExe -ArgumentList $args_ -WorkingDirectory $r.outdir `
                        -WindowStyle Hidden -PassThru
                    if (-not $p.WaitForExit($LauncherTimeoutSeconds * 1000)) {
                        try { $p.Kill() } catch { }
                        $out.action = 'launcher_timeout'; $out.detail = "launcher still running after $LauncherTimeoutSeconds s; killed (the recorder is detached)"
                    } else {
                        $out.action = 'launched'; $out.detail = "launcher exit $($p.ExitCode)"
                    }
                    $after = Get-AlivePid $r
                    $out.pid = $after
                    $out.state_after = if ($null -ne $after) { 'alive' } else { 'dead' }
                }
            }
        } catch {
            $out.action = 'error'; $out.detail = "$($_.Exception.Message)"
        }
        Write-KeepaliveLine $out
    }
} finally {
    $mutex.ReleaseMutex()
}
