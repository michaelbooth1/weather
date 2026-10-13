# Proposal: land roll-free heads on workstation pre-gate plus Windows CI, without the host bounded suite

Status: **DRAFT proposal, not in force.** Dated 2026-10-13. It is for master-agent review and an owner decision.
It changes nothing by itself. [HOST_LOAD_POLICY](../../operations/HOST_LOAD_POLICY.md), the
[integration attempt runbook](../../operations/INTEGRATION_ATTEMPT_RUNBOOK.md),
`scripts/ops/bounded_worktree_test_suite.ps1` and the production acceptance contract in
[development.md](../../development.md) all stay as they are until a reviewed change lands there.

Read when: deciding the owner question below, or building the tooling it needs (section 6). This proposal
builds on the not-in-force [host-suite shrink proposal](../../development.md#proposal-shrink-the-host-suite-once-the-windows-lane-is-green-not-in-force)
(N4, PR #262) and goes one step further for roll-free heads.

## 1. The owner question

> After host Python cutover C (2026-10-17 00:30) has succeeded and has not been rolled back, may a
> **roll-free** integration head land without the host bounded suite?
>
> Roll-free means `scripts\ops\roll_verdict.ps1 -Branch <b>` exits **0** on the host. Exit 2 does not count.
>
> The head lands through `scripts\ops\quiet_window_merge.ps1` inside 00:30–12:00 when all of the following hold:
>
> 1. **Pre-gate.** A workstation pre-gate receipt (`weather.workstation_pregate_receipt.v1`) is `PASS` for the exact tip. The receipt's SHA-256 is recorded in that night's hashed plan.
> 2. **Ancestry.** `origin/master` at merge time is an ancestor of the tip, so the merged tree equals the tree that was tested.
> 3. **CI.** `CI` and `Windows Qualification` (CPython 3.11.9) concluded `success` on the exact tip, with every `native-launch` shard successful.
> 4. **Host residual set** (option A only). The small host residual set (section 5) passes on the host at the exact tip.
>
> Every other gate stays unchanged: roll verdict, guarded merge, recovery proof, `WeatherOneShotPush`, documentation transaction, actual-host S4U smoke. Roll-sensitive heads keep the full host suite.
>
> **A (recommended):** yes, with the host residual set.
> **B:** yes, without it.
> **C:** no; every head keeps the host bounded suite.

If any check fails, the head falls back to today's suite-gated integration attempt. Nothing is ever forced.

## 2. What the rules say today

- The integration attempt binds "one full suite" per head, and its merge task requires the suite's PASS receipt ([runbook](../../operations/INTEGRATION_ATTEMPT_RUNBOOK.md), state machine).
- The [landing preflight](../../operations/LANDING_PREFLIGHT.md) says that "the bounded suite stays the host's test gate".
- Testing decision (owner 2026-10-04, PR #205; [STATE_OF_PLAY](../../operations/STATE_OF_PLAY.md)):
  - Focused and affected tests, with PR CI as full-suite evidence.
  - Every night head is pre-gated on its stacked base.
  - "host-only behaviour (3.11.0 stdlib) needs a host run".
  - This proposal follows from that last clause: after cutover C the 3.11.0 stdlib is gone from the host.
- `quiet_window_merge.ps1` itself does not require a suite. A ROLL-FREE branch may run there 00:30–12:00.

**Practice already diverges from the written contract.** Several roll-free code heads landed by guarded merge minutes after the previous merge. That is too soon for an exact-tip host bounded suite to have run; the workstation pre-gate alone takes about 50 minutes. Examples:

- `1e0e84793`: wallet-reader any-LAN, 11 files including `src/weather/market/*`. It landed 6 minutes after the previous merge.
- `ac24b9941`: wallet-reader HTTPError close, `src/` plus a test. It landed 1 minute after the previous merge.

Master should confirm from its receipts. If confirmed, this proposal makes the existing practice explicit, attested and conditional.

## 3. Evidence: host bounded suite against workstation pre-gate, N2–N9 (2026-10-07..10-13)

Sources:
- 42 pre-gate receipts under the workstation's `l-data\n*heads\pregate\`.
- Master merge history.
- The workstation state log of master's night reports.

This covers test outcomes only; no market or panel data was read.

| Outcome | Count | Heads | Cause |
| --- | ---: | --- | --- |
| Pre-gate PASS at the exact tip; the host suite passed and the head landed | 16 | rs1b `012cbc872`, rf2e `b7b8b7ebb` (N2); rsa `859df38b6`, h1 `e83194bcf`, 258 `3c95a3226` (N3); 268-nors `d3e7aecc1`, econ-nors `30cb279b9` (N4); rs-v2 `f8499d0bd`, rsb-v2 `ee41a90e8`, rf-v2 `c9029029a` (N5); N6 `9b9501806`; N7 `a36798574`; N8 rs `c6977df5f`, rf2 `1c64f9173`; plus `247fu-nors` `3e911b225`, contained in the pre-gated 268-nors | agreement |
| **Pre-gate PASS, host suite FAIL** | **2** | N3 RF-B `441cfbcfe`; N4 RS `dfce75ff2` | Both are **CPython 3.11.0 gh-98778**: `HTTPError(fp=None)` raises `KeyError 'file'` through `traceback` reading `__notes__` (PR #259). The workstation runs 3.11.9, where this is fixed. **This class disappears at cutover C.** |
| Host suite FAIL with no workstation pre-gate | 1 | N3 #261, assembled by master | (a) The repo-wide hygiene ratchet `ps1_substring_without_execution`. Platform-independent, so any full pre-gate or CI would catch it. (b) A fanout `PermissionError` (Windows delete-pending), already in the known Windows flake table in development.md. |
| Pre-gate FAIL, fixed before the host saw it | 4 | rs1 `69e9ea988` (Guards lines), rf2d `feb42229b` (stale string; doc names a module not yet landed), H1 `ad2ab569c` (research inventory) | All are platform-independent ratchets. The workstation is the earlier gate. |
| Pre-gate FAIL, host suite PASS | 0 | | No case where the workstation was stricter by accident. |

**Bottom line.** Every case where the host caught something the workstation missed was the 3.11.0 interpreter. No failure was due to host paths, Scheduler, S4U, Defender or git.

The pre-gate is not a different suite. It replays the host suite's own statements from its AST: the same chunk plan, Job containment, environment scrubbing and `C:\pt` basetemp ([development.md](../../development.md#workstation-pre-gate-before-a-host-landing-slot)). It replaces only the window, the hard stop, the host lease and `Assert-HostAdmission`.

**Caveats:**
- The sample is small: 7 nights.
- The host suite's own JUnit was not available to the workstation. Host outcomes come from master's reports and from merge history (a landed attempt implies a PASS suite receipt).
- Master should attach its `data/integration_attempts/*/suite` verdict lines for the 16 heads to close this gap.

## 4. Host-only behaviour after cutover C, and what covers it

| Host-only property | Still different after C? | Coverage under this proposal |
| --- | --- | --- |
| CPython patch level (3.11.0 vs 3.11.9) | **No.** Host, workstation venv (`pyvenv.cfg` 3.11.9) and the repinned Windows lane (#274) all run 3.11.9. | Closed. Gap: the pre-gate receipt does not record the interpreter or dependency set; tooling T1 adds a freeze hash for the host to compare. |
| Third-party packages | Possibly. The host venv is rebuilt from the lock at C; the workstation venv may drift. | T1: the host compares freeze hashes. On a mismatch the head takes the suite path. |
| Git (host 2.45.2; workstation 2.54; runner latest) | Yes | The integration merge itself runs on the host inside `quiet_window_merge.ps1` (a conflict refuses). Master's host-git-2.45 chain sim is unchanged. Tests whose result depends on git semantics are in the residual set (section 5). |
| S4U logon (session 0, non-interactive window station, no network credentials) | Yes. Neither the pre-gate nor CI reproduces it. | (i) The actual-host S4U smoke is unchanged. (ii) Every night with a roll-sensitive head still runs the full host suite under S4U, on a tip that contains every earlier roll-free landing. That is a standing lagging canary. (iii) No S4U-only failure appears in the evidence. |
| Host paths (production checkout under the owner profile, worktree roots, MAX_PATH) | Yes | Both suites use the short `C:\pt` basetemp. Path-dependent tests are hermetic. No path failure appears in the evidence. |
| Defender real-time scanning and exclusions | Yes (per machine) | Shows up as `PermissionError` or timeout flakes, which are false failures, not missed defects. Dropping a host run removes a source of false FAILs. |
| Machine tools and privileges (rclone, pwsh, symlink privilege) | Yes | The workstation skips 62 tests on `48becd401`: 14 symlink-privilege, 15 "outer workstation lease owns mutex" (admission tests), 4 "pwsh is unavailable", 8 opt-in rclone, 12 RE1 fixture-only, 6 DST known-bug, 1 Ctrl+C runner, plus pyinstrument. The Windows lane runs the privilege and admission ones (hosted runners are admin, with no outer lease), which is why requirement 3 is CI **plus** pre-gate, not either alone. The admission tests are also in the residual set. |
| Capture-host identity (MachineGuid vs `dedicated_capture_execution_host_id`) | Yes | Tests take the identity from fixtures. The admission and hook files that exercise the capture-host branch are in the residual set. |
| Host load (16 GB, commit ceiling, live capture) | Yes | This affects timing flakes, not correctness. It is a reason to run less on the host. |

## 5. The host residual set (option A)

These are the files whose outcome depends on the host itself rather than on Windows. They extend the #262 list:

- `tests/operations/test_quiet_window_merge_script.py`
- `tests/operations/test_quiet_window_merge_execution.py`
- `tests/operations/test_suite_gated_quiet_merge_script.py`
- `tests/operations/test_reconcile_ordinary_quiet_merge.py`
- `tests/operations/test_integration_attempt_scripts.py`
- `tests/operations/test_workload_admission_script.py`
- `tests/operations/test_workload_admission_service_allowlist.py`

That is 7 files, within the 25-file focused cap. They run once per roll-free head at the exact tip:
- inside 00:30–09:00;
- holding the shared lease;
- serially, as a bounded run (tooling T4).

They replace a ~50-minute full suite with a run of a few minutes. The reconciler execution file keeps its L5 rule unchanged: when its surface is touched, the head takes the suite path.

## 6. Tooling needed before the first attested landing

Each item is a separate reviewed branch. None of them registers a task.

- **T1. Pre-gate receipt identity.** `workstation_pregate.ps1` records the interpreter version and the SHA-256 of `python -m pip freeze --all` (sorted, LF) in the receipt. The host verifier compares the freeze hash with the production venv. A mismatch takes the suite path.
- **T2. CI on the exact integration-head SHA.** Today integration heads get no CI: both workflows trigger only on `pull_request` and `push: master`, and `gh run list --commit 48becd401…` is empty. There are two ways to fix this:
  - Open a draft PR per head. This works today with no code change.
  - Add `push: branches: ['claude/integration-*', 'codex/integration-*']` to both workflows. This is a roll-free `.github/` change.

  `Windows Qualification` already checks out `pull_request.head.sha || github.sha`. A red, cancelled or missing shard means the suite path, or a same-SHA rerun.
- **T2a. A green Windows lane is a precondition, not a given.**
  - On `master`, 7 of the 10 most recent Windows Qualification runs did not succeed (2026-10-11..13): 5 failed and 2 were cancelled. All 8 failed master runs inspected since 10-11 failed on the same test: `tests/operations/test_replay_cache_compression_wrapper.py::test_abrupt_wrapper_exit_kills_entire_owned_tree` ("fixture did not launch owned descendants"), in the `status-rest` shard.
  - The 3.11.9 repin run (#274) failed the same test, plus once `test_production_baseline_reconciler_execution.py::test_persistent_stop_failure_keeps_lease_and_never_reports_terminal` (`reconciler-5`). That test was not seen failing on master's recent runs; a same-SHA rerun decides whether it is a flake.
  - Requirement 3 is unusable while one shard is red on most runs. That test must be fixed, or quarantined under the staged-cut rules, before the first attested landing.
- **T3. Host verifier** (`scripts/ops/assert_roll_free_attestation.ps1`, read-only). It writes an immutable attestation receipt and checks:
  - the exact tip;
  - `roll_verdict.ps1` exit 0;
  - `origin/master` is an ancestor of the tip;
  - the plan hash, and that the receipt's SHA-256 matches the plan;
  - receipt `verdict == PASS`, `head == tip`, the log SHA-256, and `host_suite_sha256` equal to the tip's own `bounded_worktree_test_suite.ps1` blob;
  - the T1 freeze hash;
  - check runs for the tip from the public GitHub REST API. The repository is public, so no credential is read or stored.

  The receipt travels on `claude/night-plans` beside the plan, as today. Only the hash is binding.
- **T4. Residual run.** Either a `-OnlyFiles` mode for the bounded suite (frozen list, same containment, verdict `RESIDUAL n/n PASSED`, never `ALL CHUNKS PASSED`), or a focused run under `workload_admission.ps1`.
- **T5. Plan and generator.** Slots get `landing_path: RF_ATTESTED` and a `ci` block. The night-command generator (`tools/night_sequencer_commands.py`, separate branch) emits the verifier, residual and merge commands for those slots.
- **Docs, when adopted.**
  - HOST_LOAD_POLICY: a new rule 11.
  - INTEGRATION_ATTEMPT_RUNBOOK: an attested roll-free path beside the state machine.
  - development.md: the acceptance contract.
  - LANDING_PREFLIGHT: the composition table row.
  - STATE_OF_PLAY: the testing line.

## 7. What it buys

- On N5, consecutive suite-gated units landed about 50 minutes apart (01:26, 02:17, 03:09).
- Host rule 8 plans 2 roll-sensitive + 5 roll-free heads per night. The 5 roll-free suites are roughly 4 hours of the 00:30–09:00 lease.
- Under option A each roll-free unit costs a few minutes of residual run, a 60 s settle (rule 10) and the push.
- The night becomes bound by its roll-sensitive heads. The lease time freed can carry a third RS head, or the tiering reserve without a skip.
- Pre-gates stay serial on the workstation's FIFO queue and are already on the critical path the day before. Nothing moves to the host.

## 8. Risks and their bounds

- **A host-only defect lands in a roll-free head.**
  - Bounded by the roll class: nothing a capture loop imports changes, so the fleet cannot roll.
  - The guarded merge still proves recovery.
  - The next RS suite on the host re-tests that tree under S4U.
  - The rollback is an ordinary revert branch.
  - Review after 14 attested landings. Any host-only regression found later reverts the rule to option C.
- **Stale attestation.** The ancestry rule (requirement 2) makes the merged tree identical to the tested tree. A master that moved in between, even by a docs light path, voids the attestation, and the head is rebuilt or takes the suite path. This is OD35's base binding, made exact.
- **CI flake masking.** Only `success` on every required job counts. A same-SHA rerun is allowed and is recorded in the attestation.
- **Scope creep.** Roll-sensitive heads, schema-registry changes (always RS), 88a changes, and the DST night 2026-11-01 (OD30, 05-F3) are untouched.

## 9. Not in this proposal

It does not change any of these:
- the suite for roll-sensitive heads;
- the docs light path;
- the window rules;
- the S4U guard;
- `MaxFilesPerChunk`;
- the 50 GiB disk floor;
- who signs the merge queue.

It also does not authorize any task registration or live action.
