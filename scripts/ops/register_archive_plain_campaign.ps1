# Register only an exact future archive campaign or its metadata-only S4U preflight.
param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ConfigSha256,[Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedSourceTip,[switch]$PreflightOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$source=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'archive_plain_campaign_contract.ps1')
Assert-WeatherPlainSource $source $ExpectedSourceTip
. (Join-Path $PSScriptRoot 'storage_recovery_night_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$record=Read-WeatherPlainMetadata $ConfigPath $ConfigSha256 65536
$c=Assert-WeatherPlainConfiguration $record.Value
$hostId=Get-WeatherExecutionHostId
$assignment=Get-WeatherExecutionHostAssignment -RepoRoot $source
if($hostId -cne $assignment.dedicated_capture_execution_host_id -or $hostId -cne $c.execution_host_id -or $assignment.active_portable_execution_host_id -cne $c.backup_execution_host_id -or $c.source_tip -cne $ExpectedSourceTip){throw 'Registrar host/source differs'}
$root=[IO.Path]::GetFullPath($c.production_root)
$start=[DateTimeOffset]::Parse($c.start_utc).UtcDateTime
if([DateTime]::UtcNow.AddMinutes(5) -ge $start){throw 'Register at least five minutes before the approved window'}
$campaign=Join-Path $root ('scratch/archive_plain_campaigns/'+$c.campaign_id)
Assert-WeatherNightDirectory $campaign
$mode='run';$at=$start;$minutes=254
if($PreflightOnly){$mode='preflight';$at=[DateTime]::UtcNow.AddSeconds(45);$minutes=4}
$registrationRoot=Join-Path $campaign ('registration-'+$mode)
if(Test-Path -LiteralPath $registrationRoot){throw 'Spent campaign registration namespace'}
$name='WeatherPlainArchive-'+$c.campaign_id+'-'+$mode
if(@(Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue).Count -ne 0){throw 'Task namespace already exists'}
if(-not $PreflightOnly){
 $preflightRoot=Join-Path $campaign 'preflight'
 $wrapper=(Read-WeatherPlainMetadata (Join-Path $preflightRoot 'wrapper-result.json') '' 65536).Value
 if($wrapper.status -cne 'PASS' -or $wrapper.child_status -cne 'PREFLIGHT_PASS' -or $wrapper.teardown_proved -ne $true -or $wrapper.hard_stop -ne $false -or $wrapper.config_sha256 -cne $ConfigSha256 -or $wrapper.source_git_sha -cne $ExpectedSourceTip -or $wrapper.execution_host_id -cne $hostId -or $wrapper.verified_new_original_deleted_files -ne 0 -or $wrapper.verified_new_original_reclaimed_bytes -ne 0){throw 'Exact successful preflight required before arming'}
 $null=Read-WeatherPlainMetadata (Join-Path $preflightRoot 'result.json') $wrapper.child_result_sha256
 $registered=(Read-WeatherPlainMetadata (Join-Path $campaign 'registration-preflight/result.json') '' 65536).Value
 if($registered.status -cne 'PASS' -or $registered.task_name -cne ('WeatherPlainArchive-'+$c.campaign_id+'-preflight') -or $registered.config_sha256 -cne $ConfigSha256 -or $registered.source_git_sha -cne $ExpectedSourceTip){throw 'S4U registration proof differs'}
 $task=Get-ScheduledTask -TaskName $registered.task_name -TaskPath '\'
 $info=$task|Get-ScheduledTaskInfo
 $xml=Export-ScheduledTask -TaskName $registered.task_name -TaskPath '\'
 $hasher=[Security.Cryptography.SHA256]::Create()
 try {$hash=[BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($xml))).Replace('-','').ToLowerInvariant()}finally{$hasher.Dispose()}
 if($hash -cne $registered.task_xml_sha256 -or [string]$task.State -cne 'Ready' -or $info.LastTaskResult -ne 0 -or [string]$task.Principal.UserId -ine $env:USERNAME -or [string]$task.Principal.LogonType -cne 'S4U' -or [string]$task.Principal.RunLevel -cne 'Limited' -or ([DateTimeOffset]::Parse($wrapper.started_at_utc).UtcDateTime-$info.LastRunTime.ToUniversalTime()).Duration().TotalSeconds -gt 60){throw 'S4U preflight not proved complete'}
}
$null=New-Item -ItemType Directory -Path $registrationRoot
$ps=Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
$tokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'archive_plain_campaign_run.ps1'),'-ConfigPath',$record.Path,'-ConfigSha256',$ConfigSha256,'-ExpectedSourceTip',$ExpectedSourceTip)
if($PreflightOnly){$tokens+='-PreflightOnly'}
$arguments=ConvertTo-WeatherWindowsArgumentString -Tokens $tokens
$null=Write-WeatherPlainNew (Join-Path $registrationRoot 'intent.json') @{task_name=$name;config_sha256=$ConfigSha256;source_git_sha=$ExpectedSourceTip;execute=$ps;arguments=$arguments;working_directory=$source;start_utc=$at.ToString('o');prior_task_absent=$true;mutation='REGISTER_ONCE'} 65536
$action=New-ScheduledTaskAction -Execute $ps -Argument $arguments -WorkingDirectory $source
$trigger=New-ScheduledTaskTrigger -Once -At $at.ToLocalTime()
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes $minutes) -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
$null=Register-ScheduledTask -TaskName $name -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Owner-approved exact archive queue; native proof-gated removal; fixed deadline; no live authority.'
$task=Get-ScheduledTask -TaskName $name -TaskPath '\'
$actions=@($task.Actions);$triggers=@($task.Triggers)
if([string]$task.State -ceq 'Disabled' -or $actions.Count -ne 1 -or $triggers.Count -ne 1 -or [string]$actions[0].Execute -ine $ps -or [string]$actions[0].Arguments -cne $arguments -or [string]$actions[0].WorkingDirectory -ine $source -or [string]$triggers[0].CimClass.CimClassName -cne 'MSFT_TaskTimeTrigger' -or ([DateTimeOffset]::Parse($triggers[0].StartBoundary).UtcDateTime-$at).Duration().TotalSeconds -ge 1 -or -not [bool]$triggers[0].Enabled -or -not [string]::IsNullOrWhiteSpace([string]$triggers[0].Repetition.Interval) -or [Xml.XmlConvert]::ToTimeSpan([string]$task.Settings.ExecutionTimeLimit) -ne (New-TimeSpan -Minutes $minutes) -or [bool]$task.Settings.StartWhenAvailable -or -not [bool]$task.Settings.WakeToRun -or [string]$task.Settings.MultipleInstances -cne 'IgnoreNew' -or -not [bool]$task.Settings.Hidden -or [bool]$task.Settings.DisallowStartIfOnBatteries -or [bool]$task.Settings.StopIfGoingOnBatteries -or [string]$task.Principal.UserId -ine $env:USERNAME -or [string]$task.Principal.LogonType -cne 'S4U' -or [string]$task.Principal.RunLevel -cne 'Limited'){throw 'Exact registration readback failed'}
$xml=Export-ScheduledTask -TaskName $name -TaskPath '\'
$xmlPath=Join-Path $registrationRoot 'registered.xml'
$stream=[IO.File]::Open($xmlPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try {$bytes=[Text.Encoding]::UTF8.GetBytes($xml);$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
$null=Write-WeatherPlainNew (Join-Path $registrationRoot 'result.json') @{status='PASS';task_name=$name;config_sha256=$ConfigSha256;source_git_sha=$ExpectedSourceTip;task_xml_sha256=(Get-FileHash -LiteralPath $xmlPath -Algorithm SHA256).Hash.ToLowerInvariant();verified_at_utc=[DateTime]::UtcNow.ToString('o');start_utc=$at.ToString('o')} 65536
'Registered and verified '+$name+' at '+$at.ToString('o')
