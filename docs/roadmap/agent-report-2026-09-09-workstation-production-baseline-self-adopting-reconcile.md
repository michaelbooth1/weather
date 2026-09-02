# Workstation production-baseline self-adopting reconciliation report

**Verdict: PASS_WITH_PRODUCTION_HANDOFF.** The implementation safety tip is
frozen, all workstation gates are green, and the remaining production work is
the separately authorized action-time handoff below. The report-only successor
commit, its tree, and exact remote topic equality are necessarily supplied in
the final handback because this report cannot contain its own commit identity.

The three NO-GO boundaries in the 2026-09-08 report are closed in the retained
candidate:

1. the synthetic merge is now `M=[C,S]`, where safety tip `S` strictly
   descends from published target `T`, so the newly adopted status/watchdog
   behavior owns the first unpublished state;
2. every reconciliation ScheduledTasks operation is inside a hash-pinned,
   kill-on-close child RPC with an immutable request deadline inside both
   PT15M and 04:00; and
3. the assigned non-capture workstation and attending principal were proved
   with the repository's canonical hashed-identity functions, and the focused
   executable gates recorded below passed through the workstation wrapper.

No production checkout, production data, real scheduled task, credential,
provider, exchange, PR #9, or PR #7 was touched. `WeatherOneShotPush` was not
invoked. The future command in this report is a handoff template only and was
not executed.

## PR #10 exact-head CI repair follow-up (2026-09-02)

PR #10 CI at exact report tip
`1354e063eba13ea0f57bedb591004eb2073b1232` ended with `2 failed, 4173
passed, 246 skipped, 1 warning, 860 subtests`. Both failures required Git
objects that the default one-commit `actions/checkout` clone did not contain:

- production baseline `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`; and
- published target `c932b54f8747df5cdefc4cc42f8454b6797f09ae`.

The exact CI repair commit is
`3ff0e69cc3d1f88f39659cb2a72d4a3e3bb6ed31`, tree
`b4d74884208dfd29cac52dfb7cc9bd36fb0d72f8`, with sole parent
`1354e063eba13ea0f57bedb591004eb2073b1232`. Its only changed file is
`.github/workflows/ci.yml`: the existing checkout step now sets
`fetch-depth: 0` and retains `lfs: false`. No test was skipped, weakened,
mocked, xfailed, or conditionally bypassed. No reconciliation or production
code changed. Exact-head GitHub CI remains a separate production-side
verification gate.

| Repair verification | Result |
| --- | --- |
| Two exact CI failures | **PASS**, `2 passed in 0.33s` |
| Complete affected `test_production_baseline_reconciliation.py` | **PASS**, `17 passed in 61.28s (0:01:01)` |
| Complete repository pytest, default temp | **DIAGNOSTIC**, `13 failed, 4386 passed, 22 skipped, 13 warnings, 862 subtests passed in 2743.91s (0:45:43)`; all failures were Windows MAX_PATH artifacts in `test_experiment_executor.py` |
| Complete repository pytest, shorter `C:\tmp` base | **DIAGNOSTIC**, `12 failed, 4387 passed, 22 skipped, 13 warnings, 862 subtests passed in 2651.55s (0:44:11)`; all failures were the same MAX_PATH artifact |
| Complete path-sensitive executor file with documented extended-prefix temp mode | **PASS**, `24 passed in 3.04s` |
| `compileall -q app src tests` | **PASS** through `workstation_heavy.ps1` |
| Agent-document audit | **PASS**, 18 agent files / 830 Markdown files |
| Roadmap lint/generated-view check | **PASS**, generated report matches sources |
| Cumulative `git diff --check` | **PASS** |

The two complete-suite invocations were allowed to finish and are reported
honestly rather than relabelled green. Their only failures reproduced the
report's pre-existing Windows path-length diagnostic: the longest normal-path
atomic-write target is exactly 260 characters while this workstation has
`LongPathsEnabled=0`. The entire affected file passes with the already
documented extended-prefix mode. This local filesystem diagnostic is separate
from the Linux exact-head CI failure that the checkout-depth change repairs.

## Immutable mission and result identity

| Item | Exact value |
| --- | --- |
| Reviewed parent branch | `origin/codex/workstation-production-baseline-synthetic-reconcile-2026-09-84a` |
| Reviewed parent tip | `a24cf0f41bf0b321c5c813820594c56198a58d1a` |
| Reviewed parent tree | `e0a32bb543885fbec9db611d6fec45b5a35ffcc5` |
| Result branch | `codex/workstation-production-baseline-self-adopting-reconcile-2026-09-85a` |
| Final implementation safety tip `S` | `a4619c67a8b7ab8b63d64f773a33e93f08864486` |
| Final implementation tree | `b7a2364655977624713e0bd87110a05e93df5d19` |
| Safety-tip entry SHA-256 | `b896f0ae4387ab10bb72dbea304cebda8d53bfce12814d24b544e50efc40af75` |
| Canonical `L -> S` roll result | `UNDECIDABLE`, exit `1`: four live closure snapshots absent; fail-closed **ROLL-SENSITIVE**, fixed 01:00-04:00 |
| Canonical origin | `https://github.com/michaelbooth1/weather.git` |

`F` is intentionally a report-only successor to `S`. A commit cannot contain
its own object ID or final tree, so the final handback supplies exact `F`, its
tree, proof that `S..F` contains only this report, and local/remote topic-tip
equality after push. No identity may be inferred or abbreviated.

## Frozen production and adopted-byte identities

| Item | Exact value |
| --- | --- |
| Production local baseline `L` | `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac` |
| `L` tree | `5281cd8ebff233e576a0b21d138a892c8c6c956c` |
| Published target `T` | `c932b54f8747df5cdefc4cc42f8454b6797f09ae` |
| `T` tree | `6df5bac16d8c780c35b4601941eaca1137ea7070` |
| `config/location_market_events.json` tracked blob at `L` and `T` | `189151516a47166f69c64ad0b9612466614a7fbb` |
| `config/locations.json` tracked blob at `L` and `T` | `dcc595e2a0cbe73e8d4d67a30aab4def1176ee06` |
| Adopted `scripts/ops/boot_recovery.ps1` Git blob | `8465de619d7c88fded5144d8903595fb4f8cc93a` |
| Adopted boot SHA-256 | `253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a` |
| Reviewed `WeatherOneShotPush` task XML SHA-256 | `8dc106989f176abfd1a21be0951cdfa325ffb5d5400e20e39c6978a10785dd05` |

The two production-generated config contents were not accessed from the
workstation and therefore have no workstation-invented object IDs. At future
execution, their exact raw bytes and SHA-256 values are captured before any
marker or Git mutation, placed in the immutable snapshot, and become the only
tree differences contributed by future config child `C` and merge `M`.

## P0 workstation host/principal qualification

The qualification used `Get-WeatherExecutionHostId` and
`Get-WeatherExecutionPrincipalId` from
`scripts/ops/workload_admission.ps1`. Only hashes were emitted; raw
`MachineGuid`, SID, and principal material were not exposed.

| Proof | Observed | Tracked assignment | Result |
| --- | --- | --- | --- |
| Execution host ID | `a740ee7dc03165b0c88094f8b313aa6676f0984b30737ec5bcd9f723709fe5dc` | `a740ee7dc03165b0c88094f8b313aa6676f0984b30737ec5bcd9f723709fe5dc` | **PASS** |
| Execution principal ID | `899c8218f19e948baf648733e34ab9e3301c154300a30477816ed749c3c8507b` | `899c8218f19e948baf648733e34ab9e3301c154300a30477816ed749c3c8507b` | **PASS** |
| Dedicated capture host ID | `6a085bc0e2017a1a619eead39f9daa9ffe0822b9add353d94cf2c06acb8889a7` | different from observed host | **PASS** |
| Physical memory | `33,475,698,688` bytes (`31.177 GiB`) | assigned 32 GB workstation class | **PASS** |

This is the separate non-capture workstation. The production capture-host
12:00-18:00 restriction did not apply, but every Python test command used
`scripts/ops/workstation_heavy.ps1`, its host/principal admission, shared
host-global mutex, and kill-on-close Job ownership.

## Repair 1: reconciliation-aware status and watchdog

The adopted `status.ps1` now recognizes an incident-bound publication only
after proving the complete marker/snapshot/report topology, including:

- exact operation mode and active-marker schema;
- `expected_tip`, `resolved_branch_tip`, `reconciliation_source_tip`, and
  `reconciliation_safety_tip` all equal exact `S`;
- local baseline `L`, published target `T`, exact merge `M`, and exact ordered
  parents `[C,S]`;
- strict `T<S`, exact `C=child(L)`, and exactly the two allowed config paths;
- marker, immutable snapshot, roll-verdict, documentation-transaction,
  Scheduler-RPC request, task XML, entry, and dependency hashes;
- exact local HEAD/`master` and canonical live-origin acknowledgement; and
- phase, timestamp chronology, freshness, capture-recovery, stop-count, and
  terminal-proof invariants.

For a completely validated pre-dispatch marker, cached and live canonical
origin must still be exact `T`; status says guarded reconciliation owns
publication and explicitly forbids manual invocation. Once
`push_invocation_attempted=true` is durable, cached/live origin may still be
`T` or may already be `M`; status reports pending/uncertain publication and
explicitly forbids retry in either case. Only a published marker with exact
local, cached, and live canonical `origin/master==M` acknowledgement suppresses
the unpublished warning.

Only a proved `ItemNotFound` marker lookup leaves ordinary quiet-merge guidance
unchanged. Malformed, stale, colliding, unreadable, lookup-failed, reparse, or
mismatched evidence is `incident_evidence_invalid`: status preserves the
evidence, requires review, and emits no `run WeatherOneShotPush` instruction.
Invalid evidence counts from cached `origin/master`, not an unfetched live SHA;
an unreadable comparison emits a neutral warning rather than a false zero. The
incident cannot be relabelled into generic retry authority.

`health_watchdog.ps1` preserves every reconciliation publication state as a
HIGH-severity incident note. Its action is preserve/review/do-not-invoke; it
does not turn pre-dispatch, attempted, uncertain, exhausted, or invalid
evidence into another push instruction.

## Repair 2: absolute Scheduler-RPC containment

Reconciliation has no synchronous ScheduledTasks call in the parent. The
separate `production_baseline_scheduler_rpc.ps1` owns the only allowed helper
surface:

- `ReadExecutionTapeTask` uses exact singleton `Get-ScheduledTask`;
- `ReadPushSnapshot` uses exact `Get-ScheduledTask`,
  `Export-ScheduledTask -InputObject`, and
  `Get-ScheduledTaskInfo -InputObject`;
- `StartPush` uses `Start-ScheduledTask -InputObject`; and
- `StopPush` uses `Stop-ScheduledTask -InputObject` for fixed ordinal one or
  two.

The helper contains no register, replace, edit, enable, disable, delete, or
credential surface. It validates strict canonical JSON, exact repo/marker/task
identity, exact static XML/principal/action/settings, current runtime evidence,
fixed property sets, and an immutable UTC deadline. Results are exclusive,
bounded structured evidence that the parent independently revalidates.

Each call is launched in the repository kill-on-close Windows Job. The parent
recomputes time immediately before the blocking wait, clamps both wait and
termination proof to immutable UTC bounds, closes the complete helper tree
even if the root exits normally, and places the helper request deadline exactly
eight seconds inside the logical boundary: five clamped seconds for complete
`TerminateAndWait` proof and three seconds for bounded result parsing. The
safety-tip helper SHA-256 is rechecked at every RPC call boundary, so mutable
source-worktree drift cannot acquire Scheduler authority.

Start authority and Stop ordinals use fixed durable `FileMode.CreateNew`
claims plus `Flush(true)`. The parent journals
`push_invocation_attempted=true` and the Start request identity before the sole
Start helper. Creation/flush is followed by one immediate deadline recheck; a
claim that consumes its request budget is spent/unknown and performs no
Scheduler dispatch. A claim collision, helper timeout, killed tree, thrown
cmdlet, generic failed response, or lost response permanently spends that
authority. After a claim, caught
evidence records `mutation_authority_claimed=true` and
`mutation_dispatched=null`, never a false safe negative. Parent logic treats
that outcome as unknown/spent and never retries Start. Any Start helper error
prevents PASS and a published marker even when the task successfully publishes
`M` before returning the error.

Every post-Start Scheduler read before the first Stop claim is bounded to
`pushContainmentStopAt`, so a slow or hung read is killed without consuming the
full 30-second first-Stop reserve. If the Stop identity or request budget cannot
be created, Stop is exhausted locally with no false attempt, claim, dispatch,
or post-boundary marker. Stop remains capped at two distinct claims; an
uncertain Stop is terminal non-PASS, cannot consume the next ordinal, and the
lease/read-only drain continues until exact terminal proof or the absolute
report boundary.

Ordinary synchronized quiet merges retain their reviewed direct Scheduler
behavior. The child RPC and claims activate only under exact
`production_baseline_reconciliation_v0.1` inputs.

## Repair 3: exact self-adopting topology

The future transaction uses these meanings:

- `L`: frozen accepted production baseline;
- `T`: frozen published target and boot sentinel;
- `S`: final reviewed safety-patch tip, a strict descendant of `T`;
- `C`: exact one-parent config-only child of `L`; and
- `M`: exact synthetic merge with ordered parents `[C,S]`.

The implementation proves all of the following rather than inferring them:

1. canonical origin fetch and push URLs have no `pushurl`, refspec, or URL
   rewrite override;
2. live `origin/master` remains exactly `T` before dispatch;
3. `S` descends from the exact reviewed parent and strictly descends from `T`;
4. `C` has sole parent `L` and differs from `L` at exactly
   `config/location_market_events.json` and `config/locations.json`, with blobs
   made from the captured raw production bytes;
5. `M` has exactly ordered parents `[C,S]`, differs from `S` only at those two
   paths, and takes both config blobs from `C`;
6. `M` is a non-force descendant of `T` through `S`;
7. the working tree is otherwise clean and contains no other
   production-local byte; and
8. final PASS requires local HEAD/`master==M`, local `origin/master==M`, and a
   bounded live query proving canonical GitHub `refs/heads/master==M`.

Canonical roll classification is invoked exactly as:

```powershell
.\scripts\ops\roll_verdict.ps1 -Base 3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac -Branch a4619c67a8b7ab8b63d64f773a33e93f08864486 -JsonOut 'scratch\roll-verdict-S.json'
```

Every nonzero exit, unreadable/missing/stale payload, missing closure,
dormant-only closure, incomplete problem set, timestamp mismatch, or identity
mismatch is treated as roll-sensitive. The special mode is fixed to
01:00-04:00 even if the nominal verdict is roll-free. The exact workstation
invocation above exited `1` as `UNDECIDABLE`: these four non-production closure
files were absent, so the retained classification is fail-closed
**ROLL-SENSITIVE**:

- `data/snapshots/loop_supervisor_status.json`
- `data/snapshots/clob_loop_supervisor_status.json`
- `data/snapshots/observation_trigger_supervisor_status.json`
- `data/snapshots/clob_enrichment_status.json`

This missing-closure path exits before writing `JsonOut`; no
`scratch/roll-verdict-S.json` file was emitted, and no JSON classification was
invented or manually substituted.

Capture recovery is independently proved after the complete `S` tree is
staged and again immediately before publication. Conditional execution-tape
recovery is included when its task is active. Both proofs and their immutable
dependency/config identities remain in the marker, snapshot, and report.

## Adopted boot replay and marker/report compatibility

The exact adopted `L` boot bytes remain the recovery authority until `M`
adopts `S`. Precommit reconciliation phases deliberately keep every adopted
hard-reset predicate false. The implementation uses only `merge --abort` and
safe mixed restoration before commit; special-mode code contains no
`reset --hard` path.

After exact `M` exists, one atomic marker replacement exposes
`pre_merge_commit=C` while retaining expected/resolved/source/safety tip `S`,
local baseline `L`, published target `T`, merge `M`, and the complete committed
recovery predicate. Every later marker transition retains it. Uncertainty
after Start is preserved as published/unknown evidence and is never rolled
back.

The exact adopted-boot replay executes the frozen boot blob across:

- raw config snapshot before marker publication;
- preparation marker before `C`;
- `C` created;
- staged `S` with successful and failed `merge --abort`;
- `M` created before postcommit marker cutover;
- committed marker cutover;
- documentation publication;
- Start-attempt journal;
- Stop attempted and exhausted states;
- uncertain containment at the absolute boundary;
- canonical origin acknowledgement before published marker; and
- complete published state.

It asserts exact raw marker/config/evidence preservation, exact `[C,S]`
parents, strict `T<S`, and no fetch, push, `ls-remote`, or `reset --hard` from
boot recovery.

The existing `quiet_window_merge_in_progress_v0.1` marker schema remains
readable. Reconciliation fields are additive. The marker's
`auto_refreshed_sha256` and report's historical `rollback_content_sha256`
remain available, while both carry the normalized additive
`reconciliation_config_content_sha256` alias. Staged-safety and pre-push
capture proofs are distinct evidence; no old field is silently repurposed.

## Entry and dependency hash inventory

These are the exact bytes frozen in `S`. The entry row equals the command's
`ExpectedSelfSha256`; any byte change creates a different safety tip and voids
this handoff.

| Safety-tip file | SHA-256 | Git blob at `S` |
| --- | --- | --- |
| `scripts/ops/quiet_window_merge.ps1` | `b896f0ae4387ab10bb72dbea304cebda8d53bfce12814d24b544e50efc40af75` | `bab09bed87d84f751204e7bbbb23acedb57fffbe` |
| `scripts/ops/production_baseline_scheduler_rpc.ps1` | `e36a1045f02a9355ce85e61f5070150c864d9dcff4be705a51e23b9902bd8b64` | `9da520786385bcc34b99c205e4d768ca8bcc464c` |
| `scripts/ops/windows_kill_on_close_job.ps1` | `e910f4bcadd39a7b57413669fd75bcbff44b85aa46186c2f3324ec1a2ba36243` | `c80537802a8ccc9183158fec3b672a808a9d7dcf` |
| `scripts/ops/status.ps1` | `7b5d39fab90f225d4d72b46d4957f2d519efe1da3ee18f4cdc44ff623f3e345f` | `63a512b3af2dc27ecabcfe2d5e9743f712a5e80e` |
| `scripts/ops/health_watchdog.ps1` | `2d512dac921236222704988c1fae86535145e2a54d5cefad99781510b2e17d74` | `465d67adfbefc6a526dbf9ff90acff6e570e3f01` |

The immutable adopted dependency maps also bind:

| Dependency | Stage | Exact SHA-256 |
| --- | --- | --- |
| `scripts/ops/boot_recovery.ps1` | `L`, `T/S` | `253ab48e38a24af8cf8c8a5fde33f223b6e298b7acf91bbc56ad4c4a0ea8dc4a` |
| `scripts/ops/roll_verdict.ps1` | `L`, `T/S` | `3fb522a82c5325558a9da9d458c643edf5c0da8d5893e14189979859ed0a4881` |
| `scripts/ops/workload_admission.ps1` | `L` | `cdeaab38b2b9483cff5936e52411d725b0cffe4373ccebba688797c6e1d3c105` |
| `scripts/ops/workload_admission.ps1` | `T/S` | `4117eb901d292952473c57425434593bed414fa2ed2fecee301fe56e8f893306` |
| `src/weather/operations/capture_recovery_check.py` | `L`, `T/S` | `814ec274838e5cb905a0074298f5c4e27aee2d32b0b9cc6fac2ca4def27cc895` |
| `src/weather/operations/documentation_transaction.py` | `L`, `T/S` | `057def07c4ad8529457a11bba6b1f5afdb19b6f6011ff3dd77905af29bd354d9` |
| `src/weather/operations/execution_tape_supervisor.py` | `L`, `T/S` | `1f5d8e1130fa2dd4c14d8f8f9dd6c44d9a7c4850f85a5942919d5c6bbfc5763f` |

## Verification evidence

All Python test commands below used the accepted workstation profile through
`workstation_heavy.ps1`. Counts are per invocation and are not summed because
the selections overlap.

| Final-freeze gate | Result |
| --- | --- |
| P0 host/principal/RAM qualification | **PASS**; assigned non-capture host and attending principal matched |
| Marker lookup-denial plus genuine-ordinary/true-absence controls | **PASS**, `3 passed in 54.95s` |
| Complete status regression file | **PASS**, `74 passed in 581.12s (0:09:41)` |
| Complete reconciliation execution/adversarial file | **PASS**, `70 passed in 1503.70s (0:25:03)` |
| Integrated reconciliation/Scheduler/status/watchdog/quiet-merge/integration/recovery/boot matrix | **PASS**, `291 passed in 2237.54s (0:37:17)` |
| Complete repository pytest | **PASS**, `4399 passed, 22 skipped, 13 warnings, 862 subtests passed in 2750.65s (0:45:50)` |
| `compileall -q app src tests` | **PASS** through `workstation_heavy.ps1` |
| PowerShell AST parse of entry/helper/status/watchdog/Job | **PASS**, zero parser errors |
| `git diff --check` / staged implementation check | **PASS** |
| `python -m weather.operations.agent_docs_audit` | **PASS**, 18 agent files / 830 Markdown files |
| Roadmap lint/check | **PASS**, generated report matches sources |
| Exact `S`, tree, reviewed-parent ancestry, and strict `T<S` | **PASS** |
| Canonical `roll_verdict.ps1 -Base L -Branch S` | `UNDECIDABLE`, exit `1`; fail-closed **ROLL-SENSITIVE** |
| Independent read-only safety audits | **PASS**, no remaining must-fix finding after the final repairs |

Exact `F`, its tree, proof that `S..F` is report-only, and local/remote topic
equality cannot be contained inside `F`; they are supplied in the final
handback after push. Exact-head CI/review, synchronized action-time refs, live
closure evidence, and every production precondition remain requirements for
the future production attempt, not unfinished workstation gates.

### Superseded and diagnostic invocation ledger

The following results are retained for audit completeness but are not final-
freeze evidence:

- Earlier green selections later superseded by code or documentation changes:
  `68 passed` in the execution file; `71 passed` in helper/static ratchets;
  `3 passed` in the timing selection; `216 passed in 693.16s (0:11:33)` in the
  affected matrix; `69 passed in 1444.06s (0:24:04)` in the execution file;
  `101 passed in 584.78s (0:09:44)` across helper/status; and `5 passed in
  70.27s (0:01:10)` for the then-new claimed-error/deadline/origin cases.
- The earlier uninterrupted full repository suite was valid for its then-tree:
  `4392 passed, 22 skipped, 13 warnings, 862 subtests passed in 2497.75s
  (0:41:37)`. It was superseded by later safety repairs and the final 4,399-pass
  run above. Its compileall, AST, documentation, roadmap, and diff checks were
  likewise rerun after the repairs.
- The first default-temp complete-suite diagnostic ended `14 failed, 4378
  passed`: thirteen failures were Windows MAX_PATH artifacts and one was the
  architecture ratchet correctly seeing new critical files before they were
  staged. It is not behavioral gate evidence.
- A focused short-profile run with the default temp layout failed on path
  length, and a `C:\t` run still produced one exact 260-character path. Counts
  were not retained. A focused `\\?\` extended-prefix diagnostic passed 25
  tests, but the corresponding broad run was intentionally interrupted near
  27% after the prefix caused widespread path-identity failures. None is gate
  evidence.
- The first reserve-boundary test passed in about 158 seconds but its fixture
  did not exercise the intended edge. The corrected single case passed in
  `38.85s`; a corrected focused selection passed `3` tests with `66 deselected`
  in `182.74s`. Later integrated gates supersede both.
- One post-repair execution run ended `68 passed, 1 failed` because the
  `queued_after_start` expectation still assumed a read that the new Stop-
  reserve clamp correctly suppresses. The corrected run passed all 69 then-
  collected cases.
- The first five-case audit-repair selection ended `2 failed, 3 passed in
  70.54s`: one assertion assumed a topology-independent count of one, and one
  Windows PowerShell native-stderr probe terminated before classifying the
  expected unreadable ref. The corrected selection passed all five.
- A complete repository run was deliberately interrupted at 54% when review
  found the generic claimed-Start-error PASS hole. A later execution-file run
  was deliberately interrupted when review found that a marker lookup error
  could be mistaken for absence. Both are partial and not evidence.
- Sandboxed wrapper launches that reported host/principal mismatch, stale
  `ACTIVE` recovery refusals after those deliberate interruptions, and initial
  sandbox interpreter-launch failures for the docs/roadmap modules all occurred
  before the intended test/audit body. Exact approved retries proved zero
  residual heavy processes where applicable and produced the final results
  above; the refusals themselves carry no pytest result.

Any future byte drift, partial run, interruption, identity mismatch, or failed
action-time proof returns the handoff to NO-GO. A green branch does not itself
authorize production execution.

## Changed files

The implementation candidate changes:

- `docs/operations/ESTABLISHED_FINDINGS.md`
- `docs/operations/OPERATIONS_DESIGN.md`
- `docs/operations/STATE_OF_PLAY.md`
- `docs/ops/streak-soak.md`
- `scripts/ops/AGENTS.md`
- `scripts/ops/health_watchdog.ps1`
- `scripts/ops/production_baseline_scheduler_rpc.ps1`
- `scripts/ops/quiet_window_merge.ps1`
- `scripts/ops/status.ps1`
- `tests/operations/test_health_watchdog_script.py`
- `tests/operations/test_production_baseline_reconciler_execution.py`
- `tests/operations/test_production_baseline_reconciliation.py`
- `tests/operations/test_production_baseline_scheduler_rpc.py`
- `tests/operations/test_quiet_window_merge_script.py`
- `tests/operations/test_status_script.py`

The report-only successor adds:

- `docs/roadmap/agent-report-2026-09-09-workstation-production-baseline-self-adopting-reconcile.md`

PR #9 and PR #7 remain separate and unmerged.

## Prohibited-actions audit

- No production checkout, production `data/`, ignored production evidence, or
  dated production snapshot was accessed.
- No real scheduled task was started, stopped, registered, changed, enabled,
  disabled, deleted, or rebound.
- `WeatherOneShotPush` was not invoked; the owner's one future authorization
  was not consumed.
- No credential, raw host identity, or raw principal identity was read out or
  exported.
- No provider, exchange, live market, or trading endpoint was contacted.
- No training, replay, promotion, release, live order, or trade occurred.
- No production branch or `origin/master` was pushed. The only authorized
  outbound write after sealing this report is the isolated topic-branch push
  used for final handback.
- No `reset --hard`, stash, rebase, squash, force push, history rewrite,
  cherry-pick, or cleanup of user state occurred.

## Future production handoff command — not executed

After every action-time gate is green, the production operator must select an
isolated, clean, detached worktree whose exact HEAD is `S`, set `$sourceRoot`
from that worktree at invocation time, and run only during 01:00-04:00
America/Toronto. `$sourceRoot` is deliberately an action-time path operand,
not an immutable identity; its HEAD/tree/cleanliness and every pinned byte must
be independently re-proved immediately before launch. The production repo root
below is the exact action path attested by the reviewed Scheduled Task XML. This
complete command was **not executed** by the workstation:

```powershell
$sourceRoot = (Get-Location).Path
& (Join-Path $sourceRoot "scripts\ops\quiet_window_merge.ps1") `
  -Branch a4619c67a8b7ab8b63d64f773a33e93f08864486 `
  -ExpectedTip a4619c67a8b7ab8b63d64f773a33e93f08864486 `
  -ExpectedBaseline 3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac `
  -ProductionBaselineReconciliation `
  -ExpectedLocalBaseline 3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac `
  -ExpectedPublishedTarget c932b54f8747df5cdefc4cc42f8454b6797f09ae `
  -ExpectedSourceTip a4619c67a8b7ab8b63d64f773a33e93f08864486 `
  -ExpectedSourceTree b7a2364655977624713e0bd87110a05e93df5d19 `
  -ExpectedSelfSha256 b896f0ae4387ab10bb72dbea304cebda8d53bfce12814d24b544e50efc40af75 `
  -RepoRoot "C:\Users\micha\Desktop\github\weather" `
  -SettleSeconds 300 `
  -RollbackRecoverySeconds 1200
```

Do not add `-Force`, `-OwnerApprovedException`, `-AttemptReportPath`, or a
second invocation. Before launch, independently prove production HEAD/master
is exact `L`, local `origin/master` and live canonical GitHub master are exact
`T`, only the two approved generated configs are modified, source HEAD/tree is
exact `S`, the entry SHA-256 matches the command, the quiet window is open, and
the canonical action-time roll invocation has valid closure evidence. The
workstation result was exactly `UNDECIDABLE` with exit `1` because all four
required live closure snapshots were absent; it is therefore fail-closed
roll-sensitive and never relaxes the fixed 01:00-04:00 window.

The script itself re-proves those inputs, stages `S`, proves recovery, creates
`C` and `M=[C,S]`, journals the one Start, contains every Scheduler RPC, and
requires exact remote acknowledgement. If any proof fails or publication is
unknown, preserve the marker/report/lease evidence and do not retry.
