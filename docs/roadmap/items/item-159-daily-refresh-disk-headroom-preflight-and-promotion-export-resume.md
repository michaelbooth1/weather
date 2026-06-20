# 159. Daily Refresh Disk-Headroom Preflight And Promotion Export Resume [PARTIAL 2026-06-20 - PREFLIGHT AND RESUME MODE LIVE, FULL RESUME PENDING]

Goal: make daily refresh fail fast on artifact disk pressure and resume cleanly
after disk cleanup, especially before promotion refresh variant exports.

Source: `data/backtest/daily_refresh_status.json` for 2026-06-19. The
`promotion_refresh` step failed after a long run with:
`insufficient disk headroom for variant export
data\backtest\item82_miami_fallback_shadow_variants.csv`, with only
`485441536` free bytes when the guard required at least `1069048320`. Later disk
state recovered and current free space is healthy, but the daily refresh status
still records the failed promotion step.

Why this matters: disk-full failures interrupt the most expensive step and can
leave stale promotion artifacts beside fresh daily-learning artifacts. Disk
headroom must be a hard preflight, not a late exception during export.

## Design

1. Run disk headroom checks before each artifact-heavy daily refresh step:
   promotion refresh, candidate shadow export, disagreement casebook, CLOB
   audits, and backup/restore.
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
shortfall `0`. A real resume attempt was started with nonessential downstream
steps skipped, but it exceeded the 4-minute tool timeout; the process was
stopped and its stale `daily_refresh.lock` was removed. Full resume-to-success
evidence remains pending.

2026-06-20 ledger update: `daily_progress_ledger_v0.1` records disk preflight
status, free bytes, required bytes, and headroom bytes. The latest generated row
correctly classifies the historical June 19 failed promotion refresh as
`ops_disk_preflight_status=BLOCK`, with `485441536` free bytes,
`1069048320` required bytes, and `-583606784` headroom bytes.

Acceptance: when disk is low, daily refresh exits before expensive candidate
export work starts and reports a single actionable disk blocker. After cleanup,
promotion refresh can be resumed or rerun to completion, and progress tracking
records both the failed preflight and the recovered state.
