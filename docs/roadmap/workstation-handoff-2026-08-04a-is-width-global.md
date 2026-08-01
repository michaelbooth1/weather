# Workstation handoff — 2026-08-04a: is the width excess global, and what is each lever worth?

You killed my marine hypothesis and you were right to. Merged at `49c3271d`.

Three independent proofs — zero marine names and zero tree splits across all 31 artifact hours; the
`_evaluate_feature_model_for_cutoff` selection mechanism that drops the columns before inference; and a
direct in-memory counterfactual measuring **0/767** changed distributions at max L1 `0.0`. Using
Houston's 391 genuinely-observed marine snapshots as the control was the move that made it airtight:
it proves the extraction path is live and *still* has no effect, which forecloses the obvious rebuttal.

You also refused to promote a real correlation into a cause — Houston's 17.86% vs 7.16% severe rate on
marine-unavailable rows is exactly the kind of number that gets over-read, and you called it a
time/market marker because the counterfactual said zero. That is the discipline that makes the rest of
your reporting worth acting on.

I have recorded the marine gap as a **data-maintenance** finding only, deferred to after release #1,
with your condition attached: it cannot be fixed by backfilling alone, because it needs a retrain with
an artifact that actually declares the columns.

## What your diagnosis changes about the plan

Two numbers reorganise everything:

- **4.262% of rows carry 60.205% of the positive excess Brier.** This is a severity problem. Every
  future gate must include the ≥30-point tail, because a median-row improvement can hide worse severe
  errors.
- **80.22% of that severe tail lies outside the five retained bands.** So the band-scoped repair path I
  was walking us down addresses at most a fifth of the tail. Good thing you measured it before anyone
  built a candidate.

And the sharpest fact in the report: **the market's mode is the realized winner 94–99% of the time; ours
is ~24%.**

## Mission: size the levers before we build one

Both clusters share **excess width** (effective band count +1.257 coastal, +1.467 inland). Width may
therefore be a global property of our distributions rather than a band-scoped defect — and if it is,
the five bands are the wrong unit of work entirely.

Answer three questions, in order:

1. **Is the width excess global or concentrated?** Measure effective-band-count excess (model minus
   market) across **all** markets and bands in the window, not just the five. Give me its distribution:
   is nearly every row too wide, or is it concentrated in identifiable slices? Break it out by market,
   by band position relative to the forecast high, and by hour.

2. **Where is the other 80% of the severe tail?** Characterise the 7,513 severe rows outside the five
   bands the same way you did the 1,519 inside. Do they show the same two geometries, a third, or no
   coherent shape?

3. **Oracle ceiling per lever — this is the one I care most about.** Without building any candidate,
   compute the upper bound each lever could deliver on this window:
   - perfect **width** correction (match the market's effective band count, keep our centre);
   - perfect **centre** correction (match the market's expected band index, keep our width);
   - both together.

   Report each as reduction in total positive excess Brier and in the ≥30-point tail specifically.
   These are oracles using the outcome — **explicitly not achievable and not evidence** — and must be
   labelled as ceilings. Their only job is to tell us which lever is worth engineering before we spend
   weeks on one. If the width ceiling is small, we stop talking about sharpening.

## Constraints

- **No candidate, no fitting, no tuning, no transform, no production artifact, no `data/` write.**
- Oracle constructions must be unmistakably labelled non-achievable and must never be reusable as
  evidence for a later gate.
- Same window or a declared superset, wholly after the `2026-07-31` `rows[-1]` boundary.
- Declare leakage posture as before; oracles use outcomes by construction, so state that plainly rather
  than implying independence.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

**Timing:** the Toronto lock lands ~2026-08-03 and the release build starts no earlier than 08-04 from
the production host. This mission is deliberately off the release path. Expect candidate work to begin
only after release #1, when nightly retrain and the bound scorecard can actually measure it — which is
also why sizing the levers now is the right use of the interval.

## Handback

`docs/roadmap/agent-report-<date>-workstation-width-ceiling.md`: the global width-excess distribution,
the characterisation of the out-of-band severe tail, and the three oracle ceilings with their tail-
specific figures — plus your recommendation of which single lever to engineer first, or a plain
statement that neither ceiling justifies the work.
