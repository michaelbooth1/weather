# Bounded workstation metadata RPC and contained archive-phase dispatch.
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$RepoRoot,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
 [Parameter(Mandatory=$true)][ValidateSet('setup','read','write','run')][string]$Mode,
 [Parameter(Mandatory=$true)][string]$RequestBase64
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$root=[IO.Path]::GetFullPath($RepoRoot)
$own=(Get-Item -LiteralPath (Join-Path $PSScriptRoot '../..')).FullName
if($root -ine $own -or -not [IO.Path]::IsPathRooted($RepoRoot)){throw 'RPC must own this checkout'}
if((git -C $root rev-parse HEAD) -cne $ExpectedSourceTip -or @(git -C $root status --porcelain).Count -ne 0){throw 'RPC source is not exact and clean'}
if($RequestBase64.Length -gt 4000000 -or $RequestBase64 -cnotmatch '^[A-Za-z0-9+/]*={0,2}$'){throw 'RPC input bound'}
$raw=[Convert]::FromBase64String($RequestBase64)
if($raw.Length -gt 2097152){throw 'RPC metadata bound'}
$request=[Text.UTF8Encoding]::new($false,$true).GetString($raw)|ConvertFrom-Json
function Hash-Bytes([byte[]]$Bytes){
 $sha=[Security.Cryptography.SHA256]::Create()
 try{return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant()}
 finally{$sha.Dispose()}
}
function Scratch-Path([string]$Relative,[switch]$Missing){
 if($Relative -cnotmatch '^scratch/(?:ac-[a-z-]+|production_cold_archive_[a-z_]+)(?:/[A-Za-z0-9_./-]+)?/?$' -or $Relative.Contains('..')){throw 'RPC path outside archive scratch'}
 $path=[IO.Path]::GetFullPath((Join-Path $root $Relative))
 if(-not $path.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'RPC path escaped'}
 $cursor=if(Test-Path -LiteralPath $path){$path}else{Split-Path -Parent $path}
 while($cursor -and $cursor.Length -ge $root.Length){
  if(Test-Path -LiteralPath $cursor){if((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'RPC redirect refused'}}
  elseif(-not $Missing){throw 'RPC parent absent'}
  $cursor=Split-Path -Parent $cursor
 }
 return $path
}
function New-Record([string]$Path,$Value){
 $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($Value|ConvertTo-Json -Depth 40 -Compress)+[char]10)
 if($bytes.Length -gt 2097152){throw 'RPC output bound'}
 $f=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
 try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
 return @{path=$Path;sha256=(Hash-Bytes $bytes)}
}
$result=$null
switch($Mode){
 'setup' {
  if($request.campaign_id -cnotmatch '^[a-z0-9][a-z0-9-]{0,63}$'){throw 'invalid campaign ID'}
  foreach($relative in @('scratch/ac-in','scratch/ac-enc','scratch/ac-rest',
    'scratch/production_cold_archive_transport','scratch/production_cold_archive_ciphertext',
    ('scratch/ac-control/'+$request.campaign_id),('scratch/production_cold_archive_recovery/'+$request.campaign_id+'/data'))){
   $path=Scratch-Path ($relative+'/') -Missing
   [IO.Directory]::CreateDirectory($path)|Out-Null
  }
  $result=@{status='PASS';source_tip=$ExpectedSourceTip}
 }
 'read' {
  $paths=@($request.paths)
  if($paths.Count -lt 1 -or $paths.Count -gt 24){throw 'RPC read count'}
  $rows=@();$total=0
  foreach($relative in $paths){
   if($relative -cnotmatch '[.](json|jsonl|md)$'){throw 'RPC only reads recovery metadata'}
   $path=Scratch-Path $relative
   if(-not (Test-Path -LiteralPath $path)){$rows+=@{path=$relative;exists=$false};continue}
   if((Get-Item -LiteralPath $path).Length -gt 2097152){throw 'RPC file bound'}
   $bytes=[IO.File]::ReadAllBytes($path);$total+=$bytes.Length
   if($total -gt 2097152){throw 'RPC aggregate metadata bound'}
   $rows+=@{path=$relative;exists=$true;sha256=(Hash-Bytes $bytes);base64=[Convert]::ToBase64String($bytes)}
  }
  $result=@{status='PASS';files=$rows}
 }
 'write' {
  $relative=[string]$request.path
  if($relative -cnotmatch '^scratch/(ac-in|ac-control)/[A-Za-z0-9_-]+/[A-Za-z0-9._-]+[.](json|md)$'){throw 'RPC write only accepts archive metadata'}
  $path=Scratch-Path $relative
  $bytes=[Convert]::FromBase64String([string]$request.base64)
  if($bytes.Length -gt 2097152 -or (Hash-Bytes $bytes) -cne $request.sha256){throw 'RPC write hash or bound'}
  if(Test-Path -LiteralPath $path){
   if((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $request.sha256){throw 'RPC existing metadata differs'}
  }else{
   $f=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
   try{$f.Write($bytes,0,$bytes.Length);$f.Flush($true)}finally{$f.Dispose()}
  }
  $result=@{status='PASS';path=$relative;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
 }
 'run' {
  $tokens=@($request.arguments)
  if($tokens.Count -lt 4 -or $tokens.Count -gt 128 -or $tokens[0] -cne '-m' -or
    $tokens[1] -cnotin @('weather.operations.workstation_cold_archive_stage','weather.operations.workstation_cold_archive_restore') -or
    @($tokens|Where-Object {$_ -isnot [string] -or $_.Length -gt 4096 -or $_ -match '[\x00\r\n]'}).Count -ne 0 -or
    @($tokens|Where-Object {$_ -ceq '--archive-unattended'}).Count -ne 1){throw 'RPC accepts only canonical archive entry points'}
  $seconds=[int]$request.seconds
  if($seconds -lt 30 -or $seconds -gt 960){throw 'RPC phase deadline bound'}
  $receipt=Scratch-Path ([string]$request.receipt)
  if($request.receipt -cnotmatch '^scratch/ac-control/[a-z0-9-]+/[a-z0-9-]+[.]json$' -or (Test-Path -LiteralPath $receipt)){throw 'RPC run namespace spent'}
  $requestHash=Hash-Bytes $raw
  $claim=New-Record ($receipt+'.claim.json') @{status='STARTED';request_sha256=$requestHash;source_tip=$ExpectedSourceTip;started_at_utc=[DateTime]::UtcNow.ToString('o')}
  . (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
  $job=$null;$child=$null;$clear=$false;$code=1;$errorKind=$null;$started=[DateTime]::UtcNow
  try{
   $job=New-WeatherKillOnCloseJob
   $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $tokens -Compress)))
   $python=[string]$request.python
   if(-not [IO.Path]::IsPathRooted($python) -or -not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'RPC Python path invalid'}
   $ps=Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
   $childTokens=@('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'workstation_heavy.ps1'),
     '-Kind','weather_heavy','-PythonPath',$python,'-ArgumentsBase64',$encoded,'-RepoRoot',$root)
   $child=Start-WeatherProcessInJob -Job $job -FilePath $ps -WorkingDirectory $root -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens)
   $child.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal
   if(-not $child.WaitForExit($seconds*1000)){throw 'RPC archive phase deadline'}
   $code=$child.ExitCode
   $job.TerminateAndWait(5000);$clear=$true
  }catch{$errorKind=$_.Exception.GetType().Name}
  finally{
   if($job -and -not $clear){try{$job.TerminateAndWait(5000);$clear=$true}catch{$clear=$false}}
   if($child){$child.Dispose()};if($job){$job.Dispose()}
   $result=@{status=$(if($code -eq 0 -and $clear -and -not $errorKind){'PASS'}else{'FAILED_RETAIN_AND_INSPECT'});
     request_sha256=$requestHash;source_tip=$ExpectedSourceTip;exit_code=$code;teardown_proved=$clear;
     elapsed_seconds=([DateTime]::UtcNow-$started).TotalSeconds;deadline_seconds=$seconds;error_type=$errorKind;
     completed_at_utc=[DateTime]::UtcNow.ToString('o')}
   $null=New-Record $receipt $result
  }
 }
}
Write-Output ('WEATHER_ARCHIVE_RPC '+($result|ConvertTo-Json -Depth 40 -Compress))
if($result.status -cne 'PASS'){exit 1}
