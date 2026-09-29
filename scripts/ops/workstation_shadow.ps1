# Attended public-only shadow or offline agreement. No Scheduler integration.
[CmdletBinding(DefaultParameterSetName = "Public")]
param(
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][string]$ManifestPath,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][string]$ProviderPath,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][ValidatePattern('^[0-9a-f]{64}$')][string]$ProviderSha256,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][string]$StopPath,
    [Parameter(Mandatory=$true,ParameterSetName="Public")][ValidateSet("I_START_PUBLIC_SHADOW_ONLY")][string]$Confirmation,
    [Parameter(Mandatory=$true,ParameterSetName="Agreement")][string]$SourcePath,
    [Parameter(Mandatory=$true,ParameterSetName="Agreement")][ValidatePattern('^[0-9a-f]{64}$')][string]$ReceiptSha256
)
$ErrorActionPreference = "Stop"
$env:PSModulePath = Join-Path ([Environment]::GetFolderPath("Windows")) "System32\WindowsPowerShell\v1.0\Modules"
. (Join-Path $PSScriptRoot "workload_admission.ps1")
. (Join-Path $PSScriptRoot "windows_kill_on_close_job.ps1")
$repo = (Get-Item -LiteralPath (Join-Path $PSScriptRoot "..\..") -Force).FullName
foreach ($path in @($PythonPath, $OutputPath, $ManifestPath, $ProviderPath, $StopPath, $SourcePath)) {
    if (-not $path) { continue }
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '[\r\n]') { throw "absolute paths required" }
    $cursor = [IO.Path]::GetFullPath($path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "redirected path" }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
if ([IO.Path]::GetFileName($PythonPath) -cne "python.exe" -or -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "regular project CPython required"
}
if (Test-Path -LiteralPath $OutputPath) { throw "output must be create-only" }
$tokens = @("-m", "weather.market.maker_shadow")
$deadline = [DateTime]::UtcNow.AddMinutes(10)
if ($PSCmdlet.ParameterSetName -ceq "Public") {
    if ((Get-FileHash -LiteralPath $ManifestPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ManifestSha256 -or
        (Get-FileHash -LiteralPath $ProviderPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ProviderSha256) {
        throw "frozen input digest differs"
    }
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    $tip = git -C $repo rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $tip -cne $manifest.code_revision) { throw "manifest code revision differs" }
    $dirty = git -C $repo status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw "public shadow requires clean pinned source" }
    $start = [DateTimeOffset]::Parse($manifest.start.value).UtcDateTime
    $deadline = [DateTimeOffset]::Parse($manifest.end.value).UtcDateTime.AddSeconds(5)
    if ($start -lt [DateTime]::UtcNow -or $start -gt [DateTime]::UtcNow.AddMinutes(10) -or
        $deadline -gt $start.AddDays(14).AddSeconds(5)) { throw "bounded future interval required" }
    $tokens += @("public", "--manifest", $ManifestPath, "--manifest-sha256", $ManifestSha256,
        "--provider", $ProviderPath, "--provider-sha256", $ProviderSha256, "--stop-file", $StopPath)
} else {
    $tokens += @("agreement", "--source", $SourcePath, "--receipt-sha256", $ReceiptSha256)
}
$tokens += @("--output", $OutputPath)
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $repo -Workload "WorkstationPublicShadow-$PID" -ExecutionHostProfile "workstation_public_shadow"
if ($null -eq $lease) { throw "workstation shadow blocked by active heavy or live workload" }
$job = $null
$child = $null
$exitCode = 1
try {
    $job = New-WeatherKillOnCloseJob
    $child = Start-WeatherInteractiveProcessInJob -Job $job -FilePath $PythonPath `
        -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) -WorkingDirectory $repo
    while (-not $child.WaitForExit(250)) {
        $child.Refresh()
        if ([DateTime]::UtcNow -ge $deadline -or $child.PrivateMemorySize64 -gt 536870912) {
            throw "shadow deadline or 512 MiB process ceiling; segment remains incomplete"
        }
    }
    $exitCode = $child.ExitCode
} finally {
    $transitionError = $null
    $teardownError = $null
    try { Set-WeatherHeavyWorkloadLeaseTeardownPending -Lease $lease | Out-Null } catch { $transitionError = $_ }
    if ($job -and $null -eq $transitionError) {
        try { $job.TerminateAndWait(5000) } catch { $teardownError = $_ }
    }
    if ($child) { $child.Dispose() }
    if ($job) { $job.Dispose() }
    if ($transitionError) { throw $transitionError }
    if ($teardownError) {
        Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease
        throw $teardownError
    }
    Exit-WeatherHeavyWorkloadLease -Lease $lease
}
exit $exitCode
