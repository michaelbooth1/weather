# Retrain sizing memo: model-edge programme, 2026-10-19

Status: **sizing only, outcome-free.** No training was run. No label, settlement row, WU daily value or market price was
read. No data was fetched. Code base `origin/master` `6aac6de81a25bd939b954c5e7f29db02b2fd2fee` (`ML_MODEL_VERSION`
v0.5.12). Branch `claude/retrain-sizing-memo-20261019`. It feeds owner decision **OD-G3** in the draft GO/NO-GO rule
(`docs/research/model-edge-2026-10/go-no-go-rule-DRAFT-2026-10-19.md` on `claude/edge1-prereg-drafts-20261019` @
`7a2bbc53b393db57c50e51133154b8bb72bdc394`), which reads: "The retrain is either scored or explicitly waived."

Labels used below: **CODE** is traced in source at the commit above. **DOC** is quoted from a cited document. **INFERENCE**
is this memo's estimate and is not a measurement.

## 0. Verdict

**NOT FEASIBLE as a scored programme arm. FEASIBLE ONLY AS an explicit, scoped waiver**, optionally backed by an
outcome-blind build rehearsal. That rehearsal is not a score and authorises nothing.

**Binding constraint: the forward-date calendar.** It is set by inputs that do not exist yet:

- A 45-date forward arm must have its D0 on or before **2026-11-05** for its final read to land by 2026-12-21.
- A futility-only interim at 20 dates must have its D0 on or before **2026-11-16** to be read by Gate 1 (2026-12-07).
- The earliest honest freeze of a retrained model is about **2026-11-09 to 11-16** (INFERENCE, §4.3). That date is set by
  four gaps:
  1. there is no point-in-time forecast archive for October-December target windows in 2021-2023;
  2. no retrain lane runs end to end for a non-July target;
  3. the retrain-triggered reservation (§4.4) needs an owner decision;
  4. the arm needs a signed pre-registration.

The latest freeze that still works (11-05) falls before the earliest possible freeze (11-09), so the full read cannot fit
in the window.

**A scored retrain also could not produce a programme GO.** The best evidence on a season-matched HGB is the June artifact
scored in its own season: served/market **1.4233 [1.2428, 1.6589]** (EF §4e; register row 21). That interval excludes 1,
and GO clause (a) needs an upper bound of R below 1.00. A retrain addresses the measured seasonal-centre defect (EF §2,
§4e), not the information gap (EF §1c). INFERENCE: the most a retrain can plausibly do is move the out-of-season ratio
toward the in-season one.

Section 5 sets out what "explicitly waived" must say.

## 1. What a retrain would change

### 1.1 What is served today (CODE; lever-5 trace on `claude/model-edge-codecheck-20261019` @ `4743a7048dc00b3a4bda2b8a3a85817ea16d0109`)

- **Per-market HGB pickles.** There are 12, at `artifacts/models/hgb/feature_model_hgb{,_<market>}.pkl`. Each carries
  14 cutoff bundles (07-20 h).
- **Selected columns.** Each bundle selects 24-29 columns: Atlanta, Dallas, Denver, NYC and San Francisco 27; Austin,
  Chicago, Houston, Los Angeles and Seattle 24; Miami 29. These are bundle `feature_names`, read from the pickles on the
  workstation.
- **Fit dates.** The artifacts were fitted 2026-06-10..13 (EF §4b) and committed `fd728d4a4` (06-13) and `5b6f5af2d`
  (06-20). The pickles carry no `trained_at` field.
- **No release is bound.** `artifacts/releases/` is absent, so `release_serving` is RESEARCH_UNBOUND and the global
  pickles serve. The loader reads artifacts every time it constructs the model (register §0.1).

### 1.2 Which trainer produced them, and on what data (CODE)

- **Trainer.** The trainer is `python -m weather.calibration.feature_model --market <id>` (`feature_model.py:1174`,
  CLI `:1851`). It is manual: nightly has no all-market base-training step (`agent-report-2026-08-02-workstation-make-the-first-retrain-count.md`
  §1).
- **Labels and observations.** The trainer reads `TorontoHighTempModel.historical_target_cache()`
  (`model_climatology.py:71-221`):
  - labels: WU `daily/daily_summary.csv` buckets, with `row_count >= HISTORY_MIN_ROW_COUNT = 20`;
  - observations: WU `hourly/year=*/month=*/observations.jsonl`;
  - **prior years only** (`local_date.year >= target_date.year` is skipped);
  - within **+-7 days** (`HISTORY_WINDOW_DAYS`) of the model's target date.

  So no 2026 label can enter the HGB fit (EF §4c), and **the 2026-09-30 embargo does not touch HGB training at all.** It
  binds only the 2026-snapshot-trained parts in §1.3.
- **Forecast features.** `forecast_high` and `forecast_gap` come from the stitched `forecast_daily.csv` (EF §6, which says
  this contaminates the fit). Profiles come from `forecast_long.csv`. Marine and reanalysis sidecars are also read.
- **Guidance columns are always empty in training.** `build_historical_feature_record()` emits
  `empty_us_guidance_features()`, `empty_mrms_precip_features()` and `empty_eccc_gridded_features()` (2026-08-02 report
  §3 table). The NBM, MRMS and ECCC-gridded columns are therefore all-missing by construction.
- **Output paths are the served paths.** Outputs go to the **global served paths** through `writable_artifact_path`
  (`feature_model.py:1664-1692`). Run in a serving checkout, the trainer replaces the served model in place. Any retrain
  must redirect its output to the ignored `artifacts/candidates/` (artifacts/AGENTS.md).

### 1.3 Candidate changes and their status

| Change | What it would do | Status in this window |
| --- | --- | --- |
| **Season-matched refit of the per-market HGB** (target window centred in the scoring window) | Moves the fit window from late May-June to the served season. This is the root cause of the cool bias (EF §2: seasonal coverage; contrast −0.8346 C-eq [−1.4378, −0.2159]; current surface −0.64387). | **Input-blocked for October-December** (§2.2). The selected `forecast_high`/`forecast_gap` would be missing in training. |
| **Add captured NBM v2 as a model column** | The served HGB ignores NBM (FD line 54; lever-5 §1). Adding it means a new model trained on 2026 captured snapshots, because the historical builder has no NBM. | **Not a retrain of this model, and blocked three ways:** (a) the parser v2 fix (#190) is not on `origin/master` at `6aac6de81`; the v2 values exist only in the 111h extract for 08-01..09-29; (b) training on those dates re-uses the already-read 79a/81a/111h dates, and COMMON forbids using those tables as evidence for a new claim; (c) any NBM-reading candidate is in MG-1's reserved family (`reserved-confirmation-window.md`), so it cannot be scored on MG-1's 45 dates (D0 10-15, provisional last 11-28, may only move later). It would also compete with MG-1, RV-1 and HG-1 in that family. |
| **Refit of the 110g afternoon centering** | Per-context mean residuals at 15-18 h against settlement (`afternoon_residual_centering.py`). It is a post-processing refit, not a model retrain. | **Label-defined** (lever-5 §4), so it needs settled 2026 snapshots. Dev window 07-31..09-29 only: 61 dates at most, never pooled across 07-31. Those dates were served on the pre-fix path (lock-ins were no-ops until 10-06), so the residuals of the **current** path need a host replay of v0.5.12 on captured inputs. The lever-5 replay tool exists but is host-only. INFERENCE: it is feasible only as its own arm with D0 on or before 11-05, or as an A1 survivor if host replay and fit finish by **10-22**, which is unlikely. |
| **Read the point-in-time forecast file instead of the stitched one** | Fixes the fit contamination (EF §6). | Correct hygiene, but **priced as not the lever**: B − A = −0.000107 [−0.001588, +0.001349], power 0.066 (EF §6, `-09-42a`). Fold it into any retrain; do not test it alone (register row 20). |
| **Add the 11 extra free PIT fields** | Richer forecast surface. | Tested three times, INCONCLUSIVE_UNDERPOWERED (EF §1m). The 12-field pooled refit **worsened the centre**, and its own rule forbids replication. The 9-field wall is real (EF §0a). |

### 1.4 What EF §4a-bis and §4g block (DOC, re-checked in CODE)

- **§4a-bis.** The base-retrain lane (`weather.operations.base_retrain`) needs a verified research-only parent. The
  `first_party_corpus_assembly` contract branch now exists (`release_candidate_contract.py:881`). Preflight still needs
  explicit `--corpus-manifest` and `--pit-forecast-corpus-manifest` (`base_retrain.py:1635`). **No official base or PIT
  corpus manifest exists, and no retrain has ever completed** (register row 24, 2026-10-14).
- **§4g.** The exclusion registry `first_retrain_station_day_exclusions_v1` (`base_retrain.py:84-110`) names only the two
  KBKF **July** days. The lane is code-bound to:
  - `FIRST_RETRAIN_TRAINING_YEARS = 2021..2025`;
  - `SEASON_RADIUS_DAYS = 7`;
  - cutoffs 7-20.

  An October-December target needs a fresh completeness scan. Any newly failing station-day must be added to the
  code-owned list. **Never lower the 18-row floor** (EF §4g). The legacy trainer's own floor is 20 rows, a different
  constant from the 18 used by settlement.
- **PIT corpus season.** `forecast_training_corpus.py:52-53` defaults to May 10-Aug 31. A November target is outside the
  lane's corpus contract without a code change.
- **Release machinery is off the critical path** (EF §0b, owner 2026-08-09). A release is needed only if a retrain is
  ever to be served.

## 2. Data

### 2.1 Training sample per market (CODE plus DOC; no row was counted)

| Lane | Population per market and target window | Fleet | Validation clusters |
| --- | --- | --- | --- |
| Legacy `feature_model.main` | All prior WU years within +-7 days. **163-165 usable days per US market and 660 for Toronto** for a late-July centre (2026-08-02 report §3). One row per day per cutoff. | about 2,500 days x 14 cutoffs | holdout-year blocked (`feature_blocked_validation_plan`, default `holdout_year`): about 30 year clusters. The forecast feature is missing before 2018 (`feature_model.py:1189`). |
| `base_retrain` (2021-2025) | **75 days** (5 years x 15 days), 1,050 cells. Denver had 74 days / 1,036 cells in July. | **12,600 cells** (12,586 after the July exclusion; `-09-42a`) | 5 year clusters |

**These are small samples.** Each per-hour HGB fits 75-165 rows per US market. That is why per-market fits are noisy, and
INFERENCE says it is why the 12-field refit could not show a gain (EF §1m: power 0.058-0.148).

### 2.2 Forecast inputs for an October-December target (metadata only)

- **Production and workstation archive.** `data/forecast_history/<station>/` covers **May 10-Jun 30** in every year. The
  workstation manifest (2026-06-23, `cyyz`) gives `season_window` [5,10]-[6,30], 52 days per year for 2018-2025 and 45
  for 2026. `-09-41a` added Jul 17-Aug 14 on production only (EF §4f). **The archive has zero rows for October-December**
  (EF §4b shape).
- **Research corpora (workstation only; `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`; not the production PIT contract; EF §1m).**
  `pit-11field-2024-2025-calendar-extension` contains `temperature_2m` plus 10 fields for **Sep 1-Dec 31, 2024 and 2025**
  (plan scope read; manifest `501e5d0e22a0…`, 96 units, PARTIAL with explicit gaps).
  `pit-12field-multiyear-2021-2025` covers May 10-Aug 31 only.
- **So for a November-centred window**, point-in-time `forecast_high` exists for **2 of the 5 lane years (2024-2025)**,
  and then only as a research corpus. 2021-2023 need a new free Previous-Runs collection. **That is an external fetch,
  outside this track** (COMMON); it needs an owner yes and a production run.
- Without that fetch the choice is:
  - train with `forecast_high` missing on 60% of rows, against serving where it is always present (a parity defect by
    construction); or
  - drop the forecast columns, which turns the model into observations plus climatology and is a different model.

### 2.3 Evaluation dates allowed (COMMON; DL 2026-10-17)

- **Development:** 2026-07-31..09-29 only (61 dates). Never pool across 07-31 (EF §5). Those dates are already read by
  79a, 81a, 111h and the swarm.
- **Forward:** labels for dates on or after 2026-09-30 may be joined only under a signed pre-registration. **Nothing for
  10-16..11-13 is read before the panel closes on 11-13.**

### 2.4 Is it enough? (DOC)

The evaluation clusters are markets, not dates:

- With 11 US clusters, the crossed rule caps power near **40%** at half the MG-1 effect, at any season length (EF §10j).
- The 12-cluster MDE floor is about **3.2% of the out-of-season gap** at any D (EF §1d).
- Fixed-market inference (methods annex; MG-1) reaches 0.80 at 45 dates at the half effect (register row 13).

The only sized prior for a retrain is the §1d season-matched refit proxy: **24.893% [−20.5%, +55.2%]** of the
out-of-season gap. It is unpowered and was never tested as a candidate. INFERENCE: if it were real, it would clear the
3.2% floor, but GO clause (a) still needs R below 1 (see §0).

## 3. Compute and wall-clock on this 32 GB workstation

Recorded timings (DOC):

- **Feature assembly.** `agent-report-2026-08-13-workstation-retrain-rehearsal.md` measured rich feature assembly for 12
  markets at **12.021 s**, peak RSS **315.83 MiB** (0.795-1.062 s per market). The official CLI took 0.978 s / 166 MiB
  through the parent load.
- **Fits were never timed.** Twelve-market fits were "not reached" there, and `-09-42a` completed 36 market fits without
  recording a time.
- **Pooled lane.** `agent-report-2026-07-22-workstation-pool-city.md`: 350 checkpointed tasks in **23.26 min** (pooled
  lane, not the per-market HGB).

Structure (CODE): `feature_model.main` runs blocked leave-one-out per cutoff hour. Per validation day it fits:

- one `LogisticRegression`;
- one `HistGradientBoostingClassifier` (`max_iter=50`, `max_leaf_nodes=15`, one tree per class per iteration);
- inner calibration folds (`inner_hgb_calibration_rows`);
- a final refit.

The file's own comment calls the leave-one-out cost O(n²). `--skip-loo` exists, but it ships flat 0.80 blend weights
without validation, the trap the file warns about (`feature_model.py:63-66`).

INFERENCE, to be replaced by a one-market pilot timing:

| Lane | Estimate |
| --- | --- |
| `base_retrain` (75 days) | minutes per market |
| Legacy, US (about 165 days) | about 1 h per market |
| Legacy, Toronto (660 days) | several hours (at least 16x a US market by the n² term) |
| Whole fleet, serial, under `scripts/ops/workstation_heavy.ps1` | under one day |

Memory stays far below 32 GB. **Compute is not binding.** The scoring replay is the costlier step: captured
`replay_inputs.jsonl` live only on the capture host (lever-5 §3.1), inside the 00:30-09:00 leased window.

## 4. The fair-evaluation path and the calendar

### 4.1 What must happen before a retrained model can be an EDGE arm (CODE plus DOC)

1. **Lane and inputs.** Pick the legacy trainer (redirected to `artifacts/candidates/`) or `base_retrain` (official
   corpus manifests). Collect the October-December 2021-2023 PIT temperature (owner yes; production). Run a completeness
   scan and extend the code-owned exclusion list.
2. **Fit and freeze.** Fit; then record the arm hash (artifact bytes + code commit + feature contract + data manifests).
   Score the fit on its own training set first (EF §5).
3. **Parity.** Run `weather.reporting.scorecards.train_serve_feature_parity` against the known-defects file
   (`tests/fixtures/train_serve_feature_parity_known_defects_v0.1.json`). Then a captured-input replay must show
   probability mass error at most 1e-10 and no empty distribution; `-09-42a`'s rich candidate returned one on a San
   Francisco input.
4. **Reservation.** Freezing the **first retrain candidate** triggers the armed reservation
   (`reserved-confirmation-window.md`, Trigger row). Once declared, that window is **absolute**: not read, not evaluated,
   and MM paper scoring must stop on those dates (rules 3-4). Unless the owner narrows it, as was done for MG-1, a retrain
   freeze would collide with EDGE-1 and maker scoring on the same dates.
5. **Pre-registration.** Signed by the owner under the methods annex, as its own Holm family or a new EDGE-1 arm. Two
   rules constrain the form:
   - the arm must be frozen before its own D0 (EDGE-1 §1, M5.2);
   - A1 survivors close on **10-22** (EDGE-1 §1), which is impossible for a retrain.
6. **Vector of record.** Either:
   - a shadow stage on the capture host that stores the arm hash per snapshot, with coverage of at least 90% in 00-16
     (EDGE-1 §7). That is roll-sensitive code (`roll_verdict.ps1`, quiet window 01:00-04:00) and needs one full prior day
     of stored vectors; or
   - a paired host replay of the arm against a replayed A0 on captured inputs, as the evening-fix scorer does. That avoids
     a roll but uses the leased night window.
7. **Season drift.** One frozen artifact covers only +-7 days of its centre. Across a 45-date window (about 6.5 weeks) it
   drifts out of season. A nightly rolling refit is a different arm: its hash is code + data, not bytes. INFERENCE: this
   needs its own pre-registration.
8. **Serving, only after a GO.** Release binding, an `ML_MODEL_VERSION` bump, the roll verdict and the quiet window
   (DL 2026-10-13 item-337 pattern; GO/NO-GO §3).

### 4.2 Countable forward dates (logistics, not rules)

Assumptions:

- Every date is countable (methods M0: at least 9 of 11 markets); each miss shifts the read one date later.
- A date is readable on the second local day after it (EDGE-1 §2.1: date 11-13, read 11-15).
- Every join waits until after 11-13 (DL 2026-10-17).

| Arm D0 | Dates readable by Gate 1 (12-07: dates through 12-05) | Dates readable by final (12-21: dates through 12-19) | 45th date / read |
| --- | ---: | ---: | --- |
| 10-25 (EDGE-1, not-held branch) | 42 | 45 | 12-08 / 12-10 |
| 10-28 (EDGE-1, held branch) | 39 | 45 | 12-11 / 12-13 |
| **11-05 (latest D0 for a 45-date final by 12-21)** | 31 | **45** | 12-19 / 12-21 |
| 11-09 (earliest retrain freeze, best case) | 27 | 41 | 12-23 / 12-25 |
| **11-16 (latest D0 for a 20-date interim by Gate 1)** | **20** | 34 | 12-30 / 01-01 |
| 11-29 (NBM-reading arm after MG-1's provisional last date, 11-28) | 7 | 21 | 01-12 / 01-14 |

Three reading notes:

- The interim is **futility-only and spends nothing** (EDGE-1 §4). A retrain arm read at 20-41 dates can support an early
  NO-GO but cannot give a GO.
- The 88a-hold ruling OD-A6 also governs the market vectors that a retrain arm would join to.
- DST ends 11-01 (OD30 lapses 11-02). Every retrain D0 above is after it.

### 4.3 Earliest realistic freeze (INFERENCE)

Earliest dates for each step:

1. owner decisions on lane, fetch and reservation: the 10-23 sign-off at the earliest, and more likely the following
   session;
2. production fetch plus manifest: about 2-4 days after the yes;
3. lane code for a non-July target: a few days of work plus focused tests;
4. fit: under one day;
5. parity and replay checks: host night windows;
6. pre-registration signature.

Taken together, freeze lands about **11-09..11-16** in the best case, on the boundary for a Gate-1 interim and past the
11-05 limit for a final.

## 5. Verdict detail and what "explicitly waived" means

**Verdict: NOT FEASIBLE in this window as a scored arm. FEASIBLE ONLY AS an explicit waiver**, with an optional
outcome-blind retrain-readiness rehearsal. That rehearsal would cover the steps 1-3 inputs, lane and parity on a
candidates root, with no score and no freeze, so the reservation is not triggered. Binding constraint: the calendar, as in
§0. Secondary constraint: even a perfect score cannot meet GO (a) on current evidence (EF §4e).

A waiver under OD-G3 should be a DECISION_LOG row that says the following.

1. **Not scored, and why.** "The retrain is not scored in the 2026-12 model-edge programme. A 45-date forward arm needs
   D0 on or before 11-05, and no retrained candidate can be frozen before about 11-09: there is no October-December
   2021-2023 PIT forecast archive, and no retrain lane runs end to end. Cite this memo."
2. **NO-GO scope.** A NO-GO under the programme rule then means "no out-of-season edge for A0, A1, A2, MG-1 and NBM-2".
   It **does not** mean "a retrained model has no edge". The exhaustion register keeps row 24 / order 15 and L7 **OPEN,
   marked WAIVED-FOR-PROGRAMME, not exhausted or NULL** (the register's UNTESTABLE ≠ NULL rule applies by analogy).
3. **Bound on what the waiver forgoes.** The season-matched in-season ratio is 1.4233 [1.2428, 1.6589] (EF §4e). A
   retrain is therefore not expected to reach R below 1, and the waiver forgoes at most the out-of-season-to-in-season
   closure: §1d proxy 24.893% [−20.5%, +55.2%], unpowered. INFERENCE: this item is the main residual risk the owner
   accepts.
4. **What reopens it.** Either:
   - a season-matched retrain lane that is ready (inputs, lane, parity) with a signed forward pre-registration; or
   - the 2027 in-season window (from May 10), the only place the in-season figure can be re-measured (register §5,
     structural limits).

   A late GO reopens weather in any case (GO/NO-GO §3).
5. **No reservation.** The waiver freezes no candidate, so the reservation trigger does not fire. The rehearsal, if run,
   must also freeze nothing.

The alternative, **scored**, would have to name:

- the lane;
- the arm hash before D0;
- a separate Holm family or an EDGE-1 amendment;
- a narrowed reservation;
- the look (futility interim only by Gate 1; final after 12-21 unless D0 is on or before 11-05).

The programme decision would then sit at INCONCLUSIVE on 12-21 for that arm, and the owner would decide with a partial
read.

## 6. What this memo does not claim

- No retrain effect size; no power figure computed here. The figures quoted come from their cited sections.
- No timing measurement (§3 is labelled INFERENCE).
- Nothing about in-season edge.

## Sources

- EF §0a, §0b, §1c, §1d, §1m, §2, §4a-bis, §4b, §4c, §4e, §4f, §4g, §5, §6, §10h, §10j, §10k, §10q.
- [Exhaustion register](../operations/EXHAUSTION_REGISTER.md) §0.1, rows 7, 13, 20, 21, 24; L7, L19; §5 orders 15-16.
- [Reserved confirmation window](../operations/reserved-confirmation-window.md); DECISION_LOG 2026-10-13, 2026-10-17.
- Branch drafts: EDGE-1 annex, GO/NO-GO rule (`claude/edge1-prereg-drafts-20261019` @ `7a2bbc53b`); lever-5
  (`claude/model-edge-codecheck-20261019` @ `4743a7048`).
- Reports: `agent-report-2026-08-02-workstation-make-the-first-retrain-count.md`,
  `agent-report-2026-08-08-workstation-exclude-denver-station-days-and-fit.md`,
  `agent-report-2026-08-13-workstation-retrain-rehearsal.md`, `agent-report-2026-07-22-workstation-pool-city.md`.
- Code: `calibration/feature_model.py`, `model/model_climatology.py`, `model/model_constants.py`,
  `operations/base_retrain.py`, `operations/release_candidate_contract.py`, `sources/forecast_training_corpus.py`,
  `calibration/afternoon_residual_centering.py`.
