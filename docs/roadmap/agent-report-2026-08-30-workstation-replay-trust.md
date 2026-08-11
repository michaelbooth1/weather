# Agent report 2026-08-30 — replay trust on the decision stratum

## Verdict

**`REPLAY_DIVERGES_ON_THE_DECISION_STRATUM`.**

The full runtime-commit-bound decision population was replayed without stopping:
**114 of 358 matched** at the frozen `1e-12` L1 tolerance (**31.84%**) and **244
of 358 diverged**. The largest L1 error was `0.772771744045968`. Failures occur
in both decision windows, in every market, and under 8 of the 10 represented
runtime commits. This is not confined to the Toronto nightly source switch.

The 368-event stratum binds better than the earlier, mis-specified control:
**358/368 (97.28%)** carry a runtime commit, 8/368 (2.17%) carry only a model
identity, and 2/368 (0.54%) carry neither. The real replay N is therefore 358,
not 368. All 358 were run. The remaining 10 cannot be exactly replayed by the
mission's captured-runtime rule.

There is a more fundamental binding defect. For **all 358** commit-bound rows,
the captured model identity differs from the checked-out runtime-commit tree;
none of the 68 `(runtime commit, model identity)` pairs matches. Historical Git
HEAD alone therefore does not reconstruct what was actually served. The
frozen pre-registration is presently unexecutable for a reason unrelated to
the recovery candidate. The `-09-74a` ceiling mission must not resume.

## Decision-stratum replay shape

Every replayed row recorded active kind `hgb`, and every historical replay also
selected `hgb` (358/358). The divergences are therefore not an active-model-kind
switch.

### By runtime commit

| Runtime commit | Bound/replayed | Matched | Failed | Match rate | Max L1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `1dd68a4395bb` | 40 | 21 | 19 | 52.50% | 0.0277826 |
| `1e175b4428b7` | 22 | 0 | 22 | 0.00% | 0.0627986 |
| `2e3672d99680` | 83 | 19 | 64 | 22.89% | 0.772772 |
| `2f4a9ea11a47` | 5 | 2 | 3 | 40.00% | 0.0760179 |
| `3720e9871bcd` | 52 | 15 | 37 | 28.85% | 0.0132980 |
| `5b6f5af2d396` | 57 | 15 | 42 | 26.32% | 0.0402363 |
| `828a12b07fc7` | 4 | 0 | 4 | 0.00% | 0.0144553 |
| `90434a85c75f` | 10 | 10 | 0 | 100.00% | 0 |
| `e0b26bc494e7` | 84 | 31 | 53 | 36.90% | 0.0432017 |
| `f8cd408625a4` | 1 | 1 | 0 | 100.00% | 0 |
| no runtime commit | 10 | — | — | — | — |

### By model version

| Recorded model version | Rows | Replayed | Matched | Failed | Match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| `v0.3.1 empirical lookup baseline` | 5 | 0 | 0 | 0 | — |
| `v0.5.1 HGBC feature-based ML model` | 2 | 0 | 0 | 0 | — |
| `v0.5.7 HGBC feature-based ML model` | 1 | 0 | 0 | 0 | — |
| `v0.5.8 HGBC feature-based ML model` | 2 | 0 | 0 | 0 | — |
| `v0.5.10 HGBC feature-based ML model` | 358 | 358 | 114 | 244 | 31.84% |

### By market

| Market | Rows | Bound/replayed | Matched | Failed | Match rate | Max L1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| atlanta | 51 | 50 | 3 | 47 | 6.00% | 0.0616115 |
| austin | 40 | 40 | 18 | 22 | 45.00% | 0.0868985 |
| chicago | 25 | 24 | 18 | 6 | 75.00% | 0.00387928 |
| dallas | 37 | 36 | 4 | 32 | 11.11% | 0.0331514 |
| denver | 21 | 20 | 16 | 4 | 80.00% | 0.0343527 |
| houston | 22 | 22 | 7 | 15 | 31.82% | 0.0760179 |
| los-angeles | 27 | 27 | 0 | 27 | 0.00% | 0.0442796 |
| miami | 25 | 25 | 9 | 16 | 36.00% | 0.545676 |
| nyc | 31 | 29 | 11 | 18 | 37.93% | 0.0461464 |
| san-francisco | 8 | 6 | 0 | 6 | 0.00% | 0.772772 |
| seattle | 57 | 55 | 26 | 29 | 47.27% | 0.0317813 |
| toronto | 24 | 24 | 2 | 22 | 8.33% | 0.0507402 |

### By window

| Window | Rows | Bound/replayed | Matched | Failed | Match rate | Max L1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| peak heating | 163 | 158 | 59 | 99 | 37.34% | 0.0432017 |
| settlement | 205 | 200 | 55 | 145 | 27.50% | 0.772772 |

These are exact finite-population counts, not sample estimates. No uncertainty
interval or power calculation is applicable to the deterministic reproduction
question; all 358 rows admitted by the frozen runtime-binding rule were run.

## Toronto source-switch hypothesis

The hypothesis is **abandoned**. The three runtime-commit-bound M4 rows all
fail, but their recorded and replayed feature vectors select the same source
and have zero differing feature fields. The fourth row is model-identity-only
and is not exactly reconstructible from any committed tree, so the required
condition that all four replay and fail is not met.

| Toronto M4 snapshot | Binding | Replayed | Match | L1 | Feature differences |
| --- | --- | ---: | ---: | ---: | ---: |
| `20260615T000821-0400` | model identity only | no | — | — | — |
| `20260617T000830-0400` | `1dd68a4395bb` | yes | no | 0.00702234 | 0 |
| `20260619T000838-0400` | `e0b26bc494e7` | yes | no | 0.00480622 | 0 |
| `20260620T000839-0400` | `e183f1adc1cc` | yes | no | 0.00500094 | 0 |

For the unbound June 15 row, an identity reconstruction audit found that its
11 captured code-file hashes do not form a committed tree: matching blobs are
spread across multiple commits and three captured hashes do not occur in any
reachable commit. Treating a nearby commit as that runtime would manufacture
evidence, so no approximate replay is counted.

The confound is broken on the two M4 runtimes that also contain decision rows:

- Non-M4 Toronto rows on `1dd68a4395bb` match 0/2; non-Toronto rows match
  21/38 (17 failures).
- Non-M4 Toronto rows on `e0b26bc494e7` match 0/9; non-Toronto rows match
  31/75 (44 failures).
- `e183f1adc1cc` has no decision-stratum comparator rows.

Thus failures are neither M4-only nor Toronto-only.

### End-to-end trace: Toronto 2026-06-17 00:08

The captured and historical replay both use the `toronto_model` path and active
kind `hgb`. Both bind `high_so_far` and `current_temp` to the sole WU-history
row: history maximum `15 C`, latest history temperature `15 C`. A captured WU
current observation is also present (`17 C`, `max_since_7am=24 C`) but neither
feature extraction binds it. The recorded and replayed feature vectors have
**zero differences**, so there is no first feature-vector divergence.

The first observed divergence is downstream of feature extraction, at output
band 15: recorded probability `0.001399465150825757`, replayed probability
`0.0014003573306669394`, delta `+8.921798411824777e-7`. Total L1 is
`0.0070223354971857355`; maximum per-band error is `0.002394091826467548`.
For this row the captured model identity differs from the `1dd68a4395bb` tree
in 15 of 18 recorded code/artifact files. That environment-binding mismatch,
not observation-source selection or a feature-vector difference, is the first
traceable break.

## Binding census

### All replay-supported B feature snapshots

| Binding class | Count | Share |
| --- | ---: | ---: |
| runtime-commit bound | 16,143 | 57.14% |
| model identity only | 7,651 | 27.08% |
| neither | 4,460 | 15.79% |
| **total** | **28,254** | **100.00%** |

The whole-B runtime ceiling is therefore **16,143/28,254 (57.14%)**, lower
than the earlier control's 60.74%. There are 29 distinct captured runtime
commits and 9 model versions.

| Runtime commit | B snapshots | Runtime commit | B snapshots |
| --- | ---: | --- | ---: |
| `06941ce27e75` | 2 | `186b2574b993` | 12 |
| `1d74ed8728b5` | 52 | `1dd68a4395bb` | 2,477 |
| `1e175b4428b7` | 1,893 | `249b19050759` | 201 |
| `28d1c1464cc4` | 31 | `2e3672d99680` | 1,163 |
| `2f4a9ea11a47` | 1,105 | `3720e9871bcd` | 380 |
| `37668f276b8c` | 16 | `3fa9bcc6de38` | 49 |
| `4a5efaa26b4c` | 161 | `5b6f5af2d396` | 2,621 |
| `5ca4c54c0f35` | 778 | `828a12b07fc7` | 130 |
| `847d71d461f2` | 12 | `90434a85c75f` | 329 |
| `b10af31ec694` | 183 | `b1e4520075d3` | 551 |
| `ca359c02853e` | 15 | `cd68de99799c` | 9 |
| `d3709f0135a5` | 64 | `e0b26bc494e7` | 2,041 |
| `e183f1adc1cc` | 1,488 | `f7265bd3764b` | 45 |
| `f7e7ade88282` | 63 | `f8cd408625a4` | 259 |
| `fe6881fea46b` | 13 |  |  |

| Model version | B snapshots |
| --- | ---: |
| `v0.3.1 empirical lookup baseline` | 2,237 |
| `v0.4.9 HGBC feature-based ML model` | 114 |
| `v0.5.0 HGBC feature-based ML model` | 3,556 |
| `v0.5.1 HGBC feature-based ML model` | 258 |
| `v0.5.5 HGBC feature-based ML model` | 30 |
| `v0.5.6 HGBC feature-based ML model` | 48 |
| `v0.5.7 HGBC feature-based ML model` | 4,558 |
| `v0.5.8 HGBC feature-based ML model` | 1,310 |
| `v0.5.10 HGBC feature-based ML model` | 16,143 |

### The 368-event decision stratum

| Binding class | Count | Share |
| --- | ---: | ---: |
| runtime-commit bound | 358 | 97.28% |
| model identity only | 8 | 2.17% |
| neither | 2 | 0.54% |
| **total** | **368** | **100.00%** |

The ten decision-stratum runtime-commit counts are in the replay table above.
The five model-version counts are: `v0.3.1` 5, `v0.5.1` 2, `v0.5.7` 1,
`v0.5.8` 2, and `v0.5.10` 358.

## Artifacts and receipts

- `replay-trust-2026-09-75a.csv`: one row for each of the 368 decision events
  plus four M4 diagnostics, with binding, L1, maximum band error, active kinds,
  feature trace, and replay status.
- `replay-trust-2026-09-75a-manifest.json`: the census, all grouped match
  rates, runtime module paths and identity audits, source-switch confound,
  trace, input receipts, and campaign receipts.
- `replay-trust-2026-09-75a.sha256`: hashes for the CSV and manifest.
- `measure_replay_trust_09_75a_seed.json`: frozen input hashes, populations,
  tolerance, and prohibited analyses.
- `measure_replay_trust_09_75a.py`: outcome-blind extractor, exact historical
  runtime runner, identity audit, and aggregator.

The extractor read 408 local feature/replay files across 204 B market-days
(`8,922,883,529` bytes; receipt hash
`035c8dd15e15ef01d8826a8df88f9504fde9e177d685bbb7c4ee6ae23d64878c`).
It projected only the roster's non-outcome selection keys and never
materialized settlement or realized-band fields.

## Outcome and alpha receipts

- `realized_band_read: false`
- `settlement_consulted: false`
- `candidate_probabilities_computed: false`
- `displacement_computed: false`
- `ceiling_computed: false`
- `outcome_scored: false`
- `market_compared: false`
- `C_endpoint: false`
- `alpha_allocated_by_mission: 0`
- alpha remains 7/20 spent and 13 available
- decision 10 remains `CLOSED_UNUSED_NOT_REASSIGNED`

No provider or exchange call was made. Nothing under production `data/` was
written. No model, calibration, feature, floor, producer, collector, replay,
scoring, serving, release, schedule, supervisor, or trading path changed. The
serving floor was not weakened.

## Verification

The outcome-blind extraction and aggregation ran under the bundled Codex
Python 3.12 interpreter. Historical inference required the repository's
existing Python 3.11 environment because the preserved NumPy/scikit-learn
binaries are CPython 3.11 builds and the bundled 3.12 runtime has no compatible
scientific packages. Nothing was installed or downloaded.

```text
python -m py_compile tools/research/measure_replay_trust_09_75a.py
PASS

python tools/research/measure_replay_trust_09_75a.py --help
PASS

git diff --check
PASS
```

Repository audit and final Git/roll checks are recorded after the committed
branch is inspected.

## Production-host reproduction

Use an isolated checkout of this branch at the production repository root
`C:\Users\micha\Desktop\github\weather`. Write derived evidence only under
ignored `scratch/`:

```powershell
$runRoot = 'scratch\runs\replay-trust-09-75a'
$python312 = '<bundled-codex-python-3.12>'
$python311 = '.\venv\Scripts\python.exe'
$scientificSite = '.\venv\Lib\site-packages'

& $python312 tools\research\measure_replay_trust_09_75a.py extract `
  --repo-root . `
  --snapshots-root data\snapshots `
  --run-root $runRoot
```

Create disposable detached worktrees for these commits and paths, then
materialize their locally cached LFS model objects without a network fetch:

| Commit | Runtime path |
| --- | --- |
| `1dd68a4395bb` | `scratch\w\replay-trust-09-75a-1dd68a4395bb` |
| `1e175b4428b7` | `scratch\w\replay-trust-09-75a-1e175b4428b7` |
| `2e3672d99680` | `scratch\w\replay-trust-09-75a-2e3672d99680` |
| `2f4a9ea11a47` | `scratch\w\replay-trust-09-75a-2f4a9ea11a47` |
| `3720e9871bcd` | `scratch\w\replay-trust-09-75a-3720e9871bcd` |
| `5b6f5af2d396` | `scratch\w\replay-trust-09-75a-5b6f5af2d396` |
| `828a12b07fc7` | `scratch\w\replay-trust-09-75a-828a12b07fc7` |
| `90434a85c75f` | `scratch\w\replay-trust-09-75a-90434a85c75f` |
| `e0b26bc494e7` | `scratch\w\replay-trust-09-75a-e0b26bc494e7` |
| `f8cd408625a4` | `scratch\w\replay-trust-09-75a-f8cd408625a4` |
| `e183f1adc1cc` | `scratch\w\replay-trust-09-75a-e183f1adc1cc` |

For each row, run:

```powershell
& $python311 tools\research\measure_replay_trust_09_75a.py replay `
  --records "$runRoot\replay-records.jsonl" `
  --runtime-root <runtime-path> `
  --runtime-commit <commit> `
  --scientific-site $scientificSite `
  --output "$runRoot\receipt-<commit>.json"
```

Then aggregate the 11 receipts with the `aggregate` subcommand. Expected final
verdict is `REPLAY_DIVERGES_ON_THE_DECISION_STRATUM`, with 358 bound rows, 114
matches, 244 failures, and maximum L1 `0.772771744045968`. Every receipt prints
the resolved model, calibration, feature, market-registry, artifact, and path
module locations and rejects any module outside its intended historical tree.

## Roll verdict

Pending the repository-owned verdict on the committed branch.
