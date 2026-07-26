# Agent Report — 2026-07-20b (`data/` cleanup) — COMPLETED 2026-07-21

Supersedes the 2026-07-20 attempt, which correctly stopped at the memory
preflight (3.44 GiB free, below the 3.5 GiB floor) and performed no action.
Executed by the operations master agent on 2026-07-21 with VS Code retired and
7.2-7.8 GiB free.

## Outcome

**Reclaimed 1.162 GB** by hard-deleting 49 orphaned atomic-write temp files.
Tier B quarantine: **nothing** — the only sizeable candidate proved to be live
infrastructure and was kept. The reclaim is small, as the work order predicted.

The far more valuable result is a **root cause found while inventorying**: the
recent 2.5x jump in daily capture volume is not new data, it is uncompressed
data caused by the blocked settlement chain. See "Incidental finding" below;
it is worth ~15 GB/day and ~35 GB recoverable now.

## Disk and health

| Measurement | Free on `C:` |
| --- | ---: |
| Before | 222.858 GB |
| After | 224.021 GB |
| Reclaimed | **1.162 GB** |

Capture health, before and after, all three loops fresh with zero consecutive
errors (snapshot < 600 s, clob/observation < 180 s). Free RAM 7.19 GB before,
7.48 GB after. The nightly data mirror was running throughout; it was unaffected.

Scan method: a single streaming `os.scandir` walk (DirEntry stat is populated by
the directory enumeration on Windows, so no extra syscall per file), run at
below-normal priority, accumulating only counters and a bounded candidate list.
3,699,811 files scanned, 0 errors. No recursive `Get-ChildItem` was used.

## Top-level `data/` breakdown (466 GB total)

| Subtree | Size | Files |
| --- | ---: | ---: |
| `snapshots` | 345.6 GB | 3,527,668 |
| `taker_runs` | 47.8 GB | 4,733 |
| `backtest` | 43.6 GB | 3,622 |
| `noaa_ghcnh` | 6.2 GB | 4,187 |
| `mm_runs` | 5.4 GB | 3,664 |
| `wunderground` | 5.4 GB | 74,445 |
| others (14 subtrees) | ~11 GB | ~81,000 |

## Tier A — deleted (49 paths, 1,248,020,474 bytes)

Orphaned atomic-write temporaries under `data/wunderground/<station>/`, named
`last_good_sources.json.<pid>.<nanotime>.tmp`, across 11 stations (cyyz, kaus,
kbkf, kdal, khou, klax, klga, kmia, kord, ksea, ksfo).

Every deletion required four proofs, checked per file:

1. under `data/wunderground/`, where the work order explicitly exempts temp
   artifacts from the raw-source keep rule;
2. modified before 2026-07-14, i.e. outside both the 7-day and streak-window
   protections (observed range 2026-06-18 to 2026-07-13);
3. the writing PID (38 distinct PIDs) is dead — no live process could be
   mid-write; and
4. an intact canonical `last_good_sources.json` (0.8-35.3 MB) sits beside it, so
   the temp is redundant rather than the only copy.

Manifest: `C:\tmp\item40_artifacts\tierA-deleted-2026-07-21.csv`.

## Tier B — quarantined: none

`data/archive/closed_market_days/v0.1` (2.46 GB, 3,237 files, untouched since
2026-06-22) looked like the classic stale-archive candidate and was **kept after
verification**. It is live, referenced infrastructure: `closed_market_day_archive.py`,
`daily_refresh_trading_steps.py`, `daily_refresh_reporting_steps.py`,
`event_day_archive_coverage.py`, and `storage_classes.py` all reference it, it has
a formal contract (`docs/operations/closed-market-day-parquet-archive-contract.md`),
roadmap Item 243, and it is the `--archive-root` used by point-in-time evaluation.
An initial cross-check appeared to show its dates were absent from `snapshots`;
that was a false negative from comparing Hive partition names against event-slug
directory names. Re-checked correctly, the dates are present. **Do not quarantine
this tree.**

## Candidates deliberately not acted on

- **31 `.tmp` files under `data/snapshots/`** (orphaned `clob_loop_status.json`
  atomic-write temps, negligible bytes). `data/snapshots/**` is off limits by the
  work order, so they were left despite matching the Tier A pattern.
- **2 wunderground `.tmp` files** dated 2026-07-14 or later — inside the streak
  window protection.
- **554 zero-byte files** (sampled: `backtest`, `eccc`). They reclaim nothing and
  a zero-byte file can be a deliberate sentinel; risk without reward.
- **273 empty directories** (sampled: all under `archive`). Reclaim nothing.
- **Byte-identical duplicate detection was not attempted.** Doing it properly
  needs content hashing across 3.7M files, and the largest tree (`snapshots`) is
  hard-protected anyway. Absence here means not evaluated, not proven safe.
- **Rotated logs older than 30 days: none exist** (0 found under `data/logs`).

## Incidental finding (high value) — uncompressed CLOB tapes

While comparing per-day sizes, the cause of the recent growth step change became
clear. Daily totals across 12 markets: Jul 15 9.3, Jul 16 13.0, Jul 17 9.0,
Jul 18 9.6, Jul 19 26.0, Jul 20 25.3 GB. The jump is uniform across all 12
markets while per-day **file counts fell slightly** — so it is not retry or
duplicate capture, it is the same artifacts getting bigger.

The artifact is `order_books_long`. For Toronto: Jul 18 stored `order_books_long.csv.gz`
at 61 MB with no raw file; Jul 19 stored `order_books_long.csv` at 1,327.3 MB with
no gzip. Jul 20 is 1,277.2 MB raw and Jul 21 884.6 MB raw. Jul 16 has both a
46 MB gzip and a 341.8 MB raw, i.e. a partially completed tiering.

`weather.operations.clob_order_book_tiering` is the owner: it compresses
`order_books_long.csv` to `.csv.gz` and then deletes the verified source. It is a
**step of the daily refresh chain** (registered in `daily_refresh_registry.py`,
budgeted in `daily_refresh_resources.py`). The chain has been deferring on
`resource_admission_blocked` since roughly Jul 18, so the step stopped running.

**The disk problem and the memory-admission problem are the same problem.**

A read-only `plan` run (`--settled-before 2026-07-21`) reports: 24 candidate
files totalling 37.4 GB ready to compress, 20 folders where the gzip already
exists but the raw source is still present (pure redundancy), and 12 correctly
excluded as active/unsettled (today). Compressing the candidates at the observed
~21x ratio implies roughly **33-35 GB reclaimable now**, plus the redundant
sources, and roughly **15 GB/day of avoidable ongoing growth**.

Recommended: let tonight's Phase-2 admission change unblock the chain so the step
runs as designed, then verify. If the chain still defers, run
`python -m weather.operations.clob_order_book_tiering apply --delete-source
--settled-before <today>` manually. This needs an explicit operator decision
because it deletes source files after verifying their gzip.

## Safety

Main checkout used as required. No tracked file was modified by the cleanup
itself; this report is intentionally untracked and must not be committed. No
scheduler, capture-loop, release, promotion, git, or live-trading action was
taken. The pre-existing dirty `config/location_market_events.json` and
`config/locations.json` were not touched. Nothing under `data/snapshots`,
`data/mm_runs`, `data/taker_runs`, `data/settlements`, `data/forecast_payload_cas`,
or `data/archive` was deleted, moved, or modified.
