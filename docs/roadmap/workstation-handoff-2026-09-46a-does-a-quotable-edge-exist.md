# Workstation handoff 2026-09-46a — does a quotable edge exist anywhere?

Written 2026-08-08 by the production agent, after an audit of `ESTABLISHED_FINDINGS` against the
project objective. Read on `origin/master` and execute. **This replaces "make the model better" as
the top model question, and §1b explains why.**

## 1. Why the question changed

Three results in one week closed the obvious routes:

- **Inputs are not the gap** (`-09-44a`). Restoring ~28% of trained inputs moved it by at most
  **0.6% of the distance to parity**, on a tight interval. Not underpowered — a precise null.
- **Bias is not the gap** (§2, §4e). In-season the base model is nearly unbiased (**−0.18 C-eq**)
  and the served gap there is still **1.4233x** with the interval excluding 1.0.
- **The declared primary objective is unmeasurable** (§1b.1). The 09:00–14:00 slice endpoint needs
  **~504 dates. We have 50.**

And §1b.2 names the hole this mission fills: **every analysis in this project has measured where we
LOSE. None has asked whether a subset exists where we WIN.** §4d recorded that omission explicitly
and left it.

## 2. Goal

**Determine whether any conditional subset exists, identifiable at quote time, on which our
distribution beats the market's — and whether it is large and stable enough to quote.**

This is not "beat the market on average." `MARKET_MAKING_PLAN.md` Part 0 is explicit that a maker
needs to be *"better-calibrated than the market in specific windows"* for fills to be positive-EV.
Aggregate parity was never the economic requirement; it is the promotion gate's requirement, and
§1b.3 records that nobody has checked whether those two agree.

## 3. THE GUARDRAILS — read these before designing anything

**This is the highest-leakage-risk mission the project can run.** "Search subsets until one wins"
is precisely how item-224 produced a fake win. These are binding:

1. **Pre-declare everything, then hash it, then look.** Before touching any outcome, write the
   complete candidate partition list, the metric, the decision rule, and the multiple-comparisons
   procedure to a file. Commit it. **Put its SHA-256 in the report.** A partition invented after
   seeing results is not a finding.
2. **Subsets may be defined ONLY by information available at the cutoff.** Hour, market, lead time,
   forecast-source disagreement, model entropy, band distance from forecast high, book state — all
   legitimate. **Settlement, realised outcome, "the market was wrong", and anything derived from
   them are forbidden.** A subset you cannot identify while quoting is worth nothing.
3. **Report K and control for it.** Searching K partitions guarantees spurious winners at K x 0.05.
   State K, apply FDR or family-wise control, and report both raw and adjusted.
4. **Crossed date × market clustering, power before interpretation.** "Not powered" remains a valid
   verdict. Recent work ran at 0.05–0.5 and could conclude nothing; say so again if that is the answer.
5. **Never pool across `2026-07-31`** (artifact provenance, anchor `b77cfbed`).
6. **A positive control is mandatory** — pre-repair code must reproduce recorded incumbent
   distributions exactly, as `-09-43a`'s 840/840 did.
7. **Do not consume the untouched confirmation window.** Check `reserved-confirmation-window.md` at
   run time; it wins over this handoff. Any subset that survives P0 is a *candidate*, to be confirmed
   later on data you never touched — not a result.

## 4. P0 — the edge search

For each pre-declared partition, on the replay corpus, report **model Brier vs market Brier** with
crossed intervals, power, and adjusted significance. Axes worth declaring (choose before looking):

- **Hour of day.** The one prior hour-cut we have shows gaps of 0.0163 predawn, 0.0160 on the
  primary slice, and **0.0454 at 20:00–23:00 lock-in** — we are far worse when the market is nearly
  certain. That asymmetry is a strong prior that hour matters. It does not tell you where we win.
- **Band distance from the forecast high.** §4d found 75.87% of severe contribution within one band
  of forecast; the complement is unexamined.
- **Model entropy / sharpness at the tick**, market-implied entropy, and their difference.
- **Forecast-source disagreement**, which §1's older work associated with 78.93% of positive excess.
- **Market**, and **in-season vs out-of-season** (§1b.4 — we serve out-of-season).

**Report the full distribution of per-subset edge, not just the winners.** If every subset is
negative, that is the headline and it is worth more than a marginal winner.

## 5. P1 — what edge does market making actually NEED?

**Compute the break-even.** `MARKET_MAKING_PLAN.md` Part 0 has measured inputs: tick size 0.001,
`rewardsMaxSpread` 4.5 cents, `rewardsMinSize` 20–50 shares, taker fee `5% x (1-p)`, 25% of the fee
pool redistributed to makers, ~$65–71k/event/day notional, books under $100 per side.

Answer: **at what model-vs-market edge does two-sided quoting turn positive-EV**, as a function of
spread captured, fill rate, and informed-flow fraction? Express it in the same units as P0 so the
two can be compared directly.

**If the honest answer depends on the informed-flow fraction and that is unmeasured, say so and
bound it** — the plan already names that as the open question. A bound is a real deliverable.

## 6. What would falsify this mission

- **No subset survives adjustment.** Most likely outcome. **Report it plainly** — it redirects the
  programme away from model work and toward MM economics and plumbing, which is valuable.
- **A subset survives but is tiny or unstable across dates/markets.** Then it is not quotable; say so
  rather than dressing it up.
- **A subset survives and P1's break-even is above it.** Then edge exists and still is not enough.
- **The edge is concentrated where we cannot quote** (no book, below `rewardsMinSize`, outside the
  4.5-cent window). Check this before celebrating; it is the most likely way a real result dies.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. **Fit no promotable candidate, promote nothing, place no order,
enable no live trading, make no provider call.** Do not write production `data/`, run the chain,
settle a date, or restart anything. Do not weaken a gate, threshold, or known-defect fixture.
`pytest -q` on master is green — **if something is red, it is yours.**

## 8. Branch and report

- Branch: `codex/workstation-does-a-quotable-edge-exist-2026-09-46a`
- Report: `docs/roadmap/agent-report-2026-08-09-workstation-quotable-edge.md`
- Pre-registration file: commit it in a **separate, earlier commit** than any result, so the git
  history itself proves the declaration preceded the measurement.

Base on `origin/master`. Per `DELEGATION_CONTRACT.md` §5, with production-host reproduction paths and
a per-file roll verdict from `scripts\ops\roll_verdict.ps1 -Branch <branch>` — **never hand-derived.**
**Commit and push whenever you finish, at whatever hour.**
