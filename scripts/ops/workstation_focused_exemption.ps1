# Workstation focused-run exemption (owner decision 2026-10-04, P3), PowerShell side.
#
# Dot-source this file, then call
#   Test-WeatherWorkstationFocusedPytestExemption -RepoRoot <repo> -PythonPath <python.exe> -Arguments <pytest args>
# It proves the non-capture host identity with workload_admission.ps1 first; the capture
# host (or an unprovable identity) is refused before any file is classified. The file rules
# live in one place, the Codex host-load hook's classifier. workload_admission.ps1 itself
# stays independent of the hook.

$admissionScript = Join-Path $PSScriptRoot "workload_admission.ps1"
if (-not (Test-Path -LiteralPath $admissionScript -PathType Leaf)) {
    throw "workload_admission.ps1 is missing beside the focused-run exemption helper"
}
. $admissionScript

function Test-WeatherWorkstationFocusedPytestExemption {
    # Returns {Exempt, Reason}. The capture host (or an unprovable identity) is
    # refused here before any file is classified; the file rules live in one
    # place, the Codex host-load hook's `focused_pytest_verdict`.
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$PythonPath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [string]$WorkingDirectory = ""
    )

    $refuse = {
        param([string]$Reason)
        [PSCustomObject]@{ Exempt = $false; Reason = $Reason }
    }
    try {
        $executionHostId = Get-WeatherExecutionHostId
        $assignment = Get-WeatherExecutionHostAssignment -RepoRoot $RepoRoot
    }
    catch {
        return & $refuse (
            "cannot prove this host differs from the dedicated capture host"
        )
    }
    if ($executionHostId -ceq
        [string]$assignment.dedicated_capture_execution_host_id) {
        return & $refuse (
            "the dedicated capture host has no focused-run exemption; use the " +
            "bounded suite inside the 00:30-09:00 window"
        )
    }
    $markerPath = ""
    try { $markerPath = Get-WeatherHeavyWorkloadPoisonPath }
    catch {
        $stateRoot = Join-Path ([Environment]::GetFolderPath(
            [Environment+SpecialFolder]::CommonApplicationData)) "WeatherProject"
        if (Test-Path -LiteralPath $stateRoot) {
            return & $refuse "host-global workload state cannot be validated"
        }
    }
    if (-not $WorkingDirectory) { $WorkingDirectory = (Get-Location).Path }
    $hook = Join-Path $RepoRoot ".codex\hooks\pre_tool_use_host_load.py"
    if (-not (Test-Path -LiteralPath $hook -PathType Leaf)) {
        return & $refuse "the focused-run classifier is missing"
    }
    $request = [ordered]@{
        arguments = @($Arguments)
        cwd = $WorkingDirectory
        marker_path = $markerPath
    } | ConvertTo-Json -Compress
    $encoded = [Convert]::ToBase64String(
        [Text.UTF8Encoding]::new($false).GetBytes($request)
    )
    try {
        $output = & $PythonPath -I -B $hook --classify-focused-pytest $encoded
        if ($LASTEXITCODE -ne 0) { throw "classifier exited $LASTEXITCODE" }
        $verdict = (@($output) -join "") | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return & $refuse "the focused-run classifier failed: $($_.Exception.Message)"
    }
    if ($verdict.exempt -isnot [bool] -or $verdict.reason -isnot [string]) {
        return & $refuse "the focused-run classifier returned a malformed verdict"
    }
    return [PSCustomObject]@{
        Exempt = [bool]$verdict.exempt
        Reason = [string]$verdict.reason
    }
}

