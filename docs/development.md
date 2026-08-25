# Development and Verification

Status: canonical development guide. The root [README](../README.md) owns setup
and the full operator command catalog; this document owns change workflow and
verification expectations. The [Git workflow SOP](git-workflow.md) owns branch,
worktree, staging, commit, pull-request, integration, and cleanup procedure.

## Before editing

- Inspect `git status --short` and preserve unrelated changes.
- Read the nearest `AGENTS.md` and identify the owning package.
- Confirm whether the task touches local evidence, generated config, tracked
  artifacts, a scheduled task, release state, or a network service.
- Prefer a canonical `python -m weather...` entry point over a flat wrapper.

## Baseline commands

From the repository root on Windows:

```powershell
.\venv\Scripts\python.exe -m pytest -q
.\venv\Scripts\python.exe -m compileall -q app src tests
.\venv\Scripts\python.exe -m weather.operations.agent_docs_audit
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check
```

`pytest.ini` collects only `tests/` and exposes `src/`. The editable install is
still the primary package contract. Pull requests and pushes to `master` or any
`codex/**` topic branch run two Python 3.11 CI-only jobs. Ubuntu compiles the
repository, validates the canonical documentation and generated roadmap, and
runs an explicit cross-platform owner inventory plus a bounded set of static
operations ratchets, including a self-check of this workflow contract. Windows
repeats those checks and runs the complete test inventory, including executable
Windows PowerShell contracts. Both checkouts retain complete Git history so
real-repository ancestry checks are meaningful. They intentionally leave metered
model payloads as Git LFS pointers; artifact verification derives the strict
object SHA-256 and byte size from each canonical pointer instead of weakening
identity checks or spending LFS bandwidth. Both jobs install the test and live
optional dependency sets so missing SDK coverage cannot turn an integration
branch green merely because the optional client is absent. External workflow
actions are pinned to immutable commits, checkout credentials are discarded,
and the manual candidate builder follows the same full-history and isolated-
Python test contract; its former nightly schedule remains disabled.

These CI-only jobs are early backstops before review or scheduled integration.
They create no production qualification receipt and do not replace the
production host's exact-tip qualification, bounded overnight suite, workload
admission, or guarded merge evidence.

Every CI pytest step and the repository-owned bounded suite start with
`WEATHER_INTEGRATION_TEST_OFFLINE=1`. The tracked interpreter bootstrap removes
conservatively classified secret-bearing environment variables before test
collection and at Python child edges, blocks sockets, and permits subprocesses
only through sequence-form invocations of the exact Python, Git, or PowerShell
executables frozen for that run. Shell mode, `executable=` overrides,
bootstrap-disabling Python flags, arbitrary native executables, and common
PowerShell network or credential commands fail before launch. These controls
are defense in depth around the exact reviewed test inventory; they are not an
OS sandbox for hostile native extensions or dynamically constructed PowerShell.

On the 16 GB production capture host, the commands above are not authority to
run a direct full suite or parallel verification. Focused tests run serially
only inside 00:30–09:00; the full suite uses
`scripts/ops/bounded_worktree_test_suite.ps1` with its 25-file chunks and
workload lease. The user-layer Codex hook rejects direct unbounded pytest at
every hour and rejects pytest/compileall outside that window.

## Focused verification matrix

| Change | Minimum focused verification |
| --- | --- |
| Streamlit router/view | `pytest tests/app -q` |
| Source adapter/history | matching `tests/sources` tests; no live network in unit tests |
| Model/distribution/features | matching `tests/model`; C and F paths; mass/floor/cutoff checks |
| Training/calibration | matching `tests/calibration`; train/serve schema and artifact compatibility |
| Snapshot/forecast collection | matching `tests/collection`; atomicity, cadence, and replay persistence |
| Market, maker, or taker logic | matching `tests/market`; keep execution non-live |
| Daily/nightly/supervisor behavior | matching `tests/operations`; use status/dry-run paths |
| Reports, gates, roadmap | matching `tests/reporting`; verify fail-closed evidence behavior |
| Package/import/path changes | `tests/operations/test_import_architecture.py` |
| Canonical docs/agent files | `python -m weather.operations.agent_docs_audit` |
| Roadmap item/index or generated backlog | roadmap lint plus `roadmap_backlog --fail-on-lint --check` after regeneration |

Run the full suite for cross-owner changes, release/evidence contracts, shared
utilities, or before handing off a broad refactor.

## Stateful command boundaries

The following categories require inspection before execution because they can
write local or tracked state, use the network, change scheduled tasks, or affect
serving:

- source backfills and location-event refresh;
- Windows task registration and loop start/restart/stop commands;
- artifact registry, size, externalization, and promotion-preflight generators;
- cleanup, retention, migration, and archive commands;
- candidate creation, release promotion/rollback, and any live exchange mode.

Use `--help`, read the relevant [operations runbook](operations/README.md), and
prefer status, audit, dry-run, read-only, shadow, or paper modes. Never assume an
argument-free registration example is valid; the script parameter block is the
executable source of truth.

## Model-change evidence

A model improvement claim needs more than unit tests. Preserve training/live
feature parity, run captured-input or frozen-tape replay as appropriate, compare
against market prices with proper scoring, inspect protected slices and data
quality, and keep the candidate inactive until promotion and release gates pass.
Exact gates evolve and belong to the release/runbook code, not copied prose.

## Definition of done

- The intended behavior is implemented through the correct owner.
- Focused tests pass; broader checks match the change risk.
- New behavior is deterministic and network-free under unit tests.
- Schemas, fixtures, manifests, and documentation are updated together where
  their source contracts changed.
- No secrets, machine-specific paths, ignored runtime files, or unrelated user
  changes entered the diff.
- Documentation links and knowledge contracts pass the agent-doc audit.

## Update this file when

Update when baseline checks, test ownership, CI platforms, stateful command
boundaries, or the repository-wide definition of done changes.
