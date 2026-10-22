$tapeOk = $false; $tapeWanted = (Import-Csv "$N\aux-prestate.csv" | Where-Object Task -eq 'WeatherExecutionTapeSupervisor' | Where-Object { Test-PrestateEnabled $_ })
if ($tapeWanted) { $t0 = Get-Date
  while (-not $tapeOk -and ((Get-Date)-$t0).TotalMinutes -lt 5) {   # status exits 0 only for RUNNING/DEGRADED (execution_tape_supervisor.py:936)
    $tsc = Invoke-Native $Py @('-m','weather.operations.execution_tape_supervisor','status','--stale-after-seconds','180') "$N\tape-status-$(Get-Date -Format HHmmss)"
    if ($tsc -eq 0) { $tapeOk = $true } else { Start-Sleep 20 } }
  if (-not $tapeOk) { NoGo 'tape not RUNNING/DEGRADED after 5 min - inspect the tape status files; import or runtime error -> ROLLBACK' } }
$m = Get-Content -LiteralPath (Join-Path $P 'data\maker_evidence\status.json') -Raw | ConvertFrom-Json
Log "88a state=$($m.state) updated=$($m.updated_at_utc) cycles=$($m.cycles) last_error=$($m.last_error)"
foreach ($ft in $FamilyTasks) {   # family id from the task name: WeatherMakerEvidenceLowestTemperature -> lowest_temperature
  $fid = (($ft -replace '^WeatherMakerEvidence','') -creplace '([a-z0-9])([A-Z])','$1_$2').ToLowerInvariant()
  $fs = Get-Content -LiteralPath (Join-Path $P "data\maker_evidence_families\$fid\status.json") -Raw | ConvertFrom-Json
  Log "family $fid state=$($fs.state) updated=$($fs.updated_at_utc) cycles=$($fs.cycles) last_error=$($fs.last_error)" }
$st2 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-full"
$new2 = Get-NewStatusFlags "$N\status-full" "$R\c0-status-flags.txt" 'C9c'
