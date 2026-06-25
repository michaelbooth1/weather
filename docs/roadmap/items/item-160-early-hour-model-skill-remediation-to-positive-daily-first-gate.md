# 160. Early-Hour Model Skill Remediation To Positive Daily-First Gate [PARTIAL 2026-06-24 - MODEL-READY ACTIVE CANDIDATE, READINESS/PROGRESS BLOCKED]

Goal: close the early-hour model gap that blocks promotion despite directional
all-day progress.

Source: the latest hourly model performance gate. Early-hour model Brier trails
market by `0.0159`, above the `0.0030` tolerance, and early-hour log loss trails
market by `0.1693`, above the `0.0100` tolerance. The progress audit remains
`DIRECTIONAL` with `claim_allowed=False`: only 1 positive-skill comparable day,
rolling daily-first skill `-0.2290`, and current headline skill still negative.

Why this matters: aggregate progress can hide a timing failure. A model that is
competitive late in the day can still be unsafe for early market-making,
promotion, or broad improvement claims if the 00:00-08:00 window remains worse
than market.

## Design

1. Keep the current-serving hourly performance gate blocking until a candidate
   proves early-hour improvement with candidate-specific hourly evidence.
2. Separate no-market weather-model remediation from market-aware risk overlays.
3. Prioritize forecast-centering/current-max validation candidates for the
   early window, because market-blend improvements cannot prove weather-model
   edge.
4. Add daily-first and early-hour gates to candidate promotion reports so a
   candidate cannot pass only on aggregate Brier.
5. Track per-market early-hour blockers to distinguish one-market failures from
   fleet-wide early-window calibration problems.

- [x] Produce a candidate hourly-performance report for the next early-hour
  remediation candidate against the current corpus.
- [x] Add per-market early-hour Brier/log-loss deltas to the remediation
  registry and daily learning.
- [x] Require early-hour candidate Brier/log-loss to clear tolerance before it
  can mitigate the current-serving hourly blocker.
- [x] Keep market-aware overlays classified as quote/risk evidence, not
  no-market promotion evidence.
- [x] Rerun progress audit after each accepted early-hour candidate to update
  rolling daily-first skill and positive-skill day counts.

## 2026-06-20 Update

Implemented the missing tracking surface rather than relaxing the blocker.
`weather.reporting.hourly_model_performance` now adds
`remediation_registry.early_hour_market_deltas` with per-market early-hour
Brier/log-loss deltas, blocking gates, rows, days, snapshots, and winner
probabilities. `weather.reporting.daily_learning` carries those rows into the
scorecard, report, and learnings.

Current generated evidence:

- Current-serving hourly gate remains `BLOCK` with 2 blockers.
- All 12 markets are early-hour blocked by both Brier and log-loss regression.
  Worst current-serving Brier deltas are `seattle=-0.0393`, `nyc=-0.0251`,
  `austin=-0.0196`, `toronto=-0.0183`, and `miami=-0.0178`.
- `item147_time_split_alpha` candidate-hourly gate is `PASS` with 44
  early-hour market-days, early delta vs market `-0.0008`, and early log-loss
  delta vs market `-0.0027`.
- Promotion-readiness tests verify that only a matching candidate-hourly gate
  `PASS` can mitigate the current-serving hourly blocker, and that
  market-informed candidates remain blocked as core model-promotion evidence.

Remaining blocker: do not close this item until progress audit shows
non-negative rolling daily-first skill after an accepted candidate and the full
promotion report is regenerated from a successful promotion refresh.

2026-06-20 post-resume refresh: `promotion_refresh` now reruns to completion
inside daily refresh, and progress audit was regenerated afterward. The
candidate promotion verdict is still `BLOCK` with
`candidate_cutover_decision=DO_NOT_CUT_OVER`, while progress audit remains
`DIRECTIONAL` and `claim_allowed=False`. The current comparable-day summary is
still `1` positive-skill day, rolling daily-first skill
`-0.3334277590701413`, and `48` promotion-grade market-days. This keeps the
item partial: the hourly candidate evidence is useful, but it has not produced
an accepted candidate plus non-negative rolling daily-first proof.

Acceptance: a promotion candidate may clear this item only when its
candidate-specific hourly gate passes for the 00:00-08:00 window, daily-first
skill is non-negative over the required rolling window, and the promotion
report preserves the distinction between weather-model lift and market-aware
risk overlay.

## 2026-06-22 Positive Daily-First Gate

Added `weather.reporting.serving_gates.early_hour_positive_daily_first_gate` with schema
`early_hour_positive_daily_first_gate_v0.1`.

Artifacts:

- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`

Command:

`python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md`

Result: **BLOCK** with 6 blockers. The gate now reconciles candidate hourly,
weak-slot, served-distribution, progress-audit, and daily-first trend evidence
before this item can close.

Passing evidence:

- Repaired candidate 10-minute weak-slot gate is `PASS` with
  `delta_vs_market=-0.0089`.

Current blockers:

- Candidate hourly early gate is `BLOCK`; early-hour Brier trails market by
  `+0.0048 > +0.0030`.
- Served-distribution contract is `BLOCK`; repaired evidence is
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- Rolling daily-first skill is still negative at `-0.2212`.
- Positive daily-first days are `1`; the gate requires `3`.
- Promotion-grade market-days are `36`; the gate requires `84`.
- Progress audit remains `DIRECTIONAL` and `claim_allowed=False`, with blockers
  for positive-skill day count, daily-first skill, market-day count,
  live-forward SLO, independent baseline evidence, and mixed runtime identity.

Remaining unblock: produce an accepted early-hour candidate whose hourly gate
passes, promote it through active replay-contract evidence, and rerun progress
audit until rolling daily-first skill is non-negative with enough positive days
and promotion-grade market-days.

## 2026-06-22 positive daily-first gate refresh

Regenerated the positive daily-first gate after refreshing the served-
distribution contract:

- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`

The refreshed gate remains `BLOCK` with `6` blockers. The repaired candidate
10-minute weak-slot gate is still the only passing acceptance dependency, with
weak-slot `delta_vs_market=-0.0089`.

Current blockers:

- `candidate_hourly_early_gate`: early-hour candidate Brier trails market by
  `+0.0048 > +0.0030`.
- `served_distribution_contract`: served-distribution evidence remains
  `row_export_surrogate`, replay verdict is `BLOCK`, and cutover is
  `DO_NOT_CUT_OVER`.
- `rolling_daily_first_non_negative`: rolling daily-first skill is still
  `-0.2212`.
- `positive_daily_first_days`: the gate requires `3` positive daily-first days;
  current evidence has `1`.
- `promotion_grade_market_days`: the gate requires `84` promotion-grade
  market-days; current evidence has `36`.
- `progress_claim_allowed`: progress audit remains `DIRECTIONAL` with
  `claim_allowed=False`, blocked by positive-day count, rolling daily-first
  skill, market-day count, live-forward SLO countability, missing independent
  baseline evidence, and mixed runtime identity.

No progress-audit claim was accepted here. Item 160 remains partial until a
served early-hour candidate clears the hourly gate and the daily-first trend
turns non-negative with enough countable evidence.

## 2026-06-22 proof packet mapping

Proof-packet blocker: `weather_only_model_proof_packet.gates.broad_claim_gate`.
Acceptance evidence for this item must clear the packet broad-claim field; new
daily-first diagnostics stay diagnostic-only until they change that blocker.

## 2026-06-24 accepted-candidate freshness design

Design decision before implementation: the remaining checklist item is not a
threshold change. Once an early-hour remediation candidate has acceptance-grade
candidate hourly evidence, candidate 10-minute weak-slot evidence, and a
served-distribution contract, the progress audit must be regenerated after
that accepted candidate evidence. Otherwise the positive daily-first gate could
close on a stale rolling trend.

Implemented this as a fail-closed gate in
`weather.reporting.serving_gates.early_hour_positive_daily_first_gate`:

- New gate: `progress_audit_refreshed_after_candidate`.
- The gate is deferred while candidate hourly, candidate 10-minute, or
  served-distribution contract evidence is still blocked.
- When those accepted-candidate dependencies all pass, the gate requires
  `progress_audit.generated_at_utc` to be at or after the newest dependency
  timestamp among served-distribution contract, candidate hourly, and candidate
  10-minute evidence.
- Missing or invalid timestamps block after candidate evidence is otherwise
  acceptance-grade.

Verification:

```powershell
python -m pytest tests\reporting\test_early_hour_positive_daily_first_gate.py -q
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md
```

Result: `3 passed`. The regenerated gate remains `BLOCK` with `6` blockers.
The new freshness gate currently passes in deferred mode:
`progress refresh check waits for accepted candidate evidence`.

Current countable blocker state:

- `candidate_hourly_early_gate`: the configured repaired candidate still
  blocks; early-hour Brier trails market by `+0.0048 > +0.0030`.
- `served_distribution_contract`: still blocks on
  `validation_evidence=row_export_surrogate`, replay `BLOCK`, and
  `cutover=DO_NOT_CUT_OVER`.
- `rolling_daily_first_non_negative`: still `-0.2212`.
- `positive_daily_first_days`: still `1` of required `3`.
- `promotion_grade_market_days`: still `36` of required `84`.
- `progress_claim_allowed`: still `DIRECTIONAL` / `claim_allowed=False`.

Candidate design evidence:

- `item147_time_split_alpha` has a candidate-hourly `PASS`
  (`delta_vs_market=-0.0008274097289249077`) and candidate replay daily-first
  market gap within tolerance (`+0.0024462054003935724`), but remains
  row-export surrogate evidence with no active registry contract and still has
  market blockers led by Seattle `+0.013566163725248485`.
- `item224_no_market_market_route_composite_v0_1` has the right diagnostic
  shape for this item: replay metric pass with
  `delta_vs_market=-0.0010784645660626632`, candidate-hourly `PASS`, and
  10-minute weak-slot `PASS`. It remains non-countable because it is
  `row_export_surrogate` evidence and depends on unregistered diagnostic
  source variants.
- `item224_no_market_market_route_composite_v0_2` is stronger
  diagnostically (`delta_vs_market=-0.003944202055417692`, candidate-hourly
  `PASS`, 10-minute weak-slot `PASS`), but it carries
  `same_corpus_hgb_missingness_v0_2` on `3801` rows, so it cannot be used as
  active-contract promotion evidence.
- The countable active-source route probe is active-contract evidence, but it
  fails the core skill requirement (`delta_vs_market=+0.006929749866981583`)
  and candidate-hourly gate (`+0.0069174394646268275` vs market).

Conclusion: Item 160 remains `PARTIAL`. The acceptance design is now enforced:
an accepted early-hour candidate cannot close the item without a fresh
post-candidate progress audit. The remaining unblock is still a real active
candidate/runtime that reproduces the diagnostic route-composite early-hour and
daily-first gains without row-export surrogate status, same-corpus markers, or
unregistered diagnostic source lineage, then regenerates progress audit and
proof packet evidence.

## 2026-06-24 upstream source countability enforcement

Extended `weather.reporting.candidate_lifecycle.candidate_variant_replay_summary` so
`validation_evidence=active_replay_contract` now verifies upstream source rows,
not just source variant registry labels. When candidate rows include
`route_source_variant_id` or `source_variant_id`, every referenced source
variant must be registered active/headline-countable, its configured source
export must exist and contain rows for that source id, and those source rows
must not carry non-countable markers such as
`counts_toward_weather_model_promotion=false`, `same_corpus`,
`row_export_surrogate`, or `diagnostic_row_export`.

This closes the obvious false-promotion path for Item 160: the v0.1 diagnostic
route composite cannot be made countable by adding registry rows around its
source variants.

Generated probe artifacts:

- `data/backtest/item160_forced_active_route_countability_probe.json`
- `data/backtest/item160_forced_active_route_countability_probe.md`
- `data/backtest/item160_forced_active_route_countability_probe_registry.json`
- `data/backtest/item160_forced_active_route_countability_probe_contract.json`

Probe result: `EXPECTED_REJECTED`. Forcing
`item224_no_market_market_route_composite_v0_1` through active-contract mode
now fails with:

`source variant item224_no_market_seattle_warm_support_repair_v0_1 export is non-countable: 18381 row(s) are marked counts_toward_weather_model_promotion=false; row export carries non-countable/same-corpus diagnostic markers: quote_risk_gate_reason=same_corpus_location_gate_candidate_not_quote_evidence`

Verification:

```powershell
python -m pytest tests\reporting\test_candidate_variant_replay_summary.py -q
python -m weather.reporting.candidate_lifecycle.candidate_variant_replay_summary --variant-rows data\backtest\item224_active_source_route_composite_rows.csv --source-candidate-json data\backtest\current_max_trust_candidate_replay.json --validation-evidence active_replay_contract --variant-registry data\backtest\item224_active_source_route_composite_registry.json --active-registry-contract-json data\backtest\item224_active_source_route_composite_contract.json --json-out data\backtest\item224_active_source_route_composite_replay_summary.json --report-out data\backtest\item224_active_source_route_composite_replay_summary_report.md
```

Result: `13 passed`; the legitimate active-source route still validates as
active-contract evidence, but remains performance-blocked. This confirms Item
160 needs a new real active source/model for the warm-support bottom-market
behavior rather than registry relabeling of the same-corpus repair.

## 2026-06-24 candidate viability audit

Added `weather.reporting.research.item160_candidate_viability_audit` with schema
`item160_candidate_viability_audit_v0.1` to make the design target explicit.
The audit reads each existing early-hour candidate's replay summary,
candidate-hourly gate, candidate 10-minute gate, and any countability probe,
then classifies the candidate as promotion-ready, countability-blocked,
performance-blocked, mixed-blocked, or evidence-missing.

Artifacts:

- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/item224_active_source_route_composite_ten_minute_performance.json`
- `data/backtest/item224_active_source_route_composite_ten_minute_performance_report.md`

Commands:

```powershell
python -m weather.reporting.ten_minute_model_performance --item147-rows data\backtest\item224_active_source_route_composite_rows.csv --json-out data\backtest\item224_active_source_route_composite_ten_minute_performance.json --report-out data\backtest\item224_active_source_route_composite_ten_minute_performance_report.md --slot-csv-out data\backtest\item224_active_source_route_composite_ten_minute_by_slot.csv --candidate-csv-out data\backtest\item224_active_source_route_composite_ten_minute_candidate_by_slot.csv
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
python -m pytest tests\reporting\test_item160_candidate_viability_audit.py -q
```

Result: `2 passed`; audit status `BLOCK`, with `0` promotion-ready candidates,
`3` metric-ready candidates, and `1` active-countable candidate.

Candidate split:

- Best metric candidate: `route_composite_v0_2`
  (`delta_vs_market=-0.003944202055417692`, candidate-hourly
  `delta_vs_market=-0.009296893939289626`, 10-minute weak-slot
  `delta_vs_market=-0.00991581161700588`), but it is
  `COUNTABILITY_BLOCKED` because replay evidence is `row_export_surrogate` and
  the rows include same-corpus missingness repair markers.
- Best countable candidate: `active_source_route_v0_1`, but it is
  `PERFORMANCE_BLOCKED`: active-contract replay trails market by
  `+0.006929749866981583`, candidate-hourly trails market by
  `+0.0069174394646268275`, and 10-minute weak-slot trails market by
  `+0.010190323504673741`.
- `item147_time_split_alpha` and `route_composite_v0_1` are also
  `COUNTABILITY_BLOCKED`; both have useful metric shape, but neither is active
  replay/export contract evidence. The forced active probe rejects v0.1 source
  lineage because of the non-countable warm-support repair.
- The configured predawn repair remains `MIXED_BLOCKED`: its 10-minute gate
  passes, but candidate-hourly, replay metrics, and active-contract evidence
  all block.

Design conclusion: the next implementation target is not another route recipe.
The route-composite family already demonstrates the desired early-hour shape,
but only with non-countable warm-support/missingness repairs. Completing Item
160 requires a real active source/model that supplies that bottom-market
behavior as countable active-contract evidence, then reruns the progress audit
and proof packet.

## 2026-06-24 active time-split candidate wired into Item 160 gates

Design before implementation: after the Item 224 active time-split logistic
export produced countable active-contract evidence, Item 160 needed to stop
treating candidate replay/hourly/ten-minute evidence as the whole acceptance
surface. The acceptance stack now has three explicit layers:

1. Model-ready candidate evidence: active replay contract, candidate-hourly
   early gate, and candidate 10-minute weak-slot gate.
2. Served-distribution evidence: active replay plus serving parity, exact-band,
   distance-0, bottom-location, lane separation, and the pooled-F
   broad-claim/readiness gate.
3. Positive daily-first evidence: fresh progress audit after accepted candidate
   evidence, non-negative rolling daily-first skill, minimum positive
   daily-first days, minimum promotion-grade market-days, and progress-claim
   allowance.

Implementation:

- `weather.reporting.research.item160_candidate_viability_audit` now includes
  `active_timesplit_logistic_v0_1` and optional served-distribution /
  positive-gate artifacts. A model-ready active candidate that still blocks on
  readiness or progress is classified at that deeper blocker rather than as
  promotion-ready.
- `weather.reporting.serving_gates.early_hour_positive_daily_first_gate` now defaults to the
  active time-split candidate evidence instead of the older predawn repair
  artifacts.
- Generated an Item-160-specific served-distribution contract from the active
  time-split candidate:
  `data/backtest/item160_active_timesplit_served_distribution_contract.json`.
  After Item 224 split model/location evidence from broad-claim readiness, the
  contract now passes the item-local model served-distribution layer while
  preserving production readiness as a separate blocker.

Artifacts:

- `data/backtest/item160_active_timesplit_served_distribution_contract.json`
- `data/backtest/item160_active_timesplit_served_distribution_contract_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`

Commands:

```powershell
python -m weather.reporting.serving_gates.served_distribution_calibration_contract --retrain-location-gate data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json --replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --out data\backtest\item160_active_timesplit_served_distribution_contract.json --report data\backtest\item160_active_timesplit_served_distribution_contract_report.md
python -m weather.reporting.progress_audit --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
```

Evidence:

- The active time-split candidate is the first model-ready countable candidate
  for this item. Strict replay is `active_replay_contract` with
  `delta_vs_market=-0.029284577196879075`; candidate hourly is `PASS` with
  early-hour `delta_vs_market=-0.039274406409350766`; candidate 10-minute is
  `PASS` with weak-slot `delta_vs_market=-0.04751316520588918`.
- `item160_active_timesplit_served_distribution_contract.json` is now `PASS`
  for model served-distribution evidence, with `model_acceptance_passed=true`,
  `model_served_distribution_status=PASS`, and `blocker_count=0`. It passes
  contract schema, serving parity, active replay contract, early-hour hourly,
  weak-slot 10-minute, exact-band/distance-0, bottom-location, lane
  separation, and the item-local model/location gate. It still records
  `production_readiness_status=BLOCK` and
  `broad_core_model_claim_allowed=false`.
- The canonical `early_hour_positive_daily_first_gate.json` is still `BLOCK`
  with `5` blockers. Candidate hourly, candidate 10-minute,
  served-distribution contract, and post-candidate progress freshness all pass.
  The remaining blockers are production readiness, rolling daily-first skill
  `-0.2290`, `1` of `3` required positive daily-first days, `24` of `84`
  required promotion-grade market-days, and progress audit
  `DIRECTIONAL` / `claim_allowed=False`.
- `item160_candidate_viability_audit.json` is `BLOCK` with `0`
  promotion-ready candidates, `1` model-ready candidate, `4` metric-ready
  candidates, and `2` active-countable candidates. The best model-ready
  candidate is `active_timesplit_logistic_v0_1`, classified as
  `READINESS_AND_PROGRESS_BLOCKED`.

Verification:

```powershell
python -m pytest tests\reporting\test_item160_candidate_viability_audit.py -q
python -m pytest tests\reporting\test_early_hour_positive_daily_first_gate.py -q
```

Result: `4 passed`; `5 passed`.

Conclusion: Item 160 is materially closer but still `PARTIAL`. The model-ready
candidate gap is closed, the model served-distribution layer is accepted, and
the progress audit freshness requirement has been satisfied after accepted
candidate evidence. Completing the roadmap item now requires production
readiness/freshness, non-negative rolling daily-first skill, at least `3`
positive daily-first days, at least `84` promotion-grade market-days, and
`claim_allowed=True`.

## 2026-06-24 served-distribution split and fresh progress audit

After Item 224 exposed `model_location_gate_status=PASS` separately from the
broad claim readiness blocker, Item 160 was updated to consume that split:

- `weather.reporting.serving_gates.served_distribution_calibration_contract` now accepts a
  model/location pass from the pooled-F retrain/location gate while retaining
  `production_readiness_status` and `broad_core_model_claim_allowed` as
  explicit fields.
- `weather.reporting.serving_gates.early_hour_positive_daily_first_gate` now treats the
  served-distribution model contract as accepted, adds a separate
  `production_readiness_gate`, and requires `progress_audit` freshness after
  that accepted candidate evidence.
- `weather.reporting.research.item160_candidate_viability_audit` now classifies the
  active time-split candidate as `READINESS_AND_PROGRESS_BLOCKED`.

Current blockers are no longer candidate evidence or served-distribution model
evidence. They are:

- `production_readiness_gate`: production readiness is `BLOCK`, so broad
  core-model claims remain blocked.
- `rolling_daily_first_non_negative`: rolling daily-first skill is `-0.2290`.
- `positive_daily_first_days`: `1` of required `3`.
- `promotion_grade_market_days`: `24` of required `84`.
- `progress_claim_allowed`: progress audit remains `DIRECTIONAL` with
  `claim_allowed=false`, blocked by positive-day count, rolling daily-first
  skill, promotion-grade market-days, live-forward SLO countability, missing
  independent baseline evidence, and mixed runtime identity (`528` identities,
  `379753` snapshot rows).

The item remains partial because these remaining blockers are the actual
positive daily-first acceptance criteria.

## 2026-06-24 production-readiness repair attempt

Refreshed the operational evidence behind the production-readiness blocker
instead of carrying the older fleet snapshot forward.

Commands:

```powershell
python -m weather.operations.loop_jsonl_repair repair data\snapshots\loop_console.log
python -m weather.operations.loop_jsonl_repair repair data\snapshots\observation_trigger_console.log
python -m weather.reporting.fleet.fleet_observability report --out data\backtest\fleet_observability.json --report data\backtest\fleet_observability_report.md
python -m weather.collection.snapshot_tracker --ensure
python -m weather.market.market_microstructure ensure
python -m weather.reporting.promotion_refresh --precomputed-candidate-json data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --precomputed-candidate-report data\backtest\item224_active_timesplit_logistic_repair_replay_summary_report.md --candidate-hourly-performance-report data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute-performance-report data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --report data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_report.md --promotion-allowlist-out data\backtest\item224_active_timesplit_logistic_repair_promotion_allowlist.json --incomplete-manifest data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh_incomplete.json --min-artifact-free-bytes 0 --disable-long-job-guard --skip-serving-gauntlet
python -m weather.reporting.location_analysis.pooled_f_retrain_location_gate --candidate-replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --out data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json --report data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md
python -m weather.reporting.serving_gates.served_distribution_calibration_contract --retrain-location-gate data\backtest\item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json --replay data\backtest\item224_active_timesplit_logistic_repair_replay_summary.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --out data\backtest\item160_active_timesplit_served_distribution_contract.json --report data\backtest\item160_active_timesplit_served_distribution_contract_report.md
python -m weather.reporting.progress_audit --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --served-distribution-contract data\backtest\item160_active_timesplit_served_distribution_contract.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item160_active_timesplit_positive_daily_first_gate.json --report data\backtest\item160_active_timesplit_positive_daily_first_gate_report.md
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
```

Evidence:

- `loop_jsonl_repair` cleared malformed console-log evidence. The refreshed
  `fleet_observability.json` now has `loop_integrity_status=OK` and
  `malformed_lines=0` in the current-code soak summary.
- The `snapshot_tracker --ensure` and `market_microstructure ensure` repair
  commands were refused by the recovery guard because restart budgets are far
  beyond their limits (`snapshot_capture=318>6`, `clob_capture=268>12`,
  `observation_trigger=36>12`). The latest restart-budget aging blocker clears
  at `2026-06-25T17:57:20.414245+00:00`.
- The refreshed fleet artifact is still `CRITICAL`:
  `live_forward_slo_status=BLOCK`, `current_code_soak_status=BLOCK`,
  `critical_alerts=27`, `runtime_identity_status=BLOCK`, and
  `mm_evidence_starvation_status=CRITICAL`.
- The refreshed promotion refresh still has model merit: `11` promote,
  `0` shadow, `0` blocked. The pooled-F retrain/location gate still records
  `model_location_gate_status=PASS`, but production readiness remains `BLOCK`
  with `production_readiness_blocker_count=2`.
- `item160_active_timesplit_served_distribution_contract.json` remains `PASS`
  for model served-distribution evidence. `item160_active_timesplit_positive_daily_first_gate.json`
  remains `BLOCK` with `5` blockers: `production_readiness_gate`,
  `rolling_daily_first_non_negative`, `positive_daily_first_days`,
  `promotion_grade_market_days`, and `progress_claim_allowed`.
- The refreshed progress audit is still `DIRECTIONAL` with
  `claim_allowed=false`: rolling daily-first skill is `-0.2290`, positive
  daily-first days are `1/3`, promotion-grade market-days are `24/84`, and
  broad trend claims are also blocked by live-forward SLO countability,
  missing independent baseline evidence, and mixed runtime identity.

Conclusion: the immediate malformed-log defect was repaired, but Item 160 is
still not complete. The remaining blockers are not candidate model skill
blockers; they require a clean current-code/live-forward operational window,
runtime identity reconciliation, independent baseline evidence, and enough
promotion-grade days for the broad daily-first trend to become provable.

## 2026-06-24 canonical active-registry integration

Promoted the accepted active time-split repair into the canonical active
variant evidence path without changing the fail-closed acceptance threshold.

Implementation:

- Added `item224_active_timesplit_logistic_repair_v0_1` to
  `config/model_variant_registry.json` as an active no-market variant with
  `live_runtime=active_timesplit_logistic_repair`.
- Extended `weather.reporting.candidate_lifecycle.active_variant_shadow_refresh` so daily refresh
  can execute that runtime through
  `weather.reporting.research.item224_active_timesplit_logistic_repair:build_payload`
  and write the active export plus registry/contract sidecars.
- Added test coverage for the new runtime export path.

Regenerated artifacts:

- `data/backtest/active_variant_shadow.json`
- `data/backtest/active_variant_shadow_long.csv`
- `data/backtest/active_variant_shadow_attribution.jsonl`
- `data/backtest/model_variant_evidence_growth.json`
- `data/backtest/model_variant_evidence_growth_report.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Commands:

```powershell
python -m weather.reporting.candidate_lifecycle.variant_registry --registry config\model_variant_registry.json --json-out data\backtest\model_variant_registry_audit_item160.json --report-out data\backtest\model_variant_registry_audit_item160.md
python -m weather.reporting.candidate_lifecycle.active_variant_shadow_refresh --variant-registry config\model_variant_registry.json --long-out data\backtest\active_variant_shadow_long.csv --attribution-sidecar-out data\backtest\active_variant_shadow_attribution.jsonl --json-out data\backtest\active_variant_shadow.json --report-out data\backtest\active_variant_shadow_report.md
python -m weather.reporting.candidate_lifecycle.variant_evidence_growth data\backtest\active_variant_shadow_long.csv --json-out data\backtest\model_variant_evidence_growth.json --report-out data\backtest\model_variant_evidence_growth_report.md
python -m weather.reporting.progress_audit --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --served-distribution-contract data\backtest\item160_active_timesplit_served_distribution_contract.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item160_active_timesplit_positive_daily_first_gate.json --report data\backtest\item160_active_timesplit_positive_daily_first_gate_report.md
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
python -m weather.reporting.weather_only_model_proof_packet --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Evidence:

- The canonical active-shadow refresh now reports `9` active variants, includes
  `item224_active_timesplit_logistic_repair_v0_1`, and has
  `missing_active_variant_count=0`. The payload is `WARN`, not `BLOCK`, because
  row-level route-source metadata varies within the routed active variant and
  market-informed quote/risk variants are present in the same comparison
  export.
- `model_variant_evidence_growth.json` now sees the active time-split candidate
  in the current evidence set. It remains `ALERT` because no accepted baseline
  prediction export is present; the independent-evidence SLA still blocks broad
  promotion with reason `missing baseline evidence`.
- The refreshed progress audit remains `DIRECTIONAL` with
  `claim_allowed=false`: `1` positive-skill comparable day, rolling
  daily-first skill `-0.2290`, `24/84` promotion-grade market-days,
  live-forward SLO not countable, missing independent baseline evidence, and
  mixed runtime identity (`528` identities, `379753` snapshot rows).
- The item-specific positive daily-first gate remains `BLOCK` with `5`
  blockers. Candidate hourly, candidate 10-minute, served-distribution
  contract, and progress freshness all pass; blockers are
  `production_readiness_gate`, `rolling_daily_first_non_negative`,
  `positive_daily_first_days`, `promotion_grade_market_days`, and
  `progress_claim_allowed`.
- The candidate viability audit remains `BLOCK` with `0` promotion-ready
  candidates. The active time-split repair is still the best model-ready
  candidate and is classified as `READINESS_AND_PROGRESS_BLOCKED`.
- The proof packet remains `BLOCK` with `10` blockers. The refreshed packet
  now shows `served_distribution_contract=PASS`, but
  `positive_daily_first_gate=BLOCK` and the broader weather-only proof stack
  still blocks broad claims.

Conclusion: the active candidate is now first-class canonical evidence, so
Item 160 is no longer blocked by missing active-registry coverage for the
candidate. The item still remains `PARTIAL` because broad progress/readiness
proof is not yet true.

## 2026-06-24 independent-evidence baseline pin

Pinned the current canonical active-shadow evidence as the baseline for future
independent evidence growth checks. This does not make a broad claim pass
today; it removes the missing-baseline failure mode so the next settled
active-shadow evidence can be judged by actual unique-observation and
market-day growth.

Implementation:

- `weather.operations.daily_refresh_steps.run_model_variant_evidence_growth_step`
  now prefers
  `data/backtest/model_variant_evidence_baseline_active_shadow_long.csv` when
  `--variant-evidence-baseline` is not supplied, and falls back to the legacy
  `item70_71_full_multi_variant_shadow_long.csv` path for older worktrees.
- The daily-refresh CLI help documents the new default baseline preference.
- Added focused test coverage for the pinned-baseline default.

Generated baseline artifacts:

- `data/backtest/model_variant_evidence_baseline_active_shadow_long.csv`
- `data/backtest/model_variant_evidence_baseline_active_shadow_manifest.json`

Regenerated:

- `data/backtest/model_variant_evidence_growth.json`
- `data/backtest/model_variant_evidence_growth_report.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Commands:

```powershell
python -m weather.reporting.candidate_lifecycle.variant_evidence_growth data\backtest\active_variant_shadow_long.csv --baseline-predictions data\backtest\model_variant_evidence_baseline_active_shadow_long.csv --json-out data\backtest\model_variant_evidence_growth.json --report-out data\backtest\model_variant_evidence_growth_report.md
python -m weather.reporting.progress_audit --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --served-distribution-contract data\backtest\item160_active_timesplit_served_distribution_contract.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item160_active_timesplit_positive_daily_first_gate.json --report data\backtest\item160_active_timesplit_positive_daily_first_gate_report.md
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
python -m weather.reporting.weather_only_model_proof_packet --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Evidence:

- `model_variant_evidence_growth.json` now has
  `baseline_paths=["data\\backtest\\model_variant_evidence_baseline_active_shadow_long.csv"]`.
  It remains `ALERT` because the current active-shadow evidence is identical to
  the freshly pinned baseline: unique-observation delta `0/1`, market-day
  delta `0/1`, and scored-row delta `0`.
- `progress_audit.json` remains `DIRECTIONAL` with `claim_allowed=false`.
  The independent-evidence failure is now
  `independent evidence growth below daily target: unique 0 / 1, market-days 0 / 1`
  instead of missing baseline evidence.
- `item160_active_timesplit_positive_daily_first_gate.json` remains `BLOCK`
  with `5` blockers: production readiness, rolling daily-first skill
  `-0.2290`, `1/3` positive daily-first days, `24/84` promotion-grade
  market-days, and progress claim allowance.

Conclusion: the independent-evidence baseline is now ready for the next
settled active-shadow growth check. Item 160 still cannot close until new
post-baseline independent observations arrive and the remaining production,
daily-first, promotion-grade, and runtime-identity blockers clear.

## 2026-06-24 production-readiness blocker detail propagation

Propagated the concrete upstream production-readiness blockers from the Item
224 pooled-F retrain/location gate through the Item 160 served-distribution
contract and positive daily-first gate. This keeps the accepted model evidence
separate from broad-claim readiness while making the remaining blocker
actionable.

Implementation:

- `weather.reporting.serving_gates.served_distribution_calibration_contract` now forwards
  `production_readiness_blockers` from the retrain/location gate.
- `weather.reporting.serving_gates.early_hour_positive_daily_first_gate` now reports the
  first concrete production-readiness blocker instead of the generic
  `production readiness is BLOCK` detail.
- `weather.reporting.progress_audit` now includes the first concrete
  live-forward SLO blocker in the progress-claim threshold failure.
- Added focused regression coverage for the propagated blocker detail.

Regenerated:

- `data/backtest/item160_active_timesplit_served_distribution_contract.json`
- `data/backtest/item160_active_timesplit_served_distribution_contract_report.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Evidence:

- The served-distribution contract remains model-accepted:
  `status=PASS`, `model_acceptance_passed=true`, and
  `model_served_distribution_status=PASS`.
- The positive daily-first gate remains `BLOCK` with `5` blockers. Candidate
  hourly, candidate 10-minute, served distribution, and post-candidate progress
  freshness pass.
- The first blocker is now explicit:
  `location promotion evidence is non-countable until freshness gates pass:
  fleet observability must be OK/PASS before location validation counts;
  live_forward=BLOCK, critical_alerts=27`.
- Progress audit remains `DIRECTIONAL` / `claim_allowed=false` with rolling
  daily-first skill `-0.2290`, `1/3` positive-skill comparable days, `24/84`
  promotion-grade market-days, independent evidence growth below daily target,
  and mixed runtime identity. The live-forward blocker is now explicit:
  `1 gap(s), max 138 min; afternoon window not fully covered (captured
  00:04-13:53); market=toronto; gate=snapshot_coverage_gap`.

Conclusion: Item 160 remains `PARTIAL`. The local model/candidate gates are
accepted, and the remaining production-readiness blocker is now concrete; the
roadmap item still requires production readiness, non-negative daily-first
skill, enough positive days, enough promotion-grade market-days, and a proven
progress claim before completion.

## 2026-06-24 same-run fleet/readiness ordering

Found and fixed a daily-refresh orchestration gap that could make Item 160
readiness evidence stale inside the same run. `promotion_refresh` and
`progress_audit` both consume `fleet_observability.json`, but the default daily
refresh order regenerated fleet observability after those gates. That meant the
positive daily-first gate could correctly fail closed while still explaining
the production-readiness blocker with a previous fleet artifact.

Implementation:

- Moved `fleet_observability` immediately after
  `settled_day_analysis_barrier` in `STEP_ORDER` and `DEFAULT_RUNNERS`.
- Locked the dependency in `tests.operations.test_daily_refresh`: settled-day
  analysis still precedes fleet, and fleet now precedes both
  `promotion_refresh` and `progress_audit`.
- Re-ran the quick Item 160 gates after the ordering change.

Regenerated:

- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Verification:

```powershell
python -m pytest tests\operations\test_daily_refresh.py -q
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --out data\backtest\early_hour_positive_daily_first_gate.json --report data\backtest\early_hour_positive_daily_first_gate_report.md
python -m weather.reporting.serving_gates.early_hour_positive_daily_first_gate --served-distribution-contract data\backtest\item160_active_timesplit_served_distribution_contract.json --candidate-hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --candidate-ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --out data\backtest\item160_active_timesplit_positive_daily_first_gate.json --report data\backtest\item160_active_timesplit_positive_daily_first_gate_report.md
python -m weather.reporting.research.item160_candidate_viability_audit --out data\backtest\item160_candidate_viability_audit.json --report data\backtest\item160_candidate_viability_audit_report.md
python -m weather.reporting.weather_only_model_proof_packet --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Result: daily-refresh tests pass (`60 passed`). The canonical and
item-specific positive daily-first gates still return `BLOCK` with `5`
blockers, and the proof packet remains `BLOCK` with `10` blockers. The
ordering fix does not relax any Item 160 acceptance threshold; it makes future
daily-refresh runs feed promotion/progress gates with same-run fleet
readiness evidence.

## 2026-06-24 proof-packet active-candidate alignment

Fixed the remaining proof-packet attribution mismatch for Item 160. The active
time-split candidate had already passed candidate hourly and candidate
10-minute gates, but `weather_only_model_proof_packet` only understood the
legacy current-serving hourly and 10-minute gate schemas. As a result, the
packet could still report old current-serving blockers even when the selected
promotion-refresh artifact explicitly carried accepted candidate mitigation.

Implementation:

- `weather.reporting.weather_only_model_proof_packet` now reads candidate
  hourly / 10-minute mitigation from `promotion_refresh.readiness`.
- When that mitigation is explicitly `applied=true` and the candidate gate is
  `PASS`, the packet marks `gates.hourly_gate` or `gates.ten_minute_gate` as
  `PASS` and records the superseded current-serving gate in `supersedes`.
- `gates.broad_claim_gate` now reports the actual failing dependency. If model
  promotion evidence passes but progress audit does not, the blocker detail is
  the progress-audit threshold failure instead of the promotion artifact's
  passing model-skill reason.
- Added regression coverage to keep accepted candidate mitigation separate
  from broad-claim progress acceptance.

Regenerated `data/backtest/weather_only_model_proof_packet.json` with the
active time-split candidate inputs:

```powershell
python -m weather.reporting.weather_only_model_proof_packet --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Evidence:

- Proof packet remains `BLOCK`, now with `5` blockers instead of `10`.
- Passing packet gates now include `hourly_gate`, `ten_minute_gate`,
  `exact_band_distance_zero_gate`, `bottom_location_gate`,
  `source_missingness_gate`, and `served_distribution_contract`.
- Remaining blockers are `promotion_refresh_readiness`,
  `live_forward_evidence_state`, `winner_rank_parity_gate`,
  `broad_claim_gate`, and `positive_daily_first_gate`.
- The broad-claim blocker now matches `progress_audit`: `1/3` positive-skill
  comparable days, rolling daily-first skill `-0.2290`, `24/84`
  promotion-grade market-days, live-forward SLO not countable, independent
  evidence growth below target, and mixed runtime identity.

Conclusion: Item 160 is closer because the canonical proof packet now agrees
with the accepted active candidate evidence. The item still remains `PARTIAL`
because production readiness, live-forward countability, winner-rank parity,
positive daily-first/progress evidence, independent evidence growth, and
runtime identity still block the broad weather-only claim.

## 2026-06-24 proof-packet active-contract identity correction

Fixed a second proof-packet attribution issue for the active time-split
candidate. The packet previously classified the evidence basis as
`active_artifact` whenever a candidate artifact path existed and the default
pooled-F artifact loaded successfully. For the active time-split repair, those
are different evidence objects: the proof artifact is
`artifacts\models\hgb\feature_model_hgb_f_pooled_v0_3.pkl`, while the selected
candidate is the active replay/export contract
`item224_active_timesplit_logistic_repair_v0_1`.

Implementation:

- `weather.reporting.weather_only_model_proof_packet` now requires the
  candidate artifact path to match the proof artifact path before reporting
  `active_artifact`.
- Active row-runtime candidates can instead pass
  `gates.active_artifact_identity` through explicit active replay/export
  contract evidence when the contract variant matches the candidate and
  `uses_market_features=false`.
- A mismatched candidate artifact without an active replay/export contract now
  blocks with `artifact_identity_mismatch` instead of accidentally inheriting
  proof from the default pooled-F artifact.
- Added regression coverage for both the active-contract path and the
  mismatched-artifact fail-closed path.

Regenerated:

- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Verification:

```powershell
python -m pytest tests\reporting\test_weather_only_model_proof_packet.py -q
python -m weather.reporting.weather_only_model_proof_packet --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Evidence:

- Proof-packet `summary.evidence_basis` is now
  `active_replay_contract`.
- `gates.active_artifact_identity` remains `PASS`, but its detail is now
  `active replay/export contract evidence is present for
  item224_active_timesplit_logistic_repair_v0_1`.
- The gate evidence records `candidate_artifact_matches=false` and
  `active_replay_contract_ok=true`, making the proof basis auditable.
- The packet still remains `BLOCK` with the same `5` real blockers:
  `promotion_refresh_readiness`, `live_forward_evidence_state`,
  `winner_rank_parity_gate`, `broad_claim_gate`, and
  `positive_daily_first_gate`.

Conclusion: this removes a stale-proof false positive from the canonical
packet. Item 160 still remains `PARTIAL`; the remaining completion work is the
same readiness/progress evidence required by the positive daily-first gate and
proof-packet broad-claim field.

## 2026-06-24 winner-rank parity refresh after active candidate wiring

Refreshed `winner_rank_parity.json` after confirming
`active_variant_shadow_long.csv` now includes the active time-split candidate.
This removes another stale-input risk from the canonical proof packet.

Regenerated:

- `data/backtest/winner_rank_parity.json`
- `data/backtest/winner_rank_parity.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Verification:

```powershell
python -m pytest tests\reporting\test_winner_rank_parity.py -q
python -m weather.reporting.winner_rank_parity --json-out data\backtest\winner_rank_parity.json --report-out data\backtest\winner_rank_parity.md
python -m weather.reporting.weather_only_model_proof_packet --promotion-refresh data\backtest\item224_active_timesplit_logistic_repair_promotion_refresh.json --hourly data\backtest\item224_active_timesplit_logistic_repair_hourly_gate.json --ten-minute data\backtest\item224_active_timesplit_logistic_repair_ten_minute.json --exact-distance data\backtest\item224_active_timesplit_logistic_repair_exact_band_distance_zero.json --bottom-location data\backtest\item224_active_timesplit_logistic_repair_bottom_location.json --served-distribution data\backtest\item160_active_timesplit_served_distribution_contract.json --positive-daily-first data\backtest\early_hour_positive_daily_first_gate.json --out data\backtest\weather_only_model_proof_packet.json --report data\backtest\weather_only_model_proof_packet_report.md
```

Evidence:

- `active_variant_shadow_long.csv` contains
  `item224_active_timesplit_logistic_repair_v0_1` with `33924` rows.
- The refreshed winner-rank parity artifact is current at
  `2026-06-25T00:04:13.594499+00:00` and still returns `BLOCK`.
- The active time-split candidate itself has top-hit parity on the scored
  subset: model top-hit rate `0.9938391699092088`, market top-hit rate
  `0.6880674448767834`, and top-hit gap `-0.30577172503242545`.
- The fleet-level parity gate still blocks on
  `conservative_bridge_policy_v0_1`, which trails market top-hit rate by
  `0.0990` against the `0.0200` tolerance. Served-current also trails market
  (`0.5468905649637114` vs `0.6595986907641952`).
- The regenerated proof packet keeps
  `summary.evidence_basis=active_replay_contract` and remains `BLOCK` with
  `5` blockers.

Conclusion: winner-rank parity is no longer stale relative to the active
time-split export. It remains a real broad proof-packet blocker, but not
because the active time-split candidate itself failed its scored top-rank
parity slice.

## 2026-06-24 runtime-identity reconciliation surfaced fail-closed

Added an explicit runtime-identity reconciliation artifact for the current
Item 160 evidence day. This does not allow mixed-runtime aggregation; it
replaces the previous missing reconciliation state with an auditable
fail-closed report.

Implementation:

- Added `weather.reporting.serving_gates.runtime_identity_reconciliation`.
- Registered schema `runtime_identity_reconciliation_v0.1`.
- The generated report summarizes mixed runtime segments, commit row counts,
  top runtime segments, and pass requirements.
- The report intentionally keeps `allow_mixed_runtime_aggregation=false`.
  A broad model claim still needs either a reviewed PASS reconciliation that
  explicitly allows aggregation or regenerated evidence under one runtime
  identity.
- Registered the dependent
  `item224_active_timesplit_logistic_repair_v0.1` schema literal so strict
  source-tree schema audit remains clean.

Regenerated:

- `data/backtest/runtime_identity_reconciliation.json`
- `data/backtest/runtime_identity_reconciliation.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Verification:

```powershell
python -m pytest tests\reporting\test_runtime_identity_reconciliation.py tests\reporting\test_runtime_identity_evidence.py tests\reporting\test_progress_audit.py tests\operations\test_schema_registry.py -q
python -m pytest tests\reporting\test_weather_only_model_proof_packet.py tests\reporting\test_early_hour_positive_daily_first_gate.py tests\reporting\test_item160_candidate_viability_audit.py -q
python -m weather.reporting.serving_gates.runtime_identity_reconciliation --target-date 2026-06-24 --out data\backtest\runtime_identity_reconciliation.json --report data\backtest\runtime_identity_reconciliation.md
python -m weather.reporting.progress_audit --json-out data\backtest\progress_audit.json --report-out data\backtest\progress_audit_report.md
```

Evidence:

- `runtime_identity_reconciliation.json` is `BLOCK` with
  `mixed_runtime_identity=true`, `runtime_identity_count=528`,
  `snapshot_row_count=379753`, and
  `allow_mixed_runtime_aggregation=false`.
- First reconciliation blocker:
  `528 runtime identities cover 379753 snapshot rows for 2026-06-24;
  automatic mixed-runtime aggregation is not reconciled`.
- `progress_audit.json` now consumes the artifact and reports
  `runtime_identity_evidence.reconciliation_status=BLOCK` and
  `reconciliation_allowed=false`.
- Positive daily-first gates still remain `BLOCK` with the same `5` blockers:
  production readiness, rolling daily-first skill `-0.2290`, `1/3` positive
  daily-first days, `24/84` promotion-grade market-days, and
  `progress_claim_allowed`.
- The proof packet remains `BLOCK` with `5` blockers and keeps
  `summary.evidence_basis=active_replay_contract`.

Conclusion: the runtime-identity blocker is now explicit and reviewable rather
than missing. Item 160 still remains `PARTIAL`; this change does not relax the
positive daily-first acceptance criteria.

## 2026-06-24 fleet/readiness refresh after reconciliation

Regenerated fleet observability after the runtime-identity reconciliation
artifact existed, then cascaded the dependent Item 160 promotion/progress gates.
This removes the stale fleet attribution that still reported runtime
reconciliation as missing.

Regenerated:

- `data/backtest/fleet_observability.json`
- `data/backtest/fleet_observability_report.md`
- `data/backtest/artifact_provenance_manifest.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh_report.md`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md`
- `data/backtest/item160_active_timesplit_served_distribution_contract.json`
- `data/backtest/item160_active_timesplit_served_distribution_contract_report.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Evidence:

- `fleet_observability.json` is current at
  `2026-06-25T00:24:34.021938+00:00`; it remains `CRITICAL`, but
  `runtime_identity_evidence.reconciliation_status=BLOCK` and
  `reconciliation_allowed=false`.
- The runtime alert now reports reconciliation `BLOCK` instead of missing.
- Candidate promotion evidence still promotes all `11` active time-split
  markets with `0` shadow and `0` blocked markets.
- The served-distribution contract remains model-accepted:
  `status=PASS`, `model_acceptance_passed=true`, and
  `model_served_distribution_status=PASS`.
- `progress_audit.json` remains `DIRECTIONAL` with `claim_allowed=false`:
  rolling daily-first skill `-0.2290`, `1/3` positive daily-first days,
  `24/84` promotion-grade market-days, live-forward SLO not countable,
  independent evidence growth below target, and mixed runtime identity.
- The positive daily-first gates remain `BLOCK` with `5` blockers and the
  proof packet remains `BLOCK` with `5` blockers, still using
  `summary.evidence_basis=active_replay_contract`.

Conclusion: the fleet/readiness surface is now internally consistent with the
runtime reconciliation artifact. Item 160 remains `PARTIAL`; the remaining
unblock still requires production readiness, more independent settled evidence,
non-negative rolling daily-first skill, enough positive/proven market-days, and
a resolved or explicitly approved runtime-identity reconciliation.

## 2026-06-24 daily-refresh reconciliation ordering fix

Added runtime-identity reconciliation to the daily refresh runner directly after
`settled_day_analysis_barrier` and before `fleet_observability`. This keeps the
same fail-closed reconciliation policy, but prevents a future same-run daily
refresh from rebuilding fleet/readiness evidence before the reconciliation
artifact exists.

Implementation:

- Added `run_runtime_identity_reconciliation_step` to
  `weather.operations.daily_refresh_steps`.
- Inserted `runtime_identity_reconciliation` in `STEP_ORDER` and
  `DEFAULT_RUNNERS` before `fleet_observability`, `promotion_refresh`, and
  `progress_audit`.
- Re-exported the runner through `weather.operations.daily_refresh`.
- Added operation tests for default runner ordering and settled-target-date
  wiring.

Regenerated:

- `data/backtest/runtime_identity_reconciliation.json`
- `data/backtest/runtime_identity_reconciliation.md`
- `data/backtest/fleet_observability.json`
- `data/backtest/fleet_observability_report.md`
- `data/backtest/artifact_provenance_manifest.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh.json`
- `data/backtest/item224_active_timesplit_logistic_repair_promotion_refresh_report.md`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate.json`
- `data/backtest/item224_active_timesplit_logistic_repair_pooled_f_retrain_location_gate_report.md`
- `data/backtest/item160_active_timesplit_served_distribution_contract.json`
- `data/backtest/item160_active_timesplit_served_distribution_contract_report.md`
- `data/backtest/progress_audit.json`
- `data/backtest/progress_audit_report.md`
- `data/backtest/early_hour_positive_daily_first_gate.json`
- `data/backtest/early_hour_positive_daily_first_gate_report.md`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate.json`
- `data/backtest/item160_active_timesplit_positive_daily_first_gate_report.md`
- `data/backtest/item160_candidate_viability_audit.json`
- `data/backtest/item160_candidate_viability_audit_report.md`
- `data/backtest/weather_only_model_proof_packet.json`
- `data/backtest/weather_only_model_proof_packet_report.md`

Evidence:

- `runtime_identity_reconciliation.json` is current at
  `2026-06-25T00:34:15.667709+00:00`, targets `2026-06-24`, and remains
  `BLOCK` with `mixed_runtime_identity=true`, `runtime_identity_count=528`,
  `snapshot_row_count=379753`, and
  `allow_mixed_runtime_aggregation=false`.
- `fleet_observability.json` is current at
  `2026-06-25T00:38:07.864276+00:00`; it remains `CRITICAL`, with
  `live_forward_slo=BLOCK`,
  `runtime_identity_evidence.reconciliation_status=BLOCK`, and
  `reconciliation_allowed=false`.
- The active time-split promotion refresh remains metric-ready for the lane:
  `11` promote markets, `0` shadow markets, and `0` blocked markets.
- The active pooled-F location gate remains `BLOCK` with `2` production
  readiness blockers, while `model_location_gate_status=PASS`.
- The served-distribution contract remains model-accepted:
  `status=PASS`, `acceptance_passed=true`,
  `model_acceptance_passed=true`, and
  `model_served_distribution_status=PASS`.
- `progress_audit.json` is current at
  `2026-06-25T00:39:19.003928+00:00`; the core trend claim remains
  `DIRECTIONAL` with `claim_allowed=false`, rolling daily-first skill
  `-0.22902493778068272`, `1` positive daily-first day, `24`
  promotion-grade market-days, live-forward SLO not countable, independent
  evidence growth below target, and mixed runtime identity.
- Both positive daily-first gates remain `BLOCK` with `5` blockers.
- `weather_only_model_proof_packet.json` is current at
  `2026-06-25T00:40:54.860350+00:00`; it remains `BLOCK` with `5` blockers and
  `summary.evidence_basis=active_replay_contract`.

Verification:

```powershell
python -m pytest tests\operations\test_daily_refresh.py -q
```

Conclusion: this closes the daily-refresh orchestration gap that could make
fleet/readiness evidence stale relative to runtime reconciliation. Item 160
still remains `PARTIAL`; the remaining blockers are substantive production
readiness, daily-first trend, promotion-grade evidence, independent evidence
growth, and runtime-identity reconciliation criteria.
