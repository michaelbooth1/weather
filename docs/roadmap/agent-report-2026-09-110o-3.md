# 110o part 3 — retire taker and paper-maker code (owner decision 3, D2/D7) [DONE, ROLL-SENSITIVE]

**Verdict: DONE, roll-sensitive, schema change NOT additive-only. The retired taker and paper-maker runtime (35 `src`
modules, 32,685 lines), their four daily-refresh steps and flags, 46 schema-registry rows and 5 literal exclusions,
their ownership-map/size-audit entries, the five bot launcher/registrar scripts and 13 test files (13,288 lines) are
deleted. By owner decision (2026-09-29) the paper-run tool `market_making_run` and the eight modules it imports are
retained, with their tests, schema rows and docs, so the International live-pilot Stage 0/1 paper run can still be
produced; a new fixture test runs that exact prerequisite command. `trading_evidence` keeps producing
`trading_evidence.json` from the retained `mm_runs`/`taker_runs`/`mm_paper_report.json` evidence through one
read-only module.**

Branch `codex/110o-retire-taker-paper-maker-20260929` (base: `origin/codex/paper-maker-decouple-20260926`, PR #104);
handoff [workstation-handoff-2026-09-110o](workstation-handoff-2026-09-110o-repo-health-owner-decisions.md) part 3;
audit rows D2-01, D2-02, D2-03, D2-06, D2-07, D2-12 ([D2](audits/repo-health-audit-2026-09-26/dimensions/D2.md)) and
D7-06 ([D7](audits/repo-health-audit-2026-09-26/dimensions/D7.md)). Fixtures only; no `data/`, credentials, `.env`,
Scheduler state or venue call was touched.

## What was deleted

| Area | Files | Lines |
| --- | --- | ---: |
| `src/weather/market/`: `taker_bot*.py` (15), `taker_edge_permission`, `taker_evidence_starvation`, `taker_profitability_artifact_verification`, `mm_paper*.py` (6), `market_making_readiness` | 25 | |
| `src/weather/operations/`: `taker_bot_daily_roll`, `market_making_daily_roll`, `market_making_preflight_recovery`, `market_making_tape_encoding`, and the two bot-only helpers they orphaned, `bot_daily_roll_supervisor`, `bot_run_liveness` | 6 | |
| `src/weather/reporting/`: `casebooks/taker_tail_casebook`, `market/mm_countability_postmortem`, `market/mm_input_age_postmortem`, `research/unfenced_taker_bakeoff_sweep` | 4 | |
| **src total** | **35** | **32,685** |
| Tests of deleted modules (`tests/market` 10, `tests/operations` 2, `tests/reporting` 1) | 13 | 13,288 |
| `scripts/ops/`: `register_taker_bot_daily_roll{,_supervisor}.ps1`, `register_market_making_daily_roll{,_supervisor}.ps1`, `market_making_daily_roll_task.ps1` | 5 | 340 |

Net diff against the base `b8c82799` (before this report): src +1,224/−34,251, tests +412/−15,001. Two tests of
functions that survive in the read-only module were moved, not deleted: `test_taker_evidence_starvation.py` →
`tests/reporting/test_retired_trading_evidence_starvation.py` and
`test_taker_profitability_artifact_verification_streaming.py` →
`tests/reporting/test_retired_trading_evidence_profitability_streaming.py` (import line changed only). A new
`tests/reporting/test_retired_trading_evidence_freshness.py` pins the maker paper-score freshness reader (its old
coverage lived in the deleted `test_mm_paper.py` and built its fixture with the deleted producer).

The importer map was re-verified with a static AST pass over `src`, `tests`, `tools`, `app`, `scripts` plus `git grep`
for `-m weather...` strings. Beyond the handoff inventory it found `bot_daily_roll_supervisor.py` and
`bot_run_liveness.py`, whose only non-family importers were the fleet pid matchers and nightly health, both removed
here, so they were deleted with their two `test_supervisor.py` cases.

## Retained for Stage 0/1 (owner decision 2026-09-29)

The owner decided to keep the paper-run tool, and every module, CLI, schema row, test and doc it needs, until the
informed maker's own live procedure is written. Line references are to
`docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md` at this branch's head (restored unchanged from `b8c82799`).

**What requires it.** Prerequisite 7 (`:244-275`, command `:250`) requires a simultaneous one-market paper
counterfactual from `python -m weather.market.market_making_run --mode paper-live-forward --permission-profile
market_harvest ... --once`; `:270-271` says the Stage 1 selector reads that run's `run_config.json` and
`quote_intents_long.csv`. The attempt-local sequences run the strict form (`--require-preflight-pass`) three times
(`:1010-1024`, `:1408-1422`, `:1630-1644`), with the paper-run roots at `:659-660`, `:1355`, `:1569`. Their outputs feed
`portable_live_candidate_preflight --paper-run-config/--paper-preflight/--paper-quote-intents` (`:1038-1040`,
`:1434-1436`, `:1657-1659`) and `mm_live_candidate_cli --paper-run-config/--paper-quote-intents` (`:1052-1053`,
`:1076-1077`, `:1446-1447`, `:1669-1670`). `:156` names `market_making_live_pilot` as the owner of the pilot envelope
normalization, and `:442` says the ordinary `market_making_run` live-pilot path requires `mm_platform_verification_v0.6`.
Both consumers load the run through `mm_live_candidate_cli._load_paper_quote_evidence`, which checks the `mm_run`
schema, the `market_harvest` profile, paper mode, one built-in market, policy ceilings, economics identity and every
quote row.

**Dependency trace.** The static `weather.*` closure of `market_making_run` at `b8c82799`, lazy imports included, is 169
files; the only ones this branch had deleted are the nine below, all restored verbatim from `b8c82799`. Beyond the
static closure I checked: no restored module launches a `-m weather...` child, uses `importlib`/string imports, or
imports `mm_paper*`. `mm_paper_scoring` is **not** a dependency: the only edge is the reverse
(`mm_paper_scoring` imports a constant from `mm_scoring_projection`), and the projection files the paper run writes are
read only by the deleted scorer, not by the candidate consumers. My earlier handback named it as a possible dependency;
that was wrong. Data inputs are all passed explicitly by the runbook (snapshot root, observation status,
event-metadata validation, economics snapshot, runs root); `--known-edge-map` and `--promotion-refresh` default to
`data/backtest` files that `mm_paper` used to write, but `market_harvest` does not use them for permission and a
missing file is tolerated (the new test points both at absent files). No `mm_paper` output is required.

| Retained | Lines | Why |
| --- | ---: | --- |
| `weather.market.market_making_run` (CLI) | 2,000 | The prerequisite command itself. |
| `weather.market.market_making_run_support` | 1,349 | Market-harvest input assembly, preflight, lifecycle, run IO. |
| `weather.market.market_making_run_constants` | 45 | Run modes, permission profiles, default roots, quote columns. |
| `weather.market.market_making_preflight` | 1,042 | Data-layer and platform-verification gates, remediation. |
| `weather.market.market_making_evidence` | 104 | Evidence-mode classification recorded in the run. |
| `weather.market.market_making_live_pilot` | 100 | Market-harvest and live-pilot policy clamps (`:156`). |
| `weather.market.market_making_model_variants` | 427 | Model-variant quote tape the run writes. |
| `weather.market.mm_policy` | 1,752 | Quote decision, policy hash, known-edge/promotion loaders, quote columns. |
| `weather.market.mm_scoring_projection` | 679 | `finalize_scoring_projection` runs at the end of every `--once` tick. |

Schema rows restored with their original owners: `mm_scoring_projection` (v0.1, v0.2), `maker_scoring_input_binding`,
`early_hour_market_guardrail`, `mm_model_variant_bakeoff`, `mm_useful_work_liveness`; exclusion `market_harvest_v0`.
Original owners also restored for `mm_run` and the `mm_platform_verification` chain v0.1–v0.6
(`market_making_run`), `mm_policy` v0.1/v0.2 and `mm_quote_intent` v0.1–v0.3 (`mm_policy`), and the `maker_default_v0`
exclusion (`market_making_model_variants`).

Tests restored from `b8c82799`: `test_market_making_run.py` (without the preflight-recovery case, whose module stays
deleted), `test_market_making_live_pilot.py`, `test_market_making_evidence.py`, `test_mm_policy.py`,
`test_mm_scoring_projection.py` (without the four cases for the deleted scorer's `load_quote_rows`),
`test_market_making_csv_encoding.py` (without the three cases for the deleted `market_making_tape_encoding`), and the
original `test_mm_exchange.py` and `test_neutral_execution_helpers.py`. `test_worker_release_binding.py` is the original
minus its taker parts, so the maker release-binding test runs again. New:
`tests/market/test_stage01_paper_run_prerequisite.py` runs the runbook's strict command through
`market_making_run.main` on fixtures under `tmp_path` (numeric token ids, 32-byte condition ids, economics snapshot,
event-metadata validation; no network, no default `data/` path) and asserts it writes `run_config.json`,
`preflight.json` and `quote_intents_long.csv` that `_load_paper_quote_evidence` accepts with qualifying rows.

Docs: `INTERNATIONAL_MM_LIVE_PILOT.md` restored unchanged (the earlier "not executable as written" note is reverted);
README keeps the market-harvest paper-run command; `module-ownership-map.md` keeps `market_making_run` in the size
allowance with its original row and the `mm_scoring_projection` row; `module_size_audit.OWNERSHIP_NOTES` keeps the
`market_making_run` note (2,000 lines, WARN); `OPERATIONS_DESIGN.md`, `architecture.md`, `streak-soak.md` and
`RELEASE_ONE_BUILD_RUNBOOK.md` say the tool is retained for Stage 0/1 only. No scheduled task runs it.

## The read-only module

`src/weather/reporting/market/retired_trading_evidence.py` (1,173 lines, below the 2,000-line warning) holds verbatim
copies, with a docstring that it only reads retained evidence:

- from `taker_evidence_starvation`: `classify_taker_evidence_starvation`, `BLOCKING_CLASSES` and their helpers;
- from `taker_profitability_artifact_verification`: `verify_taker_profitability_artifacts` and its field-presence helpers
  (its module `SCHEMA_VERSION` renamed `TAKER_PROFITABILITY_VERIFICATION_SCHEMA_VERSION`, same value);
- from `taker_bot_artifact_projection`: only the loader `load_settled_finalization_projection` and what it needs;
- from `mm_paper_scoring`: `maker_paper_score_freshness_from_report`, `maker_paper_score_freshness`,
  `discover_run_folders` and helpers (its private `read_json` renamed `_read_maker_json`, body unchanged).

Default roots come from `weather.paths.data_path` (`DEFAULT_MM_RUNS_ROOT`, `DEFAULT_MM_PAPER_JSON`, pinned in
`test_path_policy.py`). It is "small" only relative to what it replaces: all four functions are needed for an unchanged
`trading_evidence.json`.

Readers and how they now read retained evidence:

| Reader | Change |
| --- | --- |
| `reporting/market/trading_evidence.py` (Stage-A step `trading_evidence`, still a barrier dependency) | Imports the four functions from the read-only module; payload unchanged. `--mm-root` and `--taker-root` stay because this step and `settled_day_root_cause` read them. |
| `reporting/daily/daily_learning*.py`, `daily_flow_analysis.py`, `daily_progress_ledger.py`, `scorecards/settled_day_root_cause.py`, `source_gates/cross_hub_readiness.py`, `research/cross_hub_research_audit.py`, `fleet/fleet_observability_payload.py` | Already read taker/MM JSON as data; unchanged except two remediation strings that told the operator to run the deleted `python -m weather.market.taker_bot finalize --watchdog` (now say the taker is retired and the file is archived evidence) and `daily_flow_analysis` no longer lists `taker_finalization_watchdog`/`taker_tail_casebook` as *required* inputs (nothing produces them now). |

## daily_refresh

Removed steps (registry, runners, resources, settled-day barrier dependencies, status summary, report rendering):
`taker_finalization_watchdog`, `taker_edge_permission_map`, `taker_tail_casebook`, `maker_paper_score`. The
`trading_evidence` step and its barrier row are unchanged. The special case that let `maker_paper_score` bypass the
isolated child when paused is gone.

Removed CLI flags: `--paper-maker-paused`, `--skip-maker-paper-score`, `--maker-paper-latest-active-runs`,
`--maker-paper-max-input-bytes`, `--skip-taker-finalization-watchdog`, `--taker-finalization-date`,
`--taker-finalization-sla-hours`, `--taker-finalization-min-free-bytes`, `--taker-finalization-no-finalize`,
`--skip-taker-bakeoff`, `--taker-bakeoff-strategies`, `--taker-champion-strategy-id`,
`--taker-champion-min-complete-label-days`, `--taker-champion-min-settled-orders`, `--skip-taker-tail-casebook`,
`--skip-taker-edge-permission-map`, `--taker-edge-permission-map-out`, `--taker-edge-permission-min-settled-orders`,
`--taker-edge-permission-min-independent-days`, `--taker-edge-permission-min-after-fee-skill`,
`--taker-tail-casebook-date`, `--taker-tail-casebook-max-runs`, and (nightly health, bot-only)
`--nightly-health-max-bot-activity-age-seconds`, `--nightly-health-startup-grace-seconds`. The resume/repair command
builders no longer emit the two `--maker-paper-*` flags. `scripts/ops/daily_refresh_contract.ps1` no longer passes
`--paper-maker-paused` or the three `--skip-taker-*` tokens. **The contract script and the Python CLI must be adopted in
the same merge**: the new CLI rejects the old tokens, so a production tree with the new `src` and the old contract would
fail Stage A at argument parsing.

## Nightly health and fleet observability

- `nightly_health_checks.py` no longer imports the daily-roll modules or reads `scheduled_tasks.json` bot states. It
  emits two fixed `RETIRED` bot rows (report shape kept: `bots`, `retired_bot_count`, `running_bot_count`), never a
  bot alert or restart command.
- `fleet_observability_inventory.py`/`_loops.py`: the two bot daily-roll supervisors are removed from
  `SUPERVISED_LOOP_SPECS`, `LOOP_RESTART_BUDGETS` and the pid-matcher/health branches. The current-code soak and loop
  integrity now cover only the three capture loops. A new ratchet test pins that.

## Schema registry — NOT additive-only

Removed `SchemaSpec` rows (**46**), each owned only by a deleted module and not resolved through `schema_version()`,
`registered_schema()` or `validate_schema_version()` by any retained `src`/`tests`/`tools`/`app` code, and with no
version literal left in retained `src` (checked by AST, `git grep`, and the strict source audit):
`early_hour_market_guardrail_shadow`, `market_making_daily_roll` (v0.2), `market_making_daily_roll_legacy`,
`market_making_tape_encoding`, `mm_countability_postmortem`, `mm_execution_evidence`, `mm_fill_evidence_completeness`,
`mm_known_edge_map`, `mm_known_edge_map_legacy`, `mm_live_readiness`, `mm_live_readiness_v0_2_legacy`,
`mm_model_variant_clustered_promotion_gate`, `mm_model_variant_paper_bakeoff`, `mm_paper`,
`mm_paper_run_folder_selection`, `mm_preflight_recovery_closeout`, `mm_quote_blocker_diagnostics` (v0.2 and v0.8),
`mm_reward_score_diagnostics` (v0.1 and v0.2), `mm_run_legacy`, `taker_bot_daily_roll`, `taker_bot_policy`,
`taker_bot_run`, `taker_champion_challenger_ledger`, `taker_clustered_promotion_gate`, `taker_counterfactual_tape`,
`taker_current_replay_profitability_verification`, `taker_edge_permission_map`, `taker_incremental_persistence`,
`taker_incremental_pnl`, `taker_incremental_state`, `taker_market_benchmark_scoreboard`,
`taker_model_variant_shadow_bakeoff`, `taker_pending_tick`, `taker_profitability_artifact_verification_composite` and
its alias `taker_profitability_artifact_verification_v0_2` (the only `INTENTIONAL_SCHEMA_VERSION_ALIASES` entry, now
`{}`), `taker_resource_budgets`, `taker_settlement_finalization`, `taker_settlement_finalization_watchdog`,
`taker_strategy_bakeoff`, `taker_strategy_bakeoff_ledger_projection`, `taker_strategy_registry`, `taker_tail_casebook`,
`taker_tick_resource_diagnostics`, `unfenced_taker_bakeoff_sweep`. (The first version of this branch removed 52; the
six rows the paper run needs are restored, see above.)

Removed literal exclusions (**5**; the strict audit requires every exclusion to still occur in `src`):
`flat_notional_v1`, `polymarket_symmetric_price_v1`, `top_of_book_only_v1`, `top_of_book_plus_1pct_depth_v1`,
`mm_execution_v2`.

Kept but re-owned (owner metadata pointed at a still-deleted module):
`taker_profitability_artifact_verification`, `taker_strategy_report`, `taker_settled_finalization_projection` →
`weather.reporting.market.retired_trading_evidence`. The paper-run rows keep their original owners.

**This change is NOT additive-only.** `schema_registry_data.py` and `schema_registry_recent_data.py` are in all four
capture closures (delegation contract §3), so landing rolls every capture loop. Lookups by retained code are unchanged
(`test_schema_registry.py` adds a test that the retired names raise `KeyError` and the retained ones resolve); only
names no retained code asks for were removed. A process still running an old module that asks for a removed name
would raise `KeyError` after readoption — the static trace finds none in the capture closures.

## Registrar decision

The registry already expresses "retired, no registrar": `registrar: null` (as for the other host-local retired tasks).
So the preferred route was taken: the four bot registrars and `market_making_daily_roll_task.ps1` were **deleted** (the
retained paper-run tool is attended-only and has no task), and
`WeatherTakerBotDailyRoll{,Supervisor}` and `WeatherMarketMakingDailyRoll{,Supervisor}` stay in
`config/scheduled_tasks.json` as `retired` / `expected_disabled: true` / `registrar: null` and in `status.ps1`
`$expDisabled` (comments updated: they cannot be re-enabled into working code). `test_ops_script_ratchets.py` pins that
and still runs the `-AcknowledgeRetired` refusal test for the two remaining retired registrars (enrichment,
disagreement). `OPERATING_REFERENCE.md` was regenerated with its generator.

`mm_countability_report.ps1` was **kept and reduced**: besides launching the deleted post-mortem, it is the only script
that refreshes the generated `OPERATING_REFERENCE.md` and `data/alerts/OPERATING_SCHEDULE.md`, and D6-09 says a host-local
task runs it. Deleting it would make that task fail daily and drop the schedule refresh; it now only refreshes the
operating reference and prints that the post-mortem is retired.

## Docs and allow-lists

Updated (live docs only): `README.md` (steps, command catalog, data layout), `docs/architecture.md`,
`docs/operations/OPERATIONS_DESIGN.md`, `OPERATIONS_AGENT_ROLE.md`, `HOST_LOAD_POLICY.md`, `RELEASE_ONE_BUILD_RUNBOOK.md`,
`ESTABLISHED_FINDINGS.md` (§8b: the post-mortem command is now described as deleted; the finding is unchanged),
`data-storage-class-contract.md`, `package-boundaries.md`, `module-ownership-map.md` (allowance list and rows; a row
for the read-only module; paper-run rows kept), `docs/ops/streak-soak.md`. `INTERNATIONAL_MM_LIVE_PILOT.md` is unchanged.
Allow-lists: `module_size_audit.OWNERSHIP_NOTES`, `test_import_architecture.py` (migrated/casebook lists, extracted-module
rules, taker split rule; the new module added to the reporting market slice), `cold_archive_reclaim.CONSUMER_FILES`
(dropped `mm_paper_scoring.py`, otherwise its adoption check would fail on a missing file). Dated roadmap, audit,
research and history docs were not edited.

## Per-file roll verdict

Mechanical verdict is `scripts\ops\roll_verdict.ps1 -Branch codex/110o-retire-taker-paper-maker-20260929`; until it says
otherwise **every `src/**/*.py` change and deletion is roll-sensitive**.

| Files | Roll | Closures (static AST trace from the five capture supervisors at the base) |
| --- | --- | --- |
| `src/weather/schema_registry_data.py`, `src/weather/schema_registry_recent_data.py` | **roll-sensitive, certain** | In all four capture closures (§3); change is not additive-only. |
| All 35 deleted `src` modules; `src/weather/operations/daily_refresh*.py` (13 files), `nightly_health_checks.py`, `module_size_audit.py`, `cold_archive_reclaim.py`; `src/weather/reporting/{daily/daily_flow_analysis,daily/daily_learning,fleet/fleet_observability_inventory,fleet/fleet_observability_loops,market/trading_evidence}.py`; new `reporting/market/retired_trading_evidence.py` | roll-sensitive until the verdict | Not in any capture closure by static trace; Stage A imports the daily-refresh family, so a broken edit fails Stage A, not capture. |
| `scripts/ops/*.ps1`, `config/scheduled_tasks.json`, `.github/`, `README.md`, `docs/**`, `tests/**` | roll-free | Outside every closure. |

## Verification

All commands from the worktree root with `C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe`, `TEMP`/`TMP`
and `--basetemp` under `C:\Users\Michael\Documents\github\wt-tmp-110o3`, `-p no:cacheprovider`. The
`scripts\ops\workstation_heavy.ps1` wrapper admitted this host.

- First version (full deletion, commit `f2b32c17`), full suite through `workstation_heavy.ps1 -Kind pytest`
  (`-m pytest -q -p no:cacheprovider --basetemp <tmp>\bt-full tests`): 6,616 passed, 50 skipped, 916 subtests, 2 failed;
  both failures were the correspondence-index staleness, and passed after regeneration (83 passed with the repo-wide
  audits).
- Retention change, focused (direct venv): restored and affected tests (`test_market_making_run`,
  `test_market_making_live_pilot`, `test_market_making_evidence`, `test_mm_policy`, `test_mm_scoring_projection`,
  `test_market_making_csv_encoding`, `test_mm_exchange`, `test_neutral_execution_helpers`,
  `test_worker_release_binding`, `test_mm_live_candidate_cli`, `test_portable_live_candidate_preflight`,
  `test_schema_registry`, `test_import_architecture`, `test_path_policy`, `test_module_size_audit`): 244 passed,
  1 skipped, 19 subtests; `test_stage01_paper_run_prerequisite.py`: 1 passed.
- Final head: full suite through the wrapper, compileall through the wrapper, `agent_docs_audit`,
  `roadmap_backlog --fail-on-lint --check`, and GitHub CI on PR #145 — results are in the handback (this file is not
  edited again after the correspondence-index regeneration).
- `origin/master` (`b0032a90`) is already an ancestor of this branch; `git merge origin/master` was a no-op. #135 has
  not landed, so the `settlement-audit-qualification.yml` edit stays.

## What was NOT done

- No merge to master, registration, task change, restart or production write. `data/` was never read or written.
- `nightly_retrain`/`all_shadow_release_bootstrap` still list `market_making` and `taker_bot` in their default
  expected-runtime lists (release-lifecycle strings, D2-08 keep); changing release-binding semantics is out of scope.
- `weather.market.market_latest_inputs` lost its only `src` importer (the deleted taker CLI) and is now tests-only;
  outside the handoff inventory, not deleted. (`worker_release_binding`, `live_forward_gate`, `info_event_calendar`,
  `clob_recon` and `mm_risk` are imported again by the retained paper-run tool.)
- `staleness_sweep.ps1` still scans for orphan `market_making_run`/`taker_bot` processes (now always empty); harmless.
- The retained taker readers in `daily_learning`/`daily_flow_analysis` still turn an archived
  `taker_finalization_watchdog.json` with SLA breaches into a P0 item, as they did while the steps were skipped.
- `docs/roadmap/correspondence-index.md` is regenerated after the commit (separate commit), per the generator's rule.

## Judgment calls to double-check

1. **Stage 0/1 retention boundary.** Retained exactly the static closure members this branch had deleted, plus their
   schema rows; `mm_paper_scoring`, `market_making_preflight_recovery`, `market_making_tape_encoding` and
   `market_making_readiness` stay deleted because the paper run neither imports nor reads them.
2. **Fleet soak scope.** Dropping the two dead bot supervisors from the current-code soak removes their BLOCK rows and
   "start --force" repair commands, which can change `current_code_soak` status and clean-day countability on a day when
   they were the only blockers.
3. Deleting the two orphaned bot helpers (`bot_daily_roll_supervisor`, `bot_run_liveness`) beyond the handoff list.
4. Keeping `mm_countability_report.ps1` (reduced) instead of deleting it.
5. `.github/workflows/settlement-audit-qualification.yml` is edited here (two test paths); 110o part 4 deletes that
   file. Resolve the modify/delete conflict by keeping part 4's deletion.

## Production steps

1. Get `scripts\ops\roll_verdict.ps1 -Branch codex/110o-retire-taker-paper-maker-20260929`; expect roll-sensitive
   (schema registry in all four closures).
2. Land in a 01:00–04:00 quiet window **after the exam period (panel 09-30..10-13)** unless production decides this is
   exam tooling, through `quiet_window_merge.ps1`, which proves all three capture workers recovered. The `.ps1`
   contract and the Python CLI must arrive in the same merge.
3. Confirm the next Stage-A run (`daily_refresh_status.json`): the step list has no `taker_*`/`maker_paper_score` rows,
   the settled-day barrier's dependencies list has none either and it reaches its normal verdict, and
   `trading_evidence` ran and wrote `data/backtest/trading_evidence.json` with `market_making.paper_score_freshness_*`
   and `taker.profitability_artifact_verification*` fields populated as before.
4. Confirm the next nightly health report shows two `RETIRED` bot rows and no bot alert, and fleet observability lists
   three supervised loops.
5. Optional owner-ops follow-up: identify the host-local task that runs `mm_countability_report.ps1` and retire or
   rename it; unregister the four Disabled bot tasks with backups (their registrars no longer exist).
