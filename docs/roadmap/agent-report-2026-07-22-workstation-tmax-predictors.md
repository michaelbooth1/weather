# Agent Report - 2026-07-22 Workstation Tmax Predictor Research

## Outcome

All four priority predictor lines were taken through a leakage-safe historical
acquisition and terminal-holdout evaluation. Historical support was ultimately
available from free, explicit-issue archives; availability was not the terminal
blocker. Skill was.

**No predictor earns a collector, model, serving, promotion, or live-trading
change.** Open-Meteo Previous Runs radiation is the only family with a favorable
primary holdout point estimate, but its predeclared MAE interval crosses zero.
It may be checked once on a genuinely new independent season, without further
tuning. CFSv2 850 hPa temperature, CFSv2 top-layer soil, HRRR AOTK/smoke mass,
and exact CFSv2 radiation all stop on the current specification. The exact
CFSv2 radiation result is a clear holdout regression.

Negative deltas favor the predictor arm. The intervals in this table are each
family's original predeclared fleet-date-clustered primary intervals.

| Provider / family | Acquired support | Holdout | MAE delta C (95% CI) | RMSE delta C (95% CI) | Better / worse fleet dates | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Open-Meteo Previous Runs radiation | 147 dates / 1,742 market-dates | 30 / 338 | -0.0391 `[-0.0792,+0.0019]` | -0.0428 `[-0.0788,-0.0065]` | 22 / 8 | **NEW-SEASON ONLY**; primary inconclusive |
| CFSv2 850 hPa temperature | 206 / 2,472 | 42 / 504 | +0.0348 `[-0.0145,+0.0852]` | +0.0270 `[-0.0242,+0.0795]` | 18 / 24 | **STOP** |
| CFSv2 0-0.1 m soil temperature/moisture | 206 / 2,472 | 42 / 504 | +0.0477 `[-0.0008,+0.0965]` | +0.0178 `[-0.0427,+0.0811]` | 13 / 29 | **STOP** |
| HRRR AOTK + smoke mass density | 303 dates / 3,614 joined market-dates | 61 / 710 | +0.0009 `[-0.0049,+0.0063]` | +0.0004 `[-0.0048,+0.0055]` | 34 / 27 | **STOP** |
| CFSv2 exact radiation/cloud | 206 / 2,472 | 42 / 504 | +0.0709 `[+0.0194,+0.1171]` | +0.0679 `[+0.0132,+0.1207]` | 14 / 28 | **STOP**; clear regression |

The post-hoc program audit used 200,000 permutation-invariant whole-fleet-date
sign-flip draws per family and Holm family-wise correction over these five
tested families. It produced zero rejections. Different providers and issue
times are useful source-contract sensitivities, but they reuse outcomes and
overlap dates; they are not independent confirmation samples.

## Provenance and isolation

Phase 0 had already reproduced the production-recorded replay summary at all
847 numeric leaves with maximum absolute difference `0.0`, and verified all
309 entries in the current promotion-corpus manifest. See
`docs/roadmap/agent-report-2026-07-22-workstation-phase0-parity.md`.

This workstream used the same explicitly supplied repository-local, ignored
`data/` mirror, read only. The exact resolved runtime root remains recorded in
the acquisition manifests; this durable report keeps paths
repository-relative. The mirror and its major subtrees were created on
2026-07-21 at 14:07 ET; the newest snapshot pass was observed on 2026-07-22
around 04:32 ET with source-content mtimes through 05:00 ET, and the
`data/backtest` subtree mtime was 2026-07-22 01:00 ET. No copy receipt binds
those files to a named upstream batch, so no stronger batch identity is
claimed.

The seasonal predictor corpus contains 303 fleet target dates from 2021-2026,
12 built-in markets, 3,614 baseline/settlement-matched market-dates, 12
forecast-history inputs, and 12 WU settlement-label inputs. Acquisition
manifests bind the source hashes actually read. Raw responses, range files,
derived rows, models, evaluations, and reports were written only below
`scratch/workstation-research-output/workstream_c`.

No production host, paid provider, scheduler, release pointer, serving path,
promotion path, or trading surface was touched. The research CLIs require an
existing directory as the explicit read-only data root and reject direct,
relative, symlink, or Windows junction output paths that resolve into it.
Every research file is published from an unpredictable, exclusively created
same-directory temporary file, so replacing a pre-existing destination
hardlink severs that link without writing through to the mirrored input; the
same adversarial contract is tested under concurrent writers. Distinct output
roles cannot collide. Post-hoc tools explicitly reject overwriting or
hardlink-aliasing a sealed evaluation input, and the CFSv2 radiation design
cannot overwrite or alias its sealed upstream soil contract.

## Evidence boundary before acquisition

The local `forecast_history` mirror contained 747,648 hourly rows:

- 614,880 had the admissible `fixed_lead_day_offset` issue basis;
- 132,768 had the forbidden `stitched_continuous_archive` basis; and
- 3,614 explicit-issue market-dates joined to WU settlement labels over 303
  fleet dates.

The admissible rows had none of the requested pressure, soil, radiation, AOD,
or smoke values. Some rich fields existed only in stitched rows, where later
forecast revisions could leak into a target-date claim. Those rows were
counted diagnostically and never scored. This established why a bounded,
explicit-issue backfill was necessary.

## Common evaluation contract

Every family used the same evaluator and direction of comparison:

- target: configured WU daily settlement high minus the baseline forecast
  high, physically normalized to Celsius;
- baseline: latest admissible explicit issue strictly before 00:00 local on
  the target date;
- variant: baseline plus a family-only residual Ridge model, alpha `1.0`, no
  intercept, with standardization fit on training rows only;
- temporal design: four expanding chronological folds followed by an untouched
  terminal 20% holdout selected from predictor-supported fleet dates without
  outcomes;
- inference: paired errors clustered and resampled as whole fleet dates, so
  within-date city dependence is preserved; and
- acceptance: a predictor advances only if its holdout MAE point and full
  predeclared interval favor the variant. Negative, adverse, or inconclusive
  evidence does not earn a collector.

The original family-specific bootstrap was preserved exactly. Pressure and
Open-Meteo radiation used 20,000 primary draws; soil, HRRR, and exact CFSv2
radiation used 2,000. A sealed-prediction, no-refit sensitivity then recomputed
all five at 20,000 draws and checked alternative weighting/completeness
estimands. It did not reread raw outcomes or change any model, field, issue,
horizon, date, or market choice.

## Open-Meteo Previous Runs radiation

### Acquisition contract

The bounded free backfill made 72 requests (12 cities by six seasonal date
ranges), with zero request errors. Each request records its URL, parameters,
retrieval time, response SHA-256, and raw-cache path. It produced 86,736 hourly
rows; the requested radiation/cloud fields were populated for 2024-2026 and
gave 1,742 supported market-dates across 147 fleet dates. Seventy-two raw and
48 source/derived hashes were rechecked with zero mismatches.

The feature family was frozen as shortwave sum/max, direct sum, diffuse sum,
direct fraction, and cloud mean/max. The provider's `previous_day1` contract is
a fixed 24-hour lead. It supports a leakage-safe fixed-lead comparison, but it
does not prove exact per-model-run publication latency.

### Result and follow-up

On the 30-date, 338-market-date holdout, baseline MAE was `1.3417 C` and
variant MAE `1.3027 C`: delta `-0.0391 C`, 95% CI
`[-0.0792,+0.0019]`. RMSE delta was `-0.0428 C`, CI
`[-0.0788,-0.0065]`, and 22/30 daily MAE deltas improved. The primary MAE
criterion remains inconclusive.

The 20,000-draw no-refit check reproduced the result. Equal fleet-date
weighting gave MAE delta `-0.0709 C`, CI `[-0.1536,-0.0089]`, but that is a
post-hoc alternative estimand. Restricting to the 28 exactly complete dates
(336 market-dates) gave `-0.0359 C`, CI `[-0.0759,+0.0060]`, again
inconclusive. The permitted follow-up is therefore **one frozen evaluation on
an independent future season**. Do not retune against the 2026 holdout and do
not build a collector now.

## NOAA CFSv2 explicit-issue archive

### Shared frozen archive rule

CFSv2 used the free NCEI operational nine-month forecast time-series archive.
The source rule was target minus two UTC calendar days at 18Z, member `01`, a
12-hour publication buffer, and six-hour steps f36 through f60 covering each
market's local target date. Missing fixed-rule issues were not replaced by a
different cycle or member.

The exact fixed rule existed on 206 of 303 target dates. The other 97 returned
404 under that rule. Complete dates by year were `48/52`, `48/52`, `26/52`,
`52/52`, `21/52`, and `11/43` for 2021-2026. Every available issue supported
all 12 markets, or 2,472 market-dates. This incomplete but broad coverage was
adequate for a predeclared chronological holdout.

### 850 hPa temperature

The exact field was `t850` / TMP at 850 hPa. Four hundred twelve bounded
inventory/range requests acquired the 206 fixed-rule issues. The family used
850 hPa mean/max and surface-minus-850 contrast; it did not claim a tested 925
hPa term.

The untouched 42-date, 504-market-date holdout (2024-06-21 through
2026-05-20 on the sparse supported-date sequence) moved MAE from `1.3740` to
`1.4088 C`: delta `+0.0348 C`, 20,000-draw CI
`[-0.0145,+0.0852]`. RMSE delta was `+0.0270 C`, CI
`[-0.0242,+0.0795]`; only 18/42 dates improved. Equal-date and exact-12-market
sensitivities leave the adverse point unchanged. **STOP.** The negative 850
hPa result does not justify broadening this acquisition into a 925 hPa/mixing
collector.

### Top-layer soil

An outcome-blind availability pass froze exact `soilt1` TMP and `soilm1`
SOILW, both for the `0-0.1 m below ground` layer, on the same 206-date CFSv2
cohort. The legacy evaluator adapter columns have older depth-like names; they
carry this exact 0-0.1 m layer and must not be interpreted as literal CFSv2
0 cm or 0-1 cm fields. The 824 inventory/range requests completed with zero
decode errors, and all 848 acquired plus mirrored source files passed hash
reverification.

Development CV looked favorable: MAE delta `-0.0609 C`, CI
`[-0.0970,-0.0237]`. The terminal holdout reversed it: MAE moved from
`1.3740` to `1.4217 C`, delta `+0.0477 C`, primary CI
`[-0.0008,+0.0965]`; RMSE delta was `+0.0178 C`, CI
`[-0.0427,+0.0811]`, and only 13/42 dates improved. At 20,000 draws, MAE CI
was `[-0.0013,+0.0962]`; equal-date and complete-date estimates remained
adverse. This is a concrete example of tuning-window optimism. **STOP.**

### Exact CFSv2 radiation/cloud source-contract sensitivity

This follow-up tested whether the earlier Open-Meteo radiation point depended
on provider/issue semantics. The four exact CFSv2 fields and arithmetic were
frozen before outcome access:

- total shortwave = `dswsfc` (surface downward shortwave, W/m2);
- diffuse shortwave = `vddsf + nddsf`;
- direct shortwave = `max(total - diffuse, 0)`; and
- cloud = `tcdcclm` (total cloud cover, percent).

All four fields existed on every one of the 206 candidate CFSv2 dates. The
1,648 inventory/range requests produced 9,888 predictor samples and 2,472
market-dates with zero acquisition/decode errors. The outcome-blind scale and
lineage audit passed: 1,648 request files, 24 mirrored inputs, 9,888 paired
rows, zero hash/row mismatches. There were 190 direct-radiation clamps; the
minimum unclamped value was only `-1 W/m2`, consistent with integer rounding.
Median total/direct/diffuse radiation was `149/33/63 W/m2`; median cloud was
`36%`.

Development CV MAE was neutral (`+0.0002 C`), while secondary CV RMSE was
favorable (`-0.0720 C`). The terminal holdout was unambiguously adverse: MAE
delta `+0.0709 C`, CI `[+0.0194,+0.1171]`; RMSE delta `+0.0679 C`, CI
`[+0.0132,+0.1207]`; 14/42 dates improved. The 20,000-draw, equal-date, and
exact-complete sensitivities all retained wholly adverse MAE and RMSE
intervals. **STOP.** Because this source shares outcomes/dates with other CFSv2
families, it is source-contract sensitivity evidence, not an independent
outcome confirmation.

## NOAA HRRR AOD and smoke mass

### Frozen contract and unit audit

HRRR used target minus one UTC calendar day at 12Z, a two-hour availability
buffer, and forecast steps f18, f24, f30, f36, and f42. Four in-local-day
samples per market were derived from exact `AOTK` over the entire atmosphere
and `MASSDEN` at 8 m. AOTK used native mean/max. MASSDEN was normalized to
micrograms per cubic metre, transformed sample-wise with `log1p`, then reduced
to mean/max. MASSDEN is modeled smoke mass density, **not PM2.5**.

The official 2021-12-21 12Z units boundary was handled explicitly: numeric
values before the boundary were already micrograms/m3 and used unchanged;
values after it were kg/m3 and multiplied by `1e9`. A predictor-only integrity
audit, completed without parsing settlements, passed over 4,545 request files,
24 mirrored inputs, 14,456 paired predictor rows, and 3,614 joined
market-dates. It found zero hash/row mismatches and only a `0.187` log10 gap
between pre/post-boundary MASSDEN medians, not a billion-fold discontinuity.

Exact index availability was 303/303 dates. Acquisition used 1,515 index and
3,030 bounded GRIB range requests, with zero fetch/decode errors and maximum
nearest-grid distance `1.968 km`. The frozen design was written before outcome
access. A timing addendum fixed the later 20,000-draw no-refit sensitivity while
only the first ten predictor GRIB files existed and before any outcome join or
score.

### Result

The 61-date, 710-market-date terminal holdout spanned 2025-06-13 through
2026-06-23. MAE moved from `1.3261` to `1.3271 C`: delta `+0.0009 C`, primary
CI `[-0.0049,+0.0063]`. RMSE delta was `+0.0004 C`, CI
`[-0.0048,+0.0055]`; 34/61 dates improved. The 20,000-draw MAE CI was
`[-0.0046,+0.0063]`. Equal-date MAE was `+0.0008 C`, CI
`[-0.0046,+0.0061]`; restricting to 59 exact-12-market dates (708
market-dates) gave `+0.0009 C`, CI `[-0.0046,+0.0063]`. This is a tightly
estimated null/adverse point, not incremental skill. **STOP.**

## Weighting and completeness robustness

The following are post-hoc, no-refit MAE sensitivities from sealed per-date
error summaries. They cannot replace the original primary estimand.

| Family | 20k primary-style MAE delta (95% CI) | Equal-date MAE delta (95% CI) | Exact-12-date MAE delta (95% CI) |
| --- | ---: | ---: | ---: |
| Open-Meteo radiation | -0.0391 `[-0.0792,+0.0019]` | -0.0709 `[-0.1536,-0.0089]` | -0.0359 `[-0.0759,+0.0060]` (28 dates) |
| CFSv2 850 hPa | +0.0348 `[-0.0145,+0.0852]` | +0.0348 `[-0.0145,+0.0852]` | +0.0348 `[-0.0145,+0.0852]` (42) |
| CFSv2 soil | +0.0477 `[-0.0013,+0.0962]` | +0.0477 `[-0.0013,+0.0962]` | +0.0477 `[-0.0013,+0.0962]` (42) |
| HRRR AOTK/smoke | +0.0009 `[-0.0046,+0.0063]` | +0.0008 `[-0.0046,+0.0061]` | +0.0009 `[-0.0046,+0.0063]` (59) |
| CFSv2 radiation | +0.0709 `[+0.0200,+0.1200]` | +0.0709 `[+0.0200,+0.1200]` | +0.0709 `[+0.0200,+0.1200]` (42) |

Only the post-hoc equal-date Open-Meteo radiation interval excludes zero in the
favorable direction. The primary and exact-complete intervals do not, and this
alternative was examined after the primary result. It supports the
new-season-only verdict, not a collector.

## Program-level multiplicity audit

The uniform audit targets holdout market-date-weighted MAE. Each fleet date
contributes its total paired absolute-error difference; a two-sided wild-cluster
sign flip changes the sign of the whole date contribution, preserving all
within-date city dependence. Each family used 200,000 draws. Families are
sorted by label, and each RNG seed is derived as
`(base_seed + uint64_be(SHA256(label)[:8])) mod (2^63 - 1)`, so argument order
cannot change the results. Holm step-down correction controls family-wise error
without assuming independent tests.

| Family | MAE direction | Raw two-sided p | Holm-adjusted p | Reject at FWER 0.05 |
| --- | ---: | ---: | ---: | --- |
| CFSv2 exact radiation | +0.0709 adverse | 0.010215 | 0.051075 | no |
| CFSv2 top-layer soil | +0.0477 adverse | 0.065900 | 0.263599 | no |
| Open-Meteo Previous Runs radiation | -0.0391 favorable | 0.074240 | 0.263599 | no |
| CFSv2 850 hPa | +0.0348 adverse | 0.186999 | 0.373998 | no |
| HRRR AOTK + smoke mass | +0.0009 adverse | 0.747146 | 0.747146 | no |

There are zero Holm rejections. RMSE and sign tests remain secondary. The
smallest raw p-value belongs to a harmful CFSv2 radiation effect, so even an
unadjusted finding would not justify adoption.

## Artifact ledger

All paths are relative to the worktree. SHA-256 values bind the exact files
used for this report.

| Artifact | SHA-256 |
| --- | --- |
| `scratch/workstation-research-output/workstream_c/radiation_previous_runs/manifest.json` | `7f009695078aa96d46519b84fb52e8293eda7b8952862d5ed47a7ebfa0fa4f97` |
| `scratch/workstation-research-output/workstream_c/radiation_backfilled.json` | `78b7a4fa3f63a5cdbf62efea90ac90445bdbf2862ca183d845300953c0819f28` |
| `scratch/workstation-research-output/workstream_c/radiation_methodology_sensitivity_20000.json` | `b81812b0f2c46e3ed9c39783f1ae42b5c824cd1dfc6393d264ac9dd695b9992c` |
| `scratch/workstation-research-output/workstream_c/cfsv2_pressure_m2d18z/manifest.json` | `ab6977d430801c0f05d0a249d486ae7ef370fcc91ba43117b27e664b433ce953` |
| `scratch/workstation-research-output/workstream_c/cfsv2_pressure_m2d18z/pressure850_evaluation.json` | `7f91d614af24f3b245b51a5ae81f04a7d56124f2eba6a2d57354d83a255cc14a` |
| `scratch/workstation-research-output/workstream_c/cfsv2_pressure_m2d18z/methodology_sensitivity_20000.json` | `2bf9e18efb378d75d3b4c9c1424e835c94da8e81cb2011c3aa2d5697728343c1` |
| `scratch/workstation-research-output/workstream_c/cfsv2_soil_m2d18z/availability_contract.json` | `36f82ae022759d37efd9f2b86ff360b5f226de5647d2db793d41cd4fe6dc8cd9` |
| `scratch/workstation-research-output/workstream_c/cfsv2_soil_m2d18z/manifest.json` | `81fced54d6b58602753841855edd6f6436f8741fbf0811617b6ce2262ca6bfa0` |
| `scratch/workstation-research-output/workstream_c/cfsv2_soil_m2d18z/soil_evaluation.json` | `bd815e23bfb48b676b0231eaa61f54f981f7496f90ff65e49b737e7a1d09166c` |
| `scratch/workstation-research-output/workstream_c/cfsv2_soil_m2d18z/methodology_sensitivity_20000.json` | `6ec1a96397ef3bbe0ddd2623f74e5a31bb1ac97d5a49cdd8fbae3457b4af57ea` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/design_contract.json` | `7cdf53a78123b6863a629677411efc81784c38da7dee1729b846e0c27ff8f3ed` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/manifest.json` | `4ff0ebff25e14078a6f9c512becfe4091660d24c73741d62c7f04bd0cc0a69d5` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/predictor_scale_integrity_audit.json` | `2856c3ff5ca7f4f6079c92a1e04ca13344a4c98b9bf2595e583d5658122734e9` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/bootstrap_sensitivity_addendum.json` | `b8ae7b05e172dd716ee3d74d7fd645f34a5c440877b8a26e082b74f17276226a` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/hrrr_smoke_evaluation.json` | `8d9b94af3bee8a933c1fe371584d4001bc7b19c8fa0e01eee6f69d2e00a719e7` |
| `scratch/workstation-research-output/workstream_c/hrrr_smoke_m1d12z/methodology_sensitivity_20000.json` | `c46f0d8422f07530564d3257b76bd5577e0060baf42cac60814116f2f5bd001a` |
| `scratch/workstation-research-output/workstream_c/cfsv2_radiation_m2d18z/design_contract.json` | `06022cf7c16d8fd8946359151bd9292dd8a4b798f11077c7f65755116bae8dee` |
| `scratch/workstation-research-output/workstream_c/cfsv2_radiation_m2d18z/manifest.json` | `7847f31b2e4d0f1f8f6c29b7260140db9a3ab8a6a022f2c3fac646d0668b46a4` |
| `scratch/workstation-research-output/workstream_c/cfsv2_radiation_m2d18z/predictor_scale_integrity_audit.json` | `4d9a116a821af0501ea0ce49775b6141f33093227c841858d698b210680bb815` |
| `scratch/workstation-research-output/workstream_c/cfsv2_radiation_m2d18z/cfsv2_radiation_evaluation.json` | `71cccf8d6dc0fe530facd13af68e829a4a2c575a306d67a4b8b4e47971cfb8ee` |
| `scratch/workstation-research-output/workstream_c/cfsv2_radiation_m2d18z/methodology_sensitivity_20000.json` | `acf1bd25fff1b49655d1cbba38702334e73af367ada55887c3e3e634940aebdf` |
| `scratch/workstation-research-output/workstream_c/tmax_program_multiplicity_audit.json` | `076c5bff8cf27cd3808da116b4983ac2e51852b169e6a258168d2ebca2fbc553` |

The HRRR design's canonical self-hash is
`d12a7369bddb560b690ae02f0f5269602524c231df77da39a91553cd80ca6bca`.
The CFSv2 radiation design's canonical self-hash is
`cc9983e3317267086c2668849ad56eb3344dd92f48d81f8bee1a45027c7f7299`.
The soil availability contract's canonical self-hash is
`c7cb85e665906cfeb58d9be78fda8b652b2f5cb9e871589c1f69c3f4c02b0e19`.

## Official source contracts

- [NOAA NCEI Climate Forecast System product page](https://www.ncei.noaa.gov/products/weather-climate-models/climate-forecast-system)
- [NOAA NCEI CFSv2 metadata](https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc%3AC00877)
- [NOAA NCEI Rapid Refresh / HRRR product page](https://www.ncei.noaa.gov/products/weather-climate-models/rapid-refresh-update)
- [NWS HRRR smoke-units change notice](https://www.weather.gov/media/notification/pdf2/scn21-86rap_and_hrr_smoke_units_change_aab.pdf)
- [Open-Meteo Previous Runs API](https://open-meteo.com/en/docs/previous-runs-api)
- [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)

## Code and verification

The workstream adds bounded acquisition/research modules for Previous Runs
radiation, CFSv2 pressure, CFSv2 soil, CFSv2 exact radiation, and HRRR smoke;
a shared leakage-safe offline evaluator; a sealed no-refit methodology
sensitivity; and a permutation-invariant program multiplicity audit. New
artifact versions are registered in the central schema registry.

Verification on the final owned files:

- focused Workstream C matrix: **86 passed**;
- post-hoc safety/permutation subset: **13 passed**;
- strict schema registry audit: **PASS**, 0 unregistered versions;
- agent documentation audit: **PASS**, 18 agent files / 471 Markdown files;
- `compileall` over `src/weather/reporting/research` and `tests/reporting`:
  **PASS**; and
- `git diff --check`: **PASS**.

## Final disposition

1. **Open-Meteo radiation: NEW-SEASON ONLY.** Freeze code, fields, lead,
   transforms, model, and estimand. Evaluate once on a future independent
   season. Do not reuse the present holdout for tuning and do not collect in
   production yet.
2. **CFSv2 850 hPa: STOP.** No 925 hPa/mixing expansion on this evidence.
3. **CFSv2 soil: STOP.** Favorable development evidence failed terminal
   confirmation.
4. **HRRR AOTK/smoke mass: STOP.** Exact issue-time history and units are now
   proven feasible, but incremental skill is effectively null.
5. **CFSv2 radiation/cloud: STOP.** The independent provider/issue-time
   contract regressed clearly and does not confirm the Open-Meteo point.

No further same-outcome predictor search is warranted in this workstream.
Useful continuation requires genuinely new outcomes, not another transform of
the already opened dates.
