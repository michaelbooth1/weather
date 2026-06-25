# 136. Forecast Source-State Reliability Calibrator [PARTIAL 2026-06-22 - DISPOSITION REFRESHED, SOURCE-STATE THRESHOLDS BLOCKED]

Goal: convert forecast source count, source disagreement, and freshness state
from broad diagnostics into a calibrated reliability layer that adjusts
forecast confidence when source quality changes.

Source: `data/backtest/input_variable_significance_2026_06_18_report.md`.
The forecast-source-state family was much smaller than the forecast-profile
family but still showed measurable value:

- all-day family HGB permutation delta MAE: `0.0239`, q `0.0170`;
- early-day family HGB permutation delta MAE: `0.0318`, q `0.0209`;
- `forecast_source_count` individual HGB delta MAE: `0.0186`;
- `forecast_disagreement` individual HGB delta MAE: `0.0056`.

Item 105 proved the source-state ablation gate. This item is the next step:
turn the measured source-state signal into a calibrated reliability adjustment
for the forecast family, especially before observations dominate.

Why this matters: forecast inputs are strongest early, but early-day forecasts
are also most exposed to missing sources, stale payloads, and inter-source
disagreement. Treating source-state as a standalone feature can understate its
role: it should often scale the confidence of forecast-profile evidence.

## Design

1. Build a forecast reliability calibrator that consumes source count, forecast
   disagreement, payload age, stale/failed source states, and source-family
   availability.
2. Apply the calibrator as a confidence adjustment to forecast-profile output,
   not only as independent model columns.
3. Score reliability-adjusted candidates on all-fresh, degraded-source,
   high-disagreement, and low-source-count slices.
4. Separate missingness signal from genuine meteorological disagreement so the
   model does not learn source outage artifacts as weather.
5. Feed reliability state into market-making quote width, not just fair value.

- [x] Add a reliability-calibrated forecast-profile candidate.
- [x] Add paired replay slices for all-fresh, degraded-source, low-count, and
  high-disagreement snapshots.
- [x] Add a calibration curve showing forecast error versus source-state risk.
- [x] Add per-market source reliability thresholds for forecast-family
  confidence shrinkage.
- [x] Surface the active source-state reliability reason in model explanations
  and quote-risk reports.
- [ ] Clear degraded-source and per-market reliability thresholds on pinned
  replay rows.

Acceptance: source-state reliability adjustment improves degraded-source and
high-disagreement slices without hurting all-fresh days, and promotion reports
show the reliability effect separately from raw forecast-profile skill.

## 2026-06-18 implementation update

Extended the shadow-variant export with optional source-state context columns:
`cutoff_regime`, `source_freshness_state`, `forecast_source_count_bucket`,
`forecast_disagreement_bucket`, and `forecast_bucket_pressure`. Regenerated
`data/backtest/item134_forecast_profile_shadow_variants.csv` from the pinned
forecast-profile replay so item 136 can score row-level source-state slices
without changing serving behavior.

Added `weather.reporting.research.forecast_source_state_reliability`, schema
`forecast_source_state_reliability_v0.1`. The report builds a non-serving
source-state reliability candidate by shrinking the forecast-profile
probability toward current serving probability as source-state risk rises.
Risk is keyed by source freshness, forecast source-count bucket, and forecast
disagreement bucket, and each row carries the active reliability reason.

Generated:

- `data/backtest/item136_reliability_calibrated_shadow_variants.csv`
- `data/backtest/item136_source_state_reliability.json`
- `data/backtest/item136_source_state_reliability_report.md`

The reliability candidate improves current replay daily-first
(`-0.0022` Brier delta versus current) and improves the high-disagreement slice
relative to raw forecast-profile skill (`-0.0002` delta versus raw forecast).
It does not clear acceptance: degraded-source rows are sparse (`22`) and worsen
raw forecast-profile skill by `+0.0022`, all-fresh rows are nearly flat but
slightly worse (`+0.0001`), and Houston blocks the per-market reliability
threshold with `+0.0012` delta versus raw forecast on risk rows.

Model explanations now surface a supplied `source_state_reliability` /
`forecast_source_state_reliability` payload. Quote-risk report wiring is still
open, so this item remains partial.

## 2026-06-22 source-state disposition

Updated `weather.reporting.research.forecast_source_state_reliability` so the default
input is the current all-hour Item 134 shadow export and the report includes a
dedicated quote-risk diagnostic section. The report now surfaces
`source_state_reliability_reason`, `source_state_reliability_alpha`, and
`source_state_risk_bucket` for quote-width/risk diagnostics while keeping the
lane no-market and shadow-only.

Regenerated:

```powershell
python -m weather.reporting.research.forecast_source_state_reliability --out data\backtest\item136_source_state_reliability.json --report data\backtest\item136_source_state_reliability_report.md --variant-out data\backtest\item136_reliability_calibrated_shadow_variants.csv
```

Added `weather.reporting.research.item136_source_state_disposition`, schema
`item136_source_state_disposition_v0.1`, and generated:

```powershell
python -m weather.reporting.research.item136_source_state_disposition --out data\backtest\item136_source_state_disposition.json --report data\backtest\item136_source_state_disposition_report.md
```

Result: **BLOCK**, disposition **KEEP_SHADOW_DIAGNOSTIC**.

Passing evidence:

- Source-state reliability replay covered 67,430 no-market rows.
- Reliability reason and alpha fields are surfaced for model explanations and
  quote-risk diagnostics.
- Daily-first reliability replay improves current (`-0.0013`).
- Lane separation is clean: this remains weather-only, no-market evidence.

Promotion blockers:

- Degraded-source rows do not improve raw forecast-profile skill
  (`+0.0003` delta versus raw forecast).
- High-disagreement rows do not improve raw forecast-profile skill
  (`+0.0001`).
- Per-market reliability thresholds block Chicago (`+0.0014`) and NYC
  (`+0.0011`) on risk rows.
- Upstream Item 134 and Item 135 dispositions remain shadow-only.
- The served-distribution and positive daily-first gates still block.

Next action: keep Item 136 as a shadow source-state reliability diagnostic. Do
not promote it or use it for quote-risk permission until degraded-source,
high-disagreement, Chicago/NYC, upstream Item 134/135, and served-distribution
gates clear.

## 2026-06-22 source-state disposition refresh

Regenerated the source-state reliability report and disposition after
refreshing upstream Item 134 and Item 135:

- `data/backtest/item136_source_state_reliability.json`
- `data/backtest/item136_source_state_reliability_report.md`
- `data/backtest/item136_reliability_calibrated_shadow_variants.csv`
- `data/backtest/item136_source_state_disposition.json`
- `data/backtest/item136_source_state_disposition_report.md`

The refreshed disposition remains `KEEP_SHADOW_DIAGNOSTIC`; promotion remains
disallowed with `5` blockers. Passing evidence remains:

- source-state reliability replay covered `67,430` no-market rows.
- reliability reason and alpha fields are surfaced for model explanations and
  quote-risk diagnostics.
- daily-first reliability replay improves current by `-0.0013`.
- lane separation is clean: source-state reliability remains no-market
  weather-model evidence.

Current blockers:

- `source_state_reliability_thresholds`: degraded-source slice worsens raw
  forecast-profile skill by `+0.0003`, high-disagreement slice worsens raw
  forecast-profile skill by `+0.0001`, and Chicago/NYC market reliability
  thresholds block at `+0.0014` and `+0.0011`.
- `upstream_forecast_profile_disposition`: Item 134 remains shadow-only because
  daily-first blocked validation is not within market tolerance.
- `upstream_cutoff_regime_disposition`: Item 135 remains shadow-only because
  early, midday, and late regime thresholds are blocked.
- `served_distribution_contract`: served-distribution evidence remains
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- `positive_daily_first_gate`: the active repaired path still blocks on early-
  hour Brier gap `+0.0048 > +0.0030`.

This keeps Item 136 as a shadow source-state reliability diagnostic. Do not
promote it or use it for quote-risk permission until degraded-source,
high-disagreement, Chicago/NYC, upstream Item 134/135, and served-distribution
gates clear.
