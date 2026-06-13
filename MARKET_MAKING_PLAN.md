# From Model To Market Maker: The Weather MM Plan

Research date: 2026-06-12. Audited and revised same day (v2) - every economic
assumption was re-tested against live APIs; see the audit changelog below.
Live numbers were pulled from the Gamma and CLOB APIs for the June 11-13
weather events.

This document is the deep-research answer to: how do we turn the weather model
into a successful market-making bot on Polymarket weather markets?

- Step 1: a finely tuned model (the fair-value engine).
- Step 2: the market-making bot (the execution engine around it).

The two steps are not strictly serial. The bot's data layer (order-book
capture) must start now because book history cannot be backfilled, and the
bot can run in shadow/paper mode while the model accrues the settled days its
promotion gates need.

## Audit Changelog (v2, 2026-06-12)

The v1 plan was audited by re-deriving every number from live data. Material
corrections:

1. **Volume was understated 5-10x.** v1 sampled June-13 events the evening
   before their target day ($7-28k "so far"). Settled June 11 and June 12
   events show final fleet volume of **$852k and $783k** respectively, i.e.
   **~$65-71k per event-day**. The rebate-pool estimate rises accordingly.
2. **Reward competition is measurably thin.** Live books on Toronto's central
   June-13 bands held only **$14-$88 of resting notional per side within the
   4.5-cent qualifying window** (sampled overnight). Harvest-mode reward
   capture is therefore much more winnable than v1 assumed - at least in
   off-hours - but Q scores are size-weighted, so daytime capture share
   equals size share against whoever shows up. Measuring book occupancy by
   hour is now an explicit MM-0 deliverable.
3. **No naked asks exist on Polymarket.** SELL orders require conditional
   token balance. Two-sided quoting is implemented as a YES bid plus a NO bid
   (which is what the reward formula's Q_one/Q_two definitions assume). This
   sets the real capital requirement: ~$1 x size per band quoted two-sided.
4. **Taker-fee cost corrected**: fee as a fraction of notional is
   `0.05 x (1 - p)` - about 2.5% at p=0.5 but up to ~4.75% on cheap tails,
   not "up to 2.5%" as v1 said. Flattening tail inventory by taking is more
   expensive than v1 implied.
5. **pUSD verified**: rebates/rewards pay in pUSD, Polymarket's 1:1
   USDC-backed collateral token, redeemable to USDC without fees (the reward
   campaigns' `asset_address` is the pUSD contract). Not a points token.
6. **Harvest-mode quoting was redesigned.** v1 centered harvest quotes on
   model fair value clipped into the qualifying window - the worst of both
   worlds while the model is behind the market (skewed quotes get picked
   off). v2 harvest mode centers on the market mid and uses the model only
   as a veto (quote only where model and market agree; stand down on
   disagreement). Model-skewed quoting waits for proven slices (MM-3).
7. **Under-documented mechanics flagged for empirical verification in MM-2**:
   exact heartbeat interval semantics, neg-risk margining/conversion
   tooling, minimum order size thresholds, and real-time balance monitoring
   (`max order = balance - sum(open - filled)`; abusing balance checks gets
   makers blacklisted).
8. **New risks added**: reward campaigns are non-contractual and can change
   or vanish daily; today's thin competition is evidence of low competition
   today, not a moat; overnight quoting must respect forecast model-run
   release windows (00Z/06Z/12Z/18Z synoptic runs, hourly HRRR), because
   those are the overnight information events.

---

## Part 0: The Economics (Measured, Not Assumed)

### What Polymarket pays market makers

There are two separate income programs plus the trading P&L itself:

**1. Liquidity rewards (paid daily, midnight UTC, min $1 payout).**
Scored by sampling the book (10,080 samples per epoch, i.e. roughly once per
minute over a week; payouts accrue daily). Per-order score is quadratic in
proximity to the size-adjusted midpoint:

```
S(v, s) = ((v - s) / v)^2 * b
```

- `v` = market max qualifying spread (weather: 4.5 cents, verified live)
- `s` = your order's spread from the size-adjusted midpoint
- `b` = in-game multiplier

Order scores are **multiplied by order size** when summed into Q scores, so
reward share is proportional to qualifying size, not mere presence. Quoting
tighter scores quadratically better but gets picked off more - the
tightness-vs-toxicity optimum is a measured tradeoff, not a constant.

Two-sided quoting is enforced through `Q_min`:

- Midpoint inside [0.10, 0.90]:
  `Q_min = max(min(Q_one, Q_two), max(Q_one/c, Q_two/c))` with `c = 3.0`
  (one-sided quoting still earns, at 1/3 credit).
- Midpoint outside [0.10, 0.90] (i.e. weather tail bands):
  `Q_min = min(Q_one, Q_two)` - strictly two-sided or you earn nothing.
  Note the capital asymmetry this creates on tails: the NO-side bid on a
  4-cent band costs ~$0.96/share. Tail campaign rates are small anyway -
  harvest the central bands, skip the tails.

**Measured reward budgets (June 13, 2026 events):** ~$1.00/day per event
(Dallas was $5.00 that day), attached to the central 3-5 bands only
(verified: 53 of 132 bands carried campaigns). Fleet total: **~$16/day**.

**Conclusion: liquidity rewards are a subsidy, not a business.** They pay for
infrastructure and force good quoting discipline (two-sided, tight,
persistent, sampled every minute including overnight). The measured
thin books mean a min-size quoter can plausibly capture most of this in
off-hours - but $16/day is still $16/day. Treat as cost offset.

**2. Maker rebates (paid daily in pUSD, min $1).**
Weather is a fee-charging category: takers pay
`fee = C * 0.05 * p * (1 - p)` (C = shares, p = price; as a fraction of
dollar notional that is `5% x (1 - p)`). Makers never pay fees and 25% of
the taker fee pool is redistributed to makers, weighted by the
fee-equivalent of each maker's **executed** maker volume.

Sizing with measured volumes: at ~$65-71k/event/day and an effective fee of
~1.5-3.5% of notional (mix-dependent across band prices), each event
generates roughly **$1.0-2.5k/day in taker fees**, so a **$250-600/day
rebate pool per event, ~$3-7k/day fleet-wide**. (Assumes Gamma `volumeNum`
is single-counted trade notional; verify against our own fill accounting in
MM-2.) Capturing any of it requires being the maker on executed flow - the
pool is real, but it is paid for getting filled, and every fill carries
adverse-selection risk. Rebates reward the same behavior that loses money
against informed flow; they tilt the economics, they do not remove the need
for the model.

**3. Trading P&L (the actual prize).**
A maker quoting two-sided earns spread from uninformed flow and loses to
informed flow. With a model that is better-calibrated than the market in
specific windows, quotes can be skewed so being filled is itself
positive-EV. This is where Step 1 converts to money. The measured structure
- $65k+/event/day trading through books holding under $100 per side within
the qualifying window - implies extremely high book turnover by small,
fast-refreshing quoters. Flow is there; the question MM-1 must answer is
what fraction is informed.

### Microstructure facts that shape the strategy (all verified live)

- Tick size 0.001 on weather bands; books are penny-fine and tight at top
  (1-2 ticks) but very thin within the reward window.
- `rewardsMinSize` 20-50 shares; `rewardsMaxSpread` 4.5 cents.
- Weather events are `negRisk: true`: bands are a mutually exclusive group
  with cross-band conversion support - the natural inventory hedge
  (verify adapter tooling in py-clob-client during MM-2).
- **No naked shorting**: an "ask" you do not have inventory for is posted as
  a bid on the complementary NO token. Two-sided min-size quoting on one
  band costs ~`size x $1` of capital (YES bid at p + NO bid at 1-p).
  Fleet-wide harvest at min size across ~5 central bands x 12 events:
  roughly **$3k of working capital**, cycling daily through settlement.
- Balances are monitored in real time; resting orders must stay backed
  (`max order = balance - sum(openOrderSize - filledAmount)`); intentional
  abuse of balance checks is a blacklisting offense.
- Daily markets mean capital recycles every day: automated post-resolution
  redemption (pUSD) is an operational requirement, not a nicety.

---

## Part 1: Step 1 - The Finely Tuned Model

The repo's own evidence says the model is close but not yet ahead. From the
2026-06-10 gap decomposition (`data/backtest/gap_decomposition.md`, after the
replay-harness band bug was fixed): replayed fleet Brier **0.0383 vs market
0.0325** (+0.0058/row). The gap is *located*, which is what makes this
tractable:

- **US F-family markets carry 88% of the gap** (Toronto mid-day already beats
  the market; evenings are solved in both families).
- **Mornings/overnight carry ~half the gap**, consistent with the
  forecast-tracker verdict (model gives 45% to reaching the morning
  consensus forecast; market 66%; realized 71% - the model under-calls).
- **Central at-settle / 1-off bands** carry over 100% of the remainder (the
  model wins the 2-off tails already).

That ordering produces the Step 1 work queue. Everything below already has
its harness built (replay corpus, pinned promotion gauntlet, per-market trust
gates) - the work is tuning and accrual, not new infrastructure.

### 1A. Close the US morning sharpness gap (highest-leverage tuning)

- The pooled F-family band model is already SHADOW_ONLY with aggregate replay
  Brier 0.0515 vs current 0.0686 (`pooled_candidate_replay_v0_3_report.md`).
  Its promotion is blocked by evidence accrual (1 settled day, 15/100 trust
  per F market), not by model quality. `src.promotion_refresh` automates the
  flip when days accrue. Priority: keep the loop healthy so days accrue.
- Forecast-anchored morning calibration: the forecast tracker says trust the
  morning consensus more at 0-10h cutoffs. Implement as a calibration-layer
  pull measured on the replay corpus, gated by the pinned A/B.
- Item 34 per-market calibration activates per city as soon as each has >=2
  complete days. Calendar-gated; the bot work does not wait for it.

### 1B. Central-band discrimination (the at-settle/1-off gap)

- ROADMAP item 35 (continuous-density model): a fine temperature density
  discretized to native bands directly attacks 24-vs-25 / 84-85-vs-86-87
  discrimination - exactly the bands where the reward campaigns, the volume,
  and the MM inventory risk all live.
- Near-term cheaper win: settlement-lag artifacts are already per-market
  (catch-up rates 31%-99% by city); ensure central-band hedging uses them
  everywhere.

### 1C. What "finely tuned" must mean for an MM bot (acceptance bar)

A market maker does not need to beat the market everywhere. It needs:

1. **Calibration you can quote on**: by-hour, by-band reliability such that
   fair value +/- a computed uncertainty is honest. (Toronto already at ECE
   ~0.007 on clean days.)
2. **A known-edge map**: the per-market / per-hour / per-band-distance slices
   where replayed model Brier <= market Brier. Quote tight and skewed inside
   the map, wide or market-mid-anchored outside it. The gap decomposition is
   this map; keep it regenerated as days settle.
3. **Per-market serving gates**: the promotion gauntlet (PASS/SHADOW/BLOCK)
   becomes the bot's permission system. Empirical-only markets get harvest
   quoting at minimum size; PASS markets get model-skewed quoting at size.
4. **Intra-hour freshness** (item 40, shipped v0.5.7): the quote engine
   inherits the live-reading features; the ~52-minute staircase lag behind
   the market is largely closed. Re-measure from book data once captured.

### 1D. Model-side gaps that specifically threaten an MM bot

- **Cadence mismatch, the structural one**: the model loop refreshes every
  10 minutes; a quote engine refreshes every 10-30 seconds. Between model
  refreshes the bot would quote a frozen fair value while the market moves
  on live obs. The quote engine therefore needs its own **fast-path obs
  watcher** (METAR/SWOB/wu_current polled at ~1-minute cadence) whose only
  job is: pull or widen quotes the moment an observation prints that the
  current fair value has not seen. This is a new component, not a tweak to
  the snapshot loop.
- **Stale-source quoting risk**: per-source TTLs (item 17) are still open.
  The bot must consume source freshness as a first-class input and
  widen/pull quotes when feeds age.
- **best_bid is 48% filled in our tapes and we persist no book depth** - we
  currently cannot measure what our fills would have been. Phase MM-0 fixes
  this and is already the roadmap's P0 (items 37/38).
- **Settlement disputes**: may-27-style WU revisions are rare but real. The
  settlement ledger reconciled 57/57 against Polymarket resolutions - keep
  that reconciliation as a hard nightly check once real money is at stake.

---

## Part 2: Step 2 - The Market-Making Bot

### 2A. Platform mechanics the bot is built on

**API surface** (verified against current docs):

- REST CLOB: `clob.polymarket.com`. Orders are EIP-712 signed; L1 (private
  key) derives API creds; L2 (HMAC) authenticates trading calls. Python SDK:
  `py-clob-client-v2` (matches our stack).
- Wallet: pUSD (1:1 USDC-backed) on Polygon with exchange allowances;
  signature types support EOA and Polymarket proxy wallets.
- Order types: GTC, GTD (1-minute minimum expiry buffer), FOK, FAK, plus
  **post-only** (rejected instead of crossing - the MM default).
- Discovery: Gamma event payload carries `clobTokenIds`, `conditionId`,
  `negRisk`, `rewardsMinSize`, `rewardsMaxSpread`, `orderPriceMinTickSize`
  per band. Reward campaigns: `GET /rewards/markets/current` (paginated).
  Earnings tracking: `GET /rewards/user` family of endpoints - reconcile
  these against our own Q-score accounting daily.
- Market data WebSocket: `wss://ws-subscriptions-clob.polymarket.com/ws/market`
  - `book`, `price_change`, `tick_size_change`, `last_trade_price`, and
  `best_bid_ask` with `custom_feature_enabled: true`.
- User WebSocket: `.../ws/user` - order lifecycle and fills
  (MATCHED -> MINED -> CONFIRMED / RETRYING / FAILED). Server-side only.
- **Heartbeats: `POST /heartbeats`.** Documented behavior: stop sending and
  all open orders cancel (~10s + 5s buffer per the orders overview; the
  endpoint page does not document the exact interval or opt-in semantics -
  **verify empirically in MM-2 before relying on it**). This is the
  dead-man switch; `DELETE /cancel-all` is the manual kill switch.
- Rate limits are far above our needs (5,000 order posts / 10s burst; /books
  at 500 req / 10s). A 12-event fleet quoting ~6 bands each at 10s cadence
  is ~300 requests / 10s including cancels.

**Jurisdiction/account note (hard gate for live orders):** Polymarket now
operates a separate US-regulated platform (docs.polymarket.us) alongside the
global one; terms, fees, and rewards may differ. Ontario residents have
historically been restricted on the global platform. Confirm account
eligibility and choose the operating entity/wallet before MM-2. None of the
technical plan changes; live deployment waits on this.

### 2B. Strategy design: informed maker, binary settlement

The Avellaneda-Stoikov frame (reservation price + spread from inventory and
volatility) adapts with weather-specific twists:

1. **Two quoting regimes, explicitly separated.**
   - *Harvest regime* (default, SHADOW/empirical markets, unproven hours):
     center quotes on the **market mid**, min size, within the qualifying
     window. The model is a **veto**, not the center: quote only where
     |model fair value - mid| is small relative to model uncertainty; stand
     down (or in MM-3, take) where they disagree. Never center harvest
     quotes on a fair value the gauntlet has not validated.
   - *Edge regime* (PASS markets/windows in the known-edge map): center on
     model fair value, skew with inventory, size up. The divergence between
     fair value and mid is the alpha; when it exceeds the taker fee plus
     margin, taking (FAK) beats quoting.
2. **Spread = f(model uncertainty, time-to-settlement, obs volatility,
   freshness)**: wider when the known-edge map says we are blind (US
   mornings today), within +/- N minutes of an expected WU print or METAR
   special, when any input source is stale, on bands near the current high
   late-day (one print resolves the market), and around forecast model-run
   releases (00Z/06Z/12Z/18Z synoptic, hourly HRRR) - the overnight
   information events that make "quiet" hours not actually quiet.
3. **Inventory management is neg-risk-aware.** Within one event, adjacent
   bands partially hedge; true exposure is the position-weighted temperature
   distribution vs the model's density. Cap per-event exposure in expected
   settlement P&L terms; skew quotes to mean-revert it. Flattening by
   taking costs `5% x (1 - p)` of notional in fees (worst on tails), so
   prefer skew-to-flatten except on kill conditions.

**Adverse-selection defense** (who picks us off and how we counter):

| Threat | Defense |
| :--- | :--- |
| Faster obs watchers (METAR/SWOB before WU prints) | Fast-path obs watcher pulls quotes on new prints (1-min cadence); item-40 live-reading features in fair value; widen around scheduled print windows |
| Forecast-run jumps | Forecast-disagreement feature (schema v0.4); widen at known release times; overnight quoting respects run schedule |
| Stale-quote sniping when our feed dies | Heartbeat session (auto-cancel ~10-15s); per-source freshness gates; fast-path watcher failure = cancel-all |
| End-of-day lock-in (high already printed) | Settlement-lag + lock-in artifacts (v0.5.6); refuse to quote the no-longer-possible side beyond learned catch-up bounds |
| Other reward harvesters competing size | Measured, not assumed: MM-0 book-occupancy-by-hour report; concentrate harvest in measured-thin hours |

### 2C. The build, phased with gates (roadmap-style)

**Phase MM-0: Book capture + competitor recon (no keys, no orders). NOW.**

- Persist `clobTokenIds`/`conditionId` into snapshot rows (trivial; Gamma
  payload already fetched).
- Standalone `market_book_recorder` under the existing supervisor pattern:
  REST `/books` poll every 60s as the guaranteed baseline, WebSocket market
  channel for event-driven deltas on top (resync from REST on every
  reconnect), append-only `book_long.csv` + `books.jsonl` per event: ts,
  token, book hash, top-5 levels both sides, depth, spread, midpoint,
  imbalance, executable price at $50/$200/$500, last trade. 10-15s REST
  cadence within 2h of settlement-decisive hours.
- **Competitor recon deliverable**: a report over the captured books -
  resting size within the 4.5-cent window by hour and band, quote refresh
  patterns, depth at top vs window. This decides where harvest mode can
  win and replaces the v1 assumption with measurement.
- Acceptance: 7 consecutive days, all 12 events, no book gap > 2 minutes;
  fleet-observability alerts on recorder gaps; recon report generated.

**Phase MM-1: Shadow maker (still no orders).**

- Quote engine computing, every 10-30s per band: fair value, uncertainty,
  regime (harvest/edge/stand-down), intended bid/ask/size - written to a
  `quotes_long.csv` tape alongside the book tape.
- Offline fill simulation against recorded books, **pessimistic by
  construction**: count a fill only when a trade prints strictly through
  our intended price (not at it - queue position is unknowable), and assume
  we are last in queue at our level. Score realized markout (mid at +5m,
  +30m, settlement vs would-be fill), reward Q-share (apply the published
  formulas against the sampled books, including competitor size), and
  rebate share (our simulated maker volume vs observed taker volume).
- Acceptance to MM-2: simulated P&L (markout + rewards + rebates) positive
  over >= 14 days under the pessimistic fill rule, with model gates honored;
  plus the jurisdiction gate cleared.

**Phase MM-2: Live, harvest mode (minimum risk, market-mid-anchored).**

- Live keys, heartbeat session (empirically verify cancel-on-silence
  behavior on day one with throwaway orders), post-only GTC quotes at
  `rewardsMinSize` on the campaign bands of 2-3 events, two-sided
  (YES bid + NO bid), market-mid-anchored with model veto. Working capital
  ~$50/band. Strict caps: per-band shares, per-event $, fleet $, max daily
  loss; cancel-all + alert on any breach. Automated daily redemption of
  settled positions.
- Goals: (a) validate order lifecycle, fills, redemption, and that rewards
  + rebates paid match our own Q-score/fee accounting; (b) measure REAL
  adverse selection (live markout vs shadow-simulated - the difference is
  what simulation missed); (c) verify balance monitoring, neg-risk
  tooling, and min-size thresholds empirically.
- Acceptance to MM-3: 14+ days live, accounting reconciles, realized
  markout within tolerance of simulation, zero uncontrolled-risk incidents.

**Phase MM-3: Model-skewed market making (the real strategy).**

- Mandate per market from the gauntlet + known-edge map: PASS markets get
  edge-regime quoting at size; SHADOW stays harvest; BLOCK gets nothing.
  Inventory skew and neg-risk conversion live. Taking (FAK) only when
  divergence > taker fee + margin in proven slices.
- Every model promotion that flips a market to PASS automatically widens
  the bot's mandate (`promotion_refresh` per-market actions are the bot's
  config input).
- Acceptance: trading P&L net of everything positive over a month with
  exposure caps respected; Brier-vs-market and markout improving together.

**Phase MM-4: Scale and harden (item 37 MLOps).**

- All 12 events; dynamic cadence near settlement; nightly
  retrain -> gauntlet -> mandate refresh; drift detection (markout
  degradation = someone got faster - investigate before resizing); capital
  efficiency via neg-risk conversions; rewards/rebates/redemption
  accounting in the daily fleet report.

### 2D. What we measure (the bot's own backtest discipline)

- **Markout curves** per fill (t+1m/5m/30m/settle) by market, hour, band
  distance, quote age, and regime. The execution-side Brier score.
- **Fill toxicity**: share of fills within N minutes before a WU print /
  METAR special that moved the band. Should fall as defenses improve.
- **Reward + rebate yield** vs theoretical max for quoted size, reconciled
  against the rewards API and actual pUSD payouts.
- **Inventory paths**: time-to-flat after skew, cost of flattening.
- Extend `src.backtest` with an execution-aware section once book tapes
  exist: replace "model vs mid price" with "model vs executable price at
  size" - the honest version of edge.

---

## Part 3: Sequencing, Capital, And Expected Returns

```
Now        MM-0 book recorder + token-id persistence        (days)
           ... runs unattended; recon report after 7 days ...
Next       Step 1A morning-forecast calibration pull        (replay-gated)
           MM-1 shadow quote engine + pessimistic fill sim  (1-2 weeks)
           Jurisdiction/account resolution                  (parallel)
Then       MM-2 live harvest on 2-3 events (~$500 capital)
           Step 1A/34 per-market calibration as days accrue (calendar-gated)
Later      MM-3 model-skewed MM, mandate tied to gauntlet
           Step 1B continuous-density model (item 35)
           MM-4 fleet scale + MLOps hardening
```

Honest return arithmetic (to be replaced by MM-1 measurements):

- Harvest mode, fleet-wide, min size: capital ~$3k; income = some fraction
  of $16/day rewards + rebate share on min-size fills - small absolute
  dollars. Its value is validation and measurement, not profit.
- The scalable prize: a fleet rebate pool estimated at $3-7k/day plus
  spread/skew P&L on $780-850k/day of fleet volume. Capturing even a
  single-digit percent of daily volume as the maker, with positive markout
  from model skew, is where this pays for itself. Whether that capture is
  achievable at acceptable toxicity is exactly what MM-1/MM-2 measure
  before size is committed.

## Part 4: Honest Risk Register

1. **The model is currently behind the market on aggregate** (0.0383 vs
   0.0325 replayed). The plan never requires pretending otherwise: harvest
   mode is market-mid-anchored with the model as veto, and skewed size only
   follows per-slice proof. The known-edge map, not optimism, sets the
   mandate.
2. **The subsidy is not contractual.** Reward campaigns and rebate rates can
   change or vanish any day (campaign records carry start/end dates; rates
   varied across our own observations). Today's thin reward competition is
   evidence about today, not a moat - visible easy yield attracts bots. The
   durable edge is the model; everything else is rent that must be
   re-measured continuously.
3. **Adverse selection from faster weather bots** is the existential MM
   risk, and weather flow may skew informed (the people trading daily
   temperature markets are not noise traders). Zero live measurement exists
   until MM-0/MM-1 produce markout data. Do not skip the shadow phase; do
   not trust optimistic fill simulation (trade-through fills only).
4. **Binary settlement risk**: a late-day quote left up through a decisive
   WU print is a total loss on that band. Heartbeats, print-window pulls,
   and lock-in artifacts are the mitigations; test them in shadow against
   recorded staircase days (June 9 Toronto is the canonical case).
5. **Mechanics verified only on paper** until MM-2: exact heartbeat timeout,
   neg-risk conversion tooling, min order thresholds, balance-monitoring
   behavior under multi-market quoting, rewards/rebate payment reconciliation,
   and the `volumeNum` single-counting assumption behind the pool estimates.
   Each gets an explicit verification step in MM-2.
6. **Operational**: the 2026-06-10 silent loop death and the June 11
   432-minute gap show the supervisor pattern must extend to the recorder,
   the fast-path watcher, and the quoting engine with the same
   ensure/heartbeat rigor - and the CLOB heartbeat makes order safety
   fail-closed even when our side dies. The fast-path watcher dying while
   quotes rest is the worst silent failure; its liveness must gate quoting.
7. **Compliance/eligibility** (global vs US platform split, Ontario
   restrictions) is a hard gate for live trading.

## Part 5: From Here To Live - The Detailed Execution Plan

This section turns the phases into buildable units in this repo's
conventions (managed loops, append-only tapes, reports under
`data/backtest/`, pinned A/B gates), then answers the two operating
questions directly: *how do we get to paper trading* and *when do we know we
are ready for real testing*.

### Stage 0: Capture (build days 1-3, then runs unattended)

New module `src/market_book_recorder.py`:

- Discovers tokens from the Gamma payload the snapshot loop already fetches
  (`clobTokenIds`, `conditionId` per band; persist both into snapshot rows
  while in there - that closes the data-layer audit P0).
- **REST-first**: poll CLOB `/books` for all active weather tokens every 60s
  (well inside the 500 req/10s limit). This is the guaranteed baseline tape.
  WebSocket deltas (`book`, `price_change`, `last_trade_price`) layer on
  afterward for event resolution; resync from REST on every reconnect. Do
  not blocker the baseline on WS correctness.
- Writes per event folder, append-only:
  - `book_long.csv` - one row per token per capture: ts, token, side-aggregated
    top-5 levels, depth within 4.5 cents (total and >= min-size only),
    spread, midpoint, size-adjusted midpoint, imbalance, executable price at
    $50/$200/$500.
  - `trades_long.csv` - last-trade events (price, size, side, ts) from WS;
    this is the tape the fill simulator replays against.
  - `books.jsonl` - raw book snapshots with hashes for audit/rebuild.
- Runs under the existing supervisor pattern: `--loop`, `--status`,
  `--ensure`, heartbeat into `loop_status.json`, diagnostics on failure,
  registered in the Task Scheduler script next to the snapshot loop.
- `tests/test_market_book_recorder.py`: schema stability, append safety on
  existing files, executable-price math, gap detection, token discovery.

CLI sketch:

```powershell
.\venv\Scripts\python.exe -m src.market_book_recorder --loop --interval-seconds 60
.\venv\Scripts\python.exe -m src.market_book_recorder --status
```

### Stage 1: Recon (after ~7 days of tape)

New module `src/book_analytics.py` writing
`data/backtest/book_recon_report.md`:

- **Reward-competition map**: qualifying resting size (>= `rewardsMinSize`,
  within 4.5 cents of size-adjusted mid) by market, band, and hour-of-day.
  Output: estimated harvest Q-share for a min-size two-sided quoter, by hour.
  This decides where and when harvest mode quotes.
- **Toxicity priors**: for every observed trade, markout of the passive side
  at +1/+5/+30 minutes - measures how informed the existing flow is before
  we risk anything.
- **Spread/turnover stats**: effective spread, top-of-book lifetime, depth
  replenishment speed - tells us what refresh cadence competition runs at.
- **Honest model-vs-market rescore**: join book mids to our snapshot fair
  values and regenerate the known-edge map against *real, executable* mids
  instead of the 48%-filled Gamma `best_bid`. This may move the measured
  model-market gap in either direction - it is the first deliverable that
  improves Step 1 with Step 2's data.

### Stage 2: The quoting stack (shadow only - this IS paper trading setup)

Three new modules, all key-less:

1. `src/mm_policy.py` - **pure decision function**, fully unit-testable:
   inputs (per-band fair value + uncertainty, book state, simulated
   inventory, freshness flags, regime map, caps) -> desired quote set
   (band, side, price, size, regime, reason-code). All the strategy logic
   from Part 2B lives here and nowhere else: harvest = market-mid anchored
   with model veto; edge = model-centered skew (disabled until MM-3);
   print-window pulls; staleness widening. Reason-codes make every quote
   decision auditable later.
2. `src/obs_watcher.py` - the fast path: polls METAR/SWOB/wu_current at
   ~1-minute cadence (these are different endpoints from the 10-minute
   model loop and the load is trivial), emits a freshness/event state file
   the policy consumes. New decisive print -> policy output flips to
   pull/widen on the next engine tick. Runs under the supervisor; its
   liveness gates quoting later (dead watcher = no quotes).
3. `src/quote_engine.py` - the loop (10-30s tick): assembles policy inputs
   (latest model fair values from the snapshot loop's most recent build,
   adjusted by the obs watcher state; latest recorded book), calls
   `mm_policy`, and writes intentions to `quotes_long.csv` per event:
   ts, band, bid/ask price+size, regime, fair value, uncertainty, veto
   state, reason. In live mode (MM-2+) the same engine gains an execution
   adapter; the tape format does not change.

### Stage 3: Paper trading (two loops, run for >= 14 days)

Paper trading is the combination of the Stage 2 stack with two evaluators:

1. **Replay paper trading** (`src/fill_simulator.py`) - for fast iteration:
   re-run `mm_policy` variants over *frozen* captured book/trade days.
   Fill rule is pessimistic by construction: a simulated quote fills only
   when a recorded trade prints **strictly through** its price (never "at"
   - queue position is unknowable), and at most the printed trade size.
   Tracks simulated inventory, settlement P&L, markout per fill, reward
   Q-share per sampled minute (our simulated quotes scored by the published
   formula against the *recorded* competitor book), and rebate share
   (our simulated maker volume x fee formula x 25% x pool share).
   Discipline (learned the hard way in replay work): **A/B only on frozen
   day sets** - never compare runs over a corpus the recorder is still
   appending to. Tune on one set of days, validate on held-out days.
2. **Live-forward paper trading** (`src/mm_paper_report.py`) - for honest
   validation: every night, score yesterday's *actually written*
   `quotes_long.csv` (produced in real time, so zero lookahead) against
   yesterday's book/trade tape with the same fill simulator, and emit
   `data/backtest/mm_paper_report.md`: P&L decomposed into spread capture,
   adverse selection (markout), rewards, rebates; toxicity metrics; per
   market/hour/band-distance/regime slices; quote uptime; pull latency on
   print events. This nightly report is the bot's equivalent of the
   settlement-scored backtest - the number that decides go-live.

Iteration loop while paper trading runs: weekly, take the worst slices from
the paper report (a market, an hour window, a band distance), adjust
`mm_policy` parameters or the known-edge map, validate on held-out frozen
days, ship the policy change, and watch the next live-forward week. Model
work (Step 1A morning calibration, item 34 per-market artifacts) lands in
parallel and shows up in the same report as improved veto/edge regimes.

### Stage 4: The Go-Live Gate - "when do we know we are ready?"

Live testing (MM-2, real keys, min size) starts when ALL of the following
are green. Provisional thresholds below are set conservatively and should be
re-derived from the Stage 1 recon report; the *structure* of the gate is the
commitment:

**Data and infrastructure**
- [ ] 14+ consecutive days of book capture, all 12 events, no gap > 2 min,
      recorder + obs watcher under supervisor with fleet-observability
      alerts (their uptime >= 99% over the window).
- [ ] Recon report generated and reviewed; harvest hours/bands chosen from
      measured competition, not assumption.

**Paper performance (live-forward, pessimistic fills)**
- [ ] >= 14 consecutive live-forward paper days with net positive total
      P&L (spread + markout + rewards + rebates) and >= 60% of days
      positive.
- [ ] Mean markout at +30 min on harvest-regime fills no worse than
      -0.5 cents/share (i.e., spread + rebate demonstrably covers adverse
      selection at min size).
- [ ] Zero simulated quotes resting through a decisive WU print in the
      final 10 days (print-window pull logic demonstrably works, including
      on at least one staircase-type day like 2026-06-09 Toronto).
- [ ] The window must include at least one busted-forecast day and one
      weekend; if nature does not provide one, extend the window.

**Model gates**
- [ ] Per-market mandate map produced from the promotion gauntlet
      (PASS/SHADOW/BLOCK -> edge/harvest/none) and consumed by `mm_policy`
      from `f_family_promotion_refresh.json`, not hand-edited.
- [ ] Known-edge map regenerated against real book mids (Stage 1), and the
      morning under-calling either fixed (Step 1A shipped through the
      pinned gate) or mornings excluded from quoting windows in config.

**Operational drills (rehearsed, not assumed)**
- [ ] Kill-switch drill: kill the engine process; verify all orders would
      cancel via heartbeat lapse within 15s (drill executes for real on
      MM-2 day one with throwaway orders far from the mid).
- [ ] Stale-feed drill: stop the obs watcher; engine must pull all quotes
      within one tick and alert.
- [ ] Cancel-all and manual pause paths tested; runbook written (start,
      stop, flatten, redeem, reconcile).

**Account, capital, compliance**
- [ ] Jurisdiction/eligibility resolved; operating wallet chosen.
- [ ] Dedicated wallet funded with isolated risk capital (~$500 for the
      2-3 event pilot; never the full bankroll), allowances set, API creds
      derived and stored outside the repo.
- [ ] Caps wired and unit-tested in code (per-band shares, per-event $,
      fleet $, daily loss halt), not just documented.

**MM-2 day-one protocol** (the first real-money hour is itself a test):
heartbeat-lapse verification with a throwaway order; min-size and tick
rejection probes; one tiny two-sided quote on one band; verify fill
lifecycle on the user WS, balance accounting, and next-day reward/rebate
payouts against our own predicted Q-share before scaling to the 2-3 event
pilot. Live-forward paper trading keeps running in parallel forever - it is
the counterfactual that tells us what execution is costing.

### Indicative calendar (gated by evidence, not dates)

```
Week 1      Stage 0 build + token persistence; recorder running under
            supervisor; paper-trade scaffolding started
Week 2      7-day tape -> Stage 1 recon report; quote engine + policy v0
            shadow-quoting; first replay paper results on frozen days
Weeks 3-4   Live-forward paper trading nightly; policy iteration weekly;
            Step 1A morning calibration through the pinned gate;
            jurisdiction/account workstream in parallel
Week 5+     Go-Live Gate review. If green: MM-2 day-one protocol, then the
            2-3 event live pilot at min size (~$500 capital)
Week 7+     If MM-2 acceptance holds 14 days: begin MM-3 on any
            gauntlet-PASS slices; scale per Part 2C
```

The honest expectation: roughly two weeks of building, then the calendar is
owned by evidence accrual - 14 clean paper days plus however long the
jurisdiction question takes. Real-money testing earlier than ~5 weeks out
would mean skipping a gate, and every gate exists because some measured
fact (toxic flow, thin liquidity, print risk, silent loop death) says
skipping it is how this loses money.

## Appendix: Primary Sources

- Liquidity rewards mechanics: https://docs.polymarket.com/market-makers/liquidity-rewards
- Maker rebates (weather = 25%): https://docs.polymarket.com/market-makers/maker-rebates
- Fees (weather taker fee 0.05, fee formula): https://docs.polymarket.com/trading/fees
- Order types / post-only / heartbeat warning: https://docs.polymarket.com/trading/orders/overview
- Order creation, balance rules: https://docs.polymarket.com/trading/orders/create
- Heartbeat endpoint: https://docs.polymarket.com/api-reference/trade/send-heartbeat
- Rewards config endpoint: https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations
- Rate limits: https://docs.polymarket.com/api-reference/rate-limits
- Market WS channel: https://docs.polymarket.com/market-data/websocket/market-channel
- User WS channel: https://docs.polymarket.com/market-data/websocket/user-channel
- pUSD: https://docs.polymarket.com/concepts/pusd
- Live verification 2026-06-12 via `gamma-api.polymarket.com` and
  `clob.polymarket.com` (`/rewards/markets/current`, `/book`): June 11/12
  settled volumes, June 13 reward campaigns and book depth.
- Internal evidence: `data/backtest/gap_decomposition.md`,
  `data/backtest/data_layer_audit_report.md`,
  `data/backtest/pooled_candidate_replay_v0_3_report.md`,
  `data/backtest/forecast_vs_realized.md`, ROADMAP items 33-40.
