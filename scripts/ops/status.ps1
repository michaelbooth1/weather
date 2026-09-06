# Overall host health check for the weather production PC -- one command that both
# GATHERS and INTERPRETS state, so a status update is a single tool call.
#
#   .\scripts\ops\status.ps1          # compact human digest (default)
#   .\scripts\ops\status.ps1 -Json     # machine-readable; exit 2 if any FLAG
#
# It delegates the streak to the authoritative checker (streak_status.py, which reads
# the ledger) and adds capture-loop priority, resources, the daily chain, git/push
# state, scheduled-task health, and recent alerts. Crucially it encodes what is
# EXPECTED vs anomalous (e.g. the daily chain exiting 0x2 = model-skill gates BLOCK
# pre-release, the tape backup being broken since Jun 30) so only genuine problems
# land in FLAGS. Pure host tooling, imports nothing from a capture loop -> roll-free.
# See docs/ops/streak-soak.md.
[CmdletBinding()]
param(
    [switch]$Json,
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "SilentlyContinue"
# Windows PowerShell -File binds parameter defaults before PSScriptRoot is set.
# Resolve it in the script body so scheduled subprocesses use this checkout too.
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repo = [IO.Path]::GetFullPath($RepoRoot)
$py = Join-Path $repo "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

$flags = New-Object System.Collections.Generic.List[string]
$warns = New-Object System.Collections.Generic.List[string]

function Get-WeatherIntegrationValidatedEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ExpectedManifestSha256,
        [Parameter(Mandatory = $true)]
        [ValidateSet("manifest", "registration_intent", "registration", "suite", "merge", "reconciliation", "closure", "dispatch", "claim", "quiet_report")]
        [string]$Target
    )

    # Dot-source the strict contract inside this function scope so malformed
    # evidence fails closed without changing the legacy status script's outer
    # SilentlyContinue/strict-mode behavior.
    $contractScript = Join-Path $RepositoryRoot "scripts\ops\integration_attempt_contract.ps1"
    . $contractScript
    $attemptContract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath $ManifestPath `
        -ExpectedSha256 $ExpectedManifestSha256
    $attempt = $attemptContract.Manifest
    if ($Target -eq "manifest") {
        return [pscustomobject]@{ Payload = $attempt; Status = "VALID"; Sha256 = $attemptContract.ManifestSha256 }
    }

    function Assert-StatusSafetyBoundary {
        param([Parameter(Mandatory = $true)][object]$Payload)
        if ([string]$Payload.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
            [bool]$Payload.safety.credential_value_access_authorized -or
            [bool]$Payload.safety.live_exchange_mutation_authorized) {
            throw "Evidence violates the integration-attempt safety boundary."
        }
    }

    function Assert-StatusCommonIdentity {
        param([Parameter(Mandatory = $true)][object]$Payload)
        if ([string]$Payload.attempt_id -ne [string]$attempt.attempt_id -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$Payload.manifest_path) -Right $attemptContract.ManifestPath) -or
            [string]$Payload.manifest_sha256 -ne [string]$attemptContract.ManifestSha256) {
            throw "Evidence is not bound to the task-selected manifest identity and hash."
        }
    }

    function Assert-StatusMergeParents {
        param([Parameter(Mandatory = $true)][object]$PublicationRecord)

        $commit = [string]$PublicationRecord.merge_commit
        $firstParent = @(& git -C ([string]$attempt.repo_root) rev-parse "$commit^1")
        $firstExit = $LASTEXITCODE
        $secondParent = @(& git -C ([string]$attempt.repo_root) rev-parse "$commit^2")
        $secondExit = $LASTEXITCODE
        $parentLine = @(& git -C ([string]$attempt.repo_root) rev-list --parents -n 1 $commit)
        $parentLineExit = $LASTEXITCODE
        if ($firstExit -ne 0 -or $secondExit -ne 0 -or
            $parentLineExit -ne 0 -or $parentLine.Count -ne 1 -or
            @(([string]$parentLine[0]) -split '\s+' | Where-Object { $_ }).Count -ne 3 -or
            $firstParent.Count -ne 1 -or $secondParent.Count -ne 1 -or
            ([string]$firstParent[0]).Trim().ToLowerInvariant() -ne
                ([string]$PublicationRecord.pre_merge_commit).ToLowerInvariant() -or
            ([string]$secondParent[0]).Trim().ToLowerInvariant() -ne
                ([string]$attempt.expected_tip).ToLowerInvariant()) {
            throw "Publication evidence does not identify the exact two-parent merge."
        }
    }

    function Assert-StatusDocumentationProof {
        param([Parameter(Mandatory = $true)][object]$PublicationRecord)

        $pendingSha256 = ([string]$PublicationRecord.documentation_transaction_pending_sha256).ToLowerInvariant()
        $snapshotRelative = ([string]$PublicationRecord.documentation_transaction_snapshot_path).Replace('\', '/')
        $expectedRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
        $snapshotPath = Join-Path ([string]$attempt.repo_root) ($snapshotRelative -replace '/', '\')
        if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
            $snapshotRelative -cne $expectedRelative -or
            (Get-WeatherIntegrationFileSha256 -Path $snapshotPath) -ne $pendingSha256) {
            throw "Documentation transaction snapshot identity/hash is invalid."
        }
        $snapshot = Read-WeatherIntegrationSharedJson -Path $snapshotPath
        $matchingEntries = @($snapshot.integrations | Where-Object {
            ([string]$_.integration_tip).ToLowerInvariant() -eq
                ([string]$PublicationRecord.merge_commit).ToLowerInvariant() -and
            [string]$_.branch -ceq [string]$attempt.branch_ref -and
            ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$attempt.expected_tip
        })
        if ([string]$snapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
            [string]$snapshot.status -ne "PENDING" -or
            ([string]$snapshot.latest_integration_tip).ToLowerInvariant() -ne
                ([string]$PublicationRecord.merge_commit).ToLowerInvariant() -or
            $matchingEntries.Count -ne 1) {
            throw "Documentation snapshot does not bind the exact merge/branch/tip."
        }
    }

    function Assert-StatusQuietReport {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [AllowEmptyString()][string]$ExpectedSha256 = "",
            [switch]$RequirePublication,
            [switch]$AllowMergedUnpushed,
            [switch]$AllowPreDocumentation
        )
        $canonicalPath = [string]$attempt.evidence.quiet_merge_report
        if (-not (Test-WeatherIntegrationPathEqual -Left $Path -Right $canonicalPath)) {
            throw "Quiet-merge report path is not canonical for this attempt."
        }
        $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $canonicalPath
        if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
            $actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
            throw "Quiet-merge report hash is not the recorded immutable hash."
        }
        $report = Read-WeatherIntegrationSharedJson -Path $canonicalPath
        $isPushedReport = ([string]$report.stage -eq "pushed")
        $isRecoveredUnpushedReport = (
            $AllowMergedUnpushed.IsPresent -and
            [string]$report.stage -eq "merged_unpushed"
        )
        if ([string]$report.schema -ne "quiet_window_merge_report_v0.2" -or
            [string]$report.branch -ne [string]$attempt.branch_ref -or
            [string]$report.expected_tip -ne [string]$attempt.expected_tip -or
            [string]$report.expected_baseline -ne [string]$attempt.baseline.master -or
            (-not [string]::IsNullOrWhiteSpace([string]$report.baseline_commit) -and
                [string]$report.baseline_commit -ne [string]$attempt.baseline.master) -or
            (-not [string]::IsNullOrWhiteSpace([string]$report.resolved_branch_tip) -and
                [string]$report.resolved_branch_tip -ne [string]$attempt.expected_tip) -or
            (-not [string]::IsNullOrWhiteSpace([string]$report.pre_merge_commit) -and
                [string]$report.pre_merge_commit -notmatch '^[0-9a-f]{40}$') -or
            (-not [string]::IsNullOrWhiteSpace([string]$report.merge_commit) -and
                [string]$report.merge_commit -notmatch '^[0-9a-f]{40}$')) {
            throw "Quiet-merge report schema or identity is invalid."
        }
        if ($RequirePublication -and (
            -not [bool]$report.ok -or
            (-not $isPushedReport -and -not $isRecoveredUnpushedReport) -or
            [string]$report.baseline_commit -ne [string]$attempt.baseline.master -or
            [string]$report.resolved_branch_tip -ne [string]$attempt.expected_tip -or
            [string]$report.merge_commit -notmatch '^[0-9a-f]{40}$' -or
            -not [bool]$report.capture_recovery_proved -or
            ([bool]$report.execution_tape_recovery_required -and
                -not [bool]$report.execution_tape_recovery_proved) -or
            (-not [bool]$report.documentation_transaction_recorded -and
                -not $AllowPreDocumentation.IsPresent) -or
            ($isPushedReport -and -not [bool]$report.publication_acknowledged)
        )) {
            throw "Quiet-merge report does not prove the exact recovered integration commit."
        }
        if ($RequirePublication) {
            Assert-StatusMergeParents -PublicationRecord $report
            if ([bool]$report.documentation_transaction_recorded) {
                Assert-StatusDocumentationProof -PublicationRecord $report
            }
            elseif ($isPushedReport) {
                throw "Pushed report lacks exact documentation transaction evidence."
            }
        }
        return [pscustomobject]@{ Payload = $report; Sha256 = $actualSha256; Path = $canonicalPath }
    }

    function Assert-StatusPriorMarkerAbortReport {
        param([Parameter(Mandatory = $true)][object]$PublicationEvidence)

        $path = [string]$PublicationEvidence.supporting_prior_marker_abort_path
        $sha256 = [string]$PublicationEvidence.supporting_prior_marker_abort_sha256
        $raw = [string]$PublicationEvidence.supporting_prior_marker_abort_raw
        $rawHash = [Security.Cryptography.SHA256]::Create()
        try {
            $rawSha256 = ([BitConverter]::ToString(
                $rawHash.ComputeHash([Text.Encoding]::UTF8.GetBytes($raw))
            ) -replace '-', '').ToLowerInvariant()
        }
        finally { $rawHash.Dispose() }
        try { $report = $raw | ConvertFrom-Json }
        catch { throw "Supporting prior-marker abort report JSON is invalid." }
        Assert-WeatherIntegrationBooleanProperties `
            -Object $report `
            -Names @(
                "ok", "capture_recovery_proved", "execution_tape_recovery_required",
                "execution_tape_readoption_expected", "execution_tape_rolled_but_inactive_skipped",
                "execution_tape_recovery_proved", "documentation_transaction_recorded",
                "publication_acknowledged"
            ) `
            -Label "supporting prior-marker abort report"
        $expectedDetail = "a prior quiet-window merge marker still exists - let WeatherBootRecovery reconcile it before another merge"
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left $path -Right ([string]$attempt.evidence.quiet_merge_report)) -or
            $sha256 -notmatch '^[0-9a-f]{64}$' -or $rawSha256 -ne $sha256 -or
            (Get-WeatherIntegrationFileSha256 -Path $path) -ne $sha256 -or
            [string]$report.schema -ne "quiet_window_merge_report_v0.2" -or
            [bool]$report.ok -or [string]$report.stage -ne "abort" -or
            [string]$report.detail -cne $expectedDetail -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$report.repo_root) -Right ([string]$attempt.repo_root)) -or
            [string]$report.branch -ne [string]$attempt.branch_ref -or
            [string]$report.expected_tip -ne [string]$attempt.expected_tip -or
            [string]$report.expected_baseline -ne [string]$attempt.baseline.master -or
            -not [string]::IsNullOrWhiteSpace([string]$report.resolved_branch_tip) -or
            -not [string]::IsNullOrWhiteSpace([string]$report.baseline_commit) -or
            -not [string]::IsNullOrWhiteSpace([string]$report.pre_merge_commit) -or
            -not [string]::IsNullOrWhiteSpace([string]$report.merge_commit) -or
            @($report.rollback_content_sha256.PSObject.Properties).Count -ne 0 -or
            [bool]$report.capture_recovery_proved -or
            ([bool]$report.execution_tape_recovery_required -and
                [bool]$report.execution_tape_rolled_but_inactive_skipped) -or
            ([bool]$report.execution_tape_rolled_but_inactive_skipped -and
                -not [bool]$report.execution_tape_readoption_expected) -or
            [bool]$report.execution_tape_recovery_proved -or
            $null -ne $report.execution_tape_source_before -or
            [bool]$report.documentation_transaction_recorded -or
            -not [string]::IsNullOrWhiteSpace([string]$report.documentation_transaction_pending_sha256) -or
            -not [string]::IsNullOrWhiteSpace([string]$report.documentation_transaction_snapshot_path) -or
            [bool]$report.publication_acknowledged -or
            @($report.log | Where-Object { [string]$_ -like "*ABORT: $expectedDetail" }).Count -ne 1) {
            throw "Supporting abort report is not the exact evidence-free prior-marker refusal."
        }
    }

    function Assert-StatusPriorMarkerFailReceipt {
        param([Parameter(Mandatory = $true)][object]$PublicationEvidence)

        $path = [string]$PublicationEvidence.merge_receipt_path
        $sha256 = [string]$PublicationEvidence.merge_receipt_sha256
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left $path -Right ([string]$attempt.evidence.merge_receipt)) -or
            $sha256 -notmatch '^[0-9a-f]{64}$' -or
            (Get-WeatherIntegrationFileSha256 -Path $path) -ne $sha256) {
            throw "Supporting prior-marker FAIL receipt path/hash is invalid."
        }
        $receipt = Read-WeatherIntegrationSharedJson -Path $path
        if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
            [string]$receipt.status -ne "FAIL" -or
            [string]$receipt.attempt_id -ne [string]$attempt.attempt_id -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$receipt.manifest_path) -Right $attemptContract.ManifestPath) -or
            [string]$receipt.manifest_sha256 -ne [string]$attemptContract.ManifestSha256 -or
            [string]$receipt.source_tip -ne [string]$attempt.expected_tip -or
            [string]$receipt.branch_ref -ne [string]$attempt.branch_ref -or
            [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
            [bool]$receipt.safety.credential_value_access_authorized -or
            [bool]$receipt.safety.live_exchange_mutation_authorized -or
            [bool]$receipt.origin_master_verified -or
            [bool]$receipt.source_tip_integrated -or
            [bool]$receipt.capture_recovery_proved -or
            [bool]$receipt.documentation_transaction_recorded) {
            throw "Supporting prior-marker FAIL receipt contains contradictory evidence."
        }
        foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
            $receiptScript = $receipt.scripts.$scriptName
            $manifestScript = $attempt.orchestration.$scriptName
            if ($null -eq $receiptScript -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
                [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
                throw "Supporting prior-marker FAIL receipt script binding is invalid: $scriptName"
            }
        }
        $suiteContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $attemptContract
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$receipt.suite_receipt_path) -Right $suiteContract.ReceiptPath) -or
            [string]$receipt.suite_receipt_sha256 -ne [string]$suiteContract.ReceiptSha256 -or
            -not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$receipt.quiet_merge_report.path) `
                -Right ([string]$PublicationEvidence.supporting_prior_marker_abort_path)) -or
            [string]$receipt.quiet_merge_report.sha256 -ne
                [string]$PublicationEvidence.supporting_prior_marker_abort_sha256) {
            throw "Supporting prior-marker FAIL receipt does not bind its suite/abort evidence."
        }
        $abortRaw = [string]$PublicationEvidence.supporting_prior_marker_abort_raw
        try { $abortReport = $abortRaw | ConvertFrom-Json }
        catch { throw "Supporting prior-marker abort report JSON is invalid." }
        if (($receipt.quiet_merge_report.payload | ConvertTo-Json -Depth 8 -Compress) -cne
            ($abortReport | ConvertTo-Json -Depth 8 -Compress)) {
            throw "Supporting prior-marker FAIL receipt does not embed its exact abort payload."
        }
    }

    function Assert-StatusFailedMergeReceiptRecovery {
        param(
            [Parameter(Mandatory = $true)][string]$ExpectedReceiptSha256,
            [switch]$AllowPreDocumentation
        )

        $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$attempt.evidence.merge_receipt)
        if ((Get-WeatherIntegrationFileSha256 -Path $receiptPath) -ne $ExpectedReceiptSha256) {
            throw "Recovered FAIL merge-receipt hash binding is invalid."
        }
        $receipt = Read-WeatherIntegrationSharedJson -Path $receiptPath
        Assert-StatusCommonIdentity -Payload $receipt
        Assert-StatusSafetyBoundary -Payload $receipt
        if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
            [string]$receipt.status -ne "FAIL" -or
            [string]$receipt.source_tip -ne [string]$attempt.expected_tip -or
            [string]$receipt.branch_ref -ne [string]$attempt.branch_ref) {
            throw "Recovered FAIL merge receipt schema or identity is invalid."
        }
        foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
            $receiptScript = $receipt.scripts.$scriptName
            $manifestScript = $attempt.orchestration.$scriptName
            if ($null -eq $receiptScript -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
                [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
                throw "Recovered FAIL merge-receipt script binding is invalid: $scriptName"
            }
        }
        $suiteContract = Assert-WeatherIntegrationSuiteReceipt -AttemptContract $attemptContract
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$receipt.suite_receipt_path) `
                -Right ([string]$suiteContract.ReceiptPath)) -or
            [string]$receipt.suite_receipt_sha256 -ne [string]$suiteContract.ReceiptSha256) {
            throw "Recovered FAIL merge receipt does not bind its exact PASS suite receipt."
        }
        $quietContract = Assert-StatusQuietReport `
            -Path ([string]$receipt.quiet_merge_report.path) `
            -ExpectedSha256 ([string]$receipt.quiet_merge_report.sha256) `
            -RequirePublication `
            -AllowMergedUnpushed `
            -AllowPreDocumentation:($AllowPreDocumentation.IsPresent)
        if ([string]$quietContract.Payload.stage -ne "merged_unpushed" -or
            [string]$receipt.quiet_merge_report.payload.schema -ne [string]$quietContract.Payload.schema -or
            [string]$receipt.quiet_merge_report.payload.stage -ne [string]$quietContract.Payload.stage -or
            [string]$receipt.quiet_merge_report.payload.merge_commit -ne [string]$quietContract.Payload.merge_commit -or
            [string]$receipt.quiet_merge_report.payload.expected_tip -ne [string]$quietContract.Payload.expected_tip -or
            [string]$receipt.quiet_merge_report.payload.expected_baseline -ne [string]$quietContract.Payload.expected_baseline) {
            throw "Recovered FAIL merge receipt does not embed its exact hash-bound quiet report."
        }
        return [pscustomobject]@{
            Receipt = $receipt
            ReceiptPath = $receiptPath
            ReceiptSha256 = $ExpectedReceiptSha256
            QuietReport = $quietContract.Payload
            QuietReportSha256 = $quietContract.Sha256
        }
    }

    $evidencePath = switch ($Target) {
        "registration_intent" { Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $attemptContract }
        "registration" { [string]$attempt.evidence.registration_receipt }
        "suite" { [string]$attempt.evidence.suite_receipt }
        "merge" { [string]$attempt.evidence.merge_receipt }
        "reconciliation" { [string]$attempt.evidence.reconciliation_receipt }
        "closure" { [string]$attempt.evidence.closure_receipt }
        "dispatch" { [string]$attempt.evidence.recovery_dispatch }
        "claim" { Join-Path ([string]$attempt.attempt_root) "successor-claim.json" }
        "quiet_report" { [string]$attempt.evidence.quiet_merge_report }
    }
    if ($Target -eq "quiet_report") {
        $quietContract = Assert-StatusQuietReport `
            -Path $evidencePath `
            -RequirePublication `
            -AllowMergedUnpushed `
            -AllowPreDocumentation
        $quietStatus = if ([string]$quietContract.Payload.stage -eq "pushed") {
            "PUBLISHED"
        }
        else { "RECOVERED_UNPUSHED" }
        return [pscustomobject]@{ Payload = $quietContract.Payload; Status = $quietStatus; Sha256 = $quietContract.Sha256 }
    }
    $payload = Read-WeatherIntegrationSharedJson -Path $evidencePath
    $evidenceSha256 = Get-WeatherIntegrationFileSha256 -Path $evidencePath
    $validatedStatus = [string]$payload.status

    if ($Target -notin @("claim", "registration_intent")) {
        Assert-StatusCommonIdentity -Payload $payload
    }
    if ($Target -notin @("claim", "registration_intent", "registration")) {
        Assert-StatusSafetyBoundary -Payload $payload
    }
    if ($Target -eq "registration_intent") {
        $intentContract = Assert-WeatherIntegrationRegistrationIntent `
            -AttemptContract $attemptContract `
            -ExpectedSha256 $evidenceSha256
        $payload = $intentContract.Intent
    }
    elseif ($Target -eq "registration") {
        $registrationContract = Assert-WeatherIntegrationRegistrationReceipt `
            -AttemptContract $attemptContract
        $payload = $registrationContract.Receipt
        $evidenceSha256 = $registrationContract.ReceiptSha256
    }
    elseif ($Target -eq "suite") {
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptSuiteReceiptSchema -or
            [string]$payload.status -notin @("PASS", "FAIL") -or
            [string]$payload.expected_tip -ne [string]$attempt.expected_tip -or
            [string]$payload.branch_ref -ne [string]$attempt.branch_ref -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.worktree_root) -Right ([string]$attempt.worktree_root))) {
            throw "Suite receipt schema or identity is invalid."
        }
        $suiteIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $attemptContract
        $suiteRegistrationPath = [string]$attempt.evidence.registration_receipt
        if ((Get-WeatherIntegrationFileSha256 -Path $suiteIntentPath) -ne
                [string]$payload.registration_intent_sha256 -or
            (Get-WeatherIntegrationFileSha256 -Path $suiteRegistrationPath) -ne
                [string]$payload.registration_receipt_sha256) {
            throw "Suite receipt registration intent/receipt hashes are invalid."
        }
        if ([string]$payload.status -eq "PASS") {
            Assert-WeatherIntegrationSuiteReceipt -AttemptContract $attemptContract | Out-Null
        }
        else {
            foreach ($name in @("preflight", "full_suite")) {
                $record = $payload.logs.$name
                if ($null -eq $record) { continue }
                $expectedPath = if ($name -eq "preflight") {
                    [string]$attempt.evidence.preflight_log
                }
                else { [string]$attempt.evidence.full_suite_log }
                if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$record.path) -Right $expectedPath) -or
                    (Get-WeatherIntegrationFileSha256 -Path $expectedPath) -ne [string]$record.sha256) {
                    throw "FAIL suite receipt log binding is invalid: $name"
                }
            }
        }
    }
    elseif ($Target -eq "merge") {
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
            [string]$payload.status -notin @("PASS", "FAIL", "MERGED_UNVERIFIED") -or
            [string]$payload.source_tip -ne [string]$attempt.expected_tip -or
            [string]$payload.branch_ref -ne [string]$attempt.branch_ref) {
            throw "Merge receipt schema or identity is invalid."
        }
        if ([string]$payload.status -eq "PASS") {
            Assert-WeatherIntegrationMergeReceipt `
                -AttemptContract $attemptContract -ExpectedReceiptSha256 $evidenceSha256 | Out-Null
            Assert-StatusQuietReport `
                -Path ([string]$payload.quiet_merge_report.path) `
                -ExpectedSha256 ([string]$payload.quiet_merge_report.sha256) `
                -RequirePublication | Out-Null
        }
        elseif ([string]$payload.status -eq "MERGED_UNVERIFIED") {
            Assert-WeatherIntegrationMergedUnverifiedReceipt `
                -AttemptContract $attemptContract -ExpectedReceiptSha256 $evidenceSha256 | Out-Null
            Assert-StatusQuietReport `
                -Path ([string]$payload.quiet_merge_report.path) `
                -ExpectedSha256 ([string]$payload.quiet_merge_report.sha256) `
                -RequirePublication | Out-Null
        }
        else {
            if (-not [string]::IsNullOrWhiteSpace([string]$payload.suite_receipt_sha256)) {
                $suitePath = [string]$attempt.evidence.suite_receipt
                if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.suite_receipt_path) -Right $suitePath) -or
                    (Get-WeatherIntegrationFileSha256 -Path $suitePath) -ne [string]$payload.suite_receipt_sha256) {
                    throw "FAIL merge receipt suite-receipt binding is invalid."
                }
            }
            if (-not [string]::IsNullOrWhiteSpace([string]$payload.quiet_merge_report.sha256)) {
                $failedQuietContract = Assert-StatusQuietReport `
                    -Path ([string]$payload.quiet_merge_report.path) `
                    -ExpectedSha256 ([string]$payload.quiet_merge_report.sha256)
                if ([bool]$failedQuietContract.Payload.ok -and
                    [string]$failedQuietContract.Payload.stage -eq "merged_unpushed") {
                    Assert-StatusQuietReport `
                        -Path ([string]$payload.quiet_merge_report.path) `
                        -ExpectedSha256 ([string]$payload.quiet_merge_report.sha256) `
                        -RequirePublication `
                        -AllowMergedUnpushed `
                        -AllowPreDocumentation | Out-Null
                    $validatedStatus = "RECOVERED_UNPUSHED"
                }
            }
        }
    }
    elseif ($Target -eq "reconciliation") {
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptReconciliationReceiptSchema -or
            [string]$payload.status -ne "MERGED_RECONCILED" -or
            [bool]$payload.historical_proof_upgraded -or [bool]$payload.downstream_authorized -or
            ([bool]$payload.publication_resume.performed -and
                -not [bool]$payload.publication_resume.requested) -or
            -not [bool]$payload.current_proofs.checked_out_master_equals_origin -or
            -not [bool]$payload.current_proofs.published_integration_commit_in_history -or
            -not [bool]$payload.current_proofs.frozen_source_tip_in_history -or
            -not [bool]$payload.current_proofs.capture_recovery_current -or
            -not [bool]$payload.current_proofs.exact_merge_parents_current -or
            ([bool]$payload.current_proofs.execution_tape_recovery_required -and
                -not [bool]$payload.current_proofs.execution_tape_recovery_current) -or
            [string]$payload.current_proofs.production_head -notmatch '^[0-9a-f]{40}$' -or
            [string]$payload.current_proofs.production_head -ne [string]$payload.current_proofs.origin_master -or
            -not [bool]$payload.current_proofs.capture.ok -or
            @($payload.current_proofs.capture.workers).Count -ne 3 -or
            @($payload.current_proofs.capture.workers | Where-Object { -not [bool]$_.ok }).Count -ne 0 -or
            @($payload.tasks | Where-Object { [bool]$_.exists -and -not [bool]$_.disabled }).Count -ne 0) {
            throw "Reconciliation receipt is structurally invalid or authorizing."
        }
        if ([bool]$payload.current_proofs.execution_tape_recovery_required) {
            $tape = $payload.current_proofs.execution_tape
            $tapeHealth = $tape.payload.health
            $tapeStatus = $tape.payload.status
            $tapeLock = $tape.writer_lock
            if ([string]$tapeHealth.state -notin @("RUNNING", "DEGRADED") -or
                $tapeHealth.pid_alive -ne $true -or
                $tapeHealth.runtime_identity_matches_current -ne $true -or
                [string]$tapeHealth.evidence_integrity -ne "PASS" -or
                [string]$tapeStatus.state -ne "CONNECTED" -or
                [string]$tapeStatus.market -ne "all" -or
                [string]$tapeStatus.runner -ne "managed_execution_tape" -or
                $tapeStatus.managed_process.verified_at_capture -ne $true -or
                [int]$tapeStatus.pid -le 0 -or
                [int]$tapeStatus.pid -ne [int]$tapeStatus.managed_process.pid -or
                [int]$tapeStatus.pid -ne [int]$tapeLock.pid -or
                [int]$tapeStatus.pid -ne [int]$tapeLock.managed_process.pid -or
                [string]$tapeStatus.managed_process.creation_time_token -cne
                    [string]$tapeLock.managed_process.creation_time_token) {
                throw "Reconciliation receipt execution-tape proof is structurally invalid."
            }
        }
        $reconciliationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $attemptContract
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$payload.registration_evidence.intent_path) `
                -Right $reconciliationIntentPath) -or
            (Get-WeatherIntegrationFileSha256 -Path $reconciliationIntentPath) -ne
                [string]$payload.registration_evidence.intent_sha256) {
            throw "Reconciliation registration-intent hash binding is invalid."
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$payload.registration_evidence.receipt_sha256)) {
            $reconciliationRegistrationReceipt = [string]$attempt.evidence.registration_receipt
            if (-not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$payload.registration_evidence.receipt_path) `
                    -Right $reconciliationRegistrationReceipt) -or
                (Get-WeatherIntegrationFileSha256 -Path $reconciliationRegistrationReceipt) -ne
                    [string]$payload.registration_evidence.receipt_sha256) {
                throw "Reconciliation registration-receipt hash binding is invalid."
            }
        }
        $publicationKind = [string]$payload.publication_evidence.kind
        if ($publicationKind -eq "merge_receipt") {
            $boundPath = [string]$attempt.evidence.merge_receipt
            if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.publication_evidence.merge_receipt_path) -Right $boundPath) -or
                (Get-WeatherIntegrationFileSha256 -Path $boundPath) -ne [string]$payload.publication_evidence.merge_receipt_sha256) {
                throw "Reconciliation merge-receipt hash binding is invalid."
            }
            $boundMergeContract = Assert-WeatherIntegrationMergedUnverifiedReceipt `
                -AttemptContract $attemptContract `
                -ExpectedReceiptSha256 ([string]$payload.publication_evidence.merge_receipt_sha256)
            if ([string]$payload.publication_evidence.published_integration_commit -ne
                [string]$boundMergeContract.Receipt.production_head) {
                throw "Reconciliation published commit does not match its MERGED_UNVERIFIED receipt."
            }
        }
        elseif ($publicationKind -eq "failed_merge_receipt") {
            $boundPath = [string]$attempt.evidence.merge_receipt
            if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.publication_evidence.merge_receipt_path) -Right $boundPath) -or
                (Get-WeatherIntegrationFileSha256 -Path $boundPath) -ne [string]$payload.publication_evidence.merge_receipt_sha256) {
                throw "Reconciliation recovered FAIL merge-receipt hash binding is invalid."
            }
            $failedMergeContract = Assert-StatusFailedMergeReceiptRecovery `
                -ExpectedReceiptSha256 ([string]$payload.publication_evidence.merge_receipt_sha256) `
                -AllowPreDocumentation:([bool]$payload.publication_resume.performed)
            if ([string]$payload.historical_merge_status -ne "PUBLISHED_AFTER_FAILED_PUSH_ACK" -or
                [string]$payload.publication_evidence.published_integration_commit -ne
                    [string]$failedMergeContract.QuietReport.merge_commit) {
                throw "Reconciliation recovered FAIL receipt does not bind its exact published commit."
            }
        }
        elseif ($publicationKind -eq "active_marker") {
            $markerRaw = [string]$payload.publication_evidence.active_marker_raw
            $sha = [Security.Cryptography.SHA256]::Create()
            try {
                $markerRawSha256 = ([BitConverter]::ToString(
                    $sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($markerRaw))
                ) -replace '-', '').ToLowerInvariant()
            }
            finally { $sha.Dispose() }
            if ($markerRawSha256 -ne [string]$payload.publication_evidence.active_marker_sha256) {
                throw "Reconciliation embedded active-marker hash is invalid."
            }
            try { $marker = $markerRaw | ConvertFrom-Json }
            catch { throw "Reconciliation embedded active-marker JSON is invalid." }
            Assert-WeatherIntegrationBooleanProperties `
                -Object $marker `
                -Names @("execution_tape_readoption_expected") `
                -Label "reconciliation embedded active marker"
            $markerWasResumedBeforeDocumentation = (
                [bool]$payload.publication_resume.performed -and
                [string]$marker.phase -eq "merge_committed_unpublished"
            )
            if ([string]$marker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$marker.repo_root) -Right ([string]$attempt.repo_root)) -or
                ([string]$marker.phase -notin @("documented_unpublished", "published") -and
                    -not $markerWasResumedBeforeDocumentation) -or
                [string]$marker.branch -ne [string]$attempt.branch_ref -or
                [string]$marker.expected_tip -ne [string]$attempt.expected_tip -or
                [string]$marker.expected_baseline -ne [string]$attempt.baseline.master -or
                [string]$marker.resolved_branch_tip -ne [string]$attempt.expected_tip -or
                [string]$marker.baseline_commit -ne [string]$attempt.baseline.master -or
                [string]$marker.merge_commit -ne [string]$payload.publication_evidence.published_integration_commit -or
                -not [bool]$marker.capture_recovery_proved -or
                ([bool]$marker.execution_tape_recovery_required -and
                    -not [bool]$marker.execution_tape_recovery_proved) -or
                (-not $markerWasResumedBeforeDocumentation -and
                    -not [bool]$marker.documentation_transaction_recorded) -or
                ($markerWasResumedBeforeDocumentation -and
                    [bool]$marker.documentation_transaction_recorded) -or
                ([string]$marker.phase -eq "published" -and
                    -not [bool]$marker.publication_acknowledged)) {
                throw "Reconciliation embedded active marker does not prove the attempt publication."
            }
            Assert-StatusMergeParents -PublicationRecord $marker
            if ([bool]$marker.documentation_transaction_recorded) {
                Assert-StatusDocumentationProof -PublicationRecord $marker
            }
            if (-not [string]::IsNullOrWhiteSpace(
                    [string]$payload.publication_evidence.supporting_quiet_merge_report_sha256)) {
                $supportingQuiet = Assert-StatusQuietReport `
                    -Path ([string]$payload.publication_evidence.supporting_quiet_merge_report_path) `
                    -ExpectedSha256 ([string]$payload.publication_evidence.supporting_quiet_merge_report_sha256) `
                    -RequirePublication `
                    -AllowMergedUnpushed `
                    -AllowPreDocumentation:([bool]$payload.publication_resume.performed)
                if ([string]$supportingQuiet.Payload.stage -ne "merged_unpushed" -or
                    [string]$supportingQuiet.Payload.merge_commit -ne [string]$marker.merge_commit) {
                    throw "Reconciliation supporting quiet report does not match its active marker."
                }
            }
            if (-not [string]::IsNullOrWhiteSpace(
                    [string]$payload.publication_evidence.supporting_prior_marker_abort_sha256)) {
                Assert-StatusPriorMarkerAbortReport `
                    -PublicationEvidence $payload.publication_evidence
            }
            if (-not [string]::IsNullOrWhiteSpace(
                    [string]$payload.publication_evidence.merge_receipt_sha256)) {
                if ([string]::IsNullOrWhiteSpace(
                        [string]$payload.publication_evidence.supporting_prior_marker_abort_sha256)) {
                    throw "Active-marker reconciliation may subordinate a FAIL receipt only with its exact prior-marker abort report."
                }
                Assert-StatusPriorMarkerFailReceipt `
                    -PublicationEvidence $payload.publication_evidence
            }
        }
        elseif ($publicationKind -ne "quiet_merge_report") {
            throw "Reconciliation publication-evidence kind is unsupported."
        }
        if ($publicationKind -ne "active_marker" -and
            -not [string]::IsNullOrWhiteSpace(
                [string]$payload.publication_evidence.supporting_prior_marker_abort_sha256)) {
            throw "Only active-marker reconciliation may subordinate a prior-marker abort report."
        }
        if (-not [string]::IsNullOrWhiteSpace(
                [string]$payload.publication_evidence.supporting_active_marker_sha256)) {
            $supportingMarkerRaw = [string]$payload.publication_evidence.supporting_active_marker_raw
            $supportingSha = [Security.Cryptography.SHA256]::Create()
            try {
                $supportingMarkerSha256 = ([BitConverter]::ToString(
                    $supportingSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($supportingMarkerRaw))
                ) -replace '-', '').ToLowerInvariant()
            }
            finally { $supportingSha.Dispose() }
            try { $supportingMarker = $supportingMarkerRaw | ConvertFrom-Json }
            catch { throw "Reconciliation supporting active-marker JSON is invalid." }
            Assert-WeatherIntegrationBooleanProperties `
                -Object $supportingMarker `
                -Names @("execution_tape_readoption_expected") `
                -Label "reconciliation supporting active marker"
            if ($supportingMarkerSha256 -ne
                    [string]$payload.publication_evidence.supporting_active_marker_sha256 -or
                [string]$supportingMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
                -not (Test-WeatherIntegrationPathEqual `
                    -Left ([string]$supportingMarker.repo_root) -Right ([string]$attempt.repo_root)) -or
                [string]$supportingMarker.phase -notin @(
                    "merge_committed_unpublished", "documented_unpublished", "published"
                ) -or
                [string]$supportingMarker.branch -ne [string]$attempt.branch_ref -or
                [string]$supportingMarker.expected_tip -ne [string]$attempt.expected_tip -or
                [string]$supportingMarker.expected_baseline -ne [string]$attempt.baseline.master -or
                [string]$supportingMarker.merge_commit -ne
                    [string]$payload.publication_evidence.published_integration_commit -or
                -not [bool]$supportingMarker.capture_recovery_proved -or
                ([bool]$supportingMarker.execution_tape_recovery_required -and
                    -not [bool]$supportingMarker.execution_tape_recovery_proved)) {
                throw "Reconciliation supporting active marker is not bound to this publication."
            }
            Assert-StatusMergeParents -PublicationRecord $supportingMarker
            if ([bool]$supportingMarker.documentation_transaction_recorded) {
                Assert-StatusDocumentationProof -PublicationRecord $supportingMarker
            }
            elseif (-not [bool]$payload.publication_resume.performed -and
                -not [bool]$payload.publication_evidence.quiet_merge_report_sha256) {
                throw "Lagging supporting marker lacks stronger documentation evidence or reviewed resume."
            }
        }
        if ($publicationKind -ne "active_marker") {
            $boundQuietContract = Assert-StatusQuietReport `
                -Path ([string]$payload.publication_evidence.quiet_merge_report_path) `
                -ExpectedSha256 ([string]$payload.publication_evidence.quiet_merge_report_sha256) `
                -RequirePublication `
                -AllowMergedUnpushed:($publicationKind -eq "failed_merge_receipt" -or
                    [bool]$payload.publication_resume.performed) `
                -AllowPreDocumentation:([bool]$payload.publication_resume.performed)
            if ([string]$payload.publication_evidence.published_integration_commit -ne
                [string]$boundQuietContract.Payload.merge_commit) {
                throw "Reconciliation published commit does not match its hash-bound quiet report."
            }
        }
        if ([bool]$payload.publication_resume.performed) {
            $finalMarkerRaw = [string]$payload.publication_resume.final_marker_raw
            if ([string]::IsNullOrWhiteSpace($finalMarkerRaw)) {
                if (-not [string]::IsNullOrWhiteSpace([string]$payload.publication_resume.final_marker_sha256)) {
                    throw "Publication-resume final marker fields are inconsistent."
                }
            }
            else {
                $resumeSha = [Security.Cryptography.SHA256]::Create()
                try {
                    $finalMarkerSha256 = ([BitConverter]::ToString(
                        $resumeSha.ComputeHash([Text.Encoding]::UTF8.GetBytes($finalMarkerRaw))
                    ) -replace '-', '').ToLowerInvariant()
                }
                finally { $resumeSha.Dispose() }
                try { $finalMarker = $finalMarkerRaw | ConvertFrom-Json }
                catch { throw "Publication-resume final marker JSON is invalid." }
                if ($finalMarkerSha256 -ne [string]$payload.publication_resume.final_marker_sha256 -or
                    [string]$finalMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
                    [string]$finalMarker.phase -ne "published" -or
                    [string]$finalMarker.merge_commit -ne
                        [string]$payload.publication_evidence.published_integration_commit -or
                    -not [bool]$finalMarker.documentation_transaction_recorded -or
                    -not [bool]$finalMarker.publication_acknowledged) {
                    throw "Publication-resume final marker does not prove its documented publication."
                }
                Assert-StatusDocumentationProof -PublicationRecord $finalMarker
            }
        }
    }
    elseif ($Target -eq "closure") {
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
            [string]$payload.status -ne "FAIL" -or
            [string]$payload.expected_tip -ne [string]$attempt.expected_tip -or
            @($payload.tasks).Count -ne 2 -or
            -not [bool]$payload.post_disable_proof.tasks_terminal_and_disabled -or
            -not [bool]$payload.post_disable_proof.merge_head_absent -or
            [string]$payload.post_disable_proof.checked_out_branch -ne "master" -or
            [string]$payload.post_disable_proof.head -ne [string]$attempt.baseline.master -or
            [string]$payload.post_disable_proof.master -ne [string]$attempt.baseline.master -or
            [string]$payload.post_disable_proof.origin_master -ne [string]$attempt.baseline.origin_master -or
            [bool]$payload.post_disable_proof.source_in_master -or
            [bool]$payload.post_disable_proof.source_in_origin -or
            @($payload.tasks | Where-Object { [bool]$_.exists -and -not [bool]$_.disabled }).Count -ne 0) {
            throw "Closure receipt is not a safe exact-attempt FAIL closure."
        }
        $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $attemptContract
        if (-not (Test-WeatherIntegrationPathEqual `
                -Left ([string]$payload.registration_evidence.registration_intent_path) `
                -Right $intentPath) -or
            (-not [string]::IsNullOrWhiteSpace([string]$payload.registration_evidence.registration_intent_sha256) -and
                (Get-WeatherIntegrationFileSha256 -Path $intentPath) -ne
                    [string]$payload.registration_evidence.registration_intent_sha256)) {
            throw "Closure registration-intent evidence is invalid."
        }
        foreach ($record in @($payload.preserved_evidence)) {
            if ([string]$record.sha256 -notmatch '^[0-9a-f]{64}$' -or
                (Get-WeatherIntegrationFileSha256 -Path ([string]$record.path)) -ne [string]$record.sha256) {
                throw "Closure receipt contains a stale preserved-evidence hash."
            }
        }
    }
    elseif ($Target -eq "dispatch") {
        $closurePath = [string]$attempt.evidence.closure_receipt
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptRecoveryDispatchSchema -or
            [string]$payload.status -ne "READY_FOR_SUCCESSOR_REVIEW" -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.closure_receipt_path) -Right $closurePath) -or
            (Get-WeatherIntegrationFileSha256 -Path $closurePath) -ne [string]$payload.closure_receipt_sha256 -or
            [bool]$payload.automatic_source_edit_authorized -or [bool]$payload.scheduler_change_authorized) {
            throw "Recovery dispatch schema, authority, or closure hash is invalid."
        }
    }
    elseif ($Target -eq "claim") {
        $expectedClosurePath = [string]$attempt.evidence.closure_receipt
        $expectedDispatchPath = [string]$attempt.evidence.recovery_dispatch
        if ([string]$payload.schema -ne $script:WeatherIntegrationAttemptSuccessorClaimSchema -or
            [string]$payload.status -ne "CLAIMED" -or
            [string]$payload.predecessor_attempt_id -ne [string]$attempt.attempt_id -or
            [string]$payload.successor_attempt_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$' -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.predecessor_receipt_path) -Right $expectedClosurePath) -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$payload.recovery_dispatch_path) -Right $expectedDispatchPath) -or
            (Get-WeatherIntegrationFileSha256 -Path ([string]$payload.predecessor_receipt_path)) -ne [string]$payload.predecessor_receipt_sha256 -or
            (Get-WeatherIntegrationFileSha256 -Path ([string]$payload.recovery_dispatch_path)) -ne [string]$payload.recovery_dispatch_sha256 -or
            (Get-WeatherIntegrationFileSha256 -Path ([string]$payload.successor_manifest_path)) -ne [string]$payload.successor_manifest_sha256) {
            throw "Successor claim schema, identity, or immutable hash binding is invalid."
        }
        $successorManifest = Read-WeatherIntegrationSharedJson -Path ([string]$payload.successor_manifest_path)
        if ([string]$successorManifest.schema -ne $script:WeatherIntegrationAttemptManifestSchema -or
            [string]$successorManifest.attempt_id -ne [string]$payload.successor_attempt_id -or
            [string]$successorManifest.expected_tip -ne [string]$payload.successor_expected_tip) {
            throw "Successor claim target manifest identity is invalid."
        }
    }

    return [pscustomobject]@{ Payload = $payload; Status = $validatedStatus; Sha256 = $evidenceSha256 }
}

function Assert-WeatherIntegrationStatusTaskBindings {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ExpectedManifestSha256
    )

    . (Join-Path $RepositoryRoot "scripts\ops\integration_attempt_contract.ps1")
    # Legacy schema literal weather_integration_attempt_manifest_v1 is never
    # trusted directly here; the shared manifest contract owns its validation.
    $bindingContract = Assert-WeatherIntegrationAttemptManifest `
        -ManifestPath $ManifestPath `
        -ExpectedSha256 $ExpectedManifestSha256
    $suiteBinding = Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $bindingContract -Role "suite" -IncludeTaskInfo
    $mergeBinding = Assert-WeatherIntegrationAttemptTaskBinding `
        -AttemptContract $bindingContract -Role "merge" -IncludeTaskInfo
    return [pscustomobject]@{ Suite = $suiteBinding; Merge = $mergeBinding }
}

function Get-WeatherIntegrationAttemptState {
    param(
        [AllowEmptyString()][string]$SuiteReceiptStatus = "",
        [AllowEmptyString()][string]$MergeReceiptStatus = "",
        [AllowEmptyString()][string]$ReconciliationStatus = "",
        [AllowEmptyString()][string]$ClosureStatus = "",
        [AllowEmptyString()][string]$DispatchStatus = "",
        [AllowEmptyString()][string]$ClaimStatus = ""
    )

    if ($MergeReceiptStatus -eq "PASS") { return "PASS" }
    if ($ReconciliationStatus -eq "MERGED_RECONCILED") { return "MERGED_RECONCILED" }
    if ($MergeReceiptStatus -eq "MERGED_UNVERIFIED") { return "MERGED_UNVERIFIED" }
    if ($MergeReceiptStatus -eq "RECOVERED_UNPUSHED") { return "MERGED_UNPUSHED" }
    if ($ClaimStatus -eq "CLAIMED") { return "SUCCESSOR_CLAIMED" }
    if ($DispatchStatus -eq "READY_FOR_SUCCESSOR_REVIEW") { return "RECOVERY_READY" }
    if ($ClosureStatus -eq "FAIL") { return "CLOSED_NEEDS_DISPATCH" }
    if ($SuiteReceiptStatus -eq "FAIL" -or $MergeReceiptStatus -eq "FAIL") {
        return "FAILED_NEEDS_CLOSE"
    }
    return "ACTIVE_OR_ARMED"
}

function Get-WeatherIntegrationAttemptAlertDisposition {
    param(
        [Parameter(Mandatory = $true)][string]$AttemptId,
        [Parameter(Mandatory = $true)][string]$State,
        [Parameter(Mandatory = $true)][string]$TaskState,
        [Parameter(Mandatory = $true)][bool]$EvidenceIsFresh,
        [Parameter(Mandatory = $true)][bool]$SuiteTriggerMissed,
        [bool]$SuiteRanWithoutReceipt = $false,
        [bool]$MergeReceiptMissingAfterTrigger = $false,
        [AllowEmptyString()][string]$RecoveryDispatch = "",
        [AllowEmptyString()][string]$SuccessorAttemptId = "",
        [AllowEmptyString()][string]$PublicationClassification = "ordinary"
    )

    $severity = "NONE"
    $detail = ""
    if ($State -eq "MERGED_UNVERIFIED") {
        $detail = "integration attempt $AttemptId reached production but final proof is incomplete; do not retry it"
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "MERGED_UNPUSHED") {
        $detail = if ($PublicationClassification -ceq "ordinary") {
            "integration attempt $AttemptId has a recovery-proved local merge not acknowledged by origin; obtain review, resume publication, and do not retry it"
        }
        else {
            "RECONCILIATION_PUBLICATION_RELATED_ATTEMPT: integration attempt $AttemptId has a recovery-proved local merge not acknowledged by origin; the active reconciliation marker owns publication, so preserve exact evidence and do not manually invoke or retry WeatherOneShotPush"
        }
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "MERGED_RECONCILED") {
        $detail = "integration attempt $AttemptId was reconciled without downstream authority"
        $severity = if ($EvidenceIsFresh) { "WARN" } else { "NONE" }
    }
    elseif ($State -eq "FAILED_NEEDS_CLOSE") {
        $detail = "integration attempt $AttemptId failed and must close its exact tasks (task state $TaskState)"
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "CLOSED_NEEDS_DISPATCH") {
        $detail = "integration attempt $AttemptId is closed and needs reviewed recovery dispatch"
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "RECOVERY_READY") {
        $detail = "integration attempt $AttemptId recovery is ready for an active agent: $RecoveryDispatch"
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "SUCCESSOR_CLAIMED" -and $EvidenceIsFresh) {
        $detail = "integration attempt $AttemptId authorized successor $SuccessorAttemptId"
        $severity = "WARN"
    }
    elseif ($State -eq "ACTIVE_OR_ARMED" -and
        ($SuiteRanWithoutReceipt -or $MergeReceiptMissingAfterTrigger)) {
        if ($SuiteRanWithoutReceipt -and $MergeReceiptMissingAfterTrigger) {
            $detail = "integration attempt $AttemptId ran its suite without a receipt and its merge trigger passed; close it"
        }
        elseif ($SuiteRanWithoutReceipt) {
            $detail = "integration attempt $AttemptId ran its suite but produced no receipt; close it"
        }
        else {
            $detail = "integration attempt $AttemptId passed its merge trigger without a receipt; close it"
        }
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    elseif ($State -eq "ACTIVE_OR_ARMED" -and $SuiteTriggerMissed) {
        $detail = "integration attempt $AttemptId missed its suite trigger and has no receipt"
        $severity = if ($EvidenceIsFresh) { "FLAG" } else { "WARN" }
    }
    return [pscustomobject]@{ Severity = $severity; Detail = $detail }
}

function Get-WeatherIntegrationSuiteRuntimeState {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][datetime]$SuiteAt,
        [Parameter(Mandatory = $true)][string]$PreflightLogPath
    )

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    $taskInfo = if ($null -eq $task) {
        $null
    }
    else {
        Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
    }
    $lastRunTimeProperty = if ($null -eq $taskInfo) {
        $null
    }
    else {
        $taskInfo.PSObject.Properties["LastRunTime"]
    }
    $lastRunTime = if ($null -eq $lastRunTimeProperty -or $null -eq $lastRunTimeProperty.Value) {
        $null
    }
    else {
        [datetime]$lastRunTimeProperty.Value
    }
    $preflightExists = Test-Path -LiteralPath $PreflightLogPath -PathType Leaf
    $running = ($null -ne $task -and [string]$task.State -eq "Running")
    $ran = (
        $preflightExists -or
        ($null -ne $lastRunTime -and $lastRunTime -ge $SuiteAt.AddMinutes(-5))
    )
    return [pscustomobject]@{
        TaskState = if ($null -eq $task) { "Missing" } else { [string]$task.State }
        LastRunTime = $lastRunTime
        PreflightExists = [bool]$preflightExists
        Running = [bool]$running
        Ran = [bool]$ran
        Started = [bool]($running -or $ran)
    }
}

function Test-WeatherIntegrationSuiteTriggerMissed {
    param(
        [Parameter(Mandatory = $true)][datetime]$SuiteAt,
        [Parameter(Mandatory = $true)][datetime]$Now,
        [Parameter(Mandatory = $true)][bool]$SuiteStarted,
        [AllowEmptyString()][string]$SuiteReceiptStatus = "",
        [AllowEmptyString()][string]$ClosureStatus = ""
    )

    return (
        $Now -ge $SuiteAt.AddMinutes(5) -and
        -not $SuiteStarted -and
        [string]::IsNullOrWhiteSpace($SuiteReceiptStatus) -and
        [string]::IsNullOrWhiteSpace($ClosureStatus)
    )
}

function Get-WeatherIntegrationSuiteObservation {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptManifest,
        [Parameter(Mandatory = $true)][datetime]$Now,
        [AllowEmptyString()][string]$SuiteReceiptStatus = "",
        [AllowEmptyString()][string]$ClosureStatus = ""
    )

    $suiteAt = $null
    try { $suiteAt = [datetime]::Parse([string]$AttemptManifest.schedule.suite_at_local) } catch { }
    if ($null -eq $suiteAt) {
        return [pscustomobject]@{
            SuiteAt = $null
            TaskState = "Unreadable"
            LastRunTime = $null
            PreflightExists = $false
            Running = $false
            Ran = $false
            Started = $false
            TriggerMissed = $false
            RanWithoutReceipt = $false
            ReceiptStatus = [string]$SuiteReceiptStatus
            ReceiptUnreadable = $false
        }
    }
    $runtime = Get-WeatherIntegrationSuiteRuntimeState `
        -TaskName ([string]$AttemptManifest.schedule.suite_task_name) `
        -SuiteAt $suiteAt `
        -PreflightLogPath ([string]$AttemptManifest.evidence.preflight_log)
    # The caller reads receipts before sampling the task. If the suite publishes
    # its receipt and exits between those two reads, the earlier empty status must
    # not turn the now-terminal healthy run into a false interrupted-suite alert.
    # Re-read a newly appeared receipt so FAIL is not hidden for this scan and
    # malformed evidence remains actionable instead of being treated as present.
    $suiteReceiptPath = ""
    $evidenceProperty = $AttemptManifest.PSObject.Properties["evidence"]
    if ($null -ne $evidenceProperty -and $null -ne $evidenceProperty.Value) {
        $suiteReceiptProperty = $evidenceProperty.Value.PSObject.Properties["suite_receipt"]
        if ($null -ne $suiteReceiptProperty -and $null -ne $suiteReceiptProperty.Value) {
            $suiteReceiptPath = [string]$suiteReceiptProperty.Value
        }
    }
    $effectiveSuiteReceiptStatus = [string]$SuiteReceiptStatus
    $suiteReceiptUnreadable = $false
    if ([string]::IsNullOrWhiteSpace($effectiveSuiteReceiptStatus) -and
        -not [string]::IsNullOrWhiteSpace($suiteReceiptPath) -and
        (Test-Path -LiteralPath $suiteReceiptPath -PathType Leaf)) {
        try {
            $freshSuiteReceipt = Get-Content -LiteralPath $suiteReceiptPath -Raw | ConvertFrom-Json
            $effectiveSuiteReceiptStatus = [string]$freshSuiteReceipt.status
            if ([string]::IsNullOrWhiteSpace($effectiveSuiteReceiptStatus)) {
                $suiteReceiptUnreadable = $true
            }
        }
        catch { $suiteReceiptUnreadable = $true }
    }
    $suiteReceiptExists = -not [string]::IsNullOrWhiteSpace($effectiveSuiteReceiptStatus)
    $triggerMissed = Test-WeatherIntegrationSuiteTriggerMissed `
        -SuiteAt $suiteAt `
        -Now $Now `
        -SuiteStarted ([bool]$runtime.Started) `
        -SuiteReceiptStatus $effectiveSuiteReceiptStatus `
        -ClosureStatus $ClosureStatus
    $ranWithoutReceipt = (
        [bool]$runtime.Ran -and
        -not [bool]$runtime.Running -and
        -not $suiteReceiptExists -and
        [string]::IsNullOrWhiteSpace($ClosureStatus)
    )
    return [pscustomobject]@{
        SuiteAt = $suiteAt
        TaskState = [string]$runtime.TaskState
        LastRunTime = $runtime.LastRunTime
        PreflightExists = [bool]$runtime.PreflightExists
        Running = [bool]$runtime.Running
        Ran = [bool]$runtime.Ran
        Started = [bool]$runtime.Started
        TriggerMissed = [bool]$triggerMissed
        RanWithoutReceipt = [bool]$ranWithoutReceipt
        ReceiptStatus = $effectiveSuiteReceiptStatus
        ReceiptUnreadable = [bool]$suiteReceiptUnreadable
    }
}

function Get-WeatherIntegrationMergeObservation {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptManifest,
        [Parameter(Mandatory = $true)][string]$TaskState,
        [Parameter(Mandatory = $true)][datetime]$Now,
        [AllowEmptyString()][string]$MergeReceiptStatus = "",
        [AllowEmptyString()][string]$ClosureStatus = ""
    )

    $mergeAt = $null
    try { $mergeAt = [datetime]::Parse([string]$AttemptManifest.schedule.merge_at_local) } catch { }
    if ($null -eq $mergeAt) {
        return [pscustomobject]@{
            MergeAt = $null
            Running = ($TaskState -eq "Running")
            ReceiptMissingAfterTrigger = $false
        }
    }
    $running = ($TaskState -eq "Running")
    $receiptMissingAfterTrigger = (
        $Now -ge $mergeAt.AddMinutes(5) -and
        -not $running -and
        [string]::IsNullOrWhiteSpace($MergeReceiptStatus) -and
        [string]::IsNullOrWhiteSpace($ClosureStatus)
    )
    return [pscustomobject]@{
        MergeAt = $mergeAt
        Running = [bool]$running
        ReceiptMissingAfterTrigger = [bool]$receiptMissingAfterTrigger
    }
}

# ---- streak (delegate to the authoritative ledger-based checker) ----
$streak = $null
try { $streak = & $py (Join-Path $repo "scripts\ops\streak_status.py") --json | ConvertFrom-Json } catch {}
if ($null -eq $streak) { $flags.Add("streak checker failed to run") }
$today = $streak.today_health
if ($today -and $today.verdict -eq "AT_RISK") { $flags.Add("TODAY capture AT_RISK: $($today.reason)") }

# ---- capture workers + priority (persistent loop must be alive & AboveNormal) ----
# Match the FULL module path (as capture_priority_guard.ps1 does), NOT the short name,
# and SKIP the short-lived per-cycle "hot capture" subprocesses the loop spawns to do
# the actual fetch. Those children run at Normal for a few seconds by design (I/O-bound,
# transient) and the 5-min guard rarely coincides with them; counting them would falsely
# report "not all AboveNormal" every capture cycle. The persistent loop is what matters.
$caps = [ordered]@{
    "snapshot_tracker"      = "weather.collection.snapshot_tracker"
    "market_microstructure" = "weather.market.market_microstructure"
    "observation_trigger"   = "weather.operations.observation_trigger"
}
$transientMarks = @("--expected-runtime-fingerprint", "hot_capture", "result.json")
$capState = @{}
foreach ($c in $caps.Keys) { $capState[$c] = @() }
Get-CimInstance Win32_Process | Where-Object { $_.Name -in @("python.exe", "pythonw.exe") } | ForEach-Object {
    $cl = [string]$_.CommandLine
    $skip = $false
    foreach ($tm in $transientMarks) { if ($cl -like "*$tm*") { $skip = $true; break } }
    if ($skip) { return }   # per-cycle capture child, not the persistent loop
    foreach ($label in $caps.Keys) {
        if ($cl -like "*$($caps[$label])*") {
            $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
            if ($p) { $capState[$label] += [string]$p.PriorityClass }
            break
        }
    }
}
# S4U-owned process command lines are hidden from an ordinary interactive WMI
# query on this host.  An empty command-line match is therefore UNKNOWN, not
# DOWN.  Fall back to the capture workers' portable single-writer contract:
# fresh heartbeat + live PID + a writer lock owned by that same PID.  This is
# the same evidence the resource gate uses and still fails closed if any part
# is absent, stale, unreadable, or mismatched.
$portableCaps = [ordered]@{
    # Snapshot intentionally sleeps for nearly ten minutes between cycles. Keep this
    # aligned with capture_recovery_check and the bounded-suite admission contract: 12
    # minutes tolerates a complete normal cycle while remaining below the 15-minute streak
    # gap limit. CLOB and observation retain their three-minute contracts.
    "snapshot_tracker"      = @{ Status = "loop_status.json"; Lock = ".loop_status.json.writer.lock"; MaxAge = 720.0 }
    "market_microstructure" = @{ Status = "clob_loop_status.json"; Lock = ".clob_loop_status.json.writer.lock"; MaxAge = 180.0 }
    "observation_trigger"   = @{ Status = "observation_trigger_status.json"; Lock = ".observation_trigger_status.json.writer.lock"; MaxAge = 180.0 }
}
$captureRoot = Join-Path $repo "data\snapshots"
foreach ($label in $portableCaps.Keys) {
    if ($capState[$label].Count -gt 0) { continue }
    $spec = $portableCaps[$label]
    try {
        $status = Get-Content -LiteralPath (Join-Path $captureRoot $spec.Status) -Raw | ConvertFrom-Json
        $lock = Get-Content -LiteralPath (Join-Path $captureRoot $spec.Lock) -Raw | ConvertFrom-Json
        $pidValue = [int]$status.pid
        $ageSeconds = ((Get-Date) - [datetime]$status.last_heartbeat).TotalSeconds
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($pidValue -gt 0 -and [int]$lock.pid -eq $pidValue -and $process -and
            $ageSeconds -ge 0 -and $ageSeconds -le [double]$spec.MaxAge) {
            $priority = [string]$process.PriorityClass
            # PriorityClass can be hidden with the command line under S4U.
            # The separately scheduled priority guard owns re-assertion; this
            # fallback proves liveness rather than inventing a priority value.
            if (-not $priority) { $priority = "PortableHealthy" }
            $capState[$label] += $priority
        }
    }
    catch { }
}
$captureRuntimeState = [ordered]@{}
foreach ($label in $portableCaps.Keys) {
    $runtimeState = [ordered]@{
        status_path = [string]$portableCaps[$label].Status
        parsed = $false
        consecutive_errors = $null
        last_error_present = $null
        last_clean_iteration = $null
        last_clean_age_seconds = $null
    }
    try {
        $runtimeStatus = Get-Content -LiteralPath (
            Join-Path $captureRoot $portableCaps[$label].Status
        ) -Raw | ConvertFrom-Json
        $runtimeState.parsed = $true
        $errorsProperty = $runtimeStatus.PSObject.Properties["consecutive_errors"]
        if ($null -ne $errorsProperty -and $null -ne $errorsProperty.Value) {
            $runtimeState.consecutive_errors = [int]$errorsProperty.Value
        }
        $errorProperty = $runtimeStatus.PSObject.Properties["last_error"]
        if ($null -ne $errorProperty) {
            $runtimeState.last_error_present = -not [string]::IsNullOrWhiteSpace(
                [string]$errorProperty.Value
            )
        }
        $cleanIterationProperty = $runtimeStatus.PSObject.Properties["last_clean_iteration"]
        if ($null -ne $cleanIterationProperty) {
            $runtimeState.last_clean_iteration = $cleanIterationProperty.Value
        }
        $cleanAtProperty = $runtimeStatus.PSObject.Properties["last_clean_iteration_at"]
        if ($null -ne $cleanAtProperty -and $cleanAtProperty.Value) {
            try {
                $runtimeState.last_clean_age_seconds = [math]::Round(
                    ((Get-Date) - [datetime]$cleanAtProperty.Value).TotalSeconds,
                    1
                )
            }
            catch { }
        }
        if ($null -ne $runtimeState.consecutive_errors) {
            if ([int]$runtimeState.consecutive_errors -ge 3) {
                $flags.Add(
                    "capture loop ERRORING: $label has $($runtimeState.consecutive_errors) consecutive errors"
                )
            }
            elseif ([int]$runtimeState.consecutive_errors -gt 0) {
                $warns.Add(
                    "$label has $($runtimeState.consecutive_errors) consecutive capture error(s); " +
                    "process/heartbeat liveness alone is not a clean iteration"
                )
            }
        }
    }
    catch {
        # Optional runtime-health fields supplement, rather than replace, the
        # process/lock/heartbeat liveness contract above. Sparse schemas are
        # valid; an unreadable file remains visible without inventing failure.
        $warns.Add("$label runtime error state could not be read")
    }
    $captureRuntimeState[$label] = [PSCustomObject]$runtimeState
}
foreach ($c in $caps.Keys) {
    if ($capState[$c].Count -eq 0) {
        $flags.Add("capture loop DOWN: $c")   # a dead capture loop is streak-critical
    }
    else {
        $low = @($capState[$c] | Where-Object { $_ -notin @("AboveNormal", "High", "RealTime", "PortableHealthy") })
        if ($low.Count -gt 0) {
            $warns.Add("$c not all AboveNormal ($($capState[$c] -join ',')) - guard re-asserts within 5 min")
        }
    }
}

# ---- auxiliary public execution tape (economics evidence, not streak grading) ----
# This producer is optional until its task is explicitly registered. Once
# armed, status/lock/PID/supervisor identity must agree just like the core
# loops. Its failure loses irreplaceable forward market-path evidence, but it
# does not relabel the three-worker weather-capture streak.
$executionTapeState = [ordered]@{
    armed = $false; task_state = $null; process_healthy = $null
    capture_state = $null; evidence_integrity = $null; price_path_usable = $null
    heartbeat_age_seconds = $null; pid = $null
}
$executionTapeTask = Get-ScheduledTask -TaskName "WeatherExecutionTapeSupervisor" -ErrorAction SilentlyContinue
if ($executionTapeTask) {
    $executionTapeState.armed = [string]$executionTapeTask.State -ne "Disabled"
    $executionTapeState.task_state = [string]$executionTapeTask.State
}
if ($executionTapeState.armed) {
    try {
        $executionStatus = Get-Content -LiteralPath (Join-Path $captureRoot "execution_tape_status.json") -Raw | ConvertFrom-Json
        $executionLock = Get-Content -LiteralPath (Join-Path $captureRoot ".execution_tape_status.json.writer.lock") -Raw | ConvertFrom-Json
        $executionSupervisor = Get-Content -LiteralPath (Join-Path $captureRoot "execution_tape_supervisor_status.json") -Raw | ConvertFrom-Json
        $executionPid = [int]$executionStatus.pid
        $executionProcess = Get-Process -Id $executionPid -ErrorAction SilentlyContinue
        $executionAge = ((Get-Date) - [datetime]$executionStatus.last_heartbeat).TotalSeconds
        $executionTapeState.pid = $executionPid
        $executionTapeState.heartbeat_age_seconds = [math]::Round($executionAge, 1)
        $executionTapeState.capture_state = [string]$executionStatus.state
        $executionTapeState.evidence_integrity = [string]$executionStatus.evidence_integrity
        $executionTapeState.price_path_usable = [bool]$executionStatus.price_path_evidence_usable
        $executionTapeState.process_healthy = [bool](
            $executionPid -gt 0 -and [int]$executionLock.pid -eq $executionPid -and
            $executionProcess -and $executionAge -ge 0 -and $executionAge -le 180 -and
            [string]$executionSupervisor.ensure_status -eq "OK" -and
            [bool]$executionSupervisor.runtime_identity_matches_current
        )
        if (-not $executionTapeState.process_healthy) {
            $flags.Add("public execution-tape producer is armed but its process/lock/identity contract is unhealthy")
        }
        elseif ($executionTapeState.evidence_integrity -eq "BLOCKED_EVIDENCE_LOSS") {
            $flags.Add("public execution-tape evidence integrity is BLOCKED_EVIDENCE_LOSS")
        }
        elseif (-not $executionTapeState.price_path_usable) {
            $warns.Add("public execution-tape producer is alive but complete price-path evidence is not currently usable ($($executionTapeState.capture_state))")
        }
    }
    catch {
        $executionTapeState.process_healthy = $false
        $flags.Add("public execution-tape producer is armed but its status contract is unreadable")
    }
}

# ---- resources ----
$os = Get-CimInstance Win32_OperatingSystem
$freeRamGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2)
$totRamGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2)
$freeDiskGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($freeRamGB -lt 1.5) { $flags.Add("LOW RAM: $freeRamGB GB free (streak-critical)") }
elseif ($freeRamGB -lt 2.5) { $warns.Add("RAM tightening: $freeRamGB GB free") }
if ($freeDiskGB -lt 25) { $flags.Add("LOW DISK: $freeDiskGB GB free") }
elseif ($freeDiskGB -lt 60) { $warns.Add("disk headroom low: $freeDiskGB GB free") }

# Resource headroom alone does not reveal an overlapping heavyweight job. The shared
# file-handle lease is authoritative; stale owner JSON without a live handle is not active.
$heavyWorkload = $null
try {
    . (Join-Path $repo "scripts\ops\workload_admission.ps1")
    $heavyWorkload = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $repo
    if ($heavyWorkload.Active) {
        $ownerName = [string]$heavyWorkload.Owner.workload
        $ownerPid = [int]$heavyWorkload.Owner.pid
        $warns.Add("heavy workload lease active: $ownerName (pid $ownerPid)")
    }
}
catch { $flags.Add("heavy-workload lease state could not be read") }

# Free space is a point-in-time number and tells me nothing about how long I have. The
# tape/CLOB history means "195 GB free" can be comfortable or two weeks from an outage
# depending on the slope, so keep a cheap sample trail and report the 24h burn. Sampling
# Get-PSDrive costs nothing -- deliberately NOT a recursive size walk of data\, which has
# starved capture before (see the codex-scan hazard) and must never run from a monitor.
$diskDelta = $null
$diskDaysLeft = $null
$diskDelta48 = $null
$diskDaysLeft48 = $null
try {
    $trail = Join-Path $repo "data\alerts\disk_free_trail.jsonl"
    $old = @()
    if (Test-Path $trail) { $old = @(Get-Content $trail -Tail 400 | Where-Object { $_ }) }
    $cut = (Get-Date).AddHours(-24)
    $cut48 = (Get-Date).AddHours(-48)
    $ref = $null
    $ref48 = $null
    foreach ($line in $old) {
        try {
            $s = $line | ConvertFrom-Json
            if ([datetime]$s.ts -le $cut) { $ref = $s }   # newest sample at least 24h old
            if ([datetime]$s.ts -le $cut48) { $ref48 = $s }
        }
        catch {}
    }
    if ($ref) {
        $hrs = ((Get-Date) - [datetime]$ref.ts).TotalHours
        if ($hrs -gt 0) {
            $diskDelta = [math]::Round((($freeDiskGB - $ref.free_gb) / $hrs) * 24, 1)   # GB/day, negative = filling
            if ($diskDelta -lt 0) { $diskDaysLeft = [math]::Round($freeDiskGB / [math]::Abs($diskDelta), 0) }
        }
    }
    if ($ref48) {
        $hrs48 = ((Get-Date) - [datetime]$ref48.ts).TotalHours
        if ($hrs48 -gt 0) {
            $diskDelta48 = [math]::Round((($freeDiskGB - $ref48.free_gb) / $hrs48) * 24, 1)
            if ($diskDelta48 -lt 0) {
                $diskDaysLeft48 = [math]::Round(
                    $freeDiskGB / [math]::Abs($diskDelta48), 0
                )
            }
        }
    }
    $new = @($old) + @(([ordered]@{ ts = (Get-Date).ToString("o"); free_gb = $freeDiskGB } | ConvertTo-Json -Compress))
    Set-Content -Path $trail -Value ($new | Select-Object -Last 400) -Encoding utf8
}
catch {}
if ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 21) {
    if ($null -ne $diskDaysLeft48 -and $diskDaysLeft48 -ge 21) {
        $warns.Add(
            "disk 24h burst is $([math]::Abs($diskDelta)) GB/day (~$diskDaysLeft d), " +
            "but the 48h net is $([math]::Abs($diskDelta48)) GB/day (~$diskDaysLeft48 d); " +
            "keep tiering armed and treat the short window as a burst"
        )
    }
    else {
        $flags.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days of headroom left")
    }
}
elseif ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 60) {
    $warns.Add("disk filling at $([math]::Abs($diskDelta)) GB/day - about $diskDaysLeft days left")
}

# Scheduler 0x0 is not proof that either tiering job reclaimed anything. Both wrappers
# deliberately exit zero when the shared workload lease is busy. Surface their durable
# status beside the disk slope so a skipped recovery cannot masquerade as a clean run.
$tieringState = [ordered]@{}
$tieringSkippedToday = New-Object System.Collections.Generic.List[string]
foreach ($spec in @(
    @{ Name = "clob_projection"; Path = "data\logs\clob_tiering_task_status.json" },
    @{ Name = "clob_raw_tape"; Path = "data\logs\clob_raw_tape_tiering_task_status.json" }
)) {
    $path = Join-Path $repo $spec.Path
    $row = $null
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        try { $row = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch {}
    }
    $tieringState[$spec.Name] = $row
    if ($null -eq $row -or [string]$row.status -ne "SKIPPED_WORKLOAD_LEASE_BUSY") { continue }
    try { $localTime = [datetime]$row.local_time } catch { continue }
    if ($localTime.Date -eq (Get-Date).Date) { $tieringSkippedToday.Add([string]$spec.Name) }
}
if ($tieringSkippedToday.Count -gt 0) {
    $tieringMessage = (
        "disk tiering skipped today because the heavy-workload lease was busy: {0}; " +
        "Task Scheduler 0x0 does not prove reclaim" -f ($tieringSkippedToday -join ", ")
    )
    if ($null -ne $diskDaysLeft -and $diskDaysLeft -lt 21) { $flags.Add($tieringMessage) }
    else { $warns.Add($tieringMessage) }
}

# ---- system clock ----
# CLOB heartbeats, order TTLs, evidence ordering, and scheduled one-shots all trust the
# Windows clock. W32Time is trigger-start on this workgroup host, so a stopped service is
# not itself a failure. Use the bounded Time-Service event stream as a fallback, but
# prefer the live w32tm last-success timestamp when the service is already running.
# The event stream can lag a successful resync by more than a day on this host.
$clockService = $null
$clockLastSync = $null
$clockSyncAgeH = $null
$clockSource = $null
$clockSynchronized = $null
try { $clockService = Get-Service -Name W32Time -ErrorAction Stop }
catch { }
# Get-WinEvent throws when the bounded window contains no matching event. Keep
# that fallback independent from the live query: absence of an event must not
# skip w32tm on a currently running, synchronized service.
try {
    $syncEvent = Get-WinEvent -FilterHashtable @{
        LogName = "System"
        ProviderName = "Microsoft-Windows-Time-Service"
        Id = 35, 37
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 1 -ErrorAction Stop
    if ($syncEvent) {
        $clockLastSync = [datetime]$syncEvent.TimeCreated
        $clockSyncAgeH = [math]::Round(((Get-Date) - $clockLastSync).TotalHours, 1)
    }
}
catch { }
if ($clockService -and $clockService.Status -eq "Running") {
    try {
        $clockStatusText = ((& w32tm.exe /query /status 2>&1) -join "`n")
        $clockQueryExit = $LASTEXITCODE
        $sourceMatch = [regex]::Match($clockStatusText, "(?m)^Source:\s*(.+?)\s*$")
        $liveSyncMatch = [regex]::Match(
            $clockStatusText,
            "(?m)^Last Successful Sync Time:\s*(.+?)\s*$"
        )
        if ($sourceMatch.Success) { $clockSource = $sourceMatch.Groups[1].Value.Trim() }
        if ($clockQueryExit -ne 0 -or -not $sourceMatch.Success) {
            $clockSynchronized = $false
            $clockSource = "unavailable"
        }
        else {
            $clockSynchronized = -not (
                $clockStatusText -match "Leap Indicator:\s*3" -or
                $clockStatusText -match "Source:\s*Local CMOS Clock"
            )
            $liveSync = [datetime]::MinValue
            if ($liveSyncMatch.Success -and
                [datetime]::TryParse($liveSyncMatch.Groups[1].Value.Trim(), [ref]$liveSync)) {
                $clockLastSync = $liveSync
                $clockSyncAgeH = [math]::Round(((Get-Date) - $clockLastSync).TotalHours, 1)
            }
        }
    }
    catch {
        $clockSynchronized = $false
        $clockSource = "unavailable"
    }
}
if ($clockSynchronized -eq $false) {
    $flags.Add("system clock is not synchronized (source $clockSource)")
}
elseif ($null -eq $clockLastSync) {
    $flags.Add("system clock has no successful Windows Time event in 7 days")
}
elseif ($clockSyncAgeH -gt 24) {
    $flags.Add("system clock last received valid time $clockSyncAgeH hours ago")
}
elseif ($clockSyncAgeH -gt 12) {
    $warns.Add("system clock last received valid time $clockSyncAgeH hours ago")
}

# ---- daily chain ----
$chain = $null
$cf = Join-Path $repo "data\backtest\daily_refresh_status.json"
if (Test-Path $cf) { try { $chain = Get-Content $cf -Raw | ConvertFrom-Json } catch {} }
$chainStatus = if ($chain) { [string]$chain.status } else { "?" }
$chainTerm = if ($chain -and $chain.terminal) { "terminal" } else { "running/unknown" }
$chainTaskResult = $null
try {
    $chainTaskInfo = Get-ScheduledTaskInfo -TaskName "WeatherDailySettlementPromotionRefresh"
    $chainTaskResult = "0x{0:X}" -f $chainTaskInfo.LastTaskResult
} catch {}
# A `critical` run with every step OK is NOT a broken chain: it is the production-readiness
# gate correctly reporting that no release pointer exists yet, which is the standing
# pre-release state (2026-07-26: 24/24 steps ok, SLA pass, 69 blockers led by
# active_release_verification_failed). Reporting that as breakage is the same false-positive
# trap as the old 0x2 exit code, so name what it actually means.
$chainGate = $null
$chainProductionReadiness = $null
if ($chain) {
    # status.ps1 is invoked from strict-mode operational wrappers as well as directly.
    # production_readiness is optional on interrupted/pre-gate chain receipts; direct
    # member access turns that valid absence into a terminating PropertyNotFoundException
    # under the caller's inherited strict mode.
    $productionReadinessProperty = $chain.PSObject.Properties["production_readiness"]
    if ($null -ne $productionReadinessProperty) {
        $chainProductionReadiness = $productionReadinessProperty.Value
    }
}
if ($chainProductionReadiness) {
    $pr = $chainProductionReadiness
    if ([string]$pr.status -eq "SKIPPED") {
        # A SKIPPED readiness gate carries `reason` + `pipeline_status`, NOT stage/
        # blocker_count/first_blocker. The generic format below therefore rendered it as
        # "readiness SKIPPED/, 0 blockers -> " -- three empty fields and a zero, which reads
        # as benign. It is the opposite: SKIPPED means the gate never ran at all because the
        # pipeline upstream of it did not succeed. Name that reason. (2026-08-03.)
        $chainGate = "readiness SKIPPED - {0} (pipeline {1})" -f [string]$pr.reason, [string]$pr.pipeline_status
    }
    else {
        $chainGate = "readiness {0}/{1}, {2} blockers -> {3}" -f [string]$pr.status, [string]$pr.stage,
        [int]$pr.blocker_count, [string]$pr.first_blocker.code
    }
}
# Every step can be `ok` while the run still did not succeed. A step's STEP status only says
# it EXECUTED; its PAYLOAD carries the verdict, and the two disagree routinely. On 2026-08-03
# all 23 steps were `ok` and the chain still terminated `deferred /
# upstream_pipeline_not_successful`, because live_variant_settlement_scorecard,
# hourly_model_performance, ten_minute_model_performance, rollup_freshness and
# trading_evidence were each BLOCK inside $chain.summary. Reading step status alone says
# "the chain is healthy" and is wrong -- surface the payload verdicts too.
$chainBlocked = $null
$chainSummary = $null
if ($chain) {
    $summaryProperty = $chain.PSObject.Properties["summary"]
    if ($null -ne $summaryProperty) { $chainSummary = $summaryProperty.Value }
}
if ($chainSummary) {
    $blocked = @($chainSummary.PSObject.Properties |
        Where-Object {
            $value = $_.Value
            if ($null -eq $value) { return $false }
            $statusProperty = $value.PSObject.Properties["status"]
            return $null -ne $statusProperty -and [string]$statusProperty.Value -eq "BLOCK"
        } |
        ForEach-Object { $_.Name })
    if ($blocked.Count -gt 0) { $chainBlocked = "{0} step(s) BLOCK in payload: {1}" -f $blocked.Count, ($blocked -join ", ") }
}
# Name the failing STEP and its reason. A bare "error" costs a manual dig through
# daily_refresh_status.json every single time, which is exactly what this script exists
# to avoid (2026-07-24: "error" was maker_paper_input_budget_exceeded, 20 min to find).
$chainFail = $null
if ($chain -and $chain.steps) {
    $bad = @($chain.steps | Where-Object { $_.status -and $_.status -notin @("ok", "skipped") })
    if ($bad.Count -gt 0) {
        $f = $bad[0]
        $fResult = $null
        $resultProperty = $f.PSObject.Properties["result"]
        if ($null -ne $resultProperty) { $fResult = $resultProperty.Value }
        $reasonProperty = if ($null -ne $fResult) { $fResult.PSObject.Properties["reason"] } else { $null }
        $errorProperty = $f.PSObject.Properties["error"]
        $resultStatusProperty = if ($null -ne $fResult) { $fResult.PSObject.Properties["status"] } else { $null }
        $stepStatusProperty = $f.PSObject.Properties["status"]
        $why = if ($null -ne $reasonProperty) { [string]$reasonProperty.Value } else { "" }
        if (-not $why -and $null -ne $errorProperty) { $why = [string]$errorProperty.Value }
        if (-not $why -and $null -ne $resultStatusProperty) { $why = [string]$resultStatusProperty.Value }
        if (-not $why -and $null -ne $stepStatusProperty) { $why = [string]$stepStatusProperty.Value }
        # A deferral is the resource gates working as designed (heavy steps refusing to run
        # beside live capture), not a fault. Say so, or every quiet-window-bound run looks broken.
        # WHEN it failed matters as much as what failed: a step that broke this morning and
        # was fixed this afternoon still sits in this file until the next run, so an ageless
        # "FAILING" reads as live breakage (2026-07-25: the MemoryError shown here predated
        # its own budget fix by 4.5h). Always say how old the failure is.
        $failAge = ""
        $stepFin = $null
        try {
            if ($f.finished_at_utc) {
                $stepFin = ([datetime]$f.finished_at_utc).ToLocalTime()
                $failAge = " [{0:HH:mm}, {1:N1}h ago]" -f $stepFin, ((Get-Date) - $stepFin).TotalHours
            }
        }
        catch {}
        if ([string]$f.status -eq "deferred") {
            $chainFail = "deferred at {0} ({1}) - heavy steps wait for a quieter host" -f $f.name, $why
        }
        else {
            $chainFail = "FAILING {0}{1} -> {2}" -f $f.name, $failAge, $why
            $warns.Add("chain step $chainFail")
        }
    }
}
# `terminal` describes the LAST completed run and goes stale the moment a resume starts,
# so trust the live step state instead: a running step means a run is in flight now.
if ($chain -and $chain.current_step -and [string]$chain.current_step.status -like "running*") {
    $chainTerm = "RUNNING NOW: $($chain.current_step.name)"
    $chainFail = $null
}
elseif ($chain -and -not $chain.terminal) {
    $chainTerm = "running/unknown"
}

# ---- settlement holes (the CONSEQUENCE, not the event) ----
# Everything above watches the chain as an event: which step failed, what the task
# returned. None of it watches the thing that actually costs us anything -- whether a
# target date ended up settled. Those are different questions, and on 2026-08-06 they
# gave different answers: the failing step was a MEDIUM standing note while 2026-08-05
# went unsettled in all 12 markets and nothing said so.
#
# The event is also transient and the hole is not. Each chain run settles only
# yesterday, so a missed day is never retried by the next run -- it needs an explicit
# backfill (scripts\ops\chain_recovery_run.ps1). A hole therefore compounds silently
# while the daily "chain ok" signal returns to normal the very next morning.
#
# Read the tail rather than the whole ledger: toronto's is large and this script runs
# every 15 minutes beside live capture. Revisions append, so scan a window and take the
# max rather than trusting the final line.
$settleHole = $null
$settleRoot = Join-Path $repo "data\settlements"
if (Test-Path $settleRoot) {
    # 2026-08-10: this was a MAX-DATE check that read only `target_date`, and it went blind.
    # The 08-05 backfill appended records for 08-06/08-08/08-09 that settled NOTHING
    # (settlement_source "none", missing_settlement, null high). Those satisfied a
    # target_date-only test, so every market's max became 08-09 and the flag could not fire
    # while three dates sat empty. Two defects, both fixed here:
    #   1. A record only counts as SETTLED if it actually settled - source and high present.
    #   2. Max-date can never see an INTERIOR hole (08-06 empty while 08-07 settled), so
    #      scan the whole recent window per date instead of tracking a maximum.
    # PowerShell 5.1 Get-Content -Tail rescans each ledger from byte zero and ConvertFrom-
    # Json is disproportionately slow on these large records. One Python process seeks
    # backward and parses only the requested suffix for every market.
    $windowDays = 14
    $settlementCheck = $null
    try {
        $settlementRaw = @(& $py -m weather.operations.settlement_hole_check `
            --repo-root $repo --window-days $windowDays --tail-lines 400 --json)
        if ($LASTEXITCODE -eq 0) {
            $settlementCheck = (($settlementRaw -join "`n") | ConvertFrom-Json)
        }
    }
    catch {}
    if ($null -eq $settlementCheck) {
        $flags.Add("settlement-hole checker failed to run")
    }
    elseif (-not $settlementCheck.ok) {
        $flags.Add("settlement-hole checker could not read every ledger: $(@($settlementCheck.errors) -join ', ')")
    }
    elseif (@($settlementCheck.holes).Count -gt 0) {
        $holes = @($settlementCheck.holes)
        $worst = $holes[0].date
        $dates = ($holes | ForEach-Object { $_.date }) -join ", "
        $settleHole = "SETTLEMENT HOLE: {0} date(s) unsettled in the last {1} days [{2}] - worst {3}, up to {4} of {5} market(s) - each needs an EXPLICIT per-date backfill; the next chain run will not retry it" -f `
            $holes.Count, $windowDays, $dates, $worst, ($holes | Measure-Object -Property markets -Maximum).Maximum, $settlementCheck.market_count
        $flags.Add($settleHole)
    }
}

# ---- git / push ----
# Publication guidance is action-bearing.  Inspect the reconciliation marker and
# last report before offering the ordinary push command so a spent incident-bound
# invocation can never be presented as a harmless retry.  Missing operation_mode is
# valid for historical ordinary quiet-merge evidence; malformed or unknown evidence
# is not sufficient authority to recommend a credential-bearing push.
function Get-WeatherReconciliationPublicationState {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ActiveMarkerPath,
        [Parameter(Mandatory = $true)][string]$CanonicalOrigin,
        [datetimeoffset]$Now = [datetimeoffset]::Now
    )

    # This is a one-incident consumer, not a generic marker trust mechanism.
    # L and T are immutable anchors; S, C, and M are accepted only after Git,
    # the active marker, the raw snapshot, and the two live config files agree.
    $localBaseline = "3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac"
    $publishedTarget = "c932b54f8747df5cdefc4cc42f8454b6797f09ae"
    $reviewedParent = "a24cf0f41bf0b321c5c813820594c56198a58d1a"
    $configPaths = @(
        "config/locations.json",
        "config/location_market_events.json"
    )
    $safetyDependencyPaths = @(
        "scripts/ops/quiet_window_merge.ps1",
        "scripts/ops/production_baseline_scheduler_rpc.ps1",
        "scripts/ops/windows_kill_on_close_job.ps1",
        "scripts/ops/status.ps1",
        "scripts/ops/health_watchdog.ps1"
    )
    $localBaselineDependencySha256 = [ordered]@{
        "scripts/ops/boot_recovery.ps1" = "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
        "scripts/ops/roll_verdict.ps1" = "3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881"
        "scripts/ops/workload_admission.ps1" = "cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105"
        "src/weather/operations/capture_recovery_check.py" = "814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895"
        "src/weather/operations/documentation_transaction.py" = "057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9"
        "src/weather/operations/execution_tape_supervisor.py" = "1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f"
    }
    $publishedTargetDependencySha256 = [ordered]@{
        "scripts/ops/boot_recovery.ps1" = "253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a"
        "scripts/ops/roll_verdict.ps1" = "3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881"
        "scripts/ops/workload_admission.ps1" = "4117eb901d292952473c57425434593bed414fa2ed2fecee301fe56e8f893306"
        "src/weather/operations/capture_recovery_check.py" = "814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895"
        "src/weather/operations/documentation_transaction.py" = "057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9"
        "src/weather/operations/execution_tape_supervisor.py" = "1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f"
    }
    $maximumMarkerAge = [timespan]::FromHours(36)
    $maximumFutureSkew = [timespan]::FromMinutes(5)

    # Windows PowerShell's ConvertFrom-Json silently accepts duplicate object
    # keys and resolves names case-insensitively on later property lookup. Parse
    # the complete grammar first so no reconciliation authority can be changed
    # by duplicate or case-colliding keys at any nesting depth.
    if (-not ("Weather.Operations.StatusStrictJsonObjectKeyValidator" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Weather.Operations
{
    public sealed class StatusStrictJsonObjectKeyValidator
    {
        private readonly string text;
        private int index;
        private int depth;

        private StatusStrictJsonObjectKeyValidator(string value)
        {
            if (value == null)
            {
                throw new ArgumentNullException("value");
            }
            text = value;
        }

        public static void Validate(string value)
        {
            StatusStrictJsonObjectKeyValidator parser =
                new StatusStrictJsonObjectKeyValidator(value);
            parser.SkipWhitespace();
            parser.ParseValue();
            parser.SkipWhitespace();
            if (parser.index != parser.text.Length)
            {
                throw new FormatException("trailing content after JSON value");
            }
        }

        private void ParseValue()
        {
            if (index >= text.Length)
            {
                throw new FormatException("unexpected end of JSON");
            }
            if (depth >= 32)
            {
                throw new FormatException("JSON nesting exceeds the fixed bound");
            }
            depth++;
            try
            {
                char c = text[index];
                if (c == '{') { ParseObject(); return; }
                if (c == '[') { ParseArray(); return; }
                if (c == '"') { ParseString(); return; }
                if (c == 't') { ParseLiteral("true"); return; }
                if (c == 'f') { ParseLiteral("false"); return; }
                if (c == 'n') { ParseLiteral("null"); return; }
                if (c == '-' || (c >= '0' && c <= '9'))
                {
                    ParseNumber();
                    return;
                }
                throw new FormatException("invalid JSON value");
            }
            finally { depth--; }
        }

        private void ParseObject()
        {
            Expect('{');
            SkipWhitespace();
            if (TryConsume('}')) { return; }
            HashSet<string> keys = new HashSet<string>(
                StringComparer.OrdinalIgnoreCase
            );
            while (true)
            {
                SkipWhitespace();
                string key = ParseString();
                if (!keys.Add(key))
                {
                    throw new FormatException("duplicate JSON property");
                }
                SkipWhitespace();
                Expect(':');
                SkipWhitespace();
                ParseValue();
                SkipWhitespace();
                if (TryConsume('}')) { return; }
                Expect(',');
            }
        }

        private void ParseArray()
        {
            Expect('[');
            SkipWhitespace();
            if (TryConsume(']')) { return; }
            while (true)
            {
                ParseValue();
                SkipWhitespace();
                if (TryConsume(']')) { return; }
                Expect(',');
                SkipWhitespace();
            }
        }

        private string ParseString()
        {
            Expect('"');
            StringBuilder value = new StringBuilder();
            while (index < text.Length)
            {
                char c = text[index++];
                if (c == '"') { return value.ToString(); }
                if (c < 0x20)
                {
                    throw new FormatException("control character in JSON string");
                }
                if (c != '\\')
                {
                    value.Append(c);
                    continue;
                }
                if (index >= text.Length)
                {
                    throw new FormatException("unterminated JSON escape");
                }
                char escaped = text[index++];
                switch (escaped)
                {
                    case '"': value.Append('"'); break;
                    case '\\': value.Append('\\'); break;
                    case '/': value.Append('/'); break;
                    case 'b': value.Append('\b'); break;
                    case 'f': value.Append('\f'); break;
                    case 'n': value.Append('\n'); break;
                    case 'r': value.Append('\r'); break;
                    case 't': value.Append('\t'); break;
                    case 'u':
                        if (index + 4 > text.Length)
                        {
                            throw new FormatException("short JSON unicode escape");
                        }
                        string hex = text.Substring(index, 4);
                        int code;
                        if (!Int32.TryParse(
                            hex,
                            NumberStyles.AllowHexSpecifier,
                            CultureInfo.InvariantCulture,
                            out code
                        ))
                        {
                            throw new FormatException("invalid JSON unicode escape");
                        }
                        value.Append((char)code);
                        index += 4;
                        break;
                    default:
                        throw new FormatException("invalid JSON escape");
                }
            }
            throw new FormatException("unterminated JSON string");
        }

        private void ParseNumber()
        {
            if (TryConsume('-') && index >= text.Length)
            {
                throw new FormatException("incomplete JSON number");
            }
            if (TryConsume('0'))
            {
                if (index < text.Length && Char.IsDigit(text[index]))
                {
                    throw new FormatException("leading zero in JSON number");
                }
            }
            else
            {
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON number");
                }
            }
            if (TryConsume('.'))
            {
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON fraction");
                }
            }
            if (index < text.Length &&
                (text[index] == 'e' || text[index] == 'E'))
            {
                index++;
                if (index < text.Length &&
                    (text[index] == '+' || text[index] == '-'))
                {
                    index++;
                }
                int start = index;
                while (index < text.Length && Char.IsDigit(text[index]))
                {
                    index++;
                }
                if (index == start)
                {
                    throw new FormatException("invalid JSON exponent");
                }
            }
        }

        private void ParseLiteral(string literal)
        {
            if (index + literal.Length > text.Length ||
                String.CompareOrdinal(text, index, literal, 0, literal.Length) != 0)
            {
                throw new FormatException("invalid JSON literal");
            }
            index += literal.Length;
        }

        private void SkipWhitespace()
        {
            while (index < text.Length)
            {
                char c = text[index];
                if (c != ' ' && c != '\t' && c != '\r' && c != '\n')
                {
                    return;
                }
                index++;
            }
        }

        private void Expect(char expected)
        {
            if (index >= text.Length || text[index] != expected)
            {
                throw new FormatException("invalid JSON syntax");
            }
            index++;
        }

        private bool TryConsume(char expected)
        {
            if (index < text.Length && text[index] == expected)
            {
                index++;
                return true;
            }
            return false;
        }
    }
}
'@
    }

    function ConvertFrom-StrictReconciliationJson {
        param(
            [Parameter(Mandatory = $true)][string]$Raw,
            [Parameter(Mandatory = $true)][string]$Label
        )

        try {
            [Weather.Operations.StatusStrictJsonObjectKeyValidator]::Validate($Raw)
            return ($Raw | ConvertFrom-Json -ErrorAction Stop)
        }
        catch {
            throw "$Label JSON is invalid or contains duplicate/case-colliding object keys: $($_.Exception.Message)"
        }
    }

    function Test-ReconciliationIncidentFieldPopulated {
        param(
            [Parameter(Mandatory = $true)][object]$Marker,
            [Parameter(Mandatory = $true)][string]$Name
        )

        $property = $Marker.PSObject.Properties[$Name]
        if ($null -eq $property -or $null -eq $property.Value) { return $false }
        $value = $property.Value
        if ($value -is [string]) {
            return -not [string]::IsNullOrWhiteSpace([string]$value)
        }
        if ($value -is [bool]) { return [bool]$value }
        if ($value -is [System.Collections.IDictionary]) { return $value.Count -gt 0 }
        if ($value -is [pscustomobject]) {
            return @($value.PSObject.Properties).Count -gt 0
        }
        if ($value -is [System.Collections.IEnumerable]) {
            return @($value).Count -gt 0
        }
        return $true
    }

    function Get-ReconciliationIncidentSignals {
        param([Parameter(Mandatory = $true)][object]$Marker)

        # reconciliation_config_content_sha256 is an additive compatibility
        # alias that the current writer also populates for genuine ordinary
        # markers. Every other populated reconciliation_* field is incident
        # evidence. The non-prefixed list covers the roll and child-RPC seam.
        $ordinaryCompatibilityFields = @("reconciliation_config_content_sha256")
        $candidateNames = @($Marker.PSObject.Properties | Where-Object {
                [string]$_.Name -like "reconciliation_*" -and
                [string]$_.Name -notin $ordinaryCompatibilityFields
            } | ForEach-Object { [string]$_.Name }) + @(
            "roll_verdict_exit_code",
            "roll_verdict_explicit_base",
            "roll_verdict_explicit_branch",
            "roll_verdict_json_sha256",
            "roll_verdict_transcript_sha256",
            "push_start_rpc_request_id",
            "push_start_rpc_request_sha256",
            "push_start_rpc_deadline_utc",
            "push_start_rpc_timed_out",
            "push_stop_rpc_request_id",
            "push_stop_rpc_request_sha256",
            "push_stop_rpc_deadline_utc",
            "push_stop_rpc_timed_out",
            "push_containment_deadline",
            "push_terminal_proved_at",
            "push_containment_breached",
            "push_terminal_proved",
            "push_run_observed",
            "push_stop_attempted",
            "push_stop_exhausted"
        )
        return @($candidateNames | Select-Object -Unique | Where-Object {
                Test-ReconciliationIncidentFieldPopulated -Marker $Marker -Name $_
            })
    }

    function New-PublicationState {
        param(
            [Parameter(Mandatory = $true)][string]$Classification,
            [string]$Detail = "",
            [string]$MergeCommit = "",
            [string]$LiveOriginMaster = "",
            [bool]$PushInvocationAttempted = $false,
            [bool]$PublicationAcknowledged = $false,
            [bool]$MarkerPresent = $true
        )
        return [pscustomobject]@{
            classification = $Classification
            detail = $Detail
            merge_commit = $MergeCommit
            live_origin_master = $LiveOriginMaster
            push_invocation_attempted = $PushInvocationAttempted
            publication_acknowledged = $PublicationAcknowledged
            marker_present = $MarkerPresent
            manual_push_allowed = ($Classification -ceq "ordinary")
        }
    }

    function Get-RequiredStringProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property -or $property.Value -isnot [string] -or
            [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "marker property '$Name' is missing or not a non-empty string"
        }
        return [string]$property.Value
    }

    function Get-RequiredBooleanProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property -or $property.Value -isnot [bool]) {
            throw "marker property '$Name' is missing or not Boolean"
        }
        return [bool]$property.Value
    }

    function Get-RequiredNonnegativeIntegerProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property -or
            ($property.Value -isnot [int] -and $property.Value -isnot [long]) -or
            [long]$property.Value -lt 0) {
            throw "marker property '$Name' is missing or not a nonnegative integer"
        }
        return [long]$property.Value
    }

    function Get-OptionalIntegerProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property) { throw "marker property '$Name' is missing" }
        if ($null -eq $property.Value) { return $null }
        if ($property.Value -isnot [int] -and $property.Value -isnot [long]) {
            throw "marker property '$Name' is not an integer"
        }
        return [long]$property.Value
    }

    function Get-OptionalStringProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property) { throw "marker property '$Name' is missing" }
        if ($null -eq $property.Value) { return $null }
        if ($property.Value -isnot [string] -or
            [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "marker property '$Name' is not a non-empty string or null"
        }
        return [string]$property.Value
    }

    function Get-OptionalTimestampProperty {
        param([object]$Object, [string]$Name)
        $property = $Object.PSObject.Properties[$Name]
        if ($null -eq $property) { throw "marker timestamp '$Name' is missing" }
        if ($null -eq $property.Value) { return $null }
        if ($property.Value -isnot [string] -or
            [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            throw "marker timestamp '$Name' is not a string"
        }
        try { return [datetimeoffset]::Parse([string]$property.Value) }
        catch { throw "marker timestamp '$Name' is invalid" }
    }

    function Get-StatusGitScalar {
        param([string[]]$Arguments)
        $rows = @(& git --no-optional-locks -C $RepositoryRoot @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0 -or $rows.Count -ne 1 -or
            [string]::IsNullOrWhiteSpace([string]$rows[0])) {
            throw "git $($Arguments -join ' ') did not return one value"
        }
        return ([string]$rows[0]).Trim().ToLowerInvariant()
    }

    function Get-StatusGitRows {
        param([string[]]$Arguments)
        $rows = @(& git --no-optional-locks -C $RepositoryRoot @Arguments 2>$null)
        if ($LASTEXITCODE -ne 0) {
            throw "git $($Arguments -join ' ') failed"
        }
        return @($rows | ForEach-Object {
                ([string]$_).Trim().Replace('\', '/')
            } | Where-Object { $_ })
    }

    function Get-StatusGitRawRows {
        param(
            [string[]]$Arguments,
            [switch]$AllowNoMatch
        )
        $rows = @(& git --no-optional-locks -C $RepositoryRoot @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
        if (($AllowNoMatch -and $exitCode -notin @(0, 1)) -or
            (-not $AllowNoMatch -and $exitCode -ne 0)) {
            throw "git $($Arguments -join ' ') failed"
        }
        return @($rows | ForEach-Object { ([string]$_).Trim() } |
                Where-Object { $_ })
    }

    function Assert-StatusCanonicalOrigin {
        $fetchUrls = @(Get-StatusGitRawRows -Arguments @(
                "remote", "get-url", "--all", "origin"
            ))
        $pushUrls = @(Get-StatusGitRawRows -Arguments @(
                "remote", "get-url", "--push", "--all", "origin"
            ))
        $pushUrlOverrides = @(Get-StatusGitRawRows -Arguments @(
                "config", "--get-all", "remote.origin.pushurl"
            ) -AllowNoMatch)
        $pushRefOverrides = @(Get-StatusGitRawRows -Arguments @(
                "config", "--get-all", "remote.origin.push"
            ) -AllowNoMatch)
        $urlRewrites = @(Get-StatusGitRawRows -Arguments @(
                "config", "--get-regexp", '^url\..*\.(insteadof|pushinsteadof)$'
            ) -AllowNoMatch)
        if ($fetchUrls.Count -ne 1 -or $pushUrls.Count -ne 1 -or
            [string]$fetchUrls[0] -cne $CanonicalOrigin -or
            [string]$pushUrls[0] -cne $CanonicalOrigin -or
            $pushUrlOverrides.Count -ne 0 -or $pushRefOverrides.Count -ne 0 -or
            $urlRewrites.Count -ne 0) {
            throw "origin fetch/push identity is not the exact canonical no-rewrite contract"
        }
    }

    function Get-StatusLiveOriginMaster {
        $gitCommands = @(Get-Command -Name "git.exe" -CommandType Application -ErrorAction SilentlyContinue)
        if ($gitCommands.Count -eq 0) {
            $gitCommands = @(Get-Command -Name "git" -CommandType Application -ErrorAction Stop)
        }
        if ($gitCommands.Count -eq 0 -or [string]::IsNullOrWhiteSpace([string]$gitCommands[0].Source)) {
            throw "Git executable is unavailable for bounded live origin acknowledgement"
        }
        if ($RepositoryRoot.Contains('"') -or $CanonicalOrigin.Contains('"')) {
            throw "repository/origin identity cannot be quoted for bounded live acknowledgement"
        }
        $token = [guid]::NewGuid().ToString("N")
        $temporaryRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        $stdoutPath = Join-Path $temporaryRoot "weather-status-origin-$token.out"
        $stderrPath = Join-Path $temporaryRoot "weather-status-origin-$token.err"
        $process = $null
        try {
            $process = Start-Process -FilePath ([string]$gitCommands[0].Source) `
                -ArgumentList @(
                    "--no-optional-locks", "-C", ('"{0}"' -f $RepositoryRoot),
                    "ls-remote", "--exit-code", "--refs",
                    ('"{0}"' -f $CanonicalOrigin), "refs/heads/master"
                ) `
                -WindowStyle Hidden -PassThru `
                -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
            if (-not $process.WaitForExit(5000)) {
                try { $process.Kill() }
                catch {
                    throw "bounded live origin acknowledgement timed out and root termination failed"
                }
                if (-not $process.WaitForExit(5000)) {
                    throw "bounded live origin acknowledgement timed out and root termination was not observed"
                }
                throw "bounded live origin acknowledgement timed out"
            }
            if (-not $process.WaitForExit(1000)) {
                throw "bounded live origin acknowledgement did not remain terminal during readback"
            }
            if ([int]$process.ExitCode -ne 0 -or
                -not (Test-Path -LiteralPath $stdoutPath -PathType Leaf)) {
                throw "bounded live origin acknowledgement failed"
            }
            $rows = @([IO.File]::ReadAllLines($stdoutPath, [Text.Encoding]::UTF8) |
                    Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })
            if ($rows.Count -ne 1 -or
                [string]$rows[0] -notmatch '^([0-9a-fA-F]{40})\s+refs/heads/master$') {
                throw "live origin/master response is not one exact full-SHA ref"
            }
            return $Matches[1].ToLowerInvariant()
        }
        finally {
            if ($process) { $process.Dispose() }
            Remove-Item -LiteralPath $stdoutPath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $stderrPath -Force -ErrorAction SilentlyContinue
        }
    }

    function Test-ExactConfigPathSet {
        param([object[]]$Rows)
        $normalized = @($Rows | ForEach-Object {
                ([string]$_).Trim().Replace('\', '/')
            } | Where-Object { $_ })
        return $normalized.Count -eq $configPaths.Count -and
            @($normalized | Where-Object { $configPaths -cnotcontains $_ }).Count -eq 0 -and
            @($configPaths | Where-Object { $normalized -cnotcontains $_ }).Count -eq 0
    }

    function Get-ContainedRepositoryPath {
        param([string]$RelativePath)
        if ([string]::IsNullOrWhiteSpace($RelativePath) -or
            [IO.Path]::IsPathRooted($RelativePath)) {
            throw "evidence path is empty or rooted"
        }
        $root = [IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\', '/')
        $candidate = [IO.Path]::GetFullPath(
            (Join-Path $root ($RelativePath.Replace('/', '\')))
        )
        if (-not $candidate.StartsWith(
                $root + [IO.Path]::DirectorySeparatorChar,
                [StringComparison]::OrdinalIgnoreCase
            )) {
            throw "evidence path escapes the repository"
        }
        return $candidate
    }

    $activeMarkerItem = $null
    try {
        $activeMarkerItem = Get-Item `
            -LiteralPath $ActiveMarkerPath -Force -ErrorAction Stop
    }
    catch [System.Management.Automation.ItemNotFoundException] {
        return New-PublicationState -Classification "ordinary" -MarkerPresent $false
    }
    catch {
        $lookupDetail = $_.Exception.Message
        if ([string]::IsNullOrWhiteSpace($lookupDetail)) {
            $lookupDetail = "active quiet-window marker lookup failed"
        }
        return New-PublicationState `
            -Classification "incident_evidence_invalid" `
            -Detail $lookupDetail `
            -PushInvocationAttempted $false `
            -PublicationAcknowledged $false
    }

    $marker = $null
    $markerSha256 = $null
    $liveOriginMaster = ""
    try {
        if ($activeMarkerItem.PSIsContainer -or
            ($activeMarkerItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "active quiet-window marker path is not a file"
        }
        $markerSha256 = (Get-FileHash -LiteralPath $ActiveMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
        $markerRaw = [IO.File]::ReadAllText(
            [IO.Path]::GetFullPath($ActiveMarkerPath),
            [Text.Encoding]::UTF8
        )
        if ([string]::IsNullOrWhiteSpace($markerRaw)) {
            throw "active quiet-window marker is empty"
        }
        $marker = ConvertFrom-StrictReconciliationJson `
            -Raw $markerRaw -Label "active quiet-window marker"
        if ((Get-RequiredStringProperty -Object $marker -Name "schema") -cne
            "quiet_window_merge_in_progress_v0.1") {
            throw "active quiet-window marker schema is unsupported"
        }
        $reconciliationSignals = @(Get-ReconciliationIncidentSignals -Marker $marker)
        $modeProperty = $marker.PSObject.Properties["operation_mode"]
        if ($null -eq $modeProperty -or $null -eq $modeProperty.Value -or
            [string]::IsNullOrWhiteSpace([string]$modeProperty.Value)) {
            if ($reconciliationSignals.Count -gt 0) {
                throw "active marker has populated reconciliation incident evidence but no operation mode: $($reconciliationSignals -join ', ')"
            }
            return New-PublicationState -Classification "ordinary"
        }
        if ([string]$modeProperty.Value -ceq "ordinary_synchronized_merge_v0.1") {
            if ($reconciliationSignals.Count -gt 0) {
                throw "ordinary operation mode cannot downgrade populated reconciliation incident evidence: $($reconciliationSignals -join ', ')"
            }
            return New-PublicationState -Classification "ordinary"
        }
        if ($modeProperty.Value -isnot [string] -or
            [string]$modeProperty.Value -cne "production_baseline_reconciliation_v0.1") {
            throw "active quiet-window marker operation mode is unsupported"
        }
        $rootFromMarker = [IO.Path]::GetFullPath(
            (Get-RequiredStringProperty -Object $marker -Name "repo_root")
        ).TrimEnd('\', '/')
        $normalizedRoot = [IO.Path]::GetFullPath($RepositoryRoot).TrimEnd('\', '/')
        if (-not $rootFromMarker.Equals($normalizedRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "marker repository root does not match the invoked checkout"
        }

        $updatedAt = [datetimeoffset]::Parse(
            (Get-RequiredStringProperty -Object $marker -Name "updated_at")
        )
        $markerAge = $Now.ToUniversalTime() - $updatedAt.ToUniversalTime()
        if ($markerAge -gt $maximumMarkerAge -or $markerAge -lt -$maximumFutureSkew) {
            throw "active reconciliation marker timestamp is stale or in the future"
        }

        $baselineCommit = (Get-RequiredStringProperty -Object $marker -Name "baseline_commit").ToLowerInvariant()
        $expectedBaseline = (Get-RequiredStringProperty -Object $marker -Name "expected_baseline").ToLowerInvariant()
        $reconciliationBaseline = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_local_baseline").ToLowerInvariant()
        $markerPublishedTarget = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_published_target").ToLowerInvariant()
        $bootGuardCommit = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_boot_guard_commit").ToLowerInvariant()
        if ($baselineCommit -cne $localBaseline -or $expectedBaseline -cne $localBaseline -or
            $reconciliationBaseline -cne $localBaseline -or
            $markerPublishedTarget -cne $publishedTarget -or
            $bootGuardCommit -cne $publishedTarget) {
            throw "marker L/T anchors are not the exact incident anchors"
        }

        $safetyTip = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_safety_tip").ToLowerInvariant()
        $sourceTip = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_source_tip").ToLowerInvariant()
        $expectedTip = (Get-RequiredStringProperty -Object $marker -Name "expected_tip").ToLowerInvariant()
        $resolvedTip = (Get-RequiredStringProperty -Object $marker -Name "resolved_branch_tip").ToLowerInvariant()
        $markerBranch = (Get-RequiredStringProperty -Object $marker -Name "branch").ToLowerInvariant()
        $sourceTree = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_source_tree").ToLowerInvariant()
        $safetyTree = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_safety_tree").ToLowerInvariant()
        $configCommit = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_actual_pre_merge_commit").ToLowerInvariant()
        $preMergeCommit = (Get-RequiredStringProperty -Object $marker -Name "pre_merge_commit").ToLowerInvariant()
        $mergeCommit = (Get-RequiredStringProperty -Object $marker -Name "merge_commit").ToLowerInvariant()
        foreach ($commitIdentity in @($safetyTip, $sourceTip, $expectedTip, $resolvedTip,
                $configCommit, $preMergeCommit, $mergeCommit)) {
            if ($commitIdentity -notmatch '^[0-9a-f]{40}$') {
                throw "marker contains a non-full commit identity"
            }
        }
        if ($sourceTree -notmatch '^[0-9a-f]{40}$' -or $safetyTree -notmatch '^[0-9a-f]{40}$' -or
            $sourceTree -cne $safetyTree -or
            $safetyTip -cne $sourceTip -or $safetyTip -cne $expectedTip -or
            $safetyTip -cne $resolvedTip -or $safetyTip -cne $markerBranch -or
            $configCommit -cne $preMergeCommit -or
            $safetyTip -ceq $publishedTarget) {
            throw "marker S/C identities are inconsistent"
        }

        Assert-StatusCanonicalOrigin
        $branch = Get-StatusGitScalar -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")
        $head = Get-StatusGitScalar -Arguments @("rev-parse", "HEAD^{commit}")
        $master = Get-StatusGitScalar -Arguments @("rev-parse", "refs/heads/master^{commit}")
        $originMaster = Get-StatusGitScalar -Arguments @("rev-parse", "refs/remotes/origin/master^{commit}")
        $liveOriginMaster = Get-StatusLiveOriginMaster
        if ($branch -cne "master" -or $head -cne $mergeCommit -or $master -cne $mergeCommit) {
            throw "current HEAD/master is not exact M"
        }

        $mergeParents = @((Get-StatusGitScalar -Arguments @(
                    "rev-list", "--parents", "-n", "1", $mergeCommit
                )) -split '\s+' | Where-Object { $_ })
        if ($mergeParents.Count -ne 3 -or $mergeParents[0] -cne $mergeCommit -or
            $mergeParents[1] -cne $configCommit -or $mergeParents[2] -cne $safetyTip) {
            throw "M does not have exact ordered parents [C,S]"
        }
        $configParents = @((Get-StatusGitScalar -Arguments @(
                    "rev-list", "--parents", "-n", "1", $configCommit
                )) -split '\s+' | Where-Object { $_ })
        if ($configParents.Count -ne 2 -or $configParents[0] -cne $configCommit -or
            $configParents[1] -cne $localBaseline) {
            throw "C is not an exact one-parent child of L"
        }
        & git --no-optional-locks -C $RepositoryRoot merge-base --is-ancestor $publishedTarget $safetyTip 2>$null
        if ($LASTEXITCODE -ne 0) { throw "S is not a strict descendant of T" }
        & git --no-optional-locks -C $RepositoryRoot merge-base --is-ancestor $reviewedParent $safetyTip 2>$null
        if ($LASTEXITCODE -ne 0) { throw "S does not descend from the exact reviewed parent" }
        if ((Get-StatusGitScalar -Arguments @("rev-parse", "$safetyTip^{tree}")) -cne $sourceTree) {
            throw "marker source tree does not match S"
        }
        if (-not (Test-ExactConfigPathSet -Rows (Get-StatusGitRows -Arguments @(
                        "diff", "--name-only", $localBaseline, $configCommit
                    ))) -or
            -not (Test-ExactConfigPathSet -Rows (Get-StatusGitRows -Arguments @(
                        "diff", "--name-only", $safetyTip, $mergeCommit
                    )))) {
            throw "C or M changes paths outside the exact generated-config set"
        }

        $markerPathValues = @($marker.auto_refreshed_paths)
        if (-not (Test-ExactConfigPathSet -Rows $markerPathValues)) {
            throw "marker auto-refreshed path set is not exact"
        }
        $hashProperties = @($marker.auto_refreshed_sha256.PSObject.Properties)
        $contentHashProperties = @($marker.reconciliation_config_content_sha256.PSObject.Properties)
        $snapshotProperties = @($marker.reconciliation_snapshot_paths.PSObject.Properties)
        if ($hashProperties.Count -ne $configPaths.Count -or
            $contentHashProperties.Count -ne $configPaths.Count -or
            $snapshotProperties.Count -ne $configPaths.Count -or
            @($configPaths | Where-Object { $hashProperties.Name -cnotcontains $_ }).Count -ne 0 -or
            @($configPaths | Where-Object { $contentHashProperties.Name -cnotcontains $_ }).Count -ne 0 -or
            @($configPaths | Where-Object { $snapshotProperties.Name -cnotcontains $_ }).Count -ne 0) {
            throw "marker config hash/snapshot maps are not exact"
        }

        $manifestRelative = Get-RequiredStringProperty -Object $marker -Name "reconciliation_snapshot_manifest_path"
        $normalizedManifestRelative = $manifestRelative.Replace('\', '/')
        if ($manifestRelative -cne $normalizedManifestRelative -or
            $normalizedManifestRelative -notmatch '^((?:data/alerts/production_baseline_reconciliation)/[0-9]{8}T[0-9]{9}-[0-9a-f]{32})/manifest\.json$') {
            throw "snapshot manifest path is not the exact immutable reconciliation layout"
        }
        $snapshotRootRelative = [string]$Matches[1]
        $manifestExpectedSha = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_snapshot_manifest_sha256").ToLowerInvariant()
        if ($manifestExpectedSha -notmatch '^[0-9a-f]{64}$') {
            throw "marker snapshot-manifest SHA256 is invalid"
        }
        $manifestPath = Get-ContainedRepositoryPath -RelativePath $manifestRelative
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $manifestExpectedSha) {
            throw "snapshot manifest is missing or changed"
        }
        $manifestRaw = [IO.File]::ReadAllText(
            $manifestPath, [Text.Encoding]::UTF8
        )
        $manifest = ConvertFrom-StrictReconciliationJson `
            -Raw $manifestRaw -Label "reconciliation snapshot manifest"
        $manifestCreatedAt = [datetimeoffset]::Parse(
            (Get-RequiredStringProperty -Object $manifest -Name "created_at")
        )
        $entrySha = (Get-RequiredStringProperty -Object $marker -Name "reconciliation_entry_sha256").ToLowerInvariant()
        if ((Get-RequiredStringProperty -Object $manifest -Name "schema") -cne
                "production_baseline_reconciliation_snapshot_v0.1" -or
            $manifestCreatedAt -gt $updatedAt -or
            (Get-RequiredStringProperty -Object $manifest -Name "local_baseline").ToLowerInvariant() -cne
                $localBaseline -or
            (Get-RequiredStringProperty -Object $manifest -Name "published_target").ToLowerInvariant() -cne
                $publishedTarget -or
            (Get-RequiredStringProperty -Object $manifest -Name "source_tip").ToLowerInvariant() -cne
                $safetyTip -or
            (Get-RequiredStringProperty -Object $manifest -Name "source_tree").ToLowerInvariant() -cne
                $sourceTree -or
            (Get-RequiredStringProperty -Object $manifest -Name "safety_tip").ToLowerInvariant() -cne
                $safetyTip -or
            (Get-RequiredStringProperty -Object $manifest -Name "safety_tree").ToLowerInvariant() -cne
                $safetyTree -or
            $entrySha -notmatch '^[0-9a-f]{64}$' -or
            (Get-RequiredStringProperty -Object $manifest -Name "entry_sha256").ToLowerInvariant() -cne
                $entrySha) {
            throw "snapshot manifest identity does not match L/T/S"
        }
        $entryPath = Get-ContainedRepositoryPath -RelativePath "scripts/ops/quiet_window_merge.ps1"
        if (-not (Test-Path -LiteralPath $entryPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $entryPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $entrySha) {
            throw "reconciliation entry bytes do not match the marker/snapshot identity"
        }

        $rollExitCode = Get-RequiredNonnegativeIntegerProperty -Object $marker -Name "roll_verdict_exit_code"
        $rollExplicitBase = (Get-RequiredStringProperty -Object $marker -Name "roll_verdict_explicit_base").ToLowerInvariant()
        $rollExplicitBranch = (Get-RequiredStringProperty -Object $marker -Name "roll_verdict_explicit_branch").ToLowerInvariant()
        $rollTranscriptSha = (Get-RequiredStringProperty -Object $marker -Name "roll_verdict_transcript_sha256").ToLowerInvariant()
        $rollJsonSha = Get-OptionalStringProperty -Object $marker -Name "roll_verdict_json_sha256"
        if ($null -ne $rollJsonSha) { $rollJsonSha = $rollJsonSha.ToLowerInvariant() }
        $manifestRoll = $manifest.roll_verdict
        $manifestRollExitCode = Get-RequiredNonnegativeIntegerProperty -Object $manifestRoll -Name "exit_code"
        $manifestRollReadable = Get-RequiredBooleanProperty -Object $manifestRoll -Name "readable"
        $manifestRollTranscriptPath = Get-RequiredStringProperty -Object $manifestRoll -Name "transcript_path"
        $manifestRollTranscriptSha = (Get-RequiredStringProperty -Object $manifestRoll -Name "transcript_sha256").ToLowerInvariant()
        $manifestRollJsonPath = Get-OptionalStringProperty -Object $manifestRoll -Name "json_path"
        $manifestRollJsonSha = Get-OptionalStringProperty -Object $manifestRoll -Name "json_sha256"
        if ($null -ne $manifestRollJsonSha) { $manifestRollJsonSha = $manifestRollJsonSha.ToLowerInvariant() }
        if ($rollExitCode -ne $manifestRollExitCode -or
            $rollExplicitBase -cne $localBaseline -or
            $rollExplicitBranch -cne $safetyTip -or
            (Get-RequiredStringProperty -Object $manifestRoll -Name "explicit_base").ToLowerInvariant() -cne
                $localBaseline -or
            (Get-RequiredStringProperty -Object $manifestRoll -Name "explicit_branch").ToLowerInvariant() -cne
                $safetyTip -or
            $rollTranscriptSha -notmatch '^[0-9a-f]{64}$' -or
            $manifestRollTranscriptSha -cne $rollTranscriptSha -or
            $manifestRollTranscriptPath -cne "$snapshotRootRelative/roll-verdict-output.txt") {
            throw "roll-verdict evidence does not bind exact L/S identities"
        }
        $rollTranscriptPath = Get-ContainedRepositoryPath -RelativePath $manifestRollTranscriptPath
        if (-not (Test-Path -LiteralPath $rollTranscriptPath -PathType Leaf) -or
            (Get-FileHash -LiteralPath $rollTranscriptPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $rollTranscriptSha) {
            throw "roll-verdict transcript snapshot is missing or changed"
        }
        if ($null -eq $manifestRollJsonPath) {
            if ($null -ne $manifestRollJsonSha -or $null -ne $rollJsonSha -or $manifestRollReadable) {
                throw "roll-verdict JSON/readability evidence is inconsistent"
            }
        }
        else {
            if ($manifestRollJsonPath -cne "$snapshotRootRelative/roll-verdict.json" -or
                $null -eq $manifestRollJsonSha -or
                $manifestRollJsonSha -notmatch '^[0-9a-f]{64}$' -or
                $rollJsonSha -cne $manifestRollJsonSha) {
                throw "roll-verdict JSON identity is inconsistent"
            }
            $rollJsonPath = Get-ContainedRepositoryPath -RelativePath $manifestRollJsonPath
            if (-not (Test-Path -LiteralPath $rollJsonPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $rollJsonPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $manifestRollJsonSha) {
                throw "roll-verdict JSON snapshot is missing or changed"
            }
            $rollPayloadRaw = [IO.File]::ReadAllText(
                $rollJsonPath, [Text.Encoding]::UTF8
            )
            $rollPayload = ConvertFrom-StrictReconciliationJson `
                -Raw $rollPayloadRaw -Label "reconciliation roll-verdict snapshot"
            if ($manifestRollReadable) {
                $rollGeneratedAt = [datetimeoffset]::Parse(
                    (Get-RequiredStringProperty -Object $rollPayload -Name "generated_at")
                )
                $expectedShortBase = Get-StatusGitScalar -Arguments @(
                    "rev-parse", "--short", $localBaseline
                )
                $expectedVerdict = switch ($rollExitCode) {
                    0 { "ROLL-FREE" }
                    2 { "ROLL-FREE-IF-DORMANT" }
                    3 { "ROLL-SENSITIVE" }
                    default { "" }
                }
                $closuresProperty = $rollPayload.PSObject.Properties["closures_used"]
                $problemsProperty = $rollPayload.PSObject.Properties["problems"]
                $filesProperty = $rollPayload.PSObject.Properties["files"]
                $incompleteClosureProblems = if ($null -ne $problemsProperty) {
                    @($problemsProperty.Value | Where-Object {
                            [string]$_ -match '(?i)(missing closure evidence|unreadable closure evidence|no source_scope_files|stale|dormant|tombstone)'
                        })
                }
                else { @("missing problems field") }
                $rollToSnapshot = $manifestCreatedAt.ToUniversalTime() -
                    $rollGeneratedAt.ToUniversalTime()
                if ([string]::IsNullOrWhiteSpace($expectedVerdict) -or
                    (Get-RequiredStringProperty -Object $rollPayload -Name "verdict") -cne
                        $expectedVerdict -or
                    (Get-RequiredStringProperty -Object $rollPayload -Name "branch").ToLowerInvariant() -cne
                        $safetyTip -or
                    (Get-RequiredStringProperty -Object $rollPayload -Name "base_ref").ToLowerInvariant() -cne
                        $localBaseline -or
                    (Get-RequiredStringProperty -Object $rollPayload -Name "base_sha").ToLowerInvariant() -cne
                        $expectedShortBase -or
                    $null -eq $closuresProperty -or @($closuresProperty.Value).Count -eq 0 -or
                    $null -eq $filesProperty -or $incompleteClosureProblems.Count -ne 0 -or
                    $rollToSnapshot -lt [timespan]::Zero -or
                    $rollToSnapshot -gt [timespan]::FromMinutes(5)) {
                    throw "readable roll-verdict payload is not the writer-validated L-to-S result"
                }
            }
        }

        $markerDependencyProperties = @($marker.reconciliation_dependency_sha256.PSObject.Properties)
        $manifestDependencyProperties = @($manifest.dependency_sha256.PSObject.Properties)
        $expectedManifestDependencyKeys = @(
            $localBaselineDependencySha256.Keys | ForEach-Object { "$_@local_baseline" }
        ) + @(
            $safetyDependencyPaths | ForEach-Object { "$_@safety_tip" }
        )
        $expectedMarkerDependencyKeys = @($expectedManifestDependencyKeys) + @(
            $publishedTargetDependencySha256.Keys | ForEach-Object { "$_@published_target" }
        ) + @(
            $safetyDependencyPaths | ForEach-Object { "$_@published_target" }
        )
        if ($manifestDependencyProperties.Count -ne $expectedManifestDependencyKeys.Count -or
            $markerDependencyProperties.Count -ne $expectedMarkerDependencyKeys.Count -or
            @($expectedManifestDependencyKeys | Where-Object {
                    $manifestDependencyProperties.Name -cnotcontains $_
                }).Count -ne 0 -or
            @($expectedMarkerDependencyKeys | Where-Object {
                    $markerDependencyProperties.Name -cnotcontains $_
                }).Count -ne 0) {
            throw "reconciliation dependency maps do not have the exact writer key sets"
        }
        foreach ($relativePath in $localBaselineDependencySha256.Keys) {
            $localKey = "$relativePath@local_baseline"
            $publishedKey = "$relativePath@published_target"
            $expectedLocalSha = [string]$localBaselineDependencySha256[$relativePath]
            $expectedPublishedSha = [string]$publishedTargetDependencySha256[$relativePath]
            if (([string]$marker.reconciliation_dependency_sha256.PSObject.Properties[$localKey].Value).ToLowerInvariant() -cne
                    $expectedLocalSha -or
                ([string]$manifest.dependency_sha256.PSObject.Properties[$localKey].Value).ToLowerInvariant() -cne
                    $expectedLocalSha -or
                ([string]$marker.reconciliation_dependency_sha256.PSObject.Properties[$publishedKey].Value).ToLowerInvariant() -cne
                    $expectedPublishedSha) {
                throw "fixed dependency stage identity disagrees: $relativePath"
            }
            $publishedDependencyPath = Get-ContainedRepositoryPath -RelativePath $relativePath
            if (-not (Test-Path -LiteralPath $publishedDependencyPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $publishedDependencyPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $expectedPublishedSha) {
                throw "published-target dependency bytes changed: $relativePath"
            }
        }
        foreach ($relativePath in $safetyDependencyPaths) {
            $dependencyKey = "$relativePath@safety_tip"
            $publishedDependencyKey = "$relativePath@published_target"
            $markerDependency = $markerDependencyProperties | Where-Object { $_.Name -ceq $dependencyKey }
            $manifestDependency = $manifestDependencyProperties | Where-Object { $_.Name -ceq $dependencyKey }
            $publishedDependency = $markerDependencyProperties | Where-Object {
                $_.Name -ceq $publishedDependencyKey
            }
            if (@($markerDependency).Count -ne 1 -or @($manifestDependency).Count -ne 1 -or
                @($publishedDependency).Count -ne 1) {
                throw "required safety dependency identity is missing: $dependencyKey"
            }
            $expectedDependencySha = ([string]$markerDependency[0].Value).ToLowerInvariant()
            if ($expectedDependencySha -notmatch '^[0-9a-f]{64}$' -or
                ([string]$manifestDependency[0].Value).ToLowerInvariant() -cne $expectedDependencySha -or
                ([string]$publishedDependency[0].Value).ToLowerInvariant() -cne $expectedDependencySha) {
                throw "safety dependency marker/snapshot identity disagrees: $dependencyKey"
            }
            if ($relativePath -ceq "scripts/ops/quiet_window_merge.ps1" -and
                $expectedDependencySha -cne $entrySha) {
                throw "entry SHA256 does not match the safety dependency identity"
            }
            $dependencyPath = Get-ContainedRepositoryPath -RelativePath $relativePath
            if (-not (Test-Path -LiteralPath $dependencyPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $dependencyPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $expectedDependencySha) {
                throw "adopted safety dependency bytes changed: $relativePath"
            }
            $dependencyBlob = Get-StatusGitScalar -Arguments @("rev-parse", "$safetyTip`:$relativePath")
            $liveDependencyBlob = Get-StatusGitScalar -Arguments @("hash-object", "--", $relativePath)
            if ($dependencyBlob -cne $liveDependencyBlob) {
                throw "adopted safety dependency is not the exact S blob: $relativePath"
            }
        }
        $manifestConfigProperties = @($manifest.config.PSObject.Properties)
        $manifestHashProperties = @($manifest.reconciliation_config_content_sha256.PSObject.Properties)
        if ($manifestConfigProperties.Count -ne $configPaths.Count -or
            $manifestHashProperties.Count -ne $configPaths.Count -or
            @($configPaths | Where-Object { $manifestConfigProperties.Name -cnotcontains $_ }).Count -ne 0 -or
            @($configPaths | Where-Object { $manifestHashProperties.Name -cnotcontains $_ }).Count -ne 0) {
            throw "snapshot manifest config map is not exact"
        }

        foreach ($relativePath in $configPaths) {
            $expectedHash = ([string]$marker.auto_refreshed_sha256.$relativePath).ToLowerInvariant()
            $snapshot = $marker.reconciliation_snapshot_paths.$relativePath
            $manifestSnapshot = $manifest.config.$relativePath
            $expectedSnapshotRelative = "$snapshotRootRelative/raw/$relativePath"
            if ($expectedHash -notmatch '^[0-9a-f]{64}$' -or
                ([string]$marker.reconciliation_config_content_sha256.$relativePath).ToLowerInvariant() -cne
                    $expectedHash -or
                ([string]$manifest.reconciliation_config_content_sha256.$relativePath).ToLowerInvariant() -cne
                    $expectedHash -or
                ([string]$snapshot.sha256).ToLowerInvariant() -cne $expectedHash -or
                ([string]$manifestSnapshot.sha256).ToLowerInvariant() -cne $expectedHash -or
                [string]$snapshot.snapshot_path -cne $expectedSnapshotRelative -or
                [string]$snapshot.snapshot_path -cne [string]$manifestSnapshot.snapshot_path -or
                [long]$snapshot.length -ne [long]$manifestSnapshot.length) {
                throw "config snapshot evidence disagrees for $relativePath"
            }
            $livePath = Get-ContainedRepositoryPath -RelativePath $relativePath
            $snapshotPath = Get-ContainedRepositoryPath -RelativePath ([string]$snapshot.snapshot_path)
            if (-not (Test-Path -LiteralPath $livePath -PathType Leaf) -or
                -not (Test-Path -LiteralPath $snapshotPath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $livePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $expectedHash -or
                (Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $expectedHash -or
                (Get-Item -LiteralPath $livePath -ErrorAction Stop).Length -ne [long]$snapshot.length -or
                (Get-Item -LiteralPath $snapshotPath -ErrorAction Stop).Length -ne [long]$snapshot.length) {
                throw "live/snapshotted config bytes disagree for $relativePath"
            }
            $configBlob = Get-StatusGitScalar -Arguments @("rev-parse", "$configCommit`:$relativePath")
            $mergeBlob = Get-StatusGitScalar -Arguments @("rev-parse", "$mergeCommit`:$relativePath")
            # Git's clean filter defines the blob that C/M commit. The raw-byte
            # SHA256 checks above independently bind the production file bytes.
            $liveBlob = Get-StatusGitScalar -Arguments @("hash-object", "--", $relativePath)
            if ($configBlob -cne $mergeBlob -or $mergeBlob -cne $liveBlob) {
                throw "C/M/live config blob identity disagrees for $relativePath"
            }
        }
        if (@(Get-StatusGitRows -Arguments @(
                    "status", "--porcelain=v1", "--untracked-files=all"
                )).Count -ne 0) {
            throw "post-M worktree is not clean"
        }

        $phase = Get-RequiredStringProperty -Object $marker -Name "phase"
        $captureRecoveryProved = Get-RequiredBooleanProperty -Object $marker -Name "capture_recovery_proved"
        $stagedRecoveryProved = Get-RequiredBooleanProperty -Object $marker -Name "reconciliation_staged_safety_capture_recovery_proved"
        $stagedRecoveryAt = Get-OptionalTimestampProperty -Object $marker -Name "reconciliation_staged_safety_capture_recovery_at"
        $prePushRecoveryProved = Get-RequiredBooleanProperty -Object $marker -Name "reconciliation_pre_push_capture_recovery_proved"
        $prePushRecoveryAt = Get-OptionalTimestampProperty -Object $marker -Name "reconciliation_pre_push_capture_recovery_at"
        $executionTapeRecoveryRequired = Get-RequiredBooleanProperty -Object $marker -Name "execution_tape_recovery_required"
        $executionTapeReadoptionExpected = Get-RequiredBooleanProperty -Object $marker -Name "execution_tape_readoption_expected"
        $executionTapeRolledInactive = Get-RequiredBooleanProperty -Object $marker -Name "execution_tape_rolled_but_inactive_skipped"
        $executionTapeRecoveryProved = Get-RequiredBooleanProperty -Object $marker -Name "execution_tape_recovery_proved"
        $executionTapeSourceBefore = Get-OptionalStringProperty -Object $marker -Name "execution_tape_source_before"
        if ($phase -notin @("merge_committed_unpublished", "documented_unpublished", "published") -or
            -not $captureRecoveryProved -or -not $stagedRecoveryProved -or
            $null -eq $stagedRecoveryAt -or $stagedRecoveryAt -gt $updatedAt -or
            $manifestCreatedAt -gt $stagedRecoveryAt -or
            $executionTapeRecoveryRequired -ne $executionTapeRecoveryProved -or
            ($executionTapeRecoveryRequired -ne ($null -ne $executionTapeSourceBefore)) -or
            ($executionTapeRolledInactive -and (-not $executionTapeReadoptionExpected -or
                    $executionTapeRecoveryRequired)) -or
            ($executionTapeReadoptionExpected -and -not ($executionTapeRecoveryRequired -xor
                    $executionTapeRolledInactive)) -or
            ($prePushRecoveryProved -ne ($null -ne $prePushRecoveryAt)) -or
            ($null -ne $prePushRecoveryAt -and ($prePushRecoveryAt -le $stagedRecoveryAt -or
                    $prePushRecoveryAt -gt $updatedAt))) {
            throw "marker phase or capture-recovery evidence is incomplete"
        }
        $documentationRecorded = Get-RequiredBooleanProperty -Object $marker -Name "documentation_transaction_recorded"
        $pendingEvidencePath = $null
        if ($phase -ceq "merge_committed_unpublished") {
            $pendingShaProperty = $marker.PSObject.Properties["documentation_transaction_pending_sha256"]
            $pendingPathProperty = $marker.PSObject.Properties["documentation_transaction_snapshot_path"]
            if ($documentationRecorded -or $null -eq $pendingShaProperty -or
                $null -eq $pendingPathProperty -or $null -ne $pendingShaProperty.Value -or
                $null -ne $pendingPathProperty.Value) {
                throw "pre-documentation phase claims documentation"
            }
        }
        else {
            $pendingSha = (Get-RequiredStringProperty -Object $marker -Name "documentation_transaction_pending_sha256").ToLowerInvariant()
            $pendingPath = Get-RequiredStringProperty -Object $marker -Name "documentation_transaction_snapshot_path"
            if (-not $documentationRecorded -or $pendingSha -notmatch '^[0-9a-f]{64}$' -or
                $pendingPath -cne "data/alerts/documentation_transactions/pending-$pendingSha.json") {
                throw "documented phase lacks exact documentation identity"
            }
            $pendingEvidencePath = Get-ContainedRepositoryPath -RelativePath $pendingPath
            if (-not (Test-Path -LiteralPath $pendingEvidencePath -PathType Leaf) -or
                (Get-FileHash -LiteralPath $pendingEvidencePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $pendingSha) {
                throw "documentation transaction snapshot is missing or changed"
            }
            $pendingSnapshotRaw = [IO.File]::ReadAllText(
                $pendingEvidencePath, [Text.Encoding]::UTF8
            )
            $pendingSnapshot = ConvertFrom-StrictReconciliationJson `
                -Raw $pendingSnapshotRaw `
                -Label "reconciliation documentation transaction snapshot"
            $pendingIntegrationsProperty = $pendingSnapshot.PSObject.Properties["integrations"]
            if ($null -eq $pendingIntegrationsProperty) {
                throw "documentation transaction snapshot has no integrations"
            }
            $pendingIntegrations = @($pendingIntegrationsProperty.Value)
            $invalidPendingIntegrations = @($pendingIntegrations | Where-Object {
                    [string]$_.integration_tip -notmatch '^[0-9a-f]{40}$' -or
                    [string]::IsNullOrWhiteSpace([string]$_.branch)
                })
            $matchingPendingIntegrations = @($pendingIntegrations | Where-Object {
                    ([string]$_.integration_tip).ToLowerInvariant() -ceq $mergeCommit -and
                    [string]$_.branch -ceq $safetyTip -and
                    ([string]$_.expected_tip).ToLowerInvariant() -ceq $safetyTip
                })
            if ($matchingPendingIntegrations.Count -eq 1) {
                $pendingRecordedAt = [datetimeoffset]::Parse(
                    (Get-RequiredStringProperty `
                            -Object $matchingPendingIntegrations[0] `
                            -Name "recorded_at_local")
                )
            }
            else { $pendingRecordedAt = $null }
            $pendingCreatedAt = [datetimeoffset]::Parse(
                (Get-RequiredStringProperty -Object $pendingSnapshot -Name "created_at_local")
            )
            $pendingDueAt = [datetimeoffset]::Parse(
                (Get-RequiredStringProperty -Object $pendingSnapshot -Name "due_at_local")
            )
            if ((Get-RequiredStringProperty -Object $pendingSnapshot -Name "schema_version") -cne
                    "documentation_transaction_pending_v0.1" -or
                (Get-RequiredStringProperty -Object $pendingSnapshot -Name "status") -cne
                    "PENDING" -or
                (Get-RequiredStringProperty -Object $pendingSnapshot -Name "latest_integration_tip").ToLowerInvariant() -cne
                    $mergeCommit -or
                $pendingIntegrations.Count -eq 0 -or $invalidPendingIntegrations.Count -ne 0 -or
                $matchingPendingIntegrations.Count -ne 1 -or
                $pendingDueAt -le $pendingCreatedAt -or
                $null -eq $pendingRecordedAt -or $pendingRecordedAt -lt $stagedRecoveryAt -or
                $pendingRecordedAt -gt $updatedAt) {
                throw "documentation transaction snapshot does not exactly bind M/S"
            }
        }

        $pushAttempted = Get-RequiredBooleanProperty -Object $marker -Name "push_invocation_attempted"
        $publicationAcknowledged = Get-RequiredBooleanProperty -Object $marker -Name "publication_acknowledged"
        $pushTerminalProved = Get-RequiredBooleanProperty -Object $marker -Name "push_terminal_proved"
        $pushRunObserved = Get-RequiredBooleanProperty -Object $marker -Name "push_run_observed"
        $pushStopAttempted = Get-RequiredBooleanProperty -Object $marker -Name "push_stop_attempted"
        $pushStopCount = Get-RequiredNonnegativeIntegerProperty -Object $marker -Name "push_stop_count"
        $pushStopExhausted = Get-RequiredBooleanProperty -Object $marker -Name "push_stop_exhausted"
        $pushContainmentBreached = Get-RequiredBooleanProperty -Object $marker -Name "push_containment_breached"
        $pushLastTaskResult = Get-OptionalIntegerProperty -Object $marker -Name "push_last_task_result"
        $pushRuntimeState = Get-OptionalStringProperty -Object $marker -Name "push_runtime_state"
        $pushStartRpcRequestId = Get-OptionalStringProperty -Object $marker -Name "push_start_rpc_request_id"
        $pushStartRpcRequestSha = Get-OptionalStringProperty -Object $marker -Name "push_start_rpc_request_sha256"
        $pushStartRpcDeadline = Get-OptionalTimestampProperty -Object $marker -Name "push_start_rpc_deadline_utc"
        $pushStartRpcTimedOut = Get-RequiredBooleanProperty -Object $marker -Name "push_start_rpc_timed_out"
        $pushStopRpcRequestId = Get-OptionalStringProperty -Object $marker -Name "push_stop_rpc_request_id"
        $pushStopRpcRequestSha = Get-OptionalStringProperty -Object $marker -Name "push_stop_rpc_request_sha256"
        $pushStopRpcDeadline = Get-OptionalTimestampProperty -Object $marker -Name "push_stop_rpc_deadline_utc"
        $pushStopRpcTimedOut = Get-RequiredBooleanProperty -Object $marker -Name "push_stop_rpc_timed_out"
        $pushPreLastRun = Get-OptionalTimestampProperty -Object $marker -Name "push_pre_last_run_time"
        $pushObservedLastRun = Get-OptionalTimestampProperty -Object $marker -Name "push_observed_last_run_time"
        $pushStartIssued = Get-OptionalTimestampProperty -Object $marker -Name "push_start_issued_at"
        $pushDeadline = Get-OptionalTimestampProperty -Object $marker -Name "push_containment_deadline"
        $pushTerminalAt = Get-OptionalTimestampProperty -Object $marker -Name "push_terminal_proved_at"
        if (($null -eq $pushStartIssued) -ne ($null -eq $pushDeadline) -or
            ($null -ne $pushStartIssued -and $pushStartIssued -ge $pushDeadline) -or
            ($null -eq $pushObservedLastRun) -ne ($null -eq $pushLastTaskResult) -or
            ($null -eq $pushObservedLastRun) -ne ($null -eq $pushRuntimeState) -or
            ($null -ne $pushObservedLastRun -and ($null -eq $pushPreLastRun -or
                    $pushObservedLastRun -lt $pushPreLastRun -or $pushObservedLastRun -gt $updatedAt)) -or
            ($null -ne $pushPreLastRun -and $pushPreLastRun -gt $updatedAt) -or
            ($null -ne $pushStartIssued -and $pushStartIssued -gt $updatedAt) -or
            ($null -ne $pushStartIssued -and $null -ne $pushPreLastRun -and
                $pushPreLastRun -gt $pushStartIssued) -or
            ($pushTerminalProved -ne ($null -ne $pushTerminalAt)) -or
            ($null -ne $pushTerminalAt -and ($null -eq $pushStartIssued -or
                    $pushTerminalAt -lt $pushStartIssued -or $pushTerminalAt -gt $updatedAt)) -or
            ($pushRunObserved -and ($null -eq $pushObservedLastRun -or
                    $null -eq $pushPreLastRun -or $pushObservedLastRun -le $pushPreLastRun)) -or
            ($pushStopAttempted -ne ($pushStopCount -gt 0)) -or $pushStopCount -gt 2 -or
            ($pushStopExhausted -and -not $pushStopAttempted) -or
            ($pushContainmentBreached -and $null -eq $pushStartIssued) -or
            (($null -eq $pushStartRpcRequestId) -ne ($null -eq $pushStartRpcDeadline)) -or
            ($null -ne $pushStartRpcRequestId -and $pushStartRpcRequestId -notmatch '^[0-9a-f]{32}$') -or
            ($null -ne $pushStartRpcRequestSha -and ($pushStartRpcRequestSha -notmatch '^[0-9a-f]{64}$' -or
                    $null -eq $pushStartRpcRequestId)) -or
            ($pushStartRpcTimedOut -and $null -eq $pushStartRpcRequestSha) -or
            (($null -ne $pushObservedLastRun -or $pushTerminalProved) -and
                $null -eq $pushStartRpcRequestSha) -or
            ($null -ne $pushStartRpcRequestId -and (-not $pushAttempted -or
                    -not $prePushRecoveryProved -or $null -eq $pushStartIssued -or
                    $pushStartRpcDeadline -le $pushStartIssued -or
                    $pushStartRpcDeadline -gt $pushDeadline)) -or
            (($null -eq $pushStopRpcRequestId) -ne ($null -eq $pushStopRpcDeadline)) -or
            ($null -ne $pushStopRpcRequestId -and $pushStopRpcRequestId -notmatch '^[0-9a-f]{32}$') -or
            ($null -ne $pushStopRpcRequestSha -and ($pushStopRpcRequestSha -notmatch '^[0-9a-f]{64}$' -or
                    $null -eq $pushStopRpcRequestId)) -or
            ($pushStopRpcTimedOut -and ($null -eq $pushStopRpcRequestSha -or
                    -not $pushStopExhausted)) -or
            ($pushStopExhausted -and $null -eq $pushStopRpcRequestSha) -or
            ($pushStopAttempted -ne ($null -ne $pushStopRpcRequestId)) -or
            ($null -ne $pushStopRpcRequestId -and ($null -eq $pushStartIssued -or
                    $pushStopRpcDeadline -le $pushStartIssued -or
                    $pushStopRpcDeadline -gt $pushDeadline))) {
            throw "push evidence fields or timestamps are inconsistent"
        }

        $classification = $null
        if ($publicationAcknowledged) {
            if (-not $pushAttempted -or $phase -cne "published" -or
                $originMaster -cne $mergeCommit -or $liveOriginMaster -cne $mergeCommit -or
                -not $prePushRecoveryProved -or $prePushRecoveryAt -gt $pushStartIssued -or
                -not $pushTerminalProved -or -not $pushRunObserved -or
                $pushStopExhausted -or $pushContainmentBreached -or
                $pushRuntimeState -cne "Ready" -or $null -eq $pushLastTaskResult -or
                $pushLastTaskResult -ne 0 -or
                $null -eq $pushStartRpcRequestId -or $null -eq $pushStartRpcRequestSha -or
                $null -eq $pushStartRpcDeadline -or $pushStartRpcTimedOut -or
                $pushStopRpcTimedOut -or
                ($pushStopAttempted -and $null -eq $pushStopRpcRequestSha) -or
                $null -eq $pushPreLastRun -or $null -eq $pushObservedLastRun -or
                $null -eq $pushStartIssued -or $null -eq $pushDeadline -or
                $null -eq $pushTerminalAt -or $pushObservedLastRun -le $pushPreLastRun -or
                $pushTerminalAt -ge $pushDeadline) {
                throw "published marker lacks exact successful push evidence"
            }
            $classification = "acknowledged"
        }
        elseif ($pushAttempted) {
            if ($phase -cne "documented_unpublished" -or
                $originMaster -notin @($publishedTarget, $mergeCommit) -or
                $liveOriginMaster -notin @($publishedTarget, $mergeCommit) -or
                $null -eq $pushPreLastRun -or
                $prePushRecoveryProved -ne ($null -ne $pushStartIssued) -or
                ($null -ne $pushStartIssued -and ($prePushRecoveryAt -gt $pushStartIssued -or
                        $pushPreLastRun -gt $pushStartIssued)) -or
                ($pushTerminalProved -and $pushRuntimeState -cne "Ready")) {
                throw "attempted marker phase/origin/runtime baseline is inconsistent"
            }
            $classification = "attempted_unacknowledged"
        }
        else {
            if ($phase -eq "published" -or $originMaster -cne $publishedTarget -or
                $liveOriginMaster -cne $publishedTarget -or
                $prePushRecoveryProved -or $pushTerminalProved -or $pushRunObserved -or
                $pushStopAttempted -or $pushStopCount -ne 0 -or $pushStopExhausted -or
                $pushContainmentBreached -or $null -ne $pushPreLastRun -or
                $null -ne $pushObservedLastRun -or $null -ne $pushLastTaskResult -or
                $null -ne $pushRuntimeState -or $null -ne $pushStartIssued -or
                $null -ne $pushDeadline -or $null -ne $pushTerminalAt -or
                $null -ne $pushStartRpcRequestId -or $null -ne $pushStartRpcRequestSha -or
                $null -ne $pushStartRpcDeadline -or $pushStartRpcTimedOut -or
                $null -ne $pushStopRpcRequestId -or $null -ne $pushStopRpcRequestSha -or
                $null -ne $pushStopRpcDeadline -or $pushStopRpcTimedOut) {
                throw "pre-dispatch marker contains contradictory push evidence"
            }
            $classification = "guarded_pre_dispatch"
        }

        # Re-sample the mutable boundary after every file and Git proof. A mixed
        # transition is invalid evidence, never permission to invoke the task.
        $evidenceFilesChanged = (
            (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $manifestExpectedSha -or
            (Get-FileHash -LiteralPath $entryPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $entrySha -or
            (Get-FileHash -LiteralPath $rollTranscriptPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $rollTranscriptSha
        )
        if ($null -ne $manifestRollJsonPath -and
            (Get-FileHash -LiteralPath $rollJsonPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $manifestRollJsonSha) {
            $evidenceFilesChanged = $true
        }
        if ($null -ne $pendingEvidencePath -and
            (Get-FileHash -LiteralPath $pendingEvidencePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $pendingSha) {
            $evidenceFilesChanged = $true
        }
        foreach ($relativePath in $configPaths) {
            $boundaryExpectedHash = ([string]$marker.auto_refreshed_sha256.$relativePath).ToLowerInvariant()
            $boundaryLivePath = Get-ContainedRepositoryPath -RelativePath $relativePath
            $boundarySnapshot = $marker.reconciliation_snapshot_paths.$relativePath
            $boundarySnapshotPath = Get-ContainedRepositoryPath `
                -RelativePath ([string]$boundarySnapshot.snapshot_path)
            if ((Get-FileHash -LiteralPath $boundaryLivePath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $boundaryExpectedHash -or
                (Get-FileHash -LiteralPath $boundarySnapshotPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                    $boundaryExpectedHash) {
                $evidenceFilesChanged = $true
            }
        }
        Assert-StatusCanonicalOrigin
        if ($evidenceFilesChanged -or
            (Get-FileHash -LiteralPath $ActiveMarkerPath -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant() -cne
                $markerSha256 -or
            (Get-StatusGitScalar -Arguments @("symbolic-ref", "--quiet", "--short", "HEAD")) -cne
                $branch -or
            (Get-StatusGitScalar -Arguments @("rev-parse", "HEAD^{commit}")) -cne $head -or
            (Get-StatusGitScalar -Arguments @("rev-parse", "refs/heads/master^{commit}")) -cne $master -or
            (Get-StatusGitScalar -Arguments @("rev-parse", "refs/remotes/origin/master^{commit}")) -cne
                $originMaster -or
            (Get-StatusLiveOriginMaster) -cne $liveOriginMaster -or
            @(Get-StatusGitRows -Arguments @(
                    "status", "--porcelain=v1", "--untracked-files=all"
                )).Count -ne 0) {
            throw "marker or Git refs changed during status validation"
        }
        return New-PublicationState `
            -Classification $classification `
            -MergeCommit $mergeCommit `
            -LiveOriginMaster $liveOriginMaster `
            -PushInvocationAttempted $pushAttempted `
            -PublicationAcknowledged $publicationAcknowledged
    }
    catch {
        $detail = $_.Exception.Message
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = "active marker validation failed" }
        if ($liveOriginMaster -notmatch '^[0-9a-f]{40}$') {
            try { $liveOriginMaster = Get-StatusLiveOriginMaster }
            catch { $liveOriginMaster = "" }
        }
        return New-PublicationState `
            -Classification "incident_evidence_invalid" `
            -Detail $detail `
            -LiveOriginMaster $liveOriginMaster `
            -PushInvocationAttempted $false `
            -PublicationAcknowledged $false
    }
}

function Get-WeatherUnpushedPublicationGuidance {
    param(
        [Parameter(Mandatory = $true)][int]$UnpushedCount,
        [Parameter(Mandatory = $true)][object]$PublicationState
    )

    $warning = if ($UnpushedCount -lt 0) {
        "unpushed commit state unreadable"
    }
    elseif ($UnpushedCount -gt 0) {
        if ([string]$PublicationState.classification -ceq "ordinary") {
            "$UnpushedCount commit(s) unpushed (run WeatherOneShotPush)"
        }
        else { "$UnpushedCount commit(s) unpushed" }
    }
    else { $null }
    $flag = switch ([string]$PublicationState.classification) {
        "guarded_pre_dispatch" {
            "RECONCILIATION_PUBLICATION_GUARDED_PRE_DISPATCH: guarded reconciliation owns publication; manual WeatherOneShotPush invocation is forbidden"
        }
        "attempted_unacknowledged" {
            "RECONCILIATION_PUBLICATION_ATTEMPTED_UNACKNOWLEDGED: publication is pending or uncertain; the sole invocation is spent and WeatherOneShotPush retry is forbidden"
        }
        "incident_evidence_invalid" {
            "RECONCILIATION_PUBLICATION_EVIDENCE_INVALID: preserve the active marker and obtain reviewed recovery; WeatherOneShotPush invocation is forbidden ($([string]$PublicationState.detail))"
        }
        default { $null }
    }
    return [pscustomobject]@{ warning = $warning; flag = $flag }
}

function Get-WeatherUnpushedPublicationSummary {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][object]$PublicationState
    )

    $classification = [string]$PublicationState.classification
    # Invalid incident evidence is never allowed to choose the comparison
    # object.  Its live-origin SHA may be real but unfetched, malformed marker
    # state cannot attest it, and treating a failed rev-list as zero would
    # suppress the ordinary safety warning.  Use the cached tracking ref for
    # ordinary/invalid state; only fully validated incident state may bind the
    # live canonical-origin SHA.
    $unpushedBase = if (
        $classification -notin @("ordinary", "incident_evidence_invalid") -and
        [string]$PublicationState.live_origin_master -match '^[0-9a-f]{40}$'
    ) { [string]$PublicationState.live_origin_master }
    else { "origin/master" }
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        # Native git writes a diagnostic to stderr for an unreadable revision.
        # Suppress that expected probe failure even when the caller uses Stop,
        # then classify it explicitly instead of accidentally terminating.
        $ErrorActionPreference = "SilentlyContinue"
        $rows = @(& git -C $RepositoryRoot rev-list --count "${unpushedBase}..master" 2>$null)
        $revListExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousErrorActionPreference }
    $readable = $revListExit -eq 0 -and $rows.Count -eq 1 -and
        ([string]$rows[0]).Trim() -match '^\d+$'
    if (-not $readable) {
        return [pscustomobject]@{
            display = "?"; count = -1; readable = $false; base = $unpushedBase
        }
    }
    $count = [int]([string]$rows[0]).Trim()
    return [pscustomobject]@{
        display = [string]$count; count = $count; readable = $true; base = $unpushedBase
    }
}

$quietMarkerPath = Join-Path $repo "data\alerts\quiet_window_merge_in_progress.json"
$qwf = Join-Path $repo "data\alerts\quiet_window_merge_last.json"
$reconciliationPublication = Get-WeatherReconciliationPublicationState `
    -RepositoryRoot $repo `
    -ActiveMarkerPath $quietMarkerPath `
    -CanonicalOrigin "https://github.com/michaelbooth1/weather.git"
$unpushedSummary = Get-WeatherUnpushedPublicationSummary `
    -RepositoryRoot $repo -PublicationState $reconciliationPublication
$unpushed = [string]$unpushedSummary.display
$dirty = @(& git -C $repo status --porcelain 2>$null)
$dirtyCount = ($dirty | Where-Object { $_ }).Count
$lastCommit = & git -C $repo log -1 --format="%h %s" 2>$null
$unpushedCount = [int]$unpushedSummary.count
$publicationGuidance = Get-WeatherUnpushedPublicationGuidance `
    -UnpushedCount $unpushedCount `
    -PublicationState $reconciliationPublication
if ($publicationGuidance.warning) {
    $warns.Add([string]$publicationGuidance.warning)
}
if ($publicationGuidance.flag) {
    $flags.Add([string]$publicationGuidance.flag)
}

# ---- scheduled tasks (classify against what is EXPECTED) ----
function Test-WeatherOneShotTrigger {
    param([object]$Trigger)

    if ($null -eq $Trigger) { return $false }
    $cimClassProperty = $Trigger.PSObject.Properties["CimClass"]
    if ($null -eq $cimClassProperty -or $null -eq $cimClassProperty.Value) { return $false }
    $classNameProperty = $cimClassProperty.Value.PSObject.Properties["CimClassName"]
    if ($null -eq $classNameProperty -or
        [string]$classNameProperty.Value -ne "MSFT_TaskTimeTrigger") {
        return $false
    }
    # Task Scheduler omits Repetition entirely for a true one-shot. Direct
    # member access to that valid sparse shape terminates a strict-mode caller.
    $repetitionProperty = $Trigger.PSObject.Properties["Repetition"]
    if ($null -eq $repetitionProperty -or $null -eq $repetitionProperty.Value) {
        return $true
    }
    $intervalProperty = $repetitionProperty.Value.PSObject.Properties["Interval"]
    return $null -eq $intervalProperty -or -not $intervalProperty.Value
}

function Get-WeatherCodexWakeReceiptState {
    param(
        [string]$TaskName,
        [string]$ActionArguments,
        [object]$TaskInfo
    )

    $state = [ordered]@{
        task_name = $TaskName
        recognized = $false
        runner_path = $null
        runner_sha256 = $null
        wake = $null
        receipt_path = $null
        receipt_present = $false
        correction_path = $null
        correction_applied = $false
        valid = $false
        status = $null
        schema_version = $null
        classification = $null
        detail = $null
    }
    $runnerMatch = [regex]::Match(
        $ActionArguments,
        "(?i)'([^']*\\live-(?:overnight-audits|night-salvage)-[^']*\\runner\.ps1)'"
    )
    $wakeMatch = [regex]::Match($ActionArguments, "(?i)-Wake\s+'([^']+)'(?:\s|;)")
    $hashMatch = [regex]::Match($ActionArguments, "(?i)-ne\s+'([0-9a-f]{64})'")
    $propagatesChildExit = (
        $ActionArguments -match '\$code\s*=\s*\[int\]\$LASTEXITCODE' -and
        $ActionArguments -match 'if\s*\(\$code\s*-ne\s*0\)\s*\{\s*exit\s+\$code\s*\}'
    )
    if (-not $runnerMatch.Success -or -not $wakeMatch.Success -or
        -not $hashMatch.Success -or -not $propagatesChildExit) {
        return [PSCustomObject]$state
    }

    $state.recognized = $true
    $state.runner_path = $runnerMatch.Groups[1].Value
    $state.wake = $wakeMatch.Groups[1].Value
    $state.runner_sha256 = $hashMatch.Groups[1].Value.ToUpperInvariant()
    $state.receipt_path = Join-Path (Split-Path -Parent $state.runner_path) (
        "receipts\{0}.json" -f $state.wake
    )
    $state.correction_path = Join-Path (Split-Path -Parent $state.runner_path) (
        "receipts\{0}.correction.json" -f $state.wake
    )
    if (-not (Test-Path -LiteralPath $state.runner_path -PathType Leaf)) {
        $state.detail = "bound runner is absent"
        return [PSCustomObject]$state
    }
    $actualRunnerHash = (Get-FileHash -LiteralPath $state.runner_path -Algorithm SHA256).Hash
    if ($actualRunnerHash -ne $state.runner_sha256) {
        $state.detail = "bound runner hash does not match its task action"
        return [PSCustomObject]$state
    }
    if (-not (Test-Path -LiteralPath $state.receipt_path -PathType Leaf)) {
        $state.detail = "authoritative wake receipt is absent"
        return [PSCustomObject]$state
    }
    $state.receipt_present = $true

    try { $receipt = Get-Content -LiteralPath $state.receipt_path -Raw | ConvertFrom-Json }
    catch {
        $state.detail = "authoritative wake receipt is unreadable"
        return [PSCustomObject]$state
    }
    $requiredFields = @(
        "schema_version", "wake", "task_name", "started_at_local", "finished_at_local",
        "status", "classification", "detail", "secret_values_read",
        "live_mutation_attempted_by_wrapper"
    )
    foreach ($field in $requiredFields) {
        if ($null -eq $receipt.PSObject.Properties[$field]) {
            $state.detail = "authoritative wake receipt is missing $field"
            return [PSCustomObject]$state
        }
    }
    $state.status = [string]$receipt.status
    $state.schema_version = [string]$receipt.schema_version
    $state.classification = [string]$receipt.classification
    $supportedSchemas = @(
        "live_overnight_codex_wake_receipt_v0.2",
        "live_night_salvage_wake_receipt_v0.1"
    )
    if ($supportedSchemas -notcontains [string]$receipt.schema_version -or
        [string]$receipt.task_name -ne $TaskName -or
        [string]$receipt.wake -ne $state.wake) {
        $state.detail = "authoritative wake receipt identity does not match the task action"
        return [PSCustomObject]$state
    }
    try {
        $receiptStarted = [DateTimeOffset]::Parse([string]$receipt.started_at_local)
        $receiptFinished = [DateTimeOffset]::Parse([string]$receipt.finished_at_local)
    }
    catch {
        $state.detail = "authoritative wake receipt timestamps are invalid"
        return [PSCustomObject]$state
    }
    if ($receiptFinished -lt $receiptStarted -or
        [math]::Abs(($receiptStarted.LocalDateTime - [datetime]$TaskInfo.LastRunTime).TotalMinutes) -gt 5) {
        $state.detail = "authoritative wake receipt does not correlate to the scheduled run"
        return [PSCustomObject]$state
    }
    if ([bool]$receipt.secret_values_read -or [bool]$receipt.live_mutation_attempted_by_wrapper) {
        $state.detail = "authoritative wake receipt reports a forbidden action"
        return [PSCustomObject]$state
    }
    $correction = $null
    if ($state.status -eq "FAIL" -and
        (Test-Path -LiteralPath $state.correction_path -PathType Leaf)) {
        try { $correction = Get-Content -LiteralPath $state.correction_path -Raw | ConvertFrom-Json }
        catch {
            $state.detail = "wake receipt correction is unreadable"
            return [PSCustomObject]$state
        }
        $correctionFields = @(
            "schema_version", "task_name", "wake", "created_at_local",
            "original_receipt_sha256", "last_message_sha256", "corrected_status",
            "corrected_classification", "detail"
        )
        foreach ($field in $correctionFields) {
            if ($null -eq $correction.PSObject.Properties[$field]) {
                $state.detail = "wake receipt correction is missing $field"
                return [PSCustomObject]$state
            }
        }
        try { $correctionCreated = [DateTimeOffset]::Parse([string]$correction.created_at_local) }
        catch {
            $state.detail = "wake receipt correction timestamp is invalid"
            return [PSCustomObject]$state
        }
        $receiptHash = (Get-FileHash -LiteralPath $state.receipt_path -Algorithm SHA256).Hash
        $lastMessageProperty = $receipt.PSObject.Properties["last_message_path"]
        $lastMessagePath = if ($null -ne $lastMessageProperty) {
            [string]$lastMessageProperty.Value
        }
        else { "" }
        if (-not $lastMessagePath -or
            -not (Test-Path -LiteralPath $lastMessagePath -PathType Leaf)) {
            $state.detail = "wake receipt correction cannot bind the completed agent handoff"
            return [PSCustomObject]$state
        }
        $lastMessageHash = (Get-FileHash -LiteralPath $lastMessagePath -Algorithm SHA256).Hash
        $correctionValid = @(
            [string]$correction.schema_version -eq "live_wake_receipt_correction_v0.1"
            [string]$correction.task_name -eq $TaskName
            [string]$correction.wake -eq $state.wake
            [string]$correction.original_receipt_sha256 -eq $receiptHash
            [string]$correction.last_message_sha256 -eq $lastMessageHash
            [string]$correction.corrected_status -eq "PASS"
            [string]$correction.corrected_classification -eq "bounded_codex_completed_without_integration"
            $correctionCreated -ge $receiptFinished
            $null -ne $receipt.agent_exit_code
            [int]$receipt.agent_exit_code -eq 0
            -not [bool]$receipt.agent_timed_out
            [string]$receipt.agent_output_sha256
        ) -notcontains $false
        if (-not $correctionValid) {
            $state.detail = "wake receipt correction does not satisfy its evidence contract"
            return [PSCustomObject]$state
        }
        $state.status = [string]$correction.corrected_status
        $state.classification = [string]$correction.corrected_classification
        $state.detail = [string]$correction.detail
        $state.correction_applied = $true
    }
    if ($state.status -eq "FAIL") {
        if ($state.classification -ne "refused_or_failed") {
            $state.detail = "failed wake receipt has an unexpected classification"
            return [PSCustomObject]$state
        }
        $state.valid = $true
        $state.detail = [string]$receipt.detail
        return [PSCustomObject]$state
    }
    if ($state.status -ne "PASS") {
        $state.detail = "authoritative wake receipt status is neither PASS nor FAIL"
        return [PSCustomObject]$state
    }

    $passContract = $false
    if ($state.schema_version -eq "live_overnight_codex_wake_receipt_v0.2" -and
        $state.wake -eq "smoke") {
        $passContract = (
            $state.classification -eq "authenticated_spawn_smoke" -and
            $null -ne $receipt.agent_exit_code -and
            [int]$receipt.agent_exit_code -eq 0 -and
            -not [bool]$receipt.agent_timed_out -and
            [string]$receipt.agent_output_sha256
        )
    }
    elseif ($state.schema_version -eq "live_overnight_codex_wake_receipt_v0.2" -and
        $state.wake -eq "0215") {
        if ($state.classification -eq "bounded_codex_completed_without_integration") {
            $passContract = (
                $state.correction_applied -and
                $null -ne $receipt.agent_exit_code -and
                [int]$receipt.agent_exit_code -eq 0 -and
                -not [bool]$receipt.agent_timed_out -and
                [string]$receipt.agent_output_sha256
            )
        }
        elseif ($state.classification -eq "integration_already_complete") {
            $passContract = [bool]$receipt.integration_complete_after
        }
        elseif ($state.classification -eq "integration_recovered_by_bounded_codex") {
            $passContract = (
                [bool]$receipt.integration_complete_after -and
                $null -ne $receipt.agent_exit_code -and
                [int]$receipt.agent_exit_code -eq 0 -and
                -not [bool]$receipt.agent_timed_out -and
                [string]$receipt.agent_output_sha256
            )
        }
    }
    elseif ($state.schema_version -eq "live_night_salvage_wake_receipt_v0.1" -and
        $state.wake -eq "preflight") {
        if ($state.classification -eq "preintegration_ready_no_agent") {
            $passContract = (
                [bool]$receipt.preflight_ready_after -and
                $null -ne $receipt.commit_percent_after -and
                [double]$receipt.commit_percent_after -lt 60 -and
                $null -eq $receipt.agent_pid
            )
        }
        elseif ($state.classification -eq "preintegration_recovered_by_codex") {
            $passContract = (
                [bool]$receipt.preflight_ready_after -and
                $null -ne $receipt.commit_percent_after -and
                [double]$receipt.commit_percent_after -lt 60 -and
                $null -ne $receipt.agent_exit_code -and
                [int]$receipt.agent_exit_code -eq 0 -and
                -not [bool]$receipt.agent_timed_out -and
                [string]$receipt.agent_output_sha256
            )
        }
    }
    elseif ($state.schema_version -eq "live_night_salvage_wake_receipt_v0.1" -and
        $state.wake -eq "morning") {
        $passContract = (
            $state.classification -eq "morning_closeout_completed" -and
            $null -ne $receipt.agent_exit_code -and
            [int]$receipt.agent_exit_code -eq 0 -and
            -not [bool]$receipt.agent_timed_out -and
            [string]$receipt.agent_output_sha256
        )
    }
    if (-not $passContract) {
        $state.detail = "PASS wake receipt does not satisfy its classification contract"
        return [PSCustomObject]$state
    }
    $state.valid = $true
    if (-not $state.correction_applied) {
        $state.detail = [string]$receipt.detail
    }
    return [PSCustomObject]$state
}

# Tasks that exit non-zero BY DESIGN pre-release, and tasks intentionally disabled.
$expNonZero = @{
    # 0x4B = the repository-owned wrapper reached/refused the 11:55 protected-window
    # deadline and its kill-on-close Job tore down the delegated child tree. The OS-held
    # workload lease is the ownership signal; stale JSON/lock text is diagnostic residue.
    "WeatherDailySettlementPromotionRefresh" = @("0x2", "0x4B")
    "WeatherEveningEvidenceRefresh"          = @("0x2")   # evidence gates BLOCK
    "WeatherTrainingWindow"                  = @("0x2")   # no promotion pre-release
    # 0x41306 = we terminated a wedged push. Pushes need an interactive logon session,
    # so this task legitimately fails when nobody is logged on; the honest health signal
    # is the unpushed-commit count below, not this exit code.
    "WeatherOneShotPush"                     = @("0x1", "0x0", "0x41306")
    # These two are MONITORS: their exit code is their verdict, not their health.
    # staleness_sweep.ps1:385  exit 1 = one or more WARN, exit 2 = one or more CRITICAL
    # health_watchdog.ps1:199  exit 2 = top severity CRITICAL
    # Flagging those as "unexpected" reported the smoke detector as the fire: on 2026-08-07
    # two of six FLAGS were these, on a day that also had a real capture failure to find. The
    # findings themselves are surfaced by their own reports, which are the daily reads.
    "WeatherStalenessSweep"                  = @("0x1", "0x2")
    "WeatherHostHealthWatchdog"              = @("0x2")
}
# The taker was PAUSED by operator decision 2026-08-07 to focus 100% on the maker
# (docs/operations/taker-paused-and-pruned-2026-08-07.md). Both tasks are deliberately
# Disabled; flagging them daily is noise. Re-enable BOTH to restart the taker.
# The off-host mirror was PAUSED by operator decision 2026-08-12 to keep this host's
# resources on capture stability (docs/operations/mirror-paused-2026-08-12.md). These three
# stay silent HERE because the mirror block below raises exactly one warn that carries the
# age of the frozen copy -- one voice for the pause, not four.
$expDisabled = @(
    "WeatherNightlyRetrainValidatePromote", "WeatherAgentQuietWindow",
    # Item 330 holds this standalone analysis on demand; daily freshness still applies.
    # docs/roadmap/items/item-330-maker-economics-refocus-master-plan.md
    "WeatherModelMarketDisagreementAnalysis",
    "WeatherTakerBotDailyRoll", "WeatherTakerBotDailyRollSupervisor",
    "WeatherDataMirror", "WeatherMirrorRestoreVerify", "WeatherOneShotMirror",
    # Legacy host-local queue drivers lack immutable expected-tip bindings. They stay off
    # until the repository-owned exact-tip queue replaces them. The -09-69a suite is also
    # review-blocked and must not be re-armed from its obsolete wrapper.
    "WeatherMergeQueueDriver", "WeatherMergeSensitiveDriver", "WeatherSuite0969a",
    # Superseded 2026-08-21 by the exact Fixed0822 pair. These retained disabled
    # definitions point at the pre-hardening tip and must never be re-enabled.
    "WeatherIntegrationRecoveryBootstrapSuite0822",
    "WeatherIntegrationRecoveryBootstrapMerge0822",
    # This operator hold remains visible through a dedicated warning below. Keeping it in
    # the generic anomaly path as well called the same deliberate state "unexpected".
    "WeatherEveningEvidenceRefresh",
    # The single-host training reservation is opt-in because it deliberately stops all
    # capture. Its independent 04:15 restore task remains enabled while this task is held.
    "WeatherTrainingWindow"
)
# The training reservation is expected disabled by default. An integration night can still
# carry one exact, enabled, self-disabling re-enable action; recognize that separately so the
# warning describes the temporary plan rather than the standing hold. The old 12-hour horizon
# missed tasks legitimately armed the prior morning for 04:20 the next day. Thirty hours covers
# that cadence without trusting an abandoned far-future task. Action, trigger, identity, and time
# are all checked: a similarly named task or an action with extra commands cannot change the
# classification.
$trainingReenableNow = Get-Date
$trainingReenableDeadline = $trainingReenableNow.AddHours(30)
$trainingReenable = @(Get-ScheduledTask -TaskName "WeatherTrainingWindowReenable*" -ErrorAction SilentlyContinue |
    Where-Object {
        $candidate = $_
        if ([string]$candidate.State -eq "Disabled" -or [string]$candidate.TaskPath -ne "\") {
            return $false
        }
        $candidateActions = @($candidate.Actions)
        $candidateTriggers = @($candidate.Triggers | Where-Object {
                Test-WeatherOneShotTrigger -Trigger $_
            })
        if ($candidateActions.Count -ne 1 -or $candidateTriggers.Count -ne 1) {
            return $false
        }
        $candidateAction = $candidateActions[0]
        $expectedExecutable = Join-Path $PSHOME "powershell.exe"
        $expectedArguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"Enable-ScheduledTask -TaskName 'WeatherTrainingWindow'; Disable-ScheduledTask -TaskName '$([string]$candidate.TaskName)'`""
        if ([string]$candidateAction.Execute -ine $expectedExecutable -or
            [string]$candidateAction.Arguments -cne $expectedArguments) {
            return $false
        }
        $info = $candidate | Get-ScheduledTaskInfo
        $info -and $info.NextRunTime -gt $trainingReenableNow -and
            $info.NextRunTime -le $trainingReenableDeadline
    })
if ($trainingReenable.Count -gt 0) {
    $warns.Add("WeatherTrainingWindow is intentionally held for tonight; an automatic re-enable is armed")
}
else {
    $trainingWindowTask = Get-ScheduledTask -TaskName "WeatherTrainingWindow" -ErrorAction SilentlyContinue
    if ($trainingWindowTask -and [string]$trainingWindowTask.State -eq "Disabled") {
        $warns.Add("WeatherTrainingWindow is held DISABLED by the opt-in maintenance policy; enable only for a reviewed runnable training night")
    }
}
$mustRemainDisabled = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::Ordinal
)
[void]$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapSuite0822")
[void]$mustRemainDisabled.Add("WeatherIntegrationRecoveryBootstrapMerge0822")
$taskCount = 0
$interactiveTasks = 0
$evidenceRefreshHeld = $false
$sensitiveDriverNextRun = $null
$armedQuietMerges = New-Object System.Collections.Generic.List[psobject]
$integrationAttemptState = New-Object System.Collections.Generic.List[psobject]
$observedIntegrationAttemptManifests = `
    [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
# Work that is ARMED but has not happened yet is invisible to every other check here: a
# one-shot scheduled for tonight can be deleted, disabled or silently mis-scheduled and
# nothing would say so until the morning it fails to have run. Surface the queue instead.
# List[psobject], not List[object]: `@($list)` throws "Argument types do not match" for a
# generic List[object] on this host. The -Json path only survives it because a pipeline
# enumerates the list first, which is luck rather than design.
$upcoming = New-Object System.Collections.Generic.List[psobject]
$overnightWakeState = New-Object System.Collections.Generic.List[psobject]
Get-ScheduledTask | Where-Object { $_.TaskName -like "Weather*" } | ForEach-Object {
    $taskCount++
    $ti = $_ | Get-ScheduledTaskInfo
    $res = "0x{0:X}" -f ($ti.LastTaskResult)
    $st = [string]$_.State
    $name = $_.TaskName
    $isExpectedDisabled = ($st -eq "Disabled" -and $expDisabled -contains $name)
    if ($mustRemainDisabled.Contains([string]$name) -and $st -ne "Disabled") {
        $flags.Add("$name is superseded and must never be re-enabled")
    }
    if ($name -eq "WeatherMergeSensitiveDriver" -and $st -ne "Disabled" -and $ti.NextRunTime) {
        $sensitiveDriverNextRun = [datetime]$ti.NextRunTime
    }
    # A task due soon on a one-shot trigger is armed work -- the quiet-window merge, a
    # chain recovery run. That is exactly what I want to see queued.
    #
    # Keying this on "never run" (0x41303) alone was wrong and hid real armed work: RE-ARMING
    # an existing one-shot leaves its last result 0x0, so it vanished from this list. Caught
    # 2026-07-27, when the merge task was re-pointed at a new branch for 01:15 and did not
    # appear. MSFT_TaskTimeTrigger is a `-Once` trigger; recurring work uses Daily/Weekly/
    # Logon/Boot classes, so this stays quiet about the routine fleet.
    # Repetition.Interval must be excluded too: the loop supervisors and guards are all
    # registered as a time trigger that then repeats every couple of minutes, so matching
    # the trigger class alone flagged nine recurring tasks as armed one-shot work.
    $oneShot = @($_.Triggers | Where-Object {
            Test-WeatherOneShotTrigger -Trigger $_
        }).Count -gt 0
    $noTriggers = ($null -eq $_.Triggers)
    $actionArguments = (@($_.Actions | ForEach-Object { [string]$_.Arguments }) -join " ")
    $wakeReceiptState = Get-WeatherCodexWakeReceiptState `
        -TaskName $name -ActionArguments $actionArguments -TaskInfo $ti
    if ($wakeReceiptState.recognized) { $overnightWakeState.Add($wakeReceiptState) }
    $completeAuditReceipt = $null
    $auditReportPath = $null
    if (
        $actionArguments -like "*audit_overnight_integration_chain.ps1*" -and
        $actionArguments -match '(?i)-ReportPath\s+(?:"([^"]+)"|(\S+))'
    ) {
        $auditReportPath = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
        try {
            $candidateAuditReceipt = Get-Content -LiteralPath $auditReportPath -Raw |
                ConvertFrom-Json
            if (
                $candidateAuditReceipt.schema_version -eq
                    "overnight_integration_chain_audit_v1" -and
                $candidateAuditReceipt.complete -eq $true
            ) {
                $completeAuditReceipt = $candidateAuditReceipt
            }
        }
        catch { }
    }
    $isQuietMergeAction = (
        $actionArguments -like "*quiet_window_merge.ps1*" -or
        $actionArguments -like "*suite_gated_quiet_merge.ps1*" -or
        $actionArguments -like "*integration_attempt_merge.ps1*"
    )
    # A replaced exact-tip quiet merge is spent evidence once that reviewed
    # object is already in production history, whether Task Scheduler retains
    # it as Disabled or as Ready with no next run. Do not hard-code dated task
    # names: bind the classification to the action's full SHA and Git ancestry.
    # An unmerged or unreadable tip remains anomalous.
    $integratedExactTipMerge = $false
    $integratedExactTip = $null
    if ($isQuietMergeAction -and
        $actionArguments -match '(?i)(?:^|\s)-ExpectedTip\s+([0-9a-f]{40})(?:\s|$)') {
        $integratedExactTip = $Matches[1].ToLowerInvariant()
    }
    elseif ($actionArguments -like "*integration_attempt_merge.ps1*") {
        $manifestMatch = [regex]::Match(
            $actionArguments,
            '(?i)(?:^|\s)-ManifestPath\s+(?:"([^"]+)"|(\S+))'
        )
        $manifestHashMatch = [regex]::Match(
            $actionArguments,
            '(?i)(?:^|\s)-ExpectedManifestSha256\s+([0-9a-f]{64})(?:\s|$)'
        )
        if ($manifestMatch.Success -and $manifestHashMatch.Success) {
            $attemptManifestPath = if ($manifestMatch.Groups[1].Success) {
                $manifestMatch.Groups[1].Value
            } else {
                $manifestMatch.Groups[2].Value
            }
            $attemptManifestHash = $manifestHashMatch.Groups[1].Value
            try {
                    $validatedManifest = Get-WeatherIntegrationValidatedEvidence `
                        -RepositoryRoot $repo `
                        -ManifestPath $attemptManifestPath `
                        -ExpectedManifestSha256 $attemptManifestHash `
                        -Target "manifest"
                    $attemptManifest = $validatedManifest.Payload
                    [void]$observedIntegrationAttemptManifests.Add(
                        [IO.Path]::GetFullPath($attemptManifestPath)
                    )
                    try {
                        Assert-WeatherIntegrationStatusTaskBindings `
                            -RepositoryRoot $repo `
                            -ManifestPath $attemptManifestPath `
                            -ExpectedManifestSha256 $attemptManifestHash | Out-Null
                    }
                    catch {
                        $flags.Add("integration attempt $($attemptManifest.attempt_id) live suite/merge task binding failed strict intent/receipt validation")
                    }
                    $integratedExactTip = [string]$attemptManifest.expected_tip
                    $suiteReceiptStatus = $null
                    $mergeReceiptStatus = $null
                    $reconciliationStatus = $null
                    $closureStatus = $null
                    $dispatchStatus = $null
                    $claimStatus = $null
                    $successorAttemptId = $null
                    $attemptEvidenceUnreadable = New-Object System.Collections.Generic.List[string]
                    foreach ($receiptSpec in @(
                        [pscustomobject]@{ Name = "registration intent"; Path = (Join-Path ([string]$attemptManifest.attempt_root) "registration-intent.json"); Target = "registration_intent" },
                        [pscustomobject]@{ Name = "registration receipt"; Path = [string]$attemptManifest.evidence.registration_receipt; Target = "registration" },
                        [pscustomobject]@{ Name = "suite receipt"; Path = [string]$attemptManifest.evidence.suite_receipt; Target = "suite" },
                        [pscustomobject]@{ Name = "merge receipt"; Path = [string]$attemptManifest.evidence.merge_receipt; Target = "merge" },
                        [pscustomobject]@{ Name = "reconciliation receipt"; Path = [string]$attemptManifest.evidence.reconciliation_receipt; Target = "reconciliation" },
                        [pscustomobject]@{ Name = "closure receipt"; Path = [string]$attemptManifest.evidence.closure_receipt; Target = "closure" },
                        [pscustomobject]@{ Name = "recovery dispatch"; Path = [string]$attemptManifest.evidence.recovery_dispatch; Target = "dispatch" }
                        )) {
                        if (-not (Test-Path -LiteralPath $receiptSpec.Path -PathType Leaf)) { continue }
                        try {
                            $validatedEvidence = Get-WeatherIntegrationValidatedEvidence `
                                -RepositoryRoot $repo `
                                -ManifestPath $attemptManifestPath `
                                -ExpectedManifestSha256 $attemptManifestHash `
                                -Target ([string]$receiptSpec.Target)
                            $receiptPayload = $validatedEvidence.Payload
                            $receiptStatus = [string]$validatedEvidence.Status
                            if ($receiptSpec.Target -eq "suite") { $suiteReceiptStatus = $receiptStatus }
                            elseif ($receiptSpec.Target -eq "merge") { $mergeReceiptStatus = $receiptStatus }
                            elseif ($receiptSpec.Target -eq "reconciliation") { $reconciliationStatus = $receiptStatus }
                            elseif ($receiptSpec.Target -eq "closure") { $closureStatus = $receiptStatus }
                            elseif ($receiptSpec.Target -eq "dispatch") { $dispatchStatus = $receiptStatus }
                        }
                        catch { $attemptEvidenceUnreadable.Add([string]$receiptSpec.Name) }
                    }
                    if ($null -eq $mergeReceiptStatus -and
                        (Test-Path -LiteralPath ([string]$attemptManifest.evidence.quiet_merge_report) -PathType Leaf)) {
                        try {
                            $validatedQuietEvidence = Get-WeatherIntegrationValidatedEvidence `
                                -RepositoryRoot $repo `
                                -ManifestPath $attemptManifestPath `
                                -ExpectedManifestSha256 $attemptManifestHash `
                                -Target "quiet_report"
                            # A child-owned report survives a parent hard kill.
                            # Preserve the distinction between an origin-acknowledged
                            # publication and a recovered local commit that still
                            # requires reviewed publication resume.
                            $mergeReceiptStatus = [string]$validatedQuietEvidence.Status
                        }
                        catch { $attemptEvidenceUnreadable.Add("quiet merge report") }
                    }
                    $successorClaimPath = Join-Path ([string]$attemptManifest.attempt_root) "successor-claim.json"
                    if (Test-Path -LiteralPath $successorClaimPath -PathType Leaf) {
                        try {
                            $validatedClaim = Get-WeatherIntegrationValidatedEvidence `
                                -RepositoryRoot $repo `
                                -ManifestPath $attemptManifestPath `
                                -ExpectedManifestSha256 $attemptManifestHash `
                                -Target "claim"
                            $successorClaim = $validatedClaim.Payload
                            $claimStatus = [string]$validatedClaim.Status
                            $successorAttemptId = [string]$successorClaim.successor_attempt_id
                        }
                        catch {
                            $attemptEvidenceUnreadable.Add("successor claim")
                        }
                    }
                    foreach ($unreadableName in $attemptEvidenceUnreadable) {
                        $flags.Add("integration attempt $($attemptManifest.attempt_id) has unreadable $unreadableName evidence")
                    }
                    $attemptEvidenceTimes = New-Object System.Collections.Generic.List[datetime]
                    foreach ($attemptEvidencePath in @(
                        $attemptManifestPath,
                        (Join-Path ([string]$attemptManifest.attempt_root) "registration-intent.json"),
                        [string]$attemptManifest.evidence.registration_receipt,
                        [string]$attemptManifest.evidence.suite_receipt,
                        [string]$attemptManifest.evidence.merge_receipt,
                        [string]$attemptManifest.evidence.reconciliation_receipt,
                        [string]$attemptManifest.evidence.closure_receipt,
                        [string]$attemptManifest.evidence.recovery_dispatch,
                        $successorClaimPath
                    )) {
                        if (Test-Path -LiteralPath $attemptEvidencePath -PathType Leaf) {
                            try { $attemptEvidenceTimes.Add((Get-Item -LiteralPath $attemptEvidencePath).LastWriteTime) } catch { }
                        }
                    }
                    $newestAttemptEvidence = @($attemptEvidenceTimes | Sort-Object -Descending | Select-Object -First 1)
                    $attemptEvidenceAgeHours = if ($newestAttemptEvidence.Count -eq 0) {
                        $null
                    }
                    else {
                        [math]::Round(((Get-Date) - $newestAttemptEvidence[0]).TotalHours, 1)
                    }
                    $attemptEvidenceIsFresh = ($null -eq $attemptEvidenceAgeHours -or $attemptEvidenceAgeHours -le 24)
                    $attemptObservationAt = Get-Date
                    $suiteStatusBeforeObservation = [string]$suiteReceiptStatus
                    $suiteObservation = Get-WeatherIntegrationSuiteObservation `
                        -AttemptManifest $attemptManifest `
                        -Now $attemptObservationAt `
                        -SuiteReceiptStatus ([string]$suiteReceiptStatus) `
                        -ClosureStatus ([string]$closureStatus)
                    if ([string]::IsNullOrWhiteSpace($suiteStatusBeforeObservation) -and
                        -not [string]::IsNullOrWhiteSpace([string]$suiteObservation.ReceiptStatus)) {
                        try {
                            $freshValidatedSuite = Get-WeatherIntegrationValidatedEvidence `
                                -RepositoryRoot $repo `
                                -ManifestPath $attemptManifestPath `
                                -ExpectedManifestSha256 $attemptManifestHash `
                                -Target "suite"
                            $suiteObservation.ReceiptStatus = [string]$freshValidatedSuite.Status
                        }
                        catch {
                            $suiteObservation.ReceiptStatus = ""
                            $suiteObservation.ReceiptUnreadable = $true
                            $suiteObservation.RanWithoutReceipt = (
                                [bool]$suiteObservation.Ran -and
                                -not [bool]$suiteObservation.Running -and
                                [string]::IsNullOrWhiteSpace([string]$closureStatus)
                            )
                        }
                    }
                    if ([bool]$suiteObservation.ReceiptUnreadable -and
                        -not $attemptEvidenceUnreadable.Contains("suite receipt")) {
                        $flags.Add("integration attempt $($attemptManifest.attempt_id) has unreadable suite receipt evidence")
                    }
                    $suiteReceiptStatus = [string]$suiteObservation.ReceiptStatus
                    $attemptMissedSuite = [bool]$suiteObservation.TriggerMissed
                    $mergeObservation = Get-WeatherIntegrationMergeObservation `
                        -AttemptManifest $attemptManifest `
                        -TaskState ([string]$st) `
                        -Now $attemptObservationAt `
                        -MergeReceiptStatus ([string]$mergeReceiptStatus) `
                        -ClosureStatus ([string]$closureStatus)
                    $attemptState = Get-WeatherIntegrationAttemptState `
                        -SuiteReceiptStatus $suiteReceiptStatus `
                        -MergeReceiptStatus $mergeReceiptStatus `
                        -ReconciliationStatus $reconciliationStatus `
                        -ClosureStatus $closureStatus `
                        -DispatchStatus $dispatchStatus `
                        -ClaimStatus $claimStatus
                    $integrationAttemptState.Add([pscustomobject]@{
                            attempt_id = [string]$attemptManifest.attempt_id
                            state = $attemptState
                            expected_tip = $integratedExactTip
                            manifest_path = $attemptManifestPath
                            recovery_dispatch = [string]$attemptManifest.evidence.recovery_dispatch
                            successor_attempt_id = $successorAttemptId
                            task_state = $st
                            merge_task_state = $st
                            suite_task_state = [string]$suiteObservation.TaskState
                            suite_last_run_time = if ($null -eq $suiteObservation.LastRunTime) { $null } else { ([datetime]$suiteObservation.LastRunTime).ToString("o") }
                            suite_preflight_exists = [bool]$suiteObservation.PreflightExists
                            suite_running = [bool]$suiteObservation.Running
                            suite_ran = [bool]$suiteObservation.Ran
                            suite_started = [bool]$suiteObservation.Started
                            suite_ran_without_receipt = [bool]$suiteObservation.RanWithoutReceipt
                            evidence_age_hours = $attemptEvidenceAgeHours
                            suite_trigger_missed = $attemptMissedSuite
                            merge_receipt_missing_after_trigger = [bool]$mergeObservation.ReceiptMissingAfterTrigger
                        })
                    $attemptAlert = Get-WeatherIntegrationAttemptAlertDisposition `
                        -AttemptId ([string]$attemptManifest.attempt_id) `
                        -State $attemptState `
                        -TaskState $st `
                        -EvidenceIsFresh $attemptEvidenceIsFresh `
                        -SuiteTriggerMissed $attemptMissedSuite `
                        -SuiteRanWithoutReceipt ([bool]$suiteObservation.RanWithoutReceipt) `
                        -MergeReceiptMissingAfterTrigger ([bool]$mergeObservation.ReceiptMissingAfterTrigger) `
                        -RecoveryDispatch ([string]$attemptManifest.evidence.recovery_dispatch) `
                        -SuccessorAttemptId $successorAttemptId `
                        -PublicationClassification ([string]$reconciliationPublication.classification)
                    if ([string]$attemptAlert.Severity -eq "FLAG") { $flags.Add([string]$attemptAlert.Detail) }
                    elseif ([string]$attemptAlert.Severity -eq "WARN") { $warns.Add([string]$attemptAlert.Detail) }
            }
            catch {
                $flags.Add("integration attempt manifest $attemptManifestPath is unreadable or does not match its task-bound hash")
            }
        }
    }
    if ($integratedExactTip) {
        & git -C $repo merge-base --is-ancestor $integratedExactTip HEAD 2>$null
        $integratedExactTipMerge = ($LASTEXITCODE -eq 0)
    }
    if ($oneShot -and $ti.NextRunTime -and $isQuietMergeAction) {
        $settleSeconds = 300
        if ($actionArguments -match '(?i)-SettleSeconds\s+(\d+)') {
            $settleSeconds = [int]$Matches[1]
        }
        $rollbackRecoverySeconds = 1200
        if ($actionArguments -match '(?i)-RollbackRecoverySeconds\s+(\d+)') {
            $rollbackRecoverySeconds = [int]$Matches[1]
        }
        $successProtectionSeconds = $settleSeconds + 240
        $rollbackProtectionSeconds = $settleSeconds + $rollbackRecoverySeconds + 60
        $protectedSeconds = [math]::Max($successProtectionSeconds, $rollbackProtectionSeconds)
        $protectedUntil = ([datetime]$ti.NextRunTime).AddSeconds($protectedSeconds)
        if ($actionArguments -like "*integration_attempt_merge.ps1*") {
            # The attempt consumer can wait for its exact suite through 03:40,
            # then owns the guarded merge child through its 05:00 containment
            # boundary. Another merge driver inside that interval could advance
            # the frozen production baseline or publish local master underneath it.
            $protectedUntil = ([datetime]$ti.NextRunTime).Date.AddHours(5)
        }
        $armedQuietMerges.Add([PSCustomObject]@{
                name = $name
                at = [datetime]$ti.NextRunTime
                # Cover both success (settle + push acknowledgement) and failure (settle +
                # bounded rollback readoption proof). The dangerous case is another driver
                # publishing local master before the guarded script has completed either path.
                protected_until = $protectedUntil
            })
    }
    # Both push tasks are deliberately Interactive: the Windows credential vault is not
    # available to S4U. Other Interactive tasks are reboot exposure only while they are
    # enabled and still have scheduled work. A disabled task or spent one-shot cannot miss
    # a run after reboot, and an on-demand task has no unattended schedule to miss.
    $deliberatelyInteractive = @("WeatherOneShotPush", "WeatherOneShotMirror")
    $scheduledWorkRemains = (-not $noTriggers -and (-not $oneShot -or $ti.NextRunTime))
    if ([string]$_.Principal.LogonType -eq "Interactive" -and
        $deliberatelyInteractive -notcontains $name -and $st -ne "Disabled" -and
        $scheduledWorkRemains) {
        $interactiveTasks++
    }
    if ($name -eq "WeatherEveningEvidenceRefresh" -and $st -eq "Disabled") {
        $evidenceRefreshHeld = $true
    }
    if ($ti.NextRunTime -and ($res -eq "0x41303" -or $oneShot)) {
        $hrs = ([datetime]$ti.NextRunTime - (Get-Date)).TotalHours
        if ($hrs -gt 0 -and $hrs -lt 16 -and -not $isExpectedDisabled) {
            $upcoming.Add([PSCustomObject]@{
                    name = $name; at = ([datetime]$ti.NextRunTime); in_hours = [math]::Round($hrs, 1)
                    state = $st
                })
            # Armed work that is disabled will never fire, and silence is the failure mode.
            if ($st -eq "Disabled" -and $expDisabled -notcontains $name) {
                $flags.Add("$name is armed for $($ti.NextRunTime) but DISABLED - it will not fire")
            }
            # Armed work landing inside 12:00-18:00 would roll the fleet in the graded window.
            # quiet_window_merge and chain_recovery_run both refuse there, but a mis-scheduled
            # trigger should be visible here rather than relying on the callee to save us.
            $atHour = ([datetime]$ti.NextRunTime).Hour
            if ($atHour -ge 12 -and $atHour -lt 18) {
                $flags.Add("$name is armed for $($ti.NextRunTime), inside the 12:00-18:00 graded window")
            }
        }
    }
    $completedWake = (
        $wakeReceiptState.recognized -and $oneShot -and -not $ti.NextRunTime -and
        $ti.LastRunTime -and $st -ne "Running"
    )
    if ($completedWake) {
        if (-not $wakeReceiptState.receipt_present) {
            $flags.Add(
                "$name completed without its authoritative wake receipt; $($wakeReceiptState.detail)"
            )
        }
        elseif (-not $wakeReceiptState.valid) {
            $flags.Add(
                "$name authoritative wake receipt is invalid: $($wakeReceiptState.detail); " +
                "review $($wakeReceiptState.receipt_path)"
            )
        }
        elseif ($wakeReceiptState.status -eq "FAIL") {
            $flags.Add(
                "$name authoritative wake receipt is FAIL: $($wakeReceiptState.detail); " +
                "review $($wakeReceiptState.receipt_path)"
            )
        }
        else {
            $warns.Add(
                "$name authoritative wake receipt is PASS " +
                "($($wakeReceiptState.classification)); $($wakeReceiptState.receipt_path)"
            )
        }
        return
    }
    if ($st -eq "Disabled") {
        # A one-shot that FIRED, SUCCEEDED and then disabled itself is completed work, not an
        # anomaly. Every guarded agent runner (lock day, quiet window, post-merge watchdog,
        # morning briefing) ends with Disable-ScheduledTask by design so it cannot re-fire on a
        # later boot. On 2026-08-05 that raised three simultaneous "unexpectedly DISABLED" flags
        # for three tasks that had each done exactly what they were built to do. Same lesson as
        # the spent-FAILED case below: a monitor that flags success trains us to ignore it.
        $selfDisarmed = ($oneShot -and -not $ti.NextRunTime -and $res -eq "0x0" -and $ti.LastRunTime)
        # Expected-disabled is checked FIRST. A spent one-shot that is ALSO deliberately
        # disabled (WeatherOneShotMirror, 2026-08-12) matched $selfDisarmed and reported
        # "self-disarmed cleanly", which is a different claim from "an operator turned this
        # off" and points at the wrong artifact. Deliberate beats incidental.
        $onDemandCompleted = ($noTriggers -and $res -eq "0x0" -and $ti.LastRunTime)
        if ($expDisabled -contains $name) { }
        elseif ($integratedExactTipMerge) {
            $warns.Add("$name is disabled and retained as spent exact-tip merge evidence; $integratedExactTip is already in production history")
        }
        elseif ($onDemandCompleted) {
            $warns.Add("$name completed an on-demand run at $($ti.LastRunTime) and is now disabled (exit 0x0) - verify its artifact before relying on the result")
        }
        elseif ($selfDisarmed) {
            # 2026-08-10: this used to end "completed work, no action". It cannot know that.
            # WeatherAgentOvernight1030 exited 0x0 having done NOTHING - claude.exe printed
            # "You've hit your session limit" and returned 0 - and this line called it completed
            # work. Exit 0x0 proves the task RAN and disarmed; it proves nothing about output.
            # Say only what the exit code supports, and point at the artifact that would show it.
            $warns.Add("$name ran $($ti.LastRunTime) and self-disarmed cleanly (spent one-shot, exit 0x0) - task ran; exit code does NOT prove it produced output, check its artifact")
        }
        elseif ($oneShot -and -not $ti.NextRunTime -and $ti.LastRunTime) {
            # A failed one-shot can deliberately self-disable too. Describe the
            # completed run and its durable receipt, not the expected terminal
            # scheduler state.
            $spentFailure = "$name spent one-shot FAILED $res on $($ti.LastRunTime); verify its artifact"
            $auditFailures = @($completeAuditReceipt.failures)
            $knownRetainedGapOnly = (
                $null -ne $completeAuditReceipt -and
                $completeAuditReceipt.ok -eq $false -and
                $auditFailures.Count -eq 1 -and
                [string]$auditFailures[0] -like
                    "execution_tape_runtime:*health=DEGRADED; capture=CONNECTED; integrity=PASS; identity=True; lock=True*"
            )
            if ($completeAuditReceipt -and $completeAuditReceipt.ok -eq $true) {
                $warns.Add(
                    "$name retained failed scheduler result $res; later complete audit receipt is PASS"
                )
            }
            elseif ($knownRetainedGapOnly) {
                $warns.Add(
                    "$name complete audit remains BLOCK only for retained execution-tape gaps; " +
                    "producer is CONNECTED with integrity, identity, and lock PASS"
                )
            }
            elseif ($completeAuditReceipt) {
                $flags.Add(
                    "$name complete audit verdict is BLOCK with $($auditFailures.Count) failure(s); " +
                    "review $auditReportPath"
                )
            }
            elseif ([datetime]$ti.LastRunTime -lt (Get-Date).AddHours(-24)) {
                $warns.Add($spentFailure)
            }
            else {
                $flags.Add($spentFailure)
            }
        }
        else { $flags.Add("$name unexpectedly DISABLED") }
    }
    else {
        $ok = ($res -eq "0x0")
        # LastTaskResult is a completed-run field, not a live-run verdict. Task
        # Scheduler can retain the prior result (observed as 0x800710E0 for an
        # on-demand suite) while State already says Running. Health and hang
        # checks belong to each workload's own monitor; do not turn that stale
        # result into a generic failure before the current run has completed.
        if (-not $ok -and $st -eq "Running") { $ok = $true }
        # 0x41301 = SCHED_S_TASK_RUNNING: we sampled the task mid-execution (the
        # every-minute supervisors make this a routine race). The task is healthy
        # by definition while running; its next completed result is what matters.
        if (-not $ok -and $res -eq "0x41301") { $ok = $true }
        # 0x41303 = SCHED_S_TASK_HAS_NOT_RUN: a scheduled one-shot that has not fired yet.
        # Normal for freshly registered work, and flagging it would train us to ignore flags.
        if (-not $ok -and $res -eq "0x41303") { $ok = $true }
        if (-not $ok -and $expNonZero.ContainsKey($name)) { $ok = ($expNonZero[$name] -contains $res) }
        # A completed exact-tip merge can leave the one-shot Ready with no next
        # run and retain the failed result of an earlier attempt. Once Git proves
        # that exact reviewed object is in production, the task is spent evidence,
        # not a current failure. This does not forgive an unintegrated tip.
        if (-not $ok -and $integratedExactTipMerge -and $oneShot -and -not $ti.NextRunTime) {
            $warns.Add("$name prior attempt ended $res on $($ti.LastRunTime), but exact tip $integratedExactTip is already in production history (spent one-shot)")
            $ok = $true
        }
        # Re-arming a one-shot preserves its previous exit code. Once a future
        # run is present, that code is historical evidence about the prior
        # attempt, not proof that the armed attempt already failed.
        if (-not $ok -and $oneShot -and $ti.NextRunTime -and
            ([datetime]$ti.NextRunTime) -gt (Get-Date)) {
            $warns.Add("$name is re-armed for $($ti.NextRunTime); previous attempt ended $res on $($ti.LastRunTime)")
            $ok = $true
        }
        # A SPENT one-shot -- it fired, has no NextRunTime, and last ran over a day ago -- is
        # finished work, not current breakage. Its exit code is history and would otherwise burn
        # a FLAG forever: the three WeatherQuietWindowMerge tasks were still flagging 0x1 from
        # 2026-08-01 two days later, long after a manual re-run had completed the merge. Keep the
        # failure visible, but report it as what it is -- an old run nobody re-armed -- so it
        # cannot masquerade as a live fault and train us to ignore the flag list.
        if (-not $ok -and $oneShot -and -not $ti.NextRunTime -and $ti.LastRunTime -and
            ([datetime]$ti.LastRunTime) -lt (Get-Date).AddHours(-24)) {
            $warns.Add("$name last FAILED $res on $($ti.LastRunTime) and is NOT re-armed (spent one-shot) - re-register it if that work still needs to run")
            $ok = $true
        }
        if (-not $ok) { $flags.Add("$name $res unexpected (last run $($ti.LastRunTime))") }
    }
}

# Do not rely solely on a recognizable live merge-task action for attempt
# discovery. That is the very field whose drift the status command must expose.
# Canonical registered manifests are independently recoverable from the first
# immutable registrar write, whose manifest path/hash are strictly validated.
$integrationAttemptRoot = Join-Path $repo "data\integration_attempts"
if (Test-Path -LiteralPath $integrationAttemptRoot -PathType Container) {
    foreach ($candidateManifestFile in @(
        Get-ChildItem -LiteralPath $integrationAttemptRoot -Filter "manifest.json" -File -Recurse
    )) {
        $candidateManifestPath = [IO.Path]::GetFullPath([string]$candidateManifestFile.FullName)
        $candidateIntentPath = Join-Path $candidateManifestFile.DirectoryName "registration-intent.json"
        if (-not (Test-Path -LiteralPath $candidateIntentPath -PathType Leaf) -or
            $observedIntegrationAttemptManifests.Contains($candidateManifestPath)) {
            continue
        }
        try {
            $candidateIntent = Get-Content -LiteralPath $candidateIntentPath -Raw | ConvertFrom-Json
            $candidateManifestSha256 = [string]$candidateIntent.manifest_sha256
            $validatedIntent = Get-WeatherIntegrationValidatedEvidence `
                -RepositoryRoot $repo `
                -ManifestPath $candidateManifestPath `
                -ExpectedManifestSha256 $candidateManifestSha256 `
                -Target "registration_intent"
            $validatedManifest = Get-WeatherIntegrationValidatedEvidence `
                -RepositoryRoot $repo `
                -ManifestPath $candidateManifestPath `
                -ExpectedManifestSha256 $candidateManifestSha256 `
                -Target "manifest"
            $candidateAttempt = $validatedManifest.Payload

            $terminalEvidence = $false
            foreach ($terminalSpec in @(
                [pscustomobject]@{ Path = [string]$candidateAttempt.evidence.reconciliation_receipt; Target = "reconciliation"; RequiredStatus = "MERGED_RECONCILED" },
                [pscustomobject]@{ Path = [string]$candidateAttempt.evidence.closure_receipt; Target = "closure"; RequiredStatus = "FAIL" },
                [pscustomobject]@{ Path = [string]$candidateAttempt.evidence.merge_receipt; Target = "merge"; RequiredStatus = "PASS" }
            )) {
                if (-not (Test-Path -LiteralPath $terminalSpec.Path -PathType Leaf)) { continue }
                try {
                    $validatedTerminal = Get-WeatherIntegrationValidatedEvidence `
                        -RepositoryRoot $repo `
                        -ManifestPath $candidateManifestPath `
                        -ExpectedManifestSha256 $candidateManifestSha256 `
                        -Target ([string]$terminalSpec.Target)
                    if ([string]$validatedTerminal.Status -eq [string]$terminalSpec.RequiredStatus) {
                        $terminalEvidence = $true
                        break
                    }
                }
                catch {
                    $flags.Add("integration attempt $($candidateAttempt.attempt_id) has unreadable $($terminalSpec.Target) evidence")
                }
            }
            if ($terminalEvidence) { continue }

            $bindingDetail = "task action does not expose its canonical manifest identity"
            try {
                Assert-WeatherIntegrationStatusTaskBindings `
                    -RepositoryRoot $repo `
                    -ManifestPath $candidateManifestPath `
                    -ExpectedManifestSha256 $candidateManifestSha256 | Out-Null
                $bindingDetail = "exact tasks exist but the merge action is not discoverable"
            }
            catch {
                $bindingDetail = "live task binding failed strict intent/receipt validation"
            }
            $flags.Add("integration attempt $($candidateAttempt.attempt_id) task-binding drift: $bindingDetail")
            $integrationAttemptState.Add([pscustomobject]@{
                attempt_id = [string]$candidateAttempt.attempt_id
                state = "TASK_BINDING_DRIFT"
                expected_tip = [string]$candidateAttempt.expected_tip
                manifest_path = $candidateManifestPath
                recovery_dispatch = [string]$candidateAttempt.evidence.recovery_dispatch
                successor_attempt_id = $null
                task_state = "UNDISCOVERABLE"
                merge_task_state = "UNDISCOVERABLE"
                suite_task_state = "UNVALIDATED"
                suite_last_run_time = $null
                suite_preflight_exists = Test-Path -LiteralPath ([string]$candidateAttempt.evidence.preflight_log) -PathType Leaf
                suite_running = $false
                suite_ran = $false
                suite_started = $false
                suite_ran_without_receipt = $false
                evidence_age_hours = [math]::Round(((Get-Date) - $candidateManifestFile.LastWriteTime).TotalHours, 1)
                suite_trigger_missed = $false
                merge_receipt_missing_after_trigger = $false
            })
        }
        catch {
            $flags.Add("canonical integration attempt manifest $candidateManifestPath or its registration intent is unreadable")
        }
    }
}

if ($sensitiveDriverNextRun) {
    foreach ($mergeTask in $armedQuietMerges) {
        if ($sensitiveDriverNextRun -ge $mergeTask.at -and
            $sensitiveDriverNextRun -le $mergeTask.protected_until) {
            $flags.Add(
                "$($mergeTask.name) recovery/publish interval overlaps WeatherMergeSensitiveDriver at $sensitiveDriverNextRun - the driver can publish unverified local master"
            )
        }
    }
}

if ($evidenceRefreshHeld) {
    $warns.Add("WeatherEveningEvidenceRefresh is operator-held DISABLED; evidence refresh remains unavailable until it is explicitly re-enabled")
}

# ---- unattended resilience ----
# HISTORY, because the comment here outlived the fact and produced a false alarm for ten
# days. Before 2026-07-24 almost every Weather* task was LogonType=Interactive, so the fleet
# only ran while a user session existed and a reboot left this host DARK until somebody
# logged in. That was fixed: measured 2026-08-03, every capture-critical task
# (WeatherSnapshotLoopSupervisor, WeatherClobBookLoopSupervisor,
# WeatherObservationTriggerSupervisor, WeatherCapturePriorityGuard) is S4U with a time
# trigger, and WeatherBootRecovery is S4U on a boot trigger. Credential-vault push tasks are
# excluded above; any other enabled Interactive task with scheduled work remains visible.
# The exposure is still surfaced continuously, because the monitoring cannot warn about the
# one failure that would disable the monitoring.
#
# NOT YET PROVEN: the S4U fix has never survived a real reboot (uptime was 322 h on
# 2026-08-03; the fix landed 07-24, last boot 07-21). Configuration says capture self-recovers.
# That is not the same as measured. Worth a deliberate 01:00-04:00 reboot test after the lock.
$windowsUpdatePolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
$windowsUpdateAuOptions = $null
try {
    $updatePolicy = Get-ItemProperty -Path $windowsUpdatePolicyPath -ErrorAction SilentlyContinue
    if ($updatePolicy -and $updatePolicy.PSObject.Properties.Name -contains "AUOptions") {
        $windowsUpdateAuOptions = [int]$updatePolicy.AUOptions
    }
}
catch {}
if ($windowsUpdateAuOptions -eq 2) {
    $flags.Add("Windows Update is policy-forced to notify-only (AUOptions=2); unattended security updates cannot download/install")
}
$rebootPending = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
$autoLogon = ""
try {
    $autoLogon = [string](Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon" -ErrorAction SilentlyContinue).AutoAdminLogon
}
catch {}
if ($interactiveTasks -gt 0 -and $autoLogon -ne "1") {
    if ($rebootPending) {
        $flags.Add("REBOOT PENDING + $interactiveTasks logon-dependent tasks + no auto-logon: a restart leaves the whole fleet DOWN until someone logs in")
    }
    else {
        $warns.Add("$interactiveTasks Weather tasks are LogonType=Interactive with no auto-logon - none of them run after an unattended reboot")
    }
}
elseif ($rebootPending) {
    # The fleet is S4U now, so a restart self-recovers; still worth knowing one is queued
    # because it costs a short capture gap whenever it happens.
    $warns.Add("reboot pending - fleet is S4U so it self-recovers, but expect a brief capture gap; avoid restarting inside 12:00-18:00")
}

# ---- off-host mirror (the only copy of data\ that is not on this disk) ----
# PAUSED by operator decision 2026-08-12 to keep this 16 GB host's resources on capture
# stability (docs/operations/mirror-paused-2026-08-12.md). The pause switch is the TASK STATE,
# not a marker file: re-enabling WeatherDataMirror restores full alerting automatically, so the
# suppression cannot outlive the pause or be forgotten in a file nobody reads. A paused mirror
# still WARNS on every run, carrying the AGE of the frozen copy -- the point is to stop crying
# wolf about a nightly job that is off on purpose, NOT to stop saying data\ is unprotected.
$mirrorPaused = $false
try { $mirrorPaused = ([string](Get-ScheduledTask -TaskName "WeatherDataMirror" -EA Stop).State -eq "Disabled") } catch {}
$mirror = $null
$mirrorAgeH = $null
$mf = Join-Path $env:USERPROFILE "ops\mirror_status.json"
if (Test-Path $mf) {
    try {
        $mirror = Get-Content $mf -Raw | ConvertFrom-Json
        $mirrorAgeH = [math]::Round(((Get-Date) - [datetime]$mirror.last_run).TotalHours, 1)
    }
    catch {}
}
if ($null -eq $mirror) { $warns.Add("mirror status unreadable - off-host copy unverified") }
elseif ($mirrorPaused) {
    $frozenAt = "an unknown date"
    try { $frozenAt = ([datetime]$mirror.last_run).ToString("yyyy-MM-dd HH:mm") } catch {}
    $warns.Add("mirror PAUSED by operator 2026-08-12 - the off-host copy of data\ is FROZEN at $frozenAt (${mirrorAgeH}h old and ageing). Everything written since exists ONLY on this disk. Re-enable WeatherDataMirror to resume")
}
elseif (-not $mirror.ok) { $flags.Add("mirror last run FAILED (robocopy exit $($mirror.robocopy_exit))") }
elseif ($mirrorAgeH -gt 30) { $flags.Add("mirror stale: last good run ${mirrorAgeH}h ago (nightly 04:30)") }

# robocopy's exit code says a copy RAN, not that what landed can be restored. With the tape
# backup's restore drill disabled since 2026-06-30, nothing proved the mirror readable until
# verify_mirror_restore.ps1 pulled files back and hashed them. Surface that separately from
# mirror freshness -- "copied recently" and "restorable" are different claims.
$restore = $null
$restoreAgeH = $null
$rf = Join-Path $repo "data\alerts\mirror_restore_verify.json"
if (Test-Path $rf) {
    try {
        $restore = Get-Content $rf -Raw | ConvertFrom-Json
        $restoreAgeH = [math]::Round(((Get-Date) - [datetime]$restore.ts).TotalHours, 1)
    }
    catch {}
}
# No versioned backup exists (the tape subsystem was deleted 2026-07-07, commit 3ebca26e) and
# the nightly /MIR mirror is a replica rather than a backup. That is an ACCEPTED operator
# decision as of 2026-07-26 -- durability work waits until the model is profitable -- so it is
# deliberately NOT reported here. The cheap checks below stay because they already run.
if ($null -eq $restore) { $warns.Add("mirror has never been restore-verified - run scripts\ops\verify_mirror_restore.ps1") }
elseif ($mirrorPaused) {
    # Restorability cannot improve while the mirror is off, so this is a standing fact about the
    # frozen copy rather than a new event each morning. Said once, as a warn, and only when the
    # last verify actually failed.
    if (-not $restore.ok) {
        $warns.Add("the FROZEN off-host copy is not proven restorable - the last restore-verify (before the pause) found $($restore.problems) problem file(s)")
    }
}
elseif (-not $restore.ok) { $flags.Add("MIRROR RESTORE VERIFY FAILED: $($restore.problems) problem file(s) - the off-host copy may not be restorable") }
elseif ($restoreAgeH -gt 48) { $warns.Add("mirror restore-verify stale (${restoreAgeH}h) - restorability unproven since then") }

# ---- host stability (this machine loses power) ----
# Event-log forensics on 2026-07-25 found five unexpected shutdowns in 90 days, four of them
# bugcheck=0 / powerButton=0 -- abrupt power loss, not a crash. That is roughly one every
# three weeks against a 14-day contiguous streak, and none of them were ever visible here:
# the digest reported a healthy host either side of a 29-minute outage on 2026-07-21, which
# was day 1 of the current streak. An outage inside 12:00-18:00 ends the streak, so a recent
# one is a FLAG -- it means today's grade needs checking, not just today's process list.
$uptimeH = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1)
$lastCrash = $null
$crashes90 = 0
try {
    $ev = @(Get-WinEvent -FilterHashtable @{LogName = 'System'; Id = 41; StartTime = (Get-Date).AddDays(-90) } -MaxEvents 20 -EA SilentlyContinue)
    $crashes90 = $ev.Count
    if ($ev.Count -gt 0) { $lastCrash = $ev[0].TimeCreated }
}
catch {}
if ($lastCrash -and ((Get-Date) - $lastCrash).TotalHours -lt 24) {
    $flags.Add("UNEXPECTED SHUTDOWN $lastCrash - verify today's capture grade; an outage inside 12:00-18:00 ends the streak")
}
elseif ($crashes90 -ge 3) {
    $warns.Add("$crashes90 unexpected shutdowns in 90d (most recent $lastCrash) - power loss is the top uncontrolled streak risk; a UPS would remove it")
}

# ---- the watchdog itself (who watches the watcher) ----
# health_watchdog.ps1 is what alerts overnight while nobody is awake. If IT dies, every
# window-aware alert silently stops and the first symptom is a morning with no briefing.
# Nothing else here would notice, so check its heartbeat explicitly. It runs every 15 min.
$wd = $null
$wdAgeMin = $null
$wdf = Join-Path $repo "data\alerts\host_health_latest.json"
if (Test-Path $wdf) {
    try {
        $wd = Get-Content $wdf -Raw | ConvertFrom-Json
        $wdAgeMin = [math]::Round(((Get-Date) - [datetime]$wd.ts).TotalMinutes, 0)
    }
    catch {}
}
if ($null -eq $wd) { $flags.Add("health watchdog has never reported - overnight alerting is NOT running") }
elseif ($wdAgeMin -gt 45) { $flags.Add("health watchdog stale by ${wdAgeMin} min (runs every 15) - overnight alerting may be dead") }

# ---- post-integration documentation transaction ----
$documentationTransaction = $null
try {
    $documentationRaw = & $py -m weather.operations.documentation_transaction `
        --repo-root $repo status
    if ($LASTEXITCODE -eq 0 -and $documentationRaw) {
        $documentationTransaction = $documentationRaw | ConvertFrom-Json
    }
}
catch {}
if ($null -eq $documentationTransaction) {
    $flags.Add("documentation transaction state is unreadable")
}
elseif (-not [bool]$documentationTransaction.valid -or
    [string]$documentationTransaction.state -eq "INVALID") {
    $flags.Add("documentation transaction state is invalid: $($documentationTransaction.detail)")
}
elseif ([string]$documentationTransaction.state -eq "PENDING") {
    $detail = (
        "DOCUMENTATION TRANSACTION DUE: {0} integration(s), deadline {1}, pending {2}" -f
        $documentationTransaction.integration_count,
        $documentationTransaction.due_at_local,
        $documentationTransaction.pending_sha256
    )
    if ([bool]$documentationTransaction.overdue) { $flags.Add($detail) }
    else { $warns.Add($detail) }
}

# ---- active/last guarded quiet-window merge ----
# Merges happen at 01:30 while I am not watching; the outcome must be waiting in the morning.
if (([string]$reconciliationPublication.classification -ceq "ordinary") -and
    (Test-Path -LiteralPath $quietMarkerPath -PathType Leaf)) {
    try {
        $quietMarker = Get-Content -LiteralPath $quietMarkerPath -Raw | ConvertFrom-Json
        if ([string]$quietMarker.schema -ne "quiet_window_merge_in_progress_v0.1" -or
            [string]$quietMarker.expected_tip -notmatch '^[0-9a-f]{40}$' -or
            [string]$quietMarker.expected_baseline -notmatch '^[0-9a-f]{40}$' -or
            [string]::IsNullOrWhiteSpace([string]$quietMarker.phase)) {
            throw "quiet-merge marker schema or identity is invalid"
        }
        $quietMarkerAgeMinutes = ((Get-Date) - [datetime]$quietMarker.updated_at).TotalMinutes
        $quietMarkerDetail = "quiet-window merge marker remains at phase $($quietMarker.phase) for $([math]::Round($quietMarkerAgeMinutes, 1)) minutes (tip $($quietMarker.expected_tip))"
        if ($quietMarkerAgeMinutes -gt 30) {
            $flags.Add("STALE $quietMarkerDetail - run boot/merge recovery before closure or another merge")
        }
        else {
            $warns.Add($quietMarkerDetail)
        }
    }
    catch {
        $flags.Add("quiet-window merge in-progress marker is unreadable; treat production mutation as interrupted")
    }
}
$qw = $null
if (Test-Path $qwf) {
    try {
        $qw = Get-Content $qwf -Raw | ConvertFrom-Json
        $qwAgeH = ((Get-Date) - [datetime]$qw.ts).TotalHours
        # A rollback means capture did not survive the code roll -- streak-critical, and the
        # branch still needs a human decision. Never let that scroll past in a log file.
        # Special reconciliation reports are historical compatibility slots.
        # The exact active marker above is the sole publication authority, so an
        # old report cannot poison an unrelated later commit or contradict a
        # current pre-/post-dispatch state.
        $ordinaryReport = [string]$qw.operation_mode -cne
            "production_baseline_reconciliation_v0.1"
        if ($ordinaryReport -and $qw.stage -eq "rollback_recovery_failed" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge rollback recovery is UNPROVEN ($($qw.detail)) - protect capture and reconcile before another merge")
        }
        elseif ($ordinaryReport -and $qw.stage -eq "rolled_back" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge ROLLED BACK ($($qw.detail)) - capture did not recover; branch unmerged")
        }
        elseif ($ordinaryReport -and
            [string]$reconciliationPublication.classification -ceq "ordinary" -and
            $qw.stage -eq "merged_unpushed" -and $qwAgeH -lt 36) {
            $flags.Add("quiet-window merge committed locally but NOT pushed - obtain review, run WeatherOneShotPush, then reconcile the immutable attempt evidence")
        }
    }
    catch {}
}

# ---- alerts ----
$alertLast = $null
$af = Join-Path $repo "data\alerts\streak_capture_alerts.jsonl"
if (Test-Path $af) {
    $l = Get-Content $af -Tail 1
    if ($l) {
        try {
            $j = $l | ConvertFrom-Json
            # Show the AGE. Without it a two-day-old AT_RISK reads as current alarm, which is
            # both frightening and wrong -- the entry is historical the moment the day recovers.
            $alertTime = [datetime]$j.ts
            $ageH = ((Get-Date) - $alertTime).TotalHours
            $historicalCaptureDay = $alertTime.Date -lt (Get-Date).Date
            $alertLast = "{0}  {1}  ({2:N0}h ago{3})" -f $j.ts, $j.level, $ageH,
                $(if ($historicalCaptureDay -or $ageH -ge 24) { ", historical" } else { "" })
            # The capture grade closes by local calendar day. Yesterday's final
            # AT_RISK is evidence in the ledger, not a live alarm today.
            if (-not $historicalCaptureDay -and $ageH -lt 24) {
                $flags.Add("capture alert raised today: $alertLast")
            }
        }
        catch {}
    }
}

# No task/integration compatibility branch may turn an active incident marker
# back into ordinary retry advice. Exact acknowledgement suppresses stale task
# chatter; every other incident state preserves the anomaly under the watchdog's
# reconciliation-specific no-retry action.
if ([string]$reconciliationPublication.classification -cne "ordinary") {
    $protectedFlags = New-Object System.Collections.Generic.List[string]
    foreach ($flagText in @($flags)) {
        if ([string]$flagText -notmatch 'WeatherOneShotPush' -or
            [string]$flagText -match '^RECONCILIATION_PUBLICATION_') {
            $protectedFlags.Add([string]$flagText)
        }
        elseif ([string]$reconciliationPublication.classification -cne "acknowledged") {
            $protectedFlags.Add(
                "RECONCILIATION_PUBLICATION_RELATED_TASK_STATE: an additional WeatherOneShotPush task anomaly was observed; the active marker owns publication, so preserve evidence and do not manually invoke or retry"
            )
        }
    }
    $protectedWarns = New-Object System.Collections.Generic.List[string]
    foreach ($warnText in @($warns)) {
        if ([string]$warnText -notmatch 'WeatherOneShotPush') {
            $protectedWarns.Add([string]$warnText)
        }
        elseif ([string]$reconciliationPublication.classification -cne "acknowledged") {
            $protectedWarns.Add(
                "RECONCILIATION_PUBLICATION_RELATED_TASK_STATE: WeatherOneShotPush has additional task history; the active marker owns publication and manual invocation or retry is forbidden"
            )
        }
    }
    $flags = $protectedFlags
    $warns = $protectedWarns
}

# ---- verdict ----
$verdict = if ($flags.Count -gt 0) { "ATTENTION" } else { "OK" }
$exitCode = if ($flags.Count -gt 0) { 2 } else { 0 }

# ---- render ----
$ts = Get-Date -Format "yyyy-MM-dd HH:mm"
# "no today_health" is NOT "already settled" -- that reads as a benign claim about a day
# nobody measured. Say which of the two it is; an unreadable state is not a passing state.
$todayStr = if ($null -eq $streak) { "UNKNOWN - streak checker did not run" }
elseif ($null -eq $today) { "no today_health from the streak checker" }
else { "{0}  ({1} caps, {2}min max gap)" -f ([string]$today.verdict).ToUpper(), $today.captures, $today.max_window_gap_min }
$capSummary = ($caps.Keys | ForEach-Object {
        $pri = if ($capState[$_].Count) { (($capState[$_] | Select-Object -Unique) -join ",") } else { "DOWN" }
        "{0}={1}" -f $_, $pri
    }) -join "   "
$alertStr = if ($alertLast) { $alertLast } else { "none" }

if ($Json) {
    [PSCustomObject]@{
        ts       = $ts; verdict = $verdict
        flags    = @($flags); warns = @($warns)
        streak   = @{ days = $streak.streak_days; target = $streak.target; start = $streak.streak_start;
            today = $todayStr; lock = $streak.projected_lock_date_if_all_clean;
            settled = $streak.most_recent_settled
        }
        capture  = $capState; capture_runtime = $captureRuntimeState
        execution_tape = $executionTapeState
        ram_free_gb = $freeRamGB; ram_total_gb = $totRamGB; disk_free_gb = $freeDiskGB
        disk     = @{ free_gb = $freeDiskGB; delta_gb_per_day = $diskDelta; days_left = $diskDaysLeft
            delta_48h_gb_per_day = $diskDelta48; days_left_48h = $diskDaysLeft48 }
        tiering  = $tieringState
        clock    = @{ service = $(if ($clockService) { [string]$clockService.Status } else { $null })
            synchronized = $clockSynchronized; source = $clockSource; sync_age_hours = $clockSyncAgeH
            last_sync = $(if ($clockLastSync) { $clockLastSync.ToString("o") } else { $null })
        }
        chain    = @{ status = $chainStatus; terminal = $chainTerm; failing_step = $chainFail; payload_blocked = $chainBlocked }
        git      = @{ unpushed = $unpushed; dirty = $dirtyCount; last = $lastCommit }
        reconciliation_publication = @{
            classification = [string]$reconciliationPublication.classification
            detail = [string]$reconciliationPublication.detail
            merge_commit = [string]$reconciliationPublication.merge_commit
            live_origin_master = [string]$reconciliationPublication.live_origin_master
            push_invocation_attempted = [bool]$reconciliationPublication.push_invocation_attempted
            publication_acknowledged = [bool]$reconciliationPublication.publication_acknowledged
            marker_present = [bool]$reconciliationPublication.marker_present
            manual_push_allowed = [bool]$reconciliationPublication.manual_push_allowed
        }
        mirror   = @{ ok = $(if ($mirror) { [bool]$mirror.ok } else { $null }); age_hours = $mirrorAgeH
            paused = $mirrorPaused
            restore_verified = $(if ($restore) { [bool]$restore.ok } else { $null })
            restore_verify_age_hours = $restoreAgeH
            restore_identical = $(if ($restore) { $restore.verified_identical } else { $null })
        }
        watchdog = @{ age_min = $wdAgeMin; verdict = $(if ($wd) { [string]$wd.verdict } else { $null }) }
        merge    = @{ stage = $(if ($qw) { [string]$qw.stage } else { $null }); ts = $(if ($qw) { [string]$qw.ts } else { $null }) }
        documentation = $documentationTransaction
        integration_attempts = @($integrationAttemptState | ForEach-Object {
                @{ attempt_id = $_.attempt_id; state = $_.state; expected_tip = $_.expected_tip
                    manifest_path = $_.manifest_path; recovery_dispatch = $_.recovery_dispatch
                    successor_attempt_id = $_.successor_attempt_id; task_state = $_.task_state
                    merge_task_state = $_.merge_task_state; suite_task_state = $_.suite_task_state
                    suite_last_run_time = $_.suite_last_run_time
                    suite_preflight_exists = $_.suite_preflight_exists
                    suite_running = $_.suite_running; suite_ran = $_.suite_ran
                    suite_started = $_.suite_started
                    suite_ran_without_receipt = $_.suite_ran_without_receipt
                    evidence_age_hours = $_.evidence_age_hours
                    suite_trigger_missed = $_.suite_trigger_missed
                    merge_receipt_missing_after_trigger = $_.merge_receipt_missing_after_trigger }
            })
        overnight_wakes = @($overnightWakeState | ForEach-Object {
                @{ task_name = $_.task_name; wake = $_.wake; runner_path = $_.runner_path
                    runner_sha256 = $_.runner_sha256; receipt_path = $_.receipt_path
                    receipt_present = $_.receipt_present; valid = $_.valid
                    correction_path = $_.correction_path
                    correction_applied = $_.correction_applied
                    status = $_.status; schema_version = $_.schema_version
                    classification = $_.classification; detail = $_.detail
                }
            })
        upcoming = @($upcoming | Sort-Object at | ForEach-Object {
                @{ name = $_.name; at = $_.at.ToString("yyyy-MM-dd HH:mm"); in_hours = $_.in_hours }
            })
        resilience = @{ reboot_pending = $rebootPending; auto_logon = ($autoLogon -eq "1");
            interactive_tasks = $interactiveTasks; uptime_hours = $uptimeH
            windows_update_au_options = $windowsUpdateAuOptions
            unattended_updates_blocked = ($windowsUpdateAuOptions -eq 2)
            unexpected_shutdowns_90d = $crashes90
            last_unexpected_shutdown = $(if ($lastCrash) { $lastCrash.ToString("o") } else { $null })
        }
        tasks_scanned = $taskCount; alert_last = $alertStr
    } | ConvertTo-Json -Depth 6
    exit $exitCode
}

$bar = "=" * 76
Write-Output $bar
Write-Output ("  WEATHER HOST STATUS   $ts          VERDICT: $verdict")
Write-Output $bar
Write-Output ("  STREAK    : {0}/{1}  day1 {2}    TODAY: {3}" -f $streak.streak_days, $streak.target, $streak.streak_start, $todayStr)
Write-Output ("              lock ~{0} if all clean   |  settled -> {1}" -f $streak.projected_lock_date_if_all_clean, $streak.most_recent_settled)
Write-Output ("  CAPTURE   : {0}" -f $capSummary)
$executionTapeSummary = if (-not $executionTapeState.armed) { "not armed" }
elseif (-not $executionTapeState.process_healthy) { "ARMED / UNHEALTHY" }
else { "{0}, price-path usable={1}" -f $executionTapeState.capture_state, $executionTapeState.price_path_usable }
Write-Output ("  EXEC TAPE : {0}" -f $executionTapeSummary)
$diskTrend = if ($null -eq $diskDelta) { "" }
elseif ($diskDelta -lt 0 -and $null -ne $diskDelta48) {
    "  (24h {0} GB/day, 48h {1} GB/day)" -f $diskDelta, $diskDelta48
}
elseif ($diskDelta -lt 0) { "  ({0} GB/day, ~{1}d left)" -f $diskDelta, $diskDaysLeft }
else { "  (+{0} GB/day)" -f $diskDelta }
Write-Output ("  RESOURCES : RAM {0}/{1} GB free    Disk C: {2} GB free{3}" -f $freeRamGB, $totRamGB, $freeDiskGB, $diskTrend)
$clockState = if ($clockSynchronized -eq $false) { "UNSYNCHRONIZED" }
elseif ($null -eq $clockLastSync) { "UNKNOWN" }
elseif ($clockService.Status -eq "Running" -and $clockSource) { "synced via $clockSource, $clockSyncAgeH h ago" }
else { "last valid sample $clockSyncAgeH h ago (trigger-start service $($clockService.Status))" }
Write-Output ("  CLOCK     : {0}" -f $clockState)
$chainNote = if ($chainTaskResult -eq "0x4B" -and $chain -and $chain.terminal) {
    "0x4B = protected-window deadline; durable terminal status verified"
}
elseif ($chainStatus -eq "critical" -and -not $chainFail) {
    "all steps OK - 'critical' is the readiness gate, expected pre-release"
}
elseif ($chainTaskResult -eq "0x2") {
    "0x2 = gates BLOCK, expected pre-release"
}
elseif ($chainTaskResult) {
    "$chainTaskResult = last scheduled result"
}
else { "scheduled result unavailable" }
Write-Output ("  CHAIN     : {0} / {1}   ({2})" -f $chainStatus, $chainTerm, $chainNote)
if ($chainFail) { Write-Output ("              step: {0}" -f $chainFail) }
if ($chainGate) { Write-Output ("              gate: {0}" -f $chainGate) }
if ($chainBlocked) { Write-Output ("              {0}" -f $chainBlocked) }
$mirrorStr = if ($null -eq $mirror) { "unreadable" }
elseif ($mirrorPaused) { "PAUSED by operator, frozen {0}h ago" -f $mirrorAgeH }
elseif ($mirror.ok) { "ok, {0}h ago" -f $mirrorAgeH }
else { "FAILED (exit $($mirror.robocopy_exit))" }
# While paused, the restore suffix would report a verify that can no longer change against a
# copy that can no longer change. The PAUSED string plus its warn already say it.
if ($mirrorPaused) { }
elseif ($restore) {
    $mirrorStr += if ($restore.ok) { " [restore-verified {0}/{1} {2}h ago]" -f $restore.verified_identical, $restore.checked, $restoreAgeH }
    else { " [RESTORE VERIFY FAILED]" }
}
else { $mirrorStr += " [never restore-verified]" }
Write-Output ("  OFF-HOST  : mirror {0}    |  reboot pending: {1}   logon-dependent tasks: {2}" -f $mirrorStr, $rebootPending, $interactiveTasks)
$crashStr = if ($lastCrash) { "{0} unexpected shutdown(s)/90d, last {1:MM-dd HH:mm}" -f $crashes90, $lastCrash } else { "no unexpected shutdowns in 90d" }
Write-Output ("  STABILITY : up {0}h   |  {1}" -f $uptimeH, $crashStr)
Write-Output ("  GIT       : {0} unpushed | {1} dirty | {2}" -f $unpushed, $dirtyCount, $lastCommit)
Write-Output ("  TASKS     : {0} Weather tasks scanned (anomalies -> FLAGS)" -f $taskCount)
if ($integrationAttemptState.Count -gt 0) {
    Write-Output "  ATTEMPTS  :"
    foreach ($attemptState in $integrationAttemptState) {
        Write-Output ("              {0}  {1}" -f $attemptState.attempt_id, $attemptState.state)
    }
}
$wdStr = if ($null -eq $wd) { "NEVER REPORTED" } else { "{0}, {1} min ago" -f ([string]$wd.verdict), $wdAgeMin }
$qwStr = if ($null -eq $qw) { "none" } else { "{0} ({1:yyyy-MM-dd HH:mm})" -f $qw.stage, ([datetime]$qw.ts) }
Write-Output ("  WATCHDOG  : {0}    |  last merge attempt: {1}" -f $wdStr, $qwStr)
$documentationStr = if ($null -eq $documentationTransaction) { "UNREADABLE" }
else {
    "{0}{1}" -f $documentationTransaction.state,
        $(if ($documentationTransaction.due_at_local) { " (due $($documentationTransaction.due_at_local))" } else { "" })
}
Write-Output ("  DOCS      : {0}" -f $documentationStr)
Write-Output ("  ALERTS    : last {0}" -f $alertStr)
if ($upcoming.Count -gt 0) {
    Write-Output "  ARMED     : (scheduled, not yet run)"
    foreach ($u in ($upcoming | Sort-Object at)) {
        Write-Output ("              {0:HH:mm} (+{1}h)  {2}" -f $u.at, $u.in_hours, $u.name)
    }
}
if ($flags.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  FLAGS (need attention):"
    foreach ($f in $flags) { Write-Output "    ! $f" }
}
if ($warns.Count -gt 0) {
    Write-Output ("  " + ("-" * 74))
    Write-Output "  notes (standing / low-priority):"
    foreach ($w in $warns) { Write-Output "    - $w" }
}
Write-Output $bar
exit $exitCode
