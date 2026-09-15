# Record feasibility under declared hard limits. This cannot arm or merge.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RequestPath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedRequestSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'integration_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_contract.ps1')
. (Join-Path $PSScriptRoot 'qualification_host_identity.ps1')
. (Join-Path $PSScriptRoot 'qualification_attempt_contract.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')

function Assert-WeatherMeasurementInvocation {
    param($Request,[string]$Path,[string]$Sha256,[string]$Script)
    $plan=$Request.plan
    if((Get-WeatherExecutionHostId) -cne [string]$plan.host_id -or
        (Get-WeatherExecutionPrincipalId) -cne [string]$plan.principal_id){throw 'Measurement host/principal differs'}
    $identity=Get-WeatherQualificationCurrentLogon
    if($identity.logon_type -ne 4 -or $identity.token_type -ne 1 -or $identity.elevated -or
        $identity.sid -cne [string]$Request.task.user_sid){throw 'Measurement requires its exact unelevated primary batch token'}
    $name='WeatherQualificationMeasure_'+[string]$Request.measurement_id
    if([string]$Request.task.name -cne $name){throw 'Measurement task name differs'}
    $scheduler=New-Object -ComObject 'Schedule.Service';$scheduler.Connect()
    $task=$scheduler.GetFolder('\').GetTask($name)
    $xml=[string]$task.Xml;$definition=$task.Definition
    $expected=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$Script,
        '-RequestPath',$Path,'-ExpectedRequestSha256',$Sha256)
    $arguments=ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens $expected
    $exe=Join-Path $PSHOME 'powershell.exe'
    $principalSid=([Security.Principal.NTAccount]::new([string]$definition.Principal.UserId)).Translate([Security.Principal.SecurityIdentifier]).Value
    if($principalSid -cne $identity.sid -or [int]$definition.Principal.LogonType -ne 2 -or [int]$definition.Principal.RunLevel -ne 0 -or
        $definition.Actions.Count -ne 1 -or [int]$definition.Actions.Item(1).Type -ne 0 -or
        -not (Test-WeatherIntegrationPathEqual -Left $definition.Actions.Item(1).Path -Right $exe) -or
        [string]$definition.Actions.Item(1).Arguments -cne $arguments -or
        -not (Test-WeatherIntegrationPathEqual -Left $definition.Actions.Item(1).WorkingDirectory -Right $Request.repo_root) -or
        $definition.Triggers.Count -ne 1 -or [int]$definition.Triggers.Item(1).Type -ne 1 -or
        [DateTimeOffset]::Parse([string]$definition.Triggers.Item(1).StartBoundary) -ne [DateTimeOffset]::Parse([string]$plan.not_before) -or
        $definition.Settings.StartWhenAvailable -or [int]$definition.Settings.MultipleInstances -ne 2 -or
        [string]$definition.Settings.ExecutionTimeLimit -cne 'PT34M'){throw 'Measurement task definition differs'}
    $current=Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction Stop
    $argv=[Weather.Operations.QualificationLogonReader]::Arguments([string]$current.CommandLine)
    if(-not (Test-WeatherIntegrationPathEqual -Left $identity.image -Right $exe) -or
        (ConvertTo-WeatherIntegrationScheduledTaskArgumentString -Tokens @($argv | Select-Object -Skip 1)) -cne $arguments){throw 'Actual measurement invocation differs'}
    $instances=@($task.GetInstances(1))
    if($instances.Count -ne 1 -or [int]$instances[0].State -ne 4){throw 'Measurement lacks one running instance'}
    $engine=[int]$instances[0].EnginePID
    $lineage=@([pscustomobject]@{pid=$PID;creation_utc_ticks=$identity.creation_utc_ticks})
    for($depth=0;$depth -lt 2 -and $engine -notin @($lineage.pid);$depth++){
        $parentId=[int]$current.ParentProcessId
        if($parentId -le 0 -or $parentId -in @($lineage.pid)){throw 'Measurement lineage is ambiguous'}
        $parent=Get-Process -Id $parentId -ErrorAction Stop
        try{$created=$parent.StartTime.ToUniversalTime().Ticks}finally{$parent.Dispose()}
        if($created -gt $lineage[-1].creation_utc_ticks){throw 'Measurement parent generation differs'}
        $lineage+=([pscustomobject]@{pid=$parentId;creation_utc_ticks=$created})
        $current=Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -ErrorAction Stop
    }
    if($engine -notin @($lineage.pid) -or [string]$task.Xml -cne $xml){throw 'Measurement Scheduler instance changed'}
    $sha=[Security.Cryptography.SHA256]::Create()
    try{$xmlSha=-join($sha.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($xml)) | ForEach-Object{$_.ToString('x2')})}finally{$sha.Dispose()}
    return [ordered]@{token=$identity;ancestry=$lineage;engine_pid=$engine;instance_guid=[string]$instances[0].InstanceGuid;task_xml_sha256=$xmlSha}
}

function Get-WeatherMeasurementScratchBytes {
    param([string]$Root,[UInt64]$MaximumBytes)
    $pending=New-Object 'System.Collections.Generic.Stack[string]';$pending.Push($Root)
    [UInt64]$total=0;$count=0
    while($pending.Count){
        $directory=$pending.Pop()
        if(([IO.File]::GetAttributes($directory) -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Measurement scratch directory redirects'}
        foreach($path in [IO.Directory]::EnumerateFileSystemEntries($directory)){
            $count++;if($count -gt 20000){throw 'Measurement scratch inventory exceeds bound'}
            $attributes=[IO.File]::GetAttributes($path)
            if(($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'Measurement scratch path redirects'}
            if(($attributes -band [IO.FileAttributes]::Directory) -ne 0){$pending.Push($path)}else{
                $total += [UInt64]([IO.FileInfo]::new($path).Length)
                if($total -gt $MaximumBytes){throw 'Measurement scratch exceeded declared cap'}
            }
        }
    }
    return $total
}

$path=Resolve-WeatherIntegrationPath -Path $RequestPath;$root=Split-Path -Parent $path
$ref=Get-WeatherQualificationReference -Root $root -Name (Split-Path -Leaf $path)
if($ref.sha256 -cne $ExpectedRequestSha256){throw 'Measurement request changed'}
$request=Read-WeatherQualificationReference -Root $root -Reference $ref
Assert-WeatherQualificationFields -Value $request -Names @('schema','measurement_id','repo_root','candidate','qualification','control','plan','task')
if([string]$request.schema -cne 'qualification_measurement_request_v2' -or [string]$request.measurement_id -cnotmatch '^[A-Za-z0-9]{1,40}$'){throw 'Wrong measurement request'}
$repo=Resolve-WeatherIntegrationPath -Path $request.repo_root;$plan=$request.plan
if(-not (Test-WeatherIntegrationPathEqual -Left $PSScriptRoot -Right (Join-Path $repo 'scripts/ops'))){throw 'Measurement must execute adopted B'}
$assignment=Get-WeatherExecutionHostAssignment -RepoRoot $repo
if((Get-WeatherExecutionHostId) -cne [string]$assignment.dedicated_capture_execution_host_id){throw 'Measurement requires the capture installation'}
$now=[DateTimeOffset]::Now;$deadline=[DateTimeOffset]::Parse([string]$plan.deadline)
if($now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30) -or
    $now -lt [DateTimeOffset]::Parse([string]$plan.not_before) -or $now -ge $deadline -or
    ($deadline-[DateTimeOffset]::Parse([string]$plan.not_before)).TotalSeconds -gt 1920 -or
    $deadline -gt [DateTimeOffset]::new($now.Date.AddHours(9))){throw 'Measurement missed its admitted absolute interval'}
foreach($sourceRoot in @($repo,[IO.Path]::GetFullPath([string]$request.candidate))){
    if($root.StartsWith($sourceRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
        $sourceRoot.StartsWith($root.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase) -or
        (Test-WeatherIntegrationPathEqual -Left $root -Right $sourceRoot)){throw 'Measurement evidence overlaps source'}
}
$profile=Read-WeatherQualificationReference -Root $root -Reference $plan.environment
$policy=Read-WeatherQualificationReference -Root $request.qualification.root -Reference $request.qualification.policy
$review=Read-WeatherQualificationReference -Root $request.qualification.root -Reference $request.qualification.review
Assert-WeatherQualificationNativeToolPins -Profile $profile -Policy $policy -Review $review -GraphRoot $request.qualification.root
$identity=Assert-WeatherMeasurementInvocation -Request $request -Path $path -Sha256 $ExpectedRequestSha256 -Script $PSCommandPath
$work=Join-Path $root 'measurement-work'
if(Test-Path -LiteralPath $work){throw 'Measurement namespace is spent'}
$lease=$null;$envelope=$null;$zero=$true
try{
    $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload ('SplitMeasure-'+$request.measurement_id)
    if($null -eq $lease){throw 'Shared heavy-workload lease is occupied'}
    [void][IO.Directory]::CreateDirectory($work)
    Write-WeatherQualificationImmutableJson -Path (Join-Path $work 'invocation.json') -Payload $identity
    $capture=@(Get-WeatherQualificationCaptureBindings -ProductionRoot $repo)
    $phases=[ordered]@{};$order=@('probes','audit','metadata','teardown')
    $envelope=[Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess(536870912,64);$zero=$false
    foreach($phase in $order){
        $maximum=$plan.maximums.PSObject.Properties[$phase].Value;$seconds=[int]$maximum.seconds
        $ceiling=if($phase -eq 'probes'){536870912}else{2147483648}
        $rss=if($phase -eq 'probes'){536870912}else{1610612736}
        $wall=@{probes=480;audit=1200;metadata=120;teardown=120}[$phase]
        if($seconds -le 4 -or $seconds -gt $wall -or [UInt64]$maximum.commit_bytes -gt $ceiling -or
            [UInt64]$maximum.working_set_bytes -gt $rss){throw 'Measurement exceeds hard policy caps'}
        $directory=Join-Path $work $phase;[void][IO.Directory]::CreateDirectory($directory)
        Set-WeatherQualificationOfflineEnvironment -Profile $profile -Scratch $directory
        $envelope.SetEnvelopeCommitLimit([UInt64]$maximum.commit_bytes)
        $reserved=2
        for($index=[Array]::IndexOf($order,$phase)+1;$index -lt $order.Count;$index++){$reserved += [int]$plan.maximums.PSObject.Properties[$order[$index]].Value.seconds}
        $phaseDeadline=$deadline.AddSeconds(-$reserved)
        $python=Join-Path $profile.tools.python.root $profile.tools.python.path
        $tokens=@('-I','-S','-B',(Join-Path $PSScriptRoot 'qualification_measure_control.py'),$path,$ExpectedRequestSha256,$phase)
        $phaseClock=[Diagnostics.Stopwatch]::StartNew()
        $before=$envelope.Snapshot()
        $native=Invoke-WeatherQualificationProcess -Envelope $envelope -Executable $python -Tokens $tokens -WorkingDirectory $repo `
            -Transcript (Join-Path $directory 'native.log') -DeadlineUtc $phaseDeadline -MaximumSeconds ($seconds-3) -TeardownSeconds 3 `
            -CommitBytes ([UInt64]$maximum.commit_bytes) -WorkingSetBytes ([UInt64]$maximum.working_set_bytes) -MaximumOutputBytes 2097152 `
            -VolumePaths @($repo,$root) -MinimumDiskBytes 53687091200 -ReservedScratchBytes ([UInt64]$maximum.scratch_bytes) `
            -ResourceMode capture_s4u -ProductionRoot $repo -CaptureBindings $capture
        Write-WeatherQualificationImmutableJson -Path (Join-Path $directory 'native.json') -Payload $native
        if(-not $native.completed -or -not $native.teardown_proved){throw ('Measurement failed: '+$phase+'; '+$native.failure)}
        $after=$envelope.Snapshot();$zero=$after.ProcessIds.Count -eq 1 -and $after.ProcessIds[0] -eq $PID
        if(-not $zero){throw 'Measurement descendants remain'}
        $observation=Read-WeatherQualificationReference -Root $directory -Reference (Get-WeatherQualificationReference -Root $directory -Name 'observation.json')
        if([string]$observation.schema -cne 'qualification_measurement_observation_v2' -or [string]$observation.request_sha256 -cne $ExpectedRequestSha256 -or
            [string]$observation.phase -cne $phase -or $observation.integration_eligible -isnot [bool] -or $observation.integration_eligible -or
            $observation.native_parent_completion_required -isnot [bool] -or -not $observation.native_parent_completion_required){throw 'Measurement output differs'}
        $scratchBytes=Get-WeatherMeasurementScratchBytes -Root $root -MaximumBytes ([UInt64]$maximum.scratch_bytes)
        if($phaseClock.Elapsed.TotalSeconds -gt $seconds -or [DateTimeOffset]::UtcNow -ge $phaseDeadline){throw 'Measurement readback exceeded phase deadline'}
        $phases[$phase]=[ordered]@{scratch_bytes=$scratchBytes;native=(Get-WeatherQualificationReference -Root $root -Name ('measurement-work/'+$phase+'/native.json'))
            observation=(Get-WeatherQualificationReference -Root $root -Name ('measurement-work/'+$phase+'/observation.json'))
            cpu_ms=[Int64][Math]::Ceiling(($after.UserTime100ns+$after.KernelTime100ns-$before.UserTime100ns-$before.KernelTime100ns)/10000.0)}
    }
    $identityAfter=Assert-WeatherMeasurementInvocation -Request $request -Path $path -Sha256 $ExpectedRequestSha256 -Script $PSCommandPath
    if(($identity | ConvertTo-Json -Depth 10 -Compress) -cne ($identityAfter | ConvertTo-Json -Depth 10 -Compress)){throw 'Measurement invocation changed'}
    Assert-WeatherQualificationCapture -ProductionRoot $repo -Bindings $capture
    if([DateTimeOffset]::UtcNow -ge $deadline){throw 'Measurement publication missed deadline'}
    Write-WeatherQualificationImmutableJson -Path (Join-Path $root 'measurement-result.json') -Payload ([ordered]@{
        schema='qualification_measurement_result_v2';request_sha256=$ExpectedRequestSha256;phases=$phases
        invocation=(Get-WeatherQualificationReference -Root $root -Name 'measurement-work/invocation.json')
        completed_at=[DateTimeOffset]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'",[Globalization.CultureInfo]::InvariantCulture)
        review_required=$true;integration_eligible=$false})
}finally{
    if($envelope){
        try{$snapshot=$envelope.Snapshot();$zero=$snapshot.ProcessIds.Count -eq 1 -and $snapshot.ProcessIds[0] -eq $PID}catch{$zero=$false}
        if(-not $zero -and $lease){Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease};$envelope.Dispose()
    }
    if($lease -and $zero){Exit-WeatherHeavyWorkloadLease -Lease $lease}
}
