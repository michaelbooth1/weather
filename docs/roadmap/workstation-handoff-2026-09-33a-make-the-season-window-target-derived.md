# Workstation handoff 2026-09-33a — make the season window target-derived, and make the gate able to notice

Written 2026-08-06 by the production agent. Read on `origin/master` and execute.
**Runs in parallel with `-09-31a` and `-09-32a`. Branch from `-09-20a`, not from master — see §6.**

## 1. Goal

**Make it structurally impossible for the forecast archive to cover the wrong season while the
coverage gate reports healthy** — by deriving the fetch window from the target being trained for
rather than from a constant, and by teaching the coverage report to check date-range relevance
against a declared target.

**Build and prove it. Do not fetch to production.** The collection itself is an operator
decision pending `-09-31a`.

## 2. Why this, and why it is not blocked on `-09-31a`

The archive holds **52 month-days per year, May 10 – Jun 30, in every year 2018–2026**. The
first retrain targets 2026-07-31 ±7 days — **Jul 24 to Aug 7 — for which the archive holds ZERO
rows in any year.** That is why `-09-20a` blocks at **0 / 12,600 cells, 0 of 60 staging units**.

Three reasons this proceeds now rather than waiting on the seasonal-distance result:

1. **No summer retrain is possible without it, whatever `-09-31a` says.** `-09-31a` decides
   whether refreshing the prior *helps*. It does not change whether a retrain can be *fitted*
   for a July or August target. It cannot, today, for any of them.
2. **The gate is actively lying right now.** `python -m weather.sources.forecast_history
   fleet-coverage` reports **`OK markets: 12/12`** against an archive containing zero rows for
   the retrain's target dates. It checks existence, headers, row counts and per-field non-null
   counts, and never asks whether the covered dates relate to any target. That is a live
   monitoring defect independent of any retrain decision.
3. **The constant will expire again.** It already did once, silently, on 2026-06-30 — its own
   comment says it was sized "for late-May and June target dates". A target-derived window
   cannot repeat that.

**This is the third instance of one defect shape in this repository** (`ESTABLISHED_FINDINGS.md`
§8 and §4): *the standard came from the thing being judged.* The candidate-sized retrain gate,
the unwatched model input surface, and now an archive validated against its own declared window.

## 3. Start from this — do not re-derive it

- `SEASON_START = (5, 10)`, `SEASON_END = (6, 30)` in `src/weather/sources/forecast_history.py`.
- Verified on the production host: **52 distinct month-days, earliest `05-10`, latest `06-30`**;
  intersection with Jul 24 – Aug 7 is **empty**.
- **The free tier serves the missing window.** Already tested, do not re-test to prove existence:
  `historical-forecast-api.open-meteo.com/v1/forecast`, Toronto, `2023-07-24 → 2023-08-07`
  returned **200 with 360 populated hourly rows** (13.1–30.9 °C).
- Provider policy is **closed**: free-tier Open-Meteo only, no paid API. Licensing and the
  2021–2025 population are **decided** — `forecast-source-and-training-population.md`. **Do not
  stop this mission on either question.** That exact block has halted two prior missions.
- The corpus planner wants **60 market/year staging units** = 12 markets × 5 years, and the code
  comment states "one API call per year covers it".
- **No target-year row is ever in-sample** (§4c) — irrelevant to the fetch, relevant if you
  reason about training coverage.

## 4. Prioritised work

### P0 — the cheapest falsifier, and it is about the fleet, not Toronto

**Does the free tier actually serve the target window for all twelve markets across 2021–2025?**
Toronto 2023 is proven; twelve markets and five years is not. Probe the coverage — a small
number of calls, from the workstation, against the workstation's own data root.

**If any market or year is unavailable, incomplete, or returns a different schema, report that
and stop.** The whole plan rests on this being a routine backfill, and finding out that it is
not is the single most valuable thing this mission can deliver.

### P1 — derive the window from the target

Replace the constants with a window computed from the target date plus the climatology halo the
trainer actually needs (`HISTORY_WINDOW_DAYS` and the ±7-day target window are the existing
inputs — read them, do not invent new ones).

- The manifest must record **which window it was built for**, so a later reader can tell what a
  given archive is good for.
- **An archive built for one target must not silently satisfy a request for another.** Failing
  closed on a mismatch is the whole point; a warning is not sufficient.
- **Do not extend the archive's reach into serving.** `ESTABLISHED_FINDINGS.md` records that the
  archive is not training-only and that `model_features.py` reads it. **Do not change that
  coupling in this mission** — note it and leave it. If your change would alter what serving
  reads, stop and report.

### P2 — make the coverage gate able to notice

`forecast_history_fleet_coverage` must take a **declared target** and report BLOCK when the
archive does not cover the dates that target requires. The declared target comes from the
caller or from policy — **never from the archive's own manifest.** An archive must not be
allowed to certify itself; that is the defect being fixed.

Add the regression that proves it: an archive covering the wrong season **must** report BLOCK
against a target it cannot serve, and today's real archive against a late-July target is the
natural fixture.

## 5. Explicit non-goals

- **No production fetch. No write to production `data/`.** Prove on the workstation's own root.
- **No retrain, no fit, no candidate, no corpus staging run.**
- Do not change `SEASON_*` semantics for any consumer outside the archive build and its coverage
  report without saying so.

## 6. Branch base — read this carefully

**Branch from `codex/workstation-rescue-the-pit-retrain-lane-2026-09-20a`, not from master.**

`src/weather/sources/forecast_history.py` is already held by `-09-20a` and `-09-01a`. `-09-20a`
is the surviving retrain lane, it owns the file, and the 0/12,600 block this mission clears is
*its* block. Branching from master would create a competing edit to the same file in the lane
that has to consume it.

State in the report the exact `-09-20a` commit you based on, and refresh from current
`origin/master` before finishing.

## 7. Boundaries

`DELEGATION_CONTRACT.md` §2 in full. Mission-specific:

- You own `src/weather/sources/forecast_history.py` for this mission, inherited from `-09-20a`.
- Do not touch: `reporting/research/` (`-09-31a`); `reporting/casebooks/` (`-09-32a`);
  `model/model_features.py`, `model/free_source_feature_parity.py` (`-09-22a`, `-09-26a`);
  `operations/daily_refresh*.py` (`-09-29a`); `reporting/source_gates/` (`-09-28a`);
  `sources/wu_history.py` (production fix branch); `market/**` (held maker stack).
- **Roll sensitivity matters here.** `forecast_history.py` **is in the capture closures** —
  verify per file against `runtime_identity.source_scope_files` and state the verdict. This
  branch will need a quiet-window merge; say so plainly in the report.

## 8. What would falsify this mission

- **The free tier does not serve the window for the full fleet and year set.** Report and stop;
  the collection plan needs rethinking, not forcing.
- **The window cannot be derived from the target** without changing what serving reads. Then the
  archive's training/serving coupling must be separated first, and that is a different mission.
- **The coverage gate cannot be given a target** without the caller supplying one that ultimately
  originates in the archive itself. If every available caller would end up self-certifying, say
  so — a gate that reads its standard from the thing it judges is the defect, not the fix.

## 9. Branch and report

- Branch: `codex/workstation-make-the-season-window-target-derived-2026-09-33a`
- Report: `docs/roadmap/agent-report-2026-08-06-workstation-make-the-season-window-target-derived.md`

Per `DELEGATION_CONTRACT.md` §5, with a **per-file roll verdict** and production-host
reproduction paths. **Commit and push at whatever hour you finish** — §3, corrected 2026-08-06.
