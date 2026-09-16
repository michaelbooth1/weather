# Metadata-only preparation of the owner's exact September 16 capacity attempt.
param(
 [Parameter(Mandatory=$true)][string]$ProductionRepoRoot,
 [Parameter(Mandatory=$true)][ValidatePattern('^[a-f0-9]{40}$')][string]$ExpectedSourceTip,
 [ValidatePattern('^a[1-9][0-9]?$')][string]$AttemptLabel='a1'
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$source=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'archive_plain_campaign_contract.ps1')
. (Join-Path $PSScriptRoot 'storage_recovery_night_contract.ps1')
. (Join-Path $PSScriptRoot 'workload_admission.ps1')
Assert-WeatherPlainSource $source $ExpectedSourceTip
Assert-WeatherNightDirectory $ProductionRepoRoot
$hostId=Get-WeatherExecutionHostId
$assignment=Get-WeatherExecutionHostAssignment -RepoRoot $source
if($hostId -cne $assignment.dedicated_capture_execution_host_id -or $hostId -cne '6a085bc0e2017a1a619eead39f9daa9ffe0822b9add353d94cf2c06acb8889a7'){throw 'Preparation requires the approved capture installation'}
if([DateTime]::UtcNow -ge [DateTime]'2026-09-16T04:25:00Z'){throw 'Preparation is too late for reviewed preflight'}
$handoffs=Join-Path $ProductionRepoRoot 'scratch/handoffs'
$owner=Read-WeatherPlainMetadata (Join-Path $handoffs 'capacity-150gb-20260915-owner-approval-a1.json') '2eb7309a03b9b5383f1bd848a43b9a268f6ffd390c236b3a27361f58d445cef5' 16384
$selection=Read-WeatherPlainMetadata (Join-Path $handoffs 'local-retained-capacity-selection-20260914-a1.json') '721dd300298d00397906e8ebc703150d519aa30077a2d0a9b6faa636f7ae9eed' 8388608
$oldConfig=Read-WeatherPlainMetadata (Join-Path $handoffs 'archive-next50-config-20260914-a2.json') '189500ddf3877d69d50aeaf8b8fc13b7b74a996130e2839b92dc2ed22305628c' 65536
$c=$oldConfig.Value
if($owner.Value.post_denial_approval -ne $true -or $owner.Value.temporary_disk_exception_authorized -ne $true -or $c.selection.sha256 -cne $owner.Value.archive_selection_sha256 -or $c.drive_root_folder_id -cne $owner.Value.destination_folder_id){throw 'Current owner scope differs'}
foreach($key in @('owner_approval','proposal','selection','plan')){$null=Read-WeatherPlainMetadata $c.$key.path $c.$key.sha256 8388608}
if(@($selection.Value.groups).Count -ne 62 -or $selection.Value.excluded_archive_paths -ne 1066){throw 'Retained compression selection differs'}
$groups=[Collections.Generic.List[object]]::new()
$total=0
foreach($group in @($selection.Value.groups | Select-Object -Skip 7)){
 $folders=[Collections.Generic.List[string]]::new()
 $dates=[Collections.Generic.List[string]]::new()
 foreach($row in $group.files){
  $total++
  $parts=([string]$row.path).Split('/')
  if($parts.Count -ne 3 -or $parts[0] -cne 'snapshots' -or $parts[1] -cnotmatch '-on-([a-z]+)-([0-9]{1,2})-([0-9]{4})$'){throw 'Selected cold path differs'}
  $date=[DateTime]::ParseExact(($Matches[1]+'-'+$Matches[2]+'-'+$Matches[3]),'MMMM-d-yyyy',[Globalization.CultureInfo]::InvariantCulture).ToString('yyyy-MM-dd')
  if(-not $dates.Contains($date)){$dates.Add($date)}
  $folder=$parts[0]+'/'+$parts[1]
  if(-not $folders.Contains($folder)){$folders.Add($folder)}
 }
 if($dates.Count -ne 1){throw 'A selected group is not one exact cold date'}
 $groups.Add(@{name=$dates[0];folders=$folders.ToArray()})
}
if($total -ne 8754 -or $groups.Count -ne 55){throw 'Untouched compression selection accounting differs'}
$package=Join-Path $handoffs ('capacity-150gb-20260916-'+$AttemptLabel)
if(Test-Path -LiteralPath $package){throw 'Spent preparation namespace'}
$baselinePrefix=Join-Path $handoffs ('capacity-20260916-cap150b-'+$AttemptLabel)
foreach($suffix in @('-baseline-files.json','-baseline.json')){if(Test-Path -LiteralPath ($baselinePrefix+$suffix)){throw 'Spent baseline namespace'}}
if(Test-Path -LiteralPath $c.progress_path){throw 'The approved archive progress ledger exists; reconcile before preparation'}
$activeRecovery=@(Get-CimInstance Win32_Process | Where-Object {
 $_.Name -in @('python.exe','powershell.exe','pwsh.exe') -and $_.ProcessId -ne $PID -and
 $_.CommandLine -match '(cold_snapshot_compression|storage_recovery_inventory|storage_recovery_night)'
})
if($activeRecovery.Count){throw 'A storage recovery process is active; no baseline can be asserted'}
$null=New-Item -ItemType Directory -Path $package
$ledger=Write-WeatherPlainNew ($baselinePrefix+'-baseline-files.json') @{
 production_repo_root=$ProductionRepoRoot;files=@();verified_new_reclaimed_bytes=0;verified_file_count=0;deleted_files=0;cleanup_eligible=$false
 scope='Zero credit for this new attempt. Only the bound untouched groups 7 onward are eligible; previous seven groups are excluded.'
 selection_sha256=$selection.Sha256
}
$baseline=Write-WeatherPlainNew ($baselinePrefix+'-baseline.json') @{
 production_repo_root=$ProductionRepoRoot;verified_new_reclaimed_bytes=0;verified_file_count=0;verified_file_ledger_sha256=$ledger.Sha256
 unmatched_preimages=0;unverified_compressed_files=0;active_recovery_processes=0;source_files_deleted=0
 scope='Selected untouched groups only; no global reconciliation or prior savings credit is asserted.'
}
$plan=@{
 schema_version='storage_recovery_night_plan_v1';plan_id='capacity-20260916-cap150b';night_date='2026-09-16'
 approved_by='Michael; September 15 exact capacity-recovery approval';approved_at_utc='2026-09-15T23:17:20.425091Z'
 expires_at_utc='2026-09-16T13:00:00Z';production_repo_root=$ProductionRepoRoot;execution_host_id=$hostId
 source_root=$source;source_git_sha=$ExpectedSourceTip;baseline_receipt=$baseline.Path;baseline_receipt_sha256=$baseline.Sha256
 baseline_ledger=$ledger.Path;baseline_ledger_sha256=$ledger.Sha256;groups=$groups.ToArray()
 target_new_reclaimed_bytes=1;target_free_disk_bytes=150000000000;max_new_files=8754;max_wrapper_attempts=448
 max_resource_recoveries=24;max_logical_input_bytes=214748364800;receipt_budget_bytes=134217728;allow_resource_recovery=$true
}
$planRecord=Write-WeatherPlainNew (Join-Path $package 'compression-plan.json') $plan 262144
$exception=Write-WeatherPlainNew (Join-Path $package 'disk-exception.json') @{
 schema='capacity_disk_exception_v1';owner_approval=@{path=$owner.Path;sha256=$owner.Sha256}
 source_git_sha=$ExpectedSourceTip;execution_host_id=$hostId;production_root=$ProductionRepoRoot
 plan_sha256=$c.plan.sha256;selection_sha256=$c.selection.sha256;expires_at_utc='2026-09-16T13:00:00Z'
 hard_reserve_bytes=26843545600;output_cap_bytes=2147483648;capture_bytes_per_second=1048576
} 16384
$c.campaign_id='plain-20260916-cap150b';$c.source_tip=$ExpectedSourceTip;$c.created_at_utc=[DateTime]::UtcNow.ToString('o')
$c.approved_by='Michael; exact post-denial approval on September 15';$c.approved_at_utc='2026-09-15T23:17:20.425091Z'
$c.start_utc='2026-09-16T04:30:00Z';$c.end_utc='2026-09-16T08:42:00Z';$c.expires_at_utc=$c.end_utc
$c.target_bytes=150000000000
$c|Add-Member -NotePropertyName initial_archive_headroom_bytes -NotePropertyValue 32212254720 -Force
$c|Add-Member -NotePropertyName initial_progress_sha256 -NotePropertyValue ('0'*64) -Force
$c|Add-Member -NotePropertyName current_owner_approval -NotePropertyValue @{path=$owner.Path;sha256=$owner.Sha256} -Force
$c|Add-Member -NotePropertyName disk_exception -NotePropertyValue @{path=$exception.Path;sha256=$exception.Sha256} -Force
$c|Add-Member -NotePropertyName capacity -NotePropertyValue @{
 source_root=$source;source_tip=$ExpectedSourceTip;plan_path=$planRecord.Path;plan_sha256=$planRecord.Sha256
 result_root=(Join-Path $ProductionRepoRoot 'scratch/storage_recovery_nights/capacity-20260916-cap150b')
} -Force
foreach($row in $c.queue){$row.archive_id='p16n'+$row.chunk_id.Substring(6);$row.start_at='stage'}
# Preserve only configuration fields consumed by the registered controller.
foreach($obsolete in @('owner_instruction','operating_windows','windows','supersedes_unused_configuration','minimum_free_disk_bytes','native_archive_reserve_bytes','initial_free_disk_bytes','initial_progress_status')){$c.PSObject.Properties.Remove($obsolete)}
$null=Assert-WeatherPlainConfiguration $c
$configRecord=Write-WeatherPlainNew (Join-Path $package 'archive-config.json') $c 65536
$manifest=Write-WeatherPlainNew (Join-Path $package 'prepared.json') @{
 status='PREPARED_NOT_ARMED';source_git_sha=$ExpectedSourceTip;execution_host_id=$hostId
 archive_config=@{path=$configRecord.Path;sha256=$configRecord.Sha256}
 compression_plan=@{path=$planRecord.Path;sha256=$planRecord.Sha256}
 disk_exception=@{path=$exception.Path;sha256=$exception.Sha256}
 owner_approval=@{path=$owner.Path;sha256=$owner.Sha256};created_at_utc=[DateTime]::UtcNow.ToString('o')
 payload_bytes_read=0;source_files_changed=0;originals_deleted=0;scheduler_changed=$false
}
$manifest.Value|ConvertTo-Json -Depth 8
