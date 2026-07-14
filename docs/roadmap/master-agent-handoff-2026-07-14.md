# Master Agent Handoff — 2026-07-14 (~09:20 EDT)

You are taking over as the OPERATIONS MASTER AGENT for this repository
(`c:\Users\micha\Desktop\github\weather`, Windows 11, PowerShell 5.1, venv at
`venv\`). The previous master agent ran out of usage mid-day; this document is
your complete brief. Read it fully before acting.

## Your role

1. **Analysis and direction** — audit system health, decide what needs fixing,
   sequence the work honestly. The operator (user) checks in periodically and
   relays delegate-agent responses to you; he is not watching live.
2. **Work orders** — you write prompts for delegate LLM agents
   (`docs/roadmap/agent-work-order-*.md` are your templates — read
   `2026-07-13c` for the isolation contract). Delegates work in git worktrees
   on their own branches, never in the main worktree. You audit their reports
   against the actual diff before merging. Treat their claims as unverified
   until you check the code and, where possible, live behavior.
3. **Git** — you own commits and pushes proactively (real messages, no history
   rewriting, `data/` stays untracked). Attribute your commits honestly with a
   Co-Authored-By trailer naming your own model.
4. **Cutover actions are YOURS ALONE, never delegated**: scheduler task
   registration/changes, release create/verify/promote/rollback, loop
   stop/start outside sanctioned repair verbs, trading permission changes,
   credential changes, deleting canonical evidence.

## Standing operator constraints (verbatim intent)

- **No backup work.** "We don't need or care about a backup."
- **Disk cleanup deferred** — operator acts himself at 200GB free (currently
  ~318GB; CAS dedup cut the burn rate).
- **Item-206 shim removal is EMBARGOED until 2026-07-18** (execution checklist
  is in the roadmap item; pre-scan clean: 103 shims, zero callers).
- Operator priority: **start live testing ASAP** — but never by weakening
  evidence honesty. Fail-closed over convenient.

## Host facts (HOST_LOAD_POLICY.md is authoritative)

- 15.7GB RAM, 63.7GB commit limit. Memory guard task runs every 5 min
  (`data/logs/memory_commit_guard_status.json`): warns ≥85% commit, kills
  largest ad-hoc python ≥92%, sweeps orphans. Never run tests/heavy work with
  commit ≥70%.
- Protected window 18:00–00:30 (evening MM/taker); quiet window 01:00–08:30.
- Three capture loops (snapshot / CLOB microstructure / observation trigger)
  run 24/7 under per-2-minute supervisor tasks. Sanctioned repair verbs ONLY:
  `python -m weather.collection.snapshot_tracker --restart|--ensure|--stop`,
  `python -m weather.market.market_microstructure restart|ensure|stop`,
  `python -m weather.operations.observation_trigger restart|ensure|stop`.
- **Commits roll the fleet**: supervisors detect stale loaded-module
  fingerprints and restart loops (STALE_CODE). Snapshot restart budget is
  6/24h — it sat at 4/6 this morning. Batch Python-touching commits, prefer
  the quiet window. Commits touching only `scripts/ops/*.ps1` or docs are
  roll-free. Mid-day taker code rolls also quarantine the running paper day's
  tape (fail-closed mixed-lineage rejection) — taker-touching commits belong
  near the 00:05 roll boundary.

## State as of handoff (all verified live this morning)

- **master = `e1d09389`, pushed.** All three delegate branches merged:
  13b hardening (adoption commit `391fb628`), `release-bootstrap-2026-07-13`
  (`ebbf6ad9`: bounded ten-minute scorer, production PIT retrain mode,
  rollback command), `evidence-plumbing-2026-07-14` (`85c28aba`: parity
  evidence generator, registration emitter, experiment executor, worker
  release binding). Post-merge ratchets fixed in `51460b7e`. Window stop fix
  `e1d09389`.
- **Capture fleet healthy**, all loops rolled onto merged code, 0 errors.
- **Training window** (01:00 task, `scripts/ops/training_window.ps1`): aborted
  01:00 today (exit 9001) because loops didn't drain in 90s; timeout now 600s
  with loop-name diagnostics. **Zero retrains have ever completed** — tonight
  is attempt #3 with the first clear runway. Dead-man restore task at 04:15.
- **Item-322 soak: evidence collected, needs recording.** The quarantined
  00:05 taker worker (`data/taker_runs/2026-07-14/_quarantine/
  taker-20260714-9f58e760__20260714T124945Z/run_summary.json`) shows 488
  ticks/8.5h, zero restarts, post-warmup slope 11.6 MiB/h vs 16 budget, zero
  ordinary full-history reads/rewrites, all 10 advisory checks PASS. Record
  this in the item-322 file and close its soak checkbox.
- **Item-324 soak**: the 09:30 `WeatherDailySettlementPromotionRefresh` run
  today is the first automatic pass with the bounded ten-minute scorer. The
  readback checklist is in the item-324 file (exit code vs durable status,
  per-step isolated-child receipts, budget headroom flags at ≥80%). Two clean
  scheduled runs — or one clean + one correctly-terminated budget kill —
  close it. Do NOT launch extra Stage-A runs; do NOT hand-edit statuses.
  After the bounded scorer proves itself, complete the 2026-07-12 settled-day
  barrier via its recorded resume commands (in
  `data/backtest/daily_refresh_status.json` blockers).

## THE decision in flight: bootstrap-first-release (operator informed, ~1 day to veto)

**Finding (verified empirically):** release #1 is deadlocked. A scratch
`prelock-production` over all 47 settled Toronto folders excluded 69,300/69,300
rows with `missing_release_id` — the PIT materializer
(`weather/reporting/validation/point_in_time_evaluation.py`,
`canonicalize_raw_row`) refuses to invent release lineage; rows are only
release-stamped when capture runs under an active release pointer; and
`release_promotion.py` (~line 584) rejects research-only candidates from
promotion. Circular. Item-321's own Phase 0/1 text expects a serving-identity
release #1 to exist FIRST, so this is hardening overshoot, not design intent.

**Agreed plan** (relayed to operator this morning; he had a full day to veto
before any promotion):

1. Implement a minimal `--bootstrap-first-release` allowance on the promote
   path: valid ONLY when no active pointer exists (`existing is None`),
   records explicit provenance (e.g. `release_kind:
   "serving_identity_bootstrap"`) in the pointer/journal and requires the
   reviewed promotion-decision document to declare the same. Tests both ways:
   research+no-pointer+flag → promoted with provenance; research+existing
   pointer+flag → rejected; research without flag → rejected (unchanged);
   production candidates unaffected. `release_promotion.py` and the lifecycle
   CLI are NOT loop-loaded modules — committing them does not roll the fleet.
2. Tonight 01:00: window runs `nightly_retrain` in research mode (default) →
   first candidate.
3. Tomorrow (Jul 15) morning: verify the candidate
   (`release_lifecycle_cli ... verify`), review artifacts, prepare the
   reviewed promotion-decision JSON (schema: decision=PROMOTE,
   gate_status=PASS, release_id, manifest_sha256, candidate_only_build=true,
   reviewed=true, reviewed_by, reviewed_at_utc).
4. Jul 16 00:05 market-day boundary: generate the fresh boundary proof
   (≤900s old, processes quiesced, no open/mixed market-days) and promote
   with the bootstrap flag. Then restart workers onto the pointer
   (coordinated restart = the rollback-drill counterpart), complete the
   rollback drill record, and run the parity evidence generator
   (`python -m weather.reporting.scorecards.captured_input_parity_evidence`)
   once a stamped day exists.
5. From promotion forward: capture/taker/MM stamp release identity (binding
   code verified live today — the taker already stamps
   `research_unbound_non_countable`); countable live-forward paper evidence
   begins; after 14 contiguous stamped Toronto days (~Jul 30) the first
   PRODUCTION candidate can qualify through the full PIT machinery.
6. Re-registration of the three chain tasks under the new contract uses
   `python -m weather.reporting.serving_gates.registration_parameters`
   (fail-closed; needs verified release + parity pairs per routed market).

**Promotion mechanics traps (read before promoting):**
- Promote requires a CLEAN git tree AND current HEAD == the candidate
  manifest's `code.git_commit`. Therefore: land ALL of today's commits
  (bootstrap code, item-322/324 notes, this handoff) BEFORE tonight's 01:00
  window builds the candidate, then FREEZE commits until promotion completes.
- `config/location_market_events.json` + `config/locations.json` are
  auto-regenerated every 6h (WeatherLocationConfigRefresh, fires ~00:00) and
  will dirty the tree minutes before the 00:05 boundary. At promote time:
  `git checkout --` the two config files, promote, then immediately re-run
  the refresh task (stale location config blacked out capture once before —
  see memory `location-config-refresh-gap-2026-06-29`).
- The candidate build must set `rollback_target: null` (no prior release);
  verify this in the manifest before promoting.
- Do not promote a candidate whose git commit is dirty-attested.

## Today's remaining sequence (in order)

1. ~10:30–13:00: review the 09:30 Stage A run against the item-324 checklist.
2. Implement + test the bootstrap-first-release path (yours, not a delegate's
   — it is a safety-gate change and a cutover prerequisite).
3. Record item-322 soak evidence in its item file.
4. Commit everything in ONE batch (fleet rolls once at most; before 18:00
   protected window, and strictly before 01:00).
5. Verify tonight at/after 01:00 if still active: `data/logs/
   training_window.log` should show stop → gate-confirmed inactive → retrain
   start. If capture doesn't drain in 600s the log now names the loop.
6. Check `WeatherMarketMakingDailyRoll` 19:30 and taker 00:05 rolls happen
   normally under the merged code.

## Verification habits that kept this system honest

- Never trust a green summary: read the durable status JSON, check PIDs are
  alive (`Get-CimInstance Win32_Process`), check supervisor sidecars
  (`data/snapshots/*_supervisor_status.json`).
- "interrupted + terminal:true" with `current_step.status=running_isolated`
  and a live child = RUNNING (pessimistic pre-child receipt), not failed.
- Admission deferrals are honest, not bugs. Budget kills that terminate
  in-container are the containment WORKING.
- Watch `pid_match_mode: launcher_parent` in Stage-A child receipts (venv
  shim one-hop acceptance) — that fix is `34807b4a`.
- PowerShell 5.1: no `&&`, no ternary, no `??`. Task XML: never
  `[TimeSpan]::MaxValue`.

## Key reference paths

- Policy: `docs/operations/HOST_LOAD_POLICY.md`,
  `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md`,
  `docs/operations/package-boundaries.md`
- Program: `docs/roadmap/items/item-321-...staged-release-program.md`
  (+ items 322/323/324)
- Work orders + delegate reports: `docs/roadmap/agent-work-order-*.md`,
  `docs/roadmap/agent-report-*.md`
- Statuses: `data/backtest/daily_refresh_status.json`,
  `data/backtest/nightly_retrain_status.json`,
  `data/logs/training_window.log`, `data/snapshots/*loop_status.json`,
  `data/logs/memory_commit_guard_status.json`
- Session memory (if you are a Claude Code session): the auto-memory index at
  `C:\Users\micha\.claude\projects\c--Users-micha-Desktop-github-weather\
  memory\MEMORY.md` — read `item-321-cutover-audit-2026-07-12` and
  `commit-triggered-fleet-rolls` first, and keep memory updated as you work.

Delegate parallel work freely (worktree isolation, no-touch lists, focused
tests under commit<70%), but remember: analysis, sequencing, git, and every
cutover action stay with you.
