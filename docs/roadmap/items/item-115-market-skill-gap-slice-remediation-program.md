# 115. Market-Skill Gap Slice Remediation Program [COMPLETE 2026-06-17 - GAP OWNERS ASSIGNED]

Goal: turn the latest candidate-vs-market gap table into a concrete model
remediation loop that can close the aggregate `+0.0042` Brier deficit.

Source: the June 17 pooled candidate replay scores `0.0421` candidate Brier
versus `0.0436` current Brier, but market Brier is still better at `0.0379`.
The top positive gap drivers are named and repeat across reports:
`wu_lag_catchup_miss`, settlement distance `0`, all-fresh source rows, exact
bands, NYC, Seattle, cutoff hour `7`, stale-source rows, and boundary-rounding
errors.

Why this matters: item 48 correctly keeps promotion readiness open, but the
daily reports now identify the gap cells precisely enough to assign
experiments. Without ownership, the same generated blockers will appear every
day while the model only makes small incumbent-relative gains.

## Design

Keep no-market model improvements, market-informed CLOB overlays, and
paper-trading permission logic in separate lanes.

1. Create a generated gap-owner table from the top candidate gap drivers:
   slice, group, weighted gap, affected markets, existing roadmap owner, and
   next experiment.
2. Add targeted candidate variants for the largest no-market slices:
   settlement-distance-0 winner catch-up, exact-band calibration, 07:00 cold
   start calibration, NYC/Seattle residual calibration, WU lag catch-up, and
   boundary-rounding repair.
3. Score every fix as paired daily-first replay against current, candidate,
   and market baselines. Do not accept a fix that improves one top slice by
   moving the aggregate or another shadow market backward.
4. Keep CLOB overlays market-informed. They may support quote gating and edge
   permission, but cannot be used as evidence that the weather-only core model
   beats market prices.
5. Feed successful slice fixes back into item 48's promotion readiness table
   and item 47's known-edge/permission map.

- [x] Add a generated top-gap owner table to promotion refresh or daily
  learning.
- [x] Open one paired experiment for each top no-market gap slice.
- [x] Add market-specific diagnostics for NYC and Seattle shadow blockers.
- [x] Separate CLOB-informed improvements from weather-only model-skill claims
  in the report summaries.
- [x] Require aggregate and daily-first candidate-vs-market improvement before
  clearing broad readiness.

Acceptance: the latest promotion refresh either has candidate delta versus
market at or below 0, or every remaining positive market-skill gap has an
assigned owner, experiment artifact, and blocked/shadow reason in the report.

## Implementation Notes

`weather.reporting.promotion_refresh` now builds `gap_owner_table` rows from the
top positive candidate-vs-market gap drivers. Each row includes owner, roadmap
owner, affected markets, next paired daily-first experiment, experiment artifact,
claim lane, core-skill credit policy, and clearance rule. The refresh also
writes `market_skill_gap_experiment_v0.1` manifests under
`data/backtest/experiments/`; related source-freshness rows share one repair
experiment by design.

The report now has separate model-skill claim lanes, gap-owner experiments, and
NYC/Seattle market-skill diagnostics. Daily learning ingests the owner table so
the paired experiments appear as retrain inputs. CLOB-informed overlay rows are
explicitly marked as quote-gating evidence only and do not count toward
weather-only core-model market-skill claims.

## Verification

- `.\venv\Scripts\python.exe -m pytest -q tests\calibration\test_promotion_refresh.py tests\reporting\test_daily_learning.py`
- Regenerated `data/backtest/f_family_promotion_refresh.json`,
  `data/backtest/f_family_promotion_refresh_report.md`, and
  `data/backtest/experiments/*.json` from the current promotion evidence.
- `.\venv\Scripts\python.exe -m weather.reporting.daily_learning --backtest-root data\backtest --snapshots-root data\snapshots --json-out data\backtest\daily_learning.json --report-out data\backtest\daily_learning_report.md`

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-17 - GAP OWNERS ASSIGNED`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

