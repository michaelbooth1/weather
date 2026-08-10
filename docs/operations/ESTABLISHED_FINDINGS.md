# Established Findings

Status: canonical distillation of the agent correspondence. Written for LLM agents.

`docs/roadmap/` holds ~600 dated handoffs and reports. No agent can read them. This file is the
distilled state of what they established, so that a cold agent — or one whose context was compacted —
starts from what we know instead of re-deriving it.

**How to use this file.**

- Findings here are **measured results with dates and support**, not invariants. They are durable as
  *records* even when the world moves. `AGENT_CONTEXT.md` owns invariants; this file owns evidence.
- **Before citing any interval in a decision or report, re-verify it against the named source
  report.** Numbers here are for orientation and for stopping re-derivation, not for quoting as
  fresh measurements.
- Claims that were retracted, and traps that look true, live in
  [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md). **Read that file too.** Several of the
  costliest hours in this project were spent re-discovering something already known to be false.

---

## 0. Objectives, in priority order

1. **Protect the Toronto capture streak.** Contiguous complete Toronto days gate the learning loop and
   release admissibility. A lost streak day is the most expensive routine failure available.
2. **Build a better FORECAST than the market — from our own information.** We currently do not
   beat it (§1). **The central goal is stated in full in §0c and that section governs**: aim at
   forecast accuracy, never at benchmark-consuming shortcuts, and expect the tradeable edge to
   follow in time rather than be targeted directly.
3. **The end goal is the market-making bot.** MM outranks the taker. It is **downstream of
   objective 2, not a competing objective** (§0c). The taker is deprioritized and its tape deleted.

**The primary model objective is the 09:00–14:00 local slice**, leakage-audited and walk-forward — not
aggregate Brier. Aggregate-Brier chasing was explicitly abandoned: it hides the slice where the model
is weakest and where the tradable edge would live.

---

## 0a. The PIT 21-field wall is REAL — and the production agent's fix would have re-broken a known defect

**`-09-55a`, 2026-08-09. NO-GO.** The frozen 21-field point-in-time contract is **not satisfiable on
the free tier**, and it is **not** the routing defect I proposed.

**I conflated field AVAILABILITY with point-in-time VALIDITY.** I argued that because production's
archive holds 461 days of exactly those 21 fields from `historical-forecast-api`, the fields are
free-tier available and the plan was simply querying the wrong endpoint. The fields are available.
**They are not available as of an issue time**, and that is the whole content of the contract.

Verified directly in `data/forecast_history/cyyz/forecast_long.csv` — `issue_time_basis` splits
**exactly by source**:

| Source | `issue_time_basis` | Rows |
| --- | --- | ---: |
| `open_meteo_previous_runs` | **`fixed_lead_day_offset`** — genuine issue-time evidence | 51,240 |
| `open_meteo_historical_forecast` | **`stitched_continuous_archive`** — settled, no true issue time | 11,064 |

**So genuine PIT provenance exists on the free tier for temperature only.** Historical Forecast
returns the *settled* profile; it cannot say what was forecast at the cutoff.

> **And the repair I proposed has a name in this repository already.**
> `stitched_forecast_high_without_issue_time` is a **declared known defect** in
> `train_serve_feature_parity_known_defects_v0.1.json`, dimensions `availability` and `provenance`,
> and `forecast_high is NOT point-in-time` is recorded as **~6% of the cool bias**. Sourcing the 21
> fields from stitched data would have re-introduced a contamination defect the project already
> tracks by name. **The mission stopped rather than silently changing candidate training semantics.**

**This retroactively supports §0b.** The retrain path's terminal blocker is a genuine wall requiring
either a paid provider (closed, forbidden) or a contract change that would degrade point-in-time
honesty. **Stepping off that path was correct, and this NO-GO closes it out rather than costing us.**

## 0b. OPERATOR DECISION 2026-08-09 — the goal is a BETTER model, not a QUALIFIED one

**"I think the goal should be a better one. I am happy making small improvements at a time until we
hit our goal."**

### What this drops

The **production release and qualification machinery** stops being the critical path: the release
store and active pointer, promotion, immutable qualification, Release #1, and the `base_retrain`
blocker chain that consumed six missions in a single day. Every one of those blockers was the same
shape — **designed and never built** — and the chain was being walked for a payoff that **cannot
currently be quantified**: §1's `74.97%` is retired **with no replacement**, so the retrain's
expected value has no current estimate.

Meanwhile the **only shipped improvement in the month** was a **serving-path** fix needing none of
that machinery (§3: served 1.6639 → 1.4980).

### What this does NOT drop — and this is not negotiable

**Leakage-free, point-in-time-honest evaluation.** "Better" measured with leakage is not better, and
this project has already retracted exactly that claim once: **item-224's "win" over the market was
leakage** (`RETRACTED_AND_FALSE_LEADS.md` §1). Dropping *qualification* must never become dropping
*honesty*.

So every improvement still requires: crossed date × market clustering, power stated before
interpretation, no pooling across `2026-07-31`, and a walk-forward or replay design that cannot see
its own target. **The bar for believing a result is unchanged. Only the bar for shipping one moved.**

### What it means in practice

Work is now ranked by **measurable served improvement per unit of effort**, using the existing
replay harness. The retrain remains desirable and is no longer the gate.

*(The instruction that stood here — "decompose the gap before picking improvements" — was **carried
out**: `-09-56a` → §1c, and `-09-57a` → §1d. It is no longer a prerequisite; it is a result.)*

---

## 0c. THE CENTRAL GOAL — operator, 2026-08-09

> **"We should always aim for a better forecast which in time should lead to a tradeable edge
> somewhere."**

**This is the standing goal of the project. It resolves the ambiguity in §0b — "better" means a
better FORECAST.** Read it as the ordering rule for every future decision.

### Why it is right, stated so nobody re-opens it

1. **It is the only axis we can measure today.** We have Brier, a market benchmark, crossed
   clustering, and a panel with a known MDE per stratum (§1d). We have **zero** trading outcome
   evidence — **no trade has ever been made and `fills.jsonl` has never been written** (§8b).
   Optimising the unmeasurable is precisely how a month was spent on eligibility meters.
2. **Forecast accuracy is an OUTCOME, not a proxy.** It is the one thing this project has ever
   measured honestly, and it is immune to the dominant defect pattern (`HOW_WE_GET_THINGS_WRONG.md`
   pattern 2).
3. **"Somewhere" is load-bearing and correct.** Edge need not exist in every market or hour.
   `-09-46a` found zero positive cells in 114 — **for the current model**. A materially better
   forecast is what could open a cell that does not exist today.

### The ONE qualifier, without which the goal misfires immediately

**Better *from our own information* — never by consuming the benchmark.**

This is not pedantry; it is load-bearing, and the evidence is one day old. On a pure
forecast-accuracy criterion, the top-ranked candidate we currently hold is **market shrinkage:
65.111% of the gap closed, confirmable today, and provably zero tradeable edge** (§1c). The goal as
literally stated would select it first. **A forecast improvement obtained by moving toward the
market cannot ever become an edge over that market.**

Those controls keep their real value: they **localise where our information is missing** — the
disagreement set. **Rank 1 is an instrument pointing at rank 4, not a candidate.**

### And the conversion is not automatic — there is a threshold

§1's standing caveat binds this goal: the 1.42x comparison is against **market mid**. A taker pays
`5% × (1−p)` and cannot trade at mid; a maker is paid the spread. **Forecast improvement converts
to edge only above transaction costs; below that threshold it converts to nothing at all.** So
"in time" is honest, and **no accuracy gain may be reported as expected P&L without re-deriving it
in trading terms.**

### What this changes in practice

- **§0 objective 2 is now "a better forecast than the market", not "a model that beats the market"**
  — the same target, stated as the thing we can measure.
- Rank work by **expected served accuracy gain from own-information sources**, per unit of effort.
- **Benchmark-consuming controls are diagnostics.** Never rank, ship, or book them as improvement.
- The MM track is **not cancelled** — it is downstream. §1c's open MM hypothesis (a maker needs a
  fair value that is not *worse* than the market's, not one that beats it) remains a legitimate
  question and is unaffected by this ordering.

## 1. We do not beat the market

This is the central finding of the project. Treat any result claiming otherwise as suspect until it
survives the method rules in §5.

| Finding | Value |
| --- | --- |
| **Current in-season gap** | **1.423246x [1.242584, 1.659022]** — served, excluding 1.0 (`-09-44a`) |
| Gap on the clean regime | **1.24x** — a *different, older panel*. Do not equate it with the above |
| Nature of the gap | **Resolution, not calibration** |
| Skill decomposition | **84.772% resolution / 15.228% reliability** (`-09-44a`, current surface) |
| Consequence | The gap is an *information* problem. **But see the reliability caveat below** |
| Blending model with market | **Hurts** on clean data |

**Never globally sharpen** — it is the wrong axis and it degrades calibration for nothing.

### FOUR legacy headline numbers are retired from citation — 2026-08-09 (`-09-44a`)

`-09-43a` changed the serving input surface, so every headline measured before it describes a model
that no longer exists. `-09-44a` re-measured on the sealed pre-boundary replay corpus (D=50, M=12,
524 promotion-countable market-days, 12,289 snapshots — the same population as §2 and §4e).
**Do not cite the left column as a property of the model we serve:**

| Legacy number | Status | Current surface |
| --- | --- | --- |
| **98.88% / 1.12%** resolution / reliability | superseded | **84.772% / 15.228%** |
| **−0.6641 C-eq** cool bias | superseded | **−0.64387 C-eq** (§2) |
| **4.26% / 60.2%** severity tail | superseded | **4.387% / 64.140%** — concentration is *higher* |
| **74.97%** centre oracle ceiling | **unciteable, and NO replacement exists** | none authorised |

The differences are **panel**, not repair: the repair moved none of them detectably. The legacy
values remain valid records of what they measured; they are simply not measurements of today's model.

**`74.97%` is the one that leaves a hole — and `-09-44a` gives the wrong reason for it.** The report
says that oracle panel is *post*-boundary and so cannot be pooled. **It is not.** That panel is
**07-22 → 07-30, 19,265 snapshots** — it sits *inside* `-09-44a`'s own 06-03 → 07-30 corpus and on
the **same** side of the `2026-07-31` boundary. Provenance does not forbid a rebind.

**The refusal is still correct, on the report's other ground:** the oracle construction is not a
retained CLI and cannot be rebound to the repaired replay without building a new estimator. So
`74.97%` is stale because the *surface* changed and nobody has re-derived it — **not** because the
data are incompatible. Do not let someone later notice the provenance claim is wrong and treat that
as licence to reinstate the number. **"Centre is 74.97% of oracle excess loss" is unavailable as a
justification for anything** until it is re-derived; the retrain's remaining argument is §2's
measured −0.8346 C-eq seasonal centre defect, which is *smaller*. The mechanism is untouched:
too-cool mass below the trusted floor is truncated and shifts served centre. **Never weaken the floor.**

**The reliability share is the number to look at.** `1.12%` said calibration was worth nothing.
The current-surface figure is **15.228%** — over an order of magnitude larger. The repair did not
cause the change — paired delta **+0.076pp [−0.246, +0.452], power 0.074**.

> **DECIDED 2026-08-09 (`-09-56a`) — do not fit a recalibration pass.** The open question here was
> "is any of the 15.228% recoverable?" It was answered by measuring recovery directly rather than
> by reconciling denominators: a mapping fitted on in-season B and scored on out-of-season C
> recovers **8.829% of the gap, crossed 95% [−2.467%, +16.494%]**. See **§1c**.
> **The two percentages still do not share a denominator** — 15.228% is a share of served *loss*,
> 8.829% a share of the *gap versus the market*. **Never equate them, and never subtract one from
> the other.** They agree only on the decision, which is no.

**Loss is still concentrated in a severity tail.** **4.387% of band rows carry 64.140% of positive
excess loss.** Any work that improves the pooled average while leaving the tail alone is close to
worthless.

---

## 1b. Audit 2026-08-08 — five assumptions that do not survive checking

Commissioned after `-09-44a` ruled out inputs. Nothing here is a new measurement; each item is a
**gap in what has been measured**, found by re-reading this file against the objective.

### 1. The declared primary objective is UNMEASURABLE, by ~10x

§5 records it plainly and the consequence was never drawn: **the 09:00–14:00 primary-slice
endpoint needs ~504 dates. We have 50.** At one date per day that is over a year away. The
severe-tail endpoint needs **~4**.

So the objective the project declared primary is the one it cannot evaluate, and the endpoint it
*can* evaluate with 12x margin is under a "do not tune" hold (§4d). Aggregate Brier — also
measurable — was explicitly abandoned. **Every decision taken "on the primary objective" is
uninterpretable**, which is exactly what the slice gate's 99.885% false-rejection rate showed.

**Choose objectives by measurability as well as relevance.** An endpoint you cannot power is an
aspiration, not an objective. This does not make the 09:00–14:00 slice the wrong *target* — it
makes it unusable as a *decision rule* until the corpus is ~10x larger.

### 2. We have measured only where we LOSE — ANSWERED 2026-08-09: there is nowhere we win

Every decomposition in this file was a loss decomposition, and no analysis had asked whether a
subset exists where we beat the market. `-09-46a` asked it. **The answer is no, everywhere.**

**114 non-empty pre-declared cells. ZERO with a positive point estimate.** `skill_candidate` is
False on all 114. Overall edge **−0.01915, crossed 95% [−0.02444, −0.01443]**. No raw winner, so
Holm adjustment never came into play. Positive control 840/840 exact. Edge range **−0.32289 to
−0.00002**; the only two cells whose interval reaches zero do not cross it, and the least-negative
sits at **D=3** date clusters with no support.

**The structure is the finding: we match the market only where we already agree with it.** The
least-negative cells are exactly the agreement cells — `signed_probability_gap −0.05..0.05` at
−0.00015, and every `within_10pp` hour cell at −0.0003 to −0.0007. The worst cells are where we
disagree most. **Where we copy the market we score like it; where we deviate we pay.** That is
what "no information edge" looks like when it is measured rather than inferred.

**Integrity of the null.** The pre-registration commit is the *first* on the branch and carries the
full implementation and tests, four commits before any result — so the method was frozen before
measurement. Note the guardrails were built to stop a false *positive*; a uniformly negative result
is not that failure mode, and the tight overall interval says this is a precise null, not a blind one.

**This retires model-skewed quoting as a strategy.** Do not commission further work premised on
finding a window where the model beats the market. It was searched, exhaustively and honestly.

### 3. The promotion gate is stricter than the ECONOMICS require

| Source | What it demands |
| --- | --- |
| `hourly_model_performance` (§9) | early-hour Brier within **0.0030** of the market, **in all 12 markets**. We trail by **0.0205** — 7x |
| `MARKET_MAKING_PLAN.md` Part 0 | *"with a model that is better-calibrated than the market **in specific windows**, quotes can be skewed so being filled is itself positive-EV"* |

**These are not the same requirement.** A maker earns spread from uninformed flow and loses to
informed flow; it needs edge *where it quotes*, not a fleet-wide aggregate.

**QUANTIFIED 2026-08-09 (`-09-46a` P1).** A 21,000-scenario declared sensitivity grid over adverse
move `A`, informed-fill fraction `f`, spread capture, fill rate, price and reward:

| Daily reward per band | Scenarios where **zero model edge** breaks even |
| ---: | ---: |
| $0 | **45.94%** |
| $0.20 | **72.27%** |
| $1.00 | **88.99%** |

| Informed fraction `f` | Zero-edge share (no reward) |
| ---: | ---: |
| 0.10 | **79.43%** |
| 0.50 | 42.29% |
| 1.00 | **24.57%** |

**So market-centred spread/rebate/reward harvesting is viable without any model edge across a wide
range — and its viability is dominated by `f`, which is unmeasured.** This is a sensitivity bound,
not a fitted flow model or a P&L claim: `A` and `f` are both unmeasured, so **no unique break-even
may be quoted.** It does not rescue a model skew — §1b.2 is negative in every cell.

**`f` is now the single most decisive unmeasured number in the project.**

**A capture gap blocks the rest of it:** `rewardsMinSize` eligibility is **ABSENT** from the sealed
tape, which has no contemporaneous per-side size. A valid best bid/ask exists on **51.41%** of rows
and a book within the 4.5-cent window on **45.85%** — but whether our quote would have *qualified*
for rewards cannot be answered from what we capture today. Aggregate liquidity is not a substitute.

### AND TRADE CAPTURE HAS BEEN OFF SINCE 2026-07-27 — traced 2026-08-08

`f` needs trade events. **The latency-critical CLOB loop is raw-book-only by design and refuses to
capture them** (`_assert_raw_loop_contract` raises: *"the latency-critical CLOB loop is
raw-book-only; run … enrichment-loop for price history, WebSocket events, and derived features"*).
`DEFAULT_LOOP_INCLUDE_WS_EVENTS = False` is correct for that loop.

Trade events come from the **separate `clob_enrichment` loop**, and:

| | |
| --- | --- |
| Newest `market_ws_events.csv` | **2026-07-27 09:51** |
| Registered scheduled task | **NONE** |
| Its status file | `include_ws_events: True` — configured, simply not running |
| Event dirs holding a `market_ws_events.csv` | 265 |
| **Executions in those files** | **essentially none — see below** |

### THE TAPE CONTAINS NO EXECUTIONS — measured 2026-08-08, and it was already known

**Across a 60-file, 1,107,984-row sample of the captured tape:**

| `event_type` | Rows | Share |
| --- | ---: | ---: |
| `book` | 904,325 | 81.6% |
| `price_change` | 203,584 | 18.4% |
| **`last_trade_price`** | **71** | **0.006%** |
| `tick_size_change` | 3 | — |

**Seventy-one executions in 1.1 million rows. `f` is NOT measurable from this tape**, historically
or going forward, and **re-arming the enrichment loop would not change that** — it would capture
more book and `price_change` rows and essentially no trades.

**This was already established and written down.** Commit `8e7b5732`
("*disarm the enrichment loop — its justification did not survive review*", 2026-07-27) disarmed it
deliberately on two grounds, both still live:

1. **The reward-size floor exceeds the position cap.** Qualifying for the 20-contract minimum needs
   **$19.60** against a **$10** `max_band_notional`; even the limiting positive-score quote needs
   **>$18.20**. Reward qualification is arithmetically out of reach at the current cap.
2. **The tape is not safely scoreable** — the scorer admits `price_change` rows, duplicates raw and
   CSV messages, and loses execution identity and exchange time. *"Enabling the loop would have
   generated volume without producing evidence."* Cost was ~17% duty cycle and hundreds of MB/day.

**What `-09-46a` P1 does change** is ground 1's *conclusion*, not its arithmetic: zero model edge
breaks even in 45.94% of scenarios at **$0** reward, so spread capture without reward qualification
is a live route the July review did not price. Ground 2 is untouched and is the binding blocker.

**Two lessons, and the second is mine.** The `roll_verdict` line
`WARN dormant closure clob_enrichment … cannot affect this verdict` is true *about the roll verdict*
and silent about capture; it read as a footnote for twelve days. And: **I confirmed the schema had
trade columns and that 265 files existed, and commissioned a mission without opening one.** A schema
is not data and a file count is not content — the same failure as [[a-grep-is-not-a-trace]], one
level up.

### AND EXECUTIONS CANNOT BE RECONSTRUCTED FROM WHAT WE DID CAPTURE — 2026-08-10 (`-09-47a`)

**Verdict `NO_GO_EXECUTIONS_NOT_IDENTIFIABLE_FROM_BOOK_DELTAS`.** `A`, `f`, and any measured
break-even share are **UNIDENTIFIED — not imprecise, not underpowered.**

**A `price_change` row carries post-change level *state*, not an execution record.** A level going
100 → 60 is observationally identical whether 40 shares were cancelled or 40 were executed; a zero
level says the level disappeared, not why. The retained row has no execution type, executed size,
trade ID, transaction hash, or vendor timestamp.

> **The decisive point, and the one to quote:** the tape has sparse *positive* labels
> (`last_trade_price`) and **no cancellation labels at all**, so there is **no false-positive
> denominator**. Precision is not low — it is **unestimable**. Matching depletions to known trades
> could bound recall; nothing could ever show that unmatched depletions were trades.
> **Do not accept a proposal to "improve the classifier": the discriminating variable was never
> captured.**

Successive `book` snapshots do not rescue it. Capture is **20 s per 900 s = 2.222% nominal time
coverage**, every connection re-opens with a fresh book, and no session ID, sequence number or gap
ledger is retained — so a difference between two initial books spans unobserved placements,
cancellations *and* executions. Verified in production source, not taken on report:
`ws_summary_rows` reads `timestamp_utc` while the vendor sends `timestamp` and there is no
transaction-hash column (**identity is dropped by our normalizer, not withheld by the venue**), and
`register_clob_enrichment.ps1` sets `IntervalSeconds=900` / `WebsocketSeconds=20.0`.

Workstation inventory over its historical copy (D=23, M=12, 265 market-days, all before the
`2026-07-31` boundary, nothing pooled across it): **4,493,597 rows, 411 `last_trade_price`
(0.0091%)**, `price_change` rows carrying a usable timestamp **0 / 758,189**, `book` rows retaining
levels in the CSV projection **0 / 3,734,993**.

**Crossed intervals and power are NOT APPLICABLE here** — they quantify sampling uncertainty *after*
an estimand is identified. "Not powered" would understate this: there is no valid observation unit.

**This does not say `f` is high or low, and market-centred harvesting stays open.** It says the
question cannot be answered from anything we hold or can derive. **The only route is forward
capture** — see §8c.

### 4. We evaluate in-season and SERVE out-of-season

The headline 1.4233x is **in-season**. The archive covers May 10 – Jun 30 (§4b), so in August
**every date we serve is out-of-season**, where the measured ratio is **1.526x → 1.542x**
(`-09-44a`) — worse, and the stratum the repair moved unfavourably (+0.016, not powered).
**Citing 1.4233x as "the gap" understates what we actually serve.** Say which stratum, always.

### 5. The GAP has never been decomposed on the current surface — **RESOLVED 2026-08-09 (`-09-56a`), see §1c**

*Original text, kept because it states the estimand precisely:* §1 carries a served-**loss**
decomposition (84.772% / 15.228%). The retired 98.88% / 1.12% decomposed the **gap versus the
market**. Those are different estimands on different panels, so **neither answers "of our excess
Brier over the market, how much is calibration and how much is information?"** on today's model.

**`-09-56a` answered it. The gap is information-dominated: recoverable calibration is bounded at
16.494% of the served gap and is not distinguishable from zero. See §1c.**

### A standing caveat on the benchmark itself

The 1.42x comparison is **model versus market mid-price**. That is the right benchmark for "are we
the better forecaster." It is **not** the right benchmark for "can we make money": a taker pays
`5% x (1-p)` and cannot trade at mid, while a maker is paid the spread. **Do not carry a
mid-price accuracy comparison into a profitability conclusion without re-deriving it.**

---

## 1c. THE GAP IS INFORMATION, NOT CALIBRATION — measured, `-09-56a`, 2026-08-09

Closes §1b.5 and the §1 "establish the denominator" question. **Fit on in-season B (D=23), score on
out-of-season C (D=27, the stratum we actually serve).** Method frozen before any result at
predeclaration `d8e49409`; source is the `-09-44a` repaired export, SHA-256 `9a70ac80`. Verifier
reproduced **22/22** checks including both ratios.

| Quantity, out-of-season C | Value | Crossed 95% |
| --- | ---: | ---: |
| Raw model / market Brier | `0.060112820` / `0.038977498` | ratio **1.542244x** |
| Raw excess gap | `0.021135322` | — |
| **Recoverable calibration share** | **8.829%** | **[−2.467%, +16.494%]** |
| **Remaining information share** | **91.171%** | **[83.506%, 102.467%]** |

Power **0.458**, 80%-power MDE **13.344pp** — below the binding bar.

**Cite the BOUND, never the point.** 8.829% is underpowered and may be zero. What the interval
licenses is that **even at its most favourable endpoint, calibration is at most 16.494% of the
gap** — a minority throughout. That is enough to close calibration as a workstream and not enough
to claim a recoverable 8.829%. **`8.829%` must not become a headline number**; four of those were
retired in one day on 2026-08-09 already.

**Scope of the bound: the leakage-safe monotone families actually tested.** Scalar isotonic,
per-market isotonic, daily-expanding isotonic, and the simplex-native power map `q ∝ p^β`
(β=0.55 selected on B only, reselected inside all 10,000 bootstrap draws). It does **not** prove
every conceivable mapping is worthless. It does mean nobody should build one without a new
mechanism.

### The predeclared isotonic map made things WORSE — and the reason is a method rule

It worsened C Brier by **+0.018168 [+0.012980, +0.022995]**, and — the diagnostic that matters —
**worsened its own B *training* score, 0.053380 → 0.078717.** Implementation was correct: zero mass
failures, zero order violations. **Binary per-band PAVA followed by categorical renormalization is
not fitting the objective being scored; the fit does not survive the simplex projection.** A
mapping that cannot improve its own training score is a broken objective, not a weak signal.
**Check the training score first — it is free and it localises the fault instantly.**

### The market-shrinkage numbers are a MEASUREMENT, not a candidate

| Control on out-of-season C | Brier improvement | Gap closed |
| --- | ---: | ---: |
| Shrink 50% toward market on `\|model−market\| ≥ 0.30` rows | `0.013761 [0.010011, 0.018194]` | **65.111% [60.514%, 70.111%]** |
| Shrink 25% toward market, global | `0.009437 [0.007316, 0.011937]` | 44.652% [42.055%, 48.722%] |
| Full market replacement on the disagreement set | `0.018099 [0.012472, 0.024704]` | 85.632% — an **opportunity ceiling** |

**These consume the benchmark they are scored against.** They establish that when we disagree
sharply with the market the market is usually right, and they **localise our information deficit to
the disagreement set**. They are not evidence of edge — `-09-46a` found **zero** positive
model-skew cells in 114 — and they cannot be cited as a route to beating the market.
**Never book a market-shrinkage delta as model improvement.**

**But the MM question is OPEN, not closed — do not let the paragraph above be read as forbidding
it.** A maker does not need to *beat* the market; it earns the spread and needs a fair value that
is not *worse* than the market's, i.e. it needs to avoid adverse selection. A market-shrunk fair
value is exactly that shape, and `-09-48a` found the harvest path blocked on **having** a fair
value at all. **This is a hypothesis to trace, not a finding**, and §1's standing caveat binds it:
a mid-price accuracy comparison must be re-derived before it becomes a profitability conclusion.
Anyone testing it must price adverse selection and the maker's actual fill economics, not Brier.

**Citation hazard — two "blending" results that do not contradict each other.** §1's *"blending
model with market HURTS on clean data"* is an older panel, clean regime, global blend. This is the
**out-of-season current surface, gated to the disagreement set**. Different panel, different
stratum, different gate. **Neither refutes the other; cite the one whose stratum you are in.**

### Deprioritized by this result

- **Recalibration as a workstream — closed** (see the bound above).
- **Scalar isotonic mapping — NO-GO** on this categorical surface.
- **Global sharpening — still retired.** The fitted β is **below 1**, i.e. *smoothing*.
- **More input completeness — still not a gap-closing candidate.** `-09-44a` bounded it; `-09-56a`
  found no new mechanism.

---

## 1d. WHAT THE PANEL CAN CERTIFY — `-09-57a`, 2026-08-09

`-09-56a` says what to improve. **This says whether we could ever tell that we did.** Positive
control reproduced to `6.1e-18`: `-09-44a`'s in-season MDE is exactly `0.0030551161`.

### The tail is NOT blind — the feared premise is falsified

| Endpoint | D/M/rows | 80% MDE | **MDE as share of that endpoint's gap** |
| --- | --- | ---: | ---: |
| In-season ratio | 23/12/50,996 | `0.0030551` | **0.7218%** |
| Out-of-season ratio | 27/12/84,183 | `0.0377305` | **6.9582%** |
| **Severity tail SSE** | 49/12/5,930 | `0.0151764` | **3.5326%** |
| 09:00–14:00 primary | 49/12/34,694 | `0.0016776` | **9.3700%** |

**The panel can referee the tail that carries 64.140% of the loss**, at 3.53% of its remaining gap
(4.87% under the ledger). **The primary window stays too blunt** at 9.37% — §5's ~504-date
requirement is unchanged; the window remains a readout, not an accept/reject rule.

### THERE IS A HARD FLOOR, AND IT IS SET BY MARKETS NOT DATES

**The 12 fixed market clusters leave an asymptotic MDE floor of ~`0.0173` ratio points, ~3.2% of
the out-of-season gap.** Checked directly: **D=100,000 still gives `0.0173087`.**

> **A step worth ≤2.5% of the gap is NOT confirmable at any date count.** More waiting cannot fix
> it. Only more markets, a paired design, or batching can.

Confirmation schedule (design simulation over the sealed cluster structure — **no post-boundary row
was read**): D=5 today → 15.06% · D=9 on 08-13 → 11.37% · D=15 → 9.03% · **D=29, 2026-09-02** for a
6.96% step · **D=73, 2026-10-16** for a **5%** step · D=365 → 3.62%.

### Unadjusted reuse is unsafe — see `CAMPAIGN_LEDGER.md`

Ten unadjusted looks give a **39.0%** false-accept probability; fifty give **92.2%**, with a mean
best null "improvement" equal to the whole `-09-44a` MDE. **The 20-decision α=0.0025 ledger is
adopted and live in `CAMPAIGN_LEDGER.md`; 7 of 20 are already spent by `-09-56a`.**

### Synthesis with `-09-56a` — done here because each mission was forbidden the other

| `-09-56a` candidate | Out-of-season gap closure | Confirmable |
| --- | ---: | --- |
| Shrink 50% toward market, disagreement set | **65.111%** | at **D=5, today** — but it *consumes the benchmark* |
| Shrink 25% toward market, global | 44.652% | at D=5 — same objection |
| Season-matched refit (proxy) | 24.893% | at D=5, but its own CI is [−20.5%, +55.2%] |
| Global smoothing `q ∝ p^β` | 8.829% | ~D=17, ~2026-08-21 — CI already includes zero |
| **New PIT information feature** | **unidentified** | **cannot be scheduled** |

**Every sized candidate clears the 3.2% floor. The one that would constitute real edge is the one
with no size.** And these are **indicative, not certified**: `-09-57a` is explicit that MDE depends
on the candidate's own date × market effect field, and its curve is a proxy built from `-09-44a`'s
repair-minus-control field. **Re-derive the MDE for the candidate you actually test.**

### The consequence for "small improvements at a time"

**The path is viable but has a minimum step size.** Practically, **≥5% of the gap**, confirmable
from **2026-10-16**. Below ~3.2%, improvements are *permanently* unconfirmable individually and
**must be accumulated and tested as a batch.**

---

## 2. The cool bias is real and is not correctable at serve

| Property | Value |
| --- | --- |
| Magnitude | **−0.6641 C-equivalent** |
| Crossed 95% interval | **[−1.1164, −0.2482]** |
| Support | D=34 date clusters, M=12 markets, 399 market-days |
| Survives crossed clustering | **Yes** — one of only two headline results that do |

**Current-surface value, 2026-08-09 (`-09-44a`): −0.64387 C-eq.** On the D=50 corpus the pooled
frozen-base centre error moved from **−0.70449 → −0.64387** after the input repair, a paired shift
of **+0.06061 [+0.00356, +0.12855], power 0.484**. The interval excludes zero but power is below
the binding 80% bar, so **this is not promoted to a directional finding**. At face value the repair
recovered ~9% of the bias. **The cool bias survives the repair essentially intact, so the retrain
is still needed.** Cite −0.64387 for the current surface and −0.6641 only as the older panel's record.

**Do not implement a serving-side offset.** Market heterogeneity forbids it: the bias is not uniform
across markets, so a global correction helps some and harms others.

### The root cause is MEASURED, 2026-08-06: it is seasonal coverage, not staleness

`-09-31a`, base HGB via replay, both strata out-of-sample, entirely inside the pre-`2026-07-31`
regime. 12,289 hourly snapshots, D=50, M=12, 524 market-days.

| Estimand (C-equivalent) | In-season **B** | Out-of-season **C** | C−B [crossed 95%] |
| --- | ---: | ---: | --- |
| **Base HGB** centre − settlement | **−0.1848** | **−1.0193** | **−0.8346 [−1.4378, −0.2159]** |
| **Market** implied centre − settlement | +0.0699 | +0.0642 | −0.0057 [−0.1643, +0.1520] |

B is D=23/M=12/MD=204; C is D=27/M=12/MD=320. Power **83.17%**, 80%-power MDE 0.8196.

**In-season the model is very nearly unbiased (−0.18). Out-of-season it is a full degree cool
(−1.02). The market shows no seasonal movement at all — its interval spans zero.** So this is
not the weather, and it is not general staleness: **it is the archive's May 10 – Jun 30 coverage
(§4b).** The pooled −0.6641 above sits between B and C because it is a mixture of dates at
different seasonal distances — it is a property of *where we evaluated*, not a fixed property of
the model.

**What this does NOT establish.** The same contrast on the severity tail is **underpowered —
47.65%, 80%-power MDE 1.3489 — and its interval crosses zero.** The mission's verdict is
`NO_GO_SEVERE_TAIL_NOT_POWERED` and it is correct: **no loss-lever claim is authorised.** We know
the centre moves; we have not shown it moves the loss where the loss is concentrated. Do not cite
this finding as an expected Brier or P&L improvement.

Established sub-findings:

- **The base HGB itself is cool.** Recorded root cause was "a stale/cool June prior"; the measured
  root cause is **seasonal coverage**, above.
- **Evening is the same bias**, masked by the observed-high floor rather than absent.
- **09:00–14:00 is not specially cool.** The slice is the objective for other reasons (§0), not
  because the bias concentrates there.
- **Mechanism of centre displacement:** the too-cool HGB puts probability mass below the floor;
  truncation at the floor then yanks the centre warm. **Trace this, do not infer it.**
- **Never weaken the trusted observed-high floor** to relieve the symptom. The floor is load-bearing
  and is the only absorption result whose interval excludes zero.

---

## 3. The serving floor fix — the one shipped win

Shipped 2026-07-31. It is a **serving-path** change; the model itself did not change.

| Metric | Before | After |
| --- | --- | --- |
| Served ratio vs market | **1.6639158425** | **1.4979600580** |
| Delta | **−0.1659557845**, crossed CI **[−0.3552671491, −0.0697874559]** | |
| Support | D=8, M=11, 85 market-days, 11,661 snapshots | |

Only about **2.2%** of the improvement landed in the 09:00–14:00 window — the evening problem was
solved, the primary-objective window was not. Any gap map predating this fix is stale.

**These exact numbers are a positive control** for the model-vs-market skill tracker. A measurement
stack that cannot reproduce them is wrong, and the retained finding is not.

---

## 4. The model is feature-blind — ALL DAY, FLEET-WIDE, not only at 09:00–14:00

> **CORRECTED 2026-08-06 on direct production measurement.** The "09:00–14:00" framing below was an
> artifact of where we happened to look. It is not a blind *window*; **the model is blind at every
> hour, in every market, always.** The corrected measurement is the first table; the original
> section follows unchanged because its root cause and effect analysis still stand.

**10 of 19 base features are 100% empty at every cutoff hour 07:00–20:00, in all 11 markets
measured (~5,761 rows, Aug 3–5).** Not "mostly empty" — exactly zero populated values.

| Measurement | Result |
| --- | --- |
| Toronto, 5 days, all hours 07–20 (919 rows) | 10 features at **0%**, every hour |
| Fleet, 11 markets, Aug 3–5 (5,761 rows) | the same 10 at **0.0%**; the other 9 at 93.6–100% |

> **Scope caveat, added 2026-08-06 — the survivor range is NOT a usable positive control.**
> This row says "11 markets" and never enumerates which 11 of the 12, and its row count is
> approximate. `-09-28a` re-measured on this host and got **5,731 rows and 91.36–100%** for the
> nine survivors after a strict Austin-row exclusion. **The finding itself reproduces exactly**
> — the same 10 features at 0.0%, and 8 of them dead in all 14 Toronto hour models at 29 trained
> features each. Only the *survivor range* differs, and it differs because the original scope was
> never pinned. Treat the **dead set as the control** and the 93.6–100% range as incidental
> colour. Do not conclude a measurement stack is wrong because it misses that range.
| Serving artifact `feature_model_hgb.pkl` | **8 of 29 trained features are dead at serve in all 14 hour models** |

The dead set is the entire local-meteorology block: `rise_from_7am`, `warming_rate_2h`,
`hours_at_peak`, `dewpoint_c`, `humidity`, `pressure`, `pressure_trend_3h`, `wind_speed_kmh`,
`wind_gust_kmh`, `wind_shift_3h_degrees`.

What survives is `high_so_far`, `current_temp`, `onshore_flow`, `onshore_wind_speed_kmh`,
`lake_breeze_proxy`, `forecast_high`, `forecast_gap`, `forecast_source_count`,
`forecast_disagreement` — current state, lake-breeze geometry, and forecast consensus. **The model
has no direct observation of moisture, pressure, wind, or temperature trajectory.**

**So ~28% of every prediction's trained inputs are imputed medians, always.** This is the single
largest known defect in the model and it subsumes the train/serve parity finding, which detected
2 of the 10. It also explains §1 directly: if the gap is informational rather than calibration, this
is where the information went.

**Consequence for every prior result:** the cool bias, the market gap, the severity tail and the
centre-displacement work were all measured on a model missing 10 of 19 base inputs at all times.
None of them is invalidated, but none was measuring a model that could see.

### REPAIRED 2026-08-08 (`-09-43a`) — 9 of the 10 are routed, but two stay dead in the F markets

**Reproduced on the production host, not taken on report.** Parity **196 → 100 blockers, 0
unexpected** — 96 closed is exactly 8 features × 12 markets. The known-defects fixture is
byte-unchanged and no gate was weakened. `-09-39a` had already routed `wind_gust_kmh` and
`wind_shift_3h_degrees`; this routes the other eight from our own captured station rows,
cutoff-aligned, WU first, strict fallbacks, no synthesis.

**The contract now routes 9 of the 10. What actually populates is less, and the difference is the
finding:**

| Feature | Fleet populated (replay corpus) | Going forward |
| --- | ---: | --- |
| `dewpoint_c` | 99.16% | all 12 |
| `wind_speed_kmh` | 99.13% | all 12 |
| `hours_at_peak` | 94.92% | all 12 |
| `warming_rate_2h` | 83.48% | all 12 |
| `rise_from_7am` | 75.86% | all 12 |
| `humidity` | **8.70%** — Toronto only | **all 12** — old AviationWeather envelopes never retained `rh`; METAR v3 does |
| `pressure` | **0.00%** | **Toronto only** |
| `pressure_trend_3h` | **0.00%** | **Toronto only** |
| `wind_group` | — | **dead in all 12; untouched** |

**`pressure` is not a bug and must not be "fixed".** METAR publishes altimeter and sea-level
pressure; the trained WU `pressure` feature is **station** pressure, which differs materially at
altitude — Denver's artifact median is 24.4 inHg. Aliasing either into `pressure` would pass a
presence check and be false in substance. The mission refused the alias and kept the field missing.
That is the correct call and it is the §5 "unknowable at serve" case: **the owed follow-up is to
drop `pressure` and `pressure_trend_3h` from training for the 11 F markets**, not to invent them.

**So the imputation load falls from 8 of 29 trained inputs to 2 of 29 in the F markets and 0 of 29
in Toronto — going forward.** The retained replay corpus can never show this: it holds no `rh` and
no station pressure, and enriching it would be synthesis. **The full repair is therefore
unmeasurable until v3 parsers have been capturing for a while.**

**It changes what we serve.** 821 of 840 admitted distributions move, mean L1 0.223, max L1 1.315,
positive controls 840/840 exact. Brier **−0.00816 [−0.02972, +0.00961], power 0.131**; centre
**+0.0335 [−0.0094, +0.0803]**, power 0.316; width **+0.0176**, power 0.335. Every interval crosses
zero. **Favourable direction, not powered — cite this as a defect repair, never as a scoring gain.**
The warm centre shift is only ~5% of the −0.6641 C-eq cool bias, so it does not touch §2.

### AND IT DID NOT MOVE THE GAP — measured 2026-08-09 (`-09-44a`), and this one IS precise

`-09-43a` was measured on 5 date clusters at power 0.131 and could conclude nothing. `-09-44a`
re-ran it on the sealed replay corpus — **D=50, M=12, 524 promotion-countable market-days, 12,289
snapshots, 135,179 band rows** — paired on identical rows and cutoffs.

| Stratum | Pre-repair | Repaired | Paired delta [crossed 95%] | 80%-power MDE |
| --- | ---: | ---: | ---: | ---: |
| **In-season ratio** | 1.423260x | **1.423246x** | **−0.0000140 [−0.0022674, +0.0024795]** | 0.003055 |
| In-season Brier | 0.053380315 | 0.053379789 | −0.000000526 [−0.00008317, +0.00009121] | 0.0001113 |
| Out-of-season ratio | 1.526099x | 1.542244x | +0.016145 [−0.009580, +0.043096] | 0.03773 |

**7,112 of 12,289 served distributions changed and the gap did not move.**

**Read the power figure correctly — this is the first PRECISE null in the project, not another
underpowered one.** The reported power `0.050` is plug-in power *at the observed effect*, and the
observed effect is ~0, so 0.050 is the α floor and is tautological. **The informative statistic is
the interval**, and pairing on identical rows collapsed it: the gap sits 0.4233 above parity, and
the delta interval is ±0.0025, so **the repair moved the gap by at most ~0.6% of the distance to
parity, in either direction.** Every previous "not powered" verdict in this project was a *wide*
interval that licensed nothing. This one is a tight interval around zero, and it licenses a
conclusion. The out-of-season point is unfavourable but its interval crosses zero — **not evidence
of serving harm, and not a reason to revisit the merge.**

**What this establishes:** restoring ~28% of the model's trained inputs — the single largest known
defect — bought **no measurable accuracy**. Input completeness was a **correctness** problem, not a
**skill** problem. **Stop sequencing the programme as though finishing the input population will
close the gap.** It will not. The remaining input work (`wind_group`, F-market pressure, `humidity`
going forward) is still owed as correctness, but must not be costed as a gap-closing measure.

**One caveat on the control.** The literal captured `snapshots_long.csv:model_probability` lane
could **not** serve as the positive control here: 267 of 12,289 partitions are partial and fail
probability mass, and dropping them would have changed the sealed population. The control used is
the predecessor's mass-valid replay-final incumbent distribution, re-run rather than read, PASS,
population rebound exactly. That is the right control for a *paired* delta — same machinery, one
code overlay — but it does not independently re-prove that the pre-repair replay reproduces
production output. `-09-43a`'s 840/840 exact-vs-recorded control does that, on the smaller panel.

**The parity gate stays BLOCK and cannot reach exit 0 until the fixture is narrowed.**
`nine_empty_base_features_09_to_14` still requires 9 fields to be found dead and only `wind_group`
still is. Narrowing it **records** the repair; that is not weakening it. Owed, and it needs an owner.

**This invalidates the baseline, not the findings.** Everything in §1, §2, §4d and the
centre-displacement work was measured on the blind model. Re-measure before re-citing.

### The mechanism — traced 2026-08-06, it is a ROUTING defect, not a data gap

The data is captured, parsed into the right field names, and then discarded. Four links:

1. **`extract_live_features` reads the dead sources only.** `model_features.py:753-754` binds
   `history = source_data(sources, "wu_history")` and `current = source_data(sources, "wu_current")`.
   WU live collection is disabled, so `rows` is empty and `feature_latest` is `None`. Every dead
   feature resolves through `feature_latest` / `current` / `rows` and therefore to `None`.
2. **Only the observed-high path consumes the station fallback.** `effective_observed_high_context(...)`
   takes `station` as an argument — which is exactly why `current_temp` and `high_so_far` are the two
   survivors. Nothing else in the function receives it.
3. **The station fallback deliberately returns almost nothing.** `model_sources.py:315-326`,
   `derive_station_observation_data`, builds a 10-key dict whose only measurements are `temp_native`
   and `max_since_7am_native`. It holds the full observation in `latest` and reads two values off it.
4. **The adapter already parses everything, into WU-compatible names.**
   `eccc_swob_history.py:340-375` emits `dewpoint_c`, `humidity`, `pressure`, `wind_speed_kmh`,
   `wind_gust_kmh`, `wind_dir_deg`, `clouds` — the same names the extractor asks for.

Verified on a real captured payload (Toronto, 2026-08-05, parsed by the repo's own
`parse_swob_xml`): `dewpoint_c=17.2`, `humidity=81.0`, `pressure=997.8`, `wind_speed_kmh=6.5`,
`wind_dir_deg=129.0`. Payloads accumulate up to **20 hourly rows**, so the trend features
(`pressure_trend_3h`, `wind_shift_3h_degrees`, `rise_from_7am`, `warming_rate_2h`, `hours_at_peak`)
have the history they need as well.

### Training was NOT blind — this is pure train/serve skew

The serving artifact's `SimpleImputer` carries a **finite, physically sensible median for every dead
feature**: `dewpoint_c` 13.0 °C, `humidity` 57%, `pressure` 994.25 hPa, `wind_speed_kmh` 15.0,
`rise_from_7am` 6.0 (pooled/Toronto model). Had training never observed them, sklearn would have
dropped them as all-NaN. **The model learned real relationships from these features and is now fed
the same constant for every prediction, in every market, at every hour.**

Per-market artifacts carry market-appropriate medians in **native units** — Denver `pressure` 24.4
inHg (correct for altitude), Miami `dewpoint_c` 73 °F, Houston 71 °F — while the pooled Toronto model
is hPa/Celsius. **Any repair must convert per market to the units each artifact was trained on.**

This materially lowers the risk that repair is a distribution shift into unseen territory: populating
these features restores learned behaviour rather than introducing novel behaviour.

### DIRECTIONAL probe, 2026-08-06 — half the repair is worth about −3.4% Brier

Toronto only, so by §5 this is **directional and can never be a confirmation**. PIT-safe: each row
used only the SWOB observation captured at or before its own capture time and valid at or before its
cutoff. Only the **4 directly-readable** dead features were populated (`dewpoint_c`, `humidity`,
`pressure`, `wind_speed_kmh`); the four trajectory/trend features were left imputed, so this is a
**lower bound on half the block**.

| Measure | Value |
| --- | --- |
| Rows scored / dead cells filled | 755 / 3,020 (4.00 per row) |
| Mean Brier, served (imputed) | 1.05384 |
| Mean Brier, populated | 1.01791 |
| Delta | **−0.03592 (−3.41%)** |
| Rows improved | 435 of 755 (57.6%) |
| **Dates improved** | **3 of 4** — Aug 3 reversed at +0.01455 |

**D=4. One date reversed. Toronto-only.** A crossed interval at D=4 would certainly cross zero, so
this is a prior to test, not a result to bank. It is exactly what `-09-26a` exists to measure
properly: fleet-wide, all 10 features, crossed date × market clustering.

**So the repair is routing, not collection or parsing.** Known real complications, none fatal:
SWOB is Celsius and US markets need native Fahrenheit; SWOB cadence is hourly where training rows
were denser, so trajectory features are *not* observationally identical to their trained semantics;
`wind_gust_kmh` is legitimately absent in calm conditions and must stay missing; and any station row
used must respect the cutoff and emission-time rules. One genuine name mismatch: the extractor reads
`wind_kmh` while the adapter emits `wind_speed_kmh`.

---

**Original section, retained — its root cause and effect analysis stand:**

**9 of 19 base features are empty at inference** in the floor-excluded lane, despite the inputs being
fully captured. This is a **feature-contract defect, not an information gap** — the data exists.

| Property | Value |
| --- | --- |
| Training reconstruction populated | 97.04–100% by feature and hour |
| Captured inference populated | **0%** for 8 numeric fields + wind group |
| Category | **(a) train/serve skew** for every affected feature; category (b) rejected |
| Routing | Nulls take `SimpleImputer` medians and all-zero dummies — **not** HGB missing-value branches |

**Root cause, exactly:** commit `5735b573` disabled WU history/current on 2026-06-30, severing the
training-time surface contract. Commit `2a878d91` added a free METAR/ECCC station fallback on
2026-07-02, but **only temperature and current max ever reached the feature extractor.** Free-source
parity for trajectory, dew point, humidity, pressure, wind and cloud **was never implemented.**

**What repairing it is and is not worth:**

| Effect | Value | Verdict |
| --- | --- | --- |
| Pooled daily-first Brier cost | `+0.009899`, interval `[-0.022842, +0.041688]` | **Crosses zero.** Does not justify a fleet-wide retrain |
| Severe-tail squared error | 737.065190 → 642.944476 = **12.77%**, interval **8.60–17.53%** | **Real.** This is the justification |
| Severe tail, excluded lane | 434.348864 → 368.198847 = **15.23%**, interval **9.43–21.54%** | Real |
| Effect on centre displacement | Moves the excluded lane **warmer** by `+0.005453` bands | **Blindness is NOT the centre mechanism** |

Heterogeneous: cost is positive at 09:00–11:00, negative at 12:00–13:00, near zero at 14:00, and
negative in 5 of 12 markets including NYC and Toronto. **A repair must be evaluated on the severe
tail, not pooled**, and should ship dark until release #1 is locked.

---

## 4a-bis. THE ARCHIVE IS NECESSARY BUT NOT SUFFICIENT — `-09-50a`, 2026-08-09

**The retrain never reaches preflight, and the reason has nothing to do with the archive.**
`base_retrain.load_parent_contract()` requires a **verified ACTIVE parent release**, and this host
has **no release store at all**. Verified on production, not taken on report:

- `artifacts/releases/current_release.json` — **absent**; `artifacts/releases/` **does not exist**.
- `base_retrain.py` has **zero** bootstrap / `allow_missing` / `no_parent` / `first_release`
  escape paths. The requirement is unconditional.
- `load_parent_contract` further demands the parent's semantic contract be
  `RESEARCH_ONLY_CANDIDATE_MODE`.

**This corrects a framing this file and `STATE_OF_PLAY` carried all day.** The archive extension was
described as "THE critical path — nothing else competes." It is **necessary and not sufficient**:
extending it does not let the retrain run, and this blocker needs a **decision**, not a fetch.

### The break exists, is documented, and has never been run

`NIGHTLY_RETRAIN_RUNBOOK.md` §"First inactive production release" defines one fail-closed bootstrap,
`nightly_retrain run --release-candidate-mode production --bootstrap-first-inactive-release`, whose
precondition is **exactly our current state**: *"`current_release.json` is absent and the releases
root is absent or completely empty."*

**Two things are unresolved and must not be guessed:**

1. The bootstrap **deliberately leaves the active pointer absent** — it "checks again at whole-run
   finalization that the active pointer is still absent." So it alone does **not** satisfy
   `load_parent_contract`; an activation step is still required, and activation is the thing
   `release-one-deferred-until-a-retrained-candidate.md` deferred.
2. The bootstrap runs with `--release-candidate-mode production`, while `load_parent_contract`
   rejects a parent that is not `RESEARCH_ONLY_CANDIDATE_MODE`. **These may conflict.** Do not
   assume they resolve; map it.

> **The sequencing in canon was inverted.** Release #1 was treated as *downstream* of the first
> retrain, and the retrain requires a release-shaped parent *first*. **This is why the retrain has
> never run, and no amount of archive work would have revealed it.**

### RESOLVED 2026-08-09 by `-09-51a`: it is a CODE contradiction, not a decision

**There is no supported path on current master from an empty release store to the first base
retrain.** Three mutually reinforcing reasons, of which I verified 1 and 3 directly:

1. The nightly bootstrap builds a **production-capable** release, but `load_parent_contract`
   **raises** unless the parent is `RESEARCH_ONLY_CANDIDATE_MODE`.
2. The **research-only** bootstrap requires complete corpus lineage **or** an existing verified
   release. Production has neither.
3. **The nightly plan runs `base_retrain` BEFORE candidate release construction** —
   `all_market_base_retrain` is appended as a plan step at `nightly_retrain.py:1327`, while
   `run_candidate_release_step` is only reached at `:2588`. **The circularity is in the code.**

> **AND THE DEFERRAL IS NOT THE OBSTACLE.** Creating the research parent would freeze **research
> scaffolding only** — it does **not** commit the deferred production Release #1 and does **not**
> start its confirmation window. So `release-one-deferred-until-a-retrained-candidate.md` **stands
> and is simply not in the way.** Nobody needs to relitigate it.

A scratch-root rehearsal proved the **downstream** research-parent mechanism works once a parent
exists. **So the gap is confined to CREATING one**, and the fix is engineering with a known target,
not a judgement call.

### The held branch is NOT the fix — audited and closed out, 2026-08-09 (`-09-52a`)

`codex/workstation-research-2026-07-22` rewrites the same files, so it was audited before any fresh
code was commissioned. **It closes none of the three causes**, and it cannot: **it does not contain
`base_retrain.py` at all** (verified — `git cat-file` fails on that path), so it predates the very
contract it would need to satisfy. Its bootstrap stays production-only and it has no empty-store
research-lineage source.

**Landing it is a NO-GO on its own terms:** 191 files, **72,114 insertions**, 1,365 deletions
(verified), **32 live merge conflicts**, it modifies the **live serving loader** and promotion
contracts, and it is **ROLL-SENSITIVE across six files in all three capture closures**.

> **A correction worth keeping.** I wrote that this branch's hold was "a temporary measure whose
> justification expired," by analogy with the Windows auto-update block. **Half right, and the wrong
> half mattered.** The *calendar* justification did expire; the *substantive* migration and serving
> risks never did. **Checking one stated reason and concluding about the whole is its own error** —
> ask what else a hold might be protecting before calling it stale.

**Do not re-audit this branch for the bootstrap gap.** The required fix is a **small current-master
path that creates a verified research-only parent with first-party corpus lineage before
`base_retrain` runs.**

**Start from `all_shadow_release_bootstrap.py`**, which already does most of it — its docstring is
*"Build one immutable research-only all-shadow release without a pointer"*, and it already emits
`RESEARCH_ONLY_CANDIDATE_MODE`. **The single blocking gap is that
`_verified_release_research_lineage()` sources lineage from a prior verified release's
`training_evaluation_corpus` role** — which an empty store cannot provide. That is cause 2, localized
to one function.

### BROKEN 2026-08-09 by `-09-53a` — `base_retrain` reached preflight for the first time ever

**The circularity is closed.** First-party lineage assembled and bound all **12,600 / 12,600** cells;
a scratch parent verified as `research_only` with **12 shadow markets and 84 base roles and no
pointer**; and **`base_retrain` accepted that parent and proceeded past `load_parent_contract`.**
Production's release store and pointer remain **absent** — the one-shot is untouched.

**The contract was generalized, not relaxed** — checked line by line on this host, because the diff
showed 25 deletions in a contract module:

- the `verified_immutable_release` branch is preserved **verbatim**;
- `verification_status != "PASS"` still raises **first**, for every kind;
- the new `first_party_corpus_assembly` branch is **stricter than the branch beside it** — it
  recomputes `assembly_contract_sha256` and `model_input_fields_sha256` from content and cross-checks
  `assembled_corpus_sha256` / `assembled_row_count` against `final_refit` *and* against the assembly
  contract's own `record_count` and `market_ids` length;
- an unrecognised `kind` falls through to `raise CandidateContractError(...)`. **Fail-closed.**

**THE FRONTIER HAS MOVED, not vanished.** Preflight now blocks on the **missing official base and
PIT forecast corpus manifests** — the same defect `-09-50a` saw from the other side ("the only
retained research corpus manifest has the wrong schema and target, and is rejected outright by the
immutable PIT-corpus verifier"). `base_retrain` takes them as
`--base-retrain-corpus-manifest` / `--base-retrain-pit-forecast-corpus-manifest`. **That is now the
binding blocker on objective #2.**

## 4b. The forecast archive covers the wrong 52 days — this blocks the retrain

Measured 2026-08-06. Canonical:
[the-season-window-blocks-the-retrain.md](the-season-window-blocks-the-retrain.md).

`SEASON_START=(5,10)` / `SEASON_END=(6,30)` in `forecast_history.py`. The archive holds **52
month-days per year, May 10 – Jun 30, in every year**. The first retrain targets 2026-07-31
±7 days — **Jul 24 to Aug 7 — for which the archive has ZERO rows in any year.** That is why
`-09-20a` blocks at **0 / 12,600 cells, 0 of 60 market/year staging units**.

The constant was correct when written ("for late-May and June target dates") and **expired
silently on 2026-06-30**. `fleet-coverage` still reports **`OK markets: 12/12`**, because it
checks rows and field completeness and **never asks whether the covered dates match the
target**. Third instance of the §8 shape: *the standard came from the thing being judged.*

**Every served HGB was fitted 2026-06-10 to 06-13** on that archive, and is served in August.
Release #1 **freezes** them. The unblock is ~**60 free-tier calls** — verified available:
a `2023-07-24 → 2023-08-07` historical-forecast request returns 200 with 360 populated rows.

**Also corrects §4's repair value.** `-09-26a` measured full free-source parity fleet-wide,
crossed: all-severe SSE **6.7395%** [0.5208%, 14.3964%], pooled Brier **−0.000721**
[−0.032916, +0.030983] — **crosses zero, point is a mild degradation** — with the fields
present in only **8.90%** of fleet snapshots. Verdict **NO-GO for activation or fleet
retrain**. §4's `12.77%` is the *theoretical* repair; `6.7395%` is what free sources deliver,
and the `−3.41%` Toronto probe did not survive fleet measurement.

---

## 4c. No target-year row is ever in-sample

Verified 2026-08-06 at `model_climatology.py:121` and `:234`:

```python
if local_date.year >= self.target_date.year:
    continue
```

The trainer skips every row from the target year unless an explicit coverage date is supplied,
and `feature_model.py` calls `historical_target_cache()` without one. **For a 2026-target
artifact, no 2026 date can be an exact fit row.** All twelve frozen artifacts show zero overlap
with the 2026 label inventory — 0 of 216 checked market-days (`-09-30a`).

Two consequences:

- **Every evaluation we have run on 2026 data is honestly out-of-sample.** Being inside the
  May 10 – Jun 30 archive window does *not* make a 2026 observation in-sample.
- **A seasonal-distance test needs no in-sample control stratum**, because no such stratum can
  exist. Compare in-season against out-of-season target dates, both out-of-sample.

---

## 4d. The severe tail IS ex-ante identifiable — at band granularity, not day granularity

`-09-32a`, 2026-08-06. Corpus **108 market-days, 19,265 snapshots, 211,915 band rows**
(`promotion_countable`; see the ledger-row inflation trap in `RETRACTED_AND_FALSE_LEADS.md`).

A **≥30-point model/market band probability gap** captures **100% of severe-tail loss** at
**1.714%** non-severe *band-row* collateral — but it touches **40.156% of snapshots and all 108
market-days.**

| Lever | Verdict |
| --- | --- |
| **Targeted band suppression** | **Viable** — surgical at 1.714% band collateral |
| **Whole-book or whole-day stand-down** | **Not viable** — fires on 40% of snapshots and every single day |

**Two reasons no operating point may be chosen yet, and neither is a formality:**

1. **The signal is definition-adjacent.** The severe label itself requires a market-right error,
   so a market-disagreement signal predicting it is partly definitional. The magnitude of
   disagreement is not part of the label, so it is not circular — but it is not clean either.
2. **Opportunity cost is unmeasured.** The flagged set is exactly where our claimed edge is
   largest. Suppressing it caps the downside *and* forfeits whatever upside lives there.
   `-09-32a` explicitly declined to choose, correctly.

**Do not tune this before the retrain.** The current model is **−1.0193 C-eq** cool
out-of-season (§2), so today's model/market disagreement is substantially *the cool bias itself*.
An operating point fitted now would be tuned to a defect we are removing, and would have to be
refitted afterwards. Re-measure after the first retrain, then price the opportunity cost.

---

## 4e. The gap does NOT vanish in-season — the retrain is necessary, not sufficient

`-09-34a`, 2026-08-06, same corpus and strata as `-09-31a`.

| Lane / stratum | Model Brier | Market Brier | Ratio [crossed 95%] |
| --- | ---: | ---: | --- |
| Base, in-season | 0.065509 | 0.037506 | **1.7466 [1.5149, 2.0377]** |
| Base, out-of-season | 0.073068 | 0.038977 | 1.8746 [1.5937, 2.2211] |
| **Served, in-season** | 0.053380 | 0.037506 | **1.4233 [1.2428, 1.6589]** |
| Served, out-of-season | 0.059484 | 0.038977 | 1.5261 [1.3529, 1.7564] |

**Every in-season interval excludes 1.0.** The model is very nearly unbiased in-season
(−0.1848 C-eq, §2) **and still loses to the market**, on a deficit the report attributes to
**resolution** — an information problem, not a centre problem.

**The seasonal contrast is NOT POWERED and no direction may be claimed:** base C−B
**+0.1280 [−0.2679, +0.5288]**, served **+0.1028 [−0.1695, +0.3596]**. Complete closure of the
retained gap needs **+0.24** ratio points against MDEs of **0.5384 / 0.3620** — this design could
not have detected a full closure, so "not powered" here is a property of the test, not evidence
of no effect.

**Caveat:** these ratios are on the seasonal-distance corpus and are **not** the retained
clean-regime **1.24x**. Do not equate them.

**What this changes.** Bias and sharpness are separate problems and we have a fix for one.
The retrain addresses a measured **−0.8346 C-eq** seasonal centre defect, so it remains worth doing
— but **do not restate the old "and centre is 74.97% of oracle excess loss" clause**, which §1
retired on 2026-08-09 with no replacement. The retrain's justification is now the measured seasonal
centre defect alone, which is a smaller argument than the programme has been assuming.
**Stop sequencing the programme as though the retrain is the whole answer.** A parallel line of work on resolution is required, and §1 already
says recalibration cannot supply it.

---

## 4f. The free tier has the DATA but cannot express a point-in-time CORPUS

Measured on the production host 2026-08-07, correcting two specifics in the `-09-38a` report.

**The archive collection succeeded**: `-09-38a` P0 collected **1,740 / 1,740** target-derived
market-dates across 12/12 markets. The window question (§4b) is closed.

**The PIT corpus did not**, and the reason is the request *shape*, not coverage:

| Probe (Toronto, `gfs_seamless`) | Result |
| --- | --- |
| `temperature_2m`, `cloud_cover`, `wind_speed_10m`, `shortwave_radiation`, `cape` — **every year 2021–2025** | **72/72 non-null each** |
| `temperature_850hPa`, `geopotential_height_500hPa` | **72/72 non-null** |
| `temperature_2m_previous_day1` | **72/72 non-null** |
| `cloud_cover_previous_day1` | **0/72 — all null** |
| `cloud_cover` with `previous_runs=1` | 72/72, but **identical to the plain query, 24/24** |

**`-09-38a`'s measurements were correct; an earlier draft of this section wrongly "corrected"
them.** That draft reported `temperature_850hPa` and `geopotential_height_500hPa` as served — true
of the **plain** request, but the corpus needs the **PIT** request, and with the `_previous_day1`
suffix they return HTTP 400 exactly as the mission said. **Comparing two different request shapes
is not a correction.** What survives is narrower: the *plain* fields are complete in all five
years, so **narrowing the year set cannot help** — the years were never the constraint.

**The decisive measurement — how much of the plan is PIT-expressible at all:**

All 21 required fields probed with the `_previous_day1` suffix, Toronto 2021:

| Disposition | Count | Fields |
| --- | ---: | --- |
| **Non-null** | **1** | `temperature_2m` (24/24) |
| All-null (HTTP 200) | 17 | `cloud_cover*`, `shortwave_radiation`, `wind_speed_10m`, `cape`, `direct_/diffuse_radiation`, `wind_gusts_10m`, `visibility`, `precipitation*`, `soil_*`, `vapour_pressure_deficit`, `et0_fao_evapotranspiration` |
| HTTP 400 with the suffix | 3 | `temperature_925hPa`, `temperature_850hPa`, `geopotential_height_500hPa` |

**1 of 21.** A point-in-time corpus on the free tier can carry `temperature_2m` and nothing else.

**CONFIRMED AT BREADTH 2026-08-07 (`-09-41a`)** — the number above came from a single-lead,
single-market probe, so it was a belief. Re-probed across **21 fields × 7 leads × 3 markets =
441 cells**:

| Result | Cells |
| --- | ---: |
| **Complete** | **21** — `temperature_2m`, all 7 leads, all 3 markets |
| HTTP 200, all null | 357 |
| HTTP 400 | 63 — `temperature_925hPa`, `temperature_850hPa`, `geopotential_height_500hPa` |

The two-host premise also held independently in each market, with all 48 paired non-null hours
differing between the settled and PIT series. **So the honest corpus is genuinely single-variable**
— which is why `-09-41a` built the **hybrid** (PIT `forecast_high` + settled for the rest) rather
than accepting a one-feature model.

**There are TWO hosts and only one of them is the PIT surface.** This caught both `-09-38a` and an
earlier draft of this section, so it is written out:

| Host | Purpose |
| --- | --- |
| `historical-forecast-api.open-meteo.com` | settled archive. **Ignores `previous_runs=`** — returns the settled series, unrenamed |
| `previous-runs-api.open-meteo.com` | **the PIT surface**, via `<field>_previous_day{1..7}` (`PREVIOUS_RUNS_URL` in `sources/forecast_history.py`) |

Probing `_previous_dayN` against the *archive* host is measuring the wrong thing. **An earlier
draft of this section called `previous_runs=` a leakage trap on that basis — that is RETRACTED.**
On the correct host, `temperature_2m_previous_day1` differs from the settled series in **23 of 24
hours**: it is genuinely an earlier run, and it is what the existing corpus was built from.

The **1-of-N result survives re-measurement on the correct host**: of 9 fields probed against
`previous-runs-api`, only `temperature_2m` returns data; `temperature_850hPa` is HTTP 400 and the
other seven are all-null. **So the PIT surface is temperature-only — but it is real.**

**And we already hold it.** `data/forecast_history/<station>/forecast_daily_by_issue.csv` carries
**2,135 rows with `issue_time_basis = fixed_lead_day_offset`** in each of the 12 stations. The
mechanism is proven on this project's own data. **Composition — corrected 2026-08-07 after
`-09-40a` caught an earlier draft here, then re-verified directly on production:**

| | Earlier draft (WRONG) | Verified on production |
| --- | --- | ---: |
| Rows/year, 2021–2025 | 416 | **364** (52 dates × 7 leads) |
| 2026 rows | *(not recorded)* | **315** |
| Lead days | 1–4 | **1–7** |

364 × 5 + 315 = 2,135. **The total was right and every part of the decomposition was wrong** — a
matching total is not confirmation of a population. Three further facts, from disk, no API call:

- Every fixed-lead row carries `source = open_meteo_previous_runs`. **The PIT host is already in
  use** — the two-host distinction above is corroborated from the data side.
- The file's only forecast variable is `forecast_high_native` / `forecast_high_c`. **The
  materialized honest corpus is already single-variable**, whatever the API could serve.
- Target range **2021-05-10 → 2026-06-23, months 05 and 06 only, zero July/August rows.** The
  honest corpus on disk is in the **stale** window §4b/`-09-31a` blamed for the cool bias, so
  **it cannot train the season we serve.** Collecting July 17 – Aug 14 is genuinely un-started.

**So the corpus question is narrower than "free tier cannot do PIT".** It is: *the PIT surface
carries temperature only.* The rich 21-field corpus is settled-analysis and contaminates the fit;
the temperature PIT corpus is honest and thin.

**The contamination is therefore a TRAINER defect, not a data gap.** §6 records the trainer reading
the 2-column stitched `forecast_daily.csv` while `forecast_daily_by_issue.csv` — the PIT file, on
disk, populated — **goes unread**. We are contaminated because of what the trainer opens, not
because the honest data is unavailable.

**Verified in source 2026-08-07, and it is worse than §6 stated:** `daily_by_issue_path()` in
`sources/forecast_history.py` has **zero readers anywhere in `src/`** — the PIT file is written and
never consumed by anything. `calibration/forecast_error_model.py:42` hardcodes
`DEFAULT_FORECAST_DAILY` to the stitched `forecast_daily.csv` for **`cyyz` alone**, on a 12-market
platform.

That reframes the work: **collect the temperature PIT rows for the new window** (proven mechanism,
same code path that produced the 2,135 existing rows) **and point the trainer at the PIT file**.
Do not commission "characterise the endpoint" again — it is characterised to the field level, on
both hosts. **`-09-41a` did both: 12,180/12,180 rows collected, and honest/rich/hybrid are now
selectable.**

### 4g. The retrain blocks on 14 cells, and the floor of 18 is not a knob

`-09-41a` reached **12,586 / 12,600** cells. The missing 14 are Denver **2025-07-28**, which has
**17** WU hourly rows against a floor of **18**.

**The gap is unfillable — verified on production 2026-08-07.** WU, METAR **and** NOAA GHCN-hourly
each return the *identical* 17 timestamps: hourly `00:58 → 14:58`, then `18:58`, then `23:58`.
Three independent archives agreeing exactly means KBKF (Buckley SFB) did not report those hours;
`backfill_errors.jsonl` has no entry, so the fetch succeeded. **Do not commission a re-fetch.**

**It is rare and it is one station.** Across all **1,740** market-days in July 17 – Aug 14,
2021–2025 × 12 markets, exactly **two** fail the floor — `kbkf 2022-07-20` (n=**1**) and
`kbkf 2025-07-28` (n=**17**).

**Excluding it is correct, not a workaround.** 2025-07-28's recorded max is **37.2 °C at 14:00, the
hottest value in Denver's month**, in a spell where 07-26 and 07-27 both peaked at 15:00 — and
**9 of 31 Denver July days peak inside the 15:00–17:00 window this day is missing.** The label is
very likely biased low, so a row-count floor understates how bad this day is.

**Never lower the 18.** `COMPLETE_DAY_MIN_ROWS` (`backtesting/settlement_io.py:32`,
`settlement_ledger.py:34`) is not a retrain threshold. `settlement_ledger.py:489` uses it to decide
whether **the WU daily summary is trusted as the label source at all** (below it, settlement falls
back to `snapshot wu_history_high`), and `settled_day_freshness.py:217` uses it for **day
completeness, which feeds the streak**. Lowering it to clear a retrain would change how days settle
fleet-wide and what counts as a complete day for objective #1. The fix is a **code-owned exclusion
list** naming those station-days, with the expected cell count derivable **without a candidate
loaded** — that test is what separates it from the §8 self-sizing defect.

---

## 5. Method rules — binding on every measurement

Each of these has already cost a retracted result. They are not stylistic preferences.

- **Crossed date x market clustering is mandatory.** Exchangeable market-day resampling produces
  intervals that are too narrow and has retracted headline results. An uncertainty-free point
  estimate is not acceptable output.
- **We have 34 date clusters, not 5.** The 5-date window was a convention, never a constraint.
- **The admission bar is `promotion_countable`, not `quality_grade == "complete"`.** The complete-only
  bar starved a previous corpus.
- **Settlement authority is `data/settlements/<market>/ledger.jsonl`, never `market_day_labels.csv`.**
- **Never pool across the `2026-07-31` regime boundary.** It is **artifact provenance, not
  target-date age.** The precise anchor is commit `b77cfbed` ("Floor rescued highs when WU is
  absent", 2026-07-30).
- **Report power, not just point estimates.** Most week-over-week deltas here are not distinguishable
  from zero. When a delta is not distinguishable, say so in those words and do not present the point
  estimate as a movement.
- **Known power requirements:** the primary-slice endpoint needs ~504 dates; the severe-tail endpoint
  needs ~4. A test whose N you have not checked is a test you cannot interpret.
- **Score any fitted mapping on its OWN training set before reading its test result** (`-09-56a`).
  Binary per-band PAVA worsened B from 0.053380 to 0.078717 — a fit that cannot improve the data it
  was fitted on has a **broken objective**, not a weak signal, and its test number means nothing.
  This check is free and it localises the fault immediately.
- **A control that consumes the benchmark is a measurement, not a candidate** (§1c). Shrinking
  toward the market closes the market gap by construction. It shows *where* information is missing;
  it is never evidence of edge and must not be booked as improvement.

---

## 6. Training data is contaminated at fit time

- **`forecast_high` is not point-in-time.** The trainer reads a 2-column stitched file; the
  point-in-time file exists and is **unread**. The **fit is contaminated; evaluation is not.**
  Measured lookahead is ~6% of the cool bias — real but not the main story.
- **THE CONTAMINATION IS NOT THE LEVER — measured 2026-08-08 (`-09-42a`).** The A/B/C fit priced
  it directly instead of arguing about it: **B − A = −0.000107** on the 09:00–14:00 primary
  (interval **[−0.001588, +0.001349]**, power **0.066**) and **+0.000370** all-hours (interval
  **[−0.000800, +0.001536]**, power 0.145). **The sign changes by slice and every interval
  includes zero.** The inherited ~6% price is *not reproduced* as a Brier cost. Fixing the trainer
  to read the PIT file remains correct hygiene; **do not expect it to close the market gap, and do
  not commission a mission that assumes it will.**
- **Honest and hybrid came out numerically identical.** A (PIT `forecast_high` only) and C (PIT
  `forecast_high` + the 20 settled fields) produced the same fit. **The 20 extra settled forecast
  fields contributed nothing** — which is what §4 predicts if the feature contract drops them.
  Worth a targeted check, because if true it means the archive's breadth is already worthless to
  this model and the blindness repair is the only thing that would change that.
- **Training population is 2021–2025**, decided 2026-08-05. Canonical:
  [forecast-source-and-training-population.md](forecast-source-and-training-population.md).
  This is confirmed by evidence, not only by argument: 2018–2020 contain **zero**
  `fixed_lead_day_offset` (point-in-time) rows in every market and exist only as
  `stitched_continuous_archive`.
- **Provider policy is closed:** free-tier Open-Meteo only. **No paid API, ever**, without a new
  dated operator decision. Better *free* sources may be adopted. **Agents must not stop on this
  question** — it is the exact block that halted two prior missions.

---

## 7. Two independent retrain lanes exist

Verified 2026-08-05. Neither branch contains the other's commits.

| Lane | Contains | Candidate-sized PIT gate defect |
| --- | --- | --- |
| `-09-12a` | base retrain, **`train_serve_feature_parity.py`** | **Present directly through `covered_years`** |
| `-09-01a` (named "consolidate merge queue") | base retrain, **1,536-line PIT training corpus**, PIT binding | **Present indirectly through candidate `selected_dates` and count fields; the literal `covered_years` occurrence is absent** |

**`-09-01a` is the better lane** and its corpus contract is the right design: training-only, never
reachable through `forecast_history.daily_path_for`, stitched rows fail closed, immutable and
content-addressed, no HTTP client by design. `-09-12a` uniquely carries the train/serve parity gate,
which must be salvaged whichever lane wins.

The 2026-08-06 rescue falsifier showed that the earlier literal-search conclusion was not a safety
property: `-09-01a` still reconstructed the required matrix from candidate-supplied dates and
counts. The rescue keeps that lane and fixes the gate by binding the code-owned 2021-2025
population, +/-7-day target window, 07:00-20:00 cutoffs and 12-market fleet into the self-hashed
retrain plan. See
[`agent-report-2026-08-06-workstation-rescue-the-pit-retrain-lane.md`](../roadmap/agent-report-2026-08-06-workstation-rescue-the-pit-retrain-lane.md).

**Lesson that generalizes: branch names in this repository lie.** Read the commits before judging or
disposing of a branch.

---

## 8. The self-sizing gate defect

The `-09-12a` `base_retrain.py` derives the required training matrix from the **candidate's own**
source manifest directly:

```python
years = [int(value) for value in source_payload.get("covered_years") or []]
```

A candidate can therefore shrink the gate that judges it, from **20,160 cells to 2,520**, by editing
one JSON field. Three matrices all currently qualify as "valid" for the same target.

The held `-09-01a` lane used a different form of the same defect: its required keys came from the
candidate corpus manifest's `selected_dates`, while candidate count/minimum fields helped validate
the result. Its existing synthetic PASS used only one date and one cutoff. Reducing candidate dates
could therefore reduce the expected gate even without the `covered_years` expression above.

**The fix is structural: the population policy binds into the hash-bound retrain plan; the source
manifest may prove coverage of the matrix but must never choose its size.** The 2026-08-06 rescue
adds the regression that reducing both `covered_years` and `selected_dates` cannot reduce the fixed
12,600-cell expectation.

---

## 8b. The MM countable-day clock is STOPPED — measured 2026-08-08

The MM gate cannot decide until enough maker days count toward the live-forward gate, so that
**yield**, not elapsed calendar time, sets the date the gate can rule. Nothing reported it, so it
was being argued from memory. `python -m weather.reporting.market.mm_countability_postmortem`
now reports it from the `preflight_remediation.json` every maker run already writes.

| Measure | Value |
| --- | ---: |
| Maker days on disk | **55** (`2026-06-15` → `2026-08-08`) |
| Days that counted | **7** |
| Yield | **12.7%** |
| **Last counted day** | **`2026-07-12`** — 27 days before measurement |

> **AND THE CLOCK COUNTS THE WRONG THING — `-09-48a`, 2026-08-11.** The live-forward countability
> gate **does not require a quote.** It certifies that each selected market's paper-evidence
> preflight passed and that run-level useful work was live; `quote_permission_present_in_countable
> _paper` is a *separate* readiness gate. Of the seven counted dates, six carry `QUOTE_HARVEST_MID`
> intents (300 / 4,019 / 5 / 1 / 15 / 39 rows) and the last, **`2026-07-12`, had 1,848 rows and
> ZERO quote permissions.** With `fills.jsonl` never written, **this is a data-plane qualification
> clock, not evidence that market making ever ran.** Raising the yield does not, by itself, move the
> MM decision one day closer. **Never again cite countable days as evidence a strategy traded.**

Six of the seven counted days fall in `2026-06-17` → `2026-06-27`. **The clock is not slow, it is
stopped**, and at this yield the 22–43 countable-day bar is never reached. **Do not plan MM against
elapsed days.** An earlier `STATE_OF_PLAY` line claiming "first countable day in 42 scored 08-08,
standing 4 of 55" was wrong — 08-08 has 0 counted runs.

| Gate / root cause | Days | Occurrences | First → last seen |
| --- | ---: | ---: | --- |
| `model_freshness` / `stale_model_row` | **52** | 758 | 06-15 → 08-07 |
| `clob_freshness` / `stale_clob_book_tape` | **52** | 643 | 06-15 → 08-07 |
| `clob_book_useful_write` / `stale_or_missing_clob_book_rows` | 36 | 39 | 06-20 → 08-07 |
| `no_remediation_file_written` | 27 | 39 | 06-15 → 08-08 |
| `snapshot_model_useful_write` / `stale_or_missing_snapshot_model_rows` | 26 | 28 | 06-20 → 08-07 |

**Both leading blockers are input freshness at maker runtime** — the model row and the CLOB book
tape are stale *when the maker runs*. Neither is model quality, promotion, or live-trade permission.
On the 08-07 sample the model row was ~19 minutes old at run time. This is the same class as the
"maker ran 90 min after the model went stale" scheduling defect, which was believed fixed and is
still the **#1** blocker through 08-07.

**Read `first_seen`/`last_seen`, not just the count** — an old `last_seen` is a fixed problem and a
recent `first_seen` is a regression with a date. `order_lifecycle.jsonl` independently corroborates
the date: last written `2026-06-27`, zero on all 42 days since, and `fills.jsonl` has **never** been
written on any of the 55 days.

**Re-run the post-mortem after any freshness fix — it is the yield meter, and yield is the MM
schedule.**

---

## 8bb. THE MAKER CANNOT QUOTE MARKET-CENTRED AT ALL — `-09-48a`, 2026-08-11

**Verdict NO-GO in the current configuration.** Across the post-boundary corpus — **554,004
quote-intent rows, D=8 dates, M=12 markets, 96 cells, nothing pooled across `2026-07-31`** —
**every row is `NO_QUOTE`. There are zero `QUOTE` rows.**

### The production agent's hypothesis was WRONG, and the truth is worse

I guessed the known-edge map was *incomplete* — missing records forcing `no_quote`, making a loaded
map stricter than an absent one. **The map matched 100% of rows.** All **293,964**
`KNOWN_EDGE_PERMISSION` rows had a **present** record whose permission was `no_quote` and whose
reason was **`promotion_block`**; **zero** came from `missing_known_edge_record`.

**Counterfactual replay on the real 2026-08-06 run settles it:**

| Intervention | Result |
| --- | --- |
| Lift the map restriction only | all **26,928** policy-eligible rows → `NO_QUOTE_BLOCKED_PROMOTION`, **zero quotes** |
| Grant promotion **and** `harvest_only` | harvest branch reachable on **2,386 / 26,928** rows |
| …then remove the model fair value | **zero quotes** — 19,811 `NO_QUOTE_MISSING_FAIR`, 7,117 at the information-event gate |

> **The harvest path itself requires model fair value.** So the one strategy `-09-46a` left open —
> market-centred harvesting, which needs *no model edge* — **is not implementable in the current
> code.** This is the binding fact about the MM track.

### It is deliberate architecture, not a defect

Precedence is: **preflight dominates failed inputs → a loaded `no_quote` record dominates policy →
promotion `BLOCK` dominates `harvest_only` → and the surviving harvest branch still requires model
probability, model age, and model-market disagreement.** The gate is internally consistent. **Do not
call it a bug, and do not "fix" it by deleting the map, editing a record, or relabelling
promotion** — the report shows each of those in isolation still yields zero quotes.

### Do not over-read the reason mix

`KNOWN_EDGE_PERMISSION` is 53.06% of rows, crossed 95% **[32.90%, 72.84%]**; `STALE_INPUT` 30.10%
**[14.79%, 48.82%]**. **The mix is not stable** — known-edge's daily share spans **8.34% to
76.87%**, and the first-half/second-half delta of +11.73 points carries **[−19.56, +44.81]** with
power 0.104 and an 80%-power MDE of 48.36 points. **Indistinguishable from zero.** An earlier
`STATE_OF_PLAY` line of mine reading "known-edge outranks stale ~3:1, so freshness may not be the
blocker" was directionally right but **stated far more firmly than eight dates support** — and the
reason label was never the binding constraint anyway.

## 8c. The MM decision now depends on a capture change, and that is a CLOCK

**Established 2026-08-10 by `-09-47a`.** The route to deciding whether market-making is a business
or a donation is now fully mapped, and every branch but one is closed:

| Route to `f` | Status |
| --- | --- |
| Model edge makes quoting profitable regardless | **RETIRED** (`-09-46a`: 114 cells, zero positive) |
| Measure `f` from the retained tape | **IMPOSSIBLE** — 411 executions, and no cancellation labels |
| Reconstruct executions from `price_change` / `book` deltas | **NO-GO** (§1b.3) — unidentified |
| **Capture the execution tape going forward** | **the only remaining route** |

**So the deciding evidence does not exist yet and can only be accumulated.** Every day without
execution capture is a day added to the eventual decision date — this is a stopped clock that has
not started, the same shape as §8b and the streak clock. **Do not plan the MM track against elapsed
calendar days; plan it against captured execution-days.**

### What must be captured (documented from venue docs; NO endpoint was called)

1. **Primary — continuous public market stream.** `wss://ws-subscriptions-clob.polymarket.com/ws/market`,
   subscribe `{"assets_ids": [...], "type": "market"}`, `PING` every 10 s. Retain **only** the
   explicit `last_trade_price` event: condition ID, asset ID, price, executed size, taker side, fee
   rate, **vendor exchange timestamp with declared units**, local receive time, **transaction hash**,
   raw payload hash — plus session ID, reconnects, and **an explicit gap ledger**, with one canonical
   fingerprint so raw and normalized rows cannot double-count.
2. **Reconciliation/backfill — public Data API.**
   `GET https://data-api.polymarket.com/trades?market=<condition_id>&start=&end=&limit=&offset=&takerOnly=true`.
   Page inside bounded windows; `offset` caps at 10,000. Its timestamp is integer-valued, so it
   **cannot** prove sub-second ordering — use it to reconcile, never to replace the live stream.
3. **NOT sufficient: the authenticated user stream.** It carries rich trade lifecycle records but
   **only for our own account**, so it cannot estimate a market-wide informed-flow denominator, and
   it produces nothing before an order is ever placed.

### Three cautions that bound the change

- **This is NOT re-arming `clob_enrichment`, and the July disarm does not argue against it.**
  `8e7b5732` rejected a loop that produced *hundreds of MB/day of book rows and no evidence*. An
  execution-only tape is the opposite: it is exactly the evidence, at a tiny fraction of the volume.
  **Anyone citing the disarm against this has misread which loop it was about.**
- **Volume is small but has NOT been measured.** 411 executions over 265 market-days at 2.222%
  coverage extrapolates to order-10² per market-day — **an order-of-magnitude expectation resting on
  an unverified linearity assumption**, since message limits and connect-time book bursts bias the
  observed rate. Measure it in a bounded pilot; do not size storage from this number.
- **The current collector sends the legacy frame** `{"operation":"subscribe", ...}`. It was accepted
  historically, but a new producer should use and *test* the documented `{"type":"market"}` form
  rather than silently inheriting that compatibility assumption.

> ## AUTHORIZED BY THE OPERATOR, 2026-08-09
>
> **1. Start capturing the execution tape — approved, effective immediately.**
> **2. Authorize a paper-only market-harvest lane — approved, sequenced AFTERWARDS.**
>
> The ordering is the operator's and is load-bearing: **capture supplies the evaluation that makes
> the harvest lane's output meaningful.** Authorising the lane first would produce a bot that quotes
> with no way to know whether it should. **Do not start lane work until execution capture is
> running and producing rows.**
>
> This supersedes the "nothing here has been enabled" note that stood until 2026-08-09. The standing
> "no paid API" rule is about **weather** providers; the exchange's public market stream and
> `/trades` endpoint are a separate question and are now in scope for capture.

**Implementation is staged deliberately, because the volume claim is an extrapolation.** §8c's
"order 10² per market-day" rests on scaling 411 observed trades by a 2.222% duty cycle, and message
limits truncate sessions so the true rate is **≥** that, not **≈** that. Nothing is sized from it.

| Stage | Who | When | Purpose |
| --- | --- | --- | --- |
| **Bounded pilot** | production | **after 18:00**, outside the graded window | measure the real rate, prove the documented subscription frame, prove identity survives end-to-end |
| **Continuous producer** | workstation mission | after the pilot returns numbers | build to the §8c contract using measured values |

**The pilot must not run inside 12:00–18:00.** It opens a network connection on the capture host,
and capture already died once on 2026-08-09.

### One design fact that makes the permanent producer cheap

The subscription delivers `book`, `price_change` **and** `last_trade_price` on one stream, but we
choose what to persist. At ~70 executions per market-day across 12 markets, an **execution-only**
tape is well under 1 MB/day. **The expensive thing was never the trades — it was persisting the book
that arrives alongside them.** So the July disarm's "hundreds of MB/day" objection does not apply to
a producer that discards book and `price_change` at write time.

### The SECOND operator decision, from `-09-48a`: authorize a market-harvest lane?

Independent of execution capture, and the only way to make §8bb's route reachable. **Designed, not
implemented.** Deleting the map or relabelling promotion is explicitly *not* sufficient:

1. A paper-only **`market_harvest` permission separate from model promotion**. Model `BLOCK` stays
   fully effective for edge/skew quotes — **do not reinterpret promotion globally.**
2. **A separate preflight profile.** It keeps active-event validation, CLOB token discovery,
   book/features, book continuity and freshness, information-event pulls, watcher health, exchange
   economics, post-only behaviour, and **every risk and notional cap**. It drops only
   `snapshot_model_rows` / `model_freshness` — required today merely to quote the market mid.
3. **Assemble inputs from event metadata + CLOB tokens/books/features**, not by iterating model
   snapshot rows. Today, no snapshot rows means no policy rows at all.
4. **A harvest branch entered *before* fair-value, model-age, overlay and disagreement logic.**
   Price from book mid, tick, `harvest_half_spread=0.01`, `max_harvest_spread=0.08`; keep event,
   spread, cadence, current-high and risk sizing gates; **record that no model probability
   participated.**
5. Keep shadow/paper mode, `live_trade_permission=false`, `$10 max_band_notional`, reward **$0**.

**What one successful day would and would not prove.** Would: route reachability and operational
mechanics — nonzero quote permissions, two-sided intended prices/sizes, lifecycle and post-only
behaviour, uptime, gate exposure, and a paper markout column under a declared $0 reward. **Would
NOT**: identify `A` or `f`, prove real fills, profitability, a unique break-even, reward
eligibility, live readiness, model edge, or promotion — and one day is not a powered economic
endpoint. **Forward execution capture (above) remains the only route to `f`.**

## 9. Release #1 is not sufficient for promotion — and MM quoting is gated on promotion

Measured 2026-08-06. **Read the whole entry; an earlier same-day version of it overclaimed
and was corrected within hours.** Canonical:
[release-one-is-not-the-mm-critical-path.md](release-one-is-not-the-mm-critical-path.md).

| Claim | Status |
| --- | --- |
| MM countability *modules* contain zero references to release binding | **True**, and insufficient on its own |
| MM quoting is gated on promotion | **True** — 924 intents today, `promotion_state` BLOCK on all, `known_edge_reason=promotion_block` on **847 (91.7%)** |
| Release #1 is *sufficient* for promotion | **False.** `hourly_model_performance` BLOCKs on early-hour Brier trailing the market by **0.0205 vs a 0.0030 tolerance in all 12 markets**; its own remediation reads `keep promotion blocked` |
| Release #1 is *necessary* for promotion | **NOT ESTABLISHED.** Today cannot test it — the chain died at the barrier, so promotion refresh never ran and its summary is all-null; the BLOCK is the `not_run` default |

**What survives for sequencing:** the blindness repair belongs *before* the candidate freeze.
Freezing bakes a knowingly blind incumbent into the baseline every future comparison uses,
**and** model skill is an independent promotion blocker that no release pointer clears — so
model work is on the promotion path in a way that building the release is not.

**Method lesson, the second time this project has paid it:** the retracted version reached its
conclusion by grepping three modules for a string and generalising to a causal claim. A search
is not a trace. §7 records the same error made against `-09-01a`.

---

## Related

- [release-one-is-not-the-mm-critical-path.md](release-one-is-not-the-mm-critical-path.md) —
  the sequencing finding above, with reproduction
- [mission-dispatch-reconciliation.md](mission-dispatch-reconciliation.md) — how to tell a
  never-dispatched mission from a completed one
- [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md) — what is not true despite appearing so
- [DELEGATION_CONTRACT.md](DELEGATION_CONTRACT.md) — standing boundaries for delegated missions
- [AGENT_CONTEXT.md](AGENT_CONTEXT.md) — durable domain invariants
- [forecast-source-and-training-population.md](forecast-source-and-training-population.md) — provider
  and population decisions
- [reserved-confirmation-window.md](reserved-confirmation-window.md) — **wins over every other
  document where they touch**

## Update this file when

A measurement establishes, revises, or retires a finding above. Add the date, the support (date
clusters, market clusters, market-days), and the interval treatment. **Move retracted claims to
`RETRACTED_AND_FALSE_LEADS.md` rather than deleting them** — knowing what was wrong is what stops it
being re-derived.
