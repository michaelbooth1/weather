param([string]$StopAt = '08:40')   # hard child kill time (local), before the 09:00 lease end
$ErrorActionPreference = 'Stop'
$Prod = 'C:\Users\micha\Desktop\github\weather'
$Py   = "$Prod\venv\Scripts\python.exe"
$Wt   = 'C:\tmp\wt-b-replay'
$Out  = 'C:\tmp\b-replay-20261008'
$Sha  = '7771474848e253ec6a45c4524ebfb70b726e08de'
New-Item -ItemType Directory -Force $Out | Out-Null      # already holds the three files
$res  = [ordered]@{ started = (Get-Date).ToString('s'); sha = $Sha }
function Save-Result { $res.saved = (Get-Date).ToString('s'); $res | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 "$Out\result.json" }
# --- resource preconditions (policy rule 2: HOST_LOAD_POLICY.md:400-404) ---
$g = Get-Content "$Prod\data\logs\memory_commit_guard_status.json" -Raw | ConvertFrom-Json
if ([double]$g.commit_percent -ge 70) { $res.refused = "commit_percent $($g.commit_percent)"; Save-Result; exit 1 }
$availGiB = (Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB
if ($availGiB -lt 4) { $res.refused = "available RAM $availGiB GiB"; Save-Result; exit 1 }
$freeGiB = (Get-PSDrive C).Free / 1GB
if ($freeGiB -lt 50) { $res.refused = "C: free $freeGiB GiB"; Save-Result; exit 1 }
if (Test-Path "$Out\b-replay.jsonl") { $res.refused = 'out exists'; Save-Result; exit 1 }
if (Test-Path $Wt) { $res.refused = "$Wt already exists"; Save-Result; exit 1 }
$res.pre = @{ commit_percent = $g.commit_percent; avail_gib = $availGiB; free_gib_before = $freeGiB }
. "$Prod\scripts\ops\workload_admission.ps1"
$lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $Prod -Workload 'b_replay_7771474'   # throws outside 00:30-09:00
$junction = $false
try {
  git -C $Prod fetch origin claude/scratch-189-224-b-20261006
  if ((git -C $Prod rev-parse "$Sha^{commit}") -ne $Sha) { throw 'scratch SHA missing' }
  git -C $Prod worktree add --detach $Wt $Sha
  if ((git -C $Wt rev-parse HEAD) -ne $Sha) { throw 'worktree HEAD mismatch' }
  if (git -C $Wt status --porcelain) { throw 'worktree not clean' }
  $head = [IO.File]::ReadAllBytes("$Wt\artifacts\models\hgb\feature_model_hgb.pkl")[0..22]
  if ([Text.Encoding]::ASCII.GetString($head) -like 'version https://git-lfs*') { throw 'LFS not smudged' }
  New-Item -ItemType Junction -Path "$Wt\data" -Target "$Prod\data" | Out-Null; $junction = $true
  $env:PYTHONPATH = "$Wt\src;$Wt"; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'; $env:PYTHONUTF8 = '1'
  Remove-Item Env:PYTHONSAFEPATH, Env:PYTHONHOME -ErrorAction SilentlyContinue
  Set-Location $Wt
  # proof_b.py = the §1.2 one-liner's python body (the text between the outer double quotes), one statement per line.
  # exec under -c keeps sys.path[0] = cwd, exactly as `-m` will see it.
  $proof = & $Py -c "exec(open(r'C:\tmp\b-replay-20261008\proof_b.py').read())"
  $res.import_proof = ($proof -join ' | ')
  if ($LASTEXITCODE -ne 0 -or ($proof -join ' ') -notmatch 'IMPORT-OK') { throw 'import proof failed' }
  $rargs = @('-m','weather.backtesting.metar_v4_lockin_replay','--snapshots-root',"$Prod\data\snapshots",
            '--from-date','2026-08-25','--through-date','2026-09-29','--compare-pre-lockin-floor',
            '--out',"$Out\b-replay.jsonl")
  $p = Start-Process -FilePath $Py -ArgumentList $rargs -WorkingDirectory $Wt -NoNewWindow -PassThru `
        -RedirectStandardOutput "$Out\summary.json" -RedirectStandardError "$Out\stderr.log"
  $null = $p.Handle                        # PS 5.1: needed for ExitCode later
  $p.PriorityClass = 'BelowNormal'
  $res.replay_pid = $p.Id; $res.replay_started = (Get-Date).ToString('s'); Save-Result
  $stop = [datetime]::ParseExact($StopAt, 'HH:mm', $null); $peakPriv = 0; $peakWs = 0
  while (-not $p.HasExited) {
    $p.Refresh(); $peakPriv = [math]::Max($peakPriv, $p.PrivateMemorySize64); $peakWs = [math]::Max($peakWs, $p.PeakWorkingSet64)
    if ($p.PrivateMemorySize64 -gt 6GB) { taskkill /PID $p.Id /T /F | Out-Null; $res.killed = 'private > 6 GiB'; break }
    if ((Get-Date) -gt $stop) { taskkill /PID $p.Id /T /F | Out-Null; $res.killed = "deadline $StopAt"; break }
    Start-Sleep -Seconds 30
  }
  $p.WaitForExit()
  $res.replay_exit = $p.ExitCode; $res.replay_finished = (Get-Date).ToString('s')
  $res.peak_private_gib = [math]::Round($peakPriv / 1GB, 2); $res.peak_ws_gib = [math]::Round($peakWs / 1GB, 2)
  if (Test-Path "$Out\b-replay.jsonl") { $res.out_gib = [math]::Round((Get-Item "$Out\b-replay.jsonl").Length / 1GB, 3) }
  if (-not $res.killed -and $res.replay_exit -in 0, 3) {
    $v = & $Py "$Out\eval_b.py" "$Out\b-replay.jsonl"; $res.eval_exit = $LASTEXITCODE
    ($v -join "`n") | Set-Content -Encoding UTF8 "$Out\verdict.json"
  }
} catch { $res.error = $_.Exception.Message }
finally {
  Set-Location 'C:\tmp'
  if ($junction -or (Test-Path "$Wt\data")) {
    cmd /c rmdir "$Wt\data"                                  # removes the LINK only, never the target
    if (Test-Path "$Wt\data") { $res.teardown = 'JUNCTION STILL PRESENT - worktree NOT removed' }
  }
  if (-not $res.teardown -and (Test-Path $Wt)) { git -C $Prod worktree remove --force $Wt; git -C $Prod worktree prune }
  $res.free_gib_after = (Get-PSDrive C).Free / 1GB
  Save-Result
  Exit-WeatherHeavyWorkloadLease -Lease $lease
}
