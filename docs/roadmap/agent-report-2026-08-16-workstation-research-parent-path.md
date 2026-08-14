# Workstation report 2026-08-16 — research-parent path

**VERDICT: THE EMPTY-STORE RESEARCH-LINEAGE CYCLE IS CLOSED. CURRENT MASTER CAN
ASSEMBLE FIRST-PARTY LINEAGE, FREEZE AND REVERIFY A RESEARCH-ONLY ALL-SHADOW
PARENT, AND `base_retrain` ACCEPTS ITS 12-MARKET / 84-COMPONENT CONTRACT. THE
RETRAIN THEN BLOCKS ON THE ALREADY-KNOWN ABSENT OFFICIAL BASE AND PIT CORPUS
MANIFESTS. NO POINTER, PROMOTION, ACTIVATION, MODEL FIT, OR PRODUCTION WRITE
OCCURRED.**

The implementation extends the existing
`weather.operations.all_shadow_release_bootstrap` command with an explicit
first-party corpus source. It assembles the code-owned first-retrain matrix,
requires every expected market/date/cutoff cell, hashes the canonical rows,
extracts the exact pooled-bundle model inputs, and freezes both hashes plus the
complete assembly contract into `training_evaluation_corpus`.

This is a new fail-closed lineage source, not a relaxation. Production
candidates still cannot use research lineage overrides. The existing verified
immutable-release source still requires its release, role, and payload hashes.
The new `first_party_corpus_assembly` source requires `verification_status=PASS`
and exact matches among the frozen assembly-contract hash, assembled row count,
final-refit corpus hash, model-input hash, and market count. A mismatch is a
contract error.

## Branch, basis, and safety

- Branch:
  `codex/workstation-build-the-research-parent-path-2026-09-53a`
- Base: `origin/master` at
  `277b78141bf0869f80b03d9ee923bf11be380419`.
- Implementation commit used by the immutable release:
  `c74f0db4` (`Build first-party research parent lineage`).
- `docs/operations/reserved-confirmation-window.md` was checked. Nothing is
  reserved; no retrained candidate was fitted or frozen.
- The real assembly read the existing workstation mirror. The worktree path
  helper was pointed at that read-only mirror before importing the bootstrap;
  no mirror byte was changed and no weather-provider endpoint was called.
- All generated output is under the two ignored scratch roots named below.
  Nothing under production `data/`, the canonical release store, a pointer,
  scheduler, loop, supervisor, settlement path, or trading state was written.
- Both before and after the rehearsal,
  `C:\Users\Michael\Documents\github\weather\artifacts\releases` and its
  `current_release.json` were absent.

## What changed

The new command inputs are:

```text
--first-party-forecast-history-root <read-only-root>
--first-party-target-date <YYYY-MM-DD>
[--first-party-holdout-year 2025]
[--first-party-forecast-training-variant rich]
```

The first two inputs are required together and are mutually exclusive with
`--model-source-release`. The path uses
`base_retrain._training_population_for_target()` as the population authority,
so it cannot silently choose a smaller season, market set, cutoff set, or
station-day exclusion set. It calls the existing rich forecast resolver and
feature assembly for each built-in market and requires the exact expected cell
key set before computing lineage.

The pooled bundle is not fitted here. Its exact 278 input fields are read from
the already hash-verified copied bundle. This follows the pooled trainer's
existing lineage shape: canonical source rows are hashed before band-row
expansion, while the final model-input field set includes the derived band
features. The output remains `research_only`, all-shadow, and
`production_capable=false`.

No serving loader, promotion contract, release-pointer parser, nightly step
order, or `base_retrain` check changed.

## Cause closure

| Cause from §4a-bis | Result |
| --- | --- |
| Nightly bootstrap is production-capable but the base parent must be research-only | **Closed by using the existing all-shadow bootstrap.** The immutable result reverifies as `candidate_mode=research_only` and `production_capable=false`. |
| Empty store has no research-lineage source | **Closed in code and exercised on real local inputs.** `first_party_corpus_assembly` supplies a hash-bound exact matrix without a prior release. |
| Nightly calls `base_retrain` before candidate release construction | **Closed without reordering nightly.** The research parent is built first by a separate bounded command, then supplied to `base_retrain`. |

## Real first-party corpus evidence

Target `2026-06-10`, variant `rich`, holdout 2025:

| Measure | Result |
| --- | ---: |
| Runtime markets | 12 |
| Selection-training rows, 2021-2024 | 10,080 |
| Evaluation rows, 2025 | 2,520 |
| Final-refit rows | **12,600 / 12,600** |
| Exact pooled model inputs | 278 |
| Canonical source fields | 286 |
| Assembly wall time | 24.261 s |
| Final-refit corpus SHA-256 | `b83bf594b8e8d6ca5ec436af5fd2783176524a20945fd980e4b8837fe86728fc` |
| Assembly-contract SHA-256 | `3c9be42dfbb6f48f702ccb4944960c464d2ee559d8321b8315fc36e8d9ba9097` |
| Model-input-fields SHA-256 | `98684e12753b8e2a994268b58d641cad7c8a6e834a7268e02efb42338b5f02f3` |

This run did not separately sample RSS. The directly comparable `-09-50a`
assembly measured 315.83 MiB peak RSS for the same 12,600-cell path. No fit
stage was reached, so fit resources remain unidentified.

## Immutable scratch parent

Scratch root:

```text
C:\Users\Michael\Documents\github\weather\scratch\rp53a-run-c74f0db4
```

| Field | Result |
| --- | --- |
| Release ID | `research-parent-c74f0db4` |
| Status | `PASS` |
| Candidate mode | `research_only` |
| Production capable | `false` |
| Route | 12 shadow, 0 promote, 0 blocked |
| Base graph | 12 markets, exact seven components each |
| Manifest SHA-256 | `487c63d4846eb937e97e880f205dfcfd1e11cd936ac4d4c8fa3af90061f6121b` |
| Semantic contract SHA-256 | `1673a2d52789ae8cde25718ee5d16c262e76a12dd4e9749304b994a82b634d75` |
| Files / bytes | 102 / 230,124,199 |
| Bootstrap wall time | 28.797 s |
| Receipt self-hash | `efc6be9065e97646630467f684a3e9703447dcf2f4e41cbb1149f863a014e65b` |
| Independent runtime/hash verification | `PASS` |
| Pointer before / after | absent / absent |
| Activation | `NONE` |

The copied tracked pooled bundle is bound as
`3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`.
The frozen training/evaluation role is 15,370 bytes, file SHA-256
`01c53b18a89b89e01af88faa986d7fd5700ccf54ea7583c14bac3afc84d955f8`,
and payload self-hash
`3c5e6be7d74c6f83bb45a5dfe72c14dbb5654783d5d12b2d92a020ee8957b392`.

## Parent acceptance and the pointer boundary

`base_retrain` was not weakened. It still requires the explicit parent to
match the active identity passed through `--active-pointer`. A distinct
research-store pointer is therefore the right operational design; the
production pointer need not be used.

Current master has only one real pointer writer:
`release_lifecycle_cli promote --bootstrap-first-release`. That is a reviewed
release-lifecycle promotion and this handoff explicitly forbade promotion and
activation. The rehearsal therefore did not manufacture a pointer file or
assert human review/boundary evidence. It injected only the intended scratch
release ID and manifest in memory, then ran the unmodified actual
`load_parent_contract()` and the rest of `run_base_retrain()`.

The parent contract returned:

```json
{
  "status": "PASS",
  "parent_release_id": "research-parent-c74f0db4",
  "parent_manifest_sha256": "487c63d4846eb937e97e880f205dfcfd1e11cd936ac4d4c8fa3af90061f6121b",
  "feature_contract_id": "sha256:57cb0265f0f0c1c8a4fdf4719113afdd73c9385233f3af3238bb84ed2c0b128d",
  "market_count": 12,
  "base_market_component_role_count": 84
}
```

The scratch base-retrain run then reached and completed preflight evaluation.
Its `parent_release` check is `PASS`, its output-isolation check is `PASS`,
`fit_authorized=false`, and no release or market fit exists. Plan file SHA-256
is `2462e293f6f9cff707156a44040da784743e31a9f828127823756cbe6839e2ec`;
preflight file SHA-256 is
`c9682ede5913d3c6769e7ebaa699f920ad6f406fc93057727310cef0de21b29d`.

This satisfies the requested code-path proof without performing the forbidden
pointer transition. Establishing a persistent scratch research pointer remains
a separate reviewed release-lifecycle operation; silently bypassing that
review would weaken, not complete, the contract.

## The next blocker

As `-09-50a` predicted, the next blocker is input publication, not the parent:

- no official `all_market_base_retrain_corpus_manifest_v0.1` was supplied;
- no verified immutable PIT forecast corpus with the exact 12,600-cell
  selection binding was supplied.

For the bounded proof, an existing unrelated JSON config was passed to both
arguments so preflight could name the failure without fitting. The result has
22 blockers, including `CORPUS_SCHEMA`, 12 `WU_MARKET_MISSING` rows,
`WU_FLEET_MISMATCH`, `PIT_FORECAST_CORPUS_UNVERIFIED`, and the exact 12,600-row
PIT matrix/binding failures. These are deliberate placeholder-input failures,
not new evidence that the real first-party feature rows are incomplete.

## Production-host reproduction

Run only after this branch is integrated, from the existing production
checkout. Choose a new short scratch root; never target `artifacts\releases`.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
$python = '.\venv\Scripts\python.exe'
$run = 'C:\tmp\weather-rp53a-parent'
$release = 'reviewed-research-parent'

if (Test-Path artifacts\releases) {
  throw 'Canonical production release store must remain absent.'
}
if (Test-Path $run) {
  throw 'Choose a new empty scratch root.'
}

& $python -B -m weather.operations.all_shadow_release_bootstrap `
  --candidate-id $release `
  --run-root $run `
  --repo-root (Get-Location).Path `
  --first-party-forecast-history-root data\forecast_history `
  --first-party-target-date 2026-06-10 `
  --first-party-holdout-year 2025 `
  --first-party-forecast-training-variant rich
if ($LASTEXITCODE -ne 0) { throw 'Research-parent bootstrap failed.' }

$store = "$run\release-bootstrap\releases"
& $python -B -m weather.operations.release_lifecycle_cli `
  --releases-root $store `
  --pointer "$store\research_parent_pointer.json" `
  --repo-root (Get-Location).Path `
  verify $release
if ($LASTEXITCODE -ne 0) { throw 'Research parent did not reverify.' }

if (Test-Path "$store\current_release.json") {
  throw 'Bootstrap unexpectedly wrote a pointer.'
}
```

Expected: 12,600 rows; `research_only`; `production_capable=false`; 12 shadow
routes; 84 base roles; verification `PASS`; no pointer. Do not run the
promotion command merely to extend this proof. Once a separately reviewed
research pointer and the two official corpus manifests exist, pass that
distinct pointer through `base_retrain --active-pointer`; no code change is
needed in `base_retrain`.

Focused deterministic verification:

```powershell
& $python -B -m pytest -p no:cacheprovider -q `
  tests\operations\test_all_shadow_release_bootstrap.py `
  tests\operations\test_release_candidate_contract.py `
  tests\operations\test_base_retrain.py `
  tests\model\test_corpus_lineage.py

& $python -B -m compileall -q app src tests
& $python -B -m weather.operations.agent_docs_audit
```

Observed: **60 passed**; compileall passed; agent-doc audit passed (18 agent
files, 740 Markdown files).

## Mechanical roll verdict

The repository-owned command was run from the primary checkout, where the
required live-closure evidence exists:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-build-the-research-parent-path-2026-09-53a
```

Result: **ROLL-FREE**. The command inspected all three live closures and
explicitly classified both changed importable files `free`. The dormant
`clob_enrichment` closure was mechanically subsumed by the live closures.

| Changed file | Mechanical disposition |
| --- | --- |
| `src/weather/operations/all_shadow_release_bootstrap.py` | free |
| `src/weather/operations/release_candidate_contract.py` | free |
| `tests/operations/test_all_shadow_release_bootstrap.py` | non-importable |
| `docs/operations/NIGHTLY_RETRAIN_RUNBOOK.md` | non-importable |
| `docs/roadmap/agent-report-2026-08-16-workstation-research-parent-path.md` | non-importable |

## What was not done

- No provider or exchange endpoint was called; no credential was read.
- No model was fitted, scored, selected, promoted, activated, served, or
  traded. Fit resource use remains unknown.
- No production `data/`, canonical artifact, release store, pointer, tape,
  ledger, scheduler, supervisor, loop, settlement, or trading state changed.
- No serving, promotion, pointer-validation, nightly-order, base-parent,
  feature, station-day exclusion, minimum-row, or probability contract was
  weakened.
- No held-branch code was copied or resurrected.
- No confirmation dates were consumed or reserved.
- No pull request, merge, master push, branch deletion, or live restart was
  performed.
