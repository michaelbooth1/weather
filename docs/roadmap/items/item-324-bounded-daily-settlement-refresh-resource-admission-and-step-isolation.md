# 324. Bounded Daily Settlement Refresh Resource Admission And Step Isolation [PARTIAL 2026-07-13 - CODE GATES LANDED; SCHEDULED SOAK REMAINS]

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

No extra full-stage run is authorized for this checklist. Readbacks are queued
after the 2026-07-14 and 2026-07-15 scheduled runs.

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
