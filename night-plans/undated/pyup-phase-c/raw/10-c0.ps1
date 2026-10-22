$q = Get-Content "$R\qualification.json" -Raw | ConvertFrom-Json; if ($q.result -ne 'PASS' -or $q.release_case -ne 'A') { NoGo 'not qualified for case A' }
if (((Get-Content -LiteralPath "$R\q12.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'Q12 not recorded as STOP_AUTHORIZED (G8)' }
$GapChoice = Get-GapChoice; Log "gap-overrun choice: $GapChoice"
Assert-NoU6At0035 'C0'     # enforced here, not left to the C0 next-runs exemption of the aux list
$Head = (git -C $P rev-parse HEAD).Trim()
if ($Head -ne $q.tip) { Log "HEAD moved from the qualified tip; G3 needs roll_verdict.ps1 -Branch $Head -Base $($q.tip) exit 0 (ROLL-FREE) attached before GO, else B-R" }
# Q12b: a capture-family task (N12) holds the venv like the 88a worker; it must be quiesced at C2 under a recorded choice
$FamilyTasks = @(Get-ScheduledTask -TaskName 'WeatherMakerEvidence*' -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -ne 'WeatherMakerEvidenceCapture' } | ForEach-Object { $_.TaskName })
Log "capture-family tasks: $($FamilyTasks -join ',')"
if ($FamilyTasks.Count) {
  if (-not (Test-Path -LiteralPath "$R\q12b.txt") -or ((Get-Content -LiteralPath "$R\q12b.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'a capture-family task is registered but Q12b is not STOP_AUTHORIZED' }
  $auxNames = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | ForEach-Object { $_.Trim() })
  foreach ($ft in $FamilyTasks) { if ($auxNames -notcontains $ft) { NoGo "$ft is not in aux-tasks.txt (A1 review)" } } }
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'prod tree dirty' }
if (Test-Path -LiteralPath $Old) { NoGo "$Old exists" }
if ((Get-Volume -DriveLetter C).SizeRemaining -lt 10GB) { NoGo 'disk' }
foreach ($tn in 'WeatherTrainingWindow','WeatherEveningEvidenceRefresh') { $x = Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$tn is enabled or still running (State $($x.State), G5)" } }   # State, not Settings.Enabled: a disabled task still running holds the lease
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
Log "lease state $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress)"
$st0 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$R\c0-status"
Save-StatusBaseline "$R\c0-status" "$R\c0-status-flags.txt"   # exit $st0 is 2 whenever any standing flag exists; not a gate
$ra0 = Get-ReleaseActive $Py "$R\c0-release-active"; Assert-CaseA $ra0 'C0'
$Exempt = @('WeatherMemoryCommitGuard','WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor','WeatherTrainingWindowRestore') +
          @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
Get-ScheduledTask | Where-Object { [string]$_.State -ne 'Disabled' -and $Exempt -notcontains $_.TaskName } | ForEach-Object { $i = Get-ScheduledTaskInfo $_
  if ($i.NextRunTime -and $i.NextRunTime -lt (Get-Date).Date.AddHours(4)) { "$($_.TaskName) next=$($i.NextRunTime)" } } | Tee-Object -FilePath "$R\c0-next-runs.txt"
Log "C0 complete (status.ps1 exit $st0) - awaiting owner GO"
