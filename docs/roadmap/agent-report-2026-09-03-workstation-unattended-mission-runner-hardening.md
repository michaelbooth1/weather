# Workstation unattended mission runner hardening

**Mission:** `workstation-unattended-mission-runner-hardening-2026-09-99a`

**Mission SHA-256:**
`8d43e292925ded19d98db3c80b3b21c033bed9ae14a571f0de589b248b4213d0`

**Verdict:** `PASS_REPAIRED`

**Implementation commit:** `0a8108f9d24321aaac88762c28426f8ca68d2bf8`

**Implementation tree:** `08f5187dee1f617a76c3965f393b72f097b7d764`

The sealed mission's material claims reproduced. The repository now owns a
Windows PowerShell 5.1 runner that binds an explicit mission and Codex binary,
runs the complete child tree in a kill-on-close Windows Job, publishes an
atomic sequenced heartbeat, enforces an absolute UTC deadline, retains
create-only attempt evidence, and accepts success only after the exact result
ref, clean result worktree, report, receipt, changed paths, declared passing
tests, script hashes, complete bundle, and strict object verification all pass.

The prototype premise that attempt collisions caused retry was only partly
true: the prototype already refused an existing attempt directory and had no
automatic retry. The implementation preserves that behavior and adds an
immutable terminal receipt without inventing a next attempt.

## Frozen identity and P0

The exact mission file was read first and matched its required SHA-256. All P0
identity and collision gates passed before the isolated result worktree was
created.

| Proof | Result |
| --- | --- |
| Canonical origin | `https://github.com/michaelbooth1/weather.git` |
| Production base | `c932b54f8747df5cdefc4cc42f8454b6797f09ae`; tree `6df5bac16d8c780c35b4601941eaca1137ea7070` |
| Source | `ca75c2e476e865047f07dc9856e5897533834684`; tree `1c2a7fd18dacc84c6a0e9abd4afe837c0bab3801`; sole parent `1a3f94d1fd4d8e16f618411670418eb009f8e319` |
| Result branch | `codex/workstation-unattended-mission-runner-hardening-2026-09-99a` |
| Result worktree | `C:\Users\Michael\Documents\github\weather\scratch\w\unattended-runner-hardening-09-99a` |
| Prototype | Regular non-reparse file; SHA-256 `afb65b7e63083887f84f3fcfb407ff5f65e0d895b1a0d3c8a2f10474c9c84919` |
| Workstation admission | `DESKTOP-RFCD2GH`, principal `DESKTOP-RFCD2GH\Michael`; shared mutex available; poison marker absent |

The immutable preflight receipt is
`C:\Users\Michael\Documents\Codex\runs\workstation-unattended-mission-runner-hardening-2026-09-99a\p0-preflight.json`,
4,903 bytes, SHA-256
`50bb99fe75b1355fc3d02a4e81b0c32ebd37d92245c3391b11fe5e213888864a`.

## Probe and falsifier results

The final faithful prototype probe passed 8 tests in 10.61 seconds. Its JUnit
SHA-256 is
`132e94f3f3e2eabf54cafe9317cf2cebf8e37bcab6486aa1846335d4c07f7d40`;
the results receipt SHA-256 is
`700af3773df084fc1085a68e1195703f5337e33ff221a2a65479a054c11e511b`.

| Finding | Result |
| --- | --- |
| Fresh heartbeat | Reproduced absent: one `RUNNING` timestamp, no sequence or heartbeat |
| Deadline and descendants | Reproduced absent: wrapper and handle-isolated descendant outlived the synthetic deadline |
| Exit-zero handback | Reproduced unsafe: `COMPLETE` with no report, receipt, bundle, result identity, or last-message validation |
| Atomic status | Reproduced absent: equivalent same-path writes exposed malformed/truncated or reader-denied states |
| Dirty-root isolation | Reproduced: root cleanliness blocked the child while a clean exact-source controller succeeded |
| Executable identity | Reproduced: multiple version directories caused refusal before a claim froze path and digest |
| Terminal diagnostics | Reproduced absent: child failure collapsed to generic `FAILED`; abrupt exit left `RUNNING` |
| Collision/retry premise | `FALSE_PREMISE_PARTIAL`: collision refusal and no-retry behavior already existed and were preserved |

None of the mission falsifiers fired after repair. Whole-tree containment is
proved through the existing Job helper without PID-name matching. Exact
handback validation reads only Git and declared mission artifacts. No PR #13
runtime owner changed. The replacement is more observable and more fail-closed
than the prototype.

## Implemented contract

`scripts/ops/invoke_workstation_codex_mission.ps1` has `Run`, `Status`, and
private `InternalChild` modes. `Run` requires explicit mission path/digest,
source tip/tree/parent, base tip, result ref/worktree, report/receipt, complete
bundle path, Codex executable path/digest, absolute UTC deadline, and attempt
number. It creates a detached exact-source controller, freezes those values in
`claim.json`, starts the child suspended, assigns it to the repository's
kill-on-close Job, then resumes it.

Heartbeat and status publication uses a same-directory temporary file, durable
flush, and `MoveFileEx` with replace-existing and write-through flags. Every
publication carries a strictly increasing sequence, UTC observation, and
monotonic elapsed milliseconds. The status reader consumes only the exact
claimed files and classifies stale same-boot state as
`ABRUPT_WRAPPER_EXIT_OR_CLIENT_DISCONNECT` or `RUNNING_STALE`; a changed boot
identity becomes `ABRUPT_HOST_REBOOT`.

Terminal states and exit codes are:

| State | Exit |
| --- | ---: |
| `COMPLETE_VALIDATED` | 0 |
| `CHILD_FAILURE` | 20 |
| `DEADLINE` | 21 |
| `INTERRUPTED` | 22 |
| `INVALID_HANDBACK` | 23 |
| `IDENTITY_DRIFT` | 24 |
| `TEARDOWN_FAILURE` | 25 |
| `RUNNER_FAILURE` | 26 |

The success validator resolves the exact local result ref, requires ancestry
from source and the declared implementation commit, requires a clean exact
result worktree, compares actual and declared changed paths, verifies required
tracked report/receipt bytes and declared script hashes, then verifies and
fetches the complete bundle into a new short-path bare repository before
running strict full fsck. It performs no network Git operation.

## Verification

Every Python, pytest, and compileall process ran serially under
`scripts/ops/workstation_heavy.ps1`, using profile
`workstation_offline_v1` and
`C:\Users\Michael\Documents\github\weather\venv\Scripts\python.exe`.
Failed evidence was retained. No two heavy processes overlapped.

| Gate | Result |
| --- | --- |
| Final prototype probes | **8 passed** in 10.61 s |
| Complete new operation test file | **10 passed** in 36.05 s; JUnit SHA-256 `2f35909c22db13626d091caa083e462daa09f56d7d6fdb89c823102a4b149f1b` |
| Heartbeat contract | **Pass** in 4.416 s: atomic JSON remained readable, sequence and monotonic time increased, read-only status returned `RUNNING` |
| Deadline/teardown contract | **Pass** in 5.931 s with a 4-second deadline: child root, Codex, and separately spawned descendant PIDs were all absent after confirmed Job teardown |
| Successful handback | **Pass** in 4.144 s: exact result identity, clean worktree, bundle verify, and strict fsck all passed |
| Windows PowerShell 5.1 AST | **Pass**, 7,576 tokens parsed from the changed runner |
| `-m compileall -q app src tests` | **Pass** |
| Agent-doc audit | **Pass** |
| Roadmap lint/check | **Pass** |
| Cumulative `git diff --check` | **Pass** |

The appropriate complete workstation suite executed on the final
implementation tree: **4,225 passed, 18 skipped, 12 failed, and 862 subtests
passed** in 599.04 seconds. All twelve failures are the unchanged
`tests/operations/test_experiment_executor.py` Windows `MAX_PATH` cases. A
second run of that complete file under `C:\x9t` reproduced **12 passed and 12
failed** in 4.19 seconds. This branch changes no `app/` or `src/` file and does
not change the failing test file. The sealed source commit's own independent
review report records these same twelve source-baseline failures as assigned to
draft PR #11. They were not weakened, skipped, xfailed, mocked away, relabeled,
or repaired speculatively.

The first full-suite attempt mistakenly used the long mission evidence path as
`--basetemp`; it retained **4,103 passed, 19 skipped, 133 failed, and 862
subtests passed** in 566.38 seconds. Representative failures were path-length
`FileNotFoundError`s. The required short-root rerun reduced the artifact to the
twelve source-baseline executor failures above. JUnit SHA-256 values are
`cf996d866ce56b71ae066a16adcf6a1c9396af16e2327a16a3b31b334ce25ddd`
for the retained long-root run,
`f7ee20f8ab4abe7aabd3090235f2bfdef750e62f066f4f0044ac19782ef9a151`
for the complete short-root run, and
`3c36a66fa0b6924fe212d11c986ca60eef9a7f34aa5dab65cbd30ce3dd1b804e`
for the exact failing-file rerun.

Earlier synthetic-probe attempts 1-4 failed because the external harness
traversed an unrelated mount or retained a pipe handle in the descendant; the
results receipt classifies each and the fifth unchanged-scope probe passed.
During implementation, focused attempts exposed and repaired Windows native
stderr handling, a PowerShell case-insensitive variable collision, fast-child
PID capture, malformed synthetic JSON, and an overlong bare-verification path.
Two AST command lines failed before parsing due quoting and were replaced by the
successful environment-bound invocation. Two roadmap lint attempts correctly
rejected Item 332 until its required literal `Why this matters:` section was
present; the final generator passed. These were introduced implementation,
test-harness, invocation, or documentation defects and are repaired in the
final tree.

## Roll classification boundary

No production roll verdict was requested or run. This workstation has no
authoritative live closure evidence, so the canonical dynamic verdict is
`UNDECIDABLE`; no manual path or prose inference substitutes for
`scripts/ops/roll_verdict.ps1` on the production host.

For reviewer routing, all changed files are PowerShell control-plane code,
tests, or documentation and have no canonical Python import closure. That
structural observation is not a production roll verdict. The per-file dynamic
verdict remains `UNDECIDABLE` for the runner, its tests and owning documentation,
Item 332, both roadmap indexes, this report, and the JSON handback.

## Reboot and supervision boundary

The Job and wrapper remain effective across an SSH/client disconnect while the
wrapper process and host remain alive. A host power loss destroys in-memory Job
state and cannot produce a post-reboot terminal receipt. The status reader can
identify the boot change from frozen boot identity, but this branch implements
no Scheduler task, service, restart supervisor, or automatic next attempt.
Cross-reboot continuation requires a separately reviewed supervisor design.

## Prohibited-action audit and handback

No production host, Scheduler mutation, credential store, weather provider,
exchange, capture runtime, model, outcome, promotion, release, merge, live
order, or live-trading action was used. No branch was pushed and no PR was
opened or edited. The root checkout was not modified. P0 used only the mission's
credential-disabled exact-ref check; no authenticated Git action occurred.

The report and JSON receipt are committed after the implementation commit. The
receipt uses the required external binding rule because it cannot contain the
hash of the commit/tree containing its own bytes. After the final handback
commit, a create-only external binding records the final tip/tree, receipt
hash, and complete bundle hash. Bundle verification, fetch into an isolated
bare repository, and strict full fsck provide the final external proof. Nothing
in this handback grants integration or runtime adoption authority.
