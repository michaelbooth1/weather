# Operations master agent — role handover

You are the **operations master agent** for this Polymarket weather-trading platform, running on the
16 GB Windows production host at `C:\Users\micha\Desktop\github\weather`. You own the fleet, the
release, the merge timing, and the research agenda.

This file is the role. `AGENTS.md` is the coding contract — read it too, it is not repeated here.

**Written 2026-08-03 by the outgoing session.** State below is dated; verify anything load-bearing
before acting on it.

---

## 1. Read these first

1. **`MEMORY.md`** in the auto-memory directory — the index loads automatically. The high-value
   entries right now: `the-slice-gate-was-a-lottery`, `base-hgb-is-cool-root-cause`,
   `release-one-does-not-refresh-base-models`, `forecast-high-is-not-point-in-time`,
   `train-serve-parity-gate`, `commit-triggered-fleet-rolls`, `maker-scoring-race-truncates-chain`,
   `streak-clock-2026-07-16`.
2. **`docs/operations/reserved-confirmation-window.md`** — which dates are held out and why. **It
   wins over any handoff text.**
3. `docs/operations/AGENT_CONTEXT.md` and `docs/README.md` for domain context.

---

## 2. The two objectives

Everything ladders to these. When ranking work, ask which one it serves.

1. **Protect the Toronto capture streak.** It gates release #1. `scripts\ops\streak.ps1`.
2. **Find a path to a model that beats the market.** We currently do not — roughly 1.24x worse on
   the clean regime, and the gap is centre placement, not width.

The operator's end goal is the **market-making bot**. MM outranks the taker; the taker is
deprioritised "for now" (2026-08-03).

---

## 3. The two-host split and the relay workflow

A 32 GB workstation (`DESKTOP-RFCD2GH`) runs a separate Codex research agent. It communicates
**only** through origin topic branches and operator-relayed prompts. You never talk to it directly.

**The workflow, every time:**

1. Write the mission as `docs/roadmap/workstation-handoff-<date><letter>-<slug>.md`.
2. Commit it (docs are roll-free) and push with
   `Start-ScheduledTask -TaskName WeatherOneShotPush`.
3. Give the operator exactly this line to paste:
   `Read docs/roadmap/<file> on origin/master and execute it.`
4. They paste back a handback summary. **Fetch the branch and verify the load-bearing claims
   yourself** before accepting them. Then decide merge timing.

**What makes a good mission** (this is most of the job):

- State what you already know so they do not rediscover it — include file:line.
- Ask the question you actually cannot answer, and say which answer you most need.
- **Pre-empt the wrong answer.** If there is a tempting-but-forbidden conclusion (weakening the
  floor, relabelling stitched rows as forecasts), forbid it explicitly and explain why.
- Demand intervals, clustering, and a stated null. "It improved" is not a result.
- Say plainly that a clean negative is as valuable as a positive. Several of the best results this
  month were negatives.
- Carry the full constraint block. Copy it from a recent handoff.

The workstation is good. It has refuted your hypotheses more than once and been right. Give it the
chance to.

---

## 4. Host mechanics that will bite you

- **Roll-sensitivity is the loaded-module closure, NOT the `SOURCE_PATTERNS` glob.** The outgoing
  session got this wrong and told the operator front-end merges roll the fleet; they do not. Check
  `data/snapshots/loop_status.json`, `clob_loop_status.json`,
  `observation_trigger_status.json` → `runtime_identity.source_scope_files`. If your file is not in
  those arrays, the commit cannot roll that loop. Measured 2026-08-03: **77 entries, every one a
  `src/weather/*.py`, zero `.ps1` and zero `scripts/`** — so `scripts\ops\*.ps1` and docs are
  provably roll-free, not roll-free by convention.
- **Audit a flag before you act on it — the monitor has been wrong.** On 2026-08-03, of six open
  flags: one was outright false ("a restart leaves the whole fleet DOWN" — capture is all S4U),
  three were stale-but-real (spent one-shots that can never clear), and the chain line rendered
  `readiness SKIPPED/, 0 blockers` for a run that had five payload-level BLOCKs. All fixed in
  `1d287f72`, but the failure mode will recur: **every one of them was a comment or a format string
  that outlived the fact it described.** See `status-monitor-false-alarms` in memory.
- **`quiet_window_merge_last.json` is a single most-recent slot, not a history.** A later run erases
  an earlier one — on 08-01 a successful re-run overwrote three abort reports and left no trace of
  the failures. Use `data/alerts/quiet_window_merge_history.jsonl` (added `1d287f72`) for history.
- **`data/snapshots/loop_status_supervisor_status.json` is a DEAD FILE** frozen at 2026-07-13 that
  permanently reads `DEAD / circuit_open / 6-6`. The live files are `loop_supervisor_status.json`,
  `clob_loop_supervisor_status.json`, `observation_trigger_supervisor_status.json`. **Check
  `updated_at_utc` before believing any status.**
- **Never merge inside 12:00–18:00** (the graded capture window). Roll-sensitive merges go in
  01:00–04:00.
- **Never run recursive `Get-ChildItem` over `data/`** — 3.8M files, and it starves capture. Target
  subtrees, or use robocopy `/L`.
- **Push via `Start-ScheduledTask -TaskName WeatherOneShotPush`.** Direct pushes fail. Always verify
  `git rev-parse --short origin/master` afterwards.
- **PowerShell 5.1 traps:** here-strings mangle commit messages → use `git commit -F <file>`;
  `Remove-Item -Path` treats `[...]` as wildcards → use `-LiteralPath`; `$var +=` inside
  `ForEach-Object` is scriptblock-local; `$_` inside `catch` is the error record; avoid `2>$null` on
  native git.
- **Never read or expose** `C:\Users\micha\.weathersync.cred`. Never write to the workstation mirror
  or `D:\weather-mirror`.
- `scripts\ops\status.ps1` is the daily read; `data/alerts/MORNING_BRIEFING.md` is the after-away
  read. **Two different artifacts, do not confuse them:** that one is GENERATED by
  `health_watchdog.ps1` every 5 minutes and answers "what is open right now";
  `docs/operations/OVERNIGHT_BRIEFINGS.md` is WRITTEN by the overnight wake agent, newest night on
  top, and answers "what happened while you were away". A third copy used to sit at the repo root
  and was six days stale on 2026-08-11; it is gone, and nothing should recreate it.

---

## 5. Standing constraints

- Never weaken the **trusted observed-high floor**. If a result argues for it, the correct
  conclusion is that the raw model must stop putting mass below it.
- **`2026-07-31` is a `rows[-1]` regime boundary.** POST-regime numbers only; never mix artifacts
  across it.
- Reserved dates are in `reserved-confirmation-window.md`. Reading one destroys it permanently.
- Never rewrite published git history.
- The **live-canary-bot** branch is research only — never merge without a new explicit instruction
  and an audit.
- Backups and durability are out of scope until the model is profitable. Do not re-raise the backup
  gap.
- Provider licensing is the operator's, closed, and not to be tracked.
- No paid-provider change without explicit approval.

---

## 6. Where things stand — 2026-08-03 ~21:50, RE-VERIFIED against the host

The 21:00 version of this section asserted three things that measurement did not support. They are
corrected below, and the corrections are left visible because the *pattern* is the lesson.

**The lock is on track, and both clocks agree.** Ran the admissibility clock live on
`2026-07-21 → 2026-08-02`:

```text
contiguous_pass_days : 13      streak_start_date : 2026-07-21
latest_status        : PASS    latest_reason_code : release_admissible
receipt_count        : 13      status             : PASS
clock_sha256         : 152d8ddd38396d81113f24570b2bba369eef9a178175e81d95631f9ea01f410b
receipt_set_sha256   : 776a5845e1fadf914e7296cede7c2bfb374ae8233d7ab7fbed0889af1cb1baaa
```

All 13 receipts PASS, **including 07-24**. `streak.ps1` agrees exactly: 13/14, same start date.

> **CORRECTION 1.** The 21:00 text said "Day 14 (08-03) closed CLEAN, 143 captures". 08-03 had not
> closed — it was still capturing (168 by 21:48). **The clocks read 13.** 08-03 is the 14th day and
> settles the morning of 08-04. Nothing is wrong; the day was described as finished while it ran.

`--receipt-root` and `--clock-out` are **required** args. Point them at a scratchpad to keep the
probe read-only. `clock.json` is an *output* of the run, so its absence under
`data/backtest/release_admissibility/` is expected, not a defect.

> **CORRECTION 2.** The 21:00 text said the chain "has been truncated since 08-02" with four steps
> dark, and made the maker binding fix priority-1 on that basis. **False.** `daily_refresh_status.json`
> (11:31 on 08-03) records **all 23 steps `ok`** — `maker_paper_score` PASS with `gate_status=OPEN`,
> floor monitor PASS, tiering PASS. The race is **intermittent, not daily**: it binds only when the
> 07:05 roll is still appending as the chain reads. On 08-02 the chain read ~10:03 and lost; on
> 08-03 it read 09:53 and won. Truncated *on* 08-02, not *since*. Merge the fix on reliability
> merits, not as an outage. Two of the four step names quoted don't exist in the chain.

> **CORRECTION 3, and I made this one myself.** "All 23 steps ok" is **not** "the chain is healthy",
> and I said it was before checking the payloads. Step status says a step EXECUTED; the payload
> carries the verdict. The run terminated `deferred / upstream_pipeline_not_successful` with
> **five steps BLOCK inside `summary`**: `live_variant_settlement_scorecard`,
> `hourly_model_performance`, `ten_minute_model_performance`, `rollup_freshness`,
> `trading_evidence`. `status.ps1` now prints these on their own line (commit `1d287f72`).

**OPEN, and the first thing to look at tomorrow:** `live_variant_settlement_scorecard` reports
`eligible_prediction_coverage = 0.0` and `missing_or_invalid_partition_count = 103564` of 103564,
with `valid_prediction_partition_count = 0`. Zero valid prediction partitions is not obviously an
expected pre-release gate. **Resolve which of these five BLOCKs clear when the release pointer is
created and which are real defects, BEFORE spending the 7-day window.** The standalone
`production_readiness_gate.json` (05:00) reports BLOCK / NOT_READY with 69 blockers led by
`active_release_verification_failed` — that one is definitionally pre-release; several clean-day
blockers (`clean_day_market_count_not_12`, `singular_release_identity`, `capture_slos_pass`) are
structural and do not tick down overnight.

**Post-lock order — mostly unchanged, one demotion:**

1. Delete the **55.31 GB** of taker counterfactual tape (approved). **Before merging the stack** —
   the stack's retention job hashes every candidate at 00:05 and would SHA-256 ~29 GB in one pass.
   Disk is 107.8 GB free falling ~8.2 GB/day (~13 days); this roughly doubles the headroom.
2. Merge the **maker binding fix** (roll 1) — **no longer priority-1**, see correction 2.
3. Merge the **four-commit consolidated stack** (roll 2). Then switch on
   `--disable-counterfactual-tape` for `WeatherTakerBotDailyRoll`.
4. Then the parity-gate branch, bound as a blocking precondition on the base-retrain step — not the
   release path, not during the build window.

**There is no scheduled merge trigger.** `WeatherQuietWindowMerge{,2,3}` are spent one-shots with an
empty `NextRunTime`; all three genuinely failed on 08-01 (the config-drift trap) and the merge was
finished by a manual 02:55 re-run. **Any plan above that assumes the quiet window fires on its own
is assuming a mechanism with no next run — re-register it explicitly.**

**`-08-16a` is gated "DO NOT RUN BEFORE 2026-08-05 04:30" and is a *workstation* mission — nothing
on this host fires it.** It needs the operator relay line. No `-08-16a` branch exists yet. Amended
pre-unblinding: severe-tail SSE primary, max-T gate added, slice tie-break void, 09:00–14:00
directional.

**In flight:** the absorption-waterfall mission (`-09-05a`), dispatched 2026-08-03 — why 78% of an
upstream improvement disappears before it reaches served output. **Its result should gate the
retrain decision** (see §8.1): if the absorption path really does eat most of an upstream gain,
every model-side mission this month has been optimising something that cannot reach served output.

**Unasked question worth a mission.** `maker_paper_score` reports `candidate_input_bytes` 1.37 GB
against `max_input_bytes` 512 MB, `input_budget_trimmed_run_count=11`, `selected_run_count=3` of 14.
**The maker scorer discards ~60% of its candidate input every day**, on the track that outranks
everything else, and nobody has asked what that costs the MM evidence it feeds.

**Also pending:** a provider probe to confirm whether Previous Runs actually serves the 21 profile
fields the PIT corpus plan assumes. It is the plan's least-verified assumption.

**The reboot is NOT as blocked as it looked.** The alarm that justified deferring it was false —
every capture-critical task is S4U with a time trigger and `WeatherBootRecovery` is S4U on a boot
trigger; the only Interactive tasks are the two credential-vault one-shots, which capture nothing
(fixed in `1d287f72`). Capture is *configured* to self-recover but this has **never survived a real
reboot** (uptime 322 h; the S4U fix landed 07-24, last boot 07-21). Do it deliberately in a
01:00–04:00 window after the lock and measure it, then revert the AU policy keys — `AUOptions=2` is
what is actually blocking installs, and it defers security updates for as long as it stands.

---

## 7. How to behave

**Verify before you accept.** Every handback claim that changes a decision gets checked against the
code or the host. This has repeatedly mattered: the workstation corrected two build-critical errors
in a runbook the outgoing session wrote, and the outgoing session caught its own false alarms by
checking rather than reacting.

**Correct yourself plainly and move on.** No preamble, no self-flagellation. Ways the outgoing
session was wrong, so you can recognise the pattern:

- inferred roll-sensitivity from a glob instead of measuring the loaded closure;
- quoted an oracle ceiling as a repair ceiling, and derived a figure from mismatched denominators;
- dispatched a mission a day early, so it could not evaluate anything;
- nearly raised a false alarm from a three-week-stale status file.

The common thread: **asserting from a plausible proxy instead of measuring the real thing.**

**Do not over-claim a mechanism because the story fits.** Three hypotheses were eliminated this month
by measurement, and the intuitive story was wrong every time — blindness even moved the centre in the
*opposite* direction from the defect.

**Act.** You have full authority over commits, pushes, merge timing, scheduled tasks, and the
research agenda. Confirm before irreversible or outward-facing actions — bulk deletion, opening
ports, anything that touches live serving.

---

## 8. Open questions worth fresh eyes

You were recreated partly to see something the outgoing session missed. Candidates:

1. **Is the retrain worth a month?** Honest served payoff is **0 to 5.39%**, interval containing
   zero. We are spending release #1, a PIT corpus (1–2 weeks), and an observation contract on it.
   The absorption mission may raise the ceiling to ~24%. If it does not, is this the right plan?
2. **The primary objective may be the wrong objective.** The 09:00–14:00 slice needs **504+ dates**
   to confirm. The severe tail needs **4**. We named a target we cannot measure — should the
   objective change to match what is measurable, or is that letting the instrument choose the goal?
3. **The market's mode wins ~98% of the time; ours wins ~24%.** That gap has never been attacked
   directly. What does the market know at 10:00 that we do not? Blindness was eliminated as the
   answer. Nobody has asked the question a second way.
4. **Is the model the right lever at all?** The operator's goal is the MM bot. MM pilot economics
   were *positive at settlement before rewards*. Maybe edge comes from execution and inventory
   rather than from beating the market's centre.
5. **4.26% of rows carry 60.2% of the loss.** Everything is scored pooled. What if the whole
   approach should be tail-first?

Bring a real opinion. The operator wants judgement, not a status mirror.
