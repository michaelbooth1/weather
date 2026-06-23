# Actionable Roadmap Work Order - 2026-06-23

Source: `docs/roadmap/active-backlog.md` generated at
`2026-06-23T00:59:07.133749+00:00` and the numbered roadmap item files as of
2026-06-23.

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
| 1 | [253. Two-Sided (NO-Side) Taker Edge And Book Capture](items/item-253-two-sided-no-side-taker-edge-and-book-capture.md) | This can start locally: it needs taker tape field additions, a gated two-sided strategy arm, bakeoff/scoreboard wiring, risk caps, and tests. It is not waiting on a future calendar window, external storage, or another open roadmap item. |

## OPEN But Blocked Or Deferred

| Item | Why it is not in the immediate order | Revisit after |
| --- | --- | --- |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | The item itself says local raw restore is absent and future train-side CLOB days are needed. | Fresh train-side CLOB midpoint coverage and restore-source evidence exist. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | The removal window starts after 2026-07-18, so this is calendar-gated as of 2026-06-23. | The July 18 expiration window opens and caller scans are current. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Completion requires a clean future active day with snapshot cadence, source freshness, CLOB freshness, and current-code soak evidence. | A countable active day completes cleanly. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Acceptance requires a durable repository outside the workspace, credentials or operator setup, and restore-drill evidence. | External/NAS/object storage target and credentials are available. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Safe reclaim depends on item 246 being live and restore-verified; mirror cleanup should not precede durable retention. | Item 246 is operational and restore drills pass. |

## 2026-06-23 Completion Update

- Item `245` is now `COMPLETE`: validated Parquet-first reader helpers are live,
  source-family inventory uses them, provenance/fallback reporting is exposed,
  and DuckDB is documented as optional operator tooling.
- Item `253` is the only current locally actionable `OPEN` item.
- Items `156`, `206`, `229`, `246`, and `247` remain `OPEN`, but not immediate
  local implementation items because they need future evidence, a calendar
  window, external durable-storage setup, or another open prerequisite.
