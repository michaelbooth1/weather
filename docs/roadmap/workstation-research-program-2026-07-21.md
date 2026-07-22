# Workstation Research Program — 2026-07-21

For the workstation agent on `DESKTOP-RFCD2GH` (32 GB RAM, strong CPU). Read
`docs/roadmap/workstation-agent-handoff-2026-07-21.md` first — its hard rules
(no master pushes, no production-host access, mirror is read-only, branch +
report workflow) govern everything below. This document adds the *what*: the
research program the operator wants the workstation to run now that a full copy
of `data/` lives on this machine at `\data`.

The one-sentence mission: **production is grinding out the 14-day streak that
gates release #1; the workstation's job is to have a sharper, replay-proven
model variant waiting when that gate opens.** The known scoreboard blockers
after the streak are the model-skill gates (hourly / ten-minute /
trading-evidence) — skill, not plumbing. Every workstream below feeds that.

## Phase 0 — data staging and replay parity (do this before ANY experiment)

The mirror is a best-effort nightly replica; files that were mid-write at copy
time can be torn. No experiment result is trustworthy until the workstation can
reproduce a production number from its own copy.

1. Verify the mirror landed: `C:\Users\Michael\Documents\github\weather\data` populated, recent mtimes,
   and `data/snapshots` contains the market-day event directories (562+).
2. **Parity gate:** re-run an existing replay/scorecard over a window production
   has already scored (the replay corpus and frozen-baseline trend artifacts
   under `data/backtest` record production's numbers). Key entry points:
   `weather.backtesting.replay`, `weather.backtesting.replay_backtest`,
   `weather.calibration.pooled_candidate_replay`,
   `weather.reporting.scorecards.frozen_baseline_replay_trend`. Match
   production's recorded scores to within float noise. If they do not match,
   diagnose (torn file? missing subtree? version skew?) and record it — do not
   proceed on unverified data.
3. Record in your report exactly which mirror date each staged subtree came
   from. Every experiment cites its data provenance.

## Workstream A — under-sharpness (highest value)

The model is calibrated but under-sharp; it beats the market on corpus in
repair variants yet leaves probability on the table at the times of day that
decide P&L. Known, documented frontiers:

- **Evening lock-in (~40%)**: the model concedes to the market too late in the
  day. Quantify when informativeness collapses vs when it *could* lock in.
- **Predawn 03:00–05:00**: the documented skill frontier — the window where
  model and market diverge most and edge is winnable.
- **Morning skepticism is COSTING** (forecast-tracker verdict): the model
  under-calls warm mornings; the market does not.
- **H1 (core model audit 2026-06-20)**: serve-only ordinal smoothing shipped
  untuned. A pure hyperparameter sweep — ideal first experiment: cheap,
  bounded, replay-scorable. Also revisit H2 (leaky LOO) if it survives in
  current code.

Method: one variable per experiment, scored over the staged corpus vs the
market baseline with per-day paired deltas (report the distribution, not just
the mean). Use `weather.calibration.served_stage_ablation` and
`weather.reporting.scorecards.distribution_stage_attribution` to attribute
which serving stage gains/loses. 32 GB means you can hold full pooled training
in memory and run several sweep points in parallel — production never could.

## Workstream B — ablation and bakeoff sweeps (the CPU burner)

- **Per-source ablation** (`weather.backtesting.replay_ablation`): rerun the
  known result (forecast layer +0.027 essential; Open-Meteo individually ~zero
  net) on the bigger post-item-319 corpus (228+ days) and per-city. Sources
  that cost skill in specific cities are actionable config changes.
- **Taker bakeoff** (`weather.market.taker_bot_bakeoff`, plus
  `weather.reporting.research.unfenced_taker_bakeoff_sweep`): the "multiple
  taker versions" question is answered by replay bakeoff, not parallel live
  bots. Sweep policy variants (entry thresholds, sizing, YES/NO symmetry —
  the YES-only blindspot) over the staged tapes.
- **Pool-vs-city training**: the design audit direction (pool training + city
  features, C/F as I/O only). Expensive to train, cheap to score — exactly
  what this machine is for.

## Workstream C — new Tmax predictors (research audit 2026-06-20)

Top candidates, in priority order: **850 hPa temperature / mixing potential**
(item 32), soil moisture, forecast shortwave radiation, smoke/AOD. These need
historical data acquisition (Open-Meteo archive & co. are free; workstation
network use is fine — never touch production hosts). For each: fetch history
for the 12 cities, join to the corpus offline, measure incremental skill on
Tmax projection before proposing any capture-side change. A predictor that
does not move replay skill does not earn a collector.

## Workstream D (stretch) — maker research

`docs/research/MARKET_MAKING_PLAN.md` is the end-goal economics (maker rebates
are the real pool). With staged order-book tapes, quantify spread/depth/fill
distributions per market-day and evaluate quoting policies offline against the
recorded books. Evidence-only; no live surface.

## Evidence standard (applies to every workstream)

- Baseline first, variant second, **same corpus, same dates**, paired per-day
  deltas with a sign test or bootstrap CI — a mean without a distribution is
  not evidence.
- Hold out: tune on one date range, confirm on another. Never report the tuning
  window as the result.
- Negative results are results — record them in the report and stop that line.
- Anything that looks like a production win becomes: a branch + report +
  proposed follow-up for the production master to audit. The workstation never
  changes serving behavior itself.

## Cadence

One report file per completed experiment (`docs/roadmap/agent-report-YYYY-MM-DD-workstation-<topic>.md`
on its branch), pushed for the production master to review. Ask the operator
before starting anything projected to run longer than overnight. Keep total
disk use for staged copies under ~150 GB so the mirror target drive stays
healthy.

Suggested opening sequence: Phase 0 parity → A/H1 smoothing sweep (small,
proves the loop end-to-end) → B ablation rerun → then the bigger A frontiers.
