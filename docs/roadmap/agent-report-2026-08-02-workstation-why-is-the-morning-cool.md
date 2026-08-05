# Workstation morning-centre diagnosis - 2026-08-02

## Verdict

**Yes: the base HGB is already systematically cool before the prior blend,
live-signal path, hard floor, cap, exact-distribution calibration, or market-band
conversion. The primary cause is a cool and stale fitted training-label prior
with insufficient upper support; the fitted weather response warms that prior
but does not catch up to late-July conditions. The hard floor then masks more of
the same upstream bias in the evening than in the morning.**

On all 2,868 July 22-26 snapshots at effective cutoffs 09:00-14:00, the raw
HGB expected native class was `-1.2131 C-equivalent` below the WU settlement
bucket, with a market-day cluster interval of `[-1.7928, -0.7035]`. The raw
centre was cool on 70.0% of the 60 market-days. In native units, the 11 U.S.
markets pooled at `-2.3422 F` `[-3.4290, -1.3872]`; Toronto was `-0.2436 C`
`[-0.7725, +0.2062]` on five dates. Every individual hour from 09 through 14
has a wholly negative pooled interval. Eleven of twelve markets have a negative
point estimate; six have a negative five-date interval. Chicago is the lone
positive point estimate.

The result also holds against the contemporaneous market after mapping the
unchanged raw distribution only for diagnosis: HGB is `-1.0384` ordered bands
cooler than market in the morning `[-1.4027, -0.6935]`. The model/prior blend
warms that to `-0.8036`, live signals to `-0.7194`, and the hard floor by a
further `+0.5922` bands. The plausible cap removes part of the floor movement,
leaving the served model `-0.3836` bands cooler than market. In the frozen-gate
excluded lane, the raw and final displacements are `-0.8629` and `-0.6207`
bands; downstream processing warms rather than creates the defect.

The evening comparator sees the same raw defect: `-0.9864 C-equivalent`
`[-1.4799, -0.5666]` against settlement and `-0.8006` bands against market.
The raw morning-minus-evening difference is only `-0.2267 C-equivalent`
`[-0.3816, -0.0680]`. What changes materially is masking: the floor warms the
centre by `+0.5922` bands in the morning versus `+1.0715` in the evening, a
paired difference of `-0.4793` `[-0.7302, -0.2611]`. The final market-relative
centre therefore changes from `-0.3836` bands in the morning to `+0.2547` in
the evening. The floor is a necessary control doing its job; it reveals the
upstream defect by masking it unevenly through the day and must not be weakened.

No repair, candidate, artifact, fit, tuning, scoring comparison, fresh-date
read, or operational change was made.

## Scope and exact measurement

The branch is based exactly on
`codex/workstation-measure-blindness-causally-2026-08-22a @ ababbfd1`. The sole
output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\why-is-morning-cool-2026-08-23a`,
outside the mirror. `data/` was read-only. The analysis used only the 60
manifest-pinned market-days from July 22 through July 26. It did not read,
enumerate, evaluate, or substitute July 27-31, August 1-3, or August 6-19.
July 31 remains the `rows[-1]` POST-regime boundary.

The raw estimand is calculated directly from each tracked per-market artifact:

1. Verify the immutable local captured envelope against its manifest record
   hash and invoke the base-commit feature extractor at the accepted effective
   cutoff.
2. Apply the artifact's fitted `SimpleImputer`, restore native NaN only for the
   serving contract's explicit native-NaN columns, and construct the exact
   artifact-declared wind/cloud dummy set.
3. Call `model.predict_proba()` and take the expected fitted native class.
4. Subtract the WU settlement bucket. Negative is cool. No artifact temperature,
   climatology/prior blend, live distribution signal, floor, cap, downstream
   calibration, MAP selection, rounding, or band conversion enters this
   estimate.

Per-market results remain in the configured settlement unit. Pooled raw
residuals explicitly convert deltas to Celsius-equivalent (Fahrenheit deltas
times `5/9`; Celsius deltas unchanged); distributions themselves remain native.
The market-relative stage trace is a separate descriptive view in ordered
market bands and is never substituted for the raw native estimand.

Intervals use 2,000 deterministic bootstrap replicates at the market-day
cluster, averaging snapshots within each market-day first. “Morning” is
effective cutoff 09-14; “evening” is 15-20. Effective cutoff 20 includes later
captures whose feature-model hour is capped at 20, matching serving.

All 10,885 accepted captured records were hash-verified before selecting the
6,874 effective-cutoff 09-20 snapshots. Mapping each newly computed raw native
distribution to the accepted bands reproduced the retained HGB component with
maximum probability delta `6.66e-16` and maximum centre delta `5.33e-15`.

## 1. Raw bias by hour and market

Every morning hour is cool with a wholly negative interval:

| Effective cutoff | Snapshots | Raw HGB minus settlement, C-equivalent | 95% cluster interval | Raw HGB minus market, bands | Served minus market, bands | Floor shift, bands |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 09 | 503 | -1.1490 | [-1.7299, -0.6322] | -0.9655 | -0.7659 | +0.2066 |
| 10 | 491 | -1.1822 | [-1.7517, -0.6785] | -1.0105 | -0.6291 | +0.3347 |
| 11 | 481 | -1.2901 | [-1.8327, -0.8184] | -1.0971 | -0.5105 | +0.4693 |
| 12 | 472 | -1.3122 | [-1.8609, -0.7998] | -1.0940 | -0.2549 | +0.7222 |
| 13 | 452 | -1.1532 | [-1.7043, -0.6401] | -1.0200 | -0.1157 | +0.8149 |
| 14 | 469 | -1.1920 | [-1.7943, -0.6881] | -1.0398 | +0.0222 | +1.0525 |

The market dispersion identifies where the pooled result is generated. Native
morning raw biases are Atlanta `-1.06 F`, Austin `-1.21 F`, Chicago `+0.44 F`,
Dallas `-3.70 F`, Denver `-6.21 F`, Houston `-0.60 F`, Los Angeles `-4.72 F`,
Miami `-1.64 F`, NYC `-1.33 F`, San Francisco `-0.13 F`, Seattle `-5.61 F`,
and Toronto `-0.24 C`. Dallas, Denver, Los Angeles, Miami, NYC, and Seattle have
wholly negative market-specific intervals despite only five dates each.

This is not merely an excluded-lane effect. Raw morning bias is
`-1.0043 C-equivalent` `[-1.4923, -0.5421]` in the excluded lane and
`-2.3482` `[-3.2225, -1.5587]` in the qualified lane. The gate selects rows on
which the raw distribution places more mass below the known floor, so the
qualified lane starts cooler and receives much more floor warming.

## 2. Why evening looks different

The upstream bias persists from morning into evening, while the floor's
opportunity to remove impossible cool mass grows with the observed high.

| Scope | Raw HGB minus settlement, C-equivalent | Raw HGB minus market, bands | Floor shift, bands | Served minus market, bands |
| --- | ---: | ---: | ---: | ---: |
| Morning, all | -1.2131 | -1.0384 | +0.5922 | -0.3836 |
| Evening, all | -0.9864 | -0.8006 | +1.0715 | +0.2547 |
| Morning, excluded | -1.0043 | -0.8629 | +0.1609 | -0.6207 |
| Evening, excluded | -0.6156 | -0.4611 | +0.1761 | -0.1935 |
| Morning, qualified | -2.3482 | -1.9668 | +1.5656 | -0.3402 |
| Evening, qualified | -2.0740 | -1.6804 | +2.1522 | +0.3877 |

Within the 48 market-days that appear in both excluded periods, morning and
evening raw bias are not distinguishable: paired difference
`+0.0879 C-equivalent` `[-0.2305, +0.4289]`; the floor-shift difference is also
small at `-0.0200` bands `[-0.0496, +0.0104]`. The all-row clock effect comes
from the growing qualified population and stronger qualified binding. This is
the requested mask explanation: evening is not generated by a different warm
base model. It is the same cool base distribution under a more informative
physical floor.

## 3. Cause attribution

### Training distribution and support: primary cause

The exact fitted HGB intercept recovers the artifact's training-label class
prior. Against the July 22-26 settlements, that prior is
`-2.7506 C-equivalent` cool `[-3.5672, -1.9581]`. The fitted feature response
warms it by `+1.5375` `[1.1468, 1.9215]`, leaving the observed raw bias of
`-1.2131`. Across the 12 market means, raw bias and training-prior gap correlate
`0.9621`.

The gaps are physically large: Dallas's prior is `7.82 F` below these outcomes,
Denver's `13.01 F`, Los Angeles's `8.15 F`, Seattle's `9.45 F`, and Toronto's
`1.45 C`. Most artifacts contain only 164 or 165 fitted daily rows per hour;
Miami has 439 and Toronto 649. The accepted
[provenance audit](agent-report-2026-08-02-workstation-prove-1000-blindness.md)
dates artifact contents to June 9-14 and reconstructs their rows from the
corresponding `+/-7`-day target-season history. They are early/mid-June
target-season fits serving late-July outcomes.

Upper support is a concentrated amplifier. Settlement exceeds the artifact's
maximum fitted class on 6/60 morning market-days (Austin, Dallas, Denver twice,
Houston, and Seattle), and forecast high exceeds the class maximum on 8.26% of
morning snapshots. Those six days average `-5.8731 C-equivalent` raw bias and
contribute 48.41% of the total signed daily cool displacement. The remaining
54 days are still cool at `-0.6953` `[-1.0434, -0.3795]`, so class clipping is
material but not the complete explanation.

### Feature response: warm, not the source

The contemporaneous forecast is itself `+0.4835 C-equivalent` warmer than
settlement `[0.2118, 0.7594]`; raw HGB is `-1.6995` colder than that forecast
`[-2.2657, -1.1993]`. Neutralizing observed forecast high to its artifact
missing-state makes raw HGB another `-0.5196` colder. Neutralizing live reading,
high so far, or current temperature likewise cools the centre by `-0.5535`,
`-0.3569`, and `-0.1791 C-equivalent`. These observed inputs are fighting the
cool prior, not causing it.

One-at-a-time fitted partial-dependence responses agree. Moving from each
artifact/hour group's observed 10th to 90th percentile warms raw centre by
`+1.3599 C-equivalent` for live reading, `+0.7731` for forecast high, `+0.4763`
for high so far, `+0.3215` for current temperature, and `+0.1969` for forecast
gap. Direction is positive in 68%-100% of usable artifact/hour groups for
these features. `live_reading_minus_high` has a detectable but immaterial
`+0.0163 C-equivalent` neutralization movement in the cool direction. The
affected WU surface fields from `-08-22a` remain at their
fitted medians/all-zero categories and have zero individual neutralization
movement on this as-served diagnosis, consistent with the causal blindness
result. There is no fitted feature with evidence of imposing a material share
of the pooled cool shift.

### Label, loss, rounding, and band conversion: not directional causes

- Training and evaluation use the same native WU settlement contract:
  `native_bucket()` selects the explicit native bucket, `round_half_up()` uses
  `floor(value + 0.5)`, the feature record carries that as `final_bucket`, and
  training sets `y = df["final_bucket"]`. There is no downward rounding rule.
  A uniformly cool evaluation label would make prediction-minus-label warmer,
  not create the negative residual measured here. WU's physical accuracy is
  not separately adjudicated because WU is the declared settlement proxy.
- All 168 artifact/hour bundles use multiclass categorical `log_loss` with no
  class weighting. That objective has no warm-versus-cool direction penalty
  and no ordinal-distance term. Its direction symmetry rules out an explicit
  cool-loss preference, but its categorical shrinkage and limited tree fit can
  leave predictions close to a stale class prior.
- The raw expected-class estimate happens before market bands or rounding. Its
  MAP-class residual is `-0.9493 C-equivalent`, less cool than the expected
  centre's `-1.2131`; downward MAP discretization therefore does not manufacture
  the result. Market-band conversion is downstream and cannot cause the raw
  native residual.

The causal classification is therefore **training-distribution/support mismatch
plus insufficient fitted conditional catch-up**, amplified on out-of-support
hot days. Categorical objective design is a plausible persistence mechanism,
not a demonstrated directional asymmetry. Label construction, a cool observed
feature, downstream blending, calibration, and band conversion are rejected as
the source of the raw defect.

## Tractability and next experiment

The most tractable future hypothesis is a target-date-aligned artifact refresh
that preserves native units, expands class support beyond cutoff-valid forecast
and plausible settlement extremes, and predeclares raw-centre non-regression
alongside Brier/log-loss and hard-floor invariants. It directly addresses both
the stale prior and the six clipped days without weakening the floor. It is
still a roll-sensitive fit/artifact change requiring the existing train/serve
feature-parity, replay, release-binding, and fresh-gate contracts; this mission
does not authorize it.

If a season-aligned HGB still sits materially below a warm forecast, the next
broader experiment should model an ordinal or continuous final-high residual
around the cutoff-valid forecast rather than use a post-hoc market/hour shift.
That is less tractable because it changes objective and distribution assembly.
The `-08-22a` result still rules out a fleet-wide ten-field Phase F retrain as
the first move. The floor is not a repair target.

## Handback and evidence

- Raw base HGB is systematically cool at 09-14 with a wholly negative pooled
  interval and a wholly negative interval at every individual hour.
- The same raw bias remains in the evening. Stronger and more frequent floor
  binding masks it there and reverses the final all-row market-relative sign.
- Primary cause: stale/cool training-label prior and limited upper support;
  observed live features move warmer but cannot overcome it.
- No evidence supports cool label construction, directional loss asymmetry,
  downward discretization, or downstream stages as the raw cause.
- Most tractable future line: date-aligned support/prior refresh first; ordinal
  forecast-residual design only if that remains insufficient. No work starts
  here.

The independent verifier passed 436 recomputed means/interval endpoints and
feature summaries with maximum absolute summary delta `6.66e-16`. The final
evidence manifest SHA-256 is
`09679b5d722a25f31390a42f846f42ca825b107bc744169846b3696b5d817dfa`.

| Evidence | SHA-256 |
| --- | --- |
| Declaration | `c7c36257a4a760bca487578daed48eb8fff4da016f1ddaa87178a9699fb2897e` |
| Diagnosis script | `015b9e15e8d31ac2ec8989e405199618e91b4918466a0b3abb78f237f0bfee30` |
| Snapshot raw-HGB diagnosis | `6c981f8246ebf35c9560ed5271b7f3dd18e3b2173e7afb793f4618521f9897c0` |
| Diagnosis summary | `f4ec7ca63a8d01d33c23f0cf118b024edf44f4e53e02032e89a7d97f616fe899` |
| Training-prior audit | `dd8ab1805638b4bf6f792cc0f743e67e8d47c0cff12409a688c9b3ba9af5c606` |
| Feature neutralization | `1b7cc08ad78bc4a93add6f3cee25b3de31d994655e51e78713c2c7341d71a784` |
| Partial-dependence summary | `d982ece86223ed744850ba9e203260a44e1e7bf0e3488fd2438652fd498b702e` |
| Label/objective contract audit | `fbbfc31ec8a2ba6809dd3df150ba1c943b364d76b4f2ed870cf46fa81ddcf4e0` |
| Independent verifier | `c4f1e568ec8460c2f6c86a41e0df0648896e10f66cfd5bab13cbf98a269098da` |
| Independent verification | `9584643df4a6079de377001329c1eda3fd8ff48f82d5c7cb20cc1cf5b3ef5ea2` |

`-08-16a` remains queued for 2026-08-05 04:30. No release, pointer,
promotion, serving, scheduler, capture, production host, mirror, ACL, paid
provider, PR, merge, or master state changed.
