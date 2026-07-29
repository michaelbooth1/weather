# Workstation sharpening and diffuseness - 2026-07-28

Status: **PASS - THE PREDECLARED HELD-OUT RESULT ELIMINATES GLOBAL
SHARPENING. THE FIT CHOSE SMOOTHING, AND THAT PARAMETER WORSENED HELD-OUT
BRIER. THE RESOLUTION DEFICIT IS REAL BUT CONCENTRATED. TARGETED FLOOR
PROJECTION WINS POOLED AND REMAINS UNSAFE PER CASE.**

This report executes
[`workstation-handoff-2026-07-28h-are-we-simply-too-diffuse.md`](workstation-handoff-2026-07-28h-are-we-simply-too-diffuse.md)
from exact `origin/master`
`17876717dcbab0274cef3b654eb084fe864c0b66` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Held-out answer first

The simple answer to "are we simply too diffuse?" is **no**. The clean
preblend forecast is more diffuse than the market in aggregate, but a single
global sharpening parameter is not the remedy:

- the fit selected `beta = 0.65` (`T = 1.5384615`), which is **smoothing**,
  not sharpening;
- that smoothing fit improved its own fitting dates but worsened the frozen
  held-out dates; and
- its preferred value varies materially by market and date.

The sharpening candidate is therefore **eliminated**, exactly under the
predeclared rule. No transform is proposed for deployment.

### Split frozen before scoring

At `2026-07-28T21:29:15-04:00`, after a metadata-only inventory and before
any transformed probability or score was calculated, I froze a chronological
split by `target_date`:

| Side | Dates | Valid POST simplexes |
| :--- | :--- | ---: |
| Fit | July 2, 3, 4, 5, and 7 | **6,790** |
| Held out | July 8, 9, and 10 | **4,871** |

The metadata inventory found 11,662 POST composite keys across those eight
dates. All 11 markets occur on both sides. The accepted Austin same-second
collision is excluded without replacement from simplex metrics. No date,
market, hour, or row was moved after scores were observed.

The split contract is 8,639 bytes with SHA-256
`e7cf8b5f0ddd0337257bb34e734fd545598a4f0bbb7f8c1ec95262e1c2f7f93a`;
its separate declaration receipt is 789 bytes with SHA-256
`e3bb0a84b4d3f831785bf26a6e0e23dfc7257e9aad00b8e330ffd20fbd7a75fb`.
The fit receipt records **zero held-out score evaluations** and was written
before the held-out command was allowed to run.

The transform was

```text
q_i(beta) = p_i ** beta / sum_j(p_j ** beta)
```

on the fixed grid `0.250, 0.275, ..., 3.000`. `beta = 1` is the no-op,
`beta > 1` sharpens, and `beta < 1` smooths. Selection minimized mean
categorical Brier on fit dates; ties within `1e-15` chose the value closest
to one and then the lower beta.

### Headline held-out result

All binary Murphy components below are exact per-market PAV/CORP estimates,
row-count weighted over identical held-out support.

| Lane | beta | Categorical BS | Binary BS | REL | RES | Gap to raw market |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| No-op preblend | 1.00 | **0.515030572** | **0.046820961** | **0.004854215** | 0.040677882 | 0.010646248 |
| Fit-selected transform | **0.65** | 0.515608168 | 0.046873470 | 0.005221797 | **0.040992955** | 0.010698757 |
| Raw market | n/a | 0.397921845 | 0.036174713 | 0.008048501 | 0.054518416 | 0 |

Relative to the no-op, the frozen fit-selected parameter produced:

- categorical Brier gain: **`-0.000577596`**;
- binary Brier gain: **`-0.000052509`**; and
- raw-market gap closure: **`-0.4932%`** - the gap widened.

Smoothing gained `0.000315073` of resolution but cost `0.000367582` of
reliability, so the reliability loss was larger. The maximum Murphy identity
residual was `6.94e-18`.

The fitting-side result illustrates why the split mattered. On the 6,790 fit
simplexes, categorical Brier improved from `0.529142279` to `0.516639436`
and binary Brier from `0.048103844` to `0.046967221`. Quoting that
`+0.012502843` categorical fit gain as the finding would have reversed the
out-of-sample conclusion.

The same-row held-out oracle, retained as a diagnostic only, preferred
`beta = 0.825` and categorical Brier `0.512073069`. It did not participate
in fitting or replace the headline.

### Stability and named cuts

Every strict stability check failed:

- the fit-selected value is smoothing rather than sharpening;
- fixed `beta = 0.65` helped July 8 by `0.002240405` categorical Brier but
  harmed July 9 by `0.002595613` and July 10 by `0.001906027`;
- it harmed 6 of 11 held-out markets: Atlanta, Austin, Chicago, Los Angeles,
  Miami, and NYC;
- fit-date oracle betas were `3.000`, `0.650`, `0.775`, `0.625`, and
  `0.575`; and
- fit-market oracle betas ranged from `0.375` for Denver to `1.725` for
  Atlanta, with 8 of 11 below the no-op.

The expanding-window selected betas stayed between `0.65` and `0.70`, but
their next-date categorical gains were `+0.022381639`, `+0.002240405`,
`-0.001360301`, and `+0.000286064`. That is not stable evidence for a
serving transform.

For completeness, applying the fit-selected beta to named full-corpus cuts
gives the following diagnostic binary gains. Positive means lower Brier than
the no-op on the same cut; these are descriptive, not additional fitting
results.

| Cut | n | No-op BS | beta 0.65 BS | Gain |
| :--- | ---: | ---: | ---: | ---: |
| Full POST | 11,661 | 0.047567961 | 0.046928060 | +0.000639902 |
| Predawn 03-05 | 222 | 0.074544359 | 0.072659662 | +0.001884696 |
| Primary 09-14 | 444 | 0.067948747 | 0.067454253 | +0.000494494 |
| Evening 20-23 | 339 | 0.000023484 | 0.000695386 | **-0.000671902** |
| Genuinely uncertain | 1,255 | 0.067209465 | 0.066009239 | +0.001200226 |
| Near-resolved | 600 | 0.001220783 | 0.001904092 | **-0.000683309** |

So the conditional pattern exists in-sample, but in the opposite direction
from the proposed mechanism: **smoothing** helps the uncertain cut and harms
the near-resolved cut. The complete 111-beta Brier and Murphy sweep for fit,
held-out, full POST, and every named cut is retained in
`sharpening_sweep_full.csv`.

## Where the diffuseness is concentrated

Mission 2 uses all 11,661 valid POST simplexes, or 128,271 binary band rows.
The primary market comparator is the normalized nonnegative market simplex;
raw market remains an accepted-score control.

Globally, preblend is visibly flatter:

| Measure | Preblend | Normalized market | Preblend minus market |
| :--- | ---: | ---: | ---: |
| Mean effective bands | **3.487413** | 2.627859 | **+0.859554** |
| Mean top-band probability | 0.591960 | **0.671082** | **-0.079122** |

The exact normalized-market PAV resolution is `0.049531590`, versus
preblend `0.038977629`, a deficit of **`0.010553960`**. The independently
retained raw-market control resolution is `0.049462476`. Partition
contributions reconcile to the primary resolution gap within `1.56e-17`.

The deficit is not uniform:

- the worst 1,167 partitions have mean deficit `0.048883791` and carry
  **46.35%** of the total signed resolution deficit;
- Denver supplies **468 / 1,167 = 40.10%** of the worst decile despite being
  9.48% of the population, a **4.23x** lift;
- Dallas supplies 201 and Austin 160; those three markets together supply
  **71.04%** of the worst decile;
- local hours 09-14 supply **619 / 1,167 = 53.04%**, and 09-15 supply
  **718 / 1,167 = 61.53%**; and
- hour 14 alone supplies 146 cases at a 3.24x lift, followed by hour 13 at
  114 and 2.69x.

The global entropy-style diffuseness measure is not itself the localization
answer. Seattle has the largest mean effective-band excess, approximately
`+1.376`, but contributes only eight worst-decile cases. Resolution
concentration depends on outcomes and rank structure, not just distribution
entropy.

Other requested characterizations do not yield a clean pre-outcome rule:

- high and moderate frozen forecast-disagreement buckets have only 1.10x
  and 1.16x worst-decile lifts;
- every finite interior band width is exactly one degree, so width has no
  variation;
- every winning-band nearest-inclusive-edge distance is zero under the
  whole-degree settlement and inclusive-band convention;
- a realized day-over-day move of `+5 F` puts 112 of 146 cases in the worst
  decile, a 7.67x lift, but this is post-outcome and confounded; it is not a
  serving feature; and
- all eight POST dates are in July 2026, so seasonality is unidentifiable.

The programme implication is narrower than "be a better forecaster":
resolution loss is disproportionately a Denver/Dallas/Austin and
market-local 09-15 problem. That is a useful research target, but this audit
does not establish a causal mechanism or authorize a market/hour rule.

## Targeted floor remedy

The targeted rule was fixed before measurement:

> Project replay-final only when rounded-floor forbidden mass exceeds
> `1e-9`; otherwise retain the original tuple bit-for-bit.

From 11,662 POST composite keys, the accepted projection population removes
61 no-floor keys, the one Austin collision, and two off-target-date keys:
**11,598** valid finite-floor target-day simplexes. The rule projects 7,191
and leaves 4,407 clean simplexes unchanged. All 4,407 clean vectors are
bit-exact before and after; zero float words changed.

| Scope | n | Applied | Final BS | Targeted BS | Binary gain | Blend penalty recovered | Raw gap closed | Improved / equal / worse |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| Full | 11,598 | 7,191 | 0.049673697 | **0.046950370** | **+0.002723327** | **116.67%** | 23.76% | 5,731 / 4,407 / **1,460** |
| Fit dates | 6,740 | 4,411 | 0.049288145 | **0.045990998** | +0.003297147 | 216.43% | 34.31% | 3,401 / 2,329 / **1,010** |
| Held-out dates | 4,858 | 2,780 | 0.050208613 | **0.048281404** | **+0.001927209** | **55.71%** | 13.73% | 2,330 / 2,078 / **450** |

The targeted full-population gain agrees with the accepted blanket-projection
control within `1.39e-17`, as it should: clean vectors were already unchanged
arithmetically. The targeted specification makes that non-interference an
explicit contract.

The pooled remedy is still not per-case safe. Helped and harmed cases overlap
within all 11 markets, both resolvedness groups, all four preblend-entropy
quartiles, and most local-hour, forbidden-mass, forbidden-count, and
stored-floor-position strata. Hours 18-23 and a few extreme-mass strata were
harm-free in this realized corpus, but they were identified after observing
outcomes and are not promoted as action rules.

The verdict is therefore **`POOLED_WIN_UNSAFE_PER_CASE`**. This is a measured
counterfactual, not a blend, floor-order, or serving change.

## Execution and independent verification

The single measurement write root was:

`C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\sharpening-diffuseness-20260728h-17876717`

Final admission at 21:54 ET recorded 48.21% committed memory, a valid
66,951,397,376-byte commit limit, 62.65 GiB free on `C:`, and no competing
research/training or copy/compression process visible by process name/path.
Command lines were unavailable in the sandbox, which is recorded as a
limitation. The run was outside the protected 01:00-08:30 window.

Four fail-closed corrections are retained in the execution provenance:

1. The first metadata-only loader stopped before corpus access because its
   process-local module registration did not satisfy a dataclass import.
2. An initial host receipt was rejected when denied CIM access produced an
   invalid zero resource counter. The final harness uses `Get-Counter` and
   requires valid, nonzero counters.
3. The first analysis pass completed computation but stopped when an inherited
   control check requested `brier_gain` instead of the actual `score_gain`
   field. That output was not accepted.
4. The first final verification stopped because Mission 3's measurement
   receipt intentionally said pending replay verification. The verifier was
   tightened to bind the complete measurement-to-verification-to-gate chain
   and exact Mission 3 numerics.

After each harness change, its hash changed and the complete
`self-test -> admit -> fit -> evaluate -> analyze -> verify` chain was rerun.
The final primary gate is
`PASS_SHARPENING_ELIMINATED_DIFFUSENESS_LOCALIZED_TARGETED_FLOOR_PRICED`
and grants no authority.

Three independent implementations corroborate the result:

- a standard-library sharpening validator that does not import the primary
  harness reproduced the fit selection, held-out headline, every stability
  check, and exact per-market PAV with zero discrepancies;
- the independent Mission 2 implementation rebuilt the POST population,
  normalized-market and preblend resolution contributions, worst-decile
  ranking, and requested characterizations; and
- Mission 3 has a separate measurement receipt, replay verification, and
  terminal gate. The primary verifier binds and numerically compares all
  four Mission 3 support artifacts.

## Evidence

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Predeclaration | 8,639 | `e7cf8b5f0ddd0337257bb34e734fd545598a4f0bbb7f8c1ec95262e1c2f7f93a` |
| Split declaration receipt | 789 | `e3bb0a84b4d3f831785bf26a6e0e23dfc7257e9aad00b8e330ffd20fbd7a75fb` |
| Final primary harness | 89,560 | `1b517b104b5999e3ebb5e4a1ad87655e624e140b0714e0b419460d876fba7d6a` |
| Final self-test receipt | 840 | `2ce05ac9fc62fce2e1f4fb8ac60ecdc092854d9f9481047a07827b757241625e` |
| Final host admission | 1,664 | `075ff9dad3a77e8b6bcafe3f67af0f6122562cae23c17fa81a3b0868eb5681b0` |
| Fit selection | 6,407 | `eecbc912f2f1b59daa033ab9e5c55b48126d1dd7262e1bcd7a16e14e65f85298` |
| Held-out evaluation | 19,192 | `1b67f21ce9116e928dac46729571430e7a84a7b7394524c96a05e740f312109f` |
| Complete sweep | 269,708 | `f49d4241e72dad01920bd391f2aab70d0dacd275db8a2790228a10cfda728e90` |
| Primary analysis | 81,467 | `27c2c5fda003f34b8fb9b7911f954213e890858ea7aeda99d0091a0993ca6d4a` |
| Primary verification | 6,686 | `131eb80e1c5e46d3f9c75bad454d6f4831ae306deaf80eb4df0c0d62610eb974` |
| Independent sharpening receipt | 92,837 | `d136aa4db917620be9889f007da12cfca1c01925e640e1279f39904987e3d674` |
| Independent Mission 2 receipt | 11,215 | `f2fce0a78a6968dd01a99f0d1489d8a510973ff90c5b04ee298088f9a0bd6774` |
| Mission 3 measurement receipt | 6,841 | `fe41a15dab46edef59d472f7d5221f0cbd15bbc328ac5be954052fd3bc5b1890` |
| Mission 3 replay verification | 2,289 | `613c41678ec1b30c074a4b9e171144cf1b1b66b1be5d7828a5475935f7e18dad` |
| Mission 3 terminal gate | 5,342 | `6cf4e034762378538e991527213f7136bbb360b61cb5fb8d3390f70ea04ae8ae` |
| Final primary gate | 4,980 | `f35fc8d913635ee885788f859d45696ee2fd13e8d81f477ff141a7add613da74` |
| Execution manifest | 12,081 | `4dd0fa23bc0d62fba942f35e680c4f53bdce20d87213eb83f78786699197d326` |

All fixed inputs were rehashed before fitting and again during verification.
Their exact paths, sizes, and hashes are bound in the predeclaration,
receipts, and execution manifest.

## Handback and next queue

- **DONE:** predeclared scalar fit, held-out headline, full sweep and Murphy
  decomposition, cross-market/date stability, diffuseness localization, and
  targeted floor measurement.
- **ANSWER:** aggregate diffuseness is real, but one global sharpening
  parameter is not the remedy. The fitted transform is smoothing and fails
  out of sample.
- **LEAD:** the resolution deficit is concentrated in Denver/Dallas/Austin
  and market-local hours 09-15, subject to the non-causal limitations above.
- **DECISION:** keep the targeted floor verdict at
  `POOLED_WIN_UNSAFE_PER_CASE`; do not promote a post-hoc selector.
- **NOT DONE:** no causal boundary hunt, no seasonality claim, no deployment
  transform, and no Missions 3+ of `-28c`.
- **NOT CHANGED:** `data/`, model, blend, alpha, floor order, config,
  artifacts, serving, release, pointer, collectors, schedulers, sizing,
  promotion, or trading state.
- **NOT APPLIED / DELETED / COMPRESSED:** any real data.

Missions 3+ of `-28c` remain queued for the next 01:00-08:30 window exactly
as requested.
