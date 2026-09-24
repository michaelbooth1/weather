# Mission 91a — resumed workstation verification

**WORKSTATION VERIFICATION PASS; production qualification remains owed.** This follows,
without rewriting, the published
[initial 91a report](agent-report-2026-09-91a-closed-day-compression-at-scale.md).
The owner confirmed on 2026-09-24 that RE-1 was stopped and explicitly asked
to resume 91a testing and push its branch. No production registration or run
is part of that request.

Branch `codex/closed-day-compression-20260924`, implementation under test
`07cc2987f4c292415d5035ba866afdf648d79387`, unchanged from the prior published
draft; base `198f7ccbcd8e80271693462425582097d22b298b`. The worktree was clean at
intake. Testing used the non-capture workstation `DESKTOP-RFCD2GH` and the
repository-owned `workstation_heavy.ps1` wrapper, which admitted the exact
host/principal and held the shared mutex and kill-on-close Job. No process,
lease, poison marker or guard was bypassed or cleared manually.

## Results

Focused synthetic regression: **229 passed, 1 skipped in 67.22 seconds**.
The native >64-MiB fixture passed, including streaming preimage/postimage
SHA-256, unchanged logical size, positive verified allocation savings and
refusal while a writer held the file. Budget stop, hot-day refusal, failed
hash/identity handling, failure stop, expiring policy, source binding and
wrapper teardown are covered by the focused regression. This corrects the
initial report's then-true statement that native verification had not run.

The test payload was:

```text
-m pytest tests/operations/test_cold_snapshot_nightly.py
tests/operations/test_cold_snapshot_compression.py
tests/operations/test_cold_snapshot_compression_wrapper.py
tests/operations/test_storage_recovery_inventory.py
tests/operations/test_replay_cache_compression.py
tests/operations/test_schema_registry.py
tests/operations/test_import_architecture.py -q --basetemp <owned-absolute-directory>
```

Full regression payload: `-m pytest -q --basetemp <owned-absolute-directory>
--junitxml scratch/91a-full.xml`. Both payloads are passed as UTF-8 JSON-array
base64 to `workstation_heavy.ps1 -Kind pytest`, using the project interpreter
and the absolute branch worktree as `-RepoRoot`. This is the workstation
exception in [development](../development.md#separate-non-capture-workstation),
not a direct capture-host suite. Production must use its admitted bounded
suite and owning runbook when qualifying adoption.

Full regression completed: **5,853 passed, 34 skipped, 923 subtests passed,
zero failures/errors in 2,805.24 seconds (46m45s)**. JUnit counts the subtests
separately within its 6,810 total. Skips comprise 12 unavailable symlink
fixtures, eight explicit native-rclone prerequisites, eleven lease-acquisition
tests that correctly skip under the outer workstation mutex, and three
platform-specific cases. The sole warning is a NumPy ndarray-size binary
compatibility warning while reading the cached netCDF4 fixture; that test
passed. No checks were disabled or source changed to obtain this result.

`-m compileall -q app src tests` passed under the same workstation wrapper.
The agent documentation audit passed (18 agent files, 921 Markdown files),
and roadmap backlog `--fail-on-lint --check` and `git diff --check` passed.
The owned pytest fixture directories are removed after completion; no
retained evidence or other task's temporary directory is a cleanup target.

Local retained receipts under this worktree (SHA-256):

- `scratch/91a-full.xml`:
  `f8bb321cbb253d92f7aa4cc28da235d6ae62f14d47e345f80de049c16d50b61f`
- `scratch/91a-full.log`:
  `36fc77547365c1fb7305a141ce89a2c28b16a248634696e32fa3af36ee3821dc`

These are local verification receipts, not assumed present on a clean
production checkout. The commands above reproduce the workstation checks;
production qualification follows its own admitted bounded suite.

## Deployment disposition

The implementation remains a separate nightly consumer. The original
attended thirty-day/64-MiB/600-second defaults remain intact. Nightly mode
admits event days strictly older than fourteen days and files unchanged for
fourteen days; maximum 256 MiB/file, 1 GiB/batch, 32 GiB/night. Source-close
compression and mm_runs retention remain documented designs, not implemented
capture mutations. No production savings were measured. The initial 2x/3x
capacity scenarios of 16–21.3 GiB/night remain hypothetical; gzip ratios do
not prove NTFS ratios.

Production must obtain its current per-file verdict with
`scripts/ops/roll_verdict.ps1 -Branch codex/closed-day-compression-20260924`.
The two schema registrations are additive-only but enter the registry family
in the retained capture closures, so treat this as roll-sensitive pending
that verdict. The initial report's per-file disposition still applies;
this new report is Markdown and roll-free. No frozen-mirror closure was used
as production authority.

After guarded integration and production qualification, the production owner
creates an expiring hash-bound policy, performs the documented bounded dry
run and low-budget apply, then registers:

```powershell
& .\scripts\ops\register_cold_snapshot_nightly.ps1 `
  -ProductionRepoRoot $productionRepo `
  -RequestPath $approvedPolicyPath -RequestSha256 $approvedPolicySha256 `
  -ExpectedSourceTip $reviewedSourceTip -Apply
```

These values must be the real production paths, policy hash and reviewed
tip; they are not copied from workstation scratch. The
[owning runbook](../operations/cold-snapshot-compression.md#nightly-automatic-selection)
defines the policy and registration. This task did not execute that command.

No production or mirror access, real evidence compression/deletion,
credential access, RE-1 campaign access by this test lane, venue call,
Scheduler mutation, capture restart, live command, merge or promotion occurred.
Synthetic files were the only compressed bytes. No empirical date/market
inference is involved in storage verification.
