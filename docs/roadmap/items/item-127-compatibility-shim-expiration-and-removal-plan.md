# 127. Compatibility Shim Expiration And Removal Plan [COMPLETE 2026-06-18 - EXPIRATION RATCHET LIVE]

Goal: turn compatibility shims from permanent clutter into a dated migration
layer with measurable removal criteria.

Source: 2026-06-18 repository hierarchy review. The repo still has 86 tracked
flat `src/*.py` wrappers plus root and script shims such as `app.py`,
`backfill_all.py`, `scratch.py`, `train_all_markets.ps1`, and root-level
`scripts/*.ps1` launchers. The canonical runtime surface is already
`weather.*`, but the compatibility layer still expands the visible project
surface.

Why this matters: compatibility wrappers are useful while external automation
is migrating, but they become long-term maintenance debt if they do not expire.
They keep old commands discoverable, force tests to preserve deprecated
behavior, and make the repository look larger and more ambiguous than it is.

## Design

1. Extend the compatibility-shim inventory with an explicit `expires_after`
   field or removal milestone for each wrapper group.
2. Separate shims by class: flat Python module wrappers, root helper wrappers,
   Streamlit/root entrypoint wrappers, and root scheduled-task script wrappers.
3. Scan README, active docs, scripts, tests, CI, and first-party tools for
   first-party calls to shimmed paths.
4. Add a warning or deprecation note to wrappers that are safe to retire after
   the migration window.
5. Remove wrappers in batches after one clean migration window with no
   first-party callers and no known scheduled-task dependency.

- [x] Add expiration metadata to `docs/roadmap/compatibility-shim-inventory.md`.
- [x] Define the migration window start date and minimum duration.
- [x] Add a first-party caller scan for `python -m src.*`, root helper shims,
  and root `scripts/*.ps1` shims.
- [x] Remove or archive shim classes whose removal criteria are met.
- [x] Keep one documented fallback path for operators during the retirement
  window.

Acceptance: every compatibility shim has an owner, caller policy, expiration
condition, and removal status. First-party code and current runbooks use
canonical `weather.*`, `app/`, `tools/`, and `scripts/ops` or
`scripts/launch` paths. Expired shims are removed rather than carried
indefinitely.

## Completion

Completed 2026-06-18.

The compatibility inventory now defines a dated migration window:

- Start date: 2026-06-18.
- Minimum duration: 30 days.
- Default expiration date: 2026-07-18.
- Current status: retain shims as external/local operator fallback only until
  expiration.

The inventory separates shim classes and removal status for:

- 86 flat Python wrappers under `src/*.py`.
- Root Streamlit wrapper `app.py`.
- Root helper wrappers `backfill_all.py`, `scratch.py`, and
  `train_all_markets.ps1`.
- 9 root scheduled-task/dashboard script shims under `scripts/*`.

No shim class was removed in this item because the expiration date has not yet
passed. Removal becomes eligible after 2026-07-18 when the first-party caller
scan is still clean and no known external automation depends on that shim
class.

Active first-party surfaces were moved to canonical paths:

- README dashboard command now uses `app/streamlit_app.py`.
- README scheduled-task registration now uses `scripts/ops/*`.
- README dashboard launcher now uses `scripts/launch/start_weather_dashboard.cmd`.
- Active operations docs now use `weather.*`, `scripts/ops/*`, and
  `scripts/launch/*` paths.
- The dashboard launcher starts Streamlit from `app/streamlit_app.py`.
- The overview Streamlit test loads `app/streamlit_app.py` directly.

Added `test_first_party_surfaces_do_not_call_compatibility_shims` to
`tests/operations/test_import_architecture.py`. It scans README, CI, app,
tests, tools, scripts, and active operations docs for `python -m src.*`,
direct `streamlit run app.py`/`AppTest.from_file("app.py")`, and root
scheduled-task/dashboard script shim paths.

Verification:

- `rg 'AppTest\.from_file\("app\.py"|streamlit run app\.py|python -m src\.|-m src\.|pythonw\.exe -m src\.|\\scripts\\register_|scripts/register_|\\scripts\\start_weather_dashboard|scripts/start_weather_dashboard' README.md .github app tests tools scripts docs\operations --glob '!**/__pycache__/**'`
  returned no matches.
- `python -m pytest tests\operations\test_import_architecture.py tests\app\test_app_overview.py -q`
  passed.
