# Workstation unattended runner Linux collection repair

**Mission:** `workstation-unattended-runner-linux-collection-repair-2026-09-99f`

**Mission SHA-256:**
`6e58c8a813a6941aeba37ae39ff43a34d41320d534dfea0ae58667afb0b84f48`

**Verdict:** `PASS_REPAIRED_WINDOWS_VERIFIED_LINUX_CI_PENDING`

**Result branch:**
`codex/workstation-unattended-runner-linux-collection-repair-2026-09-99f`

**Implementation commit:** `bf756a3e16d99cb0996d256af82d74221e9829b7`

**Implementation tree:** `8a398b51cb2bc5ebbce7c1c85286114109021f7b`

The intentionally Windows-only workstation mission-runner test module now
skips during collection on non-Windows hosts before it evaluates `WINDIR` or
any other Windows-only constant. The skip uses the exact durable reason
`requires Windows PowerShell 5.1 and Windows process and Job Object APIs`.
Windows behavior is unchanged: all 16 tests collected, executed, and passed.

Linux/full acceptance remains pending the production controller's subsequent
exact-head GitHub Actions run. This workstation did not contact GitHub or any
other remote service.

## Frozen source and P0

All preconditions passed before the result ref or worktree was created.

| Proof | Result |
| --- | --- |
| Source | `7c58e55e156bbd486fbd0fbf977ff9db9864f657`; tree `0bddaae7997b88a3eb0a1cdb10a07d9aee761dae`; sole parent `215c7a661e02672ca4aab96d1eba122ed6e03c60` |
| Stack base | `ca75c2e476e865047f07dc9856e5897533834684`; tree `1c2a7fd18dacc84c6a0e9abd4afe837c0bab3801`; confirmed ancestor of source |
| Result branch/worktree | Both absent before creation; created only as the mission-named result ref and `C:\Users\Michael\Documents\github\weather\scratch\w\unattended-runner-linux-collection-repair-09-99f` |
| Worktrees | Repository root, 99c source, and detached 99f controller were clean and exact |
| Workstation | `DESKTOP-RFCD2GH`, principal `DESKTOP-RFCD2GH\Michael`; tracked assignment matched and dedicated capture-host identity did not match |
| Workload controls | Host-global mutex free without abandonment; poison marker absent; no conflicting heavy or portable worker |
| Runner identity | `scripts/ops/invoke_workstation_codex_mission.ps1` SHA-256 `50dc332d687704047c6c1a440ca4352af1246466a8873df6225e052a5915e9c8` |
| Codex identity | `C:\Users\Michael\AppData\Local\OpenAI\Codex\bin\9ba750cce02d5e5c\codex.exe`; SHA-256 `be83164c07287d028cc4725105f3cceaaf244d53a862e19743f55e9150a66fc1` |
| Immutable 99c bundle | 516,981,666 bytes; SHA-256 `0503c0113d132cb2f122999556ebc197bd478b62d43d193e7e3b8f3753c068ab` |
| Immutable 99c binding | 12,735 bytes; SHA-256 `d54fcc39d81638b161d3d86556b74b516d0734c3f7d5e6a509e36e28d7dd89a2` |

## Established Linux failure

Draft PR #15 at exact head
`7c58e55e156bbd486fbd0fbf977ff9db9864f657` ran GitHub Actions CI run
`33835975368`. Windows production-contract job `100908470945` passed. Linux
test job `100908470738` failed during collection at
`tests/operations/test_workstation_codex_mission_runner.py:18` because
`Path(os.environ["WINDIR"])` raised `KeyError: 'WINDIR'`.

The repair adds exactly seven lines after `import pytest` and before the first
Windows-only constant. It makes no change to the runner, CI workflow,
application/model code, capture/trading code, or any unrelated test.

## Preserved 99d and 99e attempts

The failed attempts and their dirty worktrees remain unchanged. Each contains
only the same uncommitted seven-line test repair.

| Attempt | Complete Windows runner proof | Required fail-closed stop |
| --- | --- | --- |
| 99d | 16 passed in 33.611 seconds; JUnit 2,826 bytes, SHA-256 `6706fbb24ad969cc2d2d25459286d30882be76cb70b58e10011b16fba3405ced` | Its full suite had the exact 12 inherited MAX_PATH failures plus one unrelated daily-roll `PermissionError(13)` on `daily_roll_status.json.launch.lock`; no commit was created |
| 99e | 16 passed in 33.428 seconds from a unique short temp root; JUnit 2,826 bytes, SHA-256 `9838fdc35892aeee50af1dc59b781c74499f60822f03a88311a7cc3c727c99c9` | Its permitted daily-roll control reproduced the unrelated `PermissionError(13)`; no commit was created |

That daily-roll test is outside this mission's acceptance surface. It was not
run or modified here. No complete workstation suite was run.

## Acceptance-scoped verification

One unique short external temp root,
`C:\t99f-a1-6e58c8a8`, was created before tests. Every verification Python
process inherited process-local `TEMP` and `TMP` pointing to that root and ran
serially under `scripts/ops/workstation_heavy.ps1`.

| Check | Result |
| --- | --- |
| Complete `tests/operations/test_workstation_codex_mission_runner.py` | 16 passed, 0 skipped, 0 failures, 0 errors in 34.214 seconds; JUnit 2,826 bytes; SHA-256 `68b7eb6fbfd6fb9af2478233027f68e8efd5df2e77ff5a157c98152e1cf4487e` |
| Compileall | PASS for `app`, `src`, and `tests` |
| Agent-document audit | PASS |
| Roadmap lint/check | PASS |
| Repository-check evidence | 2 passed in 0.867 seconds with the handback files present; JUnit 391 bytes; SHA-256 `e9bdaf1295f7a4160bbd9052e091097009900d45950b19c659fd5a9ca8198d99` |
| Cumulative source-to-implementation `git diff --check` | PASS |

The first repository-check harness invocation failed before either check was
collected because pytest treated the external `Documents\Codex` directory as
a collection root and encountered an unrelated untrusted mount point. Its
create-only JUnit is 1,465 bytes with SHA-256
`035f574464afd3b6ceb62b42d39aba90751666d90bfbddecf7af073cfd9ef5f0`.
The corrected invocation fixed `--rootdir` to the result worktree, used a copy
inside the same attempt temp root, and passed both required checks. No product
or test source changed in response to the harness-only failure.

## Changed paths and roll classification

Exactly three paths differ from the source tip:

1. `tests/operations/test_workstation_codex_mission_runner.py`
2. `docs/roadmap/agent-report-2026-09-04-workstation-unattended-runner-linux-collection-repair-acceptance-scoped.md`
3. `docs/roadmap/workstation-handback-2026-09-04-unattended-runner-linux-collection-repair-acceptance-scoped.json`

The report and receipt are `docs/` historical evidence and are roll-free by
the delegation contract. The test file is test-only and does not enter a
capture runtime import closure. The production controller must still obtain
the exact canonical roll verdict before any integration decision.

## Reproduction

After importing the complete bundle into an isolated repository, the
production controller can reproduce the platform behavior at the exact final
tip with the repository interpreter:

```powershell
.\venv\Scripts\python.exe -m pytest tests\operations\test_workstation_codex_mission_runner.py -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
git diff --check 7c58e55e156bbd486fbd0fbf977ff9db9864f657..HEAD
```

The Windows pytest command must follow the applicable host-load policy. Linux
collection and the complete CI surface remain the subsequent exact-head
GitHub Actions acceptance.

No production host, Scheduler, credential store, provider, exchange, outcome,
market data, capture process, model, release, promotion, pull request, merge,
push, or live-trading action occurred. No fetch, pull, LFS transfer, network
fallback, automatic retry, cleanup, persistent task, service, or daemon was
used or added.

The report and receipt are committed as the sole child of the implementation
commit. The receipt retains null self-referential final tip, tree, and bundle
values. Complete-history bundle verification, isolated strict fsck, portable
committed-blob reproduction, final identity checks, and the create-only
external binding follow that final commit.
