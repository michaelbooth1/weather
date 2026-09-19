# reporting-rest — reconstructed from the auditor's structured return (the auditor's own Write was denied)

```
## audit:reporting-rest — grade C — report_written=false
Scope: 48 files, 30,144 lines (daily, hourly, fleet, casebooks, location_analysis, market, roadmap). Engineering quality is uneven but often good: hourly/ten-minute scoring is genuinely memory-bounded with parity tests, the scoreboard and control room are fail-closed, fleet bounded mode flags its omissions loudly. The problems are structural. The host-load controls added 2026-08-21 are bypassed by two in-scope paths (the progress ledger and the fleet CLI). A daily chain step reports a PASS that cannot fail. The rollup-freshness gate became a permanent false BLOCK when the chain was split into stages, and the project mis-recorded the cause. With Stage B held disabled, about 7.5k lines of daily rollups do not run while the ledger re-stamps stale values as current. 4,931 lines (16%) have no production caller. The layer is disproportionate to the three decisions actually open. No data/ access: nothing is live-state; durations unmeasured. Report file write was denied.
STRENGTHS: Genuinely memory-bounded scoring: src/weather/reporting/hourly/hourly_model_aggregation.py folds one market-day at a time into mergeable sufficient statistics with an on-disk SQLite distinct index, and tests/reporting/test_hourly_model_performance.py:395-397 keeps the list-based implementation as a parity oracle. || src/weather/reporting/market/mm_countability_postmortem.py is proportionate reporting done right: reads only small preflight_remediation.json files, counts runs that cannot explain themselves instead of omitting them (:102-107), and labels its counterfactual a ceiling, not permission to bypass a gate (:128-133). || src/weather/reporting/market/market_beating_objective_scoreboard.py is fail-closed and anti-anchoring: market-informed evidence cannot count as weather proof (:356-363), mark-to-market cannot count (:387-394), headline PASS requires zero input blockers (:699). || Omissions are loud: src/weather/reporting/fleet/fleet_observability_payload.py:558-578 raises an explicit scheduled_bounded_omission warning naming every skipped evidence family and stating promotion must remain fail-closed. || src/weather/reporting/market/operator_control_room.py reads only small JSON, matches readiness to the exact target date (:47-69) and blocks on any host flag; every non-trivial in-scope module has a dedicated test file.
NOT COVERED: fleet_observability_gates.py and fleet_observability_loops.py internals (function inventory only) || daily_learning.py beyond _retrain_plan and the bootstrap; most of daily_learning_scorecard.py, daily_learning_render.py and daily_flow_analysis.py || trading_evidence.py internals beyond its I/O shape || market_residual_repair_program.py, market_benchmark_residual_edge.py, pooled_f_retrain_location_gate.py, winner_underpricing_casebook.py, extra_location_registry.py, location_similarity_pooling.py, roadmap_backlog.py beyond heads and consumer mapping || all render modules || any live artefact: no data/ access was authorised, so no step durations, tape sizes, artefact ages or scheduled-task states were observed || whether WeatherEveningEvidenceRefresh (Stage B) is currently enabled on this host


=== reporting-rest-1 [high] Progress ledger re-runs, unbudgeted in the orchestrator parent, the whole-corpus replays that were deliberately removed from the budgeted fleet child (verified_in_code, new, conf high)
CLAIM: Every non-dry-run, non-bounded daily_refresh run, including the scheduled 09:30 Stage A, calls write_daily_progress_ledger after the step loop with no skip flag. build_progress_row calls build_trading_evidence_summary and build_runtime_identity_evidence(snapshots_root, target_date). The latter globs every */snapshots_long.csv and fully parses each with list(csv.DictReader) before filtering rows by date. The scheduled contract skips exactly these two replays in the isolated fleet child as too heavy, yet they run in the parent with no memory ceiling, timeout or admission check.
EVIDENCE:
  - src/weather/operations/daily_refresh.py:1694-1700 - ledger written after the loop; only dry_run, stop_after or an attribute with no CLI flag skips it
  - src/weather/operations/daily_refresh.py:1710 - terminal status is written only after the ledger returns
  - src/weather/reporting/daily/daily_progress_ledger.py:299-309 - build_trading_evidence_summary and build_runtime_identity_evidence called unconditionally
  - src/weather/reporting/serving_gates/runtime_identity_evidence.py:182-193 - glob of every tape, full read, date filter applied per row afterwards
  - src/weather/reporting/serving_gates/runtime_identity_evidence.py:36-42 - read_csv_rows is list(csv.DictReader(handle))
  - scripts/ops/daily_refresh_contract.ps1:108-113 - same two replays skipped from the scheduled fleet tail on host-load grounds
  - docs/operations/HOST_LOAD_POLICY.md:146-152 - policy says these retained-corpus scans cannot fit the morning tail
IMPACT: An unbounded, linearly growing full-corpus read runs daily outside every containment control the project built, before the terminal status write, inside a chain with a hard 11:55 teardown that is already failing to settle. Duration was not measured.
FIX: Have the ledger consume trading_evidence.json and runtime_identity_reconciliation.json already written by Stage A instead of recomputing; or honour the skip_fleet_* flags. At minimum skip folders whose slug date differs from target_date before opening the tape.
VERDICT[evidence]: partially_confirmed -> medium (new)
  CORRECTED: Every non-dry-run, non-bounded daily_refresh run calls write_daily_progress_ledger in the orchestrator parent, before the terminal status write. The skip_daily_progress_ledger attribute it checks has no CLI flag. build_progress_row unconditionally calls build_trading_evidence_summary (all-run taker enumeration) and build_runtime_identity_evidence, which globs every */snapshots_long.csv and list()-parses each tape before filtering by date. These are the same replays the scheduled contract skips in the budgeted fleet child. Cost is I/O and time: tapes load one at a time, so peak memory is one tape, not the corpus. Duration is unmeasured.
  NOTES: All seven citations match the code. I traced daily_refresh.py:1694-1710 to write_daily_progress_ledger, build_progress_row and snapshot_runtime_segments. The ledger call has no stage check. Mitigations: exceptions are caught at 1701; tapes load one at a time, so memory grows with the largest tape only. A slow scan or hang still delays the terminal status write. The contract comment and HOST_LOAD_POLICY acknowledge the scan only for the fleet child. No doc in docs/ records the ledger path. Severity lowered because duration, corpus size and any memory ceiling on the parent process were not checked.

=== reporting-rest-2 [high] The fleet-observability CLI advertised as the verification/remediation command has no bounded mode (verified_in_code, new, conf high)
CLAIM: cmd_report passes only include_audits to build_observability_payload; include_trust_replay, include_runtime_identity_replay and include_trading_replay default True and have no CLI flags. SNAPSHOT_FLEET_VERIFY_COMMAND omits --skip-audits and is embedded as verification_command in seven collection-health payloads, so following it runs the 2000-2025 historical audit, score_all_markets over every settled tape, the every-tape runtime-identity scan and the all-run trading replay, unisolated. The nightly-health remediation string omits the required report subcommand and is an argparse error.
EVIDENCE:
  - src/weather/reporting/fleet/fleet_observability_cli.py:8-18 - only include_audits is passed
  - src/weather/reporting/fleet/fleet_observability_cli.py:30-46 - parser has --skip-audits only; subparser required=True; years default 2000-2025
  - src/weather/reporting/fleet/fleet_observability_payload.py:465-468 - the three replay switches default to True
  - src/weather/reporting/fleet/fleet_observability_payload.py:220,277-281 - score_all_markets and trading replays executed when included
  - src/weather/collection/collection_health.py:60-64 - SNAPSHOT_FLEET_VERIFY_COMMAND without --skip-audits
  - src/weather/collection/collection_health.py:248 - one of seven verification_command embeddings (also 301,362,1435,1476,1554,1682)
  - src/weather/operations/nightly_health_checks.py:133 - remediation command lacks the report subcommand
IMPACT: During a capture incident the system hands an operator or agent a command that launches four workloads the project judged too heavy for a 3 GiB isolated child, in whatever window the incident occurs, on a host where diagnostics have already broken production.
FIX: Default the CLI to bounded mode and require an explicit full-corpus opt-in flag; correct SNAPSHOT_FLEET_VERIFY_COMMAND and the nightly-health remediation string.
VERDICT[evidence]: partially_confirmed -> medium (new)
  CORRECTED: The fleet_observability CLI's cmd_report passes only include_audits. The three replay switches default to True and have no CLI flags, so the CLI cannot reach the bounded mode that the scheduled daily-refresh path uses. SNAPSHOT_FLEET_VERIFY_COMMAND omits --skip-audits and is embedded as verification_command seven times in collection_health.py, and is also aliased as BROAD_SLO_VERIFY_COMMAND. Following it runs the full 2000-2025 audit and all three full-corpus replays. The remediation string at nightly_health_checks.py:133 omits the required 'report' subcommand, as does RESEARCH_AUDIT_HARNESS.md:22. The risk is latent: no incident was found.
  NOTES: Every cited line was opened and matches. The scheduled path is bounded: daily_refresh_reporting_steps.py:1457-1472 wires four skip flags that daily_refresh_contract.ps1:100-113 sets, with comments that these scans cannot fit the morning tail. HOST_LOAD_POLICY.md:150-156 confines full audits to admitted 00:30-09:00 work. The auditor's "too heavy for a 3 GiB isolated child" is imprecise: the recorded rationale is the time budget, and the 3 GiB cap at line 167 concerns MM scoring. The heaviness is already documented; the missing CLI flags are new. Tests pin only the "fleet_observability report" prefix. The command has to be followed manually, hence medium.

=== reporting-rest-3 [medium] june23_location_bias_repair 'repair replay' cannot fail, runs daily on a frozen date, and was accepted as roadmap completion evidence (verified_in_code, new, conf high)
CLAIM: _case_copy_with_repair re-scores nothing: for six hard-coded markets it sets model Brier and log-loss 65% of the way to the market's whenever the model trailed, and flips model_top_hit True whenever the market's top band hit. Protected markets are never modified, so _repair_replay status is PASS by construction whenever any repair market trailed. The only test asserts that PASS. The step is 40th of 44 in the daily chain with target date fixed at 2026-06-23 and feeds the experiment queue.
EVIDENCE:
  - src/weather/reporting/location_analysis/june23_location_bias_repair.py:221-243 - the algebraic 'repair' toward market values
  - src/weather/reporting/location_analysis/june23_location_bias_repair.py:292-304 - PASS iff improvements exist and no protected regression, both guaranteed
  - src/weather/reporting/location_analysis/june23_location_bias_repair.py:27 - DEFAULT_TARGET_DATE 2026-06-23
  - src/weather/reporting/scorecards/winner_rank_parity.py:526 - model_brier derives from model_brier_sum, so the edit propagates
  - tests/reporting/test_june23_location_bias_repair.py:132-135 - asserts PASS and zero protected regressions
  - docs/roadmap/items/item-301-june-23-location-bias-and-winner-rank-repair-packet.md:48-50 - acceptance boxes ticked on this replay
  - src/weather/operations/daily_refresh_steps.py:142 - registered in DEFAULT_RUNNERS
  - src/weather/reporting/daily/daily_learning_scorecard.py:514-522,584-591 - manifests enter the queue but legacy entries are not eligible
IMPACT: A screen that cannot fail, built by consuming the benchmark, emits repair_replay_status PASS into chain status 87 days after the date it analyses. Queue eligibility rules limit direct harm; the epistemic harm is a completed roadmap item resting on a tautology.
FIX: Remove the step from DEFAULT_RUNNERS, delete or rename _repair_replay, keep the descriptive packet only if wanted, and annotate item 301 that no repair variant was ever replayed.

=== reporting-rest-4 [medium] rollup_freshness is stage-unaware, forcing a structural BLOCK and 'critical' on clean Stage A runs; the project's triage misattributes it to the model gap (verified_in_code, new, conf medium)
CLAIM: build_rollup_freshness marks daily_learning STALE if any required granular artefact is newer, and a BLOCK upgrades an ok chain to critical. Stage A rewrites hourly_model_performance.json and ten_minute_model_performance.json; daily_learning.json is written only by a Stage B step. The check takes no stage argument and only bounded stop_after runs are exempt, so any Stage A run that refreshes either hourly artefact must end BLOCK/critical, whether or not Stage B is enabled.
EVIDENCE:
  - src/weather/reporting/daily/daily_rollup_freshness.py:15-26,177-201 - required vs rollup sets; STALE when any required artefact is newer; BLOCK on any STALE or MISSING
  - src/weather/operations/daily_refresh_status.py:18-24 - called with no stage awareness
  - src/weather/operations/daily_refresh.py:1679-1693 - only daily_progress_latest is overridden; only stop_after is exempt; BLOCK sets status critical
  - src/weather/operations/daily_refresh_registry.py:33-34,58,213-214 - hourly steps in Stage A, daily_learning in Stage B
  - tests/operations/test_daily_refresh.py:2306-2332 - pins critical for a chain with no daily_learning runner
  - docs/operations/release-one-chain-block-triage-2026-08-04.md:79-82 - records latest_required_artifact = ten_minute_model_performance and files it as downstream of the model gap
  - scripts/ops/status.ps1:1526-1532 - rollup_freshness listed among payload BLOCKs on an all-steps-ok run
IMPACT: A terminal chain status that is always critical cannot separate a good morning from a bad one, and the recorded explanation points investigators at the model instead of the plumbing. Not observed live.
FIX: Evaluate freshness only for rollups the running stage owns, or compare each rollup with the granular artefacts from its own stage's last run; correct the 08-04 triage note.

=== reporting-rest-5 [medium] With Stage B held disabled the daily rollup stack does not run, and the progress ledger re-stamps stale Stage-B values as today's (verified_in_code, new, conf medium)
CLAIM: The evidence task is registered disabled unless -EnableEvidenceTask is passed, so daily_learning, the scoreboard, daily_flow_analysis, disagreement_casebook, progress_audit, promotion_refresh and proper-scoring do not refresh by default. The progress ledger still runs at the end of Stage A, reads nine artefacts of which seven are Stage-B-only, copies candidate deltas, calibration ECE, trend and scoreboard fields into a row stamped with today's run_date, and records or checks no source timestamp. daily_flow_analysis then does day-over-day anomaly detection on those columns.
EVIDENCE:
  - scripts/ops/register_daily_refresh.ps1:4-6,191-214 - evidence task stays disabled without the explicit switch and the script throws otherwise
  - scripts/ops/status.ps1:3848-3850,4119-4121 - warning text: operator-held DISABLED, evidence refresh unavailable
  - docs/operations/HOST_LOAD_POLICY.md:128 - 'disabled-by-default Stage B'
  - src/weather/operations/daily_refresh_registry.py:41-60 - Stage B step membership
  - src/weather/reporting/daily/daily_progress_ledger.py:284-298 - run_date is today; nine artefacts read from disk
  - src/weather/reporting/daily/daily_progress_ledger.py:346-440 - values copied with no source timestamp
  - src/weather/reporting/daily/daily_flow_analysis.py:69-81 - LEDGER_ANOMALY_METRICS on the same columns
IMPACT: About 7.5k lines of rollup code produce nothing on a default-registered host while the only longitudinal record keeps adding rows that look current. A frozen input reads as 'no anomaly': the project's own stopped-counter defect shape.
FIX: Store each input's generated_at_utc in the ledger row and null any value older than the run's settlement target; decide explicitly whether the Stage B rollups are retired or re-enabled.

=== reporting-rest-6 [medium] Market-beating scoreboard requires two inputs no automated step produces and never checks input age (verified_in_code, known_open, conf high)
CLAIM: REQUIRED_INPUTS includes weather_only_model_proof_packet and market_benchmark_residual_edge. Neither name appears anywhere under src/weather/operations or scripts, and neither is in DEFAULT_RUNNERS. _input_blockers checks only existence and schema_version; the module contains no age or staleness check. In automated operation the headline can therefore only be BLOCK missing_required_input, or a verdict computed from manually produced artefacts of arbitrary age.
EVIDENCE:
  - src/weather/reporting/market/market_beating_objective_scoreboard.py:27-33 - REQUIRED_INPUTS
  - src/weather/reporting/market/market_beating_objective_scoreboard.py:110-121 - blockers only on exists/schema_version
  - src/weather/reporting/market/market_beating_objective_scoreboard.py:646-699 - inputs read from fixed backtest paths; headline PASS needs zero input blockers
  - src/weather/operations/daily_refresh_steps.py:102-147 - no producer step for either input
  - docs/roadmap/items/item-264-market-benchmark-and-residual-edge-research-lane.md:74 - producer is a manual CLI, cited with a module path that no longer exists
IMPACT: The artefact the project treats as objective #2's scoreboard reports plumbing state rather than a measurement, so it cannot inform the question it is named for.
FIX: Either schedule the two producers under a budget, or drop them from REQUIRED_INPUTS and report them as not-measured; add a maximum input age to _input_blockers.

=== reporting-rest-7 [medium] Stage A re-scores the whole settled corpus from raw tapes in separate hourly and ten-minute passes with no cache or increment (verified_in_code, new, conf medium)
CLAIM: build_hourly_performance and ten_minute build_payload each call score_folder for every labelled market-day: pd.read_csv of snapshots_long.csv, a second read_csv plus iterrows for features_long.csv, backtest_tape via df.iterrows, then frame.iloc per scored row. Settled days never change, yet nothing is memoised. price_free_model_learning adds a third pass and the ledger a fourth full read. The two steps are budgeted 60 minutes each inside a 145-minute window. About 320 lines of accumulator classes are duplicated near-verbatim between the two modules.
EVIDENCE:
  - src/weather/reporting/hourly/hourly_model_context.py:205-226 - full labelled-corpus loop
  - src/weather/reporting/hourly/ten_minute_model_performance.py:1342-1384 - second independent full loop
  - src/weather/reporting/hourly/hourly_model_scoring.py:318-348 - score_folder read_csv and per-row iloc
  - src/weather/backtesting/tape_scoring.py:149-165,186-190 - second read_csv with iterrows; backtest_tape iterrows
  - src/weather/reporting/candidate_lifecycle/price_free_model_learning.py:387,833 - third score_folder pass
  - src/weather/operations/daily_refresh_resources.py:85-86 - 60 min and 3072 MiB each
  - src/weather/reporting/hourly/hourly_model_aggregation.py:85-364 - classes duplicated at ten_minute_model_performance.py:494-812
IMPACT: CPU, disk I/O and wall-clock grow by 12 tapes a day in the window where the settlement chain is currently failing, to regenerate two gates whose verdict has not changed since at least 2026-08-04. Memory is bounded; durations were not measured.
FIX: Run one scoring pass that writes per-market-day sufficient statistics keyed by tape size and mtime; fold hourly, ten-minute and price-free summaries from that store and share one accumulator implementation.

=== reporting-rest-8 [medium] disagreement_casebook walks every snapshot folder with full materialisation, un-isolated (latent while Stage B is held) (verified_in_code, new, conf high)
CLAIM: discover_folders returns every directory under the snapshots root that has snapshots_long.csv, including today's live folders; the CLI has no date window. For each folder the step fully loads snapshots_long.csv and, by default, list(csv.DictReader) of the whole order_books_summary.csv, plus replay inputs and for case folders components, price history and websocket events. All cases for all history are held and serialised. Stage B steps have no resource policy and run in the orchestrator process.
EVIDENCE:
  - src/weather/reporting/casebooks/disagreement_casebook.py:1331-1340 - every folder, no date bound
  - src/weather/reporting/casebooks/disagreement_casebook.py:1852-1871 - parser offers no date window
  - src/weather/reporting/casebooks/disagreement_casebook.py:418-431 - whole order_books_summary.csv materialised
  - src/weather/reporting/casebooks/disagreement_casebook.py:1362-1399 - all_cases accumulated and emitted
  - src/weather/operations/daily_refresh_reporting_steps.py:1402-1421 - step passes defaults with include_clob on
  - src/weather/operations/daily_refresh.py:1374-1386 - only STAGE_A_ISOLATED_STEPS get a child process
  - src/weather/operations/daily_refresh_resources.py:52-104 - no Stage B policy exists
IMPACT: Re-enabling Stage B puts an unbounded, growing, whole-corpus read that also opens live capture files into a long-lived process with no memory ceiling on a 16 GB host.
FIX: Add start/end date arguments defaulting to a recent settled window, exclude unsettled folders, stream the book summary, and give Stage B steps the same isolation policy as Stage A before it is re-enabled.

=== reporting-rest-9 [low] Reporting layer is disproportionate to the decisions it informs; 16% of it has no production caller (verified_in_code, new, conf high)
CLAIM: Eight in-scope modules totalling 4,931 lines are referenced only by tests, schema-registry strings and historical docs. Open decisions (capture health, countable maker days, operator go/no-go) are served by bounded fleet mode and two modules under 410 lines each, while daily/ is a four-deep rollup-of-rollups with a constant verdict. The scope re-defines utc_iso 18 times, write_json 7 times and duplicates Brier/log-loss/ECE. The hourly and fleet 'decompositions' are chained star-imports with pyflakes checks disabled. 93 doc references use module paths that no longer import.
EVIDENCE:
  - src/weather/reporting/casebooks/winner_underpricing_casebook.py:1 - 599 lines, no importer or script
  - src/weather/reporting/casebooks/severe_tail_ex_ante.py:1 - 1,035 lines, mission deliverable with no caller
  - src/weather/reporting/location_analysis/no_market_location_transfer.py:1 - 1,077 lines, CLI-only research harness
  - src/weather/reporting/market/mm_input_age_postmortem.py:1 - 256 lines, one-off, not in the schema registry
  - tests/operations/test_import_architecture.py:248-259 - ratchet lists that keep the unused modules alive
  - src/weather/reporting/hourly/candidate_hourly_performance.py:82-110 - independent copy of brier, binary_logloss and ECE
  - src/weather/reporting/hourly/hourly_model_gate.py:3-6 - star-import slice that resolves globals from the previous slice
  - docs/roadmap/items/item-264-market-benchmark-and-residual-edge-research-lane.md:74 - stale flat module path
IMPACT: Every unused module still costs a test file, a registry entry and review attention on a one-operator project whose full test run already stresses the production host, and duplicated metric code invites silent drift in gate inputs.
FIX: Move the eight caller-less modules and their tests to an archive branch or tools/research, collapse the helper re-definitions onto weather.io and weather.scoring.metrics, and replace star-import slices with explicit imports.

=== reporting-rest-10 [low] Progress ledger 'append' is a non-atomic truncate-and-rewrite that silently drops unparseable history (verified_in_code, new, conf high)
CLAIM: append_jsonl and append_csv read the entire ledger, reopen the same path with mode w, and rewrite every row in place; there is no temp file or os.replace, although the same module writes daily_progress_latest.json atomically. read_jsonl skips any line that fails json.loads without counting or alerting, so a torn line is permanently discarded on the next rewrite. Ledger rows are point-in-time copies of artefact state and cannot be regenerated.
EVIDENCE:
  - src/weather/reporting/daily/daily_progress_ledger.py:581-594 - append_jsonl reads all rows then open('w') rewrites the file
  - src/weather/reporting/daily/daily_progress_ledger.py:597-618 - append_csv does the same
  - src/weather/reporting/daily/daily_progress_ledger.py:621-635 - JSONDecodeError lines silently skipped
  - src/weather/reporting/daily/daily_progress_ledger.py:853 - the atomic writer is already used for the latest-row file
  - src/weather/operations/daily_refresh.py:1694-1700 - invoked at the end of every scheduled run, near the hard teardown deadline
IMPACT: A kill, crash or power loss between truncate and flush erases the whole day-over-day history. The window is small but the loss is total, on a host that ranks power loss as its top uncontrolled risk and has already lost a CSV to a truncating recipe.
FIX: Write to a temp file and os.replace for both ledgers, or use true append with a same-date tombstone; count and surface skipped lines instead of dropping them.
```
