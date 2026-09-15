# One explicitly owner-approved first landing of exactly K. B owns admission
# and outer containment; a fixed monitored child invokes the guarded primitive.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$EnvelopePath,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedEnvelopeSha256,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedAdapterSha256
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

# These few bootstrap operations use only the native runtime. No candidate or
# adapter dependency is evaluated before the caller's independent byte pins.
function Open-WeatherBootstrapPinnedFile {
    param([string]$Path,[string]$Sha256,[Int64]$Size,[Int64]$Maximum=2097152)
    if(-not [IO.Path]::IsPathRooted($Path) -or $Path.StartsWith('\\') -or
        $Sha256 -cnotmatch '^[0-9a-f]{64}$' -or $Size -lt 0 -or $Size -gt $Maximum) { throw 'Invalid bootstrap file pin' }
    $cursor=[IO.Path]::GetFullPath($Path)
    while($cursor -and $cursor -ne [IO.Path]::GetPathRoot($cursor)) {
        if(([IO.File]::GetAttributes($cursor) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Bootstrap pin redirects' }
        $cursor=[IO.Path]::GetDirectoryName($cursor)
    }
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if($stream.Length -ne $Size) { throw 'Bootstrap pinned length differs' }
        $hasher=[Security.Cryptography.SHA256]::Create()
        try {$actual=-join($hasher.ComputeHash($stream) | ForEach-Object {$_.ToString('x2')})} finally {$hasher.Dispose()}
        if($actual -cne $Sha256) { throw 'Bootstrap pinned bytes differ' }
        $stream.Position=0
        return $stream
    } catch {$stream.Dispose();throw}
}

function Read-WeatherBootstrapPinnedObject {
    param([IO.Stream]$Stream)
    $reader=[IO.StreamReader]::new($Stream,[Text.UTF8Encoding]::new($false,$true),$false,4096,$true)
    try {$raw=$reader.ReadToEnd();$Stream.Position=0;return ($raw | ConvertFrom-Json)} finally {$reader.Dispose()}
}

$locks=New-Object 'System.Collections.Generic.List[System.IO.Stream]'
$lease=$null;$job=$null;$child=$null;$zero=$true;$savedEnvironment=$null
$work=$null;$resultWritten=$false
try {
    $self=Open-WeatherBootstrapPinnedFile $PSCommandPath $ExpectedAdapterSha256 ([IO.FileInfo]::new($PSCommandPath).Length)
    $locks.Add($self)
    $path=[IO.Path]::GetFullPath($EnvelopePath);$root=[IO.Path]::GetDirectoryName($path)
    $pinned=Open-WeatherBootstrapPinnedFile $path $ExpectedEnvelopeSha256 ([IO.FileInfo]::new($path).Length)
    $locks.Add($pinned);$envelope=Read-WeatherBootstrapPinnedObject $pinned
    if([string]$envelope.schema -cne 'qualification_bootstrap_install_envelope_v1' -or
        [string]$envelope.operation -cne 'install_control_plane_K_once' -or
        $envelope.approval.replaces_full_host_suite_for_K_only -isnot [bool] -or
        -not $envelope.approval.replaces_full_host_suite_for_K_only) { throw 'Not an explicitly approved K-only installation' }
    $localNow=[DateTimeOffset]::Now
    $earlyDeadline=[DateTimeOffset]::Parse([string]$envelope.deadline)
    if($localNow.Hour -lt 1 -or $localNow.Hour -ge 4 -or
        $localNow -lt [DateTimeOffset]::Parse([string]$envelope.not_before) -or $localNow -ge $earlyDeadline -or
        $earlyDeadline -gt [DateTimeOffset]::new($localNow.Date.AddHours(4))) { throw 'Bootstrap probe is outside its admitted window' }
    $repo=[IO.Path]::GetFullPath([string]$envelope.repo_root)
    $authority=[IO.Path]::GetFullPath([string]$envelope.control.root)
    $adoptedRoot=[IO.Path]::GetFullPath([string]$envelope.baseline_control.root)
    foreach($protected in @($repo,$authority,$root,[IO.Path]::GetFullPath([string]$envelope.candidate))) {
        if($adoptedRoot -ieq $protected -or
            $adoptedRoot.StartsWith($protected.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
            $protected.StartsWith($adoptedRoot.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Retained adopted source overlaps another root'
        }
    }
    if([IO.Path]::GetFullPath($PSScriptRoot) -ine (Join-Path $authority 'scripts/ops') -or
        [IO.Path]::GetFullPath([string]$envelope.evidence_root) -ine $root) { throw 'Bootstrap adapter/evidence location differs' }
    $adopted=@($envelope.adopted_helpers.files)
    $names=@('scripts/ops/windows_kill_on_close_job.ps1','scripts/ops/workload_admission.ps1')
    if($adopted.Count -ne 2 -or (@($adopted.path) -join '|') -cne ($names -join '|')) { throw 'Wrong adopted bootstrap helpers' }
    foreach($pin in $adopted) {
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $adoptedRoot $pin.path) $pin.sha256 $pin.size))
    }
    # Both helpers are already adopted B; no candidate helper owns admission or
    # the outer kill-on-close Job. Their handles remain locked until teardown.
    . (Join-Path $adoptedRoot 'scripts/ops/workload_admission.ps1')
    . (Join-Path $adoptedRoot 'scripts/ops/windows_kill_on_close_job.ps1')
    $lease=Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload ('BootstrapInstall-'+[string]$envelope.bootstrap_id)
    if($null -eq $lease) { throw 'Shared heavy-workload lease is occupied' }
    $reader=[IO.StreamReader]::new($pinned,[Text.UTF8Encoding]::new($false,$true),$false,4096,$true)
    try {
        Initialize-WeatherExecutionHostAssignmentReader
        $envelope=ConvertFrom-WeatherExactJson -Text ([Weather.Operations.ExecutionHostAssignmentReaderV1]::ReadStableUtf8Json($path,2097152,$null))
        $pinned.Position=0
    } finally {$reader.Dispose()}

    $closureRef=$envelope.control.closure
    if($closureRef.path -isnot [string] -or $closureRef.path -match '[\\:*?"<>|]' -or
        $closureRef.path -match '(^|/)(\.|\.\.|)(/|$)' -or $closureRef.path.StartsWith('/')) { throw 'Unsafe bootstrap closure reference' }
    $closureStream=Open-WeatherBootstrapPinnedFile (Join-Path $root $closureRef.path) $closureRef.sha256 $closureRef.size
    $locks.Add($closureStream);$closure=Read-WeatherBootstrapPinnedObject $closureStream
    if([string]$closure.schema -cne 'qualification_runtime_files_v2' -or
        @($closure.files).Count -lt 1 -or @($closure.files).Count -gt 512) { throw 'Bootstrap closure exceeds its fixed bound' }
    $seen=New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    [Int64]$metadataBytes=0
    foreach($pin in $closure.files) {
        if([DateTimeOffset]::UtcNow -ge $earlyDeadline.AddSeconds(-70)) { throw 'Bootstrap preflight exhausted its deadline reserve' }
        $metadataBytes+=[Int64]$pin.size
        if($metadataBytes -gt 8388608) { throw 'Bootstrap adapter closure exceeds eight MiB' }
        if($pin.path -isnot [string] -or $pin.path -match '[\\:*?"<>|]' -or
            $pin.path -match '(^|/)(\.|\.\.|)(/|$)' -or $pin.path.StartsWith('/') -or -not $seen.Add([string]$pin.path)) {
            throw 'Unsafe or duplicate bootstrap closure path'
        }
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $authority $pin.path) $pin.sha256 $pin.size))
    }
    foreach($name in @('scripts/ops/bootstrap_qualification_install.ps1','scripts/ops/qualification_bootstrap_probe_contract.ps1','scripts/ops/qualification_bootstrap_install_contract.ps1',
        'scripts/ops/qualification_bootstrap_install_domain.py','scripts/ops/quiet_window_merge.ps1','scripts/ops/roll_verdict.ps1',
        'scripts/ops/qualification_bootstrap_install_child.ps1','scripts/ops/qualification_bootstrap_install_control.py',
        'scripts/ops/qualification_host_identity.ps1','scripts/ops/qualification_process.ps1','scripts/ops/windows_kill_on_close_job.ps1')) {
        if(-not $seen.Contains($name)) { throw 'Required bootstrap adapter dependency is not pinned' }
    }
    $selfPin=@($closure.files | Where-Object path -CEQ 'scripts/ops/bootstrap_qualification_install.ps1')
    if($selfPin.Count -ne 1 -or $selfPin[0].sha256 -cne $ExpectedAdapterSha256) { throw 'Adapter independent pin and closure disagree' }
    . (Join-Path $PSScriptRoot 'qualification_bootstrap_install_contract.ps1')
    . (Join-Path $PSScriptRoot 'qualification_host_identity.ps1')
    . (Join-Path $PSScriptRoot 'qualification_process.ps1')
    Assert-WeatherBootstrapProbeTree -Root $authority -Inventory $closure -MaximumEntries 1024 -SourceOnly $true
    Assert-WeatherBootstrapProbeResources -ProductionRoot $repo -EvidenceRoot $root
    $envelope=Read-WeatherBootstrapInstallEnvelope $path $ExpectedEnvelopeSha256
    $candidate=Assert-WeatherBootstrapProbePath ([string]$envelope.candidate)
    foreach($protected in @($repo,$candidate,$authority)) {
        $prefix=$protected.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar
        if($root -ieq $protected -or $root.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or
            $protected.StartsWith($root.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Bootstrap evidence overlaps protected source'
        }
    }
    foreach($protected in @($repo,$candidate)) {
        if($authority -ieq $protected -or $authority.StartsWith($protected.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -or
            $protected.StartsWith($authority.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Bootstrap adapter overlaps a source checkout'
        }
    }
    $deadline=Assert-WeatherBootstrapInstallWindow $envelope
    $identity=Assert-WeatherBootstrapInstallInvocation $envelope $path $ExpectedEnvelopeSha256 $ExpectedAdapterSha256 $PSCommandPath
    $profile=Read-WeatherBootstrapProbeReference $root $envelope.environment
    $powershell=Join-Path $PSHOME 'powershell.exe'
    if([IO.Path]::GetFullPath((Join-Path $profile.tools.powershell.root $profile.tools.powershell.path)) -ine $powershell) {
        throw 'Bootstrap native PowerShell differs from the reviewed runtime'
    }
    [Int64]$preflightReadBytes=$metadataBytes
    foreach($name in @('python','powershell','git','gh')) {
        if([DateTimeOffset]::UtcNow -ge $deadline.AddSeconds(-70)) { throw 'Bootstrap tool verification exhausted its deadline reserve' }
        $tool=$profile.tools.PSObject.Properties[$name].Value
        if($tool.size -is [bool] -or ($tool.size -isnot [int] -and $tool.size -isnot [long]) -or $tool.size -lt 1) {
            throw 'Invalid bootstrap executable size'
        }
        $preflightReadBytes+=[Int64]$tool.size
        if($preflightReadBytes -gt 268435456) { throw 'Bootstrap startup verification exceeds 256 MiB' }
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $tool.root $tool.path) $tool.sha256 $tool.size 268435456))
    }
    # Before isolated Python startup, pin the complete reviewed interpreter and
    # the selected native prerequisites. Package imports remain disabled (-S).
    $qroot=Assert-WeatherBootstrapProbePath ([string]$envelope.qualification.root)
    $environment=Read-WeatherBootstrapProbeReference $qroot $profile.environment
    $runtime=Read-WeatherBootstrapProbeReference $qroot $environment.python.runtime_files
    $runtimeRoot=Assert-WeatherBootstrapProbePath ([string]$profile.bindings.interpreter)
    $pythonPath=[IO.Path]::GetFullPath((Join-Path $profile.tools.python.root $profile.tools.python.path))
    if(-not $pythonPath.StartsWith($runtimeRoot.TrimEnd('\','/')+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'Bootstrap interpreter is outside the reviewed complete startup runtime'
    }
    Assert-WeatherBootstrapProbeTree -Root $runtimeRoot -Inventory $runtime -Exclusions @($profile.bindings.interpreter_exclusions)
    $nativeFiles=Read-WeatherBootstrapProbeReference $qroot $environment.native_files
    foreach($group in @(@{root=$runtimeRoot;files=@($runtime.files)},@{root=[string]$profile.bindings.native;files=@($nativeFiles.files)})) {
        if($group.files.Count -gt 8192) { throw 'Bootstrap startup pin count exceeded' }
        foreach($pin in $group.files) {
            if([DateTimeOffset]::UtcNow -ge $deadline.AddSeconds(-70)) { throw 'Bootstrap startup verification exhausted its deadline reserve' }
            if($pin.path -isnot [string] -or $pin.path -match '[\\:*?"<>|]' -or
                $pin.path -match '(^|/)(\.|\.\.|)(/|$)' -or $pin.path.StartsWith('/')) { throw 'Unsafe bootstrap startup file path' }
            if($pin.size -is [bool] -or ($pin.size -isnot [int] -and $pin.size -isnot [long]) -or $pin.size -lt 0) {
                throw 'Invalid bootstrap startup file size'
            }
            $preflightReadBytes+=[Int64]$pin.size
            if($preflightReadBytes -gt 268435456) { throw 'Bootstrap startup verification exceeds 256 MiB' }
            $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $group.root $pin.path) $pin.sha256 $pin.size 268435456))
        }
    }
    # Freeze the complete B execution closure separately. Locking production
    # working files would prevent the approved merge from replacing them.
    $baselineClosure=Read-WeatherBootstrapProbeReference $root $envelope.baseline_control.closure
    if($baselineClosure.schema -cne 'qualification_control_closure_v2' -or
        $baselineClosure.baseline -cne $envelope.baseline -or @($baselineClosure.files).Count -gt 8192 -or
        [Int64]$baselineClosure.total_bytes -gt 134217728) {throw 'Invalid adopted execution closure'}
    $baselineInventory=[pscustomobject]@{schema='qualification_runtime_files_v2';files=@($baselineClosure.files)}
    Assert-WeatherBootstrapProbeTree -Root $adoptedRoot -Inventory $baselineInventory -MaximumEntries 12000 -SourceOnly $true
    [Int64]$baselineBytes=0
    foreach($pin in $baselineClosure.files) {
        if([DateTimeOffset]::UtcNow -ge $deadline.AddSeconds(-130)) {throw 'Adopted source verification exhausted startup reserve'}
        $baselineBytes+=[Int64]$pin.size
        if($baselineBytes -gt 134217728) {throw 'Adopted source exceeds 128 MiB'}
        $locks.Add((Open-WeatherBootstrapPinnedFile (Join-Path $adoptedRoot $pin.path) $pin.sha256 $pin.size 8388608))
    }
    if($baselineBytes -ne [Int64]$baselineClosure.total_bytes) {throw 'Adopted source byte total differs'}
    $preflightReadBytes+=$baselineBytes
    Assert-WeatherBootstrapCompletedProbeTask $envelope
    Assert-WeatherBootstrapProbeResources -ProductionRoot $repo -EvidenceRoot $root
    $work=Join-Path $root 'install-work'
    if(Test-Path -LiteralPath $work) {throw 'Installation namespace is spent'}
    Write-WeatherBootstrapProbeRecord (Join-Path $root 'install-use.json') ([ordered]@{
        schema='qualification_bootstrap_install_use_v1';envelope_sha256=$ExpectedEnvelopeSha256;parent_pid=$PID
        parent_creation_utc_ticks=$identity.token.creation_utc_ticks;retry_authorized=$false})
    [void][IO.Directory]::CreateDirectory($work)
    Write-WeatherBootstrapProbeRecord (Join-Path $work 'invocation.json') $identity
    $savedEnvironment=@{}
    foreach($entry in [Environment]::GetEnvironmentVariables('Process').GetEnumerator()) {$savedEnvironment[[string]$entry.Key]=[string]$entry.Value}
    Set-WeatherBootstrapProbeEnvironment $profile $work
    $job=New-WeatherKillOnCloseJob;$zero=$false
    $tokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
        (Join-Path $PSScriptRoot 'qualification_bootstrap_install_child.ps1'),'-EnvelopePath',$path,
        '-ExpectedEnvelopeSha256',$ExpectedEnvelopeSha256,'-ParentPid',[string]$PID,
        '-ParentCreationUtcTicks',[string]$identity.token.creation_utc_ticks)
    $child=Start-WeatherProcessInJob -Job $job -FilePath $powershell `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $authority
    $stop=$deadline.AddSeconds(-[int]$envelope.limits.teardown_seconds-5)
    $scratchClock=[Diagnostics.Stopwatch]::StartNew()
    while(-not $child.WaitForExit(100)) {
        if([DateTimeOffset]::UtcNow -ge $stop) {throw 'Installation exceeded the reserved execution deadline'}
        if($scratchClock.ElapsedMilliseconds -ge 1000) {
            [void](Get-WeatherBootstrapProbeScratchBytes $work ([UInt64]$envelope.limits.scratch_bytes))
            $scratchClock.Restart()
        }
    }
    $child.WaitForExit();$exitCode=[int]$child.ExitCode
    $job.TerminateAndWait([int]$envelope.limits.teardown_seconds*1000);$zero=$true
    if($exitCode -ne 0) {throw ('Installation child failed or may have committed: exit '+$exitCode)}
    $nativeRef=Get-WeatherBootstrapProbeReference $root 'install-work/native-result.json'
    $native=Read-WeatherBootstrapProbeReference $root $nativeRef
    $quietNativeRef=Get-WeatherBootstrapProbeReference $root 'install-work/quiet-native.json'
    $quietNative=Read-WeatherBootstrapProbeReference $root $quietNativeRef
    $reportRef=Get-WeatherBootstrapProbeReference $root 'install-work/quiet-report.json'
    $report=Read-WeatherBootstrapProbeReference $root $reportRef
    Assert-WeatherBootstrapInstallCompletion $envelope $ExpectedEnvelopeSha256 $native $quietNative $report
    $scratchBytes=Get-WeatherBootstrapProbeScratchBytes $work ([UInt64]$envelope.limits.scratch_bytes)
    $after=Assert-WeatherBootstrapInstallInvocation $envelope $path $ExpectedEnvelopeSha256 $ExpectedAdapterSha256 $PSCommandPath
    if(($identity | ConvertTo-Json -Depth 12 -Compress) -cne ($after | ConvertTo-Json -Depth 12 -Compress)) {throw 'Installation invocation changed'}
    if([DateTimeOffset]::UtcNow -ge $deadline) {throw 'Installation receipt missed the absolute deadline'}
    Write-WeatherBootstrapProbeRecord (Join-Path $root 'install-result.json') ([ordered]@{
        schema='qualification_bootstrap_install_result_v1';status='PUBLISHED_CLOSEOUT_REQUIRED'
        envelope_sha256=$ExpectedEnvelopeSha256;adapter_sha256=$ExpectedAdapterSha256;source=$envelope.source
        merge_commit=[string]$report.merge_commit;policy=$envelope.qualification.policy
        outer_teardown_proved=$zero;child_exit_code=$exitCode;preflight_read_bytes=$preflightReadBytes
        native=$nativeRef;quiet_native=$quietNativeRef;report=$reportRef;scratch_bytes=$scratchBytes
        completed_at=[DateTimeOffset]::UtcNow.ToString('o');full_host_suite_pass=$false;retry_authorized=$false})
    $resultWritten=$true
} catch {
    if($work -and (Test-Path -LiteralPath $work) -and -not $resultWritten) {
        try {Write-WeatherBootstrapProbeRecord (Join-Path $work 'failure.json') ([ordered]@{
            schema='qualification_bootstrap_install_failure_v1';envelope_sha256=$ExpectedEnvelopeSha256
            failure=[string]$_.Exception.Message;commit_or_publication_may_have_happened=$true;retry_authorized=$false})} catch {}
    }
    throw
} finally {
    if($job) {
        if(-not $zero) {try {$job.TerminateAndWait(10000);$zero=$true} catch {$zero=$false}}
        $job.Dispose()
    }
    if($child) {$child.Dispose()}
    if($lease) {
        if($zero) {Exit-WeatherHeavyWorkloadLease -Lease $lease} else {Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease}
    }
    if($savedEnvironment) {
        foreach($name in @([Environment]::GetEnvironmentVariables('Process').Keys)) {[Environment]::SetEnvironmentVariable([string]$name,$null,'Process')}
        foreach($name in $savedEnvironment.Keys) {[Environment]::SetEnvironmentVariable($name,$savedEnvironment[$name],'Process')}
    }
    foreach($stream in $locks) {$stream.Dispose()}
}
