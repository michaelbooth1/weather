# WRAPPER PHASE-C run wrapper (agent, 2026-10-20; re-dated from the 20261017 kit for the night 2026-10-21/22): Python 3.11.9 venv cutover, C0 re-run + C1..C10, with §R on a post-rename failure.
# WRAPPER Source: C:\tmp\agent-kit\phase-c-raw-20261022.md sha256 6ECF4B320144DE858418B5F44802775B28DB79C044EF1441F4D6B2820015919C
# WRAPPER   Block 1 (section 6 header, host values filled), Block 2 (Build-Venv / Test-Venv definitions), C0..C10 and §R: verbatim, in order.
# WRAPPER Runbook: docs\operations\HOST_PYTHON_UPGRADE_RUNBOOK.md sha256 FE074EE48EE564F9461F8615E5F3CD56FCB01024490D86B2147B9327C4361759 at review tip 41e3bec62 (origin/claude/pyup-c-1021-review-20261019; not yet on master).
# WRAPPER Transcript C:\pyup\cp3119\phase-c-transcript-20261022.txt.
# WRAPPER Exit codes: 0 CUTOVER PASS (C10 ran); 1 stopped before the C4 rename (runbook blocks or the wrapper undid with no swap, lease released);
# WRAPPER   2 §R ran to ROLLBACK DONE; 3 refused before any block; 4 operator hold / escalation (the lease is held by this process until a
# WRAPPER   RELEASE token, as runbook §R "Lease on an escalated §R" requires, or nothing was touched).
# WRAPPER Operator files (first token, case-sensitive; must be written after the OPERATOR CHECK line that asks for it):
# WRAPPER   C:\pyup\cp3119\decision-c8-20261022.txt  CONTINUE|ROLLBACK        (deadline 02:15, default ROLLBACK = "core not passed = §R")
# WRAPPER   C:\pyup\cp3119\decision-c9c-20261022.txt CONTINUE|ROLLBACK|HOLD   (deadline 02:45 = §R start limit, default HOLD)
# WRAPPER   C:\pyup\cp3119\hold-<step>-20261022.txt RELEASE (or ROLLBACK where offered); no timeout: the runbook says nobody else releases.
# WRAPPER Non-verbatim lines (each one carries "# WRAPPER"): this header; the preflight (refusal, exit 3); the wrapper functions Exit-Wrapper,
# WRAPPER   Wait-OperatorDecision, Wait-OperatorHold, Invoke-WrapperRollback; the two lines that open and close "function Invoke-SectionR {"
# WRAPPER   around the verbatim §R block; "try {"; the "# ---- WRAPPER" separators; each "$WStep = ..." line; the C0 GO-review copy and the
# WRAPPER   post-C0 checks (HEAD vs flag, baseline vs GO-reviewed, next-runs vs GO-reviewed, restore of the GO-reviewed baseline);
# WRAPPER   "$msg = $null" before C3; the C8 (d) judgement; the C9c judgement; the PHASE-C DONE log; the whole catch block; the final exit.
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host 'REFUSED: not elevated (Get-ScheduledTask would hide S4U tasks)'; exit 3 }   # WRAPPER Fable 10-20 #2
if ([Console]::IsErrorRedirected -or [Console]::IsOutputRedirected) { Write-Host 'REFUSED: stdio redirected; native stderr becomes terminating under Stop; run -File in a real elevated console'; exit 3 }   # WRAPPER Fable 10-20 #2
$WFlag = 'C:\pyup\cp3119\c0-done-20261022.flag'   # WRAPPER
$WGo   = 'C:\pyup\cp3119\owner-go-20261022.txt'   # WRAPPER
Start-Transcript -LiteralPath 'C:\pyup\cp3119\phase-c-transcript-20261022.txt' -Append | Out-Null   # WRAPPER
# ---- WRAPPER preflight: refuse with exit 3 before any runbook block
$WNow = Get-Date; $WWhy = $null; $WFlagHead = $null   # WRAPPER
if (-not (Test-Path -LiteralPath $WFlag)) { $WWhy = "$WFlag is missing (C0 has not completed)" }   # WRAPPER
elseif ((Get-Item -LiteralPath $WFlag).LastWriteTime -lt $WNow.Date) { $WWhy = "$WFlag was not written today" }   # WRAPPER
elseif (-not ("$(Get-Content -LiteralPath $WFlag -TotalCount 1)" -match 'head=([0-9a-f]{40})')) { $WWhy = "$WFlag has no head=" }   # WRAPPER
else { $WFlagHead = $Matches[1] }   # WRAPPER
if (-not $WWhy) {   # WRAPPER
  if (-not (Test-Path -LiteralPath $WGo)) { $WWhy = "$WGo is missing (no owner GO)" }   # WRAPPER
  elseif (("$(Get-Content -LiteralPath $WGo -TotalCount 1)".Trim() -split '\s+')[0] -cne 'GO') { $WWhy = "$WGo first token is not GO" }   # WRAPPER
  elseif ($WNow -lt $WNow.Date.AddHours(1)) { $WWhy = 'before 01:00 (C1 must not start earlier)' }   # WRAPPER
  elseif ($WNow -gt $WNow.Date.AddHours(1).AddMinutes(15)) { $WWhy = 'after 01:15 (the C1 lease deadline)' } }   # WRAPPER
if ($WWhy) { Write-Host "PHASE-C REFUSED: $WWhy"; Stop-Transcript | Out-Null; exit 3 }   # WRAPPER

# ---- WRAPPER functions
function Exit-Wrapper([int]$Code) {   # WRAPPER
  try { Log "PHASE-C wrapper exit $Code" } catch { Write-Host "PHASE-C wrapper exit $Code" }   # WRAPPER
  try { Stop-Transcript | Out-Null } catch {}   # WRAPPER
  exit $Code }   # WRAPPER
function Wait-OperatorDecision([string]$Tag, [string[]]$Allowed, [datetime]$Deadline, [string]$Default) {   # WRAPPER
  $df = "C:\pyup\cp3119\decision-$Tag-20261022.txt"; $t0 = Get-Date   # WRAPPER
  Log "OPERATOR CHECK: $Tag needs a decision. Write $df with first token $($Allowed -join '|') by $($Deadline.ToString('HH:mm')); no decision by then = $Default"   # WRAPPER
  while ((Get-Date) -lt $Deadline) {   # WRAPPER
    if ((Test-Path -LiteralPath $df) -and (Get-Item -LiteralPath $df).LastWriteTime -ge $t0) {   # WRAPPER
      $tok = ("$(Get-Content -LiteralPath $df -TotalCount 1)".Trim() -split '\s+')[0]   # WRAPPER
      if ($tok -cin $Allowed) { Log "WRAPPER: $Tag operator decision $tok"; return $tok } }   # WRAPPER
    Start-Sleep -Seconds 15 }   # WRAPPER
  Log "WRAPPER: $Tag no decision by $($Deadline.ToString('HH:mm')); applying $Default"; return $Default }   # WRAPPER
function Wait-OperatorHold([string]$Tag, [bool]$AllowRollback) {   # WRAPPER
  $hf = "C:\pyup\cp3119\hold-$Tag-20261022.txt"; $t0 = Get-Date   # WRAPPER
  $ok = if ($AllowRollback) { @('RELEASE','ROLLBACK') } else { @('RELEASE') }   # WRAPPER
  Log "OPERATOR CHECK: HOLD at $Tag. This process (PID $PID) keeps the lease and the session; escalate to the owner. Write $hf with first token $($ok -join ' or ') (RELEASE only with the owner's agreement, by 09:00; runbook §R 'Lease on an escalated §R')."   # WRAPPER
  $wRemind = $false   # WRAPPER
  while ($true) {   # WRAPPER
    if ($AllowRollback -and (Get-Date) -gt (Get-Date).Date.AddHours(8).AddMinutes(55) -and (Get-Date) -lt (Get-Date).Date.AddHours(12)) { Log "WRAPPER: hold $Tag reached the 08:55 lease deadline (host known-good); RELEASE"; return 'RELEASE' }   # WRAPPER (Fable r1 #4)
    if (-not $wRemind -and (Get-Date) -gt (Get-Date).Date.AddHours(8).AddMinutes(30) -and (Get-Date) -lt (Get-Date).Date.AddHours(12)) { Log "OPERATOR CHECK: hold $Tag still open at 08:30; lease still held"; $wRemind = $true }   # WRAPPER
    if ((Test-Path -LiteralPath $hf) -and (Get-Item -LiteralPath $hf).LastWriteTime -ge $t0) {   # WRAPPER
      $tok = ("$(Get-Content -LiteralPath $hf -TotalCount 1)".Trim() -split '\s+')[0]   # WRAPPER
      if ($tok -cin $ok) { Log "WRAPPER: hold $Tag token $tok"; return $tok } }   # WRAPPER
    Start-Sleep -Seconds 30 } }   # WRAPPER
function Invoke-SectionR {   # WRAPPER opens the function around the verbatim §R block
# ---- WRAPPER Block 4. §R rollback (verbatim)
Log 'ROLLBACK start'
$global:ReleaseOnNoGo = $false
function Test-Interp([string]$Exe, [string]$Tag) { if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
  (Invoke-Native $Exe @('-c','import weather.operations.execution_tape_supervisor, weather.operations.capture_resource_gate') "$N\probe-$Tag") -eq 0 }
$StatusFile = @{ snapshot='loop_status.json'; clob='clob_loop_status.json'; obs='observation_trigger_status.json'; tape='execution_tape_status.json' }
function Resolve-StopPy([string]$Key) {
  $rec = $null
  try { $s = Get-Content -LiteralPath (Join-Path $P "data\snapshots\$($StatusFile[$Key])") -Raw | ConvertFrom-Json
        $cmd = @($s.managed_process.expected_command); if ($cmd.Count -gt 0 -and $cmd[0]) { $rec = ([string]$cmd[0]).Trim().Trim('"') } } catch {}
  if ($rec) {
    $cand = Join-Path (Split-Path -Parent $rec) 'python.exe'     # same-directory sibling of the recorded argv[0]
    if (Test-Interp $cand "rec-$Key") { Log "$Key stop interpreter $cand (recorded $rec)"; return $cand }
    Log "ESCALATE: $Key recorded $rec but $cand does not import weather; using the probe fallback" }
  foreach ($c in @(@("$Old\Scripts\python.exe",'old'), @("$P\venv\Scripts\python.exe",'new'))) {
    if (Test-Interp $c[0] "$Key-$($c[1])") { Log "$Key stop interpreter $($c[0]) (probe fallback)"; return $c[0] } }
  Log "ESCALATE: no interpreter for $Key"; return $null }
$X = @{}; foreach ($sk in 'snapshot','clob','obs','tape') { $X[$sk] = Resolve-StopPy $sk }
$X.gate = @($X.snapshot, $X.clob, $X.obs, $X.tape | Where-Object { $_ })[0]     # the gate has no provenance check; any importable interpreter will do
$X | ConvertTo-Json | Set-Content "$N\rollback-interpreters.json" -Encoding utf8
Quiesce-Aux $X.tape -Soft         # idempotent: shadow STOP file, disable aux tasks, tape stop (already-stopped is fine), 88a stop (Q12)
if (-not $X.gate) { Log 'ESCALATE: no importable interpreter; capture stop verbs skipped, the holder sweep decides' }
elseif (-not (Stop-Capture $X -Soft)) { Log 'ESCALATE: capture stop not confirmed in 600 s; continuing to the swap-back' }
if (Test-Path -LiteralPath "$P\venv") { if (-not (Rename-WithSweep "$P\venv" 'venv-cp3119-failed' 'r1')) { NoGo 'ROLLBACK: new venv still held - ESCALATE (holders file in $N); lease kept, see below' } }
if (-not (Rename-WithSweep $Old 'venv' 'r2')) { NoGo 'ROLLBACK: venv-cp3110 cannot be renamed back - ESCALATE (holders file in $N); lease kept, see below' }
if ((& "$P\venv\Scripts\python.exe" -VV) -notlike 'Python 3.11.0*') { Log 'ESCALATE: venv not 3.11.0' }
if (Compare-Object (Mask-Editable (Get-Content "$A\freeze-3110.txt")) (Mask-Editable (& "$P\venv\Scripts\python.exe" -m pip freeze --all))) { Log 'ESCALATE: freeze differs' }
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
$rb = Wait-Restore (Get-Date)
if ($rb) { Undo-Aux; Start-AuxHolders }
else { Log 'ESCALATE: capture not 3/3 - aux tasks (including any U6 export) left DISABLED' }
$rar = Get-ReleaseActive "$P\venv\Scripts\python.exe" "$N\rollback-active"; Assert-CaseA $rar 'rollback'
Release-Lease; Log 'ROLLBACK DONE'
}   # WRAPPER closes function Invoke-SectionR
function Invoke-WrapperRollback {   # WRAPPER runs §R in this session; never returns
  if ((Get-Date) -gt (Get-Date).Date.AddHours(2).AddMinutes(45)) { Log 'OPERATOR CHECK: §R is starting after its 02:45 start limit (runbook §R heading); running it anyway; escalate to the owner' }   # WRAPPER
  try { Invoke-SectionR }   # WRAPPER
  catch { $wRErr = $_.Exception.Message   # WRAPPER
    try { Log "OPERATOR CHECK: §R stopped: $wRErr - ESCALATE to the owner; the lease is kept (runbook §R 'Lease on an escalated §R')" } catch { Write-Host "§R stopped: $wRErr" }   # WRAPPER
    $null = Wait-OperatorHold 'R' $false   # WRAPPER
    Release-Lease; Log "lease state after release $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress) (must show Active = False)"   # WRAPPER
    Exit-Wrapper 4 }   # WRAPPER
  foreach ($wf in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') {   # WRAPPER read-only receipt for the rollback pass rule
    try { $wv = (Get-Content -LiteralPath (Join-Path $P "data\snapshots\$wf") -Raw | ConvertFrom-Json).runtime_identity.python_version; Log "after §R $wf python_version=$wv" } catch { Log "after §R $wf unreadable" } }   # WRAPPER
  Log 'OPERATOR CHECK: §R reached ROLLBACK DONE. Confirm the rollback pass rules (S4U 3/3, the three status files 3.11.0, aux tasks back in pre-state, case-A BLOCK) and review every ESCALATE line in night.log; if not 3/3 by 03:45 the 04:15 WeatherTrainingWindowRestore stays the net: record and message the owner (runbook §R "Escalation", owner 2026-10-19).'   # WRAPPER
  Exit-Wrapper 2 }   # WRAPPER

$WStep = 'header'   # WRAPPER
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

# ---- WRAPPER C0 re-run (read-only) to re-derive $q, $GapChoice, $Head, $ra0, $st0, $Exempt in this session; keep the GO-reviewed receipts first
$WStep = 'C0'   # WRAPPER
$WRev = Join-Path $R 'c0-go-reviewed'; New-Item -ItemType Directory -Force $WRev | Out-Null   # WRAPPER
foreach ($wf in 'c0-status.out.txt','c0-status-flags.txt','c0-next-runs.txt') { if (Test-Path -LiteralPath "$R\$wf") { Copy-Item -LiteralPath "$R\$wf" -Destination "$WRev\$wf" -Force } }   # WRAPPER
if (-not (Test-Path -LiteralPath "$WRev\c0-status-flags.txt")) { throw 'WRAPPER: the GO-reviewed c0-status-flags.txt is missing' }   # WRAPPER
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
Log "C0 complete (status.ps1 exit $st0) - awaiting owner GO"
# ---- WRAPPER post-C0 checks: the GO was given on the C0 run's HEAD, baseline and next-runs; anything new since then goes back to the owner (exit 4, nothing touched)
if ($Head -ne $WFlagHead) { Log "OPERATOR CHECK: HEAD $Head differs from the GO-reviewed C0 HEAD $WFlagHead (the roll verdict covered the latter); nothing touched"; Exit-Wrapper 4 }   # WRAPPER
$WBaseRev = @(Get-Content -LiteralPath "$WRev\c0-status-flags.txt" | Where-Object { $_ })   # WRAPPER
$WBaseAdded = @(Get-Content -LiteralPath "$R\c0-status-flags.txt" | Where-Object { $_ -and $WBaseRev -notcontains $_ })   # WRAPPER
if ($WBaseAdded.Count) { Log "OPERATOR CHECK: status flag(s) new since the GO review: $($WBaseAdded -join ' || '); nothing touched"; Exit-Wrapper 4 }   # WRAPPER
Copy-Item -LiteralPath "$WRev\c0-status-flags.txt" -Destination "$R\c0-status-flags.txt" -Force; Log 'WRAPPER: C8/C9c baseline restored to the GO-reviewed c0-status-flags.txt'   # WRAPPER
$WRunsRev = @(if (Test-Path -LiteralPath "$WRev\c0-next-runs.txt") { Get-Content -LiteralPath "$WRev\c0-next-runs.txt" | Where-Object { "$_".Trim() } | ForEach-Object { ("$_" -split ' next=')[0] } })   # WRAPPER
$WRootNames = @(Get-ScheduledTask -TaskPath '\' | ForEach-Object TaskName)   # WRAPPER (Fable r1 #2: only root-folder tasks; \Microsoft\Windows\* reschedule dynamically)
$WRunsAdded = @(if (Test-Path -LiteralPath "$R\c0-next-runs.txt") { Get-Content -LiteralPath "$R\c0-next-runs.txt" | Where-Object { "$_".Trim() } | ForEach-Object { ("$_" -split ' next=')[0] } | Where-Object { $WRunsRev -notcontains $_ } | Where-Object { $WRootNames -contains $_ } })   # WRAPPER
if ($WRunsAdded.Count) { Log "OPERATOR CHECK: task(s) due before 04:00 that the GO review did not see: $($WRunsAdded -join ', '); nothing touched"; Exit-Wrapper 4 }   # WRAPPER

# ---- WRAPPER C1. Lease and fresh receipts (verbatim)
$WStep = 'C1'   # WRAPPER
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

# ---- WRAPPER C2. Quiesce the auxiliary tasks and long-running holders (verbatim; its catch undoes and releases)
$WStep = 'C2'   # WRAPPER
$Sup = 'WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor'
$Holders = @('WeatherExecutionTapeSupervisor','WeatherMakerShadowRunner','WeatherMakerEvidenceCapture') + $FamilyTasks   # $FamilyTasks from C0
# Was this pre-state row enabled? The Enabled column (2026-10-22) is exact. A row without it (a pre-state recorded
# before that revision) keeps the old State rule, so the undo of an existing file is unchanged.
function Test-PrestateEnabled($Row) { if ($Row.PSObject.Properties['Enabled'] -and $Row.Enabled) { return $Row.Enabled -eq 'True' }; $Row.State -ne 'Disabled' }
function Undo-Aux { foreach ($row in Import-Csv "$N\aux-prestate.csv") { if (Test-PrestateEnabled $row) { Enable-ScheduledTask -TaskName $row.Task | Out-Null }
    elseif ($row.State -eq 'Running') { Log "ESCALATE: $($row.Task) was disabled but running at C2; left disabled and not restarted" } }
  if ($ShadowStop) { Remove-Item -LiteralPath $ShadowStop -ErrorAction SilentlyContinue } }
function Start-AuxHolders {   # restart the long-running holders that C2 stopped, only where their pre-state was enabled
  foreach ($tn in $Holders) { $row = Import-Csv "$N\aux-prestate.csv" -ErrorAction SilentlyContinue | Where-Object Task -eq $tn
    if ($row -and (Test-PrestateEnabled $row)) { Start-ScheduledTask -TaskName $tn; Log "started $tn" } } }
function Stop-Tape([string]$Exe) {
  # 'stop' exits 0 only when it stopped a live worker (execution_tape_supervisor.py:909-912). A worker that is
  # already gone returns authorization.process_gone=true / recorded_process_not_found (supervisor.py:1353-1361),
  # which supervisor.managed_stop_allows_start (supervisor.py:796-804) also treats as stopped.
  $base = "$N\tape-stop-$(Get-Date -Format HHmmss)"
  $tc = Invoke-Native $Exe @('-m','weather.operations.execution_tape_supervisor','stop') $base
  if ($tc -eq 0) { Log 'tape stopped'; return }
  try { $j = Get-Content -LiteralPath "$base.out.txt" -Raw | ConvertFrom-Json } catch { NoGo "tape stop exit $tc with unreadable output" }
  if ($j.authorization.process_gone -eq $true) { Log "tape already stopped ($($j.reason))"; return }
  if ($j.reason -eq 'status_pid_unknown') {
    $sc = Invoke-Native $Exe @('-m','weather.operations.execution_tape_supervisor','status','--stale-after-seconds','180') "$base-status"
    if ($sc -ne 0) { Log 'tape has no recorded PID and is not healthy: treated as stopped (the C4/§R holder sweep is the backstop)'; return } }
  NoGo "execution tape stop exit $tc reason $($j.reason)" }
function Invoke-QStep([string]$Name, [scriptblock]$Body, [bool]$Soft) {
  try { & $Body } catch { if ($Soft) { Log "ESCALATE: quiesce step '$Name' failed: $($_.Exception.Message); continuing" } else { throw } } }
function Quiesce-Aux([string]$Exe, [switch]$Soft) {
  $Aux = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })
  Invoke-QStep 'prestate' {
    if (-not (Test-Path -LiteralPath "$N\aux-prestate.csv")) {
      $Aux | ForEach-Object { $x = Get-ScheduledTask -TaskName $_; [pscustomobject]@{ Task=$_; State=[string]$x.State; Enabled=[string]$x.Settings.Enabled } } |   # throws on a wrong name; State 'Running' does not say enabled
        Export-Csv -LiteralPath "$N\aux-prestate.csv" -NoTypeInformation } } $Soft.IsPresent
  Invoke-QStep 'shadow' {   # STOP file only, never a kill
    if ($Aux -contains 'WeatherMakerShadowRunner') {
      if (-not $ShadowStop) { NoGo 'shadow stop-file path unknown' }
      New-Item -ItemType File -Force $ShadowStop | Out-Null
      $t0 = Get-Date; while ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running' -and ((Get-Date)-$t0).TotalSeconds -lt 180) { Start-Sleep 10 }
      if ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running') { NoGo 'shadow did not seal in 3 min' } } } $Soft.IsPresent
  # Verify the disable with Settings.Enabled, never State: a disabled task with a running instance (88a, the tape) keeps State 'Running' until the stop below (C2 NO-GO 2026-10-22).
  foreach ($tn in $Aux) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null
    if ((Get-ScheduledTask -TaskName $tn).Settings.Enabled -ne $false) { NoGo "disable $tn" } } $Soft.IsPresent }
  Invoke-QStep 'tape' { Stop-Tape $Exe } $Soft.IsPresent
  Invoke-QStep '88a' {   # only with the recorded owner choice (G8, Q12)
    if (((Get-Content -LiteralPath "$R\q12.txt" -TotalCount 1) -split '\s+')[0] -ne 'STOP_AUTHORIZED') { NoGo 'Q12 not STOP_AUTHORIZED' }
    if ([string](Get-ScheduledTask -TaskName WeatherMakerEvidenceCapture).State -eq 'Running') { Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture; Log '88a worker stopped (Q12)' }
    foreach ($ft in $FamilyTasks) {   # Q12b, asserted at C0; disabled above, so its one-minute trigger cannot restart it
      if ([string](Get-ScheduledTask -TaskName $ft).State -eq 'Running') { Stop-ScheduledTask -TaskName $ft; Log "$ft worker stopped (Q12b)" } } } $Soft.IsPresent
}
try { Quiesce-Aux $Py; Log 'C2 quiesced' }
catch { $msg = $_.Exception.Message; Log "C2 failed: $msg - undoing"
  if (Test-Path -LiteralPath "$N\aux-prestate.csv") { Undo-Aux; Start-AuxHolders }
  $global:ReleaseOnNoGo = $false; Release-Lease; throw }

# ---- WRAPPER C3. Stop the capture workers (verbatim function definitions)
$WStep = 'C3C4'; $msg = $null   # WRAPPER $msg is set again only by the C3+C4 guarded catch, so the outer catch can tell whether that undo already ran
# $Exe is one interpreter for everything (C3), or a hashtable with keys snapshot, clob, obs and gate (§R, per worker).
function Stop-Capture($Exe, [switch]$Soft) {
  $X = if ($Exe -is [hashtable]) { $Exe } else { @{ snapshot=$Exe; clob=$Exe; obs=$Exe; gate=$Exe } }
  foreach ($tn in $Sup) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null   # Settings.Enabled: a running supervisor keeps State 'Running'
    if ((Get-ScheduledTask -TaskName $tn).Settings.Enabled -ne $false) { NoGo "disable $tn" } } $Soft.IsPresent }
  $stamp = Get-Date -Format HHmmss; $script:c1 = $script:c2 = $script:c3 = 99
  Invoke-QStep 'stop snapshot' { $script:c1 = Invoke-Native $X.snapshot @('-m','weather.collection.snapshot_tracker','--stop') "$N\stop-snapshot-$stamp" } $Soft.IsPresent
  Invoke-QStep 'stop clob'     { $script:c2 = Invoke-Native $X.clob @('-m','weather.market.market_microstructure','stop') "$N\stop-clob-$stamp" } $Soft.IsPresent
  Invoke-QStep 'stop obs'      { $script:c3 = Invoke-Native $X.obs @('-m','weather.operations.observation_trigger','stop') "$N\stop-obs-$stamp" } $Soft.IsPresent
  $c1 = $script:c1; $c2 = $script:c2; $c3 = $script:c3
  if ($c1 -or $c2 -or $c3) { Log "stop verb exits $c1/$c2/$c3"; if (-not $Soft) { return $false } }
  $t0 = Get-Date
  while (((Get-Date)-$t0).TotalSeconds -lt 600) {
    $g = Invoke-Native $X.gate @('-m','weather.operations.capture_resource_gate','--workload','py3119_cutover_stop_confirmation','--capture-mode','no_live_capture',
          '--min-free-memory-bytes','0','--min-free-disk-bytes','0','--no-write','--fail-on-block') "$N\gate-$stamp"
    if ($g -eq 0) { return $true }; Start-Sleep 5 }
  return $false }
function Wait-Restore([datetime]$Since) {   # S4U restore; the task limit is 15 min (register_training_window.ps1:153): one run plus one rerun
  Start-ScheduledTask -TaskName WeatherTrainingWindowRestore; $t0 = Get-Date; $rerun = $false
  while (((Get-Date)-$t0).TotalMinutes -lt 32) { Start-Sleep 20
    $st = Get-Content -LiteralPath (Join-Path $P 'data\logs\training_window_status.json') -Raw | ConvertFrom-Json
    $fresh = [datetimeoffset]$st.updated_at -gt [datetimeoffset]$Since
    if ($fresh -and $st.phase -eq 'restore_only' -and $st.outcome -eq 'capture_recovery_pass') { return $true }
    if ([string](Get-ScheduledTask WeatherTrainingWindowRestore).State -ne 'Running' -and ($fresh -or ((Get-Date)-$t0).TotalMinutes -ge 16)) {
      if ($rerun) { return $false }; $rerun = $true; Log 'restore did not pass; one rerun'; $Since = Get-Date; Start-ScheduledTask -TaskName WeatherTrainingWindowRestore } }
  return $false }
function Undo-Stop {   # pre-rename undo: the venv is still the intact 3.11.0
  foreach ($tn in $Sup) { Invoke-QStep "enable $tn" { Enable-ScheduledTask -TaskName $tn | Out-Null } $true }
  $ok = Wait-Restore (Get-Date); Invoke-QStep 'undo aux' { Undo-Aux; Start-AuxHolders } $true
  if ($ok) { Log 'undo: capture 3/3, aux tasks restored' } else { Log 'ESCALATE: undo restore did not report capture_recovery_pass' } }

# ---- WRAPPER C4. Sweep and rename (verbatim; the C3 + C4 guarded block undoes and releases on a pre-rename failure)
$OldHomeNorm = (Get-Content "$R\oldhome.txt").Trim().TrimEnd('\'); $NewHomeNorm = $NewHome.TrimEnd('\')
function Get-VenvHolders([string]$Dir) {
  # Anchored with a trailing backslash, so a sibling worktree such as <checkout>-<name>\venv never matches.
  # The base-interpreter clause catches child processes of either home that name the production checkout.
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $_.ExecutablePath -like "$Dir\*" -or $_.CommandLine -like "*$Dir\*" -or
    (($_.ExecutablePath -like "$OldHomeNorm\*" -or $_.ExecutablePath -like "$NewHomeNorm\*") -and $_.CommandLine -like "*$P\*") } |
    Select-Object ProcessId, ParentProcessId, ExecutablePath, CommandLine }
function Rename-WithSweep([string]$From, [string]$To, [string]$Tag) {
  for ($i = 1; $i -le 3; $i++) {
    $hold = Get-VenvHolders $From; $hold | Format-List | Out-File "$N\holders-$Tag-try$i.txt"
    if ($hold) { Log "$Tag try $i holders $(($hold.ProcessId) -join ',')"; Start-Sleep 20; continue }
    try { Rename-Item -LiteralPath $From -NewName $To -ErrorAction Stop; return $true } catch { Log "$Tag rename try $i failed: $($_.Exception.Message)"; Start-Sleep 20 } }
  return $false }
# C3 + C4 guarded block. NoGo must not release the lease before the undo has run, so the catch releases it itself.
$global:ReleaseOnNoGo = $false
try {
  if (-not (Stop-Capture $Py)) { NoGo 'C3 stop not confirmed' }
  $GapStart = Get-Date; Log 'C3 capture stopped'
  if ((Get-Date) -gt (Get-Date).Date.AddHours(1).AddMinutes(30)) { NoGo 'swap deadline 01:30 passed' }
  if (-not (Rename-WithSweep (Join-Path $P 'venv') 'venv-cp3110' 'c4')) { NoGo 'C4 rename failed' }
} catch {
  $msg = $_.Exception.Message; Log "C3/C4 failed before the rename: $msg - undo, no swap"
  try { Undo-Stop } finally { Release-Lease }
  throw }
Log 'C4 renamed'                  # from here on a failure means §R, which keeps the lease

# ---- WRAPPER C5. Build the new venv offline (verbatim; any failure from here = §R)
$WStep = 'C5'   # WRAPPER
& $NewPy -I -m venv (Join-Path $P 'venv'); if ($LASTEXITCODE) { NoGo 'venv create -> ROLLBACK' }
Build-Venv $Py $P

# ---- WRAPPER C6. Quick verify (verbatim)
$WStep = 'C6'   # WRAPPER
Test-Venv $Py $P 'prod'      # includes the import-location check: weather and maker_core must import from $P\src
foreach ($ln in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$ln")) -ne $K.binaries."Lib\venv\scripts\nt\$ln") { NoGo "launcher $ln -> ROLLBACK" } }
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$N\pth-3119.txt" -Encoding utf8     # receipt only; the import-location check is the pass rule
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }

# ---- WRAPPER C7. Restore the capture workers through the S4U path (verbatim)
$WStep = 'C7'   # WRAPPER
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
if (-not (Wait-Restore $GapStart)) { NoGo 'C7 not recovered -> ROLLBACK' }
$GapEnd = Get-Date; Log ("C7 3/3; gap {0:n1} min" -f ($GapEnd-$GapStart).TotalMinutes)

# ---- WRAPPER C8. Core verify (verbatim)
$WStep = 'C8'   # WRAPPER
# a) the workers run 3.11.9
foreach ($f in 'loop_status.json','clob_loop_status.json','observation_trigger_status.json') {
  $v = (Get-Content -LiteralPath (Join-Path $P "data\snapshots\$f") -Raw | ConvertFrom-Json).runtime_identity.python_version
  Log "$f python_version=$v"; if ($v -ne '3.11.9') { NoGo "$f $v -> ROLLBACK" } }
# c) release readiness: still case A
$ra1 = Get-ReleaseActive $Py "$N\release-active-3119"; Assert-CaseA $ra1 'C8'
if ($ra1.status -ne $ra0.status -or $ra1.error -ne $ra0.error) { NoGo 'release active fields changed across the swap -> ROLLBACK' }
# d) host status
$st1 = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-core"
$new1 = Get-NewStatusFlags "$N\status-core" "$R\c0-status-flags.txt" 'C8'   # judged below; aux flags are expected until C9b
# e) native-library receipt, old and new
$null = Invoke-Native $Py @('-I','-c','import ssl, sqlite3, zlib, pyexpat; print(ssl.OPENSSL_VERSION); print(sqlite3.sqlite_version); print(zlib.ZLIB_RUNTIME_VERSION); print(pyexpat.EXPAT_VERSION)') "$N\native-3119"
# ---- WRAPPER C8 (d) judgement: a new flag naming an aux task (aux-tasks.txt, the C2 holders, or the execution tape) is expected until C9b; anything else goes to the operator
$WAuxKeys = @(@(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { "$_".Trim() } | ForEach-Object { "$_".Trim() }) + $Holders + 'execution-tape','health watchdog','MAKER_EVIDENCE' | ForEach-Object { ([string]$_ -replace '[0-9a-fA-F]{64}','<sha>') -replace '\d+(\.\d+)?','#' })   # WRAPPER same masking as Get-StatusFlagKeys
$WNonAux = @(@($new1 | Where-Object { $_ }) | Where-Object { $wk = [string]$_; @($WAuxKeys | Where-Object { $wk.IndexOf([string]$_, [StringComparison]::OrdinalIgnoreCase) -ge 0 }).Count -eq 0 })   # WRAPPER
if ($WNonAux.Count) {   # WRAPPER
  Log "OPERATOR CHECK: C8 (d) new non-aux flag(s) vs the C0 baseline: $($WNonAux -join ' || '). Runbook: a new capture flag is a fail (-> §R); see $N\status-core.new-flags.txt"   # WRAPPER
  if ((Wait-OperatorDecision 'c8' @('CONTINUE','ROLLBACK') (([datetime[]]@((Get-Date).Date.AddHours(2).AddMinutes(15), (Get-Date).AddMinutes(5)) | Sort-Object)[-1]) 'ROLLBACK') -ne 'CONTINUE') { throw 'WRAPPER: C8 (d) not passed -> ROLLBACK' } }   # WRAPPER
else { Log "WRAPPER: C8 (d) new flags are aux-only ($(@($new1 | Where-Object { $_ }).Count)); C8 green" }   # WRAPPER

# ---- WRAPPER C9. Core decision (verbatim)
$WStep = 'C9'   # WRAPPER
$GapMin = ($GapEnd-$GapStart).TotalMinutes
if ($GapMin -gt 35) {
  Log ("gap {0:n1} min over 35; recorded choice {1}" -f $GapMin, $GapChoice)
  if ($GapChoice -eq 'ROLLBACK_ON_OVERRUN') { NoGo 'capture gap overran and the owner chose rollback -> ROLLBACK' } }
Log 'C9 core PASS'

# ---- WRAPPER C9b. Restore the auxiliary tasks (verbatim)
$WStep = 'C9b'   # WRAPPER
Undo-Aux; Start-AuxHolders
$AuxRestart = Get-Date
if (@(Import-Csv "$N\aux-prestate.csv" | Where-Object { $_.Task -eq 'WeatherHostHealthWatchdog' -and $_.State -ne 'Disabled' }).Count) { Start-ScheduledTask -TaskName WeatherHostHealthWatchdog }   # WRAPPER Fable 10-20 #4 fresh watchdog before C9c

# ---- WRAPPER C9c. Aux verify (verbatim)
$WStep = 'C9c'   # WRAPPER
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
# ---- WRAPPER C9c judgement against the runbook's Go/no-go C9c list; shadow and 88a are polled until 10 min after $AuxRestart ("within 10 minutes")
$WIssues = New-Object System.Collections.Generic.List[string]   # WRAPPER
$WPre = @(Import-Csv -LiteralPath "$N\aux-prestate.csv")   # WRAPPER
if ($tapeWanted) {   # WRAPPER tape: health RUNNING = identity current + evidence_integrity PASS + CONNECTED (execution_tape_supervisor.py:405-423)
  $wtf = @(Get-ChildItem -LiteralPath $N -Filter 'tape-status-*.out.txt' | Sort-Object LastWriteTime)[-1]   # WRAPPER
  $wth = $null; try { $wth = (Get-Content -LiteralPath $wtf.FullName -Raw | ConvertFrom-Json).health } catch {}   # WRAPPER
  if (-not $wth -or [string]$wth.state -ne 'RUNNING' -or $wth.runtime_identity_matches_current -ne $true -or [string]$wth.evidence_integrity -ne 'PASS' -or [string]$wth.capture_state -ne 'CONNECTED') {   # WRAPPER
    $WIssues.Add("tape health in $($wtf.Name): $($wth | Select-Object state, runtime_identity_matches_current, evidence_integrity, capture_state, detail | ConvertTo-Json -Compress)") } }   # WRAPPER
else { Log 'WRAPPER: tape pre-state Disabled; tape not checked' }   # WRAPPER
$WShadowWanted = @($WPre | Where-Object { $_.Task -eq 'WeatherMakerShadowRunner' -and $_.State -ne 'Disabled' }).Count -gt 0   # WRAPPER
$W88aRow = @($WPre | Where-Object { $_.Task -eq 'WeatherMakerEvidenceCapture' })   # WRAPPER
if (-not $W88aRow.Count) { $WIssues.Add('88a (WeatherMakerEvidenceCapture) is not in aux-prestate.csv, so C9b did not restart it; judge 88a by eye') }   # WRAPPER
$W88aWanted = @($W88aRow | Where-Object { $_.State -ne 'Disabled' }).Count -gt 0   # WRAPPER
if ($FamilyTasks.Count) { $WIssues.Add("capture-family task(s) $($FamilyTasks -join ',') registered: this wrapper does not judge the runbook C9c capture-family bullet; judge by eye") }   # WRAPPER fail-closed to the operator (41e3bec62 C9c family bullet)
$WUntil = $AuxRestart.AddMinutes(10)   # WRAPPER
do { $WPend = @()   # WRAPPER
  if ($WShadowWanted) {   # WRAPPER shadow: running again, STOP file gone
    if ($ShadowStop -and (Test-Path -LiteralPath $ShadowStop)) { $WPend += "shadow STOP file still present: $ShadowStop" }   # WRAPPER
    if ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -ne 'Running') { $WPend += 'shadow task is not Running' } }   # WRAPPER
  if ($W88aWanted) {   # WRAPPER 88a: updated after $AuxRestart, state CAPTURING or NO_ELIGIBLE_BANDS, no last_error
    try { $wm = Get-Content -LiteralPath (Join-Path $P 'data\maker_evidence\status.json') -Raw | ConvertFrom-Json   # WRAPPER
      if (-not $wm.updated_at_utc -or [datetimeoffset]$wm.updated_at_utc -le [datetimeoffset]$AuxRestart) { $WPend += "88a status not updated since the aux restart (updated $($wm.updated_at_utc))" }   # WRAPPER
      if ([string]$wm.state -notin 'CAPTURING','NO_ELIGIBLE_BANDS') { $WPend += "88a state $($wm.state)" }   # WRAPPER
      if ("$($wm.last_error)".Trim()) { $WPend += "88a last_error: $($wm.last_error) (a journal/store error = no rollback, escalate)" } }   # WRAPPER
    catch { $WPend += "88a status.json unreadable: $($_.Exception.Message)" } }   # WRAPPER
  if (-not $WPend.Count) { break }; Start-Sleep -Seconds 20   # WRAPPER
} while ((Get-Date) -lt $WUntil)   # WRAPPER
foreach ($wi in $WPend) { $WIssues.Add($wi) }   # WRAPPER
$WNew2 = @($new2 | Where-Object { $_ })   # WRAPPER
if ($WNew2.Count) {   # WRAPPER one re-read after the 10-minute settle, through the same helpers and baseline
  $null = Invoke-Native 'powershell.exe' @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $P 'scripts\ops\status.ps1'),'-Json') "$N\status-full-recheck"   # WRAPPER
  $WNew2 = @(Get-NewStatusFlags "$N\status-full-recheck" "$R\c0-status-flags.txt" 'C9c-recheck' | Where-Object { $_ }) }   # WRAPPER
if ($WNew2.Count) { $WIssues.Add("new status flag(s) vs the C0 baseline: $($WNew2 -join ' || ')") }   # WRAPPER
if ($WIssues.Count) {   # WRAPPER
  Log "OPERATOR CHECK: C9c not clean: $($WIssues -join ' ; '). Runbook: a tape or shadow import/runtime error on the new venv -> ROLLBACK (start by 02:45); an 88a journal/store error -> NO rollback, never delete or rewrite a journal, record and escalate to the owner."   # WRAPPER
  $WDec = Wait-OperatorDecision 'c9c' @('CONTINUE','ROLLBACK','HOLD') ((Get-Date).Date.AddHours(2).AddMinutes(45)) 'HOLD'   # WRAPPER
  if ($WDec -eq 'ROLLBACK') { throw 'WRAPPER: C9c operator decision -> ROLLBACK' }   # WRAPPER
  if ($WDec -eq 'HOLD') { throw 'WRAPPER: C9c HOLD (no rollback; lease kept for the operator)' } }   # WRAPPER
else { Log 'WRAPPER: C9c all pass (tape RUNNING with current identity, integrity PASS, CONNECTED; shadow running, STOP file gone; 88a fresh; no new flag)' }   # WRAPPER

# ---- WRAPPER C10. Close-out (verbatim)
$WStep = 'C10'   # WRAPPER
@{ result='PASS'; head=$Head; gap_minutes=[math]::Round(($GapEnd-$GapStart).TotalMinutes,1); old_venv=$Old; new_home=$NewHome; release_case='A'; at=(Get-Date).ToString('o') } |
  ConvertTo-Json | Set-Content "$N\cutover-receipt.json" -Encoding utf8
Release-Lease; Log 'CUTOVER PASS'
Log 'PHASE-C DONE (exit 0). OPERATOR CHECK: keep venv-cp3110, the old-home freeze copy, the 3.11.0 install, every 3.11.0 release manifest and $R for at least 14 days.'   # WRAPPER
} catch {   # WRAPPER the whole catch block is wrapper code
  $WErr = $_.Exception.Message   # WRAPPER
  Write-Host "PHASE-C STOPPED at ${WStep}: $WErr"; try { Log "PHASE-C STOPPED at ${WStep}: $WErr" } catch {}   # WRAPPER
  # WRAPPER Rename evidence: C0 NO-GOes if $Old exists (raw line 260) and only the C4 rename creates it (raw line 431), so from C3C4 on Test-Path $Old = renamed.
  $WRenamed = ($WStep -in 'C3C4','C5','C6','C7','C8','C9','C9b','C9c','C10') -and $Old -and (Test-Path -LiteralPath $Old)   # WRAPPER
  if (-not $WRenamed) {   # WRAPPER before the rename: undo with no swap (raw lines 247-248); C2's catch and the C3+C4 guarded catch already undo and release
    if ($WStep -eq 'C3C4' -and -not $msg -and $global:Lease) {   # WRAPPER C2 finished but the throw came outside the guarded try, so no runbook undo ran
      try { Log 'WRAPPER: failure after C2 and outside the C3+C4 guarded try - undo with no swap'   # WRAPPER
        if (Get-Command Undo-Stop -ErrorAction SilentlyContinue) { Undo-Stop } else { Undo-Aux; Start-AuxHolders } }   # WRAPPER
      catch { try { Log "ESCALATE: wrapper undo failed: $($_.Exception.Message)" } catch {} } }   # WRAPPER
    try { $global:ReleaseOnNoGo = $false; Release-Lease } catch { Write-Host "Release-Lease failed: $($_.Exception.Message)" }   # WRAPPER
    try { Log 'OPERATOR CHECK: stopped before the C4 rename; nothing swapped. Check night.log for ESCALATE lines and the undo restore result.' } catch {}   # WRAPPER
    Exit-Wrapper 1 }   # WRAPPER
  # WRAPPER After the rename. C5..C9 (and C3C4 after the rename): "Fail = §R". C9b/C9c/C10: §R only on a "-> ROLLBACK" failure; anything else is the operator's call.
  if ($WStep -in 'C9b','C9c','C10' -and $WErr -notlike '*-> ROLLBACK*') {   # WRAPPER
    if ((Wait-OperatorHold $WStep $true) -eq 'RELEASE') {   # WRAPPER
      Release-Lease; Log "lease state after release $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P) | ConvertTo-Json -Compress) (must show Active = False)"   # WRAPPER
      Exit-Wrapper 4 } }   # WRAPPER
  Invoke-WrapperRollback   # WRAPPER runs §R in this session; exits 2 (ROLLBACK DONE) or 4 (escalated, lease held until RELEASE)
}   # WRAPPER
Exit-Wrapper 0   # WRAPPER
