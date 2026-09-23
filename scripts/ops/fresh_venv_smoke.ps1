# Requirements-only imports, in a temporary venv owned by the workstation Job.
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$repo = (Get-Item -LiteralPath (Join-Path $PSScriptRoot '../..')).FullName
$arguments = @('-m', 'weather.operations.fresh_venv_smoke')
$encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($arguments | ConvertTo-Json -Compress)))
& (Join-Path $PSScriptRoot 'workstation_heavy.ps1') -Kind weather_heavy `
    -PythonPath $PythonPath -ArgumentsBase64 $encoded -RepoRoot $repo
exit $LASTEXITCODE
