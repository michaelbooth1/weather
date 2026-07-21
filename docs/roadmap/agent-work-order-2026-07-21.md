# Agent Work Order — 2026-07-21 (right-size the Stage-A heavy-step admission budget)

Composed by the operations master agent. The `maker_paper_score` (and every
subprocess-isolated Stage-A step) is admitted only when free physical memory ≥
`reserve + working_set_max_bytes`. For `maker_paper_score` that is
`1536 MiB reserve + 3072 MiB working-set ceiling = 4608 MiB (~4831 MB)`. On this
16 GB host with VS Code permanently resident (~3.6 GB, cannot close — Claude Code
runs in it), that bar is frequently unmet, so settled-day barriers defer on an
honest `insufficient_physical_availability` block even though the step's real
peak is far lower (a one-off live observation put maker private peak ≈ 2.3 GB).

The over-provisioning is structural: the admission requirement reuses
`working_set_max_bytes`, which the code itself documents as a **containment
ceiling, not a target allocation** (see the comment above
`STAGE_A_STEP_RESOURCE_POLICIES` in `daily_refresh_resources.py`). Using the
kill-ceiling as the admission expectation reserves headroom the step never uses.

**Goal:** decouple the *admission expectation* from the *containment ceiling* so
the gate admits on a measured realistic peak while the kill ceiling stays
unchanged — i.e. tighten to reality WITHOUT weakening any safety limit. This is
Phase 1 (mechanism + instrumentation, shipped fail-safe with ZERO behavior
change). The master sets the tightened values in Phase 2 after collecting real
peaks from instrumented production runs.

## Absolute safety constraints (do not violate)

- **Never raise** any containment ceiling (`working_set_max_bytes`,
  `private_memory_max_bytes`) or lower the reserve floor
  (`DEFAULT_STAGE_A_MIN_AVAILABLE_RESERVE_MB = 1536`; `step_resource_budget`
  already forbids a smaller reserve). This work order does the OPPOSITE of a cap
  raise — it lowers only the admission *expectation*.
- The new admission expectation must be **≤ the containment ceiling** for every
  step (assert this invariant).
- **Fail-safe default:** if a step declares no explicit admission expectation, it
  MUST default to `working_set_max_bytes` — i.e. current behavior is exactly
  preserved until the master sets explicit lower values in Phase 2. This branch
  must ship with zero behavior change.
- Do not touch the commit-percent gate, the reserve, the capture-loop freshness
  checks, or `available_memory_bytes` (it already uses `ullAvailPhys` — available,
  standby-inclusive — which is correct; the metric is not the problem).

## Task (Phase 1)

1. **Peak-memory instrumentation** (`daily_refresh_step_child.py`, or a small
   helper): when an isolated step child finishes (success or failure), record its
   own peak working-set and peak commit into `{step}.result.json`. On Windows use
   `GetProcessMemoryInfo` with `PROCESS_MEMORY_COUNTERS_EX` on the current process
   (`PeakWorkingSetSize`, `PeakPagefileUsage`) — the OS tracks these, so no
   sampling loop is needed; on POSIX use `resource.getrusage(RUSAGE_SELF).ru_maxrss`.
   Add fields like `peak_working_set_bytes` and `peak_commit_bytes` to the result
   schema (bump the step-child result `schema_version`). Best-effort: never fail
   the step if the query fails.

2. **Decouple admission from the ceiling** (`daily_refresh_resources.py`):
   - Add an optional `admission_working_set_bytes` to the budget dict (extend
     `_budget(...)` with an optional arg; when omitted it stays `None`).
   - In `step_resource_budget`, compute
     `required_available_before_start_bytes = reserve + admission_working_set_bytes`
     where `admission_working_set_bytes` falls back to `working_set_max_bytes`
     when unset. Keep `working_set_max_bytes` in the budget as the containment /
     kill ceiling (unchanged, still surfaced in the admission record).
   - Surface both numbers in `build_stage_a_step_admission`'s
     `physical_memory` block (`admission_working_set_bytes` and
     `working_set_budget_bytes`) so operators can see the gap.
   - Do NOT set any explicit `admission_working_set_bytes` values yet — leave every
     step defaulting to its ceiling (Phase 2 sets them from measured peaks).

3. **Tests** (focused, mocked memory — do NOT run the live heavy step):
   - Admission uses `admission_working_set_bytes` when set; falls back to
     `working_set_max_bytes` when unset (byte-identical current behavior).
   - Invariant: `admission_working_set_bytes <= working_set_max_bytes` for every
     configured step (and a guard that rejects a larger value).
   - The receipt records peak fields (mock the OS query).
   - Existing daily_refresh admission/deferral tests still pass unchanged.

## Rules

Same isolation and rules as `docs/roadmap/agent-work-order-2026-07-16.md` (read
it first): NEW worktree on branch `admission-budget-rightsize-2026-07-21` off
current `master`; no main-worktree edits; **no scheduler/loop/release/`data/`
actions and do NOT run the live `maker_paper_score` step or any daily_refresh
run** (Phase 1 is mechanism + unit tests only, with mocked memory); focused tests
under host `commit_percent < 70`; no merge/push.

**Note for the master (not the delegate):** expected roll-free (daily_refresh
chain modules, not loop-loaded) — verify each changed file against the three
capture loops' `source_scope_files` at merge. Phase 2 (mine): after the merge and
a few instrumented runs, read `peak_working_set_bytes` across recent
`maker_paper_score` (and other heavy-step) receipts, set
`admission_working_set_bytes = observed_peak x safety_margin` (margin ≥ ~1.3, and
always ≤ ceiling), and verify the step still admits and completes with VS Code
open. If peak variance is high or samples are thin, keep the value conservative.

### Reporting

`docs/roadmap/agent-report-2026-07-21.md` in your branch: the design, the exact
admission formula before/after, proof that the default path is byte-identical to
current behavior, the invariant test, test counts, and branch/commit ids.
