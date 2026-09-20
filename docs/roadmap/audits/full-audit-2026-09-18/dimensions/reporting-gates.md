# reporting-gates — reconstructed from the auditor's structured return (the auditor's own Write was denied)

```
## audit:reporting-gates — grade C — report_written=false
About 42k lines of gating have never promoted a candidate into production. `artifacts/releases/` does not exist, and all 18 registry variants are blocked, diagnostic, control or archived. The only end-to-end PASS (item-224 v0.1) was a label leak, found by an audit and not by the gates. Runtime artifacts changed in at least 25 commits titled "add" outside this machinery. In aggregate the stack fails closed, and the production-readiness parent gate is strict. The composite `promotion_readiness` result is report-only, because the allowlist that grants permission is written before it and ignores it. Several gates cannot realistically pass (identity override hard-coded False, WARN treated as BLOCK, a 0.0001 harm epsilon). Others pass with no input (fidelity canary, label-relative liveness, missing input files). I did not read live gate outputs under data/. The report file Write was refused, so the full report is in this response only.
STRENGTHS: src/weather/reporting/serving_gates/production_readiness_gate.py:1528-1722,2129-2265,2403-2411 - the parent gate fails closed: missing, symlinked, stale, future-dated, unknown-schema or non-PASS evidence each produce a distinct blocker; one verified release identity is required across inputs; the promotion decision is hash-linked to the pointer; the output grants no credential or order authority. || src/weather/reporting/promotion/readers.py:348-744 - every promotion input reader turns a missing file into an explicit MISSING gate rather than None, so most fail-open branches in promotion_readiness are unreachable in the default daily configuration. || src/weather/reporting/promotion/orchestration.py:153-257,562-613 - corpus identity pinning checks the file SHA before and after load and checks the semantic corpus hash; candidate replay and gauntlet must both prove they consumed the same corpus; gauntlet carry-forward never carries a failing verdict. || src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py:266-329 with config/model_variant_registry.json - post-leak hardening: surrogate evidence is preview-only by default, the active contract must match registry lifecycle, variant id, export path and lineage, and every variant carries an explicit promotion_block_reason. || src/weather/backtesting/settlement_io.py:373-425 with src/weather/reporting/promotion/promotion_corpus.py:246-337 - ledger labels are bound to the tape SHA-256 and raise on mismatch rather than falling back; corpus entries record admitted_by and label authority. I traced promotion_countable to JSON booleans, so it is not a string-truthiness bug.
NOT COVERED: promotion/gap_analysis.py; promotion/report.py beyond a grep || candidate_lifecycle: multi_variant_shadow, active_variant_shadow_refresh, price_free_model_learning/aggregation, model_market_disagreement_analysis/audit, cutoff_regime_weighting, repair_integration, variant_evidence_growth || serving_gates: registration_parameters, served_distribution_calibration_contract, serving_ordinal_smoothing_gate; about two thirds of production_readiness_gate.py (fleet, clean-day, capture-resource, unattended, storage-manifest, challenger, paper and capital validators; _verify_active_release; pointer attestation) || source_gates: cross_hub_readiness, forecast_radiation_gate, forecast_smoke_gate and slice_prep, global_model_guidance_gate, marine_contrast_gate, nbm_probabilistic_tmax_gate and settlement_scoring, official_guidance_sparse_coverage, settlement_source_audit, source_redundancy, weak_input_family_disposition; most of source_family_inventory.py || data_quality: data_auditor, data_layer_audit_collectors/remediation/report, data_retention_inventory, backtest_artifact_retention, feature_quality_quarantine, reanalysis_sidecar_coverage_audit; clob_coverage_audit beyond its function list || Live gate outputs under data/backtest were not read because the brief did not allow data/ access. Statements about current gate status come from project docs. || No tests were run. Whether serving loads artifacts/calibration/*.json was traced only as far as load_probability_calibration/resolve_artifact_path, not to the serving call site. || The report file could not be written. The Write tool refused it for subagents, and no retry was attempted elsewhere.


=== reporting-gates-1 [high] The gate stack has never gated a real change, and its one end-to-end PASS was a label leak (verified_in_code, known_open, conf high)
CLAIM: No candidate has been promoted through this machinery. artifacts/releases/ does not exist. All 18 variants in config/model_variant_registry.json are control, blocked, diagnostic_only or archived, with counts_toward_weather_model_promotion false. The only model+location PASS (item224 v0.1) used outcome-derived features and was caught by a 2026-07-11 audit, not by a gate. Tracked runtime artifacts changed in 25+ commits titled 'add' (2026-06-14 to 2026-07-11), none tied to a promotion decision.
EVIDENCE:
  - artifacts/ (ls today) - contains calibration, candidates, manifests, misc, models; there is no releases directory
  - docs/operations/ESTABLISHED_FINDINGS.md:1387 - current_release.json absent; artifacts/releases/ does not exist
  - config/model_variant_registry.json:9-251 - every non-archived variant has promotion_status blocked, diagnostic_only or control, and counts_toward_weather_model_promotion false
  - docs/roadmap/items/item-224-pooled-f-retrain-reexport-location-gate.md:2014-2037 - the v0.1 PASS used settlement_distance_bucket and feature_missingness_hash, and its evidence was invalidated
  - docs/operations/RETRACTED_AND_FALSE_LEADS.md:33-37 - item-224's win over the market was leakage
  - docs/roadmap/items/item-218-location-specific-f-family-promotion-allowlist.md:9-11,51-55 - the June promote list moved from Atlanta+Houston to austin+denver+houston within one item
  - git show --stat 3ebca26ed (2026-07-07, message 'add') - 38 files, +41496/-39491, including all 36 per-market calibration JSONs and the pooled HGB pointer
  - git log -- artifacts/models artifacts/calibration - 25+ commits, all titled 'add', the last being 9ffba967b on 2026-07-11
  - docs/operations/ESTABLISHED_FINDINGS.md:1909-1932 - 554,004 quote-intent rows, zero QUOTE, reason promotion_block
IMPACT: Large ongoing cost in code and agent attention with no demonstrated protective function. The one time evidence was good enough to pass, it was leaked. Served bytes changed outside the gates, which the project's own replay-irreproducibility finding also shows.
FIX: Define and enforce one path by which a runtime artifact may change: its SHA must be named in a reviewed decision file. Freeze new gate development until one candidate has honestly traversed the chain in a rehearsal.
VERDICT[evidence]: partially_confirmed -> medium (known_open)
  CORRECTED: No candidate has completed a production cutover through the gate stack. artifacts/releases/ does not exist. All 18 registry variants are control, blocked, diagnostic_only or archived. The one full promotion-refresh PASS (item-224 v0.1, 2026-06-25, PROMOTE_CANDIDATE for all 11 F markets) relied on a label-leaked feature; a 2026-07-11 audit found the leak, no gate did. The outer proof-packet cutover stayed BLOCK, so the leaked candidate never served. The gates do block: promotion_block causes zero maker quotes. Runtime artifacts changed in 26 "add" commits with no recorded promotion decision.
  NOTES: Every cited fact checked out. The overreach is "no protective function": item-48:1634-1639 shows the proof-packet cutover stayed BLOCK while the leaked candidate held PASS, though for unrelated reasons, and promotion_block stops every maker quote (ESTABLISHED_FINDINGS 8bb, called deliberate). Item-218's allowlist did emit PROMOTE_CANDIDATE actions. Corrections: 26 commits starting 06-13, not 25+ from 06-14; 3ebca26ed is 133 files, 38 only when path-restricted; the 5 archived variants have no promotion fields. Already in canon: ESTABLISHED_FINDINGS 4a-bis, RETRACTED, OPERATIONS_AGENT_ROLE:249. I did not verify "only PASS" or "none tied to a promotion decision" exhaustively.

=== reporting-gates-2 [high] promotion_readiness is report-only because the permission-granting allowlist is built before it and ignores it (verified_in_code, new, conf high)
CLAIM: run_promotion_refresh writes the allowlist (orchestration.py:703-722) before it computes readiness (:737-754). build_promotion_allowlist takes only per-market decisions and the candidate's cutover flag. No enforcing consumer reads readiness.status. mm_policy.load_promotion_states reads the allowlist rows and never checks the file's age. nightly_retrain.promotion_summary derives promote_ready from promote_markets and blocked_markets only. So the hourly gate, runtime identity, evidence freshness, early-hour and source-missingness blockers cannot block permission or a candidate release build.
EVIDENCE:
  - src/weather/reporting/promotion/orchestration.py:703-722 - decisions and allowlist are built and written
  - src/weather/reporting/promotion/orchestration.py:737-754 - promotion_readiness is computed afterwards and is not passed to the allowlist
  - src/weather/reporting/promotion/decisions.py:146-182,185-241 - candidate_permission_allowed is derived from action == PROMOTE_CANDIDATE and _candidate_cutover_allowed only
  - src/weather/reporting/promotion/decisions.py:1030-1388 - the roughly 15 composite blockers end only in readiness.status
  - src/weather/market/mm_policy.py:917-957 - reads promotion_allowlist.markets[*].effective_promotion_state with no readiness and no generated_at check
  - src/weather/market/mm_paper_reports.py:1034-1056 - base_permission comes from action/verdict only
  - src/weather/operations/nightly_retrain.py:1452-1480,1852-1868,2685 - promote_ready ignores readiness_status and then runs run_candidate_release_step
  - src/weather/calibration/pooled_candidate_replay_diagnostics.py:372-400 and promotion/cli.py:102-106 - a market PASS needs days>=2, trust>=25 and within 0.003 of market
  - src/weather/operations/daily_refresh_reporting_steps.py:292-334 - a short-circuited promotion leaves the old JSON on disk untouched
  - docs/operations/ESTABLISHED_FINDINGS.md:2720 - the doc attributes the promotion block to the hourly gate, but that gate does not reach the allowlist
IMPACT: Bounded today because trading is paper-only and every market is BLOCK. But the blockers the project believes protect promotion protect nothing. A lucky two-day window would grant paper quoting permission and trigger a candidate release build while readiness says OPEN.
FIX: Compute readiness first and fold its block-severity blockers into candidate_permission_allowed. Add an expiry to the allowlist. Make load_promotion_states treat a stale or missing file as BLOCK. Correct ESTABLISHED_FINDINGS section 9.
VERDICT[evidence]: partially_confirmed -> medium (new)
  CORRECTED: run_promotion_refresh builds and writes the allowlist (orchestration.py:703-722) before computing readiness (:737-754). build_promotion_allowlist uses only per-market action plus the candidate verdict and cutover decision, both derived from the market rows. Hourly, runtime-identity, freshness, early-hour and source-missingness blockers reach only readiness.blockers. The only enforcement is the opt-in promotion CLI --fail-on-block, which no automated caller passes. mm_policy never checks allowlist age, though a missing file is BLOCK. nightly_retrain's promote_ready ignores readiness and then builds an INACTIVE release; activation stays manual. Paper edge quoting also needs known-edge permission.
  NOTES: Traced orchestration, decisions, mm_policy decide_quote, mm_paper_reports and nightly_retrain through to build_candidate_release. The mechanics hold. The impact is overstated: a market PASS also needs delta_vs_current<0 and blocked_validation; promote_ready needs zero blocked markets; the release build leaves the pointer unchanged (MANUAL_POINTER_ONLY or NONE); edge quotes also need known_edge_allowed, heartbeat and source_fresh; a missing file is already BLOCK. cli.py:182-188 does enforce readiness, but it is opt-in and unused. A short-circuited daily refresh leaves the old JSON on disk, and no age check exists. No canonical doc records this.

=== reporting-gates-3 [medium] The runtime-identity gate cannot pass except through an unverified hand-written three-field JSON (verified_in_code, new, conf high)
CLAIM: build_runtime_identity_evidence BLOCKs when a corpus has more than one runtime key, and the key includes the git commit. The only escape needs allow_mixed_runtime_aggregation true and status PASS. The sole writer in src hard-codes allow False and writes BLOCK whenever the data is mixed, so no code path yields a pass. The passing test fixture is a bare three-field JSON with no reviewer, hash or expiry. Promotion passes target_date=None, which skips the date match. A manifest with zero readable rows yields PASS.
EVIDENCE:
  - src/weather/reporting/serving_gates/runtime_identity_evidence.py:64-82 - the runtime key includes runtime_git_commit
  - src/weather/reporting/serving_gates/runtime_identity_evidence.py:299-306 - the override needs allow flag true and status PASS, and the date check is skipped when target_date is falsy
  - src/weather/reporting/serving_gates/runtime_identity_evidence.py:326-327,340 - BLOCK when mixed and not reconciled; zero segments gives PASS
  - src/weather/reporting/serving_gates/runtime_identity_reconciliation.py:51,67 - status is BLOCK when mixed, and allow_mixed_runtime_aggregation is hard-coded False
  - grep for allow_mixed_runtime_aggregation in src - the only writer is runtime_identity_reconciliation.py:67
  - tests/reporting/test_runtime_identity_evidence.py:240-247 - the passing fixture is {target_date, status: PASS, allow_mixed_runtime_aggregation: true}
  - src/weather/reporting/promotion/orchestration.py:723-727 - called with no target_date
  - docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md:36 - 10 commits carry 54 identities
IMPACT: The gate is either permanently BLOCK or defeated by the weakest override in the stack, and that override would be valid forever. It adds a standing blocker that carries no information about the candidate.
FIX: Delete the gate, or replace the override with a computed equivalence check (same artifact hashes and loaded-code hash across segments). Require any manual override to hash the segments it covers and to expire.

=== reporting-gates-4 [medium] The production-readiness SHADOW stage requires evidence the owner has switched off (verified_in_code, new, conf high)
CLAIM: STAGE_SHADOW, the lowest stage, requires off_machine_backup and restore_drill evidence less than 30 days old, plus storage_headroom with growth_headroom_days >= 30. Stage results are cumulative, so any SHADOW blocker yields NOT_READY. The off-host mirror is paused and backups are deprioritized by owner decision, and the live host has about 4 days of headroom. The gate is NOT_READY by construction, independent of model quality, and no document records which decision yields.
EVIDENCE:
  - src/weather/reporting/serving_gates/production_readiness_gate.py:1442-1459 - off_machine_backup and restore_drill are STAGE_SHADOW specs with 30-day freshness
  - src/weather/reporting/serving_gates/production_readiness_gate.py:959-994 - the backup validator requires off_machine True, checksum PASS and bytes > 0
  - src/weather/reporting/serving_gates/production_readiness_gate.py:997-1018 - restore drill validator
  - src/weather/reporting/serving_gates/production_readiness_gate.py:1083-1090 - growth_headroom_days must be >= 30
  - src/weather/reporting/serving_gates/production_readiness_gate.py:2319-2349 - stage blockers are cumulative, and any SHADOW blocker gives NOT_READY
  - grep of docs/operations for off_machine_backup and storage_restore_drill - no document reconciles the gate with the paused mirror
IMPACT: Any work aimed at making this gate pass cannot succeed until a closed owner decision is reopened. Effort on release qualification is at risk of being spent against a structurally closed gate.
FIX: Record one line in STATE_OF_PLAY: either SHADOW is knowingly unreachable until the mirror resumes, or the backup and restore inputs move to the PAPER stage. This does not reopen the backup decision.

=== reporting-gates-5 [medium] The row-export candidate path reports gate fields that are constants or declarations, not computed (verified_in_code, known_open, conf high)
CLAIM: In candidate_variant_replay_summary, the path item-224 used, replay_gate global_ok/corpus_ok/fidelity_ok are all bool(rows). split_audit carries literal leak_count 0 and leaks []. uses_market_features is hard-coded False. Elsewhere uses_market_features is a CLI flag or a registry track string and is never derived from the artifact's feature list, yet promotion_readiness relies on it for the weather-only rule. build_family_decisions defaults a missing replay gate to global_ok True.
EVIDENCE:
  - src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py:730-749 - the replay_gate fields are bool(rows), same_identity_n is None, and the message reads PASS
  - src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py:457-461 - literal leak_count 0 and leaks []
  - src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py:623 - uses_market_features False is hard-coded
  - src/weather/reporting/candidate_lifecycle/active_variant_shadow_refresh.py:285,379 - uses_market_features is derived from the registry track string
  - src/weather/calibration/pooled_candidate_replay.py:3715,3728 - uses_market_features comes from a CLI flag
  - src/weather/reporting/promotion/decisions.py:42-43,118-130,1052-1061 - global_ok defaults True, cutover is allowed when the verdict is missing, and the market-informed blocker depends on the declared flag
  - docs/roadmap/model-systems-audit-2026-07-12.md:337-345 - the same always-ok leak audit is recorded for calibration/blocked_validation.py only
  - src/weather/reporting/candidate_lifecycle/candidate_variant_replay_summary.py:266-329 - post-leak hardening; the path is currently closed because the candidates have active_for_headline false
IMPACT: The fields a reviewer would use to ask whether a candidate was leak-checked, fidelity-proven and free of market features are constants. That is how a leaked candidate obtained a PASS. The path is closed by registry configuration today, not fixed.
FIX: Emit NOT_COMPUTED instead of 0 or True for anything that was not computed. Derive uses_market_features from the artifact feature manifest against a deny-list. Implement the recursive leakage audit that item-224's own checklist demands as a real gate input.

=== reporting-gates-6 [medium] Several gates cannot realistically pass: WARN collapses to BLOCK and thresholds sit far below measured noise (verified_in_code, new, conf medium)
CLAIM: data_layer_audit emits PASS/WARN/FAIL and six of its gates are warn-severity, but promotion's freshness gate accepts only PASS/OK/READY, so one WARN is a promotion BLOCK. The physical ratchet blocks a family if any of dozens of slices shows delta < -0.0001 Brier, about 30x below the project's own whole-sample MDE of 0.0031. Every skill tolerance is a literal 0.003. READY needs zero blockers, including any shadow market. The current-max gate passes its quarantine check only when quarantine rows exist.
EVIDENCE:
  - src/weather/reporting/data_quality/data_layer_audit.py:717-851,900-911 - warn-severity gates; the summary status is WARN or FAIL
  - src/weather/reporting/promotion/decisions.py:562-577,610-625 - _is_green_status accepts only PASS/OK/READY; data_layer status feeds _freshness_gate
  - src/weather/reporting/source_gates/physical_feature_family_ratchet.py:30-32,268-286,326-331 - HARM_EPSILON is -0.0001, and any harmful slice blocks the family
  - docs/operations/ESTABLISHED_FINDINGS.md:599-605 - the in-season MDE is 0.0030551
  - src/weather/reporting/promotion/cli.py:102-106 - tol, market-tol and current-tol are 0.003; min-days 2; min-trust 25
  - src/weather/reporting/promotion/decisions.py:1109-1120,1379 - per_market_shadow is a blocker, and READY needs zero blockers
  - src/weather/reporting/candidate_lifecycle/current_max_trust_retrain_gate.py:25,267-286 - the gate passes only if quarantine_row_count > 0; the input is hard-wired to the 2026-06-20 root-cause file
  - docs/operations/ESTABLISHED_FINDINGS.md:368-376 - the project already notes the promotion gate is stricter than the economics require
IMPACT: A BLOCK from this stack carries almost no information about the candidate. Blockers accumulate for structural reasons, which hides the one question that matters: does the candidate forecast better?
FIX: For each gate, estimate the probability that a truly neutral candidate passes. Retire or demote gates where that probability is near 0 or near 1. Replace the literal 0.003 with a date-clustered interval test, or park the skill gates.

=== reporting-gates-7 [medium] Scoring liveness uses the settlement ledger as its clock, so a settlement stall reads PASS (verified_in_code, new, conf high)
CLAIM: build_scoring_liveness compares last_scored_target_date to the latest settled label date and has no wall-clock term. When settlement stops, the latest label stops advancing, last_scored equals latest, and the status is PASS. With no labels the status is UNKNOWN, and apply_liveness_to_gate acts only on BLOCK, so UNKNOWN passes through. With 10 of the last 14 dates unsettled, this is exactly the condition under which the check reports healthy.
EVIDENCE:
  - src/weather/reporting/serving_gates/model_scoring_liveness.py:232-291 - a blocker is raised only if last_scored < the latest settled label; the status is PASS when there are no blockers and latest exists, otherwise UNKNOWN
  - src/weather/reporting/serving_gates/model_scoring_liveness.py:319-334 - apply_liveness_to_gate returns the gate unchanged unless the status is BLOCK
  - src/weather/reporting/promotion/decisions.py:1271-1275,1314-1320 - promotion applies liveness only when the status is BLOCK
  - src/weather/reporting/promotion/decisions.py:593-608 - the separate settled_day_freshness check exists but sits inside the unenforced readiness (see reporting-gates-2)
IMPACT: During the current settlement hole, the hourly and 10-minute performance artifacts can report scoring liveness as PASS while nothing is being settled or scored. This is the project's own 'a stopped counter looks satisfied' defect shape.
FIX: Add a wall-clock condition: BLOCK when the latest settled label is older than N days. Treat UNKNOWN as BLOCK.

=== reporting-gates-8 [medium] The gauntlet's replay-fidelity canary passes on an empty input, and no caller enables the strict mode (verified_in_code, new, conf high)
CLAIM: _fidelity_gate_status returns (True, 'WARN: no exact-identity snapshots') when same_identity_n is 0 unless require_exact_identity is set, and the report then prints 'Replay fidelity PASS'. The per-market fidelity check is skipped when same_n is 0. The flag is store_true, default off, in every CLI, and no script under scripts/ passes it. The project measured median replay divergence of 0.0154 among failures, above the gauntlet's 0.01 limit, and exact identity on 0.39% of rows.
EVIDENCE:
  - src/weather/reporting/promotion/promotion_gauntlet.py:143-155 - returns True with a WARN when there are no exact-identity snapshots
  - src/weather/reporting/promotion/promotion_gauntlet.py:180-183 - the market fidelity check is guarded by 'if same_n'
  - src/weather/reporting/promotion/promotion_gauntlet.py:431 - the report renders PASS when fidelity_ok
  - src/weather/reporting/promotion/cli.py:140 and src/weather/operations/daily_refresh_cli.py:637 - the flag defaults off
  - grep of scripts/ for require-exact-identity - no matches
  - src/weather/backtesting/replay_backtest.py:96 - FIDELITY_FAITHFUL_L1 = 0.01
  - docs/operations/REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md:14-28,71-72 - 31.84% matched, median L1 0.0154, exact identity on 111 of 28,254 rows
  - src/weather/reporting/promotion/decisions.py:1133-1138 - only a literal BLOCK gauntlet verdict blocks; PARTIAL_PASS or a skipped gauntlet does not
IMPACT: The one gate meant to prove that replay equals what was served reports PASS precisely when it cannot test that. The project's strongest negative finding about replay is invisible in the gauntlet verdict.
FIX: Make require_exact_identity the default. Turn 'no canary rows' into a BLOCK with its own reason code, and treat PARTIAL_PASS and a skipped gauntlet as non-green.

=== reporting-gates-9 [low] Vacuous passes on empty or uncomputed inputs, including a dead alert whose test uses a fabricated fixture shape (verified_in_code, new, conf high)
CLAIM: A missing inventory gives zero families and ratchet status PASS. source_family promotion_preflight passes with no rows, and ablation PRESENT with delta None becomes PROMOTION_CANDIDATE. Two early-hour sub-gates return PASS when skipped or when the status is missing, and their default inputs are the quarantined item-224 files with no lineage check. shadow_ab_monitor reads serving_gauntlet.blocking_markets, but the producer only emits decomposition.blocking_markets, so that alert can never fire. Its test passes on a fabricated shape.
EVIDENCE:
  - src/weather/reporting/source_gates/physical_feature_family_ratchet.py:51-55,351-353,417-421 - a read error gives {}, zero families and PASS
  - src/weather/reporting/source_gates/source_family_inventory.py:1302-1313,1576-1593 - delta None falls through to PROMOTION_CANDIDATE; an empty blocked list gives PASS
  - src/weather/reporting/serving_gates/early_hour_positive_daily_first_gate.py:20-25,136-142,242-249 - item224 default inputs; PASS when the check did not run; PASS when the status is missing
  - src/weather/reporting/candidate_lifecycle/shadow_ab_monitor.py:88-95 - reads serving.blocking_markets
  - src/weather/reporting/promotion/readers.py:312-329 - the serving summary has no blocking_markets key; it is nested under decomposition
  - src/weather/reporting/promotion/gap_analysis.py:620 - another consumer uses the correct decomposition path
  - tests/reporting/test_shadow_ab_monitor.py:23 - the fixture fabricates serving_gauntlet.blocking_markets
  - src/weather/reporting/source_gates/observed_floor_safety_monitor.py:231-233,346-352 - a day with every snapshot floorless gives PASS with zero floors examined
  - src/weather/reporting/data_quality/artifact_disk_budget.py:20-21 - the guard is a no-op when min_free_bytes is 0, which is the _write_json default
IMPACT: Each case is minor on its own, but the habit is systemic: a green status can mean 'checked nothing'. The shadow-monitor case shows that unit tests can pass on shapes production never produces.
FIX: Adopt one repo-wide rule and enforce it with a test: a gate that evaluated zero items, or whose input file was absent, returns a distinct non-green status. Build fixtures from the real producer output.

=== reporting-gates-10 [info] The observed-floor safety monitor is documented as fail-closed but runs alert-only (verified_in_code, known_accepted, conf high)
CLAIM: The module docstring says 'Fail-closed settlement monitor', but production runs it with enforcement_mode alert_only and hard_stop_pipeline False. The daily step passes fail_closed from a flag that defaults off, and no script under scripts/ sets it. The flip to fail-closed was explicitly deferred on 2026-08-04 as a 'temporary pre-lock' posture, and the lock date has passed by about six weeks.
EVIDENCE:
  - src/weather/reporting/source_gates/observed_floor_safety_monitor.py:1,278,372-373,480-487 - the docstring versus the alert_only default
  - src/weather/operations/daily_refresh_trading_steps.py:745-753 - fail_closed comes from fail_on_observed_floor_safety, which defaults False
  - src/weather/operations/daily_refresh_settled_day.py:69-79 - 'alert-only daily visibility until explicitly configured fail-closed'
  - grep of scripts/ for fail-on-observed-floor-safety - no matches
  - docs/operations/release-one-floor-flip-deferred-2026-08-04.md:4,57-69 - the flip was explicitly deferred
  - docs/operations/RELEASE_ONE_BUILD_RUNBOOK.md:106 - the flip is listed as a post-lock step
IMPACT: Low. This is an accepted posture. It monitors the project's single shipped forecast win, so an over-settlement floor would raise an alert and would not stop the chain.
FIX: Fix the docstring now. Either set a date for the flip or record that alert-only is the permanent posture.
```
