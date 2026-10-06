# Missing-information research swarm — 2026-10-02

- **Owns:** the 11-agent study of what information the forecast lacks, where it lives, latency and cost (free sources; paid flagged only).
- **Read when:** choosing forecast-data work (NBH/NBS, METAR cadence, Toronto blocks, T+1/T+2 measurement).
- **Do not use for:** current state ([STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)) or decisions in force ([DECISION_LOG](../../operations/DECISION_LOG.md)).

Read-only agents; no exam-blackout data read; numbers are MEASURED only where marked. Owner decisions are in DECISION_LOG.

## Synthesis

**Verdict:** The missing information is *fresher, station-specific NWP centre* (morning) and *sub-daily NWP plus near-real-time observations* (afternoon), all of which exist free in files production already touches; the honest ceiling from public sources is parity with the market (Crosier: the best blend of six public products beats the market by only 3.1% RMSE), not an edge, and nothing PAID was found that sells information the free feeds lack.

## A. What is missing, ranked by recoverable loss

| # | Slice | Gap (MEASURED) | Recoverable (ESTIMATED) | Information kind, where it lives |
|---|---|---|---|---|
| 1 | Morning 06:00-10:00, modal band, T+0 | ratio 1.44-1.48 (79a); hours 06-09 carry the largest hourly gaps; 4.4% of rows carry 64% of excess (EF §1:412) | NBM-percentile read beats served by 0.012-0.015 Brier, ratio → 1.15-1.22, ~half the morning gap (EF §10h, §10j:3331-3334) | Fresher station NWP: NBH hourly bulletin (+54-73 min), NBM 07Z, GEFS/ENS 06Z/12Z cycles. Not yet selected by any artifact (EF §10h:3293) |
| 2 | Afternoon 13:00-17:00, T+0 | ratio 1.72-1.79; ≥50% of signed excess at/after noon; PM−AM +0.28-0.33 (79a:64-70); guidance 5-24 h stale by construction (EF §10l:3402) | unsized; only sub-daily NWP and obs can act; market jumps on METAR minutes (95a: 1.18x), not bulletins | NBH hourly TMP+TSD, HRRR 2 m TMP (+53-74 min), NWS API 5-min station rows (~18 min lag), decidedness clock (89b Brier 0.042) |
| 3 | Out-of-season centre | C−B −0.83 C-eq [−1.44,−0.22]; served 1.526 vs 1.423 (EF §2:1468-1478) | refit proxy 24.9% [−20.5,+55.2] (EF §1d:738) | Training coverage: free Open-Meteo history 2021-2025 (EF §1m); workstation only |
| 4 | T+1/T+2 bands | UNMEASURED; all four RE-1 fills landed here (EF §10m:3446) | unknown; maker P&L sign depends on it | Pre-day NWP: NBS/NBX, GFS 00Z (+3.9 h), ECMWF IFS mx2t3 (+7.5 h), ENS 51 members |
| 5 | Toronto | zero guidance; replay fails L1 0.00702 (EF §1k:1307) | unknown | NBH/NBS/NBP all carry CYYZ/CYTZ blocks; refused by our own gate `src/weather/model/model_sources.py:1704-1708`, `:2029-2032` |

Not recoverable or closed: calibration ≤16.5% (interval includes zero, §1c:633); settlement mechanics ≤3.4% of market-days (§10h:3289); band reshaping (§1g); regime tags (power 26.6% at OR=2, §1f:895-899); width (centre, not width, §1g).

Honest ceiling (MEASURED, two independent lines): full replacement by the market closes 85.6% of the gap (§1c:665), so ~14% of the gap is noise even the market does not price; and Crosier (7,590 city-days, arXiv 2609.23969) finds the optimal blend of NDFD/NBM/LAMP/MOS/HRRR/ECMWF beats the market by 3.1% at open, with NBM moving toward the market 4x more than the reverse. Everything below targets ratio ~1.0-1.1 from 1.42, not below 1.0. Any single fix must close ≥~5% of the gap to clear the 12-market MDE floor (§1d:716-750).

## B. Candidate sources

| Source | Gap targeted | Latency | Cost | Ingest (req/day, stored) | Effort | Risk | Host |
|---|---|---|---|---|---|---|---|
| **NBH text** (`noaa-nbm-grib2-pds` `blend_nbhtx`, hourly TMP+TSD h1-25, all 12 incl. CYYZ) | 1, 2, 5 | +54-73 min after cycle (MEASURED) | free | 24 req, 0.7 GB transfer, <1 MB stored as station blocks | low (text regex, existing NBP CAS path) | **repeats the 24.9 GB/15 h NBP fan-out (EF §10l:3407) unless fetched per cycle** | capture |
| **NBS text** (3-h, h6-72) | 4, 5 | +56 min | free | 4-8 req, <1 MB | low | TXN blank for today after 12Z (same as NBP) | capture |
| **NWS API 5-min obs** (`api.weather.gov/stations/{icao}/observations`) | 2 (timing/decidedness) | ~18 min MEASURED once; 5-min rows precede the :51 METAR by 15-45 min | free, public domain | 11×288 = 3,168 req, ~10 MB raw, <0.5 MB stored | low | whole °C (±0.9 °F); KBKF absent; 8 stations UNVERIFIED; rate limit unpublished | capture |
| **METAR cadence 10→2-5 min** (existing `aviationweather.gov` call, `model_sources.py:1354`) | 2 | 1-3 min | free | 5x current, ~15 MB/day | trivial | ≤1 req/s guidance | capture |
| **HRRR 2 m TMP by `.idx` byte-range** (`noaa-hrrr-bdp-pds`) | 2 | +53-74 min | free | ≤12×1.2 MB/cycle, 0.35 GB/day, KB stored | medium | **no `wgrib2` on capture host** (`grib_probe.py:388-390`) | workstation |
| **GEFS/ECMWF ENS via Open-Meteo** (already captured, `model_sources.py:2135-2218`) → EMOS station Tmax | 1, 3, 4, 5 | 06Z/12Z cycles land ~18-20Z | free, 10k calls/day | 0 new req; ~MB/day | low-medium | ensemble mean is a cold, 0.044-weight input today (`forecast_error_model.json:241-256`) | either |
| **Dynamical GEFS archive** (2020-10→, 00Z, `maximum_temperature_2m`, S3 Zarr) + Open-Meteo history 2021-25 | 3 (training seasons) | n/a | free, CC-BY | one-off, point reads KB-MB/init | medium | `data.dynamical.org` endpoint ended 2026-09-30; use `s3://dynamical-*` | workstation |
| **MADIS HF-ASOS 1-min** (account via Data Application Form) | 2 (maker timing) | 2-5 min | free, registration | 288 req, ~1 MB | low-medium | whether an individual gets an account UNVERIFIED; experimental, outages | capture |
| **ECCC HRDPS** (Toronto, 2.5 km) | 5 (T+1) | +3 h | free | 24×3.5 MB | medium | too stale for T+0 afternoon; already proxied via `gem_seamless` | workstation |
| **ECMWF IFS mx2t3 / AIFS open data** | 4 | +7.5 h / +5.8 h | free (CC-BY since 2025-10-01) | ~500 ranged req, 0.5-1 GB | medium | needs eccodes; Open-Meteo `ecmwf_ifs025` gives the same points in 5 KB | workstation |
| GOES ACM cloud mask / GLM / MRMS / RTMA-RU | 2 (cloud arrival, outflow) | 3.4 min / 27 s / 3 min / 15.6 min | free | 1-2.5 GB/day transfer per satellite set | high | unpowered regime claims; GRIB decode absent; MRMS poll already writes 100-200 MB/day of dead listing (audit finding 9) | workstation only |
| Synoptic commercial, NYS Mesonet ($250/station/mo), WindBorne, Jua, Meteomatics (~$500/mo), TWC ($500/mo) | PAID, information only | — | PAID, quote-only | — | — | repackaged NWP/obs except WindBorne/Jua (unquantified for station highs); repo forbids (`model_constants.py:19`) | — |

## C. Recommended top 3 free experiments

**1. NBH hourly station guidance as the all-hours centre (slices 1, 2, 5).**
*Estimand:* paired Brier ratio vs market on T+0 band rows, strata 06:00-09:59 and 13:00-16:59 local, for a served-plus-NBH read (remaining-day max = max(running max, NBH hourly TMP to local sunset), width from TSD) vs the served model. *Data:* new dates from 2026-10-15; if the `noaa-nbm-grib2-pds` bucket retains dated `text/` files (UNVERIFIED), a PIT backfill of September is admissible because bulletin bytes are immutable. *Success:* afternoon ratio ≤1.35 (from 1.72-1.79) and morning ≤1.25, each with the paired CI excluding zero; secondary: ≥5% of the total gap, the confirmability floor. *Falsifier:* paired PM difference CI includes zero, or NBH does no better than the 07Z NBP read at 13:00-17:00 (the "market trades obs, not bulletins" hypothesis). *Cheapest first step:* once 83b's cycle-level fan-out lands, fetch `blend_nbhtx.tHHz` once per hour, extract 12 station blocks (<1 MB/day), log them beside NBP in the CAS. Precondition is the fan-out fix, not new budget.

**2. Five-minute station rows plus the 89b decidedness clock (slice 2, maker timing).**
*Estimand:* (a) fraction of 95a-style large mid moves at METAR minutes that are preceded by a 5-min row crossing the band boundary; (b) Brier of "final degree already printed" with 5-min rows vs METAR-only (89b baseline 0.042). *Data:* new dates from 10-15 only (no retained 5-min bytes exist; production METAR store stopped 06-30). *Success:* ≥60% of large moves preceded by ≥10 min, and decidedness Brier ≤0.035. *Falsifier:* 5-min rows lead the market <50% of the time, or whole-°C rounding makes band crossings ambiguous on >20% of events. *Cheapest first step:* one `limit=12` call per station per 5 min (3,168 req/day, <0.5 MB stored); first confirm availability for KATL/KAUS/KORD/KHOU/KLAX/KMIA/KSEA (only KLGA/KDAL/KSFO verified; KBKF absent). Pair with the stale WU-era `LIVE_FLOOR_HEDGE` (`model_distribution_signals.py:275-308`) as a bundled pre-registration.

**3. Multi-season refit on the workstation (slice 3) with a first T+1/T+2 and Toronto measurement riding on it.**
*Estimand:* out-of-season C−B centre bias and served/market ratio after retraining on free Open-Meteo history 2021-2025 plus dynamical GEFS 00Z `maximum_temperature_2m` (2020-10→) through the existing EMOS-style per-source kernel. *Data:* training on archived seasons; scoring on new dates from 10-15 (out-of-season now, so this is the right calendar). *Success:* out-of-season ratio 1.526 → ≤1.42 (in-season parity) with proxy closure ≥15% and CI excluding zero. *Falsifier:* closure CI includes zero (the 24.9% [−20.5,+55.2] proxy was already unpowered), or train/serve parity gate fails. *Cheapest first step:* zero capture-host cost; the T+1/T+2 model-vs-market Brier can be computed today from existing maker bands and NBS/GFS captures without any new feed.

## D. What not to pursue

- **PAID vendors.** Every retail product monetises latency to the settlement sensor (wethr $14.99-99/mo, WeatherEdgeFinder $99.99/mo), which NWS API/MADIS give free; the rest is repackaged GFS/HRRR/ECMWF/NBM. WindBorne and Jua are the only non-repackaged claims and are unquantified for station highs. Repo contract stands.
- **GOES/GLM/MRMS/RTMA on the capture host.** No decoder, memory-gated, 1-2.5 GB/day transfer; regime claims are unpowered (AUROC 0.548, 79a power 26.6%). Workstation research only, after a tagged panel exists.
- **Settlement mechanics as a forecast lever.** Ceiling ≤3.4% of market-days, below the MDE floor; the venue `:51-:59` filter affects 2.26% of station-days. Keep only as a bundled pre-reg (hedge removal, pre-07:00 prints).
- **Width, calibration, band reshaping, global sharpening.** Closed in canon.
- **Kalshi mid as an input.** Different settlement window (CLI, 01:00-00:59), and it is the market's information, not ours.
- **Sub-hourly HRRR, RRFS, NBM qmd.** 4x bytes for nothing on a daily max; RRFS later and larger; qmd posts +8 h, 572 MB.
- **NYS Mesonet, CWOP/PWS, WU PWS API.** PAID or uncalibrated or ToS-barred.

## E. Owner decisions needed

1. **Land 83b's cycle-level fan-out before any new national bulletin** — yes; it is the precondition for NBH/NBS and prevents a second 24.9 GB incident.
2. **Allow per-cycle NBH (24/day) and NBS (4-8/day) capture on the capture host, station blocks only** — yes.
3. **Remove the `:US` gate on NBM guidance for Toronto** (`model_sources.py:1704-1708`, `:2029-2032`), behind a flag — yes; the data is already in the file we download.
4. **Stop the MRMS listing poll** writing 100-200 MB/day of dead S3 listing into `replay_inputs.jsonl` — yes, before anything else is added.
5. **Raise METAR cadence to 2-5 min and add NWS API 5-min polling** (~3,500 req/day, <1 MB stored) — yes.
6. **Install `wgrib2` on the workstation only** for HRRR/ECMWF point extraction — yes; never on the capture host.
7. **Apply for a MADIS HF-ASOS account** — defer until experiment 2 shows the NWS API lag is the bottleneck.
8. **Run the multi-season refit and the first T+1/T+2 Brier on the workstation** — yes, now; no capture cost.
9. **Any PAID probe** — no; if ever, WindBorne/Jua only, quote-first, bounded.

Plain statement of the ceiling: free sources can plausibly take the morning ratio to ~1.15-1.2 and the afternoon down from ~1.75, closing perhaps half the in-season gap and reaching parity on good days; the evidence does not support a free path to beating the market on T+0, and the maker's economics on T+1/T+2 remain unmeasured until decision 8 runs.

## Critic

**Verdict:** The synthesis is directionally sound on NBM fan-out and Toronto, but its afternoon claim (experiment 1) rests on a Tmax construction that cannot work, its headline morning gain quotes the conditional 79a number canon already superseded with 81a, its "ceiling" leans on an external paper absent from canon, and it misses that settlement is now the WRH *hourly* table.

1. **Most likely wrong: experiment 1's afternoon target (ratio 1.75 → ≤1.35 from NBH).** NBH carries hourly instantaneous `TMP`/`TSD`, no MaxT; max-of-hourly undershoots the true daily max and `TSD` is per-hour spread, not the distribution of the running maximum. Canon says the afternoon gap is where the market trades observations, not bulletins (OPEN_QUESTIONS.md:23, 95a: METAR ±2 min catches 1.18x large moves on T+0; NBM/GFS/HRRR pulls ≤ baseline). A +54-73 min bulletin is older than the obs the market already priced. Closing ~55% of the afternoon gap has no evidence anywhere.

2. **Morning gain is overstated against canon.** "0.012-0.015 Brier, ratio → 1.15-1.22, half the morning gap" is the 79a *conditional-on-fill* read (EF:3283-3287). The pre-registered all-rows read 81a halved it to −0.0067 / 1.36x, below the frozen minimum-effect falsifier, with power capped near 40% by 11 market clusters (EF:3330-3336). Success criterion "morning ≤1.25" re-registers a falsifier that already fired; the digest forbids re-registering an unchanged gate.

3. **The "honest ceiling" is UNVERIFIED.** "Crosier, arXiv 2609.23969, 7,590 city-days, 3.1%" appears nowhere in FINDINGS_DIGEST, EF, or RF; it is a point-forecast RMSE claim on an unnamed venue, not a band-Brier ratio on our 12 markets. Present it as external, unweighed input, not a ceiling. The "14% is noise even the market does not price" reading of 85.632% is wrong: that figure is full replacement *on the disagreement set only* (EF:659-660); the remainder is rows outside that set.

4. **Experiment 3 contradicts the nearest measured attempt.** The 12-field pooled refit "worsened the C-pre centre and may not be replicated" (digest, EF §1m), and stitching history into training "re-creates a named contamination defect" (EF §0a, §4f). The 24.893% proxy is [−20.5, +55.2] (EF:734). Decision 8 "yes, now" is a call to repeat an unpowered, once-negative experiment; at minimum it needs the §1d MDE re-derived for its own effect field (EF:741-744).

5. **Missed: settlement is the WRH "Hourly Data" table.** EF:3203-3206: current Rules resolve on the page's hourly rows, exact-degree agreement post-switch unmeasured, and the code still hard-codes WU. If the venue pays on hourly rows, 5-min NWS rows and MADIS 1-min cannot change the settled value; experiment 2's "5-min row crosses the band boundary" can lead the market into a crossing that never settles, and the model's target should be max-of-hourly-obs, which is a different, lower quantity than the forecast Tmax. This is a bigger, unmeasured lever than "settlement mechanics ≤3.4%" (that bound measured station-max vs bucket, not hourly-vs-continuous).

6. **Experiment 2's falsifier is structurally pre-fired for Fahrenheit markets.** Whole-°C rows are 1.8 °F steps against 1 °F bands; ambiguity is not a ">20% of events" risk but the default for 11 of 12 markets. The existing METAR T-group has tenths; raising METAR cadence (decision 5a) is the only part that survives.

7. **Missed: T+1/T+2 information events are NWP publish times, and canon already shows it.** The only informed fill was Miami 75 YES placed 36 min after the 00Z GFS (EF:3446-3447); 95a says fixed clocks beat METAR on T+1/T+2. The synthesis lists slice 4 as "unknown" and omits that the maker should pull quotes at 00Z/06Z/12Z/18Z GFS/ECMWF availability — free, already captured, no new feed.

8. **Missed: market microstructure as *input* for the maker.** Book/flow tape (377,104 trades) exists; using mid or imbalance for quote centring is legitimate for pillar B even though it is forbidden as a scoring route (EF:663-667). The synthesis rejects "Kalshi mid" only and never considers own-venue flow.

9. **Rule-breach risk: "PIT backfill of September" from the NBM bucket.** September ends 09-30, inside the forbidden exam window (UTC 09-30..10-14); any backfill must stop at 09-29 and the retention claim is UNVERIFIED. Also no α-ledger rows are proposed; the digest requires the row before scoring.

10. **Toronto claim half-verified.** `model_sources.py:1704-1708` is the NBP gate (confirmed); `:2029-2032` gates Open-Meteo `/v1/gfs`, not NBM text. That NBH/NBS carry `CYYZ` blocks is asserted, not shown in repo evidence; verify one bulletin before promising decision 3.
