Set-StrictMode -Version Latest

$script:WeatherIntegrationAttemptManifestSchema = "weather_integration_attempt_manifest_v1"
$script:WeatherIntegrationAttemptSuiteReceiptSchema = "weather_integration_attempt_suite_receipt_v1"
$script:WeatherIntegrationAttemptMergeReceiptSchema = "weather_integration_attempt_merge_receipt_v1"
$script:WeatherIntegrationAttemptRegistrationReceiptSchema = "weather_integration_attempt_registration_receipt_v1"
$script:WeatherIntegrationAttemptClosureReceiptSchema = "weather_integration_attempt_closure_receipt_v1"

function Get-WeatherIntegrationFileSha256 {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-WeatherIntegrationSharedText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required file is missing: $Path"
    }

    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $reader = New-Object System.IO.StreamReader($stream)
        try {
            return $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Read-WeatherIntegrationSharedJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $text = Read-WeatherIntegrationSharedText -Path $Path
    try {
        return $text | ConvertFrom-Json
    }
    catch {
        throw "Could not parse JSON from ${Path}: $($_.Exception.Message)"
    }
}

function Write-WeatherIntegrationImmutableJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [object]$Payload
    )

    if (Test-Path -LiteralPath $Path) {
        throw "Immutable evidence already exists and will not be replaced: $Path"
    }

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        throw "Evidence parent directory is missing: $parent"
    }

    $temporaryPath = "$Path.$PID.tmp"
    if (Test-Path -LiteralPath $temporaryPath) {
        throw "Temporary evidence path already exists: $temporaryPath"
    }

    $json = $Payload | ConvertTo-Json -Depth 20
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($temporaryPath, $json + [Environment]::NewLine, $encoding)
    try {
        Move-Item -LiteralPath $temporaryPath -Destination $Path -ErrorAction Stop
    }
    catch {
        if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
        throw
    }
}

function Resolve-WeatherIntegrationPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

function Test-WeatherIntegrationPathEqual {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Left,
        [Parameter(Mandatory = $true)]
        [string]$Right
    )

    $leftPath = Resolve-WeatherIntegrationPath -Path $Left
    $rightPath = Resolve-WeatherIntegrationPath -Path $Right
    return [string]::Equals($leftPath, $rightPath, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-WeatherIntegrationEvidencePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$AttemptRoot,
        [Parameter(Mandatory = $true)]
        [string]$ActualPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedName
    )

    $expectedPath = Join-Path (Resolve-WeatherIntegrationPath -Path $AttemptRoot) $ExpectedName
    if (-not (Test-WeatherIntegrationPathEqual -Left $ActualPath -Right $expectedPath)) {
        throw "Attempt evidence path for $ExpectedName is not canonical. Expected $expectedPath; got $ActualPath"
    }
    return $expectedPath
}

function Assert-WeatherIntegrationAttemptManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ManifestPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedSha256
    )

    $resolvedManifestPath = Resolve-WeatherIntegrationPath -Path $ManifestPath
    $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $resolvedManifestPath
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected manifest SHA256 must be exactly 64 hexadecimal characters."
    }
    if ($actualSha256 -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Attempt manifest hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }

    $manifest = Read-WeatherIntegrationSharedJson -Path $resolvedManifestPath
    if ([string]$manifest.schema -ne $script:WeatherIntegrationAttemptManifestSchema) {
        throw "Unsupported integration-attempt manifest schema: $($manifest.schema)"
    }
    if ([string]$manifest.attempt_id -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
        throw "Attempt id is missing or unsafe: $($manifest.attempt_id)"
    }
    if ([string]$manifest.expected_tip -notmatch '^[0-9a-f]{40}$') {
        throw "Attempt expected tip must be a lowercase 40-character commit id."
    }
    if ([string]$manifest.branch_ref -notmatch '^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$') {
        throw "Attempt branch ref is missing or unsafe: $($manifest.branch_ref)"
    }
    if ([string]::IsNullOrWhiteSpace([string]$manifest.authorization.review_reference)) {
        throw "Attempt is missing its review reference."
    }
    $expectedSuiteTaskName = "WeatherIntegrationSuite_$($manifest.attempt_id)"
    $expectedMergeTaskName = "WeatherIntegrationMerge_$($manifest.attempt_id)"
    if ([string]$manifest.schedule.suite_task_name -ne $expectedSuiteTaskName -or
        [string]$manifest.schedule.merge_task_name -ne $expectedMergeTaskName) {
        throw "Attempt task names are not the canonical names derived from attempt_id."
    }
    try {
        $suiteAt = [datetime]::Parse([string]$manifest.schedule.suite_at_local)
        $mergeAt = [datetime]::Parse([string]$manifest.schedule.merge_at_local)
    }
    catch {
        throw "Attempt schedule timestamps are invalid."
    }
    $suiteMinute = ($suiteAt.Hour * 60) + $suiteAt.Minute
    $mergeMinute = ($mergeAt.Hour * 60) + $mergeAt.Minute
    if ($suiteAt.Date -ne $mergeAt.Date -or
        $suiteMinute -lt 30 -or $suiteMinute -ge 540 -or
        $mergeMinute -lt 60 -or $mergeMinute -ge 220 -or
        ($mergeAt - $suiteAt) -lt [TimeSpan]::FromMinutes(30)) {
        throw "Attempt schedule violates the suite or quiet-window contract."
    }
    if ([string]$manifest.baseline.master -notmatch '^[0-9a-f]{40}$' -or
        [string]$manifest.baseline.master -ne [string]$manifest.baseline.origin_master) {
        throw "Attempt baseline does not bind equal production and origin tips."
    }

    $attemptRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.attempt_root)
    $manifestParent = Resolve-WeatherIntegrationPath -Path (Split-Path -Parent $resolvedManifestPath)
    if (-not (Test-WeatherIntegrationPathEqual -Left $attemptRoot -Right $manifestParent)) {
        throw "Manifest attempt_root does not match the manifest parent directory."
    }
    if (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.repo_root) -Right ([string]$manifest.worktree_root)) {
        throw "An integration attempt may not use the production repository as its suite worktree."
    }

    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.preflight_log) -ExpectedName "preflight.log" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.full_suite_log) -ExpectedName "full-suite.log" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.suite_receipt) -ExpectedName "suite-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.merge_receipt) -ExpectedName "merge-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.quiet_merge_report) -ExpectedName "quiet-merge-report.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.registration_receipt) -ExpectedName "registration-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.closure_receipt) -ExpectedName "closure-receipt.json" | Out-Null

    return [pscustomobject]@{
        Manifest = $manifest
        ManifestPath = $resolvedManifestPath
        ManifestSha256 = $actualSha256
        AttemptRoot = $attemptRoot
    }
}

function Assert-WeatherIntegrationOrchestrationFiles {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $expectedFiles = [ordered]@{
        contract = Join-Path $repoRoot "scripts\ops\integration_attempt_contract.ps1"
        attempt_creator = Join-Path $repoRoot "scripts\ops\new_integration_attempt.ps1"
        attempt_registrar = Join-Path $repoRoot "scripts\ops\register_integration_attempt.ps1"
        attempt_closer = Join-Path $repoRoot "scripts\ops\close_integration_attempt.ps1"
        bounded_suite = Join-Path $repoRoot "scripts\ops\bounded_worktree_test_suite.ps1"
        attempt_suite = Join-Path $repoRoot "scripts\ops\integration_attempt_suite.ps1"
        attempt_merge = Join-Path $repoRoot "scripts\ops\integration_attempt_merge.ps1"
        attempt_success_gate = Join-Path $repoRoot "scripts\ops\assert_integration_attempt_success.ps1"
        quiet_merge = Join-Path $repoRoot "scripts\ops\quiet_window_merge.ps1"
    }
    foreach ($name in $expectedFiles.Keys) {
        $record = $manifest.orchestration.$name
        if ($null -eq $record) {
            throw "Attempt manifest is missing the orchestration binding for $name."
        }
        $expectedPath = [string]$expectedFiles[$name]
        if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$record.path) -Right $expectedPath)) {
            throw "Attempt orchestration path for $name is not canonical."
        }
        $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $expectedPath
        if ($actualSha256 -ne [string]$record.sha256) {
            throw "Attempt orchestration file changed after freeze: $name"
        }
    }
}

function Assert-WeatherIntegrationSuiteReceipt {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.suite_receipt
    $receipt = Read-WeatherIntegrationSharedJson -Path $receiptPath
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptSuiteReceiptSchema) {
        throw "Unsupported integration-attempt suite receipt schema: $($receipt.schema)"
    }
    if ([string]$receipt.status -ne "PASS") {
        throw "The integration-attempt suite did not pass. Receipt status: $($receipt.status)"
    }
    if ([string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Suite receipt is not bound to the selected manifest hash."
    }
    if ([string]$receipt.expected_tip -ne [string]$manifest.expected_tip) {
        throw "Suite receipt expected tip does not match the manifest."
    }
    if ([string]$receipt.branch_ref -ne [string]$manifest.branch_ref) {
        throw "Suite receipt branch does not match the manifest."
    }
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.worktree_root) -Right ([string]$manifest.worktree_root))) {
        throw "Suite receipt worktree does not match the manifest."
    }
    if (-not [bool]$receipt.full_suite_started -or
        [bool]$receipt.credential_value_read -or
        [bool]$receipt.live_exchange_mutation_attempted) {
        throw "Suite receipt is missing full-suite proof or violates the attempt safety boundary."
    }

    foreach ($logName in @("preflight", "full_suite")) {
        $logRecord = $receipt.logs.$logName
        if ($null -eq $logRecord) {
            throw "Suite receipt is missing the $logName log binding."
        }
        $logPath = [string]$logRecord.path
        $expectedPath = if ($logName -eq "preflight") { [string]$manifest.evidence.preflight_log } else { [string]$manifest.evidence.full_suite_log }
        if (-not (Test-WeatherIntegrationPathEqual -Left $logPath -Right $expectedPath)) {
            throw "Suite receipt $logName log path does not match the manifest."
        }
        $actualLogSha256 = Get-WeatherIntegrationFileSha256 -Path $logPath
        if ($actualLogSha256 -ne [string]$logRecord.sha256) {
            throw "Suite receipt $logName log hash does not match the current file."
        }
        if ([int]$logRecord.exit_code -ne 0) {
            throw "Suite receipt $logName phase did not exit successfully."
        }
    }
    if ([string]$receipt.logs.preflight.verdict -notlike "*VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized") {
        throw "Suite receipt preflight verdict is not exact."
    }
    if ([string]$receipt.logs.full_suite.verdict -notmatch 'VERDICT: ALL CHUNKS PASSED \([0-9]+/[0-9]+\); exact tip eligible for separate reviewed merge$') {
        throw "Suite receipt full-suite verdict is not exact."
    }

    $scriptBindings = [ordered]@{
        bounded_suite = $manifest.orchestration.bounded_suite
        integration_suite = $manifest.orchestration.attempt_suite
    }
    foreach ($scriptName in $scriptBindings.Keys) {
        $manifestScript = $scriptBindings[$scriptName]
        $receiptScript = $receipt.scripts.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "Suite receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $receiptPath
    }
}

function Assert-WeatherIntegrationMergeReceipt {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedReceiptSha256
    )

    if ($ExpectedReceiptSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected merge receipt SHA256 must be exactly 64 hexadecimal characters."
    }
    $manifest = $AttemptContract.Manifest
    $receiptPath = [string]$manifest.evidence.merge_receipt
    $actualReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $receiptPath
    if ($actualReceiptSha256 -ne $ExpectedReceiptSha256.ToLowerInvariant()) {
        throw "Merge receipt hash mismatch. Expected $ExpectedReceiptSha256; got $actualReceiptSha256"
    }

    $receipt = Read-WeatherIntegrationSharedJson -Path $receiptPath
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema) {
        throw "Unsupported integration-attempt merge receipt schema: $($receipt.schema)"
    }
    if ([string]$receipt.status -ne "PASS") {
        throw "Integration-attempt merge receipt is not PASS: $($receipt.status)"
    }
    if ([string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$manifest.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$manifest.branch_ref) {
        throw "Merge receipt identity does not match the immutable attempt manifest."
    }
    if (-not [bool]$receipt.origin_master_verified -or
        -not [bool]$receipt.source_tip_integrated -or
        -not [bool]$receipt.capture_recovery_proved -or
        -not [bool]$receipt.documentation_transaction_recorded) {
        throw "Merge receipt is missing one or more required integration proofs."
    }
    if ([string]$receipt.production_head -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.production_head -ne [string]$receipt.origin_master) {
        throw "Merge receipt does not bind equal production and origin tips."
    }
    if ([bool]$receipt.credential_value_read -or [bool]$receipt.live_exchange_mutation_attempted) {
        throw "Merge receipt violates the no-credential/no-live-exchange boundary."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $manifest.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "Merge receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    $quietReportPath = [string]$manifest.evidence.quiet_merge_report
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.quiet_merge_report.path) -Right $quietReportPath)) {
        throw "Merge receipt quiet-report path does not match the attempt manifest."
    }
    $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $quietReportPath
    if ($quietReportSha256 -ne [string]$receipt.quiet_merge_report.sha256) {
        throw "Immutable quiet-merge report hash does not match the merge receipt."
    }
    $quietReport = Read-WeatherIntegrationSharedJson -Path $quietReportPath
    if (-not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.branch -ne [string]$manifest.branch_ref) {
        throw "Immutable quiet-merge report does not prove the frozen source tip was pushed."
    }

    $suiteReceiptPath = [string]$manifest.evidence.suite_receipt
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.suite_receipt_path) -Right $suiteReceiptPath)) {
        throw "Merge receipt suite-receipt path does not match the attempt manifest."
    }
    $suiteReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $suiteReceiptPath
    if ($suiteReceiptSha256 -ne [string]$receipt.suite_receipt_sha256) {
        throw "Suite receipt changed after the merge gate consumed it."
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = $actualReceiptSha256
        QuietReport = $quietReport
        QuietReportSha256 = $quietReportSha256
    }
}
