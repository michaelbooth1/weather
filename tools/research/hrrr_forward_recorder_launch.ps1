# L13 HRRR forward recorder launcher (the action of the logon task; also safe to run by hand).
# Starts the recorder exactly as C:\t\l13\probe\on_death.ps1 does: WMI Win32_Process.Create (so the
# recorder is not a child of the task or of any shell), per-launch logs, --wait-lock-seconds 120, and a
# line in C:\t\l13\recorder_pid_log.txt. It exits within about a minute; the recorder keeps running.
# Refuses (logs and exits 0) when: the STOP file exists, a recorder is already alive, or the recorder
# code in the pinned worktree is not the pinned git blob ids (claude/hrrr-forward-recorder-20261026 @
# 30598e9b7). Research/shadow only: no capture-host, Scheduler or credential access.
param(
    [string]$Worktree = 'C:\wt\l13',
    [string]$OutDir = 'C:\t\l13\hrrr_forward',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe',
    [string]$PidLog = 'C:\t\l13\recorder_pid_log.txt'
)
$ErrorActionPreference = 'Stop'
$pinned = @{
    'tools\research\hrrr_forward_recorder.py' = '2243152b5f18a43e65415bbd44fa9cbc97e23e4b'
    'tools\research\hrrr_point_fetch.py'      = '6ef2244a7146414a50e7691988ffc3e10c05b7f7'
}
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

New-Item -ItemType Directory -Force $OutDir | Out-Null
if (Test-Path (Join-Path $OutDir 'STOP')) { Write-PidLog 'STOP file present; not started'; exit 0 }
foreach ($rel in $pinned.Keys) {
    $got = Get-GitBlobLf (Join-Path $Worktree $rel)
    if ($got -ne $pinned[$rel]) { Write-PidLog "refused: $rel blob $got != pinned $($pinned[$rel])"; exit 0 }
}
$pidFile = Join-Path $OutDir 'recorder.pid'
if (Test-Path $pidFile) {
    $old = [int](Get-Content $pidFile -TotalCount 1)
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$old" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -like '*hrrr_forward_recorder*') { Write-PidLog "recorder pid $old alive; not started"; exit 0 }
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss')
$script = Join-Path $Worktree 'tools\research\hrrr_forward_recorder.py'
$cmd = "cmd.exe /c `"`"$Python`" $script --out $OutDir --wait-lock-seconds 120 1>>$OutDir\stdout_$stamp.log 2>>$OutDir\stderr_$stamp.log`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd; CurrentDirectory = $OutDir}
$deadline = (Get-Date).AddSeconds(60); $newpid = $null
while ((Get-Date) -lt $deadline) {
    if (Test-Path $pidFile) {
        $p = [int](Get-Content $pidFile -TotalCount 1)
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
        if ($c -and $c.CommandLine -like '*hrrr_forward_recorder*' -and $c.CreationDate -gt (Get-Date).AddMinutes(-2)) { $newpid = $p; break }
    }
    Start-Sleep -Seconds 1
}
$parent = if ($newpid) { (Get-CimInstance Win32_Process -Filter "ProcessId=$newpid").ParentProcessId }
Write-PidLog ("started via WMI cmd {0} rc {1}; interpreter pid {2} parent {3}; logs stdout_{4}.log/stderr_{4}.log" -f $r.ProcessId, $r.ReturnValue, $newpid, $parent, $stamp)
