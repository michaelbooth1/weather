# Information-gap sources: free untested and paid candidates (proposal, 2026-10-23)

Status: dated proposal for the owner (lane E, workstation). Desk study only: no data downloaded, no account, no key,
no purchase, no quote requested; nothing under `data/` was read. **Nothing here is approved.** Each paid source
needs its own owner decision (owner 2026-10-23: "Paid if needed, bring to me when you think merits it").

- **Owns:** the 2026-10-23 inventory of free sources we have not tested and paid sources worth considering, with a
  measure-before-buying plan and a kill criterion for each paid source on the shortlist.
- **Read when:** proposing a new data source, a paid purchase, or a dev-scorecard screen of a source.
- **Do not use for:** measured results (the [findings digest](../operations/FINDINGS_DIGEST.md) and EF own them), the
  status of a source row (the [exhaustion register](../operations/EXHAUSTION_REGISTER.md) §2 owns it), or the
  provider/licence decision (owned by [forecast-source-and-training-population.md](../operations/forecast-source-and-training-population.md);
  any paid adoption is recorded there as a new dated decision).
- Vendor prices were read from public pages on 2026-10-23. Pages that render prices with JavaScript were read through
  the vendor's own blog or documentation. Where only third-party listings carried a price, the price is marked
  **(3rd-party)**. Every price must be re-checked at decision time.

## 0. What the measured gap says a new source must do

- The gap is information, not calibration (EF §1c). Shrinking toward the market only locates it.
- After the two serving repairs on captured data, the largest residual is **13-16 local: +0.0231 Brier, 1.81x the
  market**. 58% of 15-16 snapshots have not yet rolled over below the running high, so it is a remaining-rise problem.
  00-12 keeps +0.010 to +0.014 (1.18-1.26x) that nothing tested closes (EF §10q; OQ Q-20).
- The lever is the centre, not the width (EF §1, §1g).
- **No external free source added information beyond captured NBM v2 plus the lock-in** (EF §10q): NBH, NBS, MOS/NBE,
  HRRR single and multi-run, ECMWF IFS, soundings at 17-23, NWS revisions, neighbours, cloud. Most of those intervals
  include the 5% bar, so the claim is "no increment demonstrated" (register §1 row 16).
- NBM reaches no served band (EF §10u; lever-5 record). The only free signal that ever helped is station guidance read
  with zero parameters (MG-1) and, at 13-16, a no-source METAR remaining-rise pmf (t3-r3). t3-r3 is
  **freshness-bound**: WEAK at +1 h METAR staleness, NULL at +2 h (EF §10q).
- Training: the free tier is point-in-time (PIT) for 12 of 21 fields. The other 9 are a wall: cloud low/mid/high,
  visibility, soil temperature and moisture, 925/850 hPa temperature and 500 hPa height (EF §0a, §4f). Free history is
  2021-2025 for temperature and 2024-2025 for ten fields (EF §1m).

**So a source earns a test only if it plausibly carries information that the market and NBM v2 lack, about the 13-16
remaining rise or the centre.** The cheapest such information is fresher observations of the settlement station.

**Scoring every screen below.** Run it on Lane C's dev scorecard (`claude/dev-scorecard-20261023`, under construction):
walk-forward, dates ≤ 2026-09-29, crossed date x market clustering.
- Report the paired increment over the matching control: MG-1 for 00-12, t3-r3 for 13-16, served for 17-23.
- Report it per block, with power and MDE.
- The bar is 5% of the block's post-repair gap. It is about -0.0012 at 00-16 (SYN §1.1). At 13-16 it is about
  -0.0012 (5% of +0.0231; derived here, not published).
- A dev screen is a development read, never confirmation. A pass earns a pre-registration on new dates (EF §5).
- The 11 US market clusters cap crossed power near 40% for MG-1-sized effects (EF §10j), so a null at that size is
  "underpowered", not "no effect".

## 1. Free sources

### 1a. Already tested or closed (do not re-run as new)

| Source | Verdict | Cite |
| --- | --- | --- |
| NBM v2 zero-parameter read (MG-1) | Dev lead; forward read signed | EF §10q; register S1 |
| NBM at all hours | Closed: afternoon harm | EF §10p |
| NBH, NBS, MOS/NBE, HRRR (single, multi-run), ECMWF IFS via Open-Meteo | No increment over MG-1 (NBS a precise null; the others underpowered) | EF §10q; register S3-S7, S10 |
| Open-Meteo Previous Runs, the 11 extra PIT fields | Tested-underpowered x3; pooled refit worsened the centre | EF §1m; register S15 |
| NWS gridpoint, NWS revision direction | Underpowered kernel; revision direction beaten by a placebo | EF §10h; register S16-S17 |
| Neighbour METAR, 12Z soundings (17-23 only), GOES/METAR cloud | Underpowered | register S23-S25 |
| METAR remaining-rise (t3-r3) at 13-16 | Dev lead, fragile; D2 unsigned | EF §10q; OQ Q-19 |
| Climatology / persistence standalone | Harm at 13-23 | register S28 |
| 1-minute ASOS as a settlement label or target | Harm (target); rounding null | register S20 (T16) |
| Intraday tail, METAR live signal stages | Structurally inert | EF §10u |

### 1b. Genuinely untested, ranked by fit to the gap

"Parity" means the train/serve feature-parity contract; "PIT" means the value as known at the cutoff.

| # | Source | Information it could add (block) | PIT availability and history | Parity feasibility | Cost to integrate | Dev-scorecard screen |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | **High-frequency ASOS of the settlement station** (1-min archive via IEM/NCEI; real-time 5-min "HF-METAR"/1-min via MADIS; register S20 as an *input*) | **13-16.** It shrinks the running-max staleness that t3-r3 dies on (hourly METAR is up to ~60 min old) and catches a peak between routine reports. | Archive: free, public domain, US ASOS from 2000. It is **18-36 h delayed** (NCEI monthly files), so it serves training only. The real-time path is MADIS (free; account by the owner, signup list #6). MADIS distribution category for 1-min ASOS is **unverified**. | Hard part: 5-min/1-min products carry **whole °C**, METAR T-groups carry tenths. Train on the archive degraded to the serve product's resolution and latency. | Low for the archive reader; medium for a real-time MADIS collector (owner signup + master capture) | Rebuild t3-r3's running max at 5-min cadence from the 1-min archive with a simulated 5-10 min latency. Score it against hourly-METAR t3-r3 at 13-16, 11 US markets. **This one screen decides whether any paid observation feed is worth discussing (§3 P1).** |
| F2 | **MRMS radar** (captured, never scored; S26) | **13-16.** Convection onset caps the afternoon rise. | Captured on the host from some date (start not traced here). Free archive deep (NOAA open data). | Captured stamps make parity straightforward. | Lowest: already captured | Add an "echo within R km in the last 30 min" flag to t3-r3's pmf conditioning, 13-16. |
| F3 | **12Z sounding mixed-layer / inversion as an afternoon-cap signal** (S24 at 00-16 never tested) | **13-16 and centre** | Free RAOB archive (IEM), decades; 12Z is available ~13Z, before the block | Easy (issue time explicit) | Low | Mixed-layer potential-temperature cap vs running max as a t3-r3 conditioner, 13-16. |
| F4 | **Per-model Open-Meteo members** (ICON, AIFS, AIGFS, GraphCast, GEFS alone; S11, S12, S29, L21) | Centre, 00-12 | Captured inside the served consensus vote. Previous Runs history only for models Open-Meteo archives. | Captured, so parity holds forward | Low | Score each member's own increment over MG-1 at 00-12 on held data. Low prior: IFS already failed. |
| F5 | **ECMWF ENS open data** (CC BY 4.0; the whole real-time catalogue is open since 2025-10-01) | Centre and spread, 00-12 | **Forward only.** The free archive is not open (see §2 P2). | Forward capture keeps parity by construction | Medium (GRIB fetch, member extraction, ~daily volume unmeasured) | Shadow-capture ≥ 45 dates, then ENS member quantiles vs MG-1 at 00-12. Needs new dates, so it cannot use the dev scorecard. |
| F6 | **Toronto GEM/HRDPS and ECCC citypage alone** (S13) | Centre, all blocks, **Toronto only** (no NBM there) | Captured citypage; gridded readers exist | Captured | Low | First Toronto guidance control: a zero-parameter read of the citypage vs served. |
| F7 | **RAP / RTMA / URMA / HREF** (S8, S32) | RTMA: current state (duplicates METAR). HREF: convective-allowing 2 m T max, 13-16. | Free real time. Archive depth on the NOAA cloud buckets **unverified**. | HREF issue times are explicit | Medium | HREF max-T and convection probability vs t3-r3 at 13-16. Low prior: HRRR already failed. |
| F8 | **Area Forecast Discussion text** (S18) | Forecaster's centre and bust risk, 00-12 | Free IEM text archive with issue times, deep | Easy | Medium (text features) | Keyword flags for "warmer/cooler than guidance" vs MG-1. Lowest prior. |
| F9 | **TAF TX/TN** where issued (KBKF yes; LFPB likely; NWS civil no) | Centre at one or two stations | Free AWC cache; IEM TAF archive | Easy | Low | Too few stations for a fleet screen; record only. |
| F10 | Marine refresh (S27), coastal markets | 13-16 sea-breeze cap | Sidecar dark since 06-13 | Needs refresh scheduling | Low-medium | Owner call only (register order 13). |

**Europe-first cities (London EGLC, Paris LFPB, Munich EDDM, Madrid LEMD).** These cities have no served model, no
capture of guidance and no test of anything (register §2, L9). Every source is untested there, and the free options
are better than any paid one:
- **DWD MOSMIX.** Station MOS for all four airports; all four are exact catalogue matches (S0(e)). It is the European
  analogue of the one free signal that worked (station guidance). Licence CC BY 4.0. The open server keeps recent runs
  only, so this is forward capture; archive depth is **unverified**.
- **Met Office DataHub site-specific blended probabilistic forecast** (London). Free plan: 55 calls/day.
- **Météo-France 6-minute observations** (Paris). The portal key keeps 24 h of real-time data; the climatological
  6-minute archive is on data.gouv.fr under Licence Ouverte 2.0, from 2005 at the earliest.
- **DWD 10-minute observations** (Munich). The `now` directory updates hourly.
- **AEMET OpenData** (Madrid). Terms not read here.

European METAR is half-hourly, so the staleness argument in F1 is weaker there.

## 2. Paid candidates

Honest prior: most paid products **re-package the same public NWP** that §1a already found adds nothing. A paid source
earns a case only when it carries something the free tier cannot: fresher station observations, a genuine PIT archive
past the 9-field wall, or more history depth.

| # | Provider and product | Published price and terms | Coverage: 11 US / London, Paris, Munich, Madrid | History depth for a PIT backfill | Expected gain, tied to the gap | Cheap first measurement | Licence points |
| --- | --- | --- | --- | --- | --- | --- | --- |
| P1 | **Synoptic Data**, commercial Weather API including HF-ASOS (1-min) and HF-METAR (5-min). Synoptic is the backend of the US resolution page (`weather.gov/wrh/timeseries`). | **No published price; quote only.** 14-day free trial (needs signup). Open Access is free but `.edu` and non-commercial, so we do not qualify (signup list). The owner declined a free WRH token on 2026-10-16 (DL); a commercial account would be a different decision. | US: strong (ASOS plus aggregated mesonets). Europe: global METAR only; nothing beyond free METAR. | HF-ASOS: Synoptic says it has received full 1-minute data since 2019, but the feed was **unavailable from its source Oct 2023 - Jan 2026**. It is labelled experimental, and multi-day outages are "not uncommon". **It cannot backfill our training window;** the free NCEI/IEM archive must do that. | **13-16 only.** It is the paid route to F1's mechanism: latency 2-5 min, whole °C. If F1 shows freshness has value, the free MADIS route probably delivers the same data. Mesonet density is the neighbour family, already underpowered (S23). | F1 (free) first. Then MADIS (free). The trial only if MADIS fails on latency or coverage. | Quote-specific; resale or redistribution typically excluded (**unverified**). |
| P2 | **ECMWF archive (MARS) access, commercial**: HRES/ENS historical forecasts | Archive Web-API access **3,000 EUR/year** for commercial users; ECMWF may waive it for research or societal benefit. Delivery service charges are extra. A 50% small-business discount is reported on ECMWF's catalogue pages (**unverified**). Real-time data is CC BY 4.0 with no information cost since 2025-10-01. | Global: all 11 US and all four EU cities | **Decades, PIT by construction** (each field is stamped with its run time). It includes the walled fields: 850/925 hPa temperature, 500 hPa height, cloud layers, soil moisture. | **Training, not new information.** It breaks the 9-field wall and the 2021/2024 depth limits, so it serves the retrain lane (register L7; waived for the 12-21 decision) and an ENS spread feature. Against it: the 11 extra free PIT fields were underpowered three times and never harmful (EF §1m), and IFS-via-Open-Meteo had the wrong sign (EF §10q). Expected gain is small unless F5 (ENS forward, free) shows an increment. | F5 forward capture, free, ≥ 45 dates | CC BY 4.0 for real-time data. Archive licence terms for derived products and automated use **not read**. |
| P3 | **Visual Crossing** Historical Forecast add-on (Timeline API) | Pro $35/month, Corporate $150/month, metered $0.0001/record with 1,000 records/day free (vendor blog and docs; plan table **3rd-party**). The historical-forecast add-on fits any plan. Commercial use allowed; raw-data resale prohibited; attribution required on Pro. | Global | **From 2020-01-01; one stored run per day (00Z).** Variable list not published. | Low. It is one year deeper than Open-Meteo Previous Runs, but a single 00Z blend of public models, and its 00Z snapshot misses the morning cycles that carry MG-1. Duplicative. | Free 1,000 records/day after an owner signup | Commercial use allowed; resale prohibited |
| — | **Meteomatics** (multi-model API; historical forecasts in the Business package) | Business: quote only. Free Basic is non-commercial: 500 queries/day, 15 parameters, 24 h of history. 14-day trial: 1,800 parameters, history only a 6-month subset on request. | Global | Business tier claims history to 1940 "including historical forecast"; first-availability evidence unverified | Re-sells ECMWF, ICON, AROME, UKMO and HRRR, which are free or already tested. Duplicative. | Trial | Non-commercial free tier |
| — | **Tomorrow.io** (proprietary nowcast and blend) | Quote only. Free: 500 calls/day, no history. Premium archive 2000-present, priced per request. | Global | Archive is reanalysis-like history; PIT forecast archive not documented | Nowcast is unproven for daily-max centre; no PIT archive, so no train/serve parity. | none useful | Quote-specific |
| — | **IBM / The Weather Company** (WU's owner; History on Demand) | Quote only. History on Demand: 35 km grid, hourly from July 2011. | Global | Gridded history, not PIT forecasts | WU history for METAR airports is METAR-derived, which we have free. A licence would only legitimise WU live access for WU-settled cities (Madrid, Munich): a settlement-parity question, not information. | n/a | Quote-specific |
| — | **Open-Meteo commercial** | $29 Standard / $99 Professional per month (Open-Meteo's own blog); historical and Previous Runs APIs need Professional. CC BY 4.0. | Global | Same data as the free tier | **None.** It fixes the non-commercial licence risk the owner accepted (2026-08-05), not information. A separate licensing decision. | n/a | Commercial licence |
| — | **Met Office DataHub paid tiers** (London) | Site-specific blended probabilistic: free 55 calls/day, then £9-£10,429/month. Global spot: free 360 calls/day, then £9-£437/month (ex-VAT). No archive of past forecasts listed. | London only (spot is global) | None listed | The free tier covers 55 calls/day for one site, which is enough for EGLC capture | Free tier | Proprietary licence; "Powered by Met Office data" |
| — | **Lightning** (Vaisala GLD360/NLDN, Earth Networks ENTLN) | Quote only (no public prices found) | US and EU | Deep, but expensive | Afternoon convection is a 13-16 cap, but free MRMS (F2) carries the same mechanism and has never been scored | F2 first | Not read |
| — | **Commercial station networks** (Earth Networks/WeatherBug, PWS) | Quote only | US dense | Varies | The neighbour family is underpowered (S23); PWS siting does not match the settlement instrument | Neighbour METAR already tested | Not read |

## 3. Ranked shortlist (paid): two candidates, both conditional on a free screen

Only two paid sources meet the bar of plausibly adding information the free tier cannot. Both are **gated on a free
measurement**; if that measurement fails, the paid case dies without spending anything. No third candidate merits a
proposal: P3 and the rest duplicate free or tested data (§2).

### 1. Synoptic Data commercial HF-ASOS/HF-METAR (price: quote only)

- **Why:** it attacks the 13-16 residual (1.81x) through the one mechanism with a dev signal, the freshness of the
  station's running maximum, and it is the provider behind the US resolution page.
- **Measure before buying:**
  1. **F1 screen**, free, on the dev scorecard, dates ≤ 09-29: t3-r3 rebuilt from the IEM 1-min archive at 5-min
     cadence, with a simulated 5-10 min latency and whole-°C rounding, against hourly-METAR t3-r3 at 13-16.
  2. If F1 passes, the owner signs up for MADIS (free, public category). Measure real-time latency and fill for the
     11 stations for 14 days.
  3. Only if MADIS cannot deliver: propose the 14-day Synoptic trial (the owner signs up), then ask for a quote.
- **Kill criteria:**
  - The F1 increment's crossed interval does not exclude the -0.0012 bar at 13-16. That kills every paid observation
    feed.
  - Or MADIS delivers the 5-min product at median latency ≤ 10 min on ≥ 10 of 11 stations. Then the free route
    suffices and P1 is never bought.

### 2. ECMWF archive access (3,000 EUR/year commercial, plus delivery charges)

- **Why:** it is the only route found to a genuinely PIT forecast archive past the 9-field wall and the 2021/2024
  depth limits, for all US and EU cities.
- **Measure before buying:**
  1. **F5**: shadow-capture free ECMWF ENS open data (CC BY 4.0) for ≥ 45 new dates. This needs master and the owner
     for capture; check the roll verdict.
  2. Score ENS member quantiles and the walled fields that the real-time open set carries (850 hPa temperature, cloud
     layers) as increments over MG-1 at 00-12 and over t3-r3 at 13-16, under a pre-registration.
  3. Buy the archive only if that passes **and** a retrain lane is scheduled to consume it.
- **Kill criteria:**
  - Neither block's increment interval excludes its 5% bar after 45 dates.
  - Or no retrain lane is scheduled by the time of the read (item 339 has waived the retrain for the 12-21 decision).
    The archive buys training depth only, so without a consumer it buys nothing.

## 4. Owner decisions proposed

1. **Approve the F1 free screen** (1-min ASOS freshness emulation, dev scorecard, dates ≤ 09-29, no purchase). It is
   the gate for P1 and the highest-value untested free source for 13-16.
2. **Approve the cheap free screens on data already captured:** F2 (MRMS), F3 (soundings at 13-16), F4 (per-model
   members) and F6 (Toronto citypage). They cost nothing new and use no paid data.
3. **Pre-approve the owner's MADIS public-category signup** (already signup list #6), conditional on F1 passing.
4. **Approve free forward capture as shadow columns:** ECMWF ENS open data (F5, gates P2) and DWD MOSMIX for the four
   Europe-first cities plus the US stations. Master schedules it under the roll verdict.
5. **Defer both paid purchases** to the reads above. They come back to the owner only with a passing free screen.
6. **Decline for now:** Meteomatics, Tomorrow.io, TWC/IBM, Visual Crossing, paid lightning, commercial station
   networks, and paid Met Office tiers (as information sources). Open-Meteo commercial is a separate licensing
   question, not a model lever.

## Sources read (public pages, 2026-10-23)

- Synoptic pricing and Open Access: https://synopticdata.com/pricing/ ; HF-ASOS: https://docs.synopticdata.com/services/high-frequency-asos
- ECMWF data pricing and service charges: https://ecmwf.int/en/forecasts/accessing-forecasts/payment-rules-and-options/tariffs ;
  open real-time catalogue (2025-10-01): https://www.ecmwf.int/node/29328
- Visual Crossing plans: https://www.visualcrossing.com/weather-data-editions ; historical forecasts:
  https://www.visualcrossing.com/resources/documentation/weather-data/how-to-query-weather-forecasts-from-the-past-historical-forecasts/ ;
  cost blog: https://www.visualcrossing.com/resources/blog/what-will-my-weather-data-cost/
- Open-Meteo plans: https://open-meteo.com/en/pricing ; prices: https://openmeteo.substack.com/p/api-subscriptions-for-commercial
- Met Office DataHub site-specific pricing: https://datahub.metoffice.gov.uk/pricing/site-specific
- Meteomatics free and trial tiers: https://www.meteomatics.com/en/api-entry-level/
- Tomorrow.io archive coverage: https://support.tomorrow.io/hc/en-us/articles/38449008659220-Weather-Timeline-Historical-and-Forecast-Coverage
- IEM 1-minute ASOS: https://mesonet.agron.iastate.edu/request/asos/1min.phtml ; MADIS 1-min ASOS: https://madis.ncep.noaa.gov/madis_OMO.shtml
- Météo-France observation API: https://portail-api.meteofrance.fr/web/fr/api/DonneesPubliquesObservation ; DWD 10-min:
  https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/
- In-repo: [S0(e)/(f) stations and licences](data-layer-v2-s0-2026-10-15/s0ef-stations-and-licences.md),
  [free-registration sign-up list](../operations/free-registration-signup-list.md).
