# L3 T+1 price forward recorder launcher (the action of the logon task; also safe to run by hand).
# Starts the recorder detached through WMI Win32_Process.Create (not a child of the task or of any shell), with
# per-launch logs, --wait-lock-seconds 120 and a line in C:\t\t1_prices\forward\recorder_pid_log.txt, then exits
# within about a minute. Refuses (logs and exits 0) when: the STOP file exists, a recorder is already alive, or the
# code in the pinned worktree is not the pinned git blob id (claude/t1-price-recorder-20261030).
# Research/shadow only: public read-only International Polymarket reads (Gamma event by slug, CLOB /books), no
# credentials, no auth/order/signing/account endpoint, no capture-host, Scheduler or credential access.
param(
    [string]$Worktree = 'C:\wt\l3t1rec',
    [string]$OutDir = 'C:\t\t1_prices\forward',
    [string]$Horizons = '1,2',
    [string]$Python = 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
$pinned = @{
    'tools\research\t1_price_forward_recorder.py' = 'e73b75372b5bf3ca8de0ec5786e3b90fce8f9ab8'
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
    if ($proc -and $proc.CommandLine -like '*t1_price_forward_recorder*') { Write-PidLog "recorder pid $old alive; not started"; exit 0 }
}
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmss')
$script = Join-Path $Worktree 'tools\research\t1_price_forward_recorder.py'
$cmd = "cmd.exe /c `"`"$Python`" $script --out $OutDir --horizons $Horizons --wait-lock-seconds 120 1>>$OutDir\stdout_$stamp.log 2>>$OutDir\stderr_$stamp.log`""
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine = $cmd; CurrentDirectory = $OutDir}
$deadline = (Get-Date).AddSeconds(60); $newpid = $null
while ((Get-Date) -lt $deadline) {
    if (Test-Path $pidFile) {
        $p = [int](Get-Content $pidFile -TotalCount 1)
        $c = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
        if ($c -and $c.CommandLine -like '*t1_price_forward_recorder*' -and $c.CreationDate -gt (Get-Date).AddMinutes(-2)) { $newpid = $p; break }
    }
    Start-Sleep -Seconds 1
}
$parent = if ($newpid) { (Get-CimInstance Win32_Process -Filter "ProcessId=$newpid").ParentProcessId }
Write-PidLog ("started via WMI cmd {0} rc {1}; interpreter pid {2} parent {3}; logs stdout_{4}.log/stderr_{4}.log" -f $r.ProcessId, $r.ReturnValue, $newpid, $parent, $stamp)
