# Workstation synthetic post-preselection rehearsal — 2026-08-01

## Ordered failure list

This rehearsal ran from exact merged `origin/master` commit
`db49fa8acf050b1ff5de5ea49a7ea3ec1a5f37f1` on topic branch
`codex/workstation-synthetic-rehearsal-2026-08-01c`. All generated output is
below the single declared root
`C:\Users\Michael\Documents\github\weather\scratch\runs\synthetic-rehearsal-2026-08-01c`.
The main repository `data/` tree was mounted read-only into the isolated
worktree for input access; no file below `data/` was written.

| Order | Stage | Exact failure | Classification | Disposition |
| ---: | --- | --- | --- | --- |
| 1 | Synthetic source inventory | The ordinary grade-only corpus skipped `2026-06-01` and `2026-06-02` as `too_few_replay_inputs`; both folders lack the captured replay prerequisite. | **missing-prerequisite** | Excluded before constructing the synthetic window. Neither date is in the locked window. |
| 2 | Bounded source reader | Seven older folders contain duplicate pinned replay identities: `2026-06-17`, `06-18`, `06-19`, `06-20`, `06-22`, `06-25`, and `06-28`. The bounded reader failed on the first duplicate in each folder. | **missing-prerequisite** | Preserved as data-integrity findings. The production contract correctly refuses duplicates; no source tape was changed. |
| 3 | Synthetic prelock construction | Supplying an ordinary promotion-corpus manifest beside the same explicit folders failed with `ContractViolation: explicit folders differ from the supplied replay manifest`. | **synthetic-artifact** | Let `prelock-production` own the bounded manifest instead of treating the ordinary manifest as production-equivalent. |
| 4 | Synthetic prelock construction | Passing the promotion CLI's special token `quality-grades=all` to `prelock-production` produced an empty manifest and the contradictory diagnostic `BoundedReadError: market-day bound exceeded: 0 > 60`. | **real-defect** | The empty input is invalid, but `0 > 60` is a real diagnostic defect. Re-ran with explicit `complete,partial`; no contract was changed. |
| 5 | Synthetic prelock construction | Production source materialization then refused partial labels: `production preselection requires a complete or manual_override manifest label admitted by quality grade`. | **synthetic-artifact** | Expected safety boundary. Constructed the marked synthetic lock outside the production contract, as authorized by the handoff. The real verifier was separately proven to reject it. |
| 6 | Candidate fit, attempt 1 | Pooled fitting refused four preselected dates absent from the F-family training corpus: `2026-06-15`, `06-16`, `06-24`, and `06-26`. | **missing-prerequisite** | Excluded only those unlocked dates and regenerated the synthetic hash. The first family artifact was preserved as attempt evidence. |
| 7 | Candidate fit, attempt 2 | The bounded, duplicate-free date inventory reached nested-fold construction but failed with `production outer fold has no nested inner folds: rolling_origin_001`. | **synthetic-artifact** | The seven duplicate-folder exclusions made the synthetic date sequence too gapped for the unchanged 14/7/3/7 fold contract. Restored those dates in an ordinary synthetic manifest; did not relax fold settings. |
| 8 | Candidate fit, attempt 3 | Restoring the ordinary dates exposed two further F-family coverage gaps, `2026-06-18` and `2026-06-25`. | **missing-prerequisite** | Added them to the unlocked exclusion set. V4 then passed the unchanged nested-fold preflight and the full pooled fit. |
| 9 | Locked replay / PIT qualification | `qualify-production` refused the marked lock before replay with `ContractViolation: source rows differ from the exact replay snapshot/label inventory`. It created no corpus, materialization manifest, validation plan, or streaming evaluation. | **synthetic-artifact** | This is the intended non-authorizing stop: the synthetic universe is deliberately disjoint from the preserved real source. The contract was not bypassed. |
| 10 | Immutable training-graph verification | Full immutable verification could not run because its four PIT artifacts do not exist after order 9. | **missing-prerequisite** | Independently constructed and self-hash-checked the graph from the exact fitted model, family, and routing artifacts; full cross-artifact verification remains for the real lock. |
| 11 | Research-only all-shadow release, attempt 1 | The tracked research model failed semantic freeze because corpus lineage is incomplete: `selection_training:missing_hash`, `evaluation:missing_hash`, `final_refit:missing_hash`, and `model_input_fields:missing`. | **missing-prerequisite** | Used the command's sanctioned `--model-source-release` path with the previously verified immutable rehearsal release. No lineage was invented. |

No other real code defect was found. The only real code defect above is the
zero-count diagnostic in order 4; the remaining stops were missing inputs or
deliberate consequences of making the lock non-authorizing.

## How far the path ran

### Synthetic lock safety

The final V4 lock is visibly marked `SYNTHETIC_NOT_EVIDENCE`, declares
`production_evidence_authorized=false`, and lives outside every repository-owned
candidate, release, and evidence path.

| Property | Value |
| --- | --- |
| Synthetic preselection hash | `efd9d33975885bacfde4be6cbcb1b129750e374f6085a48ef1e1ad73a54ffd98` |
| Replay manifest file SHA-256 | `922dac656785012d81fbfa7dd6ea43d0fa6b66fd9b8c87e71cc9fa4b6f583a6c` |
| Replay corpus hash | `6302eb85fa8a8e5b9a113a0f9b946f87156d6ef552191e86a77dcc8a7e513fb9` |
| Synthetic universe | 52 Toronto dates; 24 `complete`, 28 `partial` |
| Locked window | `2026-07-17` through `2026-07-30`; 11 `complete`, 3 `partial` |
| Production-verifier result | **REFUSED**, source/replay row inventory mismatch |

The lightweight trainer reader accepted the self-hashed shape, allowing
selection-exclusion code to run. The production verifier independently refused
the same file before replay. It therefore cannot satisfy a later real gate.

### Candidate fit

V4 completed both canonical production trainers with the unchanged fold and
memory contract:

| Artifact | Result |
| --- | --- |
| Pooled F-band model | **PASS**, 5,614 training rows, 1,499.4 seconds, SHA-256 `efb323dcaaf67a0913462c03239ad02951a9a8d7acec48eeb9198c2b45635dba` |
| Family-secondary graph | **PASS**, 11 ML serving modes, 1,853.0 seconds, SHA-256 `1550cef47d2acf25997569c8bb6e5d29013b267455e1fc12eff6f24aa9566d42` |
| Artifact registry | **PASS**, candidate-contained, 103 artifacts |
| Training evidence | 3 outer folds, 6 inner folds, 54 six-stage fit receipts |

Two earlier family fits also passed before their paired pooled attempts found
the synthetic inventory gaps: 1,768.6 seconds for attempt 1 and 1,578.1
seconds for attempt 2. Lock day should budget these stages in tens of minutes,
not seconds.

### Promotion qualification and routing

The exact unlocked 38-entry frozen corpus replayed successfully in 915.4
seconds. Promotion refresh returned **0 promote, 11 shadow, 0 blocked** and the
no-reuse binding passed with hash
`76788bb9752f34ccfee101d63df208ce0a52eab9ff60934aaca07a39a6cf50e6`.
The final routing artifact SHA-256 is
`00217f00ced8a3f2875fc8ea799c95678a969d09f1c1c44ef3c7e279b05e45db`.

The 11 F markets are shadow because the Toronto-only synthetic replay supplies
zero pinned candidate rows for each F market. That is the honest synthetic
result, not promotion evidence.

### Training graph

Independent graph construction over the exact V4 model, family, and bound
routing artifacts passed:

- artifact type: `point_in_time_candidate_training_graph`;
- graph hash:
  `0d9fd3b135b34607e420b2a364d10397dc550f13a60d9e03a314a83cae283670`;
- graph file SHA-256:
  `ded19ab79b2ede5db0b3e7e83a25a01f26c26a6df8bfca1f4839836e04dbaa5d`;
- route: 11 shadow, 0 promote, 0 blocked.

This proves graph construction and the artifact-level selection bindings. It
does not substitute for the full immutable verifier over PIT corpus, manifest,
plan, and evaluation.

### Research-only all-shadow release

The sanctioned source-release retry passed end to end using verified immutable
release `r1-rehearsal-20260729` only as the model and training/evaluation
lineage source:

| Property | Value |
| --- | --- |
| Status | **PASS**, runtime reverified |
| Candidate mode | `research_only` |
| Production capable | `false` |
| Activation | `NONE` |
| Runtime routes | 12 shadow markets: Toronto in C plus eleven F markets |
| Release file count | 102 |
| Release manifest SHA-256 | `e929e545c74c64537215c98d4b0619db4a0129b484f388a969514163a53acbfa` |
| Receipt SHA-256 | `88e37939f8ef2bdafb820fa26c444f29027f4e6707aefd31d592d4f9ed8df62e` |
| Active pointer | absent before and after |

This all-shadow release exercises the independent research bootstrap. It does
not contain the newly fitted V4 synthetic candidate model, because that model
cannot acquire a verified immutable source release without the PIT artifacts
that the synthetic safety stop intentionally withheld.

## What the synthetic approach could not exercise

The following remain for the real lock window:

1. bounded candidate replay after full production preselection verification;
2. the 2,000-iteration PIT evaluation and direct re-proof that the historical
   149 simplex failures remain gone on real evidence;
3. publication and cross-verification of the PIT corpus, materialization
   manifest, validation plan, and streaming evaluation;
4. full immutable candidate-training-graph verification across those four PIT
   artifacts;
5. production candidate semantic freeze and the first inactive production
   release build from the newly fitted candidate.

The synthetic run did exercise candidate fit, frozen promotion replay,
promotion routing/binding, artifact-level graph construction, and the separate
research-only all-shadow release bootstrap.

## Guardrail handback

- The isolated worktree passed the clean-source-tree gate at `db49fa8a`.
- Main and worktree production release pointers are both absent.
- No promotion, pointer, serving, scheduler, capture, mirror, ACL, trading, or
  paid-provider state changed.
- No production candidate or release directory was created.
- `data/` remained input-only.
- The declared synthetic run root contains 569 files totaling 729,227,375
  bytes; it is intentionally not evidence and must not be reused as a real
  prelock.
