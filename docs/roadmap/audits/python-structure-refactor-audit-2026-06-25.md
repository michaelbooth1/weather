# Python Structure Refactor Audit - 2026-06-25

## Executive Summary

The top-level repo structure is still directionally sound: canonical code lives
under `src/weather`, app code under `app`, durable artifacts under `artifacts`,
local runtime state under ignored `data`, and the roadmap is linted from
numbered item files.

The current structure risks are not a reason for a broad top-level
reorganization. They are owner-boundary and growth-pressure issues inside the
existing layout:

1. The architecture ratchet is red because `weather.sources` now imports
   `weather.model` from `src/weather/sources/marine_water_contrast.py`.
2. The module-size ratchet has regressed to eight warnings over 2,000 lines.
3. `weather.reporting` remains the widest package: 147 Python files, 88,943
   lines, and 115 root-level modules even after the first safe subpackage move.
4. The compatibility layer is still large at 102 shims, but this is already
   owned by item 206.
5. Ignored local runtime state is operationally large at 230,575.10 MiB, but
   cleanup, storage classification, backup, and retention are already covered
   by existing roadmap items.

This audit creates two new roadmap items only for uncovered, actionable gaps:

- item 317: restore the `sources -> model` boundary ratchet.
- item 318: refresh large-module decomposition for the current eight warnings.

## Evidence And Commands Run

Baseline:

```powershell
git status --short
git ls-files *.py | Measure-Object
Get-ChildItem -Force
git ls-files | ForEach-Object { ($_ -split '[\\/]')[0] } | Group-Object
```

Native audits:

```powershell
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md --run-architecture-ratchet
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
python -m pytest tests\operations\test_import_architecture.py -q
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md --include-data-sizes
```

Results:

- Baseline worktree was clean before generated audit outputs and concurrent
  roadmap updates appeared.
- Tracked Python files: 696.
- Roadmap backlog lint: `OK` in the first native run.
- Structure inventory with architecture ratchet: `FAIL`.
- Direct architecture ratchet: `1 failed, 17 passed`; failure is
  `sources->model` from `src/weather/sources/marine_water_contrast.py`.
- Module size audit: 326 modules, 8 warnings over the 2,000-line threshold.
- Ignored data size run: 230,575.10 MiB under `data`.

## Current Structure Snapshot

Top-level tracked file counts:

| Area | Tracked files |
| :--- | ---: |
| `src` | 413 |
| `docs` | 375 |
| `tests` | 242 |
| `artifacts` | 107 |
| `tools` | 31 |
| `scripts` | 27 |
| `app` | 10 |
| `config` | 6 |

Source packages:

| Package | Python files | Lines |
| :--- | ---: | ---: |
| `weather.reporting` | 147 | 88,943 |
| `weather.market` | 42 | 30,365 |
| `weather.operations` | 37 | 24,946 |
| `weather.calibration` | 25 | 16,973 |
| `weather.sources` | 25 | 16,000 |
| `weather.model` | 18 | 12,368 |
| `weather.collection` | 10 | 7,680 |
| `weather.backtesting` | 10 | 5,003 |
| `weather.scoring` | 3 | 242 |

Largest test files:

| Test file | Lines |
| :--- | ---: |
| `tests/market/test_taker_bot.py` | 3,281 |
| `tests/operations/test_daily_refresh.py` | 2,456 |
| `tests/reporting/test_daily_learning.py` | 2,109 |
| `tests/calibration/test_pooled_candidate_replay.py` | 2,055 |
| `tests/calibration/test_promotion_refresh.py` | 1,783 |
| `tests/market/test_market_making_run.py` | 1,620 |
| `tests/reporting/test_fleet_observability.py` | 1,548 |
| `tests/reporting/test_source_family_inventory.py` | 1,512 |

Ignored data budget warnings:

| Area | MiB | Threshold MiB |
| :--- | ---: | ---: |
| `data/snapshots` | 122,094.28 | 50,000 |
| `data/tape_backups` | 81,523.99 | 50,000 |
| `data/noaa_ghcnh` | 6,321.24 | 5,000 |
| `data/backtest` | 6,192.68 | 2,000 |
| `data/wunderground` | 4,257.38 | 2,000 |
| `data/reanalysis` | 3,342.43 | 1,000 |
| `data/metar` | 3,060.00 | 2,000 |
| `data/taker_runs` | 1,565.42 | 1,000 |
| `data/mm_runs` | 1,088.31 | 1,000 |

## Findings

### P0 - Architecture Ratchet Fails On `sources -> model`

Evidence:

- `python -m pytest tests\operations\test_import_architecture.py -q` fails
  with one undocumented edge:
  `sources->model: src\weather\sources\marine_water_contrast.py`.
- The source module imports
  `weather.model.model_constants.INTRADAY_CUTOFF_HOURS`.
- `docs/operations/package-boundaries.md` says `weather.sources` owns raw
  provider fetch, parsing, daily summaries, and source-specific historical
  stores, while `weather.model` owns serving-time model assembly and feature
  extraction.
- Existing item 191 owns marine water-contrast feature readiness, but not this
  architecture boundary repair.
- Completed item 99 created the ratchet; it does not own new ratchet failures.

Impact:

The ratchet is doing its job: a source adapter now depends on model internals.
If this is documented as transitional instead of fixed, the source/model split
gets weaker exactly where historical feature assembly and serving parity need
clear contracts.

Recommended change:

Move the cutoff-hour contract to a shared neutral owner, pass cutoff hours from
callers, or keep a source-local default that does not import `weather.model`.
Then rerun the architecture ratchet and update docs only if a temporary
transition is genuinely unavoidable.

Roadmap owner:

- New item needed: item 317,
  `Marine Water-Contrast Source/Model Boundary Ratchet`.

### P0 - Module Size Ratchet Has Eight Current Warnings

Evidence:

`python -m weather.operations.module_size_audit ...` reports 8 warnings:

| Module | Owner | Lines |
| :--- | :--- | ---: |
| `src/weather/operations/tape_backup.py` | operations | 3,741 |
| `src/weather/reporting/daily/daily_learning.py` | reporting | 3,078 |
| `src/weather/operations/daily_refresh_steps.py` | operations | 2,827 |
| `src/weather/market/mm_paper.py` | market | 2,475 |
| `src/weather/schema_registry.py` | shared | 2,200 |
| `src/weather/collection/snapshot_store.py` | collection | 2,164 |
| `src/weather/market/taker_bot_bakeoff.py` | market | 2,162 |
| `src/weather/reporting/source_family_inventory.py` | reporting | 2,038 |

Prior decomposition items 90, 98, 130, 173, and 205 are complete. The current
warnings are new work, not unfinished checklist items in those completed files.
Item 270 is folder cohesion for `weather.reporting`; it is not a cross-owner
module-size recovery plan.

Impact:

The codebase has crossed the warning threshold again in operations, market,
collection, reporting, and shared registry code. The largest tests track the
same pressure, which makes future refactors slower and riskier.

Recommended change:

Create a bounded decomposition refresh: name an owner and split target for each
warning, update `docs/operations/module-ownership-map.md`, keep public CLIs and
facades stable, split tests where fixtures dominate, and drive the module-size
warning count back to zero or document explicit exceptions.

Roadmap owner:

- New item needed: item 318,
  `Post-Threshold Large Module Decomposition Refresh`.

### P1 - `weather.reporting` Is Still Too Wide

Evidence:

- `weather.reporting`: 147 Python files and 88,943 lines.
- Root-level reporting files: 115 Python modules.
- Current subpackages: `daily`, `data_quality`, `fleet`, and `promotion`.
- Item 270 already states the target taxonomy and remains `PARTIAL`.

Impact:

The package remains hard to navigate and still has many root modules that
should be grouped into hourly, scorecards, validation, casebooks, market, and
research subdomains. This is not a reason to reorganize the whole repo; it is a
reason to continue item 270 in safe slices.

Recommended change:

Continue item 270. Prioritize the remaining low-risk reporting families after
their owning model/trading items settle, and keep schema registry path updates
atomic with module moves.

Roadmap owner:

- Existing item 270. Do not create a duplicate.

### P1 - Transitional Package Edges Still Need Burn-Down

Evidence:

The structure inventory lists high-pressure edges, including:

- `reporting -> market`: 25 files.
- `reporting -> backtesting`: 23 files.
- `reporting -> model`: 18 files.
- `operations -> market`: 13 files.
- `operations -> reporting`: 12 files.
- `reporting -> calibration`: 11 files.

`docs/operations/package-boundaries.md` already documents a burn-down route
for transitional edges, but no generic broad edge-rewrite item should be added
from this audit.

Impact:

The coupling is real, but a broad import rewrite would mix too many domains.
The better path is to remove edges opportunistically during the new
module-size splits and existing reporting subdomain moves.

Recommended change:

Attach edge burn-down to item 318 for size-driven modules and item 270 for
reporting subdomain moves. Remove transitional allowances only when the code
edge is gone.

Roadmap owner:

- Existing item 270 for reporting subdomain edges.
- New item 318 for edges encountered during large-module splits.
- Completed item 99 remains the ratchet baseline.

### P1 - Compatibility Shims Remain Large But Already Owned

Evidence:

Structure inventory reports 102 compatibility shims:

- 86 flat `src/*.py` wrappers.
- 4 root helper shims.
- 12 root script shims.

Item 206 is `OPEN` and explicitly owns the post-2026-07-18 shim caller scan and
batch removal.

Impact:

The shims keep old commands discoverable and increase audit noise, but deleting
them before the compatibility window would be premature.

Recommended change:

Keep first-party docs and scripts off shim paths now. Execute item 206 on or
after 2026-07-18.

Roadmap owner:

- Existing item 206. Do not create a duplicate.

### P1 - Ignored Runtime Data Is Operationally Large

Evidence:

The `--include-data-sizes` structure inventory found 230,575.10 MiB under
ignored `data`, led by `snapshots`, `tape_backups`, `backtest`,
`wunderground`, `reanalysis`, `metar`, `taker_runs`, and `mm_runs`.

Impact:

This will dominate local scans and can starve daily refresh, snapshot loops,
and backup workflows. It is local operational risk, not Git structure risk.

Recommended change:

Keep runtime state ignored, apply retention and backup policies, and move bulky
backup/snapshot roots outside the repo where practical. Do not track this data
to solve local disk pressure.

Roadmap owner:

- Existing items 176, 171, 172, 146, 247, 286, 288, 289, and related storage
  policy docs. Do not create a duplicate.

### P2 - Large Test Files Should Split With Their Owners

Evidence:

Four test files are over 2,000 lines and several more exceed 1,500 lines. The
largest correspond to the largest production owners: taker bot, daily refresh,
daily learning, pooled replay, and promotion refresh.

Impact:

Large tests make owner splits harder because fixtures, assertions, and scenario
builders are interleaved.

Recommended change:

When item 318 splits production modules, extract reusable fixture builders and
scenario factories in the matching test areas. Avoid standalone test-only churn
unless it unblocks a source split.

Roadmap owner:

- New item 318.

### P2 - Dependency Pins Are Already Guarded

Evidence:

`tests/operations/test_dependency_pins.py` compares `requirements.txt` and
`pyproject.toml` exactly. Item 176 also records dependency pin sync as done.

Impact:

No current roadmap gap.

Recommended change:

Keep the existing test. No new item.

Roadmap owner:

- Existing item 176 and `tests/operations/test_dependency_pins.py`.

### P2 - Tools, Scratch, And Retired Research Scripts Are Already Owned

Evidence:

Item 176 owns stale local generated state, scratch review, retired
`tools/research` scripts, and the research harness inventory.

Impact:

No new roadmap item is needed unless a future audit finds a live retired script
that bypasses the harness.

Recommended change:

Keep item 176 as the cleanup owner.

Roadmap owner:

- Existing item 176.

### P2 - App Views Are Manageable

Evidence:

Largest app files are `app/views/single_market.py` at 702 lines and
`app/views/market_making.py` at 448 lines.

Impact:

These are worth splitting if they become harder to test, but they are not
current structure blockers compared with the source package warnings.

Recommended change:

No new roadmap item. If touched for feature work, separate data loading and
view-model assembly from Streamlit rendering.

Roadmap owner:

- No new item needed.

## Do Not Start With

1. Do not bulk-move the whole repository. The top-level layout is healthy.
2. Do not document `sources -> model` as transitional unless a quick fix proves
   impractical.
3. Do not delete compatibility shims before item 206's post-2026-07-18 checks.
4. Do not move ignored `data` into Git to solve local disk pressure.
5. Do not reorganize all reporting modules in one change; keep item 270 sliced.
6. Do not split tests separately from their production owners unless the test
   split is required to make a production refactor reviewable.

## Verification Commands

For the audit state:

```powershell
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md --run-architecture-ratchet
python -m weather.operations.structure_inventory --report data\backtest\structure_inventory_report.md --include-data-sizes
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
```

For item 317:

```powershell
python -m pytest tests\sources\test_marine_water_contrast.py tests\sources\test_marine_context.py tests\operations\test_import_architecture.py -q
```

For item 318:

```powershell
python -m weather.operations.module_size_audit --out data\backtest\module_size_audit.json --report data\backtest\module_size_audit_report.md
python -m pytest tests\operations\test_import_architecture.py -q
```
