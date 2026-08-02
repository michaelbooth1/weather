# Workstation handoff 2026-08-16a — score both candidates on the same dates

> **DO NOT RUN BEFORE 2026-08-05 04:30 local.** `-08-14a` was dispatched a day early and could not
> evaluate anything because the labels had not arrived. This mission is worthless if run before all
> four declared dates are on the mirror. If you are reading this earlier, stop and wait.

Two frozen artifacts now exist and neither has been scored on evidence it did not help build. This
mission spends the remaining ordinary date budget once, on both of them, on identical dates.

## The frozen inputs — nothing here may change

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
report it missing — do not wait on it and do not substitute.

July 31 is restated as already-scored for the base candidate and must be labelled as such. The
**fresh** evidence is August 1–3, and it is fresh for both artifacts.

## Pre-commit which candidate wins, before scoring

Scoring two candidates on one date set is a fair comparison only if the choice rule is fixed first.

1. Fewest failed primary gates.
2. Then the smaller one-sided 95% market-day bootstrap upper bound.
3. Then the lower newly-severe rate.
4. Then the fewest catastrophic protected slices.
5. Then the **simpler** artifact — the base candidate — on an exact tie.

This is the `-08-13a` lexicographic rule with an added simplicity tie-break. Do not deviate from it
after seeing results.

## What I want back

1. **Per-date deltas** for both candidates, one row per calendar day. This is the replication
   question: does the July 31 improvement recur on August 1–3, or was it one good day?
2. **Pooled multi-day estimates** for both, with the bootstrap recomputed over the full market-day
   set across all four dates.
3. **August 1–3 alone**, separately from the pooled figure, since July 31 is not fresh for the base.
4. All three primary gates, both candidates.
5. **The structural check on fresh data:** does the repaired candidate hold mean
   `P(D1) >= P(D>=2)` on qualified D1 rows outside the development window, and does the `D_class=D1`
   slice stop failing? The repair was selected on 54 development snapshots; this is the first
   independent test of it.
6. Whether `capture_hour=14` and `capture_hour=17` recur. I expect at least one not to.
7. Whether the excluded rows still contribute **zero** newly-severe rows for both candidates. They
   must, by construction; if not, something crosses the gate and that is the headline.

## If the repair overshoots

If the repaired candidate is worse than the base on fresh dates, say so plainly — do not soften it.
And note for the record: **a smaller smoothing strength is not the remedy.** Both `0.50` and `0.75`
failed the structural criterion during selection, so there is no weaker eligible setting inside this
form. Overshoot would mean the form itself is wrong — pooling valley snapshots to exact equality is
too strong a prior — and the next attempt would need per-snapshot monotonicity or smoothing across
the full D-support instead of a three-way collapse. Do not attempt that here.

## What earns the confirmation window

Unchanged from `-08-14a` and still binding: a candidate becomes worth taking to the reserved window
only if **all three primary gates pass on its pooled multi-day estimate** *and* its per-date deltas
are consistently negative rather than carried by one day.

Anything less and both stay held.

**2026-08-06 → 08-19 remains untouched** — not read, enumerated, evaluated, or substituted. Note that
August 1–3 exhausts the ordinary date budget: August 4 and 5 are the only dates left before the
reserved window, so this is close to the last honest scoring pass available.

## Constraints — unchanged

- Base on `codex/workstation-repair-d1-anchor-2026-08-15a` @ `8377873e`. It and every parent are held
  and unmerged on purpose. Do not merge any of them.
- **July 22–30 stays burned** and may not enter this evaluation at all.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.** Control, not a tunable.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- **Scope the freshness gate to exactly the four declared dates.** Do not gate on the mirror being
  current to today — it cannot be.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Expect both artifacts to remain held
regardless of outcome. By the time this runs the production host will be at or past its release-#1
lock, and nothing here touches that path.
