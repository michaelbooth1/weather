# Production Readiness Audit — 2026-07-11

## Decision

The platform is **not ready for live capital**. Keep collection, research,
shadow inference, and paper trading running, but do not enable authenticated
orders.

Canonical execution owner: [Item 321 — Model Production Readiness, Evidence
Integrity, And Staged Release Program](items/item-321-model-production-readiness-evidence-integrity-and-staged-release-program.md).

The fastest responsible route is to productionize a single immutable
prediction release in shadow mode first, repair evaluation integrity and live
capture, requalify one legitimate weather-only challenger, and allow capital
only after independent forward and executable after-cost gates pass.

This audit covered source and test architecture, model/evaluation code,
artifact and promotion flows, live collection status, settled labels, the
current two-week tapes, trading evidence, CI/scheduled operations, local data
retention, and the canonical roadmap.

## Two-Week Performance

Audit window: **2026-06-28 through 2026-07-11**. July 11 is unresolved, so the
latest scoreable date is July 10.

- Theoretical settled market-days: 156 (13 dates × 12 markets).
- Promotion-countable scored market-days: 141 (90.4%) across 12 dates.
- July 6 is excluded for all markets because capture coverage was only
  68.8%–77.5%.
- Atlanta, NYC, and Seattle on July 4 are excluded for decisive gaps.
- The effective independent evidence is 141 market-days across 12 dates, not
  the hundreds of thousands of correlated band/snapshot rows.

Lower Brier and log loss are better. Gap is model minus market, so positive is
bad.

| Scope | Model Brier | Market Brier | Gap | Model log loss | Market log loss | Model top-1 | Market top-1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All hourly checkpoints (35,618 rows) | 0.07191 | 0.03734 | +0.03458 | 0.24078 | 0.11823 | 36.9% | 67.0% |
| 00:00–08:00 | 0.08092 | 0.05160 | +0.02932 | 0.27847 | 0.16208 | 27.3% | 52.2% |
| 09:00–14:00 | 0.07624 | 0.05388 | +0.02236 | 0.24796 | 0.16971 | 27.8% | 53.8% |
| 15:00–19:00 | 0.05773 | 0.02217 | +0.03557 | 0.18407 | 0.07278 | 51.5% | 82.1% |
| 20:00–23:00 | 0.06435 | 0.00079 | +0.06356 | 0.22264 | 0.00335 | 52.8% | 99.3% |
| First live variant prediction (1,551 band rows / 141 market-days) | 0.08175 | 0.05954 | +0.02221 | 0.27787 | 0.18922 | 23.4% | 46.1% |

Overall Brier skill versus market is **−0.926**: model error is about 1.93×
market error. Model ECE is 0.0303 versus market 0.0023. Every recent scored
date, market, and hour trails the market.

The first six scored dates averaged model Brier 0.0831; the last six averaged
0.0612. That directional improvement is encouraging, but the corresponding
market averages were 0.0357 and 0.0382, every day still lost, and mixed runtime
identities prevent attributing the change to a release.

### Legitimate live-forward variants

| Variant | Lane | Brier | Delta vs current | Gap vs market | Disposition |
| --- | --- | ---: | ---: | ---: | --- |
| Dynamic source state | weather-only | 0.07635 | −0.00540 | +0.01681 | Best legitimate recent weather challenger; retain |
| Item 50 pooled | weather-only | 0.07709 | −0.00467 | +0.01755 | Retain as challenger/control |
| Exact-winner catch-up | weather-only | 0.08094 | −0.00081 | +0.02140 | Useful late-slice hypothesis only |
| CLOB raw OOF | market-informed | 0.07389 | −0.00786 | +0.01435 | Quote-risk lane only; still trails market |
| Continuous density HGB | weather-only | 0.13128 | +0.04953 | +0.07174 | Quarantine; live/replay parity failure |

The most promising next experiment is a **predeclared serve-time regime
router**, not a new feature hunt: dynamic-source early/midday, exact-winner
late, and Item 50 at lock-in. This must be selected inside nested walk-forward
training and tested on an untouched window; the recent window cannot be used
both to select and claim the router.

## Invalid Evidence Found

### Item 224 — deterministic label leakage

`item224_active_timesplit_logistic_repair_v0_1` used
`settlement_distance_bucket` as a categorical feature and in a guardrail. The
field is calculated from the final settled bucket. Across 67,430 train/eval
rows it perfectly encoded the outcome: all distance-0 rows were winners and no
other distance bucket contained a winner.

The reported held-out Brier of 0.00927 is invalid. On the same split:

| Version | Brier | Log loss |
| --- | ---: | ---: |
| Reported leaked model | 0.00927 | 0.05160 |
| Leak removed | 0.08848 | 0.32400 |
| Leak removed + inference-available guardrail | 0.07894 | 0.26624 |
| Current model | 0.05068 | 0.17024 |
| Market | 0.03856 | 0.12804 |

Its independent band logits also did not form a probability partition. All
downstream Item 224/160 market-beating, hourly, 10-minute, and location PASS
claims are revoked. V0.1 is now shadow-only, non-headline,
non-promotion-countable, and explicitly quarantined in the registry. Item 224
is reopened.

### Item 187 — research target leakage

The June 23 input-significance run included the generated target
`target_market_z` as a predictor after a broad import fallback. It dominated
permutation importance and produced implausible cross-validation scores. This
invalidates the permutation-evidence leg of Item 187, not the separately
trained radiation model.

The shared feature-safety policy now rejects target/outcome/settlement fields,
the research fallback is fail-closed for promotion-grade work, and the existing
contaminated CSV makes the radiation gate return
`permutation_target_leakage_detected` until it is regenerated.

## Production Readiness

### What is strong

- Latest settlement finalization is complete and reconciled for all 12
  markets.
- The project generally fails closed and emits unusually detailed blocker and
  remediation artifacts.
- Source/schema/duplicate/impossible-value checks are broad.
- Trading risk defaults are conservative and no tracked credentials/private
  keys were found.
- The repository has a large automated test suite and now has pull-request CI.

### P0 blockers

1. **No proven model or executable edge.** Weather-only, residual, and trading
   lanes are blocked. Taker has no settled fills and maker evidence is not
   live-forward countable.
2. **Candidate evidence integrity was compromised.** Item 224 and Item 187
   artifacts must be regenerated after the fixes; a generic leakage gate must
   cover every candidate pipeline.
3. **No canonical live-variant settlement scorecard exists.** Promotion can
   score replay exports while live variants skip or collapse. The recent tape
   exposed 100% unsupported-runtime skips for Item 224 and a severe live
   density failure that headline replay reports missed.
4. **Runtime identity remains mixed.** Correct date scoping reduces the July 11
   evidence from 608 apparent identities/684k historical rows to 3 genuine
   identities/13,332 current-day rows, but one immutable release identity is
   still required for a countable day.
5. **CLOB capture misses its SLO.** A configured 15-second fast interval had a
   latest fleet iteration near 386 seconds; eight markets experienced roughly
   34–38 minute gaps. Collection must be isolated from heavy training/report
   jobs and sharded/concurrent.
6. **Training and serving artifacts are not isolated.** Training writes into
   serving paths before promotion, writes are not an atomic immutable release,
   missing family manifests can fail open, and rollback is not release-based.
7. **Scheduled promotion/retraining is not reliably unattended.** Long phases,
   cache sentinel invalidation, stale/inconsistent inputs, and lock contention
   have blocked multiple nights. Seven consecutive complete unattended cycles
   are required.
8. **Storage is on an unsafe trajectory.** The latest inventory contains 3.28M
   files / 256.2 GB, 60.1 GB written in 24 hours, 54.9 GB unclassified, and zero
   event-day manifests. At the observed write rate, free-space headroom is
   about seven days. The inventory now blocks below 30 days of observed-write
   headroom, but retention/externalization work remains.
9. **This is a mutable desktop deployment.** Processes run as an interactive
   user, different loops can run different commits, restart depends on the
   checkout, and there is no immutable service release.
10. **A real order adapter is not wired.** Live order mode still resolves to a
    null/fixture adapter. This is intentionally deferred until model and paper
    gates pass.

## Fastest Responsible Release Path

### Stage 0 — integrity reset (now)

- Quarantine Item 224 v0.1 and density HGB.
- Regenerate Item 187 significance evidence and every Item 224-derived gate.
- Add the live-variant settlement scorecard with variant-level grouping,
  probability-simplex validation, coverage/skips, and replay/serve parity.
- Establish one candidate release manifest: code commit, source fingerprint,
  model/calibration hashes, config hashes, Python/sklearn versions, routes, and
  rollback target.

Exit: no label/post-event features; exactly one winning band; all partitions
sum to one; no unsupported live runtime; replay and served outputs match.

### Stage 1 — production shadow

- Deploy capture and prediction from an immutable release directory with no
  order credentials.
- Run capture separately from research/promotion compute.
- Restart all loops together only at a market-day boundary.
- Make automatic health-based restart and rollback operational.

Exit: one identity, 100% prediction coverage, zero material snapshot/CLOB gaps,
fresh sources, and three consecutive clean active days.

### Stage 2 — challenger requalification and paper canary

- Start from dynamic-source and Item 50; test the predeclared regime router.
- Use nested rolling-origin folds grouped by whole fleet date, with all
  preprocessing/calibration fitted inside each training fold.
- Keep the latest locked 14-day window untouched until the candidate is frozen.

Exit: at least seven complete forward days / 84 countable market-days, better
aggregate Brier and log loss than current, no material per-market regression,
hourly/weak-slot gates pass, 100% live coverage, and replay/serve parity.

### Stage 3 — limited capital canary

Only wire the authenticated adapter after a second independent forward window
confirms either a weather-only market-beating lane or a predeclared residual
edge, and paper execution shows positive after-fee/after-slippage P&L. Require
at least 100 aggregate executable paper fills, position/order reconciliation,
idempotent orders, cancel-all/dead-man controls, tiny hard caps, and manual
authorization.

## Prioritized Backlog

| Priority | Work | Existing roadmap consolidation | Acceptance |
| --- | --- | --- | --- |
| P0 | Regenerate/revoke leaked evidence | 187, 224, 160 | Fresh outputs block all label-derived features; old PASS claims remain diagnostic-only |
| P0 | Canonical live-variant scorer and parity gate | 141, 143, 233 | Settlement-scored variant tape; zero skips; variant-separated rank/RPS; simplex and served/replay parity pass |
| P0 | Immutable candidate/release/rollback manifest | 126, 131, 142, 177 | Candidate-only writes; hash-verified atomic promotion; tested one-command rollback |
| P0 | CLOB/capture resource isolation | 118, 124, 156, 157 | p99 book age <120s normally and <30s near close; zero threshold gaps for three days |
| P0 | One clean current-release active-day proof | 157, 161, 229, 307 | One identity; all 12 markets countable; fresh source/CLOB/cadence evidence |
| P0 | Unattended daily/nightly reliability | 101, 108, 112 | Seven consecutive idempotent scheduled completions inside SLA |
| P0 | Storage manifests, columnar archive, off-machine copy | 171, 287, 290 | ≥30 days write-rate headroom; checksummed manifests; restore drill; reviewed deletion only |
| P1 | Requalify one legitimate challenger | 134, 135, 136, 138, 147, 160, 178, 228, 230 | Nested date-blocked evaluation; current improvement; locked holdout and forward confirmation |
| P1 | Streaming evaluator and honest sample accounting | 117, 163 | 14-day scorecard completes without materializing raw corpus; reports dates/market-days/CIs |
| P1 | Data quality/source reliability repair | 114, 125, 185 | Stale/failed source rate <5%; training exclusions understood; active sidecars complete |
| P1 | Executable experiment queue | 298 and daily-learning queue | Every queued experiment has command, frozen inputs, owner, decision rule, and recorded result |
| P1 | Service hardening | operations track | Dedicated account/host, loopback/authenticated UI, health rollback |
| P2 | Live exchange adapter | 67 | Implement only after Stage 2; full order lifecycle and risk-canary tests |
| P2 | Module/shim cleanup | 130, 173, 206 | Reduce blast radius after critical gates; execute shim removal on/after July 18 |

The 26 active roadmap items should be managed as five epics: evaluation
integrity, candidate requalification, clean-day operations, artifact/deployment
lifecycle, and data/storage lifecycle. Opening more feature-source items before
these close will slow the path to production.

## Best Use Of The Accumulated Data

1. **Build one point-in-time analytical contract.** Key facts by
   `(target_date, market_id, snapshot/cutoff, band, variant_id)` and keep raw
   source provenance/hash, settlement label, prediction lane, runtime/release
   identity, and countability status separate.
2. **Preserve raw; derive compact columnar tables.** Finish event-day manifests
   and validated Parquet projections. Never delete canonical tapes until an
   off-machine copy and restore drill pass.
3. **Separate claim lanes.** Historical weather trains physical/forecast
   residuals; settlement labels train/calibrate band distributions; CLOB is a
   benchmark and quote-risk/residual overlay, never weather-only proof;
   partial/quarantined labels remain diagnostic-only.
4. **Validate on dates, not rows.** Use rolling-origin outer folds grouped by
   the entire fleet target date, a 3–7 day embargo for persistent heat regimes,
   nested training-only feature selection/preprocessing/calibration, equal
   market-day weighting, and date-clustered bootstrap confidence intervals.
5. **Use simple pooled structure.** There are roughly 309 corpus market-days
   but only about a month of fleet dates. Prefer regularized forecast-residual
   and ordinal/density models with market partial pooling over high-capacity
   models that treat millions of correlated rows as independent.
6. **Model the error that matters.** Predict the daily-high residual to strong
   NWP anchors, then map a calibrated continuous distribution to market bands.
   Calibrate separately by cutoff regime and market only where sample size
   supports it.
7. **Prioritize active data acquisition, not active labels.** Labels arrive
   automatically. Rank backfills/capture repairs by uncertainty × model-market
   disagreement × regime novelty × economic exposure, while never touching the
   locked evaluation window.
8. **Use stage attribution to prune.** Retain features/stages only when nested
   out-of-time evidence improves Brier and log loss without location or regime
   regressions. Stop expanding sources while core winner centering, live parity,
   and capture reliability are unresolved.

## Changes Applied During This Audit

- Quarantined Item 224 v0.1, removed settlement-derived features/guardrail,
  added fail-closed contracts and probability-partition validation, and
  reopened the roadmap item.
- Added shared target/outcome feature safety and made Item 187 permutation
  evidence fail closed.
- Corrected runtime-identity target-date scoping and added provenance
  accounting.
- Made roadmap parsing BOM-safe and regenerated a lint-clean active backlog.
- Separated variant identities in proper-scoring distribution diagnostics.
- Preserved all-null columns in pooled model imputers to prevent fold/serving
  shape drift.
- Added a 30-day observed-write-headroom storage gate.
- Repaired schema/path hygiene for recent artifacts.
- Added pull-request CI and changed nightly GitHub retraining into a validated
  candidate build that uploads artifacts for review instead of pushing models
  directly to the branch.

Large local data artifacts were not regenerated or deleted. Item 187 and Item
224 evidence regeneration, density diagnosis, and clean forward collection are
the next required operational runs.

## Verification

- `python -m compileall -q app src tests tools/research`: pass.
- Full repository suite: **2,094 passed, 701 subtests passed, 13 warnings**.
- Focused integrity/roadmap/runtime/storage suite: **45 passed**.
- Canonical roadmap backlog: **OK**, 314 items, 26 active, 0 lint errors.
- `git diff --cached --check`: pass.
