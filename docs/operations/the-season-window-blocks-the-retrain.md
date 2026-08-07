# The forecast archive covers the wrong 52 days of the year

Status: canonical. Measured 2026-08-06 on the production host. This is the binding constraint
on the project's #2 objective (find a model that beats the market).

## The finding

`SEASON_START = (5, 10)` / `SEASON_END = (6, 30)` in `src/weather/sources/forecast_history.py`.
The archive therefore holds **52 distinct month-days per year, May 10 through June 30**, in
every year 2018–2026. Verified directly:

```
distinct month-day values: 52     earliest: 05-10     latest: 06-30
retrain window Jul24-Aug07 present in archive: NONE
```

The first retrain targets 2026-07-31 with a ±7-day window — **Jul 24 to Aug 7. The archive
contains zero rows for those dates in any year.** Not sparse. Zero.

That is exactly why `-09-20a` reports the retrain blocking at **0 / 12,600 cells** with
**0 of 60 required market/year staging units complete**. 60 = 12 markets × 5 years
(2021–2025). Nothing is corrupt; the data was never fetched for this season.

## Why nobody noticed

The constant carries its own explanation:

```python
# Generous target-season window so one day's +/-7 climatology window is covered
# for late-May and June target dates. One API call per year covers it.
```

**It was correct when written.** The project's target dates were late-May and June. It expired
silently on 2026-06-30 and has been wrong for five weeks.

**And the coverage gate cannot see it.** `python -m weather.sources.forecast_history
fleet-coverage` reports **`OK markets: 12/12`** today. It checks existence, header validity,
row counts and per-field non-null counts — it never asks whether the covered dates have
anything to do with the target being trained for. **A gate that validates an archive against
the archive's own declared window is satisfied by construction.**

This is the **third** instance of one defect shape in this repository:

| Instance | The standard came from | Result |
| --- | --- | --- |
| Retrain gate (`ESTABLISHED_FINDINGS.md` §8) | the candidate's own manifest | gate shrinkable 20,160 → 2,520 cells |
| Model input surface (§4) | nothing watched it at all | 10 of 19 features dead for 5 weeks |
| **Forecast archive coverage** | **the archive's own `season_window`** | **12/12 OK while covering 0% of target dates** |

## Why this is the binding constraint

Every served model artifact was fitted **2026-06-10 to 2026-06-13** — the whole fleet, all 14
hour models. They were fitted on an archive that has never contained a July or August row, and
they are being served in August.

`ESTABLISHED_FINDINGS.md` §2 records that the base HGB is cool with root cause "a stale/cool
June prior", and §1 records that **centre displacement retires 74.97% of excess loss** while
width retires 10.94%. The season window is the structural reason the prior is June-bounded and
cannot improve by waiting: no amount of elapsed time adds July rows to an archive whose fetch
window ends June 30.

**Release #1 freezes these June HGBs.** Freezing before the archive is extended cements the
artifact that produces the dominant defect, and arms the confirmation window against it as
baseline.

> **Marked as inference, not measurement:** that the cool bias is *caused* by the season window
> is a hypothesis consistent with every fact above. It has **not** been traced through training
> row selection. Do not cite it as established. Trace it before acting on it as a cause —
> this project has twice paid for treating a consistent story as a proven one.

## The unblock is small, and free

Falsifying test already run — the free tier serves the missing window:

```
GET historical-forecast-api.open-meteo.com/v1/forecast
    latitude=43.6772 longitude=-79.6306
    start_date=2023-07-24 end_date=2023-08-07
-> 200, 360 hourly rows, 2023-07-24T00:00 -> 2023-08-07T23:00, 360 non-null temps (13.1-30.9 C)
```

One call, about a second. The code comment says "one API call per year covers it", and the
corpus planner wants 60 market/year units — so the whole extension is on the order of **60
free-tier calls**. `python -m weather.sources.forecast_history backfill` already exists.

Provider policy is closed and permits this: free-tier Open-Meteo, no paid API
(`forecast-source-and-training-population.md`). **This is not blocked on a decision.**

## What the season window does NOT explain

The blindness repair is a separate, smaller lever, and its properly-measured value is about
half what §4 implies. `-09-26a` measured full free-source parity fleet-wide with crossed
date × market intervals:

| Endpoint | Value |
| --- | --- |
| All-severe SSE | 737.065190 → 687.390626 = **6.7395%**, crossed 95% **[0.5208%, 14.3964%]**, D=5 M=12, 55 market-days |
| Pooled daily-first Brier | **−0.000721**, crossed 95% **[−0.032916, +0.030983]** — crosses zero, point is a mild *degradation* |
| Fleet reach | Toronto's direct moisture/pressure fields are **254 of 2,855 snapshots (8.90%)** |
| Verdict | **NO-GO for activation or fleet retrain** |

§4's `12.77%` describes the *theoretical* full repair; **6.7395% is what free sources can
actually deliver**, and the earlier `−3.41%` Toronto directional Brier probe did not survive
fleet measurement. Both figures are real; they are not the same intervention.

## Update this file when

The season window is extended and the archive re-fetched, or the coverage gate learns to
check date-range relevance to a declared target.
