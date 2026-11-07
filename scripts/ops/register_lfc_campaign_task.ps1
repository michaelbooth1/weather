# OWNER ONLY: register/verify/enable. Agents never call any action here.
param([Parameter(Mandatory=$true)][ValidateSet('Register','Verify','Enable')][string]$Action,
      [string]$RepoRoot='',
      [Parameter(Mandatory=$true)][string]$CampaignPath,
      [Parameter(Mandatory=$true)][string]$ReleasePath,
      [string]$PythonPath,[string]$PregateReceipt,[ValidatePattern('^[0-9a-f]{40}$')][string]$QualifiedHead)
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'lfc_campaign_task_contract.ps1')
. (Join-Path $PSScriptRoot 'workstation_pregate_receipt.ps1')
Assert-LfcCampaignImportEnvironment
if(-not [Environment]::UserInteractive) { throw 'owner interactive logon required' }
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if($Action -eq 'Register') {
    if(Get-ScheduledTask -TaskName 'WeatherLFCCampaign' -TaskPath '\' -ErrorAction SilentlyContinue) { throw 'task already exists; verify rather than overwrite' }
    if(Test-Path -LiteralPath $ReleasePath) { throw 'release already exists; never overwrite enrollment' }
    if(-not $PythonPath -or -not $PregateReceipt -or -not $QualifiedHead) { throw 'register requires interpreter, pregate and reviewed head' }
    $receipt=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($PregateReceipt))
    [void](Assert-WeatherPregateReceipt -Receipt $receipt -ExpectedHead $QualifiedHead -ProcessExitCode 0 -NotBefore ([DateTimeOffset]$receipt.started_at))
    if(-not (Test-Path -LiteralPath $CampaignPath)) {
        $parent=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($CampaignPath))
        [void][IO.Directory]::CreateDirectory($parent)
        # Create-only copy of an explicitly disabled policy, edited by owner next.
        [IO.File]::Copy((Join-Path $RepoRoot 'docs\examples\lfc-campaign.example.json'),$CampaignPath,$false)
    }
    Push-Location $RepoRoot
    try {
        & $PythonPath -m weather.market.lfc_campaign_cli seal --campaign $CampaignPath --release $ReleasePath --pregate $PregateReceipt --head $QualifiedHead --python $PythonPath
        if($LASTEXITCODE -ne 0) { throw 'release/enrollment failed; do not reset account state' }
    } finally { Pop-Location }
    $sha=(Get-FileHash -LiteralPath $ReleasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $release=Read-LfcCampaignRelease -Path $ReleasePath -Sha256 $sha
    $xml=New-LfcCampaignTaskXml -Release $release -ReleasePath $ReleasePath -ReleaseSha256 $sha -OwnerSid $sid
    [void](Register-ScheduledTask -TaskName $release.task_name -TaskPath '\' -Xml $xml -ErrorAction Stop)
} else {
    $sha=(Get-FileHash -LiteralPath $ReleasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $release=Read-LfcCampaignRelease -Path $ReleasePath -Sha256 $sha
    if([IO.Path]::GetFullPath($CampaignPath) -cne [IO.Path]::GetFullPath($release.campaign_path)) { throw 'campaign path changed' }
    $xml=New-LfcCampaignTaskXml -Release $release -ReleasePath $ReleasePath -ReleaseSha256 $sha -OwnerSid $sid
}
$actual=Export-ScheduledTask -TaskName $release.task_name -TaskPath '\'
$enabled=Assert-LfcCampaignTaskXml -Actual $actual -Expected $xml
if($Action -eq 'Register' -and $enabled) { throw 'new task unexpectedly enabled' }
if($Action -in @('Verify','Enable')) {
    # Validate editable policy and immutable installation again, without arming
    # or running a session. No new pregate for a supported policy-only edit.
    Push-Location $release.root
    try {
        $validationArgs=@('-m','weather.market.lfc_campaign_cli','check','--release',$ReleasePath,'--release-sha256',$sha)
        if($Action -eq 'Enable') { $validationArgs += '--require-enabled' }
        & $release.python @validationArgs
        if($LASTEXITCODE -ne 0) { throw 'campaign validation failed' }
    } finally { Pop-Location }
}
if($Action -eq 'Enable') {
    [void](Enable-ScheduledTask -TaskName $release.task_name -TaskPath '\')
    $enabled=Assert-LfcCampaignTaskXml -Actual (Export-ScheduledTask -TaskName $release.task_name -TaskPath '\') -Expected $xml
    if(-not $enabled) { throw 'enable readback failed' }
}
@{task=$release.task_name;definition_valid=$true;enabled=[bool]$enabled;release_sha256=$sha;owner_only=$true} | ConvertTo-Json -Compress
