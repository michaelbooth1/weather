# Workstation causal blindness measurement - 2026-08-02

## Verdict

**Blindness has a small, uncertain pooled cost in the incumbent model, a real
but narrower severe-tail cost, and it does not explain the excluded lane's cool
centre displacement. I would not pay for a fleet-wide Phase F retrain on this
evidence.**

On 2,855 jointly eligible July 22-26 snapshots at effective cutoffs 09:00-14:00,
blinding all ten fields increased daily-first multiclass Brier by `+0.009899`
and pooled snapshot Brier by `+0.008581`. The market-day cluster interval on the
daily-first effect is wide and crosses zero: `[-0.022842, +0.041688]`. On the
excluded lane, the corresponding effects are `+0.008210` daily-first and
`+0.004273` pooled, with interval `[-0.023948, +0.042744]`.

The severe-tail result is more consistent. On the 1,545 band rows selected by
the joint-blind arm's predeclared severe rule, restoring the fields reduces
squared error from `737.065190` to `642.944476`, or **12.77%** (market-day
cluster interval **8.60%-17.53%**). On the excluded lane's 919 frozen severe
rows, it reduces squared error from `434.348864` to `368.198847`, or
**15.23%** (interval **9.43%-21.54%**). The number of severe rows does not
materially move: joint blindness and full information each have 1,545 under
their own threshold overall; excluded blindness has 919 versus 922 full.
Blindness changes the magnitude of concentrated misses more reliably than it
changes threshold crossings or pooled performance.

The centre finding materially undermines the repair rationale. The served
model is `-0.370417` ordered market bands cooler than the market on the joint
population. Joint blindness moves it only `-0.010491` bands relative to the
full row, **2.83%** of that displacement in absolute magnitude, with a median
of zero and an almost even cool/warm split. More importantly, in the target
excluded lane blindness moves the centre **warmer** by `+0.005453` bands while
the served displacement is `-0.297504` bands cooler than market. Blindness is
therefore not the excluded-lane centre mechanism.

The effect is also not stable enough to transfer casually: daily-first
blindness cost is positive at 09:00-11:00, negative at 12:00-13:00, and nearly
zero at 14:00. Five of twelve markets have a negative point estimate, including
NYC and Toronto. The severe-tail finding survives this heterogeneity better
than pooled Brier, but it does not turn the line into a broad centre repair.

No repair, candidate, artifact, fit, held-candidate score, feature/sidecar
write, fresh-date read, production-host access, or operational change was made.

## Scope and exact estimand

The work is based exactly on
`codex/workstation-spec-contract-repair-2026-08-21a @ 37183243` on branch
`codex/workstation-measure-blindness-causally-2026-08-22a`. Every branch in the
stack remains held and unmerged.

The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\measure-blindness-causally-2026-08-22a`,
outside the mirror. `data/` was read-only. The experiment used only the frozen
July 22-26 development corpus and effective cutoffs 09:00-14:00. It did not
read, enumerate, evaluate, or substitute July 27-31, August 1-3, or August
6-19. The safe WU reader stopped both the daily and hourly current-year streams
at July 26; the hourly stop was an exact daily-`row_count` prefix, not a scan
for the first July 27 row.

The within-model intervention is:

1. Start with each immutable captured serving envelope, market price, outcome,
   hard floor, active artifact, and every unaffected captured feature.
2. Add only the ten affected values from the existing read-only WU archive,
   using target-date rows whose valid local minute is no later than the frozen
   effective cutoff.
3. Run the incumbent model as the **full** arm.
4. For a blind arm, replace the requested numeric fields with null before the
   active artifact's fitted `SimpleImputer` and replace wind/cloud group with
   null before one-hot construction. This yields the exact serving mechanism:
   fitted medians and all-zero categorical vectors.
5. Run the entire incumbent path again, including empirical/HGB composition,
   floor, calibration, native distribution, and market-band probability
   mapping. No model is fitted or altered.

This identifies the causal response of the **fitted incumbent model** to the
input intervention on the declared rows. It is not yet a causal estimate of an
operational repair:

- The retained WU archive has observation valid times but no capture-time
  publication receipts. A valid-time row may not have been known when the
  snapshot was built. Phase R still needs its separate current-day availability
  proof.
- The values are in the artifact's WU contract. METAR/ECCC have different
  cadence, precision, pressure definitions, wind representations, and weather
  categories. The result does not estimate a retrained Phase F model.
- It measures how the existing fitted trees use observed information. A
  retrain can learn a different function and different missingness behavior.

The experiment uses no market centre, oracle tilt, winner-aware selector, or
hindsight decision about whether to apply an arm. Market prices enter only as
the contemporaneous benchmark in excess/severe metrics.

## Integrity and mechanism verification

The development identities are unchanged:

| Input | SHA-256 |
| --- | --- |
| Development corpus | `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d` |
| Accepted replay rows | `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd` |
| Accepted floor trace | `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b` |

All 60 local market-day folders and 10,885 manifest-pinned replay records were
verified against the manifest before selection. Re-running the as-served arm
matched all **31,548 / 31,548** accepted 09:00-14:00 band probabilities exactly;
mean and maximum absolute deltas were both `0.0`.

The blind transform was independently checked in all 72 market/hour artifact
groups:

- 576 numeric cells landed on the exact fitted artifact median;
- 864 wind/cloud dummy cells remained exact zero; and
- no affected numeric was sent to an HGB native-missing branch.

The WU reconstruction populated 358/360 market-hour-days for two-hour warming,
359/360 for three-hour pressure trend, and 360/360 for each other field. This
left 2,855 of 2,868 snapshots jointly eligible. Per-field estimates use every
row where that field is populated and never select on outcome or whether the
intervention helps.

## Joint effect

Positive deltas mean blindness is worse than the full row. Daily-first Brier
averages snapshots within market-day before averaging market-days. The severe
set is frozen from the joint-blind arm before comparing squared error, avoiding
a post-treatment tail selector.

| Scope | Eligible snapshots / market-days | Full daily-first Brier | Blind daily-first Brier | Blind - full daily-first | Pooled blind - full | 95% cluster interval | Frozen severe rows | Severe SSE reduction from restoration | Blind - full centre |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All | 2,855 / 60 | 0.762121 | 0.772019 | **+0.009899** | +0.008581 | [-0.022842, +0.041688] | 1,545 | **12.77%** [8.60%, 17.53%] | -0.010491 |
| Frozen-gate excluded | 2,262 / 56 | 0.790906 | 0.799116 | **+0.008210** | +0.004273 | [-0.023948, +0.042744] | 919 | **15.23%** [9.43%, 21.54%] | **+0.005453** |
| Frozen-gate qualified | 593 / 29 | 0.618017 | 0.643103 | **+0.025086** | +0.025013 | [-0.034241, +0.085969] | 626 | **9.24%** [4.71%, 14.05%] | -0.071308 |

The pooled cost is about 1.30% of full daily-first Brier overall and 1.04% in
the excluded lane. That is not zero, but it is far smaller than the withdrawn
51.40% oracle claim. The tail result is the material part: the full row removes
`94.120714` squared-error units on the frozen severe set, `66.150016` of them in
the excluded lane.

The qualified lane has the largest pooled effect even though the proposed
Phase F rationale targets the excluded lane. That does not authorize applying
anything there: release #1 and the held floor-gate candidates still own the
qualified population and sequencing is unchanged.

## Phase R versus Phase F footprints

The accepted `-08-21a` contract does not support a disjoint field partition.
If exact current-day public WU history is available, Phase R can populate all
ten fields. The common METAR contract directly covers nine because it lacks
relative humidity; ECCC can cover all ten for Toronto. These are overlapping
deployment footprints, so they are priced separately and **must not be added**.

| Footprint | Fields blinded from WU full state | Scope | Daily-first blind - full | Pooled blind - full | 95% cluster interval | Severe SSE reduction from restoration | Centre shift |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Phase R exact WU | all ten | all markets | +0.009899 | +0.008581 | [-0.022842, +0.041688] | 12.77% [8.60%, 17.53%] | -0.010491 |
| Phase R exact WU | all ten | excluded lane | +0.008210 | +0.004273 | [-0.023948, +0.042744] | 15.23% [9.43%, 21.54%] | +0.005453 |
| Phase F common METAR footprint | nine, excluding humidity | all markets | +0.011907 | +0.010907 | [-0.017033, +0.039295] | 12.62% [8.28%, 17.43%] | -0.014021 |
| Phase F common METAR footprint | nine, excluding humidity | excluded lane | +0.008150 | +0.004288 | [-0.021687, +0.037677] | 14.49% [8.08%, 21.24%] | +0.005962 |
| Phase F ECCC-complete footprint | all ten | Toronto only | **-0.091901** | -0.099084 | [-0.253892, +0.124917] | 3.48% on 39 severe rows | -0.017209 |

These are still WU-valued incumbent-tree ablations. The METAR/ECCC labels name
which fields those sources could eventually observe; they do not pretend that
WU values are source-parity evidence. The Toronto point estimate is especially
unfavorable to a complete Phase F claim: full WU state worsens pooled Brier on
these five Toronto days even while helping slightly on its 39 severe rows.

The common-nine arm costs slightly more than the all-ten joint arm even though
it blinds fewer fields. That is a real tree interaction: humidity's marginal
effect after the other nine are blind differs from its standalone effect.
Neither group nor single-field effects are additive.

## Per-field effects

Positive daily-first values mean that field's blindness hurts the incumbent;
negative values mean the full value hurts on this window. The severe columns
report the reduction in squared error when the field is restored on the same
joint-blind-defined tail. Intervals are market-day cluster percentiles for the
all-population daily-first effect.

| Field blinded | Eligible snapshots | All daily-first | 95% interval | Excluded daily-first | Severe reduction, all | Severe reduction, excluded | Mean centre shift |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pressure` | 2,868 | **+0.010270** | [-0.009339, +0.029710] | **+0.010512** | **4.22%** | **5.48%** | -0.007009 |
| `rise_from_7am` | 2,868 | +0.004625 | [-0.005105, +0.016782] | +0.003590 | 1.78% | 3.11% | +0.009726 |
| `dewpoint_c` | 2,868 | +0.003360 | [-0.008379, +0.014879] | +0.007031 | **3.29%** | 2.68% | -0.019123 |
| `humidity` | 2,868 | +0.002637 | [-0.012102, +0.019091] | +0.000586 | 0.81% | 1.01% | +0.003841 |
| `warming_rate_2h` | 2,855 | +0.002401 | [-0.003396, +0.009730] | -0.001098 | 1.32% | 1.15% | +0.001660 |
| `cloud_group` | 2,868 | -0.000552 | [-0.009045, +0.008712] | +0.000381 | 0.23% | 0.11% | +0.001674 |
| `wind_group` | 2,868 | -0.000624 | [-0.007615, +0.006005] | -0.002096 | 1.47% | 0.75% | -0.010974 |
| `wind_speed_kmh` | 2,868 | -0.001424 | [-0.012079, +0.008995] | -0.001658 | 0.25% | **-0.45%** | +0.002707 |
| `pressure_trend_3h` | 2,861 | -0.002189 | [-0.014002, +0.008206] | -0.002354 | 1.22% | 1.43% | -0.001679 |
| `hours_at_peak` | 2,868 | -0.002439 | [-0.005960, +0.000856] | -0.002451 | -0.18% | 0.10% | +0.002725 |

Pressure is the only field with an all- and excluded-lane daily-first point
estimate near the joint effect. Pressure, dew point, and rise since 07:00
carry most of the severe-tail value. That is useful prioritization, but pressure
is also the field with the least portable source contract: WU pressure, METAR
altimeter/SLP, and ECCC station/MSL/altimeter pressure are not interchangeable.
A large incumbent-tree response therefore raises the evidence bar for Phase F;
it does not lower it.

Wind speed, peak age, wind group, cloud group, and pressure trend have negative
pooled point estimates in the existing trees. Some still help on the frozen
tail, which again shows that a broad pooled or centre narrative is too coarse.

## Direction check

| Scope | Served - market centre | Blind - full centre | Cool / warm share of blind shift | Finding |
| --- | ---: | ---: | ---: | --- |
| All jointly eligible | -0.370417 bands | -0.010491 | 48.65% / 49.70% | Tiny average cool shift; median zero; only 2.83% of observed displacement |
| Excluded lane | -0.297504 bands | **+0.005453** | mixed | Blindness is slightly warm, opposite the observed cool defect |
| Qualified lane | -0.648544 bands | -0.071308 | mixed | Same direction, but this is not Phase F's target lane |

Across all rows the blindness/observed-displacement correlation is `0.3601`,
but the treatment magnitude is tiny and sign-balanced. Correlation does not
rescue the mechanism claim. The direct excluded-lane intervention has the
wrong sign.

This resolves the tension from `-08-20a`: the earlier imputed-versus-native-NaN
diagnostic was not the requested treatment, but its warning was directionally
right. Exact median/all-zero blinding of populated rows also fails to reproduce
the excluded lane's cool centre displacement. Blindness can worsen severe
probability errors without being their centre cause.

## Transfer evidence

The transfer assumption is **stable incumbent treatment response**: conditional
on the captured non-affected envelope, market, hour, lane, and hard floor, the
full-to-blind response observed with cutoff-valid retrospective WU values is
assumed to approximate the response that would occur if those artifact-contract
values had actually been available at capture. Phase F adds a second and much
stronger assumption that a retrained METAR/ECCC contract retains that value.

The first assumption is only partly supported:

| Effective cutoff | Eligible snapshots | Daily-first blind - full | 95% cluster interval | Frozen severe SSE delta | Centre shift |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 09 | 503 | +0.025806 | [-0.020009, +0.071883] | +17.173442 | -0.006360 |
| 10 | 491 | +0.010090 | [-0.040009, +0.064037] | +21.961419 | -0.016505 |
| 11 | 481 | +0.035867 | [-0.030688, +0.100067] | +22.343855 | -0.052481 |
| 12 | 472 | -0.005591 | [-0.058095, +0.045116] | +9.866292 | -0.011031 |
| 13 | 446 | **-0.025545** | [-0.104348, +0.048990] | +10.486707 | -0.006790 |
| 14 | 462 | +0.000196 | [-0.072460, +0.066658] | +12.288999 | +0.032099 |

Every hour helps on the frozen severe tail, but the daily-first sign reverses after
midday and every hourly interval crosses zero. Market heterogeneity is larger:
Houston (`+0.110806`) and Los Angeles (`+0.082364`) benefit materially, while
NYC (`-0.067905`) and Toronto (`-0.091901`) go the other way. Dallas, Houston,
and Los Angeles have positive market-specific intervals; NYC has a negative
one. Seven markets are positive and five negative by point estimate.

Date effects are also mixed: `-0.044218`, `+0.040258`, `-0.001150`,
`+0.037055`, and `+0.017549` from July 22 through 26. The aggregate remains
positive in every leave-one-date-out calculation (`+0.002309` to `+0.023428`)
and every leave-one-market-out calculation (`+0.000725` to `+0.019153`), so no
single date or market creates the sign. The wide cluster interval reflects real
cross-cluster instability rather than one obvious outlier.

The severe-tail response is the best-supported transferable fact. Even that
is conditional on current-day WU availability and does not identify how a new
source contract or retrained model will behave.

## Is Phase F worth a retrain?

**No, not as a fleet-wide or centre-repair project. Retire that broad claim
now.**

The reasons are quantitative:

1. The target excluded lane's daily-first cost is only `+0.008210`, roughly
   1.04% of full Brier, and its cluster interval spans meaningful harm and
   benefit.
2. Blindness moves the excluded centre in the wrong direction. It cannot be the
   proposed cause of the `-0.297504`-band cool displacement.
3. The larger pooled effect sits in the qualified lane, whose sequencing and
   ownership remain elsewhere.
4. Hour, date, and market effects are heterogeneous; Toronto's complete-footprint
   point estimate is strongly negative.
5. Phase F must pay for a new source contract, shared train/live normalizers,
   feature version, retrain, parity producer, and full fresh gate. The experiment
   deliberately does not price those costs or prove source equivalence.

There is one narrower result worth retaining as research context: restoration
removes 15.23% of blind-arm severe-tail squared error in the excluded lane,
concentrated mainly in pressure, rise since 07:00, and dew point. If the line
is revisited after release #1, it should be a predeclared **severe-tail-only** experiment for those
fields, with pressure-definition overlap proven first. It should not be a
general ten-field retrain and should not be justified as a centre repair.

The cheap conditional Phase R path is a separate decision. A `+0.009899`
daily-first point estimate plus severe-tail improvement may make an exact
public-WU restoration worth measuring after release #1 **if** live availability
and byte/value/unit parity are first proven. This experiment does not supply
that proof or authorize the repair.

## Handback and guardrails

- Honest joint causal model-input cost: `+0.009899` daily-first Brier overall,
  `+0.008210` excluded, both uncertain across market-days.
- Severe-tail cost: 12.77% overall and 15.23% excluded, with positive cluster
  intervals.
- Direction: tiny and balanced overall; opposite the observed cool defect in
  the excluded lane.
- Highest-value individual fields in the existing trees: pressure, rise since
  07:00, and dew point; effects are non-additive and not Phase F source parity.
- Recommendation: do not undertake broad Phase F; retain at most a later narrow
  severe-tail hypothesis. No work begins before release #1.

`-08-16a` remains queued for 2026-08-05 04:30. No release, pointer,
promotion, serving, scheduler, capture, mirror, ACL, paid-provider, production
host, or master state changed. No PR or merge was created.

## Evidence identities

| Evidence | SHA-256 |
| --- | --- |
| Experiment declaration | `2461c41ba9173150dcf02e631b6ab8f59a9ae520fb27227ffef7b442d58083b1` |
| Measurement script | `201610650365accfe7a524082314f76cf75a5cde6e552a59a34168fdeec96778` |
| Selected normalized WU payload | `b1add9771ac55d1cc41a426564b682841451be6e6c8cc3536805eb76428f7d55` |
| Snapshot-arm effects | `832a9b54c3669e941d0a2e259803de006b825c48e92ca061445d5876b83b77d2` |
| Causal-ablation summary | `3a4977d7bd26fe58e2698672b4ff32c9e9a35b7f68a7f75813a9cb8ff1f485a4` |
| Independent verifier | `7a79ad73ea019ac981150989002fa2f792818b53a7c131bda16ba82a6d969cb5` |
| Independent verification | `7fe2ec0d3e4f2011e64ac4da7b8f30044e1a7592ab405c5cdf4351164e7ce6cb` |

The independent verifier passed 144 recomputed summary comparisons across
14 arms and all 40,152 snapshot-arm rows. Audit scripts and generated JSON/CSV
remain ignored under the declared run root; this report is the only repository
change.
