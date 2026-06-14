# Market-Making Model Readiness And Gap Plan

Date: 2026-06-14

Question: how close does the model need to be to market-make effectively, do we
need to beat Polymarket before starting, and what is the path to closing the
model-market gap?

## Short Answer

We do not need the model to beat Polymarket globally before starting the
market-making program. We should start, and continue, the keyless shadow/paper
market-making stack now. A live-forward shadow run still requires fresh CLOB
capture; if the CLOB loop is dead, fixing that is step zero.

We should not start live model-skewed market making across the fleet until the
model beats Polymarket in the specific market/hour/band slices where quotes are
allowed, and until live-forward paper trading proves positive net markout after
spread, rebates, rewards, inventory risk, and operational buffers.

The first live mode, after paper gates pass, should be harvest-only: market-mid
anchored, min-size, post-only, with the model as a veto. That mode does not
require global model superiority. It requires that the model is calibrated
enough to identify dangerous disagreements and that paper/live markouts show
we are not being selected against faster than spread plus incentives can pay.

## Current State

The current evidence says the model is improving, but not globally ahead:

- Corrected June 10 gap decomposition: replayed model Brier `0.0386` versus
  market `0.0325`, a `+0.0061` per-row gap.
- Current F-family candidate replay: candidate Brier `0.0508` versus market
  `0.0379`, a `+0.0130` gap, while improving strongly versus current serving
  (`-0.0139`).
- Per-market promotion: Atlanta is promoted (`0.0363` candidate versus
  `0.0395` market). Austin, Chicago, Dallas, Denver, Houston, Los Angeles,
  Miami, NYC, San Francisco, and Seattle remain shadow because they are not
  proven better than market on pinned rows.
- CLOB microstructure overlay: raw out-of-fold CLOB rows are nearly at market
  parity (`0.0303` versus market `0.0299`) and beat market on raw
  `market_lead` and `book_liquidity_artifact` target slices, but the
  taxonomy-gated overlay still trails market globally.
- Operationally, the latest current check shows the CLOB loop state as `DEAD`
  and strict CLOB audit failing on stale trailing captures. This blocks any
  live order plan regardless of model quality.

## What "Close Enough" Means

For market making, Brier score is necessary context but not the go/no-go metric.
The actionable unit is quote-level expected value:

```text
quote_ev =
  fair_value_edge
  + spread_capture
  + expected_maker_rebate
  + expected_liquidity_reward
  - adverse_selection_markout
  - inventory_penalty
  - flattening_fee
  - operational_error_buffer
```

The model is close enough for each phase when it clears that phase's evidence
bar.

## Phase Bars

### 1. Shadow/Paper Market Making

Start now. No model-beats-market requirement.

Required bar:

- full quote/no-quote intent tape,
- current book/source/watcher freshness visible in each row,
- no live keys,
- conservative fill simulation and queue-aware companion scoring,
- no quote decisions without reason codes.

Purpose: measure fill toxicity, markout, reward competition, and quote uptime.

### 2. Live Harvest Pilot

Does not require global model superiority. It requires paper evidence that
market-mid quoting is not toxic under our stale-input and model-disagreement
vetoes.

Required bar before live:

- at least 14 live-forward paper days with locked policy parameters,
- conservative simulated net P&L positive after markout, rewards, rebates, and
  flattening costs,
- mean harvest fill markout no worse than the configured tolerance; use
  `-0.5 cents/share` at +30m as the initial gate from the market-making plan,
- zero quotes resting through decisive observation events,
- strict CLOB audit passing and observation watcher fresh,
- heartbeat, cancel-all, min-size/tick/post-only, balance, and user WebSocket
  drills passed.

The model's role here is defensive: if model and market disagree too much, stand
down. The quote center stays the market midpoint.

### 3. Model-Skewed Edge Quoting

Requires beating Polymarket, but only in the allowed slices.

Required bar:

- market/hour/band-distance slice Brier at or better than market,
- confidence interval or held-out/live-forward evidence that the edge survives
  selection bias,
- quote-level edge above risk buffers. The current shadow policy's rough
  structure is sensible: require several cents of edge before model-centered
  quoting, not sub-cent marginal differences,
- positive post-fill markouts by regime and cause,
- inventory risk represented as event-level settlement P&L across mutually
  exclusive bands.

No fleet-wide edge mode until the fleet-wide evidence clears. Atlanta can be an
edge-mode candidate earlier than the other F markets because its current replay
already beats market, but only after the paper execution gate verifies markouts.

## Where The Gap Lives

The gap is not "the model is bad everywhere." It is concentrated:

1. US F-family markets carry most of the corrected gap.
2. Morning and overnight rows are large contributors.
3. At-settlement and one-off central bands dominate the moneyness gap.
4. The model is already better on two-off bands and Toronto mid-day.
5. Some CLOB/casebook slices are promising, especially raw `market_lead` and
   `book_liquidity_artifact`, but need careful gating and more data.

This matters because market making does not need an all-hours all-bands model.
It needs an honest permission map.

## Path To Closing The Gap

1. Keep CLOB capture and observation-trigger loops healthy.

   Live order quality is irrelevant if book/watcher freshness fails. The CLOB
   loop currently needs attention before any live gate can pass.

2. Convert the current quote policy into live-forward paper runs.

   The existing pure shadow policy is the right starting point. The missing
   layer is date/budget orchestration, budget ledgers, fill simulation,
   queue-aware scoring, and nightly `mm_paper_report.md`.

3. Use the promotion map as the quote permission system.

   PASS -> eligible for edge research and eventually model-skewed quotes.
   SHADOW -> harvest only. BLOCK -> no quotes. Today that means Atlanta is the
   only F market that can even be considered for edge-mode research.

4. Close the US morning/overnight gap.

   Current F-family replay still trails market most in early cutoffs. The
   forecast tracker now says morning reach calibration is no longer obviously
   underconfident, so the remaining work is not simply "trust forecasts more."
   It is per-market/hour calibration and better probability mass allocation
   around the central bands.

5. Fix central-band discrimination.

   The at-settle and one-off gap is the main economic problem because central
   bands carry reward campaigns, volume, and inventory risk. Per-market
   calibration helps first; a continuous-density model is the structural fix
   because two-degree F buckets need sub-bucket resolution.

6. Promote CLOB microstructure features carefully.

   The raw CLOB overlay is close to market parity and improves some casebook
   slices. Do not globally promote it yet. Expand taxonomy gates only where
   held-out and live-forward evidence beats the base and market after markout.

7. Turn disagreement cases into quote rules.

   `wu_lag_catchup_miss`, `stale_source`, `forecast_miss`, and
   `boundary_rounding_error` should mostly widen or pull quotes. Proven
   `market_overreaction` cases can become small edge candidates only after
   fees, latency, and markout buffers.

8. Let size follow evidence.

   Start with zero live size while shadowing. Move to min-size harvest only
   after paper gates. Increase size only when realized live markouts match
   paper and the slice-level edge remains positive after all costs.

## Practical Decision

Start the market-making bot in shadow/paper mode now.

Do not wait for the model to beat Polymarket globally to collect quote tapes,
simulate fills, and learn where market making is viable. That data is needed to
know whether the model is useful for execution.

Do wait for per-slice model superiority and positive execution markouts before
placing model-skewed live quotes. The current gap is close enough to justify
building and shadowing the bot, not close enough to justify broad live edge
quoting.

## References

- `docs/research/MARKET_MAKING_PLAN.md`
- `docs/research/MARKET_MAKING_RESEARCH_AUDIT_2026-06-13.md`
- `docs/research/MM_INITIAL_TEST_RUN_DESIGN.md`
- `data/backtest/gap_decomposition.md`
- `data/backtest/pooled_candidate_replay_latest_report.md`
- `data/backtest/f_family_promotion_refresh_report.md`
- Polymarket orders overview: https://docs.polymarket.com/trading/orders/overview
- Polymarket liquidity rewards: https://docs.polymarket.com/market-makers/liquidity-rewards
- Polymarket fees: https://docs.polymarket.com/trading/fees
- Polymarket heartbeat endpoint: https://docs.polymarket.com/api-reference/trade/send-heartbeat
