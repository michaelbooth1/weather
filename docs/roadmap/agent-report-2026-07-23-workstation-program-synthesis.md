# Agent Report - 2026-07-23 Workstation Research Program Synthesis

## Outcome

**The program is complete with no serving, release, promotion, collector,
trading, sizing, or capital change.** Phase 0 established exact replay parity,
and every planned Workstream A-D line reached a documented decision. The
strongest model result is to retain pooled geographic training. The strongest
source result is to preserve METAR continuity. Current W0 smoothing remains the
serving decision. None of the tested forecast or execution variants proves
absolute edge over captured market prices or positive after-cost trading edge.

The integrated decision is:

- keep pooled training topology, current W0 serving, the configured WU
  settlement contract, and existing METAR availability;
- make no model-artifact, smoother, stage, source-weight, city-rule, collector,
  release-pointer, serving, or trading-policy change;
- stop the tested per-city/LOCO replacement, taker policies,
  `one_tick_inside` maker policy, same-panel predictor mining, and stale
  mixed-identity stage tuning;
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

Pool-vs-city uses an untouched 2025 confirmation and is the cleanest temporally
separate positive result, but it proves relative topology rather than market
edge. Tmax families have their own terminal holdouts, yet the five provider
families overlap outcomes and are corrected together. Maker and taker use
execution endpoints rather than forecast scores; their limited fills do not
confirm model skill. Stage attribution spans a broader historical tape but is
mixed-identity and has no current-code feature-model component rows.

The July 15-19 ordinal-smoothing one-shot panel is exposed, its authorization is
consumed, and it is permanently unavailable for fresh confirmation.

## Program results

| Line | Evidence | Decision |
| --- | --- | --- |
| Phase 0 parity | Frozen current/control match on all 18,403 shared observations; fresh replay matches 847/847 numeric leaves; 309/309 corpus inputs rehash cleanly | research gate passes; not edge evidence |
| H2 validation | current source uses symmetric blocked folds, fold-local preprocessing, and nested calibration; the 12 fallback artifacts predate the complete correction | do not re-fix source; fresh retrain and receipt required |
| Morning frontier | at 09:00, model-minus-market Brier `+0.1553`, log loss `+0.4434`, warm-event reach gap `+0.2541`, point MAE gap `+0.7743 C`; only Miami clears city multiplicity | diagnostic weakness; no city policy |
| Ordinal smoothing | physical tune selects C `0.75 C` directionally and F `1.25 C = 2.25 F` with F Brier/log deltas `-0.00465892/-0.01531136` vs fresh W0; selected F still trails market by `+0.00586560/+0.02280111` | keep W0; no fresh confirmation |
| Time frontier | native W1 F all-hours improves Brier/log loss `-0.00243/-0.00856` but winner probability falls `-0.01241`; market wins all three metrics in all six major slices and 36/36 ten-minute unit-slots | W1 is not the under-sharpness fix |
| Stage attribution | 6,670,906 rows; broad `feature_blend` gains; `forecast_pull` Brier `-0.00779` but log loss `+0.07028` and spread `-0.04506`; zero current-code component rows | historical diagnostic only |
| Pool-vs-city | untouched 2025 macro band Brier `0.047053` pooled vs `0.071389` per-city and `0.070298` LOCO; pooled wins every reported metric | retain pooled topology |
| Taker bakeoff | 20 complete dates, nine preregistered policies; every fill is one losing Denver day; least-negative filled arm `-$0.3669` over two fills | stop; no threshold/sizing sweep |
| Tmax predictors | five-family 200,000-draw Holm audit has zero rejections; exact CFSv2 radiation regresses MAE `+0.0709` [`+0.0194`, `+0.1171`] | no collector; one optional new-season radiation check only |
| Maker research | selected `one_tick_inside` loses `-0.857855` USDC/fleet-date vs `at_touch`, CI [`-1.754664`, `-0.144149`]; 52 complete fills net `-8.525664` | stop tested quoting policy |
| Source ablation | METAR removal worsens strict Brier/log loss `+0.023760/+0.090995`, Holm `p=0.00537109`; Denver is the only city action after 210-test Holm; no harmful source | preserve/instrument METAR; no config change |

## Integrated interpretation

There is no substantive contradiction among these results. Pooled training,
METAR availability, or F-family smoothing can outperform a weaker model or
control while the resulting forecast still trails the market. Relative model
improvement is not absolute edge.

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

- pooled geographic training with city features;
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

- replacing pooled training with per-city or LOCO models;
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
   integrity, and feature consumption—especially at late cutoffs—on that fresh
   artifact. Then run one preregistered ablation on genuinely new dates. Do not
   add a provider or change settlement semantics.
3. **Current-identity stage tapes.** Regenerate component tapes under one
   current identity and test `forecast_pull` with joint Brier, log-loss,
   bottom/winner-mass, and market-gap constraints.
4. **Partial pooling only over the pooled base.** If topology work continues,
   test regularized city deviations with untouched confirmation. Do not revive
   independent per-city or LOCO replacement.
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
- The ignored repository-local `data/` tree is a nightly mirror and was treated
  as read only. Experiment outputs live under
  `scratch/workstation-research-output`.
- Phase 0's pinned corpus has 309 market-days, 44,178 snapshots, 486,486 band
  rows, 12 markets, and 32 fleet dates; its file SHA-256 is
  `4cafcf1aa827bbf0b2b4c85af898192a50637c49d0b270c5006ef56f3cacd1f5`.
  The current frozen score still trails market Brier: `0.04272136` versus
  `0.03310608`, a `+0.00961528` gap.
- The clone-local mirror was first observed from the July 21 copy and refreshed
  on July 22. No upstream batch receipt binds every subtree, so observed mirror
  state plus content hashes are the strongest provenance. Source replay used a
  staged, content-addressed corpus outside `data/` after the refresh.
- Before the operator's explicit mirror reminder, one empty directory was
  created at `data/backtest/research/workstation_2026-07-22/phase0`. No file or
  result was ever written there. The later nightly `/MIR` refresh removed it;
  the program made no other write under `data/`.
- Source generation-001 failed closed on two support-count mismatches. No
  generation directory or result survived. An outcome-blind target-date rule
  correction made all 44 runtime-support pairs exact; generation-002 and
  synthesis-002 then published under matched execution closures. The detailed
  evidence is in the [source-ablation report](agent-report-2026-07-23-workstation-source-ablation.md).
- The July 15-19 H1 one-shot authorization was consumed after both arms ran,
  then failed a false-positive same-identity candidate gate before committing
  a result. Only the attempt marker remains. No confirmation metric exists, and
  the panel must never be rerun or reconstructed as fresh evidence.
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
The best next move is new evidence, not another slice: a fresh pooled,
H2-compliant artifact with an exact receipt, followed by one narrow METAR
confirmation and current-identity stage attribution. Until those inputs exist,
the production decision remains unchanged.

