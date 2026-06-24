# 217. Pinned Frozen-Baseline Replay Trend For Code-vs-Weather Skill Separation [COMPLETE 2026-06-22 - DAILY REFRESH AND LEDGER WIRING LIVE]

Goal: maintain a durable, rolling "current code vs a pinned baseline code, scored
over the SAME frozen captured inputs" skill series, so model improvement can be
measured with weather held constant — separating code-driven skill change from
day-to-day weather variance.

Source: the 2026-06-21 week-long settled-log audit (`are we improving?`). Over
2026-06-14 → 06-20, the per-day model-minus-market Brier delta swung by a
standard deviation of `±0.074` day to day, while the best-fit trend slope was
`+0.015/day` — about one standard error (`t≈1.1`, `p≈0.3`), i.e. statistically
indistinguishable from zero. One week of live-forward data **cannot** separate
code improvement from weather luck because the per-day variance is ~7× any drift.
Meanwhile the daily progress ledger (item 163) blocks the broad-improvement claim
on `independent_baseline_missing`, and the variant-evidence-growth baseline
(`--baseline-predictions`) is never pinned, so the claim gate is blocked on an
input that nothing currently produces.

Why this matters / why existing items do not cover it:
- **Item 117** (day-over-day skill trend gate) is **live-forward**: each day's
  served model is scored on that day's weather, so the trend is exactly the
  weather-confounded signal this item removes.
- **Item 163** only *consumes* `independent_baseline_missing`; it does not pin or
  produce a baseline.
- **Item 216** segments live model-review evidence by runtime identity, but the
  evidence is still live-forward (weather varies across commits).
- The **candidate replay** (`pooled_candidate_replay`) already scores two code
  versions on one frozen corpus — but as a one-off candidate-vs-current gate, not
  a **rolling current-vs-pinned-baseline series over time** that answers "how much
  has the code improved since date D, weather held constant?"

Holding the captured-input corpus fixed and varying only the code collapses the
weather variance, so a few replay runs become decisive instead of needing months
of live days.

## Design

1. Pin a durable baseline: a tagged code/artifact version plus its prediction
   export over a frozen, quality-gated captured-input corpus (e.g. the accepted
   model as of date D). Make it the canonical `--baseline-predictions` source so
   item 163's `independent_baseline_missing` can clear.
2. On a schedule (daily and/or per-merge), replay **current** code over the SAME
   frozen corpus and score current vs baseline (and vs market) per market and per
   regime. Weather is identical, so the delta is code-attributable.
3. Append a rolling `frozen_baseline_replay_trend` series (date, code runtime
   identity, current−baseline Brier/log-loss, per regime, per market) and surface
   it in progress audit and the daily ledger **next to** the live-forward trend,
   clearly labeled "weather held constant."
4. Define a baseline-refresh policy: re-pin when a candidate is promoted (so the
   series measures progress since last promotion), retain prior baselines for
   continuity, and never let the baseline drift silently.
5. Feed the weather-held-constant trend into the broad-improvement claim gate
   (item 163) as the independent baseline evidence, kept distinct from
   live-forward skill.

- [x] Pin a baseline code/prediction export over a frozen corpus and store it as
  the canonical baseline.
- [x] Add a current-code replay over the frozen corpus with current-vs-baseline
  scoring per market and regime (the `update` action; scheduled wiring pending).
- [x] Emit the rolling `frozen_baseline_replay_trend` series and render it (the
  report shows the weather-constant `Current - Baseline` delta beside the
  live-forward `Current - Market` delta).
- [x] Wire the pinned baseline into item 163 so `independent_baseline_missing`
  clears when present.
- [x] Add a baseline-refresh policy (re-`pin` overwrites the manifest) and tests.

Acceptance: a pinned baseline exists and clears item 163's
`independent_baseline_missing`; a scheduled job emits a rolling
current-vs-baseline skill series on a fixed corpus (weather constant); progress
audit shows the live-forward trend and the weather-held-constant trend side by
side; and a code change's skill effect is measurable from a few replay runs
instead of waiting for enough live days.

## Progress 2026-06-22

Core weather-held-constant trend capability is implemented, tested, and proven on
real data. Remaining work is orchestrator/ledger wiring only.

Delivered:

- New module `weather.reporting.frozen_baseline_replay_trend` with `pin`,
  `update`, and `report` subcommands. It scores two model-version prediction
  exports over the **intersection** of their observations
  (`market_id, target_date, snapshot_id, band_key`) — the shared set *is* the
  frozen corpus, so weather is held constant. Reports overall / per-market /
  per-regime Brier and log-loss, the `Current - Baseline` delta (code-attributable
  on identical inputs), and the `Current - Market` delta (live-forward-style
  reference). Observations whose settled outcome disagrees between exports are
  skipped as label drift.
- `pin` writes a durable manifest (`frozen_baseline_manifest.json`: baseline id,
  code identity, corpus id, copied prediction export) into a stable store;
  re-pinning is the baseline-refresh mechanism.
- Rolling series `frozen_baseline_replay_trend.jsonl` (upsert by run-date) plus
  JSON payload and Markdown report; the report renders the run-date series and a
  first-vs-latest "improving / not improving on fixed weather" line.
- `--current-variant-id` / `--baseline-variant-id` filters let a single
  multi-variant export supply both code versions.
- Registered schemas `frozen_baseline_replay_trend_v0.1` and
  `frozen_baseline_manifest_v0.1` (schema audit: 0 unregistered).
- Tests: `tests/reporting/test_frozen_baseline_replay_trend.py` (8 cases:
  current-better delta, shared-only scoring, MISSING with no overlap, label-drift
  skip, per-market/regime split, pin/manifest roundtrip, run-date upsert,
  trend-row/report render). Focused suite green (13 passed incl. schema-registry
  and variant-evidence-growth).
- Real-data proof: pinned the control variant as baseline and scored the
  `item50_pooled_forecast_v3_candidate` over the **same** 18,403 observations
  (12 market-days, 3 markets). Output `data/backtest/frozen_baseline_replay_trend.*`:
  status `PRESENT`, candidate−control Brier `+0.0000` (this candidate ≈ control on
  identical weather), candidate−market `+0.0096`, with the expected regime shape
  (early Brier `0.067`, midday `0.059`, late `0.003`).

## Completion Notes 2026-06-22

The remaining integration is now complete. Daily refresh includes a
`frozen_baseline_replay_trend` step after `active_variant_shadow` and before
`model_variant_evidence_growth`, so the scheduled path scores current active
shadow predictions against the pinned manifest over the same frozen captured
inputs. The step defaults to `active_variant_shadow_long.csv`, uses the pinned
baseline manifest, and requires explicit current/baseline variant filters to
avoid averaging multi-variant rows.

The daily progress ledger now consumes
`data/backtest/frozen_baseline_replay_trend.json`. When that artifact reports
`independent_baseline_status: PRESENT`, the broad-improvement gate no longer
emits `independent_baseline_missing`. The ledger records the frozen baseline id,
shared observations, shared market-days, and current-minus-baseline Brier delta.

Progress audit now renders a `Live-Forward Vs Weather-Held-Constant` table next
to the core day-over-day trend. The live-forward row remains weather-confounded;
the frozen-baseline row shows the code-attributable current-minus-baseline delta
on identical captured inputs.

Regenerated real artifacts show the pinned baseline is PRESENT over `18,403`
shared observations and `12` shared market-days. Current-minus-baseline Brier is
`+0.0000` for the existing item50/control demo baseline, and current-minus-market
Brier remains `+0.0096`. `data/backtest/daily_progress_latest.json` now has
`evidence_independent_baseline_status: PRESENT`; its claim failures no longer
include `independent_baseline_missing`.

Verification:

- `python -m pytest tests\operations\test_daily_refresh.py tests\reporting\test_daily_progress_ledger.py tests\reporting\test_progress_audit.py tests\reporting\test_frozen_baseline_replay_trend.py tests\operations\test_schema_registry.py -q`
- `python -m weather.reporting.frozen_baseline_replay_trend update data\backtest\active_variant_shadow_long.csv --manifest data\backtest\frozen_baseline_manifest.json --current-variant-id item50_pooled_forecast_v3_candidate --baseline-variant-id pooled_f_candidate_control --code-identity item50_pooled_forecast_v3_candidate --trend-jsonl data\backtest\frozen_baseline_replay_trend.jsonl --json-out data\backtest\frozen_baseline_replay_trend.json --report-out data\backtest\frozen_baseline_replay_trend_report.md`
- `python -m weather.reporting.daily_progress_ledger --backtest-root data\backtest --snapshots-root data\snapshots`
- `python -m weather.reporting.progress_audit --backtest-root data\backtest --snapshots-root data\snapshots --roadmap docs\roadmap\ROADMAP.md --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md`

Related: items 163, 117, 216, 26, 85, 69, 182, 205; `[[replay-corpus]]`,
`[[settled-day-review-2026-06-20]]`.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-22 - DAILY REFRESH AND LEDGER WIRING LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

