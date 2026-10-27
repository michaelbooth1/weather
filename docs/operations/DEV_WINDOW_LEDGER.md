# Dev-window reuse ledger

Status: canonical append-only ledger (lane L7, 2026-10-24). One row per candidate, control or descriptive
read scored on the development window **2026-07-31..2026-09-29**.

- **Owns:** which candidates have been scored on the development window, by whom, under which rule, with which
  headline result; and so the reuse count that every pre-registration must cite
  ([pre-registration checklist](PREREGISTRATION_CHECKLIST.md) section (e)).
- **Read when:** writing a pre-registration; scoring anything on 07-31..09-29; sizing the multiplicity correction
  of an edge test; citing a dev-window result.
- **Do not use for:** the measured conclusions ([findings digest](FINDINGS_DIGEST.md),
  [established findings](ESTABLISHED_FINDINGS.md)); sealed-panel or reserved-window decisions
  ([campaign ledger](CAMPAIGN_LEDGER.md), [reserved confirmation window](reserved-confirmation-window.md)).
- **Update when:** before scoring a candidate (add its row as `pending`), and when its result exists (fill
  delta, CI and verdict). Rows are never deleted or rewritten; a correction is a new row that names the old one.

## Rules that bind every row

- **Dev wins are provisional.** A KEEP here is development evidence on dates that many lanes have read. It earns a
  pre-registration on new dates and a forward shadow; it is never confirmation, edge or promotion evidence (EF §5).
- **The edge test corrects for the number of candidates tried.** Its multiplicity denominator is every
  `candidate` row below **plus** the pre-ledger block (the 134 registered rules of the model-parity swarm, EF §10q,
  and the earlier 79a, 81a and 111h reads). Controls, baselines and descriptive reads are listed because they
  re-read the dates, not because they are candidates.
- **Numbers come from committed files only.** A number not yet in a committed record is `pending`, never
  estimated. Intervals are the 95% crossed date x market interval of the pooled `ALL` row unless the row says
  otherwise.
- **Population:** unless a row says otherwise, the dev scorecard's default folds on `C:\swarm\v3layout`: scored
  2026-08-15..09-29, 43 dates x 11 US markets = 473 market-days.

## Pre-ledger reads of the same dates (block, not itemised)

| Read | Scope | Candidates | Record |
| --- | --- | --- | --- |
| 79a, 81a | morning guidance leads; read 2026-08-23..09-29 among other dates | pending (count not itemised here) | EF §10h, §10j |
| 111h | guidance at all hours, 111h table (08-01..09-29) | pending (count not itemised here) | EF §10p |
| Model-parity swarm v2 (2026-10-04) | 111h table, 08-01..09-29, harness v2 | 134 registered rule ids (the swarm's own multiplicity denominator) | EF §10q, [synthesis](../research/model-parity-swarm-2026-10-04/SYNTHESIS.md) |

## Rows

Types: **B** baseline, **C** control (reproduction of a known rule), **K** candidate (counts toward the
correction), **D** descriptive read.

| # | Date | Lane | Branch @ tip | Rule (sha256 or commit) | Type | Candidate | Headline delta [95%] | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2026-10-04 | swarm v2 | master (EF §10q) | registered `r-t5-inc-c1`; harness `8db69adc…` | K | MG-1 (v2_mean, sigma = max(v2_stddev, 1), floored, zero parameters) | 00-16 MG-1 − served −0.0100 [−0.0179, −0.0035], 10/11 markets (harness v2, 111h table, not the dev-scorecard rows) | lead, SIGNED for a reservation (`b044e0f1`); fails Bonferroni at 134 rules |
| 2 | 2026-10-23 | C | `claude/integration-20261024-devscorecard-on-master` @ `4be7c077c` | none (baseline) | B | served vector of record vs market | R all 1.774 [1.566, 2.052]; 00-16 1.526 [1.369, 1.721]; 13-16 1.862 [1.557, 2.345] (score `3557f797c6ca…`; numbers recorded by L5 and G) | baseline |
| 3 | 2026-10-24 | G | `claude/free-source-screens-20261023` @ `ee514984d` | EF §10q t3-r3 (pre-registered) | C | t3-r3 METAR remaining-rise | 13-16 t3-r3 − served −0.0110 [−0.0188, −0.0041] | control reproduced (EF §10q −0.0116) |
| 4 | 2026-10-24 | G | same | `r-t5-inc-c1` | C | MG-1 | 00-12 MG-1 − served −0.0153 [−0.0234, −0.0083] | control reproduced (EF §10j) |
| 5 | 2026-10-24 | G | same | in-doc pre-declaration, commit `31f536c84` (no file sha256) | K | F1 IEM 1-min ASOS running high, degraded 5-min whole °C +10 min | 13-16 over t3-r3 +0.0044 [+0.0017, +0.0076]; vs served −0.0066 [−0.0138, −0.0000] (score `6b0179912f9b…`) | KILL (harm) |
| 6 | 2026-10-24 | G | same | same as row 5 | K | F1u raw 1-min +2 min (sensitivity) | 13-16 over t3-r3 +0.0029 [+0.0004, +0.0057]; vs served −0.0081 [−0.0156, −0.0015] (`f9633f12518f…`) | harm (reported only) |
| 7 | 2026-10-24 | G | same | in-doc pre-declaration, commit `308ce88ed` | K | F2 MRMS reflectivity >= 35 dBZ within 25 km | 13-16 over t3-r3 −0.0005 [−0.0010, −0.0001]; vs served −0.0115 [−0.0192, −0.0046] (`511bd35de76e…`) | KEEP as development lead only (below the 5% bar; needs a capture change) |
| 8 | 2026-10-24 | G | same | in-doc pre-declaration, commit `2f97d1a1c` | K | F3 12Z sounding mixed-layer cap | 13-16 over t3-r3 −0.0001 [−0.0003, +0.0000]; vs served −0.0111 [−0.0188, −0.0043] (`52f20094cdfb…`) | KILL (null) |
| 9 | 2026-10-24 | G | same | in-doc pre-declaration, commit `308ce88ed` | K | F4 `gfs_seamless`, MG-1 recentred halfway | 00-12 over MG-1 +0.0008 [−0.0032, +0.0055]; vs served −0.0145 [−0.0227, −0.0064] | KILL (null) |
| 10 | 2026-10-24 | G | same | same as row 9 | K | F4 `ncep_nam_conus` | 00-12 over MG-1 +0.0007 [−0.0037, +0.0052]; vs served −0.0146 [−0.0214, −0.0082] | KILL (null) |
| 11 | 2026-10-24 | G | same | same as row 9 | K | F4 `ncep_aigfs025` | 00-12 over MG-1 +0.0003 [−0.0046, +0.0056]; vs served −0.0150 [−0.0234, −0.0064] | KILL (null) |
| 12 | 2026-10-24 | G | same | same as row 9 | K | F4 `gefs_mean` | 00-12 over MG-1 +0.0054 [+0.0016, +0.0100]; vs served −0.0099 [−0.0185, −0.0011] | KILL (harm) |
| 13 | 2026-10-24 | G | same | in-doc pre-declaration, commit `825330709` | K | G2-a ECMWF ENS 51-member mean, bias-adjusted, MG-1 recentred halfway | 00-12 over MG-1 −0.0000 [−0.0033, +0.0031]; vs served −0.0154 [−0.0230, −0.0078] (`1d72ea4b36f8…`) | KILL (null) |
| 14 | 2026-10-24 | G (L4) | same | `96dee78c7bfe8e350905c19048824ddf25729fcf3bc829bde066f16ad346a3b0` (commit `144a1f582`) | K | L4 per-station x hour inverse-MSE blend of NBM v2, GFS, IFS, ICON day-1 | 07-12 over MG-1 −0.0002 [−0.0045, +0.0047]; vs served −0.0141 [−0.0211, −0.0068] (`d019d6b1fde6…`) | KILL (null at 07-12) |
| 15 | 2026-10-24 | L5 | `claude/morning-loss-diagnosis-20261024` @ `dee30cabe` | plan `a10b172fb1e99e3f3aa268849e58bb4441ea729a233c048acd805aae4425786a` | D | served-minus-market loss diagnosis at 07-12 (served control reproduced first) | served control R all 1.774 [1.566, 2.052], 00-16 1.526 [1.369, 1.721]; 07-12 centre share 76.5% [63.1, 88.7]; served bias −1.44 F [−2.20, −0.69]; MG-1 07-12 excess 0.0117 vs served 0.0258 | descriptive; no candidate decision |
| 16 | 2026-10-24 | L2 | `claude/pooled-residual-model-20261024` @ `685c5beec` | original and amendments 1-3 (`e2649f16…`, `6dac6419…`, `1a656639…`, `09f77d4e…`) | K | P3 pooled residual model vs served on the dev window (amendment 3) | pending | pending |
| 17 | 2026-10-24 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | `dev_rule.md` `cf75eced…` + clarifications 1-3 → `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676` (original `cf75eced…` locked before any row) | K | arm A: OLS + hard floor (forecast_high from 2026 Previous Runs, running high, current temp; fitted Aug-Sep 2021-25) vs served | dR = R_model − R_ref, pooled ALL 07-12, crossed [date-clustered]: −0.179 [−0.306, −0.072] [−0.232, −0.127]; no standard block worse; 5 primary −0.165 [−0.275, −0.060]; 12-16 −0.317; covers 07-23 only (23,955 snapshots 00-06 fall back to served) (`dev_scores_v4` under `C:\t\l3\dev4`) | beats served (dev rule); selection evidence only |
| 18 | 2026-10-24 | L7 | `claude/loss-atlas-prereg-20261024` @ `8a58d9b04` | none (control) | C | loss atlas, served (positive control R 1.774 / 1.526 must reproduce) | control R all 1.774 [1.566, 2.052], 00-16 1.526 [1.369, 1.721] PASS; 07-12 centre share 76.5% [63.1, 88.7], served bias −1.44 F [−2.20, −0.69], top-decile share 35.0% [29.3, 45.2], top-decile lead 13.2 h [9.6, 14.7] (atlas `4d094a63eb25…`, workstation `C:\t\l7\atlas\served\`) | control PASS; reproduces row 15 to every reported digit |
| 19 | 2026-10-25 | L7 | `claude/loss-atlas-prereg-20261024` @ `8a58d9b04` | none (control re-run, delta mode) | C | loss atlas, MG-1 (lane G rule `r-t5-inc-c1`), delta vs served | control PASS; 07-12 MG-1 − served −0.0139 [−0.0212, −0.0072] (date-clustered [−0.0173, −0.0102]), closes 53.7% of served's excess; closed slice 43.1% centre, 10.6% width; closes 67.9% [49.8, 82.6] of served's top-decile excess; hottest tercile closes 74.0% (atlas `535221e08c1d…`) | control (reproduces row 4 direction; not a new candidate) |
| 20 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | none (control) | C | served vs market through L3's scorer | R all 1.7739, 00-16 1.5263 (`3557f797…`) | control PASS |
| 21 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | `dev_rule.md` `cf75eced…` + clarifications 1-3 → `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676`, clarification 1 gate | K | arm A vs MG-1 (L7 `mg1_frame`; control 07-12 excess 0.011957 PASS) | dR = R_model − R_ref, pooled ALL 07-12, crossed [date-clustered]: +0.080 [−0.011, +0.195] [+0.020, +0.142]; 06-09 +0.148 [+0.052, +0.260]; 00-16 +0.121 [+0.021, +0.250]; 13-16 −0.366; MG-1 − served −0.259 at 07-12, −0.247 at 00-16; 5 primary +0.086 [−0.090, +0.313] | **FAIL** (no-worse-than-MG-1 gate) |
| 22 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | same as row 17 | K | arm (b) OLS + floor + residual HGB vs served / MG-1 | vs served −0.179 [−0.302, −0.072]; vs MG-1 +0.080 | beats served; FAIL vs MG-1 |
| 23 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | same as row 17 | C | forecast + floor (bias-corrected forecast, floored) vs served | 07-12 −0.078 [−0.219, +0.059] [−0.125, −0.030]; 12-16 +0.210 [+0.007, +0.466] | control (the gain of A is not the floor) |
| 24 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | same as row 17 | D | arm A sensitivities: served forecast; two features; L8 serve-equivalent high_so_far | 07-12 vs served −0.198 / −0.177 / −0.179 (L8 definition equal on all 9,224 replay hours; file byte-identical) | descriptive |
| 25 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | `dev_rule.md` `cf75eced…` + clarifications 1-3 → `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676`, clarification 3 | C | L6 own-obs twin re-run through L6's own module (walk-forward) | 07-12 Brier − MG-1 −0.0036243 = L6 `d6971121…` to 1e-6; twin − arm A dR = R_model − R_ref, pooled ALL 07-12, crossed [date-clustered]: −0.148 [−0.255, −0.061] [−0.190, −0.103] | control PASS; twin adds beyond A at 07-12 |
| 26 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | `dev_rule.md` `cf75eced…` + clarifications 1-3 → `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676`, clarification 3 | K | intercept-only twin: MG-1 + per-hour 07-12 shift, no observations | − MG-1 +0.007 [−0.045, +0.062]; − arm A −0.074 [−0.174, +0.018] [−0.122, −0.022] | null vs MG-1 |
| 27 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `eaed66d6a` | `dev_rule.md` `cf75eced…` + clarifications 1-3 → `fa72409a187744f294913356ff78ac1a508bbb3bebad375ffd89f87e7efc8676`, clarification 3 (sensitivity, not binding) | K | arm A and A' (A + NBM mean regressor) refitted walk-forward on dev rows | A dev-fit − A −0.025 [−0.126, +0.068]; A' dev-fit − A −0.017 [−0.118, +0.075], − MG-1 +0.064 [−0.030, +0.162] | null; A' on L9's historical PIT NBM pending |
| 28 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `a8f922cfa` | MG-2 pick rule `C:\t\mg2\afternoon_pick_rule.md` `2f2c5994…` clarification 1 (a), (e); `dev_rule.md` clarification 5 → `171caa3c…` | C | serve-parity read of the dev capture, inputs only (no labels, outcomes or pick rows): captured forecast_high vs Open-Meteo Previous Runs analogues; captured NBM v2 vs L9's NBP 07Z pipeline; L6 own-obs features from captured METAR vs the IEM-built serve features | no PIT analogue of the captured forecast_high (day-0 13-16 MAD 1.29 °F, not PIT; lead-1 1.68); NBM 07Z mean exact on 47,414/47,414; L6 own-obs t exact 78% (99.5% excluding reports < 10 min old), prev_dmax not captured | parity evidence only; nothing scored |
| 29 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `0a8e7fc9a` | MG-2 pick rule `C:\t\mg2\afternoon_pick_rule.md` clarification 2 → `52cef556…` (erratum → `deb3eae3…`), (a), (b), (d) | K | pick-rule control: A_N (OLS+floor on captured NBM 07Z mean, L8 running max, current_temp; training corpus `1ae4bf52…`, dev corpus `85746b7a…`) − MG-1 at 13-16 on the pick rows, before any P3d_N row; `control_refit_armA.json` `714f1c51…` | −0.3915 date-clustered [−0.5567, −0.2488], crossed [−0.6199, −0.1807], 13,958 rows; harness check old lead-1 arm A −0.364 vs −0.366 | clause (d) passes: pick may proceed once P3d_N exists |
| 30 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `ecd8c9ba6` | pick rule clarification 2 (e) `deb3eae3…`; `dev_rule.md` `171caa3c…` | K | L6 re-spec: L6's own-obs stack on nowcasts from the captured METAR rows (10-minute rule, T-group dewpoint, prev-day max from the previous day's last captured snapshot); nowcasts `3806687c…`, refit positive control gap 0.0; twin control −0.0036243 reproduced | − MG-1 07-12, 11 mkts −0.0673 [−0.1016, −0.0339] crossed [−0.1227, −0.0160]; 5 mkts −0.0786 [−0.1340, −0.0238] crossed [−0.1988, +0.0062]; − IEM twin +0.0005 [−0.0008, +0.0022] | captured-METAR L6 matches the IEM twin; parity holds |
| 31 | 2026-10-25 | L3 | `claude/r0-ols-floor-challenger-20261024` @ `ecd8c9ba6` | MG-2 pick rule `C:\t\mg2\afternoon_pick_rule.md` `deb3eae3…`, clarification 2; L2 rule amendment 5 `b3f017bb…` | K | MG-2 afternoon pick, run once: A_N (`066ac73b…`) vs P3d_N (`721ae2cd…`) on the 13-16 intersection (13,958 snapshots, 5-mkt 6,372); parity notes A_N `078a3879…` and P3d_N `13dfa4cd…` both pass, written before the result; output `pick_result.json` `1ce2b5b4…` | control reproduced −0.3915 (tol 0.005); P3d_N − A_N, 11 mkts −0.155 [−0.218, −0.098] crossed [−0.330, −0.031]; 5 mkts −0.108 [−0.194, −0.026] crossed [−0.357, +0.044]; h13-h16 −0.109/−0.150/−0.197/−0.280, all date-clustered upper bounds < 0; − MG-1 −0.547 [−0.723, −0.399] | P3d_N eligible on conditions 1-4; pick = P3d_N (one challenger eligible) |
| 57 | 2026-10-26 | L11 | `claude/permarket-bias-20261026` @ `f84ba000c` | R-M `91e25610…` (committed `78fb338de`) | K | per-market additive centre shift at 07-12 on P3d_N_fix, nested LOYO 2021-25 (19,657 rows, 300 clusters); `rm_loyo.json` `0f6a7394…`, `rm_loyo_rows.jsonl` `6eee0764…` | gate 1 +0.00013 [−0.00027, +0.00055]; Miami +0.00252 [+0.00092, +0.00421] | gate 1 FAIL → KILL, every NBM-anchored arm |
| 58 | 2026-10-26 | L15 | `claude/spread-info-20261026` @ `efd95d8b9` | R-S `70908316…` (committed `8f80ea821`); plan `523d334e…` | K | NBP TXNSD anomaly as scale modulator on P3d_N_fix 07-12; LOYO 2021-25 then dev 2026-08-15..09-29 (21,664 snapshots); results `604b0a0f…`, score `c3e8f0b2…` | gate 1 LOYO −0.00099 [−0.00171, −0.00026]; gate 2 dev +0.00067 [−0.00604, +0.00722] | gate 2 FAIL → KILL, NBM-published-spread family |

The F1-F4 and G2-a rules were committed inside the
[free-source screens record](https://github.com/michaelbooth1/weather/blob/claude/free-source-screens-20261023/docs/research/free-source-screens-2026-10-23.md)
before each was scored; that record and EF §10x on that branch own the per-hour and per-market detail.

Rows 32-56 are held by ledger branches not yet on master (`claude/l3-dev-ledger-rows-20261025`,
`claude/l2-dev-ledger-rows-20261026`); rows 57 and 58 were numbered after them so that no number is reused.
