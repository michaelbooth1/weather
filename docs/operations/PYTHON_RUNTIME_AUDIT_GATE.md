# Python Runtime Audit Gate

- **Owns:** how to run `weather.operations.python_runtime_audit` and what it
  combines; the baseline file `python-runtime-audit-baseline.json`.
- **Read when:** closing a Python audit, daily-refresh, Streamlit UI or
  runtime-log cleanup change, or editing the baseline.
- **Do not use for:** the full test matrix ([development.md](../development.md))
  or host load rules ([HOST_LOAD_POLICY.md](HOST_LOAD_POLICY.md) — this gate runs
  ruff, Streamlit smokes and log reads, so it is not a protected-window command
  on the capture host).
- **Verify with:** `build_parser`/constants at the top of
  `src/weather/operations/python_runtime_audit.py`; status in
  [item 313](../roadmap/items/item-313-python-runtime-audit-regression-gate.md).

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
- deterministic fixture-backed Streamlit smokes for the current Control Room
  and Roadmap routes through the real app router without network calls;
- current-window log signature grouping and owner routing for Streamlit,
  daily-refresh, snapshot, CLOB, observation-trigger, taker, and maker logs.

Use `--json-out` to write the audit artifact somewhere other than
`data/backtest/python_runtime_audit.json`. Use `--log-sources` for a temporary
or fixture log set, formatted as comma-separated `name=path` entries.

## Update this file when

Update when the gate's flags, check families, baseline path/schema, default
output, or covered Streamlit routes and log owners change.
