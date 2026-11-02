# L48 station-pooled training corpus: frozen rule (rows 108 C / 109 K)

Status: **frozen at this file's first commit**. Its sha256 is in `rule_station_pool.md.sha256`. Any later change
is a dated clarification in a separate file, committed before the rows it affects. Rows: DEV_WINDOW_LEDGER
**108** (C: corpus build and controls; campaign count 207) and **109** (K: LOYO rung plus its dev read; count 208).
Both ledger lines go in a docs head, not in this branch.

Master GO 2026-11-01 at N = 300, relayed by the coordinator. Development evidence only, no edge claim:

- no live, capture, Scheduler or credential action;
- no paid source;
- no B-bound file edited (they are imported read-only);
- nothing dated after 2026-09-29 is read;
- no 88a, panel or settlement data for 2026-09-30..10-15 is read.

S0 evidence: `s0.md` (same folder). The station filter folds in `station_filter_spec_DRAFT.md` @ `4dacfa4fc8c11cf51ef4d628d82c620c34269364`,
with the changes listed in §3.

**Allowlist entry approved by master 2026-11-01, module weather.calibration.station_pool_corpus, branch
claude/station-pooled-corpus-s0-20261101 @ 94fdcc475c8cd3b24a0fa45a8a00a2f4b290b8de.**

## 0. Master's rulings, written in

1. **R-I scope.**
   - R-I (EF §10af) closed scale *variants*: model changes to the scale or width on NBM-anchored arms.
   - This rung changes **only the training rows**. The code, hyperparameters, features, kernel and scale model are
     identical to P3d_N_fix. That makes it a sample-size lever, a different family, and R-I does not cover it.
   - No scale, temperature or kernel change is made here.
2. **N = 300.**
   - Going to about 1,000 stations needs a new go, and only after the 300-station arm survives LOYO.
   - The 100-station dose arm is **descriptive only**: reported beside the verdict, never gating, no multiplicity
     spent.
3. **No V5.0 2026 pool.** Training is Aug-Sep 2021-25 only. The V4.x → V5.0 shift (register X64) is handled by the
   **per-version parse and mean check C-d** (§6). The year folds are reported per year as well. Each of 2023, 2024
   and 2025 is its own NBM version (V4.1, V4.2, V4.3) and 2021-22 share V4.0, so the per-year table is also the
   per-version table. Neither substitutes for the dev gate on V5.0.
4. **Storage.**
   - Raw files go under `C:\t\l48\corpus`; the built corpus is immutable under `C:\t\l48\corpus\corpora\<sha256>\`.
   - Before each fetch or build phase, a free-space precheck refuses to start if projected free space after its
     writes would fall below **8 GB**. The same check runs again during the phase, and the phase stops if free
     space drops below 8 GB.
   - NBP is streamed bulletin by bulletin (download, extract, delete). The full set is never staged.
5. **Kill gate as drafted** (§7). The station filter (§3) is frozen here, before any label is read.
6. **Dev-stage descriptive output (tied to L47).** Only at the dev stage, and only after master's dev go: the
   pooled arm's 07-12 centre offset against the market, in bands, by tercile (§8). This tests whether pooling moves
   the warm offset.
7. **Fetch phases run directly** (network-bound light work, master 2026-11-01), under these conditions:
   - IEM requests are serial with 5 s spacing.
   - Each script's sha256 is recorded before it runs.
   - The process stops itself if its RSS exceeds 1 GB, if free space falls below the 8 GB floor, or on runaway
     errors (§4).
   - Every long run's PID goes to the coordinator.
   - Build and LOYO run only via `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy -Queue`.

**X36 note.** X36 (R-M) closed centre shifts on NBM-anchored arms; its reopen route is "a new training corpus shows
a fitted per-market shift beyond ±1 °F". The build output reports the pooled corpus's fitted 2021-25 centre shift
descriptively (§6, D-x). It is never a gate and never a model change.

## 1. Arms (one candidate)

The model code is identical in every arm. Each arm calls `weather.calibration.pooled_residual_model.fit_pooled(train,
market_id=False, doy=True, raw_columns=False)`, `MeanModel.predict` and `predictive_distribution` on master's
B-bound module, unedited. That is P3d_N_fix's form: R-A's `_rung_entry(simple=False)` with no extra columns.

| Arm | Training rows per (hour, held-out year) | Role |
| --- | --- | --- |
| `P3d_N_11m` | R-A's rows for the 11 markets, years ≠ Y | base |
| `P3d_N_pool` | the same rows plus the 300 pool stations' rows, years ≠ Y | **candidate (gating)** |
| `P3d_N_pool100` | the same rows plus the first 100 pool survivors (§3 order), years ≠ Y | descriptive only |

**The 11 markets' rows are R-A's, unchanged.** They come from `dev_training_frame(C:\t\l2\records)` plus
`attach_training_nbm` with L9's PIT NBM corpus `C:\t\l9\nbm_corpus\nbm_pit_corpus_rows.jsonl` (sha256
`1ae4bf52a0e032fc0c05ddfa7b282a17db53bd9a2e3f3a32a9a5686139faa1fd`), restricted to hours 07..12. Only the pool rows
are new. This change from the S0 draft (which had the 11 on a METAR path) keeps the base an exact reproduction of a
frozen artifact (control C-0) and of P3d_N_fix's training path. The METAR-vs-WU path difference on the 11 is
measured instead (C-a).

## 2. Population and season

- **Season:** P3d_N_fix trains and is served on Aug-Sep, so the pool covers only Aug-Sep. Target dates are
  2021-25 Aug 01..Sep 29 (300 dates), the R-A population. S0's 675-date plan (with Oct-Dec) is narrowed to these 300.
- **Hours:** local cutoff hours 07..12.
- **Scoring:** **the 11 markets only**, on R-A's rows, labels and bucket spaces. Pool rows never enter a score.

## 3. Station filter and selection (frozen; outcome-free)

- **Universe:** the 1,365 ex-Gulf candidates in `s0_candidate_ids.txt` (sha256 recorded in the build receipt), minus
  the 11 market stations, which leaves **1,354**.
- **Order:** sorted by `sha256("L48-station-pool-v1|" + ICAO)` as lowercase hex, ascending.
- **IEM fetch per station and year 2021..2025:**
  - one `report_type=3` and one `report_type=4` request, made with `weather.sources.metar_history.MetarClient.fetch`;
  - date span Aug 01..Sep 30, with `include_metar_text=True`;
  - layout `<root>/<icao>/{routine,special}/<year>.csv`.
- **Filter window:** local dates Aug 01..Sep 29 of 2021-25 (300 days). That replaces the draft's Aug-Dec, which
  had 765 days. A station survives only if all of F1..F5 hold:

| ID | Criterion | Threshold |
| --- | --- | --- |
| F1 | A routine file with at least one report in each of the 5 years | all 5 |
| F2 | Share of routine reports with a temperature whose raw text carries a T-group `T[01]ddd[01]ddd` | ≥ 0.95 over the window, and ≥ 0.90 in each year |
| F3 | Share of local days that are label-complete. Routine reports with a temperature (presence only), at least 18 per day, no gap over 180 min counting local midnight to the first report and the last report to the next midnight | ≥ 0.90 of the 300 days, and ≥ 0.80 in each year |
| F4 | Mean special reports per local day | ≤ 20 |
| F5 | Share of routine reports at the single modal minute | ≥ 0.80 |

- **What the filter reads:** timestamps, report counts, T-group presence and temperature presence only. **No
  temperature value, label, daily maximum or price.**
- **Stopping:** fetch in order, filter each station as it completes, and stop at **300 survivors**. The first 100
  survivors are the descriptive dose subset. Every fetched station is logged with its F1..F5 values and verdict.
- **Retries and exhaustion:** no station is refetched or re-tested under another threshold. A station gets at most
  3 HTTP retries and then fails F1. If the order is exhausted below 300, the pool is every survivor, and that is
  reported.
- **Not used for selection:** distance to a market, climate, NBM error, label agreement, temperature range, any hand
  choice.
- **The 11 market stations** are fetched the same way, for controls C-a and C-c only. They are not filtered and
  their METAR rows never train.

## 4. Fetch phases (direct, light, network-bound)

- **IEM:** serial, 5 s between requests, receipts appended with URL, report type, bytes, sha256, HTTP status and UTC
  time. Expect about 3,100-3,600 requests if about 75% of stations pass.
- **NBP 07Z, 300 dates:**
  - For each date, `GET` the bulletin `blend.YYYYMMDD/07/text/blend_nbptx.t07z` from `noaa-nbm-grib2-pds` (free,
    official) into a temporary file under the corpus root.
  - Record S3 `Last-Modified`, `ETag`, size and the sha256 of the body.
  - Extract the blocks of the 300 pool survivors and the 11 market stations with L9's header regex, append one JSONL
    record in L9's `nbp_station_blocks.jsonl` shape, then delete the bulletin before the next request.
  - About 9.7 GB is transferred and one bulletin (at most 35 MB) is on disk at a time.
  - The NBP phase starts only after the station set is final.
- **Guards, in process:**
  - RSS is read through the Win32 process memory counters, with a hard stop at 1 GB.
  - `shutil.disk_usage` is checked before each request, with a hard stop below 8 GB free.
  - The run stops after 20 consecutive request failures, or a failure share above 10% after 100 requests.
  - Runs are resumable, and finished keys are skipped.
- **PID** of each long run goes to the coordinator.

## 5. Build (heavy, queued): corpus rows

Built only after both fetch phases complete. For each pool station:

- **Labels (`y`):** the venue rule, through `new_city_corpus.venue_routine_records` and `daily_labels`, with a
  duck-typed station spec (a `dataclasses.replace` of a built-in US F market spec carrying the station's id, ICAO
  and IEM zone):
  - highest routine METAR on the local date, SPECI excluded, T-group tenths with a body fallback, half-up to whole
    °F;
  - only `label_complete` days (180-minute rule, inside the input span) are kept;
  - dates are limited to Aug 01..Sep 29.
- **`F` and `x_high_so_far`:** the running maximum over **every** report (routine and special, after
  `select_reports` corrections), with valid time in [local midnight, cutoff instant]. The venue value (T-group
  tenths, body fallback) is converted to whole °F by `pooled_residual_model.wu_whole_f(·, "half_up")`. That is the
  same conversion P3d_N_fix applies to METAR at serve (`rung_inputs`).
- **`x_current_temp`:** the latest such report at or before the cutoff, same conversion.
- **Dropped rows:** a row with no report before its cutoff is dropped.
- **`fh`:** `ols_floor_ladder.nbm_at_cutoff` on the pool NBM corpus. The pool NBM corpus is L9's row format, built
  with the canonical parser v2 and the station's IEM zone injected in-process into
  `NBM_NBP_STATION_TIMEZONES`; the module file is never edited. A row with no available NBM at its cutoff is
  **dropped**, not imputed, and the count is reported.
- **Other columns:**
  - `centre = nearest_centre(date)`, `season = "aug_sep"`, `year`, `hour`, `target_date`;
  - `lat`, `lon` and `elev` (metres) from the IEM network metadata;
  - `doy_sin` and `doy_cos` as in `dev_emit_n`;
  - `market` is the ICAO.
- **Publish:** rows go to `corpora/<sha256 of rows.jsonl.gz>/` with `manifest.json`. The manifest holds input
  shas, the per-station counts and this rule's sha.

## 6. Controls (computed and reported before any candidate statistic)

- **C-0 (gating): positive control.** `P3d_N_11m` must reproduce R-A's `C:\t\l2\rung0712\emit\loyo_rows.jsonl`
  `P3d_N_fix_brier` to 1e-9 on every (hour, market, date) row, with identical key sets. Otherwise the rung is
  refused.
- **C-b (gating): zero-pool identity.** The pool arm's code path with an empty pool frame gives Brier values
  identical to `P3d_N_11m` on the fold (hour 07, held-out year 2021).
- **C-d (gating plus descriptive): extractor and versions.**
  - **Gating:** every extracted market block's sha256 must equal L9's `block_sha256` for the same (market, date).
    Any mismatch refuses the build.
  - **Descriptive, per NBM version:** the pool parse rate, the share of pool rows dropped for no NBM, and the mean
    of `y − fh` at h07 with its spread, for pool stations and for the 11.
- **C-a (descriptive): METAR path vs WU path on the 11.** For 2021-25 Aug-Sep h07..12, compare the 11 markets'
  METAR-built `F` (the §5 rule) with R-A's records `F`: exact-match share, mean and SD of the difference, by hour.
- **C-c (descriptive): label agreement.** For the 11 markets' 2021-25 Aug-Sep days, compare the METAR venue label
  with the WU label in R-A's rows: agreement share and mean difference.
- **D-x (descriptive, X36): fitted centre shift.**
  - Per pool station: the full-data in-sample bias `mean(y − fh)` over 2021-25, as a distribution, and the share
    of stations beyond ±1 °F.
  - Per market of the 11: the mean held-out residual `y − ŷ` at 07-12 under `P3d_N_11m` and under `P3d_N_pool`,
    and their difference.
- **Coverage:** stations, station-days and rows per year and hour, and the pool-to-base row ratio.

## 7. LOYO gate (row 109; kill only)

- **Folds:** blocked leave-one-year-out over 2021-25, per local hour 07..12. Each fold drops the held-out year Y
  from **every** station's rows.
- **Pool-arm folds:** each pool arm's training frame is concatenated with the base frame, so the base rows are
  byte-identical in every arm.
- **Prediction:** each arm predicts the 11 markets' year-Y rows. Brier and log loss use R-A's bucket spaces and
  `p_clim`, through `feature_model.brier_score` and `log_loss`.
- **Statistic:** d = Brier(`P3d_N_pool`) − Brier(`P3d_N_11m`), pooled over h07..h12 as the mean per row. Rows are
  summed within date and divided by the row count.
- **Intervals:**
  - date-clustered percentile bootstrap, 2,000 draws, seed 20261024;
  - block-3 interval: moving blocks of 3 consecutive target dates within a year, resampled with replacement to the
    same date count, 2,000 draws, same seed.
  - The **wider** of the two upper bounds decides.
- **KILL** if any of the following holds:
  1. the point estimate is ≥ −0.0005;
  2. the wider 95% upper bound is ≥ 0;
  3. any of the 11 markets is CI-worse (its date-clustered 95% lower bound > 0);
  4. more than one of the five held-out years has a year mean d > 0.
- **PASS** of gate 1 if none holds. A PASS licenses nothing beyond asking master for the dev go.
- **Reported, never gating:**
  - 07-12 log loss;
  - per hour, per market and per year (that is, per NBM version) tables;
  - 13-16 is not run;
  - `P3d_N_pool100 − P3d_N_11m` with its intervals.
- **Report:** the LOYO verdict goes to the coordinator. **No dev read before master's go.**

## 8. Dev stage (row 109; only after master's dev go; frozen now, not run)

- **Gate 2:** dev 07-12 dR of `P3d_N_pool` against P3d_N_fix. The population is R-F's: scorecard folds 2026-08-01..09-29,
  scored 08-15..09-29.
  - Capture-time inputs as in R-A's `dev_emit_rung`: METAR running max with WU whole °F, captured NBM mean, latest
    replay snapshot at or before capture.
  - The model is fitted on all of Aug-Sep 2021-25 with the pool.
  - KILL unless the upper 95% bound of dR is below 0 (date-clustered and crossed both reported; the wider decides).
- **Then** walk-forward w against the market vs placebo and floor-only (method rule 4), under its own clarification.
- **Descriptive (ruling 6):** the pooled arm's 07-12 centre offset against the market, in bands.
  - The offset is the predictive mean minus the market-implied mean, both in bucket units.
  - It is reported by tercile of the market-implied mean within market, with `P3d_N_fix`'s offset beside it.

## 9. Futility and order

The order is fetch, then controls C-0, C-b and C-d, then LOYO, then the verdict to the coordinator, then (only on a
go) dev. Each tier kills before the next. No interim look produces a PASS. A KILL is final for this rule, and the
artifacts are archived under `C:\archive\ruled-out\station-pool-n300\` with SHA256SUMS, a README and an INDEX.md line.
