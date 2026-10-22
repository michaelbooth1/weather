# WRAPPER PHASE-C0 run wrapper (agent, 2026-10-20; re-dated from the 20261017 kit for the night 2026-10-21/22). READ-ONLY: section 6 header, helper definitions, C0 only.
# WRAPPER Source: C:\tmp\agent-kit\phase-c-raw-20261022.md sha256 6ECF4B320144DE858418B5F44802775B28DB79C044EF1441F4D6B2820015919C
# WRAPPER   Block 1 (section 6 header, host values filled), Block 2 (Build-Venv / Test-Venv definitions only), Block 3 C0: verbatim.
# WRAPPER Runbook: docs\operations\HOST_PYTHON_UPGRADE_RUNBOOK.md sha256 FE074EE48EE564F9461F8615E5F3CD56FCB01024490D86B2147B9327C4361759 at review tip 41e3bec62 (origin/claude/pyup-c-1021-review-20261019; not yet on master).
# WRAPPER Output: transcript C:\pyup\cp3119\phase-c0-transcript-20261022.txt; C:\pyup\cp3119\c0-done-20261022.flag ONLY when C0 completed with no NO-GO
# WRAPPER   (flag line: "C0 PASS head=<40-hex HEAD> at=<time>"; the Phase C wrapper compares that head). Exit 0 = C0 complete, 1 = stopped.
# WRAPPER Non-verbatim lines (every one ends in or starts with "# WRAPPER"): these header comments; removal of a stale flag before the run;
# WRAPPER   Start-Transcript; "try {"; the "# ---- WRAPPER" separators; after C0: the next-runs count log, the OPERATOR CHECK log, the flag write
# WRAPPER   and its log; the catch line (log PHASE-C0 STOPPED, null-safe Release-Lease, Stop-Transcript, exit 1); Stop-Transcript; exit 0.
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host 'REFUSED: not elevated (Get-ScheduledTask would hide S4U tasks)'; exit 3 }   # WRAPPER Fable 10-20 #2
if ([Console]::IsErrorRedirected -or [Console]::IsOutputRedirected) { Write-Host 'REFUSED: stdio redirected; run -File in a real elevated console'; exit 3 }   # WRAPPER Fable 10-20 #2
Remove-Item -LiteralPath 'C:\pyup\cp3119\c0-done-20261022.flag' -Force -ErrorAction SilentlyContinue   # WRAPPER a flag from an earlier attempt never survives a new run
Start-Transcript -LiteralPath 'C:\pyup\cp3119\phase-c0-transcript-20261022.txt' -Append | Out-Null   # WRAPPER
try {   # WRAPPER
# ---- WRAPPER Block 1. Section 6 header (runbook section 6, host values filled)
$ErrorActionPreference = 'Stop'
$P       = 'C:\Users\micha\Desktop\github\weather'                 # e.g. the WeatherSnapshotLoopSupervisor working directory
$Py      = Join-Path $P 'venv\Scripts\python.exe'
$R       = 'C:\pyup\cp3119'
$WH      = Join-Path $R 'wheelhouse'; $Tools = Join-Path $R 'tools'   # $Inst (installer) retired 2026-10-13
$A       = Join-Path $R 'receipts-3110'
$NewHome = 'C:\Program Files\Python311-cp3119'   # under Program Files: Users get read/execute only
$NewPy   = Join-Path $NewHome 'python.exe'
$Stage   = Join-Path (Split-Path -Parent $P) 'weather-py3119-stage'; $StagePy = Join-Path $Stage 'venv\Scripts\python.exe'   # Phase B's stage
$Old     = Join-Path $P 'venv-cp3110'
$Log     = Join-Path $R 'night.log'
New-Item -ItemType Directory -Force $R, $Tools, $A | Out-Null
$K = if (Test-Path -LiteralPath (Join-Path $R 'constants.json')) { Get-Content -LiteralPath (Join-Path $R 'constants.json') -Raw | ConvertFrom-Json }   # §6a
if ($K) { foreach ($kk in 'nupkg_url','nupkg_size','nupkg_sha512_b64','tools_manifest_sha256','binary_signer_thumbprint','vv_prefix','binaries') { if (-not $K.$kk) { throw "constants.json lacks $kk" } } }
# Session globals that a later phase reads come from files, never from an earlier session (A1 writes oldhome.txt).
$OldHome = if (Test-Path -LiteralPath "$R\oldhome.txt") { (Get-Content -LiteralPath "$R\oldhome.txt" -TotalCount 1).Trim() }
function Log($m){ $l = "{0:o} {1}" -f (Get-Date), $m; Add-Content -LiteralPath $Log -Value $l -Encoding utf8; Write-Host $l }
# The lease lives in the session's global scope. While $global:ReleaseOnNoGo is set (B0-B1e, and C1 until the C4 rename),
# every NoGo releases it; after the C4 rename it stays held for §R.
$global:Lease = $null; $global:ReleaseOnNoGo = $false
function Release-Lease { if ($global:Lease) { Exit-WeatherHeavyWorkloadLease -Lease $global:Lease; $global:Lease = $null; Log 'lease released' } }
function NoGo($m){ Log "NO-GO: $m"; if ($global:ReleaseOnNoGo) { $global:ReleaseOnNoGo = $false; Release-Lease }; throw "NO-GO: $m" }
function Sha($f){ (Get-FileHash -LiteralPath $f -Algorithm SHA256).Hash.ToUpper() }
# pip freeze records the production HEAD on the weather editable line, so it changes on every master merge (A' r2, 2026-10-14).
# Mask only that 40-hex sha, only on that exact line; every other line, and any other form of that line, is compared as is.
function Mask-Editable([string[]]$Lines) { foreach ($line in $Lines) {
  if ($line -cmatch '^-e git\+https://github\.com/michaelbooth1/weather\.git@[0-9a-f]{40}#egg=weather_market$') { $line -creplace '@[0-9a-f]{40}#', '@<HEAD>#' } else { $line } } }
# Native calls whose stderr matters go through Invoke-Native. Never use 2>&1 or 2> on a native command while
# $ErrorActionPreference is 'Stop': Windows PowerShell 5.1 turns each stderr line into a terminating error.
function Invoke-Native([string]$Exe, [string[]]$Arguments, [string]$OutBase) {
  $quoted = foreach ($a in $Arguments) { if ($a -match '[\s"]') { '"' + ($a -replace '"','\"') + '"' } else { $a } }
  $proc = Start-Process -FilePath $Exe -ArgumentList ($quoted -join ' ') -WorkingDirectory $P -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$OutBase.out.txt" -RedirectStandardError "$OutBase.err.txt"
  $proc.WaitForExit(); if ($null -eq $proc.ExitCode) { NoGo "no exit code from $Exe" }
  Log ("native exit {0}: {1} {2}" -f $proc.ExitCode, (Split-Path -Leaf $Exe), ($Arguments -join ' ')); [int]$proc.ExitCode }
# Release readiness as parsed fields (release_lifecycle_cli prints JSON; a BLOCK goes to stderr with a non-zero exit)
function Get-ReleaseActive([string]$Exe, [string]$OutBase) {
  $code = Invoke-Native $Exe @('-m','weather.operations.release_lifecycle_cli','--repo-root',$P,'active') $OutBase
  # "$(...)" not [string](...): Get-Content -Raw of an empty file is $null and [string]$null stays $null in PS 5.1,
  # so the BLOCK case (empty stdout) threw at $o.Trim() (Phase B B3, 2026-10-16).
  $o = "$(Get-Content -LiteralPath "$OutBase.out.txt" -Raw)"; $e = "$(Get-Content -LiteralPath "$OutBase.err.txt" -Raw)"
  # PASS prints indented JSON on stdout; BLOCK prints one JSON line on stderr (release_lifecycle_cli.py:191).
  # Take only that last JSON line from stderr, so a stray warning line cannot break the parse.
  $raw = if ($o.Trim()) { $o } else { @($e -split "`r?`n" | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1 }
  try { $j = $raw | ConvertFrom-Json } catch { NoGo "release active output is not JSON ($OutBase)" }
  $r = [pscustomobject]@{ exit=$code; status=[string]$j.status; error=[string]$j.error }
  $r | ConvertTo-Json | Set-Content -LiteralPath "$OutBase.json" -Encoding utf8; $r }
# G5/Q3: a U6 export registered at 00:35 can hold the lease until 01:25, so it must be disabled on Phase B and C nights
function Assert-NoU6At0035([string]$Tag) {
  $u6 = Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue
  if ($u6 -and [string]$u6.State -ne 'Disabled' -and @($u6.Triggers | Where-Object { [string]$_.StartBoundary -match 'T00:35' }).Count -gt 0) {
    NoGo "$Tag U6 export is registered at 00:35 and enabled (G5, Q3)" } }
# §11: the owner's recorded choice for a capture gap over 35 minutes; first token ACCEPT_OVERRUN or ROLLBACK_ON_OVERRUN
function Get-GapChoice { $c = if (Test-Path -LiteralPath "$R\gap-overrun.txt") { ((Get-Content -LiteralPath "$R\gap-overrun.txt" -TotalCount 1) -split '\s+')[0] }
  if ($c -notin 'ACCEPT_OVERRUN','ROLLBACK_ON_OVERRUN') { NoGo 'gap-overrun choice not recorded in $R\gap-overrun.txt (§11)' }; $c }
function Assert-CaseA($ra, $tag) {
  if ($ra.status -ne 'BLOCK' -or $ra.error -notlike '*active release pointer is missing*') { NoGo "$tag release is not case A: $($ra | ConvertTo-Json -Compress)" }
  if (Test-Path -LiteralPath (Join-Path $P 'artifacts\releases\current_release.json')) { NoGo "$tag active release pointer exists" } }
# status.ps1 -Json exits 2 on ANY flag, and the host can carry standing flags that predate the night (2026-10-16: an
# overdue documentation transaction and two STALENESS_SWEEP CRITICAL rows). Never gate on its exit code; compare its
# flags with a baseline taken before the phase. Keys mask 64-hex hashes and numbers, so an ageing standing flag
# ("63 days" -> "64 days") keeps its key while a new kind of flag does not.
function Get-StatusFlagKeys([string]$OutBase) {
  $raw = "$(Get-Content -LiteralPath "$OutBase.out.txt" -Raw)"; if (-not $raw.Trim()) { NoGo "status.ps1 printed nothing ($OutBase)" }
  try { $j = $raw | ConvertFrom-Json } catch { NoGo "status.ps1 output is not JSON ($OutBase)" }
  if ($null -eq $j -or -not $j.PSObject.Properties['flags']) { NoGo "status.ps1 JSON has no flags field ($OutBase)" }
  @(@($j.flags) | ForEach-Object { ([string]$_ -replace '[0-9a-fA-F]{64}','<sha>') -replace '\d+(\.\d+)?','#' } | Sort-Object -Unique) }
function Save-StatusBaseline([string]$OutBase, [string]$Path) {
  $k = @(Get-StatusFlagKeys $OutBase); $k | Set-Content -LiteralPath $Path -Encoding utf8; Log "status baseline $Path ($($k.Count) flags)" }
function Get-NewStatusFlags([string]$OutBase, [string]$Baseline, [string]$Tag) {
  if (-not (Test-Path -LiteralPath $Baseline)) { NoGo "$Tag status baseline $Baseline is missing" }
  $base = @(Get-Content -LiteralPath $Baseline | Where-Object { $_ })
  $new = @(Get-StatusFlagKeys $OutBase | Where-Object { $base -notcontains $_ })
  $new | Set-Content -LiteralPath "$OutBase.new-flags.txt" -Encoding utf8
  Log "$Tag status: $($new.Count) new flag(s) vs $(Split-Path -Leaf $Baseline)"; $new }
. (Join-Path $P 'scripts\ops\workload_admission.ps1')
. (Join-Path $P 'scripts\ops\memory_guard_status_reader.ps1')
Log "session start host=$env:COMPUTERNAME head=$(git -C $P rev-parse HEAD)"

# ---- WRAPPER Block 2. Build-Venv (B1c) and Test-Venv (B1d) function definitions only
function Build-Venv($vpy, $root) {
  Select-String -LiteralPath "$R\lock-hashed.txt" -Pattern '^(pip|setuptools|wheel)==' | ForEach-Object Line | Set-Content "$R\lock-tools-hashed.txt" -Encoding ascii
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-tools-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tools install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-hashed.txt";       if ($LASTEXITCODE) { NoGo 'lock install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --no-deps -e $root;                                    if ($LASTEXITCODE) { NoGo 'editable install' }
}

function Test-Venv($vpy, $root, $tag) {
  $out = Join-Path $R "check-$tag"; New-Item -ItemType Directory -Force $out | Out-Null
  $vv = & $vpy -VV; $vv | Set-Content "$out\VV.txt"; if ($vv -notlike "$($K.vv_prefix)*") { NoGo "$tag VV" }
  $cfg = Get-Content -LiteralPath (Join-Path (Split-Path (Split-Path $vpy)) 'pyvenv.cfg')
  if (-not ($cfg -match ('^home\s*=\s*' + [regex]::Escape($NewHome) + '\s*$'))) { NoGo "$tag pyvenv home" }
  & $vpy -I -m pip check | Set-Content "$out\pipcheck.txt"; if ($LASTEXITCODE) { NoGo "$tag pip check" }
  $skip = '^(-e |#)'   # under the Q13 exemption use '^(-e |#|tzdata==)'
  $d = Compare-Object (Get-Content "$A\freeze-3110.txt" | Where-Object { $_ -notmatch $skip }) (& $vpy -m pip freeze --all | Where-Object { $_ -notmatch $skip })
  $d | Out-File "$out\freeze-diff.txt"; if ($d) { NoGo "$tag freeze differs" }
  # import location: run from a neutral directory so only the editable install can supply the packages
  Push-Location -LiteralPath $R
  try {
    $loc = & $vpy -c "import weather, maker_core; print(weather.__file__); print(maker_core.__file__)"; if ($LASTEXITCODE) { NoGo "$tag import location" }
    $src = (Join-Path $root 'src') + '\'
    foreach ($l in $loc) { if (-not $l.StartsWith($src, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag package imported from $l, not $src" } }
    # Without -I (as the workers run): the stdlib comes from the new home and no sys.path entry reaches the
    # 3.11.0 home, whose PEP 514 PythonPath key shares sys.winver 3.11.
    $std = & $vpy -c "import os, ssl, sys; print(os.__file__); print(ssl.__file__); print('\n'.join(p for p in sys.path if p))"; if ($LASTEXITCODE) { NoGo "$tag stdlib location" }
    $std | Set-Content "$out\stdlib-path.txt" -Encoding utf8
    if (-not $OldHome) { NoGo "$tag oldhome.txt missing" }
    $nh = $NewHome.TrimEnd('\') + '\'; $oh = $OldHome.TrimEnd('\') + '\'
    foreach ($s in $std[0..1]) { if (-not $s.StartsWith($nh, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag stdlib from $s, not $nh" } }
    foreach ($s in $std) { if (($s.TrimEnd('\') + '\').StartsWith($oh, [StringComparison]::OrdinalIgnoreCase)) { NoGo "$tag sys.path reaches the 3.11.0 home: $s" } }
  } finally { Pop-Location }
  Push-Location -LiteralPath $root
  try {
    & $vpy -c "import json; from weather.release_artifacts import capture_runtime_versions as c; print(json.dumps(c(), indent=1, sort_keys=True))" | Set-Content "$out\rtv.json" -Encoding utf8
    & $vpy -c "import weather.collection.snapshot_tracker, weather.market.market_microstructure, weather.operations.observation_trigger, weather.operations.execution_tape_supervisor, weather.operations.capture_recovery_check, weather.release_serving, weather.market.maker_evidence_capture, weather.market.maker_shadow; import sklearn, numpy, scipy, pandas, pyarrow, netCDF4, websocket, requests; print('import smoke ok')"
    if ($LASTEXITCODE) { NoGo "$tag import smoke" }
  } finally { Pop-Location }
  $o = Get-Content "$A\rtv-3110.json" -Raw | ConvertFrom-Json; $n = Get-Content "$out\rtv.json" -Raw | ConvertFrom-Json
  if ($n.python -ne '3.11.9' -or $o.implementation -ne $n.implementation) { NoGo "$tag rtv python/implementation" }
  if (($o.direct_dependencies | ConvertTo-Json -Compress) -ne ($n.direct_dependencies | ConvertTo-Json -Compress)) { NoGo "$tag direct dependencies moved" }
  Log "$tag Test-Venv PASS"
}

# ---- WRAPPER C0. GO checks (verbatim)
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
  if ($x -and [string]$x.State -ne 'Disabled') { NoGo "$tn is enabled (G5)" } }
$mg = Read-WeatherMemoryGuardStatus -Path (Join-Path $P 'data\logs\memory_commit_guard_status.json'); Log "memory $($mg | ConvertTo-Json -Compress)"
Log "lease state $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress)"
$st0 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$R\c0-status"
Save-StatusBaseline "$R\c0-status" "$R\c0-status-flags.txt"   # exit $st0 is 2 whenever any standing flag exists; not a gate
$ra0 = Get-ReleaseActive $Py "$R\c0-release-active"; Assert-CaseA $ra0 'C0'
$Exempt = @('WeatherMemoryCommitGuard','WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor','WeatherTrainingWindowRestore') +
          @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
Get-ScheduledTask | Where-Object { [string]$_.State -ne 'Disabled' -and $Exempt -notcontains $_.TaskName } | ForEach-Object { $i = Get-ScheduledTaskInfo $_
  if ($i.NextRunTime -and $i.NextRunTime -lt (Get-Date).Date.AddHours(4)) { "$($_.TaskName) next=$($i.NextRunTime)" } } | Tee-Object -FilePath "$R\c0-next-runs.txt"
$wr = Get-ScheduledTask -TaskName WeatherTrainingWindowRestore; if ([string]$wr.State -eq 'Disabled' -or -not @($wr.Triggers | Where-Object { [string]$_.StartBoundary -match 'T04:15' -and $_.Enabled }).Count) { NoGo 'WeatherTrainingWindowRestore (04:15 net) is not armed' }   # WRAPPER Fable 10-20 #5
Log "C0 complete (status.ps1 exit $st0) - awaiting owner GO"

# ---- WRAPPER end of C0: flag + operator check
$wNextRuns = @(if (Test-Path -LiteralPath "$R\c0-next-runs.txt") { Get-Content -LiteralPath "$R\c0-next-runs.txt" | Where-Object { "$_".Trim() } })   # WRAPPER
Log "WRAPPER: c0-next-runs.txt has $($wNextRuns.Count) line(s) (must be empty, else the task goes to the owner)"   # WRAPPER
Log "OPERATOR CHECK: owner GO point. Master reviews $R\c0-status.out.txt (capture 3/3, no unaccepted FLAG), $R\c0-status-flags.txt (the C8/C9c baseline), $R\c0-next-runs.txt (must be empty), G3/G5/G7/G8/G11 and the G3 output of roll_verdict.ps1 -Branch $Head -Base $($q.tip) (must exit 0, ROLL-FREE); the owner's GO goes in C:\pyup\cp3119\owner-go-20261022.txt (first token GO)."   # WRAPPER
Set-Content -LiteralPath 'C:\pyup\cp3119\c0-done-20261022.flag' -Value "C0 PASS head=$Head at=$(Get-Date -Format o)" -Encoding ascii   # WRAPPER
Log 'PHASE-C0 DONE flag written'   # WRAPPER
} catch { Write-Host "PHASE-C0 STOPPED: $($_.Exception.Message)"; try { Log "PHASE-C0 STOPPED: $($_.Exception.Message)" } catch {}; try { $global:ReleaseOnNoGo = $false; Release-Lease } catch { Write-Host "Release-Lease failed: $($_.Exception.Message)" }; Stop-Transcript | Out-Null; exit 1 }   # WRAPPER
Stop-Transcript | Out-Null   # WRAPPER
exit 0   # WRAPPER
