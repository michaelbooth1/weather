# Retrain sizing memo: model-edge programme, 2026-10-19

Status: **sizing only, outcome-free.** No training was run. No label, settlement row, WU daily value or market price was
read. No data was fetched. Code base `origin/master` `6aac6de81a25bd939b954c5e7f29db02b2fd2fee` (`ML_MODEL_VERSION`
v0.5.12). Branch `claude/retrain-sizing-memo-20261019`. It feeds owner decision **OD-G3** in the draft GO/NO-GO rule
(`docs/research/model-edge-2026-10/go-no-go-rule-DRAFT-2026-10-19.md` on `claude/edge1-prereg-drafts-20261019` @
`7a2bbc53b393db57c50e51133154b8bb72bdc394`), which reads: "The retrain is either scored or explicitly waived."

Labels used below: **CODE** is traced in source at the commit above. **DOC** is quoted from a cited document. **INFERENCE**
is this memo's estimate and is not a measurement.

## 0. Verdict

> **r2 (2026-10-20), §r2.4:** still waiver-only for the programme decision. At best, a futility-only arm R0 with D0 on
> 11-17, and only if the owner approves the 2021-2023 Previous Runs fetch and a narrow reservation ruling by about 10-30.
> A 20-date look cannot give GO. One-market timing pilot (§r2.3): 4 h 50 min for Atlanta on today's trainer.

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
- **Selected columns.** Each bundle selects 24-29 columns, in two schemas:
  - `toronto_feature_store_v0.3`, 27 columns: Atlanta, Dallas, Denver, NYC, San Francisco;
  - `toronto_feature_store_v0.2`, **24 columns**: Austin, Chicago, Houston, Los Angeles, Seattle. These lack
    `minutes_since_cutoff`, `live_reading_temp` and `live_reading_minus_high`;
  - 29 columns: Miami and Toronto.

  These are bundle `feature_names`. *Corrected r3 (2026-10-21)*: r1/r2 implied every market was v0.3. Source: the
  served-list extraction on `claude/retrain-column-allowlist-20261021`, where HGB bundles and LR coefficients agree in all
  12 markets across 14 cutoffs.
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
- **PIT corpus season.** `forecast_training_corpus.py:52-53` defaults to May 10-Aug 31. The season is a plan flag
  (r2), but see the r3 correction under §r2.1: that module has no HTTP client, and on master it always requires all 21
  fields.
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

## r2 (2026-10-20): season-coverage candidate, what can freeze by 11-16, and the restated verdict

Requested by master-agent on 2026-10-20 (lever 9; the owner wants more pace on model leads). Same boundaries as above,
with one addition: a ONE-market timing pilot was run under `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -Queue`.
It trained on prior-year WU rows only, wrote only to `C:\t\rtp`, and no score was read (§r2.3).

**Corrections to r1:**
- §1.4 said a November target is outside the PIT corpus contract "without a code change". That is wrong. The season is
  a CLI flag: `python -m weather.sources.forecast_training_corpus plan --season-start MM-DD --season-end MM-DD --years ...`
  (`forecast_training_corpus.py:1576-1577`). Only the default is May 10-Aug 31.
- §1.1 understated the parity problem. Today's trainer does not reproduce the served column set; see §r2.2.

### r2.1 The season-coverage fix for the cool bias

**What is documented (DOC):**
- The base HGB centre is cool by **−0.64387 C-eq** on the current surface (EF §2).
- The cause is measured as **seasonal coverage**, not staleness. The contrast is in-season about −0.18 against
  out-of-season about −1.02 C-eq, a difference of **−0.8346 [−1.4378, −0.2159]** (EF §2, `-09-31a`; register row 7).
- Every served HGB was fitted 2026-06-10..13 on a training window of prior years ±7 days around the run date (EF §4b;
  §1.2 above). Every date served since about July is therefore out of the model's training season.
- Scored in its own season, the same model is still at **1.4233x [1.2428, 1.6589]** the market (EF §4e). The retrain fixes
  the centre, not the information gap (EF §1c, §4e).

**What a season-coverage retrain changes (CODE):** exactly one thing, the date the model is fitted for.
`historical_target_cache()` keeps prior-year days within `HISTORY_WINDOW_DAYS = 7` of the model's target date
(`model_climatology.py:112-122`). The target date defaults to the run date (`toronto_model.py:125`, `config_for_date`).

The candidate is fitted for a **pinned centre date inside the scoring window**. Labels and observations are prior-year
WU daily and hourly rows in that ±7-day window. No 2026 row is used: the trainer skips the target year.

Everything downstream is unchanged:
- the climatology prior at serve time (already season-matched, because it is computed for the serving date);
- the post-processing stages;
- the lock-ins;
- the calibration.

**Forecast inputs for an October-December centre:**

| Years | `forecast_high` source available | Status |
| --- | --- | --- |
| 2018-2020 | none | The trainer sets the feature to missing before 2018 (`feature_model.py:1189`). 2018-2020 have no PIT rows (EF §6). |
| 2021-2023 | **none** | **Missing.** |
| 2024-2025 | `temperature_2m_previous_day1..7`, Sep 1-Dec 31 | Workstation research corpus `pit-11field-2024-2025-calendar-extension`, manifest `501e5d0e22a0…`, PARTIAL with explicit gaps. `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`; not the production PIT contract (EF §1m). |

- **The free source for the missing 2021-2023 rows** is the Open-Meteo **Previous Runs API**
  (`previous-runs-api.open-meteo.com`, `PREVIOUS_RUNS_URL` in `sources/forecast_history.py:39`), field
  `temperature_2m_previous_day{1..7}`.
- EF §1m measured `temperature_2m` as complete for 2021-2025 on that host. The same host produced the existing 2,135
  fixed-lead rows per station (EF §4f).
- ~~The repository's own collector covers it: `forecast_training_corpus plan ...`, then `resume` and `materialize`.~~
  **Corrected r3 (2026-10-21):** `weather.sources.forecast_training_corpus` has **no HTTP client**. Its docstring says the
  bytes come from "a separately authorized collector". Its CLI is `plan` / `resume-status` / `materialize` only.

  On master the plan always requests all 21 `DEFAULT_SOURCE_FIELDS`, and `materialize` requires every one of them. Only
  `temperature_2m` exists for 2021-2023 on the free tier, so master cannot build this corpus as is.

  A downloader and a `--fields` option are now built on `claude/pit-corpus-fetch-20261021` @
  `b28c3d94151d2e65eff675a4dc1913007da863b0`, pending master review. That change is **roll-sensitive** and lands through
  the quiet-window merge after N12. **The fetch is not yet run.**
- Scale: the July window took about 60 free-tier calls for 12 markets (EF §4b). The research collections ran 96-120
  units each (EF §1m).
- Other fields are not available for 2021-2023 on the free tier (EF §1m), so a temperature-only forecast feature is the
  honest surface.
- **Fetching this needs an owner yes, and it is a production or master action. It was not done here.**

**Without that fetch**, the only honest choices are:
1. fit on 2024-2025 only (30 days per market per cutoff, too thin for a 14-hour per-market HGB; INFERENCE); or
2. fit 1995/2021-2025 with `forecast_high` missing on every row that has no PIT value.

Option 2 trains a model that rarely sees the column which serving always fills: a parity defect by construction (§2.2).

### r2.2 Minimal candidate that could freeze by 11-16 ("R0")

| Element | Definition |
| --- | --- |
| Lane | Legacy per-market trainer `weather.calibration.feature_model.main`, run through a wrapper that redirects every write. `base_retrain` stays blocked on official corpus manifests (§1.4) and adds no value for a futility-only arm. |
| Markets | US11 (EDGE-1 population). Toronto is optional; it has about 4x the rows of a US market, so up to 16x the fit time under the O(n²) cost (INFERENCE). |
| Centre date | One pinned date per window, frozen in the hash. Proposal: **2026-11-28** (window 11-21..12-05 of prior years), the middle of the dates an 11-17 D0 would score. INFERENCE: one artifact covers ±7 days; the 34 days from 11-17 to 12-19 need **two** centres (for example 11-24 and 12-10, switched on 12-02) or a frozen nightly-refit rule. Two frozen artifacts are simpler and hash cleanly. |
| Labels and observations | Prior-year WU `daily_summary.csv` (rows ≥ 20) and hourly observations, ±7 days, years < 2026, as `historical_target_cache()` already does. Plus a completeness scan of the window; any station-day below the 18-row settlement floor goes on a code-owned exclusion list (EF §4g). |
| `forecast_high` / `forecast_gap` | PIT lead-1 daily maximum from `temperature_2m_previous_day1` (the "honest" variant A of `-09-42a`). 2024-2025 come from the workstation research corpus; 2021-2023 come from the fetch above (owner yes). Built into a candidate `forecast_daily.csv` under a scratch data root, **never** the production `data/forecast_history/`. |
| Columns | **Pin each market's served column list** (24-29 columns: the bundle `feature_names` of today's pickles, schema v0.2 or v0.3 by market, §1.1; **minus `pressure` and `pressure_trend_3h`, owner 2026-10-21, §r3**). See the parity note below. |
| Model and hyperparameters | Unchanged: `HistGradientBoostingClassifier(max_iter=50, max_leaf_nodes=15, learning_rate=0.05)`, LR fallback, late-day coefficients, leave-one-out per-hour temperature and blend tuning (`RUN_LOO = True`). |
| Output path | `artifacts/candidates/retrain-r0-<centre>/` (ignored by git; artifacts/AGENTS.md). Never `artifacts/models/`. |
| Arm hash | sha256 over the artifact bytes, code commit, column lists, centre dates, data manifests and the exclusion list. |

**Parity note: the trainer on master does not reproduce the served columns (CODE).** On master,
`feature_model_columns()` builds 217 numeric + 12 one-hot = **229 columns** for Atlanta from the
`toronto_feature_store_v1.16` schema (221 `FEATURE_COLUMNS`, minus the two F-market pressure columns). Most of those
columns are always missing in historical rows (guidance, MRMS, ECCC gridded; see §1.2).

The served Atlanta bundle has **27 columns of schema v0.3**, and it still selects `pressure` and `pressure_trend_3h`. The
current training policy `native_station_pressure_train_serve_v1` excludes those as unservable in F markets
(`feature_training_policy.py`; EF §4 "dead in F markets by design").

So R0 needs:
- a **column-allowlist option** in the trainer (small code; `calibration/feature_model.py` was roll-free in
  the 2026-08-12 report, but the verdict must be re-taken with `scripts\ops\roll_verdict.ps1`);
- an owner or programme choice between:
  - **(a) the served columns minus the two dead F-market pressure columns.** Recommended: it isolates the season effect
    and removes a known train/serve skew;
  - **(b) the served columns as is,** which isolates the season effect exactly but keeps the skew.

**Build steps and wall-clock on this 32 GB workstation:**

| # | Step | Who | Estimated wall-clock |
| --- | --- | --- | --- |
| 1 | Owner yes: R0 scope, the 2021-2023 Previous Runs fetch, the reservation ruling (below) | owner | the next sign-off session |
| 2 | Fetch plan, collect and materialize 2021-2023 (US11, two windows) | production / master | about 1 day, including the manifest (INFERENCE from EF §4b scale) |
| 3 | Column allowlist plus pinned centre option in the trainer; candidate `forecast_daily.csv` builder from PIT rows; completeness scan; focused tests | workstation | 2-3 days of work |
| 4 | Fit 11 markets x 2 centres under `workstation_heavy.ps1` | workstation | **measured 4.84 h for one US market** with the current trainer (229 columns, full leave-one-out; §r2.3), so about 53 h per centre for US11 and about 106 h for two centres, serially. INFERENCE: with the 27-column allowlist, much less (the HGB histogram and split cost scales with column count), probably under one day for both centres. Re-time one market after the allowlist lands, before scheduling the fleet. |
| 5 | Train-on-own-training-set check (EF §5); `train_serve_feature_parity` scorecard against the known-defects file; captured-input replay mass checks on dev dates <= 09-29 (mass error <= 1e-10, no empty distribution) | workstation + host replay window | 1-2 host nights |
| 6 | Research-only immutable release holding R0's base components, **no active pointer** (`all_shadow_release_bootstrap` / `release_candidate_build`; the `first_party_corpus_assembly` lineage branch exists, EF §4a-bis). The vector of record binds R0 through `serving_bundle` (`model_features.py:59-71` `_bound_base_component`), not the global pickles | workstation + production | 1-2 days |
| 7 | Vector of record: a paired host replay of R0 against replayed A0 on each forward date's captured inputs (no capture-loop code, so no roll), or a shadow stage (roll-sensitive, quiet window) | production | host nights from D0 |
| 8 | Pre-registration (methods annex, own family, futility-only interim) signed with the arm hash | owner | at freeze |

INFERENCE: steps 1-8 fit between the next owner session and **11-16** only if step 1 happens by about 10-30 and step 2
by about 11-04. Steps 5-6 are the long poles.

**Reservation interaction (DOC: `reserved-confirmation-window.md`).** Freezing "the first retrain candidate" triggers the
armed window on the next target date. Once declared it is **absolute** (rule 3):
- not read, enumerated, evaluated or substituted;
- **MM paper scoring must stop** on those dates (rule 4).

An R0 freeze on 11-16 would therefore hold 11-17 onward. That collides with:
- EDGE-1 A0/A1/A2 dates up to 12-08 / 12-11;
- MG-1's tail, provisional last 11-28;
- the maker shadow and paper scoring.

The file also says that if no endpoint is powered at achievable N, say so and **do not declare a confirmation**. A
20-date futility-only arm confirms nothing.

**The narrowest owner ruling that avoids the collision** is a DECISION_LOG row, modelled on the MG-1 narrow scope of
2026-10-04, with five parts:
1. The retrain-triggered window is declared at R0's freeze with **narrow scope**: the dates are held out **only** against
   retrain-family candidates. That means any base HGB/LR/late-day artifact not byte-identical to the June-fit artifacts,
   plus any re-selection, re-tuning or re-centring of R0.
2. **Explicit exemption**, identical in form to MG-1's: EDGE-1 arms, MG-1, the evening-fix scorer, t3-r3, maker shadow and
   paper scoring, and every other use of these dates' captures, served vectors and settlements.
3. R0's looks are a futility interim only. It is non-confirmatory, so N is not sized as a confirmation (Sizing at freeze).
4. Rule 5 still binds: the freeze is not timed to dodge dates.
5. The window's size is R0's 45 dates. A later confirmatory retrain needs its own fresh window.

Without this ruling, R0 must not freeze inside the programme.

### r2.3 One-market timing pilot (measured)

**Run.**
- Tool: `python -m tools.research.retrain_pilot.run --market atlanta --target-date 2026-10-20`, under
  `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -Queue`. Ticket 1; no other ticket was queued.
- Started 2026-10-20 17:41 local; exit 0 at 22:31.
- Code: this branch at `17a398fa04c64f93f657b640f0f68191811a7384`.
- The tool is admitted to the offline allowlist on this branch: one line each in `workload_admission.ps1` and the Codex
  hook, and the two allowlist tests. The test file passes alone (28 passed, 15 skipped). Run alongside the other two
  files, 3 mutex/teardown tests failed. Those 3 skip when run alone, so the failure looks environmental, not caused by
  this change.
- Reads came from the main checkout's `data/` and `artifacts/`. Every write was redirected to `C:\t\rtp`.
- The trainer's stdout (which holds leave-one-out scores) went to a file that was **not read**. Only the
  "Loaded …" and "Cutoff Hour … (N days)" lines were extracted.

**Measured.**

| Quantity | Value | Source |
| --- | --- | --- |
| Wall-clock, one US market, full LOO, all 14 cutoffs | **17,428.8 s (4 h 50 min)** | tool summary |
| CPU time | **more than 346,479 CPU-s** at 21:55, about 4 h 14 min in (about 22 of 32 logical cores busy on average; HGB OpenMP) | `Get-Process` sample |
| Peak working set | **265,850,880 B (253.5 MiB)**, sampled during the run | `Get-Process` `PeakWorkingSet64`; the tool's own reading returned null |
| Training days per cutoff hour | **165** for each of the 14 hours (prior-year days within ±7 of 10-20, WU rows ≥ 20; 2026 excluded) | trainer stdout, structural lines |
| Forecast-history days loaded | 461, all inside May 10-Jun 30 (manifest), so **zero** fall in the Oct 13-27 window: `forecast_high` was missing on every training row | trainer stdout; §2.2 |
| Columns fitted | **229** (schema `toronto_feature_store_v1.16`), against 27 in the served Atlanta bundle (schema v0.3) | scratch pickle structure |
| Output | 14 cutoff bundles; HGB pickle 18,214,472 B, sha256 `135d886b80c014dfad4080f14e5397979066b646e8762f85ebeba31607fcdc50` (scratch, then deleted; not a candidate) | scratch dir |

**Guards checked after the run.** In the main checkout:
- `git status --short artifacts` was empty;
- `data/wunderground/katl/analysis/feature_model_report_atlanta.md` still had its 2026-06-10 mtime;
- this worktree's `artifacts/` was unchanged.

**What the pilot shows** (no score was read):
1. Compute is hours per market. It is not binding for one market, but it is for a fleet of two centres on today's
   trainer (about 4.4 days serial).
2. The trainer on master cannot reproduce the served model's column contract. R0 needs the allowlist (§r2.2).
3. An October-centred fit has no forecast feature at all until the PIT rows of §r2.1 exist. This confirms §2.2 on real
   data.

### r2.4 Verdict, restated

**Waiver-only for the programme decision. Feasible at best as a futility-only arm with D0 on 11-17**, and only if all of
the following happen in time:
- the owner approves by about 10-30 both the 2021-2023 Previous Runs fetch and the narrow reservation ruling above;
- the column-allowlist trainer change lands;
- R0 freezes with a signed futility-only pre-registration by 11-16.

**A 20-date look cannot give GO.** The interim is futility-only and spends no alpha (EDGE-1 §4; methods M4). GO requires
a final-look Holm rejection plus the falsifiers. Even at a final look, GO clause (a) needs R below 1, against a
season-matched in-season ratio of 1.4233 [1.2428, 1.6589] (EF §4e).

What R0 could contribute by Gate 1 is one of two things:
1. A futility crossing. This makes the OD-G3 waiver unnecessary: "scored: futility".
2. No crossing. That leaves the retrain row OPEN for the 12-21 INCONCLUSIVE decision.

Binding constraint, unchanged: the calendar. A missed owner step by 10-30 or a late fetch moves D0 past 11-16, and R0
then has no read before Gate 1.

## r3 (2026-10-21): owner decisions

Relayed by master-agent, about 16:1x on 2026-10-21. The answers are quoted verbatim.

- **Pressure columns: "Drop pressure (Recommended)".**
  - R0 = the served base columns **minus `pressure` and `pressure_trend_3h`**, per training policy
    `native_station_pressure_train_serve_v1` (`calibration/feature_training_policy.py`).
  - **Difference from served, recorded:** every served bundle that selects those two columns loses them in R0. All other
    columns stay exactly as served, per market and per schema (v0.2 24 / v0.3 27 / 29; §1.1). That includes the served
    Atlanta bundle (§r2.2).
  - This is option (a) of §r2.2.
- **Late-day models: "No, base models only (Recommended)".**
  - R0 refits the **base models only**: the per-market HGB and LR feature models.
  - The served late-day continuation models (`late_day_model_coefs*.json`) stay unchanged. R0's arm hash must bind the
    served late-day bytes.
  - The trainer's late-day output (written by `feature_model.main`, §1.2) is discarded.
- **EDGE-1 bundle questions approved by the owner on 2026-10-21:**
  - **OD-G3:** the retrain is **waived for the 12-21 decision**. The best case remains a futility-only R0 from 11-17
    (§r2.4).
  - **(j):** the 2021-2023 Previous Runs fetch: **yes**. It is still not run; it waits on
    `claude/pit-corpus-fetch-20261021` (§r2.1).
  - **(k):** the narrow reservation ruling of §r2.2: **yes**.
- **Consequences for §r2.4:**
  - The waiver now stands as decided.
  - Two of the three conditions for an 11-17 D0 are met (owner yes on fetch and reservation).
  - What remains:
    - the fetch branch landing and running;
    - the column-allowlist trainer change (`claude/retrain-column-allowlist-20261021`) landing;
    - R0 freezing by 11-16 with a signed futility-only pre-registration.
  - A 20-date look still cannot give GO.

## 6. What this memo does not claim

- No retrain effect size; no power figure computed here. The figures quoted come from their cited sections.
- No timing measurement in r1 (§3 is labelled INFERENCE); r2.3 adds one measured one-market timing.
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
