# 321. Model Production Readiness, Evidence Integrity, And Staged Release Program [OPEN 2026-07-11 - SHADOW/PAPER/CAPITAL GATES NOT YET CLEARED]

Goal: converge the current research, collection, model, promotion, storage, and
trading systems into one fail-closed production release program that can move a
single model through immutable shadow, paper, and tightly controlled capital
stages without confusing replay volume with independent evidence or allowing
invalid/stale artifacts to satisfy a release gate.

Owner/package: weather.reporting, weather.operations, weather.calibration, weather.collection, weather.model, weather.market

Source: `docs/roadmap/production-readiness-audit-2026-07-11.md`, the settlement-
scored live tapes for 2026-06-28 through 2026-07-10, and the current production
blockers in `data/backtest/daily_refresh_status.json`,
`fleet_observability.json`, `active_variant_shadow.json`,
`proper_scoring_reliability_scorecard.json`,
`market_beating_objective_scoreboard.json`, and
`data_retention_inventory.json`.

Why this matters: the platform has broad fail-closed diagnostics and a large
test surface, but it is not yet safe to treat as a production model or trading
system. In the latest two-week window the served model trails the market on
every scored date, market, and hour. The effective evidence is 141 countable
market-days across 12 fleet dates, not millions of correlated band/variant
rows. Item 224's apparent market-beating candidate used a deterministic
post-settlement label feature, Item 187's permutation-evidence leg included its
generated target, the density lane collapses in live inference relative to
replay, live variant tapes have unsupported-runtime skips, current-day evidence
still contains multiple genuine runtime identities, CLOB cadence is not meeting
its advertised SLO, daily/nightly work has not completed unattended for a
stable run, and storage is growing faster than the current operational posture
can safely absorb.

This item is the cross-cutting production-release owner. Existing numbered
items remain the implementation/evidence owners for their domains; Item 321
does not mark their software complete again or weaken their thresholds. It
composes their outputs, adds the missing end-to-end contracts, and stays OPEN
until real operational evidence clears the final staged-release gate.

## Current Baseline And Non-Negotiable Boundaries

- Latest two-week hourly-checkpoint Brier is `0.07191` for the served model
  versus `0.03734` for the market; log loss is `0.24078` versus `0.11823`.
- First-live-prediction Brier is `0.08175` versus market `0.05954` over 141
  countable market-days.
- Dynamic-source state is the best legitimate recent weather-only challenger
  (`0.07635` Brier), but still trails market by `+0.01681`.
- Item 224 v0.1 is permanently diagnostic-only. Removing its leaked
  `settlement_distance_bucket` reverses the apparent lift.
- Item 187's radiation implementation remains separate from its contaminated
  permutation-evidence leg; that evidence is non-countable until regenerated.
- Continuous-density HGB is quarantined until live/replay divergence is either
  explained and repaired or the lane is formally retired.
- Production shadow means real live inputs and production operating discipline
  with **no order credentials or capital permission**.
- CLOB/market-informed signals may support benchmark, residual-edge, or
  quote-risk claims, but can never satisfy weather-only proof.
- Missing, stale, mixed-lineage, non-point-in-time, unsupported-runtime, or
  non-normalized evidence always denies promotion. No manual override may turn
  such evidence into a PASS.
- Thresholds here are minimums. A stricter child gate (including Item 44's
  paper-trading duration requirement) remains binding.

## Phase 0 — P0 Evidence Integrity Reset

### Leakage invalidation and regeneration

- [ ] Regenerate the Item 187 input-significance/permutation bundle under the
  shared fail-closed feature-safety policy; rerun its gate and explicitly mark
  the contaminated June 23 permutation artifact non-countable.
- [ ] Regenerate every Item 224-derived replay, hourly, 10-minute, location,
  promotion, Item 160, proof-packet, and objective-scoreboard artifact under a
  new clean variant identity. Never overwrite or rehabilitate v0.1 as if its
  historical proof remained valid.
- [ ] Add a generic candidate-contract audit that rejects target, outcome,
  settlement, settlement-distance, winner, post-event, retrospective casebook,
  and label-gate fields from model, calibration, guardrail, route, and feature-
  hash inputs.
- [ ] Require the leakage audit to inspect derived hashes/feature-family
  manifests as well as visible column names, with input hashes and rejected
  field reasons persisted in the candidate packet.

### Canonical live-variant settlement scorer

- [ ] Implement one canonical live-tape settlement scorecard from
  `variant_predictions_long.csv`, joined to canonical settlement labels and
  grouped by `variant_id`, release identity, market-day, snapshot/cutoff, and
  mutually exclusive band partition.
- [ ] Report live prediction coverage, unsupported-runtime skips, duplicate or
  collapsed variant identities, missing bands, exactly-one-winner validity,
  finite/in-range probabilities, probability-partition sum error, Brier, log
  loss, ECE, ranked probability score, top-band hit, winner rank, and current/
  market deltas.
- [ ] Require 100% eligible live prediction coverage and zero unsupported-
  runtime skips for any candidate that can satisfy a release gate.
- [ ] Keep weather-only, market-only, market-informed overlay, predeclared
  residual-edge, and trading lanes separate in both row schemas and summaries.
- [ ] Make all rank/RPS/distribution grouping include `variant_id` and release
  identity so multiple candidates can never form one synthetic partition.

### Replay/serve parity and density disposition

- [ ] Capture the exact point-in-time inputs required to reproduce every served
  prediction, then compare captured-input replay with the served probability
  partition under the same release manifest.
- [ ] Fail promotion if replay and served probabilities, band identities,
  routes, postprocessing, or skip decisions exceed declared deterministic
  tolerances.
- [ ] Diagnose continuous-density HGB live Brier/log-loss collapse by checking
  feature order, missing-value behavior, units, band integration, calibration,
  artifact hash, and serving-route parity.
- [ ] Repair and requalify density on untouched data or formally retire it from
  active/shadow registries. It cannot remain a nominal candidate with known
  live failure.

### Phase 0 exit

- [ ] Every scored market-day partition has exactly one outcome band; every
  candidate partition is finite, within `[0,1]`, unique by band, and sums to
  `1` within the declared tolerance.
- [ ] The promotion candidate contains no label/post-event leakage, has a
  complete lineage attestation, has 100% live coverage, and matches captured-
  input replay.
- [ ] Item 187/224 dependent claims and the market-beating objective are
  regenerated after the integrity reset rather than carried forward.

Primary child evidence: Items 20, 24, 35, 83, 106, 140-143, 160, 177-179, 187,
208, 216, 217, 224, 233, 242, 262-266, 269, 308, 314, and 315.

## Phase 1 — P0 Immutable Release Lifecycle

### Candidate-only build and release manifest

- [ ] Train into an immutable candidate directory, never directly into the
  active serving path. Candidate artifacts remain unservable until the exact
  candidate packet passes.
- [ ] Create `artifacts/releases/<release_id>/release_manifest.json` with the
  release ID; code commit and source fingerprint; dirty-state attestation;
  model, imputer, calibrator, feature schema, postprocessor, route, registry,
  location/config, and settlement-rule hashes; Python/sklearn/direct dependency
  versions; training/evaluation corpus hashes and date bounds; expected live
  runtimes; parent release; and rollback target.
- [ ] Hash-verify the complete release before deserializing or serving it.
  Missing, corrupt, stale, unregistered, or version-incompatible manifests deny
  ML serving and trading rather than falling back to an unverified artifact.
- [ ] Promote atomically by switching a single reviewed release pointer only
  after all gates pass; do not copy partially written files into active paths.
- [ ] Implement and test one-command rollback to the last known-good immutable
  release, including coordinated loop restart and release-identity proof.
- [ ] Cut over all collection/prediction processes only at a market-day
  boundary. A market-day cannot mix release identities and remain countable.
- [ ] Keep GitHub/nightly builds candidate-only: tests and gates run first,
  artifacts are uploaded for review, and no unvalidated model is pushed or
  activated automatically.

### Parent release artifacts

| Artifact | Required role |
| --- | --- |
| `data/backtest/production_readiness_gate.json` / `.md` | Single current stage, status, first blocker, evidence hashes, and next action |
| `data/backtest/live_variant_settlement_scorecard.json` / `.md` | Canonical live-tape model/variant scoring and coverage |
| `artifacts/releases/<release_id>/release_manifest.json` | Immutable build, runtime, routing, lineage, and rollback contract |
| `data/backtest/release_promotion_decision.json` | Reviewed candidate-to-release decision with all gate inputs |
| `data/backtest/release_rollback_drill.json` | Rollback target, timing, post-rollback identity, and health proof |

Primary child evidence: Items 36, 37, 48, 89, 126, 131, 142, 172, 177, 216,
217, 254, and 314.

## Phase 2 — P0 Resource-Isolated Shadow Operations

### Capture isolation, sharding, and identity

- [ ] Run snapshot, observation-trigger, and CLOB capture independently from
  replay, promotion, training, Parquet conversion, and large report jobs, with
  explicit CPU/memory/I/O budgets and backpressure.
- [ ] Shard or concurrently capture markets so one slow provider/market cannot
  stretch a fleet iteration beyond the freshness SLO.
- [ ] Require p99 CLOB book age below 120 seconds normally and below 30 seconds
  near close, plus zero material snapshot/CLOB gaps on countable days.
- [ ] Coordinate snapshot, CLOB, trigger, maker, taker, and dashboard workers on
  one release identity and one configuration fingerprint.
- [ ] Add external critical alerts, automatic health-based restart, and
  rollback escalation; local JSON/Markdown/dashboard state alone is not a
  production notification channel.
- [ ] Bind operator controls to an authenticated/local-only boundary and run
  long-lived workers under a dedicated service identity that does not require
  an interactive login.

### Clean shadow proof and unattended cycles

- [ ] Collect at least three consecutive active days where all 12 markets are
  countable, release identity is singular, source and CLOB freshness pass,
  snapshot cadence has zero material gaps, and current-code soak/restart budget
  pass.
- [ ] Complete seven consecutive idempotent daily-refresh and nightly-retrain/
  validate cycles inside their SLA with no manual repair, stale locks,
  inconsistent inputs, mixed target dates, or unreviewed promotion.
- [ ] Persist a clean-day ledger and unattended-cycle ledger that cannot be
  reset by rewriting the latest status file.

Primary child evidence: Items 16, 17, 42, 57, 101, 108, 112, 118, 124, 152,
157-159, 161, 210-212, 216, 229, 282, 299, 305, 307, 312, 319, and 320.

## Phase 3 — P0 Storage, Archive, And Restore Proof

- [ ] Backfill and validate `event_day_manifest.json` for every active and
  retained historical market-day folder; zero-manifest inventories are not an
  acceptable rollout state even if the writer implementation exists.
- [ ] Complete incremental validated Parquet conversion or record an explicit
  blocker for every retained eligible closed day. High-byte readers must prefer
  validated Parquet with source-mode provenance and text fallback.
- [ ] Keep raw canonical evidence immutable; store derived point-in-time tables
  and analysis projections separately with rebuild lineage.
- [ ] Create a checksummed off-machine copy of irreplaceable settlement,
  snapshot, source-status, replay-input, CLOB, and trading tapes; document RPO,
  RTO, and ownership.
- [ ] Perform and record a restore drill that reproduces a representative
  market-day score and release input from the off-machine copy.
- [ ] Require at least 30 days of observed-write-rate headroom, source-side log
  rotation, explicit ownership for unclassified bytes, and reviewed manifests
  before deletion. Never delete canonical evidence merely to clear a disk gate.
- [ ] Use the demonstrated columnar compression benefit (approximately 136x on
  the audited conversion sample) to finish archive rollout before opening new
  high-volume capture families.

Primary child evidence: Items 15, 25, 60, 124, 131, 154, 159, 171, 172,
176, 201, 203, 243-245, 286, 287, 289, and 290.

## Phase 4 — P1 Point-In-Time Data And Evaluation Contract

### Canonical analytical table

- [ ] Materialize a point-in-time analytical contract keyed by
  `(target_date, market_id, cutoff_or_snapshot, band, variant_id, release_id)`
  with source payload/hash/provenance, feature-availability time, label quality,
  claim lane, release identity, countability, and replay/serve status.
- [ ] Preserve raw inputs unchanged; perform cleaning/normalization in derived
  processed tables with explicit transformation/version metadata.
- [ ] Treat fleet dates and market-days as the independent evidence units.
  Snapshot density, band count, and variant multiplication cannot increase the
  effective independent sample size.

### Validation design

- [ ] Use nested rolling-origin outer folds grouped by the entire fleet target
  date, not independent market-day/band rows.
- [ ] Apply a predeclared 3-7 day embargo where persistent weather regimes can
  leak temporal information between train and evaluation.
- [ ] Fit feature selection, scaling/imputation, model training, calibration,
  postprocessing, and regime/router selection inside each training fold.
- [ ] Weight market-days equally and report date-clustered bootstrap confidence
  intervals alongside point estimates and per-market/regime results.
- [ ] Lock the most recent 14-day evaluation window before candidate selection;
  it cannot be used to choose features, routes, hyperparameters, or thresholds.
- [ ] Make the standard 14-day evaluator stream/aggregate by market-day rather
  than materializing the raw corpus, and always report selected labels,
  excluded days/reasons, market-days, fleet dates, and runtime identities.
- [ ] Target stale/failed source status below 5%, explain every training-
  excluded row/folder, and keep incomplete/quarantined labels diagnostic-only.

Primary child evidence: Items 20, 24-31, 64, 69, 83, 85, 106, 113-117, 120,
140, 143, 179, 203, 208, 216, 243-245, 262-265, 287, 290, 296, and 319.

## Phase 5 — P1 Legitimate Challenger Requalification

- [ ] Start with the inference-valid dynamic-source and Item 50 weather-only
  candidates. Predeclare and test a simple regime router with dynamic-source
  early/midday, exact-winner late, and Item 50 at lock-in; do not select that
  routing policy on the locked evaluation window.
- [ ] Prefer regularized pooled forecast-residual/ordinal or continuous-
  distribution models with market partial pooling. The corpus has roughly a
  month of fleet dates despite millions of rows, so model capacity must reflect
  the independent sample size.
- [ ] Predict residual error around strong point-in-time NWP anchors and map a
  calibrated continuous distribution to market bands. Calibrate by cutoff
  regime/market only where training-fold sample size supports it.
- [ ] Use stage attribution and nested ablation to remove features/stages that
  fail to improve both Brier and log loss or cause protected market/regime
  regressions.
- [ ] Keep CLOB raw OOF and other market-informed candidates in quote-risk or
  predeclared residual lanes. Their gains cannot promote the weather-only core.
- [ ] Pause new feature-source hunts while leakage, parity, capture, storage,
  and the primary challenger are blocked. Acquire/backfill data by uncertainty
  x model-market disagreement x regime novelty x economic exposure instead.

### Challenger exit

- [ ] Accumulate at least seven complete forward days and 84 countable market-
  days under the frozen challenger release.
- [ ] Beat the frozen current release on aggregate Brier **and** log loss with
  date-clustered uncertainty, pass hourly and 10-minute weak-slot gates, and
  have no material per-market regression beyond the existing declared
  tolerances.
- [ ] Preserve 100% live coverage, zero unsupported-runtime skips, probability
  invariants, and captured-input replay/serve parity throughout the window.
- [ ] Record any comparison to market separately from the requirement to beat
  current; no weather-only market-beating claim is allowed unless its own proof
  packet passes.

Primary child evidence: Items 26, 34, 35, 50, 69-71, 73, 82, 86, 105, 115,
125, 134-138, 145, 147, 151, 153, 160, 168-170, 177-184, 224, 228, 230-233,
263, 266-269, 297-301, 314, 315, and 317.

## Phase 6 — P1 Executable Experiment Queue And Learning Loop

- [ ] Require every queued experiment to specify an executable command,
  immutable input/corpus/release hashes, owner, hypothesis, primary and
  protected metrics, minimum sample, decision threshold, expected artifacts,
  timeout/resource budget, and terminal disposition.
- [ ] Execute queued work from isolated candidate directories; a failed or
  interrupted experiment cannot mutate serving artifacts or block capture.
- [ ] Record resolved, rejected, regressed, inconclusive, and superseded
  outcomes so the queue measures learning rather than the count of generated
  ideas.
- [ ] Trigger retraining from verified drift/skill evidence, but require the
  same immutable release and promotion gates as a manually initiated candidate.
- [ ] Promote data acquisition/backfill tasks when missing coverage overlaps
  uncertainty, model-market disagreement, novel regimes, or economic exposure;
  labels arrive automatically and do not need an active-labeling program.

Primary child evidence: Items 69, 85, 104, 108, 113, 115, 125, 163, 165, 182,
198, 207, 262, 271, 293-298, and 308.

## Phase 7 — Staged Production Gates

### Shadow gate — production operation, zero capital

- [ ] Phase 0 integrity/parity exit is PASS for the exact release.
- [ ] Immutable manifest, atomic promotion, and rollback drill pass.
- [ ] Three consecutive clean active days pass under one release identity with
  all 12 markets countable and capture SLOs clear.
- [ ] Seven unattended daily/nightly cycles pass inside SLA.
- [ ] Storage/restore and 30-day headroom gates pass.
- [ ] The system remains credential-free/order-disabled in this stage.

### Paper gate — frozen challenger evidence

- [ ] The shadow gate remains continuously PASS.
- [ ] The frozen challenger completes at least seven forward days / 84
  countable market-days and clears the challenger exit criteria.
- [ ] Paper execution uses current exchange-economics, real two-sided book
  depth where required, after-fee/after-slippage accounting, settlement
  reconciliation, and countable current-release evidence.
- [ ] Any stricter existing paper-duration, fill-count, or clustered evidence
  gate remains binding; Item 321 cannot lower it.

### Capital canary gate — deferred and fail closed

- [ ] Complete a second independent forward window of at least 14 settled days
  after the candidate/release is frozen.
- [ ] Prove either a weather-only market-beating lane or a predeclared residual
  edge without contaminating claim lanes.
- [ ] Produce at least 100 executable settlement-scored paper fills with
  positive net P&L after fees, slippage, depth, and adverse-selection costs,
  plus date/market-clustered uncertainty and a market/no-trade benchmark.
- [ ] Implement and verify authenticated secret-store access, read-only account
  preflight, idempotent order keys, place/cancel/replace, private-stream
  acknowledgement, position/order reconciliation, cancel-all/dead-man control,
  tiny hard caps, correlated-exposure limits, and health-triggered demotion.
- [ ] Require a reviewed manual authorization for the exact release, account,
  markets, budget, caps, and expiry. No general live permission is implied.
- [ ] Automatically demote to paper/shadow on release mismatch, data/capture
  degradation, reconciliation failure, drawdown/risk breach, stale economics,
  or any production-readiness blocker.

Primary child evidence: Items 44, 45, 47, 67, 162, 164-167, 209, 214, 234-241,
256-261, 264, 269, 273-285, 292, and 300.

## Explicit Non-Goals Until Their Gate Opens

- No credentials, authenticated order submission, or capital exposure before
  the capital-canary gate.
- No promotion of Item 224 v0.1 or continuous-density HGB while quarantined.
- No market/CLOB signal counted as weather-only proof.
- No broad source/feature expansion merely because data is available; Items
  32, 185, 188, and 189 proceed only when the canonical scorecard identifies a
  direct blocker or a predeclared experiment has budget.
- No deletion of canonical tapes before off-machine copy and restore proof.
- No reopening/reimplementation of COMPLETE child items merely to duplicate
  their software. Reopen only when their accepted evidence is specifically
  invalidated; otherwise consume their artifacts and add missing rollout proof.
- Item 67's authenticated adapter remains deferred until all earlier stages
  pass.

## Verification Surface

New modules/commands may choose their final package boundaries during
implementation, but the canonical operator surface must be documented and
must generate the parent artifacts listed above. Verification must include:

```powershell
python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint
python -m weather.reporting.fleet.fleet_observability report --strict
python -m weather.reporting.data_quality.data_retention_inventory
python -m weather.operations.daily_refresh status
python -m weather.operations.nightly_retrain status
python -m compileall -q app src tests tools/research
python -m pytest -q
```

The implementation must also add focused tests for leakage rejection,
probability partitions, variant/release grouping, live prediction coverage,
captured-input replay/serve parity, candidate-only writes, manifest hash
verification, atomic promotion, rollback, market-day-boundary cutover, capture
resource isolation, append-only clean-day/cycle ledgers, point-in-time folds,
and capital-gate fail-closed behavior.

Acceptance: Item 321 may be marked COMPLETE only when the canonical
`production_readiness_gate` identifies the exact immutable release and reports
the capital-canary stage PASS; all parent artifacts are current, hash-linked,
and independently reproducible; the live-variant scorecard and point-in-time
validation are leakage-free and parity-clean; capture, unattended-cycle,
storage/restore, challenger, paper-execution, and risk/reconciliation evidence
meet this item and every stricter child threshold; and a reviewed, tiny,
expiring capital canary has completed without bypassing or weakening any gate.

Until then, the highest cleared stage is the only permitted operating mode.

Related: Items 20, 24, 35-37, 44-48, 50, 67, 69-73, 83, 85-89, 101, 106,
108, 112-118, 124-126, 131, 134-145, 147, 152-163, 168-179, 182, 187, 198,
203, 208-217, 224, 229, 233, 240-245, 254, 262-269, 282, 286-290, 293-300,
305, 307, 308, 312, 314, 315, 319, and 320.
