# Production Hardening Handoff — 2026-07-16 09:55 EDT

This is the stopping-point brief for the production-hardening audit begun on
July 15. Resume from the isolated worktrees below; do not restart the audit from
`master` or assume that the hardened code is live.

## Operator constraints

- Do not install or use Box. Do not build off-machine backup yet; the operator
  wants that only after a model has proven value.
- Preserve tapes, ledgers, and trading evidence. No cleanup or deletion was
  authorized.
- No model promotion, active-pointer change, live trading, or capital
  permission is authorized. The current model has not proven edge.
- The user asked to stop at a clean checkpoint. No integration merge, task
  registration, fleet restart, or runtime adoption was started after that
  request.

## Exact git and worktree state

### Live worktree

- Path: `C:\Users\micha\Desktop\github\weather`
- Branch/HEAD: `master` at `39460f6c`
- `master` is 19 commits ahead of `origin/master`.
- The live worktree has two runtime-generated changes:
  `config/location_market_events.json` and `config/locations.json`. They came
  from the successful July 16 06:00 location refresh and roll active markets to
  July 18. Preserve and validate them; do not discard or hand-edit them.

### Integration worktree

- Path: `C:\Users\micha\Desktop\github\weather-overnight-integration`
- Branch/HEAD at handoff creation: `codex/overnight-integration` at
  `e3d09c3d`
- It is clean before this handoff document and contains the hardened release
  bootstrap, snapshot admission/resource stability, taker latest-input bounds,
  observation-cache isolation, and scheduler provenance work.

### PIT preselection worktree

- Path: `C:\Users\micha\Desktop\github\weather-pit-preselection-source`
- Branch/HEAD: `codex/pit-preselection-source` at `11bab9bb`
- It is clean. Its commit stack after shared base `670243b8` is:
  - `db916484` adversarial population-lock tests
  - `7d418d8e` bounded tape/replay reader tests
  - `32266713` bounded promotion-corpus input assembly
  - `ea20291c` staged-source binding tests
  - `11bab9bb` candidate-independent source implementation and docs

Do not squash or rewrite these commits. Merge the branch into the integration
worktree and resolve documentation conflicts by retaining both scheduler and
PIT evidence.

## Completed successfully

### Integrated hardening already on `codex/overnight-integration`

- First inactive release bootstrap is explicit, immutable, and fail-closed; it
  does not activate a release or grant trading permission.
- Snapshot workers use host-memory admission, two-worker defaults, and bounded
  child resources.
- Taker latest-input readers use bounded stable suffix reads and reject
  concurrent mutation, malformed input, and incomplete records.
- Observation watcher caches are isolated per market and bounded/quarantined.
- Scheduler lineage now attests the OS-observed executable, complete argv,
  working directory, creation time, engine PID, and bounded ancestor chain.

### Candidate-independent PIT source on the isolated PIT branch

- Production preselection no longer requires candidate/release/probability
  fields and no longer lets an ambient model choose which rows exist.
- The narrow `production_point_in_time_preselection_source_v1` projection is
  built directly from manifest-pinned captured tape/replay rows and settlement
  labels.
- Tape, replay, auxiliary CSV, settlement JSON, replay/source manifests,
  Arrow batches, row counts, market-days, fields, and output Parquet are
  bounded before expensive parsing or iteration.
- Strict production flags, root/file containment, regular-file/symlink rules,
  stable reads, strict JSON, exact snapshot IDs, label hashes, label quality,
  one winner per snapshot, and winner-band identity are verified.
- Generic candidate-bearing materializations are rejected in production.
- Concurrent source publishers are rejected with exclusive output locks.
  Publication is per-file atomic and manifest-last; a crash orphan remains
  fail-closed and requires reviewed cleanup.
- Final owner-focused verification passed `105` tests and `23` subtests with
  one skipped symlink-escape probe because this Windows account lacks symlink
  privilege. Compile-all, roadmap lint, and agent-doc audit passed.
- A pre-hardening real Toronto June 3 probe had already produced all 231 pinned
  rows with no candidate-dependent fields and a matching selection universe.
  Re-run one real probe after integration because the final bounds and staged
  verifier were added afterward.

## July 16 scheduled daily run

`WeatherDailySettlementPromotionRefresh` ran automatically from 09:30:01 to
09:50:08 EDT and ended fail-closed with Task Scheduler result `1`. The task is
`Ready`; next run is July 17 at 09:30. No daily child/parent remains and both
runtime locks were removed cleanly.

Seven steps completed and persisted:

| Step | Duration |
| --- | ---: |
| `reanalysis_recent_refresh` | 212.441 s |
| `ingest_quality_gate` | 13.017 s |
| `event_metadata_validation` | 1.098 s |
| `public_wu_settlement_restore` | 796.443 s |
| `market_day_labels_finalize` | 149.732 s |
| `exchange_economics_rule_drift` | 0.049 s |
| `taker_finalization_watchdog` | 22.536 s |

New evidence is strong but is not model-edge evidence: all 12 built-in markets
for July 15 have complete labels, strict material coverage, promotion-countable
status, WU settlement, a matching winning band, and exchange reconciliation.
The taker day finalized within SLA with no fills; 660 scoreable source orders
and 4,680 scoreable counterfactual orders were retained, and
`low_price_tail_capped` remains champion.

The blocking step is `taker_edge_permission_map`. Its isolated child hit the
2,147,483,648-byte private-memory cap after 5.334 seconds. Peak private memory
was 2,148,282,368 bytes: 798,720 bytes (about 0.76 MiB, 0.037%) over the cap.
Working set was only 866,439,168 bytes and input bytes were 160,240,634. Treat
this as a cumulative-tape allocation/boundary-sizing defect to diagnose; do not
blindly raise the cap. Production-readiness evaluation was correctly skipped.

Primary evidence:

- `data/backtest/daily_refresh_status.json`
- `data/backtest/daily_refresh_report.md`
- `data/backtest/daily_refresh_step_children/2026-07-16T133007.473705_0000-46772/taker_edge_permission_map.result.json`
- `data/backtest/public_wu_settlement_restore_2026-07-15.json`
- `data/backtest/market_day_labels.csv`
- `data/backtest/taker_finalization_watchdog_2026-07-15.json`

The persisted resume command is below. Do not run it until the permission-map
memory defect is understood and a focused fix has passed tests:

```powershell
c:\Users\micha\Desktop\github\weather\venv\Scripts\pythonw.exe -m weather.operations.daily_refresh run --fail-on-variant-evidence-alert --continue-on-error --evidence-task-name WeatherEveningEvidenceRefresh --stage settlement --settled-analysis-target-date 2026-07-15 --resume-from-step taker_edge_permission_map --heavy-step-subprocess --stage-a-min-available-reserve-mb 1536 --stage-a-max-commit-percent 70.0 --maker-paper-latest-active-runs 14 --maker-paper-max-input-bytes 536870912
```

## Production truth and open blockers

1. The model is not production-ready. Latest audited hourly Brier was about
   `0.07191` versus market `0.03734`; first-live was about `0.08175` versus
   `0.05954`; the best dynamic result was about `0.07635`. There is no proven
   edge and no capital permission.
2. There is no active immutable production release, release-bound corpus,
   clean scheduled training streak, forward shadow window, paper window, or
   capital canary.
3. The July 16 daily pipeline must be repaired/resumed from
   `taker_edge_permission_map`; prior successful steps must not be rerun
   casually.
4. The hardened branches are not merged into each other or adopted by the live
   worktree. Full merged deterministic verification remains mandatory.
5. The training-window tasks still need registration under the hardened
   scheduler contract after code adoption. The last July 16 01:00 run ended
   result `2`; do not register direct nightly/daily alternatives without the
   required reviewed evidence paths.
6. Shared payload CAS reduced duplication, but the last measured host burn was
   still roughly 25.4 GiB/day with about 10.5 days of headroom. No deletion was
   authorized.
7. Off-machine backup remains intentionally out of scope until a model proves
   worth preserving.

## Resume sequence

1. Diagnose `taker_edge_permission_map` read/allocation behavior with the exact
   failed child receipt and a bounded fixture. Preserve the 2 GiB gate until
   measured evidence justifies a contract change. Commit the fix on an isolated
   branch and re-run focused tests.
2. Merge `codex/pit-preselection-source` into
   `codex/overnight-integration`. Expect conflicts in the nightly runbook,
   roadmap item 321, ROADMAP, and generated active backlog. Preserve both work
   streams, then regenerate the backlog.
3. Run the merged verification from the integration worktree with the project
   interpreter:

   ```powershell
   & 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe' -m pytest -q
   & 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe' -m compileall -q app src tests
   & 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe' -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
   & 'C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe' -m weather.operations.agent_docs_audit
   ```

4. Run one real, ignored-data PIT folder probe under final code. Retain only its
   hashes/counts as evidence unless a real production retrain is explicitly
   being attempted.
5. Validate and preserve the two generated location config changes. Commit
   them separately on `master`, merge that commit into the integration branch,
   and repeat proportional verification. Do not overwrite them from an older
   worktree.
6. Merge the verified integration branch into `master` once. Coordinate the
   capture fleet restart/adoption only after the merge so snapshot,
   observation, and taker code roll together. Do not promote a model.
7. Register the dedicated training window after adoption:

   ```powershell
   $repo = (Resolve-Path 'C:\Users\micha\Desktop\github\weather').Path
   $ps = (Get-Command powershell.exe -CommandType Application -ErrorAction Stop).Source
   & "$repo\scripts\ops\register_training_window.ps1" -RepoRoot $repo -WindowTaskName WeatherTrainingWindow -RestoreTaskName WeatherTrainingWindowRestore -WindowAt '01:00' -RestoreAt '04:15' -PowerShellExecutable $ps
   ```

   Read back both tasks exactly: one action each, expected PowerShell executable,
   case-sensitive arguments, exact working directory, enabled state, 01:00 and
   04:15 triggers, `IgnoreNew`, and execution limits `PT3H45M`/`PT15M`.
8. Resume the daily pipeline from the persisted command only after the memory
   fix is adopted. Verify terminal status plus the production-readiness step;
   do not infer success from Task Scheduler alone.
9. Push `master` only after the adopted runtime is healthy and the worktree is
   clean. No push was performed in this stopping pass.

## Safety notes for the next agent

- Check host memory/commit pressure before full tests or resume runs.
- A transient daily status of `interrupted` with a live isolated child is a
  pessimistic pre-child receipt, not terminal failure. Today's run is truly
  terminal and has no live child.
- Use only the repository-owned stop/ensure/restart verbs for capture loops.
- Do not hand-edit status JSON, replay manifests, tapes, ledgers, or generated
  active backlog.
- The source pair has exclusive locks, but replay-manifest/preselection-lock
  outputs still rely on unique candidate work paths and the scheduler's
  single-instance topology. Add broader transaction locking only with focused
  concurrency tests.
