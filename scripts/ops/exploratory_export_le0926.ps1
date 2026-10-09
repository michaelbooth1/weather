<#
EXPLORATORY_NOT_COUNTED host twin of the nightly v0.2 exporter (EXPLORATORY-SHADOW-HOST-SPEC plan 3A).
Exports ONE bundle day in 2026-09-23..2026-09-26 by running the sibling replay_bundle_export_nightly.ps1 with an
explicit -Day and -Kind night. The first statement refuses any day after 2026-09-26 (exit 2) before any path,
lease or Python. It takes no lease itself: the nightly wrapper takes the shared lease, and a lease held here
would make the wrapper refuse as busy. DataRoot and ReleaseRoot are always derived from ProductionRoot.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('\A2026-09-2[3-6]\z')][string]$Day,
    [Parameter(Mandatory = $true)][string]$DeployRoot,
    [Parameter(Mandatory = $true)][string]$ProductionRoot,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[0-9a-f]{64}\z')][string]$ExpectedModuleSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('\A[0-9a-f]{64}\z')][string]$ExpectedSelfSha256,
    [ValidateRange(512, 65536)][int]$MinAvailableMiB = 4096
)
if (-not ($Day -cmatch '\A2026-09-2[3-6]\z') -or [DateTime]::ParseExact($Day, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) -gt [DateTime]::new(2026, 9, 26)) { [Console]::Out.WriteLine('{"status":"REFUSED","reason":"exploratory_day_after_2026-09-26"}'); exit 2 }
$ErrorActionPreference = 'Stop'
$wrapper = Join-Path $PSScriptRoot 'replay_bundle_export_nightly.ps1'
if (-not (Test-Path -LiteralPath $wrapper -PathType Leaf)) { [Console]::Error.WriteLine("missing $wrapper"); exit 10 }
$arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $wrapper,
    '-DeployRoot', $DeployRoot, '-ProductionRoot', $ProductionRoot,
    '-DataRoot', (Join-Path $ProductionRoot 'data'), '-ReleaseRoot', (Join-Path $ProductionRoot 'artifacts\releases'),
    '-OutputRoot', $OutputRoot, '-ExpectedModuleSha256', $ExpectedModuleSha256,
    '-ExpectedSelfSha256', $ExpectedSelfSha256, '-Day', $Day, '-Kind', 'night',
    '-MinAvailableMiB', [string]$MinAvailableMiB)
& powershell.exe @arguments
exit $LASTEXITCODE
