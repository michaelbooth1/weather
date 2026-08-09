# Workstation report 2026-09-43a — repair the blind local-meteorology block

## Verdict

**IMPLEMENTATION COMPLETE; 96 CLASSIFIED PARITY BLOCKERS CLOSED; SERVED OUTPUT
MOVES, BUT BENEFIT IS NOT POWERED; ROLL-SENSITIVE.** The eight trained numeric
inputs named by the handoff now use cutoff-aligned captured station rows only
when the canonical WU field is unavailable. The serving floor, probability
mass, provider missingness, and native settlement units are unchanged.

The deterministic parity gate moves from 196 blockers to 100 with **zero
unexpected findings**. The known-defects fixture is byte-unchanged. All eight
fields are the exact eight in §4's “8 of 29 trained inputs dead at serve”; none
is additional. `wind_gust_kmh` and `wind_shift_3h_degrees` remain the two
additional prospective fields repaired by `-09-39a`.

The repair changes 1,649 of 1,680 admitted incumbent distributions across two
provenance-isolated receipts. Both positive controls are exact. Brier moves in
the favorable direction in both regimes, but both crossed intervals include
zero and plug-in power is only 6.9% and 13.1%. The result is therefore **not
powered**, not a serving-win claim. It fits no candidate and authorizes no
promotion.

Implementation commit: `b17f29b0f48b8329a376aaa10c8af4d635ff8a19` on
`codex/workstation-repair-the-blind-feature-block-2026-09-43a`, based on the
declared stacked dependency
`origin/codex/workstation-exclude-denver-station-days-and-fit-2026-09-42a` at
`1937d34fd83dc870a3136c9faf4953de4712c57d`.

## P0 — what was actually absent

The handoff's production-file inventory and the workstation's retained replay
envelopes describe different surfaces. The production WU history files carry
all eight inputs, but those after-the-fact files are not point-in-time serving
inputs. Captured replay inputs have an empty `wu_history` surface and carry
station rows separately. The old `station_observations` adapter returned only
top-level temperature/max values and discarded those rows before feature
extraction.

The four commissioned absence categories are used below:

1. adapter never produced the field at serve time;
2. adapter produced it but the serving feature route dropped it;
3. provider used a different name or unit;
4. field was derivable, but serving retained no routed history window.

| Feature | U.S. markets | Toronto | Repair and honest boundary |
| --- | --- | --- | --- |
| `dewpoint_c` | METAR `dewpoint_native`; categories 2+3 | SWOB direct; category 2 | Route provider-native dewpoint from the cutoff row. Legacy `_c` remains native-unit data. |
| `humidity` | AviationWeather v2 capture omitted it; category 1 | SWOB direct; category 2 | v3 retains direct provider `rh`/`humidity`; old U.S. replay remains honestly missing. |
| `pressure` | METAR exposes altimeter/sea-level hPa, not the trained WU station-pressure quantity; category 3 | SWOB v2 omitted `stn_pres`; category 1 | v3 retains direct Toronto station pressure. METAR pressure is kept under explicit names and is **not** aliased into WU `pressure`, especially unsafe at Denver elevation. |
| `wind_speed_kmh` | METAR knots; categories 2+3 | old SWOB capture omitted wind, but captured METAR supplies it; categories 1+2+3 | Normalize knots to the artifact's native WU unit: mph in F markets, km/h in Toronto. |
| `pressure_trend_3h` | no comparable pressure history; categories 3+4 | v2 held no pressure history; categories 1+4 | Derive only within one routed pressure surface; never mix WU, SWOB, or METAR pressure semantics. |
| `rise_from_7am` | METAR temperature rows existed; categories 2+4 | SWOB temperature rows existed; categories 2+4 | Derive current minus the closest 07:00 row on the same cutoff-aligned station surface. |
| `warming_rate_2h` | METAR temperature rows existed; categories 2+4 | SWOB temperature rows existed; categories 2+4 | Derive from the closest same-surface row two hours before the effective cutoff. |
| `hours_at_peak` | METAR temperature rows existed; categories 2+4 | SWOB temperature rows existed; categories 2+4 | Find the first same-surface row equal to the trusted high; do not weaken or replace the high. |

This corrects one premise in the handoff: a METAR pressure-shaped value is not
automatically the trained WU pressure feature. Presence would have been easy;
substantive parity would have been false. The same rule keeps unavailable
historical humidity and pressure missing rather than synthesizing them.

## P1 — implementation and deterministic parity

`station_observation_data` now carries normalized station rows through the
existing serving route. Feature extraction filters every WU and station row to
the effective print cutoff before using it. WU remains first. Direct fields may
fall through the declared station source order; derived fields stay within one
surface. Toronto may therefore use SWOB humidity and METAR wind without mixing
pressure surfaces.

The source contracts advance SWOB and METAR parsers from v2 to v3. SWOB v3
retains direct station pressure, sea-level pressure, temperature, dewpoint,
humidity, and wind. METAR v3 retains direct humidity and explicit altimeter and
sea-level pressure, but deliberately creates no `pressure` alias. The feature
store advances from v1.15 to v1.16, retaining v1.15 as a legacy schema.

The schema-registry change is **not additive-only as a whole**. The new
`blind_feature_repair_replay_v0.1` family and legacy v1.15 entry are additive,
but the active feature-store version changes from v1.15 to v1.16. That version
advance describes real serving behavior and must not be represented as an
inert registry-only merge.

The parity proof reports:

| Status | Blockers | Unexpected | Known groups rediscovered | Coverage blockers | Self-hash |
| --- | ---: | ---: | ---: | ---: | --- |
| `BLOCK` (expected retained defects) | 100 | **0** | 3/4 | 0 | `8629a929823e91673f0fb8e61be550082d01047bbe0128fe92463e31b0c17bb6` |

The former `nine_empty_base_features_09_to_14` fixture group is no longer fully
rediscovered: only its out-of-scope categorical `wind_group` remains. The other
three known groups still reproduce. Proof mode therefore exits 2 for the right
reason; no fixture or gate was weakened to force exit 0.

## P2 — captured-input completeness

The table combines the two valid, provenance-correct replay windows only:
10,885 pre-roll and 16,978 post-roll captured snapshots, 27,863 total. Every
control cell is 0.0%; entries below are repaired population rates.

| Market | Dewpoint | Humidity | Pressure | Wind speed | Pressure trend | Rise 07:00 | Warming 2h | Hours at peak | Rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| atlanta | 99.9% | 0.0% | 0.0% | 99.9% | 0.0% | 76.2% | 83.9% | 92.3% | 2,325 |
| austin | 100.0% | 0.0% | 0.0% | 100.0% | 0.0% | 76.0% | 83.9% | 93.7% | 2,319 |
| chicago | 99.9% | 0.0% | 0.0% | 99.9% | 0.0% | 76.4% | 83.8% | 93.9% | 2,346 |
| dallas | 99.8% | 0.0% | 0.0% | 99.7% | 0.0% | 75.6% | 83.6% | 95.6% | 2,299 |
| denver | 95.6% | 0.0% | 0.0% | 95.6% | 0.0% | 73.7% | 79.3% | 95.4% | 2,361 |
| houston | 99.8% | 0.0% | 0.0% | 99.8% | 0.0% | 76.6% | 84.2% | 95.1% | 2,298 |
| los-angeles | 99.2% | 0.0% | 0.0% | 99.2% | 0.0% | 76.0% | 83.9% | 94.9% | 2,236 |
| miami | 99.9% | 0.0% | 0.0% | 99.8% | 0.0% | 76.4% | 83.8% | 95.6% | 2,276 |
| nyc | 99.7% | 0.0% | 0.0% | 99.7% | 0.0% | 76.4% | 84.0% | 94.2% | 2,288 |
| san-francisco | 99.2% | 0.0% | 0.0% | 99.2% | 0.0% | 75.6% | 83.6% | 96.0% | 2,303 |
| seattle | 99.3% | 0.0% | 0.0% | 99.3% | 0.0% | 75.1% | 83.3% | 94.4% | 2,350 |
| toronto | 99.6% | 99.6% | 0.0% | 99.2% | 0.0% | 76.6% | 84.3% | 99.4% | 2,462 |
| **Fleet** | **99.31%** | **8.80%** | **0.00%** | **99.26%** | **0.00%** | **75.87%** | **83.46%** | **95.07%** | **27,863** |

The zeros are evidence, not implementation failures. Old U.S. AviationWeather
envelopes do not retain humidity. Old Toronto SWOB envelopes do not retain raw
XML or pressure. The new parsers make direct values available going forward;
the retained corpus cannot be retroactively enriched without synthesis.

## P2 — served-output delta and power

An initial July 22–August 7 run correctly blocked its positive control because
the current code cannot reproduce the pre-`b77cfbed` rescued-floor runtime.
Regime was then classified per captured runtime commit—not per folder and never
by target-date age. The pre-roll slice ran on the prior proven runtime
`641f71337f9279c579a743bbd605fc1c54d5a391` plus only the station-row routing;
the post-roll slice ran on the current stack. July 31's eight pre-anchor rows
were excluded from the post receipt explicitly.

Both receipts select the first snapshot per market, target date, effective
cutoff, and provenance regime. Ledger revisions are deduplicated to
`(market, target_date)` before `promotion_countable` is applied. Metrics are
daily-first, then use a 10,000-replicate crossed pigeonhole bootstrap with
independent date and market weights. Centre and width use Celsius-equivalent
units; Brier is repair minus control, so negative is favorable.

| Regime | Dates | Positive control | Changed | Centre delta C-eq. [95%] | Width delta C-eq. [95%] | Brier delta [95%] | Brier power; 80% MDE |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| pre-anchor | 2026-07-22..26; D=5, M=12, 60 days, 840 cells | 840/840 exact; max L1 0 | 828 | 0.00430 [-0.02267, 0.03928] | 0.01579 [-0.00495, 0.03644] | -0.00380 [-0.02175, 0.01616] | 6.9%; 0.02664 |
| post-anchor | 2026-07-31..08-07; D=5 countable, M=12, 60 days, 840 cells | 840/840 exact; max L1 0 | 821 | 0.03345 [-0.00936, 0.08035] | 0.01764 [-0.00289, 0.04189] | -0.00816 [-0.02972, 0.00961] | 13.1%; 0.02767 |

Pre receipt self-hash:
`70ce2a430fdc8c01c6f56f904d7eadd70eebd4624133684faf01c01f7f946ee4`.
Post receipt self-hash:
`8afdab2fc11e8f612eafad4b62e55306dcebcdbdd6a22cf4188b0f1ae26caa9c`.

No centre, width, or Brier comparison is adequately powered. The repair
restores input parity and materially changes incumbent output; the available
independent date support cannot establish that the change improves scoring.

## Consequence for established findings

The successful routing repair changes the baseline used by §4 and therefore
invalidates reuse of model-performance numbers measured while these inputs
were always imputed. Before they are cited as current, remeasure:

- the clean market gap, market-sharpness decomposition, and any in-season gap;
- the 09:00–12:00 cool bias and seasonal-distance center comparisons;
- severe-tail Brier, severity-band suppression, and ex-ante tail detectability;
- residual centre displacement and mass-below-floor magnitudes.

The serving floor's mechanical safety finding itself is not retracted: this
mission never weakens it, and both replay controls preserve it. What expires is
the downstream magnitude measured on the blind input surface. `-09-26a` also
remains a valid NO-GO for its external-source treatment; it is not evidence
against this captured-station treatment and its numerical result does not
transfer here.

## Verification

Focused owner verification under Python 3.11:

```text
33 passed, 666 subtests passed
```

This covers feature extraction, F-market native units, raw SWOB replay,
alternate Toronto METAR wind, pressure-semantic refusal, METAR parser retention,
parity, receipt rendering/hash, and schema lookup. Additional checks:

```text
python -m compileall -q app src tests
PASS

python -m weather.operations.agent_docs_audit
PASS (18 agent files, 720 Markdown files before this report)

git diff --check
PASS
```

The canonical full suite reached 98% and hit its 15-minute workstation bound.
A bounded last-failed rerun completed with 710 passed, 4 skipped, 37 deselected,
and 24 failures. One was the tracked-or-ignored ratchet while the two new files
were untracked; it passed after exact staging. The remaining 23 do not assert a
mission-owned path: 13 are Windows path-length failures caused by the relative
scratch base, four are PowerShell execution-policy failures, two are protected
`data/` cache-write failures, and one each is inherited settlement-ledger,
schema-audit, paid-provider-prose, and relative-path behavior. These overlap the
stacked branch's previously reported red inventory; this report does not call
them master-equivalent or hide them behind the four failures named on master.

The project `venv` points to a removed Python 3.11 installation on this
workstation. Verification used an official Python 3.11.9 embeddable runtime
against the repository's existing venv packages; no repository dependency or
environment file changed.

## Roll verdict

`scripts\ops\roll_verdict.ps1 -Branch
codex/workstation-repair-the-blind-feature-block-2026-09-43a` inspected the
committed branch against master and returned exit 3, **ROLL-SENSITIVE**. The
cumulative stacked branch has 82 changed files and 29 importable files. The
dormant CLOB-enrichment closure is mechanically subsumed by live closures.

| Mission file | Retained live closures | Verdict |
| --- | --- | --- |
| `src/weather/model/feature_store.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/model/model_features.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/model/model_sources.py` | snapshot, observation-trigger | **Roll-sensitive** |
| `src/weather/schema_registry_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive** |
| `src/weather/schema_registry_recent_data.py` | snapshot, CLOB, observation-trigger | **Roll-sensitive** |
| `src/weather/reporting/research/blind_feature_repair.py` | none | Roll-free |
| all five changed test files | none | Roll-free |
| this report | none | Roll-free |

Integration belongs in the 01:00–04:00 quiet window through
`quiet_window_merge.ps1`. Pushing this branch does not roll production.

## Explicitly not done

- No candidate, calibration, artifact, or release was fitted, generated,
  frozen, promoted, registered, or activated.
- No weather-provider call, paid source, credential, or new collection ran.
- No production `data/`, mirror, tape, ledger, trading evidence, scheduled
  task, collector, supervisor, or live process was written or restarted.
- No serving floor, probability-mass contract, promotion gate, or known-defect
  fixture was weakened or edited.
- No confirmation window was declared; the reserved-window file was checked
  and remained armed but undated.
- No PR, merge, production checkout, or runtime adoption was performed.

## Production-host reproduction

After fetching this branch in a repository worktree, these paths exist on the
production host and write only ignored `scratch/` evidence:

```powershell
$branch = 'origin/codex/workstation-repair-the-blind-feature-block-2026-09-43a'
git rev-parse $branch

$runRoot = 'scratch\runs\weather-blind-feature-repair-09-43a-production-verify'
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q `
  tests/model/test_feature_skew.py `
  tests/model/test_source_cache_ttl.py::TestSourceCacheTtl::test_metar_carries_raw_payload_for_observation_sidecar `
  tests/reporting/test_train_serve_feature_parity.py `
  tests/reporting/test_blind_feature_repair.py `
  tests/operations/test_schema_registry.py::TestSchemaRegistry::test_registry_lookup_returns_public_versions

.\venv\Scripts\python.exe -B -m weather.reporting.scorecards.train_serve_feature_parity `
  --input tests\fixtures\train_serve_feature_parity_known_defects_v0.1.json `
  --run-root "$runRoot\parity" `
  --proof-mode

.\venv\Scripts\python.exe -B -m weather.reporting.research.blind_feature_repair `
  --snapshots-root data\snapshots `
  --settlements-root data\settlements `
  --output-root "$runRoot\post" `
  --start-date 2026-07-31 `
  --end-date 2026-08-07 `
  --provenance-regime post_2026_07_31_artifact

powershell.exe -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\ops\roll_verdict.ps1 `
  -Branch $branch
```

Expected parity result: `BLOCK`, 100 blockers, zero unexpected findings, 3/4
historical groups fully rediscovered. Expected post replay result: `PASS`, 840
exact positive-control rows, 821 changed distributions, D=5, M=12, 60
market-days. Expected roll result: `ROLL-SENSITIVE` (exit 3).

The provenance-frozen pre-roll replay is workstation-owned supporting evidence,
as in `-09-39a`, and is intentionally not prescribed on production. Its
disposable archived runtime and ignored receipt contain no unique operational
state and are not committed.
