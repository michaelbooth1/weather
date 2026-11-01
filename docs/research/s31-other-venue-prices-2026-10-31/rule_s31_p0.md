# S31 cross-venue twin prices against the market: market-residual P0 rule (ledger row 93, DRAFT)

Status: **DRAFT for master's review** (lane L14, 2026-10-31). It is written before any twin-venue price, outcome
or label is read for S31. The ledger row was committed first (`18fd48ac9`). Evidence class: a dev-window,
kill-only P0 screen. It is its own arm family with its own K, and it is not pooled with rows 78, 81 or 85-92.
Nothing here is a release, serving, capture, scheduling or trading decision. **No fetch runs under this rule until:**
(1) master has seen this rule; (2) the coordinator has reviewed the fetch module's diff; (3) the open fields in (f)
are filled by a dated Clarification with its own sha256.

Inventory, S0 argument and S2 step 1: [s0-s1-inventory.md](s0-s1-inventory.md).

## 1. Mechanism (R14) and prior, written before any read

**R14 intake:** this is not a free-source T+0 screen without a mechanism. **The S0 mechanism is the trader-pool
channel.** Kalshi and ForecastEx are CFTC-regulated US venues, reached through Kalshi itself, Robinhood and
Interactive Brokers. Their flow is US retail plus US market makers, and International Polymarket excludes US
persons. If that pool forecasts the same station's high better, or its makers react sooner to model runs and
METARs, the twin's capture-time price predicts our market's error at the same instant.

The prior is low to moderate. Weaknesses, stated now:

- **Shared information.** Both venues can price the same public NWP and METAR. Cross-venue market makers can also
  arbitrage the two, which leaves no residual (S0 falsifier 1).
- **Kalshi settles on a different quantity.** Kalshi settles on the **NWS Daily Climate Report (CLI)**: a
  continuous-sensor daily maximum over the local-standard-time day (01:00-00:59 local during DST). **We settle on
  WU** (whole-degree WU history before 2026-10-23; every scored date here is before that). Even at the same
  station, part of any Kalshi-minus-us gap is the CLI-minus-WU gap. That gap is weather we can model, not trader
  information (S0 falsifier 2). Its constant part cancels in Δ, because the calibration-matched placebo keeps the
  same c − m values (§5); its date-varying part does not.
- **Band geometry.** Kalshi lists 4 two-degree brackets plus 2 tails with day-to-day parity shifts. ForecastEx lists
  a "greater than X" ladder. The arms therefore use location and scale summaries of the twin, never a band-by-band
  mapping (§4).
- **Thin or stale twin prices** shrink coverage. A price taken after the high is known is excluded by the
  capture-time rule (§3).

## 2. Data, dates and the read rule

- **Our side, unchanged from rule_mr_sweep `85f8192c` §1:**
  - layout `C:/swarm/v3layout`;
  - burn-in 2026-08-01..08-14; scored 2026-08-15..09-29;
  - m = `Table.p_market`, y = the band's winner indicator, e = y − m;
  - market moments with the σ_m² floor 0.25 °F²; z_b as in §1 of that rule.
- **Population:** only the markets an arm covers (§4). Toronto is excluded: no twin with events.
- **Twin-venue reads (master ruling 2026-10-31):**
  - Prices are read only for target dates 2026-08-01..09-29 (burn-in plus scored). The released cells (local
    targets 2026-09-30..10-14 minus Austin 10-03) are **not** used: this rule is dev-only.
  - No venue **page** that renders prices or results is fetched. Metadata endpoints and data endpoints are parsed
    through a field allowlist (§6).
  - No twin-venue result or settlement field is read. y comes from our own layout.
- **Evidence cutoff and reserved window:** STATE_OF_PLAY's outcome embargo (no outcome, price or label after
  2026-09-29 outside a named, owner-opened test). The reserved MG-1 window (local targets from 2026-10-15) is
  untouched: no date after 09-29 is read.

## 3. V0: outcome-free verification (first; refuse-if-wrong)

V0 runs before any price is read. Each check that fails drops the named city or arm before §4. The drop is recorded,
and the arm stays in K.

1. **Kalshi's 2026-08-15 settlement-source change (verified first).**
   - For each Kalshi twin series, fetch the markets of two events, one before 08-15 and one after, both dated up to
     09-29.
   - Use `GET /trade-api/v2/markets?event_ticker=…`, parsed through allowlist A (§6).
   - From `rules_primary` and `rules_secondary`, record the named station and the source text.
   - **A city stays in KAL iff its post-08-15 rules name the same station as its pre-08-15 CLI code** (S1 table:
     ATL, AUS, HOU Hobby, LAX, MIA, SFO, SEA). It also must not name a different measurement than the NWS CLI daily
     maximum. A changed station drops the city from KAL. A changed measurement drops it for the dates after the
     change.
2. **Kalshi strike semantics.** From allowlist A's `strike_type`, `floor_strike` and `cap_strike`, record every
   market's interval for every event used. Tickers are never parsed for semantics. An event whose six intervals do
   not tile the line drops that event.
3. **ForecastEx stations, from metadata only.** The Robinhood-derived station names are not used (incidental
   exposure, S31 doc).
   - For each candidate city, the designated station must be confirmed from a ForecastEx or IBKR specification
     document: `product_filings/` PDFs, or `supplemental_data/` files whose names mark them as contract
     specifications. Notices to members are not opened.
   - A city without such confirmation is dropped from FEX before any pairs row is read.
   - Same-station cities only: our station must equal the confirmed station.
4. **ForecastEx `pair_time` format (S2 step 1 left it open).**
   - On the first allowed pairs file, the parser reads only the `pair_time` and `event_contract` columns of the
     first row.
   - **FEX refuses** unless `pair_time` parses to at most 1-minute resolution, with an explicit or
     documented time zone.
   - `event_contract` must decode to (city code, target date, threshold) through the filing's product code
     (`U H <city>`). Otherwise FEX refuses.
   - A refusal leaves FEX in K as UNTESTABLE, with p = 1.

## 4. Arms (fixed; K = 3)

Types and tilt are those of rule_mr_sweep `85f8192c` §4:

- **Type C:** s_b = (x − μ_m)(z_b − μ_m)/σ_m².
- **Type S:** s_b = g_z((z_b − μ_m)² − σ_m²)/σ_m².
- **Tilt:** c_b = Σm·m̃_b·exp(s_b/σ_s) / Σ m̃·exp(s/σ_s).
- g_z and σ_s are taken within market over covered fit-table snapshots. No parameter is fitted.

| # | id | venue, markets | type | value |
| --- | --- | --- | --- | --- |
| 1 | KAL-MEAN | Kalshi, V0-passed of ATL, AUS, HOU, LAX, MIA, SFO, SEA | C | μ_t, the twin-implied mean |
| 2 | KAL-WIDTH | same | S | g = σ_t − σ_m (twin wider than our market widens ours) |
| 3 | FEX-MEAN | ForecastEx, V0-passed of NYC, ATL, AUS, HOU, LAX, MIA, SFO, SEA, DEN (KBKF) | C | μ_t from the exceedance ladder |

**Kalshi twin distribution at capture time t_c** (snapshot `captured_at_utc`):

- **Quote:** per market, take the latest 1-minute candle with `end_period_ts` ≤ t_c and ≥ t_c − 60 min. Its quote is
  the mid of `yes_bid.close` and `yes_ask.close`, required to satisfy 0 < bid ≤ ask < 1 and ask − bid ≤ 0.20.
- **Coverage:** a snapshot is covered only if all six markets of the event have a quote.
- **Moments:**
  - q = mids / Σ mids.
  - z for each interval: an interior bracket is its midpoint. The lower tail is (upper bound − 1) − W/2 and the
    upper tail is (lower bound + 1) + W/2, with W = 2 and integer °F intervals from V0.2. This is the sweep's
    open-band convention.
  - μ_t = Σ q z and σ_t² = Σ q (z − μ_t)², floored at 0.25 °F².

**ForecastEx twin ladder at t_c:**

- **Price:** per threshold contract, the latest fill with `pair_time` ≤ t_c and ≥ t_c − 120 min. Its price is
  `yes_price` as P(T > X).
- **Monotonicity:** the covered thresholds are made non-increasing in X by pool-adjacent-violators.
- **Coverage:** at least 3 thresholds are needed, spanning μ_m (one at or below, one above).
- **Masses:** between consecutive thresholds X_k < X_{k+1}, the mass sits at z = (X_k + 1 + X_{k+1})/2. Below X_1
  it sits at X_1 − 1, and above X_K at X_K + 2.

**Not tested, decided now:**

- A band-by-band twin vector: it would need interpolation across misaligned edges (S0 falsifier 3).
- Kalshi NYC (Central Park), CHI (Midway), DAL (DFW) and DEN (KDEN), and ForecastEx CHI and DAL: different
  stations, so they cannot test the pure trader-pool channel.
- Kalshi volume and open interest: no pre-statable sign.
- Any twin order book: not public historically.

## 5. P0 and decision (rule_mr_sweep `85f8192c` §5, unchanged)

- **Placebo:** calibration-matched disagreement placebo c_pl(d) = m(d) + (c(d′) − m(d′)), with derangements within
  (market, local hour) on the fit table. J = 20, seeds 20260921 + j.
- **Statistic:** pooled Pearson over the entries, ρ_c = ρ(c − m, e) and ρ_pl,j. **Δ = ρ_c − mean_j ρ_pl,j.**
- **Bootstrap:** B = **10,000 date-cluster draws, seed 20261024**, with draw b using j_b = b mod 20. One-sided p and a
  95% percentile interval.
- **Multiplicity:** Benjamini-Hochberg at **q = 0.10 over K = 3**. UNTESTABLE arms (< 20 covered scored dates or
  < 1,000 covered snapshots) get p = 1.
- **Survivor** iff BH rejects and Δ's lower 95% bound > 0.
- **Also reported:** ρ_c and mean ρ_pl with their intervals, the c-deranged diagnostic, and Δ by block
  (00-05, 06-09, 10-12, 13-16, 17-23) and by market.
- **Survivors only, the w gate (rule_mr `37cb46be`, `mr_gate.gate_candidate`):**
  - all hours, walk-forward w with a gap of 1 day on the grid 0..1, and placebo c_pl,0;
  - **PASS iff** mean w ≥ 0.05, blend R date upper < 1, blend − placebo upper < 0 and blend − floor-only upper < 0.
- **The three controls run first and refuse the run on any miss** (37cb46be):
  - served R 1.774 / 1.526;
  - MG-1 07-12 excess 0.0120;
  - the w = 0 identity (MG-1 and every survivor).
- A PASS (w) goes to a tradability replay only under its own rule and ledger row. Nothing is replayed here.

## 6. Fetch module contract (code pending; diff to the coordinator before any price fetch)

- **The module:** a new module, `weather.research.s31_venue_fetch` (name provisional). It writes only under its
  `--out` dir. It is light-rate: at most 1 request per second, sequential, and unauthenticated. No WebSocket, no
  account, no key. It refuses any target date after 2026-09-29.
- **Raw bodies:** a response body is parsed in memory through its allowlist. The module writes only the allowlisted
  extract, plus the sha256 and byte length of the raw body. The raw body is never written. Exception: Kalshi candle
  and ForecastEx pairs bodies for dates ≤ 09-29 are price data this rule may read, and are kept only as their
  allowlisted columns.
- **Allowlist A** (Kalshi `/markets`, V0 only): `ticker`, `event_ticker`, `strike_type`, `floor_strike`,
  `cap_strike`, `rules_primary`, `rules_secondary`, `open_time`, `close_time`. Every price, volume, open-interest,
  `result`, `settlement_value` and expiration-value field is dropped.
- **Allowlist B** (Kalshi candlesticks, `/series/{s}/markets/{m}/candlesticks` and `/historical/markets/{m}/
  candlesticks`, `period_interval=1`): `end_period_ts`, `yes_bid.close`, `yes_ask.close`.
- **Allowlist C** (ForecastEx `pairs/pairs_YYYYMMDD.csv`, target dates ≤ 09-29): `event_contract`,
  `expiration_date`, `yes_price`, `pair_time`. `quantity` and `no_price` are dropped. Rows whose
  `expiration_date` is after 2026-09-29 are dropped unparsed.
- **Market discovery:** Kalshi uses the archived `/events` pages and `/events/{t}/metadata` (tickers only).
  ForecastEx uses the S3 key listing.
- **Size, disclosed:** about 7 cities × 60 dates × 6 markets ≈ 2,500 Kalshi candle requests (about 45 min at 1/s), V0
  about 30 requests, and about 60 ForecastEx day files at ≤ 2 MB each.

## 7. Pre-registration sections

### (a) Positive control
Served vs market pooled R **1.774** (all hours) and **1.526** (00-16), dev scorecard default folds; MG-1 07-12 excess
0.0120; w = 0 identity. Any miss refuses the run (§5).

### (b) Comparator fairness
The comparator is our own market m. Each arm is an exponential tilt of m with Σc = Σm on identical rows, with no
floor and no calibration on either side. The w gate adds the same rule-4 floor-only control and placebo as rule_mr
`37cb46be`. Not raw R0.

### (c) Targeted loss slice
The market's error e = y − m on the covered markets at all hours, not a model-loss slice. For context, loss atlas
`4d094a63eb25` (ledger row 18) locates the served model's excess, not the market's. No expected size is claimed;
the P0 is kill-only.

### (d) MDE and clusters
At most 43 date clusters and 7 market clusters (KAL), or 9 market clusters (FEX), before the V0 drops. The MDE80
is not stated yet: it comes from (f)'s sigma_d in Clarification 1. Until then `prereg_check` refuses this file on (d),
by design, and nothing runs.

### (e) Dev-window reuse
DEV_WINDOW_LEDGER.md: this is candidate number 93 on 2026-07-31..09-29.

### (f) Power gate (DRAFT: fields filled by Clarification 1 before any fetch)
- **sigma_d:** to be taken, before any S31 price read, from the dev source block, as the date-level sd of the Δ
  contribution of row 78's OM-HRRR (type C, all hours) in its per-date rows (receipt `02c46630…`), restricted to the
  KAL markets. The file sha256 is recorded.
- **Remaining fields** (rho, VIF, delta, N ≤ 43, MDE80, power, class, intervals: date-clustered and block-3): pending
  in Clarification 1.
- **Launch rule:** a screen below power 0.5 is not launched (MODEL_IMPROVEMENT_METHOD §5 rule 6). The arm is then
  recorded as UNDERPOWERED, not run.

## 8. Outputs

- **Receipt:** `s31_p0.json`, never overwritten, recording:
  - code HEAD (a dirty tree refuses) and the module sha;
  - the layout manifest sha;
  - the V0 table;
  - the allowlisted-extract SHA256SUMS;
  - coverage, every statistic, the BH table and the verdicts.
- **Per-date rows:** one per (arm, date), with the sufficient sums.
- **Non-survivors:** one EXHAUSTION_REGISTER line each, drafted.

## 9. Kill and reopen line (written now)

- **If all three arms KILL:** S31 closes for capture-time twin location and scale on the same-station cities. It
  reopens only with a new construct (for example, a lead-lag arm on twin price changes) under a new rule, with its
  mechanism written first.
- **A survivor is not promotable.** It earns only a pre-registration on new dates and a forward recorder question,
  raised through master.
