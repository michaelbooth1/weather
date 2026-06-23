# Actionable Roadmap Work Order - 2026-06-22

Source: `docs/roadmap/active-backlog.md` generated at
`2026-06-23T00:31:26.016335+00:00` and the numbered roadmap item files as of
2026-06-22.

This document lists only `OPEN` roadmap items. `PARTIAL` and `COMPLETE` items
are intentionally omitted, even when they remain important parent gates or
diagnostic lanes.

For this work order, "not blocked" means the remaining work can start in this
checkout without a future calendar window, a future clean active day, external
durable-storage setup, or another `OPEN` item that must land first.

Audit result: `active-backlog.md` currently lists 8 `OPEN` items. Two are
locally actionable now; six are open but blocked or deferred by evidence,
calendar, external storage, or prerequisite work.

## OPEN Unblocked Implementation Order

| Rank | Item | Why this comes here |
| ---: | --- | --- |
| 1 | [251. Standing-High Partial Lock-In Dampener](items/item-251-standing-high-partial-lockin-dampener.md) | Build the soft standing-high dampener now that official rollover diagnostics and robust forecast-cluster metadata exist. |
| 2 | [244. Historical Snapshot Parquet Backfill And Validation Harness](items/item-244-historical-snapshot-parquet-backfill-validation.md) | Implement dry-run/apply conversion now that the archive contract is explicit. |

## OPEN But Blocked Or Deferred

| Item | Why it is not in the immediate order | Revisit after |
| --- | --- | --- |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | The item itself says local raw restore is absent and future train-side CLOB days are needed. | Fresh train-side CLOB midpoint coverage and restore-source evidence exist. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | The removal window starts after 2026-07-18, so this is calendar-gated as of 2026-06-22. | The July 18 expiration window opens and caller scans are current. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Completion requires a clean future active day with snapshot cadence, source freshness, CLOB freshness, and current-code soak evidence. | A countable active day completes cleanly. |
| [245. Parquet-First Historical Analysis Readers](items/item-245-parquet-first-historical-analysis-readers.md) | Reader migration depends on validated Parquet partitions and manifests from item 244. | Item 244 writes representative validated partitions and reports. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Acceptance requires a durable repository outside the workspace, credentials or operator setup, and restore-drill evidence. | External/NAS/object storage target and credentials are available. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Safe reclaim depends on item 246 being live and restore-verified; mirror cleanup should not precede durable retention. | Item 246 is operational and restore drills pass. |

## 2026-06-22 Completion Update

- Items `252`, `249`, and `248` are now `COMPLETE` with evidence in
  `data/backtest/austin_weather_model_hardening_report.md`; they are removed
  from the OPEN work order.
- Item `251` remains `OPEN` and is now the first local implementation item.
- Item `243` is now `COMPLETE`: the versioned closed-day Parquet archive
  contract and manifest schema are registered and documented.
- Item `244` is now the next data-archive implementation item.
- Item `245` remains `OPEN`, but waits on validated partitions from item `244`.
- Items `156`, `206`, `229`, and `246` are `OPEN`, but not immediate local
  implementation items because they need future evidence, a calendar window, or
  external durable-storage setup.
- Item `247` remains blocked behind item `246`.
