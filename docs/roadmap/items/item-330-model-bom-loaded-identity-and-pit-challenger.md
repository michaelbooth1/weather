# 330. Model Bill Of Materials, Loaded Identity, And PIT Challenger [PARTIAL 2026-09-02 - FOUNDATION WORKSTATION-QUALIFIED; 12-FIELD SEASONAL CHALLENGER INCONCLUSIVE; PRODUCTION REVIEW OPEN]

Goal: make the served model graph reproducible from the bytes actually loaded
by a process, establish the supported base retrain as a correctness baseline,
and test a simple challenger that adds genuinely new point-in-time forecast
information.

Source: the 2026-08-15 production-host core-model audit, distilled in
[`MODEL_SYSTEM.md`](../../operations/MODEL_SYSTEM.md) and
[`ESTABLISHED_FINDINGS.md` §8v](../../operations/ESTABLISHED_FINDINGS.md#8v-core-model-structure-and-lineage-audit--2026-08-15).

Why this matters: the supported base-retrain lane has strong isolation,
population, and PIT contracts, but it intentionally freezes the incumbent
feature order and model capacity. The active base artifact does not establish
that named forecast-consensus fields carry learned consensus information, and
the inherited postprocessors were fitted or selected against an older base.
Separately, filesystem-at-snapshot identity cannot prove which code and
artifacts a long-lived process actually served.

Relationship to existing work: item 321 remains the parent authority for
production readiness, immutable releases, shadow operation, and promotion.
Items 177, 178, 182, 216, and 233 retain their existing historical scope. This
item is the bounded child for the remaining cross-cutting model lineage,
matched-stack qualification, and new-information experiment; it does not
reopen their completed mechanisms or grant trading permission.

## Phase A — Generated model bill of materials

- [x] Add a deterministic, release-aware model BOM that enumerates the served
  graph as named semantic nodes and typed dependency edges, with exact execution
  order for each runtime-owned lane, plus owner/producer, feature contract,
  artifact or constant binding, training corpus/receipt where applicable, and
  dependency/runtime identity.
- [x] Distinguish the feature-extraction forecast ensemble from the
  distribution-stage forecast context and fail if an undocumented semantic
  difference appears.
- [x] Record the stored estimator feature order and structural use summary so a
  newer extractor schema cannot be mistaken for adoption by an older model.
- [x] Make the release verifier reject missing, ambiguous, global-fallback, or
  non-content-bound BOM entries for production candidates.

Implementation evidence: the workstation Phase-A descendant adds the
`weather.model.model_bom` builder/verifier, the narrow
`weather.model.model_bom_contracts` semantic catalog, a graph of named nodes and
typed edges, and two exact runtime-owned lane orders. It binds
candidate-relative artifacts, owner source and loaded-module identity, behavior
constants, release runtime/dependencies, artifact-specific training lineage,
stored feature order, structural-use summaries for pooled/HGB/JSON coefficient
models, and two source-set-verified forecast contexts. Candidate and
immutable-release verification reject partial, extra, legacy-production,
absolute-path, or self-rehashed stage/evidence substitutions. Loaded serving
rechecks estimator and coefficient structure after deserialization.
Research-unbound and unrebound research-child states are explicit `INCOMPLETE`
records without an authoritative identity. The implementation passed this
mission's current-tip full workstation qualification and remains pending
production review; no candidate was fitted, frozen, promoted, or activated by
this Phase-A work.

## Phase B — Loaded-process identity repair

- [x] Replace raw `marshal.dumps(code)` identity with a stable recursive code
  representation that removes path-only fields such as `co_filename` while
  retaining behavior-bearing bytecode, names, defaults, closures, and nested
  constants.
- [x] Canonically bind behavior-bearing nested module constants, including
  mappings and sequences, without admitting mutable runtime caches or fitted
  objects into the code hash.
- [x] Bind estimators and postprocessors to the bytes or canonical state
  actually deserialized by the process, not the files visible on disk at later
  snapshot time.
- [x] Prove identical loaded behavior hashes equally across worktree paths;
  prove a code/constant mutation changes identity; and prove post-load disk
  mutation cannot relabel the already-loaded process.
- [x] Supersede rather than merge unmodified commit
  `4050f1ee6551cc0a5806941b6b5f20ed766dbc95`.

Implementation evidence: the isolated v0.3 successor normalizes nested code
filenames, binds function defaults/closures and canonical nested constants,
expands the serving-code graph to the actual runtime owners, hashes loaded
estimator/postprocessor state plus Python/numpy/scipy/sklearn identity, and
leaves import-time/disk hashes as unhashed diagnostics. Adversarial tests cover
cross-worktree compilation, constant/default changes, mapping order, late
imports, loaded-artifact replacement, and post-load disk mutation. The real
Toronto HGB graph fingerprints deterministically with a cached steady-state
path. The implementation was restacked onto `c932b54f` on
`codex/model-pit-foundation-20260831`. Its earlier focused evidence remains a
positive control, not current-tip qualification. The branch is roll-sensitive
and remains unmerged pending workstation requalification, exact CI, production
review, and a guarded quiet-window adoption decision.

## Phase B2 — Honest free-PIT source contract

- [x] Keep all 21 schema-known forecast fields explicit, but classify the exact
  12 fields proved available from the free Previous Runs endpoint separately
  from the nine all-null or rejected fields.
- [x] Make the default immutable training plan request only the proved 12-field
  surface and exclude profile features that require an unavailable field.
- [x] Preserve the prohibition on stitched settled data as a substitute for
  missing issue-time evidence.
- [x] Re-run focused corpus/contract/base-retrain tests on the workstation.
- [ ] Build one complete multi-year staged v2 response set before claiming the
  formal corpus is materializable.
- [ ] Verify the production-host collector/export path can supply request-bound
  raw responses without the workstation calling a provider.

Workstation P2 audit disposition: **NO-GO — no repository-owned collector
consumes the immutable v2 plan.** `weather.sources.forecast_training_corpus`
intentionally has no HTTP client and exposes only CLI `plan`, `resume-status`,
and `materialize`; `stage_response` has no non-test caller. The existing
`forecast_history` network path does not consume plan request hashes or emit the
required request-bound raw-byte/issue-evidence receipts. Smallest follow-up
owner: a separate `weather.sources.forecast_training_corpus_collector` module
plus focused source tests, leaving the corpus module network-free;
export/transfer follows only after complete hash-verified materialization.

Official-source P0 disposition: **NO-GO — no reviewed free source supplies both
provider-bound historical first-availability evidence and train/serve-equivalent
coverage for the frozen 12-field hourly contract.** NOAA GFS and ECMWF Open Data
encode provider cycles, but fail historical availability and field/archive
parity. Open-Meteo Single Runs fixes explicit run selection, but its GFS archive
begins only on 2026-04-02 and its documented availability metadata covers only
the latest run, not historical runs. No collector or provider transport was
built. The evidence and exact field/timestamp matrices are in
[`agent-report-2026-09-06-workstation-pit-v2-source-contract.md`](../agent-report-2026-09-06-workstation-pit-v2-source-contract.md).

## Phase C — Correctness baseline and matched-stack qualification

- [ ] Run the supported all-market base retrain only after its explicit PIT
  corpus and feature records pass every existing guard. Preserve the candidate
  as an immutable inactive release; do not mutate the active pointer.
- [ ] Label the result as a seasonal/PIT correctness baseline. Do not claim it
  tested staged fields outside the frozen parent feature order.
- [ ] On one frozen outer-date population, compare the refitted base alone, the
  complete inherited serving stack, and matched removals of each inherited
  postprocessor. Use the stage-attribution harness without treating historical
  in-sample validation as qualification.
- [ ] Retain an inherited stage only when it improves or is safety-required on
  the exact served graph. Route statistically adverse or redundant stages to a
  removal candidate; safety constraints remain non-raisable.

## Phase D — Simple new-information challenger

Workstation terminal result (2026-09-02): the exact sealed 12-field corpus
passed P0, and the outcome-blind all-leads 1-7 design was committed before C
outcomes were opened. The locked C-pre result is
**`INCONCLUSIVE_UNDERPOWERED`**: Brier improved slightly, centre SSE worsened,
all crossed intervals span zero, and the leads-2-7 sensitivity has an adverse
centre direction. The original decision rule therefore rejects
`GO_TO_SECOND_RESEARCH_REPLICATION`. C-post was kept separate and is
three-market directional evidence only. See
[`agent-report-2026-09-10-workstation-12field-seasonal-challenger.md`](../agent-report-2026-09-10-workstation-12field-seasonal-challenger.md).
The earlier missing-corpus disposition remains historical evidence in commits
`e741b599` and `52510fca`; it is superseded rather than erased. Phase D remains
open because this candidate did not qualify and the broader correctness
baseline/matched-stack work elsewhere in this item is not complete.

- [ ] Define a regularized market-aware NWP residual or ordinal challenger that
  consumes issue-qualified staged Previous Runs fields unavailable to the
  frozen incumbent feature order. No market price may enter the weather model.
- [ ] Compare it with a simple market/date prior and the correctness-baseline
  incumbent on identical PIT rows, folds, labels, cutoffs, and support.
- [ ] Tune only inside blocked training folds and reserve later fleet dates for
  the locked claim. Use crossed date-by-market clustering and report intervals,
  power/MDE, coverage, severity-tail behavior, and per-market regressions.
- [ ] Prefer the simpler model unless added complexity demonstrates independent
  out-of-sample value. Calibration-only or market-shrunk controls cannot win
  this gate.

## Phase E — immutable shadow disposition

- [ ] Freeze the winning graph, BOM, loaded identity, corpus and request hashes,
  dependencies, feature order, labels, and evaluation receipt before shadow.
- [ ] Collect process-bound captured-input shadow evidence with no historical
  release-boundary pooling and no reconstruction claim when served bytes are
  absent.
- [ ] Hand any promotion decision back to item 321. This item never activates a
  release, allocates alpha, weakens a serving floor, or authorizes live orders.

Acceptance: complete only with a verifier-enforced model BOM; a path-independent identity
that binds loaded code and loaded artifacts; a candidate-only supported base
retrain with an honest correctness-only disposition; matched outer-date
qualification of inherited serving stages; and a simple new-information PIT
challenger with crossed-cluster uncertainty. A candidate may advance to item
321 shadow gates only if its complete served graph beats the locked baselines
without a material fleet, tail, parity, mass, lineage, or safety regression.

## Verification surface

- focused model-identity and release-verifier tests, including cross-worktree
  and post-load disk-mutation cases;
- focused base-retrain, PIT-corpus, train/serve-parity, stage-attribution, and
  captured-input replay tests;
- model BOM determinism and clean-checkout fixture tests;
- `python -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint`;
- `python -m weather.operations.agent_docs_audit` and `git diff --check`.
