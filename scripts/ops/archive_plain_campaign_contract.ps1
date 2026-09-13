# Bounded metadata and phase contracts for the owner-approved plain archive lane.
Set-StrictMode -Version 2
$ErrorActionPreference='Stop'

function Read-WeatherPlainMetadata {
 param([string]$Path,[string]$Sha256='', [long]$Maximum=2097152)
 $info=Get-Item -LiteralPath $Path -Force
 if($info.PSIsContainer -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $info.Length -gt $Maximum){throw 'Invalid bounded metadata file'}
 $stream=[IO.File]::Open($info.FullName,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
 try {
  if($stream.Length -gt $Maximum){throw 'Metadata grew beyond its bound'}
  $memory=[IO.MemoryStream]::new()
  try {$stream.CopyTo($memory);$raw=$memory.ToArray()} finally {$memory.Dispose()}
 } finally {$stream.Dispose()}
 $algorithm=[Security.Cryptography.SHA256]::Create()
 try {$digest=[BitConverter]::ToString($algorithm.ComputeHash($raw)).Replace('-','').ToLowerInvariant()} finally {$algorithm.Dispose()}
 if($Sha256 -and $Sha256 -cne $digest){throw ('Metadata hash differs: '+$info.Name)}
 $value=[Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json
 [pscustomobject]@{Value=$value;Sha256=$digest;Bytes=$raw.Length;Raw=$raw;Path=$info.FullName}
}

function Write-WeatherPlainNew {
 param([string]$Path,$Value,[long]$Maximum=2097152)
 $raw=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 80 -Compress)+"`n")
 if($raw.Length -gt $Maximum){throw 'New metadata exceeds bound'}
 $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try {$stream.Write($raw,0,$raw.Length);$stream.Flush($true)} finally {$stream.Dispose()}
 Read-WeatherPlainMetadata $Path '' $Maximum
}

function Assert-WeatherPlainSource {
 param([string]$Root,[string]$Tip)
 $actual=[string](git -C $Root rev-parse HEAD)
 if($LASTEXITCODE -ne 0 -or $actual.Trim() -cne $Tip){throw 'Campaign source tip differs'}
 $dirty=@(git -C $Root status --porcelain)
 if($LASTEXITCODE -ne 0 -or $dirty.Count -ne 0){throw 'Campaign source is dirty'}
}

function Assert-WeatherPlainLiteralPath {
 param([string]$Path)
 if($Path -cnotmatch '^[A-Za-z]:[\\/][A-Za-z0-9_:/\\.-]+$' -or $Path -match '(^|[\\/])\.\.([\\/]|$)') {throw 'Campaign path must be absolute and literal'}
 [IO.Path]::GetFullPath($Path)
}

function Assert-WeatherPlainConfiguration {
 param($Config)
 if($Config.schema_version -cne 'plain_archive_campaign_config_v1' -or $Config.campaign_id -cnotmatch '^plain-20260914-[a-z0-9]{1,12}$'){throw 'Invalid campaign identity'}
 if($Config.source_tip -cnotmatch '^[a-f0-9]{40}$' -or $Config.workstation_source_tip -cnotmatch '^[a-f0-9]{40}$'){throw 'Invalid source binding'}
 foreach($key in @('execution_host_id','backup_execution_host_id','known_hosts_sha256','initial_progress_sha256')){
  if($Config.$key -cnotmatch '^[a-f0-9]{64}$'){throw ('Invalid digest: '+$key)}
 }
 foreach($key in @('production_root','workstation_root','progress_path','private_key','known_hosts','ssh_executable','scp_executable','workstation_python','rclone_executable','drive_config','drive_secret')){
  $null=Assert-WeatherPlainLiteralPath $Config.$key
 }
 if([IO.Path]::GetFullPath($Config.production_root) -ieq [IO.Path]::GetFullPath($Config.workstation_root) -or $Config.execution_host_id -ceq $Config.backup_execution_host_id){throw 'Archive host roles overlap'}
 if($Config.remote_host -cnotmatch '^192\.168\.1\.[0-9]{1,3}$' -or $Config.remote_user -cnotmatch '^[A-Za-z][A-Za-z0-9_-]{0,31}$' -or $Config.drive_remote_name -cnotmatch '^[A-Za-z][A-Za-z0-9_]{0,63}$' -or $Config.drive_root_folder_id -cnotmatch '^[A-Za-z0-9_-]{10,128}$'){throw 'Invalid fixed transport identity'}
 if($Config.start_utc -cne '2026-09-14T04:30:00Z' -or $Config.end_utc -cne '2026-09-14T08:42:00Z' -or $Config.expires_at_utc -cne $Config.end_utc){throw 'Campaign exceeds approved date/window'}
 $approved=[DateTimeOffset]::Parse($Config.approved_at_utc)
 if($approved -gt [DateTimeOffset]::UtcNow -or $approved -ge [DateTimeOffset]::Parse($Config.start_utc) -or ([DateTimeOffset]::Parse($Config.end_utc)-$approved).TotalHours -gt 72){throw 'Campaign approval is future-dated or overlong'}
 if(-not $Config.approved_by -or $Config.approved_by.Length -gt 128 -or [long]$Config.target_bytes -ne 100000000000 -or [long]$Config.initial_archive_headroom_bytes -ne 23622320128){throw 'Campaign target or approval differs'}
 foreach($key in @('owner_approval','proposal','selection','plan')){
  if($Config.$key.sha256 -cnotmatch '^[a-f0-9]{64}$'){throw ('Invalid proof binding: '+$key)}
  $null=Assert-WeatherPlainLiteralPath $Config.$key.path
 }
 if($Config.proposal.sha256 -cne 'd47eec8ff7fbd500c720a273339729cb9f8f75eb84be615082d9d39e2b22b927' -or $Config.owner_approval.sha256 -cne '2878ff1c2e673a539a74f1939a15682c9f624c7f54184ddee63dfb522fc34d7e' -or $Config.plan.sha256 -cne '2faae41470c42508a8639e98ec17ace7ecebc0b8715c09eaa92d33c0845251d3' -or $Config.selection.sha256 -cne '566e0fd15a0095c131068cc4ef3cf09e715ca570b1205286e6e6fd6927f607c9'){throw 'Campaign is outside the approved initial primary queue'}
 $expected=@('00085','00090','00086','00101','00127','00125','00104','00093','00113','00116','00129','00083','00094','00091','00050','00105','00117','00114','00102','00071')
 if(@($Config.queue).Count -ne $expected.Count){throw 'Campaign queue cardinality differs'}
 for($i=0;$i -lt $expected.Count;$i++){
  $row=$Config.queue[$i]
  $phase=if($i -eq 0){'reclaim'}elseif($i -eq 1){'copy'}else{'stage'}
  if($row.archive_id -cne ('p11k'+$expected[$i]) -or $row.chunk_id -cne ('chunk-'+$expected[$i]) -or $row.start_at -cne $phase){throw 'Campaign queue or resume point differs'}
 }
 $null=Assert-WeatherPlainLiteralPath $Config.existing_upload.path
 if($Config.existing_upload.sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Existing upload binding missing'}
 foreach($key in @('source_root','plan_path','result_root')){$null=Assert-WeatherPlainLiteralPath $Config.capacity.$key}
 if($Config.capacity.source_tip -cnotmatch '^[a-f0-9]{40}$' -or $Config.capacity.plan_sha256 -cnotmatch '^[a-f0-9]{64}$'){throw 'Capacity fallback is unbound'}
 return $Config
}

function Get-WeatherPlainBaseRequest {
 param($Config,[string]$Schema,[string]$Operation)
 [ordered]@{schema_version=$Schema;production_repo_root=$Config.production_root;execution_host_id=$Config.execution_host_id;operation=$Operation;approved_by=$Config.approved_by;approved_at_utc=$Config.approved_at_utc;expires_at_utc=$Config.expires_at_utc;source_git_sha=$Config.source_tip}
}

function Get-WeatherPlainTransport {
 param($Config,[switch]$Ssh)
 $tokens=@('-F','none','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','PermitLocalCommand=no','-o','ProxyCommand=none','-o','ProxyJump=none','-o','ClearAllForwardings=yes','-o','IdentitiesOnly=yes','-o','ConnectTimeout=10','-i',$Config.private_key,'-o',('UserKnownHostsFile='+$Config.known_hosts))
 if($Ssh){$tokens+=@('-T','-n','-o',('HostName='+$Config.remote_host),'-l',$Config.remote_user,'weather-workstation')}
 return $tokens
}

function Assert-WeatherPlainUpload {
 param($Config,$Stage,$Upload,[string]$ArchiveId)
 if($Upload.status -cne 'PASS' -or $Upload.payload_encryption -cne 'none' -or $Upload.independent_download_verified -ne $true -or $Upload.originals_deleted -ne 0 -or $Upload.execution_host_id -cne $Config.backup_execution_host_id -or $Upload.bundle_sha256 -cne $Stage.archive_sha256 -or [long]$Upload.bytes -ne [long]$Stage.archive_bytes -or $Upload.drive.root_folder_id -cne $Config.drive_root_folder_id -or $Upload.attempt_id -cnotmatch ('^'+[regex]::Escape($ArchiveId)+'u[1-9][0-9]*$')){throw 'Independent upload proof differs'}
 $age=([DateTimeOffset]::UtcNow-[DateTimeOffset]::Parse($Upload.completed_at_utc)).TotalHours
 if($age -lt 0 -or $age -ge 24){throw 'Independent download proof is stale or future-dated'}
}
