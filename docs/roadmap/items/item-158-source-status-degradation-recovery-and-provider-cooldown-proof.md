# 158. Source-Status Degradation Recovery And Provider Cooldown Proof [COMPLETE 2026-06-20 - SOURCE STATUS PROOF AND ZERO BLOCKED MARKETS]

Goal: make source-status degradation recoverable and auditable so temporary
provider limits do not silently block active-day evidence or contaminate model
learning.

Source: the June 19 recovery sequence improved source status but still left
blocked or degraded markets. Fleet checkpoints moved from 12 blocked
`source_status_freshness` markets to a smaller set, but the latest report still
showed 5 blocked markets and Open-Meteo-family degradation. Per-target-day
source-status tapes also show repeated `rate_limited`, `rate_limited_cache`,
`fresh_cache`, and `failed` rows across June 16-19.

Why this matters: source failures are not all equal. A provider cooldown with a
fresh cache and redundant source support should not be treated like a missing
settlement-critical observation. Conversely, degraded status must remain visible
when it weakens live-forward or promotion evidence.

## Design

1. Classify source-status degradation by family, provider, severity, market,
   target date, and whether fallback/cache evidence is acceptable for the
   current claim lane.
2. Separate model-review countability, paper-trading countability, live-trade
   permission, and promotion-readiness treatment for degraded sources.
3. Add provider-cooldown proof: retry-after/cooldown state, cache age, fallback
   source rows, and exact markets blocked.
4. Add repair commands that target the failing family instead of rerunning the
   entire snapshot stack blindly.
5. Feed source-status blocked-market counts into the daily progress ledger.

- [x] Extend `source_status_freshness` reporting with affected family, affected
  market, cooldown/cache state, fallback state, and claim-lane allowance.
- [x] Add regression coverage for Open-Meteo rate-limit/cache states observed
  on June 19.
- [x] Add a repair or verification command that refreshes only missing/degraded
  source-status rows when the provider is no longer cooling down.
- [x] Make daily learning report the top degraded source family and blocked
  market count.
- [x] Define which source-status states are non-countable for live trading even
  when model-review evidence remains allowed.

2026-06-20 update: `collection.source_status_proof` now records per-market and
per-family affected counts, cooldown/cache detail, fallback and rate-limit
states, claim-lane allowance, and targeted per-folder repair commands. Fleet
observability and daily learning both render a `Source Status Proof` section.
Provider cooldown with fresh family coverage remains model-review and paper
eligible, but is not live-trade or promotion-ready evidence. Targeted repair
uses `python -m weather.collection.snapshot_tracker --backfill-source-status
--overwrite-source-status --source-status-folder <folder>`.

Latest regenerated evidence: `data/backtest/fleet_observability_report.md`
shows `source_status_freshness` `PASS`, blocked markets `0`,
provider-cooldown sources `0`, top degraded family `-`, and daily learning
records the same blocked-market count.

Acceptance: fleet observability reports `source_status_freshness` blocked
markets `0` for a future active day, or gives one market/family/owner/action
for any remaining block. Provider cooldown rows are auditable without being
confused with hard source failure, and daily progress records the blocked
market count.

## Completion Notes

Validated in the 2026-06-24 complete-roadmap sweep:

- `ROADMAP.md` and this item file both mark the item `COMPLETE` with status text `COMPLETE 2026-06-20 - SOURCE STATUS PROOF AND ZERO BLOCKED MARKETS`.
- The file contains 5 checked implementation checklist item(s); no unchecked implementation checklist items remain.
- Validation result: accepted as properly implemented for this completed disposition based on the existing checked implementation evidence; no active roadmap work was reopened for this item.
- Future validation should rerun `python -m weather.reporting.roadmap_backlog --fail-on-lint` and the referenced modules, generated artifacts, and checked implementation bullets in this file.

