# Workstation handoff — 2026-08-05a: how much of the centre ceiling is actually reachable?

Accepted and merged (`810d5397`). This is the most decisive analysis the project has produced, and it
changes the engineering order. **Centre first. No global sharpening.**

Three things you did that make the answer trustworthy rather than merely large:

- **The liberal sensitivity.** Clipping infeasible entropy targets instead of skipping them moves width
  to 19.43%/13.20% and centre to 59.66%/76.43% — so the ranking is not an artifact of the strict
  feasibility rule. Without that check the whole result would have been arguable.
- **The infeasibility finding is itself the argument.** For 4,433 snapshots the market entropy is below
  the minimum achievable while holding the model centre. Width-only is not merely low-value on those
  rows, it is **not well-defined**. That is a structural reason centre is primary, not a numerical one.
- **You reported that the oracle creates new severe rows** (width 36, centre 189, both 13). Nobody
  asked for that and it argues against your own headline. It is exactly why I can act on the rest.

I have recorded, as standing guidance: **never build a global sharpen.** 25.37% of distributions are
already narrower than the market, and Miami and Chicago are narrower on average — a global transform
would push them further the wrong way.

## The finding that shapes the mission

The centre error is **market-conditioned with differing signs**: Seattle −1.574, Denver −1.201, Dallas
−1.213, Miami −0.951, versus Chicago +0.667, San Francisco +0.681, NYC +0.317. A single global centre
shift is therefore also wrong. Any correction must be conditional.

And the failures sit **near the forecast high**, not in far tails — offsets 0/−1/+1 carry 75.87% of
outside-five severe contribution. This is a precision problem about which of two or three adjacent
bands wins.

## Mission: convert the ceiling into an achievable estimate

The 74.97% tail ceiling is **hindsight**. The only question that matters now:

> **How much of the centre displacement is predictable from information available at cutoff time?**

If it is noise, the achievable gain is near zero no matter how large the ceiling. If a meaningful
fraction is predictable, that is the model programme for the next quarter.

Work up a ladder, simplest first, and report each rung's out-of-sample recovery as a **fraction of the
74.97% tail ceiling**:

1. **Per-market constant centre offset.** The crudest possible correction. If this alone recovers a
   real fraction, it is cheap, robust, and auditable.
2. **Per-market × hour.** You showed the width phenomenon is hour-conditioned; test whether centre is
   too.
3. **Feature-conditioned.** Only if the first two justify it, and only from cutoff-available features.

Gate every rung on **both** aggregate positive excess Brier **and** the ≥30-point tail, because we
already know a median-row improvement can hide worse severe errors.

## Leakage protocol — declare it before you run, not after

This is the highest leakage-risk work in the project. Item-224's apparent win was leakage, and you
yourself caught a 31,092-day pool cutoff leak in earlier work. So:

- **Declare the train/test split in writing before fitting anything.** No reruns after seeing test
  scores. If you need a second pass, say so and report both.
- Fit only on cutoff-available information. No post-cutoff observation, no settlement, no market price
  as a feature.
- **Be explicit that 2026-07-22→07-30 is already heavily inspected.** We derived the entire geometry
  from it, so any estimate measured on it is optimistic and is *not* a clean holdout. Say so plainly
  rather than letting the number stand unqualified.
- **Nominate a genuinely untouched forward window** — dates after this analysis, which nobody has
  looked at — and reserve it for later confirmation. Do not evaluate on it now. I want it clean when we
  need it.

A result of "centre error is mostly unpredictable" is a completely acceptable and valuable answer. It
would tell us the remaining gap is irreducible information and redirect the programme toward new
inputs instead of transforms. Do not tune to avoid that conclusion.

## Constraints

- **Analysis only.** No production artifact, no serving change, no `data/` write, no promotion, no
  transform shipped. A fitted corrector here is a measurement instrument, not a candidate.
- Wholly after the `2026-07-31` `rows[-1]` boundary.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

**Timing:** the Toronto lock lands ~2026-08-03; the release build runs from the production host no
earlier than 08-04. This mission stays off the release path. Candidate engineering waits for release #1
anyway, when nightly retrain and the bound scorecard can measure it properly — which is exactly why
establishing predictability now is the right use of the interval.

## Handback

`docs/roadmap/agent-report-<date>-workstation-centre-predictability.md`: the pre-declared split, each
rung's out-of-sample recovery as a fraction of the 74.97% tail ceiling, aggregate-and-tail figures for
both, the nominated untouched forward window, and a plain verdict on whether centre correction is worth
engineering.
