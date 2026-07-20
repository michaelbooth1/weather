# Master Agent Handoff — 2026-07-20 (~10:00 ET)

You are taking over as the operations master agent for this repository:
analysis, direction, work-order composition for delegate agents, audits of
their branches, git authority, and host operations. The operator (Michael)
relays delegate completions to you; you audit, merge, and run the runtime.
Repo: `c:\Users\micha\Desktop\github\weather` (Windows 11, PowerShell 5.1,
venv at `venv\`). Persistent memory for this project lives in the Claude
auto-memory directory and is loaded each session — trust it, it is current
as of this handoff.

## Top goal

**A model that beats the market.** Everything routes through one gate: the
first production release candidate requires a **contiguous 14-day run of
complete-grade Toronto market-days** (the "streak clock"). Streak day 1 =
2026-07-18 (Jul 17 was lost to my own midday merge rolls — see hard rules).
Day 3 (Jul 20) is collecting now. Earliest lockable ≈ Aug 1. When 14 days
exist: re-run the prelock probe (pattern in
`data/analysis/point_in_time/probe_2026-07-16_window_short_10of14/`, exclude
the 7 June duplicate-replay folders: Jun 17,18,19,20,22,25,28), stage the
source trio into `data/analysis/point_in_time/production_source_2026-07-16/`
(exact dir name `scripts/ops/training_window.ps1` arms on), and the 01:00
window runs `--bootstrap-first-inactive-release` automatically. The nightly
training window itself is PROVEN (three clean nights: capture stop confirmed
in ~1 s, retrain runs and exits "blocked" by design until armed, capture
restored, ~30 s total).

## URGENT — time-sensitive items you must own immediately

My session held two session-only scheduled jobs that DIED with my session.
Execute them yourself:

1. **Attestation live-fire check (after 14:00 and/or 17:00 today).** The
   daily tasks were re-registered this morning under the new delegated_child
   wrapper (work order 19b, merged `4ac529f9`, then
   `& .\scripts\ops\register_daily_refresh.ps1 -ProvenanceOnly` was run —
   both tasks Ready). After a Stage B fallback fires (14:00/17:00), read
   `data/backtest/daily_refresh_evidence_status.json` →
   `invocation.scheduler_attested` should be **true** with topology
   `delegated_child`; the run itself still SKIPs on
   `stage_a_not_completed` (expected until item 2 lands). If attested is
   false, capture `invocation.blockers` verbatim and debug against
   `scripts/ops/daily_refresh_contract.ps1` token construction BEFORE
   tomorrow's 09:30 Stage A.

2. **Quiet-window merge of 19a at ~01:02 tonight (2026-07-21).** Work order
   19a (maker scoring projection) is FULLY AUDITED and mergeable: branch
   `maker-projection-2026-07-19` (worktree
   `..\weather-maker-projection-2026-07-19`), implementation `d587c9a4`,
   report `cf8d456b`; I re-ran 233 tests + 4 subtests green; policy diffs
   clean; byte-equivalence proven. It MUST NOT merge in daytime: it touches
   `src/weather/schema_registry_recent_data.py`, which ALL THREE capture
   loops load — a daytime push rolls them mid-collection and risks the
   streak (that exact mistake reset the clock on Jul 17). At ~01:02 (after
   the training window closes ~01:00:30 and Toronto day 3 is sealed):
   1. Verify `data/logs/training_window.log` shows tonight's window closed
      and loops restored.
   2. `git merge --no-ff maker-projection-2026-07-19` + push.
   3. Run the backfill (idempotent, skip-existing):
      `venv\Scripts\python.exe -m weather.market.mm_scoring_projection backfill`
      — record per-run results and the projected/canonical ratio.
   4. Resume the July-18 barrier:
      `venv\Scripts\python.exe -m weather.operations.daily_refresh run
      --fail-on-variant-evidence-alert --continue-on-error
      --evidence-task-name WeatherEveningEvidenceRefresh --stage settlement
      --settled-analysis-target-date 2026-07-18
      --resume-from-step maker_paper_score --heavy-step-subprocess
      --stage-a-min-available-reserve-mb 1536
      --stage-a-max-commit-percent 70.0` — DEFAULT 14-run window, no
      overrides.
   5. Then the same for `--settled-analysis-target-date 2026-07-19`.
   6. Expect the defer/resume dance (below); loops will re-adopt the new
      code via supervisor rolls in the predawn hours — that is fine.
   If you are reading this AFTER 01:02 passed without execution, do it in
   the NEXT quiet window (01:00-04:00); do not do it midday.

## Why 19a matters this much

Since 2026-07-16 the canonical maker tapes are provenance-fat by design
(runtime-identity/lineage stamped on every variant row — required for PIT
countability; NEVER strip it) and runs are 75-217 MB each, so the 512 MiB
maker input preflight fails at ANY window size. That single BLOCK
hard-stops every settled-day barrier from Jul 18 onward
(`post_label_maker_evidence`) AND keeps Stage B skipping
(`stage_a_not_completed`), which has starved `daily_learning` rollups since
Jul 10. 19a fixes it with a compact 69-column scoring projection
(`mm_scoring_projection_v0.1`, ~10-25% of canonical bytes) + fail-closed
canonical fallback + backfill CLI. Caps stay untouched — never raise the
512 MiB input, 4 GiB private, or 3 GiB working-set caps
(HOST_LOAD_POLICY forbids it; the "row doubling" scare was diagnosed as
under-capture on Jul 15, not a defect — constant 132 rows/tick).

## Current settled-day scoreboard

- **Certified complete + countable: Jul 14, 15, 16** (barrier zero
  blockers each).
- Jul 17: `partial` forever (my midday rolls) — new streak base.
- Jul 18, 19: labels complete; barriers maker-blocked → unblocked by the
  01:02 plan above.
- Jul 12, 13: `partial` forever. Jul-12 completion was DROPPED — it can
  never count; do not spend roll-risk on it.
- Known open BLOCKs that are HONEST MODEL VERDICTS, not ops debt: hourly /
  ten-minute skill gates (model trails market, esp. early hours) — that is
  the thing the learning loop exists to fix. Do not chase them as bugs.

## Hard operational rules (each learned the hard way)

1. **Roll-sensitive merges ONLY in the 01:00-04:00 quiet window.** Before
   ANY merge, check the diff against each capture loop's loaded modules
   (`managed_process.runtime_identity.source_scope_files` in each loop
   status; snapshot: `weather.collection.snapshot_tracker.LOOP_STATUS_PATH`,
   clob: `weather.market.market_microstructure.CLOB_LOOP_STATUS_PATH`,
   observation: `weather.operations.observation_trigger.STATUS_PATH`).
   ps1/docs/config/tests-only commits are roll-free and can merge anytime
   (that is how 19b merged same-day).
2. **Never raise resource caps to force a run through.** Bound the step or
   shrink its input instead. All five chain memory-killers were fixed by
   streaming rewrites (permission map, ten-minute, hourly, maker-paper,
   taker watchdog, tail casebook) — the in-tree reference implementations
   are `hourly_model_aggregation.py`, `mm_paper_aggregation.py`,
   `taker_bot_aggregation.py`.
3. **Never hand-edit** status JSON, replay manifests, tapes, ledgers, or
   generated backlogs. Data restoration goes through repository CLIs.
4. **The defer/resume dance is NORMAL.** Chain runs frequently end
   `deferred` with `interruption.reason=post_step_capture_or_physical_check_failed`
   (a supervisor roll makes a loop heartbeat momentarily stale) or
   `resource_admission_blocked`. Read
   `data/backtest/daily_refresh_status.json` → `interruption.resume_command`
   and relaunch it verbatim (detached:
   `Start-Process ... -WindowStyle Hidden -RedirectStandardOutput/Error`,
   then `Wait-Process` in a background task). Heavy steps need ~4.5-4.8 GB
   available physical; the ChatGPT desktop app respawns into the tray and
   eats ~700 MB — the operator authorized killing it
   (`Stop-Process -Name ChatGPT -Force`).
5. **A "dead" loop right after a roll may be mid-revival**: the fresh
   worker's startup fleet pass delays its first status write by minutes.
   Look for a younger worker process before escalating; the sanctioned
   revive is `schtasks /run /tn WeatherSnapshotLoopSupervisor` (or clob/
   observation equivalents). Stop verbs now work under both python/pythonw
   (fix `c4c4092b`).
6. **No promotion, live trading, or capital.** The learning path is the
   INACTIVE bootstrap release; promotion stays forbidden until proven edge.
   No Box / off-machine backup until the model proves value. Preserve all
   tapes/ledgers/evidence; no cleanup without operator instruction.
7. Git: proactive commits/pushes with real messages; never rewrite
   published history; `data/` stays untracked; commits end with the
   Claude Fable co-author line.

## Delegation pattern (how this project actually moves)

You write work orders in `docs/roadmap/agent-work-order-YYYY-MM-DD*.md`
(read 2026-07-16/17/19 ones as templates: isolation in a NEW worktree
branch off master, focused tests under commit_percent < 70, no
scheduler/loop/release/data actions, no merge/push, report file required).
The operator hands them to delegate agents and relays completions. You then:
read the report, diff the branch, spot-check the subtle seams, re-run their
focused suites yourself in THEIR worktree, check loop-module overlap, then
merge (quiet window if roll-sensitive) and run any adoption-day actions
(backfills, registrations, barrier resumes) yourself.

## Queue after the urgent items

1. **Verify tomorrow's 09:30 Stage A**: attested + projections under cap +
   barrier pass + Stage B completes on the 14:00/17:00 trigger → first
   fully-clean day. Then the chain needs no daily babysitting.
2. **Item-206 shim removal** (was due Jul 18, embargo lifted, pre-scan
   clean: 103 shims, zero callers). Roll-sensitive src removal → quiet
   window, AFTER 19a is merged and stable. Check for conflicts with any
   open delegate branch first.
3. **Disk**: ~226 GB free on Jul 20 morning, burning 3-4 GB/day (fat
   canonical tapes). Operator-owned cleanup threshold is 200 GB → he needs
   to schedule his pass within ~a week. Remind him; do NOT delete anything
   yourself.
4. **Tape backup** has been dead since ~Jul 11 (PT2H task limit kill,
   0x41306). Known, unfixed, deliberately deprioritized; revisit after the
   streak locks.
5. **Streak watch**: protect capture above all routine work. Every day
   Jul 18 → Jul 31 must grade complete. If a day goes partial, the clock
   resets again — nothing else on this list is worth that.
6. When the streak locks (~Aug 1): prelock probe → stage the trio → the
   window bootstraps release #1 (inactive) → parity/qualification ladder →
   only then does promotion discussion begin, evidence-first.

## Key artifacts and receipts

- `data/backtest/daily_refresh_status.json` — single-slot latest chain run;
  `interruption.resume_command` is your resume path.
- `data/backtest/daily_refresh_evidence_status.json` — Stage B (separate
  slot); `stage_gate.skip_reason` explains skips.
- `data/backtest/settled_day_freshness.json`, `market_day_labels.csv` —
  per-day grades/countability (Toronto rows = the streak).
- `data/backtest/fleet_observability.json` — alerts, cadence proofs,
  countability.
- `data/logs/training_window.log` — nightly window outcomes.
- `docs/roadmap/agent-report-2026-07-19a.md` / `-19b.md` — the two branches
  you are adopting tonight/verifying today.
- Recent master: `4ac529f9` (19b merge) > `c4e88aad` (work orders) >
  `c4c4092b` (stop-verb fix) > `4a37b3ed` (17b casebook) > `026bdb57`
  (17a watchdog) > `65ecfa2a` (16b maker) > `10d4b586` (cutover).

Everything here is also reflected in the auto-memory files (streak-clock
memory is the master index of current state). Good luck — the plumbing is
finally solid; protect the streak and ship release #1.
