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
