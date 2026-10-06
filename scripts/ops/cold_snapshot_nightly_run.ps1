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
# Owner decision 2026-10-05: 06:50-09:00, after the 04:45-06:45 tiering jobs, so the
# 01:00-04:00 quiet window stays free for roll-sensitive merges.
$windowStartMinute = 6 * 60 + 50
$windowEndMinute = 9 * 60
# The biggest night (2026-10-02, 21.3 GB) took 73 minutes; with the child's soft-stop
# and stop reserves a start needs 90 minutes before 09:00, so the latest start is 07:30.
# A refused start creates no attempt and consumes no local date.
$minimumRunMinutes = 90
$minute = $now.Hour * 60 + $now.Minute
if ($minute -lt $windowStartMinute -or $minute -ge $windowEndMinute) {
    throw 'Nightly compression refuses outside 06:50-09:00'
}
if ($windowEndMinute - $minute -lt $minimumRunMinutes) {
    throw 'Nightly compression refuses a start after 07:30: a run needs 90 minutes before 09:00'
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
            # Only a reviewed create-only resolution bound to this exact wrapper
            # receipt (weather.operations.cold_snapshot_nightly_resolution) clears it.
            $resolutionPath = Join-Path $parent ('resolved-nightly\' + $prior.Name + '.json')
            $resolved = $false
            if (Test-Path -LiteralPath $resolutionPath -PathType Leaf) {
                $resolutionInfo = Get-Item -LiteralPath $resolutionPath
                if ($resolutionInfo.Length -gt 2097152 -or ($resolutionInfo.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Unsafe resolution receipt' }
                $resolution = Get-Content -LiteralPath $resolutionPath -Raw | ConvertFrom-Json
                $wrapperHash = (Get-FileHash -LiteralPath $receiptPath -Algorithm SHA256).Hash.ToLowerInvariant()
                $resolved = ($resolution.record -ceq 'failed_attempt_resolution' -and $resolution.status -ceq 'RESOLVED' -and
                    $resolution.attempt -ceq $prior.Name -and $resolution.wrapper_result_sha256 -ceq $wrapperHash -and
                    $resolution.deleted_files -eq 0 -and $resolution.cleanup_eligible -eq $false)
            }
            if (-not $resolved) { throw "Prior nightly attempt requires review: $($prior.Name)" }
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
# Backstop only. The compression wrapper hard-stops at 09:00 - 15 s and then writes its
# receipt; killing it earlier would leave an attempt without a receipt, which no
# resolution can clear.
$deadline = [TimeZoneInfo]::ConvertTimeToUtc($now.Date.AddMinutes($windowEndMinute), $zone)
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
