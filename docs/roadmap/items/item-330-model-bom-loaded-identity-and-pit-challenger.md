# 330. Model Bill Of Materials, Loaded Identity, And PIT Challenger [PARTIAL 2026-08-31 - IDENTITY V0.3 RESTACKED; FREE-PIT CONTRACT AND WORKSTATION QUALIFICATION OPEN]

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

- [ ] Add a deterministic, release-aware model BOM that enumerates every
  serving stage in execution order, its owner/producer, feature contract,
  artifact or constant binding, training corpus/receipt where applicable, and
  dependency/runtime identity.
- [ ] Distinguish the feature-extraction forecast ensemble from the
  distribution-stage forecast context and fail if an undocumented semantic
  difference appears.
- [ ] Record the stored estimator feature order and structural use summary so a
  newer extractor schema cannot be mistaken for adoption by an older model.
- [ ] Make the release verifier reject missing, ambiguous, global-fallback, or
  non-content-bound BOM entries for production candidates.

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
- [ ] Re-run focused corpus/contract/base-retrain tests on the workstation and
  build one complete multi-year staged response set before claiming the formal
  corpus is materializable.
- [ ] Verify the production-host collector/export path can supply request-bound
  raw responses without the workstation calling a provider.

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
