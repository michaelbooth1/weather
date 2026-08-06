# Workstation handoff 2026-09-20a — fill the point-in-time forecast gap

**Goal: collect the point-in-time forecast rows the first retrain needs, so it can be trained on
issue-qualified evidence instead of stitched evidence.** The licensing block that stopped `-09-16a`
and `-08-28a` is cleared. The training population is decided. The collector already exists and works.
What is missing is the *window*: the corpus stops on **June 30** and the retrain's slice is aligned on
**July 31**.

Branch from refreshed `origin/master`. Branch name:
`codex/workstation-fill-the-pit-forecast-gap-2026-09-20a`.

## Read this first — it is the answer to the question that stopped two prior missions

`docs/operations/forecast-source-and-training-population.md` is canonical and binding:

- **Free tier of Open-Meteo. No paid API, ever, without a new dated operator decision.** Collection
  through the existing Previous Runs integration is authorized by the repository owner.
- **The training population is 2021–2025.** This is decided. Do not re-open it, do not widen it, and
  do not stop to ask whether collection is permitted — it is.

If you find yourself about to halt on sourcing or licensing, you have found the exact failure mode
this file exists to prevent. Continue.

## Start from this — measured on the operations host 2026-08-05, do not re-derive it

All 12 markets already have `data/forecast_history/<icao>/`, each ~18.5 MB of `forecast_long.csv`.
The collector `src/weather/sources/forecast_history.py` is complete and has a working CLI
(`--market <id> backfill`), `fetch_previous_runs_payload`, `PREVIOUS_RUNS_URL`,
`DEFAULT_PREVIOUS_RUN_START_YEAR = 2021`, `DEFAULT_PREVIOUS_RUN_LEADS = (1..7)`.

Toronto's `manifest.json`, generated **2026-06-23** (43 days stale), tells the whole story:

| Field | Value | What it means |
| --- | --- | --- |
| `season_window` | start `[5, 10]`, end **`[6, 30]`** | **the defect** — 52 target dates per year, ending June 30 |
| `previous_runs.per_year_rows` | 2018–2020: **0**; 2021–2025: **8,736** each | PIT rows exist for exactly 2021–2025, and nowhere else |
| `covered_years` | `[2018 … 2026]` | claims nine years the PIT evidence does not support |

And the per-basis split of `forecast_daily_by_issue.csv` (Toronto, 2,596 rows) is unambiguous:

| Years | `fixed_lead_day_offset` (PIT) | `stitched_continuous_archive` |
| --- | ---: | ---: |
| 2018, 2019, 2020 | **0 per year** | 52 per year |
| 2021–2025 | 364 per year (52 dates x 7 leads) | 52 per year |

**This independently confirms the 2021–2025 decision on the evidence rather than on argument.**
2018–2020 are not a population we chose to exclude; they are a population that does not exist in
issue-qualified form. Do not spend time re-litigating them.

## The actual gap

`8,736 = 52 dates x 7 leads x 24 hours`. The PIT corpus covers **May 10 – June 30 only.**

The retrain's slice is aligned on the `2026-07-31` artifact regime boundary, and the markets we trade
run through the summer. **There is currently zero PIT forecast coverage for late July, August, or
September in any market, in any year.** A retrain run today would have no issue-qualified evidence
for the part of the season it is actually going to serve.

## P1 — extend the season window and collect

Extend the season window end from `[6, 30]` to **`[9, 30]`**. Keep the start at `[5, 10]` so existing
rows stay comparable and the append stays idempotent. Collect PIT rows for **2021–2025** across all
**12 markets**.

Sequence it, do not fire all 12 at once:

1. **Toronto first, alone.** Report exact wall time, exact bytes added, request count, and any
   throttling or error response from the free tier. That is your sizing measurement.
2. **Stop and check the budget.** Expected order of magnitude is ~2.5x current file size per market
   (52 dates to ~129) and roughly 60 previous-runs requests fleet-wide. If Toronto alone projects
   past **1.5 GB fleet-wide** or the free tier throttles, stop and report rather than pushing through.
3. Then the remaining 11, paced. Keep the existing `--pause` discipline; a polite collector is the
   condition of continuing to have a free source.

**Clamp 2026 to completed target dates only.** September 2026 has not happened. A partial current
year is correct and expected; a fabricated one is not.

## P2 — make the manifest stop overstating what it has

The manifest currently reports `covered_years: [2018 … 2026]` on the strength of stitched rows. That
single field is load-bearing far outside this module: **the retrain preflight derives its required
matrix from `source_payload["covered_years"]`**, so a manifest that counts stitched years inflates
and misdescribes the gate.

Your job here is narrow and specific:

- Report **PIT-qualified years separately** from any-basis years. A year with zero
  `fixed_lead_day_offset` rows is not a covered year for training purposes, and the manifest must say
  so in a field a consumer can read without parsing the CSV.
- Make the stitched rows **explicitly identifiable and separable** at read time. They are not garbage
  — they are legitimate compatibility evidence — but they are the exact contamination the retrain
  exists to remove, and nothing should be able to admit them into a fit by accident.
- Record the season window and the per-year, per-basis row counts in the manifest so coverage is
  checkable without a rescan.

**Do not touch `base_retrain.py` and do not try to repair the preflight's self-sizing gate.** That
repair lives on the held `-09-12a` lane and binds the year set into the hash-bound retrain plan. The
two halves must stay separate: **the source manifest proves coverage; the plan chooses the matrix.**
Your half is making the proof honest. Say in your report what a consumer should read instead of
`covered_years`.

## P3 — prove the coverage

Deliver a coverage report that states, per market and per year: PIT target dates, leads present,
hourly rows, and any hole. A hole is a finding, not a failure — report it, do not paper over it.

Then answer the question the retrain will actually ask: **for the `2026-07-31`-aligned slice, is the
PIT matrix complete across all 12 markets and all 5 years, and if not, exactly which cells are
missing.** That sentence is the deliverable.

`class_support` is expected to be tight in the severity tail — Dallas 108 F, Denver 101–102 F,
Houston 103–104 F, Seattle 95 F. Extending into August and September should *help*, because the
hottest days of the year are in that window and were previously outside the corpus entirely.
**Measure whether it does.** If tail support is still short, say so and stop there — do not widen
`covered_years` to reach it. The decision record names observation history as the next place to look,
and that is a separate mission.

## Boundaries

- **Read-only with respect to production.** Write nothing under `data/` on the production host,
  register nothing, start no loop, mutate no scheduled task, never write to the mirror or
  `D:\weather-mirror`. Collect into your own clone.
- **Do not commit the collected CSVs.** Never add `lfs: true`. The deliverable is the collector, the
  manifest contract, the coverage report and the exact reproduction command — production re-runs the
  identical idempotent command in a quiet window.
- **Free tier only.** No paid provider, no paid tier, no new credentialed endpoint. If a better
  *free* source looks compelling, note it in the report; adopting it is out of scope here.
- Never read or expose `C:\Users\micha\.weathersync.cred`.
- `docs/operations/reserved-confirmation-window.md` wins over this document. **No dates are reserved
  today**; the window is armed but undated. **Check the file when you run — do not assume it is still
  empty** — and exclude any reserved date from collection and from the coverage report.
- Do not weaken the trusted observed-high floor, do not relax the promotion gate for `harvest_only`
  rows, do not change providers or paid tiers.
- Per-file roll verdict from the retained capture-loop import closures, not the `SOURCE_PATTERNS`
  glob. State which of the snapshot / CLOB / observation-trigger / CLOB-enrichment closures each
  changed file enters. `forecast_history.py` is a collection module — **check it rather than
  assuming it is roll-free**, because a roll verdict is what decides whether this can merge outside
  the quiet window.
- No PR, no merge. Commit to the exact branch name above and push that branch only.
- Report to `docs/roadmap/agent-report-2026-08-06-workstation-fill-the-pit-forecast-gap.md`.

## What would falsify this mission

- Finding that Previous Runs will not serve July–September for past years, or serves them with a
  different issue-time semantics than the May–June rows, would mean the corpus cannot simply be
  extended — report the exact semantics rather than collecting rows that only look compatible.
- Finding that the existing 2021–2025 May–June PIT rows fail their own issue-time contract would be a
  bigger finding than the missing window, and would outrank it. Check them before adding to them.
- Finding that `season_window` is consumed somewhere that assumes a June end would make this a wider
  change than a config edit; find the consumers before you widen it.
- Finding that extending to September does **not** improve `class_support` in the severity tail would
  mean the tail problem is not a window problem, and the observation-history route becomes the
  priority. That is a useful negative result — report it plainly.
