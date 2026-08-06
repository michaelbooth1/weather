# Workstation report 2026-08-05 — can the MM gate decide?

## Verdict

**No. The gate cannot decide as written, and the 14-day clock must not start.**

The headline economic answer is also unambiguous: **a 30-minute-profit rule
would reject both pilot strategies even though both were profitable at binary
settlement before liquidity rewards.** At the $25/tier-20 setting the sign is
`-$10.166` at 30 minutes and `+$11.222` at settlement; at $50/tier-50 it is
`-$21.448` and `+$20.604`. Those are the same fixed fills. The horizon choice,
not fill selection, flips the decision.

Three independent problems prevent the existing clock from being decision
grade:

1. the plan does not name the P&L horizon, and the current scorer silently uses
   settlement when a label exists but 30 minutes when it does not;
2. the six-event-day pilot contains only **two date clusters and three market
   clusters**, which cannot identify a stable crossed date × market variance;
   and
3. the current reservation forbids reading or scoring target dates
   **2026-08-06 through 2026-11-03**. Under the current reservation, those dates
   contribute exactly zero countable MM days. The earliest uninterrupted clock
   can start is 2026-11-04 unless the operator explicitly changes the canonical
   reservation.

The revised specification below uses **43 consecutive countable target dates**
as a non-reducible planning floor for the roughly $500 fleet, with a blinded
variance-only recalculation after the first five countable post-PASS dates that
may raise, but never lower, the final N. Forty-three is a conservative pilot
sensitivity, not a claim that the two-date pilot estimated power reliably. If
every date counted from 2026-11-04, the earliest decision would be 2026-12-16.

No release, PIT path, promotion rule, trusted floor, paper permission, collector,
schedule, or trading surface was changed.

## Q1 — settlement is the acceptance horizon

The primary economic endpoint should be **net settlement P&L**, because these
are daily binary contracts and the measured strategy is funded to hold its
inventory to resolution. Settlement cash P&L is the realized trading result.
Liquidity rewards are earned from resting qualifying size and rebates from
maker volume; neither changes because a mark is sampled at +5m or +30m.

Thirty-minute markout remains important, but as an adverse-selection and
inventory-risk guardrail. It answers whether informed flow is picking off the
book and whether inventory could become unsafe before resolution. It should
become the primary horizon only if the operating policy actually liquidates or
marks risk at 30 minutes. In that case the correct endpoint is the policy's
real liquidation P&L, not an arbitrary observation-time convention.

### Pilot decomposition

The following are the six frozen market-days: Atlanta, Dallas, and Toronto on
2026-07-10 and 2026-07-11. Rewards were not observed in dollars, so the table
decomposes the measured pre-reward economics only.

| Cap / tier | N | Horizon-dependent trading P&L @30m | Horizon-dependent trading P&L @settlement | Horizon-independent rebate estimate | Net @30m | Net @settlement | Horizon-sensitive share of measured settlement net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| $25 / 20 | 6 market-days, 2 dates, 3 markets | -$10.479011 | +$10.909713 | +$0.312616 | **-$10.166395** | **+$11.222329** | 97.21% |
| $50 / 50 | 6 market-days, 2 dates, 3 markets | -$22.019995 | +$20.031212 | +$0.572450 | **-$21.447545** | **+$20.603662** | 97.22% |

The horizon-independent rebate is only 2.79% and 2.78% of measured positive
settlement net respectively. The mark change accounts for `$21.388724` and
`$42.051207` of the 30m-to-settlement swing. Therefore nearly all **measured**
economics are horizon-sensitive. The fraction of **full expected** economics
is not identified because historical reward dollars were not captured; adding
an unknown reward term to the denominator would manufacture precision.

At tier 20, the crossed-CR1 mean settlement net is `$1.870388` per market-day
with a 95% small-cluster interval `[-$22.513672, +$26.254448]`, which crosses
zero. At tier 50 the ordinary two-way sandwich variance is negative—a known
failure mode with two date clusters. A constrained nonnegative crossed
random-effects fallback gives `$3.433944 [-$123.203372, +$130.071259]` per
market-day; that interval crosses zero and is a sensitivity, not valid
decision-grade inference. No pilot profitability interval excludes zero.

## Q2 — 14 calendar days are not decision grade

Fourteen calendar target dates are not 14 event-days. A complete 12-market
fleet supplies up to **168 market-day cells**, but cells share target-date
weather/information shocks and persistent market effects. N for the test is the
number of target dates, with the complete market-day table retained for
two-way clustering; it is never the quote-row, fill-row, or band-row count.

### What the pilot can and cannot say about power

The power sensitivity uses one-sided alpha 0.05, 80% power, a 12-market fleet,
degrees of freedom capped at 11, and the settlement endpoint. The planning
approximation is `(t[0.95,11] + z[0.80]) * sigma / sqrt(D)`. The $25 row uses
the positive crossed-CR1 fleet-date-equivalent standard deviation. The $50 row
uses the nonnegative crossed random-effects fallback because its sandwich
variance is invalid. The date-shock envelope refuses to credit market
diversification and is the safer boundary with only two dates.

| Cap / tier | Pilot settlement mean per market-day | Crossed planning SD | 14-date MDE | Approx. power at pilot mean | Dates for 80% power | 12-market event-days | Date-shock-envelope MDE / dates / event-days |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| $25 / 20 | +$1.870388 | $2.713971 | $1.913087 | 78.3% | 15 | 180 | $2.341720 / 22 / 264 |
| $50 / 50 | +$3.433944 | $7.047431 | $4.967756 | 51.1% | 30 | 360 | $5.959558 / **43** / **516** |

Thus 14 dates miss 80% power even at both favourable pilot point estimates.
The $50/tier-50 scenario is the relevant conservative planning case: its
maximum pilot fleet reserve was `$476.95`, close to the current paper run's
`$500` fleet budget. Under the safer date-shock envelope it needs 43 countable
dates. The tier-50 pilot crossed interval still crosses zero, and the variance
fallback rests on one residual degree of freedom, so **43 is a floor for
planning, not a decision-grade pilot estimate**.

The honest statistical conclusion is that the pilot cannot supply a single
reliable powered N. It supplies a bound: 14 is too short; 43 is the minimum
provisional design for the approximately $500 population; and the required N
must be recomputed after real post-PASS quotes change the population.

### The reservation stops the near-term clock

The canonical reservation is 2026-08-06 through 2026-11-03 inclusive. Those
90 target dates must not be read, enumerated, replayed, or scored. A maker
score on one of them would destroy its reserved status. Therefore:

- a pre-reservation date may count only if every checklist item below passes;
- no reserved target date counts, even if capture is healthy; and
- absent an operator change to the reservation, the first possible new
  43-date window is 2026-11-04 through 2026-12-16.

## Q3 — what is actually computable today

The distinction that matters is not whether the JSON schema contains a field;
it is whether captured evidence can compute that field without an assumption.

| Acceptance input | Current implementation | Captured-evidence verdict today |
| --- | --- | --- |
| Pessimistic trade-through-only fills | Implemented correctly: a taker SELL must print strictly below a YES bid, a taker BUY strictly above a YES ask, and size is capped by recorded execution size. | **Not computable for the inspected 2026-08-02 and 2026-08-03 days.** All 12 event folders on both dates retain raw and summary books, but 0/12 retain `market_ws_events.csv`, `market_ws.jsonl`, `market_trades.csv`, or `trades_long.csv`. Books alone cannot prove a strict-through execution. |
| Reward Q-share | The scorer computes own score, but competitor Q is a scalar from a CLOB-recon suggestion or `paper_config_reward_competitor_q`; its reward result is explicitly `COUNTERFACTUAL_ONLY` and `does_not_change_pnl=True`. CLOB recon uses median 5%-depth as a proxy, not sample-by-sample competitor Q. | **Evidence-capable, endpoint-not-ready.** Full-depth `order_books.jsonl` is retained and includes competitor levels/size, so an exact sampled Q denominator can be built. The current report does not build it or attach decision-grade reward dollars. |
| Rebate share | Each fill receives `0.05 * size * p * (1-p) * 0.25`, a fee-equivalent estimate. It does not divide our simulated eligible maker volume by observed eligible maker/taker volume for the market-day. | **Not computable for the inspected outage days from retained evidence.** The required execution-volume tape is absent. The existing number is a formula sensitivity, not pool-share evidence. |
| Markout at +30s/+1m/+5m/+30m and settlement | The fill schema carries all four market marks plus settlement. `compute_fill_financials` uses settlement when present, otherwise 30m, which is the current silent horizon mixture. | **Marks are available conditionally, but filled-position results are not.** All 12 inspected folders per day retain `order_books_summary.csv`, which can supply future mids. Settlement existed in 12/12 August 2 folders and 0/12 August 3 folders at the mirrored snapshot; a final ledger label can close the latter later. Missing strict-fill evidence still prevents acceptance scoring. |
| Fill toxicity around decisive WU/METAR evidence | Quote/fill rows retain scheduled event-window class, ID, and action. The paper report can slice by casebook taxonomy. Its `decisive_resting_check` currently treats settlement availability as resolution of the audit; it does not join fills to actual decisive print timestamps. | **Partially captured, not mechanically computed.** Observation manifests/raw payloads retain fetch/first-seen evidence, and scheduled windows are recorded, but there is no complete actual-print/METAR-special-to-fill join with an N-minute exposure statistic. |

### What the maker-score outage costs

The queued binding repair makes a growing canonical quote tape deterministic by
hashing the last complete-record prefix. That repairs the scorer's quote-input
race; it does not create missing executions, marks, rewards, or rebate-volume
evidence.

The mirror retains source-bound scoring projections for both inspected days:

| Target date | Base projection rows | Markets | Quote permissions | Promotion state | Execution tape folders |
| --- | ---: | ---: | ---: | --- | ---: |
| 2026-08-02 | 11,616 | 12 | 0 | 11,616 `BLOCK` | 0/12 |
| 2026-08-03 | 20,724 | 12 | 0 | 20,724 `BLOCK` | 0/12 |

Those quote decisions and full books are recoverable. The required conservative
fills are not recoverable **by rescoring retained evidence**. A separately
authorized historical-execution reconstruction might recover them, but it
would require a network/provider operation, a completeness proof, and the same
timestamp/side/size provenance used by the pilot. None is authorized here, and
until it exists these dates are unscoreable and cannot count.

The mirrored `mm_paper_report.json` generated at
`2026-08-03T13:53:25.491201+00:00` illustrates the silent gap: it reports three
live-forward days and freshness `PASS`, but zero conservative fills, reward
status `MISSING_POOL_OR_SCORE`, competitor source
`paper_config_reward_competitor_q`, no actual payout evidence, and rewards that
do not change P&L. Freshness is therefore not acceptance countability.

Finally, the inspected August 2–3 projection population is wholly
`promotion_state: BLOCK`. Even a perfect later rescore would describe the
pre-release restricted population, not the post-PASS acceptance population.

## Q4 — promotion PASS breaks transport, not the old arithmetic

Promotion PASS does not change the pilot's recorded numbers. It does invalidate
using their mean, fill rate, market weights, or toxicity as if they were sampled
from the future strategy. The pilot had six market-days, four filled cells at
tier 20, four filled cells at tier 50, and only Atlanta/Dallas/Toronto. The
inspected current runs had 12 markets but zero permitted base quotes. PASS is
expected to alter the number of markets, quoted bands, fills, capital
allocation, reward competition, and exposure to informed flow.

After the first **five countable post-PASS target dates**, and only after at
least three markets have strict-through fills on at least three of those dates,
perform a variance-only sample-size recalculation over the complete 12-market
cell table. If that fill support is absent, emit `POWER_NOT_EVALUABLE` and keep
collecting. Re-estimate and report:

- date, market, and market-day-intersection variance;
- fills and filled notional by date and market, including zero-fill cells;
- reward/rebate share of net economics;
- 30m and settlement markout distributions; and
- actual-print toxicity by event class.

Do not test for success at day 5. Let `s_post` be the larger of (a) the
two-way-cluster variance converted to a fleet-date standard deviation and (b)
the ordinary standard deviation of whole-fleet date totals. With the frozen
tier-50 pilot planning alternative `delta = $10.301831` per fleet date, set:

`N_final = max(43, ceil(((t[0.95,11] + z[0.80]) * s_post / delta)^2))`.

This recalculation may raise N only. The post-PASS mean, participation, and
toxicity are reported to expose non-transferability; they are not used to
shorten the test after a lucky start. If the policy, fleet, capital, release
semantics, incentive formula, or permission contract changes, start a new
window and recompute rather than pooling regimes.

## Revised mechanical acceptance specification

Status today: **`NOT_READY_CLOCK_NOT_STARTED`**.

1. **Population:** the 12-market fleet frozen before day 1, a fixed `$500`
   fleet budget, locked policy hash, and one declared release/promotion
   contract. Valid gate-driven abstentions remain zero-P&L cells. A
   promotion-BLOCK population is a different regime and cannot enter.
2. **Primary horizon:** binary settlement.
3. **Cell value:** for every target date `d` and market `m`,
   `Y[d,m] = settlement cash P&L + exact observed-book reward allocation +
   observed-volume rebate allocation - flattening/taker fees - other execution
   costs`. Do not add spread capture separately to settlement cash P&L.
4. **Primary statistic:** mean whole-fleet daily net,
   `mean_d(sum_m Y[d,m])`, with the underlying `Y[d,m]` table retained.
5. **Inference:** one-sided alpha 0.05 test of mean net greater than zero,
   two-way clustered by target date and market, market degrees of freedom capped
   at 11. Every reported interval must use the same crossed cell table. No
   fill-level or quote-level IID interval is admissible.
6. **N:** 43 consecutive countable target dates minimum; after the first five
   countable post-PASS dates, calculate `N_final` above and raise the target if
   required. No success look occurs before `N_final`.
7. **Decision at N:** `PASS_MM_ECONOMICS` only if the one-sided 95% lower bound
   is greater than zero. Otherwise `BLOCK_MM_ECONOMICS_NOT_PROVEN`; do not call
   a crossing interval profitable and do not extend opportunistically to chase
   significance.
8. **Risk guardrails:** report +30s/+1m/+5m/+30m markouts and actual-print
   toxicity. Negative 30m mean does not by itself reject a settlement-positive
   hold-to-resolution strategy, but any existing capital, inventory, stale
   quote, decisive-event, or unresolved-resting-quote gate blocks.
9. **External conjunctive gate:** the jurisdiction gate and every unchanged
   release, promotion, known-edge, risk, and execution-readiness gate must pass
   separately before MM-2. This report grants no live permission.

## Day-1 checklist — a target date counts only if every box is true

- [ ] The target date is outside 2026-08-06 through 2026-11-03, or the operator
  has explicitly changed the canonical reservation before any read or score.
- [ ] Release identity, promotion state, registry/fleet, `$500` budget, policy
  hash, economics formula, and scoring code are frozen and recorded.
- [ ] The post-PASS population is active; a promotion-BLOCK or release-unbound
  day does not count.
- [ ] The complete local target-day run is present with no maker-roll gap,
  quarantine ambiguity, stale input, or partial coverage.
- [ ] Quote inputs are source-bound to exact immutable files or a hashed
  complete-record prefix; the binding race fix is deployed and verified.
- [ ] Every frozen market has complete full-depth sampled books, including
  competitor size. A valid policy abstention is included as zero; missing
  market evidence fails the whole date.
- [ ] Every frozen market has complete execution evidence with exchange time,
  timestamp precision, token/condition, taker side, price, size, and deduplicated
  identity. Books without executions do not satisfy this box.
- [ ] Pessimistic fills use strict trade-through only; queue simulation is
  companion evidence and never substitutes.
- [ ] All filled positions have +30s/+1m/+5m/+30m marks and a countable final
  settlement label; missing marks or labels fail the date.
- [ ] Reward campaign metadata and full-book samples produce sample-level own Q,
  competitor Q, normalized share, pool allocation, and payout-threshold result.
  An assumed competitor scalar or `COUNTERFACTUAL_ONLY` result fails the date.
- [ ] Rebate accounting uses our simulated eligible maker volume and observed
  eligible market volume/pool; a fixed fee-equivalent shortcut fails the date.
- [ ] Actual WU print/METAR-special first-seen timestamps are joined to resting
  quotes and fills for the declared N-minute toxicity windows, with zero
  unresolved decisive-event audits.
- [ ] Settlement P&L, reward, rebate, flattening/taker fees, and every other cost
  reconcile at market-day and fleet-date level without mixed horizons.
- [ ] The date is appended exactly once to the complete crossed date × market
  cell table, including zero-fill/valid-abstention cells.
- [ ] No policy, fleet, capital, release, promotion semantics, or incentive rule
  changed during the window. A change starts a new window.
- [ ] The score is final and countable. A fresh report, a captured day, or a day
  listed in `live_forward_days` is not enough by itself.

If any box is false, the date emits `NOT_COUNTABLE` with the exact blocker. It
does not increment N. Because the revised window is consecutive, a failed date
ends that window rather than being silently skipped.

## What would falsify this

- If the operating policy demonstrably liquidates inventory before settlement,
  settlement is the wrong primary horizon; use realized policy liquidation P&L
  and re-power the design.
- If exact reward and rebate reconstruction shows they dominate settlement
  trading P&L, the measured 97.2% horizon-sensitive fraction will fall and the
  power inputs must be recomputed.
- If a provenance-complete retained or separately authorized historical trade
  tape is found for August 2–3, those days may become mechanically scoreable;
  they still remain pre-PASS and cannot establish post-PASS power.
- If five countable post-PASS dates produce a fleet-date standard deviation
  above the pilot envelope, the 43-date floor is too short and `N_final` must
  rise. If the population has too few strict-fill clusters, power remains
  `NOT_EVALUABLE`.
- If a valid crossed analysis at the final N has a one-sided lower bound above
  zero at 30m but not settlement, or the strategy repeatedly must flatten
  before resolution, the economic rationale for settlement-first acceptance is
  false.
- If the operator changes the reserved window, the stated earliest clock date
  changes. Without that explicit change, scoring a reserved target date would
  falsify the evidence boundary rather than add an MM day.

## Evidence boundary and receipts

This mission read only the published 2026-07-10/11 pilot, the explicitly
allowed 2026-08-02/03 maker runs and snapshot folders, current source/contracts,
and the queued maker-binding repair report. It did not read, enumerate, replay,
or score any reserved target date. It made no provider or trading call. Network
use was limited to the requested `git fetch`; the branch push is the only
remaining network action.

Base: `origin/master` at `171319e40958512c44e10fe84a2218c813189ca7`.

| Evidence | SHA-256 |
| --- | --- |
| Pilot fills | `177f0c3cd14a7a0280d598db6072dbbc69fd410bbfae7883f3f9a052b66d21d5` |
| Pilot scenarios | `4d7472960ae90ae7c47f709b4b626774244177f444c6472b12b5defd29bd9a2b` |
| Pilot strata | `14ea7b5750fa9f35ffa605740bd7807cd3064d7c60abebc8d4c5934a2a6a7bf8` |
| 2026-08-02 scoring-projection manifest | `4ecdb2869d78f41d0bb4477ed73edb0932a51133befab5a698baa2f451b7cfc4` |
| 2026-08-03 scoring-projection manifest | `29a9325ee945541d7c9a742344add21049488371d06291b50b76c8eb27188586` |
| Mirrored maker-paper report | `fb86c3e9fbc807c6136f5c1977e021c5733b5f193591fc7abf1545fa8d2b7891` |
