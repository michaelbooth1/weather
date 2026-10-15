# 10-18 landing night (2026-10-17 -> 2026-10-18): one combined roll-sensitive attempt

Workstation summary for master. Master lands; nothing here is a merge. Integration branches only.

## Tips

| Choice | Branch | Sha | Contents (merge order) |
| --- | --- | --- | --- |
| **Chosen: land this** | `claude/integration-20261018-stack6` | `cf8cfe6aec4e56cd7ad9f16ba9258e2d55c8da25` | stack5-lg + merge of master `90b2e1844` (`c7ff5abd2`, docs only, clean) + one repair/timings commit (below) |
| Fable-reviewed base (SHIP, master 11:22) | `claude/integration-20261018-stack5-lg` | `a39b998a231d58c2ba645da84cfa100c4766ad17` | stack4 + lastgood `0c62fafe4` (`claude/lastgood-cas-ref-20261015`); **failed the workstation pre-gate**, do not land |
| Fallback reference | `claude/integration-20261018-stack4` | `770ec91d816001e93ddc5ecc51abf5b39b678dbd` | master `01cad4b91` -> #177 r3 `9121de239` -> BLAS cap `50b8c2e7e` -> #182 refresh `33d51261c` (contains #172 refresh `ba5f73d5d`) -> #190 refresh `1f8c2f2c1` |

stack6 contains master `90b2e1844`, so it fast-forwards today; re-check
against `origin/master` at 00:30 and merge master in again (docs only) if it moved.

stack4 carries the same four #182 pre-gate failures, so a stack4 fallback needs the repair commit cherry-picked.
If stack4 is chosen, lastgood stays the 10-19 head (`0c62fafe4`, already merge-tree clean against stack4).

The codex PR heads are stale: #172 `d01d7ce13`, #182 `c4f3a5511`, #190 `97848089a`. Use the `claude/*-refresh-20261013` tips above.

## Merge-tree and the one resolution

Every pair is clean against master and each other except #182 x #190 in
`src/weather/operations/storage_classes.py`. Both add one `ArtifactFamilyClassification` row:
- #182 adds `passive_capture_family_evidence` and `passive_capture_family_status`;
- #190 adds `nbp_complete_cycle_index`.

The resolution in `770ec91d8` keeps all three rows in that order, with no other edits.

## Roll class

On the workstation, `roll_verdict.ps1` returns UNDECIDABLE for every head (no live closure evidence), so the
verdict must come from the host: `scripts\ops\roll_verdict.ps1 -Branch <tip>`.

By content every head touches loop-imported modules (88a capture, `operations/supervisor.py`, NBM sources,
collection), so expect ROLL-SENSITIVE. The tip lands in the 01:00-04:00 quiet window via
`quiet_window_merge.ps1`, and the #177 88a restart is explicit.

## Time budget

There is one bounded suite for the whole tip. Its cap is `MaxRuntimeSeconds` 5400
(`bounded_worktree_test_suite.ps1:27`).

| Step | Time |
| --- | --- |
| Start | about 01:05 |
| Suite ends | by 02:35 at the latest |
| Merge, then 3-worker recovery | about 02:50 |

This leaves about 70 minutes of margin, which is not enough for an unchanged retry. A red result freezes every
head for the night. Fallback: stack4 cannot be retried the same night; re-plan per head for 10-19.

## Workstation evidence

Runs A, B and R used qtest (queue lease) on `a39b998a2`.

- **A, 447 passed:** the #177 r3, BLAS and #172/#182 files:
  - `tests/market/test_execution_tape_{disconnects,flush_faults,stream_coverage,write_cadence}.py`
  - `tests/market/test_maker_evidence_{capture,disconnects,stream_coverage,family}.py`
  - `tests/reporting/test_mg1_reserved_window.py`, `tests/test_short_basetemp.py`
  - `tests/collection/test_loop_supervisor.py`, `tests/market/test_market_microstructure.py`
  - `tests/operations/test_{observation_trigger,supervisor,monitoring_fixes}.py`
  - `tests/app/test_cockpit_view.py`, `tests/reporting/test_{capture_family_status,cockpit_snapshot}.py`
- **B, 644 passed, 15 skipped:** the #190 and lastgood files:
  - `tests/collection/test_{nbp_cycle_reuse,collection_robustness,shared_forecast_payload_cas}.py`
  - `tests/model/test_{nbm_input_regime,source_cache_ttl}.py`
  - `tests/operations/test_{missing_information_admission,schema_registry,storage_classes,workload_admission_script,import_architecture}.py`
  - `tests/reporting/test_{guidance_extract,nbm_target_trace}.py`
  - `tests/sources/test_{nbm_parser_v2_landing,nbm_probabilistic_tmax,nbm_target_fix}.py`
- **R, 146 passed:** `-m ratchet` over all 25 ratchet-marked files.
- **Full pre-gate on `a39b998a2`** (`workstation_pregate.ps1` from master `01cad4b91`, base `01cad4b91`): **FAIL**, 3 chunks
  (receipt `l-data/s18/pregate/pg-a39b998a231d-20261015T103418-83616/receipt.json`). Four tests, all from the #182 refresh
  (`c4f3a5511`, `15dcf8948`), none from #177, BLAS, #190 or lastgood:
  - `test_ps_script_root_param_defaults`: `register_maker_evidence_family_capture.ps1` derived `-RepoRoot` from
    `$PSScriptRoot` in `param()` (empty under PS 5.1 `-File`);
  - `test_hygiene_ratchet[guards_declaration]`: no `Guards:` line in `test_maker_evidence_family.py`, `test_capture_family_status.py`;
  - `test_hygiene_ratchet[unmarked_spawning_test]`: three PowerShell-spawning tests without `@pytest.mark.spawns`;
  - `test_windows_qualification_shards`: `test_capture_family_status.py` (Windows-only) in no CI shard.
- **Repair commit `cf8cfe6ae`** (tests, `.ps1`, workflow, timings; no `src/`): empty `-RepoRoot` default derived in the
  body (an explicit argument still wins); two `Guards:` lines; three `spawns` marks; the file joins `windows-lane-a` in
  the workflow and the pinned shard plan; `tests/bounded_suite_file_timings.json` gains the 12 new test files, with
  seconds from the failed pre-gate's chunk XMLs (Fable's minor note). The hygiene baseline needs no entry: the files now
  comply. Focused run (9 files incl. hygiene, shards, ci_timing, ps-root, bounded-suite script): rc 0.
- **Full pre-gate on `cf8cfe6ae`** (base and pre-gate script from master `90b2e1844`): **FAIL**, 1 chunk of the bounded suite
  (receipt `l-data/s18/pregate/pg-cf8cfe6aec4e-20261015T120012-81956/receipt.json`). All four failures are
  `test_production_cold_archive_wrapper` teardown tests asserting `'running' == 'not_found'`: a child process
  still alive at the check, while three other heavy jobs shared the machine. The stack touches no cold-archive code.
  - Isolated re-run of that file on `cf8cfe6ae`: **71 passed**.
  - Re-run of the whole failing chunk (25 files) on `cf8cfe6ae`: **334 passed, 12 skipped**, rc 0.
  - Verdict: load flake, not a stack defect. Every other chunk passed.
- **Full pre-gate re-run on `cf8cfe6ae`** on an idle queue (master 13:5x): **PASS**, base `90b2e1844` is an ancestor
  (receipt `l-data/s18/pregate/pg-cf8cfe6aec4e-20261015T134457-115928/receipt.json`, sha256 `7107585e…`). The cold-archive
  teardown did not reproduce; that file sits in chunk 4 of 22 in this tree's packing.
- **Fallback** `claude/integration-20261018-stack4-r` @ `50071829d`: stack4 + `cherry-pick -x` of the repair +
  merge of master `90b2e1844`; focused run 228 passed. Land only if stack6 is rejected.

The BLAS parity proof was accepted 10-15: the toronto-aug-12 captured-input replay is byte-identical with and without the cap.

## Host verify after recovery (read-only)

1. **#177 r3:**
   - `status.ps1` exits 0;
   - the 88a and tape workers are RUNNING with the new identity;
   - stream_coverage has no `KeyError awaiting_connect` (F1).
2. **BLAS cap:** within 15 minutes, each capture worker's private bytes are about 60-110 MiB, against roughly 750 MiB
   before. Run:
   ```powershell
   Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' or Name='python.exe'" | ForEach-Object { $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; if ($p) { '{0,7} {1,8:N0} MiB  {2}' -f $_.ProcessId, ($p.PrivateMemorySize64/1MB), ($_.CommandLine -replace '^.*?-m\s+','').Substring(0, [Math]::Min(80, ($_.CommandLine -replace '^.*?-m\s+','').Length)) } }
   ```
   An explicitly set operator value still wins (`setdefault`).
3. **#182:** `status.ps1` and the cockpit show the capture-families block. `maker_evidence_families/*/status.json` is present once a family is enabled.
4. **#190:** NBM v2 parse rows are flowing in the next snapshot pass, and the v1-shadow quarantine is in place.
5. **lastgood (stack5-lg only):** after one snapshot pass, every `last_good_sources.json` is about 1-2 MB, against
   roughly 35 MB before, and `forecast_payloads` rows are still being written. Run:
   ```powershell
   Get-ChildItem -LiteralPath data -Filter last_good_sources.json -Recurse -Depth 2 | Select-Object FullName, Length, LastWriteTime
   ```
   If the NBM fetch fails during the night, look for one `cache_status=fallback_unprovable` warning per digest.

## Not in this plan

- DLv2 S1 and S3 are built separately (S1 on top of stack4, because #172/#182 add `config/capture_families.json`). Neither is a 10-18 head.
- Constraint until Phase B is done (about 04:45 10-16): none of these heads changes `pyproject.toml` dependencies or `requirements.txt`.
