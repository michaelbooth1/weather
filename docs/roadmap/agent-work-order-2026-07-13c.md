# Agent Work Order 3 — 2026-07-13 (parallel lane: release bootstrap)

Composed by the operations master agent. This order runs IN PARALLEL with
the resource-hardening agent's automated overnight chain (healthy-hour →
01:05 adoption commit → 08:20 readback → 09:30 soak checks). It is scoped
to avoid every file that chain owns.

Goal: clear the remaining code prerequisites for cutting immutable release
#1, which is the gate to countable live-forward paper evidence — the
operator's stated priority is starting live testing as soon as the program
allows.

---

## Prompt

You are working in `c:\Users\micha\Desktop\github\weather` (Windows 11,
PowerShell 5.1, venv at `venv\`). Read
`docs/operations/HOST_LOAD_POLICY.md` and the rules section of
`docs/roadmap/agent-work-order-2026-07-13.md` first — every constraint
there applies (no loop control, no scheduler changes, no evidence
deletion, no release promotion, 8 GB ad-hoc memory budget, focused tests +
compileall per commit).

### Isolation contract (mandatory, read twice)

Another agent's automation owns the MAIN worktree tonight: it holds
uncommitted supervisor/collection/CAS/monitor changes and will commit them
at ~01:05 during the training window. Therefore:

- **Create a git worktree on a new branch** (`git worktree add
  ..\weather-release-bootstrap release-bootstrap-2026-07-13` from the repo
  root) and do ALL work there. Never edit, stage, commit, or revert
  anything in the main worktree.
- Commit to your branch only. Do NOT merge to master and do NOT push
  master; the operations master agent merges after the 01:05 adoption
  commit lands and conflicts are reviewed.
- Do not run full test suites or heavy replays on this memory-constrained
  live-capture host; focused tests only, and check
  `data\logs\memory_commit_guard_status.json` shows commit_percent < 70
  before any test batch.
- Files you must not modify anywhere (the other agent's loaded surface):
  `snapshot_tracker.py`, `market_microstructure*.py`,
  `observation_trigger.py`, `capture_resource_gate.py`, anything under
  `weather/operations/` named `daily_refresh*` except the ten-minute
  scorer hookup noted in Task 1, forecast/CAS storage modules, and the
  runtime monitor.

### Task 1 — Bound the ten-minute scorecard (urgent: tomorrow's 09:30 run)

`ten_minute_model_performance` exceeded its 3 GiB private cap today
(observed 3,222,503,424 bytes) and was correctly killed in-container with
a MemoryError. It will fail again on every scheduled run until bounded,
which blocks the settled-day barrier and prevents clean item-324 cycles.
Rewrite the scorer (`weather/reporting/ten_minute_model_performance.py` or
its actual owner module) to stream/window its checkpoint rows —
market-day by market-day aggregation, never materializing the full
multi-week row set. Preserve its outputs, schema version bump if row
semantics change, and its gate thresholds exactly. Do not raise the cap.
Add a regression test that proves peak memory stays roughly flat as
synthetic day count grows (mirror the 600-tick taker test pattern).
Also note in the item-324 file: after this lands, the 2026-07-12
settled-day analysis completes via the barrier's recorded resume commands.

### Task 2 — Nightly production-mode point-in-time integration (the release blocker)

Item-321 Phase 4's remaining integration is the single blocker for a
production candidate, and therefore for release #1. Per the item file
(`docs/roadmap/items/item-321-...md`, Phase 4 notes): "nightly
production-mode arguments, real fit receipts, a real locked evaluation,
and a production candidate remain open."

Implement in `weather/operations/nightly_retrain.py` and the
`weather/reporting/validation/point_in_time_evaluation.py` owner (verify
current names before editing):

- Production-mode arguments that materialize the four immutable PIT roles
  (Parquet corpus, materialization manifest, rolling validation plan,
  streaming evaluation) into the candidate directory during a retrain.
- Real self-hashed fit receipts for feature selection, imputation, model,
  calibration, postprocessing, and routing in every outer/inner fold —
  wired to the actual training code paths, not synthetic fixtures.
- The locked 14-day evaluation window: locked before candidate selection,
  recorded in the candidate packet, and rejected if reused for selection.
- The candidate must verify under the existing
  `release_candidate_contract` production mode so
  `release_lifecycle_cli create → verify` accepts it. Do not touch the
  promotion/pointer code itself.
- Bounded memory: all corpus work must stream per market-day (the PIT
  materializer already does; keep it that way) and declare budgets
  consistent with a 15.7 GB host.

Acceptance: focused tests prove a synthetic retrain in production mode
yields a candidate directory that passes candidate verification with all
four PIT roles, real receipts, and a locked window; research mode remains
default and unchanged. This is code + tests only — do not run a real
retrain; tonight's scheduled window handles that.

### Task 3 — One-command rollback drill readiness (Phase 1 open box)

Implement the remaining rollback piece in the release lifecycle: a single
command that atomically returns the pointer to the prior verified release,
emits the release-identity proof, and writes
`data/backtest/release_rollback_drill.json` with target, timing, and
post-rollback identity fields. Coordinated worker restart can be recorded
as a required manual step in the drill record for now (loop control is
out of scope tonight) — design the record so the drill is completable
once a real release exists. Focused tests with synthetic releases.

### Task 4 (stretch) — Isolated experiment executor skeleton (Phase 6)

If time remains: the executor that runs one verified queue entry in an
isolated candidate directory with declared budgets, records a terminal
disposition (`resolved/rejected/regressed/inconclusive/superseded`), and
cannot mutate serving artifacts. The queue contract and verifier already
exist; build the execution wrapper against them. Skip cleanly if Tasks
1–3 consume the session.

### Reporting

Write `docs/roadmap/agent-report-2026-07-13c.md` in your branch: per task
status, tests with counts, exact branch/commit ids, and anything the
morning merge needs to know. If the host is distressed, stop and say so.

---

*Why this lane: tonight's window can only produce a research candidate.
With Task 2 landed, the NEXT retrain produces a production candidate →
release #1 can be cut and promoted at a market-day boundary → parity rows
generate under the release → tasks re-register under the new contract →
MM/taker paper evidence becomes countable live-forward proof. That is the
shortest honest path to live testing.*
