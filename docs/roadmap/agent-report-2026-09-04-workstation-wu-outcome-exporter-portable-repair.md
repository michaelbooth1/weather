# COMPLETE_WORKSTATION_QUALIFIED_PORTABLE_REPAIR

**Verdict: `COMPLETE_WORKSTATION_QUALIFIED_PORTABLE_REPAIR`.**

Mission `workstation-wu-outcome-exporter-portable-repair-2026-09-100e`
repairs both reproduced defects in the 100c WU outcome exporter using synthetic
sources only. The public exporter now accepts a read-only data worktree and the
exact tracked frozen spec from a separate reviewed worktree of the same Git
repository. A new explicit portable-copy validator accepts a byte-perfect copy
only when the caller supplies the exact producer manifest-file SHA-256 and the
producer-bound payload SHA-256 together. Default producer validation still
requires the manifest ACL proof to equal the current export-directory ACL.

No real settlement value, real outcome export, production source, provider,
market-data service, credential, exchange, or network endpoint was accessed.
No production export was run.

## Mission and result identity

- Sealed mission: 11,142 bytes, SHA-256
  `e440e9a8d8b971e7dfacfaecb41be821815dbf99527ec9fe62c5d9709065c637`.
- Assigned workstation/principal: `DESKTOP-RFCD2GH` /
  `DESKTOP-RFCD2GH\Michael`; runner host/principal identities
  `31240dff4b7af1a8bff9df37a1f26424b5cf1ab03764ec39769cff4a1ce6f5ee` /
  `d501209aea15eecd4334a10fb6c49532ccf94b2358b409d4a718d3938969221e`.
- Source commit/tree:
  `e87af418e4aa78b3628b6da8225ed4f0288f8c06` /
  `5ad3c96d2fb051dd9a58724e906867227a53f200`; sole parent
  `93bcb73b98c22b374d9b8b074a437558b9d5801b`.
- Stack base/tree:
  `2e20e59aae08e7367dc79e1b8102c0551e7f6904` /
  `f3855fcd456fa81df8486bf02d0f21de833ea4ff`.
- Implementation commit/tree:
  `93f8fcfede0b0767caacfb3de3e460837f922c8a` /
  `d8e2e13cadc252a5db04670449e75fa34f90a730`.
- Result ref:
  `refs/heads/codex/workstation-wu-outcome-exporter-portable-repair-2026-09-100e`.
- Result worktree:
  `C:\Users\Michael\Documents\github\weather\scratch\w\wu-outcome-exporter-portable-repair-09-100e`.
- Final bundle:
  `C:\Users\Michael\Documents\Codex\runs\workstation-wu-outcome-exporter-portable-repair-2026-09-100e\publication-transfer-final.bundle`.

P0 verified the exact source/base objects, trees, sole parent, ancestry, source
ref, controller path, initially absent result ref/worktree, assigned host and
principal, clean repository/source/controller state, free shared mutex, absent
poison marker, and absence of a conflicting workstation-heavy or portable-live
worker. The immutable 100c terminal receipt matched SHA-256
`3cf74fa248762f6272e4e5f274e144171b85a5fb3526be036664c52b4a2b72ff`,
state `COMPLETE_VALIDATED`, exit 0, and its required implementation, final, and
bundle identities. The 100d terminal receipt matched SHA-256
`87b4e5ff7f6e31d5f9a058955bd4d4b163980b404b9d6738a2f02364d452c533`,
state `INTERRUPTED`, exit 22, and `child_tree_teardown_confirmed=true`; its two
dormant worktrees and source-identical branch remained clean and untouched.

## Repair 1: independently tracked spec worktree

`--repo-root` remains the absolute, exact Git top level for the 24 read-only
source paths. `_load_frozen_spec` now discovers the spec's Git top level from
its existing parent, requires absolute/existing/non-reparse/exact-case ancestry
and the exact frozen relative path, proves the file is tracked there, and
requires both worktrees to resolve to the same Git common directory. All exact
spec file/self hashes, gap binding, schema, canonical parsing, and all-false
downstream-authority checks remain unchanged.

The synthetic integration proof created two linked Git worktrees. The data
worktree contained only ignored synthetic `data/` sources; the spec worktree
contained the exact tracked frozen spec. The public CLI created byte-identical
two-file exports in two fresh destinations, and both worktrees remained clean.
Exact-byte untracked, wrong-relative, wrong-case, reparse, and different-Git-
repository spec inputs were rejected. Existing source escape/reparse and
pre/post identity tests remained green.

## Repair 2: producer-bound portable-copy validation

Default `validate-export` retains its prior result and CLI surface and still
requires the producer ACL proof to equal the current root ACL. The explicit
`validate-portable-copy` command requires both producer hashes; there is no
boolean ACL bypass or fallback. It verifies the exact producer manifest bytes
before parsing, the exact payload bytes, canonical manifest and payload
encodings, manifest self-hash, spec/gap bindings, request coverage and order,
native units, configured WU identities, source bindings, byte/file bounds, and
all-false authority. It validates the producer ACL proof internally, skips only
producer-versus-copy ACL equality, reads the actual copied-root ACL, and returns
that proof for optional create-only external sealing.

A deterministic different-ACL synthetic copy failed default validation and
passed portable validation only with both exact hashes. Missing, partial,
malformed, and wrong hashes; manifest/payload tampering; extra files; and
reparse roots failed closed. Hash and byte-count checks proved portable
validation changed neither artifact file. A distinctive synthetic outcome
value was absent from stdout and stderr.

## Public placeholder-only commands

These forms are deliberately non-runnable until an operator supplies reviewed
paths and producer hashes. Their argument vectors must be encoded and run
through `scripts/ops/workstation_heavy.ps1` on the assigned workstation.

```text
python -m weather.operations.wu_outcome_export_contract export-production --repo-root <absolute-read-only-data-worktree> --spec <absolute-path-to-exact-tracked-spec> --destination <absolute-new-export-directory>
python -m weather.operations.wu_outcome_export_contract validate-export --spec <absolute-path-to-exact-spec> --export-root <absolute-producer-export-directory>
python -m weather.operations.wu_outcome_export_contract validate-portable-copy --spec <absolute-path-to-exact-spec> --export-root <absolute-copied-export-directory> --expected-producer-manifest-sha256 <exact-producer-manifest-file-sha256> --expected-producer-payload-sha256 <exact-producer-payload-sha256>
```

## Serial workstation verification

Every recognized Python/test command ran serially through
`scripts/ops/workstation_heavy.ps1` and its shared mutex.

| Gate | Result |
| :--- | :--- |
| Focused contract/exporter tests | PASS: 72 passed in 45.65 seconds |
| Compileall for `app`, `src`, and `tests` | PASS |
| Import/schema/module-size/workload-wrapper/host-hook ratchets | PASS: 91 passed, 15 expected skips in 15.78 seconds |
| Agent document audit | PASS: 18 agent files, 839 Markdown files |
| Roadmap lint/check | PASS: generated report matches sources |
| Complete workstation suite | PASS: 4,425 passed, 18 skipped, 13 warnings, 866 subtests passed in 478.65 seconds |
| Explicit split-root/portable proof set | PASS: 8 passed in 12.39 seconds |
| `git diff --check` | PASS |

The complete suite ran exactly once at implementation commit `93f8fcfe` under
fresh external base temp `C:\t\w100e-f1-93f8fcfe`. No second complete suite was
needed. Its 13 warnings are the existing synthetic sklearn empty-feature and
netCDF binary-compatibility warnings. The first pre-commit focused run exposed
one inconsistent synthetic evidence field; the fixture was repaired, and two
subsequent complete focused-file runs passed all 72 tests. No product defect
was hidden or gate weakened.

## Changed paths and roll verdict

The exact sorted source-to-final changed path set is:

1. `docs/operations/WU_OUTCOME_EXPORT_CONTRACT.md`
2. `docs/roadmap/agent-report-2026-09-04-workstation-wu-outcome-exporter-portable-repair.md`
3. `docs/roadmap/workstation-handback-2026-09-04-wu-outcome-exporter-portable-repair.json`
4. `src/weather/operations/wu_outcome_export_contract.py`
5. `src/weather/operations/wu_outcome_production_exporter.py`
6. `tests/operations/test_wu_outcome_production_exporter.py`

The required repository tool returned `UNDECIDABLE: no live closure evidence`
with exit 1 because all four live supervisor closure files are absent from this
isolated workstation. No per-file closure mapping or roll classification was
derived manually. Production integration must rerun
`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-wu-outcome-exporter-portable-repair-2026-09-100e`
against current live closure evidence.

## Immutable handback and prohibited-action audit

After the separate report/receipt commit, sealing requires a complete-history
bundle, bundle verification, fetch into a new isolated bare repository, strict
full fsck, and raw committed report/receipt identity reproduction. The
committed generic receipt leaves its final tip/tree/bundle fields null. The
unchanged outer runner owns those post-commit bindings and the immutable
terminal receipt.

No production host, Scheduler, credential, provider, exchange, GitHub, remote,
market-data, real production data, corpus, ledger, model, prediction, scoring,
campaign, promotion, or live action occurred. No fetch, pull, push, merge, PR,
prior-attempt rerun, complete-suite rerun, production export, real outcome
access, or old-worktree cleanup occurred. Only the exact result branch/worktree,
synthetic temporary test state, required commits, final bundle, and runner-owned
create-only terminal evidence are written.

A reboot destroys in-memory Job and runner state. Attempt 1 is the sole
authorized attempt; the committed pre-terminal receipt is not publication
authority until the runner records `COMPLETE_VALIDATED` with the final result
tip/tree, bundle SHA-256, and committed report/receipt blob identities.
