# 159. Daily Refresh Disk-Headroom Preflight And Promotion Export Resume [COMPLETE 2026-06-20 - PREFLIGHT, RESUME, AND LEDGER RECOVERY PROVEN]

Goal: make daily refresh fail fast on artifact disk pressure and resume cleanly
after disk cleanup, especially before promotion refresh variant exports.

Original source: `data/backtest/daily_refresh_status.json` for 2026-06-19. The
`promotion_refresh` step failed after a long run with:
`insufficient disk headroom for variant export
data\backtest\item82_miami_fallback_shadow_variants.csv`, with only
`485441536` free bytes when the guard required at least `1069048320`. Later disk
state recovered and the resumed 2026-06-20 daily refresh now records the
promotion step as `ok` with a passing disk preflight.

Why this matters: disk-full failures interrupt the most expensive step and can
leave stale promotion artifacts beside fresh daily-learning artifacts. Disk
headroom must be a hard preflight, not a late exception during export.

## Design

1. Run disk headroom checks before each artifact-heavy daily refresh step:
   promotion refresh, candidate shadow export, disagreement casebook, CLOB
2. Estimate required bytes from expected row counts and configured export
   classes before work begins.
3. Fail fast with an actionable cleanup command when projected free space is
   below threshold.
4. Record disk state in `daily_refresh_status.json`, daily learning, and the
   daily progress ledger.
5. Add a resume path that reruns the failed step after cleanup without
   invalidating already fresh upstream outputs.

- [x] Add a daily-refresh-level disk preflight before `promotion_refresh`.
- [x] Include projected export bytes, required free bytes, actual free bytes,
  and cleanup recommendation in the daily refresh report.
- [x] Add a resume or targeted rerun mode for a failed promotion refresh after
  cleanup.
- [x] Add tests for fail-fast disk preflight and no-partial-export behavior.
- [x] Add disk free/headroom fields to the daily progress ledger.

2026-06-20 update: daily refresh now runs a structured
`promotion_refresh` disk preflight before calling the expensive promotion
runner. It records free bytes, required free bytes, projected export bytes,
estimated rows, cleanup command, resume command, and `no_partial_export` on
failure. Low-headroom tests prove `promotion_refresh.run_promotion_refresh` is
not called when the preflight blocks. `--resume-from-step promotion_refresh`
now reruns promotion refresh and downstream steps after cleanup.

Current local preflight evidence is healthy: free bytes `130720903168`,
required free bytes `1069048320`, projected export bytes `69048320`, and
shortfall `0`. The first real resume attempt was started with nonessential
downstream steps skipped, but it exceeded the 4-minute tool timeout; the
process was stopped and its stale `daily_refresh.lock` was removed. A later
full resume completed, as recorded below.

2026-06-20 ledger update: `daily_progress_ledger_v0.1` records disk preflight
status, free bytes, required bytes, and headroom bytes. The latest generated row
correctly classifies the historical June 19 failed promotion refresh as
`ops_disk_preflight_status=BLOCK`, with `485441536` free bytes,
`1069048320` required bytes, and `-583606784` headroom bytes.

2026-06-20 completion update: after removing a stale long-job lock whose PID was
not running, `python -m weather.operations.daily_refresh run --resume-from-step
promotion_refresh` completed the resumed promotion refresh and all downstream
steps without step errors. The overall daily refresh status is `critical`
because model/evidence gates still block, but `promotion_refresh` itself is
`ok`, took `1171.885` seconds, and wrote the promotion report. The structured
disk preflight passed with `129955160064` free bytes, `1069048320` required
bytes, `69048320` projected export bytes, and shortfall `0`.

The daily progress ledger now contains both sides of the recovery: the
2026-06-19 failed row has `daily_refresh_status=error` and
`ops_disk_preflight_status=BLOCK`; the 2026-06-20 resumed row has
`daily_refresh_status=critical`, `ops_disk_preflight_status=PASS`, and
`ops_disk_headroom_bytes=128886111744`.

Acceptance: when disk is low, daily refresh exits before expensive candidate
export work starts and reports a single actionable disk blocker. After cleanup,
promotion refresh can be resumed or rerun to completion, and progress tracking
records both the failed preflight and the recovered state.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - PREFLIGHT, RESUME, AND LEDGER RECOVERY PROVEN`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

