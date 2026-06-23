# 2026-06-23 Trading Stack Performance And Profitability Audit

Scope: evidence audit of weather-market trading over the latest active run
window, focused on June 19-22, 2026. This separates maker-style market making
from taker-bot trading because the evidence, failure modes, and go-live gates
are different.

Primary evidence:

- Maker runs: `data/mm_runs/2026-06-19` through `data/mm_runs/2026-06-22`.
- Taker runs: `data/taker_runs/2026-06-19` through `data/taker_runs/2026-06-22`.
- Refreshed maker paper score:
  `data/backtest/mm_paper_june19_22.md` and
  `data/backtest/mm_paper_june19_22.json`.
- Prior taker audit:
  `docs/roadmap/audits/taker-bot-performance-strategy-audit-2026-06-22.md`.
- Policy/run code reviewed: `src/weather/market/mm_policy.py`,
  `src/weather/market/mm_risk.py`, `src/weather/market/mm_paper.py`,
  `src/weather/market/market_making_run.py`, and `src/weather/market/taker_bot*.py`.

No live orders were placed or recommended by this audit.

## Executive Summary

The maker stack is not yet a profitability problem first; it is an operational
evidence and countability problem. The June 19-22 maker runs emitted only paper
or shadow-intent quotes, never live-trade permission. Four of five recent maker
runs were blocked or degraded by stale model rows, stale CLOB books, stale
observation-trigger state, or non-countable evidence mode. The only clean
preflight run, June 19 `20260619T040103782099Z`, was an operator drill and still
did not count toward the live-forward gate.

The refreshed maker paper score over the five June 19-22 run folders found 33
conservative fills, 165 filled shares, and `+1.6556` USDC net after estimated
fees/incentives, but the gate is still `OPEN`: zero live-forward paper days,
unlocked policy parameters, 3,964 missing-size trade rows, and no live-trade
permission evidence. This is useful early signal, not live-profit evidence.

The taker stack has a sharper strategy problem. Mark-to-market PnL is repeatedly
misleading. June 19 `taker-20260619-3d3450f0` reported `+1238.75` MTM and
settled to `-10.00`. June 21 `taker-20260621-bbe63642` reported `+4401.81` MTM
and settled to `-56.31`. June 22's active `low_price_tail_capped` canary has no
settled sample, 75% low-price-tail fills, and a `WARN_HIGH_TAIL_SHARE` gate.

The best path is not to increase risk. First make the evidence loop reliable:
fresh model/CLOB/watcher state, daily settlement finalization, maker paper
scoring, and taker champion/challenger scoring. Then scale only narrow slices
with settlement-scored, after-fee, executable-depth positive evidence.

## Maker Evidence

Quote rows below are quote-permission rows from `quote_intents_long.csv`.
Intent rows are total rows in the quote tape.

| Date | Run | Preflight | Live-forward | Counts | Intent rows | Quote rows | Paper legs | Budget reserved | Main blockers/reasons |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2026-06-19 | `20260619T040103782099Z` | PASS | BLOCK | false | 25,186 | 4,019 | 8,026 | 57.63 / 500 | Operator drill; top no-quote reason `NO_QUOTE_KNOWN_EDGE_PERMISSION` 10,813; harvest quotes only |
| 2026-06-19 | `20260620T033636978961Z` | WARN | BLOCK | false | 18,348 | 169 | 338 | 0 / 500 | 9 markets stale for model and CLOB; post-settlement evidence mode |
| 2026-06-20 | `20260620T233005288278Z` | STALE | BLOCK | false | 27,192 | 687 | 1,374 | 0 / 500 | 12 markets stale, including 9 model/CLOB and 12 watcher stale |
| 2026-06-21 | `20260621T153607128252Z` | WARN | BLOCK | false | 60,940 | 1,115 | 2,230 | 0 / 500 | 10 markets model-stale, 9 CLOB-stale; 14,168 blocked-promotion rows |
| 2026-06-22 | `20260622T233019900796Z` | STALE | BLOCK | false | 924 | 0 | 0 | 0 / 500 | 12 CLOB-stale, 12 watcher-stale, 2 model-stale; all latest rows no-quote |

Refreshed paper scoring for these five runs:

| Metric | Value |
| --- | ---: |
| Quote rows / legs scored | 132,590 / 11,980 |
| Conservative fills / shares | 33 / 165.000 |
| Queue-estimated fill legs / shares | 688 / 2,299.974 |
| Spread capture | 1.6500 USDC |
| Adverse-selection markout 30m | -5.2175 USDC |
| Settlement PnL | 2.0125 USDC |
| Maker rebate estimate | 0.1190 USDC |
| Flattening fee estimate | 0.4759 USDC |
| Net after fees/incentives | 1.6556 USDC |
| Gate status | OPEN |
| Live-forward paper days | 0 |
| Locked policy params | false |
| Missing-size trade rows | 3,964 |

Interpretation: the maker score is directionally encouraging but too thin and
too non-countable. The policy is behaving safely by failing closed, but the
system is not producing the continuous fresh evidence required by item 44.

## Taker Evidence

| Date | Run | Strategy | Fills | Spent | Reported/MTM PnL | Settlement/executable PnL | Tail evidence | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 2026-06-19 | `taker-20260619-221a357c` | manual/legacy | 50 | 59.81 | -17.21 reported | +36.69 settled, paper-no-fee | no low-price-tail fills | WARN reconciliation; not after-fee/slippage scored |
| 2026-06-19 | `taker-20260619-3d3450f0` | manual/legacy | 4 | 10.00 | +1238.75 MTM | -10.00 settled | no low-price-tail fills | MTM/settlement sign flip |
| 2026-06-20 | `taker-20260620-3d3450f0` | manual/legacy | 50 | 66.99 | -66.99 reported | -66.99 settled | 50 losses | Losing day, paper-no-fee |
| 2026-06-21 | `taker-20260621-bbe63642` | `raw_edge_control` | 50 | 65.83 | +4401.81 MTM | -56.31 settled | 31 low-price-tail fills, 0.62 fraction | BLOCK next-run policy |
| 2026-06-22 | `taker-20260622-3d74b86b` | `low_price_tail_capped` canary | 8 | 2.60 | +6.61 MTM | missing settled sample | 6 low-price-tail fills, 0.75 fraction | `MISSING_SETTLED_SAMPLE`, `WARN_HIGH_TAIL_SHARE` |

Taker no-trade and friction evidence:

- June 19-22 order tapes contain `fee_usdc`, but these run artifacts do not
  carry executable-depth, slippage, market-benchmark, avoided-loss, missed-gain,
  or no-trade scoreboard columns.
- Settled June 19-21 finalization payloads mark `live_profitability_evidence_basis`
  as `paper_no_fee`, with `after_fee_pnl_scored=false` and
  `after_slippage_pnl_scored=false`.
- June 22 strategy reporting correctly prevents MTM promotion:
  `promotion_evidence_basis=settlement_scored`, `MTM can promote=false`, and
  `Best settlement-scored strategy=-`.

The current taker evidence therefore does not justify promotion or live use.
The safest action is to keep `low_price_tail_capped` paper-only until it has
settlement-scored, after-fee, after-slippage evidence and tail share below the
promotion threshold.

## Top Root Causes

1. **Maker countability is failing before strategy can be evaluated.**
   Live-forward gates are blocked by stale model, CLOB, and watcher state. June
   22 is the clearest example: every selected market was stale, and the run
   emitted zero quote rows.

2. **Maker evidence is too thin and not locked.**
   The June 19-22 paper score has only 33 conservative fills, zero live-forward
   paper days, unlocked policy params, and missing-size trade rows. Positive
   `+1.6556` USDC cannot carry a profitability claim.

3. **Taker MTM is not quality evidence.**
   The June 19 and June 21 sign flips prove stale or misleading CLOB marks can
   make losing tail positions look profitable before settlement.

4. **Taker tail exposure remains unsafe.**
   June 21 raw edge bought 31 low-price-tail fills and settled negative. June 22
   `low_price_tail_capped` still put 75% of fills into low-price tails, above
   the configured 50% promotion threshold.

5. **Actual run artifacts lag the latest profitability requirements.**
   Roadmap items 240 and 241 exist, but the June 19-22 taker order tapes do not
   yet show executable-depth/slippage or market-benchmark/no-trade fields. Those
   runs should not be used as live-profitability evidence.

## Profitability Blockers

- No live maker run has passed live-readiness, platform-verification,
  data-layer, live-forward, and settlement-scored profitability gates.
- Maker paper trading lacks 14 consecutive locked live-forward days.
- Stale CLOB/model/watcher inputs are frequent enough to erase countability.
- Taker promotion still has unresolved or unscored samples and poor tail mix.
- Fee/slippage/depth and no-trade benchmark evidence is missing from the recent
  taker run artifacts.
- Reward and rebate economics remain estimates; actual payout reconciliation is
  not available without a gated live pilot, which is not yet justified.

## Immediate Fixes

| Rank | Fix | Owner area | Acceptance evidence |
| ---: | --- | --- | --- |
| 1 | Repair active-day freshness for snapshot/model, CLOB, and observation-trigger loops before running maker/taker sessions. | `weather.collection.snapshot_tracker`, `weather.market.market_microstructure`, `weather.operations.observation_trigger` | `market_making_run` preflight PASS across selected markets; `fleet_observability report --strict`; no stale model/CLOB/watcher blockers in `preflight.json` |
| 2 | Make taker finalization and strategy scoring settlement-first every day. | `weather.market.taker_bot_finalization`, daily refresh | `settled_pnl.json`, `settled_strategy_summary.json`, and `strategy_bakeoff.json` exist for each eligible run before any promotion decision |
| 3 | Keep `low_price_tail_capped` canary paper-only and reduce/block low-price-tail fills until settled evidence improves. | `weather.market.taker_bot_strategy_registry`, `taker_bot_sizing`, `taker_bot_finalization` | Tail fill fraction <= 0.50, no unresolved fills, positive settled after-fee net PnL across required sample |
| 4 | Regenerate taker runs/reports with executable-depth, slippage, fee, and no-trade benchmark fields. | `taker_bot_scoring`, `taker_bot_strategy_evaluation`, item 240/241 reporting | Order/strategy artifacts include after-fee, after-slippage, executable-depth, avoided-loss, missed-gain, and market-smarter slice fields |
| 5 | Run maker paper scoring nightly on the latest locked paper-live-forward folders. | `weather.market.mm_paper`, daily refresh | `mm_paper_report.md` covers the latest active days, has live-forward days increasing, and reports conservative fills plus markout slices |

## Longer-Term Improvement Loop

Daily:

1. Confirm loop health: snapshot/model, CLOB, observation-trigger, disk, and
   tape backup.
2. Finalize settlement labels and taker runs as soon as labels are available.
3. Run taker champion/challenger bakeoff from settled, after-fee, after-slippage
   evidence only.
4. Run maker paper scoring against the latest quote tapes and CLOB/trade tapes.
5. Refresh promotion and known-edge maps only from countable evidence.
6. File or update roadmap items for the single worst blocker found that day.

Weekly:

1. Review maker markout slices by market, hour, band distance, freshness, and
   event-gate state.
2. Review taker settled PnL, tail exposure, market-smarter/no-trade slices, and
   drawdown.
3. Freeze a policy hash before comparison, validate on held-out days, and avoid
   tuning on the same days used for claims.
4. Promote only when the evidence is settled, after-fee, after-slippage,
   out-of-sample, and has enough fills across markets.

Scaling requirements:

- Maker: at least 14 consecutive locked live-forward paper days, positive net
  after markout/rewards/rebates/fees, no decisive-event resting quote breaches,
  fresh live-forward countability, and clean data-layer/platform readiness.
- Taker: at least 3-5 settled days per candidate, enough filled orders and
  markets, positive executable net PnL, no MTM/settlement sign flips, acceptable
  drawdown, and tail fill fraction under the configured cap.

## Best Path To Profitability

1. **Stabilize evidence collection first.**
   The highest-return immediate work is operational: make all loops fresh and
   countable so the strategy can be measured honestly.

2. **Stop relying on MTM for taker decisions.**
   MTM remains telemetry only. Settlement-scored executable PnL is the promotion
   standard.

3. **Stop bad tail exposure.**
   Block or sharply cap low-price and market-centered warm-tail trades until
   repeated settled evidence proves they win after fees and slippage.

4. **Run maker harvest in paper only, with locked parameters.**
   The maker paper score has a small positive net, but not enough evidence. Lock
   policy hashes and accumulate clean days before interpreting it.

5. **Scale narrow proven slices, not broad model optimism.**
   The first profitable path is likely a small set of market/hour/band-distance
   slices where model and market evidence agree, not full-fleet risk.

6. **Consider live maker MM-2 only after all gates pass.**
   Live testing requires passing live-readiness, platform verification,
   data-layer proof, live-forward evidence, kill-switch drills, and positive
   settlement/executable profitability. Those conditions are not true today.

## Roadmap Work Needed

Existing taker work items 234-241 are still the right spine. This audit adds or
reinforces the following work:

- Add a maker active-day freshness recovery item if one is not already open:
  rerun `market_making_run` preflight after snapshot/CLOB/watcher repair and
  require all selected markets to produce countable paper evidence.
- Extend item 240/241 verification to assert that current run artifacts, not
  only code/tests, contain executable-depth/slippage and benchmark/no-trade
  fields.
- Add a daily maker paper-score freshness SLA: `mm_paper_report.md` must cover
  the latest completed active day, or maker evidence is stale.
- Add a taker canary demotion rule for `WARN_HIGH_TAIL_SHARE` plus missing
  settled sample: the active canary must remain paper-only until requalified.

## Commands Run

Evidence and context reads:

```powershell
git status --short
Get-Content README.md
Get-Content docs\research\MARKET_MAKING_PLAN.md
Get-Content docs\research\MARKET_MAKING_LIVE_RUNBOOK_2026-06-15.md
Get-Content docs\roadmap\items\item-43-market-making-policy-and-quote-intent-tape.md
Get-Content docs\roadmap\items\item-44-paper-trading-queue-simulation-markouts-and-incentive-accounting.md
Get-Content docs\roadmap\items\item-45-market-making-position-sizing-risk-controls-and-live-gate.md
Get-Content docs\roadmap\items\item-46-date-budget-market-making-run-orchestrator.md
Get-Content docs\roadmap\audits\taker-bot-performance-strategy-audit-2026-06-22.md
rg -n "def decide_quote|NO_QUOTE_|known_edge|current_high_trust|event_gate|book_age|model_age|watcher" src\weather\market\mm_policy.py
rg -n "def |class |halt|kelly|loss|risk|reserve|negative|settlement|stale|heartbeat|cancel" src\weather\market\mm_risk.py
rg -n "def |class |conservative|queue|markout|reward|rebate|settlement|pnl|fill|live_forward" src\weather\market\mm_paper.py
rg -n "preflight|live_forward|quote_permission|risk_events|budget|paper-live-forward|live-pilot" src\weather\market\market_making_run.py
rg -n "def |class |strategy|settled|mark_to_market|fee|slippage|depth|tail|warm|current_high|benchmark|no_trade|promotion|canary" src\weather\market -g "taker_bot*.py"
```

Artifact aggregation:

```powershell
.\venv\Scripts\python.exe -m weather.market.mm_paper --run-folder data\mm_runs\2026-06-19\20260619T040103782099Z --run-folder data\mm_runs\2026-06-19\20260620T033636978961Z --run-folder data\mm_runs\2026-06-20\20260620T233005288278Z --run-folder data\mm_runs\2026-06-21\20260621T153607128252Z --run-folder data\mm_runs\2026-06-22\20260622T233019900796Z --json-out data\backtest\mm_paper_june19_22.json --report-out data\backtest\mm_paper_june19_22.md --fills-out data\backtest\mm_paper_june19_22_fills.csv
```

No pytest suite was run because this was an evidence/reporting audit with no
source-code changes. The `mm_paper` scorer completed successfully for the
requested June 19-22 maker run folders.
