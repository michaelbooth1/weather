# Agent report - 2026-07-27 workstation account for the recorded output

Status: **MISSION 1 COMPLETE — `recorded_probability` IS
`NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS`. THE MOST
PERMISSIVE CONVEX BLEND FAILS, LAG ZERO WINS FOR EVERY DOCUMENTED LANE,
AND NO FROZEN POSTPROCESS REPRODUCES THE OUTPUT. MISSION 2 DESIGN IS
COMPLETE AT THE RECORDING BOUNDARY; ACTUAL DELIVERY PROOF WOULD REQUIRE
SERVING/CONSUMER INSTRUMENTATION AND STOPS THERE. MISSIONS 3+ OF `-28c`
WERE NOT RUN OUTSIDE THEIR MORNING WINDOW.**

This report executes
`docs/roadmap/workstation-handoff-2026-07-27f-account-for-the-recorded-output.md`
from exact `origin/master`
`4fa47e4a4f0eafa1774670434a7168c14cd37a8d` on topic branch
`codex/workstation-account-for-recorded-2026-07-27f`.

The population, candidate functions, residual tolerance, lag null,
postprocess matrix, authority rule, and serving-design boundary were frozen
before measurement in
`scratch/workstation-research-output/account-for-recorded-20260727f/predeclaration.md`,
SHA-256
`377fcd959f63b9d8f72b5eefc8d1682a7d5625cc4df41312b122d486bc2aff82`.

## Executive verdict

None of the predeclared evaluable functions reproduces all **206,745 raw
rows** within the `1e-12` residual tolerance:

- direct preblend, replay-final, and incumbent identity all fail;
- even a different fitted convex weight on every band row leaves maximum
  error `0.926350`, so recorded is not a convex combination of frozen
  preblend and incumbent;
- lag zero is the unique full-precision minimum on fixed common support for
  preblend, replay-final, and incumbent, so the proposed staleness mechanism
  is rejected;
- all 20 fixed vector candidates plus the terminal-floor diagnostic fail to
  account for the output; and
- the historical corpus supplies one coarse version label but no exact
  artifact, config, code, release, pointer, captured-input, or served-binding
  identity.

The Mission 1 terminal is therefore:

**`NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS`.**

This is narrower than “no possible function exists.” Context-dependent paths
whose required fields are absent, unpredeclared compound lag-plus-transform
functions, and a different artifact/config/code path remain unresolved
possibilities. No frozen evidence identifies one of them as the producer.

## Population and the collision correction

The audit revalidated the complete accepted population:

| Contract | Count |
| :--- | ---: |
| Raw band rows | 206,745 |
| Composite `(market, target date, snapshot)` keys | 18,793 |
| Canonical eleven-band simplexes / rows | 18,791 / 206,701 |
| Same-second collision keys / rows | 2 / 44 |
| Full-timestamp eleven-row capture groups | 18,795 |
| Market-days / markets / target dates | 129 / 11 / 12 |
| Earliest target-day market-local hour cells | 2,962 |

A result-blind implementation review caught an important input fact before
analysis. Each Austin/Dallas collision key contains two identical eleven-row
halves, but each half has preblend and replay-final mass `0.5`, while
incumbent and recorded each have mass `1.0`. The two halves are therefore not
four ordinary probability simplexes.

The audit did not silently renormalize them. Direct identity and alpha
accounting retain all 44 raw rows and all 18,795 capture groups. Lag and
simplex-normalizing postprocesses use the 18,791 canonical simplexes and are
explicitly terminal-ineligible because they do not cover the 44 collision
rows.

## Direct identity

Strict decimal equality agrees with the accepted prior audit: preblend and
replay-final have no identical rows; incumbent has 9,115. The operational
`1e-12` tolerance admits additional nearly equal rows, but no lane reproduces
the corpus.

| Frozen lane | Strict decimal rows | Rows within `1e-12` | Capture groups within `1e-12` | Row MAD | Mean half-L1 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Preblend | 0 | 741 | 0 / 18,795 | 0.078558 | 0.432067 |
| Replay-final | 0 | 768 | 0 / 18,795 | 0.044209 | 0.243148 |
| Incumbent | 9,115 | 10,406 | 2 / 18,795 | **0.027592** | **0.151758** |

Strict whole-partition identity remains zero for every lane. The two
incumbent capture groups in the table are operational `<=1e-12` matches, not
strict decimal identities. Incumbent remains the closest documented lane,
but resemblance is not an identity.

## Implied-alpha accounting

For the 206,077 informative rows, raw
`alpha = (recorded - incumbent) / (preblend - incumbent)` is not a coherent
convex weight:

- 104,618 / 206,077 (`50.77%`) lie inside `[0,1]`;
- median alpha is `3.91e-7`, but the mean is `-0.7241`, with range
  `[-2054.87, 2972.45]`;
- 668 rows have `|preblend - incumbent| <= 1e-12`, of which 607 are
  compatible and **61 are irreducible**;
- denominator counts at `1e-9`, `1e-6`, and `1e-3` are 3,158, 13,460, and
  47,156, confirming that extreme raw alphas often come from near-zero
  denominators; and
- only 2 / 18,795 capture groups have informative-alpha range `<=1e-9`.

The fitted residuals settle the mechanism:

| Fitted convex alpha | Row MAD | Maximum error | Exact rows | Exact capture groups | Mean half-L1 |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Per row | **0.016506** | **0.926350** | 105,574 | 458 | **0.090782** |
| Per capture group | 0.024597 | 0.926350 | 4,695 | 2 | 0.135283 |
| Global | 0.028001 | 0.926939 | 1,004 | 0 | 0.154006 |
| Per market | 0.028012 | 0.926350 | 4,944 | 0 | 0.154066 |
| Per market-local hour | 0.028593 | 0.926518 | 2,970 | 0 | 0.157259 |

The global least-squares alpha is `0.043392`. Market fits range from `0` to
`0.135705`; hour fits range from `0` to `0.145571`. That structure is not
historical authority: every fitted alpha uses recorded itself, and even the
most permissive row-specific convex class fails on many rows. The accounting
conclusion is **`CONVEX_BLEND_CLASS_ELIMINATED`**.

## Temporal lag and its null

The lag sweep tested `0, 5, ..., 180` minutes within the same market-day and
identical band signature. It reported all eligible pairs and a fixed common
support of **16,161 canonical partitions across all 129 market-days**. The
primary metric gives each market-day equal weight.

| Source lane | Lag-0 primary TV | Lag-5 primary TV | Full-precision winner |
| :--- | ---: | ---: | ---: |
| Preblend | **0.441830** | 0.445129 | 0 minutes |
| Replay-final | **0.256814** | 0.269335 | 0 minutes |
| Incumbent | **0.162470** | 0.189514 | 0 minutes |

Positive lags deteriorate immediately. On all-eligible support, coverage falls
from 18,791 partitions at lag zero to 16,161 (`86.00%`) at 180 minutes.
Lag zero is the unique full-precision minimum for every lane:

**`NO_DOCUMENTED_LANE_POSITIVE_LAG_IMPROVEMENT`.**

No stale/carried-forward documented lane survives. The sweep remains
post-hoc and terminal-ineligible regardless.

## Frozen postprocess candidates

The fixed matrix contains direct identities; normalization, `gamma=1.25`,
clipping, duplicate artifact temperature, and duplicate artifact market-bias
for each of the three source lanes; the canonical conservative bridge; its
preblend counterfactual; and the accepted printed-floor diagnostic.

| Candidate | Authoritative rows | Row MAD | Exact groups | Mean half-L1 | Result |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Incumbent + `normalize(gamma=1)` | 206,701 | **0.027580** | 2 | **0.151690** | Incomplete by 44 rows; not exact |
| Incumbent identity | 206,745 | 0.027592 | 2 | 0.151758 | Full coverage; not exact |
| Conservative bridge, replay-final + incumbent | 206,745 | 0.033846 | 0 | 0.186156 | Full coverage; not exact |
| Replay-final + `normalize(gamma=1)` | 206,701 | 0.044200 | 0 | 0.243098 | Incomplete; not exact |
| Replay-final identity | 206,745 | 0.044209 | 0 | 0.243148 | Full coverage; not exact |
| Counterfactual preblend bridge | 206,745 | 0.048027 | 0 | 0.264147 | Diagnostic only; not exact |
| Preblend + clipping/normalization | 206,701 | 0.078552 | 0 | 0.432038 | Incomplete; not exact |
| Preblend identity | 206,745 | 0.078558 | 0 | 0.432067 | Full coverage; not exact |

Duplicate temperature and market-bias transforms are worse than the
corresponding identities. They are already upstream of frozen preblend and
are diagnostics, not evidence of a missing stage. No numeric candidate
reproduces every evaluated partition.

Recorded also assigns more than `1e-9` mass below the accepted printed-floor
proxy in 118 / 124 cases, total mass `24.538691`. That eliminates a
hypothetical **terminal post-blend** hard-floor step on the joined subset. It
does not eliminate an upstream floor followed by incumbent blending.

Support floor, late lock-in, adjacent calibration, and exact configured-blend
re-execution remain unidentifiable because the 46-column export omits their
required context. Disabled density postprocessing, exact-winner, and forecast
centering are identity paths.

## Different artifact or code version

All 141 promotion-manifest market-days carry the same coarse label,
`v0.5.10 HGBC feature-based ML model`, spanning a summed 20,586 snapshots.
Zero of 141 entries carries any of the exact fields needed to name the
producer:

`release_id`, `release_manifest_sha256`, `release_pointer_sha256`,
`artifact_hash`, `model_identity_hash`, `config_hash`, `code_commit`,
`captured_input_hash`, or `served_binding_sha256`.

The current code's matching human-readable version constant is not an
artifact/release binding. A different artifact, config, code build, or
unrecorded transform is the residual explanation, but this corpus cannot say
which.

## Mission 2 - minimal record-only production binding

The current release graph already has strong building blocks:

- `src/weather/release_artifacts.py` produces self-hashed release manifests,
  inventories, routes, actual served bindings, and
  `served_binding_sha256`;
- `src/weather/release_serving.py` verifies the active pointer and returns an
  opaque, sticky release bundle with lineage;
- `src/weather/collection/snapshot_store.py` constructs and persists the
  snapshot from that verified bundle and already has the final
  `long_rows[].model_probability`;
- `replay_inputs.jsonl` records release/pointer/base-binding identity,
  model/runtime identity, captured-input hash, a self-hashed
  `recorded_distribution` mapping; and
- `src/weather/market/worker_release_binding.py` can verify the replay-input
  self-hash, release/day identity, and exact projection from
  `recorded_distribution` to snapshot `model_probability`.

The gap is the authoritative join. `snapshots_long.csv` and
`snapshots.jsonl` do not themselves retain the release/captured-input binding.
`variant_predictions.jsonl` has useful release and input fields but is an
optional sidecar: zero rows are allowed and sidecar failure does not block the
canonical snapshot.

The minimal record-only design is an append-only, self-hashed
`recorded_output_binding_receipts.jsonl` beside the snapshot records. Emit one
receipt per market-day-snapshot capture partition from the **already computed
final long rows**—never by rerunning the model. Publish it only after the
referenced snapshot and replay-input records are durable, making the receipt
their commit marker.

Each receipt needs:

- scope and coordinates: schema, claim scope
  `snapshot_persistence_not_delivery`, status, event/market/target date,
  snapshot ID, full capture timestamp, decision timestamp, and process
  instance;
- vector contract: native unit, canonical ordered band keys/ranges/token or
  condition IDs, exact probability text encoding, count, sum, band-contract
  hash, and ordered-vector SHA-256;
- release graph: release ID, manifest and pointer hashes/generation, sequence
  and production status, artifact/config/registry/code-build identities,
  base binding, bundle fingerprint, and route;
- input graph: feature schema, model identity, runtime identity,
  `captured_input_hash`, replay-input self-hash, and snapshot projection hash;
  and
- receipt self-hash and previous-record/append identity where the tape
  contract supports it.

The verifier must not invoke the model. It must prove uniqueness, canonical
band order and unit, exact text/vector hash, equality to
`snapshots_long.model_probability`, equality to the replay input's
`recorded_distribution`, the release manifest/pointer/binding graph, one
singular identity across the record, and append-only durable publication.
Collision structure must be recorded explicitly rather than silently
normalized.

That evidence would bind a vector to the production **snapshot decision and
persistence boundary** without changing probability computation, selection,
serialization, or delivery.

It would not prove that an API, UI, worker, exchange request, or other
consumer actually received the vector. That stronger claim needs exact
serialized payload bytes/hash, destination, request/idempotency identity,
send result, and acknowledgement captured at the serving/consumer boundary.
No current recording boundary observes all of those. Adding them would touch
the serving path, so this mission stops there and does not design or authorize
that change.

## Admission, receipts, and independent validation

The bounded run made no vendor request, network call, full-book read,
`data/` analytic read, replay, or model fit. `data/` retained two deny-write
ACL entries. The primary admission at 18:54 ET recorded 53.03% committed
memory, 9.99 GiB available physical memory, 53.216 GiB free disk, and no
Python or robocopy activity.

The primary harness self-test and analysis returned `PASS`. A no-import,
standard-library validator independently re-read all 206,745 rows and
recomputed population/collision structure, direct identities, alpha
residuals, the 222-row lag matrix, all 21 postprocess candidates, manifest
identity gaps, and the terminal.

The first independent pass failed after its vector scan at
`target-day hour count`: the validator used the CSV's stored offset instead
of converting capture timestamps through the pinned market-timezone registry.
The failed receipt is preserved. The correction changed only timezone
normalization before grouping/hour/lag; candidate functions, tolerances,
authority, and terminal stayed frozen. A fresh admission was green, and the
retry returned `PASS` with matching results.

This retry was actual sequential vector scan 3 against the predeclared
two-scan resource ceiling. The deviation is explicit in both admission and
validation receipts; this report does **not** claim strict two-pass adherence.
It did not change the statistical question or use new inputs, but it is a
process limitation.

| Evidence | SHA-256 |
| :--- | :--- |
| Predeclaration | `377fcd959f63b9d8f72b5eefc8d1682a7d5625cc4df41312b122d486bc2aff82` |
| Primary host admission | `70e6498cce969ea60e8d1645395aead6d9f9fb5e9de4eb45f92bee23ab085a88` |
| Primary harness | `48ce2d92174063e84a2b5d7d6ef1d60322dd92c368631c0dae8f6d8e8a747281` |
| Primary analysis | `727a2f2b202c53a1a720d51dccf5d2076a074e58c5f1e1884472c0eb6508bd57` |
| Primary analysis receipt | `888655a14e29b6341325bd8af3ca9816fd0196b6c635fd530da27d1002873efc` |
| Alpha summary | `827518fc8c8a66cc852d251f91a6a83bdd766c915d9996fd0adc5550ea99bd7a` |
| Lag sweep | `3d075ba50399c56b29c2e8dd4b179b28653255959990c3643a655b907cbe8bf5` |
| Postprocess summary | `130f89b061c7e93c04b8e22d08fa5616ba3d4574e424e6a8ad0d6cbaa11e83b0` |
| Independent validator | `15ce90269cb4db8a69b763d283c64dfb37af56c5b08749980563d34a4188cde4` |
| Initial validator admission | `3462a19d3a5293d73110896bd8af80bf61823380e65701a6a9b07d915bc274f1` |
| Preserved failed validation receipt | `daefe5d339902853aed3a9bbb5682341db0719ea960f2c4e21b01421da7fbfee` |
| Retry admission | `8dd206321ce54be5f5e46ac8c3c33098bbd968306df7d0267757cd8cec588b06` |
| Independent PASS receipt | `702b5d594d5934962c9c920c360b5be8a5ad9ea9c012846be2c5422daea60683` |
| Frozen candidate vector | `cf661e9fb396e95db4e98f2aa29fd32dda2fb9b992099e4d0d6fcfea89b68a4b` |

## Limitations and NOT-DONE / NOT-PROVEN

- **NOT ACCOUNTED FOR:** no predeclared evaluable function reproduces all raw
  recorded probabilities.
- **NOT IDENTIFIED:** the different artifact/config/code/unrecorded-transform
  residual possibility has no exact producer binding.
- **NOT ELIMINATED:** omitted-context support floor, late lock-in, adjacent
  calibration, exact configured-blend paths, or unpredeclared compound
  lag-plus-transform functions.
- **NOT PROVEN:** `recorded_probability` was actually delivered by an API,
  UI, worker, request, or acknowledged consumer.
- **NOT IMPLEMENTED:** the proposed record-only binding receipt.
- **NOT DESIGNED OR AUTHORIZED:** serving-path delivery instrumentation.
- **NOT DONE:** model, blend, alpha, postprocess, config, artifact, release,
  pointer, collector, scheduler, sizing, cap, trading, or serving changes.
- **NOT USED:** vendor request, full-book read, `data/` analytic read, replay,
  fitting, settlement outcome, market price, or future row to select an
  accounting function.
- **PROCESS DEVIATION:** three vector scans were executed after the first
  validator implementation failed, versus the predeclared ceiling of two.
- **NOT RUN:** Missions 3+ of
  `workstation-handoff-2026-07-28c-scale-the-mm-corpus.md`; their morning
  window and gates remain unchanged.
- **NOT DONE:** PR, merge, or master push.

## Handback

Recorded output remains closest to incumbent, but it is not incumbent, not
replay-final, not preblend, not a convex blend of the frozen inputs, not a
carried-forward documented lane, and not any tested fixed postprocess. The
accounting track therefore closes this queue with a measured negative:
**`NOT_ACCOUNTED_FOR_BY_PREDECLARED_EVALUABLE_FUNCTIONS`**.

Release-#1 work now has a concrete record-only design for binding the final
snapshot vector to its release and captured inputs. Proof of actual delivery
is a separate serving-boundary problem and was deliberately not crossed.
