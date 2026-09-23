# Register only after production integration and dependency verification.
# Public-data capture only. Editing/testing this registrar does not arm it.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$TaskName = "WeatherMakerEvidenceCapture"
)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Repository pythonw is absent." }
$root = Join-Path $RepoRoot "data\maker_evidence"
$extra = Join-Path $root "extra_conditions.json"
$arguments = '-m weather.market.maker_evidence_capture --root "{0}" --extra-conditions "{1}"' -f $root, $extra
if (-not $PSCmdlet.ShouldProcess($TaskName, "Register public maker-evidence capture")) { return }
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 10
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Independent public maker evidence; minute books/rewards, capped raw stream, continuous public trades; no account/order path." `
    -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName
if ($registered.Actions.Execute -ne $python -or $registered.Actions.Arguments -ne $arguments -or
    $registered.Actions.WorkingDirectory -ne $RepoRoot -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited" -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    $registered.Settings.Priority -ne 10 -or
    $registered.Triggers[0].Repetition.Interval -ne "PT1M") {
    throw "Registered maker evidence task did not match its contract."
}
Write-Output "Registered $TaskName; verify data\maker_evidence\status.json after the first complete minute."
