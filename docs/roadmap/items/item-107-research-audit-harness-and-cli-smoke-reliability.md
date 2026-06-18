# 107. Research Audit Harness And CLI Smoke Reliability [COMPLETE 2026-06-17 - RESEARCH HARNESS LIVE]

Goal: make model-audit scripts reliable enough that they can catch model
regressions instead of adding their own stale assumptions.

Source: 2026-06-16 local Python audit. The production package compiles, imports
with the installed package, and passes tests, but several ad-hoc research
scripts have stale or copy-pasted assumptions. Examples include an undefined
`dist` in `tools/research/chicago_audit.py`, stale Celsius field assumptions in
Chicago helpers, a stray `audit_chicago` fragment in `tools/research/nyc_audit.py`,
and live scripts that are not covered by the normal pytest suite.

Why this matters: these scripts are often the fastest way to inspect a live
model surprise. If they are stale, audits can misdiagnose the model or miss a
real serving regression.

## Design

1. Classify every file under `tools/research` as supported, fixture-only, or
   retired. Retired scripts should say so at startup or be removed after their
   findings are migrated.
2. Convert supported audit scripts to use native-unit accessors, current market
   registry fields, and the canonical `weather.*` package imports.
3. Add network-free smoke tests for supported scripts: `--help`, fixture-backed
   dry run, or import plus main-guard validation.
4. Add a live-script checklist to the audit docs so new same-day investigations
   use the maintained harness.
5. Keep root shims and README instructions aligned with editable-install
   operation, and add an install-parity smoke in CI or local verification docs.

- [x] Inventory `tools/research/*.py` and mark each script supported,
  fixture-only, or retired.
- [x] Fix supported scripts that use stale unit-specific fields or undefined
  variables.
- [x] Add network-free smoke tests for the supported audit scripts.
- [x] Move durable findings from one-off scripts into reporting modules or
  roadmap items.
- [x] Add an install-parity smoke check for dashboard and backfill entrypoints.

Acceptance: supported research scripts can be run from the documented
environment without undefined names or stale unit assumptions, and retired
scripts no longer look like current model diagnostics.

## Completion Notes

Completed 2026-06-17. Added `tools/research/research_harness.py` with a
manifest covering every `tools/research/*.py` file. The harness classifies each
script as `supported`, `fixture-only`, or `retired`, validates inventory drift,
and runs network-free smoke checks. The explicitly broken live city probes
`chicago_audit.py` and `nyc_audit.py` are now retired stubs with `--help`
instead of stale diagnostics.

Added `docs/operations/RESEARCH_AUDIT_HARNESS.md` with the live-investigation
checklist and maintained package-report entrypoints. Added tests for exact
inventory coverage, supported/fixture smoke checks, retired city stubs, and
install-parity imports for dashboard/backfill entrypoints.

Verification:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_research_harness.py tests\operations\test_import_architecture.py
.\venv\Scripts\python.exe tools\research\research_harness.py --validate --smoke --include-fixtures
```

Result: 17 passed; harness validation and smoke checks passed.
