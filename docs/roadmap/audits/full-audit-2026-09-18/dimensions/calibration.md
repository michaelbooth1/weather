# Audit dimension: Calibration, candidate replay and scoring

Auditor key: `calibration`. Date: 2026-09-18. Host: production (read-only audit; no code, tests, or CLI were run).

## 1. Scope and method

**In scope:** `src/weather/calibration/` (34 modules, ~1.3 MB of Python) and `src/weather/scoring/` (2 modules, 240 lines).
Adjacent code was opened only where a trace required it: `src/weather/model/calibration_runtime.py`,
`model/current_blend.py`, `model/continuous_density.py`, `model/model_distribution.py`, `model/toronto_model.py`,
`model/variant_prediction_runtime.py`, `collection/live_variant_predictions.py`, `backtesting/replay_backtest.py`,
`reporting/location_analysis/pooled_f_retrain_location_gate.py`, `artifacts.py`, `units.py`, and the committed JSON
manifests in `artifacts/calibration/`.

**Method:** Read / Grep / Glob with explicit paths only, plus whitelisted `git log` / `git show` and non-recursive `ls`.
Nothing under `data/` was opened. No Python was executed, so every numeric claim below is either read out of a
committed file or is hand arithmetic that I label as such. Each structural claim was traced through at least one
concrete call path; the trace is given with the finding.

**Canonical docs checked for prior knowledge:** `docs/operations/ESTABLISHED_FINDINGS.md` (section index, 4c, 5, 6, 7, 8),
`RETRACTED_AND_FALSE_LEADS.md` (sections 1-3), `REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`.

**Recent activity:** `git log -- src/weather/calibration src/weather/scoring` shows the package has been effectively
frozen since 2026-08-09 (`669ad6bb9`); the single later touch (`dcf714a4a`, 2026-09-09) is cold-archive plumbing in
`residual_distribution_corpus.py`. That is consistent with the standing "no new model-alpha work" decision. The
findings below are therefore mostly about the *evidence machinery that will be trusted when work resumes*, and about
what is loaded by serving today.

## 2. Headline

The package contains two generations of code with very different rigor.

- The **newer lanes** (`residual_distribution_v1.py`, the pooled "production point-in-time" lane in `pooled_training.py`,
  the bounded replay adapter, `simplex_calibration.py`, the nested calibration in `feature_model.py`) are careful:
  rolling-origin folds with embargo, inner-OOF selection, fit receipts, label stripping before prediction, fail-closed
  errors. The project also caught and neutralised its own same-holdout fit/report defect in the legacy band trainer.
- The **older gate machinery that still produces the PASS/BLOCK verdicts** has several checks that cannot fail or that
  measure something other than what their label says: a leakage audit that is a hard-coded constant, a fidelity gate
  that passes when it cannot measure, a "held-out days" count that counts market-days not dates, and a served
  calibration artifact whose own training record shows it scoring worse than identity with nothing gating on that.

Health grade: **C**. The base-model leakage risk is structurally low (prior-year-only training cache, ESTABLISHED_FINDINGS 4c),
so these are primarily *false-assurance* defects rather than proven contamination of a published number.

## 3. Findings

### calibration-1 (HIGH) - The leakage audit is a hard-coded constant, and gates and reports consume it as a verdict

`blocked_validation_audit()` returns `"ok": True, "leak_count": 0, "leaks": []` as literals
(`src/weather/calibration/blocked_validation.py:358-368`). The function never calls `validation_splits()` or
`split_leakage()`. `split_leakage()` has no caller anywhere under `src/` (grep: only
`tests/calibration/test_blocked_validation.py:39`).

Git history shows this was not always so. `git show e0b26bc49:src/weather/calibration/blocked_validation.py`
(2026-06-18) computes `leaks.extend(split_leakage(...))` and returns `"ok": len(leaks) == 0, "leak_count": len(leaks)`.
The next commit, `4a5efaa26` (2026-06-19, message "add"), replaced the computation with summary arithmetic and constants.

Consumers, each traced:

- `pooled_candidate_scoring.py:1212-1215` - `blocked_candidate_validation_gate()` has
  `if not split_audit.get("ok"): reasons.append("... blocked split leakage issue(s)")`. This branch is unreachable.
- `pooled_candidate_replay_report.py:325-327` - renders `["Leakage audit", "PASS" if split_audit.get("ok") else "FAIL"]`
  and `["Leak count", ...]` into every candidate replay report.
- `reporting/location_analysis/pooled_f_retrain_location_gate.py:330-335` - the `training_validation_provenance` gate is
  `PASS` when `artifact["blocked_validation"]["ok"] is True`.
- `pooled_training.py:1680, 1726, 1852, 1980, 2122, 2357` and `feature_model.py:495, 737` stamp the constant into
  artifacts and reports.
- `tests/calibration/test_blocked_validation.py:42-50` asserts `audit["ok"] is True` and `audit["leak_count"] == 0`
  on clean rows only. There is no negative test, so the suite cannot notice that the audit is inert.

Two further points:

1. Even the original check was close to tautological: it verified that splits built by `validation_splits()` do not share
   partition keys with themselves. Nothing in `run_pooled_candidate_replay()` (`pooled_candidate_replay.py:3501-3921`)
   compares the candidate artifact's *training dates* with the replay corpus dates (grep for
   `train*_dates|holdout|held_out|exclude` in that file: no matches). "Leakage audit: PASS" in the replay report
   therefore never tested the question a reader assumes it tested.
2. The `leave_one_market_day` mode (`blocked_validation.py:82-94`) holds out one `(market, date)` and trains on the same
   calendar date in the other markets; its leak check uses partition key `market_day`, so same-date cross-market reuse
   is invisible to it by construction. It is used as the single-year inner mode in `feature_model.py:592`.

Mitigation that keeps this from being critical: base HGB artifacts cannot contain target-year rows
(`ESTABLISHED_FINDINGS.md:1522-1541`), and the production PIT lane does real locked-date exclusion
(`pooled_feature_cli.py:312-348`, `pooled_training.py:2027-2044`).

Known status: not recorded in `ESTABLISHED_FINDINGS.md`, `RETRACTED_AND_FALSE_LEADS.md` or any file under
`docs/operations` (grep for `blocked_validation|leak_count|Leakage audit`: no matches). **New.**

Recommendation: either restore the computed audit (bounded, date-partition modes only) and add a negative test with a
deliberately leaky split, or delete the field and the "Leakage audit" report row. Separately add the check that actually
matters: artifact training-date set intersect replay-corpus date set must be empty, read from `corpus_lineage`.

### calibration-2 (HIGH) - The replay fidelity gate passes when it cannot measure, and covers only the same-identity subset

`replay_gate_status()` (`pooled_candidate_replay_diagnostics.py:484-522`):

- If `same_identity_n == 0` and `require_exact_identity` is False, it sets `fidelity_ok = True` with message
  `"WARN: no exact-identity snapshots yet; strict canary not required"` (lines 507-509), and `global_ok` is then True.
- `require_exact_identity` defaults to False everywhere: `pooled_candidate_replay.py:3676` (`getattr(..., False)`) and
  `:3996` (`action="store_true"`), and likewise in `nightly_retrain.py:3080`, `daily_refresh_cli.py:637`,
  `promotion/cli.py:140`, `promotion_gauntlet.py:566`, `active_variant_shadow_refresh.py:1071`. Grep of `scripts/` for
  `require-exact-identity|RequireExactIdentity` returns nothing, so no scheduled wrapper opts in.
- "Same identity" means `recorded_identity_hash == replayed_identity_hash` (`backtesting/replay_backtest.py:178-183`),
  where the replayed hash is the identity of the code and artifacts on disk *at replay time*. Rows whose recorded identity
  differs fall into `changed` and are "reported separately ... instead of failing the canary" (docstring, lines 166-173).
  They are not gated at all.
- The threshold is `FIDELITY_FAITHFUL_L1 = 0.01` (`replay_backtest.py:96`).

Set against the project's own measurement (`REPLAY_DOES_NOT_REPRODUCE_WHAT_WE_SERVED_2026-08-11.md`): 54 identities
under 10 commits, exact reconstruction available for 111 / 28,254 rows (0.39%) and 0 / 368 decision rows, median
divergence L1 0.0154 against a 1e-12 bar. So on a historical corpus the expected state of this gate is either
"no same-identity rows, PASS with a WARN" or "a small recent subset gated at a tolerance ten orders of magnitude looser
than the bar the project used to retire the 'incumbent reproduces' claim". The verdict string a reader sees is
`replay_gate.global_ok = True`, and `verdict` / `cutover_decision` (`pooled_candidate_replay.py:3773-3774, 3791`) are
built on it, up to `CUTOVER_READY`.

This is the "a stopped counter looks satisfied" shape from the project's own memory notes.

Known status: the underlying non-reproduction is **known and the thread is closed**. The gate's fail-open default and
subset coverage are not recorded anywhere I could find (grep of `docs/operations` for
`strict canary|require-exact-identity|exact-identity|same_identity`: no matches). **New** as a code defect.

I could not measure how often `same_identity_n == 0` occurs on the current pinned corpus (needs `data/`).

Recommendation: make unmeasurable fidelity a distinct non-PASS state (`UNMEASURED`), propagate it into `verdict`, and
report the gated fraction (`same_identity_n / snaps_scored`) beside every candidate-vs-current number. State in the
report header which question is being answered (internal paired replay vs "what we served"), as the 08-11 doc asks.

### calibration-3 (MEDIUM) - The served probability-calibration artifacts are fit in-sample on 6 dates with a mismatched objective, and their own training record shows them scoring worse than identity with nothing gating on it

Serving path, traced: `TorontoHighTempModel.load_probability_calibration()` (`model/toronto_model.py:240-245`) resolves
`probability_calibration{suffix}.json` through `resolve_artifact_path()` (`artifacts.py:395-407`) to
`artifacts/calibration/`, and `model_distribution.py:540-546` applies it via `apply_exact_distribution_calibration()`
to the pre-calibration distribution.

What the committed artifacts say about themselves (read directly from the JSON):

| Artifact | generated | rows | dates per hour | baseline Brier / logloss | artifact-replay Brier / logloss |
| --- | --- | ---: | ---: | --- | --- |
| `probability_calibration_f_family.json` | 2026-07-07 | 96,041 | 5-6 | 0.061096 / 0.270806 | **0.065624 / 0.591234** |
| `probability_calibration_nyc.json` | 2026-07-07 | 9,262 | 6 (`06-07, 06-08, 06-12, 06-13, 06-28, 07-05`) | 0.062422 / 0.200436 | **0.066450 / 0.362441** |
| `probability_calibration_denver.json` | 2026-07-07 | 9,097 | - | 0.063398 / 0.261863 | **0.067817 / 0.534718** |
| `probability_calibration.json` (Toronto) | 2026-06-10 | 4,763 | - | 0.053604 / 0.174826 | 0.053604 / 0.174825 |

(Line refs: f_family `:2011-2016, :420, :241-417`; nyc `:1691-1720`; denver `:1647-1659`; Toronto `:1522-1534`.)

Four separate problems:

1. **Self-score worse than identity, ungated.** `build_artifact()` computes `artifact_replay_*` on the training rows
   (`probability_calibration.py:767-773`). For the F artifacts, log loss roughly doubles. `gate_for_market()`
   (`family_secondary_artifacts.py:1259-1287`) checks only `status == "ok"`, trust score and settled days. The project's
   binding method rule (`ESTABLISHED_FINDINGS.md:1769-1772`) is "score any fitted mapping on its OWN training set ... a
   fit that cannot improve the data it was fitted on has a broken objective". The trainer records exactly that signal
   and nothing reads it.
   Mechanism, from code: with `preserve_distribution_coherence: True` (always written, `probability_calibration.py:608`)
   `calibrate_market_probability()` returns the raw probability unless `hard_bin_probability()` fires
   (`:360-366`). So the entire degradation comes from hard 0/1 assignments derived from the tape's WU-floor columns
   (`row_floor_bucket`, `:422-423`) contradicting settlement. Hand arithmetic, assuming each wrong hard call costs
   `-ln(1e-15) = 34.54` nats under `binary_log_loss`: about 890 rows (0.93%) in the F-family set, about 72 (0.79%) for
   Denver, about 43 (0.47%) for NYC. This is consistent with, and predates by a month, the known
   "replay floor is not the served floor" defect (2026-08-10). I did not verify that it is the same defect.
2. **In-sample fit, noise-level selection.** `fit_exact_distribution_config()` (`:671-713`) grid-searches 6 temperatures
   per hour on all rows with no held-out data, on 5-6 date clusters per hour. In the F-family artifact Brier and log loss
   disagree on direction (Brier is minimised at T=1.2: 0.073554 vs 0.074030 at T=1.0; log loss keeps improving to T=2.0:
   0.286818). The Brier gain that selects T is 0.00048, roughly one sixth of the project's own in-season MDE (0.0030551).
   The resulting hour table (1.0 at 02, 03, 22, 23; 1.30 at 16-18, 20-21; 1.12 elsewhere) is 24 in-sample selections.
3. **Fit transform is not the applied transform.** `_fit_temperature()` scores `sigmoid(logit(p)/T)` on *binary band rows*
   (`:656-668`). Serving applies `p ** (1/T)` renormalised over the *exact-bucket simplex*
   (`model/calibration_runtime.py:384-389`). These coincide only for two classes. This is the same class as the
   retracted 5.39% figure ("a separately fitted transform, not a propagated one").
4. **Residual fitted on already-calibrated output.** Training rows take `model_probability` from the recorded tape
   (`read_scored_rows`, `:459-493`), which is the post-calibration served value (`model_distribution.py:540-556`), and
   the fitted T is then written as the absolute temperature for the raw distribution. Successive refits would measure
   residual miscalibration and overwrite rather than compose. Basis for this sub-point: inferred from the two code paths;
   I did not confirm the tape column semantics against data.

Also: the `market_bin` selection machinery (27 candidates, leave-one-date-out, `:556-631`) is a no-op at serve because
`preserve_distribution_coherence` short-circuits it, yet the artifact still publishes `selected_brier_skill_vs_market`
for a transform that is never applied. The trainer's admission bar is `quality_grades: ["complete", "manual_override"]`,
not `promotion_countable` (method rule, `ESTABLISHED_FINDINGS.md:1758-1759`).

Severity is medium, not high, because the softening direction agrees with the project's measured "fitted beta below 1"
(`ESTABLISHED_FINDINGS.md:590`), the magnitudes are small, and the served hard floor uses live inputs.

Known status: **new** (grep of `docs/operations` for `temperature_by_hour|fit_exact_distribution_config|probability_calibration.json`: no matches).

### calibration-4 (MEDIUM) - Candidate replay normalises over whatever bands survived row filtering; live normalises over the full partition

- `run_replay_backtest()` drops a band row when `market_yes is None or recorded_p is None`
  (`backtesting/replay_backtest.py:440-443`) or when `replayed_p is None` (`:444-446`).
- `normalize_partition_probabilities()` (`pooled_candidate_replay.py:1389-1406`) then groups the *surviving* rows by
  `(market_id, snapshot_id)` and rescales `candidate_p ** gamma` to sum to 1. There is no completeness check.
- Live does the same arithmetic over all `band_rows` (`collection/live_variant_predictions.py:862-880, 646-656`).
- `tests/calibration/test_pooled_candidate_replay.py:378-389` pins the degenerate case: a snapshot with one surviving band
  at 0.4 is asserted to become 1.0.
- The incumbent's `replayed_p` is not renormalised, so on partial partitions the paired comparison is asymmetric. After
  blending, a second `normalize(..., gamma=1.0)` (`:1244-1248`) means that even `alpha = 0` markets are not exactly equal
  to the incumbent on partial partitions.

Direction of bias is indeterminate (inflates the winner if a loser is dropped; inflates losers if the winner's row is
dropped). Frequency is unmeasured: it depends on how often a band lacks a market quote, which needs `data/`.

Related hard-coded value: `partition_normalization_gamma = 1.25` (`pooled_training.py:1754`, `:804` of
`pooled_density_training.py`, defaults at `pooled_candidate_replay.py:1234, 1380` and
`live_variant_predictions.py:879, 1007`). An exponent above 1 is a global sharpening applied to every snapshot. It is
unfitted, and `ESTABLISHED_FINDINGS.md:272` says "Never globally sharpen", `:590` that the fitted exponent is below 1.
This affects the pooled band/density candidate lanes (shadow), not the incumbent.

Known status: **new**.

### calibration-5 (MEDIUM) - Per-market blend weights are hard-coded from replay outcomes and then re-scored on the same corpus; a zero weight passes the per-market gate trivially

- `default_band_postprocess()` (`pooled_training.py:1755-1797`) hard-codes `current_blend_market_alpha`
  (`dallas 0.0, miami 0.0, san-francisco 0.0, denver/houston/los-angeles/nyc/seattle 0.20`), and for the exact-winner lane
  `chicago/houston/nyc/seattle 0.10` with the comment "except for markets that cleared paired full-replay guardrails"
  (`:1789-1790`). `:2202-2215` adds a hand-set source-freshness alpha table and `"miami": 0.0`.
- `alpha` is the candidate weight: `alpha * candidate + (1 - alpha) * incumbent` (`model/current_blend.py:268`).
- `market_verdict()` blocks only when `delta_vs_current > current_tol` (`pooled_candidate_replay_diagnostics.py:376-387`).
  With `alpha = 0` the candidate *is* the incumbent in that market, so that market cannot BLOCK. `overall_verdict()`
  (`:457-473`) returns `PASS_WITH_SHADOWS` / `PER_MARKET_ONLY` rather than `BLOCK`.
- The replay runner scores the whole pinned corpus with no notion of when the alphas were chosen. (The shadow-variant
  exports do carry `experiment_start_date`, `pooled_candidate_scoring.py:585, 652`, so a forward-only protocol exists
  downstream; the gate verdict itself does not use it.) `CONSERVATIVE_BRIDGE_ALPHA_BY_MARKET` (`:66-78`) is declared
  "predeclared ... 2026-06-15" (`:998-1005`) and is scored the same way by `conservative_bridge_report()`.
- Semantics trap: `resolve_current_blend_alpha()` applies the source-state cap with `min()` but context rules by
  *overwrite* (`current_blend.py:242-246`, pinned by `tests/model/test_current_blend.py:112-118`). The three default rules
  are described as "Reduce ... candidate weight" with `alpha 0.35 / 0.35 / 0.50`. In the three markets set to 0.0 and the
  five set to 0.20 they *raise* the candidate weight whenever they match.

Basis: code verified; the claim that the alpha values were chosen from replay outcomes rests on the source comment and
the item ids in the policy names, so that part is inferred. Known status: **new**.

### calibration-6 (MEDIUM) - Gate statistics ignore the project's own clustering rules

- `daily_first_candidate_comparison()` groups by `(market_id, target_date)` and returns `n_days = len(comps)`
  (`pooled_candidate_scoring.py:1181-1205`). `blocked_candidate_validation_gate()` then tests `n_days < min_days` with
  default `min_days = 2` and words it as "daily-first held-out day(s)" (`:1219-1221`). On the fleet-level call
  (`pooled_candidate_replay.py:3690-3695`) one calendar date with 11 F markets yields `n_days = 11`. The count is
  market-days, not date clusters, and nothing is held out.
- All thresholds are point estimates with no interval: `current_tol = 0.003`, `market_tol = 0.003`, `min_days = 2`,
  `min_trust = 25` (`pooled_candidate_replay.py:3964-3969`); microstructure gate constants at
  `pooled_candidate_scoring.py:79-84`.
- The only interval code in the package is one-way, date-only: `served_stage_ablation.py:537-575`
  (`cluster_unit: fleet_target_date`) and `residual_distribution_v1.py:933-986` (`whole_fleet_target_date`). Grep of
  `src/weather/calibration` for `crossed|two.way` finds nothing. `ESTABLISHED_FINDINGS.md:1754-1756` makes crossed
  date x market clustering mandatory and 1d says the floor is set by 12 markets, not dates.

Known status: the method rule is recorded and the slice-gate lottery is recorded; the `n_days` miscount and the absence
of any crossed-cluster implementation in this package are not. **Known_open** in spirit, new in the specifics.

### calibration-7 (MEDIUM) - Serving-critical calibration logic exists in two copies with no parity test, and training and serving use different copies

`apply_exact_distribution_calibration`, `apply_continuous_density_calibration`, `calibrate_market_probability`,
`select_context_base_rate`, `continuous_floor_threshold_f` are defined in both
`calibration/probability_calibration.py:158-400` and `model/calibration_runtime.py:335-560`. I compared them by eye and
they are currently equivalent line for line apart from helper names.

Who uses which:

- Trainer self-score: local copy (`probability_calibration.py:719`).
- Density training: calibration copy, via `pooled_density_training.py:3` star-importing
  `pooled_feature_assembly.py:87`.
- Replay: model copy, via `pooled_candidate_replay.py:52-58` from `model/variant_prediction_runtime.py:16`.
- Live and serving: model copy (`live_variant_predictions.py:935`, `model_presentation.py:23`, `model_distribution.py:540`).

The split exists for a reason (`tests/operations/test_import_architecture.py:1128` forbids model runtime importing the
calibration package), but the calibration package could import the runtime copy instead of keeping its own. Grep of
`tests/` shows no test that exercises both copies on the same inputs. Partition normalisation likewise exists three
times (`pooled_candidate_replay.py:1389`, `live_variant_predictions.py:646`, `operations/density_live_replay_parity.py`).
Train/serve skew is the project's self-described dominant defect class.

Known status: **new** (the parity gate the project has concerns feature extraction, not this layer).

### calibration-8 (MEDIUM) - Metric definitions are fragmented, so headline numbers from different modules are not comparable

- `weather.scoring.metrics` is documented as the shared home, yet grep finds 35+ private `brier` / `log_loss` / `_ece`
  definitions across `src/weather` (6 inside `calibration/`, 6 under `reporting/validation/`, others in `reporting/`,
  `market/`, `operations/`).
- Log-loss clipping differs: `1e-15` (`scoring/metrics.py:34`, `feature_model.py:140, 229`,
  `intraday_calibration.py:123`, `feature_probability_calibration.py:60`), `1e-9`
  (`reporting/scorecards/proper_scoring_reliability_scorecard.py:89`), `1e-6` inside the calibrator
  (`probability_calibration.py:57-64`), and unclipped `math.inf` (`simplex_calibration.py:171`). A single
  zero-on-the-winner row costs 34.5, 20.7, 13.8 nats or infinity respectively. The project served 0.0 on the realised
  band in 8.486% of rows before the 2026-06-15 fix, so any log-loss series spanning that period depends heavily on which
  module produced it.
- ECE is 5 equal-width bins over per-band binary probabilities in `scoring/metrics.py:107-132` and 10 bins over top-label
  confidence in `feature_model.py:150`, `simplex_calibration.py:228-243`, `served_stage_ablation.py:604`.
- "Daily-first skill" has two definitions. `scoring/metrics.py:182-184` recomputes `1 - mean(model)/mean(market)` from
  averaged Briers. `pooled_candidate_scoring.py:1200-1201` and `backtesting/replay_backtest.py:146-147` average the
  per-market-day *ratios*. A late-day market-day whose market Brier is near zero dominates a mean of ratios. The ratio
  form is not used by a gate (gates use Brier deltas), so this is a reporting defect. It is the mismatched-denominator
  family the project has already retracted results over.
- Brier is per-band binary mean in `scoring/metrics.py` and per-partition categorical sum in `simplex_calibration.py:146`,
  `feature_model.py:143`, `intraday_calibration.py:127`. RPS (`simplex_calibration.py:150-156`) is unnormalised, so it is
  not comparable across markets with different band counts.
- There is no CRPS and no probability-integral-transform implementation anywhere in scope. In this repo "PIT" always
  means point-in-time.

The arithmetic of each individual implementation I read is correct.

### calibration-9 (LOW) - Monolith risk: one 4,046-line replay module plus a 7-file star-import chain that is one module in disguise

- `pooled_candidate_replay.py` is 164,030 bytes. It holds slice bucketing, feature assembly, three probability-attach
  paths, partition normalisation, blending, the replay cache and its sentinel, heavy-diagnostics carry-over, a
  byte-bounded file and JSON loader family (`:2115-2530`), the bounded streaming adapter (`:2664-3370`), the runner and
  the CLI. It imports about 100 names, including underscore-private helpers from sibling modules (`:173-182, 221-224`),
  and ends with a circular-import workaround (`:3923`).
- `pooled_feature_model.py` is a facade over a *linear* star-import chain:
  `pooled_feature_assembly -> pooled_density_training -> pooled_band_training -> pooled_training -> pooled_artifact_io ->
  pooled_reporting -> pooled_feature_cli`, each ending with
  `__all__ = [name for name in globals() if not name.startswith("__")]` (for example `pooled_training.py:15, 2413`).
  Every slice sees every earlier global, single-underscore privates included. The files total about 263 KB. The split
  bought smaller files without boundaries, name shadowing is silent, and patching a name on one module in a test does not
  affect the copies bound in the others.
- It *is* tested: `tests/calibration/test_pooled_candidate_replay.py` (92 KB), `..._streaming.py` (30 KB),
  `test_pooled_feature_model.py` (81 KB), `test_promotion_refresh.py` (87 KB). I did not run them.

### calibration-10 (LOW) - Silent skips and stray hard-coded values

- `probability_calibration.py:574-582` - any exception in any fold drops that whole calibration method from the
  candidate table with no log line and no count.
- `forecast_error_model.py:144-148` - a folder whose `snapshots_long.csv` cannot be read is skipped silently. A transient
  `[Errno 13]` while capture holds the file is the exact failure that cost a settlement day on 2026-08-11.
- `pooled_candidate_replay.py:750-757` - per-snapshot feature errors are caught, only the first 20 are recorded, and no
  total is kept (it can be derived as `candidate_snapshots - predicted_snapshots`).
- `pooled_feature_assembly.py:617` - optional store failures become an empty index.
- `intraday_calibration.py:32-33` - `MARKET_BIN_MIN = 19`, `MARKET_BIN_MAX = 29` are Toronto early-summer Celsius tails.
  `market_group()` applies them to every market, so in an F market every bucket is `gte_29` and the "market group"
  metrics are degenerate. The optimiser uses exact log loss, so only reported diagnostics are affected.
- `current_blend_context_rule_matches()` accepts any row key (`model/current_blend.py:182-209`). In the unbounded replay
  path rows still carry `outcome` and `settlement_distance_bucket` when blending runs
  (`pooled_candidate_replay.py:1416-1423`), so a rule keyed on a settlement field would match in replay and never live.
  No current rule does this, and the bounded path strips those fields (`:1675-1704`).
- `_candidate_replay_row_identity()` uses `str(value or "")` (`:1661-1672`), so a band value of exactly 0 is
  indistinguishable from missing. The band label is also in the key, so a collision is unlikely.
- Band-edge note: the density path integrates a 0.1 F grid over half-open `[X-0.5, X+0.5)` native intervals
  (`model/continuous_density.py:93-141`). For F markets the lower edge sits exactly on a grid point and always goes to
  the upper band, so if grid points are cell centres the mapping is shifted cool by 0.05 F. For Toronto every C boundary
  (`1.8k + 32.9` F) also lands on a grid point and its assignment depends on a one-ulp difference between
  `round(low + i*0.1, 6)` and `c*9/5+32`. Mass is conserved either way. Negligible next to the measured cool bias;
  recorded for completeness. `round_half_up = floor(v + 0.5)` (`units.py:23-28`) rounds negative halves toward plus
  infinity; I did not check that against WU's convention for sub-zero Toronto highs.

## 4. Strengths

1. **`residual_distribution_v1.py`** - rolling-origin outer folds, inner OOF used for ridge alpha, residual scale and the
   simplex temperature (`:692-844`), simplest-non-inferior arm selection (`:847-861`), chained fit receipts verified by hash
   (`:600-684`), and whole-fleet-date bootstrap that reduces each date to one score before resampling (`:933-986`).
2. **The legacy band trainer neutralised its own leak.** `pooled_training.py:2131-2161` documents that temperature,
   adjacent, exact-winner and market-bias transforms "used to be fitted on that same holdout and then reported on it",
   forces them to identity, and writes `promotion_permission: forbidden_without_nested_inner_oof_receipts`. The outer
   holdout "never selects a served transform" (`:2296-2298`).
3. **Production PIT lane** - locked-window exclusion checked as set equality (`pooled_feature_cli.py:342-348`,
   `pooled_training.py:2039-2044`), nested rolling folds with a 3-7 day embargo that fail closed when an outer fold has no
   inner folds (`:418-504`), and locked-date exclusion for the secondary artifacts
   (`family_secondary_artifacts.py:170-230, 555-735`).
4. **Bounded replay adapter** strips every settlement-derived field before candidate prediction and rejoins by identity
   afterwards, raising on any missing or duplicate identity (`pooled_candidate_replay.py:1675-1719`); corpus pins are
   verified by SHA-256 (`:3508-3513`); recent days bypass the replay cache because sidecars refresh (`:3597-3602`).
5. **`feature_model.py`** fits imputer and scaler strictly inside each outer fold (`:503-558`) and reports tuned metrics
   only from inner-OOF calibration built from the outer fold's training rows (`:647-709, 1516-1560`).
   `simplex_calibration.py` validates complete partitions, preserves hard zeros, has one degree of freedom and accepts a
   non-identity temperature only if both Brier and log loss strictly improve (`:259-305`).

## 5. What I could not cover

- Not read, or only skimmed by symbol list: `residual_distribution_corpus.py`, `residual_distribution_stress.py`,
  `residual_distribution_lock.py`, `settlement_lag_model.py`, `model_ensemble.py`, `afternoon_residual_centering.py`,
  `base_model_candidate.py`, `forecast_training_contract.py`, `pooled_band_training.py`, most of
  `pooled_density_training.py`, `pooled_reporting.py`, `pooled_artifact_io.py`, `feature_model_reports.py`,
  `pooled_feature_source_state.py`, and the body of the bounded preselection loaders
  (`pooled_candidate_replay.py:2100-3300`).
- No test was run; "tested" above means a test file exists and I read the relevant assertions.
- No `data/` access, so these frequencies are unmeasured: how often replay drops a band for a missing market quote
  (calibration-4); how often `same_identity_n == 0` on the current corpus (calibration-2); whether the production host's
  working-tree copies of `artifacts/calibration/*.json` match what I read (the project has a documented history of serving
  uncommitted bytes).
- The Toronto C/F path was checked only in the density integration and `units.py`. I did not trace Celsius band values
  through `snapshot_band_key` or `resolve_outcome`.
- `scoring/trading.py` prices entries at `market_yes` / `market_no` with no spread, fees or fill model. I treated that as
  out of scope because no live trading is authorised and the maker track has its own economics code.

## 6. Open questions for the owner

1. Was `4a5efaa26` a deliberate performance trade (the leave-one-market-day audit is quadratic on large row sets)? If so,
   the report row should say "split summary", not "Leakage audit: PASS".
2. Is any consumer still reading `replay_gate.global_ok` or `cutover_decision` as authority, or has the bounded
   release-candidate contract fully superseded it? If superseded, the old verdict strings are a trap for the next agent.
3. Are the 2026-07-07 secondary calibration artifacts what production loads today, or does a bound release bundle
   override them (`toronto_model.py:241-242`)?
4. When model work resumes, should `weather.scoring.metrics` become the only permitted scorer (enforced by an import-lint
   test like the existing architecture tests), with one declared clip and one declared skill definition?
