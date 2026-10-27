# More-markets phase 2 scoping: forecast and score the next cities (2026-10-23)

Status: dated research note, workstation desk study, owner-approved 2026-10-23 ("yes approved", relayed). No code,
config, registration, scheduled-task, capture-host or `data/` change was made, and nothing under `data/` was read. It
is a proposal, not a decision. It builds on the [2026-10-14 desk study](more-markets-desk-study-2026-10-14.md)
(`ed476593f`, "DS-14" below) and the S2+S9 recorder-only pilot (DATA_LAYER_V2_PLAN.md:117, :336; `17439f7c8`).

**Number labels.** **[M]** = measured, with its source. **[C]** = computed here from measured inputs, with the
arithmetic shown. **[E]** = estimated, with the method stated. **[NM]** = not measured.

## Answer in eight lines

1. No extra US city is listed. The venue's 51 active locations include our 11 US built-ins and Toronto, and all 39
   others are non-US (`config/location_market_events.json`, generated 2026-10-23T10:00Z, `location_count` 51).
2. **No liquid candidate has a Weather Underground settlement source.** The venue names WU only for Jinan and
   Zhengzhou, which are Tier 3. Every other liquid city resolves on METAR: the NOAA WRH page, and since the 10-23
   events the raw `aviationweather.gov` METAR API. That is free, so for these cities the label should be METAR, with
   WU as a cross-check (§a).
3. **Recommended tranche:** London, Paris, Seoul, Tokyo and Shanghai (the five S2+S9 pilot cities), then Munich and
   Madrid. With the US11 that makes M = 18.
4. Each city needs a `MarketSpec`, a METAR label source and a 2021-2025 Open-Meteo Previous Runs archive. The US-only
   inputs (NWS, NBM, MRMS) go NaN, and the EDGE-1 binding twin T1 does nothing outside the US (§b).
5. **Power (§c):** under crossed clustering the market term is about 70% of the variance. It falls only as 1/M, so
   extra dates on the current 11 never get the crossed MDE80 below about 0.23 on R [C]. M = 36 gets it to about 0.12.
   No count in 18-36 reaches the 0.05 UNTESTABLE bar under crossed inference. Under the fixed-market primary, the
   0.05 bar needs about 227 dates at M = 11, 154 at 18, 125 at 24 and 97 at 36 [C].
6. **Storage (§d):** recorder-only costs about 4.3 MB per city-day gzipped [M, S2+S9 dry run]. The full model lane
   costs about 0.44 GiB per city-day retained [M, one sample]. Recorder-only fits; the model lane for 7 cities is
   about 3 GiB/day before NTFS compression [C].
7. **Timeline (§e):** the EDGE-1 freeze bars any serving-path change from D0 (10-28) to 12-21. So recorder-only now,
   the model lane built on the workstation now and landed after 12-21. A new city's first final read is about
   2027-03 at the earliest [E].
8. The owner has eight decisions to make (§e). The biggest is the label source for METAR-settled cities, followed by
   the host windows: Asian and European peak hours fall inside the merge window and Stage-A.

## (a) Which cities: liquidity and a free settlement source

**Universe [M].** `config/location_market_events.json` (generator `weather.operations.location_config_refresh`,
`source.event_count` 181, 51 locations, `locations_in_api_not_file` empty). Its US cities are exactly the built-ins
(`BUILTIN_SPECS`, `src/weather/market/market_registry.py:307-320`). **No extra US city is listed**, so every candidate
below is non-US. Polymarket US is not considered.

**Liquidity fields and their limits.** The config snapshot has **no volume or liquidity field**: its event and market
keys are ids, dates, URLs, labels, tokens and flags only. The public Gamma fields the repo already reads are
`volumeNum`/`volume` and `liquidityNum`/`liquidity` (`src/weather/market/polymarket_client.py:67-69`,
`src/weather/market/market_microstructure_capture.py:210-211`). No repo CLI prints them per city. Liquidity therefore
comes from the DS-14 census [M, public unauthenticated GETs 2026-10-14, closed events dated 08-31..09-29, n = 30 per
city; DS-14:30-38]. No new fetch was made: every closed event after 09-29 carries a resolved outcome, and this study
reads none. Limits of the measure:

- Event `volume` is whole-life notional over 2-4 trading days, summed over the bands. It is not calendar-day volume
  and not maker-addressable flow.
- The book depth figures come from one snapshot (DS-14:32-35).
- `liquidity` was not tabulated [NM].
- The reward pool is flat at about $100 per event-day per city (DS-14:36-37, :87-89), so it does not rank cities.

**Settlement source [M, metadata only].** Read per event from `resolution_source_url` in the same file:

| Event dates in the snapshot | Declared source |
| --- | --- |
| 10-22 | `weather.gov/wrh/timeseries?site=<icao>` for the foreign WRH cities |
| 10-23 and later | `aviationweather.gov/api/data/metar?ids=<ICAO>&format=raw...` for **every** city with a URL, built-ins included |
| Jinan, Zhengzhou (event dates 05-20/21) | `wunderground.com/history/daily/...` |
| Hong Kong (all events) | none (HKO, EF §10c) |
| Istanbul, Moscow, Tel Aviv | none on 10-22; METAR from 10-23 |

The 10-23 switch to raw METAR postdates EF §10c (ESTABLISHED_FINDINGS.md:3215), which records only the earlier
WU → weather.gov move. The Rules text behind the new URL was not read [NM]. `config/locations.json` still says
`wunderground_history` for most foreign cities, so it is stale against the venue (DS-14:171-172).

**What this means for "clean, free WU".** AGENT_CONTEXT.md:22-24 and :31 make configured WU the settlement proxy, but
for these cities the venue does not settle on WU. The free, settlement-faithful source is METAR: IEM, the venue and
the WRH page agreed at exact degree on 50/50 foreign station-days, 2026-09-20..29 (EF §10c; foreign-settlement desk
study :15-17) [M]. WU history for foreign stations is collectable by the existing public-page collector
(`python -m weather.sources.wu_history --market <market> public-backfill`, `wu_history.py:558`) only once a
`MarketSpec` with `wu_history_id` exists. Its agreement with the venue is [NM] for every foreign city.

**Shortlist** (DS-14 volume [M]; grade from DS-14 §5 updated for the 10-23 source; region is used for §c):

| City | Median event vol $ [M] | Source (venue, 10-23 snapshot) | Grade | Region |
| --- | ---: | --- | --- | --- |
| London EGLC | 80,543 | METAR | B | W. Europe |
| Shanghai ZSPD | 74,323 | METAR | B | E. Asia |
| Paris LFPB | 71,476 | METAR | B | W. Europe |
| Seoul RKSI | 64,825 | METAR | B | E. Asia |
| Tokyo RJTT | 62,610 | METAR | B (midnight max, foreign desk study :77-79) | E. Asia |
| Beijing ZBAA | 56,588 | METAR | B, pending rules text | E. Asia |
| Wellington NZWN | 54,942 | METAR | B, pending; southern-hemisphere DST | Oceania |
| Munich EDDM | 51,644 | METAR | B, pending | W. Europe |
| Madrid LEMD | 47,456 | METAR | B, pending | W. Europe |
| Milan, Amsterdam, Singapore, Shenzhen, Guangzhou, Chengdu | 42,983-48,025 | METAR | B, pending | Europe / E. & SE Asia |
| Hong Kong | 127,726 | none (HKO, floor rounding) | C: recorder-only | E. Asia |
| Jinan, Zhengzhou | 2,802 / 5,662 | WU | C: Tier 3 | E. Asia |

Rows are DS-14:43-58. The reference line is the built-in median, $41,901 (DS-14:38). "Pending" means the city's Rules
text has not been read, which DS-14 also left open (DS-14:204).

## (b) Per-city model needs

**Free sources (existing roles only).**

- **What a foreign city keeps:** `wu_history`, `wu_current`, `metar`, `weather_forecast`, `open_meteo`,
  `global_ensemble`, `open_meteo_multimodel` and `marine_context` (coastal only). These are the role names in the
  US specs (`market_registry.py:139-153`).
- **What a foreign city loses:** the US-only `nws_hourly`, `nws_grid`, `mrms_precip` and NBM, and the Canadian ECCC
  roles. Serving stays NaN-tolerant, but consensus loses those votes (DS-14:184-186).
- **Effect on EDGE-1 arms.** The binding twin T1 is NWS hourly alone, so it equals the base everywhere outside the
  US. That is the Toronto precedent, and Toronto is reported beside with no alpha (EDGE-1 annex §1, branch
  `claude/edge1-prereg-drafts-20261019`, lines 84-88). NBM reaches no band (EF §10u), so its loss costs nothing in the
  served path.
- **Open-Meteo history [M]:** Previous Runs covers Paris, Seoul, Shanghai and Tokyo from 2021. London's `best_match`
  starts only in 2024-03, so London must pin `gfs_seamless` (DS-14:179-181).

**Training corpus (code and config, not data).**

| Input | Depth | Source in the repo |
| --- | --- | --- |
| Forecast archive | Previous Runs from 2021 | `DEFAULT_PREVIOUS_RUN_START_YEAR = 2021` (`src/weather/sources/forecast_history.py:44`) |
| Training years | 2021-2025 | `FIRST_RETRAIN_TRAINING_YEARS = tuple(range(2021, 2026))` (`src/weather/operations/base_retrain.py:80`); [forecast-source-and-training-population.md](../operations/forecast-source-and-training-population.md):55-77 |
| WU history | no start bound in code | `public-backfill --start/--end` (`wu_history.py:558`); the depth WU serves per foreign station is [NM] |
| IEM METAR | no year bound in code | `metar_history.py:39`, the label source we propose |

- **Production WU status conflicts across documents.** AGENT_CONTEXT.md:80 says WU history fetching "stays off on
  production". DATA_LAYER_V2_PLAN.md:389 records `public_wu_settlement_restore` passing for 12/12 markets after
  redaction landed. Either way, it covers registered markets only.
- **Nothing is collected for unregistered cities.** The forecast-history collector iterates `all_specs()`
  (`forecast_history.py:1145`).

**Timezone and DST** [C, from `zoneinfo` with the tz in `config/locations.json`]:

| Group | Zone examples | DST | Local 14-17 h in Toronto time | Material window 12-18 h local in Toronto time |
| --- | --- | --- | --- | --- |
| W. Europe | London, Paris, Madrid, Munich | ends **2026-10-25**, starts 2027-03-28 | 08:00-12:00 | 06:00-13:00 (Stage-A 09:30-11:55) |
| E. Asia | Seoul, Tokyo, Shanghai, Beijing | none | 00:00-05:00 | 23:00-05:00 (merge window 01:00-04:00) |
| Oceania | Wellington | ends 2027-04-04 | 20:00-00:00, previous Toronto day | 18:00-01:00 |

- **DST bug exposure.** Every DST-observing new city inherits the Open-Meteo fixed-offset label defect (EF §10w,
  ESTABLISHED_FINDINGS.md:3909). That fix is scheduled for N13.
- **Midnight max.** Tokyo's daily max often lands on the local-midnight row (foreign desk study :77-79), so date
  bucketing must key on `obsTime` (AGENT_CONTEXT.md:63-71).

**Effective print cutoff [code].**

- Cutoff hours run 07-20 local (`INTRADAY_CUTOFF_HOURS`, `src/weather/model/model_constants.py:26`). The effective
  cutoff is the latest cutoff at or before the newest printed row (`model_distribution.py:1790-1800`). A print up to
  10 minutes before the hour counts for that hour (`SETTLEMENT_PRINT_ALIAS_WINDOW_MINUTES = 10`,
  `model_base.py:17`, `:160-176`).
- **Foreign stations report every 30 minutes** in the WRH evidence (foreign desk study :82-89). A :50 row aliases up
  to the hour; a :20 row does not. The per-station METAR minute is measured only for the 12 built-ins
  (FINDINGS_DIGEST.md:114-118), so for foreign stations it is [NM].
- **If METAR becomes the label for these cities**, "printed cutoff" has to be redefined on METAR rows. That is a
  parity change for the owner, not a config flip.

**Days until a new city counts** (existing rules):

| Rule | Days / dates | Source |
| --- | --- | --- |
| Per-day countability: material coverage 12:00-18:00 local, capture ratio >= 0.8, max gap 60 min (45 in the 14-17 peak), and reconciliation = `match` | from the first served day, if both hold | `src/weather/backtesting/settlement_ledger.py:45-55`, `:334-341` |
| A Polymarket-only winner is never countable; an independent local settlement is required | blocks every foreign day until a local label source exists | `settlement_ledger.py:741-760` |
| Never pool across an artifact-provenance boundary; a new city's first served artifact is one | the city starts its own clock | EF §5 (ESTABLISHED_FINDINGS.md:2152-2165) |
| Minimum training / retirement dates | 14 outer + 7 inner train dates; 14 locked dates; 14 paired fleet dates | `pooled_training.py:458-459`; `residual_distribution_v1.py:95-96`; `model_stage_retirement.py:32` |
| Model-edge instrument (EDGE-1 template) | market list fixed in advance; interim at 20, final at 45 countable dates; power on development dates before D0 | EDGE-1 annex §2 (lines 229-232); methods annex M4.4 (lines 189-193) |
| Serving freeze | no serving-path landing from D0 2026-10-28 to 12-21 | methods annex M5.2 residual rule (lines 278-283) |

**Earliest path [E]** (assumes every date is countable; method: add up the rules above):

1. Land after 12-21, at the earliest in the first quiet window: 2026-12-22.
2. Collect at least 14 development dates, about 2027-01-05.
3. Sign a new instrument with D0 around 2027-01-10.
4. Interim read about 2027-01-30; **final read about 2027-02-24**. A realistic margin of 2-4 weeks for missed dates
   moves the final to March 2027.

New cities can never join EDGE-1's US11 list (fixed, annex §2).

## (c) EDGE-1 power at M = 18, 24, 36 vs more days on the current 11

**Where the method lives.**

- **Primary inference:** fixed-market, date-clustered bootstrap (methods annex M3, lines 130-145).
- **Crossed date x market:** reported beside it and binding as a falsifier. EF §5 makes crossed clustering
  mandatory; the market dimension sets a hard floor (EF §1d, ESTABLISHED_FINDINGS.md:726-732, "set by markets not
  dates").
- **UNTESTABLE bar:** MDE80 on R > 0.05 (M4.4, lines 194-206).
- **Measured anchor:** H-A0 MDE80 on R is 0.308 / 0.263 / 0.242 at 20 / 45 / 90 dates x 11 markets [M,
  `v3_power.resampled_power`, edge1 annex §8 lines 413-419].

**Inputs [M].** The variance components are the two-way method-of-moments components of the served-vs-market 00-16
influence table, z = (Brier_served - R x Brier_mkt) / mean(Brier_mkt), over 55 development dates x 11 markets:

- date component σ_D² = 0.012509;
- market component σ_M² = 0.047903;
- residual σ_E² = 0.654261.

Source: `provenance/edge1-rpower-2026-10-20.json`, `programme_components_diag`, index 4 = `A0_00-16` (selection order
in the probe, line 114).

**Formulas.** z80 = z.975 + z.80 = 2.8016.

- Crossed: V_c = σ_D²/D + σ_M²/M + σ_E²/(D·M).
- Fixed-market (the market term is fixed, so it drops out): V_f = σ_D²/D + σ_E²/(D·M).
- MDE80 = 2.8016 · √V.
- **Calibration.** At M = 11 the analytic crossed MDE80 is 0.250 / 0.216 / 0.201 against the resampled 0.308 / 0.263 /
  0.242. The ratio is 1.20-1.23 (mean 1.216), and the crossed column is scaled by it. That is conservative for larger
  M, because the extra width comes from estimating the SE from only 11 markets.

**Cross-market correlation within a date.** σ_D² *is* the part of each cell shared by every market on that date. The
cell ICC is 0.0125 / 0.7147 = 0.0175 [C]. It enters as σ_D²/D, which more markets never shrink. That is the
within-date correlation, handled exactly under the assumption that new markets share the US11 components. The US11
already contain close regional pairs (three Texas markets, three West Coast markets), so the measured components
include regional correlation of that kind. **Worst-case bound:** the new cities' residuals are perfectly correlated
within each region, so each region counts as one market. M_eff is then 11 + number of regions: 13 for the M = 18
tranche (2 regions), 15 for M = 24, and about 17 for M = 36.

**Table [C].** MDE80 on R; "fixed" is the M3 primary, "crossed" is calibrated.

| M | D = 20 crossed / fixed | D = 45 crossed / fixed | D = 90 crossed / fixed | D = 365 crossed / fixed | D → ∞ crossed |
| ---: | --- | --- | --- | --- | ---: |
| 11 | 0.304 / 0.168 | 0.263 / 0.112 | 0.244 / 0.079 | 0.230 / 0.039 | 0.225 |
| 18 | 0.243 / 0.138 | 0.208 / 0.092 | 0.193 / 0.065 | 0.180 / 0.032 | 0.176 |
| 24 | 0.215 / 0.125 | 0.183 / 0.083 | 0.168 / 0.059 | 0.156 / 0.029 | 0.152 |
| 36 | 0.182 / 0.110 | 0.153 / 0.073 | 0.139 / 0.052 | 0.128 / 0.026 | 0.124 |
| worst case M_eff 13 / 15 / 17 at D = 45 | — | 0.243 / 0.105, 0.227 / 0.099, 0.214 / 0.094 | — | — | — |

- **Dates for fixed-market MDE80 <= 0.05:** D >= (2.8016/0.05)² · (σ_D² + σ_E²/M). That gives **227** at M = 11,
  **154** at 18, **125** at 24 and **97** at 36. For <= 0.10: 57 / 39 / 32 / 25 [C].
- **Crossed:** the floor 2.8016 · √(σ_M²/M) · 1.216 stays above 0.05 for any M below about 220 [C]. So **no tranche
  makes an E1 hypothesis TESTABLE under crossed inference**. The market term is 73% of V_c at M = 11 and still 66% at
  M = 36 (D = 45) [C].
- **Reading.** For the crossed falsifier, which EF §5 and M7.1 bind, M is the only lever: M = 36 at 45 dates
  (0.153) beats M = 11 at any number of dates (0.225). For the fixed-market primary, dates and markets trade
  roughly as D·M. M = 18 at 45 dates (0.092) is about M = 11 at 70 dates. M = 36 at 45 dates (0.073) is about M = 11
  at 115 dates.
- **The 12-cluster floor.** This study reads it two ways and meets both. First, no look below 12 date clusters
  (every row above has D >= 20). Second, EF §1d's floor set by the 12 market clusters, which is the D → ∞ column.
  Note: the repo's coded minimum is 10 date clusters (`execution_tape_markout.py:77`).

**Assumptions** (any of them failing moves the table):

1. New markets have the US11 variance components. They are [NM] for foreign cities, and their markets and served
   model differ: no NWS or NBM.
2. Market Brier levels are similar.
3. The arm's effect is common across markets.
4. The development-date variance carries over to forward dates.
5. Normal approximation.
6. No type-I correction beyond 45 dates. The annex forbids 90 dates without one (lines 396-398).
7. **Development context:** served R at 00-16 is 1.510 [M, same JSON], i.e. the arm trails the market by 51%. Power
   is moot unless an arm gets near parity.

## (d) Storage per market-day and host load

**Measured figures only.**

| Item | Figure | Source |
| --- | --- | --- |
| Recorder-only pilot, 5 cities, top 10 bands, T+0..T+2 | **≈4.3 MB/city-day gzip**, ≈105 MB/city-day plain (523 MB/day for 5) [M, 1.035 h dry run scaled linearly] | `e2d48d849` (DATA_LAYER_V2_PLAN.md S2+S9 dry-run paragraph on `claude/dlv2-s2-s9-pilot-20261015`, not on master) |
| Earlier 88a per-city figure | 7.1-7.7 MB/city-day, 0.8 MB/condition-day gzip [M] | DATA_LAYER_V2_PLAN.md:117; swarm-expansion-2026-10-01.md:58, :176 |
| Pilot REST | 0.092 req/s for 5 cities (books 0.034 + rewards 0.024 + Gamma 0.034), ≈0.018 req/s per city [C from M]; whole run 0.374 req/s steady against a 0.4 budget; zero 429s | same dry run |
| 88a memory | ≈23 MiB commit after import [M] | EF §10s (ESTABLISHED_FINDINGS.md:3744) |
| Full model lane | **0.439 GiB per closed city-day** retained [M, one sample]; NTFS 2.97:1 on small files, ratio on large files [NM] | swarm-expansion-2026-10-01.md:46, :56 |
| Model-lane families | order books 21 MiB, variant predictions 79 MiB, book summary 48 MiB, explanations ≈40 MiB per city-day [M] | drive-offload-2026-10-02.md:27-38 |
| Execution tape | ≈0.5 MB/day of tape for the then-universe [M]; per city [NM] | efficiency-audit-2026-09-27.md:25 |
| Baseline burn, no new city | 4.5-8.6 GiB/day [M/E] | swarm-expansion :45; drive-offload :79 |
| Host ceilings | Stage-A ≈75 min, the "first time ceiling on adding cities"; Open-Meteo free quota binds at ≈130 cities; fleet CPU 0.2 core plus 0.1-0.2 [E]; Stage-A incremental (#117) is listed done at :64 | swarm-expansion :47, :53-54, :64 |
| Disk policy | green >= 75 GiB free, daily-low target >= 70 GiB; pilot families stop below 70 GiB | storage-plan-2026-09-23.md:28-35; `config/capture_families.json` (at `17439f7c8`) |

DS-14 cites the execution-tape per-city figure (0.6 MB) to ESTABLISHED_FINDINGS.md:1264. That line holds no such
number, so this note does not use it.

**Per tranche [C].**

| Added cities | Recorder-only (4.3 MB per city-day) | Recorder at the older 7.7 MB | Model lane before NTFS (0.439 GiB per city-day) | Model lane after NTFS at 2.97:1 [E, small-file ratio] |
| --- | --- | --- | --- | --- |
| +7 (M = 18) | 30 MB/day | 54 MB/day | 3.07 GiB/day | ≈1.0 GiB/day |
| +13 (M = 24) | 56 MB/day | 100 MB/day | 5.71 GiB/day | ≈1.9 GiB/day |
| +25 (M = 36) | 108 MB/day | 193 MB/day | 11.0 GiB/day | ≈3.7 GiB/day |

**Not measured, and the estimate method for each:**

- **Today's free space.** Read `Get-Volume -DriveLetter C` on the host.
- **Foreign model-lane bytes.** These are likely below the US sample, because there is no NBM bulletin text in
  `last_good_sources.json` (≈36 MB per US station, EF §10s). Method: one recorder-on day per city, then the 91a
  manifest size for that event folder.
- **Host CPU per added model city.** Method: `status.ps1` capture-process CPU before and after one added city.
- **The 88a `peak_raw_working_bytes` against the 500 MB latch.** Read it from `status.ps1` after the P1 day-3
  receipts. It is gated below 50% (DATA_LAYER_V2_PLAN.md:118).

**Host-load timing [C].** The host's protected windows are US-centric: graded 12:00-18:00 and near-close 18:00-00:30
Toronto. The new cities' material windows (table in §b) fall elsewhere:

- **East Asia** falls in the 01:00-04:00 roll-sensitive merge window and in the 00:30-09:00 heavy window.
- **Europe** overlaps Stage-A (09:30-11:55).

A `STALE_CODE` restart in those hours could open a gap of more than 60 minutes and cost a countable Asian or European
day (`settlement_ledger.py:47-49`). This does not matter for recorder-only; it matters once the model lane serves.

## (e) Recommended first tranche, timeline, owner decisions

**Tranche.** Phases R1-R2 are recorder-only. Phase M1 is the model lane.

| Phase | Cities | M served | What | Earliest |
| --- | --- | ---: | --- | --- |
| R1 | London, Paris, Seoul, Tokyo, Shanghai (the P1 rows already in `config/capture_families.json`) | 11 | switch `pilot` on (config, roll-free per AGENTS.md; verdict from `roll_verdict.ps1`) after S2+S9 lands | after the 10-25/26 S2+S9 night and its day-3 receipts (≈10-29) |
| R2 | + Munich, Madrid, Beijing, Wellington, Hong Kong (recorder only) | 11 | config rows; REST ≈+0.09 req/s [C], which needs the post-10-31 `event_driven` cadence to fit 0.4 | after R1 receipts, ≥ 11-01 |
| M1 build | London, Paris, Seoul, Tokyo, Shanghai, Munich, Madrid | 18 | workstation: `MarketSpec`s, METAR label adapter, Previous Runs 2021-2025 under `workstation_heavy.ps1`, dev replay | now → 12-21 (no landing) |
| M1 land | same | 18 | quiet window 01:00-04:00 via `quiet_window_merge.ps1`; new instrument signed after ≥ 14 dev dates | ≥ 12-22; final read ≈ late Feb-Mar 2027 [E] |
| M2 | + Beijing, Wellington, Milan, Amsterdam, Singapore, Shenzhen | 24 | only if M1 shows near-parity arms | after the M1 interim |

The tranche avoids stacking mainland China: there are eight Chinese cities, and EF §1d and DS-14:111-112 warn they count
as less than eight independent markets. It favours cities with long series and full 2021 archives.

**Owner decisions.**

1. **Label source for METAR-settled cities.** The default proposal is IEM METAR as the local settlement for
   reconciliation, with WU as a cross-check. That would amend the "configured WU is the settlement proxy" contract
   (AGENTS.md; AGENT_CONTEXT.md:22-31) and the ledger's WU-only path (EF §10c). The alternative is to keep WU and
   first measure WU≡venue per city.
2. **Recognise the 10-23 venue switch** to raw `aviationweather.gov` METAR, the built-ins included, as a finding.
   This needs an EF §10c addendum and a Rules-text read; this study did neither.
3. **R1/R2 go**: turn the pilot on after the S2+S9 receipts, and approve the R2 cities.
4. **Freeze compliance**: confirm that no model-lane landing happens before 12-21 (methods annex M5.2), so M1 is
   build-only until then.
5. **Host windows**: accept that Asian and European material windows overlap the merge window and Stage-A, or move
   roll-sensitive merges for the served foreign cities.
6. **Scale and estimand**: choose M = 18 now (recommended) or wait for M = 24/36. Set which inference binds for new
   cities. Under crossed inference no realistic M reaches the 0.05 bar (§c).
7. **Storage**: approve ≈1-3 GiB/day of model lane [C/E] for M = 18-24 against the >= 70 GiB daily low, or require
   Drive offload first.
8. **Hong Kong**: recorder-only for maker economics, or an HKO adapter (grade C).

## Not answered, and why

- **Liquidity after 09-29.** Closed events after 09-29 carry outcomes and were not fetched.
- **Calendar-day volume and `liquidityNum`.** Not tabulated; no repo CLI prints them.
- **Rules text for every city's 10-23 METAR source.** Not read; this is a public read for a later step.
- **WU history depth per foreign station, and WU≡venue agreement.** Both need fetches; the code has no bound.
- **Foreign variance components.** No development dates exist, because no foreign city is served.
- **Today's host free space and per-city host CPU.** Both are capture-host reads.
- **Whether the US11 components transfer abroad.** This is the main assumption in §c.
