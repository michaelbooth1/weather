# Workstation handoff — 2026-08-06a: stop correcting the symptom, find the mechanism

Accepted and merged (`0e9e8168`). You answered the question: **centre displacement is predictable, and
only with hour conditioning.** Recovery of 49.06% of the tail ceiling, target correlation up from
0.2838 to 0.6707, severe rows 3,893 → 2,980.

The process was the point, and you got it right where it was easiest to get wrong:

- **The declaration was hashed at 21:44:20Z, before any fit.** One test run at 21:49:37–21:50:29, never
  rerun. That ordering is the difference between a result and a story.
- **Rung 3 stayed locked because rung 1 failed**, even though rung 2 succeeded. A weaker agent would
  have argued the rule's intent was satisfied. You let the predeclared rule bind against your own
  interest, so no feature fit, coefficient, or second-pass score exists to contaminate later work.
- **You pre-committed that Aug 6–19 must not be swapped after seeing results.** That closes the last
  obvious escape hatch.

I am treating both costs as first-class, not footnotes: **total Brier got worse by 0.001972**, and the
correction **created 1,065 new severe rows**. Any future candidate carries total-Brier and
new-severe-row protections on top of the positive-excess gates. Your disposition already says this; I
am ratifying it.

## Why I am not asking you to refine the corrector

The obvious next moves — shrink the offset, gate where it applies, unlock the feature rung — all spend
more of an already-inspected window and push us toward a lookup table that corrects a symptom. The
fit and test windows are now burned for tuning. Iterating there buys diminishing returns at rising
overfit risk.

There is a far more interesting fact in your result:

> **The offset is predictable from market identity and capture hour alone — with zero weather
> information.**

A weather-dependent error would not behave like that. This is a **systematic structural bias in our own
model**, keyed to time of day. That is not something to correct after the fact; it is something to
find and fix at its source.

And we already have a prime suspect. The codebase carries **hour-conditioned centering and blending
parameters** — `forecast_centering`, `current_blend_alpha`, things like
`hour7_forecast_centering alpha 0.4 sigma 1.25` and Seattle current-blend alpha 0.2 — living in
`live_variant_predictions.py`, `pooled_training.py`, `variant_prediction_runtime.py`, and the pooled
candidate replay path. **Those parameters and your measured displacement are plausibly the same
phenomenon.**

## Mission: find where the hour-dependent centre bias is manufactured

Read-only investigation. No fitting, no candidate, no correction.

1. **Trace the centre.** Follow, in code, every stage between the raw forecast/observation inputs and
   the final served distribution's expected band index. Identify each stage that can move the centre —
   forecast centering, current-observation blending, calibration, postprocessing, the regime router.
2. **Compare against your measured displacement.** Your fitted per-market × hour offsets are the ground
   truth of the symptom. Which stage's hour profile matches it? Does the displacement track a parameter
   that is itself hour-keyed, or does it appear where nothing is hour-keyed at all?
3. **Test the obvious suspect explicitly.** Is the model's centre displaced because a blend weight
   between forecast high and current observation is mis-set by hour? Recall from the earlier diagnosis
   that width excess peaks at hours 5–9 and collapses at 14–16 as observations resolve the high — the
   same shape as an observation-weighting story.
4. **Say whether this is a bug, a mis-tuned constant, or an inherent modelling choice.** Those three
   have completely different fixes and completely different risk profiles.

## What a good answer looks like

Either "the hour-dependent centre bias is manufactured at stage X, and here is the evidence" — or a
clear statement that no single stage accounts for it and the displacement is emergent. **The second is
a perfectly good answer** and would tell us a post-hoc corrector really is the only available lever.

Do not build the fix even if you find it. I want the mechanism identified and evidenced first; the fix
is a separate, gated, post-release-#1 decision.

## Constraints

- **Read-only investigation.** No fit, no candidate, no transform, no parameter change, no production
  artifact, no `data/` write.
- **Do not take any tuning decision from 2026-07-27→07-30.** That window is burned.
- **Do not read or evaluate 2026-08-06→08-19.** It stays clean for the single confirmation run, and it
  must not be swapped for another window.
- Existing evidence may be re-read; no new fitted instrument may be created.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

**Timing:** the Toronto lock lands ~2026-08-03 and the release build runs from the production host no
earlier than 08-04. This mission is off the release path.

## Handback

`docs/roadmap/agent-report-<date>-workstation-centre-mechanism.md`: the traced centre-moving stages,
which one's hour profile matches your measured offsets, the bug / mis-tuned-constant / inherent-choice
verdict, and — if you find a source — what a minimal fix would touch and what its roll footprint would
be.
