# Workstation unattended mission runner portable binding repair

**Mission:** `workstation-unattended-mission-runner-portable-binding-repair-2026-09-99c`

**Mission SHA-256:**
`b695e2f30d13a573476b1e5a8feb166c856a0642c5f7a10ee85c54162f56bc41`

**Verdict:** `PASS_REPAIRED`

**Implementation commit:** `215c7a661e02672ca4aab96d1eba122ed6e03c60`

**Implementation tree:** `330d0833771eed04954c140ea2d77f50f8ca3398`

Successful handback validation now resolves the required report and receipt at
the validated final tip, verifies that each object is a Git blob, and streams
raw `git cat-file blob` stdout directly into SHA-256. Terminal validation
exports the blob OID, byte length, and SHA-256 for both files. Clearly named
worktree length/hash values remain diagnostics and are not publication
identities.

## Frozen identity and P0

All preconditions passed before the result ref or worktree was created.

| Proof | Result |
| --- | --- |
| Source | `45cc36c31be9e9c64f1f216a1d772407736655a7`; tree `19d736a8df0ef6503ae36960922d147ada3a4a69`; sole parent `cb2b5c6eaafc51d67eb42cad009502506e5e6ec5` |
| Stack base | `ca75c2e476e865047f07dc9856e5897533834684`; tree `1c2a7fd18dacc84c6a0e9abd4afe837c0bab3801`; confirmed ancestor of source |
| Result branch/worktree | Both absent before creation; created only as `codex/workstation-unattended-mission-runner-portable-binding-repair-2026-09-99c` and `C:\Users\Michael\Documents\github\weather\scratch\w\unattended-runner-portable-binding-repair-09-99c` |
| Worktrees | Repository root, 99b source, and detached 99c controller were clean and exact |
| Workstation | `DESKTOP-RFCD2GH`, principal `DESKTOP-RFCD2GH\Michael`; tracked host/principal assignment matched; dedicated capture-host identity did not match |
| Workload controls | Host-global mutex available without abandonment; poison marker absent; no conflicting heavy or portable worker |
| 99b bundle | 516,984,478 bytes; SHA-256 `bcaa42f59f35eab32edf0d71a431c3ca358d9358f2a5a7a71f5a038f19ec9147` |
| 99b external binding | 11,925 bytes; SHA-256 `4a926b657e91c7754a6881e60db89c70058a3fa1f55f60050a38face89163139` |

No remote query, fetch, pull, LFS transfer, or network fallback was used. The
99b source bundle and binding were read-only evidence and are rechecked at
closeout.

## Observed mismatch and red proof

The 99b external binding used the receipt's 19,441-byte CRLF worktree content,
SHA-256
`d0ce9e67d37624504a90f7f5cf2bef6af75fd78ab5325f5aadbbcd45f8136ee1`.
The exact committed object was blob
`c78ed0e0d63aa80b1d722ca8eaf08225d8831320`, containing 19,163 LF bytes with
SHA-256
`345e655e46ea1aa30639a1f35e4275eb6f12fbdba4322eda6476c840eaf5f843`.
The 278-byte difference came from `.gitattributes` normalization. A clean
worktree did not imply equal bytes.

The local deterministic falsifier committed CRLF report and receipt files
under `text eol=lf`. The unchanged 99b runner returned the worktree hashes:

| File | Worktree identity returned by 99b | Committed blob identity |
| --- | --- | --- |
| Report | 32 bytes; SHA-256 `5ec8df95a7691cd28312c1bca8a0b2aee4233827c83a77dce310bb2b34f1f6fb` | `eef3712c6bc2fffb7d0d9c8976158403b90f5f34`; 31 bytes; SHA-256 `da8969e3174ecfbc26864a7eecce75223e34c69f05296f48de4fd66d55f37d2c` |
| Receipt | 2,343 bytes; SHA-256 `c8bea85f7ba82656a4db413fbfe67556a2a75d52c2d893189d9ea0797aeed528` | `8a94f738eb6c418dd537947ee8eec8d94cea2399`; 2,294 bytes; SHA-256 `962f17ce2e8ce2915fb10bad7638c3a275f40c84223ad1df9858df84e13e00fd` |

The red test failed exactly one case in 3.21 seconds. Its create-only JUnit is
3,178 bytes, SHA-256
`a48f0370f9d2c8e4f6af87329d7c6a55a1924bc1458fa96534dff9ad85d75f9d`.

## Repair and green proof

`Get-CommittedBlobIdentity` first resolves `<validated-tip>:<required-path>`,
requires a 40-character blob OID and `cat-file -t == blob`, and parses the
declared `cat-file -s` length. It starts the already resolved and claimed
`git.exe` directly with shell execution disabled, disables credential prompting
in the process, hashes bytes read from `StandardOutput.BaseStream`, drains
standard error concurrently, and rejects start, stream, exit, hash-shape, or
length disagreement. It performs no text decoding, shell redirect, temporary
file, credential lookup, or network operation.

The same focused case passed in 3.62 seconds. Terminal validation exported:

| File | Committed blob identity | Worktree diagnostic |
| --- | --- | --- |
| Report | `eef3712c6bc2fffb7d0d9c8976158403b90f5f34`; 31 bytes; SHA-256 `da8969e3174ecfbc26864a7eecce75223e34c69f05296f48de4fd66d55f37d2c` | 32 bytes; SHA-256 `5ec8df95a7691cd28312c1bca8a0b2aee4233827c83a77dce310bb2b34f1f6fb` |
| Receipt | `8885a9ed9bf511429f7d79483f11985ed6c2faa3`; 2,294 bytes; SHA-256 `da792fe70656f1d729ea62d3957378cb7bb1c48f9c47f2d192d0817c79f634ca` | 2,343 bytes; SHA-256 `7a1c7bd81133683f2621a0909fcf89d38db02e93f334c497f85cd57a3fe53399` |

The test fetched the complete bundle into a second bare repository and
reproduced both three-part blob identities exactly. The green JUnit is 406
bytes, SHA-256
`38414bea1f9ad893b074cafb04416924bbc313def59673025afb8cc9b708cccd`.

The final report and receipt cannot contain their own blob OIDs or SHA-256
values without changing those values. Their authoritative portable identities
are therefore recorded after the final commit in the create-only external
binding at
`C:\Users\Michael\Documents\Codex\runs\workstation-unattended-mission-runner-portable-binding-repair-2026-09-99c\publication-transfer-final-binding.json`.
That binding copies the six committed-blob fields required by terminal
validation.

## Verification

Recognized Python work ran serially under
`scripts/ops/workstation_heavy.ps1`, profile `workstation_offline_v1`, with the
99c result worktree as repository root and the root-checkout interpreter. The
single full suite used short external basetemp `C:\t99c-full` and was not
rerun.

| Gate | Result |
| --- | --- |
| Focused portability test | Red: 1 failed; green: **1 passed**; both create-only JUnits retained |
| Complete runner test file | **16 passed** in 33.04 s; JUnit 2,826 bytes, SHA-256 `8dce96741f851985241510c032694bef423da13139e63d61bf5dc148ca209461` |
| Windows PowerShell 5.1 AST | **Pass**, 8,694 tokens and zero parse errors |
| Complete workstation suite | **4,231 passed, 18 skipped, 12 failed, 862 subtests passed** in 447.93 s; JUnit 728,672 bytes, SHA-256 `3f7f842591c674d81693609b90ca18fa3e9a647678ba8037554f01e9c4a57293` |
| Baseline classification | All 12 failures are the exact same `tests/operations/test_experiment_executor.py` node IDs as the retained 99b/source JUnit; set difference zero; no other test failed |
| Compileall | `-m compileall -q app src tests` passed under the workstation wrapper |
| Agent-document audit and roadmap lint/check | **2 passed** in 0.90 s after the report/receipt were written, under one wrapper-contained harness; JUnit SHA-256 `1b853ae2d642e359d5363e9fde3b2b64f0c3fe835a4869d7721f40d12c54ac32` |
| Cumulative source diff | `git diff --check 45cc36c31be9e9c64f1f216a1d772407736655a7 --` passed before the implementation commit |

The first external repository-check harness was placed under a long evidence
directory. Pytest failed during collection on an unrelated Windows untrusted
mount point before either check ran. That JUnit remains immutable at SHA-256
`6b4507b6ae68cab5834c0405631076bd404acf2f1388a0b7f8acf53d847d6175`.
The unchanged harness was copied byte-for-byte to a short path, pytest root was
pinned to the result worktree, and both required checks passed. This was not a
second complete-suite run.

## Exact changed paths

1. `docs/operations/WORKSTATION_CODEX_MISSION_RUNNER.md`
2. `docs/roadmap/active-backlog.md`
3. `docs/roadmap/agent-report-2026-09-03-workstation-unattended-mission-runner-portable-binding-repair.md`
4. `docs/roadmap/items/item-332-unattended-workstation-mission-runner.md`
5. `docs/roadmap/workstation-handback-2026-09-03-unattended-mission-runner-portable-binding-repair.json`
6. `scripts/ops/invoke_workstation_codex_mission.ps1`
7. `tests/operations/test_workstation_codex_mission_runner.py`

## Roll and authority boundary

No canonical production roll verdict was requested or run because the mission
forbids production contact. The dynamic result is `UNDECIDABLE`; no manual
substitute was used. The operations guide, generated backlog, Item 332, report,
and receipt are `docs/` and structurally roll-free. The changed `.ps1` control
plane is structurally roll-free under the durable delegation contract. The
test file is test-only and is not a capture runtime module. Production must
still obtain the exact canonical verdict before any integration decision.

No production host, Scheduler, credential store, provider, exchange, market
data, outcome, capture, model, release, promotion, pull request, merge, push,
or live-trading action occurred. No LFS fetch, network fallback, automatic
retry, cleanup, persistent task, service, or daemon was added.

## Remaining reboot boundary

The kill-on-close Job, heartbeat, and deadline remain effective only while the
host and wrapper remain alive. A reboot destroys in-memory Job state. Status
can diagnose the changed boot, but no Scheduler task, service, restart
supervisor, or automatic next attempt is implemented.

The report and JSON receipt are committed separately from the implementation.
The receipt retains null self-referential final tip, tree, and bundle values.
The complete-history bundle, isolated strict fsck, final committed-blob
reproduction, executable rechecks, clean-worktree checks, and create-only
external binding follow that final commit.
