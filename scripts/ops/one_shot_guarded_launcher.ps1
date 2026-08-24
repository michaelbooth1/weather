[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias("ManifestPath")]
    [string]$ReadinessManifestPath,

    [Parameter(Mandatory = $true)]
    [Alias("ExpectedManifestSha256")]
    [ValidatePattern("^[0-9a-fA-F]{64}$")]
    [string]$ExpectedReadinessManifestSha256
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath(
    (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
)
$validatorPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "one_shot_readiness.ps1")
)
$workloadAdmissionPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "workload_admission.ps1")
)
$jobContainmentPath = [IO.Path]::GetFullPath(
    (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1")
)
$registryLockPath = [IO.Path]::GetFullPath(
    (Join-Path $repoRoot "one_shot_registry.lock")
)
$registryLock = $null
$workloadLease = $null
$dependencyLeaseSet = $null
$payloadJob = $null
$payloadProcess = $null
$exitCode = 3

try {
    $lockDeadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        try {
            # The launcher keeps a shared reader lease across validation and
            # payload execution. Writer, resolver, recovery, and compaction
            # require FileShare.None and therefore cannot alter the authority
            # record while reviewed code is running.
            $registryLock = [IO.FileStream]::new(
                $registryLockPath,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::Read
            )
        }
        catch [IO.IOException] {
            if ([DateTime]::UtcNow -ge $lockDeadline) { throw }
            Start-Sleep -Milliseconds 100
        }
    } while ($null -eq $registryLock)

    $lockItem = Get-Item -LiteralPath $registryLockPath -Force -ErrorAction Stop
    if ($lockItem.PSIsContainer -or
        ($lockItem.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "One-shot registry lock is not a regular non-reparse file."
    }

    . $validatorPath -LibraryOnly
    $contract = Read-WeatherOneShotReadinessManifest `
        -Path ([IO.Path]::GetFullPath($ReadinessManifestPath)) `
        -ExpectedSha256 $ExpectedReadinessManifestSha256
    if ([IO.Path]::GetFullPath([string]$contract.Manifest.task.action_file) -ine
        [IO.Path]::GetFullPath($PSCommandPath)) {
        throw "The manifest does not bind this canonical guarded launcher."
    }

    $bootIdentity = Get-WeatherOneShotCurrentBootIdentity
    $taskObservation = Get-WeatherOneShotTaskObservation `
        -ManifestContract $contract
    $readiness = Test-WeatherOneShotReadinessSnapshot `
        -ManifestContract $contract `
        -ObservedTaskSnapshot $taskObservation.Snapshot `
        -CurrentBootIdentity $bootIdentity `
        -InitialBlockers @($taskObservation.Blockers) `
        -ObservationMode "Execution"
    if (-not [bool]$readiness.ready) {
        [Console]::Error.WriteLine(
            ($readiness | ConvertTo-Json -Depth 6 -Compress)
        )
        $exitCode = 2
    }
    else {
        $dependencyLeaseSet = Enter-WeatherOneShotDependencyLeaseSet `
            -ManifestContract $contract
        $payloadPath = [IO.Path]::GetFullPath(
            [string]$contract.Manifest.task.payload_file
        )
        $payloadArguments = [string[]]@(
            $contract.Manifest.task.payload_arguments
        )
        if ([string]$contract.Manifest.admission.workload_class -ceq "heavy") {
            . $workloadAdmissionPath
            $workloadLease = Enter-WeatherHeavyWorkloadLease `
                -RepoRoot $repoRoot `
                -Workload ("one_shot:{0}" -f
                    [string]$contract.Manifest.task.task_name)
            if ($null -eq $workloadLease) {
                throw "The shared heavy-workload lease is already held."
            }
        }

        . $jobContainmentPath
        $argumentTokens = @(
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", $payloadPath
        ) + $payloadArguments
        $argumentString = ConvertTo-WeatherOneShotProcessArgumentString `
            -Tokens $argumentTokens
        $payloadJob = New-WeatherKillOnCloseJob
        $payloadProcess = Start-WeatherProcessInJob `
            -Job $payloadJob `
            -FilePath ([string]$contract.Manifest.task.executable) `
            -ArgumentString $argumentString `
            -WorkingDirectory ([string]$contract.Manifest.task.working_directory)
        $hardStop = [DateTimeOffset]::Parse(
            [string]$contract.Manifest.admission.teardown_deadline_at_local
        )
        while (-not $payloadProcess.HasExited) {
            if ([DateTimeOffset]::Now -ge $hardStop) {
                $payloadJob.Dispose()
                $payloadJob = $null
                $payloadProcess.WaitForExit()
                throw "One-shot payload reached its absolute reviewed teardown deadline."
            }
            [void]$payloadProcess.WaitForExit(250)
            $payloadProcess.Refresh()
        }
        $payloadProcess.WaitForExit()
        $exitCode = [int]$payloadProcess.ExitCode
    }
}
catch {
    [Console]::Error.WriteLine(
        ("one-shot guarded launch failed: {0}" -f $_.Exception.Message)
    )
    $exitCode = 3
}
finally {
    if ($null -ne $payloadJob) {
        $payloadJob.Dispose()
    }
    if ($null -ne $payloadProcess) {
        $payloadProcess.Dispose()
    }
    if ($null -ne $workloadLease) {
        Exit-WeatherHeavyWorkloadLease -Lease $workloadLease
    }
    if ($null -ne $dependencyLeaseSet) {
        Exit-WeatherOneShotDependencyLeaseSet -LeaseSet $dependencyLeaseSet
    }
    if ($null -ne $registryLock) {
        $registryLock.Dispose()
    }
}

exit $exitCode
