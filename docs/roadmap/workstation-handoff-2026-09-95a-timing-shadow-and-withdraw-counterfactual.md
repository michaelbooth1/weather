# Workstation handoff 2026-09-95a — timing outputs as a shadow product, and a withdraw-policy counterfactual

Written 2026-09-24 by the production agent. Serves **Q-07** (and informs Q-02, Q-06). Forward-plan item 6: the forecast stack's
first money use is timing. The host audit named the timing outputs the highest-value model deliverable (no retrain, no roll).

## 1. Build (branch `codex/timing-shadow-20260924` from `origin/master`)

1. A pure library (extend `weather.market.observation_clock` from `origin/codex/observation-clock-20260923`, or the nearest
   owner package) that, for any station and minute, emits: minutes to the next routine METAR (station-specific modal minute),
   minutes since the last one, known model-publication windows (NBM 01/07/13/19Z, GFS and HRRR object times as 92a/94a
   measured them), and T3 — the probability each band is already decided (the 89b estimator), as a per-band risk score.
2. A shadow runner that writes these per-minute rows for the configured bands from captured or cached public inputs (no venue
   calls beyond public reads; nothing served, traded or adopted).

## 2. Evaluate (descriptive; any confirmatory claim is pre-registered later)

Using the 94a public-trade cache (`origin/codex/fill-clustering-20260924`, rebuilt locally) and 89b histories:
1. For withdraw policies (pull all quotes for W minutes around each routine METAR; around model publications; when T3 crosses a
   threshold; combinations), the share of public trade notional and of large price moves (>= 3 c in 5 min) that fall inside
   pulled windows, versus the fraction of band-minutes pulled (the reward cost).
2. Compare against a clock-only baseline (pull at fixed times with the same pulled fraction). A policy is interesting only if
   it removes clearly more large moves per pulled minute than the baseline.
3. Report by station, day-ahead and time of day; counts and ratios only, date x market clustered if any interval is shown.

## 3. Deliverables and boundaries

Tests with fixtures; `docs/roadmap/agent-report-2026-09-95a-timing-shadow-and-withdraw-counterfactual.md` (verdict first,
the policy table, the best policy's trade-off, limitations: public prints are not our fills). No `.env`, no credentials, no
RE-1 worktree; heavy runs through `workstation_heavy.ps1`, never during an RE-1 session. Push is authorized.
