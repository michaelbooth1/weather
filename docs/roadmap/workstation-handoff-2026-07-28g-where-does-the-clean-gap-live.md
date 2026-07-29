# Workstation handoff — 2026-07-28g: where does the clean gap actually live?

This is `-27g` Missions 2 and 3, POST-only, plus one question the regime split made obvious.
Everything here runs on the frozen corpus with no vendor call and no full-book read.

## What the split changed

Thank you for forcing it. On the clean POST regime we are **1.243x** the market's Brier
(preblend `0.047572` vs `0.038280`), not the 1.7x we had been quoting, and the decomposition is
**reliability `0.000322`, resolution `0.011251`** — essentially perfect calibration with the
entire residual in sharpness. My blend refutation was a pooling artifact and I have retracted
it: on POST the blend *costs* `0.002281`, about 20% of the remaining gap.

## The question the split made obvious

On POST, preblend wins on **two independent measures**:

- lower Brier (`0.047572` vs `0.049853`); and
- zero below-floor cases (`0 / 124`, against `108 / 124` for replay-final).

**Are those the same defect or two?** If the blend's `0.002281` cost is concentrated in the
partitions where it introduces below-floor mass, there is one defect with one fix, and the
floor violation *is* the blend cost. If the cost is spread evenly across partitions with and
without below-floor mass, they are independent and each needs its own remedy.

Answer that directly: partition POST rows by whether replay-final puts mass below the printed
floor, and report the preblend-minus-final Brier delta within each group. Include the group
sizes — if the below-floor group is tiny, it cannot carry `0.002281` and the question answers
itself.

## Mission 1: re-unmix the gap on clean data

The old unmixing — predawn ~28% worse, primary ~31%, evening catastrophic — was computed on the
pooled corpus and is now suspect. Redo it POST-only:

1. Gap to market **by hour**, all 24, and for the named cuts predawn 03–05, primary 09–14,
   evening 20–23.
2. Split by **near-resolved versus genuinely uncertain** partitions, however you defined that
   previously, with the counts.
3. For each cut, the reliability/resolution decomposition, so we can see where sharpness is
   actually lost.

The decision this drives: **if the clean-regime gap is still concentrated where the answer is
already publicly observable, the remaining work is engineering. If it is spread across
genuinely uncertain hours, it is forecasting.** Those imply completely different programmes and
I do not want to choose between them by assumption.

## Mission 2: localize the below-floor mass, POST-only

As originally specified: given a clean preblend and a violating incumbent, decompose
replay-final's below-floor mass into the part explained by mixing in a violating incumbent at
the artifact's own alpha, and any residual beyond that. Zero residual means the blend merely
propagates the incumbent's violation and the defect is upstream. Non-zero means something else
adds it.

Also: is preblend clean **by construction or by luck**? `0 / 124` with total mass `4.84e-13`
looks like an explicit projection. If a floor-aware step exists and is applied to the candidate
and then lost downstream, that is a different bug from one that never existed.

## Mission 3: price the projection, POST-only

Project each lane onto the floor-feasible simplex, rescore, and report before/after with full
decompositions, pooled and evening-specific. Use the **rounded** floor as the bound —
`ROUND_HALF_UP(high_so_far)` had zero settlement exceedances, and the raw comparison against a
whole-degree bucket is over-strict. Exclude no-constraint instants from the projected lane
rather than projecting them onto an imaginary floor.

Report any case where projection makes the score **worse**; that would be an important surprise.

## Why this matters more than it did yesterday

At 1.243x with near-zero reliability error, the market-making question stops being academic. A
well-calibrated book that is only slightly less sharp than the market is a much better maker
candidate than a 1.7x one. **Missions 3+ of `-28c` are now the most commercially interesting
thing in the queue** and should run in the next 01:00–08:30 window — this mission is what fills
the gap until then, not a replacement for it.

## A caution about me

Six mechanisms from me this week: five died, and the survivor only survived after you removed a
confound I had not noticed. I am now proposing that the blend cost and the floor violation are
the same defect. **Treat that as a seventh candidate to eliminate, not a lead.** It dies if the
below-floor group is too small to carry the delta, and it dies if the delta is similar in both
groups. Say so if it does.

## Guardrails

Unchanged. `data/` read-only, single declared output root, no model/blend/serving/config/
release change, topic branches only, no PR/merge/master push, NOT-DONE first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-clean-gap-anatomy.md`: the same-defect-or-two
answer with group sizes first, the POST-only unmixing by hour and by resolvedness, the
below-floor localization, and the priced projection.

Context: streak 7/14, lock ~2026-08-03 — which now gates a quantified `0.002281` configuration
win, since acting on it needs the release binding we still lack. Storage merges here at 01:15.
