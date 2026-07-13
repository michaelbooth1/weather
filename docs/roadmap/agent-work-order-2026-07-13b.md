# Agent Work Order 2 — 2026-07-13 (follow-up)

Composed by the operations master agent after auditing the execution of
`agent-work-order-2026-07-13.md` (report:
`docs/roadmap/agent-report-2026-07-13.md`, commits `765bac8c..c9b0267d`).

Audit verdict on the prior run: high quality. Verified live: CAS dedup is
active in the restarted capture path (market-local writes are now ~80 KB
hash refs instead of ~35 MB payload copies; single shared blob reused),
CLOB loop re-adopted rotation code at 11:59, the memory guard's physical
warning is live, and the interruption-safe Stage-A status produced a usable
resume receipt. Residual gaps below are the follow-up scope.

---

## Prompt

Same repository, host, and **non-negotiable rules** as
`docs/roadmap/agent-work-order-2026-07-13.md` — reread its rules section
before starting; every constraint there still applies (no capture stops
outside 01:00–04:15, sanctioned repair verbs only for already-down loops,
8 GB ad-hoc budget, no evidence deletion, no re-registration/release/
trading changes, focused tests + compileall before each commit, don't
touch unrelated worktree changes).

### Task 1 — Snapshot supervisor dead-loop blindness (new, highest priority)

The per-minute snapshot supervisor (`snapshot_tracker --ensure`, task
`WeatherSnapshotLoopSupervisor`) has now failed twice to revive a dead
loop while returning success: 2026-07-12 ~18:21–19:34 (wedged under memory
pressure) and 2026-07-13 ~10:51–13:11 (loop PID dead, writer lock absent,
stale-code identity — supervisor kept exiting 0 without restarting; the
outage lasted three hours until a manual `--restart`). Fix the ensure
path so that:

- A dead recorded PID, a missing writer lock, or stale-code identity with
  no live process triggers an actual restart attempt (respecting the
  existing restart budget/backoff), not a silent success.
- When ensure decides not to restart (budget exhausted, backoff, lock
  contention), it says so in its exit code and status output so the
  scheduled task's Last Result stops reading 0 while capture is down.
- The restart-circuit state is inspectable: persist the current backoff/
  budget decision where fleet observability can surface it.
- Add regression tests reproducing both failure shapes: dead-PID-with-
  stale-status, and wedged-ensure-holding-lock (the CLOB equivalent from
  07-12 19:40 had the same signature — check whether the CLOB and
  observation ensure paths share the defect and fix them too).

### Task 2 — Snapshot loop error-counter latching vs admission freshness

The new Stage-A admission (correctly) refuses heavy children when a
capture loop reports `degraded_reasons: consecutive_errors,
last_error_present`. But after a loop restart, `consecutive_errors: 1` and
a stale `last_error` can persist across iterations even while the fleet
reports 12/12 healthy — today that latched state deferred the
`hourly_model_performance` resume at 13:11 local. Decide and implement the
honest semantics: either the loop clears `last_error`/`consecutive_errors`
after a fully clean iteration, or admission distinguishes "historical
error, currently healthy" (heartbeat fresh + 12/12 + errors not
increasing) from "actively degraded". Do not weaken the gate for genuinely
degraded capture. Add tests for the restart-then-admit sequence.

### Task 3 — Item 324 soak evidence (continues prior Task 1)

The bounded Stage-A machinery is in the tree but unsoaked. Using the next
scheduled 09:30 Stage A run(s) — do not launch extra full-stage runs
yourself:

- Collect the per-step resource receipts (peak private/working set,
  elapsed, I/O) from the durable status after each scheduled run into the
  item-324 inventory checklist, and compare actuals against the declared
  budgets. Tighten any budget that is grossly oversized; flag any step
  within 20% of its ceiling.
- Confirm the scheduled task's exit code matched the durable status for
  the run, and that no step ran unisolated that the inventory says is
  high-risk (2026-07-13's blowups were `taker_edge_permission_map` →
  `maker_paper_score`, and the resumed chain ballooned across steps 11–15
  in-process — all of these must show subprocess receipts).
- Two consecutive clean scheduled runs close the soak checkbox; one clean
  run plus one budget kill that terminated correctly also counts as proof
  the enforcement works — record either honestly.

### Task 4 — Item 323 remaining proofs

- **Controlled capture hour**: with capture healthy, run the item's
  controlled measurement over one hour of live NBM cycles: bytes
  created/reused/avoided from the CAS observability, market-local ref
  sizes, and zero new market-local payload copies. Record it in the item.
- **Cross-process fan-out**: fleet markets run in isolated child
  processes, so today each child still fetches the national payload
  itself even though storage converges. Implement the cross-process
  single-fetch claim (file-lock or claim-file under the CAS root, holder
  fetches, others wait-then-read with a bounded timeout and fail-open to
  their own fetch), then prove one network fetch per cycle across a live
  fleet pass. Provider backoff/cooldown sharing must not regress.
- **Dry-run migration inventory** over the real snapshot root (read-only,
  bounded), recording legacy duplicate bytes by month so the operator can
  see the reclaimable total. No apply mode.

### Task 5 — Item 322 soak evidence (continues prior Task 3)

The incremental-persistence taker code adopts at the next 00:05 roll. From
tomorrow's live paper day, collect the declared diagnostics (PID
continuity, private/working-set peaks and post-warmup slope, per-tick tape
and process I/O, tick duration) over at least four consecutive hours and
compare against the budgets. Flat-slope evidence closes the soak
checkbox; a regression reopens the implementation. Do not restart or
signal the live worker to force adoption early.

### Task 6 — Hygiene (small, batch last)

- Normalize the corrected 2026-07-13 daily-refresh status progress
  counters (`completed_step_count=14`, `total_step_count=13`) or make the
  writer tolerate/repair historical inconsistency so downstream readers
  don't trip.
- The three date-sensitive active-variant tests that failed outside the
  prior run's changed surface: make them date-robust (no weakening of
  what they assert).
- The 12-hour monitor's derived hourly summaries were corrupted by resume
  re-bucketing (duplicate `hour_1`, missing `hour_2`/`hour_12`); its raw
  JSONL was authoritative. If the monitor tooling lives in this repo, add
  the regression test for resume bucketing; if it was session-local
  tooling, note that and skip.

### Reporting

Append results to a new `docs/roadmap/agent-report-2026-07-13b.md` in the
same per-task format (status, what changed, tests with counts, deferred
items with reasons). If the host is in memory/disk distress at any point,
stop feature work and protect capture first.

---

*Excluded from this order: tonight's 01:00 training-window verification
and the Stage-A same-day resume (operations master agent owns both); the
item-321 release bootstrap (gated on the window proof); item-206 shims
(embargoed to 2026-07-18); disk cleanup (operator-owned at 200 GB).*
