# Workstation production-baseline reconciliation audit (2026-09-07 mission)

## Verdict

**NO-GO.** No production command is authorized by this report.

The repository has no existing path that can reconcile the accepted production
state
`3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac ->
c932b54f8747df5cdefc4cc42f8454b6797f09ae` while satisfying all of the
mission's first-adoption, rollback, no-credential, no-real-task, and
no-`reset --hard` requirements. The correct existing refusal must remain in
place. PR #9 and PR #7 must not be adopted until a separately authorized path
closes this bootstrap boundary.

This is a dated audit report, not production evidence. The mission identifier
uses 2026-09-07 as requested; the workstation evidence below was collected on
2026-09-01 America/Toronto. Production state was not contacted or re-derived;
the production facts in the assignment are treated as accepted inputs.

## Exact source identity and scope

- Required and fetched canonical `origin/master`:
  `c932b54f8747df5cdefc4cc42f8454b6797f09ae`.
- Source tree: `6df5bac16d8c780c35b4601941eaca1137ea7070`.
- Accepted production local `master` / `HEAD`:
  `3361520fa4c2bb8aa8701f94ce57fcbd0c7d3bac`.
- Production-baseline tree:
  `5281cd8ebff233e576a0b21d138a892c8c6c956c`.
- Canonical origin URL observed in the isolated workstation worktree:
  `https://github.com/michaelbooth1/weather.git`.
- Audit branch:
  `codex/workstation-production-baseline-reconciliation-2026-09-83a`.
- Isolated audit worktree started clean at the required source SHA. No
  production checkout, production data, Scheduler state, credentials,
  provider, exchange, portable checkout, PR ref, or live process was touched.

The final branch tip and tree cannot be embedded in the commit that contains
this report without an impossible self-reference. They are recorded in the
push handback and can be reproduced with `git rev-parse HEAD` and
`git rev-parse HEAD^{tree}`.

## Ancestry and merge topology

Read-only Git checks proved:

- `3361520...` is a strict ancestor of `c932b54...`.
- The merge base is exactly `3361520...`.
- `git rev-list --left-right --count 3361520...c932b54` is `0 26`.
- The range contains 26 commits: 23 non-merges and 3 merges. Only the final
  PR #5 merge is on `master`'s first-parent path.
- `3361520...` is GitHub's merge of PR #3. Its tree equals its PR-head second
  parent.
- PR #4 was merged into `codex/portable-execution-host-clean-20260827`, not
  `master`. Merge `24443acaa4dc1d736c18b8f5ff6285626da15b2d`
  has PR #4 head `d1616ceda2ac90621e276aadead84b3a6952d5ca`
  as its tree-equivalent second parent.
- Topic sync merge `f12e5785abbf6e4077a64e7dfdfb295cf337ce31`
  has parents `0a15c9b...` and `3361520...`; its tree equals its first parent,
  so it added ancestry and no content relative to the topic.
- Final PR #5 merge `c932b54...` has parents `3361520...` and
  `1acf9ebbc4a9576810b99126ea5ab8764f35aa9b`. Its tree equals the PR #5
  head tree. PR #5 therefore carried the mis-targeted PR #4 work and all later
  topic work onto GitHub `master`.

GitHub records no submitted review on PR #3, PR #4, or PR #5; this report does
not invent an independent-review claim.

## Per-commit changed-file inventory

Paths below are each commit's delta from its first parent. Brace notation is
only compact spelling: every member named inside braces is a distinct path.

1. `c5e9ca7b03443cc6fa4f1151a4ef182dd7cfdf4a` —
   `.codex/hooks/pre_tool_use_host_load.py`; `AGENTS.md`;
   `docs/development.md`; `docs/operations/DELEGATION_CONTRACT.md`;
   `docs/operations/HOST_LOAD_POLICY.md`;
   `docs/operations/OPERATIONS_AGENT_ROLE.md`;
   `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`;
   `scripts/ops/AGENTS.md`; `scripts/ops/memory_commit_guard.ps1`;
   `scripts/ops/register_memory_commit_guard.ps1`;
   `tests/operations/test_codex_host_load_hook.py`;
   `tests/operations/test_memory_commit_guard_script.py`.
2. `c2c80de97c7323c3f315b757bce0b8673a7cd9a0` —
   `.codex/hooks/pre_tool_use_host_load.py`; `AGENTS.md`;
   `docs/development.md`; `docs/operations/DELEGATION_CONTRACT.md`;
   `docs/operations/HOST_LOAD_POLICY.md`;
   `docs/operations/OPERATIONS_AGENT_ROLE.md`;
   `scripts/ops/AGENTS.md`; `scripts/ops/memory_commit_guard.ps1`;
   `scripts/ops/register_memory_commit_guard.ps1`;
   `tests/operations/test_codex_host_load_hook.py`;
   `tests/operations/test_memory_commit_guard_script.py`.
3. `839279b84d65d32cca07ec50e3e30052b0c9220e` —
   `.codex/hooks/pre_tool_use_host_load.py`; `AGENTS.md`;
   `config/international_live_execution_host.json`; `docs/development.md`;
   `docs/operations/DELEGATION_CONTRACT.md`;
   `docs/operations/HOST_LOAD_POLICY.md`;
   `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
   `docs/operations/OPERATIONS_AGENT_ROLE.md`;
   `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`;
   `docs/operations/STATE_OF_PLAY.md`; `docs/roadmap/active-backlog.md`;
   `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md`;
   `scripts/ops/AGENTS.md`; `scripts/ops/install_codex_host_load_hook.ps1`;
   `scripts/ops/international_live_templates/fixed_scope_launcher.ps1.tmpl`;
   `scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl`;
   `scripts/ops/windows_kill_on_close_job.ps1`;
   `scripts/ops/workload_admission.ps1`;
   `scripts/ops/workstation_heavy.ps1`;
   `src/weather/operations/international_live_session_launcher_sealer.py`;
   `src/weather/operations/international_live_wrapper_sealer.py`;
   `src/weather/operations/live_path_security.py`;
   `tests/market/test_live_sdk_portability.py`;
   `tests/operations/test_codex_host_load_hook.py`;
   `tests/operations/test_international_live_session_launcher_sealer.py`;
   `tests/operations/test_live_path_security.py`;
   `tests/operations/test_live_wrapper_credential_launcher.py`;
   `tests/operations/test_workload_admission_script.py`.
4. `d1616ceda2ac90621e276aadead84b3a6952d5ca` —
   `tests/operations/test_codex_host_load_hook.py`.
5. `24443acaa4dc1d736c18b8f5ff6285626da15b2d` (PR #4 merge) —
   its 31-file first-parent aggregate is the union of commits 1–4: the files
   listed there plus `config/international_live_execution_host.json`, the
   International live documentation/templates, workstation wrapper,
   workstation/admission/containment operations files, and their named tests.
   Its second-parent delta is empty and its tree equals the PR #4 head.
6. `e1f7985ed9057019ccbfa1034fbdeadd8fd52a4a` —
   `docs/operations/STATE_OF_PLAY.md`.
7. `657e1c960127c9aabb3f469785ba7bf9167e7b4d` —
   `docs/operations/STATE_OF_PLAY.md`.
8. `0a15c9b30b21d1b9acc0ada6a9b6d17b84dd5b2f` —
   `docs/operations/DELEGATION_CONTRACT.md`;
   `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
   `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`;
   `scripts/ops/international_live_templates/stage0.py.tmpl`;
   `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl`;
   `src/weather/market/mm_live_pilot_cli.py`;
   `src/weather/operations/international_live_session_launcher_sealer.py`;
   `src/weather/operations/international_live_session_runner.py`;
   `src/weather/operations/international_live_wrapper_sealer.py`;
   `src/weather/schema_registry_data.py`;
   `tests/market/test_mm_live_pilot_cli.py`;
   `tests/operations/test_international_live_session_launcher_sealer.py`;
   `tests/operations/test_international_live_session_runner.py`;
   `tests/operations/test_international_live_wrapper_sealer.py`;
   `tests/operations/test_schema_registry.py`.
9. `f12e5785abbf6e4077a64e7dfdfb295cf337ce31` (topic/master sync
   merge) — empty first-parent delta; tree equals `0a15c9b...`.
10. `ce3a0e785b40b978e306e827045b37e3ab9c35aa` —
    `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
    `docs/operations/STATE_OF_PLAY.md`.
11. `99f4707b4da6793185a35ea41d1e6c0ca6c1aa14` —
    `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
    `src/weather/market/market_making_run.py`;
    `src/weather/market/mm_policy.py`;
    `tests/market/test_market_making_run.py`.
12. `98f2ff66e1ffa58e46083a2096f2c8b92a882497` —
    `docs/operations/STATE_OF_PLAY.md`.
13. `4e87112a9d0cd528fafcbc108346b29f4356e3d9` —
    `src/weather/market/portable_live_candidate_preflight.py`;
    `tests/market/test_portable_live_candidate_preflight.py`.
14. `7db0a0aa145570d1ec029b580c1ac32f78888916` —
    `docs/operations/STATE_OF_PLAY.md`.
15. `045a9e6d991db487f9feb9302e3450a864095aa9` —
    `src/weather/market/portable_live_candidate_preflight.py`;
    `tests/market/test_portable_live_candidate_preflight.py`.
16. `65926ba1d97265ffba9638a405924c2b634bf832` —
    `docs/operations/STATE_OF_PLAY.md`.
17. `fb2d041fa7c88138ec605119d8c67c1914c99b1c` —
    `docs/operations/STATE_OF_PLAY.md`.
18. `8c081248616acf14844480991bb8aa5adbf5e9e0` —
    `docs/operations/STATE_OF_PLAY.md`.
19. `f27347b4c5bd33991ff7ff860cce16e724ec402e` —
    `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
    `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`;
    `docs/operations/STATE_OF_PLAY.md`;
    `scripts/ops/international_live_templates/stage0.py.tmpl`;
    `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl`;
    `src/weather/operations/international_live_session_runner.py`;
    `src/weather/operations/international_live_time_window.py`;
    `src/weather/operations/international_live_wrapper_sealer.py`;
    `tests/operations/test_international_live_session_runner.py`;
    `tests/operations/test_international_live_wrapper_sealer.py`.
20. `1d4f449527e2a227f6c0661de11bba9e3862c0af` —
    `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
    `docs/operations/STATE_OF_PLAY.md`; `docs/roadmap/ROADMAP.md`;
    `docs/roadmap/active-backlog.md`;
    `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md`;
    `scripts/ops/international_live_templates/fixed_scope_launcher.ps1.tmpl`;
    `scripts/ops/international_live_templates/stage0.py.tmpl`;
    `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl`;
    `scripts/ops/workload_admission.ps1`;
    `src/weather/market/mm_live_pilot_cli.py`;
    `src/weather/operations/international_live_session_runner.py`;
    `src/weather/operations/international_live_wrapper_sealer.py`;
    `src/weather/operations/live_path_security.py`;
    `src/weather/schema_registry_data.py`;
    `tests/market/test_mm_live_pilot_cli.py`;
    `tests/operations/test_international_live_session_runner.py`;
    `tests/operations/test_international_live_wrapper_sealer.py`;
    `tests/operations/test_live_path_security.py`;
    `tests/operations/test_schema_registry.py`;
    `tests/operations/test_workload_admission_script.py`.
21. `1e60b6b0c184fc88bd5c52913cdf949961d475db` —
    `tests/operations/test_live_path_security.py`.
22. `9b6f3ccf014a122dda7d62979625c7741745f4d8` —
    `docs/operations/STATE_OF_PLAY.md`; `docs/roadmap/ROADMAP.md`;
    `docs/roadmap/active-backlog.md`;
    `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md`.
23. `a9d6bac8b7135cade13330e5fb42813aabf9fdc0` —
    `docs/operations/STATE_OF_PLAY.md`;
    `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md`.
24. `3f2b077b95f5dcabbeba8995ac24fb2e4ca85659` —
    `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`;
    `scripts/ops/international_live_templates/stage0.py.tmpl`;
    `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl`;
    `src/weather/market/mm_live_bootstrap.py`;
    `src/weather/market/mm_live_pilot_cli.py`;
    `src/weather/operations/international_live_session_runner.py`;
    `src/weather/operations/international_live_wrapper_sealer.py`;
    `tests/market/test_mm_live_bootstrap.py`;
    `tests/market/test_mm_live_pilot_cli.py`;
    `tests/operations/test_international_live_session_runner.py`;
    `tests/operations/test_international_live_wrapper_sealer.py`.
25. `1acf9ebbc4a9576810b99126ea5ab8764f35aa9b` —
    `docs/operations/STATE_OF_PLAY.md`.
26. `c932b54f8747df5cdefc4cc42f8454b6797f09ae` (PR #5 merge) —
    its first-parent delta is the exact 49-file range union listed below; its
    second-parent delta is empty and its tree equals the PR #5 head tree.

## Exact 49-file range union

The net range is 49 files, 13,774 insertions, and 551 deletions:

- `.codex/hooks/pre_tool_use_host_load.py`
- `AGENTS.md`
- `config/international_live_execution_host.json`
- `docs/development.md`
- `docs/operations/DELEGATION_CONTRACT.md`
- `docs/operations/HOST_LOAD_POLICY.md`
- `docs/operations/INTERNATIONAL_MM_LIVE_PILOT.md`
- `docs/operations/OPERATIONS_AGENT_ROLE.md`
- `docs/operations/PORTABLE_LIVE_EXECUTION_HOST.md`
- `docs/operations/STATE_OF_PLAY.md`
- `docs/roadmap/ROADMAP.md`
- `docs/roadmap/active-backlog.md`
- `docs/roadmap/items/item-67-authenticated-exchange-adapter-and-mm-2-pilot-harness.md`
- `scripts/ops/AGENTS.md`
- `scripts/ops/install_codex_host_load_hook.ps1`
- `scripts/ops/international_live_templates/fixed_scope_launcher.ps1.tmpl`
- `scripts/ops/international_live_templates/fixed_session_launcher.ps1.tmpl`
- `scripts/ops/international_live_templates/stage0.py.tmpl`
- `scripts/ops/international_live_templates/stage1_cancel_all.py.tmpl`
- `scripts/ops/memory_commit_guard.ps1`
- `scripts/ops/register_memory_commit_guard.ps1`
- `scripts/ops/windows_kill_on_close_job.ps1`
- `scripts/ops/workload_admission.ps1`
- `scripts/ops/workstation_heavy.ps1`
- `src/weather/market/market_making_run.py`
- `src/weather/market/mm_live_bootstrap.py`
- `src/weather/market/mm_live_pilot_cli.py`
- `src/weather/market/mm_policy.py`
- `src/weather/market/portable_live_candidate_preflight.py`
- `src/weather/operations/international_live_session_launcher_sealer.py`
- `src/weather/operations/international_live_session_runner.py`
- `src/weather/operations/international_live_time_window.py`
- `src/weather/operations/international_live_wrapper_sealer.py`
- `src/weather/operations/live_path_security.py`
- `src/weather/schema_registry_data.py`
- `tests/market/test_live_sdk_portability.py`
- `tests/market/test_market_making_run.py`
- `tests/market/test_mm_live_bootstrap.py`
- `tests/market/test_mm_live_pilot_cli.py`
- `tests/market/test_portable_live_candidate_preflight.py`
- `tests/operations/test_codex_host_load_hook.py`
- `tests/operations/test_international_live_session_launcher_sealer.py`
- `tests/operations/test_international_live_session_runner.py`
- `tests/operations/test_international_live_wrapper_sealer.py`
- `tests/operations/test_live_path_security.py`
- `tests/operations/test_live_wrapper_credential_launcher.py`
- `tests/operations/test_memory_commit_guard_script.py`
- `tests/operations/test_schema_registry.py`
- `tests/operations/test_workload_admission_script.py`

Neither accepted production-generated path is in the range. The tracked blobs
at both endpoints are identical:

| Path | Blob at `3361520...` | Blob at `c932b54...` |
| --- | --- | --- |
| `config/location_market_events.json` | `189151516a47166f69c64ad0b9612466614a7fbb` | same |
| `config/locations.json` | `dcc595e2a0cbe73e8d4d67a30aab4def1176ee06` | same |

This proves the published delta itself does not require changing either
tracked config path. It does **not** prove the current production working bytes;
those were neither read nor contacted.

## PR provenance and exact-head CI

Primary GitHub evidence:

- [PR #4](https://github.com/michaelbooth1/weather/pull/4) — merged into the
  topic branch, head `d1616ced...`, merge `24443aca...`; exact-head CI
  [run 33234292928](https://github.com/michaelbooth1/weather/actions/runs/33234292928)
  passed.
- [PR #5](https://github.com/michaelbooth1/weather/pull/5) — base
  `master@3361520...`, head `1acf9ebb...`, merge `c932b54...`; exact-head CI
  [run 33412934719](https://github.com/michaelbooth1/weather/actions/runs/33412934719)
  passed.
- Final `master@c932b54...` push CI
  [run 33440226565](https://github.com/michaelbooth1/weather/actions/runs/33440226565)
  passed, including compile, agent-document validation, roadmap check, and the
  repository test step.
- [PR #9](https://github.com/michaelbooth1/weather/pull/9) remains open at
  `9a403705309f784066de6d34af98e817049f7952`; exact-head CI
  [run 33523041305](https://github.com/michaelbooth1/weather/actions/runs/33523041305)
  passed. Its accepted production verdict remains ROLL-FREE.
- [PR #7](https://github.com/michaelbooth1/weather/pull/7) remains open at
  `2e20e59aae08e7367dc79e1b8102c0551e7f6904`; exact-head CI
  [run 33530176631](https://github.com/michaelbooth1/weather/actions/runs/33530176631)
  passed. Its accepted production verdict remains ROLL-SENSITIVE.

Across the 26-commit range, no exact-SHA workflow run was found for
`c5e9ca7...`, `c2c80de...`, or `3f2b077...`; exact-SHA runs failed at
`839279b...` and `1d4f449...`, and were cancelled at `045a9e6...` and
`fb2d041...`. Every other range SHA has a successful exact-SHA run. These
intermediate results are superseded for cumulative-tree regression purposes by
the green PR #5 head and final merge, but they are not rewritten here as
per-commit PASSes.

## Exact roll-classification boundary

The range contains 11 importable Python candidates:

- `src/weather/market/market_making_run.py`
- `src/weather/market/mm_live_bootstrap.py`
- `src/weather/market/mm_live_pilot_cli.py`
- `src/weather/market/mm_policy.py`
- `src/weather/market/portable_live_candidate_preflight.py`
- `src/weather/operations/international_live_session_launcher_sealer.py`
- `src/weather/operations/international_live_session_runner.py`
- `src/weather/operations/international_live_time_window.py`
- `src/weather/operations/international_live_wrapper_sealer.py`
- `src/weather/operations/live_path_security.py`
- `src/weather/schema_registry_data.py`

Only production's current live closures can decide whether those files roll a
loaded producer. The workstation has no such evidence, so it cannot truthfully
classify this delta.

There is also a critical caller trap: when local `master` is strictly behind,
`roll_verdict.ps1` deliberately changes its default base from local `master` to
`origin/master`. For this incident, an unmodified call would therefore exclude
the entire `3361520...c932b54...` delta. Any future authorized repair must call
the canonical script with the exact old SHA as `-Base` and the exact target SHA
as `-Branch`; exit 1, exit 2, missing JSON, stale evidence, or missing evidence
must all be treated as ROLL-SENSITIVE and confined to 01:00–04:00.

## Existing production integration/recovery paths

### `quiet_window_merge.ps1`

The wrapper intentionally refuses at the synchronized-baseline gate:

```text
if ($head -ne $originMaster) {
    Fail "local master (...) != origin/master (...); reconcile first"
}
```

That refusal occurs before it binds the baseline, hashes either generated file,
writes the preparation marker, creates the temporary config-only commit, stages
a merge, proves recovery, or publishes. The preceding fetch may move cached
refs, but no working-tree or local-branch mutation occurs. Supplying
`-ExpectedBaseline 3361520...` cannot bypass the earlier equality gate.

The wrapper's ordinary synchronized path correctly accepts no tracked drift
outside the two generated paths, hashes both files, journals before its
temporary config commit, retains `MERGE_HEAD` through recovery proof, and uses
only the exact pre-provisioned `WeatherOneShotPush` task after documentation and
capture revalidation. Those contracts are correct and were not weakened.

### Immutable integration attempts

`new_integration_attempt.ps1` refuses to freeze an attempt unless production
`master == origin/master`. `integration_attempt_contract.ps1`, registration,
suite, wait, and merge consumers reprove the frozen equal baseline.
`integration_attempt_merge.ps1` delegates to the same guarded quiet merge.
`reconcile_integration_attempt.ps1 -ResumePublication` can resume only an exact
recovery-proved merge already bound to an immutable attempt; it is not a
general local-behind-origin updater. These are intentional evidence boundaries.

### Boot recovery

`boot_recovery.ps1` safely removes an unverified staged target first. It then
refuses the second mixed reset when `origin/master` differs from the marker's
baseline, preserving the marker and pre-merge state for reviewed recovery. A
recovery-proved committed two-parent merge is preserved, never guessed into a
push at boot.

The currently adopted script still contains `reset --hard` fallbacks after
`merge --abort` failure and for certain validated-marker states. A repair branch
can remove those fallbacks for future runs, but the new bytes are not installed
until the first reconciliation stages/adopts them. That bootstrap interval is
the decisive no-`reset --hard` falsifier.

### One-shot push

`WeatherOneShotPush` is push-only. The repository validates an already-created
singleton root task, current-user Interactive/Limited principal, exact command,
working directory, state, and reviewed XML SHA-256. It has no repository-owned
registrar or template. It cannot advance a behind local checkout. A synthetic
guarded merge could publish a descendant of `c932b54...`, but doing so requires
the real credential-bearing task, which this mission explicitly lists as a
falsifier and does not authorize.

## Candidate repairs and their falsifiers

| Candidate | Useful property | Decisive failure |
| --- | --- | --- |
| Plain `pull` / `merge --ff-only` | Published history is strictly fast-forwardable and the tracked config blobs are unchanged | Does not stage first, bind live roll evidence, journal raw bytes, prove workers, or provide interruption rollback. |
| Stage PR #5's second parent, prove recovery, then fast-forward local `master` to the already-published merge `c932b54...` | Avoids credentials and can expose exactly the final tree before moving the ref | The installed boot script can reach its legacy `reset --hard` fallback during first-adoption interruptions. Fixing the boot task first requires prohibited Scheduler mutation/a real task. |
| Create a new guarded two-parent reconciliation merge and push it | Fits the existing marker, capture-recovery, documentation, rollback, and origin-ack machinery | Requires the credential-bearing real push task; this is an explicit mission falsifier. |
| Temporarily rebind boot recovery to an isolated, hash-pinned repair script, then perform the staged fast-forward | Can close the direct-fast-forward crash boundary | Requires Scheduler registration/rebinding, explicitly outside authority and itself a real-task dependency. |

Because each viable topology crosses at least one explicit falsifier, adding a
partial helper would create a second, misleading merge system or weaken a
correct refusal. No implementation was retained.

## Adversarial conclusions

- Published history needs no rewrite: `3361520...` is an ancestor of
  `c932b54...`.
- The target delta does not change either tracked config blob, but the current
  repository path refuses before it hashes the production raw bytes.
- Existing synchronized rollback can preserve the exact generated bytes; it is
  unavailable before baseline reconciliation.
- The first-use isolated-worktree self-hash on `quiet_window_merge.ps1` is
  necessary but insufficient: recovery behavior during the staged target is
  still supplied by the production checkout or its registered boot action.
- The existing roll caller would classify the wrong (empty post-origin) delta
  unless the old SHA is passed explicitly as `-Base`.
- No safe command can be issued under the current authority. This is a real
  bootstrap dependency, not a missing unit test or a reason to relax the
  synchronized-baseline guard.

## Verification

The audit used read-only Git/GitHub topology, tree, blob, PR, commit-to-PR, and
workflow metadata checks. Repository verification results:

- focused existing operations tests: **POLICY-BLOCKED before Python launch**.
  The required `scripts/ops/workstation_heavy.ps1` wrapper exited 1 because
  this host/principal is not the repository-assigned non-capture workstation.
  The guard was not bypassed. The exact source `c932b54...` already has green
  final-master CI, but that is not relabeled as a local run.
- PowerShell AST parse: **PASS**, zero parser errors across nine traced scripts
  (`roll_verdict`, quiet merge, boot recovery, attempt creator/contract/merge/
  reconciliation, boot registrar, and workstation wrapper).
- compileall through `scripts/ops/workstation_heavy.ps1`:
  **POLICY-BLOCKED before Python launch** by the same exact host/principal
  refusal; the guard was not bypassed.
- agent-document audit: **PASS** (18 agent files, 828 Markdown files).
- roadmap lint/check: **PASS** (generated report matches sources).
- full suite: **not required and not run**, because no code changed;
- finished-branch canonical roll verdict: **UNDECIDABLE**, exit 1. The
  workstation lacks all four required production closure files
  (`loop_supervisor_status`, `clob_loop_supervisor_status`,
  `observation_trigger_supervisor_status`, and `clob_enrichment_status`). The
  guard was not replaced by a hand-derived roll-free claim. The final exact tip
  is recorded in the branch handback.

## Canonical stop handoff

There is no safe production run plan under the mission's authority. Therefore:

1. Leave production `HEAD/master` at accepted SHA `3361520...` and preserve the
   exact two generated modifications.
2. Do not run `quiet_window_merge.ps1`, a manual fast-forward, `pull`, stash,
   reset, checkout cleanup, rebase, squash, cherry-pick, or any push workaround.
3. Do not create an immutable attempt: its synchronized-baseline refusal is
   correct.
4. Do not adopt PR #9 or PR #7.
5. Resume only after the repository owner issues new authority that explicitly
   resolves one bootstrap choice: hash-pinned Scheduler rebinding for repaired
   boot recovery, or use of the existing credential-bearing one-shot push for
   a reviewed synthetic reconciliation merge. A future mission must then bind
   exact new SHAs and rerun production live-closure classification; this report
   is not standing authority for either choice.
