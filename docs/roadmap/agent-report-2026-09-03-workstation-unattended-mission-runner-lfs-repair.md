# Workstation unattended mission runner LFS repair

**Mission:** `workstation-unattended-mission-runner-lfs-repair-2026-09-99b`

**Mission SHA-256:**
`c012a47b3e74e5f828159765c3dd768bbb3f387b9b116ca45d1d3d2946cef1aa`

**Verdict:** `PASS_REPAIRED`

**Implementation commit:** `cb2b5c6eaafc51d67eb42cad009502506e5e6ec5`

**Implementation tree:** `d4ddddc65584d9fbc719ba63356e81cf2bf99c36`

The unattended controller checkout now disables Git LFS smudging only around
its exact-source `worktree add`, restores the prior process environment value
in `finally`, and leaves pointer bytes in a clean source worktree without an
LFS download. The terminal identity boundary also re-resolves and verifies the
claimed Git and Windows PowerShell paths and SHA-256 values before handback
validation.

## Frozen identity and P0

All preconditions passed before the result branch or worktree was created.

| Proof | Result |
| --- | --- |
| Canonical origin | `https://github.com/michaelbooth1/weather.git` |
| Source | `b11626edb02f2c36d467597c83c067547c4ede39`; tree `e5d1292e6e6fa4c21102172744aba544862a3540`; sole parent `0a8108f9d24321aaac88762c28426f8ca68d2bf8` |
| Stack base | `ca75c2e476e865047f07dc9856e5897533834684`; tree `1c2a7fd18dacc84c6a0e9abd4afe837c0bab3801` |
| Source branch | `codex/workstation-unattended-mission-runner-hardening-2026-09-99a` at the exact source tip |
| Result branch/worktree | Both absent before creation; created only as `codex/workstation-unattended-mission-runner-lfs-repair-2026-09-99b` and `C:\Users\Michael\Documents\github\weather\scratch\w\unattended-runner-lfs-repair-09-99b` |
| Root and 99a worktrees | Clean before creation and left unmodified |
| Workstation | `DESKTOP-RFCD2GH`, principal `DESKTOP-RFCD2GH\Michael`; shared mutex available; poison marker absent |
| External prototype | Regular non-reparse file; SHA-256 `afb65b7e63083887f84f3fcfb407ff5f65e0d895b1a0d3c8a2f10474c9c84919` |
| 99a bundle | 516,957,605 bytes; SHA-256 `acc57a1675b86170166bff91057e2f10b03ca33e62b84083ad550d2a01550aa6`; `git bundle verify` reported complete history |
| 99a external binding | Report, receipt, Git blobs, byte counts, hashes, final tip/tree, and bundle hash all reproduced exactly |

No remote query or fetch was used. The cached result local and remote-tracking
refs and the requested worktree path were absent.

## Falsifier and repair

The production controller's retained failure was the decisive falsifier:

```text
Error downloading object: artifacts/models/hgb/feature_model_hgb.pkl (bf53fd6)
Smudge error: batch request: missing protocol: ""
error: external filter 'git-lfs filter-process' failed
```

The local red test reproduced the mechanism without Internet access. A
loopback-only Git LFS batch endpoint received one batch POST and one payload
GET, and the source controller materialized payload bytes instead of the
committed pointer. The same red run showed that no executable checker covered
the copied Git or Windows PowerShell path/SHA drift cases. It failed 5 tests in
4.48 seconds. Its JUnit is 25,325 bytes, SHA-256
`42ec91e66695cb4b083db3552476949b23d4b584eb5a5d73edea04d43672da6f`;
the red test-source SHA-256 is
`6384fc09beafa25cce842b60d73d750235144cc2def621558ae408275bb20dd0`.

After repair, the same five cases passed in 4.54 seconds. The endpoint received
zero requests; the controller held exact pointer bytes at the source tip/tree
and `git status` was clean. Repository, user/global, and system Git
configuration snapshots were unchanged, the parent environment was unchanged,
and the fake child inherited the exact prior process value `0`. Copied Git and
Windows PowerShell path and byte drift each threw from the executable identity
check before `Assert-Handback`. The green JUnit is 1,113 bytes, SHA-256
`28f4d96c2b5208fddbbf8b7d7629448ac3031b54cecf7b920f8381f26680c414`.

The repair changes no persistent Git configuration and no non-LFS filter. It
sets `GIT_LFS_SKIP_SMUDGE=1` only for controller creation and restores the exact
prior process value even if that Git operation throws. Every other Git
operation retains the existing credential-disabled local-only wrapper.

## Verification

Every Python, pytest, and compileall process ran serially under
`scripts/ops/workstation_heavy.ps1` with profile `workstation_offline_v1`, the
99b worktree as repository root, the root-checkout interpreter, and short
external basetemp paths.

| Gate | Result |
| --- | --- |
| Complete runner test file | **15 passed** in 30.13 s; JUnit SHA-256 `0bd536cbdbe151393b571c60dcd370f66735b69ae17cef162836fc974a82beb6` |
| Existing runner contracts | Heartbeat, deadline descendant teardown, interrupt, collision/no-retry, dirty-root isolation, invalid handback, complete bundle/fsck, and status reader all passed |
| Git/PowerShell identity drift | Four copied-executable path/SHA cases passed; final `IDENTITY_DRIFT` mapping precedes handback validation |
| Windows PowerShell 5.1 AST | **Pass**, 7,920 tokens and zero parse errors |
| Complete workstation suite | **4,230 passed, 18 skipped, 12 failed, 862 subtests passed** in 439.11 s |
| Baseline classification | All twelve failures are the exact same `tests/operations/test_experiment_executor.py` node IDs as 99a's retained SHA-256 `f7ee20f8ab4abe7aabd3090235f2bfdef750e62f066f4f0044ac19782ef9a151`; current JUnit SHA-256 `caf7feacc9ea11badd792d947935695ccf026bd1d32d77ba89cc75300182fac1` |
| Compileall | `-m compileall -q app src tests` passed |
| Agent-doc audit and roadmap lint/check | **2 passed**; JUnit SHA-256 `7c0197ecf932d8607c34cbd3e76aeff9db14de9586f8b795a4ee40f3a492bfee` |
| Cumulative diff check | Passed from exact source through implementation; final source-to-handback proof is in the external binding |

The twelve full-suite failures are the retained Windows `MAX_PATH` source
baseline. This branch does not change `app/`, `src/`, or
`tests/operations/test_experiment_executor.py`; it did not weaken, skip,
xfail, mock, or relabel them. No other full-suite failure occurred.

## Content identities

| Path | SHA-256 |
| --- | --- |
| `scripts/ops/invoke_workstation_codex_mission.ps1` | `4d204f176c2fb5201889c888cf7e9a054c518a422667482d4a60c35861ab112a` |
| `scripts/ops/windows_kill_on_close_job.ps1` | `e910f4bcadd39a7b57413669fd75bcbff44b85aa46186c2f3324ec1a2ba36243` |
| `scripts/ops/workstation_heavy.ps1` | `31a353c616e293882daab4292e8e7628ee09fdda032cb04bafed8ed8fe531532` |
| `tests/operations/test_workstation_codex_mission_runner.py` | `02f780c904177752cc6ad8fd7bfbf31c19a7c864207f4729319db3f94bdac745` |
| `docs/operations/WORKSTATION_CODEX_MISSION_RUNNER.md` | `a46bef391d94fb3339e409019ecb53fc24b963f567318dea5e9f322d39a832fd` |

The final claimed executable identities are Git
`C:\Program Files\Git\cmd\git.exe` at
`81ef35ae005ca9318018d18e3327578ce939fb99feaad6b2d7c8ab15f3de8db5`
and Windows PowerShell
`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` at
`7600ffe12da441fe89d035b13801e8e91d064bc544a27b19a5cf49f6ab8b18f5`.

## Roll and authority boundary

No canonical production roll verdict was requested or run. This workstation
has no live closure evidence, so the dynamic verdict for every changed file is
`UNDECIDABLE`; no manual substitute was used. The changed implementation paths
are one PowerShell control-plane script, its test, owning documentation, Item
332, and the generated active backlog. The final report and receipt are also
documentation. This structural description is not a production verdict.

No production host, Scheduler, credential store, provider, exchange, capture,
model, outcome, release, promotion, merge, push, pull request, or live-trading
action occurred. The existing Job helper, workload/quiet-merge files, Python
runtime, schemas, CI, and runner/adoption state were unchanged. No retry,
network fallback, LFS fetch, cleanup, persistence, or daemon was added.

## Reboot and immutable handback boundary

The existing kill-on-close Job, heartbeat, and deadline remain effective only
while the host and wrapper remain alive. A reboot destroys in-memory Job state;
the status reader can identify the boot change, but no Scheduler task, service,
restart supervisor, or automatic next attempt is implemented.

The report and JSON receipt are committed separately from the implementation.
Because the receipt cannot contain the hash of the commit/tree or bundle that
contains its own bytes, its final tip/tree/bundle fields remain null. The
create-only external binding records those final identities, the report and
receipt hashes, complete bundle verification, required commit reachability,
and strict isolated fsck. Nothing in the handback grants integration or runtime
adoption authority.
