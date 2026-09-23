# Workstation handoff 2026-09-89b — observation clock and band decidedness (timing outputs T1 and T3)

Written 2026-09-23 by the production agent. Forward-plan item 6: the forecast stack's first money use is **timing**. This
mission measures two timing outputs from free public data on the workstation. Research and a small library; nothing is
served, traded or adopted.

## 1. Outputs

- **T1, the observation clock, per station** (the 12 configured markets' settlement stations): from IEM METAR history
  (`weather.sources.metar_history`, routine + SPECI) for 2026-06-01 to yesterday, the distribution of routine report minutes,
  SPECI frequency by hour of day and by temperature-change size, and the report-to-availability lag where measurable. For
  the US stations also compare with ASOS one-minute data (`weather.sources.asos_one_minute`) where available. Toronto
  (CYYZ) uses what the free sources offer and says what is missing.
- **T3, band decidedness:** for each station-day in the same period, from the observation history alone, the probability at
  each local time (15-minute grid) that the day's final maximum already equals the running maximum (band "decided from
  above") and the probability the running maximum is already above a given band (band "dead"). Report by station, month and
  hour; calibration of a simple estimator (for example running maximum plus the historical distribution of the remaining
  rise by hour) on held-out dates.
- **Settlement rule check:** the current Rules resolve on the WRH page's "Hourly Data" (mission 86a); compute T3 under both
  "all reports" and "hourly-rule" maxima and say where they differ.

## 2. Deliverables

Branch `codex/observation-clock-20260923` from `origin/master`: a pure library `weather.market.observation_clock` (or the
nearest owner package) with the station clock table and a T3 estimator; a `tools/` script that rebuilds the tables from
cached IEM responses; tests with fixtures; the report
`docs/roadmap/agent-report-2026-09-89b-observation-clock-and-band-decidedness.md` with the per-station clock table, the T3
curves and calibration, and a concrete proposal for correcting `info_event_calendar.py`'s fixed :52 METAR minute (a diff
proposal only; do not change that module).

## 3. Rules

Free, keyless public sources only, throttled (one request per second per host, as 86a did), cached under the worktree's
ignored `data/`; reuse 86a's cache if present. No `.env`, no credentials, no venue calls, no RE-1 worktree. Stop all
network work by 19:45 ET on 2026-09-23 (RE-1 session 2 from 20:00) and do not resume while a live session runs. Pushing the
branch is authorized.
