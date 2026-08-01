# Workstation band-mechanism diagnosis — 2026-08-01

## Verdict

The marine lead is **not the current-serving mechanism**. The July 22–30
captures do contain missing marine measurements, and the historical
`marine_water_contrast` sidecars really do stop on 2026-06-13. But every
checked-in HGB, logistic fallback, and late-day artifact used by the current
replay selects **zero marine features**. Removing the captured marine source
in memory changed **0/767** replayed distributions (`max L1 = 0.0`), including
all 391 Houston snapshots that contain observed marine measurements. No marine
data was generated, extended, injected, or written.

The answer to “one mechanism or five?” is: **one shared output failure with
two distinct geometric clusters, not one homogeneous cause and not five
independent band defects**.

- All five bands show a severe resolution failure: relative to the market,
  the model places much less mass on the realized winner and spreads more mass
  across losing bands.
- Los Angeles, Houston, and San Francisco add a clear warm-side displacement
  to that excess width.
- Dallas and Austin are nearly centered as a cluster; their dominant defect is
  excess width around an approximately correct center, especially in the
  early extreme-heat cases.

This remains diagnosis, not a candidate result. It does not authorize a
backfill, distribution transform, artifact, or promotion.

## Source, run root, and evidence boundary

| Field | Value |
| :--- | :--- |
| Source | exact `origin/master` `e7c2cece95b3e9e4222f935c8d5503816d6a3a92` |
| Topic branch | `codex/workstation-band-mechanisms-2026-08-03b` |
| Declared run root | `C:\Users\Michael\Documents\github\weather\scratch\runs\band-mechanisms-2026-08-03b` |
| Analysis window | 2026-07-22 through 2026-07-30, inclusive |
| Inputs reused | accepted exact corpus and current replay from `disagreement-map-2026-08-03a` |
| Input scale | 108 complete market-days; 19,265 snapshots; 211,915 band rows |
| Corpus identity | `promotion_corpus_v0.1`, SHA-256 `fc878cbc5290d45e93b36f9efdf796196708d125788da9458d3c1c8c2ef5fb72` |
| Workstation serving binding | `RESEARCH_UNBOUND`: no active release pointer; checked-in current artifacts and serving logic only |

All derived result rows and diagnostics were produced after the 2026-07-31
`rows[-1]` boundary. The accepted replay was reused rather than regenerated
because `25b6172b..e7c2cece` changes only the accepted disagreement-map report
and this handoff; there is no intervening serving-code or artifact change.

## What the model actually sees

The live extractor reads captured `sources["marine_context"]` and can derive
17 marine fields. Missing context returns all fields missing. A present but
unavailable station result produces explicit availability indicators—most
notably `marine_station_count=0` and a positive
`marine_missing_sensor_count`—while measurement fields remain missing. This
is neither a stale value nor blanket silent zero-filling.

Across the exact five-band snapshot universe:

| Market | Snapshots | Captured source state | Derived marine feature state | Marine fields selected by current artifacts |
| :--- | ---: | :--- | :--- | ---: |
| Los Angeles | 1,535 | 1,535 fresh wrappers reporting no usable station | 1,535 availability-indicators-only | 0 |
| San Francisco | 1,577 | 1,577 fresh wrappers reporting no usable station | 1,577 availability-indicators-only | 0 |
| Houston | 1,595 | 391 available; 1,204 fresh wrappers unavailable | 391 observed measurements; 1,204 availability-indicators-only | 0 |
| Dallas | 1,587 | source absent | 1,587 all missing | 0 |
| Austin | 1,600 | source absent | 1,600 all missing | 0 |

Houston proves that the extraction path itself is live. Its 391 observed rows
populate measurement fields; for example, 182 flag onshore flow and onshore
cooling potential, 67 flag marine-breeze risk, and 62 flag marine-layer
suppression. Those values still cannot affect this serving artifact.

### Why the stale sidecar has zero current effect

For every one of the five markets, the artifact inventory is:

- 14 HGB hours with 24 or 27 selected features, zero marine names, and zero
  marine tree splits;
- 14 logistic-fallback hours with the same zero marine names; and
- 3 late-day hours with 23 selected features and zero marine names.

`model_features.py::_evaluate_feature_model_for_cutoff` builds the full live
feature dictionary and then selects exactly the artifact's `feature_names`.
The current v0.2/v0.3/v0.5 artifacts therefore drop the newer marine columns
before inference. The historical `marine_water_contrast` sidecar is loaded by
training and candidate-replay assembly only when the candidate artifact
declares a marine feature; it is not an implicit input to these current
artifacts.

The production-host lead remains a valid **data-maintenance finding**: the
KLAX, KHOU, and KSFO manifests each describe a one-shot
`marine_water_contrast_backfill_v0.1` with 938 rows, generated on June 25 and
ending on June 13. It is simply not causal for the current replay.

The direct source-removal smoke covered 767 cases: all 391 Houston snapshots
with observed marine measurements plus the deterministic first unavailable
snapshot in each date/hour cell (124 Houston, 126 Los Angeles, 126 San
Francisco). Actual versus marine-source-removed distributions had mean and
maximum L1 distance `0.0`; all 767 were identical.

## Two-cluster failure shape

The table below covers **all 1,519 ≥30-point market-right rows in the five
retained bands**, including the minority where the model over-allocates to a
losing retained band. Probabilities are normalized over the settlement bands;
positive band-index displacement is warmer. Width and effective-band values
are model minus market.

| Measure | Coastal three | Inland Texas two |
| :--- | ---: | ---: |
| Severe rows | 1,029 | 490 |
| Mean absolute selected-band gap | 50.99 pts | 44.65 pts |
| Realized-winner probability, model minus market | **−53.61 pts** | **−43.45 pts** |
| Model mode equals realized winner | 23.71% | 25.71% |
| Market mode equals realized winner | 98.74% | 94.49% |
| Expected band index, model minus market | **+0.417** | **−0.078** |
| Band-index standard deviation, model minus market | +0.411 | +0.486 |
| Effective band count, model minus market | +1.257 | +1.467 |
| Cooler mass, model minus market | +9.28 pts | +14.94 pts |
| Warmer mass, model minus market | **+44.33 pts** | +28.51 pts |
| Forecast high minus realized-winner midpoint | +3.47°F | +1.03°F |

The coastal diagnosis is **warm miscentering plus excess width**. Its model
center lies 0.417 bands warmer than the market and almost five times as much
excess mass is on the warm side as on the cool side. The result is strongest
in Los Angeles, but Houston and San Francisco have the same sign.

The inland-Texas diagnosis is **excess width with little aggregate center
error**. Dallas is mildly warm (`+0.140` band index) and Austin mildly cool
(`−0.267`), producing a combined `−0.078`. Both remain substantially wider
than the market. Austin's severe rows occur especially early relative to the
daily high: current temperature averages 14.66°F below the realized-winner
midpoint even while forecast high is only 0.06°F away. That is a distribution
resolution problem around an approximately correct forecast high, not the
coastal warm displacement.

The aggregate “market higher than model” description is correct for the five
retained-band rankings, but the ≥30-point tail has useful nuance. Of the 1,519
selected severe rows, 1,149 (75.64%) are direct winner under-allocation and
370 (24.36%) are model over-allocation to a losing retained band. Both produce
the same lower-level signature: the market's mode is almost always the
realized winner while the model's distribution is displaced or diffuse.

## Severity-tail characterization

| Measure | Result |
| :--- | ---: |
| ≥30-point market-right rows | 9,032 / 211,915 (**4.262%**) |
| Unique snapshots containing those rows | 6,125 |
| Share of daily-normalized positive excess Brier | **60.205%** |
| Rows in the five retained bands | 1,519 / 9,032 (**16.82%**) |
| Five-band share of all positive contribution | **11.911%** |
| Five-band share of severe-tail positive contribution | **19.78%** |
| Coastal-three share of all positive contribution | 8.390% |
| Inland-Texas-two share of all positive contribution | 3.521% |

The tail is real and concentrated by severity, but it is not confined to the
five retained bands: 80.22% of severe-tail positive contribution lies
elsewhere. The five remain useful mechanism scopes because their full-band
recurrence and contribution passed the prior map's queue cut, not because
they exhaust the tail.

Capture hour is not a narrow trigger. Severe rows occur in all 24 hours and
on all nine dates. Hour 12 ranks first but contributes only 3.175% of all
positive contribution, or 5.27% of the severe-tail contribution. The top
five hours together carry only 24.34% of severe-tail contribution.

The collapsed general source-freshness state is also not a discriminator.
`failed:weather_forecast,wu_current,wu_history` describes 9,005/9,032 severe
rows (99.70%), but also 211,002/211,915 rows (99.57%) and 19,182/19,265
snapshots (99.57%) in the full replay. It is an almost universal state in this
retrospective capture and cannot explain tail membership.

Marine availability correlates with the selected coastal tail but is not
causal here: 1,001/1,029 coastal severe rows have availability indicators only
and 28 have observed measurements. Within Houston, the severe rate is 17.86%
for unavailable rows versus 7.16% for observed rows, yet removing the source
changes no prediction. The state is therefore a time/market marker for this
artifact, not an active model input.

## Leakage posture and limits

Feature/outcome leakage: **PASS for descriptive diagnosis**. Evaluation
independence: **development-only, not unseen-day, candidate, or promotion
evidence**.

- The analysis reuses the accepted exact July 22–30 current-serving replay;
  no fitting, tuning, parameter selection, candidate scoring, or
  outcome-conditioned rerun occurred.
- Distribution-shape metrics use the settlement outcome only to identify the
  realized winner after prediction. They describe existing errors and do not
  feed a rule back into the model.
- The marine counterfactual removes one captured source in memory. It neither
  supplies post-cutoff data nor substitutes historical sidecar values.
- July 22–30 is already-used retrospective engineering evidence, and current
  code postdates some target days. Nothing here is a forward holdout claim.
- The workstation has no active release pointer, so this is an exact audit of
  the checked-in artifacts used by the accepted current replay, not a claim
  that an independently bound production release was exercised.

## Ranked change disposition

1. **MEASURED CANDIDATE — coastal center plus scale.** Freeze one coastal
   hypothesis across Los Angeles, Houston, and San Francisco that can correct
   warm displacement and excess width together. It must earn its result on a
   separately declared forward/untouched evaluation and preserve aggregate
   Brier, calibration, probability mass, and non-tail behaviour. Do not turn
   the three bands into three overrides.
2. **MEASURED CANDIDATE — inland-Texas scale.** Test Dallas and Austin as one
   extreme-heat resolution lane, initially changing width without assuming a
   shared center correction. Gate explicitly on the ≥30-point loss tail as
   well as overall Brier so a median-row improvement cannot conceal worse
   severe errors.
3. **DATA FIX — marine sidecar continuity, deferred.** After release #1,
   schedule and measure the missing refresh/backfill only as a separate data
   change, and only alongside a train/serve-parity plan for an artifact that
   actually declares the marine columns. The current June 13 stop is real,
   but fixing it cannot repair today's artifact.
4. **NOTHING — current marine serving path.** Do not backfill, inject defaults,
   alter serving, or change the current artifacts before the lock. The direct
   counterfactual measured zero current effect.
5. **NOTHING — five band-specific patches or a generic global sharpen.** The
   evidence supports two scoped shapes and a broad tail outside the five. It
   does not support five independent overrides, nor does this diagnostic
   re-authorize a global transform.

## Machine-readable evidence and guardrails

All generated evidence is under the single declared run root outside the
mirror. Principal files:

- `serving-artifact-marine-usage.json` — artifact feature/split inventory;
  SHA-256 `b19253635eb6f0e93e7b6d0a76fe110f3368063ae9f8622eefe6319738e173fa`.
- `marine-runtime-summary.json` — per-market captured-source and derived-field
  inventory; SHA-256
  `d5c51d544297d54ff055e3a4e391f35db0dd64a52802ff47bf79cd6bd77aac5d`.
- `marine-source-removal-counterfactual.json` — zero-effect causal smoke;
  SHA-256 `1bc0a6c2ee073d22844f18aca633adc15567655742b0df8eb2ec7fe033051700`.
- `band-mechanism-analysis.json` — severity rankings and full distribution
  geometry; SHA-256
  `d1c313c498ce1a5cc285317621e3c7ff86d5220bbe1353e08b211a9e09cb3d7a`.
- `source-state-baseline.json` — tail-versus-universe source-state baseline;
  SHA-256 `59eaff98b97b16a155804c55bff2196963e9e6810057a712b0d87561ed44e8e4`.
- `severe-market-right-rows.csv` and `retained-band-severe-shape.csv` — row
  evidence; SHA-256 respectively
  `5a6a4bfed436619d1dc9887830bf8bdc0d9647be5efa14af649f38afe8b60c16`
  and `7f2be0eb82837a3cecfaa1951e75614e1ca5901dcb53b92077cc5b964ae0d8c1`.

`data/` and the mirror remained read-only. No marine extension, regeneration,
backfill, candidate, tuning, fitting, production artifact, PR, merge, master
push, promotion, pointer, serving, scheduler, capture, mirror, or ACL change
occurred. No sync credential was read or exposed.
