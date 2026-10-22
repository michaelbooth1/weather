$global:Lease = $null; $deadline = (Get-Date).Date.AddHours(1).AddMinutes(15)
while (-not $global:Lease) { $global:Lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $P -Workload 'py3119_cutover'
  if (-not $global:Lease) { if ((Get-Date) -gt $deadline) { NoGo 'no lease by 01:15' }; Start-Sleep -Seconds 30 } }
$global:ReleaseOnNoGo = $true     # until the C4 rename, any NoGo releases the lease; after it, §R needs the lease
$N = Join-Path $R ('night-' + (Get-Date -Format yyyyMMdd)); New-Item -ItemType Directory -Force $N | Out-Null
& $Py -m pip freeze --all | Set-Content "$N\freeze-3110-tonight.txt"
if (Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt")) (Mask-Editable (Get-Content "$N\freeze-3110-tonight.txt"))) { NoGo 'prod venv changed since Phase B - requalify (full Phase B on another night)' }
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') { Copy-Item -LiteralPath (Join-Path $P "data\snapshots\$f") "$N\pre-$f" }
$shadowTask = Get-ScheduledTask -TaskName WeatherMakerShadowRunner -ErrorAction SilentlyContinue
$ShadowStop = $null
if ($shadowTask) {   # the registrar's -StopFile (register_maker_shadow_runner.ps1:31, :43)
  if ([string]$shadowTask.Actions[0].Arguments -match '--stop-file\s+"([^"]+)"') { $ShadowStop = $Matches[1] } else { NoGo 'shadow task registered but its stop-file argument is unreadable' } }
Log "shadow task registered=$([bool]$shadowTask) stop file: $ShadowStop"
