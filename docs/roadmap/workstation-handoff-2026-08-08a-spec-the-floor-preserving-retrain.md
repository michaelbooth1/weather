# Workstation handoff — 2026-08-08a: spec the floor-preserving retrain

Accepted and merged (`31c3ae2d`). The chain is closed and the answer is green.

Three results carried it, and two of them cut against the easy conclusion:

- **The floor binds on 76.34% of severe rows — but on 72.41% of all snapshots.** A 0.20pp enrichment
  means binding is ubiquitous and is *not* what puts a row in the tail. That kills the tempting story
  that flooring causes the loss.
- **The floor improves accuracy**: net selected-row Brier `−0.04957`, mean total-distribution
  `−0.07260` on floor-active severe snapshots.
- **No selected severe band and no settled winner lay below the floor** on any of the 6,895 materially
  bound rows. That is the decisive correctness check I asked for, and with the 0/12,813 over-final
  audit the floor is now validated. We can stop revisiting it.

What survives is the sharpest statement of our defect yet: **told "at least X", the model puts its
mode on the settled band 22.64% of the time against the market's 78.22%, and 54.40% of rows are wrong
at the floor band or the one immediately above it.** We are not failing at meteorology. We are failing
at allocating probability across two or three adjacent bands when the floor has already told us where
the bottom is.

## Mission: write the retrain specification. Do not run it.

You have earned the spec. Produce `docs/roadmap/` design content, not a candidate.

**First, settle one factual question I tried and failed to answer cleanly.** The incumbent artifact
reports `feature_subset = 'all'` ("All default pooled band model features"), and the live feature dict
does build `current_max_trust_features` and an `effective_observed_high` / `current_max_bucket`. But
you showed for marine that presence in the dict proves nothing — the artifact selects a subset and can
have zero tree splits on a column.

> **Does the incumbent HGB actually consume the floor?** Run the same inventory you ran for marine:
> selected feature names *and* tree-split counts for the observed-high / current-max family, per hour.

That answer forks the whole spec:

- **If the model cannot see the floor**, it is being asked to predict an unconditional high and then
  truncated at serve time. The fix is to make it floor-aware, and that is a feature-contract change.
- **If it can see the floor and still places mass below it**, the features are not the problem and the
  training objective is — the model is optimising an unconditional likelihood when the served quantity
  is conditional on `high ≥ floor`.

**Then write the spec**, covering at minimum:

1. The training-target change. The served quantity is a *conditional* distribution given an observed
   floor known at effective time; state precisely what the model should be trained to predict.
2. Preservation of the hard-floor invariant — non-negotiable, and stated as a test, not a hope.
3. Explicit targeting of near-floor modal allocation, since that is where the measured loss is.
4. **Gates.** Total Brier non-regression, severe-tail improvement, a cap on newly created severe rows
   (the market×hour corrector created 1,065), probability-mass conservation, floor invariance,
   train/serve parity, captured-input replay.
5. The evaluation plan: development on the fit window, and **one** confirmation run on the reserved
   2026-08-06 → 08-19 window after it closes, with completeness declared without inspecting outcomes.
6. Roll footprint and rollback: which files and artifacts change, what must restart, and how to undo.
7. An explicit statement of what would falsify the hypothesis — what result would mean we abandon this.

Anchor expectations to your own bound: at most **44.65pp** of the severe-tail baseline under
hindsight-perfect centre replacement, and an achievable retrain must land lower. Say so in the spec so
nobody later reads the ceiling as a forecast.

## Constraints

- **Specification only.** No retrain, no candidate, no fitting, no artifact, no `data/` write, no
  serving or floor change. The artifact inventory in step one is read-only.
- Do not read or evaluate **2026-08-06 → 08-19**, and do not swap it.
- No tuning decision from 2026-07-27 → 07-30.
- Execution waits for release #1 regardless — nightly retrain is blocked without a release identity, so
  there is no path to running this sooner even if the spec is perfect.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

## Handback

`docs/roadmap/agent-report-<date>-workstation-retrain-spec.md`: the floor-consumption inventory and
which fork it selects, then the specification with its gates, evaluation plan, roll footprint,
rollback, and falsification criterion.
