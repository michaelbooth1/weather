# Actionable Roadmap Work Order - 2026-06-23

Source: `docs/roadmap/active-backlog.md` generated at
`2026-06-23T02:15:07.248374+00:00` and the numbered roadmap item files as of
2026-06-23.

This document lists only canonical `OPEN` roadmap items. `PARTIAL` and
`COMPLETE` items are intentionally omitted from the implementation order, even
when they remain important parent gates or diagnostic lanes.

For this work order, "workable now" means a local implementation, test, report,
or runbook change can make meaningful progress in this checkout without waiting
for a future calendar window, a future clean active day, external durable
storage, or another `OPEN` item that should land first.

Audit result: `active-backlog.md` currently lists 16 `OPEN` items. Nine are
workable now as local implementation or reporting work. Seven are open but
blocked or deferred by future evidence, calendar timing, external storage, or
an open prerequisite.

## OPEN Workable Now - Recommended Order

| Rank | Item | First move | Why this comes here |
| ---: | --- | --- | --- |
| 1 | [255. Taker Current-High Deny Regression Proof](items/item-255-taker-current-high-deny-regression-proof.md) | Remove the config-reopenable aggressive pre-late current-high allowance and add a regression with `current_high_trust_gate_start_hour_local=15`. | Small, high-safety fix. It closes a live-risk escape hatch before more taker campaign work. |
| 2 | [261. Taker Canary Tail-Share Demotion On Unsettled Sample](items/item-261-taker-canary-tail-share-demotion-on-unsettled-sample.md) | Add the paper-only demotion decision for `WARN_HIGH_TAIL_SHARE` plus `MISSING_SETTLED_SAMPLE` and surface the reason in next-run/daily-roll status. | Another direct safety gate. It prevents unresolved high-tail canary evidence from being promoted while item 256 waits for labels. |
| 3 | [259. Current-Run Artifact Profitability Field Verification](items/item-259-current-run-artifact-profitability-field-verification.md) | Add a verifier for latest taker order tapes, strategy summaries, and finalization payloads, with June 19-22 legacy fixtures that fail. | It prevents stale artifacts from supporting false profitability claims and should land before requalification evidence is trusted. |
| 4 | [260. Daily Maker Paper-Score Freshness SLA](items/item-260-daily-maker-paper-score-freshness-sla.md) | Add latest maker-run discovery to daily refresh and emit paper-score freshness fields in the standard report/JSON. | Low-dependency operations work that makes maker evidence freshness visible before the next active-day proof attempt. |
| 5 | [257. Real NO-Book Depth For Two-Sided Taker](items/item-257-real-no-book-depth-for-two-sided-taker.md) | Add real NO-token best bid/ask/depth provenance to taker candidate rows and keep synthetic complement rows non-promotable. | Item 253 is complete, so the next two-sided bottleneck is real execution depth. Do it after the immediate taker safety/verifier gates. |
| 6 | [265. Settlement-Source Revision And Truth-Label Audit](items/item-265-settlement-source-revision-and-truth-label-audit.md) | Add the settlement-source revision audit schema and report over WU, Weather.com, canonical ledger, and market-resolution labels. | Truth-label reliability underpins promotion, backtest, and trading evidence. It is foundational but broader than the immediate safety gates. |
| 7 | [262. Proper-Scoring And Reliability Scorecard](items/item-262-proper-scoring-and-reliability-scorecard.md) | Add the scorecard schema and Markdown/JSON report using existing proof-packet inputs without retraining. | This improves model-review quality after the label-audit path is underway. |
| 8 | [263. Physical Feature-Family Isolated Replay Ratchet](items/item-263-physical-feature-family-isolated-replay-ratchet.md) | Add the physical-family evidence contract and rollup with explicit lineage, missingness, and isolated-replay statuses. | This is broad model-governance work. It benefits from the scorecard and truth-label audit rather than preceding them. |
| 9 | [264. Market Benchmark And Residual Edge Research Lane](items/item-264-market-benchmark-and-residual-edge-research-lane.md) | Add the market benchmark/residual-edge report while preserving weather-only, market-only, overlay, and trading-result separation. | Important research lane, but it is less urgent than safety gates and partly depends on clean executable-depth/profitability verification. |

## OPEN But Blocked Or Deferred

| Item | Why it is not in the immediate order | Revisit after |
| --- | --- | --- |
| [156. CLOB Midpoint Continuity For Market-Informed Repair](items/item-156-clob-midpoint-continuity-for-market-informed-repair.md) | Local restore evidence is exhausted and train-side midpoint coverage needs future raw token/book days or an external restore source. | Fresh train-side CLOB midpoint coverage or off-machine raw restore evidence exists. |
| [206. Compatibility Shim Expiration Removal Execution](items/item-206-compatibility-shim-expiration-removal-execution.md) | The removal checklist is explicitly gated until on or after 2026-07-18. | The July 18 expiration window opens and caller scans are current. |
| [229. Early-Hour Live-Forward Clean-Day Proof](items/item-229-early-hour-live-forward-clean-day-proof.md) | Completion requires a future active day with clean snapshot cadence, source freshness, CLOB freshness, and current-code soak evidence. | A countable active day completes cleanly. |
| [246. Deduplicated Durable Tape Backup Repository](items/item-246-deduplicated-durable-tape-backup-repository.md) | Acceptance requires an external/NAS/object-storage repository, credentials, and restore-drill evidence outside this checkout. | A durable repository target and credentials are available. |
| [247. Tape Backup Mirror Demotion And Guarded Reclaim](items/item-247-tape-backup-mirror-demotion-guarded-reclaim.md) | Safe reclaim depends on item 246 being operational and restore-verified. | Item 246 is live and restore drills pass. |
| [256. Post-Fix Taker After-Fee Requalification Campaign](items/item-256-post-fix-taker-after-fee-requalification-campaign.md) | The campaign can be prepared, but acceptance requires 3-5 fresh complete-label paper days under current defaults. | Items 255, 259, and 261 land, then new labelable campaign days settle. |
| [258. Maker Active-Day Freshness Recovery And MM Preflight Proof](items/item-258-maker-active-day-freshness-recovery-and-mm-preflight-proof.md) | The proof packet can be prepared, but the item cannot close without a fresh post-recovery maker paper-live-forward session. | Item 260 lands and a selected-market maker session completes with clean preflight evidence. |

## Status Notes

- Item `254` is no longer treated as `OPEN`: its heading was normalized to
  `PARTIAL 2026-06-23 - IMPLEMENTED, VERIFICATION BLOCKED BY UNTRACKED RUNTIME IDENTITY FILE`
  because its named verification command currently fails on
  `src/weather/runtime_identity.py` being untracked.
- Item `253` remains `COMPLETE` and is no longer in the open work order.
- The roadmap lint passes with `265` item files, `16` `OPEN`, `32` `PARTIAL`,
  `217` `COMPLETE`, and `0` lint errors.
