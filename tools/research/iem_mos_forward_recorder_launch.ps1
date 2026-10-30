# L13 IEM MOS forward recorder launcher (the action of the logon task; also safe to run by hand).
# Starts the recorder detached through WMI Win32_Process.Create (not a child of the task or of any shell), with
# per-launch logs, --wait-lock-seconds 120 and a line in C:\t\iem_mos\forward\recorder_pid_log.txt, then exits
# within about a minute. Refuses (logs and exits 0) when: the STOP file exists, a recorder is already alive, or the
# code in the pinned worktree is not the pinned git blob id (claude/iem-mos-recorder-20261030).
# Research/shadow only: free public IEM MOS archive (mesonet.agron.iastate.edu, anonymous; 12 stations), no
# capture-host, Scheduler or credential access.
param(
    [string]$Worktree = 'C:\wt\l13iem',
    [string]$OutDir = 'C:\t\iem_mos\forward',
    [string]$Models = 'NBS,NBE,GFS,MEX,NAM,LAV',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$pinned = @{
    'tools\research\iem_mos_forward_recorder.py' = '66b008392e9b16a420d47bce5ec30adfa3c61eaa'
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
    if ($proc -and $proc.CommandLine -like '*iem_mos_forward_recorder*') { Write-PidLog "recorder pid $old alive; not started"; exit 0 }
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss')
$script = Join-Path $Worktree 'tools\research\iem_mos_forward_recorder.py'
$cmd = "cmd.exe /c `"`"$Python`" $script --out $OutDir --models $Models --wait-lock-seconds 120 1>>$OutDir\stdout_$stamp.log 2>>$OutDir\stderr_$stamp.log`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd; CurrentDirectory = $OutDir}
$deadline = (Get-Date).AddSeconds(60); $newpid = $null
while ((Get-Date) -lt $deadline) {
    if (Test-Path $pidFile) {
        $p = [int](Get-Content $pidFile -TotalCount 1)
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
        if ($c -and $c.CommandLine -like '*iem_mos_forward_recorder*' -and $c.CreationDate -gt (Get-Date).AddMinutes(-2)) { $newpid = $p; break }
    }
    Start-Sleep -Seconds 1
}
$parent = if ($newpid) { (Get-CimInstance Win32_Process -Filter "ProcessId=$newpid").ParentProcessId }
Write-PidLog ("started via WMI cmd {0} rc {1}; interpreter pid {2} parent {3}; logs stdout_{4}.log/stderr_{4}.log" -f $r.ProcessId, $r.ReturnValue, $newpid, $parent, $stamp)
