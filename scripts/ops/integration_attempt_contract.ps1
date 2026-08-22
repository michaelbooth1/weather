Set-StrictMode -Version Latest

$script:WeatherIntegrationAttemptManifestSchema = "weather_integration_attempt_manifest_v1"
$script:WeatherIntegrationAttemptSuiteReceiptSchema = "weather_integration_attempt_suite_receipt_v1"
$script:WeatherIntegrationAttemptMergeReceiptSchema = "weather_integration_attempt_merge_receipt_v1"
$script:WeatherIntegrationAttemptRegistrationReceiptSchema = "weather_integration_attempt_registration_receipt_v1"
$script:WeatherIntegrationAttemptRegistrationIntentSchema = "weather_integration_attempt_registration_intent_v1"
$script:WeatherIntegrationAttemptTaskBindingContract = "weather_integration_attempt_exact_task_binding_v1"
$script:WeatherIntegrationAttemptClosureReceiptSchema = "weather_integration_attempt_closure_receipt_v1"
$script:WeatherIntegrationAttemptSuccessorClaimSchema = "weather_integration_attempt_successor_claim_v1"
$script:WeatherIntegrationAttemptRecoveryDispatchSchema = "weather_integration_attempt_recovery_dispatch_v1"
$script:WeatherIntegrationAttemptReconciliationReceiptSchema = "weather_integration_attempt_reconciliation_receipt_v1"

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

function Enter-WeatherIntegrationControlMutex {
    param(
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)]
        [ValidateSet("heavy_workload.lock", "integration_attempt_terminal.lock")]
        [string]$LockLeaf,
        [Parameter(Mandatory = $true)][string]$Owner
    )

    $logRoot = Join-Path (Resolve-WeatherIntegrationPath -Path $RepositoryRoot) "data\logs"
    if (-not (Test-Path -LiteralPath $logRoot -PathType Container)) {
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    }
    $lockPath = Join-Path $logRoot $LockLeaf
    try {
        $stream = [IO.File]::Open(
            $lockPath,
            [IO.FileMode]::OpenOrCreate,
            [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::Read
        )
    }
    catch [IO.IOException] { return $null }
    try {
        $stream.SetLength(0)
        $payload = [ordered]@{
            schema = "weather_integration_control_mutex_v1"
            owner = $Owner
            pid = $PID
            acquired_at = (Get-Date).ToUniversalTime().ToString("o")
        }
        $writer = New-Object IO.StreamWriter(
            $stream,
            (New-Object Text.UTF8Encoding($false)),
            1024,
            $true
        )
        try {
            $writer.Write(($payload | ConvertTo-Json -Compress))
            $writer.Flush()
            $stream.Flush()
        }
        finally { $writer.Dispose() }
        return [pscustomobject]@{ Path = $lockPath; Stream = $stream }
    }
    catch {
        $stream.Dispose()
        throw
    }
}

function Exit-WeatherIntegrationControlMutex {
    param([AllowNull()][object]$Mutex)
    if ($null -ne $Mutex -and $null -ne $Mutex.Stream) {
        $Mutex.Stream.Dispose()
    }
}

function Assert-WeatherIntegrationAttemptNotTerminal {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    $attempt = $AttemptContract.Manifest
    foreach ($terminal in @(
        [pscustomobject]@{ Label = "closure"; Path = [string]$attempt.evidence.closure_receipt },
        [pscustomobject]@{ Label = "reconciliation"; Path = [string]$attempt.evidence.reconciliation_receipt }
    )) {
        if (Test-Path -LiteralPath $terminal.Path) {
            throw "$Operation is forbidden because the attempt already has a terminal $($terminal.Label) receipt: $($terminal.Path)"
        }
    }
}

function Get-WeatherIntegrationLogVerdict {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $lines = @(
        (Read-WeatherIntegrationSharedText -Path $Path) -split "`r?`n" |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    )
    if ($lines.Count -eq 0) {
        throw "Attempt log is empty: $Path"
    }
    return [string]$lines[-1]
}

function Assert-WeatherIntegrationFullSuiteVerdict {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Verdict,
        [ValidateRange(0, 100000)]
        [int]$ExpectedChunkCount = 0
    )

    $match = [regex]::Match(
        $Verdict,
        '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}  VERDICT: ALL CHUNKS PASSED \((?<passed>[0-9]+)/(?<planned>[0-9]+)\); exact tip eligible for separate reviewed merge$'
    )
    if (-not $match.Success) {
        throw "Full suite log is missing its exact PASS verdict."
    }
    $passed = [int]$match.Groups["passed"].Value
    $planned = [int]$match.Groups["planned"].Value
    if ($passed -le 0 -or $passed -ne $planned -or
        ($ExpectedChunkCount -gt 0 -and $planned -ne $ExpectedChunkCount)) {
        throw "Full suite PASS verdict has an invalid chunk ratio: $passed/$planned"
    }
    return $planned
}

function Assert-WeatherIntegrationPreflightVerdict {
    param(
        [Parameter(Mandatory = $true)][string]$Verdict
    )

    if ($Verdict -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}  VERDICT: INTEGRATION PREFLIGHT PASSED; full suite not run and merge is not authorized$') {
        throw "Integration preflight log is missing its exact PASS verdict."
    }
}

function Assert-WeatherIntegrationFullSuiteLogPlan {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateRange(1, 1000000)][int]$ExpectedTestFileCount,
        [Parameter(Mandatory = $true)][ValidateRange(1, 25)][int]$ExpectedMaxFilesPerChunk,
        [Parameter(Mandatory = $true)][ValidateRange(1, 100000)][int]$ExpectedChunkCount
    )

    $text = Read-WeatherIntegrationSharedText -Path $Path
    $matches = [regex]::Matches(
        $text,
        '(?m)planned chunks=(?<chunks>[0-9]+) files=(?<files>[0-9]+) max_files=(?<max>[0-9]+)\r?$'
    )
    if ($matches.Count -ne 1) {
        throw "Full suite log must contain exactly one immutable test plan."
    }
    $match = $matches[0]
    $chunks = [int]$match.Groups["chunks"].Value
    $files = [int]$match.Groups["files"].Value
    $maxFiles = [int]$match.Groups["max"].Value
    if ($files -ne $ExpectedTestFileCount -or
        $maxFiles -ne $ExpectedMaxFilesPerChunk -or
        $chunks -ne $ExpectedChunkCount) {
        throw "Full suite test plan does not match the frozen manifest: chunks=$chunks files=$files max_files=$maxFiles"
    }
    return [pscustomobject]@{ Chunks = $chunks; Files = $files; MaxFilesPerChunk = $maxFiles }
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
        # File.Move is one same-volume create-if-absent operation. It never
        # replaces an existing destination, including under concurrent claimers.
        [System.IO.File]::Move($temporaryPath, $Path)
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

function ConvertTo-WeatherIntegrationScheduledTaskArgumentString {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Tokens
    )

    $encoded = foreach ($token in $Tokens) {
        $value = [string]$token
        if ($value.Contains('"')) {
            throw "Integration-attempt task action tokens may not contain a double quote: $value"
        }
        if ($value -match '\s') {
            if ($value.EndsWith('\')) {
                throw "A quoted integration-attempt task action token may not end in a backslash: $value"
            }
            '"{0}"' -f $value
        }
        elseif ($value.Length -eq 0) {
            '""'
        }
        else {
            $value
        }
    }
    return ($encoded -join " ")
}

function Get-WeatherIntegrationRegistrationIntentPath {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $expectedPath = Join-Path (Resolve-WeatherIntegrationPath -Path $AttemptContract.AttemptRoot) "registration-intent.json"
    $pathProperty = $AttemptContract.Manifest.evidence.PSObject.Properties["registration_intent"]
    if ($null -ne $pathProperty -and
        -not [string]::IsNullOrWhiteSpace([string]$pathProperty.Value) -and
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$pathProperty.Value) -Right $expectedPath)) {
        throw "Attempt registration-intent path is not canonical. Expected $expectedPath"
    }
    return Resolve-WeatherIntegrationPath -Path $expectedPath
}

function Get-WeatherIntegrationExpectedTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][string]$UserId,
        [string]$PowerShellExecutable = (Join-Path $PSHOME "powershell.exe")
    )

    if ([string]::IsNullOrWhiteSpace($UserId)) {
        throw "Integration-attempt task binding requires a non-empty principal user id."
    }
    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    if ($Role -eq "suite") {
        $taskName = [string]$manifest.schedule.suite_task_name
        $atLocal = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.suite_at_local) `
            -Label "suite_at_local"
        $scriptPath = Join-Path $repoRoot "scripts\ops\integration_attempt_suite.ps1"
        $scriptRecord = $manifest.orchestration.attempt_suite
        $executionTimeLimit = "PT8H"
        $description = "Immutable integration attempt $($manifest.attempt_id): preflight and full suite"
    }
    else {
        $taskName = [string]$manifest.schedule.merge_task_name
        $atLocal = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.merge_at_local) `
            -Label "merge_at_local"
        $scriptPath = Join-Path $repoRoot "scripts\ops\integration_attempt_merge.ps1"
        $scriptRecord = $manifest.orchestration.attempt_merge
        $executionTimeLimit = "PT4H"
        $description = "Immutable integration attempt $($manifest.attempt_id): guarded merge"
    }
    if ($null -eq $scriptRecord -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$scriptRecord.path) -Right $scriptPath) -or
        [string]$scriptRecord.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Attempt manifest is missing the canonical $Role task script binding."
    }

    $tokens = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-File", $scriptPath,
        "-ManifestPath", $AttemptContract.ManifestPath,
        "-ExpectedManifestSha256", $AttemptContract.ManifestSha256
    )
    return [pscustomobject][ordered]@{
        task_name = $taskName
        task_path = "\"
        description = $description
        action_id = ""
        executable = Resolve-WeatherIntegrationPath -Path $PowerShellExecutable
        arguments = ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens $tokens
        working_directory = $repoRoot
        script_sha256 = [string]$scriptRecord.sha256
        trigger = [pscustomobject][ordered]@{
            type = "Once"
            id = ""
            at_local = $atLocal.ToString("o")
            enabled = $true
            end_boundary = ""
            random_delay = ""
            execution_time_limit = ""
            repetition_interval = ""
            repetition_duration = ""
            repetition_stop_at_duration_end = $false
        }
        settings = [pscustomobject][ordered]@{
            multiple_instances = "IgnoreNew"
            compatibility = "Win7"
            allow_demand_start = $true
            allow_hard_terminate = $true
            delete_expired_task_after = ""
            execution_time_limit = $executionTimeLimit
            hidden = $false
            priority = 7
            restart_count = 0
            restart_interval = ""
            wake_to_run = $true
            start_when_available = $false
            allow_start_if_on_batteries = $true
            stop_if_going_on_batteries = $false
            run_only_if_idle = $false
            run_only_if_network_available = $false
            disallow_start_on_remote_app_session = $false
            use_unified_scheduling_engine = $true
            volatile = $false
            maintenance_settings = ""
            idle_duration = "PT10M"
            idle_restart = $false
            idle_stop_on_end = $true
            idle_wait_timeout = "PT1H"
            network_id = ""
            network_name = ""
        }
    }
}

function Assert-WeatherIntegrationRequiredProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in $Names) {
        if ($null -eq $Object.PSObject.Properties[$name]) {
            throw "$Label is missing required property: $name"
        }
    }
}

function Assert-WeatherIntegrationBooleanProperties {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string[]]$Names,
        [Parameter(Mandatory = $true)][string]$Label
    )

    foreach ($name in $Names) {
        $property = $Object.PSObject.Properties[$name]
        if ($null -eq $property -or $property.Value -isnot [bool]) {
            throw "$Label property must be a JSON boolean: $name"
        }
    }
}

function Assert-WeatherIntegrationTaskBindingRecord {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][object]$Record,
        [Parameter(Mandatory = $true)][string]$UserId
    )

    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record `
        -Names @("task_name", "task_path", "description", "action_id", "executable", "arguments", "working_directory", "script_sha256", "trigger", "settings") `
        -Label "$Role task binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record.trigger `
        -Names @("type", "id", "at_local", "enabled", "end_boundary", "random_delay", "execution_time_limit", "repetition_interval", "repetition_duration", "repetition_stop_at_duration_end") `
        -Label "$Role trigger binding"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $Record.settings `
        -Names @("multiple_instances", "compatibility", "allow_demand_start", "allow_hard_terminate", "delete_expired_task_after", "execution_time_limit", "hidden", "priority", "restart_count", "restart_interval", "wake_to_run", "start_when_available", "allow_start_if_on_batteries", "stop_if_going_on_batteries", "run_only_if_idle", "run_only_if_network_available", "disallow_start_on_remote_app_session", "use_unified_scheduling_engine", "volatile", "maintenance_settings", "idle_duration", "idle_restart", "idle_stop_on_end", "idle_wait_timeout", "network_id", "network_name") `
        -Label "$Role settings binding"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $Record.trigger `
        -Names @("enabled", "repetition_stop_at_duration_end") `
        -Label "$Role trigger binding"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $Record.settings `
        -Names @("allow_demand_start", "allow_hard_terminate", "hidden", "wake_to_run", "start_when_available", "allow_start_if_on_batteries", "stop_if_going_on_batteries", "run_only_if_idle", "run_only_if_network_available", "disallow_start_on_remote_app_session", "use_unified_scheduling_engine", "volatile", "idle_restart", "idle_stop_on_end") `
        -Label "$Role settings binding"
    $expected = Get-WeatherIntegrationExpectedTaskBinding `
        -AttemptContract $AttemptContract `
        -Role $Role `
        -UserId $UserId
    if ([string]$Record.task_name -ne [string]$expected.task_name -or
        [string]$Record.task_path -ne [string]$expected.task_path -or
        [string]$Record.description -ne [string]$expected.description -or
        -not [string]::IsNullOrEmpty([string]$Record.action_id) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$Record.executable) -Right ([string]$expected.executable)) -or
        [string]$Record.arguments -ne [string]$expected.arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$Record.working_directory) -Right ([string]$expected.working_directory)) -or
        [string]$Record.script_sha256 -ne [string]$expected.script_sha256) {
        throw "$Role registration evidence does not bind the exact task identity and action."
    }
    if ([string]$Record.trigger.type -ne "Once" -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.id) -or
        [string]$Record.trigger.at_local -ne [string]$expected.trigger.at_local -or
        -not [bool]$Record.trigger.enabled -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.end_boundary) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.random_delay) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.execution_time_limit) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.repetition_interval) -or
        -not [string]::IsNullOrEmpty([string]$Record.trigger.repetition_duration) -or
        [bool]$Record.trigger.repetition_stop_at_duration_end) {
        throw "$Role registration evidence does not bind the exact one-shot trigger."
    }
    if ([string]$Record.settings.multiple_instances -ne "IgnoreNew" -or
        [string]$Record.settings.compatibility -ne "Win7" -or
        -not [bool]$Record.settings.allow_demand_start -or
        -not [bool]$Record.settings.allow_hard_terminate -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.delete_expired_task_after) -or
        [string]$Record.settings.execution_time_limit -ne [string]$expected.settings.execution_time_limit -or
        [bool]$Record.settings.hidden -or
        [int]$Record.settings.priority -ne 7 -or
        [int]$Record.settings.restart_count -ne 0 -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.restart_interval) -or
        -not [bool]$Record.settings.wake_to_run -or
        [bool]$Record.settings.start_when_available -or
        -not [bool]$Record.settings.allow_start_if_on_batteries -or
        [bool]$Record.settings.stop_if_going_on_batteries -or
        [bool]$Record.settings.run_only_if_idle -or
        [bool]$Record.settings.run_only_if_network_available -or
        [bool]$Record.settings.disallow_start_on_remote_app_session -or
        -not [bool]$Record.settings.use_unified_scheduling_engine -or
        [bool]$Record.settings.volatile -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.maintenance_settings) -or
        [string]$Record.settings.idle_duration -ne "PT10M" -or
        [bool]$Record.settings.idle_restart -or
        -not [bool]$Record.settings.idle_stop_on_end -or
        [string]$Record.settings.idle_wait_timeout -ne "PT1H" -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.network_id) -or
        -not [string]::IsNullOrEmpty([string]$Record.settings.network_name)) {
        throw "$Role registration evidence does not bind the required fail-closed task settings."
    }
    return $expected
}

function Assert-WeatherIntegrationRegistrationIntent {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [string]$ExpectedSha256 = ""
    )

    $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    $actualSha256 = Get-WeatherIntegrationFileSha256 -Path $intentPath
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and
        ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$' -or
            $actualSha256 -ne $ExpectedSha256.ToLowerInvariant())) {
        throw "Registration intent hash mismatch. Expected $ExpectedSha256; got $actualSha256"
    }
    $intent = Read-WeatherIntegrationSharedJson -Path $intentPath
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent `
        -Names @("schema", "status", "binding_contract", "attempt_id", "intent_path", "manifest_path", "manifest_sha256", "prepared_at_local", "principal", "suite", "merge", "safety") `
        -Label "Registration intent"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.principal `
        -Names @("user_id", "logon_type", "run_level", "id", "display_name", "group_id", "process_token_sid_type", "required_privileges") `
        -Label "Registration intent principal"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $intent.safety `
        -Names @("authority", "credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration intent safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $intent.safety `
        -Names @("credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration intent safety boundary"
    if ([string]$intent.schema -ne $script:WeatherIntegrationAttemptRegistrationIntentSchema -or
        [string]$intent.status -ne "PREPARED" -or
        [string]$intent.binding_contract -ne $script:WeatherIntegrationAttemptTaskBindingContract -or
        [string]$intent.attempt_id -ne [string]$AttemptContract.Manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$intent.intent_path) -Right $intentPath) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$intent.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$intent.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Registration intent does not bind this exact immutable attempt."
    }
    if ([string]::IsNullOrWhiteSpace([string]$intent.principal.user_id) -or
        [string]$intent.principal.logon_type -ne "S4U" -or
        [string]$intent.principal.run_level -ne "Limited" -or
        [string]$intent.principal.id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$intent.principal.display_name) -or
        -not [string]::IsNullOrEmpty([string]$intent.principal.group_id) -or
        [string]$intent.principal.process_token_sid_type -ne "Default" -or
        @($intent.principal.required_privileges).Count -ne 0) {
        throw "Registration intent does not bind the required S4U/Limited principal."
    }
    $preparedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$intent.prepared_at_local) `
        -Label "registration intent prepared_at_local"
    Assert-WeatherIntegrationTaskBindingRecord `
        -AttemptContract $AttemptContract `
        -Role "suite" `
        -Record $intent.suite `
        -UserId ([string]$intent.principal.user_id) | Out-Null
    Assert-WeatherIntegrationTaskBindingRecord `
        -AttemptContract $AttemptContract `
        -Role "merge" `
        -Record $intent.merge `
        -UserId ([string]$intent.principal.user_id) | Out-Null
    if ([string]$intent.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$intent.safety.credential_value_access_authorized -or
        [bool]$intent.safety.live_exchange_mutation_authorized) {
        throw "Registration intent violates the attempt safety boundary."
    }
    return [pscustomobject]@{
        Intent = $intent
        IntentPath = $intentPath
        IntentSha256 = $actualSha256
    }
}

function Assert-WeatherIntegrationRegistrationReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [switch]$RequirePass
    )

    $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$AttemptContract.Manifest.evidence.registration_receipt)
    $receipt = Read-WeatherIntegrationSharedJson -Path $receiptPath
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt `
        -Names @("schema", "status", "binding_contract", "attempt_id", "manifest_path", "manifest_sha256", "registration_intent_path", "registration_intent_sha256", "registered_at_local", "principal", "suite", "merge", "downstream_tasks_created", "safety") `
        -Label "Registration receipt"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.principal `
        -Names @("user_id", "logon_type", "run_level", "id", "display_name", "group_id", "process_token_sid_type", "required_privileges") `
        -Label "Registration receipt principal"
    Assert-WeatherIntegrationRequiredProperties `
        -Object $receipt.safety `
        -Names @("authority", "credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration receipt safety boundary"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt `
        -Names @("downstream_tasks_created") `
        -Label "Registration receipt"
    Assert-WeatherIntegrationBooleanProperties `
        -Object $receipt.safety `
        -Names @("credential_value_access_authorized", "live_exchange_mutation_authorized") `
        -Label "Registration receipt safety boundary"
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptRegistrationReceiptSchema -or
        [string]$receipt.binding_contract -ne $script:WeatherIntegrationAttemptTaskBindingContract -or
        [string]$receipt.attempt_id -ne [string]$AttemptContract.Manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
        throw "Registration receipt does not bind the exact task contract for this attempt."
    }
    if ($RequirePass -and [string]$receipt.status -ne "PASS") {
        throw "Integration-attempt runtime requires an immutable PASS registration receipt."
    }
    if ([string]$receipt.status -notin @("PASS", "FAIL")) {
        throw "Registration receipt status is unsupported: $($receipt.status)"
    }
    $registeredAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$receipt.registered_at_local) `
        -Label "registration receipt registered_at_local"
    if ([bool]$receipt.downstream_tasks_created -or
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "Registration receipt violates the attempt safety boundary."
    }
    $intentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.registration_intent_path) -Right $intentPath)) {
        throw "Registration receipt does not bind the canonical pre-registration intent."
    }
    if ([string]$receipt.registration_intent_sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Registration receipt has an invalid pre-registration intent hash."
    }
    $intentContract = Assert-WeatherIntegrationRegistrationIntent `
        -AttemptContract $AttemptContract `
        -ExpectedSha256 ([string]$receipt.registration_intent_sha256)
    $preparedAt = ConvertFrom-WeatherIntegrationEvidenceTimestamp `
        -Value ([string]$intentContract.Intent.prepared_at_local) `
        -Label "registration intent prepared_at_local"
    if ($registeredAt -lt $preparedAt) {
        throw "Registration receipt predates its immutable pre-registration intent."
    }
    if ([string]$receipt.principal.user_id -ne [string]$intentContract.Intent.principal.user_id -or
        [string]$receipt.principal.logon_type -ne "S4U" -or
        [string]$receipt.principal.run_level -ne "Limited" -or
        [string]$receipt.principal.id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$receipt.principal.display_name) -or
        -not [string]::IsNullOrEmpty([string]$receipt.principal.group_id) -or
        [string]$receipt.principal.process_token_sid_type -ne "Default" -or
        @($receipt.principal.required_privileges).Count -ne 0) {
        throw "Registration receipt principal disagrees with its immutable intent."
    }
    foreach ($role in @("suite", "merge")) {
        $record = $receipt.PSObject.Properties[$role].Value
        Assert-WeatherIntegrationRequiredProperties `
            -Object $record `
            -Names @("registered", "trigger_at_local") `
            -Label "$role registration receipt"
        Assert-WeatherIntegrationBooleanProperties `
            -Object $record `
            -Names @("registered") `
            -Label "$role registration receipt"
        Assert-WeatherIntegrationTaskBindingRecord `
            -AttemptContract $AttemptContract `
            -Role $role `
            -Record $record `
            -UserId ([string]$receipt.principal.user_id) | Out-Null
        $intentRecord = $intentContract.Intent.PSObject.Properties[$role].Value
        if ([string]$record.arguments -ne [string]$intentRecord.arguments -or
            [string]$record.trigger_at_local -ne [string]$intentRecord.trigger.at_local -or
            [string]$record.trigger.at_local -ne [string]$intentRecord.trigger.at_local -or
            [string]$record.settings.execution_time_limit -ne [string]$intentRecord.settings.execution_time_limit) {
            throw "$role registration receipt disagrees with its immutable intent."
        }
        if ($RequirePass -and -not [bool]$record.registered) {
            throw "PASS registration receipt does not prove that the $role task was registered."
        }
    }
    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = $receiptPath
        ReceiptSha256 = Get-WeatherIntegrationFileSha256 -Path $receiptPath
        Intent = $intentContract.Intent
        IntentPath = $intentContract.IntentPath
        IntentSha256 = $intentContract.IntentSha256
    }
}

function Assert-WeatherIntegrationScheduledTaskObject {
    param(
        [Parameter(Mandatory = $true)][object]$Task,
        [Parameter(Mandatory = $true)][object]$BindingEvidence,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role
    )

    $record = $BindingEvidence.PSObject.Properties[$Role].Value
    $principal = $BindingEvidence.principal
    $actions = @($Task.Actions)
    $triggers = @($Task.Triggers)
    $requiredPrivileges = @(
        $Task.Principal.RequiredPrivilege |
            Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) }
    )
    if ($actions.Count -ne 1 -or
        -not [string]::IsNullOrEmpty([string]$actions[0].Id) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right ([string]$record.executable)) -or
        [string]$actions[0].Arguments -ne [string]$record.arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$record.working_directory))) {
        throw "$Role task action is not exactly bound to the immutable registration evidence."
    }
    if ([string]$Task.TaskPath -ne [string]$record.task_path -or
        [string]$Task.Description -ne [string]$record.description) {
        throw "$Role task path or description does not match the immutable registration evidence."
    }
    if (-not [string]::Equals(
            [string]$Task.Principal.UserId,
            [string]$principal.user_id,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        [string]$Task.Principal.LogonType -ne "S4U" -or
        [string]$Task.Principal.RunLevel -ne "Limited" -or
        [string]$Task.Principal.Id -ne "Author" -or
        -not [string]::IsNullOrEmpty([string]$Task.Principal.DisplayName) -or
        -not [string]::IsNullOrEmpty([string]$Task.Principal.GroupId) -or
        [string]$Task.Principal.ProcessTokenSidType -ne "Default" -or
        $requiredPrivileges.Count -ne 0) {
        throw "$Role task principal is not the exact S4U/Limited registration principal."
    }
    if ($triggers.Count -ne 1 -or
        [string]$triggers[0].CimClass.CimClassName -ne "MSFT_TaskTimeTrigger" -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Id) -or
        -not [bool]$triggers[0].Enabled) {
        throw "$Role task must have exactly one enabled one-shot time trigger."
    }
    try {
        $actualBoundary = [string]$triggers[0].StartBoundary
        if ($actualBoundary -notmatch '[+-][0-9]{2}:[0-9]{2}$') {
            throw "Task Scheduler trigger boundary does not carry an explicit local UTC offset."
        }
        $actualTrigger = [datetimeoffset]::Parse(
            $actualBoundary,
            [Globalization.CultureInfo]::InvariantCulture
        )
        $actualTriggerAt = $actualTrigger.DateTime
        $expectedTriggerAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$record.trigger.at_local) `
            -Label "$Role trigger_at_local"
        $expectedOffset = [TimeZoneInfo]::Local.GetUtcOffset($expectedTriggerAt)
    }
    catch {
        throw "$Role task trigger boundary is unreadable."
    }
    if ($actualTriggerAt -ne $expectedTriggerAt -or
        $actualTrigger.Offset -ne $expectedOffset -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].EndBoundary) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].RandomDelay) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].ExecutionTimeLimit) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Repetition.Interval) -or
        -not [string]::IsNullOrEmpty([string]$triggers[0].Repetition.Duration) -or
        [bool]$triggers[0].Repetition.StopAtDurationEnd) {
        throw "$Role task trigger does not match the exact non-repeating local trigger."
    }
    $settings = $Task.Settings
    if ([string]$settings.MultipleInstances -ne [string]$record.settings.multiple_instances -or
        [string]$settings.Compatibility -ne [string]$record.settings.compatibility -or
        [bool]$settings.AllowDemandStart -ne [bool]$record.settings.allow_demand_start -or
        [bool]$settings.AllowHardTerminate -ne [bool]$record.settings.allow_hard_terminate -or
        [string]$settings.DeleteExpiredTaskAfter -ne [string]$record.settings.delete_expired_task_after -or
        [string]$settings.ExecutionTimeLimit -ne [string]$record.settings.execution_time_limit -or
        [bool]$settings.Hidden -ne [bool]$record.settings.hidden -or
        [int]$settings.Priority -ne [int]$record.settings.priority -or
        [int]$settings.RestartCount -ne [int]$record.settings.restart_count -or
        [string]$settings.RestartInterval -ne [string]$record.settings.restart_interval -or
        [bool]$settings.WakeToRun -ne [bool]$record.settings.wake_to_run -or
        [bool]$settings.StartWhenAvailable -ne [bool]$record.settings.start_when_available -or
        [bool]$settings.DisallowStartIfOnBatteries -eq [bool]$record.settings.allow_start_if_on_batteries -or
        [bool]$settings.StopIfGoingOnBatteries -ne [bool]$record.settings.stop_if_going_on_batteries -or
        [bool]$settings.RunOnlyIfIdle -ne [bool]$record.settings.run_only_if_idle -or
        [bool]$settings.RunOnlyIfNetworkAvailable -ne [bool]$record.settings.run_only_if_network_available -or
        [bool]$settings.DisallowStartOnRemoteAppSession -ne [bool]$record.settings.disallow_start_on_remote_app_session -or
        [bool]$settings.UseUnifiedSchedulingEngine -ne [bool]$record.settings.use_unified_scheduling_engine -or
        [bool]$settings.volatile -ne [bool]$record.settings.volatile -or
        [string]$settings.MaintenanceSettings -ne [string]$record.settings.maintenance_settings -or
        [string]$settings.IdleSettings.IdleDuration -ne [string]$record.settings.idle_duration -or
        [bool]$settings.IdleSettings.RestartOnIdle -ne [bool]$record.settings.idle_restart -or
        [bool]$settings.IdleSettings.StopOnIdleEnd -ne [bool]$record.settings.idle_stop_on_end -or
        [string]$settings.IdleSettings.WaitTimeout -ne [string]$record.settings.idle_wait_timeout -or
        [string]$settings.NetworkSettings.Id -ne [string]$record.settings.network_id -or
        [string]$settings.NetworkSettings.Name -ne [string]$record.settings.network_name) {
        throw "$Role task settings disagree with the exact registration contract."
    }
    return $Task
}

function Assert-WeatherIntegrationScheduledTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [Parameter(Mandatory = $true)][object]$BindingEvidence,
        [switch]$IncludeTaskInfo
    )

    $record = $BindingEvidence.PSObject.Properties[$Role].Value
    $matches = @(Get-ScheduledTask -TaskName ([string]$record.task_name) -ErrorAction SilentlyContinue)
    if ($matches.Count -ne 1) {
        throw "$Role task lookup must resolve exactly one task; found $($matches.Count)."
    }
    $task = $matches[0]
    Assert-WeatherIntegrationScheduledTaskObject `
        -Task $task `
        -BindingEvidence $BindingEvidence `
        -Role $Role | Out-Null
    $info = $null
    if ($IncludeTaskInfo) {
        $info = Get-ScheduledTaskInfo `
            -TaskName ([string]$record.task_name) `
            -TaskPath ([string]$record.task_path) `
            -ErrorAction Stop
    }
    return [pscustomobject]@{
        Task = $task
        Info = $info
        BindingEvidence = $BindingEvidence
    }
}

function Assert-WeatherIntegrationAttemptTaskBinding {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][ValidateSet("suite", "merge")][string]$Role,
        [switch]$IncludeTaskInfo
    )

    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $AttemptContract `
        -RequirePass
    $binding = Assert-WeatherIntegrationScheduledTaskBinding `
        -AttemptContract $AttemptContract `
        -Role $Role `
        -BindingEvidence $registration.Intent `
        -IncludeTaskInfo:$IncludeTaskInfo
    return [pscustomobject]@{
        Task = $binding.Task
        Info = $binding.Info
        RegistrationReceipt = $registration.Receipt
        RegistrationReceiptSha256 = $registration.ReceiptSha256
        RegistrationIntent = $registration.Intent
        RegistrationIntentSha256 = $registration.IntentSha256
    }
}

function Get-WeatherIntegrationRepairAllowedPatterns {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("retry_unchanged", "schema_registry", "ownership_metadata", "orchestration_wrapper", "manual_reviewed_change")]
        [string]$RepairClass
    )

    $patterns = switch ($RepairClass) {
        "retry_unchanged" { @() }
        "schema_registry" {
            @(
                '^src/weather/schema_registry_data\.py$',
                '^src/weather/schema_registry_recent_data\.py$',
                '^src/weather/schema_registry_types\.py$'
            )
        }
        "ownership_metadata" {
            @(
                '^docs/operations/module-ownership-map\.md$',
                '^tests/operations/test_module_size_audit\.py$'
            )
        }
        "orchestration_wrapper" {
            @(
                '^scripts/ops/(integration_attempt_contract|new_integration_attempt|register_integration_attempt|close_integration_attempt|dispatch_integration_attempt_recovery|integration_attempt_suite|integration_attempt_merge|assert_integration_attempt_success|reconcile_integration_attempt|bounded_worktree_test_suite|quiet_window_merge|boot_recovery|register_boot_recovery)\.ps1$',
                '^tests/operations/test_(integration_attempt_scripts|integration_attempt_registration_safety|integration_attempt_evidence_recovery_hardening|bounded_worktree_test_suite_script|suite_gated_quiet_merge_script|quiet_window_merge_script|boot_recovery_script|register_boot_recovery_script|host_task_wrappers|status_script)\.py$',
                '^docs/operations/(INTEGRATION_ATTEMPT_RUNBOOK|OPERATIONS_DESIGN)\.md$',
                '^docs/ops/streak-soak\.md$',
                '^(AGENTS\.md|scripts/ops/AGENTS\.md|tests/AGENTS\.md|docs/AGENTS\.md)$'
            )
        }
        "manual_reviewed_change" { @('^.+$') }
    }
    return @($patterns)
}

function Get-WeatherIntegrationSuiteWaitDecision {
    param(
        [Parameter(Mandatory = $true)][string]$TaskState,
        [Parameter(Mandatory = $true)][datetime]$LastRunTime,
        [Parameter(Mandatory = $true)][int]$LastTaskResult,
        [Parameter(Mandatory = $true)][bool]$ReceiptExists,
        [AllowEmptyString()][string]$ReceiptStatus = "",
        [Parameter(Mandatory = $true)][datetime]$Now,
        [Parameter(Mandatory = $true)][datetime]$Deadline
    )

    if ($ReceiptExists -and $ReceiptStatus -eq "FAIL") {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite emitted an immutable FAIL receipt" }
    }
    if ($TaskState -eq "Running") {
        if ($Now -ge $Deadline) {
            if ($ReceiptExists -and $ReceiptStatus -eq "PASS" -and
                $Now -lt $Deadline.AddSeconds(120)) {
                return [pscustomobject]@{
                    Action = "WAIT"
                    Reason = "suite emitted PASS and has a bounded two-minute task-exit grace"
                    PassExitGrace = $true
                    GraceUntil = $Deadline.AddSeconds(120)
                }
            }
            return [pscustomobject]@{ Action = "STOP"; Reason = "suite remained running through the merge-wait deadline" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task is still running" }
    }
    if ($TaskState -eq "Disabled" -and -not $ReceiptExists) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task is disabled and can no longer run" }
    }
    if ($TaskState -notin @("Ready", "Disabled")) {
        if ($Now -ge $Deadline) {
            return [pscustomobject]@{ Action = "STOP"; Reason = "suite task remained non-terminal through the merge-wait deadline: $TaskState" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task state is not terminal yet: $TaskState" }
    }
    if ($LastRunTime -lt $Now.Date) {
        if ($Now -ge $Deadline) {
            return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task did not run before the merge-wait deadline" }
        }
        return [pscustomobject]@{ Action = "WAIT"; Reason = "suite task has not run on the current local day" }
    }
    if ($ReceiptExists -and $ReceiptStatus -eq "PASS" -and
        $LastTaskResult -in @(0x41301, 0x41303)) {
        return [pscustomobject]@{
            Action = "READY"
            Reason = "suite task is terminal with immutable PASS evidence; Scheduler result is a stale transient"
            StaleSchedulerResult = $true
        }
    }
    if ($LastTaskResult -ne 0) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = ("suite task result is 0x{0:X}" -f $LastTaskResult) }
    }
    if (-not $ReceiptExists) {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite task returned success without an immutable receipt" }
    }
    if ($ReceiptStatus -ne "PASS") {
        return [pscustomobject]@{ Action = "FAIL"; Reason = "suite receipt status is unsupported or unreadable" }
    }
    return [pscustomobject]@{ Action = "READY"; Reason = "suite task and receipt are terminal PASS" }
}

function Assert-WeatherIntegrationLocalScheduleTime {
    param(
        [Parameter(Mandatory = $true)][datetime]$Value,
        [Parameter(Mandatory = $true)][string]$Label,
        [TimeZoneInfo]$TimeZone = [TimeZoneInfo]::Local
    )

    if ($Value.Kind -eq [DateTimeKind]::Utc) {
        throw "$Label must be a local wall-clock value without a UTC marker."
    }
    $wallClock = [datetime]::SpecifyKind($Value, [DateTimeKind]::Unspecified)
    if ($TimeZone.IsInvalidTime($wallClock)) {
        throw "$Label falls in a daylight-saving gap and will not run: $($wallClock.ToString('o'))"
    }
    if ($TimeZone.IsAmbiguousTime($wallClock)) {
        throw "$Label falls in an ambiguous daylight-saving hour and is not safe for a one-shot: $($wallClock.ToString('o'))"
    }
    return $wallClock
}

function ConvertFrom-WeatherIntegrationLocalTimestamp {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -match '(?i)(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "$Label must not carry a UTC marker or numeric offset; use the local wall clock."
    }
    try {
        $parsed = [datetime]::ParseExact(
            $Value,
            [string[]]@("o", "yyyy-MM-dd'T'HH:mm:ss"),
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::None
        )
    }
    catch {
        throw "$Label is not a supported invariant local timestamp."
    }
    return Assert-WeatherIntegrationLocalScheduleTime -Value $parsed -Label $Label
}

function ConvertFrom-WeatherIntegrationEvidenceTimestamp {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if ($Value -notmatch '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,7})?(?:Z|[+-][0-9]{2}:[0-9]{2})$') {
        throw "$Label must be an invariant ISO-8601 timestamp with an explicit UTC offset."
    }
    try {
        return [datetimeoffset]::Parse(
            $Value,
            [Globalization.CultureInfo]::InvariantCulture,
            [Globalization.DateTimeStyles]::RoundtripKind
        )
    }
    catch {
        throw "$Label is not a valid invariant ISO-8601 timestamp."
    }
}

function Assert-WeatherIntegrationGitBaseline {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$Phase
    )

    $manifest = $AttemptContract.Manifest
    $repoRoot = Resolve-WeatherIntegrationPath -Path ([string]$manifest.repo_root)
    $masterOutput = @(& git -C $repoRoot rev-parse master)
    if ($LASTEXITCODE -ne 0 -or $masterOutput.Count -eq 0) {
        throw "$Phase could not resolve production master."
    }
    $masterTip = ([string]$masterOutput[-1]).Trim().ToLowerInvariant()
    $headOutput = @(& git -C $repoRoot rev-parse HEAD)
    if ($LASTEXITCODE -ne 0 -or $headOutput.Count -eq 0) {
        throw "$Phase could not resolve the production working-tree HEAD."
    }
    $headTip = ([string]$headOutput[-1]).Trim().ToLowerInvariant()
    $branchOutput = @(& git -C $repoRoot symbolic-ref --quiet --short HEAD)
    if ($LASTEXITCODE -ne 0 -or $branchOutput.Count -eq 0) {
        throw "$Phase production working tree is detached instead of checked out on master."
    }
    $branchName = ([string]$branchOutput[-1]).Trim()
    $originOutput = @(& git -C $repoRoot rev-parse origin/master)
    if ($LASTEXITCODE -ne 0 -or $originOutput.Count -eq 0) {
        throw "$Phase could not resolve origin/master."
    }
    $originTip = ([string]$originOutput[-1]).Trim().ToLowerInvariant()
    if ($branchName -ne "master" -or
        $headTip -ne [string]$manifest.baseline.master -or
        $masterTip -ne [string]$manifest.baseline.master -or
        $originTip -ne [string]$manifest.baseline.origin_master) {
        throw "$Phase baseline changed after attempt freeze. Expected $($manifest.baseline.master); branch=$branchName HEAD=$headTip master=$masterTip origin/master=$originTip"
    }
    return [pscustomobject]@{ Branch = $branchName; Head = $headTip; Master = $masterTip; OriginMaster = $originTip }
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
        $suiteAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.suite_at_local) `
            -Label "suite_at_local"
        $mergeAt = ConvertFrom-WeatherIntegrationLocalTimestamp `
            -Value ([string]$manifest.schedule.merge_at_local) `
            -Label "merge_at_local"
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
    $expectedTestFileCount = [int]$manifest.suite.expected_test_file_count
    $maxFilesPerChunk = [int]$manifest.suite.max_files_per_chunk
    $expectedChunkCount = [int]$manifest.suite.expected_chunk_count
    if (-not [string]::IsNullOrWhiteSpace([string]$manifest.suite.additional_python_path)) {
        throw "Integration attempts do not support AdditionalPythonPath because external Python content is not frozen by the manifest."
    }
    if ($expectedTestFileCount -le 0 -or $maxFilesPerChunk -lt 1 -or
        $maxFilesPerChunk -gt 25 -or $expectedChunkCount -le 0 -or
        $expectedChunkCount -ne [int][math]::Ceiling($expectedTestFileCount / [double]$maxFilesPerChunk)) {
        throw "Attempt suite inventory is missing or internally inconsistent."
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
    $registrationIntentProperty = $manifest.evidence.PSObject.Properties["registration_intent"]
    if ($null -ne $registrationIntentProperty -and
        -not [string]::IsNullOrWhiteSpace([string]$registrationIntentProperty.Value)) {
        Assert-WeatherIntegrationEvidencePath `
            -AttemptRoot $attemptRoot `
            -ActualPath ([string]$registrationIntentProperty.Value) `
            -ExpectedName "registration-intent.json" | Out-Null
    }
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.closure_receipt) -ExpectedName "closure-receipt.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.recovery_dispatch) -ExpectedName "recovery-dispatch.json" | Out-Null
    Assert-WeatherIntegrationEvidencePath -AttemptRoot $attemptRoot -ActualPath ([string]$manifest.evidence.reconciliation_receipt) -ExpectedName "reconciliation-receipt.json" | Out-Null

    $contract = [pscustomobject]@{
        Manifest = $manifest
        ManifestPath = $resolvedManifestPath
        ManifestSha256 = $actualSha256
        AttemptRoot = $attemptRoot
    }
    Assert-WeatherIntegrationRepairClaim -AttemptContract $contract
    return $contract
}

function Disable-WeatherIntegrationAttemptTasks {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $registrationReceiptPath = [string]$manifest.evidence.registration_receipt
    $registrationReceipt = $null
    $strictRegistration = $null
    $strictBindingSource = $null
    $registrationReceiptError = $null
    $registrationIntentPath = Get-WeatherIntegrationRegistrationIntentPath -AttemptContract $AttemptContract
    if (Test-Path -LiteralPath $registrationIntentPath -PathType Leaf) {
        # This is the first durable registrar write and is independently
        # derivable from the manifest. Prefer it as the crash-recovery floor;
        # a torn or missing later receipt must not strand exact tasks.
        $strictRegistration = Assert-WeatherIntegrationRegistrationIntent -AttemptContract $AttemptContract
        $strictBindingSource = "pre_registration_intent"
    }
    if (Test-Path -LiteralPath $registrationReceiptPath -PathType Leaf) {
        try {
            $registrationReceipt = Read-WeatherIntegrationSharedJson -Path $registrationReceiptPath
            if ([string]$registrationReceipt.schema -ne $script:WeatherIntegrationAttemptRegistrationReceiptSchema -or
                [string]$registrationReceipt.attempt_id -ne [string]$manifest.attempt_id -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$registrationReceipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
                [string]$registrationReceipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256) {
                throw "Registration receipt does not bind this exact attempt."
            }
            $bindingContractProperty = $registrationReceipt.PSObject.Properties["binding_contract"]
            if ($null -ne $bindingContractProperty -and
                [string]$bindingContractProperty.Value -eq $script:WeatherIntegrationAttemptTaskBindingContract) {
                $strictRegistration = Assert-WeatherIntegrationRegistrationReceipt -AttemptContract $AttemptContract
                $strictBindingSource = "registration_receipt"
            }
            elseif ($null -ne $strictRegistration) {
                throw "Registration receipt lacks the exact task-binding contract recorded by its intent."
            }
        }
        catch {
            if ($null -eq $strictRegistration) {
                throw
            }
            $registrationReceiptError = $_.Exception.Message
            $registrationReceipt = $null
            $strictBindingSource = "pre_registration_intent_receipt_unusable"
        }
    }

    $taskSpecs = @(
        [pscustomobject]@{ name = [string]$manifest.schedule.suite_task_name; role = "suite" },
        [pscustomobject]@{ name = [string]$manifest.schedule.merge_task_name; role = "merge" }
    )
    $taskEvidence = New-Object System.Collections.Generic.List[object]
    foreach ($spec in $taskSpecs) {
        $taskMatches = @(Get-ScheduledTask -TaskName $spec.name -ErrorAction SilentlyContinue)
        if ($taskMatches.Count -eq 0) {
            $taskEvidence.Add([ordered]@{ task_name = $spec.name; exists = $false; disabled = $false })
            continue
        }
        if ($taskMatches.Count -ne 1) {
            throw "Refusing to disable ambiguous attempt task name: $($spec.name)"
        }
        $task = $taskMatches[0]
        if ([string]$task.State -eq "Running") {
            throw "Attempt task is still running and may not be disabled: $($spec.name)"
        }
        if ($null -eq $registrationReceipt -and $null -eq $strictRegistration) {
            throw "Refusing to disable an existing task without its immutable registration receipt or pre-registration intent: $($spec.name)"
        }
        $registeredAction = $null
        $bindingEvidence = $null
        if ($null -ne $strictRegistration) {
            $bindingEvidence = if ($null -ne $strictRegistration.PSObject.Properties["Intent"]) {
                $strictRegistration.Intent
            }
            else {
                throw "Strict task-closing evidence is missing its registration intent."
            }
            Assert-WeatherIntegrationScheduledTaskBinding `
                -AttemptContract $AttemptContract `
                -Role ([string]$spec.role) `
                -BindingEvidence $bindingEvidence | Out-Null
            if ($null -ne $registrationReceipt) {
                $registeredAction = $registrationReceipt.PSObject.Properties[[string]$spec.role].Value
            }
        }
        else {
            # Backward-compatible close support for attempts registered before
            # exact trigger/settings intents existed. New receipts always take
            # the strict branch above; legacy tasks retain their prior action
            # and S4U/Limited close boundary rather than becoming stranded.
            $registeredActionProperty = $registrationReceipt.PSObject.Properties[[string]$spec.role]
            $registeredAction = if ($null -eq $registeredActionProperty) { $null } else { $registeredActionProperty.Value }
            if ($null -eq $registeredAction -or [string]$registeredAction.task_name -ne [string]$spec.name) {
                throw "Registration receipt does not bind this exact task action: $($spec.name)"
            }
            $actions = @($task.Actions)
            if ($actions.Count -ne 1 -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].Execute) -Right ([string]$registeredAction.executable)) -or
                [string]$actions[0].Arguments -ne [string]$registeredAction.arguments -or
                -not (Test-WeatherIntegrationPathEqual -Left ([string]$actions[0].WorkingDirectory) -Right ([string]$registeredAction.working_directory)) -or
                [string]$task.Principal.UserId -ne [string]$registrationReceipt.principal.user_id -or
                [string]$task.Principal.LogonType -ne "S4U" -or
                [string]$task.Principal.RunLevel -ne "Limited") {
                throw "Refusing to disable task whose action is not exactly bound to this attempt: $($spec.name)"
            }
        }
        if ([string]$task.State -ne "Disabled") {
            if ($null -ne $strictRegistration) {
                Disable-ScheduledTask -TaskName $spec.name -TaskPath "\" -ErrorAction Stop | Out-Null
            }
            else {
                Disable-ScheduledTask -TaskName $spec.name -ErrorAction Stop | Out-Null
            }
        }
        if ($null -ne $strictRegistration) {
            $disabledBinding = Assert-WeatherIntegrationScheduledTaskBinding `
                -AttemptContract $AttemptContract `
                -Role ([string]$spec.role) `
                -BindingEvidence $bindingEvidence
            $disabledTask = $disabledBinding.Task
        }
        else {
            $disabledTask = Get-ScheduledTask -TaskName $spec.name -ErrorAction Stop
        }
        if ([string]$disabledTask.State -ne "Disabled") {
            throw "Attempt task did not enter Disabled state: $($spec.name)"
        }
        $info = if ($null -ne $strictRegistration) {
            Get-ScheduledTaskInfo -TaskName $spec.name -TaskPath "\" -ErrorAction SilentlyContinue
        }
        else {
            Get-ScheduledTaskInfo -TaskName $spec.name -ErrorAction SilentlyContinue
        }
        $taskEvidence.Add([ordered]@{
            task_name = $spec.name
            exists = $true
            disabled = $true
            binding_source = if ($null -eq $strictBindingSource) { "legacy_registration_receipt" } else { $strictBindingSource }
            registration_receipt_error = $registrationReceiptError
            registration_receipt_registered = if ($null -eq $registeredAction) { $null } else { [bool]$registeredAction.registered }
            registration_receipt_disagreed = if ($null -eq $registeredAction) { $null } else { -not [bool]$registeredAction.registered }
            last_run_time = if ($null -eq $info) { $null } else { ([datetime]$info.LastRunTime).ToString("o") }
            last_task_result = if ($null -eq $info) { $null } else { [int]$info.LastTaskResult }
        })
    }
    return @($taskEvidence | ForEach-Object { $_ })
}

function Assert-WeatherIntegrationRepairClaim {
    param(
        [Parameter(Mandatory = $true)]
        [object]$AttemptContract
    )

    $manifest = $AttemptContract.Manifest
    $repairOfProperty = $manifest.authorization.PSObject.Properties["repair_of"]
    $repairOf = if ($null -eq $repairOfProperty) { $null } else { $repairOfProperty.Value }
    if ($null -eq $repairOf) {
        if ([string]$manifest.authorization.repair_class -ne "initial") {
            throw "A non-initial attempt is missing its predecessor receipt and successor claim."
        }
        return
    }
    if ([string]$manifest.authorization.repair_class -eq "initial") {
        throw "An initial attempt may not carry predecessor repair evidence."
    }

    $receiptPath = Resolve-WeatherIntegrationPath -Path ([string]$repairOf.receipt_path)
    $receiptSha256 = Get-WeatherIntegrationFileSha256 -Path $receiptPath
    if ($receiptSha256 -ne [string]$repairOf.receipt_sha256) {
        throw "The predecessor FAIL receipt changed after the successor was frozen."
    }
    $priorReceipt = Read-WeatherIntegrationSharedJson -Path $receiptPath
    if ([string]$priorReceipt.schema -ne $script:WeatherIntegrationAttemptClosureReceiptSchema -or
        [string]$priorReceipt.status -ne "FAIL") {
        throw "A successor attempt must bind an immutable closure FAIL receipt."
    }
    if ([string]$priorReceipt.attempt_id -ne [string]$repairOf.prior_attempt_id) {
        throw "The predecessor closure receipt attempt id does not match the successor manifest."
    }

    $dispatchPath = Resolve-WeatherIntegrationPath -Path ([string]$repairOf.dispatch_path)
    $dispatchSha256 = Get-WeatherIntegrationFileSha256 -Path $dispatchPath
    if ($dispatchSha256 -ne [string]$repairOf.dispatch_sha256) {
        throw "The predecessor recovery dispatch changed after the successor was frozen."
    }
    $dispatch = Read-WeatherIntegrationSharedJson -Path $dispatchPath
    if ([string]$dispatch.schema -ne $script:WeatherIntegrationAttemptRecoveryDispatchSchema -or
        [string]$dispatch.status -ne "READY_FOR_SUCCESSOR_REVIEW" -or
        [string]$dispatch.repair_class -ne [string]$manifest.authorization.repair_class -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$dispatch.closure_receipt_path) -Right $receiptPath) -or
        [string]$dispatch.closure_receipt_sha256 -ne $receiptSha256) {
        throw "The predecessor recovery dispatch does not authorize this successor."
    }

    $priorManifestPath = Resolve-WeatherIntegrationPath -Path ([string]$priorReceipt.manifest_path)
    $priorManifestSha256 = Get-WeatherIntegrationFileSha256 -Path $priorManifestPath
    if ($priorManifestSha256 -ne [string]$priorReceipt.manifest_sha256) {
        throw "The predecessor manifest changed after closure."
    }
    $priorManifest = Read-WeatherIntegrationSharedJson -Path $priorManifestPath
    $priorAttemptRoot = Resolve-WeatherIntegrationPath -Path ([string]$priorManifest.attempt_root)
    $expectedClaimPath = Join-Path $priorAttemptRoot "successor-claim.json"
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$repairOf.claim_path) -Right $expectedClaimPath)) {
        throw "The successor claim path is not canonical for the predecessor attempt."
    }

    $claim = Read-WeatherIntegrationSharedJson -Path $expectedClaimPath
    if ([string]$claim.schema -ne $script:WeatherIntegrationAttemptSuccessorClaimSchema -or
        [string]$claim.status -ne "CLAIMED") {
        throw "The predecessor successor claim is unsupported."
    }
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.predecessor_receipt_path) -Right $receiptPath) -or
        [string]$claim.predecessor_receipt_sha256 -ne $receiptSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.recovery_dispatch_path) -Right $dispatchPath) -or
        [string]$claim.recovery_dispatch_sha256 -ne $dispatchSha256 -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$claim.successor_manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$claim.successor_manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$claim.successor_attempt_id -ne [string]$manifest.attempt_id -or
        [string]$claim.successor_expected_tip -ne [string]$manifest.expected_tip -or
        [string]$claim.repair_class -ne [string]$manifest.authorization.repair_class) {
        throw "The predecessor successor claim does not bind this exact successor manifest."
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
        attempt_recovery_dispatch = Join-Path $repoRoot "scripts\ops\dispatch_integration_attempt_recovery.ps1"
        boot_recovery = Join-Path $repoRoot "scripts\ops\boot_recovery.ps1"
        register_boot_recovery = Join-Path $repoRoot "scripts\ops\register_boot_recovery.ps1"
        quiet_merge = Join-Path $repoRoot "scripts\ops\quiet_window_merge.ps1"
        token_contract = Join-Path $repoRoot "scripts\ops\training_window_contract.ps1"
        job_containment = Join-Path $repoRoot "scripts\ops\windows_kill_on_close_job.ps1"
        workload_admission = Join-Path $repoRoot "scripts\ops\workload_admission.ps1"
        roll_verdict = Join-Path $repoRoot "scripts\ops\roll_verdict.ps1"
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
    $registration = Assert-WeatherIntegrationRegistrationReceipt `
        -AttemptContract $AttemptContract `
        -RequirePass
    if ([string]$receipt.registration_receipt_sha256 -ne [string]$registration.ReceiptSha256 -or
        [string]$receipt.registration_intent_sha256 -ne [string]$registration.IntentSha256) {
        throw "Suite receipt does not bind the exact registration receipt and pre-registration intent."
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
        [string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
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
    Assert-WeatherIntegrationPreflightVerdict -Verdict ([string]$receipt.logs.preflight.verdict)
    Assert-WeatherIntegrationFullSuiteVerdict `
        -Verdict ([string]$receipt.logs.full_suite.verdict) `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) | Out-Null
    Assert-WeatherIntegrationFullSuiteLogPlan `
        -Path ([string]$receipt.logs.full_suite.path) `
        -ExpectedTestFileCount ([int]$manifest.suite.expected_test_file_count) `
        -ExpectedMaxFilesPerChunk ([int]$manifest.suite.max_files_per_chunk) `
        -ExpectedChunkCount ([int]$manifest.suite.expected_chunk_count) | Out-Null

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

function Assert-WeatherIntegrationQuietReportDocumentation {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][object]$QuietReport
    )

    $manifest = $AttemptContract.Manifest
    $pendingSha256 = ([string]$QuietReport.documentation_transaction_pending_sha256).ToLowerInvariant()
    $snapshotRelative = ([string]$QuietReport.documentation_transaction_snapshot_path).Replace('\', '/')
    $expectedRelative = "data/alerts/documentation_transactions/pending-$pendingSha256.json"
    $snapshotPath = Join-Path ([string]$manifest.repo_root) ($snapshotRelative -replace '/', '\')
    if ($pendingSha256 -notmatch '^[0-9a-f]{64}$' -or
        $snapshotRelative -cne $expectedRelative -or
        (Get-WeatherIntegrationFileSha256 -Path $snapshotPath) -ne $pendingSha256) {
        throw "Quiet-merge documentation transaction snapshot identity/hash is invalid."
    }
    $snapshot = Read-WeatherIntegrationSharedJson -Path $snapshotPath
    $matchingEntries = @($snapshot.integrations | Where-Object {
        ([string]$_.integration_tip).ToLowerInvariant() -eq
            ([string]$QuietReport.merge_commit).ToLowerInvariant() -and
        [string]$_.branch -ceq [string]$manifest.branch_ref -and
        ([string]$_.expected_tip).ToLowerInvariant() -eq [string]$manifest.expected_tip
    })
    if ([string]$snapshot.schema_version -ne "documentation_transaction_pending_v0.1" -or
        [string]$snapshot.status -ne "PENDING" -or
        ([string]$snapshot.latest_integration_tip).ToLowerInvariant() -ne
            ([string]$QuietReport.merge_commit).ToLowerInvariant() -or
        $matchingEntries.Count -ne 1) {
        throw "Quiet-merge documentation snapshot does not bind the exact merge, branch, and source tip."
    }
    return [pscustomobject]@{
        PendingSha256 = $pendingSha256
        SnapshotPath = Resolve-WeatherIntegrationPath -Path $snapshotPath
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
    if ([string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
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
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        -not [bool]$quietReport.capture_recovery_proved -or
        ([bool]$quietReport.execution_tape_recovery_required -and
            -not [bool]$quietReport.execution_tape_recovery_proved) -or
        -not [bool]$quietReport.publication_acknowledged -or
        -not [bool]$quietReport.documentation_transaction_recorded -or
        [string]$quietReport.merge_commit -ne [string]$receipt.production_head) {
        throw "Immutable quiet-merge report does not prove the frozen source tip was pushed."
    }
    Assert-WeatherIntegrationQuietReportDocumentation `
        -AttemptContract $AttemptContract -QuietReport $quietReport | Out-Null

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

function Assert-WeatherIntegrationMergedUnverifiedReceipt {
    param(
        [Parameter(Mandatory = $true)][object]$AttemptContract,
        [Parameter(Mandatory = $true)][string]$ExpectedReceiptSha256
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
    if ([string]$receipt.schema -ne $script:WeatherIntegrationAttemptMergeReceiptSchema -or
        [string]$receipt.status -ne "MERGED_UNVERIFIED") {
        throw "Reconciliation requires an immutable MERGED_UNVERIFIED merge receipt."
    }
    if ([string]$receipt.attempt_id -ne [string]$manifest.attempt_id -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.manifest_path) -Right $AttemptContract.ManifestPath) -or
        [string]$receipt.manifest_sha256 -ne [string]$AttemptContract.ManifestSha256 -or
        [string]$receipt.source_tip -ne [string]$manifest.expected_tip -or
        [string]$receipt.branch_ref -ne [string]$manifest.branch_ref -or
        -not [bool]$receipt.origin_master_verified -or
        -not [bool]$receipt.source_tip_integrated) {
        throw "MERGED_UNVERIFIED receipt does not prove this exact attempt reached production."
    }
    if ([string]$receipt.production_head -notmatch '^[0-9a-f]{40}$' -or
        [string]$receipt.production_head -ne [string]$receipt.origin_master) {
        throw "MERGED_UNVERIFIED receipt does not bind equal published production and origin tips."
    }
    if ([string]$receipt.safety.authority -ne "NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY" -or
        [bool]$receipt.safety.credential_value_access_authorized -or
        [bool]$receipt.safety.live_exchange_mutation_authorized) {
        throw "MERGED_UNVERIFIED receipt violates the no-credential/no-live-exchange boundary."
    }
    foreach ($scriptName in @("attempt_merge", "quiet_merge")) {
        $receiptScript = $receipt.scripts.$scriptName
        $manifestScript = $manifest.orchestration.$scriptName
        if ($null -eq $receiptScript -or
            -not (Test-WeatherIntegrationPathEqual -Left ([string]$receiptScript.path) -Right ([string]$manifestScript.path)) -or
            [string]$receiptScript.sha256 -ne [string]$manifestScript.sha256) {
            throw "MERGED_UNVERIFIED receipt script binding does not match the frozen manifest: $scriptName"
        }
    }

    $quietReportPath = [string]$manifest.evidence.quiet_merge_report
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.quiet_merge_report.path) -Right $quietReportPath)) {
        throw "MERGED_UNVERIFIED receipt quiet-report path does not match the attempt manifest."
    }
    $quietReportSha256 = Get-WeatherIntegrationFileSha256 -Path $quietReportPath
    if ($quietReportSha256 -ne [string]$receipt.quiet_merge_report.sha256) {
        throw "Immutable quiet-merge report hash does not match the MERGED_UNVERIFIED receipt."
    }
    $quietReport = Read-WeatherIntegrationSharedJson -Path $quietReportPath
    if ([string]$quietReport.schema -ne "quiet_window_merge_report_v0.2" -or
        -not [bool]$quietReport.ok -or [string]$quietReport.stage -ne "pushed" -or
        [string]$quietReport.expected_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.expected_baseline -ne [string]$manifest.baseline.master -or
        [string]$quietReport.baseline_commit -ne [string]$manifest.baseline.master -or
        [string]$quietReport.resolved_branch_tip -ne [string]$manifest.expected_tip -or
        [string]$quietReport.branch -ne [string]$manifest.branch_ref -or
        -not [bool]$quietReport.capture_recovery_proved -or
        ([bool]$quietReport.execution_tape_recovery_required -and
            -not [bool]$quietReport.execution_tape_recovery_proved) -or
        -not [bool]$quietReport.publication_acknowledged -or
        -not [bool]$quietReport.documentation_transaction_recorded -or
        [string]$quietReport.merge_commit -ne [string]$receipt.production_head) {
        throw "Immutable quiet-merge report does not prove the MERGED_UNVERIFIED publication."
    }
    Assert-WeatherIntegrationQuietReportDocumentation `
        -AttemptContract $AttemptContract -QuietReport $quietReport | Out-Null
    $suiteReceiptPath = [string]$manifest.evidence.suite_receipt
    if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$receipt.suite_receipt_path) -Right $suiteReceiptPath) -or
        (Get-WeatherIntegrationFileSha256 -Path $suiteReceiptPath) -ne [string]$receipt.suite_receipt_sha256) {
        throw "Suite receipt changed after the MERGED_UNVERIFIED merge consumed it."
    }

    return [pscustomobject]@{
        Receipt = $receipt
        ReceiptPath = Resolve-WeatherIntegrationPath -Path $receiptPath
        ReceiptSha256 = $actualReceiptSha256
        QuietReport = $quietReport
        QuietReportSha256 = $quietReportSha256
    }
}
