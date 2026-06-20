# 137. Official Guidance Sparse-Coverage Evidence Growth [PARTIAL 2026-06-18 - COVERAGE GATE LIVE, ROW GROWTH BLOCKED]

Goal: grow enough settled coverage for official and multi-model guidance
features to decide whether they should influence the model or remain
diagnostics.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md`.
The report found promising but sparse official-guidance signals:

- early `nws_grid_high`: latest-snapshot `r=0.4854` over 21 market-days;
- early `open_meteo_nam_high_delta`: `r=-0.4940` over 21 market-days;
- midday `nws_grid_qpf_after_cutoff_sum`: `r=-0.7114`, but only 11 days;
- ECCC GEM fields had only about 2 non-missing days in the analyzed corpus.

Why this matters: these fields may add meaningful independent forecast
information, but their current sample sizes are too small for production
promotion. Promoting them now risks learning source-availability artifacts;
ignoring them forever risks leaving real official-guidance signal unused.

## Design

1. Add a coverage-growth report for NWS grid, Open-Meteo multi-model deltas,
   ECCC GEM/HRDPS, MRMS precipitation, and other official-guidance fields.
2. Backfill or continue collecting raw payloads until each candidate family has
   enough market-days, markets, cutoff regimes, and non-missing variation.
3. Use family-level replay gates instead of individual p-values while coverage
   is sparse.
4. Keep official guidance fields diagnostic-only until they clear coverage and
   replay thresholds.
5. Prioritize fields with plausible early-day value: `nws_grid_high`,
   multi-model high deltas, official QPF/pop/cloud diagnostics, and Toronto
   ECCC GEM high.

- [x] Add per-feature and per-family official-guidance coverage targets.
- [x] Add a daily report that names official-guidance fields blocked by sparse
  market-days or insufficient within-market variation.
- [ ] Backfill or collect enough rows for NWS and multi-model guidance across
  at least the active F-family markets.
- [ ] Backfill or collect enough Toronto-specific ECCC GEM/HRDPS rows for a
  Toronto-only replay decision.
- [x] Add a promotion gate that blocks official-guidance model influence until
  coverage and replay thresholds both pass.

Acceptance: official-guidance candidates have explicit coverage thresholds and
promotion decisions. A field cannot influence a served artifact until it has
sufficient settled market-day evidence and a positive family-level replay
result; otherwise it remains diagnostic-only with a named blocker.

## 2026-06-18 implementation update

Added `weather.reporting.official_guidance_sparse_coverage`, schema
`official_guidance_sparse_coverage_v0.1`. The report reads the June 18 input
significance coverage/summary artifacts plus
`data/backtest/source_family_inventory.json`, then emits per-feature coverage
targets, family promotion gates, and named diagnostic-only blockers.

Generated:

- `data/backtest/item137_official_guidance_sparse_coverage.json`
- `data/backtest/item137_official_guidance_sparse_coverage_report.md`

The generated promotion gate is `BLOCK` /
`official_guidance_model_influence_blocked`: `nws_grid`,
`multi_model_guidance`, `eccc_gridded`, and `mrms_precip` all remain
diagnostic-only. Current blockers are explicit:

- NWS grid and Open-Meteo multi-model priority fields top out at 32
  non-missing market-days across 11 markets, below the 60-day / 0.35 coverage
  targets, and their family replay evidence has only 1 day with no positive
  lift.
- Toronto ECCC GEM/HRDPS fields have only 2 non-missing market-days and 1
  market in the input-significance corpus, below the Toronto-only 30-day
  target.
- MRMS priority precipitation fields have zero non-missing market-days for the
  core interruption/precipitation-rate fields, while the broader family replay
  evidence has only 1 day and no positive lift.

Lineage also remains `PARTIAL_SOURCE_STATUS` for all four families in the
source-family inventory. The report therefore enforces the item 137 policy:
official-guidance fields cannot influence a served artifact until coverage,
lineage, and positive family-level replay all pass. Actual row growth/backfill
remains open.
