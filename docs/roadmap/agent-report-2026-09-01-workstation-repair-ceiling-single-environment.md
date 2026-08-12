# Agent report 2026-09-01 — under today's environment, NOT what we would have served

**Verdict: the declared outcome-free ceiling clears the smallest effect detectable at
`alpha = 0.0025` with 12 market clusters.** Its crossed `mean + q*SE` upper bound is
`0.6423289473`, versus the binding detectable effect `0.2164183792`. The frozen `-09-73a`
pre-registration therefore asks the wrong historical question. I drafted the required
single-environment rewrite, but did not freeze or execute it and allocated no alpha. The operator
must decide whether to re-freeze it and spend an allocation.

This report answers only: **what can `point_in_time_wu_observable_tail_recovery_v2` buy under the
current `origin/master` environment, holding both arms in that environment on the same captured raw
inputs?** It does not answer what production would have served historically. That reconstruction
route remains closed: exact output reconstruction was 0/368 decision rows and 111/28,254 whole-B
rows in `-09-75a`/`-09-76a`.

## Outcome-free ceiling

I ran the 368-row B decision stratum: 11 target-date clusters, 12 market clusters, and 66
market-days. The incumbent `q` is the current pipeline on each captured payload as-is. Candidate
`p` is the same imported pipeline after replacing only `sources.wu_history.data.rows` with the
strict-prior observable-tail repair: current rows win at the same minute, and a previously
published row is recovered only if the current payload contains no row at or after that local
minute. Every other captured input is unchanged.

The harness computed only the declared statistic

```text
ceiling_i = sum_k(p_k^2) - sum_k(q_k^2) + 2*max_k(q_k - p_k)
```

with `p = candidate` and `q = incumbent`. In that orientation this is the maximum
candidate-minus-incumbent Brier difference over possible realized bands. It is the exact
outcome-free screen instructed by the handoff, not a realized paired-improvement estimate.

| Quantity | Result |
| --- | ---: |
| Population / paired-defined rows | 368 / 368 |
| Incumbent-defined rows | 368 |
| Candidate-defined rows | 368 |
| Undefined rows and reasons | 0 / none |
| Candidate-changed rows | 366 |
| Exact no-recovery clone controls | 2 |
| Same-model arm-order state-control failures | 0 |
| Strict-prior failures / future snapshots consumed | 0 / 0 |
| Mean ceiling | `0.4720049166` |
| Crossed bootstrap SE | `0.0547685189` |
| `mean - 3.1098893*SE` | `0.3016808858` |
| `mean + 3.1098893*SE` | `0.6423289473` |

Inference used 10,000 crossed `target_date x market_id` pigeonhole-bootstrap draws with seed
`20260977`. The interval is the repository convention `mean +/- q*SE` at `q = 3.1098893`; it is not
a percentile interval. Pointwise domination therefore does not transfer to either interval bound.

The candidate moved 366 rows, with mean L1 probability displacement `0.5879151574`, maximum L1
displacement `1.6012110577`, and 196 argmax changes. The two no-recovery controls were exact clones.
The decision pass scanned 66 captured replay files, 4,924,364,657 bytes and 13,664 replay rows. Whole
B was not computed: the complete primary population already answers the commissioned question, and
another multi-gigabyte pass was not cheap.

## Detectable-effect arithmetic

The canonical 12-market asymptotic floor is `0.032` under the reference two-sided 5% convention.
Pricing it at the campaign's `alpha = 0.0025`, 80% power, and uniform `q = 3.1098893` gives

```text
q multiplier
  = (3.1098893 + 0.8416212336) / (1.9599639845 + 0.8416212336)
  = 1.4104552337

corrected 12-market floor
  = 0.032 * 1.4104552337
  = 0.0451345675

candidate-field MDE from the measured crossed SE
  = (3.1098893 + 0.8416212336) * 0.0547685189
  = 0.2164183792

binding smallest effect detectable
  = max(0.0451345675, 0.2164183792)
  = 0.2164183792
```

The comparison required by the handoff is therefore

```text
ceiling upper bound 0.6423289473 > binding MDE 0.2164183792
```

The margin is `0.4259105681`. Even the lower endpoint is above the MDE by `0.0852625066`, although
the decision rule uses the upper bound. The canonical hard floor is set by the 12 markets, not the
number of dates; adding dates cannot push detectability below that market-cluster floor.

## Recommendation and alpha stop

Use the retained draft
`docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json` as the
rewrite, review it, and re-freeze it only if the operator chooses to allocate a future look. **Do
not execute the look and do not allocate alpha from this mission.** The draft's status is
`DRAFT_NOT_FROZEN_ALPHA_UNALLOCATED_NOT_EXECUTABLE` and it asks the licensed question under the
content-addressed environment, not the impossible historical-serving question.

- alpha remains 7 of 20 spent and 13 available
- alpha allocated or spent by `-09-77a`: 0
- decision 10 remains `CLOSED_UNUSED_NOT_REASSIGNED`

## Fixed environment and forward-capture proof

The source base is current `origin/master` at mission start,
`ab6159d312a87a0095229e6034f15cfd55892847`. Both arms ran in one CPython 3.11.9 process with NumPy
2.4.6, SciPy 1.17.1, scikit-learn 1.8.0, pandas 3.0.3 and joblib 1.5.3. Nothing was installed. The
working-tree HEAD during the final measurement was evidence commit
`14cd92d2b0869464b923b82985a1ed3ff5e43382`; its changes were only the mission's documentation,
research harness and artifacts, so the runtime pipeline bytes remained the stated source base.

After import and both-arm execution, the harness enumerated `sys.modules`, resolved every loaded
`weather.*` `__file__`, and captured its exact bytes. A Python open-audit hook also captured every
repository-local artifact, config and non-snapshot supporting-data file actually opened. Captured
raw replay payloads remain separately hashed inputs rather than bundle members. The resulting
immutable ZIP contains 564 files: 49 loaded module files and 515 runtime-open support files,
482,853,649 bytes uncompressed. Independent extraction and hash verification passed with zero
escaped modules.

```text
bundle: docs/roadmap/repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip
bundle bytes: 67,425,083
bundle SHA-256: 5a53c2cfc3ace75b79f4b7469e0f7ffe071d1a51c431f0f6947be1aee2581b10
environment content ID: e72fc0e0923fb855be869eedb3ef58ccfdb3a5e0f8384342c6ee4a03ed4042ff
```

This is the requested working demonstration of the forward fix without changing
`model_identity.py`. The first pass emitted the immutable but narrower source/artifact/config bundle
`repair-ceiling-single-environment-runtime-bundle-53ec30351dd222b3.zip` (SHA-256
`53ec30351dd222b33bda0d7dae24c68cff4f316971f580239fa98c697f082653`). It is retained rather than
deleted, but superseded for extracted-runtime reproduction by the complete `5a53...` bundle above.
Adding the support files did not change the measurement CSV byte-for-byte.

Every loaded module file is printed below. Each absolute path resolves inside the workstation tree
`C:\Users\Michael\Documents\github\weather`; the bundle manifest records zero escapes.

```text
weather -> C:\Users\Michael\Documents\github\weather\src\weather\__init__.py
weather.artifacts -> C:\Users\Michael\Documents\github\weather\src\weather\artifacts.py
weather.forecast_payload_contracts -> C:\Users\Michael\Documents\github\weather\src\weather\forecast_payload_contracts.py
weather.io -> C:\Users\Michael\Documents\github\weather\src\weather\io.py
weather.market -> C:\Users\Michael\Documents\github\weather\src\weather\market\__init__.py
weather.market.market_config -> C:\Users\Michael\Documents\github\weather\src\weather\market\market_config.py
weather.market.market_registry -> C:\Users\Michael\Documents\github\weather\src\weather\market\market_registry.py
weather.model -> C:\Users\Michael\Documents\github\weather\src\weather\model\__init__.py
weather.model.calibration_runtime -> C:\Users\Michael\Documents\github\weather\src\weather\model\calibration_runtime.py
weather.model.continuous_density -> C:\Users\Michael\Documents\github\weather\src\weather\model\continuous_density.py
weather.model.feature_store -> C:\Users\Michael\Documents\github\weather\src\weather\model\feature_store.py
weather.model.model_base -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_base.py
weather.model.model_climatology -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_climatology.py
weather.model.model_constants -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_constants.py
weather.model.model_contracts -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_contracts.py
weather.model.model_distribution -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_distribution.py
weather.model.model_distribution_constants -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_distribution_constants.py
weather.model.model_distribution_signals -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_distribution_signals.py
weather.model.model_features -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_features.py
weather.model.model_presentation -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_presentation.py
weather.model.model_sources -> C:\Users\Michael\Documents\github\weather\src\weather\model\model_sources.py
weather.model.source_adapters -> C:\Users\Michael\Documents\github\weather\src\weather\model\source_adapters.py
weather.model.toronto_model -> C:\Users\Michael\Documents\github\weather\src\weather\model\toronto_model.py
weather.paths -> C:\Users\Michael\Documents\github\weather\src\weather\paths.py
weather.point_in_time_contract -> C:\Users\Michael\Documents\github\weather\src\weather\point_in_time_contract.py
weather.release_artifacts -> C:\Users\Michael\Documents\github\weather\src\weather\release_artifacts.py
weather.release_contract -> C:\Users\Michael\Documents\github\weather\src\weather\release_contract.py
weather.release_serving -> C:\Users\Michael\Documents\github\weather\src\weather\release_serving.py
weather.runtime_identity -> C:\Users\Michael\Documents\github\weather\src\weather\runtime_identity.py
weather.schema_registry -> C:\Users\Michael\Documents\github\weather\src\weather\schema_registry.py
weather.schema_registry_data -> C:\Users\Michael\Documents\github\weather\src\weather\schema_registry_data.py
weather.schema_registry_recent_data -> C:\Users\Michael\Documents\github\weather\src\weather\schema_registry_recent_data.py
weather.schema_registry_types -> C:\Users\Michael\Documents\github\weather\src\weather\schema_registry_types.py
weather.scoring -> C:\Users\Michael\Documents\github\weather\src\weather\scoring\__init__.py
weather.scoring.metrics -> C:\Users\Michael\Documents\github\weather\src\weather\scoring\metrics.py
weather.sources -> C:\Users\Michael\Documents\github\weather\src\weather\sources\__init__.py
weather.sources.daily_summary -> C:\Users\Michael\Documents\github\weather\src\weather\sources\daily_summary.py
weather.sources.eccc_gridded -> C:\Users\Michael\Documents\github\weather\src\weather\sources\eccc_gridded.py
weather.sources.forecast_history -> C:\Users\Michael\Documents\github\weather\src\weather\sources\forecast_history.py
weather.sources.forecast_payload_fanout -> C:\Users\Michael\Documents\github\weather\src\weather\sources\forecast_payload_fanout.py
weather.sources.grib_probe -> C:\Users\Michael\Documents\github\weather\src\weather\sources\grib_probe.py
weather.sources.historical_schema -> C:\Users\Michael\Documents\github\weather\src\weather\sources\historical_schema.py
weather.sources.marine_context -> C:\Users\Michael\Documents\github\weather\src\weather\sources\marine_context.py
weather.sources.mrms_precip -> C:\Users\Michael\Documents\github\weather\src\weather\sources\mrms_precip.py
weather.sources.nbm_probabilistic_tmax -> C:\Users\Michael\Documents\github\weather\src\weather\sources\nbm_probabilistic_tmax.py
weather.sources.reanalysis_history -> C:\Users\Michael\Documents\github\weather\src\weather\sources\reanalysis_history.py
weather.sources.reanalysis_synoptic -> C:\Users\Michael\Documents\github\weather\src\weather\sources\reanalysis_synoptic.py
weather.sources.wu_history -> C:\Users\Michael\Documents\github\weather\src\weather\sources\wu_history.py
weather.units -> C:\Users\Michael\Documents\github\weather\src\weather\units.py
```

## Artifacts and receipts

```text
3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8  docs/roadmap/repair-ceiling-single-environment-2026-09-77a.csv
f1242b399b82ec7571e3fb70b04d748ed0733b6f30b66953aed6d57ebacbd40e  docs/roadmap/repair-ceiling-single-environment-2026-09-77a-manifest.json
5a53c2cfc3ace75b79f4b7469e0f7ffe071d1a51c431f0f6947be1aee2581b10  docs/roadmap/repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip
88bdfee0269e1372c336518e3c7bf35c01399f8c92e5df88a05f012353c2a8ef  tools/research/measure_single_environment_repair_ceiling_09_77a.py
24fa6e01c9151e005586fde90c98cdb62d874777ed639bba7f3f6b72ba7ad416  tools/research/measure_single_environment_repair_ceiling_09_77a_seed.json
17d53456961d1f75f9bd07178e8c9baf3c7442ffe1485d0a709d4ceaea348d56  docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json
```

The CSV contains 368 arm pairs, probability-mass checks, displacement and the declared ceiling; it
contains no realized band or realized score. The manifest contains the bootstrap, detectability,
input, environment and safety receipts. Evidence through the complete bundle binding is committed
at `9ce847a92af240012f8edf9bfb5f51474464f971`.

## Safety receipts

- `realized_band_read: false`
- `delta_i_computed: false`
- `settlement_consulted: false`
- `outcome_scored: false`
- `market_compared: false`
- `C_endpoint: false`
- `whole_B_computed: false`
- `commit_binding_attempted: false`
- `identity_binding_attempted: false`
- `synthetic_historical_tree_created: false`

No provider or exchange call, production `data/` write, scheduled-task mutation, registration,
restart, promotion, activation, release, trade, merge, rebase, or branch deletion occurred. Other
branches and refs were read-only. No model, calibration, feature, floor, producer, collector,
scoring, serving, supervisor, or `model_identity.py` file changed. The serving floor was not
weakened.

## Production-host reproduction

Run from an isolated checkout of the pushed branch at the production repository root. The worktree
supplies the retained harness and separately hashed captured inputs; the extracted bundle supplies
the exact current-environment source, artifact, config and support bytes. Use the existing Python
3.11 environment and install nothing.

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
$branch = 'origin/codex/workstation-what-can-the-repair-buy-2026-09-77a'
$python311 = Join-Path $repo 'venv\Scripts\python.exe'
$verifyRoot = Join-Path $repo 'scratch\w\verify-repair-ceiling-09-77a'
$runRoot = Join-Path $repo 'scratch\runs\repair-ceiling-09-77a-production-verification'
$runtimeRoot = Join-Path $runRoot 'runtime'
$artifactRoot = Join-Path $runRoot 'artifacts'

Set-Location $repo
git fetch origin '+refs/heads/*:refs/remotes/origin/*'
git worktree add --detach $verifyRoot $branch
Set-Location $verifyRoot
git lfs pull --include='docs/roadmap/repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip'

& $python311 tools\research\measure_single_environment_repair_ceiling_09_77a.py `
  verify-bundle --bundle docs\roadmap\repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip

New-Item -ItemType Directory -Force -Path $runtimeRoot, $artifactRoot | Out-Null
Expand-Archive `
  -LiteralPath docs\roadmap\repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip `
  -DestinationPath $runtimeRoot

& $python311 tools\research\measure_single_environment_repair_ceiling_09_77a.py execute `
  --repo-root $verifyRoot `
  --runtime-root $runtimeRoot `
  --snapshots-root (Join-Path $repo 'data\snapshots') `
  --run-root (Join-Path $runRoot 'working') `
  --artifact-root $artifactRoot `
  --seed (Join-Path $verifyRoot 'tools\research\measure_single_environment_repair_ceiling_09_77a_seed.json')

(Get-FileHash -Algorithm SHA256 `
  -LiteralPath (Join-Path $artifactRoot 'repair-ceiling-single-environment-2026-09-77a.csv')).Hash.ToLower()
```

Expected CSV SHA-256:
`3d782223e5b882d2bbda233f6abaed42b1a30442126979835720aa7e610611a8`. Expected bundle
verification: 564 files, 482,853,649 uncompressed bytes, 49 module paths, zero escapes, environment
content ID `e72fc0e0923fb855be869eedb3ef58ccfdb3a5e0f8384342c6ee4a03ed4042ff`. Expected result:
368/368 paired-defined rows, mean `0.4720049166`, crossed SE `0.0547685189`, upper bound
`0.6423289473`, and verdict `CEILING_ABOVE_DETECTABLE_FLOOR_DRAFT_PREREGISTRATION`.

## Verification and roll verdict

```text
measurement harness self-test
PASS

independent immutable-bundle verification
PASS (564 files; 482,853,649 bytes; 49 module paths; zero escapes)

all six SHA-256 receipt entries
PASS

CSV row count / manifest and draft JSON parse
PASS (368 rows; draft non-executable; realized_band_read false)

git diff --check
PASS

python -m weather.operations.agent_docs_audit
PASS
```

The branch-current repository-owned `scripts\ops\roll_verdict.ps1` compared this branch with the
actual landing base `origin/master` and returned exit 0, **`ROLL-FREE`**. It found no importable
changed file. The report itself and every evidence artifact are non-importable; the research
harness is outside the serving package.

| Changed file | Roll verdict |
| --- | --- |
| `.gitattributes` | ROLL-FREE — repository metadata |
| `docs/roadmap/agent-report-2026-09-01-workstation-repair-ceiling-single-environment.md` | ROLL-FREE — documentation |
| `docs/roadmap/observation-recovery-single-environment-preregistration-draft-2026-09-77a.json` | ROLL-FREE — non-executable draft evidence |
| `docs/roadmap/repair-ceiling-single-environment-2026-09-77a.csv` | ROLL-FREE — evidence |
| `docs/roadmap/repair-ceiling-single-environment-2026-09-77a-manifest.json` | ROLL-FREE — evidence |
| `docs/roadmap/repair-ceiling-single-environment-2026-09-77a.sha256` | ROLL-FREE — receipt |
| `docs/roadmap/repair-ceiling-single-environment-runtime-bundle-53ec30351dd222b3.zip` | ROLL-FREE — immutable preliminary evidence bundle |
| `docs/roadmap/repair-ceiling-single-environment-runtime-bundle-5a53c2cfc3ace75b.zip` | ROLL-FREE — immutable reproduction bundle |
| `tools/research/measure_single_environment_repair_ceiling_09_77a.py` | ROLL-FREE — non-serving research harness |
| `tools/research/measure_single_environment_repair_ceiling_09_77a_seed.json` | ROLL-FREE — frozen research seed |

Pushing this branch cannot restart capture. No merge or production working-tree change is part of
this mission.
