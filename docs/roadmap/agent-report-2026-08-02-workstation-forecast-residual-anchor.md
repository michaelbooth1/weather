# Workstation forecast-residual anchor report - 2026-08-02

## Pre-registration - frozen before fitting or development-result inspection

Declared at `2026-08-02T19:10:05.3897960Z`. The sole output root is
`C:\Users\Michael\Documents\github\weather\scratch\runs\forecast-residual-anchor-2026-08-18a`,
outside the mirror. `data/` and the mirror remain read-only.

This mission is build-only. It will read exactly `2026-07-22` through
`2026-07-26`, fit and select through the forward folds below, and freeze one
research artifact. It will not read, enumerate, replay, or score July 27-31,
August 1-3, or August 6-19. It will not use a substitute date. No fresh-date
probability or result will be produced.

The application population is frozen as the complement of the 20% floor gate:

`not floor_available or floor_removed_mass <= 0.20`

Rows satisfying `floor_available and floor_removed_mass > 0.20` remain owned
by whatever 08-16a selects. The composite development replay must copy the
incumbent probability text for every such row, and the build must fail unless
the number changed is exactly zero. The floor itself remains a hard physical
constraint whenever it is available, including inside the excluded lane.

### Target, model, and decoding

For each snapshot, round the captured native-unit `forecast_high` half-up to
an integer anchor `A`. The training label is the integer native settlement
bucket minus `A`. Fit one `HistGradientBoostingClassifier` for each existing
market/effective-cutoff group using the frozen parent model's feature list.
The estimator parameters are fixed at `max_iter=50`, `max_leaf_nodes=15`,
`learning_rate=0.05`, and `random_state=42`. Outcome, market-price, settlement,
floor, date, and gate fields are forbidden predictors. Snapshot weights give
each market-date equal total training weight.

Decode residual class `r` to native bucket `A+r`. Blend this distribution with
the date-balanced empirical residual prior, then remove all mass below the
frozen floor and renormalize whenever a floor is available. Convert the final
native distribution to the complete market bands without clipping or losing
mass. Missing anchors or model groups are explicit unchanged-incumbent
fallbacks and are reported, never reconstructed.

There is no feature search, architecture search, temperature search, or
after-the-fact parameter expansion. Temperature is fixed at `1.00`; prior
additive mass is fixed at `0.10`. The only selectable grid is the Cartesian
product of model weights `{0.75, 0.90}` and ordinal strengths `{0.50, 1.00}`.

### Two-sided ordinal smoothing

Ordinal smoothing is part of every candidate from the start and acts on the
post-blend, post-hard-floor distribution expressed relative to forecast anchor
`A`. On the positive side, compare `P(R=+1)` with `P(R>=+2)`; on the negative
side, compare `P(R=-1)` with `P(R<=-2)`. For either side with an adjacent
valley, transfer `s * (tail-adjacent) / 2` from that tail to its adjacent
bucket, preserving tail proportions. `P(R=0)`, the opposite side, the hard
floor, and total probability are preserved. Before/after adjacent and tail
means, valley counts, and maximum floor violation are mandatory evidence.

### Cutoff-vintage proof

The anchor must be rebuilt from the exact hash-bound captured replay input and
must match the accepted replay feature. A row is rejected if it is marked as
reconstructed; if its capture is off the target date; if a source `fetched_at`,
provider issue time, or provider update time is later than capture; or if the
captured anchor differs from the accepted `feature_forecast_high`. Missing
provider metadata is reported separately and cannot be invented. Only the 60
manifest-pinned market-days and their pinned snapshots may be opened. This
proof is required before fitting; any rejected excluded snapshot remains an
unchanged-incumbent fallback and cannot contribute a label.

### Development folds and selection rule

The folds are frozen as:

1. train July 22-23, validate July 24;
2. train July 22-24, validate July 25;
3. train July 22-25, validate July 26.

Selection metrics use excluded validation snapshots only and group Brier by
market-day first. Positive excess is the sum over band rows of
`max(0, candidate_brier - market_brier)`. A severe row has positive excess and
absolute candidate-versus-market probability distance at least `0.30`.

A grid point is eligible only if both sides are monotone in aggregate after
smoothing, its excluded positive excess is strictly below the incumbent's,
and its excluded severe-row count is strictly below the incumbent's. Among
eligible settings, minimize excluded daily-first Brier, positive excess,
severe rows, then model weight and smoothing strength. If none is eligible,
select the monotone setting with the same lexicographic ordering solely to
freeze a diagnostic artifact and mark it `NO_DEVELOPMENT_WIN`; it must not be
described as advancing. No criterion or fallback will be added after outcomes
are inspected.

The final artifact is refit on all five development dates with the selected
parameters, declares no score dates, and remains candidate-only. The handback
will report its SHA-256, exact frozen parameters, cutoff-vintage proof,
excluded-only fold evidence, monotonicity evidence, the qualified-row
invariance check, and the development-selection/family-wise-error caveat.

## Build result

**BUILT AND FROZEN; UNSCORED; HELD.** The predeclared selection rule returned
`NO_DEVELOPMENT_WIN`. The diagnostic fallback selected model weight `0.75` and
ordinal strength `0.50`, with temperature `1.00` and prior alpha `0.10` fixed.
The final research artifact is:

`C:\Users\Michael\Documents\github\weather\scratch\runs\forecast-residual-anchor-2026-08-18a\final\forecast-residual-anchor-candidate.pkl`

Its SHA-256 is
**`abd4731bb5c0dfbd41fb2a1656eb5a6bb1b56c80e25f3892db4d6f546acccb1a`**.
It declares `status=CANDIDATE_ONLY_UNSCORED` and `score_dates=[]`. It is not an
advancing candidate and must wait without fresh scoring.

The artifact contains 160 market/effective-cutoff model groups fitted on the
five declared dates. A group with no eligible, vintage-valid excluded-lane
training row is absent and therefore remains an unchanged-incumbent fallback.
No runtime, variant-registry, release, or serving route references the artifact.

## Excluded-lane development evidence

Across 5,397 excluded validation snapshots, the residual model was applicable
to 5,172 and copied the incumbent on 225 anchor-missing fallbacks. It regressed
all three required measures:

| Metric | Incumbent | Forecast-residual candidate | Delta |
| --- | ---: | ---: | ---: |
| Daily-first multiclass Brier | `0.593783` | `0.755995` | **`+0.162212`** |
| Positive Brier excess vs market | `1401.663752` | `2484.766164` | **`+1083.102412` (`+77.27%`)** |
| Severe band rows | `1,797` | `3,665` | **`+1,868`** |

Every validation date regressed independently:

| Validation date | Excluded / modeled snapshots | Brier incumbent / candidate | Positive excess incumbent / candidate | Severe incumbent / candidate |
| :--- | :--- | :--- | :--- | :--- |
| `2026-07-24` | `1,916 / 1,829` | `0.588530 / 0.816059` | `494.966991 / 1097.773671` | `552 / 1,516` |
| `2026-07-25` | `1,873 / 1,735` | `0.562614 / 0.792843` | `454.233199 / 830.174495` | `634 / 1,334` |
| `2026-07-26` | `1,608 / 1,608` | `0.630204 / 0.659083` | `452.463563 / 556.817999` | `611 / 815` |

All four coarse settings failed the development-win rule. The selected pair is
only the predeclared lowest-key monotone diagnostic, not evidence of edge:

| Model weight | Ordinal strength | Candidate Brier | Positive-excess delta | Severe-row delta | Monotone | Win |
| ---: | ---: | ---: | ---: | ---: | :---: | :---: |
| `0.75` | `0.50` | `0.755995` | `+1083.102412` | `+1,868` | Yes | **No** |
| `0.75` | `1.00` | `0.758247` | `+1076.173947` | `+1,871` | Yes | **No** |
| `0.90` | `0.50` | `0.776970` | `+1195.734215` | `+1,853` | Yes | **No** |
| `0.90` | `1.00` | `0.772348` | `+1162.743176` | `+1,969` | Yes | **No** |

The evidence rejects this residual-distribution form on the declared
development population. Anchoring on the forecast is directionally sensible,
but a snapshot-rich classifier trained on only two to four distinct settled
dates does not estimate the residual distribution well enough here.

## Ordinal and hard-floor evidence

The selected half-strength smoothing repaired both sides in aggregate without
putting any mass below an available floor:

| Residual side | Before adjacent / tail | After adjacent / tail | Aggregate monotone before / after |
| :--- | :--- | :--- | :---: |
| Negative: `P(R=-1)` / `P(R<=-2)` | `0.260712 / 0.334521` | `0.326541 / 0.268692` | No / **Yes** |
| Positive: `P(R=+1)` / `P(R>=+2)` | `0.129039 / 0.058760` | `0.140441 / 0.047359` | Yes / **Yes** |

Maximum final mass below the hard floor was exactly `0.0`; independently
recomputed OOF simplex error was at most `6.66e-16`. Half-strength smoothing
does not remove every pointwise valley: all 2,059 negative-side and 615
positive-side valley snapshots remain locally ordered the wrong way even
though non-valley rows make both aggregate means monotone. That limitation is
another reason the frozen artifact is diagnostic only.

## Cutoff-vintage proof

All 10,885 replay records matched their manifest-pinned hashes, and the
manifest excluded reconstruction. Of those, 10,562 had an available forecast
anchor; every one rebuilt exactly from its captured source envelope and matched
both the accepted `feature_forecast_high` and effective cutoff. The remaining
323 had no finite captured forecast anchor and were rejected from fitting, not
reconstructed. On the validation folds, this produced 225 unchanged fallbacks.

The audit inspected 234,152 captured `fetched_at` values, 9,906 `issued_at`
values, 9,871 provider issue times, and 10,885 provider update times. It found
zero post-capture values and needed zero timezone assumptions. Provider issue
metadata was absent in 9,906 envelopes and provider update metadata in 9,871;
those absences are reported rather than invented. The available-anchor proof
therefore rests on the immutable captured input hash, capture-time envelope,
all present provider metadata, and an exact anchor rebuild—not on later API
responses or reconstructed forecasts.

## Disjointness and selection-risk handback

The composite OOF replay covered 6,523 validation snapshots and 71,753 band
rows. All 12,386 band rows in the floor-gate-qualified lane copied the incumbent
probability text exactly: **zero qualified rows changed**. The later 08-16a
choice for those qualified rows is therefore untouched. The excluded lane is
additive and disjoint, and the floor remains hard inside both lanes.

The family-wise and development-selection risk remains real: four settings
were compared on only three forward validation dates, and the diagnostic
fallback was chosen on those same dates. Here that risk cannot rescue the
candidate—the selected form and every alternative regressed badly on every
date—but the artifact still must not be interpreted as a fresh rejection or
scored on a substitute date. The queued 08-16a pass remains separate.

## Evidence and guardrails

| Field | Value |
| :--- | :--- |
| Handoff source | `origin/master` `5a63cd69` |
| Exact stacked base | `b5be028a4b1ffc2d731d0cfb06f40773449b6d0a` |
| Topic branch | `codex/workstation-forecast-residual-anchor-2026-08-18a` |
| Pre-registration commit | `27fdae40` |
| Implementation commit | `06b38d2d` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\forecast-residual-anchor-2026-08-18a` |
| Declaration time | `2026-08-02T19:10:05.3897960Z` |
| Frozen application population | `not floor_available or floor_removed_mass <= 0.20` |
| Frozen parameters | weight `0.75`; ordinal `0.50`; temperature `1.00`; prior alpha `0.10` |
| Frozen artifact | `abd4731bb5c0dfbd41fb2a1656eb5a6bb1b56c80e25f3892db4d6f546acccb1a` |
| Verdict | `BUILT_UNSCORED_NO_DEVELOPMENT_WIN`; **HELD** |

| Evidence | SHA-256 |
| :--- | :--- |
| Run declaration | `44a97d5e8494b9720f743f49c69971ad7df4e1c56befa7d93d04145b77850a71` |
| Development corpus | `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d` |
| Development replay rows | `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd` |
| Development floor trace | `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b` |
| Parent ordinal continuation candidate | `ba6cd8b7c02a6d6890762b17ab139fb9a3afbf146239b9e617ea192eea4970ef` |
| Cutoff-vintage proof | `172243084ef83c20c2ad388a81edcdc2c905f69b1c1767a054ac0e2d741ec150` |
| Development selection | `c27e2562c8405038fb4a0a65ebbba610f143677d26548f82f7f3ea72b76ab0e2` |
| OOF composite rows | `7f0793c3a44a1580d8338c0868e4324f7aa12c47e1519a21d696ce11bbf5fcf4` |
| OOF native distributions | `4cd494c54a6e9fe6116be870a4e048666fb247db10aa8ab9077fb70e67636af9` |
| Forecast-residual artifact | `abd4731bb5c0dfbd41fb2a1656eb5a6bb1b56c80e25f3892db4d6f546acccb1a` |
| Final summary | `9d90b8af50f29cfbe9b8070050fd869e1be60317a23b01d5829e19a76ddc8b61` |

The broader calibration, feature-parity, and schema suite passed 390 tests
plus 713 subtests. The focused builder/continuation/schema suite passed 22
tests. Independent artifact verification confirmed 160 model groups, empty
score dates, exact qualified-row copying, and normalized OOF distributions.

`data/` and the mirror remained read-only. No date outside July 22-26 was read,
enumerated, replayed, evaluated, or substituted. No fresh date was scored. No
production host, sync credential, paid provider, release, promotion, pointer,
serving, scheduler, capture, mirror topology, or ACL state was accessed or
changed. No PR, merge, or master push was made.
