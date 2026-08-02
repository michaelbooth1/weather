# Workstation handoff 2026-08-13a — gate the lane on floor informativeness

`-08-12a` returned a correct FAIL and a very informative one. Read that report first; this mission
is its direct successor.

## What the last run actually showed

Nineteen protected slices failed, but they are not nineteen problems. Every failing dimension is a
proxy for one variable — **how much the canonical floor already knows** — and binding strength is
cleanly monotone with a single sign change:

| Floor-removed mass | Brier delta | Severe rows | |
| :--- | ---: | ---: | :--- |
| `>1e-6 to 1%` | +0.007064 | 1,107 → 1,167 | FAIL |
| `>1% to 5%` | +0.004903 | 811 → 1,257 | FAIL |
| `>5% to 20%` | −0.002371 | 625 → 543 | PASS |
| `>20%` | −0.007972 | 1,335 → 423 | PASS |

Capture hour says the same thing from the other end: hours 18–23 drive severe rows to 18, 11, 12, 2,
0, 0, while hours 10, 13, 14 rise to 301, 281, 316. `D0` versus `D2plus`, and settles-below-forecast
versus `+0`/`+1`, agree.

Mechanism: late in the day `F` is nearly the answer and `D` is easy; at mid-morning `F` is weakly
informative, so learning `Y − F` is strictly harder than learning `Y`, and the prior conditioned to
the `D`-support is mis-specified. That is why the conditioned prior is the largest standalone loss
(+0.0286). **A floor-anchored objective was applied uniformly, including where the floor is not yet
informative.**

## The mission

Gate the continuation lane on floor informativeness, decided at cutoff time. Rows that do not
qualify retain the incumbent output exactly and unchanged.

Everything else stays as frozen in `-08-12a`: the objective, the lossless `F + D` translation, the
prior conditioning, the untouched hard-floor stages, and the gate harness.

## Two traps that will invalidate the result if you miss them

**1. Only two of the four dimensions are decidable at serve time.** Floor-removed mass and capture
hour are computable at cutoff from the incumbent distribution and `F`. **`D_class` is defined from
`Y`, and `forecast_relative_winner` uses the settled winner — gating on either is leakage.** Build
the gate from binding strength and hour only. If you find yourself wanting outcome information to
decide the gate, that is the signal to stop and report it.

**2. July 27–30 is burned for this hypothesis family.** It was declared a one-time score window and
has been spent. Choosing the binding-strength cut from those slice results would be selecting a
threshold on the score set — the exact mechanism behind the item-224 "win" that turned out to be
leakage.

Therefore:

- **Fit and threshold selection happen entirely within 2026-07-22 → 07-26**, using internal
  chronological blocked folds and market-day grouping. Partition it further if you need a selection
  fold; do not reach outside it.
- **Score on the freshest clean dates outside 07-22 → 07-30 that the mirror actually holds.**
  2026-07-31 should be present. 2026-08-01 settled after the 04:30 mirror ran, so it will likely
  arrive on the 04:30 run of 08-03 — take it if it is there, and do not wait on it or substitute for
  it.
- **A thin score window means a weaker conclusion.** Say so explicitly rather than compensating.
- **The reserved 2026-08-06 → 08-19 window stays untouched.** Do not read, enumerate, evaluate, or
  substitute it. It is the final confirmation set and must not be spent on an intermediate iteration.

## Pre-register before you fit

Declare, before inspecting any result:

1. **One primary gate definition** — a single threshold on floor-removed mass, chosen on development
   data for a stated reason. Report any hour-based or combined variant as **secondary and
   exploratory**, clearly separated from the primary.
2. The frozen bar, unchanged: **no protected slice may regress by more than the pooled improvement.**
3. The newly-severe cap and the one-sided 95% market-day bootstrap non-regression gate, both as
   applied in `-08-12a`.

Do not tune the threshold finely. A gate fitted to the last decimal has just relocated the leakage
into the gate itself. Prefer a defensible cut over an optimal one, and say which you chose.

## What I want back

1. The pre-registration block, written before any result.
2. Pass or fail on all three gates — bootstrap non-regression, newly-severe cap, catastrophic slice.
3. Whether the excluded rows contribute **zero** newly-severe rows, as they should by construction.
   If not, something is leaking across the gate and that is the headline.
4. Whether the bootstrap tightened. The dominant variance source in `-08-12a` was mixing a large win
   and a large loss inside one estimate; if gating does not tighten it, the instability is coming
   from somewhere else and I want to know where.
5. How much of the 58.23% severe-tail reduction survives gating.
6. A precisely named null if it fails again. That remains more valuable than a marginal win.

## Constraints — unchanged

- Base on `codex/workstation-continuation-candidate-2026-08-12a` @ `1e525a02`, which itself bases on
  the held gate harness `b9c62ead`. Both are **held and unmerged on purpose**; do not merge either,
  and do not assume either is on master.
- **POST-regime rows only.** `2026-07-31` is a `rows[-1]` regime boundary; do not straddle it.
- **Never weaken the trusted observed-high floor.** It is a control, not a tunable.
- `data/` strictly read-only with the OS-level deny-write ACL; all output under one declared run root
  outside the mirror; declare root and timestamp before inspecting any result.
- **Scope the freshness gate to the exact dates this experiment reads.** Do not gate on the mirror
  being current to today — it cannot be.
- Research only. **No** promotion, pointer change, serving change, scheduler change, capture restart,
  PR, merge, or master push. **No** mirror topology change, **no** ACL change, **no** paid-provider
  change.
- Topic branch only; merge timing stays with the production host. Do not access the production host
  or the mirror sync credential.

## Handback

Push the topic branch and report the branch and commit. Expect it to be held. The production host is
one to two clean capture days from the release-#1 lock, and a good result here authorizes nothing.
