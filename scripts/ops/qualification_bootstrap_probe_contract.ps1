# Temporary probe-adapter functions. The entrypoint pins these bytes before
# dot-sourcing; the envelope, not candidate-generated evidence, is authority.
Set-StrictMode -Version Latest

function Assert-WeatherBootstrapProbeFields {
    param($Value,[string[]]$Names)
    if($null -eq $Value -or
        (@($Value.PSObject.Properties.Name | Sort-Object -CaseSensitive) -join '|') -cne
        (@($Names | Sort-Object -CaseSensitive) -join '|')) { throw 'Bootstrap record has missing or unsupported fields' }
}

function Assert-WeatherBootstrapProbePath {
    param([string]$Path)
    if(-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\') -or $Path.IndexOf([char]0) -ge 0) {
        throw 'Bootstrap requires an absolute local path'
    }
    $full=[IO.Path]::GetFullPath($Path)
    $cursor=$full
    while($cursor -and $cursor -ne [IO.Path]::GetPathRoot($cursor)) {
        if(Test-Path -LiteralPath $cursor) {
            if(([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Bootstrap path redirects'
            }
        }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Read-WeatherBootstrapProbeReference {
    param([string]$Root,$Reference)
    Assert-WeatherBootstrapProbeFields $Reference @('path','sha256','size')
    if($Reference.path -isnot [string] -or $Reference.path -match '[\\:*?"<>|]' -or
        $Reference.path -match '(^|/)(\.|\.\.|)(/|$)' -or $Reference.path.StartsWith('/') -or
        $Reference.sha256 -cnotmatch '^[0-9a-f]{64}$' -or $Reference.size -is [bool] -or
        $Reference.size -lt 1 -or $Reference.size -gt 2097152) { throw 'Invalid bounded bootstrap reference' }
    $path=Assert-WeatherBootstrapProbePath (Join-Path $Root ([string]$Reference.path))
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if($stream.Length -ne [Int64]$Reference.size) { throw 'Bootstrap reference length changed' }
        $bytes=New-Object byte[] ([int]$stream.Length)
        $offset=0
        while($offset -lt $bytes.Length) {
            $count=$stream.Read($bytes,$offset,$bytes.Length-$offset)
            if($count -le 0) { throw 'Bootstrap reference truncated' };$offset+=$count
        }
        $sha=[Security.Cryptography.SHA256]::Create()
        try {$actual=-join($sha.ComputeHash($bytes) | ForEach-Object {$_.ToString('x2')})} finally {$sha.Dispose()}
        if($actual -cne [string]$Reference.sha256) { throw 'Bootstrap reference digest changed' }
        Initialize-WeatherExecutionHostAssignmentReader
        $strict=[Weather.Operations.ExecutionHostAssignmentReaderV1]::ReadStableUtf8Json($path,2097152,$null)
        return ConvertFrom-WeatherExactJson -Text $strict
    } finally {$stream.Dispose()}
}

function Write-WeatherBootstrapProbeRecord {
    param([string]$Path,$Value)
    [void](Assert-WeatherBootstrapProbePath $Path)
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value | ConvertTo-Json -Depth 16 -Compress)+"`n")
    if($bytes.Length -gt 2097152) { throw 'Bootstrap output exceeds metadata bound' }
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try {$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
}

function Assert-WeatherBootstrapProbeWindow {
    param($Envelope)
    $start=[DateTimeOffset]::Parse([string]$Envelope.not_before)
    $deadline=[DateTimeOffset]::Parse([string]$Envelope.deadline)
    $now=[DateTimeOffset]::Now
    if($now -lt $start -or $now -ge $deadline -or ($deadline-$start).TotalSeconds -gt 480 -or
        ($deadline-$start).TotalSeconds -le 15 -or $now.Hour -ge 9 -or ($now.Hour -eq 0 -and $now.Minute -lt 30) -or
        $deadline -gt [DateTimeOffset]::new($now.Date.AddHours(9))) { throw 'Bootstrap probe missed its admitted absolute window' }
    return $deadline
}

function Assert-WeatherBootstrapProbeInvocation {
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
    $name='WeatherQualificationBootstrapProbe_'+[string]$Envelope.bootstrap_id
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
        [string]$definition.Settings.ExecutionTimeLimit -cne 'PT9M') { throw 'Bootstrap task definition differs' }
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

function Set-WeatherBootstrapProbeEnvironment {
    param($Profile,[string]$Scratch)
    # The adopted bounded-suite runner establishes its offline marker and
    # scrubs sensitive inherited values before candidate startup. Here the
    # reviewed copy narrows that boundary to a complete allowlist as well.
    $keep=@{}
    foreach($name in @('SYSTEMROOT','WINDIR','COMSPEC','SYSTEMDRIVE','PATHEXT')) {
        $value=[Environment]::GetEnvironmentVariable($name,'Process')
        if($value) {$keep[$name]=$value}
    }
    foreach($name in @([Environment]::GetEnvironmentVariables('Process').Keys)) {
        [Environment]::SetEnvironmentVariable([string]$name,$null,'Process')
    }
    foreach($name in $keep.Keys) {[Environment]::SetEnvironmentVariable($name,$keep[$name],'Process')}
    $paths=@($Profile.tools.PSObject.Properties | ForEach-Object {
        [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath((Join-Path $_.Value.root $_.Value.path)))
    } | Sort-Object -Unique)
    [Environment]::SetEnvironmentVariable('PATH',($paths -join [IO.Path]::PathSeparator),'Process')
    foreach($name in @('TEMP','TMP','TMPDIR','HOME','USERPROFILE','APPDATA','LOCALAPPDATA')) {
        [Environment]::SetEnvironmentVariable($name,$Scratch,'Process')
    }
    foreach($entry in @{
        WEATHER_INTEGRATION_TEST_OFFLINE='1';PYTHONDONTWRITEBYTECODE='1';PYTHONNOUSERSITE='1';PYTHONHASHSEED='0'
        PYTEST_DISABLE_PLUGIN_AUTOLOAD='1';GIT_CONFIG_NOSYSTEM='1';GIT_CONFIG_GLOBAL='nul';GIT_TERMINAL_PROMPT='0'
        GIT_LFS_SKIP_SMUDGE='1';PSModuleAnalysisCachePath='nul';TZ='UTC';LANG='C';LC_ALL='C'
    }.GetEnumerator()) {[Environment]::SetEnvironmentVariable([string]$entry.Key,[string]$entry.Value,'Process')}
}


function Get-WeatherBootstrapProbeCaptureBindings {
    param([string]$ProductionRoot)
    $bindings=@()
    foreach($name in @('loop_status.json','clob_loop_status.json','observation_trigger_status.json')) {
        $path=Join-Path (Join-Path $ProductionRoot 'data/snapshots') $name
        $status=ConvertFrom-WeatherExactJson -Text (Read-WeatherStableExecutionHostAssignmentText -Path $path)
        $worker=Get-Process -Id ([int]$status.pid) -ErrorAction Stop
        try {$bindings+=([pscustomobject]@{name=$name;pid=[int]$status.pid;creation_utc_ticks=$worker.StartTime.ToUniversalTime().Ticks})}
        finally {$worker.Dispose()}
    }
    Assert-WeatherQualificationCapture -ProductionRoot $ProductionRoot -Bindings $bindings
    return $bindings
}

function Get-WeatherBootstrapProbeScratchBytes {
    param([string]$Root,[UInt64]$MaximumBytes)
    $pending=New-Object 'System.Collections.Generic.Stack[string]'
    $pending.Push((Assert-WeatherBootstrapProbePath $Root))
    [UInt64]$bytes=0;$count=0
    while($pending.Count) {
        $directory=$pending.Pop()
        foreach($path in [IO.Directory]::EnumerateFileSystemEntries($directory)) {
            $count++;if($count -gt 512) { throw 'Bootstrap scratch inventory exceeded 512 entries' }
            $attributes=[IO.File]::GetAttributes($path)
            if(($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Bootstrap scratch path redirects' }
            if(($attributes -band [IO.FileAttributes]::Directory) -ne 0) {$pending.Push($path)} else {
                $bytes+=[UInt64]([IO.FileInfo]::new($path).Length)
                if($bytes -gt $MaximumBytes) { throw 'Bootstrap scratch byte limit exceeded' }
            }
        }
    }
    return $bytes
}

function Get-WeatherBootstrapProbeReference {
    param([string]$Root,[string]$Name)
    $path=Assert-WeatherBootstrapProbePath (Join-Path $Root $Name)
    $stream=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if($stream.Length -lt 1 -or $stream.Length -gt 2097152) { throw 'Bootstrap result exceeds metadata bound' }
        $sha=[Security.Cryptography.SHA256]::Create()
        try {$hash=-join($sha.ComputeHash($stream) | ForEach-Object {$_.ToString('x2')})} finally {$sha.Dispose()}
        return [pscustomobject][ordered]@{path=$Name;sha256=$hash;size=[Int64]$stream.Length}
    } finally {$stream.Dispose()}
}

function Assert-WeatherBootstrapProbeObservation {
    param($Envelope,[string]$Root,[string]$EnvelopeSha256)
    $directory=Join-Path $Root 'probe-work/observations'
    $ref=Get-WeatherBootstrapProbeReference $directory 'observation.json'
    $value=Read-WeatherBootstrapProbeReference $directory $ref
    Assert-WeatherBootstrapProbeFields $value @('schema','envelope_sha256','started_at','completed_at','source','configuration',
        'results','markets','native_parent_completion_required','integration_eligible','full_suite_replacement')
    if($value.schema -cne 'qualification_bootstrap_probe_observation_v1' -or $value.envelope_sha256 -cne $EnvelopeSha256 -or
        $value.integration_eligible -isnot [bool] -or $value.integration_eligible -or
        $value.full_suite_replacement -isnot [bool] -or $value.full_suite_replacement -or
        $value.native_parent_completion_required -isnot [bool] -or -not $value.native_parent_completion_required) {
        throw 'Bootstrap observation has the wrong authority or source envelope'
    }
    foreach($name in @('commit','tree','baseline')) {
        if($value.source.PSObject.Properties[$name].Value -cne $Envelope.source.PSObject.Properties[$name].Value) {
            throw 'Bootstrap observed source differs'
        }
    }
    $start=[DateTimeOffset]::Parse([string]$value.started_at)
    $end=[DateTimeOffset]::Parse([string]$value.completed_at)
    if($start -lt [DateTimeOffset]::Parse([string]$Envelope.not_before) -or $end -lt $start -or
        $end -gt [DateTimeOffset]::UtcNow -or $end -ge [DateTimeOffset]::Parse([string]$Envelope.deadline)) {
        throw 'Bootstrap observation interval differs'
    }
    $candidate=@('isolated_imports','configuration_overlay','offline_environment','duplicate_path','stdin_eof','create_once_flush_rename')
    $parent=@('captured_streams','timeout_cleanup','inherited_handles')
    Assert-WeatherBootstrapProbeFields $value.results ($candidate+$parent)
    foreach($name in ($candidate+$parent)) {
        $probeRef=$value.results.PSObject.Properties[$name].Value
        $expected=if($name -in $candidate) {'candidate/'+$name+'.json'} else {$name+'.json'}
        if([string]$probeRef.path -cne $expected) { throw 'Bootstrap result selected another probe path' }
        $probe=Read-WeatherBootstrapProbeReference $directory $probeRef
        Assert-WeatherBootstrapProbeFields $probe @('schema','name','status','detail')
        if($probe.schema -cne 'qualification_host_probe_v2' -or $probe.name -cne $name -or $probe.status -cne 'PASS') {
            throw 'A fixed bootstrap probe did not pass'
        }
    }
    return [ordered]@{path='probe-work/observations/observation.json';sha256=$ref.sha256;size=$ref.size}
}

function Assert-WeatherBootstrapProbeTree {
    param([string]$Root,$Inventory,[string[]]$Exclusions=@(),[int]$MaximumEntries=8192,[bool]$SourceOnly=$false)
    if($Inventory.schema -cne 'qualification_runtime_files_v2') { throw 'Wrong bootstrap file inventory' }
    $full=Assert-WeatherBootstrapProbePath $Root
    $prefix=$full.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
    $expected=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach($pin in @($Inventory.files)) {
        if($pin.path -isnot [string] -or $pin.path -match '[\\:*?"<>|]' -or
            $pin.path -match '(^|/)(\.|\.\.|)(/|$)' -or $pin.path.StartsWith('/') -or
            -not $expected.Add([string]$pin.path) -or
            ($SourceOnly -and $pin.path -match '(?i)\.(pyc|pyo)$')) { throw 'Unsafe bootstrap inventory member' }
    }
    $excluded=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach($name in $Exclusions) {
        if($name -cnotin @('Doc','tcl','Tools','Lib/site-packages') -or -not $excluded.Add($name)) {
            throw 'Bootstrap interpreter exclusion can hide startup code'
        }
    }
    $pending=New-Object 'System.Collections.Generic.Stack[string]';$pending.Push($full)
    $observed=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $count=0
    while($pending.Count) {
        foreach($path in [IO.Directory]::EnumerateFileSystemEntries($pending.Pop())) {
            $count++;if($count -gt $MaximumEntries) { throw 'Bootstrap file inventory exceeded its entry bound' }
            $attributes=[IO.File]::GetAttributes($path)
            if(($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Bootstrap inventory redirects' }
            $relative=$path.Substring($prefix.Length).Replace('\','/')
            if(($attributes -band [IO.FileAttributes]::Directory) -ne 0) {
                if(-not $excluded.Contains($relative)) {$pending.Push($path)}
            } elseif(-not $expected.Contains($relative) -or -not $observed.Add($relative)) {
                throw 'Bootstrap inventory contains an unreviewed file'
            }
        }
    }
    if($observed.Count -ne $expected.Count) { throw 'Bootstrap inventory is missing a reviewed file' }
}

function Assert-WeatherBootstrapProbeResources {
    param([string]$ProductionRoot,[string]$EvidenceRoot)
    [void](Assert-WeatherQualificationDisk -VolumePaths @($ProductionRoot,$EvidenceRoot) -MinimumFreeBytes 53687091200 -ReservedScratchBytes 67108864)
    $system=[Weather.Operations.QualificationSystemResources]::Read()
    if(100.0*$system.CommittedBytes/$system.CommitLimitBytes -gt 64 -or
        100.0*($system.CommittedBytes+536870912)/$system.CommitLimitBytes -gt 66 -or
        ([double]$system.PhysicalAvailableBytes-536870912) -lt 4294967296) { throw 'Bootstrap projected memory reservation refused' }
    [void](Get-WeatherBootstrapProbeCaptureBindings -ProductionRoot $ProductionRoot)
}

function Assert-WeatherBootstrapProbeNativeResult {
    param($Value,[string]$EnvelopeSha256,[UInt64]$MaximumReadBytes)
    Assert-WeatherBootstrapProbeFields $Value @('schema','envelope_sha256','native','integration_eligible','native_read_bytes')
    if($Value.schema -cne 'qualification_bootstrap_probe_native_result_v1' -or
        $Value.envelope_sha256 -cne $EnvelopeSha256 -or
        $Value.integration_eligible -isnot [bool] -or $Value.integration_eligible -or
        $Value.native.completed -isnot [bool] -or -not $Value.native.completed -or
        $Value.native.teardown_proved -isnot [bool] -or -not $Value.native.teardown_proved -or
        $null -ne $Value.native.failure -or $Value.native.exit_code -is [bool] -or
        ($Value.native.exit_code -isnot [int] -and $Value.native.exit_code -isnot [long]) -or
        $null -eq $Value.native.exit_code -or $Value.native.exit_code -ne 0 -or
        $Value.native_read_bytes -is [bool] -or
        ($Value.native_read_bytes -isnot [int] -and $Value.native_read_bytes -isnot [long]) -or
        $Value.native_read_bytes -lt 0 -or [UInt64]$Value.native_read_bytes -gt $MaximumReadBytes) {
        throw 'Bootstrap native result is incomplete or exceeds its read limit'
    }
}
