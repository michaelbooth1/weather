# Registers WeatherEvidenceHost, the Data Layer v2 PL-6 evidence host (docs/operations/EVIDENCE_HOST.md).
# Public, free, read-only GETs only (AWC, api.weather.gov, HKO, JMA, ECCC, DWD, Open-Meteo meta,
# Gamma); no credential, wallet, signer or order client is importable from it. Editing or testing
# this registrar does not arm it: registration is an explicit owner/production act.
#
# One long-lived `python -m weather.evidence.host run` parent supervises one child per enabled
# family, each inside a kill-on-close Job object with a hard commit cap. The 1-minute repetition
# only respawns the parent after a crash or reboot (IgnoreNew while it runs; a second parent also
# exits at once on the root's host lock). Stop it with `python -m weather.evidence.host stop`
# (children close and seal their segments within about a second); while the stop file exists every
# respawn exits at once (exit 0; host_status.json says why). New code is adopted only by an explicit
# `python -m weather.evidence.host restart --family <id>` (owner Q11).
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = "",
    [string]$TaskName = "WeatherEvidenceHost",
    [string]$ConfigPath = ""
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an
# advanced script's param() defaults under `powershell -File`; derive the default
# here. An explicit -RepoRoot always wins.
if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $RepoRoot "venv\Scripts\pythonw.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Repository pythonw is absent." }
if (-not $ConfigPath) { $ConfigPath = Join-Path $RepoRoot "config\evidence_host.json" }
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "Evidence host config $ConfigPath is absent." }
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ([string]$config.schema_version -ne "evidence_host_config_v1") { throw "Evidence host config schema is not v1." }
if ([int]$config.host.parent_ram_cap_mib -le 0 -or [int]$config.host.parent_ram_cap_mib -gt 64) {
    throw "Evidence host parent cap must be 1-64 MiB."
}
foreach ($family in $config.families.PSObject.Properties) {
    if (-not ([string]$family.Value.module).StartsWith("weather.evidence.families.")) {
        throw "Family $($family.Name) must run a weather.evidence.families module."
    }
    if ([int]$family.Value.ram_cap_mib -le 0) { throw "Family $($family.Name) needs a positive ram_cap_mib." }
}
$arguments = '-m weather.evidence.host --config "{0}" run' -f $ConfigPath
if (-not $PSCmdlet.ShouldProcess($TaskName, "Register the read-only evidence host supervisor")) { return }
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 3650)
# Priority 10 = idle process priority: every capture loop wins every CPU race.
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 10
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "DLv2 evidence host: public read-only weather/Gamma GETs into change-only journals under data\evidence; no account, signing or order path." `
    -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName
if ($registered.Actions.Execute -ne $python -or $registered.Actions.Arguments -ne $arguments -or
    $registered.Actions.WorkingDirectory -ne $RepoRoot -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited" -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    $registered.Settings.Priority -ne 10 -or
    $registered.Triggers[0].Repetition.Interval -ne "PT1M") {
    throw "Registered evidence host task did not match its contract."
}
Write-Output "Registered $TaskName; verify with python -m weather.evidence.host status after two minutes."
