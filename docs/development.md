# Development and Verification

Status: canonical development guide. The root [README](../README.md) owns setup
and the full operator command catalog; this document owns change workflow and
verification expectations.

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
```

`pytest.ini` collects only `tests/` and exposes `src/`. The editable install is
still the primary package contract. CI uses Python 3.11 on Ubuntu, so production
modules must remain cross-platform even though scheduled operations are Windows
specific.

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
