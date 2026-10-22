# Phase C (Python 3.11.9 venv cutover), 00:30 on Thu 2026-10-22 (night of 10-21 to 10-22, capture host)

Generated from `docs/operations/HOST_PYTHON_UPGRADE_RUNBOOK.md` at the fixed review tip
`41e3bec626954e05b73331079fd111e1c9379436` (branch `origin/claude/pyup-c-1021-review-20261019`; file sha256
`FE074EE48EE564F9461F8615E5F3CD56FCB01024490D86B2147B9327C4361759`, 1547 lines), read with `git show`, together with
`docs/operations/pyup-c-1021-delta-review.md` at the same tip. Generated read-only on 2026-10-20 (workstation-side kit
prep; nothing was run against the night). The section 6 header, the B1c `Build-Venv` and B1d `Test-Venv` function
definitions, Phase C (C0 to C10), §R (including its new "Escalation" paragraph) and the referenced gate, question and
§7a rows are copied verbatim, with only the host values listed below filled in. If the runbook that is on master on the
night differs from this file, the runbook wins: regenerate this file. Changes against the 10-17 raw are listed in the
final section "Delta vs 20261017 raw".

**This kit is ahead of master's runbook by the C2 fix on claude/pyup-c2-enabled-check-20261022; until that lands, do NOT regenerate from master's runbook.**

**Launch form (as run on 10-21/22):** the wrappers run as FILES, elevated, with no redirects, from local copies under
`C:\pyup\cp3119`: `Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File <wrapper>'`.

**Not yet on master.** At generation time `41e3bec62` is a review branch tip, not an ancestor of master
`6aac6de81`. The Phase C *code* that the 20261022 wrappers run is taken from `41e3bec62`; if the branch lands changed,
regenerate.

**Phase B outcome this rests on:** `C:\pyup\cp3119\qualification.json` `result=PASS`, `release_case=A`,
`tip=90b2e1844ad0de71916c67996026dea7b04ce5ff` (branch `py3119-qual-20261016`). Unchanged since the 10-17 raw.
Owner choices on file (first lines read 2026-10-20): `q12.txt` = `STOP_AUTHORIZED DECISION_LOG 2026-10-12 (...)`,
`gap-overrun.txt` = `ACCEPT_OVERRUN DECISION_LOG 2026-10-12 (...)`. Owner rulings for this night (delta review §4b,
§7; runbook G4, §R "Escalation", §11): cutover C = 00:30 Thu 10-22 on pre-N12 master ("Keep Python 10-21/22
(Recommended)", 2026-10-20); escalation = "Auto net, you in the morning (Recommended)" (2026-10-19); MG-1 and the
10-22 gap = "Test's own rule decides (Recommended)" (2026-10-19).

## Expected head and G3 (fill on the night)

| Value | Fill | Note |
| --- | --- | --- |
| `<EXPECTED_HEAD>` | **FILLED 2026-10-22 00:07 (master-agent): `41119c42eaace44a9d0308428e05023b5f0b3cc4`** = local drift commit on master 1c19ae10b (2 fleet config files). G3 `roll_verdict -Branch 41119c42e -Base 90b2e1844` = ROLL-FREE exit 0 (44 files, 1 importable, free). (Was: master `6aac6de81a25bd939b954c5e7f29db02b2fd2fee`.) | If master lands a docs-only change on Wed 10-21, the expected head is that new master sha. Whichever it is, it must be the HEAD C0 logs (`session start ... head=`), the `head=` in `c0-done-20261022.flag`, and the `-Branch` of the G3 call below. |
| G3 base (qualified tip) | `90b2e1844ad0de71916c67996026dea7b04ce5ff` | Ancestor of `6aac6de81` (checked 2026-10-20 with `git merge-base --is-ancestor`). |
| G3 call (master runs it on the host before GO; C0 names it in its log) | `scripts\ops\roll_verdict.ps1 -Branch <EXPECTED_HEAD> -Base 90b2e1844ad0de71916c67996026dea7b04ce5ff` | Must exit 0 (ROLL-FREE). Exit 3 or 1 fails G3. Delta review §4b expects ROLL-FREE (no pin, no loop-closure change from `90b2e1844` to `6aac6de81`). |

## Timetable (runbook Phase C table and §10)

| Clock (local) | Step | Hard stop |
| --- | --- | --- |
| 00:30-00:55 | C0 GO checks | Any fail = NO-GO, nothing touched |
| (after C0) | **Owner types GO** (in chat; G4) | No GO = stop; nothing touched |
| 01:00, latest 01:15 | C1 lease and receipts | No lease by 01:15 = NO-GO |
| +5 min | C2 quiesce aux tasks and holders | Any throw = `Undo-Aux`, NO-GO |
| +5-10 min | C3 stop capture workers | Still active after 600 s = undo, restore, NO-GO |
| by 01:30 | C4 rename `venv` to `venv-cp3110` | Fails 3 times or past 01:30 = undo, restore, NO-GO |
| +3 min | C5 build new venv offline | Fail = §R |
| +2 min | C6 quick verify | Fail = §R |
| +5-32 min | C7 S4U restore of the 3 capture workers | Not 3/3 after one rerun = §R |
| +5 min | C8 core verify | Fail = §R |
| core by 02:15; aux by 02:25 | C9 core decision; C9b restore aux; C9c aux verify | Core not passed = §R; aux per C9c |
| start by 02:45, done by 03:45 | §R rollback (worst case about 50 min) | Not 3/3 by 03:45: the 04:15 restore is the net; record and message the owner (§R, "Escalation") |

## Paste order (one elevated Windows PowerShell 5.1 window; nothing tails `night.log`)

0. **Before 00:30 (prerequisites, not runbook blocks):** `$R\aux-tasks.txt`, `$R\q12.txt` and `$R\gap-overrun.txt`
   exist (all three present on 2026-10-20). Per delta review §5 item 4, re-take §4 H3 and rebuild `aux-tasks.txt`
   before C0 (the file on disk is dated 2026-10-16 21:08). `$R\q12b.txt` is needed only if a
   `WeatherMakerEvidence<Family>` task is registered (none on 2026-10-20: the only `WeatherMakerEvidence*` task is
   `WeatherMakerEvidenceCapture`, which C0 excludes). Run the G3 call above and keep its output for the GO review.
1. Block 1, the section 6 header (host values filled). Expect `session start host=<capture host> head=<40-hex>`;
   the 40-hex must equal `<EXPECTED_HEAD>`.
2. Block 2, the `Build-Venv` and `Test-Venv` function definitions only (C5 requires them in this session; do NOT
   paste the B1c/B1d calls).
3. C0 (00:30-00:55). It now also logs `capture-family tasks: <list>` and, with a family task registered, asserts Q12b
   and `aux-tasks.txt` membership. It ends with `C0 complete (status.ps1 exit N) - awaiting owner GO`.
4. **Owner GO point.** Master reviews `c0-status.out.txt`, `c0-status-flags.txt`, `c0-next-runs.txt` (must be empty),
   G3 (the `roll_verdict.ps1` exit 0 above)/G5 (including: no host replay or research batch running or holding the
   lease; the lever-5 Toronto replay of 10-20/21 must have ended)/G7/G8/G11; the owner types GO.
5. C1 (at 01:00), then C2, C3 (functions), C4 (the guarded C3+C4 block), C5, C6, C7, C8, C9, C9b, C9c, C10, one block
   at a time, checking each go/no-go. C2 and §R read `$FamilyTasks`, which C0 assigns: they must run in the same
   session as C0.
6. On any NO-GO from C5 onward (`-> ROLLBACK`), or a C9/C9c rollback outcome: paste §R in the same session. Start by
   02:45. If §R escalates: the owner's ruling for this night applies (§R "Escalation", Block 4).

## Placeholders and host values filled

| Value | Filled with | Source |
| --- | --- | --- |
| `$P` | `C:\Users\micha\Desktop\github\weather` | unchanged from the 10-17 raw; equals `$R\paths.json` `P` |
| `$R` | `C:\pyup\cp3119` | unchanged; equals `paths.json` `R` |
| `$NewHome` | `C:\Program Files\Python311-cp3119` | unchanged; equals `paths.json` `NewHome` |
| `$Stage` | `Join-Path (Split-Path -Parent $P) 'weather-py3119-stage'` | unchanged (Phase B's stage; Phase C does not use it) |
| `$OldHome` | not filled; read from `$R\oldhome.txt` by the header | runbook (file present 2026-10-20) |
| `$K` | not filled; read from `$R\constants.json` by the header | runbook (file present 2026-10-20) |
| `<EXPECTED_HEAD>` | placeholder (see above) | not part of any runbook block; used by the GO review and G3 only |

No other line is changed. Phase C itself has no `<...>` placeholders.

## Block 1. Section 6 header (runbook §6, host values filled)

```powershell
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
```

The two dot-sourced scripts define `Enter-WeatherHeavyWorkloadLease` (`workload_admission.ps1:1620`),
`Exit-WeatherHeavyWorkloadLease` (`:2279`), `Get-WeatherHeavyWorkloadLeaseState` (`:2352`) and
`Read-WeatherMemoryGuardStatus` (`memory_guard_status_reader.ps1:13`), checked at this HEAD.

Runbook trap reminders (§6, verbatim):
- there is no `&&`;
- use `-LiteralPath`;
- never append `2>$null` to native `git`;
- never run a recursive listing of `data\`;
- track and terminate every process you start;
- an agent session runs in Windows session 0, so any window it starts (an installer, a UAC prompt) is invisible. A step that needs the owner to click runs in the owner's own elevated window (seen on the host, 2026-10-13);
- a value one phase assigns is `$null` in the fresh session of a later night: read it from the file that phase wrote
  (the §6 header reads `oldhome.txt`), never from a variable set earlier (found in review 2026-10-13);
- PowerShell variable names ignore case, and `foreach` and `ForEach-Object` assign in the session scope: a loop variable `$k`, `$p`, `$a` or `$r` overwrites `$K`, `$P`, `$A` or `$R`. Never reuse a session constant's name for a loop variable (a `foreach ($k ...)` in C6 would have rolled back every cutover; found in review 2026-10-13);
- never follow `night.log` with a tailing reader (`Get-Content -Wait`, `tail -F`): it can hold the file so that `Log`'s `Add-Content` fails and stops the phase. Read snapshots instead (seen on the host, 2026-10-13).

Plain `& $exe ...; if ($LASTEXITCODE)` calls with no stderr redirection are safe under `Stop`.

`Enter-WeatherHeavyWorkloadLease` returns `$null` when the lease is busy and throws outside
00:30-09:00. Keep a whole phase in one PowerShell process, and release the lease on every exit path.
`NoGo` does that while `$global:ReleaseOnNoGo` is set. If any other command throws in a leased
step, run `Release-Lease` before you leave the session. The one exception is after the C4 rename,
where §R needs the lease.

## Block 2. `Build-Venv` (B1c) and `Test-Venv` (B1d) function definitions only

Runbook C5: "The C session is fresh: before C5, define `Build-Venv` (B1c) and `Test-Venv` (B1d) in it by pasting
those two function definitions only, not the B1c and B1d calls." Extracted verbatim from the B1c and B1d fences.

```powershell
function Build-Venv($vpy, $root) {
  Select-String -LiteralPath "$R\lock-hashed.txt" -Pattern '^(pip|setuptools|wheel)==' | ForEach-Object Line | Set-Content "$R\lock-tools-hashed.txt" -Encoding ascii
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-tools-hashed.txt"; if ($LASTEXITCODE) { NoGo 'tools install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --require-hashes --no-deps -r "$R\lock-hashed.txt";       if ($LASTEXITCODE) { NoGo 'lock install' }
  & $vpy -I -m pip install --isolated --no-index --find-links $WH --no-deps -e $root;                                    if ($LASTEXITCODE) { NoGo 'editable install' }
}
```

```powershell
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
```

## Block 3. Phase C, verbatim from the runbook (41e3bec62 lines 938-1297)

### Phase C. Cutover night

| Clock (local) | Step | Hard stop |
| --- | --- | --- |
| 00:30-00:55 | C0 GO checks | Any fail = NO-GO, nothing touched |
| 01:00, latest 01:15 | C1 lease and receipts | No lease by 01:15 = NO-GO |
| +5 min | C2 quiesce the auxiliary tasks and long-running holders | Any throw = `Undo-Aux`, NO-GO |
| +5-10 min | C3 stop the capture workers | Still active after 600 s = undo, restore, NO-GO |
| by 01:30 | C4 rename `venv` to `venv-cp3110` | Rename fails 3 times or it is past 01:30 = undo, restore, NO-GO |
| +3 min | C5 build the new `venv` offline | Fail = §R |
| +2 min | C6 quick verify | Fail = §R |
| +5-32 min | C7 S4U restore of the three capture workers only | Not 3/3 after one rerun = §R |
| +5 min | C8 core verify | Fail = §R |
| by 02:15; aux by 02:25 | C9 core PASS decision; C9b restore the aux tasks; C9c aux verify | Core not passed = §R; aux failure per C9c |
| start by 02:45, done by 03:45 | §R rollback (worst case about 50 min) | Not 3/3 by 03:45: the 04:15 restore is the net; record and message the owner (§R, "Escalation") |

This sits inside the 01:00-04:00 quiet window and ends before the 04:15 `WeatherTrainingWindowRestore`
trigger, which stays armed as the final safety net. The expected capture gap (C3 to C7) is about
20-35 minutes. The auxiliary tasks (tape, shadow, 88a and the rest) stay quiesced until C9b, so
§R never has to stop processes running on the new venv except the three capture workers. §R still
re-runs the quiesce to be safe.

A failure before the C4 rename means **undo with no swap**: re-enable what C2 and C3 disabled, then
start the S4U restore. A failure after the rename means §R.

**C0. GO checks.**

```powershell
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
$auxNames = @(Get-Content -LiteralPath "$R\aux-tasks.txt" | Where-Object { $_.Trim() })   # the aux list exactly as C2's Quiesce-Aux reads it
foreach ($auxName in $auxNames) { $null = Get-ScheduledTask -TaskName $auxName -ErrorAction Stop }   # a wrong name throws here, before anything has changed, not part-way through C2
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
```

**Go/no-go C0:**
- `c0-status.out.txt` shows capture healthy (3/3), with no FLAG the owner has not accepted. The flags in
  `c0-status-flags.txt` are the accepted baseline for C8 and C9c; `status.ps1` exit 2 alone is not a NO-GO;
- the release is case A (already asserted);
- `c0-next-runs.txt` is empty. The exempt tasks are the memory guard, the three supervisors, the 04:15 restore, and the aux tasks that C2 disables. Any other task due before 04:00 goes to the owner;
- G3, G5, G7, G8 and G11 hold; with a capture-family task registered, Q12b is recorded (asserted above);
- the owner types GO.

**C1. Lease and fresh receipts.**

```powershell
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
```

If the shadow task is not registered, `aux-tasks.txt` must not list it (A1 review). If it does
list it, C0's aux-name check throws, before anything has changed. C2 reads every pre-state row
before it writes `aux-prestate.csv`, so a lookup that still fails in C2 leaves no partial file.

**C2. Quiesce the auxiliary tasks and long-running holders.** The functions are defined once and
reused by C3, C9b and §R.
- `Quiesce-Aux` is idempotent. It records the pre-state only once, and stopping something already
  stopped succeeds.
- With `-Soft` (§R only), a failed step logs `ESCALATE` and the next step still runs.

```powershell
$Sup = 'WeatherSnapshotLoopSupervisor','WeatherClobBookLoopSupervisor','WeatherObservationTriggerSupervisor'
$Holders = @('WeatherExecutionTapeSupervisor','WeatherMakerShadowRunner','WeatherMakerEvidenceCapture') + $FamilyTasks   # $FamilyTasks from C0
# Was this pre-state row enabled? The Enabled column (2026-10-22) is exact. A row without it (a pre-state recorded
# before that revision) keeps the old State rule, so the undo of an existing file is unchanged.
function Test-PrestateEnabled($Row) { if ($Row.PSObject.Properties['Enabled'] -and $Row.Enabled) { return $Row.Enabled -eq 'True' }
  if ($Row.PSObject.Properties['Enabled']) { Log "ESCALATE: $($Row.Task) pre-state Enabled is empty; using the State rule (State $($Row.State))" }; $Row.State -ne 'Disabled' }
function Undo-Aux { foreach ($row in Import-Csv "$N\aux-prestate.csv") { if (Test-PrestateEnabled $row) { Enable-ScheduledTask -TaskName $row.Task | Out-Null }
    elseif ($row.State -eq 'Running') { Log "ESCALATE: $($row.Task) was disabled but running at C2; left disabled and not restarted" } }
  if ($ShadowStop) { Remove-Item -LiteralPath $ShadowStop -ErrorAction SilentlyContinue } }
function Start-AuxHolders {   # restart the long-running holders that C2 stopped, only where their pre-state was enabled
  foreach ($tn in $Holders) { $row = Import-Csv "$N\aux-prestate.csv" -ErrorAction SilentlyContinue | Where-Object Task -eq $tn
    if ($row -and (Test-PrestateEnabled $row)) { Start-ScheduledTask -TaskName $tn; Log "started $tn" }
    elseif ($row) { Log "ESCALATE: $tn pre-state disabled; not restarted" } } }
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
    if (-not (Test-Path -LiteralPath "$N\aux-prestate.csv")) {   # read every row first: a throw on row N must not leave a partial file
      $rows = @($Aux | ForEach-Object { $x = Get-ScheduledTask -TaskName $_; [pscustomobject]@{ Task=$_; State=[string]$x.State; Enabled=[string]$x.Settings.Enabled } })   # throws on a wrong name; State 'Running' does not say enabled
      $rows | Export-Csv -LiteralPath "$N\aux-prestate.csv" -NoTypeInformation } } $Soft.IsPresent
  Invoke-QStep 'shadow' {   # STOP file only, never a kill
    if ($Aux -contains 'WeatherMakerShadowRunner') {
      if (-not $ShadowStop) { NoGo 'shadow stop-file path unknown' }
      New-Item -ItemType File -Force $ShadowStop | Out-Null
      $t0 = Get-Date; while ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running' -and ((Get-Date)-$t0).TotalSeconds -lt 180) { Start-Sleep 10 }
      if ([string](Get-ScheduledTask -TaskName WeatherMakerShadowRunner).State -eq 'Running') { NoGo 'shadow did not seal in 3 min' } } } $Soft.IsPresent
  # Verify the disable with Settings.Enabled, never State: a disabled task with a running instance (88a, the tape) keeps State 'Running' until the stop below (C2 NO-GO 2026-10-22).
  foreach ($tn in $Aux) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null
    $st = @(Get-ScheduledTask -TaskName $tn); if ($st.Count -ne 1 -or $st[0].Settings.Enabled -ne $false) { NoGo "disable $tn" } } $Soft.IsPresent }
  # A disable does not end an in-flight ensure run, which could relaunch the tape after its stop. The tape supervisor is a
  # periodic ensure task (1 min, IgnoreNew, 2 min limit: register_execution_tape_supervisor.ps1:11, :27-34); wait for its instance.
  if ($Aux -contains 'WeatherExecutionTapeSupervisor') { Invoke-QStep 'tape ensure' { $tn = 'WeatherExecutionTapeSupervisor'
    $t0 = Get-Date; while ([string](Get-ScheduledTask -TaskName $tn).State -eq 'Running' -and ((Get-Date) - $t0).TotalSeconds -lt 330) { Start-Sleep 5 }
    if ([string](Get-ScheduledTask -TaskName $tn).State -eq 'Running') { NoGo "$tn instance still running past its time limit" } } $Soft.IsPresent }
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
```

A tape that is not running at C2 (crashed, or disabled in its pre-state) is not a NO-GO. Its stop
returns `process_gone` and C2 carries on.

**C3. Stop the capture workers.** This is the training-window stop sequence, with the exit codes
checked as `training_window.ps1:404-409` does. The capture stop verbs print JSON and exit 0 even
when the loop was already stopped (`snapshot_tracker.py:2413-2415`, `market_microstructure.py:2276-2278`,
`observation_trigger.py:1955-1957`), so the gate is the stop proof.

```powershell
# $Exe is one interpreter for everything (C3), or a hashtable with keys snapshot, clob, obs and gate (§R, per worker).
function Stop-Capture($Exe, [switch]$Soft) {
  $X = if ($Exe -is [hashtable]) { $Exe } else { @{ snapshot=$Exe; clob=$Exe; obs=$Exe; gate=$Exe } }
  foreach ($tn in $Sup) { Invoke-QStep "disable $tn" { Disable-ScheduledTask -TaskName $tn | Out-Null   # Settings.Enabled: a running supervisor keeps State 'Running'
    $st = @(Get-ScheduledTask -TaskName $tn); if ($st.Count -ne 1 -or $st[0].Settings.Enabled -ne $false) { NoGo "disable $tn" } } $Soft.IsPresent }
  # A disable does not end an in-flight ensure run, which could relaunch a loop after the stop verbs. The supervisors are periodic
  # ensure tasks (IgnoreNew; limits snapshot 5 min, clob and obs 2 min): wait, after all three disables, for every instance to end.
  foreach ($tn in $Sup) { Invoke-QStep "ensure $tn" {
    $t0 = Get-Date; while ([string](Get-ScheduledTask -TaskName $tn).State -eq 'Running' -and ((Get-Date) - $t0).TotalSeconds -lt 330) { Start-Sleep 5 }
    if ([string](Get-ScheduledTask -TaskName $tn).State -eq 'Running') { NoGo "$tn instance still running past its time limit" } } $Soft.IsPresent }
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
```

C3 and C4 run as one guarded block (below, after C4's functions). Any failure before the rename,
whether a `NoGo` or any other throw, runs `Undo-Stop` and then releases the lease.

In no-live-capture mode, one gate call checks all three loops, as `Wait-CaptureStopped` does
(`training_window.ps1:238-252`). `--workload` is only a label.

**C4. Sweep and rename (deadline 01:30).**

```powershell
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
```

C4 never kills a holder. An unknown holder means NO-GO with no swap. The holder file goes to the
owner.

**C5. Build the new venv offline.** From here on, any failure means §R. The C session is fresh: before
C5, define `Build-Venv` (B1c) and `Test-Venv` (B1d) in it by pasting those two function definitions
only, not the B1c and B1d calls. Both read only §6 header values (`$R`, `$WH`, `$A`, `$K`, `$NewHome`,
`$OldHome`).

```powershell
& $NewPy -I -m venv (Join-Path $P 'venv'); if ($LASTEXITCODE) { NoGo 'venv create -> ROLLBACK' }
Build-Venv $Py $P
```

**C6. Quick verify.**

```powershell
Test-Venv $Py $P 'prod'      # includes the import-location check: weather and maker_core must import from $P\src
foreach ($ln in 'python.exe','pythonw.exe') { if ((Sha (Join-Path $P "venv\Scripts\$ln")) -ne $K.binaries."Lib\venv\scripts\nt\$ln") { NoGo "launcher $ln -> ROLLBACK" } }
Get-ChildItem -LiteralPath (Join-Path $P 'venv\Lib\site-packages') -Filter *.pth | ForEach-Object { "$($_.Name): $((Get-Content -LiteralPath $_.FullName) -join ' | ')" } |
  Set-Content "$N\pth-3119.txt" -Encoding utf8     # receipt only; the import-location check is the pass rule
if (git -C $P status --porcelain --untracked-files=no) { NoGo 'tree dirty -> ROLLBACK' }
```

**C7. Restore the capture workers through the S4U path.** `Wait-Restore` (defined in C3) allows
one full 15-minute run plus one rerun.

```powershell
foreach ($tn in $Sup) { Enable-ScheduledTask -TaskName $tn | Out-Null }
if (-not (Wait-Restore $GapStart)) { NoGo 'C7 not recovered -> ROLLBACK' }
$GapEnd = Get-Date; Log ("C7 3/3; gap {0:n1} min" -f ($GapEnd-$GapStart).TotalMinutes)
```

The restore task enables the supervisors itself (`training_window.ps1:159` onward), so enabling
them first is harmless. The auxiliary tasks stay disabled until C9b.

**C8. Core verify.**

```powershell
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
```

**Go/no-go C8:**
- (a) all three status files report 3.11.9;
- (c) `status` and `error` are identical to C0, a missing-pointer BLOCK;
- (d) `status-core.new-flags.txt` (new flags against the C0 baseline) lists nothing but aux-task flags, which are
  expected until C9b; a new capture flag is a fail. The `status.ps1` exit code is not the test;
- (e) is a receipt only.

**C9. Core decision (by 02:15).** PASS needs C6, C7 and C8 all green, and either a gap of
35 minutes or less, or an overrun covered by the owner's choice recorded before the night (§11,
`$R\gap-overrun.txt`, read at C0). Nobody is asked at 02:15. Otherwise run §R.

```powershell
$GapMin = ($GapEnd-$GapStart).TotalMinutes
if ($GapMin -gt 35) {
  Log ("gap {0:n1} min over 35; recorded choice {1}" -f $GapMin, $GapChoice)
  if ($GapChoice -eq 'ROLLBACK_ON_OVERRUN') { NoGo 'capture gap overran and the owner chose rollback -> ROLLBACK' } }
Log 'C9 core PASS'
```

The worst-case gap with C7 passing is about 47 minutes: the C4 sweeps, then C5 and C6, then the
full C7 run and its rerun. A rollback after an overrun adds a second stop and restart, so it
lengthens the total gap rather than shortening it. That is why accepting the overrun is the
recommendation.

**C9b. Restore the auxiliary tasks.**

```powershell
Undo-Aux; Start-AuxHolders
$AuxRestart = Get-Date
```

**C9c. Aux verify (within 10 minutes).**

```powershell
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
```

**Go/no-go C9c:**
- **Tape:** the status command exited 0 within 5 minutes (health `RUNNING` or `DEGRADED`). In its
  latest `tape-status-*.out.txt`, the identity matches the current runtime, evidence integrity
  passes, and the connection state is `CONNECTED`.
- **Shadow:** running again, with the STOP file gone.
- **88a:** `status.json` has an `updated_at_utc` after `$AuxRestart`, `state` is `CAPTURING` or `NO_ELIGIBLE_BANDS`, and no `last_error` mentions a torn journal.
- **Capture family (Q12b, if registered):** its `status.json` has an `updated_at_utc` after `$AuxRestart`, `state` is
  `CAPTURING` (`STOPPED_FAMILY_DISK_FLOOR` is its own disk brake, a WARN), and no `last_error` mentions a torn journal.
  Its task restarts on its one-minute trigger, so run `status.ps1` only after its first fresh status; a family failure
  is handled like an 88a failure below.
- **Status:** `status-full.new-flags.txt` is empty: no flag beyond the C0 baseline. A new flag names the component
  to judge under the rules above; the `status.ps1` exit code (2 while any standing flag exists) is not the test.

If the tape or shadow fails with an import or runtime error on the new venv, run §R. It must start
by 02:45.

If 88a or a capture family fails with a journal or store error (the Q12 or Q12b risk), do **not** roll back and do not delete or
rewrite any journal. The production agent records the evidence and escalates to the owner, who
decides the remediation under the 88a retention hold.

**C10. Close-out.**

```powershell
@{ result='PASS'; head=$Head; gap_minutes=[math]::Round(($GapEnd-$GapStart).TotalMinutes,1); old_venv=$Old; new_home=$NewHome; release_case='A'; at=(Get-Date).ToString('o')
   escalations=@(Select-String -LiteralPath $Log -SimpleMatch 'ESCALATE' | Where-Object { $_.Line.StartsWith((Get-Date).ToString('yyyy-MM-dd')) }).Count } |   # tonight's lines only: night.log spans every phase
  ConvertTo-Json | Set-Content "$N\cutover-receipt.json" -Encoding utf8
Release-Lease; Log 'CUTOVER PASS'
```

Keep these for at least 14 days:
- `venv-cp3110`;
- the freeze copy of the old home;
- the 3.11.0 installation;
- every 3.11.0 release manifest;
- `$R`.

Uninstalling 3.11.0 is a later, separate owner decision. The 3.11.9 home is a plain directory with no
uninstall entry, so uninstalling 3.11.0 cannot touch it.
## Block 4. §R rollback, verbatim from the runbook (41e3bec62 lines 1299-1408, including "Escalation")

### §R. Rollback (start by 02:45, done by 03:45)

§R uses the C2, C3 and C4 functions in the same session. Every quiesce and stop step is soft: a
failure logs `ESCALATE`, and §R carries on to the swap-back and the restore. Only a rename failure,
or a failed final release check, stops §R. The aux tasks are re-enabled only after capture is 3/3.

**Which interpreter runs the stop verbs.** A stop verb kills a worker only if the expected command
matches what the worker recorded. The verb builds its expected command from its own
`sys.executable`. `managed_stop_expected_command` (`supervisor.py:1231-1266`) adopts the recorded
`managed_process.expected_command` only when its `argv[0]` is a `python.exe`/`pythonw.exe` sibling
in the **same directory**. Anything else fails closed as
`managed_process_provenance_missing_or_mismatched` (`supervisor.py:1341-1343`). So for each worker,
§R reads `managed_process.expected_command[0]` from that worker's status file, which is the file the
stop verb itself reads:
- `loop_status.json` (`snapshot_tracker.py:240`, `:789`);
- `clob_loop_status.json` (`market_microstructure_constants.py:34`, `market_microstructure.py:982`);
- `observation_trigger_status.json` (`observation_trigger.py:102`, `:986`);
- `execution_tape_status.json` (`execution_tape_supervisor.py:74`, `:502`).

§R then runs that worker's stop verb with the `python.exe` in the recorded directory, if it imports
`weather`. Only when nothing is recorded, or the recorded directory has no importable interpreter,
does it fall back to an `import weather` probe of `$Old`, then of the new venv. The two failure
cases:

| Failure at | What is running | Recorded `argv[0]` | Stop interpreter |
| --- | --- | --- | --- |
| C5 or C6 (before C7) | Nothing on the new venv. The capture workers and aux holders were stopped at C2/C3 on 3.11.0. | `$P\venv\Scripts\pythonw.exe`, from the 3.11.0 run; that path is now the new, possibly broken, venv | `$P\venv\Scripts\python.exe` if it imports; otherwise the `$Old` fallback. The recorded processes are gone, so the capture verbs only report. The gate (PID-based, no provenance check) is the stop proof, and the holder sweep proves that nothing holds the new venv. A tape stop refused for provenance logs `ESCALATE` and §R continues. |
| C7, C8, C9 or C9c | The capture workers on the new venv; after C9b, also the tape, shadow and 88a | `$P\venv\Scripts\pythonw.exe`, on the new venv | `$P\venv\Scripts\python.exe` (it imported at C6). It passes the same-directory rule, so the verbs stop the live workers. The `$Old` interpreter would be refused here. |

```powershell
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
```

**Worst-case duration.** The steps add up to about 50 minutes:
- interpreter probes: about 1 minute;
- the shadow seal wait: 3 minutes;
- the capture gate wait: 10 minutes;
- the r1 and r2 sweeps: up to 2 minutes each;
- `Wait-Restore`: 32 minutes.

That is why §R must start by 02:45: it then ends by about 03:35, inside 03:45, and well before the
04:10 U6 slot and the 04:15 restore trigger.

**Lease on an escalated §R.** If §R stops at r1, r2 or the final `Assert-CaseA`, it deliberately
keeps the lease. Nothing heavy may start on a host in an unknown state.
- **Who holds it:** the elevated PowerShell session that runs §R (workload `py3119_cutover`). The
  lease is an OS file handle on `data\logs\heavy_workload.lock`, and
  `Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P` shows it `Active` with its owner record
  (`workload_admission.ps1:2352-2377`).
- **Who releases it, and when:** the production agent that ran §R, with the owner's agreement after
  the escalation. The hard deadline is **09:00**, the end of the heavy-work window, so the 09:30
  Stage-A chain finds the lease free.
- **How:** in the same session, run `Release-Lease` (that is,
  `Exit-WeatherHeavyWorkloadLease -Lease $global:Lease`), then confirm that
  `Get-WeatherHeavyWorkloadLeaseState -RepoRoot $P` shows `Active = False`.
- **If the session is lost:** the OS closes the handle with the process. The next
  `Enter-WeatherHeavyWorkloadLease` recovers the stale marker only after proving there are no
  residual heavy processes, and asks for a retry (`workload_admission.ps1:1940-1953`).
- **If the host cannot be made safe by 09:00:** the owner decides whether Stage-A runs. Nobody else
  releases the lease to unblock it.

**Rollback passes when:**
- the S4U restore reports 3/3;
- the three status files report 3.11.0;
- the aux tasks are back in their pre-state;
- `active` is still the case-A BLOCK.

There is no release pointer to roll back in case A.

Keep `venv-cp3119-failed` and `$R` for diagnosis. If 3/3 is not reached by 03:45, escalate to the
owner. The aux tasks stay disabled, so a 04:10 U6 export cannot start on a half-restored venv. The
04:15 restore trigger stays armed.

**Escalation (C on the night of 10-21 to 10-22).** The owner's ruling, verbatim: "Auto net, you in the morning (Recommended)"
(owner 2026-10-19 ~13:1x EDT, selected options relayed by master-agent). If capture is not 3/3 by 03:45, the 04:15 `WeatherTrainingWindowRestore` task stays the automatic
net and nobody improvises a further repair overnight. Master-agent records everything (`night.log`, `$N`, the holders
files, the lease state) and messages the owner, who acts when up. The lease rules above still apply, including the
09:00 deadline and the owner's call on Stage-A. This ruling supersedes the DECISION_LOG rows of 2026-10-13 and 2026-10-17
on who answers an escalation for that night.

## Block 5. Referenced runbook text, verbatim (gates §2 lines 106-122, Q12/Q12b rows 147-148, §7a lines 524-544)

## 2. Gates (any one fails = NO-GO, nothing touched)

| Gate | Condition | Checked at |
| --- | --- | --- |
| G0 | The owner has signed §11 for this runbook revision and has named the morning or night of the phase about to run (Phase A: its owner-attended morning; Phase B and C: their nights). Revised 2026-10-12 (owner-confirmed). | Before Phase A, B0, C0 |
| G1 | The bounded suite supports `-InterpreterPath` and `-ExpectedInterpreterVersion` (`scripts/ops/bounded_worktree_test_suite.ps1:44-52`). | Met on master; re-read `param(` if the script changed |
| G2 | Phase A and Phase B passed on earlier nights, and `$R\qualification.json` has `"result":"PASS"`. | C0 |
| G3 | The production HEAD equals the qualified tip, or `scripts\ops\roll_verdict.ps1 -Branch <HEAD sha> -Base <qualified tip sha>` exits 0 (ROLL-FREE; exit 3 or 1 fails G3). A failed G3 needs B-R (requalify on the new tip) on an earlier night, or an owner ruling. | C0 |
| G4 | The owner is reachable from 00:30 to 03:45 on the cutover night: GO at C0, and any escalation up to the end of §R. Phase A needs no owner click since the 2026-10-13 revision (A4 has no installer).  **For C on the night of 10-21 to 10-22** the escalation rule is the owner's "Auto net, you in the morning (Recommended)" (owner 2026-10-19 ~13:1x EDT, selected options relayed by master-agent), which supersedes the DECISION_LOG rows of 2026-10-13 (advance GO, automatic rollback) and 2026-10-17 (the owner's own GO that night) on who answers an escalation; GO at C0 still comes from the owner in chat (§R, "Escalation"). | C0 |
| G5 | No other lease user is due that night. Specifically: <br>- `WeatherTrainingWindow` (a 01:00 one-shot, `register_training_window.ps1:3`) is disabled or has no trigger that night; <br>- Stage B `WeatherEveningEvidenceRefresh` (00:35, holds the lease to 09:00 when enabled; `register_daily_refresh.ps1:20-24`) is disabled; <br>- a U6 export registered at 00:35 (Q3) is disabled (enforced in B0 and C0 by `Assert-NoU6At0035`);<br>- no integration attempt, quiet-window merge, storage one-shot or held-head work is scheduled;<br>- no host replay or research batch (for example a lever-5 or item 337 replay) is scheduled or still running, and none holds the lease. | Phase B (B0), C0 |
| G6 | Release case A: `artifacts\releases\current_release.json` is absent (H5, B3, C0). Case B or C is NO-GO for this runbook (§8). | H5, B3, C0 |
| G7 (LFC) | The cutover night (and any Phase B prep night) is not the night before or the night of a scheduled LFC session. Revised 2026-10-12 (owner-confirmed): it no longer waits for LFC session 0, which the owner postponed. **Dated exception 2026-10-14** (owner: "Keep B" (2026-10-14 16:27 EDT, relayed verbatim by master-agent); DECISION_LOG 2026-10-13 LFC session 0 row): Phase B runs at 00:30 on 10-16, the morning of LFC session 0 (Fri 10-16), on the guard that B ends clean by 09:00 with the 8765 reader and capture re-checked, else session 0 slips; C stays at 00:30 on 10-17 (history: 10-17 plan; C is now 00:30 on 10-22, §7a). | Phase B (B0), C0 |
| G8 (88a) | The night is after the 88a merge freeze in the state of play. `$R\q12.txt` records the owner's Q12 choice as `STOP_AUTHORIZED` with its DECISION_LOG reference. Any other value means NO-GO, because the 88a worker would hold the venv. | Sign-off, C0, C2 |
| G9 (tzdata) | The tzdata sequencing is decided (Q13), so the freeze comparison in `Test-Venv` cannot false-fail. | Before Phase B |
| G10 (seals) | No live attempt is planned between the cutover and the reseal. | Sign-off |
| G11 (DST) | No phase of this runbook runs on the DST fall-back night (the night of 10-31 to 11-01). That night is under OD30 (HOST_LOAD_POLICY rule 10), and the repeated hour breaks the `.Date.AddHours()` deadlines below. | Every phase |
| G12 (downloads) | The owner has approved the PyPI wheel downloads (§T, B1a, B1b) and the NuGet package download (A3; revision 2026-10-13). The installer download approved earlier is no longer used. | Sign-off |

| # | Question | Status | Answer or next step |
| --- | --- | --- | --- |
| Q12 (new) | How does the 88a worker release the venv? | **OWNER-DECISION**, recorded in `$R\q12.txt` (G8) | `WeatherMakerEvidenceCapture` runs one long-lived worker that holds the lock ([passive maker evidence capture](passive-maker-evidence-capture.md), "Commands and registration"). Its CLI has no stop verb and no stop file (`maker_evidence_capture.py:365-372`), so disabling the task does not end it, and the rename fails while it runs. **Recommendation:** after the 88a freeze, the owner authorizes `Stop-ScheduledTask -TaskName WeatherMakerEvidenceCapture` at C2 (record `STOP_AUTHORIZED`), with the resume check in C9c. Risk: an abrupt stop skips `store.seal()` (`maker_evidence_capture.py:343-360`), and the store raises "torn journal" on a partial last line (`maker_evidence_store.py:142-143`). Alternative: wait for a reviewed graceful-stop verb, which is 88a capture behaviour and waits for the freeze to end. Until one exists, the cutover is NO-GO. |
| Q12b (2026-10-19) | How does a capture-family task (`WeatherMakerEvidence<Family>`, N12) release the venv? | **OWNER-DECISION**, recorded in `$R\q12b.txt`; needed only if such a task is registered on the cutover night | Same code and the same risk as Q12: `maker_evidence_capture --family` has no stop verb, its S4U task repeats every minute with `IgnoreNew`, so only disable-then-`Stop-ScheduledTask` ends it, and an abrupt stop can leave a partial last journal line in its own root `data\maker_evidence_families\<id>`. **Recommendation:** `STOP_AUTHORIZED` (C2 stops it next to the 88a worker; C9c checks it). Alternative: leave it unregistered until after the cutover. |

### 7a. Phase calendar (owner-confirmed 2026-10-12; Phase A done 2026-10-14)

The owner confirmed this calendar on 2026-10-12, including the fallbacks, and named the cutover
night 00:30 on 10-17 (owner reachable 00:30-03:45, G4), accepting the short gap inside the 88a
desk-study panel window (DECISION_LOG 2026-10-12). Today's position lives in
[the state of play](STATE_OF_PLAY.md). A night is named by its
morning: "00:30 on 10-16" is the night of 10-15 to 10-16.

| Phase | Primary | Fallback | Reason |
| --- | --- | --- | --- |
| A install (elevated operator session; no owner click since 2026-10-13) | **done**: P0-A2 10-13 08:54-08:57 (A4 NO-GO on the installer route); A' (A3 + A4, NuGet route) **PASS 10-14 05:23** after N9 handed back | none needed | It ran before §T, so §T ends with T-R. |
| §T tzdata + T-R | 00:30-02:00 on Thu 10-15 | 00:30 on Fri 10-16 | First admitted night after N9 (00:30 on 10-14). |
| B prep night | 00:30-04:45 on Fri 10-16 | 00:30 on Sat 10-17 | After A and after §T's T-R (B builds its lock from the refreshed freeze). |
| C cutover | 00:30-02:25 on Sat 10-17 (owner-named; did not run). **Now 00:30-02:25 on Thu 10-22** (owner 2026-10-20 ~16:4x EDT, verbatim "Keep Python 10-21/22 (Recommended)", relayed by master-agent), before N12 | the next night inside 10-15..10-30 that meets G4 and G5, named by the owner (G0) | The night after B, so the qualified tip has little time to move (G3); after the freeze (G8). If B uses its fallback (10-17), C moves too. |
| Latest second attempt | 00:30 on Thu 10-29 | none | Keeps 10-30 and 10-31 spare; never 11-01 (G11). |
| §D cleanup | first admitted night after a C PASS that has no other lease user | any later night | Removes the stage worktree; not urgent. |

Re-check every row against the night plan of the day. A later quiet-window merge night (including
the held 88a heads) that collides with a row moves the phase to its fallback (G5). G0 (the night is
named), G4 (the owner reachable 00:30-03:45) and G7 (not the night before or the night of a
scheduled LFC session) are checked again before each Phase B and Phase C night.

## Self-check (generation time, 2026-10-20, read-only)

**Functions called in C0-C10 and §R:** unchanged from the 10-17 raw (header: `Log`, `NoGo`, `Release-Lease`, `Sha`,
`Mask-Editable`, `Invoke-Native`, `Get-ReleaseActive`, `Assert-NoU6At0035`, `Get-GapChoice`, `Assert-CaseA`,
`Get-StatusFlagKeys`, `Save-StatusBaseline`, `Get-NewStatusFlags`; dot-sourced lease and memory-guard functions; Block
2 `Build-Venv`, `Test-Venv`; C2 `Undo-Aux`, `Start-AuxHolders`, `Stop-Tape`, `Invoke-QStep`, `Quiesce-Aux`; C3
`Stop-Capture`, `Wait-Restore`, `Undo-Stop`; C4 `Get-VenvHolders`, `Rename-WithSweep`; §R `Test-Interp`,
`Resolve-StopPy`). The 41e3bec62 revision adds no function; the 2026-10-22 C2 fix (Delta item 14) adds
`Test-PrestateEnabled` (C2). Missing definitions: **none**.

**Variables added by the 41e3bec62 revision:** `$FamilyTasks`, `$auxNames` (C0); loop variables `$ft` (C0, C2
`Quiesce-Aux`, C9c), `$fid`, `$fs` (C9c). None collides case-insensitively with a session constant (`$K`, `$P`, `$A`,
`$R`, `$N`, ...). `$FamilyTasks` is assigned only in C0 and read in C2 (`$Holders`, `Quiesce-Aux`), C9b
(`Start-AuxHolders` via `$Holders`), C9c and §R (`Quiesce-Aux -Soft`): C0 must run in the same session as C1-§R (the
20261022 run wrapper re-runs C0 in its own session, as the 20261017 one did).

**Files (Test-Path / first line only, 2026-10-20):**

| Path | Exists | Value read |
| --- | --- | --- |
| `C:\pyup\cp3119\qualification.json` | True | `result=PASS`, `release_case=A`, `tip=90b2e1844ad0de71916c67996026dea7b04ce5ff`, branch `py3119-qual-20261016` |
| `C:\pyup\cp3119\q12.txt` | True | first token `STOP_AUTHORIZED` |
| `C:\pyup\cp3119\gap-overrun.txt` | True | first token `ACCEPT_OVERRUN` |
| `C:\pyup\cp3119\aux-tasks.txt` | True (dated 2026-10-16 21:08; 19 names) | re-take H3 and rebuild before C0 (delta review §5 item 4) |
| `C:\pyup\cp3119\q12b.txt` | False | not needed: no `WeatherMakerEvidence<Family>` task registered (only `WeatherMakerEvidenceCapture`, excluded by C0) |
| `C:\pyup\cp3119\oldhome.txt`, `constants.json` | True | |
| `C:\pyup\cp3119\c0-done-20261022.flag`, `owner-go-20261022.txt` | False (as they must be before the night) | |

`WeatherReplayBundleExportNightly` (U6) and `WeatherEvidenceHost`: not registered on 2026-10-20 (matches delta review
§4a).

## Delta vs 20261017 raw

Every place where the 41e3bec62 runbook (and therefore this file) differs from `phase-c-raw-20261017.md`
(runbook `aae62cac2`, sha256 `4CD82738...1BDED`):

1. **Source and date.** Runbook `aae62cac2` (1475 lines) -> `41e3bec62` (1547 lines); night Sat 10-17 -> Thu 10-22
   (runbook header and §7a C row re-dated; G7's 10-17 C date now marked history).
2. **Expected head.** Old raw: HEAD `aae62cac2`, 18 docs-only commits past the tip. Now: `<EXPECTED_HEAD>` placeholder
   (master `6aac6de81` or Wed's docs-only master).
3. **G3 (gate row and C0 line).** Old: "master must attach roll_verdict.ps1 output showing roll-free before GO". New: the
   exact call `roll_verdict.ps1 -Branch <HEAD> -Base <qualified tip>`, exit 0 only; exit 3 or 1 fails; a failure
   needs B-R or an owner ruling. The C0 `if ($Head -ne $q.tip)` log line now names the call.
4. **C0 Q12b block (new, 6 lines).** Lists registered `WeatherMakerEvidence*` tasks except
   `WeatherMakerEvidenceCapture` into `$FamilyTasks`, logs them, and with any registered: NO-GO unless `$R\q12b.txt`
   first token is `STOP_AUTHORIZED` and each family task is in `aux-tasks.txt`. Go/no-go C0 bullet gains "with a
   capture-family task registered, Q12b is recorded".
5. **C1** NO-GO text: `'prod venv changed since Phase B - requalify (full Phase B on another night)'`.
6. **C2 `$Holders`** now `@(...) + $FamilyTasks`, so C9b restarts family tasks and the C8 aux-flag set includes them.
7. **C2 `Quiesce-Aux` 88a step** also `Stop-ScheduledTask`s each running family task (Q12b).
8. **C9c** adds the family `status.json` log loop (`data\maker_evidence_families\<id>\status.json`) and a "Capture
   family" go/no-go bullet (fresh `updated_at_utc` after `$AuxRestart`, `CAPTURING`, no torn journal; run
   `status.ps1` only after its first fresh status); the no-rollback rule for journal/store errors now covers families.
9. **G4** adds the owner's 10-19 escalation ruling for this night; **§R** gains the "Escalation (C on the night of
   10-21 to 10-22)" paragraph; the Phase C table's §R hard stop changes from "Escalate to the owner if not 3/3 by
   03:45" to "the 04:15 restore is the net; record and message the owner".
10. **G5** adds "no host replay or research batch ... is scheduled or still running, and none holds the lease" (no
    code check; master's GO review).
11. **Q12b** question-register row (new) and §11 checklist item; §11 MG-1 10-22 gap ruling.
12. **Unchanged:** §6 header, B1c/B1d functions, C3-C8, C9, C9b, C10 code and the §R code block (byte-identical to the
    10-17 raw). Not part of C but changed in the runbook: new B-R step (parked), §D removes every qualification
    worktree, §9 lane-pin citation by content.
13. **Self-check prerequisites:** the 10-17 raw listed `q12.txt`, `gap-overrun.txt`, `aux-tasks.txt` as missing; all
    three now exist.
14. **C2 disable check and its review fixes (2026-10-22, after the C2 false NO-GO at 01:02:11; mirrors
    claude/pyup-c2-enabled-check-20261022).** A task with a running instance keeps State `Running` after
    `Disable-ScheduledTask`, so the C2 and `Stop-Capture` post-disable checks now read `Settings.Enabled` and also require
    exactly one task of that name. The C2 pre-state records `Enabled`; `Test-PrestateEnabled` (new) decides "was it
    enabled" for `Undo-Aux`, `Start-AuxHolders`, C9c and the wrapper judgements, keeps the State rule for a row without
    the column, and logs `ESCALATE` when the column is present but empty. `Undo-Aux` logs `ESCALATE` for a task that was
    disabled but running; `Start-AuxHolders` logs `ESCALATE` for a holder with a disabled pre-state. A disable does not
    end an in-flight ensure run, so `Stop-Capture` waits (bounded 330 s) for the three supervisors' instances after all
    disables, and C2 waits the same way for the tape supervisor before its stop; the 88a, shadow and family holders are
    stopped explicitly and not waited on. C2 reads every pre-state row before writing `aux-prestate.csv` (no partial
    file), and C0 resolves every aux name first. The C10 receipt adds `escalations`, tonight's `ESCALATE` lines in
    `night.log`.
