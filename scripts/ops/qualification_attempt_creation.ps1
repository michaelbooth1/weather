# Explicit v2 creator. Prepared records remain inert until native verification,
# a durable manifest and any exact predecessor claim have all been published.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'qualification_preparation.ps1')

function New-WeatherQualificationAttempt {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot,
          [Parameter(Mandatory = $true)][string]$DraftPath,
          [Parameter(Mandatory = $true)][string]$ExpectedDraftSha256)
    if ((Split-Path -Leaf $DraftPath) -cne 'prepared-manifest.json') {throw 'Canonical prepared-manifest.json required'}
    $draft=Assert-WeatherQualificationAttemptManifest -ManifestPath $DraftPath -ExpectedSha256 $ExpectedDraftSha256 -BeforeSuccessorClaim
    $m=$draft.Manifest
    if (-not (Test-WeatherIntegrationPathEqual -Left $RepositoryRoot -Right ([string]$m.repo_root))) {throw 'Draft production repository differs'}
    $target=Join-Path $draft.AttemptRoot 'manifest.json'
    foreach($name in @('manifest.json','manifest.json.publish-claim','registration-intent.json','registration-receipt.json',
        'arming-receipt.json','host-claim.json','host-receipt.json','merge-invocation.json','merge-receipt.json',
        'closure-receipt.json','recovery-dispatch.json','reconciliation-receipt.json')) {
        if(Test-Path -LiteralPath (Join-Path $draft.AttemptRoot $name)){throw 'Prepared attempt contains spent execution evidence'}
    }
    $terminal=Enter-WeatherIntegrationControlMutex -RepositoryRoot $RepositoryRoot -LockLeaf 'integration_attempt_terminal.lock' -Owner ('create-split:'+$m.attempt_id)
    if($null -eq $terminal){throw 'Another integration terminal operation is active'}
    try {
        $prior=$null
        if($null -ne $m.authorization.repair_of) {
            $repair=$m.authorization.repair_of
            $closure=Read-WeatherIntegrationSharedJson -Path ([string]$repair.receipt_path)
            if((Get-WeatherIntegrationFileSha256 -Path ([string]$repair.receipt_path)) -cne [string]$repair.receipt_sha256){throw 'Predecessor closure changed'}
            $prior=Assert-WeatherIntegrationAttemptManifest -ManifestPath ([string]$closure.manifest_path) -ExpectedSha256 ([string]$closure.manifest_sha256)
            if([string]$closure.schema -cne (Get-WeatherIntegrationRecordSchema -AttemptContract $prior -Kind closure_receipt) -or
                [string]$closure.status -cne 'FAIL' -or [string]$closure.attempt_id -cne [string]$repair.prior_attempt_id -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$repair.claim_path) -Right (Join-Path $prior.AttemptRoot 'successor-claim.json'))) {
                throw 'Successor requires exact closed failed predecessor'
            }
            $dispatch=Read-WeatherIntegrationSharedJson -Path ([string]$repair.dispatch_path)
            if((Get-WeatherIntegrationFileSha256 -Path ([string]$repair.dispatch_path)) -cne [string]$repair.dispatch_sha256 -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$repair.dispatch_path) -Right ([string]$prior.Manifest.evidence.recovery_dispatch)) -or
                [string]$dispatch.schema -cne (Get-WeatherIntegrationRecordSchema -AttemptContract $prior -Kind recovery_dispatch) -or
                [string]$dispatch.status -cne 'READY_FOR_SUCCESSOR_REVIEW' -or [string]$dispatch.repair_class -cne [string]$m.authorization.repair_class -or
                [string]$dispatch.closure_receipt_sha256 -cne [string]$repair.receipt_sha256) {throw 'Predecessor dispatch does not authorize this repair'}
            if(Test-Path -LiteralPath ([string]$repair.claim_path)){throw 'Predecessor already has a successor'}
            Assert-WeatherQualificationRepairScope -AttemptContract $draft -PriorContract $prior
        }
        $state=Read-WeatherQualificationHostAttempt -ManifestPath $DraftPath -ExpectedManifestSha256 $ExpectedDraftSha256
        Invoke-WeatherQualificationPreparation -State $state
        Assert-WeatherQualificationPreparation -AttemptContract $draft | Out-Null
        # Preserve the exact reviewed draft bytes: native proof and the final
        # manifest therefore have one SHA, despite their different filenames.
        $raw=[IO.File]::ReadAllBytes($draft.ManifestPath)
        if((Get-WeatherIntegrationFileSha256 -Path $draft.ManifestPath) -cne $ExpectedDraftSha256){throw 'Reviewed draft changed before publication'}
        Write-WeatherQualificationImmutableRaw -Path $target -Bytes $raw
        $actual=Get-WeatherIntegrationFileSha256 -Path $target
        if($actual -cne $ExpectedDraftSha256){throw 'Published manifest differs from reviewed preparation'}
        if($null -ne $prior) {
            $claim=[ordered]@{schema=(Get-WeatherIntegrationRecordSchema -AttemptContract $prior -Kind successor_claim);status='CLAIMED'
                claimed_at_local=(Get-Date).ToString('o');predecessor_attempt_id=$prior.Manifest.attempt_id
                predecessor_receipt_path=$repair.receipt_path;predecessor_receipt_sha256=$repair.receipt_sha256
                recovery_dispatch_path=$repair.dispatch_path;recovery_dispatch_sha256=$repair.dispatch_sha256
                successor_attempt_id=$m.attempt_id;successor_manifest_path=$target;successor_manifest_sha256=$actual
                successor_expected_tip=$m.expected_tip;repair_class=$m.authorization.repair_class;review_reference=$m.authorization.review_reference}
            # Even a v1 predecessor gets the stronger writer for this new claim.
            Write-WeatherQualificationImmutableJson -Path ([string]$repair.claim_path) -Payload $claim
        }
        $final=Assert-WeatherQualificationAttemptManifest -ManifestPath $target -ExpectedSha256 $actual
        Assert-WeatherQualificationPreparation -AttemptContract $final | Out-Null
        return $final
    }
    finally {Exit-WeatherIntegrationControlMutex -Mutex $terminal}
}

function Assert-WeatherQualificationRepairScope {
    param([Parameter(Mandatory = $true)]$AttemptContract,[Parameter(Mandatory = $true)]$PriorContract)
    $m=$AttemptContract.Manifest; $prior=$PriorContract.Manifest; $class=[string]$m.authorization.repair_class
    $state=Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    $git=Join-Path $state.Profile.tools.git.root $state.Profile.tools.git.path
    if((Get-WeatherIntegrationFileSha256 -Path $git) -cne [string]$state.Profile.tools.git.sha256){throw 'Selected Git changed'}
    & $git --no-replace-objects -C $m.repo_root merge-base --is-ancestor $prior.expected_tip $m.expected_tip
    if($LASTEXITCODE -ne 0){throw 'Repair does not descend from failed source'}
    $rows=@(& $git --no-replace-objects -C $m.repo_root diff --no-ext-diff --no-textconv --name-status $prior.expected_tip $m.expected_tip)
    if($LASTEXITCODE -ne 0){throw 'Repair diff could not be read'}
    $rows=@($rows | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if($class -eq 'retry_unchanged') {
        if([string]$m.expected_tip -cne [string]$prior.expected_tip -or [string]$prior.authorization.repair_class -ceq 'retry_unchanged'){throw 'Unchanged retry scope or one-retry limit failed'}
    } elseif($rows.Count -eq 0){throw 'Repair contains no actual changed paths'}
    $allowed=@(Get-WeatherIntegrationRepairAllowedPatterns -RepairClass $class)
    foreach($row in $rows) {
        $parts=@(([string]$row) -split "`t")
        if($class -ne 'manual_reviewed_change' -and $parts[0] -cnotmatch '^[AM]$'){throw 'Bounded repair includes delete/rename'}
        foreach($path in @($parts | Select-Object -Skip 1)) {
            if(@($allowed | Where-Object {$path -match $_}).Count -eq 0){throw "Repair class excludes path: $path"}
        }
    }
}
