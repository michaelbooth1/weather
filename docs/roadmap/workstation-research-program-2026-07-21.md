# Workstation Research Program — 2026-07-21

For the workstation agent on `DESKTOP-RFCD2GH` (32 GB RAM, strong CPU). Read
`docs/roadmap/workstation-agent-handoff-2026-07-21.md` first — its hard rules
(no master pushes, no production-host access, mirror is read-only, branch +
report workflow) govern everything below. This document adds the *what*: the
research program the operator wants the workstation to run now that a full copy
of `data/` lives on this machine, inside this clone's own `data/` directory.

**`data/` is the nightly mirror target, not workspace.** Production robocopies
onto it with `/MIR` every night at 04:30, which *deletes* anything there that is
not on the production host — proven 2026-07-22, when files deleted on production
were removed from the mirror automatically. Treat `data/` as strictly read-only,
write every experiment output somewhere else, and avoid reads during 04:30–05:00
while the sync runs.

## The primary objective (2026-07-22)

> **Does a leakage-audited, walk-forward-selected variant beat the market in the
> 09:00–14:00 slice on an untouched window?**

That single question is the program's north star; everything below either answers
it or is explicitly secondary. It replaces the older framing of "raise aggregate
Brier," which was both misleading and partly unwinnable — see the baseline below.

### Ground truth you must not misremember

Earlier versions of this document said the model "beats the market on corpus in
repair variants." **That was false.** Item 224's apparent win came from
`settlement_distance_bucket`, a post-settlement label feature; removing the leak
reverses the lift, and the variant is now permanently diagnostic-only. Item 187's
original permutation bundle had the same defect. **Two of two headline wins were
leakage — assume any large lift is a leak until proven otherwise.**

Measured reality (`docs/roadmap/production-readiness-audit-2026-07-11.md`,
141 countable market-days, 35,618 hourly checkpoints):

| Scope | Model Brier | Market Brier | Gap |
| --- | ---: | ---: | ---: |
| All hourly checkpoints | 0.07191 | 0.03734 | +0.03458 |
| 00:00–08:00 | 0.08092 | 0.05160 | +0.02932 |
| **09:00–14:00** | **0.07624** | **0.05388** | **+0.02236** |
| 15:00–19:00 | 0.05773 | 0.02217 | +0.03557 |
| 20:00–23:00 | 0.06435 | 0.00079 | +0.06356 |

Model error is 1.93× market error; every scored date, market, and hour trails.
The 09:00–14:00 slice is the target for two reasons: it carries the **narrowest
gap**, and it is where the **market itself is weakest** (0.05388). By contrast
the market's 20:00–23:00 Brier of 0.00079 means the outcome is effectively
resolved — no weather model can win there, and chasing the aggregate number just
imports that unwinnable slice into the objective.

The best legitimate weather-only challenger is dynamic-source state at 0.07635,
still +0.01681 behind the market. That is the number to beat.

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

## Workstream A — close the 09:00–14:00 gap (the objective)

Every experiment here reports its result **as a 09:00–14:00 paired delta vs the
market**, whatever else it also reports. Aggregate Brier may be included as
context; it is never the headline.

- **Regime router (start here).** The readiness audit's own recommendation, and
  it is not a feature hunt: a predeclared serve-time router — dynamic-source
  early/midday, exact-winner late, Item 50 pooled at lock-in. It must be selected
  inside nested walk-forward and confirmed on a window that was never used for
  selection. The recent window cannot both choose and vindicate the router.
- **H1 (core model audit 2026-06-20)**: serve-only ordinal smoothing shipped
  untuned. A bounded hyperparameter sweep — cheap and fully replay-scorable, so
  it is the right way to prove the experiment loop end to end before spending
  hours on the router. Also revisit H2 (leaky LOO) if it survives in current code.
- **Morning skepticism is COSTING** (forecast-tracker verdict): the model
  under-calls warm mornings and the market does not. This sits directly inside
  the target slice and is the most specific known defect in it.
- **Secondary — predawn 00:00–08:00** (+0.02932): the widest model/market
  *divergence*, which is where disagreement-driven edge would live even though
  the accuracy gap is larger. Worth attacking after the primary slice.
- **Not a target — evening lock-in.** Previously listed as a frontier; the
  market's 20:00–23:00 Brier of 0.00079 means there is nothing to win there.
  Study it only to explain the model, never to claim edge.

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

## Workstream D — maker research (promoted, no longer a stretch goal)

`docs/research/MARKET_MAKING_PLAN.md` is the end-goal economics, and the maker
rebate is the real pool. This is promoted deliberately: **maker P&L does not
require directional edge**, so it is the most plausible route to positive
returns given a model that trails the market on every slice today. With staged
order-book tapes, quantify spread/depth/fill distributions per market-day and
evaluate quoting policies offline against the recorded books. Evidence-only;
no live surface, no credentials, no orders.

## Evidence standard (applies to every workstream)

- **Leakage audit before any result is reported — non-negotiable.** For every
  feature the variant consumes, state where its value comes from and prove it was
  knowable at prediction time. Anything derived from settlement, the label, the
  realized high, or a post-hoc bucket is disqualifying. A variant that shows a
  large lift gets this audit *twice*: two of two historical headline wins here
  were leaks, so a big number is evidence of a bug until proven otherwise.
- Baseline first, variant second, **same corpus, same dates**, paired per-day
  deltas with a sign test or bootstrap CI — a mean without a distribution is
  not evidence.
- Hold out: tune on one date range, confirm on another. Never report the tuning
  window as the result. For the router specifically, selection and confirmation
  windows must be disjoint and declared before you look.
- Report the **09:00–14:00 slice delta** as the headline for Workstream A results.
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

Suggested opening sequence: Phase 0 parity → A/H1 smoothing sweep (small, proves
the loop end-to-end) → **A/regime router, scored on the 09:00–14:00 slice** →
B ablation rerun → D maker economics. Workstream C (new predictors) is the
longest-horizon line and should wait until the router result is in, since it adds
data acquisition on top of an unproven measurement loop.
