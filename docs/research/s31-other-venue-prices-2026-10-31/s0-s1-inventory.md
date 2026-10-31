# S31 other-venue prediction-market prices: S0 intake and S1 outcome-free inventory (lane L14, 2026-10-31)

**Status:** dated research record: stages S0 and S1, plus the header-only S2 step 1 (ForecastEx pairs schema). It records **no prices, outcomes or settlement results**. Every
fact below comes from public documentation, regulatory filings, or unauthenticated **metadata** endpoints: series and
event titles, rules, settlement-source URLs, market tickers (strike structure) and listing dates. Master ruled on S1 on
2026-10-31 (section "Venue-read rule"); price reads wait for the P0 pre-registration and the coordinator's code review.

- **Owns:** the S0 argument for and against S31, the twin-market inventory for the 12 built-in markets, and the
  fetch receipts for that inventory.
- **Read when:** proposing an S2 price read for S31, choosing a twin venue or city, or re-checking a twin's settlement
  source.
- **Do not use for:** any claim of information or edge. Nothing here is measured. Settlement semantics of *our*
  markets live in [AGENT_CONTEXT](../../operations/AGENT_CONTEXT.md) and
  [venue-rule labels](../../operations/venue-rule-labels.md).
- **Owner approval:** S31 is a READ-ONLY research input (owner approval relayed to lane L14 by master). The embargo on later price
  reads is dev dates up to 2026-09-29 plus 09-30..10-14, and never any date after 10-14.
- **Raw metadata archive:** `C:\archive\ruled-out\_s31-intake\` on the 32 GB workstation (DESKTOP-RFCD2GH), with
  `SHA256SUMS.txt` at its root. That archive is local, not in the repository.

## S0: why another venue might know something International Polymarket does not

Our venue is **International Polymarket**: non-US, crypto-collateral traders, 2 °F bands (1 °C for Toronto) with two
tails. Before 2026-10-23 it paid the WU band; from 2026-10-23 it resolves on the highest routine METAR (SPECI
excluded), with WU as the fallback ([FINDINGS_DIGEST](../../operations/FINDINGS_DIGEST.md), EF §10x, §10ai). A twin
venue's price can carry information ours lacks only through one of these channels:

1. **Different traders.** Kalshi and ForecastEx are CFTC-regulated US venues, reached through Kalshi itself,
   Robinhood and Interactive Brokers. Their flow is US retail plus US market makers, and some of those makers run
   weather desks. International Polymarket excludes US persons. If the two populations hold different forecast
   skill, or if one side has a professional maker the other lacks, the two prices can disagree, and the better-informed
   side leads.
2. **Liquidity and depth.** A deeper book updates faster after a model run or a fresh METAR. If the twin is deeper
   for a city, its mid-price can lead ours by minutes, and a lead is exactly what an as-of-capture feature can use.
3. **Timing.** ForecastEx trades until 23:59 local time on the target date (filing, Appendix A). Kalshi's legacy
   terms trade until 23:59 ET. Each venue's trading window, listing time and strike re-centring differ from ours. A
   venue that lists earlier, or re-centres its strikes on a model run, puts a forecast into the public record before our
   book reacts.
4. **Settlement source.** Kalshi settles on the NWS Daily Climate Report (CLI). That is a continuous-sensor daily
   maximum over the **local-standard-time** day, so during DST the day runs 01:00 to 00:59 local. Our labels are
   whole-degree WU before 10-23 and routine METAR after. ForecastEx settles on the WU Daily Observations table, the
   same source family as our pre-10-23 labels. A venue that settles on a related but different quantity prices that
   quantity. Its price is informative about ours only through the joint distribution of the two quantities, and that
   joint distribution is weather we can model ourselves.
5. **Fees, limits and carry.** Kalshi weather series declare `fee_type: quadratic` (series metadata) and a position
   accountability level of $25,000 per strike. ForecastEx pays an incentive coupon on held contracts and has a
   250,000-contract accountability level. Different costs move each venue's no-arbitrage band, so a price gap inside
   both venues' cost bands is not information.

**What would make S31 false.** Each case below is checkable in S2, and each should be checked before any model use:

- **The twin follows us** (or both follow the same public models). If the twin's moves lag ours, or both are
  explained by the same NBM/HRRR run, its residual against our capture-time market is zero. Test: a lead-lag check on
  mid-price changes, plus the incremental log-loss of the twin price over our market price at the same capture
  instant, on dev dates only.
- **Settlement-source noise.** If the twin settles on a different station (Kalshi NYC Central Park vs our LaGuardia;
  Chicago Midway vs our O'Hare; Dallas DFW vs our Love Field) or a different measurement (CLI continuous max vs WU or
  routine METAR), the gap between the two prices partly reflects the gap between the two quantities. That component
  is predictable from weather and adds nothing over our own model. Only same-station, same-measurement twins test the
  pure "other traders know more" channel.
- **Band-geometry artefacts.** Kalshi lists 4 two-degree brackets plus 2 tails, and the bracket parity shifts day to
  day (below). ForecastEx lists a "greater than X" ladder. Mapping either onto our 11 bands needs interpolation where
  the edges do not align. Interpolation error can look like signal.
- **Stale or thin twin prices.** A venue that only publishes daily closes, or trades rarely in a city, cannot supply an
  as-of-capture value. A post-close price taken after the high is known is outcome leakage, not information.
- **Already in our market.** Our own capture-time market price already beats the model on the dev scorecard (served
  vs control comparisons in the [free-source screens](../free-source-screens-2026-10-23.md)). A twin price adds
  information only if it beats **our market**, not only our model. That is the bar for S2.

## S1: twin inventory (outcome-free)

### Venues checked

| Venue | Daily city-high product | Public metadata access | Result |
| --- | --- | --- | --- |
| **Kalshi** (KalshiEX LLC, CFTC DCM) | Yes: `KXHIGH*` series, a range ladder | Trade API v2 `/series`, `/events`, `/events/{t}/metadata` are unauthenticated (OpenAPI `security: []`) | 11 of 12 cities have live twins; the Toronto series exists with **0 events** |
| **ForecastEx** (IBKR's CFTC DCM; also routed through Robinhood) | Yes: "Daily Temperature Forecast Contract", product code `U H <city>` (°F), `S H <city>` (°C, filed 2026-02-04), a "greater than X" ladder | CFTC filings and a public S3 data bucket; no public API found | 11 of 12 cities found as Robinhood-listed ForecastEx contracts on WU stations; Toronto not found |
| Robinhood (Robinhood Derivatives) | Front end only; routes to KalshiEX, ForecastEx, Rothera Exchange and Clearing, or NADEX | Public event pages (they carry prices) | Not a separate venue for S31; it is how the ForecastEx station names were read |
| Crypto.com / OG (NADEX DCM) | Temperature contracts exist (press and comparison sites) | No public metadata endpoint found | **Not inventoried**: settlement source and cities unconfirmed |
| Polymarket US | Twin listings plausible | Not probed | **Excluded**: a compatibility surface only (AGENTS.md); no new probes allowed |

### Twin table

Our station is `config/locations.json` `settlement.station_id` (the WU history station). The Polymarket venue
resolves on routine METAR from 2026-10-23 and names KDEN, not KBKF, for Denver (EF §10x). Kalshi stations come from the
first-party CLI `issuedby` code in each series' or event's `settlement_sources` up to 2026-08-14. From 2026-08-15 every
Kalshi twin's event `settlement_sources` reads "The Weather Company, weather.com/kalshi". That portal states it relays
"NWS/NOAA official Daily Climate Report (CLI) values", and its primary-station list includes every station below. The
post-08-15 station is therefore **presumed unchanged but not verified**, because the per-market rules text exists only
in the price-bearing `/markets` endpoint, which this stage did not call. ForecastEx stations come from Robinhood event
pages that name ForecastEx as the contract-terms source (dates 2026-04-27..09-15). Those pages were read through a
summariser told to drop prices, so the station names there are secondhand, one page per city.

| Market (ours) | Our station | Kalshi series (CLI station) | Same station? | Kalshi events from | ForecastEx station (WU) | Same station? |
| --- | --- | --- | --- | --- | --- | --- |
| NYC | KLGA | `KXHIGHNY` (Central Park, CLI NYC) | **No** | 2021-08-07 | KLGA | **Yes** |
| Chicago | KORD | `KXHIGHCHI` (Midway, CLI MDW, since 2023-04-13; before that a generic LOT climate page) | **No** | 2021-08-20 | KMDW | **No** |
| Atlanta | KATL | `KXHIGHTATL` (CLI ATL) | Yes | 2026-02-05 | KATL | **Yes** |
| Austin | KAUS | `KXHIGHAUS` (CLI AUS, Bergstrom) | Yes | 2023-05-12 | KAUS | **Yes** |
| Dallas | KDAL | `KXHIGHTDAL` (CLI DFW) | **No** | 2026-02-12 | KDFW | **No** |
| Denver | KBKF (venue KDEN from 10-23) | `KXHIGHDEN` (CLI DEN) | No vs KBKF; **yes vs the venue's KDEN** | 2024-11-21 | KBKF (page dated 09-15) | Yes vs KBKF |
| Houston | KHOU | `KXHIGHTHOU` (CLI HOU, Hobby); earlier `KXHIGHHOU` 2024-11-21..2025-01-29 | Yes | 2026-02-12 | KHOU | **Yes** |
| Los Angeles | KLAX | `KXHIGHLAX` (CLI LAX) | Yes | 2025-01-06 | KLAX | **Yes** |
| Miami | KMIA | `KXHIGHMIA` (CLI MIA) | Yes | 2023-05-12 | KMIA | **Yes** |
| San Francisco | KSFO | `KXHIGHTSFO` (CLI SFO) | Yes | 2026-01-15 | KSFO | **Yes** |
| Seattle | KSEA | `KXHIGHTSEA` (CLI SEA) | Yes | 2026-01-15 | KSEA | **Yes** |
| Toronto | CYYZ (°C) | `KXHIGHTCYYZ` listed (TWC international terms) | n/a | **0 events** | not found | n/a |

Coverage notes (from paginated `/events`; the event list has no gaps longer than 3 days in any series):

- Kalshi event counts as of 2026-10-31: NY 1,909; CHI 1,897; MIA 1,269; AUS 1,266; DEN 711; LAX 665; SEA 291; SFO 291;
  ATL 270; DAL 263; HOU 263 (plus 70 in `KXHIGHHOU`). The NY, CHI, AUS and MIA counts include the legacy `HIGH*`
  tickers that migrated into the `KX` series. The legacy series objects (`HIGHNY`, `HIGHCHI`, `HIGHAUS`, `HIGHMIA`)
  now hold 0 events, and so do `KXHIGHOU`, `KXHOUHIGH` and `KXDENHIGH`.
- Every Kalshi twin switched its event `settlement_sources` from an NWS CLI URL to `weather.com/kalshi` on target date
  2026-08-15. Austin carried a mis-attached Los Angeles (CQT) CLI URL alongside AUS from 2024-09-05 to 09-15
  (metadata artefact).
- ForecastEx: the °F daily contract was filed with the CFTC on 2026-01-23 and re-filed on 2026-08-06; the
  re-filing narrowed resolution to the WU **Daily Observations table**, not the Summary "High Temp". The °C contract
  was filed on 2026-02-04. Robinhood event pages for these contracts exist from at least 2026-01 (NYC page dated
  2026-01-26; its venue is not confirmed). The first listing date per city is **not** established: it lives in the
  exchange's price, pairs and summary CSVs, which were not opened.

### Settlement semantics versus ours

| | Ours (International Polymarket) | Kalshi | ForecastEx |
| --- | --- | --- | --- |
| Quantity | WU whole-degree daily high before 10-23; highest routine METAR, half-up, from 10-23 (WU fallback) | NWS CLI daily maximum, "final" report; TWC is first in the source hierarchy, NWS second | WU Daily Observations table highest value for the station and date |
| Day window | Local calendar day | **Local standard time** (01:00 to 00:59 during DST) | Local calendar day, final once the next day's first observation posts |
| Sensor basis | Hourly and routine reports (WU includes SPECI; the venue rule from 10-23 excludes SPECI) | Continuous ASOS max (can exceed every hourly report) | Same as WU: hourly plus specials as WU displays them |
| Relation to our label | — | Different measurement even at the same station; also a different station in NYC, CHI, DAL and DEN-vs-KBKF | **Same source family and table** as our pre-10-23 WU label at 9 stations; after 10-23 it differs from our venue rule wherever WU-with-SPECI differs from routine METAR (EF §10ai: the routine-only rule matched the WU band on 617/626 pre-10-23 market-days; 8 band flips, all SPECI effects) |

### Band and threshold structure

- **Ours:** 11 outcomes per event: a lower tail, 9 two-degree bands with an **even lower bound** (e.g. 60-61 °F), and an
  upper tail; Toronto uses 1 °C bands (config `location_market_events.json` titles).
- **Kalshi:** 6 markets per event: 4 two-degree brackets (`B<mid>.5`, inclusive pairs) plus `T<x>` tails, about 8 °F
  of central coverage, re-centred daily. **Bracket parity changes day to day.** In the sampled dev-date events (target
  dates 2025-06-15, 2026-09-15 and 09-16), some days used even lower bounds that align with ours (NY 09-15:
  72-73 ... 76-77) and others odd lower bounds offset by 1 °F (NY 09-16: 75-76 ... 81-82; CHI 09-16; DAL 09-16;
  HOU, SEA, SFO, ATL, LAX on 09-15). On offset days no Kalshi bracket maps exactly onto one of our bands. Legacy
  `NHIGH` terms allow strikes at any integer from −30 to 130 °F.
- **ForecastEx:** a "greater than X" ladder of about 9-13 strikes per event (Robinhood pages), at integer thresholds,
  not always consecutive (e.g. CHI 72, 75, 76, 78...). Where two thresholds are 2 °F apart and match our band edges,
  P(our band) = P(>lower−1) − P(>upper) exactly. Elsewhere the mapping needs interpolation.

### History depth and snapshot granularity (from public docs; nothing fetched)

| | Kalshi | ForecastEx |
| --- | --- | --- |
| Trades | `GET /markets/trades` (public, per trade: ticker, price, size, timestamp; `min_ts`/`max_ts`; up to 1,000 per page); `GET /historical/trades` for trades before the cutoff | No public trade tape found; `pairs/pairs_YYYYMMDD.csv` "daily pairs data (refreshed every 10 minutes)" from 2024-08-01 (schema not inspected) |
| Candles | `GET /series/{s}/markets/{m}/candlesticks` and `/historical/markets/{m}/candlesticks`; intervals 1 min, 60 min, 1 day; fields yes_bid/yes_ask OHLC, trade price OHLC, volume, open interest | None; `prices/daily_prices_YYYYMMDD.csv` "daily closing prices for all events" from 2024-08-01 |
| Order book | `GET /markets/{t}/orderbook`: **current snapshot only** (depth up to 100); no historical book; WebSocket feeds **require authentication** even for public channels | None public |
| Archive split | `GET /historical/cutoff` (fetched; timestamps only): markets and trades settled or created before 2026-08-31 have moved to `/historical/*`; events and series stay on the live endpoints | S3 bucket `forecastex-public-data`, plus `daily_summary/summary_YYYYMMDD.csv` from 2025-01-01 |
| Auth | Every endpoint above declares `security: []` | Public S3 objects; no account needed |

**Granularity verdict.** Kalshi supports an as-of-capture twin price: 1-minute candles with bid and ask, and a
per-trade tape, back to each series' start (2021 for NY and CHI). ForecastEx publicly supports only daily closes plus
an intraday-refreshed "pairs" file of unverified schema. A daily close on a contract that trades until 23:59 local
time comes after the high is known, so it is outcome-contaminated and **unusable as a forecast input** unless the
pairs file carries timestamped intraday prices.

### Viable S1 matches

Ranked for an S2 price read, should master approve one:

1. **Kalshi, same station, different measurement (CLI vs our WU/METAR):** Atlanta, Austin, Houston, Los Angeles,
   Miami, San Francisco, Seattle (7 cities). These have intraday candles and trades. Kalshi's series start dates leave
   all 7 inside the dev window (≤ 2026-09-29), but ATL, HOU, SEA, SFO and DAL only from 2026-01/02. The CLI-vs-WU
   measurement gap is a known nuisance that S2 must model or difference out.
2. **ForecastEx, same station, same WU table:** NYC, Atlanta, Austin, Houston, Los Angeles, Miami, San Francisco,
   Seattle, Denver-KBKF (9 cities). This is the cleanest test of the "other traders" channel, but it is viable **only
   if** the public pairs CSV holds timestamped intraday prices. S2 should first inspect that file's **schema**
   (header row only, one dev date) before any price read.
3. **Not viable for the pure channel:** NYC, Chicago and Dallas on Kalshi, and Chicago and Dallas on ForecastEx (each a
   different station). Denver on Kalshi (KDEN) matches the venue's post-10-23 station, but every post-10-14 date is
   embargoed, so it cannot be used now.
4. **Toronto:** no twin with events on any venue checked.

## Access, auth walls, and price exposure

- **No auth wall was hit.** Every endpoint used was unauthenticated. No account, key or credential was used or
  opened.
- **Not called:** Kalshi `/markets`, `/markets/{t}`, `/events?with_nested_markets=true`, candlesticks, trades and the
  orderbook (all price-bearing); every ForecastEx `prices/`, `pairs/`, `daily_summary/` CSV, and the
  `notices_to_members/` PDFs (these may announce resolutions). Only S3 key **names** were listed, to date the files.
  A bucket prefix that the public index page excludes was not touched.
- **Incidental exposure, Robinhood (master ruling 2026-10-31: NOT a read).** The 11 Robinhood event pages
  fetched through the web-fetch summariser render prices and results. The summariser was told to drop them; none
  were reported to the lane, recorded, kept or analysed. Master ruled this an incidental exposure, not a price or
  outcome read. The same note is at `C:\archive\ruled-out\_s31-intake\INCIDENTAL_EXPOSURE.md`. The ForecastEx
  station names in the twin table come from those pages and are therefore **unverified for S2**: S2 re-derives every
  station from metadata only (rule below).
- **Other metadata seen:** Kalshi event-metadata responses carried market **tickers** only (strike levels), with
  no prices; the sampled events were all on dev dates (2025-06-15, 2026-09-15, 2026-09-16). The 2026-10-27..11-01
  event titles in the `/events` pages are listing metadata, with no prices or results.
- **Light rate:** about 70 Kalshi requests at ≥ 1 s spacing, plus static docs and filings.

## Venue-read rule for S31 (master ruling, 2026-10-31)

- **Never fetch a venue PAGE that renders prices or results** (Robinhood, Kalshi or ForecastEx web pages, or any
  front end). Use metadata endpoints only, parsed through a **field allowlist** that drops every price, volume,
  open-interest, result and settlement-value field before anything is written.
- **Price reads are allowed only** for target dates up to 2026-09-29, or for **released cells**: local targets
  2026-09-30..10-14, minus Austin 2026-10-03. Never any other date after 2026-09-29.
- Any fetch code is a **new module that writes only under its own out dir**. Its diff goes to the coordinator
  before any price fetch, and master sees the pre-registration first.

## S2 step 1: ForecastEx pairs schema (approved by master 2026-10-31; header only)

- **Read:** one dev-date file, `pairs/pairs_20260915.csv` (S3 `forecastex-public-data`; object size 1,134,848 bytes,
  Last-Modified 2026-09-15 21:17:08 UTC, ETag `6ebeacc52fa23d9b88be4003b202619b`), by an HTTP Range request for
  bytes 0-2047. Only the bytes up to and including the first newline (77 bytes) were kept; the rest of the range
  was discarded in memory without being parsed, printed or written. **No price row was read.**
- **Header (verbatim):** `pair_id,event_contract,expiration_date,quantity,yes_price,no_price,pair_time`
  (sha256 of the 77 header bytes `764d1b7efac3b7be9e9a785e70482453aef01bf6aad2fe81a54f39d9156b7641`).
- **Columns:** `pair_id` (one row per matched YES/NO pair, i.e. per fill, not a quote or a close); `event_contract`
  (contract identifier; format not inspected); `expiration_date`; `quantity`; `yes_price`, `no_price`; `pair_time`.
- **Timestamp granularity:** each row carries its own `pair_time`, so the file is a **per-fill tape with intraday
  timestamps**, not a daily close. The value format (resolution, time zone) is **not verified**: it can only be
  read from a data row, which this step did not open. S3 listing metadata for 2026-09-10..19 shows **one file per
  day**, last modified about 21:16-21:17 UTC daily (sizes 0.73-1.67 MB), so the "refreshed every 10 minutes" file is
  rewritten through the day and frozen after the day's last update.
- **Consequence:** the ForecastEx arm of S2 is feasible in principle (per-fill prices with times, no order book). The
  P0 pre-registration makes the `pair_time` format a refuse-if-wrong check on its first allowed row.
- **Receipts:** `C:\archive\ruled-out\_s31-intake\forecastex\s2_step1\` (`pairs_20260915_header.bin`, its receipt
  JSON with the HTTP response headers, and the S3 key listing for `pairs/pairs_2026091*`).

## Fetch receipts

All files are saved under `C:\archive\ruled-out\_s31-intake\`. The sha256 of each file is in `SHA256SUMS.txt`.

| Folder | Content |
| --- | --- |
| `kalshi/series_climate_weather.json` | `/series?category=Climate and Weather` (500 series metadata objects; no cursor returned) |
| `kalshi/events/events_<SERIES>_pNN.json` | Paginated `/events?series_ticker=` for the 20 twin and legacy series (no nested markets) |
| `kalshi/events/probe_*` | The first probes (events, limit 5; one event-metadata call) |
| `kalshi/event_metadata/meta_*.json` | `/events/{t}/metadata` for 16 dev-date events (market tickers only) |
| `kalshi/historical_cutoff.json` | `/historical/cutoff` timestamps |
| `kalshi/pdf/` | GLOBALTEMPERATURE and INTERNATIONALTEMPERATURE contract terms and product certifications; legacy NHIGH terms |
| `kalshi/docs/` | Kalshi API reference pages (markdown) for candlesticks, trades, orderbook, historical data, rate limits, WebSocket, events |
| `weathercom/` | The `weather.com/kalshi` portal HTML, its static JS chunks, and the primary-station list (`/kalshi/api/metar?primary=true&listOnly=true`: station id, name and timezone only) |
| `forecastex/cftc/` | CFTC filings ptc01232637912 (2026-01-23), ptc08062614351 (2026-08-06), ptc08272622411 (hourly, not read in full) |
| `forecastex/site/` | forecastex.com `/data` and `/markets` HTML, the public-data index, S3 key listings, and the two daily-temperature product filings |
| `_scripts/` | The two scratch scripts used (event pagination with a banned-field guard; coverage summary) |
| `forecastex/s2_step1/` | S2 step 1: the pairs header bytes, their receipt, and the `pairs/pairs_2026091*` key listing |
| `INCIDENTAL_EXPOSURE.md` | The Robinhood incidental-exposure note (master ruling 2026-10-31) |
