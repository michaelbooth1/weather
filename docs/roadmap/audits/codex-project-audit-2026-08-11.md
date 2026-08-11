# Codex project audit — 2026-08-11

**Audit verdict:** the project has built an unusually rigorous evidence and operations system, but
the control plane has grown faster than the forecast-learning loop. The central goal is still not
met: the weather-only forecast does not beat the market, no retrained candidate has completed the
full path, and no trade or maker fill has been observed. The next step should not be another layer
of qualification machinery. It should be a short, certified path from the newly staged
point-in-time (PIT) forecast information to one coherent, low-capacity research candidate, judged
on the distribution production actually served.

The project should preserve its strongest habits—PIT honesty, captured-input replay, release
binding, native settlement units, pre-registration, crossed inference, power/MDE calculations,
explicit retractions, and fail-closed production gates. It should change how those controls are
sequenced and measured. In particular:

1. **Repair and certify the judge before fitting another confirmatory candidate.** The latest five-
   mission chain showed that Gate 3 judged a replay floor that production had not served and that an
   “any bad row” gate becomes a panel-size limit.
2. **Turn the staged 12-field, seven-lead PIT corpus into a durable research input without changing
   serving.** This is the clearest remaining own-information source that has not been honestly
   evaluated.
3. **Separate maintenance retraining from model discovery.** The base retrain is a safe refit of the
   incumbent family, not a search for a materially better forecast.
4. **Start with a pooled, native-unit forecast-residual distribution around an honest NWP anchor.**
   Compare it with boring baselines before considering another large HGB or a neural network.
5. **Make missions resolve bounded dependency graphs, not one exception at a time.** Preserve narrow
   write scopes but grant repository-wide read-only diagnostic scope and require outcome artifacts.
6. **Make current truth and accepted evidence mechanically current.** `STATE_OF_PLAY`, the campaign
   ledger, active backlog, report archive, and branch disposition are not synchronized with the
   latest accepted findings.

---

## 1. Audit basis, scope, and limitations

### Repository snapshot

The checked-out branch was clean but materially stale:

| Item | Value |
| --- | --- |
| Checked-out `master` | `5c3918815075d8c89c92d7d73d981a298aedfe4b` |
| Local `origin/master` inspected as current | `cbeb9a99674ddce44277a83dd1424f04db4fc06a` |
| Divergence | local `master` **63 commits behind**, 0 ahead |
| Last known fetch of the inspected remote-tracking ref | 2026-08-10 19:31 local time |
| `master..origin/master` diff | 64 files, +32,432 / -10,946 |

This report therefore uses `git show origin/master:<path>`, ref-aware history, and ref-aware diffs
for current findings. A worktree-only review would have missed missions `-09-60a` through
`-09-68a`, the staged PIT corpus, the objective change, and the Gate-3 instrument audit. The actual
GitHub remote may have advanced after the last local fetch; this report is explicitly an audit of
the local `origin/master` snapshot above.

### Sources reviewed

- Required canonical context: [state of play](../../../docs/operations/STATE_OF_PLAY.md),
  [durable agent context](../../../docs/operations/AGENT_CONTEXT.md),
  [established findings](../../../docs/operations/ESTABLISHED_FINDINGS.md),
  [retracted and false leads](../../../docs/operations/RETRACTED_AND_FALSE_LEADS.md), and the
  [delegation contract](../../../docs/operations/DELEGATION_CONTRACT.md).
- Product, architecture, development, path ownership, scoped `AGENTS.md` files, runbooks,
  campaign ledger, backlog, retrospective, model code, reporting code, tests, artifacts, CI, and
  PowerShell operations scripts.
- Full reachable Git history and first-parent history, with special attention to the July 9–August
  10 campaign and the newest remote-only commits.
- Three independent read-only audit lanes: commit history, model/training/evaluation, and
  mission/delegation design.
- Primary external literature on statistical weather post-processing, used only to propose
  hypotheses and baselines—not as evidence that this project has edge.

### What was not audited

- Ignored production `data/` was not treated as present or complete. Runtime claims are based on
  checked-in receipts, code, reports, manifests, and commit evidence. The report does not certify
  current live capture health.
- No provider calls, scheduled task mutations, model fits, promotions, trading actions, or live
  writes were performed.
- The canonical Python 3.11 virtual environment on this host is broken: its interpreter points to
  a removed `C:\Users\Michael\AppData\Local\Programs\Python\Python311\python.exe`.
  Full `pytest` therefore could not be run. Using the bundled workspace Python 3.12, `compileall`
  over `app`, `src`, and `tests` passed, and `weather.operations.agent_docs_audit` passed for 18
  agent files and 748 Markdown files. Those checks are useful but are not a substitute for the
  canonical full test suite.

### Evidence labels used in this report

- **Established:** already supported by accepted project evidence.
- **Audit finding:** directly observed in code, history, or current tracked documents.
- **Inference:** a reasoned interpretation of established evidence; not yet measured directly.
- **Hypothesis:** a proposed model or process improvement that requires a cheap falsifier.

---

## 2. What this project is and what success means

This is a Windows-operated probabilistic forecasting and research platform for 12 daily highest-
temperature markets: Toronto in Celsius and 11 U.S. markets in Fahrenheit. It collects weather,
forecast, market, CLOB, and settlement evidence; builds a probability distribution over the venue's
temperature bands; stores captured inputs and component stages; evaluates model and market scores;
and supports research, paper, shadow, and gated live workflows.

The operating graph is approximately:

```text
free PIT forecast data + WU history/settlement proxy + live observations
        -> canonical feature and provenance records
        -> per-market probability model / candidate model
        -> band projection and serving post-processing
        -> captured snapshots, replay inputs, model/market tape
        -> settlement and label provenance
        -> paired proper-score evaluation and release evidence
        -> shadow/paper execution evidence
        -> explicitly gated promotion or trading
```

The goal is not “make probabilities look closer to the market.” It is:

1. produce a better **forecast** than the market using the project's own weather information;
2. establish that improvement with PIT-honest, powered, predeclared evidence;
3. determine whether the forecast advantage survives execution and costs;
4. trade only after existing safety and readiness gates pass.

Market probabilities are therefore a benchmark and diagnostic, not an input to the weather-only
candidate. Market shrinkage can improve score mechanically but does not establish independent
forecast skill.

### Current outcome state

The [project retrospective](../../../docs/operations/HOW_WE_GET_THINGS_WRONG.md) and latest findings establish
the following baseline:

| Outcome | Current state |
| --- | ---: |
| Missions dispatched / returned in retrospective | 130 / 125 |
| Retracted or false claims catalogued | 31 |
| Served changes with a measured score improvement | 1 |
| Completed retrains | 0 |
| Trades | 0 |
| Maker fill-tape days | 0 |
| Predeclared model-edge cells with positive established edge | 0 of 114 |
| Overall model minus market Brier delta | `-0.01915` [`-0.02444`, `-0.01443`] |

The platform is capable; the learning outcome is not yet achieved. Future process metrics must use
these outcomes as the denominator, not mission count or green eligibility alone.

---

## 3. What is working and should be preserved

### 3.1 Scientific honesty

The project has repeatedly corrected itself rather than preserving convenient narratives. The
retrospective, retraction log, and latest Gate-3 chain are unusually candid. Specific strengths are:

- fit-on-B / score-on-C discipline and a campaign alpha ledger;
- crossed target-date × market clustering after narrower inference caused retractions;
- explicit distinction between “not identified,” “underpowered,” and “evidence of no useful
  effect”;
- candidate-specific MDE and finite-panel power calculations;
- cheap B-only premise screens that can close a direction without touching C or spending alpha;
- positive and negative controls, production-host reproduction, and hash-bound protocols;
- reporting of point estimates in the wrong direction even when intervals cross zero;
- separation of a correctness repair from proof of forecasting skill.

These controls produced important, credible closures: generic recalibration, global sharpening,
conditional power-map reshaping, input completeness as a skill lever, model-skewed quoting,
execution reconstruction from retained books, and market shrinkage as an own-information forecast
candidate.

### 3.2 Data and serving contracts

The codebase takes difficult operational invariants seriously:

- settlement units are native to each market;
- WU history is the configured settlement proxy and other weather sources are supporting evidence;
- paid weather sources are excluded;
- PIT issue semantics, captured-input replay, release identity, probability mass, and floor behavior
  are explicit contracts;
- source provenance and event configuration are durable;
- research, shadow, dry-run, and paper modes are the default;
- promotion and live trading are fail-closed.

The component-stage snapshots and ablation/replay systems give the project substantially better
observability than a typical prototype.

### 3.3 Operational safety

The roll-verdict and quiet-window workflow recognizes that production imports can restart capture.
The more recent distinction between roll-sensitive code and roll-free docs/config/PowerShell work
corrected an earlier process bottleneck. Capture recovery is verified before a roll-sensitive merge
is pushed. Those safeguards should remain.

### 3.4 The newest model direction is evidence-led

The project has correctly concluded that the remaining lever is not more reshaping of the same
distribution, but new own-information. The free Previous Runs surface has now produced a staged
corpus with:

- 12 of 12 markets;
- 2026-06-03 through 2026-08-09;
- 12 fields across lead offsets 1–7;
- 1,645,056 rows;
- 100% reported non-null coverage;
- `fixed_lead_day_offset` provenance;
- an exact positive control on the temperature field already held.

It was also correct not to copy this directly into the serving archive: the historical analog path
would begin consuming newly populated values, which is itself a serving change.

---

## 4. Central findings

### P0 — Current truth is not current

**Audit finding.** Even `origin/master` contains contradictory current-state documents:

- `STATE_OF_PLAY.md` says it was last rewritten on 2026-08-08, remains above its intended ~90-line
  cap, and stops around missions `-09-59a`/`-09-61a` as dispatched.
- The same ref contains accepted results through `-09-68a` and a reframed objective in
  `ESTABLISHED_FINDINGS.md`: contiguity gates nothing on the active critical path.
- The [campaign ledger](../../../docs/operations/CAMPAIGN_LEDGER.md) still describes decision 10 as
  allocated/unspent in places even though the
  later chain closes it unused and forbids reassignment.
- The [active backlog](../../../docs/roadmap/active-backlog.md) was last generated on 2026-08-01, before the
  central objective and research
  route changed.
- [The operations-agent role](../../../docs/operations/OPERATIONS_AGENT_ROLE.md) still contains dated August
  3 state and obsolete streak/release
  premises.
- One canonical section calls seasonal coverage a measured root cause while other accepted text
  correctly labels the causal step as inference.

This is not cosmetic documentation debt. `STATE_OF_PLAY` is mandatory first reading and is meant to
prevent re-derivation. When it lags, every mission starts with a different world model.

**Do now.** Add a generated semantic-currentness receipt that fails when:

1. `STATE_OF_PLAY` predates the latest decision-changing accepted handback;
2. a mission is still `DISPATCHED` after its accepted verdict exists;
3. its objective conflicts with the active objective claim;
4. the campaign ledger disagrees with the accepted decision state;
5. the backlog exceeds a freshness SLA without an explicit stale marker;
6. two canonical claims with the same key are simultaneously active.

Represent load-bearing claims in a small structured registry with `claim_id`, state (`measured`,
`inference`, `decision`, `retracted`), evidence hash, accepted commit, and `superseded_by`. Generate
the compact human state page from it. Do not try to infer semantic truth only from prose dates.

### P0 — The evaluation instrument was not certified before candidate contact

**Established.** The Gate-3 trace at
`origin/master:docs/operations/GATE_3_FIRED_ON_A_FLOOR_WE_NEVER_SERVED_2026-08-10.md` shows that
decision 10's Gate 3 failed on an alleged incumbent zero on Denver's realized
band. Production had actually served `0.5206313021` there. The zero came from a research replay
floor of 91; production's captured served floor was 68. Later work found two genuine B floor
crossings, traced to a mutable upstream observation series and an empty-history fallback that used
instantaneous current temperature as `high_so_far`.

The latest audit then established that the gate itself was structurally mis-specified. With two
crossings among 204 B market-days, its estimated probability of firing on a panel of that size was
about 86.6%. More generally, a fail-on-any-row gate has
`P(fire) = 1 - (1 - q)^n`, which tends to one for any nonzero incumbent floor-error rate `q` as the
panel grows. That gate primarily measured panel size and incumbent/common input defects, not a
candidate's behavior.

This does **not** license weakening the observed-high floor, adding epsilon probability, changing
the frozen protocol after seeing the failure, or reusing retired decision 10. It licenses fixing the
research instrument before allocating a new decision.

**Do now: build a sealed golden evaluation table.** Every evaluated row should contain:

- exact captured served probability vector and component-stage identity;
- exact captured served floor/support/lock-in inputs, not a reconstruction from deprecated columns;
- raw incumbent distribution and candidate distribution;
- market/event/band geometry in native units;
- authoritative deduplicated settlement label and provenance;
- release ID, schema ID, record hash, issue time, cutoff, and exclusion reason;
- market benchmark only as a scoring column, never a weather-candidate feature;
- content hash over row order and all load-bearing fields.

Certify it with:

- exact-clone candidate negative control: candidate delta must be exactly zero;
- deliberately damaged positive control: the evaluator must detect a known mass/floor/label error;
- served-versus-replay parity by endpoint and stratum;
- mass, nesting, native-unit, dedupe, and label-provenance checks;
- gate satisfiability at current and planned panel sizes;
- empirical coverage of the actual crossed interval procedure;
- outcome-independent exclusion rules frozen before candidate outcomes are inspected.

Split gates into two classes:

1. **Absolute serving/data-integrity gates.** These fail on an incumbent floor, label, mass, or
   provenance defect and route to operations. They are not charged to every candidate.
2. **Paired candidate-safety gates.** These test whether the candidate introduces a new defect
   relative to the certified incumbent on the same row. Existing common defects cannot be
   misattributed to the candidate.

If absolute floor integrity is not certifiable, fix and recapture it before confirmatory use; do not
make a post-outcome exception list.

### P0 — Binding inference is not implemented consistently

**Audit finding.** Canon says crossed target-date × market clustering is mandatory. Yet two generic
candidate paths still drive PASS logic with whole-fleet target-date bootstraps:

- `calibration/residual_distribution_v1.py` reports `whole_fleet_target_date` intervals;
- `calibration/served_stage_ablation.py` aggregates and bootstraps by fleet target date.

Correct crossed logic exists in research modules, but not as a single reusable, tested statistical
primitive. This permits a candidate or stage-retirement packet to be internally valid yet
inadmissible under the project's own method contract.

**Do now.** Create one canonical crossed pigeonhole/bootstrap utility and require it everywhere a
model, stage, slice, or MDE result can drive PASS, promotion, or retirement. It should always report:

- target-date clusters, market clusters, market-days, and snapshots;
- paired estimand and weighting unit;
- point estimate, crossed CI, seeds/draws, and empirical coverage receipt;
- candidate-native MDE and power at the proposed effect;
- descriptive date-only results, if desired, clearly marked non-decision-bearing.

### P0 — Base freshness is not a startup gate

**Audit finding.** A clean worktree was 63 commits behind the remote-tracking ref. Root instructions
required `git status --short`, which did not make the divergence sufficiently prominent. The stale
checkout gave materially false current state.

**Do now.** Every audit and mission receipt should record:

```powershell
git status -sb
git rev-parse HEAD
git rev-parse origin/master
git rev-list --left-right --count HEAD...origin/master
```

Abort or explicitly switch to ref-aware reads if the base exceeds a mission-specific divergence
limit. A handoff should name an exact base SHA, and the handback should state the executed SHA and
any premise-changing commits that landed during the mission.

### P0 — The learning path and release path are conflated

**Audit finding.** The all-market base retrain is necessary maintenance but not candidate discovery.
On current `origin/master` it:

- inherits the parent feature contract, while the new policy only removes pressure and pressure
  trend for Fahrenheit markets that cannot serve them;
- inherits parent HGB parameters and topology;
- fits one model per market and cutoff hour;
- searches probability temperature and blend weights;
- uses blocked year/date OOF for calibration;
- cannot introduce multi-run PIT fields, seasonality, conditional scale, a coherent continuous
  target, partial pooling, or a different capacity regime.

The historical population is 75 target dates per market across 2021–2025 and 14 cutoffs—12,600
fleet cells. A per-market, per-hour learner therefore sees only about 75 independent target-day rows
before folds and missingness. A large per-market classifier cannot manufacture independent
information from the many band or snapshot rows derived from the same day.

**Do now.** Preserve `base_retrain` as an incumbent-safe refresh, but name it accordingly. Build a
separate research candidate command that:

1. binds one immutable PIT corpus and feature contract;
2. trains without an active production parent release;
3. emits a complete content-addressed fit receipt;
4. scores on the certified served surface;
5. cannot promote or write production state;
6. compares against simple baselines and the incumbent;
7. exits with an explicit `worked`, `stopped(reason)`, or `failed(reason)` outcome artifact.

Prove this vertical thin slice before building more release qualification around it.

---

## 5. Model and training audit

### 5.1 Current model shape

The active legacy model is a multiclass `HistGradientBoostingClassifier` per market and printed
cutoff hour, with fixed capacity (`max_iter=50`, `max_leaf_nodes=15`, `learning_rate=0.05`) and a
climatology blend/temperature calibration. Served artifacts use heterogeneous feature-schema
generations: roughly 24–29 inputs depending on market, not the full 221-column feature-store
surface (which includes 53 forecast-profile and 40 U.S.-guidance columns). Their actual inputs are
mostly intraday temperature trajectory, basic moisture/pressure/
wind state, a forecast high/gap, source count/disagreement, freshness, and live-reading indicators.

Important consequences:

- the model artifacts were fitted around June 10–13;
- the primary HGB artifact stopped changing on June 20 and the tracked HGB directory on July 11;
- schemas vary across markets (`v0.2`–`v0.4`);
- no explicit cyclic season/day-of-year representation is in the active feature contract;
- the 11 newly available PIT physical forecast fields are absent;
- historical training uses one Open-Meteo forecast source while live serving can take a median of
  multiple sources and expose disagreement, putting live values outside actual historical support;
- the base classifier is followed by a long serving transformation graph, so base-objective gains
  need not equal final served gains.

The code's stage attribution and predeclared ablation matrix are strengths. They should be used with
the canonical crossed method to determine which stages help the final served score and which only
add variance or complexity.

### 5.2 What the evidence has already closed

Do not spend another mission on these without a genuinely new information mechanism:

- generic global recalibration as the main route to parity;
- global sharpening or smoothing as independent edge;
- another conditional power-map reshape of the existing distribution;
- scalar per-band isotonic repair or static band-key factors;
- input population/completeness as proof of skill;
- exact-winner multipliers;
- market-probability shrinkage inside the weather-only candidate;
- broad searches for quotable model-skew cells;
- reusing quarantined density or settlement-conditioned candidate families unchanged;
- weakening the observed-high floor;
- stitched forecast history presented as PIT training evidence.

The current model has a cool bias, but bias correction alone is not the central gap: reliability is
a small share of the excess loss and the in-season model still loses materially. A maintenance
retrain is necessary, not sufficient.

### 5.3 The best next target: a coherent NWP-residual distribution

**Hypothesis.** The most defensible next candidate is a low-capacity model of
`settlement daily high - honest PIT NWP anchor`, followed by one coherent predictive distribution
projected into each market's native band partition.

Why this shape fits the evidence:

- it starts from genuinely new weather information rather than reshaping the incumbent;
- daily maximum is ordered and continuous, while the current sparse multiclass target treats
  neighboring bands as unrelated classes;
- one continuous density automatically produces coherent exact/range/LTE/GTE probabilities and
  preserves mass when projected correctly;
- pooling residual structure across markets can increase effective training support while retaining
  market-specific deviations;
- mean and conditional scale can be tested separately;
- simple linear/distributional baselines are auditable and well matched to the small number of
  independent dates.

The existing [residual-distribution runtime](../../../src/weather/model/residual_distribution_v1.py) and
[candidate trainer](../../../src/weather/calibration/residual_distribution_v1.py) are the closest scaffold,
but the path is not decision-ready:

1. its PASS uncertainty is whole-date only rather than crossed date × market;
2. it converts all inputs and density to canonical Fahrenheit, conflicting with the repository's
   native-unit invariant and recreating risk near the prior Toronto C/F defect;
3. it uses one global residual width;
4. it has no explicit seasonality;
5. market one-hot effects share one Ridge penalty rather than true hierarchical shrinkage;
6. its required checked-in candidate artifact is absent and live capture is blocked.

Use the scaffold, not its current qualification claim. Either split the U.S. Fahrenheit and Toronto
Celsius lanes or define an explicitly approved dimensionless anomaly representation with strict
conversion-at-boundary tests; do not silently operate Toronto's model in Fahrenheit.

### 5.4 Candidate ladder

Run a small, predeclared ladder on B only. Every row below must use identical PIT population, folds,
weights, and band projection.

| Arm | Candidate | Purpose / abort rule |
| --- | --- | --- |
| A0 | climatology by market and seasonal window | floor for whether the machinery adds value |
| A1 | raw lead-1 PIT NWP daily maximum with empirical residual width | honest physics anchor baseline |
| A2 | regularized pooled residual mean: anchor + market deviations | test whether past forecast error is predictable |
| A3 | A2 + lead-1…7 revision/dispersion block | test genuinely unused multi-run information |
| A4 | A3 + one predeclared physical block from the 12 fields | test radiation/cloud/convective or moisture/wind mechanism |
| A5 | winning mean model + low-capacity conditional scale | only if PIT/coverage diagnostics show stable heteroskedasticity |

Do not begin with a neural network. With approximately 75 target dates per market-hour, a regularized
linear/EMOS-style residual model is a much stronger baseline. A neural model with station embeddings
becomes reasonable only if pooling across markets and years yields enough independent target dates
and it beats the same blocked baselines without leakage.

### 5.5 Use the staged multi-run information deliberately

The staged corpus contains seven fixed lead-day offsets, but operational readers historically select
one lead. Predeclare a compact revision/dispersion family such as:

- lead-1 daily maximum;
- lead-2 through lead-7 daily maxima;
- lead1-minus-lead2 latest revision;
- robust slope over leads 1–3;
- multi-run median, range, standard deviation, and MAD;
- lead-1 deviation from the multi-run median;
- peak timing/profile summaries from the PIT run;
- issue age and exact fixed-lead identity.

**Cheap falsifier:** before fitting probabilities, test rolling-origin prediction of the continuous
lead-1 residual with and without this entire block. Use no market inputs, keep preprocessing inside
folds, and apply crossed inference to market/date residual deltas. If the block cannot improve
out-of-fold residual MAE/MSE or a preregistered proper distribution score by a material amount, stop
without C and without another large candidate build.

### 5.6 Add physical fields as mechanism blocks, not a feature lottery

The available fields span surface heating/radiation, cloud/convective state, precipitation,
moisture/evapotranspiration, and wind/gust. They are physically plausible for daily maximum error,
but availability is not evidence of skill.

Evaluate at most one or two grouped, named mechanisms at a time:

- **surface heating budget:** shortwave/direct/diffuse radiation, cloud, peak timing;
- **convective suppression:** CAPE, cloud/precipitation, changes near the heating window;
- **moisture/evaporative regime:** VPD/ET0 and relevant humidity signal;
- **mixing/advection:** wind/gust and forecast revision.

Each block needs an anchor-only ablation, a mechanism-specific sign/behavior expectation, a B-only
abort threshold, and the same availability at live cutoff. Do not sweep fields, leads, cutoffs,
markets, and transforms and then report the best cell.

### 5.7 Represent season and drift carefully

**Hypothesis.** Residual bias may vary with cyclic day-of-year, distance from the target season,
cutoff, market/coastal regime, and forecast vintage. The current model does not represent this
directly.

Cheap test: add a single strongly regularized block containing `sin/cos(day_of_year)`, target-season
distance, and shrunken market deviations. Evaluate the block as a whole on rolling-origin B folds.
Do not treat the known B/C contrast as proof that seasonality will close the market gap; the
in-season model already loses.

### 5.8 Model conditional uncertainty only after mean signal

The severity tail is concentrated and predictable, but conditional distribution reshaping failed.
That means “where loss occurs” is not automatically “where a remedy works.” Conditional scale is a
different hypothesis because it uses new PIT error information, but it must earn complexity.

Predeclare a few possible scale drivers: multi-run dispersion/revision, cutoff, source state,
anchor-to-observed-high gap, seasonal position, and market regime. First inspect PIT/coverage by
these exact regimes on inner-fold residuals. Then test a low-capacity log-scale model, quantile Ridge,
or two/three fixed scale regimes. Abort if held-out log/RPS/CRPS does not improve without degrading
Brier, tail safety, or market comparison. Do not add a second large HGB for scale.

### 5.9 Training and validation contract

Every candidate must satisfy all of the following:

1. **PIT population.** 2021–2025, target-derived seasonal windows, exact issue/cutoff semantics,
   no stitched endpoint in any candidate feature.
2. **Unit of independence.** Target date × market is the scientific unit; snapshots and bands from
   the same market-day do not increase independent N.
3. **Folds.** Rolling-origin or leave-one-year/date-blocked folds; all cutoffs and bands from a
   market-day stay together. No random row split. Preprocessing, imputation, feature selection,
   and scale fitting occur within the outer training fold.
4. **Selection.** Candidate families and hyperparameters selected only in B/nested folds. C is
   scored once under a new explicitly allocated ledger decision.
5. **Weights.** Equalize dates and markets before snapshots/bands; report sensitivity to the
   project-approved weighting hierarchy.
6. **Targets.** Use deduplicated WU settlement-proxy labels with provenance frozen before outcomes;
   model label reliability or predeclare source-quality exclusions, never remove rows because the
   candidate lost there.
7. **Scores.** Continuous CRPS/MAE diagnose physical forecast quality; band Brier, log score/RPS,
   probability mass, and protected-slice safety judge the served distribution. Final paired Brier
   versus market remains the goal metric.
8. **Readouts.** Primary 09:00–14:00 and severity tail remain readouts until their independent
   clusters can support a decision. Do not turn a low-power slice into a hard accept/reject gate.
9. **Power.** With 12 market clusters, effects at or below roughly 2.5–3.2% of the current gap are
   individually unconfirmable. Batch small mechanism-consistent improvements and prefer candidates
   plausibly closing at least ~5% before spending C.
10. **Controls.** Exact clone, intentionally damaged model, target permutation, time-shifted feature,
    and anchor-only baselines must behave as expected.

### 5.10 Complete artifact and model card

Every fitted artifact should carry a machine-readable receipt with:

- candidate ID, code SHA, training-corpus hash, label hash, feature-contract hash;
- market/unit lane, native-unit proof, band-geometry hash;
- target dates/years, per-market counts, missingness and source availability;
- exact features and transformations, issue/lead semantics, source provenance;
- model family, objective, parameters, random seeds, dependency versions;
- outer/inner fold membership and preprocessing ownership;
- OOF baseline/candidate metrics, crossed intervals, MDE/power, protected slices;
- calibration/scale fit population, mass and coherence diagnostics;
- negative/positive control results;
- replay/serve parity result and release binding;
- `research_only`, `promotion_authorized`, and failure/stop reason.

Serving must reject an artifact whose receipt, schema, unit lane, feature availability, or release
binding is not exact.

---

## 6. Data and label improvements

### 6.1 Make the staged PIT corpus durable without serving it

The staged rows currently live in two temporary roots. One root alone contains only 37 of 58 sealed
dates and would leave the B fit with 7 rather than 23 dates. Temporary storage is too fragile for
the project's one remaining information lever.

Create a research-only corpus namespace that the serving analog loader cannot discover. Track a
small manifest and Merkle/content hashes in Git; retain the large rows in an explicitly backed-up
local/object store according to the existing ignored-data policy. The manifest should bind both
roots, all markets/dates/leads/fields, request parameters, response hashes, parser version, and a
known-row positive control. Adoption into any serving-readable archive must be a separate measured
change after replay.

### 6.2 Backfill the feature population actually needed for training

The 2026 B/C panel proves availability, not training sufficiency. The candidate population is
2021–2025. Before claiming the new fields can train a model:

1. run a breadth/coverage probe for all 12 markets, the target-derived seasonal dates, and required
   lead offsets;
2. freeze the supported 12-field contract and explicit nine-field exclusions from evidence;
3. backfill only the predeclared fields/leads needed by the first candidate;
4. verify hourly completeness, native units, issue timestamp, lead identity, non-finites,
   duplicates, and cutoff availability;
5. publish per-market/year/field availability matrices and response hashes;
6. keep the provider free-tier/no-credential boundary.

The current 21-field corpus contract is all-or-nothing even though nine fields are known unavailable.
Repair it with an evidence-bound supported-field policy, not by silently deleting mappings.

### 6.3 Resolve the historical/live forecast-anchor mismatch

Historical training has a single Open-Meteo anchor; live serving can use a median across available
Open-Meteo, Weather Forecast, and ECCC values. `forecast_source_count` and disagreement can therefore
be invariant/missing in training but nonzero live.

Cheap falsifier on captured input:

1. score the exact historical-equivalent Open-Meteo anchor;
2. score the live multi-source median;
3. score a PIT-trainable ensemble/residual correction for only the combinations with honest history.

If the multi-source anchor wins, either build its PIT corpus and train it explicitly or serve the
same single-source contract used in training. Do not expose a one-source-trained HGB to synthetic
live disagreement features and call that parity.

### 6.4 Treat settlement and observation mutation as measurement error

The latest floor investigation proved two mechanisms: upstream WU rows can be restated, and empty
history can make instantaneous current temperature masquerade as a running maximum. It did not
measure how common each mechanism is.

Next read-only diagnostic:

- classify every `high_so_far` decrease by captured source state;
- distinguish mutable-row restatement, empty history, day-boundary carryover, join gaps, and unknown;
- measure by market, local hour, release era, and settlement agreement;
- compare the vendor summary maximum, immutable captured running maximum, and final settlement;
- predeclare a monotone cutoff-aligned maximum with provenance before changing serving.

Do not change the serving floor from two traced rows alone. The floor is the only served change with
a measured improvement and should remain fail-closed until a population-level replacement is
verified.

---

## 7. Mission and delegation audit

### 7.1 The system is fast but too granular

For missions `-09-50a` through `-09-68a`, median handoff-to-branch-tip time was about 30.9 minutes
and mean time about 32.3 minutes. Nineteen missions were dispatched in roughly 30 hours. The agents
are not slow.

But speed per mission hides serial rework:

- `-09-50a` through `-09-55a` walked one retrain path through parent release, bootstrap, held-branch
  audit, research parent, missing producer, and PIT provenance wall.
- `-09-63a` through `-09-68a` used five follow-up missions after the candidate gate failed to trace
  repaired zeros, floor provenance, served-floor rescoring, settlement labels, and mathematical
  satisfiability.

The answers were valuable. The mission boundary was too narrow. Strict write scope is sensible;
read-only causal tracing should not stop at the first exception.

### 7.2 Better mission unit: a bounded decision graph

Every mission should own one decision, not one guessed blocker. It should have:

1. stable mission ID and exact base SHA;
2. the decision its result will change;
3. goal metric and smallest worthwhile effect;
4. facts tagged `ARTIFACT`, `CODE_TRACE`, `OPERATOR_DECISION`, or `HYPOTHESIS`;
5. a P0 cheapest killer against actual content, not schema/file count;
6. instrument certification and gate satisfiability;
7. a bounded adaptive read-only budget to trace the dependency graph to terminal cause;
8. a separate, narrow write allowlist;
9. GO, NO-GO, and BLOCKED actions;
10. explicit alpha/ledger impact;
11. output artifact, evidence packet, report, branch, and per-file roll paths;
12. the prior canonical sentence that becomes false under each verdict.

Diagnostic read scope should be repository-wide unless sensitive data or stateful tools are named as
exceptions. Implementation writes remain file-disjoint and narrow. Stop only at a user/operator
decision boundary, a stateful authorization boundary, or the mission's declared evidence budget—not
at the first source-file exception.

### 7.3 Certify the mission premise before building

Before dispatch, require:

- current base and divergence receipt;
- actual artifact census plus sample-content validation;
- outcome artifact: “if this never worked, what would still be empty?”;
- certified evaluation-surface ID/hash;
- gate satisfiability at planned N;
- feature/label/provenance matrix;
- candidate-native MDE;
- cheapest whole-track falsifier;
- what work is cancelled under GO and NO-GO;
- why this mission has more decision value than one direct candidate attempt.

This would have caught the missing corpus producer, inactive parent, wrong served floor, and no-op
agent outcomes earlier.

### 7.4 Exit zero, branch names, and green gates are not outcomes

Commit `7b71de72` records a scheduled wake that exited successfully but did no work. Other history
shows countable maker days without quotes, readiness without fills, and a streak that gated nothing
on the active path.

Every unattended process and mission needs a nonce-bound receipt:

```json
{
  "run_id": "...",
  "base_sha": "...",
  "started_at": "...",
  "ended_at": "...",
  "outcome": "worked | skipped | blocked | failed",
  "reason": "...",
  "work_count": 0,
  "output_paths": [],
  "output_hashes": [],
  "last_successful_output_at": "..."
}
```

Monitors should evaluate this receipt and the output artifact, not process eligibility or exit code.

### 7.5 Mission state cannot be inferred from filename order

Roadmap guidance says the newest handoff is live and older files are historical, but missions now
overlap. A handoff remains live until accepted, rejected, withdrawn, held, or superseded. Handoff
and report filenames also use different nominal dates, requiring commit archaeology to pair them.

Generate a Git-backed mission index with:

- stable mission ID;
- commissioned, dispatched, handback, verified, accepted, merged, held, withdrawn states;
- base and tip SHAs;
- dependencies and file ownership;
- report and evidence hashes;
- ledger slot and alpha state;
- roll verdict and acceptance receipt;
- `superseded_by` / next decision.

### 7.6 Accepted evidence must survive the branch

At the inspected snapshot there were 134 local branches, 72 remote-tracking refs, 58 worktrees, 35
remote branches not merged to `origin/master`, and 22 unique report paths reachable on local refs
but absent from `origin/master`. Nine of the latest ten reports were still only on topic branches.

This has already caused one rescue of 45 branch-only reports. Do not delete those branches yet.
Instead:

1. land every accepted immutable report and compact evidence packet independently of whether code is
   held;
2. generate a branch-disposition manifest with tip/base/ahead/behind, report hash, conflicts,
   status, supersession, and archive receipt;
3. retain archival refs/tags for unmerged code after evidence is harvested;
4. only then amend the “never delete” rule and remove inactive worktrees;
5. cap active missions/worktrees to actual agent and human review capacity.

### 7.7 Make the delegation contract machine-checkable

The existing docs audit explicitly does not prove semantic currency and omits several load-bearing
canonical documents from its required lists. Add `weather.operations.mission_contract_audit` and
extend the docs audit to validate:

- current-state freshness and line cap;
- handoff/report pairing and stable IDs;
- required decision, falsifier, provenance, MDE, controls, reproduction, roll, and not-done fields;
- accepted-report archive receipt;
- active claim conflicts and supersession;
- campaign ledger consistency;
- backlog age and rank-1 ownership;
- reproduction paths or explicit supplied-fact tags.

### 7.8 Portfolio metrics

Track outcomes and learning efficiency:

- dispatch → handback → verified → evidence-on-master latency;
- blocker depth resolved per mission;
- correction-chain length and premise-kill rate at P0;
- percentage of load-bearing claims reproduced from opened artifact content;
- production/clean-host reproduction rate;
- accepted reports archived on master;
- canonical freshness and active claim conflicts;
- rank-1 risk age and deferral reason;
- retractions per 100 accepted claims;
- missions per candidate fitted, sealed evaluation, retrain, and served improvement;
- remaining gap closed with crossed intervals;
- primary-window and severity-tail Brier deltas;
- execution-tape rows/days, quote permissions, orders, fills, and after-cost fills.

---

## 8. Repository engineering and operations audit

### 8.1 Scale and complexity

The inspected ref contains roughly 1,791 tracked files. The checked-out source snapshot has about
303,000 lines under `src/weather` and 121,000 test lines. Nineteen source modules exceed 2,000 lines;
the largest critical-path modules include PIT evaluation, pooled replay, live scorecards, snapshot
storage, nightly retrain, market making, and production readiness.

Large modules are not automatically defects, and a broad rewrite would delay learning. Refactor
where history shows repeated causal confusion:

- extract a typed evaluation-surface contract from PIT evaluation;
- extract canonical crossed inference;
- isolate candidate training from nightly orchestration;
- isolate snapshot source-state classification from storage;
- isolate maker outcome receipts from policy;
- generate schema ownership from local declarations where possible.

Set a complexity/churn budget for these modules and require new model families to use the extracted
contracts rather than adding another parallel implementation.

### 8.2 CI does not match the production platform

CI runs Ubuntu with Python 3.11, compileall, docs audit, and pytest. Production is Windows and relies
on PowerShell, path bootstraps, scheduled tasks, supervisor/process behavior, and native path
semantics. This host's broken venv demonstrates that the documented bootstrap is not currently
self-verifying.

Add a bounded Windows CI job for:

- clean virtual-environment bootstrap and import smoke;
- `weather.paths`, `sitecustomize`, native separator, and non-root-CWD tests;
- PowerShell parse/static checks and safe `-WhatIf`/help paths;
- supervisor fingerprint/roll-verdict fixtures;
- exact train/serve unit and captured-input replay contracts;
- mission/docs currentness audit.

Add selective `ruff`/static-import checks and a changed-module complexity budget only after the
Windows contract is green. Do not launch a repository-wide style rewrite.

### 8.3 Roll verdict compares against stale local master

The authoritative `roll_verdict.ps1` compares `master...branch`. `quiet_window_merge.ps1` invokes it
before fetching and before verifying local master equals origin. In the `-09-68a` report this
classified 67 paths against a stale base although the actual mission delta was three files. It
remained safely roll-free by luck of file types, but the changed set was wrong.

Fix the sequence:

1. fetch/prune;
2. verify exact base/ancestry and clean integration worktree;
3. compute the actual merge delta against the intended integration SHA;
4. emit a classification for every path, including docs/config/tests/PowerShell;
5. then decide quiet-window handling;
6. run focused cumulative tests after each code-bearing merge group and docs audit after canon groups.

### 8.4 Generated config churn obscures history

`config/location_market_events.json` accumulated more than half a million changed lines across 48
commit touches since July 9. Full generated rewrites advance master, create branch conflicts, and
hide meaningful review changes.

Store reviewable source metadata in a stable normalized form and generate the runtime snapshot
deterministically. If the large file must remain tracked, use stable ordering, content-based update
suppression, and a compact semantic-diff receipt in each commit.

### 8.5 Direct outcomes remain missing

The latest canon authorizes execution capture but does not prove a continuously producing,
settled, gap-accounted execution tape. The paper maker had no quote rows in more than half a million
post-boundary intents and has never written a fill tape. Treat these as missing outcomes, not a
readiness score.

Required operations counters:

- last execution-tape output time, rows, markets, gaps, and settled days;
- quote permissions emitted and rejection reasons;
- orders submitted/acknowledged/cancelled;
- fills observed and independently reconciled;
- after-cost scored fills;
- promotion-countable date clusters, not contiguity;
- capture gaps and settlement completeness directly.

The ranked operations backlog should require the highest unowned risk to be assigned, mitigated, or
explicitly deferred with owner and deadline before lower-ranked work is dispatched. This is how log
rotation, orphan processes, overnight end gates, and monitor no-ops stop becoming incidents after
long periods of known exposure.

### 8.6 Artifact weight needs an explicit lifecycle

The checked-out `artifacts/` tree contains 108 files and approximately 388 MB, including 26 pickle
files and 81 JSON manifests. The binary artifacts are important release evidence, but they are
opaque in review and the served fits are much older than the surrounding control code.

Require every retained binary to have an owning release/candidate, content hash, reproducible fit
receipt, dependency/security provenance, disposition (`served`, `candidate`, `quarantined`,
`superseded`), and clean-checkout load test. Keep the small manifest and golden evaluation evidence
durable in Git; move superseded large blobs only through an explicit migration that preserves
release reproducibility. Do not casually delete historical served artifacts.

Direct Python dependencies are exactly pinned, which is valuable for sklearn pickle compatibility,
but transitive packages are not locked with hashes. Add a reproducible lock/SBOM and load pickle
artifacts only after verifying their trusted manifest/hash. Pin CI actions by reviewed commit digest
if the repository adopts a stronger supply-chain posture. These are P2 hardening items, not reasons
to delay the model thin slice.

---

## 9. What the commit history says

### 9.1 Quantitative history

At inspected `origin/master`:

| Period / measure | Result |
| --- | ---: |
| Total reachable commits since initial prototype | 866 |
| Reachable commits since 2026-07-09 | 703 |
| Non-merge commits since 2026-07-09 | 600 |
| First-parent commits since 2026-07-09 | 471 |
| Merges since 2026-07-09 | 103 |
| Non-merge commits touching `docs/` | 471 (78.5%) |
| Non-merge commits touching `src/` | 127 (21.2%) |
| Non-merge commits touching `tests/` | 123 (20.5%) |

The documentation volume contains real research and trustworthy NO-GOs; it is not mere ceremony.
But the output mix shows that interpretation, qualification, and operations have dominated new
forecast capability.

Early history is hard to audit: 154 of the first 166 commit subjects are variants of `add`, `added`,
or `Cleanup`. The core model, forecast history, replay, maker policy, and nightly retrain were built
in that opaque period. Commit quality improves sharply after July 11. Keep conventional, behavior-
describing commit subjects and add a small provenance index for the opaque foundational anchors.

### 9.2 Phase interpretation

#### Prototype/model construction — May 29 to July 10

The Toronto projector became a multi-market model and operations platform extremely quickly. Core
model and policy structures were added in a few days, and the served model artifacts froze early.

**Lesson:** foundational behavior needs characterization tests and provenance before later agents
infer intent from sparse commit messages.

#### Production and release hardening — July 11 to July 26

Very large vertical changes landed, including production readiness and PIT candidate machinery. One
PIT simplex merge was reverted and reapplied minutes later. Release scaffolding became substantial
before a minimal “one research retrain completes” path was proven.

**Lesson:** require a vertical smoke outcome before expanding the surrounding qualification graph.

#### Operations, maker, and floor pivot — July 27 to August 5

An enrichment loop was deployed and disarmed within an hour after its execution-identification
premise failed review. The maker was shown never to have placed a quote. The observed-high floor was
the one durable served improvement, reducing the served model/market ratio from 1.6639 to 1.4980,
although little of the gain landed in the primary window.

**Lesson:** measure the causal outcome artifact before building eligibility or enrichment around it.

#### Falsification and gap audit — August 6 to 9

The project found an all-day, fleet-wide train/serve routing defect and repaired it, then measured a
precise near-null: correctness moved at most about 0.6% of the distance to parity. The retrain chain
then discovered parent-release circularity, a missing producer, and the PIT provenance wall one
mission at a time.

**Lesson:** correctness is mandatory but is not evidence of skill; whole-path read-only tracing
should precede implementation missions.

#### New-information and instrument audit — August 10

The loss tail was shown predictable from own information, but a conditional reshape lost even to
global smoothing on its own B training objective. That closed reshaping and sharpened the remaining
direction: know more. The project staged the PIT fields, pre-registered a candidate, then discovered
that its safety instrument was judging a floor production had not served and a gate that becomes
unsatisfiable with panel size.

**Lesson:** a valid hypothesis cannot rescue an invalid judge. Certify the surface, controls, and
gate mathematics before allocating a confirmatory decision.

### 9.3 History hotspots

High-churn paths point directly to recurring failure modes:

- `STATE_OF_PLAY.md`: current truth rewritten/appended frequently but still stale;
- `location_market_events.json`: massive generated churn and branch divergence;
- `ESTABLISHED_FINDINGS.md`: necessary distillation becoming another large correspondence archive;
- `schema_registry_recent_data.py`: centralized capture-closure coupling;
- `status.ps1`: repeated corrections for stale/no-op/false outcome claims;
- `pooled_candidate_replay.py` and `nightly_retrain.py`: large, changing machinery despite zero
  completed retrains.

Use history-weighted refactoring: extract stable contracts where churn and retractions co-occur,
not wherever a file is merely long.

---

## 10. External research and how it should influence this project

External work supports the proposed design direction, not a claim of project-specific skill:

- Gneiting and colleagues' ensemble model output statistics (EMOS) work frames post-processing as
  estimating a predictive distribution and optimizing a proper score such as CRPS. See
  [Calibrated Probabilistic Forecasting Using Ensemble Model Output Statistics](https://doi.org/10.1175/MWR2904.1).
- Rasp and Lerch show that nonlinear distributional regression can use auxiliary meteorological
  predictors and station embeddings to improve 2 m temperature post-processing in a much larger
  station dataset. That supports pooling and auxiliary PIT fields, but their sample scale does not
  justify starting this project with a neural network. See
  [Neural networks for post-processing ensemble weather forecasts](https://arxiv.org/abs/1805.09091).
- An ECMWF technical memorandum found linear regression, random forests, and neural networks had
  similar ability to learn situation-dependent near-surface temperature/wind errors, with reported
  RMSE improvements of 10–15% in its setting. This is a strong reason to require linear baselines
  before more capacity. See
  [Statistical modelling of 2m temperature and 10m wind speed forecast errors](https://www.ecmwf.int/en/elibrary/81297-statistical-modelling-2m-temperature-and-10m-wind-speed-forecast-errors).
- Time-series EMOS work explicitly models seasonality and autocorrelation in temperature forecast
  errors across stations and lead times. That supports a small residual-revision/season block as a
  testable hypothesis. See
  [Time Series based EMOS for Temperature Forecasts Postprocessing](https://arxiv.org/abs/2402.00555).
- Spatial hierarchical post-processing improves parameter estimation by pooling related locations
  while retaining local effects. The project has stations rather than a dense grid, but the
  partial-pooling principle is relevant to 12 sparse market-specific fits. See
  [Spatial forecast postprocessing: The Max-and-Smooth approach](https://arxiv.org/abs/2209.00477).
- NOAA's comparison of surface-temperature MOS methods uses a long reforecast training period and
  simple bias/MOS baselines. It reinforces that a sophisticated learner should beat raw guidance,
  decaying bias, and regularized MOS on the same blocked population. See
  [Comparing and Combining Deterministic Surface Temperature Postprocessing Methods over the United States](https://repository.library.noaa.gov/view/noaa/45318).

The common message is: start from honest NWP, learn forecast error with proper blocked validation,
pool where local samples are sparse, and emit a coherent distribution. None of these papers proves
that the resulting distribution will beat this market. The repository's sealed market comparison
must decide that.

---

## 11. Prioritized improvement backlog

### P0 — before another confirmatory model decision

| Rank | Outcome | Acceptance test |
| ---: | --- | --- |
| 1 | Reconcile current canon and ledger | no active claim conflicts; state reflects `-09-68a`; ledger slot 10 closed unused; backlog regenerated |
| 2 | Base-fresh mission startup | every handoff/handback records exact base/divergence; stale execution aborts or uses explicit ref reads |
| 3 | Certified golden evaluation surface | served distributions/floors/labels/release hashes; clone and damaged controls; native-unit/mass/provenance PASS |
| 4 | Satisfiable gate taxonomy | absolute incumbent integrity separated from paired candidate safety; false-stop behavior bounded at planned N |
| 5 | Canonical crossed inference | residual, stage ablation, candidate comparison, MDE, and power use one tested implementation |
| 6 | Durable research-only PIT corpus | both temporary roots bound and backed up; training-range coverage/field matrix; no serving loader can read it |
| 7 | Minimal fit-to-evaluation command | anchor baseline fits and scores without active release or production write; complete outcome/model-card receipt |
| 8 | Windows/bootstrap repair | canonical venv recreates; Windows CI smoke and full test command run |
| 9 | Accepted evidence archive | all accepted reports/evidence on durable master/archive ref independent of held code |
| 10 | Direct execution outcome receipt | producer/tape days/rows/gaps visible; zero work cannot appear successful |

### P1 — first B-only model programme

1. Establish climatology, raw lead-1 NWP, and regularized anchor-residual baselines.
2. Screen the lead-1…7 revision/dispersion block on continuous residual prediction.
3. Screen one physical feature block, chosen and frozen before scoring.
4. Test the cyclic season block with strong shrinkage.
5. Compare local per-market fits with a pooled base plus shrunken market deviations.
6. Test a conditional scale arm only if predeclared residual diagnostics support it.
7. Use crossed stage ablation to remove/bypass serving stages that do not help the final distribution.
8. Select one candidate in B and calculate its own MDE/power before allocating C.

### P2 — after a candidate is genuinely decision-ready

1. Allocate a **new** campaign slot; never reuse decision 10.
2. Freeze the exact candidate, evaluator, gates, surface hash, exclusions, and controls.
3. Score C once.
4. If it passes, run untouched captured-input replay, shadow, and release binding before promotion.
5. If it fails, update established/retracted findings and close the mechanism; do not tune on C.
6. Use execution tape and paper harvest to estimate fill fraction and after-cost value only after
   forecast skill is established.

---

## 12. A better sequence for the next missions

These are intentionally outcome-sized mission packets. Each may contain several read-only tracing
steps; split implementation only for write conflicts or operator decisions.

### Mission 1 — current-truth and evidence reconciliation

Reconcile `STATE_OF_PLAY`, `ESTABLISHED_FINDINGS`, retractions, campaign ledger, active backlog,
mission index, and latest report archive at one exact ref. Produce a machine-readable claim and
mission-state snapshot. No model decision and no alpha.

### Mission 2 — certify the judge end to end

Build the golden evaluation table from actual served artifacts, bind labels/provenance, run clone and
damaged controls, quantify replay divergence, replace decision-bearing date-only inference with the
canonical crossed method, and calculate every gate's satisfiability. Continue read-only through all
dependencies instead of stopping at the first mismatch.

### Mission 3 — bind the durable PIT training corpus

Back up and hash the staged B/C corpus, probe 2021–2025 supported-field/lead coverage, freeze the
research-only supported-field contract, and prove serving cannot discover the new rows. Stop before
provider expansion or serving adoption.

### Mission 4 — prove the research vertical slice

Fit and score climatology, raw lead-1 anchor, and a simple native-unit residual distribution through
one command. Require complete model cards, native-unit tests, mass/coherence, crossed intervals,
MDE, and explicit worked/stopped receipts. No C.

### Mission 5 — test the strongest new-information block

Run the lead-1…7 revision/dispersion residual falsifier, followed only if it passes by one frozen
physical field block. Compare to anchor-only on identical rolling-origin B folds. Stop the whole
direction if the block cannot clear its materiality threshold.

### Mission 6 — test pooling, season, and scale parsimoniously

Compare local versus pooled/shrunken market residuals; test one cyclic-season block; test conditional
scale only if residual coverage requires it. Select one B winner or close the track. Do not create a
mission per coefficient or market.

### Mission 7 — preregister the one C decision

Only after the candidate and judge are frozen, allocate a new ledger slot, reproduce hashes on both
hosts, verify candidate-native power, and specify GO/NO-GO actions. This mission touches no C scores.

### Mission 8 — execute and close the decision

Score C once, reproduce on the production host, update canon/ledger/report archive in the same
acceptance transaction, and either close the mechanism or authorize untouched shadow replay.

### Mission 9 — prove direct execution observability

Independently of model promotion, ensure the forward execution tape produces rows or explicit
zero-work receipts; expose gaps, settled days, quotes, orders, fills, and after-cost reconciliation.
Do not infer executions from book deltas.

### Mission 10 — simplify the system from measured attribution

Use crossed stage ablation, history churn, and mission-yield data to delete or isolate losing serving
stages, stale canonical surfaces, redundant monitor proxies, and inactive worktrees—only after
report/evidence archival is proven.

---

## 13. Things to stop doing

- Do not call a maintenance refit “the better model” before it can change information, objective,
  or model structure.
- Do not allocate confirmatory alpha before the evaluator, controls, interval coverage, and gate
  satisfiability are certified.
- Do not count snapshots, bands, or synthetic rows as independent evidence when the information unit
  is a market-day.
- Do not turn low-power primary-window slices into binary gates; use them as readouts until powered.
- Do not use market probability as a feature or router for the own-information forecast claim.
- Do not infer outcomes from exit zero, branch names, schemas, row declarations, green readiness,
  countable days, or process liveness.
- Do not dispatch another mission on a premise that can be killed by opening the actual artifact or
  tracing the producer/consumer path.
- Do not make one mission per exception when a bounded read-only dependency trace can reach the
  terminal cause.
- Do not leave accepted reports only on topic branches.
- Do not delete branch/worktree evidence until every unique report has an archive receipt.
- Do not require quiet-window handling for roll-free work.
- Do not weaken the observed-high floor or amend a frozen protocol after seeing its failure.
- Do not copy staged PIT fields into the serving archive before replay measures the effect.
- Do not broaden to paid providers or a new source hunt before the already staged free PIT fields are
  evaluated.
- Do not launch a repository-wide refactor, neural-network programme, or feature sweep before the
  simple residual baselines pass.

---

## 14. Definition of meaningful progress

The project is closer to its goal when one of these counters changes—not when another mission merely
returns:

1. **Judge certified:** actual served surface, labels, crossed inference, controls, and gates all
   pass one immutable receipt.
2. **New information bound:** training-range PIT fields/leads are available, durable, and serveable
   with exact parity.
3. **Candidate fitted:** at least one coherent own-information candidate completes blocked B OOF
   against raw NWP, climatology, incumbent, and market benchmark.
4. **Candidate confirmable:** its expected effect exceeds its candidate-native MDE and no protected
   safety endpoint regresses.
5. **Sealed decision closed:** one frozen candidate is scored once on C under a new ledger slot.
6. **Served improvement reproduced:** captured replay and shadow show a crossed positive final-served
   delta without market input.
7. **Execution learned:** a forward tape identifies quote/order/fill outcomes and after-cost value.

The strongest near-term success would be modest but decisive: a certified evaluation instrument,
an immutable PIT corpus, and one simple residual baseline that either demonstrates a measurable
own-information improvement on B or cleanly falsifies the remaining feature direction. Both outcomes
are more valuable than another layer of readiness around a model that has not learned anything new.

---

## 15. Verification and reproducibility notes

Read-only commands used to anchor this audit included:

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
git rev-list --left-right --count HEAD...origin/master
git log origin/master --first-parent --date=iso-strict
git diff --shortstat master..origin/master
git show origin/master:<path>
git worktree list --porcelain
git branch --no-merged origin/master
git branch -r --no-merged origin/master
```

Repository checks performed:

```text
Bundled Python 3.12: compileall -q app src tests                 PASS
Bundled Python 3.12 + src: weather.operations.agent_docs_audit PASS
Canonical venv Python 3.11: full pytest                         NOT RUN
Reason: configured interpreter executable is missing
```

This audit itself changes only `CODEX_AUDIT_20260811.md`. It authorizes no live serving, scheduled
task, artifact, data, promotion, or trading mutation.
