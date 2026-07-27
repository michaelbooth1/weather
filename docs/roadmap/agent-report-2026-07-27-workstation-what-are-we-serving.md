# Agent report - 2026-07-27 workstation what are we serving?

Status: **MISSION 1 COMPLETE; THE RECORDED-OUTPUT CONTROL
UNDERPERFORMS REPLAY-FINAL; ACTIVE SERVING REMAINS NOT PROVEN. MISSION 2
STOPPED AT ITS APPLICABILITY GATE; THE PROPOSED CONTINUOUS
CELSIUS-TO-FAHRENHEIT CONVERSION MECHANISM IS NOT THE ACCEPTED MODEL AND
CANNOT BE MEASURED ON THE FROZEN CORPUS. MISSION 3 NOT RUN OUTSIDE ITS
MORNING WINDOW.**

This report executes Missions 1 and 2 of
`docs/roadmap/workstation-handoff-2026-07-27e-what-are-we-serving.md`
from exact `origin/master`
`ff7c3ba4537be9f3b57b66572fd5d8ba727ad605` on topic branch
`codex/workstation-what-are-we-serving-2026-07-27e`.

The information, population, comparison, and stop contracts were frozen
before new measurement in
`scratch/workstation-research-output/what-are-we-serving-20260727e/predeclaration.md`,
SHA-256
`f576463a2b8497882fe48703929c3be7ef0e00b90cf6d653d474eba161bda2a4`.

## Executive verdict

Coverage is complete: all four probability fields are finite and in `[0,1]`
on all **206,745 frozen band rows**, with unit mass on all **18,791 valid
eleven-band simplexes**. The scored population is therefore not a
coverage-selected subset.

The historical `recorded_probability` control is closest to the incumbent
input at row and partition level, but it is not identical to any measured
lane. It underperforms the hypothetical replay-final reconstruction:

- binary-band Brier: `0.0736943` versus `0.0620561`, deficit `+0.0116381`;
- realized categorical Brier: `0.810483` versus `0.682558`, deficit
  `+0.127926`; and
- market-soft expected categorical Brier: `0.796027` versus `0.686331`,
  deficit `+0.109696`.

Recorded is worse than replay-final in all three named windows and in every
one of the 24 market-local hourly comparisons, in both categorical lanes.
It also has worse aggregate Brier than preblend and incumbent. Against the
accepted 124-case printed-floor proxy, recorded assigns more than `1e-9`
mass below the floor in 118 cases, compared with 108 for replay-final and
zero for preblend.

The defensible Mission 1 conclusion is:

**`RECORDED_CONTROL_UNDERPERFORMS_REPLAY_FINAL_ON_FROZEN_ROWS`.**

This is not proof that production served recorded, preblend, incumbent, or
replay-final. The frozen replay has no active-release binding and its
validation verdict is `BLOCK`. Replay-final is a hypothetical reconstruction,
so “production served the worse model” and “could have served” are not
supported claims.

Mission 2's framing fails before attribution. The accepted artifact predicts
native-F bands directly (`prediction_mode = band_binary`,
`family_unit = F`); it is not a continuous Celsius distribution converted
and binned into Fahrenheit bands. Toronto is absent from the accepted scored
vector, and exact pre-round continuous realized maxima do not survive in the
frozen corpus. A conversion-flip count and same-lane Toronto control therefore
are not measurable without changing the frozen question.

The Mission 2 conclusion is:

**`CONTINUOUS_CONVERSION_HYPOTHESIS_NOT_APPLICABLE_OR_NOT_MEASURABLE`.**

No boundary score, conversion count disguised as zero, or causal conversion
claim was produced.

## Coverage before scores

The standalone harness independently streamed the 156,464,494-byte candidate
vector with decimal parsing before using the accepted scoring helpers.

| Scope | Cells | Rows | Recorded usable | Common four-lane usable |
| :--- | ---: | ---: | ---: | ---: |
| Pooled | 1 | 206,745 | 206,745 (100%) | 206,745 (100%) |
| Markets | 11 | 206,745 | 100% in every cell | 100% in every cell |
| Target dates | 12 | 206,745 | 100% in every cell | 100% in every cell |
| Market-local hours | 24 | 206,745 | 100% in every cell | 100% in every cell |

The accepted population checks also revalidated:

| Population contract | Count |
| :--- | ---: |
| Band rows | 206,745 |
| Composite `(market, target date, snapshot)` keys | 18,793 |
| Valid eleven-band simplex partitions / rows | 18,791 / 206,701 |
| Known same-second collision keys / rows | 2 / 44 |
| Market-days | 129 |
| US Fahrenheit markets | 11 |
| Target dates | 12 |
| Earliest target-day market-local hour cells | 2,962 |
| Predawn 03-05 partitions / rows | 354 / 3,894 |
| Primary 09-14 partitions / rows | 771 / 8,481 |
| Evening 20-23 partitions / rows | 481 / 5,291 |
| Exact hour-20 floor cases / rows | 124 / 1,364 |

The two accepted collision keys remain the known Austin and Dallas
same-second duplicates. The binary CORP bridge includes their 44 rows.
Categorical-simplex metrics exclude the two keys after full-population time
selection and do not replace them.

Captured instants are converted through the hash-pinned market timezone.
`cutoff_hour` is not used as the analysis clock.

## What each lane means

| Frozen field | Meaning here |
| :--- | :--- |
| `candidate_preblend_probability` | Candidate captured before reconstructed current-blend processing |
| `probability` | Hypothetical replay-final reconstruction; validation remained `BLOCK` |
| `current_probability` | Incumbent input to the reconstructed blend |
| `recorded_probability` | Historical recorded-output control; not an active-release binding |
| `market_yes` | Raw Gamma market-probability proxy; not executable CLOB pricing |
| `outcome` | Settled one-hot band label |

The label “recorded-output control” is intentionally narrower than “served.”
The frozen artifacts do not prove which active release, producer, config, or
pointer emitted those values in production.

## Which lane does recorded resemble?

Recorded is closest to incumbent by every predeclared distance statistic.

| Comparator to recorded | Row numeric exact | Row MAD | Whole-partition exact | Mean L1 | Mean TV | P95 TV |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Preblend | 0 / 206,745 (0%) | 0.078558 | 0 / 18,791 | 0.864080 | 0.432040 | 0.953267 |
| Replay-final | 0 / 206,745 (0%) | 0.044209 | 0 / 18,791 | 0.486197 | 0.243098 | 0.693027 |
| Incumbent | 9,115 / 206,745 (4.41%) | **0.027592** | 0 / 18,791 | **0.303380** | **0.151690** | **0.605407** |

Raw-text equality agrees with parsed numeric equality: 9,115 incumbent rows
and zero rows for preblend or replay-final. Resemblance does not establish
producer lineage or release binding.

## Four-lane pooled score

Lower scores are better. The realized binary CORP lane includes all 206,745
rows. The categorical and market-soft lanes use the 18,791 valid simplexes.

| Forecast | Binary Brier | Binary REL | Binary RES | Realized categorical | Market-soft expected | Soft REL | Soft RES |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Preblend | 0.065607 | 0.007619 | 0.024657 | 0.721610 | 0.735700 | 0.075640 | 0.249031 |
| Replay-final | **0.062056** | **0.004370** | **0.024958** | **0.682558** | **0.686331** | **0.030640** | **0.253400** |
| Incumbent | 0.070310 | 0.006329 | 0.018663 | 0.773332 | 0.770845 | 0.056123 | 0.194369 |
| Recorded output | 0.073694 | 0.007778 | 0.016728 | 0.810483 | 0.796027 | 0.066378 | 0.179442 |

Recorded has both higher reliability error and lower resolution than
replay-final in both decompositions. It is also worse than incumbent despite
being closest to incumbent at row level.

For context only, the raw market proxy scores `0.0373686` binary Brier and
`0.411113` realized categorical Brier (`0.410128` after partition
normalization). That proxy is not a fillable or executable price.

## Named windows and all hours

Recorded loses to replay-final in every named window.

The bound `score_summary.csv` and analysis JSON retain all four forecasts,
the market baseline, and their binary CORP and market-soft decompositions for
every named cut. The compact tables below show the decision contrast requested
by the handoff; they do not replace those full machine-readable results.

| Market-local cut | Partitions | Replay-final categorical | Recorded categorical | Recorded deficit | Replay-final soft | Recorded soft | Recorded deficit |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Predawn 03-05 | 354 | 0.826553 | 0.928942 | +0.102390 | 0.808540 | 0.874570 | +0.066030 |
| Primary 09-14 | 771 | 0.735572 | 0.810405 | +0.074832 | 0.742905 | 0.800745 | +0.057840 |
| Evening 20-23 | 481 | 0.499770 | 0.735157 | +0.235387 | 0.505261 | 0.738789 | +0.233527 |

The hourly deficits are positive in **24/24** realized-categorical comparisons
and **24/24** market-soft comparisons:

| Hour | Partitions | Recorded minus replay-final categorical | Recorded minus replay-final soft |
| ---: | ---: | ---: | ---: |
| 00 | 118 | +0.112218 | +0.077846 |
| 01 | 118 | +0.112942 | +0.071756 |
| 02 | 118 | +0.112249 | +0.070431 |
| 03 | 118 | +0.114354 | +0.073489 |
| 04 | 118 | +0.099510 | +0.063300 |
| 05 | 118 | +0.093306 | +0.061301 |
| 06 | 118 | +0.088223 | +0.056173 |
| 07 | 121 | +0.107365 | +0.066853 |
| 08 | 122 | +0.049161 | +0.061066 |
| 09 | 126 | +0.066834 | +0.064890 |
| 10 | 129 | +0.080549 | +0.057565 |
| 11 | 129 | +0.075486 | +0.046699 |
| 12 | 129 | +0.042088 | +0.027231 |
| 13 | 129 | +0.067947 | +0.049836 |
| 14 | 129 | +0.115903 | +0.100983 |
| 15 | 129 | +0.153862 | +0.136740 |
| 16 | 129 | +0.204010 | +0.201613 |
| 17 | 129 | +0.190002 | +0.175078 |
| 18 | 128 | +0.223703 | +0.202387 |
| 19 | 126 | +0.161702 | +0.157745 |
| 20 | 124 | +0.195103 | +0.193290 |
| 21 | 121 | +0.237252 | +0.235354 |
| 22 | 118 | +0.262517 | +0.260590 |
| 23 | 118 | +0.248676 | +0.246873 |

The smallest deficit is at hour 12 and the largest at hour 22 in both lanes.
This is a retrospective frozen-panel result, not forward performance or
serving authority.

## Printed-floor comparison

The audit exact-joined all 124 accepted hour-20 cases. Printed floor is
`ROUND_HALF_UP(high_so_far)`. An equality band is below-floor only when its
inclusive upper bound is below the floor; an `lte` band is below-floor when
its cap is below the floor; `gte` is never below-floor.

| Forecast | Cases with mass greater than `1e-9` | Total below-floor mass | Mean | Median | P95 | Maximum |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| Preblend | 0 / 124 | 4.84e-13 | 3.90e-15 | 3.95e-15 | 7.96e-15 | 9.03e-15 |
| Replay-final | 108 / 124 | 12.504538 | 0.100843 | 0.048515 | 0.432415 | 0.495856 |
| Incumbent | 118 / 124 | 25.075771 | 0.202224 | 0.097030 | 0.864830 | 0.991712 |
| Recorded output | 118 / 124 | 24.538691 | 0.197893 | 0.100484 | 0.817277 | 0.997154 |

Recorded is close to incumbent on this diagnostic and materially worse than
replay-final. This is the accepted printed/code-effective floor proxy. It is
not newly established strict-readable WU authority, active serving proof, or
a release-bound physical-floor guarantee.

## Mission 2 - the proposed mechanism is not applicable

The predeclared applicability gates were evaluated before any boundary bucket
or score.

### 1. The accepted model does not use the proposed conversion path

The hash-pinned artifact declares:

- `prediction_mode = band_binary`;
- `family_unit = F`;
- `objective = binary_market_band_brier_source_reliability`; and
- schema `pooled_feature_band_hgb_v0.3`.

The exact replay source calls `predict_band_rows_for_bundle` for this mode and
normalizes direct band predictions. A distinct `continuous_density_f` branch
exists in the source but is not the accepted artifact's branch. Therefore the
premise “continuous Celsius distribution converted into Fahrenheit bands” is
false for the measured candidate.

### 2. The Toronto control is absent

The accepted vector contains 11 Fahrenheit markets, 129 market-days, and no
Toronto rows. The wider manifest contains 12 Toronto/Celsius market-days, but
there is no Toronto candidate/preblend/replay-final vector in the same lane.
Substituting a different artifact, corpus, or recorded-only control would
change the question and still confound city with unit.

### 3. Boundary distance and conversion flips are not observable

The manifest preserves already settled native-unit labels, not independent
pre-round continuous maxima. All 141 surviving settlement highs are integral:
the 129 Fahrenheit winners are equality bands; Toronto has 11 equality winners
and one `lte` winner. Under the market's half-unit payout edges, the surviving
labels collapse to a distance of `0.5` native units from the deciding edge.
That is a one-bucket tautology, not boundary attribution.

The existing `settlement_distance_bucket` field is band-row distance from the
settled winner and is outcome-derived. Reusing it as an ex-ante boundary
metric would leak the answer.

Because the pre-round value is absent, the number of labels that would flip
under floor, round, or nearest is **NOT MEASURABLE**. Applying alternate
rounding to the already rounded integers would manufacture a circular zero,
so no flip count is reported.

### 4. Reconciliation context does not establish authority

The frozen manifest admits 141/141 market-days: 109 through
`promotion_countable` and 32 through `quality_grade`. Its prose says the
promotion-countable records are settlement reconciled. However, its authority
summary is `{"unreported": 141}` and it does not freeze explicit
exchange-winner fields from which match, mismatch, and missing can be
independently rederived.

Accordingly:

- manifest admission assertion: `141 / 141`;
- direct exchange match / mismatch / missing counts: not reported;
- directly rederived authoritative reconciliation rate: not available; and
- authority status: unreported, not upgraded by this audit.

The handoff's recent “11 of 12 with one local missing” observation is not
substituted into this historical corpus.

## Leakage, identity, and verification

The bounded run made no vendor request, network call, full-book read, replay,
model fit, or `data/` analytic read. `data/` retained its deny-write ACL.
Fresh host admission at 17:16 ET recorded 45.33% committed memory, 58.96 GiB
free disk, no WeatherTrainingWindow/restore activity, and no
WeatherDataMirror/robocopy activity. Two unrelated Python processes in the
separate market-making repository were observed and left untouched.

The harness rehashed every frozen input before and after analysis. It reused
the exact accepted scoring implementation only after verifying that
implementation's hash. A separate validator does not import either harness;
it verifies output identities, population and coverage, row/partition
agreement, decomposition algebra, floor join, and terminal contracts.

| Evidence | SHA-256 |
| :--- | :--- |
| Predeclaration | `f576463a2b8497882fe48703929c3be7ef0e00b90cf6d653d474eba161bda2a4` |
| Host admission | `4e3e9c57838a405342b5668b1bff940da11d105954b60004edd047fb080c8e02` |
| Frozen candidate vector | `cf661e9fb396e95db4e98f2aa29fd32dda2fb9b992099e4d0d6fcfea89b68a4b` |
| Audit harness | `a32539704193dcac63f010c28edb7312cccbc5457cc0cde42f0d845d2d1a6fb9` |
| Separate validator | `7255c67c30ff9fc267838e45de5acae79115d6a42c32e540ba7896487edea990` |
| Analysis JSON | `48b5e83680a48850b7eef18689e1c574da18433dda92fde4ed13e6e3a6d36d93` |
| Analysis receipt | `4c95206f7465d1107b8ffc17cff9679e0e92457640fa95e093e1471056bf589f` |
| Verification receipt | `15315532ac214867dcd3bd09b4f95dbc7d2f6c4914ca931acdcf9cd3aa4f7337` |
| Independent full remeasurement receipt | `2f6978a115e15a0ed8a1239bc6f3aaa2ff4cc418099a418c490a56cd8f28f35c` |
| Full score-summary CSV | `4b054783afd33eb3d9ed0161f682fe7ac865049842448aa6a96d8ab4598cb7d2` |
| Accepted prior harness | `fcc3c6ac3a6b8b8334e3e8ded3a84e0092b55503efbe53da644415da444e7b09` |
| Accepted pooled-F artifact | `3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c` |
| Frozen promotion corpus | `128db63ec78c92a4126f886caec078dcab6786b47d0d65ad0aff10f5f1dc1dc5` |
| Exact replay source | `0531f5c8da0774c457bd89b0a06a3a1cd6ba0cbcaed8f455d3ee173c5f40be1a` |
| Exact scoring source | `80cbd830d3b070417c5cca5a2df99361eb9f1ef7009dfbdc96e16c97f7007d3b` |
| Exact hour-20 cases | `62098846077d58c89caf500488d9d24e6db207905804fe0584377bdf94de98c8` |

The standalone commands `self-test`, `analyze`, and `verify` all returned
`PASS`. Repository documentation audit and proportional report verification
also pass on the exact worktree.

## Limitations and NOT-DONE / NOT-PROVEN

- **NOT PROVEN:** active release, pointer, config, producer, or actual
  production-serving binding for `recorded_probability`.
- **NOT PROVEN:** replay-final was deployable; its accepted validation verdict
  remained `BLOCK`.
- **NOT PROVEN:** raw Gamma probabilities were executable or fillable CLOB
  prices.
- **NOT PROVEN:** the printed-floor proxy is new authoritative WU
  strict-readable proof.
- **NOT MEASURABLE:** continuous boundary attribution, alternative
  conversion-flip count, or same-lane Toronto control on the frozen scored
  vector.
- **NOT REDERIVED:** corpus-wide exchange match, mismatch, and missing counts,
  or exact training-label lineage.
- **NOT DONE:** model, blend, alpha, floor order, config, artifact, release,
  pointer, collector, scheduler, sizing, cap, trading, or serving changes.
- **NOT RUN:** Mission 3 / the unchanged scaled-MM `-28c` queue. Its authorized
  window is 01:00-08:30 ET with practical entry after 06:00 ET; this evening
  execution was outside that window. Its
  `NONTERMINAL_FULL_BOOK_HASHES_REQUIRED` gate remains unchanged.
- **NOT DONE:** PR, merge, or master push.

## Handback

Mission 1 closes with a measured negative for the recorded-output control:
it is closest to incumbent, but worse than replay-final on every pooled,
named-window, and hourly score requested. Mission 2 closes the proposed
conversion suspect **for this frozen direct-band artifact and corpus** on
applicability, not on a fabricated boundary estimate. No operational or
serving authority follows from either result.
