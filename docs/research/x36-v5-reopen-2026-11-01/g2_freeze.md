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
