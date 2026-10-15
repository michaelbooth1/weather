# A9: maker replay v2 calibration-bundle transfer (short plan)

Written 2026-10-15 on the 32 GB workstation.
- r2 folded in master's answers on Q2, Q4-Q6 and the fence.
- r3 used master's host stat, added `calibration_v01_reference` and answered "does 09-28 matter".
- r4 folded in Q9, Q10 and Q11 and added the exact host block.
- **r6 (same day):** master found by stat that `$Prod\artifacts\releases` does not exist. §7a(b2) shows from code that
  no captured row can carry the verified-release marker in that configuration, so `$Rel` is now a fresh, empty, dated
  folder created at registration (R0).
- **r5 (same day) applies master's r4 decisions:**
  - O2: no bypass of the admitted exam wrapper. The 09-28 root moves outside the repository, and H4 enforces 03:15
    with an outer Job deadline.
  - O3, O4, O5: host facts plus answers (a), (b) and (c) in §7a.
  - O6: the driver lands after Fable.
  - O7: W8 runs through `workstation_heavy.ps1`, which depends on `6c3c4792b`.

**Plan only: nothing in §7-§8 has run on either host.** The workstation ran only the read-only hash recompute in §7a(c).
Every function, parameter and token is cited from source. A9 is separate from `O9-TRANSFER-PLAN.md` and its tools
(O9-TRANSFER-PLAN.md:54-61, 375-377).

Refs:
- `M` = `origin/master` @ `90b2e1844`.
- `R` = `origin/claude/mrv2-owner-rulings-20261015` @ `4007292ac`, where `transfer.py` lives.
- `L` = build line @ `1fd0c295f`.
- `U` = U6 deploy tip `claude/u6-deploy-0410-20261015` @ `67cad7be244de3bf6309dbe21112b3fd62bb79c9`.
- `X` = exam tree `6ac18be7e911289e165676bc12c6deccc4695b15`.
- `W7B` = `claude/workstation-heavy-transfer-cli-20261015` @ `6c3c4792b`.
- `U6B` = `night-plans/2026-10-10/U6-DEPLOY-BLOCK.md` and `O9` = `night-plans/o9/O9-TRANSFER-PLAN.md`, both on this branch.
- `DRV` = `src/maker_core/replay/v2/transfer_cli.py`, pushed at `0f2944548`; it lands on master after Fable.

## Authority

- Owner, 2026-10-15 batch 2: strict UTC cutoff 2026-09-30T00:00Z; A9 gets its own short plan (M docs/operations/DECISION_LOG.md:221).
- 2026-10-03: sealed *panel* bundles move only after signature (M DECISION_LOG.md:103 item 4). Calibration bundles are
  the pre-signature P3 step (R docs/research/maker-replay-v2-engineering-plan-DRAFT.md:63-71).
- 2026-10-02 exam method: one pinned, locked exam tree; exporter module hashes agree across exam bundles (M DECISION_LOG.md:89).
- Master, 2026-10-15:
  - Q2: the workstation writes the driver.
  - Q4: production runs the host side.
  - Q5: the 10-21 night.
  - Q6: one U6 tip.
  - Fence `0ea7a3c86` accepted.
  - Q7: transfer `calibration_v01_reference`.
  - Q10: export 09-28 v0.1 from X in the 10-21 slot. Hold the lease; start 00:30 or later; finish before 03:15; routine backfill.
  - Q9: run order 09-28, 09-27, 09-29; leftovers go to 10-22.
  - Q11: refuse rather than mis-record.
  - **r4 review (~15:2x):** no bypass of the admitted exam wrapper ("Relaxing a guard is not arming a driver"). The new
    root goes outside the repository with a deterministic `<n>`. 03:15 is enforced by an outer deadline that kills the
    child tree.

## 1. What the bundle is

- Exported day folders for the calibration UTC dates 2026-09-27..29 only (R src/maker_core/replay/v2/panel.py:37).
- A root is `<root>\receipt.json` plus `<root>\bundle\`, holding exactly `bundle.json`, `export.json` and the listed
  streams (R transfer.py:17-19, 180-185, 304).
- Kinds (transfer.py:7-14, 100-113):
  - `calibration_night` (P1, v0.2/v0.3, U6 runner);
  - `calibration_hazard` (P2, v0.2/v0.3, U6 runner);
  - `calibration_v01_reference` (E3 reference, v0.1, exam tree X).
- Target set: **9 roots**: 3 P1, 3 P2 and 3 v0.1. The v0.1 roots are c2b 09-27, the new 09-28 export and c2 09-29.

## 2. Host paths

`$G = C:\Users\micha\Desktop\github` is the only root. `$Prod = $G\weather` and `$C2b = $Prod\scratch\maker-replay-exam-c2b`.

| Item | Exact host path | State / source |
| --- | --- | --- |
| v0.1 09-27 | `$C2b\calibration-20261003T050423Z\2026-09-27` | master stat: FOUND (ledger, module file and `.writer.lock` in the attempt dir) |
| v0.1 09-29 | `$Prod\scratch\maker-replay-exam-c2\calibration\2026-09-29` | FOUND (ledger and lock in `...\calibration\`; module file in `...\maker-replay-exam-c2\`) |
| v0.1 09-28 exam root (new) | `$G\mrv2-cal\a9-<NIGHT>-0928-<n>` | the wrapper's `-ExamRoot`; H4 creates it after `Assert-A9Fresh` |
| v0.1 09-28 attempt root (new) | `$G\mrv2-cal\a9-<NIGHT>-0928-<n>\calibration-a9-<NIGHT>-0928-<n>` | the wrapper's `-AttemptRoot`; the day root is `...\2026-09-28` |
| X worktree (new, locked) | `$G\weather-exam-a9-<NIGHT>-6ac18be7e` | H2 |
| DRV worktree (new, locked) | `$G\weather-a9-drv-<NIGHT>` | H2 |
| U6 deploy tree for U | `$G\weather-exam-deployed-67cad7be244de3bf6309dbe21112b3fd62bb79c9` | made by the separate U6 deploy (Q6, U6B:221 naming); H2b checks it |
| A9 night dir (new) | `$G\mrv2-cal\a9-<NIGHT>\` | H1 |
| Inbox (workstation) | `C:\Users\Michael\Documents\github\weather\data\research_inbox\maker-replay-v2-calibration\` | §8 |

Naming rules:
- `<NIGHT>` is `20261021`, or `20261022` for leftovers. `<n>` is `1`.
- A new `<n>` is used only if master explicitly re-attempts on the same night. The wrapper never retries a day in place
  (M scripts/ops/maker_replay_exam_step.ps1:311-313; Q11).
- The attempt root is a child of the master-named root because the wrapper takes `-AttemptRoot` only when it is
  `calibration-*` inside `-ExamRoot` (:301-303) and already exists (:305). Without `-AttemptRoot` it names the root
  `calibration-<UTC stamp>` (:295-299), which is not deterministic.

Lock and layout: roots are day folders, and `.writer.lock` and the ledgers sit in the parent attempt dir. No driver
change is needed. The binding hash is each receipt's `module_sha256` (X src/weather/market/maker_replay_night.py:204;
transfer.py:308).

## 3. Data cutoff: strict UTC

1. **DRV, by name.** It refuses before any byte is read (`admitted_day`, `parse_root`).
2. **Library.** `days_of` allows only 09-27..29 for these kinds (transfer.py:135-141).
3. **Bounds scan.** It refuses any `captured_at` outside `[day, day+1)` (transfer.py:53-56).
4. **Carry fence.** It refuses carry dates at or after 09-30.
5. **Exporters.**
   - The U6 runner refuses [09-30, 10-16) with `PANEL_GATED`, exit 3 (U scripts/ops/replay_bundle_export_nightly.ps1:37-46, 151-155).
   - X and the exam wrapper admit only calibration days for `calibration` (X maker_replay_night.py:172; wrapper :68, 263-267, 320).
6. **Commands.** Every date in §7-§8 is a literal in 09-27..29. Nothing names or globs 09-30..10-15. H1's data-root stat
   (§7a(a)) names only `maker_evidence\2026-09-27` and `\2026-09-29` segment manifests, and only stats them.

## 4. Integrity

- `build` hashes three small JSON files per root, plus the module hashes and stream identities (transfer.py:33-42, 293-312).
- DRV writes the manifest by exclusive create and prints `manifest_sha256` (DRV :124-125), the out-of-band anchor.
- `verify` checks the raw manifest bytes against the relayed hash before parsing. It then requires exact root coverage,
  hashes every stream and runs the bounds scan (transfer.py:445-509; DRV :130, 159).
- **Q11:** any refusal stops the line. Nothing is recorded partially.

## 5. Does missing 09-28 matter?

**Yes. Without a 09-28 v0.1 reference E3 is blocked, so signature is blocked.**
- E3 is per date (R docs/research/maker-replay-v2-registration-DRAFT.md:450, 360-364).
- Absent evidence is `NOT_SUPPLIED`, which makes the status `INCOMPLETE` (R src/maker_core/replay/v2/reachability.py:248-254, 322).
- The v0.1 n/x needs all three dates (R src/maker_core/replay/calibration.py:149-151).

The transfer alone is not blocked (transfer.py:352-374). Remedy: §7 H4 (Q10).

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
- The v0.1 unit is **killed** at 03:15 by H4's outer deadline.
- A U6 unit started before 03:15 ends by about 04:01: a 2,730 s deadline with the child capped at 2,700 s (U :53-67,
  216-218). That is before U6's 04:10 slot (DECISION_LOG.md:213).
- Roughly four 2,700 s units fit. Leftovers rerun on 10-22 with `$Night = '20261022'`. Build (H7) needs all seven sealed.

## 7. 10-21 host command block (exact)

Run as master on the capture host in Windows PowerShell 5.1, one phase at a time; each phase is one `. { }` block (U6B:212-214).
- A `throw` starting with `STOP` ends the night.
- Native calls need `$ErrorActionPreference = 'Continue'` with `$LASTEXITCODE` checks (U6B:207-208).
- No phase uses `Remove-Item` or `-Force`, and nothing is overwritten:
  - new files are created with `FileMode.CreateNew`;
  - new directories pass `Assert-A9Fresh` first;
  - environment variables are cleared with `SetEnvironmentVariable(..., $null, 'Process')`.
- The block holds **no lease itself**. The exam wrapper (H4) and the U6 runner (H5) each take and release the shared
  lease (wrapper :205-209 and 228-240; U :193-195).

**R0. Empty release root, created once at registration on 10-20.** It is a fresh, dated folder outside `artifacts\`
and outside every output root, as the runner requires (U :167-173). Expected output: `R0 ok`. Receipt: the folder itself.

```powershell
$Rel = 'C:\Users\micha\Desktop\github\mrv2-cal\u6-release-root-empty-20261020'
if (Test-Path -LiteralPath $Rel) { throw "STOP: $Rel already exists; attempt paths are never reused" }
New-Item -ItemType Directory -Path $Rel | Out-Null; 'R0 ok'
```

**H0. Constants and helpers.** Expected output: `H0 ok`. Receipt: none.

```powershell
$ErrorActionPreference = 'Continue'
. {
  $G = 'C:\Users\micha\Desktop\github'; $Prod = "$G\weather"; $Py = "$Prod\venv\Scripts\python.exe"
  $Night  = '20261021'                                   # leftovers night: '20261022'; nothing else changes
  $Nights = @('20261021', '20261022')                    # H7 searches these two nights only
  $N      = '1'                                          # 09-28 attempt ordinal; a new value only on master's explicit re-attempt
  $ExamPin = '6ac18be7e911289e165676bc12c6deccc4695b15'
  $V01x  = 'f97ce024a46f907c4ec64e34811a7f46d9c447fdd2e869788a8398efa8a041c0'   # X module-hash, 55 files (workstation, py 3.11.9; §7a(c))
  $DrvSha = '<LANDED_MASTER_SHA>'                        # OPEN O6: the master commit that lands DRV after Fable (pushed tip 0f2944548)
  $USha  = '67cad7be244de3bf6309dbe21112b3fd62bb79c9'
  $D     = "$G\weather-exam-deployed-$USha"              # U6B:221 naming; built by the Q6 deploy, checked in H2b
  $MOD1  = 'dbb118d4c247826cc278dac468a8d5a38ab8e46d484d440f1eb7e30949089beb'; $MOD1Files = 63   # §7a(c)
  $WRAP1 = '8dd29ad3495d33c53bedfdacaaa3e6d342bb55891256a2554e20a15830fc1143'                    # §7a(c)
  $Data  = "$Prod\data"                                  # master's proposal; H1 stat-confirms it (§7a(a))
  $Rel   = "$G\mrv2-cal\u6-release-root-empty-20261020"   # R0 creates it empty on 10-20; any verified row refuses the day (Q11)
  $MinMiB = 7168                                         # U6B:227
  $X = "$G\weather-exam-a9-$Night-6ac18be7e"; $T = "$G\weather-a9-drv-$Night"
  $C2b = "$Prod\scratch\maker-replay-exam-c2b"; $C2 = "$Prod\scratch\maker-replay-exam-c2"
  $V27 = "$C2b\calibration-20261003T050423Z\2026-09-27"; $V29 = "$C2\calibration\2026-09-29"
  $V28Exam = "$G\mrv2-cal\a9-$Night-0928-$N"; $V28Root = "$V28Exam\calibration-a9-$Night-0928-$N"; $V28 = "$V28Root\2026-09-28"
  $A9 = "$G\mrv2-cal\a9-$Night"
  $Units = @('v01 2026-09-28', 'night 2026-09-28', 'calibration 2026-09-28', 'night 2026-09-27',
             'calibration 2026-09-27', 'night 2026-09-29', 'calibration 2026-09-29')
  $Done = New-Object 'System.Collections.Generic.List[string]'
  if ($DrvSha -cnotmatch '\A[0-9a-f]{40}\z') { throw 'STOP: $DrvSha placeholder not replaced (O6)' }
  function Get-A9Local { [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow,
      [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')) }
  function Assert-A9Fresh([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw "STOP: $Path already exists; attempt paths are never reused" } }
  function Write-A9New([string]$Path, [string]$Text) {
    $fs = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try { $b = (New-Object Text.UTF8Encoding($false)).GetBytes($Text); $fs.Write($b, 0, $b.Length) } finally { $fs.Dispose() } }
  function Write-A9Leftovers([string]$Why) {
    $left = @($Units | Where-Object { -not $Done.Contains($_) })
    $msg = "$Why. Leftovers move to 10-22: $($left -join ', ')"
    if (Test-Path -LiteralPath $A9 -PathType Container) { Write-A9New "$A9\leftovers-$((Get-Date).ToString('HHmmss')).txt" $msg }
    return $msg }
  function Assert-A9Start([string]$Unit) {
    $t = (Get-A9Local).TimeOfDay
    if ($t -lt [TimeSpan]'00:30:00' -or $t -ge [TimeSpan]'03:15:00') {
      throw ('STOP: ' + (Write-A9Leftovers "03:15 cutoff at $($t.ToString('hh\:mm')); not started: $Unit")) } }
  function Assert-A9Sealed([string]$Root, [string]$Module) {
    $r = [IO.File]::ReadAllText("$Root\receipt.json") | ConvertFrom-Json
    if ([string]$r.status -cne 'SEALED') { throw "STOP: $Root receipt status is $($r.status)" }
    if ($Module -and [string]$r.module_sha256 -cne $Module) { throw "STOP: $Root module $($r.module_sha256) != $Module" }
    return $r }
  'H0 ok'
}
```

**H1. Pre-checks, the night dir, the v0.1 stat and the data-root stat.** The floors follow M
docs/operations/HOST_LOAD_POLICY.md:415-425. The lease state comes from M scripts/ops/workload_admission.ps1:2352.
Expected output: listings, then `H1 ok data-root segments <found>/<listed>`. Receipts: `$A9\h1-stat.txt` and
`$A9\h1-data-root.txt`.

```powershell
. {
  Assert-A9Start 'H1'
  . "$Prod\scripts\ops\workload_admission.ps1"; . "$Prod\scripts\ops\memory_guard_status_reader.ps1"
  if ((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod).Active) { throw 'STOP: shared lease busy at H1' }
  $commit = (Read-WeatherMemoryGuardStatus -Path "$Prod\data\logs\memory_commit_guard_status.json").row.commit_percent
  if ([double]$commit -ge 70) { throw "STOP: commit_percent $commit >= 70" }
  $free = (New-Object IO.DriveInfo 'C').AvailableFreeSpace
  if ($free -lt 50GB) { throw "STOP: volume free $free bytes < 50 GiB" }
  foreach ($p in @($A9, $X, $T, $V28Exam)) { Assert-A9Fresh $p }
  # The exam wrapper refuses an exam root with .git in it or any ancestor (wrapper :151-153): prove that first.
  for ($dir = New-Object IO.DirectoryInfo $V28Exam; $null -ne $dir; $dir = $dir.Parent) {
    if (Test-Path -LiteralPath (Join-Path $dir.FullName '.git')) { throw "STOP: .git at $($dir.FullName); exam root would be refused" } }
  if (-not (Test-Path -LiteralPath $Data -PathType Container)) { throw "STOP: $Data missing" }
  if (-not (Test-Path -LiteralPath $Rel -PathType Container)) { throw "STOP: $Rel missing (run R0 at registration)" }
  if (@(Get-ChildItem -LiteralPath $Rel -Force).Count) { throw "STOP: $Rel is not empty" }
  New-Item -ItemType Directory -Path $A9 | Out-Null
  $side = @("$C2b\calibration-20261003T050423Z\calibration-ledger.jsonl", "$C2b\calibration-20261003T050423Z\exporter-module-sha256.txt",
            "$C2\calibration\calibration-ledger.jsonl", "$C2\exporter-module-sha256.txt")
  $need = @("$V27\receipt.json", "$V27\bundle\bundle.json", "$V27\bundle\events.jsonl", "$V27\bundle\export.json",
            "$V29\receipt.json", "$V29\bundle\bundle.json", "$V29\bundle\events.jsonl", "$V29\bundle\export.json") + $side
  $miss = @($need | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
  if ($miss.Count) { throw "STOP: missing $($miss -join '; ')" }
  foreach ($v in @($V27, $V29)) { if (Test-Path -LiteralPath "$v\pending") { throw "STOP: $v\pending exists (unsealed attempt)" } }
  $r27 = Assert-A9Sealed $V27 ''; $r29 = Assert-A9Sealed $V29 ''
  $lines = @(Get-ChildItem -LiteralPath $V27, $V29 -Recurse -File) + @(Get-Item -LiteralPath $side) |
    ForEach-Object { "{0}`t{1}`t{2:o}" -f $_.FullName, $_.Length, $_.LastWriteTimeUtc }
  Write-A9New "$A9\h1-stat.txt" ($lines -join "`r`n"); $lines
  # Data-root confirmation, stat only (§7a(a)): every sealed segment a receipt names must exist under $Data.
  $seg = @(); $listed = 0
  foreach ($pair in @(@('2026-09-27', $r27), @('2026-09-29', $r29))) {
    $day, $r = $pair
    if (-not (@($r.PSObject.Properties.Name) -contains 'sealed_segments')) { $seg += "$day sealed_segments omitted (details_omitted)"; continue }
    foreach ($id in @($r.sealed_segments.PSObject.Properties.Name)) {
      if ($id -cnotmatch '\A(?:[01]\d|2[0-3])-[0-9a-f]{12}\z') { throw "STOP: unexpected segment id $id" }
      $listed++; $p = "$Data\maker_evidence\$day\$id\manifest.json"
      $seg += "$p`t$(Test-Path -LiteralPath $p -PathType Leaf)" } }
  $found = @($seg | Where-Object { $_ -like "*`tTrue" }).Count
  Write-A9New "$A9\h1-data-root.txt" ($seg -join "`r`n")
  if ($listed -eq 0 -or $found -ne $listed) { throw "STOP: data root unconfirmed: $found of $listed segment manifests under $Data (O5)" }
  "H1 ok data-root segments $found/$listed"
}
```

**H2. Fresh locked worktrees: exam tree X and the driver.** Light; `$Prod`'s working tree is untouched. The wrapper
requires X to be a locked, clean worktree of `$Prod` at the pin, outside `$Prod` (wrapper :131-145). Expected output:
`H2 ok`. Receipt: `$A9\h2-worktrees.txt`.

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
    if ($LASTEXITCODE -ne 0) { throw "STOP: worktree lock $path failed" }
    if (([string](& git -C $path rev-parse HEAD)).Trim() -cne $sha) { throw "STOP: $path HEAD is not $sha" }
    if (@(& git -C $path status --porcelain --untracked-files=all).Count) { throw "STOP: $path is not clean" }
  }
  Write-A9New "$A9\h2-worktrees.txt" "X=$X $ExamPin`r`nT=$T $DrvSha"; 'H2 ok'
}
```

**H2b. U6 deploy-tree pins (light, unleased).** This mirrors U6B P2 (U6B:302-321): `WRAP1` is the file SHA-256 of
the runner, and `MOD1` is the v0.2 `module-hash` under `PYTHONPATH=$D\src`. Expected output:
`H2b ok MOD1=<MOD1> files=63`. Receipt: `$A9\h2b-u6-pins.json`.

```powershell
. {
  if (-not (Test-Path -LiteralPath "$D\src" -PathType Container)) { throw "STOP: U6 deploy tree $D missing (Q6 deploy first)" }
  if (([string](& git -C $D rev-parse HEAD)).Trim() -cne $USha) { throw "STOP: $D HEAD is not $USha" }
  if (@(& git -C $D status --porcelain --untracked-files=all).Count) { throw "STOP: $D is not clean" }
  $w = (Get-FileHash -LiteralPath "$D\scripts\ops\replay_bundle_export_nightly.ps1" -Algorithm SHA256).Hash.ToLowerInvariant()
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$D\src", 'Process'); Push-Location -LiteralPath $D
  try { $j = (& $Py -P -B -m weather.market.maker_replay_night_v02 module-hash) | ConvertFrom-Json; $rc = $LASTEXITCODE }
  finally { Pop-Location; [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  Write-A9New "$A9\h2b-u6-pins.json" (@{ sha = $USha; MOD1 = [string]$j.module_sha256; MOD1_files = $j.files; WRAP1 = $w } | ConvertTo-Json -Compress)
  if ($rc -ne 0 -or [string]$j.module_sha256 -cne $MOD1 -or $j.files -ne $MOD1Files) { throw "STOP: MOD1 $($j.module_sha256) ($($j.files)) != $MOD1 ($MOD1Files); never adopt a host value (U6B:459)" }
  if ($w -cne $WRAP1) { throw "STOP: WRAP1 $w != $WRAP1" }
  "H2b ok MOD1=$MOD1 files=$MOD1Files"
}
```

**H3. Module guard for X (light, unleased).** `module-hash` reads no data (X maker_replay_night.py:282, 307-310). The
binding value is c2b's: both its module file and its 09-27 receipt. `$V01x` is a cross-check only. Expected output:
`H3 ok module=<64-hex>`. Receipt: `$A9\h3-module.txt`.

```powershell
. {
  $txt = ([IO.File]::ReadAllText("$C2b\calibration-20261003T050423Z\exporter-module-sha256.txt")).ToLowerInvariant()
  $m = [regex]::Match($txt, '[0-9a-f]{64}'); if (-not $m.Success) { throw 'STOP: no hash in the c2b module file' }
  $V01 = $m.Value
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$X\src", 'Process'); Push-Location -LiteralPath $X
  try { $out = (& $Py -P -B -m weather.market.maker_plugin.replay_export module-hash) -join ''; $rc = $LASTEXITCODE }
  finally { Pop-Location; [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  if ($rc -ne 0) { throw "STOP: module-hash exited $rc" }
  $live = [string]($out | ConvertFrom-Json).module_sha256
  $r27 = Assert-A9Sealed $V27 ''
  Write-A9New "$A9\h3-module.txt" "x_live=$live`r`nc2b_file=$V01`r`nc2b_0927_receipt=$($r27.module_sha256)`r`nworkstation_x=$V01x"
  if ($live -cne $V01 -or $live -cne [string]$r27.module_sha256) { throw 'STOP: X does not hash to the c2b exporter module (O1)' }
  if ($live -cne $V01x) { "WARN: host X hash differs from the workstation's $V01x (interpreter); c2b agreement governs" }
  "H3 ok module=$live"
}
```

**H4. Unit 1: v0.1 09-28 through the admitted exam wrapper, under an outer 03:15 deadline.**

The wrapper is called unchanged (M scripts/ops/maker_replay_exam_step.ps1). It accepts these arguments as follows:
- **Parameters.** `-Step calibration -Worktree -Pin -ExamRoot -RepoRoot -DataRoot -Day -AttemptRoot -ModuleSha256`
  are its declared parameters (:39-57). `-ModuleSha256` must be 64-hex (:56). `-ReleaseRoot` is required only for
  `night` (:319), so none is passed.
- **Worktree.** It must be outside `-RepoRoot`, at the pin, clean, and a locked worktree of `-RepoRoot` (:131-145).
  H2 provides this.
- **Exam root.** It must be outside the data root (:150), with no `.git` in it or any ancestor (:151-153); H1 proves
  both. The wrapper creates `operator\` inside it (:154-156).
- **Attempt root.** It must be `calibration-*` inside the exam root (:301-303) and already exist (:305), with no
  foreign subdirectories (:306-310) and the day not yet attempted (:311-313). H4 creates it empty.
- **Day.** 2026-09-28 is a calibration day (:68, 320) and closed (:321). The time window is 00:30-08:50 (:185-193, 322).
- **Module hash.** The live hash must equal `-ModuleSha256` (:323-324). That value is `$V01` from H3.
- **Exporter call.** The wrapper's own tokens are `calibration --day --data-root --out --expected-module-sha256` plus
  its limits (:328-332). It holds the shared lease around the child (:205-209) and proves teardown before releasing
  (:228-240).
- **Pass.** A SEALED receipt (:334) and exit 0 (:335).

The wrapper caps its child only to 08:50 (:71, 185-197), so H4 enforces 03:15 from outside:
- The wrapper's `powershell.exe` runs as the only member of a kill-on-close Job (M
  scripts/ops/windows_kill_on_close_job.ps1:691-716; `KILL_ON_JOB_CLOSE` :186-200; no breakaway flag). Its Python
  child, in the wrapper's own nested Job, is therefore inside the outer Job as well.
- At 03:15 local, `TerminateAndWait` kills the whole tree and proves zero processes (:641-667).
- The wait is a drain loop with a deadline, not `Wait-Process`. The capture is single-reader polling and must be
  drained while waiting (:389-390, 561-566).
- A killed wrapper abandons the lease mutex, and the next `Enter-WeatherHeavyWorkloadLease` acquires it through
  `AbandonedMutexException` (M workload_admission.ps1:1799-1812).

Expected output, three cases:
- **Sealed:** `v01 2026-09-28 SEALED module=<V01> bytes=<n>`.
- **Killed at 03:15:** `STOP: v01 2026-09-28 killed at the 03:15 deadline ... Leftovers move to 10-22: ...`.
- **Refused:** `STOP: wrapper exit <c>`. The cause is in the wrapper's `REFUSED:` stderr line.

Receipts:
- `$V28\receipt.json` and `$V28Root\calibration-ledger.jsonl`, written by the exporter;
- `$V28Exam\operator\<stamp>-calibration_2026-09-28.{stdout,stderr}.log`, written by the wrapper (:203-204, 214-217);
- `$A9\v01-2026-09-28.{stdout,stderr}.log` (wrapper output) and `$A9\v01-2026-09-28.step.json`.

```powershell
. {
  Assert-A9Start 'v01 2026-09-28'
  $log = "$A9\v01-2026-09-28"
  foreach ($p in @($V28Exam, "$log.stdout.log", "$log.stderr.log", "$log.step.json")) { Assert-A9Fresh $p }
  . "$Prod\scripts\ops\workload_admission.ps1"; . "$Prod\scripts\ops\windows_kill_on_close_job.ps1"
  if ((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod).Active) { throw 'STOP: shared lease busy before v01 2026-09-28' }
  $now = Get-A9Local; $deadline = $now.Date.Add([TimeSpan]'03:15:00')
  if (($deadline - $now).TotalSeconds -lt 600) { throw ('STOP: ' + (Write-A9Leftovers 'under 600 s before 03:15; v01 not started')) }
  New-Item -ItemType Directory -Path $V28Exam | Out-Null
  New-Item -ItemType Directory -Path $V28Root | Out-Null
  $ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $tokens = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "$Prod\scripts\ops\maker_replay_exam_step.ps1",
    '-Step', 'calibration', '-Worktree', $X, '-Pin', $ExamPin, '-ExamRoot', $V28Exam, '-RepoRoot', $Prod,
    '-DataRoot', $Data, '-Day', '2026-09-28', '-AttemptRoot', $V28Root, '-ModuleSha256', $V01)
  $job = $null; $cap = $null; $child = $null; $killed = $false; $code = $null; $proved = $false; $tdErr = $null
  $clock = [Diagnostics.Stopwatch]::StartNew()
  try {
    $job = New-WeatherKillOnCloseJob
    $cap = [Weather.Operations.KillOnCloseJob+CapturedOutput]::new("$log.stdout.log", "$log.stderr.log", 8388608)
    $child = Start-WeatherProcessInJob -Job $job -FilePath $ps -ArgumentString (ConvertTo-WeatherWindowsArgumentString -Tokens $tokens) `
      -WorkingDirectory $Prod -OutputCapture $cap
    $null = $child.Handle
    while (-not $child.HasExited) {
      if ((Get-A9Local) -ge $deadline) { $killed = $true; break }
      $cap.Drain(); Start-Sleep -Milliseconds 200; $child.Refresh() }
    if (-not $killed) { $child.WaitForExit(); $code = [int]$child.ExitCode }
  } finally {
    try { if ($job) { $job.TerminateAndWait(10000) }; $proved = $true; if ($cap) { $cap.Complete(2000) } }
    catch { $tdErr = $_.Exception.Message }
    finally { if ($cap) { $cap.Dispose() }; if ($child) { $child.Dispose() }; if ($job) { $job.Dispose() } } }
  Write-A9New "$log.step.json" (@{ unit = 'v01 2026-09-28'; exit_code = $code; killed_at_deadline = $killed; teardown_proved = $proved
    teardown_error = $tdErr; runtime_seconds = [Math]::Round($clock.Elapsed.TotalSeconds, 3); exam_root = $V28Exam; attempt_root = $V28Root } | ConvertTo-Json -Compress)
  if (-not $proved) { throw "STOP: child tree not proved gone ($tdErr); start nothing else; HOST_LOAD_POLICY.md:33-40" }
  if ($killed) { throw ('STOP: ' + (Write-A9Leftovers "v01 2026-09-28 killed at the 03:15 deadline; $V28Root is spent, 10-22 uses a new -$N root")) }
  if ($code -ne 0) { throw "STOP: wrapper exit $code (see $log.stderr.log)" }
  $r = Assert-A9Sealed $V28 $V01; $Done.Add('v01 2026-09-28')
  "v01 2026-09-28 SEALED module=$($r.module_sha256) bytes=$($r.bundle.bytes)"
}
```

**H5. Units 2-7: the U6 runner, serial, in Q9 order.**
- The runner's parameters are at U :17-28. Its start window is 00:30-04:54, and its deadline is the earlier of +2,730 s
  and 04:54:45 (U :53-67).
- The **output parent** must exist (U :175-178), and the output must be disjoint from the data and release roots (U :167-173).
- It takes and releases the lease itself (U :193-195).
- Expected output per unit: `<kind> <day> rc=0 SEALED`. Exit 3 is `PANEL_GATED`, which cannot happen for these dates.
- Receipts: `$A9\p1-night\<day>\receipt.json` or `$A9\p2-calibration\<day>\receipt.json`, plus `$A9\u6-<kind>-<day>.{out,err,rc}`.

```powershell
. {
  foreach ($r in @("$A9\p1-night", "$A9\p2-calibration")) { if (-not (Test-Path -LiteralPath $r)) { New-Item -ItemType Directory -Path $r | Out-Null } }
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

In H5, `-OutputRoot` is the per-kind root, so the day folder is `<root>\<day>`. The exporter creates it under an
existing parent (U src/weather/market/maker_replay_night_v02.py:110-120).

**H6. Leftovers.** `$A9\leftovers-*.txt` names the units. On 10-22, run:
1. H0 with `$Night = '20261022'`;
2. H1 and H2 (fresh `-20261022` worktrees);
3. H2b and H3;
4. H4 only if v0.1 09-28 is listed (a new exam root `a9-20261022-0928-1`);
5. H5. It skips units that have no leftover entry: after H0, master marks the 10-21-sealed units with `$Done.Add('<unit>')`.

**H7. Build (light, unleased).** It needs exactly one SEALED root per unit across `$Nights`, and names literal paths
only. Expected output: DRV JSON with `"verdict": "BUILT"` and `manifest_sha256` (DRV :124-125). Exit 2 prints
`refused: <code>`; under Q11, stop and report. Receipts: `$A9\transfer_manifest.json` and `$A9\h7-build.json`.

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
  $roots += '--root', ('calibration_v01_reference=' + (Find-A9Sealed @($Nights | ForEach-Object {
      "$G\mrv2-cal\a9-$_-0928-1\calibration-a9-$_-0928-1\2026-09-28" })))
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

**H8. Hash relay.** A stat and hash only. Expected output: the relay lines. Receipt: `$A9\relay.txt`; master relays
its content out of band.

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

Everything on the host is kept as evidence: `$A9`, `$X`, `$T` and the new `a9-<NIGHT>-0928-<n>` root. Nothing is moved or deleted.

## 7a. Master's questions (a), (b) and (c)

**(a) Which key records the data root?**
- **No receipt, ledger or `export.json` key records the data-root path.** `--data-root` is a required CLI argument (X maker_replay_night.py:290). It is used only to open inputs (X :183, 210, 220).
- The receipt keys are listed at X :203-206, 212-213, 237-239 and 249-251; `export.json` is at X
  src/weather/market/maker_replay_bundle.py:432-434. None of them is a path.
- How the exporter derives its input:
  - it reads sealed segments at `<data-root>\maker_evidence\<day>\<HH-12hex>\manifest.json` (X
    src/weather/market/maker_plugin_capture.py:283-298);
  - every input key in `input_hashes` is a path *relative to* the data root (X maker_replay_bundle.py:54-55);
  - the receipt keeps `sealed_segments` (segment id to manifest hash, X maker_replay_night.py:99, 212).
- So the data root is provable only indirectly. H1 stats `<$Data>\maker_evidence\<day>\<segment>\manifest.json` for
  every segment named in the 09-27 and 09-29 receipts, and stops unless all exist. This is stat only; no content is read.
- A stronger proof would re-hash `input_hashes` entries. That reads data, so it is not in this plan.
- If a receipt omitted `sealed_segments` (`details_omitted`, X :252-256), H1 stops and reports.

**(b) What must the release root contain?**
- **Exam wrapper / X `calibration`:** nothing. `--release-root` is passed only for `night` (wrapper :319, 329). With
  no release root, X projects the captured row's own `release_calibration_method` (X
  src/weather/market/maker_replay_release.py:20-22).
- **U6 runner (U):** `-ReleaseRoot` is mandatory (U :21). It must be an absolute, normalized path with no quotes or
  newlines, and every existing component must be an ordinary non-reparse directory (U :69-81, 157). It must be
  disjoint from `-OutputRoot` (U :167-173). The runner passes it to the v0.2 exporter for both kinds (U :219-221).
- **The v0.2 exporter (U):**
  - It refuses a release root that overlaps the output (U maker_replay_night_v02.py:103-107).
  - It reads the release root only for a captured source row whose `release_identity_status` is
    `verified_variant_serving_bundle` (U maker_replay_release.py:55-62). `for_event` runs for every in-horizon event
    regardless of kind (U maker_replay_bundle.py:373, 422).
  - For each such `(release_id, release_manifest_sha256, market)`, it needs:
    1. `<Rel>\<release_id>\release_manifest.json`, whose `schema_version` is the registry's `release_manifest`
       version and whose `release_id` and `manifest_sha256` equal the captured values and the content hash (:26-32);
    2. exactly one inventory entry with `role` = `base_model.<market>.probability_calibration`, `declared` true and
       `kind` `calibration` (:33-37);
    3. that artifact at `<Rel>\<release_id>\<path>`, with matching `bytes` and `sha256`, as JSON carrying a non-empty
       `market_bin.method` (:38-46).
  - Each read is limited to 2 MiB and hash-recorded as `release:<relative path>` (U maker_replay_bundle.py:94-102).
- **A fresh release root:**
  - An empty directory passes every path check.
  - It suffices only if no captured row for the day is a verified release. Otherwise the read fails, the receipt is
    `REFUSED` and the runner exits non-zero, which is a refusal, never a mis-record (Q11).
  - It would need copies of exactly the releases those rows name. Their ids are visible only in the captured data.
- **The canonical location** is `artifacts\releases` (U src/weather/release_artifacts.py:49;
  src/weather/artifacts.py:36). It does not exist on the host (master stat, r6), so see (b2).

**(b2) Is the verified marker written in the current configuration? (r6, code and docs only; every file below is identical at M and U)**
- **Only one writer:** `serving_bundle_lineage`, which emits `verified_variant_serving_bundle` only when the bundle status
  is `BOUND` (M src/weather/release_serving.py:899-917). Every other status maps to an unverified value (:922-935).
  `worker_release_binding.py:42` and the readers only compare against it.
- **`BOUND` needs the active pointer.** `load_verified_active_serving_bundle` returns `RESEARCH_UNBOUND` ("no active
  release pointer") when the pointer is absent (:513-521). `BOUND` is set only after the pointer and the release
  verify (:522-585).
- **The pointer is the default path.** It is `artifacts\releases\current_release.json` (M
  src/weather/release_artifacts.py:49-50; M src/weather/paths.py:12). Capture callers use that default (M
  src/weather/collection/snapshot_store.py:210-214; M src/weather/market/market_making_run.py:1218; M
  src/weather/market/worker_release_binding.py:75, 84-108). The tracked scheduled-task contract passes the same path
  (M scripts/ops/daily_refresh_contract.ps1:129, 140).
- **Not tracked.** `artifacts\releases` is not a tracked directory (the M tree `artifacts/` holds calibration,
  manifests, misc and models only), and master's stat shows no such folder on the host.
- **Verdict:** the marker is written only when a variant serving bundle is served, and that is **never in the current
  configuration**. Captured rows carry `research_unbound_non_countable` with an empty `release_id` (:922-935), so the
  exporter never reads the release root (U maker_replay_release.py:55-59). **U6 can start with an empty fresh `$Rel`.**
  A verified row, if one existed, would refuse the day (Q11).

**(c) MOD1, WRAP1 and V01 for U, recomputed as P2 does.**
- **Pin code:** U6B P2 (U6B:302-321).
  - `WRAP1` = `Get-FileHash -Algorithm SHA256` of `scripts\ops\replay_bundle_export_nightly.ps1`.
  - `MOD1` and `V01` are the `module-hash` JSON of `weather.market.maker_replay_night_v02` and
    `weather.market.maker_plugin.replay_export`, each run with `-P -B` and `PYTHONPATH=<tree>\src` from the tree.
  - It imports no test machinery.
- **How it was run:** read-only on the workstation, in a fresh detached worktree `C:\wt\u6-pin-check` at `67cad7be2`,
  created with `GIT_LFS_SKIP_SMUDGE=1`. The worktree was clean and has been removed. The interpreter was the
  workstation venv, Python 3.11.9.

| Value | Result at `67cad7be2` | Files |
| --- | --- | --- |
| `MOD1` (v0.2 closure) | `dbb118d4c247826cc278dac468a8d5a38ab8e46d484d440f1eb7e30949089beb` | 63 |
| `WRAP1` (runner file) | `8dd29ad3495d33c53bedfdacaaa3e6d342bb55891256a2554e20a15830fc1143` | n/a |
| `V01` (v0.1 facade closure in U) | `07bb8e32b152e33621a6b06b312adc72206f6f516d32bffe11ae87e3f9d5e6c3` | 57 |

- **WRAP1 is line-ending stable.** `.gitattributes` sets `* text=auto eol=lf`, and the working file equals the blob
  (both are `8dd29ad3…`).
- **All three differ from the 10-10 attempt** (MOD1 `abc38cea…` with 62 files, WRAP1 `bc7c19c3…`, V01 `089cb29a…`),
  as expected for a newer tip.
- **The U6 runner never uses U's V01.** It launches only v0.2 (U :219).
- **The exam-tree value `$V01x` is a different number.** It is X's own `module-hash`, computed the same way in a fresh
  worktree at `6ac18be7e` (since removed): `f97ce024a46f907c4ec64e34811a7f46d9c447fdd2e869788a8398efa8a041c0`, 55 files.
  The wrapper's four-module probe also resolved inside that tree (wrapper :76-77, 169-175).
- **Interpreter caveat (U6B:459):** a host interpreter that loads a different closure gives a different value. H2b
  stops on that, and H3 warns.

## 8. Workstation block (steps 7-9)

Windows PowerShell 5.1 on the 32 GB workstation, after the relay. Paste `relay.txt`'s lines into `$Relay`.

**W7. Pull by exact name (never `.writer.lock`).** scp overwrites silently, so every destination is first asserted
absent. Expected output: `W7 ok 9 roots`. Receipt: `$I\w7-pull.txt`.

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

**W8. Verify through `workstation_heavy.ps1`.**

**Landing dependencies:**
- **O7:** `6c3c4792b` (W7B) adds `"maker_core.replay.v2.transfer_cli"` to `Get-WeatherWorkstationOfflineModule`
  (W7B scripts/ops/workload_admission.ps1:611-639, entry :616).
- **O6:** DRV is landed.

W8 runs from a fresh worktree of the **landed master commit that contains both**.

The wrapper contract (W7B scripts/ops/workstation_heavy.ps1):
- **Parameters:** `-Kind weather_heavy -PythonPath -ArgumentsBase64 -RepoRoot` (:10-20).
- **`-RepoRoot`** must be the tree that owns the invoked wrapper (:57-66).
- **`-PythonPath`** must be an absolute `python.exe` (:68-80).
- **The arguments** are canonical base64 of a UTF-8 JSON string array of 2 to 128 entries (:82-106). The module is
  read only when `arguments[0]` is exactly `-m` (:108), and the module must be in the allowlist (:130-139). So no
  `-P`/`-B` comes first.
- **The child** runs with `-RepoRoot` as its working directory, under the `workstation_offline_v1` lease, and inherits
  the console (:162-199). It exits with the child's code (:236).
- **Imports:** `PYTHONPATH=$W\src` is set in the calling process and inherited, so imports resolve to the landed tree
  ahead of the venv's editable `.pth`. That `.pth` points at the main checkout's `src`.

Expected output: DRV JSON with `"verdict": "PASS"` (DRV :159) and exit 0. Receipts: `$I\w8-verify.json` (stdout) and
`$I\w8-verify.err`.

```powershell
. {
  $Land = '<LANDED_MASTER_SHA>'                         # OPEN O6/O7: master commit containing DRV and 6c3c4792b's allowlist entry
  if ($Land -cnotmatch '\A[0-9a-f]{40}\z') { throw 'STOP: $Land placeholder not replaced' }
  $Main = 'C:\Users\Michael\Documents\github\weather'; $VPy = "$Main\venv\Scripts\python.exe"
  $W = "C:\wt\a9-verify-$($Land.Substring(0, 9))"
  foreach ($p in @($W, "$I\w8-verify.json", "$I\w8-verify.err")) { if (Test-Path -LiteralPath $p) { throw "STOP: $p exists" } }
  [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', '1', 'Process')
  try { & git -C $Main worktree add --detach $W $Land; $wrc = $LASTEXITCODE }
  finally { [Environment]::SetEnvironmentVariable('GIT_LFS_SKIP_SMUDGE', $null, 'Process') }
  if ($wrc -ne 0) { throw "STOP: worktree add $W exited $wrc" }
  if (-not (Select-String -LiteralPath "$W\scripts\ops\workload_admission.ps1" -SimpleMatch '"maker_core.replay.v2.transfer_cli",' -Quiet)) {
    throw 'STOP: landed tree lacks the transfer_cli allowlist entry (6c3c4792b)' }
  if (-not (Test-Path -LiteralPath "$W\src\maker_core\replay\v2\transfer_cli.py" -PathType Leaf)) { throw 'STOP: landed tree lacks DRV' }
  $argv = [string[]](@('-m', 'maker_core.replay.v2.transfer_cli', 'verify', '--manifest', "$I\transfer_manifest.json",
    '--expected-manifest-sha256', $sha) + $VerifyRoots)
  $b64 = [Convert]::ToBase64String((New-Object Text.UTF8Encoding($false)).GetBytes((ConvertTo-Json -InputObject $argv -Compress)))
  [Environment]::SetEnvironmentVariable('PYTHONPATH', "$W\src", 'Process')
  try {
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$W\scripts\ops\workstation_heavy.ps1" `
      -Kind weather_heavy -PythonPath $VPy -ArgumentsBase64 $b64 -RepoRoot $W 1> "$I\w8-verify.json" 2> "$I\w8-verify.err"
    $rc = $LASTEXITCODE }
  finally { [Environment]::SetEnvironmentVariable('PYTHONPATH', $null, 'Process') }
  Get-Content -LiteralPath "$I\w8-verify.json"
  if ($rc -ne 0) { throw "STOP: verify exited $rc (see $I\w8-verify.err)" }
}
```

After PASS, check the pulled files only. Record the results in the master report.
- Each v0.1 ledger's row for its day has `status` `SEALED` (X maker_replay_night.py:73-88, 257-265).
- The three `calibration_v01_reference` entries share one `module_sha256`, and it equals both pulled
  `exporter-module-sha256.txt` values (DECISION_LOG.md:89).

**W9.** On PASS, master names a branch. Copy the byte-identical manifest to
`config\maker_replay_v2\transfer_manifest.json` in a fresh worktree with `Copy-Item -LiteralPath` (no `-Force`; the
target must not exist). Re-hash, commit and push; `config/` is roll-free. Then run the P3 rehearsal (R
tools/research/maker_replay_v2/rehearse_cli.py:1-11).

## 9. Verification and rollback

- **PASS:** W8 exit 0 and verdict `PASS`, plus the W8 checks.
- **Workstation:** leave `$I` and start a fresh inbox name. Revert a committed manifest with a new commit, never a force-push.
- **Host:** nothing is moved or deleted. A refused, killed or partial unit is never retried in place. The next night uses
  new `<NIGHT>` paths (wrapper :311-313; maker-replay-bundle.md:251-252).
- **Unproved teardown in H4:** stop and follow HOST_LOAD_POLICY.md:33-40.

## 10. Open items (not pinned down here)

- **O1.** Does X at `6ac18be7e` hash to c2b's exporter module? The workstation value is `f97ce024…` (55 files). The c2b
  file and the 09-27 receipt have not been read from here. H3 stops on disagreement. The pin may then be `6ac18be7e`
  plus the Clarification 3 hash commit (DECISION_LOG.md:89). Master's locked `weather-exam-deployed-6ac18be` is at
  `6ac18be7e`; H2 makes a fresh one at the same pin.
- **O2 (resolved by r5 design; one assumption).** H4 uses the wrapper unchanged. It assumes `$G` and its ancestors hold
  no `.git`, and H1 proves that.
- **O3 (resolved, pending deploy).** MOD1, WRAP1 and the U tip are in H0. The deploy tree for `67cad7be2` must exist
  (Q6 deploy), and H2b re-derives both values on the host.
- **O4 (resolved r6).** `$Rel` is the fresh empty R0 folder (§7a(b2)). Master runs R0 at registration on 10-20.
- **O5.** `$Data = $Prod\data` is master's proposal. H1's segment stat confirms it or stops.
- **O6.** The landed master sha of DRV (`$DrvSha` in H0 and `$Land` in W8), after Fable. Pushed tip: `0f2944548`.
- **O7 (dependency).** `6c3c4792b` must land before W8. W8 checks for the allowlist entry.
- **O8.** c2's 09-29 is recorded as "spent" (R STATE_OF_PLAY.md:44-45). H1 enforces SEALED. Module agreement between c2
  and c2b is checked at W8.
- **O9.** The format of `exporter-module-sha256.txt` is unknown. H3 takes its first 64-hex token and cross-checks it
  against the 09-27 receipt.
- **O10.** Capacity: v0.1 09-28 has no measured runtime. If it is killed at 03:15, it and the remaining U6 units move
  to 10-22.
