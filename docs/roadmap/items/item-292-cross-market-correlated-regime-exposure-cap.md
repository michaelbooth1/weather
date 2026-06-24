# 292. Cross-Market Correlated-Regime Exposure And Joint-Loss Cap For Trading Bots [OPEN 2026-06-24 - PER-MARKET CAPS DO NOT BOUND CORRELATED FLEET DOWNSIDE]

Goal: stop the taker and maker from accumulating concentrated, positively
correlated positions across markets that move together on a shared weather
regime. Add a correlation/regime-aware joint-exposure and joint-loss cap so a
single fleet-wide model bias cannot create unbounded correlated drawdown.

Source: 2026-06-24 system-level roadmap audit of the trading-systems theme,
building on the taker ML audit (items 283-285). The taker sizing path
(`weather.market.taker_bot_sizing.apply_taker_budget`) caps exposure per token,
per market, per adjacent-bin cluster, per low-price tail, and per
market-centered warm tail, but has no aggregate cap beyond the daily dollar
budget. The maker risk stack (item 45, `weather.market.mm_risk`) has a flat
fleet notional cap and per-event worst-case cap, but no correlation weighting.
Both treat markets as independent. In reality daily-high settlement outcomes are
driven by shared synoptic regimes: a continental heat dome moves Chicago,
Dallas, Austin, and Houston the same direction at once, so one warm model bias
misses them together. The June 19-21 settled taker losses bear this out -
losses concentrated on the same days across NYC, Toronto, Atlanta, and Miami and
in the hour-9 and warm-tail slices simultaneously, not as independent draws.

Why this matters: per-market and even flat-fleet notional caps bound total
dollars but not the joint downside when positions are positively correlated. For
short and maker exposure (and the two-sided NO-taker arm in items 253/257/276)
correlated joint loss can exceed premium collected; for the YES-buy taker it
concentrates the entire budget into one regime so a single bad synoptic call
loses everywhere at once. The trading-stack audit explicitly says to "scale
narrow proven slices, not broad full-fleet risk" and to review drawdown by
regime - which requires a correlation-aware exposure control that does not yet
exist.

Why it is not already covered: item 45 provides a flat fleet notional cap and a
per-event worst-case cap but no regime/correlation weighting, and the taker has
no aggregate cap at all beyond its budget. Items 275/279 cluster same-day
cross-market fills only for statistical promotion accounting, not for live
exposure capping. Item 183 clusters correlated forecast sources on the fallback
path, not trading positions. Item 38 builds cross-market microstructure signal,
not risk caps. No item bounds correlated joint exposure or joint loss across
markets as a live trading control.

## Design

1. Define a per-target-day correlated-regime grouping that assigns each open or
   candidate position a regime-group key from shared synoptic driver, geographic
   cluster, and band-direction-versus-forecast (warm-side versus cool-side),
   with a documented default grouping, a configurable override, and a
   data-driven check against realized same-day cross-market settlement-outcome
   correlation.
2. Add a shared correlated-exposure risk primitive (consumed by both
   `weather.market.taker_bot_sizing` and `weather.market.mm_risk`) that tracks
   group-level signed notional and a stress-scenario joint loss, for example
   "model biased warm fleet-wide so every warm-side position loses together."
3. Add a correlation-aware joint cap that bounds same-direction notional and
   worst-case joint loss per regime group, layered on top of the existing
   per-token, per-market, per-event, and flat-fleet caps, failing closed to
   no-trade when a new fill would breach the group cap.
4. Emit regime-group key, group signed notional, and joint-stress loss fields on
   taker order rows and maker quote/risk artifacts, and surface group
   concentration in the run reports and daily progress so single-regime
   concentration is visible to the operator.
5. Validate on the existing counterfactual/replay tapes (item 273) and bakeoff
   (items 238/275) by measuring realized same-day cross-market settlement-outcome
   correlation and showing the cap bounds the joint drawdown that per-market and
   flat-fleet caps miss; keep it shadow-first and fail-closed before it changes
   any active default.

- [ ] Add a per-target-day correlated-regime grouping with a documented default
  and a realized-correlation validation check.
- [ ] Add a shared correlated-exposure risk primitive consumed by the taker
  sizing path and the maker risk stack.
- [ ] Enforce a correlation-aware joint notional and joint-loss cap per regime
  group, failing closed on breach, on top of existing caps.
- [ ] Emit regime-group exposure and joint-stress-loss fields in taker and maker
  artifacts and run reports.
- [ ] Prove on the item 273 counterfactual tape and item 238/275 bakeoff that the
  correlation-aware cap bounds joint drawdown that per-market and flat-fleet caps
  do not.

Acceptance: each trading run assigns open and candidate positions to
correlated-regime groups; a stress scenario in which the model is biased one
direction fleet-wide cannot exceed a configured per-group joint-loss cap for
either the taker or the maker; regime-group exposure and joint-stress loss are
reported per run; and a settled replay shows the correlation-aware cap bounds
joint drawdown that per-market and flat-fleet caps leave unbounded.

Related: items 38, 45, 55, 167, 183, 209, 214, 253, 275, 279, 283, 284, 285.
