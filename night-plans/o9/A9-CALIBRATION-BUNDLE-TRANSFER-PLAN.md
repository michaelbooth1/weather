# A9: maker replay v2 calibration-bundle transfer (short plan)

Written 2026-10-15 on the 32 GB workstation.
- r2 folded in master's answers on Q2, Q4-Q6 and the fence.
- r3 used master's host stat, added `calibration_v01_reference` and answered "does 09-28 matter".
- **r4 (same day) folds in master's Q9, Q10 and Q11 decisions and adds the exact 10-21 host command block (§7) and
  the workstation block (§8).**

**Plan only: nothing here has run on either host.** Not run on the workstation either: no command in §7-§8 has been
executed, and every function and parameter name is cited from source. It is separate from `O9-TRANSFER-PLAN.md`
and its tools (O9-TRANSFER-PLAN.md:54-61, 375-377).

Refs:
- `M` = `origin/master` @ `90b2e1844`.
- `R` = `origin/claude/mrv2-owner-rulings-20261015` @ `4007292ac`, where `transfer.py` lives; it is **not yet on the
  build line**.
- `L` = build line `origin/codex/maker-replay-v2-build-20261003` @ `1fd0c295f`.
- `X` = exam tree `6ac18be7e911289e165676bc12c6deccc4695b15`.
- `U6B` = `night-plans/2026-10-10/U6-DEPLOY-BLOCK.md`, and `O9` = `night-plans/o9/O9-TRANSFER-PLAN.md`, both on this
  branch.
- `DRV` = `src/maker_core/replay/v2/transfer_cli.py` on `claude/mrv2-transfer-driver-20261015` @ `0f2944548`.

## Authority

- Owner, 2026-10-15 batch 2: strict UTC cutoff 2026-09-30T00:00Z; A9 gets its own short plan (M docs/operations/DECISION_LOG.md:221).
- 2026-10-03: sealed *panel* bundles move only after signature (M DECISION_LOG.md:103 item 4). Calibration bundles
  are the pre-signature P3 step (R docs/research/maker-replay-v2-engineering-plan-DRAFT.md:63-71).
- 2026-10-02 exam method: one pinned, locked exam tree; exporter module hashes agree across all exam bundles (M DECISION_LOG.md:89).
- Master, 2026-10-15:
  - Q2: the workstation writes the driver.
  - Q4: production runs the host side.
  - Q5: the 10-21 night.
  - Q6: one U6 deploy tip.
  - Fence `0ea7a3c86` accepted.
  - Q7: transfer `calibration_v01_reference`.
  - **Q10: export 09-28 v0.1 from X into a NEW c2b attempt root in the 10-21 slot. Hold the lease; start 00:30 or
    later; finish before 03:15. Routine backfill, no owner ask.**
  - **Q9: run order 09-28, 09-27, 09-29; leftovers go to 10-22.**
  - **Q11: refuse rather than mis-record.**

## 1. What the bundle is

- Exported day folders for the calibration UTC dates 2026-09-27..29 only (R src/maker_core/replay/v2/panel.py:37).
- A root is `<root>\receipt.json` plus `<root>\bundle\`, holding exactly `bundle.json`, `export.json` and the listed
  streams (R src/maker_core/replay/v2/transfer.py:17-19, 180-185, 304).
- Kinds (transfer.py:7-14, 100-113):
  - `calibration_night` (P1, v0.2/v0.3, U6 runner);
  - `calibration_hazard` (P2, v0.2/v0.3, U6 runner);
  - `calibration_v01_reference` (E3 reference, v0.1, exam tree X).
- Target set: up to **9 roots**, namely 3 P1, 3 P2 and 3 v0.1. The v0.1 roots are c2b 09-27, the new 09-28 export
  and c2 09-29.

## 2. Host paths

`$G = C:\Users\micha\Desktop\github` (the only root; `C:\Users\Michael` does not exist there). `$Prod = $G\weather`,
`$C2b = $Prod\scratch\maker-replay-exam-c2b`.

| Item | Exact host path | State / source |
| --- | --- | --- |
| v0.1 09-27 | `$C2b\calibration-20261003T050423Z\2026-09-27` | master stat: FOUND. Ledger 1,885,470 B, `exporter-module-sha256.txt` and `.writer.lock` in the attempt dir |
| v0.1 09-29 | `$Prod\scratch\maker-replay-exam-c2\calibration\2026-09-29` | FOUND. Ledger 543,477 B and `.writer.lock` in `...\calibration\`; module file one level up in `...\maker-replay-exam-c2\` |
| v0.1 09-28 (new, Q10) | `$C2b\calibration-<NIGHT>-a9-0928\2026-09-28`, with `<NIGHT>` = `20261021` (or `20261022` if left over) | created by §7 H4; deterministic, never an existing name |
| X worktree (new) | `$G\weather-exam-a9-<NIGHT>-6ac18be7e` | §7 H2 |
| DRV worktree (new) | `$G\weather-a9-drv-<NIGHT>` | §7 H2 |
| A9 night dir (new) | `$G\mrv2-cal\a9-<NIGHT>\` with `p1-night\`, `p2-calibration\`, logs and receipts | §7 H1 (U6B:232 convention) |
| Inbox (workstation) | `C:\Users\Michael\Documents\github\weather\data\research_inbox\maker-replay-v2-calibration\` | §8 (O9:284-285) |

Lock and layout:
- Roots are **day folders**. Both `.writer.lock` and the ledgers sit in the parent attempt dir, so the root transfer
  never names or copies them. The side files are pulled by exact name.
- DRV never reads `exporter-module-sha256.txt`. The binding hash is each receipt's `module_sha256` (X
  src/weather/market/maker_replay_night.py:175, 204; transfer.py:308).
- No driver change is needed.

## 3. Data cutoff: strict UTC

1. **DRV, by name before any byte.** It accepts only calibration kinds and `YYYY-MM-DD` leaves strictly before the
   fence (DRV `admitted_day`, `parse_root`).
2. **Library.** `days_of` allows only 09-27..29 for these kinds (transfer.py:135-141).
3. **Bounds scan.** The scan refuses any `captured_at` outside `[day, day+1)` UTC (transfer.py:53-56).
4. **Carry fence.** The fence refuses `carry:` dates at or after 2026-09-30.
5. **Exporters.**
   - U6 refuses [09-30, 10-16) with `PANEL_GATED`, exit 3 (L scripts/ops/replay_bundle_export_nightly.ps1:38-42, 151-153).
   - X refuses any non-calibration day for `calibration` (X maker_replay_night.py:172).
6. **Commands.** Every date in §7-§8 is a literal in 2026-09-27..29. No path, glob or argument names a date in
   09-30..10-15, and no wildcard sits at a day level. The host block only does these things:
   - stats (`Test-Path`, `Get-Item`, `Get-ChildItem -LiteralPath`);
   - hashes;
   - reads of 09-27..29 receipts and of one operator hash file;
   - the exports;
   - the DRV build.

## 4. Integrity

- `build` reads three small JSON files per root and records their hashes, the module hashes and the stream
  identities (transfer.py:33-42, 293-312).
- DRV writes the manifest by exclusive create, reads it back and prints `manifest_sha256` (the out-of-band anchor;
  O9:19, 204-205).
- `verify` compares the raw manifest bytes with the relayed hash **before** parsing. It then requires exact root
  coverage, hashes every stream and runs the bounds scan (transfer.py:445-509).
- **Q11:** any refusal, including a PB2(a) refusal of an X-era input key, stops the build. Nothing is recorded
  partially, and the refusal code goes to master.

## 5. Does missing 09-28 matter? (r3, now remedied)

**Yes. Without a 09-28 v0.1 reference E3 is blocked, so signature is blocked.**
- E3 is per date (R docs/research/maker-replay-v2-registration-DRAFT.md:450, 360-364).
- Absent evidence is `NOT_SUPPLIED`, so the status is `INCOMPLETE` (R src/maker_core/replay/v2/reachability.py:248-254, 322).
- The v0.1 n/x needs all three dates (R src/maker_core/replay/calibration.py:149-151).

The transfer alone is not blocked (transfer.py:352-374). The rehearsal and ceilings need the 09-28 P1/P2 exports to
seal (R src/maker_core/replay/v2/rehearsal.py:97-100; R src/maker_core/replay/v2/ceilings.py:84-86). **Remedy approved
(Q10):** §7 H4.

## 6. Order: the 10-21 night (Q5, Q9)

Run order (Q9), seven units:
1. v0.1 09-28;
2. P1 09-28;
3. P2 09-28;
4. P1 09-27;
5. P2 09-27;
6. P1 09-29;
7. P2 09-29.

Constraints:
- No unit starts at or after **03:15** America/Toronto.
- The v0.1 unit's own budget is capped to end before 03:15.
- A U6 unit started before 03:15 ends by about 04:00 (2,700 s child budget, 2,730 s outer deadline; R
  docs/operations/maker-replay-bundle.md:404-406), before U6's 04:10 slot (DECISION_LOG.md:213).
- At up to 2,700 s each, roughly four units fit. Expect leftovers on 10-22: the same block with `$Night = '20261022'`.
  Build (H7) runs only once all seven units have sealed.

## 7. 10-21 host command block (exact)

Run as master on the capture host in Windows PowerShell 5.1, one phase at a time; each phase is one `. { }` block
(U6B:212-214 pattern). A `throw` beginning `STOP` ends the night. Native exit codes need
`$ErrorActionPreference = 'Continue'` (U6B:207-208). No phase uses `Remove-Item`, `-Force` or an overwriting write:
- each new file goes through `Write-A9New` (`FileMode.CreateNew` throws if the file exists);
- each new directory goes through `Assert-A9Fresh`;
- environment variables are cleared with `[Environment]::SetEnvironmentVariable(..., $null, 'Process')`.

**H0. Constants and helpers.** Expected output: none. Receipt: none.

```powershell
$ErrorActionPreference = 'Continue'
. {
  $G = 'C:\Users\micha\Desktop\github'; $Prod = "$G\weather"; $Py = "$Prod\venv\Scripts\python.exe"
  $Night   = '20261021'                                    # leftovers night: '20261022' (and nothing else changes)
  $Nights  = @('20261021', '20261022')                     # H7 looks for sealed roots in these two nights only
  $ExamPin = '6ac18be7e911289e165676bc12c6deccc4695b15'
  $DrvSha  = '0f29445480e19b0aa9967e45db38a9f712cf3997'    # OPEN O6: replace with the sha master lands after review
  $X   = "$G\weather-exam-a9-$Night-6ac18be7e"; $T = "$G\weather-a9-drv-$Night"
  $C2b = "$Prod\scratch\maker-replay-exam-c2b"; $C2 = "$Prod\scratch\maker-replay-exam-c2"
  $V27 = "$C2b\calibration-20261003T050423Z\2026-09-27"; $V29 = "$C2\calibration\2026-09-29"
  $V28Root = "$C2b\calibration-$Night-a9-0928"; $V28 = "$V28Root\2026-09-28"
  $A9  = "$G\mrv2-cal\a9-$Night"
  $Data = "$Prod\data"                                     # OPEN O5 (R STATE_OF_PLAY.md:44: exam data root data\)
  $Rel  = '<HOST_RELEASE_ROOT>'                            # OPEN O4 (U6B:225 leaves it to master)
  $D = '<U6 deploy tip path>'; $MOD1 = '<64-hex>'; $WRAP1 = '<64-hex>'   # OPEN O3 (Q6 tip, U6B:219-226)
  $MinMiB = 7168                                           # U6B:227
  $Units = @('v01 2026-09-28', 'night 2026-09-28', 'calibration 2026-09-28', 'night 2026-09-27',
             'calibration 2026-09-27', 'night 2026-09-29', 'calibration 2026-09-29')
  $Done = New-Object 'System.Collections.Generic.List[string]'
  function Get-A9Local { [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow,
      [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')) }
  function Assert-A9Fresh([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw "STOP: $Path already exists; attempt paths are never reused" } }
  function Write-A9New([string]$Path, [string]$Text) {
    $fs = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $b = (New-Object Text.UTF8Encoding($false)).GetBytes($Text); $fs.Write($b, 0, $b.Length) } finally { $fs.Dispose() } }
  function Assert-A9Start([string]$Unit) {
    $t = (Get-A9Local).TimeOfDay
    if ($t -lt [TimeSpan]'00:30:00' -or $t -ge [TimeSpan]'03:15:00') {
      $left = @($Units | Where-Object { -not $Done.Contains($_) })
      $msg = "03:15 cutoff at $($t.ToString('hh\:mm')); not started: $Unit. Leftovers move to 10-22: $($left -join ', ')"
      if (Test-Path -LiteralPath $A9 -PathType Container) { Write-A9New "$A9\leftovers-$((Get-Date).ToString('HHmmss')).txt" $msg }
      throw "STOP: $msg" } }
  function Assert-A9Sealed([string]$Root, [string]$Module) {
    $r = [IO.File]::ReadAllText("$Root\receipt.json") | ConvertFrom-Json
    if ([string]$r.status -cne 'SEALED') { throw "STOP: $Root receipt status is $($r.status)" }
    if ($Module -and [string]$r.module_sha256 -cne $Module) { throw "STOP: $Root module $($r.module_sha256) != $Module" }
    return $r }
}
```

**H1. Pre-checks, the night dir and the stat of the existing v0.1 roots.** The lease state check and disk/memory
floors follow M docs/operations/HOST_LOAD_POLICY.md:415-425. The lease functions are in M
scripts/ops/workload_admission.ps1:1620, 2279 and 2352. Expected output: `H1 ok`, followed by the listings. Receipt:
`$A9\h1-stat.txt`.

```powershell
. {
  Assert-A9Start 'H1'
  . "$Prod\scripts\ops\workload_admission.ps1"; . "$Prod\scripts\ops\memory_guard_status_reader.ps1"
  if ((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod).Active) { throw 'STOP: shared lease busy at H1' }
  $commit = (Read-WeatherMemoryGuardStatus -Path "$Prod\data\logs\memory_commit_guard_status.json").row.commit_percent
  if ([double]$commit -ge 70) { throw "STOP: commit_percent $commit >= 70" }
  $free = (New-Object IO.DriveInfo 'C').AvailableFreeSpace
  if ($free -lt 50GB) { throw "STOP: volume free $free bytes < 50 GiB" }
  foreach ($p in @($A9, $X, $T, $V28Root)) { Assert-A9Fresh $p }
  New-Item -ItemType Directory -Path $A9 | Out-Null
  $side = @("$C2b\calibration-20261003T050423Z\calibration-ledger.jsonl", "$C2b\calibration-20261003T050423Z\exporter-module-sha256.txt",
            "$C2\calibration\calibration-ledger.jsonl", "$C2\exporter-module-sha256.txt")
  $need = @("$V27\receipt.json", "$V27\bundle\bundle.json", "$V27\bundle\events.jsonl", "$V27\bundle\export.json",
            "$V29\receipt.json", "$V29\bundle\bundle.json", "$V29\bundle\events.jsonl", "$V29\bundle\export.json") + $side
  $miss = @($need | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
  if ($miss.Count) { throw "STOP: missing $($miss -join '; ')" }
  if (Test-Path -LiteralPath "$V27\pending") { throw "STOP: $V27\pending exists (unsealed attempt)" }
  if (Test-Path -LiteralPath "$V29\pending") { throw "STOP: $V29\pending exists (unsealed attempt)" }
  $null = Assert-A9Sealed $V27 ''; $null = Assert-A9Sealed $V29 ''
  $lines = @(Get-ChildItem -LiteralPath $V27, $V29 -Recurse -File) + @(Get-Item -LiteralPath $side) |
    ForEach-Object { "{0}`t{1}`t{2:o}" -f $_.FullName, $_.Length, $_.LastWriteTimeUtc }
  Write-A9New "$A9\h1-stat.txt" ($lines -join "`r`n"); $lines; 'H1 ok'
}
```

**H2. Fresh worktrees: the exam tree X and the driver.** Light (no lease); it never touches `$Prod`'s working tree.
Expected output: `H2 ok X=<pin> T=<drv>`. Receipt: `$A9\h2-worktrees.txt`.

```powershell
. {
  Assert-A9Start 'H2'
  foreach ($pair in @(@($X, $ExamPin, 'A9 exam tree X'), @($T, $DrvSha, 'A9 transfer driver'))) {
    $path, $sha, $why = $pair; Assert-A9Fresh $path
    & git -C $Prod cat-file -e "$sha^{commit}"
    if ($LASTEXITCODE -ne 0) { & git -C $Prod fetch --no-tags origin $sha; if ($LASTEXITCODE -ne 0) { throw "STOP: cannot fetch $sha" } }
    [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', '1', 'Process')
    try { & git -C $Prod worktree add --detach $path $sha; $rc = $LASTEXITCODE }
    finally { [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', $null, 'Process') }
    if ($rc -ne 0) { throw "STOP: worktree add $path exited $rc" }
    & git -C $Prod worktree lock --reason "$why $Night" $path
    if (([string](& git -C $path rev-parse HEAD)).Trim() -cne $sha) { throw "STOP: $path HEAD is not $sha" }
    if (@(& git -C $path status --porcelain --untracked-files=all).Count) { throw "STOP: $path is not clean" }
  }
  Write-A9New "$A9\h2-worktrees.txt" "X=$X $ExamPin`r`nT=$T $DrvSha"; "H2 ok X=$ExamPin T=$DrvSha"
}
```

**H3. Module-hash guard for X.** Light and unleased; `module-hash` reads no data (X maker_replay_night.py:282, 307-310;
facade X src/weather/market/maker_plugin/replay_export.py:2-6). It reads one operator text file. Expected output:
`H3 ok module=<64-hex>`. Receipt: `$A9\h3-module.txt`.

```powershell
. {
  $txt = ([IO.File]::ReadAllText("$C2b\calibration-20261003T050423Z\exporter-module-sha256.txt")).ToLowerInvariant()
  $m = [regex]::Match($txt, '[0-9a-f]{64}'); if (-not $m.Success) { throw 'STOP: no hash in the c2b module file' }
  $V01 = $m.Value
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$X\src", 'Process'); Push-Location $X
  try { $out = (& $Py -P -B -m weather.market.maker_plugin.replay_export module-hash) -join ''; $rc = $LASTEXITCODE }
  finally { Pop-Location; [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  if ($rc -ne 0) { throw "STOP: module-hash exited $rc" }
  $live = [string]($out | ConvertFrom-Json).module_sha256
  $r27 = Assert-A9Sealed $V27 ''
  Write-A9New "$A9\h3-module.txt" "x_live=$live`r`nc2b_file=$V01`r`nc2b_0927_receipt=$($r27.module_sha256)"
  if ($live -cne $V01 -or $live -cne [string]$r27.module_sha256) { throw 'STOP: X does not hash to the c2b exporter module (OPEN O1)' }
  "H3 ok module=$live"
}
```

**H4. Unit 1: the v0.1 09-28 export (Q10), under the shared lease.**
- Why not the admitted exam wrapper: M scripts/ops/maker_replay_exam_step.ps1 refuses an exam root inside a
  repository (:151-153), and `$C2b` is inside `$Prod`. It also caps `--max-seconds` only at 08:50 (:71-74, 185-197).
- So H4 runs X's exporter itself, with that wrapper's own lease and Job pattern (:199-241) and its byte limits (:74).
- `--max-seconds` is capped so the export ends before 03:15.
- Tokens: X maker_replay_night.py:288-296.

Expected output: `v01 2026-09-28 SEALED module=<V01> bytes=<n>`. A refusal prints `calibration refused: ...` and
exits 2 (X :315-317). Receipts:
- `$V28\receipt.json` and the new `$V28Root\calibration-ledger.jsonl` (the exporter's own; R
  docs/operations/maker-replay-bundle.md:248-250);
- `$A9\v01-2026-09-28.{stdout,stderr}.log` and `$A9\v01-2026-09-28.step.json`.

```powershell
. {
  Assert-A9Start 'v01 2026-09-28'; Assert-A9Fresh $V28Root
  if (-not (Test-Path -LiteralPath $C2b -PathType Container)) { throw "STOP: $C2b missing" }
  . "$Prod\scripts\ops\workload_admission.ps1"; . "$Prod\scripts\ops\windows_kill_on_close_job.ps1"
  $now = Get-A9Local; $secs = [int][Math]::Min(2700, [Math]::Floor(($now.Date.Add([TimeSpan]'03:15:00') - $now).TotalSeconds) - 120)
  if ($secs -lt 600) { throw "STOP: only $secs s before 03:15; v01 2026-09-28 moves to 10-22" }
  $log = "$A9\v01-2026-09-28"
  $tokens = @('-P', '-B', '-m', 'weather.market.maker_plugin.replay_export', 'calibration', '--day', '2026-09-28',
    '--data-root', $Data, '--out', $V28Root, '--expected-module-sha256', $V01, '--max-input-bytes', '17179869184',
    '--max-seconds', [string]$secs, '--max-output-bytes', '2147483648')
  $lease = Enter-WeatherHeavyWorkloadLease -RepoRoot $Prod -Workload 'maker_replay_exam_calibration_2026-09-28' `
    -ExpectedExecutionHostId (Get-WeatherExecutionHostId)
  if ($null -eq $lease) { throw 'STOP: shared lease busy; v01 2026-09-28 moves to 10-22' }
  $job = $null; $cap = $null; $child = $null; $proved = $false; $code = $null; $hard = $false
  $clock = [Diagnostics.Stopwatch]::StartNew()
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$X\src", 'Process')
  try {
    $job = New-WeatherKillOnCloseJob
    $cap = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new("$log.stdout.log", "$log.stderr.log", 8388608)
    $child = Start-WeatherProcessInJob -Job $job -FilePath $Py -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) `
      -WorkingDirectory $Prod -OutputCapture $cap
    $null = $child.Handle
    while (-not $child.HasExited) {
      if ($clock.Elapsed.TotalSeconds -ge ($secs + 60)) { $hard = $true; break }
      $cap.Drain(); Start-Sleep -Milliseconds 100; $child.Refresh() }
    if (-not $hard) { $child.WaitForExit(); $code = [int]$child.ExitCode }
  } finally {
    [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process')
    try { if ($job) { $job.TerminateAndWait(5000) }; $proved = $true; if ($cap) { $cap.Complete(2000) } }
    finally {
      if ($cap) { $cap.Dispose() }; if ($child) { $child.Dispose() }; if ($job) { $job.Dispose() }
      if ($proved) { Exit-WeatherHeavyWorkloadLease -Lease $lease } else { Set-WeatherHeavyWorkloadLeasePoisoned -Lease $lease } } }
  Write-A9New "$log.step.json" (@{ unit = 'v01 2026-09-28'; exit_code = $code; hard_stop = $hard; teardown_proved = $proved
    max_seconds = $secs; runtime_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3); out = $V28Root } | ConvertTo-Json -Compress)
  if ($hard -or $code -ne 0) { throw "STOP: v01 2026-09-28 exit=$code hard_stop=$hard (see $log.stderr.log)" }
  $r = Assert-A9Sealed $V28 $V01; $Done.Add('v01 2026-09-28')
  "v01 2026-09-28 SEALED module=$($r.module_sha256) bytes=$($r.bundle.bytes)"
}
```

**H5. Units 2-7: the U6 exports, serial, in Q9 order.**
- The runner takes and releases the lease itself (L replay_bundle_export_nightly.ps1:185-193, 264), so no phase
  holds a lease around it.
- Its parameters are at L :16-27, and the output **parent** must exist (L :170-173).
- Expected output per unit: `<kind> <day> rc=0 SEALED`. Exit 3 means `PANEL_GATED` and cannot occur for these dates.
- Receipts: `$A9\p1-night\<day>\receipt.json` or `$A9\p2-calibration\<day>\receipt.json`, plus
  `$A9\u6-<kind>-<day>.{out,err,rc}`. The `.out` holds the runner's one JSON line (L :242-246).

```powershell
. {
  function Invoke-A9U6([string]$Kind, [string]$Day) {
    $unit = "$Kind $Day"; Assert-A9Start $unit
    $root = if ($Kind -ceq 'night') { "$A9\p1-night" } else { "$A9\p2-calibration" }
    $base = "$A9\u6-$Kind-$Day"; foreach ($p in @("$root\$Day", "$base.out", "$base.err", "$base.rc")) { Assert-A9Fresh $p }
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\replay_bundle_export_nightly.ps1" `
      -DeployRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot $root `
      -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB $MinMiB -Kind $Kind -Day $Day `
      1> "$base.out" 2> "$base.err"
    $rc = $LASTEXITCODE; Write-A9New "$base.rc" "$rc"
    if ($rc -ne 0) { throw "STOP: $unit exited $rc (see $base.err)" }
    $null = Assert-A9Sealed "$root\$Day" $MOD1; $Done.Add($unit); "$unit rc=0 SEALED" }
  foreach ($u in @($Units | Where-Object { $_ -cne 'v01 2026-09-28' -and -not $Done.Contains($_) })) {
    $k, $d = $u -split ' '; Invoke-A9U6 $k $d }
  'H5 ok: all U6 units sealed tonight'
}
```

**H6. Leftovers.** If H4 or H5 stopped at the 03:15 cutoff, `$A9\leftovers-*.txt` lists the units. On the 10-22 night:
- run H0 with `$Night = '20261022'`, then H1, then H4 if v0.1 09-28 is listed, then H5;
- skip H2 unless a fresh `$X`/`$T` is needed, which it is: H2 creates `-20261022` worktrees;
- **skip H3 only if** `$X` is reused.

The sealed units from 10-21 are found by H7.

**H7. Build (light, unleased; three small JSON files per root).** It runs once every unit has sealed across
`$Nights`. It names only literal night dirs and dates, and needs exactly one sealed root per unit. Expected output:
DRV's JSON with `"verdict": "BUILT"` and `manifest_sha256`; exit 2 prints `refused: <code>` (Q11: stop, report).
Receipts: `$A9\transfer_manifest.json` (exclusive create, DRV) and `$A9\h7-build.json`.

```powershell
. {
  function Find-A9Sealed([string[]]$Candidates) {
    $hits = @($Candidates | Where-Object { Test-Path -LiteralPath "$_\receipt.json" -PathType Leaf } |
      Where-Object { [string]([IO.File]::ReadAllText("$_\receipt.json") | ConvertFrom-Json).status -ceq 'SEALED' })
    if ($hits.Count -ne 1) { throw "STOP: need exactly one SEALED root among $($Candidates -join '; '); found $($hits.Count)" }
    return $hits[0] }
  $roots = @()
  foreach ($d in @('2026-09-27', '2026-09-28', '2026-09-29')) {
    $roots += '--root', ('calibration_night=' + (Find-A9Sealed @($Nights | ForEach-Object { "$G\mrv2-cal\a9-$_\p1-night\$d" })))
    $roots += '--root', ('calibration_hazard=' + (Find-A9Sealed @($Nights | ForEach-Object { "$G\mrv2-cal\a9-$_\p2-calibration\$d" }))) }
  $roots += '--root', "calibration_v01_reference=$V27"
  $roots += '--root', ('calibration_v01_reference=' + (Find-A9Sealed @($Nights | ForEach-Object { "$C2b\calibration-$_-a9-0928\2026-09-28" })))
  $roots += '--root', "calibration_v01_reference=$V29"
  Assert-A9Fresh "$A9\transfer_manifest.json"; Assert-A9Fresh "$A9\h7-build.json"
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$T\src", 'Process')
  try { $out = (& $Py -P -B -m maker_core.replay.v2.transfer_cli build @roots --host-id $env:COMPUTERNAME `
          --out "$A9\transfer_manifest.json") -join "`n"; $rc = $LASTEXITCODE }
  finally { [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  Write-A9New "$A9\h7-build.json" $out; $out
  if ($rc -ne 0) { throw "STOP: build exited $rc" }
  $Built = $out | ConvertFrom-Json; $RootArgs = $roots
}
```

**H8. Hash relay.** A stat and hash only. Expected output: the relay text. Receipt: `$A9\relay.txt`; master relays its
content out of band.

```powershell
. {
  $h = (Get-FileHash -LiteralPath "$A9\transfer_manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($h -cne [string]$Built.manifest_sha256) { throw "STOP: file hash $h != printed $($Built.manifest_sha256)" }
  $v28root = Split-Path -Parent (($RootArgs | Where-Object { $_ -like 'calibration_v01_reference=*2026-09-28' }) -replace '^[^=]+=', '')
  $side = @("$C2b\calibration-20261003T050423Z\calibration-ledger.jsonl", "$C2b\calibration-20261003T050423Z\exporter-module-sha256.txt",
            "$C2\calibration\calibration-ledger.jsonl", "$C2\exporter-module-sha256.txt", "$v28root\calibration-ledger.jsonl")
  $lines = @("manifest=$A9\transfer_manifest.json", "manifest_sha256=$h", "manifest_bytes=$($Built.manifest_bytes)") +
    @($RootArgs | Where-Object { $_ -cne '--root' } | ForEach-Object { "root=$_" }) +
    @($side | ForEach-Object { "side=$_ sha256=$((Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()) bytes=$((Get-Item -LiteralPath $_).Length)" })
  Write-A9New "$A9\relay.txt" ($lines -join "`r`n"); $lines
}
```

`$A9`, `$X`, `$T` and the new c2b attempt are kept as evidence; nothing on the host is moved or deleted.

## 8. Workstation block (steps 7-9)

Windows PowerShell 5.1 on the 32 GB workstation, after the relay, no host lease. Paste `relay.txt`'s lines into `$Relay`.

**W7. Pull (copies only, by exact name; never `.writer.lock`).** Expected output: `W7 ok <n> roots`. Receipt:
`$I\w7-pull.txt`. scp silently overwrites, so every destination is first asserted absent.

```powershell
$ErrorActionPreference = 'Continue'
. {
  $I = 'C:\Users\Michael\Documents\github\weather\data\research_inbox\maker-replay-v2-calibration'
  $Relay = @'
<paste relay.txt here>
'@ -split "`r?`n" | Where-Object { $_ }
  function Get-R([string]$k) { ($Relay | Where-Object { $_ -like "$k=*" }) -replace "^$k=", '' }
  function Assert-Absent([string]$p) { if (Test-Path -LiteralPath $p) { throw "STOP: $p exists" } }
  function To-Scp([string]$p) { 'production-pc:' + ($p -replace '\\', '/') }
  $sha = [string](Get-R 'manifest_sha256'); if ($sha -cnotmatch '\A[0-9a-f]{64}\z') { throw 'STOP: relay has no manifest_sha256' }
  Assert-Absent $I; New-Item -ItemType Directory -Path $I | Out-Null
  scp -o BatchMode=yes -o ConnectTimeout=10 (To-Scp (Get-R 'manifest')) "$I/transfer_manifest.json"
  if ((Get-FileHash -LiteralPath "$I\transfer_manifest.json" -Algorithm SHA256).Hash.ToLowerInvariant() -cne $sha) { throw 'STOP: manifest hash != relay' }
  $VerifyRoots = @()
  foreach ($r in @(Get-R 'root')) {
    $kind, $src = $r -split '=', 2; $day = Split-Path -Leaf $src; $dst = "$I\$kind"
    if (-not (Test-Path -LiteralPath $dst)) { New-Item -ItemType Directory -Path $dst | Out-Null }
    Assert-Absent "$dst\$day"
    scp -r -o BatchMode=yes -o ConnectTimeout=10 (To-Scp $src) "$dst/"
    if ($LASTEXITCODE -ne 0) { throw "STOP: scp $src exited $LASTEXITCODE" }
    $VerifyRoots += '--root', "$kind=$dst\$day" }
  $n = 0
  foreach ($s in @(Get-R 'side')) {
    $path, $hash = ($s -replace ' bytes=\d+$', '') -split ' sha256='; $n++
    $dst = "$I\v01-side\$n"; New-Item -ItemType Directory -Path $dst | Out-Null
    scp -o BatchMode=yes -o ConnectTimeout=10 (To-Scp $path) "$dst/"
    $got = (Get-FileHash -LiteralPath "$dst\$(Split-Path -Leaf $path)" -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -cne $hash) { throw "STOP: side file $path hash mismatch" } }
  [IO.File]::WriteAllLines("$I\w7-pull.txt", [string[]](@("relay_manifest_sha256=$sha") + $VerifyRoots))
  "W7 ok $($VerifyRoots.Count / 2) roots"
}
```

**W8. Verify.** Expected output: DRV JSON with `"verdict": "PASS"`, one bundle per entry, and per-stream counts and
min/max inside each day; exit 0. Receipt: `$I\w8-verify.json`. The workstation's heavy wrapper does not admit this
module (OPEN O7), so the command below is the direct form.

```powershell
. {
  $DrvSha = '0f29445480e19b0aa9967e45db38a9f712cf3997'   # OPEN O6: the landed sha
  $W = "C:\wt\a9-verify-$($DrvSha.Substring(0, 9))"
  if (Test-Path -LiteralPath $W) { throw "STOP: $W exists" }
  [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', '1', 'Process')
  try { & git -C 'C:\Users\Michael\Documents\github\weather' worktree add --detach $W $DrvSha; $wrc = $LASTEXITCODE }
  finally { [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', $null, 'Process') }
  if ($wrc -ne 0) { throw "STOP: worktree add $W exited $wrc" }
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$W\src", 'Process')
  try { $out = (& 'C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe' -P -B -m maker_core.replay.v2.transfer_cli verify `
          --manifest "$I\transfer_manifest.json" --expected-manifest-sha256 $sha @VerifyRoots) -join "`n"; $rc = $LASTEXITCODE }
  finally { [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  $fs = [IO.File]::Open("$I\w8-verify.json", [IO.FileMode]::CreateNew); try { $b = [Text.Encoding]::UTF8.GetBytes($out); $fs.Write($b, 0, $b.Length) } finally { $fs.Dispose() }
  $out; if ($rc -ne 0) { throw "STOP: verify exited $rc" }
}
```

After PASS, three checks, read from the pulled files only. Receipt: append nothing; record the results in the
master report.
- Each v0.1 ledger's row for its day has `status` `SEALED` (row fields `day`/`status`, X maker_replay_night.py:91-104).
- The three `calibration_v01_reference` entries in `$I\transfer_manifest.json` carry one identical `module_sha256`,
  and it equals both pulled `exporter-module-sha256.txt` values (M DECISION_LOG.md:89).
- The c2 09-29 entry is the one most likely to differ (OPEN O8).

**W9.** On PASS and the checks, master names a branch. Copy the byte-identical `$I\transfer_manifest.json` to
`config\maker_replay_v2\transfer_manifest.json` in a fresh worktree of it with `Copy-Item -LiteralPath` (no `-Force`;
the target must not exist). Re-hash it, commit and push (`config/` is roll-free). Then run the P3 rehearsal (R
tools/research/maker_replay_v2/rehearse_cli.py:1-11).

## 9. Verification and rollback

- **PASS:** W8 exit 0 and verdict `PASS`, plus the three W8 checks.
- **Workstation rollback:** leave `$I` in place and start a fresh inbox name. Revert a committed manifest with a new
  commit (never a force-push).
- **Host:** nothing is moved or deleted. A refused or partial unit is never retried in place: a new night gets new
  `-<NIGHT>` paths (maker-replay-bundle.md:251-252). On a poisoned lease (H4 teardown unproved), stop and follow
  HOST_LOAD_POLICY.md:33-40.

## 10. Open items (not pinned down here)

- **O1. X's module hash.** DECISION_LOG.md:89 defines the exam tree as `6ac18be7e` plus the reviewed Clarification 3
  hash commit. If X at `6ac18be7e` does not hash to the c2b exporter module (and to the c2b 09-27 receipt), H3 stops.
  Master then names the real pin, or the existing locked exam worktree (R STATE_OF_PLAY.md:46 "exam tree above").
  Known value elsewhere: v0.1 facade closure `089cb29a…fa88` at `6d1fa4b74` (U6B:30). That is not the exam tree.
- **O2. Bypassing the admitted exam wrapper.** H4 does not use `maker_replay_exam_step.ps1`, for two reasons: the
  in-repository exam-root guard (:151-153) refuses `$C2b`, and the wrapper offers no 03:15 cap (:71-74). How the
  existing c2b/c2 roots under `$Prod\scratch` were written is not on record. Master either confirms the H4 pattern,
  or names an exam root outside `$Prod`; in that case the new attempt is no longer under c2b.
- **O3.** `$D`, `$MOD1` and `$WRAP1` for the one U6 tip (Q6, handled separately).
- **O4.** `$Rel`, the host release root (U6B:225).
- **O5.** `$Data = $Prod\data`: confirm it is the c2b exports' `--data-root`.
- **O6.** The DRV sha after Fable review and master landing. `0f2944548` is the pushed tip; the host must be able to
  fetch it.
- **O7.** `workstation_heavy.ps1 -Kind weather_heavy` admits only the modules in `Get-WeatherWorkstationOfflineModule`
  (M scripts/ops/workload_admission.ps1:611-635; workstation_heavy.ps1:130-139), and `transfer_cli` is not one of
  them. The options are to add it (a roll-free `.ps1` change on master) or to approve W8's direct run.
- **O8.** c2's 09-29 is recorded as "spent" (R STATE_OF_PLAY.md:44-45). H1 enforces a SEALED receipt. Module
  agreement between c2 and c2b is checked only at W8.
- **O9.** The format of `exporter-module-sha256.txt` is unknown. H3 takes its first 64-hex token and cross-checks it
  against the 09-27 receipt.
- **O10.** H1's disk floor (50 GiB) and commit floor (70%) are the ad-hoc policy values (HOST_LOAD_POLICY.md:415-425).
  U6's own admission (`-MinAvailableMiB 7168`) applies on top of them.
