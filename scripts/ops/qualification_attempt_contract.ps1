# Typed split lifecycle metadata. Authentication/native gates remain separate.
Set-StrictMode -Version Latest

function Assert-WeatherQualificationFields {
    param([Parameter(Mandatory = $true)]$Value, [Parameter(Mandatory = $true)][string[]]$Names)
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    if (($actual -join '|') -cne (($Names | Sort-Object) -join '|')) { throw 'Unexpected or missing split record fields' }
}

function Get-WeatherQualificationOrchestrationNames {
    return [ordered]@{
        contract = 'integration_attempt_contract.ps1'; attempt_creator = 'new_integration_attempt.ps1'
        attempt_registrar = 'register_integration_attempt.ps1'; attempt_closer = 'close_integration_attempt.ps1'
        attempt_host = 'integration_attempt_host.ps1'; attempt_merge = 'integration_attempt_merge.ps1'
        attempt_success_gate = 'assert_integration_attempt_success.ps1'; attempt_recovery_dispatch = 'dispatch_integration_attempt_recovery.ps1'
        attempt_reconciler = 'reconcile_integration_attempt.ps1'; boot_recovery = 'boot_recovery.ps1'
        register_boot_recovery = 'register_boot_recovery.ps1'; quiet_merge = 'quiet_window_merge.ps1'
        token_contract = 'training_window_contract.ps1'; job_containment = 'windows_kill_on_close_job.ps1'
        workload_admission = 'workload_admission.ps1'; roll_verdict = 'roll_verdict.ps1'
        qualification_attempt = 'qualification_attempt_contract.ps1'; qualification_host = 'qualification_host_contract.ps1'
        qualification_identity = 'qualification_host_identity.ps1'; qualification_process = 'qualification_process.ps1'
        qualification_merge = 'qualification_merge_contract.ps1'; attempt_armer = 'arm_integration_attempt.ps1'
        qualification_arming = 'qualification_arming_contract.ps1'; qualification_publication = 'qualification_durable_json.ps1'
        qualification_preparation = 'qualification_preparation.ps1'; qualification_creation = 'qualification_attempt_creation.ps1'
        qualification_reconciliation = 'qualification_reconcile_contract.ps1'; attempt_planner = 'prepare_split_qualification.ps1'
    }
}

function Assert-WeatherQualificationOrchestration {
    param([Parameter(Mandatory = $true)]$AttemptContract)
    $m = $AttemptContract.Manifest
    $names = Get-WeatherQualificationOrchestrationNames
    Assert-WeatherQualificationFields -Value $m.orchestration -Names @($names.Keys)
    $closure = Read-WeatherQualificationReference -Root $AttemptContract.AttemptRoot -Reference $m.control.closure
    if ([string]$closure.schema -cne 'qualification_control_closure_v2' -or [string]$closure.baseline -cne [string]$m.baseline.master) {
        throw 'Split orchestration is not from the adopted baseline'
    }
    foreach ($key in $names.Keys) {
        $item = $m.orchestration.PSObject.Properties[$key].Value
        Assert-WeatherQualificationFields -Value $item -Names @('path', 'sha256')
        $relative = 'scripts/ops/' + [string]$names[$key]
        $expected = Join-Path ([string]$m.control.root) $relative
        $pinned = @($closure.files | Where-Object { [string]$_.path -ceq $relative })
        if ($pinned.Count -ne 1 -or -not (Test-WeatherIntegrationPathEqual -Left ([string]$item.path) -Right $expected) -or
            [string]$item.sha256 -cne [string]$pinned[0].sha256 -or
            (Get-WeatherIntegrationFileSha256 -Path $expected) -cne [string]$item.sha256) { throw ('Split orchestration drift: ' + $key) }
    }
}

function Assert-WeatherQualificationAttemptManifest {
    param([Parameter(Mandatory = $true)][string]$ManifestPath, [Parameter(Mandatory = $true)][string]$ExpectedSha256,
          [switch]$BeforeSuccessorClaim)
    . (Join-Path $PSScriptRoot 'workload_admission.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
    $state = Read-WeatherQualificationHostAttempt -ManifestPath $ManifestPath -ExpectedManifestSha256 $ExpectedSha256
    $contract = $state.Contract; $m = $contract.Manifest
    Assert-WeatherQualificationFields -Value $m -Names @('schema', 'qualification_mode', 'attempt_id', 'created_at_local',
        'attempt_root', 'repo_root', 'worktree_root', 'branch_ref', 'expected_tip', 'baseline', 'authorization', 'schedule',
        'orchestration', 'evidence', 'qualification', 'control', 'host')
    Assert-WeatherQualificationFields -Value $m.baseline -Names @('master', 'origin_master')
    Assert-WeatherQualificationFields -Value $m.authorization -Names @('review_reference', 'repair_class', 'repair_of')
    Assert-WeatherQualificationFields -Value $m.schedule -Names @('host_at_local', 'merge_at_local', 'host_task_name', 'merge_task_name')
    Assert-WeatherQualificationFields -Value $m.control -Names @('root', 'closure', 'git_policy')
    Assert-WeatherQualificationFields -Value $m.qualification -Names @('root', 'policy', 'review', 'certificate', 'import', 'revocations')
    if ([string]$m.expected_tip -cnotmatch '^[0-9a-f]{40}$' -or [string]$m.baseline.master -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$m.baseline.master -cne [string]$m.baseline.origin_master -or [string]$m.expected_tip -ceq [string]$m.baseline.master -or
        [string]$m.branch_ref -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$' -or [string]$m.branch_ref -match '\.\.' -or
        [string]$m.branch_ref -match '/$' -or [string]::IsNullOrWhiteSpace([string]$m.authorization.review_reference)) {
        throw 'Split source/baseline/review binding is invalid'
    }
    $hostAt = ConvertFrom-WeatherIntegrationLocalTimestamp -Value ([string]$m.schedule.host_at_local) -Label 'host_at_local'
    $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp -Value ([string]$m.schedule.merge_at_local) -Label 'merge_at_local'
    $hostMinute = 60 * $hostAt.Hour + $hostAt.Minute; $mergeMinute = 60 * $mergeAt.Hour + $mergeAt.Minute
    if ($hostAt.Date -ne $mergeAt.Date -or $hostMinute -lt 30 -or $hostMinute -ge 540 -or
        $mergeMinute -lt 60 -or $mergeMinute -ge 220 -or ($mergeAt - $hostAt).TotalMinutes -lt 34 -or
        [string]$m.schedule.host_task_name -cne ('WeatherIntegrationHost_' + [string]$m.attempt_id) -or
        [string]$m.schedule.merge_task_name -cne ('WeatherIntegrationMerge_' + [string]$m.attempt_id) -or
        [string]$state.Plan.local_day -cne $hostAt.ToString('yyyy-MM-dd')) { throw 'Split schedule binding refused' }
    ConvertFrom-WeatherIntegrationLocalTimestamp -Value ([string]$m.created_at_local) -Label 'created_at_local' | Out-Null
    if (Test-WeatherIntegrationPathEqual -Left ([string]$m.repo_root) -Right ([string]$m.worktree_root)) { throw 'Split candidate is not isolated' }
    $evidence = [ordered]@{ host_receipt='host-receipt.json'; host_log='host.log'; merge_receipt='merge-receipt.json'
        quiet_merge_report='quiet-merge-report.json'; registration_intent='registration-intent.json'; registration_receipt='registration-receipt.json'
        closure_receipt='closure-receipt.json'; recovery_dispatch='recovery-dispatch.json'; reconciliation_receipt='reconciliation-receipt.json' }
    Assert-WeatherQualificationFields -Value $m.evidence -Names @($evidence.Keys)
    foreach ($key in $evidence.Keys) {
        Assert-WeatherIntegrationEvidencePath -AttemptRoot $contract.AttemptRoot -ActualPath ([string]$m.evidence.PSObject.Properties[$key].Value) -ExpectedName $evidence[$key] | Out-Null
    }
    foreach ($key in @('policy', 'review', 'certificate', 'import', 'revocations')) {
        Read-WeatherQualificationReference -Root ([string]$m.qualification.root) -Reference $m.qualification.PSObject.Properties[$key].Value | Out-Null
    }
    Read-WeatherQualificationReference -Root $contract.AttemptRoot -Reference $m.control.git_policy | Out-Null
    Assert-WeatherQualificationOrchestration -AttemptContract $contract
    if (-not $BeforeSuccessorClaim) { Assert-WeatherIntegrationRepairClaim -AttemptContract $contract }
    return $contract
}

function Assert-WeatherQualificationHostReceipt {
    param([Parameter(Mandatory = $true)]$AttemptContract, [switch]$RequireFresh)
    . (Join-Path $PSScriptRoot 'workload_admission.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
    $m = $AttemptContract.Manifest; $root = $AttemptContract.AttemptRoot
    $ref = Get-WeatherQualificationReference -Root $root -Name 'host-receipt.json'
    $receipt = Read-WeatherQualificationReference -Root $root -Reference $ref
    Assert-WeatherQualificationFields -Value $receipt -Names @('schema', 'status', 'attempt_id', 'manifest_sha256', 'host_plan_sha256',
        'registration_receipt_sha256', 'registration_intent_sha256', 'started_at', 'completed_at', 'local_day', 'invocation',
        'phases', 'probes', 'audit', 'configuration_sha256', 'environment_sha256', 'code_sha256', 'capture_before', 'capture_after',
        'teardown_proved', 'failure', 'integration_eligible')
    if ([string]$receipt.schema -cne 'weather_integration_attempt_host_receipt_v2' -or [string]$receipt.status -cne 'PASS' -or
        [string]$receipt.attempt_id -cne [string]$m.attempt_id -or [string]$receipt.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
        $receipt.teardown_proved -isnot [bool] -or -not $receipt.teardown_proved -or $null -ne $receipt.failure -or
        $receipt.integration_eligible -isnot [bool] -or $receipt.integration_eligible) { throw 'Host receipt does not prove this exact split attempt' }
    $state = Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    if ([string]$receipt.host_plan_sha256 -cne [string]$m.host.sha256 -or [string]$receipt.configuration_sha256 -cne [string]$state.Plan.configuration.sha256 -or
        [string]$receipt.environment_sha256 -cne [string]$state.Plan.environment.sha256 -or [string]$receipt.code_sha256 -cne [string]$m.qualification.certificate.sha256 -or
        [string]$receipt.local_day -cne [string]$state.Plan.local_day -or
        [string]$receipt.registration_receipt_sha256 -cne (Get-WeatherIntegrationFileSha256 -Path ([string]$m.evidence.registration_receipt)) -or
        [string]$receipt.registration_intent_sha256 -cne (Get-WeatherIntegrationFileSha256 -Path ([string]$m.evidence.registration_intent))) {
        throw 'Host receipt dependency binding differs'
    }
    $start = ConvertFrom-WeatherIntegrationEvidenceTimestamp -Value ([string]$receipt.started_at) -Label 'host started_at'
    $end = ConvertFrom-WeatherIntegrationEvidenceTimestamp -Value ([string]$receipt.completed_at) -Label 'host completed_at'
    if ($start -gt $end -or $start -lt [DateTimeOffset]::Parse([string]$state.Plan.not_before) -or $end -gt [DateTimeOffset]::Parse([string]$state.Plan.deadline)) {
        throw 'Host phase interval differs from the plan'
    }
    if ($RequireFresh -and (([DateTimeOffset]::UtcNow - $end).TotalSeconds -lt 0 -or
        ([DateTimeOffset]::UtcNow - $end).TotalSeconds -gt [int]$state.Policy.validity.host_seconds -or
        (Get-Date).ToString('yyyy-MM-dd') -cne [string]$receipt.local_day)) { throw 'Host receipt is stale or belongs to another local day' }
    Assert-WeatherQualificationFields -Value $receipt.phases -Names @('probes', 'audit', 'metadata', 'teardown')
    Assert-WeatherQualificationFields -Value $receipt.probes -Names @('isolated_imports', 'configuration_overlay', 'offline_environment', 'duplicate_path',
        'captured_streams', 'stdin_eof', 'timeout_cleanup', 'inherited_handles', 'create_once_flush_rename')
    foreach ($row in $receipt.phases.PSObject.Properties) {
        $proof = Read-WeatherQualificationReference -Root $root -Reference $row.Value
        if ($proof.completed -ne $true -or $proof.teardown_proved -ne $true -or $proof.exit_code -ne 0 -or $null -ne $proof.failure) { throw 'Host native phase failed' }
    }
    foreach ($row in $receipt.probes.PSObject.Properties) {
        $proof = Read-WeatherQualificationReference -Root $root -Reference $row.Value
        if ([string]$proof.schema -cne 'qualification_host_probe_v2' -or [string]$proof.status -cne 'PASS' -or [string]$proof.name -cne $row.Name) { throw 'Host probe failed' }
    }
    Read-WeatherQualificationReference -Root $root -Reference $receipt.invocation | Out-Null
    if ($null -ne $receipt.audit) { Read-WeatherQualificationReference -Root $root -Reference $receipt.audit | Out-Null }
    # Actual merge consumes the complete Python host reader again, including
    # measured resource proofs and whole current-input/audit dependency graphs.
    return [pscustomobject]@{ Receipt=$receipt; ReceiptPath=[string]$m.evidence.host_receipt; ReceiptSha256=[string]$ref.sha256 }
}

function Assert-WeatherQualificationPublishedProof {
    param([Parameter(Mandatory = $true)]$AttemptContract, [Parameter(Mandatory = $true)]$QuietReport)
    . (Join-Path $PSScriptRoot 'workload_admission.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
    $m = $AttemptContract.Manifest; $root = $AttemptContract.AttemptRoot
    $proof = $QuietReport.split_qualification
    Assert-WeatherQualificationFields -Value $proof -Names @('manifest_path', 'manifest_sha256', 'commit_invocation_started', 'published_boundary', 'published_native', 'boundaries', 'capture')
    if ([string]$QuietReport.operation_mode -cne 'split_qualification_v2' -or
        [string]$proof.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$proof.manifest_path) -Right $AttemptContract.ManifestPath) -or
        $proof.commit_invocation_started -isnot [bool] -or -not $proof.commit_invocation_started -or
        [string]$proof.published_boundary.path -cne 'merge-work/published/boundary.json' -or
        [string]$proof.published_native.path -cne 'merge-work/published/native.json') { throw 'Split publication proof belongs to another attempt' }
    $state = Read-WeatherQualificationHostAttempt -ManifestPath $AttemptContract.ManifestPath -ExpectedManifestSha256 $AttemptContract.ManifestSha256
    $maximum = $state.Measurements.phases.metadata.maximum
    foreach ($phase in @('prepare', 'prepared', 'before-stage', 'staged', 'before-commit', 'committed', 'before-push', 'published')) {
        $bound = $proof.boundaries.PSObject.Properties[$phase].Value
        Assert-WeatherQualificationFields -Value $bound -Names @('boundary', 'native')
        $boundaryRef = $bound.boundary; $nativeRef = $bound.native
        if ([string]$boundaryRef.path -cne "merge-work/$phase/boundary.json" -or
            [string]$nativeRef.path -cne "merge-work/$phase/native.json") { throw 'Split boundary evidence path differs' }
        $boundary = Read-WeatherQualificationReference -Root $root -Reference $boundaryRef
        $native = Read-WeatherQualificationReference -Root $root -Reference $nativeRef
        if ([string]$boundary.schema -cne 'qualification_merge_boundary_v2' -or [string]$boundary.phase -cne $phase -or
            [string]$boundary.manifest_sha256 -cne $AttemptContract.ManifestSha256 -or
            [string]$boundary.effective_tree -cnotmatch '^[0-9a-f]{40}$' -or
            [string]$boundary.code.certificate_sha256 -cne [string]$m.qualification.certificate.sha256 -or
            $boundary.native_parent_completion_required -ne $true -or $boundary.integration_eligible -ne $false -or
            $native.completed -ne $true -or $native.teardown_proved -ne $true -or $native.exit_code -ne 0 -or $null -ne $native.failure -or
            $native.elapsed_ms -le 0 -or $native.elapsed_ms -gt (1000 * [int]$maximum.seconds) -or
            $native.peak_private_bytes -gt [UInt64]$maximum.commit_bytes -or
            $native.peak_working_set_bytes -gt [UInt64]$maximum.working_set_bytes -or
            $native.maximum_sample_gap_ms -gt 1000 -or $native.resource_samples -lt 1 -or
            $native.native_peak_commit_bytes -gt [UInt64]$maximum.commit_bytes -or
            $native.system_commit_basis_points -gt 6600 -or
            $native.minimum_disk_bytes -lt [UInt64]$state.Policy.host.minimum_disk_bytes) { throw "Split mutation boundary proof failed: $phase" }
        if ($phase -eq 'published' -and (
            [string]$boundaryRef.sha256 -cne [string]$proof.published_boundary.sha256 -or
            [string]$nativeRef.sha256 -cne [string]$proof.published_native.sha256 -or
            [string]$boundary.head -cne [string]$QuietReport.merge_commit -or
            [string]$boundary.prepared_baseline -cne [string]$QuietReport.pre_merge_commit)) { throw 'Published split tree differs from the guarded merge report' }
    }
    if ($proof.capture.ok -ne $true -or @($proof.capture.workers).Count -ne 3 -or
        @($proof.capture.workers | Where-Object { $_.ok -ne $true }).Count -ne 0) { throw 'Post-publication split capture proof failed' }
}
