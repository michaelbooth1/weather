# Agent Report — 2026-07-20 (item 206 compatibility-shim removal)

## Outcome

Item 206 is complete. All 103 expired compatibility shims were removed, no
shim was retained, canonical caller paths were refreshed, absence ratchets are
live, and the generated active backlog no longer lists item 206.

## Isolation And Git Identity

- Worktree:
  `C:\Users\micha\Desktop\github\weather-item206-shim-removal-2026-07-20`
- Branch: `item206-shim-removal-2026-07-20`
- Base/current-master commit:
  `6e31b8af94017faffe51b0938205a2e30c966e5d`
- Implementation commit:
  `dd193f3de1d7fbc03cb3d986f42ba5c89a28a728`
- The main worktree's pre-existing edits to `config/locations.json` and
  `config/location_market_events.json` were not touched.
- This report is committed in the single follow-up handoff commit; its exact
  branch-head SHA is supplied in the delegate completion message because a
  commit cannot embed its own object ID.
- No push or merge was performed.

## Fresh Pre-Removal Scan

### Caller gate

Command:

```powershell
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m pytest tests\operations\test_import_architecture.py::test_first_party_surfaces_do_not_call_compatibility_shims -q
```

Result: `1 passed in 2.39s`.

### Structure inventory

The required JSON was written inside the isolated worktree. The inventory was
extended to schema `structure_inventory_v0.2` so the JSON records every shim
path rather than only truncated examples. The safe rerun supplied both output
paths inside the worktree:

```powershell
C:\Users\micha\Desktop\github\weather\venv\Scripts\python.exe -m weather.operations.structure_inventory `
  --out C:\Users\micha\Desktop\github\weather-item206-shim-removal-2026-07-20\shim_inventory.json `
  --report C:\Users\micha\Desktop\github\weather-item206-shim-removal-2026-07-20\shim_inventory_report.md
```

Pre-removal result:

- `tracked=1457`
- `source_py=405`
- `large_modules=93`
- `shims=103`
- 103 JSON paths, 103 unique
- Classes: 85 flat `src/*.py`, one root Streamlit wrapper, three root
  helpers, and 14 direct root scripts

The work-order brief's `tracked=1456` preceded base commit `6e31b8af`, which
added the work-order file; the fresh count of 1457 is therefore expected.

CLI safety note: the first literal `--out` run exposed that the CLI also writes
its default Markdown report under `data/backtest`. It created one new 8.9 KB
report in the isolated worktree. I detected it immediately, verified it was the
only worktree-local `data/` content and shared the scan creation timestamp,
then removed that exact file and its empty directories. No main-worktree or
pre-existing runtime data was altered. Every later run explicitly placed both
outputs outside `data/`; final verification confirmed the isolated worktree
has no `data/` directory.

### Scheduler and local launchers

`Get-ScheduledTask` produced 215 action rows across all local tasks, including
17 `Weather*` tasks. Every action was checked against the exact 103-path JSON
inventory and `-m src.*`; there were zero hits. Weather actions use canonical
`-m weather.*` modules or `scripts/ops/*` paths (apart from the separately
owned quiet-window temp runner, which is not a repository shim).

Eleven top-level desktop shortcuts and the one top-level launcher/URL file were
checked. None targeted the weather repository or a shim path.

### Repository callers

Scans covered `README.md`, `.github` CI configuration, `app/`, `scripts/`,
`tests/`, `tools/`, `docs/operations/`, reusable runbooks, and canonical
`src/weather/` source.

- README references were migration/deprecation prose, not callers; they were
  refreshed for the completed removal.
- CI, operations docs, app code, scripts, and reusable tools had no active shim
  caller.
- Test matches were negative assertions or synthetic inventory/runtime
  fixtures, not invocations.
- Dated roadmap/research matches were retained as historical evidence.
- The broader source scan found one stale operator recommendation in
  `weather.reporting.data_quality.data_layer_audit`: it emitted
  `scripts/register_clob_supervisor.ps1`. It now emits the canonical
  `scripts/ops/register_clob_supervisor.ps1`, with a focused regression
  assertion.

No external dependency requiring retention was found.

## Deleted Batches

| Batch | Deleted | Retained |
| --- | ---: | ---: |
| Flat Python wrappers directly under `src/*.py` | 85 | 0 |
| Root Streamlit wrapper `app.py` | 1 | 0 |
| Root helpers `backfill_all.py`, `scratch.py`, `train_all_markets.ps1` | 3 | 0 |
| Direct scheduled-task/dashboard shims under `scripts/*` | 14 | 0 |
| **Total** | **103** | **0** |

The 103 deleted Git paths exactly matched the 103 unique pre-removal JSON
paths. `src/__init__.py`, `weather/__init__.py`, `sitecustomize.py`, canonical
`src/weather/`, `app/`, `scripts/ops/`, `scripts/launch/`, and `tools/` were not
part of the deletion set.

Post-implementation inventory at commit `dd193f3d` reported
`tracked=1354 source_py=405 shims=0 paths=0`. The eventual report commit adds
this one tracked Markdown file.

## Ratchets And Documentation

- `test_compatibility_shim_surfaces_remain_retired` forbids all four retired
  filesystem classes.
- The caller scan now includes canonical `src/weather/` and command-shaped root
  helper calls, while intentional classifier fixtures remain excluded.
- Structure inventory v0.2 emits the exact shim path list; its repository test
  requires all counts, total, and paths to remain zero.
- The empty-wrapper import-regex case is safe after deletion and cannot match
  arbitrary imports.
- Root/package guidance and README now state that the old surfaces are retired.
- `compatibility-shim-inventory.md` records current count zero, the historical
  103-file registry, and no retentions.
- Item 206 and its ROADMAP row are complete. The generated active backlog is
  `OK`: 318 items, 30 active, 3 OPEN, 27 PARTIAL, 288 COMPLETE, zero lint
  errors; item 206 is omitted from the active list.

## Verification

Every test batch read
`data/logs/memory_commit_guard_status.json` from the main host first. The
pre-scan ran at `commit_percent=44.7`; focused test batches ran at 46.6 and the
final report audit at 46.8, always below the required 70 percent threshold.

| Check | Result |
| --- | --- |
| Required pre-removal caller gate | `1 passed` |
| Full import architecture suite | `21 passed` |
| Structure inventory + schema registry | `13 passed` |
| Data-layer audit + roadmap backlog | `40 passed` |
| Final combined focused pytest batch | `74 passed in 7.84s` |
| `python -m compileall -q app src tests` | PASS |
| `python -m weather.operations.agent_docs_audit` | PASS (`18` agent files, `453` Markdown files) |
| Roadmap backlog regeneration with `--fail-on-lint` | `Roadmap backlog: OK` |
| Post-removal structure inventory | `shims=0 paths=0` |
| `git diff --check` / cached diff check | PASS |

No scheduler registration/action, loop start/stop/restart, release operation,
promotion, network collector, live trade, merge, or push was performed.

## Master-Agent Merge Note

Per the work order, the master should still compare every deleted path with the
actual snapshot/CLOB/observation loop `source_scope_files` at merge time. Some
retired paths match broad whole-tree runtime-identity patterns, while managed
capture scopes are expected to contain only loaded canonical modules. I did not
inspect or alter live loop state. If any deleted path is unexpectedly present
in a live scoped file list, use the required quiet-window adoption procedure.
