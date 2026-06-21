# 182. Distribution Stage-Attribution Harness [COMPLETE 2026-06-21 - SETTLED STAGE ATTRIBUTION LIVE]

Goal: make every heuristic stage's marginal contribution measurable so the
distribution stack can be tuned or retired with evidence instead of intuition.
This is the audit's highest-leverage, lowest-risk build and the measurement
substrate for the other core-model items.

Source: `docs/roadmap/core-model-audit-2026-06-20.md` finding M3 (the "biggest
opportunity"). `_estimate_distribution_result` runs ~13 post-processors in fixed
order, each mutating one `scores` dict, so their interactions are unmodeled —
items 169 (predawn over-diffusion) and 170 (late-day under-confidence) are the
bill coming due. The pipeline already records every intermediate distribution via
`DistributionPipelineState.snapshot(...)`
([model_distribution.py:76-91](../../../src/weather/model/model_distribution.py#L76))
and persists them in `component_payload`, so the data needed for attribution is
already captured.

Why this matters: there is currently no routine measurement of each stage's
marginal effect on held-out Brier/log-loss. Stages added to fix one failure can
silently hurt another regime (the floors/caps were already measured net-negative
for Toronto once). Attribution turns the existing instrumentation into an audit
and lets every other repair be proven.

## Design

1. Build a replay-corpus harness that, for each settled market-day, scores every
   named snapshot (`climatology_prior`, `feature_blend`, `post_live_signals`,
   `forecast_pull`, `late_day_lockin`, `final_model`, ...) against settlement.
2. Report each stage's marginal Brier/log-loss delta (stage N vs N−1) sliced by
   cutoff hour and regime, plus winner-probability and effective-band-spread
   movement.
3. Register a schema, CLI, and tests; persist JSON + Markdown in the daily
   evidence bundle and wire into daily learning / promotion so a net-negative
   stage is an explicit removal candidate.
4. Use the harness as the measurement substrate for items 178–181, 183, 184,
   169, and 170.

- [x] Add `weather.reporting.distribution_stage_attribution` with schema
  registration and tests over the snapshot payloads.
- [x] Emit per-stage marginal Brier/log-loss by hour and regime on the settled
  corpus.
- [x] Run it in the daily refresh bundle and surface it in daily learning.
- [x] Flag at least one net-negative stage with evidence.

Acceptance: a canonical report attributes held-out Brier/log-loss to each
pipeline stage by hour and regime over the settled corpus, is regenerated in the
daily bundle, and identifies at least one stage that does not pay its way.

Completion note 2026-06-21: added
`weather.reporting.distribution_stage_attribution`, schema
`distribution_stage_attribution_v0.1`, tests, CLI, and a daily-refresh step that
writes `data/backtest/distribution_stage_attribution.json` and
`data/backtest/distribution_stage_attribution_report.md`. The local settled
component corpus run scored 185 settled folders and 2,357,091 attribution rows.
It flagged `forecast_pull` as the top net-negative stage by log-loss
(`mean_delta_logloss=+0.1653`, `mean_delta_brier=-0.0049`), giving item 181 and
the downstream forecast-stage work a concrete measurement substrate.

Related: items 169, 170, 178, 181, 183, 184, 26; `[[replay-corpus]]`,
`[[replay-ablation-findings]]`.
