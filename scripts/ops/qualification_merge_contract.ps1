# Adopted split-mode calls made inside the existing guarded merge's lease.
# The public v2 lifecycle remains closed until its complete routing is reviewed.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'qualification_durable_json.ps1')

function Assert-WeatherQualificationMergeController {
    param([Parameter(Mandatory = $true)]$State)
    $m = $State.Contract.Manifest
    $closure = Read-WeatherQualificationReference -Root $State.Contract.AttemptRoot -Reference $m.control.closure
    if ([string]$closure.baseline -cne [string]$m.baseline.master) { throw 'Merge controller baseline differs' }
    foreach ($row in $closure.files) {
        $path = Join-Path ([string]$m.control.root) ([string]$row.path)
        if ((Get-WeatherIntegrationFileSha256 -Path $path) -cne [string]$row.sha256) { throw 'Frozen merge controller changed' }
    }
}

function Assert-WeatherQualificationDelegatedMerge {
    param([Parameter(Mandatory = $true)]$State)
    $m, $plan = $State.Contract.Manifest, $State.Plan
    if ((Get-WeatherExecutionHostId) -cne [string]$plan.host_id -or
        (Get-WeatherExecutionPrincipalId) -cne [string]$plan.principal_id) { throw 'Delegated merge host/principal differs' }
    $assignment = Get-WeatherExecutionHostAssignment -RepoRoot ([string]$m.control.root)
    if ((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id) { throw 'Dedicated capture installation required' }
    $identity = Get-WeatherQualificationCurrentLogon
    if ($identity.logon_type -ne 4 -or $identity.token_type -ne 1 -or $identity.elevated) { throw 'Delegated merge is not an unelevated batch token' }
    $binding = Assert-WeatherIntegrationAttemptTaskBinding -AttemptContract $State.Contract -Role merge -IncludeTaskInfo
    $expected = Get-WeatherIntegrationExpectedTaskBinding -AttemptContract $State.Contract -Role merge -UserId ([string]$binding.Task.Principal.UserId)
    if ([string]$binding.Task.State -cne 'Running') { throw 'Registered merge wrapper is not running' }
    $invocationRef = Get-WeatherQualificationReference -Root $State.Contract.AttemptRoot -Name 'merge-invocation.json'
    $invocation = Read-WeatherQualificationReference -Root $State.Contract.AttemptRoot -Reference $invocationRef
    if ([string]$invocation.role -cne 'merge' -or [string]$invocation.host_id -cne [string]$plan.host_id -or
        [string]$invocation.principal_id -cne [string]$plan.principal_id -or
        [string]$invocation.token.sid -cne [string]$identity.sid -or
        [string]$invocation.token.authentication_id -cne [string]$identity.authentication_id -or
        [string]$invocation.registration_receipt_sha256 -cne [string]$binding.RegistrationReceiptSha256 -or
        [string]$invocation.registration_intent_sha256 -cne [string]$binding.RegistrationIntentSha256) { throw 'Delegated invocation binding differs' }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    if ([int]$current.ParentProcessId -ne [int]$invocation.token.pid) { throw 'Quiet merge is not the registered wrapper child' }
    $parent = Get-Process -Id ([int]$current.ParentProcessId) -ErrorAction Stop
    try {
        if ($parent.StartTime.ToUniversalTime().Ticks -ne [Int64]$invocation.token.creation_utc_ticks -or
            -not (Test-WeatherIntegrationPathEqual -Left $parent.MainModule.FileName -Right $expected.executable) -or
            -not (Test-WeatherIntegrationPathEqual -Left $identity.image -Right $expected.executable)) { throw 'Delegated native parent generation/image differs' }
    } finally { $parent.Dispose() }
    $parentRow = Get-CimInstance Win32_Process -Filter ("ProcessId=" + [string]$invocation.token.pid) -ErrorAction Stop
    $argv = [Weather.Operations.QualificationLogonReader]::Arguments([string]$parentRow.CommandLine)
    if ((ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens @($argv | Select-Object -Skip 1)) -cne [string]$expected.arguments) {
        throw 'Registered parent command line differs'
    }
    $scheduler = New-Object -ComObject 'Schedule.Service'; $scheduler.Connect()
    $instances = @($scheduler.GetFolder('\').GetTask([string]$binding.Task.TaskName).GetInstances(1))
    if ($instances.Count -ne 1 -or [int]$instances[0].State -ne 4 -or
        [string]$instances[0].InstanceGuid -cne [string]$invocation.instance_guid -or
        [int]$instances[0].EnginePID -ne [int]$invocation.engine_pid) { throw 'Delegated Scheduler instance changed' }
    return $identity
}

function Initialize-WeatherQualificationMerge {
    param([Parameter(Mandatory = $true)][string]$ManifestPath, [Parameter(Mandatory = $true)][string]$ManifestSha256,
          [Parameter(Mandatory = $true)][string]$ProductionRoot, [Parameter(Mandatory = $true)][string]$Source,
          [Parameter(Mandatory = $true)][string]$Baseline, [Parameter(Mandatory = $true)][string]$SelfPath)
    $state = Read-WeatherQualificationHostAttempt -ManifestPath $ManifestPath -ExpectedManifestSha256 $ManifestSha256
    $m = $state.Contract.Manifest
    if ([string]$m.expected_tip -cne $Source -or [string]$m.baseline.master -cne $Baseline -or
        -not (Test-WeatherIntegrationPathEqual -Left $ProductionRoot -Right ([string]$m.repo_root)) -or
        -not (Test-WeatherIntegrationPathEqual -Left $SelfPath -Right ([string]$m.orchestration.quiet_merge.path))) {
        throw 'Split primitive arguments differ from the adopted attempt'
    }
    Assert-WeatherQualificationMergeController -State $state
    Assert-WeatherQualificationDelegatedMerge -State $state | Out-Null
    if ((Get-Date).ToString('yyyy-MM-dd') -cne [string]$state.Plan.local_day -or (Get-Date).Hour -lt 1 -or (Get-Date).Hour -ge 4) {
        throw 'Split merge missed its same-day quiet window'
    }
    $directory = Join-Path $state.Contract.AttemptRoot 'merge-work'
    if (Test-Path -LiteralPath $directory) { throw 'Split merge namespace is spent' }
    [void][IO.Directory]::CreateDirectory($directory)
    Import-Module ScheduledTasks -ErrorAction Stop
    $envelope = [Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$state.Policy.host.audit_commit_bytes, 64)
    return [pscustomobject]@{ State = $state; Envelope = $envelope; GitOptions = @(); Last = $null; DomainOrdinal = 0; Proofs = [ordered]@{} }
}

function Invoke-WeatherQualificationMergeBoundary {
    param([Parameter(Mandatory = $true)]$Context,
          [Parameter(Mandatory = $true)][ValidateSet('prepare', 'before-config', 'prepared', 'before-stage', 'staged', 'before-commit', 'committed', 'before-push', 'published')][string]$Phase,
          [Parameter(Mandatory = $true)][string]$PreparedBaseline)
    $state = $Context.State; $m = $state.Contract.Manifest
    Assert-WeatherQualificationMergeController -State $state
    Assert-WeatherQualificationDelegatedMerge -State $state | Out-Null
    $maximum = $state.Measurements.phases.metadata.maximum
    $seconds = [int]$maximum.seconds
    if ($seconds -le 4 -or $seconds -gt 120 -or $seconds -gt [int]$state.Policy.host.metadata_seconds -or
        [UInt64]$maximum.commit_bytes -gt [UInt64]$state.Policy.host.audit_commit_bytes -or
        [UInt64]$maximum.working_set_bytes -gt [UInt64]$state.Policy.host.audit_working_set_bytes) { throw 'Merge metadata exceeds reviewed limits' }
    $directory = Join-Path (Join-Path $state.Contract.AttemptRoot 'merge-work') $Phase
    if (Test-Path -LiteralPath $directory) { throw 'Merge boundary namespace is spent' }
    [void][IO.Directory]::CreateDirectory($directory)
    Set-WeatherQualificationOfflineEnvironment -Profile $state.Profile -Scratch $directory
    $Context.Envelope.SetEnvelopeCommitLimit([UInt64]$maximum.commit_bytes)
    $end = [DateTimeOffset]::Now.Date.AddHours(4)
    $deadline = [DateTimeOffset]::Now.AddSeconds($seconds)
    if ($deadline.LocalDateTime -gt $end) { $deadline = [DateTimeOffset]::new($end) }
    $cleanup = 3
    $requestDeadline = $deadline.AddSeconds(-$cleanup - 1)
    $request = [ordered]@{ manifest_path = $state.Contract.ManifestPath; manifest_sha256 = $state.Contract.ManifestSha256
        phase = $Phase; prepared_baseline = $PreparedBaseline
        deadline = $requestDeadline.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", [Globalization.CultureInfo]::InvariantCulture) }
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'request.json') -Payload $request
    $ref = Get-WeatherQualificationReference -Root $directory -Name 'request.json'
    $python = Join-Path $state.Profile.tools.python.root $state.Profile.tools.python.path
    $tokens = @('-I', '-S', '-B', (Join-Path $m.control.root 'scripts/ops/qualification_merge_control.py'),
                (Join-Path $directory 'request.json'), [string]$ref.sha256)
    $capture = @(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
    $native = Invoke-WeatherQualificationProcess -Envelope $Context.Envelope -Executable $python -Tokens $tokens `
        -WorkingDirectory ([string]$m.control.root) -Transcript (Join-Path $directory 'native.log') `
        -DeadlineUtc $deadline -MaximumSeconds ($seconds - $cleanup) -TeardownSeconds $cleanup `
        -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) `
        -MaximumOutputBytes 2097152 -VolumePaths @([string]$m.repo_root, $directory) `
        -MinimumDiskBytes ([UInt64]$state.Policy.host.minimum_disk_bytes) -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
        -ResourceMode capture_s4u -ProductionRoot ([string]$m.repo_root) -CaptureBindings $capture
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
    if (-not $native.completed -or -not $native.teardown_proved -or $native.elapsed_ms -gt $seconds * 1000) {
        throw "Split merge boundary failed: $Phase; $($native.failure)"
    }
    $result = Read-WeatherQualificationReference -Root $directory -Reference (Get-WeatherQualificationReference -Root $directory -Name 'boundary.json')
    if ([string]$result.schema -cne 'qualification_merge_boundary_v2' -or [string]$result.phase -cne $Phase -or
        [string]$result.manifest_sha256 -cne $state.Contract.ManifestSha256 -or
        [string]$result.prepared_baseline -cne $PreparedBaseline -or $result.native_parent_completion_required -ne $true -or
        $result.integration_eligible -ne $false) { throw 'Split merge result binding differs' }
    $Context.GitOptions = @($result.git_options)
    Set-WeatherQualificationGitEnvironment -Options $Context.GitOptions
    $Context.Proofs[$Phase] = [ordered]@{
        boundary = Get-WeatherQualificationReference -Root $state.Contract.AttemptRoot -Name ("merge-work/$Phase/boundary.json")
        native = Get-WeatherQualificationReference -Root $state.Contract.AttemptRoot -Name ("merge-work/$Phase/native.json")
    }
    $Context.Last = $result
    return $result
}

function Assert-WeatherQualificationMutationFresh {
    param([Parameter(Mandatory = $true)]$Context, [Parameter(Mandatory = $true)][string]$Phase)
    $last = $Context.Last
    if ($null -eq $last -or [string]$last.phase -cne $Phase -or $null -eq $last.data_final) { throw 'No final current-input boundary' }
    $elapsed = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse([string]$last.data_final)).TotalSeconds
    if ($elapsed -lt 0 -or $elapsed -gt 5 -or (Get-Date).Hour -ge 4) { throw 'Current-input validation is more than five seconds from mutation' }
}

function Close-WeatherQualificationMerge {
    param([Parameter(Mandatory = $true)]$Context, [Parameter(Mandatory = $true)]$Lease)
    $zero = $false
    try { $snapshot = $Context.Envelope.Snapshot(); $zero = $snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID }
    finally {
        if (-not $zero) { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $Lease }
        $Context.Envelope.Dispose()
    }
    return $zero
}

function Invoke-WeatherQualificationDomain {
    param([Parameter(Mandatory = $true)]$Context,
          [Parameter(Mandatory = $true)][ValidateSet('capture', 'execution-status', 'documentation')][string]$Mode)
    $state = $Context.State; $m = $state.Contract.Manifest
    Assert-WeatherQualificationMergeController -State $state
    $maximum = $state.Measurements.phases.metadata.maximum
    $seconds = [int]$maximum.seconds
    if ($seconds -le 4 -or $seconds -gt 120) { throw 'Deferred baseline verifier exceeds metadata budget' }
    $Context.DomainOrdinal++
    $directory = Join-Path (Join-Path $state.Contract.AttemptRoot 'merge-work') ("domain-" + $Context.DomainOrdinal + '-' + $Mode)
    if (Test-Path -LiteralPath $directory) { throw 'Deferred baseline verifier namespace spent' }
    [void][IO.Directory]::CreateDirectory($directory)
    Set-WeatherQualificationOfflineEnvironment -Profile $state.Profile -Scratch $directory
    Set-WeatherQualificationGitEnvironment -Options $Context.GitOptions
    $python = Join-Path $state.Profile.tools.python.root $state.Profile.tools.python.path
    $tokens = @('-I', '-S', '-B', (Join-Path $m.control.root 'scripts/ops/qualification_domain_control.py'),
                $state.Contract.ManifestPath, $state.Contract.ManifestSha256, $Mode)
    $capture = @(Get-WeatherQualificationCaptureBindings -ProductionRoot ([string]$m.repo_root))
    $native = Invoke-WeatherQualificationProcess -Envelope $Context.Envelope -Executable $python -Tokens $tokens `
        -WorkingDirectory ([string]$m.control.root) -Transcript (Join-Path $directory 'output.json') `
        -DeadlineUtc ([DateTimeOffset]::UtcNow.AddSeconds($seconds)) -MaximumSeconds ($seconds - 3) -TeardownSeconds 3 `
        -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) `
        -MaximumOutputBytes 2097152 -VolumePaths @([string]$m.repo_root, $directory) `
        -MinimumDiskBytes ([UInt64]$state.Policy.host.minimum_disk_bytes) -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
        -ResourceMode capture_s4u -ProductionRoot ([string]$m.repo_root) -CaptureBindings $capture
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
    if (-not $native.completed -or -not $native.teardown_proved) { throw ('Deferred baseline verifier failed: ' + $native.failure) }
    $ref = Get-WeatherQualificationReference -Root $directory -Name 'output.json'
    Read-WeatherQualificationReference -Root $directory -Reference $ref | Out-Null
    $global:LASTEXITCODE = 0
    return [IO.File]::ReadAllText((Join-Path $directory 'output.json'), [Text.UTF8Encoding]::new($false, $true))
}

function Set-WeatherQualificationGitEnvironment {
    param([Parameter(Mandatory = $true)][string[]]$Options)
    if ($Options.Count -lt 3 -or $Options[0] -cne '--no-replace-objects' -or ($Options.Count % 2) -ne 1) { throw 'Fixed Git options malformed' }
    $count = 0
    for ($index = 1; $index -lt $Options.Count; $index += 2) {
        if ($Options[$index] -cne '-c') { throw 'Unexpected Git execution option' }
        $pair = $Options[$index + 1].Split(@('='), 2)
        if ($pair.Count -ne 2) { throw 'Malformed fixed Git setting' }
        [Environment]::SetEnvironmentVariable(('GIT_CONFIG_KEY_' + $count), $pair[0], 'Process')
        [Environment]::SetEnvironmentVariable(('GIT_CONFIG_VALUE_' + $count), $pair[1], 'Process')
        $count++
    }
    [Environment]::SetEnvironmentVariable('GIT_CONFIG_COUNT', [string]$count, 'Process')
    [Environment]::SetEnvironmentVariable('GIT_NO_REPLACE_OBJECTS', '1', 'Process')
    [Environment]::SetEnvironmentVariable('GIT_ATTR_NOSYSTEM', '1', 'Process')
}

function Assert-WeatherQualificationBoundaryFresh {
    param([Parameter(Mandatory = $true)]$Context, [Parameter(Mandatory = $true)][string]$Phase)
    if ($null -eq $Context.Last -or [string]$Context.Last.phase -cne $Phase) { throw 'Wrong mutation boundary' }
    $age = ([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse([string]$Context.Last.validated_at)).TotalSeconds
    if ($age -lt 0 -or $age -gt 5 -or (Get-Date).Hour -ge 4) { throw 'Mutation boundary expired before actual command' }
}
