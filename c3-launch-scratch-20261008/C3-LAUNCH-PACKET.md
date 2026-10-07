# C3 console rehearsal: launch packet for 2026-10-08 09:00-09:30 (capture host, owner-attended)

Workstation session, 2026-10-07 ~12:40 local; F1-F4, Defender and dry pass completed ~13:30. Built from `D-c3-rehearsal-v3.1.md` (the spec), `C3-v3-defender.md`
(CLEARED-AFTER-FIXES; M1-M3, Q5, Q6 and N1-N9 are applied in v3.1), `C3-v2-defender.md`, `C3-handler-order-proof.md`,
`P-rehearsal-plan-v2.md` (only the landing calendar), `HOST-FACTS-20261006.md` and `WORKSTATION_STATE.md`. Pins were
resolved in a scratch detached worktree at `c9cf068be` on this workstation. That worktree has been removed. Nothing ran
on the capture host.

## 0. Verdict first

**READY on the workstation side for 2026-10-08 09:00, as of about 13:30 on 10-07.** The go decision is conditional.
It needs the owner items still open (Q7, Q2/Q1, the 3.6 deviation acceptance) and the 08:55 host gates. Section 7 has
the full list.

- **F1 (site-packages under `-I -S`): FIXED** in the spec, `c3_break.py` and `c3_ctrlc.py` (section 2.3).
- **F2 (corrupt reference launcher copy): FIXED** by re-extracting it.
- **F3 (new; found by the dry pass): FIXED.** v3.1's `c3_run.ps1` HARD STOPs at step 6b and then REFUSES every later
  call. The cause is a stale console-list entry, not an escape.
  - The fix is `c3-run-v3.1-F3` with the record-only field `consoleStale`, and 6b re-pinned to `2k+2`.
  - **6b now runs as the LAST call (step 8d)**, per the Defender's MUST-FIX.
- **F4 (new; operator text): FIXED.** In v3.1 the step-7 judge always refused its own folder.
- **Defender:** F1/F2/V31-R1 CLEARED-AFTER-FIXES; F3/F4 CLEARED-AFTER-FIXES. Every must-fix is applied
  (`C3-F1-defender.md`).
- **Workstation dry pass: PASS** (`C3-DRYPASS-20261007.md`, run3 in the final order).
  - `k=2`; `2k`=4, `2k+1`=5, `2k+2`=6, `3k+1`=7, `2k+3`=7.
  - All lines `verify OK`, all zeros, `consoleStale` clean.
  - No `.pyc` was written.
- **Stage `c3-launch-20261008\v3.1-F3-host\`** with the section 2.3 / section 4 hashes. **Not `v3.1-F1-host\`**, which
  would HARD STOP at 6b.
- **Not exercised anywhere yet:**
  - P8 item 6 (the Ctrl+C guard self-test, owner Q7);
  - step 7.1 (operator Ctrl+C);
  - steps 8a and 8b (typed input).
  - These first run on the host with the owner, under the spec's bounded rules. An incidental 8a-shaped acceptance
    was observed on the workstation (`C3-DRYPASS-20261007.md`, deviation 4).
- **No credential, wallet, exchange or signing step exists in the spec** (section 3.5).

## 1. What runs, from where

| Item | Value |
| --- | --- |
| Host | 16 GB capture host, interactive owner session (not RDP-disconnected, not a scheduled task) |
| Tree (official record) | `C:\Users\micha\Desktop\github\weather` (production checkout, branch `master`) |
| Python | `C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe` |
| Scratch | `C:\c3\20261008` (scripts, run folders, ledger). Command sheet: `C:\c3\C3-COMMANDS-20261008.txt` |
| Base SHA (N2 base = `origin/master` now) | `c9cf068be6f7f74c6ac7304690d88f8fd90fa9e6` |
| #230 landing (contains #228 + #229) | merge `eefbb3dfde3de72bf92df80f4ba462c9cc5b6688`; reviewed tip `f9063256e5becbc5d75cf3a79380c4d2ee919c24` (an ancestor of `c9cf068be`; no diff in runner, harness, templates, Job helper or `sitecustomize.py` between the two) |
| #229 stdin change | `85ab63bdeb3ade39c83f9a0c17a7dacffaf4436c` (runner line 363 `stdin=subprocess.DEVNULL`, present at `c9cf068be`) |
| Expected HEAD at 09:00 | **The post-N2 `master` SHA from master-agent's N2 closing receipt** (`WeatherOneShotPush` verified). It equals `c9cf068be…` only if N2 lands nothing. The rehearsal does not need a specific N2 SHA. It needs the **tier-A files unchanged since `c9cf068be`** (section 2), checked by `git diff` at the console |
| Prompt hash (`_prompt_until`, both templates) | `c03caf8cbe6114c2c42ff216c49e8c2b6453f57f29ed2ea12146b40cffd44597`. Recomputed here from `c9cf068be`; both templates are equal and match the reviewed value |

The scripts exist only as text in the spec. They are committed nowhere and pushed nowhere. Master-agent must place them
on the host **byte-exact (ASCII, LF line endings, no BOM)** and verify them against section 2.3 before 09:00.

## 2. Pins

### 2.1 Tier A: behaviour under test. No N2 head touches any of these

The repo has `* text=auto eol=lf`, so the host working-tree bytes equal the blob bytes, and the SHA-256 below is what
`Get-FileHash` must print. **Checked:** none of these paths differ from `c9cf068be` on any N2 head (`rs1` 69e9ea988,
`rs1b` 012cbc872, `rs2` d9240032e, `rs` 2aac78750, `rf` ae44d6d09, `rf2` dead62ff3, `rf2b` ac0cf1138, `rf2d` feb42229b,
`rf2e` b7b8b7ebb, `l5` 7a03b5810, `l5-reconciler-surface` f58164daf, timebomb fix 27e67f6e6, pf2 79e5eb106).

| Path | git blob | SHA-256 |
| --- | --- | --- |
| `src/weather/operations/international_live_session_runner.py` | d4568432f6564ba8bd90d989c334a403814380ab | d3b1ae5c91319709512c8643b7b8ea2d6e3061840b6508ecdc543a82b607049e |
| `src/weather/operations/live_path_security.py` | 97b50da65f7f919dbc7d0c32a9de9da9050c052c | 63049bea7175c371c7d21908d8c6e6d05be0b84baf58aef688e53c6e34eff7a6 |
| `src/weather/operations/windows_silent.py` | 293a5f17fcac8a957ef90ffbdfe83090559d2905 | f4521eec3e9f99a1b1ae89c095fd74625eac54e1f3acb583262038a519557bc9 |
| `tests/operations/live_launcher_break_harness.py` | e6c07d0ce781280e54cec3295c2759b582ec8b15 | e7d9ae9a644343da89812ed8987403fbea82a925c1099a836fabd72a1732ab09 |
| `tests/operations/test_live_runner_console_guards.py` | d79c2fb6f97bd1196cebabe1a14352aeb75027e1 | 9212d07cbe27d3d3d00941a25b91e7f75c916f6be1ec3f761f8e169974861765 |
| `scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl` | 1ecf135a70e19935016e40892078982e84c7a55d | d3dda82f4b265abda4942d29c518ce72ab7ba04b92a1ecc51d21f71845cbd9ab |
| `scripts/ops/international_live_templates/stage0.py.tmpl` | 4bac2bac3898ac766327e77b82a7153a14c848f6 | 9c2c7b6ffa0226adafb4b1af60d3e321c9492d89aebe89ee9157b737cb0278db |
| `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl` | f9c7daae2f3808a512dbc1f34f4f7a7dfd93b1b4 | 2508d1fa7f7e1fd9a77602c389274c2bb46ce9ce10718b340669ed8849ca5e90 |
| `scripts/ops/windows_kill_on_close_job.ps1` (step-8 `job_helper` pin) | a55997db12a362bc5b408ea3e13fc898f642fe0c | 05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669 |
| `sitecustomize.py` (steps 4 and 6b) | 04d3f7e1984edcb073e6cc8f7eae248e1499f5f8 | 99eda86954069d2a266e8b8559219039d397455144708755941f2db03ad4ac47 |

Template check (spec step 2), recomputed: lines 141-143 are `"-I",`, `"-S",` and `"-B",`. Line 145 is the bootstrap ending
`runpy.run_module('weather.operations.international_live_session_runner',run_name='__main__')`. The harness `BOOTSTRAP` and
`PRODUCTION_FLAGS` match it.

### 2.2 Tier B: the rest of the runner/harness import closure (recorded, not gating)

The runner import also loads the modules below. The list was measured by importing the runner, `live_path_security`
and the harness under `-I -S -B` at `c9cf068be`. **Two closure files are expected to change in N2:**
`src/weather/schema_registry_recent_data.py` (RS1/RS1b, pf2, RF: blob `7f14eacb873c663fffd9ad1ba800815ceec03a13` at rs1b)
and `src/weather/schema_registry_data.py` (RF2d/RF2e: blob `c52837e575392b54bb2c04c473d2405baf94cb35` at rf2e). These are
schema data tables and do not affect launcher control. The console records which closure files changed (section 4,
check C0). Blobs at `c9cf068be`:

```
src/weather/__init__.py 582d8e5775cbe14facce4dbcc409fad896b654fe
src/weather/cold_archive_locations.py fda534af6a513c47fe281bf967daef4a4644db10
src/weather/collection/__init__.py 64dc832d36d009a378d1b9d1dc6f4f37d1c0c5d6
src/weather/collection/redaction.py 499a9818b34a8309d1da327536a1d093d19f095b
src/weather/execution_host.py 210211f62fc439b0313a80cecc6d06db3864c509
src/weather/io.py 1fddd60a4b8094dd1e9a793ddfcf2d5fdb185005
src/weather/market/__init__.py 6686495896b8dc771af32eefa9177b75fc9f1aa8
src/weather/market/exchange_economics.py aaf526c850eaaa50e8e3c5f7ef28aafc22ee15cc
src/weather/market/execution_contract.py 69cb262a0e0107e40671ec1be95db93826bd1ac1
src/weather/market/market_config.py 5f7f0f237437b91d81b0d27404510f56773ae697
src/weather/market/market_microstructure_capture.py 4e2e12362fbea1cc217f7438f934c5f0f7d3815c
src/weather/market/market_microstructure_constants.py 63fbb272f5fc8db9067897a0479369d28ff6724d
src/weather/market/market_microstructure_features.py 6b47484f59e45fe19b58a37b7a81a68fd0dc9099
src/weather/market/market_registry.py c6c8b143a9ded1462ccf6bd32738fa025db4ecdc
src/weather/market/mm_geographic_eligibility.py 770b6d6cf9de2c6b5afdc541534ab2c486fdd5b0
src/weather/market/mm_live_candidate_cli.py c4faf70fbe96a551e85d636be18e7b6a169ef1bb
src/weather/market/mm_live_lifecycle_probe.py fbd4f51c2848b8650bf163c210829bde88ad2e43
src/weather/market/mm_official_adapter.py 444664ad0d2bfcb4c19110356e4a30c59e51107e
src/weather/market/platform_contract.py 1e83a702366ee05b22a348231998fc7201b515c5
src/weather/market/polymarket_client.py 8b021a0ec40ff18f8ca9dcb2d29d86bbcbef99d6
src/weather/market/storage_pressure_policy.py 160450931458db92c7eb2add180e1ca881688560
src/weather/market/value_helpers.py 26b2c214f7e9e1fc22bc525952b4e3aea097868c
src/weather/operations/__init__.py 218d90653f31ac461793a184d862b4e399caf0e0
src/weather/operations/international_live_lineage.py 9fc4ad6b5d5c47c7fdf1d8114fcda5b1a01ea072
src/weather/operations/international_live_time_window.py ecb42cc106f845e7e0989392f25788a3dc07c9fb
src/weather/operations/international_live_wrapper_sealer.py 6d17c49c4acaf91a25798905584b601ff97eeead
src/weather/paths.py a10213cd5e5ca64c9cb0b0ac2e6d316b4179d608
src/weather/schema_registry.py 4705186b10b5c758dda3d53ff742957aded98468
src/weather/schema_registry_data.py 9b8ccec071f68ba4f3590a8c722722cca194dd95
src/weather/schema_registry_recent_data.py 211f55d01b31c9a7df9a588cfcfc35fae29cd818
src/weather/schema_registry_types.py 7b6780b18d4d50156d24c8cbeb4fccc4ce62cf67
src/weather/time.py 12ea32523837675cb3e76c3993f4cdee17bf936f
src/weather/units.py c79768aadad2b49d5f6eb6a945e8eef5cf1751d4
tests/__init__.py 38bb211b065081810c8c65af2d44ca10dc9fb059
```

A coarse scan of top-level statements in every closure module found no module-level environment read, credential read,
file open or network call. This agrees with the earlier Defender clearance of the import closure.

### 2.3 The six scratch scripts (host-substituted, date 20261008)

**Stage these copies (F1-F3 applied, 2026-10-07):**
`C:\wt\workstation-chat\l-data\swarm-m\c3-launch-20261008\v3.1-F3-host\`. (`v3.1-F1-host\` is superseded: its
`c3_run.ps1` HARD STOPs at 6b; see F3 below.) They are extracted byte-exact from the F1-F4
spec text (`D-c3-rehearsal-v3.1.md`, F1 note at the top) with the host values substituted:
- `<tree>` = `C:\Users\micha\Desktop\github\weather`, `<venv>` = `…\weather\venv` and `<date>` = `20261008`;
- `<PROMPT_SHA256>` = `c03caf8c…44597`, pre-filled. P8 item 3 becomes a *verify* step, not an edit at the console.

All six files are pure ASCII with LF line endings and no BOM. Both `.ps1` files parse with 0 errors, and all four `.py`
files pass `ast.parse`. The P8 item-5 stop-verb scan prints nothing, and the CIM scan prints exactly 1 line
(`c3_run.ps1`, inside `Get-C3Snapshot`). The extractor reproduces the four unchanged reviewed hashes exactly.

**Do NOT stage `v3.1-as-reviewed-host\`.** Its `c3_prompt_launcher.ps1` is corrupt (F2, found 2026-10-07): the
substitution ate the backslash escapes, so line 6 reads `$tree = 'C:SERSMICHADESKTOPGITHUBWEATHER'` and the stub's
dot-source of the Job helper would fail in step 8 (fail-closed, but step 8 could never pass). Its hash `0fa49c86…7a33`
is retired. The spec text itself was always correct.

| File | SHA-256 (F1-F3, stage these) | Change |
| --- | --- | --- |
| `c3_run.ps1` | bdc597d7d456450fcbcff01428ce5066fccd59c184fffcf5a21c02156f6f2153 | **F3** stale console entries (`c3-run-v3.1-F3`; was 733b8c41…6589) |
| `c3_break.py` | 6ef96ecc3281916e6c6fbb7f519909273c9201153c49d45cdae0c68af37cfafa | **F1** (was 3144c612…2cfb) |
| `c3_ctrlc.py` | b567542703968e985fc8173d0107813a7e7b5987aac165994e3f699abf72ead2 | **F1** in `run` (was c12f536f…f0e9f0) |
| `c3_prompt.py` | b0a55816abf30d9595ad8771a5b34fc22e386c42d298dad00d08ea3562d4bccd | unchanged |
| `c3_prompt_launcher.ps1` | 742c4e9314983689fa71610d8ceeaf6e9a285a16b7fca42f654bc8c70c6ca419 | **F2** re-extracted correctly (was the corrupt 0fa49c86…7a33) |
| `c3_prompt_child.py` | d2b0a84efa5cd79b7fc0ed3f49cd6c0d0af968a9f383f8775a621d77c8436714 | unchanged |

**F1 fix (applied to the spec and the two scripts).**
1. Step 3 console command uses the template's rule instead of the `-I -S` `sysconfig` query:
   `$env:WEATHER_FIXED_SESSION_SITE_PACKAGES = Join-Path (Split-Path -Parent (Split-Path -Parent $py)) 'Lib\site-packages'`,
   followed by a `Test-Path -PathType Container` check (section 4 already had this form).
2. `c3_break.py`, and `c3_ctrlc.py`'s `run` path, reset the venv prefix **before the harness import and before the
   first `import sysconfig`**. The snippet this packet first proposed (`import os, sysconfig` *then* set `sys.prefix`)
   **does not work**: Python 3.11's `sysconfig` copies `sys.prefix` into module globals at import time, so a later
   reset leaves purelib at the base install (verified on the workstation; it would have failed closed at its own
   assert). The applied text asserts `"sysconfig" not in sys.modules`, checks `pyvenv.cfg`, sets
   `sys.prefix = sys.exec_prefix = <venv>`, then imports `sysconfig` and asserts purelib equals step 3's
   `WEATHER_FIXED_SESSION_SITE_PACKAGES` (a missing variable fails closed too).
3. The trap is recorded in the spec's top note: *`-S` means `sys.prefix` is the base install; never derive a venv path
   from `sysconfig` under `-S`.* Carry it into the pilot runbook record.

**Reproduced and fixed on the workstation** (venv `C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe`,
tree = detached `c9cf068be` worktree, direct runs outside `c3_run.ps1`):
- old step-3 rule → `C:\Users\Michael\AppData\Local\Programs\Python\Python311\Lib\site-packages`; the probe fails
  with `ModuleNotFoundError: No module named 'requests'`;
- old `c3_break.py … s5 positive`, even with the correct variable in the caller → rc 1, helper output
  `ModuleNotFoundError: No module named 'requests'` (the harness overwrites the variable);
- F1 step-3 rule → the probe prints `{"patched": false, "silencer": false, "sitecustomize": false, …}`;
- F1 `c3_break.py … s5 positive` → `raised: true, forced: false, exit_code: 3`, `C3 STEP 5 PASS`;
- F1 `c3_break.py` with the variable unset, or set to the base path → `AssertionError` before the harness import (fail closed).

`k` and the `started` formulas are unchanged by F1. No process is added.

**F3 and F4 (found by the workstation dry pass, 2026-10-07; full ledger `C3-DRYPASS-20261007.md`).**
- **F3 (`c3_run.ps1`, now `c3-run-v3.1-F3`).** In v3.1, **6b HARD STOPs** (`started=6` against the pin 5;
  `consoleForeign=1`), and then every later call in that console is `REFUSED`. There are two causes.
  - The 6b mutant's `CREATE_NO_WINDOW` stub gets its own `conhost.exe` inside the Job. So 6b is **`2k+2`**.
  - The runner's Ctrl+Break, sent to the stub's process group on another console, makes conhost leave the stub's PID in
    the C3 console's process list **after the stub has exited**. This was reproduced in isolation. It is a stale entry,
    not a process, and nothing escaped.
  - The fix: an entry whose PID provably has no live process is recorded in the new record-only field `consoleStale`,
    and excluded from the start refusal and from `consoleForeign`. Any doubt counts as live (fail closed).
    `consoleForeign>0` remains a HARD STOP.
  - In section 4, 6b is now `-ExpectStarted (2*$k+2)`.
  - **On the host, expect `consoleStale=[close:<pid>]` on the s6b line and on later lines. This is normal.**
- **F4 (operator text only).** `$w = @(Get-ChildItem …).FullName` returns a string for a single folder, so the
  step-7 judge got the folder `C` and refused. Both step-7 lines now collect the names with `ForEach-Object`.
- P8 item 5 line 2 now reports `c3_run.ps1:353` (it was 336).

## 3. Prerequisites

### 3.1 Load class and lease

**Light. No `workload_admission` lease. Allowed at 09:00-09:30.**
- The policy's heavy list is test suites, compileall, training, replay and bulk scans. The rehearsal is none of these.
  It peaks at about 9 processes, under 500 MB working set, about 5 minutes of machine time and under 1 MB written
  (spec § "Resource profile"). It is not pytest, even though it imports the #230 harness module.
- It must still not overlap heavy work. Master-agent confirms at 08:55 that nobody holds the lease and that the N2
  chain is terminal.
- **It must not be launched by an agent.** HOST_LOAD_POLICY rule 6 has the S4U guard terminate `claude.exe`- or
  `codex.exe`-rooted inline Python outside 00:30-09:00. Step 1 also aborts if the console's parent is an agent or a
  shell, and `c3_run.ps1` refuses a shared console. The owner opens the console with **Win+R** →
  `powershell.exe -NoProfile`. Every process then has `explorer.exe` ancestry, which the guard does not target.
  Master-agent never types into, attaches to, or starts processes in that console.

### 3.2 Scheduled tasks 08:30-10:00 (do not touch any of them)

`config/scheduled_tasks.json` carries no times. Times come from the registrars at `c9cf068be` and `HOST-FACTS-20261006.md`.

| Task | When | Relation to C3 |
| --- | --- | --- |
| `WeatherColdSnapshotNightly` (91a) | **Host fact (master-agent, 10-07): on 10-08, 91a runs at 00:30 under the OLD pin. There is NO 06:50 91a run on 10-08.** 06:50-07:30 on 10-08 is only the #238 dry run plus `register -Apply`. The 06:50 schedule (window to 09:00, backstop 09:00, `ExecutionTimeLimit` PT2H20M = 09:10) applies from 10-09 | **10-08 gate:** the re-pin is done, and no 91a or dry-run process is alive at 08:55 (3.3) |
| `WeatherDailySettlementPromotionRefresh` (Stage A) | 09:30 | Rehearsal console closed by 09:27 |
| `WeatherEveningEvidenceRefresh` (Stage B) | 00:35 trigger, 09:00 teardown, PT8H40M limit = 09:15, **if enabled** | Expected disabled (owner: #153 Stage B disabled). Verify `State = Disabled` |
| `WeatherExchangeEconomicsSnapshotRefresh` | Host: 06:50 (repo default 09:00, 5-minute limit) | Verify its next run is not 09:00-09:30. If it is, it is record-only noise; do not move it |
| Repeating: `WeatherMemoryCommitGuard` (1 min), `WeatherExecutionTapeSupervisor` (1 min), CLOB/observation supervisors (1 min), snapshot supervisor (2 min), `WeatherMakerEvidenceCapture` 88a (5 min), `WeatherHostHealthWatchdog` (15 min), S4U guard | continuous | Outside the Job and the console. They appear only in record-only `vanishedOutsideJob`. Never stopped, never queried by name from the C3 console |
| `WeatherIntegrationMerge_*` / `WeatherIntegrationSuite_*` / `WeatherOneShotPush` (N2) | must be finished, not pending | Gate (3.3) |

Master-agent runs this read-only at 08:50 from its own shell, not the C3 console:

```powershell
$from = (Get-Date).Date.AddHours(8).AddMinutes(30); $to = (Get-Date).Date.AddHours(10)
Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' } | ForEach-Object {
    $i = $_ | Get-ScheduledTaskInfo
    if ($_.State -eq 'Running' -or ($i.NextRunTime -ge $from -and $i.NextRunTime -le $to)) {
        [pscustomobject]@{ Task = $_.TaskName; State = $_.State; Next = $i.NextRunTime; Last = $i.LastRunTime; Result = $i.LastTaskResult }
    }
} | Sort-Object Next | Format-Table -AutoSize
(Get-ScheduledTask -TaskName 'WeatherEveningEvidenceRefresh').State
Get-ScheduledTask | Where-Object { $_.TaskName -like 'WeatherIntegration*' -or $_.TaskName -eq 'WeatherOneShotPush' } | ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; [pscustomobject]@{ Task = $_.TaskName; State = $_.State; Next = $i.NextRunTime; Result = $i.LastTaskResult } } | Format-Table -AutoSize
```

GO requires all of the following:
- no `WeatherIntegration*` or `WeatherOneShotPush` task is `Running` or due before 10:00;
- `WeatherColdSnapshotNightly` is not `Running`;
- Stage B is `Disabled`;
- nothing unexpected is due 09:00-09:30.

### 3.3 The 91a re-pin and its first 06:50 run: no clash

- **Not touched.** The rehearsal reads only `<tree>\src`, `<tree>\tests\operations`, `<tree>\scripts\ops` (templates
  and Job helper), `<tree>\sitecustomize.py` and `git rev-parse`/`status`/`diff` on `<tree>`. It never references:
  - the 91a deployment worktree (`weather-cold-snapshot-deployed-<sha>`, re-pinned in N2 before RS1b);
  - its request/policy file;
  - its `scratch\cold_snapshot_compression\` output;
  - `data\`;
  - the `WeatherColdSnapshotNightly` task.
  91a runs `cold_snapshot_nightly_run.ps1` from its own deployed worktree, so step 8's read lock on the production
  checkout's `scripts\ops\windows_kill_on_close_job.ps1` cannot block it.
- **Time gate, 10-08 (host fact from master-agent, 10-07).** There is no 06:50 91a run on 10-08: 91a runs at 00:30
  under the old pin, and 06:50-07:30 holds only the #238 dry run plus `register -Apply`. At 08:55 master-agent
  confirms read-only that **the re-pin is done** and that **no 91a or #238 dry-run process is alive**
  (`WeatherColdSnapshotNightly` not `Running`, and no process whose command line references the 91a deployment
  worktree or the dry run). Either one failing is a no-go for 10-08.
- **Time gate, 10-09 fallback only.** From 10-09, 91a's first 06:50 run may run to its 09:00 backstop. Before step 1,
  master-agent confirms read-only that the task is not `Running` and that
  `C:\Users\micha\Desktop\github\weather\scratch\cold_snapshot_compression\nightly-20261009-*\wrapper-result.json`
  exists with a terminal status. Any terminal status (including `FAILED_RETAIN_AND_INSPECT`) is fine for C3; it
  only has to have ended.
  - If 91a is still running at 09:05 on 10-09, **no-go for that day.** Starting later cannot meet the 09:20 cut-off with margin.
- **B replay and N2.** The B replay ends by 06:40 at the latest (StopAt 06:40), and **N2 being terminal** (closing
  receipt, `WeatherOneShotPush` verified) is a gate in its own right at 08:55.
- **No re-pin, re-registration, merge, pull or checkout write between 08:55 and the end of cleanup** (spec N6, P3).

### 3.4 Disk

- Spec P7: `(Get-Volume -DriveLetter C).SizeRemaining` > 5 GiB (5,368,709,120 bytes).
- The rehearsal itself writes under 1 MB to `C:\c3`, plus transient CodeDom files in `%TEMP%`.
- The 50 GiB heavy-work floor does not apply (light work). Record the byte figure.

### 3.5 Credentials, live orders, signing: console and dry-run only (confirmed, no blocker)

Every step was checked against the spec text and the scripts:
- No step builds a manifest, runs a sealer, starts a sealed launcher, signs, places, cancels or prepares an order.
- No step contacts the exchange, a wallet or a paid API.
- No step opens Credential Manager, `.env*`, `*.cred`, `*.key`, `*.pem` or `config/local/*`.
- `_default_launcher_runner` runs only on the #230 harness stub (steps 5-7) and on the pinned scratch stub (step 8).
- `c3_prompt.py` refuses (exit 9) if the stub text contains `credential`, `wallet`, `clob`, `polymarket`, `manifest`,
  `seal`, `stage0`, `stage1` or `data\`.
- The step-8 prompt runs only the extracted `_prompt_until`, under a minimal builtins table. Nothing else from
  `stage0`/`stage1` executes.

P5 env-name check: **clear (host fact, master-agent 10-07): the host has no `WEATHER_*` variable in any scope
(process, user or machine).** No owner P5 decision is needed. The console check still runs at 09:00 and any printed
name is still an abort. Note for the operator: P5 runs **before** step 3, which itself sets
`WEATHER_FIXED_SESSION_SRC`/`WEATHER_FIXED_SESSION_SITE_PACKAGES` in the console; those two names are expected after
step 3 and are not a P5 finding. A credential-shaped name (`KEY`, `SECRET`, `TOKEN`, `PRIVATE`, `CLOB`, `POLY`) is
always an abort.

### 3.6 Night N2 precondition (spec deviation; owner/master must accept it explicitly)

- The spec recommends "a morning after a night with no landing and no export". 10-08 follows **N2**, a landing night
  (91a re-pin → RS1b → RF2e → B replay with StopAt 06:40).
- Through N8, every night is a landing or an export night, so the recommendation cannot be met before 10-15. The
  owner's "ASAP" decision implies accepting this.
- The safety-relevant substance is still enforced by the 08:55 gates: the N2 chain is terminal, all three capture
  workers have recovered, no lease is held, `git status` is clean, HEAD equals the N2 closing receipt, and tier A is
  unchanged since `c9cf068be`.
- **No reseal has happened since #230.** The official record must come from the post-#230 tree before any reseal.
  Master confirms this.

### 3.7 Roles

- **Owner (operator; required physically at the console).**
  - Opens the console with Win+R.
  - Pastes each block from `C:\c3\C3-COMMANDS-20261008.txt`, opened in Notepad. Notepad is not attached to the console.
  - Presses **Ctrl+C exactly once** in P8 item 6 (after `C3 GUARD STUB READY`) and in step 7.1 (after the
    `press Ctrl+C ONCE now` line). Never presses Ctrl+Break.
  - Types `C3_REHEARSAL_TYPED_INPUT_ACCEPTED` in 8a and `WRONG` in 8b.
  - Owns the 09:20 and 09:25 time calls, reads each verdict line aloud or into the record, and is named as the
    operator in the record.
  - Before the run, the owner answers spec **Q2** (whether the extracted `_prompt_until` counts as "reach that
    confirmation prompt"). Without that answer, step 8 cannot count for the record. Q1 (R6 `caller_stdin_open=True`)
    is recommended "keep".
- **Master-agent (preparer and observer; never at the console).**
  - Before 08:55: stages the files (2.3, after F1) and verifies their SHA-256, writes the command sheet, runs the
    3.2-3.6 gates read-only, and gives GO or NO-GO by 08:58.
  - During the run: no merges, pulls, registrations, re-pins, checkout writes or heavy work, and nothing attached to
    the console. It watches capture health only.
  - Afterwards: the read-only verification, archive and cleanup in section 6, and the docs-only record PR on the light
    path (before 12:00).

## 4. Console command sequence (owner types or pastes, in ONE console)

The blocks are PowerShell 5.1 only: no `&&`, `||`, `??` or ternary. Section numbers refer to the spec. Each
`c3_run.ps1` call prints a `C3RUN <label> … verify …` line. **Hands off the keyboard until that line appears**, except
for the designated keypresses.

**09:00, step 1 (Win+R → `powershell.exe -NoProfile` → Enter):**
```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
[Console]::IsInputRedirected; [Console]::IsOutputRedirected; $Host.Name; $PSVersionTable.PSVersion
$parent = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").ParentProcessId
(Get-CimInstance Win32_Process -Filter "ProcessId=$parent").Name
```
Expected: `False`, `False`, `ConsoleHost`, `5.1.x`, then `explorer.exe` (or `WindowsTerminal.exe`, `OpenConsole.exe` or
`conhost.exe`). Anything else: ABORT.

**C0, P2, P5-P8 facts (one-shot reads):**
```powershell
$tree = 'C:\Users\micha\Desktop\github\weather'
$py   = 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe'
$c3   = 'C:\c3\20261008'
$base = 'c9cf068be6f7f74c6ac7304690d88f8fd90fa9e6'
git -C $tree rev-parse HEAD
git -C $tree --no-optional-locks status --short
$tierA = @('src/weather/operations/international_live_session_runner.py','src/weather/operations/live_path_security.py','src/weather/operations/windows_silent.py','tests/operations/live_launcher_break_harness.py','tests/operations/test_live_runner_console_guards.py','scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl','scripts/ops/international_live_templates/stage0.py.tmpl','scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl','scripts/ops/windows_kill_on_close_job.ps1','sitecustomize.py')
git -C $tree --no-optional-locks diff --name-only $base HEAD -- $tierA
git -C $tree --no-optional-locks diff --name-only $base HEAD -- src/weather tests/__init__.py
(Get-ChildItem Env:).Name | Where-Object { $_ -match 'WEATHER|POLY|CLOB|KEY|SECRET|TOKEN|PRIVATE' }
Get-ChildItem -LiteralPath $c3 -Force | Select-Object Name, Length
(Get-Volume -DriveLetter C).SizeRemaining
$env:COMPUTERNAME; [Environment]::OSVersion.Version; cmd /c ver
(Get-FileHash $py -Algorithm SHA256).Hash.ToLower()
(Get-FileHash (Join-Path $tree 'scripts\ops\windows_kill_on_close_job.ps1') -Algorithm SHA256).Hash.ToLower()
```

Expected:
- HEAD = the N2 receipt SHA, and `status` prints nothing;
- the **tier-A diff prints nothing**;
- the closure diff prints at most `src/weather/schema_registry_data.py` and `src/weather/schema_registry_recent_data.py`.
  Record any other path, and ABORT if it is a tier-A path;
- the env filter prints nothing (3.5);
- `$c3` holds exactly the six scripts;
- free space > 5368709120 bytes;
- Windows ≥ 10.0;
- the Job helper hash is `05f362cdb04142b30c436b91175555e5c66ebaff2594fde6e8578cb5db7e2669`.

Write HEAD, the python hash, host, console and Windows version into the paper record.

**Independent script pins (Defender N5; ABORT on any MISMATCH).** F1/F2 hashes filled in (section 2.3):
```powershell
$expect = [ordered]@{
  'c3_run.ps1'             = 'bdc597d7d456450fcbcff01428ce5066fccd59c184fffcf5a21c02156f6f2153'
  'c3_break.py'            = '6ef96ecc3281916e6c6fbb7f519909273c9201153c49d45cdae0c68af37cfafa'
  'c3_ctrlc.py'            = 'b567542703968e985fc8173d0107813a7e7b5987aac165994e3f699abf72ead2'
  'c3_prompt.py'           = 'b0a55816abf30d9595ad8771a5b34fc22e386c42d298dad00d08ea3562d4bccd'
  'c3_prompt_launcher.ps1' = '742c4e9314983689fa71610d8ceeaf6e9a285a16b7fca42f654bc8c70c6ca419'
  'c3_prompt_child.py'     = 'd2b0a84efa5cd79b7fc0ed3f49cd6c0d0af968a9f383f8775a621d77c8436714'
}
foreach ($f in $expect.Keys) { $h = (Get-FileHash (Join-Path $c3 $f) -Algorithm SHA256).Hash.ToLower(); if ($h -ne $expect[$f]) { "MISMATCH $f $h" } else { "ok $f" } }
```

**P8 item 2: session helpers and prompt-hash extraction (first `c3_run.ps1` call, unpinned):**
```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$c3Start = Get-Date
function New-C3RunDir([string]$name) { $d = Join-Path $c3 $name; if (Test-Path $d) { throw "run folder exists: $d" }; (New-Item -ItemType Directory -Path $d).FullName }
function Get-C3Ledger([string]$label) {
    $l = @(Get-Content "$c3\launch-ledger.txt" | Where-Object { $_ -match (' label=' + [regex]::Escape($label) + ' ') })
    if ($l.Count -ne 1) { throw "expected exactly one ledger line for $label, found $($l.Count)" }
    $h = @{}; foreach ($m in [regex]::Matches($l[0], '(\w+)=(\[[^\]]*\]|\S+)')) { $h[$m.Groups[1].Value] = $m.Groups[2].Value }; $h
}
function Test-C3Contained([hashtable]$row) {
    $row.verify -eq 'OK' -and $row.escaped -eq '0' -and $row.memberMismatch -eq '0' -and $row.consoleForeign -eq '0' -and $row.startedPin -ne 'DIFF'
}
& "$c3\c3_run.ps1" -Label p8-prompt-hash -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 -Tokens @('-I','-S','-B',"$c3\c3_prompt_child.py",$tree,'--hash-only')
```
Expected: both `prompt_until_sha256` values = `c03caf8c…44597`, then `C3 PROMPT EXTRACTION OK`, then `C3RUN p8-prompt-hash … verify OK`.

**P8 item 3 (verify, not edit):**
```powershell
@(Select-String -Path "$c3\c3_prompt_launcher.ps1" -SimpleMatch 'c03caf8cbe6114c2c42ff216c49e8c2b6453f57f29ed2ea12146b40cffd44597').Count
```
Expected: `1`.

**P8 item 4: pins (copy the printed JSON into the paper record):**
```powershell
$files = 'c3_run.ps1','c3_break.py','c3_ctrlc.py','c3_prompt.py','c3_prompt_child.py','c3_prompt_launcher.ps1'
$pin = [ordered]@{ tree = $tree; head = (git -C $tree rev-parse HEAD); prompt_until = 'c03caf8cbe6114c2c42ff216c49e8c2b6453f57f29ed2ea12146b40cffd44597'
                   job_helper = (Get-FileHash (Join-Path $tree 'scripts\ops\windows_kill_on_close_job.ps1') -Algorithm SHA256).Hash.ToLower() }
foreach ($f in $files) { $pin[$f] = (Get-FileHash (Join-Path $c3 $f) -Algorithm SHA256).Hash.ToLower() }
$pin | ConvertTo-Json | Set-Content -Encoding ascii "$c3\p8-pins.json"; Get-Content "$c3\p8-pins.json"
```

**P8 item 5: static check.** The first line must print nothing; the second must print exactly one line, inside
`Get-C3Snapshot`:
```powershell
Select-String -Path "$c3\*.ps1","$c3\*.py" -Pattern 'Stop-Process|taskkill|Get-Process|wmic|TerminateProcess|TerminateJobObject|StartTime|os\.kill|\.kill\(|\.terminate\(|send_signal|GenerateConsoleCtrlEvent|psutil|Stop-Job|Remove-Job|Invoke-CimMethod'
Select-String -Path "$c3\*.ps1","$c3\*.py" -Pattern 'Get-CimInstance|Win32_Process'
```

**P8 item 6: guard self-test.** Press nothing in run 1. In run 2, wait for `C3 GUARD STUB READY`, then press **Ctrl+C once**:
```powershell
$g = "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);print('C3 GUARD STUB READY',flush=True);time.sleep(10)"
& "$c3\c3_run.ps1" -Label p8-guard-1 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 30 -Tokens @('-I','-S','-B','-c',$g)
$k = [int](Get-C3Ledger 'p8-guard-1').started
if ($k -notin 1,2) { throw "k=$k is not 1 or 2: abort (unexplained venv layout)" } else { "k=$k" }
& "$c3\c3_run.ps1" -Label p8-guard-2 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 30 -ExpectStarted $k -Tokens @('-I','-S','-B','-c',$g)
```
```powershell
$g1 = Get-C3Ledger 'p8-guard-1'; $g2 = Get-C3Ledger 'p8-guard-2'
$ok1 = (Test-C3Contained $g1) -and $g1.rc -eq '0' -and $g1.ctrlC -eq 'False' -and $g1.ctrlCCount -eq '0'
$ok2 = (Test-C3Contained $g2) -and $g2.rc -eq '0' -and $g2.timedOut -eq 'False' -and $g2.interrupted -eq 'False' -and $g2.ctrlC -eq 'True' -and $g2.ctrlCCount -eq '1' -and $g2.startedPin -eq 'OK'
if ($ok1 -and $ok2) { 'C3 P8 GUARD SELF-TEST PASS' } else { 'C3 P8 GUARD SELF-TEST FAIL'; $g1; $g2 }
```
(P8 item 7 is dry-pass only; skip it on the host.)

**Step 2:**
```powershell
$tmpl = Join-Path $tree 'scripts\ops\international_live_templates\fixed_session_launcher.ps1.tmpl'
Select-String -Path $tmpl -Pattern '^\s*"-I",$|^\s*"-S",$|^\s*"-B",$|runpy.run_module' | ForEach-Object { $_.LineNumber.ToString() + ': ' + $_.Line.Trim() }
```
Expected: 4 lines, 141-143 and 145.

**Step 3 (with the F1 site-packages rule):**
```powershell
$env:WEATHER_FIXED_SESSION_SRC = Join-Path $tree 'src'
$env:WEATHER_FIXED_SESSION_SITE_PACKAGES = Join-Path (Split-Path -Parent (Split-Path -Parent $py)) 'Lib\site-packages'
if (-not (Test-Path -LiteralPath $env:WEATHER_FIXED_SESSION_SITE_PACKAGES -PathType Container) -or ((Get-Item -LiteralPath $env:WEATHER_FIXED_SESSION_SITE_PACKAGES -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'venv site-packages missing or a reparse point: abort' } else { $env:WEATHER_FIXED_SESSION_SITE_PACKAGES }
Remove-Item Env:WEATHER_ALLOW_CONSOLE_CHILDREN -ErrorAction SilentlyContinue
$env:PYTHONPATH = $tree
$probe = "import os,runpy,sys;sys.dont_write_bytecode=True;sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC']);sys.path.append(os.environ['WEATHER_FIXED_SESSION_SITE_PACKAGES']);import json,subprocess;before=subprocess.Popen;import weather.operations.international_live_session_runner as r;print(json.dumps({'patched': subprocess.Popen is not before or bool(getattr(subprocess.Popen,'_weather_silent_windows_children',False)),'silencer':'weather.operations.windows_silent' in sys.modules,'sitecustomize':'sitecustomize' in sys.modules,'runner':r.__file__}))"
& "$c3\c3_run.ps1" -Label s3 -Exe $py -WorkingDirectory $tree -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-I','-S','-B','-c',$probe)
Remove-Item Env:PYTHONPATH
```

**Step 4:**
```powershell
$env:PYTHONPATH = $tree
& "$c3\c3_run.ps1" -Label s4 -Exe $py -WorkingDirectory $tree -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-B','-c',"import json,subprocess,sys;print(json.dumps({'patched': bool(getattr(subprocess.Popen,'_weather_silent_windows_children',False)),'sitecustomize':'sitecustomize' in sys.modules}))")
Remove-Item Env:PYTHONPATH
```

**Step 5.** First compare the pins with the paper copy and re-run the P8 item-5 static check:
```powershell
Get-Content "$c3\p8-pins.json"
Select-String -Path "$c3\*.ps1","$c3\*.py" -Pattern 'Stop-Process|taskkill|Get-Process|wmic|TerminateProcess|TerminateJobObject|StartTime|os\.kill|\.kill\(|\.terminate\(|send_signal|GenerateConsoleCtrlEvent|psutil|Stop-Job|Remove-Job|Invoke-CimMethod'
foreach ($n in 1..3) {
  $d = New-C3RunDir "s5-$n"
  & "$c3\c3_run.ps1" -Label "s5-$n" -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted (2*$k+1) -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s5','positive')
}
```

**Step 6:**
```powershell
$d = New-C3RunDir 's6a'
& "$c3\c3_run.ps1" -Label s6a -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted (2*$k+1) -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s6a','no_break')
# [F3 MUST-FIX 1] 6b is NOT run here: it is the LAST c3_run.ps1 call, after step 8 (see "Step 8d").
```

**Step 7.0, control (press nothing):**
```powershell
$d = New-C3RunDir 's7-control'
& "$c3\c3_run.ps1" -Label s7-control -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 150 -ExpectStarted (3*$k+1) -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'run',$tree,$d,'control')
$w = @(Get-ChildItem -Path $d -Directory -Filter 'c3-s7-ctrlc-control-*' | ForEach-Object { $_.FullName })   # [F4]
if ($w.Count -ne 1) { throw "expected exactly one control work folder, found $($w.Count)" }
& "$c3\c3_run.ps1" -Label s7-control-judge -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'judge',$tree,$w[0],'s7-control','control')
```

**Step 7.1, operator.** Wait for `press Ctrl+C ONCE now`, then press **Ctrl+C once** within 15 s, then hands off until
the `C3RUN s7-1 … verify` line:
```powershell
$d = New-C3RunDir 's7-1'
& "$c3\c3_run.ps1" -Label s7-1 -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 150 -ExpectStarted (3*$k+1) -WatchMarkersUnder $d -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'run',$tree,$d,'operator')
$w = @(Get-ChildItem -Path $d -Directory -Filter 'c3-s7-ctrlc-*' | ForEach-Object { $_.FullName })   # [F4]
if ($w.Count -ne 1) { throw "expected exactly one work folder, found $($w.Count)" }
& "$c3\c3_run.ps1" -Label s7-1-judge -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 60 -ExpectStarted $k -Tokens @('-I','-S','-B',"$c3\c3_ctrlc.py",'judge',$tree,$w[0],'s7-1','operator')
```
Only if the judge prints `operator_timing_only: true`, repeat once with `s7-2` / `s7-2-judge` (same commands with the
labels and folder changed). Never run a third time.

**Step 8.** First check the clock (8a must start by **09:20**), compare `p8-pins.json` with the paper copy, and
master-agent confirms that no checkout writer will run:
```powershell
Get-Date -Format HH:mm:ss
$pin = Get-Content "$c3\p8-pins.json" -Raw | ConvertFrom-Json
$boot = "import os,runpy,sys;sys.dont_write_bytecode=True;sys.path.insert(0,os.environ['WEATHER_FIXED_SESSION_SRC']);sys.path.append(os.environ['WEATHER_FIXED_SESSION_SITE_PACKAGES']);p=sys.argv.pop(1);runpy.run_path(p,run_name='__main__')"
$s8 = @('-I','-S','-B','-c',$boot,"$c3\c3_prompt.py","$c3\c3_prompt_launcher.ps1",$pin.'c3_prompt_launcher.ps1',$pin.'c3_prompt_child.py',$pin.job_helper)
& "$c3\c3_run.ps1" -Label s8a -Exe $py -WorkingDirectory $tree -TimeoutSeconds 180 -ExpectStarted (2*$k+3) -Tokens $s8
```
At the prompt in 8a, type `C3_REHEARSAL_TYPED_INPUT_ACCEPTED` and press Enter. Then 8b, typing `WRONG` and Enter:
```powershell
& "$c3\c3_run.ps1" -Label s8b -Exe $py -WorkingDirectory $tree -TimeoutSeconds 180 -ExpectStarted (2*$k+3) -Tokens $s8
```
8c is optional: type nothing, and **skip it if the clock is past 09:23**:
```powershell
& "$c3\c3_run.ps1" -Label s8c -Exe $py -WorkingDirectory $tree -TimeoutSeconds 180 -ExpectStarted (2*$k+3) -Tokens $s8
```

**Step 8d: step 6b, the LAST call [F3 MUST-FIX 1]** (run it even if 8c was skipped). Its Ctrl+Break leaves a stale
console-list entry for the rest of this console's life, so nothing may run through `c3_run.ps1` after it:
```powershell
$pin6b = 2*$k+2          # [F3 S-F3a] set to (2*$k+1) ONLY if step 4 printed "patched": false
$d = New-C3RunDir 's6b'
& "$c3\c3_run.ps1" -Label s6b -Exe $py -WorkingDirectory $c3 -TimeoutSeconds 120 -ExpectStarted $pin6b -Tokens @('-I','-S','-B',"$c3\c3_break.py",$tree,$d,'s6b','sitecustomize')
```
Expected: no `BREAK`, `sitecustomize_loaded: true`, `popen_silenced: true`, `started=6` (k=2), `verify OK`,
`consoleStale=[close:<stub PID>]`.

**Step 9 (in the same console, then close it):**
```powershell
Get-Content "$c3\launch-ledger.txt"
Get-Content "$c3\launch-ledger.txt" | Where-Object { $_ -notmatch ' escaped=0 ' -or $_ -notmatch ' memberMismatch=0 ' -or $_ -notmatch ' consoleForeign=0 ' -or $_ -notmatch ' verify=OK ' -or $_ -match ' startedPin=DIFF ' }
Get-Content "$c3\launch-ledger.txt" | Where-Object { if ($_ -match ' label=s6b ') { $_ -notmatch ' consoleStale=\[(close:\d+)?\]( |$)' } else { $_ -notmatch ' consoleStale=\[\]( |$)' } }   # [F3] must print nothing: consoleStale=[] except s6b ([] or [close:<pid>])
Get-ChildItem -LiteralPath "$tree\src","$tree\tests","$tree\scripts","$tree\__pycache__" -Recurse -Filter *.pyc -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $c3Start } | Select-Object -ExpandProperty FullName
Get-FileHash "$c3\*.ps1","$c3\*.py","$c3\p8-pins.json","$c3\launch-ledger.txt" | Format-Table -AutoSize
Get-ChildItem $c3 -Recurse -Include markers.txt,helper-output.txt,helper-rc.txt,sentinel.txt | Get-FileHash | Format-Table -AutoSize
Get-Date -Format HH:mm:ss
exit
```
The second and third commands must print nothing. `exit` closes the console, which also clears the
`WEATHER_FIXED_SESSION_*` variables, the process-scope execution policy and the C3 types.

## 5. Pass / fail

**PASS** requires every row below. Any HARD STOP overrides everything else.

| # | Criterion | Output that proves it |
| --- | --- | --- |
| C0 | Tree is post-#230, tier A unchanged, clean | `git diff … -- $tierA` empty; `status --short` empty; Job helper SHA-256 `05f362cd…2669` |
| 1 | Real, exclusive operator console | `False False ConsoleHost 5.1.x`; parent `explorer.exe` (or an accepted terminal host) |
| P5 | No credential-shaped environment names | The env filter prints nothing |
| P8.2 | Prompt bound to the reviewed source | Both hashes `c03caf8c…44597`; `C3 PROMPT EXTRACTION OK`; `C3RUN p8-prompt-hash … verify OK` |
| P8.5 | No stop path in the scripts | Line 1 prints nothing; line 2 prints exactly 1 line (`Get-C3Snapshot`), both times |
| P8.6 | Native Ctrl+C guard holds on the 2nd call | `C3 P8 GUARD SELF-TEST PASS`; ledger `p8-guard-2`: `ctrlC=True ctrlCCount=1 interrupted=False timedOut=False rc=0 startedPin=OK`; `k` ∈ {1, 2} |
| 2 | Template starts the runner isolated | 4 lines: `"-I",` `"-S",` `"-B",` + the `runpy.run_module(...runner...)` bootstrap |
| 3 | Production shape loads no silencer | `{"patched": false, "silencer": false, "sitecustomize": false, "runner": "C:\Users\micha\Desktop\github\weather\src\weather\operations\international_live_session_runner.py"}`; `C3RUN s3 … startedPin=OK … verify OK` |
| 4 | Negative control | `{"patched": true, "sitecustomize": true}` (a `false` is recorded as NOT REPRODUCIBLE, not a fail); `verify OK` |
| 5 | Cooperative Ctrl+Break, ×3 | Each: `events` START < `deadline_ms` < BREAK < `release_ms`, then EXIT; `raised: true, cooperative: true, forced: false, exit_code: 3, child_stdin: ["-3"], sitecustomize_loaded: false, popen_silenced: false`; `C3 STEP 5 PASS`; `C3RUN s5-n … startedPin=OK … verify OK` (`started` = 2k+1) |
| 6a | Marker not spurious | `events` without `BREAK`; `verify OK` |
| 6b | Silencer detected | No `BREAK`; `sitecustomize_loaded: true, popen_silenced: true` (if step 4 was `false`: record NOT REPRODUCIBLE); `verify OK` |
| 7.0 | Sentinel not spurious | `C3 STEP 7 CONTROL PASS`; ledger `s7-control`: `ctrlC=False ctrlCCount=0 verify=OK` |
| 7.1 | Operator Ctrl+C delivered, cooperative end | Judge prints `C3 STEP 7 PASS` (sentinel: one READY, one DONE, exactly one in-window SIGINT; ledger `s7-1`: `rc=0 timedOut=False interrupted=False ctrlC=True ctrlCCount=1 verify=OK`); at most one `s7-2` repeat, and only after `operator_timing_only: true` |
| 8a | Prompt reads console keys with stdin on NUL | Pin line, all `true`; `C3 STUB stdin_redirected=True`; child line `prompt_bound: true`; echo while typing; `{"typed_matches": true, "length": 33}`; `{"returncode": 0, "raised": false}`; `C3RUN s8a … startedPin=OK … verify OK` (`started` = 2k+3) |
| 8b | Wrong literal fails closed | `{"typed_matches": false, "length": 5}`; `{"returncode": 4, "raised": false}`; `verify OK` |
| 8c (opt.) | Timeout | `{"typed_matches": null, "reason": "timeout"}` + `returncode: 5`, or `{"raised": true, "cooperative": true…}` (record which); `verify OK` |
| 9 | Containment over the whole run | One ledger line per call; the ledger filter prints nothing; the `.pyc` check prints nothing; evidence hashes recorded |

Record only, never a fail: `vanishedOutsideJob`/`outsideJob`, `pidReuse`, `lateMembers`, `peakActive`,
`peakJobPrivateMB` and `guardRemoved`.

The official record goes in `INTERNATIONAL_MM_LIVE_PILOT.md` ("Gate before the first live attempt after PR #229") or
item 330, by a docs-only light-path PR. It has one line per step (`PASS`, `FAIL` or `NOT REPRODUCIBLE`) plus the
spec § Step 9 field list, the owner's Q2 answer and the operator name.

## 6. Abort, then cleanup

### 6.1 Abort conditions

- **HARD STOP:** any `C3RUN`/ledger line with `escaped>0`, `memberMismatch≠0` or `consoleForeign>0` (`verify=HARDSTOP`).
- **ABORT:**
  - any `verify=FAIL` (evidence missing, inconsistent Job read, or `startedPin=DIFF`) or `verify=REFUSED`;
  - any per-step abort in the spec's § "Abort summary" (for example step 5 without a `BREAK`, `forced: true`,
    `exit_code≠3`, or 8a `stdin_redirected=False`);
  - any C0, P5 or P8 mismatch;
  - script pin `MISMATCH`.
- **Time aborts:**
  - pre-flight not GO by 09:03, or step 1 not started by 09:05;
  - **8a not started by 09:20** (stop; do not run 8a);
  - 8c skipped after 09:23;
  - the console closed no later than 09:27 in every case.
- **External aborts (master-agent calls them):**
  - a capture supervisor reports a worker down or a `STALE_CODE` restart;
  - anything starts writing the checkout;
  - the lease becomes held;
  - 91a turns out to be still running.

  The owner lets the current `c3_run.ps1` call finish (never interrupt it), then stops.

### 6.2 Abort procedure

1. Do not press Ctrl+C or Ctrl+Break to stop a call.
   - If a call shows no `C3RUN` line by its `-TimeoutSeconds` + 60 s, close the console window with **X**. Windows
     closes the Job handle, and kill-on-close ends every member.
   - This is safe, because `consoleForeign=0` proves that only Job members and this PowerShell share the console.
2. Otherwise, after the abort line, run only the first two lines of the step-9 block (the ledger print and the
   filter), read-only. Then `exit`.
3. Record `FAIL` with the step number and the full ledger line. Keep `C:\c3\20261008` untouched.
   - **After a HARD STOP:** no rerun on the capture host until that ledger line has been reviewed (spec).
   - **After an ABORT:** fix the cause, then repeat another day from step 1 in a new console and a **new** scratch
     folder (`C:\c3\<newdate>`). Never resume mid-way.
4. Never stop, `taskkill` or `wmic` any process by name, image, command line or start time (spec cleanup rule 1).

### 6.3 Cleanup (master-agent, from its own shell, after the console is closed)

**(a) Verify nothing remains.** Read-only, filtered by the scratch path, excluding this shell:
```powershell
$needle = 'C:\c3\'
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (($_.CommandLine -like ('*' + $needle + '*')) -or ($_.ExecutablePath -like ($needle + '*'))) } | Select-Object ProcessId, ParentProcessId, Name, CreationDate, CommandLine)
if ($left.Count -eq 0) { 'C3 CLEANUP: no process references C:\c3' } else { 'C3 CLEANUP: RESIDUAL PROCESSES - HARD STOP, do not kill by name'; $left | Format-List }
```
- Expected: `no process references C:\c3`.
- A residual is a containment failure. Do not run a name or time sweep. Report the exact PID, parent and command line
  to the owner. Any termination is one exact-PID decision by the owner, after review, and is recorded.

**(b) Archive the evidence before deleting anything.** The spec says to keep the folder as the record's evidence, and
the owner asked for `C:\c3` to be removed, so archive first, then remove.

The archive location is master-agent's state folder, not the repo and not `data\`. First scan for links without
following any (expected: nothing):
```powershell
$root = 'C:\c3'
if ((Get-Item -LiteralPath $root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'C:\c3 itself is a reparse point: stop, remove the link only with cmd /c rmdir' }
$links = New-Object System.Collections.ArrayList
$stack = New-Object System.Collections.Stack
$stack.Push($root)
while ($stack.Count -gt 0) {
    $dir = $stack.Pop()
    foreach ($e in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)) {
        if ($e.Attributes -band [IO.FileAttributes]::ReparsePoint) { [void]$links.Add($e.FullName) } elseif ($e.PSIsContainer) { $stack.Push($e.FullName) }
    }
}
'reparse points: ' + $links.Count; $links
```
If `$links.Count` is 0:
```powershell
$zip = 'C:\tmp\agent-kit\c3-evidence-20261008.zip'
if (Test-Path -LiteralPath $zip) { throw "archive exists: $zip" }
Compress-Archive -LiteralPath 'C:\c3\20261008','C:\c3\C3-COMMANDS-20261008.txt' -DestinationPath $zip
(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
```
Put the archive hash and `launch-ledger.txt`'s hash in the record PR.
- **After a HARD STOP**, stop here: keep `C:\c3` in place until the review, then do (c).

**(c) Remove `C:\c3`, junctions first.** Never recurse through a junction.
```powershell
foreach ($l in $links) {
    if ((Get-Item -LiteralPath $l -Force).PSIsContainer) { cmd /c rmdir "$l" } else { cmd /c del /a "$l" }
}
```
Then re-run the scan block from (b). It must print `reparse points: 0`. Then:
```powershell
Remove-Item -LiteralPath 'C:\c3' -Recurse -Force
Test-Path -LiteralPath 'C:\c3'
```
Expected: `False`.

**(d) Final checks.**
- Re-run (a).
- `git -C C:\Users\micha\Desktop\github\weather --no-optional-locks status --short` prints nothing.
- Record `(Get-Volume -DriveLetter C).SizeRemaining`.
- The PSReadLine history in `%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt` holds only the
  typed commands, with no secrets. Leave it.

## 7. Readiness

**READY (workstation side) for 2026-10-08 09:00, as of 2026-10-07 about 13:30.** Status of the original items:

1. **F1: DONE.**
   - Spec step 3 uses `<venv>\Lib\site-packages`, plus the S1 reparse check.
   - `c3_break.py` and `c3_ctrlc.py run` reset the venv prefix before the first `import sysconfig`.
   - Repro and fix are shown in section 2.3. F2 was re-extracted.
2. **Defender delta review: DONE.**
   - F1/F2/V31-R1: CLEARED-AFTER-FIXES. The MUST-FIX (a dry pass through `c3_run.ps1`) is met; S1 and N1 are applied.
   - F3/F4: CLEARED-AFTER-FIXES. MUST-FIX 1 (6b last, plus the `consoleStale` rule) is applied, and so is S-F3a.
   - S2 (c3_run evidence hardening) and S-F3b (tighter stale binding) were not applied. Both are optional.
3. **Owner Q7: PENDING.**
   - The dry pass did not run P8 item 6 or the standalone self-test.
   - It did run `c3-run-v3.1-F3` live through 12 + 14 + 10 calls, with every safety field correct.
   - The owner must still authorize the single workstation guard self-test, or accept the host's P8 item 6 (the first
     two calls on the host) as that self-test.
4. **Workstation dry pass: DONE, PASS** (`C3-DRYPASS-20261007.md`).
   - Covered: P8 items 2-5 and 7, steps 2-6, 7.0, 8c and 8d (6b), and 9.
   - Skipped (no simulated keypresses): steps 7.1, 8a and 8b.
   - Not run: P8 item 6 (Q7).
   - Python 3.11.9 on the workstation. On the host, k is taken from `p8-guard-1` as the spec says.
5. **Owner Q2 (and Q1): PENDING.** They are required for step 8 to count in the record. P5 is clear: the host has no
   `WEATHER_*` variable in any scope (section 3.5).
6. **Staging on the host (master-agent).**
   - Place the six files from `c3-launch-20261008\v3.1-F3-host\` in `C:\c3\20261008`, and verify the six SHA-256
     values in section 2.3 / the section 4 `$expect` block.
   - Write `C:\c3\C3-COMMANDS-20261008.txt` from section 4. Its hashes are already filled in: three files changed
     against the reviewed v3.1 (`c3_run.ps1` F3, `c3_break.py` F1, `c3_ctrlc.py` F1), and one copy was corrected
     (`c3_prompt_launcher.ps1` F2).
   - Run the env-name pre-check.
7. **Morning gates (3.2-3.6, as updated by master-agent).** These must hold at 08:55:
   - the 91a re-pin is done, and no 91a or dry-run process is alive;
   - the B replay has ended (by 06:40 at the latest), and N2 is terminal;
   - Stage B is disabled;
   - no lease is held;
   - the tree is clean, with tier A unchanged;
   - there has been no reseal;
   - **explicit owner/master acceptance of the post-landing-night deviation (3.6): PENDING.**

   The "91a still running at 09:05 → no-go" rule applies only to the 10-09 fallback.

**On the host, expect** `consoleStale=[close:<pid>]` on the s6b line only (the last call), and `[]` on every other
line. The step-9 filter enforces this.

**Fallback.** If any owner item or gate fails at 08:55, the next slot is **10-09 09:00-09:30**, with the same packet.
