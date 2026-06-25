# 313. Python Runtime Audit Regression Gate [COMPLETE 2026-06-25 - STRICT RUNTIME AUDIT GATE LIVE]

Goal: keep high-signal Python audit checks actionable for operator-facing
runtime paths, so undefined names, dashboard tracebacks, and current-window log
errors are either blocked by a focused gate or intentionally baselined with an
owning roadmap item.

Source: 2026-06-24 Python/log audit. `compileall` passed over `app`, `src`,
`tests`, `tools`, and `weather`, but the focused ruff sweep failed with 118
findings: 69 `F821`, 45 `F811`, and 4 `F841`. Some findings are known analyzer
noise around compatibility re-exports or dependency-injected CLI globals, but
the audit found at least two current hazards that escaped completed audit work:
`src/weather/operations/daily_refresh_steps.py` calls `utc_now()` without
importing it in the reanalysis refresh and event-metadata validation steps, and
`data/logs/streamlit_stderr.log` shows a 2026-06-24 single-market dashboard
`UnboundLocalError` caused by a local `import pandas as pd` shadowing the
module-level pandas import before `pd.to_datetime(...)` runs. The sweep also
flagged a lower-risk unresolved `date` annotation in
`src/weather/operations/event_day_manifest.py`.

Why this matters: completed items 119, 122, and 129 prove earlier audit and UI
cleanup passes, but they do not currently stop fresh runtime regressions in the
daily-refresh or dashboard paths. A clean compile pass alone is not enough:
missing imported helpers can sit behind step conditions, and Streamlit page
errors can remain visible only in runtime logs.

Why it is not already covered: item 119 completed the 2026-06-18 repo audit
fixes, item 122 completed serialization/log cleanup, item 129 completed the
single-market view extraction, item 205 split daily-refresh orchestration, and
item 306 completed historical log separation. None is an active owner for a
continuous, focused regression gate that keeps the static audit profile,
daily-refresh step smoke, Streamlit route smoke, and last-24-hour traceback
triage clean after those items closed.

## Design

1. Split the high-signal Python audit into an actionable gate and a documented
   baseline. Compatibility re-export noise and intentional dependency-injected
   CLI globals should be either removed, isolated behind explicit wrappers, or
   listed in a small owned baseline so real `F821` regressions stand out.
2. Add a daily-refresh smoke that imports and exercises the configured
   step-entry surfaces far enough to catch missing helpers such as `utc_now()`
   before a full overnight run reaches them.
3. Add a Streamlit dashboard smoke for the overview and each per-market route,
   using the existing app test approach or a lightweight launcher probe, so
   single-market page tracebacks fail locally instead of only landing in
   `data/logs/streamlit_stderr.log`.
4. Add a current-window log traceback parser for `data/logs`, daily-refresh,
   taker, maker, snapshot, CLOB, and observation-trigger logs that groups new
   signatures and requires each actionable signature to map to an active item or
   an explicit non-actionable disposition.
5. Wire the combined command into the documented audit/maintenance workflow and
   include focused tests for the daily-refresh missing-import path, the pandas
   local-shadowing dashboard regression, and log-signature ownership routing.

- [x] Define and document the focused Python audit gate and its explicit
  analyzer-noise baseline.
- [x] Add daily-refresh step smoke coverage for the reanalysis and
  event-metadata validation entry paths.
- [x] Add Streamlit route smoke coverage that fails on single-market runtime
  tracebacks.
- [x] Add current-window traceback signature grouping and roadmap-owner routing.
- [x] Add regression tests for missing imported helpers, pandas local-shadowing,
  and log-signature ownership.

Acceptance: the focused Python audit command passes without hiding real
undefined-name hazards, the daily-refresh step smoke catches missing runtime
helpers, Streamlit per-market smoke fails on dashboard tracebacks, current-window
log signatures are grouped with active roadmap ownership, and the documented
maintenance command can be run before closing future audit/UI cleanup items.

Related: items 92, 107, 119, 122, 129, 205, 306, 312.

## Completion Notes

Implemented `weather.operations.python_runtime_audit`, a strict regression gate
that combines the focused ruff sweep, an explicit analyzer-noise baseline at
`docs/operations/python-runtime-audit-baseline.json`, daily-refresh
runner/global smoke checks, a fixture-backed Streamlit single-market route
smoke, and current-window log signature ownership routing.

The gate is documented in `docs/operations/PYTHON_RUNTIME_AUDIT_GATE.md` and
passes with:

```powershell
.\venv\Scripts\python.exe -m weather.operations.python_runtime_audit --strict --json-out data\backtest\python_runtime_audit.json
```

Targeted verification also passed:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_python_runtime_audit.py
.\venv\Scripts\python.exe -m pytest -q tests\app\test_single_market_route_smoke.py
.\venv\Scripts\python.exe -m pytest -q tests\operations\test_daily_refresh.py::TestDailyRefresh::test_daily_roll_log_hygiene_archives_old_errors_and_promotes_recurrence
.\venv\Scripts\python.exe -m pytest -q tests\app\test_app_overview.py tests\app\test_app_roadmap.py
.\venv\Scripts\python.exe -m compileall -q app src tests tools weather
```
