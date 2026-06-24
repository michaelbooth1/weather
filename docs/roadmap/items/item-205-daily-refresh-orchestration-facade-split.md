# 205. Daily Refresh Orchestration Facade Split [COMPLETE 2026-06-21 - DAILY REFRESH FACADE BELOW THRESHOLD]

Goal: split `weather.operations.daily_refresh` into focused owner modules while
keeping the public CLI and scheduled task command stable.

Source: item 173 closed the post-agent large-module split for its target files,
but the module-size audit still reports one module above the 2,000-line warning
threshold: `src/weather/operations/daily_refresh.py`, currently about 2,230
lines. The ownership map names the next split as step runner registry,
status/report rendering, preflight gates, and CLI.

Why this matters: many recently closed items now wire new behavior through
daily refresh: active-variant execution, disk preflight, data retention,
root-cause reporting, stale-lock handling, and progress ledger updates. Leaving
all orchestration, locks, reports, CLI parsing, and step-specific adapters in
one file makes each follow-up harder to review and raises merge-conflict risk.

## Design

1. Keep `weather.operations.daily_refresh` as the compatibility facade and CLI
   entrypoint.
2. Extract lock/preflight repair helpers, step registry/runners, status payload
   assembly, report rendering, and CLI parsing into owner modules.
3. Preserve existing schema versions and output paths.
4. Add import-architecture guards so extracted modules do not import back from
   the facade.
5. Update the module-size audit ownership map and require the warning count to
   return to zero unless a new module is explicitly accepted.

- [x] Extract daily-refresh lock, stale-lock repair, and disk preflight helpers.
- [x] Extract the step registry and runner adapters.
- [x] Extract status payload and Markdown report rendering.
- [x] Extract CLI parsing while preserving `python -m weather.operations.daily_refresh`.
- [x] Add focused tests and import-boundary ratchets for each owner module.
- [x] Regenerate the module-size audit and ownership map.

Acceptance: `weather.operations.daily_refresh` is a thin facade below the module
size warning threshold, the scheduled command still works, daily-refresh tests
continue to pass, and `module_size_audit` has no unowned warning for this file.

Completion note 2026-06-21: `weather.operations.daily_refresh` now delegates
lock, stale-state repair, and disk-preflight helpers to
`weather.operations.daily_refresh_locks`; step order, runner registry, step
adapters, and status summary helpers to
`weather.operations.daily_refresh_steps`; Markdown status rendering to
`weather.operations.daily_refresh_report`; and CLI parser/command handling to
`weather.operations.daily_refresh_cli`. The facade remains the stable public
module and `python -m weather.operations.daily_refresh` entrypoint. The CLI
module receives facade dependencies by injection, and the import-architecture
ratchet now includes `daily_refresh_*` modules so extracted owner modules cannot
import back from the facade.

The regenerated module-size audit reports `daily_refresh.py` at 375 lines with
status `OK`. The audit still has one unrelated warning for
`src/weather/calibration/pooled_candidate_replay.py` at 2,016 lines; item 205's
target file has no warning.

Verification:
- `python -m pytest tests\operations\test_daily_refresh.py -q` passed with
  `37 passed`.
- `python -m pytest tests\operations\test_import_architecture.py::test_extracted_modules_do_not_import_orchestration_facades -q`
  passed with `1 passed`.
- `python -m pytest tests\operations\test_module_size_audit.py -q` passed with
  `2 passed`.
- `python -m weather.operations.daily_refresh run --dry-run ...` exited `0`
  and wrote the temp status/report.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-21 - DAILY REFRESH FACADE BELOW THRESHOLD`.
- The file contains 6 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the item-specific `Verification:` command(s) or artifact checks listed above.

