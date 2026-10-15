# Desk study: should we track more Polymarket weather markets? — 2026-10-14

Owner question (2026-10-14, relayed by master-agent): *"Have we look at tracking more markets? I know polymarket has
more. Would that help? I know our constraint is storage but I feel it is doable."*

Status: research note, workstation desk study. No code, config, capture-host or `data/` change was made. Nothing
here is a decision; the tranche and pilot in §6 are a proposal for the owner. Where a number was not measured it says
**not measured**.

## Answer in one paragraph

Yes, it would help, and the binding constraint is not storage for the cheap version. Sixteen of the 39 cities we do not
trade have more median volume per event than the median built-in, and five of them (London, Shanghai, Paris, Seoul,
Tokyo) are both the most liquid and settle on a free, METAR-built NOAA page, so their labels are free. A
**recorder-only** pilot (88a maker evidence + public trade tape, no model lane) costs about 7.7 MB per city-day:
+6 cities ≈ 46 MB/day ≈ 1.4 GB/month, under 1% of the measured baseline burn. The **full** model-evidence lane is what
storage cannot carry: +6 cities ≈ 0.9 GiB/day after NTFS compression and the 70 GiB headroom is already spoken for by
the baseline. Statistically, more markets are the only lever that lowers the panel's hard MDE floor (EF §1d), but only
for markets the model actually serves, which needs a WRH adapter, registry entries and a fresh forecast archive. More
markets do not rescue the maker-P&L power problem (EF §10r) on any plausible count.

## 1. Liquidity of the 39 non-built-in cities

Source: public, unauthenticated GETs to Gamma (`gamma-api.polymarket.com/events/slug/...`) and the CLOB
(`/book`, `/markets/{conditionId}`, `/rewards/markets/current`), ~2,750 requests at ≤ 4 req/s, workstation, run
2026-10-14 ~20:00 EDT. Slug prefixes from `config/locations.json` (`event_slug_prefix`); built-ins from `BUILTIN_SPECS`
in `src/weather/market/market_registry.py`. **Embargo:** no event dated 2026-09-30..10-15 was fetched; no 88a, panel
or settlement-ledger file was read.

- **Volume:** Gamma event `volume` (equal to the sum of band `volumeNum`), event dates 2026-08-31..09-29, n = 30 closed
  events for every city. It is the event's whole-life volume (2–4 trading days) for one temperature day, notional,
  as Polymarket reports it — not calendar-day volume and not maker-addressable flow.
- **Books:** one snapshot of the 2026-10-16 event's YES books, 2026-10-15 00:00–00:12Z (1–2 days before resolution).
  Medians over bands with a two-sided book; "act" = bands with mid in 0.05–0.95 (count in brackets). Depth is USD
  (price × size), both sides, within ±2c / ±5c of mid. One snapshot is not a time series.
- **Rewards:** sum of `total_daily_rate` over the event's rewarded bands (count in brackets); every rewarded band had
  min size 20 and max spread 4.5c in the rewards listing (Gamma's market objects showed min size 50 on spot checks).
- **Tiers:** reference = median of the 12 built-ins' median daily volume = **$41,901**. Tier 1 ≥ $41,901; Tier 2
  ≥ 25% of it ($10,475); Tier 3 below.

| City | Unit | Series start | Median vol $ | Spread c all/act (n) | Depth 2c act $ | Depth 5c act $ | Reward $/day (bands) | Tier |
|---|---|---|---:|---|---:|---:|---|---|
| Hong Kong | °C | 2026-03-13 | 127,726 | 1.6 / 3.0 (3) | 72 | 462 | 100 (3) | 1 |
| London | °C | 2025-01-22 | 80,543 | 0.8 / 2.5 (4) | 22 | 151 | 100 (3) | 1 |
| Shanghai | °C | 2026-03-13 | 74,323 | 1.1 / 2.0 (3) | 46 | 108 | 100 (3) | 1 |
| Paris | °C | 2026-02-11 | 71,476 | 1.0 / 3.0 (4) | 24 | 186 | 100 (4) | 1 |
| Seoul | °C | 2025-12-06 | 64,825 | 1.0 / 4.0 (4) | 51 | 121 | 100 (4) | 1 |
| Tokyo | °C | 2026-03-11 | 62,610 | 1.0 / 2.0 (3) | 104 | 4,154¹ | 100 (3) | 1 |
| Beijing | °C | 2026-03-20 | 56,588 | 2.5 / 3.0 (5) | 35 | 84 | 100 (5) | 1 |
| Wellington | °C | 2026-01-22 | 54,942 | 1.2 / 4.0 (3) | 14 | 187 | 100 (3) | 1 |
| Munich | °C | 2026-03-05 | 51,644 | 1.2 / 2.5 (6) | 13 | 155 | 100 (6) | 1 |
| Shenzhen | °C | 2026-03-20 | 48,025 | 1.5 / 3.5 (4) | 11 | 129 | 100 (4) | 1 |
| Madrid | °C | 2026-03-16 | 47,456 | 0.8 / 3.0 (4) | 53 | 227 | 100 (4) | 1 |
| Guangzhou | °C | 2026-04-15 | 47,128 | 1.6 / 3.0 (3) | 38 | 225 | 100 (3) | 1 |
| Milan | °C | 2026-03-16 | 45,476 | 1.0 / 2.5 (4) | 47 | 282 | 100 (4) | 1 |
| Chengdu | °C | 2026-03-20 | 44,752 | 2.0 / 2.0 (6) | 56 | 113 | 100 (6) | 1 |
| Singapore | °C | 2026-03-13 | 44,257 | 1.5 / 3.0 (3) | 26 | 158 | 100 (3) | 1 |
| Amsterdam | °C | 2026-04-03 | 42,983 | 1.0 / 2.6 (4) | 31 | 142 | 100 (4) | 1 |
| Taipei | °C | 2026-03-16 | 41,407 | 1.9 / 3.0 (4) | 19 | 132 | 100 (4) | 2 |
| Sao Paulo | °C | 2026-02-11 | 40,968 | 1.2 / 2.0 (5) | 27 | 315 | 100 (5) | 2 |
| Moscow | °C | 2026-03-30 | 37,838 | 4.6 / 5.0 (6) | 0 | 38 | 100 (7) | 2 |
| Cape Town | °C | 2026-04-09 | 37,433 | 1.7 / 3.0 (4) | 79 | 487 | 100 (5) | 2 |
| Kuala Lumpur | °C | 2026-04-03 | 36,087 | 2.0 / 4.0 (4) | 55 | 163 | 100 (4) | 2 |
| Warsaw | °C | 2026-03-16 | 36,081 | 2.0 / 2.0 (3) | 123 | 160 | 100 (3) | 2 |
| Chongqing | °C | 2026-03-20 | 34,026 | 2.6 / 3.0 (5) | 14 | 146 | 100 (5) | 2 |
| Busan | °C | 2026-04-03 | 33,417 | 1.4 / 3.0 (4) | 22 | 450 | 100 (4) | 2 |
| Manila | °C | 2026-04-16 | 33,391 | 0.9 / 3.0 (3) | 33 | 677 | 100 (3) | 2 |
| Wuhan | °C | 2026-03-20 | 33,196 | 0.9 / 3.0 (5) | 6 | 94 | 100 (5) | 2 |
| Buenos Aires | °C | 2025-12-06 | 32,509 | 1.6 / 2.5 (6) | 42 | 152 | 100 (5) | 2 |
| Helsinki | °C | 2026-04-03 | 31,790 | 0.9 / 2.0 (3) | 49 | 155 | 100 (3) | 2 |
| Ankara | °C | 2026-01-22 | 31,502 | 1.7 / 3.0 (5) | 41 | 98 | 100 (4) | 2 |
| Qingdao | °C | 2026-04-27 | 29,147 | 1.8 / 3.0 (3) | 42 | 757 | 100 (3) | 2 |
| Tel Aviv | °C | 2026-03-11 | 28,523 | 1.0 / 1.0 (3) | 86 | 378 | 100 (3) | 2 |
| Karachi | °C | 2026-04-16 | 23,375 | 1.0 / 2.0 (3) | 69 | 790 | 100 (3) | 2 |
| Jeddah | °C | 2026-04-09 | 23,131 | 1.3 / 3.0 (3) | 16 | 2,352¹ | 100 (3) | 2 |
| Mexico City | °C | 2026-04-01 | 23,037 | 3.0 / 3.0 (5) | 4 | 372 | 100 (5) | 2 |
| Lucknow | °C | 2026-03-05 | 22,869 | 1.4 / 4.0 (4) | 14 | 410 | 100 (3) | 2 |
| Istanbul | °C | 2026-03-31 | 19,424 | 2.3 / 5.0 (4) | 0 | 29 | 102 (4) | 2 |
| Panama City | °C | 2026-04-04 | 19,391 | 3.1 / 3.0 (4) | 25 | 1,511¹ | 100 (3) | 2 |
| Zhengzhou | °C | 2026-08-07 | 5,662 | not measured² | not measured² | not measured² | not measured² | 3 |
| Jinan | °C | 2026-08-07 | 2,802 | not measured² | not measured² | not measured² | not measured² | 3 |

¹ One large resting order dominates the figure. ² Gamma returned 404 for the 10-16 event at snapshot time.

**Built-in comparison (same method):** median volume Miami 73,247 (highest) … Denver 30,574 (lowest); every built-in
event also carried a $100/day reward pool over 3–6 bands, and active-band ±5c depth of 55–720.

**Reading:** 16 Tier 1, 21 Tier 2, 2 Tier 3. Hong Kong, London, Shanghai, Paris and Seoul out-trade every built-in
except Miami; Tokyo is level with NYC. Spreads and near-mid depth look like the built-ins'. The reward pool is flat at
about **$100 per event-day per city** in this snapshot, so each added city adds the same gross pool regardless of
volume. Pools on concurrent T+1/T+2 events and how the rate moves toward resolution: **not measured**.

## 2. Statistical value: the MDE floor and dates for a 5% step

EF §1d (`-09-57a`): the panel's MDE has a hard floor set by the number of market clusters, not dates — 3.2% of the
out-of-season gap at M = 12, and "a step worth ≤ 2.5% of the gap is NOT confirmable at any date count … Only more
markets, a paired design, or batching can." Its schedule (D = 5 → 15.06%, D = 73 → 5.00%, D = 365 → 3.62%) is fitted
exactly by MDE² = a + b/D with a ≈ 10.24, b ≈ 1075 (share-%²). Scaling to M markets assumes new markets have the
built-ins' per-cluster variance, so the floor term scales as 12/M. Two bounds for the date term: **conservative**, b
unchanged (date effects common to all markets); **optimistic**, b × 12/M (date effects idiosyncratic per market).

| M | Floor (share of gap) | Dates for a 5% step, conservative / optimistic | Dates for a 3% step, conservative / optimistic |
|---:|---:|---|---|
| 12 (today) | 3.20% | 73 / 73 | impossible / impossible |
| 18 | 2.61% | 60 / 40 | 495 / 330 |
| 24 | 2.26% | 55 / 28 | 277 / 139 |
| 36 | 1.85% | 50 / 17 | 192 / 64 |

These are proxies built on `-09-44a`'s out-of-season effect field and this report's scaling assumptions, not a new
design simulation. Three caveats bind: (1) the gain accrues only to markets the model serves and scores; recorder-only
cities add nothing to this table; (2) nearby, correlated cities (e.g. the eight mainland-China cities)
count for less than one independent market each, pushing toward the conservative column; (3) fixed-market inference
(FP item 7) removes the market floor for decisions on the existing 12 without new markets, and is cheaper.

## 3. Maker value: K1 power and reward capture

**K1 (maker-P&L sign test, EF §10r, 2026-10-14):** N_req ≈ 6.18 · σ_up² / δ² = 706 event dates at δ = 1 pUSD per
band-day (138 with σ_d in place of σ_up), against a 28-date ceiling. If the date-mean variance is idiosyncratic per
market, σ² scales as 12/M:

| M | N_req (σ_up) | N_req (σ_d) |
|---:|---:|---:|
| 12 | 706 | 138 |
| 18 | 471 | 92 |
| 24 | 353 | 69 |
| 36 | 236 | 46 |

Every row is above 28, and the optimistic scaling is the best case. **More markets do not make the maker-P&L desk
study decidable**; besides, its pre-registration is frozen on the 12 ledgers, so foreign cities would need a new
pre-registration, not a bigger panel.

**Reward capture:** each added city adds ~$100/day of gross reward pool per event (§1). Our achievable share is **not
measured** — it depends on queue position and competition (item 330's maker economics) and requires live quoting,
which stays behind the existing readiness gates. A recorder-only pilot measures the inputs (book competition at the
reward spread, fill flow) without quoting.

## 4. Storage

Measured per-family costs (sources in brackets; the two largest come from a single sample):

| Family | Per city-day | Source |
|---|---:|---|
| Model-evidence lane (snapshots, order-book tape, replay inputs, variant predictions, explanations) | 0.439 GiB kept after gzip tiering; 0.12–0.27 GiB after NTFS (2.97:1 on small files; large-file ratio not measured) | `roadmap/audits/swarm-expansion-2026-10-01.md:43-56`; `roadmap/audits/drive-offload-2026-10-02.md:27-41,62` |
| 88a maker evidence (books, trades, lifecycle, rewards; ~10 conditions over T+0..T+2) | ~7.1 MB gzipped | swarm-expansion :58, :185 |
| Execution tape (public trades) | ~0.6 MB | `operations/ESTABLISHED_FINDINGS.md:1264`; `roadmap/audits/efficiency-audit-2026-09-27.md:25` |
| Weather sources, closed-day Parquet, panel bundles, labels | not measured per city-day | `operations/workstation-disk-and-mirror-scope.md:60-62`; drive-offload :25-30 |

| Added cities | Recorder-only (88a + tape) per day / per 30 days | Full lane, kept before NTFS, per day / 30 days | Full lane after NTFS, central (range), per day / 30 days |
|---:|---|---|---|
| +6 | 46 MB / 1.4 GB | 2.68 GiB / 80 GiB | 0.93 (0.78–1.65) GiB / 28 (23–50) GiB |
| +12 | 92 MB / 2.8 GB | 5.35 GiB / 161 GiB | 1.86 (1.56–3.30) GiB / 56 (47–99) GiB |
| +24 | 185 MB / 5.5 GB | 10.70 GiB / 321 GiB | 3.72 (3.12–6.60) GiB / 112 (94–198) GiB |

**Against the storage plan** (`operations/storage-plan-2026-09-23.md:30-35`): volume 930.6 GiB; green ≥ 75 GiB free,
daily-low target ≥ 70 GiB; the expansion plan aborts below a 70 GiB 24-hour low (swarm-expansion :227). The latest free
figure in the docs is ~106 GiB (2026-10-06); 91a reclaimed 20.4 GB (10-08) and ~16 GiB (10-11) since; **today's free
space is not measured** (only `Get-Volume` on the host knows). Baseline burn is 4.5–8.6 GiB/day with no new cities
(swarm-expansion :45; drive-offload :79). So:

- **Recorder-only fits at any of +6/+12/+24**: at most ~0.2 GiB/day, 2–4% of baseline burn.
- **The full lane does not fit without Drive offload.** Even after the drive-offload study's projected ~264 GiB free
  by 10-22 (drive-offload :77, an estimate), the full lane for +6 lasts ~1.2 months and +24 ~0.8 months on top of
  baseline. The 2026-10-02 premortem reached the same verdict ("recorder-only at Stage 2",
  `roadmap/audits/exam-premortem-2026-10-02.md:77`).

## 5. Foreign model feasibility

**Settlement source.** The venue's event metadata (`config/location_market_events.json`, refreshed 2026-10-14) names
`weather.gov/wrh/timeseries` — a NOAA page built on METAR — for almost every city, built-ins included (the switch is
recorded in EF §10c). Exceptions: Taipei, Jinan, Zhengzhou still name Weather Underground; Hong Kong, Istanbul, Moscow
and Tel Aviv have no URL. `config/locations.json` still says WU for most foreign cities and is stale. Over 2026-09-20..29
the WRH max, the IEM METAR max and the winning band agreed on 50/50 foreign station-days (EF §10c;
`research/foreign-settlement-desk-study-2026-10.md:15-17`), so for WRH cities **free METAR is the settlement truth**.
Hong Kong pays `floor(HKO absolute daily max)`; VHHH airport METAR is not a proxy (wrong band 6 of 10 days) and HKO
has no free intraday archive (same desk study, :18-21, :118-124).

**Forecast inputs** (public Open-Meteo GETs for 2026-09-20, workstation): ECMWF IFS, AIGFS, ICON, JMA, UKMO,
Météo-France and CMA historical forecasts return 24/24 hours for all candidate cities. AIFS, GraphCast, KMA and the
past-date ensemble return 0/24 everywhere, Toronto included — a fleet-wide gap, not a foreign one. Previous Runs (the
archive the model trains from) covers Paris, Seoul, Shanghai, Tokyo, Hong Kong, Taipei and Jinan from 2021; London's
`best_match` only from 2024-03, so London must pin `gfs_seamless` to reach the 2021 start year
(`forecast_history.py:44`).

**Train/serve parity.** Abroad, the US-only sources (NWS, NBM, HRRR, NAM deltas, MRMS, CO-OPS/NDBC) and ECCC become NaN;
all sit in the NaN-tolerant list (`feature_store.py:206-251`), so serving does not break, but the consensus loses its
NWS/ECCC votes (`operations/EXHAUSTION_REGISTER.md` on the exreg branch, §3). Global-model deltas and METAR observed-path
features work everywhere. WU live history is off for every market (EF §10e), so foreign cities lose nothing there.
Nothing exists yet: no foreign forecast archive (the collector iterates registered markets only,
`forecast_history.py:1145`), no registry entry (`config/markets.json`, `market_registry.py:364-390`), and "no adapter
reads WRH or HKO yet" (EF §10c).

**Labels: Polymarket resolved outcomes vs the WU cutoff.** The ledger already reads venue winners but marks a
Polymarket-only winner `promotion_countable: False` (`settlement_ledger.py:738-760`), and that is right: a band carries
no intraday timing (the print-cutoff semantics and observed-path features need intraday rows), is interval-censored
with open-ended tails, and only goes back to the series start (§1). **For WRH cities the label source should be IEM
METAR** — exact degree, years of history, 50/50 agreement — with venue bands for reconciliation only. For WU cities
(Taipei, Jinan) METAR≡WU agreement is **not measured**.

| City | Grade | Binding reason |
|---|---|---|
| London | B | WRH/METAR labels free; needs registry + WRH adapter; pin `gfs_seamless` for pre-2024 archive |
| Paris, Seoul, Shanghai, Tokyo | B | Same, full archive from 2021; Tokyo's max often falls at local midnight (date-boundary care) |
| Taipei | B, conditional | WU RCSS; METAR≡WU unmeasured; WU collector state unknown |
| Other WRH-named cities | B, pending | Rules text not read; `locations.json` stale |
| Hong Kong | C | No free intraday HKO archive; VHHH not a proxy; HKO adapter missing; floor rounding |
| Istanbul, Moscow, Tel Aviv | C until verified | Venue resolution URL is null |
| Jinan, Zhengzhou | C (market) | Tier 3 volume; no live event at snapshot |

No grade-A city exists: none can reuse the built-in pipeline unchanged.

## 6. Proposed first tranche and capture-only pilot

Ranking = liquidity (§1 tier and volume) × coverage (§5 grade) × storage (equal per city, so it does not discriminate).

| Rank | City | Why |
|---:|---|---|
| 1 | London | Tier 1 ($80.5k), grade B, longest series (2025-01-22), tightest all-band spread |
| 2 | Shanghai | Tier 1 ($74.3k), grade B |
| 3 | Paris | Tier 1 ($71.5k), grade B |
| 4 | Seoul | Tier 1 ($64.8k), grade B, series since 2025-12 |
| 5 | Tokyo | Tier 1 ($62.6k), grade B, deepest active book in the snapshot |
| 6 (optional) | Hong Kong | Highest volume of all 51 ($127.7k) but grade C for a model; worth recording for maker economics only |

**Pilot: recorder-only, 5–6 cities.** 88a maker evidence plus the public trade tape for the tranche, no model lane, no
quoting, no orders. Cost ≈ 40–46 MB/day (§4). It answers what the census cannot: book competition at the 4.5c reward
spread over time, fill and trade flow by hour, and reward-rate movement toward resolution — the inputs to item 330's
maker economics — and it starts the tape any later model scoring would need. The model lane (registry entries, WRH
adapter, Open-Meteo Previous Runs + IEM METAR archive) is a separate, later workstation build that the pilot does not
require; the 88a hold (UTC 09-27..10-30) is untouched because the pilot only adds new files.

**Roll class: not decided here.** It depends on the head, and the verdict comes only from
`scripts\ops\roll_verdict.ps1 -Branch <b>`. Whether 88a's recorder can pick up extra cities through config alone
(`config/` is roll-free) or needs a change to a loop-imported module (roll-sensitive, 01:00–04:00 quiet window via
`quiet_window_merge.ps1`) is **not measured**; reading the 88a recorder's market enumeration is the pilot's first step.

**Earliest night:** not 10-15..10-17 (LFC session 0 and the host-Python Phase B/C nights), and the 10-18 slots are
taken, so the earliest realistic landing is the **10-19 quiet window (01:00–04:00)** or later, after the pilot head is
built, reviewed, and the host's free space is read with `Get-Volume` against the ≥ 70 GiB daily-low target.

## Not established

Calendar-day volume; reward pools on T+1/T+2 events; any book time series; our achievable reward share; the
large-file NTFS ratio; today's free space; METAR≡WU agreement for RCSS/ZSJN; settlement rules text for the WRH-named
cities beyond London and the 2026-10-02 desk study's five; whether new markets have the built-ins' cluster variance.

Raw census files (CSV, JSON, fetch scripts) are kept on the workstation scratchpad and not committed.
