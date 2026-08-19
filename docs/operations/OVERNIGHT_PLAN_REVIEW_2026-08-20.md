# INDEPENDENT READ-ONLY REVIEW — August 20 overnight plan
**Audit window:** 2026-08-19 12:23 → 13:0x America/Toronto (inside the protected graded window; read-only throughout)
**Baseline confirmed:** `git status --short --branch` → `## master...origin/master`, only `config/location_market_events.json` and `config/locations.json` modified.

---

## 1. Executive verdict

# **CONDITIONALLY_PROTECTED**

The plan is the most disciplined orchestration I have seen in this repository. **All 32 hash bindings I recomputed matched exactly** (19 named in the brief plus 13 further cross-checks). Every new task exists, is S4U/`IgnoreNew`, has an exact `NextRunTime`, a hash-bound action that correctly propagates `$LASTEXITCODE`, an immutable-receipt guard, a sealed start window, a kill-on-close Job, and a fail-closed downstream contract. The active-hours topology is provably gap-free. Capture is healthy and the roll verdict is independently reproducible.

It is **not** NIGHT_PROTECTED for three reasons, one of which is a defect in the PASS audit itself:

1. **The schedule audit certified guards that are not deployed.** `audit.ps1:108` validates the tiering wrappers' containment by reading the **git blob at the un-merged cumulative tip**, not the file that will actually execute at 05:00 and 06:00. The deployed scripts have **no `MaxRuntimeSeconds`, no `New-WeatherKillOnCloseJob`, no `HARD_STOPPED`** — and Task Scheduler limits of **PT1H30M and PT3H**, not the 30/40-minute "hard ends" the audit table asserts. If the merge fails, this is an uncontained job in the morning window.
2. **The Codex CLI is a single point of failure for the entire night, including the August 17 settlement hole.** Smoke → focused → suite → merge → {continuity, backfill, tiering retries, candidate, Stage-A headroom, closeout}. A settlement recovery that needs no agent at all is gated behind an LLM CLI returning one token at 00:43.
3. **Reboot protection now rests entirely on Active Hours**, and nothing after 00:27 re-checks it.

None of these is a reason to cancel the night. All three are reasons to state the failure modes plainly before the operator logs off.

---

## 2. Top findings, ordered

### P0 — none
No finding will *certainly* waste the night. The structure is fail-closed everywhere I probed.

### P1-a — The PASS audit verified the wrong file for the two recurring tiering tasks
`audit.ps1:66-83` (`Get-GitBlobSha256` / `Get-GitBlobText`) resolves blobs at `$exactTip = dc93479b…`, **not** the working tree. Consequences:

| Field | Value in receipt | What it actually means |
| --- | --- | --- |
| `internal_time_load_absolute_guard` for `WeatherClobTiering` / `…RawTapeTiering` | `true` | The **tip's** script has the guards. |
| `wrapper.current_matches_expected` | **`false`** for both | The **deployed** script differs from the tip — and this field is recorded and **never checked** (`audit.ps1:103-105,111-123`). |

Verified directly against the deployed files:

```
scripts/ops/clob_tiering_run.ps1          deployed: MaxRuntimeSeconds=0  Job=0  HARD_STOPPED=0   (tip: 3/1/1)
scripts/ops/clob_raw_tape_tiering_run.ps1 deployed: MaxRuntimeSeconds=0  Job=0  HARD_STOPPED=0   (tip: 3/1/1)
```

`clob_raw_tape_tiering_run.ps1:94-103` is `Start-Process -PassThru` then a bare `$proc.WaitForExit()` — no timeout, no Job. `ExecutionTimeLimit` is **PT3H**. So on a merge failure, a 06:00 raw-tape run can hold `data/logs/heavy_workload.lock` until 09:00, and — per `ESTABLISHED_FINDINGS §8d` — **killing the wrapper does not kill its child**, while the lease handle closes and frees the lease *underneath a still-running job*. That collides with the 06:41 retry, 06:50 economics, 07:05 MM roll, 07:40 candidate, and potentially 09:30 Stage A.

**The audit's `exclusive_intervals` table asserts a 40-minute hard end for that task that nothing enforces.**

### P1-b — The whole night is serially gated on one Codex authentication at 00:43
`live-cumulative-focused-0820/run.ps1:177-235` requires the smoke receipt with `codex_exit_code -eq 0` and the exact final message. `full-suite:118-136` requires the focused receipt. `gated-merge:117-130` requires the suite receipt. `settlement-backfill-0817-0820/run.ps1:172-186` requires `git.ok` **and** the merge receipt.

Net: **if `codex.exe` cannot authenticate at 00:43, August 17 stays a 0/12 hole** — a task that needs no agent, no network, and no LLM. That is the single highest-value thing on the schedule and it is downstream of the most fragile dependency on it.

### P1-c — `WeatherOneShotPush` is an Interactive-logon task; sign-out silently forfeits the night
```
WeatherOneShotPush  LogonType: Interactive  RunLevel: Limited  UserId: micha
quser →  micha   ID 2   Disc   idle 5+15:17   logon 2026-08-08 18:17
```
The current **Disconnected** session is correct and the task ran clean at 10:09 today (`0x0`). If the operator **signs out** rather than locking/disconnecting: `quiet_window_merge.ps1:335-350` starts the task, polls `origin/master` for 3 minutes, then takes the `merged_unpushed` branch and `exit 3`. The gated-merge wrapper (`run.ps1:205-212`) then throws `"authoritative quiet-merge result does not prove this exact pushed run"`, writes only `failure-<ts>.json`, and **every downstream task refuses**.

The dangerous asymmetry: **the roll-sensitive merge is already committed locally and capture has already rolled onto the new code.** Production would spend the day on unpublished code with no PASS receipt anywhere.

### P1-d — Reboot protection is now single-layer, and nothing re-checks it after 00:27
```
ActiveHoursStart = 11 (DWord), ActiveHoursEnd = 5 (DWord)   ← only two values present
HKLM\...\Policies\...\WindowsUpdate\AU   → EMPTY (no AUOptions, no NoAutoRebootWithLoggedOnUsers)
WindowsUpdate RebootRequired = True ; CBS RebootPending = True ; PendingFileRenameOperations = True
```
`ESTABLISHED_FINDINGS §8i` records the deliberate 2026-08-14 removal of the temporary block. Correct then; it means **Active Hours is the only thing standing between three pending-reboot indicators and a restart**. If *both* 00:20 and 00:22 fail, the registry stays `11→5`, leaving **05:00–11:00 unprotected** across tiering, economics, MM roll, candidate, closeout, Stage-A headroom and the first 90 minutes of Stage A. No later task reads the registry. Also unverified: neither `IsActiveHoursEnabled` nor `SmartActiveHoursState` exists, so nothing on this host *proves* Windows 11 is honouring the manual values rather than smart active hours.

### P2-a — The recovery agent runs `--sandbox danger-full-access`
`live-overnight-audits-0820/invoke-agent.ps1:47`:
```
"exec","--ephemeral","--sandbox","danger-full-access","--color","never","-C",$repo,"-o",$LastMessagePath,"-"
```
Same for the morning closeout (`live-morning-closeout-0820/invoke-agent.ps1:20`). The narrow scope in the brief — "repair only host-local roll-free orchestration; may not edit the frozen tip, weaken gates, access credentials, or trade" — is enforced **only by prompt prose plus a postcondition check after the fact**. The hash-sealed prompt does not constrain actions. Q10's answer is: the *authority* is right, the *sandboxing is not consistent with it*.

### P2-b — The candidate's RAM gate has ~0.74 GiB of margin right now
`worker.ps1:472`: `ram_free_gb -lt 4.0 -or commit_percent -ge 64.0 → throw`. Measured now: **4,854 MB free physical (4.74 GiB), commit 55.4%**. There is **no snapshot restart between 00:42 and 07:40**, and `ESTABLISHED_FINDINGS §8r` documents the snapshot parent reaching 5,864 MiB private over ~2,866 iterations. A plausible overnight drift of <1 GiB fails the 07:40 candidate on resources alone.

### P2-c — `WeatherTrainingWindowRestore` (04:15–04:30) overlaps the backfill without the lease
`audit.ps1:130-138` computes overlap **only among `category='exclusive'` specs**; `light` specs are listed under `allowed_light_overlaps` and never tested. `training_window.ps1:126-131` takes the `-RestoreOnly` branch and calls `Restore-Capture`, which issues `schtasks /change /enable` for three tasks plus three `ensure` verbs — and **`Enter-WeatherHeavyWorkloadLease` is at line 189, after that branch**. So it runs un-leased inside `WeatherSettlementBackfill20260817_0820` (03:55–04:40). Idempotent in the normal case, but the overlap was *assumed* safe, not checked.

### P2-d — A tiering retry PASS proves execution, not reclamation
`tiering-retries-0820/run.ps1:111` requires a current-day durable `OK` plus `max_runtime_seconds` binding. It records **no before/after free-space delta**. `RETRY_COMPLETED` is therefore an eligibility claim. Given this project's stated dominant defect shape (31 retractions vs one shipped win, "we measure eligibility, never outcome"), that gap should be closed before any disk claim is written from these receipts.

### P3 findings
- `audit.ps1:86` computes `$git.ok` and **never adds it to `$errors`**. The PASS receipt therefore carries `git.ok: false`, `exact_tip_ancestor: false` — correct pre-merge, but a reader could reasonably mis-grade it.
- Suite terminal-verdict regex `VERDICT: ALL CHUNKS PASSED \(\d+/\d+\)` accepts **any** chunk count. A degenerate 1/1 run would satisfy it.
- The audit hard-codes `[int]$exit_code -eq 0` for tiering durable status, but the live status files carry **no `exit_code` field** (`{schema_version,status,written_at_utc,local_time}`) → `[int]$null = 0` → the check is vacuous on that shape. Harmless today because `status -eq 'OK'` carries the decision.

---

## 3. Current evidence snapshot

**Git**
```
HEAD = origin/master = a76ec7b5599d499011054f98e43564ad0563a58f          (verified)
dc93479b2d6f0e2e3d16b8a30451068b9eb71d46 exists; is NOT an ancestor of master (correct pre-merge)
0df52a9c…(successor)  ancestor of dc93479b : YES
6be4dc07…(hardening)  ancestor of dc93479b : YES
a76ec7b5…(production) ancestor of dc93479b : YES
1f4fb146 / 3c326ac1 in master : YES / YES
worktree C:\Users\micha\Desktop\github\weather-overnight-hardening-0819 @ dc93479b — CLEAN
```
Tip changes **45 files**: 17 `src/weather/*.py`, 6 `scripts/ops/*.ps1`, 5 new test files, docs/roadmap.

**Roll verdict — independently re-derived from the live closures (not from `roll_verdict.ps1`, which I did not execute):**

| Closure | files | tip-changed modules present |
| --- | ---: | --- |
| snapshot | 79 | `long_job_guard.py`, `schema_registry_data.py`, `schema_registry_recent_data.py` |
| clob | 23 | `schema_registry_data.py`, `schema_registry_recent_data.py` |
| observation | 84 | `long_job_guard.py`, `schema_registry_data.py`, `schema_registry_recent_data.py` |
| clob_enrichment | 21 | `schema_registry_data.py`, `schema_registry_recent_data.py` |

**ROLL-SENSITIVE confirmed.** 01:25–02:00 is inside the mandated 01:00–04:00 window.

**Capture — healthy**
```
loop_supervisor_status              RUNNING  pid 10084  fp 199dc1d73ba4897c  updated 16:34:11Z
clob_loop_supervisor_status         RUNNING  pid 16996  fp 53deeaab4985ed02  updated 16:35:11Z
observation_trigger_supervisor_st.  RUNNING  pid  3108  fp 63439e1efc766cab  updated 16:35:11Z
execution_tape_status               CONNECTED  pid 8704  evidence_integrity PASS
   identity_integrity = BLOCKED_UNIQUE_EXECUTION_COUNTS ; price_path_evidence_usable = false
execution_tape_supervisor_status    state = DEGRADED  (ensure_status OK, action noop)
```
All three supervisors record `git_commit 3c326ac1c03b` — expected; the a76ec7b5 delta is docs-only and the fingerprint is content-based (`DELEGATION_CONTRACT §3`).

**The stale-lock artifacts (do not touch)**
```
data/backtest/daily_refresh.lock        {"created_at_utc":"2026-08-19T13:30:14.658649+00:00","pid":20668}
data/backtest/long_job_guard.lock       {"job_name":"daily_refresh","pid":20668,"started_at_utc":"…13:30:14.661687+00:00"}
data/backtest/long_job_guard_status.json  active:true status:running pid:20668 last_progress 15:04:10Z (11:04 local)
data/backtest/daily_refresh_status.json   status:"interrupted" terminal:true owner_pid:20668
     interruption: {step: closed_day_parquet_incremental, child_pid: 13540,
                    fallback_persisted_before_child: TRUE, status: RESUMABLE}
PID 20668 ABSENT · 13540 ABSENT · 21216 ABSENT · 8712 ABSENT · 3212 ABSENT
```
**Correction to the brief's framing:** the 11:04 timestamp is *not* the last heartbeat before death. `fallback_persisted_before_child: true` means the orchestrator wrote its terminal-safe resume receipt at 11:04:10 **before resuming the isolated child**, exactly as `HOST_LOAD_POLICY` specifies. The chain completed **15 of 25 steps**, all `ok`, through `replay_status_backfill` (14:41:08→15:04:10Z), then ran `closed_day_parquet_incremental` in child 13540 from 11:04 until the **11:55** teardown. `lock_proof.status = PASS`, `stale_lock_count = 0` — the run acquired both locks cleanly; it simply never released them.

**Root cause of the leak, exactly:** `scripts/ops/daily_refresh.ps1:143-147`. The `finally` block disposes the Job, disposes the child, and exits the lease. **It does not remove either lock file.** `long_job_guard.py:1889-1910` releases the lock in a Python `finally` that `TerminateProcess` never runs. Exit `75` is `daily_refresh.ps1:135` — `0x4B` matches.

**Disk (measured from `data/alerts/disk_free_trail.jsonl`, 399 samples)**
```
free now 165.1 GB
  8h : −7.80 GB/day     24h : −23.00 GB/day     48h : −14.60 GB/day     72h : −9.23 GB/day
midnight-to-midnight net: 08-16 −15.8 · 08-17 −2.3 · 08-18 −7.9 · 08-19 −0.2 (partial)
```
STATE_OF_PLAY's "both adverse" is correct. Note a **+10.2 GB step at 10:50** — per `ESTABLISHED_FINDINGS §8d/§8p`, discrete reclaims and pagefile/commit swings contaminate short windows, so treat −23.0 GB/day as an upper bound, not a rate.

**Memory:** 4,854 MB free physical of 16,125 MB; commit 17.61 / 31.78 GB = **55.4%**.

**Settlement — independently verified row-by-row across all 12 market ledgers**

| Date | Result |
| --- | --- |
| 2026-08-15 | **12/12** real `daily_summary` |
| 2026-08-16 | **12/12** real `daily_summary` |
| **2026-08-17** | **0/12** — every market `settlement_source: none`, `settlement_high: null` |
| 2026-08-18 | **12/12** real `daily_summary` |

The 08-17 failure artifact is preserved and its hash matches the seal:
```
data/alerts/settlement_backfill_2026-08-17.json  SHA-256 6F60B25F…F5CF2E   ✓
  state "REFUSED" · "daily_refresh.lock is held; another chain run is in flight" · at 2026-08-19T06:15:01
```
That is `scripts/ops/settlement_backfill_one.ps1:69-75` — a bare `Test-Path` on the lock, refusing against the **03:05 run's** stale metadata. The same class of failure that produced today's artifacts.

**Precedent already on disk:** `C:\Users\micha\ops\stale-lock-recovery-0819\receipt.json` records a *manual* agent repair at **08:46** today, preserving the 03:05 locks (`pid 3212`) and noting that PID `3212` had been reused by `node_repl.exe`. **This is the second stale-lock leak in one day.**

**Protected task states:** `WeatherEveningEvidenceRefresh` Disabled · `WeatherDataMirror` Disabled · `WeatherTrainingWindow` Disabled · `WeatherTrainingWindowRestore` Ready. ✓ Unchanged by me.

**Documentation transaction:** `documentation_transaction_latest.json` → `status PASS`, `documentation_tip a76ec7b5…`, `pending_sha256 0EC77703…`, immutable receipt at `receipt-a76ec7b5599d-0EC77703D605.json` (10:10 local). The lingering `documentation_transaction_pending.json` is **by design** — `transaction_status()` resolves to **COMPLETE** because the latest receipt covers that exact pending hash.

---

## 4. Dependency graph, 00:20 → 11:58

| Time | Task | Prerequisite | Authoritative success artifact | Hard end (enforced by) | Failure propagates to |
| --- | --- | --- | --- | --- | --- |
| 00:20 / 00:22 | ActiveHoursMorningProtect (+dead-man) | date+time seal 00:18–00:24 | `morning-protect-latest.json` PASS, registry `23→17` | 00:25/00:27 (PT5M) | **nothing** — no later task re-checks |
| 00:30 | SnapshotHeadroom0820 `-Mode midnight` | `1f4fb146` ancestor of HEAD; head==origin. **Merge receipt NOT required** (`run.ps1:80`) | `midnight/receipt.json` | 00:42 (internal + PT12M) | nothing — correctly isolated |
| 00:43 | CodexOvernightSmoke0820 | 4 component hashes; real `runner.ps1 -ValidateOnly`; 3 supervisors; lease free; merge-task binding | `smoke/receipt.json` PASS | 00:47 (internal + PT4M) | **focused → suite → merge → everything** |
| 00:50 | LiveCumulativeFocused0820 | smoke receipt PASS + `LastRunTime.Date == today` | `receipt.json` (349 passed / 15 subtests, stdout+stderr SHA) | 00:55 (internal + PT5M) | suite → merge → all |
| 00:56 | LiveCumulativeFullSuite0820 | focused receipt + artifact re-hash + tip unchanged | `receipt.json` + `…full-suite-0820.log` SHA | 01:21 (poll+Job **and** PT25M) | merge → all |
| 01:25 | LiveCumulativeSuiteGatedMerge0820 | suite task `LastTaskResult 0` today, receipt PASS, log hash, tip unchanged, 4 repo-script hashes | `receipt.json` `live_cumulative_gated_merge_receipt_v0.1` stage=`pushed` | 02:00 (poll+Job + PT35M) | **continuity, backfill, tiering retries, candidate, StageA headroom, closeout** |
| 02:05 | ExecutionTapeContinuity0820 | merge receipt; `-RequiredAncestor dc93479b` | `receipt.json` + probe `execution_tape_continuous_observation_v0.1` | 02:23 (poll+Job + PT18M) | candidate |
| 02:25 | CodexOvernightRecovery0225_0820 | manifest READY + runner hash; self-disarms first | `receipts/recovery-<stamp>.json` + `recovery.latest.json` | 03:50 (internal + PT1H25M) | candidate |
| 03:55 | SettlementBackfill20260817_0820 | `git.ok` (tip ancestor + head==origin), merge receipt valid & == HEAD, deployed script has bounded-finalize/registry/daily_summary markers | `receipt.json` `AUTHORITATIVE_DAILY_SUMMARY_BACKFILL_PROVED` | 04:40 (poll+Job + PT45M) | candidate |
| 04:15 | TrainingWindowRestore | none | `training_window.log` `[RESTORE]` | 04:30 (PT15M) | none — but **overlaps backfill un-leased** |
| 05:00 | ClobTiering (recurring) | none | `data/logs/clob_tiering_task_status.json` | **PT1H30M only — no internal bound deployed** | can starve 05:31 retry |
| 05:31 | ClobTieringRetry0820 | merge receipt + hardened deployed script | `clob-tiering-retry-0820/receipt.json` | 05:58 (internal + PT27M) | none |
| 06:00 | ClobRawTapeTiering (recurring) | none | `clob_raw_tape_tiering_task_status.json` | **PT3H only — no internal bound deployed** | **can starve 06:41 / 06:50 / 07:05 / 07:40** |
| 06:41 | ClobRawTapeTieringRetry0820 | merge receipt + hardened deployed script | receipt | 06:47 (internal + PT6M) | none |
| 06:50 | ExchangeEconomicsSnapshotRefresh | none | `data/backtest/exchange_economics_snapshot.json` v0.3 | PT10M | candidate |
| 07:05 | MarketMakingDailyRoll | none | run folder | PT30M | none |
| 07:40 | LiveTestCandidatePaper0820 | **8** receipts: focused, full_suite, gated_merge, continuity, backfill, recovery(latest), 08-16 historical, economics + ≥4 GiB RAM + commit<64% + lease | `receipt.json` | 08:05 (PT25M) | none |
| 08:10 / 08:15 | StalenessSweep / MmCountability | none | reports | PT15M / PT20M | none |
| 08:36 | CodexMorningCloseout0836_0820 | head==origin before & after, capture ok, merge receipt valid, integration ancestor of post-doc HEAD, docs txn COMPLETE | `receipt.json` | 09:00 (PT24M) | — |
| 09:05 | SnapshotStageAHeadroom0820 | `dc93479b` ancestor + merge receipt == HEAD | `stagea/receipt.json` | 09:25 (internal + PT20M) | Stage A runs without headroom proof |
| 09:30 | DailySettlementPromotionRefresh | **none of the above** | `daily_refresh_status.json` | 11:55 (wrapper `$localMinute -ge 715`) | tomorrow |
| 11:56 / 11:58 | ActiveHoursRestore (+dead-man) | seal 11:55–11:59 | `restore-latest.json` PASS, registry `11→5` | 12:01 / 12:03 | graded window unprotected 17:00–18:00 |

**Critical structural observation:** the 09:30 Stage-A chain is the **only** node with no dependency on the merge chain. That is correct and deliberate — settlement continuity survives a total overnight failure.

---

## 5. Per-task audit (deltas from the plan's own claims only)

All 26 tasks: `exists=true`, `state` Ready (Stage A was `Running` at audit time), `ok=true`, `S4U`, `IgnoreNew`, `next_run_exact` ✓, `normal_receipt_absent` ✓, wrapper hash bound into the action ✓.

| Task | Deviation found |
| --- | --- |
| `WeatherClobTiering` | ETL **PT1H30M** vs asserted 30-min hard end; deployed script `current_matches_expected=false`; guard check read the tip. `SWA=True, Wake=False`. |
| `WeatherClobRawTapeTiering` | ETL **PT3H** vs asserted 40-min hard end; same three problems. `SWA=True, Wake=False`. |
| `WeatherTrainingWindowRestore` | `SWA=True, Wake=True`; excluded from the overlap test by category; `-RestoreOnly` takes no lease. |
| `WeatherDailySettlementPromotionRefresh` | ETL **PT4H** (09:30→13:30); only the wrapper's internal 11:55 guard prevents crossing into the graded window. Proven today (exit `0x4B` at 11:55). `SWA=True`. |
| `WeatherSnapshotHeadroom0820` | `-ExpectedTip 1f4fb146…` (parent) while the Stage-A twin uses `dc93479b…`. **Deliberate and correct** — the midnight gate validates the *currently integrated* parent. |
| `WeatherExchangeEconomics…`, `StalenessSweep`, `MmCountability`, `MarketMakingDailyRoll` | `SWA=True` (warned, not gated). |
| All 18 new 0820 tasks | `SWA=False`, `WakeToRun=True` — cannot catch up late. ✓ |

**Exit-code semantics (Q9), verified from the registered XML:** every `-Command` action ends `$code = [int]$LASTEXITCODE; if ($code -ne 0) { exit $code }; exit 0|$code`, and every `-File` action targets a wrapper whose last statements are explicit `exit 0` / `exit 1`. `runner.ps1` self-disarms via `Disable-ScheduledTask` **before** the work (line 192) and still ends `exit 1` on FAIL (lines 303, 396-398). **I found no path that shows `0x0` on FAIL.**

---

## 6. Repository / code review

**Locks.** Production `daily_refresh_locks.acquire_lock` (lines 296-341) already self-heals: on `FileExistsError` it calls `_remove_lock_if_verified_stale`, which marks `stale` only when `process_is_running(pid)` is **False**, then unlinks and re-opens `O_CREAT|O_EXCL`. `long_job_guard.acquire_long_job_lock` (236-280) does the same via `_lock_owner_is_active`. **PID 20668 is dead, so tomorrow's 09:30 Stage A will repair both locks by itself.** The residual hazard is exactly the one `RETRACTED_AND_FALSE_LEADS` recorded today: PID reuse. `_lock_owner_is_active` is PID-only; the tip's `process_lock_identity.py` adds creation-token/image identity.

**Bounded refresh.** The tip adds `daily_refresh_bounded.py` and `--stop-after-step`. `chain_recovery_run.ps1` at the tip (453 lines vs 124 deployed) refuses outside 00:30–09:00, sets `hardStopLocal = today 09:00`, runs `repair-stale-locks` **before** the chain, refuses on a live/unreadable owner, runs with `--stop-after-step`, then post-run cleanup with `lock_release_verified` and `post_lock_cleanup_status`. **This is the correct fix and it is the only thing that clears today's artifacts automatically.**

**Settlement.** The tip's `settlement_backfill_one.ps1` deletes the bare `Test-Path` guard entirely and replaces Guard 2 with authoritative `market_registry` discovery — proving the module resolves from *this* checkout and that a missing directory becomes an explicit `missing_ledger_markets` failure rather than shrinking the denominator. `Test-RowSettled` rejects `''/none/null` sources and null highs. This directly closes the `settlement_source: none` trap.

**Tiering.** Tip adds `MaxRuntimeSeconds`, Job containment, `HARD_STOPPED`, atomic latest + append-only history. **Not deployed** (P1-a).

**Status.** `status.ps1` is **not read-only** — line 287 `Set-Content -Path $trail …` writes `data/alerts/disk_free_trail.jsonl`. I therefore did **not** run it, per the contract. *(Recommend the brief's step 3 be reworded; as written it would have mutated state.)*

**Stage 2 / candidate.** `worker.ps1:483-495` runs `market_making_run --mode paper-live-forward --permission-profile market_harvest --budget-usdc 25 --evidence-mode operator_drill --once` and asserts `max_daily_loss=25`, `max_event_notional=25`, `max_band_notional=10`, `quote_ttl_seconds=120`, `live_trade_permission=false`, `two_sided_post_only_intent=true`, `selection_is_trading_authorization=false`. It uses a **copy** of the economics snapshot and asserts `production_economics_unchanged`. It also proves every imported module resolves inside the production root. No credential path, no live mutation.

**Documentation transaction.** `documentation_transaction.begin` (lines 162-181) sees state COMPLETE and starts a **fresh** pending containing only tonight's integration — so the gated-merge check (`status PENDING`, `latest_integration_tip == integrationTip`, exactly one matching `{branch, expected_tip, integration_tip}`) will pass. `complete` requires `documentation_tip == HEAD == origin/master` and every integration tip to be an ancestor — which means **the morning agent must also push**, a second dependency on the Interactive push task.

---

## 7. Receipt / schema compatibility matrix

| Producer | Schema emitted | Consumers | Fields each consumer requires | Compatible? |
| --- | --- | --- | --- | --- |
| smoke | `weather_codex_overnight_smoke_v0.1` | focused | `status`, `manifest_sha256`, `canonical_capture_ok`, `codex_exit_code`, `static_preflight_sha256` | ✓ all present |
| focused | `live_cumulative_focused_receipt_v0.1` | full suite, candidate | `schema_version,status,expected_tip,observed_tip,workload_lease_acquired,expected_test_count,commands[].{exit_code,hard_stop_reached},stdout/stderr{path,sha256}` | ✓ |
| full suite | `live_cumulative_full_suite_receipt_v0.1` | merge, candidate | `+ suite_exit_code, suite_log_sha256, observed_branch_tip, live_mutation_attempted, credential_value_read` | ✓ |
| gated merge | **`live_cumulative_gated_merge_receipt_v0.1`** | **6 consumers** | see below | ✓ **verified field-by-field** |
| quiet merge | `data/alerts/quiet_window_merge_last.json` | gated merge | `ok, stage, branch, expected_tip, resolved_branch_tip, ts` | ✓ all emitted by `Save-Report` |
| continuity | `execution_tape_continuity_0820_receipt_v0.1` | candidate | `status`, nested `probe.*` | ✓ |
| probe | `execution_tape_continuous_observation_v0.1` | continuity, candidate | `producer_mode, ok, stage, required_ancestor, duration_seconds, existing_producer_unchanged, new_trade_observations, new_gap_count, baseline_pid, final_pid, baseline/final_session_id, capture_workers_before/after` | ✓ |
| recovery | `live_overnight_recovery_receipt_v0.1` + `…latest_v0.1` | candidate | `status, classification, receipt_sha256` | ✓ |
| backfill | `settlement_backfill_0817_0820_receipt_v0.1` | candidate | `status`, `backfill_result.*` | ✓ |
| tiering retry | `tiering_retry_0820_receipt_v0.1` | none | — | ✓ |
| closeout | `weather_codex_morning_closeout_v0.1` | operator | — | ✓ |

**The single merge receipt against all six readers** — every required top-level field is emitted at `gated-merge/run.ps1:258-297`:

| Reader | Required | Emitted |
| --- | --- | --- |
| continuity `:118-133` | `schema_version, status, ok, stage, source_tip, integration_tip, production_head, origin_master, quiet_merge_receipt_sha256, capture_recovery_proved, origin_master_verified` | ✓ all 11 |
| backfill `:91-107` | same 11 | ✓ |
| tiering retry `:81` | 10 of 11 (no quiet hash) | ✓ |
| snapshot headroom `:83` | 10 of 11 | ✓ |
| candidate | via shared helper, same set | ✓ |
| closeout `:54-71` | adds `original_failed_receipt.{path,sha256}`, `suite.{planned_task_name,planned_log_path,log_sha256}`, `documentation_transaction_recorded`, `credential_value_read` | ✓ all emitted |
| recovery preflight `:307-330` | adds `live_mutation_attempted_by_correction_wrapper` | ✓ emitted |

**No schema drift found.** This is the strongest part of the design.

---

## 8. Git / integration analysis

- Merge path: `suite_gated_quiet_merge.ps1` → `quiet_window_merge.ps1`. All four repo scripts the merge wrapper hash-asserts match on disk: `DD130207…`, `118952F7…`, `9FA1FD83…`, `89221B11…`. ✓
- **Generated drift is handled correctly.** `quiet_window_merge.ps1:138-139` names `config/locations.json` and `config/location_market_events.json` explicitly and commits them **before** taking the rollback point (`:182`), so a rollback cannot discard fleet-generated state.
- `:170-171` refuses unless local master == origin/master before merging. ✓
- `:197` acquires the heavy lease; `:202` runs `capture_recovery_check`; `:282-305` rolls back and waits up to `RollbackRecoverySeconds` (default 1200) for all three workers to re-adopt, failing to `rollback_recovery_failed` (exit 4) if not.
- `:316-330` records the documentation transaction **before** publication; `:335` publishes only via `Start-ScheduledTask -TaskName WeatherOneShotPush`; `:344` verifies `origin/master`.
- **Caveat worth stating:** `git rev-parse origin/master` reads the *local remote-tracking ref*, which `git push` updates on success. It is valid push evidence but not an independent remote read. Given the no-fetch constraint that is the right trade-off; it should just not be described as remote verification.
- Post-doc ancestry: closeout `:185-186` requires `merge-base --is-ancestor <integration_tip> <production_head_after>`, and `documentation_transaction` itself requires `documentation_tip == HEAD == origin` plus ancestry for every pending tip. **A documentation commit changing HEAD after integration is explicitly modelled.** ✓
- **Timing risk:** the 1200 s rollback-recovery wait plus `-SettleSeconds 300` can theoretically exceed the 02:00 Job teardown. The rollback `git reset` itself happens first, so a teardown mid-wait leaves the tree at pre-merge with workers re-adopting on their own — degraded, not corrupt.

---

## 9. Resource and timing analysis

**Permitted overlap:** none among exclusive intervals — minimum inter-task gap **1 minute** (00:42→00:43, 05:30→05:31, 06:40→06:41). The lease serializes anything that slips.

**Forbidden / unmodelled overlap:**
1. `WeatherTrainingWindowRestore` 04:15–04:30 ⊂ backfill 03:55–04:40, **un-leased** (P2-c).
2. `WeatherClobRawTapeTiering` with PT3H and no internal bound can extend to 09:00 and hold the lease across four later tasks (P1-a).
3. `WeatherActiveHoursRestoreDeadman0820` runs 11:58–12:03, i.e. 3 minutes into the graded window. Registry write only; negligible.

**Catch-up:** the 8 `StartWhenAvailable=True` tasks are all pre-existing recurring jobs. The lease bounds their damage, except for the two tiering tasks whose children escape the lease's lifetime.

**Measured feasibility of the tight gates:**
- Full suite in 25 min: prior exact-tip suites took **8–9 minutes** (§8l, §8n, §8o). Comfortable even with 5 new test files.
- Continuity needs `new_trade_observations ≥ 1` in 780 s at 02:05. I counted the fleet execution tape for 2026-08-19: **local hour 02 = 277 trade rows** (≈4.6/min). Risk is low and now measured rather than assumed. `new_gap_count == 0` over 13 minutes is the thinner of the two conditions.
- Midnight headroom must observe an **advancing Toronto snapshot** between ~00:31 and 00:42 on a 10-minute loop — worst case ~1 minute of slack. It fails safe and blocks nothing.
- Candidate RAM gate: 0.74 GiB of margin today (P2-b).

---

## 10. Assumptions challenged / unsupported claims found

| Claim | Status |
| --- | --- |
| "Final schedule audit PASS" | **True but narrower than it reads.** Zero errors, but `git.ok=false` is unchecked, `current_matches_expected=false` is unchecked, light-category overlap is untested, and the two recurring tiering ETLs are exempted from the `execution_limit` check by an empty spec value. |
| "Tiering internal bounds enforce 05:30 / 06:40" | **FALSE for the deployed code.** True only at the un-merged tip. |
| "Both locks name PID 20668, last progress ~11:04" | True, but 11:04 is the **pre-child resume receipt**, not the death time. Death was the 11:55 Job teardown. |
| "August 18 independently verified 12/12" | **Confirmed** by direct ledger read, as are 08-15 and 08-16; 08-17 is **0/12**, not partial. |
| "Local verification passed 349 tests + 15 subtests… diagnostic only" | Correctly labelled. The focused wrapper re-proves it with worktree-scoped imports and `__file__` assertions — the exact §8s repair. |
| "ROLL-SENSITIVE" | **Independently confirmed** from the live closures. |
| "Five hash-bound one-shots implement overlapping transitions" | True; there are **three distinct transitions** across five tasks and three wrapper scripts. All three overlap (proof in §12/below). |
| `status.ps1 -Json` is safe to run | **FALSE** — it appends to the disk trail. |
| STATE_OF_PLAY: "The parent integration transaction is overdue until this rewrite…" | **Already satisfied** — completed 10:10, receipt `receipt-a76ec7b5599d-0EC77703D605.json`, `documentation_transaction_latest.json` `status PASS`. |
| STATE_OF_PLAY: "supervised execution tape is connected and integrity-valid" | True, but the supervisor's own `state` is **DEGRADED** and `price_path_evidence_usable=false`. Omitted. |

**Active-hours proof (Q17), from the actual `In-ActiveHours` semantics `start>end ⇒ h≥start ∨ h<end`:**

| Switch | Old window | h∈old? | New window | h∈new? | Overlap |
| --- | --- | --- | --- | --- | --- |
| 18:05 (h=18.083) | 11→5 | 18.083 ≥ 11 → **yes** | 11→5 | **yes** | ✓ |
| 00:20 (h=0.333) | 11→5 | 0.333 < 5 → **yes** | 23→17 | 0.333 < 17 → **yes** | ✓ |
| 11:56 (h=11.933) | 23→17 | 11.933 < 17 → **yes** | 11→5 | 11.933 ≥ 11 → **yes** | ✓ |

**Gap-free confirmed independently.** Wrappers reject out-of-window invocation (`morning-protect.ps1:28`, `restore.ps1:28`, `protect.ps1:30-36` allowing 10:00–11:30 or 18:00–18:10), read the registry back as a postcondition, never reboot, and `exit 1` on failure.

---

## 11. What the plan proves vs. what it does not

**It proves, if everything passes:**
- The exact tip `dc93479b` is suite-consistent and integrates cleanly with capture recovery on all three workers.
- Lock ownership, bounded refresh, tiering containment and honest status reach production.
- August 17 is settled 12/12 from authoritative `daily_summary` rows across the exact current registry.
- The already-supervised public execution producer runs 780 s with no second writer and no new gap.
- A non-authorizing, paper-only, International candidate either selects or refuses safely.
- The documentation transaction closes at the exact post-integration HEAD.

**It does not prove — and must not be described as proving:**
- Any order, fill, queue position, fee actually charged, rebate actually paid, or realized P&L.
- Physical eligibility. The binding record is still `blocked=true, country=CA, region=ON`.
- That disk was reclaimed (§P2-d).
- That the model contributes edge. `ESTABLISHED_FINDINGS §1`: we do not beat the market.
- That the execution price path is usable — `price_path_evidence_usable: false`, `identity_integrity: BLOCKED_UNIQUE_EXECUTION_COUNTS`, and historical gaps still make the accumulated path unusable for economics.

---

## 12. Recommended changes (do not implement tonight unless flagged "tonight")

Ordered by urgency. **Nothing here should be implemented by me.**

1. **[Tonight, ~10 min] Bound the two recurring tiering tasks.** Lower `WeatherClobTiering` ExecutionTimeLimit to ~PT30M and `WeatherClobRawTapeTiering` to ~PT40M so Task Scheduler enforces what the audit table asserts, until the merge deploys `MaxRuntimeSeconds`. *Validation:* re-export both task XMLs and confirm `ExecutionTimeLimit`; re-run `audit.ps1` and confirm still PASS. **Target:** the two registered tasks, not the repo.
2. **[Tonight, decision only] Accept or break the Codex→backfill coupling.** Either accept that a 00:43 auth failure forfeits August 17, or register an independent, agent-free 08-17 backfill fallback that requires the *deployed* `chain_recovery_run.ps1` to carry `repair-stale-locks` rather than requiring the merge receipt. *Validation:* a `-ValidateOnly` receipt showing which dependencies it would and would not require. **Target:** a new `C:\Users\micha\ops\settlement-backfill-0817-fallback-0820\`.
3. **[Tonight, 1 min] State the sign-out dependency to the operator explicitly** (see §14).
4. **[This week] Fix `audit.ps1` to verify the file that will run.** For `hash_mode='deployed_repo'`, gate on the **working-tree** text and promote `current_matches_expected=false` to a warning naming the merge it depends on; add `$git.ok` and light-vs-exclusive overlap to the checked set. *Target:* `C:\Users\micha\ops\overnight-schedule-audit-0820\audit.ps1`.
5. **[This week] Add an active-hours re-assertion at ~05:00.** A sixth one-shot that reads the registry and re-applies `23→17` if it is not already, so a double failure at 00:20/00:22 is caught before the unprotected span. *Target:* `active-hours-0820\`.
6. **[This week] Record reclamation in the tiering retry receipt.** Capture free bytes before/after and emit `reclaimed_bytes`; keep PASS on zero, but make the number visible so no disk claim is written from an execution-only receipt. *Target:* `tiering-retries-0820\run.ps1`.
7. **[This week] Add lock cleanup to the Stage-A teardown path.** `scripts/ops/daily_refresh.ps1` `finally` should invoke the canonical `repair-stale-locks` after `$childJob.Dispose()`. This is the actual root cause of both of today's leaks and is independent of the merge. *Target:* `scripts/ops/daily_refresh.ps1` — **roll-free (.ps1)**.
8. **[This week] Reconsider `danger-full-access` for the recovery agent.** If Codex supports a writable-roots allowlist, scope it to `C:\Users\micha\ops\` + Task Scheduler; otherwise document that the boundary is prose. *Target:* `live-overnight-audits-0820\invoke-agent.ps1`.
9. **[This week] Give `training_window.ps1 -RestoreOnly` the lease**, or classify it as exclusive in the auditor. *Target:* `scripts/ops/training_window.ps1:126`.
10. **[Low] Pin a minimum chunk count** in the suite verdict regex. *Target:* `live-cumulative-full-suite-0820\run.ps1:215`.
11. **[Low] Reword the review contract's step 3** — `status.ps1 -Json` writes the disk trail and is not read-only.

---

## 13. Go / no-go checklists

### Tonight — before the operator logs off
- [ ] **Lock or disconnect the session. Do NOT sign out.** `WeatherOneShotPush` is `LogonType: Interactive`; sign-out forfeits the merge publication and every downstream receipt.
- [ ] Confirm `codex.exe` is authenticated *now* (the whole chain hinges on 00:43).
- [ ] Confirm all 18 new tasks read `Ready` / `0x41303` / correct `NextRunTime` — verified as of this audit.
- [ ] Confirm `WeatherActiveHoursProtect0820` fires at 18:05 tonight and its receipt shows `observed 11/5`.
- [ ] Accept, or bound, the two unbounded recurring tiering ETLs (P1-a).
- [ ] Leave `data\backtest\daily_refresh.lock`, `long_job_guard.lock`, `long_job_guard_status.json`, `daily_refresh_status.json` **untouched** — the 03:55 canonical repair, and failing that the 09:30 `acquire_lock` dead-PID path, both handle them.
- [ ] Do not reboot. Three pending indicators are set and Active Hours is the only guard.
- [ ] Confirm `WeatherEveningEvidenceRefresh` / `WeatherDataMirror` / `WeatherTrainingWindow` remain Disabled and `WeatherTrainingWindowRestore` enabled — verified.

### No-go tonight if any of these become true
- The cumulative worktree stops being clean at `dc93479b` (it is clean now).
- `origin/master ≠ HEAD` before 00:56.
- Any of the three capture supervisors leaves `RUNNING`.
- Free physical RAM drops below ~2 GiB or commit above 64% before 00:30.

### Future live-money test, after physical relocation — separate and stricter
- [ ] Fresh official geoblock response `blocked=false` matching the host's **real** location, no VPN/proxy, fetched at client construction, at the one-submit capability, and **again within 5 minutes of submit**.
- [ ] International (`polymarket_global`) only. Any other platform identifier is an abort.
- [ ] Isolated wallet funded ≤ **100 pUSD** of the verified settlement collateral; run budget ≤ wallet cap.
- [ ] Exactly one weather market; one backed BUY; forced post-only; **no marketable retry after post-only rejection**; **no naked sell**.
- [ ] Non-raisable ceilings verified in the run config: 25 daily loss / 25 event notional / 10 band notional / 120 s TTL.
- [ ] Smallest current exchange-valid share size and tick read from the book immediately before submit.
- [ ] Attended session only. Ends with cancel-all **plus an authenticated query proving zero open orders**.
- [ ] Authoritative account readers for user events, open orders, positions, balances, fees, rebates.
- [ ] Economics declared **incomplete** until exit, settlement, and rebate **payout** are reconciled. An estimated rebate is unrealized.
- [ ] Explicit operator authorization at the time of the action. Candidate selection is never authorization.

---

## 14. Final concise handoff

**Single next action before the operator logs off:**

> **Lower the two recurring tiering `ExecutionTimeLimit` values to match the plan's own hard ends (`WeatherClobTiering` → ~PT30M, `WeatherClobRawTapeTiering` → ~PT40M), then tell the operator to lock or disconnect — never sign out.**

That one task-settings change closes the only gap where a *failed* merge can produce an **uncontained** job holding the shared lease into the Stage-A and graded windows, and it is the only finding where the PASS audit certified code that will not be the code that runs. Everything else is either already fail-closed or is a design trade-off the operator should be told about rather than a defect to fix tonight.

Two sentences the operator needs, verbatim:

1. *"If you sign out instead of locking, tonight's merge will land locally, the push will never happen, and continuity, the August 17 backfill, both tiering retries, the candidate and the morning closeout will all refuse — while production runs the day on unpublished code."*
2. *"If Codex cannot authenticate at 00:43, August 17 stays a 0/12 settlement hole, because the backfill is five links downstream of that smoke test."*

---

### Read-only compliance
No file created, edited, deleted, moved or copied. No git command beyond `status`, `rev-parse`, `cat-file -t`, `merge-base --is-ancestor`, `diff --name-only/--name-status`, `show`, `worktree list`. No fetch. No task registered, modified, enabled, disabled, started or stopped. No wrapper executed — including `status.ps1`, `roll_verdict.ps1`, and every `-ValidateOnly` path. No test, collector, backfill, tiering or Codex run. No process terminated. No credential read; `C:\Users\micha\Desktop\.env.txt` never touched. All JSONL/JSON reads used shared-read semantics or Python file reads that do not block writers. Every tape, ledger, receipt, log, task result and branch is preserved. Report returned here only; nothing saved locally.
