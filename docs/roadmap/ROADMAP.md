# Weather Market Platform Roadmap

This roadmap is organized around the fastest path from a useful live dashboard
to a calibrated, auditable multi-market trading and research system for daily
high-temperature markets.

For current work, start with the generated
[active backlog](active-backlog.md). Each numbered item file is authoritative
for that item's status, scope, acceptance criteria, and evidence. This file is
the complete taxonomy and item index; dated narratives and audits are
historical context rather than current instructions.

## Roadmap Files

- [Generated active backlog (canonical current-work view)](active-backlog.md)
- [Overview and triage history (historical)](overview.md)
- [Actionable work order from 2026-06-23 (historical)](actionable-work-order.md)
- [Platform era reconciliation](platform-era-reconciliation.md)
- [Sequencing notes (historical)](sequencing.md)
- [Research questions](research-questions.md)
- [Open and blocked audit - 2026-06-18](open-blocker-audit-2026-06-18.md)
- [2026-05-28 Codex audit summary](audits/codex-audit-summary-2026-05-28.md)
- [2026-05-28 deep model audit](audits/codex-deep-model-audit-2026-05-28.md)
- [2026-06-20 taker bot log audit](audits/taker-bot-log-audit-2026-06-20.md)
- [2026-06-22 taker bot performance strategy audit](audits/taker-bot-performance-strategy-audit-2026-06-22.md)
- [2026-06-23 taker bot performance strategy audit](audits/taker-bot-performance-strategy-audit-2026-06-23.md)
- [2026-06-23 trading stack performance and strategy audit](audits/trading-stack-performance-strategy-audit-2026-06-23.md)
- [2026-06-24 system-level backlog audit](audits/system-level-backlog-audit-2026-06-24.md)
- [2026-06-24 Python and runtime log audit](audits/python-log-audit-2026-06-24.md)

## Status Taxonomy

Roadmap item states are `COMPLETE`, `PARTIAL`, and `OPEN`.
`COMPLETE` means the item has accepted implementation evidence or an explicit
final disposition, including superseded or intentionally discontinued work, and
has no remaining active roadmap work. `PARTIAL` means useful work exists but
acceptance is not fully met, and `OPEN` means primary implementation or
infrastructure work remains.

## Numbered Items

### Near-Term Priorities

| Item | File |
| ---: | --- |
| 1 | [Snapshot Analytics [COMPLETE]](items/item-01-snapshot-analytics.md) |
| 2 | [Intraday Model Calibration [COMPLETE]](items/item-02-intraday-model-calibration.md) |
| 3 | [Forecast Archive [COMPLETE]](items/item-03-forecast-archive.md) |
| 4 | [ECCC SWOB Historical Layer [COMPLETE]](items/item-04-eccc-swob-historical-layer.md) |
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
| 27 | [Weather Regime And Microclimate Features [COMPLETE 2026-06-15 - FEATURE-VALUE GATE LIVE]](items/item-27-weather-regime-and-microclimate-features.md) |

### [Track A — From Basic To Best-Possible Data Layer](tracks/track-a-data-layer.md)

| Item | File |
| ---: | --- |
| 28 | [Settlement Ground-Truth Ledger [COMPLETE - LEDGER LIVE]](items/item-28-settlement-ground-truth-ledger.md) |
| 29 | [Deepen And Widen The Historical Record [COMPLETE 2026-06-16 - SOURCE-LIMITED QUEUE COMPLETE]](items/item-29-deepen-and-widen-the-historical-record.md) |
| 30 | [Source Redundancy And Gap-Filling [COMPLETE - REDUNDANCY REPORT LIVE]](items/item-30-source-redundancy-and-gap-filling.md) |
| 31 | [Data Integrity And Observability At Scale [COMPLETE - FLEET REPORT LIVE]](items/item-31-data-integrity-and-observability-at-scale.md) |
| 32 | [Reanalysis And Synoptic Feature Layer [PARTIAL 2026-06-22 - SIDECAR AUDIT REFRESHED, PRESSURE SOURCE-LAG BLOCKED]](items/item-32-reanalysis-and-synoptic-feature-layer.md) |
| 39 | [Data Layer Audit Findings (2026-06-09) [COMPLETE 2026-06-16 - AUDIT FINDINGS RECONCILED]](items/item-39-data-layer-audit-findings-2026-06-09.md) |
| 61 | [Supplemental Nearby Station Registry And Provenance [COMPLETE 2026-06-15 - REGISTRY AND PROVENANCE LIVE]](items/item-61-supplemental-nearby-station-registry-and-provenance.md) |
| 62 | [Nearby Station Validation And Promotion Gates [COMPLETE 2026-06-15 - VALIDATION GATE LIVE]](items/item-62-nearby-station-validation-and-promotion-gates.md) |
| 64 | [Canonical Settlement History Provenance Guardrails [COMPLETE 2026-06-15 - CANONICAL GUARDRAILS LIVE]](items/item-64-canonical-settlement-history-provenance-guardrails.md) |
| 76 | [GRIB Subset Extraction Foundation [COMPLETE 2026-06-16 - GRIB CACHE POLICY LIVE]](items/item-76-grib-subset-extraction-foundation.md) |
| 77 | [One-Minute ASOS Spike And High-Timing Layer [COMPLETE 2026-06-16 - ASOS 1-MIN GATE LIVE]](items/item-77-one-minute-asos-spike-and-high-timing-layer.md) |
| 78 | [Coastal Marine And Lake-Breeze Context Features [COMPLETE 2026-06-16 - MARINE CONTEXT REPORTING LIVE]](items/item-78-coastal-marine-and-lake-breeze-context-features.md) |
| 79 | [MRMS Radar Precipitation Interruption Layer [COMPLETE 2026-06-16 - MRMS INTERRUPTION REPORTING LIVE]](items/item-79-mrms-radar-precipitation-interruption-layer.md) |
| 80 | [ECCC HRDPS And GEM Toronto Gridded Forecast Layer [COMPLETE 2026-06-16 - TORONTO ECCC GRIDDED SCORING LIVE]](items/item-80-eccc-hrdps-and-gem-toronto-gridded-forecast-layer.md) |
| 81 | [Meteostat And NASA POWER Historical Fallback Sources [COMPLETE 2026-06-16 - SUPPLEMENTAL FALLBACK GATES LIVE]](items/item-81-meteostat-and-nasa-power-historical-fallback-sources.md) |
| 85 | [Independent Market-Day Evidence Expansion For Variant Evaluation [COMPLETE 2026-06-16 - EVIDENCE GROWTH MONITOR LIVE]](items/item-85-independent-market-day-evidence-expansion-for-variant-evaluation.md) |
| 100 | [Open-Meteo Rate Limit And Source Fallback Resilience [COMPLETE 2026-06-18 - DEGRADED SOURCE PROVENANCE LIVE]](items/item-100-open-meteo-rate-limit-and-source-fallback-resilience.md) |
| 102 | [Toronto ECCC Runtime Source Hardening [COMPLETE 2026-06-18 - TORONTO SOURCE HEALTH GATE LIVE]](items/item-102-toronto-eccc-runtime-source-hardening.md) |
| 109 | [Settled-Day Replay Status Artifact Backfill [COMPLETE 2026-06-17 - REPAIR COMMAND LIVE]](items/item-109-settled-day-replay-status-artifact-backfill.md) |
| 113 | [Independent Settled Evidence Growth And Sample SLA [COMPLETE 2026-06-17 - EVIDENCE SLA LIVE]](items/item-113-independent-settled-evidence-growth-and-sample-sla.md) |
| 114 | [Data-Layer P0 Gate Closure For Retrain Eligibility [COMPLETE 2026-06-17 - DATA P0 CLEARED]](items/item-114-data-layer-p0-gate-closure-for-retrain-eligibility.md) |
| 120 | [Settled-Day Finalization Freshness SLA [COMPLETE 2026-06-18 - NIGHTLY PREFLIGHT LIVE]](items/item-120-settled-day-finalization-freshness-sla.md) |
| 124 | [CLOB Order-Book Retention Coverage And Storage Budget [COMPLETE 2026-06-18 - CLOB MANIFEST AUDIT LIVE]](items/item-124-clob-order-book-retention-coverage-and-storage-budget.md) |
| 154 | [Backtest Artifact Disk-Budget And Retention Guard [COMPLETE 2026-06-19 - GUARDED EXPORTS AND CLEANUP MANIFEST LIVE]](items/item-154-backtest-artifact-disk-budget-and-retention-guard.md) |
| 156 | [CLOB Midpoint Continuity For Market-Informed Repair [OPEN 2026-06-20 - LOCAL RAW RESTORE ABSENT, FUTURE TRAIN DAYS NEEDED]](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) |
| 157 | [Live-Forward Snapshot Cadence SLO Closure [PARTIAL 2026-07-12 - BOUNDED CAPTURE IMPLEMENTED, DEPLOYMENT/CLEAN DAY NEEDED]](items/item-157-live-forward-snapshot-cadence-slo-closure.md) |
| 158 | [Source-Status Degradation Recovery And Provider Cooldown Proof [COMPLETE 2026-06-20 - SOURCE STATUS PROOF AND ZERO BLOCKED MARKETS]](items/item-158-source-status-degradation-recovery-and-provider-cooldown-proof.md) |
| 159 | [Daily Refresh Disk-Headroom Preflight And Promotion Export Resume [COMPLETE 2026-06-20 - PREFLIGHT, RESUME, AND LEDGER RECOVERY PROVEN]](items/item-159-daily-refresh-disk-headroom-preflight-and-promotion-export-resume.md) |
| 185 | [Daily-High Predictor Data-Source Expansion [PARTIAL 2026-06-22 - SOURCE PREFLIGHT CLEARED, CHILD GATES OPEN]](items/item-185-daily-high-predictor-data-source-expansion.md) |
| 186 | [Soil-Moisture & Antecedent Land-Surface Dryness Predictor [COMPLETE 2026-06-23 - WATER BACKFILL AND POSITIVE-MARKET LANE PASS]](items/item-186-soil-moisture-antecedent-dryness-predictor.md) |
| 187 | [Forecast Shortwave-Radiation & Peak-Window Insolation Features [COMPLETE 2026-06-23 - POSITIVE-MARKET RADIATION LANE PASS]](items/item-187-forecast-shortwave-insolation-features.md) |
| 188 | [Aerosol & Wildfire-Smoke Suppression Features [PARTIAL 2026-06-24 - AQ ARCHIVE AND SMOKE SLICE PREP LIVE, RETRAIN BLOCKED]](items/item-188-aerosol-wildfire-smoke-features.md) |
| 189 | [ECMWF & ML-NWP Ensemble Forecast Members [PARTIAL 2026-06-24 - GLOBAL-MODEL ARCHIVE SUPPORT LIVE, REPLAY BLOCKED]](items/item-189-ecmwf-ml-nwp-ensemble-members.md) |
| 190 | [NBM Native Probabilistic Tmax Consumption [COMPLETE 2026-06-25 - SETTLEMENT SCORING LIVE; PROMOTION BLOCKED BY SKILL GATE]](items/item-190-nbm-probabilistic-tmax-consumption.md) |
| 191 | [Lake/Sea Surface-Temperature Contrast Feature [COMPLETE 2026-06-25 - SIDECAR-BACKED SETTLEMENT REPLAY LIVE; PROMOTION BLOCKED BY DAILY-FIRST GATE]](items/item-191-lake-sea-surface-temperature-contrast.md) |
| 193 | [WU Current-Max Anomaly Quarantine And Trust Weighting [COMPLETE 2026-06-21 - TRUSTED SUPPORT-ONLY QUARANTINE FIELDS LIVE]](items/item-193-wu-current-max-anomaly-quarantine-and-trust-weighting.md) |
| 197 | [Startup Live-Observation Null And Unit Guard [COMPLETE 2026-06-21 - IMPLAUSIBLE STARTUP OBSERVATIONS QUARANTINED]](items/item-197-startup-live-observation-null-unit-guard.md) |
| 201 | [Raw Observation Payload Sidecars [COMPLETE 2026-06-21 - OBSERVATION RAW PAYLOADS HAVE DURABLE SIDECARS]](items/item-201-raw-observation-payload-sidecars.md) |
| 203 | [Historical Snapshot Sidecar Coverage Closure [COMPLETE 2026-06-21 - SIDECAR ELIGIBILITY AND PROMOTION EXCLUSIONS LIVE]](items/item-203-historical-snapshot-sidecar-coverage-closure.md) |
| 208 | [Historical Feature-Quality Quarantine And Training Exclusion [COMPLETE 2026-06-21 - FEATURE-QUALITY QUARANTINE EXCLUDES LEGACY BAD ROWS]](items/item-208-historical-feature-quality-quarantine-and-training-exclusion.md) |
| 243 | [Closed Market-Day Parquet Archive Contract [COMPLETE 2026-06-22 - VERSIONED ARCHIVE CONTRACT REGISTERED]](items/item-243-closed-market-day-parquet-archive-contract.md) |
| 244 | [Historical Snapshot Parquet Backfill And Validation Harness [COMPLETE 2026-06-22 - GUARDED PARQUET BACKFILL LIVE]](items/item-244-historical-snapshot-parquet-backfill-validation.md) |
| 245 | [Parquet-First Historical Analysis Readers [COMPLETE 2026-06-23 - VALIDATED PARQUET READERS LIVE]](items/item-245-parquet-first-historical-analysis-readers.md) |
| 286 | [Three-Class Data Storage Contract And Retention Classification [COMPLETE 2026-06-23 - STORAGE CLASS REGISTRY AND REPORTING LIVE]](items/item-286-three-class-data-storage-contract.md) |
| 287 | [Per-Market-Day Event Manifest For Evidence, Projections, And Rebuild Sources [COMPLETE 2026-06-23 - EVENT-DAY MANIFEST WRITER AND VALIDATOR LIVE]](items/item-287-market-day-event-manifest.md) |
| 289 | [CLOB Price-History Deduplication And Content-Addressed Raw Response Store [COMPLETE 2026-06-23 - DEDUPED POINT TABLE AND HASHED RAW STORE LIVE]](items/item-289-clob-price-history-dedup-content-addressed-store.md) |
| 290 | [Incremental Closed-Day Parquet Conversion And Reader Migration Closure [COMPLETE 2026-06-23 - BOUNDED CURSOR CONVERTER AND READER STATUS LIVE]](items/item-290-incremental-closed-day-parquet-conversion.md) |
| 291 | [Schema Registry Reconciliation For Storage And Log Artifacts [COMPLETE 2026-06-24 - STRICT AUDIT CLEAN WITH EXPLICIT NON-SCHEMA EXCLUSIONS]](items/item-291-schema-registry-storage-log-artifact-reconciliation.md) |
| 299 | [Polymarket Event-Metadata Rollover Gate [COMPLETE 2026-06-24]](items/item-299-polymarket-event-metadata-rollover-gate.md) |

### [Track B — From Bootstrap To Full Production Model](tracks/track-b-production-model.md)

| Item | File |
| ---: | --- |
| 33 | [Family-Pooled Model + City Features [COMPLETE 2026-06-15 - PIPELINE LIVE, READINESS SPLIT TO ITEM 48]](items/item-33-family-pooled-model-and-city-features.md) |
| 34 | [Per-Market Calibration And F-Family Secondary Artifacts [COMPLETE - EMPIRICAL GATED]](items/item-34-per-market-calibration-and-f-family-secondary-artifacts.md) |
| 35 | [Unified Continuous-Density Model [PARTIAL 2026-06-22 - V0.7 DIAGNOSTICS REFRESHED, TARGET-DAY SIGNAL BLOCKED]](items/item-35-unified-continuous-density-model.md) |
| 36 | [Production Validation, Gating, And Promotion [COMPLETE]](items/item-36-production-validation-gating-and-promotion.md) |
| 37 | [MLOps And Always-On Production Hardening [COMPLETE 2026-06-15 - NIGHTLY RETRAIN + SHADOW AB MONITORING LIVE]](items/item-37-mlops-and-always-on-production-hardening.md) |
| 38 | [Cross-Market And Market-Microstructure Signal [COMPLETE 2026-06-16 - SETTLEMENT-SCORED CLOB EDGE PROVEN]](items/item-38-cross-market-and-market-microstructure-signal.md) |
| 40 | [Intra-Hour Feature Freshness [COMPLETE 2026-06-11 - FLEET REFRESHED]](items/item-40-intra-hour-feature-freshness.md) |
| 41 | [Model-Market Disagreement Casebook [COMPLETE 2026-06-14 - CASEBOOK LIVE]](items/item-41-model-market-disagreement-casebook.md) |
| 42 | [Fast Observation-Triggered Recompute Path [COMPLETE 2026-06-16 - PERMISSIONED REPLAY GATE LIVE]](items/item-42-fast-observation-triggered-recompute-path.md) |
| 43 | [Market-Making Policy And Quote Intent Tape [COMPLETE 2026-06-14 - SHADOW POLICY LIVE]](items/item-43-market-making-policy-and-quote-intent-tape.md) |
| 44 | [Paper Trading, Queue Simulation, Markouts, And Incentive Accounting [COMPLETE 2026-06-15 - PAPER SCORER LIVE]](items/item-44-paper-trading-queue-simulation-markouts-and-incentive-accounting.md) |
| 45 | [Market-Making Position Sizing, Risk Controls, And Live Gate [COMPLETE 2026-06-16 - PLATFORM VERIFICATION GATE LIVE]](items/item-45-market-making-position-sizing-risk-controls-and-live-gate.md) |
| 46 | [Date/Budget Market-Making Run Orchestrator [COMPLETE 2026-06-15 - OPERATOR WORKFLOW LIVE]](items/item-46-date-budget-market-making-run-orchestrator.md) |
| 47 | [Model Readiness And Known-Edge Permission Map [COMPLETE 2026-06-15 - POLICY-CONSUMED MAP]](items/item-47-model-readiness-and-known-edge-permission-map.md) |
| 48 | [F-Family Promotion Readiness And Serving Parity [COMPLETE 2026-06-25 - MARKET DISPOSITIONS PASSED, PRODUCTION CUTOVER FAIL-CLOSED]](items/item-48-f-family-promotion-readiness-and-serving-parity.md) |
| 49 | [Late-Day Forecast-Gap Continuation Training [COMPLETE 2026-06-15 - FORECAST-GAP ARTIFACTS LIVE]](items/item-49-late-day-forecast-gap-continuation-training.md) |
| 50 | [Scholarly Weather-Input Gap Closure [COMPLETE 2026-06-16 - CORE BACKFILL AND SHADOW EVIDENCE]](items/item-50-scholarly-weather-input-gap-closure.md) |
| 51 | [Model Architecture Health Refactor [COMPLETE 2026-06-15 - REPLAY BASELINED + NATIVE CLEANUP]](items/item-51-model-architecture-health-refactor.md) |
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
| 66 | [CLOB Book Recon And Reward-Competition Analytics [COMPLETE 2026-06-16 - BOOK RECON LIVE]](items/item-66-clob-book-recon-and-reward-competition-analytics.md) |
| 67 | [Authenticated Exchange Adapter And MM-2 Pilot Harness [PARTIAL 2026-06-24 - LIVE CREDENTIALS ABSENT; EVIDENCE BLOCKED]](items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md) |
| 68 | [Information-Event Calendar And Quote-Pull Gates [COMPLETE 2026-06-16 - EVENT GATE LIVE]](items/item-68-information-event-calendar-and-quote-pull-gates.md) |
| 69 | [Multi-Variant Shadow Harness And Experiment Governance [COMPLETE 2026-06-15 - LONG-FORM HARNESS LIVE]](items/item-69-multi-variant-shadow-harness-and-experiment-governance.md) |
| 70 | [Exact-Winner Catch-Up Candidate [COMPLETE 2026-06-16 - WHITELIST ALPHA GUARDRAIL PASSED]](items/item-70-exact-winner-catch-up-candidate.md) |
| 71 | [Dynamic Source-Freshness Model Variant [COMPLETE 2026-06-16 - SOURCE-STATE GATE PASSED]](items/item-71-dynamic-source-freshness-model-variant.md) |
| 72 | [Market-Aware CLOB Overlay Variant [COMPLETE 2026-06-16 - MARKET-INFORMED QUOTE GATES LIVE]](items/item-72-market-aware-clob-overlay-variant.md) |
| 73 | [Conservative Per-Market Candidate Bridge [COMPLETE 2026-06-16 - PAIRED SHADOW SCORING LIVE]](items/item-73-conservative-per-market-candidate-bridge.md) |
| 74 | [Open-Meteo Expanded Environmental Forecast Features [COMPLETE 2026-06-16 - PROMOTION GATE AND MISSING-ZERO REPORT LIVE]](items/item-74-open-meteo-expanded-environmental-forecast-features.md) |
| 75 | [US Official Forecast Grid And Multi-Model Guidance [COMPLETE 2026-06-16 - US GUIDANCE REPLAY DIAGNOSTICS LIVE]](items/item-75-us-official-forecast-grid-and-multimodel-guidance.md) |
| 82 | [Miami Candidate Block Regression Remediation [COMPLETE 2026-06-16 - CURRENT FALLBACK CLEARS BLOCK]](items/item-82-miami-candidate-block-regression-remediation.md) |
| 83 | [Shadow Evidence Accounting And Active Variant Registry [COMPLETE 2026-06-16 - ACTIVE EVIDENCE ACCOUNTING LIVE]](items/item-83-shadow-evidence-accounting-and-active-variant-registry.md) |
| 84 | [Cross-Family Control De-Duplication And Variant Namespace Hygiene [COMPLETE 2026-06-16 - SHARED CONTROL DEDUPE LIVE]](items/item-84-cross-family-control-deduplication-and-variant-namespace-hygiene.md) |
| 86 | [No-Market Candidate Bakeoff And Promotion Lane Selection [COMPLETE 2026-06-16 - ITEM50 SHADOW LANE SELECTED]](items/item-86-no-market-candidate-bakeoff-and-promotion-lane-selection.md) |
| 101 | [Live-Forward Gate State Reconciliation [COMPLETE 2026-06-18 - RECONCILED GATE ARTIFACT LIVE]](items/item-101-live-forward-gate-state-reconciliation.md) |
| 103 | [Late-Day Warm-Side Disagreement Casebook [COMPLETE 2026-06-18 - WARM-SIDE CASEBOOK SLICE LIVE]](items/item-103-late-day-warm-side-disagreement-casebook.md) |
| 104 | [Feature Matrix Assembly And Training Throughput Warning Gate [COMPLETE 2026-06-17 - THROUGHPUT GATE LIVE]](items/item-104-feature-matrix-assembly-and-training-throughput-warning-gate.md) |
| 105 | [Source-State Feature Ablation And Forecast Freshness Calibration [COMPLETE 2026-06-18 - SOURCE-STATE ABLATION GATE LIVE]](items/item-105-source-state-feature-ablation-and-forecast-freshness-calibration.md) |
| 106 | [Time-Blocked Active-Day Validation And Leakage Audit [COMPLETE 2026-06-17 - BLOCKED VALIDATION GATE LIVE]](items/item-106-time-blocked-active-day-validation-and-leakage-audit.md) |
| 108 | [Overnight Self-Improvement Run Evidence And Blocker SLA [COMPLETE 2026-06-17 - NIGHTLY SLA LIVE]](items/item-108-overnight-self-improvement-run-evidence-and-blocker-sla.md) |
| 110 | [Market-Making Roll Window And Evidence Classification [COMPLETE 2026-06-17 - EVIDENCE MODE GATE LIVE]](items/item-110-market-making-roll-window-and-evidence-classification.md) |
| 115 | [Market-Skill Gap Slice Remediation Program [COMPLETE 2026-06-17 - GAP OWNERS ASSIGNED]](items/item-115-market-skill-gap-slice-remediation-program.md) |
| 116 | [Per-Market Live-Forward Evidence Credit And Stale-Row Recovery [COMPLETE 2026-06-17 - PER-MARKET CREDIT LIVE]](items/item-116-per-market-live-forward-evidence-credit-and-stale-row-recovery.md) |
| 117 | [Core Model Day-Over-Day Skill Trend Gate [COMPLETE 2026-06-17 - TREND CLAIM GATE LIVE]](items/item-117-core-model-day-over-day-skill-trend-gate.md) |
| 118 | [Broad Live-Forward SLO Recovery [COMPLETE 2026-06-17 - RECOVERY CHECKLIST LIVE]](items/item-118-broad-live-forward-slo-recovery.md) |
| 121 | [Market-Making Tape Encoding And CSV Read Robustness [COMPLETE 2026-06-18 - ROBUST CSV READER LIVE]](items/item-121-market-making-tape-encoding-and-csv-read-robustness.md) |
| 123 | [Cross-Hub Readiness Transfer And Promotion Guardrails [COMPLETE 2026-06-18 - READINESS REPORT LIVE]](items/item-123-cross-hub-readiness-transfer-and-promotion-guardrails.md) |
| 125 | [Weather Input Value Attribution And Promotion Queue [COMPLETE 2026-06-18 - SOURCE-FAMILY PREFLIGHT LIVE]](items/item-125-weather-input-value-attribution-and-promotion-queue.md) |
| 134 | [Early-Day Forecast Profile Calibration [PARTIAL 2026-06-22 - DISPOSITION REFRESHED, SHADOW-ONLY FORECAST PROFILE]](items/item-134-early-day-forecast-profile-calibration.md) |
| 135 | [Cutoff-Regime Forecast/Observation Weighting [PARTIAL 2026-06-22 - DISPOSITION REFRESHED, SHADOW-ONLY REGIME WEIGHTS]](items/item-135-cutoff-regime-forecast-observation-weighting.md) |
| 136 | [Forecast Source-State Reliability Calibrator [PARTIAL 2026-06-22 - DISPOSITION REFRESHED, SOURCE-STATE THRESHOLDS BLOCKED]](items/item-136-forecast-source-state-reliability-calibrator.md) |
| 137 | [Official Guidance Sparse-Coverage Evidence Growth [COMPLETE 2026-06-24 - SOURCE ROW GROWTH BACKFILLED]](items/item-137-official-guidance-sparse-coverage-evidence-growth.md) |
| 138 | [Weak Input-Family Pruning And Regime Backfill [PARTIAL 2026-06-22 - GATE REFRESHED, ACTIVE ARTIFACT PRUNING BLOCKED]](items/item-138-weak-input-family-pruning-and-regime-backfill.md) |
| 139 | [Scheduled Active Variant Shadow Refresh [COMPLETE 2026-06-21 - INLINE REGISTRY EXECUTION LIVE]](items/item-139-scheduled-active-variant-shadow-refresh.md) |
| 140 | [Live First-Class Variant Prediction Tape [COMPLETE 2026-06-22 - LIVE VARIANT RUNTIME RUNNERS WIRED]](items/item-140-live-first-class-variant-prediction-tape.md) |
| 141 | [Variant Learning Operational Gates [COMPLETE 2026-06-18 - VARIANT LEARNING BLOCKING GATE LIVE]](items/item-141-variant-learning-operational-gates.md) |
| 142 | [Active Variant Registry Export Contract [COMPLETE 2026-06-18 - ACTIVE EXPORT CONTRACTS AUDITED]](items/item-142-active-variant-registry-export-contract.md) |
| 143 | [Variant Attribution Shadow Schema [COMPLETE 2026-06-18 - ATTRIBUTION SCHEMA AND SIDECAR LIVE]](items/item-143-variant-attribution-shadow-schema.md) |
| 144 | [Early-Hour Market-Aware Risk Guardrail [PARTIAL 2026-06-18 - GUARDRAIL LIVE, MARKOUT EVIDENCE BLOCKED]](items/item-144-early-hour-market-aware-risk-guardrail.md) |
| 145 | [Hourly Performance Gate And Remediation Registry [COMPLETE 2026-06-18 - HOURLY GATE AND REGISTRY LIVE]](items/item-145-hourly-performance-gate-and-remediation-registry.md) |
| 147 | [Early-Hour Winner-Centering Candidate [PARTIAL 2026-06-22 - DISPOSITION REFRESHED, SHADOW-ONLY BASELINE]](items/item-147-early-hour-winner-centering-candidate.md) |
| 148 | [No-Market Extra-Location Shadow Lane [COMPLETE 2026-06-18 - SHADOW LANE QUARANTINED]](items/item-148-no-market-extra-location-shadow-lane.md) |
| 149 | [Target-Vs-Extra Location Validation Harness [COMPLETE 2026-06-18 - PRICE-FREE TRANSFER HARNESS LIVE]](items/item-149-target-vs-extra-location-validation-harness.md) |
| 150 | [Extra-Location Compatibility Registry [COMPLETE 2026-06-18 - COMPATIBILITY GATE LIVE]](items/item-150-extra-location-compatibility-registry.md) |
| 151 | [Location-Similarity Partial Pooling [COMPLETE 2026-06-18 - WEIGHTED TRANSFER PATH LIVE]](items/item-151-location-similarity-partial-pooling.md) |
| 152 | [Active-Day Bot Preflight And Disk Liveness [COMPLETE 2026-06-18 - DISK AND DISCOVERY DENY-BY-DEFAULT GATES]](items/item-152-active-day-bot-preflight-and-disk-liveness.md) |
| 153 | [Live Observation Monotonicity And Settlement-Bin Normalization [COMPLETE 2026-06-18 - SETTLEMENT-NORMALIZED LIVE HIGH LEDGER]](items/item-153-live-observation-monotonicity-and-settlement-bin-normalization.md) |
| 155 | [Inactive-Market Price-Free Learning And Current-Max Carryover Guard [COMPLETE 2026-06-19 - 2026-06-18 AUDIT GAP]](items/item-155-inactive-market-price-free-learning-and-current-max-carryover-guard.md) |
| 160 | [Early-Hour Model Skill Remediation To Positive Daily-First Gate [PARTIAL 2026-07-12 - PRIOR CANDIDATE QUARANTINED, CLEAN FORWARD PROOF REQUIRED]](items/item-160-early-hour-model-skill-remediation-to-positive-daily-first-gate.md) |
| 162 | [Countable Trading Evidence And Taker Strategy Quality Gate [COMPLETE 2026-06-20 - GATES LIVE, CURRENT EVIDENCE NON-COUNTABLE]](items/item-162-countable-trading-evidence-and-taker-strategy-quality-gate.md) |
| 163 | [Daily Progress Ledger And Broad Improvement Claim Gate [COMPLETE 2026-06-20 - LEDGER AND CLAIM GATE LIVE, CLAIM BLOCKED]](items/item-163-daily-progress-ledger-and-broad-improvement-claim-gate.md) |
| 164 | [Settlement-Aware Taker P&L Finalization [COMPLETE]](items/item-164-settlement-aware-taker-pnl-finalization.md) |
| 165 | [Taker Strategy Experiment Harness And Arm Attribution [COMPLETE 2026-06-20 - MULTI-ARM ATTRIBUTION LIVE]](items/item-165-taker-strategy-experiment-harness-and-arm-attribution.md) |
| 166 | [Settlement-Scored Taker Strategy Bakeoff [COMPLETE 2026-06-20 - BAKEOFF AND LABEL-QUALITY BLOCKERS LIVE]](items/item-166-settlement-scored-taker-strategy-bakeoff.md) |
| 167 | [Calibration-Aware Taker Sizing And Tail-Risk Controls [COMPLETE 2026-06-20 - RISK-ADJUSTED SIZING LIVE]](items/item-167-calibration-aware-taker-sizing-and-tail-risk-controls.md) |
| 168 | [Ten-Minute Performance Gate And Weak-Slot Watchlist [COMPLETE]](items/item-168-ten-minute-performance-gate-and-weak-slot-watchlist.md) |
| 169 | [Predawn Winner-Centering And Forecast-Anchor Repair [COMPLETE 2026-06-20 - LOGISTIC WINNER-CENTERING PASS]](items/item-169-predawn-winner-centering-and-forecast-anchor-repair.md) |
| 170 | [Late-Day Lock-In Probability Saturation [COMPLETE 2026-06-20 - GROUP-GATED LOGISTIC LOCK-IN PASS]](items/item-170-late-day-lock-in-probability-saturation.md) |
| 178 | [Serving-Time Ordinal Smoothing Train/Serve Skew [PARTIAL 2026-06-22 - GATE REFRESHED, VALIDATION BLOCKED]](items/item-178-serving-ordinal-smoothing-train-serve-skew.md) |
| 179 | [Honest Blocked Validation For Feature-Model Tuning [COMPLETE 2026-06-22 - HONEST RE-EXPORT AND PROMOTION GATE LIVE]](items/item-179-honest-blocked-validation-for-feature-model-tuning.md) |
| 180 | [Unit-Safe Missing-Feature Handling [COMPLETE 2026-06-21 - MISSINGNESS ROUTES THROUGH IMPUTER]](items/item-180-unit-safe-missing-feature-handling.md) |
| 181 | [Forecast Signal Double-Counting And Dead Capture-Hour [COMPLETE 2026-06-22 - ML SCOPE REMOVED, EMPIRICAL FALLBACK GATED]](items/item-181-forecast-double-counting-and-dead-capture-hour.md) |
| 182 | [Distribution Stage-Attribution Harness [COMPLETE 2026-06-21 - SETTLED STAGE ATTRIBUTION LIVE]](items/item-182-distribution-stage-attribution-harness.md) |
| 183 | [Correlated Forecast-Source Clustering On Fallback Path [COMPLETE 2026-06-21 - FALLBACK CONSENSUS CLUSTER LIVE]](items/item-183-correlated-forecast-source-clustering-fallback-path.md) |
| 184 | [Per-Market Climatological Fallback Prior [COMPLETE 2026-06-21 - MARKET-SPECIFIC FALLBACK PRIOR LIVE]](items/item-184-per-market-climatological-fallback-prior.md) |
| 192 | [Taker Active-Policy Warm-Tail Kill Switch And Arm Cutover [COMPLETE 2026-06-21 - ACTIVE DEFAULT CUT TO LOW-PRICE TAIL-CAPPED ARM]](items/item-192-taker-active-policy-warm-tail-kill-switch-and-arm-cutover.md) |
| 194 | [High-Disagreement Forecast Warm-Outlier Dampening [COMPLETE 2026-06-21 - ROBUST FORECAST SIGNAL CAP LIVE]](items/item-194-high-disagreement-forecast-warm-outlier-dampening.md) |
| 195 | [Ramp-Window Ordinal Centering And Warm-Tail Spread Repair [COMPLETE 2026-06-21 - RAMP WARM-TAIL DAMPENER LIVE]](items/item-195-ramp-window-ordinal-centering-and-warm-tail-spread-repair.md) |
| 196 | [Late-Day Lock-In Coverage And Saturation Parity [COMPLETE 2026-06-21 - EXPANDED STOOD-HIGH LOCK-IN LIVE]](items/item-196-late-day-lock-in-coverage-and-saturation-parity.md) |
| 198 | [Settled-Day Root-Cause Attribution Report [COMPLETE 2026-06-21 - CANONICAL REPORT AND DAILY-REFRESH STEP LIVE]](items/item-198-settled-day-root-cause-attribution-report.md) |
| 199 | [Daily Learning Rollup Stale-Lock Recovery [COMPLETE 2026-06-21 - STALE LOCKS AND STALE ROLLUPS FAIL CLOSED]](items/item-199-daily-learning-rollup-stale-lock-recovery.md) |
| 200 | [First-Class Model Explanation Tape [COMPLETE 2026-06-21 - EXPLANATION SIDECARS QUERYABLE BY SNAPSHOT]](items/item-200-first-class-model-explanation-tape.md) |
| 202 | [Price-History And WebSocket Event Capture Loop [COMPLETE 2026-06-21]](items/item-202-price-history-and-websocket-event-capture-loop.md) |
| 207 | [Root-Cause Active Owner Recurrence Routing [COMPLETE 2026-06-21 - ACTIVE OWNER RECURRENCE ROUTING LIVE]](items/item-207-root-cause-active-owner-recurrence-routing.md) |
| 209 | [Taker Active Strategy Post-Cutover Canary [COMPLETE 2026-06-21 - CANARY LIFECYCLE GATES COMPLETE-LABEL PROMOTION]](items/item-209-taker-active-strategy-post-cutover-canary.md) |
| 210 | [Market-Maker Stale-Input Blackout Routing And Active-Day Evidence SLA [COMPLETE 2026-06-21 - CRITICAL SLA ROUTES LOST ACTIVE DAYS TO 161/157]](items/item-210-mm-stale-input-blackout-routing-and-evidence-sla.md) |
| 211 | [Active-Day Supervisor Repair And MM Preflight Rerun [COMPLETE 2026-06-22 - OPERATOR CLOSEOUT AND RECOVERY REPORTING ADDED]](items/item-211-active-day-supervisor-repair-and-mm-preflight-rerun.md) |
| 212 | [Snapshot Cadence As Model-Quality And Trading-Permission Input [COMPLETE 2026-06-22 - CADENCE QUALITY NOW HAIRCUTS CONFIDENCE AND PERMISSION]](items/item-212-snapshot-cadence-as-model-quality-and-trading-permission-input.md) |
| 213 | [Current-Date WU History Expected-Degradation Handling [COMPLETE 2026-06-22 - CURRENT-DAY WU 400S ARE TYPED EXPECTED DEGRADATION]](items/item-213-current-date-wu-history-expected-degradation.md) |
| 214 | [Settlement-Scored Taker Promotion And Tail-Fill Gate [COMPLETE 2026-06-22 - MTM-ONLY PNL IS PROVISIONAL AND TAIL FILLS ARE GATED]](items/item-214-settlement-scored-taker-promotion-and-tail-fill-gate.md) |
| 215 | [Current-High Trust Gate For Aggressive Trading [COMPLETE 2026-06-22 - UNTRUSTED CURRENT MAX BLOCKS AGGRESSIVE RISK]](items/item-215-current-high-trust-gate-for-aggressive-trading.md) |
| 216 | [Runtime-Identity Segmented Model Evidence [COMPLETE 2026-06-22 - SEGMENTED CLAIM GATES LIVE]](items/item-216-runtime-identity-segmented-model-evidence.md) |
| 217 | [Pinned Frozen-Baseline Replay Trend For Code-vs-Weather Skill Separation [COMPLETE 2026-06-22 - DAILY REFRESH AND LEDGER WIRING LIVE]](items/item-217-pinned-frozen-baseline-replay-trend.md) |
| 218 | [Location-Specific F-Family Promotion Allowlist [COMPLETE 2026-06-22 - PER-MARKET ALLOWLIST ENFORCED]](items/item-218-location-specific-f-family-promotion-allowlist.md) |
| 219 | [Bottom-Location Early/Midday Winner-Centering Repair [PARTIAL 2026-07-12 - V0.1 PROOF INVALIDATED, CLEAN REQUALIFICATION REQUIRED]](items/item-219-bottom-location-early-midday-winner-centering.md) |
| 220 | [CLOB Overlay Quote-Risk Lane Separation [COMPLETE 2026-06-22 - CLOB QUOTE-RISK LANE SEPARATED]](items/item-220-clob-overlay-quote-risk-lane-separation.md) |
| 221 | [Market Source/Missingness Location Gates [COMPLETE 2026-06-22 - MARKET SOURCE/MISSINGNESS GATE LIVE]](items/item-221-market-source-missingness-location-gates.md) |
| 222 | [Blocked-Market Variant Basket No-Go Guard [COMPLETE 2026-06-22 - FAILED BASKETS EMIT NO-GO DISPOSITIONS]](items/item-222-blocked-market-variant-basket-no-go-guard.md) |
| 223 | [Market-Stage Winner-Mass Attribution [COMPLETE 2026-06-22 - BOTTOM-LOCATION WINNER-MASS GUARDRAILS LIVE]](items/item-223-market-stage-winner-mass-attribution.md) |
| 224 | [Pooled F Retrain/Re-Export Location Gate [PARTIAL 2026-07-11 - REOPENED, ITEM224 V0.1 LABEL-LEAK QUARANTINE]](items/item-224-pooled-f-retrain-reexport-location-gate.md) |
| 225 | [Location Audit Evidence Freshness Repair [COMPLETE 2026-06-22 - FRESHNESS BLOCKER LIVE]](items/item-225-location-audit-evidence-freshness-repair.md) |
| 226 | [Per-Location Artifact Schema Quarantine [COMPLETE 2026-06-22 - STALE PER-LOCATION ARTIFACTS HISTORICAL-ONLY]](items/item-226-per-location-artifact-schema-quarantine.md) |
| 227 | [Early-Hour Promotion Blocker Enforcement [COMPLETE 2026-06-22 - CONSOLIDATED FAIL-CLOSED BLOCKER LIVE]](items/item-227-early-hour-promotion-blocker-enforcement.md) |
| 228 | [Predawn Weak-Slot Repair Candidate Gate [PARTIAL 2026-06-22 - PARAMETER SWEEP BLOCKS BROAD HOURLY]](items/item-228-predawn-weak-slot-repair-candidate-gate.md) |
| 229 | [Early-Hour Live-Forward Clean-Day Proof [OPEN 2026-06-25 - CLEAN ACTIVE DAY EVIDENCE REQUIRED]](items/item-229-early-hour-live-forward-clean-day-proof.md) |
| 230 | [Exact-Band And Settlement-Distance-0 Early-Hour Calibration [PARTIAL 2026-06-22 - GATE REFRESHED, DISTANCE-0 AND ONE-ABOVE BLOCKED]](items/item-230-exact-band-and-settlement-distance-zero-early-hour-calibration.md) |
| 231 | [Market-Specific Early-Hour Residual Repair Program [COMPLETE 2026-06-22 - MARKET MANIFESTS AND REJECTED-FAMILY REGISTRY LIVE]](items/item-231-market-specific-early-hour-residual-repair-program.md) |
| 232 | [Current-Max Trust Retrain And Warm-Tail Replay [COMPLETE 2026-06-23 - TRUST RETRAIN AND WARM-TAIL ABLATION PASS]](items/item-232-current-max-trust-retrain-and-warm-tail-replay.md) |
| 233 | [Validate-What-You-Serve Early-Hour Calibration Head [PARTIAL 2026-06-22 - CONTRACT REFRESHED, HEAD TRAINING BLOCKED]](items/item-233-validate-what-you-serve-early-hour-calibration-head.md) |
| 234 | [Settlement-Only Taker Quality Gate [COMPLETE 2026-06-22 - MTM-ONLY QUALITY FAILS CLOSED]](items/item-234-settlement-only-taker-quality-gate.md) |
| 235 | [Bad-Tail No-Go And Tail Calibration Repair [COMPLETE 2026-06-22 - BAD TAIL SLICES FAIL CLOSED]](items/item-235-bad-tail-no-go-and-tail-calibration-repair.md) |
| 236 | [Universal Current-High And Warm-Tail Risk Gates [COMPLETE 2026-06-22 - STRATEGY-FAMILY LOOPHOLES CLOSED]](items/item-236-universal-current-high-and-warm-tail-risk-gates.md) |
| 237 | [Active Taker Canary Demotion And Requalification [COMPLETE 2026-06-22 - CANARY PAPER-ONLY UNTIL REQUALIFIED]](items/item-237-active-taker-canary-demotion-and-requalification.md) |
| 238 | [Daily Taker Full-Bakeoff Champion/Challenger Loop [COMPLETE 2026-06-22]](items/item-238-daily-taker-full-bakeoff-champion-challenger-loop.md) |
| 239 | [Taker Settlement Finalization Liveness And Storage SLA [COMPLETE 2026-06-22]](items/item-239-taker-settlement-finalization-liveness-and-storage-sla.md) |
| 240 | [Taker Fee, Slippage, And Executable-Depth Profitability Model [COMPLETE 2026-06-22]](items/item-240-taker-fee-slippage-and-executable-depth-profitability-model.md) |
| 241 | [Market Benchmark No-Trade And Profitability Scoreboard [COMPLETE 2026-06-22]](items/item-241-market-benchmark-no-trade-and-profitability-scoreboard.md) |
| 242 | [Decisive Model Proof Packet And Gate Stack Ratchet [COMPLETE 2026-06-22 - WEATHER-ONLY PROOF PACKET AND RATCHET LIVE]](items/item-242-decisive-model-proof-packet-and-gate-stack-ratchet.md) |
| 248 | [Austin Robust Forecast-Cluster Signal [COMPLETE 2026-06-22 - ROBUST FORECAST CLUSTER HARD-SLICE GATE LIVE]](items/item-248-austin-robust-forecast-cluster-signal.md) |
| 249 | [Official METAR Rollover Lock-In Signal [COMPLETE 2026-06-22 - OFFICIAL ROLLOVER LOCK-IN LIVE]](items/item-249-official-metar-rollover-lockin-signal.md) |
| 250 | [Austin HGB Per-Location Requalification [COMPLETE 2026-06-22 - AUSTIN HGB FAIL-CLOSED REQUALIFICATION PACKET LIVE]](items/item-250-austin-hgb-per-location-requalification.md) |
| 251 | [Standing-High Partial Lock-In Dampener [COMPLETE 2026-06-22 - PARTIAL DAMPENER GATED]](items/item-251-standing-high-partial-lockin-dampener.md) |
| 252 | [Impossible Guidance Feature Quarantine [COMPLETE 2026-06-22 - FRESH-BUT-IMPOSSIBLE GUIDANCE QUARANTINED]](items/item-252-impossible-guidance-feature-quarantine.md) |
| 253 | [Two-Sided (NO-Side) Taker Edge And Book Capture [COMPLETE 2026-06-22 - NO-SIDE FADE ARM, BOOK CAPTURE, AND SETTLEMENT INVERSION LIVE]](items/item-253-two-sided-no-side-taker-edge-and-book-capture.md) |
| 254 | [Extract Serving-Safe Variant-Prediction Runtime From Calibration [COMPLETE 2026-06-23 - SERVING RUNTIME EDGE REMOVED AND ARCHITECTURE RATIFIED]](items/item-254-extract-serving-safe-variant-prediction-runtime.md) |
| 255 | [Taker Current-High Deny Regression Proof [COMPLETE 2026-06-23 - CONFIG-DRIFT CURRENT-HIGH DENY RATIFIED]](items/item-255-taker-current-high-deny-regression-proof.md) |
| 256 | [Post-Fix Taker After-Fee Requalification Campaign [COMPLETE 2026-06-24 - CURRENT-FEE CAMPAIGN CLOSED FAIL-CLOSED]](items/item-256-post-fix-taker-after-fee-requalification-campaign.md) |
| 257 | [Real NO-Book Depth For Two-Sided Taker [COMPLETE 2026-06-23 - REAL NO-BOOK DEPTH GATES LIVE]](items/item-257-real-no-book-depth-for-two-sided-taker.md) |
| 258 | [Maker Active-Day Freshness Recovery And MM Preflight Proof [COMPLETE 2026-06-23 - SELECTED PAPER PROOF PASS]](items/item-258-maker-active-day-freshness-recovery-and-mm-preflight-proof.md) |
| 259 | [Current-Run Artifact Profitability Field Verification [COMPLETE 2026-06-23 - CURRENT-RUN PROFITABILITY VERIFIER GATES PROMOTION]](items/item-259-current-run-artifact-profitability-field-verification.md) |
| 260 | [Daily Maker Paper-Score Freshness SLA [COMPLETE 2026-06-23 - STANDARD MM PAPER SCORE FRESHNESS GATED]](items/item-260-daily-maker-paper-score-freshness-sla.md) |
| 261 | [Taker Canary Tail-Share Demotion On Unsettled Sample [COMPLETE 2026-06-23 - HIGH-TAIL UNSETTLED CANARY DEMOTION LIVE]](items/item-261-taker-canary-tail-share-demotion-on-unsettled-sample.md) |
| 262 | [Proper-Scoring And Reliability Scorecard [COMPLETE 2026-06-23 - CANONICAL SCORECARD AND DAILY REFRESH STEP LIVE]](items/item-262-proper-scoring-and-reliability-scorecard.md) |
| 263 | [Physical Feature-Family Isolated Replay Ratchet [COMPLETE 2026-06-23 - FAIL-CLOSED PHYSICAL FAMILY RATCHET LIVE]](items/item-263-physical-feature-family-isolated-replay-ratchet.md) |
| 264 | [Market Benchmark And Residual Edge Research Lane [COMPLETE 2026-06-23 - MARKET RESIDUAL LANE FAIL-CLOSED]](items/item-264-market-benchmark-and-residual-edge-research-lane.md) |
| 265 | [Settlement-Source Revision And Truth-Label Audit [COMPLETE 2026-06-23 - TRUTH-LABEL AUDIT AND BLOCKER LIVE]](items/item-265-settlement-source-revision-and-truth-label-audit.md) |
| 266 | [Winner-Rank Parity And Market-Top-Miss Repair Gate [COMPLETE 2026-06-23 - PARITY GATE LIVE, CURRENT MODEL BLOCKED]](items/item-266-winner-rank-parity-and-market-top-miss-repair-gate.md) |
| 267 | [Multi-Market Source-Bias Model Extension (Global-Ensemble + NWS, Per-Market Refit) [COMPLETE 2026-06-23 - MULTI-MARKET SOURCE-BIAS ARTIFACTS REFIT WITH RELIABILITY WEIGHTS]](items/item-267-multi-market-source-bias-model-extension.md) |
| 268 | [Afternoon Post-Ramp Per-Market Warm-Centering Correction (15:00-18:00 Local) [COMPLETE 2026-06-23 - AFTERNOON RESIDUAL CENTERING ARTIFACT LIVE]](items/item-268-afternoon-post-ramp-per-market-warm-centering.md) |
| 269 | [Market-Beating Objective Scoreboard And Anti-Anchoring Gate [COMPLETE 2026-06-23 - NORTH-STAR SCOREBOARD LIVE]](items/item-269-market-beating-objective-scoreboard-and-anti-anchoring-gate.md) |
| 270 | [weather.reporting Subdomain Decomposition (Folder Cohesion After Size-Splits) [COMPLETE 2026-06-25 - REPORTING ROOT RATCHETED]](items/item-270-weather-reporting-subdomain-decomposition.md) |
| 271 | [Audit Analysis Operator Loop [COMPLETE 2026-06-23 - DASHBOARD OPERATOR LOOP LIVE]](items/item-271-audit-analysis-operator-loop.md) |
| 272 | [Taker Daily-Roll Liveness And Artifact Restart [COMPLETE 2026-06-23]](items/item-272-taker-daily-roll-liveness-and-artifact-restart.md) |
| 273 | [Settlement-Scored Taker Counterfactual Tape [COMPLETE 2026-06-23]](items/item-273-settlement-scored-taker-counterfactual-tape.md) |
| 274 | [Taker Model-Version Shadow Bakeoff [COMPLETE 2026-06-23]](items/item-274-taker-model-version-shadow-bakeoff.md) |
| 275 | [Taker Clustered Statistical Promotion Gate [COMPLETE 2026-06-23]](items/item-275-taker-clustered-statistical-promotion-gate.md) |
| 276 | [NO-Side Taker Data Collection Campaign [COMPLETE 2026-06-23 - REAL NO-SIDE COUNTERFACTUAL CAMPAIGN LIVE]](items/item-276-no-side-taker-data-collection-campaign.md) |
| 277 | [Maker All-Market Liveness And Fresh Data SLA [COMPLETE 2026-06-23 - TWO ALL-MARKET PROOF RUNS PASS]](items/item-277-maker-all-market-liveness-and-fresh-data-sla.md) |
| 278 | [Maker Model-Version Shadow Bakeoff [COMPLETE 2026-06-23 - MAKER MODEL-VARIANT BAKEOFF LIVE]](items/item-278-maker-model-version-shadow-bakeoff.md) |
| 279 | [Maker Clustered Statistical Promotion Gate [COMPLETE 2026-06-23 - MARKET-DAY CLUSTER GATE LIVE]](items/item-279-maker-clustered-statistical-promotion-gate.md) |
| 280 | [Maker CLOB Fill Evidence And Trade-Size Completeness [COMPLETE 2026-06-23 - FILL-EVIDENCE COMPLETENESS GATE LIVE]](items/item-280-maker-clob-fill-evidence-and-trade-size-completeness.md) |
| 281 | [Settlement-Source Authentication And Transient-Failure Typing And Backfill Poisoning Guard [COMPLETE 2026-06-24 - FAILURE TYPING, RECOVERY, AND FLEET BLOCKERS LANDED]](items/item-281-settlement-source-auth-failure-and-backfill-poisoning-guard.md) |
| 282 | [Maker Parallel CLOB Raw-Book Refresh SLA [COMPLETE 2026-06-24 - PARALLEL RAW-REFRESH AND SPLIT FRESHNESS LANDED]](items/item-282-maker-parallel-clob-raw-book-refresh-sla.md) |
| 283 | [Settlement-Calibrated And Market-Shrunk Taker Fair Value [COMPLETE 2026-06-23 - CALIBRATED MARKET-SHRUNK TAKER FAIR LIVE]](items/item-283-settlement-calibrated-market-shrunk-taker-fair-value.md) |
| 284 | [After-Fee EV Entry Gate, Adverse-Selection Edge Cap, And EV-Ranked Taker Allocation [COMPLETE 2026-06-23 - AFTER-COST EV GATE AND RANKING LIVE]](items/item-284-after-fee-ev-gate-adverse-selection-cap-ev-ranked-allocation.md) |
| 285 | [Taker Edge-Permission Map For Per-Slice Proven-Skill Entry [COMPLETE 2026-06-23 - FAIL-CLOSED TAKER EDGE PERMISSION LIVE]](items/item-285-taker-edge-permission-map-per-slice-proven-skill.md) |
| 292 | [Cross-Market Correlated-Regime Exposure And Joint-Loss Cap For Trading Bots [COMPLETE 2026-06-24 - CORRELATED-REGIME CAPS WIRED INTO TAKER AND MAKER RISK]](items/item-292-cross-market-correlated-regime-exposure-cap.md) |
| 293 | [Daily-Analysis Correctness And Fail-Closed Robustness Fixes [COMPLETE 2026-06-24 - FAIL-CLOSED PROMOTION AND STABLE DAILY LEDGERS]](items/item-293-daily-analysis-correctness-and-failclosed-robustness-fixes.md) |
| 294 | [Daily-Analysis Input Freshness, Coverage, And Cross-Artifact Consistency Gate [COMPLETE 2026-06-24 - INPUT GATE FAIL-CLOSED IN DAILY ANALYSIS]](items/item-294-daily-analysis-input-freshness-coverage-and-consistency-gate.md) |
| 295 | [Longitudinal Daily-Analysis: Closed-Loop Blocker Lifecycle, Chronic Escalation, And Metric Anomaly Detection [COMPLETE 2026-06-24 - LEDGER HISTORY CONSUMED FOR BLOCKER LIFECYCLE AND ANOMALIES]](items/item-295-longitudinal-daily-analysis-blocker-lifecycle-and-anomaly-detection.md) |
| 296 | [Impact- And Confidence-Aware Daily Prioritization And Model Promotion Gating [COMPLETE 2026-06-24 - IMPACT RANKING AND CONFIDENCE-GATED PROMOTION LIVE]](items/item-296-impact-and-confidence-aware-daily-prioritization-and-promotion-gating.md) |
| 297 | [Calibration-Drift And Directional-Bias Daily Tracking [COMPLETE 2026-06-24 - CALIBRATION AND BIAS LEDGER TREND LIVE]](items/item-297-calibration-drift-and-directional-bias-daily-tracking.md) |
| 298 | [Automatic Experiment Queue And Drift-Triggered Retrain Loop [COMPLETE 2026-06-24 - STRUCTURED QUEUE, NIGHTLY EXECUTION, AND RETRAIN RECOMMENDATION LIVE]](items/item-298-automatic-experiment-queue-and-drift-triggered-retrain-loop.md) |
| 300 | [Current Exchange Economics And Rule-Drift Gate [COMPLETE 2026-06-24 - SNAPSHOT AND DRIFT GATES ENFORCED FOR PAPER EVIDENCE]](items/item-300-current-exchange-economics-and-rule-drift-gate.md) |
| 301 | [June 23 Location Bias And Winner-Rank Repair Packet [COMPLETE 2026-06-24 - LOCATION-BIAS PACKET, REPAIR MANIFESTS, AND PROTECTED-SLICE REPLAY LIVE]](items/item-301-june-23-location-bias-and-winner-rank-repair-packet.md) |
| 302 | [Post-Settlement Disagreement Audit Rehydration Gate [COMPLETE 2026-06-24 - POST-LABEL REHYDRATION GATED]](items/item-302-post-settlement-disagreement-audit-rehydration-gate.md) |
| 303 | [Post-Settlement Taker Zero-Fill Evidence And Artifact Canonicalization [COMPLETE 2026-06-24 - ZERO-FILL DAYS AND PRE-LABEL BAKEOFFS NOW PRODUCE CANONICAL POST-SETTLEMENT EVIDENCE]](items/item-303-post-settlement-taker-zero-fill-evidence-and-artifact-canonicalization.md) |
| 304 | [Maker Current-Run Evidence Selection And Quote-Starvation Gate [COMPLETE 2026-06-24 - TRADING EVIDENCE SELECTS TARGET-DATE RUNS AND GATES QUOTE STARVATION]](items/item-304-maker-current-run-evidence-selection-and-quote-starvation-gate.md) |
| 305 | [Settled-Day Finalization Order, Partial-Label, And Nightly Run-Date Gate [COMPLETE 2026-06-24 - NIGHTLY ANALYSIS CAN RUN BEFORE FINAL ARTIFACTS AND MIX TARGET DATES]](items/item-305-settled-day-finalization-order-partial-label-and-nightly-run-date-gate.md) |
| 308 | [Model-Performance Scoring Liveness And Regenerate-On-Settlement [COMPLETE 2026-06-24 - MODEL-SKILL SCORING WENT 3 DAYS STALE WHILE LABELS ARE CURRENT]](items/item-308-model-performance-scoring-liveness-and-regenerate-on-settlement.md) |
| 309 | [Current Exchange-Economics Snapshot Production, Verification, And Accept-Baseline Workflow [COMPLETE 2026-06-24 - SNAPSHOT TEMPLATE, PUBLISH, ACCEPT-BASELINE, AND REFRESH CADENCE IN PLACE]](items/item-309-exchange-economics-snapshot-production-verification-and-accept-baseline.md) |
| 310 | [Toronto WU Current-Max Boundary Over-Lock Guard [COMPLETE 2026-06-24 - SUPPORT-ONLY CURRENT-MAX BOUNDARY GUARD LIVE]](items/item-310-toronto-wu-current-max-boundary-overlock-guard.md) |
| 311 | [Taker Evidence-Starvation Classification And Upstream Liveness Gate [COMPLETE 2026-06-25 - LATEST-TICK STARVATION FAILS CLOSED]](items/item-311-taker-evidence-starvation-upstream-liveness-gate.md) |
| 312 | [Taker And Maker Daily-Roll Auto-Restart Supervisor And Stale-Fingerprint Recovery [COMPLETE 2026-06-25 - BOT DAILY-ROLL ENSURE SUPERVISORS AND STALE-FINGERPRINT RECOVERY LIVE]](items/item-312-taker-maker-daily-roll-auto-restart-supervisor-and-stale-fingerprint-recovery.md) |
| 321 | [Model Production Readiness, Evidence Integrity, And Staged Release Program [OPEN 2026-07-16 - BOOTSTRAP SOURCE CONTRACT FIXED; REAL RETRAIN/SHADOW/PAPER/CAPITAL GATES OPEN]](items/item-321-model-production-readiness-evidence-integrity-and-staged-release-program.md) |
| 322 | [Bounded Taker Long-Loop Memory And Incremental Tape Persistence [PARTIAL 2026-07-16 - INPUT DISCOVERY BOUNDED; POPULATED SOAK PENDING]](items/item-322-bounded-taker-long-loop-memory-and-incremental-tape-persistence.md) |
| 323 | [Shared Forecast Payload CAS And Single-Fetch Fan-Out [PARTIAL 2026-07-15 - CONTROLLED STORAGE HOUR PASSED; HARDENING ON ISOLATED BRANCH; LIVE NETWORK PROOF AND REAL-ROOT INVENTORY PENDING]](items/item-323-shared-forecast-payload-cas-and-single-fetch-fan-out.md) |
| 324 | [Bounded Daily Settlement Refresh Resource Admission And Step Isolation [PARTIAL 2026-07-15 - FIRST POST-GATE RECEIPT SAFELY DEFERRED BUT SCHEDULER-UNATTESTED AND NON-COUNTABLE]](items/item-324-bounded-daily-settlement-refresh-resource-admission-and-step-isolation.md) |
| 325 | [Tiered Data Retention And Verified Archive Offload [OPEN 2026-07-21 - DESIGN RECORDED; NO DELETION AUTHORIZED YET]](items/item-325-tiered-data-retention-and-verified-archive-offload.md) |

### Architecture And Maintainability

| Item | File |
| ---: | --- |
| 87 | [Canonical CLI And Import Surface Retirement [COMPLETE 2026-06-16 - CANONICAL PACKAGE SURFACE LIVE]](items/item-87-canonical-cli-and-import-surface-retirement.md) |
| 88 | [Shared Scoring, Formatting, And Backtest Utility Split [COMPLETE 2026-06-16 - SHARED HELPER MODULES LIVE]](items/item-88-shared-scoring-formatting-and-backtest-utility-split.md) |
| 89 | [Explicit Model Build Contract And Source Adapter Boundary [COMPLETE 2026-06-16 - EXPLICIT BUILD CONTRACTS LIVE]](items/item-89-explicit-model-build-contract-and-source-adapter-boundary.md) |
| 90 | [Large Module Decomposition For Calibration And Market Operations [COMPLETE 2026-06-16 - CALIBRATION AND PREFLIGHT SPLITS LIVE]](items/item-90-large-module-decomposition-for-calibration-and-market-operations.md) |
| 91 | [Repository Path Policy Hardening [COMPLETE 2026-06-16 - REPO-ABSOLUTE DEFAULT PATHS LIVE]](items/item-91-repository-path-policy-hardening.md) |
| 92 | [Streamlit App Import Hygiene And UTF-8 Cleanup [COMPLETE 2026-06-16 - APP HYGIENE GUARD LIVE]](items/item-92-streamlit-app-import-hygiene-and-utf8-cleanup.md) |
| 93 | [Canonical Temperature Rounding And Unit Helpers [COMPLETE 2026-06-16 - CANONICAL UNITS HELPER LIVE]](items/item-93-canonical-temperature-rounding-and-unit-helpers.md) |
| 94 | [Internal Compatibility Fallback Retirement [COMPLETE 2026-06-16 - INTERNAL FALLBACKS RETIRED]](items/item-94-internal-compatibility-fallback-retirement.md) |
| 95 | [Shared Supervisor Runtime Primitives [COMPLETE 2026-06-16 - SHARED SUPERVISOR PRIMITIVES LIVE]](items/item-95-shared-supervisor-runtime-primitives.md) |
| 96 | [Pure Distribution Result And Calibration Runtime Boundary [COMPLETE 2026-06-16 - DISTRIBUTION RESULT OWNS METADATA]](items/item-96-pure-distribution-result-and-calibration-runtime-boundary.md) |
| 97 | [Shared IO, Time, And Structured Logging Utilities [COMPLETE 2026-06-16 - SHARED RUNTIME UTILITIES LIVE]](items/item-97-shared-io-time-and-structured-logging-utilities.md) |
| 98 | [Remaining Large Module Decomposition [COMPLETE 2026-06-16 - MM EXCHANGE REPORT OWNER SPLIT]](items/item-98-remaining-large-module-decomposition.md) |
| 99 | [Package Dependency Boundary Ratchet [COMPLETE 2026-06-16 - PACKAGE EDGE RATCHET LIVE]](items/item-99-package-dependency-boundary-ratchet.md) |
| 107 | [Research Audit Harness And CLI Smoke Reliability [COMPLETE 2026-06-17 - RESEARCH HARNESS LIVE]](items/item-107-research-audit-harness-and-cli-smoke-reliability.md) |
| 112 | [Single-Writer Loop Status And JSONL Integrity [COMPLETE 2026-06-17 - LOOP INTEGRITY GATE LIVE]](items/item-112-single-writer-loop-status-and-jsonl-integrity.md) |
| 119 | [Python Repo Audit Reliability Fixes [COMPLETE 2026-06-18 - AUDIT FIXES LIVE]](items/item-119-python-repo-audit-reliability-fixes.md) |
| 122 | [UI And Loop Serialization Health Cleanup [COMPLETE 2026-06-18 - ARROW SAFE TABLES AND JSONL QUARANTINE]](items/item-122-ui-and-loop-serialization-health-cleanup.md) |
| 126 | [Clean-Checkout Architecture File Ownership [COMPLETE 2026-06-20 - CLEAN-CHECKOUT AND PACKAGE RATCHET PASS]](items/item-126-clean-checkout-architecture-file-ownership.md) |
| 127 | [Compatibility Shim Expiration And Removal Plan [COMPLETE 2026-06-18 - EXPIRATION RATCHET LIVE]](items/item-127-compatibility-shim-expiration-and-removal-plan.md) |
| 128 | [Import Helper Policy And Scheduled Worker Packaging [COMPLETE 2026-06-18 - IMPORT POLICY DOCUMENTED]](items/item-128-import-helper-policy-and-scheduled-worker-packaging.md) |
| 129 | [Streamlit Single-Market View Extraction [COMPLETE 2026-06-18 - SINGLE-MARKET VIEW SPLIT LIVE]](items/item-129-streamlit-single-market-view-extraction.md) |
| 130 | [Large Module Decomposition Phase 2 [COMPLETE 2026-06-18 - REPORT AND EVIDENCE OWNER SPLITS LIVE]](items/item-130-large-module-decomposition-phase-2.md) |
| 131 | [Model Artifact Storage Growth Guard [COMPLETE 2026-06-18 - SIZE AUDIT AND STORAGE POLICY LIVE]](items/item-131-model-artifact-storage-growth-guard.md) |
| 132 | [Active Docs Canonical Command Normalization [COMPLETE 2026-06-18 - ACTIVE DOC LINT LIVE]](items/item-132-active-docs-canonical-command-normalization.md) |
| 133 | [Data Runtime Locality And Fixture Boundary Guard [COMPLETE 2026-06-18 - DATA BOUNDARY GUARD LIVE]](items/item-133-data-runtime-locality-and-fixture-boundary-guard.md) |
| 161 | [Loop Restart Noise And Current-Code Cadence Proof [PARTIAL 2026-06-25 - JUNE 25 SOAK BLOCKED, NEW CLEAN SOAK NEEDED]](items/item-161-loop-restart-noise-and-current-code-cadence-proof.md) |
| 171 | [Local Data Retention And CLOB Tape Storage Cleanup [COMPLETE 2026-06-20 - DATA RETENTION INVENTORY AND DAILY BUDGET LIVE]](items/item-171-local-data-retention-and-clob-tape-storage-cleanup.md) |
| 172 | [Artifact Storage Externalization And Git Object Store Cleanup [COMPLETE 2026-06-20 - LFS ARTIFACT PREFLIGHT PASS]](items/item-172-artifact-storage-externalization-and-git-object-store-cleanup.md) |
| 173 | [Post-Agent Large Module Decomposition And Ownership Split [COMPLETE 2026-06-20 - FACADES SPLIT AND SIZE AUDIT RATIFIED]](items/item-173-post-agent-large-module-decomposition-and-ownership-split.md) |
| 174 | [Configuration Registry Hygiene And Volatile Metadata Refresh [COMPLETE 2026-06-20 - DURABLE CONFIGS AND FRESH GENERATED EVENTS]](items/item-174-configuration-registry-hygiene-and-volatile-metadata-refresh.md) |
| 175 | [Roadmap Backlog Normalization And Historical Noise Reduction [COMPLETE 2026-06-21 - ACTIVE BACKLOG PARSER AND LINT LIVE]](items/item-175-roadmap-backlog-normalization-and-historical-noise-reduction.md) |
| 176 | [Local Generated State And Tooling Cleanup Sweep [PARTIAL 2026-07-12 - LF NORMALIZATION APPLIED, RECURRING CACHE SWEEP AWAITS QUIET WORKTREE]](items/item-176-local-generated-state-and-tooling-cleanup-sweep.md) |
| 177 | [Core Model Validation And Serving Skew Repair [PARTIAL 2026-06-21 - CLIMATOLOGY CACHE BOUNDED, CHILD REPAIRS OPEN]](items/item-177-core-model-validation-and-serving-skew-repair.md) |
| 204 | [Roadmap Index Ownership Lint And Duplicate Membership [COMPLETE 2026-06-21 - INDEX LINT GATE LIVE]](items/item-204-roadmap-index-ownership-lint-and-duplicate-membership.md) |
| 205 | [Daily Refresh Orchestration Facade Split [COMPLETE 2026-06-21 - DAILY REFRESH FACADE BELOW THRESHOLD]](items/item-205-daily-refresh-orchestration-facade-split.md) |
| 206 | [Compatibility Shim Expiration Removal Execution [OPEN 2026-07-12 - OWNED, PRE-SCAN CLEAN, EXECUTES ON 2026-07-18]](items/item-206-compatibility-shim-expiration-removal-execution.md) |
| 306 | [Daily-Roll Log Hygiene And Historical Error Separation [COMPLETE 2026-06-24 - CURRENT-WINDOW HEALTH SEPARATED FROM HISTORICAL INCIDENTS]](items/item-306-daily-roll-log-hygiene-and-historical-error-separation.md) |
| 307 | [Snapshot And Collection Loop Restart-Runaway Root-Cause Remediation [PARTIAL 2026-07-16 - OBSERVATION CACHE ISOLATED, DEPLOYMENT/CLEAN SOAK PENDING]](items/item-307-snapshot-loop-restart-runaway-root-cause-remediation.md) |
| 313 | [Python Runtime Audit Regression Gate [COMPLETE 2026-06-25 - STRICT RUNTIME AUDIT GATE LIVE]](items/item-313-python-runtime-audit-regression-gate.md) |
| 314 | [Artifact And Training-Data Schema Forward-Migration To Retire Historical-Only Quarantines [COMPLETE 2026-06-25 - FORWARD MIGRATION AND ROW RECOVERY LIVE]](items/item-314-artifact-schema-forward-migration-retire-historical-only-quarantine.md) |
| 315 | [First-Class Repair Integration Into The Active Artifact And Replay Contract (Retire The Row-Export Surrogate) [COMPLETE 2026-06-25 - ACTIVE REPAIR INTEGRATION CONTRACT ADDED]](items/item-315-first-class-repair-integration-retire-row-export-surrogate.md) |
| 316 | [Unify The Blanket Tail/Warm/Weak-Slot Taker Blocks With The Per-Slice Edge-Permission Map [COMPLETE 2026-06-25 - EDGE-PERMISSIONED RISK GUARDS LIVE]](items/item-316-unify-blanket-taker-risk-blocks-with-edge-permission-map.md) |
| 317 | [Marine Water-Contrast Source/Model Boundary Ratchet [COMPLETE 2026-06-25 - SOURCE-LOCAL CUTOFF CONTRACT RESTORES RATCHET]](items/item-317-marine-water-contrast-source-model-boundary-ratchet.md) |
| 318 | [Post-Threshold Large Module Decomposition Refresh [COMPLETE 2026-06-25 - MODULE-SIZE WARNING SET CLEARED]](items/item-318-post-threshold-large-module-decomposition-refresh.md) |
| 319 | [Material Coverage Grading For Settled-Label Promotion Countability [COMPLETE 2026-06-25 - MATERIAL COVERAGE COUNTABILITY LIVE]](items/item-319-material-coverage-grading-for-settled-label-promotion-countability.md) |
| 320 | [Capture-Cadence Due-Boundary Tolerance For Strict-Complete Day Coverage [COMPLETE 2026-06-27 - DUE-BOUNDARY TOLERANCE LIVE]](items/item-320-capture-cadence-due-boundary-tolerance-for-strict-complete-coverage.md) |

## Maintenance Conventions

- Update the owning item file rather than this index when changing item scope, status, acceptance criteria, or implementation notes.
- Keep numbered item headings in the format `# N. Title [STATUS]` so audit tooling and human readers can find them quickly.
- Regenerate the compact active backlog with `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`; this also lints `ROADMAP.md` index ownership, links, title text, and status text against canonical item files.
- Historical implementation updates and command transcripts inside completed or dated sections are historical-only evidence, not current operator instructions.
- Add broad narrative updates to `overview.md`, track framing to `tracks/`, and historical findings to `audits/`.
- When adding or moving numbered items, update the table above in the same change.
