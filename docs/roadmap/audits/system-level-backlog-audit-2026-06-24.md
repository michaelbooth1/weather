# System-Level Backlog Audit - 2026-06-24

Scope: all numbered roadmap items through item 300, plus the active backlog and
ROADMAP maintenance conventions.

## Settlement Truth, Provenance, And Label Quality

Already covered: items 20, 23, 25, 28, 64, 93, 120, 153, 164, 193, 197, 201,
203, 208, 213, 265, and 281 cover settlement-scored evaluation, canonical
Weather Underground truth, source-role separation, finalization freshness,
revision audits, and failure/backfill poisoning guards.

Overlaps: item 28 owns the ledger, item 64 owns canonical-vs-supplemental source
role guardrails, item 120 owns daily finalization freshness, item 265 owns
post-close revision/truth-label audit, and item 281 owns source auth/transient
failure typing. These are related but not duplicate.

Gap disposition: no new item. Future truth-label problems should expand item
265 or item 281 unless they are outside canonical settlement-source behavior.

## Historical Data, Redundancy, Backup, And Retention

Already covered: items 29-32, 61-65, 76-81, 100, 102, 109, 111, 113, 114, 124,
146, 154, 171, 172, 185-191, 201, 203, 243-247, and 286-291 cover source depth,
redundancy, raw sidecars, source-health recovery, tape backup, Parquet archives,
event-day manifests, storage classes, cleanup gates, and schema reconciliation.

Overlaps: items 65/111/146/246/247 form a backup maturity chain; item 287 plus
items 286/288/290/291 form the storage-class and archive-verification chain.

Gap disposition: no new item. External durable/deduplicated backup remains owned
by item 246, and local mirror reclaim remains item 247.

## Live Collection, Freshness, And Operations

Already covered: items 31, 37, 40, 42, 57, 95, 100-102, 108, 112, 116, 118,
120, 141, 152, 157, 158, 161, 199, 210-213, 225, 229, 258, 277, 282, and 294
cover loop supervision, freshness, source degradation, live-forward SLOs,
stale-row recovery, snapshot cadence, current-code soak, and daily input
freshness.

Overlaps: item 157 owns snapshot cadence SLO, item 161 owns restart/current-code
soak, and item 229 owns the clean active-day proof needed for early-hour fixes.

New item: item 299, Polymarket Event-Metadata Rollover Gate. Existing items
catch stale or blank market discovery after it breaks a run, but none proactively
validate target-date event metadata across snapshot, CLOB, bot, and daily
learning countability before an active day starts.

## Model Calibration, Train/Serve Parity, And Validation

Already covered: items 21-24, 26-27, 33-37, 48, 69-73, 83-86, 104-106,
117, 123, 125, 134-143, 177-184, 217, 224, 226, 242, 254, 262-269, and
293-298 cover calibration, train/serve parity, variant governance, promotion
gates, daily progress, proper scoring, market benchmark separation, and the
daily analysis improvement loop.

Overlaps: items 293-298 are a coherent daily-analysis suite, not duplicates:
correctness, input freshness, longitudinal blocker lifecycle, impact/confidence
ranking, calibration drift, and experiment-queue consumption each have separate
acceptance criteria.

Gap disposition: no new item. Follow-on daily-analysis work should expand
items 293-298 rather than create another generic reporting item.

## Early-Hour, Late-Day, And Location-Specific Weaknesses

Already covered: items 8, 49, 59, 70, 103, 134-136, 144, 147, 160, 168-170,
177-178, 194-196, 219, 224, 227-233, 248-252, 266, and 268 cover early-hour
forecast anchoring, winner centering, exact-band calibration, validate-what-you
serve, bottom-location gaps, late-day lock-in, and per-market warm centering.

Overlaps: item 160 is the umbrella gate, item 147 targets winner centering, item
219 targets bottom locations, item 228 targets the predawn weak-slot candidate,
item 230 targets exact/distance-0 calibration, and item 233 targets the final
served distribution head.

Gap disposition: no new item. New early-hour fixes should be folded into the
active owners above, especially items 160, 219, 228, 230, and 233.

## Trading Systems, CLOB, Order Lifecycle, And Profitability

Already covered: items 38, 43-47, 55-57, 66-68, 110, 121, 144, 152, 156,
162, 164-167, 192, 202, 209-215, 220, 234-241, 253, 255-261, 272-285, and 292
cover CLOB capture, maker/taker evidence classification, live adapter gates,
order lifecycle, settlement-scored PnL, fees/slippage/depth, NO-side evidence,
clustered promotion gates, EV-ranked taker allocation, per-slice permissions,
and correlated-regime exposure caps.

Overlaps: item 292 closes cross-market correlated exposure risk; item 240 owns
friction modeling; item 284 owns after-cost EV entry/ranking; item 45 owns live
platform/account verification.

New item: item 300, Current Exchange Economics And Rule-Drift Gate. Existing
items model and consume fee/reward/order assumptions, but none prove those
assumptions are current before paper evidence, bakeoffs, and promotion claims
use them.

## Architecture, Maintainability, Docs, And Roadmap Hygiene

Already covered: items 87-99, 107, 119, 122, 126-133, 161, 173-176, 204-206,
254, and 270 cover canonical package surfaces, compatibility shims, import
boundaries, large-module splits, generated-state cleanup, roadmap lint, and
reporting subdomain decomposition.

Overlaps: items 90/98/130/173 are historical large-module size work; item 270 is
the active folder-cohesion owner after those splits.

Gap disposition: no new item. Compatibility-shim execution remains item 206,
generated-state cleanup remains item 176, and reporting cohesion remains item
270.
