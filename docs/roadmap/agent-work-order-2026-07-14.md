# Agent Work Order 4 — 2026-07-14 (parallel lane: countable-evidence plumbing)

Composed by the operations master agent after auditing branch
`release-bootstrap-2026-07-13` (clean: Tasks 1–3 complete, no forbidden
files, one trivial doc conflict). This order covers the remaining CODE
prerequisites for the release-#1 cutover; the cutover actions themselves
(merge, window mode flip, create/verify/promote, re-registration) are
executed by the operations master agent, not by you.

---

## Prompt

Same repository, host, and rules as `agent-work-order-2026-07-13.md` and
the isolation contract of `agent-work-order-2026-07-13c.md`: work in a NEW
git worktree on branch `evidence-plumbing-2026-07-14`, commit only to that
branch, never touch the main worktree, never run loop/scheduler/promotion
actions, focused tests only with commit_percent < 70, and do not modify:
supervisor/collection modules (`snapshot_tracker`, `market_microstructure*`,
`observation_trigger`, `capture_resource_gate`), `daily_refresh*` operations
modules, forecast/CAS storage, the runtime monitor, or anything the
`release-bootstrap-2026-07-13` branch already changed (rebase/merge is the
operations agent's job; base your branch on current `master`).

### Task 1 — Captured-input parity evidence generator (the last re-registration blocker)

The new-contract register scripts demand existing files for
`-CapturedInputParityServed`, `-CapturedInputParityReplay`, and the parity
preflight requires both sides fresher than 48h, release-bound. Nothing in
the repo today *produces* the replay side on a schedule. Build it:

- A command (suggate: `python -m weather.reporting.scorecards.captured_input_parity_evidence`,
  verify naming conventions first) that, under a VERIFIED active release
  only: reads the day's `replay_inputs.jsonl` captured inputs per market,
  regenerates prediction rows through the exact release-verified serving
  bundle, and writes replay-side rows to a stable path
  (`data/backtest/captured_input_parity/replay_rows.csv` or similar);
  plus exports the corresponding served rows tape slice to a stable
  served-side path. Atomic writes, self-hashed, release id/manifest sha
  stamped in both files.
- Fail closed with an actionable message when: no active release pointer,
  release verification fails, captured inputs are missing/stale, or the
  serving bundle fingerprint mismatches. NEVER fabricate replay rows from
  served rows — the two sides must come from independent paths.
- Bounded: one market-day at a time, declared memory ceiling suitable for
  the 15.7 GB host, and runnable inside the 01:00–08:30 quiet window.
- Focused tests with a synthetic release + captured inputs proving: honest
  generation, each fail-closed branch, and that the existing
  `persist_captured_input_replay_parity` comparator PASSES on the
  generated pair and BLOCKs on a tampered row.

### Task 2 — Register-parameter emitter (make re-registration mechanical)

A small read-only command that, given a verified active release, emits the
exact parameter set for `register_daily_refresh.ps1` and
`register_nightly_retrain.ps1`: the ROLE=PATH served-artifact bindings
drawn from the release manifest's serving roles, the served route path,
and the parity file paths from Task 1. Output as JSON plus a ready-to-run
PowerShell invocation block. Fail closed without a verified release. Tests
with a synthetic release.

### Task 3 — Isolated experiment executor (Phase 6, carried from prior order)

The queue contract and verifier exist; build the executor: run ONE
verified `executable_experiment_manifest` entry in an isolated candidate
directory under declared CPU/memory/timeout budgets (reuse the existing
Windows Job Object containment), record a terminal disposition
(`resolved/rejected/regressed/inconclusive/superseded`) through the
existing self-hashed result contract, and guarantee a failed or killed
experiment cannot mutate serving artifacts or block capture. No automatic
scheduling — the executor is invoked deliberately. Focused tests: budget
kill, disposition recording, serving-artifact immutability.

### Task 4 (stretch) — Worker release-binding verification

A focused test (plus fix if it fails) proving the taker and MM workers,
when an active release pointer exists, bind through the verified serving
bundle and stamp release id/manifest sha into their run summaries and
tapes — the field the countability ledgers require. Synthetic release
fixtures only; do not touch live workers.

### Reporting

`docs/roadmap/agent-report-2026-07-14.md` in your branch: per-task status,
tests with counts, branch/commit ids, merge notes.

---

*Sequencing context: tonight's window proves the loop; the merged
production-mode retrain (next window) produces the production candidate;
release #1 is then cut and promoted at a market-day boundary. Task 1+2
outputs are consumed the same morning to re-register the chain tasks under
the new contract — from that day, MM/taker paper days accrue as countable
live-forward evidence.*
