# Workstation handoff 2026-08-26a — build the all-market base-retrain step

Run this now. **Implementation and tests only: no fit, no retrain, no artifact, no candidate
scoring, no fresh dates, no run against real corpora.** `-08-16a` remains queued for
2026-08-05 04:30.

## Why this changed priority

`-08-25a` answered the question I said mattered most, and the answer was the bad one. I verified all
three legs on the production host before accepting it:

- `planned_steps()` has no `weather.calibration.feature_model` — only the **pooled** band model.
- `WeatherNightlyRetrainValidatePromote` runs exactly `nightly_retrain run`.
- `_freeze_base_model_serving_graph()` **copies** the seven components per market. It freezes bytes.
- `retrain.yml` is manual-only and trains **toronto and nyc**.

So release #1 binds the June 10–13 HGBs. I had told the operator that release #1 restarts base
learning; that was wrong, and correcting it puts **this step on the critical path between release #1
and a model that is not a degree too cool**. It does not exist, so it has to be written.

**Base this branch on `master` @ `73d53cde`, not on the held research chain.** This is operational
plumbing, independent of the four held candidates, and it must be mergeable without dragging them
along.

## 1. Build the step

Implement the all-market base-model candidate step specified in §5 of your own report. Restating the
boundary so it is unambiguous:

1. Explicit target date, parent release ID, training as-of/cutoff, feature-contract ID, corpus
   manifest, candidate directory, runtime ID. **No ambient-date default anywhere.**
2. All 12 registered markets, native units.
3. Writes **only** immutable candidate paths. Never the global `artifacts/` tree, never `data/`.
4. Emits HGB + compatible LR, candidate-specific probability calibration, receipts, report.
5. Copies every intentionally unchanged graph component from the parent **by exact hash**.
6. Builds an inactive release only after the complete 12-market graph verifies.

The statistical change for run one stays narrow: **target-date-aligned prior** and **contiguous
serving support declared separately from `model.classes_`**, with the fold-local upper edge and the
predeclared margin (2 buckets C, 4 buckets F) exactly as you specified. Parent feature-name contract
and hyperparameters otherwise frozen. **Do not silently activate the other 202 schema columns.**

The current CLI is not fit for this. Harden it or wrap it — your call — but the existing global-path
write behaviour must be impossible to reach from the new step.

## 2. Build the fail-closed preflight

Implement the preflight table from §5 as executable gates, not documentation. Every one fails closed.

Two of them must fail **today**, on purpose, and I want to see them do it:

- **Forecast archive.** I confirmed the manifests directly: `season_window` is **May 10 → June 30**
  in every year, 52 days/year. A late-July-aligned window gets 0 rows for parent-selected
  `forecast_high` / `forecast_gap`. The gate must report `0/N` and stop.
- **Train/serve parity.** The WU-blind surface fields must fail it. A boolean replay receipt is not
  sufficient — compare values, units, categories and missingness.

A preflight that passes on today's inputs is a broken preflight. Demonstrate both failures.

## 3. Prove output isolation

Before/after hash inventory of the repository globals, the active pointer, and every parent release
component, across a dry output-path probe. Any write outside the declared candidate root aborts.

I want this proven by test, not asserted. The failure mode where someone runs the base trainer
directly and silently mutates `artifacts/` and `data/` is the one that would cost us the most.

## 4. Fleet atomicity

All 12 HGB/LR pairs and candidate calibration complete, or nothing is releasable. **Toronto/NYC-only
success is failure** — that is exactly the shape of the retired hosted workflow and I do not want it
reachable by accident.

## Explicitly out of scope

- **Extending the forecast archive.** It is a hard blocker, but it is not a free chore:
  `model_features.py:1636` calls `load_forecast_daily(daily_path_for(spec))` on the **analog serving
  path**, so widening the season window changes live serving inputs. That needs its own gate and its
  own decision. Detect the gap here; do not close it.
- The WU/feature-contract repair. Already specified in `-08-21a`.
- Any actual fit. The preflights fail today; that is the correct state.

## What I want back

1. The step, with tests, on a branch off `master`.
2. Both intended preflight failures demonstrated.
3. The output-isolation proof.
4. Which files you touched that are roll-sensitive under `SOURCE_PATTERNS`
   (`src/**/*.py`, `scripts/**/*.ps1`, `tools/**`, …), so I can size the capture-loop roll before I
   pick a merge window.
5. Anything in the spec that turned out to be wrong or unbuildable once you were in the code. You
   wrote the spec a day ago against a codebase you had only read; say so if it did not survive
   contact.

## Constraints — unchanged

- **Do not read, enumerate, evaluate, or substitute 2026-08-01 → 08-03 or 2026-08-06 → 08-19.**
- **Do not fit, refresh, backfill, or write any artifact, sidecar, prior, cache, archive, or marine
  path.** Fixtures and synthetic corpora only.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. Registering the new step in the orchestrator's plan is a code change on a branch — it
  is **not** authorization to register or modify a Windows scheduled task.
- **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Merge timing is mine and will not be before
the release lock. Flag anything you believe should block the merge.
