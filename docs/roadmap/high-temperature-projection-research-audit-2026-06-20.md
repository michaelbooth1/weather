# Daily-High Projection — Research Audit & Data-Source Gap Analysis (2026-06-20)

What physically determines a day's maximum temperature, what the model already
captures, and which additional data sources the scholarly literature says would
help. Companion to `core-model-audit-2026-06-20.md` (that audit covered *code*;
this one covers *predictors and data*).

Method: mapped the model's live feature set
([model_features.py](../../src/weather/model/model_features.py),
[feature_store.py](../../src/weather/model/feature_store.py),
[model_distribution.py](../../src/weather/model/model_distribution.py)) onto the
physical drivers of the daytime maximum, then checked each against the
post-processing and land–atmosphere literature.

---

## 1. The physics of the daily high (the predictor framework)

Tmax is set by the surface energy balance during peak insolation (~10:00–16:00):
net radiation `(1−α)·SW↓ + LW↓ − LW↑` is partitioned into **sensible** heat (warms
the air), **latent** heat (evaporation, does not), and **ground** heat flux. The
high is how hot the growing daytime mixed layer gets before the sun weakens. The
controllable drivers, in rough order of how much they explain day-to-day spread:

| Driver | Physical role | Literature anchor |
| --- | --- | --- |
| **A. Surface shortwave / clouds / smoke** | sets the energy input during peak heating | clouds lower Tmax by cutting SW↓ ([MDPI Climate 2019](https://www.mdpi.com/2225-1154/7/7/89)) |
| **B. Soil moisture / ET (Bowen ratio)** | dry soil → sensible heat → higher Tmax; wet → latent → lower | dominant control on hot extremes ([Nat. Commun. 2025](https://www.nature.com/articles/s41467-025-56109-0); [WACE 2015](https://www.sciencedirect.com/science/article/pii/S2212094715000201)) |
| **C. Air mass aloft / mixing** | 850 hPa temp + thickness mixed down into a deep PBL | the "850 mixing"/thickness method ([Wea. Forecasting 1995](https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml)) |
| **D. Advection / fronts** | warm/cold-air advection, frontal timing can cap the high early | thickness-tendency in the same technique |
| **E. Local circulations** | lake/sea breeze cools shorelines; downslope warms; UHI | Great Lakes breeze representation ([GLSEA / CoastWatch](https://coastwatch.glerl.noaa.gov/satellite-data-products/great-lakes-surface-environmental-analysis-glsea/)) |
| **F. Surface albedo / snow** | snow cover suppresses Tmax (shoulder seasons) | (lower priority for summer markets) |
| **G. Antecedent state / persistence** | morning temp, overnight min, the day's path so far | analog/persistence skill ([Delle Monache 2013](https://journals.ametsoc.org/mwr/article/141/10/3498/71598/Probabilistic-Weather-Prediction-with-an-Analog)) |

---

## 2. What the model already captures (credit where due)

The model is genuinely strong on **G, D-partial, E-partial, and the forecast
ensemble**, which is most of what short-lead Tmax post-processing usually uses:

- **G — observed path / persistence (excellent):** `high_so_far`, `current_temp`,
  `rise_from_7am`, `warming_rate_2h`, `hours_at_peak`, plus an empirical
  climatology prior and a feature-based analog search
  ([model_features.py:336-592](../../src/weather/model/model_features.py#L336)).
  This matches the Analog-Ensemble predictor philosophy (2 m temp path + wind)
  of [Delle Monache et al. 2013](https://journals.ametsoc.org/mwr/article/141/10/3498/71598/Probabilistic-Weather-Prediction-with-an-Analog).
- **Forecast ensemble (strong):** Open-Meteo (incl. multi-model GFS/HRRR/NBM/NAM),
  NWS grid, ECCC GEM/HRDPS, a global ensemble with member spread + p10/p90,
  disabled paid-provider, and ECCC city-page — distilled into `forecast_high`,
  `forecast_gap`, `forecast_disagreement`, per-model deltas, run-age, and
  run-to-run change. This is a richer forecast-feature set than most published
  EMOS/QRF studies use.
- **D — advection proxies (partial):** `pressure_trend_3h`, `wind_shift_3h`,
  run-to-run forecast change, multi-model disagreement (a frontal-uncertainty
  proxy).
- **E — local circulation (partial):** `onshore_flow`, `lake_breeze_proxy`,
  `wind_group`, and a marine-context layer (item 78).
- **A — clouds (partial):** `cloud_group`, NWS-grid sky-cover/POP/QPF after the
  cutoff, an MRMS radar precip-interruption layer (item 79), forecast CAPE/precip
  profile.
- **Calibration:** per-hour temperature scaling tuned by log loss, which is
  squarely in the modern ML-post-processing tradition of
  [Rasp & Lerch 2018](https://arxiv.org/pdf/1805.09091) and
  [Taillardat et al. 2016](https://journals.ametsoc.org/view/journals/mwre/144/6/mwr-d-15-0260.1.xml).

So the model is not naive — it already implements a credible hybrid of climatology
prior + gradient-boosted post-processing + analog reasoning. The gaps below are
specific physical drivers it is **blind to**, not a wholesale redesign.

---

## 3. Gaps — physical drivers the model does not (well) capture

### Gap 1 — Boundary-layer thermodynamics: 850 hPa temperature, thickness, mixing height (driver C)
**Highest leverage, and the scaffolding already exists.** `extract_live_features`
emits `empty_reanalysis_synoptic_features()` at serve time
([model_features.py:587](../../src/weather/model/model_features.py#L587)) — the
synoptic feature columns are present but **unpopulated** (item 32 is PARTIAL /
blocked). Yet the single most classic operational Tmax method is to mix the 850 hPa
temperature (and 850–700 / 1000–850 thickness) down a deep daytime PBL
([Wea. Forecasting 1995](https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml)).
The model is leaving its most physically-grounded predictor on the table.
*Source already reachable:* Open-Meteo pressure-level API (`temperature_850hPa`,
`geopotential_height_850hPa/700hPa`), GFS/HRRR/GEM pressure levels, ERA5. → **unblock item 32.**

### Gap 2 — Soil moisture / antecedent land-surface state (driver B)
**Biggest *missing* physical driver.** The model has **no** soil-moisture,
evapotranspiration, or antecedent-precipitation feature. The land–atmosphere
literature is unambiguous that antecedent dryness is the dominant non-synoptic
control on hot-day extremes: dry soils shift the energy balance toward sensible
heat and amplify the high ([Nat. Commun. 2025](https://www.nature.com/articles/s41467-025-56109-0);
[WACE 2015 — soil moisture & European Tmax extremes](https://www.sciencedirect.com/science/article/pii/S2212094715000201)).
Soil moisture is slowly varying, so a multi-day data lag is fine.
*Sources:* **NLDAS-2** root-zone soil moisture (operational, ~4-day lag, CONUS —
covers US markets, [Drought.gov/NLDAS](https://www.drought.gov/data-maps-tools/north-american-land-data-assimilation-system-nldas));
**ERA5-Land** soil moisture/soil temperature (global — covers Toronto and every
market); **SMAP L4** root-zone ([SMAP/ERA5-Land fusion, ESSD 2026](https://essd.copernicus.org/articles/18/1061/2026/)).
Feature: root-zone soil-moisture **percentile/anomaly** + antecedent 7/14/30-day
precip + evaporative fraction.

### Gap 3 — Surface shortwave radiation & peak-window cloud cover (driver A)
The model reasons about clouds **categorically** (`cloud_group`, sky-cover) but
never ingests the **downward shortwave radiation flux (GHI/DSWRF)** that those
clouds modulate — the quantity that actually drives daytime heating. Insolation/
cloud-based models beat temperature-only models for exactly this reason
([MDPI Climate 2019](https://www.mdpi.com/2225-1154/7/7/89); [Eurasia all-sky Tmax
ML reconstruction](https://www.sciencedirect.com/science/article/abs/pii/S0169809522003842)).
*Source already fetched:* Open-Meteo serves hourly `shortwave_radiation` and
`cloudcover` — add the integral of forecast SW↓ over the remaining heating window
as a feature (near-zero new collection cost).

### Gap 4 — Aerosols / wildfire smoke (modifies driver A)
The model is **blind to smoke**, a regime that has produced large one-sided Tmax
busts over Toronto/NYC in recent summers. Thick smoke dims the surface and
suppresses the daytime maximum by several degrees ([California smoke temperature
anomaly, ACP 2024](https://acp.copernicus.org/articles/24/6937/2024/)); operational
smoke fields exist ([HRRR-Smoke, NWS](https://www.weather.gov/mfr/HRRR_smoke_tutorial)).
*Sources:* **HRRR-Smoke** (near-surface PM2.5 + column AOD, CONUS); **Copernicus
CAMS** AOD/PM2.5 (global — covers Toronto); **Open-Meteo Air-Quality API** serves
CAMS `aerosol_optical_depth` / `pm2_5`. Feature: AOD / near-surface smoke over the
heating window, as a Tmax-suppression flag.

### Gap 5 — Lake/sea surface temperature for breeze markets (sharpens driver E)
`lake_breeze_proxy` is wind-only; it never sees the **lake–land temperature
contrast** that actually sets breeze strength and inland penetration. For Toronto
(and Chicago/Detroit) the lake-breeze front can reach Pearson on some afternoons
and shave the high. *Source:* **GLSEA** daily Great-Lakes surface temperature
([NOAA CoastWatch](https://coastwatch.glerl.noaa.gov/satellite-data-products/great-lakes-surface-environmental-analysis-glsea/));
OISST/NDBC buoys for coastal markets. Feature: lake-minus-air contrast × breeze-
favorable wind.

### Gap 6 — Albedo / snow cover (driver F)
No snow/albedo feature. Immaterial for summer markets; flag it for any shoulder-
season or northern market (SNODAS / IMS snow cover).

---

## 4. Forecast-input gaps (widen the ensemble the model already consumes)

- **ECMWF + ML-NWP members.** The ensemble lacks ECMWF (HRES/ENS) and the new
  ML models. ECMWF's **AIFS** went operational Feb 2025 and cut surface-T RMSE
  ~20% vs the physics ensemble at day 5 ([ECMWF AIFS](https://arxiv.org/html/2509.18994v1));
  **GenCast** is the first ML model to beat ENS probabilistically
  ([GenCast/marginals work](https://arxiv.org/pdf/2506.10772)). Open-Meteo already
  serves ECMWF IFS and several ML models — adding them widens `forecast_high` /
  `forecast_disagreement` cheaply and is exactly the "add other models' output as
  predictors" lever [Rasp & Lerch](https://arxiv.org/pdf/1805.09091) highlight.
- **NBM native probabilistic Tmax.** The model consumes NBM's *point* high but
  NBM publishes **calibrated Tmax percentiles / exceedance probabilities** — a
  ready-made calibrated Tmax PDF ([NOAA MDL NBM v4.2](https://vlab.noaa.gov/web/mdl/-/nbm-upgraded-to-version-4-2)).
  Consume the percentiles directly as features or as a calibration anchor for US
  markets.

---

## 5. Methodological notes from the post-processing literature

- **Distributional target over bucket classification.** The model classifies ~25
  integer-degree buckets and then patches ordinal structure with smoothing (see
  `core-model-audit` H1). The field instead predicts a **continuous predictive
  distribution** — EMOS/NGR, **quantile regression forests**
  ([Taillardat 2016](https://journals.ametsoc.org/view/journals/mwre/144/6/mwr-d-15-0260.1.xml),
  operational at Météo-France), or distributional networks
  ([Rasp & Lerch 2018](https://arxiv.org/pdf/1805.09091)). This is more
  sample-efficient and ordinal-aware. → aligns with **item 35** (continuous
  density); finishing it is the single biggest methodological upgrade.
- **Score with CRPS + PIT.** For a continuous Tmax target the standard headline
  score is **CRPS**, with **PIT histograms** / reliability diagrams for
  calibration ([post-processing review, Vannitsem et al.](https://arxiv.org/pdf/2004.06582)).
  The model's Brier/log-loss are fine for the bucketized form but CRPS makes it
  rank-comparable to NBM/EMOS baselines.
- **Learned station/market embeddings.** The pooled multi-market model could
  replace hand-built microclimate flags with learned market embeddings — the key
  ingredient behind [Rasp & Lerch](https://arxiv.org/pdf/1805.09091)'s gains.
- **Analog similarity metric.** The analog search could adopt a learned
  similarity metric ([ML analog metric](https://arxiv.org/pdf/2103.04530)) instead
  of fixed feature weights.

---

## 6. Prioritized recommendations

| # | Add | Driver | Effort | Owner |
| --- | --- | --- | --- | --- |
| 1 | **850 hPa temp + thickness + mixing height** | C | M | unblock **item 32** |
| 2 | **Root-zone soil moisture + antecedent precip / ET** (NLDAS-2 + ERA5-Land) | B | M | **new item** |
| 3 | **Forecast SW↓ + peak-window cloud integral** (Open-Meteo, already fetched) | A | S | **new item** |
| 4 | **Aerosol/smoke AOD + PM2.5** (CAMS/HRRR-Smoke) | A | M | **new item** |
| 5 | **ECMWF + ML-NWP (AIFS/GenCast) members; NBM prob Tmax** | C/D | S–M | extend forecast layer |
| 6 | **Lake surface temp contrast** (GLSEA) | E | S | extend item 78 |
| 7 | **Continuous-density target + CRPS/PIT scoring** | method | L | **item 35** |
| 8 | Snow/albedo (deferred) | F | S | future northern markets |

Highest expected accuracy-per-effort: **#1 (850T — scaffold exists), #2 (soil
moisture — biggest blind spot), and #3 (shortwave — nearly free).** #5 widens an
already-strong forecast ensemble cheaply; #7 is the strategic methodological move.

These map onto the existing roadmap: **item 32** (reanalysis/synoptic — unblock),
**item 35** (continuous density + CRPS), **item 78** (marine/lake — extend), and
**Track A** data-source items for the genuinely new feeds (soil moisture, shortwave,
aerosol/smoke, ECMWF/ML-NWP, NBM-prob).

---

## Sources

- Rasp & Lerch 2018, *Neural networks for post-processing ensemble weather forecasts*, Mon. Wea. Rev. — https://arxiv.org/pdf/1805.09091
- Taillardat et al. 2016, *Calibrated Ensemble Forecasts Using Quantile Regression Forests and EMOS*, Mon. Wea. Rev. — https://journals.ametsoc.org/view/journals/mwre/144/6/mwr-d-15-0260.1.xml
- Delle Monache et al. 2013, *Probabilistic Weather Prediction with an Analog Ensemble*, Mon. Wea. Rev. — https://journals.ametsoc.org/mwr/article/141/10/3498/71598/Probabilistic-Weather-Prediction-with-an-Analog
- Statistical post-processing review (Vannitsem et al.) — https://arxiv.org/pdf/2004.06582
- 850–700 mb thickness Tmax technique, Wea. Forecasting 1995 — https://journals.ametsoc.org/view/journals/wefo/10/1/1520-0434_1995_010_0160_fmttuo_2_0_co_2.xml
- Soil-moisture/temperature coupling, Nat. Commun. 2025 — https://www.nature.com/articles/s41467-025-56109-0
- Soil moisture & European Tmax extremes, WACE 2015 — https://www.sciencedirect.com/science/article/pii/S2212094715000201
- Clouds/solar radiation & diurnal temperature range, MDPI Climate 2019 — https://www.mdpi.com/2225-1154/7/7/89
- All-sky Tmax ML reconstruction (GLDAS + shortwave) — https://www.sciencedirect.com/science/article/abs/pii/S0169809522003842
- Wildfire smoke temperature anomaly, ACP 2024 — https://acp.copernicus.org/articles/24/6937/2024/
- HRRR-Smoke tutorial, NWS — https://www.weather.gov/mfr/HRRR_smoke_tutorial
- NLDAS (near-real-time soil moisture), Drought.gov — https://www.drought.gov/data-maps-tools/north-american-land-data-assimilation-system-nldas
- SMAP L4 / ERA5-Land fusion, ESSD 2026 — https://essd.copernicus.org/articles/18/1061/2026/
- GLSEA Great Lakes surface temperature, NOAA CoastWatch — https://coastwatch.glerl.noaa.gov/satellite-data-products/great-lakes-surface-environmental-analysis-glsea/
- ECMWF AIFS update — https://arxiv.org/html/2509.18994v1
- GenCast / skillful probabilistic ML forecasting — https://arxiv.org/pdf/2506.10772
- NBM v4.2 probabilistic MaxT, NOAA MDL — https://vlab.noaa.gov/web/mdl/-/nbm-upgraded-to-version-4-2
- ML analog similarity metric — https://arxiv.org/pdf/2103.04530
