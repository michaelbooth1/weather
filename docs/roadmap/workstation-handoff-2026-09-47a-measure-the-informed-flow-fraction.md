# Workstation handoff 2026-09-47a — can executions be reconstructed at all?

Written 2026-08-08 by the production agent. **Rewritten the same evening after the original premise
was falsified on this host — read §2 before anything else.** Read on `origin/master` and execute.

## 1. Why this matters

`-09-46a` closed the model route: 114 pre-declared cells, **zero** with positive edge, overall
**−0.01915 [−0.02444, −0.01443]**. Model-skewed quoting is retired.

Its P1 kept one route open — **market-centred spread harvesting needs no model edge** — and showed
the answer is dominated by the informed-fill fraction `f`:

| Informed fraction `f` | Scenarios breaking even with **zero** model edge (no reward) |
| ---: | ---: |
| 0.10 | **79.43%** |
| 0.50 | 42.29% |
| 1.00 | **24.57%** |

At low `f` the maker is a business; at high `f` it is a donation. **Nothing else on the board moves
the answer as much.**

## 2. THE ORIGINAL PREMISE OF THIS MISSION WAS WRONG

The first version of this handoff told you to measure `f` from 265 captured `market_ws_events.csv`
files. **Do not do that.** Measured on production before you were dispatched:

| `event_type` | Rows in a 60-file, 1,107,984-row sample |
| --- | ---: |
| `book` | 904,325 |
| `price_change` | 203,584 |
| **`last_trade_price`** | **71** |

**Seventy-one executions in 1.1 million rows.** There is no execution tape. Commit `8e7b5732` had
already recorded that the tape "loses execution identity and exchange time" and that arming the loop
would "generate volume without producing evidence." That was correct.

**The production agent wrote a mission on a schema and a file count without opening a file. Do not
inherit that mistake — open the data before you design anything.**

## 3. P0 — is an execution signal recoverable at all?

**This is a feasibility question first and a measurement second. Answer it in that order and stop if
the answer is no.**

1. **Can executions be reconstructed from `price_change` and `book` deltas?** 203,584 `price_change`
   rows exist. A fill removes size from a level. Determine whether depletions are separable from
   cancellations with usable precision — and **say plainly if they are not.** Cancel-vs-fill
   ambiguity is the whole difficulty; do not assume a depletion is a trade.
2. **If separable, what is the aggressor side**, and can you time it well enough for a markout?
3. **Only if 1 and 2 succeed**, estimate `A` (adverse move after an inferred execution, by horizon,
   market and price bucket) and `f` (share of inferred executions followed by persistent adverse
   movement rather than reversion). Pre-declare the classifier threshold and report `f`'s
   sensitivity to it — there is no ground truth for "informed."
4. Substitute the result back into `-09-46a`'s break-even grid and report what fraction of scenarios
   clear with zero model edge. **The deliverable is not `f`, it is what `f` implies for the business.**

## 4. P1 — what feed would actually settle this?

Independent of the above, and cheap: **does the venue expose an execution feed we are not
consuming?** Document what is available — a trades channel, a fills or trade-history endpoint,
whatever exists — with the exact subscription or call, the fields it returns, and whether execution
identity and exchange timestamp survive.

**Do not call it.** Document it. This sizes a production capture change, and that change is the
operator's decision, not yours.

*(Scope note: the standing "no paid API" rule is about **weather** providers. The exchange's own API
is a different question — but you are still documenting, not calling.)*

## 5. What would falsify this mission

- **Executions are not separable from cancellations.** Most likely outcome. **Report it plainly** —
  it means `f` is unobtainable without a capture change, which is itself the decision-relevant
  answer and sizes P1's importance.
- **They are separable but the inferred rate is far too low or too noisy** to support a markout.
- **`f` comes out high (≳0.5).** Then market-centred making is also a donation, which closes the
  last open route. That is the most valuable answer available, so do not soften it.

## 6. Context you should not have to re-derive

Two findings from `8e7b5732` remain live and bound anything you conclude:

- **Reward qualification is arithmetically out of reach**: the 20-contract minimum needs **$19.60**
  against a **$10** `max_band_notional` cap. So evaluate the **$0-reward** column of the break-even
  grid as the realistic case unless the cap changes.
- `-09-46a` found per-side size **absent** from the sealed book tape, so `rewardsMinSize`
  eligibility cannot be checked from it. Aggregate liquidity is not a substitute.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Fit nothing, promote nothing, place no order, enable no live
trading, call no exchange or provider endpoint.** Do not write production `data/`, run the chain,
settle a date, or restart anything — including the enrichment loop. Crossed date × market
clustering; power before interpretation; never pool across `2026-07-31`.

## 8. Branch and report

- Branch: `codex/workstation-can-executions-be-reconstructed-2026-09-47a`
- Report: `docs/roadmap/agent-report-2026-08-10-workstation-execution-reconstruction.md`

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never
hand-derived.** Registering a schema will make you roll-sensitive; that is expected.
**Commit and push whenever you finish, at whatever hour.**
