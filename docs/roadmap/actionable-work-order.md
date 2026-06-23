# Actionable Roadmap Work Order - 2026-06-23

Source: `docs/roadmap/active-backlog.md` generated at
`2026-06-23T03:35:23.822849+00:00` and the numbered roadmap item files as of
2026-06-23.

This document lists only canonical `OPEN` roadmap items. `PARTIAL` and
`COMPLETE` items are intentionally omitted from the implementation order, even
when they remain important parent gates or diagnostic lanes.

For this work order, "workable now" means a local implementation, test, report,
or runbook change can make meaningful progress in this checkout without waiting
for a future calendar window, a future clean active day, external durable
storage, or another `OPEN` item that should land first.

Audit result: `active-backlog.md` currently lists 7 `OPEN` items. No canonical
`OPEN` item is currently workable as local implementation or reporting work.
All seven are open but
blocked or deferred by future evidence, calendar timing, external storage, or
an open prerequisite.

## OPEN Workable Now - Recommended Order

No `OPEN` item is ready for local implementation right now.

## OPEN But Blocked Or Deferred

| Item | Why it is not in the immediate order | Revisit after |
| --- | --- | --- |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | Local restore evidence is exhausted and train-side midpoint coverage needs future raw token/book days or an external restore source. | Fresh train-side CLOB midpoint coverage or off-machine raw restore evidence exists. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | The removal checklist is explicitly gated until on or after 2026-07-18. | The July 18 expiration window opens and caller scans are current. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Completion requires a future active day with clean snapshot cadence, source freshness, CLOB freshness, and current-code soak evidence. | A countable active day completes cleanly. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Acceptance requires an external/NAS/object-storage repository, credentials, and restore-drill evidence outside this checkout. | A durable repository target and credentials are available. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Safe reclaim depends on item 246 being operational and restore-verified. | Item 246 is live and restore drills pass. |
| [256. Post-Fix Taker After-Fee Requalification Campaign](items/item-256-post-fix-taker-after-fee-requalification-campaign.md) | The campaign can be prepared, but acceptance requires 3-5 fresh complete-label paper days under current defaults. | New labelable campaign days settle under the current gates. |
| [258. Maker Active-Day Freshness Recovery And MM Preflight Proof](items/item-258-maker-active-day-freshness-recovery-and-mm-preflight-proof.md) | The proof packet can be prepared, but the item cannot close without a fresh post-recovery maker paper-live-forward session. | A selected-market maker session completes with clean preflight evidence. |

## Status Notes

- Item `255` is complete: config-drift delayed current-high trust starts now
  warn in daily-roll status while aggressive untrusted-current-high taker rows
  still deny from local hour `0`.
- Item `261` is complete: high-tail active canaries with missing settled
  samples now demote to paper-only with an explicit demotion code and
  post-fix-campaign requalification route.
- Item `259` is complete: current-run taker profitability artifacts now need
  after-fee, after-slippage, executable-depth, benchmark, avoided-loss,
  missed-gain, and no-trade fields before they can support promotion or
  live-profitability evidence.
- Item `260` is complete: daily refresh now regenerates the standard maker
  paper report, records latest completed versus covered active maker days, and
  trading evidence blocks maker countability when the report is stale.
- Item `257` is complete: taker discovery now captures real NO-token book
  depth, order tapes carry real-NO provenance/freshness/depth eligibility, and
  two-sided promotion blocks synthetic-only, stale, or missing-depth NO fills.
- Item `265` is complete: settlement-source revision audit artifacts now
  classify finalized/provisional/revised/disagreed/unreconciled labels, record
  lineage hashes or explicit missing reasons, and block trading evidence when
  settled target dates depend on non-proof-grade truth labels.
- Item `262` is complete: the proper-scoring reliability scorecard now writes
  canonical JSON/Markdown artifacts, runs in daily refresh after active-variant
  shadow, and reports lane-separated Brier/log-loss/ECE/sharpness/rank
  diagnostics plus served-versus-validated parity.
- Item `263` is complete: physical-weather feature families now have a
  fail-closed ratchet with explicit lineage, active-column, replay-slice, and
  promotion-readiness blockers, while CLOB/market overlays are excluded from
  physical proof.
- Item `264` is complete: the market benchmark/residual-edge research lane now
  separates weather-only, market-only, overlay, residual, and trading-facing
  evidence, records missing frozen CLOB/executable-depth blockers, and cannot
  satisfy weather-only proof-packet blockers.
- Item `254` is no longer treated as `OPEN`: its heading was normalized to
  `COMPLETE 2026-06-23 - SERVING RUNTIME EDGE REMOVED AND ARCHITECTURE RATIFIED`
  after its named verification command passed with `73 passed`.
- Item `253` remains `COMPLETE` and is no longer in the open work order.
- The roadmap lint passes with `265` item files, `7` `OPEN`, `31` `PARTIAL`,
  `227` `COMPLETE`, and `0` lint errors.
