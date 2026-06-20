# Large Module Ownership Map

Last updated: 2026-06-20

Use this map before moving code out of the current large facades. Keep public
module names and CLIs stable until focused tests and import-architecture guards
cover the extracted owner.

| Module | Owner | Current boundary | Next split |
| :--- | :--- | :--- | :--- |
| `weather.calibration.pooled_feature_model` | Calibration | Pooled training and CLI facade. Dynamic source-state feature helpers now live in `weather.calibration.pooled_feature_source_state`. | Feature assembly, training loops, validation/postprocess, artifact IO, report rendering, and CLI orchestration. |
| `weather.market.taker_bot` | Market | Taker strategy orchestration facade. | Strategy registry, strategy evaluation, sizing/risk, bakeoff/reporting, tape IO, and CLI. |
| `weather.reporting.promotion_refresh` | Reporting | Promotion refresh orchestration facade. | Gate readers, mitigation evaluation, report rendering, and artifact publication. |
| `weather.reporting.fleet_observability` | Reporting | Fleet status report orchestration and rendering. | Slot scoring, gate rendering, loop integrity, and shared report utilities. |
| `weather.reporting.hourly_model_performance` | Reporting | Hourly model performance report facade. | Slot scoring, gate policy, rendering, and CLI. |
| `weather.operations.daily_refresh` | Operations | Daily refresh orchestration facade. | Step runner registry, status/report rendering, preflight gates, and CLI. |

Run the current audit with:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
```

The warning threshold is 2,000 lines. Warnings do not block existing facades,
but any new module crossing that threshold must either be split before merge or
added to this map with an owner and concrete next split.
