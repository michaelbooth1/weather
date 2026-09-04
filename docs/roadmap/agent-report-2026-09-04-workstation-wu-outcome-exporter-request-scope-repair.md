# COMPLETE_WORKSTATION_QUALIFIED_REQUEST_SCOPE_REPAIR

**Verdict: `COMPLETE_WORKSTATION_QUALIFIED_REQUEST_SCOPE_REPAIR`.**

Mission `workstation-wu-outcome-exporter-request-scope-repair-2026-09-100f`
repairs the qualified 100e WU exporter so daily-row semantic validation applies
to the exact frozen request cohort for each market. Every daily CSV is still
decoded and structurally parsed in full, and every source remains bound by its
exact bytes, SHA-256, and stable file identity through publication. Requested
dates remain subject to every existing schema, unit, row-count, threshold,
bucket, duplicate, coverage, and ledger-reconciliation gate.

All implementation and verification used synthetic `tmp_path` sources only.
No real WU file, settlement value, outcome export, production source, provider,
market-data service, credential, exchange, or network endpoint was accessed.
No production export was run.

## Mission and result identity

- Sealed mission: 8,969 bytes, SHA-256
  `8831c39776c5093cbef4d27a692f52d937cb2f9b21ef4938e57c47ba88cde481`.
- Assigned workstation/principal: `DESKTOP-RFCD2GH` /
  `DESKTOP-RFCD2GH\Michael`; runner host/principal identities
  `31240dff4b7af1a8bff9df37a1f26424b5cf1ab03764ec39769cff4a1ce6f5ee` /
  `d501209aea15eecd4334a10fb6c49532ccf94b2358b409d4a718d3938969221e`.
- Source commit/tree:
  `164acb745275744768702ecaf41b8fb936ec1745` /
  `1f575f08ec89e39d540ed3ea0071f0c2878c6914`; sole parent
  `93f8fcfede0b0767caacfb3de3e460837f922c8a`.
- Stack base/tree:
  `2e20e59aae08e7367dc79e1b8102c0551e7f6904` /
  `f3855fcd456fa81df8486bf02d0f21de833ea4ff`.
- Implementation commit/tree:
  `dd926395e7b4dd42a7dd4f98c1aee1b9a4921d76` /
  `0e610f85a3ce908fa177121cc711a5aa6ad56e21`.
- Result ref:
  `refs/heads/codex/workstation-wu-outcome-exporter-request-scope-repair-2026-09-100f`.
- Result worktree:
  `C:\Users\Michael\Documents\github\weather\scratch\w\wu-outcome-exporter-request-scope-repair-09-100f`.
- Final bundle:
  `C:\Users\Michael\Documents\Codex\runs\workstation-wu-outcome-exporter-request-scope-repair-2026-09-100f\publication-transfer-final.bundle`.

P0 verified the exact source/base objects, trees, sole parent, ancestry, source
ref, controller path, initially absent result ref/worktree, assigned host and
principal, clean repository/source/controller state, free shared mutex, absent
poison marker, and absence of a conflicting workstation-heavy or portable-live
worker. The immutable 100e terminal receipt matched SHA-256
`b8710b8db4afcd82e2c521b65a8f0d9e8bde386f9dc72f27610706e3041c187e`,
state `COMPLETE_VALIDATED`, exit 0, implementation
`93f8fcfede0b0767caacfb3de3e460837f922c8a` / tree
`d8e2e13cadc252a5db04670449e75fa34f90a730`, final
`164acb745275744768702ecaf41b8fb936ec1745` / tree
`1f575f08ec89e39d540ed3ea0071f0c2878c6914`, and complete-bundle SHA-256
`39a999bde992260ddeca3c93afd96552444da4a6df6313decbe889254a392e49`.

The sealed mission supplied the production-attempt facts as external evidence:
terminal reason `E_DAILY_BUCKET`, zero published files, absent final and staging
directories, and zero outcome values printed. This workstation did not contact
that host or open its sources, export, or create-only receipt.

## Bounded repair and falsifiers

`_build_rows` now derives a separate immutable requested-date set for every
configured market from the already validated request rows. That derivation
independently rejects a non-object request, an unknown request market, an empty
market set, a non-canonical ISO date, or a duplicate date within a market.
`_parse_daily` receives that set explicitly and requires its selected key set
to match exactly.

The parser uses strict CSV mode and consumes the complete input. Header shape,
missing or extra row fields, missing/duplicate/case-colliding columns, malformed
CSV, and encoding errors remain whole-file blockers. It examines the literal
`local_date` before row semantics. Only a row whose literal date belongs to the
market's requested set is checked for an allowed daily schema, canonical ISO
date, configured native unit, numeric row count, the 18-row minimum, and an
integral finite bucket. Requested dates must appear exactly once. Ledger/WU
bucket reconciliation and the 100e source, identity, atomicity, split-root,
portable-copy, ACL, output-leak, and downstream-authority gates are unchanged.

The pre-repair positive falsifier reproduced the defect: a structurally valid
irrelevant historical row stopped the old parser with `E_DAILY_SCHEMA`. After
the repair, invalid historical schema, date, unit, row count, and blank,
nonintegral, or nonfinite bucket semantics outside the cohort are ignored. Two
fresh destinations produced byte-identical 96-row artifacts containing only
the exact requests. All 24 synthetic source files retained their exact bytes
and hashes before and after both exports, and the manifest bound each identity.

The same defects on requested dates failed closed. Explicit negatives covered
missing and duplicate requested dates, below-threshold support, wrong schema or
unit, blank/nonfinite/nonintegral bucket, invalid row count, non-ISO request,
empty per-market request set, duplicate request, request-market mismatch, and
selected/requested key-set mismatch. Extra fields, missing fields, and malformed
quoting on irrelevant rows also failed as structural CSV errors.

The retained split-root test exported from a clean synthetic data worktree with
the exact spec in a distinct clean linked worktree. The retained portable-copy
test required both exact producer hashes, preserved the default producer ACL
equality check, returned the copied-root ACL proof, and proved no artifact file
mutation. Both the successful portable path and a blocked CLI path exposed no
synthetic outcome value on stdout or stderr.

## Serial workstation verification

Every recognized Python/test command ran serially through
`scripts/ops/workstation_heavy.ps1` and its shared mutex.

| Gate | Result |
| :--- | :--- |
| Pre-repair positive falsifier | PASS: reproduced `E_DAILY_SCHEMA` on an irrelevant historical row |
| Focused contract/exporter tests | PASS: 86 passed in 57.11 seconds |
| Compileall for `app`, `src`, and `tests` | PASS |
| Import/schema/module-size/workload-wrapper/host-hook ratchets | PASS: 91 passed, 15 expected skips in 16.04 seconds |
| Agent document audit | PASS: 18 agent files, 840 Markdown files |
| Roadmap lint/check | PASS: generated report matches sources |
| Complete workstation suite | PASS: 4,439 passed, 18 skipped, 13 warnings, 866 subtests passed in 483.87 seconds |
| Explicit requested-scope/split-root/portable/ACL/leak proof | PASS: 15 passed in 13.94 seconds |
| `git diff --check` | PASS |

The complete suite ran exactly once at implementation commit `dd926395` under
fresh external base temp `C:\t\w100f-f1-dd926395`. No second complete suite was
needed. Its 13 warnings are the existing synthetic sklearn empty-feature and
netCDF binary-compatibility warnings. The focused post-commit proof used fresh
external base temp `C:\t\w100f-proof-dd926395`.

## Changed paths and roll verdict

The exact sorted source-to-final changed path set is:

1. `docs/operations/WU_OUTCOME_EXPORT_CONTRACT.md`
2. `docs/roadmap/agent-report-2026-09-04-workstation-wu-outcome-exporter-request-scope-repair.md`
3. `docs/roadmap/workstation-handback-2026-09-04-wu-outcome-exporter-request-scope-repair.json`
4. `src/weather/operations/wu_outcome_production_exporter.py`
5. `tests/operations/test_wu_outcome_production_exporter.py`

The required repository tool returned `UNDECIDABLE: no live closure evidence`
with exit 1 because all four live supervisor closure files are absent from this
isolated workstation. No per-file closure mapping or roll classification was
derived manually. Production integration must rerun
`scripts\ops\roll_verdict.ps1 -Branch codex/workstation-wu-outcome-exporter-request-scope-repair-2026-09-100f`
against current live closure evidence.

## Immutable handback and prohibited-action audit

The report and generic receipt are committed separately from the implementation.
Sealing then creates a complete-history bundle, verifies it, fetches it into a
new isolated bare repository, runs strict full fsck, and reproduces the raw
committed report and receipt identities. The committed receipt keeps its final
tip/tree/bundle fields null; the unchanged outer runner owns those post-commit
bindings and the immutable terminal receipt.

No production host, Scheduler, credential, provider, exchange, GitHub, remote,
market-data, real production data, corpus, ledger, model, prediction, scoring,
campaign, promotion, or live action occurred. No fetch, pull, push, merge, PR,
prior-attempt rerun, complete-suite rerun, production export, real outcome
access, gap/spec regeneration, or old-worktree cleanup occurred. Only the exact
result branch/worktree, synthetic temporary test state, required commits, final
bundle, and runner-owned create-only terminal evidence are written.

A reboot destroys the in-memory Job and runner state. Attempt 1 is the sole
authorized attempt; the committed pre-terminal receipt is not publication
authority until the runner records `COMPLETE_VALIDATED` with the final result
tip/tree, bundle SHA-256, and committed report/receipt blob identities.
