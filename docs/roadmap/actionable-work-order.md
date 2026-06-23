# Actionable Roadmap Work Order - 2026-06-22

Source: `docs/roadmap/active-backlog.md` generated at
`2026-06-23T00:46:11.814025+00:00` and the numbered roadmap item files as of
2026-06-22.

This document lists only `OPEN` roadmap items. `PARTIAL` and `COMPLETE` items
are intentionally omitted, even when they remain important parent gates or
diagnostic lanes.

For this work order, "not blocked" means the remaining work can start in this
checkout without a future calendar window, a future clean active day, external
durable-storage setup, or another `OPEN` item that must land first.

Audit result: `active-backlog.md` currently lists 6 `OPEN` items. One is
locally actionable now; five are open but blocked or deferred by evidence,
calendar, external storage, or prerequisite work.

## OPEN Unblocked Implementation Order

| Rank | Item | Why this comes here |
| ---: | --- | --- |
| 1 | [245. Parquet-First Historical Analysis Readers](items/item-245-parquet-first-historical-analysis-readers.md) | Reader migration can now start because item 244 writes validated closed-day Parquet partitions and manifests with text-tape fallback evidence. |

## OPEN But Blocked Or Deferred

| Item | Why it is not in the immediate order | Revisit after |
| --- | --- | --- |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | The item itself says local raw restore is absent and future train-side CLOB days are needed. | Fresh train-side CLOB midpoint coverage and restore-source evidence exist. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | The removal window starts after 2026-07-18, so this is calendar-gated as of 2026-06-22. | The July 18 expiration window opens and caller scans are current. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Completion requires a clean future active day with snapshot cadence, source freshness, CLOB freshness, and current-code soak evidence. | A countable active day completes cleanly. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Acceptance requires a durable repository outside the workspace, credentials or operator setup, and restore-drill evidence. | External/NAS/object storage target and credentials are available. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Safe reclaim depends on item 246 being live and restore-verified; mirror cleanup should not precede durable retention. | Item 246 is operational and restore drills pass. |

## 2026-06-22 Completion Update

- Items `252`, `249`, and `248` are now `COMPLETE` with evidence in
  `data/backtest/austin_weather_model_hardening_report.md`; they are removed
  from the OPEN work order.
- Item `243` is now `COMPLETE`: the versioned closed-day Parquet archive
  contract and manifest schema are registered and documented.
- Items `251` and `244` are now `COMPLETE` and removed from the OPEN work
  order.
- Item `245` remains `OPEN` and is now the first local implementation item.
- Items `156`, `206`, `229`, and `246` are `OPEN`, but not immediate local
  implementation items because they need future evidence, a calendar window, or
  external durable-storage setup.
- Item `247` remains blocked behind item `246`.
