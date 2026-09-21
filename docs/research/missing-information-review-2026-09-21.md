# What information does the market have that we do not? — review, 2026-09-21

Status: hypothesis ranking from the canonical record. **Nothing here is measured.** The owner unpaused model work on
2026-09-21; the five checks are specified in `missing-information-test-plan-2026-09-21.md` and delegated by workstation
handoff `2026-09-79a`. **Correction made after this was written:** station guidance (NBM percentiles, NWS grid high, HRRR
delta) is already captured in `features_long.csv`, so candidate B reads "we hold it and do not use it", not "we lack it".

## What the record already says about the shape of the gap (EF = ESTABLISHED_FINDINGS)

1. 98.88% of the gap is resolution, not reliability: the market separates days we cannot. Recalibration ≤ 16.494%. EF §1c.
2. 4.387% of band rows carry 64.140% of excess loss; that tail is **confident, wrong centre**, and is predictable ex ante
   (AUROC 0.90260): we can tell *when* we will be wrong, not *which way*. EF §1f, §1g.
3. On rows where we disagree with the market by ≥ 0.30, replacing us with the market closes 85.6% of the gap. EF §1c.
4. Repairing 9 of 10 blind live features moved the ratio 1.423260 → 1.423246. The information is not in the features we
   already defined. EF §4.
5. Cool bias −0.64387 C-eq, caused by seasonal training coverage; forecast archive has no July/August. EF §2, §4a-bis.
6. Since 2026-06-30 every capture carries empty `wu_history`, `wu_current`, `weather_forecast`; by code trace 13 of ~26
   serving stages, **including all five late-day lock-ins**, do nothing. EF §10e.
7. The venue settles on `weather.gov/wrh/timeseries?site=<icao>` since ~2026-08-23; that string appears nowhere in `src/`. EF §10c.
8. `forecast_high` is not point-in-time; the PIT source stops 2026-06-23; the free tier offers 12 of 21 PIT fields. EF §0a, §1e, §4f.
9. `high_so_far` is not a running maximum because the vendor series drops rows. EF §1k.
10. An NBM probabilistic-Tmax adapter exists (item 190) but has no durable payload capture and zero selected columns.
11. Marine features went dark (coastal markets).

## Candidates, ranked by (fit to the shape above) × (free) × (big enough to clear the 3.2% panel floor)

### A. The settlement instrument itself, at native cadence and precision — most likely
The market is a bet on one ASOS thermometer, read through one public page. Traders watch that page. We see roughly
hourly METAR and, since 06-30, nothing from the settlement feed. What they have that we lack: 5-minute observations, the
running maximum at the instrument's own precision, METAR remark groups (T-group tenths, 6-hour max), the daily climate
report, and the known rounding behaviour of the timeseries page (5-minute temperatures are whole °C converted to °F, so
only some °F values can appear). With 1–2 °F bands, late in the day "is the max 84 or 85" *is* the market.
Fits 1, 2, 3, 4, 6, 7, 9. Free: `api.weather.gov/stations/<icao>/observations`, MADIS 5-minute (registration), IEM
one-minute ASOS (delayed, good for history).

### B. Station-calibrated official guidance — most likely for the pre-day and morning gap
The crowd anchors on the NWS point forecast / NDFD, NBM (with NBP percentiles), LAMP and GFS-MOS, and HRRR. All are
bias-corrected to the airport site; our Open-Meteo grid blends are not — and a site bias is exactly what a −0.64 C-eq cool
bias looks like. Fits 1, 3, 5, 8, 10. Free, and **IEM archives MOS / NBM / LAMP station text keyed by run time for years**,
which is a genuine point-in-time corpus and goes round the free-tier PIT wall for the 11 US markets. Toronto needs the
ECCC equivalents (HRDPS/RDPS via MSC Datamart). ECMWF open data (IFS and AIFS) is also free now.

### C. Morning mesoscale state on bust days
64% of loss in 4.4% of rows smells like regime days: frontal timing, marine-layer burn-off, lake/sea breeze, convective
outflow, smoke. Information: GOES cloud, 12Z sounding (850 hPa temperature, mixing depth), radar/MRMS, dewpoint and wind
shifts, buoys/CO-OPS (dark). HRRR carries most of it hourly. Fits 2, 11. Free but GRIB-heavy; do after A and B.

### D. History rather than live data
No in-season forecast rows, no target-year row in-sample. Observation history is unlimited (IEM, GHCNh); the IEM guidance
archive in B supplies the forecast side. Fits 5, 8. This is a training-population fix, not a new signal.

### E. Non-weather information: who is trading
For the maker objective the missing information may not be weather. The execution tape (30 dates, 377,104 trades) carries
wallet identity and transaction hash. Unmined: which wallets' fills carry the worst maker markout, at what hours, and how
fast after an observation is published. This is data we hold.

### F. Latency
Even with the same feeds, the market reprices within a minute or two of an observation; we snapshot every 10 minutes.

### What we cannot get under the owner's rules
Paid station feeds, ECMWF HRES/ENS at full resolution and low latency, commercial nowcasts. If A–C do not reach parity,
this is the residual — and parity, not superiority, is what a maker's fair value needs (EF §1c, "MM question is open").

## Five diagnostics that discriminate between A–F (descriptive; no α; workstation or 00:30–09:00 only)

1. **Gap by local hour and by hours-to-close.** Rising through the afternoon ⇒ A/F; flat from the open ⇒ B/D.
2. **Adjacent-band test on the tail rows.** Market mode one band from ours ⇒ instrument/rounding (A); two or more ⇒ regime or guidance (B/C).
3. **Event study of mid jumps against the observation clock** (METAR ~:53, 5-minute marks). Says which feed the market reads, and whether anyone is ahead of the public feeds.
4. **NBM/LAMP-only band probabilities from the IEM archive against market mid on the 50 panel dates.** If guidance alone is near the market, B is identified for the cost of a download.
5. **Weather-type the 4.4% tail** from METAR we already hold (front, ceiling, wind shift, thunder). Says whether C is worth its GRIB cost.

Reading rule: these localise; none is an edge claim; crossed date × market clustering and the 12-market floor still bind.
