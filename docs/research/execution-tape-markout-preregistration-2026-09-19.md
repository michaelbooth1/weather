# Execution-tape maker markout - pre-registration (2026-09-19)

Status: **FROZEN BEFORE ANY RESULT EXISTS.** Written and committed before
`weather.market.execution_tape_markout` was executed once, on any data. No number in this file is a
measurement. Audit origin: `market-maker-1` and `strategy-5` (full audit 2026-09-18): the public
execution tape has been collected since 2026-08-15 and has no analytic consumer.

## Question

Per filled share, what did a **passive maker** in our 12 weather markets earn or lose to subsequent
price movement? This is the adverse-selection term (`A` and `f` of `ESTABLISHED_FINDINGS.md` section
on the zero-edge maker grid, "the single most decisive unmeasured number") that decides whether
liquidity rewards plus maker rebates can pay.

## Data

- Trades: `data/snapshots/<event_slug>/execution_tape/trades-NNNNN.jsonl` (`execution_tape_trade_v0.1`),
  fields `asset_id`, `price`, `size`, `side`, `timestamp` (epoch ms), `market_id`, `target_date`,
  `transaction_hash`. `side` is read as the **aggressor (taker)** side, per the venue's documented
  `last_trade_price` semantics. This is not chain-verified; the report prints a quote-rule agreement
  rate as a check on it.
- Midpoints: `order_books_summary.csv` in the same event folder (our own REST book captures):
  `(best_bid + best_ask) / 2` at `captured_at_utc`, two-sided books only.
- Closed event dates only. Cluster = `target_date` (event date).

## Estimator

1. Maker side is the opposite of the aggressor: aggressor BUY at `p` means the maker SOLD at `p`.
   If `side` is absent the quote rule against the last midpoint at or before the trade is used and the
   row is flagged; ties and rows with no midpoint are counted `side_undetermined`, never guessed.
2. Markout at horizon `h` in {1 min, 5 min, 30 min, settlement}: maker sold `p - mid(t+h)`; maker
   bought `mid(t+h) - p`. `mid(t+h)` is the first captured midpoint at or after `t+h` within a
   tolerance (default 120 s). Settlement uses the token payoff (0 or 1) from `settlement.json`.
   Rows without a usable mark are counted `unmarkable` per horizon and never dropped silently.
3. Nominal maker rebate per share: `0.25 * 0.05 * p * (1 - p)`. Net = markout + rebate.
4. Means are reported share-weighted and trade-weighted, pooled and split by market, hours-to-close
   (>24h, 6-24h, 1-6h, <1h), price (p<0.1, 0.1-0.3, 0.3-0.7, 0.7-0.9, >0.9), trade size and maker side.
5. Uncertainty: cluster bootstrap by event date (ratio estimator re-computed per replicate), fixed
   seed, 90% percentile interval. Fewer than 10 date clusters prints `UNDERPOWERED` on every interval.

## Primary metric (one, fixed)

**Share-weighted net maker P&L per share at the 5-minute horizon, all markets pooled, two-sided
midpoints only, recorded aggressor side, date-clustered 90% interval `[L, U]`.** Everything else in
the report (other horizons, all splits, trade-weighting, the one-sided `bound` midpoint policy) is
descriptive and cannot change the verdict.

## Decision rule

`R` is a **named parameter, deliberately unfilled here**: the per-share liquidity-reward income a
maker must collect to break even, in price units per filled share. It must come from the
reward-ceiling measurement (daily reward pool a qualifying quote can actually earn, divided by the
shares that quote expects to have filled per day). Rewards are paid on resting time, fills are paid
per share; `R` is the bridge between them and it must be frozen **before** this analysis is read.
It is passed as `--reward-per-share`; without it the report's verdict is `R_NOT_SUPPLIED`.

- **KILL-SIGNAL** if `U < -R`: even the optimistic bound loses more per share than rewards repay.
- **SUPPORTIVE** if `L > -R`: even the pessimistic bound is covered by rewards.
- **INCONCLUSIVE** otherwise.
- With fewer than 10 date clusters the verdict is `INCONCLUSIVE` with reason `UNDERPOWERED`
  whatever the interval says. An accept is the dangerous direction; no verdict is bought from a
  handful of dates.

A KILL-SIGNAL or SUPPORTIVE reading is evidence about the maker track's economics. It is not a
trading authorization, a promotion input, or a statement about our own fills.

## Caveats (binding on any citation of the result)

1. **Other makers' fills, not ours.** The public tape shows fills that happened to whoever was
   resting. Our quotes would sit at different prices, sizes and times.
2. **Queue position unknown.** A fill at `p` went to the front of the queue; we do not know where we
   would have stood, so the fill *rate* is not estimated here at all. This measures P&L per filled
   share only.
3. **Survivorship of quotes is not visible.** Quotes cancelled before adverse moves leave no trade.
   Observed fills are selected toward quotes that did not get out of the way, and skilled makers'
   cancellations make the average fill look better or worse than ours would be; sign unknown.
4. **Midpoint source resolution.** Midpoints are our REST captures (tens of seconds apart), not an
   event-time book. The 1-minute horizon is near that resolution. One-sided books have no midpoint,
   so late-day trades near 0/1 are disproportionately `unmarkable`; read the unmarkable counts and
   the `bound` sensitivity before citing a late-bucket number.
5. **Rebate is nominal.** The sampled tape rows record `fee_rate_bps = "0"`. If no taker fee is
   charged in these markets the true rebate is zero; the report therefore always shows markout alone
   beside net, and prints the observed `fee_rate_bps` distribution.
6. **Coverage.** The tape starts on the event date, so the `>24h` bucket is expected to be empty;
   websocket dark gaps remove trades; repeated public observations are collapsed by identity.
7. **Complementary matching.** A taker BUY of Yes may be matched against a maker BUY of No. In
   Yes-price terms that maker sold Yes at `p`; the estimator treats it so.
8. **Split cells are not multiplicity-adjusted** and must not be mined for a favourable bucket.
