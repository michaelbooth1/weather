# Workstation handoff 2026-09-110v — efficiency fixes from the 2026-09-27 audit

Written 2026-09-27 by the production agent from the [efficiency audit](audits/efficiency-audit-2026-09-27.md). Base:
`origin/master` after the 2026-09-27/28 landing. One branch per part, in this order; state roll classification per file.
Fixtures only; no production data, credentials or venue calls; repo-wide audits in every focused run. Push and draft PRs
are authorized; report `docs/roadmap/agent-report-2026-09-110v-<part>.md`, verdict first.

## Part 1 — execution-tape write storm (`codex/exec-tape-write-throttle-20260927`, priority, target the 09-28/29 window)

Production measured ~3.7 MB/s (≈ 314 GB/day) from the execution-tape worker for ~0.5 MB/day of tape per market.
`execution_tape_store.heartbeat()` (~1270) persists the ~25 KB root status with an atomic write on every websocket frame
(`execution_tape_capture.py` ~410), and `append()` (~496) does `flush()+os.fsync()` per row. Persist status only on a state
change or at most every 10 s; group fsync to at most once per second per file (the owner decides the durability trade-off;
default to once per second and document "≤ 1 s of rows at risk on a crash"). Keep every status field and the tape bytes
identical. Tests: status cadence, fsync grouping, crash-recovery replay of the last second, identical tape bytes.

## Part 2 — Stage-A incremental (`codex/stage-a-incremental-20260927`, roll-free)

- Hourly and ten-minute model performance: cache scored rows per settled folder keyed by (path, size, mtime, scorer schema
  version) and reuse for both aggregations.
- `replay_status_backfill`: return early when status exists and inputs are unchanged, before parsing evidence; limit to the
  recent target-date window; count lines with a byte scan.
- `market_day_labels_finalize`: finalize only folders lacking a label or within N days; load the daily summary once; reconcile
  only unreconciled labels.
- Prove identical outputs on fixtures (old full path vs new incremental path) and report expected minutes saved.

## Part 3 — CLOB writes (`codex/clob-write-on-change-20260927`, roll-sensitive, after 2026-10-13)

Write CLOB token rows only when a token's fields change (hash per token; one row per token at day open); cache Gamma events
with a ~10 minute TTL; enrichment appends instead of rewriting whole files. Prospective only; readers unchanged.

## Part 4 — snapshot capture reads (`codex/snapshot-incremental-reads-20260927`, roll-sensitive, after 2026-10-13)

Tail reads for last-snapshot time; a small hash sidecar for forecast-archive and first-seen checks; append rather than rewrite
derived files; evaluate one child per cycle for all due markets (keep the memory cap). Report reads/CPU per cycle before/after.

## Part 5 — thin ensure entry (`codex/thin-ensure-entry-20260927`, roll-free new module)

A lightweight `--ensure` entry that imports only the supervisor/status code and lazily imports loop code on start/restart;
registrar changes as roll-free `.ps1` with exact re-registration commands.

## Part 6 — profiling harness (`codex/stage-a-profile-20260927`, roll-free)

Optional per-step pyinstrument and tracemalloc capture for the daily refresh behind a flag, writing a small JSON report of
wall time and peak private bytes per step, so production can profile one Stage-A run.

Later (design first, after the exam): gzip-streamed raw book tape, compact JSON separators at a UTC day boundary,
de-embedding `snapshots.jsonl`.
