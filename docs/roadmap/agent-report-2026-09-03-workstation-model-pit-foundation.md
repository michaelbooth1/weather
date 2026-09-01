# Agent report 2026-09-03 — model/PIT foundation workstation qualification

**Verdict: PASS P0/P1 / NO-GO
`P2_NO_REPOSITORY_OWNED_V2_COLLECTOR`.** The loaded-process identity repair, honest
twelve-field free-PIT contract, deterministic model bill of materials (BOM),
release integration, and current-tip workstation verification passed. The
branch is mergeable for production review, but it is not adopted, promoted, or
live. P2 is a precise negative: the repository has no collector that consumes
the immutable v2 plan and emits the required request-bound raw-response
evidence, so no corpus collection or transfer was attempted.

## Git and isolation

The production handoff ref and the foundation were verified before work began:

```text
handoff ref              origin/codex/model-pit-foundation-20260831
handoff ref tip          b43eae5985f22b2b19a71e8b998e200cea125757
foundation commit        42657a1f48c82b81c6f2257f4d2614092862ae94
foundation tree          033f9bc8644dee34a498ccc627f1436565b193c4
mission branch           codex/workstation-model-pit-foundation-2026-09-79a
implementation commit    6e105b291ac0e9d86791131b7cb0d6de292e76e4
implementation tree      752c845c31f30f2c26a4c831563fa4e92a05422f
```

The final report-only tip and tree are reported in the outer handback after
this file is committed; a commit cannot truthfully contain its own hash.

All work ran in the separate mission worktree at
`C:\Users\Michael\Documents\github\weather\scratch\w\model-pit-foundation-09-79a`.
The import preflight printed these exact paths and both remained inside it:

```text
C:\Users\Michael\Documents\github\weather\scratch\w\model-pit-foundation-09-79a\src\weather\model\model_identity.py
C:\Users\Michael\Documents\github\weather\scratch\w\model-pit-foundation-09-79a\src\weather\sources\forecast_training_corpus.py
```

The portable live checkout was not used or modified. At implementation-commit
closure it remained clean on `codex/live-gate-provenance-20260831`, at
`40717b288b77b69555f977099dff90966b5c93e4`, tracking the matching remote.

## P0 — foundation qualification

Loaded-process identity v0.3 now has a path-stable recursive code
representation and binds behavior-bearing nested constants, defaults,
closures, the actual loaded estimator/postprocessor state, and the Python,
NumPy, SciPy, and scikit-learn runtime identity. Import-time and on-disk values
remain diagnostics, not authority. Fingerprint errors remain visible and make
the identity incomplete. Mutable `_PROCESS_BUNDLES` cache state is explicitly
excluded from behavior constants because its pointer/manifest binding is
verified separately.

The free-PIT v2 contract keeps all 21 schema-known profile fields explicit. It
requests exactly the 12 fields proved available from Previous Runs and records
the other nine as reason-bearing unavailable dispositions. It rejects v1
evidence, stitched issue evidence, unbound responses, and incomplete field
partitions rather than silently substituting settled projections.

### Required adversarial checks

| Required property | Result | Evidence |
| --- | --- | --- |
| Identical loaded behavior hashes equally across absolute worktree paths | PASS | Cross-root identity and BOM fixtures produce equal identities. |
| Nested constants and function defaults move identity | PASS | Mutations change the loaded-code identity; mapping order does not. |
| Loaded estimator bytes and runtime dependency changes move identity | PASS | Artifact-state and dependency mutation tests fail the prior binding. |
| Post-load disk mutation cannot relabel the unchanged process | PASS | Loaded identity remains bound to deserialized state. |
| Fingerprint errors cannot masquerade as complete | PASS | Error details are retained and authoritative identity is withheld. |
| v1 plan, manifest, or preflight cannot pass as v2 | PASS | Each legacy substitution is rejected. |
| v2 requests exactly 12 proved fields and zero unavailable fields | PASS | Exact request-field assertion passes. |
| Included profile features depend only on the 12 proved fields | PASS | Dependency closure assertion passes. |
| Every profile column is partitioned exactly once | PASS | Included plus reason-bearing excluded sets are disjoint and complete. |
| Stitched issue evidence remains rejected | PASS | Projection substitution cannot satisfy raw issue-time evidence. |
| Synthetic one-market corpus materializes atomically and passes v2 preflight | PASS | Atomic materialization and exact preflight test pass. |

Every mission falsifier was exercised. Identity is neither checkout-path nor
capture-time-disk dependent; unsupported loaded components cannot return a
confident complete identity; the profile partition is exhaustive; v1 evidence
is rejected; no provider call is required to prove the offline contract; the
BOM does not use ambient global artifacts or add a `weather.model` to
`weather.calibration` import edge; and the fresh current-tip focused and full
verification runs are clean and contained.

## P1 — deterministic model BOM

`weather.model.model_bom` builds and verifies schema
`weather_model_bill_of_materials_v0.1`. The BOM is a graph, not a fabricated
total order. It has named semantic nodes, typed required/conditional edges,
and two exact orders only where runtime code owns an order:

1. `toronto_base_distribution` — 16 stages:
   `base_estimator_and_prior_blend`, `bucket_transition`,
   `live_signal_adjustment`, `observed_hard_floor`,
   `intraday_tail_adjustment`, `plausible_upper_cap`, `forecast_shape`,
   `ramp_warm_tail_dampening`, `afternoon_residual_centering`,
   `validated_current_max_floor`, `observation_support_floor`,
   `late_day_continuation`, `late_day_lockin`,
   `pre_calibration_normalization`, `exact_distribution_calibration`, and
   `current_max_boundary_guard`.
2. `pooled_band_live_variant` — five stages: `candidate_raw`,
   `candidate_postprocessed`, `candidate_preblend`,
   `candidate_current_blend`, and `candidate_final`.

The BOM binds stage owner/source/loaded-module identity, input/output semantic
contracts, native-unit and cutoff obligations, behavior constants, release
runtime/dependencies, candidate-relative artifact hashes, artifact-specific
training lineage, estimator feature order and structural feature use, and the
feature-extraction forecast ensemble separately from the distribution-stage
forecast context. Production candidate and immutable-release verification
reject missing, extra, ambiguous, absolute-path, legacy-production,
self-rehashed, global-fallback, or post-deserialization structural
substitutions.

One deterministic complete synthetic release fixture produced identical
candidate and release BOMs:

```text
status                         COMPLETE
artifacts                      33
graph nodes / typed edges      33 / 33
runtime lanes                  2
model nodes                    4
missing entries                0
authoritative/diagnostic SHA   152254a7b6ededd30576888cb5e8f8a32902355b3d8a3742b25139dcd52e2eca
payload SHA                    f1cc77a5e1103db4ee73cd2b82e198b96f8e77dc49ec5f99382d83fb66f523aa
Toronto lane contract SHA      7c8b09715b72ffb213a16d57c50efba38d99674190962380cdafd1500d8d0a99
pooled lane contract SHA       b1092cfe31e22aa878f1cb3aa0e6ecbe2770a5f16736f569c046f5a6eb591050
distribution context SHA       3dc53aa296a5853ffd5030e28785d2c4edd9c6e760e17adb4f1a789a95c85ffc
feature context SHA            d7ff31c69d1f8e66f8619e1535b6104523c153396e452ab870d7321bc2d53226
```

Those are deterministic test-fixture identities, not claims about an active
release. The research-unbound fixture proves the negative path: status
`INCOMPLETE`, authoritative identity `null`, 36 explicit artifact-lineage
gaps, diagnostic SHA
`c6f1e7ce6426bdee1da7c9883f31e08766f003ce50d8962df6bb2bb20cd6648a`,
and payload SHA
`29e8fa47b65213bcee05f7d3849626dffbaa568f88a901e8ea2edf30ba861d0f`.
It does not invent training lineage or promote a diagnostic hash to authority.

## P2 — exact corpus collector/export disposition

**NO-GO: the production host cannot yet execute the requested v2 collection
with repository-owned code.** The audit found:

- `weather.sources.forecast_training_corpus` deliberately has no HTTP client;
  its CLI surface is `plan`, `resume-status`, and `materialize`;
- `stage_response` has no non-test caller;
- the existing `forecast_history` network path does not consume immutable plan
  request hashes and does not emit the required request-bound raw bytes,
  byte count, SHA-256, retrieval/issue evidence, and receipts;
- staged long CSV projections cannot reconstruct the missing provider bytes or
  issue-time proof.

No provider call was made. No offline import boundary was invented around
insufficient projections. The smallest follow-up owner is a new
`weather.sources.forecast_training_corpus_collector` module plus focused source
tests, leaving the existing corpus/materializer module network-free. A later
export/transfer mission should begin only after a complete, hash-verified v2
materialization exists.

## Verification

All Python commands ran serially through
`scripts/ops/workstation_heavy.ps1` with the exact
`workstation_offline_v1` host profile and the existing 64-bit CPython 3.11
environment. Python was never invoked directly.

| Verification surface | Result |
| --- | --- |
| Exact required focused matrix, final rerun | `121 passed, 4 subtests passed in 19.94s` |
| Expanded touched-code matrix | `280 passed, 1 skipped, 6 subtests passed in 38.05s` |
| Combined BOM/release matrix | `121 passed, 1 skipped in 40.72s` |
| Repaired release/BOM integration surface | `238 passed, 2 skipped, 4 subtests passed in 60.80s` |
| Release-consumer fixtures | `46 passed, 1 skipped` |
| Experiment-executor file after MAX_PATH repair | `24 passed` |
| Nightly-retrain file after genuine fixture repair | `41 passed` |
| Fresh complete workstation suite | `4299 passed, 23 skipped, 1 warning, 866 subtests passed in 647.30s` |
| Worktree compileall | PASS |
| Roadmap generation with lint | `Roadmap backlog: OK` |
| Roadmap parity check | `Roadmap backlog: OK (generated report matches sources)` |
| Agent documentation audit after this report | PASS (18 agent files, 830 Markdown files) |
| Cumulative `git diff --check` | PASS |

The one full-suite warning is the existing non-failing NumPy extension ABI-size
`RuntimeWarning` in `tests/sources/test_reanalysis_synoptic.py` (`Expected 16`,
`got 96`). It did not alter the verdict. An earlier full run exposed 27 real
integration/path failures and is not counted as qualification; they were
repaired before the fresh clean run. The main repairs were path-independent
process-cache identity, genuine role-specific nightly release fixtures,
release-consumer source-root binding, schema registration, and moving
experiment-executor scratch runs to the shallow same-volume ignored
`artifacts/candidates/.executor_runs` root to avoid Windows `MAX_PATH` while
preserving containment and atomic commit gates.

The wrapper does not expose peak process-tree memory, so none is claimed. After
the last wrapped check, `data/logs/heavy_workload.lock` could be opened with
exclusive sharing (no active holder), and `C:\ProgramData\WeatherProject` was
empty: no ACTIVE/TEARDOWN_PENDING poison marker remained. The final qualifying
run was neither partial nor interrupted.

One non-blocking maintainability follow-up is recorded honestly:
`release_candidate_contract.py` now exceeds 2,000 lines. Its owner metadata,
documentation row, and module-size audit entry were updated; a later owner
split should reduce it without weakening the release boundary.

## Roll disposition

This workstation does not possess the production live-closure receipts needed
for the canonical roll verdict, so no roll sensitivity was guessed. Production
must run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\ops\roll_verdict.ps1 `
  -Branch origin/codex/workstation-model-pit-foundation-2026-09-79a
```

`src/weather/schema_registry_recent_data.py` is not an additive-only registry
change on this branch. Production must treat it as potentially behavioral until
the repository-owned verdict and source review prove the required adoption
path. Pushing this topic branch does not modify the production working tree and
does not itself roll capture.

## Cumulative change against the foundation

Implementation commit `6e105b29` changes 47 files with 5,863 insertions and
292 deletions. Including this report, the final cumulative diff is:

```text
48 files changed, 6,216 insertions(+), 292 deletions(-)
```

Complete final changed-file list (the report is the 48th file):

```text
.codex/hooks/pre_tool_use_host_load.py
docs/development.md
docs/operations/MODEL_SYSTEM.md
docs/operations/PIT_FORECAST_TRAINING_CORPUS.md
docs/operations/module-ownership-map.md
docs/roadmap/ROADMAP.md
docs/roadmap/active-backlog.md
docs/roadmap/agent-report-2026-09-03-workstation-model-pit-foundation.md
docs/roadmap/items/item-330-model-bom-loaded-identity-and-pit-challenger.md
scripts/ops/workload_admission.ps1
src/weather/calibration/forecast_training_contract.py
src/weather/calibration/pooled_feature_assembly.py
src/weather/collection/live_variant_predictions.py
src/weather/model/model_bom.py
src/weather/model/model_bom_contracts.py
src/weather/model/model_contracts.py
src/weather/model/model_distribution.py
src/weather/model/model_features.py
src/weather/model/model_identity.py
src/weather/model/toronto_model.py
src/weather/operations/base_retrain.py
src/weather/operations/experiment_executor.py
src/weather/operations/module_size_audit.py
src/weather/operations/release_candidate_build.py
src/weather/operations/release_candidate_contract.py
src/weather/release_artifacts.py
src/weather/release_contract.py
src/weather/release_serving.py
src/weather/schema_registry_recent_data.py
src/weather/sources/forecast_training_corpus.py
tests/calibration/test_forecast_training_contract.py
tests/collection/test_live_variant_predictions.py
tests/market/test_worker_release_binding.py
tests/model/test_estimate_distribution.py
tests/model/test_feature_model_calibration.py
tests/model/test_forecast_feature.py
tests/model/test_model_bom.py
tests/model/test_model_identity_binding.py
tests/operations/test_base_retrain.py
tests/operations/test_experiment_executor.py
tests/operations/test_module_size_audit.py
tests/operations/test_nightly_retrain.py
tests/operations/test_release_candidate_contract.py
tests/operations/test_release_lifecycle.py
tests/operations/test_replay_cache_retention.py
tests/reporting/test_captured_input_parity_evidence.py
tests/sources/test_forecast_training_corpus.py
tests/test_release_serving.py
```

No binary, Git LFS pointer, credential, private key, environment file, model
payload, generated corpus, or provider response is part of the diff.

## Reproduction

Production review can use only repository-relative paths from its existing
checkout:

```powershell
git fetch origin codex/workstation-model-pit-foundation-2026-09-79a
git rev-parse origin/codex/workstation-model-pit-foundation-2026-09-79a
git diff --check 42657a1f48c82b81c6f2257f4d2614092862ae94 `
  origin/codex/workstation-model-pit-foundation-2026-09-79a
git diff --stat 42657a1f48c82b81c6f2257f4d2614092862ae94 `
  origin/codex/workstation-model-pit-foundation-2026-09-79a
```

For an authorized rerun on the assigned 32 GB workstation, run from the
mission branch root with its existing venv and repository wrapper:

```powershell
$python311 = (Resolve-Path .\venv\Scripts\python.exe).Path

function Invoke-WorkstationPython([string]$Kind, [string[]]$Arguments) {
  $json = ConvertTo-Json -Compress -InputObject @($Arguments)
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
  & .\scripts\ops\workstation_heavy.ps1 `
    -Kind $Kind `
    -PythonPath $python311 `
    -ArgumentsBase64 $b64 `
    -RepoRoot (Get-Location).Path
  if ($LASTEXITCODE -ne 0) { throw "$Kind failed: $LASTEXITCODE" }
}

Invoke-WorkstationPython pytest @(
  "-m", "pytest", "-q",
  "tests/model/test_model_identity_binding.py",
  "tests/model/test_feature_model_calibration.py",
  "tests/sources/test_forecast_training_corpus.py",
  "tests/calibration/test_forecast_training_contract.py",
  "tests/operations/test_base_retrain.py",
  "tests/operations/test_schema_registry.py",
  "tests/operations/test_import_architecture.py"
)
Invoke-WorkstationPython compileall @("-m", "compileall", "-q", "app", "src", "tests")
Invoke-WorkstationPython weather_heavy @(
  "-m", "weather.reporting.roadmap.roadmap_backlog", "--fail-on-lint", "--check"
)
Invoke-WorkstationPython weather_heavy @("-m", "weather.operations.agent_docs_audit")
Invoke-WorkstationPython pytest @("-m", "pytest", "-q")
```

Do not run the workstation wrapper on the capture host. Production should obey
`HOST_LOAD_POLICY.md`, review the pushed tree, run the roll command above, and
choose its own canonical verification/adoption route.

## What was not done

No credential or `.env` file was read or moved. No exchange, SDK, provider, or
other network endpoint was contacted. No live order, cancel, account mutation,
Scheduler mutation, production write, frozen-mirror write, reserved-date read,
model fit, candidate scoring, candidate freeze, release creation, release
promotion, active-pointer write, alpha allocation, live checkout change,
capture restart, merge, rebase, history rewrite, or branch deletion occurred.
No production dataset, `data/` tree, virtual environment, SDK overlay, attempt
state, or historical LFS object was copied into the branch.

Statistical estimates, uncertainty intervals, power/MDE, and model-skill claims
are not applicable: this mission deliberately fitted and scored no model.
