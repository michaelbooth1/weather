# Python Runtime Audit Gate

Roadmap item 313 owns the focused regression gate for operator-facing Python
runtime failures that can pass `compileall` but still break daily refresh,
Streamlit routes, or current-window logs.

Run the gate before closing future Python audit, daily-refresh, Streamlit UI, or
runtime-log cleanup items:

```powershell
.\venv\Scripts\python.exe -m weather.operations.python_runtime_audit --strict
```

The gate combines:

- focused ruff checks for undefined names, import-loader failures, redefinitions,
  unused locals, and the high-signal runtime rules from the 2026-06-24 audit;
- an explicit baseline in
  `docs/operations/python-runtime-audit-baseline.json` for compatibility
  re-export noise and `daily_refresh_cli.py` dependency-injected globals
  validated by `daily_refresh_cli.configure()`;
- daily-refresh entrypoint smoke checks for registered step runners and required
  runtime globals such as `utc_now`;
- a fixture-backed Streamlit single-market route smoke that renders snapshot
  history through the real app router without network calls;
- current-window log signature grouping and owner routing for Streamlit,
  daily-refresh, snapshot, CLOB, observation-trigger, taker, and maker logs.

Use `--json-out` to write the audit artifact somewhere other than
`data/backtest/python_runtime_audit.json`. Use `--log-sources` for a temporary
or fixture log set, formatted as comma-separated `name=path` entries.
