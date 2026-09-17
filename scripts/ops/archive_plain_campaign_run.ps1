# Own the complete local campaign tree; every archive payload phase uses its native lease wrapper.
param(
 [Parameter(Mandatory=$true)][string]$ConfigPath,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{64}$')][string]$ConfigSha256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedSourceTip,
 [switch]$PreflightOnly
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$source=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tip=[string](git -C $source rev-parse HEAD)
$dirty=@(git -C $source status --porcelain)
if($LASTEXITCODE -ne 0 -or $tip.Trim() -cne $ExpectedSourceTip -or $dirty.Count -ne 0){throw 'Campaign requires exact clean source'}
. (Join-Path $PSScriptRoot 'archive_plain_campaign_contract.ps1')
. (Join-Path $PSScriptRoot 'storage_recovery_night_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$configRecord=Read-WeatherPlainMetadata $ConfigPath $ConfigSha256 65536
$c=Assert-WeatherPlainConfiguration $configRecord.Value
$root=[IO.Path]::GetFullPath($c.production_root)
Assert-WeatherNightDirectory $root
Assert-WeatherNightDirectory $source
Assert-WeatherNightDirectory (Split-Path -Parent $configRecord.Path)
$hostIdentity=Get-WeatherExecutionHostId
$assignment=Get-WeatherExecutionHostAssignment -RepoRoot $source
if($hostIdentity -cne $assignment.dedicated_capture_execution_host_id -or $hostIdentity -cne $c.execution_host_id -or $assignment.active_portable_execution_host_id -cne $c.backup_execution_host_id -or $c.source_tip -cne $ExpectedSourceTip){throw 'Campaign host/source binding differs'}
$start=[DateTimeOffset]::Parse($c.start_utc).UtcDateTime
$deadline=[DateTimeOffset]::Parse($c.end_utc).UtcDateTime
$name='run'
if($PreflightOnly){
 if($c.campaign_id.StartsWith('plain-20260913-',[StringComparison]::Ordinal)){
  if(-not(Test-WeatherPlainStartWindow $c)){throw 'Immediate preflight is outside the approved window'}
 }elseif([DateTime]::UtcNow -ge $start){throw 'Preflight must precede approved window'}
 $deadline=[DateTime]::UtcNow.AddSeconds(180);$name='preflight'
}elseif(-not(Test-WeatherPlainStartWindow $c)){throw 'Campaign missed its approved launch window'}
$campaignRoot=Join-Path $root ('scratch/archive_plain_campaigns/'+$c.campaign_id)
Assert-WeatherNightDirectory $campaignRoot
$outputRoot=Join-Path $campaignRoot $name
if(Test-Path -LiteralPath $outputRoot){throw 'Spent campaign namespace'}
if(-not $PreflightOnly){
 $pre=(Read-WeatherPlainMetadata (Join-Path $campaignRoot 'preflight/wrapper-result.json') '' 65536).Value
 if($pre.status -cne 'PASS' -or $pre.child_status -cne 'PREFLIGHT_PASS' -or $pre.teardown_proved -ne $true -or $pre.source_git_sha -cne $ExpectedSourceTip -or $pre.config_sha256 -cne $ConfigSha256 -or $pre.execution_host_id -cne $hostIdentity){throw 'Campaign lacks matching preflight'}
}
$job=$null;$process=$null;$teardown=$false;$exitCode=1
$receipt=[ordered]@{status='FAILED';source_git_sha=$ExpectedSourceTip;config_sha256=$ConfigSha256;execution_host_id=$hostIdentity;preflight_only=[bool]$PreflightOnly;started_at_utc=[DateTime]::UtcNow.ToString('o');deadline_utc=$deadline.ToString('o');teardown_proved=$false;hard_stop=$false;verified_new_original_reclaimed_bytes=$null;verified_new_original_deleted_files=$null;cleanup_eligible=$false}
try {
 if(-not(Test-Path -LiteralPath $campaignRoot)){$null=New-Item -ItemType Directory -Path $campaignRoot}
 $null=New-Item -ItemType Directory -Path $outputRoot
 $tokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $source 'scripts/ops/archive_plain_campaign_worker.ps1'),'-ConfigPath',$configRecord.Path,'-ConfigSha256',$ConfigSha256,'-ExpectedSourceTip',$ExpectedSourceTip,'-OutputRoot',$outputRoot)
 if($PreflightOnly){$tokens+='-PreflightOnly'}
 $job=New-WeatherKillOnCloseJob
 $process=Start-WeatherProcessInJob -Job $job -FilePath (Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe') -WorkingDirectory $root -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens)
 $null=$process.Handle
 $process.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal
 while(-not $process.HasExited){
  if([DateTime]::UtcNow -ge $deadline -or $process.PrivateMemorySize64 -gt 256MB -or $process.WorkingSet64 -gt 256MB){$receipt.hard_stop=$true;throw 'Campaign exceeded absolute deadline or controller memory bound'}
  Start-Sleep -Milliseconds 250
  $process.Refresh()
 }
 $process.WaitForExit();$exitCode=$process.ExitCode
 $job.TerminateAndWait(5000);$teardown=$true
 if($null -eq $exitCode -or $exitCode -ne 0){throw 'Campaign worker failed; retain and inspect phase receipts'}
 $record=Read-WeatherPlainMetadata (Join-Path $outputRoot 'result.json') '' 2097152
 $result=$record.Value
 $safe=@('WINDOW_COMPLETE','QUEUE_COMPLETE','TARGET_REACHED')
 if($PreflightOnly){$safe=@('PREFLIGHT_PASS')}
 if($result.status -cnotin $safe -or $result.config_sha256 -cne $ConfigSha256 -or $result.source_git_sha -cne $ExpectedSourceTip -or $result.execution_host_id -cne $hostIdentity -or $result.preflight_only -ne [bool]$PreflightOnly){throw 'Campaign result binding differs'}
 Assert-WeatherPlainSource $source $ExpectedSourceTip
 $null=Read-WeatherPlainMetadata $ConfigPath $ConfigSha256 65536
 $receipt.child_result_sha256=$record.Sha256;$receipt.child_status=$result.status
 $receipt.status='PASS';$exitCode=0
} catch {$receipt.error=$_.Exception.Message;$exitCode=1}
finally {
 try {
  if($job -and -not $teardown){$job.TerminateAndWait(5000);$teardown=$true}
  if(-not $job){$teardown=$true}
 } finally {
  $receipt.teardown_proved=$teardown
  if(-not $teardown){$receipt.status='TEARDOWN_UNPROVED';$exitCode=1}
  if($process){$process.Dispose()};if($job){$job.Dispose()}
  try {
   $progress=Read-WeatherPlainMetadata $c.progress_path '' 524288
   $receipt.canonical_progress_sha256=$progress.Sha256
   $receipt.canonical_progress_status=$progress.Value.status
   $receipt.canonical_total_original_reclaimed_bytes=$progress.Value.reclaimed_allocated_bytes
   $baselineBytes=79105806336;$baselineFiles=1679
   if($c.campaign_id -cin @('plain-20260916-cap150b','plain-20260917-cap150')){$baselineBytes=0;$baselineFiles=0}
   if($progress.Value.status -ceq 'READY' -and $progress.Value.owner_approval_sha256 -ceq $c.owner_approval.sha256 -and [long]$progress.Value.reclaimed_allocated_bytes -ge $baselineBytes -and [long]$progress.Value.deleted_files -ge $baselineFiles){
    $receipt.verified_new_original_reclaimed_bytes=[long]$progress.Value.reclaimed_allocated_bytes-$baselineBytes
    $receipt.verified_new_original_deleted_files=[long]$progress.Value.deleted_files-$baselineFiles
   }
  }catch {
   if($c.campaign_id -cin @('plain-20260916-cap150b','plain-20260917-cap150') -and $PreflightOnly -and -not(Test-Path -LiteralPath $c.progress_path)){
    $receipt.verified_new_original_reclaimed_bytes=0;$receipt.verified_new_original_deleted_files=0
   }else{$receipt.progress_error=$_.Exception.Message}
  }
  $receipt.completed_at_utc=[DateTime]::UtcNow.ToString('o')
  if(Test-Path -LiteralPath $outputRoot -PathType Container){$null=Write-WeatherPlainNew (Join-Path $outputRoot 'wrapper-result.json') $receipt 65536}
 }
}
$receipt|ConvertTo-Json -Depth 8 -Compress
exit $exitCode


