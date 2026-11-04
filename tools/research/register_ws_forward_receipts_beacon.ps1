# R20: register the forward receipts beacon task on the WORKSTATION (master ruling 2026-11-01, section 2).
# NOT REGISTERED. Registration needs the owner's yes in the coordinator's chat (a WS scheduled task, conflict C18).
# Run with -WhatIf first: it prints the full definition as JSON and calls no Scheduler command.
#
# Action: tools\research\ws_forward_receipts_beacon.ps1 from -Worktree (a pinned, locked worktree at the reviewed
# tip), with -ShareRoot (the host-name form of the xfer share) and -FallbackShareRoot (its IP form). Both are
# parameters here; nothing in the repository names the host's address.
# Triggers: one -Once trigger at the next :10 or :40, repeating every 30 minutes indefinitely (an interval trigger,
# so it keeps :10/:40 across DST), plus AtLogOn for this user.
# Principal: current user, Interactive / Limited. This is the vault exception: the share is reached with the
# workstation's stored credential, which an S4U session cannot use (as the MG-2 pull and L6_G daily tasks). The
# task runs only while the user is logged on, and stops after an unattended restart until the next logon.
# Settings: MultipleInstances IgnoreNew, ExecutionTimeLimit 5 minutes, no StartWhenAvailable (the next half hour is
# the retry). -ExpectedBeaconSha256 is required to register: the beacon on disk must be exactly the reviewed one.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'R20 forward receipts beacon',
    [string]$Worktree = '',
    [string]$WorkingDirectory = 'C:\t\forward-receipts-beacon',
    [string]$ShareRoot = '',
    [string]$FallbackShareRoot = '',
    [string]$ExpectedBeaconSha256 = ''
)
# Windows PowerShell 5.1 leaves $PSScriptRoot and $PSCommandPath empty inside an advanced script's param()
# defaults under `powershell -File`; derive the default here. An explicit -Worktree always wins.
if (-not $Worktree) {
    $Worktree = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
}
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $repoRoot 'scripts\ops\scheduled_task_test_guard.ps1')
# A plain name only: no path separators or wildcard/reserved characters, no leading or trailing space.
if ([string]::IsNullOrWhiteSpace($TaskName) -or $TaskName -ne $TaskName.Trim() -or $TaskName.Length -gt 200 -or
    $TaskName.IndexOfAny([char[]]'/\:*?"<>|') -ge 0) {
    throw "invalid task name: '$TaskName' (no / \ : * ? `" < > | and no leading/trailing space)"
}
foreach ($pair in @(@('ShareRoot', $ShareRoot), @('FallbackShareRoot', $FallbackShareRoot))) {
    if ($pair[1] -and ($pair[1] -notmatch '^\\\\[^\\\s"]+\\[^\\\s"]+$')) {
        throw "-$($pair[0]) must be a share root of the form \\host\share (no spaces, quotes or trailing path)"
    }
}
if (-not $ShareRoot) { throw 'pass -ShareRoot (the host-name form of the xfer share root)' }
foreach ($path in @($Worktree, $WorkingDirectory)) {
    if (-not [IO.Path]::IsPathRooted($path) -or $path -match '["\r\n]' -or $path -match '\s') {
        throw "absolute paths without spaces, quotes or newlines are required: '$path'"
    }
}
$beacon = Join-Path $Worktree 'tools\research\ws_forward_receipts_beacon.ps1'
if (-not (Test-Path -LiteralPath $beacon -PathType Leaf)) { throw "beacon missing: $beacon" }
# Get-FileHash honours -WhatIf and would return nothing under it, so hash directly.
$sha = [Security.Cryptography.SHA256]::Create()
$beaconSha = (($sha.ComputeHash([IO.File]::ReadAllBytes($beacon)) | ForEach-Object { $_.ToString('x2') }) -join '')
$expected = $ExpectedBeaconSha256.Trim().ToLowerInvariant()
if ($expected -and $beaconSha -cne $expected) { throw "beacon sha256 $beaconSha != expected $expected" }

$user = "$env:USERDOMAIN\$env:USERNAME"
$exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$argument = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$beacon`" " +
    "-ShareRoot `"$ShareRoot`" -LogRoot `"$WorkingDirectory`""
if ($FallbackShareRoot) { $argument += " -FallbackShareRoot `"$FallbackShareRoot`"" }
$now = Get-Date
$start = $now.Date.AddHours($now.Hour).AddMinutes(10)
while ($start -le $now) { $start = $start.AddMinutes(30) }
$timeLimit = 'PT5M'
$interval = 'PT30M'
$description = "R20 research: forward receipts beacon. Projects C:\t\mg2\forward\input_receipts.jsonl and " +
    "C:\t\l6g\forward\{bundle,input}_receipts.jsonl plus heartbeat.json to <share>\in\forward-receipts; " +
    "logs $WorkingDirectory\runs.jsonl."

if (-not $PSCmdlet.ShouldProcess($TaskName, 'Register-ScheduledTask (owner yes required)')) {
    [ordered]@{
        task_name = $TaskName; execute = $exe; arguments = $argument; working_directory = $WorkingDirectory
        triggers = @(
            [ordered]@{ type = 'Once'; start_local = $start.ToString('yyyy-MM-ddTHH:mm:ss'); repetition_interval = $interval
                repetition_duration = 'indefinite' },
            [ordered]@{ type = 'AtLogOn'; user = $user })
        principal = "$user Interactive Limited"
        execution_time_limit = $timeLimit; multiple_instances = 'IgnoreNew'; start_when_available = $false
        beacon_path = $beacon; beacon_sha256 = $beaconSha; registered = $false
    } | ConvertTo-Json -Compress -Depth 4
    return
}

Assert-WeatherScheduledTaskTestIsolation -Command @('Register-ScheduledTask', 'Get-ScheduledTask', 'Disable-ScheduledTask')
if (-not $expected) { throw "pass -ExpectedBeaconSha256 (beacon sha256 is $beaconSha)" }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw "task already exists: $TaskName" }
# The task's working directory must exist before the first start, or the task cannot start at all.
[void][IO.Directory]::CreateDirectory($WorkingDirectory)
$action = New-ScheduledTaskAction -Execute $exe -Argument $argument -WorkingDirectory $WorkingDirectory
$repeat = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes 30)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$null = Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($repeat, $logon) -Principal $principal `
    -Settings $settings -Description $description
$actual = Get-ScheduledTask -TaskName $TaskName
$actions = @($actual.Actions | Where-Object { $null -ne $_ })
$triggers = @($actual.Triggers | Where-Object { $null -ne $_ })
$repeating = @($triggers | Where-Object { $_.Repetition -and [string]$_.Repetition.Interval -ceq $interval })
$logons = @($triggers | Where-Object { [string]$_.CimClass.CimClassName -ceq 'MSFT_TaskLogonTrigger' })
if ($actions.Count -ne 1 -or [string]$actions[0].Execute -ine $exe -or [string]$actions[0].Arguments -cne $argument -or
    ([string]$actions[0].WorkingDirectory).TrimEnd('\') -ine $WorkingDirectory.TrimEnd('\') -or
    $triggers.Count -ne 2 -or $repeating.Count -ne 1 -or [string]$repeating[0].Repetition.Duration -or
    $logons.Count -ne 1 -or
    [string]$actual.Principal.LogonType -cne 'Interactive' -or [string]$actual.Principal.RunLevel -cne 'Limited' -or
    [string]$actual.Settings.ExecutionTimeLimit -cne $timeLimit -or
    [string]$actual.Settings.MultipleInstances -cne 'IgnoreNew' -or $actual.Settings.StartWhenAvailable) {
    Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null
    throw 'registered beacon task does not match the reviewed action, triggers, principal and settings; the task was disabled'
}
Write-Output ("registered {0}: logon={1} state={2} interval={3} beacon_sha256={4}" -f $TaskName,
    $actual.Principal.LogonType, $actual.State, $interval, $beaconSha)
