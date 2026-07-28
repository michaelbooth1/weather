# Workstation handoff — 2026-07-27g: who breaks the floor, and what is it worth?

Missions 3+ of `-28c` are unchanged and still yours in the morning window. This mission runs
on the frozen corpus with no vendor call and no full-book read.

## Currency note — added 2026-07-28, three things changed after this was written

1. **Run this now.** The storage queue jumped ahead of it and is finished from your side;
   this is the live mission. `-28c` cannot start until the 01:00–08:30 ET window reopens.
2. **The storage rework is accepted.** I verified `6312e88d` is preserved as an ancestor, both
   release files are byte-identical to master, no trace of `allow_pinned_external_pointer`
   remains, it merges clean, and 175 focused tests pass on the merged state. Reusing
   `MIN_QUIET_SECONDS`/`source_is_quiet` rather than duplicating them was the right call. It
   merges here at 01:15 tonight and I apply the cleanup in the same window.
3. **That creates a dependency you must answer before your next window.** I will be
   compressing `order_books_long.csv` tonight. Your `-28c` full-book read runs *after* that.
   **State in your handback which representation that read consumes** — `.csv.gz` via the
   fallback, `order_books.jsonl`, or the uncompressed CSV. If it is the last one, say so
   plainly and I will exclude that family from tonight's apply rather than strand your next
   queue. I would rather reclaim less disk than break the profit question.

Master is now `7c33f90c`, not `9bc01ef1` as stated at the bottom. Streak is 7/14.

## Closing out `-27f`

`NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS` is a strong result, and the 61
irreducible rows are the part I value most: where `preblend == incumbent` within tolerance but
recorded differs, no convex blend can produce recorded, so that is an impossibility proof
rather than a failed fit. Lag zero winning uniquely kills my staleness hypothesis cleanly —
that is the fourth framing of mine measurement has killed this week, and the pattern is that I
propose a mechanism, find it plausible, and assemble corroboration instead of a test. I would
rather keep losing hypotheses at this rate than keep one that is wrong.

Also noted: you flagged your own deviation from the predeclared two-scan ceiling after the
timezone-validation failure, and you caught that the Austin/Dallas collision halves carry
preblend/replay-final mass `0.5` against incumbent/recorded `1.0` and declined to silently
renormalize. Both are exactly right.

The binding receipt design is accepted as a design. **I am not implementing it before the
lock** — it sits at the snapshot-persistence boundary, which is loop-loaded and streak-critical,
and we are 6/14 with the lock around 2026-08-03. It lands after.

## The fact I want to exploit

From your printed-floor table:

| Forecast | Cases with below-floor mass | Total below-floor mass |
| :--- | ---: | ---: |
| **Preblend** | **0 / 124** | **4.84e-13** |
| Replay-final | 108 / 124 | 12.504538 |
| Incumbent | 118 / 124 | 25.075771 |
| Recorded | 118 / 124 | 24.538691 |

The candidate is *clean*. Everything downstream is not. And the evening — where this
concentrates — is both where our deficit against replay-final is largest (`+0.235` categorical)
and where the market is close to perfect, because by then it is reading a thermometer rather
than forecasting. Near-resolved partitions are a large share of the corpus.

If mass below an already-observed floor is being introduced after a clean candidate, that is an
engineering defect with a measurable price, not a forecasting deficit. I want it localized and
priced.

## Mission 1, gate first: is the floor honestly ex-ante?

**Do this before any scoring, and stop here if it fails.**

The printed floor is `ROUND_HALF_UP(high_so_far)`. Everything below depends on `high_so_far`
being the maximum observed *as of the snapshot instant*, not an end-of-day or otherwise
forward-looking value. If it is contaminated, projecting onto it would manufacture a
spectacular fake improvement, and this whole mission is void.

Verify it against the frozen corpus: is `high_so_far` monotone non-decreasing within a
market-day as snapshots advance, and is it always less than or equal to the settled max? A
violation of either is disqualifying. Report the check and its result explicitly even if it
passes.

## Mission 2: localize the introduction

Given a clean preblend and a violating incumbent, some of the downstream violation is
arithmetic. Separate what is arithmetic from what is a defect:

1. **Is preblend clean by construction or by luck?** `0 / 124` with total mass `4.84e-13` looks
   like an explicit projection or clip, not an accident. If a floor-aware step exists and is
   applied to the candidate, name it — and then say what happens to it downstream. A floor
   guarantee that exists and is then discarded is a different bug from one that was never there.
2. **Attribute the violation.** For the 124 cases, decompose the below-floor mass of
   replay-final into the part explained by mixing in a violating incumbent at the artifact's
   own alpha, and any residual beyond that. If the residual is zero, the blend is merely
   propagating the incumbent's violation and the defect is upstream in the incumbent. If not,
   something else is adding it.
3. **Why does the incumbent violate at all?** Characterize it — is the below-floor mass
   concentrated in particular markets, hours, or floor magnitudes? You do not need to fix it;
   I want to know whether it looks like a missing projection, a stale input, or an unaware model.

## Mission 3: price the fix

Compute the counterfactual: project each lane's distribution onto the floor-feasible simplex —
zero the bands strictly below the printed floor, renormalize — and rescore.

Report, for replay-final and recorded, pooled and for the evening window specifically:

- categorical and binary Brier before and after projection;
- the full decomposition, so we can see whether the gain is reliability, resolution or both;
- how much of the remaining gap to the market this closes; and
- any case where projection makes the score *worse*, which would be an important surprise.

This is measurement of a counterfactual, not a proposal to deploy it. It bounds the prize. If
the prize is small, we stop talking about the floor; if it is large, it becomes the strongest
profitability lead we have, because it is engineering rather than research.

## Cautions

- The leakage gate in Mission 1 is the whole ballgame. A large gain from floor projection is
  exactly the shape of result that has been a bug here before. If `high_so_far` is even
  partially forward-looking, say so and stop.
- Projection onto an observed floor is *not* free skill. Be explicit that any measured gain
  assumes the floor was available at decision time, and confirm that from the corpus rather
  than from my assertion.
- Nothing here authorises a serving, model, floor-order, config or release change.

## Guardrails

- `data/` read-only with proven deny-write ACL; single declared output root outside the mirror.
- No model, blend, alpha, config, artifact, release, pointer, collector, scheduler, sizing,
  cap, trading or serving change. Measurement and written design only.
- Topic branches only; push without asking; never `master`, no PRs, no merges.
- No vendor request outside the declared window.
- NOT-DONE / NOT-REHEARSED first-class.

## Handback

`docs/roadmap/agent-report-<date>-workstation-who-breaks-the-floor.md`: the ex-ante gate result
first, the attribution of introduced mass, the incumbent characterization, and the priced
counterfactual with decompositions. Push all topic branches.

Context: master is `9bc01ef1` and carries all three of your reports. Streak 6/14, earliest lock
~2026-08-03. Your mm-measurable branch merges here at 01:15.
