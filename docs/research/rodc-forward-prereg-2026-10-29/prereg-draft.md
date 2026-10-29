# R-ODC forward pre-registration: DRAFT, NOT FROZEN

Status: draft for master and the owner (L8, 2026-10-29). Nothing here is frozen.

- No date after 2026-09-29 has been read for it: no snapshot, no label, no outcome.
- It freezes only when master and the owner rule, as a later commit that says FROZEN.

Lineage:

- Ledger row 69: G2 history gate PASS.
- Ledger row 70: the PROXY retro gate PASS, on IEM ASOS archive features.
- Both are selection-contaminated history evidence on Oct-Dec 2021-25 07-12. This forward test is the first clean
  evidence.

## 0. Power first

The power table comes from the row 70 dev rows. Source:

- rows `C:/t/l16odc/proxy/gate2_proxy_rows.csv.gz`, sha256 `b2056ed6…`;
- script `C:/t/l16odc/power/power.py`, sha256 `e32a71ac…`.

Method:

- Cells are (date, market), each the mean over h07-12, as in the gate.
- dR(NEST vs G1) is computed per bootstrap draw by resampling n whole dates, 4,000 draws, seed 20261027.
- The table uses the Nov-Dec subset (230 dates; estimate −0.00112), because the forward window is Nov-Dec. The
  Oct-Dec numbers differ by at most 0.00007 in SE.
- At n = 375 the interval half-width is 0.00060, which reproduces row 70's interval (0.00059).

| Forward dates n | SE | 95% half-width | MDE80 (2.8·SE) | Superiority power at the dev effect (−0.001) | NI power, m = +0.0015, true −0.001 / true 0 | NI power, m = +0.0025, true −0.001 / true 0 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 30 | 0.00106 | 0.00209 | 0.00298 | 0.15 | 0.65 / 0.29 | 0.91 / 0.65 |
| 45 | 0.00086 | 0.00169 | 0.00241 | 0.21 | 0.83 / 0.42 | 0.98 / 0.83 |
| 60 | 0.00075 | 0.00147 | 0.00210 | 0.26 | 0.91 / 0.51 | 1.00 / 0.91 |
| 75 | 0.00068 | 0.00134 | 0.00191 | 0.31 | 0.96 / 0.59 | 1.00 / 0.96 |
| 90 | 0.00063 | 0.00125 | 0.00175 | 0.36 | 0.98 / 0.67 | 1.00 / 0.98 |
| 120 | 0.00055 | 0.00106 | 0.00154 | 0.44 | 1.00 / 0.78 | 1.00 / 1.00 |
| 150 | 0.00048 | 0.00094 | 0.00135 | 0.55 | 1.00 / 0.87 | 1.00 / 1.00 |
| 225 | 0.00040 | 0.00078 | 0.00111 | 0.71 | 1.00 / 0.97 | 1.00 / 1.00 |

How to read it:

- **Superiority is undecidable in one season.** Even 225 dates give only 0.71 power. So superiority is reported
  only (section 3) and is never a gate.
- **Non-inferiority is decidable at about 45 dates.**
- **The table is optimistic.** It resamples dates across five seasons. One contiguous forward season has
  correlated weather and fewer distinct regimes, so the forward SE is likely larger.
- **Assumption:** forward cells per date are close to dev (11 markets × 6 hours). Fewer markets per date
  (missing captures) also widens the SE.

## 1. P1 (primary): serve parity

P1 needs no labels.

- **On each forward date** D, market and h07-12, compute:
  - **serve:** `odc_metar_features.odc_features` on the captured snapshot chosen by the state's late-report rule;
  - **research:** the WU history construction on the same date and hour. That is the rows with local_date == D
    and minute_of_day ≤ h·60; low = the min of temp_native; dew = the dewpoint of the latest row.
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

- **Refusals:**
  - A `check_bounds` refusal on a serve row counts as a mismatch.
  - A row with no snapshot, no METAR row or no WU row is excluded and counted. If more than 10% of rows are
    excluded, P1 is VOID.
- **Dependency, flagged.** This workstation's WU history stops at 2026-08 (KATL to 08-10). P1 needs WU hourly
  history for the forward dates, fetched at or after the look and never before. The fetch path and its approval
  must be named before freezing.

## 2. P2 (primary): non-inferiority on dR

- **Arms:** NEST = G2, frozen, fitted on all of 2021-25, with low_so_far and dewpoint from `odc_metar_features`.
  It is scored against G1, frozen and fitted on all of 2021-25. Both run in the frozen blend_l6_H, on the same
  forward captured inputs, at h07-12 on the dev markets.
- **Statistic:** dR as in rule_rodc §4: date-clustered, 2,000 draws, seed 20261027.
- **Pass:** the upper 95% bound of dR(NEST vs G1) < m.
- **Derivation of m.** m is the largest forward cost of the serve-built features that is still negligible. Take it as
  the dev gain plus its own sampling width:
  - |dR_dev| + half-width_dev = 0.00102 + 0.00060 = 0.00162, rounded down to **m = +0.0015**.
  - Read plainly, P2 rules out that the serve-built columns cost more than the whole plausible range of their dev
    benefit.
  - At 45 dates the power is 0.83 if the dev effect holds, and 0.42 if the true effect is 0.
- **Looser alternative, for the owner:** m = +0.0025, which is 10% of the G1-vs-COMP gain (0.0248) that R-ODC rides
  on. Power is 0.98 / 0.83 at 45 dates.
- **Recommendation:** m = +0.0015 with N ≥ 45. If the window must be shorter, use +0.0025 rather than run a test that
  cannot decide.

## 3. Secondary, reported only

- Superiority (upper bound < 0).
- Each hour, each market, and the primary 5.
- NEST vs COMP and vs MG-1.
- The P1 mismatch breakdown by market and hour.

None of these gates anything, and none can rescue a failed primary.

## 4. Embargo and timing

- **Embargo:** no snapshot, label or outcome after 2026-09-29 is read before the look.
- **P1 is also a look.** Post-freeze snapshots are read only at the look, together with P2.
- **D0** is the freeze date or later, strictly forward. Captured-but-unread days before the freeze do not count.
- **The look** comes after the B look receipt, and no earlier than 2026-12-14.
- **One fixed-sample look.** No interim look and no re-estimation of N.
- **Example timing:** a freeze on 10-30 gives D0 = 10-30 and 45 dates to 12-13, with the look on 12-14 or later. Each
  day the freeze slips costs a date unless the look moves later.

## 5. Outcomes

| P1 | P2 | Verdict |
| --- | --- | --- |
| PASS | PASS | R-ODC becomes an **adoption candidate** for the next model release. This is not a promotion; the release and readiness gates still apply. |
| FAIL | any | R-ODC closes as serve-infeasible. The research columns cannot be reproduced at serve time. |
| PASS | FAIL (upper bound ≥ m) | R-ODC closes: the gain does not survive serve-built features forward. |
| VOID | any | No verdict. The dates are spent. |

## 6. Pinned items 1-8 (the serve construction)

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
   `claude/rodc-odc-metar-features-20261029` @ `0e11b018fda76125425c8ebdd21560ee10289d70`, sha256 `dd53e81e…`.
   - It is not in RELEASE_FILES, and no serve path imports it.
   - A forward scorer that calls it is still to be written. It will be pinned at freeze.

## 7. Open questions before freezing

- **(a) Date overlap with B.** The forward dates overlap test B's 45 dates (D0 10-28, 45th date 12-12). B's rule
  forbids pooling and double use of B's verdict, and R-ODC is a different candidate. Master should confirm that the
  overlap is allowed and that R-ODC's look follows B's receipt.
- **(b) The WU history fetch for P1** (section 1): its source, approval and timing.
- **(c) Denver.** B excludes Denver; the dev gate included it. Keep the dev market set, or match B?
- **(d) Multiplicity.** This is the 3rd R-ODC test on the hypothesis, after rows 69 and 70, and the first on fresh
  dates. It should be disclosed in its ledger row at freeze.
