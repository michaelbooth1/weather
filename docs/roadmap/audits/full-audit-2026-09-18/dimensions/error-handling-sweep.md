# Audit dimension: error-handling sweep (swallowed errors, silent skips, fail-open defaults)

Auditor: error-handling-sweep. Date: 2026-09-19. Host: production (read-only; Read/Grep/Glob only, no shell used).
Scope: `src/weather/**` (Python), `scripts/ops/**` (PowerShell + `streak_status.py`). No project file was modified.
No file under `data/`, `scratch/`, `logs/`, `venv/`, `.git/` was read, searched, or listed.

## 1. Method

1. Pattern counts per package with Grep (explicit `path`), multiline where needed.
2. Picked the instances that sit on a decision path the live state says is hurting (settlement chain, status
   monitor, streak, health checks, serving fallback, risk sizing) and TRACED each one end to end: the line that
   produces the default, the function that consumes it, and the decision that the consumer makes.
3. For every structural claim below at least one instance was opened and read; `path:line` is given.
4. Basis labels: `verified_in_code` = I read the lines; `doc_claimed` = a project comment/doc says so;
   `inferred` = reasoning from verified code to a live consequence I could not observe (I had no access to `data/`).

## 2. Counts (src/weather, Python)

| Pattern | Total | Files | Heaviest files |
| --- | --- | --- | --- |
| `except Exception` (broad catch) | 307 | 129 | long_job_guard 16, market_microstructure_capture 13, nightly_retrain 8, mm_live_pilot_cli 8, international_live_session_runner 8, daily_refresh 7, live_variant_predictions 7, family_secondary_artifacts 7, residual_distribution_release 7 |
| bare `except:` | 1 | 1 | calibration/feature_model.py |
| `except ...:` then `pass` | 113 | 59 | experiment_executor 7, model_sources 7, io 6, taker_bot_incremental 5 |
| `except ...:` then `continue` | 139 | 80 | pooled_density_training 11, runtime_monitor 5, wu_history 5, open_meteo_archives 5, marine_water_contrast 5 |
| `except ...:` then `return None/{}/[]/0/False/True/""` | 521 | 250 | variant_prediction_runtime 12, supervisor 12, taker_bot_artifact_projection 9, runtime_monitor 8, io 7, mm_credential_import_cli 7 |
| `read_json(...) or {}` / `default={}` | 104 | 37 | snapshot_evaluation 7, market_making_run 6, market_making_readiness 6, settled_day_root_cause 6, progress_audit 6 |
| `) or {}` / `) or []` idiom | operations 1,211 (72 files); market 894 (48); reporting 4,338 (142); collection 138 (9) | | daily_refresh_status 114, daily_refresh_reporting_steps 112, mm_paper_reports 106, taker_bot_finalization 104 |

Approximate `except Exception` split by package: operations ~121, market ~61, reporting ~32, calibration ~23,
collection ~18, sources ~18, model ~17, top-level ~9, backtesting ~8.

Token polarity in `src/weather/operations` gates: ~101 comparisons against a NEGATIVE token
(`== "BLOCK"`, `== "FAIL"`, `== "CRITICAL"`, `"error"`) versus ~304 against a POSITIVE token (`== "PASS"`, `!= "PASS"`,
`"ok"`). The negative-token style is concentrated in the older chain code (daily_refresh.py 20, event_day_manifest 19,
nightly_retrain 15); newer cold-archive / international-live / storage-recovery code is positive-token (fail-closed).

**Reading the counts honestly.** The large majority of the 521 return-default sites are scalar parse helpers
(`_float_or_none`, `_int`, `safe_float`, date parsing) and are benign. Most of the 307 broad catches that I opened are
annotated (`# noqa: BLE001 - reason`) and RECORD the error into a result dict rather than dropping it
(market_microstructure_capture.py:1171-1184, 1361-1373, 1521-1527, 1584-1585; snapshot_tracker.py:1787-1797, 1943-1948;
long_job_guard.py throughout). The raw counts overstate the problem. The defects that matter are a much smaller set of
GATE-SEMANTICS problems, below.

## 3. Counts (scripts/ops, PowerShell; 73 scripts)

| Pattern | Total | Files | Heaviest |
| --- | --- | --- | --- |
| `-ErrorAction SilentlyContinue` | 80 | 26 | quiet_window_merge 14, status 13, staleness_sweep 8, memory_commit_guard 6 |
| `2>$null` / `Out-Null` | 204 | 49 | quiet_window_merge 32, boot_recovery 27, integration_attempt_contract 22, status 17, training_window 17 |
| empty `catch {}` | 68 | 20 | status 27, workload_admission 13, health_watchdog 4 |
| scripts referencing `$LASTEXITCODE` | 160 refs | 32 of 73 | quiet_window_merge 29, status 14, boot_recovery 12 |
| global `$ErrorActionPreference = "SilentlyContinue"` | 3 scripts | | status.ps1:20, health_watchdog.ps1:25, capture_priority_guard.ps1:13 |

The two MONITORS (status.ps1, health_watchdog.ps1) run with errors globally silenced and depend on explicit
`$null` checks after each probe. Most probes do have one (`if ($null -eq $streak) { $flags.Add(...) }` status.ps1:1103;
`if ($null -eq $settlementCheck)` :1642; `if ($null -eq $mirror)` :4189; watchdog "we are now blind" :41-43). A few do
not (see finding 9).

## 4. Findings (most severe first)

### F1 (HIGH) - The daily chain's failure channel is saturated: `critical`, `deferred`, `interrupted` and a deadline kill all read as "expected"

Trace:
- `daily_refresh_cli.py:815-820` `exit_code_for_status`: `{"critical","deferred","interrupted"}` all return **2**.
- `daily_refresh.py:1485-1498`: top-level status is `critical` whenever the promotion lane is `BLOCKED`
  (`promotion_blocked`), which status.ps1:1494-1498 and :4527-4528 document as the STANDING pre-release state.
- `daily_refresh.py:1499-1582`: every `fail_on_*` escalation is written `if X == "BLOCK" and payload["status"] == "ok"`.
  While the promotion lane is BLOCKED the status is never `"ok"`, so all ~12 escalations are no-ops; ingest FAIL,
  exchange-rule BLOCK, hourly/ten-minute BLOCK, scoring-liveness BLOCK cannot change the top-level status or exit code.
  Each lookup also defaults an ABSENT step to `{}` (`next((...), {})`), so a step that never ran contributes nothing.
- `status.ps1:3414`: `$expNonZero["WeatherDailySettlementPromotionRefresh"] = @("0x2","0x4B")`, consumed at :3983.
  0x2 = any of the three statuses above; 0x4B = the wrapper KILLED the chain at the 11:55 protected-window deadline.
  Neither is flagged.
- `status.ps1:1584-1590`: a step with status `deferred` sets a display string only; `$warns.Add` is in the `else`.
  `$chainStatus` is used only for display (:1487, :4441, :4527, :4537). `$chainBlocked` (payload BLOCKs) is display-only
  (:1548, :4441, :4540) - no warn, no flag.
- `chain_recovery_run.ps1:441`: any unbounded exit 2 is written to the recovery status as
  "chain ran; exit 2 = readiness gates BLOCK, expected pre-release" - also when the run was DEFERRED and did nothing.

Consequence: a chain day that was deferred by the resource gate, interrupted, or killed at the deadline before
`market_day_labels_finalize` produces exit 2/0x4B (= expected), no warn, no flag. Each run settles only yesterday, so
that date is a permanent hole until someone runs a per-date backfill. The only alarm is the CONSEQUENCE check
(`settlement_hole_check`), which deliberately skips yesterday before 12:00 (`settlement_hole_check.py:83-84`), i.e. it
fires roughly a day later. This is the project's own named shape ("silencing a false alarm creates a false silence";
"split the overloaded bit") applied to the most important task on the host.

Basis: verified_in_code (all lines above); the "promotion lane is always BLOCKED pre-release" premise is doc_claimed
(status.ps1 comments). Known status: the hole mechanics are known_open (memory + status.ps1:1603-1613); I found no
record in docs/operations of the exit-code conflation itself -> new.

Recommendation: split the bit. Give `deferred`/`interrupted` their own exit code (e.g. 75, already used by
chain_recovery_run.ps1 for temp-fail), make status.ps1 WARN on `deferred` and FLAG when the settled-day steps
(`public_wu_settlement_restore`, `market_day_labels_finalize`) are absent/not-ok for yesterday, and compute the
`fail_on_*` escalations into a separate field that the permanent readiness BLOCK cannot mask.

### F2 (HIGH) - "Settled" has six divergent definitions; the freshness gate and its repair command are satisfied by a row that holds nothing

Definitions found:
1. `backtesting/settled_days.py:91-93` `discover_settled_folders`: target_date < today AND tape exists (a CALENDAR test).
2. `operations/closed_market_day_archive.py:823-833` `_finalization_for_folder`: ANY label dict -> `settled_countable` /
   `settled_non_countable`; a `settlement_source:"none"`, bucket-null label is named "settled_non_countable".
3. `operations/settled_day_freshness.py:265-317`: `canonical_complete = not missing`, where `missing` is eight
   EXISTENCE checks (folder, tape, labels row, ledger row, settlement.json, replay status, replay inputs, source status).
4. `operations/settlement_hole_check.py:48-51`: source non-empty, != "none", `settlement_high` not None (so `snapshot_high`,
   `daily_summary(sparse)`, `override` all count).
5. `scripts/ops/settlement_backfill_one.ps1:240-257`: source == `daily_summary` EXACTLY and a finite high.
6. `scripts/ops/streak_status.py:61,105`: quality_grade not in `{"missing_settlement"}`.

The dangerous one is (3):
- `settled_day_freshness.py:402-406`: status is FAIL only if something is MISSING, WARN on source lag, else PASS.
  `settlement_bucket_missing_count` (:429) is computed and rendered but a Grep of `src/weather` shows it is consumed
  nowhere else - no gate reads it.
- `:283-287` `needs_finalization` is False as soon as a ledger row + label row + settlement.json exist, whatever they
  contain. `repair_missing_settlements` (:512-514) `continue`s past such rows, and `cmd_repair` (:732) returns 0 unless
  status is FAIL. So the `repair_command` that the freshness report itself prints is a guaranteed exit-0 no-op for a
  date whose row is `none`. Worse, `:524-537` "restores from existing": if ANY prior label exists (including a `none`
  one in settlement.json) it is copied into the ledger/labels CSV instead of re-finalizing.
- `daily_refresh_settled_day.py:387` the settled-day barrier blocks on freshness only when status == "FAIL".
- How `none` rows get written for dates other than yesterday: `run_market_day_labels_finalize`
  (`daily_refresh_source_steps.py:658`) finalizes EVERY folder returned by definition (1), while the WU restore step
  only fetches the single target date (`:169-191`). The project's own incident notes (status.ps1:1621-1628,
  streak_status.py:99-102, settlement_backfill_one.ps1:199-204) record exactly this happening on 2026-08-10/11; the fix
  landed in those three places and not in settled_day_freshness / the barrier / closed_market_day_archive.

Basis: verified_in_code. Known status: the shape is known and was fixed elsewhere; this residue is new as far as I
can find (no mention of `settlement_bucket_missing_count` or `canonical_complete` in docs/operations).

Recommendation: one shared `is_settled(row)` predicate (source + finite high + bucket) imported by all six sites;
make freshness FAIL when `settlement_bucket_missing_count > 0` for a closed date; make `needs_finalization` true for
rows that fail the predicate; rename `discover_settled_folders` / `settled_non_countable` so that "settled" is never
used for "past-dated" or "has a row".

### F3 (HIGH, known_open) - Settlement is all-or-nothing across 12 markets with no self-heal; one market's BLOCK leaves the whole date unsettled

- `daily_refresh_source_steps.py:252,278-282`: restore status is BLOCK if ANY one market row is not PASS.
- `:650-657`: `run_market_day_labels_finalize` returns BLOCK for ALL markets when restore status != "PASS" -
  finalize_folders is never called, so zero of 12 ledgers get a row for that date.
- Each run targets only yesterday (`settled_analysis_target_date`), so nothing retries the date. The code comment at
  `:204-209` records the 2026-07-27 instance; retries for TRANSIENT errors were added (:210-219) but the structure
  (one market gates twelve) is unchanged. `finalize_folders` itself already isolates per-folder failures
  (`settlement_ledger.py:1465-1490`) - the isolation exists one layer down and is defeated one layer up.
- `wu_history.py:735-741`: `missing_dates` silently subtracts dates stamped `treated_as_source_unavailable`. For such a
  date the restore row is BLOCK with `error_count: 0` and `fetched_range_count: 0` and NO field explaining that the
  fetch was skipped on purpose (`daily_refresh_source_steps.py:253-276`). Page-backed 404 was demoted to transient
  (`wu_history.py:116-117`), but HTTP 400 still poisons a date permanently.

This is the inverse of fail-open, and it is the mechanism most consistent with the live "10 of 14 dates unsettled,
up to 12 of 12 markets" (inferred - I could not read the ledgers or chain receipts). Known status: known_open
(memory: "chain fail-closed blast radius", "missed chain day = settlement hole").

Recommendation: finalize the markets whose restore row PASSed and BLOCK only the failed ones (the per-folder isolation
and `merge_labels_csv` already exist); add a bounded automatic retry of the last N unsettled dates at the start of each
chain run; add `skipped_as_source_unavailable: true` to the restore row.

### F4 (MEDIUM) - A fallback settlement from our own tape is graded `complete`, clears the hole flag, and needs no WU fetch

- `settlement_ledger.py:489-508`: if the WU daily summary is absent or has < 18 rows, settlement falls back to
  `snapshot_high` (max of the WU-high column seen in OUR capture tape).
- `quality_grade` (:156-176) and `material_coverage_grade` (:272-299) penalise only `sparse`, `none`, `override`;
  `snapshot_high` can be `complete` and promotion-countable. `settlement_source_audit._classify`
  (`reporting/source_gates/settlement_source_audit.py:273-292`) can return FINALIZED for it.
- The hole checker (definition 4 above) counts it as settled; the backfill tool (definition 5) does not.
- `settled_day_freshness repair` calls `finalize_folder` directly (:539) with no WU restore, so it will "settle" an
  absent date from `snapshot_high` whenever the daily summary is missing, and report WARN at most.
- Gate-threshold mismatch: the restore gate passes on `row_count > 0` (`daily_refresh_source_steps.py:134-143`) while
  the ledger needs `row_count >= 18` (`COMPLETE_DAY_MIN_ROWS`, settlement_ledger.py:34,489) to use the summary.
  Between 1 and 17 rows the restore says PASS and the label silently comes from the tape instead.

Mitigation present: Polymarket reconciliation + `append_mismatch_alert` (:1432) is an independent cross-check when
enabled. The project's own findings say the WU series is not append-only and the pre-dawn high can carry yesterday, so
a tape-derived high is not a safe silent substitute. Basis: verified_in_code. Known status: new.

### F5 (MEDIUM) - Health checks gate on the presence of a NEGATIVE token, so unreadable/absent evidence passes

- `nightly_health_checks.py:216-221` `latest_maker_run_summary`: `payload = read_json(latest, default={}) or {}` then
  `"status": "ok"` is stamped unconditionally. A corrupt or half-written `run_summary.json` yields status ok with every
  field None. (`weather/io.py:127-134` `read_json` returns `default` for both "missing" and "corrupt"; 104 call sites use
  the `or {}` form.)
- `:383` the useful-work alert fires only when `useful_work_status == "BLOCK"`; None (unreadable/absent) raises nothing.
- `:329-336` `if artifact:` - an absent `artifact_liveness` block skips the check entirely; `artifact.get("ok") is False`
  passes when `ok` is missing.
- Same style in the chain aggregator (F1) and ~101 comparisons in `operations/`.

Mitigation present: mtime staleness is still checked (:370). Basis: verified_in_code. This contradicts the project's
own written rule "an unreadable state is not a passing state" (OPERATIONS_AGENT_ROLE.md:288). Known status: new.

### F6 (MEDIUM) - Serving silently degrades HGB -> LR -> empirical on ANY exception; the fallback is recorded but nothing alarms on it

- `model/model_features.py:1238-1293`: any exception in the HGB path (corrupt pickle, sklearn mismatch, feature-shape
  mismatch) -> `logger.warning` and fall through to LR; `:1296-1347` same again to `(None, "empirical")`.
  Loaders `:65-71`, `:84-89`, `:1567-1572` return None on any exception.
- `:1269` `pd.DataFrame([feat_dict], columns=bundle["feature_names"])` turns any feature the artifact expects but
  serving does not supply into NaN -> imputed, with no count (the "model is blind" defect class; the project has a
  train/serve parity gate as a standing control - known).
- `active_model_kind` is persisted (`collection/snapshot_store.py:381,2087,2334`) and attributed after the fact in
  `reporting/scorecards/distribution_stage_attribution.py`, but a Grep of `src/weather/operations`, `scripts/` and the
  reporting gates finds no monitor that flags `active_model_kind != "hgb"`.

Basis: verified_in_code for the ladder; the "no alarm" half is a negative grep result (medium confidence).
Known status: new.

### F7 (LOW) - The streak is contiguous over LEDGER ROWS, not calendar days

`scripts/ops/streak_status.py:94-114`: `contiguous_complete_run` walks `sorted(grades)` in reverse; a calendar date with
no ledger row at all is not in `grades`, so [D-3 complete, D-2 ABSENT, D-1 complete] counts as streak 2.
`complete_rate_last14` (:233-235) is completes over the last 14 ROWS, not the last 14 days. With F3 producing dates that
have no row at all, the headline "N/14 contiguous complete days" can overstate. The owner has ruled that the streak
gates nothing, so severity is low - but it is the first line of status.ps1 and MORNING_BRIEFING.md. Known status: new.

### F8 (LOW, latent) - Risk sizing coerces unparseable USAGE to 0.0 and disables correlated caps on a bad value

`market/mm_risk.py:32-37` `_float(value, default=0.0)`. For CAPS a bad value -> 0 -> size 0 (fail-closed, good). For USED
state it is fail-open: `:400-425` `remaining = cap - _float(state.current_*_usdc)`, so None/NaN/garbage "loss used"
reads as "nothing used" and the full cap is available. `:448-451` `if correlated_notional_cap > 0:` - an unparseable
correlated cap becomes 0.0 and the limiter is OMITTED rather than binding. Latent today: `fractional_kelly=0.0` and
`live_edge_is_credible=False` (:344-347) force size 0, and no live trading is authorized. Fix before any live pilot.
Basis: verified_in_code. Known status: new.

### F9 (LOW) - Monitor self-blinding spots in status.ps1

- `:20` global `SilentlyContinue`. `:1330` a failed `Get-Content` of `disk_free_trail.jsonl` (file briefly locked by a
  concurrent status run - the watchdog and the 15-minute task both invoke it) leaves `$old = @()` without throwing;
  `:1361-1362` then REWRITES the trail with only the new sample. For the next 24-48 h `$ref` is null, `$diskDelta` is
  null and the "disk filling at X GB/day" flag (:1365-1375) cannot fire. The absolute `< 25 GB` flag (:1301) still
  works, so this is bounded. (inferred failure scenario, mechanism verified_in_code.)
- `:1484-1488` an unreadable or missing `daily_refresh_status.json` yields `CHAIN: ? / running/unknown` - no warn/flag.
  There is no age check on that file at all, so a chain that stopped running shows its last run's status forever.
- `:1179,1203` `last_clean_age_seconds` is computed and exported but never compared with a threshold; only
  `consecutive_errors >= 3` flags, and only if the field exists (:1210).
- `:1620` `if (Test-Path $settleRoot)` - if the path is absent the whole hole check is skipped with no message.
  `settlement_hole_check.py:68-72` likewise: a missing root or a market without `ledger.jsonl` is skipped silently and
  `ok` stays True; `market_count` is reported but never compared with the registry (the backfill tool DOES build its
  denominator from the registry: settlement_backfill_one.ps1:86-147).

### F10 (INFO) - Silent row drops in training/scoring shrink denominators without a counter

`calibration/pooled_density_training.py` has 11 `except (TypeError, ValueError): continue` row skips (e.g. :147, :340,
:557, :736) with no dropped-row count returned. `:735` `outcome = float(row.get("outcome") or 0.0)` treats a MISSING
outcome as a negative in a calibration fit; `:732` `zip(rows or [], probabilities or [])` silently truncates on a length
mismatch. Narrow exception types, probably rare in practice; relevant to the project's own lesson "check the
denominator". Not traced to a served artifact.

## 5. Strengths (verified)

1. `scripts/ops/settlement_backfill_one.ps1` is a model of outcome verification: header states "EXIT 0 IS NOT EVIDENCE
   OF A SETTLED DATE" (:24-27), denominator comes from the market registry not from directories (:86-147), per-market
   content check of the newest row (:209-257), distinct SILENT_NOOP / PARTIAL / SETTLED states (:297-307), and ledger
   reads use `FileShare.ReadWrite` so a diagnostic cannot fail a production write (:213-223).
2. `operations/capture_resource_gate.py` is genuinely fail-closed: unmeasurable memory -> BLOCK (:426-433), unmeasurable
   disk -> BLOCK (:455-463), evaluator exception -> deny (:670), proof-persistence failure -> deny (:735);
   un-evaluated growth headroom is labelled `NOT_EVALUATED`, not PASS (:481).
3. `backtesting/settlement_ledger.py:1436-1490` `finalize_folders`: per-folder retry, failures collected, surviving labels
   MERGED (not overwritten), then a loud `FolderFinalizationError`. Exactly the right shape, with the incident recorded
   in the docstring.
4. `collection/snapshot_tracker.py:1402-1444` `finalize_iteration_error_state`: uses an EXPECTED-market denominator, a
   missing result is an error (`capture_result_missing`), liveness heartbeat and clean-iteration markers are separate
   fields; status.ps1:1210-1221 reads them ("process/heartbeat liveness alone is not a clean iteration").
5. `scripts/ops/storage_recovery_night_run.ps1:54-60,110`: the receipt is born `FAILED` and only becomes PASS after the
   child result is hash-bound and verified - status is stamped AFTER verification, never before. Broad catches across
   `long_job_guard.py`, `market_microstructure_capture.py`, `supervisor.py` are annotated and record tri-state results
   (`unknown` / `available: False` / `error`) instead of returning bare defaults.

## 6. Not covered

- The other ~290 `except Exception` sites and ~500 return-default sites were counted, not individually read. I opened
  roughly 25 files.
- `src/weather/reporting` (4,338 `or {}` sites): only settlement_source_audit and the attribution scorecard were read.
  Promotion/orchestration (`reporting/promotion/orchestration.py`, 6 return-defaults) and
  `production_readiness_gate.py` were not traced.
- `market/market_making_readiness.py` (57 `or {}`, 6 `read_json or {}`) and `market_making_preflight.py` were not traced.
- `scripts/ops/quiet_window_merge.ps1` (14 SilentlyContinue, 32 Out-Null, 29 $LASTEXITCODE) - the most
  state-changing script - was only counted. `boot_recovery.ps1`, `training_window.ps1` likewise.
- No live evidence was read (no `data/` access in this brief), so every link from a code mechanism to the current
  10-date hole is inferred, not observed.
- Tests were not inspected for coverage of the fail-open branches.

## 7. Open questions for the owner

1. Are the ten currently-unsettled dates ABSENT from the ledgers or present as `none` rows? (Absent -> F3/F1;
   `none` -> F2, and `settled_day_freshness repair` will no-op on them.)
2. Were the unsettled chain days `deferred`, killed at 0x4B, or BLOCKed at the WU restore? The exit code cannot tell
   you (F1); `daily_refresh_status.json` for each day would.
3. Is `snapshot_high` an acceptable settlement source for promotion-countable evidence? The backfill tool says no,
   the ledger grader says yes (F4).
