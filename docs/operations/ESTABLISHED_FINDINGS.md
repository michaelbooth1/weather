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
2. **Find a model that beats the market.** We currently do not. See §1.
3. **The end goal is the market-making bot.** MM outranks the taker. The taker is deprioritized and
   its tape has been deleted.

**The primary model objective is the 09:00–14:00 local slice**, leakage-audited and walk-forward — not
aggregate Brier. Aggregate-Brier chasing was explicitly abandoned: it hides the slice where the model
is weakest and where the tradable edge would live.

---

## 1. We do not beat the market

This is the central finding of the project. Treat any result claiming otherwise as suspect until it
survives the method rules in §5.

| Finding | Value |
| --- | --- |
| Gap on the clean regime | **1.24x**, not the 1.7x figure from contaminated windows |
| Nature of the gap | **Pure sharpness.** Not calibration |
| Skill decomposition | **98.88% resolution / 1.12% reliability** |
| Consequence | **Recalibration cannot close it.** The gap is an *information* problem |
| Blending model with market | **Hurts** on clean data |

**Centre, not width, is the lever.** Oracle ceiling analysis: correcting the distribution *centre*
retires **74.97%** of excess loss; correcting *width* retires **10.94%**.
**Never globally sharpen** — it is the wrong axis and it degrades calibration for nothing.

**Loss is concentrated in a severity tail.** **4.26% of rows carry 60.2% of total loss.** On those
rows the market's modal band wins roughly **98%** of the time against our roughly **24%**. Any work
that improves the pooled average while leaving the tail alone is close to worthless.

---

## 2. The cool bias is real and is not correctable at serve

| Property | Value |
| --- | --- |
| Magnitude | **−0.6641 C-equivalent** |
| Crossed 95% interval | **[−1.1164, −0.2482]** |
| Support | D=34 date clusters, M=12 markets, 399 market-days |
| Survives crossed clustering | **Yes** — one of only two headline results that do |

**Do not implement a serving-side offset.** Market heterogeneity forbids it: the bias is not uniform
across markets, so a global correction helps some and harms others.

Established sub-findings:

- **The base HGB itself is cool.** Root cause is a stale/cool June prior.
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

---

## 6. Training data is contaminated at fit time

- **`forecast_high` is not point-in-time.** The trainer reads a 2-column stitched file; the
  point-in-time file exists and is **unread**. The **fit is contaminated; evaluation is not.**
  Measured lookahead is ~6% of the cool bias — real but not the main story.
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

## Related

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
