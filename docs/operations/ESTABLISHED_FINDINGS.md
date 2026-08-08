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
The retrain addresses a measured **−0.8346 C-eq** seasonal centre defect and centre is 74.97% of
oracle excess loss, so it remains worth doing — but **stop sequencing the programme as though the
retrain is the whole answer.** A parallel line of work on resolution is required, and §1 already
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
**"Build the corpus from the fields that do carry `_previous_dayN`" collapses to a single feature
and is not a model.** Do not commission that mission; the number is the answer.

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
both hosts.

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
