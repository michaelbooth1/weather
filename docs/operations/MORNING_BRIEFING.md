# Morning briefing

**The after-away read.** Unattended overnight wake agents append a dated section here. Newest
night at the top. If nothing needed you, the sections will be short — that is the intended outcome.

**How to read it:** every section leads with `OK`, `ATTENTION` or `ACTION NEEDED`. If any section
says **ACTION NEEDED**, its first sentence is the thing to do, in imperative form with the command.

---

## Night of 2026-08-09 → 2026-08-10

Three wakes are armed: **02:00**, **06:00**, **10:30** (`WeatherAgentOvernight0200/0600/1030`,
runner `C:\tmp\weather-overnight-0810\runner.ps1`, one-shot and self-disarming). The mechanism was
smoke-tested at 21:42 on 2026-08-09 — headless launch returned `SMOKE_OK`, exit 0.

**State at hand-off, 21:39 on 2026-08-09** — `status.ps1` verdict **ATTENTION**:

| | |
| --- | --- |
| Streak | 15/14, today **CLEAN** — 142 captures, 0.0 min max gap |
| Capture | all three loops at AboveNormal |
| Disk | 160.5 GB free, **−15.1 GB/day, ~11 days headroom** |
| Settled through | **2026-08-04** — 12 of 12 markets, 4 days behind |
| Git | clean, 0 unpushed |

**Open flags the wakes are watching:**

1. **The 05:15 roll-free merge ROLLED BACK on 2026-08-09 05:20** — snapshot heartbeat did not
   advance because capture was mid-outage. Nothing landed. **11 branches are pending**, including
   `-09-56a` and `-09-57a`, whose findings are already in canon.
2. **Settlement hole, 4 days.** `WeatherSettlementBackfill20260805` fires **05:30 on 08-10**; the
   other three are armed for 08-11, 08-12, 08-13. Each missed day needs its own backfill — the
   chain will not retry it.
3. **Disk at ~11 days.** Not tonight's problem; do not let it become a surprise.
4. Mirror restore-verify reported a problem file (standing, deprioritized).

**If a wake section is missing**, the task either did not fire or its guard aborted it. Check
`C:\tmp\weather-overnight-0810\logs\runner-<wake>-*.log` — guards abort on low memory (<2500 MB),
a concurrent agent, or a missing binary, and a skipped wake is by design safer than a wake that
starves capture.

---

### 02:00 wake — 2026-08-10

**OK.** Nothing broke tonight. Capture is writing right now, all three supervisors are RUNNING with
no circuit breaker open, and the 01:20 roll-sensitive driver ran clean. No action before breakfast.

**The 01:20 driver: it ran, and it had nothing to merge.** `WeatherMergeSensitiveDriver` last ran
`2026-08-10 01:20:01`, result `0`. All six missions in the `-09-43a` entry had **already landed the
previous night**, 2026-08-09 01:30-01:50, and were pushed then. Tonight it logged
`skip (already merged or absent)` for all six. That message is ambiguous, so I resolved it: every
one of the six refs **exists** and **is an ancestor of `origin/master`**. Already merged, not absent.

| queue entry | state |
| --- | --- |
| `-09-43a` repair-the-blind-feature-block (carries -09-33a/38a/39a/41a/42a) | MERGED |
| `production-tolerate-benign-capture-race-2026-08-08` | MERGED |
| `production-register-two-schema-literals-2026-08-08` | MERGED |
| `-09-44a` remeasure-the-gap | MERGED |
| `production-register-mm-countability-schema-2026-08-08` | MERGED |
| `-09-46a` does-a-quotable-edge-exist | MERGED |

The driver also did one piece of real work: at 01:20 it found master ahead of origin by one commit
(the 01:00 config auto-commit `1b21343e`) and reconciled it via `WeatherOneShotPush`. That orphan
normally waits for a manual morning push.

**Two corrections for whoever reads the flags next:**

- The `status.ps1` FLAG *"quiet-window merge ROLLED BACK ... capture did not recover"* is **21 hours
  stale**. It refers to the **05:15 roll-FREE** driver on 2026-08-09 05:20, which correctly refused
  to push while capture was mid log-rotation outage. It does **not** describe the 01:20 sensitive
  driver, and nothing rolled back tonight.
- The branch in the wake instructions, `...repair-blind-local-meteorology-2026-09-43a`, does not
  exist. The real name is `codex/workstation-repair-the-blind-feature-block-2026-09-43a`. The wrong
  name makes `merge-base --is-ancestor` exit **128**, which reads like a "no" and is not one.

**Capture recovered and is counting — evidence, not assumption:**

| check | value |
| --- | --- |
| last snapshot written | `2026-08-10T02:02:40` (id `20260810T020239152425-0400`) |
| iteration | 85, outcome `clean`, 0 errors, `last_error` empty |
| fleet liveness | 12 of 12 markets healthy, **0 stale**, 0 pending |
| today | 15 captures, max in-window gap **0 min**, window covered through 02:03 |
| supervisors | snapshot_capture / clob_loop / observation_trigger all `RUNNING`, `action=noop`, updated 02:02:1x |
| restart budget | no circuit breaker open on any live loop |

Snapshot capture shows `started_at 01:00:15` — that is the expected commit-triggered readopt of the
01:00 config commit (`runtime_identity.git_commit = 1b21343eeead`, `runtime_code_state = current`),
and it has run 85 clean iterations since.

**Do not be alarmed by `loop_status_supervisor_status.json`** — it reads `state=DEAD`,
`action=circuit_open`, but it was last updated **2026-07-13**, four weeks ago. It is the legacy
tombstone that `roll_verdict.ps1` explicitly ignores, not a fourth live loop. The three live
supervisors each have their own status file and all three are green.

**No log rotation was needed.** Largest live `.jsonl` is `diagnostics.jsonl` at **13.8 MB** (it was
625 MB when it took capture down on 08-09); `observation_trigger_diagnostics.jsonl` 13.1 MB,
`observation_triggers.jsonl` 9.0 MB, `clob_diagnostics.jsonl` 5.5 MB. Nowhere near the reopen-crash
regime, so I rotated nothing.

**Escalated, not fixed — for the 06:00 and 10:30 wakes:**

1. **The chain fix is still UNTESTED in production.**
   `production-tolerate-benign-capture-race` landed 08-09 01:30 to stop the chain dying at step 4,
   but the 08-09 09:30 run **never reached step 4** — it deferred earlier, at `ingest_quality_gate`,
   on physical-memory/capture admission. Today's **09:30** run is the first genuine test of that fix.
   The 10:30 wake sees the result; the 06:00 wake will not.
2. **Settlement is now 6 days behind** (settled through 2026-08-04, not 4 days as at hand-off).
   `WeatherSettlementBackfill20260805` fires **05:30**, just before the 06:00 wake — that wake should
   confirm it actually settled 08-05 rather than merely exiting 0.
3. **12 branches still pending** in the roll-free queue (`-09-47a` through `-09-58a`).
   `WeatherMergeQueueDriver` fires **05:15**. `-09-59a` appeared as a new remote branch tonight and
   is not queued yet.
4. **Disk: 158.3 GB free, -9.4 GB/day, ~17 days.** Better than the ~11 days quoted at hand-off.
5. **Mirror restore-verify still fails on exactly one file** — and it is
   `snapshots\loop_status.json`, the highest-churn file in the 19-file check set (18 hash-match).
   The mismatch dates from the 08-09 outage window. Standing/deprioritized per operator.

---

### 06:00 wake — 2026-08-10

**ACTION NEEDED.** Re-point `WeatherSettlementBackfill20260807` (armed 08-12 05:30) at
`-TargetDate 2026-08-09`: **nothing is armed to settle 2026-08-09**, while 08-07 is already settled
and the defect that armed it cannot be repaired by a backfill. Second, `status.ps1`'s settlement-hole
flag is now **silenced by empty ledger records** and will not report the remaining holes — see below.

**Both jobs ran. Both worked.** Neither had failed this time.

#### (A) 05:15 merge queue — MERGED, did not roll back. 17 of 17 branches are on `origin/master`.

`WeatherMergeQueueDriver` ran 05:15:01, **exit 0**, finished 06:16:02. It merged **10** branches this
run (`-09-47a` through `-09-58a`), ~5 min each. `origin/master` is now `808682bf`. I checked every
entry in `merge-queue.txt` with `git merge-base --is-ancestor`: **17 of 17 are ancestors of
`origin/master`**, including `-09-56a` and `-09-57a`. The queue is fully drained.

**This is not the 08-09 pattern.** The 05:20 rollback on 08-09 was the snapshot-heartbeat check
failing while capture was mid-outage. That same check ran before and after all 10 merges tonight and
passed every time — the log reads `capture before: 6 loops, heartbeat …` / `capture healthy after the
roll; pushing` at each step. The check did its job on both nights; the difference is capture, not the
driver. Nothing merged by hand.

#### (B) 05:30 settlement backfill — it RAN and it SETTLED. 08-05 is closed in 12 of 12 markets.

`WeatherSettlementBackfill20260805` started 05:30:00 and is **still running at 06:18** (its
`LastTaskResult` `267009` = `0x41301` "task is currently running" — not a failure code). It is on
`taker_finalization_watchdog`, ~32 min into that step.

It is **not** a stopped counter. What it actually did, from `ledger.jsonl`:

- refetched the WU day file for its own target only — `raw\2026-08-05.json`, all 12 stations, 05:31–05:40;
- at 05:45 appended **74 records per market**, target dates 2026-05-27 → 2026-08-09;
- **2026-08-05 is now settled in all 12 markets** with real highs, `settlement_source=daily_summary`,
  `quality_grade=complete`, `promotion_countable=True`. Toronto 29.0 C, Dallas 101 F, Chicago 81 F.

**The hole was never "since 08-04".** Per-market state is identical across all 12 markets:

| date | state |
| --- | --- |
| 2026-08-04 | settled |
| 2026-08-05 | **settled — new tonight** |
| 2026-08-06 | **UNSETTLED** |
| 2026-08-07 | settled, but graded `partial` |
| 2026-08-08 | **UNSETTLED** |
| 2026-08-09 | **UNSETTLED** |

Most recent *settled* date, all 12 markets: **2026-08-07**.

**Why the three are empty — traced to source, not inferred.** They carry `settlement_source: none`,
reason `no settlement bucket available`. The cause is upstream: the raw WU day file does not exist for
those dates **in any of the 12 stations** — `raw\2026-08-06.json`, `2026-08-08.json`, `2026-08-09.json`
are all absent, while `08-04`, `08-05`, `08-07` are present. Not a 404, not quarantine
(`quarantined_raw_observations: 0`), not a settlement-code bug. The daily pull fetches *yesterday* at
~09:35 UTC, and the ledger shows **zero appends on 08-06, 08-07, 08-08 and 08-09** — four silent chain
days — so those day-files were never pulled. `-Refetch` fetches only its own `-TargetDate`, which is
exactly why 08-05 came back tonight and its neighbours did not. The per-day backfill design is right.

**Consequences for the three still armed:**

| task | fires | verdict |
| --- | --- | --- |
| `…Backfill20260806` | 08-11 | **correct** — will pull `2026-08-06.json` and should close 08-06 |
| `…Backfill20260807` | 08-12 | **wasted** — 08-07 is already settled; its `partial` grade is **2 capture gaps, max 41 min**, in our own snapshot tape, and a WU refetch cannot repair a capture gap |
| `…Backfill20260808` | 08-13 | **correct** — will pull `2026-08-08.json` and should close 08-08 |
| *(2026-08-09)* | — | **nothing armed** |

08-09 also did not get picked up by today's normal pull: the 05:30 backfill resumed the chain from
`public_wu_settlement_restore`, i.e. *downstream* of the fetch step, so no `2026-08-09.json` exists as
of 06:18. That is why the 08-12 slot should be re-pointed at 08-09.

**Streak reality check:** even with all three holes closed, 08-07 stays `partial`, so contiguity breaks
there and the 14-day clock restarts at 08-08 at best. Streak is **0/14** right now (most recent 08-09,
`missing_settlement`). There is a clean 10-day run 07-27 → 08-05, but it is historical.

#### The monitor will not tell you about the remaining holes — escalated, not fixed

`status.ps1` printed `settled -> 2026-08-09` this morning and raised **no** settlement-hole flag, while
three dates are unsettled. Traced, not guessed: line 232 reads **only** `target_date` from each ledger
record and never looks at `settlement_source`, `settlement_high` or `promotion_countable`. Tonight's
backfill appended records for 08-06/08-08/08-09 that settled *nothing* — and those records satisfy the
check. Every market's max `target_date` is now 08-09, so `latest -lt expected` is false and the flag at
line 245 **cannot fire**, today or for the next hole. (It is also gated to `Hour -ge 12`, so 06:00 was
never going to show it regardless.) Before tonight this flag correctly read "12 of 12 unsettled since
2026-08-04"; appending empty records is what silenced it. This is the stopped-counter shape: the
counter is reading satisfied over records that carry no settlement. `status.ps1` is a script, not
documentation, so I left it alone — but the hole detector is now blind and should be fixed before it
hides the next one.

#### Capture is alive

Writing continuously — newest snapshot write **06:18:39**, all 12 market tapes written at 06:07:31.
Most recently counted: **47 captures today, 0.0 min max in-window gap, window covered through 06:08**
(closes 18:00), verdict ON TRACK. Six loops, heartbeat advancing (06:15:02, per the merge driver's own
pre/post check). All three supervisors at AboveNormal. **No circuit breaker open, no restart budget
burned.** No worker hand-started.

**No log rotation needed.** Largest live `.jsonl`: `diagnostics.jsonl` **17.1 MB**,
`clob_diagnostics.jsonl` 10.6 MB, `observation_triggers.jsonl` 10.3 MB. The 625 MB and 752 MB files on
disk are the *already-rotated* 08-09 archives, not live. Nowhere near the reopen-crash regime.

**One thing I did to myself, disclosed:** at 06:12 I started a recursive `Get-ChildItem` over the repo
looking for chain state files — the known memory hazard. I killed it at 06:17 before it could starve
capture. RAM 8.13 GB free afterwards, capture unaffected (writes at 06:16:35 and 06:18:39 either side).
I answered the question from targeted paths instead.

**Standing, unchanged:** disk 163.2 GB free; mirror restore-verify still fails on the one high-churn
file (deprioritized per operator); chain terminal `0x2` = gates BLOCK, expected pre-release.

**For the 10:30 wake:** the 09:30 chain run is the first genuine test of the
`production-tolerate-benign-capture-race` fix — the 06:00 wake could not see it. Also confirm whether
the backfill's chain tail ever left `taker_finalization_watchdog`, and whether `2026-08-09.json` ever
landed.

### 10:30 wake — 2026-08-10 — **DID NOT RUN**

**No check was performed at this hour.** The runner's guards all passed (9018 MB free) and the agent
launched at 10:30:01, but `claude.exe` printed *"You've hit your session limit · resets 11am"* and
**exited 0**. The runner recorded success and no section appeared — and an absent section reads
exactly like "nothing to report". It was not.

**Fixed, not just noted.** The runner now inspects stdout for limit messages, rejects near-empty
output, checks the briefing's mtime advanced, and writes its own `DID NOT RUN` section when a wake
no-ops. **Exit code is not evidence a wake ran.** Recorded in the wake-agent memory as an instance
of the stopped-counter pattern — in the monitoring tooling itself.

**Covered manually by the production agent at ~10:40–11:00 instead:**

| Check | Result |
| --- | --- |
| Capture before the graded window | all three loops **AboveNormal**, RAM 8.27 GB free |
| Streak | **1/14**, day 1 `2026-08-09` — restarted, 08-09 settled `complete` 12/12 |
| The 09:30 chain run | **passed** — this was the first genuine test of `production-tolerate-benign-capture-race`, and 08-09 settled end to end |
| Disk | **169.2 GB free, ~22 days** — improved from ~11; CLOB tiering appears to have run |
| Settlement holes | **08-06 and 08-08** remain; backfills armed 08-11 and 08-13 |

**Standing:** the `WeatherSettlementBackfill20260809` armed this morning was **disabled** — the
09:30 run settled 08-09, so it was redundant. `WeatherExecTapePilot` is armed for **18:15** tonight.
