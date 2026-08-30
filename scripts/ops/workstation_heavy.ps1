# Run approved offline heavy Python work on a non-capture workstation while
# holding the same host-global mutex as a portable International live stage.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("pytest", "compileall", "weather_heavy")]
    [string]$Kind,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ArgumentsBase64,
    [Parameter(Mandatory = $true)][string]$RepoRoot
)

$ErrorActionPreference = "Stop"

$windowsPowerShellModules = Join-Path `
    ([Environment]::GetFolderPath([Environment+SpecialFolder]::Windows)) `
    "System32\WindowsPowerShell\v1.0\Modules"
if (-not (Test-Path -LiteralPath $windowsPowerShellModules -PathType Container)) {
    throw "canonical Windows PowerShell module directory is absent"
}
[Environment]::SetEnvironmentVariable(
    "PSModulePath",
    $windowsPowerShellModules,
    "Process"
)

$admissionScript = Join-Path $PSScriptRoot "workload_admission.ps1"
$jobScript = Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1"
foreach ($requiredScript in @($admissionScript, $jobScript)) {
    if (-not (Test-Path -LiteralPath $requiredScript -PathType Leaf)) {
        throw "required workstation-heavy helper is missing: $requiredScript"
    }
}
. $admissionScript
. $jobScript

if (-not [IO.Path]::IsPathRooted($RepoRoot)) {
    throw "workstation-heavy repository root must be absolute"
}
$repo = Get-Item -LiteralPath $RepoRoot -Force -ErrorAction Stop
if (
    -not $repo.PSIsContainer -or
    ($repo.Attributes -band [IO.FileAttributes]::ReparsePoint)
) {
    throw "workstation-heavy repository root is absent or redirected"
}
$resolvedRepoRoot = $repo.FullName
$wrapperRepoRoot = (Get-Item -LiteralPath (Join-Path $PSScriptRoot "..\..") `
    -Force -ErrorAction Stop).FullName
if (-not [string]::Equals(
    $resolvedRepoRoot,
    $wrapperRepoRoot,
    [StringComparison]::OrdinalIgnoreCase
)) {
    throw "workstation-heavy repository root must own this exact wrapper"
}

$pythonPathIsAbsolute = [IO.Path]::IsPathRooted($PythonPath)
$python = Get-Item -LiteralPath $PythonPath -Force -ErrorAction Stop
if (
    $pythonPathIsAbsolute -and
    -not $python.PSIsContainer -and
    -not ($python.Attributes -band [IO.FileAttributes]::ReparsePoint) -and
    $python.Name -cmatch '\Apython(?:3(?:\.\d+)?)?\.exe\z'
) {
    $resolvedPython = $python.FullName
}
else {
    throw "workstation-heavy execution requires a regular CPython executable"
}

if (
    $ArgumentsBase64.Length -gt 131072 -or
    $ArgumentsBase64 -cnotmatch '\A(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\z'
) {
    throw "workstation-heavy Python argument contract is not canonical base64"
}
try {
    $argumentBytes = [Convert]::FromBase64String($ArgumentsBase64)
    $argumentsJson = [Text.UTF8Encoding]::new($false, $true).GetString($argumentBytes)
    if ([Convert]::ToBase64String($argumentBytes) -cne $ArgumentsBase64) {
        throw "base64 is not canonical"
    }
    $decoded = $argumentsJson | ConvertFrom-Json -ErrorAction Stop
}
catch { throw "workstation-heavy Python arguments are not valid canonical JSON" }
$arguments = @($decoded)
if (
    $arguments.Count -lt 2 -or
    $arguments.Count -gt 128 -or
    @($arguments | Where-Object {
        $_ -isnot [string] -or $_.Length -gt 4096 -or $_ -match '[\x00\r\n]'
    }).Count -gt 0
) {
    throw "workstation-heavy Python arguments are invalid or unbounded"
}

$module = if ($arguments[0] -ceq "-m") { [string]$arguments[1] } else { "" }
switch ($Kind) {
    "pytest" {
        if ($module -cne "pytest") {
            throw "pytest workload requires exact '-m pytest' arguments"
        }
    }
    "compileall" {
        if ($module -cne "compileall") {
            throw "compileall workload requires exact '-m compileall' arguments"
        }
    }
    "weather_heavy" {
        $offlineModules = @(Get-WeatherWorkstationOfflineModule)
        if (
            $module -cnotin $offlineModules -or
            @($arguments | Where-Object {
                $_ -cmatch '(?i)\A--?(?:live|execute|place|cancel|promote)(?:=|\z)'
            }).Count -gt 0
        ) {
            throw "weather-heavy workload must be an offline training/replay module"
        }
    }
}

$lease = Enter-WeatherHeavyWorkloadLease `
    -RepoRoot $RepoRoot `
    -Workload ("WorkstationOffline-{0}-{1}" -f $Kind, $PID) `
    -ExecutionHostProfile "workstation_offline_v1"
if ($null -eq $lease) {
    throw "workstation-heavy execution is blocked by another heavy or portable live lease"
}

$job = $null
$child = $null
$exitCode = 1
try {
    $job = New-WeatherKillOnCloseJob
    $argumentString = ConvertTo-WeatherWindowsArgumentString -Tokens $arguments
    [Environment]::SetEnvironmentVariable(
        "WEATHER_WORKSTATION_WRAPPER_ACTIVE",
        "1",
        "Process"
    )
    [Environment]::SetEnvironmentVariable(
        "PSExecutionPolicyPreference",
        "Bypass",
        "Process"
    )
    $child = Start-WeatherInteractiveProcessInJob `
        -Job $job `
        -FilePath $resolvedPython `
        -ArgumentString $argumentString `
        -WorkingDirectory $resolvedRepoRoot
    $child.WaitForExit()
    $exitCode = $child.ExitCode
}
finally {
    $teardownTransitionError = $null
    $jobTeardownError = $null
    if ($null -ne $lease) {
        try {
            Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease |
                Out-Null
        }
        catch { $teardownTransitionError = $_ }
    }
    if ($job -and $null -eq $teardownTransitionError) {
        try { $job.TerminateAndWait(5000) }
        catch { $jobTeardownError = $_ }
    }
    if ($child) { $child.Dispose() }
    if ($job) { $job.Dispose() }
    if ($null -ne $teardownTransitionError) {
        # The transition helper retained the ACTIVE lease. Disposing the Job
        # closes its kill-on-close handle; process exit closes the retained lease.
    }
    elseif ($jobTeardownError) {
        Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
    }
    else {
        Exit-WeatherHeavyWorkloadLease -Lease $lease
    }
    if ($null -ne $teardownTransitionError) { throw $teardownTransitionError }
    if ($jobTeardownError) { throw $jobTeardownError }
}
exit $exitCode
