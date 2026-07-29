# Workstation concentrated-deficit anatomy - 2026-07-28

Status: **PASS - THE MARKET IS ABSOLUTELY SHARP IN THE CONCENTRATED
DENVER/DALLAS/AUSTIN 09-15 CELLS WHILE PREBLEND IS NOT. THE WEAKNESS IS
PERSISTENT WITH DAY-LEVEL SPIKES; ITS WORST ROWS ADD COOL-SIDE CENTERING
ERROR, NOT EXTRA SPREAD. RETAINED JULY INPUTS DO NOT IDENTIFY A UNIQUE
MECHANISM OR A FUNDABLE PREDICTOR CHANGE.**

This report executes
[`workstation-handoff-2026-07-28i-characterise-the-concentrated-deficit.md`](workstation-handoff-2026-07-28i-characterise-the-concentrated-deficit.md)
from exact `origin/master`
`c977fd141fdbeaaf6bd42a0af11a29d3c55f2b2e` on topic branch
`codex/workstation-who-breaks-floor-2026-07-27g`.

## Absolute resolution and uncertainty by cell

The discriminator is decisive: **the market is resolving these outcomes; we
are not merely both diffuse in intrinsically difficult cells.**

The fixed lead panel is Denver, Dallas, and Austin at market-local hours
09-15: 21 cells, 908 accepted POST snapshots, 9,988 binary band rows, and 21
market-days across July 3, 4, 5, 7, 8, 9, and 10. For each cell and lane I
fit exact empirical PAV/CORP on the same accepted rows. The deterministic
control match first took the four best non-lead cells at each hour by
market-minus-preblend resolution deficit, then assigned three distinct
controls to minimize absolute market-resolution distance.

`n` below is the accepted snapshot count. `R` is absolute binary resolution
and `U` is binary uncertainty. The same `U` appears on both lanes of every
cell.

| Lead cell | n | Preblend R | Market R | U | Matched cell | n | Preblend R | Market R | U |
| :--- | ---: | ---: | ---: | ---: | :--- | ---: | ---: | ---: | ---: |
| Austin 09:00 | 36 | 0.029566 | 0.050670 | 0.082645 | Atlanta 09:00 | 41 | 0.024514 | 0.031507 | 0.082645 |
| Dallas 09:00 | 36 | 0.020005 | 0.047783 | 0.082645 | Houston 09:00 | 35 | 0.017213 | 0.021753 | 0.082645 |
| Denver 09:00 | 49 | 0.006171 | 0.044910 | 0.082645 | Seattle 09:00 | 43 | 0.011183 | 0.017830 | 0.082645 |
| Austin 10:00 | 51 | 0.023167 | 0.048550 | 0.082645 | Atlanta 10:00 | 31 | 0.029147 | 0.028674 | 0.082645 |
| Dallas 10:00 | 52 | 0.023314 | 0.050326 | 0.082645 | Houston 10:00 | 51 | 0.010976 | 0.021080 | 0.082645 |
| Denver 10:00 | 44 | 0.012053 | 0.045511 | 0.082645 | NYC 10:00 | 28 | 0.010480 | 0.020736 | 0.082645 |
| Austin 11:00 | 52 | 0.026941 | 0.043130 | 0.082645 | Atlanta 11:00 | 41 | 0.041550 | 0.034878 | 0.082645 |
| Dallas 11:00 | 45 | 0.025342 | 0.050332 | 0.082645 | Houston 11:00 | 44 | 0.041464 | 0.019709 | 0.082645 |
| Denver 11:00 | 47 | 0.011401 | 0.050288 | 0.082645 | NYC 11:00 | 42 | 0.015833 | 0.021387 | 0.082645 |
| Austin 12:00 | 44 | 0.024613 | 0.039804 | 0.082645 | Chicago 12:00 | 44 | 0.028754 | 0.036876 | 0.082645 |
| Dallas 12:00 | 46 | 0.023813 | 0.056149 | 0.082645 | Houston 12:00 | 43 | 0.028147 | 0.032335 | 0.082645 |
| Denver 12:00 | 40 | 0.021247 | 0.052160 | 0.082645 | Miami 12:00 | 47 | 0.037190 | 0.037664 | 0.082645 |
| Austin 13:00 | 37 | 0.018460 | 0.043007 | 0.082645 | Chicago 13:00 | 36 | 0.041001 | 0.042150 | 0.082645 |
| Dallas 13:00 | 38 | 0.019493 | 0.061941 | 0.082645 | Houston 13:00 | 34 | 0.037865 | 0.034655 | 0.082645 |
| Denver 13:00 | 37 | 0.027067 | 0.058215 | 0.082645 | San Francisco 13:00 | 41 | 0.040635 | 0.041949 | 0.082645 |
| Austin 14:00 | 45 | 0.026349 | 0.043438 | 0.082645 | Houston 14:00 | 42 | 0.037091 | 0.031327 | 0.082645 |
| Dallas 14:00 | 38 | 0.030422 | 0.052837 | 0.082645 | NYC 14:00 | 33 | 0.040683 | 0.035867 | 0.082645 |
| Denver 14:00 | 44 | 0.040337 | 0.058213 | 0.082645 | San Francisco 14:00 | 43 | 0.072849 | 0.063507 | 0.082645 |
| Austin 15:00 | 40 | 0.042114 | 0.055743 | 0.082645 | Houston 15:00 | 44 | 0.053202 | 0.054148 | 0.082645 |
| Dallas 15:00 | 45 | 0.043258 | 0.059356 | 0.082645 | Los Angeles 15:00 | 47 | 0.082645 | 0.082645 | 0.082645 |
| Denver 15:00 | 42 | 0.049828 | 0.062583 | 0.082645 | San Francisco 15:00 | 51 | 0.081117 | 0.081308 | 0.082645 |

The market has higher absolute resolution in **all 21 lead cells**. All 147
paired leave-one-date refits retain that sign; the smallest refit
market-minus-preblend resolution is `0.001885935`.

The panel-level market-stratified PAV estimates make the magnitude clearer:

| Panel and lane | Partitions | Binary BS | REL | RES | RES / U | Effective bands | Top probability |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Lead preblend | 908 | 0.066830497 | 0.004672366 | **0.020486497** | 24.79% | 4.455812 | 0.426264 |
| Lead market | 908 | **0.040952355** | 0.005061596 | **0.046753869** | 56.57% | 2.892498 | 0.590760 |
| Matched preblend | 861 | **0.056149739** | 0.006045622 | 0.032540512 | 39.37% | 4.102596 | 0.479065 |
| Matched market | 861 | 0.057784852 | 0.011383222 | 0.036242998 | 43.85% | 2.803455 | 0.614482 |

The absolute resolution gap is `0.026267371` in the lead panel versus only
`0.003702487` in the matched controls. The result is not a snapshot-count
weighting artifact: equal-cell means give lead preblend/market resolution
`0.025950515 / 0.051187843`, a `0.025237327` gap, versus
`0.037311358 / 0.037713482`, a `0.000402124` matched gap.

The uncertainty request has an important limitation. With one winning band
among eleven, accepted binary uncertainty is mechanically
`10 / 121 = 0.082644628` in every cell. It is a design constant, not a
measure of meteorological difficulty, so it cannot perform the intended
intrinsic-difficulty separation. Date-balanced categorical outcome variety
is `0.612245` for Austin and Denver and `0.775510` for Dallas, but only seven
dates support each estimate. The stronger evidence against irreducibility is
the market itself: it resolves 56.57% of `U` in the lead cells, more than its
43.85% in the matched panel, while preblend falls in the other direction.

The matched controls were selected on these realized scores and are
descriptive, not held out or causal. That limitation does not affect the
within-lead fact that every cell and every date-delete refit has positive
market-minus-preblend resolution.

## What distinguishes the bad rows

### Persistent weakness with concentrated peaks

The fixed global worst-decile label identifies 470 of the 908 lead
partitions. Every one of the 21 lead market-days has at least one such row.
Across individual market-hour cells, worst cases occur on 2-7 of the 7
dates; Austin 15:00, Dallas 15:00, Denver 09:00, and Denver 14:00 contain a
worst case on every date.

The concentration is real but not a few pathological days:

- top one / three / five market-day shares are
  `10.64% / 27.45% / 43.19%`;
- market-day HHI is `0.063341`, versus `1 / 21 = 0.047619` under equal
  shares; and
- all 21 market-days contribute, while the five largest account for less
  than half.

| Market-day | Worst / partitions | Worst rate | Share of 470 | Mean resolution deficit |
| :--- | ---: | ---: | ---: | ---: |
| Denver, July 5 | 50 / 52 | 96.15% | 10.64% | 0.055990 |
| Dallas, July 9 | 40 / 42 | 95.24% | 8.51% | 0.048556 |
| Denver, July 10 | 39 / 41 | 95.12% | 8.30% | 0.050474 |
| Dallas, July 10 | 37 / 40 | 92.50% | 7.87% | 0.055943 |
| Denver, July 7 | 37 / 43 | 86.05% | 7.87% | 0.061222 |

### Centering, spread, and who changes

Center errors and spread below are in ordinal band-index units, so they are
not converted mechanically to Fahrenheit across open tail bands.

| Cohort and lane | n | Signed center error | Absolute center error | Spread | Binary BS |
| :--- | ---: | ---: | ---: | ---: | ---: |
| All lead, preblend | 908 | **-0.641** | 0.952 | **1.485** | 0.066830 |
| All lead, market | 908 | +0.018 | **0.406** | **0.777** | **0.040952** |
| Lead worst, preblend | 470 | **-0.784** | 1.030 | 1.463 | 0.066874 |
| Lead worst, market | 470 | -0.045 | **0.317** | **0.731** | **0.031096** |
| Lead nonworst, preblend | 438 | -0.489 | 0.868 | 1.509 | 0.066783 |
| Lead nonworst, market | 438 | +0.086 | 0.502 | 0.827 | 0.051529 |

Across the whole lead panel, preblend is both too cool and too broad relative
to the market. Within the lead panel, however, the worst rows are **not more
diffuse** than the nonworst rows: spread is slightly lower
(`1.463` versus `1.509`). Their distinguishing preblend error is cooler
centering (`-0.784` versus `-0.489`), also visible in the retained point-high
error (`-0.772 F` versus `-0.471 F`).

The sharper description is that the market changes much more than preblend.
Preblend binary Brier is almost identical in worst and nonworst rows
(`0.066874` versus `0.066783`), whereas market Brier improves from
`0.051529` to `0.031096`. The deficit rank is therefore finding rows where
the market becomes especially informative while preblend remains weak, not
a separate population of catastrophic preblend scores.

### Retained weather and forecast contrast

Raw snapshot weighting initially suggests a coherent hot/dry/clear regime:
the largest worst-minus-nonworst standardized differences include lower
next-three-hour CAPE (`-0.893`), lower remaining CAPE (`-0.869`), lower
low-cloud maximum (`-0.743`), higher 925 hPa temperature (`+0.731`), higher
850 hPa temperature (`+0.704`), and lower shallow soil moisture (`-0.634`).

That pattern is substantially market-day composition. With each market-day
weighted equally, the thermal contrasts are at most `|0.051|`, shallow soil
moisture is `-0.002`, VPD is `-0.044`, and raw low-cloud maximum collapses
to `-0.026`. Point-high error also reverses direction under this weighting.

The largest date-balanced survivors are lower ET0 (`-0.513`), lower
remaining solar (`-0.505`), lower next-three-hour solar (`-0.458`), a
smaller NWS-grid versus forecast-high gap (`-0.425`), less forecast gap
(`-0.376`), an earlier remaining peak (`-0.367`), lower remaining direct
radiation (`-0.357`), and less remaining rise (`-0.339`). These are
descriptive ranks over only seven dates, not a unique state signature:
ET0 and remaining-solar signs are positive on two dates and negative on
five, and the fields overlap physically and temporally.

Lead-versus-matched contrasts remain large - for example VPD `+2.436` SMD,
925 hPa temperature `+2.124`, and low cloud `-1.058` - but those primarily
describe continental hot markets versus the matched geographic mix. They do
not separate the lead panel's worst from nonworst rows after date balancing.

Several requested distinctions are unavailable:

- there is no retained current-day observed minimum or full intraday range;
- `rise_from_7am`, observed wind/gust, and `cloud_group` / `wind_group` have
  zero lead coverage;
- `warming_rate_2h`, `hours_at_peak`, and onshore-flow proxies are constant;
  and
- the accepted nearest-band-edge distance is exactly zero in all 908 rows,
  so the band-edge comparison is
  **`UNIDENTIFIABLE_NO_VARIATION`** and no substitute was used.

Forecast solar, cloud, CAPE, and gust fields are retained and varying; the
coverage limitation applies to the named observed/path fields above.

## Consistency with the June predictor gaps

The blanket "absent predictor" description in
[`high-temperature-projection-research-audit-2026-06-20.md`](high-temperature-projection-research-audit-2026-06-20.md)
is partly stale against the serialized pooled-F artifact and July retained
rows. The artifact exposes 278 unique feature names and was parsed with
standard-library `pickletools` without executing it.

| June family | July currency and coverage | Bad-versus-good result | Verdict |
| :--- | :--- | :--- | :--- |
| 850 hPa thermal state / mixing depth | **Partly stale.** Forecast 850/925 hPa temperature and lapse/geopotential proxies are populated and varying. Direct mixing/PBL height is absent; seven ECCC/reanalysis pressure-level fields are unpopulated. | All populated thermal proxies have date-balanced `|SMD| <= 0.051`. | **`CORPUS_CANNOT_DISTINGUISH`** direct mixing depth; observed thermal state does not explain the split. |
| Root-zone / antecedent land surface | **Partly stale.** Shallow soil, VPD, and ET0 fields are populated; explicit root-zone state is absent and 16 reanalysis/antecedent fields are unpopulated. | Shallow moisture `-0.002`, VPD `-0.044`, soil temperature `-0.115`; ET0 `-0.513` but only two positive versus five negative date contrasts. | **`CORPUS_CANNOT_DISTINGUISH`** root-zone state; no root-zone mechanism is established. |
| Forecast shortwave / peak cloud | **Stale.** Sixteen forecast/NWS solar, direct/diffuse radiation, and cloud fields are populated and varying; five ECCC/reanalysis fields are unpopulated. | Remaining solar `-0.505` and direct radiation `-0.357` after date balancing. | **`PRESENT_WITH_DESCRIPTIVE_ASSOCIATION_ONLY`**; this is not an absent-predictor case or a unique mechanism. |
| Smoke / AOD | **Stale.** All seven AOD, PM, dust, and smoke fields are populated and varying. | Every date-balanced `|SMD|` is below `0.091`. | **`PRESENT_NOT_EXPLANATORY_IN_THIS_CORPUS`**. |

The combined terminal assessment is
**`NO_UNIQUE_SIZEABLE_TEMPORALLY_BROAD_MECHANISM_OR_FUNDABLE_CHANGE_ESTABLISHED`**.
The corpus leaves direct mixing depth and root-zone state unmeasured, but it
does not show that either is the missing information. Shortwave has a modest
descriptive contrast but is already present. Smoke/AOD is present and does
not distinguish bad from good rows. No predictor addition or retraining is
proposed.

## Execution and independent verification

The predeclaration was frozen at `2026-07-28T22:46:35-04:00`, after
metadata/schema/availability inspection but before any new absolute cell
score, control match, feature contrast, or gap-consistency statistic. Its
SHA-256 is
`7b157c7cf35569613c4c0449f4f4d653e85d1c49d012957b83fa8bd97ec56efa`.

The single measurement write root was:

`C:\Users\Michael\Documents\github\weather\scratch\workstation-research-output\deficit-anatomy-20260728i-c977fd14`

Final admission at 23:08 ET recorded 35.20% committed memory, a valid
66,951,397,376-byte commit limit, 66,664,189,952 bytes free on `C:`, no
visible copy/compression process, and an execution time outside the protected
01:00-08:30 window. `data/` was read only.

Three independent implementations corroborate the result:

- Mission 1 rebuilt the absolute PAV decomposition and deterministic match;
  all 21 cells and all 147 date-delete refits agree on the resolution sign.
- Mission 2 independently joined 1,769 lead-plus-matched rows across 76
  unchanged retained files with zero missing/duplicate exact joins. Ten
  headline values and 320 overlapping feature contrasts reconcile with
  maximum numeric residual `4.44e-16`.
- Mission 3 independently parsed the artifact, rehashed all 76 selected
  retained files before and after, and reached the no-fundable-change
  verdict above.

An initially overbroad independent Mission 3 scan stopped on an Austin
retained `snapshot_id` collision. Binding the exact candidate capture instant
selected the intended row; the collision is absent from the accepted/joined
population and changes no estimate. The primary verifier was also tightened
from label/token checks to exact Mission 1 and 2 numeric reconciliation plus
Mission 3 semantic reconciliation. The 01:00-08:30 guard was corrected to
exclude hour 00. After those harness changes, the full
`self-test -> admit -> analyze -> verify` chain was rerun.

The final primary terminal is
**`PASS_CONCENTRATED_DEFICIT_CHARACTERISED_NO_MECHANISM_PROMOTED`** and
grants no authority.

## Evidence

| Evidence | Bytes | SHA-256 |
| :--- | ---: | :--- |
| Predeclaration | 10,748 | `7b157c7cf35569613c4c0449f4f4d653e85d1c49d012957b83fa8bd97ec56efa` |
| Final primary harness | 99,677 | `174cedbd74295a7ff810719aafbc43fc2ff9e8c6350e8e60d0c8c2141fd21fb7` |
| Final self-test receipt | 910 | `213b27b6e57ff0d4ec57ef6b3b489285c17dd4f2235c2c7343de3f22b5617da8` |
| Final host admission | 4,935 | `6efa85df59c4ebed4fbd7b44b00d2647fe1116291f54636d1990a326a784aa81` |
| Primary analysis | 38,723 | `56ee620f97a48ba689d8c1473f8534ea72fac3372507ed87c562d7cda05c33b0` |
| Cell absolute resolution | 61,087 | `72f8d1865d7c8edc5b4a689a9b1452532acb19796af20ac7b1638f043b4965c9` |
| Matched cells | 3,968 | `a61149eb29cf9bcf8fb0926f49294e3c1b1c7cd966f856cb5e25934199c53f40` |
| Panel absolute resolution | 4,145 | `6f382d8c2bafbb9460e6721568d5e5bd7699d8733b7315c6e7b403a664ef35b7` |
| Market-day concentration | 7,089 | `e3b716d49e7f04e93a9baf67d3c9bce02e79706c7c734d06b6034f22f0e533e9` |
| Feature contrasts | 98,876 | `af0dbe3e7f169c387295bdf29923bdb3e72ea7f71d0d49405a09a5543020b9d6` |
| Data-gap assessment | 20,283 | `e7955aad8a47628151e48b7bb794dee1acff7219a7a0bf08d306ae23743e0cd4` |
| Independent Mission 1 receipt | 21,189 | `01d9f10f2deb8384c84bd535536334a215e466c7d009e8dc4992e1bec76ad76a` |
| Independent Mission 2 receipt | 16,320 | `f54c076952241ea90eea1512d0fb0817f44cbbc81b2f5de7b21963b9d74ceee4` |
| Independent Mission 3 receipt | 344,836 | `2887b330edc4b9b582ffdc23707e45b7ca7fae22750605387293c6d658b08f4c` |
| Final verification receipt | 2,459 | `061d8d826c20042a0e307c6679c8f88ac055f78374c47151d224780422592c72` |
| Final primary gate | 28,430 | `11c57ad416fd9116c76c4101292ead9db5b99039e81278f6750cc17c94ae43de` |
| Execution manifest | 9,594 | `c16653e1261944f3f3fed13463f6a26f4f16bd03f149250efe38de79dba863bb` |

All fixed inputs were rehashed before and after measurement and again during
verification. Exact paths, sizes, and hashes are bound in the predeclaration,
analysis, independent receipts, and execution manifest.

## Handback and next queue

- **ANSWER:** the market is genuinely sharp in these cells. Lead market
  resolution is `0.046754` versus preblend `0.020486`; the matched gap is
  only `0.003702`.
- **DESCRIPTION:** the weakness is persistent across all 21 market-days but
  has concentrated peaks. Within lead rows it is cool-side centering, not
  additional spread, and is especially characterized by the market becoming
  much better while preblend Brier remains flat.
- **MECHANISM:** no date-balanced, unique retained-weather signature survives.
  Lower remaining solar/ET0 is descriptive, but does not identify a missing
  predictor.
- **DATA-GAP CURRENCY:** the June blanket absence claim is stale for forecast
  850 hPa, shallow-soil, shortwave/cloud, and smoke/AOD fields. Direct mixing
  depth and root-zone state remain unobserved, so this corpus cannot
  distinguish them.
- **NOT DONE:** no causal mechanism test, predictor addition, retraining,
  deployment rule, seasonality claim, vendor/network/full-book access, or
  Missions 3+ of `-28c`.
- **NOT CHANGED:** model, blend, alpha, predictor set, config, artifacts,
  serving, release, pointers, collectors, schedulers, sizing, promotion, or
  trading state.
- **NOT APPLIED / DELETED / COMPRESSED:** any real data.

Missions 3+ of `-28c` remain queued for the next 01:00-08:30 window exactly
as requested.
