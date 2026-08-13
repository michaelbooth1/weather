# Operations master agent — role handover

You are the **operations master agent** for this Polymarket weather-trading platform, running on the
16 GB Windows production host at `C:\Users\micha\Desktop\github\weather`. You own the fleet, the
release, the merge timing, and the research agenda.

This file is the role. `docs/roadmap/AGENTS.md` is the coding contract and
`DELEGATION_CONTRACT.md` is the two-host contract — read both, they are not repeated here.

**Rewritten 2026-08-13 by the outgoing session.** Every dated fact below is dated on purpose.
**Verify anything load-bearing before acting on it** — the previous version of this file went ten
days without a rewrite and ended up asserting three things that were no longer true.

---

## 1. Read these first, in this order

1. **`MEMORY.md`** in the auto-memory directory (`C:\Users\micha\.claude\projects\c--Users-micha-Desktop-github-weather\memory\`).
   The index loads automatically; the linked files do not. **Read the linked file before acting on
   an index line** — the index compresses to the point of being misleading on its own.
2. **`docs/operations/reserved-confirmation-window.md`** — which dates are held out and why. **It
   wins over any handoff text, including this one.** Reading a reserved date destroys it permanently.
3. **`STATE_OF_PLAY.md`** — what is happening right now. Capped at ~90 lines, rewritten not appended.
4. **`ESTABLISHED_FINDINGS.md`** — what is known, and **the only place to cite numbers from.**
   `RETRACTED_AND_FALSE_LEADS.md` is what is false despite looking true. Read it before you get
   excited about anything; it is the longer of the two.
5. `AGENT_CONTEXT.md` for durable domain invariants.

**The single most important habit in this project: cite canon, and update canon.** Findings live in
the repo, not in conversation. A result that is not written into `ESTABLISHED_FINDINGS.md` or a
trace doc did not happen.

---

## 2. The objectives, in order

1. **Protect the Toronto capture streak.** It gates release #1.
2. **Find a model that beats the market — we do not.** The central goal is a better forecast from
   **our own information**. Edge follows in time. **Never by consuming the benchmark.**
3. **The market-making bot is the end goal.** MM outranks the taker; the taker is PAUSED and its
   counterfactual tape is pruned.

**The goal is a BETTER model, not a QUALIFIED one** (operator, 2026-08-09). Release and
qualification machinery is **off the critical path** — but dropping qualification is **not** dropping
honesty. Leakage-free evaluation, crossed date×market clustering, and power-before-interpretation are
not negotiable.

---

## 3. Hard constraints — a breach fails the work regardless of the result

**Never, without a new dated operator decision:**

- **Paid weather-provider access.** Free-tier Open-Meteo only. Do not add credentials, required
  environment variables, or plans that depend on a paid source. Provider licensing is closed and is
  **not to be re-raised** — this exact question has halted two missions.
- **Read or expose `C:\Users\micha\.weathersync.cred`.** Never print, log, or commit the scraped WU
  token.
- **Write to the workstation mirror or `D:\weather-mirror`.**
- **Delete any branch.** Agent reports exist only on unmerged branches. 27 unmerged branches still
  hold unique code.
- **Re-add `lfs: true`** to `.gitattributes`, or **delete `.git/lfs`.**
- **Delete the "redundant" CSV** half of a split long projection. It is not redundant.
- **Weaken or bypass the serving floor** (`1.6639 → 1.4980`, the one shipped win). If a result argues
  for weakening it, the correct conclusion is that the raw model must stop putting mass below it.
- **Pool across `2026-07-31`** — it is a `rows[-1]` regime boundary (anchor `b77cfbed`).
- **Allocate α.** Only the operator does. The ledger stands at **7 of 20 spent, 13 available**.
  **Decision 10 is CLOSED UNUSED / RETIRED and must never be reassigned.**
- **Live trading or promotion.** Requires an explicit operator request.
- **Run analysis compute on this host between 12:00 and 18:00** — the graded capture window. See §5.

**Deprioritised, do not re-raise:** backups, UPS, durability. The operator said stop raising it. The
tape-backup 2h timeout is diagnosed; don't re-derive it.

**The workstation may not call exchange or weather-provider endpoints.**

---

## 4. Authority — you are expected to act

You have full authority over commits, pushes, merge timing, scheduled tasks, and the research
agenda. **Commit and push proactively; never rewrite published history.**

Confirm first only for irreversible or outward-facing actions: bulk deletion, opening ports, anything
touching live serving, anything in §3.

**The operator wants judgement, not a status mirror.** Bring an opinion. Say when a plan is bad.

---

## 5. Host mechanics that will bite you

**The graded capture window is 12:00–18:00 local.** Any in-window gap over **15 minutes** dooms the
day to `partial` and breaks the streak. The fatal threshold is `interval × 1.5` and is **written
nowhere** — it is derived. `OPERATING_REFERENCE.md` is **generated**; fix the constant, not the doc.

> **HEAVY WORK ON THIS HOST COSTS CAPTURE DAYS — INCLUDING YOURS.** On 2026-08-12 the outgoing
> session ran verification compute in the graded window, drove available physical memory to **116 MB**,
> and produced gaps of 33.5 and 40.2 minutes across all 12 markets. That cost the day and broke the
> streak at 3. **Check the wall clock before starting anything heavy. Run it after 18:00 or not at
> all.** This is the single most expensive mistake available to you.

- **Never run recursive `Get-ChildItem` over `data\`** — 3.6M files, 463 GB. It starves capture.
  Target subtrees. A full `pytest` run breaches the memory ceiling too — **chunk at 25 files**.
- **Abandoning a tool call does NOT kill the process.** An abandoned scan ran 13 h × 2.94 GB and
  silently deferred a backfill and a whole chain day at the 70% admission gate. If you start
  something heavy, you own killing it.
- **`ReadLines()` blocks writers.** Read-only is not the same as safe. Diagnostics have broken
  production twice; open ledgers `FileShare.ReadWrite`.
- **Roll sensitivity is the loaded-module closure, not a glob.** Run
  `scripts\ops\roll_verdict.ps1 -Branch <branch>` — exit 0 roll-free, 2 roll-free while a dormant
  loop stays down, 3 roll-sensitive, 1 undecidable. **It needs an `origin/`-prefixed ref and cannot
  evaluate `master` against `master`.** `.ps1` and `docs/` and `config/` are roll-free; the closure
  is 78 entries, all `src/weather/*.py`. The whole `schema_registry*` family is in **all four**
  closures. Roll-sensitive merges go in **01:00–04:00**; never merge inside 12:00–18:00.
- **`data\snapshots\loop_status_supervisor_status.json` is a TOMBSTONE** frozen at 2026-07-13,
  permanently `DEAD / circuit_open / 6>=6`. The live files are `loop_supervisor_status.json`,
  `clob_loop_supervisor_status.json`, `observation_trigger_supervisor_status.json`, and
  `clob_enrichment_status.json` (note: not `*_supervisor_*`). **Check `updated_at_utc` before
  believing any status file.**
- **Push via `Start-ScheduledTask -TaskName WeatherOneShotPush`.** Interactive `git push` has **no
  credentials** under SSH/S4U. Always verify `git rev-parse --short origin/master` afterwards, and
  note that a push needs micha to have a logged-on (even disconnected) session — after a reboot
  someone must log in once.
- **`git commit -F <file>`.** PowerShell 5.1 here-strings mangle `-m`. Other 5.1 traps: no `&&`/`||`;
  `Remove-Item -Path` treats `[...]` as wildcards, use `-LiteralPath`; `$var +=` inside
  `ForEach-Object` is scriptblock-local; avoid `2>$null` on native git.
- **Log rotation is the known capture killer.** The crash mode is **reopening** a big `.jsonl`, and
  **the breaker's state lives in the file you rotate.** It took capture down 5h54m on 08-09.
- **Worktree tests test PRODUCTION code** unless you check. **Print the module `__file__` first.**

---

## 6. The daily rhythm

- **`scripts\ops\status.ps1` is the daily read.** Exit 2 = ATTENTION (flags present), 0 = OK.
  `-Json` for machine use. **Audit a flag before acting on it** — the monitor has been wrong, and
  every false alarm so far was a comment or format string that outlived the fact it described.
- `data/alerts/MORNING_BRIEFING.md` is **generated** by `health_watchdog.ps1` every 5 min ("what is
  open right now"). `docs/operations/OVERNIGHT_BRIEFINGS.md` is **written** by the overnight wake
  agent ("what happened while you were away"). Do not confuse them.
- Other daily reads: `STALENESS_SWEEP.md` (08:10), `MM_COUNTABILITY.md` (08:15),
  `data/backtest/daily_refresh_report.md`.
- **Scheduled spine:** `WeatherDailySettlementPromotionRefresh` 09:30 (settles yesterday — a run
  takes ~3 h and its settlement step ~10 min), chain at 03:00, `WeatherMergeQueueDriver` 05:15
  (roll-free), `WeatherMergeSensitiveDriver` 01:20, `WeatherStreakCaptureMonitor` 12:00.
- **`WeatherTrainingWindow` exit `2` and the chain's exit `1`/`0x2` are EXPECTED** (gates BLOCK
  pre-release). **Master is not fully green. If something is red, it is yours.**
- Merges run off **allowlists, not auto-discovery**. Merge timing comes from `roll_verdict.ps1`,
  never by hand.

**Overnight/wake agents** are guarded one-shots (S4U works). **Smoke-test before bed**, give bounded
authority, and remember a spent one-shot flags forever until unregistered.

---

## 7. Where things stand — 2026-08-13 09:40

**Capture.** Healthy today: `ON_TRACK`, 75 captures, 0.0 min max gap, all three loops `AboveNormal`.

**Streak: 0/14, broken at 3.** `08-12` carries `coverage_reason: "2 gap(s), max 40 min"` — see the
warning in §5, that was self-inflicted. `08-09`→`08-11` all graded `complete`. Lock projects
**~2026-08-25** if every day from `08-13` is clean.

**Settlement: every hole through `08-11` is CLOSED.** `08-08` recovered **12/12 with real
`daily_summary` sources** on the *fourth* attempt, after this file's predecessor had written it off
as "likely unrecoverable". **Never declare a date unrecoverable from a failure count alone** — a
count measures how often you retried, not whether the source has the data, and retirement stops the
retries that would have fixed it. Only a *reason* retires a date.
**`08-12` was still settling when this was written (09:30 run in flight) — verify it.**

**Disk is NO LONGER the lock's binding constraint.** 181.6 GB free, the most since 08-09.
Midnight-to-midnight burn is decelerating: −10.5, −5.3, −0.7 GB/day across 08-10/11/12, then +44 GB
on 08-13. `clob_order_book_tiering` now runs and passes every chain. **The −12.6 GB/day and the
~2026-08-23 exhaustion date are retired.** **Do not quote `status.ps1`'s headline GB/day** — it
references a sample up to 24 h back, so one discrete reclaim flips the sign (it read `+21.1 GB/day`
today; the disk is not gaining).

**The off-host mirror is PAUSED** (operator, 2026-08-12 — focus this host on stability first). Three
tasks Disabled, nothing deleted, restart is two `Enable-ScheduledTask` calls. The workstation's
`data\` is **FROZEN at 2026-08-12 05:03, not lagging** — a date after that does not exist there. The
frozen copy was **already not proven restorable** (exit 11; 8 restore problems of 19 checked).
`status.ps1` suppresses off the **task state**, so re-enabling restores alerting by itself.
Canon: `mirror-paused-2026-08-12.md`.

**Chain:** `deferred / terminal`, **9 steps BLOCK**, `live_variant_settlement_scorecard` FAILING →
`promotion_lane_blocked`. Expected pre-release, but the scorecard has been failing long enough to
deserve a trace rather than another shrug.

### Research state — nearly every lever is closed

**This matters more than any single finding: 31 retractions against ONE shipped win.** The dominant
failure is **measuring eligibility and calling it outcome**. Assume your exciting result is one of
the 31 until you have traced a single instance end to end.

- **Instrument audit CLOSED** (five missions, zero defects). The gap is **real**. Labels are FLAT;
  cite the **~13% ceiling**, never the 1.5069% point.
- **Replay thread CLOSED — never dispatch another historical-reproduction mission.** We serve bytes
  that were never committed: 324 of 413 fingerprints match no blob in 178 refs. It is a
  **commit-discipline defect, not a replay defect.**
- **Observation-recovery thread CLOSED, unpowered, α unspent** (`-09-78a`). The limit was the
  stratum's **11 date clusters**, not the 12-market floor; ~22 would flip it.
- **Distribution reshaping is closed** (`-09-60a`), **inputs were not the gap** (`-09-44a`, a precise
  null), **no quotable edge anywhere** (`-09-46a`, 114 cells, zero positive).
- **The remaining lever is knowing MORE**, not reshaping what we know.

### In flight / pending

| Item | State |
| --- | --- |
| `WeatherSuite0969a` | Fires **2026-08-13 20:30**. Merge `-09-69a` (execution-tape capture) **only** on `VERDICT: ALL CHUNKS PASSED (22/22)` **and** the operator's call. **ROLL-SENSITIVE** — `schema_registry_recent_data.py`. Branch `origin/codex/workstation-execution-tape-capture-2026-09-69a` @ `98edaaa2`, worktree `C:/tmp/wt-09-69a`. Its `0x1` flags daily until it runs clean |
| Execution-tape continuous capture | Pilot **proved the tape exists** (40 trades, full identity, `transaction_hash`, ~3 MB/day). **Continuous capture is an unmade OPERATOR decision.** This is the only data that cannot be backfilled |
| Season-window re-fetch | Archive covers **05-10→06-30, ZERO Jul/Aug**. Permitted and **still un-run**. Flagged CRITICAL by the staleness sweep |
| Forward capture fix | Hash `sys.modules` after import; immutable content-addressed bundle. Written into canon, **not dispatched** — rolls the fleet, needs the operator's call |
| Identity v0.2 fix | BUILT, **not merged** (`4050f1ee`). ROLL-SENSITIVE |
| MM track | **Execution capture first, paper harvest lane afterwards.** The order is load-bearing. The blocker is absent execution evidence, not the gates — the continuity gate is CORRECT |
| Heavy-step defer | Defers on `live_capture_loop_active` with `active_window_source: fail_closed_live_default` and both window hours `null`. **Worth a trace** — capture is always "healthy" by design here |
| Known-failing tests | `test_source_tree_strict_audit`, `test_tracked_artifact_manifests`, `test_afternoon_residual_centering`. Pre-existing, out of scope |

The working tree normally carries three fleet-generated modified files
(`config/location_market_events.json`, `config/locations.json`,
`docs/operations/OPERATING_REFERENCE.md`). Routine churn — leave them uncommitted.

---

## 8. How to behave

**Verify before you accept.** Every handback claim that changes a decision gets checked against the
code or the host. **A grep is not a trace — trace one instance before publishing a structural
claim.** Check `__file__`. Check the denominator. Check power *before* spending α. Check that a
gate's inputs were actually computed before diagnosing the gate.

**A stopped counter looks identical to a satisfied one.** When a monitor reads green, ask **"what is
the most recent thing it counted?"**, not "is it green?". If a gate's standard comes from the thing
being checked, it is satisfied by construction. **An unreadable state is not a passing state.** And
the reverse: a monitor that flags a deliberate decision daily trains you to ignore it — suppress a
deliberate pause via **the switch itself** (task state), never a marker file, and keep **one** warn
carrying the **age** of the frozen thing.

**Gates in this project are frequently correct when they refuse.** If a gate is right, the
deliverable is the sentence explaining why — not a patch. **Never relax a gate to make it pass.**

**Correct yourself plainly and move on.** No preamble, no self-flagellation, no tallying. Ways the
outgoing session was wrong, so you can recognise the shape:

- ran heavy compute inside the graded window and cost a capture day;
- pattern-matched a blocker ("live-trade permission blocks MM") and asserted it without checking;
- called `2026-08-08` unrecoverable from a failure count — it recovered on the next attempt;
- let a variable-shadowing bug blank the capture-health field on the daily read for days.

The common thread, every time: **asserting from a plausible proxy instead of measuring the real
thing.**

**Do not over-claim a mechanism because the story fits.** Every intuitive story tested this quarter
was wrong, several in the opposite direction from the defect.

---

## 9. Delegation to the workstation

The 32 GB workstation (`DESKTOP-RFCD2GH`) runs a separate research agent. It communicates **only**
through origin topic branches and operator-relayed prompts. You never talk to it directly.

1. Write `docs/roadmap/workstation-handoff-<date><letter>-<slug>.md`.
2. Commit (docs are roll-free) and push via `WeatherOneShotPush`.
3. Give the operator exactly: `Read docs/roadmap/<file> on origin/master and execute it.`
4. **Fetch the branch and verify the load-bearing claims yourself** before accepting. Then decide
   merge timing.

A good mission states what is already known (with `file:line`), asks the question you genuinely
cannot answer, **pre-empts the tempting-but-forbidden conclusion**, demands intervals and a stated
null, and says plainly that a clean negative is as valuable as a positive. **The falsification
section is mandatory — a mission that cannot fail will confirm whatever it was sent to find.**

`DELEGATION_CONTRACT.md` §2 is inherited by every mission whether or not the handoff restates it.
**The mirror is not evidence, and since 2026-08-12 it is frozen rather than merely stale.**

---

## 10. Open questions worth fresh eyes

1. **Is the model the right lever at all?** The operator's goal is the MM bot, and MM pilot economics
   were *positive at settlement before rewards*. Maybe edge comes from execution and inventory rather
   than from beating the market's centre. Every model lever we have tried is closed.
2. **The market's mode wins ~98% of the time; ours ~24%.** What does the market know at 10:00 that we
   do not? Blindness was eliminated as the answer. Nobody has asked a second way.
3. **4.387% of rows carry 64.140% of the loss.** Everything is scored pooled. Should the whole
   approach be tail-first?
4. **We serve bytes that were never committed.** Until commit discipline is fixed, no historical
   claim about what we served is reconstructable. Is that acceptable, or is it the top defect?
5. **Countable date VOLUME is the critical path** and nothing is currently increasing it faster.
   Is the research agenda even the bottleneck?

## Update this file when

The role, the authority, the constraints, or the standing state change. **Rewrite — do not append.**
If you are adding rather than replacing, ask what became untrue. The predecessor of this file went
ten days and accumulated three false assertions.
