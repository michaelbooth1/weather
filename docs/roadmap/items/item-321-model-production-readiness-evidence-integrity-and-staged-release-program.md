# 321. Model Production Readiness, Evidence Integrity, And Staged Release Program [OPEN 2026-07-16 - BOOTSTRAP SOURCE CONTRACT FIXED; REAL RETRAIN/SHADOW/PAPER/CAPITAL GATES OPEN]

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
post-settlement label feature, Item 187's original permutation-evidence leg
included its generated target (the evidence has since been regenerated under
the shared leakage policy), the density lane collapses in live inference relative to
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
- Item 187's contaminated June 23 permutation bundle remains non-countable,
  but its July 12 leakage-safe replacement and narrow Austin/Dallas/Houston
  radiation gate now pass. This does not create a broad all-market claim.
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

- [x] Regenerate the Item 187 input-significance/permutation bundle under the
  shared fail-closed feature-safety policy; rerun its gate and explicitly mark
  the contaminated June 23 permutation artifact non-countable.
- [ ] Regenerate every Item 224-derived replay, hourly, 10-minute, location,
  promotion, Item 160, proof-packet, and objective-scoreboard artifact under a
  new clean variant identity. Never overwrite or rehabilitate v0.1 as if its
  historical proof remained valid.
- [x] Add a generic candidate-contract audit that rejects target, outcome,
  settlement, settlement-distance, winner, post-event, retrospective casebook,
  and label-gate fields from model, calibration, guardrail, route, and feature-
  hash inputs.
- [x] Require the leakage audit to inspect derived hashes/feature-family
  manifests as well as visible column names, with input hashes and rejected
  field reasons persisted in the candidate packet.

### Canonical live-variant settlement scorer

- [x] Implement one canonical live-tape settlement scorecard from
  `variant_predictions_long.csv`, joined to canonical settlement labels and
  grouped by `variant_id`, release identity, market-day, snapshot/cutoff, and
  mutually exclusive band partition.
- [x] Report live prediction coverage, unsupported-runtime skips, duplicate or
  collapsed variant identities, missing bands, exactly-one-winner validity,
  finite/in-range probabilities, probability-partition sum error, Brier, log
  loss, ECE, ranked probability score, top-band hit, winner rank, and current/
  market deltas.
- [x] Require 100% eligible live prediction coverage and zero unsupported-
  runtime skips for any candidate that can satisfy a release gate.
- [x] Keep weather-only, market-only, market-informed overlay, predeclared
  residual-edge, and trading lanes separate in both row schemas and summaries.
- [x] Make all rank/RPS/distribution grouping include `variant_id` and release
  identity so multiple candidates can never form one synthetic partition.

2026-07-12 scorer implementation: the canonical v0.1 scorecard now treats the
sibling `snapshots_long.csv` tape as the independent expected snapshot/band
universe. A missing whole snapshot, band, or variant partition is materialized
as explicit missing evidence; unexpected snapshots/bands, duplicate compact
partitions, inconsistent child configuration, simplex failure, invalid
settlement, missing immutable release identity, or silent child failure blocks.
Headline metrics weight market-days equally, expose equal-fleet-date estimates,
and bootstrap whole fleet dates; snapshot-weighted values remain diagnostic.
Daily refresh and the CLI process one tape/sibling pair at a time under file and
aggregate byte limits. The parent release gate requires the sibling contract,
nonempty frozen expected variants, 100% snapshot and prediction coverage, and
zero missing/unexpected partitions. Focused scorer/daily/parent verification
passes `127` tests plus `2` subtests. Historical v0.1 tapes still lack immutable
release IDs and correctly remain non-production evidence; no real tape was
laundered into a PASS.

### Replay/serve parity and density disposition

- [x] Capture the exact point-in-time inputs required to reproduce every served
  prediction, then compare captured-input replay with the served probability
  partition under the same release manifest.
- [x] Fail promotion if replay and served probabilities, band identities,
  routes, postprocessing, or skip decisions exceed declared deterministic
  tolerances.
- [x] Diagnose continuous-density HGB live Brier/log-loss collapse by checking
  feature order, missing-value behavior, units, band integration, calibration,
  artifact hash, and serving-route parity.
- [ ] Repair and requalify density on untouched data or formally retire it from
  active/shadow registries. It cannot remain a nominal candidate with known
  live failure.

2026-07-12 pipeline integration: daily refresh and nightly retraining now run
the canonical captured-input replay/serve comparison after resource admission
and before promotion, active-variant replay, candidate preparation, or other
heavy children. Missing, unreadable, stale, future-dated, release-mismatched,
manifest-mismatched, or non-PASS inputs block that work. Both pipelines write
the canonical production-readiness JSON/Markdown as their literal final,
read-only status step and attest that the active pointer was not mutated.
Focused verification passes `39` scorer/parent tests, `26` nightly tests, and
`95` daily tests plus `2` subtests. This is orchestration evidence only; the
Phase 0 exit remains open until a real immutable release produces fresh,
matching captured-input replay evidence.

2026-07-11 density disposition evidence: the bounded existing-tape diagnostic
in `data/backtest/item35_density_live_replay_parity_diagnostic.json` and `.md`
reproduces two concrete missing-context defects. Toronto C bands were integrated
with the live F fallback (maximum recorded/canonical delta `0.9995817940`), and
Atlanta F feature values were canonicalized through the implicit Toronto/C
market default (maximum delta `0.1920051927`). Artifact hashes match; repaired
code and the canonical captured-snapshot calculation match with maximum delta
`0.0` on both unit families. The route now injects registered market/unit
context, derives replay-equivalent floor/lock-in context, and shares density
band postprocessing. The registry lane is shadow diagnostic-only,
non-headline, and non-countable for promotion; explicit diagnostic live capture
remains enabled so fresh parity tape can be collected without laundering it
into evidence. The second checkbox stays open:
fresh immutable-release live/captured-input parity plus untouched
fleet-date-blocked requalification is still required, or the lane must be
retired.

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

- [x] Train into an immutable candidate directory, never directly into the
  active serving path. Candidate artifacts remain unservable until the exact
  candidate packet passes.
- [x] Create `artifacts/releases/<release_id>/release_manifest.json` with the
  release ID; code commit and source fingerprint; dirty-state attestation;
  model, imputer, calibrator, feature schema, postprocessor, route, registry,
  location/config, and settlement-rule hashes; Python/sklearn/direct dependency
  versions; training/evaluation corpus hashes and date bounds; expected live
  runtimes; parent release; and rollback target.
- [x] Hash-verify the complete release before deserializing or serving it.
  Missing, corrupt, stale, unregistered, or version-incompatible manifests deny
  ML serving and trading rather than falling back to an unverified artifact.
- [x] Promote atomically by switching a single reviewed release pointer only
  after all gates pass; do not copy partially written files into active paths.
- [ ] Implement and test one-command rollback to the last known-good immutable
  release, including coordinated loop restart and release-identity proof.
- [x] Cut over all collection/prediction processes only at a market-day
  boundary. A market-day cannot mix release identities and remain countable.
- [x] Keep GitHub/nightly builds candidate-only: tests and gates run first,
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

2026-07-12 release-mechanism update: candidate outputs are path-guarded away
from active artifacts; immutable manifests, semantic contracts, corpus lineage,
route tables, settlement rules, atomic pointer promotion, boundary proof, and
rollback are implemented and adversarially tested. Serving verifies the entire
release graph before any deserialization. The graph freezes seven per-market
base roles plus shared afternoon/family-secondary calibration, rejects omitted,
swapped, stale, route-substituted, partial, or global-fallback roles, and loads
only the routed HGB after a second hash check. Snapshot construction and
persistence must share the exact verified bundle. A pointer change is
restart-required and cannot create mixed in-process serving.

This is mechanism evidence, not a release claim. There is still no active
release pointer or production release directory. The one-command rollback
checkbox remains open because a real coordinated worker restart, restored
release-identity proof, and health drill have not been executed.

2026-07-13 rollback-drill readiness: the reviewed lifecycle rollback command
now verifies the recorded prior release, atomically replaces the pointer,
re-reads the resulting pointer/release identity, emits that hash-linked proof,
and writes `data/backtest/release_rollback_drill.json`. The initial record is
explicitly pending and includes target/timing fields plus a structured manual
coordinated-restart and health completion surface. Synthetic release tests
cover the pointer, proof, record, protected output path, CLI behavior, and an
injected post-swap write failure. A self-hashed pre-swap journal makes that
partial success recoverable by rerunning the same command without toggling the
pointer. The checkbox remains open until an actual release permits the
coordinated restart and post-restart health drill to run.

## Phase 2 — P0 Resource-Isolated Shadow Operations

### Capture isolation, sharding, and identity

- [ ] Run snapshot, observation-trigger, and CLOB capture independently from
  replay, promotion, training, Parquet conversion, and large report jobs, with
  explicit CPU/memory/I/O budgets and backpressure.
- [x] Shard or concurrently capture markets so one slow provider/market cannot
  stretch a fleet iteration beyond the freshness SLO.
- [ ] Require p99 CLOB book age below 120 seconds normally and below 30 seconds
  near close, plus zero material snapshot/CLOB gaps on countable days.
- [ ] Coordinate snapshot, CLOB, trigger, maker, taker, and dashboard workers on
  one release identity and one configuration fingerprint.
- [ ] Add automatic health-based restart and rollback escalation.
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
- [x] Persist a clean-day ledger and unattended-cycle ledger that cannot be
  reset by rewriting the latest status file.

2026-07-11 append-only ledger contract update: Item 321 now has standalone
`weather.operations.production_evidence_ledgers` commands for `clean-day`,
`unattended-cycle`, and `verify`. The JSONL chains use exclusive writer locks,
durable append/flush/fsync, monotonic sequence numbers, previous-entry and
canonical entry hashes, source-file SHA-256s, and immutable entry keys.
Re-appending byte-equivalent evidence is an idempotent no-op; changing an
existing date is a hard conflict rather than a rewrite. Atomic JSON/Markdown
summaries compute only the latest consecutive target-date suffix under one
release, matching the three-day and seven-cycle parent-gate fields.

The current summaries correctly remain `BLOCK`: `0/3` clean days and `0/7`
unattended cycles. No July 11 fleet snapshot was appended because it is not a
closed frozen day and lacks singular immutable-release binding and the required
CLOB p99 proofs. Existing daily/nightly files also lack positive scheduled-
invocation, zero-lock-repair, and per-stage SLA attestations. Producer
integration must add those fields before the forward window starts; mutable
latest-status files will not be retroactively laundered into ledger PASS rows.
The checkbox remains open until real append-only entries establish the required
streaks.

2026-07-12 fail-closed producer-provenance implementation: future daily Stage
A, daily Stage B, and nightly status artifacts now carry OS-attested invocation
proof, exact instrumented stale/forced lock outcomes, explicit manual/resume
state, a predeclared stage SLA with measured duration, and an active release ID
and manifest hash only after the serving bindings verify against the immutable
release. On Windows, a countable invocation requires the named scheduled task
to exist, be enabled and running, have exactly the registered executable,
arguments, and working directory of the current process contract, and have a
fresh scheduler last-run/start correlation. The proof records hashes of both
the exported task definition and normalized invocation contract. Non-Windows,
manual, dry-run, resumed, forced/stale-lock, disabled/mismatched task, missing
release-binding, and SLA-breach cases fail closed. Both ledger commands now
refuse to append any entry whose complete evidence is not exact `PASS`.

The daily and nightly registration scripts declare these task contracts and
four-/eight-hour stage SLAs, but no task was registered, enabled, restarted, or
run as part of this implementation. The existing host definitions therefore
remain non-countable until an operator deliberately re-registers them. A
read-only scheduler audit found Stage A enabled/ready but still on the old
action contract, while Stage B and nightly were disabled and also predated the
new flags. No ledger row was appended, so the honest forward counts remain
`0/3` clean days and `0/7` unattended cycles.

2026-07-12 bounded snapshot-capture implementation: the July 11 scheduled tape
shows why a heartbeat alone is insufficient. All 12 markets had repeated
scheduled gaps above 15 minutes; the worst per-market gaps were approximately
43-48 minutes, and recorded serial fleet sweeps reached `33.147`, `29.187`,
`25.843`, and `22.977` minutes under host pressure/re-adoption even though a
freshly restarted healthy sweep later completed in `1.148` minutes. The managed
snapshot loop now admits markets in the existing due/oldest-first order into at
most three isolated child process trees. For the 12-market default, each child
is capped at 120 seconds and 1536 MiB while the whole pass has a 540-second
budget; the timeout is tightened automatically if worker count or fleet size
would require it. A slow or failed market is killed and scored as its own
explicit result while other worker slots continue.

The implementation preserves the parent runtime fingerprint in every child,
falls back to already-loaded inline capture during stale-code re-adoption, uses
the existing per-event `SnapshotStore` lock against trigger-loop races, emits
five-second parent heartbeats plus active/queued/completed market status, and
shares an atomic Open-Meteo cooldown file across isolated children so provider
retry/backpressure is not reset at every process boundary. Synthetic timing
tests prove three-way overlap, FIFO admission, slow-market isolation, timeout
tightening inside the fleet budget, failure isolation, process-tree/memory
containment metadata, and fail-closed runtime mismatch. Focused verification
passed (`36` capture/source-budget tests, `61` collection robustness/loop
supervisor tests, and `12` process-tree containment tests). A fresh-process
runtime-scope probe also confirms that the batch runner, long-job containment,
and model-source budget modules are all inside the recorded fingerprint. This
is implementation evidence only: the running loop was not manually restarted
or rescheduled for this change, and no July 11/12 day is claimed clean.
Deployment requires a controlled current-release loop re-adoption followed by
the still-open three-day forward proof.

The scheduled loop did auto-adopt the sharded implementation late on July 11.
Its first 12-market pass completed in about `61` seconds with `3` active workers
and no timeout, but five children hit the `1536 MiB` cap while widening existing
CSV headers because `SnapshotStore.append_csv` materialized all prior rows.
Containment correctly killed only those child trees. The writer now streams the
old CSV through a unique fsynced temporary file and atomically replaces it; a
non-materializing iterator test and the collection suite pass. Release serving
also stopped eagerly deserializing all-market HGBs in every child. The active
window ended before another production-isolated batch could verify both fixes,
so this is not a clean-day proof.

2026-07-12 CLOB critical-path isolation implementation: read-only live status
showed fast-mode fleet iterations of `108.5-114.4` seconds. Each iteration
captured `264` raw books but also reprocessed `63,624` price-history rows across
12 markets for only `493` new points and `63,131` duplicates, then sampled 18
WebSocket messages and rebuilt 15,895 derived feature rows. The defaults had
both optional enrichment streams enabled inside the critical loop.

The managed CLOB loop is now raw-book-only and rejects any attempt to enable
price history or WebSocket capture in that mode. Its default fleet path uses
bounded parallel per-market capture, a 20-second market deadline, strict
`<120s` normal and `<30s` near-close fleet contracts, per-market timeout/error
visibility, runtime identity, and a non-overlap lock so a timed-out worker
cannot race a later tape writer. Price history, WebSocket sampling, and derived
features have a separate `enrichment-loop` mode with a 15-minute default
cadence, independent writer/status/diagnostic artifacts, per-token and
per-market failure accounting, and an explicit declaration that it neither
blocks nor counts toward raw-book freshness. Enrichment never writes raw token
or book tapes; fleet observability reads its optional-stream health separately.
Synthetic adversarial tests cover deadline return, slow-market isolation,
overlap prevention, partial history failure, raw-tape non-mutation, legacy
mixed-loop degradation, and independent status/runtime identity.

This is implementation evidence only. At `03:00 UTC` the pre-existing
supervisor automatically detected the changed runtime identity and attempted
to re-adopt the raw-only loop without any manual process or scheduler action.
That first detached process failed before capture because its managed command
still emitted legacy enrichment flags that the raw-only CLI had removed. The
launcher/parser mismatch was corrected and an exact-command-through-parser
regression test was added; the supervisor was left to its normal recovery
backoff rather than restarted manually. The p99/zero-gap checklist remains open
until a current-release forward tape proves the normal and near-close
thresholds.

The supervisor subsequently auto-adopted the corrected command and the final
cross-process tape guard without operator action. Read-only status at
`03:15:51Z` showed 13 consecutive raw-only 12/12 iterations under PID 40488,
`0.8` seconds for the latest and maximum recent fleet pass, 12 workers, a
20-second per-market deadline, zero failed/slow/timed-out markets, zero
consecutive errors, and the strict 30-second fast-mode contract clear. Raw
token/book appends are now serialized by a filesystem-backed per-event lock;
contention blocks only that market without touching its tape, and enrichment
uses the same guard before consistency-sensitive reads. This remains dirty,
after-hours implementation evidence and does not count toward p99 or the clean
forward-day gates.

2026-07-12 heavy-work admission enforcement: daily refresh now evaluates and
persists an exact consumer-specific resource receipt before active-variant
replay or promotion, and nightly does so before candidate preparation,
training, replay, or promotion. A live capture host must return and enforce
`DEFER` before launching a heavy child; an explicitly configured offline host
may return `ADMIT` only with zero live loops and passing memory/disk reserves.
Proof-write failure, missing/stale evidence, workload/consumer mismatch, or an
incoherent decision blocks. The parent gate validates the enforced receipt
rather than fabricated sharding/topology booleans. Focused verification passes
35 tests. No real pipeline was invoked, and the current host correctly remains
blocked while live loops are active and 30-day disk headroom is absent.

Ledger focused verification:

- `python -m pytest tests/operations/test_production_evidence_ledgers.py tests/operations/test_schema_registry.py -q`
  passed with `15 passed`.

Primary child evidence: Items 16, 17, 42, 57, 101, 108, 112, 118, 124, 152,
157-159, 161, 210-212, 216, 229, 282, 299, 305, 307, 312, 319, and 320.

## Phase 3 — P0 Storage, Archive, And Restore Proof

- [ ] Backfill and validate `event_day_manifest.json` for every active and
  retained historical market-day folder; zero-manifest inventories are not an
  acceptable rollout state even if the writer implementation exists.
- [ ] Complete incremental validated Parquet conversion or record an explicit
  blocker for every retained eligible closed day. High-byte readers must prefer
  validated Parquet with source-mode provenance and text fallback.
- [x] Keep raw canonical evidence immutable; store derived point-in-time tables
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

2026-07-12 bounded rollout evidence: manifests now cover `48` complete folders
for fleet dates June 6-9. The newest 36 were written in three bounded date
batches; full verification with file hashes, row counts, extra-file detection,
and internal manifest hashes reports `36/36 PASS`, 22 inventoried files and 11
canonical-evidence files per folder, and zero unclassified files. This advances
the rollout but does not satisfy the all-retained-folders checkbox: the snapshot
root contains 441 event folders, including earlier Toronto-only history and
later fleet dates.

The Google Drive transport/restore pilot is also deliberately narrower than
the production gate. One June 6 Atlanta archive was uploaded, fetched back, and
verified byte-for-byte: local and remote-restored SHA-256
`c24503e700d40417db8b5c42760e464d09c182a4dc2358e9992fe7bbfd4aa32c`,
with all 22 manifest files matching. It proves the transport path only; it is
not recurring coverage, does not reproduce a release input or score, and does
not establish RPO/RTO ownership.

A bounded headroom probe now reuses the exact hashed prior full inventory
instead of rescanning 3.28 million files on the live host. Source SHA-256
`9e0e531f9113111b7f0896be04ed101f7b5777f405531429b781207abe09c4b4`
records `64,500,349,845` recent bytes over 24 hours. With current free space
`435,879,149,568` bytes, the current proof is honestly `BLOCK` at `6.758` days
of observed-write-rate headroom, `23.242` days short of policy. The source was
47.19 hours old and passed the 168-hour trust bound. The critical CLOB loop's
per-minute price-history/WebSocket enrichment is a confirmed write/I/O target;
canonical deletion is not an acceptable remedy.

The bounded global manifest/archive index now makes the remaining denominator
explicit without walking source tapes or opening Parquet. As of 2026-07-11 it
reports `BLOCK`: `48/429` closed folders have structurally valid event-day
manifests (`11.19%`) and `248/429` have self-hash-valid, structurally valid,
declared-PASS archive manifests (`57.81%`), but `0/429` have fully linked archive
evidence. No archive links to the newer event-day-manifest hash; only `188`
cursor entries link to the current archive hash. The cursor is `INVALID` because
closed-folder coverage and the scan boundary are incomplete; its 344 entries
contain `188` converted, `57` skipped, `10` blocked, and `89` failed rows.
Backup and restore remain `0/48 PASS`. The audit records input/index digests and
its own SHA-256. These are rollout blockers, not a reason to delete canonical
evidence.

Primary child evidence: Items 15, 25, 60, 124, 131, 154, 159, 171, 172,
176, 201, 203, 243-245, 286, 287, 289, and 290.

## Phase 4 — P1 Point-In-Time Data And Evaluation Contract

### Canonical analytical table

- [ ] Materialize a point-in-time analytical contract keyed by
  `(target_date, market_id, cutoff_or_snapshot, band, variant_id, release_id)`
  with source payload/hash/provenance, feature-availability time, label quality,
  claim lane, release identity, countability, and replay/serve status.
- [x] Preserve raw inputs unchanged; perform cleaning/normalization in derived
  processed tables with explicit transformation/version metadata.
- [x] Treat fleet dates and market-days as the independent evidence units.
  Snapshot density, band count, and variant multiplication cannot increase the
  effective independent sample size.

### Validation design

- [x] Use nested rolling-origin outer folds grouped by the entire fleet target
  date, not independent market-day/band rows.
- [x] Apply a predeclared 3-7 day embargo where persistent weather regimes can
  leak temporal information between train and evaluation.
- [x] Fit feature selection, scaling/imputation, model training, calibration,
  postprocessing, and regime/router selection inside each training fold.
- [x] Weight market-days equally and report date-clustered bootstrap confidence
  intervals alongside point estimates and per-market/regime results.
- [ ] Lock the most recent 14-day evaluation window before candidate selection;
  it cannot be used to choose features, routes, hyperparameters, or thresholds.
- [x] Make the standard 14-day evaluator stream/aggregate by market-day rather
  than materializing the raw corpus, and always report selected labels,
  excluded days/reasons, market-days, fleet dates, and runtime identities.
- [x] Target stale/failed source status below 5%, explain every training-
  excluded row/folder, and keep incomplete/quarantined labels diagnostic-only.

2026-07-12 bounded contract implementation update: the new
`weather.reporting.validation.point_in_time_evaluation` owner and
`docs/operations/POINT_IN_TIME_EVALUATION.md` runbook now define four
registered v0.1 artifacts: the canonical analytical row contract, bounded
materialization manifest, nested rolling-origin validation plan, and streaming
evaluation report. The row contract uses the exact six-field key above and persists
canonical source-payload JSON plus SHA-256, archive/text-reader provenance,
feature-availability and prediction timestamps, settlement quality and
countability, one of four isolated claim lanes, replay/serve parity, source
quality, transformation version, release identity, score fields, and runtime
identity. Missing lineage is rejected rather than inferred, and every artifact
uses a validated timezone-aware `generated_at_utc` field.

The materializer reads through the validated Parquet/gzip/text fallback owner,
retains at most one bounded market-day frame, writes only an atomic derived
Zstandard Parquet projection, and emits a hash/row-count/input-provenance
manifest. The fold builder keeps whole fleet dates together, applies a
predeclared 3-7 calendar-day embargo, restricts every inner fold to its outer
training dates, and exposes fresh fold-local hook factories whose `fit` calls
cannot receive validation rows. The evaluator locks the calendar window before
scoring, reduces bands to cutoffs and cutoffs to equally weighted market-day
summaries, reports both equal-market-day and equal-fleet-date estimates, and
uses a seeded bootstrap that resamples complete fleet dates. Weather-only,
market-benchmark, market-informed, and trading evidence are never pooled.
Any duplicate or excluded row poisons its complete cutoff, and the evaluator
fails closed when stale/failed source rows are at or above the declared 5%
ceiling.

Focused synthetic verification covers payload tamper/future-feature rejection,
text-reader provenance and raw immutability, missing-release blocking,
whole-date nested folds and embargo bounds, training-only fit receipts, lane
isolation, unequal market-day/fleet-date weighting, deterministic date-cluster
intervals, parity/quarantined-label exclusion, and calendar-window locking:

- `python -m pytest tests/reporting/test_point_in_time_evaluation.py tests/operations/test_schema_registry.py -q`
  passed with `19 passed`.

The checked Phase 4 boxes above are implemented mechanism contracts; the
materialization and locked production-window boxes remain open. No full retained
corpus was materialized, no production 14-day window was locked, no candidate
was selected or trained with these folds, and no forward challenger evidence
was created. Existing legacy
rows that lack immutable `release_id`, point-in-time availability timestamps,
countable label lineage, or runtime identity require a canonical join/backfill;
they must not be silently upgraded. Promotion/daily/nightly integration and
per-market/regime production reports are also still outstanding.

A real plan over 36 promotion-countable fleet dates (2026-05-28 through
2026-07-10) passes with 19 outer folds, a three-day calendar embargo, and nested
training-only inner folds. A bounded Atlanta July 10 materialization pilot read
1,496 source rows and accepted zero: every row lacks immutable `release_id`.
That `BLOCK` is the intended proof that millions of legacy rows cannot be
silently upgraded into release-bound point-in-time evidence.

Production candidate contracts now require four immutable PIT roles: the
Parquet corpus, materialization manifest, rolling validation plan, and streaming
evaluation. Candidate verification inspects the full corpus and requires
self-hashed fit receipts for feature selection, scaling/imputation, model,
calibration, postprocessing, and regime routing in every outer/inner fold. It
also requires a contiguous 14-day window locked before scoring, isolated claim
lanes, fleet-date-clustered intervals, exact candidate/release/corpus hashes,
all 14 weather-only dates under one identity, and evidence no older than seven
days. Research-only candidates forbid these roles and cannot be promoted or
served. Immutable release re-verification checks the qualified hash graph
without loading PyArrow into serving/snapshot processes.

2026-07-13 nightly production-mode integration update: `nightly_retrain` now
keeps `research_only` as its default and requires an explicit bounded source
for production mode. Production prelocks the candidate-independent selection
universe before any candidate-dependent work, then excludes all 14 locked dates
and every out-of-universe date from pooled feature/source-reliability priors,
family calibration/trust, pooled fitting, and routing selection. The latest
source target must be no more than seven days old when locked. The pooled
training path emits six chained,
self-hashed stage receipts for every actual outer/inner fit scope plus a final-
refit receipt bound to the serialized serving bundle. Qualification freshly
replays that exact model, attaches settlement evidence only after scoring, and
freezes the Parquet corpus, materialization manifest, rolling validation plan,
and streaming evaluation under one candidate graph. Candidate construction and
immutable-release verification both recheck the exact model, calibration,
routing artifact, and normalized route identities. Source/replay work is capped
at 60 market-days and retains one raw market-day at a time under declared row,
fold-scope, batch, and private-memory bounds.

The software integration is complete, but the two Phase 4 production-evidence
boxes remain open. This work did not run a real retrain, materialize a retained
production corpus, or create a scheduled candidate/evaluation window; the next
scheduled production-mode retrain must supply that operational evidence before
either box can close.

2026-07-14 first-serving-identity bootstrap update: the categorical
research-only promotion/serving prohibition above remains the default. One
reviewed exception can establish pointer sequence 1 when no active pointer
exists. It requires the explicit `--bootstrap-first-release` flag, an otherwise
valid research-only immutable release with null `rollback_target`, the usual
fresh boundary proof, and a promotion decision whose `release_kind` is exactly
`serving_identity_bootstrap`. The pointer binds the decision hash, boundary
hash, reviewer, origin action, and origin sequence as self-hashed provenance.
The same flag cannot authorize a replacement research-only release after an
active pointer exists.

This bootstrap is release-bound research infrastructure, not production
qualification. Serving exposes `candidate_mode=research_only` and
`production_capable=false`; capital-canary readiness and maker `live-pilot`
therefore fail closed while shadow and paper identity evidence can proceed. A
later production promotion preserves the bootstrap kind and origin proof on
the previous-release edge, and rollback restores both rather than converting
the release into an implicit production identity. Promotion still requires a
coordinated restart. Because the serving gate is loaded by long-running loops,
landing this contract change also consumes the normal fleet-roll budget; it is
not a roll-free documentation-only exception. This does not close either open
Phase 4 production-evidence box.

2026-07-15 first-inactive-production-release bootstrap update: nightly's
unconditional pre-candidate parity check created a circular dependency on an
active release identity. The new explicit
`--bootstrap-first-inactive-release` contract waives only that impossible
pre-release check and only when candidate mode is `production`, immutable build
is enabled, the releases root is absent/empty, the active pointer and release
parent are absent, and neither generic parity skip nor parity inputs are
configured. All offline point-in-time, leakage, semantic, clean-source, and
promotion-refresh gates remain binding.

The PASS contract is self-hashed and frozen into release lineage. After the
one immutable directory is copied, nightly independently verifies every
artifact and manifest hash, production capability, null parent/rollback
target, the one-release store inventory, and pointer absence. The result has
`activation=NONE` and explicitly denies promotion, serving, and live fallback;
the whole-run finalizer rechecks pointer absence. Ordinary runs and invalid or
ambiguous bootstrap requests still fail closed before heavy children. Focused
synthetic coverage includes contract tampering, non-first stores, conflicting
flags/evidence, research mode, parent binding, pre-child denial, and a complete
production freeze with no pointer. This closes the bootstrap ordering defect in
software, not the open operational evidence: no real production candidate or
release was created, and exact release-bound parity plus forward qualification
are still required.

2026-07-16 candidate-independent source closure: the first-release bootstrap
still had a second circular contract. Production preselection reused the full
candidate-scoring row schema, so every otherwise usable historical row was
rejected for missing `release_id`; supplying a syntactically valid old source
would also have let the ambient model decide which rows existed before the
lock. Production preselection now requires the separate
`production_point_in_time_preselection_source_v1` projection. It enumerates
every manifest-pinned snapshot/band row directly from the bounded captured
tape, joins only the manifest-pinned settlement label, and stores coordinates,
capture/prediction-boundary times, countability/quality, lane, and label. Model,
variant, release, probability, runtime, and payload fields are physically
absent. The old generic materialization manifest is rejected in production.

The producer caps the request before input I/O, reads one market-day at a time,
limits tape/replay bytes, fields, lines, records, rows, Arrow batches, and total
market-days, rejects reconstructed/unsettled/promotion-countable admission,
requires paths below the configured snapshots root, verifies source mutation,
exactly one winning band per snapshot, and exact replay/source market-day and
snapshot/label inventories. Exclusive output locks reject concurrent writers;
files publish atomically with the manifest last, and consumers require the
complete hash-bound pair. A host crash can leave a fail-closed orphan or lock
that requires reviewed cleanup. The final owner-focused checkpoint passes 105
tests and 23 subtests, with 1 Windows symlink-privilege skip. A real Toronto
June 3 probe
materialized all 231 pinned
rows with zero candidate-dependent fields and an identical 231-row selection
universe. This closes the software source deadlock only; no retained production
corpus, real retrain, inactive release, positive edge result, shadow window,
paper window, or capital permission has been produced.

2026-07-15 artifact-lineage closure refreshed all four tracked artifact
manifests through their
canonical producers. The current LFS object for
`feature_model_hgb_f_pooled_clob_overlay_v0_2.pkl` is now consistently recorded
as SHA-256 `c4eaa40df23a43702cbf3fdecd5be0d190235b0e832653e690b3e8196aabe3bc`
and 211,935 bytes instead of the two stale historical identities. Registry,
externalization, size-audit, and promotion-preflight outputs now agree with the
complete current artifact tree; promotion preflight reports PASS with zero
warnings/errors. Promotion preflight now independently recomputes the
checkout-stable identity of the tracked registry and externalization manifests,
so future byte/hash/classification drift fails instead of being reported PASS;
generation time and checkout mtimes remain diagnostic. The producer also
normalizes its registry reference to a repository-relative path so a worktree
name is not embedded as artifact identity. No model binary was edited or
generated by this repair.

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

- [x] Require every queued experiment to specify an executable command,
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

2026-07-12 queue-contract implementation: an entry becomes eligible only when
its self-hash-valid `executable_experiment_manifest_v0.1` is also materialized
under the explicit repository root. The verifier requires exact JSON argv
(never a shell string), an allowlisted `python -m weather.*` module with one
explicit candidate-only output root, actual on-disk release/corpus/input bytes
matching their hashes and schemas, absent expected outputs, owner/hypothesis,
primary and protected metrics, an independent sample floor, a deterministic
decision rule, and CPU/memory/I/O/timeout budgets. Symlink/path escapes fail
closed. Legacy, incomplete, or merely structural entries remain visible with
empty executable argv and are never upgraded by inferred commands or hashes.
A self-hashed result contract defines and validates `resolved`, `rejected`,
`regressed`, `inconclusive`, and `superseded`; invalid legacy results cannot
surface an unverified scientific disposition. The v0.2 queue re-verifies its
own hash, unique IDs, item bindings, and summary at the consumer boundary.
Focused contract/builder verification passes `27` tests with one Windows
symlink-permission skip. Nightly deliberately defers even verified work until
the isolated executor exists, so execution and real terminal-result recording
remain open and the next two checkboxes are not closed by this contract alone.

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
