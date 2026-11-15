# Drive decision 4 — archive-safe readers and workstation restore-set [DONE, DO NOT MERGE BEFORE 10-14]

**Verdict: DONE.** D1–D5 are implemented on `codex/drive-reader-safety-20261003` (draft
[PR #174](https://github.com/michaelbooth1/weather/pull/174), marked DO NOT MERGE BEFORE 10-14).
With nothing archived, every reader behaves exactly as before; the parity tests below pin that.
The branch merges `origin/codex/stage-a-incremental-20260927` (#117) first, so its diff is
additive on top of #117. Roll verdict: **UNDECIDABLE on the workstation** (no closure evidence).
Production must run `scripts\ops\roll_verdict.ps1 -Branch codex/drive-reader-safety-20261003`.

Owner decision: Drive decision 4 (2026-10-02), approved in the dispatch prompt. Open questions served: none.

## What changed

| Item | File | Behaviour with an archived (marker-registered) file |
| --- | --- | --- |
| D1 | `src/weather/backtesting/settlement_ledger.py` | `finalize_folders` success path keeps the existing `market_day_labels.csv` row byte-for-byte for a folder whose tape is archived (`tape_is_archived`); no re-finalize, no ledger upsert. The failure path already merged. |
| D2 | `src/weather/backtesting/settled_days.py` | `discover_settled_folders` counts a marker-registered tape as present. |
| D2 | `src/weather/backtesting/replay.py` | `_read_jsonl` resolves through `resolve_local_path`: verified cache or `ArchivedInputRequired`. |
| D2 | `src/weather/backtesting/replay_backtest.py` | An archived tape is no longer "no snapshots_long.csv"; it is read through the cache or raises. |
| D2 | `src/weather/backtesting/tape_scoring.py` | `load_feature_vectors` raises instead of scoring without features (needed by D4). |
| D2 | `src/weather/reporting/candidate_lifecycle/price_free_model_learning.py` | Label-less discovery yields marker-only tapes; `read_csv_rows` resolves or raises; selection counts `archived`. |
| D2 | `src/weather/reporting/scorecards/live_variant_settlement_scorecard.py` | `discover_tapes` includes marker-only `variant_predictions_long.csv`; `read_rows` reads the cache (keeping the logical `_source_path`) or raises. |
| D2 | `src/weather/reporting/scorecards/captured_input_parity_evidence.py` | An archived input raises `ArchivedInputRequired`; a cached one blocks `<role>_archived` (a restore is never fresh capture). |
| D3 | `src/weather/operations/replay_status_backfill.py` | Archived inputs reuse the existing status: the #117 cache result if present, otherwise `skipped / replay_status_exists` with marker-derived evidence (`archived_inputs`, counts `None`). Archiving no longer forces an overwrite through the signature change. No status gives action `archived`; `--overwrite` raises. |
| D4 | `src/weather/reporting/hourly/hourly_model_scoring.py` | Hourly and ten-minute selection (shared) report `skipped["archived"]` apart from `missing_tape`; a verified cache is selected and scored from the cache. |
| D5 | `src/weather/operations/workstation_restore_set.py` (new) | `plan` (read-only) and `run` (workstation wrapper + assignment): date range + families → markers → event-day-manifest SHA/size check → catalog proof export → independent download (`transfer_chunk`, `download_and_verify`) → crypt restore (`bulk_cold_archive_crypt.run("restore")`) → `publish_restore` → `publish_cache` → every member re-hashed through `cached_path`. Refuses hand-copied originals, manifest mismatch or absence, unverified caches, quota overflow and an overlapping work root. |
| docs | `docs/operations/cold-archive-locations.md` | Reader table and the restore-set procedure. |

No `src/maker_core`, `maker_replay_bundle` or `maker_plugin` change. No schema-registry change
(the restore-set report carries `tool`, not a `schema_version`).

## Consequence the owner should know

Training and calibration jobs that discover days through `settled_days` (probability calibration,
forecast-error, ensemble, settlement-lag, residual corpus, point-in-time evaluation, promotion corpus)
now see archived days. They raise (`ArchivedInputRequired`, or `FileNotFoundError` where a caller
opens the tape directly) instead of training on a silently smaller population. That is the
decision's intent, but it means old days must not be archived from production ahead of a scheduled
retrain unless a restore set is published first, or the retrain window is bounded to local days.
Report/selection surfaces (D4) do not raise; they report `archived`.

## Tests (fixtures only)

Every marker, catalog entry, restore record and cache is produced by the production publishers through
the existing `test_cold_archive_catalog` proof-chain fixture (`tests/cold_archive_fixture.py`).

- `tests/backtesting/test_archive_aware_readers.py` (6): D1 archived row byte-for-byte (fails without
  the fix; verified); D1 parity: without a marker the rewrite equals the old `write_labels_csv(labels)`
  output exactly; D2 settled discovery with and without archive; replay corpus raises / reads cache.
- `tests/reporting/test_archive_aware_scoring.py` (8): D4 `archived` vs `missing_tape` for hourly and
  price-free; parity without archive; cached restore selected and read; variant discovery and rows;
  parity evidence raise and cache block.
- `tests/operations/test_replay_status_backfill_archive.py` (4): D3 reuse with cache, without cache,
  no-status `archived`, `--overwrite` raises, parity without archive.
- `tests/operations/test_workstation_restore_set.py` (8): D5 end-to-end to a verified cache that readers
  resolve; refusals (hand copy, manifest mismatch, manifest missing, family/date filter, work-root overlap,
  wrapper required); `plan` CLI writes nothing.

Full suite through `scripts\ops\workstation_heavy.ps1`: **not run locally**. The wrapper refused for
~2 h: first another session's heavy lease, then `ACTIVE workload recovery found 2 residual heavy process(es)`
(two `python.exe` started 2026-10-02 16:13 that belong to another session; not terminated, admission not
bypassed). The 26 new tests, `test_ops_script_ratchets.py` and the agent-docs audit were run directly.
GitHub CI is the full-suite evidence. The first run (`80529b12`) failed one test,
`test_task_inventory_covers_registrars_status_and_generated_docs`, with 6587 passing. The cause was this
branch: the new import shifted two `settlement_ledger` constant line numbers recorded in the generated
`docs/operations/OPERATING_REFERENCE.md`. It was regenerated with `python -m weather.operations.operating_reference
--out docs/operations/OPERATING_REFERENCE.md`. The final head's CI conclusion is in the handback reply and on PR #174.

## Per-file roll classes

`roll_verdict.ps1` exits 1 (UNDECIDABLE) here: the workstation has none of the four closure status files.
Advisory only, not a verdict: importing `weather.collection.snapshot_tracker`,
`weather.market.market_microstructure` and `weather.operations.observation_trigger` on this branch
loads none of the changed modules at import time (lazy imports are not covered).

| File | Class to confirm on production |
| --- | --- |
| `docs/operations/cold-archive-locations.md`, `docs/operations/OPERATING_REFERENCE.md`, `docs/roadmap/*` | roll-free (docs) |
| `tests/**` | roll-free (tests are not imported by capture) |
| `src/weather/operations/workstation_restore_set.py` | new module, imported by nothing in `src`; expected roll-free |
| `src/weather/backtesting/{settlement_ledger,settled_days,replay,replay_backtest,tape_scoring}.py` | Python; not loaded by the three loop entry modules at import time; confirm with `roll_verdict.ps1` |
| `src/weather/operations/replay_status_backfill.py` | same (daily-chain module) |
| `src/weather/reporting/{hourly/hourly_model_scoring,candidate_lifecycle/price_free_model_learning,scorecards/live_variant_settlement_scorecard,scorecards/captured_input_parity_evidence}.py` | same (reporting) |
| #117 files carried by the merge | as classified on #117 |

Not touched: `schema_registry*` (no additive-only statement needed), `weather.cold_archive_locations`.

## What was NOT done

No registration, no Scheduler change, no production write, no restart, no merge, no download or Drive
call, no credential or `.env` access, no auto-fix. The `run` path's real download/restore steps are the
existing reviewed executors and were exercised only through fixture seams; the first real restore set
should be a one-archive set on the assigned workstation.

## Reproduction

```powershell
git fetch origin
git switch codex/drive-reader-safety-20261003
.\venv\Scripts\python.exe -m pytest tests\backtesting\test_archive_aware_readers.py tests\reporting\test_archive_aware_scoring.py tests\operations\test_replay_status_backfill_archive.py tests\operations\test_workstation_restore_set.py -q --basetemp <short-empty-dir>
.\venv\Scripts\python.exe -m weather.operations.workstation_restore_set plan --data-root <recovery-data-root> --start-date 2026-09-01 --end-date 2026-09-07 --family snapshots
powershell -File scripts\ops\roll_verdict.ps1 -Branch codex/drive-reader-safety-20261003
```

Use a short `--basetemp` on Windows: the catalog fixture nests deep paths.

## Commit

Branch `codex/drive-reader-safety-20261003`. Code commit `80529b12`; the handback reply gives the final head SHA
(this report's own commit).
