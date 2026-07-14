# Agent Report — 2026-07-13b

This follow-up stayed in research, paper, read-only, dry-run, and operational
repair modes. It did not re-register a scheduled task, change release or
trading state, enable credentials, delete evidence, run an apply migration, or
launch an extra Stage-A run. The unrelated generated changes in
`config/location_market_events.json` and `config/locations.json` remain
unmodified and excluded from this work.

## Task 1 — snapshot supervisor dead-loop blindness

Status: **PARTIAL — core repair live; destructive-authorization hardening and
commit deferred to the adoption window**.

- Snapshot, CLOB, and observation ensures now verify status-PID/writer-lock
  ownership, serialize supervisor actions, persist the latest circuit/backoff
  decision in a separate atomic supervisor sidecar, expose it through status
  and fleet observability, and return nonzero for lock contention, backoff,
  circuit-open, or failed launch decisions.
- Regression coverage reproduces a dead PID with stale status and an ensure
  action-lock contention. The scheduled snapshot supervisor was observed
  returning nonzero while its restart circuit was open and returning zero only
  after a healthy writer lock existed.
- A read-only integration review found one remaining high-severity edge case:
  all three stop paths can still authorize termination from a generic live
  Python PID after the new lock check has already declared that PID
  untrustworthy. Observation can also remove the lock before termination is
  confirmed. Loaded capture source is frozen until 01:00–04:15; the queued
  adoption-window fix will require exact managed command/process-instance
  provenance, fail closed when identity is uninspectable, treat a mismatched
  live lock owner as authoritative, and add negative reused-PID tests.

Verification so far:

- Supervisor/loop/CLOB/observation/fleet slice: **175 passed**.
- `python -m compileall -q app src tests`: passed before the follow-up review.
- Schema/docs slice: **9 passed, 1 failed** only for the two Task-4 schema
  registrations still pending in the adoption-safe window.
- Import architecture: **20 passed, 1 failed** because the two new Task-4 files
  are intentionally untracked until the adoption-window commit.

This task made no commit outside the adoption window because changing HEAD or
loaded capture source would force another live-code readoption. The unrelated
concurrent commit is attributed under Task 6.

## Task 2 — snapshot error latch and Stage-A admission

Status: **IMPLEMENTED; commit pending with the loaded-source adoption**.

- In-progress heartbeats retain the previous completed iteration's error.
  Only a complete all-registered-market iteration can replace that latch.
- Missing market results count as errors. A fully complete clean iteration
  clears `consecutive_errors` and `last_error` and records explicit completed
  and clean iteration markers; genuinely degraded capture remains blocked.
- The live repaired worker's first pass had a real NYC exit-137 error and kept
  the latch. Its next completed clean iteration cleared the latch from one to
  zero. This is the required restart-then-admit sequence, not a freshness
  bypass.

Verification:

- Collection/admission focused slice: **79 passed**.
- `python -m compileall -q src`: passed.
- Agent documentation audit: passed.

## Task 3 — Item 324 scheduled soak

Status: **DEFERRED to the next scheduled 09:30 runs; no extra Stage-A run was
launched**.

- The 2026-07-13 scheduled task still reports result `267014`; its resume
  stopped at `hourly_model_performance` when capture honestly reported the
  first post-restart iteration's error latch. That row is a valid admission
  rejection, not a budget soak.
- The durable status contained only that deferred resource receipt and carried
  earlier steps without new isolated-subprocess receipts, so it cannot prove
  the representative inventory, high-risk isolation, exit-code agreement, or
  two-run soak.
- Follow-up is queued after the next two scheduled 09:30 runs. It will compare
  private/working-set peaks, elapsed time, I/O, and exit status against every
  declared budget; flag any result within 20% of its ceiling; and verify
  `taker_edge_permission_map`, `maker_paper_score`, and resumed steps 11–15
  have subprocess receipts.

A separate user-owned Claude Code session was found launching additional
`hourly_model_performance` resume attempts at 18:41, 18:44, 18:49, and 18:55
UTC. They were not started by this task and are not scheduled 09:30 runs, so
they are excluded from soak evidence. The 18:55 attempt admitted an isolated
child; its process returned zero, but terminal-manifest validation failed and
the durable run correctly ended `error`. The first genuine 17:11 UTC admission
receipt remains embedded. This task did not terminate the other user-owned
agent session or relabel its artifacts.

## Task 4 — Item 323 remaining proofs

Status: **PARTIAL**.

- Added a cross-process claim/receipt coordinator under the shared CAS. One
  isolated child holds the NBM fetch; followers wait a bounded 30 seconds,
  verify receipt identity plus CAS hash/size, and parse their market station.
  Timeout fails open to the normal fetch. HTTP/timeout/connection outcomes are
  shared within a pass, and existing provider cooldown propagation remains.
- Added network fetch/reuse, cross-process reuse, and timeout-fail-open counts
  to compact storage/status/runtime observability.
- Upgraded the read-only migration inventory to v0.2 with month selection,
  streaming totals, retained-detail sampling, and explicit elapsed-time,
  directory, tree-entry, manifest-count, manifest-byte, JSONL-line,
  manifest-row, per-payload, aggregate payload-read, and physical-blob bounds.
  Repeated manifest references count one physical legacy file once, absolute
  legacy paths must remain inside both the selected snapshot root and event
  folder, and every bound emits a resumable partial result. It still exposes no
  apply, rewrite, GC, or delete mode.
- The immediate live pass showed one NBM network fetch and reuse among the
  completed markets, but NYC exited 137, so 11/12 is not a clean fleet proof.
- A fresh controlled monitor started from clean capture at 14:44 local and is
  writing under `data/monitoring/item323_controlled_healthy_hour`; a separate
  14:29 run is retained as outage/repair context and will not be relabeled as a
  healthy hour.
- Read-only review found additional proof-boundary gaps. The migration-side
  traversal/deadline, record-size, scan-integrity, duplicate-physical-byte,
  path-containment, and invalid-digest gaps are now fixed and covered. A holder
  death after receipt publication can still
  lose fetch/physical-write attribution, and receipts still need bounded,
  no-symlink, immutable, cycle-semantic verification. Those loaded fan-out
  fixes wait for the adoption window.

Verification so far:

- Cross-process/migration/runtime focused slice: **69 passed**.
- Migration-only slice after bounded-inventory hardening: **34 passed**.
- Roadmap regeneration/lint: passed.
- Real-root inventory: migration code is ready; the scan remains queued for the
  bounded 01:00–08:30 load window.

## Task 5 — Item 322 soak evidence

Status: **DEFERRED to normal worker adoption and four-hour readback**.

The incremental taker implementation does not adopt until the normal 00:05
roll. No live paper worker was restarted, signaled, or forced to adopt early.
A read-only 08:20 follow-up will evaluate at least four consecutive post-
training hours for PID/process-instance continuity, private and working-set
peaks, post-warmup slope, per-tick tape/process I/O, and tick duration against
the declared budgets. Flat-slope evidence is required before closing the soak.

## Task 6 — hygiene

Status: **IMPLEMENTED IN THE WORKTREE; adoption-window commit pending**.

- Daily-refresh progress now counts only successful terminal step statuses,
  retains a declared total across resume, and repairs historical
  `completed_step_count > total_step_count` with explicit provenance. The
  ignored 14/13 operational counters were normalized without deleting any
  tape, ledger, or captured evidence.
- The three active-variant fixtures now use the last completed Toronto market
  date, include the current registry booleans, isolate CLI paths under the test
  temp root, and preserve the intended negative-contract failure.
- Runtime-monitor resume bucketing now reconstructs missing immutable-clock
  hours from authoritative raw JSONL on every terminal path. A cross-process
  lock makes summary emission exactly once, and reconstructed hours use their
  historical component-health tape state rather than the latest state.
- Production readiness now runs after a safe captured-input parity defer but
  remains skipped after an orchestration/status-persistence error.

Verification:

- Runtime-monitor slice: **15 passed**.
- Named daily-refresh/date/path/progress checks: **8 passed**; active-variant
  named checks: **7 passed**; post-HEAD critical rerun: **4 passed**.
- Scoped compileall and `git diff --check`: passed. A full daily-refresh suite
  was deliberately not rerun against a memory-constrained live capture host.

A concurrent user-owned Claude Code session committed and pushed
`34807b4a` (`fix: accept venv launcher-shim ancestry in Stage-A child receipt
validation`) while this work was in progress. That commit included the
daily-refresh source and one resource-test file from this worktree. This task
did not create, amend, or push that commit and will not rewrite it.

## Operational incident and current state

At 14:23 local, the snapshot PID was dead, its writer lock was absent, the
supervisor restart circuit was open at 6/6, and physical availability fell to
about 1.93 GiB. Because the loop was already down, the exact sanctioned
`python -m weather.collection.snapshot_tracker --restart` repair was used at
14:31. No live process was stopped. The new worker is PID 9828 and acquired the
writer lock. Its first fleet pass wrote 11/12 markets and recorded NYC
`returncode=137`; subsequent completed iterations were clean. Physical
availability briefly reached about 1.53 GiB after launch and recovered above
3 GiB. The worker's loaded-source fingerprint remains current and unchanged.
At the 15:10 readback it was still producing fresh snapshots with zero latched
errors; the controlled monitor was also current and running toward its 15:44
end.

The healthy-hour monitor, adoption-window repair/commit, Item-322 morning
readback/real-root migration, and two Item-324 scheduled-run readbacks are
chained through the current task's active follow-up automation. Each phase is
explicitly barred from extra Stage-A runs, scheduler re-registration, evidence
deletion, release/trading changes, or unsanctioned loop control.

A concurrent Claude Code session remained active and launched the non-
scheduled Stage-A resumes described under Task 3. No daily-refresh child was
active at the last readback; capture remained clean. Available physical memory
reached 3.72 GiB before later fluctuating below 3 GiB, so broad tests remain
deferred. This report keeps that concurrent ownership explicit rather than
claiming those runs as work from this task.
