# 92. Streamlit App Import Hygiene And UTF-8 Cleanup [COMPLETE 2026-06-16 - APP HYGIENE GUARD LIVE]

Goal: make the Streamlit app a clean package consumer with readable UTF-8 UI
text and testable data-loading boundaries.

Source: 2026-06-16 architecture review. The app still mutates `sys.path`, imports
top-level compatibility wrappers in several views, and contains mojibake in UI
strings and tests. The market-making view also reads repo data files directly
from app code.

Why this is missing: the Streamlit split moved views into `app/`, but some of
the pre-package import and file-access patterns stayed in place. That keeps the
UI coupled to compatibility shims and makes text regressions look normal
because tests assert the mojibake output.

- [x] Replace Streamlit app and view imports with canonical `weather.*` package
  imports.
- [x] Remove `sys.path.insert` from app startup.
- [x] Normalize app files and app tests to UTF-8 and replace mojibake with the
  intended symbols or plain ASCII text.
- [x] Move dashboard data-loading and file-reading helpers into small
  service-style functions outside the Streamlit view layer where practical.
- [x] Update Streamlit tests to assert meaningful text and behavior rather than
  corrupted strings.
- [x] Add a lightweight app architecture test covering import hygiene and UTF-8
  decoding for app files.

Acceptance: the app runs through canonical package imports, UI text is readable
UTF-8, app tests no longer lock in mojibake, and view code is mostly presentation
over small data/service helpers.

## Design

Import hygiene:

- Keep the app as a package consumer. App files should import `weather.*` and
  `app.views.*`; they should not mutate `sys.path` or import top-level
  compatibility wrappers from `src/`.
- Add an app-specific architecture test for `sys.path` mutation, legacy wrapper
  imports, and mojibake/UTF-8 regressions. This complements the broader
  operations architecture guard.

UTF-8 cleanup:

- Verify app files and app tests decode as UTF-8.
- Reject common mojibake fragments (`Â`, `â`, `ð`, replacement characters) in
  app files and app tests.
- Keep legitimate readable symbols where they are intentional UI signals, such
  as degree signs, em dashes, and status icons.

Dashboard data boundary:

- Add a small service module outside the Streamlit view layer for
  market-making dashboard file access:
  `weather.reporting.market_making_dashboard`.
- Move JSON, CSV, JSONL, run-folder listing, and latest-run loading helpers out
  of `app.views.market_making`.
- Keep view-specific table shaping in `app.views.market_making`, because those
  helpers are presentation transforms and already have focused tests.

Verification strategy:

- Run the app tests and the new app architecture test.
- Run the broader architecture guard.
- Run the full suite before marking complete.

## Completion

Completed 2026-06-16.

- Added `weather.reporting.market_making_dashboard` for market-making dashboard
  JSON, CSV, JSONL, run-folder, and latest-run data loading.
- Updated `app.views.market_making` to import dashboard data helpers from the
  service module while keeping presentation/table transforms in the view.
- Added `tests/app/test_app_architecture.py` to reject app/test `sys.path`
  mutation, top-level compatibility-wrapper imports, and common mojibake
  fragments while decoding app files as UTF-8.
- Added service-level coverage for market-making dashboard artifact readers and
  run-folder discovery.
- Verified current app files and app tests use canonical package imports and
  readable UTF-8 UI/test text.

Verification:

- `.\venv\Scripts\python.exe -m pytest tests\app tests\operations\test_import_architecture.py -q` (18 passed)
- `.\venv\Scripts\python.exe -m pytest tests\operations\test_path_policy.py tests\app -q` (12 passed)
- `.\venv\Scripts\python.exe -m pytest` (800 passed)

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-16 - APP HYGIENE GUARD LIVE`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

