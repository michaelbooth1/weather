# Toronto Weather Market Roadmap

This roadmap is organized around the fastest path from a useful live dashboard
to a calibrated, auditable trading/research system for Toronto high-temperature
markets.

This file is the roadmap index. Detailed narrative, audit history, and each numbered roadmap item live in smaller files under this directory so updates stay localized and reviewable.

## Roadmap Files

- [Overview and current triage](overview.md)
- [Platform era reconciliation](platform-era-reconciliation.md)
- [Sequencing the two tracks](sequencing.md)
- [Research questions](research-questions.md)
- [2026-05-28 Codex audit summary](audits/codex-audit-summary-2026-05-28.md)
- [2026-05-28 deep model audit](audits/codex-deep-model-audit-2026-05-28.md)

## Numbered Items

### Near-Term Priorities

| Item | File |
| ---: | --- |
| 1 | [Snapshot Analytics [CLOSED]](items/item-01-snapshot-analytics.md) |
| 2 | [Intraday Model Calibration [CLOSED]](items/item-02-intraday-model-calibration.md) |
| 3 | [Forecast Archive [CLOSED]](items/item-03-forecast-archive.md) |
| 4 | [ECCC SWOB Historical Layer [CLOSED]](items/item-04-eccc-swob-historical-layer.md) |
| 5 | [METAR Historical Layer [COMPLETE - LEARNED METAR SERVING ROLE]](items/item-05-metar-historical-layer.md) |

### Model Improvements

| Item | File |
| ---: | --- |
| 6 | [Feature-Based Probability Model [COMPLETE - TEMPERATURE CALIBRATION LAYER]](items/item-06-feature-based-probability-model.md) |
| 7 | [Bucket Boundary Logic [COMPLETE - TRANSITION PRIOR LIVE]](items/item-07-bucket-boundary-logic.md) |
| 8 | [Late-Day Tail Model [COMPLETE - CONTINUATION BLEND LIVE]](items/item-08-late-day-tail-model.md) |
| 9 | [Analog Search [COMPLETE]](items/item-09-analog-search.md) |

### Dashboard Improvements

| Item | File |
| ---: | --- |
| 10 | [Odds Timeline View [COMPLETE]](items/item-10-odds-timeline-view.md) |
| 11 | [Source Freshness Panel [COMPLETE - TTL POLICY TRACKED IN ITEM 17]](items/item-11-source-freshness-panel.md) |
| 12 | [Model Explanation Panel [COMPLETE]](items/item-12-model-explanation-panel.md) |
| 13 | [Snapshot Controls [COMPLETE]](items/item-13-snapshot-controls.md) |

### Data Quality And Operations

| Item | File |
| ---: | --- |
| 14 | [Data Validation Suite [COMPLETE - FLEET-AWARE]](items/item-14-data-validation-suite.md) |
| 15 | [Reproducible Backfills [COMPLETE]](items/item-15-reproducible-backfills.md) |
| 16 | [Background Process Management [COMPLETE]](items/item-16-background-process-management.md) |
| 17 | [Error Handling And Caching [COMPLETE]](items/item-17-error-handling-and-caching.md) |

### Market Expansion

| Item | File |
| ---: | --- |
| 18 | [Multi-Day Market Support [COMPLETE - CONFIG REGISTRY OVERLAY]](items/item-18-multi-day-market-support.md) |
| 19 | [Other Weather Markets [COMPLETE - EXPLICIT MARKET MAPPINGS]](items/item-19-other-weather-markets.md) |

### [Long-Run Accuracy Roadmap](long-run-accuracy-roadmap.md)

| Item | File |
| ---: | --- |
| 20 | [Settlement-Scored Evaluation V2 [COMPLETE]](items/item-20-settlement-scored-evaluation-v2.md) |
| 21 | [Market-Bin Probability Calibration [COMPLETE - HIGHEST PRIORITY]](items/item-21-market-bin-probability-calibration.md) |
| 22 | [Forecast-Error And Source-Bias Model [COMPLETE]](items/item-22-forecast-error-and-source-bias-model.md) |
| 23 | [WU Settlement Lag And Revision Model [COMPLETE]](items/item-23-wu-settlement-lag-and-revision-model.md) |
| 24 | [Unified Feature Store And Train/Serve Parity [COMPLETE]](items/item-24-unified-feature-store-and-train-serve-parity.md) |
| 25 | [Market-Day Data Collection And Label Quality [COMPLETE]](items/item-25-market-day-data-collection-and-label-quality.md) |
| 26 | [Model Ensemble And Ablation Framework [COMPLETE - AWAITING MORE CLEAN DAYS]](items/item-26-model-ensemble-and-ablation-framework.md) |
| 27 | [Weather Regime And Microclimate Features [PARTIAL 2026-06-15 - WIND SHIFT/GUST FEATURES PLUMBED]](items/item-27-weather-regime-and-microclimate-features.md) |

### [Track A — From Basic To Best-Possible Data Layer](tracks/track-a-data-layer.md)

| Item | File |
| ---: | --- |
| 28 | [Settlement Ground-Truth Ledger [COMPLETE - LEDGER LIVE]](items/item-28-settlement-ground-truth-ledger.md) |
| 29 | [Deepen And Widen The Historical Record [PARTIAL - WU SEASONAL STRONG, REDUNDANT SOURCES SHALLOW]](items/item-29-deepen-and-widen-the-historical-record.md) |
| 30 | [Source Redundancy And Gap-Filling [COMPLETE - REDUNDANCY REPORT LIVE]](items/item-30-source-redundancy-and-gap-filling.md) |
| 31 | [Data Integrity And Observability At Scale [COMPLETE - FLEET REPORT LIVE]](items/item-31-data-integrity-and-observability-at-scale.md) |
| 32 | [Reanalysis And Synoptic Feature Layer [NEW - GATED]](items/item-32-reanalysis-and-synoptic-feature-layer.md) |
| 39 | [Data Layer Audit Findings (2026-06-09) [PARTIAL 2026-06-15 - SOURCE/TRUTH/STORAGE/GATE/SCHEMA/DASHBOARD CLEANUP DONE]](items/item-39-data-layer-audit-findings-2026-06-09.md) |
| 61 | [Supplemental Nearby Station Registry And Provenance [COMPLETE 2026-06-15 - REGISTRY AND PROVENANCE LIVE]](items/item-61-supplemental-nearby-station-registry-and-provenance.md) |
| 62 | [Nearby Station Validation And Promotion Gates [COMPLETE 2026-06-15 - VALIDATION GATE LIVE]](items/item-62-nearby-station-validation-and-promotion-gates.md) |
| 64 | [Canonical Settlement History Provenance Guardrails [COMPLETE 2026-06-15 - CANONICAL GUARDRAILS LIVE]](items/item-64-canonical-settlement-history-provenance-guardrails.md) |

### [Track B — From Bootstrap To Full Production Model](tracks/track-b-production-model.md)

| Item | File |
| ---: | --- |
| 33 | [Family-Pooled Model + City Features [COMPLETE 2026-06-15 - PIPELINE LIVE, READINESS SPLIT TO ITEM 48]](items/item-33-family-pooled-model-and-city-features.md) |
| 34 | [Per-Market Calibration And F-Family Secondary Artifacts [COMPLETE - EMPIRICAL GATED]](items/item-34-per-market-calibration-and-f-family-secondary-artifacts.md) |
| 35 | [Unified Continuous-Density Model [NEW - ENDGAME]](items/item-35-unified-continuous-density-model.md) |
| 36 | [Production Validation, Gating, And Promotion [COMPLETE]](items/item-36-production-validation-gating-and-promotion.md) |
| 37 | [MLOps And Always-On Production Hardening [PARTIAL 2026-06-15 - LIVE-FORWARD SLO + ARTIFACT REGISTRY READY]](items/item-37-mlops-and-always-on-production-hardening.md) |
| 38 | [Cross-Market And Market-Microstructure Signal [PARTIAL 2026-06-14 - TAXONOMY-GATED CLOB OVERLAY]](items/item-38-cross-market-and-market-microstructure-signal.md) |
| 40 | [Intra-Hour Feature Freshness [COMPLETE 2026-06-11 - FLEET REFRESHED]](items/item-40-intra-hour-feature-freshness.md) |
| 41 | [Model-Market Disagreement Casebook [COMPLETE 2026-06-14 - CASEBOOK LIVE]](items/item-41-model-market-disagreement-casebook.md) |
| 42 | [Fast Observation-Triggered Recompute Path [PARTIAL 2026-06-14 - WATCHER SHIPPED]](items/item-42-fast-observation-triggered-recompute-path.md) |
| 43 | [Market-Making Policy And Quote Intent Tape [COMPLETE 2026-06-14 - SHADOW POLICY LIVE]](items/item-43-market-making-policy-and-quote-intent-tape.md) |
| 44 | [Paper Trading, Queue Simulation, Markouts, And Incentive Accounting [COMPLETE 2026-06-15 - PAPER SCORER LIVE]](items/item-44-paper-trading-queue-simulation-markouts-and-incentive-accounting.md) |
| 45 | [Market-Making Position Sizing, Risk Controls, And Live Gate [PARTIAL 2026-06-15 - RISK + NEG-RISK + AUDIT GATE + RUNBOOK LIVE]](items/item-45-market-making-position-sizing-risk-controls-and-live-gate.md) |
| 46 | [Date/Budget Market-Making Run Orchestrator [COMPLETE 2026-06-15 - OPERATOR WORKFLOW LIVE]](items/item-46-date-budget-market-making-run-orchestrator.md) |
| 47 | [Model Readiness And Known-Edge Permission Map [COMPLETE 2026-06-15 - POLICY-CONSUMED MAP]](items/item-47-model-readiness-and-known-edge-permission-map.md) |
| 48 | [F-Family Promotion Readiness And Serving Parity [OPEN - GAP DRIVERS + PERMISSION CELLS LIVE]](items/item-48-f-family-promotion-readiness-and-serving-parity.md) |
| 49 | [Late-Day Forecast-Gap Continuation Training [COMPLETE 2026-06-15 - FORECAST-GAP ARTIFACTS LIVE]](items/item-49-late-day-forecast-gap-continuation-training.md) |
| 50 | [Scholarly Weather-Input Gap Closure [NEW - OPEN]](items/item-50-scholarly-weather-input-gap-closure.md) |
| 51 | [Model Architecture Health Refactor [PARTIAL 2026-06-15 - ANALOG FEATURE VIEW]](items/item-51-model-architecture-health-refactor.md) |
| 52 | [Miami Current-Serving Replay Regression Triage [COMPLETE 2026-06-15 - MIAMI SERVING BLOCK CLEARED]](items/item-52-miami-current-serving-replay-regression-triage.md) |
| 53 | [Candidate Source-Freshness Gap Attribution [COMPLETE 2026-06-15 - REPORT ATTRIBUTION LIVE]](items/item-53-candidate-source-freshness-gap-attribution.md) |
| 54 | [Source-Freshness Known-Edge Map Consumption [COMPLETE 2026-06-15 - PERMISSION CELLS LIVE]](items/item-54-source-freshness-known-edge-map-consumption.md) |
| 55 | [Market-Making Order Lifecycle And Budget Reconciliation [COMPLETE 2026-06-15 - LIFECYCLE LEDGER LIVE]](items/item-55-market-making-order-lifecycle-and-budget-reconciliation.md) |
| 56 | [Market-Making Test Cockpit And Drilldown Diagnostics [COMPLETE 2026-06-15 - COCKPIT LIVE]](items/item-56-market-making-test-cockpit-and-drilldown-diagnostics.md) |
| 57 | [Market-Making Preflight Remediation And Active-Day Reliability [COMPLETE 2026-06-15 - REMEDIATION INCIDENTS LIVE]](items/item-57-market-making-preflight-remediation-and-active-day-reliability.md) |
| 58 | [Miami Intra-Hour WU Print-Lag Feature Parity [COMPLETE 2026-06-15 - PRINT-LAG PARITY FIXED]](items/item-58-miami-intra-hour-wu-print-lag-feature-parity.md) |
| 59 | [Afternoon High-Has-Stood Lock-In Model [COMPLETE 2026-06-15 - HIGH-HAS-STOOD LOCK-IN LIVE]](items/item-59-afternoon-high-has-stood-lock-in-model.md) |
| 60 | [Snapshot Range-Band Audit Schema And Serving Version Guard [COMPLETE 2026-06-15 - RANGE SCHEMA AND STALE-CODE GUARD LIVE]](items/item-60-snapshot-range-band-audit-schema-and-serving-version-guard.md) |
| 63 | [Nearby Station Source-Trust And Redundant-History Features [COMPLETE 2026-06-15 - HISTORICAL-ONLY FEATURES LIVE]](items/item-63-nearby-station-source-trust-and-redundant-history-features.md) |

## Maintenance Conventions

- Update the owning item file rather than this index when changing item scope, status, acceptance criteria, or implementation notes.
- Keep numbered item headings in the format `# N. Title [STATUS]` so audit tooling and human readers can find them quickly.
- Add broad narrative updates to `overview.md`, track framing to `tracks/`, and historical findings to `audits/`.
- When adding or moving numbered items, update the table above in the same change.
