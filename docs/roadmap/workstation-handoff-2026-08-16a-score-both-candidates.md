# Workstation handoff 2026-08-16a â€” score both candidates on the same dates

> **DO NOT RUN BEFORE 2026-08-05 04:30 local.** `-08-14a` was dispatched a day early and could not
> evaluate anything because the labels had not arrived. This mission is worthless if run before all
> four declared dates are on the mirror. If you are reading this earlier, stop and wait.

> ## AMENDED 2026-08-03 20:52, BEFORE ANY SCORING â€” read this first
>
> `-08-04a` measured the instrument this mission was going to judge with, and it is broken:
> **the 53â€“54-slice catastrophic gate falsely rejects a uniformly better candidate 99.885%â€“99.9905%
> of the time.** Its output is very close to a constant. That means the 19-of-54 and 3-of-53 slice
> breaches reported by `-08-12a` and `-08-13a` carry almost no information about those candidates.
>
> This amendment is made **pre-unblinding** â€” nothing in this mission has been scored â€” and it
> changes the instrument, not the hypothesis. That distinction is the whole reason it is legitimate,
> and it is why it is dated and recorded here rather than applied silently at scoring time.
>
> **Three changes, nothing else:**
>
> 1. **Tie-break 4 is void.** Do not rank on "fewest catastrophic protected slices". Still report the
>    raw count for continuity with `-08-12a`/`-08-13a`, explicitly labelled non-informative. If the
>    lexicographic rule reaches a tie at step 4, fall through to step 5 (the simpler artifact).
> 2. **Add the corrected gate**: the one-sided two-way-cluster max-T harm-evidence test controlling
>    familywise error at 5%, per `-08-04a`. Report it alongside, as the gate that actually carries
>    information about per-slice harm.
> 3. **Demote the primary-slice readout to directional.** Four dates cannot resolve the 09:00â€“14:00
>    fleet endpoint â€” the 14-date MDE is 32.30% of the served gap, so at four dates it is far worse.
>    Report it, and label it directional. **Do not call any 09:00â€“14:00 result a confirmation.**
>
> **Elevate the frozen severe-tail SSE to this mission's primary readout.** It is the one endpoint
> genuinely powered at this N: `-08-04a` puts the fleet requirement at **4 dates** at the optimistic
> effect and **9** at the midpoint, and this mission has four. The tail is also where the conditional
> correction improved all five held-out dates. If the severe tail moves, that is the headline; if it
> does not, that is the headline.
>
> Everything else â€” frozen artifacts, the declared date set, the harness, seed, repetitions, and
> steps 1, 2, 3 and 5 of the choice rule â€” is **unchanged**.

Two frozen artifacts now exist and neither has been scored on evidence it did not help build. This
mission spends the remaining ordinary date budget once, on both of them, on identical dates.

## The frozen inputs â€” nothing here may change

| Item | Identity |
| :--- | :--- |
| Base gated candidate | `d542ec0955f5fa7e7feab8541d78ba124d8f99f7f556cd7f1e0a2290f8275c85` |
| Repaired candidate | `ba6cd8b7c02a6d6890762b17ab139fb9a3afbf146239b9e617ea192eea4970ef` |
| Application gate (both) | `floor_available and floor_removed_mass > 0.20` |
| Smoothing strength (repaired) | `1.00`, form `post_blend_d1_valley_pool` |
| Harness | the held `-08-09a` harness, seed `20260809`, 10,000 repetitions |

No refit, no reselection, no threshold change, no smoothing-strength change, no new variant. If any
artifact changes, this stops being a fair test and the dates are burned.

## The declared score set

**July 31, August 1, August 2, August 3.** Four dates, roughly 48 market-days.

Declare that list in the report before scoring any of it. It is fixed. Do not extend it after seeing
a result and do not drop a date that scores badly. If a declared date is genuinely missing labels,
report it missing â€” do not wait on it and do not substitute.

July 31 is restated as already-scored for the base candidate and must be labelled as such. The
**fresh** evidence is August 1â€“3, and it is fresh for both artifacts.

## Pre-commit which candidate wins, before scoring

Scoring two candidates on one date set is a fair comparison only if the choice rule is fixed first.

1. Fewest failed primary gates.
2. Then the smaller one-sided 95% market-day bootstrap upper bound.
3. Then the lower newly-severe rate.
4. Then the fewest catastrophic protected slices.
5. Then the **simpler** artifact â€” the base candidate â€” on an exact tie.

This is the `-08-13a` lexicographic rule with an added simplicity tie-break. Do not deviate from it
after seeing results.

## What I want back

1. **Per-date deltas** for both candidates, one row per calendar day. This is the replication
   question: does the July 31 improvement recur on August 1â€“3, or was it one good day?
2. **Pooled multi-day estimates** for both, with the bootstrap recomputed over the full market-day
   set across all four dates.
3. **August 1â€“3 alone**, separately from the pooled figure, since July 31 is not fresh for the base.
4. All three primary gates, both candidates.
5. **The structural check on fresh data:** does the repaired candidate hold mean
   `P(D1) >= P(D>=2)` on qualified D1 rows outside the development window, and does the `D_class=D1`
   slice stop failing? The repair was selected on 54 development snapshots; this is the first
   independent test of it.
6. Whether `capture_hour=14` and `capture_hour=17` recur.

   **Pre-registered predictions, added 2026-08-02 from the `-08-17a` diagnosis.** That mission
   separated the two failures into distinct mechanisms, so this is now a test of whether we
   understand the model, not just a measurement:

   - **Hour 17 is the recurring D1-valley mechanism**, which the `-08-15a` ordinal repair directly
     targets. **Prediction: hour 17 improves under the repaired candidate relative to the base.**
   - **Hour 14 is a distinct cold-forecast over-continuation failure**, concentrated in Los Angeles,
     NYC, and Denver, which the repair does not address. **Prediction: hour 14 does not improve
     materially under the repair.**

   Report both predictions as confirmed or refuted, explicitly. If hour 17 fails to improve, the
   D1-valley diagnosis was wrong and the repair is not doing what we think. If hour 14 *does*
   improve, we do not understand why the repair works, which matters more than the Brier number.
7. Whether the excluded rows still contribute **zero** newly-severe rows for both candidates. They
   must, by construction; if not, something crosses the gate and that is the headline.

## If the repair overshoots

If the repaired candidate is worse than the base on fresh dates, say so plainly â€” do not soften it.
And note for the record: **a smaller smoothing strength is not the remedy.** Both `0.50` and `0.75`
failed the structural criterion during selection, so there is no weaker eligible setting inside this
form. Overshoot would mean the form itself is wrong â€” pooling valley snapshots to exact equality is
too strong a prior â€” and the next attempt would need per-snapshot monotonicity or smoothing across
the full D-support instead of a three-way collapse. Do not attempt that here.

## What earns the confirmation window

Unchanged from `-08-14a` and still binding: a candidate becomes worth taking to the reserved window
only if **all three primary gates pass on its pooled multi-day estimate** *and* its per-date deltas
are consistently negative rather than carried by one day.

Anything less and both stay held.

**2026-08-06 â†’ 08-19 remains untouched** â€” not read, enumerated, evaluated, or substituted. Note that
August 1â€“3 exhausts the ordinary date budget: August 4 and 5 are the only dates left before the
reserved window, so this is close to the last honest scoring pass available.

## Constraints â€” unchanged

- Base on `codex/workstation-repair-d1-anchor-2026-08-15a` @ `8377873e`. It and every parent are held
  and unmerged on purpose. Do not merge any of them.
- **July 22â€“30 stays burned** and may not enter this evaluation at all.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.** Control, not a tunable.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- **Scope the freshness gate to exactly the four declared dates.** Do not gate on the mirror being
  current to today â€” it cannot be.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Expect both artifacts to remain held
regardless of outcome. By the time this runs the production host will be at or past its release-#1
lock, and nothing here touches that path.
