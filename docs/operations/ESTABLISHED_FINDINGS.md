# Established Findings

Status: canonical **reference depth**. Written for LLM agents. **Do not read this file top to bottom.**

| | |
| --- | --- |
| **Owns** | The measured results of the agent correspondence under `docs/roadmap/` (handoffs and reports nobody can read in bulk): verdict, numbers, support, scope limits and source report for each finding. |
| **Read first instead** | [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md) — every conclusion in one screen, each linked to its section here. A cold agent reads the digest, not this file. |
| **Read a section here when** | you are about to cite a number, reopen a question, design a measurement, or change code that a finding constrains. Find the section id in the [section index](#section-index), then load only that section (`Grep` for `^## <id>\.` gives the line; `Read` from there). |
| **Do not use for** | current host or work state ([STATE_OF_PLAY.md](STATE_OF_PLAY.md)), invariants ([AGENT_CONTEXT.md](AGENT_CONTEXT.md)), claims that were withdrawn ([RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md)), the α budget ([CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md)). |

**How to use a section.**

- Sections are appended as results arrive; older sections are **not** rewritten. A section that a
  later result overtook carries a `SUPERSEDED` banner naming its replacement. Where a section and
  the digest disagree, the newer dated section wins and the digest must be fixed in the same change.
- Findings here are **measured results with dates and support**, not invariants. They are durable as
  *records* even when the world moves. `AGENT_CONTEXT.md` owns invariants; this file owns evidence.
- **Before citing any interval in a decision or report, re-verify it against the named source
  report.** Numbers here are for orientation and for stopping re-derivation, not for quoting as
  fresh measurements.
- Claims that were retracted, and traps that look true, live in
  [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md). **Read that file too.** Several of the
  costliest hours in this project were spent re-discovering something already known to be false.

## Section index

Ids are stable; headings are long, so search by id (`^## 1c\.`). Mission ids such as `-09-56a` are
sequence numbers, not calendar dates.

| Id | What the section establishes |
| --- | --- |
| **Objectives and owner decisions** | |
| 0 | Objective order: capture and settlement evidence, maker economics, then forecast |
| 0a | The point-in-time 21-field wall is real on the free tier; 12 of 21 fields are available, 9 are not (`-09-55a`) |
| 0b | Owner decision 2026-08-09: aim for a better model, not a qualified one; release machinery leaves the critical path (partly superseded) |
| 0c | Central goal: a better forecast from our own information, never by consuming the benchmark (MM ordering superseded) |
| 0d | The streak gates nothing on the critical path; countable date volume is what matters |
| **Model versus market** | |
| 1 | We do not beat the market; four legacy headline numbers retired |
| 1b | Five audit assumptions: primary objective unmeasurable, nowhere we win, gate stricter than economics, no executions on tape, gap decomposition |
| 1c | The gap is information, not calibration (`-09-56a`) |
| 1d | What the panel can certify: a floor set by 12 markets, not dates (`-09-57a`) |
| 1e | The point-in-time source stops 2026-06-23; the `-09-58a` null is blind, not precise |
| 1f | The tail is centre overconfidence and is predictable ex ante (`-09-59a`) |
| 1g | Where the loss is is not where the fix works; distribution reshaping closed (`-09-60a`) |
| 1h | The point-in-time field test is pre-registered and frozen (`-09-61a`) |
| 1i | α = 0.0025 is short on the thin tail; quantile amendment A1 (`-09-62a`) |
| 1j | Decision 10 closed unused; Gate 3 fired on a floor never served (`-09-63a`) |
| 1k | Missions `-09-64a`..`-09-78a`: instrument audit closed, `high_so_far` is not append-only, replay does not reproduce what was served, recovery thread closed unpowered |
| 1m | Workstation research lineage 2026-09-01..04 (unmerged): the eleven extra free PIT fields are tested and inconclusive three times, never harmful; provider history depth by field/year; no free v2 PIT source |
| 2 | The cool bias is real, seasonal-coverage caused, and not correctable at serve |
| 3 | The serving floor fix: the one shipped win |
| 4 | The model was feature-blind all day, fleet-wide; repaired; the repair did not move the gap |
| 4a-bis | The forecast archive is necessary but not sufficient for the retrain (`-09-50a`..`-09-53a`) |
| 4b | The forecast archive covers the wrong 52 days |
| 4c | No target-year row is ever in-sample |
| 4d | The severe tail is identifiable ex ante at band granularity |
| 4e | The gap does not vanish in-season |
| 4f | The free tier has the data but cannot express a point-in-time corpus |
| 4g | The retrain blocks on 14 cells; the floor of 18 is not a knob |
| **Method** | |
| 5 | Method rules binding on every measurement (crossed date × market clustering, power, denominators) |
| 6 | Training data is contaminated at fit time |
| 7 | Two independent retrain lanes exist; branch names mislead |
| 8 | The self-sizing gate defect |
| **Market making and execution evidence** | |
| 8b | The maker countable-day clock counts the wrong property |
| 8bb | The maker cannot quote market-centred at all under the promotion gate (`-09-48a`) |
| 8c | Public execution capture and own-account fills answer different questions; bounded pilot |
| 8h | Maker recovery outside the evidence window is non-countable waste |
| 8k | Historical maker legs need their own captured International economics |
| 8m | Target-date validation must precede the active-day maker launch |
| 8n, 8s, 8t | International Stage 0/1/2 software: suite-proved and adopted, not live-proven (see 10f for the 2026-09-06 test) |
| 8q | The paper market-harvest route works; an end-of-day market is not a safe live candidate |
| **Operations** | |
| 8d | A terminated scheduled wrapper can leave its governed child alive |
| 8e | Large live logs caused capture failure; bounded non-deleting rotation |
| 8f | Daily-roll launch decisions must be serialized |
| 8g | A DEAD status with a source closure is a tombstone |
| 8i | The temporary Windows Update block outlived its build window |
| 8j | A monitor must separate durable risk from preserved history |
| 8l | The snapshot fatal-gap repair is suite-proved, not live-timing-proved |
| 8o | Windows venv launchers need child-PID adoption |
| 8p | The disk-days alarm measured a one-day burst (superseded by 10b) |
| 8r | The Windows child-resource sampler leaked ctypes pointer types |
| 8u | The 2026-08-23 Codex incident was abandoned agent load, not a proven OOM |
| 8v, 8w, 8x | Guarded integration bootstrap for a behind production master |
| 9 | Release #1 is not sufficient for promotion |
| **2026-09-19 measurements** | |
| 10a | Configured liquidity-reward pool: about 2,800 per day same-day, 4,800 all active; share unmeasured |
| 10b | Free disk is a daily sawtooth; the daily low binds |
| 10c | The venue's declared resolution source moved from WU to `weather.gov` timeseries; band agreement measured |
| 10d | Settlement-chain design facts: single-shot, gated behind a learning-lane audit, non-idempotent finalize |
| 10e | 13 of about 26 serving post-processing stages are no-ops since live WU inputs were disabled (code-traced) |
| 10f | The 2026-09-06 attended Stage 0/1 test ran off master; spent; grants nothing |
| 10g | The memory-guard kill path has been inert since 2026-08-23 |
| 10h | `-09-79a`: the gap starts in the morning; unused NBM guidance beats the served forecast there, and still trails the market |
| 10i | `-09-80a`: place-and-hold constraints — 10-15 s cancel-on-disconnect, the wallet falsifier, the evidence-minute budget |
| 10j | `-09-81a`: on every morning row the guidance lead halves; most guidance is dropped against the floor; 11 market clusters cap confirmation power |
| 10k | `-09-82a`: after the 13Z cycle the NBM parser reads tomorrow morning's minimum as today's maximum; a live shadow variant consumes the columns |
| 10l | `-09-83a`: the versioned parser repair is built (PARTIAL); production downloads the same national NBM bulletin ~49 times an hour |
| 10m | RE-1 live reward sessions 1-11: the reward model holds; empty bands fill |
| 10n | Open orders are limited to cash per market, not across markets |
| 10o | Weather takers pay fees and makers earn fee-funded rebates |
| 10p | `2026-09-111h`: NBM guidance at all hours (parser v2) does not carry the morning lead into the afternoon; the US all-hours route is closed |
| 10q | Model-parity swarm v2 (2026-10-04, development; landed by production 2026-10-04): two serving repairs on captured data close about half of the 111h table's gap (evening lock-in defect; morning v2 read); no external free source adds information; 13-16 residual |
| 10qq | WU's Toronto daily high counts the 00:00 local observation; the venue paid the with-midnight band on both discriminating days (n = 2; host read, 2026-10-13) |
| 10r | Desk-study power rule (2026-10-14, pre-registered, n = 4 pilot dates): N_req = 706 event dates, branch UNDECIDABLE_AT_DELTA; the 11-13 embargo end stands |
| 10s | Data layer v2 S0 measurement pack (workstation, 2026-10-15; inputs dated before 2026-09-30 only) |
| 10t | First counterfactual-tape toxicity fit (item 330 build 2, workstation, 2026-10-17): CF fills adverse at every horizon, settlement unresolved; DESCRIPTIVE, every cell UNDERPOWERED |
| 10u | HGB path: the intraday-tail and METAR-live-signal stages never act (code-traced + Toronto replay, 2026-10-21); the WU-floor residual is only data-inert |
| 10v | Dev replay with current code does not reproduce the served vector (M8 check, 2026-10-21, outcome-blind): code drift, not artifacts; replay deltas are "current code ± variant" |
| 10w | Open-Meteo hourly labels are fixed-offset per response; serving reads them as zone wall time, so labels on the far side of a DST change are 1 h late (code trace on master `1c19ae10b`, 2026-10-21; live behaviour inferred) |
| 10x | From the 2026-10-23 events the venue's declared resolution source is the raw aviationweather.gov METAR API, routine reports only (SPECI excluded), with a WU fallback; Denver names KDEN, not our KBKF (event metadata only; SPECI effect measured 07-31..09-29) |
| 10y | Free-source and blend levers (lane G, development, 2026-10-24): F1, F3, F4, G2-a and L4 add nothing over their no-source controls and none helps 07-12; F2 MRMS is a sub-bar 13-16 lead |
| 10z | R0 trained on the full year beats windowed R0 but loses to the floored forecast baselines by about 1 nat at 07-12 (lane L1, workstation, 2026-10-24); not adopted |
| 10aa | Lane L2 pooled residual model (2026-10-24/25): beats OLS + floor and the floored forecast on R0's rows and served on the dev window; pooling is the lever; still worse than the market |
| 10ab | Lanes L3 and L6 (2026-10-24/25): OLS + hard floor beats floored R0 and served, loses to MG-1 at 07-12; L6 own-obs twin beats it; upstream ASOS adds nothing |
| 10ac | Lane L9 ingredient ladder on OLS + hard floor (blocked LOYO 2021-25, weather-only, 2026-10-25): PIT NBM mean KEEP, cross-market pooling KEEP; overnight low, dewpoint and hour-pooled slopes KILL |
| 10ad | Lane L11 (2026-10-25): market blend w about 0 (MG-1 and P3d_N NOTHING, composite INCONCLUSIVE); dead-bucket mechanism closed fleet-wide under capture-time dating; P3d_N dev emitter is `last_in_hour` (about 6% of rows exposed) |
| 10ae | Lanes L3, L7, L8 (2026-10-24/25): loss atlas control PASS; option N analogue and A_N control; MG-2 pick = P3d_N; L8 binding v2 serve control PASS (unlanded) |
| 10af | Lane L2 rung ladder (2026-10-25, dev): R-A NULL vs MG-1, R-D blend WIN vs MG-1 superseded by R-F, R-F blends NULL, R-G STOP at gate 3b, R-I KILL (width lever closed for the NBM family), R-J KILL (trajectory family closed for the afternoon; HRRR hourly path excluded) |
| 10ag | Lane L2 (2026-10-25, descriptive): P3d_N receipt look-ahead worth +0.0004 Brier at 13-16, no MG-2 gate flips, pick survives; R-H market-relative atlas (selection evidence): 07-12 loss is winner-bucket mass, regime-flat |
| 10ah | Reads from 2026-10-24/25 recorded late (dev): L5 hot-day centre arms and AFD all KILL vs MG-1; L8 high_so_far parity KEEP vs base, not bound; L10 gap atlas has no cell at R <= 1; L11 stage C gross bound; no fresh pre-07-31 dates |
| 10ai | Before 10-23 the venue paid the WU band 626/626 (routine-only rule 617/626; 8 band flips 08-11..09-29, all SPECI effects): labels are WU before 10-23 and the venue rule from it (master ruling (10-25), reading B) |
| 10aj | Found defect 2026-10-26: the MG-2 "no production importer" test was vacuous (literal backspace bytes for `\b`); fixed in `e40804dfe`; control-byte ratchet approved (master ruling (10-25)), landing 10-26/27 |
| 10ak | Lane reads 2026-10-26 (dev): R-P KILL at gate 3 (a LOYO intercept win is bias correction, not information); R-PD and R-N CLOSED at 00-06 (gate 2 NULL); R-L STOPPED at gate 1a (NBS drops the day's TXN from ≥ 13Z cycles), R-L2 KILL at gate 3; R-R WIN at 07-12 vs L6, still worse than the market; R-S KILL at gate 2 (NBM-published spread closed) |
| 10al | Reads 2026-10-26/27: R-U CLOSED at P0 (HRRR 3x3 spread as width closed at all hours); C10 opened, not adopted; SM-H selected for MG-3 13-15 (h15 unresolved); CS-1 P3d_H 13-16 transfers, P3d_H 07-12 does not; R-V gate 2 (a) capture-proposal PASS, (b) KILL |

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

> **PARTLY SUPERSEDED — ordering only.** The 2026-08-13 maker-rebate pivot and the 2026-09-04 item-330
> refocus put maker economics ahead of model work; the owner paused new model-alpha work then and unpaused it on 2026-09-21.
> Current ordering: §0 and [item 330](../roadmap/items/item-330-maker-economics-refocus-master-plan.md).
> What stays binding from this section: release machinery is off the critical path, and
> leakage-free evaluation is not negotiable.

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

> **PARTLY SUPERSEDED — the "MM is downstream" bullet only.** Since 2026-08-13 the approved maker
> experiment is market-centred and does not wait for a model that beats the market (§0 objective 2,
> item 330). What stays binding: "better" means a better forecast **from our own information**, and a
> benchmark-consuming control is a diagnostic, never an improvement.

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

> **Input scale note, 2026-09-19 (§10a).** The grid's reward levels ($0, $0.20, $1.00 per band per
> day) were sized from the 2026-06-13 measurement. Configured per-band rates sampled on 2026-09-19 ran
> from 1 to 246 per day. The grid is not wrong; its reward axis stops far below the configured range,
> and what a capped quoter's **share** of a band's pool would be is unmeasured.

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
*forecast-model output at issue time*.** They were fetched and staged 2026-08-10 (§1e) and then
tested three times on the workstation research lineage (§1m): a pooled-refit replacement was adverse on the centre,
and an NWP-anchored residual challenger was **inconclusive and never harmful** at powers 0.06-0.39. They are
**tested, not resolved**; the spent evaluations may not be reused.

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

## 1k. Missions `-09-64a` to `-09-78a` — instrument audit, `high_so_far`, replay trust, recovery thread

Added 2026-09-19 from the repository reports; these results previously lived only in the reports,
three trace documents and a machine-local agent memory. Every entry is the report's own verdict.
Common support unless stated: the sealed pre-boundary panel, stratum **B** (23 dates, 12 markets, 204
market-days, 4,636 panel snapshots) and stratum **C** (27 dates, 12 markets, 320 market-days, 7,653
snapshots), never pooled. **None of these missions spent or allocated α: the ledger stays 7 of 20
spent, and decision 10 stays closed unused and is never reassigned.** Report paths are under
`docs/roadmap/`.

**Two thread-level conclusions, so nobody reopens them:**

1. **The instrument audit is closed and the gap is real** (`-09-64a`..`-09-68a`). Post-processing,
   the replay floor and the outcome labels were each checked as an explanation for trailing the
   market; none is.
2. **Historical replay does not reproduce what production served, and cannot be made to**
   (`-09-74a`..`-09-76a`). Never dispatch another historical-reproduction mission. The observation-
   recovery candidate that depended on it was then priced in one environment and found **unpowered**
   (`-09-78a`); that thread is closed with α kept.

### `-09-64a` — the blind-feature repair adds no realized-band zeros (precise null)

Repaired and control surfaces are identical row for row: **28 of 4,636** B snapshots and **1 of 7,653**
C snapshots put exactly 0.0 on the realized band, in both. No repair-only snapshot or market-day
exists. The repair inherited the zeros from the replay input; it did not create them. The zeros carry
2.60% (B) and 0.056% (C) of the reference gap `G = 0.021135322`. Limit: says nothing about whether
those rows were served as zeros (they were not — see `-09-65a`, `-09-66a`). Source:
`agent-report-2026-08-19-workstation-repair-zero-audit.md`.

### `-09-65a` — the panel has no floor column; the replay floor is rebuilt, not recorded

The retained paired panel carries no floor or `high_so_far` column, so no cross-host floor verdict
is possible from it. `feature_row` in replay is rebuilt later from captured sources
(`pooled_candidate_replay.py`, `_record_feature_row`), not the row serving used. Denver 2026-06-08
traced: replay rebuilt `high_so_far = 91` from `wu_current.max_since_7am_c` (yesterday's value before
dawn) against a current temperature of 68; production served 0.5206 on the band replay zeroed.
Source: `agent-report-2026-08-20-workstation-panel-floor-provenance.md`; trace
[REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md)
(raw floor above settled high on 7.478% of rows against 0.008% for the served floor; divergence is
81.132% of comparable B rows and 0.000% of C).

### `-09-66a` — re-scoring B on the served floor is cosmetic in the mean

B incumbent Brier moves 0.053379789 → 0.053290041; the gap to market shrinks by **0.5654%**, so 99.43%
of it remains and the B screens stand as run. Realized-band zeros fall 28 → 3. The floor changes
probabilities on 560 of 4,636 B snapshots (12.08%). C is byte-identical under the same intervention
(0 of 7,653 changed). Limit: exact deterministic census, no interval applies. "Cosmetic in the mean"
is not "safe in the extreme" — one row was enough to fire Gate 3. Source:
`agent-report-2026-08-21-workstation-b-served-floor-rescore.md`.

### `-09-67a` — the outcome labels are not the story

The incumbent-minus-market gap is flat across label-coverage buckets. C: 0.019948935 on clean
market-days, 0.023865217 with a gap under 30 minutes, 0.021818110 at 30 minutes or more;
material-minus-clean contrast **+0.001869 [−0.011748, +0.018514]** (crossed 95%). The market's own
Brier is flat too (+0.000116). The centre error on gapped days is cool, the opposite of a warm model
scored against an under-reading label. `snapshot_high` fallback labels occur only on four B dates (37
market-days); C is all `daily_summary`. Limit: resolution of this panel; bucket intervals are wide.
The diagnostic share of `G` attributable to the material bucket is 1.5069% **[−11.92%, +12.95%]**:
cite the interval's upper end (about 13%) as the ceiling on a label effect, never the point. Source:
`agent-report-2026-08-22-workstation-outcome-label-audit.md`.

### `-09-68a` — Gate 3 is a panel-size limit, not a quality bar

Only **two** B zeros are attributable to a floor actually served: Chicago 2026-06-14 (floor 70,
settled 69) and San Francisco 2026-06-09 (68, 67). The third (NYC 2026-06-22) has a blank served
floor. At 2 crossings in 204 market-days a fail-on-any-row gate fires with probability 62.66% at 100
market-days, **86.60% on the observed panel**, 99.27% at 500, whatever the candidate. **Never
re-register that gate unchanged**, never weaken the serving floor to pass it, never add epsilon mass.
Limit: independent-market-day plug-in projection; the crossed 95% interval on the rate is [0%,
4.04%]. Source: `agent-report-2026-08-23-workstation-gate-3-satisfiability.md`; trace
[GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md).
Related: the served realized-band zeros were a serialization defect that ended on 2026-06-15 with
commit `28d1c146` (8.486% of Fahrenheit rows before, 0.000% after; the pooled 1.017% straddles the
fix and must not be quoted) —
[SERVED_BAND_FLOOR_DEFECT_2026-08-10.md](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md).

### `-09-69a` — public execution-tape capture was built (implementation, not a measurement)

`weather.market.execution_tape_capture` and `execution_tape_store`: credential-free public websocket,
one append-only tape per market-day under `data/snapshots/<event_slug>/execution_tape/`, dedupe on
`transaction_hash`, explicit dark-gap accounting, status that cannot republish green from a stopped
counter. Sizing extrapolated to about 7 MB per day fleet-wide. §8c owns the evidence split and the
production pilot; [item 326](../roadmap/items/item-326-supervised-continuous-public-execution-tape.md)
owns status. Source: `agent-report-2026-08-24-workstation-execution-tape-capture.md`.

### `-09-70a` — `high_so_far` decreases are common, and in B they sit on the main decision path

`high_so_far` fell between consecutive admitted snapshots **906 times in B** (125 of 204 market-days)
and **1,284 times in C** (292 of 320). C is the narrow pre-dawn fallback (`M2_empty_history` 99.53%,
81.70% pre-dawn). B is not: `M5_cutoff_change` is 72.63% and **368 of 906 (40.62%)** fall in the
peak-heating or settlement window. Train/serve skew on this feature: serve-time value differs from the
archive-rebuilt training value on 9.74% of comparable B snapshots and 93.72% of C. Unexplained
residual 24 of 2,190 (1.10%). Limit: exact census of recorded features; measured only, nothing
changed. Source: `agent-report-2026-08-25-workstation-high-so-far-population.md`.

### `-09-71a` — the WU observation series is not append-only; the narrowing cutoff is a symptom

All **658 of 658** B `M5` events **narrowed** the cutoff (−1 hour in 655) and none widened. The live
model derives `cutoff_hour` from the latest retained WU observation minute, so when the vendor series
drops rows the input window slides backward. Raw-series loss lowered the old-cutoff maximum in 636 of
658 events; narrowing alone in 48. `M5`, `M3_rows_dropped` and the two `M1` rows are one defect. C's
two `M5` events widen and are station-series regressions; that label is misnamed for C. Limit: no
serving change was made or authorized. Source:
`agent-report-2026-08-26-workstation-cutoff-direction.md`.

### `-09-72a` — a point-in-time union envelope recovers the rows but is unsafe to serve

An append-only envelope repairs 748 of 906 B events, all 658 `M5`, all 78 `M3`, and all 368
decision-window events; it repairs 0 of 1,284 in C (predeclared null, exact). It also creates **55 new
above-settlement feature rows**, all San Francisco 2026-06-09, by freezing a transient 68 °F print
into the trusted floor (settled 67). The pre-registration frozen here is safety-blocked and not
executable. Use the complete workstation evidence root: a partial root yields 7 B dates, not 23.
Source: `agent-report-2026-08-27-workstation-observation-envelope.md`.

### `-09-73a` — a payload-observable recovery rule is floor-safe; α unallocated

Rule: trust every row in the current WU payload; recover a previously published row **only if the
current payload has no row at or after that row's local minute**. It repairs **744 of 906** B events
and **366 of 368** in the decision window, creates **zero** new above-settlement rows on all 28,254
replay-supported B snapshots, consumes no future snapshot, and reduces train/serve mismatches
(2,057 → 1,510 of 21,554). Both B `M1_restatement` labels were wrong (timestamp replacement, not
restatement), so **do not write a rule over the mechanism labels**; the `M5 ∪ M3` filter is post hoc
and not servable. Pre-registration
`observation-envelope-preregistration-2026-09-73a.json` is frozen, safety-cleared, **not executable,
α unallocated**. A repaired input is not evidence of a better forecast. Source:
`agent-report-2026-08-28-workstation-safe-recovery-rule.md`.

### `-09-74a` — the incumbent replay control failed; stopped before the candidate

On the first exactly bound runtime commit, 7 of 8 unchanged rows reproduced within L1 `1e-12`;
Toronto `20260617T000830-0400` missed by L1 **0.00702**, with identical captured sources and both
paths on HGB. Of the 163 control rows only 60.74% carry a runtime commit, across six model versions.
No candidate number was computed. This retires "the incumbent reproduces recorded output", which
rested on one Austin market-day at diagnostic grade. Source:
`agent-report-2026-08-29-workstation-repair-ceiling.md`.

### `-09-75a` — replay diverges on the decision stratum

Of the 368 decision-window events, 358 carry a runtime commit; replayed at that commit, **114 match
(31.84%) and 244 diverge**, in every market, both windows, and 8 of 10 commits; max L1 0.7728. All
358 captured model identities differ from their own commit tree, and one version label (`v0.5.10`)
covered 15 artifact hashes. 158 of the 244 failures have zero feature differences: it is the
environment binding, not the inputs. Limit: exact finite counts; whole-B commit-bound ceiling
16,143 of 28,254. Source: `agent-report-2026-08-30-workstation-replay-trust.md`; trace
[REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md).

### `-09-76a` — identity binding does not restore replay; we served bytes that were never committed

No decision-stratum identity resolves fully from reachable Git: across 178 refs and 17,348 blobs only
**89 of 413** captured file fingerprints match any blob. Partial identity trees match 105 of 358
(29.33%), rescuing zero commit-binding failures and losing nine matches. Exactly reconstructable
population: **0 of 368** decision rows and **111 of 28,254** whole-B rows. The production trace adds
the cause: files that fail to resolve are the most frequently edited (`model_features.py`, 36
commits, unresolved in 62 of 63 identities; `model_base.py`, 10 commits, resolves in 63 of 63), so
production served working-tree bytes that were never committed — a commit-discipline defect, not a
replay defect. Whether a stale loaded process explains individual rows is unidentifiable. Source:
`agent-report-2026-08-31-workstation-identity-binding.md`; trace
[REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md) §5.

### `-09-77a` — single-environment ceiling (its screen could not fail; superseded by `-09-78a`)

Both arms run under current `origin/master` on the same captured inputs, 368 B decision rows (11
dates, 12 markets, 66 market-days): the candidate changes 366 rows, mean L1 displacement 0.5879, 196
argmax changes; outcome-free "ceiling" mean 0.4720, upper bound 0.6423 against a detectable effect of
0.2164. **That statistic bounds the candidate's maximum cost, not its benefit, and is non-negative by
construction, so the NO-GO branch was unreachable.** It answers what the rule does today, not what
would have been served. Source:
`agent-report-2026-09-01-workstation-repair-ceiling-single-environment.md`.

### `-09-78a` — the look is not powered; thread closed, α kept

On the actual estimand (paired Brier improvement), under the premise most generous to the candidate
the crossed SE is **0.0397607**, giving an 80%-power MDE of **0.15711** against a candidate-favourable
mean of **+0.13852**: NO-GO. Under the incumbent-calibrated premise the sign is negative (harm) and it
is also NO-GO (SE 0.0454453, MDE 0.17958). The 12-market canonical floor (0.04513) is not what binds
here. The repair sharpens **254 of 368** rows on a project where global sharpening is retired, and the
candidate must be the closer arm on at least 57 rows for a positive mean. Both decision branches were
proved reachable before the data was read. Limit: B decision stratum only, 11 date clusters; no
outcome, label or market price was read. Source:
`agent-report-2026-09-02-workstation-estimand-power-and-sign.md`.

---

## 1m. THE ELEVEN EXTRA FREE PIT FIELDS ARE TESTED, NOT UNTESTED — workstation research lineage, 2026-09-01..04 (unmerged)

Recorded 2026-09-25 from branch-only reports (model-lanes audit "Missing paths" 2; numbers re-checked against the reports by
the production agent). These research ids collide with later production missions of the same numbers: cite them as
`research 2026-09-NNx` with the branch. The lineage branches from master at `c932b54f8` (2026-08-31); no commit below is on
master. All results are point-forecast research on the workstation: nothing promoted, served, released, or allocated α.
Crossed target-date × market pigeonhole bootstrap, 20,000 draws, percentile 95%, throughout.

### The corpora (research `2026-09-87a`, `2026-09-89a`; collected 2026-09-02)

Two Previous Runs corpora exist **only on the workstation**, each collected from a plan committed before the first provider
call and content-addressed:

| Corpus | Root (workstation) | Rows requested = normalized | Non-null / missing | Manifest SHA-256 |
| --- | --- | ---: | ---: | --- |
| 12 fields, leads 1-7, May 10-Aug 31, 2021-2025 (120 units) | `C:\Users\Michael\Documents\Codex\inputs\pit-12field-multiyear-2021-2025` | 13,789,440 | 5,975,424 / 7,814,016 | `d41bd21efb7a…` |
| 11 fields, Jan 1-May 9 and Sep 1-Dec 31, 2024-2025 (96 units) | `C:\Users\Michael\Documents\Codex\inputs\pit-11field-2024-2025-calendar-extension` | 11,154,528 | 10,682,595 / 471,933 | `501e5d0e22a0…` |

**Provider history depth is a field × year boundary:** `temperature_2m` is complete 2021-2025; the other ten fields exist for
2024-2025 only; `precipitation_probability` for 2025 only; the calendar extension's only gap is early January 2024. This
reconciles §4f (Toronto 2021: temperature only) with §0a (2026: 12 of 21). Both corpora carry
`HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`: research inputs only, not the production v2 PIT contract.

### The pooled-refit replacement challenger lost on the centre (research `2026-09-86a`, 2026-09-02)

Design frozen at `2b0057394` before any C outcome was opened; fit on in-season B (23 dates, 204 market-days); scored on C-pre
(27 dates, 320 market-days, 7,653 snapshots). The repository pooled-band classifier with the 12-field surface vs temperature only:

| C-pre endpoint | Point | Crossed 95% | Power |
| --- | ---: | ---: | ---: |
| Centre-SSE improvement | −1.341677301 | [−4.678093564, 1.065943194] | 0.148 |
| Brier delta (challenger − baseline) | −0.000555427 | [−0.004691350, 0.003748432] | 0.058 |

Four of six frozen conditions failed (San Francisco alone −15.70 SSE); verdict **`INCONCLUSIVE_UNDERPOWERED`**, and the frozen
rule forbids a second replication. The research baseline (Brier 0.0779) is not the served incumbent, so this says nothing about
serving. It was a research-only look on the sealed C-pre panel with no `CAMPAIGN_LEDGER.md` row (§1d counts looks; owner call).

### The residual information test is inconclusive three times and never harmful (research `2026-09-88a`, `2026-09-100h`, `2026-09-90a`)

Target = native settlement high − median NWP maximum anchor over leads 2-7; baseline = temperature-only features; challenger adds
the ten extra fields (median and SD across leads); two `HistGradientBoostingRegressor` fits; WU `row_count ≥ 18`.

| Test | Frozen before outcomes | Evaluate | Primary MSE improvement, C² [crossed 95%] | Power | Verdict |
| --- | --- | --- | ---: | ---: | --- |
| `88a` | `c9f41c5bc` | 2025 May-Aug, 1,365 md, 114 dates (train 2024 May-Aug) | **0.2751 [−0.0234, 0.6186]** | 0.389 | `INCONCLUSIVE_UNDERPOWERED` |
| `100h`, no refit | amendment `5d6c9c1f…` | 2026 pre 06-03..07-30 (694 md); post 07-31..08-09 (120 md) | pre 0.4191 [−0.0410, 0.9678]; post 0.3681 [−0.1542, 0.9501] | 0.374 / 0.259 | `EXTERNAL_DIRECTION_CONSISTENT` (directional; verdict unchanged) |
| `90a` | `5ce4a11a1` | 2025 Feb 1-May 9 + Sep-Dec, 2,624 md, 219 dates (train 2024 Feb-Dec) | **0.045130 [−0.242193, 0.355152]**; early −0.0767, late +0.1420 | 0.061 | `INCONCLUSIVE_UNDERPOWERED` |

Read together: the fleet MSE point is positive in four of five cohorts and never below zero, but no interval excludes zero and
the outside-window replication is an order of magnitude smaller with one adverse segment. **The fields carry no established
information and no established harm.** All three evaluations are spent; a further test needs a new independently pre-committed
design with more independent year support (2021-2023 are temperature-only). A reproduction-and-power preflight
(`codex/48h-residual-preflight-20260911` @ `cbaa7cf9f`) was built and never executed.

### The calendar-extension hours are fixed-offset, read as wall time: standard-time dates are shifted 1 h (audit 2026-10-21)

Open-Meteo returns one scalar `utc_offset_seconds` per response, the offset at **download** time. All 96 calendar-extension
units (downloaded 2026-09-02, daylight time) carry the daylight offset (New York/Toronto −14400, Chicago −18000, Denver
−21600, Los Angeles −25200) for every window, January and December included; Atlanta Nov 1-Dec 31 2024 is 1,464 labels, no
repeat. The collector (`previous_runs_research_collection.py` `_normalize_response`, 89a @ `7839340f2`, ~line 1320) never reads
the offset and writes the naive label as `target_datetime_local`; the 90a consumer (`calendar_residual_replication.py`
`load_feature_surfaces`, @ `e4d6588eb`, ~line 902) takes `datetime.fromisoformat(row[1])` as market wall time and feeds
`.date()` and `.hour` to 88a's `_summary_targets`. Traced, Atlanta lead 1: label `2024-12-10T07:00` (offset −14400, 61.8 °F)
is 11:00 UTC = 06:00 EST, but the consumer counts it as hour 7 (inside the 07-20 window), +1 h; control `2024-09-15T07:00`
is 07:00 EDT, shift 0. The shortwave peak sits on label 14:00 in December and in September, which confirms the fixed offset.

On standard-time dates every label is one hour ahead of local wall time: 97 of 335 frozen 90a training dates and 96 of 220
evaluation dates. Affected: the 07-20 and 09-18 hour-window summaries (true local 06-19 / 08-17) and the calendar-day
boundary (the day runs 23:00 the previous evening to 22:00). The daily max, total and CAPE/gust summaries, including the
temperature anchor, are robust except when the extreme falls in the edge hour. No cutoff or issue-time check reads these
hours. **So the `90a` result (+0.045130) was measured on a misaligned surface for those dates. It is not retracted; it is
unverified as an aligned measurement.** Not affected: the May-Aug corpus and `88a`/`100h`, whose dates are all daylight time
and match the download offset. Master's `forecast_history.local_valid_datetime` has the same `replace(tzinfo=…)` pattern;
it was not traced here.

### No free source satisfies the v2 point-in-time contract (research `2026-09-82a`, 2026-09-01)

**`NO_GO_PROVIDER_BOUND_AVAILABILITY_AND_PARITY`** from official documentation only (no provider called): NOAA GFS, ECMWF Open
Data and Open-Meteo (Previous Runs, Historical Forecast, Single Runs, `data_run`, Model Updates) document no immutable historical
per-artifact first-availability time, and none pairs a free 2021-2025 archive with a forward surface of equal 12-field hourly
semantics. Closed under the frozen contract; the only valid next input is provider-owned availability evidence.

### Evidence

Branch-only reports (filename dates are labels): `agent-report-2026-09-06-workstation-pit-v2-source-contract.md`
(`codex/workstation-pit-v2-source-contract-2026-09-82a` @ `2e20e59aa`); `agent-report-2026-09-10-workstation-12field-seasonal-challenger.md`
and `agent-report-2026-09-11-workstation-multiyear-pit-research-collection.md` (`codex/workstation-collect-multiyear-pit-research-2026-09-87a`
@ `3f3367b29`); `agent-report-2026-09-12-workstation-multiyear-nwp-residual.md` (`codex/workstation-multiyear-nwp-residual-2026-09-88a`
@ `798225bc2`); `agent-report-2026-09-04-workstation-multiyear-nwp-residual-external-completion.md` (100i publication branch @
`efaf8839f`); `agent-report-2026-09-13-workstation-calendar-extension.md` (`codex/workstation-collect-calendar-extension-2026-09-89a`
@ `7839340f2`); `agent-report-2026-09-14-workstation-calendar-residual-replication.md` (`codex/workstation-calendar-residual-replication-2026-09-90a`
@ `91fe352f0`). Run roots on the workstation under `C:\Users\Michael\Documents\github\weather\scratch\runs\` (existence today
UNVERIFIED). The lineage's own `item-330-model-bom-…` file collides with master's item 330: never merge it.

---

## 2. The cool bias is real and is not correctable at serve

**110g owner decision, 2026-09-25:** the global afternoon residual-centering
artifact now has `component.enabled=false`; production activation requires the
model reload in the [110g report](../roadmap/agent-report-2026-09-110g-disable-afternoon-centering.md).
Its retained contexts were fitted in-sample in June on a pipeline not served
since June 30. This disables the stage pending a separate measurement; it does
not establish an improvement and must never trigger a refit on its own output.

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
  **Update 2026-09-25:** a *research* corpus with May-August 2021-2025 (temperature all years; 11 further fields
  2024-2025) and a Jan-May 9 / Sep-Dec 2024-2025 extension exist on the workstation only (§1m); production `data/` is unchanged.

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
was being argued from memory. `weather.reporting.market.mm_countability_postmortem` then
reported it from the `preflight_remediation.json` every maker run writes (module deleted with the
retired paper maker on 2026-09-29; it remains in git history).

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

> **SUPERSEDED by §10b (2026-09-19).** This section's reading ("absolute headroom is currently ample")
> was true at 157.7 GB free on 2026-08-14 and is not true now. The durable part — one 24-hour slope is
> not a steady rate — survives; the replacement adds that free space is a daily sawtooth and the daily
> low is the number that binds.

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

> **LATER EVENT — read §10f.** This section is accurate for `master` as of 2026-08-23. An attended
> Stage 0/1 lifecycle test did run on 2026-09-06, from the portable PC on unmerged branch code. It is
> spent and grants nothing, and the code that ran is not the code this section describes.

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

## 8x. The self-adopting successor closes both first-adoption boundaries

**Workstation implementation and adversarial verification recorded 2026-09-01;
production remains unchanged.** The safe topology is no longer constrained to
`M=T+two configs`. Under the owner's narrow authorization, freeze a reviewed
safety tip `S` which strictly descends both published target `T` and reviewed
parent `a24cf0f41bf0b321c5c813820594c56198a58d1a`. Create the same exact
config-only child `C` of accepted local baseline `L`, then require the synthetic
merge to have ordered parents `[C,S]` and a tree equal to `S` plus only the two
captured production config contents. This preserves non-force ancestry through
`T<S<M` while adopting the safety patch on the first published merge.

The adopted patch makes status and its scheduled watchdog incident-aware.
Only a complete marker bound to current `M`, `L`, `S`, `C`, exact config/raw
snapshots, roll-verdict and documentation evidence, full dependency hashes,
clean worktree, immutable canonical origin, cached origin, and a bounded live
canonical query receives special treatment. Its strict parser rejects duplicate
or case-colliding keys in every bound JSON object, and an ordinary-mode relabel
cannot downgrade populated incident evidence. Before dispatch it reports guarded
ownership and forbids manual invocation. Once the exact Start request is
journaled, it reports publication pending/uncertain and forbids retry. Exact
local/cached/live acknowledgement suppresses the warning. Every stale,
malformed, unreadable/lookup-failed, incomplete, unrelated, or mismatched shape is
`incident_evidence_invalid`: preserve the marker and its bound evidence, obtain
reviewed recovery authority, and never manually invoke or retry
`WeatherOneShotPush`. Invalid evidence uses cached `origin/master`, not an
unfetched live SHA, to count unpushed commits; an unreadable comparison produces
a neutral warning rather than a false zero. The watchdog retains that no-retry
action.

The same patch makes PT15M/04:00 containment absolute with respect to Scheduler
RPCs. Reconciliation launches `production_baseline_scheduler_rpc.ps1` only in a
repository kill-on-close Job. Immediately before every RPC launch, the parent
re-hashes the helper against its exact `S`-pinned dependency SHA-256. The request
deadline is eight seconds before the applicable PT15M/04:00 boundary, leaving
five clamped seconds for `TerminateAndWait` proof and a further three seconds
for bounded result parsing. The helper re-resolves and fully attests the exact
task twice, uses only the final task object, and the parent independently
validates its structured result. Start is journaled first; immediately before
mutation an atomic fixed-path claim spends Start or the exact Stop ordinal.
After claim creation and durable flush, one immediate nonblocking deadline
recheck precedes the direct `InputObject` mutation. A deadline crossed during
the claim leaves authority spent/unknown and performs no Scheduler dispatch. A
claim collision, or any cmdlet throw once a durable claim exists, is
authority-claimed with dispatch unknown and spent, never a false no-dispatch;
replay and lost-result cases therefore fail closed. Any failed, lost, or
timed-out Start is permanently spent and cannot PASS or produce a published
marker even if exact publication is later observed.
Before the first Stop claim, every post-Start Scheduler read identity is bounded
to `pushContainmentStopAt`, preserving the complete 30-second mutation reserve;
a slow or hung read is killed before that edge. If a Stop identity or its budget
cannot be created, Stop authority is exhausted locally without recording a
false attempt or dispatch. No post-boundary marker is written, and the lease
plus read-only drain remains until exact terminal proof or the absolute report
boundary. Successful Stop calls remain capped at two, while a lost,
timed-out, or uncertain Stop is terminal non-PASS and is never retried. Closing
the Job terminates and proves the entire helper descendant tree, including a
hung cmdlet or helper-spawned child. No helper can register, edit, enable,
disable, delete, or replace a task. The parent recomputes absolute deadlines
immediately before waits; bounded capture/documentation Python and live-origin
Git use the same Job ownership. Mid-flight 04:00 crossings cannot authorize a
later mutation or extend rollback polling, and the final journal is followed by
another exact live-origin/local-ref proof before the Start helper launches.

This finding does not itself authorize production execution. The exact future
command, frozen `S` commit/tree/entry/dependency hashes, host-profile proof, and
all required gate receipts belong to the final branch's dated self-adopting
reconciliation handoff report. That report is a handback artifact, not part of
the safety tip adopted into the synthetic production merge.

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

## 10. 2026-09-19 measurements

From the read-only project audit of 2026-09-18/19 and the owner's 2026-09-19 statements. **Evidence
status:** the audit's own files are retained in the repository under
`docs/roadmap/audits/full-audit-2026-09-18/` (`AUDIT_FINDINGS.md`, `D3_REWARD_CEILING.md`,
`OWNER_DECISIONS.md`, `dimensions/*.md`); where a repository path or code line carries the fact it is cited first.
The audit executed nothing: every code finding is read and traced, none is reproduced. Caveats are
the sources' own.

### 10a. The configured liquidity-reward pool is about 2,800 per day same-day, not about 16

| | Configured pool per day |
| --- | ---: |
| Same-day events (12 events, 35–46 rewarded bands; 200 per event, 400 for NYC and Los Angeles) | **about 2,800** |
| T+1 events | about 1,200 |
| T+2 events (listed since 2026-08-29) | about 800 |
| **All active** | **about 4,800** (about 4,000 before 2026-08-29) |

Stable on **31 of 31 sampled days** between 2026-08-15 and 2026-09-19 (same-day 2,717–2,830; one
11-event day at 2,394). On 2026-09-19: 129 of 352 conditions rewarded, maximum distance 4.5 cents
everywhere, minimum size 100 shares on 26 same-day bands and 20 shares on the other 15 same-day bands
and every T+1/T+2 band; per-band rates 1 to 246 per day.

- **Evidence:** the project's own `exchange_economics_snapshot.json` — `data/backtest/` and the copy
  each maker daily roll saves under `data/mm_runs/<date>/<run>/` — field
  `markets[].liquidity_rewards.current_daily_rate_usdc` (the sum of `active_configs[].rate_per_day`
  from the venue's current-rewards endpoint), summed across markets. Host-local write-up:
  `docs/roadmap/audits/full-audit-2026-09-18/D3_REWARD_CEILING.md`.
- **Caveats, binding on any citation:** this is a **pool shared by all makers, not income**. It is
  split by Q-score share (size × closeness to the adjusted midpoint, sampled each minute; two-sided
  required outside 0.10–0.90; single-sided divided by 3 inside). **Our share is unmeasured.** No paid
  reward has ever been observed by this project (`actual_payout_evidence: false`), and the **unit of
  `rate_per_day` is unconfirmed by any paid epoch** — do not write it as dollars.
- **What it replaces:** the 2026-06-13 measurement of about $1 per event and about $16 per day fleet
  ([MARKET_MAKING_PLAN.md](../research/MARKET_MAKING_PLAN.md) Part 0), which was true for that date.
  The July `NOT_VIABLE_CURRENT_TRACK` report had only that figure as a scale and recorded the July
  allocation as `UNKNOWN_NOT_ZERO`; the §1b zero-edge grid's reward axis stops at $1 per band per day.
  Their inputs are stale, not their logic. The verdict's first leg — the smallest reward-qualifying
  two-sided size (20 shares, about 19.60 pUSD) does not fit the 10 pUSD per-band cap — is unchanged.
- **What it changes:** the binding unknown is no longer the size of the pool but **the share a capped
  quoter can win**, next to what resting quotes lose to informed flow. Item 330 owns both.

### 10b. Free disk is a daily sawtooth; the daily low is what binds

Free space on the production system volume bottoms at about 04:50 local, 10–13 GiB below the evening
reading, then the 05:00 order-book tiering job returns about 13 GiB. Measured troughs: 29.9 → 25.9 →
14.2 GiB (2026-09-15, -17, -18); live readings on 2026-09-19 were 11.21 GiB at 02:23 and 9.82 GiB at
02:57. The status monitor divided the **instantaneous** free space by a same-clock 24-hour slope
(`scripts/ops/status.ps1:1343-1348` on `master`), which reported about 4 days when the low was about
1.5–2.5 days from zero. Differing free-space figures quoted on one day (21, 18.5, 14.2, 11.3) are one
instrument at different sawtooth phases.

- **Consequences traced in code:** projection tiering skips a file unless free space is at least the
  source size plus 1 GiB although the gzip is about 1/23 of the source; archive and qualification
  lanes need a 50 GiB reserve; so every reclaim lane refuses exactly when it is needed. At audit time
  about 62 GiB was duplicate smudged model pickles in linked worktrees (175 of 200 worktrees,
  371,560 KiB each), every byte already in `.git/lfs/objects`; the durable rule is to create worktrees
  with `GIT_LFS_SKIP_SMUDGE=1`. What has since been reclaimed is current state, not a finding.
- **Caveats:** troughs are the auditors' readings of the free-space trail; the 2026-09-20 projection
  (0–2 GiB) was a forecast, not a measurement. A fix that reports the daily low is authored on
  `claude/audit-rollfree-fixes-20260919` and is **not adopted**. Current numbers:
  [STATE_OF_PLAY.md](STATE_OF_PLAY.md) and `status.ps1`, never this section.

- **Correction 2026-09-24:** the ~04:50 trough no longer holds. Every closed day's long CSV is already gzip, so the 05:00
  tiering reclaims nothing (09-23, 09-24); the large reclaim steps were System Restore shadow-copy purges (15.4 of 18.6 GB
  on 09-24, three restore points), which moved the low to the evening: **43.2 GiB at 21:50 on 09-23**. The owner capped
  shadow storage at 2 GB and disabled Windows Search on 09-24 (+12.3 GiB). Judge the band from the free-space trail's
  24-hour minimum, not a clock time ([storage plan](storage-plan-2026-09-23.md); host audit 2026-09-24).

### 10c. The venue's declared resolution source moved from WU to `weather.gov` timeseries

> **SUPERSEDED IN PART** for events dated 2026-10-23 onward by §10x (raw METAR API, routine reports only).

Around the **2026-08-23** event (verified in git history for Atlanta and Toronto) the venue's
`resolutionSource` for the 12 captured markets changed from Weather Underground to
`weather.gov/wrh/timeseries?site=<icao>`; same ICAO stations. In the working copy of
`config/location_market_events.json` on 2026-09-19, 103 of 119 active events name the NWS URL, 7 name
WU, 9 are null. **Measured band-level agreement between the WU-derived label and the venue's winning
band: 921 of 921 before the switch, 131 of 132 after** (the one divergence: Miami 2026-09-02, WU 89 °F
against a venue-paid 90–91 band — venue above WU, the floor-safe and label-unsafe direction).

- **Evidence:** `data/backtest/market_day_labels.csv` reconciliation statuses, counted by Grep;
  promotion countability already requires a venue `match` (`settlement_ledger.py`,
  `PROMOTION_RECONCILIATION_STATUSES`). Host-local write-up:
  `docs/roadmap/audits/full-audit-2026-09-18/dimensions/gap-settlement-truth-source.md`.
- **Caveats:** the post-switch sample is thin — 11 comparable dates; 156 of 288 post-switch
  market-days had no WU label and could not be compared. **Exact-degree agreement for the 11
  Fahrenheit markets is unmeasured.** Whether the venue's binding Rules text changed too is
  unverified; the Rules text is retained nowhere.
- **Update 2026-09-22:** a production ledger count (latest revision per market-day, `reconciliation_status`) gives
  **359 of 360** post-switch market-days (2026-08-23..09-21) matching at band level, all 360 labelled from WU daily
  summaries; the 156-day gap was backfilled. Mission `2026-09-86a` (`codex/settlement-truth-source-20260922` @
  `d53e280a7`, UNDECIDABLE for lack of a post-switch panel on the workstation) found free IEM METAR (routine + SPECI)
  reproduces 480/480 pre-switch WU degrees and 504/504 venue bands, and that current event Rules resolve on the WRH
  page's "Hourly Data" with a WU fallback. Post-switch exact-degree agreement remains unmeasured.
- **Update 2026-10-02 (foreign stations, [desk study](../research/foreign-settlement-desk-study-2026-10.md)):**
  "Hourly Data" applies to the **US markets only**. On the WRH page that view keeps only rows carrying
  sea-level pressure, which Synoptic's global METAR network lacks, so it is empty for every foreign station. The
  London, Paris, Seoul, Shanghai and Tokyo Rules resolve on the highest "Temp" reading "for all times" (metric),
  with a WU fallback; over 2026-09-20..29 the WRH max, the IEM METAR max and the venue band agreed 50/50 at exact
  degree. **Hong Kong resolves on HKO's Daily Extract "Absolute Daily Max" (0.1 °C) by truncation**: the venue
  paid `floor(value)` on 10/10 days, and half-up rounding would have mislabelled 4 (31.9 → 31, 32.5 → 32 twice,
  32.7 → 32). `config/locations.json` now records these blocks, and the release settlement-rules payload carries
  per-location `rounding` with `band_contract.location_rounding_overrides` (`hong-kong`: `whole_degree_floor`).
- **Open:** `MarketSpec` and the ledger hard-code WU, and the US entries in `locations.json` still name WU;
  no gate can detect a source change. Since 2026-10-02 the foreign WRH cities and Hong Kong declare their venue
  source in `locations.json`, but no adapter reads WRH or HKO yet.
- **Lowest temperature (2026-10-02 desk study):** Lowest-temperature markets resolve on the minimum of the hourly rows, which differs in band from the CLI minimum on 202/708 US station-days (28.5%) (branch `claude/lowest-temp-desk-study-20261002`, addendum A1).

### 10d. Settlement-chain design facts

These are properties of the code on `master`, traced, not run. They explain why a settlement hole
persists rather than heals.

1. **Single-shot.** One 09:30 trigger; each isolated step checks admission once; a DEFER raises and
   ends the run (`daily_refresh.py`); the persisted `resume_command` has no consumer; the WU restore
   fetches only yesterday. Nothing retries and nothing backfills. Every missed date needs an explicit
   backfill (`scripts/ops/settlement_backfill_one.ps1`, which verifies outcome, not exit code).
2. **Settlement sits behind a learning-lane audit.** `ingest_quality_gate` precedes
   `public_wu_settlement_restore` and `market_day_labels_finalize`
   (`src/weather/operations/daily_refresh_registry.py`, `STEP_REGISTRY`). Admission uses an error
   threshold of 1 where the capture supervisor's own threshold is 3, so one market's blip defers all 12.
3. **There is no disk gate on this path.** Proven deferrals were memory-commit admission (72.5% and
   91.4% against a 70% ceiling) and a degraded-capture reading. The 70–85% commit band is a silent
   dead zone: above the chain's ceiling, below the memory guard's warning.
4. **Finalize re-revises every historical market-day on every run.** The label hash includes the
   wall-clock `finalized_at_utc`, so the idempotent early return can never fire; folders run
   oldest-first and the labels CSV is written only at the end, so a teardown loses the new day.
5. **Evaluation consequence.** Unsettled dates silently leave every scorecard, and evaluators fall
   back to a tape-derived proxy label when the ledger has no row; the promotion path does not.

- **Caveats:** only 2 of the 10 dates unsettled at audit time have a proven cause, because the chain's
  status file is overwritten daily. The live commit limit had shrunk to about 22 GB; a dynamic pagefile
  on a nearly full volume is the **likely, unproven** mechanism, which would make low disk an indirect
  cause (see the matching entry in [RETRACTED_AND_FALSE_LEADS.md](RETRACTED_AND_FALSE_LEADS.md)).
  Write-ups: `docs/roadmap/audits/full-audit-2026-09-18/AUDIT_FINDINGS.md` §2.B and §6.2.

### 10e. 13 of about 26 serving post-processing stages are silent no-ops — CODE-TRACED, SERVED OUTPUT NOT READ

> **PARTLY SUPERSEDED by §10q:** for the late-day lock-in stages and the calibration
> taper, one real served payload has now been read (ATL 2026-09-20 23:55: lock-in no-op, calibration moved above-high mass
> 0.031 → 0.087), plus a production multi-payload read (27 closing snapshots, 11 markets x 3 dates 08-12/09-14/09-27, where the floor agrees with the market): the per-band change made by `late_day_lockin` is median 8.4e-9, max 1.2e-7, a no-op in all 27; mass above the running high is 0.276 served vs 0.002 market ([synthesis §12](../research/model-parity-swarm-2026-10-04/SYNTHESIS.md)), and their forecast consequence is measured (development) in §10q.

`src/weather/model/model_constants.py:19` sets `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False` (commit
`5735b573a`, 2026-06-30), with no environment override. `fetch_wu_history`, `fetch_wu_current` and
`fetch_weather_com_forecast` therefore raise immediately and every live capture since carries empty
`wu_history`, `wu_current` and `weather_forecast`. §4 records and repaired the **feature** consequence.
The **post-processing** consequence was never recorded: by code trace, 13 of about 26 serving stages —
including all five late-day lock-ins and the calibration taper — receive `None` inputs and do nothing.

- **Caveats:** traced through the call paths, **not confirmed from any served output**; the stage
  count is the auditor's. No alert-path monitor aggregates source, NaN-feature or model-kind
  degradation. Host-local write-up:
  `docs/roadmap/audits/full-audit-2026-09-18/dimensions/gap-what-production-serves.md`.
- **Do not act on this as a forecast finding** until one served stage snapshot has been read. (Model work was
  unpaused by the owner on 2026-09-21; the read-before-acting condition still stands.)

### 10f. The 2026-09-06 attended Stage 0/1 test ran off master; it is spent

An owner-attended International Stage 0/1 lifecycle test ran on 2026-09-06 from the portable
execution PC on unmerged branch code (`origin/codex/live-gate-provenance-20260831`, execution tip
`c6ee36147`; its record is on `origin/codex/stage1-pass-docs-20260906` at `8739902fe`). Nine attempt
namespaces, three real 0.005 pUSD post-only BUY orders, all cancelled, **zero fills**. It proves
plumbing on that code only, says nothing about economics, and **grants no authority today**.
[Item 67](../roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md) owns the
attempt ledger; [INTERNATIONAL_MM_LIVE_PILOT.md](INTERNATIONAL_MM_LIVE_PILOT.md) records what differed
from `master`'s documented controls.

### 10g. The memory-guard kill path has been inert since 2026-08-23

`scripts/ops/memory_commit_guard.ps1:200,205` assigns to `$pid`, which PowerShell resolves to the
read-only automatic `$PID`. The termination loop therefore inspects the guard's own process, logs a
creation-identity mismatch, and never reaches `Stop-Process`. Every tree kill the guard reports since
the change has been a no-op; its tests are substring assertions that execute nothing. Runtime
evidence: `memory_commit_guard.log` 2026-09-10 21:29 logs a three-member tree "terminated" with the
same pid three times. **Fix authored at `0b6d4f288` on `claude/audit-rollfree-fixes-20260919`, not
adopted as of 2026-09-19** — until it is, treat the guard as a warning device only, and expect it to
really terminate out-of-window agent process trees once it lands.

### 10h. Unused station guidance beats the served forecast in the morning, and still trails the market — `-09-79a`, 2026-09-21

Descriptive, on the served surface: 503 `promotion_countable` market-days (89,354 snapshots), target
dates 2026-08-01..09-19, strata split at 2026-08-23 and never pooled (239 / 264 market-days, 20 / 22
date clusters, 12 markets). Crossed date x market bootstrap, 2,000 draws. Values are before / from 08-23.

- **The gap is already there in the morning.** Served / market Brier ratio 06:00-09:59 local: 1.482
  [1.287, 1.749] / 1.440 [1.247, 1.654]; 13:00-16:59: 1.789 / 1.715. Share of signed excess at or after
  noon 54.7% / 50.1%. The gap widens intraday but does not start there.
- **Band probabilities read straight off the captured NBM percentiles — no fitted parameter — score
  better than the served model on matched morning snapshots:** raw −0.0123 [−0.0230, −0.0036] /
  −0.0152 [−0.0251, −0.0061] (218 / 239 market-days, 20 / 22 dates, 11 markets); with the observed floor
  −0.0147 [−0.0260, −0.0033] / −0.0148 [−0.0275, −0.0020] (149 / 166, 19 / 22, 9). Ratio to market 1.198 /
  1.177 raw and 1.217 / 1.148 floored: **not parity**. Earlier-date error kernels on point guidance:
  HRRR 1.308 / 1.251, NWS 1.429 / 1.372, Open-Meteo 1.516 / 1.456.
- **Settlement instrument and rounding are not the explanation:** our final captured station maximum
  differs from the settlement bucket on 2 / 239 and 2 / 264 market-days (upper bounds 3.35% / 3.41%); model
  mass below its own captured floor is zero throughout.
- A captured Atlanta row traced through the canonical selection and imputation path: 27 selected columns
  per cutoff, no NBM, NWS-grid or HRRR column; removing NBM changes no model input.
- **Caveats, binding:** the NBM read is conditional on guidance being present — fill is 24.6-38.3% of
  snapshots, none for Toronto (not captured: production's guidance capture is US-only, but the NBP, NBS and NBH
  bulletins and the HRRR grid all carry CYYZ; RF "Toronto has no NBM"), almost none after 10:00 local (and those rows score 0.16-0.18; cause
  untraced), and the feature builder writes NBM only when it is valid against the observed floor. Power
  at a 0.01 effect is 35-40% per stratum. Regime tags and the SPECI event study are unpowered (no tag
  above 27% power at OR = 2). Provider-to-ingestion latency is unmeasurable: all 89,271 observation
  payload rows lack a complete provider-time / first-seen pair. Historical active-artifact binding is
  unproved. No candidate was fitted and no α spent.
- Record: branch `codex/missing-information-checks-20260921` (ROLL-FREE by the repository tool),
  `docs/roadmap/agent-report-2026-09-79a-workstation-what-does-the-market-know-completion.md` and the
  aggregate JSON beside it. Successor: mission `2026-09-81a` pre-registers two zero-parameter morning
  candidates scored on every row.

### 10i. Place-and-hold constraints found by `-09-80a` — 2026-09-21

- **Venue cancel-on-disconnect is 10 s with a 5 s buffer, not one 5 s heartbeat interval.** The Stage 1
  lifecycle already accepts order disappearance only inside 10-15 s, and the 2026-09-06 run measured
  10.359 s. A held quote's primary end-of-session action must therefore be an explicit acknowledged
  cancel; the dead-man is a backstop with up to 15 s of residual exposure.
- **The 2026-09-06 wallet cannot satisfy master's isolated-wallet control:** the recorded cash readings
  (275.48, 447.01397, 489.60767 pUSD) fail the `<= 100` isolated branch in the real validators; a
  separately declared isolated wallet at 50 passes. Restoring isolation means a fresh dedicated wallet.
- **Three 45-minute sessions cannot reach the RE-1 floor of 180 visible two-sided minutes**; a
  place-and-hold build needs a dated RE-1A treatment addendum before its first order.
- Chaining two single-token Stage 1 probes is not place-and-hold: each adapter binds one token, clamps at
  10 pUSD and burns a single-use capability, and the lifecycle requires account-wide zero open orders.
- Record: branch `codex/stage2-hold-build-20260921` (PARTIAL / NO-GO; pure pricer and inert hash-bound
  envelope delivered, no execution path). Successor: mission `2026-09-80b`.

---

### 10j. Scored on every morning row the guidance lead halves; a confirmation is not affordable — `-09-81a`, 2026-09-21

Branch `codex/morning-guidance-candidate-20260921` @ `7edd82ebb`; pre-registration frozen at `e404f7fdc` and pushed
before the first score, unchanged afterwards (verified by the production agent from the commit history). Development
read on the 79a export, never a confirmation; no α spent; reservation file untouched.

- Two zero-parameter candidates, fallback to served where no complete valid NBM set with a floor exists. US, 06:00-09:59,
  458 market-days, 42 dates, 11 markets, pooled: C1 (NBM with floor) minus served **-0.006672 [-0.011525, -0.002373]**;
  C2 (fixed 50/50 pool) **-0.006326 [-0.009902, -0.003145]**; ratios to market 1.356 / 1.362, intervals above one. Both
  strata agree in sign. C1's gain is below the frozen half-of-79a threshold (0.00735 / 0.00738) in both strata: **the
  minimum-effect falsifier fired.** C2 minus C1 is indistinguishable from zero. The candidate changes 46.1% of US morning
  rows and one row in 10:00-12:59.
- The size is what dilution predicts (about 0.46 x the 79a matched gain): the per-row benefit held where guidance was
  usable, and the rest of the rows simply fell back to served.
- **Why guidance is missing (traced through the code and the retained rejection field):** the feature builder drops each
  NBM value that sits below the observed floor. US morning: 6,293 complete valid sets, 7,290 rows with an explicit
  floor-dropped field, 1 unexplained. All-market fill by local hour 72.7% / 60.2% / ~33% / ~6-7% at 06 / 07 / 08 / 09 and
  about zero afterwards; 16 of the 17 complete sets after 10:00 exist only because no floor was captured. 79a's matched
  result was therefore selected on physical validity. Never-fetched and wrong-target counts are **unavailable, not zero**:
  the export carries no payloads, issue times or chosen slots.
- **Confirmation planning:** at half the pooled development effect, 45 new dates give 22.4% (C1) / 36.2% (C2) power, and
  even unlimited dates give 37.0% / 43.1%, because the 11 market clusters keep their uncertainty however many dates are
  added. **Under the crossed date x market rule no improvement of this size can be confirmed at any length of season**;
  the plan would need an effect roughly twice as large. No reservation was proposed.
- Open question raised by the production review, not a finding: a rejection rate of about nine in ten at 09:00 local is
  hard to square with a correct forecast of today's maximum, and the parser's slot rule takes the first token of each
  bulletin group. Mission `2026-09-82a` tests against real bulletins whether some cycles return a night minimum or
  another day's value. No new candidate is scored until that is answered.

### 10k. After 13Z the NBM parser reads tomorrow morning's minimum as today's maximum — `-09-82a`, 2026-09-21

Branch `codex/nbm-target-trace-20260921` @ `2e8406366` (ROLL-FREE by the production tool). A trace against 12 public
NOAA NBP bulletins (2026-09-17..19, cycles 01Z/07Z/13Z/19Z, the 11 US settlement stations, 132 station blocks committed
as evidence). No score, no comparison with served or market, no candidate.

- **Convention (NOAA's NBP product key):** `TXN` values valid at 12Z are minima, values valid at 00Z are maxima; for
  mainland US stations the 00Z maximum belongs to the preceding local date. The pipe-separated groups are UTC dates:
  01Z and 07Z bulletins begin with a 00Z maximum, **13Z and 19Z bulletins begin with a lone 12Z minimum.** Magnitudes
  agree: maximum-token p50 sits a median +2 F from the observed maximum, minimum-token p50 +1 F from the observed minimum.
- **What the unchanged parser picks** (`_slot_index_for_target` takes the first token of a group and subtracts a day
  whatever its valid hour): for target = the local date, 33 of 33 right at 07Z and **33 of 33 wrong at 13Z and at 19Z**
  (66 wrong picks, 3 dates, 11 markets), each the next morning's minimum, median 15 F below the day's observed maximum.
  Target = tomorrow is right at every cycle. **A 13Z or 19Z bulletin contains no maximum for the current local date at
  all**, so the repair is to reject and use an older cycle, never to take the next token.
- **Confirmed live on production, 2026-09-21:** the 10:08 local Los Angeles snapshot recorded cycle `20260921T13Z` with
  `provider_update_time` 2026-09-22 12:00Z - a minimum. The event-day `forecast_payloads` manifests carry `cycle_key` and
  `provider_update_time` for every snapshot and the national bulletins are retained. **Exact census run on production
  2026-09-22 01:17 (14 target dates 2026-09-08..21, 168 event-days, 12 markets, 27,473 NBM rows):** every row whose cycle
  is 12Z, 13Z or 19Z chose a token valid at 12Z (a minimum) - 927 + 7,281 + 10,244 rows, zero exceptions (the 12Z rows
  are a `20260921T12Z`-keyed bulletin captured 13:17-13:36Z, before 13Z arrives) - and every 01Z/07Z row chose a
  00Z-valid token (a maximum) - 3,407 + 5,614 rows, zero exceptions. The minimum-picking cycles are 67% of all NBM
  rows, so that share of the captured NBM guidance was a wrong-period value before the floor. Limit: exact deterministic census
  of the manifests' chosen token; it does not say how many wrong-period values passed the floor into scored rows.
- **It explains the export:** on all 55,565 floor-dropped US rows the recorded representative value is a median 14 F
  below the settled maximum and 2.7 F above the next day's observed minimum; the loss of guidance moves west to east with
  the local hour at which 13Z becomes the newest cycle (06:00 Pacific ... 09:00 Eastern). Hours 00-05 differ: there a
  correct forecast loses only a low quantile to the floor. The handoff was wrong that the median is recoverable
  (p75-IQR gives p25, p90-spread gives p10; p50 was deleted on 54,863 rows).
- **Consequences for earlier reads:** the NBM rows that 79a and 81a scored were those that passed the floor, mostly 01Z
  and 07Z picks, i.e. genuine same-day maxima; those results stand as stated. "No guidance after 10:00" was a parser
  defect, not an absence of information. How many wrong-period values slipped past the floor into the scored rows is
  **not yet counted**.
- **Parity:** the served headline model selects no NBM column (§10h), but one tracked artifact does -
  `feature_model_hgb_f_pooled_v0_3.pkl` selects all 15 `nbm_prob_tmax_*` columns and is bound to the shadow variant
  `pooled_f_candidate_miami_current_fallback_v0_1` (not headline, promotion blocked, legacy-validation-quarantined),
  which wrote predicted rows on production on 2026-09-21. The agent therefore stopped before any fix, as its handoff
  required. Mission `2026-09-83a` builds the repair in place with a parser version and token provenance, replay of old
  bytes under the old rule, and the rule that a row counts as guidance only when its provenance says "maximum".

### 10l. The parser repair is built; production re-downloads the national bulletin on almost every pass — `-09-83a`, 2026-09-21

Branch `codex/nbm-target-fix-20260921` @ `e1b663938` (roll-sensitive; the workstation's roll verdict was UNDECIDABLE
for lack of live closure evidence, so production must run its own). Handback **PARTIAL**, stopped correctly.

- **Built and reviewed:** parser version 2 selects the single `TXN` token valid at 00Z whose 12Z window start and 00Z
  label fall on the target's station-local date (unambiguous for all 11 US stations, standard and daylight time),
  requires all seven rows, and otherwise returns unavailable (`target_max_not_in_cycle`); version 1 stays callable and
  replay dispatches on the recorded version. NOAA publishes complete `TXN` rows at 00/01/07/12/13/19Z (02Z and 18Z
  returned 404); 00/01/07Z carry the issue date's maximum, 12/13/19Z do not. **From 12Z onward the newest bulletin
  holding today's maximum is 07Z, so afternoon and evening guidance is 5 to 24 hours old by construction.** Version 1
  also marked a station available when its block had no `TXN` rows at all (PGUM); version 2 rejects it.
- **Two of the three blockers were errors in the production agent's handoff.** The manifest already records parser
  version, issue time and valid time, and the bytes are retained, so the other token fields are derivable by replay.
  The fetch budget assumed a two-hour bulletin cache that does not exist. The parity CLI's BLOCK is the expected result
  of its known-defect fixture (4 of 4 rediscovered, 0 unexpected).
- **Measured on production, 2026-09-21 00:00-15:00Z:** the fan-out scope is one supervisor iteration and markets fall
  due in different iterations, so 729 of 783 NBM manifest rows were distinct network downloads of the ~35 MB national
  bulletin (24.9 GB in 15 hours, about 49 downloads an hour) for six distinct files a day; every download found its
  bytes already in the shared payload store. Production captures NBM for the current local date only, so the repair
  itself adds no download. This waste predates the repair.
- **Open from review:** the four provenance columns were appended to the NBM feature list and so became selectable
  model inputs and source-gate features; they must be stored but not selectable. Version 2 can raise in the live path
  on a bad clock. Mission `2026-09-83b` fixes both (Part A) and adds truthful, fail-open reuse of an already-held
  cycle file (Part B, its own branch).
- **`-09-83b` handback (same day, PARTIAL on both parts, stopped correctly; code reviewed and accepted).** Part A
  (`codex/nbm-target-fix-20260921` @ `2e17ce0eb`): the four provenance columns are stored as diagnostics and the
  selectable NBM list is back to its 15 names; a bad capture clock yields an unavailable payload with a specific
  reason in the live path and still raises in replay; one manifest row plus the retained bytes reproduces the chosen
  token. On a healthy day every local hour in all four US timezones has a reachable bulletin (07Z from early morning
  on, up to 24 hours old late in the Pacific evening); if that one file is missing, evenings are unavailable rather
  than wrong. Part B (`codex/nbp-bulletin-reuse-20260921` @ `62e8ff044`): a create-only index of complete, verified
  cycle files; fixture probe 33 downloads to 1 over three passes of 11 markets, no extra retained text; fail-open on
  every index or storage error; 403/404 never indexed; reused rows record no network fetch and keep the original
  fetch time. Cost on a full-size bulletin is not yet measured. **Every remaining blocker was a file outside the
  mission's ownership** (tool inventory entry, the admission test's exact-name set, the storage-class registration),
  and the branches conflict with each other and with the unlanded research stack. Mission `2026-09-83c` grants that
  ownership and asks for three stacked, individually green integration branches.
- **Landing branch (2026-10-04, `codex/nbm-parser-v2-landing-20261004`, draft, not adopted):** the 83d layer-3
  branch (83a + 83b Parts A and B, with the 82a trace bound to v1) merged onto current master as one branch.
  **The 12Z/13Z/19Z rejection is correct.** On all 44 retained station blocks plus the 00Z/12Z controls, a
  bulletin issued at 12Z or later starts with D+1's 12Z minimum, and its first 00Z maximum is D+1's. The window
  for D opens at 12Z on D, so it is never published again
  ([contract](nbm-target-period-contract.md#why-12z-13z-and-19z-bulletins-carry-no-maximum-for-the-issue-date)).
  MG-1's "07Z all day" afternoon staleness is therefore structural to NBP. Fresher same-day guidance needs the
  NBH/NBS products. The v1-trained shadow is quarantined, not re-versioned: NBM inputs are masked when the parser
  regimes differ. Review also found and fixed a v1 replay regression: `live_only_fields` had dropped to 11 names.

### 10m. RE-1 live reward sessions 1-11 (2026-09-23/25): the reward model holds; empty bands fill — mission 92a

Owner-attended sessions on the testing wallet (sized treatment, 75 shares at ±1.5 c from session 4 on). Journal folders are
numbered by **attempt**: attempts 1-9 are sessions 1, 2, none (opening check refused), 3, 4, 5, 6, 7, 8.

- **The reward model is right in scale.** Minute-integrated modelled reward matched the venue's accrual records: session 1
  0.117 accrued vs `P_many`/`P_single` 0.105/0.125; session 4 increment 0.438 vs 0.352/0.447; session 5 0.376 vs 0.330/0.347.
  **UTC 2026-09-24 paid +2.13 pUSD** (owner-observed liquidity-reward credit ~00:00Z 09-25) against a sum of modelled
  `P_many` of about 2.03 over that day's sessions (0.352, 0.330, 0, 0.106, 0.872, 0.369): **k ≈ 1.05**, the first paid day;
  formal per-session verdicts from `collect-evidence` pending.
- **Competition arrives within minutes of our quote.** The selected share halved 2-4 minutes after posting in every
  session (Miami 95.4% -> 3.55%; Atlanta 63.1% -> 4.07%) while midpoints barely moved. An "empty" band at selection is
  empty only until we post; selection-time six-hour projections overstate reward by an order of magnitude.
- **Fills in sessions 1-8 came on the thinnest bands.** Four fills in sessions 1-8 (six minute-bearing attempts), at
  1.8, 12.3, 42.0 and 87.2 minutes, all at the quote price (three partial; Miami full but not through): 5.57 NO
  @0.48 (NYC), **75 YES @0.35 (Miami 90-91°F Sep 25; marked -8.5 c/share at +5 and +30 minutes, ~-6.4; the 00Z GFS
  published 36 minutes before)**, 18.41 NO @0.59, 10 NO @0.40; four distinct takers. Only Miami looks informed at short
  horizons; all four are held to settlement (~43.8 cost). On an empty band share is 100% at any size or distance, so 75
  shares at 1.5 c bought fill exposure for no extra reward.
- **Execution defects found live and fixed:** venue order reads trail posts and cancels by under a second (the SDK then
  fails to decode); one hung heartbeat at a 5 s cadence tripped the 8 s stale limit; a zero-byte-safe reconcile was needed
  for closed orders. Fixed on `codex/re1-wallet-200-20260923` through `6b5fde587`, which also carries the owner's selection
  amendment (local T+1/T+2 and at least max(75, size) displayed depth each side within max spread).
- **Session 9 (attempt 10, first under the depth rule, 2026-09-24):** a contested band (selected share 54%) ran 38 minutes
  with no fill and no requote, `P_many` 0.369 (~1 c/minute); it ended `exception` (RuntimeError) because the owner's
  deliberate manual test orders appeared on the account — correct refusal, generic label (to be named `foreign_open_order`).
  UTC 09-24 rewards reached ~1.99 before its last minutes.
- **Session 11 (attempt 12, depth rule, 2026-09-25 01:12-02:23Z):** contested Chicago 68-69°F Sep 25 band (selected share 0.56,
  ~14% at 20 min), 72 minutes, `P_many` 0.383, no requote; a burst of five taker trades then filled the YES leg in full (75 @0.43,
  32.25) and the session ended and cleaned up; positions read lagged the trades (empty at cleanup, 75 YES in the app). Four of the five trades printed
  at 0.43 and the fifth at 0.42, strictly through our price: RE-1's fifth fill and its only strictly-through one
  (campaign-root attempt 12 `terminal_trades`).
- **Settlements (owner portfolio, 2026-09-25 ~00:30Z):** Atlanta 72-73°F Sep 24 NO (18.41 @0.59) won, +7.54; NYC 66-67°F Sep 24
  NO (5.57 @0.48) won, +2.89; Chicago 68-69°F Sep 24 NO (10 @0.40) lost, -4.00 (the taker was right). Realized fills
  **+6.43**; Miami 90-91°F Sep 25 YES (75 @0.35) open, marked 0.44 (+6.75) after a -8.5 c short-horizon mark — short marks
  were not a reliable guide. Three binary outcomes are noise, not evidence that fills are benign.
- **Inventory decisions (2026-09-25 ~11:10 ET, owner-placed on the [positions review](../roadmap/audits/positions-review-2026-09-25.md)):**
  Miami 90-91°F Sep 25 YES **market-sold** into a bid that fell 0.23→0.18 in five minutes (every forecast 86-87°F, running high
  81°F; exact proceeds to reconcile from the wallet). Chicago 68-69°F Sep 25 YES: **resting maker sell 75 @0.37 GTC** (first S2 /
  Q-04 test; the bid side held only ~20 shares within 6 c). Neither earns rewards: `rewardsMinSize` was 100 on both same-day
  bands, above the 75-share lot. An open resting sell makes RE-1 refuse to start (`foreign_open_order`); cancel it first.
  Wallet reader (100a, first live read 12:20 ET): Miami fill confirmed **75 @0.18 as taker, 12.9465 received** (fee ~0.55 at
  0.05·p(1−p), consistent with EF §10o); lot result −13.30. The owner withdrew the Chicago sell unfilled; 75 YES held to settlement.
- **Reward terms change intraday (2026-09-25):** Chicago 68-69°F Sep 25 `rewards_min_size` read 100 (rate 73/day) at 15:01Z and
  **20** (rate 65-67/day) at ~17:05Z on both gamma and CLOB `/rewards/markets/<id>`. The "neither earns rewards" line above
  held only for the morning. CLOB `/rewards/markets` is authoritative (RE-1 reads it; 88a captures it per minute); read it at
  decision time, never from an earlier snapshot.
- **Realized net, restated from wallet balances (Q-22, 2026-10-09):** **−36.97 pUSD** = five lots −39.11 (NYC +2.90, Miami −13.30 after the owner's taker sale at 0.18 with fee 0.5535 = 0.05·p(1−p)·75, Atlanta +7.55, Chicago Sep 24 NO −4.00 and Chicago Sep 25 YES −32.25, the two Chicago payouts of 0 inferred from no credit with the cash path reconciling) plus the 09-24 reward +2.13; no rebates observed. Sources: `data/wallet_ledger` snapshots dated 09-25..09-29 only. It supersedes the earlier "+6.43", which covered three 09-24 lots only.
- **Caveats:** six cities, nine attempts, two trade dates — descriptive only, no inference.
  Evidence: `origin/codex/re1-campaign-analysis-20260924` @ `7f98359` (report and rebuild script), second-opinion audit
  `docs/roadmap/audits/second-opinion-audit-2026-09-24.md`, session-1 analysis 86c.

### 10n. Open orders are limited to cash per market, not across markets — owner replication, 2026-09-24

The venue's order-lifecycle documentation states `maxOrderSize = balance - sum(openOrderSize - filledAmount)` across open
orders. **In practice it is not enforced.** With 96.15 pUSD cash the owner placed resting buys totalling **299.00 across four
unrelated events** (Chicago 68-69°F Sep 25, 200 YES @0.36; Paris 29°C, 300 YES @0.27; Qingdao 22°C, 200 YES @0.37; Toronto
20°C, 400 YES @0.18; all "until cancelled", 0 filled), and earlier 167.80 in one negative-risk event; all were accepted. The
app's "Cash" is the on-chain wallet, which moves only when a fill settles.

- **Consequences:** reward capacity is bounded by resting size and the number of bands, not by cash; the binding risk
  becomes **simultaneous fills beyond cash**, whose venue handling (fill failure at match, order removal, account
  consequences) is **unmeasured** (Q-13). RE-1's reserve model (`size x (yes + no) <= min(wallet - 10, 75)`) is therefore a
  deliberate choice, not a venue constraint.
- **The rule (owner, years of platform use, 2026-09-24):** open limit orders **within one market** cannot exceed cash; orders in
  **different markets are not aggregated**. Every weather band (city, date, range) is its own market, so each band has its
  own cash-sized allowance; a two-sided quote on one band (YES and NO of the same market) must fit within cash. All six
  accepted test orders were in distinct markets and each below cash, consistent with this rule.
- **Caveats:** one account, one day; the behaviour when fills exceed balance is not observed, and
  unsettleable fills at scale may breach the venue's integrity rules (strategy re-audit 2026-09-24). The earlier review's "reserved at placement" conclusion is withdrawn (second-opinion audit record).

### 10o. Weather takers pay fees and makers earn fee-funded rebates — mission 95e, 2026-09-24

Retires the "taker fee 0, therefore maker rebates zero" reading of the 2026-09-20 public tape. All 418 active bands of the 12
configured daily-high families and Taipei carry the weather fee schedule: taker fee **`shares x 0.05 x p x (1 - p)`** pUSD
(1.25 pUSD per 100 shares at 0.50, 2.5% of notional), **maker fee zero**; the category was introduced 2026-03-30 and on-chain
taker charges are shown on every date 2026-09-20..24 for every family. Gamma configures a **25% weather maker-rebate
allocation**, paid daily in pUSD (1-dollar minimum) by filled maker liquidity weighted by the fee curve — a second revenue
stream distinct from liquidity rewards, not a guaranteed payment to us. Optional builder fees can add charges to either side.

- **Consequences:** fills now carry a rebate share as well as markout risk; our own taker exits would pay the fee; an informed
  taker pays ~1.25 c/share at mid to hit us. The earlier zeros were probably a missing field read as zero (the old evidence
  was not re-read).
- **Evidence:** `origin/codex/weather-fee-check-20260924` @ `64cd786c9` (fee schedule, changelog, dated on-chain samples);
  [fees](https://docs.polymarket.com/trading/fees), [maker rebates](https://docs.polymarket.com/programs/maker-rebates).

### 10p. Guidance at all hours does not carry into the afternoon; the US all-hours route is closed — `2026-09-111h`, 2026-10-03

Development reading under the frozen pre-registration
`docs/research/guidance-all-hours-preregistration-2026-09-29.md` (nothing fitted, no α, no reservation, no serving change).
Input: production Part 1 extract (parser v2 worktree `2e17ce0eb`, COMPLETE, 110,807 snapshot rows, 626 market-days, 11 US
markets, targets 2026-08-01..09-29; no row on or after the replay panel's 09-30), scored on the workstation with 81a's
candidate and statistics unchanged (crossed date x market bootstrap, 2,000 draws, seed 20260921, 95% intervals).

- **Positive control passed:** C1 on captured (v1) features, 06-09 local, targets to 09-19: −0.006891 [−0.011894, −0.002688],
  inside 81a's [−0.011525, −0.002373], so the stack reconciles with §10j.
- **Primary fails:** pooled all-hours C1 − served **−0.000924 [−0.006083, +0.003924]** against the twice-81a line −0.013344,
  descriptively and on the interval; strata of opposite sign (before −0.002613, from +0.000057). C2 − served −0.005112
  [−0.008164, −0.002370], also short.
- **Both falsifiers fire:** the afternoon is harmed - 13-16 **+0.005986 [+0.002282, +0.009941]**, 17-23 **+0.015495
  [+0.010079, +0.020989]**; the gain sits overnight and in the morning (about −0.0127 at 00-05, −0.0134 at 06-09) and the
  afternoon harm cancels it. Every cell is worse than the market (all-hours C1 / market Brier 1.741).
- **§10k census:** 81 of 7,031 eligible 06-09 rows (1.15%; 8 market-days, 8 dates, 4 markets) used a wrong-period minimum
  that passed the floor; none had an unknown or missing period.
- **Consequences:** the morning lead (§10h, §10j) stands; the stale overnight bulletin hurts once the day is under way. An
  hour-gated guidance candidate is the obvious next idea, but it was not computed and needs a new pre-registration on new
  dates; these results may not be used to choose its hours.
- **Evidence:** `codex/guidance-all-hours-analysis-20261003` @ `0206f4d1` (PR #183),
  `docs/roadmap/agent-report-2026-09-111h-guidance-all-hours.md`; extract on production `data\exports\nbm-guidance-111h`.

### 10q. Half of the 111h table's served-to-market gap is two serving repairs on captured data; no external free source adds information — model-parity swarm v2, 2026-10-04

> Reviewed and landed by the production agent 2026-10-04 (owner approved landing). Every number remains a development read.

**Every number is a development read.** The from stratum (2026-08-23..09-29) had already been read by 79a, 81a and 111h,
so it is not a holdout and nothing here is confirmation. Table: the §10p extract (110,807 snapshots, 626 market-days, 57
dates, 11 US markets, targets 08-01..09-29; 0 rows after 09-29), scored by a hash-pinned harness (one crossed date x market
bootstrap weight matrix, 2,000 draws; 81a floor mask on every candidate; served fallback on every row). On this table
served/market Brier is 1.77x pooled; that is not §1's 1.423246x (different panel; never mix). 26 hunters, 2 refuters per
lead family; **134 registered rule ids** are the multiplicity denominator. No serving, config, capture or reservation change
was made.

- **Ladder (no new source), from stratum, all rows:**

  | Block | served − market (ratio) | + evening lock-in restoration (r1) | + MG-1 morning read (r2) | r2 − market (ratio) | r2 share of gap closed |
  | --- | --- | --- | --- | --- | --- |
  | 00-05 | +0.0244 (1.43) | 0 | −0.0141 [−0.0234, −0.0067] 11/11 | +0.0102 (1.18) | 58% [37, 76] |
  | 06-09 | +0.0254 (1.45) | 0 | −0.0139 [−0.0229, −0.0063] 11/11 | +0.0114 (1.20) | 55% [33, 75] |
  | 10-12 | +0.0228 (1.44) | 0 | −0.0092 [−0.0164, −0.0027] 10/11 | +0.0137 (1.26) | 40% [15, 62] |
  | 13-16 | +0.0239 (1.84) | −0.0006 | −0.0002 [−0.0086, +0.0077] 2/11 | +0.0231 (1.81) | 4% [−36, 33] |
  | 17-23 | +0.0296 (not interpretable: market Brier ~0.0008) | **−0.0252 [−0.0350, −0.0174] 11/11** | +0.0018 | +0.0063 | 79% [63, 89] (r1 alone 85% [76, 92]) |
  | 00-16 | +0.0242 (1.49) | −0.0002 | **−0.0099 [−0.0177, −0.0034] 10/11** | +0.0141 (1.29) | 42% [19, 62] |
  | all | +0.0258 (1.73) | −0.0073 | −0.0066 | +0.0119 (1.34) | **54% [35, 70]** |

- **Evening (17-23) is a serving defect, not missing information.** The late-day lock-in stages read WU-only
  `history_max`, empty since 2026-06-30 (§10e), so lock-in strength is 0 and the calibration taper (S7) is untapered.
  Re-anchoring S1/S2 with production constants (a band-level emulation, not a replay) closes 85% of the 17-23 gap. The
  emulation used `max(history_max, guidance_floor)`; the **served rule is the v3 anchor** (owner decision 2026-10-05,
  PR #191). It is the observed same-day station high, with METAR keyed by observation time and before-07:00 readings
  included, and the D-1 report carried in by the M0 `reportTime` defect excluded. Once a late-day stage acts, no mass
  is left below the anchor bucket. `guidance_floor` itself was not a safe anchor: production's captured-input replay
  of the v2 rule found 679 rows where the new vector put more mass below the anchor than the old one (worst: austin
  2026-08-25 18:07, a carried 84.02 °F "00:00" row). **v3 replay** (production, closed dates <= 2026-09-29;
  development):
  - `floor_check` PASS, with 0 rows worse below the anchor.
  - 17-23 mean mass above the anchor fell 0.332 → 0.075.
  - The settled check found 0 v3-rule anchors with a settled bucket below the anchor. **Confirmed on one real served payload** (ATL 2026-09-20 23:55:
  lock-in no-op; calibration moved above-high mass 0.031 → 0.087), and by a production multi-payload read (27 closing snapshots, 11 markets x 3 dates 08-12/09-14/09-27, where the floor agrees with the market): the per-band change made by `late_day_lockin` is median 8.4e-9, max 1.2e-7, a no-op in all 27; mass above the running high is 0.276 served vs 0.002 market ([synthesis §12](../research/model-parity-swarm-2026-10-04/SYNTHESIS.md)); together these meet §10e's read-before-acting condition for
  these stages. An independent re-implementation (T27) reproduces the rung to 7e-6 and it clears Bonferroni at the full
  registry count. The taper reads the same lock-in strength (`model_distribution.py:544`), so the restored strength
  must reach it; an extra S7 gate is optional (−0.00008 at 17-23). Every 17-23 "lead" from the remaining-rise / decided-band family (T1-T4, T15, T16 and the 17-23 legs of
  T5-T10) is this mechanism: an unconditional collapse with no input does at least as well. **Cosmetic for the maker**
  (the market already knows the high is in); it removes Brier loss that never moved a quote.
- **Morning (00-12): served under-uses the NBM v2 guidance it already captures.** MG-1 (v2_mean, sigma = max(v2_stddev, 1),
  floored, zero parameters, no hour gate) 00-16 −0.0100 [−0.0179, −0.0035], 10/11, before stratum −0.0122. This is the
  known §10h/§10j/§10p family, not a discovery; §10j's power cap (11 market clusters, about 40% crossed power) applies. It
  depends on landing the 83a/83b parser repair (§10k, §10l): production's v1 parser reads a minimum as today's maximum on 75,049 of
  110,807 rows. The fitted forms (T18 EMOS, frozen RV-1) differ from MG-1 by spread modelling on captured v2, not by a source
  (RV-1 − MG-1 00-16 −0.0034 [−0.0078, +0.0007]).
- **No external free source adds information beyond captured data plus those two repairs:** NBH, NBS, MOS/NBE, Open-Meteo
  Single-Runs HRRR (latest and time-lagged), ECMWF IFS, 12Z soundings, NWS revision direction, neighbour stations,
  METAR/GOES cloud. NBH's 00-16 increment over MG-1 is +0.0027 [−0.0037, +0.0098] (5/11, wrong sign); v2_mean carries 137%
  of T5's 00-16 gain. The one borderline sign (MOS/NBE t7-r2 at 13-14, −0.0063 over r2) is a post-hoc hour slice and not an
  increment over the remaining-rise rung (−0.0031 [−0.0077, +0.0017]).
- **Residual after both repairs is largest in the registered 13-16 block:** +0.0231 [+0.0173, +0.0289], 1.81x (the POST-HOC
  15-16 slice reads +0.0270, 2.53x). Re-anchoring the 13-19 h lock-in stages S3-S5 recovers only −0.0020 (−0.0032 at
  15-16; 58% of 15-16 snapshots have not rolled over below the high: a remaining-rise problem, under a declared forecast
  proxy). The no-source METAR remaining-rise rung t3-r3 (station x month x local-hour pmf of final max − running max from
  IEM history to 2026-07-31) beats served at 13-16 by −0.0116 [−0.0190, −0.0052], 10/11, and r2 by −0.0107, 11/11, but is
  **fragile**: WEAK at +1 h METAR staleness, NULL at +2 h, and fails family-wise (z −3.26). The 15-16 "−0.0181 over r2" is
  post-hoc twice and 0.0068 of it is MG-1's own 15-16 harm. A new rule; it can only enter through a pre-registration on
  new dates.
- **No candidate reaches market parity in 00-16.** Serveable without a new rule: 1.29x. Best composed (POST-HOC r2 x t3-r3):
  1.245x. Nothing tested closes the 00-12 residual (+0.010 to +0.014).
- **T1 (decided-band collapse) is subsumed, not drafted.** Serving-stage form: after the final calibrated distribution,
  when local time is past sunset or (hour >= 15 and the latest routine METAR is >= 1 °F below the METAR running max), bands
  1-3 °F above the floor band B keep a historical residual rate q(k) and the rest of the mass above B moves into B. Floor
  interaction: the 81a mask (max of `guidance_physical_floor`, `high_so_far`, `trusted_current_max`; B = round_half_up)
  is lower-side, T1 upper-side; both act on B, never conflict, and never weaken the floor. Inserted before calibration it
  needs an S7 gate (it does not feed the taper). 17-23 −0.0264, but the unconditional collapse scores −0.0287 and the restored lock-in −0.0254: the
  "decided" condition carries none of the effect.
- **Tail lens, this table's definition:** band rows with served SE > market SE and |p_served − p_market| >= 0.30 are
  **6.075% of rows carrying 70.38% of the positive excess**. §1/§1f's **4.387% / 64.140%** is the sealed in-season panel's
  figure; the difference is expected and does not change §1. Per-market tail sign cannot rank candidates here (98 of 99
  candidate vectors improve the tail); the separating quantity is the non-tail cost (MG-1 about −27% of the 00-16 tail
  excess vs about −6% for the history-fitted spread forms).
- **Defects found:** **M0** — production keyed METAR rows by AWC `reportTime` (nominal hour) until `metar-parser-v4`
  landed on 2026-10-09 (`6ad52c89f`), so a 23:5x report entered the next day's running max; confirmed on the captured floor at KLGA 2026-09-19 and KMIA 2026-08-29 (on KMIA every floored
  candidate gave the winner 0 all day); 0.3-0.6% of station-days Aug-Sep, 2.2% Oct-Dec, up to 5.4% at KLGA; fix = key on
  `obsTime` (parse-only, versioned). `trusted_current_max` is null on 100% of extract rows. 31 rows carry a captured floor
  10 °F above the METAR max. Late S3 NBM uploads are upstream delays plus one transfer backlog, not re-uploads.
- **Bonferroni** (134 rules x 7 block groups, z about 4.04): passes for the 17-23 family, T18 00-16, RV-1 00-16 and t7-r2
  00-16 (about 90% captured v2); fails for MG-1 00-16, r2 all hours, t3-r3 13-16 and the POST-HOC composite. MG-1 survives
  its statistics refuter on resampling robustness (W, date, market, LOMO, LOWO), not on multiplicity. Passing makes a
  result worth a pre-registration, not established.
- **Consequences (owner decisions 2026-10-04, [DECISION_LOG](DECISION_LOG.md)):** the evening lock-in fix is approved and
  built (PR #191, re-anchored on the v3 same-day observed high, owner decision 2026-10-05, so the restored strength
  reaches the S7 taper), with a
  production captured-input replay and then a quiet-window landing; the parser v2 landing is approved (PR #190), and its
  12Z/13Z/19Z rejection was verified correct; MG-1 is SIGNED at `b044e0f1`, with a narrow-scope reservation
  ([reserved-confirmation-window.md](reserved-confirmation-window.md)); RV-1, t3-r3 and HG-1 are held until the evening fix
  is live; NBH-1 is declined; the M0 fix is built (PR #189), plus the DST fetch-window fix (item I). **There is no capture
  case for any new source.** Landed since: v3 on 2026-10-06; the M0 fix (#189, `metar-parser-v4`) with lockin-anchor-v4
  (#246, the same-day METAR floor before lock-in, `ML_MODEL_VERSION` v0.5.12) on 2026-10-09 (`6ad52c89f`).
- **Evidence:** [synthesis](../research/model-parity-swarm-2026-10-04/SYNTHESIS.md) and per-agent reports in
  `docs/research/model-parity-swarm-2026-10-04/`; harness `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`;
  scores and acquired data on the workstation only (`C:\swarm\`).

### 10qq. WU's Toronto daily high counts the 00:00 local observation; the venue paid the with-midnight band on both discriminating days (n = 2) — host read, 2026-10-13

Read by the master agent on the capture host for [item 337](../roadmap/items/item-337-no-metar-observed-floor-gap.md);
pre-embargo dates only (nothing from 2026-09-30 on).

- **WU day files:** the CYYZ raw WU day files hold 24 observations, 00:00-23:00 local, so the 00:00 reading is inside
  day D's history.
- **The three B-replay rows do not discriminate:** settled highs 09-06 = 22 (max at 13h), 09-21 = 15 (00:00 ties
  14-17h), 09-26 = 23 (14-15h); all reconcile with the Polymarket outcome under either reading.
- **Discriminating days:** of Toronto raw days 2025-01-01..2026-09-29, 23 had the maximum only at 00:00; 2 have
  settlement rows. 2026-06-14: 24 with midnight, 23 without; resolved 24. 2026-08-02: 24 with, 22 without; resolved 24.
- **Independence:** our `settlement_high` comes from `daily_summary` and would agree by construction; the Polymarket
  closed-market winner is the independent check: **with-midnight 2, without 0.**
- **Consequence:** an observed hour-0 same-day high is consistent with venue settlement as a floor, on n = 2 with no
  counterexample. It is evidence for the owner's hedge-vs-floor decision on item 337, not a decision; the host
  `--with-no-metar-arm` replay over 2026-08-25..09-29 is still open.

### 10r. The maker-P&L desk study is not powerable at delta = 1.0: N_req = 706 event dates from a 4-date pilot — power rule #263, 2026-10-14

Pre-registered computation, run once: `docs/research/maker-pnl-adverse-selection-preregistration-2026-10-01.md`
(frozen at `574f8369b`, lines 118-133) with Clarification 1 point 3 (`67e44273b`), on the owner's 2026-10-07 instruction
to run the power rule now (DECISION_LOG 2026-10-07). Input: the 88a variance pilot only (UTC days 2026-09-25..09-29,
event dates 2026-09-26..09-29; the script refuses any later date) and the 12 settlement ledgers. Nothing fitted, no α,
no panel read. Source: host run by master-agent 2026-10-14 03:09-03:11 EDT, head `69af7d613` (`claude/desk-study-power-rule-r2-20261014`, draft PR #283), result_sha256 `e4061d78aeb254680e63d1e7962c4f43b63b44ef6afd8bb32fab2d264268efae`; output `C:\tmp\pwr-20261014\results\power-rule.json` on the capture host.

- **Inputs read:** dry run 311,061,393 bytes, 121 sealed segments, no missing day, all 12 ledgers present.
- **Result (verbatim):** n = 4 date clusters; sigma_d = 4.713343445231315 pUSD per band-day (sample SD of the date-mean
  NP_S); c = 0.5843743741551835 (the 0.10 lower-tail chi-square quantile, 3 df; a fixed function of n);
  sigma_up = 10.679333086154092; delta = 1.0 pUSD per band-day (fixed in the pre-registration, not from the pilot);
  **N_req = 706**; branch **UNDECIDABLE_AT_DELTA** (N_req > 28); decision **EMBARGO_END_UNCHANGED**.
- **Caveat:** sigma_up is the one-sided 90% upper bound on sigma from 4 dates (3 degrees of freedom), so it is 2.27x
  sigma_d by construction. With sigma_d itself in place of sigma_up the same formula gives about 138 dates; both are far
  above the 28-date ceiling, so the branch does not depend on that choice.
- **Consequences under the pre-registration, nothing more:** the panel stays 14 dates and runs descriptive only, with the
  achieved MDE reported; the owner's conditional (N_req <= 14 moves the embargo end 11-13 -> 10-31) does not fire, so the
  shadow scoring embargo end stays 2026-11-13. As a gate, the desk-study P&L comparison cannot decide the sign question at
  delta = 1.0 pUSD per band-day on any panel the pre-registration allows; no maker decision may treat its outcome as
  powered.
- **Not established:** the size or sign of NP_S; whether the pilot's variance holds on later dates; any figure for a
  different delta.

### 10s. Data layer v2 S0 measurement pack — workstation, 2026-10-15

Receipts: [S0 receipts](../research/data-layer-v2-s0-2026-10-15/README.md). Inputs are workstation copies dated before
2026-09-30 only; repository facts are read at commit `9fc1ff062`.

- **Book write-on-change is lossless:** on 2026-08-05 (3 events, 246,224 captures, median per-token interval 15 s), 50.3%
  of consecutive per-token captures repeat their quote content and 44.7% repeat the venue hash. The hash never stayed
  fixed while content changed. A write-on-change journal replays exactly at heartbeats of 0-3,600 s and keeps 48-49% of
  the plaintext bytes.
- **Codecs:** WOF LZX beats NTFS LZNT1 by 3.0-7.3x on every family tested, and stdlib xz-6 beats gzip-6 by 1.2-3.4x.
  xz-6 compresses JSONL at 16-27 MiB/s but forecast blobs at about 4 MiB/s (32-thread workstation).
- **numpy import commits ~756 MiB of private memory** with no thread cap: OpenBLAS (scipy-openblas 0.3.31,
  `MAX_THREADS=24`) reserves about 30 MiB per thread. It is 113 MiB at `OPENBLAS_NUM_THREADS=4` and 17 MiB at 1.
  `snapshot_tracker`, `observation_trigger`, `market_microstructure` and `execution_tape_supervisor` each commit
  775-816 MiB after import; the 88a and exec-tape capture modules commit about 23 MiB. Only `experiment_executor.py`
  sets a cap. **Host stat (master-agent, 2026-10-15 03:28, 20 logical CPUs):** private bytes `market_microstructure`
  793 MiB, `snapshot_tracker` 745, `observation_trigger` 709, `execution_tape_supervisor` 677, about 2.9 GiB in all;
  `maker_evidence_capture` 58 and `maker_shadow` 49. A numpy worker started through `supervisor.launch_detached` with
  the one-thread cap commits 48 MiB against 788 MiB uncapped (workstation, 2026-10-15); `launch_detached` sets that cap.
- **The GEFS "ensemble mean" is the control run:** `fetch_global_ensemble` reads the unsuffixed `temperature_2m` column
  of the GEFS payload as the mean, but it sits 0.26-0.54 °F (max 1.26 °F) from the 30-member mean on stored 2026-08-10
  San Francisco payloads, at a moving rank (0.17-0.73). There are 31 columns, one of which is the control. Train and
  serve read the same column, so parity holds; only the name is wrong.
  - **Caveat (2026-10-26, lever inventory F6):** every result labelled "GEFS mean" scored this control-run column,
    including lane G's F4 harm (+0.0054 [+0.0016, +0.0100], §10y). The 30-member GEFS mean is untested.
- **`last_good_sources.json` is rewritten whole on every pass:** `model_sources.py:596-619` reloads and atomically
  rewrites the ~36 MB file (the NBM bulletin text in `raw_payload`) even when unchanged; est. 5.2 GB/day of writes per
  US station at the 10-minute default. Host count (master-agent, 2026-10-15 02:57-03:27): 3-4 rewrites per 30 min of
  ~34.4 MiB files, about 4.8 GiB/day per US station and ~53 GiB/day across 11.
- **L2 deltas (S0(a), one public connection, 2026-10-16 01Z-11Z only):** raw `book`/`price_change`/`tick_size_change`
  payload is ≈3.1 GB/day for the 264-token T+0 exec-tape universe and ≈7.0 GB/day with T+1; `price_change` is >98%.
  Per-(token, hour) p95 is 1.8 MB (T+0) / 1.9 MB (T+0+T+1) and p99 7.7 / 5.7 MB; a p95 budget drops 45% / 26% of
  bytes. The run ended on the reconnect abort rule at 12:56Z ([receipt](../research/data-layer-v2-s0-2026-10-15/s0a-l2-delta-bytes.md)).
- **Not established:** post-gzip savings of write-on-change; FC-10 bytes per point; post-gzip L2
  bytes and L2 bytes in US daytime hours (13Z-23Z).

### 10t. First counterfactual-tape toxicity fit: CF fills are adverse at every horizon, settlement unresolved (DESCRIPTIVE, UNDERPOWERED) — item 330 build 2, workstation, 2026-10-17

**Status: DESCRIPTIVE ONLY.** Every cell is `UNDERPOWERED` (`maker_core.replay.inference`: fewer than 10 date
clusters). This is not a test of the `-0.43 c` settlement constant (`maker_core.quoting.fill_cost.CONSTANT_ADVERSE_MARKOUT`
= 0.0043, the 2026-09-20 public-tape run, 30 dates, 23 settlement clusters), and it changes no cost floor.

**Input.** The host counterfactual tape (`weather.market.maker_counterfactual_tape`, landed `30ec100f0`, host run
2026-10-17) over sealed 88a days UTC 2026-09-25..09-29 only: 1,164,086 hypothetical 20-share best-bid quote-minutes, every
day `all_match=True`. Two fill rules as two backlogs: `strictly_through` (print < bid, the default) and `at_price`
(print ≤ bid, the declared sensitivity). `to-jsonl` (master `5937c03a1`) wrote one file per maker side, YES and NO.

**Fit.** Build 2 `maker_core.replay.toxicity fit` (branch `claude/maker-toxicity-20261016` code, run from a never-landed
scratch tree `dfb3bc9d4`): 200 replicates, seed 20261016, a crossed date x market cluster bootstrap with a 90% interval.
The estimate is the unweighted mean over date x market cells, in cents per share, maker-signed (negative is adverse).
Clusters: 5 dates x 12 markets for 1/5/30 min; 4 dates x 12 markets at settlement.

**Settlement labels (provenance).** The public International Polymarket Gamma endpoint (`/markets?condition_ids=<id>&closed=true`,
unauthenticated, paced at 0.6 s or more) was queried only for the 201 condition_ids with fills whose event date is ≤ 09-28,
taken from the tape and written to a request manifest before any call. Value: `outcomePrices` over `["Yes","No"]`. Time:
`closedTime` (equal to `umaEndDate` in all 201). All 201 resolved (48 YES, 153 NO; one YES band per event), between
09-26T05:18Z and 09-29T11:57Z, so the ≥ 09-30 rule withheld none. 09-29 events are unlabelled (they resolve on or after
09-30). No local settlement file (the per-station `daily_summary.csv` and per-market ledgers mix 09-30+ rows) and no
snapshot was read.

| Rule, side | Fills / quote-min | Hazard per min | 1 min | 5 min | 30 min | Settlement (labelled fills) |
| --- | --- | --- | --- | --- | --- | --- |
| strictly_through YES | 1,344 / 596,691 | 0.00225 | -2.25 [-2.88, -1.66] | -2.32 [-3.28, -1.54] | -0.64 [-1.97, +1.16] | -3.59 [-8.54, +0.44] (1,023) |
| strictly_through NO | 1,186 / 567,395 | 0.00209 | -2.93 [-3.77, -2.07] | -3.06 [-3.95, -2.21] | -3.00 [-4.16, -1.98] | -2.42 [-6.59, +2.17] (892) |
| at_price YES | 2,893 / 596,691 | 0.00485 | -0.50 [-0.85, -0.21] | -0.64 [-1.31, -0.17] | +0.40 [-0.39, +1.44] | -1.31 [-5.63, +2.69] (2,256) |
| at_price NO | 2,791 / 567,395 | 0.00492 | -1.12 [-1.74, -0.28] | -1.25 [-1.87, -0.46] | -1.56 [-2.30, -0.81] | -1.51 [-5.44, +2.34] (2,089) |

Table digests (fit1, without labels; the 1/5/30 min rows are identical in the labelled refit): strictly_through YES
`d6a951bf0f932274…`, NO `d3d100de7eba687c…`; at_price YES `42c9a985a52d64c4…`, NO `998b7015fcbb3f17…`.

**What it shows, and what it does not.**
- Short-horizon counterfactual markouts are adverse at 1 and 5 minutes in all four tables, unlike the public-tape run's
  +0.38 c (1 min) and +0.19 c (5 min). The rule choice moves them 2-4x. Part of this is construction: a
  `strictly_through` fill exists only when a print trades through the bid, which selects for downward moves. The live
  fill rule is what the LFC campaign measures.
- Settlement point estimates are 3-8x more adverse than -0.43 c, but every interval spans both 0 and -0.43 c on 4 date
  clusters. The constant is neither confirmed nor refuted.
- Sweeps and large prints are the worst cells (about -3.5 to -6 c at 1 minute); calm minutes with no prior print are near 0
  under `at_price`. These cells are underpowered too.
- The tape nulls the weather fields, so the clock and decided dimensions are all `unknown`, and depth is almost all
  `deep`. The hazard row is keyed by exposure minute and the markout by fill instant, so a row's fill count can differ
  from its markout `n` (intended).
- 09-29 is thin (about 103k minutes), because bands whose event date is after 09-29 are dropped.

**Next readable labels.** Events 10-16..11-13 are inside the shadow panel: descriptive reads are refused (owner
2026-10-17) and scored reads open 2026-11-14 under a signed prereg. Build 2's fit stops at `FIT_LAST` 09-29, so fitting on
any later label needs an owner amendment of the fit window.

### 10u. HGB path: the intraday-tail and METAR-live-signal stages never act — code-traced plus Toronto replay, lever 5, 2026-10-21

**Claim, at exactly this scope:** on the HGB feature path, the intraday-tail stage and the learned METAR live
signal cannot change the served vector, even when their WU-history input is repointed to the observed station
high. Code-traced on master `6aac6de81a25bd939b954c5e7f29db02b2fd2fee`; checked on one real Toronto snapshot, in
the Toronto host replay and in the 12-market workstation replay. Outcome-blind: no label, score or market price was read.

- **Mechanism, intraday tail:** `distribution_model_path_stage` starts with `intraday = None`
  (`model_distribution.py:788`). On the feature path (`:808`) it returns at `:838` with `intraday` still `None`;
  only the empirical branches build it. The stage acts only under `if intraday and observed_bucket is not None`
  (`:993`), so repointing `observed_bucket` cannot open it.
- **Mechanism, METAR live signal:** the vote is computed at `model_distribution.py:423`, but the feature-path
  live-signal list (`distribution_live_signals`, `:1580-1611`) does not include it; only the empirical lists do
  (`:1620`, `:1642`). It is also `None` whenever `metar_bucket <= history_bucket`
  (`model_distribution_signals.py:318`), which always holds once the history high is the station high, because
  that high already includes the METAR rows.
- **Evidence:**
  - Synthetic tests on `claude/model-edge-codecheck-20261019` (`tools/research/model_edge_lever5/test_model_edge_lever5.py`):
    `test_metar_signal_and_intraday_tail_shims_reach_the_call_site` shows that the repointed value reaches both call
    sites (so the zeros are not a wiring no-op) and that a forced METAR vote of (95, 1.0, 1.0) gives final TV exactly 0
    on the feature path. `test_intraday_tail_shim_changes_the_stage_when_intraday_exists` shows that the tail stage
    does act once an `intraday` input exists.
  - Real-snapshot trace (`l5_variant_trace.py`, code `6a4c92d7b`): Toronto 2026-08-10 snapshot
    `20260810T151157359564-0400`, 15 h, `hgb`. Each shim was called once in base and once in the variant. METAR
    signal: history bucket 28, METAR bucket 28, returned `None`. Tail: `observed_bucket` `None` → 28, no `intraday`
    input, stage not entered. Final TV 0 for both.
  - Toronto host replay (`stage_replay.py` at `bd75f710a`): 61/61 folders, 11,298 snapshots, 0 errors, model kind
    `hgb` only, `changed_fraction` exactly 0.000 in every hour band for both variants.
- **Not claimed:**
  - Nothing about non-HGB (empirical or calibrated-empirical) markets, where both stages are wired.
  - Nothing about whether enabling these stages would help: no score was read.
  - The WU-floor residual is **not** structurally inert. It read 0.000 on Toronto because the data never opened its
    gate (`model_distribution_signals.py:344-352`; on the traced snapshot "support 28 <= history 28"). Toronto's
    station order is SWOB first (`model_sources.py:279-283`), so the repointed high already holds the SWOB rows. The
    residual can fire: `test_wu_residual_variant_can_change_the_served_vector` moves the final vector by TV 0.0055 on
    a synthetic SWOB-led case.
- **Fleet-wide confirmation (workstation replay, 2026-10-21, code `a653a7c14`, tool `6a4c92d7b`):** all 12
  markets, 61 folders each, 0 folder errors, 0 base errors, model kind `hgb` only. `intraday_tail`,
  `metar_live_signal` and `wu_residual` read changed fraction exactly 0 in every market and every hour band, so
  the claim holds fleet-wide for the HGB path, and the WU-floor residual's gate stayed closed on every dev snapshot
  of every market. The workstation's Toronto file reproduces the host file row for row (11,360 rows, identical
  `tv` and `max_bucket`; only the `attempt` and `seconds` run fields differ) across the tool change
  `bd75f710a` → `6a4c92d7b`. On US markets the residual is inert by construction, not only by data: US
  support is the current temperature and METAR, both already inside the repointed station high (traced on
  Atlanta 2026-08-10 snapshot `20260810T150843696523-0400`: "support 92 <= history 92"); only a SWOB same-day max
  above its own rows, so Toronto alone, could open the gate. That is a code inference checked on one snapshot,
  not a fleet statistic. The same replay closes the NBM arm (lever-5 note §1 and §3.5). Record: [lever-5 note](../research/model-edge-lever5-2026-10-19.md) §2 and §3.5.

### 10v. Dev replay with current code does not reproduce the served vector; the drift is code, not artifacts — M8 check, 2026-10-21

**Claim, at exactly this scope:** on dev target dates 2026-07-31..2026-09-29, replaying each captured snapshot
unmodified with current code reproduces the served vector of record within 1e-9 on only 4.0-22.4% of snapshots
per market, and the difference is large in the late hours. So every dev replay delta (lever 5, EDGE-1 twin) is
"current code ± variant on captured inputs", not a delta from what was served. Outcome-blind: no label,
settlement or market price was read.

- **Mechanism:** code drift since capture. Comparing each record's capture-time `model_identity` with the
  replay identity: `model_version` differs on 100% of rows; `code_changed` includes
  `src/weather/model/model_constants.py` and `model_distribution.py` on 100% of rows, `market_registry.py` on
  75,116 rows, and `feature_store.py` and `model_features.py` on 19,230 rows each. Dev captures span 490 distinct
  capture commits. The hour profile fits the lock-in serving changes made after capture (lever-5 note §2,
  stages 1-8): share within 1e-9 / median `max_abs` by local hour band, all markets, 00-05 0.247 / 0.0017;
  06-09 0.112 / 0.0063; 10-12 0.098 / ~0; 13-16 0.042 / 0.060; 17-23 0.004 / 0.275.
- **Evidence:** `python -m tools.research.model_edge_lever5.run served`, module
  `tools/research/model_edge_lever5/served_repro.py` (added in `64cbecca4`), branch
  `claude/model-edge-codecheck-20261019` at `0941dc432afe8ff47291938479d17c2931ef3a6b`. It compares the
  unmodified replay with the record's `recorded_distribution`, which `src/weather/collection/snapshot_store.py`
  writes as `model.get("distribution")` beside the sources it consumed (the replay fidelity canary); that field
  is a model output, not an outcome. Run: 732 folders, 128,594 snapshots, 0 folder errors, 0 base errors.
  Per market n / share within 1e-9 / p99 `max_abs` / max `max_abs` (`max_abs` = max absolute per-bucket
  difference): atlanta 10805 / 0.056 / 0.784 / 0.872; austin 10875 / 0.100 / 0.725 / 0.956; chicago
  10819 / 0.062 / 0.883 / 0.952; dallas 10662 / 0.040 / 0.769 / 0.830; denver 10769 / 0.116 / 0.844 / 0.917;
  houston 10584 / 0.079 / 0.758 / 0.799; los-angeles 10432 / 0.043 / 0.869 / 0.968; miami 10561 / 0.171 /
  0.754 / 0.976; nyc 10551 / 0.059 / 0.814 / 0.982; san-francisco 10512 / 0.224 / 0.859 / 0.971; seattle
  10726 / 0.115 / 0.709 / 0.941; toronto 11298 / 0.143 / 0.662 / 0.891.
- **Not claimed:**
  - No outcome was read; nothing here says whether current code or capture-time code forecasts better.
  - Not the artifacts: `artifact_hash` changed on 0 rows, `active_model_kind` (`hgb`) differs on 0 rows, and
    0 mismatched rows carry an identical identity.
  - Nothing about pre-07-31 dates or forward rows.
- **Relation to §1k:** consistent with, and narrower than, §1k (`-09-74a`..`-09-76a`) and RF "Check out the
  recorded runtime commit and replay reproduces what we served". §1k replayed at each row's runtime commit and
  still failed because served bytes were never committed; this check replays at one current commit and fails
  because the code moved. Whether dev-window identities resolve to reachable blobs was not measured.
- **Implication for replay-based evidence:** the base of a dev replay is current code. Lever-5 deltas
  ([note](../research/model-edge-lever5-2026-10-19.md) §3.3-3.5) and the EDGE-1 twin (T1/T0) dev deltas are
  "current code ± variant", not "served ± variant". Reproducing the served vector to 1e-9 on dev dates needs a
  per-row replay at each row's capture commit, which no tool does; forward reproduction (M8) is checkable only at
  a frozen hash on forward rows. Evidence scored against the served vector of record (for example the A0 power
  figure) is unaffected. Record: [lever-5 note](../research/model-edge-lever5-2026-10-19.md) §3.6.
- **EDGE-1 twins on the same dev inputs (3b, 2026-10-21, same tool sha, opt-in `--variants`):** against the
  current-code base, T1 (`t1_nws_hourly_only`) changes 89-100% of US vectors in every band 00-16 (mean TV
  0.06-0.31, 17-23 0.010-0.081; Toronto has no NWS hourly, so T1 = base) and T0 (`t0_climatology_prior`)
  changes 95-100% in every band (all-hours mean TV 0.15-0.43). Vector deltas only: no score, no edge claim;
  the binding comparison is forward at the frozen hash. Record: [lever-5 note](../research/model-edge-lever5-2026-10-19.md) §3.7.

### 10w. Open-Meteo hourly labels are fixed-offset per response; read as zone wall time they are 1 h late across a DST change — code trace, 2026-10-21

**Claim, at exactly this scope:** Open-Meteo returns one `utc_offset_seconds` per response, the zone offset when the
request is served, and applies it to every hourly label. Code that requests `timezone=<IANA zone>` and then does
`replace(tzinfo=zone)` therefore puts every label on the far side of a DST change one hour late. Traced read-only on
master `1c19ae10b`. Archive behaviour is measured; **live Forecast API behaviour is INFERRED** from the same provider's
Archive API, because no live capture crosses a DST change (the project started 2026-05-29). No label, outcome or price
was read.

- **Evidence (Archive payloads downloaded in June):** `katl` 2025-10-07..11-06 carries GMT-4 / −14400 on all 744 labels;
  label `2025-11-02T14:00` is truly 13:00 EST but the code assigns 14:00 EST (+1 h). `cyyz` over the same window is
  identical. `katl` 2026-02-13..03-15 crosses the spring change with −14400 throughout. The labels are contiguous in UTC:
  no repeated or skipped hour.
- **Live-served sites (real):** `model_sources.py:1549`, `:1622`, `:1667`, `:2143`, `:2249` (`open_meteo`,
  `air_quality`, `global_models`, `multimodel`, `global_ensemble`) and `eccc_gridded.py:146/170` (Toronto `eccc_gem`);
  all use `timezone=` IANA plus `replace(tzinfo)`.
- **Blast radius (inferred):** only 2026-11-01. Fetches before 06:00Z get the −4 h offset, so afternoon labels are +1 h
  and the `forecast_high` day window drops the true 23:00 EST hour. Later fetches are correct except that the true
  00:00 EDT hour is missing. From 11-02 on the data is correct. The served headline HGB reads only `forecast_high` and
  `forecast_gap` from these sources (Toronto adds `forecast_disagreement` and `forecast_source_count`), so only a max
  that falls in an edge hour can move: **small**. Hour-keyed features exist only in shadow candidates.
- **Latent readers (training and research):** `forecast_history.py:340` `local_valid_datetime` (training; reaches
  serving only through the `forecast_daily.csv` analogs, `model_features.py:1775`, `toronto_model.py:321`);
  `forecast_training_corpus.py:898` (master; fixed on the PIT-fetch branch); `open_meteo_archives.py:154`;
  `reanalysis_history.py:83`; `historical_fallbacks.py:154/219` (research). **Train/serve parity:** training and
  archive labels are +1 h on every date whose offset differs from the download season, not only on the change day.
- **Not affected:** `marine_context.py:256` (CO-OPS `lst_ldt` is true local time), NWS, METAR, SWOB, ASOS, MRMS and NBM
  (offset-aware or UTC).
- **Fix:** branch `claude/dst-provider-labels-fix-20261021` at `5588c40799855bd22f0b65cd099b836c2e1baff4` reads
  fixed-offset labels as label − offset in UTC (`weather.time.provider_hourly_local_times`) on the live served
  fetchers only; training readers are unchanged, pending master's decision. Host `roll_verdict.ps1`: ROLL-SENSITIVE;
  landing is the owner's call.
- **Training readers (measured, 2026-10-21):** branch `claude/dst-training-readers-fix-20261021` at
  `a399941e32932c3ac3704fad3984cc673d608c70` (held until after 2026-12-21, behind the fix above) re-reads the 4,786
  stored reanalysis payloads (dates ≤ 2026-09-29). On standard-time dates nearly every hour label shifts and the daily
  max changes on 0.7% (Los Angeles) to 17.4% (Chicago) of days, largest 11.4 °F; `reanalysis_prev_day_avg_temp`,
  the pressure features and the `heat_anomaly` features change on ~97–99% of standard-time days, `min_temp` on 22%,
  `max_temp` on 8%, and `source_reanalysis_bias` reads the same max. **Any past research that used reanalysis-derived
  features over Nov–Mar dates is affected.** Served headline features are unaffected (they do not read reanalysis).
- **Not claimed:** no measured live payload across a DST change; no forecast-skill effect; nothing about the size of
  the training-label shift's effect on any fitted model.
- **Relation to other records:** the same provider behaviour explains the §1m calendar-extension note (standard-time
  dates shifted 1 h); this section traces the `forecast_history.local_valid_datetime` path that note left untraced.
  **Supersedes in part** [DST audit 2026-10-07](../roadmap/audits/dst-audit-2026-10-07.md): DST-M3 left the
  per-response offset "not verified" and framed the effect as every label on 11-01; it is fixed-offset, the live
  effect is limited to pre-06:00Z fetches on 11-01, and the archive/training readers it lists are shifted on every
  standard-time date. DST-L9's "latent: the season is May-Aug" no longer holds once the Oct-Dec PIT fetch exists. The
  audit does not list `eccc_gridded.py`, `reanalysis_history.py` or `historical_fallbacks.py`.

### 10x. From the 2026-10-23 events the venue resolves on the raw METAR API, routine reports only — event metadata plus IEM measurement, 2026-10-23

**Claim, at exactly this scope:** for built-in events dated 2026-10-23 and later, the venue's declared
`resolutionSource` is the raw `aviationweather.gov/api/data/metar` API for the station, replacing the
`weather.gov/wrh/timeseries` page of §10c. Verbatim samples (public read-only Gamma GETs, `resolutionSource` field only):
NYC 10-23 `https://aviationweather.gov/api/data/metar?ids=KLGA&format=raw&date=2026-10-24T04:00:00Z&hours=27`,
Chicago 10-24 `...?ids=KORD&format=raw&date=2026-10-25T08:00:00Z&hours=30`, Denver 10-25
`...?ids=KDEN&format=raw&date=2026-10-26T09:00:00Z&hours=30`. The three `description` texts are one template (identical
hash after swapping station, date and URL). Only event metadata was read for these dates: no prices, no outcomes.

- **Rules as summarised (not quoted in full):** the label is the highest **routine** METAR temperature on the local date,
  read in tenths of °C from the remark group (whole-degree body value if the remark is missing), rounded half up to °F; a
  report that begins with SPECI does not count; corrected reports count until the next day's first report; WU Daily
  Observations is the fallback.
- **SPECI effect (measured, IEM, 671 US station-days 2026-07-31..09-29, METAR only):** dropping SPECIs lowers the daily-max
  degree on 15 days and changes the 2 °F band on 9 (1.3%). WU included the SPECI on both days where one held the max (2/2),
  so WU-derived labels and the repo's routine+SPECI METAR path sit on the SPECI-inclusive side of that gap.
- **Agreement where WU exists (measured, 07-31..08-10, 110 US market-days; the workstation's WU history ends 08-10):**
  repo rule (routine + SPECI, `tmpc`, half-up) 110/110 exact with WU; the new venue rule 108/110 exact, 1 band flip. This
  repeats 86a's pre-switch window rather than adding new dates.
- **Denver station:** the 10-23..10-25 Denver events name **KDEN**; the built-in spec, WU history and
  `config/locations.json` use KBKF. No KDEN measurement exists.
- **Not claimed:** no exact-degree agreement between WU and the venue after 09-29; nothing for Toronto or Hong Kong; the
  pilot cities' post-10-23 Rules were not read; foreign SPECIs cannot be separated in IEM raw text.
- **Consequence (decision, not finding):** owner 2026-10-23 (DECISION_LOG) labels new METAR-settled cities from IEM METAR;
  the built-ins stay on the WU proxy pending a later decision. The ledger still hard-codes WU. Source:
  [METAR-vs-WU agreement study](../research/metar-vs-wu-agreement-2026-10-23.md);
  [phase-2 scoping](../research/more-markets-phase2-scoping-2026-10-23.md). **Supersedes in part §10c** for events dated
  2026-10-23 onward (the WRH page and its "Hourly Data"/"Temp" rules no longer name the source).
- **Superseded consequence (2026-10-26):** the built-ins now label as the venue resolves each date (master ruling (10-25),
  reading B); see §10ai.

### 10y. Free-source and blend levers add nothing at 07-12; one afternoon radar lead — lane G screens, development, 2026-10-24

**Claim, at exactly this scope:** on the dev scorecard (`weather.reporting.scorecards.dev_scorecard`, walk-forward
7-day folds, scored 2026-08-15..09-29, 43 dates x 11 US markets = 473 market-days, 83,801 snapshots), six
forecast-source levers were each scored as a paired increment over their no-source control (`--control-module`,
same rows and crossed date x market weights, 2,000 draws, seed 20260921). **None improves the morning; every 07-12
read is null or harm.** Unpowered by construction (11 market clusters, EF §10j); dates already read by earlier
lanes; nothing here is confirmation. Record, rules (each committed before scoring) and receipts:
[free-source screens](../research/free-source-screens-2026-10-23.md).

| Lever (control) | Decided block | Increment over control [95% crossed] | MDE80 | Morning increment (06-09 / 10-12) | Verdict |
| --- | --- | --- | --- | --- | --- |
| F1 IEM 1-min ASOS running high, degraded to 5-min whole °C +10 min (t3-r3) | 13-16 | +0.0044 [+0.0017, +0.0076]; 0/10 markets better | 0.0042 | +0.0001 / +0.0013 [+0.0002, +0.0026] | KILL (harm); raw 1-min +2 min also harms (+0.0029 [+0.0004, +0.0057]) |
| F2 MRMS composite reflectivity >= 35 dBZ within 25 km (t3-r3) | 13-16 | −0.0005 [−0.0010, −0.0001]; 7/11 | 0.0006 | −0.0000 / −0.0001 (span 0) | development lead only, below the 5% bar |
| F3 12Z sounding mixed-layer cap (t3-r3) | 13-16 | −0.0001 [−0.0003, +0.0000] | 0.0002 | −0.0000 / −0.0000 | KILL (null) |
| F4 captured Open-Meteo members, MG-1 recentred halfway (MG-1) | 00-12 | gfs_seamless +0.0008 [−0.0032, +0.0055], NAM +0.0007, AIGFS +0.0003 (span 0); GEFS mean +0.0054 [+0.0016, +0.0100] | ~0.006 | all span 0 except GEFS harm | KILL (null; GEFS harm); AIFS, GraphCast never captured |
| G2-a ECMWF ENS 51-member mean, bias-adjusted, MG-1 recentred halfway (MG-1) | 00-12 | −0.0000 [−0.0033, +0.0031] | 0.0047 | −0.0008 / −0.0008 (span 0) | KILL (null) |
| L4 per-station x hour inverse-MSE blend of NBM v2, GFS, IFS, ICON day-1 (MG-1) | 07-12 | −0.0002 [−0.0045, +0.0047]; date-clustered [−0.0031, +0.0025]; h07..h12 all span 0 | 0.0064 | — | KILL (null) |

- **Controls reproduce:** t3-r3 − served at 13-16 is −0.0110 [−0.0188, −0.0041] (EF §10q's −0.0116); MG-1 −
  served at 00-12 is −0.0153 [−0.0234, −0.0083] (EF §10j). The MDE80 of the 00-12/07-12 reads (about 0.005-0.006)
  is four to five times the 5% bar (about −0.0012), so the nulls are "no increment demonstrated".
- **F1 kills every paid observation feed in the 2026-10-23 proposal** (its P1 rule) and does not trigger the
  MADIS sign-up: a fresher running high from the 1-minute archive moves mass off the METAR-based settling value.
- **L4 afternoon (parked, not a win):** at h15..h23, L4 − MG-1 is −0.008 to −0.013 with intervals excluding 0
  (13-16 −0.0059 [−0.0103, −0.0014]; 17-23 −0.0129 [−0.0179, −0.0077]). That mostly undoes MG-1's own afternoon
  harm (MG-1 − served +0.0068 at 17-23, EF §10p); L4 − served does not exclude 0 there (13-16 −0.0070 [−0.0149,
  +0.0005]; 17-23 −0.0061 [−0.0176, +0.0045]), and t3-r3 is far better. Parked as an afternoon candidate that
  would have to beat t3-r3, under a new pre-registration on new dates.
- **Pre-registration and receipts:** L4 frozen in `docs/research/forecast-blend-l4-preregistration-2026-10-24.md`,
  sha256 `96dee78c7bfe8e350905c19048824ddf25729fcf3bc829bde066f16ad346a3b0` (commit `144a1f582`). The score JSONs are
  content-addressed under the workstation `data\research\free_sources\scores\`: F1 `6b0179912f9b`, F1u `f9633f12518f`,
  F2 `511bd35de76e`, F3 `52f20094cdfb`, G2-a `1d72ea4b36f8`, L4 `d019d6b1fde6`.
  Fetches (serial, hashed per file):
  - IEM 1-minute ASOS: 396 requests, 503.9 MB, 11.66 M rows (KBKF has none);
  - IEM RAOB: 363 requests, 255.5 MB, 19,405 soundings (KDNR empty);
  - MRMS: 2,928 objects, 4.14 GB, reduced to 32,208 station rows;
  - ECMWF ENS: 171 00Z runs x 51 `2t` members x 6 steps, 36.83 GB in 42,484 range requests via the Google Cloud open-data mirror (AWS throttled), eccodes in a separate research venv only, 3,751 station-date rows;
  - Open-Meteo Previous Runs day-1: 33 requests, 1.19 MB;
  - F4 used captured replay inputs (122,711 snapshots), with no download.
- **G2-b (ENS gap conditioning t3-r3, 13-16):** −0.0002 [−0.0005, +0.0001] over t3-r3, MDE80 0.0004: KILL (null);
  score `60047a9deb4d`.
- **Not scored:** DWD MOSMIX (the open server keeps about 2 days, so it needs forward capture).

### 10z. R0 on the full year beats windowed R0 but loses to the floored forecast baselines by about 1 nat at 07-12 — lane L1, workstation, 2026-10-24

- **Question:** does training the R0 cutoff-hour HGB on every 2021-2025 day (about 1,712 per market instead of 75,
  plus `doy_sin`/`doy_cos`) beat the windowed fit on the same held-out window days, and does it beat fair comparators?
- **Design (pre-declared, `C:\t\l1\rule.md`, sha256 `993e01d4…` then clarification `008c662b…` before any floored
  row):** atlanta, austin, chicago, dallas, denver; centre 2026-11-24; blocked leave-one-year-out on the held-out
  years' 11-17..12-01 rows, cutoffs 07-20; equal-weight market mean of per-market mean log-loss deltas; date-clustered
  bootstrap, 2,000 draws, seed 20261024. The climatology prior is the windowed one in every arm. Comparators (e)
  R0 baseline + floor, (f) bias-corrected forecast + floor and OLS + floor come from lane L3's own rows
  (`weather.calibration.r0_ols_floor_challenger` @ `171717d5f`) behind a parity gate. Corpora: the full-year union
  `621bcd8ea82ceed397bcfbdfae1c80664d1cb73adba3e71b240fae34db529cdc` ([PIT corpus guide](PIT_FORECAST_TRAINING_CORPUS.md)).
- **Controls:** windowed leaf-20 rows reproduce lane D's trainer rows and L3's `r0_repro` on 1,050 of 1,050 rows in
  each market (max diff 1.8e-15).
- **Result vs raw windowed R0 (original rule):** full-year leaf 20 −1.035 [−1.246, −0.837] at 07-12, a win at every
  hour; leaf 10 −0.854 [−1.062, −0.656]. Leaf 5 +0.990 [+0.876, +1.100] is a fitting failure (in-sample loss about
  14), not an overfitting result. Windowed R0 itself (about 4.3-4.6 nats at 07-12) is worse than its own floored
  climatology baseline (e), so this win mostly measures a broken comparator.
- **Result vs fair comparators (decisive), full-year leaf 20 + served floor (×1e-6):** vs (f) **+0.900 [+0.729,
  +1.075]** at 07-12 (07 +0.979, 12 +0.656), vs OLS + floor **+1.018 [+0.860, +1.180]** (07 +0.965, 12 +0.959);
  every market is worse at 07-12 against both. Against (f) it is better from 15:00 on (−0.55 to −1.18, CIs exclude 0);
  against OLS + floor it is worse at every hour except 15-16 (CIs cross 0). It beats (e) −0.406 [−0.555, −0.268].
  The floor alone moves full-year by −0.102 [−0.119, −0.087]. Against lane D's served-floor windowed R0 rows
  (`retrain-r0-floor-msl20-2026-11-24`, 5,250 rows, all paired) it is −0.802 [−1.008, −0.619].
- **Verdict:** do not adopt the full-year R0 HGB. More rows do not rescue a ~67-class bucket classifier against a
  forecast-anchored discretised normal with a hard floor.
- **Not claimed:** nothing about edge over market prices; one centre (11-24) and five markets; the seasonal columns
  are not served features.

### 10aa. A pooled residual model beats OLS + floor and the floored forecast on R0's rows, and beats the served vector on the development window; pooling is the lever, and it is still worse than the market — lane L2, workstation, 2026-10-24/25

**Claim, at exactly this scope:** a model pooled across the 11 US markets (`weather.calibration.pooled_residual_model`, arm P3) beats lane L3's OLS + floor ((a), EF §10ab) and the floored bias-corrected forecast ((f)) at 07-12, on R0's own blocked leave-one-year-out rows. Its development variant P3d beats the served vector on the development window.
- What P3 does: it forecasts the WU high minus a bias-corrected forecast, fitting the bias per market and per cutoff inside each fold. It hard-floors the result at the observed running high, and its error distribution is learned rather than assumed normal.
- What this is: model against model on development years, and model against served on development dates.
- What this is not: edge evidence. No market price enters any comparison except the scorecard's R denominator, and **P3d's R stays above 1 in every block**, so it is still worse than the market everywhere. Nor is it confirmation or promotion evidence (§5).
- The dev-window numbers are **selection evidence only**; the window has been reused by many lanes.
- Nothing after 2026-09-29 was read.

**The model.**
1. mu0 = forecast_high + the in-fold (market, cutoff) bias, or the market normal when there is no forecast.
2. OLS of the residual y − mu0 on [1, g, max(g, 0)], where g = observed high so far − mu0.
3. An HGB on the OLS residual, using station, level and day-of-year features.
4. An HGB scale model fitted on inner-LOYO errors.
5. A kernel-smoothed empirical standardised-error distribution, censored at the floor bucket, mixed 0.98/0.02 with climatology.

P3 is fitted per cutoff on all markets together. The rule is `rule.md`, sha256 `53ba558b50502fd51bf5565c448493169ae2c6524234b5f4439de6a92bde3a32` (the original `e2649f16…` plus amendments 1-4, each appended before its rows existed). Research record: [l2-pooled-residual-2026-10-24](../research/l2-pooled-residual-2026-10-24/README.md).

**Oct-Dec, R0's rows.**
- Setup:
  - PIT union `674b12ac`, centre 11-24, 11 markets.
  - 11,550 rows, identical to L3's: (a) has a max abs diff of 0 on every row, and R0 reproduces to 1.8e-15.
  - Date-clustered bootstrap: 75 clusters, 2,000 draws, seed 20261024, with crossed date × market beside it.
  - P3 is also trained on the Aug-Sep corpus `b455bd53` (union `744289be`). Incomplete centres are dropped whole (12-24 fails closed).
- Log loss at 07-12, P3 minus:

| Comparator | Δ log loss | Interval |
| --- | --- | --- |
| (a) L3 OLS + floor | **−0.147** | 97.5% [−0.195, −0.102]; crossed [−0.211, −0.083] |
| (f) floored bias-corrected forecast | **−0.272** | 97.5% [−0.339, −0.211]; crossed [−0.374, −0.183] |

- Brier vs (a): −0.032. vs (f): −0.049.
- Hour 12: −0.159 vs (a), −0.447 vs (f). The gain over (a) grows into the afternoon: −0.373 at hour 15.
- No market is worse than (a) beyond its interval. Miami, NYC and Seattle intervals cross 0.
- Against lane D's floored R0 (5 markets): −1.995 [−2.258, −1.745].
- **Pooling is the lever.** The per-market twin U0 is worse than P3 by +0.174 [+0.141, +0.208] and only ties (a): +0.027 [−0.000, +0.055].
- **More training data adds nothing.** P3F, trained on L1's full-year union `621bcd8e` (EF §10z; 23 centres, 245,625 rows), scores −0.151 vs (a) and −0.275 vs (f), but P3F − P3 is −0.004 [−0.014, +0.006].
- The comparison against raw R0 (−1.968) uses an unfair comparator, because serving floors and calibrates. Do not cite it.

**Dev window vs served.**
- Setup:
  - Dev scorecard `4be7c077c` through L3's `dev-score`: 08-15..09-29, 43 dates, 473 market-days.
  - Positive control: served R 1.774 (all) and 1.526 (00-16), reproduced.
  - P3d uses only forecast_high, high_so_far and current_temp, and is fitted on Aug-Sep 2021-25 only.
  - Its inputs are those of L3's main variant: the 2026 Previous Runs `gfs_seamless` lead-1 forecast, and captured METAR rows at or before each cutoff. Its 79,403 snapshots are the same as arm A's.
- Results, dR = R_P3d − R_served:
  - **Pooled 07-12: −0.210**, date-clustered [−0.256, −0.162], crossed [−0.357, −0.091]. No standard block is worse.
  - R is 1.273 for P3d against 1.483 for served.
  - Hour 12: −0.210. 00-16: −0.151. 13-16: −0.496 [−0.627, −0.378]. 12-16: −0.406.
  - U0d also beats served (−0.186) but trails P3d.
  - R_P3d by block: 06-09 1.327, 10-12 1.268, 13-16 1.366, 00-16 1.375, 17-23 2.141. Every block is above 1.
  - Selecting P3d for MG-2's afternoon slot is governed by the pre-declared pick rule `5898bfb0…`, scored once by L3. This entry does not decide it.

**Serve parity (code and captured inputs, outcome-blind, 2026-10-25).**
- high_so_far, current_temp, cutoff and date come from the capture with the trainer's cutoff semantics. high_so_far equals L8's `running_max_since_midnight` on all 9,224 replay hours (EF §10ab).
- **forecast_high does not.**
  - The Previous Runs lead-1 value that P3d (and arm A) is trained and scored on is not in the capture, and no serving module fetches it.
  - The captured `gfs_seamless` day max is the current run, a different lead.
  - On the 13-16 dev rows, the served `forecast_high` minus the PIT value has MAE 2.26 °F (mean +1.03 °F), and is at least 1 °F apart on 72% of rows.
  - Serving either model as scored needs a Previous Runs fetch at serve time. That input is free and public, and issued before the cutoff.
- Two further mismatches, shared with arm A:
  - Training reads high_so_far and current_temp from WU history (whole °F), while serving reads METAR (tenths).
  - The fit is for Aug-Sep only, so an Oct-Nov forward shadow needs a refit, which has no dev read.

**Not claimed:** no edge, no price comparison, no confirmation. Nothing outside the 11 US markets or outside the stated windows. Nothing about replacing R0, which is master's decision.
### 10ab. OLS + hard floor beats floored R0 and the served vector, but NBM-based MG-1 and L6's own-observation twin beat it in the morning; upstream ASOS adds nothing beyond own observations — lanes L3 and L6, workstation, 2026-10-24/25

**Claim, at exactly this scope:** on R0's own blocked leave-one-year-out rows, a three-feature OLS on the forecast high,
the observed running high and the current temperature, discretised on integer native buckets and hard-floored at the
observed high (arm A, `weather.calibration.r0_ols_floor_challenger`), beats R0 by a wide margin, and beats it **after R0
is floored too**. On the development window it beats the served vector at every hour 07-17, but it is **worse than the
zero-parameter NBM read MG-1 from 06:00 to about 12:00** and better only from 13:00. Lane L6's own-observation twin (MG-1
recentred on an own-station nowcast) beats arm A at 07-12. Upstream ASOS observations add nothing beyond the
own-observation twin (L6 KILL). Dev-window numbers are **selection evidence only**: the window has been reused by many
lanes (the dev-window ledger `docs/operations/DEV_WINDOW_LEDGER.md` on `claude/loss-atlas-prereg-20261024`). None of this is confirmation,
edge or promotion evidence (§5). Nothing after 2026-09-29 was read.

- **Oct-Dec, R0's rows (final, rule `rule.md` sha256 `d9224231aa7614bc3e2b1a5c5a13126b7ebab58a53f57ddf405e80886ddc243a`
  with clarifications 1-3):** PIT union `674b12ac` at centre 11-24, 1,050 rows per market, blocked LOYO, date-clustered
  bootstrap (2,000 draws, seed 20261024; crossed date x market beside it). **Positive control:** the baseline and
  R0-repro reproduce lane D's rows exactly (max abs diff 0.0), and all 20 of D's 07-12 means reproduce to three
  decimals (HGB raw / floored, baseline raw / floored; e.g. Atlanta 4.333 / 4.081 / 4.089 / 3.704). **Verdict, 5 primary
  markets, 07-12 log loss:** A − D's floored R0 **−1.820 [−2.098, −1.563]** (crossed [−2.154, −1.484]), Brier −0.146,
  every market's interval below 0; A − forecast + floor −0.119 [−0.181, −0.060] (5 markets) and −0.125 [−0.171, −0.083]
  (11 markets); A − baseline + floor −1.425 (5) and −1.217 [−1.354, −1.087] (11). The residual-HGB variant is
  indistinguishable from A. Context (L1, EF §10z): full-year R0 + floor is still worse than A by +1.018 [+0.860, +1.180]
  at 07-12 in 5/5 markets.
- **Aug-Sep, in-season corpus `b455bd53` at centre 09-07 (no R0 comparator; lane D's in-season fits deferred):**
  A − baseline + floor −0.735 [−0.865, −0.615] (11 markets), −0.870 (5). **A − forecast + floor −0.166 [−0.257, −0.064]
  on 11 markets (crossed [−0.316, +0.011]) but −0.064 [−0.169, +0.054] on the 5 primary markets: a fail there.**
- **Dev window vs served (rule `dev_rule.md` sha256 `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676`,
  original `cf75eced…` plus clarifications 1-3; dev scorecard rows, 43 dates 08-15..09-29, 473 market-days; positive
  control served R 1.774 all / 1.526 00-16 reproduced).** A is fitted on the Aug-Sep 2021-25 corpus only and fed the
  2026 Open-Meteo Previous Runs forecast (`gfs_seamless`, lead 1) and the captured METAR rows at or before each cutoff.
  dR = R_A − R_served, pooled 07-12: **−0.179 date-clustered [−0.232, −0.127], crossed [−0.306, −0.072]**, no standard
  block worse (5 markets −0.165 [−0.242, −0.092]); 12-16 −0.317 [−0.398, −0.242]; 00-16 −0.126; every hour 07-17 below 0.
  Forecast + floor alone is −0.078 at 07-12 but +0.210 at 12-16: the gain is the running-high regression, not the floor.
- **Dev window vs MG-1 (gate: no worse than MG-1, no CI-worse block) — FAILS.** MG-1 is L7's `loss_atlas.mg1_frame`
  (control: 07-12 excess over market 0.011957 reproduced). On the same blocks: MG-1 − served is **−0.259** at 07-12 and
  −0.247 at 00-16, against A − served −0.179 and −0.126. A − MG-1: 07-12 **+0.080 [+0.020, +0.142]** (crossed
  [−0.011, +0.195]); 06-09 +0.148 [+0.088, +0.204]; 00-16 +0.121 [+0.053, +0.185]; but 12-16 −0.229 [−0.358, −0.113],
  13-16 −0.366 and all hours −0.177. By hour: worse 07-10, tied 11-14, better from 15. 5 markets: 07-12 +0.086
  [−0.013, +0.190].
- **Twins vs A, identical rows (walk-forward fits through the scorecard's own `module_predictions`):** L6's own-obs twin
  (L6's module, control: its 07-12 Brier − MG-1 −0.0036243 reproduced to 1e-6) − A at 07-12 **−0.148 [−0.190, −0.103]**
  (crossed [−0.255, −0.061]), worse than A from 14:00. An intercept-only twin (MG-1 + a per-hour 07-12 shift, no
  observations) − A −0.074 [−0.122, −0.022] (crossed [−0.174, +0.018]); intercept twin − MG-1 +0.007 [−0.024, +0.038], so
  a bias shift alone adds nothing to MG-1. Both NBM-based twins add morning information beyond A.
- **Fit scheme and NBM as a regressor (dev-fit, sensitivity only):** A refitted walk-forward on dev rows − A historical
  −0.025 [−0.069, +0.020]; A plus the NBM mean as a fourth OLS regressor (A', dev-fit) − A −0.017 [−0.069, +0.034] and
  still +0.064 [+0.005, +0.124] over MG-1. Putting the NBM centre into a Gaussian OLS does not recover MG-1's morning
  advantage. A' fitted on L9's historical PIT NBM corpus is pending.
- **high_so_far definition:** L8's serve-equivalent running max since local 00:00
  (`weather.model.observed_running_max.running_max_since_midnight`, branch `claude/high-so-far-parity-shadow-20261024`
  @ `f3b49fabb`) equals L3's own METAR reading on all 9,224 replay hours used; the distribution files are byte-identical.
- **Scope of A:** A predicts only from the 07:00 cutoff, so all 23,955 fallback-to-served snapshots are 00:00-06:59
  local; from 07:00 to 23:00 it covers at least 99% of snapshots in every market (98 snapshots lack a floor, 15 lose all
  mass to it). On covered rows only: 07-12 unchanged, 00-16 A − served −0.236 and A − MG-1 −0.032 [−0.113, +0.043].
- **L6 upstream ASOS (rule sha256 `6687c8dfb49b0650d27bbf23164ba102de5d838ada79917df50075c61653921a`, branch
  `claude/upstream-obs-screen-20261024` @ `e6c3f30cf`): KILL.** Candidate (MG-1 recentred on an own + upstream-ring
  nowcast) − own-obs twin at 07-12 −0.0005 [−0.0012, +0.0003] Brier, MDE80 0.0011. Consistent with T13 and §10q: the
  NBM already carries the upstream information; the own-observation stack is a development lead.
- **Not claimed:** no edge over the market (every arm still trails it); no claim that A should replace MG-1 in the
  morning; no powered result (11 market clusters); no claim for Toronto.
- **Branch:** `claude/r0-ols-floor-challenger-20261024` (code, tests, rule files under `C:\t\l3`).
### 10ac. On blocked LOYO 2021-25, the PIT NBM mean and cross-market pooling improve OLS + hard floor; overnight low, dewpoint and hour-pooled slopes do not — lane L9 ingredient ladder, workstation, 2026-10-25

**Claim, at exactly this scope:** weather-only, development-stage, blocked leave-one-year-out (LOYO) on 2021-2025
target dates. There is **no claim against MG-1, the served vector or the market**, and the 2026 dev window was
not read. The ingredients were tested one rung at a time against plain OLS + hard floor (L3's `ols_floor`, §10ab),
on identical rows, under the pre-declared rule `C:\t\l9\rule.md` (sha256 `3b4976dc…`). Rungs are cumulative only
on KEEP.

- **Rows:** 103,609, from 11 US markets x 9 non-overlapping ±7-day centres x cutoffs 07-20. The Aug-Sep centres
  are 08-08, 08-23, 09-07 and 09-22; the Oct-Dec centres are 10-10, 10-25, 11-09, 11-24 and 12-09. Records and
  splits are the R0 trainer's, built through L3's challenger module.
- **Corpora:** the season members of the full-year union `621bcd8e…` (§10z): `b455bd53…` for Aug-Sep and the
  Oct-Dec members for Oct-Dec. The year-keyed trainer union refuses the overlapping full-year manifests; the
  Jan-Jul members plan no date in these windows.
- **Statistics:** the primary metric is D(07-12), the equal-weight 11-market mean of per-market mean log-loss
  deltas, with both seasons pooled. CIs are a date-clustered bootstrap (2,000 draws, seed 20261025). **KEEP** means
  the CI upper bound < 0 AND no CI-worse block. The blocks are {07-12, 12-16, 17-20} x {11, primary 5} x
  {pooled, Aug-Sep, Oct-Dec}, plus Brier 07-12 on the 11.
- **Controls:**
  - **Positive control:** BASE equals L3's per-row `ols_floor` log loss on identical row sets for all 11 markets
    at centres 11-24 and 09-07; the largest difference is 5.3e-13.
  - **Placebo:** a N(0,1) regressor gives +0.0097 [+0.0081, +0.0113], so it is not KEEP. That is the expected
    cost of one extra slope at about 60 training rows per (market, centre, hour, fold) fit.
- **PIT NBM corpus** `1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd`:
  - **Source and parse:** NOAA open data, `noaa-nbm-grib2-pds` `blend_nbptx` (NBP). It is parsed with parser v2
    TXNMN, the column MG-1 consumes.
  - **Cycle:** the 07Z cycle of the target date. It is used only when its S3 LastModified (07:55-11:43Z) is <= the
    cutoff instant.
  - **Coverage:** 675 dates x 11 stations with zero gaps; 3 scored rows had a late bulletin and fell back to the
    forecast.
  - **Fetch:** station blocks were read by HTTP Range, serially, about 0.9 GB in total (fetcher
    `tools/research/ols_floor_ladder_nbm_fetch.py`).

| Rung (vs the cumulative base) | D 07-12, 11 markets [95% CI] | Verdict |
| --- | --- | --- |
| 1 NBM mean alongside the forecast (N1) | −0.0960 [−0.1138, −0.0779], MDE 0.026 | **KEEP** (picked) |
| 1 NBM mean instead of the forecast (N2) | −0.0945 [−0.1196, −0.0694] | KEEP, not picked (pre-declared tie-break) |
| 2 overnight low since midnight (L1) | −0.0124 [−0.0189, −0.0060], MDE 0.009 | **KILL** (Aug-Sep blocks CI-worse) |
| 3 dewpoint at the cutoff (DP) | −0.0009 [−0.0078, +0.0073], MDE 0.011 | **KILL** (null; Aug-Sep 07-12 CI-worse) |
| 4 slopes pooled across hours (PH) | +0.0632 [+0.0518, +0.0741] | **KILL** |
| 4 slopes pooled across markets (PM) | −0.0406 [−0.0541, −0.0278], MDE 0.019 | **KEEP** |

- **NBM (N1):**
  - 5 primary markets: −0.157. Aug-Sep −0.104 (11) / −0.175 (5); Oct-Dec −0.090 (11) / −0.142 (5).
  - By hour (11 markets): −0.157 at 07, fading to −0.008 at 16; 17-20 is about 0. 12-16 overall is −0.016.
  - Brier 07-12: −0.0147.
  - 10 of 11 markets have a negative point estimate at 07-12. **Los Angeles leans worse:** +0.035 [−0.003, +0.080].
- **Overnight low, a seasonal split:**
  - Oct-Dec helps at 07-12: −0.028 (11) and −0.031 (5).
  - Aug-Sep is flat to worse: +0.007 (11) and +0.013 (5, CI-worse); Aug-Sep 12-16 and 17-20 are also CI-worse on
    the 11.
  - This is consistent with L5's A2 null against MG-1 on dev (−0.0016, crossed CI [−0.0059, +0.0033],
    pre-registration `53fd0bc5…`, branch `claude/morning-loss-diagnosis-20261024`).
  - A season-gated variant is a **lead only**, with no pre-registration (coordinator ruling, 2026-10-25). The
    previous-evening low (descriptive) is weaker still: −0.0067.
- **Dewpoint:** Aug-Sep 07-12 is CI-worse (+0.016 on the 11, +0.010 on the 5); Oct-Dec helps a little (−0.014 on
  the 11). Hours 07-08 are hurt.
- **Pooling:**
  - **Per-hour slopes are essential.** PH (shared slopes with hour fixed effects) loses +0.87 nats at 17-20,
    because it destroys the late-day near-identity on the observed high.
  - **PM** (shared slopes, market intercepts, per-market sd) helps in both seasons: Aug-Sep −0.057 and Oct-Dec
    −0.028 on the 11; −0.034 on the primary 5.
  - **Brier flag:** on the 5 primary markets in Oct-Dec, PM is flat on log loss (−0.006 [−0.027, +0.014]) and
    CI-worse on Brier (+0.0048 [+0.0018, +0.0076]). That cell is not a pre-declared guard block, so the KEEP stands.
  - **Los Angeles leans worse** under PM: +0.066 [−0.002, +0.126].
  - L2's pooled model is §10aa.
- **Cumulative, descriptive:** OLS + floor + N1 + PM vs plain OLS + floor, on the same rows:
  - 07-12: −0.137 [−0.156, −0.117] (11 markets), −0.191 (5 markets);
  - 12-16: −0.035 (11), −0.056 (5);
  - 17-20: about 0;
  - no guarded block is CI-worse.
- **Disposition (coordinator ruling, 2026-10-25):**
  - MG-2's A' stays OLS + floor + N1. PM is not added after the fact.
  - OLS + floor + N1 + PM is recorded as an **MG-3 candidate lead**.
- **Not claimed:**
  - no edge over the market;
  - no comparison with MG-1 or the served model on these rows;
  - nothing outside Aug-Dec;
  - nothing for non-US markets.
  - The fits are small (about 60 rows each), and the L1 and DP kills are nulls only above their MDEs.
- **Relation to other records:** BASE and rows are §10ab (L3); the full-year union is §10z (L1); the pooled
  challenger is §10aa (L2). Code: branch `claude/ols-floor-ladder-20261025`, module
  `weather.calibration.ols_floor_ladder` (stacked on L3's `r0_ols_floor_challenger`).

### 10ad. Against the market, the models add nothing (blend weight about 0), and the dead-bucket mechanism is closed fleet-wide once the floor is dated by receipt — lane L11, workstation, 2026-10-25

**Claim, at exactly this scope:** development window only (dev scorecard, scored 2026-08-15..09-29, 43 dates x
11 US markets = 473 market-days, burn-in 08-01..08-14; Toronto dead buckets 08-10..09-29). Research only: no
orders, International venue only, nothing dated after 2026-09-29 read, no oracle. Records:
[`docs/research/market-blend-l11-2026-10-25/`](../research/market-blend-l11-2026-10-25/README.md). Code:
`weather.calibration.market_blend`, `weather.calibration.dead_bucket`, `weather.calibration.dead_bucket_toronto`
(branch `claude/market-blend-l11-20261025`). Intervals: crossed [date-clustered] 95%, 2,000 draws, seed 20260921.

- **Market blend (walk-forward log pool of market and candidate; rule `e29c9a84…`, clarification 1 `46e1fac2…`).**
  Controls all PASS: served R 1.774 / 1.526 reproduced, MG-1 07-12 excess 0.011957, L6 own-stack −0.0036243,
  the w = 0 identity, and placebos (vectors deranged across dates) at mean w 0.005 and 0.007.
  - **MG-1, 07-12 (primary): NOTHING.** R 1.0017 [0.9990, 1.0077]; mean w 0.008, with w = 0 on 25 of 43 dates.
  - **Composite pre-13 (MG-1 + captured-METAR L6 stack): INCONCLUSIVE.** Run 2 R 0.9998 [0.9938, 1.0063],
    mean w 0.067, MDE80 0.006: w > 0, but no increment over the market is demonstrated. Run 2's composite rows
    supersede run 1's (`results-run1.md`, kept).
  - **P3d_N, 07-12 (rule `94b1603a…`): NOTHING.** Mean w 0.0051, w = 0 on 28 of 43 dates; R 1.0013
    [0.9992, 1.0075]. Unblended, P3d_N is R 1.1912 [1.1024, 1.2944] at 07-12 (descriptive).
  - **13-16 (secondary): NOTHING for every candidate.** MG-1 blend R 0.9858 and composite 0.9843 against the
    floor-only control (market plus hard floor) 0.9845: the afternoon "gain" is the hard floor zeroing mass on
    buckets already below the observed high, not model information. P3d_N alone at 13-16 is R 1.2795
    [1.1539, 1.4106] (descriptive, not pre-registered).
- **Dead buckets (buy NO on a bucket the observed running max has already killed, before the book reprices).**
  - **US stage A, rule r4, capture-time dating** (`fac8cd7211bb3c0e39edc8f95a7808c24fdf3a36558d9da5aab8462ff684a921`,
    recorded before any row): $25 `print_d1` **$0.03/day [0.00, 0.09]**, MDE80 0.06, **21 trades**, 3 of 48 dates
    nonzero, none of the traded buckets settled YES. NOT WORTH PURSUING. Sanity control (a)2 PASS: 3,011 of 3,098
    doubly dead buckets (0.972, minimum 0.95) have an r4 receipt at or after the killing IEM observation.
  - **Toronto stage A, rule r4-toronto** (`12902246a5358df5a2926314465e61dd4d1afaeedd408b994706e5b773c9f061`;
    dated Clarification 1 document `46c48626…`): **$0.00/day [0.00, 0.00], 0 trades filled over 51 labelled
    primary dates.** NOT WORTH PURSUING. Label-free measure (descriptive): **2 of 312** capture-dated dead buckets
    ever offered a NO ask with value >= 0.005. Run 1 (pinned WU only, 50 of 51 dates unlabelled) is superseded and kept.
  - **r3 early and r3 late:** $0.00/day [0.00, 0.00], 0 of 48 dates nonzero (nulls, firmer after the audit).
  - **Stage A's obs-dated $0.37/day [0.12, 0.69] on 57 trades is retracted as look-ahead** (RF "Dead-bucket
    stage A"). Under r4 it falls to $0.03: the 57 trades were exactly the late-receipt tail, and 26 of them have
    no capture by the end of the window.
- **Look-ahead audit (master ruling 2026-10-25; metadata and code only, nothing re-scored).**
  - Dead buckets: the r2/r3 code dated a bucket's death at the METAR's `valid_utc` plus an assumed 10 min. On
    the served-floor proxy, 41 of stage A's 57 primary trades were not yet dead at the book row and carried
    $0.366 of the $0.372; the served floor killed the bucket a median 15.5 min after the valid time.
  - **P3d_N's dev emitter is `last_in_hour`:** `pooled_residual_model.scan_replay_n` takes `high_so_far` and
    `current_temp` from the last replay snapshot captured in [h:00, h+1:00) and emits them for every row with
    `cutoff_hour = h`. Exposed rows, a lower bound at 10-minute receipt: **1,793 of 28,770 (6.2%) at 07-12 and
    1,057 of 18,591 (5.7%) at 13-16**. The look-ahead can only favour the candidate, so the P3d_N nulls above are
    firmer. Any positive result built on these vectors needs a no-look-ahead re-emission first.
  - MG-1, the L6 captured re-spec and the market side are clean: each uses the row's own captured fields.
- **Not claimed:** no edge, no forward result, no claim for Denver under KDEN labels, no claim that a blend with
  w > 0 adds information at this MDE. The market-blend and dead-bucket multiplicity belongs to the dev-window ledger.

### 10ae. The MG-2 chain: option N replaces the uncaptured forecast with the captured NBM mean, P3d_N is picked for 13:00+, and L7's loss atlas and checklist govern every dev read — lanes L3, L7 and L8, workstation, 2026-10-24/25

**Claim, at exactly this scope:** dev-window selection evidence only (rows from `DEV_WINDOW_LEDGER.md`); nothing
here is confirmation, edge or promotion evidence (§5). Nothing after 2026-09-29 was read.

- **L7 (loss atlas, pre-registration checklist, dev-window ledger; branch `claude/loss-atlas-prereg-20261024`).**
  The atlas reproduces the served control (R 1.774 [1.566, 2.052] all hours, 1.526 [1.369, 1.721] 00-16) and L5's
  diagnosis to every reported digit: 07-12 centre share 76.5% [63.1, 88.7], served bias −1.44 F [−2.20, −0.69]
  (ledger row 18). In delta mode MG-1 − served at 07-12 is −0.0139 [−0.0212, −0.0072] and closes 53.7% of served's
  excess, 43.1% of it centre and 10.6% width (row 19). The [checklist](PREREGISTRATION_CHECKLIST.md) and `prereg_check`
  now gate every dev-window rule.
- **L3, option N.** P3d's and arm A's forecast input (Open-Meteo Previous Runs, lead 1) has no captured analogue
  (ledger row 28; served forecast MAE 2.26 °F at 13-16, §10aa), while the captured NBM 07Z mean matches L9's NBP
  pipeline on 47,414 of 47,414 rows. Under pick-rule Clarification 2 the analogue (N) was approved: A_N is OLS + floor
  on the captured NBM 07Z mean, L8's running max and current temperature. **Pick-rule control: A_N − MG-1 at 13-16
  −0.3915, date-clustered [−0.5567, −0.2488], crossed [−0.6199, −0.1807], 13,958 rows** (row 29), before any P3d_N row.
- **The MG-2 afternoon pick (run once, row 31; pick rule `deb3eae3…`):** control reproduced −0.3915; P3d_N − A_N on
  11 markets −0.155 [−0.218, −0.098] (crossed [−0.330, −0.031]), 5 markets −0.108 [−0.194, −0.026] (crossed
  [−0.357, +0.044]); every hour 13-16 below 0 date-clustered; P3d_N − MG-1 −0.547 [−0.723, −0.399]. Pick = P3d_N.
  These vectors are the `last_in_hour` emission (§10ad), which is allowed for this model-vs-model gate only.
- **L8, MG-2 composite binding v2 — UNLANDED** (branch `claude/mg2-composite-binding-v2-20261025`; the forward rule
  file's sha256 at that tip is `bb5d2e61f3e44c1fd7628851caba749c5c67985d1d8229872f3f5bf1afc94f23`, status DRAFT, D0
  unset). Measured there: the P3d_N serve control PASSES, refitting L2's dev fit through the forward state export and
  re-emitting all 79,403 dev rows with no missing or extra row and max |dp| = 0.0. Nothing about the forward look is
  claimed; until that branch lands this bullet records a measurement on an unmerged branch only.
- **Not claimed:** that MG-2 beats the market (§10ad: w about 0); any forward or reserved-window result.

### 10af. Lane L2's rung ladder on the NBM-anchored arms closes the blend, trajectory and width levers: R-F NULL, R-G STOP at gate 3b, R-I KILL, R-J KILL — lane L2, workstation, 2026-10-25

**Claim, at exactly this scope:** development window only (dev scorecard, 43 scored dates 08-15..09-29, 473
market-days, 11 US markets; training and LOYO 2021-25). Each rung had its rule committed before any of its rows
existed. Intervals are date-clustered 95% unless marked crossed; dR is the dev scorecard's R difference. No edge claim:
every arm still trails the market. Nothing dated after 2026-09-29 was read. Records:
`docs/research/l2-pooled-residual-2026-10-24/` (`rung0712/`, `rungi/`, `rungj/`) on branch `claude/rung0712-20261025`;
the R-F and R-G score summaries are the `rung0712/rf_summary.txt` and `rg_summary.txt` files on that branch.

- **Arms.** B_N is the NBM-anchored pooled baseline: per-cutoff pooled OLS of y − (NBM mean + bias) on [1, g, max(g, 0)],
  hard floor. P3d_N_fix is P3d_N with the receipt look-ahead removed (each dev row uses the latest replay snapshot
  captured at or before its own capture) and the frozen WU whole °F conversion. L6 is the frozen MG-2 pre-13 arm, which
  is in-sample on this window and so favoured.
- **R-A, the NBM-anchored baseline and its HGB layer at 07-12 (rule `0b6be0d68f9f2c732468450a0abc5f075e43cc33a001bf9d76726160ccd5f25d`;
  proposals `5aefe029…`): NULL vs MG-1.** 21,664 covered snapshots. B_N − MG-1 −0.0094 [−0.0504, +0.0324] (crossed
  [−0.0740, +0.0560]); P3d_N_fix − MG-1 −0.0320 [−0.0663, +0.0041] (crossed [−0.0848, +0.0244]); the HGB layer is
  admitted over the baseline, P3d_N_fix − B_N −0.0225 [−0.0428, −0.0039]. R: B_N 1.2138, P3d_N_fix 1.1912, MG-1 1.2232.
  The receipt look-ahead fix changes nothing at 07-12 (P3d_N_fix − P3d_N +0.0007 [−0.0012, +0.0026]). PRIMARY5 (reported
  only): B_N − MG-1 −0.0640 [−0.1217, −0.0042], P3d_N_fix − MG-1 −0.0505 [−0.0969, −0.0059].
- **R-D, walk-forward hour-wise blend of MG-1 and P3d_N_fix (rule `7d497e3cf03ff33792f9575cc780d64ec122f3b2aae7eca6b8d0493c065d0b34`):
  WIN vs MG-1, superseded.** blend − MG-1 at 07-12 −0.0467 [−0.0665, −0.0257] (crossed [−0.0835, −0.0134]), every hour
  h07..h12 below 0; blend − P3d_N_fix −0.0147 [−0.0301, +0.0004]. MG-1 is not the composite's pre-13 arm (L6 is), so
  R-F re-asked the question against L6 and found nothing (below); R-D supports no Clarification on its own (RF "R-D
  blend"). R-E (descriptive): of P3d_N_fix − MG-1 at 07-12, the gain sits one and two buckets above the winner
  (+1: −0.0205 [−0.0336, −0.0086]; +2: −0.0087), that is MG-1's warm-side mass, not data freshness.
- **R-F, hour-wise blends against L6 (rule `cca30734771933f2028a9c46f7edbebd887af9ac9b9ece968b73325cf85ce7f6`): NULL.**
  blend(MG-1, P3d_N_fix) − L6 at 07-12 +0.0243 [−0.0033, +0.0523]; blend(L6, P3d_N_fix) − L6 −0.0096 [−0.0187, +0.0003]. No
  WIN, so no MG-2 Clarification or re-run plan was drafted.
- **R-G, morning trajectory columns (overnight min, 3-METAR trend, path gap) at 07-12 (rule
  `a8cf65640625605acdd0acad391bb267357957a5fd0bd9bd7e6e7a62dafe9b29`): STOP at gate 3b.** Parity and LOYO passed.
  Gate 3a B_G − B_N −0.0093 [−0.0199, −0.0000] (crossed [−0.0303, +0.0087]) passed; gate 3b P3d_G − P3d_N_fix −0.0048
  [−0.0113, +0.0012] failed (upper bound >= 0). Gate 4 (P3d_G and blend(L6, P3d_G) against L6) was not scored.
- **R-I, per-hour temperature (width) on P3d_N_fix (rule `b8a3d79ca13111db2bd667dc16e7a8418ddfe27bfaecbfaea23b099037341730`):
  KILL at gate 2.** Gate 1 (nested LOYO) passed barely: −0.00045 Brier [−0.00094, −0.0000084], about 0.05% of the
  uncalibrated Brier. Gate 2, dev 07-12, calibrated − uncalibrated: **dR −0.0022 [−0.0156, +0.0104]**; the walk-forward
  temperature (mean 1.40-1.88 by hour) was much sharper than the LOYO one (1.04-1.29) and did not transfer. Tempering L6
  is null too (+0.0024 [−0.0046, +0.0094], reported only). **The width lever is closed for the NBM family, extending
  §1c's closure to L6 and P3d_N_fix at capture time:** under the rule no other temperature grid, hour grouping, scale
  variant, per-market map, conditional trigger or isotonic form is run on any NBM-anchored arm.
- **R-J, the R-G trajectory columns at 13-14 (rule `e948c0a288f6e4a1cf4f3f143b8246cb11bc48e21cc67238187c180f58dfe171`):
  KILL at gate 3.** Parity passed, and LOYO B_G − B_N −0.0335 Brier [−0.0377, −0.0295] passed. Gate 3, dev P3d_G −
  P3d_N_fix at 13-14: **dR −0.0025 [−0.0207, +0.0158]** (crossed [−0.0298, +0.0260]). The h15 cell (−0.0451) is reported
  only and cannot seed a rung. **The trajectory family is closed for the afternoon:** no other trajectory, path-gap,
  trend or floor-feature variant is run on any NBM-anchored arm at any hour. **The separately pre-registered HRRR hourly
  path variant is excluded from this kill.** Reported: P3d_N_fix − the composite's post-13 arm (P3d_N) at 13-14 +0.0107
  [+0.0016, +0.0210], so an afternoon challenger built on P3d_N_fix starts behind the incumbent.
- **The common shape (R-G and R-J):** the new columns help the simple OLS arm a great deal (R-J dev B_G − B_N −0.0946 at
  13-14), but the HGB residual arm already carries that information (LOYO −0.004, dev null). A rung must be measured on
  the strongest arm, not only on the baseline.
- **Reopen if** (each also has an exhaustion-register row, §6):
  - R-A: a new NBM-family input (hourly NBS TXN, lane L12) changes the anchor, or the dev window grows; a new rule each time.
  - R-D: only if MG-1 becomes the pre-13 arm again (L6 dropped from MG-2).
  - R-F: L6 is re-fitted or replaced, or a 07-12 arm with a genuinely new input exists; never a re-cut of these blends.
  - R-G and R-J: on Aug-Sep, only an input not derivable from the METAR path (the pre-registered HRRR hourly path,
    R-K), or a strongest arm without the HGB residual layer; Oct-Dec is open under R10 below.
  - R-I: a fitted temperature or scale map only after a centre lever changes the NBM-family arm, once, under a new
    rule; spread information is a separate, open family (R9 below).
- **Scope of the closures, narrowed by master (rulings R9 and R10, 2026-10-25; master's rulings, not the owner's),**
  after the [lever inventory](LEVER_INVENTORY_2026-10-26.md) flags F3 and F4. They replace the wider wording above:
  - **R-I (R9):** the kill covers only fitted temperature or scale spread maps on NBM-anchored arms. Spread
    *information* (ensemble spread, NBS TXNSD, other day-specific predictors of spread) is a new family that needs its
    own pre-registration and the full ladder. Hard limits: no global sharpening, and the floor is never weakened.
  - **R-G and R-J (R10):** the kills cover the Aug-Sep development window only. An Oct-Dec rung needs a fresh
    pre-registration plus LOYO on Oct-Dec 2021-25 (where §10ac shows the overnight low and dewpoint help), and it can
    promote only through a forward test.
- **Not claimed:** edge, any forward result, or a claim about the HRRR hourly path.

### 10ag. The P3d_N afternoon look-ahead is worth +0.0004 Brier at 13-16 and flips no MG-2 gate; the market-relative atlas puts the 07-12 loss in winner-bucket mass — lane L2, workstation, 2026-10-25

**Claim, at exactly this scope:** descriptive dev-window reads, selection evidence only; no arm, rule or edge claim.
Nothing dated after 2026-09-29 was read. Records: `p3dn_diag/diag_summary.md` and `rungh/rh_summary.md` under
`docs/research/l2-pooled-residual-2026-10-24/`.

- **P3d_N diagnostic (fit held fixed; the whole gap is the inputs).** P3d_N's dev emitter takes the last replay snapshot
  captured in [h:00, h+1:00) for every row of hour h. At 13-14, 8,077 of 9,332 rows use a snapshot captured after the
  row's own capture (median 27.6 min later), and 180 use a METAR row first received after capture; no observation is
  observed after capture. **It is receipt look-ahead through `last_in_hour` snapshot selection,** acting mostly through
  high_so_far (feature and floor; share 0.79 [0.23, 1.44] at 13-14); WU whole °F rounding costs nothing.
  - **MG-2 composite − MG-1:** 13-16 −0.0155 with P3d_N against −0.0151 [−0.0192, −0.0113] with P3d_N_fix, so the fix
    costs **+0.0004 Brier [+0.0001, +0.0007], about 3% of the composite's 13-16 gain**; 00-16 −0.0049 against −0.0048.
    **No gate flips:** G1 and G2 pass in both versions.
  - **The pick survives:** P3d_N_fix − A_N −0.1413 [−0.2043, −0.0824] (crossed [−0.3226, −0.0154]) against the pick's
    −0.1551; conditions 2-4 and the tie rule hold. A_N's reader has the same look-ahead and was not fixed, so this is
    conservative for P3d_N_fix. Clause (d) (A_N − MG-1 −0.3915) does not involve P3d_N.
  - The forward MG-2 gate path is also `last_in_hour`; the as-of-capture path is primary for market comparisons. **A C7
    Clarification to the MG-2 rule is pending** (not written at the time of this entry).
- **R-H market-relative atlas, SELECTION EVIDENCE** (atlas `ff7ee23179be2beceb9c7b883ffb3ae37fb9966e1aee7f8ee6df0744ab9fb814`;
  57 dates, 626 market-days; reference is the capture-time market price, never `last_in_hour`; not pre-registered).
  - **At 07-12 the loss is winner-bucket mass:** position 0 carries +0.0093 of L6's +0.0081 excess and +0.0122 of
    P3d_N_fix's +0.0101; winner mass is 0.415 for the market against 0.325 (L6) and 0.292 (P3d), with the difference two
    or more buckets away. The excess is flat by hour (h07 to h12) and full size before any daytime observation.
  - **It is regime-flat:** no front, cloud, onshore, HRRR−NBM, NWS−NBM or observed-path tag separates from the window
    mean at 07-12.
  - **Re-centring on the market median removes about 25%** of P3d_N_fix's 07-12 excess (+0.0102 to +0.0077) and about
    15% of L6's (R-I alternative reading); only after re-centring does tempering help (+0.0012 for P3d). Centre, not
    width, is the lever (§1c).
  - At 13-16 P3d_N_fix loses most where the observed path runs below NBM's diurnal path (cold path +0.0183, 47% of the
    window excess); MG-1 alone fails on NBM-too-warm days, which P3d_N_fix mostly removes (+0.0083 against +0.0233).
- **Reopen if:** the look-ahead question reopens if the live serve path (L8 binding) differs from the as-of-capture
  dev path, or C7 is not adopted before MG-2 D0 (then the forward gate scores `last_in_hour` vectors and the 3% is a
  known optimism). The atlas is re-run for every newly picked arm and when the window grows; it never closes a lever.
- **Not claimed:** that any atlas cell is a lever on its own; every cell consumes the market benchmark and is never a
  gate, arm or improvement.

### 10ah. Reads from 2026-10-24/25 that reached no canonical file at the time: L5's hot-day centre arms and AFD KILL, L8's high_so_far parity fix not bound, L10's gap atlas, L11's stage C bound, and no fresh pre-07-31 dates — workstation, recorded 2026-10-25

**Claim, at exactly this scope:** dev window 08-15..09-29 (43 dates, 473 market-days, 11 US markets) unless stated;
development and selection evidence only; no edge claim; nothing dated after 2026-09-29 was read. Each was found by the
10-26 gap audit (owner 2026-10-25: "we are recording each thing we rule out yes? All of it is useful in some way
potentially"). Intervals are crossed date x market 95% unless marked date-clustered.

- **L5 hot-day centre lever, arms A and B, and the AFD screen: all KILL** (rules arm A `53fd0bc5…`, arm B addendum
  `42d30a2f…`, AFD `e146655a…`, each committed before scoring; record: the 2026-10-25 addendum of
  `docs/research/morning-loss-diagnosis-2026-10-24.md` on branch `claude/morning-loss-diagnosis-20261024` @
  `9eb04e6f4`). Candidate − control at 07-12, pooled 11:
  - A1, v2+NWS per-market debias, vs MG-1: −0.0001 [−0.0042, +0.0045], MDE80 0.0062: null.
  - A2, linear forecasts + overnight-low anomaly, vs MG-1: −0.0016 [−0.0059, +0.0033], MDE80 0.0068: null.
  - B1, full-year corpus GFS day-1 linear, vs MG-1: +0.0169 [+0.0069, +0.0269]: harm. The Aug-Sep-only fit also
    harms (+0.0122 [+0.0043, +0.0215], sensitivity).
  - B2, (v2 + B1)/2, vs MG-1: +0.0021 [−0.0032, +0.0084]: null.
  - AFD text features vs matched coastal intercepts: +0.0012 [−0.0006, +0.0040], date-clustered [+0.0003, +0.0020]:
    harm on the date-clustered interval, mostly Los Angeles (+0.0112 [+0.0026, +0.0195]).
  - **Reading:** the hot-day centre lever is MG-1 itself; every arm-A gain over served is MG-1's. A2 extrapolates beyond
    its training maximum on 8.8% of rows and still gains nothing on hot days (−0.0020 [−0.0086, +0.0035]). The
    coastal residual stays unexplained by free text.
  - **Reopen if:** a centre source outside MG-1's guidance family is captured (hourly NBS TXN, HRRR), or the coastal
    five get their own pre-registered rung; never a re-cut subset of these arms.
- **L8 HGB with the high_so_far train/serve parity fix (rule `55cf6989…`, dev-window ledger row 33 on
  `claude/mg2-composite-binding-v2-20261025`): KEEP vs base, not bound.** Fix − base at 00-16 −0.0088, date-clustered
  [−0.0171, −0.0008], crossed [−0.0232, +0.0058]; fix − MG-1 +0.2232 [+0.1489, +0.2927]. MG-1 sidesteps the skew, so
  the HGB serving family stays behind MG-1. **Reopen if:** an HGB serving arm re-enters a forward candidate; the fix is
  then a precondition, not a lever.
- **L10 gap-to-market atlas** (code `weather.calibration.gap_to_market_atlas`, branch `claude/stack-l10-20261025`;
  its rendered page is a workstation-local file, not in the repository): no pooled block or hour has R <= 1 for MG-1,
  arm A, P3d or the composite. Best on the primary five: composite 07-12 R 1.159 [1.070, 1.266]; MG-1 at 13-16 is
  1.697. Descriptive; it consumes the market benchmark. **Reopen if:** re-run for every new candidate; it is a map, not
  a test.
- **L11 dead-bucket stage C (rule r2 `177e9acf…`): gross upper bound $18.35/day [7.74, 34.73], not executable.** Denver
  is 89% of it and one trade 41%; 0 of 3,106 dead buckets settled YES. Stage A then measured executability, and under
  capture-time dating the mechanism is closed (§10ad). The bound assumes free, instant fills and observation-time
  dating; never cite it as value.
- **P2, fresh development dates before 07-31: none.** 07-12..07-30 lies in the sealed panel (7 of 20 decisions spent).
  A sealed-panel confirmation is available only for a winning candidate, proposed formally with its budget cost
  (master ruling 2026-10-25). **Reopen if:** a candidate wins on the dev window.
- **Not claimed:** edge, any forward result, or that a KILL here covers a different input or form.

### 10ai. Before 2026-10-23 the venue paid the WU band on every measured market-day, so the venue's own label is WU before the cutover and the venue rule from it — lane cutover reproduction, workstation, 2026-10-26

**Claim, at exactly this scope:** over 2026-08-01..09-29 (US built-ins, pre-embargo data only), WU sits in the venue's
winning band on **626/626** market-days and the routine-only venue rule on **617/626**. Over 08-11..09-29 the workstation
reproduction (F2 label table `368112bc…`, routine-only with the T-group; dev-layout WU labels identical on every row)
finds the venue rule ≠ WU on **13 of 517** market-days and the 2 °F band moved on **8**, matching the host's 537/550 tool
(`eeb2e1df4`); every one of the 13 is a SPECI effect (routine + SPECI equals WU on all 13).

- **Consequence (master ruling (10-25), reading B; DECISION_LOG):** labels are WU before 10-23 and the venue rule (WU
  fallback) from 10-23. Reading A, backfilling the routine-only rule onto history, would contradict the venue's paid
  outcome on 8 market-days; it survives only as an opt-in training view. No past evaluation changes.
- **Code:** `claude/venue-label-cutover-20261026` @ `28e96a3e7` (`weather.backtesting.venue_label_reader`), pregated
  2026-10-27; master runs the host roll verdict before landing. Design: lane cutover `design.md` (raw sha256
  `fb102ef9…`, local to the workstation).
- **Not claimed:** anything about post-09-29 agreement (embargoed); Toronto or Hong Kong; the captured paid band as a
  training target (it stays a reconciliation check, band-level and later than the observations).
- **Reopen if:** the venue's declared resolution rule changes again, or a post-embargo reconciliation shows the paid band
  departing from the venue-rule reconstruction. **Supersedes in part §10x's consequence line.**

### 10aj. A test meant to prove "no production importer" was vacuous: its regex held literal backspace bytes where `\b` was meant — found 2026-10-26

**Claim:** `tests/calibration/test_mg2_p3d_n.py`'s no-production-importer regex contained literal `\x08` bytes where the
word boundary `\b` was meant, so the pattern could never match and the test passed whatever the code imported.
Introduced in `fdd7ddc75`, fixed in `e40804dfe` (the C7/C8 line).

- **Sweep:** across every `origin/claude/*` and `origin/codex/*` head, only `origin/claude/mg2-composite-binding-v2-20261025`
  has a `\x08` byte in a `.py` or `.ps1` file (this test). `origin/master` has none in text files; the only hits are
  inside a binary `.csv.gz` fixture.
- **Ratchet (master ruling (10-25): APPROVED, implemented):** `tests/operations/test_source_control_bytes.py` on
  `claude/control-byte-ratchet-20261025` @ `8f4f831c0` refuses `\x00-\x08`, `\x0b`, `\x0c` and `\x0e-\x1f` in
  `src/**/*.py` and `tests/**/*.py`, with no baseline, in the CI audit job, as the docs audit's `control_character_errors`
  already does for Markdown. It lands in the 10-26/27 chain; its `tests/AGENTS.md` note lives on that branch.
- **Lesson:** a negative test must be shown to fail on a planted violation before it is trusted.
- **Reopen if:** a control byte is found in a `.ps1` file or another type the ratchet does not cover.

### 10ak. Lane reads of 2026-10-26: R-P killed, R-PD and R-N closed at 00-06, R-L stopped on an NBS format fact, R-R a dev WIN at 07-12 — workstation, recorded 2026-10-26

**Scope:** development evidence on dates ≤ 2026-09-29 plus LOYO 2021-25; rules committed before rows; nothing after
09-29 read. Rows and "Reopen if" lines: [exhaustion register](EXHAUSTION_REGISTER.md) §6 X30-X34. DEV_WINDOW_LEDGER rows
for these reads (and L3's rows 32-35 on `claude/l3-dev-ledger-rows-20261025` @ `217b99ea7`) are renumbered at the
merge-forward, because that file is not on this head's base.

- **R-P (L14), NBH remaining-hours max as a 13-16 centre shift: KILL at gate 3.** Gate 2 LOYO passed (B_P − B_N 13-16
  −0.0093 [−0.0118, −0.0067]), but the fits were mostly an intercept: slope b = 0 in 40% (B_N) and 55% (P3d_N_fix) of
  fits, a −0.2..−0.3 °F. On dev the shift reversed: gate 3 P3d_P − P3d_N_fix 13-16 dR +0.0141 [−0.0043, +0.0341]
  (pass = false; MDE ≈ 0.027), with harm at 15-16 +0.0425 [+0.0058, +0.0804] and h16 +0.0793 [+0.0351, +0.1263];
  R vs market 1.307 against P3d_N_fix's 1.293 (43 dates, 13,970 snapshots; score sha256 `3e278836…`, local at
  `C:\t\l14\rp\out\score`). **Lesson: a pooled LOYO intercept win is a bias correction, not information**; test a slope
  or a by-market split before reading a LOYO pass as an input's value. **Disclosure:** production never captured NBH,
  so even a pass could not have served. Rule `ed3236fa…` + RP-1 `f71a566a…` + RP-2 `70d4f01f…`, branch
  `claude/nbh-centre-1316-20261026` @ `ba11dd107`. **Reopen if:** NBH is captured forward and a slope-term rule passes.
- **R-PD and R-N (L3), 00-06: CLOSED.** Both passed LOYO (R-PD −0.0047 [−0.0073, −0.0022]; R-N −0.0062 [−0.0092,
  −0.0032]) and were NULL at gate 2 on dev (R-PD −0.0232 [−0.0520, +0.0047]; R-N −0.0105 [−0.0482, +0.0239]) under
  PD-1 `fa874b10…`. **The dev window underpowers 00-06**, so this is a null, not a precise zero. **Reopen if:** a larger
  00-06 window or a forward read under its own rule.
- **R-L (L2), NBS TXN at 07-12: STOPPED at gate 1a, not a kill.** Coverage 0.433 against 0.95; every miss is
  `column_absent`. **Format fact: NBS omits the target day's TXN maximum from cycles issued after that day's maximum
  period has begun (13Z and later); 12Z and earlier carry it.** So a "newest cycle" rule is missing by construction
  for most of 07-12. R-L2 (newest cycle that carries the TXN) is pre-registering; it yields an older centre at late
  cutoffs. Rule `3ce9a6f2…`.
- **R-L2 (L2), NBS TXN at 07-12 from the newest cycle carrying the target-day TXN: KILL at gate 3.** LOYO passed
  (B_L − B_N −0.0279 [−0.0308, −0.0248]); dev P3d_L − P3d_N_fix −0.0123 [−0.0283, +0.0038] failed (21,664 snapshots).
  NBS TXN is closed as a 07-12 centre input under both cycle rules. The selected cycle is 3-5 h stale at h10-h12, and
  median |n_txn − anchor| is 1.0 °F in training vs 0.0 °F on dev. **Corrected 2026-10-26:** that is not the dev anchor
  choice. The dev training-identical anchor equals the captured `usable_v2_mean` on 28,514 of 28,814 07-12 dev rows
  (about 99%; `C:\t\l2\p3d_n_dev\dev_emit_audit.json`, `dev_corpus_vs_captured_nbm_by_hour`), so the gap is a
  training-era (2021-25) vs 2026 difference between L9's NBM corpus and NBS TXN: rounding, version or cycle timing.
  **Mechanism:** dev gap ≈ 0 is an NBM v5.0 NBS product change (08-12Z TXN carried forward from 07Z, equal to the NBP
  07Z mean on ~95% of dev rows vs ≤ 0.45 in v4.x); cycle labels verified. **NBS-derived inputs trained on v4.x
  (2021-25) face a train/serve shift on v5.0 (2026): any NBS feature needs a per-version distribution check before
  use.** Source: `claude/rs-spread-20261026` @
  `e8ece032c`, `docs/research/l2-pooled-residual-2026-10-24/rungl2/nbs_label_check.md` (sha256 `41e5d1af…`) and `anchor_diag.md` (`68a97bbb…`).
  R-L3 is DROPPED (no rule written); an outcome-free, input-only diagnostic (|n_txn − L9 nbm| by year x hour) is
  running. Rule `a1f95786…`, branch `claude/rung0712-20261025` @ `6488c7a31`. **Reopen if:** the diagnostic identifies
  a training-side anchor defect (rounding, version or timing) that a fresh, differently named rule could correct on the
  training side.
- **R-R (L2), HRRR hourly path at 07-12: WIN on dev against L6.** Gate 2 LOYO B_H − B_N −0.0092 [−0.0112, −0.0073];
  gate 3 P3d_H − P3d_N_fix −0.0598 [−0.0813, −0.0401]; gate 4 blend_l6_H − L6 −0.0402 [−0.0603, −0.0198], every hour
  below 0. Still worse than the market: R 1.112 [1.072, 1.159]. Disclosures: the dev window has been read by every rung
  since R-A and R-R was chosen because R-K won; L6 is in-sample on dev. Rule `e3d92e1a…`, branch
  `claude/rung0712-20261025` @ `4fccf23f7`. **Not an edge and not promotable:** no captured-forward HRRR exists. The
  MG-2 Clarifications for R-K (post-13) and R-R (pre-13) and the forward recorder parity plan and its R-R addendum are
  DRAFTS, not applied ([recorder plan](../research/l2-pooled-residual-2026-10-24/drafts/hrrr_forward_recorder_parity_plan_DRAFT.md),
  [R-R addendum](../research/l2-pooled-residual-2026-10-24/drafts/hrrr_forward_parity_rr_addendum_DRAFT.md),
  [post-13 Clarification](../research/l2-pooled-residual-2026-10-24/drafts/mg2_post13_clarification_rk_DRAFT.md),
  [pre-13 Clarification](../research/l2-pooled-residual-2026-10-24/drafts/mg2_pre13_clarification_rr_DRAFT.md)). B is unaffected.
- **R-S (L15), NBM-published spread (NBP TXNSD anomaly) as a scale modulator on P3d_N_fix at 07-12: KILL at gate 2.**
  Gate 1 nested LOYO 07-12 −0.00099 [−0.00171, −0.00026] passed (19,657 rows); gate 2 dev 07-12 dR +0.00067
  [−0.00604, +0.00722] failed (21,664 snapshots, 43 dates, 473 market-days); the secondary 13-16 LOYO −0.00023
  [−0.00060, +0.00017] failed (no dev run). The kill closes the NBM-published-spread family (NBP TXNSD, NBP p90 − p10,
  NBS XND/TSD) as a scale modulator for every NBM-anchored arm; GEFS member spread, multi-model dispersion and
  observed-state predictors are not covered. Likely cause (a reading, not a gate): NBM v5.0 TXNSD on dev is compressed
  (25% of values equal 1). Rule `70908316…` (committed `8f80ea821`), plan `523d334e…`, `results.md` `604b0a0f…`, score
  `c3e8f0b2…`, branch `claude/spread-info-20261026` @ `efd95d8b9`. **Reopen if:** a future NBM version publishes
  uncompressed spread, or an Oct-Dec rung under R10. Register X37; DEV_WINDOW_LEDGER row 58.
- **Not claimed:** edge; any forward result; that a kill here covers another input form.

### 10al. Reads of 2026-10-26/27: R-U closes HRRR spread as width at 13-16, C10 is not adopted, SM-H is selected for MG-3 13-15, P3d_H 07-12 does not transfer to the cool season, R-V gate 2 splits — workstation, recorded 2026-10-27

**Scope:** history (2021-25) and development evidence on dates ≤ 2026-09-29; every rule committed before its rows;
nothing after 09-29 read. Register §6 X39-X42 holds the rule-outs. Ledger rows 42, 48, 50, 51, 55 and 56 are on
`claude/l2-dev-ledger-rows-20261026` @ `5a4861117`; rows 45, 47 and 49 on `claude/l3-dev-ledger-rows-20261025` @
`e4d224c72`. They are cited here, not copied.

- **R-U (L2), HRRR 3x3 spread anomaly as a width signal on P3d_H at 13-16: CLOSED at P0** (2026-10-26). History only,
  Aug-Sep 2021-25, 13,108 rows, z coverage 1.00. LOYO-μ pooled ρ(za, |dmax − μ|) −0.0007 (the bar is ≥ 0.05), with 2
  opposite-sign years (at most 1 allowed); per hour h13 +0.011, h14 +0.029, h15 −0.026, h16 −0.050; rise subset pooled
  +0.029; frozen-state μ −0.006 (reported). high_so_far removes most 15-16 error mechanically (median |dmax − μ| 0.83 →
  0.16 °F while sd9 stays near 0.6 °F), but h13-14 and the rise subset are below the bar too. **With X38 (00-06, 07-12),
  HRRR 3x3 spread as width is closed at all hours.** Rule `9441cc94…`; `ru_p0.json` sha256
  `cacdf2c84987865358444de1a63f29cac903d4ae8b738de804fb570a4adc5264`; record `ru/p0_result.md` on
  `claude/ru-hrrr-spread-1316-20261026` @ `a8c896a64`; ledger row 42 (commit `a55790422`). Register X39.
- **C10 (L2), season-matched P3d_N (SM-N) for MG-2 13-16: opened, not adopted** (master, 10-27). SM_N − P3d_N_fwd 13-16
  Brier +0.00356 [+0.00185, +0.00523] (history LOYO; h15 +0.0090, h16 +0.0075, both intervals above 0). The season gain
  is already in the served forward state `c6cc39f7…` (P3d_N_fwd − dev state −0.0569 [−0.0631, −0.0505]); MG-2 keeps
  `c6cc39f7`. Rule `8c59c1b6…`, audit `c10_audit.json` `9c237dd0…`, ledger row 50. Register X40; the earlier "~0.05"
  flag is retracted (RF "A season-matched P3d_N beats MG-2 at 13-16").
- **SM-H (L2): selected for MG-3 13-15** under clarification SMH-1 `b3007803…` (ledger row 51): SM_H − P3d_N_fwd 13-15
  Brier −0.01273 [−0.01625, −0.00936] on identical keys (12,372). Row 48's acceptance is SUPERSEDED: its −0.0669 is
  recorded as vs the dev state `dff5d797…`, never the served arm. **h15 alone is unresolved** (+0.0029 [−0.0019,
  +0.0080]); disclosed in MG-3's scope, not a decision input.
- **CS-1 cool-season transfer (L3, history only, descriptive):** (1b) P3d_H 13-16 vs the MG-1 analogue Oct-Dec 2021-25
  −0.310 [−0.319, −0.300] (16,496 rows; `part1b.json` `34284e45…`): **transfers**. CS-1's P3d_N column is the dev state
  `dff5d797…`, not MG-2's bound `c6cc39f7…`. (1c) on Oct-Dec 2024-25 (9,830 rows, 150 date clusters; 2021-23 Oct-Dec is a
  coverage gap): **P3d_H 07-12 −0.0063 [−0.0167, +0.0036], no transfer** (interval spans 0; Aug-Sep 2024-25 in-sample
  −0.0797); blend_l6_H −0.0163 [−0.0238, −0.0090], weakened but still below 0. Ledger rows 45, 47 and 49. Register X41.
- **R-V gate 2 (L2, dev, master accepted 10-27).** IEM MOS/NBE day-max (v_gap) as an afternoon input. **(a) PASS:**
  P3d_V_fwd − served `c6cc39f7` 13-16 dR −0.0206 [−0.0405, −0.0008] (13,970 snapshots), gain at 13-14 (−0.0318
  [−0.0538, −0.0096]; 15-16 +0.0044 [−0.0297, +0.0372]); R 1.266 vs 1.286, both still worse than the market. It is a
  capture-proposal pass only, for a future MG-2 successor refit; there is no MG-3 route, because SM-H serves h13-15
  and (b) killed v_gap there. **(b) FAIL, pre-registered KILL:** SM_HV − SM-H 13-15 ex-San Francisco dR −0.0007
  [−0.0185, +0.0164] (10,514 snapshots; out of season, Oct-Dec fits on Aug-Sep dev); San Francisco reported only,
  −0.0185 [−0.0485, +0.0083]. Rule `b0cf2a03…` + RV-C1 + RV-G2a `3605333b…` / RV-G2b `d9275e5e…`; run `rv-g2` at
  `claude/rv-c1-20261027` @ `1c8730c1a`; audit `g2_audit.json` `4f1d2441…`, dev MOS manifest `e0c6caa3…`, frozen
  states P3d_V_fwd `8a113250…` and SM_HV `3e91349e…`; ledger rows 55 and 56. Register X42.
- **Not claimed:** edge; any forward result; a binding change to MG-2 or B from any read here.

### 10am. R-Q: GEFS member spread as a scale modulator is killed at 07-16; its 00-06 variant is blocked on capture parity — lane L13 (L15's rule), workstation, 2026-10-29

**Scope:** history (2021-25) and development evidence on dates ≤ 2026-09-29; rule committed before any row; nothing
after 09-29 read. Ledger row 71 and register X43 hold the full record; it is cited here, not copied.

- **Variant A, GEFS v12 member SD as a scale modulator on P3d_N_fix at 07-12: KILLED** (master ruling, 2026-10-29).
  u = ln max(SD, 0.25), centred per market; m = clip(β·u, ±ln 2); s' = max(0.5, s·e^m). Gate 2 dev 07-12 dR −0.00260
  [−0.00650, +0.00094] failed (21,664 snapshots, 473 market-days, 43 dates; control byte-identical to `cd0034b9…`;
  no hour's lower bound above 0). **Kill scope:** GEFS member SD as a P3d_N_fix/L6-family scale modulator at 07-16,
  full breadth: no other cycle, product, member statistic, centring, clip, grid or hour grouping under any rung name.
  **Context only, not decision inputs:** gate 1 nested LOYO 07-12 −0.00067 [−0.00122, −0.00015] passed (19,657 rows,
  frozen β 0.20-0.30); the secondary 13-16 LOYO −0.00024 [−0.00062, +0.00014] failed. Precondition P is R-O's P under
  rule_rn Clarification 1 (`7a4354d05`, 10-27), which fixed P's definition before R-Q was scored; clarifications are
  part of the governing rule, so A is killed rather than blocked. The run used environment `c471b32b9` (the code
  commit alone lacked `ols_floor_ladder`; module byte-identical); master accepted the deviation.
- **Variant B, MG-1 warm half at 00-06 from the 18Z D-1 GEFS cycle: BLOCKED, not killed.** Precondition P_B (L11's
  limits: |mean diff| ≤ 1 °F, median |diff| ≤ 1 °F, r ≥ 0.95) failed as registered (p10 −1.41 °F) and again under R-Q
  Clarification 1 `1d47c8bb…` (capture side recomputed at history's node maximum, the same fix as R-O C1): p10 mean
  diff −1.156 °F, median |diff| 1.078, r 0.986; p90 −0.971, 1.000, r 0.988 (33,609 snapshots). The gap is concentrated
  in San Francisco (about −5.3 °F), Houston (−1.8) and NYC (−1.4 to −1.7); the rest are within about 0.9 °F, consistent
  with coastal cells on the 0.5° grid vs Open-Meteo (a reading, not a gate). **Train/serve fact:** captured Open-Meteo
  GEFS member highs are not a parity substitute for ap5 18Z history at 00-06. Gate B1 was not run; no 18Z recorder
  costing.
- Rule `rule_rq.md` sha256 `5703f06542b6f369bd32eaa2b84214bf4064b98490be3791b223c439d5e010c4` (`197729f4a`); C1
  `5641dbfc9`; code `19d822389` + `33b9fdd0a`; score `a2e0dcdb…`, LOYO `441ccce4…`, P_B `fdf28824…`, P_B C1
  `72b97e0b…`; `results_rq.md` on `claude/rq-run-env-20261029` @ `558889b13`. Code unlanded (P3d_N family B-bound).
- **Not claimed:** edge; any forward result; that the kill covers multi-model dispersion, observed-state predictors
  or a GEFS-anchored arm.

## Related

- [FINDINGS_DIGEST.md](FINDINGS_DIGEST.md) — the one-screen digest of this file; read it first
- [CAMPAIGN_LEDGER.md](CAMPAIGN_LEDGER.md) — the binding α budget for the sealed pre-boundary panel
- [HOW_WE_GET_THINGS_WRONG.md](HOW_WE_GET_THINGS_WRONG.md) — the recurring defect shapes behind the retractions
- Production trace documents: [replay does not reproduce what we served](REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md),
  [Gate 3 fired on a floor we never served](GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md),
  [replay floor diverges from served](REPLAY_FLOOR_DIVERGES_FROM_SERVED_2026-08-10.md),
  [served band floor defect](SERVED_BAND_FLOOR_DEFECT_2026-08-10.md),
  [finalize lost a settlement day](FINALIZE_LOST_A_SETTLEMENT_DAY_2026-08-11.md)
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
clusters, market clusters, market-days), and the interval treatment. **In the same change** add the
section to the section index, add or correct its one-line conclusion in
[FINDINGS_DIGEST.md](FINDINGS_DIGEST.md), and put a `SUPERSEDED` banner on any section it overtakes.
A mission report that lands without a section here has not been distilled. **Move retracted claims to
`RETRACTED_AND_FALSE_LEADS.md` rather than deleting them** — knowing what was wrong is what stops it
being re-derived.
