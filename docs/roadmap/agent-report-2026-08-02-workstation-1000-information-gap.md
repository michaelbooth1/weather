# Workstation 10:00 information-gap audit - 2026-08-02

## Verdict

**AUDIT COMPLETE; NO CANDIDATE, ARTIFACT, FIT, OR SCORE.** The best next
information hypothesis is not a new provider. It is a train/serve feature
continuity defect: same-day METAR/ECCC observations are captured, but the
active feature extractor admits those sources only to temperature and the hard
observed-high floor. At 09:00-14:00 on the floor-excluded development
population, nine of the 19 base features selected by the active HGB artifacts
are completely empty, and cloud state is populated only for Toronto. Several
of those empty fields are among the most-used fields in the trained trees.

The older physical-input diagnosis is also stale. Forecast 850/925 hPa thermal
structure, shortwave/direct/diffuse radiation, shallow soil moisture, and
smoke/AOD are present and varying in the captured feature rows; none is selected
by the current per-market HGB artifacts. Direct boundary-layer height remains
genuinely absent. Antecedent soil/reanalysis sidecars exist but are not present
in this captured replay. Marine live capture still works, but the historical
sidecar refresh has no daily owner and stopped at 2026-06-13.

No single available input plausibly closes a gap containing about 80% of the
remaining loss. The evidence supports a portfolio of narrower, predeclared
information tests, starting with the surface-observation continuity defect.
Some remainder is likely forecast uncertainty and market aggregation rather
than a recoverable calibration error. This audit cannot quantify that
irreducible share without a new experiment, and none was run.

## Scope and guardrails

The audit was based exactly on
`codex/workstation-forecast-residual-anchor-2026-08-18a @ ed0f5ffe` on topic
branch `codex/workstation-1000-information-gap-audit-2026-08-19a`.

The sole declared output root was
`C:\Users\Michael\Documents\github\weather\scratch\runs\1000-information-gap-audit-2026-08-19a`,
declared at `2026-08-02T19:46:18.6144173Z`. It is outside the mirror. The audit
read only the previously held July 22-26 manifest-pinned replay, its accepted
floor trace, the 12 tracked HGB artifacts, seven explicit marine sidecars, and
repository code/documentation. It did not read, enumerate, evaluate, or
substitute August 1-3 or August 6-19. It did not write `data/`, a sidecar, a
feature store, or a marine path. July 31 remains the `rows[-1]` POST-regime
boundary. No runtime, scheduler, pointer, floor, capture, or serving state was
changed.

## 1. Forecast-anchor post-mortem

The proposed rule is **too strong as a mathematical rule, but useful as a
candidate-screening rule for this repository**:

> Anchor reparameterization adds support information only when the anchor is a
> constraint. A non-constraint anchor can still change a finite model's
> inductive bias, but it supplies no new information and must earn its own
> evidence.

The continuation floor is different in kind: `D = Y - F` has `D >= 0`, so it
removes impossible support. A forecast-centred residual remains two-sided. The
active artifacts already use `forecast_high`, and `forecast_gap` has non-zero
splits in 154 of 168 hourly bundles. Replacing `Y` with `Y - forecast` therefore
did not reveal a missing variable or constrain the outcome.

The failure does not isolate anchor choice from every alternative mechanism.
The candidate estimated market/hour residual classes from only two to four
distinct settled dates per fold, and its two-sided smoothing left every local
valley in place even though aggregate means became monotone. Conditioning,
thin effective sample size, class support, and smoothing may all have
contributed. What the evidence does establish is that every predeclared setting
failed every validation date, with positive excess `+77.27%` and severe rows
`1,797 -> 3,665`; no tuning explanation rescues this form.

This rules out **anchor-only** follow-ups around climatology, persistence/high
so far, the forecast/blend centre, or market mid. The first three are
deterministic summaries of information already in the system and are not hard
bounds. Market mid can carry genuinely external aggregated information as a
predictor, but anchoring to it is not a weather-information repair, is not a
support constraint, and would require point-in-time train-side book continuity
before it could be evaluated.

## 2. What the active 09:00-14:00 models consume

The exact inventory covers 72 bundles: 12 market artifacts times six effective
cutoff hours. Across them, the active artifacts select 29 encoded names
representing 19 base features. Twenty-seven encoded names split at least once.
The exhaustive per-market/hour list is in `model-feature-inventory.json`.

| Selected feature | Bundle-feature selections | Selections with a split | Split nodes |
| --- | ---: | ---: | ---: |
| pressure | 72 | 72 | 57,777 |
| high so far | 72 | 72 | 55,682 |
| humidity | 72 | 72 | 49,589 |
| dew point | 72 | 72 | 38,899 |
| pressure trend, 3 h | 72 | 72 | 38,205 |
| wind speed | 72 | 72 | 37,842 |
| rise from 07:00 | 72 | 72 | 30,928 |
| current temperature | 72 | 72 | 30,683 |
| hours at peak | 72 | 71 | 11,940 |
| forecast high | 72 | 66 | 83,001 |
| forecast gap | 72 | 66 | 42,648 |
| warming rate, 2 h | 72 | 60 | 17,335 |
| cloud dummies, combined | 432 | 206 | 15,056 |
| wind dummies, combined | 432 | 265 | 18,302 |
| live reading / gap / elapsed minute | 126 | 126 | 121,984 |
| forecast source count | 12 | 3 | 3 |

`cloud_Other` and `forecast_disagreement` are selected but never split in the
09:00-14:00 bundles. The current feature schema declares 221 columns. Of the
202 columns outside the active 19-base-feature set, 129 are populated in the
accepted excluded rows and 122 are both populated and varying.

The important fact is serve-side availability, not tree importance:

| Active base feature | Non-missing on 2,275 excluded snapshots |
| --- | ---: |
| forecast high / source count / elapsed minute | 100.00% |
| high so far / current temp / live temp / live gap / forecast gap | 99.56% |
| forecast disagreement | 98.64% |
| cloud group | 11.16% (Toronto only) |
| dew point, humidity, pressure, pressure trend | **0.00%** |
| wind speed / wind group | **0.00%** |
| rise from 07:00 / warming rate / hours at peak | **0.00%** |

This is a sharper diagnosis than “the floor is silent.” In the excluded lane,
the served model is also blind to much of the observed same-day trajectory and
surface state on which its trained trees split heavily.

## 3. Captured but unused

There are two distinct disconnections.

### A. Raw observations do not reach already-selected features

METAR is present and healthy in all 2,275 audited snapshots. Its decoded dew
point, cloud cover, and temperature are populated on 2,263 snapshots (99.47%);
wind speed/direction are populated on 2,260 (99.34%). ECCC SWOB supplies
Toronto dew point and humidity on all 254 Toronto snapshots. The captured row
histories are sufficient to derive rise since 07:00, two-hour warming, and time
at the current peak.

Yet [`extract_live_features()`](../../src/weather/model/model_features.py#L739)
derives dew point, humidity, pressure, wind, cloud, and within-day trajectory
only from WU history/current rows. Those two paid-provider legacy sources are
expected-unavailable on the current target date. The separate station-source
adapter in
[`model_sources.py`](../../src/weather/model/model_sources.py#L293) retains only
temperature and max-since-07:00. The METAR adapter captures dew point, wind,
cover, and the full same-day row sequence, but not normalized pressure or
humidity. Humidity is derivable from captured temperature/dew point; future
pressure would require retaining the METAR altimeter/sea-level-pressure field.

This is not evidence that simply filling the fields will improve Brier. It is a
high-value falsifiable hypothesis because it restores the information contract
the incumbent trees were trained to use, with almost fleet-wide point-in-time
coverage and no new provider.

### B. Derived forecast/physical features reach the matrix but no active tree

The accepted excluded rows contain 122 inactive, varying columns. The most
relevant groups are:

- Forecast 925/850 hPa temperatures, lapse proxies, and 500 hPa height: 100%.
- Remaining/next-three-hour shortwave, direct/diffuse radiation, cloud layers,
  CAPE, VPD, ET0, shallow soil moisture, and hourly temperature profile: 100%.
- PM2.5, AOD, dust, and smoke-suppression diagnostics: 100%.
- Global-ensemble spread and global-model high deltas: 88.84-100% depending on
  US-only versus global fields.
- NWS grid and multimodel features: 88.84% fleet coverage.
- Live marine-derived fields: about 32.4% fleet coverage, with the source
  present for 66.4% because many rows have stations but lack a complete observed
  water/wind contrast.

These are not “uncaptured.” They are unselected by the current active HGB
artifacts. Prior item evidence also prevents treating availability as value:
the radiation family passed only for Austin, Dallas, and Houston; soil dryness
passed only a seven-market lane; marine passed conditional on onshore/breeze
rows but not the daily-first cutover gate; smoke and new global-model families
remain blocked.

## 4. What is genuinely absent now

Re-deriving the June audit against current code changes its list:

| Earlier diagnosis | Current truth at 09:00-14:00 |
| --- | --- |
| 850 hPa temperature / mixing height | Forecast 850/925 hPa structure is captured and derived at 100%; direct PBL/mixing height is not requested or represented. Antecedent pressure-level sidecars are absent from this replay and their NOAA source was lagged. |
| Soil moisture | Forecast 0-1 cm soil moisture is captured at 100% but inactive. The implemented antecedent 0-7 cm anomaly/water-balance sidecar is not injected into these captured rows. |
| Forecast shortwave | Captured, derived, varying, and inactive at 100%; it is no longer a collection gap. |
| Smoke/AOD | Captured, derived, varying, and inactive at 100%; the missing piece is replay-safe historical depth and regime evidence. |

The additional missing information is:

1. **Direct PBL/mixing depth.** Open-Meteo currently exposes hourly boundary
   layer height, and NOAA HRRR is hourly, 3 km, public, and archived since 2014.
   This would distinguish a shallow capped morning from one able to mix warm
   air down. It is forecast information, not an observed constraint.
2. **Observed radiative receipt / cloud evolution.** The system has forecast
   radiation and METAR cover but no observed surface shortwave or satellite
   cloud-motion/insolation state. This is the realized heating input between
   sunrise and 10:00, and is distinct from another daily-high forecast.
3. **Run-to-run guidance tendency.** The schema has
   `open_meteo_*_run_to_run_high_change` hooks, but both are empty and explicitly
   marked as requiring a previous-run archive. Sequential captured snapshots
   contain partial point-in-time history, but the feature row does not consume
   it and the training archive is incomplete.
4. **Replay-safe antecedent land state.** Soil/reanalysis sidecars exist on disk
   and have prior settlement evidence, but the audited captured-input rows have
   zero populated `reanalysis_*` fields. A point-in-time, release-bound injection
   contract is missing from this replay, not the underlying calculations.
5. **Complete current marine SST/contrast.** Live station capture is partial,
   while GLSEA/OISST coverage needed for Chicago, Los Angeles, and Seattle is
   absent from the held sidecars.

NOAA's Aviation Weather API is public but rate-limited; its official METAR
description includes wind, sky condition, temperature, dew point, and altimeter
setting. Open-Meteo's current forecast API documents boundary-layer height and
the surface-state/radiation variables already in use. NOAA HRRR's public AWS
archive requires no account and is explicitly open for use. These paths do not
require a paid weather provider:

- https://aviationweather.gov/data/api/
- https://open-meteo.com/en/docs
- https://registry.opendata.aws/noaa-hrrr-pds/

For commercial Open-Meteo use, the public page requires a paid licence and
dedicated endpoint; the accessible pricing page lists call budgets but not a
dollar amount, so a current vendor quote/dashboard price would be required.
That is unnecessary for the proposed first tests and remains unsupported by
repository policy. Nothing was procured or configured:
https://open-meteo.com/en/pricing.

## 5. Marine diagnosis

The failure is **sidecar refresh ownership plus known source sparsity**, not a
general live-capture or feature-construction failure.

- All seven explicit `marine_water_contrast` sidecars contain 938 rows from
  2022-06-17 through **2026-06-13**. Khou, KLGA, KMIA, and KSFO have 719, 624,
  938, and 420 water/wind rows respectively; KLAX, KORD, and KSEA have zero.
- Repository references provide a historical backfill CLI/planner and research
  loaders, but no scheduled daily marine-water-contrast refresh path.
- In the July 22-26 excluded snapshots, live `marine_context` capture is still
  present for Chicago 226/237, Houston 214/238, Los Angeles 24/232, Miami
  208/233, NYC 203/231, San Francisco 235/247, Seattle 147/237, and Toronto
  254/254. Water temperature is present for Houston, Miami, NYC, and Toronto;
  wind is present for Chicago, Houston, Miami, NYC, San Francisco, and Toronto.
- Live construction therefore still emits varying marine features, but the
  active HGB artifacts select zero of them. Removing live marine input cannot
  change those artifacts. The sidecar-backed Item 191 lane previously improved
  its onshore/breeze slice by `-0.007076` Brier but remained blocked for
  daily-first cutover.

No backfill, repair, refresh, or scheduler action was taken.

## 6. Expected-value ranking for the floor-excluded population

This ranks information families, not candidate models. “Cheap falsification”
is a proposal for a later predeclared mission, not work performed here.

| Rank | Input state | Why it could move the 10:00 centre | Acquisition / cost | Cheap falsification |
| ---: | --- | --- | --- | --- |
| 1 | Captured METAR/ECCC trajectory and surface state into the existing feature contract | Restores rise/warming/peak-age, dew point, wind, humidity, and cloud information that the trained trees use heavily but see as missing exactly in the excluded lane. It can distinguish continuing mixing/heating from an early plateau. | Existing Aviation Weather/ECCC captures; free. Pressure needs a small future adapter extension or must stay missing. | From immutable captures only, build a parity-safe station-derived feature view; compare coverage and missing-direction behavior first, then one isolated chronological excluded-only replay. Fail if lift is not stable across dates/markets or units/source roles differ from training. |
| 2 | Already-captured radiation/cloud profile | Directly measures forecast heating still available after 10:00; existing isolated evidence is positive for Austin/Dallas/Houston, especially midday. | Already captured/derived; zero provider cost. | Reuse the existing isolated radiation lane on a disjoint predeclared window. Fail outside its three-market lane unless it clears daily-first and high-disagreement gates. |
| 3 | Antecedent soil-dryness/water balance | Explains surface energy partitioning on low-floor hot days; prior settlement gate identified seven positive markets. | Existing reanalysis sidecars; free source, but point-in-time replay injection/refresh ownership is required. | Prove sidecar availability at capture and release binding, then replay only the pre-existing positive-market policy. Fail on stale/missing PIT lineage or loss of the prior lane. |
| 4 | Marine water contrast plus onshore flow | Explains coastal/lake bands where the point forecast remains warm while an onshore boundary arrests heating; prior onshore slice lift is material. It cannot explain inland loss. | Existing NOAA station feeds are free; GLSEA/OISST are public. Engineering and archive coverage, not provider fees, are the cost. | First repair only the research refresh contract in a later authorized mission, then repeat the predeclared onshore slice. Fail if daily-first tolerance or source-parity gate still blocks. |
| 5 | Direct PBL height paired with already-captured 850/925 structure | Measures whether warm air aloft can mix to the surface, the clearest truly absent centre-moving physical state at 10:00. Prior upper-air evidence is narrow/unstable, so EV is below already evidenced families. | Add `boundary_layer_height` to the existing Open-Meteo request for research, or use public NOAA HRRR archive for US markets; no paid provider required, but historical PIT extraction is nontrivial. | One isolated PBL/thermal family with issue-time archive proof and market-date folds. Fail if it adds no stable excluded-only lift over the already-captured 850/925 fields. |
| 6 | Run-to-run high/profile tendency | The market can react to new model cycles while the feature row sees only the latest level. Directional revisions can move the centre even when the ensemble centre is already present. | Earlier immutable snapshots are free; complete historical model-run continuity is missing. | Derive only from prior captured runs with strict issue/capture times; test incrementally over the current forecast/profile family. Fail on sparse continuity or no gain after level/spread controls. |
| 7 | Smoke/AOD suppression | Can explain one-sided warm busts on smoke days, but those are a narrow regime and current evidence has no settled high-smoke slice. | Already live-captured from Open-Meteo AQ; free for current research limits. Historical PIT depth is the cost. | Do not broad-fit. Wait for a predeclared high-AOD/high-PM slice, then require bust reduction and no aggregate regression. |
| 8 | Additional NWP member deltas | Could reveal clustered consensus error, mainly earlier in the day, but much of the same signal already enters `forecast_high`, spread, and existing model deltas. | Existing Open-Meteo global/multimodel captures; no incremental provider cost for research. | Require an isolated global-model family and predawn/morning lane; fail if incremental value disappears after forecast centre/spread controls. |

Observed surface shortwave/satellite cloud evolution is not ranked for immediate
work because it needs a new observation/archive contract. It remains a genuine
information gap and may eventually outrank the speculative families if the
captured surface-state repair fails.

## 7. How much is closable?

The honest answer is **not 80% by any one available input**. The target lane is
84.58% of the 09:00-14:00 primary window and holds 81.21% of positive excess,
but that concentration does not imply one omitted variable causes the loss.
The available features are correlated forecast views, several have already
shown only market- or regime-specific value, and the broad model comparison
found the market sharper than the preblend in all 21 cells and all 147
date-delete refits. The project's existing decomposition attributes 98.88% of
the gap to resolution and only 1.12% to reliability.

That bounds the conclusion in two ways:

1. Calibration-only and anchor-only work is the wrong response.
2. The market appears to aggregate information the single weather pipeline
   lacks, but the held evidence cannot separate recoverable omitted information
   from irreducible atmospheric uncertainty.

The rational sequence is therefore: restore already-captured surface
information, reuse only the already positive physical lanes, and treat PBL or
new observation feeds as isolated information-acquisition tests. If those fail
on disjoint dates, the objective should be reframed around selective abstention
or market aggregation rather than another fleet-wide weather candidate.

## Evidence identities

| Evidence | SHA-256 |
| --- | --- |
| Declaration | `4d9580ce49fb0eb5c0cbeaf09d954c925d7500086020131b13881ff8c93fdfcc` |
| Model/feature inventory | `2f82ccc3b223673596568a8e9b6a95a82decab8b84b6f7f912412f449c8fda4b` |
| Captured-payload inventory | `b10bc1e13ea89a241ed8a137411a18b09a0ef72fa7307841e7751b9f9226f952` |
| Marine-sidecar inventory | `1f6ce3a3b829a4bfea9f684894bc852b61b137f7792c50ce691d3c4e9ef49735` |
| Accepted development replay input | `55fd5104d7aa8240a9714d368ab15dd9bda34d87c4da27d7025b6cdb7c8e9ccd` |
| Development floor trace | `2e9da6e324130494760cd6b2dbe632658f6b29b99615439bab66fa1141519c9b` |
| Development corpus manifest | `8cf0d01d222172dadd024b3e55a69494860477785ec100cbe8ae2ed546c1662d` |

The tracked report is the only repository change. The audit JSON and scripts
remain ignored under the declared run root; no model artifact was created.
