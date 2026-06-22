# 176. Local Generated State And Tooling Cleanup Sweep [PARTIAL 2026-06-22 - SAFE CACHE SWEEP APPLIED, LF NORMALIZATION DEFERRED]

Goal: remove or quarantine stale local generated state, retired research
stubs, and scratch outputs after active agents finish.

Source: the 2026-06-20 full repository cleanup audit. Ignored directories such
as `venv`, caches, `__pycache__`, `src/weather_market.egg-info`, and `scratch`
are present locally. `tools/research` also contains a mix of supported,
fixture-only, and retired scripts guarded by the research harness.

Why this matters: ignored local state is useful during development, but stale
generated files make audits noisy and can hide whether behavior is reproducible
from tracked source.

## Design

1. Wait until active agent work is complete before sweeping local generated
   state.
2. Produce a dry-run cleanup report that separates safe cache deletion from
   durable scratch/research outputs.
3. Promote durable scratch reports or scripts into `docs/research`,
   `tools/research`, or tests before deleting local copies.
4. Remove retired research stubs only after confirming the harness no longer
   needs them as explicit failure sentinels.
5. Normalize line endings in a controlled docs/code hygiene PR after dirty
   files settle.

- [x] Add a local cleanup dry-run command that reports ignored generated files
  and sizes without deleting anything.
- [ ] Delete safe caches after active work finishes: `__pycache__`,
  `.pytest_cache`, `.ruff_cache`, and egg-info.
- [x] Review `scratch/` for outputs worth promoting to tracked docs or tests.
- [x] Review retired `tools/research` scripts and either remove them or keep
  them as documented harness fixtures.
- [x] Ensure dependency pins are managed from one source or add a sync check
  for `pyproject.toml` and `requirements.txt`.
- [ ] Run a controlled CRLF-to-LF normalization pass consistent with
  `.gitattributes`.

Acceptance: local generated clutter can be cleaned reproducibly, durable
scratch findings are promoted before deletion, and repo audits no longer have
to manually filter stale local state.

## 2026-06-21 implementation update

Added `weather.operations.local_generated_state_cleanup`, schema
`local_generated_state_cleanup_v0.1`, as a dry-run-only local audit. The command
writes:

- `data/backtest/local_generated_state_cleanup.json`
- `data/backtest/local_generated_state_cleanup_report.md`

The report separates safe cache deletion candidates from durable scratch review
items, validates the `tools/research` harness inventory, checks exact dependency
pin sync between `pyproject.toml` and `requirements.txt`, and scans tracked
docs/code text files for CRLF drift under `.gitattributes`.

Current checkout findings:

- Safe cache candidates: 32 roots, 985 files, 15.2 MiB.
- Scratch review: 21 files, 234.8 KiB; durable findings summarized in
  `docs/research/local-generated-state-cleanup-review-2026-06-21.md`.
- Research harness: validation passes; 1 supported script, 8 fixture-only
  scripts, and 17 retired scripts/wrappers are inventoried.
- Dependency pins: PASS; `pyproject.toml` and `requirements.txt` match.
- Line endings: 146 tracked docs/code files still contain CRLF and need a
  controlled normalization pass.

The research harness inventory now includes `input_variable_significance.py` as
fixture-only historical audit code and `ten_minute_performance_audit.py` as a
retired compatibility wrapper for `weather.reporting.ten_minute_model_performance`.

The destructive sweep remains deferred by design: active tests and ongoing
agent work recreate caches, and the worktree still contains broad dirty files.
When active work settles, rerun:

```powershell
python -m weather.operations.local_generated_state_cleanup --out data\backtest\local_generated_state_cleanup.json --report data\backtest\local_generated_state_cleanup_report.md
```

Then delete only the listed safe cache roots and run a separate LF
normalization pass.

Verification:

- `python -m pytest tests\operations\test_local_generated_state_cleanup.py tests\operations\test_schema_registry.py -q`
- `python tools\research\research_harness.py --validate --smoke --include-fixtures`
- `python -m weather.operations.local_generated_state_cleanup --out data\backtest\local_generated_state_cleanup.json --report data\backtest\local_generated_state_cleanup_report.md`

## 2026-06-22 cleanup readiness refresh

I refreshed the dry-run report:

- `data/backtest/local_generated_state_cleanup.json`
- `data/backtest/local_generated_state_cleanup_report.md`

The current dry-run status remains `ACTION_REQUIRED`, but the actionable
ignored-cache portion is bounded and reproducible: 32 safe cache roots, 1,061
files, and 17.8 MiB, all with cleanup policy
`delete_after_active_work_finishes`. Those roots are limited to `.pytest_cache`,
`.ruff_cache`, `__pycache__` directories, and `src/weather_market.egg-info`
inside the workspace. I applied that safe cache sweep after the item
verification and backlog refresh, using the audited manifest paths only.

The durable scratch and tracked-file cleanup portions remain intentionally
separate. Scratch review now reports 29 files and 9.2 MiB, including newly
created 2026-06-22 audit folders that need manual classification before
deletion. The CRLF scan reports 150 tracked docs/code files inconsistent with
`.gitattributes`; I did not normalize them in this pass because the worktree
contains broad active roadmap/source changes, and a repo-wide line-ending
rewrite would mix unrelated tracked-file churn into this work.

Item 176 therefore remains `PARTIAL`. The reproducible dry-run and safe-cache
deletion path are live, research/tooling checks pass, and dependency pins are
still in sync. The remaining unblock is a dedicated controlled LF normalization
pass after the current dirty worktree settles, followed by a final dry-run that
shows no CRLF drift.

Verification:

- `python -m pytest tests\operations\test_local_generated_state_cleanup.py tests\operations\test_schema_registry.py -q`
  passed with `5 passed`.
- `python tools\research\research_harness.py --validate --smoke --include-fixtures`
  passed with `research inventory OK`.
