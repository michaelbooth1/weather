# Register one immutable S4U preflight or both fixed future night segments.
param(
    [Parameter(Mandatory = $true)][string]$ProductionRepoRoot,
    [Parameter(Mandatory = $true)][string]$PlanPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PlanSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$sourceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'storage_recovery_night_contract.ps1')
Assert-WeatherNightSource $sourceRoot $ExpectedSourceTip
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$plan = Read-WeatherNightPlan $ProductionRepoRoot $sourceRoot $ExpectedSourceTip $PlanPath $PlanSha256
$nightRoot = Join-Path $ProductionRepoRoot ('scratch\storage_recovery_nights\' + $plan.plan_id)
Assert-WeatherNightDirectory $nightRoot
$early = Get-WeatherNightTimes $plan 'early'
if ([DateTime]::UtcNow.AddMinutes(5) -ge $early.Start) { throw 'register at least five minutes before the night' }
$mode = 'segments'
if ($PreflightOnly) { $mode = 'preflight' }
$registrationRoot = Join-Path $nightRoot ('registration-' + $mode)
if (Test-Path -LiteralPath $registrationRoot) { throw 'spent registration namespace' }
if (-not $PreflightOnly) {
    $preflightRoot = Join-Path $nightRoot 'preflight'
    $wrapperPath = Join-Path $preflightRoot 'wrapper-result.json'
    $wrapper = Read-WeatherNightRetainedJson $wrapperPath
    $resultPath = Join-Path $preflightRoot 'result.json'
    if ($wrapper.status -cne 'PASS' -or $wrapper.child_status -cne 'PREFLIGHT_PASS' -or
        $wrapper.teardown_proved -ne $true -or $wrapper.hard_stop -ne $false -or
        $wrapper.plan_sha256 -cne $PlanSha256 -or $wrapper.source_git_sha -cne $ExpectedSourceTip -or
        $wrapper.execution_host_id -cne $plan.execution_host_id -or $wrapper.segment -cne 'preflight' -or
        $wrapper.deleted_files -ne 0 -or $wrapper.cleanup_eligible -ne $false -or
        (Get-FileHash -LiteralPath $resultPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $wrapper.child_result_sha256) {
        throw 'a successful exact S4U preflight is required before arming'
    }
    $null = Read-WeatherNightRetainedJson $resultPath $wrapper.child_result_sha256
    $registration = Read-WeatherNightRetainedJson (Join-Path $nightRoot 'registration-preflight\preflight-result.json')
    if ($registration.status -cne 'PASS' -or $registration.plan_sha256 -cne $PlanSha256 -or
        $registration.source_git_sha -cne $ExpectedSourceTip -or
        $registration.task_name -cne ('WeatherStorageRecovery-' + $plan.plan_id + '-preflight')) {
        throw 'preflight registration receipt binding mismatch'
    }
    $currentXml = Export-ScheduledTask -TaskName $registration.task_name -TaskPath '\'
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $xmlHash = [BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($currentXml))).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose() }
    if ($xmlHash -cne $registration.task_xml_sha256) { throw 'preflight task changed since verified registration' }
    $preflightTask = Get-ScheduledTask -TaskName ('WeatherStorageRecovery-' + $plan.plan_id + '-preflight') -TaskPath '\'
    $preflightInfo = $preflightTask | Get-ScheduledTaskInfo
    if ([string]$preflightTask.State -ne 'Ready' -or $preflightInfo.LastTaskResult -ne 0 -or
        [string]$preflightTask.Principal.UserId -ine $env:USERNAME -or
        [string]$preflightTask.Principal.LogonType -ne 'S4U' -or
        [string]$preflightTask.Principal.RunLevel -ne 'Limited' -or
        ([DateTimeOffset]::Parse($wrapper.started_at_utc).UtcDateTime - $preflightInfo.LastRunTime.ToUniversalTime()).Duration().TotalSeconds -gt 60) { throw 'S4U preflight has not closed successfully' }
}
$segments = @('early','late')
if ($PreflightOnly) { $segments = @('preflight') }
foreach ($segment in $segments) {
    $name = 'WeatherStorageRecovery-' + $plan.plan_id + '-' + $segment
    if (@(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue).Count -ne 0) {
        throw ('task namespace already exists: ' + $name)
    }
}
$null = New-Item -ItemType Directory -Path $registrationRoot
$powerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$runner = Join-Path $PSScriptRoot 'storage_recovery_night_run.ps1'
foreach ($segment in $segments) {
    Assert-WeatherNightSource $sourceRoot $ExpectedSourceTip
    $null = Read-WeatherNightPlan $ProductionRepoRoot $sourceRoot $ExpectedSourceTip $PlanPath $PlanSha256
    $name = 'WeatherStorageRecovery-' + $plan.plan_id + '-' + $segment
    $runtimeMinutes = 254
    $at = $early.Start
    $argumentSegment = $segment
    if ($segment -eq 'late') { $at = (Get-WeatherNightTimes $plan 'late').Start; $runtimeMinutes = 134 }
    if ($segment -eq 'preflight') { $at = [DateTime]::UtcNow.AddSeconds(45); $runtimeMinutes = 2; $argumentSegment = 'early' }
    $tokens = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$runner,
        '-ProductionRepoRoot',$ProductionRepoRoot,'-PlanPath',$PlanPath,'-PlanSha256',$PlanSha256,
        '-ExpectedSourceTip',$ExpectedSourceTip,'-Segment',$argumentSegment)
    if ($PreflightOnly) { $tokens += '-PreflightOnly' }
    $arguments = ConvertTo-WeatherWindowsArgumentString -Tokens $tokens
    $action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments -WorkingDirectory $sourceRoot
    $trigger = New-ScheduledTaskTrigger -Once -At $at.ToLocalTime()
    $options = @{MultipleInstances='IgnoreNew'; Hidden=$true; ExecutionTimeLimit=(New-TimeSpan -Minutes $runtimeMinutes)
                 WakeToRun=$true; AllowStartIfOnBatteries=$true; DontStopIfGoingOnBatteries=$true}
    $settings = New-ScheduledTaskSettingsSet @options
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
    $intent = @{task_name=$name; task_path='\'; plan_sha256=$PlanSha256; source_git_sha=$ExpectedSourceTip
                execute=$powerShell; arguments=$arguments; working_directory=$sourceRoot
                start_utc=$at.ToString('o'); execution_time_limit=('PT' + $runtimeMinutes + 'M')
                prior_task_absent=$true; mutation='REGISTER_ONCE'; created_at_utc=[DateTime]::UtcNow.ToString('o')}
    Write-WeatherNightJson (Join-Path $registrationRoot ($segment + '-intent.json')) $intent
    $registration = @{TaskName=$name; TaskPath='\'; Action=$action; Trigger=$trigger; Settings=$settings
                      Description='One approved bounded retained-file recovery segment; no deletion or live authority.'}
    $null = Register-ScheduledTask @registration -Principal $principal
    $task = Get-ScheduledTask -TaskName $name -TaskPath '\'
    $actions, $triggers = @($task.Actions), @($task.Triggers)
    if ([string]$task.State -eq 'Disabled' -or $actions.Count -ne 1 -or $triggers.Count -ne 1 -or
        [string]$actions[0].Execute -ine $powerShell -or [string]$actions[0].Arguments -cne $arguments -or
        [string]$actions[0].WorkingDirectory -ine $sourceRoot -or
        [string]$triggers[0].CimClass.CimClassName -ne 'MSFT_TaskTimeTrigger' -or
        ([DateTimeOffset]::Parse($triggers[0].StartBoundary).UtcDateTime - $at).Duration().TotalSeconds -ge 1 -or
        -not [bool]$triggers[0].Enabled -or -not [string]::IsNullOrWhiteSpace([string]$triggers[0].Repetition.Interval) -or
        [Xml.XmlConvert]::ToTimeSpan([string]$task.Settings.ExecutionTimeLimit) -ne (New-TimeSpan -Minutes $runtimeMinutes) -or
        [bool]$task.Settings.StartWhenAvailable -or -not [bool]$task.Settings.WakeToRun -or
        [string]$task.Settings.MultipleInstances -ne 'IgnoreNew' -or -not [bool]$task.Settings.Hidden -or
        [bool]$task.Settings.DisallowStartIfOnBatteries -or [bool]$task.Settings.StopIfGoingOnBatteries -or
        [string]$task.Principal.UserId -ine $env:USERNAME -or [string]$task.Principal.LogonType -ne 'S4U' -or
        [string]$task.Principal.RunLevel -ne 'Limited') { throw ('registration readback mismatch: ' + $name) }
    $xml = Export-ScheduledTask -TaskName $name -TaskPath '\'
    $xmlPath = Join-Path $registrationRoot ($segment + '-registered.xml')
    $stream = [IO.File]::Open($xmlPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $bytes = [Text.Encoding]::UTF8.GetBytes($xml); $stream.Write($bytes,0,$bytes.Length); $stream.Flush($true) }
    finally { $stream.Dispose() }
    Write-WeatherNightJson (Join-Path $registrationRoot ($segment + '-result.json')) @{
        status='PASS'; task_name=$name; plan_sha256=$PlanSha256; source_git_sha=$ExpectedSourceTip
        task_xml_sha256=(Get-FileHash -LiteralPath $xmlPath -Algorithm SHA256).Hash.ToLowerInvariant()
        verified_at_utc=[DateTime]::UtcNow.ToString('o'); start_utc=$at.ToString('o')
    }
    Write-Output ('Registered and verified ' + $name + ' at ' + $at.ToString('o'))
}
