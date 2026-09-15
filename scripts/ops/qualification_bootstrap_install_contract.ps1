# Independently pinned first-landing hooks for the existing guarded primitive.
# This contract reads only the closed bootstrap envelope, never a v2 manifest.
Set-StrictMode -Version Latest
. (Join-Path $PSScriptRoot 'qualification_bootstrap_probe_contract.ps1')

function Assert-WeatherBootstrapInstallWindow {
    param($Value)
    $start=[DateTimeOffset]::Parse([string]$Value.not_before)
    $end=[DateTimeOffset]::Parse([string]$Value.deadline)
    $now=[DateTimeOffset]::Now
    if($now -lt $start -or $now -ge $end -or ($end-$start).TotalSeconds -le 120 -or
        ($end-$start).TotalSeconds -gt 2700 -or $now.Hour -lt 1 -or $now.Hour -ge 4 -or
        $start.LocalDateTime.Date -ne $now.LocalDateTime.Date -or
        $end -gt [DateTimeOffset]::new($now.Date.AddHours(4))) { throw 'First landing missed its exact quiet window' }
    return $end
}

function Assert-WeatherBootstrapInstallLimits {
    param($Value)
    $limits=$Value.limits
    Assert-WeatherBootstrapProbeFields $limits @('commit_bytes','working_set_bytes','scratch_bytes','read_bytes',
        'metadata_seconds','metadata_read_bytes','teardown_seconds')
    foreach($name in @($limits.PSObject.Properties.Name)) {
        $number=$limits.PSObject.Properties[$name].Value
        if($number -is [bool] -or ($number -isnot [int] -and $number -isnot [long]) -or $number -le 0) {
            throw 'Invalid first-landing native limit'
        }
    }
    if($limits.commit_bytes -lt 67108864 -or $limits.commit_bytes -gt 2147483648 -or
        $limits.working_set_bytes -lt 67108864 -or $limits.working_set_bytes -gt $limits.commit_bytes -or
        $limits.working_set_bytes -gt 1610612736 -or $limits.scratch_bytes -gt 134217728 -or
        $limits.read_bytes -gt 68719476736 -or $limits.metadata_seconds -lt 10 -or $limits.metadata_seconds -gt 120 -or
        $limits.metadata_read_bytes -gt 4294967296 -or $limits.metadata_read_bytes -gt $limits.read_bytes -or
        $limits.teardown_seconds -lt 10 -or $limits.teardown_seconds -gt 60) { throw 'First-landing cap exceeds fixed policy' }
}

function Read-WeatherBootstrapInstallEnvelope {
    param([string]$Path,[string]$Sha256)
    $root=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($Path))
    $ref=Get-WeatherBootstrapProbeReference $root ([IO.Path]::GetFileName($Path))
    if($ref.sha256 -cne $Sha256) { throw 'First-landing envelope changed' }
    $value=Read-WeatherBootstrapProbeReference $root $ref
    Assert-WeatherBootstrapProbeFields $value @('schema','bootstrap_id','operation','repo_root','candidate','baseline','source',
        'branch_ref','qualification','control','baseline_control','environment','configuration','effective_tree','host','task',
        'not_before','deadline','limits','adopted_helpers','review_evidence','approval','probe','rollback','evidence_root')
    if($value.schema -cne 'qualification_bootstrap_install_envelope_v1' -or
        $value.operation -cne 'install_control_plane_K_once' -or
        $value.approval.replaces_full_host_suite_for_K_only -isnot [bool] -or
        -not $value.approval.replaces_full_host_suite_for_K_only -or
        [string]::IsNullOrWhiteSpace([string]$value.approval.owner) -or
        [string]$value.bootstrap_id -cnotmatch '^[A-Za-z0-9]{1,40}$' -or
        [string]$value.baseline -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$value.source.commit -cnotmatch '^[0-9a-f]{40}$' -or
        [string]$value.effective_tree -cnotmatch '^[0-9a-f]{40}$') { throw 'Not an explicitly approved K-only installation envelope' }
    Assert-WeatherBootstrapInstallLimits $value
    return $value
}

function Assert-WeatherBootstrapCompletedProbeTask {
    param($Value)
    $probeRoot=Assert-WeatherBootstrapProbePath ([string]$Value.probe.root)
    $probe=Read-WeatherBootstrapProbeReference $probeRoot $Value.probe.envelope
    $invocation=Read-WeatherBootstrapProbeReference $probeRoot (Get-WeatherBootstrapProbeReference $probeRoot 'probe-work/invocation.json')
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$xmlSha=-join($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes([string]$invocation.task_xml)) | ForEach-Object {$_.ToString('x2')})}
    finally {$sha.Dispose()}
    if($xmlSha -cne [string]$Value.probe.task_xml_sha256) { throw 'Retained probe task definition changed' }
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $task=$scheduler.GetFolder('\').GetTask([string]$probe.task.name)
    if([string]$task.Xml -cne [string]$invocation.task_xml -or [int]$task.State -notin @(1,3) -or
        @($task.GetInstances(1)).Count -ne 0 -or [int]$task.LastTaskResult -ne 0 -or
        [DateTimeOffset]::new([datetime]$task.LastRunTime) -lt [DateTimeOffset]::Parse([string]$probe.not_before).AddSeconds(-2) -or
        [DateTimeOffset]::new([datetime]$task.LastRunTime) -ge [DateTimeOffset]::Parse([string]$probe.deadline)) {
        throw 'Probe task is changed, unfinished, failed or uncorrelated'
    }
}

function Assert-WeatherBootstrapInstallDelegation {
    param($Context)
    $value=$Context.Value;$root=$Context.Root
    $claim=Read-WeatherBootstrapProbeReference $root (Get-WeatherBootstrapProbeReference $root 'install-use.json')
    $invocation=Read-WeatherBootstrapProbeReference $root (Get-WeatherBootstrapProbeReference $root 'install-work/invocation.json')
    $monitor=Read-WeatherBootstrapProbeReference $root (Get-WeatherBootstrapProbeReference $root 'install-work/monitor.json')
    $identity=Get-WeatherQualificationCurrentLogon
    if($identity.logon_type -ne 4 -or $identity.token_type -ne 1 -or $identity.elevated -or
        $identity.sid -cne [string]$value.host.user_sid -or
        $identity.authentication_id -cne [string]$invocation.token.authentication_id -or
        $claim.envelope_sha256 -cne $Context.Sha256 -or
        $monitor.envelope_sha256 -cne $Context.Sha256 -or
        [int]$monitor.parent_pid -ne [int]$claim.parent_pid -or
        [Int64]$monitor.parent_creation_utc_ticks -ne [Int64]$claim.parent_creation_utc_ticks) {
        throw 'First-landing delegation token/claim differs'
    }
    $current=Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    if([int]$current.ParentProcessId -ne [int]$monitor.pid) { throw 'Primitive is not the fixed monitor child' }
    $powershell=Join-Path $Context.State.Profile.tools.powershell.root $Context.State.Profile.tools.powershell.path
    $closure=Read-WeatherBootstrapProbeReference $root $value.control.closure
    $outerPin=@($closure.files | Where-Object path -CEQ 'scripts/ops/bootstrap_qualification_install.ps1')[0]
    foreach($row in @(
        @{pid=[int]$monitor.pid;created=[Int64]$monitor.creation_utc_ticks;parent=[int]$claim.parent_pid;tokens=@(
            '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
            (Join-Path $value.control.root 'scripts/ops/qualification_bootstrap_install_child.ps1'),
            '-EnvelopePath',$Context.Path,'-ExpectedEnvelopeSha256',$Context.Sha256,
            '-ParentPid',[string]$claim.parent_pid,'-ParentCreationUtcTicks',[string]$claim.parent_creation_utc_ticks)},
        @{pid=[int]$claim.parent_pid;created=[Int64]$claim.parent_creation_utc_ticks;parent=0;tokens=@(
            '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
            (Join-Path $value.control.root 'scripts/ops/bootstrap_qualification_install.ps1'),
            '-EnvelopePath',$Context.Path,'-ExpectedEnvelopeSha256',$Context.Sha256,'-ExpectedAdapterSha256',[string]$outerPin.sha256)}
    )) {
        $process=Get-Process -Id $row.pid -ErrorAction Stop
        try {
            if($process.StartTime.ToUniversalTime().Ticks -ne $row.created -or $process.MainModule.FileName -ine $powershell) {
                throw 'First-landing parent generation/image differs'
            }
        } finally {$process.Dispose()}
        $native=Get-CimInstance Win32_Process -Filter ("ProcessId="+$row.pid) -ErrorAction Stop
        if($row.parent -gt 0 -and [int]$native.ParentProcessId -ne $row.parent) { throw 'First-landing parent lineage differs' }
        $argv=[Weather.Operations.QualificationLogonReader]::Arguments([string]$native.CommandLine)
        if((ConvertTo-WeatherWindowsArgumentString -Tokens @($argv | Select-Object -Skip 1)) -cne
            (ConvertTo-WeatherWindowsArgumentString -Tokens $row.tokens)) { throw 'First-landing parent command changed' }
    }
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $task=$scheduler.GetFolder('\').GetTask([string]$value.task.name);$instances=@($task.GetInstances(1))
    if([string]$task.Xml -cne [string]$invocation.task_xml -or $instances.Count -ne 1 -or
        [int]$instances[0].State -ne 4 -or [string]$instances[0].InstanceGuid -cne [string]$invocation.instance_guid -or
        [int]$instances[0].EnginePID -ne [int]$invocation.engine_pid) { throw 'First-landing task instance changed' }
}

function Initialize-WeatherBootstrapInstallMerge {
    param([string]$ManifestPath,[string]$ManifestSha256,[string]$ProductionRoot,[string]$Source,[string]$Baseline,[string]$SelfPath)
    $value=Read-WeatherBootstrapInstallEnvelope $ManifestPath $ManifestSha256
    [void](Assert-WeatherBootstrapInstallWindow $value)
    $root=[IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ManifestPath))
    if([IO.Path]::GetFullPath($ProductionRoot) -ine [string]$value.repo_root -or
        $Source -cne [string]$value.source.commit -or $Baseline -cne [string]$value.baseline -or
        [IO.Path]::GetFullPath($SelfPath) -ine (Join-Path $value.control.root 'scripts/ops/quiet_window_merge.ps1')) {
        throw 'First-landing primitive arguments differ'
    }
    $profile=Read-WeatherBootstrapProbeReference $root $value.environment
    $state=[pscustomobject]@{Profile=$profile;Contract=[pscustomobject]@{AttemptRoot=(Join-Path $root 'install-work')}}
    $context=[pscustomobject]@{Value=$value;Root=$root;Path=$ManifestPath;Sha256=$ManifestSha256;State=$state
        Envelope=$null;GitOptions=@();Last=$null;DomainOrdinal=0;Proofs=[ordered]@{}}
    Assert-WeatherBootstrapInstallDelegation $context
    Assert-WeatherBootstrapCompletedProbeTask $value
    $directory=Join-Path $root 'install-work/merge-work'
    if(Test-Path -LiteralPath $directory) { throw 'First-landing merge namespace is spent' }
    [void][IO.Directory]::CreateDirectory($directory)
    Import-Module ScheduledTasks -ErrorAction Stop
    $context.Envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$value.limits.commit_bytes,64)
    return $context
}

function Invoke-WeatherBootstrapInstallNative {
    param($Context,[string]$Directory,[string[]]$Tokens,[string]$Transcript)
    [void](Assert-WeatherBootstrapInstallWindow $Context.Value)
    Assert-WeatherBootstrapInstallDelegation $Context
    $seconds=[int]$Context.Value.limits.metadata_seconds
    $end=[DateTimeOffset]::Parse([string]$Context.Value.deadline).AddSeconds(-2*[int]$Context.Value.limits.teardown_seconds-15)
    $deadline=[DateTimeOffset]::UtcNow.AddSeconds($seconds)
    if($deadline -gt $end) {$deadline=$end}
    $seconds=[int][Math]::Floor(($deadline-[DateTimeOffset]::UtcNow).TotalSeconds)
    if($seconds -le 5) { throw 'First-landing boundary has no teardown reserve' }
    Set-WeatherBootstrapProbeEnvironment $Context.State.Profile $Directory
    if($Context.GitOptions.Count) {Set-WeatherQualificationGitEnvironment $Context.GitOptions}
    $capture=@(Get-WeatherBootstrapProbeCaptureBindings $Context.Value.repo_root)
    $python=Join-Path $Context.State.Profile.tools.python.root $Context.State.Profile.tools.python.path
    $limit=[UInt64]$Context.Envelope.Snapshot().ReadBytes+[UInt64]$Context.Value.limits.metadata_read_bytes
    $native=Invoke-WeatherQualificationProcess -Envelope $Context.Envelope -Executable $python -Tokens $Tokens `
        -WorkingDirectory $Context.Value.control.root -Transcript $Transcript -DeadlineUtc $deadline `
        -MaximumSeconds ($seconds-3) -TeardownSeconds 3 -CommitBytes ([UInt64]$Context.Value.limits.commit_bytes) `
        -WorkingSetBytes ([UInt64]$Context.Value.limits.working_set_bytes) -MaximumOutputBytes 2097152 `
        -VolumePaths @($Context.Value.repo_root,$Context.Root) -MinimumDiskBytes 53687091200 `
        -ReservedScratchBytes ([UInt64]$Context.Value.limits.scratch_bytes) -MaximumReadBytes $limit `
        -ResourceMode capture_s4u -ProductionRoot $Context.Value.repo_root -CaptureBindings $capture
    Write-WeatherBootstrapProbeRecord (Join-Path $Directory 'native.json') $native
    if(-not $native.completed -or -not $native.teardown_proved -or $native.exit_code -ne 0 -or $native.failure) {
        throw ('First-landing native boundary failed: '+$native.failure)
    }
}

function Invoke-WeatherQualificationMergeBoundary {
    param($Context,[ValidateSet('prepare','before-config','prepared','before-stage','staged','before-commit','committed','before-push','published')][string]$Phase,
          [string]$PreparedBaseline)
    $directory=Join-Path $Context.Root ('install-work/merge-work/'+$Phase)
    if(Test-Path -LiteralPath $directory) { throw 'First-landing boundary is spent' }
    [void][IO.Directory]::CreateDirectory($directory)
    $deadline=[DateTimeOffset]::UtcNow.AddSeconds([int]$Context.Value.limits.metadata_seconds-5)
    $end=[DateTimeOffset]::Parse([string]$Context.Value.deadline).AddSeconds(-2*[int]$Context.Value.limits.teardown_seconds-20)
    if($deadline -gt $end) {$deadline=$end}
    $request=[ordered]@{envelope_path=$Context.Path;envelope_sha256=$Context.Sha256;phase=$Phase
        prepared_baseline=$PreparedBaseline;deadline=$deadline.UtcDateTime.ToString('o')}
    Write-WeatherBootstrapProbeRecord (Join-Path $directory 'request.json') $request
    $ref=Get-WeatherBootstrapProbeReference $directory 'request.json'
    $tokens=@('-I','-S','-B',(Join-Path $Context.Value.control.root 'scripts/ops/qualification_bootstrap_install_control.py'),
        (Join-Path $directory 'request.json'),[string]$ref.sha256)
    Invoke-WeatherBootstrapInstallNative $Context $directory $tokens (Join-Path $directory 'native.log')
    $result=Read-WeatherBootstrapProbeReference $directory (Get-WeatherBootstrapProbeReference $directory 'boundary.json')
    if($result.schema -cne 'qualification_bootstrap_install_boundary_v1' -or $result.envelope_sha256 -cne $Context.Sha256 -or
        $result.phase -cne $Phase -or $result.prepared_baseline -cne $PreparedBaseline -or
        $result.effective_tree -cne $Context.Value.effective_tree -or
        $result.integration_eligible -isnot [bool] -or $result.integration_eligible -or
        $result.native_parent_completion_required -isnot [bool] -or -not $result.native_parent_completion_required) {
        throw 'First-landing boundary binding differs'
    }
    $Context.GitOptions=@($result.git_options)
    Set-WeatherQualificationGitEnvironment $Context.GitOptions
    $Context.Proofs[$Phase]=[ordered]@{
        boundary=Get-WeatherBootstrapProbeReference $Context.State.Contract.AttemptRoot ('merge-work/'+$Phase+'/boundary.json')
        native=Get-WeatherBootstrapProbeReference $Context.State.Contract.AttemptRoot ('merge-work/'+$Phase+'/native.json')}
    $Context.Last=$result
    return $result
}

function Invoke-WeatherQualificationDomain {
    param($Context,[ValidateSet('capture','execution-status','documentation')][string]$Mode)
    $Context.DomainOrdinal++
    $directory=Join-Path $Context.Root ('install-work/merge-work/domain-'+$Context.DomainOrdinal+'-'+$Mode)
    if(Test-Path -LiteralPath $directory) {throw 'First-landing domain namespace is spent'}
    [void][IO.Directory]::CreateDirectory($directory)
    $tokens=@('-I','-S','-B',(Join-Path $Context.Value.control.root 'scripts/ops/qualification_bootstrap_install_domain.py'),
        $Context.Path,$Context.Sha256,$Mode)
    Invoke-WeatherBootstrapInstallNative $Context $directory $tokens (Join-Path $directory 'output.json')
    [void](Read-WeatherBootstrapProbeReference $directory (Get-WeatherBootstrapProbeReference $directory 'output.json'))
    $global:LASTEXITCODE=0
    return [IO.File]::ReadAllText((Join-Path $directory 'output.json'),[Text.UTF8Encoding]::new($false,$true))
}

function Assert-WeatherQualificationMutationFresh {
    param($Context,[string]$Phase)
    if($null -eq $Context.Last -or $Context.Last.phase -cne $Phase -or $null -eq $Context.Last.data_final) {
        throw 'First landing lacks a final current-configuration boundary'
    }
    $age=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse([string]$Context.Last.data_final)).TotalSeconds
    if($age -lt 0 -or $age -gt 5) {throw 'First-landing current-configuration check expired'}
    [void](Assert-WeatherBootstrapInstallWindow $Context.Value)
}

function Assert-WeatherQualificationBoundaryFresh {
    param($Context,[string]$Phase)
    if($null -eq $Context.Last -or $Context.Last.phase -cne $Phase) {throw 'Wrong first-landing mutation boundary'}
    $age=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse([string]$Context.Last.validated_at)).TotalSeconds
    if($age -lt 0 -or $age -gt 5) {throw 'First-landing mutation check expired'}
    [void](Assert-WeatherBootstrapInstallWindow $Context.Value)
}

function Close-WeatherBootstrapInstallMerge {
    param($Context)
    $snapshot=$Context.Envelope.Snapshot()
    $zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID
    Write-WeatherBootstrapProbeRecord (Join-Path $Context.Root 'install-work/quiet-native.json') ([ordered]@{
        schema='qualification_bootstrap_install_quiet_native_v1';envelope_sha256=$Context.Sha256;children_zero=$zero
        native_read_bytes=[UInt64]$snapshot.ReadBytes;native_peak_commit_bytes=[UInt64]$snapshot.PeakCommitBytes})
    $Context.Envelope.Dispose()
    if(-not $zero) {throw 'First-landing primitive retained descendants'}
}

# Report references keep the guarded primitive's existing relative-path shape.
function Get-WeatherQualificationReference {
    param([string]$Root,[string]$Name)
    return Get-WeatherBootstrapProbeReference $Root $Name
}
function Assert-WeatherBootstrapInstallInvocation {
    param($Envelope,[string]$EnvelopePath,[string]$EnvelopeSha256,[string]$AdapterSha256,[string]$ScriptPath)
    if((Get-WeatherExecutionHostId) -cne [string]$Envelope.host.host_id -or
        (Get-WeatherExecutionPrincipalId) -cne [string]$Envelope.host.principal_id) { throw 'Bootstrap host/principal differs' }
    $assignment=Get-WeatherExecutionHostAssignment -RepoRoot ([string]$Envelope.repo_root)
    if([string]$assignment.dedicated_capture_execution_host_id -cne [string]$Envelope.host.host_id) {
        throw 'Bootstrap requires the dedicated capture installation'
    }
    $identity=Get-WeatherQualificationCurrentLogon
    if($identity.logon_type -ne 4 -or $identity.token_type -ne 1 -or $identity.elevated -or
        $identity.sid -cne [string]$Envelope.host.user_sid) { throw 'Bootstrap requires its exact unelevated primary batch token' }
    $name='WeatherQualificationBootstrapInstall_'+[string]$Envelope.bootstrap_id
    if([string]$Envelope.task.name -cne $name) { throw 'Bootstrap task name differs' }
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $task=$scheduler.GetFolder('\').GetTask($name);$xml=[string]$task.Xml;$definition=$task.Definition
    $tokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$ScriptPath,
        '-EnvelopePath',$EnvelopePath,'-ExpectedEnvelopeSha256',$EnvelopeSha256,'-ExpectedAdapterSha256',$AdapterSha256)
    $arguments=ConvertTo-WeatherWindowsArgumentString -Tokens $tokens
    $powershell=Join-Path $PSHOME 'powershell.exe'
    $sid=([Security.Principal.NTAccount]::new([string]$definition.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
    if($sid -cne $identity.sid -or [int]$definition.Principal.LogonType -ne 2 -or [int]$definition.Principal.RunLevel -ne 0 -or
        $definition.Actions.Count -ne 1 -or [int]$definition.Actions.Item(1).Type -ne 0 -or
        [IO.Path]::GetFullPath([string]$definition.Actions.Item(1).Path) -ine $powershell -or
        [string]$definition.Actions.Item(1).Arguments -cne $arguments -or
        [IO.Path]::GetFullPath([string]$definition.Actions.Item(1).WorkingDirectory) -ine [string]$Envelope.repo_root -or
        $definition.Triggers.Count -ne 1 -or [int]$definition.Triggers.Item(1).Type -ne 1 -or
        [DateTimeOffset]::Parse([string]$definition.Triggers.Item(1).StartBoundary) -ne [DateTimeOffset]::Parse([string]$Envelope.not_before) -or
        $definition.Settings.StartWhenAvailable -or [int]$definition.Settings.MultipleInstances -ne 2 -or
        [string]$definition.Settings.ExecutionTimeLimit -cne 'PT46M') { throw 'Bootstrap task definition differs' }
    $current=Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    $actual=[Weather.Operations.QualificationLogonReader]::Arguments([string]$current.CommandLine)
    if($identity.image -ine $powershell -or
        (ConvertTo-WeatherWindowsArgumentString -Tokens @($actual | Select-Object -Skip 1)) -cne $arguments) {
        throw 'Actual bootstrap invocation differs'
    }
    $instances=@($task.GetInstances(1))
    if($instances.Count -ne 1 -or [int]$instances[0].State -ne 4) { throw 'Bootstrap lacks one running task instance' }
    $engine=[int]$instances[0].EnginePID
    $lineage=@([pscustomobject]@{pid=$PID;creation_utc_ticks=$identity.creation_utc_ticks})
    for($depth=0;$depth -lt 2 -and $engine -notin @($lineage.pid);$depth++) {
        $parentId=[int]$current.ParentProcessId
        if($parentId -le 0 -or $parentId -in @($lineage.pid)) { throw 'Bootstrap lineage is ambiguous' }
        $parent=Get-Process -Id $parentId -ErrorAction Stop
        try {$created=$parent.StartTime.ToUniversalTime().Ticks} finally {$parent.Dispose()}
        if($created -gt $lineage[-1].creation_utc_ticks) { throw 'Bootstrap parent generation differs' }
        $lineage+=([pscustomobject]@{pid=$parentId;creation_utc_ticks=$created})
        $current=Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction Stop
    }
    if($engine -notin @($lineage.pid) -or [string]$task.Xml -cne $xml) { throw 'Bootstrap Scheduler instance changed' }
    return [ordered]@{token=$identity;ancestry=$lineage;engine_pid=$engine;instance_guid=[string]$instances[0].InstanceGuid;task_xml=$xml}
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


function Assert-WeatherBootstrapInstallCompletion {
    param($Value,[string]$Sha256,$Native,$QuietNative,$Report)
    Assert-WeatherBootstrapProbeFields $Native @('schema','envelope_sha256','native','native_read_bytes')
    Assert-WeatherBootstrapProbeFields $QuietNative @('schema','envelope_sha256','children_zero','native_read_bytes','native_peak_commit_bytes')
    if($Native.schema -cne 'qualification_bootstrap_install_native_result_v1' -or
        $QuietNative.schema -cne 'qualification_bootstrap_install_quiet_native_v1' -or
        $Native.envelope_sha256 -cne $Sha256 -or $QuietNative.envelope_sha256 -cne $Sha256 -or
        $QuietNative.children_zero -isnot [bool] -or -not $QuietNative.children_zero) {throw 'Incomplete installer native identity'}
    foreach($name in @('completed','teardown_proved')) {
        if($Native.native.PSObject.Properties[$name].Value -isnot [bool] -or -not $Native.native.PSObject.Properties[$name].Value) {
            throw 'Installer completion/teardown was not proved'
        }
    }
    if(($Native.native.exit_code -isnot [int] -and $Native.native.exit_code -isnot [long]) -or $Native.native.exit_code -ne 0 -or $null -ne $Native.native.failure) {
        throw 'Installer native process failed'
    }
    foreach($pair in @(
        @{number=$Native.native_read_bytes;maximum=$Value.limits.read_bytes},
        @{number=$QuietNative.native_read_bytes;maximum=$Value.limits.read_bytes},
        @{number=$Native.native.native_peak_commit_bytes;maximum=$Value.limits.commit_bytes},
        @{number=$QuietNative.native_peak_commit_bytes;maximum=$Value.limits.commit_bytes},
        @{number=$Native.native.peak_working_set_bytes;maximum=$Value.limits.working_set_bytes}
    )) {
        if(($pair.number -isnot [int] -and $pair.number -isnot [long]) -or $pair.number -is [bool] -or
            $pair.number -lt 0 -or [UInt64]$pair.number -gt [UInt64]$pair.maximum) {throw 'Installer native budget exceeded'}
    }
    if($Report.schema -cne 'quiet_window_merge_report_v0.2' -or $Report.operation_mode -cne 'bootstrap_installation_v1' -or
        $Report.ok -isnot [bool] -or -not $Report.ok -or $Report.stage -cne 'pushed' -or
        $Report.publication_acknowledged -isnot [bool] -or -not $Report.publication_acknowledged -or
        $Report.capture_recovery_proved -isnot [bool] -or -not $Report.capture_recovery_proved -or
        $Report.documentation_transaction_recorded -isnot [bool] -or -not $Report.documentation_transaction_recorded -or
        $Report.expected_baseline -cne $Value.baseline -or $Report.baseline_commit -cne $Value.baseline -or
        $Report.expected_tip -cne $Value.source.commit -or $Report.resolved_branch_tip -cne $Value.source.commit -or
        $Report.branch -cne $Value.branch_ref -or [string]$Report.merge_commit -cnotmatch '^[0-9a-f]{40}$' -or
        $Report.bootstrap_installation.manifest_sha256 -cne $Sha256 -or
        $Report.bootstrap_installation.commit_invocation_started -isnot [bool] -or
        -not $Report.bootstrap_installation.commit_invocation_started) {throw 'Guarded installation did not prove exact publication'}
    $capture=$Report.bootstrap_installation.capture
    if($capture.ok -isnot [bool] -or -not $capture.ok -or @($capture.workers).Count -ne 3 -or
        @($capture.workers | Where-Object {$_.ok -isnot [bool] -or -not $_.ok}).Count) {throw 'Final capture proof missing'}
    $work=Join-Path $Value.evidence_root 'install-work'
    foreach($phase in @('prepare','prepared','before-stage','staged','before-commit','committed','before-push','published')) {
        $proof=$Report.bootstrap_installation.boundaries.PSObject.Properties[$phase].Value
        if($null -eq $proof -or $proof.boundary.path -cne ('merge-work/'+$phase+'/boundary.json') -or
            $proof.native.path -cne ('merge-work/'+$phase+'/native.json')) {throw 'Required installation boundary is absent'}
        $boundary=Read-WeatherBootstrapProbeReference $work $proof.boundary
        $nativeProof=Read-WeatherBootstrapProbeReference $work $proof.native
        if($boundary.schema -cne 'qualification_bootstrap_install_boundary_v1' -or $boundary.phase -cne $phase -or
            $boundary.envelope_sha256 -cne $Sha256 -or $boundary.effective_tree -cne $Value.effective_tree -or
            $nativeProof.completed -isnot [bool] -or -not $nativeProof.completed -or
            $nativeProof.teardown_proved -isnot [bool] -or -not $nativeProof.teardown_proved -or
            $nativeProof.exit_code -ne 0 -or $null -ne $nativeProof.failure) {throw 'Installation boundary is not complete'}
        if($phase -eq 'published' -and $boundary.head -cne $Report.merge_commit) {throw 'Published commit differs'}
    }
}

function Close-WeatherBootstrapInstallation {
    param($Value,[string]$EnvelopeSha256,[string]$ResultSha256)
    $root=[string]$Value.evidence_root
    $resultRef=Get-WeatherBootstrapProbeReference $root 'install-result.json'
    if($resultRef.sha256 -cne $ResultSha256) {throw 'Installed-result bytes changed'}
    $result=Read-WeatherBootstrapProbeReference $root $resultRef
    if($result.schema -cne 'qualification_bootstrap_install_result_v1' -or
        $result.status -cne 'PUBLISHED_CLOSEOUT_REQUIRED' -or $result.envelope_sha256 -cne $EnvelopeSha256 -or
        $result.outer_teardown_proved -isnot [bool] -or -not $result.outer_teardown_proved -or
        ($result.child_exit_code -isnot [int] -and $result.child_exit_code -isnot [long]) -or $result.child_exit_code -ne 0 -or
        $result.full_host_suite_pass -isnot [bool] -or $result.full_host_suite_pass -or
        $result.retry_authorized -isnot [bool] -or $result.retry_authorized -or
        $result.native.path -cne 'install-work/native-result.json' -or
        $result.quiet_native.path -cne 'install-work/quiet-native.json' -or $result.report.path -cne 'install-work/quiet-report.json' -or
        [DateTimeOffset]::Parse([string]$result.completed_at) -ge [DateTimeOffset]::Parse([string]$Value.deadline)) {
        throw 'Incomplete installation cannot be closed or upgraded'
    }
    $native=Read-WeatherBootstrapProbeReference $root $result.native
    $quietNative=Read-WeatherBootstrapProbeReference $root $result.quiet_native
    $report=Read-WeatherBootstrapProbeReference $root $result.report
    Assert-WeatherBootstrapInstallCompletion $Value $EnvelopeSha256 $native $quietNative $report
    if($result.merge_commit -cne $report.merge_commit -or $result.source.commit -cne $Value.source.commit -or
        $result.source.tree -cne $Value.source.tree -or $result.policy.sha256 -cne $Value.qualification.policy.sha256) {
        throw 'Installed policy/source identity differs'
    }
    $probe=Read-WeatherBootstrapProbeReference $Value.probe.root $Value.probe.envelope
    $probeInvocation=Read-WeatherBootstrapProbeReference $Value.probe.root (Get-WeatherBootstrapProbeReference $Value.probe.root 'probe-work/invocation.json')
    $installInvocation=Read-WeatherBootstrapProbeReference $root (Get-WeatherBootstrapProbeReference $root 'install-work/invocation.json')
    if($probe.task.name -cne ('WeatherQualificationBootstrapProbe_'+[string]$probe.bootstrap_id) -or
        $Value.task.name -cne ('WeatherQualificationBootstrapInstall_'+[string]$Value.bootstrap_id)) {throw 'Wrong closeout task names'}
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $targets=@(
        @{name=[string]$probe.task.name;xml=[string]$probeInvocation.task_xml;start=[string]$probe.not_before;end=[string]$probe.deadline},
        @{name=[string]$Value.task.name;xml=[string]$installInvocation.task_xml;start=[string]$Value.not_before;end=[string]$Value.deadline})
    foreach($target in $targets) {
        $task=$scheduler.GetFolder('\').GetTask($target.name)
        if([string]$task.Xml -cne $target.xml -or [int]$task.State -notin @(1,3) -or
            @($task.GetInstances(1)).Count -ne 0 -or [int]$task.LastTaskResult -ne 0 -or
            [DateTimeOffset]::new([datetime]$task.LastRunTime) -lt [DateTimeOffset]::Parse($target.start).AddSeconds(-2) -or
            [DateTimeOffset]::new([datetime]$task.LastRunTime) -ge [DateTimeOffset]::Parse($target.end)) {
            throw 'Closeout requires exact non-running successful tasks'
        }
    }
    # Claim before any task mutation. A partial/lost closeout is retained for
    # review and cannot be retried by ordinary installation or this command.
    Write-WeatherBootstrapProbeRecord (Join-Path $root 'close-use.json') ([ordered]@{
        schema='qualification_bootstrap_install_close_use_v1';envelope_sha256=$EnvelopeSha256;result_sha256=$ResultSha256
        retry_authorized=$false})
    $closed=@()
    foreach($target in $targets) {
        $task=$scheduler.GetFolder('\').GetTask($target.name)
        if([string]$task.Xml -cne $target.xml -or @($task.GetInstances(1)).Count -ne 0 -or [int]$task.State -notin @(1,3)) {
            throw 'Exact task changed before closeout mutation'
        }
        # Definition is a detached COM copy. Compute the exact expected
        # post-close XML before the singleton task mutation.
        $expectedDefinition=$task.Definition
        $expectedDefinition.Settings.Enabled=$false
        [xml]$expected=[string]$expectedDefinition.XmlText
        $task.Enabled=$false
        $after=$scheduler.GetFolder('\').GetTask($target.name)
        [xml]$actual=[string]$after.Xml
        if($after.Enabled -or [int]$after.State -ne 1 -or @($after.GetInstances(1)).Count -ne 0 -or
            $actual.OuterXml -cne $expected.OuterXml) {throw 'Exact task closeout was not proved'}
        $closed+=([ordered]@{name=$target.name;disabled=$true})
    }
    Write-WeatherBootstrapProbeRecord (Join-Path $root 'installed-root.json') ([ordered]@{
        schema='qualification_bootstrap_installed_root_v1';envelope_sha256=$EnvelopeSha256;result=$resultRef
        source=$Value.source;integration_commit=$result.merge_commit;policy=$Value.qualification.policy
        review=$Value.qualification.review;bootstrap_id_revoked=$Value.bootstrap_id;tasks=$closed
        future_attempts_require_split_qualification=$true;full_host_suite_pass=$false
        recorded_at=[DateTimeOffset]::UtcNow.ToString('o')})
}
