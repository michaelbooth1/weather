# L8 Open-Meteo Previous Runs forward recorder launcher (the action of the logon task; also safe to run by hand).
# Starts the recorder detached through WMI Win32_Process.Create, so it is not a child of the task or of any shell.
# It uses per-launch logs and --wait-lock-seconds 120, writes a line to recorder_pid_log.txt in the output
# directory, then exits within about a minute.
# Refuses (logs and exits 0) when the STOP file exists, a recorder is already alive, or the code in the pinned
# worktree is not the pinned git blob id (claude/om-prev-runs-recorder-20261030).
# Research/shadow only: one public read-only GET of previous-runs-api.open-meteo.com (free endpoint, no key), no
# credentials, no capture-host, Scheduler or credential access.
param(
    [string]$Worktree = 'C:\wt\omprevrec',
    [string]$OutDir = 'C:\t\om_prev_runs\forward',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$pinned = @{
    'tools\research\om_prev_runs_forward_recorder.py' = 'd54e228b5537221e7392f7603163e0222a73365c'
}
New-Item -ItemType Directory -Force $OutDir | Out-Null
$PidLog = Join-Path $OutDir 'recorder_pid_log.txt'
function Write-PidLog([string]$msg) {
    Add-Content -Path $PidLog -Value ("{0} launch: {1}" -f (Get-Date).ToUniversalTime().ToString('s'), $msg)
}
function Get-GitBlobLf([string]$path) {
    $raw = [IO.File]::ReadAllBytes($path)
    $text = [Text.Encoding]::GetEncoding(28591).GetString($raw).Replace("`r`n", "`n")
    $data = [Text.Encoding]::GetEncoding(28591).GetBytes($text)
    $head = [Text.Encoding]::ASCII.GetBytes("blob $($data.Length)`0")
    $sha1 = [Security.Cryptography.SHA1]::Create()
    return (($sha1.ComputeHash([byte[]]($head + $data)) | ForEach-Object { $_.ToString('x2') }) -join '')
}

if (Test-Path (Join-Path $OutDir 'STOP')) { Write-PidLog 'STOP file present; not started'; exit 0 }
foreach ($rel in $pinned.Keys) {
    $got = Get-GitBlobLf (Join-Path $Worktree $rel)
    if ($got -ne $pinned[$rel]) { Write-PidLog "refused: $rel blob $got != pinned $($pinned[$rel])"; exit 0 }
}
$pidFile = Join-Path $OutDir 'recorder.pid'
if (Test-Path $pidFile) {
    $old = [int](Get-Content $pidFile -TotalCount 1)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$old" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like '*om_prev_runs_forward_recorder*') { Write-PidLog "recorder pid $old alive; not started"; exit 0 }
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss')
$script = Join-Path $Worktree 'tools\research\om_prev_runs_forward_recorder.py'
$cmd = "cmd.exe /c `"`"$Python`" -I $script --out $OutDir --wait-lock-seconds 120 1>>$OutDir\stdout_$stamp.log 2>>$OutDir\stderr_$stamp.log`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd; CurrentDirectory = $OutDir}
$deadline = (Get-Date).AddSeconds(60); $newpid = $null
while ((Get-Date) -lt $deadline) {
    if (Test-Path $pidFile) {
        $p = [int](Get-Content $pidFile -TotalCount 1)
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
        if ($c -and $c.CommandLine -like '*om_prev_runs_forward_recorder*' -and $c.CreationDate -gt (Get-Date).AddMinutes(-2)) { $newpid = $p; break }
    }
    Start-Sleep -Seconds 1
}
$parent = if ($newpid) { (Get-CimInstance Win32_Process -Filter "ProcessId=$newpid").ParentProcessId }
Write-PidLog ("started via WMI cmd {0} rc {1}; interpreter pid {2} parent {3}; logs stdout_{4}.log/stderr_{4}.log" -f $r.ProcessId, $r.ReturnValue, $newpid, $parent, $stamp)
