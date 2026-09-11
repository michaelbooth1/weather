# Lightweight campaign owner. Payload phases retain their own admission leases.
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$Configuration,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigurationSHA256,
 [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedSourceTip,
 [ValidateRange(0,10000)][int]$MaximumBatches=0
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version 2
$source=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if((git -C $source rev-parse HEAD) -cne $ExpectedSourceTip -or @(git -C $source status --porcelain).Count -ne 0){throw 'campaign source is not exact and clean'}
if(-not [IO.Path]::IsPathRooted($Configuration)){throw 'campaign configuration must be absolute'}
$info=Get-Item -LiteralPath $Configuration -Force
if($info.Length -gt 262144 -or ($info.Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'campaign configuration bound or redirect'}
if((Get-FileHash -LiteralPath $Configuration -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ConfigurationSHA256){throw 'campaign configuration hash differs'}
$config=Get-Content -LiteralPath $Configuration -Raw|ConvertFrom-Json
if($config.production_source_tip -cne $ExpectedSourceTip){throw 'campaign configuration source differs'}
$python=Join-Path ([string]$config.production_root) 'venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'production interpreter is absent'}
. (Join-Path $PSScriptRoot 'windows_kill_on_close_job.ps1')
$mutex=New-Object Threading.Mutex($false,'Global\WeatherColdArchiveCampaignControllerV1')
$held=$false;$job=$null;$child=$null;$cleared=$false;$code=1
$prior=$env:WEATHER_ARCHIVE_CAMPAIGN_WRAPPER
$priorPythonPath=$env:PYTHONPATH
try{
 try{$held=$mutex.WaitOne(0)}catch [Threading.AbandonedMutexException]{$held=$true}
 if(-not $held){throw 'another archive campaign controller owns this host'}
 $env:WEATHER_ARCHIVE_CAMPAIGN_WRAPPER='1'
 $env:PYTHONPATH=Join-Path $source 'src'
 $logParent=Join-Path ([string]$config.production_root) ('scratch/ac-control/'+[string]$config.campaign_id)
 $logPath=Join-Path $logParent ('controller-'+[Guid]::NewGuid().ToString('N')+'.log')
 Write-Output ('CAMPAIGN_LOG '+$logPath)
 $childTokens=@('-m','weather.operations.cold_archive_campaign','--config',$Configuration,'--config-sha256',$ConfigurationSHA256,'--log-file',$logPath)
 if($MaximumBatches -gt 0){$childTokens+=@('--max-batches',[string]$MaximumBatches)}
 $job=New-WeatherKillOnCloseJob
 $child=Start-WeatherProcessInJob -Job $job -FilePath $python -WorkingDirectory $source -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $childTokens)
 $child.PriorityClass=[Diagnostics.ProcessPriorityClass]::BelowNormal
 while(-not $child.WaitForExit(1000)){
  $child.Refresh()
  if([Math]::Max($child.WorkingSet64,$child.PrivateMemorySize64) -gt 384MB){throw 'campaign controller memory limit'}
 }
 $code=$child.ExitCode
 if(Test-Path -LiteralPath $logPath){Get-Content -LiteralPath $logPath -Tail 30}
 $job.TerminateAndWait(5000);$cleared=$true
}finally{
 $env:WEATHER_ARCHIVE_CAMPAIGN_WRAPPER=$prior
 $env:PYTHONPATH=$priorPythonPath
 if($job -and -not $cleared){$job.TerminateAndWait(5000);$cleared=$true}
 if($child){$child.Dispose()};if($job){$job.Dispose()}
 if($held){$mutex.ReleaseMutex()};$mutex.Dispose()
}
exit $code
