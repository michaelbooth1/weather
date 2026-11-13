# OWNER ONLY: register/upgrade/verify/enable. Agents never call any action here.
param([Parameter(Mandatory=$true)][ValidateSet('Register','Upgrade','Verify','Enable')][string]$Action,
      [string]$RepoRoot='',
      [Parameter(Mandatory=$true)][string]$CampaignPath,
      [Parameter(Mandatory=$true)][string]$ReleasePath,
      [string]$PythonPath,[string]$PregateReceipt,[ValidatePattern('^[0-9a-f]{40}$')][string]$QualifiedHead,
      [string]$PreviousReleasePath='',
      # OWNER ONLY (B090, owner 11-13): -PregateReceipt is then an owner waiver
      # JSON for the same QualifiedHead instead of a full pregate receipt.
      [switch]$OwnerWaivedPregate)
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0
. (Join-Path $PSScriptRoot 'lfc_campaign_task_contract.ps1')
. (Join-Path $PSScriptRoot 'workstation_pregate_receipt.ps1')
Assert-LfcCampaignImportEnvironment
if(-not [Environment]::UserInteractive) { throw 'owner interactive logon required' }
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if($Action -in @('Register','Upgrade')) {
    $existing=Get-ScheduledTask -TaskName 'WeatherLFCCampaign' -TaskPath '\' -ErrorAction SilentlyContinue
    if($Action -eq 'Register' -and $existing) { throw 'task already exists; verify rather than overwrite' }
    if($Action -eq 'Upgrade') {
        if(-not $existing -or -not $PreviousReleasePath) { throw 'upgrade requires existing task and prior release' }
        if(-not (Test-Path -LiteralPath $CampaignPath)) { throw 'upgrade requires the retained campaign file' }
        if([IO.Path]::GetFullPath($PreviousReleasePath) -ceq [IO.Path]::GetFullPath($ReleasePath)) { throw 'upgrade preserves prior release' }
        $oldSha=(Get-FileHash -LiteralPath $PreviousReleasePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $previous=Read-LfcCampaignRelease -Path $PreviousReleasePath -Sha256 $oldSha
        [void](Assert-LfcCampaignUpgrade -Previous $previous -CampaignPath $CampaignPath -Enabled ([bool]$existing.Settings.Enabled) -State ([string]$existing.State))
        $oldLimit=if($previous.parameter_support.PSObject.Properties['f2_pinb']){'PT11H'}else{'PT9H'}
        $oldXml=New-LfcCampaignTaskXml -Release $previous -ReleasePath $PreviousReleasePath -ReleaseSha256 $oldSha -OwnerSid $sid -ExecutionTimeLimit $oldLimit
        [void](Assert-LfcCampaignTaskXml -Actual (Export-ScheduledTask -TaskName $previous.task_name -TaskPath '\') -Expected $oldXml)
    }
    if(Test-Path -LiteralPath $ReleasePath) { throw 'release already exists; never overwrite enrollment' }
    if(-not $PythonPath -or -not $PregateReceipt -or -not $QualifiedHead) { throw 'register requires interpreter, pregate and reviewed head' }
    $receipt=ConvertFrom-Json -InputObject ([IO.File]::ReadAllText($PregateReceipt))
    if($OwnerWaivedPregate) {
        $names=@($receipt.PSObject.Properties | ForEach-Object { $_.Name })
        foreach($field in @('schema','head','reason','focused_tests','at_utc')) { if($names -notcontains $field) { throw "owner pregate waiver missing $field" } }
        if([string]$receipt.schema -cne 'weather.owner_pregate_waiver.v1') { throw 'owner pregate waiver schema' }
        if([string]$receipt.head -cne $QualifiedHead) { throw 'owner pregate waiver head mismatch' }
        if(-not ([string]$receipt.reason).Trim()) { throw 'owner pregate waiver reason required' }
        if(-not ($receipt.focused_tests -is [int] -or $receipt.focused_tests -is [long]) -or $receipt.focused_tests -lt 1) { throw 'owner pregate waiver focused_tests' }
        [void][DateTimeOffset]::Parse([string]$receipt.at_utc, [Globalization.CultureInfo]::InvariantCulture)
        Write-Warning 'OWNER WAIVED THE FULL PREGATE for this head; the release records the waiver file hash as its pregate.'
    } else {
        [void](Assert-WeatherPregateReceipt -Receipt $receipt -ExpectedHead $QualifiedHead -ProcessExitCode 0 -NotBefore ([DateTimeOffset]$receipt.started_at))
    }
    if(-not (Test-Path -LiteralPath $CampaignPath)) {
        $parent=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($CampaignPath))
        [void][IO.Directory]::CreateDirectory($parent)
        # Create-only copy of an explicitly disabled policy, edited by owner next.
        [IO.File]::Copy((Join-Path $RepoRoot 'docs\examples\lfc-campaign.example.json'),$CampaignPath,$false)
    }
    Push-Location $RepoRoot
    try {
        $sealArgs=@('-m','weather.market.lfc_campaign_cli','seal','--campaign',$CampaignPath,'--release',$ReleasePath,'--pregate',$PregateReceipt,'--head',$QualifiedHead,'--python',$PythonPath)
        if($Action -eq 'Upgrade') { $sealArgs += @('--previous-release',$PreviousReleasePath) }
        & $PythonPath @sealArgs
        if($LASTEXITCODE -ne 0) { throw 'release/enrollment failed; do not reset account state' }
    } finally { Pop-Location }
    $sha=(Get-FileHash -LiteralPath $ReleasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $release=Read-LfcCampaignRelease -Path $ReleasePath -Sha256 $sha
    $xml=New-LfcCampaignTaskXml -Release $release -ReleasePath $ReleasePath -ReleaseSha256 $sha -OwnerSid $sid
    if($Action -eq 'Upgrade') {
        # Re-read immediately before replacing the action. An owner re-enable
        # or a running prior child must never be hard-stopped by this upgrade.
        $current=Get-ScheduledTask -TaskName $previous.task_name -TaskPath '\' -ErrorAction Stop
        [void](Assert-LfcCampaignUpgrade -Previous $previous -Successor $release -CampaignPath $CampaignPath -Enabled ([bool]$current.Settings.Enabled) -State ([string]$current.State))
        if((Get-FileHash -LiteralPath $PreviousReleasePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $oldSha) { throw 'prior release changed during upgrade' }
        [void](Assert-LfcCampaignTaskXml -Actual (Export-ScheduledTask -TaskName $previous.task_name -TaskPath '\') -Expected $oldXml)
        [void](Register-ScheduledTask -TaskName $release.task_name -TaskPath '\' -Xml $xml -Force -ErrorAction Stop)
    } else {
        [void](Register-ScheduledTask -TaskName $release.task_name -TaskPath '\' -Xml $xml -ErrorAction Stop)
    }
} else {
    $sha=(Get-FileHash -LiteralPath $ReleasePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $release=Read-LfcCampaignRelease -Path $ReleasePath -Sha256 $sha
    if([IO.Path]::GetFullPath($CampaignPath) -cne [IO.Path]::GetFullPath($release.campaign_path)) { throw 'campaign path changed' }
    $xml=New-LfcCampaignTaskXml -Release $release -ReleasePath $ReleasePath -ReleaseSha256 $sha -OwnerSid $sid
}
$actual=Export-ScheduledTask -TaskName $release.task_name -TaskPath '\'
$enabled=Assert-LfcCampaignTaskXml -Actual $actual -Expected $xml
if($Action -in @('Register','Upgrade') -and $enabled) { throw 'new task unexpectedly enabled' }
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
