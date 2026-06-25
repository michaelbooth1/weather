# 129. Streamlit Single-Market View Extraction [COMPLETE 2026-06-18 - SINGLE-MARKET VIEW SPLIT LIVE]

Goal: finish the Streamlit app split so `app/streamlit_app.py` owns app setup
and routing only, while each page body lives in a dedicated view module.

Source: 2026-06-18 repository hierarchy review. The app package already has
`app/views/overview.py`, `app/views/history.py`, `app/views/operations.py`,
and `app/views/market_making.py`, but `app/streamlit_app.py` still contains the
large single-market dashboard body after routing.

Why this matters: the app directory is now structurally correct, but the
largest page remains embedded in the router. That makes dashboard changes
harder to review, makes page ownership less clear, and keeps app setup
coupled to live market rendering.

## Design

1. Add a dedicated single-market view module, for example
   `app/views/single_market.py`.
2. Move market title, trust banner, model/client caches, source fetches,
   distribution rendering, market price rendering, and page-specific controls
   out of `app/streamlit_app.py`.
3. Keep `app/streamlit_app.py` focused on page config, sidebar selection,
   query-param synchronization, and dispatch.
4. Keep Streamlit cache boundaries stable so the split does not alter refresh
   behavior.
5. Add app architecture tests that prevent large page bodies from drifting back
   into the router.

- [x] Extract the single-market page into `app/views/single_market.py`.
- [x] Keep current query-param behavior and sidebar labels unchanged.
- [x] Preserve cache TTLs and model/snapshot store behavior.
- [x] Add focused tests for routing/import hygiene and the extracted helper
  boundaries.
- [x] Smoke the dashboard with the Streamlit launcher.

Acceptance: `app/streamlit_app.py` is a small router/setup module, all major
page bodies live under `app/views/`, and existing dashboard behavior remains
unchanged.

## Completion

Completed 2026-06-18.

Implementation:

- Added `app/views/single_market.py` and moved the single-market dashboard
  body there.
- Reduced `app/streamlit_app.py` to page config, sidebar selection,
  query-param synchronization, and dispatch.
- Kept the existing sidebar labels and query-param behavior for `overview`,
  `history`, `ops`, `mm`, and registered market ids.
- Preserved live refresh and cache TTL values: `LIVE_REFRESH_SECONDS = 60` in
  the router and `LIVE_CACHE_TTL_SECONDS = 55` in the single-market view.
- Updated the app architecture tests to require a thin router and to require
  the single-market view to own market page dependencies such as
  `SnapshotStore`, `PolymarketClient`, and `TorontoHighTempModel`.

Verification:

- `python -m compileall -q app` passed.
- `python -m pytest tests\app\test_app_architecture.py tests\app\test_app_overview.py tests\operations\test_import_architecture.py -q`
  passed.
- `git ls-files --others --exclude-standard -- app` returned no rows after the
  new view was added to the index.
- `.\scripts\launch\start_weather_dashboard.ps1 -NoBrowser -Port 18501`
  started the dashboard; `Invoke-WebRequest http://localhost:18501/?market=overview`
  returned HTTP 200; the smoke process was stopped after verification.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-18 - SINGLE-MARKET VIEW SPLIT LIVE`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

