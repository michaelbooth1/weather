# Owner-activated task wrapper. Agents never invoke this script on an account.
param([Parameter(Mandatory=$true)][string]$ReleasePath,
      [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ReleaseSha256,
      [Parameter(Mandatory=$true)]$TaskStartedUtc)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'lfc_campaign_task_contract.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
Assert-LfcCampaignImportEnvironment
$release=Read-LfcCampaignRelease -Path $ReleasePath -Sha256 $ReleaseSha256
$job=New-WeatherKillOnCloseJob
$child=$null; $exitCode=1
try {
    $began=[DateTimeOffset]::UtcNow
    $launch=Get-LfcCampaignLaunch -CampaignPath $release.campaign_path -NowUtc $began -TaskStartedUtc $TaskStartedUtc
    $deadline=[DateTimeOffset]::Parse($launch.deadline_utc)
    if($deadline -le $began) { throw 'campaign task containment budget expired' }
    $maxSeconds=($deadline-$began).TotalSeconds
    $elapsed=[Diagnostics.Stopwatch]::StartNew()
    $tokens=@('-m','weather.market.lfc_campaign_cli','tick','--release',$ReleasePath,'--release-sha256',$ReleaseSha256,
              '--wrapper-deadline-utc',$launch.deadline_utc,'--wrapper-policy-sha256',$launch.policy_bytes_sha256)
    $child=Start-WeatherProcessInJob -Job $job -FilePath $release.python -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $release.root
    while(-not $child.WaitForExit(500)) {
        if([DateTimeOffset]::UtcNow -ge $deadline -or $elapsed.Elapsed.TotalSeconds -ge $maxSeconds) { throw 'campaign child deadline; cancellation unproven' }
    }
    $exitCode=$child.ExitCode
} finally {
    # This is process containment, never a claim that orders were cancelled.
    # A crash leaves the account claim/HOLD incident for owner-led recovery.
    try { $job.TerminateAndWait(15000) } finally { $job.Dispose() }
    if($null -ne $child) { $child.Dispose() }
}
exit $exitCode
