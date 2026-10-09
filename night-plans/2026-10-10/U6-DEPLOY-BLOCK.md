# U6 DEPLOY BLOCK: nightly replay-export wrapper from build line 6d1fa4b74 (N4/N5 night plan)

> **N4 assembler copy (2026-10-09).** Per master: the build line moved docs-only from `6d1fa4b74` to `89618c30c`; MOD, v0.1, WRAP, REG and JOB pins are unchanged (only docs/operations/maker-replay-bundle.md and maker-core-contracts.md changed). The deploy tip and DeployRoot in P0-P5, the verify list and the STOP table now read `89618c30cbe23f4b267728692ccf8bc0b1c2dd0b`; hash-evidence rows still name the tip where the hashes were computed. See §11.

> **Owner decision 2026-10-09 ~11:10 (relayed by master): the U6 registrar 04:10 slot is approved.** It is being built on the build line as `claude/u6-registrar-0410-20261009`. Registration of `WeatherReplayBundleExportNightly` stays owner-gated and not before 10-16; nothing in this block registers a task on N4 (fallback night N5).

Written 2026-10-09 ~05:50 by a workstation sub-agent (DESKTOP-RFCD2GH). Read-only. Nothing was run on the capture host,
nothing was pushed, and no Scheduler task was touched. The hashes were recomputed on the workstation from a detached
checkout of `6d1fa4b742f49856aeafd7907dcc96a78fc2e6c2`, which was then removed.

**Verdict.**
- **Deploy and prove on N4** (10-10), with N5 (10-11) as the fallback:
  - the exact-tip worktree;
  - the pins;
  - the PANEL_GATED refusal proof;
  - registrar `-WhatIf`;
  - the optional 03:40 shakeout.
- **Do NOT register the task on N4/N5.** STATE_OF_PLAY (master, "Current truth", Disk/91a bullet) says
  `WeatherReplayBundleExportNightly` "stays unregistered until at least 10-16". The real registration is the
  ACTIVATION BLOCK (§8). It needs an owner yes.
- **`-MinAvailableMiB 7168`.**
- **Always pass `-DeployRoot` / `-RepoRoot` explicitly.**

## 0. Fixed values (checked 2026-10-09 against origin)

| Item | Value | Evidence |
| --- | --- | --- |
| Build-line tip | `89618c30cbe23f4b267728692ccf8bc0b1c2dd0b` | `git ls-remote origin codex/maker-replay-v2-build-20261003` at 05:4x 10-09; D1-BUILDLINE-redo-report |
| MOD (v0.2 exporter closure; the U6 task's `-ExpectedModuleSha256`) | `abc38cea25ee564f3190c9f02cfc798048ddcc06b1fc9ff4555ebabf98bf3a11`, 62 files | D1 redo report; recomputed by me at 6d1fa4b74: `{"files": 62, "module_sha256": "abc38cea..."}` |
| v0.1 facade closure (`weather.market.maker_plugin.replay_export module-hash`) | `089cb29a5ed41fd3a2c0897be7e3e6eb4959e900d0079fbd248970144d51fa88`, 57 files | computed by me at 6d1fa4b74 (same method). Used only by the hand-run v0.1 refusal test, **never by the U6 task** |
| WRAP (`replay_bundle_export_nightly.ps1`, LF bytes) | `bc7c19c35c8be0b7ff857d6a481b3062761f5e27dece16c0b0aee825ccaf235d` | blob and working-tree bytes at 6d1fa4b74 (`* text=auto eol=lf`) |
| Registrar (`register_replay_bundle_export_nightly.ps1`) | `7082280cdeb6bde46bd88afb4cedbb211d88be03ae744de501b0ea0512b21fca` | same |
| Job helper (`replay_export_limited_job.ps1`) | `10e3ff4eb7e48eb714ea37a4efedb11991c908fdf7107650c571f44266edebb2` | same |
| Task name | `WeatherReplayBundleExportNightly`, daily 00:35 (`ValidateSet('00:35')`), S4U/Limited, 50-minute limit, IgnoreNew | registrar :17, :20, :73-78 |
| U6 child envelope | Job commit 2 GiB (job and per process), summed working-set poll 2 GiB, BelowNormal, budget at most 2,700 s, start 00:30-04:54, ends by 04:54:45 | wrapper :32-33, :59-66, :210-231 |

**Superseded pins (never use):**
- pre-SWOB: v0.1 `e10ac8b2…f76f`, v0.2 `11be8374…85ec`;
- SWOB-only at 876ac224f (no U6): v0.1 `2bdfe4ac…6e93`, v0.2 `0bcdb8a6…23c0` (SWOB-owner-ab-report "Hash-pin impact").

---

## 1. Open question 1: the `-DeployRoot` doc default

**What the docs say.** At 6d1fa4b74, `docs/operations/maker-replay-bundle.md`:
- line 359 says `-DeployRoot` has the "default: the tree that holds the invoked wrapper";
- lines 395-396 say the registrar's `-RepoRoot` has the "default: its own checkout".

**What the scripts require.**
- `replay_bundle_export_nightly.ps1:18` declares
  `[string]$DeployRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))`. Under Windows PowerShell 5.1
  `powershell.exe -File`, `$PSScriptRoot` is empty inside a param-block default, so the default throws
  (`ParameterArgumentValidationErrorEmptyStringNotAllowed`). The run exits **1 before the panel gate**, so a gated day
  gives 1, not 3. This is U6-wrapper-defender L1, reproduced by
  `test_finding_deployroot_default_is_dead_under_file_so_gated_day_exits_1_not_3`.
- The registrar's `-RepoRoot` default (`register_replay_bundle_export_nightly.ps1:9`) has the same defect (L1, last
  bullet).
- The wrapper also requires, at :153-154, that `-DeployRoot` equals the tree that holds the invoked wrapper
  (`DeployRoot must own the invoked wrapper`).
- At :71-73 it requires an absolute, normalized path (`GetFullPath(p) -cne p` refuses).
- The registrar always passes `-DeployRoot $RepoRoot` (:67-70), so the scheduled path works. Hand runs and a registrar
  run without `-RepoRoot` do not.

**Exact doc fix** (on the build line, docs only, roll-free; it does not change WRAP):

`docs/operations/maker-replay-bundle.md:359`. Replace the line
```
- `-DeployRoot` (default: the tree that holds the invoked wrapper, and it must be that tree) is the exact-tip code.
```
with
```
- `-DeployRoot` is the exact-tip code tree and must be the absolute, normalized path of the tree that holds the
  invoked wrapper (otherwise `DeployRoot must own the invoked wrapper`). **Always pass it explicitly.** Its declared
  default is computed from `$PSScriptRoot` in the `param` block, which is empty under `powershell.exe -File` in
  Windows PowerShell 5.1, so a run that omits it fails parameter binding with exit 1 before the panel gate (a gated
  day then exits 1, not 3). The registrar always passes it.
```
(The next line, "Its `src` is the child's only `PYTHONPATH`…", stays.)

`docs/operations/maker-replay-bundle.md:395-396`. Replace
```
`-MinAvailableMiB`. Its `-RepoRoot`
(default: its own checkout) is the deploy tree and is passed to the runner as `-DeployRoot`. It refuses equal or
```
with
```
`-MinAvailableMiB`. Its `-RepoRoot`
is the deploy tree and is passed to the runner as `-DeployRoot`; pass it explicitly, because its `$PSScriptRoot`
default has the same `-File` defect. `-WhatIf` checks paths, disjointness and the runner hash only, not the module
hash, the time zone or the host assignment. It refuses equal or
```

**Second stale doc, found while checking SWOB.** `docs/operations/maker-core-contracts.md:203-204` says
"`replay_export module-hash` (the nightly export's registered `-ExpectedModuleSha256`)". Since U6, the wrapper launches
`maker_replay_night_v02`, so the registered pin is the **v0.2** `module-hash`. Replace
```
night exporters' module closure, so `replay_export module-hash` (the nightly export's registered
`-ExpectedModuleSha256`), the v0.2 `module-hash` and `execution_manifest.source_hashes` change and must
```
with
```
night exporters' module closure, so the v0.2 `module-hash` (the nightly export's registered
`-ExpectedModuleSha256` since U6), the v0.1 `replay_export module-hash` and `execution_manifest.source_hashes` change and must
```

**Code fix (optional, later).** Make `-DeployRoot` mandatory in the wrapper, or compute it in the body from
`$PSCommandPath`. This changes WRAP. Bundle it with the reviewed U6-Q1 `-OwnerDecision` wrapper change, which re-pins
WRAP anyway. Do not change it now.

**Value to use on the host:**
`-DeployRoot C:\Users\micha\Desktop\github\weather-exam-deployed-89618c30cbe23f4b267728692ccf8bc0b1c2dd0b`
- No trailing backslash, no 8.3 short name, no relative segment.
- It must be the same folder whose `scripts\ops\replay_bundle_export_nightly.ps1` is passed to `-File`.
- For the registrar, pass `-RepoRoot` with this same value.
- The longest repo path is 108 characters, so the deepest path is about 201 characters, under MAX_PATH.

## 2. Open question 2: stale commands in P-rehearsal-plan-v2.md

Parameter names were checked against the wrapper at 6d1fa4b74 (`param` :17-28). The wrapper has **no** `-RepoRoot`.
`-ProductionRoot`, `-DataRoot`, `-ReleaseRoot`, `-OutputRoot`, `-ExpectedModuleSha256`, `-ExpectedSelfSha256` and
`-MinAvailableMiB` are mandatory.

Stale commands fail in one of two ways. A `-NonInteractive` run fails with a binding error (exit 1). Without
`-NonInteractive`, the run **prompts** for the missing mandatory parameters. Neither gives exit 3.

| # | Plan line(s) | Stale | Corrected |
| --- | --- | --- | --- |
| S1 | §3.0 :177-180 wrapper refusal | `powershell -NoProfile -File …\replay_bundle_export_nightly.ps1 -RepoRoot <DEPLOY1> -DataRoot … -ExpectedModuleSha256 <MOD1> -ExpectedSelfSha256 <WRAP1> -Kind night -Day 2026-09-30` | `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\replay_bundle_export_nightly.ps1" -DeployRoot $D -ProductionRoot $Prod -DataRoot "$T\empty-data" -ReleaseRoot "$T\empty-release" -OutputRoot "$T\out" -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB 7168 -Kind night -Day 2026-09-30 2> "$T\wrapper-2026-09-30.err"`. This is the registrar's own token form (registrar :67-70). |
| S2 | §3.0 :185-188 python v0.2 night refusal | `Set-Location <DEPLOY1>; & <HOST_PY> -B -m weather.market.maker_replay_night_v02 night …`. There is no `-P` and no `PYTHONPATH`. `src\` is not on `sys.path` from the deploy root, and **master has no `maker_replay_night_v02` or `export_gate`**, so this tests the wrong code or fails with ModuleNotFoundError | `$env:PYTHONPATH="$D\src"; Push-Location $D; & $Py -P -B -m weather.market.maker_replay_night_v02 night --day 2026-10-05 --data-root "$T\empty-data" --release-root "$T\empty-release" --out "$T\out" --expected-module-sha256 $MOD1; Pop-Location; Remove-Item Env:PYTHONPATH`. Expect exit **2** and stderr `night refused: BundleError: panel_export_requires_signed_registration` (`maker_replay_night_v02.py:218`, `export_gate.py:89-90`). |
| S3 | §3.0 :189 "likewise" calibration and v0.1 | the same `-B` without `-P`/`PYTHONPATH`; the v0.1 call has no hash value | `… maker_replay_night_v02 calibration --day 2026-09-30 --data-root "$T\empty-data" --out "$T\out" --expected-module-sha256 $MOD1` and `… weather.market.maker_plugin.replay_export night --day <latest closed gated> --data-root "$T\empty-data" --release-root "$T\empty-release" --out "$T\out" --expected-module-sha256 $V01` (`$V01 = 089cb29a…fa88`), in the same `PYTHONPATH`/`-P` frame |
| S4 | §3.1 :243-245 pin check | `& <HOST_PY> -B -m … module-hash   # must print <MOD2>`. This prints **JSON**, not a hash, and imports the wrong tree. `(Get-FileHash …).Hash` is **upper-case** and is compared to a lower-case pin | `$MOD = ((& $Py -P -B -m weather.market.maker_replay_night_v02 module-hash) \| ConvertFrom-Json).module_sha256` (with `PYTHONPATH=$D\src`, cwd `$D`); `(Get-FileHash -LiteralPath … -Algorithm SHA256).Hash.ToLowerInvariant()`; compare with `-cne` |
| S5 | §3.1 :247-251 P1 export (and §3.0 shakeout, §3.2 :322 P2 "the P1 command with `-Kind calibration`", which inherit it) | `-RepoRoot <DEPLOY2>`; no `-ProductionRoot`; no `-MinAvailableMiB` | `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D2\scripts\ops\replay_bundle_export_nightly.ps1" -DeployRoot $D2 -ProductionRoot $Prod -DataRoot <HOST_DATA_ROOT> -ReleaseRoot <HOST_RELEASE_ROOT> -OutputRoot C:\Users\micha\Desktop\github\mrv2-cal\<attempt-id>\p1-night -ExpectedModuleSha256 <MOD2> -ExpectedSelfSha256 <WRAP2> -MinAvailableMiB 7168 -Kind night -Day 2026-09-27`. Note: the output **parent** must already exist (wrapper :170-173). |
| S6 | §0.2 :65 | "`<HOST_REPO>` … Never the `-RepoRoot` of a P-step." | "Never the `-DeployRoot` of a P-step; it is always `-ProductionRoot`." |
| S7 | §5 :553 skip rule | "Task Scheduler shows a `replay_bundle_export_nightly` task" | `Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue` returns a task. `replay_bundle_export_nightly` is the **lease workload** name (wrapper :188), not the task name. |
| S8 | §5 :550 memory read | `Get-CimInstance Win32_OperatingSystem` `FreePhysicalMemory`, used as the admission source | Keep it as the pre-check reading. The binding admission is the wrapper's own `GlobalMemoryStatusEx` read against `-MinAvailableMiB` just before launch (wrapper :220-221). The plan's in-run abort at 3,328 MiB (W-ADM, Q17) **is not in the U6 wrapper**: it polls only its own Job's working set (:226-234). So admission must cover the whole envelope (see §3). |
| S9 | §0.2 `<DEPLOY1>` "sha1: U6 + W-ADM" | sha1 is now the D1 landing | sha1 = `6d1fa4b74` = SWOB 876ac224f + U6 b88f5565b on 501f47579 (W-ADM is inside b88f5565b) |

PowerShell 5.1 note for every corrected command: run it with `$ErrorActionPreference = 'Continue'`. With `'Stop'`, a
native command's `2>` redirect turns stderr into a terminating NativeCommandError, so you lose `$LASTEXITCODE`.

## 3. Open question 3: `-MinAvailableMiB`

**Recommendation: `7168`.**

| Term | MiB | Source |
| --- | --- | --- |
| U6 child envelope: Job commit ceiling = per-process ceiling = working-set poll stop | 2,048 | wrapper :32-33 (`2GB`), :109, :222 |
| Two snapshot-fleet worker slots, 2 × 1,792 MiB tree cap | 3,584 | HOST_LOAD_POLICY "Snapshot fleet capture admits at most two isolated children … 1,792 MiB" (master HLP ~:246-249) |
| Capture reserve for the snapshot parent and other capture loops | 1,536 | HLP ~:261-263 ("must leave 1,536 MiB available"); the Stage-A rule "plus a 1.5 GiB capture reserve" (~:293) |
| **Sum** | **7,168** | = P-defender PM2 amendment, adopted as P-rehearsal-plan-v2 PM2 and §5 (":≥ 7,168 MiB") |

**Why this number:**
1. **Admission is one reading at launch, with no in-run memory abort.** The wrapper reads available physical memory
   once, after the import probe and before the child starts (:220-221), and then polls only its own Job. A launch must
   therefore leave room for the child's *whole* ceiling, plus a two-worker snapshot launch, plus the reserve. HLP: the
   loop "uses two only above the complete 5,120 MiB requirement" (~:264).
   - At 4,096 (the D1 report and exploratory-spec value), a child that grows to its 2 GiB ceiling leaves about
     2,048 MiB.
   - That is below even **one** worker launch (1,792 + 1,536 = 3,328 MiB). The result is a snapshot-loop admission
     failure, a capture-evidence cost (P-defender PM2).
   - Capture evidence is the first objective (AGENTS.md; established findings §0d).
2. **The worker caps are measured, not guessed.** HLP sets the 1,792 MiB cap above a measured 1,598,382,080-byte
   (1,524 MiB) production child peak on 2026-07-16.
3. **The child will usually be far below its ceiling,** but this is not measured on production v0.2. The W2 S2
   fixture day (170 conditions, 1 BLAS thread) peaked at **0.303 GiB** (EXPLORATORY-SHADOW-HOST-SPEC §5). Because the
   Job enforces 2 GiB and nothing re-checks memory mid-run, admission reserves the ceiling, not the expectation.
4. **The host has 15.7 GiB ≈ 16,077 MiB** (HOST-FACTS). At 7,168, a launch is admitted only while everything else
   (OS, snapshot parent, CLOB/observation loops, 88a every 5 min from 02:34, wallet reader) uses at most about
   8,909 MiB (P-v2-defender M3).
5. **Unmeasured: the overnight available-memory distribution.**
   - No p10/p50/min for 00:35-04:10 exists in the repo or in swarm-m. P-v2-defender M3 asked master to read it; the
     source is the host sampler `C:\tmp\suite-logs\mem-sample-20261007.log` and its second night (HOST-FACTS).
   - The only dated host readings in the repo are daytime and incident values: 5.26 GiB available at 12:25 on
     2026-07-13 (agent-report-2026-07-13 :263), 617 MiB in the 2026-07-14 incident (HLP ~:321) and 1.81 GB during the
     09-06 deferral (full-audit-2026-09-18 live-ops-state :153).
   - So **expect some nights to refuse.** A refusal throws at once, writes nothing and is not an attempt (P-plan §5).
     That is the intended capture-first failure.
6. **Fallback (owner act only):** `5632` (2,048 + one 1,792 slot + 1,536), if the sampler's p10 at 00:35 is below
   7,680 and the owner accepts "snapshot ran one worker during the export" as a disclosed capture cost (P-v2-defender
   M3 option ii). Do not pick it by agent judgement.

**Knock-on for the exploratory spec** (out of scope, flagged only). Its verify value (3,072) and driver value (6,144)
used the "ceiling + 1.5 GiB + margin" rule without the two worker slots. The same arithmetic gives:
- verify: 1,024 + 3,584 + 1,536 = **6,144**;
- driver: 4,096 + 3,584 + 1,536 = **9,216** (P-defender PM2 "about 9.1 GiB for any 4 GiB host step").
Its U6 export step should also use 7168, not 4096.

## 4. Host, operator, window

- **Host:** the capture host only. Both the wrapper (:183-187) and the registrar (:61-64) refuse any other
  `dedicated_capture_execution_host_id`.
  - Production checkout: `C:\Users\micha\Desktop\github\weather`.
  - venv: `…\weather\venv\Scripts\python.exe`.
- **Who runs it:** master-agent (the production agent), in one attended `powershell.exe` window, serially, never through
  parallel tool calls.
  - Keep and poll every process you start; terminate it if abandoned.
  - While the shakeout child is alive, no other agent python or heavy command runs on the host (P-plan PM10).
- **Window:**
  - P0-P4 (pre-checks, deploy, pins, refusal proof, `-WhatIf`) are **light and unleased**. They run on N4 inside
    00:30-09:00, never 12:00-00:30. Preferred: 00:30-00:58, before the 01:00 quiet-window landings. Otherwise run them
    after the landing lease is released.
  - The MOD recompute is in-window by rule (P-plan PN5).
  - P5 shakeout (optional): the wrapper takes the shared lease **itself** (:188-190), so do not hold an outer lease. It
    starts only after the N4 landings release the lease (HOST-FACTS: 03:40), and no later than **04:09:15**, the
    latest full-budget start (P-plan PM1). A later start is skipped, not run.
  - Fallback: the same sequence on N5.
- **Not tonight:** Scheduler registration (§8).

## 5. Commands, in order (PowerShell 5.1)

Paste **one phase at a time**. Each phase is one `. { … }` block: variables persist, and a `throw` ends the phase. If a
phase prints `STOP` or throws, do not paste the next one; go to §7.

### P0. Constants and pre-checks

```powershell
$ErrorActionPreference = 'Continue'
. {
  $script:Prod   = 'C:\Users\micha\Desktop\github\weather'
  $script:Py     = "$Prod\venv\Scripts\python.exe"
  $script:Sha    = '89618c30cbe23f4b267728692ccf8bc0b1c2dd0b'
  $script:D      = "C:\Users\micha\Desktop\github\weather-exam-deployed-$Sha"
  $script:MODx   = 'abc38cea25ee564f3190c9f02cfc798048ddcc06b1fc9ff4555ebabf98bf3a11'
  $script:V01x   = '089cb29a5ed41fd3a2c0897be7e3e6eb4959e900d0079fbd248970144d51fa88'
  $script:WRAPx  = 'bc7c19c35c8be0b7ff857d6a481b3062761f5e27dece16c0b0aee825ccaf235d'
  $script:REGx   = '7082280cdeb6bde46bd88afb4cedbb211d88be03ae744de501b0ea0512b21fca'
  $script:JOBx   = '10e3ff4eb7e48eb714ea37a4efedb11991c908fdf7107650c571f44266edebb2'
  $script:MinMiB = 7168
  $script:Data   = "$Prod\data"                      # confirm = the exam runbook's night -DataRoot
  $script:Rel    = '<HOST_RELEASE_ROOT>'             # master fills: the exam night -ReleaseRoot (must exist)
  $script:Out    = 'C:\Users\micha\Desktop\github\mrv2-nightly\v02'   # proposed task OutputRoot (used by -WhatIf only tonight)
  $script:Att    = "C:\Users\micha\Desktop\github\mrv2-cal\u6-deploy-$((Get-Date).ToString('yyyyMMdd-HHmm'))"
  $script:yday   = [DateTime]::UtcNow.Date.AddDays(-1).ToString('yyyy-MM-dd')   # latest closed UTC day = the task's default -Day

  $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
  $now  = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone)
  if ($now.TimeOfDay -lt [TimeSpan]'00:30:00' -or $now.TimeOfDay -ge [TimeSpan]'09:00:00') { throw 'STOP: outside 00:30-09:00' }
  if ($yday -lt '2026-09-30' -or $yday -gt '2026-10-15') { throw "STOP: $yday is not a gated day; the refusal proof would export. Use a fixed gated day instead." }

  # (1) build-line tip
  $remote = ((git -C $Prod ls-remote origin refs/heads/codex/maker-replay-v2-build-20261003) -split '\s+')[0]
  if ($remote -cne $Sha) { throw "STOP: build-line tip is $remote, not $Sha (re-plan; never deploy a different tip from this block)" }

  # (2) no conflicting lease, no poison
  . "$Prod\scripts\ops\workload_admission.ps1"
  $ls = Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod
  if ($ls.Active) { throw "STOP: lease held: $($ls.Owner | ConvertTo-Json -Compress)" }
  if ($null -ne (Get-WeatherHeavyWorkloadPoisonState -Path (Get-WeatherHeavyWorkloadPoisonPath))) { throw 'STOP: lease poisoned; the owner clears it' }

  # (3) disk (volume free bytes, never a directory walk): wrapper floor 50 GiB + deploy + shakeout output
  $free = [IO.DriveInfo]::new('C:\').AvailableFreeSpace
  if ($free -lt 55GB) { throw "STOP: C: free $([math]::Round($free/1GB,1)) GiB < 55 GiB" }

  # (4) memory: guard fresh and commit < 70 %; available is recorded (binding only for P5, inside the wrapper)
  $gp = "$Prod\data\logs\memory_commit_guard_status.json"
  $g  = Get-Content -LiteralPath $gp -Raw | ConvertFrom-Json
  $age = ([DateTime]::UtcNow - (Get-Item -LiteralPath $gp).LastWriteTimeUtc).TotalMinutes
  $avail = [math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
  if ($age -gt 5 -or [double]$g.commit_percent -ge 70) { throw "STOP: guard age $age min / commit $($g.commit_percent) %" }

  # (5) no export task exists yet (STATE_OF_PLAY: unregistered until >= 10-16)
  if (Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue) {
    throw 'STOP: WeatherReplayBundleExportNightly already registered - unknown state; report its Actions[0].Arguments, do not overwrite' }

  # (6) production tree baseline (proves later that nothing rolled)
  $script:ProdHead = (git -C $Prod rev-parse HEAD).Trim()
  $script:ProdDirty = @(git -C $Prod status --porcelain).Count

  New-Item -ItemType Directory -Force -Path $Att | Out-Null
  [ordered]@{ at = $now.ToString('s'); tip = $remote; commit_percent = $g.commit_percent; guard_age_min = $age;
    avail_mib = $avail; free_gib = [math]::Round($free/1GB,1); prod_head = $ProdHead; prod_dirty = $ProdDirty } |
    ConvertTo-Json | Set-Content -LiteralPath "$Att\p0-prechecks.json" -Encoding utf8
  "P0 OK  avail=$avail MiB (P5 needs >= $MinMiB at launch)"
}
& "$Prod\scripts\ops\status.ps1"     # read it: STOP if any capture worker is not healthy
```

### P1. Deploy the exact tip (roll-free: production working tree untouched)

```powershell
. {
  git -C $Prod fetch origin codex/maker-replay-v2-build-20261003
  if (Test-Path -LiteralPath $D) {
    if ((git -C $D rev-parse HEAD).Trim() -cne $Sha -or @(git -C $D status --porcelain --untracked-files=all).Count) {
      throw "STOP: $D exists but is not a clean $Sha checkout" }
    'P1 reuse: existing clean deploy'
  } else {
    $env:GIT_LFS_SKIP_SMUDGE = '1'
    git -C $Prod worktree add --detach $D $Sha
    Remove-Item Env:GIT_LFS_SKIP_SMUDGE
    git -C $Prod worktree lock $D --reason "U6 nightly export deploy $Sha"
  }
  if ((git -C $D rev-parse HEAD).Trim() -cne $Sha) { throw 'STOP: deploy not at tip' }
  if (@(git -C $D status --porcelain --untracked-files=all).Count) { throw 'STOP: deploy dirty' }
  if (-not ((git -C $Prod worktree list --porcelain) -match [regex]::Escape('locked'))) { throw 'STOP: no locked worktree listed' }
  'P1 OK'
}
```

### P2. Pins: script hashes and the MOD recompute (light, in-window)

```powershell
. {
  function H([string]$p) { (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant() }
  $script:WRAP1 = H "$D\scripts\ops\replay_bundle_export_nightly.ps1"
  if ($WRAP1 -cne $WRAPx) { throw "STOP: WRAP $WRAP1 (CRLF checkout?)" }
  if ((H "$D\scripts\ops\register_replay_bundle_export_nightly.ps1") -cne $REGx) { throw 'STOP: registrar hash' }
  if ((H "$D\scripts\ops\replay_export_limited_job.ps1") -cne $JOBx) { throw 'STOP: job helper hash' }

  $env:PYTHONPATH = "$D\src"; Push-Location -LiteralPath $D
  try {
    $j2 = (& $Py -P -B -m weather.market.maker_replay_night_v02 module-hash) | ConvertFrom-Json
    $j1 = (& $Py -P -B -m weather.market.maker_plugin.replay_export module-hash) | ConvertFrom-Json
  } finally { Pop-Location; Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
  $script:MOD1 = $j2.module_sha256
  $script:V01  = $j1.module_sha256
  [ordered]@{ sha = $Sha; MOD1 = $MOD1; MOD1_files = $j2.files; V01 = $V01; V01_files = $j1.files; WRAP1 = $WRAP1 } |
    ConvertTo-Json | Set-Content -LiteralPath "$Att\p2-pins.json" -Encoding utf8
  if ($MOD1 -cne $MODx -or $j2.files -ne 62) { throw "STOP: MOD1 $MOD1 ($($j2.files) files) != $MODx (62)" }
  if ($V01 -cne $V01x) { "WARN: v0.1 facade $V01 != $V01x - the v0.1 refusal test below still runs on the host value; report it" }
  "P2 OK  MOD1=$MOD1"
}
```

### P3. PANEL_GATED refusal proof (sentinel roots only; nothing reads data)

```powershell
. {
  $script:T = "$Att\refusal"
  New-Item -ItemType Directory -Force -Path "$T\empty-data", "$T\empty-release" | Out-Null
  $wr = "$D\scripts\ops\replay_bundle_export_nightly.ps1"
  foreach ($day in @('2026-09-30', '2026-10-05', $yday, '')) {      # '' = the task's default (yesterday UTC)
    $tag = if ($day) { $day } else { "default-$yday" }
    $dayArgs = if ($day) { @('-Day', $day) } else { @() }
    powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $wr `
      -DeployRoot $D -ProductionRoot $Prod -DataRoot "$T\empty-data" -ReleaseRoot "$T\empty-release" -OutputRoot "$T\out" `
      -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB $MinMiB -Kind night @dayArgs 2> "$T\wrapper-$tag.err"
    $rc = $LASTEXITCODE; "$rc" | Set-Content -LiteralPath "$T\wrapper-$tag.rc"
    $want = if ($day) { $day } else { $yday }
    if ($rc -ne 3 -or -not (Select-String -LiteralPath "$T\wrapper-$tag.err" -SimpleMatch "REFUSED: PANEL_GATED $want" -Quiet)) {
      throw "STOP: gate FAIL for $tag (rc $rc)" }
  }
  # python side, exact code only
  $env:PYTHONPATH = "$D\src"; Push-Location -LiteralPath $D
  try {
    & $Py -P -B -m weather.market.maker_replay_night_v02 night --day 2026-10-05 --data-root "$T\empty-data" `
      --release-root "$T\empty-release" --out "$T\out" --expected-module-sha256 $MOD1 2> "$T\py-v02-night.err"
    $r1 = $LASTEXITCODE
    & $Py -P -B -m weather.market.maker_replay_night_v02 calibration --day 2026-09-30 --data-root "$T\empty-data" `
      --out "$T\out" --expected-module-sha256 $MOD1 2> "$T\py-v02-cal.err"
    $r2 = $LASTEXITCODE
    & $Py -P -B -m weather.market.maker_plugin.replay_export night --day $yday --data-root "$T\empty-data" `
      --release-root "$T\empty-release" --out "$T\out" --expected-module-sha256 $V01 2> "$T\py-v01-night.err"
    $r3 = $LASTEXITCODE
  } finally { Pop-Location; Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
  foreach ($p in @(@($r1, 'py-v02-night'), @($r2, 'py-v02-cal'), @($r3, 'py-v01-night'))) {
    if ($p[0] -ne 2 -or -not (Select-String -LiteralPath "$T\$($p[1]).err" -SimpleMatch 'panel_export_requires_signed_registration' -Quiet)) {
      throw "STOP: python gate FAIL $($p[1]) (rc $($p[0]))" }
  }
  if (Test-Path -LiteralPath "$T\out") { throw 'STOP: an output root was created' }
  if (@(Get-ChildItem -Force -Recurse -LiteralPath "$T\empty-data", "$T\empty-release").Count) { throw 'STOP: sentinels written' }
  'P3 OK  (4 wrapper exit-3 + 3 python exact refusals, sentinels empty)'
}
```

### P4. Registrar `-WhatIf` (pins and paths; no Scheduler IO)

```powershell
. {
  if ($Rel -like '<*') { throw 'STOP: fill $Rel first' }
  if (-not (Test-Path -LiteralPath $Rel -PathType Container)) { throw 'STOP: release root missing' }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null     # parent must exist; $Out itself is not created
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\register_replay_bundle_export_nightly.ps1" `
    -RepoRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot $Out `
    -ExpectedModuleSha256 $MOD1 -ExpectedRunnerSha256 $WRAP1 -MinAvailableMiB $MinMiB -WhatIf *> "$Att\p4-whatif.txt"
  $rc = $LASTEXITCODE
  if ($rc -ne 0 -or -not (Select-String -LiteralPath "$Att\p4-whatif.txt" -SimpleMatch "pin modules $MOD1" -Quiet)) { throw "STOP: WhatIf rc $rc" }
  if (Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue) { throw 'STOP: WhatIf registered a task?!' }
  'P4 OK'
}
```

### P5. Optional shakeout export of calibration date 2026-09-27 (only if master's N4 plan keeps the 03:40 trial export)

This is a real export: it reads the 88a sealed data for 09-27 only. 09-27 is a calibration date (≤ 09-29), never a panel
day. It is counted in the night's three-export cap and labelled `SHAKEOUT` (P-plan §3.0, PN2).

```powershell
. {
  $zone = [TimeZoneInfo]::FindSystemTimeZoneById('Eastern Standard Time')
  $t = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $zone).TimeOfDay
  if ($t -lt [TimeSpan]'00:40:00' -or $t -gt [TimeSpan]'04:09:15') { throw 'SKIP (not an attempt): outside 00:40-04:09:15' }
  . "$Prod\scripts\ops\workload_admission.ps1"
  if ((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod).Active) { throw 'SKIP: lease busy; no wait, no retry tonight' }
  $avail = [math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)
  if ($avail -lt $MinMiB) { throw "SKIP (not an attempt): available $avail MiB < $MinMiB" }
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\replay_bundle_export_nightly.ps1" `
    -DeployRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot "$Att\shakeout" `
    -ExpectedModuleSha256 $MOD1 -ExpectedSelfSha256 $WRAP1 -MinAvailableMiB $MinMiB -Kind night -Day 2026-09-27 `
    1> "$Att\shakeout.out" 2> "$Att\shakeout.err"
  $script:ShakeRc = $LASTEXITCODE; "$ShakeRc" | Set-Content -LiteralPath "$Att\shakeout.rc"
  "P5 rc=$ShakeRc"; Get-Content -LiteralPath "$Att\shakeout.out" -Tail 1
}
```

## 6. Verify

```powershell
. {
  # deploy
  if ((git -C $D rev-parse HEAD).Trim() -cne $Sha -or @(git -C $D status --porcelain --untracked-files=all).Count) { throw 'FAIL deploy' }
  # production untouched -> no STALE_CODE roll
  if ((git -C $Prod rev-parse HEAD).Trim() -cne $ProdHead) { throw 'FAIL production HEAD moved' }
  if (@(git -C $Prod status --porcelain).Count -ne $ProdDirty) { 'WARN production status count changed - inspect (runtime config refreshes are known dirt)' }
  # pins on record
  Get-Content -LiteralPath "$Att\p2-pins.json"
  # refusal evidence: 4 x rc 3 + 3 python refusals
  Get-ChildItem -LiteralPath "$Att\refusal" -Filter *.rc | ForEach-Object { "$($_.Name)=$(Get-Content -LiteralPath $_.FullName)" }
  # still unregistered
  if (Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly -ErrorAction SilentlyContinue) { throw 'FAIL task exists' }
  # lease free and not poisoned after everything
  . "$Prod\scripts\ops\workload_admission.ps1"
  "lease active: $((Get-WeatherHeavyWorkloadLeaseState -RepoRoot $Prod).Active); poison: $($null -ne (Get-WeatherHeavyWorkloadPoisonState -Path (Get-WeatherHeavyWorkloadPoisonPath)))"
  # shakeout (if run): rc 0; JSON line memory_limit_hit=false; receipt module_sha256 == MOD1 and threads.pinned
  if (Test-Path -LiteralPath "$Att\shakeout") {
    $line = Get-Content -LiteralPath "$Att\shakeout.out" -Tail 1 | ConvertFrom-Json
    $rcpt = Get-ChildItem -LiteralPath "$Att\shakeout" -Recurse -Filter receipt.json | Select-Object -First 1 | Get-Content -Raw | ConvertFrom-Json
    "shakeout rc=$ShakeRc limit_hit=$($line.memory_limit_hit) peak_commit=$($line.peak_job_memory_bytes) avail_at_launch=$($line.available_mib_at_launch) status=$($rcpt.status) mod_ok=$($rcpt.module_sha256 -ceq $MOD1) pinned=$($rcpt.threads.pinned)"
  }
}
& "$Prod\scripts\ops\status.ps1"     # all capture workers healthy after
```

**Pass criteria:**
- the deploy is clean at `89618c30c` and locked;
- MOD1 = `abc38cea…3a11` (62 files);
- WRAP1, REG and JOB match;
- the wrapper gave exit 3 with `PANEL_GATED <day>` four times (09-30, 10-05, latest closed day and the default `-Day`);
- the three python calls gave exit 2 with `panel_export_requires_signed_registration`;
- the sentinels are empty and there is no `$T\out`;
- `-WhatIf` gave rc 0, and its output names `pin modules abc38cea…`;
- no task is registered;
- the production HEAD is unchanged;
- capture is healthy.

**Shakeout** (informational): rc 0, `memory_limit_hit` false, receipt `module_sha256` = MOD1, `threads.pinned` true.
Record the runtime and peak for P1 planning (P-plan Q19).

**Hand back to the workstation** (hash-confirmed): `p0-prechecks.json`, `p2-pins.json`, the refusal `.rc`/`.err` files,
`p4-whatif.txt`, and the shakeout `.out` JSON line. Not the bundle or `receipt.json` coverage.

## 7. STOP and rollback

| Trigger | Action |
| --- | --- |
| Any P0 check fails | Stop. Nothing was changed; nothing to roll back. Retry next eligible night. |
| Tip != 89618c30c | Stop. Re-plan with master. Never deploy a different tip under this block's pins. |
| Deploy wrong (HEAD, dirty, a script hash mismatch) | `git -C $Prod worktree unlock $D; git -C $Prod worktree remove $D` (it holds only checked-out code; no outputs live in it). Report. |
| MOD1 != abc38cea… or the file count != 62 | Do not register and do not run P3-P5. Keep the deploy. Report both JSONs. A different interpreter can change the closure; a host value is never adopted as the pin without review. |
| Any wrapper result other than exit 3 + `PANEL_GATED <day>`, or any python result other than the exact code | **Gate FAIL.** Stop all U6/P-work. Keep the deploy and `$Att` for diagnosis (do not remove). Report to master/owner. Sentinel roots mean nothing real was read (PB1). |
| `-WhatIf` non-zero | Do not register. Read `p4-whatif.txt` (path normalization, reparse point, disjointness, runner hash). |
| Shakeout: capture worker unhealthy, or the operator must stop it | Terminate the wrapper's `powershell.exe`. Its kill-on-close Job takes the child with it. Then check lease state and poison. Report. |
| Shakeout: memory limit hit, non-zero exit, or deadline | It is an attempt FAIL (P-plan §5). Keep the output root. Report. Never retry in place; a rerun needs a fresh root. |
| Lease poisoned (unproved teardown) | Stop. Do not clear the poison: that is an owner act. Report before 04:59 so 05:00 tiering is decided (P-v2-defender M4). |
| After registration (≥ 10-16) | Stop: `Disable-ScheduledTask -TaskName WeatherReplayBundleExportNightly`. Roll back: `Unregister-ScheduledTask -TaskName WeatherReplayBundleExportNightly -Confirm:$false`, and only then remove the deploy worktree (the task runs from `$D`). |

## 8. ACTIVATION BLOCK

- **What:** Scheduled Task `WeatherReplayBundleExportNightly`.
  - Daily at 00:35, with S4U/Limited, a 50-minute limit, IgnoreNew and no StartWhenAvailable.
  - It runs `$D\scripts\ops\replay_bundle_export_nightly.ps1`:
    - `-DeployRoot $D -ProductionRoot $Prod`;
    - pinned `-ExpectedModuleSha256 abc38cea…3a11` and `-ExpectedSelfSha256 bc7c19c3…235d`;
    - `-MinAvailableMiB 7168`;
    - the default `-Day` (yesterday UTC) and `-Kind night`.
- **Host:** the capture host. The registrar refuses any other host (:61-64) and requires the Eastern time zone (:59).
- **Who starts it:** master-agent, only after an **explicit owner yes** relayed to it. Registration is a
  production-operator act (maker-replay-bundle.md, "Scheduled production export"). This block grants it no authority.
- **When:**
  - **Not before 2026-10-16** (STATE_OF_PLAY: "stays unregistered until at least 10-16").
  - The registrar is light: run it 00:30-12:00, never 12:00-00:30.
  - Registered on 10-16 by day, the first fire is 10-17 00:35 Toronto (04:35Z) with `-Day 2026-10-16`, the first
    non-gated day.
  - Registered earlier, it would just exit 3 nightly through the 10-16 00:35 run.
- **Command** (after a fresh P0-P2 on that day; `-WhatIf` first, then the same line without it):
  ```powershell
  powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$D\scripts\ops\register_replay_bundle_export_nightly.ps1" `
    -RepoRoot $D -ProductionRoot $Prod -DataRoot $Data -ReleaseRoot $Rel -OutputRoot $Out `
    -ExpectedModuleSha256 $MOD1 -ExpectedRunnerSha256 $WRAP1 -MinAvailableMiB 7168 -WhatIf
  # then the identical command without -WhatIf; expect "Registered WeatherReplayBundleExportNightly at 00:35; ..."
  ```
- **Verify command:**
  ```powershell
  $t = Get-ScheduledTask -TaskName WeatherReplayBundleExportNightly
  $a = $t.Actions[0].Arguments
  if ($a -notmatch [regex]::Escape("-DeployRoot $D") -or $a -notmatch 'abc38cea25ee564f3190c9f02cfc798048ddcc06b1fc9ff4555ebabf98bf3a11' -or
      $a -notmatch 'bc7c19c35c8be0b7ff857d6a481b3062761f5e27dece16c0b0aee825ccaf235d' -or $a -notmatch '-MinAvailableMiB 7168') { throw 'FAIL task args' }
  Get-ScheduledTaskInfo -TaskName WeatherReplayBundleExportNightly | Select-Object LastRunTime, LastTaskResult, NextRunTime
  ```
- **Reading `LastTaskResult` the next morning:**
  - `0`: exported. Check `<Out>` for the day's `receipt.json` (`status`, `module_sha256` = MOD1).
  - `3`: PANEL_GATED. Expected only for days 09-30..10-15.
  - `1`: a refusal (lease busy, memory admission below 7168, commit, disk, hash mismatch or deadline). The wrapper's
    stdout JSON is not captured under Scheduler (L2), so read the exporter ledger and receipt under `<Out>`.
- **Re-pin trigger:** any build-line change to a closure module or to the wrapper requires a new `$D`, P0-P2 and a
  registrar re-run (`-Force` overwrites the task). That covers sha2 = U1 + X1, the U6-Q1 `-OwnerDecision` change and
  the L1 code fix.
- **Open before activation (owner/master):**
  1. **Landing nights.** The task takes the lease at 00:35 for up to 45 minutes, so the 01:00 quiet-window merges may
     find it busy. The registrar only allows `00:35`, and P-plan PM3 asks for starts at or after 00:40. Either accept
     this, disable the task on landing nights, or change the registrar (review needed).
  2. **The three-exports-per-night cap** (U6 Q3 / P-plan Q6) applies to the task plus any hand exports.
  3. **The `<Out>` location.** The proposal is `C:\Users\micha\Desktop\github\mrv2-nightly\v02`, outside `$Prod`, disjoint
     from data, releases and the deploy, on C: (the 50 GiB free check uses this drive).

## 9. SWOB export re-registration: the values

- **There is nothing registered to re-register today.**
  - HOST-FACTS-20261006: "NO enabled 00:35 trigger".
  - STATE_OF_PLAY: the task "stays unregistered until at least 10-16".
  - P0 check (5) stops if a task unexpectedly exists.
- **The SWOB re-pin obligation** (maker-core-contracts.md:201-205; SWOB-ab-defender N1; SWOBCLOCK-defender N-3) is met
  by making the **first** registration use the post-SWOB+U6 values.

| Pin | Value at 6d1fa4b74 | Where it is used |
| --- | --- | --- |
| v0.2 exporter closure (MOD1) | `abc38cea25ee564f3190c9f02cfc798048ddcc06b1fc9ff4555ebabf98bf3a11` (62 files) | The task's `-ExpectedModuleSha256` (the wrapper launches v0.2 only, :213) |
| v0.1 facade closure | `089cb29a5ed41fd3a2c0897be7e3e6eb4959e900d0079fbd248970144d51fa88` (57 files) | Only hand-run v0.1 refusal tests or v0.1 reference exports (P-plan §3.0); never the task |
| Wrapper (WRAP1) | `bc7c19c35c8be0b7ff857d6a481b3062761f5e27dece16c0b0aee825ccaf235d` | `-ExpectedRunnerSha256` / `-ExpectedSelfSha256` |

- **How to compute them.** They are not fixed constants; they are content hashes. Compute them from the deploy, in
  window:
  ```powershell
  $env:PYTHONPATH = "$D\src"; Push-Location $D
  $MOD1 = ((& "$Prod\venv\Scripts\python.exe" -P -B -m weather.market.maker_replay_night_v02 module-hash) | ConvertFrom-Json).module_sha256
  $V01  = ((& "$Prod\venv\Scripts\python.exe" -P -B -m weather.market.maker_plugin.replay_export module-hash) | ConvertFrom-Json).module_sha256
  Pop-Location; Remove-Item Env:PYTHONPATH
  ```
  They must equal the table values. My workstation check matched D1-redo's blob-byte recomputation for MOD1.
- `python -m weather.market.maker_replay_night module-hash` prints nothing (that module has no `__main__` entry point).
  Use the facade.
- **Also out of date after SWOB, not pinned by this task:**
  - `execution_manifest.source_hashes`, which hashes `maker_plugin_runner.py`, is the gate/oracle side's re-pin
    (maker-core-contracts.md:204).
  - `maker_fair_value_score.implementation_hashes` does not change.

## 10. Not done / open

- Nothing ran on the host. The overnight available-memory p10/p50/min (sampler log on the host) is unread. Master
  should read it before choosing between 7168 and the 5632 owner fallback.
- The `<HOST_RELEASE_ROOT>` and the exam `-DataRoot` subpaths are not in the repo. Master fills them from the exam
  runbook.
- The doc fixes in §1 and the P-plan fixes in §2 are text for master to apply. Nothing was committed or pushed.

## 11. Master decisions 2026-10-09 05:35
- 7168 confirmed. Host N2 sampler: avail min 7711, p10 8330, median 8764, max 9712.
- P0-P4 run 00:30-00:58 on N4, before the landings. Master decides P5 (09-27) at 04:00.
- Owner recommendations (master carries them):
  - Registrar ValidateSet gains a post-quiet-window slot, about 04:10, ≤45 min, ending before the 05:00 tiering. The task is not disabled on landing nights.
  - Cap of 3 exports per night.
  - Out = C:\Users\micha\Desktop\github\mrv2-nightly\v02.
- Master fills <HOST_RELEASE_ROOT> and -DataRoot before activation, which is ≥10-16 and needs an owner yes.
- Exploratory knock-on: verify 6144. Driver 9216 is an OWNER QUESTION: it is above the observed max minus margin, so expect frequent refusals.
- Doc fixes branch: claude/u6-doc-fixes-20261009 @ 89618c30c (base: build line 6d1fa4b74). Docs only, roll-free.
- 2026-10-09: master fast-forwarded the build line from 6d1fa4b74 to **89618c30c** (docs only: maker-replay-bundle.md and maker-core-contracts.md). MOD, v0.1, WRAP, REG and JOB pins are unchanged, because no .py or .ps1 changed. Deploy the exact tip 89618c30cbe23f4b267728692ccf8bc0b1c2dd0b instead. The DeployRoot becomes C:\Users\micha\Desktop\github\weather-exam-deployed-89618c30cbe23f4b267728692ccf8bc0b1c2dd0b. The docs head is dropped from N4.
