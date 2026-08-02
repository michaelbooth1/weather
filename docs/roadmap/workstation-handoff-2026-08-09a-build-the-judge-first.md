# Workstation handoff — 2026-08-09a: build the judge before the thing it judges

Accepted and merged (`82b94190`). The specification is production-grade and I am adopting it as the
plan of record for the first model change after release #1.

You also corrected my error precisely rather than working around it: the `feature_subset = "all"`
artifact I probed is the pooled **direct-band** model, not the per-market base HGBs that produce
`replayed_p`, and you inventoried both rather than just the one that suited the argument. The answer is
unambiguous — **all 168 bundles select and split on the observed-high family, `high_so_far` alone
carrying 267,253 splits (17.63%), rising to 40.90% of splits by hour 20.** The model sees the floor
perfectly well. The objective is what is wrong.

`D = Y − F` is the right shape. It converts "predict an unconditional high, then truncate" into
"predict the continuation above a floor we already know", which makes sub-floor mass **structurally
impossible** instead of removed after the fact. Keeping the hard-floor stages as independent defense,
and preserving the incumbent lane where no floor exists, is the correct conservatism.

Three things in the gate design I want to name, because they are the difference between a spec and a
wish: the newly-severe cap is **inherited** from the market×hour warning rather than invented; the
floor invariant includes a **metamorphic test** rather than only fixed assertions; and
*"fixing such a bug does not authorize a second unblinded confirmation run"* closes the escape hatch
that would otherwise quietly turn one confirmation into many.

## Mission: implement the evaluation harness — not the candidate

Execution of the retrain is blocked until release #1 exists, and that is the production host's critical
path. But one part of your spec can be built now, and building it now is materially better than
building it later:

> **Implement the qualification-gate harness and prove it against the incumbent, before any candidate
> exists.**

Why the ordering matters: a gate written after seeing a candidate's numbers is a gate shaped by those
numbers, however carefully one tries. Building the judge first, while there is nothing to judge, is the
strongest available guarantee that the thresholds mean what the spec says.

Concretely:

1. Implement every hard gate in your `## Qualification gates` table as executable checks over the
   accepted corpus and replay: corpus/target validity, total-Brier non-regression with the market-day
   block bootstrap, severe-tail improvement on the incumbent-frozen set, the newly-severe cap,
   near-floor three-way allocation, probability mass, the floor invariant including the metamorphic
   raise-`F` fixture, train/serve parity, captured-input replay, release binding.
2. **Run it with the incumbent as both candidate and baseline.** Every comparative gate should return
   an exact tie, and every invariant gate should pass. Any gate that cannot produce that degenerate
   result is mis-specified — report it as a spec defect and fix the spec, not the harness.
3. Emit the protected reports the spec requires — by market, capture hour, floor source, binding
   strength, forecast-relative winner position, and `D` class — so the "one catastrophic slice"
   blocker is mechanically checkable rather than a matter of judgement.
4. Note any gate that turns out to be unimplementable or ambiguous as written. Finding those now is
   free; finding them mid-confirmation is not.

## Constraints

- **Harness only. No candidate, no retrain, no fitting, no serving change, no artifact, no `data/`
  write.** The harness is a measurement instrument.
- Keep it on a topic branch. I will not merge implementation code before the lock; a roll-sensitive
  merge in the next 48 hours is out of the question regardless of quality.
- **Do not read or evaluate 2026-08-06 → 08-19**, and do not swap it. The harness must be exercised
  against the accepted July corpus only.
- No tuning decision from 2026-07-27 → 07-30.

## Guardrails

Unchanged. `data/` read-only, one declared run root outside the mirror, topic branches only, no PR, no
merge, no master push, no promotion/pointer/serving/scheduler/capture/mirror/ACL change, never read or
expose the sync credential.

## Handback

`docs/roadmap/agent-report-<date>-workstation-gate-harness.md`: which gates are implemented, the
incumbent-versus-incumbent degenerate run showing exact ties and passing invariants, any gate found
ambiguous or unimplementable as specified, and the resulting spec corrections.
