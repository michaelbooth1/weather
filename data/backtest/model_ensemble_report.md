# Model Ensemble And Ablation Report

Rows scored: 704
Target days: 1
Sample cap: none

## Inputs

| Event | Included | Quality | Rows | Settlement | Source | Component keys |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| highest-temperature-in-toronto-on-may-27-2026 | False | partial | 0 | - | - | 0 |
| highest-temperature-in-toronto-on-may-28-2026 | True | complete | 704 | 20 | snapshot_high | 0 |
| highest-temperature-in-toronto-on-may-30-2026 | False | partial | 0 | - | - | 0 |

## Standalone Forecasters

| Forecaster | Rows | Brier | LogLoss | Base rate |
| :--- | :--- | :--- | :--- | :--- |
| market_price | 704 | 0.0394 | 0.1230 | 0.0909 |
| deployed_model | 704 | 0.0583 | 0.1850 | 0.0909 |

## Leave-One-Day Ensemble

No-market candidates exclude Polymarket prices. Market-informed candidates include them and are scored separately so edge claims remain interpretable.

| Ensemble | Rows | Brier | LogLoss | Base rate |
| :--- | :--- | :--- | :--- | :--- |
| No-market tuned pair | - | - | - | - |
| Market-informed tuned pair | - | - | - | - |

> Insufficient clean target days for leave-one-day ensemble validation.

## Standalone By Cutoff

| Forecaster | Cutoff | Rows | Brier | LogLoss | Base rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| deployed_model | 8 | 11 | 0.0813 | 0.2650 | 0.0909 |
| deployed_model | 9 | 66 | 0.1023 | 0.3641 | 0.0909 |
| deployed_model | 10 | 66 | 0.0982 | 0.3450 | 0.0909 |
| deployed_model | 11 | 55 | 0.0914 | 0.2812 | 0.0909 |
| deployed_model | 12 | 66 | 0.0771 | 0.2154 | 0.0909 |
| deployed_model | 13 | 66 | 0.0354 | 0.1196 | 0.0909 |
| deployed_model | 14 | 66 | 0.0360 | 0.1264 | 0.0909 |
| deployed_model | 15 | 66 | 0.0549 | 0.1570 | 0.0909 |
| deployed_model | 16 | 66 | 0.0877 | 0.2221 | 0.0909 |
| deployed_model | 17 | 55 | 0.0400 | 0.1119 | 0.0909 |
| deployed_model | 18 | 66 | 0.0037 | 0.0287 | 0.0909 |
| deployed_model | 19 | 55 | 0.0036 | 0.0282 | 0.0909 |
| market_price | 8 | 11 | 0.0554 | 0.1698 | 0.0909 |
| market_price | 9 | 66 | 0.0615 | 0.1837 | 0.0909 |
| market_price | 10 | 66 | 0.0637 | 0.1896 | 0.0909 |
| market_price | 11 | 55 | 0.0676 | 0.1983 | 0.0909 |
| market_price | 12 | 66 | 0.0691 | 0.2014 | 0.0909 |
| market_price | 13 | 66 | 0.0439 | 0.1352 | 0.0909 |
| market_price | 14 | 66 | 0.0290 | 0.1041 | 0.0909 |
| market_price | 15 | 66 | 0.0363 | 0.1193 | 0.0909 |
| market_price | 16 | 66 | 0.0433 | 0.1294 | 0.0909 |
| market_price | 17 | 55 | 0.0071 | 0.0392 | 0.0909 |
| market_price | 18 | 66 | 0.0022 | 0.0202 | 0.0909 |
| market_price | 19 | 55 | 0.0001 | 0.0038 | 0.0909 |

## Standalone By Market-Bin Type

| Forecaster | Bin type | Rows | Brier | LogLoss | Base rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| deployed_model | eq | 576 | 0.0711 | 0.2244 | 0.1111 |
| deployed_model | gte | 64 | 0.0006 | 0.0155 | 0.0000 |
| deployed_model | lte | 64 | 0.0000 | 0.0000 | 0.0000 |
| market_price | eq | 576 | 0.0482 | 0.1498 | 0.1111 |
| market_price | gte | 64 | 0.0000 | 0.0044 | 0.0000 |
| market_price | lte | 64 | 0.0000 | 0.0005 | 0.0000 |

Promotion guardrail: do not promote an ensemble unless it improves the no-market score on clean leave-one-day validation and the market-informed score is reported separately.
