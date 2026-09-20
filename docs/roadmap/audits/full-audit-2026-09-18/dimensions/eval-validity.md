# Audit dimension: Evaluation, backtesting and statistical validity (`eval-validity`)

Auditor: Claude (subagent), 2026-09-18, on the live production host under the read-only rule set.
Method: Read / Grep / Glob with explicit paths under `src/`, `tests/`, `docs/`, `scripts/`; three whitelisted
`git` reads. No Python, no pytest, no data/ access, no writes other than this file.

Health grade for this dimension: **B**.

One-paragraph verdict: the project's *central* evaluation conclusion ("we do not beat the market; the gap is
information") is credible, and the direction of every benchmark bias I could find favours the model rather than
the market, so the negative result is if anything understated. The research-grade discipline (pre-registration
bound by file hash, an alpha-spending ledger, crossed date x market bootstrap, fit-on-B / score-on-C, a
retraction log) is unusually strong for a one-person project. The weaknesses are (a) that discipline lives in
three research modules and in markdown, while every *decision-bearing* code path (production PIT evaluator,
live-variant settlement scorecard, promotion decisions, hourly gate, experiment contract) still uses either
date-only clustering or bare point-estimate thresholds, which the project's own canon calls inadmissible;
(b) the ad-hoc evaluators and the calibration trainers silently substitute a tape-derived proxy label when the
settlement ledger has no row, which is exactly the state 10 of the last 14 dates are in; and (c) the only
instrument that can ever confirm anything (the post-2026-07-31 panel) accrues only from settled, countable
dates, and is currently accruing at roughly 4 dates in 14.

---

## 1. Scope covered

Read in full or in the decision-relevant parts:

- `src/weather/backtesting/`: `settled_days.py` (all), `settlement_io.py` (1-135, 233-472), `settlement_ledger.py`
  (452-570), `backtest.py` (385-425, 498-667), `replay_backtest.py` (all), `replay_ablation.py` (160-310),
  `tape_scoring.py` (150-288).
- `src/weather/reporting/validation/point_in_time_evaluation.py` (5,500 lines / ~230 KB): module map, 1-245,
  443-875, 1063-1315, 1647-1745, 2460-3290, 3288-3495, 3934-4137, 4900-5017, 5329-5367.
- `src/weather/reporting/validation/market_anchor_validation.py` (structure + split logic).
- `src/weather/reporting/research/`: `quotable_edge.py` (60-150, 676-1018), `blind_feature_repair.py` (175-277),
  `profit_edge_analysis.py` (1-140 + fee grep), `skill_gap_decomposition.py` (grep), `item224_*` (headers).
- `src/weather/reporting/scorecards/`: `proper_scoring_reliability_scorecard.py` (100-205, 378-592),
  `live_variant_settlement_scorecard.py` (440-590, 740-805), `model_history.py` (115-135, 455-515, 600-690).
- Adjacent code I had to trace to make claims honest: `scoring/metrics.py`, `scoring/trading.py`,
  `collection/snapshot_store.py` (740-850), `model/model_presentation.py` (152-202), `market/polymarket_client.py`,
  `reporting/promotion/promotion_corpus.py` (161-290, 405-552), `reporting/promotion/promotion_gauntlet.py`
  (290-362), `reporting/promotion/decisions.py` (grep), `reporting/hourly/hourly_model_gate.py` (175-247),
  `reporting/serving_gates/model_scoring_liveness.py` (all), `reporting/serving_gates/production_readiness_gate.py`
  (170-360), `reporting/daily/daily_learning.py` (1440-1567), `reporting/daily/daily_learning_scorecard.py`
  (1040-1230, 1333-1355, 1640-1700), `operations/settlement_hole_check.py` (all), `experiment_contract.py`
  (380-441), `calibration/probability_calibration.py` (425-494), `operations/module_size_audit.py` (225-255).
- Canon: `docs/operations/ESTABLISHED_FINDINGS.md` (§1, §1b, §1c head, §5, §6), `RETRACTED_AND_FALSE_LEADS.md`
  (§1-2), `CAMPAIGN_LEDGER.md` (all), `STATE_OF_PLAY.md` (all),
  `docs/roadmap/audits/codex-project-audit-2026-08-11.md` (270-440).

## 2. How "the market" benchmark is actually built (traced end to end)

1. `PolymarketClient.get_event()` GETs `https://gamma-api.polymarket.com/events/slug/<slug>`
   (`market/polymarket_client.py:21-30, 44-45`).
2. `model_presentation.market_bins()` takes the **Gamma `outcomePrices` entry for "Yes"** as `market_yes`
   (`model/model_presentation.py:159-164, 190`). `bestBid`, `bestAsk`, `lastTradePrice` are captured alongside
   (`:192-194`) but are not what the scorers use.
3. `snapshot_store` writes `market_yes` next to `model_probability` on the same `snapshot_id` /
   `captured_at_utc` row, plus Gamma's `event_updated_at` (`collection/snapshot_store.py:785-823`).
4. Every scorer reads that column: `scoring/metrics.py:46-48`, `backtesting/tape_scoring.py:191-194`,
   `backtesting/replay_backtest.py:440-443`, `research/skill_gap_decomposition.py:905` (default column
   `market_yes`), `research/quotable_edge.py:855-909`.

Consequences, in both directions:

- It is **not a CLOB mid**. It is whatever Gamma publishes as the outcome price (in practice a midpoint when the
  book is tight and a last trade otherwise), served through a cached REST API. The canon calls it "market
  mid-price" (`ESTABLISHED_FINDINGS.md:515`); that is an approximation, not a verified description. The
  project's own number says a valid two-sided book exists on only 51.41% of band rows
  (`ESTABLISHED_FINDINGS.md:401-402`).
- The market vector is **scored raw, not renormalised** ("Market prices remain raw for Brier comparability",
  `skill_gap_decomposition.py:1481`; no normalisation in `metrics.py`). Overround on thin tail bands costs the
  market a little Brier. Bias direction: favours the model.
- No scorer filters on `event_updated_at` staleness or `market_status`. A stale Gamma price makes the market
  look slower than it was. Bias direction: favours the model.
- The model row and the market row share a timestamp and a row, and the main scorers require both to be present
  (`replay_backtest.py:442-443`, `tape_scoring.py:193-194`), so the core comparison is **paired at row level**.
  Exceptions are listed in finding 5.
- Net: I found no benchmark-construction bias that flatters the market. The "we lose" conclusion is robust to
  everything I could identify. `quotable_edge.py:139-141` even pre-registered `book_spread`, `liquidity` and
  `volume` axes, so "maybe we only lose where the benchmark is junk" was already asked and answered (no cell
  positive).
- For profitability rather than forecasting skill the benchmark is wrong in the other direction, and the canon
  already says so (`ESTABLISHED_FINDINGS.md:513-518`). `profit_edge_analysis.py:117` fills a taker at
  `market_yes` / `1 - market_yes` (no half-spread) with the fee `0.05*p*(1-p)` per share (`:91-97`), and the
  legacy `backtest.py` "Realized Edge / P&L" section fills at `market_yes` with **no fee and no spread**
  (`scoring/trading.py:18-26`, `backtest.py:392-397`). Both are labelled diagnostic, but the section title
  "Realized" is misleading.

## 3. Findings

Severity scale per the audit brief. `known_status` says whether the project already records it.

### eval-validity-1 (HIGH, known_open, extended) - The mandated inference is not what decision-bearing code runs

Canon: "Crossed date x market clustering is mandatory. Exchangeable market-day resampling ... has retracted
headline results" (`ESTABLISHED_FINDINGS.md:1754-1756`), and "THERE IS A HARD FLOOR, AND IT IS SET BY MARKETS
NOT DATES" (`:614`).

Code of record:

| Path | What it does | Evidence |
| --- | --- | --- |
| Production PIT evaluator | resamples **whole fleet dates only**; emits `cluster_unit: "fleet_target_date"` | `point_in_time_evaluation.py:2518-2572` (`:2568`) |
| Its verifier | **rejects** any interval whose `cluster_unit != "fleet_target_date"` ("interval is not date-clustered") | `point_in_time_evaluation.py:3472-3482` |
| Live-variant settlement scorecard | `whole_fleet_date_clustered_percentile_bootstrap` | `live_variant_settlement_scorecard.py:451-527` |
| Same scorecard, deltas | `delta_vs_current` / `delta_vs_market` are **differences of marginal means, no interval on the delta** | `live_variant_settlement_scorecard.py:793-802` |
| Experiment contract | independent unit must be `fleet_target_date` or `market_day`; decision rule is `metric <op> threshold` - no uncertainty term, no "crossed" option | `experiment_contract.py:24, 398-423` |
| Promotion decisions | per-slice point threshold `delta_vs_market > 0.003` | `reporting/promotion/decisions.py:362-369, 388, 830-872` |
| Hourly gate | point threshold on `brier_delta`, no interval | `reporting/hourly/hourly_model_gate.py:204-213` |
| Replay regression gate | point threshold `tol=0.003` on band-row-pooled Brier | `backtesting/replay_backtest.py:752-783, 808` |
| Daily-learning promotion CI | **i.i.d. bootstrap** over samples, seed fixed | `reporting/daily/daily_learning.py:1502-1525` |

Correct crossed logic exists three times, each a private copy with a different estimand:
`quotable_edge.py:680-724` (product weights, row-weighted), `blind_feature_repair.py:228-276` (daily-first cell
means), `casebooks/severe_tail_ex_ante.py:568`. There is no shared primitive; `src/weather/scoring/` holds only
`metrics.py` and `trading.py`. The `delta_vs_market` estimand is re-implemented across **69 files** (Grep count
over `src/weather`).

Already recorded: `docs/roadmap/audits/codex-project-audit-2026-08-11.md:303-322` ("P0 - Binding inference is not
implemented consistently"), which named `residual_distribution_v1.py` and `served_stage_ablation.py`. What is
new here: that audit did not name the two production evaluators, and did not notice the verifier *hard-codes*
the non-canonical unit, so a future crossed interval would be refused by the contract. Five weeks later no
shared utility exists.

Impact is bounded today only because promotion is off the critical path by owner decision. It becomes live the
moment any candidate (model or maker) is qualified through these paths.

### eval-validity-2 (HIGH, new) - Evaluators and trainers silently fall back to a tape-derived proxy label when the ledger has no row

`settlement_for_tape()` (`backtesting/settlement_io.py:277-328`) tries the strict ledger first (`:284-295`). If
there is no ledger row it calls `settlement_from_sources()` (`backtesting/settlement_ledger.py:462-527`), which
returns, in order: override, daily summary if >= 18 rows, else **`snapshot_high` = the max of the tape's own
`wu_history_high` column** (`:452-459, 499-508`), else a sparse daily summary. No completeness or as-of guard.

Callers that use whatever comes back:

- `backtest.py:536-542` (label from `settlement.json`/ledger, else fallback); default folder set is **every**
  `*/snapshots_long.csv` including today's in-progress market (`backtest.py:641-644`), so an unfinished day is
  scored against its running maximum.
- `replay_backtest.py:380-385` when no `--corpus` is given; default folder set likewise `:833-835`.
- `replay_ablation.py:201-206`.
- Trainers, which **discard the source string**: `calibration/probability_calibration.py:473`
  (`bucket, _, _ = ...`), `forecast_error_model.py:152`, `settlement_lag_model.py:209`, `model_ensemble.py:126`;
  also `location_trust.py:153`, `forecast_tracker.py:157`.

"Settled" for folder discovery is purely calendar: `target_date < today`, with *today* taken in Toronto time for
all 12 markets (`settled_days.py:57-59, 91`). It never checks that a label exists.

Why it matters now: 10 of the last 14 dates have no ledger row for up to 12 of 12 markets. For those dates these
paths do not drop the day and do not fail - they score or train against a label reconstructed from our own
capture, which the project has independently shown is not a running maximum
(memory/canon: "the WU series is not append-only", 658/658 B cutoffs narrowed). The proxy is also circular: the
label is the terminal value of the same `wu_history_high` series that feeds the model's observed-high floor.
The reports do print the source per day (`replay_backtest.py:690-705`), so it is visible to a careful reader,
but headline aggregates pool proxy-labelled and ledger-labelled days with no split.

Not affected: the promotion path. `promotion_gauntlet.py:321-330` passes the pinned corpus manifest, and
`promotion_corpus._entry_for_folder` refuses a folder with no label (`promotion_corpus.py:246-247`,
`missing_settlement_label`) and records authority status (`settlement_io.py:428-467`). Training is currently
disabled, so the trainer half is latent, not active.

### eval-validity-3 (HIGH, known_open for the hole; the evaluation consequence is new) - Unsettled dates vanish from the evidence base, and the evaluation layer's own liveness check cannot see it

Where an unsettled market-day goes, path by path:

| Consumer | Behaviour | Loud? |
| --- | --- | --- |
| Promotion corpus | dropped; appended to `manifest["skipped"]` with `missing_settlement_label` | recorded, but `summarize_entries()` summarises entries only (`promotion_corpus.py:405-429`); `replay_backtest._manifest_summary` drops `skipped` entirely (`replay_backtest.py:221-237`) |
| Production PIT window | a date with **zero** countable markets -> `missing_calendar_dates` -> BLOCK (`point_in_time_evaluation.py:3166-3187, 4089-4098`) | loud |
| Production PIT window, **partial** hole | passes: the lock and the verifier check only `fleet_dates == 14` (`:3483-3492`); nothing checks market-days against 14 x 12 | silent |
| PIT evaluator status | a fully non-countable market-day only increments `excluded_rows`; `blocking` looks at `contract_errors`, `excluded_cutoffs`, source quality (`:2709-2713, 2884-2888`) | silent for status, present in payload |
| `model_history` | every (date, market) cell rendered with status "No settlement" (`model_history.py:510-512, 640-650`) - the good pattern | per-row loud; headline `overall.market_days` is scored-only with no expected denominator (`:660-675`) |
| `proper_scoring_reliability_scorecard` | rows without an outcome are `continue`d (`:141-144`); summary has no date range, no date/market counts (`:559-568`); `scored_probability_row_count` double-counts because each source row also emits a `market_only` row (`:154-163`), so dropped rows cannot be inferred | silent |
| `backtest` / `replay_backtest` / `replay_ablation` | proxy label instead (finding 2) | substituted |

The evaluation layer's liveness gate is structurally blind to this failure. `build_scoring_liveness()` compares
`last_scored_target_date` with the **latest date that has a label** (`model_scoring_liveness.py:241-267`), read
from `market_day_labels.csv` (which canon says is not the authority, `ESTABLISHED_FINDINGS.md:1760`). When
settlement stops, the reference stops with it and the gate reads PASS; interior holes are invisible to a
max-date comparison by construction (`include_date_counts=False`, `:245`). This is the project's own
"a stopped counter looks satisfied" shape.

What does flag it: the operations layer. `operations/settlement_hole_check.py:55-99` (14-day window, last 400
ledger lines per market) feeds `scripts/ops/status.ps1:1603-1652`, and `health_watchdog.ps1:98-108` escalates to
CRITICAL at >= 2 days. `daily_learning_scorecard._settled_target_recency_check` (`:1151-1184`) fails when the
analysed target trails run date by > 1 day, and `operations/settled_day_freshness.py` counts missing labels for
the single date the chain analyses. None of these is consumed by a scorecard, and a hole older than 14 days
leaves the only monitor that sees interior gaps.

Why this is the finding that matters for the project's goals: the pre-boundary panel is sealed at D=50 and its
alpha budget is for selection only - an accepted step is labelled `SELECTED_ON_PREBOUNDARY_PANEL`, *not
confirmed*, until post-boundary evidence decides it (`CAMPAIGN_LEDGER.md:143-144`). Post-boundary evidence
accrues only from settled, promotion-countable dates. At 4 settled dates in 14 the confirmation instrument is
growing at under a third of calendar rate, and the production window additionally requires 14 *contiguous*
dates with the latest no older than 7 days (`point_in_time_evaluation.py:3922, 4089-4103`) - unsatisfiable
today. Labels are re-fetchable from WU history (canon: 08-08 recovered on the fourth try), so this is
recoverable, which is why I rate it high and not critical.

Missingness is probably close to ignorable for bias (fleet-wide chain failures are not weather-driven), but I
could not verify that from code; per-market WU failures during station outages would be informative.

### eval-validity-4 (MEDIUM, known_open) - Promotion and regression gates decide on point estimates

`decisions.py:362-369` (slice status from `delta_vs_market > market_tolerance`, default 0.003, plus a row-count
floor), `hourly_model_gate.py:204-213`, `replay_backtest.gate()` (`:752-783`, tolerance 0.003 on a band-row-pooled
aggregate in which snapshot-dense days and many-band markets dominate). The canon already retracted this design
("The slice gate was a lottery", false-rejection 99.885-99.9905%, `RETRACTED_AND_FALSE_LEADS.md:63-67`) and
recorded that the gate is stricter than the economics need (`ESTABLISHED_FINDINGS.md:368-376`). The code is
unchanged. Accepted as off the critical path; listed so nobody reads a future PASS/BLOCK from these as evidence.

### eval-validity-5 (MEDIUM, new) - Mismatched denominators survive in two model-versus-market comparisons

The class of error that produced the retracted "78% leak":

- `replay_ablation.summarize()` computes base and variant Brier over **all** rows but market Brier over
  `sub.dropna(subset=["market_yes"])` (`replay_ablation.py:287-293`). Model and market are scored on different
  row sets whenever any `market_yes` is null.
- `live_variant_settlement_scorecard._metric_views()` filters partitions per metric field
  (`:537-539`), so `metrics`, `current_served_metrics` and `market_benchmark_metrics` can each be averaged over a
  different partition subset, and `delta_vs_market` is then the difference of those means (`:798-802`).
  The production readiness gate requires full prediction coverage (`production_readiness_gate.py:264-271`) but
  I found no check that market-benchmark coverage equals candidate coverage.
- `proper_scoring_reliability_scorecard._score_rows()` appends one `market_only` row **per source row**
  (`:154-163`). The input is a per-variant long file, so the market lane is replicated once per variant and is
  weighted toward snapshots covered by more variants; its `row_count` is inflated by the same factor.

All three are diagnostics rather than gates, hence medium.

### eval-validity-6 (MEDIUM, new) - Pre-registration is partly code-enforced; alpha spending is documentation only

Enforced in code: `quotable_edge.analyze()` refuses to run if the band-row file hash, the pre-registration file
hash, the predictor sidecar or thresholds changed, and requires `outcomes_read is False` from the preparation
step (`quotable_edge.py:830-841`); the 117-cell family is asserted (`:143-144`) and Holm-adjusted (`:989-1016`).
The production path locks the evaluation population before training (`prepare_production_preselection`,
`point_in_time_evaluation.py:4006-4136`; `window_selected_after_evaluation` check `:3380-3385`).

Not enforced: the campaign ledger. No code reads `CAMPAIGN_LEDGER.md` or any machine-readable equivalent
(Grep for `campaign_ledger|alpha_spen|alpha_budget|alpha_ledger` over `src/weather`: no matches). Nothing stops a
module from scoring the sealed panel's out-of-season outcomes without a ledger row. The ledger also prices only
*formal decisions*: outcome-bearing looks that shaped later candidate design (`-09-44a`, `-09-46a`'s 114 cells
across both strata, `-09-59a`) are not charged. The project's mitigation - nothing selected on this panel is
"confirmed" - is the right one, but it makes finding 3 the binding constraint.

### eval-validity-7 (LOW, new) - "Power" in the canon is observed-effect plug-in power

`quotable_edge.py:952-977` and `blind_feature_repair.py:258-270` compute power at the **observed** effect
(`z = |point| / se`). The code is honest about it (`observed_effect_plugin_power`; `severe_tail_ex_ante.py:744`
says "descriptive plug-in power, not prospective power"), but the rendered table header is just "Power"
(`blind_feature_repair.py:565`) and the canon quotes it as such ("power 0.074", "power 0.066",
`ESTABLISHED_FINDINGS.md:307, 1786-1787`). Observed power is a monotone transform of the p-value and adds nothing
to the interval; values near 0.05-0.07 simply restate "the point estimate is near zero". The MDE that these
functions also compute is the informative number and should be the one cited. No decision I saw turned on the
plug-in power, hence low.

### eval-validity-8 (LOW, new) - The only statistical promotion check in the daily loop has no input producer

`daily_learning._promotion_delta_confidence()` needs `candidate["paired_delta_samples"]`
(`daily_learning.py:1480-1499, 1528-1555`). The scorecard forwards `paired_delta_samples` or `market_day_deltas`
(`daily_learning_scorecard.py:1677-1683`), but no file under `src/`, `scripts/` or `tools/` writes either key
(exhaustive Grep; only the two consumers and one test match). The check therefore always returns BLOCK with
`delta_vs_current_paired_samples_missing`. Fail-closed, so safe, but it is dead machinery that reads like a live
30-market-day confidence gate. If it is ever wired up it is an i.i.d. bootstrap (finding 1), and its
independence count falls open: a row with no `market_day`/`target_date` key, or a bare number, is counted as its
own independent market-day (`daily_learning.py:1467-1477, 1493-1498`).

### eval-validity-9 (LOW, known_open) - 230 KB monolith mixes five concerns; tests cover contracts more than statistics

`point_in_time_evaluation.py` holds the row contract, two materialisers, fold construction, fit receipts, the
streaming evaluator, the bootstrap, four verifiers, the production qualification orchestrator and a CLI. It is
listed in `operations/module_size_audit.py:236-240` with a split plan that is conditional on "verifier
consolidation". 44 tests across two files (`tests/reporting/test_point_in_time_evaluation.py`: 19,
`test_point_in_time_preselection_source.py`: 25) exercise contracts, locks, poisoning and determinism. I found
no test that checks interval *coverage* under a simulated null for any bootstrap in the repo; the one coverage
study (`-09-62a`) lives in a report, not in the suite. Only 7 commits have ever touched the module, so churn
risk is low; the risk is that the statistical core (60 lines at `:2518-2572`) is buried under 5,400 lines of
provenance plumbing and cannot be swapped without touching the verifier contract (finding 1).

### eval-validity-10 (INFO, known_accepted) - PIT "qualification PASS" certifies integrity, not skill

`materialize_production_candidate_packet()` returns `status: "PASS"` when locks, receipts, hashes and interval
inventory verify (`point_in_time_evaluation.py:4985-5017`). No comparison against incumbent or market is made
there, and no producer emits `claim_lane = "market_benchmark"` rows into the PIT table (Grep over `src/weather`:
only the contract constants match), so that lane is declared but empty. This is consistent with the owner's
2026-08-09 decision that release machinery is off the critical path; it is recorded so that a future "PIT
qualification PASS" is not read as a performance claim.

## 4. Strengths (genuine)

1. **The negative headline is conservative and well defended.** Pre-registered 117-cell search with hash-bound
   inputs, Holm adjustment, support/stability/power screens and leave-one-date / leave-one-market stability
   (`research/quotable_edge.py:830-841, 989-1016`). Zero positive cells, and benchmark-quality axes were included.
2. **Leakage controls are in code, not prose.** Rolling-origin folds with a mandatory 3-7 day calendar embargo
   (`point_in_time_evaluation.py:1655-1698`), `feature_available_at <= prediction_made_at` enforced per row
   (`:581-587`), candidate-independent selection universe hashed before training (`:3029-3128`), window locked
   before scoring and verified (`:3380-3385`).
3. **The promotion corpus is pinned and strict about label authority**: per-snapshot pinning, corpus hash,
   ledger-first labels with tape-binding verification, explicit `skipped` reasons
   (`promotion_corpus.py:246-259, 494-551`; `settlement_io.py:404-467`), and the regression gate refuses a
   corpus-hash mismatch (`replay_backtest.py:765-774`).
4. **Lane isolation**: weather-only, market-benchmark, market-informed and trading evidence can never be pooled
   (`point_in_time_evaluation.py:98-143, 2899-2903, 3446-3455`), and a partial failure poisons the whole cutoff
   rather than silently thinning it (`:2745-2765`).
5. **An institutional memory for statistical error**: `RETRACTED_AND_FALSE_LEADS.md`, §5 method rules, and a
   campaign ledger that charged contestable looks rather than arguing the count down
   (`CAMPAIGN_LEDGER.md:129-133`). `model_history.py` shows the right survivorship pattern (full date x market
   grid with a status per cell).

## 5. What I could not cover

- No data access, so I did not verify any number: how many post-boundary countable dates exist, how many recent
  folders would take the `snapshot_high` fallback, or whether the missing dates differ in difficulty.
- `calibration/residual_distribution_v1.py`, `served_stage_ablation.py`, `pooled_candidate_scoring.py` (the
  candidate scoring core) - outside the brief's path list; only grepped.
- 10 of the 12 `validation/*_validation.py` modules and ~24 of the 31 `research/` modules were not opened
  (June-era, item-numbered one-offs). `snapshot_evaluation.py`, `progress_audit.py`,
  `weather_only_model_proof_packet.py`, `settled_day_root_cause.py`, `frozen_baseline_replay_trend.py`,
  `winner_rank_parity.py`, `distribution_stage_attribution.py` not read.
- Did not run any test, so "tests exist" means the files and test names exist, not that they pass.
- Did not verify Gamma's `outcomePrices` semantics (no network); the statement that it is midpoint-or-last is
  from general knowledge and is labelled as such.

## 6. Open questions for the owner / other dimensions

1. Operations: `settlement_hole_check` reads only the last 400 lines of an append-only-with-revisions ledger and
   lets the **last** row for a date win (`settlement_hole_check.py:37-52, 60`). After dozens of failed
   backfill attempts, could appended `none` rows be (a) pushing good rows out of the 400-line tail or
   (b) overwriting a good row's status? If so the "10 of 14" count is partly an instrument artefact.
2. Is the post-boundary confirmation panel being tracked as a number anywhere (countable dates since
   2026-07-31)? I could not find it in `STATE_OF_PLAY.md`.
3. Should `settlement_for_tape` lose its proxy fallback for everything except an explicit `--allow-proxy-label`
   diagnostic mode?

## 7. Recommendations (no changes made)

1. One shared, tested `crossed_bootstrap` primitive (paired delta, date x market, MDE, null-coverage test in the
   suite) and widen `cluster_unit` / `INDEPENDENT_SAMPLE_UNITS` so the verifier accepts it. Mark date-only
   intervals non-decision-bearing.
2. Make `settlement_for_tape` return `None` without a ledger row unless the caller opts in; make trainers refuse
   non-ledger labels; add an `as_of` guard to `backtest.py` / `replay_backtest.py` default folder discovery.
3. Put an expected-versus-scored (date x market) grid and a `missing_settlement` count in every scorecard
   headline; anchor scoring liveness to the calendar, not to the latest label.
4. Treat settlement backfill as the evaluation critical path: it is the accrual rate of the only confirmatory
   instrument.
5. Cite MDE, not plug-in power, in the canon.
