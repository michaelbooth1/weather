# Workstation handoff 2026-09-06a — re-power the endpoints before `-08-16a` scores

Run this now. **Re-analysis and power arithmetic only: no fit, no retrain, no candidate, no scoring
of held candidates, no network, no reserved dates.**

> **THIS MUST LAND BEFORE 2026-08-05 04:30**, when `-08-16a` scores both frozen candidates. After
> that it is post-hoc and worthless. If you cannot finish in time, say so immediately and hand back
> whatever is settled — a partial answer before the deadline beats a complete one after it.

## What just happened, and why it invalidates the instrument

`-09-05a` (merged `d6aa5ef7`, report
`docs/roadmap/agent-report-2026-08-03-workstation-where-does-the-improvement-go.md`) established two
things that between them knock out the basis of our confirmation design.

**1. The 5.39% figure was never the served value of the correction.** It was
`separately_fitted_direct_served_correction` — a different transform, fitted directly in served
space, scored against `base_market_gap = 0.021361`. The raw 24.69% was scored against
`base_market_gap = 0.031532`. Two fits, two denominators. The propagated served value of the
*actual* frozen correction is **18.32%**, `[-21.03%, +55.81%]`.

**2. Under correct clustering, every interval crosses zero — including the raw one.** With a crossed
date/market pigeonhole bootstrap (2,000 replicates, seed 90501, dates and markets resampled
independently), raw HGB is **24.69% `[-7.41%, +54.68%]`**. `-08-24a`'s `[-0.015137, -0.000868]`
excluded zero only because it resampled market-days as exchangeable units, collapsing two dependence
dimensions into one.

Now look at `docs/operations/reserved-confirmation-window.md`:

| Endpoint | N at 5.39% | N at 2.5% midpoint |
| --- | ---: | ---: |
| **Frozen severe-tail SSE** | **4** | **9** |
| Pooled all-hour Brier | 53 (weak 3-date variance proxy) | 246 |
| 09:00–14:00 Brier | 504 | 2,337 |
| Toronto-only, any endpoint | 3,350 | 15,550 |

**Every cell in that table is indexed on 5.39%, and its variance came from the old clustering.**
`-08-16a`'s primary readout is the frozen severe-tail SSE, and its legitimacy rests on the `N = 4`
in the top-left cell. We now know both inputs to that cell are wrong.

## The question I cannot answer

**Is `-08-16a`'s primary endpoint actually powered at four dates, or not?**

Both inputs moved, **in opposite directions**:

- effect size was the wrong quantity — 5.39% was not this correction's served effect. Pushes N
  **down**.
- variance basis was the wrong clustering — crossed is wider than exchangeable. Pushes N **up**.

I do not know the net. Naive scaling (`N ∝ 1/effect²`) would drop the 09:00–14:00 row from 504 to
roughly 44, which would make the primary objective measurable for the first time in this project's
history. **I do not believe that number and neither should you** — it ignores the variance change
entirely. That is exactly the arithmetic I want done properly rather than guessed.

## Three subtleties, so you do not spend time rediscovering them

1. **18.32% does not transfer to the severe-tail row.** It was measured on the 09:00–14:00
   population (hours 9–14, 5 dates, 12 markets, 60 market-days, 2,868 snapshots). The severe tail is
   a *different* population — the 4.26% of rows carrying 60.2% of the loss. Do not substitute one
   into the other's power calculation. If the severe-tail effect size has to be re-derived, derive
   it; if it cannot be derived from available data, say that.
2. **The pooled all-hour row is already self-flagged as weak** in the file itself — "weak 3-date
   variance proxy". Whatever you do to it, do not let it silently harden into a real number.
3. **Most of the machinery already exists.** `-09-05a` computed the crossed bootstrap over the same
   population; reuse its evidence and its resampling code rather than rebuilding. This should be
   re-analysis, not a fresh replay. That is also how it fits inside the deadline.

## Pre-empting the answers I do not want

**"The effect is 3.4x bigger, so we are better powered — proceed."** No. That reads one input and
ignores the other. If you conclude we are better powered, show the variance side of the arithmetic
explicitly.

**"Read a few reserved dates to get a better variance estimate."** Absolutely not. Reserved is
**2026-08-06 → 2026-11-03**, and `docs/operations/reserved-confirmation-window.md` is the single
source of truth and wins over this document. Reading one destroys it permanently. A power analysis
is precisely the task that tempts you to peek at held-out data; do not.

**Endpoint shopping.** If the severe tail turns out underpowered, do **not** go hunting for whichever
endpoint happens to be significant now and nominate that. Any endpoint change must be stated as a
*rule* derived from the power arithmetic, pre-unblinding, dated and recorded — the same standard the
`-08-16a` amendment met when it voided the 53–54-slice tie-break. A change chosen after seeing which
way a result fell is not an amendment, it is a result.

**Do not re-fit the correction.** Use the frozen artifacts. Re-deriving the effect size by fitting
is circular and would repeat the error that produced the 5.39% figure in the first place.

**Do not treat 18.32% as a design effect size without arguing for it.** Its own interval spans
77 percentage points. If the defensible design input is a lower bound rather than a point estimate,
use the lower bound and say so.

## What I want back

1. **The corrected MDE / N table**, all four endpoints, under crossed date/market clustering, at
   whatever effect sizes you can defend. Replace the `5.39%` and `2.5%` columns with honest ones and
   name what each column now means.
2. **The number I most want: is the frozen severe-tail SSE powered at N = 4 — yes or no?** If no,
   what N does it need, and **what should `-08-16a` do at 04:30 on 08-05** — run as amended, run
   with a further amendment, or not run? Give me the amendment text if you recommend one.
3. **Does the 09:00–14:00 row move materially from 504?** This decides whether our stated primary
   objective is measurable at all, or whether we keep using the severe tail as a proxy for it.
4. **A sweep: which other published "interval excludes zero" claims in this repo survive crossed
   clustering?** `-08-24a`'s did not. I want the list of every load-bearing significance claim we
   are still carrying that was computed under exchangeable market-day resampling, and your judgement
   on which are now doubtful. Do not re-run them all — identify them and flag the ones that matter.
5. **A recommended diff to `reserved-confirmation-window.md`, written but NOT applied.** That file
   requires an explicit dated operator decision to change; I want the exact text to hand over, not a
   fait accompli. **Do not shorten the reservation** whatever the arithmetic says — extending is
   cheap, shortening after the fact is not.

**A clean negative is the most useful answer here.** If five non-reserved dates cannot support an
honest power estimate for any of these endpoints, say that plainly. It would mean `-08-16a` should
be re-scoped rather than run, and I would much rather learn that on 08-04 than read an
uninterpretable result on 08-05.

## Sequencing

Development window **2026-07-22 → 07-26** only, as `-09-05a` used. No 07-27 → 07-31 (burned), no
08-01 → 08-05 (`-08-16a`'s declared set), and nothing in the reserved window. This needs no release
pointer, no corpus, and no fresh dates.

## Constraints

- Base on `master` @ `d6aa5ef7`.
- **Reserved window is `2026-08-06 → 2026-11-03`** — see
  `docs/operations/reserved-confirmation-window.md`, which is the single source of truth and wins
  over any handoff text. Not read, enumerated, evaluated, or substituted.
- Also excluded: **2026-07-27 → 07-31** (burned) and **2026-08-01 → 08-05** (`-08-16a`'s declared
  set).
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary.
- **Never weaken the trusted observed-high floor.** `-09-05a` confirmed it is the top absorber and
  that the floor-compatible upstream projection is *worse*; the floor stays.
- **No network access.**
- **Do not fetch, backfill, refresh, or write any archive, artifact, sidecar, prior, or cache. Do not
  delete anything under `data/`.**
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror.
- **No** promotion, pointer change, serving change, scheduler change, capture restart, PR, merge, or
  master push. **No** mirror topology change, **no** ACL change, **no** paid-provider change.
- Topic branch only. Do not access the production host or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. **Lead with item 2** — everything else can
wait, that one has a deadline. If the answer is that we have been designing confirmations against an
instrument we never calibrated, say so plainly; that is worth more than a clean table.
