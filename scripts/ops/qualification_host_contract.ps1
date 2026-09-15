# Native parent for the split host phase. No Scheduler/Git mutation occurs here.
# The public integration manifest reader remains the registration authority.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'qualification_durable_json.ps1')

function Read-WeatherQualificationReference {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)]$Reference)
    $names = @($Reference.PSObject.Properties.Name | Sort-Object)
    if (($names -join '|') -cne 'path|sha256|size' -or
        $Reference.path -isnot [string] -or $Reference.sha256 -cnotmatch '\A[0-9a-f]{64}\z' -or
        $Reference.size -is [bool] -or $Reference.size -lt 1 -or $Reference.size -gt 2097152) {
        throw 'Invalid bounded qualification record reference'
    }
    $parts = ([string]$Reference.path).Split('/')
    if ([IO.Path]::IsPathRooted([string]$Reference.path) -or [string]$Reference.path -match '[\\:]' -or
        @($parts | Where-Object { $_ -in @('', '.', '..') -or $_.TrimEnd(' ', '.') -cne $_ }).Count -gt 0) {
        throw 'Qualification reference escaped its evidence root'
    }
    $path = Join-Path $Root ([string]$Reference.path)
    Initialize-WeatherExecutionHostAssignmentReader
    $raw = [Weather.Operations.ExecutionHostAssignmentReaderV1]::ReadStableUtf8Json($path, 2097152, $null)
    $bytes = [Text.UTF8Encoding]::new($false, $true).GetBytes($raw)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $actual = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') }) } finally { $sha.Dispose() }
    if ($bytes.Length -ne $Reference.size -or $actual -cne [string]$Reference.sha256) { throw 'Qualification record bytes changed' }
    return ConvertFrom-WeatherExactJson -Text $raw
}

function Get-WeatherQualificationReference {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Name)
    $path = Join-Path $Root $Name
    $result = [pscustomobject]@{ path = $Name; sha256 = (Get-WeatherIntegrationFileSha256 -Path $path)
                               size = [Int64](Get-Item -LiteralPath $path).Length }
    Read-WeatherQualificationReference -Root $Root -Reference $result | Out-Null
    return $result
}

function Assert-WeatherQualificationNativeToolPins {
    param([Parameter(Mandatory = $true)]$Profile,[Parameter(Mandatory = $true)]$Policy,
          [Parameter(Mandatory = $true)]$Review,[Parameter(Mandatory = $true)][string]$GraphRoot)
    $expectedRef=$Review.environments.windows
    if([string]$Profile.schema -cne 'qualification_host_environment_v2' -or
        [string]$Profile.environment.path -cne [string]$expectedRef.path -or
        [string]$Profile.environment.sha256 -cne [string]$expectedRef.sha256 -or
        [Int64]$Profile.environment.size -ne [Int64]$expectedRef.size){throw 'Native launch environment is not the independently reviewed Windows environment'}
    $expected=Read-WeatherQualificationReference -Root $GraphRoot -Reference $expectedRef
    if([string]$expected.schema -cne 'qualification_environment_v2' -or [string]$expected.platform -cne 'windows'){throw 'Wrong native launch environment schema/platform'}
    $pins=@{python=[string]$expected.python.executable_sha256;git=[string]$expected.git.sha256
        powershell=[string]$expected.powershell.sha256;gh=[string]$Policy.verifier.gh_sha256}
    $names=@($Profile.tools.PSObject.Properties.Name | Sort-Object)
    if(($names -join '|') -cne 'gh|git|powershell|python'){throw 'Native launch tool set differs'}
    foreach($name in $pins.Keys){
        if($pins[$name] -cnotmatch '^[0-9a-f]{64}$' -or [string]$Profile.tools.PSObject.Properties[$name].Value.sha256 -cne $pins[$name]){
            throw ('Native launch executable is not independently pinned: '+$name)
        }
    }
}

function Read-WeatherQualificationHostAttempt {
    param([Parameter(Mandatory = $true)][string]$ManifestPath, [Parameter(Mandatory = $true)][string]$ExpectedManifestSha256)
    $path = Resolve-WeatherIntegrationPath -Path $ManifestPath
    $root = Split-Path -Parent $path
    $ref = Get-WeatherQualificationReference -Root $root -Name (Split-Path -Leaf $path)
    if ($ref.sha256 -cne $ExpectedManifestSha256) { throw 'Host attempt manifest hash differs' }
    $manifest = Read-WeatherQualificationReference -Root $root -Reference $ref
    if ([string]$manifest.schema -cne 'weather_integration_attempt_manifest_v2' -or
        [string]$manifest.qualification_mode -cne 'split_v2' -or
        [string]$manifest.attempt_id -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._-]{0,47}\z' -or
        $null -ne $manifest.PSObject.Properties['suite'] -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.attempt_root) -Right $root) -or
        -not (Test-WeatherIntegrationPathEqual -Left ([string]$manifest.control.root) -Right (Join-Path $root 'control'))) {
        throw 'Host entry requires an explicit canonical split attempt'
    }
    $production = [IO.Path]::GetFullPath([string]$manifest.repo_root).TrimEnd('\', '/')
    $attemptRoot = [IO.Path]::GetFullPath($root).TrimEnd('\', '/')
    if ($attemptRoot.Equals($production, [StringComparison]::OrdinalIgnoreCase) -or
        $attemptRoot.StartsWith($production + '\', [StringComparison]::OrdinalIgnoreCase) -or
        $production.StartsWith($attemptRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Split attempt namespace must be outside the production checkout'
    }
    $contract = [pscustomobject]@{ Manifest = $manifest; ManifestPath = $path; ManifestSha256 = $ref.sha256; AttemptRoot = $root }
    if ((Get-WeatherIntegrationPrerequisite -AttemptContract $contract).Role -cne 'host') { throw 'Wrong attempt prerequisite' }
    $plan = Read-WeatherQualificationReference -Root $root -Reference $manifest.host
    $profile = Read-WeatherQualificationReference -Root $root -Reference $plan.environment
    $policy = Read-WeatherQualificationReference -Root ([string]$manifest.qualification.root) -Reference $manifest.qualification.policy
    $measurements = Read-WeatherQualificationReference -Root $root -Reference $plan.measurements
    $review = Read-WeatherQualificationReference -Root ([string]$manifest.qualification.root) -Reference $manifest.qualification.review
    Assert-WeatherQualificationNativeToolPins -Profile $profile -Policy $policy -Review $review -GraphRoot ([string]$manifest.qualification.root)
    if ([string]$plan.schema -cne 'qualification_host_plan_v2' -or
        [string]$profile.schema -cne 'qualification_host_environment_v2' -or
        [string]$policy.schema -cne 'qualification_policy_v2' -or
        [string]$measurements.schema -cne 'qualification_host_measurement_v2') { throw 'Unreviewed host plan/environment/measurement record' }
    if ($null -ne $plan.audit) {
        $audit = Read-WeatherQualificationReference -Root $root -Reference $plan.audit
        if (-not (Test-WeatherIntegrationPathEqual -Left ([string]$audit.receipt_root) -Right (Join-Path $root 'audit-receipts'))) {
            throw 'Noncanonical host audit receipt namespace'
        }
    }
    return [pscustomobject]@{ Contract = $contract; Plan = $plan; Profile = $profile; Policy = $policy; Measurements = $measurements }
}

function Assert-WeatherQualificationControllerFiles {
    param([Parameter(Mandatory = $true)]$State)
    $m = $State.Contract.Manifest
    $closure = Read-WeatherQualificationReference -Root $State.Contract.AttemptRoot -Reference $m.control.closure
    if ([string]$closure.schema -cne 'qualification_control_closure_v2' -or
        [string]$closure.baseline -cne [string]$m.baseline.master) { throw 'Host control source is not from adopted B' }
    foreach ($name in @('integration_attempt_host.ps1', 'qualification_host_contract.ps1', 'integration_attempt_contract.ps1',
                        'qualification_host_identity.ps1', 'qualification_process.ps1', 'windows_kill_on_close_job.ps1',
                        'workload_admission.ps1', 'qualification_host_control.py')) {
        $relative = 'scripts/ops/' + $name
        $row = @($closure.files | Where-Object { [string]$_.path -ceq $relative })
        if ($row.Count -ne 1 -or (Get-WeatherIntegrationFileSha256 -Path (Join-Path $m.control.root $relative)) -cne [string]$row[0].sha256) {
            throw "Adopted native controller changed: $name"
        }
    }
    # Python's fixed child additionally checks every actual B Git blob and the
    # complete deferred import closure before it imports candidate code.
}

function Set-WeatherQualificationOfflineEnvironment {
    param([Parameter(Mandatory = $true)]$Profile, [Parameter(Mandatory = $true)][string]$Scratch)
    $values = @{}
    foreach ($name in @('SystemRoot', 'WINDIR', 'COMSPEC', 'SYSTEMDRIVE', 'PATHEXT')) {
        $value = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($value) { $values[$name] = $value }
    }
    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($name in @('python', 'git', 'powershell', 'gh')) {
        $tool = $Profile.tools.PSObject.Properties[$name].Value
        $path = Join-Path ([string]$tool.root) ([string]$tool.path)
        if (-not [IO.Path]::IsPathRooted($path) -or (Get-WeatherIntegrationFileSha256 -Path $path) -cne [string]$tool.sha256) {
            throw "Reviewed host executable drift: $name"
        }
        $directory = Split-Path -Parent $path
        if (-not $paths.Contains($directory.ToLowerInvariant())) { $paths.Add($directory.ToLowerInvariant()) }
    }
    $system32 = (Join-Path $values['SystemRoot'] 'System32').ToLowerInvariant()
    if (-not $paths.Contains($system32)) { $paths.Add($system32) }
    foreach ($name in @([Environment]::GetEnvironmentVariables().Keys)) { [Environment]::SetEnvironmentVariable([string]$name, $null, 'Process') }
    foreach ($name in $values.Keys) { [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process') }
    [Environment]::SetEnvironmentVariable('PATH', ($paths -join ';'), 'Process')
    foreach ($name in @('TEMP', 'TMP', 'TMPDIR', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')) {
        [Environment]::SetEnvironmentVariable($name, $Scratch, 'Process')
    }
    foreach ($name in @('PYTHONDONTWRITEBYTECODE', 'PYTHONNOUSERSITE', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD',
                        'WEATHER_INTEGRATION_TEST_OFFLINE', 'GIT_CONFIG_NOSYSTEM', 'GIT_LFS_SKIP_SMUDGE')) {
        [Environment]::SetEnvironmentVariable($name, '1', 'Process')
    }
    [Environment]::SetEnvironmentVariable('GIT_CONFIG_GLOBAL', 'NUL', 'Process')
    [Environment]::SetEnvironmentVariable('GIT_TERMINAL_PROMPT', '0', 'Process')
}

function Get-WeatherQualificationCaptureBindings {
    param([Parameter(Mandatory = $true)][string]$ProductionRoot)
    $result = @()
    foreach ($name in @('loop_status.json', 'clob_loop_status.json', 'observation_trigger_status.json')) {
        $path = Join-Path (Join-Path $ProductionRoot 'data/snapshots') $name
        $status = Read-WeatherIntegrationSharedJson -Path $path
        $worker = Get-Process -Id ([int]$status.pid) -ErrorAction Stop
        try { $result += [pscustomobject]@{ name = $name; pid = [int]$status.pid; creation_utc_ticks = $worker.StartTime.ToUniversalTime().Ticks } }
        finally { $worker.Dispose() }
    }
    Assert-WeatherQualificationCapture -ProductionRoot $ProductionRoot -Bindings $result
    return $result
}

function Invoke-WeatherQualificationHostPhase {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)]$Envelope,
          [Parameter(Mandatory = $true)][ValidateSet('probes', 'audit', 'metadata', 'teardown')][string]$Phase,
          [Parameter(Mandatory = $true)][object[]]$CaptureBindings)
    $m, $plan = $State.Contract.Manifest, $State.Plan
    $maximum = $State.Measurements.phases.PSObject.Properties[$Phase].Value.maximum
    $seconds = [int]$maximum.seconds
    $ceiling = [int]$State.Policy.host.PSObject.Properties[$Phase + '_seconds'].Value
    $commitCeiling = if ($Phase -eq 'probes') { [UInt64]$State.Policy.host.probe_commit_bytes } else { [UInt64]$State.Policy.host.audit_commit_bytes }
    $workingCeiling = if ($Phase -eq 'probes') { [UInt64]$State.Policy.host.probe_commit_bytes } else { [UInt64]$State.Policy.host.audit_working_set_bytes }
    if ($seconds -lt 1 -or $seconds -gt $ceiling -or $seconds -gt [int]$plan.phase_seconds.PSObject.Properties[$Phase].Value -or
        [UInt64]$maximum.commit_bytes -gt $commitCeiling -or [UInt64]$maximum.working_set_bytes -gt $workingCeiling -or
        [UInt64]$State.Policy.host.minimum_disk_bytes -lt 53687091200) { throw 'Host phase exceeds the reviewed production ceiling' }
    Assert-WeatherQualificationControllerFiles -State $State
    $directory = Join-Path (Join-Path $State.Contract.AttemptRoot 'host-work') $Phase
    if (Test-Path -LiteralPath $directory) { throw "Host phase namespace already exists: $Phase" }
    [void][IO.Directory]::CreateDirectory($directory)
    Set-WeatherQualificationOfflineEnvironment -Profile $State.Profile -Scratch $directory
    $Envelope.SetEnvelopeCommitLimit([UInt64]$maximum.commit_bytes)
    $python = Join-Path $State.Profile.tools.python.root $State.Profile.tools.python.path
    $script = Join-Path $m.control.root 'scripts/ops/qualification_host_control.py'
    $tokens = @('-I', '-S', '-B', $script, $State.Contract.ManifestPath, $State.Contract.ManifestSha256, $Phase)
    # Each phase budget includes cleanup; preserve every later reviewed phase
    # plus two seconds for the final bounded parent publication.
    $order = @('probes', 'audit', 'metadata', 'teardown')
    $reserved = 2
    for ($index = [Array]::IndexOf($order, $Phase) + 1; $index -lt $order.Count; $index++) {
        $reserved += [int]$State.Measurements.phases.PSObject.Properties[$order[$index]].Value.maximum.seconds
    }
    $deadline = [DateTimeOffset]::Parse([string]$plan.deadline).AddSeconds(-$reserved)
    $cleanupSeconds = [Math]::Min(30, [Math]::Max(1, [int][Math]::Floor($seconds / 4)))
    if ($seconds -le $cleanupSeconds) { throw 'Reviewed phase leaves no execution and cleanup budget' }
    $native = Invoke-WeatherQualificationProcess -Envelope $Envelope -Executable $python -Tokens $tokens `
        -WorkingDirectory ([string]$m.control.root) -Transcript (Join-Path $directory 'native.log') `
        -DeadlineUtc $deadline -MaximumSeconds ($seconds - $cleanupSeconds) -TeardownSeconds $cleanupSeconds `
        -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) `
        -MaximumOutputBytes 2097152 -VolumePaths @([string]$m.repo_root, $directory) `
        -MinimumDiskBytes ([UInt64]$State.Policy.host.minimum_disk_bytes) -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
        -ResourceMode capture_s4u -ProductionRoot ([string]$m.repo_root) -CaptureBindings $CaptureBindings
    Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
    if (-not $native.teardown_proved) { throw 'Host phase has no zero-child proof; admission must remain poisoned' }
    if (-not $native.completed -or $native.elapsed_ms -gt ($seconds * 1000)) { throw "Host phase failed: $Phase; $($native.failure)" }
    $ref = Get-WeatherQualificationReference -Root $directory -Name 'phase.json'
    $result = Read-WeatherQualificationReference -Root $directory -Reference $ref
    if ([string]$result.schema -cne 'qualification_host_phase_v2' -or [string]$result.phase -cne $Phase -or
        [string]$result.manifest_sha256 -cne $State.Contract.ManifestSha256 -or
        [string]$result.host_plan_sha256 -cne [string]$m.host.sha256 -or
        $result.native_parent_completion_required -ne $true -or $result.integration_eligible -ne $false) { throw 'Host phase output binding differs' }
    return [pscustomobject]@{ Result = $result; Native = $native
        NativeReference = (Get-WeatherQualificationReference -Root $State.Contract.AttemptRoot -Name "host-work/$Phase/native.json") }
}
