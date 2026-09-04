# COMPLETE_WORKSTATION_ADMISSIBLE_GAP_SPEC

**Verdict: `COMPLETE_WORKSTATION_ADMISSIBLE_GAP_SPEC`.**

Mission `workstation-wu-outcome-admissible-gap-spec-2026-09-100g` adds the
second exact WU production-export specification. It deterministically selects
the 94 original requests whose literal `local_status` is `missing` and records
Atlanta and Miami on `2026-06-06`, both native F, as the exact two known
low-support exclusions. The exclusions are not requested, exported, imputed,
threshold-lowered, or backfilled by this contract.

All implementation and verification used the tracked 100a specification and
synthetic `tmp_path` sources only. No real WU file, settlement value, outcome
export, production source, provider, market-data service, credential, exchange,
or network endpoint was accessed. No production export, model fit, or scoring
was run.

## Mission and result identity

- Sealed mission: 10,192 bytes, SHA-256
  `742fb8a9d02fcb5c308e0389d8888149a06eb8bf7736f236391b62ad6bcc78b0`.
- Assigned workstation/principal: `DESKTOP-RFCD2GH` /
  `DESKTOP-RFCD2GH\Michael`; runner host/principal identities
  `31240dff4b7af1a8bff9df37a1f26424b5cf1ab03764ec39769cff4a1ce6f5ee` /
  `d501209aea15eecd4334a10fb6c49532ccf94b2358b409d4a718d3938969221e`.
- Source commit/tree:
  `26c4986146aacd06e43c5f57a7a75487db28d328` /
  `27290cf5a8347c40b0e6101b37bd3d0beaf04cae`; sole parent
  `dd926395e7b4dd42a7dd4f98c1aee1b9a4921d76`.
- Stack base/tree:
  `2e20e59aae08e7367dc79e1b8102c0551e7f6904` /
  `f3855fcd456fa81df8486bf02d0f21de833ea4ff`.
- Implementation commit/tree:
  `e47857bad276e767f15baa98ccf0347cf2048ec0` /
  `e92bd4e4683d925d8bf961bc4dd751cb00322a5a`.
- Result ref:
  `refs/heads/codex/workstation-wu-outcome-admissible-gap-spec-2026-09-100g`.
- Result worktree:
  `C:\Users\Michael\Documents\github\weather\scratch\w\wu-outcome-admissible-gap-spec-09-100g`.
- Final bundle target:
  `C:\Users\Michael\Documents\Codex\runs\workstation-wu-outcome-admissible-gap-spec-2026-09-100g\publication-transfer-final.bundle`.

P0 verified the exact source/base objects, trees, sole parent, ancestry, source
ref, detached controller path and identity, initially absent result ref and
worktree, assigned host and principal, clean repository/source/controller
state, available shared mutex, absent poison marker, and absence of a
conflicting workstation-heavy or portable-live worker. The immutable 100f
terminal receipt matched SHA-256
`3401ef7a1f18140324379c44047c39728e0175faf7dd11b436881ad3e6849e65`,
state `COMPLETE_VALIDATED`, exit 0, implementation
`dd926395e7b4dd42a7dd4f98c1aee1b9a4921d76` / tree
`0e610f85a3ce908fa177121cc711a5aa6ad56e21`, final
`26c4986146aacd06e43c5f57a7a75487db28d328` / tree
`27290cf5a8347c40b0e6101b37bd3d0beaf04cae`, and complete-bundle SHA-256
`800ac1c918116ba5375ea201aa82b7a544c3a555e9518f6545a3b7d0bf2d6b00`.

The production-attempt facts were mission-supplied external evidence only:
100e stopped prepublication at `E_DAILY_BUCKET`; 100f stopped prepublication at
`E_DAILY_BELOW_THRESHOLD`; both left final and staging absent, emitted zero
outcome values, and published zero files. This workstation did not contact or
copy either production attempt.

## Exact repair and falsifiers

The original 100a file remains 41,288 bytes with file SHA-256
`cf10553a9b041a783bf5caf56b191835e2904474a4bad34dcbc1f6ad934d093f`
and self-hash
`5d370c51da7d95e1d3a62a8ff4f9d66cd3312c5eecfebcbdbaab169be505e0f9`.
It still contains exactly 96 requests: 94 `missing` plus the two exact
`present_below_threshold` keys.

The new tracked spec is 41,870 bytes with file SHA-256
`d540a5dc43845f87e811aca7670e86f5eada3f5ba8476dd1bdc2aef80bd3518c`
and self-hash
`6f02e1dcc077c69037017137725931e94d4fd652da976affda12a2109bb67407`.
Its 94 requests are byte-order-preserving copies of the original `missing`
rows. Its separate exclusion set is exactly the two original low-support rows.
The combined 94/2 key set equals the original 96-key set with no duplicate or
cross-boundary drift; all 12 markets retain a nonempty request-date set. The
gap, boundary, source-policy, stability, NWP-context, destination, manifest,
and all-false downstream-authority bindings are retained exactly.

`derive-admissible-spec` reads only the exact original file and reproduces the
tracked new spec byte-for-byte. A two-entry immutable registry keys admission by
the canonical tracked relative path plus exact file and self hashes. Export,
producer validation, and portable-copy validation accept only those two specs.
Unregistered paths, aliases, repository identities, file hashes, self-hashes,
counts, status partitions, source-spec bindings, and exclusion combinations
fail closed before publication.

The pre-repair synthetic falsifier selected the original 94 `missing` requests
and reproduced `E_REQUEST_COUNT` from the hard-coded 96-row admission. After
the repair, a synthetic new-spec source with the two excluded June 6 rows at 17
observations and all 94 requested rows admissible exported exactly 94 rows.
Both excluded keys stayed out of the payload, and two fresh destinations were
byte-identical. Moving the 17-observation defect onto a requested row still
failed at `E_DAILY_BELOW_THRESHOLD` before publication.

Requested-row schema, unit, date, row-count, bucket, missing, duplicate, and
ledger-reconciliation faults remain fail-closed. Whole-file CSV shape, source
byte/hash/file-identity stability, exact source set, two-file create-only atomic
publication, output bounds, default ACL equality, portable-copy producer-hash
binding, all-false authority, and stdout/stderr outcome-leak behavior remain
unchanged. The retained irrelevant-semantic-row, split-root, stable two-root,
and portable-copy proofs pass for both registered specs where applicable.

## Serial workstation verification

Every recognized Python/test command ran serially through
`scripts/ops/workstation_heavy.ps1` and its shared mutex.

| Gate | Result |
| :--- | :--- |
| Pre-repair admission falsifier | PASS: reproduced `E_REQUEST_COUNT` for the exact 94 `missing` rows |
| Focused contract/exporter tests | PASS: 101 passed in 63.93 seconds; the added tamper cases then passed 6/6 |
| Compileall for `app`, `src`, and `tests` | PASS |
| Import/schema/module-size/workload-wrapper/host-hook ratchets | PASS: 90 non-import cases passed with 15 expected skips; affected import file passed 22/22 after the new module was staged |
| Agent document audit | PASS: 18 agent files, 840 Markdown files |
| Roadmap regenerate and lint/check | PASS: generated report matches sources |
| Complete workstation suite | PASS: 4,455 passed, 18 skipped, 13 warnings, 866 subtests passed in 497.50 seconds |
| Explicit 94/2, low-support, split-root, portable, ACL, irrelevant-row, and leak proof | PASS: 8 passed in 15.53 seconds |
| `git diff --check` | PASS |

The first focused implementation run exposed two bounded test/guard-order
issues; both were repaired before the passing 99- and 101-test focused runs.
The first architecture batch correctly rejected the new source module while it
was untracked; staging that exact path and rerunning the affected file passed.
No product behavior was changed to satisfy either ratchet.

The complete suite ran exactly once at implementation commit `e47857ba` under
fresh external base temp `C:\t\w100g-f1-e47857ba`. No second complete suite was
needed. Its 13 warnings are the existing synthetic sklearn empty-feature and
netCDF binary-compatibility warnings. The focused post-commit proof used fresh
external base temp `C:\t\w100g-proof-e47857ba`.

## Changed paths and roll verdict

The exact source-to-final changed path set contains the implementation paths
below plus this report and its generic receipt:

1. `docs/operations/module-ownership-map.md`
2. `docs/operations/WU_OUTCOME_EXPORT_CONTRACT.md`
3. `docs/roadmap/active-backlog.md`
4. `docs/roadmap/agent-report-2026-09-04-workstation-wu-outcome-admissible-gap-spec.md`
5. `docs/roadmap/items/item-330-model-bom-loaded-identity-and-pit-challenger.md`
6. `docs/roadmap/workstation-handback-2026-09-04-wu-outcome-admissible-gap-spec.json`
7. `docs/roadmap/wu-outcome-admissible-gap-production-export-spec-2026-09-100g.json`
8. `src/weather/operations/wu_outcome_export_contract.py`
9. `src/weather/operations/wu_outcome_production_exporter.py`
10. `src/weather/operations/wu_outcome_spec_registry.py`
11. `tests/operations/test_wu_outcome_export_contract.py`
12. `tests/operations/test_wu_outcome_production_exporter.py`

The required repository tool returned `UNDECIDABLE: no live closure evidence`
with exit 1 because all four live supervisor closure files are absent from this
isolated workstation. No per-file closure mapping or roll classification was
derived manually. Production integration must rerun
`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-wu-outcome-admissible-gap-spec-2026-09-100g`
against current live closure evidence.

## Immutable handback and prohibited-action audit

The report and generic receipt are committed separately from the implementation.
The complete-history bundle is then created and verified locally; the unchanged
outer runner independently verifies it, fetches it into a new isolated bare
repository, runs strict full fsck, reproduces the raw committed report/receipt
identities, and writes the create-only terminal binding. The committed receipt
keeps final tip/tree/bundle fields null because only that terminal receipt owns
the post-commit binding.

No production host, Scheduler, credential, provider, exchange, GitHub, remote,
market-data, real production data, corpus, ledger, model, prediction, scoring,
campaign, promotion, or live action occurred. No fetch, pull, push, merge, PR,
prior-attempt rerun, complete-suite rerun, production export, real outcome
access, original gap/spec regeneration, or old-worktree cleanup occurred. Only
the exact result branch/worktree, synthetic temporary test state, required
commits, new derived spec, final bundle, and runner-owned create-only terminal
evidence are written.

A reboot destroys the in-memory Job and outer-runner state. Attempt 1 is the
sole authorized attempt; the committed pre-terminal receipt is not publication
authority until the runner records `COMPLETE_VALIDATED` with the final result
tip/tree, bundle SHA-256, and committed report/receipt blob identities.
