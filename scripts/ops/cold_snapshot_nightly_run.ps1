# Repository-owned scheduled entrypoint. No source deletion or automatic recovery.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory=$true)][string]$RequestPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
$zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
$now = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
if ($now.Hour * 60 + $now.Minute -lt 30 -or $now.Hour * 60 + $now.Minute -ge 285) {
    throw 'Nightly compression refuses outside 00:30-04:45'
}
$parent = Join-Path $ProductionRepoRoot 'scratch\cold_snapshot_compression'
$dayPrefix = 'nightly-' + $now.ToString('yyyyMMdd') + '-'
# A prior interrupted/failed nightly attempt requires production review. Never
# silently skip an already-compressed file whose verification did not finish.
if (Test-Path -LiteralPath $parent) {
    foreach ($prior in @(Get-ChildItem -LiteralPath $parent -Directory -Filter 'nightly-*')) {
        if ($prior.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Redirected prior attempt' }
        $receiptPath = Join-Path $prior.FullName 'wrapper-result.json'
        if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) { throw "Unfinished nightly attempt: $($prior.Name)" }
        $info = Get-Item -LiteralPath $receiptPath
        if ($info.Length -gt 2097152 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe prior receipt' }
        $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        if ($receipt.status -cne 'PASS' -or $receipt.teardown_proved -ne $true -or $receipt.hard_stop -ne $false) {
            throw "Prior nightly attempt requires review: $($prior.Name)"
        }
        if ($prior.Name.StartsWith($dayPrefix)) { throw 'A nightly attempt already consumed this local date' }
    }
}
$output = Join-Path $parent ($dayPrefix + [DateTime]::UtcNow.ToString('HHmmssfffffffZ'))
$arguments = @('-NoProfile','-ExecutionPolicy','Bypass','-File',
    (Join-Path $PSScriptRoot 'cold_snapshot_compression_run.ps1'),
    '-ProductionRepoRoot',$ProductionRepoRoot,'-RequestPath',$RequestPath,
    '-RequestSha256',$RequestSha256,'-OutputRoot',$output,'-ExpectedSourceTip',$ExpectedSourceTip,
    '-Nightly','-MaxRuntimeSeconds','15300')
if ($Apply) { $arguments += '-Apply' }
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'training_window_contract.ps1')
$job = New-WeatherKillOnCloseJob
$child = $null
$exitCode = 1
$deadline = [TimeZoneInfo]::ConvertTimeToUtc($now.Date.AddMinutes(285), $zone).AddSeconds(-10)
try {
    $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $child = Start-WeatherProcessInJob -Job $job -FilePath $exe `
        -ArgumentString (ConvertTo-ScheduledTaskArgumentString -Tokens $arguments) `
        -WorkingDirectory (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    while (-not $child.HasExited -and [DateTime]::UtcNow -lt $deadline) {
        Start-Sleep -Milliseconds 500
        $child.Refresh()
    }
    if ($child.HasExited) { $child.WaitForExit(); $exitCode = $child.ExitCode }
}
finally {
    try { $job.TerminateAndWait(5000) }
    finally { if ($child) { $child.Dispose() }; $job.Dispose() }
}
exit $exitCode
