# Split recovery observes exact retained commit evidence. It never retries a
# commit or publication, upgrades historical proof, or releases downstream work.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')

function Read-WeatherQualificationCommitEvidence {
    param([Parameter(Mandatory = $true)]$AttemptContract,
          [Parameter(Mandatory = $true)][ValidateSet('MergeReceipt','QuietReport','ActiveMarker')][string]$Kind,
          [Parameter(Mandatory = $true)][string]$ExpectedSha256)
    $m=$AttemptContract.Manifest
    $path=switch($Kind) {
        'MergeReceipt' { [string]$m.evidence.merge_receipt }
        'QuietReport' { [string]$m.evidence.quiet_merge_report }
        'ActiveMarker' { Join-Path $m.repo_root 'data/alerts/quiet_window_merge_in_progress.json' }
    }
    $root=Split-Path -Parent $path
    $ref=Get-WeatherQualificationReference -Root $root -Name (Split-Path -Leaf $path)
    if($ExpectedSha256 -cnotmatch '^[0-9a-f]{64}$' -or [string]$ref.sha256 -cne $ExpectedSha256){throw 'Reviewed commit evidence changed'}
    $value=Read-WeatherQualificationReference -Root $root -Reference $ref
    if($Kind -ceq 'MergeReceipt') {
        if([string]$value.schema -cne 'weather_integration_attempt_merge_receipt_v2' -or
            [string]$value.status -cnotin @('COMMIT_UNVERIFIED','MERGED_UNVERIFIED') -or
            [string]$value.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
            [string]$value.attempt_id -cne [string]$m.attempt_id -or [string]$value.source_tip -cne [string]$m.expected_tip -or
            [string]$value.branch_ref -cne [string]$m.branch_ref -or
            -not (Test-WeatherIntegrationPathEqual -Left $value.quiet_merge_report.path -Right $m.evidence.quiet_merge_report)) {
            throw 'Receipt is not an exact ambiguous split commit'
        }
        $inner=Read-WeatherQualificationCommitEvidence -AttemptContract $AttemptContract -Kind QuietReport -ExpectedSha256 $value.quiet_merge_report.sha256
        return [pscustomobject]@{Path=$path;Reference=$ref;Payload=$value;PreparedBaseline=$inner.PreparedBaseline;ExecutionRequired=$inner.ExecutionRequired;Report=$inner}
    }
    $schema=if($Kind -ceq 'ActiveMarker'){'quiet_window_merge_in_progress_v0.1'}else{'quiet_window_merge_report_v0.2'}
    $binding=if($Kind -ceq 'ActiveMarker'){$value.qualification}else{$value.split_qualification}
    if([string]$value.schema -cne $schema -or [string]$value.operation_mode -cne 'split_qualification_v2' -or
        [string]$value.branch -cne [string]$m.branch_ref -or [string]$value.expected_tip -cne [string]$m.expected_tip -or
        [string]$value.resolved_branch_tip -cne [string]$m.expected_tip -or
        [string]$value.expected_baseline -cne [string]$m.baseline.master -or [string]$value.baseline_commit -cne [string]$m.baseline.master -or
        [string]$value.pre_merge_commit -cnotmatch '^[0-9a-f]{40}$' -or $value.execution_tape_recovery_required -isnot [bool] -or
        -not (Test-WeatherIntegrationPathEqual -Left $value.repo_root -Right $m.repo_root) -or
        [string]$binding.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left $binding.manifest_path -Right $AttemptContract.ManifestPath) -or
        $binding.commit_invocation_started -isnot [bool] -or -not $binding.commit_invocation_started) {
        throw 'Evidence does not bind this exact split commit invocation'
    }
    return [pscustomobject]@{Path=$path;Reference=$ref;Payload=$value;PreparedBaseline=[string]$value.pre_merge_commit;ExecutionRequired=$value.execution_tape_recovery_required;Report=$null}
}

function Assert-WeatherQualificationNoCommitClaim {
    param([Parameter(Mandatory = $true)]$AttemptContract)
    if((Get-WeatherIntegrationPrerequisite -AttemptContract $AttemptContract).Version -cne 'v2'){return}
    $m=$AttemptContract.Manifest
    foreach($kind in @('QuietReport','ActiveMarker')) {
        $path=if($kind -ceq 'QuietReport'){[string]$m.evidence.quiet_merge_report}else{Join-Path $m.repo_root 'data/alerts/quiet_window_merge_in_progress.json'}
        if(-not (Test-Path -LiteralPath $path)){continue}
        $ref=Get-WeatherQualificationReference -Root (Split-Path -Parent $path) -Name (Split-Path -Leaf $path)
        $value=Read-WeatherQualificationReference -Root (Split-Path -Parent $path) -Reference $ref
        if([string]$value.operation_mode -cne 'split_qualification_v2'){throw 'Foreign recovery evidence blocks split closure or retry'}
        $binding=if($kind -ceq 'QuietReport'){$value.split_qualification}else{$value.qualification}
        if([string]$binding.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
            $binding.commit_invocation_started -isnot [bool]){throw 'Unbound recovery evidence blocks split closure or retry'}
        if($binding.commit_invocation_started){throw 'Commit invocation may have happened; reconcile before any closure or retry'}
    }
}

function Assert-WeatherQualificationTerminalNative {
    param([Parameter(Mandatory = $true)]$State,[Parameter(Mandatory = $true)]$Native,[Parameter(Mandatory = $true)]$Current)
    $maximum=$State.Measurements.phases.metadata.maximum
    if([string]$Current.schema -cne 'qualification_terminal_current_v2' -or
        [string]$Current.manifest_sha256 -cne $State.Contract.ManifestSha256 -or
        [string]$Current.disposition -cnotin @('UNCOMMITTED_REQUIRES_REVIEW','MERGED_UNPUBLISHED_REQUIRES_REVIEW','PUBLISHED_CURRENT') -or
        $Current.native_parent_completion_required -isnot [bool] -or -not $Current.native_parent_completion_required -or
        $Current.historical_proof_upgraded -isnot [bool] -or $Current.historical_proof_upgraded -or
        $Current.downstream_authorized -isnot [bool] -or $Current.downstream_authorized -or
        $Native.completed -isnot [bool] -or -not $Native.completed -or $Native.teardown_proved -isnot [bool] -or -not $Native.teardown_proved -or
        $Native.exit_code -ne 0 -or $null -ne $Native.failure -or $Native.elapsed_ms -le 0 -or $Native.elapsed_ms -gt 1000*[int]$maximum.seconds -or
        $Native.peak_private_bytes -gt [UInt64]$maximum.commit_bytes -or $Native.native_peak_commit_bytes -gt [UInt64]$maximum.commit_bytes -or
        $Native.peak_working_set_bytes -gt [UInt64]$maximum.working_set_bytes -or $Native.maximum_sample_gap_ms -gt 1000 -or
        $Native.resource_samples -lt 1 -or $Native.system_commit_basis_points -gt 6600 -or
        $Native.minimum_disk_bytes -lt [UInt64]$State.Policy.host.minimum_disk_bytes) {throw 'Terminal native inspection is incomplete or exceeds reviewed limits'}
}

function Move-WeatherQualificationReconciledMarker {
    param([Parameter(Mandatory = $true)]$AttemptContract,[Parameter(Mandatory = $true)]$Receipt)
    if($null -eq $Receipt.marker){return}
    if([string]$Receipt.observation -cnotmatch '^reconciliations/[0-9a-f]{64}$'){throw 'Noncanonical marker retirement namespace'}
    $path=Join-Path $AttemptContract.Manifest.repo_root 'data/alerts/quiet_window_merge_in_progress.json'
    $destination=Join-Path $AttemptContract.AttemptRoot ([string]$Receipt.observation+'/'+'retired-marker.json')
    if(Test-Path -LiteralPath $destination) {
        if((Get-WeatherIntegrationFileSha256 -Path $destination) -cne [string]$Receipt.marker.sha256 -or (Test-Path -LiteralPath $path)) {
            throw 'Marker retirement conflicts with retained evidence'
        }
        return
    }
    $marker=Read-WeatherQualificationCommitEvidence -AttemptContract $AttemptContract -Kind ActiveMarker -ExpectedSha256 $Receipt.marker.sha256
    if([IO.Path]::GetPathRoot($path) -cne [IO.Path]::GetPathRoot($destination)){throw 'Marker retirement must be an atomic same-volume move'}
    [IO.File]::Move($marker.Path,$destination)
    if((Get-WeatherIntegrationFileSha256 -Path $destination) -cne [string]$Receipt.marker.sha256){throw 'Retired marker bytes differ'}
}

function Invoke-WeatherQualificationReconciliation {
    param([Parameter(Mandatory = $true)]$AttemptContract,[Parameter(Mandatory = $true)][string]$Kind,
          [Parameter(Mandatory = $true)][string]$ExpectedSha256,[Parameter(Mandatory = $true)][string]$ReviewReference,
          [string]$Notes,[switch]$ResumePublication)
    if($ResumePublication){throw 'Ambiguous split commits require separately reviewed recovery; reconciliation has no commit or publication authority'}
    . (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
    . (Join-Path $PSScriptRoot 'qualification_process.ps1')
    $state=Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    $m=$AttemptContract.Manifest; $root=$AttemptContract.AttemptRoot
    if(-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $m.control.root 'scripts/ops'))){throw 'Reconciliation requires the frozen B controller'}
    if((Get-WeatherExecutionHostId) -cne [string]$state.Plan.host_id -or (Get-WeatherExecutionPrincipalId) -cne [string]$state.Plan.principal_id){throw 'Reconciliation host/principal differs'}
    $assignment=Get-WeatherExecutionHostAssignment -RepoRoot $m.control.root
    if((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id){throw 'Capture-host reconciliation required'}
    $now=Get-Date
    if($now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30)){throw 'Reconciliation is outside heavy admission'}
    $maximum=$state.Measurements.phases.metadata.maximum; $seconds=[int]$maximum.seconds
    if($seconds -le 5 -or $seconds -gt 120 -or $seconds -gt [int]$state.Policy.host.metadata_seconds -or
        [UInt64]$maximum.commit_bytes -gt [UInt64]$state.Policy.host.audit_commit_bytes -or
        [UInt64]$maximum.working_set_bytes -gt [UInt64]$state.Policy.host.audit_working_set_bytes){throw 'Reconciliation exceeds metadata envelope'}
    $deadline=[DateTimeOffset]::UtcNow.AddSeconds($seconds)
    if($deadline -gt [DateTimeOffset]::new($now.Date.AddHours(9))){throw 'Reconciliation cannot finish in admission'}
    $terminal=Enter-WeatherIntegrationControlMutex -RepositoryRoot $m.repo_root -LockLeaf 'integration_attempt_terminal.lock' -Owner ('reconcile-split:'+$m.attempt_id)
    if($null -eq $terminal){throw 'Another terminal operation is active'}
    $lease=$null; $envelope=$null; $zero=$true
    try {
        $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot $m.repo_root -Workload ('SplitReconcile-'+$m.attempt_id)
        if($null -eq $lease){throw 'Shared heavy-workload lease is occupied'}
        if(Test-Path -LiteralPath $m.evidence.closure_receipt){throw 'Closed attempts cannot be reconciled'}
        foreach($role in @('host','merge')) {
            $binding=Assert-WeatherIntegrationAttemptTaskBinding -AttemptContract $AttemptContract -Role $role
            if([string]$binding.Task.State -cnotin @('Ready','Disabled')){throw 'Attempt task is not quiescent'}
        }
        $hash=[Security.Cryptography.SHA256]::Create()
        try{$reviewId=-join ($hash.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($ReviewReference)) | ForEach-Object {$_.ToString('x2')})}finally{$hash.Dispose()}
        $relative='reconciliations/'+$reviewId; $directory=Join-Path $root $relative
        if(Test-Path -LiteralPath $m.evidence.reconciliation_receipt) {
            $receipt=Read-WeatherQualificationReference -Root $root -Reference (Get-WeatherQualificationReference -Root $root -Name 'reconciliation-receipt.json')
            if([string]$receipt.schema -cne 'weather_integration_attempt_reconciliation_receipt_v2' -or [string]$receipt.status -cne 'MERGED_RECONCILED' -or
                [string]$receipt.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or [string]$receipt.observation -cne $relative -or
                [string]$receipt.evidence.sha256 -cne $ExpectedSha256 -or [string]$receipt.evidence_kind -cne $Kind -or
                $receipt.downstream_authorized -isnot [bool] -or $receipt.downstream_authorized -or
                $receipt.historical_proof_upgraded -isnot [bool] -or $receipt.historical_proof_upgraded){throw 'Existing reconciliation does not permit this marker cleanup'}
            $retainedCurrent=Read-WeatherQualificationReference -Root $root -Reference $receipt.current
            if($retainedCurrent.disposition -cne 'PUBLISHED_CURRENT' -or $retainedCurrent.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
                ($Kind -ceq 'ActiveMarker' -and [string]$receipt.marker.sha256 -cne $ExpectedSha256)){throw 'Original reconciliation proof differs'}
            Read-WeatherQualificationReference -Root $root -Reference $receipt.native | Out-Null
            Move-WeatherQualificationReconciledMarker -AttemptContract $AttemptContract -Receipt $receipt
            return $receipt
        }
        $evidence=Read-WeatherQualificationCommitEvidence -AttemptContract $AttemptContract -Kind $Kind -ExpectedSha256 $ExpectedSha256
        if(Test-Path -LiteralPath $directory){throw 'Reviewed reconciliation namespace is spent; retain it and review a new observation'}
        [void][IO.Directory]::CreateDirectory($directory)
        $marker=$null; $markerPath=Join-Path $m.repo_root 'data/alerts/quiet_window_merge_in_progress.json'
        if(Test-Path -LiteralPath $markerPath) {
            $marker=Read-WeatherQualificationCommitEvidence -AttemptContract $AttemptContract -Kind ActiveMarker -ExpectedSha256 (Get-WeatherIntegrationFileSha256 -Path $markerPath)
            if($marker.PreparedBaseline -cne $evidence.PreparedBaseline){throw 'Active marker and reviewed evidence disagree'}
            Write-WeatherQualificationImmutableRaw -Path (Join-Path $directory 'marker-snapshot.json') -Bytes ([IO.File]::ReadAllBytes($markerPath))
            if((Get-WeatherIntegrationFileSha256 -Path (Join-Path $directory 'marker-snapshot.json')) -cne $marker.Reference.sha256){throw 'Marker changed during retention'}
        }
        Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'request.json') -Payload ([ordered]@{
            manifest_path=$AttemptContract.ManifestPath;manifest_sha256=$AttemptContract.ManifestSha256;prepared_baseline=$evidence.PreparedBaseline;execution_required=$evidence.ExecutionRequired
            deadline=$deadline.AddSeconds(-4).ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",[Globalization.CultureInfo]::InvariantCulture)})
        $ref=Get-WeatherQualificationReference -Root $directory -Name 'request.json'
        $capture=@(Get-WeatherQualificationCaptureBindings -ProductionRoot $m.repo_root)
        Set-WeatherQualificationOfflineEnvironment -Profile $state.Profile -Scratch $directory
        $envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$maximum.commit_bytes,64);$zero=$false
        $python=Join-Path $state.Profile.tools.python.root $state.Profile.tools.python.path
        $tokens=@('-I','-S','-B',(Join-Path $PSScriptRoot 'qualification_terminal_control.py'),(Join-Path $directory 'request.json'),[string]$ref.sha256)
        $native=Invoke-WeatherQualificationProcess -Envelope $envelope -Executable $python -Tokens $tokens -WorkingDirectory $m.control.root `
            -Transcript (Join-Path $directory 'native.log') -DeadlineUtc $deadline -MaximumSeconds ($seconds-3) -TeardownSeconds 3 `
            -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) -MaximumOutputBytes 2097152 `
            -VolumePaths @([string]$m.repo_root,$directory) -MinimumDiskBytes ([UInt64]$state.Policy.host.minimum_disk_bytes) `
            -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) -ResourceMode capture_s4u -ProductionRoot $m.repo_root -CaptureBindings $capture
        Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
        $snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
        if(-not $zero){throw 'Reconciliation children did not drain'}
        $current=Read-WeatherQualificationReference -Root $directory -Reference (Get-WeatherQualificationReference -Root $directory -Name 'current.json')
        Assert-WeatherQualificationTerminalNative -State $state -Native $native -Current $current
        Read-WeatherQualificationReference -Root $directory -Reference $current.health | Out-Null
        if($current.execution_required -isnot [bool] -or $current.execution_required -ne $evidence.ExecutionRequired -or
            ($evidence.ExecutionRequired -and $current.execution_healthy -ne $true)){throw 'Current auxiliary producer proof is incomplete'}
        if([string]$current.disposition -cne 'PUBLISHED_CURRENT'){return $current}
        $tasks=@(Disable-WeatherIntegrationAttemptTasks -AttemptContract $AttemptContract)
        foreach($role in @('host','merge')) {
            $binding=Assert-WeatherIntegrationAttemptTaskBinding -AttemptContract $AttemptContract -Role $role
            if([string]$binding.Task.State -cne 'Disabled'){throw 'Attempt task did not become quiescent and disabled'}
        }
        Assert-WeatherQualificationCapture -ProductionRoot $m.repo_root -Bindings $capture
        Read-WeatherQualificationCommitEvidence -AttemptContract $AttemptContract -Kind $Kind -ExpectedSha256 $ExpectedSha256 | Out-Null
        if([DateTimeOffset]::UtcNow -gt $deadline){throw 'Reconciliation exceeded native deadline'}
        $receipt=[ordered]@{schema='weather_integration_attempt_reconciliation_receipt_v2';status='MERGED_RECONCILED'
            attempt_id=$m.attempt_id;manifest_sha256=$AttemptContract.ManifestSha256;observation=$relative;review_reference=$ReviewReference;notes=$Notes
            evidence_kind=$Kind;evidence=$evidence.Reference;marker=$(if($marker){$marker.Reference}else{$null});tasks=$tasks
            current=(Get-WeatherQualificationReference -Root $root -Name ($relative+'/current.json'))
            native=(Get-WeatherQualificationReference -Root $root -Name ($relative+'/native.json'))
            historical_proof_upgraded=$false;downstream_authorized=$false}
        Write-WeatherQualificationImmutableJson -Path $m.evidence.reconciliation_receipt -Payload $receipt
        Move-WeatherQualificationReconciledMarker -AttemptContract $AttemptContract -Receipt ([pscustomobject]$receipt)
        return $receipt
    }
    finally {
        if($envelope){
            try{$snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID}catch{$zero=$false}
            if(-not $zero -and $lease){Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease};$envelope.Dispose()
        }
        if($lease -and $zero){Exit-WeatherHeavyWorkloadLease -Lease $lease}
        Exit-WeatherIntegrationControlMutex -Mutex $terminal
    }
}
