# 324. Bounded Daily Settlement Refresh Resource Admission And Step Isolation [PARTIAL 2026-08-22 - WORKFLOW REPAIR ADOPTED; FIRST TERMINAL MORNING RECEIPT PROVED]

Goal: keep the scheduled settlement refresh inside explicit per-step memory,
physical-RAM, commit, runtime, and input-size budgets so truth finalization can
run alongside capture without starving or falsely destabilizing the live loops.

Owner/package: weather.operations, weather.market, weather.reporting

Source: the final boundary of the 2026-07-13 12-hour runtime monitor. The
scheduled Stage-A refresh worker grew from 2,250.7 MiB private memory at
13:46:56Z to 13,992.8 MiB at 13:47:56Z while the host fell from 2,698.0 MiB to
416.7 MiB physically available. It later reached 19,934.3 MiB private memory.
The sharp rise began in `taker_edge_permission_map`, whose current path reads
complete order tapes into one aggregate row list, and the following in-process
`maker_paper_score` retained or added another full-history materialization.
Physical availability reached 305.4 MiB at the monitor boundary, the
observation loop recycled under pressure, and a shell/CIM taker liveness probe
produced a false `pid_missing` status even though the exact taker tree remained
alive and kept writing countable paper evidence.

Immediate incident handling preserved data: the owning scheduled settlement
task was stopped at 14:02:30Z after its worker exceeded 19.9 GiB private memory;
commit returned from roughly 76% to 47% and physical availability recovered
above 6 GiB. The repository's `repair-stale-locks` command then verified both
recorded owner PIDs were dead before removing the daily-refresh and long-job
locks and clearing their stale state. No tape, ledger, label, or captured input
was deleted. Items 285 and 260 own the edge-permission and maker-paper
semantics; this item owns their bounded orchestration on the capture host.

Why this matters: Stage A is an approved heavy window, but approval of the
schedule is not a memory budget. Its in-process address space crosses many
independent corpus steps, so one full-history materialization can retain a high
water mark and the next can push a healthy capture host into paging without
ever crossing the commit-only guard threshold. Items 205 and 298 own pipeline
structure and scheduling, and Item 321 owns production readiness; none proves
per-step physical-memory safety, process isolation, or interruption-safe
resume for the settlement chain.

## Scope

- [ ] Inventory every settlement-stage step's input cardinality, peak private
  memory, peak working set, elapsed time, and read/write volume. Classify heavy
  steps explicitly rather than applying admission only to later promotion
  work.
- [x] Replace full-list taker order-tape aggregation with streaming or bounded
  per-slice statistics while preserving deterministic permission records,
  source-artifact lineage, settled-order counts, and independent-day logic.
- [x] Give maker-paper scoring an explicit evidence-window/input-byte contract.
  A full-history rebuild must be a separately admitted maintenance operation,
  not the ordinary daily settlement path.
- [x] Run high-risk Stage-A steps in isolated subprocesses with declared
  timeout and working-set/private-memory limits. Release one step's address
  space before starting the next, and fail closed without promotion when a
  child exceeds its budget.
- [x] Gate each heavy child on both commit and physical availability, then
  re-check capture-loop freshness before and after it. A commit-only gate is
  insufficient: this incident reached 98% physical load at only 69.7% commit.
- [x] Persist `current_step`, child PID, resource budget, and last progress
  before invocation. On task stop, native failure, or resource rejection,
  write an interruption-safe terminal status and exact bounded resume command
  instead of leaving `status=running` with only the prior completed step.
- [x] Surface Stage-A resource peaks, budget decisions, child exit reasons,
  stale-lock repair provenance, and capture impact in daily-refresh status,
  fleet observability, and the memory guard without authorizing generic
  termination of arbitrary `weather.*` processes.
- [x] Prove the scheduled task's normal and resource-blocked exit codes match
  its durable status, and that retry/resume cannot duplicate or discard
  settlement evidence.

Acceptance: an ordinary settlement refresh over the representative current
corpus completes with every heavy step under its declared resource budget and
with capture loops fresh; deliberately oversized fixtures are rejected or
terminated in an isolated child before host pressure affects capture; taker
edge-permission and maker-paper outputs remain semantically equivalent; an
interrupted run has a terminal durable status plus exact safe resume point;
and a production-window soak shows bounded memory between steps with no manual
process or lock cleanup.

2026-07-13 immediate containment landed after the monitor stopped. Taker
edge-permission statistics are now accumulated per permission cell in one pass
and order tapes are yielded one at a time, removing the complete-corpus row-
dict retention that triggered the 14 GiB surge. The scheduled maker-paper step
now selects only the latest 14 active-day runs, records its selected inputs,
and fails closed before loading them when quote plus variant CSVs exceed
512 MiB; both limits have explicit CLI overrides and are persisted in refresh
configuration/status. Focused aggregation/lazy-loading and maker preflight
tests pass, as do compile and diff checks. Per-step subprocess isolation,
physical-memory admission, interruption-safe terminal status, and a production
soak remain open; at the user's stop instruction no live settlement rerun was
started.

Later on 2026-07-13, the remaining code-side containment landed. Every Stage-A
step now has an explicit resource classification; the corpus-owning subset runs
through the existing isolated-subprocess/Windows Job Object machinery with
per-step timeout, private-memory, and working-set ceilings. The parent requires
available physical RAM equal to the child's working-set ceiling plus a 1.5 GiB
capture reserve and checks live-loop freshness before and after each child.
Before user code resumes, daily-refresh status contains the current step, child
PID, budget, last progress, and an exact bounded resume command while the
top-level state is deliberately terminal/resumable. This makes a parent kill or
native death recoverable without leaving `status=running`. Child resource peaks
and admission decisions flow into daily-refresh and fleet-observability JSON and
Markdown together with elapsed time, lifetime process-tree read/write bytes,
and bounded result cardinality/byte fields. Focused resource/status tests pass;
the CLI test exercises the actual command handler and matches normal/deferred
exit codes to the status it writes, while terminal-manifest recovery advances
only after schema/step/PID validation and preserves the completed step result.
The representative scheduled Stage-A soak and measured inventory values remain
open and must not be inferred from unit tests.

The ten-minute scorecard follow-up reduces checkpoint rows market-day by
market-day instead of retaining the full multi-week scored corpus. After this
bounded scorer change is adopted, the 2026-07-12 settled-day analysis completes
through the barrier's recorded resume commands for
`ten_minute_model_performance` and `maker_paper_score` with
`--settled-analysis-target-date 2026-07-12`; the barrier status must not be
hand-edited to substitute for that recorded step evidence.

## 2026-07-13b scheduled-soak checkpoint

The 2026-07-13 scheduled task remains non-countable soak evidence. Its Task
Scheduler result is `267014`, and the only genuine new resource row is the
17:11 UTC `hourly_model_performance` admission rejection. The snapshot loop's
first post-restart iteration still had one real isolated-child exit-137 error,
so the gate correctly deferred before launching the child. Earlier steps were
carried forward without new subprocess resource receipts. This proves neither
a clean scheduled run nor budget enforcement under load.

Four later `hourly_model_performance` attempts at 18:41, 18:44, 18:49, and
18:55 UTC came from a separate user-owned Claude Code session, not the 09:30
scheduled task and not this work order's execution. The first three deferred
at admission. The fourth admitted an isolated child whose process returned
zero but whose terminal manifest failed validation, so the run ended `error`.
They remain durable operational evidence but are excluded from scheduled-soak
counts.

## 2026-07-14 scheduled-soak readback - non-countable

The 2026-07-14 09:30 scheduled run is safety evidence but does not count toward
the soak. Two agent-owned `rg` searches traversed ignored `data/` at startup,
driving antivirus/CPU load and delaying the scheduled interpreter's entry into
the daily-refresh CLI until 09:46. The worktree also changed while the run was
active. The invocation's durable producer attestation therefore reported
`scheduler_contract_missing`, `scheduler_attested=false`, and
`mode=manual_or_unverified`; it cannot prove scheduler correlation internally.

The only clean isolated receipt was `ingest_quality_gate`. It completed in
14.694 seconds with `pid_match_mode=launcher_parent`, containment and terminal
validation `PASS`, and before/after admission decisions `ADMIT` with zero
blockers. Its lifetime resource evidence was:

- private peak 1,506,394,112 bytes against a 2 GiB ceiling (70.147%);
- working-set peak 256,155,648 bytes against a 1.5 GiB ceiling (15.904%);
- lifetime read/write bytes 461,357,152 / 888,362.

The resource row is retained in `data/backtest/daily_refresh_status.json`; its
child argument and result manifests are under
`data/backtest/daily_refresh_step_children/2026-07-14T134615.508266_0000-57976/`.

No ingest metric reached the 80% review threshold. Its 30-minute timeout and
working-set ceiling are grossly above this one observation and require review
after representative clean receipts; one low sample is not authority to
tighten them.

Two steps classified as in-process invalidated the run before the next
isolated child. `public_wu_settlement_restore` took 898.459 seconds and rebuilds
full retained WU history even though network fetches target one day. Live
whole-parent samples reached approximately 3.25 GiB private memory and
1.75 GiB working set while available physical RAM fell to approximately
1.26 GiB, below the 1.5 GiB capture reserve. These are sampled lower bounds,
not a durable child receipt.

The snapshot loop restarted for stale code, entered its restart circuit, and
later died. An explicit recovery restart's first catch-up pass recorded
Miami/Seattle child exit 137 errors. Capture was therefore not continuously
fresh or impact-free. `taker_finalization_watchdog` then retained repeated
full current-day order/counterfactual materializations and the seven-strategy
bakeoff in the parent. Last-observed lower bounds before emergency intervention
were 5,792,079,872 private bytes and 4,118,310,912 working-set bytes, with only
617 MiB physically available. The operations owner manually stopped the
scheduled task to protect capture.

Task Scheduler recorded `267014` (externally terminated). The canonical
`repair-stale-locks` command verified the owner PID was dead, removed both the
daily-refresh and long-job locks, and wrote `status=interrupted`,
`terminal=true`, with the exact bounded resume point
`--resume-from-step taker_finalization_watchdog`. Both locks were absent after
repair. The daily-refresh Markdown report and settlement-stage manifest remain
the stale 2026-07-13 versions because this run never reached fleet
observability. The numerical scheduler result is consistent with an external
stop, but this path does not prove the normal or self-terminated CLI exit-code
contract.

This run supplies neither a clean scheduled pass nor an isolated budget kill.
All scheduled-soak checkboxes remain open.

### Corrective containment required before the next countable run

- `public_wu_settlement_restore` runs as an isolated child with a 60-minute,
  4,096 MiB private-memory, and 2,560 MiB working-set ceiling. Admission
  requires 4,096 MiB physically available, including the 1,536 MiB capture
  reserve.
- `taker_finalization_watchdog` runs as an isolated child with a 60-minute,
  5,120 MiB private-memory, and 2,048 MiB working-set ceiling. Admission
  requires 3,584 MiB physically available, including the capture reserve.
- WU raw payload, daily summary, and manifest publication must be atomic, and
  an existing raw filename must parse as valid JSON before `skip_existing`
  treats it as reusable. A budget kill must leave the previous valid artifact
  or a refetchable absence, not a filename-valid truncated payload.
- Taker-derived JSON publication must be atomic, and bakeoff freshness must
  require valid JSON with the expected schema. A terminated child must resume
  from raw tapes instead of accepting a newer truncated derived artifact.

These limits are fail-closed containment ceilings. In particular, the
watchdog ceilings are intended to terminate today's oversized shape before it
repeats the physical-memory incident; their existence does not prove that the
current corpus completes within budget. The first isolated receipts must be
compared with the 80% thresholds before any adjustment.

The readback checklist for each next scheduled 09:30 run is therefore still
open:

- [ ] Scheduled-task exit code equals the durable terminal status.
- [ ] Every declared Stage-A step has elapsed, lifetime read/write, peak
  private, and peak working-set evidence or an explicit pre-launch defer.
- [ ] `taker_edge_permission_map`, `maker_paper_score`, and every resumed
  corpus-owning step from positions 11–15 have isolated-child receipts.
- [ ] Each receipt is compared with its declared timeout/private/working-set
  ceiling; results at or above 80% are flagged and grossly oversized budgets
  are reviewed before any tightening.
- [ ] Capture admission is healthy before and after each heavy child.
- [ ] Two consecutive clean scheduled runs, or one clean run plus one correctly
  terminated budget kill, are recorded before the soak checkbox closes.

No extra full-stage run is authorized for this checklist. The 2026-07-14
readback above is non-countable; the next eligible readback is the next
scheduled 09:30 run after the corrective containment lands and capture is
stable.

## 2026-07-15 scheduled receipt readback - non-countable

The first requested post-gate receipt is fresh and terminal, but it does not
count toward the soak. Task Scheduler recorded the 09:30:01 local occurrence,
result 2, and the next daily trigger for July 16. The installed action still
uses a 20-hour task limit and omits `--scheduler-task-name`,
`--scheduler-task-executable`, and `--scheduler-task-working-directory`.
Run `2026-07-15T133008.086105_0000-47292` began seven seconds after the task
timestamp and finished at 09:33:42 local after 214.793 seconds, but timestamp
correlation is not producer attestation. Its durable invocation records
`scheduler_contract_missing`, `scheduler_attested=false`,
`mode=manual_or_unverified`, blocked task correlation, and blank task identity.

The settlement manifest is terminal `DEFERRED` for target 2026-07-14 and never
reached its barrier. Four of the exact 23 Stage-A rows materialized: reanalysis,
ingest quality, and event-metadata validation completed, then
`public_wu_settlement_restore` deferred before child launch. Steps 5 through 23
did not run. The progress total of 24 is the 23-step registry plus the separately
declared production-readiness gate; it is not a 24th Stage-A step. Of the 16
declared isolated steps, only `ingest_quality_gate` has child argument and
result receipts under
`data/backtest/daily_refresh_step_children/2026-07-15T133008.086105_0000-47292/`.

That one child is clean isolation evidence. It returned zero in 13.442 seconds,
did not time out, passed terminal validation and Windows job containment, and
left no active or terminated process in the job. Peak private memory was
1,505,812,480 of 2,147,483,648 bytes (70.12%); peak working set was 258,355,200
of 1,610,612,736 bytes (16.04%); elapsed time was 0.747% of its 1,800-second
ceiling. No measured ceiling reached the 80% review threshold. Lifetime
read/write was 461,368,763/888,362 bytes; that receipt configured no I/O
ceiling.

The public-WU pre-launch admission correctly failed closed with 4,270,419,968
bytes available against 4,294,967,296 required, a 24,547,328-byte shortfall.
No child started, no resource limit fired, and no process was terminated, so
this was a resumable admission defer rather than a budget kill. The bounded
resume point is `public_wu_settlement_restore`. Scheduler result 2 is
semantically consistent with the root `deferred` mapping, but the receipt has
no durable root `exit_code` field; only the ingest child's return zero is
directly recorded.

Lock proof passed with no stale or forced repair, both runtime lock files are
absent, and the long-job state is inactive/complete. Snapshot, CLOB, and
observation capture were healthy and fresh before and after the child and at
the defer. At readback, exact snapshot PID 35100 remained on the same process
instance and command at loaded/current identity `713692de26ea` /
`4867a3ef74fe4668`, iteration 903, and zero consecutive errors. No extra run,
resume, task repair, loop control, or evidence rewrite was performed. This is
the first of the two requested receipt inspections, but it contributes zero
countable runs and no budget-kill lane; every soak checkbox remains open.

Verification:

- Focused streaming-equivalence tests for taker edge-permission aggregation.
- Focused daily-refresh subprocess, resource-cap, interruption, status, and
  resume tests on Windows-compatible process abstractions.
- Representative bounded-corpus maker-paper parity and peak-memory regression.
- A scheduled Stage-A paper soak reporting each child PID, input bytes,
  private/working-set peak, duration, host physical/commit minima, capture
  freshness, exit status, and lock state.
- `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`.

Related: items 95, 171, 205, 260, 285, 298, 321, 322.

## 2026-08-19 backfill-containment repair

The August 16 recovery established the defect with real timings: settlement
restore and finalization completed, but the generic resume continued through
unrelated scoring and storage work until its hard teardown. Cleanup did not
run, stale locks remained, and August 17 refused on file existence. Windows
then reused the recorded PID for an unrelated process, proving PID liveness is
not lock ownership.

- [x] Add an inclusive `--stop-after-step` daily-refresh contract and require
  every selected step to finish `ok`.
- [x] Make one-date backfill stop normally after
  `market_day_labels_finalize`, suppress downstream publication/readiness, and
  verify finite real settlement values across every market ledger.
- [x] Bind daily-refresh and long-job locks/state to PID plus process creation
  identity, fail closed on unreadable identity, and protect replacement locks
  during release.
- [x] Give direct recovery and tiering launches kill-on-close child-tree
  containment, bounded runtimes, atomic latest status, and append-only history.
- [x] Pass the combined immutable full suite and guarded production adoption.
- [ ] Recover August 17 through the new bounded path and prove normal lock
  release, 12/12 real settlement, current capture, and no downstream work.

The implementation is prepared on an isolated branch. It is not production
proof and must not be used to relabel the failed August 19 wrapper receipt.

## 2026-08-21 overnight workflow audit repair

Three consecutive scheduled Stage-A runs reached the absolute 11:55 teardown
without a terminal manifest. The August 21 trace proved the parent had already
finished 23 recorded steps and then entered the nominally in-process
`fleet_observability` tail. That tail still contained both the full historical
audit, the growing `score_all_markets` settled-tape replay, and runtime-identity
evidence that scanned every snapshot tape before filtering, so calling it a
light status read was false. It also redundantly enumerated every MM/taker run
after Stage A had already produced current trading evidence.

- [x] Isolate the scheduled fleet tail in a 20-minute child with 3,072 MiB
  private and 2,048 MiB working-set ceilings, plus the existing pre-child
  resumable checkpoint and terminal validation.
- [x] Make the scheduled fleet mode explicitly omit the separately admitted
  historical audit, full settled-tape trust replay, and runtime-identity tape
  replay, plus the duplicate all-run MM/taker summaries, recording each
  omission rather than manufacturing evidence.
- [x] Bind the exchange-economics barrier dependency to its explicit
  `settled_analysis_target_date`; its current operating date is deliberately D
  while settlement analysis is D-1.
- [x] Accept the exact one-hop Windows venv launcher relationship during stale
  child-terminal recovery, matching the already enforced live child contract.
- [x] Publish Stage-A manifest/trigger disposition atomically and turn any
  required-manifest publication failure into durable terminal error status.
- [x] Replace the impossible immediate/14:00/17:00 Stage-B topology with one
  disabled-by-default 00:35 contract whose target is independently derived
  from the expected prior morning, whose wrapper tears down by 09:00, and whose
  Scheduler limit leaves cleanup margin.
- [x] Pass focused composition tests, the exact full suite, and guarded
  production integration.
- [ ] Obtain a representative scheduled 09:30 receipt that terminalizes before
  11:55 and a separately authorized Stage-B resource proof before enabling its
  established monolithic workload hold.

These changes make refusal and timeout terminal and attributable. They do not
claim that the omitted historical/trust/runtime-identity/MM-taker work ran,
that Stage B is resource-safe to enable, or that the representative scheduled
soak has passed.

## 2026-08-22 production adoption and first scheduled readback

The workflow repair passed its immutable integration preflight and all 357
tracked pytest files in 18/18 bounded chunks, then published source tip
`5d8e94e0d882d13ec3b8bfd71df9f474466d5528` through guarded merge
`cfdad9e5225f4dad86eaeddae7631893cd6c5350`. The PASS merge receipt binds the
exact suite, local/remote master equality, source ancestry, and current
three-worker capture recovery.

The first production 09:30 run on that code published
`daily_refresh_stage_manifest_v0.1` with `status=COMPLETED`,
`inside_sla=true`, and completion at 11:30 local after 7,229.282 seconds. The
formerly unbounded `fleet_observability` tail returned `ok` in 13.777 seconds.
Its scheduled payload records `SKIPPED` for the historical audit, trust replay,
runtime-identity replay, and duplicate trading replay instead of presenting
those omitted evidence families as current. The Stage-A trigger disposition is
terminal `SKIPPED` because the scheduled task deliberately disables the held
Stage-B trigger.

This readback proves that the repaired scheduled tail terminalizes before the
11:55 teardown; it is not yet the clean representative soak required by
acceptance. The run repaired two stale locks and its settled-day barrier
correctly remained `BLOCK` on exchange-economics and maker-paper evidence, so
Task Scheduler returned 2. Stage B remains disabled and still lacks its
separately authorized monolithic resource proof. The compound Stage-A/Stage-B
checkbox above therefore remains open.

The canonical projection and raw-tape tiering tasks also produced durable
`OK` status at 05:00 and 06:00 within their respective runtime bounds and
without reaching a hard stop. August 17 settlement recovery remains open; no
ordinary chain result or successful tiering receipt substitutes for the
required bounded 12-market backfill proof.

## 2026-09-01 one-date retry reliability repair

The August 30 one-date attempt ran at 00:35 on September 1 and failed before
the recovery chain. Its immutable receipt is `REFUSED`; stderr proves the
inline `python -c` market-registry program reached Python only as the token
`import`, which raised `SyntaxError`. Task Scheduler recorded result 2. A
configured Scheduler restart did not create a second run, so neither inline
program text nor `RestartOnFailure` is a reliable unattended retry contract
for this path.

The prepared repair moves authoritative fleet discovery behind the canonical
`weather.operations.settlement_backfill_registry` module and rejects any
module path outside the current checkout. A new registrar creates one exact
primary plus one separate receipt-driven successor, refuses a second pair for
the same target date while either task is running or still due, keeps both
triggers inside 00:30-09:00 with at least 30 minutes between them, omits late
catch-up and Scheduler retries, and attests the registered actions, principal,
triggers, and settings. Inert historical tasks remain evidence and do not
freeze a later reviewed attempt. The successor
skips an already settled date, refuses running, mis-bound, missing,
unattributable, or ambiguous primary evidence, and can invoke the bounded
wrapper only once. It requires a final all-market `SETTLED` receipt rather
than treating an exit code as success.

PowerShell AST parsing and diff checks pass on the production host. No
post-09:00 backfill or test suite was started. Workstation focused/full-suite
verification and a future admitted one-date production receipt remain
required; this repair does not close the representative Stage-A soak or the
August 17 settlement proof above.

The spent `WeatherSettlementBackfill20260830_0901a` task was disabled after
exact action, trigger, last-result, and `REFUSED` receipt readback. Its task and
receipt remain intact as evidence; it was not deleted or retried after the
window.

## 2026-09-01 workstation verification and repair

The source branch was fetched at exact handoff tip
`c49ade8338d123ea77c707e63a1943e3d2398c2b`; implementation commit
`3e9b2c08c0f85468d1d5956cfd3bdcd0c7e3e2d3` and tree
`d2d83251cd97a6f2f06997552f86e5954f77e82d` are its ancestors. Line-by-line
workstation review found that the source ratchets did not yet prove the
Scheduler lifecycle and that several fail-closed edges were incomplete. The
registrar now serializes same-date creation, treats queued and other ambiguous
states as active, proves rollback through disabled readback, and verifies the
root task path, principal identity, trigger type, enabled state, settings, and
exact action. The successor now binds attempt-scoped atomic receipts to the
date, attempt, and primary task; refuses a never-run primary that is still due;
requires run-correlated fresh evidence; and accepts `SETTLED` only when every
required all-market field proves the exact unique denominator with no missing
or unsettled market. The watchdog rejects structurally invalid JSON even when
it parses and retains the nested status exit code in its blind alert.

Deterministic Windows PowerShell mocks now exercise pair creation, second-task
registration rollback, readback rollback, ambiguous active history, inert
history, same-date concurrency refusal, settled skip, running/stale/still-due
refusal, exact one-call retry success and failure, invalid all-market proof,
and watchdog blindness without calling the real Task Scheduler. Registry
coverage executes `python -m weather.operations.settlement_backfill_registry`
in a subprocess, requires the module to come from the tested checkout, and
requires the exact unique 12-market built-in fleet.

The admitted workstation evidence is green: the mocked Scheduler file passed
10 tests; the focused operations and roadmap scope passed 1,425 tests with 17
skips and 77 subtests; compileall returned zero; agent-doc audit passed 18
agent files and 828 Markdown files; roadmap lint/check matched its generated
report; and the complete repository suite passed 4,235 tests with 22 skips,
13 warnings, and 862 subtests. Every pytest and compileall command ran through
`scripts/ops/workstation_heavy.ps1`. No real task was registered, started,
stopped, disabled, or deleted, and no provider, exchange, credential, live,
promotion, release, production-data, or production-master surface was used.

The canonical roll command was also executed and failed closed with exit 1:
`UNDECIDABLE: no live closure evidence`. All four locally retained closure
snapshots were dormant by roughly 486 to 865 hours, so the command emitted no
per-file rows and no roll-free verdict. A production-side rerun with fresh live
closure evidence remains required before adoption. This workstation proof
does not authorize adoption or registration; the only production follow-up is
the handoff's reviewed adoption decision and, during a future admitted
00:30-09:00 window, a fresh pair for an actually open date.
