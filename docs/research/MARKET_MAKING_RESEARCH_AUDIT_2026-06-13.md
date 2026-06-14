# Market Making Research Audit

Research date: 2026-06-13 local / 2026-06-14 UTC.

Starting point: `docs/research/MARKET_MAKING_PLAN.md`.

Scope: proper market-making technique, quantitative/statistical validation,
position sizing, execution simulation, Polymarket mechanics, and weather-specific
information risk. This is a research artifact only; no code was changed.

## Executive Verdict

The current plan is directionally strong. Its largest strengths are the
right separation between harvest quoting and model-edge quoting, the insistence
on book capture before paper trading, the use of markouts instead of headline
P&L, and the decision to gate edge-regime quoting by model-vs-market evidence.
Those choices line up with the core market-making literature: spread capture is
compensation for inventory risk, adverse selection, order-processing cost, and
competition, not free yield.

The main upgrades this audit recommends are:

1. Make queue position and latency first-class in the paper simulator. Trade-
   through-only fills are a good conservative start, but the literature says
   queue position can be worth a material fraction of the spread.
2. Turn position sizing into explicit formulas: per-band max loss, per-event
   distribution exposure, daily drawdown halt, and fractional-Kelly sizing only
   after observed live-forward edge is statistically credible.
3. Treat maker rebates and liquidity rewards as endogenous incentives that can
   increase toxic fills. Rebate-adjusted EV must be scored after adverse
   selection, not before.
4. Add statistical anti-overfit controls to the market-making policy loop:
   frozen-day validation sets, walk-forward/live-forward paper results, deflated
   Sharpe or equivalent multiple-test adjustment, and slice-level confidence
   intervals before increasing size.
5. Use the new disagreement casebook and CLOB recorder as the bridge from model
   research to quoting policy. The casebook's current losing families
   (`WU lag/catch-up miss`, `stale source`, `forecast miss`, `boundary/rounding`,
   `market lead`) map directly to quote widen/pull rules.
6. Resolve a local evidence inconsistency before live trading: the plan says CLOB
   token persistence shipped, but the current `data/backtest/data_layer_audit_report.md`
   still says `Market token IDs persisted: False`. That is not a theory issue,
   but it is a hard pre-live verification gap.

## Current Plan Audit

### What The Plan Gets Right

- **Regime separation is correct.** Classical optimal market-making models
  assume a fair value or reference price plus inventory skew. The current plan's
  harvest mode refuses to center quotes on an unproven model and uses the model
  only as a veto. That is the right response while the aggregate model Brier
  remains behind Polymarket.
- **Book capture is not optional.** Limit-order strategy cannot be backtested
  from midpoint-only or best-bid-only data. Full depth, trades, quote age,
  queue assumptions, and feed latency determine whether apparent edge survives.
- **Markout is the correct execution score.** For market making, immediate fill
  P&L is misleading. Post-fill price movement and settlement outcomes reveal
  whether fills were toxic.
- **Inventory is recognized as a distribution, not a scalar.** Weather bands in
  one event are mutually exclusive and negative-risk-related. Exposure should be
  tracked over the full event temperature distribution, not only by token count.
- **Heartbeat and fail-closed behavior are central.** Stale quotes are the
  fastest path to a binary total loss around observation prints.
- **The model gate is honest.** Current local evidence says the model is not yet
  ahead overall: `gap_decomposition.md` reports market Brier around 0.0325 and
  replayed model Brier around 0.0386 on the June 10 corpus; the pooled F-family
  v0.3 replay improved the incumbent but still trailed market Brier. Edge-mode
  size must stay per-slice, not global.

### What Needs Tightening Before Live Orders

- **Queue-position model.** The plan's pessimistic trade-through fill rule is
  a safe floor, but it cannot estimate missed fills, partial fills, or the value
  of being early in queue. Add a second simulator mode that uses recorded book
  deltas to approximate queue depletion and cancellation. Keep the trade-through
  mode as the conservative promotion gate.
- **Latency budget.** Every quote decision should carry timestamps for model
  input age, book age, order submission age, and source observation age. Quote
  permission should fail closed when any budget is stale.
- **Position sizing math.** The plan names caps but does not yet define a
  formula. Use a hierarchy:
  `min(reward-min-size target, per-band loss cap, per-event distribution cap,
  daily drawdown cap, fractional Kelly cap)`.
- **Rebate accounting.** Maker rebates should be decomposed into:
  theoretical fee-equivalent, realized maker fee-equivalent, market rebate pool,
  our pool share, and adverse-selection markout. Never report rebates without
  net markout.
- **Reward competition drift.** Thin books are not a moat. Market makers visible
  in the reward window attract other market makers. The Stage 1 recon report
  should be refreshed on a rolling basis, not treated as a one-time gate.
- **Source-event timing.** The roadmap now has item 42 for fast observation-
  triggered recompute. A future quote engine should not trust 10-minute model
  cadence for sub-minute CLOB quotes.
- **US/global API split.** Polymarket global and Polymarket US docs now show
  different incentive mechanics. The operating entity, account eligibility,
  and exact API/reward rules must be verified immediately before live trading.

## Technique Notes For This Bot

### 1. Quote Only When Expected Value Survives All Costs

For a binary YES quote at price `q` with fair probability `p`, naive edge is
`p - q` for a buy. That is not enough for market making. The quote needs:

```text
expected_edge
  = fair_value_edge
  + expected_spread_capture
  + expected_rebate
  + expected_liquidity_reward
  - expected_adverse_selection_markout
  - expected_inventory_penalty
  - expected_flattening_fee
  - operational_error_buffer
```

The minimum acceptable edge should be larger near:

- fresh WU/METAR/SWOB prints,
- HRRR/RAP/model-run updates,
- late-day bucket-boundary lock-in points,
- stale source states,
- wide or fast-moving CLOB books,
- markets where the model is not ahead on settled evidence.

### 2. Use Reservation Price, But Adapt It To Binary Settlement

The Avellaneda-Stoikov family gives a useful mental model:

- reservation price moves away from accumulating more inventory,
- spreads widen with risk, volatility, and lower fill quality,
- order arrival rates depend on quote distance.

For weather binaries, the reference price should not be a Brownian stock mid.
Use the model's settlement probability density in edge regimes and the market
mid in harvest regimes. Inventory penalty should be computed as event-level
settlement P&L across all mutually exclusive bands:

```text
event_inventory_risk
  = stdev_over_model_density(position_value_if_each_band_wins)
```

This is more useful than counting shares because adjacent bands and NO tokens
can be correlated through negative-risk conversion.

### 3. Position Sizing Should Be Evidence-Weighted And Capped

Full Kelly is too aggressive for this system because probability estimates,
fill assumptions, and rebate pools are all uncertain. Use fractional Kelly only
after live-forward paper and MM-2 fills produce credible edge estimates.

Recommended sizing stack:

```text
raw_fractional_kelly = kelly_fraction(edge_distribution) * 0.10 to 0.25

quote_size = min(
    rewards_min_size_or_campaign_target,
    bankroll * raw_fractional_kelly / worst_case_band_loss,
    per_band_share_cap,
    per_event_expected_loss_cap / band_expected_loss,
    per_event_worst_case_cap / band_worst_case_loss,
    remaining_daily_loss_budget / band_worst_case_loss,
    available_backed_balance_after_open_orders
)
```

Use zero size when the estimate is based on too few fills. The system should
earn the right to scale through live-forward paper and then live MM-2 markouts.

### 4. Measure Markouts By Cause, Not Just Time

At minimum:

- markout at `+30s`, `+1m`, `+5m`, `+30m`, and settlement;
- markout by market, hour, band distance, quote age, quote regime, and source
  freshness;
- markout around observation windows and forecast model releases;
- separate passive fills from taker/FAK fills;
- separate reward-harvest fills from model-edge fills;
- report gross spread, rebates, rewards, fees paid while flattening, and net
  markout.

The casebook should become a fill toxicity taxonomy. If `market lead` cases are
settled model losses, the policy should pull or widen when market movement is
not supported by our source state but book movement is fast and deep. If
`market overreaction` cases remain settled model wins, they are candidates for
small edge-regime quotes or FAK takers only after fee and latency buffers.

### 5. Backtest Like The Market Is Trying To Fool Us

Backtest requirements before increasing size:

- frozen historical days for replay tuning;
- held-out frozen days for validation;
- live-forward paper days that were generated in real time;
- no parameter chosen only because it won on the same day set;
- pessimistic fill rules as the promotion gate;
- a queue-aware simulator as an analysis companion;
- confidence intervals around markout by slice;
- multiple-testing correction or a deflated performance statistic when many
  policy variants are tried.

### 6. Market Making Rewards Are Not Alpha

Polymarket's liquidity rewards pay for resting quoted size near the adjusted
midpoint. Maker rebates pay only when liquidity is executed. Both incentives
can reward behavior that increases adverse selection:

- liquidity rewards pull quotes toward the midpoint even when fair value says
  stand down;
- rebates encourage being filled, but informed fills are exactly the dangerous
  fills;
- the daily reward/rebate pool can change at Polymarket's discretion;
- payout thresholds mean small accounts can earn less than modeled.

Therefore:

```text
reward/rebate income is valid only after toxic markout is deducted.
```

### 7. Weather-Specific Information Events Define The Spread Schedule

Weather market making is not "quiet overnight" just because trades are sparse.
Known information events include:

- WU current/history updates and revisions,
- METAR/SPECI reports,
- ASOS/AWOS one-minute or rapid observations where available,
- SWOB updates for Toronto,
- HRRR hourly model updates and extended cycles,
- RAP hourly cycles,
- local noon/afternoon heating dynamics,
- late-day settlement lock-in when a high has printed.

The quote policy should encode event windows as spread multipliers or stand-down
states, then validate them against the casebook and book tapes.

## Suggested Additions To The Build Plan

### A. MM Policy Permission Matrix

| Model state | Market state | Source state | Bot action |
| :--- | :--- | :--- | :--- |
| BLOCK | any | any | no quotes |
| SHADOW | stable mid, thin reward competition | fresh | harvest min-size only |
| SHADOW | model-market disagreement | fresh | stand down; log case |
| PASS slice | edge > spread + fees + risk buffer | fresh | model-skewed quote |
| PASS slice | edge > taker fee + slippage + latency buffer | fresh | consider FAK in paper first |
| any | observation watcher stale | stale | cancel/pull all |
| any | heartbeat unhealthy | any | cancel/pull all |
| any | near decisive print/window | uncertain | widen or stand down |

### B. Quote Tape Fields To Require

Every intended quote row should include:

- policy version and parameters hash;
- model version and promotion gate state;
- market/band/token IDs;
- fair probability, market midpoint, uncertainty, and edge;
- inventory vector summary and event-level risk;
- book spread/depth/imbalance/quote age;
- source freshness by provider;
- reason code for quote, widen, or stand-down;
- latency budget status;
- expected reward score and expected rebate value;
- expected adverse-selection buffer;
- final size limiter that bound the quote.

### C. Go-Live Gate Additions

Add these to the existing MM-2 gate:

- token-id persistence verified by the latest audit, not only by roadmap text;
- 14 live-forward paper days with queue-aware analysis and conservative
  trade-through promotion results both reviewed;
- all policy parameters locked before the 14-day paper window begins;
- no live quote if source watcher is absent or stale;
- real heartbeat drill with throwaway orders;
- wallet allowance and balance accounting tested under simultaneous YES/NO
  orders in a negative-risk event;
- rebate/reward expected-vs-paid reconciliation for at least one payout cycle
  before scaling beyond one event.

## Source Index

### Polymarket Mechanics And API

- [Polymarket Liquidity Rewards](https://docs.polymarket.com/market-makers/liquidity-rewards) - reward formula, Q-score mechanics, daily payouts, min payout.
- [Polymarket Maker Rebates](https://docs.polymarket.com/market-makers/maker-rebates) - fee-equivalent rebate weighting and weather category rebate rate.
- [Polymarket Fees](https://docs.polymarket.com/trading/fees) - taker fee formula, maker fee zero, category fee rates.
- [Polymarket Orders Overview](https://docs.polymarket.com/trading/orders/overview) - order types, post-only, tick sizes, allowances, validity checks, heartbeat.
- [Polymarket Create Order](https://docs.polymarket.com/trading/orders/create) - GTC/GTD/FOK/FAK order semantics and SDK examples.
- [Polymarket Negative Risk Markets](https://docs.polymarket.com/advanced/neg-risk) - conversion relationship for mutually exclusive outcomes.
- [Polymarket pUSD](https://docs.polymarket.com/concepts/pusd) - collateral token, USDC backing, wrapping/unwrapping.
- [Polymarket Market WebSocket](https://docs.polymarket.com/market-data/websocket/market-channel) - orderbook, price change, last trade, best bid/ask events.
- [Polymarket User WebSocket](https://docs.polymarket.com/market-data/websocket/user-channel) - authenticated order and trade lifecycle events.
- [Polymarket Rate Limits](https://docs.polymarket.com/api-reference/rate-limits) - endpoint classes and quota surface.
- [Polymarket Heartbeat Endpoint](https://docs.polymarket.com/api-reference/trade/send-heartbeat) - dead-man-switch endpoint.
- [Polymarket US Liquidity Incentive Program](https://docs.polymarket.us/incentives/liquidity) - important because US docs show different scoring mechanics than global docs.
- [Polymarket Markets & Events](https://docs.polymarket.com/concepts/markets-events) - condition IDs and token IDs.
- [Polymarket Overview](https://docs.polymarket.com/market-makers/overview) - maker role and high-level market-making docs.

### Classical Market-Making And Microstructure

- [Avellaneda and Stoikov, High-frequency Trading in a Limit Order Book](https://people.orie.cornell.edu/sfs33/LimitOrderBook.pdf) - reservation price, spread, inventory risk.
- [Ho and Stoll, Optimal Dealer Pricing Under Transactions and Return Uncertainty](https://rodneywhitecenter.wharton.upenn.edu/wp-content/uploads/2014/03/7927.pdf) - inventory-aware dealer quotes.
- [Glosten and Milgrom, Bid, Ask and Transaction Prices in a Specialist Market](https://www.kellogg.northwestern.edu/research/math/papers/570.pdf) - adverse selection from informed order flow.
- [Kyle, Continuous Auctions and Insider Trading](https://people.duke.edu/~qc2/BA532/1985%20EMA%20Kyle.pdf) - market depth and informed trading.
- [Glosten and Harris, Estimating Components of the Bid/Ask Spread](https://www.acsu.buffalo.edu/~keechung/MGF743/Readings/B3%20Glosten%20and%20Harris%2C%201988%20JFE.pdf) - decomposing spread components.
- [Madhavan, Market Microstructure: A Survey](https://www.acsu.buffalo.edu/~keechung/MGF743/Readings/Market%20microstructure%20A%20surveyq.pdf) - survey of price formation, liquidity, market design.
- [Biais, Glosten, and Spatt, Market Microstructure: A Survey of Microfoundations](https://www.cis.upenn.edu/~mkearns/finread/bias-spatt-survey.pdf) - adverse selection, inventory, transparency.
- [Harris, Trading and Exchanges](https://www.acsu.buffalo.edu/~keechung/MGF743/Readings/Trading-Exchanges-Market-Microstructure-Practitioners%20Draft%20Copy.pdf) - practitioner market microstructure and spread components.
- [Hasbrouck, Empirical Market Microstructure](https://www.acsu.buffalo.edu/~keechung/MGF743/Readings/Hasbrouck%27s%20book.pdf) - empirical tools for order flow and trading data.
- [Stoll, Market Microstructure](https://www.econ.sdu.edu.cn/__local/F/CE/F2/A97EE00B1B5A4969CECF053D98D_97353554_2A130.pdf?e=.pdf) - spread sources including order processing, asymmetric information, and inventory.
- [O'Hara, Market Microstructure Theory overview](https://business.cornell.edu/hub/2018/11/20/maureen-ohara-microstructure-ethics/) - market design, liquidity, and price discovery.

### Optimal Market Making Extensions

- [Gueant, Lehalle, Fernandez-Tapia, Dealing with Inventory Risk](https://arxiv.org/abs/1105.3115) - closed-form approximations and inventory constraints.
- [Cartea, Jaimungal, Ricci, Algorithmic Trading, Stochastic Control, and Mutually-Exciting Processes](https://oxford-man.ox.ac.uk/wp-content/uploads/2020/05/Algorithmic-Trading-Stochastic-Control-and-Mutually-Exciting-Processes.pdf) - market making with clustered order flow and short-term signals.
- [Cartea, Jaimungal, Penalva, Algorithmic and High-Frequency Trading](https://assets.cambridge.org/97811070/91146/frontmatter/9781107091146_frontmatter.pdf) - textbook treatment of market making, execution, VWAP, pairs, and dark pools.
- [Optimal Market-Making with Risk Aversion](https://ideas.repec.org/a/inm/oropre/v60y2012i3p541-565.html) - threshold inventory policies.
- [Market Making via Reinforcement Learning](https://arxiv.org/pdf/1804.04216) - high-fidelity LOB simulation and inventory-aware RL.
- [Algorithmic Trading with Model Uncertainty](https://kclpure.kcl.ac.uk/ws/files/115222270/Algorithmic_Trading_CARTEA_Accepted_3_Apr_17_GREEN_AAM.pdf) - ambiguity aversion and inventory penalties.
- [Limit Order Strategic Placement with Adverse Selection Risk and Latency](https://arxiv.org/pdf/1610.00261) - liquidity imbalance, latency, and adverse selection.
- [Limit Order Trading With a Mean-Reverting Reference Price](https://math.stanford.edu/~papanico/pubftp/LOB_OU.pdf) - limit orders around a mean-reverting signal.
- [Stanford Optimal Market-Making Slides](https://web.stanford.edu/class/cme241/lecture_slides/MarketMaking.pdf) - concise intuition for reservation price and inventory.

### Limit Order Book Simulation, Queue, And Execution

- [The Market Maker's Dilemma: Fill Probability vs Post-Fill Returns](https://arxiv.org/html/2502.18625v2) - direct framing of fill probability versus adverse selection.
- [A Model for Queue Position Valuation in a Limit Order Book](https://moallemi.com/ciamac/papers/queue-value-2016.pdf) - queue position value and adverse-selection cost.
- [Multi-Level Order-Flow Imbalance in a Limit Order Book](https://ora.ox.ac.uk/objects/uuid%3A9b7d0422-4ef1-48e7-a2d4-4eaa8a0a7ec1/files/m89dedb16194e627a2c92d14e3329bd48) - book-level imbalance as a price-change signal.
- [A Framework for Realistic Limit Order Book Simulation](https://arxiv.org/html/2501.08822v1) - queue-reactive LOB simulation.
- [Limit Order Book Simulations: A Review](https://arxiv.org/html/2402.17359v1) - model taxonomy and simulation pitfalls.
- [Deep Learning Fill Probabilities in a Limit Order Book](https://business.columbia.edu/sites/default/files-efs/citation_file_upload/deep-lob-2021.pdf) - data-driven fill-time probability.
- [Resiliency of the Limit Order Book](https://opus.lib.uts.edu.au/bitstream/10453/98964/1/Lo_Hall_Resiliency_of_the_limit_order_book_Accepted_Manuscript.pdf) - liquidity shock recovery.
- [Analysis of Limit Order Book and Order Flow](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID488422_code350826.pdf?abstractid=488422&mirid=1) - book shape and strategic order submission.
- [HftBacktest Documentation](https://hftbacktest.readthedocs.io/) - practical backtesting with queue position and feed/order latencies.
- [HftBacktest Queue-Based Market Making](https://hftbacktest.readthedocs.io/en/latest/tutorials/Queue-Based%20Market%20Making%20in%20Large%20Tick%20Size%20Assets.html) - queue importance in tick-constrained markets.

### Probability Forecasting, Calibration, And Statistical Validation

- [Brier, Verification of Forecasts Expressed in Terms of Probability](https://journals.ametsoc.org/view/journals/mwre/78/1/1520-0493_1950_078_0001_vofeit_2_0_co_2.xml) - original Brier score.
- [Gneiting and Raftery, Strictly Proper Scoring Rules](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf) - proper scoring rule foundations.
- [Guo et al., On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599) - reliability diagrams, ECE, temperature scaling.
- [Siegert, Simplifying and Generalising Murphy's Brier Score Decomposition](https://ore.exeter.ac.uk/articles/journal_contribution/Simplifying_and_generalising_Murphy_s_Brier_score_decomposition/29748851/1/files/56771708.pdf) - reliability, resolution, uncertainty.
- [Stable Reliability Diagrams for Probabilistic Classifiers](https://pmc.ncbi.nlm.nih.gov/articles/PMC7923594/) - robust calibration diagnostics.
- [Scikit-Learn Probability Calibration](https://scikit-learn.org/stable/modules/calibration.html) - practical calibration methods.
- [Proper Scoring Rules for Estimation and Forecast Evaluation](https://arxiv.org/html/2504.01781v1) - recent review of scoring rule theory.
- [Forecast Verification resources](https://www.cawcr.gov.au/projects/verification/) - meteorological forecast verification background.
- [Revisiting Calibration of Modern Neural Networks](https://openreview.net/forum?id=QRBvLayFXI) - ECE limitations and calibration concerns.

### Position Sizing, Kelly, And Risk Of Ruin

- [Kelly, A New Interpretation of Information Rate](https://www.princeton.edu/~wbialek/rome/refs/kelly_56.pdf) - original log-growth criterion.
- [MacLean, Thorp, Ziemba, Good and Bad Properties of the Kelly Criterion](https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf) - why fractional Kelly is often safer.
- [The Kelly Capital Growth Investment Criterion](https://www.worldscientific.com/worldscibooks/10.1142/7598) - comprehensive reference volume.
- [Ziemba, Understanding the Kelly Capital Growth Investment Strategy](https://www.caia.org/sites/default/files/AIAR_Q3_2016_05_KellyCapital.pdf) - investment-oriented Kelly overview.
- [Using the Kelly Criterion for Investing](https://webhomes.maths.ed.ac.uk/mckinnon/blackouts/StochOptFinanceAndEnergySpringer/Chap1_KellyZiemba.pdf) - Kelly applied to investment sizing.
- [Position sizing and timing strategies](https://www.econstor.eu/handle/10419/55526) - systematic sizing effects.
- [Investopedia Position Sizing](https://www.investopedia.com/terms/p/positionsizing.asp) - basic risk-per-trade framework.
- [Investopedia Kelly Criterion](https://www.investopedia.com/articles/trading/04/091504.asp) - accessible Kelly formula and caveats.

### Backtesting, Overfitting, And Financial ML Discipline

- [Bailey and Lopez de Prado, Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) - selection bias and non-normal returns.
- [Bailey et al., Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) - estimating PBO.
- [Correcting for Selection Bias, Backtest Overfitting and Non-Normality](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551) - DSR paper page.
- [The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253) - PBO paper page.
- [Portfolio Optimization Book: Dangers of Backtesting](https://portfoliooptimizationbook.com/book/8.3-dangers-backtesting.html) - practical backtest risks.
- [Portfolio Optimization Book: Seven Sins of Quantitative Investing](https://portfoliooptimizationbook.com/book/8.2-seven-sins.html) - look-ahead, survivorship, data snooping.
- [QuantStart Backtesting Transaction Costs](https://www.quantstart.com/articles/Successful-Backtesting-of-Algorithmic-Trading-Strategies-Part-II/) - slippage, commissions, market impact.
- [Purged Cross-Validation overview](https://en.wikipedia.org/wiki/Purged_cross-validation) - purging/embargoing for overlapping financial labels.

### Prediction Markets And Automated Market Makers

- [Hanson, Combinatorial Information Market Design](https://mason.gmu.edu/~rhanson/combobet.pdf) - market scoring rules for prediction markets.
- [Logarithmic Market Scoring Rules for Modular Combinatorial Information Aggregation](https://www.eecs.harvard.edu/cs286r/courses/fall10/papers/mktscore.pdf) - LMSR mechanics.
- [A Practical Liquidity-Sensitive Automated Market Maker](https://www.cs.cmu.edu/~sandholm/liquidity-sensitive%20automated%20market%20maker.teac.pdf) - liquidity-sensitive LMSR.
- [A Bayesian Market Maker](https://people.cs.vt.edu/~sanmay/papers/bmm-ec.pdf) - prediction market makers with beliefs.
- [Comparing Prediction Market Structures](https://people.cs.vt.edu/~sanmay/papers/predmarkets.pdf) - CDA vs market-maker structures.
- [Comparing Prediction Market Mechanisms](https://www.jasss.org/21/1/7.html) - continuous double auction and LMSR mechanisms.
- [Hanson's Automated Market Maker](https://www.ubplj.org/index.php/jpm/article/download/451/489/1429) - implementation formulae for LMSR.
- [Automated Market Makers for DeFi](https://arxiv.org/pdf/2009.01676) - AMM cost-function comparison including LMSR variants.

### Practical Bot And Market-Making References

- [Hummingbot Pure Market Making](https://hummingbot.org/strategies/v1-strategies/pure-market-making/) - order refresh loop and basic PMM architecture.
- [Hummingbot Inventory Skew](https://hummingbot.org/strategies/v1-strategies/strategy-configs/inventory-skew/) - target inventory balancing.
- [Hummingbot Order Levels](https://hummingbot.org/strategies/v1-strategies/strategy-configs/order-levels/) - multiple quote levels.
- [Hummingbot Avellaneda Market Making](https://hummingbot.org/strategies/v1-strategies/avellaneda-market-making/) - practical reservation-price/inventory controls.
- [SEC Maker-Taker Fees Memo](https://www.sec.gov/spotlight/emsac/memo-maker-taker-fees-on-equities-exchanges.pdf) - rebate/fee structure background.
- [The Impact of Make-Take Fees on Market Efficiency](https://ou.edu/content/dam/price/Finance/CFS/paper/pdf/Black%20Paper.pdf) - maker/taker rebates and efficiency concerns.
- [Hoffmann, Adverse Selection, Transaction Fees, and Multi-Market Trading](https://www.fese.eu/app/uploads/2025/01/dlv-winner-2011.pdf) - interaction of fees and adverse selection.

### Weather And Observation Timing Sources

- [NOAA HRRR](https://rapidrefresh.noaa.gov/hrrr/) - hourly updated high-resolution model.
- [NCEP HRRR Products](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/) - cycle and forecast-hour product structure.
- [NCEI RAP/RUC](https://www.ncei.noaa.gov/products/weather-climate-models/rapid-refresh-update) - hourly RAP cycles.
- [NWS ASOS](https://www.weather.gov/asos) - hourly and special observations.
- [NCEI ASOS/AWOS](https://www.ncei.noaa.gov/products/land-based-station/automated-surface-weather-observing-systems) - automated station data and AWOS intervals.
- [NWS METAR Decode Key](https://www.weather.gov/media/wrh/mesowest/metar_decode_key.pdf) - METAR/SPECI scheduled and special report definitions.
- [Aviation Weather Center METAR Data](https://aviationweather.gov/data/metar/) - current and recent METAR/TAF access.
- [NWS API Web Service](https://www.weather.gov/documentation/services-web-api) - observations, alerts, and forecasts API.
- [Iowa Environmental Mesonet ASOS Download](https://mesonet.agron.iastate.edu/request/download.phtml) - ASOS/METAR archive and real-time ingest notes.
- [Synoptic High-Frequency ASOS](https://docs.synopticdata.com/services/high-frequency-asos) - one-minute ASOS availability context.

## Local Evidence Read During This Audit

- `docs/research/MARKET_MAKING_PLAN.md`
- `data/backtest/gap_decomposition.md`
- `data/backtest/pooled_candidate_replay_v0_3_report.md`
- `data/backtest/forecast_vs_realized.md`
- `data/backtest/data_layer_audit_report.md`
- `docs/roadmap/ROADMAP.md`

## Bottom Line

Do not skip MM-0/MM-1. The current plan's caution is justified by the literature:
market making dies by adverse selection, stale quotes, and overfit fill models
long before it dies by a missing fancy model. The fastest high-quality path is:

1. verify token/book persistence and source freshness,
2. finish the book recon and markout reports,
3. build the quote policy as a pure, auditable decision function,
4. paper trade with conservative and queue-aware simulators,
5. size only from live-forward edge after costs, rebates, rewards, and markout.
