# Streamlit App Instructions

The canonical entry point is `app/streamlit_app.py`. It intentionally exposes
only two pages: the default read-only Control Room and Roadmap. Keep it a thin
router; page bodies belong in `app/views/`, reusable table rendering belongs
in `app/table_utils.py`, and domain logic belongs in its owning `weather`
package.

- Preserve `?market=control` and `?roadmap` compatibility. Retired overview,
  city, history, operations, and market-making routes fall back to Control Room;
  do not restore their page modules without an explicit product decision.
- Avoid import-time network calls in the router. Views should use existing
  cached/domain helpers rather than reimplementing model or market behavior.
- Keep UI tables Arrow-safe and user-facing text UTF-8 clean.
- Add or update Streamlit `AppTest` coverage for visible routing/behavior.

Focused checks:

```powershell
.\venv\Scripts\python.exe -m pytest tests\app -q
.\venv\Scripts\python.exe -m pytest tests\app\test_app_architecture.py -q
```

See [the architecture guide](../docs/architecture.md) for the UI boundary.

## Update this file when

Update when router responsibilities, view ownership, query parameters, or the
app test strategy changes.
