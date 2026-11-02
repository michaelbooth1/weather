# G2 freeze and dev plan (K row 112, lane L47), written before any dev row is opened

- Rule: `rule_x36_trailing_final.md`, sha256 `032c8dc3bf33fd7dc549a5a9e93ed04d86809678a087fc43766e272b99f077f2`.
- Module: `tools/research/x36_v5_reopen/x36_trailing_g2.py`, sha256
  `022565ccceba52eed4b617ca031425a81f40dd9d373b08a64ee751dae9e55679`. It is the selection script and the dev
  module. G1 (`7b14c319…`) is imported read-only after a sha check.
- Freeze table: `g2_freeze_table.json`, sha256 `eb73fc04ab20d7b0410633e3d159b069aa14ab4a8f36c5b76db0750fac79fc37`.
  - Written by `freeze` through `workstation_heavy.ps1 -Queue` (v4 launcher, launcher PID 40492).
  - Inputs touched: 2021-25 only (L9 corpus `1ae4bf52…`, G1 dseries `387c1a50…`, trainer records).

## Freeze (master ruling: G1's inner-selection algorithm on all five years)

For each year Y, the model is fit on the other four years. It then predicts Y's gate rows (Aug 15..Sep 29), using
nested b_train from the four fit years. The five out-of-fold sets are pooled per hour, and each hour's pick is
made in three steps:

1. Score every combo with the tabulated kernel.
2. Re-score the best 3, plus λ = 0, exactly. The table error stays at or below 1.2e-9 per row; the limit is 1e-6.
3. Pick the lowest score with `g1.pick`.

| hour | W | λ | rows | summed Brier λ=0 | summed Brier pick |
| --- | ---: | ---: | ---: | ---: | ---: |
| h07 | 7 | 0.5 | 2505 | 2170.837 | 2160.502 |
| h08 | 14 | 0.5 | 2505 | 2162.321 | 2152.981 |
| h09 | 7 | 0.25 | 2506 | 2153.752 | 2146.399 |
| h10 | 14 | 0.25 | 2507 | 2142.100 | 2136.186 |
| h11 | 7 | 0.25 | 2507 | 2109.042 | 2103.335 |
| h12 | 14 | 0.25 | 2507 | 2053.649 | 2050.560 |

- **Tie-break.** The rule's tie-break applies: the smaller λ, then the smaller W, for scores within 1e-12. It was
  never needed, because no hour had a tie at its minimum.
- **2026 b_train(m).** This is the mean of d over Aug 1..Sep 29 of all five years. The values are recorded in the
  table under `b_train_2026`.

## Dev plan (date ranges stated before opening anything)

- **Market data.** Prices come from `C:\swarm\v3layout`, file `market.parquet`, field `p_market_yes` per band
  (schema `harness_v3_layout/1`, built 2026-10-19). The layout covers 2026-08-01..09-29 and is loaded through
  `dev_scorecard_data.load_layout`. Scoring covers target dates 2026-08-15..09-29 only, in 7-day folds from 08-15,
  hours 07-12.
- **Dev outcome labels.** These come from the same layout's `labels.parquet`, 2026-08-01..09-29.
- **2026 trailing d.** This is NBP 07Z mean − WU high.
  - NBP comes from `C:\t\l3\analogue\nbm2026\corpus\nbm_pit_corpus_rows.jsonl` (sha256 `85746b7a…`, which matches
    its manifest `corpus_id`).
  - WU labels come from `data/wunderground/<station>/daily/daily_summary.csv`.
  - Only target dates 2026-07-31..09-28 are used. Corpus lines outside that range are dropped on their date text
    before they are parsed. Labels are filtered by date before any value is read.
  - The sealed panel (07-30 or earlier) is never used.
- **Model inputs.** The dev P3d_N_fix inputs are re-emitted by the R-A dev-emit loop, using the replay snapshot at
  or before each layout row's capture. They use only the replay folders for target dates 08-15..09-29, from
  `data/inbox/replay-inputs-le0929`. Nothing on or after 2026-09-30 is read, and the module refuses such rows.
- **Positive control (STOP on failure).** The re-emitted BASE must reproduce R-A's
  `C:\t\l2\rung0712\emit\dev_P3d_N_fix.jsonl` (sha256 `cd0034b9…`) to 1e-9 on the same keys (target dates
  08-15..09-29). Lines dated before 08-15 are skipped on their date text.
- **Kill.** The test statistic is dR = R(P3d_T) − R(P3d_N_fix), where R = Brier_model / Brier_market. It is taken
  over pool ALL, scope covered (snapshots covered by both arms), group 07-12. The interval is a date-clustered 95%
  interval (2000 draws, seed 20261024, as row 112).
  - **PASS only if the upper bound is below 0.**
  - The MDE (80%, from the same bootstrap) is disclosed.
  - The unchanged `dev_score` is run on the same files as a cross-check. It uses its own seed, 20260921, and its
    point estimate must agree.
- **Rows with fewer than W prior dates.** These get shift 0 and are counted.
- **Descriptive only.** Two summaries are reported next to the verdict:
  - R vs market at 07-12 (and per hour) for P3d_T and P3d_N_fix.
  - The remaining centre offset vs market for both arms, in bands, by tercile of the applied shift. The offset is
    the probability-weighted mean band index of the arm minus that of the market.
- **Order.** The `dseries26` (light) and `dev` (queued) steps run only after the coordinator's go.

## DISCLOSURE: the label lag the correction assumes (train/serve parity; not a variant, the module is unchanged)

### (a) What the code does

- **Where the window is built.** `b_recent(m, t; W)` comes from `x36_trailing_g1.b_recent`, which is used unchanged
  by G1, the freeze and G2. It averages d over the market's W latest target dates strictly before t.
- **No time gate.** The window carries no hour or instant check. The cutoff hour enters only the model inputs
  (high_so_far and current_temp at h:00).
- **The D-1 label is in the window at every hour 07-12.** This holds for h07, h08, h09, h10, h11 and h12 alike, so
  the D-1 WU label is treated as usable from 07:00 local on D, and in fact from the start of D.
- **The same assumption runs through every gate:**
  - G1 LOYO and the freeze use the 2021-25 L9 dseries.
  - G2 uses the 2026 dseries26.
- **The NBP side of d(D-1) is not a concern.** It is the 07Z NBP mean for D-1, issued about 08:30Z on D-1 (corpus
  `last_modified`), so it exists long before D.

### (b) Production source and when the D-1 label exists

**Before 2026-10-23: the WU daily history.** This covers the entire training era and the whole 2026 dev window.

- **Source.** `docs/operations/AGENT_CONTEXT.md` (§Settlement and units) and
  `src/weather/backtesting/venue_label_reader.py` (docstring, policy `wu_history`).
- **The serving process cannot fetch it.** `ModelSources.fetch_wu_history` calls
  `paid_weather_provider_disabled("wu_history", …)` (`src/weather/model/model_sources.py:1221`).
- **Production WU history fetching is off.** It stays off until the token-redaction change lands
  (`AGENT_CONTEXT.md` §Paid sources, OD24).
- **The settled label enters local state only through the Stage-A settlement chain.** The chain runs 09:30–11:55
  host local (`docs/operations/HOST_LOAD_POLICY.md`, timetable row "09:30–11:55 Stage A"), and the finalize step
  is in `docs/operations/venue-rule-labels.md` §4.
- **Earliest time relative to 07:00 local on D.** The label exists no earlier than 09:30 host local on D, and may
  arrive as late as 11:55. The host clock is assumed to be US Eastern (UTC−05:00 on 2026-11-01); I did not
  verify this. Under that assumption, 09:30 ET is:

  | Markets | Local time at 09:30 ET | Hours 07-12 without the label |
  | --- | --- | --- |
  | Eastern (atlanta, miami, nyc) | 09:30 | 07, 08, 09 at least |
  | Central (austin, chicago, dallas, houston) | 08:30 | 07, 08 |
  | Mountain (denver) | 07:30 | 07 |
  | Pacific (los-angeles, san-francisco, seattle) | 06:30 | none at the start time |

  The chain may run until 11:55 ET, so later hours are not guaranteed for any market. Whenever the chain is late or
  fails, no market has the label at any hour.

**From 2026-10-23: the routine-METAR maximum (SPECI excluded).**

- **Source.** `AGENT_CONTEXT.md` §Settlement and units, `docs/operations/venue-rule-labels.md` (report filter row)
  and `src/weather/backtesting/venue_rule_labels.py` (`metar_routine`).
- **Live computation.** D-1's last routine METAR is about 23:5x local on D-1. The repo's convention is that a
  captured METAR row is usable from observation + 10 min (`src/weather/calibration/mg2_composite.py:783`, and
  `r0_ols_floor_challenger.routine_dmax`, which needs at least 20 routine rows). On that basis the D-1 routine
  maximum can be computed from captured METAR by about 00:10 local on D. That is well before 07:00, at every
  hour 07-12.
- **The official venue-rule CSV is built later.** It is built inside Stage A from METAR fetched outside it
  (`venue-rule-labels.md` §4), so a serve path that reads the CSV inherits the Stage-A timing above.

### Finding for the checkpoint

**The code assumes the D-1 label at 07:00 local, for every hour.** It is evaluated (G1, freeze, and G2 2026-08..09)
entirely on WU-history labels, and production could not have those at 07:00. At best they arrive after Stage A
(09:30–11:55 host local); live WU fetch is disabled.

**Two serve options give parity:**

1. Use a captured routine-METAR D-1 max as d's label. That is the venue label itself from 10-23, but for pre-10-23
   dates it is a proxy that differs from the WU high on a few percent of days (`venue_label_reader.py`
   docstring).
2. Lag the window by one more day (labels ≤ D-2) at the hours before Stage A finishes.

Neither is what G1 or G2 measured. A G2 PASS would therefore not transfer to serve unchanged, and this lag
mismatch must be closed before any L6 / MG-2 comparison. The module is deliberately left unchanged (master
ruling).

## Clarification 1 (2026-11-01), before any dev row: departures, G2-P, routine-METAR coverage, wider CI, three-way verdict

Docs only, added below the frozen text, which stays as it was. Written after master's independent leak review of
`x36_trailing_g1.py` @ `f1ca94f0a` found no leak. Its non-fatal concerns are answered here. No dev row has been
opened.

The code for G2-P and the moving-block bootstrap is in the adjacent commit
`20e5dd1ab06c1302785b790fb4303dbeec955c14`:
- a new module `tools/research/x36_v5_reopen/x36_trailing_g2p.py`, sha256
  `ee9e2eec1d532fe194c70e532336c95a2a7568dee49d432c108777d71262c291`;
- its tests `tests/calibration/test_x36_trailing_g2p.py`, sha256
  `99d6bc95310a63587991612f07255997db84e90def471ba39f0ff30e2ba7dfdb`.

`x36_trailing_g2.py` is unchanged (`022565cc…`). The bootstrap could not go into it, because any edit changes its
sha256. `load_freeze` binds the freeze table to the sha of the module that wrote it (`x36_trailing_g2.py:120`), so
G2's `dev` would then refuse the table.

### C1.1 Departures from the rule text (`rule_x36_trailing_final.md`, sha256 `032c8dc3…`)

- **(a) Positive control.** The rule (§G1) names R-K's 07-12 rows. The G1 and G2 modules use R-A instead. G1 uses
  `C:\t\l2\rung0712\emit\loyo_rows.jsonl`; G2 uses `dev_P3d_N_fix.jsonl`, sha256 `cd0034b9…`. The reason is that
  R-K has no 07-12 rows; R-A's rows are the 07-12 reference that R-R, R-S and R-Q reproduced at zero difference.
  Until now this was disclosed only in the G1 module docstring (`x36_trailing_g1.py:19-21`) and in commit
  messages. It is recorded here as a departure from the rule.
- **(b) b_train.** The rule defines b_train as the 2021-25 raw mean of d. It cites the context table of `fit.json`
  `6fe1f123…`. The modules compute it differently:
  - G1 uses the nested d-series mean over the fit years only (`x36_trailing_g1.py:303`, `:323`).
  - G2 uses the five-year d-series mean, frozen in the table's `b_train_2026`.
  - Neither reads the `fit.json` all-years table.
  The module is correct. Read literally, the rule text would have leaked the held year into b_train in G1.
- **(c) Season end.** The modules' season runs Aug 1 to Sep 29 (`x36_trailing_g1.py` `in_season`, `SEASON_LAST`).
  The rule's "Aug-Sep" would include Sep 30, which no run used.
- **DISCLOSURE: cycle mismatch (by design, not a leak).** b_recent is a mean of d built on the NBP 07Z mean, so it
  measures the 07Z-cycle bias. The shift is applied to P3d_N_fix's per-hour centre, which comes from the NBM at
  each hour's own cutoff. Those are different cycles. G1 and G2 measure exactly this design, and serving must
  keep it.

### C1.2 G2 pick (answers the review's "G2 pick undefined")

The G2 pick is already pinned by the freeze table:
- run file sha256 `eb73fc04ab20d7b0410633e3d159b069aa14ab4a8f36c5b76db0750fac79fc37` (CRLF);
- git blob sha256 `383e4a6a1b8f4449e09f046dcff6bef90903df311115623d31b16974cf8ca449` (LF).

It is the all-years inner selection described under "Freeze" above. One W and λ per hour; the table is above. It
was written before any dev row, and G2's `dev` refuses any other table.

### C1.3 Routine-METAR coverage (count first, rule 16), 2026-07-31..09-28

The WS has no complete captured routine METAR for these stations:
- `data/venue_rule_labels/metar` holds only KDEN among US stations, and KDEN is the post-10-23 Denver station.
- `data/research/upstream_obs` mixes routine reports and SPECI with no report-type column.
- `C:\t\L40\s0v2\metar` holds per-snapshot receipt fields, not a report stream.

So a free IEM fetch was made under the coordinator's conditions:
- Script: `C:\t\L47b\g2\metar_s\fetch_count_v1.py`, sha256
  `578c1159b23bc63c71482cce0a15b5bc3a9498aa96f18a534645d8bfbc608db1`, recorded before the run. PID 60060.
- Run time: 2026-11-02 01:40:00Z to 01:41:07Z.
- Requests: serial, 6 s spacing, `report_type=3` only, raw text included.
- Guards, checked before and after each station: RSS under 1 GB, C: at least 8 GB free. No anomaly occurred.
- Window: the UTC request runs from each station's local 07-31 00:00 to local 09-29 12:00. The 09-29 morning
  supplies the venue rule's later report for 09-28. No 07-24..07-30 local report was requested, and the script
  asserts that none arrived.
- Stations: the venue rule resolves every date to the same ICAO as the WU history station, and the registry
  (`config/venue_rule_stations.json`) has no dated override before 10-23. Denver is KBKF.
- Counting: `venue_rule_labels.reports_from_csv` plus `venue_daily_labels`, SPECI excluded.
- Receipts: `C:\t\L47b\g2\metar\receipts.jsonl`, sha256
  `4bd9869fa983f1c6f7073abfae40ddce5094151fd36942e41d4f991c322edb97`. Each receipt holds the URL, size and sha256.
- Table: `coverage.json`, sha256 `fca343ffe1417f5768db5a962e263afde0fc564f660d7c318cdd2aba4c8ba9a5`.

| market | ICAO | days labelled / 60 | days >= 18 routine | days >= 20 routine | min / median routine per day | bytes | raw sha256 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atlanta | KATL | 60 | 60 | 60 | 24 / 24 | 264669 | `41e24949…3002` |
| austin | KAUS | 60 | 60 | 60 | 23 / 24 | 242158 | `857735ed…08a7` |
| chicago | KORD | 60 | 60 | 60 | 24 / 24 | 252243 | `4bdf5d8c…04c8` |
| dallas | KDAL | 60 | 60 | 60 | 24 / 24 | 244677 | `91191710…8bbc` |
| denver | KBKF | 60 | 60 | 60 | 22 / 24 | 249499 | `a688a2da…ca12` |
| houston | KHOU | 60 | 60 | 60 | 24 / 24 | 247020 | `d125fff2…0637` |
| los-angeles | KLAX | 60 | 60 | 60 | 23 / 24 | 245342 | `4db054d8…2f31` |
| miami | KMIA | 60 | 60 | 60 | 23 / 24 | 272081 | `c1c31130…0ed2` |
| nyc | KLGA | 60 | 60 | 60 | 23 / 24 | 262550 | `4a1dbc1a…b34a` |
| san-francisco | KSFO | 60 | 60 | 60 | 24 / 24 | 246433 | `3579f298…98d0` |
| seattle | KSEA | 60 | 60 | 60 | 24 / 24 | 246001 | `18db905a…c1e0` |

Every station is 100% complete at both thresholds: 18 is `settlement_ledger.COMPLETE_DAY_MIN_ROWS`, and 20 is the
r0 `routine_dmax` minimum. No station is below 95%. All reports parsed as routine. The raw files are under
`C:\t\L47b\g2\metar\raw\`, and the full sha256 values are in the receipts.

### C1.4 G2-P (label parity), pre-registered here. It is not a variant.

- Everything is the same as G2 except one input:
  - the same frozen W/λ table (`eb73fc04…`);
  - the same dev rows (07-12, target dates 2026-08-15..09-29, covered scope);
  - the same b_train;
  - the same bootstraps.
- The one change: the 2026 b_recent is rebuilt from d(m, u) = NBP 07Z mean − the venue-rule label. That label is
  the half-up integer of the routine-METAR daily maximum (T-group tenths, SPECI excluded, `native_bucket` of the
  `venue_daily_labels` row). It replaces the WU high. Dates are 2026-07-31..09-28 only, from the files in C1.3,
  each checked against its receipt sha.
- Steps:
  1. `x36_trailing_g2p.py dseries26p` writes a file in G2's `dseries26` schema.
  2. `x36_trailing_g2.py dev --d26 <that file>` runs into a separate output folder, through the same module, the
     same freeze table and the same `-Queue` admission.
  3. `x36_trailing_g2p.py compare` reports:
     - the per-date shift difference (G2-P − G2) on identical row keys;
     - dR_P with its date-clustered 95% interval (2000 draws, seed 20261024; the same bootstrap as G2), plus
       the moving-block interval in C1.5.
- **DISCLOSED MISMATCH, not fixed:** b_train stays as frozen. It is a WU-era mean of d (2021-25 WU labels), while
  G2-P's b_recent uses routine-METAR labels, so a level difference between the two label sources enters the
  clip(b_recent − b_train) term directly.

### C1.5 Wider CI: circular moving-block bootstrap, pre-registered for G2

Overlapping 7- and 14-day windows correlate adjacent dates, so the date-cluster bootstrap understates the interval.
G2 therefore reports a circular moving-block bootstrap next to the date-cluster one. Both apply to the 07-12
covered dR for G2 and G2-P:
- block L = 7 dates, 2000 draws, seed 20261024;
- the distinct dates in calendar order form one circular sequence; ceil(n/7) blocks are drawn and truncated to n
  dates;
- a cell's weight is its date's draw count, and the statistic is the same ratio as G2's.

`x36_trailing_g2p.py mbbdev` rebuilds G2's 07-12 vectors exactly as `score_dev` does. It must reproduce G2's
date-clustered interval to 1e-12 before it reports the moving-block interval. It loads the dev layout, so it runs
through `-Queue` and needs a branch-local allowlist line for `tools.research.x36_v5_reopen.x36_trailing_g2p`. That
line is asked of the coordinator and is not added here.

G1 under the same moving-block bootstrap (training era, descriptive, no dev row). Computed with
`x36_trailing_g2p.py g1mbb` at module `ee9e2eec…` from `g1_rows.jsonl` (gate rows, 15,037). Output
`C:\t\L47b\g2\g1mbb\g1_mbb.json`, sha256 `d32b84da72a4177c50c41bab80875046bbf8a272cef761e280264dc6d9d9c689`. Values
are dBrier (P3d_T − P3d_N_fix, mean per row). The pooled point reproduces G1's −0.0022567548565844 exactly. The
cluster column uses the scorecard's multinomial draw, so it differs slightly from G1's reported
[−0.00378, −0.00079], which came from integer-index draws.

| group | n | dates | point | date-cluster 95% | MBB L=7 95% |
| --- | --- | --- | --- | --- | --- |
| pooled 07-12 | 15037 | 230 | −0.00226 | [−0.00370, −0.00082] | **[−0.00408, −0.00039]** |
| h07 | 2505 | 230 | −0.00310 | [−0.00499, −0.00123] | [−0.00558, −0.00056] |
| h08 | 2505 | 230 | −0.00291 | [−0.00451, −0.00123] | [−0.00513, −0.00061] |
| h09 | 2506 | 230 | −0.00243 | [−0.00379, −0.00111] | [−0.00429, −0.00043] |
| h10 | 2507 | 230 | −0.00209 | [−0.00318, −0.00093] | [−0.00342, −0.00070] |
| h11 | 2507 | 230 | −0.00207 | [−0.00400, −0.00019] | [−0.00433, +0.00018] |
| h12 | 2507 | 230 | −0.00094 | [−0.00351, +0.00161] | [−0.00356, +0.00176] |

| year (NBM version) | n | dates | point | date-cluster 95% | MBB L=7 95% | pooled point without this year |
| --- | --- | --- | --- | --- | --- | --- |
| 2021 (v4.0) | 3036 | 46 | +0.00078 | [−0.00299, +0.00471] | [−0.00299, +0.00472] | −0.00303 |
| 2022 (v4.0) | 3036 | 46 | −0.00591 | [−0.00892, −0.00280] | [−0.00924, −0.00287] | −0.00133 |
| 2023 (v4.1) | 2923 | 46 | −0.00712 | [−0.01024, −0.00390] | [−0.01019, −0.00391] | −0.00108 |
| 2024 (v4.2) | 3036 | 46 | +0.00125 | [−0.00111, +0.00371] | [−0.00222, +0.00518] | −0.00314 |
| 2025 (v4.3) | 3006 | 46 | −0.00044 | [−0.00315, +0.00246] | [−0.00282, +0.00197] | −0.00271 |

Reading, descriptive only:
- The MBB widens the pooled interval by a factor of about 1.28. Its upper bound stays below 0.
- The gain comes from two of the five years: 2022 and 2023 have intervals entirely below 0. 2021 and 2024 have
  positive points, and 2025 is about 0.
- No single year carries the result. Dropping 2022 leaves −0.00133 and dropping 2023 leaves −0.00108, both still
  below the −0.0005 kill line. With both dropped, the remaining three years average about 0.
- NBM versions are per the ledger row 86 note. Dev 2026 runs on NBM v5.0, which is absent from all of these
  years.

### C1.6 Power: the three-way G2 verdict, frozen verbatim (it REPLACES the two-way combined verdict)

The earlier two-way text, recorded for the history and now superseded, read: "K112 passes G2 only if G2's upper
bound is < 0 AND G2-P's point estimate is < 0. If G2 passes and G2-P flips sign → INCONCLUSIVE-PARITY, no serving
proposal."

The verdict now in force:

- **PASS: UB < 0 under BOTH bootstraps AND G2-P point < 0.**
- **CONSISTENT: point < −0.0005 AND G2-P point < 0, with UB not < 0. No serving claim; it proceeds to the
  history-tier test against market prices (L52 atlas, Dec-May).**
- **KILL: point ≥ −0.0005, or G2-P flips sign (the INCONCLUSIVE-PARITY case becomes KILL for serving, and
  archive).**

Implementation (`three_way_verdict`): a G2-P point ≥ 0 is KILL first. Then PASS is tested, then CONSISTENT, else
KILL. One overlap is open: UB < 0 under both bootstraps with −0.0005 ≤ point < 0. The code reads it as PASS, and
the coordinator is asked to confirm.

**Dev MDE80 at 07-12, from known figures, without opening dev:**
- EF §10y puts the MDE80 of the dev 00-12/07-12 dR reads at about 0.005-0.006. That section's 07-12 lever row
  (L4) has MDE80 0.0064, and G2-a has 0.0047.
- Register X22 (NBM 07-12 blend) gives MDE80 0.0038 on R.
- Master's estimate is about 0.005-0.006, consistent with these.
- Projection for the moving-block bootstrap: G1's MBB/cluster width ratio of about 1.28 puts it near 0.0064-0.0077.
  That is about three times G1's training-era point (−0.00226).
- G2's `dev` also discloses its own date-clustered MDE80 (`mde80`, `power_at_-0.0075`) with the result.
- G2 is underpowered for an effect of G1's size, so CONSISTENT is the expected informative outcome, not PASS.

### C1.7 Serving rule, recorded now

"serve must compute d from captured METAR and must never read the Stage-A CSV."
