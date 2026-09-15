# One bounded native command for a reviewed GitHub-hosted Windows producer.
# The attended workstation fallback retains workstation_heavy.ps1; this entry
# point cannot claim that role or run on the dedicated capture installation.
param(
    [Parameter(Mandatory = $true)][string]$RequestPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RequestSha256,
    [Parameter(Mandatory = $true)][string]$ResultPath
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$trustedRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
$assignment = Get-WeatherExecutionHostAssignment -RepoRoot $trustedRoot
if ((Get-WeatherExecutionHostId) -ceq [string]$assignment.dedicated_capture_execution_host_id) {
    throw 'The off-host qualification producer is forbidden on the dedicated capture installation'
}
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted') {
    throw 'This producer requires the reviewed GitHub-hosted runner; workstation work uses its admitted wrapper'
}
if (-not [IO.Path]::IsPathRooted($RequestPath) -or -not [IO.Path]::IsPathRooted($ResultPath)) { throw 'Absolute request/result paths required' }
$requestText = Read-WeatherStableExecutionHostAssignmentText -Path $RequestPath
$hasher = [Security.Cryptography.SHA256]::Create()
try {
    $actual = -join ($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($requestText)) | ForEach-Object { $_.ToString('x2') })
} finally { $hasher.Dispose() }
if ($actual -cne $RequestSha256) { throw 'Native producer request bytes differ' }
$request = ConvertFrom-WeatherExactJson -Text $requestText
$expectedNames = @('schema', 'executable', 'arguments', 'working_directory', 'transcript', 'deadline_utc', 'maximum_seconds', 'teardown_seconds', 'commit_bytes', 'working_set_bytes', 'maximum_output_bytes', 'volumes', 'minimum_disk_bytes')
if ((@($request.PSObject.Properties.Name | Sort-Object) -join '|') -cne (($expectedNames | Sort-Object) -join '|') -or
    [string]$request.schema -cne 'qualification_process_request_v2') { throw 'Unsupported native producer request' }
if (@($request.arguments).Count -lt 1 -or @($request.arguments).Count -gt 512) { throw 'Bounded native argument list required' }
foreach ($argument in $request.arguments) {
    if ($argument -isnot [string] -or $argument.Length -gt 8192 -or $argument.IndexOf([char]0) -ge 0) { throw 'Invalid native argument' }
}
foreach ($name in @('maximum_seconds', 'teardown_seconds', 'commit_bytes', 'working_set_bytes', 'maximum_output_bytes', 'minimum_disk_bytes')) {
    $value = $request.$name
    if ($value -is [bool] -or ($value -isnot [int] -and $value -isnot [long]) -or $value -lt 0) { throw 'Native limit must be an exact nonnegative integer' }
}
foreach ($path in @($request.executable, $request.working_directory, $request.transcript) + @($request.volumes)) {
    if ($path -isnot [string] -or -not [IO.Path]::IsPathRooted($path) -or $path.StartsWith('\\') -or $path.IndexOf([char]0) -ge 0) { throw 'Explicit local native path required' }
}
if ($request.commit_bytes -gt 17179869184 -or $request.working_set_bytes -gt 17179869184) { throw 'Off-host memory ceiling exceeded' }
# The trusted parent supplies a clean allowlisted environment. Recheck at the
# actual native launch boundary, then remove CI identity before candidate code.
foreach ($entry in [Environment]::GetEnvironmentVariables().GetEnumerator()) {
    $key = [string]$entry.Key
    if ($key -match '(?i)(TOKEN|SECRET|PASSWORD|CREDENTIAL)' -or $key -match '^(?i:GH_|AWS_|AZURE_|OPENAI_)') { throw 'Off-host child inherited credential authority' }
    if ($key -like 'GITHUB_*' -or $key -eq 'RUNNER_ENVIRONMENT') { [Environment]::SetEnvironmentVariable($key, $null, 'Process') }
}
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
. (Join-Path $PSScriptRoot 'qualification_process.ps1')
$envelope = [Weather.Operations.KillOnCloseJob]::EncloseCurrentProcess([UInt64]$request.commit_bytes, 64)
try {
    $result = Invoke-WeatherQualificationProcess -Envelope $envelope -Executable ([string]$request.executable) `
        -Tokens ([string[]]$request.arguments) -WorkingDirectory ([string]$request.working_directory) `
        -Transcript ([string]$request.transcript) -DeadlineUtc ([DateTimeOffset]::Parse([string]$request.deadline_utc)) `
        -MaximumSeconds ([int]$request.maximum_seconds) -TeardownSeconds ([int]$request.teardown_seconds) `
        -CommitBytes ([UInt64]$request.commit_bytes) -WorkingSetBytes ([UInt64]$request.working_set_bytes) `
        -MaximumOutputBytes ([Int64]$request.maximum_output_bytes) -VolumePaths ([string[]]$request.volumes) `
        -MinimumDiskBytes ([UInt64]$request.minimum_disk_bytes) -ResourceMode offhost
    $raw = [Text.UTF8Encoding]::new($false).GetBytes(($result | ConvertTo-Json -Depth 4 -Compress) + "`n")
    $stream = [IO.File]::Open($ResultPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
    if (-not $result.completed) { exit 1 }
} finally { $envelope.Dispose() }
