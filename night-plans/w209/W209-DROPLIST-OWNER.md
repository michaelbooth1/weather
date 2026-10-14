# W209 host-suite drop list: proposal for the owner (NOT IN FORCE)

generated: 2026-10-14 01:35 America/Toronto (workstation DESKTOP-RFCD2GH)
status: **PROPOSAL ONLY.** Nothing here changes HOST_LOAD_POLICY or `scripts/ops/bounded_worktree_test_suite.ps1`. Adopting it would need a reviewed change to the suite, plus master and owner approval.

## The question
The host runs the full bounded suite: every tracked `tests/**/test_*.py`, 522 files, in 25-file chunks, inside 00:30-09:00. The GitHub Windows Qualification lane (`.github/workflows/windows-qualification.yml`, 13 shards on `win25-vs2026`, Python 3.11.0) already runs many of the Windows-native tests on every master push.

Which individual tests could the host stop running because the Windows lane already proves them?

## Answer in one paragraph
**1,958 test cases** in 78 files could leave the host suite. Each one PASSED natively on the Windows lane in all three evidence runs. They took about 45 min of runner time in the 08:09Z run.

**215 cases stay.** Every one of the other ~440 files also stays, since the lane does not run them.

The list is **per test, not per file** (Defender N2). A file can lose some cases and keep others: every case the lane skipped, or never ran, stays on the host.

## Evidence (JUnit artifacts, read-only)
| Run | When (UTC) | master SHA | Result |
| --- | --- | --- | --- |
| 38351441191 | 2026-10-13 05:27 | ed22f00fe7a0 | success, 13/13 shards |
| 38367397542 | 2026-10-13 08:09 | 4bc93ae5d100 | success, 13/13 shards |
| 38410615599 | 2026-10-13 14:07 | a99423120301 (current master) | failure: status-rest, 1 failed / 200 passed. This is the flake fixed by draft PR #284. |

- Full per-test table: `C:\wt\workstation-chat\l-data\swarm-m\W209-DROPLIST-per-test.csv`. It has 2,173 rows, with these columns: `verdict` (DROP/KEEP), `shard`, `test_id`, the status in each run, and `reason`.
- Builder: `C:\wt\w209-art\w209_droplist_build.py`.
- Artifacts: `C:\wt\w209-art\<run>\`.

## Rule used (a case is DROP only if all of these hold)
1. It appears in the Windows lane JUnit of **all three** runs.
2. It is **passed** in all three. It is not skipped, failed or errored in any of them.
3. Its file is not on the keep list below.

Anything that is not DROP stays on the host. That includes cases the lane deselects through its `-k` or `-m "not ratchet or windows_native"` filters (they never appear in the JUnit), and every file outside the lane.

## Files kept whole on the host (reason)
| File | Cases on the lane | Reason |
| --- | --- | --- |
| test_production_baseline_reconciler_execution.py | 76 (reconciler-1..7) | L5: runs when the reconciler surface is touched and nightly |
| test_bounded_worktree_test_suite_script.py | 44 | integration-preflight ratchet |
| test_quiet_window_merge_execution.py | 25 | host-divergent merge script, until the M5 classifier (#243) lands |
| test_integration_attempt_scripts.py | 21 | integration-preflight ratchet; host-divergent integration script |
| test_integration_attempt_evidence_recovery_hardening.py | 8 | integration-preflight ratchet |
| test_reconcile_ordinary_quiet_merge.py | 5 | host-divergent merge script (#243) |
| test_integration_attempt_registration_safety.py | 3 | integration-preflight ratchet |
| (other preflight ratchets: schema_registry, module_size_audit, import_architecture, agent_docs_audit, boot_recovery, register_boot_recovery, suite_gated_quiet_merge, quiet_window_merge_script, host_task_wrappers, roadmap_backlog, app_roadmap) | 0 on the lane | integration-preflight ratchet |

## Individual cases kept inside otherwise-dropped files (33)
**Skipped on the lane, so never proven natively (Defender N2): 19 cases**
- `test_workload_admission_script.py::test_lease_is_exclusive_and_recovers_when_owner_exits`
  - Skipped in the 14:07Z run ("lease acquisition is policy-blocked now"): the runner's UTC clock was outside the window. This is the capture-profile lease test that N1 flagged.
- `test_workstation_pregate_script.py`, 5 cases: `interrupted_pregate_exits_nonzero…`, `detects_a_console_attached_chunk_launch_mutant`, `fails_a_head_whose_tests_fail`, `passes_a_good_head_in_host_console_mode…`, `rejects_a_base_that_is_not_an_ancestor`
  - Skip reason: "the host suite's 50 GiB disk floor cannot be met" on the runner.
- `test_supervisor.py::TestSupervisorPrimitives`, 3 cases: `capture_identity_records_verified_windows_venv_resolution`, `handle_scoped_command_check_accepts_only_current_venv_resolution`, `managed_command_accepts_only_current_windows_venv_base_resolution`
  - Skip reason: no Windows venv redirector on the runner.
- `test_live_path_security.py::test_live_launcher_lineage_accepts_real_windows_venv_redirector`
  - Skip reason: no venv redirector.
- `test_international_live_session_launcher_sealer.py::test_forced_outer_launcher_exit_kills_session_runner_tree`
  - Skip reason: no Windows venv layout.
- `test_exchange_economics_refresh_script.py`, 3 cases: `a_killed_run_leaves_a_running_marker…`, `collector_failure_records_exit_code…`, `successful_collection_records_pass`
  - Skip reason: needs a venv interpreter to clone.
- `test_bulk_cold_archive_crypt.py`, 2 cases: `native_complete_restore_after_local_originals_are_removed`, `native_new_client_file_copy_filter_and_restore`
  - Skip reason: needs an installed rclone.
- `test_production_cold_archive_stage.py::test_production_source_pin_has_no_portable_fallback`
  - Skipped on the runner.
- `test_mm_credential_import_cli.py`, 2 POSIX-fallback cases
  - These are POSIX-only, so the host never runs them either. They are listed for completeness.

**Failed on the lane in an evidence run: 1 case**
- `test_replay_cache_compression_wrapper.py::test_abrupt_wrapper_exit_kills_entire_owned_tree`
  - It failed on 4 of the last 6 master runs (a 4 s hard stop raced the fixture).
  - Draft PR #284 fixes it. Keep it on the host until the fix has several consecutive green lane runs.

**Not in every evidence run (new files): 13 cases**
- `test_dst_audit_lows_20261011.py`: 10 cases.
- `test_dst_audit_suite_20261011.py`: 3 cases.
- They passed in the two later runs but did not exist yet in the first. They become DROP after one more green run if the rule is applied again.

## Preconditions if the owner adopts it
1. On the **exact SHA** being merged, the Windows Qualification run must be `success` on all 13 shards and CI (Linux) must be `success`. Older runs do not count.
2. Regenerate the DROP set from **that run's** JUnit with the same rule. Never reuse this file's list blindly: shard membership drifts, and `test_windows_qualification_shards.py` guards only the file names.
3. Implement it as a per-test deselect list that the bounded suite reads, with fail-closed behaviour: if the list is missing or stale, run everything. Do not implement it as a file drop.
4. Gaps the Windows lane does not cover, which are reasons a host smoke still matters:
   - The S4U/Scheduler principal and the real `Global\` mutex.
   - Host commit and disk pressure.
   - The host's own Python build: the lane uses 3.11.0, and the host is mid python-upgrade.
   - The host's venv redirector, which is why the venv cases above are skipped on the runner.
   - The S4U smoke is not replaced.

## Expected saving
The DROP cases took about 2,716 s of runner time in run 38367397542. Host timings will differ, so treat this only as an order of magnitude: roughly 45 min of the native-launch-heavy work in the host suite.
