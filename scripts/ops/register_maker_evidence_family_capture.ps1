# Register only after production integration (not before 2026-10-14) and dependency verification.
# Public-data capture only, books and reward terms, no websocket. Editing/testing this registrar does not arm it.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [ValidatePattern('^[a-z][a-z0-9_]{0,40}$')]
    [string]$Family = "lowest_temperature",
    [string]$TaskName = "WeatherMakerEvidenceLowestTemperature"
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Repository pythonw is absent." }
$families = Get-Content -LiteralPath (Join-Path $RepoRoot "config\capture_families.json") -Raw | ConvertFrom-Json
if ($null -eq $families.families.$Family) { throw "Capture family '$Family' is not in config\capture_families.json." }
$root = Join-Path $RepoRoot "data\maker_evidence_families\$Family"
$arguments = '-m weather.market.maker_evidence_capture --family {0} --root "{1}"' -f $Family, $root
if (-not $PSCmdlet.ShouldProcess($TaskName, "Register public capture family $Family")) { return }
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 10
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Passive public capture family '$Family': minute books and reward terms in its own root; no websocket, no account/order path." `
    -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName
if ($registered.Actions.Execute -ne $python -or $registered.Actions.Arguments -ne $arguments -or
    $registered.Actions.WorkingDirectory -ne $RepoRoot -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited" -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    $registered.Settings.Priority -ne 10 -or
    $registered.Triggers[0].Repetition.Interval -ne "PT1M") {
    throw "Registered capture family task did not match its contract."
}
Write-Output "Registered $TaskName; verify data\maker_evidence_families\$Family\status.json after the first complete minute."
