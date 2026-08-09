# Workstation report 2026-08-17 — official corpus manifests

**VERDICT: NO-GO — CURRENT MASTER CANNOT PRODUCE EITHER OFFICIAL INPUT. THE
BASE-RETRAIN MANIFEST HAS NO FIRST-PARTY WRITER AT ALL, AND THE PIT LANE HAS
ONLY A NO-NETWORK PLANNER/MATERIALIZER WITH 0/60 STAGED REQUEST UNITS. ITS
FROZEN 21-FIELD CONTRACT ALSO CONFLICTS WITH THE ESTABLISHED FREE-TIER RESULT
THAT ONLY `temperature_2m` IS PIT-AVAILABLE. THIS IS THE SIXTH RETRAIN BLOCKER.
NO MANIFEST WAS HAND-AUTHORED, NO PREFLIGHT OR FIT RAN, AND NO PROVIDER WAS
CALLED.**

## Branch, basis, and safety

- Branch:
  `codex/workstation-produce-the-corpus-manifests-2026-09-54a`
- Base: `origin/master` at
  `22a6861b6f0b883b75c9fd447ef9ba916243416a`.
- `docs/operations/reserved-confirmation-window.md` was checked at run time.
  Nothing is reserved; no candidate was fitted or frozen.
- The canonical `artifacts/releases` store and
  `artifacts/releases/current_release.json` were absent before and after the
  mission.
- The only generated evidence is below ignored
  `scratch/runs/weather-corpus-manifests-09-54a`. Nothing under `data/`, a
  release store, pointer, scheduler, loop, settlement path, or trading state
  was written.
- The repository venv points at a removed Python 3.11 interpreter. The retained
  compatible Python 3.12 environment at `scratch/r30a/.venv` was used without
  installing or changing a dependency.

## P0 — official producer inventory

| Required input | Expected schema | Official producer on current master | Result |
| --- | --- | --- | --- |
| Base feature corpus | `all_market_base_retrain_corpus_manifest_v0.1` | **None** | **BLOCK** |
| PIT forecast corpus | `pit_forecast_corpus_manifest_v1` | `python -m weather.sources.forecast_training_corpus plan`, then a separately reviewed collector calling `stage_response`, then `python -m weather.sources.forecast_training_corpus materialize` | **BLOCK: collector/staging absent and frozen field matrix is not satisfiable under established endpoint evidence** |

### Base manifest: a consumer contract with no writer

`weather.operations.base_retrain` registers and consumes
`all_market_base_retrain_corpus_manifest_v0.1`. The only other construction in
the tree is `_manifest()` in `tests/operations/test_base_retrain.py`, which is
explicitly synthetic test data.

The named candidates do not produce it:

- `weather.calibration.pooled_feature_assembly.build_market_records` returns
  in-memory rows.
- `weather.calibration.pooled_feature_cli` consumes a PIT manifest or an A/B/C
  forecast-history root and fits pooled artifacts; it does not publish the
  base-retrain manifest or its per-market record files.
- `weather.calibration.base_model_candidate` reads already hash-bound record
  files only after preflight authorizes fitting.
- `weather.operations.nightly_retrain` passes the two manifest paths through to
  `base_retrain`; neither `point_in_time_preselection` nor
  `point_in_time_production_qualification` writes either retrain input.

The absence is structural, not a missing command-line flag. A real writer must
freeze the 12 per-market JSONL record files and populate the exact source-row,
feature-order, parity, sidecar, and fold/final support evidence that
`evaluate_preflight()` checks. Hand-authoring that topology would be precisely
the unauditable bypass the handoff forbids.

### PIT manifest: the planner exists, collection does not

`weather.sources.forecast_training_corpus` is the official PIT owner. Its
planner and materializer are intentionally network-free. The canonical
contract says a separately reviewed collector may call `stage_response`, but
there is no such caller in `src/`; all `stage_response` call sites outside its
definition are deterministic tests.

The current-master planner was run for the `-09-53a` rehearsal population:
target `2026-06-10`, training dates June 3–17 in 2021–2025, 12 markets, and
cutoffs 07:00–20:00.

| Direct measurement | Result |
| --- | ---: |
| Plan schema | `pit_forecast_corpus_plan_v1` |
| Plan self-hash | `987a2ccd4e449b4e5317a61eb02028260c9675935dad865f4a5c2bc2b79f19f2` |
| Plan file SHA-256 | `f426a4b021bb1c073d3f781d7a1d66d6c742737ef1999b78f9a564caae948b3c` |
| Markets / years / request units | 12 / 5 / **60** |
| Expected market/date/cutoff cells | **12,600** |
| Frozen source fields | **21** |
| Complete staged units | **0 / 60** |

`resume-status` classified every request as `missing_body_or_receipt`.
Materialization was not attempted because it would only append a failure
receipt to the empty staging root; it cannot publish until all 60 units verify.

This is not sequenced behind the extended settled forecast archive. The PIT
producer does not read `data/forecast_history`; it requires immutable raw
Previous Runs responses plus issue and availability evidence. The June base
feature matrix was already established as 12,600/12,600, so the extended
archive is also not the blocker for this rehearsal. A real `2026-07-31` base
manifest remains sequenced behind production's target-derived archive
backfill.

There is a second PIT blocker behind empty staging. The plan requires all 21
fields to be complete for every row. `ESTABLISHED_FINDINGS.md` §4f records the
frozen breadth result: 1 of 21 fields is non-null on the free Previous Runs
surface, 17 are all-null, and 3 return HTTP 400; the 441-cell breadth probe
confirmed only `temperature_2m`. No endpoint was re-probed here. Under the
standing evidence, collecting the plan would still fail closed even if a
collector existed.

## Wrong target versus wrong schema

`-09-50a`'s retained research input was
`honest_rich_hybrid_feature_corpus_manifest_v0.2` for target `2026-07-31`.
Its ignored artifact is no longer present in this checkout, so this mission
does not claim a fresh file hash; the exact schema and target are inherited
from that accepted report. Current source independently supplies both expected
schema IDs below.

| Use | Expected | Retained research input | Disposition |
| --- | --- | --- | --- |
| Base rehearsal | schema `all_market_base_retrain_corpus_manifest_v0.1`, target `2026-06-10` | schema `honest_rich_hybrid_feature_corpus_manifest_v0.2`, target `2026-07-31` | Target could be regenerated only after a writer exists; schema/topology is incompatible. |
| PIT rehearsal | schema `pit_forecast_corpus_manifest_v1`, target year 2026, season June 3–17, immutable plan/files/issue evidence | schema `honest_rich_hybrid_feature_corpus_manifest_v0.2`, target `2026-07-31` | It is an A/B/C research receipt, not a PIT corpus; changing its target cannot make it pass. |

So “wrong target” and “wrong schema” are independent. The target mismatch is a
parameter/population mismatch. The schema mismatch names two different
artifacts with different evidence contracts and cannot be repaired by editing
a field or renaming the schema.

## Why P1 stopped

The handoff says that a nonexistent input is the sixth blocker and that naming
it is more valuable than fixing it. P0 found two producer gaps before
`base_retrain` could consume anything:

1. no official base-manifest producer exists;
2. the PIT producer has neither staged source units nor a current satisfiable
   source-field contract.

Therefore no scratch manifest pair exists, preflight cannot honestly clear,
and fit wall-clock/RSS remain unmeasured. No placeholder or synthetic manifest
was passed to `base_retrain` in this mission.

There is also an integration dependency, not a new functional blocker:
`-09-53a` implementation commit `c74f0db4` is not an ancestor of this
mission's required `origin/master` base, and its reported scratch parent is no
longer present. The `-09-49a` training-policy branch is likewise not in this
master, so any eventual fit from this base would still use the pre-`-09-49a`
F-market feature state. Neither branch was silently cherry-picked or copied.

## What must happen next

1. Add a reviewed first-party base-manifest writer around the code-owned
   training population and feature assembly. It must publish immutable
   per-market record files and every preflight evidence field; tests must prove
   that candidate inputs cannot shrink the gate.
2. Decide and implement the official PIT source contract that current free-tier
   evidence can actually satisfy. That requires a reviewed collector and a
   reviewed field/disposition change; it is not permission to weaken the
   existing verifier or relabel the A/B/C receipt.
3. Integrate `-09-53a` before attempting the complete empty-store rehearsal.
   Then produce both manifests to a new scratch root and rerun `base_retrain`.

## Production-host reproduction

Run from the production checkout only for read-only/source inspection and a
new disposable `C:\tmp` plan. These commands do not fetch or materialize.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
$python = '.\venv\Scripts\python.exe'
$run = 'C:\tmp\weather-corpus-manifests-09-54a-verify'
if (Test-Path $run) { throw "Choose a new empty scratch root: $run" }

Select-String -Path `
  src\weather\operations\base_retrain.py, `
  src\weather\schema_registry_data.py, `
  tests\operations\test_base_retrain.py `
  -Pattern 'all_market_base_retrain_corpus_manifest'

Get-ChildItem src\weather -Recurse -Filter *.py |
  Select-String -Pattern 'stage_response\('

& $python -B -m weather.sources.forecast_training_corpus plan `
  --out "$run\pit-plan-june10.json" `
  --years 2021,2022,2023,2024,2025 `
  --target-year 2026 `
  --season-start 06-03 `
  --season-end 06-17 `
  --cutoff-hours 7,8,9,10,11,12,13,14,15,16,17,18,19,20 `
  --source-model gfs_seamless `
  --lead-days 1
if ($LASTEXITCODE -ne 0) { throw 'PIT planning failed.' }

& $python -B -m weather.sources.forecast_training_corpus resume-status `
  --plan "$run\pit-plan-june10.json" `
  --staging-root "$run\pit-staging"
```

Expected source trace: the base schema appears in the registry, consumer, and
synthetic test only; `stage_response` has no production caller. Expected plan:
12 markets, 60 requests, 12,600 market/date/cutoff cells, 21 source fields,
network authorization false. A new empty staging root reports 0/60 complete.

Focused deterministic verification on the workstation used:

```powershell
.\scratch\r30a\.venv\Scripts\python.exe -B -m pytest `
  -p no:cacheprovider `
  --basetemp scratch\pytest-09-54a `
  -q `
  tests\sources\test_forecast_training_corpus.py `
  tests\operations\test_base_retrain.py
```

Observed: **29 passed in 3.62 s**. The first attempt without `--basetemp`
produced 4 passes and 25 setup errors because
`C:\Users\Michael\AppData\Local\Temp\pytest-of-Michael` is ACL-denied; no
test body failed.

## Mechanical roll verdict

The committed branch was checked with the repository-owned command:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-produce-the-corpus-manifests-2026-09-54a
```

Result: recorded after the evidence/report commit.

| Changed file | Live closures | Verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-17-workstation-corpus-manifests.md` | none | Roll-free |

## What was not done

- No provider or exchange endpoint was called; no credential was read.
- No base or PIT manifest was hand-authored, converted, relabelled, or passed
  as qualified evidence.
- No model was fitted, scored, selected, frozen, promoted, activated, served,
  or traded. No confidence interval or power calculation applies because no
  candidate or estimand exists.
- No production `data/`, mirror, canonical artifact, release, pointer, tape,
  ledger, scheduler, supervisor, loop, settlement, or trading state changed.
- No verifier, gate, feature contract, source field, station-day exclusion,
  minimum-row floor, serving floor, promotion rule, or probability contract was
  weakened.
- No PR, merge, master push, branch deletion, restart, registration, or live
  action occurred.

## Commit

- Evidence/report commit: recorded after commit creation.
- Final metadata commit: the pushed branch head is authoritative.
