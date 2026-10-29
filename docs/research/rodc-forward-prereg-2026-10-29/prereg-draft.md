# R-ODC forward pre-registration: DRAFT, NOT FROZEN

Status: draft (L8, 2026-10-29), with master's rulings (a)-(d) of 2026-10-29 applied. Nothing here is frozen.

- No date after 2026-09-29 has been read for it: no snapshot, no label, no outcome.
- It freezes only as a later commit that says FROZEN, dated 2026-10-30 or later, together with its ledger row.

Lineage:

- Ledger row 69: G2 history gate PASS.
- Ledger row 70: the PROXY retro gate PASS, on IEM ASOS archive features.
- Both are selection-contaminated history evidence on Oct-Dec 2021-25 07-12. This forward test is the first clean
  evidence.

**Disclosure: Denver.** This test excludes Denver from P1 and P2, as test B does (DL 10-23, KDEN vs KBKF). The dev
rows of ledger rows 69 and 70 included Denver. The power table below is recomputed without it, from the row 70 dev
rows (dev only).

## 0. Power first

The power table comes from the row 70 dev rows, Denver excluded. Source:

- rows `C:/t/l16odc/proxy/gate2_proxy_rows.csv.gz`, sha256 `b2056ed6ccb772d7441d029d60d6b7dffb933f8e11a0d100ae70f4935bff2847`;
- script `C:/t/l16odc/power/power_nodenver.py`, sha256
  `365ddc691e854789c9ddf3a7a77e72571ac1974762e079992c579bae96968a1f` (it is `power.py`, sha256 `e32a71ac…`, plus a
  Denver filter and an assert);
- output `power_nodenver.json`, sha256 `0f662c368c5b681b8a9406180c607c852b3b610a13e07c1e5c730fc86a537916`;
- power columns by `pw_table.py`, sha256 `387fbb4a66359cae48e9b56cab8db62454ec2fc616e7c54a6fc0d2816d5a9d76`
  (normal approximation on the bootstrap SE, two-sided 95% bound).

Method:

- Cells are (date, market), each the mean over h07-12, as in the gate.
- dR(NEST vs G1) is computed per bootstrap draw by resampling n whole dates, 4,000 draws, seed 20261027.
- The table uses the Nov-Dec subset (230 dates; estimate −0.00116), because the forward window is Nov-Dec.
- Without Denver, the Oct-Dec estimate is −0.00095 and the n = 375 half-width 0.00064 (with Denver: −0.00102,
  0.00060). The SEs rise by about 5-8%; the NI power at 45 dates falls from 0.83 to 0.78.

| Forward dates n | SE | 95% half-width | MDE80 (2.8·SE) | Superiority power at the dev effect (−0.001) | NI power, m = +0.0015: true −0.001 / true 0 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 30 | 0.00114 | 0.00222 | 0.00319 | 0.14 | 0.59 / 0.26 |
| 45 | 0.00091 | 0.00180 | 0.00256 | 0.19 | 0.78 / 0.37 |
| 60 | 0.00079 | 0.00156 | 0.00223 | 0.24 | 0.88 / 0.47 |
| 75 | 0.00072 | 0.00140 | 0.00201 | 0.28 | 0.94 / 0.55 |
| 90 | 0.00067 | 0.00133 | 0.00186 | 0.32 | 0.96 / 0.62 |
| 120 | 0.00058 | 0.00113 | 0.00162 | 0.41 | 0.99 / 0.74 |
| 150 | 0.00051 | 0.00101 | 0.00144 | 0.50 | 1.00 / 0.83 |
| 225 | 0.00042 | 0.00084 | 0.00118 | 0.66 | 1.00 / 0.94 |

How to read it:

- **Superiority is undecidable in one season.** Even 225 dates give only 0.66 power. So superiority is reported
  only (section 3) and is never a gate.
- **Non-inferiority is decidable at about 45 dates** (0.78 if the dev effect holds).
- **The table is optimistic.** It resamples dates across five seasons. One contiguous forward season has
  correlated weather and fewer distinct regimes, so the forward SE is likely larger.
- **Assumption:** forward cells per date are close to dev (10 markets × 6 hours without Denver). Fewer markets per
  date (missing captures) also widens the SE.

## 1. P1 (primary): serve parity

P1 needs no labels, but it reads forward snapshots and WU rows, so it is a look (section 4).

- **Markets:** the dev markets without Denver.
- **On each forward date** D, market and h07-12, compute:
  - **serve:** `odc_metar_features.odc_features` on the captured snapshot chosen by `choose_snapshot` with the
    state's late-report rule `last_in_hour`;
  - **research:** the training construction on the WU history (below). That is the rows with local_date == D
    and minute_of_day ≤ h·60; low = the min of temp_native; dew = the dewpoint_native of the latest row.
- **WU source (ruling b).** The capture host's existing daily-refresh WU history, `weather.sources.wu_history`. It
  is free and approved.
  - The store is `WundergroundHistoryStore` exactly as `daily_refresh_source_steps._store_for_wu_restore(spec)`
    builds it, with `spec = market_registry.spec_for_id(market)`. Its root is `spec.data_root`, which is built by
    `weather.paths.data_path()`. No data path is written by hand; the scorer's `wu_store(market)` is the only
    constructor.
  - Reading it for any date after 2026-09-29 before the look is a label read, under the embargo.
  - At the look, master exports the forward dates' rows from the capture host to the workstation.
  - Any missing (market, date) day is backfilled with the same `PublicWundergroundHistoryClient`.
  - **Gap limit, pre-set:** if more than 5% of the required (market, date) WU days are still missing after the
    backfill, the test is VOID (`rodc_forward_scorer.WU_GAP_VOID`).
- **Dev reference:** the 2026-08-01..08-10 sample (L8, `par.py` part b), 575 compared rows:
  - low_so_far: 563/575 exact (97.9%, Wilson 95% lower bound 96.4%), max |diff| 1 °F;
  - dewpoint: 573/575 exact (99.7%, Wilson lower 98.7%), max |diff| 4 °F, from one receipt lag;
  - for reference, the served high_so_far: 564/575.
- **Pre-set limits.** Each is set below the dev Wilson lower bound to allow for a winter regime shift (more frequent
  SPECIs, a different receipt lag):

  | Column | Exact-match rate | Max \|diff\| | Rows with \|diff\| ≥ 2 °F |
  | --- | --- | --- | --- |
  | low_so_far | ≥ 95% | ≤ 2 °F | ≤ 1% |
  | dewpoint | ≥ 97% | ≤ 5 °F | ≤ 1% |

- **Mismatches and refusals:**
  - A `check_bounds` refusal on a serve hour counts as a mismatch in the ≥ 2 °F bucket. The hour's own bounds are
    checked, and its running minimum against the previous scored hour.
  - A value on one side and None on the other counts the same way. Both None is a match. Neither enters max |diff|.
- **Exclusions:** a row with no snapshot in the hour, no kept METAR row, or no WU row is excluded and counted. If
  more than 10% of P1 rows are excluded, P1 is VOID.

## 2. P2 (primary): non-inferiority on dR

- **Arms:** NEST = G2, frozen, fitted on all of 2021-25, with low_so_far and dewpoint from `odc_metar_features`.
  It is scored against G1, frozen and fitted on all of 2021-25. Both run in the frozen blend_l6_H, on the same
  forward captured inputs, at h07-12 on the dev markets without Denver.
- **Statistic:** dR as in rule_rodc §4. Cells are (date, market); date-clustered multinomial weights, 2,000 draws,
  seed 20261027. The scorer reproduces the gate's `rz_hrrr_spread._cell_ratio` through
  `r0_ols_floor_challenger._date_weights` and `dev_scorecard.ratio_interval`.
- **Pass:** the upper 95% bound of dR(NEST vs G1) < **m = +0.0015** (ruling d).
- **Derivation of m.** m is the largest forward cost of the serve-built features that is still negligible. Take it as
  the dev gain plus its own sampling width:
  - With Denver: |dR_dev| + half-width_dev = 0.00102 + 0.00060 = 0.00162.
  - Without Denver: 0.00095 + 0.00064 = 0.00159.
  - Both round down to **m = +0.0015**.
  - Read plainly, P2 rules out that the serve-built columns cost more than the whole plausible range of their dev
    benefit.
  - At 45 dates the power is 0.78 if the dev effect holds, and 0.37 if the true effect is 0.
- **Forward frame, flagged.** P2 needs per-row Brier for NEST and G1 on forward dates. Building it needs the G1
  inputs forward: NBM mean, HRRR columns, L6 nowcasts, high_so_far and current_temp. The history path
  (`cool_season_audit.record_rows` on L2 records) refuses dates outside 2021-25. The scorer takes the frame from
  its caller, and the forward frame builder is still to be written, at or before the look and without reading any
  forward label before it.

## 3. Secondary, reported only

- Superiority (upper bound < 0).
- Each hour, each market, and the primary 5 without Denver.
- NEST vs COMP and vs MG-1.
- The P1 mismatch breakdown by market and hour.

None of these gates anything, and none can rescue a failed primary.

## 4. Embargo, timing and the B overlap

- **Embargo:** no snapshot, label or outcome after 2026-09-29 is read before the look.
- **P1 is also a look.** Post-freeze snapshots and WU rows are read only at the look, together with P2.
- **D0** is the freeze date or later, strictly forward. Captured-but-unread days before the freeze do not count.
- **The look** comes after the B look receipt, and no earlier than 2026-12-14.
- **One fixed-sample look.** No interim look and no re-estimation of N.
- **Scored dates** are [D0, look date). A freeze on 10-30 gives D0 = 10-30 and 45 dates to 12-13, with the look on
  12-14 or later. Each day the freeze slips costs a date unless the look moves later.
- **Overlap with B (ruling a): allowed.** The forward dates overlap test B's 45 dates. R-ODC's dates and results
  are never pooled with B. Its look comes after the B look receipt. Nothing from it feeds B or MG-2.
- **Enforced in code:** `rodc_forward_scorer.check_look` refuses every read and verdict unless the freeze is
  ≥ 2026-10-30, D0 ≥ the freeze, the look ≥ 2026-12-14 and ≥ the B receipt date, today ≥ the look, every date is in
  [D0, look), and no Denver row is present.

## 5. Outcomes

| P1 | P2 | Verdict |
| --- | --- | --- |
| PASS | PASS | R-ODC becomes an **adoption candidate** for the next model release. This is not a promotion; the release and readiness gates still apply. |
| FAIL | any | R-ODC closes as serve-infeasible. The research columns cannot be reproduced at serve time. |
| PASS | FAIL (upper bound ≥ m) | R-ODC closes: the gain does not survive serve-built features forward. |
| VOID | any | No verdict. The dates are spent. |

A WU gap above 5% makes P1 VOID, and so the test.

## 6. Pinned items 1-8 (the serve construction) and the scorer

1. **Source:** captured `sources.metar.data` rows only. No WU-current or station fallback.
2. **Instant:** `observed_running_max.metar_observation_local_time` (obsTime, else raw DDHHMMZ), else the row's
   `obs_time`. Undated rows are skipped.
   - A row is kept if it is on local date D, at or before h:00, and at or before the snapshot capture time.
3. **Snapshot:** the state's late-report rule (`last_in_hour`) through `choose_snapshot`. `as_of_capture` is
   reported as a secondary only.
4. **Values:** low_so_far = `wu_whole_f`(the min plausible temp_native, half_up). dewpoint = `wu_whole_f`(the
   dewpoint_native of the latest kept row, half_up).
   - Here `wu_whole_f` is `mg_serve_core.wu_whole_f`, the serve T-group conversion.
   - The unit is native °F whole degrees. The legacy name dewpoint_c does not mean Celsius.
5. **Missing values:**
   - dewpoint is None when the latest kept row lacks one. There is no fallback.
   - No kept row means the row is excluded and counted, like high_so_far.
6. **Refusals:** `check_bounds`: the running min never increases, low ≤ current, and low ≤ high.
7. **The train/serve split is accepted and measured.** The model stays trained on the WU-print columns (rows 69/70).
   P1 measures the split forward, and P2 bounds its cost.
8. **Code:** the pure, unbound module `src/weather/calibration/odc_metar_features.py` on
   `claude/rodc-odc-metar-features-20261029` @ `0e11b018fda76125425c8ebdd21560ee10289d70`, git blob
   `1cc4d565468bf4959137a8f6f6cec5b10adfce24`, sha256
   `dd53e81ebbf8851673d01f138296fb56a91ce898e53c0541d67226e64dd981d1`. It stays unlanded, pinned by blob.

**Scorer:** `src/weather/calibration/rodc_forward_scorer.py` on `claude/rodc-forward-scorer-20261029` @
`4ed7fd7b4ac119a982afa02f4923e537191a9ede` (stacked on 0e11b018f), git blob
`ee3430956ee7df4edc15f364857eb4ae968868b9`, sha256
`0d6e66a6725f70be3594abb96b61a359250817b30c0927cb514c5ef40d7d1a54`. Tests: `tests/calibration/test_rodc_forward_scorer.py`,
blob `09c606eae0f2d6d119a3e0b470c81e3bbe759582`; with the module's tests, 26 passed through the workstation queue.

- Neither file is in RELEASE_FILES, and no serve path imports them.
- The constants are pinned in the scorer: `MARGIN`, `P1_LIMITS`, `P1_EXCLUDED_VOID`, `WU_GAP_VOID`, `SEED`, `DRAWS`,
  `HOURS`, `EXCLUDED_MARKETS`, `FREEZE_EARLIEST`, `LOOK_EARLIEST`.

## 7. Rulings applied (master, 2026-10-29)

- **(a)** The overlap with B's dates is allowed: never pooled, disclosed here, the look after the B receipt, and
  nothing feeds B or MG-2 (section 4).
- **(b)** The P1 WU source is the daily-refresh WU history store, with a 5% gap limit (section 1).
- **(c)** Denver is excluded from P1 and P2. The power table is recomputed without it (section 0).
- **(d)** m = +0.0015 (section 2).
- **Multiplicity.** This is the 3rd R-ODC test on the hypothesis, after rows 69 and 70, and the first on fresh
  dates. It is disclosed in a new ledger row at the freeze.
