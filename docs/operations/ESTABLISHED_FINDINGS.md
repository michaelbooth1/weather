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

1. **Protect irreplaceable capture and keep real settlement evidence accruing.** Contiguity is not
   the objective (§0d), but a lost public execution interval or unsettled date cannot be recreated
   by documentation or a later model run.
2. **Determine whether International market making is profitable after every cost.** The approved
   experiment is market-centred resting liquidity: spread plus actually paid maker rebates versus
   adverse selection, inventory/settlement loss, fees, and operational cost. Public executions
   provide counterfactual paths; only authoritative own-account events and balances prove realized
   economics (§8c). No profitability result exists yet.
3. **Improve the weather forecast from our own information.** We currently lose to the market
   (§1). The model is an input to quote centring and risk control, not assumed alpha and not a
   prerequisite for testing market-centred spread economics. Benchmark-consuming controls remain
   diagnostics rather than forecast improvements (§0c).

**Ordering changed by the operator's 2026-08-13 maker-rebate pivot.** Sections §0b–§0c remain the
canonical model-research standard, but their statement that market making is downstream of beating
the market is superseded. The taker remains deprioritized.

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

**So genuine PIT provenance exists in OUR ARCHIVE for temperature only.** Historical Forecast
returns the *settled* profile; it cannot say what was forecast at the cutoff.

> ### NARROWED 2026-08-09 — "temperature only" is a property of what we REQUEST, not of the free tier
>
> Probed directly against `previous-runs-api.open-meteo.com`, read-only, **12 of the 21 declared
> fields return complete PIT data at lead 7** (Toronto, 2026-07-05→06, 48/48 non-null each):
>
> | PIT-available free (12) | NOT available (9) |
> | --- | --- |
> | `temperature_2m`, `cloud_cover`, `shortwave_radiation`, `wind_speed_10m`, `cape`, `direct_radiation`, `diffuse_radiation`, `wind_gusts_10m`, `precipitation_probability`, `precipitation`, `vapour_pressure_deficit`, `et0_fao_evapotranspiration` | `cloud_cover_low/mid/high`, `visibility`, `soil_temperature_0cm`, `soil_moisture_0_to_1cm` (all return 0/48); `temperature_925hPa`, `temperature_850hPa`, `geopotential_height_500hPa` (HTTP 400) |
>
> **The cause is in our own fetcher:** `forecast_history.py:692` builds
> `hourly = ",".join(f"temperature_2m_previous_day{lead}" ...)` — **it has only ever asked for
> temperature.** Eleven additional PIT-honest fields have been free the whole time and were never
> requested.
>
> **Scope of this probe, stated so nobody over-reads it: ONE market, TWO target dates, leads 1 and 7.**
> It is strong on *availability* and says nothing about coverage across markets, dates, or history
> depth. **Treat as a verified probe, not a full trace** — it needs a mission before the fetcher
> changes.
>
> **What survives unchanged:** the 9 failing fields are a real wall; the stitched-source refusal is
> still correct; and `-09-55a`'s NO-GO on *its* proposed fix stands. What narrows is the **scope** —
> the wall covers 9 fields, not 21.

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

---

## 0d. THE STREAK GATES NOTHING ON THE CRITICAL PATH — operator challenge, 2026-08-10

**Operator: *"I thought the streak would have been worth more but we hit 14 days and it bought us
very little. What good is it now?"*** **The challenge is correct, and the mechanism is worse than
bad luck.**

### Both consumers of contiguity are off the critical path

| Consumer of *contiguous* days | Status |
| --- | --- |
| PIT staging receipt — `point_in_time_staging_receipt.py:253` requires a **contiguous 14-day window** | serves the **retrain / release** path — **off the critical path** (§0b) |
| Release admissibility | **deferred indefinitely** (§0b) |

### And banking a streak was never possible — it has a 7-day shelf life

**`POOLED_PIT_MAX_LATEST_TARGET_AGE_DAYS = 7`** (`pooled_training.py:54`, enforced at line 391).
Pooled PIT training requires the **latest** target to be at most 7 days old. **So the 14-day streak
banked in July had already expired before anything could consume it.** It "bought very little"
**structurally, not through misfortune** — and a future retrain would need a *fresh* streak anyway,
so early banking carries **no option value**.

### What the live work actually needs — and it is NOT contiguity

§1d's post-boundary confirmation panel is the only thing standing between us and being able to
**believe** any improvement. It needs **promotion-countable date clusters**. Crossed date × market
clustering treats dates as **exchangeable** — **gaps are irrelevant.** And per §5 the admission bar
is **`promotion_countable`, not `quality_grade == "complete"`.**

Measured 2026-08-10, post-boundary:

| Date | Countable markets | Grade |
| --- | ---: | --- |
| 07-31 → 08-05 | **12 / 12** each | complete |
| 08-06 | 0 | missing_settlement |
| **08-07** | **11 / 12** | **`partial` — and it still counts** |
| 08-08 | 0 | missing_settlement |
| 08-09 | **12 / 12** | complete (settled by today's 09:30 run) |

**Eight usable date clusters, not five.** §1d planned from **D=5 on 08-09 accruing ~1/day**, which
predicts D=6 today. **We are at D=8 — two ahead of schedule**, while the streak counter reads
**0/14** and looks like a catastrophe.

### The real defect: we count the wrong property, loudly

**`08-07` breaks the streak and simultaneously counts for the panel.** The metric that screams is
measuring something nothing consumes; the metric that matters has **no counter at all**. Same shape
as the settlement-hole detector that went blind on 2026-08-10 — *ask what a monitor counts, not
whether it is green* — but inverted: **a red light over a non-problem, and no light at all over the
live clock.**

### What changes

- **Objective 1 is reframed** to settled promotion-countable accrual (§0). Contiguity is demoted to
  a health *proxy*, not a goal.
- **A lost day still costs a date cluster**, which is real — the confirmation clock is fed one day
  at a time and cannot be conjured from nothing. **But it is a linear cost, not a reset.** Do not
  treat a broken streak as an emergency, and do not treat 14 contiguous days as an achievement.
- **Capture health is watched directly** (in-window gap, captures/day), and the settlement-hole
  detector was repaired 2026-08-10. Neither needs the streak as a proxy.
- **If the retrain returns to the critical path, rebuild the streak then** — the 7-day shelf life
  means it must be fresh regardless.

---

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

## 1e. THE PIT SOURCE STOPS 2026-06-23 — and that, not dispersion, is what `-09-58a` found

`-09-58a` screened two PIT-honest own-information dispersion signals on in-season B and returned
**NO-GO**. No feature was built, C was never scored, and **campaign decision 8 closed unused** —
the ledger worked exactly as designed on its first use.

### Read it as a BLIND null, not a precise one

| Signal | OOF MSE improvement [crossed 95%] | Power | 80% MDE |
| --- | ---: | ---: | ---: |
| Seven-run forecast-high SD | `−0.002960 [−0.012636, +0.003834]` | **0.113** | `0.011356` |
| Lagged five-day error SD | `−0.013338 [−0.068979, +0.001003]` | **0.103** | `0.055613` |

**These are wide intervals at power ~0.11. Contrast `-09-44a`, whose *tight* interval licensed a
conclusion.** The report is right that the negative points must not be redescribed as "dispersion
is protective" — and **the symmetric warning is equally binding: this does NOT establish that
dispersion signals are worthless.** It establishes that a screen on **11–14 date clusters could not
see anything.** Distinguishing a blind null from a precise one is the distinction this project has
already paid to learn.

### Why the screen was blind — the finding that matters

**The PIT-honest source ends `2026-06-23`. Verified on production, not taken from the report:**

```
fixed_lead_day_offset        n=25620  min=2021-05-10  MAX=2026-06-23
stitched_continuous_archive  n= 5532  min=2018-05-10  MAX=2026-06-23
```

**Out-of-season C is July. It has ZERO PIT-honest coverage.** So *any* PIT-honest forecast-derived
feature is currently **untestable on the stratum we actually serve** — the confirmatory design of
§1c cannot be run at all for this class of candidate.

It also thinned the screen itself. B is D=23; coverage left **17 and 20**, and the forward-chain
warm-up (6 prior clusters required) took each down to **11 and 14**. Both costs are real; the
warm-up is the larger one, so **re-fetching alone would take the screen to ~17 clusters, not to
comfort.** The decisive gain from a re-fetch is **C becoming testable at all.**

### IT IS FULLY RECOVERABLE — there is no clock

Probed directly against the same free endpoint the fetcher already uses
(`previous-runs-api.open-meteo.com`), read-only, nothing written:

| Probe | Result |
| --- | --- |
| Toronto, 2026-07-05 → 07-11, leads 1–7 | **HTTP 200, 168/168 non-null at every lead** |
| 2025-07-01 (last year) | 200, 72/72 at leads 1 and 7 |
| 2021-06-01 (the configured floor) | 200, 72/72 at leads 1 and 7 |

**Nothing has been lost and no retention cliff exists.** The gap is not decay — **we stopped
running the fetch.** This was checked *because* a deadline would have been urgent; there is none,
and that is worth stating so nobody manufactures urgency later.

### The consequence

**The ~60-call archive re-fetch — code landed by `-09-33a`, never run, parked when the retrain left
the critical path (§4b) — is now the blocker for the CURRENT goal too.** It stopped being a retrain
prerequisite and became a prerequisite for testing any PIT-honest feature under §0c.

### FETCHED AND STAGED 2026-08-10 — the gap is closed, but NOT adopted

Operator authorized the re-fetch. **Staged to `C:\tmp\pit-refetch-2026-08-10`, deliberately NOT
written into production `data/`.**

| | |
| --- | ---: |
| Markets | **12 / 12** |
| Range | **2026-06-03 → 2026-08-09** — the date gap **and** the sealed corpus in both strata |
| Variables per market | **84** (12 fields × leads 1–7) **in ONE call** |
| Rows | **1,645,056** (1,137,024 + 508,032 front segment) |
| Coverage | **100.0000%** non-null, every market, both segments |
| Provenance | `fixed_lead_day_offset` / `open_meteo_previous_runs` — **stitched endpoint never touched** |

**Two segments, and the second one matters more than it looks.** The first closed the *date* gap
(`06-24 → 08-09`). But the **11 missing fields were absent from the ENTIRE archive, not just the
gap** — including in-season B. A front segment (`06-03 → 06-23`, `C:\tmp\pit-refetch-2026-08-10-front`)
was fetched so the sealed corpus is covered in **both** strata. **Without it the fit-on-B /
score-on-C design of §1c would have had a test stratum and no training stratum.**

**Positive control against the archive.** The staged range begins exactly where the archive stops,
so `2026-06-23` was fetched separately and compared to a known-good row:

```
STAGED  2026-06-23T00:00 lead1: temp=13.1  cloud=100  cape=0.0
ARCHIVE 2026-06-23T00:00 lead1: temp=13.1  cloud=''   cape=''      TEMPERATURE MATCH: True
```

**Exact reproduction of the field we already hold, and real values where the archive is blank.**
That blankness is the finding made concrete: the columns existed in the schema all along —
`forecast_history.py:692` only ever asked for `temperature_2m_previous_day{lead}`.

### ADOPTION IS A SERVING CHANGE — do not "just copy it in"

**`model_features.py:1775` calls `load_forecast_daily(daily_path_for(spec))` and feeds
`forecast_high` into the HISTORICAL ANALOG DAYS** used to build today's forecast. Backfilling
`2026-06-24` onward would hand the analog path real values where it currently has `None`, **for
exactly the recent dates it looks at**. That is an unmeasured change to what we serve.

**Sequence: measure by replay against the sealed corpus, then adopt.** Never the other way round —
§3's floor fix moved the served ratio `1.6639 → 1.4980`, so serving changes are not small. Staging
first costs nothing and keeps the option.

**Do not conclude from `-09-58a` that own-information dispersion is a dead end.** The honest
statement is that **it has not yet been tested at usable power, and the thing preventing that is a
fetch nobody has run.**

---

## 1f. THE TAIL IS CENTRE OVERCONFIDENCE, AND IT IS EX-ANTE PREDICTABLE — `-09-59a`, 2026-08-10

**GO.** Severity-tail membership is predictable from **own information alone**, forward, with no
provider call and no new data.

| Own-information family | Forward AUROC [crossed 95%] |
| --- | ---: |
| Schedule only (market/unit + season + cutoff) | 0.49298 [0.43398, 0.55117] |
| **Band / own distribution state** | **0.85207 [0.81556, 0.88834]** |
| Weather at cutoff | 0.54832 [0.49180, 0.60039] — **not established** |
| **Full** | **0.90260 [0.88356, 0.91772]**, MDE 0.02406 |

Observed AUROC **exceeds all 500 draws** of the corrected global-permutation null (mean 0.49985,
max 0.51243). Concentration is **not** a density artifact — equal-snapshot and equal-market-day
weighting both reproduce 4.387% / 64.140%.

### What the tail actually is

| Own-distribution position | Tail prevalence | Share of tail rows |
| --- | ---: | ---: |
| **Centre / modal band** | **26.5929%** | **55.1096%** |
| Adjacent shoulders | 7.2769% | 29.2243% |
| Other / extreme bands | 0.9377% | 15.6661% |

**Centre + shoulders carry 84.33% of tail rows.** Centre-minus-shoulder is **+19.3160 points
[15.8026, 23.1529], power 1.000.** **The tail is centre-and-shoulder OVERCONFIDENCE, not an
extreme-bin phenomenon** — which independently corroborates §1's "our mode wins ~24%".

**Routes this CLOSES:**

- **"One or two bad markets" is dead.** Effective market count **11.44 of 12** (HHI 0.08739); the
  top two hold 23.47% of tail rows against 16.76% of all rows. There is no operational station fix.
- **Season and cutoff gating: NO-GO.** C−B `+1.3731 [−0.0497, 2.7464]` power 0.496; primary−early
  `+0.6263 [−0.2027, 1.3803]` power 0.343. Unsupported in both directions.
- **Weather alone is not established** — AUROC 0.548, Brier improvement negative. It adds
  *collectively* after band state (+0.05053 [0.01903, 0.08255]) but the increment is +0.117 in B
  and +0.026 [−0.003, +0.058] in C, and **that asymmetry bars a weather-regime claim.**

### Addressability, and it is a CEILING not a gain

Top 5% of forward scores: precision **39.70%** (8.62× base rate), recalls **43.10%** of tail rows
and **27.42% [20.86%, 34.12%]** of all positive excess loss. **No served improvement was measured.
Do not book 27.42% as expected gain** — it is what a perfect intervention on that slice could
reach.

### THREE things to carry forward — mine, not the report's

**1. This is NOT closed by §1c.** §1c closed **global, information-free monotone mappings**. A
reshape fired by an **own-information trigger** uses information to decide *where* to act, which
makes it a model change, not a calibration map. Anyone citing "recalibration is closed" against
this has conflated the two.

**2. Anchor the expected size to §1c's `8.829% [−2.467%, +16.494%]`, not to 27.42%.** §1c's
β=0.55 **global smoothing is the closest already-measured analogue of "flatten the centre"**, and
it was not distinguishable from zero. Two readings, both live: conditioning could **concentrate a
benefit that global smoothing diluted across the 95% of rows that were fine** — or §1c's upper
bound already caps it. **Whoever tests this must say which they expect, in advance.**

**3. Open caveat worth one cheap check: the `|p_model − p_market| ≥ 0.30` gate mechanically favours
high-probability bands.** A band where we assign 0.01 can only enter the tail if the market assigns
**≥0.31**. So "the tail is centre-concentrated" is **partly definitional**. It is not refuted —
extreme bands still supply 929 tail rows — but the report tested *density* artifacts and not this
one. **Re-run the position split under a relative or rank-based disagreement gate before building
on the centre story.**

### Ledger

**No decision spent.** No candidate fitted, no C candidate score, no probabilities modified. Any
mission that turns direction 1 or 2 into a candidate **must declare and spend a slot explicitly**.

---

## 1g. WHERE THE LOSS IS IS NOT WHERE THE FIX WORKS — `-09-60a`, 2026-08-10

**NO-GO at P0, zero ledger cost.** Conditional own-distribution reshaping **does not beat global
smoothing** on in-season B. The production agent's predeclared expectation was the opposite and was
**falsified cleanly**.

| B score | Brier |
| --- | ---: |
| Incumbent | `0.053379789` |
| **Global smoothing, β=0.55** | **`0.050612803`** |
| Conditional, β=0.52 / threshold 0.65 | `0.051511678` |

**Conditional lost on the very data it was fitted on**, by `0.000898875`. Forward: global
`0.053566688` vs conditional `0.054804104`, paired **`−0.001237416 [−0.003005130, +0.000583109]`**
— not distinguishable from zero, but the point is in the wrong direction and the rule required
conditional to *win*.

### The number that interprets the result: the trigger fired on 46.786% of snapshots

The fit was free to pick any threshold, including a narrow tail-focused one. **It chose to fire on
nearly half the panel — and still lost to firing on all of it.** The gradient points at full
coverage.

> **Smoothing's benefit is DIFFUSE, not concentrated at the tail. Conditioning discards benefit
> instead of concentrating it.**

**This dissociates two things §1f made it tempting to conflate.** The tail carries **64.140%** of
excess loss and is predictable at **AUROC 0.90260** — and **knowing where the loss is does not tell
you where the remedy applies.** §1f's 27.42% "addressability ceiling" was flagged as unbookable;
this is *why* it was unbookable.

### What this closes

**Distribution reshaping as a direction.** §1c bounded the global family at **8.829%
[−2.467%, +16.494%]**, not distinguishable from zero; `-09-60a` shows conditioning cannot
concentrate it. **The whole family is capped by a number indistinguishable from zero.** Strictly,
one trigger form (peak probability) and one reshape form (power map) were tested — but with the
global bound and the coverage gradient both pointing the same way, **do not spend another decision
here without a genuinely new mechanism.**

**Safety held throughout:** probability mass preserved, all **12,882** zero-probability B rows
stayed exactly zero, the serving floor untouched.

### What is left, stated plainly

Every own-information lever derivable from **what we already hold** has now been tested and bounded:
recalibration (§1c), conditional reshape (here), markets and season/cutoff (§1f), own station
weather at cutoff (§1f, AUROC 0.548), input completeness (`-09-44a`, ≤0.6%). Market shrinkage works
and is **forbidden** as benchmark-consuming (§0c).

> **We have exhausted what can be done by reshaping what we already know. The remaining lever is
> knowing MORE.**

And there is exactly one untapped free source: **the 11 PIT forecast fields the fetcher never
requested** (§0a). **Note carefully — §1f tested our own *station observations* at cutoff, not
*forecast-model output at issue time*.** Those fields do not exist in the archive, so they are
**untested, not disproven.** That makes the re-fetch the top item, and it is production work
because the workstation may not call providers.

---

## 1h. THE PIT-FIELD TEST IS PRE-REGISTERED AND FROZEN — `-09-61a`, 2026-08-10

The 12-field corpus of §1e has a **frozen, hashed protocol written before the data was
integrated**, so the candidate cannot be fished. `-09-63a` later executed its B-only integrity
screen unchanged; the result is in §1j.

| | |
| --- | --- |
| Artifact | `docs/roadmap/pit-field-evaluation-protocol-2026-09-61a.json` |
| SHA-256 | `336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146` |
| Campaign | Allocated here; **CLOSED UNUSED by `-09-63a`**. α remains **7 of 20**; 13 available |
| Candidate | ONE lead-1 target-day surface-heating / convective-budget tilt, 12 named features, no sweep |
| Design | fit on in-season B (D=23) → score once on out-of-season C (D=27), the §1c pattern |

**Digest reproduced independently on the production host** (15,048 bytes) and the roll verdict
re-run here: **ROLL-FREE, 4 files, 0 importable.** Merged `21356a85`, capture 6 loops both sides.

### P0 — the BOUNDARY is the result, not the point estimate

| Quantity | Value |
| --- | ---: |
| C incumbent excess-Brier gap `G` | `0.021135322` |
| MDE under the declared coherent-effect assumption (`a=b=c=0.05`) | **6.790047% of `G`** = `0.001435098` |
| Campaign-adjusted floor (3.2% × 1.3796) | `4.414601%` |
| Detectability boundary for a 10% effect | **`a=b=c ≤ 0.0736372`** |
| MDE at `a=b=c=0.075` | `10.185071%` — the 10% target is **no longer visible** |

**Verdict: CONTINUE CONDITIONALLY.** Every figure above reproduces here to all printed digits
(`z=3.0233414397392`, `K=3.8649626733121`). **The 10% target is a declared hypothesis, not a
measured prior** — `-09-44a`'s ≤0.6% precedent is the cautionary comparison, and the protocol
rejects as `NO_GO_UNDERPOWERED_EFFECT_FIELD` if the candidate's *own* effect field yields an MDE
above 10% of `G`. That is §1d's "re-derive the MDE for the candidate you actually test", enforced.

### The protocol is EXECUTABLE — verified against the staged corpus, 2026-08-10

The frozen coverage gate (lead 1, local hours 07:00–20:00, sealed dates only, 12 fields × 12
markets) was run against what is actually staged:

| Segment | Sealed dates | Cells expected | Missing | Duplicate | Non-finite |
| --- | ---: | ---: | ---: | ---: | ---: |
| Front `…-front` | 21 (`06-03 → 06-23`) | 42,336 | **0** | **0** | **0** |
| Back `…-08-10` | 37 (`06-24 → 07-30`) | 74,592 | **0** | **0** | **0** |
| **Total** | **58** | **116,928** | **0** | **0** | **0** |

**The gate passes on the full sealed window.** Nothing past `2026-07-30` enters either stratum.

> **TRAP — the corpus is in TWO ROOTS and the main one's manifest says `start_date 2026-06-24`.**
> An executor who reads `C:\tmp\pit-refetch-2026-08-10` alone gets **37 of 58 sealed dates** and,
> because B is June, would fit on **7 B dates instead of 23** — and the manifest would look
> complete while it happened. Both roots are required. See `CORPUS.md` in the main root.

### THE ASSUMPTION NOBODY HAD MEASURED AT FREEZE — resolved before execution by `-09-62a`

The protocol builds its interval as `point ± z(1−α/2) × bootstrap SD`, **z = 3.0233 at
α=0.0025 — a three-sigma normal quantile off a bootstrap whose market dimension has 12 clusters.**
That is the campaign-wide convention, inherited from `-09-44a` and `-09-57a`, not a `-09-61a`
choice.

**`-09-57a` measured multiplicity, never coverage.** Its 50,000-campaign simulation null-centres
the *real* crossed-bootstrap distribution to price best-of-k selection — so if that distribution's
dispersion is wrong at M=12, the multiplicity result inherits the error rather than detecting it.
**At protocol freeze no mission had measured empirical coverage.** `-09-62a` subsequently measured
it under a true-zero simulation before any candidate execution; §1i records the result and adopted
amendment A1.

The direction of the risk is known from the cluster-robust literature: few-cluster normal
intervals **under-cover**, and the error grows in the far tail. For scale, at 11 degrees of freedom
`t(1−0.00125) = 4.02` against `z = 3.02` — **a 33% wider interval, at the exact α this ledger
runs on.**

> **If the interval under-covers, α=0.0025 is nominal rather than real, every MDE in §1d is
> optimistic, and the 3.2% floor is a floor on the wrong quantity.** This gated decision 10 and
> retroactively qualified decisions 1–7. `-09-62a` measured it before decision 10 could be spent.

This is filed as the next mission rather than left as a note, per `HOW_WE_GET_THINGS_WRONG.md`
pattern 5.

### What was done right, and is worth copying

- **The negative control is an algebraic identity**, not an exchangeability assumption: an exact
  incumbent clone whose improvement is zero row by row. `-09-59a` had to correct its control
  mid-flight; this one **cannot drift**. It verifies the scoring path, not the inference calibration
   — which is precisely why the coverage mission was still required; §1i now closes it.
- **The spend trigger is conservative**: decision 10 is spent by the first computation that touches
  candidate-dependent C state together with any C outcome or market price — *including a failed
  attempt*. A broken run cannot become a free look.
- **Both endpoints are mandatory, and a primary win with a negative tail point is REJECTED.**
  That is `-09-60a` (§1g) converted into a rule.

---

## 1i. ALPHA=0.0025 IS SHORT ON THE THIN TAIL, NOT GENERICALLY AT M=12 — `-09-62a`, 2026-08-10

Coverage is now measured under a true-zero simulation using the sealed panel's actual occupancy
and endpoint-specific date / market / residual components from the real `-09-44a`
repair-minus-control field. The predeclared M=200 positive control passed at both alpha levels.

| Endpoint | Empirical alpha at nominal 0.05 | Empirical alpha at nominal 0.0025 | Restoring `q` at 0.0025 |
| --- | ---: | ---: | ---: |
| Out-of-season C | `0.04244` | **`0.00240`** | `3.006595` |
| **Severity tail** | **`0.04908`** | **`0.00340 [0.002927, 0.003950]`** | **`3.109889`** |
| In-season B | `0.00346` | `0` | `2.019972` |

The tail result uses 50,000 coverage replications (170 rejections; MC SE `0.000260`) and resolves
an absolute `0.00090` excess over the ledger alpha; the predeclared 80%-power resolution was
`0.0006486`. **The prior that every M=12 endpoint must under-cover is falsified.** Component mix
matters: C is nominal at ledger alpha and B is conservative, while the 5,930-row tail is short.

**ADOPTED 2026-08-10 as amendment A1 — uniform, both endpoints.** `z=3.0233414` is replaced by
`q=3.1098893` for **both** required decision-10 endpoints, not only the short tail. Nominal α is
unchanged at `0.0025`; the quantile is corrected to *deliver* it. The amendment is
`docs/roadmap/pit-field-evaluation-protocol-2026-09-61a-amendment-A1.json`, SHA-256
`549e26a3a55494e0da2d406809ad67c43dba60c6fbb3604aec62488ea4e8f2bb`; **the base protocol is
byte-identical and was edited nowhere** (`336150be1a62e88c2fe40ccd7b77916576d08981617ebbff1e01195007cfc146`).
The exact endpoint-specific rule was rejected deliberately: it would have cost no power on C, but it
makes *"which quantile applies here"* a live choice at analysis time, and this campaign's recorded
failure mode is researcher degrees of freedom, not lost power. **Decision 10 keeps its number** —
nothing has been executed, and every effect of A1 is strictly conservative (see `CAMPAIGN_LEDGER.md`).

> **A LIMITATION THE `-09-62a` REPORT DID NOT STATE: `q=3.1098893` IS A LOWER BOUND, NOT A POINT
> ESTIMATE.** The coverage simulation draws **Gaussian** date, market, and residual effects, but the
> severity tail is **by construction a selected-extreme subset** — incumbent SE > market SE and
> disagreement ≥ 0.30 — and is **not Gaussian**. Simulating a heavy-tailed field as thin-tailed
> **understates** far-tail miscalibration, so the true restoring quantile is **at least**
> `3.1098893`. Do not read it as the calibrated answer, and do not use it to argue the correction is
> now "priced". Uniform adoption was chosen partly to buy margin against exactly this.

This changes the section 1d campaign MDE multiplier from `1.3796` to `1.410455`
(current ledger MDEs x `1.022393`). The four proxy MDEs become `0.004309` B ratio, `0.053218` C
ratio, `0.021406` tail SSE, and `0.002366` primary-window Brier. The campaign-adjusted market
floor moves from `4.414601%` to **`4.513457%`**, so the practical >=5% step survives. The
alpha=0.05 D=73 / **2026-10-16** confirmation date also survives because neither required endpoint
under-covered at 0.05.

Decision 10's coherent `a=b=c=0.05` P0 MDE moves from `6.790047%` to `6.942096%` of `G`, still
below its 10% gate. **The frozen `-09-61a` protocol was NOT edited in place, and must not be** —
A1 is a separate, hashed, side-by-side amendment, which is the only permitted shape for a change
here. Decision 10 was **allocated and unspent as of this mission**, and was CLOSED UNUSED hours
later by `-09-63a` — see §1j. This calibration mission spent and allocated no
alpha and A1 spends none, so the ledger remains **7 of 20 spent, 13 available**. Full method,
components, seeds, coverage table, and evidence hashes are in
`docs/roadmap/agent-report-2026-08-19-workstation-interval-coverage.md`.
---

## 1j. DECISION 10 CLOSED UNUSED BEFORE FITTING — `-09-63a`, 2026-08-10

**NO-GO at Gate 3, zero ledger cost — and the gate was measuring the wrong thing.** The required
feature extract reproduced its frozen SHA-256 `60b450f1…ac8`. Before any fit, the B-only screen
found what it read as a realized winning band with incumbent repaired probability exactly zero, and
failed closed.

**What survives, and is the point of this section:** no beta was fitted, no expanding-window B
curve was produced, and **the surface-heating mechanism was not tested in either direction.**
Treating the absent coefficient vector as evidence about the mechanism would be a second error.
Only B outcomes and incumbent repaired probabilities were materialized; no C outcome, market
probability, candidate state, bootstrap draw, or clone control was ever computed.
**Decision 10 is closed unused and RETIRED, must never be reassigned, and alpha remains 7 of 20
spent, 13 available.**

**What does NOT survive is the trigger.** `-09-63a` named Denver `2026-06-08`, snapshot
`20260608T030552-0400`, band 4 as a served zero. **Production served `0.5206313021` on that row.**
The zero was a research-replay artifact: replay rebuilt `high_so_far = 91` from
`wu_current.max_since_7am_c` against a current temperature of 68, giving a replay floor of 91 where
the captured served floor was 68. `-09-65a` reached the same conclusion independently. The full
trace is `docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md`, and the
replay-vs-served floor divergence it exposes is an open production question, not a settled finding.

Of the B floor crossings, only **two** are genuine — Chicago `2026-06-14` (70/69) and San Francisco
`2026-06-09` (68/67); NYC `2026-06-22` is a fallback row with a blank `served_floor_bucket`.
`-09-68a` then showed the gate is structurally mis-specified rather than unlucky: a fail-on-any-row
gate has `P(fire) = 1 − (1 − q)^n`, which at 2 crossings in 204 B market-days fires **86.60%** of the
time on the observed panel and **99.27%** at 500 market-days, **regardless of candidate quality**.
It must not be re-registered unchanged.

> **This section is therefore evidence about the INSTRUMENT, not about the candidate.** The NO-GO
> and the zero alpha cost are real; the stated cause is retracted. Do not cite the Denver row.

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

## 8c. Public execution capture and own-account fills answer different questions

**Established 2026-08-10 by `-09-47a`, corrected by production audit 2026-08-13.** The original
section conflated a market-wide public-flow tape with our own quote-selection process. The public
tape is necessary for market price paths and counterfactual markouts; it cannot reveal which of our
resting orders filled, their queue position, our fees/rebates, inventory, or realized P&L.

| Route to `f` | Status |
| --- | --- |
| Model edge makes quoting profitable regardless | **RETIRED** (`-09-46a`: 114 cells, zero positive) |
| Measure `f` from the retained tape | **IMPOSSIBLE** — 411 executions, and no cancellation labels |
| Reconstruct executions from `price_change` / `book` deltas | **NO-GO** (§1b.3) — unidentified |
| Capture the public execution tape going forward | **NECESSARY BUT NOT SUFFICIENT** — price paths, market trades, and counterfactual markouts only |
| Capture authoritative own-account user events, open orders, positions, fees and rebate receipts during a bounded maker session | **THE ROUTE TO OUR REALIZED FILL SELECTION AND ECONOMICS** |

**So the deciding economic evidence does not exist yet and can only be accumulated.** Public
execution-days and own-account maker sessions are separate denominators and must never be merged
into one counter. A public trade after our hypothetical quote supports a counterfactual; only an
authoritative account event proves a fill, and only reconciled positions/fees/rebates support P&L.

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
3. **Necessary for Stage 2: authenticated own-account evidence.** The user stream, open-order
   reader, position reader, and fee/rebate receipts are the authority for our lifecycle and P&L.
   They cannot estimate a market-wide informed-flow denominator, but the public stream cannot
   substitute for them. Mutation stays disabled if any authoritative reader is absent or stale.

### Three cautions that bound the change

- **This is NOT re-arming `clob_enrichment`, and the July disarm does not argue against it.**
  `8e7b5732` rejected a loop that produced *hundreds of MB/day of book rows and no evidence*. An
  execution-only tape is the opposite: it is exactly the evidence, at a tiny fraction of the volume.
  **Anyone citing the disarm against this has misread which loop it was about.**
- **The pre-pilot volume estimate was not a measurement.** 411 executions over 265 market-days at
  2.222% coverage extrapolated to order-10² per market-day, but message limits and connect-time book
  bursts made linear scaling invalid. The bounded production result below supersedes that estimate
  for its exact scope; it is still too short to establish a daily rate.
- **The legacy collector used** `{"operation":"subscribe", ...}`. The corrected producer uses the
  documented `{"type":"market"}` form, and the production pilot proved that form against every
  configured seed. Do not restore the compatibility assumption.

### Production bounded pilot — capture mechanics proved, economics still absent

**Measured 2026-08-14 from the production-only receipt
`data/alerts/execution_tape_probe_last.json`.** The probe ran from **02:25:00 to 02:38:05 local**
with a declared **780-second** duration. It connected all **12/12** configured seeds and retained
**146** routed public execution observations spanning **11/12** configured market-day scopes.
Parse rejections, unrouted observations, and ambiguous observations were **0 before and after**;
the retained rows had **0 repeated, weak, or partial public identities** in this run.

The child peaked at **4.14 MB working set**, host commit peaked at **34.44%**, all **3/3** capture
workers were healthy before and after, and the slow snapshot heartbeat advanced from
**02:23:26 to 02:35:52 local**. The durable execution-tape status was `STOPPED` at teardown, so this
was a bounded proof, not continuous collection.

**Evidence boundary:** these are received-time public market observations. Even a row carrying a
transaction hash plus complete documented economics fields retains the identity class
`transaction_hash_plus_economics_not_proven_unique`. The pilot proves subscription, routing,
identity preservation, resource coexistence, and price-path collection. It does **not** prove
unique fills, execution intensity, our fills, queue position, fees, rebates, inventory, or P&L.

> ## AUTHORIZED BY THE OPERATOR, 2026-08-09
>
> **1. Start capturing the execution tape — approved, effective immediately.**
> **2. Authorize a paper-only market-harvest lane — approved.**
>
> Public capture still supplies market-path evaluation, but it is not a prerequisite for preparing
> the fail-closed own-account lifecycle implementation. The two evidence sources are complementary.

> ## AUTHORIZED BY THE OPERATOR, 2026-08-13
>
> Prepare and run a minimal real-world test on the production International execution host with
> a finite **100 USDC-equivalent hard cap**. Exactly one market, post-only orders, no naked sells,
> existing risk ceilings non-raisable, and authoritative user-event plus position readers are
> mandatory.
>
> This supersedes the "nothing here has been enabled" note that stood until 2026-08-09. The standing
> "no paid API" rule is about **weather** providers; the exchange's public market stream and
> `/trades` endpoint are a separate question and are now in scope for capture.

**Implementation remains staged deliberately.** The production pilot replaces the old linear
extrapolation for one bounded interval, but it does not establish a stable daily rate or solve the
own-account evidence gap.

| Stage | Who | When | Purpose |
| --- | --- | --- | --- |
| **Bounded public-tape pilot** | production | **PASSED 2026-08-14** | proved the documented subscription frame, routing, identity preservation, bounded resources, and capture survival |
| **Continuous producer** | workstation mission | after the pilot returns numbers | build to the §8c contract using measured values |
| **Bounded own-account maker session** | production execution host | after Stage-0/1 readiness and authoritative readers pass | prove post-only lifecycle, reconciled fills/positions/fees/rebates, and bounded realized economics |

**The pilot must not run inside 12:00–18:00.** It opens a network connection on the capture host,
and capture already died once on 2026-08-09.

### One design fact that makes the permanent producer cheap

The subscription delivers `book`, `price_change` **and** `last_trade_price` on one stream, but we
choose what to persist. The bounded producer discarded `book` and `price_change` at write time and
retained only the execution evidence. **The expensive thing was never the trades — it was
persisting the book that arrives alongside them.** So the July disarm's "hundreds of MB/day"
objection does not apply to this execution-only design. Size continuous retention from a longer
measured run, not from the retired linear extrapolation.

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
NOT**: identify `A` or an informed-fill fraction, prove real fills, profitability, a unique break-even, reward
eligibility, live readiness, model edge, or promotion—and one day is not a powered economic
endpoint. Public execution capture supplies the counterfactual market path; a bounded own-account
session supplies actual fills. Neither alone identifies a universal informed-flow fraction.

## 8d. A terminated scheduled wrapper can leave its governed child alive — measured 2026-08-13

`WeatherEveningEvidenceRefresh` started at **12:03:20 local** and Task Scheduler later reported the
wrapper terminated (`0x41306`), but its delegated `weather.operations.daily_refresh` process tree
remained alive. The proof is direct: both surviving Python processes had the task's exact creation
second, the child named PID `19872` in `daily_refresh_faulthandler_20260813T160323Z.log`, and its
parent/child relationship was still present after the scheduled task returned to `Ready`.

At the last pre-kill guard sample the child held **44,391 MB private commit**. Snapshot admission
failed for all 12 markets, and the authoritative streak checker recorded a **13:24→13:57 local
gap, 32.5 minutes**, so `2026-08-13` is unavoidably partial. Disk free fell from **180.6 GB to
146.8 GB** while commit expanded; **26.2 GB returned immediately after process teardown**, proving
most of the apparent disk burn was transient pagefile/commit pressure rather than retained tapes.

The process could not be terminated from the interactive session because it belonged to S4U. The
already-scheduled S4U memory guard terminated the exact two-process tree after it was taught the
narrow ownership rule: inside 12:00–18:00, an evidence-refresh `daily_refresh` child older than two
minutes is an orphan when its owning scheduled task is not `Running`. The task was disabled before
its 14:00 retry. By **14:00:20**, all 12 current event folders were fresh, snapshot admission passed,
and the last fleet cadence had zero errors and zero stale markets.

> A governed `-m weather.*` exemption is not sufficient by itself. Scheduler ownership must be
> checked, because termination of the wrapper does not guarantee termination of its delegated
> child.

**Follow-up proof, 2026-08-13 18:16–18:21 local.** After the wrapper was changed to create its
Python child suspended, assign it to a Windows Job Object with `KILL_ON_JOB_CLOSE`, and only then
resume it, a real `WeatherEveningEvidenceRefresh` scheduled invocation established the tree
`3288 → 17464 → 20180`. At the five-minute inspection, PID `20180` held **9,030.1 MB working set**
and **13,810.1 MB private memory**; system commit was **28,703,297,536 / 37,054,656,512 bytes
(77.46%)**. `Stop-ScheduledTask` moved the task to `Ready`, returned `0x41306`, and all three PIDs
were gone in under three seconds without a separate process kill. System commit then fell to
**16.91 / 34.51 GB (49.00%)**.

This retires the orphan-cleanup defect but establishes a separate daytime-resource defect. The
14:00/17:00 task is disabled again. Do not re-enable it until its evidence workload is chunked and
guarded by capture-health plus commit admission; child-tree containment alone does not make an
eight-hour monolith safe beside capture.

## 8e. Large live logs caused capture failure; bounded non-deleting rotation is now live

**Incident measured 2026-08-09; mitigation production-proved 2026-08-14.** Reopening a
**625 MB** `diagnostics.jsonl` raised `PermissionError`, killed the snapshot loop, exhausted its
**6/6** restart budget, and produced a **5 h 54 m** capture outage. A held-open console was mostly a
disk concern; repeatedly reopened JSONL sidecars and restart-breaker reads were the crash path.
Hand rotation removed the immediate trigger but did not prevent regrowth.

The landed implementation rotates managed files at a **64 MiB** bound using timestamped renames,
never deletion. First-adoption archive scans are bounded to the breaker window, transient Windows
rename/unlink denials receive bounded retry, persistent denial still fails closed, and breaker
history survives rotation. The dormant enrichment writer is bounded without re-arming that loop.

The guarded adoption retained, among other archives, a **1,080.747 MB** observation console,
**66.910 MB** observation event sidecar, **94.297 MB** snapshot diagnostics file,
**372.132 MB** snapshot console, and **98.501 MB** CLOB console. The replacement observation
console and event sidecar reopened below **0.100 MB**, while all **3/3** capture workers adopted the
new exact source and passed PID, writer-lock, heartbeat, and runtime-fingerprint recovery. This
closes log regrowth as an unowned streak risk. Archive lifecycle is a separate retention decision;
do not delete these retained files as part of rotation.

## 8f. Daily-roll launch decisions must be serialized, not only duplicate-checked

**Incident measured 2026-08-07; maker mitigation landed 2026-08-08; taker parity added
2026-08-14.** Two maker workers started **47 seconds** apart. Both launchers read the old status
before either launch result was durable, the second PID replaced the first in the status file, and
the supervisor later stopped only the recorded PID. The unrecorded worker survived with **431 MB**
resident while the host recorded **430** memory-admission refusals and two protected-window capture
gaps of **24** and **41 minutes**. The same defect class had produced taker orphans on 2026-06-30
and 2026-07-04.

The durable invariant is stronger than “check whether a worker already exists.” Direct `start` and
supervisor `ensure` must acquire the same process-safe lock around the complete read/retire/launch/
persist lifecycle decision. Maker and taker daily rolls now do so, fail closed if the lock cannot
be acquired, and carry a concurrent start/ensure regression proving that only one worker launches
and the waiter adopts its status. `staleness_sweep.ps1` keeps duplicate-process enumeration as an
invariant-breach detector; it is no longer the primary mitigation.

## 8g. A DEAD status with a source closure is a tombstone, not live roll evidence

**Failure measured 2026-08-06; stale artifact retired 2026-08-14.** The frozen
`loop_status_supervisor_status.json` described the snapshot loop as `DEAD`, `BLOCKED`, and
`restart_budget_exceeded=6>=6`, but also retained a complete `source_scope_files` list. Hand
analysis counted it as a fifth live closure while missing the differently named CLOB-enrichment
closure. The explicit `roll_verdict.ps1` inventory already rejected that mistake.

The stale file is preserved outside the live status namespace as
`data/snapshots/_retired_supervisor_status/loop_status_supervisor_status.20260713T182612Z.json`
with SHA-256 `FB263B9FD9A6FFC461F4FC76EC27D0E0560468C6EE1FB742995D2D9A0C3560D8`.
`staleness_sweep.ps1` now rejects `DEAD` or `BLOCKED` states generically in every configured
closure rather than carrying a permanent warning for one historical filename.

## 8h. Maker recovery outside the evidence window is non-countable waste

**Production state measured 2026-08-14 03:31 local; bounded recovery added 2026-08-14.** The prior
maker status recorded a run started at **23:01 local** for the previous target date. Its evidence
classifier correctly marked it `post_settlement_evaluation`, false for the live-forward gate, and
“started after active-day evidence window.” The supervisor had only a **07:05** lower launch bound;
same-target recovery after the **20:00** evidence cutoff was therefore allowed to consume restart
budget and create a run folder that could never count.

Maker `ensure` now has a fail-closed **07:05–20:00** local launch/recovery window aligned to the
configured evidence cutoff. A healthy worker is left alone after the boundary; only a proposed
`start` or `restart` becomes `scheduled_wait`, before recovery-budget accounting or process
mutation. The taker remains intentionally unbounded at the end of day. Inverted windows are
rejected rather than silently interpreted as overnight ranges.

## 8i. The temporary Windows Update block outlived its build window

**Policy audited and restored 2026-08-14 03:40 local.** The host still carried
`AUOptions=2` (notify-only) and `NoAutoRebootWithLoggedOnUsers=1`, installed for the 2026-08-03
release build window. Notify-only prevented unattended security-update download and installation;
the temporary safeguard had become a security-maintenance outage.

Both override values were removed after exporting the exact AU registry key to
`C:/Users/micha/ops/windowsupdate-au-policy-before-revert-20260814.reg` (SHA-256
`D3B8580B079287627A429F04A7FE6A0F37F84C02125C4F230F62D9F695874EA9`). Windows Update active
hours remain **08:00–01:00**, outside the automatic-restart window described by the streak runbook,
and neither Windows Update nor Component Based Servicing reported a pending reboot at the change.
No scan, download, installation, or reboot was initiated. `status.ps1` now fails visibly if
`AUOptions=2` returns.

## 8j. A monitor must distinguish durable risk from preserved history and unapproved work

**False warnings reproduced and corrected 2026-08-14.** `staleness_sweep.ps1` reported six
unreachable operations documents even though five were date-stamped historical evidence and the
sixth was the historical `OVERNIGHT_BRIEFINGS.md` aggregate. It also claimed the current
`STATE_OF_PLAY.md` omitted missions listed compactly inside the documented `-09-73a…-09-78a`
range, and treated every remote branch not merged to `origin/master` as approved work requiring a
scheduled merge.

The reachability check now applies to canonical/non-dated operations documents, while preserving
historical evidence without demanding an index entry. Mission drift understands explicit compact
ranges. The remote-branch merge warning was removed: a held or unapproved branch is not a merge
queue, and only an immutable explicitly approved exact-tip queue authorizes integration. These
changes remove three standing warnings without weakening capture, closure, task, or exact-tip
checks.

## 8k. Historical maker legs require their own captured International economics

**Immutable exact-tip suite measured 2026-08-14 04:30–04:38 local.** Branch
`codex/international-live-probe` was clean at
`904ce2d824fe48071062eb9a769d6a5e921b4dba`; all three capture workers passed every
chunk admission. The complete 17-chunk receipt contains **4,425 tests: 4,418 passed and 7
failed**, with terminal verdict `3 CHUNK(S) FAILED; do not merge`.

Four failures are one economics defect: daily maker scoring returned `BLOCK` when selecting,
trimming, or mixing historical run inputs because it tried to bind those legs to the newest
current-day condition/token snapshot. International condition and token identities roll by date;
the current snapshot cannot truthfully supply an older run's economics. Two failures enforce the
module-size ownership ratchet after the live-pilot runner crossed its warning threshold. The final
failure is a stale-stack research inventory mismatch already repaired on current production
master. None is a capture or resource-admission failure.

The correction is to atomically freeze the validated snapshot in each run, then score in a bounded
two-pass stream that verifies file hash, source hash, snapshot/quote identity, target date, and
run-time freshness. Missing, mixed, replaced, or tampered captures stay unbound with zero incentive
economics. The isolated current-master repair at
`9f3b926ecf6332ea23db990ee38401cce6f87495` then passed its own immutable **17/17 chunks and
4,417/4,417 tests** with all capture admissions healthy. It is pushed and proven roll-sensitive,
so production integration must wait for the next quiet window.

**Refreshed cumulative successor measured 2026-08-14 05:31–05:39 local.** Branch
`codex/international-live-probe-refresh-20260814` was clean and pushed at
`59e7bbfe9d9e47e88807a832238544c291e7c42a`. It contains current master, the per-run economics
repair, and the International Stage 0/1 stack. Its one immutable receipt passed **18/18 chunks and
4,523/4,523 tests**, with **19/19** preflight/chunk admissions observing all three capture workers
healthy. The task result was zero and the log contains one start segment and one terminal
`ALL CHUNKS PASSED` verdict. The runner is back below the 2,000-line ownership threshold through a
dedicated live-pilot policy module. Capability, lifecycle, and bundle boundaries each revalidate
the 100 pUSD wallet/request ceiling, and reported lifecycle orders cannot exceed 10 pUSD. The
post-push verdict is still roll-sensitive through the live CLOB loop and schema registries. This
cumulative exact tip supersedes the standalone economics branch as the preferred integration
target, but does not authorize an out-of-window merge or an order from a blocked location.

**Failed-tip packaging refusal measured 2026-08-14 08:40 local.** The S4U/Limited immutable
bundle task for obsolete failed tip `904ce2d824fe48071062eb9a769d6a5e921b4dba` ran once and
returned **1** after correlating to the suite task's nonzero result and terminal three-chunk
failure. It created **zero** bundle, manifest, or partial artifacts. Task Scheduler's operational
log records one time-triggered process and return code `2147942401`; no later path overrode the
failed suite. This proves the source-bundle boundary refused known-ineligible code as designed.

## 8l. The snapshot fatal-gap repair is suite-proved, not yet live-timing-proved

**Immutable exact-tip suite measured 2026-08-14 06:45–06:53 local.** Branch
`codex/supervisor-gap-bound-20260814` was clean at
`a206a7cf8036e7a371b3ec2a0922e2a952333dc5`. Its one receipt contains one start segment, one
terminal `ALL CHUNKS PASSED` verdict, **17/17 passing chunks and 4,402/4,402 passing tests**.
All **18/18** preflight/chunk admissions observed all three capture workers healthy, resource use
stayed below the wrapper ceiling, the scheduled task returned zero, and the workload lease was
released. The exact log is
`C:/Users/micha/ops/supervisor-gap-bound-full-suite-20260814.log`; its 17 JUnit sidecars carry run
tag `20260814T064503`.

This establishes software consistency for the immutable branch, not the operational fatal-gap
bound. The suite did not inject a hung snapshot worker or measure scheduler jitter, stop latency,
restart latency, or the next successful snapshot. The branch also predates the production S4U
registrar repair. Before integration, merge current production into it while preserving both the
cadence argument and S4U principal, run a fresh exact-tip suite, use the guarded quiet-window merge,
and measure the live stop-to-recovery interval. Keep the backlog item open until that evidence
exists.

## 8m. Target-date validation must precede the active-day maker launch

**Live paper-path reproduction and recovery measured 2026-08-14 07:05–07:09 local.** The scheduled
paper-maker started on the current date with all three useful-write checks passing, but all **12/12
markets** failed preflight because the validation artifact still targeted `2026-08-13`. The live
location configuration had already refreshed successfully at 06:00; the next existing validation
producer was the 09:30 daily chain. This ordering made the 07:05 launch non-countable despite fresh
capture and current market configuration.

An independent live validation for `2026-08-14` passed **12/12 markets with zero issues**. On the
next maker tick, preflight changed to `PASS` and the run counted toward live-forward evidence. It
still had **zero quote-permission rows, zero open orders, and zero fills** because policy found no
executable edge; no risk or evidence gate was weakened. The durable location-refresh wrapper now
runs that independent live validation after regenerating configuration and refuses task success
unless the receipt is readable, dated to the same local target date, and `PASS`.

## 8n. The bounded International Stage 2 successor is suite-proved, not integration-ready

**Immutable exact-tip suite measured 2026-08-14 07:12–07:21 local.** The refreshed Stage 2 branch
`codex/international-live-stage2-refresh-20260814` was clean at
`0994fa137b8d10c02f559fcbea5afe3d2dfd0a6a`. It records the obsolete Stage 2 lineage as a merge
parent, then replays only that branch's bounded-probe delta onto the exact-green refreshed Stage
0/1 parent `59e7bbfe9d9e47e88807a832238544c291e7c42a`. The immutable receipt has one start segment, one
terminal `ALL CHUNKS PASSED` verdict, **18/18 passing chunks and 4,539/4,539 passing tests**, with
zero failures, errors, or skips across 18 JUnit sidecars. All **19/19** preflight/chunk admissions
observed all three streak-critical capture workers healthy; peak recorded commit was **36.59%**
against the wrapper's 64% start and 66% abort ceilings. The task returned zero, the workload lease
was released, capture recovery passed for all three workers, and the spent task was disabled. The
receipt is `C:/Users/micha/ops/international-stage2-refresh-full-suite-20260814.log`; its JUnit run
tag is `20260814T071302`.

This proves software consistency and the bounded fail-closed implementation only. It does not
prove deployment dependencies, authenticated lifecycle authority, order acceptance, a fill,
fee or rebate receipt, realized P&L, or profitability. Stage 2 remains stacked on the unmerged
Stage 0/1 parent and remains roll-sensitive. Land that parent first; then merge current production
into Stage 2, run a fresh exact-tip suite for the combined tree, review the fixed-scope wrapper,
and use the guarded quiet-window path.

## 8o. Windows venv launchers require child-PID adoption for supervised public capture

**Initial supervisor proof and adoption measured 2026-08-14 07:38-07:50 local.** The clean
supervisor branch at `7a1da5328973e9fd564dc3a5ccbb723ba57ed259` passed one immutable
**17/17-chunk, 4,414/4,414-test** receipt with zero failures, errors, or skips. All **18/18**
preflight/chunk admissions observed the three core capture workers healthy; peak recorded commit
was **38.91%** against the **64%/66%** start/abort limits. The branch was mechanically roll-free
while the optional producer was unarmed, then merged and pushed to production.

The first real S4U/Limited, priority-7 ensure did not satisfy the process handshake and correctly
returned nonzero. Windows launched venv PID **13068**, whose direct base-interpreter child PID
**20736** owned both status and writer lock. The original handshake expected the launcher's PID,
terminated that exact launcher, refused adoption, and left the recurring task Disabled rather
than accepting mismatched provenance. The child subsequently exited; no order or credential path
was present. This was a lifecycle-provenance defect, not public evidence loss being waived.

**Repair proof measured 2026-08-14 07:57-08:07 local.** At exact repair tip
`a5359030318d2a8af64aab638e0f6f3a5afef313`, an isolated public-only run launched venv PID
**19380** and adopted direct child PID **5804** only after OS parent, complete command, distinct
creation tokens, worker/status/lock PIDs, and current loaded-source identity agreed. The child was
`CONNECTED`, evidence integrity was `PASS`, and its measured working set was **56.89 MiB**. The
official stop proved child exit and writer-lock removal; the launcher also exited. The same exact
tip then passed one immutable **18/18-chunk, 4,543/4,543-test** receipt with zero failures, errors,
or skips. All **19/19** admissions observed all three core workers healthy; peak recorded commit
was **38.96%** against the same ceilings.

The later repair line adds only the repository-owned post-merge adoption guard, its focused
ratchet, current production evidence, and two fail-closed cleanup hardenings. Final tip
`5ed4ff6979905eaa826d9ce97f457a142aadf454` is pushed and bound to a same-local-day full reproof,
suite-gated quiet merge, and guarded adoption on 2026-08-15. Until those tasks pass, the
production supervisor remains Disabled. This evidence proves public producer lifecycle and
capture coexistence only. It does not prove a unique execution count, our fill, queue position,
fee, rebate, inventory, P&L, or profit; historical public gaps still make the current retained
price path unusable for economics.

**Final-tip pre-quiet reproof measured 2026-08-14 08:25-08:33 local.** The exact pushed final
tip `5ed4ff6979905eaa826d9ce97f457a142aadf454` passed one immutable **18/18-chunk,
4,544/4,544-test** receipt with zero failures, errors, or skips. All **19/19** admissions observed
the three core capture workers healthy; peak recorded commit was **36.49%** against the
**64%/66%** start/abort limits. The receipt had one start, one passing terminal verdict, eighteen
distinct JUnit files, and Task Scheduler result **0**; the heavyweight OS lease was released and
capture recovered at all three priorities. This closes final-tip regression risk before the
quiet window, but it does not replace the separately queued same-local-day reproof or any guarded
merge/adoption condition.

A final isolated S4U/Limited scheduler proof on tip `5ed4ff69` established that task priority
**7** propagated through both venv launcher layers: the long-running child reported
`BelowNormal`, matched status and lock at PID **4492**, retained evidence integrity `PASS`, and
used **57.11 MiB** working set. The official stop again proved process exit and lock removal. This
closes priority inheritance as an assumption; it still does not arm production ahead of the
guarded overnight chain.

---

## 8p. The current disk-days alarm measures a one-day burst, not an established steady rate

**Free-space trail audited 2026-08-14 08:50 local.** The status monitor correctly measured a
**24.4 GB** free-space reduction over its trailing **24-hour** reference, leaving **157.7 GB** and
therefore printing an approximately **6-day** linear extrapolation. Longer and shorter windows do
not support treating that slope as steady: the trailing **48 hours** lost **3.0 GB** net
(**1.5 GB/day**), while the trailing **8 hours** lost **1.0 GB** net (**3.0 GB/day**). The last two
hours did contain a separate **6.0 GB** burst while many immutable proofs and new worktrees were
active, but the trail alone does not assign causality.

The correct operational reading is a conservative burst warning, not a forecast that the disk
will actually fill in six days. Do not silence it: absolute headroom is currently ample, but the
off-host mirror is operator-paused and new capture remains single-disk evidence. Re-evaluate after
the proof burst ages out of both the short and 24-hour windows; investigate if the multi-window
slope converges upward or absolute free space approaches the monitor's fixed thresholds.

## 8q. The paper market-harvest route works; an end-of-day market is not a safe live candidate

**One-market forward proof measured 2026-08-15 18:34-18:35 local and independently audited.**
The clean exact branch tip `9f8915c4aa1a7ae210ddc3c85f3c8c50f4d0e925` collected a fresh
International economics v0.3 snapshot, then ran one Toronto `market_harvest` paper tick. The run
retained **11 quote-intent rows**, **2 quote-permission rows**, **4 two-sided paper lifecycle legs**,
and **0 live-permission rows**. Preflight passed. The fixed ceilings remained **25 pUSD** for the
run/daily loss and event notional, **10 pUSD** per band, and **120 seconds** TTL. The fill tape
retained the public-counterfactual and authoritative-account field boundary, but no real fill or
account evidence exists.

Candidate-plan v0.2 then correctly returned `BLOCK`: the only paper-proved midpoints were
**0.9985** and **0.002**, both outside its non-raisable **0.20-0.80** safety interval. It selected
no condition or token, authorized nothing, and named
`current_paper_proved_safe_fee_eligible_book_candidate` as missing. This is evidence that the
paper route is reachable and that current-market selection fails closed; it is not evidence of a
safe candidate, reward eligibility, a fill, a rebate, or profit. Do not weaken the midpoint gate to
turn a late-day market green. Select again from a fresh paper tick when a current market naturally
meets the existing interval.

The preserved receipt and independent audit are under
`C:/Users/micha/ops/live-test-parent-proof-0815c/`. The audit binds the run-script hash, exact local
and remote tip, Scheduler start/completion records, economics and candidate hashes, complete paper
tape hashes, risk ceilings, zero live permission, and the safe refusal. No baseline was accepted and
no secret or live-mutation path was used. This is a single operational proof, not a powered economic
endpoint; no interval or P&L claim is available.

---

## 8r. The Windows child-resource sampler retained fresh ctypes pointer types on every sample

**Measured 2026-08-16 10:29-10:38 local.** The healthy production snapshot
parent had run **2,866 iterations** since 2026-08-15 01:00 and held **5,864
MiB private / 4,808 MiB working set**, while its handle and thread counts
remained bounded and its latest iteration was clean. The other two core parents
from the same adoption held **709-736 MiB private**, which made the snapshot
parent the host's dominant memory consumer and reduced free physical memory to
about **3.6 GiB**.

The hot Windows sampler in `weather.operations.long_job_guard` declared two
new `ctypes.Structure` classes and their pointer prototypes on every resource
sample. CPython retains pointer classes in its process-wide cache. A disposable
**2,000-call** reproduction against the current process grew that cache from
**3 to 4,020 entries** (**+4,017**) after garbage collection. Moving the ABI
types and function prototypes to module scope made the same warmed repeated
sampler path hold the cache size constant in the regression test.

This establishes a real unbounded parent-retention mechanism and justifies the
fix. It does **not** attribute every byte in the live parent to that mechanism,
nor does a one-time restart prove the repair. Closure requires the exact-tip
suite, guarded production adoption, and a fresh-parent memory slope over real
capture iterations. Until then, the post-grade restart is only an operational
headroom mitigation.

## 8s. The cumulative International parent is integrated; the fixed-scope successor was never tested

**Measured 2026-08-19 from immutable suite, merge, task, and wake receipts.** Parent tip
`1f4fb14611fe94781323d2b2da43f057a6f7241e` passed **18/18 chunks and 4,489 tests** with zero
failures, errors, or skips. Its guarded merge recovered all three core capture workers, recorded
the documentation obligation, and published merge
`3c326ac1c03b415877da33dc254b39d32f576de4` through `WeatherOneShotPush`. This lands the paper
harvest route, official unified client, pUSD contract, and sampler repair. It proves software
consistency and adoption, not an order, candidate, fill, rebate, or profit.

The fixed-scope successor failure is an orchestration result, not a Stage 2 code result. Its focused
wrapper set a worktree `PYTHONPATH` but invoked Python from the production working directory, whose
root package bootstrap won resolution; import of successor-only `mm_live_stage2` failed before the
focused tests. The full suite therefore correctly refused and produced no suite log, and the merge,
continuous-observation task, and candidate all refused the absent ancestor. Running the same four
focused files from the exact worktree subsequently passed **73/73**, but that diagnostic is not an
immutable full-suite receipt and authorizes no merge.

The same night exposed a separate settlement-orchestration defect. The August 16 backfill settled
**12/12** markets from real `daily_summary` rows, then continued through unrelated downstream chain
work until its bounded teardown. Cleanup did not run, so stale lock files remained; the August 17
wrapper used bare file existence and refused. PID reuse then made PID-only stale-lock detection
unsafe. August 17 remains an explicit hole and will not self-heal in the next daily run.

## 8t. The fixed-scope International Stage 0/1 stack is production-adopted, not live-proven

**Measured 2026-08-23 from immutable attempt, suite, and merge receipts.** Exact source tip
`a6327ccf52499ed8d9ab0c34580fcd013ca7f094` passed integration preflight and **19/19 bounded
chunks: 4,698 tests, zero failures, errors, or skips**. Attempt `stage1-readiness-0823-a2` then
published guarded merge `0af64ecf36287a8e88aa1f85cbfa2ff540adb03b`; its PASS receipt binds
source ancestry, `HEAD == master == origin/master`, all three core capture workers, and required
execution-tape recovery.

This lands the interrupt-cleanup path, repository-owned fixed-scope wrapper sealer, no-argument
fixed-session runner, and pinned process-local SDK overlay contract. The receipt's authority is
explicitly **`NO_CREDENTIAL_OR_LIVE_EXCHANGE_AUTHORITY`**: it neither read credential values nor
authorized an exchange mutation. No current safe candidate, authenticated Stage 0 bootstrap,
Stage 1 order/cancellation proof, fill, fee, rebate, position, settlement, P&L, or profit evidence
was created. Software adoption must not be reported as a live lifecycle result.

## 8u. The 2026-08-23 Codex incident was abandoned agent load, not a proven OOM

**Measured from session rollouts, executor records, Windows process telemetry,
event logs, and capture sidecars.** Four recursive commands yielded control
after 10–30 seconds while their JavaScript callers discarded the returned
executor session IDs. They actually continued for **64.592–120.296 seconds**.
The last ran `Get-ChildItem .. -Recurse` across every worktree and production
`data/` for **95.359 seconds**, about 65 seconds after its tool wrapper returned,
while three pytest commands overlapped.

From 14:11 through 14:36 the session launched **36 pytest, three compileall,
three py_compile, and four documentation-audit commands** inside the protected
window. Executor concurrency peaked at **four**, once through explicit
`Promise.all` and once through the unowned scan plus three pytest runs.

Windows NCSI lost Internet reachability on DNS-probe failure at 14:22.
Observation died at 14:37; fleet-wide CLOB and snapshot network timeouts began
at 14:38. The operator reset the unresponsive host and Windows booted at 14:53
with Kernel-Power 41/EventLog 6008 and no clean shutdown.

**Do not call this OOM.** The five-minute memory guard completed without its
1.5-GiB physical or 85%-commit warning, and Windows emitted no resource-
exhaustion event. The evidence also does not identify Codex as the cause of the
DNS failure. What is established is prohibited recursive and concurrent agent
load plus a contemporaneous network failure.

Two guards false-passed or could not act. The watchdog's 92% kill path was
unreachable because the 85% warning changed `action` before the action branch
tested for `none`; it also omitted pytest and non-Python Codex trees. After the
reset, boot recovery reported capture recovered from stale PID/lock/heartbeat
state without revalidating the OS process creation token or command, even
though CLOB never recovered. The repaired contracts use a one-minute OS
backstop, a user-layer Codex pre-tool hook, and PID-reuse-resistant boot proof;
see [the incident trace](codex-host-overload-2026-08-23.md).

## 8v. Guarded integration has no authorized bootstrap for a behind production master

**Workstation audit completed 2026-09-01 from exact Git/GitHub and repository
control-flow evidence.** GitHub `master` at `c932b54f8747df5cdefc4cc42f8454b6797f09ae`
strictly descends the accepted production checkout
`3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` by 26 commits. The published delta
does not change either tracked generated location-config blob. Nevertheless,
the canonical quiet merge and immutable-attempt creator intentionally require
local `master == origin/master` and refuse before hashing or journaling the
production working bytes.

A plain fast-forward is not a substitute: it does not stage the target, classify
the exact old-to-origin delta against live closures, prove capture recovery, or
close every interruption boundary. A staged fast-forward can avoid a push, but
the currently adopted boot script retains `reset --hard` fallbacks during the
first-use interval; adopting repaired boot bytes first requires prohibited
Scheduler rebinding. A synthetic guarded merge instead requires the real
credential-bearing one-shot push task. Under a mission that forbids both
dependencies, the truthful verdict is **NO-GO** and the equality refusal must
not be weakened. See
[the exact audit](../roadmap/agent-report-2026-09-07-workstation-production-baseline-reconciliation.md).

One additional trap is durable: `roll_verdict.ps1` changes its default base to
`origin/master` when local `master` is strictly behind. A future authorized
baseline repair must explicitly classify `-Base <old-local-sha> -Branch
<exact-origin-sha>`; otherwise it excludes the very catch-up delta being
adopted. Missing, stale, or unreadable live closure evidence remains
roll-sensitive.

## 8w. A fail-closed synthetic bootstrap exists only with explicit one-shot push authority

**Implementation candidate and static audit recorded 2026-09-01; production
remains unchanged and the first-adoption path is still NO-GO.**
The owner subsequently authorized one future use of the already-provisioned
`WeatherOneShotPush` task for the exact §8v incident. That resolves the task-
authority falsifier but does not authorize a fast-forward, Scheduler change,
generic retry, or any other baseline pair.

The adopted `3361520f...` boot script need not be changed. With local baseline
`L=3361520...` and published target `T=c932b54f...`, every precommit marker can
keep `baseline_commit=expected_baseline=L` and use `pre_merge_commit=T` as a
deliberately invalid reset sentinel. `L` is ancestral to `T`, but `T` is a
two-parent merge with non-config changes, so it cannot satisfy adopted boot's
validated one-parent config-child predicate. Reconciliation-specific phases
also avoid boot's legacy `preparing` mixed-reset branch. Without `MERGE_HEAD`,
boot refuses and preserves; with it, boot may try `merge --abort`, but both
marker-derived hard-reset fallbacks remain unreachable because the predicate is
false.

The real first parent is exposed only after an exact config-only child `C` of
`L`, affected-producer recovery, and a merge `M` with ordered parents `[C,T]`
are proved, together with a target-equivalent non-config tree and content-
addressed raw config snapshots. One atomic marker replacement then changes
`pre_merge_commit` to `C` in the existing
`merge_committed_unpublished` phase with the complete capture/execution proof.
At that point adopted boot's committed-recovery predicate is true and preserves
`M`. Every later marker replacement must retain the full predicate; a partial
postcommit marker would re-enable a hard reset and is forbidden.

This is implemented as the incident-bound
`production_baseline_reconciliation_v0.1` mode in
`scripts/ops/quiet_window_merge.ps1`. It requires the exact L/T endpoint trees
and config blobs, exact dirty paths, canonical origin, an isolated pinned
source tip/tree/self hash, pinned adopted dependencies, explicit
`roll_verdict.ps1 -Base L -Branch T`, 01:00-04:00 containment, the shared lease,
raw byte snapshots, exact capture recovery, documentation binding, and the
existing singleton zero-trigger push task. It atomically records
`push_invocation_attempted=true` before the sole task start; failure or missing
acknowledgement spends the invocation and cannot enter generic attempt resume.
Special failure reports use `reconciliation_merged_unpublished`; the exact
first `M` is `T` plus two configs and therefore cannot rely on this topic's
newer status/consumer guards to suppress adopted `T`'s ordinary push-retry
instruction. The distinct stage avoids the report-specific
`merged_unpushed` instruction, but adopted `T` also emits an earlier,
unconditional `origin/master..master` warning to run `WeatherOneShotPush`.
The scheduled `WeatherHostHealthWatchdog` delegates to that adopted status
script and republishes its warnings into the host-health state and morning
briefing. Thus a failed or uncertain sole invocation can automatically leave a
contradictory retry instruction. The topic-side status guard is correct defense
for later adoption, but it is absent from exact `M` and cannot make this first
run safe. Resolving that contradiction requires a newly reviewed topology or
authorized containment that preserves the exact-tree and no-Scheduler-mutation
contracts; operator prose alone is insufficient.
Windows explicitly bypasses the task XML `ExecutionTimeLimit` for on-demand
starts, so the mode separately persists a 15-minute containment deadline,
reserves one minute before 04:00, stops the cached exact task object if needed,
allows one stop retry, and requires repeated `Ready` plus stable runtime
information. Stop exhaustion, a late terminal proof, or an unresolved stop is
never PASS. This candidate bounds its poll sleeps and canonical Git child, but
the ScheduledTasks cmdlets themselves still execute synchronously in the parent
PowerShell process. A hung Start, Stop, Get, Info, or Export RPC can therefore
cross the persisted deadline or 04:00 before control returns. A safe successor
must isolate every Scheduler RPC in a killable, time-bounded helper that
re-resolves and revalidates the exact singleton, atomically journals before a
mutating call, treats a timed-out Start as spent, and never lets a Stop timeout
authorize another mutation. Until that is implemented and adversarially
exercised, the logical deadline is not an absolute wall-clock containment
proof. The
reviewed handoff must also exclude every concurrent manual invoker across the
final Ready/start boundary; the task has no per-start identity that could safely
resolve that race after it occurs.

The exact adopted-boot replay harness covers every sentinel/cutover boundary and
intercepts any `reset --hard`. Required Python verification must also run
through `workstation_heavy.ps1` on the assigned non-capture workstation; no
policy bypass is permitted. The dated report owns both remaining boundaries:
the adopted automated retry instruction and any verification gate that was not
admitted. There is no production command or handoff while either remains.

---

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
