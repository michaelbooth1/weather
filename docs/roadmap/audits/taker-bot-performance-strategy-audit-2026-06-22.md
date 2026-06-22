# 2026-06-22 Taker Bot Performance Strategy Audit

This audit turns the June 19-22 taker bot evidence into follow-up roadmap work.
The core finding is that the bot has been learning and promoting from evidence
that is not yet settlement-scored, while the active edge model repeatedly buys
bad low-price and warm-tail shapes.

## What Is Going Wrong

`mark_to_market` is not reliable enough to drive quality or promotion. The
June 21 taker run reported `+4401.81` MTM, but settlement scoring against
available labels gives `-56.31`. A June 19 run reported `+1238.75` MTM and
finalized to `-10.00`. Cheap losing tails can sit near `0.999` before
settlement, so MTM is useful telemetry but not quality evidence.

The raw edge model is still buying bad tails. June 20 root-cause evidence shows
`50` losing fills, all classified as warm-tail losing fills. June 21 had `31`
low-price-tail fills, all lost. The model is overpricing low-probability,
high-temperature or far-from-current-high bands.

Current-high and warm-tail gates are too narrow. Warm-tail blocking currently
targets only the `raw_edge` family, leaving candidates such as
`low_price_tail_capped` able to fill market-centered warm tails. The
current-high trust gate also permits aggressive untrusted-current-high trades
before the late window.

The active strategy was promoted too early. `low_price_tail_capped` is the
active default, but it has no settlement-scored June 22 sample yet, has a
high low-price-tail fill fraction, and its promotion gate is supposed to block
on unresolved orders and excessive tail fraction. The June 20 bakeoff was only
partial-quality evidence.

Operational plumbing is weak enough to hide strategy truth. June 21 labels
exist but the run was not finalized to `settled_pnl`. The console log reports
`No space left on device`, large backtest artifacts are accumulating, and the
bot process can be alive while effectively idle.

Live-profit assumptions are incomplete. The taker configuration uses
`taker_fee_rate: 0.0`, while provider fee documentation lists a Weather taker
fee schedule and maker fee `0`. Any profitability claim needs executable depth,
spread/slippage, and fees.

## Roadmap Work Created

- Item 234: make taker quality and promotion settlement-only.
- Item 235: block and recalibrate bad low-price and warm-tail slices.
- Item 236: close current-high and warm-tail gate loopholes for all strategies.
- Item 237: demote and requalify the active taker canary before live use.
- Item 238: run daily full champion/challenger bakeoffs instead of one-arm days.
- Item 239: add settlement finalization, liveness, and storage SLAs.
- Item 240: add fee, slippage, and executable-depth profitability modeling.
- Item 241: compare every traded slice to market benchmarks and choose no-trade
  where the market is smarter.

## Profitability Direction

The best path is a settlement-scored champion/challenger loop, not taking every
model edge. Promote only after `3-5` settled days, enough fills across markets,
positive net PnL after fees, acceptable drawdown, and no MTM/settlement sign
flips. Prefer narrow proven strategies such as current-high lock-in and
adjacent-band trades, with low-tail probes allowed only where repeated
settlement evidence supports them.
