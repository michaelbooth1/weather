# Agent Report - 2026-07-23 Workstation Research Program Synthesis

## Outcome

**The program is complete with no serving, release, promotion, collector,
trading, sizing, or capital change.** Phase 0 established exact replay parity,
and every planned Workstream A-D line reached a documented decision. The
corrected pool-vs-city result supports retaining pooled geographic training as
the working research baseline, but it is not an independent first look at its
already-opened 2025 confirmation window. The strongest source result is to
preserve METAR continuity. Current W0 smoothing remains the serving decision.
None of the tested forecast or execution variants proves absolute edge over
captured market prices or positive after-cost trading edge.

The integrated decision is:

- keep the existing pooled training topology as the baseline, current W0
  serving, the configured WU settlement contract, and existing METAR
  availability;
- make no model-artifact, smoother, stage, source-weight, city-rule, collector,
  release-pointer, serving, or trading-policy change;
- do not replace pooled training with the tested pure per-city or LOCO
  alternatives; stop the tested taker policies, `one_tick_inside` maker
  policy, same-panel predictor mining, and stale mixed-identity stage tuning;
- make the next model candidate a fresh pooled artifact trained through the
  corrected H2 path with a complete receipt and train/serve parity.

## Evidence independence

The reports are not eleven independent confirmations. Phase 0, Morning, H1,
Time Frontier, and Source Ablation reuse the June 3-July 10 replay corpus.
Source Ablation uses the exact H1 17-date tune and 15-date holdout files. H1 and
Time Frontier are one experiment plus a decomposition, not two validations.
The Source Ablation result is explicitly non-outcome-blind because earlier
forensic attempts exposed outcomes. Its Holm correction controls its declared
families but cannot restore blinding or correct across the whole program.

The original pool-vs-city result and hardened generation-001 were
future-informed. Their nominal `2024-01-01` exclusive cutoff filtered WU-backed
climate dates but failed to filter independently loaded METAR, GHCNh, and
reanalysis source-reliability dates globally. Corrected generation-002 removes
that leakage and reproduces the same strong direction, but it uses the same
fixed 2025 confirmation window after that window had already been opened.
Thus it is a corrected robustness rerun, not an untouched or independent
confirmation. It supports a conservative topology baseline, not a claim of
market edge.

Tmax families have their own terminal holdouts, yet the five provider families
overlap outcomes and are corrected together. Maker and taker use execution
endpoints rather than forecast scores; their limited fills do not confirm model
skill. Stage attribution spans a broader historical tape but is mixed-identity
and has no current-code feature-model component rows.

The July 15-19 ordinal-smoothing one-shot panel is exposed, its authorization is
consumed, and it is permanently unavailable for fresh confirmation.

## Program results

| Line | Evidence | Decision |
| --- | --- | --- |
| Phase 0 parity | Frozen current/control match on all 18,403 shared observations; fresh replay matches 847/847 numeric leaves; 309/309 corpus inputs rehash cleanly | research gate passes; not edge evidence |
| H2 validation | current source uses symmetric blocked folds, fold-local preprocessing, and nested calibration; the 12 fallback artifacts predate the complete correction | do not re-fix source; fresh retrain and receipt required |
| Morning frontier | at 09:00, model-minus-market Brier `+0.1553`, log loss `+0.4434`, warm-event reach gap `+0.2541`, point MAE gap `+0.7743 C`; only Miami clears city multiplicity; Dallas, Denver, NYC, San Francisco, and Toronto reverse tune-versus-evaluation reach direction | diagnostic weakness; no city policy |
| Ordinal smoothing | physical tune selects C `0.75 C` directionally and F `1.25 C = 2.25 F` with F Brier/log deltas `-0.00465892/-0.01531136` vs fresh W0; selected F still trails market by `+0.00586560/+0.02280111` | keep W0; no fresh confirmation |
| Time frontier | native W1 F all-hours improves Brier/log loss `-0.00243/-0.00856` but winner probability falls `-0.01241`; market wins all three metrics in all six major slices and 36/36 ten-minute unit-slots | W1 is not the under-sharpness fix |
| Stage attribution | 6,670,906 rows; broad `feature_blend` gains; `forecast_pull` Brier `-0.00779` but log loss `+0.07028` and spread `-0.04506`; zero current-code component rows | historical diagnostic only |
| Pool-vs-city | corrected generation-002 macro band Brier `0.047009` pooled vs `0.071389` per-city and `0.070879` LOCO; pooled-minus-per-city `-0.024497` CI `[-0.028373,-0.020724]`, pooled-minus-LOCO `-0.023774` CI `[-0.027274,-0.020235]`, each 14/0 dates and exact sign `p=0.00012207` | retain pooled as baseline; no clean new confirmation, artifact, or promotion claim |
| Taker bakeoff | 20 complete dates, nine preregistered policies; every fill is one losing Denver day; least-negative filled arm `-$0.3669` over two fills | stop; no threshold/sizing sweep |
| Tmax predictors | five-family 200,000-draw Holm audit has zero rejections; exact CFSv2 radiation regresses MAE `+0.0709` [`+0.0194`, `+0.1171`] | no collector; one optional new-season radiation check only |
| Maker research | selected `one_tick_inside` loses `-0.857855` USDC/fleet-date vs `at_touch`, CI [`-1.754664`, `-0.144149`]; 52 complete fills net `-8.525664` | stop tested quoting policy |
| Source ablation | METAR removal worsens strict Brier/log loss `+0.023760/+0.090995`, Holm `p=0.00537109`; Denver is the only city action after 210-test Holm; no harmful source | preserve/instrument METAR; no config change |

## Integrated interpretation

There is no substantive contradiction among these results. Corrected pooled
training, METAR availability, or F-family smoothing can outperform a weaker
model or control while the resulting forecast still trails the market.
Relative model improvement is not absolute edge. The repeated pool direction
is useful for deciding what not to replace, but the opened confirmation window
means that a genuinely new panel is still required for a fresh topology claim.

The Morning result and the smoothing mechanics also show why
"under-sharpness" is not one global scalar. The model can under-call a warm
morning while a global ordinal transform diffuses mass and lowers realized
winner probability elsewhere. Stage `forecast_pull` tells the same
multi-objective story: Brier improves while log loss worsens. Any next
candidate must jointly guard Brier, log loss, winner mass, calibration, and
market gap instead of optimizing one score.

METAR helping does not conflict with the negative Tmax-predictor program.
Observed near-surface conditions can aid the current inference path without
justifying another forecast collector. It also does not make METAR the
settlement source; configured WU history remains the settlement proxy.

The execution STOP results are compatible with model-relative gains. A
plausible probability improvement can still be too small for fees, spread,
queue position, adverse selection, and sparse fills. The program contains no
positive after-cost execution evidence.

## Decision matrix

### Keep

- the existing pooled geographic training with city features as the research
  baseline, pending genuinely new confirmation;
- current W0 serving behavior;
- existing METAR continuity and the configured WU settlement contract;
- blocked H2 validation, nested tuning, captured-input replay, mass,
  alignment, and release-binding ratchets;
- research-only, dry-run, and exclusive-generation safeguards.

### No change

- model artifacts or active pointers;
- ordinal-smoothing or stage constants;
- city-specific rules or source routing;
- source weights, collectors, settlement proxy, or provider requirements;
- maker/taker policies, sizing, capital, live/paper modes, or account state.

### Stop on the present evidence

- replacing pooled training with the tested pure per-city or LOCO models;
- current taker threshold/sizing arms and the `one_tick_inside` maker policy;
- CFSv2 850 hPa, soil, exact-radiation, and HRRR smoke specifications;
- tuning stage weights from mixed-identity component tapes;
- same-panel provider, city, hourly, threshold, or subgroup mining.

### Do not reuse or infer

- do not reuse June 22-July 10 for ordinal-smoothing selection or fresh
  confirmation;
- do not reuse July 15-19 for ordinal-smoothing confirmation;
- do not reuse the leaked seven-city morning grouping;
- do not infer that unsupported or no-op source variants are useless;
- do not treat group ablations as additive coefficients, METAR as settlement
  authority, or reused provider sensitivities as independent confirmations.

## Ranked follow-up program

1. **Fresh pooled H2 artifact.** Retrain through the corrected blocked/nested
   path. Bind exact code, input, model, calibration, and nested-counter hashes
   in a training receipt; prove train/serve feature parity and replay identity.
   This removes the largest shared provenance limitation.
2. **Narrow METAR confirmation.** Instrument METAR continuity, station-cascade
   integrity, and feature consumption, especially at late cutoffs, on that fresh
   artifact. Then run one preregistered ablation on genuinely new dates. Do not
   add a provider or change settlement semantics.
3. **Current-identity stage tapes.** Regenerate component tapes under one
   current identity and test `forecast_pull` with joint Brier, log-loss,
   bottom/winner-mass, and market-gap constraints.
4. **Partial pooling only over the pooled base.** If topology work continues,
   test regularized city deviations on a preregistered, genuinely new
   confirmation panel. Do not treat the opened 2025 window as fresh evidence
   or revive independent per-city or LOCO replacement.
5. **One new smoother design.** Only after the research candidate has a
   distinct identity and all deterministic preflight completes before the
   one-shot authorization is consumed, test a model-integrated,
   physically-mapped and possibly time-conditioned smoother on a genuinely new
   panel. A serve-only W1 constant is not eligible.
6. **New-data Miami morning test.** Specify the city rule before new outcomes;
   never reuse the retrospective four- or seven-city groups.
7. **Optional new-season radiation check.** Run one independent Open-Meteo
   Previous Runs radiation confirmation without further same-outcome provider
   tuning.
8. **Defer execution research.** Revisit maker/taker policies only after
   materially new complete settled tapes, explicit trades/fills, actual fees,
   and defensible queue economics exist.

Items 2-8 depend on new artifacts, new outcome dates, or materially better
execution evidence. Re-slicing the current corpus cannot satisfy them. This is
the point at which additional same-data analysis becomes more likely to
overfit than inform.

## Safety, provenance, and run-history disclosures

- Branch: `codex/workstation-research-2026-07-22`, isolated worktree
  `scratch/worktrees/weather-workstation-research-2026-07-22`, base
  `99c0616419ce75a402e5b752fc87b4f9bebec54c`.
- The ignored repository-local `data/` tree is a nightly mirror. After the
  operator's explicit reminder it was treated as strictly read only, and all
  experiment output remained under `scratch/workstation-research-output`.
- Phase 0's pinned corpus has 309 market-days, 44,178 snapshots, 486,486 band
  rows, 12 markets, and 32 fleet dates; its file SHA-256 is
  `4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5`.
  The current frozen score still trails market Brier: `0.04272136` versus
  `0.03310608`, a `+0.00961528` gap.
- The clone-local mirror was first observed from the July 21 copy and refreshed
  on July 22. No upstream batch receipt binds every subtree, so observed mirror
  state plus content hashes are the strongest provenance. Source replay used a
  staged, content-addressed corpus manifest outside `data/`, while reading the
  manifest-bound, hash-verified snapshot and WU inputs from the read-only
  `data/` mirror.
- Before the operator's explicit mirror reminder, one empty directory was
  created in the main mirror at
  `data/backtest/research/workstation_2026-07-22/phase0`. It contained no file
  or result and was later removed by the mirror.
- An earlier roadmap-linter invocation wrote the exact isolated-worktree file
  `scratch/worktrees/weather-workstation-research-2026-07-22/data/backtest/roadmap_backlog.json`;
  that exact file was immediately deleted. A later docs-agent linter invocation
  recreated the same isolated-worktree file. It remains untouched at 648,435
  bytes, modification time `2026-07-23T22:32:38.4830872Z`, SHA-256
  `de787a12a3c7c1ae45031f41baeed48e5f7eaf3d0472967fc7f7c2e97874a65f`.
- The main mirrored `data/backtest/roadmap_backlog.json` remained untouched at
  649,358 bytes, modification time `2026-07-21T23:44:39.4206860Z`, SHA-256
  `0eb53c76a1b1821ead4cf31e4b904a85ea3c71126928334c71e97522f8319997`.
  No experiment output was written under any `data/` path.
- Cutoff-forensic schema `pool_source_cutoff_forensic_v0.4` proves that the
  legacy pool context retained 31,092 market/source overlap-days at or after
  the exclusive `2024-01-01` boundary: 10,414 METAR, 10,300 GHCNh, and 10,378
  reanalysis; 36 are exactly on the boundary and 31,056 are later. Corrected
  behavior retains zero. Receipt SHA-256
  `edd36e3f651284ae9c716aa586ecf83bc9d4470d3a68e936a37bc49ef3410d94`;
  receipt-file SHA-256
  `6c2647c1d2007c92bd8dee645b5e325668ad393e43005b98df6e71d6f5c7cefa`.
  Its independent cutoff verifier passes all nine checks.
- The original pool report and hardened generation-001 remain
  future-informed diagnostic evidence. Corrected generation-002 completed all
  350 exact tasks with zero resumed training tasks under run ID
  `1c50d6b86750c7952463e2d98f97e58d32e8235fdc04a0a2186c3d9be1797ecd`.
  Its 257-file, 455,940,120-byte input receipt has SHA-256
  `96b7cb739267fb527ced8275106ac240390b8fd84f603dc45dfd30276c6a3334`;
  final source-closure verification is `PASS`. JSON, Markdown, predictions, and
  checkpoint-status SHA-256 values are respectively
  `478ce996b2c2ff85d9ab4af29c643a35388c4c70025da20e6b9d815a18a31429`,
  `177b69f205189ed17b107d961db4f2d239f8e8b5f316b47770b0aac8406e7eb1`,
  `ee2ea4ffe31d0e6b2839f49c2a994515c81fcb8907f8706ea70e0cd7dc6da600`,
  and `901f2cdf7ea8eb01fe272611004d780a4d5680b1eeb89d1fc26a3b1f69c70050`.
  Its equal-city macro log loss/winner Brier/MAE F are
  `0.184728/0.435524/1.0403` pooled,
  `0.308333/0.575592/1.3434` per-city, and
  `0.386554/0.529889/1.7748` LOCO.
  Relative to future-informed generation-001, corrected macro Brier moved from
  `0.04817346/0.07381472/0.07166716` to
  `0.04700852/0.07138937/0.07087913` for pooled/per-city/LOCO, so the
  qualitative direction survives the cutoff repair. An independent verifier
  passes the exact 350-checkpoint inventory.
- Morning generation-003 is structured-result-identical to the original and
  generation-002 JSON. Its corrected renderer enumerates all five direction
  reversals: Dallas, Denver, NYC, San Francisco, and Toronto. Generation-003
  JSON and Markdown SHA-256 values are
  `6e327611e038c8b36955beecc668352e456cd0f1a67e9b9b798e0a0dddfb51ba`
  and `09226e53f6bfefd691e00eb925c128ada8e10e96a099be07adfc41d3d03ae933`.
- Source generation-001 failed closed on two support-count mismatches. No
  generation directory or result survived. An outcome-blind target-date rule
  correction made all 44 runtime-support pairs exact; generation-002 and
  synthesis-002 then published under matched execution closures. The detailed
  evidence is in the [source-ablation report](agent-report-2026-07-23-workstation-source-ablation.md).
- A scratch-only final verifier independently rebuilt all 960 source-inference
  rows and matched 43,404 primitive leaves (35,862 numeric; 14,688 floating
  point) with maximum floating-point difference `0.0`. It also reproduced the
  explicitly defined 220 pooled fields within `3.189115638235762e-14` and ran
  all 26 focused synthesis cases. Receipt SHA-256:
  `1c492a34cd215f63d66293cba9cec76a571644853cb0b6a3c390907c01b26d55`.
  Its current-identity pass found only the expected post-seal source-tree drift
  from the safety work; 966 of the 967 source bindings still match, all
  terminal seals match, and the sealed generation outputs are unchanged.
- Operational source evidence is now accepted only through the verified
  canonical active release. Candidate, ambient, or legacy source reports
  cannot authorize an effective production route. Serving reads bind one
  descriptor, validate `fstat`, hash the exact bytes, rebind the path, and
  complete all route/role/kind/path/hash checks before pickle deserialization.
  Reparse points and links fail closed across release creation, bootstrap,
  nightly retraining, and serving.
- Promotion authorization is a code-owned empty set; forged legacy evidence
  cannot expand it. Recommendations are distinct from effective routes and
  fail closed to shadow when not release-bound; conflicting duplicates block.
  Strict JSON parsing rejects duplicate keys and non-finite or overflowed
  numbers. Promotion-corpus generations are immutable and exclusive, and
  scheduled-refresh resume binds the exact corpus receipt and hash-chained
  ledger. Point-in-time evaluation rejects duplicate rows, non-finite values,
  and invalid point/lower/upper interval order.
- These implementation-safety changes add verification and fail-closed
  behavior only. They do not authorize artifact promotion, an active-release
  change, paper/live trading, sizing, or capital use.
- The full repository suite is green: 3,572 passed, 9 skipped, 13 warnings,
  and 846 subtests passed. Focused closure evidence includes the 100-test
  schema/pool matrix plus 44 subtests; 85 release/source-binding tests passed
  with 3 skipped; the promotion-corpus resume matrix passed 151 tests with 1
  skipped and 8 subtests; point-in-time validation passed 59 tests with 1
  skipped; and the source synthesis verifier passed all 26 focused cases.
- The July 15-19 H1 one-shot marker durably records consumed authorization and
  bound inputs. Contemporaneous terminal output, not retained as a durable
  artifact, indicated that both arms completed before a same-identity
  fidelity-canary error; the false-positive diagnosis is therefore an
  operator-session interpretation rather than artifact-proven fact. No result
  or error artifact was committed, no confirmation metric exists, and the panel
  must never be rerun or reconstructed as fresh evidence.
- No production host, scheduled task, live collector, release pointer,
  promotion path, Polymarket account, live/paper order path, or master branch
  was touched.

## Evidence inventory

- [Phase 0 parity](agent-report-2026-07-22-workstation-phase0-parity.md)
- [H2 validation audit](agent-report-2026-07-22-workstation-h2-validation-audit.md)
- [Morning frontier](agent-report-2026-07-22-workstation-morning-frontier.md)
- [Ordinal smoothing](agent-report-2026-07-22-workstation-ordinal-smoothing.md)
- [Time frontier](agent-report-2026-07-22-workstation-time-frontier.md)
- [Stage attribution](agent-report-2026-07-22-workstation-stage-attribution.md)
- [Pool-vs-city training](agent-report-2026-07-22-workstation-pool-city.md)
- [Taker bakeoff](agent-report-2026-07-22-workstation-taker-bakeoff.md)
- [Tmax predictors](agent-report-2026-07-22-workstation-tmax-predictors.md)
- [Maker research](agent-report-2026-07-22-workstation-maker-research.md)
- [Source ablation](agent-report-2026-07-23-workstation-source-ablation.md)

These dated reports are historical research evidence. Their ignored local data
and scratch artifacts are not clean-checkout assumptions. No reproduction
command authorizes writing under `data/`, rerunning the consumed H1 one-shot,
reusing opened panels as fresh confirmation, or publishing into an existing
exclusive generation.

## Final disposition

The requested workstation program has exhausted the useful analyses available
from the present corpus without crossing into repeated-outcome overfitting.
Corrected generation-002 supports keeping pooled as the baseline and not
adopting the tested pure per-city or LOCO replacements, but the already-opened
2025 window prevents a fresh confirmation claim. The best next move is new
evidence, not another slice: a fresh pooled, H2-compliant artifact with an
exact receipt, followed by one narrow METAR confirmation, current-identity
stage attribution, and, only if still useful, a preregistered partial-pooling
test on genuinely new dates. Until those inputs exist, the production decision
remains unchanged.
