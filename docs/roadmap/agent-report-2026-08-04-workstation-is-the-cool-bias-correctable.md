# Workstation frozen-HGB centre-bias measurement — 2026-08-04

## Verdict

**The frozen base HGB is systematically cool, but the defect is not an
admissible serving-side constant.** Across the exact `-09-07a` population, the
raw-HGB centre error is `-0.6641 °C-equivalent`, with a crossed date × market
95% interval of `[-1.1164, -0.2482]`. The support is 34 target-date clusters,
12 market clusters, 399 promotion-countable market-days, and 9,360
hour-balanced captured rows.

The decisive result is calendar drift. June is `-0.1996 °C-equivalent`
`[-0.6234, +0.2005]`, which crosses zero; July is `-1.0586`
`[-1.6512, -0.4319]`. July minus June is `-0.8590`
`[-1.5581, -0.1359]`, and the calendar slope is `-0.03553
°C-equivalent/day` `[-0.06176, -0.00945]`. Both intervals use crossed date ×
market resampling. This supports worsening staleness from June into July.

It does **not** complete the handoff's June-to-August test: the mandated
34-date set contains 16 June dates, 18 July dates, and **zero August dates**.
The claim that August is worst is not identifiable without violating the
fixed-population instruction, and reserved August dates were not inspected.
The result is therefore evidence consistent with a stale June prior, not proof
that a retrain necessarily removes the defect or establishes its decay curve.

A single offset is contradicted by market heterogeneity: C-equivalent market
means range from Denver `-1.7902` to Austin `+0.4026`. Per-market constants are
also unstable across months and remove only 8.11% of row-level residual
variance in this descriptive, in-sample decomposition. Hour/lead shape is not
the main structure: effective 09:00–14:00 minus 15:00–20:00 is `+0.0032`
`[-0.2678, +0.2704]`, which crosses zero, and short lead minus long lead is
`-0.2717` `[-0.6450, +0.0891]`, which also crosses zero. Adding per-market
effective-hour cells removes only another 1.91% of descriptive residual
variance.

The floor interaction is real and non-additive. The unchanged production hard
floor currently removes 14.54% of pre-floor probability mass on average
`[10.98%, 18.33%]` and warms the centre by `+0.6809 °C-equivalent`
`[+0.4649, +0.9342]`. A diagnostic `+0.6641 °C-equivalent` global translation
before that same floor produces only `+0.5582` after it
`[+0.5294, +0.5853]`: the correction reduces truncated mass by 3.58 percentage
points `[-4.41, -2.86]`, so the floor returns `0.1059 °C-equivalent` less
warmth `[-0.1371, -0.0802]`. Only 84.06% `[79.69%, 88.12%]` of the nominal
translation reaches the post-floor centre. The floor is behaving as designed
and was not changed.

**Recommendation: do not ship a global, per-market, hour, or lead centre
correction before the retrain.** The measured offsets are retrospective,
calendar-dependent, coupled to the load-bearing floor, and have no held-out
proper-score evidence. No correction form is authorized by this mission.

No model fit, retrain, candidate score, candidate-power claim, promotion,
artifact change, release/PIT change, floor change, provider call, or reserved
date access was performed.

## Sign, population, and inference contract

**Sign convention:** raw-HGB expected native high minus the canonical
promotion-countable settlement bucket. Negative is cool; positive is warm.
Fahrenheit deltas are multiplied by `5/9` only after subtraction when pooled;
Toronto remains native Celsius and the 11 U.S. markets remain native
Fahrenheit in market-specific results.

The population is the exact, ordered 34-date fleet set declared by `-09-07a`,
not a re-derived population and not the nine-date `quality_grade=complete`
subset. It contributes 399 of the possible 408 market-days. Within each
admitted market-day, the measurement selects the earliest captured replay
record in each local clock hour that also appears in `snapshots_long.csv`.
This outcome-independent sampling gives equal weight to each selected
market-date-local-hour and prevents collection cadence from becoming an
implicit weight.

The 399 canonical labels are all `promotion_countable=True` and settlement
reconciliation `match`: 368 use `settlement_source=daily_summary`, and 31 use
the ratified, materially covered `snapshot_high` source. The latter are kept
because the handoff explicitly makes `promotion_countable`, not
`quality_grade=complete` or settlement-source name, the admission contract.

Every interval below is a deterministic 2,000-replicate percentile interval
using crossed target-date × market pigeonhole resampling. `D`, `M`, `MD`, and
`H` mean target-date clusters, market clusters, distinct market-days, and
selected hour rows. A market-specific interval has `M=1`, so its market draw is
necessarily degenerate while date clusters are still resampled. Month
contrasts use independent date draws within month and a shared market draw.
Direct structure contrasts use shared date and market draws for both sides.

## Q1 — signed centre error

### Pooled and by market

The pooled error is `-0.6641 °C-equivalent` `[-1.1164, -0.2482]`
(`D=34`, `M=12`, `MD=399`, `H=9,360`). Its interval is wholly negative.

Market intervals are reported in each market's settlement unit; the final
column is only the point estimate re-expressed in C-equivalent units.

| Market | Unit | Raw HGB minus settlement, native [95% crossed interval] | D | M | MD | H | Point, C-eq |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Atlanta | F | -1.1992 [-2.1404, -0.1085] | 33 | 1 | 33 | 772 | -0.6662 |
| Austin | F | +0.7246 [+0.0162, +1.6353] | 34 | 1 | 34 | 798 | +0.4026 |
| Chicago | F | -0.9226 [-1.9353, +0.1359] | 33 | 1 | 33 | 773 | -0.5126 |
| Dallas | F | -1.0844 [-2.1472, -0.1321] | 34 | 1 | 34 | 798 | -0.6024 |
| Denver | F | -3.2223 [-4.2100, -2.2116] | 34 | 1 | 34 | 797 | -1.7902 |
| Houston | F | -0.1900 [-0.8471, +0.5326] | 33 | 1 | 33 | 774 | -0.1056 |
| Los Angeles | F | -1.5983 [-2.6391, -0.7399] | 32 | 1 | 32 | 752 | -0.8879 |
| Miami | F | -1.3995 [-1.8353, -0.9982] | 34 | 1 | 34 | 796 | -0.7775 |
| NYC | F | -2.7117 [-4.2113, -1.3462] | 33 | 1 | 33 | 773 | -1.5065 |
| San Francisco | F | -0.3804 [-1.7396, +0.7162] | 33 | 1 | 33 | 776 | -0.2113 |
| Seattle | F | -1.6750 [-3.2108, -0.3695] | 32 | 1 | 32 | 753 | -0.9305 |
| Toronto | C | -0.4028 [-0.9859, +0.1921] | 34 | 1 | 34 | 798 | -0.4028 |

Seven markets have wholly negative native-unit intervals. Austin's point has
the opposite sign and its native-unit interval is barely wholly positive;
Chicago, Houston, San Francisco, and Toronto cross zero. This sign/range split
is enough to reject one fleet-wide constant as a faithful description.

### By local capture-hour bucket

| Local capture bucket | Error, C-eq [95% crossed interval] | D | M | MD | H |
| --- | ---: | ---: | ---: | ---: | ---: |
| 00–05 overnight | -0.5005 [-1.0138, +0.0012] — crosses zero | 33 | 12 | 387 | 2,277 |
| 06–08 early | -0.6289 [-1.1323, -0.1536] | 34 | 12 | 391 | 1,168 |
| 09–14 morning | -0.7451 [-1.2968, -0.2413] | 34 | 12 | 399 | 2,390 |
| 15–17 afternoon | -0.6865 [-1.1014, -0.3108] | 34 | 12 | 399 | 1,197 |
| 18–20 evening | -0.7172 [-1.0976, -0.3660] | 34 | 12 | 399 | 1,187 |
| 21–23 late | -0.7779 [-1.2325, -0.3741] | 34 | 12 | 391 | 1,141 |

The requested 09:00–14:00 bucket is cool, but it is not uniquely cool: all
post-overnight capture buckets are negative with strongly overlapping
intervals. This table uses actual local capture time. The model's effective
feature cutoff is separately decomposed below because early captures map to
cutoff 07 and captures after cutoff 20 remain capped at 20.

| Effective cutoff | Error, C-eq [95% crossed interval] | D | M | MD | H |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 07 | -0.5059 [-0.9991, -0.0299] | 34 | 12 | 390 | 3,198 |
| 08 | -0.6396 [-1.1638, -0.1216] | 34 | 12 | 365 | 374 |
| 09 | -0.6427 [-1.2377, -0.0498] | 34 | 12 | 343 | 368 |
| 10 | -0.6104 [-1.1732, -0.0698] | 34 | 12 | 388 | 443 |
| 11 | -0.8474 [-1.4174, -0.3139] | 34 | 12 | 387 | 399 |
| 12 | -0.8621 [-1.5232, -0.3204] | 34 | 12 | 389 | 397 |
| 13 | -0.7669 [-1.3359, -0.2656] | 34 | 12 | 389 | 402 |
| 14 | -0.7851 [-1.3131, -0.3013] | 34 | 12 | 391 | 399 |
| 15 | -0.7224 [-1.2220, -0.2993] | 34 | 12 | 391 | 400 |
| 16 | -0.6654 [-1.0760, -0.3209] | 34 | 12 | 391 | 402 |
| 17 | -0.6999 [-1.0635, -0.3820] | 34 | 12 | 375 | 381 |
| 18 | -0.7163 [-1.0998, -0.3734] | 34 | 12 | 363 | 376 |
| 19 | -0.7307 [-1.1225, -0.3479] | 34 | 12 | 377 | 403 |
| 20 | -0.8201 [-1.2627, -0.4194] | 34 | 12 | 395 | 1,418 |

Every effective-hour interval is negative. That is evidence for a persistent
base-centre defect, not for an hour-specific repair: the direct morning-minus-
evening contrast is effectively zero in Q2.

### By lead time

Lead is hours from local capture to the end of the target day.

| Lead | Error, C-eq [95% crossed interval] | D | M | MD | H |
| --- | ---: | ---: | ---: | ---: | ---: |
| 00–<04h | -0.7722 [-1.1968, -0.3749] | 34 | 12 | 395 | 1,533 |
| 04–<08h | -0.6828 [-1.0509, -0.3398] | 34 | 12 | 399 | 1,593 |
| 08–<12h | -0.7781 [-1.2923, -0.3159] | 34 | 12 | 399 | 1,596 |
| 12–<18h | -0.6620 [-1.2158, -0.1702] | 34 | 12 | 399 | 2,361 |
| 18–24h | -0.5005 [-1.0302, -0.0313] | 33 | 12 | 387 | 2,277 |

All lead buckets are cool, their intervals overlap, and the point estimates do
not form a monotone lead curve.

### By calendar month

| Month | Error, C-eq [95% crossed interval] | D | M | MD | H |
| --- | ---: | ---: | ---: | ---: | ---: |
| June 2026 | -0.1996 [-0.6234, +0.2005] — crosses zero | 16 | 12 | 187 | 4,299 |
| July 2026 | -1.0586 [-1.6512, -0.4319] | 18 | 12 | 212 | 5,061 |

## Q2 — constant or structured?

### (a) Single global offset: rejected as a shipping form

The pooled signed error is real, but its global mean hides a 2.1927
°C-equivalent range in market means and an opposite-sign Austin estimate. It
also averages a June interval that crosses zero with a July interval that is
wholly cool. A `+0.6641 °C-equivalent` serving constant would therefore encode
market mix and artifact age from this retrospective sample, not an invariant
incumbent property.

### (b) Per-market constants: descriptive, not stable corrections

Per-market constants reduce mean squared row residual from `4.0123` to
`3.6871 °C-equivalent²`, only 8.11%. This is an in-sample heterogeneity
decomposition, not a fitted candidate score. The month contrasts show why a
fixed set of 12 numbers is not stable:

| Market | July minus June, C-eq [95% crossed interval] | June D/H | July D/H |
| --- | ---: | ---: | ---: |
| Atlanta | -1.6183 [-2.7419, -0.7369] | 16/367 | 17/405 |
| Austin | +0.2917 [-0.5151, +1.2572] — crosses zero | 16/368 | 18/430 |
| Chicago | -1.5173 [-2.5084, -0.4727] | 15/344 | 18/429 |
| Dallas | -1.8441 [-2.8328, -0.9336] | 16/368 | 18/430 |
| Denver | -1.8359 [-2.8087, -0.9106] | 16/369 | 18/428 |
| Houston | +0.0390 [-0.6798, +0.7703] — crosses zero | 15/344 | 18/430 |
| Los Angeles | -1.4158 [-2.3356, -0.6029] | 14/322 | 18/430 |
| Miami | +0.0545 [-0.3999, +0.4927] — crosses zero | 16/367 | 18/429 |
| NYC | -1.0031 [-2.6490, +0.4666] — crosses zero | 16/367 | 17/406 |
| San Francisco | +0.1627 [-1.3065, +1.4503] — crosses zero | 15/346 | 18/430 |
| Seattle | -1.0018 [-2.4908, +0.4061] — crosses zero | 16/370 | 16/383 |
| Toronto | -0.7901 [-1.9160, +0.2837] — crosses zero | 16/367 | 18/431 |

Each row has `M=1`; within each month `MD=D`. Five markets have wholly negative
July-minus-June intervals, while seven cross zero. The heterogeneous levels and
changes do not supply 12 stable serving constants.

### (c) Hour/lead shape: not detected as a material repair axis

Effective 09:00–14:00 averages `-0.7512 °C-equivalent` on `D=34`, `M=12`,
`MD=399`, `H=2,408`. Effective 15:00–20:00 averages `-0.7544` on `D=34`,
`M=12`, `MD=399`, `H=3,380`. Their direct crossed contrast is `+0.0032`
`[-0.2678, +0.2704]`, which crosses zero.

The shortest-lead minus longest-lead contrast is `-0.2717`
`[-0.6450, +0.0891]`, which crosses zero. Its left support is `D=34`, `M=12`,
`MD=395`, `H=1,533`; its right support is `D=33`, `M=12`, `MD=387`,
`H=2,277`.

Finally, replacing per-market constants with per-market × effective-hour cell
means lowers descriptive residual MSE from `3.6871` to `3.6106`, only another
1.91% of the global residual variance. The all-hour cool defect therefore does
not reduce to a morning endpoint or a lead-dependent shape.

### (d) Drift: detected from June to July

July minus June is `-0.8590 °C-equivalent` `[-1.5581, -0.1359]`. June support
is `D=16`, `M=12`, `MD=187`, `H=4,299`; July support is `D=18`, `M=12`,
`MD=212`, `H=5,061`. The interval is wholly negative.

The continuous calendar slope is `-0.03553 °C-equivalent/day`
`[-0.06176, -0.00945]` on `D=34`, `M=12`, `MD=399`, `H=9,360`, also wholly
negative. This is the dominant systematic structure found by the mission.

## Q3 — stale June prior

The June-to-July prediction of the stale-prior hypothesis passes: the frozen
HGB is near neutral in June and materially cooler in July, the crossed month
contrast is negative, the calendar slope is negative, and five market-specific
month contrasts are wholly negative.

The stronger hypothesis in the handoff does not yet pass or fail. The fixed
population ends on 2026-07-21 and contains no August target date, so “smallest
in June, largest in August” cannot be tested here. Reading August 6 through
November 3 would also violate the reserved-confirmation contract. No August
substitute was introduced.

This distinction matters operationally:

- The evidence supports artifact age/season distance as a first-class retrain
  variable and supports measuring raw-centre residual against artifact age.
- It does not establish a retrain cadence from two observed months.
- It does not prove that refreshing the artifact fixes the bias. A refresh
  using the same stale seasonal construction, limited upper support, or fitting
  objective could reproduce it.
- These are current-incumbent retrospective diagnostics, not point-in-time
  candidate scores. Current artifacts were deliberately applied to all old
  target dates as instructed.

## Q4 — exact hard-floor interaction

The mechanism trace translates the fully assembled pre-hard-floor native
distribution, splitting mass linearly between adjacent integer buckets so the
requested expected-centre movement is exact. It then applies the unchanged
production rule: multiply probability below the exact captured trusted floor
by `0.000001` and renormalize. Manual reproduction of the current pipeline's
hard-floor output has maximum probability difference `5.88e-15` across all
9,360 rows.

### Global diagnostic translation

| Scope | Baseline mass below floor [95% CI] | Baseline floor warmth, C-eq [95% CI] | Mass change after +0.6641 C [95% CI] | Floor-warmth change, C-eq [95% CI] | Net post-floor movement, C-eq [95% CI] | Transmission [95% CI] | D/M/MD/H |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All hours | 0.1454 [0.1098, 0.1833] | +0.6809 [+0.4649, +0.9342] | -0.03584 [-0.04410, -0.02857] | -0.1059 [-0.1371, -0.0802] | +0.5582 [+0.5294, +0.5853] | 0.8406 [0.7969, 0.8812] | 34/12/399/9,360 |
| Effective 09–14 | 0.1376 [0.0936, 0.1901] | +0.7243 [+0.4706, +1.0437] | -0.03124 [-0.04093, -0.02233] | -0.1052 [-0.1482, -0.0729] | +0.5588 [+0.5197, +0.5899] | 0.8415 [0.7830, 0.8908] | 34/12/399/2,408 |
| Effective 15–20 | 0.2659 [0.2044, 0.3359] | +1.0656 [+0.7122, +1.4902] | -0.06900 [-0.09096, -0.05152] | -0.1738 [-0.2261, -0.1271] | +0.4903 [+0.4351, +0.5386] | 0.7383 [0.6537, 0.8094] | 34/12/399/3,380 |

The naive-addition error equals the floor-warmth change: `-0.1059
°C-equivalent` all hours. The absorber is stronger later because more mass is
already below a higher observed floor; the same nominal centre translation
therefore transmits only 73.83% in effective hours 15–20 versus 84.15% in
09–14. This traces the received mechanism directly: evening masking is
stronger, while the upstream raw bias itself is not detectably different
between those windows.

The per-market diagnostic translations give the same qualitative result. On
all 9,360 rows (`D=34`, `M=12`, `MD=399`), their mean post-floor movement is
`+0.5579 °C-equivalent` `[+0.3226, +0.8231]`; the interaction is `-0.1061`
`[-0.1878, -0.0262]`, and mean transmission is 80.80%
`[73.96%, 86.20%]`. The removed-mass change is `-0.02647`
`[-0.05201, +0.00813]`, which crosses zero because Austin's retrospective
per-market translation is cool rather than warm and market resampling retains
that heterogeneity.

These translations are mechanism-only counterfactuals. They are not candidate
distributions, are not evaluated for Brier/log-loss or trading utility, and do
not authorize a serving change.

## Pre-retrain recommendation

No serving-side centre correction is admissible before the retrain.

1. A global constant is contradicted by market sign/range and June-to-July
   drift.
2. Twelve constants are estimated on the same outcomes used to diagnose the
   defect, explain little residual variation, and change materially by month.
3. An hour/lead correction has no direct crossed support in the two
   predeclared structure contrasts.
4. Any pre-floor correction is partially and time-dependently absorbed by the
   trusted floor. A post-floor correction would instead violate the production
   distribution contract and physical support unless separately designed and
   validated.
5. No proper-score, train/serve-parity, fresh confirmation, or release-binding
   evidence exists for any correction.

Evidence required to reconsider a serving correction would include a
training-only estimate frozen before evaluation; untouched, non-reserved
market-days spanning artifact ages and all markets; crossed date × market
intervals for signed centre error and proper scores; probability-mass and
native-unit checks; an exact unchanged-floor trace at the intended pipeline
location; and the normal captured-input replay, release binding, and promotion
gates. None of that evidence was created here.

## What the first retrain must fix

The retrain should target the upstream raw centre, not weaken the floor:

- refresh each market's training distribution so the raw-HGB prior and class
  support cover the current target-season regime;
- preserve the native settlement unit, cutoff-valid features, train/serve
  parity, captured-input replay, probability mass, effective WU print cutoff,
  trusted observed-high floor, and release binding;
- predeclare raw signed-centre diagnostics by market and artifact age alongside
  Brier/log-loss and the existing serving endpoints;
- verify that the June-to-July age slope flattens on untouched data and does
  not merely reset at the retrain date;
- use the accumulated age curve, not this two-month diagnostic alone, to set a
  retrain cadence.

A retrain would reproduce the defect if it regenerates the same stale seasonal
prior, limited warm-class support, or fitting shrinkage. The present evidence
does not identify hour/lead shape as the primary repair target and does not
justify encoding retrospective per-market offsets into serving.

## Provenance and safety

The branch starts exactly at `origin/master @
ec6f726fbb5ee783dc6e20f8afcf1c7fee34fd17`. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\is-the-cool-bias-correctable-2026-09-08a`,
outside `data/`.

The July 31 `rows[-1]` boundary was treated as an artifact-provenance boundary,
not a target-date boundary. Every one of the 9,360 records was re-extracted and
replayed through the same current POST code at the base commit and the same 12
tracked current HGB artifacts; all 12 artifact hashes and five serving-source
hashes were verified. No historical result row or artifact identity was mixed
into the measurement. All routes report `hgb`; maximum raw probability-sum
error is `6.66e-16`.

The independent verifier re-hashed 798 snapshot input files, matched all 9,360
selected record payloads, verified all 12 artifact and five source hashes,
recomputed 81 measurement/structure intervals and 48 floor intervals, and
passed. `data/backtest/market_day_labels.csv` remained at 1,010,953 bytes,
last-write `2026-08-03T13:48:45.1855535Z`, SHA-256
`653c15d83a0111d21ec380337824d387d0561e331be8912136838fc2a4388c72`.
The data mirror remained read-only.

Reserved dates 2026-08-06 through 2026-11-03 were not enumerated, read,
replayed, scored, or inspected. No provider or paid-source access occurred.

## What would falsify this

- **Systematic frozen-HGB cool bias:** the same declared population, artifact
  hashes, feature extraction, settlement labels, and hour-balanced weighting
  producing a pooled crossed interval that includes zero or a non-negative
  point would overturn it.
- **Not a global constant:** homogeneous market effects with no opposite-sign
  market, stable levels across artifact age, and untouched proper-score gains
  from one frozen offset would overturn the rejection.
- **Per-market constants are not stable enough:** 12 training-only constants
  that remain stable across untouched months, remove a dominant share of
  residual variation, and improve held-out proper scores under the unchanged
  floor would overturn it.
- **No material hour/lead shape detected:** a predeclared crossed contrast that
  excludes zero, replicates on untouched dates, and adds held-out proper-score
  value beyond market and age would overturn it.
- **June-to-July drift:** a recomputation whose July-minus-June or calendar-slope
  interval includes zero would overturn it.
- **Stale-prior interpretation:** an admissible August/other age endpoint that
  does not worsen with artifact age, or a correctly refreshed retrain that
  leaves the age trend unchanged, would reject staleness as the main cause. The
  missing August endpoint means this causal claim is not yet established.
- **Non-additive floor coupling:** exact replay showing unchanged removed mass,
  unchanged floor warmth, or 100% transmission after a centre translation
  would overturn it.
- **POST/current-artifact provenance:** any artifact/source hash mismatch, a
  non-HGB route, a historical result row, or hard-floor reproduction error
  above tolerance would invalidate the measurement.
- **Safety boundary:** any reserved-date access, provider call, data mutation,
  fit, candidate score, floor change, or release/PIT change would invalidate
  the handback.

## Evidence handback

Final evidence-manifest SHA-256:
`00dfee7e20949be3ac9c421ecb7d903f1f2eea9a45744a22f3acbeb9faa9c8fe`.

| Evidence | SHA-256 |
| --- | --- |
| Declaration | `c725db5e1a42e973f3b0c8319d0cfa300b274fdc4da6ebbf7745a51e35ce1283` |
| Measurement script | `3415c05a664e3ad72833fb1890b7fa7db1f24412f55c9bac49c92eb8bd366e06` |
| Pinned measurement manifest | `3dacbeb21abf80119563a058dcc88fcdcc05536bcb14181d609af4bcc75e2413` |
| Snapshot centre errors | `94f5eb8d2809f94ebe0c4d1254778f942752263abb2f1c3afc0360bdb4849cb5` |
| Centre-error summary | `6ebb680723a8dfd9e56388727a62cc84f03467f130e3d7aebeebebb9ebdc8540` |
| Market decomposition | `6841d7b59a86c4c99798867ab848c72e0916dc997f3c0952e8aa6c1e83fcb178` |
| Effective-hour decomposition | `3e2688d422b84ba5b56589947a53d72355eb0282ce8cc473a215044c217fe732` |
| Capture-bucket decomposition | `3f11298b1a8299771f70a619be2ff7672f15d31fe5289759dbfb6f7053497923` |
| Lead decomposition | `3422f21f482f8346f6eed7346c5e919277233d75fcf993f7ad3b6a7ff1851211` |
| Month decomposition | `3a188e2ee3c128cac9d94585bdb14ffff5464b4f6f98211feb350f213ca46e82` |
| Structure contrasts | `78efee25db88e321ff66cbbf155156bb6c6cc5f9574016b896dad4e0ceacf88a` |
| Floor interaction rows | `56368290c9dad83476bfc62ee88aa962ff83a8db2e540b9f047980c09a3154c1` |
| Floor interaction summary | `699cb2ea8b5fa3eaed66af3b6776b767819228733d7456e8f22b8a8aefb815e8` |
| Independent verifier | `ef85a7d8ee53a03eb3c9269e0654ced925736a33562a9af9865632094052a0fd` |
| Independent verification | `288c5f585b6116961ec179bdf49462a94f0db1999fe9357fb52d8d3cd210670c` |

No PR was opened and no merge was performed.
