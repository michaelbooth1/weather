# Registers the forward, paper-only maker shadow runner (#192, informed-maker Phase 3).
# Public International Polymarket GET reads only; no credential, wallet, signer or order
# client is importable from it (docs/operations/maker-shadow-runner.md). Editing or
# testing this registrar does not arm it: registration is an explicit owner/production act.
#
# One long-lived `python -m weather.market.maker_shadow run` process tapes every minute
# under data\maker_shadow\tapes and seals each UTC day at the day roll. The repetition
# trigger only respawns it after a crash or reboot (IgnoreNew while it runs). Stop it
# with the stop file (the run seals its tape at the next minute and exits); do NOT use
# Stop-ScheduledTask, which kills the process and leaves an unsealed tape the scorer
# never reads. While the stop file exists every respawn refuses at once (exit 2).
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$RepoRoot = "",
    [string]$TaskName = "WeatherMakerShadowRunner",
    [string]$ConfigPath = "",
    [string]$StopFile = ""
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
$root = Join-Path $RepoRoot "data\maker_shadow"
if (-not $ConfigPath) { $ConfigPath = Join-Path $root "shadow_config.json" }
if (-not $StopFile) { $StopFile = Join-Path $root "STOP" }
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Shadow config $ConfigPath is absent; write it first (docs/operations/maker-shadow-runner.md)."
}
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ([string]$config.schema_version -ne "weather.maker_shadow_config.v0.1") { throw "Shadow config schema is not v0.1." }
if ([string]$config.guard.policy.campaign_id -ne "shadow-maker") { throw "Shadow guard policy must name the paper campaign." }
if ($config.guard.PSObject.Properties.Name -contains "wallet_book" -or
    $config.guard.PSObject.Properties.Name -contains "campaigns") { throw "Shadow config must not name a wallet book." }
if (-not (Test-Path -LiteralPath ([string]$config.guard.latch_dir) -PathType Container)) {
    throw "Guard latch is not initialised; run python -m maker_core.runtime.guard_latch init --state-dir <latch_dir>."
}
$arguments = '-m weather.market.maker_shadow run --config "{0}" --stop-file "{1}"' -f $ConfigPath, $StopFile
if (-not $PSCmdlet.ShouldProcess($TaskName, "Register the paper-only public maker shadow runner")) { return }
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
# Priority 7 = BelowNormal process priority: the capture loops run AboveNormal and win every CPU race.
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Paper-only maker shadow: public book/reward/print GETs, per-minute sealed quotes tape; no account, signing or order path." `
    -Force | Out-Null
$registered = Get-ScheduledTask -TaskName $TaskName
if ($registered.Actions.Execute -ne $python -or $registered.Actions.Arguments -ne $arguments -or
    $registered.Actions.WorkingDirectory -ne $RepoRoot -or
    [string]$registered.Principal.LogonType -ne "S4U" -or
    [string]$registered.Principal.RunLevel -ne "Limited" -or
    [string]$registered.Settings.MultipleInstances -ne "IgnoreNew" -or
    $registered.Settings.Priority -ne 7 -or
    $registered.Triggers[0].Repetition.Interval -ne "PT5M") {
    throw "Registered maker shadow task did not match its contract."
}
Write-Output "Registered $TaskName; verify with scripts\ops\maker_shadow_readout.ps1 after two complete minutes."
