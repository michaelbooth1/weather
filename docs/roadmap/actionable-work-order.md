# Actionable Roadmap Work Order - 2026-06-22

Source: `docs/roadmap/active-backlog.md` and the numbered roadmap item files as
of 2026-06-22. This filters roadmap items that are not `DONE` or `COMPLETE`
down to work we can start now. Items blocked by external access, future active
days, calendar windows, or parent roll-up dependencies are removed from the
main order and listed afterward.

Completed roadmap items are intentionally omitted, even when they were part of
an earlier work sequence.

## Recommended Order

| Rank | Item | Why this comes here |
| ---: | --- | --- |
| 1 | [240. Taker Fee, Slippage, And Executable-Depth Profitability Model](items/item-240-taker-fee-slippage-and-executable-depth-profitability-model.md) | Add executable net PnL before any bakeoff or canary result can be treated as live-profit evidence. |
| 2 | [241. Market Benchmark No-Trade And Profitability Scoreboard](items/item-241-market-benchmark-no-trade-and-profitability-scoreboard.md) | Compare model trades with market/no-trade baselines after after-fee scoring exists, so market-smarter slices can be blocked. |
| 3 | [242. Decisive Model Proof Packet And Gate Stack Ratchet](items/item-242-decisive-model-proof-packet-and-gate-stack-ratchet.md) | Consolidate the overlapping weather-model gates into one proof packet before adding more repair diagnostics. |
| 4 | [250. Austin HGB Per-Location Requalification](items/item-250-austin-hgb-per-location-requalification.md) | Fail-close Austin serving evidence immediately after proof-packet and market-baseline gates define the local requalification contract. |
| 5 | [252. Impossible Guidance Feature Quarantine](items/item-252-impossible-guidance-feature-quarantine.md) | Quarantine physically impossible guidance before adding new late-day or cluster features that might consume it. |
| 6 | [249. Official METAR Rollover Lock-In Signal](items/item-249-official-metar-rollover-lockin-signal.md) | Add official rollover state before building dampeners that depend on official-current-below-high evidence. |
| 7 | [251. Standing-High Partial Lock-In Dampener](items/item-251-standing-high-partial-lockin-dampener.md) | Build partial late-day dampening after official rollover diagnostics can distinguish flat third-party current from official drop. |
| 8 | [248. Austin Robust Forecast-Cluster Signal](items/item-248-austin-robust-forecast-cluster-signal.md) | Repair feature-path warm-source overreaction after source validity and late-day lock-in context are explicit. |
| 9 | [243. Closed Market-Day Parquet Archive Contract](items/item-243-closed-market-day-parquet-archive-contract.md) | Define the closed-day archive and manifest contract before converting historical snapshot tapes or changing readers. |
| 10 | [244. Historical Snapshot Parquet Backfill And Validation Harness](items/item-244-historical-snapshot-parquet-backfill-validation.md) | Build the dry-run/apply conversion path after the archive contract exists, with source tapes preserved. |
| 11 | [245. Parquet-First Historical Analysis Readers](items/item-245-parquet-first-historical-analysis-readers.md) | Move heavy historical analyses to validated Parquet only after converted partitions and manifests are available. |
| 12 | [228. Predawn Weak-Slot Repair Candidate Gate](items/item-228-predawn-weak-slot-repair-candidate-gate.md) | Keep the scoped weak-slot repair as the first weather-model item because its no-go sweep defines what residual repairs must target. |
| 13 | [219. Bottom-Location Early/Midday Winner-Centering Repair](items/item-219-bottom-location-early-midday-winner-centering.md) | Build the main no-market repair lane for the weakest bottom-location early and midday slices once the weak-slot candidate is scoped. |
| 14 | [230. Exact-Band And Settlement-Distance-0 Early-Hour Calibration](items/item-230-exact-band-and-settlement-distance-zero-early-hour-calibration.md) | Target the exact-band and distance-zero early-hour calibration failures that remain after weak-slot and bottom-location repairs are measurable. |
| 15 | [232. Current-Max Trust Retrain And Warm-Tail Replay](items/item-232-current-max-trust-retrain-and-warm-tail-replay.md) | Prove current-max trust fields improve warm-tail and anomaly handling before re-exporting broader artifacts. |
| 16 | [224. Pooled F Retrain/Re-Export Location Gate](items/item-224-pooled-f-retrain-reexport-location-gate.md) | Re-export and validate the active pooled F artifact only after the narrow early-hour and current-max gates above are in place. |
| 17 | [178. Serving-Time Ordinal Smoothing Train/Serve Skew](items/item-178-serving-ordinal-smoothing-train-serve-skew.md) | Close the remaining serving validation step with regenerated artifact evidence and weak-slot/ramp/late checks after the retrain path is stable. |
| 18 | [233. Validate-What-You-Serve Early-Hour Calibration Head](items/item-233-validate-what-you-serve-early-hour-calibration-head.md) | Turn the isolated early-hour fixes into a served-distribution calibration contract after the immediate repairs are measurable. |
| 19 | [160. Early-Hour Model Skill Remediation To Positive Daily-First Gate](items/item-160-early-hour-model-skill-remediation-to-positive-daily-first-gate.md) | Reconcile the early-hour remediation item after candidate-specific gates show positive daily-first skill. |
| 20 | [147. Early-Hour Winner-Centering Candidate](items/item-147-early-hour-winner-centering-candidate.md) | Reconcile the original winner-centering candidate after items 219 and 228 produce active evidence. |
| 21 | [134. Early-Day Forecast Profile Calibration](items/item-134-early-day-forecast-profile-calibration.md) | Revisit the older early-day profile candidate once the new early-hour gate stack is in place. |
| 22 | [135. Cutoff-Regime Forecast/Observation Weighting](items/item-135-cutoff-regime-forecast-observation-weighting.md) | Re-evaluate regime weighting with the same market-specific and weak-slot gates. |
| 23 | [136. Forecast Source-State Reliability Calibrator](items/item-136-forecast-source-state-reliability-calibrator.md) | Finish source-state explanation and degraded-source thresholds after source/missingness and early-hour gate evidence exists. |
| 24 | [138. Weak Input-Family Pruning And Regime Backfill](items/item-138-weak-input-family-pruning-and-regime-backfill.md) | Prune weak families after the new gates expose whether they fail by market, regime, or missingness. |
| 25 | [186. Soil-Moisture And Antecedent Land-Surface Dryness Predictor](items/item-186-soil-moisture-antecedent-dryness-predictor.md) | Highest-value physical-data child with most plumbing already present; finish precipitation backfill and isolated settlement gates. |
| 26 | [187. Forecast Shortwave-Radiation And Peak-Window Insolation Features](items/item-187-forecast-shortwave-insolation-features.md) | Run the isolated replay for the already-wired insolation controls before adding noisier source families. |
| 27 | [191. Lake/Sea Surface-Temperature Contrast Feature](items/item-191-lake-sea-surface-temperature-contrast.md) | Finish SST backfill and lake/sea-breeze gates after the core land-surface and radiation controls above. |
| 28 | [189. ECMWF And ML-NWP Ensemble Forecast Members](items/item-189-ecmwf-ml-nwp-ensemble-members.md) | Add run-archive coverage after the nearer physical feature families are gated. |
| 29 | [190. NBM Native Probabilistic Tmax Consumption](items/item-190-nbm-probabilistic-tmax-consumption.md) | Add probabilistic payload archive and US-slice gates after the ensemble archive path is settled. |
| 30 | [188. Aerosol And Wildfire-Smoke Suppression Features](items/item-188-aerosol-wildfire-smoke-features.md) | Keep smoke as a targeted regime feature until enough high-smoke historical evidence exists. |
| 31 | [32. Reanalysis And Synoptic Feature Layer](items/item-32-reanalysis-and-synoptic-feature-layer.md) | Resume narrower subfamily promotion only after the above physical-data gates clarify source value. |
| 32 | [35. Unified Continuous-Density Model](items/item-35-unified-continuous-density-model.md) | Defer model-class expansion until location, early-hour, and core feature evidence is stable. |
| 33 | [176. Local Generated State And Tooling Cleanup Sweep](items/item-176-local-generated-state-and-tooling-cleanup-sweep.md) | Do the remaining cleanup after active generated artifacts and long-running evidence jobs are no longer in flight. |

## Removed From Immediate Work Order

These are still active roadmap items, but they should not drive the next work
sequence because their remaining work is blocked or only closes after child
items finish.

| Item | Reason removed |
| --- | --- |
| [48. F-Family Promotion Readiness And Serving Parity](items/item-48-f-family-promotion-readiness-and-serving-parity.md) | Parent readiness claim; close after the location, retrain, early-hour, and live-forward gates clear. |
| [67. Authenticated Exchange Adapter And MM-2 Pilot Harness](items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md) | Needs live account/platform evidence before remaining acceptance can be proven. |
| [137. Official Guidance Sparse-Coverage Evidence Growth](items/item-137-official-guidance-sparse-coverage-evidence-growth.md) | Waiting on row growth/backfill coverage; actionable source work is represented by items 189 and 190. |
| [144. Early-Hour Market-Aware Risk Guardrail](items/item-144-early-hour-market-aware-risk-guardrail.md) | Needs live-forward markout evidence. |
| [146. Tape Backup Capacity And CLOB Tiered Retention](items/item-146-tape-backup-capacity-and-clob-tiered-retention.md) | Needs an external durable backup root with enough capacity. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Needs an external durable repository outside the workspace, credentials, and restore-drill evidence. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Depends on item 246 being live and restore-verified before guarded local mirror cleanup can apply. |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | Local raw restore is absent and future train-side CLOB days are required. |
| [157. Live-Forward Snapshot Cadence SLO Closure](items/item-157-live-forward-snapshot-cadence-slo-closure.md) | June 21 is nonrecoverable; completion depends on a new active day finishing cleanly. |
| [161. Loop Restart Noise And Current-Code Cadence Proof](items/item-161-loop-restart-noise-and-current-code-cadence-proof.md) | Current-source soak and June 23 aging evidence are pending. |
| [177. Core Model Validation And Serving Skew Repair](items/item-177-core-model-validation-and-serving-skew-repair.md) | Parent roll-up; close after item 178 and retrain/replay evidence settle. |
| [185. Daily-High Predictor Data-Source Expansion](items/item-185-daily-high-predictor-data-source-expansion.md) | Parent roll-up; direct work is in child items 186-191. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | Removal window starts after 2026-07-18. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Requires a clean future active day with snapshot cadence, CLOB freshness, and current-code soak evidence. |
