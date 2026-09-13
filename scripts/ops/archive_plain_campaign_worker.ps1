param([Parameter(Mandatory=$true)][string]$ConfigPath,[Parameter(Mandatory=$true)][string]$ConfigSha256,[Parameter(Mandatory=$true)][string]$ExpectedSourceTip,[Parameter(Mandatory=$true)][string]$OutputRoot,[switch]$PreflightOnly)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$source=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
. (Join-Path $PSScriptRoot 'archive_plain_campaign_contract.ps1')
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
Assert-WeatherPlainSource $source $ExpectedSourceTip
$configRecord=Read-WeatherPlainMetadata $ConfigPath $ConfigSha256 65536
$c=Assert-WeatherPlainConfiguration $configRecord.Value
if($c.source_tip -cne $ExpectedSourceTip){throw 'Worker source/config mismatch'}
$root=[IO.Path]::GetFullPath($c.production_root)
$deadline=[DateTimeOffset]::Parse($c.end_utc).UtcDateTime
if($PreflightOnly){$deadline=[DateTime]::UtcNow.AddSeconds(150)}
$ps=Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
$script:phaseSequence=0
$script:events=[Collections.Generic.List[object]]::new()
$script:completed=[Collections.Generic.List[object]]::new()
$script:currentArchive=''
$script:currentPhase='preparing'
$status='FAILED_RETAIN_AND_INSPECT'
$reason=$null
$initial=$null
$final=$null

function Record-Event([string]$Phase,[string]$State){
 $script:currentPhase=$Phase
 $row=[ordered]@{at_utc=[DateTime]::UtcNow.ToString('o');archive_id=$script:currentArchive;phase=$Phase;status=$State}
 $script:events.Add($row)
 $null=Write-WeatherPlainNew (Join-Path $OutputRoot ('event-{0:d4}.json' -f $script:events.Count)) $row 32768
}

function Run-Child([string]$Phase,[string]$Executable,[string[]]$Tokens,[int]$Seconds,[int]$AfterSeconds=0){
 if(([DateTime]::UtcNow.AddSeconds($Seconds+$AfterSeconds+10)) -ge $deadline){throw 'WINDOW_COMPLETE_BEFORE_NEXT_PHASE'}
 $null=Read-WeatherPlainMetadata $ConfigPath $ConfigSha256 65536
 Assert-WeatherPlainSource $source $ExpectedSourceTip
 $script:phaseSequence++
 $job=$null;$child=$null;$teardown=$false;$exitCode=$null
 Record-Event $Phase 'STARTED'
 $end=[DateTime]::UtcNow.AddSeconds($Seconds)
 try {
  $job=New-WeatherKillOnCloseJob
  $child=Start-WeatherProcessInJob -Job $job -FilePath $Executable -WorkingDirectory $root -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $Tokens)
  $null=$child.Handle
  $child.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal
  while(-not $child.HasExited){
   if([DateTime]::UtcNow -ge $end){throw ('Child deadline: '+$Phase)}
   Start-Sleep -Milliseconds 250
   $child.Refresh()
   if(-not $child.HasExited -and ($child.PrivateMemorySize64 -gt 384MB -or $child.WorkingSet64 -gt 384MB)){throw ('Child memory bound: '+$Phase)}
  }
  $child.WaitForExit();$exitCode=$child.ExitCode
  $job.TerminateAndWait(5000);$teardown=$true
  if($null -eq $exitCode -or $exitCode -ne 0){throw ('Child failed: '+$Phase)}
 } finally {
  if($job -and -not $teardown){$job.TerminateAndWait(5000);$teardown=$true}
  if($child){$child.Dispose()};if($job){$job.Dispose()}
  $null=Write-WeatherPlainNew (Join-Path $OutputRoot ('child-{0:d4}.json' -f $script:phaseSequence)) ([ordered]@{phase=$Phase;archive_id=$script:currentArchive;exit_code=$exitCode;teardown_proved=$teardown;completed_at_utc=[DateTime]::UtcNow.ToString('o')}) 32768
 }
 Record-Event $Phase 'PASS'
}

function Remote-Command([string]$Phase,[string[]]$Tokens,[int]$Seconds=30){
 Run-Child $Phase $c.ssh_executable @((Get-WeatherPlainTransport $c -Ssh)+$Tokens) $Seconds
}

function Copy-RemoteReceipt([string]$Remote,[string]$Local){
 if(Test-Path -LiteralPath $Local){throw 'Receipt copy destination is spent'}
 Run-Child 'copy-receipt' $c.scp_executable @((Get-WeatherPlainTransport $c)+@(('-q'),($c.remote_user+'@'+$c.remote_host+':'+$Remote),$Local)) 30
 Read-WeatherPlainMetadata $Local '' 524288
}

function Stage-Metadata($Row){
 $dir=Join-Path $root ('scratch/production_cold_archive/'+$Row.archive_id+'s1/stage')
 $manifest=Read-WeatherPlainMetadata (Join-Path $dir 'manifest.json') '' 524288
 $receipt=Read-WeatherPlainMetadata (Join-Path $dir 'receipt.json') '' 524288
 if($manifest.Value.chunk_id -cne $Row.chunk_id -or $manifest.Value.plan_sha256 -cne $c.plan.sha256 -or $receipt.Value.status -cne 'PASS' -or $receipt.Value.verification.status -cne 'PASS'){throw 'Retained stage evidence differs'}
 [pscustomobject]@{Directory=$dir;Manifest=$manifest;Receipt=$receipt}
}

function Wait-Capture {
 $end=[DateTime]::UtcNow.AddMinutes(12)
 while([DateTime]::UtcNow -lt $end){
  if([DateTime]::UtcNow.AddSeconds(335) -ge $deadline){throw 'WINDOW_COMPLETE_BEFORE_NEXT_PHASE'}
  $ready=$true
  foreach($name in @('loop_status.json','clob_loop_status.json','observation_trigger_status.json')){
   $s=(Read-WeatherPlainMetadata (Join-Path $root ('data/snapshots/'+$name)) '' 1048576).Value
   $age=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse($s.last_heartbeat)).TotalSeconds
   $fresh=$age -ge 0 -and $age -lt 150
   if($name -ceq 'loop_status.json'){
    $clean=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse($s.last_clean_iteration_at)).TotalSeconds
    $planned=(@($s.markets_in_progress).Count -eq 0 -and $s.last_sleep_seconds -gt 180 -and $s.last_sleep_seconds -le 600 -and $age -ge 0 -and $clean -ge 0 -and ($age-$clean) -ge 0 -and ($age-$clean) -le 1 -and $age -le ($s.last_sleep_seconds+10) -and $clean -le 900)
    $fresh=$fresh -or $planned
    if($script:currentPhase -ceq 'reclaim'){
     foreach($queueName in @('pending','inflight')){
      $entries=[IO.Directory]::EnumerateFileSystemEntries((Join-Path $root ('data/snapshots/triggered_snapshot_queue/'+$queueName))).GetEnumerator()
      try {if($entries.MoveNext()){$ready=$false}} finally {$entries.Dispose()}
     }
    }
   }
   if(-not $fresh -or $s.paused -ne $false -or $s.consecutive_errors -ne 0){$ready=$false}
  }
  $m=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
  if($m.AvailableMBytes -lt 4608 -or -not $m.CommitLimit -or ($m.CommittedBytes*100.0/$m.CommitLimit) -ge 66.0){$ready=$false}
  if($ready){return}
  Start-Sleep -Seconds 10
 }
 throw 'No fresh capture/resource opportunity within twelve minutes'
}

function Production-Phase([string]$Phase,$Row,$Request,[string]$Suffix){
 $script:currentPhase=$Phase
 Wait-Capture
 $requestFile=Join-Path $OutputRoot ($Row.archive_id+'-'+$Phase+'-request.json')
 $proof=Write-WeatherPlainNew $requestFile $Request 32768
 $family=if($Phase -ceq 'stage'){'production_cold_archive'}elseif($Phase -ceq 'copy'){'production_cold_archive_copy'}else{'production_cold_archive_reclaim'}
 $out=Join-Path $root ('scratch/'+$family+'/'+$Row.archive_id+$Suffix)
 if(Test-Path -LiteralPath $out){throw 'Native phase attempt is spent'}
 $after=if($Phase -ceq 'reclaim'){300}else{0}
 Run-Child $Phase $ps @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $source 'scripts/ops/production_cold_archive_run.ps1'),'-ProductionRepoRoot',$root,'-RequestPath',$proof.Path,'-RequestSha256',$proof.Sha256,'-OutputRoot',$out,'-ExpectedSourceTip',$ExpectedSourceTip,'-Operation',$Phase) 320 $after
 $result=(Read-WeatherPlainMetadata (Join-Path $out 'wrapper-result.json') '' 524288).Value
 if($result.status -cne 'PASS' -or $result.teardown_proved -ne $true -or $result.source_git_sha -cne $ExpectedSourceTip -or $result.request_sha256 -cne $proof.Sha256){throw 'Native phase did not prove complete success'}
 return $result
}

function Backup-Metadata([string]$Kind,[string[]]$Paths){
 $records=@();[long]$total=0
 foreach($path in $Paths){
  $record=Read-WeatherPlainMetadata $path '' 524288
  $total+=$record.Bytes
  if($total -gt 1048576){throw 'Recovery metadata exceeds one MiB'}
  $records+=@{path=$record.Path;sha256=$record.Sha256;content_base64=[Convert]::ToBase64String($record.Raw)}
 }
 $backupId='p14n'+$script:currentArchive+$Kind
 $bundlePath=Join-Path $OutputRoot ($backupId+'-recovery.json')
 $bundle=Write-WeatherPlainNew $bundlePath ([ordered]@{contains_archive_payload=$false;contains_credential_values=$false;records=$records;source_payload_bytes_read=0;originals_deleted=0})
 $remote=$c.workstation_root+'/scratch/ac-control/'+$c.campaign_id+'/'+$backupId+'-recovery.json'
 Run-Child 'copy-recovery-metadata' $c.scp_executable @((Get-WeatherPlainTransport $c)+@('-q',$bundle.Path,($c.remote_user+'@'+$c.remote_host+':'+$remote))) 30
 $tokens=@('-m','weather.operations.workstation_cold_archive_stage','--backup-recovery','--archive-unattended','--attempt-id',$backupId,'--expected-source-tip',$c.workstation_source_tip,'--bundle-path',$remote,'--bundle-sha256',$bundle.Sha256,'--rclone-executable',$c.rclone_executable,'--rclone-config',$c.drive_config,'--dpapi-secret',$c.drive_secret,'--drive-remote-name',$c.drive_remote_name,'--drive-root-folder-id',$c.drive_root_folder_id)
 $encoded=[Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes(($tokens|ConvertTo-Json -Compress)))
 Remote-Command 'backup-recovery-metadata' @($ps.Replace('\','/'),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',($c.workstation_root+'/scripts/ops/workstation_heavy.ps1'),'-Kind','weather_heavy','-PythonPath',$c.workstation_python,'-ArgumentsBase64',$encoded,'-RepoRoot',$c.workstation_root) 210
 $proof=Copy-RemoteReceipt ($c.workstation_root+'/scratch/ac-backup/'+$backupId+'/receipt.json') (Join-Path $OutputRoot ($backupId+'-verified.json'))
 if($proof.Value.status -cne 'PASS' -or $proof.Value.independent_download_verified -ne $true -or $proof.Value.bundle_sha256 -cne $bundle.Sha256 -or $proof.Value.originals_deleted -ne 0 -or $proof.Value.archive_payload_bytes_read -ne 0 -or $proof.Value.drive.root_folder_id -cne $c.drive_root_folder_id -or $proof.Value.execution_host_id -cne $c.backup_execution_host_id){throw 'Independent recovery metadata backup differs'}
}

try {
 if(-not $PreflightOnly -and ([DateTime]::UtcNow -lt [DateTimeOffset]::Parse($c.start_utc).UtcDateTime -or [DateTime]::UtcNow -gt [DateTimeOffset]::Parse($c.start_utc).UtcDateTime.AddSeconds(50))){throw 'Campaign is outside its one-shot start window'}
 $known=Get-Item -LiteralPath $c.known_hosts -Force
 if($known.PSIsContainer -or $known.Length -gt 65536 -or ($known.Attributes -band [IO.FileAttributes]::ReparsePoint) -or (Get-FileHash -LiteralPath $known.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne $c.known_hosts_sha256){throw 'Pinned known-hosts file differs'}
 foreach($name in @('owner_approval','proposal','selection','plan')){$null=Read-WeatherPlainMetadata $c.$name.path $c.$name.sha256}
 $initial=Read-WeatherPlainMetadata $c.progress_path $c.initial_progress_sha256 524288
 if($initial.Value.status -cne 'READY' -or $initial.Value.sequence -ne 85 -or [long]$initial.Value.reclaimed_allocated_bytes -ne 79105806336){throw 'Initial reclaim checkpoint changed; review before resumption'}
 $oldStage=Stage-Metadata $c.queue[0]
 $existing=Read-WeatherPlainMetadata $c.existing_upload.path $c.existing_upload.sha256 524288
 Assert-WeatherPlainUpload $c $oldStage.Manifest.Value $existing.Value $c.queue[0].archive_id
 if(([DateTimeOffset]::Parse($c.end_utc)-[DateTimeOffset]::Parse($existing.Value.completed_at_utc)).TotalHours -ge 24){throw 'Existing download proof will expire before the campaign ends'}
 $null=Stage-Metadata $c.queue[1]
 foreach($row in $c.queue){
  foreach($family in @('production_cold_archive_reclaim','production_cold_archive_copy')){
   $suffix=if($family -ceq 'production_cold_archive_copy'){'c1'}else{'r1'}
   if($row.start_at -ceq 'reclaim' -and $suffix -ceq 'c1'){continue}
   if(Test-Path -LiteralPath (Join-Path $root ('scratch/'+$family+'/'+$row.archive_id+$suffix))){throw 'Queued native attempt was already used'}
  }
  if($row.start_at -ceq 'stage' -and (Test-Path -LiteralPath (Join-Path $root ('scratch/production_cold_archive/'+$row.archive_id+'s1')))){throw 'Queued stage was already used'}
 }
 $capacity=Read-WeatherPlainMetadata $c.capacity.plan_path $c.capacity.plan_sha256 262144
 Assert-WeatherPlainSource $c.capacity.source_root $c.capacity.source_tip
 if($PreflightOnly){
  Run-Child 'capacity-metadata-preflight' $ps @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $c.capacity.source_root 'scripts/ops/storage_recovery_night_run.ps1'),'-ProductionRepoRoot',$root,'-PlanPath',$c.capacity.plan_path,'-PlanSha256',$c.capacity.plan_sha256,'-ExpectedSourceTip',$c.capacity.source_tip,'-Segment','early','-PreflightOnly') 75
 }
 $capacityPreflight=(Read-WeatherPlainMetadata (Join-Path $c.capacity.result_root 'preflight/wrapper-result.json') '' 65536).Value
 if($capacityPreflight.status -cne 'PASS' -or $capacityPreflight.child_status -cne 'PREFLIGHT_PASS' -or $capacityPreflight.teardown_proved -ne $true -or $capacityPreflight.plan_sha256 -cne $c.capacity.plan_sha256 -or $capacityPreflight.source_git_sha -cne $c.capacity.source_tip -or $capacityPreflight.deleted_files -ne 0){throw 'Conditional capacity lacks matching metadata preflight'}
 Remote-Command 'workstation-connectivity' @('git','-C',$c.workstation_root,'rev-parse','--verify','HEAD') 20
 if($PreflightOnly){$status='PREFLIGHT_PASS'}
 else {
  if([DateTime]::UtcNow -lt [DateTimeOffset]::Parse($c.start_utc).UtcDateTime -or [DateTime]::UtcNow -gt [DateTimeOffset]::Parse($c.start_utc).UtcDateTime.AddSeconds(50)){throw 'Campaign missed its one-shot start window'}
  $free=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($root)).AvailableFreeSpace
  if($free -lt [long]$c.initial_archive_headroom_bytes){
   Run-Child 'conditional-retained-compression' $ps @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $c.capacity.source_root 'scripts/ops/storage_recovery_night_run.ps1'),'-ProductionRepoRoot',$root,'-PlanPath',$c.capacity.plan_path,'-PlanSha256',$c.capacity.plan_sha256,'-ExpectedSourceTip',$c.capacity.source_tip,'-Segment','early') ([int]([Math]::Floor(($deadline-[DateTime]::UtcNow).TotalSeconds)-20))
   $capacityResult=(Read-WeatherPlainMetadata (Join-Path $c.capacity.result_root 'early/wrapper-result.json') '' 2097152).Value
   if($capacityResult.status -cne 'PASS' -or $capacityResult.teardown_proved -ne $true -or $capacityResult.deleted_files -ne 0 -or $capacityResult.plan_sha256 -cne $c.capacity.plan_sha256){throw 'Conditional capacity did not prove safe teardown'}
  }
  if([IO.DriveInfo]::new([IO.Path]::GetPathRoot($root)).AvailableFreeSpace -lt [long]$c.initial_archive_headroom_bytes){throw 'Archive working reserve remains unavailable'}
  Remote-Command 'new-remote-metadata-directory' @($ps.Replace('\','/'),'-NoProfile','-NonInteractive','-Command','New-Item','-ItemType','Directory','-Path',($c.workstation_root+'/scratch/ac-control/'+$c.campaign_id),'-ErrorAction','Stop') 20
  foreach($row in $c.queue){
   if([long](Read-WeatherPlainMetadata $c.progress_path '' 524288).Value.reclaimed_allocated_bytes -ge [long]$c.target_bytes){$status='TARGET_REACHED';break}
   $script:currentArchive=$row.archive_id
   $minimum=if($row.start_at -ceq 'reclaim'){950}elseif($row.start_at -ceq 'copy'){2200}else{2520}
   if([DateTime]::UtcNow.AddSeconds($minimum) -ge $deadline){$status='WINDOW_COMPLETE';break}
   if($row.start_at -ceq 'stage'){
    $request=Get-WeatherPlainBaseRequest $c 'production_cold_archive_request_v0.1' 'stage_only'
    $request.plan_path=$c.plan.path;$request.plan_sha256=$c.plan.sha256;$request.chunk_id=$row.chunk_id
    $null=Production-Phase 'stage' $row $request 's1'
   }
   $stage=Stage-Metadata $row
   if($row.start_at -cne 'reclaim'){
    $request=Get-WeatherPlainBaseRequest $c 'production_cold_archive_copy_request_v0.1' 'copy'
    foreach($key in @('remote_host','remote_user','private_key','known_hosts','known_hosts_sha256','ssh_executable','scp_executable')){$request[$key]=$c.$key}
    $request.plan_path=$c.plan.path;$request.plan_sha256=$c.plan.sha256;$request.chunk_id=$row.chunk_id;$request.direction='to_workstation';$request.archive_id=$row.archive_id;$request.workstation_root=$c.workstation_root
    $request.production_manifest_path=$stage.Manifest.Path;$request.production_manifest_sha256=$stage.Manifest.Sha256;$request.production_receipt_path=$stage.Receipt.Path;$request.production_receipt_sha256=$stage.Receipt.Sha256
    $request.files=@()
    foreach($name in @('archive.tar.gz','manifest.json','receipt.json')){
     $bytes=if($name -ceq 'archive.tar.gz'){$stage.Manifest.Value.archive_bytes}elseif($name -ceq 'manifest.json'){$stage.Manifest.Bytes}else{$stage.Receipt.Bytes}
     $sha=if($name -ceq 'archive.tar.gz'){$stage.Manifest.Value.archive_sha256}elseif($name -ceq 'manifest.json'){$stage.Manifest.Sha256}else{$stage.Receipt.Sha256}
     $request.files+=@{local=(Join-Path $stage.Directory $name);remote=($c.workstation_root+'/scratch/ac-in/'+$row.archive_id+'/'+$name);bytes=$bytes;sha256=$sha}
    }
    $null=Production-Phase 'copy' $row $request 'c1'
    $uploadTokens=@('-m','weather.operations.workstation_cold_archive_stage','--backup-recovery','--plain-file','--archive-unattended','--attempt-id',($row.archive_id+'u1'),'--expected-source-tip',$c.workstation_source_tip,'--bundle-path',($c.workstation_root+'/scratch/ac-in/'+$row.archive_id+'/archive.tar.gz'),'--bundle-sha256',$stage.Manifest.Value.archive_sha256,'--rclone-executable',$c.rclone_executable,'--rclone-config',$c.drive_config,'--dpapi-secret',$c.drive_secret,'--drive-remote-name',$c.drive_remote_name,'--drive-root-folder-id',$c.drive_root_folder_id)
    $encoded=[Convert]::ToBase64String([Text.UTF8Encoding]::new($false).GetBytes(($uploadTokens|ConvertTo-Json -Compress)))
    Remote-Command 'upload-and-independent-download' @($ps.Replace('\','/'),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',($c.workstation_root+'/scripts/ops/workstation_heavy.ps1'),'-Kind','weather_heavy','-PythonPath',$c.workstation_python,'-ArgumentsBase64',$encoded,'-RepoRoot',$c.workstation_root) 930
    $upload=Copy-RemoteReceipt ($c.workstation_root+'/scratch/ac-backup/'+$row.archive_id+'u1/receipt.json') (Join-Path $OutputRoot ($row.archive_id+'-upload-verified.json'))
   } else {$upload=$existing}
   Assert-WeatherPlainUpload $c $stage.Manifest.Value $upload.Value $row.archive_id
   Backup-Metadata 'b1' @($ConfigPath,$stage.Manifest.Path,$stage.Receipt.Path,$upload.Path)
   $request=Get-WeatherPlainBaseRequest $c 'production_cold_archive_plain_reclaim_request_v0.1' 'reclaim'
   $request.attempt_id=$row.archive_id+'r1';$request.archive_id=$row.archive_id;$request.payload_encryption='none'
   foreach($key in @('owner_approval','proposal','selection','plan')){$request[$key]=@{path=$c.$key.path;sha256=$c.$key.sha256}}
   $request.production_manifest=@{path=$stage.Manifest.Path;sha256=$stage.Manifest.Sha256};$request.production_receipt=@{path=$stage.Receipt.Path;sha256=$stage.Receipt.Sha256};$request.plain_upload=@{path=$upload.Path;sha256=$upload.Sha256}
   $result=Production-Phase 'reclaim' $row $request 'r1'
   $progress=Read-WeatherPlainMetadata $c.progress_path '' 524288
   if($progress.Value.status -cne 'READY' -or $progress.Value.attempt_id -cne $request.attempt_id -or $progress.Value.last_receipt_sha256 -cne $result.reclaim_receipt_sha256){throw 'Canonical reclaim counter did not reconcile'}
   $script:completed.Add(@{archive_id=$row.archive_id;reclaimed_bytes=$result.reclaimed_bytes;deleted_files=$result.deleted_files;reclaim_receipt_sha256=$result.reclaim_receipt_sha256;total_original_reclaimed_bytes=$progress.Value.reclaimed_allocated_bytes})
   $receipt=Join-Path (Split-Path -Parent $c.progress_path) ($request.attempt_id+'/receipt.json')
   $catalog=Join-Path $root ('data/cold_archive/catalog/archives/'+$row.archive_id+'/upload.json')
   Backup-Metadata 'b2' @($receipt,$catalog,$c.progress_path)
   Record-Event 'batch' 'VERIFIED_RECLAIM_AND_RECOVERY_BACKUP'
   $status='QUEUE_COMPLETE'
  }
 }
} catch {
 $reason=$_.Exception.Message
 if($reason -ceq 'WINDOW_COMPLETE_BEFORE_NEXT_PHASE'){$status='WINDOW_COMPLETE'}else{$status='FAILED_RETAIN_AND_INSPECT'}
} finally {
 try {$final=(Read-WeatherPlainMetadata $c.progress_path '' 524288).Value} catch {$final=$null}
 $value=[ordered]@{status=$status;reason=$reason;config_sha256=$ConfigSha256;source_git_sha=$ExpectedSourceTip;execution_host_id=$c.execution_host_id;completed_at_utc=[DateTime]::UtcNow.ToString('o');current_archive=$script:currentArchive;current_phase=$script:currentPhase;completed_batches=$script:completed.ToArray();canonical_progress=$final;preflight_only=[bool]$PreflightOnly;source_payload_bytes_read_by_controller=0;source_files_deleted_by_controller=0}
 $null=Write-WeatherPlainNew (Join-Path $OutputRoot 'result.json') $value
}
if($status -ceq 'FAILED_RETAIN_AND_INSPECT'){exit 1}
exit 0
