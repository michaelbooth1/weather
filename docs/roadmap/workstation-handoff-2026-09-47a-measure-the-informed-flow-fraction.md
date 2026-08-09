# Workstation handoff 2026-09-47a — measure the informed-flow fraction

Written 2026-08-08 by the production agent. Read on `origin/master` and execute.
**`f` is now the single most decisive unmeasured number in the project.** `-09-46a` closed the model
route; this decides whether the remaining route is viable.

## 1. Why this is the top item

`-09-46a` established two things:

- **There is no quotable model edge, anywhere.** 114 pre-declared cells, **zero** with a positive
  point estimate, overall **−0.01915 [−0.02444, −0.01443]**. Model-skewed quoting is retired.
- **Market-centred harvesting does not need model edge** — but whether it *pays* is dominated by the
  informed-fill fraction `f` and the adverse move `A`, and both were unmeasured:

| Informed fraction `f` | Scenarios where zero model edge breaks even (no reward) |
| ---: | ---: |
| 0.10 | **79.43%** |
| 0.50 | 42.29% |
| 1.00 | **24.57%** |

**That spread is the whole question.** At low `f` the maker is a business; at high `f` it is a
donation. Nothing else on the board changes the answer as much.

## 2. The data exists, and it is historical only

Trade events come from the **`clob_enrichment` loop**, not the latency-critical CLOB loop — which is
raw-book-only *by design* and raises if asked to capture them. That enrichment loop went dormant on
**2026-07-27** and has no registered task, so there is nothing newer. But:

- **265 event directories already contain `market_ws_events.csv`.**
- Columns include `event_type`, `price`, `size`, `trade_size`, `shares`, `amount`,
  `matched_amount`, `maker_amount`, `timestamp_utc`.
- The window ends **2026-07-27**, entirely **before** the `2026-07-31` provenance boundary, so the
  corpus is provenance-clean by construction. **Do not pool across it anyway.**

**Verify the tape's real coverage before designing.** 265 directories is a file count, not a
guarantee of usable trade density per market-day. If coverage is too thin in some markets, say so
per market rather than pooling to hide it.

## 3. P0 — measure `A` and `f`

**`A` — the adverse move.** After a trade at price `p`, how far does the fair price move *in the
aggressor's direction* over the horizons a maker cares about? Report the markout distribution at
several horizons (seconds to minutes), by market, by price bucket, and by time-to-settlement.
Report the distribution, not just a mean — the tail is what kills a maker.

**`f` — the informed fraction.** What share of executed volume is followed by a persistent adverse
move rather than mean reversion? State your classifier explicitly and pre-declare its threshold.
**There is no ground truth for "informed", so this is a definitional estimate** — give the
sensitivity of `f` to the threshold, and never present one number without that curve.

Then **substitute both back into `-09-46a`'s break-even grid** and report what fraction of scenarios
clear with zero model edge at the measured `f`. That is the deliverable: not `f` alone, but what `f`
implies for the business.

## 4. Method — binding

- **Crossed date × market clustering; power before interpretation.** "Not powered" is a valid verdict.
- **Never pool across `2026-07-31`** (anchor `b77cfbed`). The corpus predates it; keep it that way.
- **Maker perspective, not taker.** We are asking what happens to *a resting quote that gets hit* —
  not whether crossing the spread is profitable. Those are different signs.
- **Beware the reward window.** `rewardsMaxSpread` is 4.5 cents and `rewardsMinSize` 20–50 shares.
  `-09-46a` found per-side size **absent** from the sealed book tape, so if your `f` estimate needs
  it, say it is unavailable rather than substituting aggregate liquidity.
- Deduplicate to `(market, target_date)` before any day-level claim.

## 5. What would falsify this mission

- **`f` is high (≳0.5) across markets.** Then market-centred making is a donation too, and the MM
  track needs a different strategy or a different venue. **Report it plainly** — it is the most
  valuable answer available, because it would close the last open route.
- **The tape cannot support the estimate.** Then the deliverable is a precise statement of what is
  missing and what capture change would fix it, which directly sizes the production work.
- **`A` is small but `f` is high, or vice versa.** Report the joint result; the break-even depends on
  `f x max(A - e, 0)`, so neither alone decides it.

## 6. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Fit nothing, promote nothing, place no order, enable no live
trading, make no provider call.** Do not write production `data/`, run the chain, settle a date, or
restart anything — including the enrichment loop, which is a production decision already flagged to
the operator. Do not weaken a gate or a known-defect fixture.

## 7. Branch and report

- Branch: `codex/workstation-measure-the-informed-flow-fraction-2026-09-47a`
- Report: `docs/roadmap/agent-report-2026-08-10-workstation-informed-flow-fraction.md`

Base on `origin/master`. Note `-09-46a` merges in the 01:00–04:00 quiet window; if your work needs
its break-even grid, take it from the branch and say which you used. Per `DELEGATION_CONTRACT.md`
§5, with production-host reproduction paths and a per-file roll verdict from
`scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.** If you register a schema,
expect exit 3: that is what made both `-09-46a` and the countability post-mortem roll-sensitive.
**Commit and push whenever you finish, at whatever hour.**
