# Workstation report 2026-08-13 — first-retrain rehearsal

**VERDICT: THE IN-SEASON CORPUS ASSEMBLES 12,600/12,600 CELLS, BUT THE
OFFICIAL RETRAIN CANNOT REACH PREFLIGHT. IT FAILS FIRST ON THE ABSENT ACTIVE
PARENT RELEASE, AND THE REHEARSAL TARGET CANNOT TEST THE DENVER EXCLUSION. NO
CANDIDATE WAS FITTED.**

The read-only rich-archive feature path completed for all 12 markets on target
`2026-06-10`. The official `weather.operations.base_retrain` invocation then
wrote only its plan and failed in `load_parent_contract()` because there is no
active release pointer. Two further independent inputs are also absent: the
only retained research corpus manifest has the wrong schema and target, and it
is rejected outright by the immutable PIT-corpus verifier.

The handoff's proposed target is valid for archive-row containment but not for
testing `-09-42a`: `2026-06-10` selects June 3–17 in each prior year, so its
code-owned exclusion set is empty. A target whose ±7-day population contains
Denver `2025-07-28` necessarily needs archive rows after June 30. With the
current single `--target-date` contract, the two requested properties cannot
hold simultaneously. This is the handoff's explicit “in-season target is not a
valid rehearsal” falsifier for the exclusion claim.

## Branch, basis, and safety

- Branch: `codex/workstation-rehearse-the-first-retrain-2026-09-50a`
- Base: `origin/master` at
  `eef907565c639ddf9bd5e315f6cdcb12b418c674`
- Handoff read from that exact remote-tracking commit.
- `docs/operations/reserved-confirmation-window.md` was checked at run time.
  No dates are reserved; the window remains armed but undated. No candidate was
  frozen and no reservation was declared.
- The run used the repository Python 3.11.9 environment. Its base interpreter
  is outside the workspace sandbox, so commands required the existing local
  execution permission; no dependency was installed or changed.
- All generated output was under ignored workstation scratch or
  `C:\tmp\weather-retrain-09-50a`. Nothing under `data/`, tracked
  `artifacts/`, an active pointer, or an immutable release store was written.
- The workstation mirror is not production evidence. The row-coverage and
  corpus counts below describe the local mirrored inputs; the production
  archive bounds stated in the handoff were accepted as supplied facts.

## P0 — target validity and archive containment

The code-owned radii are 7 target days plus a 7-day climatology halo, for a
total archive radius of 14 days. For `2026-06-10`, every 2021–2025 request
window is May 27–June 24, which is contained inside the handoff's May 10–June
30 archive coverage.

| Contract | `2026-06-10` | Real target `2026-07-31` |
| --- | --- | --- |
| Selected training dates per year | June 3–17 | July 24–August 7 |
| Archive radius | May 27–June 24 | July 17–August 14 |
| Required cells | **12,600** | **12,586** |
| Active station-day exclusions | **0** | Denver `2025-07-28` |
| Tests `-09-42a` exclusion | **No** | Yes |

The mirrored CSV rows cover all 145 required market-dates per market for the
June target: 1,740/1,740 fleet market-dates and zero missing dates. The
repository coverage gate nevertheless returns `BLOCK`, 0/12 markets, because
all 12 legacy manifests say neither `target_date` nor `target_window_contract`;
their target status is `UNDECLARED`. The sole blocker on every market is
`archive_target_manifest_mismatch`. This is metadata/provenance, not missing
archive rows, and it means the legacy mirror cannot itself supply a formally
passing target-bound archive receipt.

## P0 — corpus result

The actual `build_market_records()` path was exercised with an explicit
`ForecastTrainingVariantResolver(..., variant="rich")`, the June population,
cutoffs 07–20, all 12 built-in markets, and no writes. Every market produced
75 market-days × 14 cutoffs = 1,050 cells.

| Measure | Result |
| --- | ---: |
| Markets passing | **12/12** |
| Fleet cells | **12,600/12,600** |
| Missing / unexpected cells | **0 / 0** |
| Record fields per assembled row | 286 |
| Active code-owned exclusions | **0** |
| Denver `2025-07-28` exercised | **False** |

This proves the in-season local rich feature assembly is complete. It does not
prove the official hash-bound base corpus, the PIT corpus, or the July exclusion
path. In particular, it must not be reported as “`-09-42a` cleared the first
retrain”; that proposition was not executable with an archive-contained target.

## Exact blocker order

### 1. Verified active parent release — first runtime blocker

The official CLI accepted the explicit arguments, created the candidate root,
and wrote `base_retrain/plan.json`. It then failed before reading either corpus
manifest:

```text
weather.release_artifacts.ReleaseArtifactVerificationError:
active release pointer is missing:
C:\tmp\weather-retrain-09-50a\releases\current_release.json
```

The checkout has neither `artifacts/releases/` nor
`artifacts/releases/current_release.json`; the scratch store was deliberately
empty and remained so. The CLI requires the explicit parent to match an active
pointer, verify as a research-only release, bind all 84 market components, and
supply the exact feature contract.

What would fix it: provide a verified research-only parent and matching active
pointer, or redesign the first-retrain bootstrap contract. The current project
decision defers Release #1 until a retrained candidate exists, while the
retrain requires an active parent. That circular prerequisite needs an operator
decision; this mission was explicitly forbidden to create or update a pointer.

The missing-pointer exception also escapes the CLI's
`BaseRetrainContractError` handler and prints a traceback. That is secondary to
the missing parent, but it is the exact operational failure surface.

### 2. Official base feature-corpus manifest — independently absent

The best retained real feature corpus is
`honest_rich_hybrid_feature_corpus_manifest_v0.2`, target `2026-07-31`, with 36
variant/market entries. The base retrain requires
`all_market_base_retrain_corpus_manifest_v0.1`, target `2026-06-10`, and an
exact `markets` mapping with selected WU rows, record-file hashes, frozen
feature order, parity samples, sidecars, and fold/final support. The retained
manifest has no `markets` mapping and cannot be substituted.

What would fix it: a reviewed producer must materialize the official
row-level, hash-bound base manifest for the chosen target. No such real
manifest was found outside deterministic pytest outputs. This mission did not
invent one or convert the research A/B/C manifest.

### 3. Immutable PIT forecast corpus — independently absent

Passing the retained A/B/C manifest to
`preflight_pit_forecast_training_corpus()` returns:

```text
CorpusVerificationError: unsupported PIT forecast corpus manifest schema
```

The rich-archive feature rows are not the immutable PIT corpus required by the
official lane. They do not satisfy its request/raw hashes, issue and
availability timestamps, corpus identity, or exact feature-record selection
binding.

What would fix it: supply a complete verified PIT corpus manifest whose exact
selection binding matches the base records, or make a separately reviewed
change to the official retrain input contract. The previously established
Previous Runs limitations remain in force; this run made no provider call and
did not fabricate issue evidence.

### 4. The in-season target cannot validate the real exclusion

Even if blockers 1–3 were supplied, `2026-06-10` would still produce a
12,600-cell no-exclusion plan. It cannot answer whether Denver
`2025-07-28` is actually removed from the real 12,586-cell corpus. Conversely,
the real July target is outside the current archive and violates the handoff's
instruction not to use an out-of-season target.

What would fix it: after the target-derived archive is extended, rehearse the
real `2026-07-31` target, or introduce a reviewed rehearsal contract that
separates archive-coverage selection from the code-owned training population.
No such code change was made here.

### 5. `-09-49a` was not in this run

At the branch base, `origin/master` did not contain the code from
`origin/codex/workstation-close-the-repair-follow-ups-2026-09-49a`. Therefore
the registry-unit training policy that removes `pressure` and
`pressure_trend_3h` from Fahrenheit-market fits was not present. The corpus
row count is unaffected, but any eventual fit from this branch would retain the
pre-`-09-49a` feature policy and would not reproduce the post-merge real run.

## P1 — resource envelope

Peak RSS is Windows aggregate Python working set sampled every 100 ms. Scratch
disk is the new candidate/output bytes, excluding the pre-existing input
archive. No child stage was allowed to fetch from a provider.

| Stage reached | Wall clock | Peak RSS | Peak/new disk | Result |
| --- | ---: | ---: | ---: | --- |
| Rich feature assembly, 12 markets | **12.021 s** | **331,169,792 B (315.83 MiB)** | 0 artifact bytes; 11,368 B measurement log | PASS 12,600/12,600 |
| Official CLI through parent load | **0.978 s** | **174,403,584 B (166.32 MiB)** | **9,275 B**, one plan | BLOCK missing active pointer |
| Base-manifest preflight | not reached | not measured | 0 | input absent |
| PIT preflight | not reached by CLI | not measured | 0 | independent validator BLOCK |
| Twelve-market fits | not reached | **unknown** | **unknown** | no authorization from preflight |
| Candidate graph/release assembly | not reached | **unknown** | **unknown** | no fit |

Per-market feature-assembly times were 0.795–1.062 seconds, median 0.879
seconds; the 12 market stages totalled 10.862 seconds.

The reached stages are comfortably below the production host's 3.49 GB
per-worker admission bar. That does **not** decide where retraining can run:
the memory- and disk-dominant fit/assembly stages were never reached. The
resource-placement verdict is therefore **unidentified**, not “production is
safe” and not “workstation-only.”

## Outputs and evidence

The official attempt produced exactly one file, the 9,275-byte plan. It
produced no market fit, HGB, LR coefficients, calibration, fleet receipt,
semantic graph, candidate release, manifest, or pointer.

| Evidence | SHA-256 |
| --- | --- |
| Read-only corpus stdout | `1fbfa706cd8f24393653a2acb3530a3409eecaf9c10a0c2e85641c2939e15cc9` |
| Official CLI failure stderr | `47ab5b209e1c4dbf78941c0a50611fe5ca927ce7063e37e58a2e35da311bd689` |
| Candidate-local plan | `dc1c703d85031c6e5c07c3840e5019f76e0bed8e46ab57b0f608cae92436465a` |

These ignored workstation paths are retained locally for audit but are not
used as production reproduction paths. No scoring, incumbent comparison,
confidence interval, or power calculation applies: no candidate exists.

## Production-host reproduction

Run from the existing production repository root. These checks are read-only
except for the explicitly disposable `C:\tmp` CLI attempt; they do not write
production `data/`, update a pointer, fetch a provider, fit, register, restart,
settle, promote, or trade.

Code-owned containment and the incompatible exclusion sets:

```powershell
Set-Location C:\Users\micha\Desktop\github\weather
$python = '.\venv\Scripts\python.exe'

& $python -B -c "from weather.sources.forecast_history import archive_window_for_target as w; from weather.operations.base_retrain import _training_population_for_target as p; import json; print(json.dumps({'june_windows':{str(y):[d.isoformat() for d in w(y,'2026-06-10')] for y in range(2021,2026)},'june':p('2026-06-10'),'july':p('2026-07-31')},indent=2))"
```

Expected: June archive windows May 27–June 24, June required cells 12,600
with zero exclusions, and July required cells 12,586 with Denver
`2025-07-28` excluded.

Read-only local archive receipt:

```powershell
& $python -B -m weather.sources.forecast_history fleet-coverage `
  --target-date 2026-06-10 --years 2021,2022,2023,2024,2025
```

On the legacy mirrored manifests this reports 0/12 because target binding is
undeclared even though the required rows are present. Production should use
its current local manifests as the authority; a different result is expected
after target-derived publication.

Read-only corpus count using the existing explicit rich archive:

```powershell
@'
from weather.calibration.pooled_feature_assembly import build_market_records
from weather.market.market_registry import all_specs
from weather.operations.base_retrain import _training_population_for_target
from weather.sources.forecast_training_variants import ForecastTrainingVariantResolver

p = _training_population_for_target("2026-06-10")
dates = set(p["selected_dates"])
hours = tuple(p["cutoff_hours_local"])
total = 0
for spec in all_specs():
    resolver = ForecastTrainingVariantResolver(
        "data/forecast_history", spec, variant="rich", pit_lead_days=1
    )
    rows = build_market_records(
        spec,
        cutoff_hours=hours,
        included_target_dates=dates,
        prior_as_of_exclusive=min(dates),
        forecast_training_resolver=resolver,
    )
    print(spec.id, len(rows))
    total += len(rows)
print("fleet", total, "expected", p["expected_market_date_cutoff_count"])
'@ | & $python -B -
```

Expected on inputs equivalent to the workstation mirror: each market 1,050;
fleet 12,600.

Official first runtime blocker in disposable scratch:

```powershell
$root = 'C:\tmp\weather-retrain-09-50a-verify'
if (Test-Path $root) { throw "Choose a new empty verification root: $root" }
New-Item -ItemType Directory -Path "$root\releases" | Out-Null

& $python -B -m weather.operations.base_retrain `
  --target-date 2026-06-10 `
  --parent-release-id rehearsal-parent `
  --training-as-of 2026-08-09T13:30:00-04:00 `
  --feature-contract-id ('sha256:' + ('0' * 64)) `
  --corpus-manifest docs\operations\NIGHTLY_RETRAIN_RUNBOOK.md `
  --pit-forecast-corpus-manifest docs\operations\PIT_FORECAST_TRAINING_CORPUS.md `
  --candidate-dir "$root\candidate-rehearsal-june10" `
  --runtime-id workstation-rehearsal-09-50a `
  --releases-root "$root\releases" `
  --active-pointer "$root\releases\current_release.json" `
  --repo-root (Get-Location).Path
```

Expected: plan written under the disposable candidate; then
`ReleaseArtifactVerificationError` for the missing scratch active pointer,
before either placeholder manifest is read.

Focused deterministic verification:

```powershell
& $python -B -m pytest -p no:cacheprovider -q `
  tests\operations\test_base_retrain.py `
  tests\sources\test_forecast_training_variants.py
```

Expected: **18 passed**.

## Per-file roll verdict

This mission changes only this Markdown report. The repository-owned command
was run against the committed branch:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch codex/workstation-rehearse-the-first-retrain-2026-09-50a
```

Result: **ROLL-FREE** — 1 changed file, 0 importable files. The dormant
`clob_enrichment` closure was 315.6 hours old but mechanically subsumed by the
live closures, so it did not affect the verdict.

| Changed file | Live closures | Verdict |
| --- | --- | --- |
| `docs/roadmap/agent-report-2026-08-13-workstation-retrain-rehearsal.md` | none | Roll-free |

## Verification

```text
focused base-retrain + forecast-variant tests: 18 passed in 3.54s
June rich feature assembly: PASS, 12/12 markets, 12,600/12,600 cells
official base-retrain: BLOCK before preflight, active parent pointer missing
PIT validator on best retained research manifest: BLOCK, unsupported schema
candidate artifacts: none; one plan only
```

## What was not done

- No provider or exchange endpoint was called. No paid source, credential, or
  sync credential was read.
- No production `data/`, workstation mirror, `D:\weather-mirror`, tape,
  ledger, tracked artifact, release, active pointer, scheduler, loop,
  supervisor, settlement chain, or trading state was mutated.
- No source, config, schema, test, gate, minimum-row floor, feature policy,
  station-day exclusion, or serving behavior was changed.
- No blocker was repaired or bypassed. No synthetic parent, base manifest, PIT
  manifest, parity evidence, or issue timestamp was manufactured.
- No model was fitted, scored, selected, frozen, registered, released,
  promoted, activated, or offered as the first retrained candidate.
- No restart, merge, branch deletion, pull request, or live trade occurred.

## Commit

- Evidence/report commit:
  `e4842b8bd41fde30be88146cefc92f78167052a1`.
- Final metadata commit: the pushed branch head is authoritative.
