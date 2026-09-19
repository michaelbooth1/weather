# Audit dimension: Architecture and code health

Auditor: architecture subagent. Date: 2026-09-18. Host: live 16 GB production host (read-only audit).
No project file was modified. No Python, pytest, script, or scheduled-task command was run.

## 1. Scope covered

- `docs/architecture.md`, `docs/operations/package-boundaries.md`, `docs/operations/module-ownership-map.md`,
  `docs/operations/cold-archive-locations.md`, relevant sections of `DELEGATION_CONTRACT.md`,
  `ESTABLISHED_FINDINGS.md`, nested `AGENTS.md` files (src/weather, operations, config, tools).
- `src/weather/` top-level modules read in full: `io.py`, `paths.py`, `time.py`, `units.py`,
  `schema_registry.py`, `schema_registry_types.py`, `cold_archive_locations.py`, `runtime_identity.py`,
  `variant_registry.py`; partial reads of `schema_registry_data.py`, `release_serving.py`,
  `collection/snapshot_store.py`, `operations/supervisor.py`, `operations/module_size_audit.py`,
  `backtesting/replay.py`.
- `tests/operations/test_import_architecture.py` (full), `test_module_size_audit.py`, `test_dependency_pins.py`.
- `app/` (all 6 files listed, 3 read), `tools/` (listing, 4 files read), `weather/__init__.py`,
  `src/__init__.py`, `sitecustomize.py`, `pyproject.toml`, `requirements.txt`, `pytest.ini`,
  `.github/workflows/ci.yml`.
- Import structure and duplication measured with Grep (count mode) over `src/weather` only.

## 2. Method

- Line counts: ripgrep count of `^` per directory (no `wc`, no tree walk outside `src/`, `tests/`, `tools/`).
- File sizes: non-recursive `ls -S -l` of single package directories.
- Every structural claim below was traced through at least one concrete instance (file:line given).
- Git history: `git log -- <path>` and `git show --stat` only.
- Process note: two early shell calls chained several non-recursive `ls` invocations / used `cd && git log`
  in one call. They were whitelisted commands on specific directories, but strictly the brief said one
  command per call; later calls complied.

## 3. Size and shape (verified numbers)

| Area | Lines | Files | Note |
| --- | ---: | ---: | --- |
| `src/weather` total | 371,663 | 502 | avg 740 lines/file |
| `reporting` | 120,690 | 172 | 14 sub-packages, root restricted to `formatting.py` by test |
| `operations` | 85,950 | 120 | one flat directory |
| `market` | 64,804 | 73 | one flat directory |
| `model` | 14,908 | 22 | the forecasting core = 4.0% of source |
| `reporting/research` | 18,880 | 31 | one-off research analyses inside the package |
| live-trading session machinery (20 files, see F2) | 20,079 | 20 | larger than `model`; no live trading is authorized |
| `tests` | 183,052 | 413 | |
| `tools` | 16,781 | 46 | 19 of the 46 are "retired" tombstone stubs |
| registered artifact schemas | 674 `SchemaSpec` + 19 exclusions | 2 data shards (~4,300 lines) | version strings only, no field schema |
| CLI entry points (`def main(`) | 246 modules | | zero `[project.scripts]` |

Files over 3,000 lines (exact counts):

| File | Lines |
| --- | ---: |
| `reporting/validation/point_in_time_evaluation.py` | 5,494 |
| `calibration/pooled_candidate_replay.py` | 4,045 |
| `reporting/scorecards/live_variant_settlement_scorecard.py` | 3,689 |
| `operations/nightly_retrain.py` | 3,216 |
| `operations/international_live_wrapper_sealer.py` | 3,189 |
| `market/mm_paper.py` | 3,112 |
| `collection/snapshot_store.py` | 3,111 |
| (near) `schema_registry_data.py` | 2,829 |

## 4. Findings

### F1 (high, known_open) The central schema registry sits in every capture loop's code identity, so most feature merges restart production capture

Mechanism, traced end to end:

1. Capture loops fingerprint only the repo source files present in `sys.modules`
   (`runtime_identity.py:132-164`, `:189-227`; used at `collection/snapshot_store.py:269`,
   `collection/snapshot_tracker.py:873`, `market/market_microstructure.py:1228/1535/1841`,
   `operations/observation_trigger.py:717/1102/1307`, `operations/execution_tape_supervisor.py:805`).
2. When the fingerprint differs from disk, the loop exits and the supervisor relaunches it
   (`operations/supervisor.py:416-441`; the comment records this as the root cause of the
   2026-06-24/25 snapshot outages, capture ratio 0.51, 8.5 h gap). A 900 s debounce was added
   (`supervisor.py:86-91`).
3. `weather.schema_registry` statically imports both data shards (`schema_registry.py:14-23`,
   `schema_registry_data.py:5`). 196 modules import `weather.schema_registry`, and since 2026-09-09
   `weather.io` reaches it as well (`io.py:18` -> `cold_archive_locations.py:17`).
4. Registration is mandatory: `schema_version()` raises `KeyError` for an unregistered name
   (`schema_registry.py:40-45`).
5. Therefore any branch that adds a schema changes a file loaded by all four capture closures.
   `git log` shows about 60 commits touching the two data shards between 2026-08-08 and 2026-09-09,
   almost all for unrelated subsystems (live wrapper sealer, cold archive, documentation transactions).

The project records this itself: `docs/operations/DELEGATION_CONTRACT.md:186-193` ("Any change to any of
them rolls every capture loop at merge ... the roll cannot be avoided") and
`ESTABLISHED_FINDINGS.md:2261`. It built `roll_verdict.ps1` and `quiet_window_merge.ps1` around the
coupling and confines such merges to 01:00-04:00 (`OPERATING_REFERENCE.md:26`).

What is new in this audit: "cannot be avoided" is a design choice, not a constraint. The registry stores
only `name, version, owner, status, description` (`schema_registry_types.py:11-19`); it validates no
fields. `schema_registry.scan_schema_literals` (`schema_registry.py:79-102`) already discovers version
literals by scanning source, so the same audit can run in CI without the registry being an import-time
dependency of capture. The cost side is large: nearly every feature branch becomes roll-sensitive and
must queue for a three-hour nightly window on a host that currently has 210 unmerged branches.
(The causal link to the branch backlog is inferred, not measured.)

Recommendation: decouple. Options in rising effort: (a) let each producer own its version constant and
make the registry a CI-time generated inventory; (b) shard the registry per owner package so a capture
closure loads only `collection`/`market` shards; (c) at minimum exclude additive-only registry shards
from the loaded-scope fingerprint and compare only the version strings the loop actually resolved.

### F2 (high, new as a judgement) The codebase is out of proportion to the product, and the excess is where agent effort goes

Verified numbers are in section 3. The forecasting core (`model`) is 14,908 lines, 4.0% of source.
`reporting` + `operations` are 206,640 lines (55.6%). There are 674 registered durable artifact schemas
and 246 modules with their own `main()`. Twenty files (20,079 lines, listed below) implement live
International trading sessions, credential import, SDK overlay sealing and wrapper sealing, added mostly
2026-08-13..09-04, while live trading is not authorized and the project's own conclusion is that the
model does not beat the market. That block alone is larger than the model package, and its commits
account for a visible share of the schema-registry churn in F1.

Live-machinery files counted: `market/mm_live_candidate_cli.py` 1,850; `mm_live_lifecycle_probe.py` 1,581;
`mm_live_pilot_cli.py` 1,457; `mm_official_adapter.py` 1,455; `live_sdk_portability.py` 1,655;
`mm_live_bootstrap.py` 989; `mm_credential_import_cli.py` 959; `portable_live_candidate_preflight.py` 575;
`live_sdk_overlay.py` 502; `mm_geographic_eligibility.py` 440; `mm_credentials.py` 417; `mm_user_stream.py` 283;
`mm_official_transport.py` 252; `market_making_live_pilot.py` 102; `operations/international_live_wrapper_sealer.py` 3,189;
`international_live_session_runner.py` 1,757; `international_live_session_launcher_sealer.py` 1,540;
`live_path_security.py` 874; `international_live_time_window.py` 132; `international_live_lineage.py` 70.

Context-window cost for agents: `point_in_time_evaluation.py` is 229 KB, roughly 55-60k tokens, and
needs three maximum-size reads to see once. Twenty-three modules sit on the >2,000-line allowance list
(`module-ownership-map.md:9-25`). The eight canonical operations docs an agent is told to read total
4,499 lines, `ESTABLISHED_FINDINGS.md` alone 2,753. A careful agent spends a large share of its context
on orientation before touching the task; a less careful one edits a 4,000-line file it has read a third of.

Judgement: not proportionate. One shipped forecast improvement against ~372k lines suggests the platform
has been growing gates, receipts and reports around a model that is not yet worth gating. This is an
inferred assessment; the numbers are verified.

Recommendation: declare a freeze on new subsystems; move the live-session block and `reporting/research`
to a parked branch or a separate non-loaded package until a live decision exists; set a line budget per
package and require deletions to fund additions.

### F3 (medium, known_open) Seven files exceed 3,000 lines and the size governance has no ceiling

`module_size_audit.py:18` sets only a 2,000-line warning. `tests/operations/test_module_size_audit.py:61-77`
passes as long as each warning module appears on a named allowance list in `module-ownership-map.md:9-25`.
Nothing bounds growth of a module once it is on the list. Evidence that this matters: the ownership map
records `international_live_wrapper_sealer` as "WARN at 2,770 lines in the 2026-08-27 ... audit"
(`module-ownership-map.md:62`); it is 3,189 lines today. Every row in the map has a written "next split"
that has not been executed; several date from 2026-07-03.

What would break them up (from their own ownership notes, which are sound):
`point_in_time_evaluation` -> materialization / fit receipts / streaming evaluator;
`pooled_candidate_replay` -> cache+sentinel owner, result aggregation;
`live_variant_settlement_scorecard` -> move parity normalization to `validation.captured_input_replay_parity`;
`nightly_retrain` -> SLA/report rendering and CLI handlers; `mm_paper` -> reward diagnostics and promotion gates;
`snapshot_store` -> payload persistence, explanation sidecar, backfill methods.

Recommendation: add a per-module ratchet (recorded max lines that may only decrease) so the allowance
cannot silently grow, and schedule the two largest splits.

### F4 (medium, new) Shared helpers exist but are bypassed; the same five utilities are re-implemented 50-150 times

Counts from `src/weather` (regexes given in section 7 so they can be re-run):

| Helper | Shared home | Private definitions elsewhere |
| --- | --- | --- |
| JSON file reader (`_read_json`, `load_json`, ...) | `weather.io.read_json` | 116 definitions in 108 files |
| JSONL reader | `weather.io.read_jsonl` | 20 definitions in 19 files |
| datetime parser | `weather.time.parse_datetime` | 66 definitions in 65 files |
| float coercion | `weather.units.to_float` | 65 definitions in 65 files |
| `utc_now`/`utc_iso`/`now_utc`/... | `weather.time` | 147 definitions in 140 files |
| sha256 of file/bytes | `weather.io.sha256_file` | about 50 definitions in 43 files |
| fsync'd durable write | none in `weather.io` | 80 `os.fsync` call sites in 52 files |

`weather.time` is imported by 7 modules; `weather.io` by 94. Traced instances: nine sibling gates under
`reporting/source_gates/` each carry a private `_read_json`, and they disagree on malformed input
(`marine_contrast_gate.py:56-60` raises, `nbm_probabilistic_tmax_settlement_scoring.py:57-64` returns `{}`,
`settlement_source_audit.py:78-82` returns `None`). `operations/cleanup_preflight.py:25`,
`closed_day_projection_tiering.py:88`, `closed_market_day_archive.py:616`, `clob_order_book_tiering.py:58`
are byte-identical `utc_iso()` bodies.

Why it matters beyond tidiness: cross-cutting behaviour cannot be added in one place. `weather.io`'s atomic
writers have no `fsync` (whole file read: none), so durability after power loss depends on which module
wrote the artifact, and 52 modules grew their own durable writer. `write_json_atomic` (`io.py:353-377`)
also leaves its temp file behind if the final `replace` raises, unlike `write_text_atomic` (`io.py:475-492`).
F5 is the most consequential instance of the same problem.

Recommendation: add durable variants to `weather.io`, then a ratchet test (same style as
`test_temperature_rounding_uses_canonical_helper`, `test_import_architecture.py:1080-1090`) that freezes
the current count of private readers/parsers and only lets it fall.

### F5 (medium, known_open as a class; the instance is new) Replay readers are not cold-archive aware: an archived market-day reads as empty

`docs/operations/cold-archive-locations.md:3-5` sets the rule that archiving "must not ... turn an
unavailable tape into an empty research population", and `:147-152` says consumers with their own
existence checks need their own integration. Only 12 files reference the archive API
(`resolve_local_path`, `require_local_inputs`, `registered_sources`, `archived_inputs`).

Traced instance: `backtesting/replay.py:50-63` defines a private `_read_jsonl` that returns `[]` when
`Path(path).exists()` is false, with no marker lookup. `load_replay_records` (`replay.py:66-79`) uses it
for `replay_inputs.jsonl` and `replay_inputs_reconstructed.jsonl`. Callers:
`calibration/pooled_candidate_replay.py:699, 816, 895` and `backtesting/replay_backtest.py:360`.
Folder discovery at `replay.py:648` globs physical `*/snapshots.jsonl`. These files are classed as
canonical snapshot-folder evidence (`operations/storage_classes.py:176-190`) and have the three-part
`snapshots/<event>/<file>` shape that `cold_archive_locations.load_location` accepts (`:162-164`).

Consequence (inferred): once an original `replay_inputs.jsonl` is reclaimed, candidate replay and replay
backtests silently score a smaller population instead of raising `ArchivedInputRequired`. The reclaim
procedure has a manual "protected release/replay inputs" review (`cold-archive-locations.md:210-214`),
which is the only control. I did not verify whether any replay input has been reclaimed yet.

Recommendation: route `replay.py` through `weather.io.read_jsonl` and `registered_sources` before any
reclaim that includes the `replay_inputs` family; add a test that an archived marker makes
`load_replay_records` raise.

### F6 (medium, new) The import ratchet is permissive and blind to top-level conduit modules

`tests/operations/test_import_architecture.py:663-704` permits 26 "allowed" + 11 "transitional" directed
edges = 37 of the 56 possible edges between the eight owner packages (66%). Ten package pairs are
bidirectional; two of those cycles are in the *stable allowed* set, not the transitional one:
`collection <-> operations` and `market <-> operations` (`:671-682`). `operations` and `reporting` may
each import all seven other packages. None of the 11 transitional edges listed on 2026-06-16
(`package-boundaries.md:59-79`) has been removed except `market -> model` (`:113-115`).

Blind spot, traced: `source_package()` returns `None` for any file directly under `src/weather/`
(`test_import_architecture.py:777-782`), and `imported_weather_package()` ignores any target that is not
a package root or a listed shared module (`:785-794`). So top-level modules are checked neither as
importers nor as imports. Two of them carry owner-package imports:

- `weather/variant_registry.py:11` re-exports `weather.reporting.candidate_lifecycle.variant_registry`.
  It is listed as a shared utility (`test_import_architecture.py:660`), and its docstring says it exists
  to keep "collection and calibration callers from depending on the reporting package". Chain:
  `collection/snapshot_tracker.py:17` -> `collection/collection_health.py:27` -> `weather/variant_registry.py:11`
  -> `reporting/candidate_lifecycle/variant_registry.py:14`. That is a `collection -> reporting` runtime
  dependency, an edge in neither list, inside the production capture closure.
- `weather/residual_distribution_release.py:25-58` imports `calibration` (4 modules), `model`,
  `operations.release_manifest`, and `reporting.validation.point_in_time_evaluation` (5,494 lines).
  It is reached lazily from `weather/release_serving.py:711-715`, which `collection/snapshot_store.py:236`
  calls when the `RESIDUAL_SHADOW_RELEASE_DIR` env var is set. When enabled, the capture process imports
  calibration and reporting code, and (by F1) edits to those files would restart capture.

The ten unmonitored top-level modules total about 380 KB: `captured_input_hash`, `execution_host`,
`experiment_contract`, `forecast_payload_contracts`, `model_stage_retirement`, `point_in_time_contract`,
`release_artifacts`, `release_contract`, `release_serving`, `residual_distribution_release`. Eight of the
ten import only shared modules (verified by grep of their `weather.` imports).

Also: `sources -> market` is 13 imports, all of `market.market_registry`, and `model -> market` is the
same kind of dependency. `market_registry` is a shared module living inside a 65k-line owner package.

Recommendation: give top-level modules a pseudo-package in the ratchet so their edges are recorded; move
the variant-registry implementation to the shared module and let reporting import it (invert the facade);
move `market_registry` to a shared location; burn down transitional edges by count, with a recorded maximum.

### F7 (medium, new) No lint, no type check, no dependency lock

`pyproject.toml` is 31 lines and contains no `[tool.ruff]`, `[tool.mypy]`, or any tool table.
`ci.yml:41-51` runs `compileall`, two doc audits and `pytest` only. `docs/development.md` mentions no
linter or type checker (only roadmap lint). A `.ruff_cache/` directory dated 2026-06-24 and `# noqa: BLE001`
markers (`io.py:111`, `app/views/control_room.py:121`) show ruff was used ad hoc but never configured, so
the `noqa` codes refer to rules nothing selects. About 43% of 11,097 functions carry return annotations
(4,736 in 218 of 461 files) but no tool reads them. There are 308 broad `except Exception`/bare `except`
sites in 130 files, and 926 `print(` calls in 244 files against `logging` use in 5 files (the project's
observability is status JSON and JSONL sidecars, which is a legitimate choice, but it means there is no
log level, no uniform timestamping and no central sink).

Dependencies: nine direct pins in `requirements.txt` and `pyproject.toml`, kept in sync by
`tests/operations/test_dependency_pins.py:20-25` (good). There is no transitive lock or hash file at the
repo root (listing checked: no `*.lock`, no `constraints*.txt`). The pins are recent majors
(`numpy==2.4.6`, `pandas==3.0.3`, `scikit-learn==1.8.0`, `scipy==1.17.1`). The sklearn pin is justified in
`requirements.txt:2-3` by pickled HGB artifacts, but `joblib`, `threadpoolctl`, `cftime`, and Streamlit's
tree float. Given that off-host backup is a closed owner decision, a rebuilt venv after host loss would
not be the venv that produced the artifacts. `netCDF4` is imported in one function
(`sources/reanalysis_synoptic.py:571`) and `matplotlib` in one module (`backtesting/snapshot_analytics.py:9-13`);
both are core dependencies of the production capture venv. CI runs on `ubuntu-latest` / Python 3.11 while
production is Windows with many Windows-only operations modules.

Recommendation: add a minimal ruff config (F, E9, BLE, B) with a frozen baseline; export
`pip freeze` from the production venv into a tracked constraints file; move netCDF4/matplotlib/streamlit
to extras.

### F8 (low, new) Research one-offs and tombstones live in the production package and tools

`src/weather/reporting/research/` holds 30 modules (18,880 lines). Only two are imported by non-research
code (`reporting/market/market_residual_repair_program.py:14`,
`reporting/candidate_lifecycle/active_variant_shadow_refresh.py:422`). No file under
`src/weather/operations` or `scripts/` references the package by name (grep: no matches); the other
references are 33 owner strings in the schema registry. Nine are per-roadmap-item dispositions dated June
(`item134`, `135`, `136`, `138`, `147`, `160`, `186` x2, `item48`). They are reachable only through their
own CLI and tests. I did not check for dynamic `importlib` use.

`tools/research/` has 19 files whose whole body is `RESEARCH_STATUS = "retired"` plus a message and
`return 2` (e.g. `fix_app.py`, `train_all2.py`), tracked by a manifest in `research_harness.py:13`. The 15
measurement scripts that produced the 2026-08 findings (`*_09_6xa`..`*_09_78a`, about 600 KB) have no tests
(grep of `tests/` finds only `test_input_variable_significance.py` and `test_research_harness.py`).
`src/__init__.py` is an empty "compatibility namespace" for `python -m src.<module>` commands that the
ratchet forbids (`test_import_architecture.py:1013-1033`).

Recommendation: delete tombstones (git history is the tombstone); move closed-item research modules out
of the importable package or into an `archive/` tree excluded from the schema registry.

### F9 (low, known_open) A generated 1.7 MB runtime file is tracked under `config/`, so the production tree is always dirty

`config/location_market_events.json` (1,786,130 bytes) and `config/locations.json` are rewritten by the
fleet (`config/AGENTS.md:7-9`); both were modified at session start. `git log` shows 11 commits since
2026-08-17 titled "ops: preserve fleet-generated drift (pre-merge, automated)". Every merge on production
is preceded by an automated commit of generated state, and any clean-tree gate has to special-case it.
`docs/architecture.md:85-86` documents the file as generated. It belongs under ignored `data/` with a
tracked seed, or behind a smudge-free export step.

### F10 (low, known_open) Four overlapping import-resolution mechanisms; `sitecustomize.py` patches the interpreter

`weather` can resolve through (1) the editable install (`pyproject.toml:29-30`), (2) `sitecustomize.py:17-22`
inserting `src/` at `sys.path[0]` whenever the repo root is on the path, (3) the repo-root shim package
`weather/__init__.py:7-11` extending `__path__`, and (4) `pytest.ini:5` `pythonpath = src`. With 200
worktrees, which copy wins depends on cwd and launch style; the owner's notes already record "worktree
tests production code; print the module `__file__` first".

`sitecustomize.py` also replaces `subprocess.Popen` with a subclass that forces `CREATE_NO_WINDOW`
(`:44-63`), overwrites the private `platform._syscmd_ver` (`:34-42`), and sets `LOKY_MAX_CPU_COUNT`
(`:24-32`) for every Python process started from the repo root, including pytest, Streamlit, tools and
agent one-liners. The intent is documented and sensible for `pythonw.exe` workers; the risk is that tests
and diagnostics never exercise an unpatched interpreter, and the patch applies silently to any process
that happens to start in this directory. Opt out is `WEATHER_ALLOW_CONSOLE_CHILDREN=1`.

Recommendation: keep one mechanism (editable install) plus the worker-only patch applied explicitly from
the worker entry points; delete the root shim package.

## 5. Strengths

1. The lowest layers are clean. `src/weather/model` and `src/weather/sources` contain zero imports of
   `reporting`, `operations`, `calibration`, `collection` or `backtesting` (grep verified), and
   `test_import_architecture.py:1128-1136` enforces the model/calibration runtime boundary.
2. Architecture is tested, not just documented: `tests/operations/test_import_architecture.py` (1,136 lines)
   ratchets package edges, forbids `sys.path` mutation, legacy shims, stray `round_half_up` definitions,
   legacy `_c` temperature reads in the model runtime, and keeps `reporting/` sub-packaged with a
   root restricted to `formatting.py` (`:847-853`).
3. `app/` is genuinely thin and read-only: 6 files, a two-page router (`app/streamlit_app.py`), all
   decision logic in `weather.reporting.market.operator_control_room`, a fail-closed `try/except` around
   evidence loading (`app/views/control_room.py:119-123`), no mutation controls.
4. `weather/io.py` contains careful bounded-memory readers (`read_csv_tail_rows_with_diagnostics`,
   `read_jsonl_tail_with_diagnostics`, `iter_csv_rows`, `read_pretty_json_top_level_values`) with
   concurrent-modification detection (`io.py:945-956`), written in response to real incidents.
5. Global mutable state is rare: two `global` statements in 502 files. Direct dependency pins are exact
   and a test keeps `requirements.txt` and `pyproject.toml` identical (`test_dependency_pins.py:20-25`).
   Large-module ownership is written down per module with a concrete next split
   (`docs/operations/module-ownership-map.md`).

## 6. Not covered

- `scripts/ops` (73 PowerShell files) structure; left to the operations auditor.
- Whether any snapshot input has actually been reclaimed (F5 consequence), and the live contents of the
  capture closures in `data/snapshots/*_status.json` (no `data/` access in this brief).
- A full dead-module sweep: only `reporting/research` and `tools/` were checked for inbound references.
  Dynamic imports (`importlib`, subprocess module strings) were not searched.
- Supply-chain review of the `live` extra (`polymarket-client==0.6.0`); noted for the security auditor.
- True import cycles at module level (needs an import graph tool; not run on this host).
- Type-hint quality beyond a return-annotation count.
- `venv/` contents (forbidden), so the claim "no transitive lock" is limited to the repo root listing.

## 7. Reproduction patterns

All run with ripgrep over `src/weather`, `glob *.py`, count mode:

- JSON readers: `^\s*def\s+_?(read_json|load_json|_load_json|read_json_file|_read_json_object|load_json_file|_json_load)\w*\s*\(` -> 119 in 109 files (3 in `io.py`).
- JSONL readers: `^\s*def\s+_?(read_jsonl|load_jsonl|iter_jsonl|_iter_jsonl|read_jsonl_rows)\w*\s*\(` -> 22 in 20 files (2 in `io.py`).
- datetime parsers: `^\s*def\s+_?(parse_time|parse_dt|parse_datetime|parse_utc|parse_iso|parse_timestamp|parse_ts|as_utc|to_utc|parse_iso_utc|parse_utc_datetime|coerce_datetime)\w*\s*\(` -> 67 in 66 files.
- float coercion: `^\s*def\s+_?(safe_float|to_float|as_float|float_or_none|_float|coerce_float|optional_float)\s*\(` -> 66 in 66 files.
- utc-now: `^\s*def\s+_?(utc_now|now_utc|utcnow|utc_now_iso|utc_iso|now_iso)\s*\(` -> 149 in 142 files (2 in `time.py`).
- sha256: `^\s*def\s+_?(sha256|sha256_file|file_sha256|...)\w*\s*\(` -> 54 in 44 files.
- `os\.fsync\(` -> 80 in 52 files; none in `io.py`.
- `^\s*from\s+weather\.time\s+import|^\s*import\s+weather\.time` -> 9 in 7 files.
- `^\s*from\s+weather\.io\s+import|^\s*import\s+weather\.io` -> 96 in 94 files.
- `^\s*def\s+main\s*\(` -> 246 files. `^\s*print\(` -> 926 in 244 files. `logging` -> 5 files.

## 8. Open questions for the owner

1. Is mandatory import-time schema registration worth a fleet restart per feature merge (F1)?
2. Should the 20k-line live-session block stay in the loaded package while live trading is unauthorized?
3. Before the next reclaim batch: has anyone enumerated which snapshot-folder readers are archive-unaware (F5)?
