# Workstation handoff `-09-09a` — complete the age curve, and separate age from heat

Written 2026-08-04 by the operations master agent on the production host. Read this on
`origin/master` and execute it.

## What this fixes

`-09-08a` established the frozen-HGB cool bias and it **survived crossed clustering**: pooled
`-0.6641 °C-equivalent`, interval `[-1.1164, -0.2482]`. It could not answer its own decisive
question, and **that was my error, not the mission's.**

I mandated the `-09-07a` 34-date set and forbade re-deriving it. That set ends `2026-07-21` and
contains **zero August dates**, so June→August was unidentifiable. The 34-date set is scoped to
**candidate-clean** dates — it excludes Jul 22–26 because both held continuation candidates
serialized them as `fit_dates`. **`-09-08a` scored no candidate.** It measured the frozen incumbent,
for which candidate contamination is irrelevant. I imported a constraint that did not apply.

> **This handoff explicitly countermands that instruction.** Do **not** reuse the `-09-07a` 34-date
> set. Re-derive the population per §Population below.

## Population — re-derive it, incumbent-only

Admission bar, applied to **target dates**:

- `promotion_countable = True` (**not** `quality_grade = complete`, which yields only 9 fleet dates),
- replayable from captured inputs,
- **≥8 markets** on the date (same structural bar as `-09-07a`'s primary set, so the two are
  comparable),
- target date **on or before `2026-08-05`**.

Candidate `fit_dates` are **not** an exclusion criterion in this mission. Nothing here scores a
candidate.

This should recover roughly 15 additional dates (`2026-07-22` → `2026-08-05`) on top of the 34,
and — critically — the first August support the project has.

**Report the exact date list you admit, with per-date market counts, and state the June / July /
August split.** If a date you expect is missing, say which and why rather than working around it.

### Timing

**Amended 2026-08-04:** with the reservation re-based, August support is no longer capped at 5 dates
and there is no deadline. Run when convenient; every extra settled date strengthens the age curve.
Report the August N you actually obtained rather than a target.

## Questions

### Q1 — the age curve, June through August

Re-run `-09-08a`'s signed centre-error measurement on the corrected population. Report the pooled
estimate, the per-month estimates, month contrasts, and the calendar slope — all with crossed
date × market intervals and stated N.

`-09-08a`'s comparable figures, for continuity: June `-0.1996 [-0.6234, +0.2005]`, July `-1.0586
[-1.6512, -0.4319]`, July−June `-0.8590 [-1.5581, -0.1359]`, slope `-0.03553 °C-eq/day
[-0.06176, -0.00945]`.

**State plainly whether adding August strengthens, weakens, or reverses the staleness reading.**

### Q2 — separate artifact age from temperature level (the decisive question)

**This is the question the mission exists for.** Staleness is not the only hypothesis consistent with
a June→July worsening. "Bias scales with realized temperature level" — limited warm-class support,
shrinkage toward a cooler training mean — predicts **exactly the same** monthly pattern, because July
and August are hotter than June.

The two point in opposite operational directions:

- **Age carries the signal** → a retrain genuinely repairs it, its value decays with artifact age, and
  **retrain cadence becomes a first-class operational parameter we have never set.**
- **Temperature level carries the signal** → it is *not* staleness. A retrain on a cooler
  distribution would **reproduce the defect**, and the repair is warm-tail support / class coverage,
  not recency. Refreshing on schedule would be cargo cult.

Estimate both together — bias against artifact age **and** against realized temperature level (and/or
position in the market's warm tail) — and report which carries the signal once both are present, with
intervals. If they are not separable on this support, **say so and stop**; an honest
non-identification is worth more than a forced attribution. Report the collinearity you actually
observe.

### Q3 — does the `2026-07-31` regime boundary confound the slope?

`2026-07-31` is a `rows[-1]` regime boundary, concerning **artifact provenance, not target-date age**.
The new dates straddle it, so it now binds where it did not before.

One frozen artifact set applied retrospectively to all target dates does not itself mix artifacts —
but **the captured replay rows either side of the boundary may not be equivalent**, and if they are
not, an "August effect" could be a **regime** effect wearing age's clothes.

Test it. Report the slope with and without the boundary crossing, and say whether the age result
survives. If it does not, that finding outranks Q1 and Q2 and should lead your report.

### Q4 — Austin

Austin was the lone **wholly positive** market (`+0.7246 F [+0.0162, +1.6353]`) against seven wholly
negative ones. On the larger population, is that stable, or did it regress toward the fleet? A market
whose sign genuinely inverts is either real structure worth understanding or a contract defect worth
finding. Short answer is fine — do not let it consume the mission.

## Deliverable

1. Answers to Q1–Q4 with N and crossed intervals throughout.
2. **What the first retrain must do differently under each Q2 outcome.** Release #1 freezes these June
   HGBs; the first retrain is the only event that can change them, and it has not been scheduled. This
   is the operational payload of the mission — write it so it can be acted on.
3. A `## What would falsify this` section.

## Constraints

> ### AMENDED 2026-08-04 — the 2026-08-05 ceiling is GONE
>
> This handoff originally imposed a hard ceiling at `2026-08-05` because `2026-08-06 → 2026-11-03`
> was reserved. **The operator re-based the reservation on 2026-08-04: nothing is reserved today.**
> The window is armed but undated, and begins only when the first retrain candidate is frozen.
>
> **Consequence for this mission — it gets materially better.** The August support that made Q1/Q2
> answerable was capped at 3–5 dates; it is now limited only by what has settled. Use **every settled
> `promotion_countable` date available when you run**, and report the June/July/August split you
> actually obtained.
>
> This strengthens Q3 too: the `2026-07-31` `rows[-1]` boundary can now be tested with real support on
> both sides rather than a handful of dates.

**`docs/operations/reserved-confirmation-window.md` is the single source of truth and outranks this
document — re-read it when you run.** If a window has been declared there by then, it is absolute:
reserved target dates must not be read, replayed, scored, or inspected, and reading one destroys it
permanently. Note the distinction that still applies: the reservation is on **target dates**, not
processing days, so settling a non-reserved target date using data produced later is fine.

**The trusted observed-high floor is out of scope and must not be weakened, softened, re-tuned, or
"improved" in any variant.** It is load-bearing.

**Clustering.** Crossed date × market on every interval. If an interval crosses zero, say so in the
same sentence as the point estimate. Do not quote proxy sensitivity as candidate power.

**No fitting, no retraining, no candidate scoring, no promotion, no artifact change, no release/PIT
path change.** This measures the frozen incumbent. The two held candidates remain out of scope.

**Do not touch the release or PIT path.** The release #1 build runs on the production host around
this time; a change there would collide with it.

**Network:** `git fetch` and `git push` are permitted and required. **No provider calls, no paid
sources, no new collection.** Everything needed is captured.

Push `codex/workstation-complete-the-age-curve-2026-09-09a`. **No PR, no merge.** Report to
`docs/roadmap/agent-report-2026-08-06-workstation-complete-the-age-curve.md` (adjust the date in the
filename to the day you actually run).

## How to disagree

If the population cannot be re-derived as specified, if the age/heat separation is not identifiable,
or if the boundary invalidates the design — **say so and stop.** `-09-08a` was strengthened by
refusing to substitute a population when mine was wrong. Do that again if needed.
