# Workstation handoff — 2026-07-23: Release-#1 bootstrap dress rehearsal

From the production-host master agent, following the completed research program
(`codex/workstation-research-2026-07-22` @ `423eaa59` — accepted; audited
leakage-first; verdict: rigorous, supports no production change). That program's
own conclusion stands: **the current corpus is exhausted — the next value is new
evidence, not another slice.** This handoff therefore points the workstation at
the one thing that has never been executed end-to-end and now has a clock on it:
**the release-#1 bootstrap that fires when the Toronto streak locks.**

## Why this is the most valuable next mission

- The streak (14 contiguous `complete`-grade Toronto days) is at 2/14, earliest
  lock ~2026-08-03. When it locks, the 4-gate bootstrap
  (attestation → release → admission → parity) executes release #1 — the gate to
  the entire learning loop. **That path has never run end-to-end.** A defect
  discovered at lock time burns real streak days; a defect discovered in
  rehearsal costs nothing.
- The 2026-07-12 cutover audit recorded that release #1 "still needs Phase-4
  nightly PIT code." Whether that gap was since closed is unverified. The
  rehearsal answers it definitively.
- The research branch hardened the exact modules this bootstrap runs
  (`release_bootstrap.py`, `nightly_retrain.py`, `release_candidate_build.py`,
  promotion/*, PIT validation) to fail closed. The production host will NOT
  merge that branch before lock (merge rolls capture loops and changes the
  release path at the worst moment). Whether the hardening would have *blocked*
  a legitimate release on real data is an open question only a rehearsal on
  identical inputs can answer — it converts the merge-timing decision from
  caution into evidence.

## Mission 1 (primary): dress-rehearse the release-#1 bootstrap, twice

Run the bootstrap end-to-end in the isolated worktree against the read-only
`data/` mirror, in dry-run/research mode, on **two code identities with
identical inputs**:

1. **master @ HEAD** — the code that will actually execute at lock.
2. **`codex/workstation-research-2026-07-22` @ `423eaa59`** — the hardened
   fail-closed path under merge consideration.

Because no real 14-day window exists yet, synthesize the lock precondition
**inside scratch only** (e.g. a research-harness ledger stand-in with 14
contiguous `complete` days, or a documented gate relaxation) purely to exercise
the code path. Label every such synthetic input unmistakably; it must never be
mistakable for, or written near, real settlement data.

Specific verifications to fold in:

- **Grade-authority check (named, pending since 2026-07-16):** trace what
  actually feeds the PIT preselection's `quality_grade` rows. PIT admission
  gates on `COUNTABLE_LABEL_QUALITIES` with `admitted_by == "quality_grade"`
  (`src/weather/reporting/validation/point_in_time_evaluation.py`, ~lines
  99–104, 1507–1552). The authoritative source is
  `data/settlements/toronto/ledger.jsonl` (append-only; latest row per
  `target_date` wins). `data/backtest/market_day_labels.csv` is a lagging
  promotion artifact. **If the preselection path reads the CSV (or anything
  that lags the ledger), the bootstrap can fail or select a wrong window at
  lock — report it as a pre-lock defect with the exact call chain.**
- **Phase-4 nightly PIT code:** confirm whether the gap from the 2026-07-12
  cutover audit is closed on master. If code is missing, that is finding #1.
- **Host-bound gates** (scheduled-task attestation etc.) cannot be rehearsed on
  the workstation: enumerate them explicitly as NOT-REHEARSED rather than
  skipping silently, so the production host knows its residual checklist.

**Deliverable — a go/no-go readiness report** with every defect classified:

- **(a) Blocks release #1 on the master path** → must fix before lock
  (production host owns scheduling the fix; do not fix-and-merge from the
  workstation).
- **(b) Hardened-path-only block** → the fail-closed branch would reject
  something master accepts. For each: true positive (real integrity issue in
  our corpus master silently tolerates — argues for merging the hardening
  pre-lock) or over-strict check (argues for post-lock merge). This
  classification IS the merge-timing decision input.
- **(c) Cosmetic / deferred.**

## Mission 2 (secondary, if capacity remains): fresh pooled H2 artifact

The research program's own top-ranked follow-up: train a fresh pooled candidate
through the corrected blocked/nested H2 path, binding exact code, input, model,
calibration, and nested-counter hashes in a training receipt; prove train/serve
feature parity and replay identity.

**Hard scope limit:** produce artifact + receipt + parity proof and STOP.

- Do NOT evaluate it against market outcomes on any opened window (June 3 –
  July 10 corpus, June 22 – July 10, July 15–19, and the 2025 pool window are
  all consumed).
- Instead, preregister (spec + hash committed to the branch) the future
  confirmation panel: dates that have not yet occurred, metrics fixed in
  advance — jointly Brier, log loss, winner mass, and market gap, per the
  synthesis' multi-objective guard — with the 09:00–14:00 slice as a named
  reporting cut.
- The artifact is a research candidate with a distinct identity. It authorizes
  nothing.

## Guardrails (unchanged, non-negotiable)

- `data/` mirror is strictly read-only; all outputs under
  `scratch/workstation-research-output/`.
- No promotion, release-pointer, serving, collector, scheduler, sizing,
  live/paper trading, or capital change of any kind.
- Work on a fresh topic branch off master (base commit recorded); push the
  topic branch only — never master. PR creation is the operator's.
- Never rerun or reconstruct consumed one-shot panels; never reuse the leaked
  seven-city morning grouping.
- No access to the production host; this document plus origin branches are the
  entire interface.
- Report honestly, including what was not run; a NOT-REHEARSED list is a
  first-class result.

## Handback

Write the readiness report to
`docs/roadmap/agent-report-<date>-workstation-bootstrap-rehearsal.md` on the
topic branch (plus the Mission-2 receipt/prereg docs if reached), push, and
notify the operator. The production-host agent will consume the (a)/(b)
classification directly: (a)-list drives pre-lock fixes on master; (b)-list
drives the merge-timing decision for the hardening branch.
