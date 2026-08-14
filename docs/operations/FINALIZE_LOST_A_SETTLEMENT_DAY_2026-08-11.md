# One transient file error cost a whole settlement day — 2026-08-11

**Status: RECOVERED and FIXED.** 2026-08-10 is settled 12/12 `complete`; the defect that lost it
is merged (`bcb49506`, ROLL-FREE). Written by the production agent, 2026-08-11 late evening.

## What happened

The 08-11 chain (`WeatherDailySettlementPromotionRefresh`, started 09:43:57) restored the
settlement data for target `2026-08-10` successfully and then threw it away.

| Step | Status | Detail |
| --- | --- | --- |
| `public_wu_settlement_restore` | **ok** | `PASS; target 2026-08-10; restored 12/12; fetched 12` (645.7 s) |
| `market_day_labels_finalize` | **error** | `[Errno 13] Permission denied: data\settlements\austin\ledger.jsonl` (284.8 s) |

`finalize_folders` had **no per-folder error handling**. The first raise aborted the loop, so
`write_labels_csv` — which runs *after* the loop — never executed. Result:

- `data/backtest/market_day_labels.csv` stayed stamped **08-10 09:49**, 789 rows, max
  `target_date` **2026-08-09**.
- **2026-08-10 had no label row for any of the 12 markets**, despite its data being on disk.

That is the expensive part. Per `missed-chain-day-leaves-settlement-hole`, **each chain run settles
only yesterday and no future run goes back**, so a transient filesystem error becomes a *permanent*
settlement hole unless someone notices within the day.

## Why it was cheap to recover

The failure was downstream of the data. Everything needed was already on disk:

- All **12** `data/snapshots/*august-10-2026/` folders present with `snapshots_long.csv` (~2 MB each).
- WU daily summaries carry 08-10 (`cyyz` 29.0 C, `kaus` 97.0 F).

So this needed **finalize only — no refetch**. Recovery re-finalized the 12 folders against the
production ledger root: **12/12 `complete`, reconciliation `match`, `promotion_countable=True`**.
`market_day_labels.csv` went 789 → **801** rows with nothing lost.

**This advanced the capture streak from 1 to 2.** `COUNTABLE_LABEL_QUALITIES` is
`{complete, manual_override}` (`point_in_time_evaluation.py:104`), and the contiguous countable run
is now `08-09` + `08-10`. The streak read 1/14 not because capture failed but because **the step
that certifies a captured day died**.

## The trap in the recovery path — read this before backfilling

`write_labels_csv` (`settlement_ledger.py`) opens the CSV with `"w"` and writes **only the labels
handed to it**. It does not merge. So the "surgical" recipe of re-finalizing just the 12 folders for
one date with `--labels-csv` pointing at the production file would have **truncated 789 rows to 12**.

The codebase already knew this — `_merge_labels_into_csv` (`daily_refresh_trading_steps.py:615`)
exists precisely for subset re-finalizes and documents the hazard. The recovery used that helper.
**A subset re-finalize must merge by `event_slug`, never rewrite.**

## The fix (`bcb49506`)

Three changes in the finalize path, plus one lock bug:

1. **`finalize_folders` isolates each folder.** Failures are collected and re-raised as
   `FolderFinalizationError` **after** the surviving labels are persisted — the step still fails
   loudly and visibly, but the work that succeeded is kept. This converts "lose 12 market-days
   silently" into "lose one market, reported".
2. **A partial run merges instead of truncating.** New `merge_labels_csv` is used when any folder
   failed, so the rows belonging to the failed folders are not deleted.
3. **`_finalize_folder_with_retry`** retries `OSError` (the observed transient sharing violation).
   Data and schema errors still raise on the first attempt.
4. **`_acquire_ledger_lock` stale-lock reclaim** caught only `FileNotFoundError`. Windows refuses to
   unlink a lock file a live holder still has open and raises `PermissionError`, which escaped the
   loop. A held lock is not a stale lock — wait rather than die.

341 tests pass across all 16 files that consume `settlement_ledger`. ROLL-FREE per
`scripts\ops\roll_verdict.ps1` — `settlement_ledger.py` is outside all three live capture closures.

## What is NOT claimed

**The root cause of the `PermissionError` is not diagnosed.** Finalize *succeeded* on 08-10 (the CSV
was written 09:49 that day) and failed on 08-11, so it is **intermittent, not a daily failure** —
the same shape as the maker binding race, where "it will recur every day" was measured and proved
wrong. This is a robustness fix, not a diagnosis.

One structural fact is worth recording because it sets the collision window and is independently
suspicious: **`upsert_ledger_record` rewrites the entire ledger on every single upsert.** Austin's
ledger is 19.5 MB and the chain finalizes ~66 austin folders per run, so one market's ledger is
rewritten ~66 times per run, fleet-wide on the order of 15 GB of writes per chain run. It also
explains why a July 12 label carries `revision_number = 28`: every run appends a fresh revision
because `evidence` churns. **Nobody has asked what that costs in disk or in collision risk.**
That is an open question, not a finding.

## Still open — the other two holes

`2026-08-06` and `2026-08-08` remain `source='none'`, `quality_grade=missing_settlement`, 12/12.
These are **genuine source holes**, not finalize failures: the WU daily summaries skip both dates
(`cyyz` runs 08-05 → 08-07 → 08-09 → 08-10). They need an explicit per-date backfill **with refetch**,
and the 05:30 backfill tasks keep deferring at the 70% commit-admission ceiling while reporting
`SETTLED` on a `source='none'` row (see `backfill-reports-settled-on-a-none-row`).
