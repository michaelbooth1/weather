# Workstation report 2026-08-18 — corpus producer and endpoint trace

**VERDICT: NO-GO — THE 21-FIELD BLOCKER IS A REAL FREE-TIER POINT-IN-TIME
CONTRACT WALL, NOT A SIMPLE ENDPOINT-ROUTING DEFECT. THE PLAN SENDS ALL 21
FIELDS TO THE PREVIOUS RUNS ENDPOINT, BUT THAT IS REQUIRED BY ITS FROZEN
FIXED-LEAD, ISSUE-TIME, AVAILABILITY, AND CUTOFF-SAFETY CONTRACT. THE
HISTORICAL FORECAST ENDPOINT SUPPLIES THE 21 RICH PROFILE VALUES ONLY AS A
`stitched_continuous_archive` WITH EMPTY ISSUE TIME, WHICH THIS CONTRACT
EXPLICITLY REJECTS. ROUTING 20 FIELDS THERE WOULD CREATE THE ALREADY-DOCUMENTED
HYBRID RESEARCH INPUT, NOT A VALID PIT CORPUS, AND WOULD CHANGE WHAT THE FIRST
CANDIDATE IS TRAINED ON. PER THE HANDOFF'S FALSIFICATION RULE, P1 STOPPED:
NO BASE-CORPUS PRODUCER WAS WRITTEN AND THE OPERATOR MUST FIRST CHOOSE A NEW
FROZEN FORECAST-INPUT CONTRACT.**

## Branch, basis, and safety

- Branch:
  `codex/workstation-write-the-corpus-producer-2026-09-55a`.
- Base: fetched `origin/master` at
  `65c503058b1d84d51a0c3e1db2e558c2a8c479a9`.
- `docs/operations/reserved-confirmation-window.md` was checked at run time.
  Nothing is reserved; no candidate was fitted or frozen.
- `artifacts/releases` and
  `artifacts/releases/current_release.json` were absent before and after the
  trace. No release store or pointer was created.
- The only generated evidence is below ignored
  `scratch/runs/corpus-producer-09-55a`. Nothing under `data/`, a release
  store, pointer, scheduler, loop, settlement path, or trading state was
  written.
- No weather-provider endpoint was called. The plan command is code-owned,
  deterministic for the supplied timestamp, and declares
  `network_authorized=false` and `provider_probe_authorized=false`.

## P0 — actual plan-to-endpoint trace

`weather.sources.forecast_training_corpus.build_plan()` constructs one request
per market/year. `_binding_for()` transforms every frozen source field to
`<field>_previous_day1`; the enclosing request unconditionally names
`PREVIOUS_RUNS_ENDPOINT`. `verify_plan()` recomputes both the endpoint and all
21 bindings, so changing a request after planning fails its self-hash and the
frozen-contract checks.

The no-network planner was run for the same June 3–17, 2021–2025 rehearsal
population used by the predecessor missions:

| Direct measurement | Result |
| --- | ---: |
| Plan schema | `pit_forecast_corpus_plan_v1` |
| Markets / years / request units | 12 / 5 / **60** |
| Market/date/cutoff cells | **12,600** |
| Frozen source fields | **21** |
| Field/date/cutoff cells | **264,600** |
| Unique request endpoint | `https://previous-runs-api.open-meteo.com/v1/forecast` |
| Unique issue-evidence kind | `fixed_lead_offset` |
| Plan self-hash | `7b4bc9b564187e652e734309b5e2f1be45ad69b93f1eefb0cf0e342ac4b3f706` |
| Plan file SHA-256 | `a9f43252d8b44e788249e441b58b26c88334a2b72064936dfd498a476f5d0d14` |

Every field routes identically:

| Source field | Requested field | Endpoint |
| --- | --- | --- |
| `temperature_2m` | `temperature_2m_previous_day1` | Previous Runs |
| `cloud_cover` | `cloud_cover_previous_day1` | Previous Runs |
| `cloud_cover_low` | `cloud_cover_low_previous_day1` | Previous Runs |
| `cloud_cover_mid` | `cloud_cover_mid_previous_day1` | Previous Runs |
| `cloud_cover_high` | `cloud_cover_high_previous_day1` | Previous Runs |
| `shortwave_radiation` | `shortwave_radiation_previous_day1` | Previous Runs |
| `wind_speed_10m` | `wind_speed_10m_previous_day1` | Previous Runs |
| `cape` | `cape_previous_day1` | Previous Runs |
| `temperature_925hPa` | `temperature_925hPa_previous_day1` | Previous Runs |
| `temperature_850hPa` | `temperature_850hPa_previous_day1` | Previous Runs |
| `geopotential_height_500hPa` | `geopotential_height_500hPa_previous_day1` | Previous Runs |
| `direct_radiation` | `direct_radiation_previous_day1` | Previous Runs |
| `diffuse_radiation` | `diffuse_radiation_previous_day1` | Previous Runs |
| `wind_gusts_10m` | `wind_gusts_10m_previous_day1` | Previous Runs |
| `visibility` | `visibility_previous_day1` | Previous Runs |
| `precipitation_probability` | `precipitation_probability_previous_day1` | Previous Runs |
| `precipitation` | `precipitation_previous_day1` | Previous Runs |
| `soil_temperature_0cm` | `soil_temperature_0cm_previous_day1` | Previous Runs |
| `soil_moisture_0_to_1cm` | `soil_moisture_0_to_1cm_previous_day1` | Previous Runs |
| `vapour_pressure_deficit` | `vapour_pressure_deficit_previous_day1` | Previous Runs |
| `et0_fao_evapotranspiration` | `et0_fao_evapotranspiration_previous_day1` | Previous Runs |

This mission did not re-probe the provider. The accepted production result
remains 1 of 21 PIT-available fields: `temperature_2m`; 17 all-null and 3 HTTP
400. Crossed intervals and power do not apply because this is an endpoint and
contract-identification result, not a sampled model-performance estimand.

## Why the historical endpoint does not collapse the wall

The repository proves that the historical endpoint carries the values but
also proves they have the wrong evidence semantics:

1. `forecast_history.historical_forecast_rows()` emits all 21 rich fields with
   `source=open_meteo_historical_forecast`, `issue_time=""`, and
   `issue_time_basis=stitched_continuous_archive`.
2. The immutable PIT plan sets `issue_time_required=true`,
   `available_at_utc_required=true`, and rejects `stitched` and
   `stitched_continuous_archive` evidence. Staging requires every field to be
   present with a valid unit; materialization requires every field complete and
   safe at each cutoff.
3. `PIT_FORECAST_TRAINING_CORPUS.md` makes that semantic requirement explicit:
   all contracted fields, accepted issue evidence, and issue/availability at or
   before every feature cutoff.
4. `ForecastTrainingVariantResolver(variant="hybrid")` already implements the
   proposed physical split: PIT daily high from Previous Runs and settled
   profiles from Historical Forecast. Its contract records
   `uses_settled_profiles=true`. The canonical PIT-corpus document explicitly
   says this A/B/C input does **not** satisfy base-retrain PIT-manifest
   preflight.

Therefore the plan does ask one endpoint for everything, but the minimal
correction is not to change 20 URLs. A URL-only split would either fail the
current issue-evidence verifier or mislabel settled profiles as point-in-time.
The actual alternatives are contract decisions:

- freeze a temperature-only PIT corpus and explicitly drop the 20 profile
  fields from this candidate input;
- freeze a hybrid immutable corpus that names the 20 profiles as settled,
  removes their PIT claim, and accepts the corresponding fit-time semantics;
  or
- adopt another reviewed free source that supplies issue-bound versions of
  the missing fields.

The first two change the candidate's training inputs. The third has not been
established. Paid weather data remains out of scope. None is delegated to this
mission.

## Why P1 stopped before implementation

The handoff says that a genuine free-tier wall is an operator decision about a
frozen contract and requires the mission to stop rather than narrow the field
set. That falsifier fired.

The base producer cannot honestly choose among `honest`, `rich`, or `hybrid`
semantics on the operator's behalf. The accepted `-09-53a` path uses
`build_market_records()` plus an explicit forecast resolver to assemble the
code-owned matrix. The official writer should reuse that assembly after the
forecast contract is decided, publish immutable per-market record files, and
derive the manifest evidence that `base_retrain.evaluate_preflight()` already
consumes. Building it now would freeze one of those unresolved semantics into
the manifest producer and make a future candidate look auditable under a
contract the operator did not choose.

No seventh blocker was exposed because the sixth correctly prevented manifest
publication and preflight.

## Verification

Focused deterministic tests were run with the retained compatible Python 3.12
environment because this worktree has no repository `venv`:

```powershell
C:\Users\Michael\Documents\github\weather\scratch\r30a\.venv\Scripts\python.exe -B -m pytest `
  -p no:cacheprovider `
  --basetemp scratch\pytest-09-55a `
  -q `
  tests\sources\test_forecast_training_corpus.py `
  tests\sources\test_forecast_training_variants.py `
  tests\operations\test_base_retrain.py
```

Observed: **32 passed in 4.04 s**.

## Production-host reproduction

Run from the production checkout. These commands write only a new disposable
plan under `C:\tmp`; they do not fetch, stage, materialize, fit, or touch
production `data/` or releases.

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
$python = '.\venv\Scripts\python.exe'
$run = 'C:\tmp\weather-corpus-producer-09-55a-verify'
$plan = "$run\pit-plan-june10.json"
if (Test-Path -LiteralPath $run) {
  throw "Choose a new empty scratch root: $run"
}

& $python -B -m weather.sources.forecast_training_corpus plan `
  --out $plan `
  --years 2021,2022,2023,2024,2025 `
  --target-year 2026 `
  --season-start 06-03 `
  --season-end 06-17 `
  --cutoff-hours 7,8,9,10,11,12,13,14,15,16,17,18,19,20 `
  --source-model gfs_seamless `
  --lead-days 1 `
  --planned-at-utc 2026-08-09T00:00:00+00:00
if ($LASTEXITCODE -ne 0) { throw 'PIT planning failed.' }

$payload = Get-Content -Raw -LiteralPath $plan | ConvertFrom-Json
$payload.requests | ForEach-Object endpoint | Sort-Object -Unique
$payload.requests[0].variables |
  Select-Object source_field,request_field
$payload.issue_contract
$payload.summary

Select-String -Path src\weather\sources\forecast_history.py `
  -Pattern 'issue_time=""|issue_time_basis="stitched_continuous_archive"'
Select-String -Path src\weather\sources\forecast_training_variants.py `
  -Pattern 'uses_settled_profiles|profile_source'
```

Expected: exactly one endpoint (`previous-runs-api`); 21
`*_previous_day1` bindings; fixed-lead issue/availability requirements; 60
requests; 12,600 market/date/cutoff cells; and Historical Forecast rows marked
as stitched with empty issue time.

## Mechanical roll verdict

The repository-owned command was run from the primary checkout, where the
retained live-closure evidence exists:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-write-the-corpus-producer-2026-09-55a
```

Result: **ROLL-FREE**. The primary checkout's local `master` is nine commits
behind the required `origin/master` base, so the mechanical command reported
14 changed files. It found one importable file and classified it `free`; the
other 13 were non-importable config/documentation. The dormant
`clob_enrichment` closure was mechanically subsumed by the live closures.

| File seen by the mechanical comparison | Live closures | Verdict |
| --- | --- | --- |
| `config/location_market_events.json` | none | Roll-free |
| `config/locations.json` | none | Roll-free |
| `docs/operations/ESTABLISHED_FINDINGS.md` | none | Roll-free |
| `docs/operations/HOW_WE_GET_THINGS_WRONG.md` | none | Roll-free |
| `docs/operations/OPERATING_REFERENCE.md` | none | Roll-free |
| `docs/operations/README.md` | none | Roll-free |
| `docs/operations/STATE_OF_PLAY.md` | none | Roll-free |
| `docs/roadmap/agent-report-2026-08-18-workstation-corpus-producer.md` | none | Roll-free |
| `docs/roadmap/workstation-handoff-2026-09-51a-map-the-release-bootstrap-before-we-spend-it.md` | none | Roll-free |
| `docs/roadmap/workstation-handoff-2026-09-52a-does-the-held-branch-already-close-the-gap.md` | none | Roll-free |
| `docs/roadmap/workstation-handoff-2026-09-53a-build-the-research-parent-path.md` | none | Roll-free |
| `docs/roadmap/workstation-handoff-2026-09-54a-produce-the-official-corpus-manifests.md` | none | Roll-free |
| `docs/roadmap/workstation-handoff-2026-09-55a-write-the-missing-producer-and-trace-the-endpoint.md` | none | Roll-free |
| `src/weather/operations/operating_reference.py` | none; mechanically `free` | Roll-free |

The actual branch diff against its required `origin/master` base is only the
report file. It enters no capture closure.

## What was not done

- No provider or exchange endpoint was called; no credential was read.
- No manifest, request receipt, issue evidence, or lineage record was
  hand-authored, relabelled, or passed as qualified evidence.
- No base producer, PIT collector, source-field narrowing, hybrid corpus,
  verifier relaxation, or endpoint-routing change was implemented.
- No model was fitted, scored, selected, frozen, promoted, activated, served,
  or traded.
- No production `data/`, mirror, canonical artifact, release, pointer, tape,
  ledger, scheduler, supervisor, loop, settlement, or trading state changed.
- No serving floor, minimum-row floor, station-day exclusion, promotion gate,
  feature contract, probability contract, or release contract was weakened.
- No PR, merge, master push, branch deletion, restart, registration, or live
  action occurred.

## Commit

- Evidence/report commit:
  `3a3037b38a2a6e8ac6a7de479c76045fcfa77570`.
- Final metadata commit: the pushed branch head is authoritative.
