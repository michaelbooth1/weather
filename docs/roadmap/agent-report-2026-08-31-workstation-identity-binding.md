# Agent report 2026-08-31 — rebuild the runtime from captured identity

## Verdict

**`NO_SELECTED_IDENTITY_FULLY_RESOLVES_FROM_REACHABLE_GIT`. Identity binding does not restore
historical replay, the stale-loaded-process hypothesis is not identifiable on these rows, and the
`-09-74a` ceiling mission remains blocked.**

The 368-row decision stratum contains 366 identity-bearing rows across 63 distinct identities.
Every selected identity is only partially resolvable: each records 17–19 present files, while only
4–11 can be recovered from every Git blob reachable from every ref. The fully resolved decision
population is therefore **N=0**. There is no honest fully-resolved match rate to report.

On the same 358 rows used by `-09-75a`, the partial synthetic trees match **105 / 358 (29.33%)** at
L1 `1e-12`, versus **114 / 358 (31.84%)** under commit binding: **−2.51 percentage points**. All 105
new matches were already commit-binding matches; identity binding rescued zero prior failures and
lost nine prior matches. This rate is a diagnostic of incomplete trees, not a restored replay rate.

The eight identity-only rows can be executed from isolated partial trees, but only **1 / 8** matches;
the other seven fail. Two decision rows have no captured identity and cannot be reconstructed. The
whole-B exact identity-reconstructable population is only **111 / 28,254 (0.39%)**, not the old
commit-bound availability ceiling of 16,143 / 28,254 (57.14%). What was served on this historical
decision stratum cannot be rebuilt from what capture preserved.

## Blob resolution

The resolver enumerated 178 refs, including all 27 unmerged `origin/*` branches, without changing
any branch history. It enumerated 32,033 reachable objects and 17,348 reachable blobs. It first
checked 475 blobs seen at captured paths, then checked all 16,873 other reachable blobs for every
fingerprint still unresolved.

Captured fingerprints are SHA-256 over decoded file bytes. They are not Git object IDs. The positive
control `src/weather/model/model_base.py` maps captured SHA-256
`5df7480d99874ea5e6cc23f8313605b113bb28da65283b8395f60fa077bb8daa` to Git blob
`60fa602a9c33f11140820410ad131c3294d31212`; hashing the blob's 10,221 decoded bytes produces the
captured value exactly. Selected historical binary artifacts were reachable as ordinary pre-LFS Git
blobs, so no selected match depended on fetching an LFS object.

| Resolution scope | Fully resolved | Partially resolved | No identity | Total |
| --- | ---: | ---: | ---: | ---: |
| Selected decision identities | 0 | 63 | — | 63 |
| Selected decision rows | 0 | 366 | 2 | 368 |
| Whole-B identities | 12 | 690 | — | 702 |
| Whole-B rows | 111 | 23,683 | 4,460 | 28,254 |

Only **89 / 413** distinct target fingerprints resolve; 324 do not. The most common unresolved files
among the 63 selected identities are:

| Captured file | Identities unresolved |
| --- | ---: |
| `src/weather/model/model_features.py` | 62 |
| `src/weather/calibration/forecast_error_model.py` | 62 |
| `src/weather/calibration/settlement_lag_model.py` | 62 |
| `artifacts/manifests/f_family_secondary_artifacts.json` | 56 |
| `src/weather/model/model_distribution.py` | 54 |
| `src/weather/calibration/family_secondary_artifacts.py` | 54 |
| `src/weather/calibration/probability_calibration.py` | 54 |
| `src/weather/market/market_registry.py` | 54 |
| `src/weather/model/feature_store.py` | 8 |

Market-specific weight, coefficient, calibration, forecast-error and settlement-lag artifacts also
fail to resolve. The complete answer to “which files?” is retained per identity in
`identity-binding-2026-09-76a-manifest.json` under `resolution.selected_per_identity`; the CSV repeats
each row's unresolved path list in `identity_unresolved_files`. No missing fingerprint is replaced by
a nearby version.

## Replay result

| Population / binding | Replayed | Matched | Failed | Match rate | Failure median L1 | p90 | max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `-09-75a` commit binding | 358 | 114 | 244 | 31.84% | 0.0154 | 0.0424 | 0.7728 |
| Same rows, partial identity trees | 358 | 105 | 253 | 29.33% | 0.015076 | 0.041281 | 0.086899 |
| All identity-bearing decision rows, partial trees | 366 | 106 | 260 | 28.96% | 0.015391 | 0.042436 | 0.730676 |
| Fully resolved decision identities | 0 | 0 | 0 | — | — | — | — |

All 63 identity processes ran under the preserved **CPython 3.11.9** interpreter with the existing
repository scientific environment (NumPy 2.4.6, SciPy 1.17.1, scikit-learn 1.8.0). Nothing was
installed. Fifty-eight trees used their packaged synthetic entrypoint and five older trees used
their historical flat synthetic entrypoint. The 63 receipts record **2,534** loaded repository
module paths; every path is under its identity's disposable synthetic root, with zero empty module
sets and zero escaped `weather.*` modules.

The decision population spans 11 target dates from 2026-06-09 through 2026-06-26, 12 markets and 66
market-days; whole B spans 204 market-days. These are deterministic finite-population equality
checks, not estimates, so no confidence interval or crossed-cluster inference applies. Partial-tree
matches occur in 9 of 12 markets and both windows, but those market rates are confounded by different
missing files and are not evidence of recoverability.

| Market | Rows | Partial-tree replayed | Matched |
| --- | ---: | ---: | ---: |
| atlanta | 51 | 51 | 3 |
| austin | 40 | 40 | 16 |
| chicago | 25 | 25 | 18 |
| dallas | 37 | 37 | 4 |
| denver | 21 | 21 | 15 |
| houston | 22 | 22 | 7 |
| los-angeles | 27 | 27 | 0 |
| miami | 25 | 25 | 7 |
| nyc | 31 | 31 | 10 |
| san-francisco | 8 | 7 | 0 |
| seattle | 57 | 56 | 26 |
| toronto | 24 | 24 | 0 |

## Three-way-drift diagnosis

The source inspection behind the operator's diagnosis is correct as far as it goes:
`model_identity.py` reads configured source paths from disk when building the identity, while the
captured Git commit is `HEAD`. Neither field records the bytes held by an already-running process.
Roll-free commits can therefore advance `HEAD` without restarting that process.

The proposed residual test nevertheless **cannot be completed on the historical decision stratum**.
There are no fully resolved selected identities, and capture contains no process-start timestamp,
restart event or loaded-module content hash. Of the 253 failures on the same 358 rows, 234 have zero
feature differences, but every one still has unresolved code or artifact bytes. Those failures
cannot distinguish stale loaded code from an incomplete synthetic tree.

Declared timing proxies do not rescue identification. Partial-tree match rates by commit age are
28.1% within 1 hour, 25.0% at 1–6 hours, 17.2% at 6–24 hours and 39.3% over 24 hours; the pattern is
not monotonic. All 232 rows with available represented commit-hour metadata land in the 12:00–18:00
Toronto window, so there is no outside-window comparator. Identity-transition distance is a disk
identity transition, not a process roll. The residual-failure-class verdict is therefore **unknown**,
not “absent” and not “stale process proven.”

The forward capture repair should preserve an immutable content-addressed bundle of the actual
loaded source and artifact bytes, record module hashes after import, and bind them to process start,
restart and dependency versions. That is a report recommendation only; `model_identity.py` and all
runtime code remain unchanged.

## Artifacts and receipts

- `identity-binding-2026-09-76a.csv`: 372 rows (368 decision plus four frozen source-switch
  diagnostics), with commit and identity replay results, resolution class, missing paths, feature
  comparison and declared timing proxies.
- `identity-binding-2026-09-76a-manifest.json`: ref/blob census, 702 whole-B identity summaries, the
  complete 63-identity file resolution, grouped replay results, module `__file__` receipts, drift-test
  limitations, input hashes and campaign receipts.
- `identity-binding-2026-09-76a.sha256`: SHA-256 for the CSV and manifest.
- `measure_identity_binding_09_76a_seed.json`: frozen parent hashes, population, tolerance, outputs
  and prohibited analyses.
- `measure_identity_binding_09_76a.py`: outcome-blind identity catalog, all-ref blob resolver,
  synthetic-tree assembler, isolated Python 3.11 runner and aggregator.

The catalog pass read 204 local replay inputs and 8,890,733,675 bytes. Input receipts bind the prior
records (`f0281f86…`), census (`931f3a16…`) and `-09-75a` CSV (`d61daf4e…`). Final artifact hashes:

```text
9e604f770d3a5d09f9342443d2d8dd2c5a92f9de9d1cab1e9c5b3403c5019a23  identity-binding-2026-09-76a.csv
625fc1612658d9edfdd9715f2843ea5ef428b2db8e5e54cf1b144780ece679c3  identity-binding-2026-09-76a-manifest.json
```

One initial disposable assembly attempt invoked Git LFS smudge and stopped at GitHub authentication
before downloading an LFS object. The retained assembly forces `GIT_LFS_SKIP_SMUDGE=1`; no dependency
was installed or downloaded, and no LFS object was downloaded.

## Outcome, alpha and safety receipts

- `realized_band_read: false`
- `settlement_consulted: false`
- `candidate_probabilities_computed: false`
- `displacement_computed: false`
- `ceiling_computed: false`
- `outcome_scored: false`
- `market_compared: false`
- `C_endpoint: false`
- `alpha_allocated_by_mission: 0`
- alpha remains 7 / 20 spent and 13 available
- decision 10 remains `CLOSED_UNUSED_NOT_REASSIGNED`

No provider or exchange call, production `data/` write, registration, scheduled-task mutation,
restart, promotion, release, live trade, merge, rebase or branch deletion occurred. The 27 unmerged
branches were read only; only their already-fetched reachable objects were inspected. No model,
calibration, feature, floor, producer, collector, scoring, replay, serving, identity or supervisor
code changed. The serving floor was not weakened. The `-09-74a` ceiling mission was not resumed.

## Production-host reproduction

Run from an isolated checkout of this branch at the production repository root. These paths are for
the production host, not the workstation scratch tree. Use its existing Python 3.11 environment;
install nothing.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'origin/codex/workstation-rebuild-the-runtime-from-the-identity-2026-09-76a'
$python311 = Join-Path $repo 'venv\Scripts\python.exe'
$scientificSite = Join-Path $repo 'venv\Lib\site-packages'
$priorRoot = Join-Path $repo 'scratch\runs\replay-trust-09-75a-production-verification'
$runRoot = Join-Path $repo 'scratch\runs\identity-binding-09-76a-production-verification'

Set-Location $repo
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
$env:GIT_LFS_SKIP_SMUDGE = '1'
git worktree add --detach (Join-Path $repo 'scratch\w\verify-identity-binding-09-76a') $branch
Set-Location (Join-Path $repo 'scratch\w\verify-identity-binding-09-76a')

& $python311 tools\research\measure_replay_trust_09_75a.py extract `
  --repo-root . --snapshots-root (Join-Path $repo 'data\snapshots') --run-root $priorRoot

& $python311 tools\research\measure_identity_binding_09_76a.py `
  --seed tools\research\measure_identity_binding_09_76a_seed.json catalog `
  --repo-root . --snapshots-root (Join-Path $repo 'data\snapshots') `
  --records (Join-Path $priorRoot 'replay-records.jsonl') `
  --census (Join-Path $priorRoot 'census-records.jsonl') `
  --output (Join-Path $runRoot 'identity-catalog.json')

& $python311 tools\research\measure_identity_binding_09_76a.py `
  --seed tools\research\measure_identity_binding_09_76a_seed.json resolve `
  --repo-root . --catalog (Join-Path $runRoot 'identity-catalog.json') `
  --output (Join-Path $runRoot 'identity-resolution.json')

& $python311 tools\research\measure_identity_binding_09_76a.py `
  --seed tools\research\measure_identity_binding_09_76a_seed.json assemble `
  --repo-root . --catalog (Join-Path $runRoot 'identity-catalog.json') `
  --resolution (Join-Path $runRoot 'identity-resolution.json') --run-root $runRoot

& $python311 tools\research\measure_identity_binding_09_76a.py `
  --seed tools\research\measure_identity_binding_09_76a_seed.json run-all `
  --records (Join-Path $priorRoot 'replay-records.jsonl') `
  --catalog (Join-Path $runRoot 'identity-catalog.json') `
  --resolution (Join-Path $runRoot 'identity-resolution.json') `
  --python311 $python311 --scientific-site $scientificSite `
  --receipts-root (Join-Path $runRoot 'receipts') `
  --run-manifest (Join-Path $runRoot 'run-manifest.json')

& $python311 tools\research\measure_identity_binding_09_76a.py `
  --seed tools\research\measure_identity_binding_09_76a_seed.json aggregate `
  --repo-root . --records (Join-Path $priorRoot 'replay-records.jsonl') `
  --census (Join-Path $priorRoot 'census-records.jsonl') `
  --catalog (Join-Path $runRoot 'identity-catalog.json') `
  --resolution (Join-Path $runRoot 'identity-resolution.json') `
  --run-manifest (Join-Path $runRoot 'run-manifest.json') `
  --receipts-root (Join-Path $runRoot 'receipts') `
  --csv-output (Join-Path $runRoot 'identity-binding.csv') `
  --manifest-output (Join-Path $runRoot 'identity-binding-manifest.json') `
  --checksums-output (Join-Path $runRoot 'identity-binding.sha256')
```

Expected verdict: `NO_SELECTED_IDENTITY_FULLY_RESOLVES_FROM_REACHABLE_GIT`; selected identities
0 fully resolved / 63 partial, same-row partial-tree matches 105 / 358, whole-B fully resolved rows
111 / 28,254. The CSV is host-independent and should match the committed CSV hash. The manifest is
a workstation receipt containing absolute disposable-tree paths and the exact ref universe seen by
that run; a production rerun must reproduce its headline counts and path-isolation assertions, not
its byte hash. The committed checksum validates the retained workstation evidence.

## Verification and roll verdict

```text
python -m py_compile tools/research/measure_identity_binding_09_76a.py
PASS

python tools/research/measure_identity_binding_09_76a.py --help
PASS

all 63 isolated CPython 3.11 identity processes
PASS (2,534 synthetic-tree module paths; zero escapes)

git diff --check
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 812 Markdown files)
```

The repository-owned roll verdict and per-file retained-closure result are pending the evidence
commit. This paragraph is replaced after `scripts\ops\roll_verdict.ps1 -Branch <branch>` inspects
the committed branch; no hand-derived verdict is used.

The evidence commit is `PENDING_EVIDENCE_COMMIT`, based on `origin/master` at
`32443b75ab987046fa6b1557a0ab7eb5d420ee98`. Branch:
`codex/workstation-rebuild-the-runtime-from-the-identity-2026-09-76a`.
