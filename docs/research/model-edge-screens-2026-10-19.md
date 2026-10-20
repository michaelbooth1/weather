# Model-edge week 1: development screens for levers 6, 7, 8 and 13 under HARNESS v3 (2026-10-19)

**Status:** dated research record, **development only**. Every scored number below comes from dates
2026-07-31..2026-09-29 that 79a, 81a, 111h and the model-parity swarm v2 had already read (forward alpha ledger
row `spent-dev-20260731-20260929`). Nothing here is confirmation or evidence of edge; a survivor only earns a
place on the A1 list for a pre-registration on new dates.

**Owns:** the pre-declared kill-rule blocks, the screen results, kill/survive verdicts and H3 power for levers 6,
7, 8 and 13 of the model-edge programme, and the A1 survivor list for the EDGE-1 annex.

**Read when:** drafting the EDGE-1 annex, or before proposing any candidate from these levers again.

Branch `claude/model-edge-screens-20261019`, created off the HARNESS v3 tip `74a85c7f6e48c929f1a16a9fdb97e8800c998fde`
(not master) so that `v3_*.py` is available. HARNESS v3 design and controls:
[harness-v3-2026-10-19.md](harness-v3-2026-10-19.md). Lever 5 (serving-stage re-trace):
`docs/research/model-edge-lever5-2026-10-19.md` on `claude/model-edge-codecheck-20261019` @ `4743a7048dc00b3a4bda2b8a3a85817ea16d0109` (not on this branch).

## 1. Boundaries and how the screens ran

- Dates: 2026-07-31..2026-09-29 only (the layout holds 57 dates 08-01..09-29; 07-31 is not in it). Gate purpose
  `development` (the brief's "dev-screen"): HARNESS v3's H1 gate admits it on these dates through the existing
  ledger row `spent-dev-20260731-20260929`; `closed-from-20260930` refuses every join on or after 2026-09-30 and
  `embargo-20261016-20261113` refuses everything 10-16..11-13. No ledger row was needed or added, and no file
  holding a date >= 2026-09-30 was opened (the layout manifest lists none).
- Data: `C:\swarm\v3layout` (split from the v2 swarm cache; inputs, labels and market prices in separate files,
  sha256-checked). This layout is derived from the 111h extract. Its numbers are therefore **development screens on
  already-read dates, not evidence** for any claim, and no 79a/81a/111h *result table* is cited as evidence here.
- Every data job ran through `scripts\ops\workstation_heavy.ps1 -Kind pytest -Queue` driving
  `tools/research/model_parity/test_me_screens_dev.py` (phases `dryrun`, then `score`), because the model-parity
  modules are not on the `weather_heavy` allowlist.
- H2 dry run (outcome-free: no label or market file opened, `v3_outcomes`/`v3_score`/`harness` never imported) ran
  first for every arm (section 3).
- Scoring: one sealed `v3_score.run` single-shot pass (all arms + input-removed twins + `market_identity`), then the
  screen statistics on the same `v3_core.Table` (81a floor mask, served fallback, one crossed date x market W matrix,
  2,000 draws). Code: `tools/research/model_parity/me_screens_score.py`, arms `me_arm_*.py`.
- v2 registry: `C:\swarm\registry.jsonl` (138 rule ids). Rules already tried there are cited by id and not re-tested.

## 2. Pre-declared blocks and kill rule

**KILL RULE DECLARED BEFORE SCORING** (written after the outcome-free H2 dry run of section 3 and committed before
the score phase; `me_screens_score.check_declared` refuses to score unless this commit is an ancestor of HEAD and
holds this line).

**Universal kill rule.** A candidate is KILLED if, in its declared block, (a) the point estimate of the declared
estimand is >= 0, OR (b) fewer than 7 of the 11 markets have a per-market mean of the same (negative) sign, OR (c) its
input-removed twin captures >= 75% of the effect (twin estimate / candidate estimate >= 0.75). Otherwise it
SURVIVES. Statistics: equal-weight (date, market) cells, crossed W interval (v3_core, 2,000 draws, seed 20260921),
81a floor mask and served fallback on every row.

| ID | Lever | Candidate (arm file, code sha256) | Declared block | Estimand | Twin |
| --- | --- | --- | --- | --- | --- |
| C-L7-V2Q | 7 | Captured NBM v2 **quantiles** p10..p90 read as a piecewise-linear distribution, H = max(B, X), zero parameters (`me_arm_l7_v2q.py`, `1a825a2adf0a937e979a3ee46f0e80cad8d38a3fdcfc23cda351831862c903b8`) | 00-16 | candidate − served Brier | v2 quantile inputs blanked (served fallback) |
| C-L13-BT | 13 (lever-5 open stage 9) | Bucket-transition prior re-pointed on captured `high_so_far`, serving code and constants, **stage-level approximation on the final served vector** (`me_arm_l13_bt.py`, `9bcfdd258981e7e0b265abcc6d18757b034948bf8362dc75b6e5e7dbe039f41c`) | 00-16 | candidate − served Brier | `high_so_far`, `cutoff_hour` blanked (served fallback) |
| C-L8-E2S | 8 | E2 blend w·served + (1 − w)·market, w per block fit on dev dates only (grid 0.00..1.00 step 0.01) | 00-16 | **out-of-fold** blend − market Brier (2-fold by date: fold A 08-01..08-22, fold B 08-23..09-29; each fold scored with the weight fit on the other) | the market alone (served has no inputs; removing the model leaves the market, effect 0) |
| C-L8-E2M | 8 | E2 blend of the MG-1-like arm (`v3_arm_mg1_like.py`, `5844c50cc341a47f9cc4ccbb7db2b04ff26461423fb92a8a9dccca21679dbdae`) and the market, same fitting | 00-16 | out-of-fold blend − market | the same blend built on the MG-1-like arm's input-removed twin (= served) with the same fold weights |

Declared secondary readings (not kill conditions):
- C-L7-V2Q reads the same source as MG-1 (captured NBM v2). It is eligible for the A1 list **only if** it survives
  AND its paired increment over the MG-1-like arm in 00-16 has a negative point with >= 7/11 markets negative;
  otherwise it is reported as "survives, but no increment over MG-1" (MG-1 is already signed and frozen).
- C-L8-E2*: the in-sample (full-dev fit) blend − market is reported beside the out-of-fold number for comparison
  with the harness controls; only the out-of-fold number decides.
- Context arm (not a candidate): `v3_arm_mg1_like.py` (the v2 c1 / MG-1 family re-implementation), scored with the
  same statistics.
- **H3** for every survivor: variance components from the survivor's own development cells in its declared block
  (crossed, date-only and market-only SDs, `v3_power.components_from_entry`), simulated at 20 and 45 forward dates x
  11 markets, effect = one half of the development estimate, bar 0.0133; TESTABLE iff the analytic MDE80 <= the bar.
- **Lever 13** is descriptive (no kill). The tail lens is the EF §1/§1f definition on this table's rows (band rows
  with served SE > market SE and |p_served − p_market| >= 0.30); it is characterised by market, hour block, local
  hour, stratum, band position relative to the floor bucket, winner band, served-above/below-market direction and
  MG-1-like coverage. Every arm reports its share of tail excess removed (00-16, 17-23, all).

## 3. H2 dry run (outcome-free)

Run `dryrun_20261019T122521` (`C:\swarm\out\mescr\...\dryrun.json`, sha256
`cdb70340a0e6da45f94c011bb95eabebb920edc0cf04bf74df5e3a47b10c8f4b`), code `046aded49021e8237f0420c7e12df28336721e6c`,
through the heavy wrapper (lease ticket 1, waited 145 s). Modules loaded: `me_screens_dryrun`, `v3_arms`,
`v3_dryrun`, `v3_gate`, `v3_inputs` only (no `v3_outcomes`, `v3_score` or `harness`). Gate: MG-1 window
`reserved_undated` from 2026-10-15; ledger sha256 `11e57524…`, 4 rows; **0 dates refused** for any arm under purpose
`development`.

| Arm | Family | Eligible snapshots (floor present, arm covers) | Market-days | 00-16 eligible share |
| --- | --- | --- | --- | --- |
| C-L7-V2Q | `nbm_guidance_band` | 110,077 of 110,807 | 626 | 0.992 |
| C-L13-BT | `serving_stage_bucket_transition` | 14,660 (13.2%; Miami 5,684, Houston 3,517, others 101-1,459) | 324 | 0.149 |
| MG-1-like (context) | `nbm_guidance_band` | 110,077 | 626 | 0.992 |
| served identity | `serving_identity_control` | 110,077 | 626 | 0.992 |

C-L13-BT's 14,660 active snapshots equal lever 5's census count exactly (14,660 of 110,077, 13.3%), so the arm
reproduces the stage's own gating. Outcome-free input facts:
- **Toronto: 0 rows.** The layout holds the 11 US markets only.
- `forecast_high + open_meteo_hrrr_high_delta` (the Open-Meteo multimodel HRRR day high) equals the captured
  `hrrr_high` **exactly** on all 106,377 rows where both exist (|difference| max 0.0). It is the same captured value
  the v2 swarm already tested (t8-c2, t9-c2), so it is not a new source.
- v2 quantiles: all five present and point-in-time on every row where `v2_mean`/`v2_stddev` are (110,807), so
  C-L7-V2Q covers exactly MG-1's rows.
- `trusted_current_max` is null on **100%** of rows (all 11 markets), as EF §10q and lever 5 stage 13 say.

## 4. Lever 6: Toronto GEM/HRDPS and captured-but-unscored ensemble members — STOPPED (input not on this workstation)

Inventory of what this workstation holds (read-only listing, no download):
- The dev layout and the 111h extract it comes from have **no Toronto rows** (EXHAUSTION_REGISTER §1: "11 US markets
  (no Toronto)"), so there are no Toronto labels or market prices here to score against either.
- Toronto captures that production makes (`eccc_gem` = Open-Meteo GEM seamless/global/regional, `eccc_citypage`,
  `global_ensemble` = Open-Meteo GEFS members summarised as mean/spread/p10/p90) live in the capture host's
  `data\snapshots\...\replay_inputs.jsonl`. The workstation's `data\` holds none for the dev window: no
  `data\snapshots`; `data\archive\closed_market_days\v0.1` ends 2026-07-11; `data\eccc\cyyz` and
  `data\eccc_swob\cyyz` are observation archives (climate hourly / SWOB), not GEM or HRDPS; `data\forecast_history\cyyz`
  is the Open-Meteo stitched historical-forecast corpus generated 2026-06-23 (`stitched_continuous_archive`, not
  captured, `HISTORICAL_FIRST_AVAILABILITY_UNPROVEN`, EF §1m) and ends before the dev window;
  `data\forecast_payload_cas` holds NBM NBP bulletins and fan-out receipts only.
- **Ensemble members:** no captured payload with member values exists on the workstation. The dev table carries no
  `global_ensemble` column at all (the served GEFS "mean" is the control run, EF §10s). The swarm's acquired data
  (`C:\swarm\data`: ECMWF IFS oper, HRRR, NBH, NBS, Single-Runs, soundings, GOES, IEM) is deterministic or
  bulletin-level and US-only; none of it is ENS/GEFS members or Toronto.

**Verdict: lever 6 cannot be screened here.** The input it needs (Toronto GEM/HRDPS payloads with their fetch
times, and per-member GEFS values) is captured only on the capture host. No download was made. What would unblock it:
a host-side, read-only extract of `eccc_gem` and `global_ensemble` payload fields (with `fetched_at`) for Toronto and
the 11 US markets on 07-31..09-29, plus Toronto labels and market prices for those dates, built under the host lease;
then a Toronto guidance control (EXHAUSTION_REGISTER S9-GEFS, S13 and order 12: "Toronto first, with GEM/HRDPS").

## 5. Lever 7: full free-source parity

Which captured free sources the v2 registry (`C:\swarm\registry.jsonl`, 138 ids) already tested, by the captured
column the dev table carries:

| Captured value on the workstation | Tested in v2 as | Status here |
| --- | --- | --- |
| NBM v2 mean / stddev | r-t5-inc-c1 (MG-1), ladder-r2, t6-c2, t10-c2, t18-r1/c1/r1s, d3-z1, r-stat-mg1-d1/d2 | tested (EF §10q) |
| NBM v1 `nbm_prob_tmax_*` | 79a, 81a, 111h (EF §10h, §10j, §10p) | tested; not re-read |
| `hrrr_high` (Open-Meteo HRRR day high) | t8-c2, t9-c2, t18-r1/c1/r1s, t17-d1 | tested |
| `forecast_high + open_meteo_hrrr_high_delta` | identical to `hrrr_high` (section 3) | tested (same value) |
| `nws_grid_high(_raw)` | t12-r1/r2, t15-r1..r4, t7-c2, t18-r1 | tested |
| `forecast_high` (served consensus median) | t15-r1..r4, t18-r1/c1/r1s | tested |
| floor fields (`high_so_far`, `guidance_physical_floor`) | d-defect-r1, d2-r3f, d3-z1f | tested |
| `trusted_current_max` | — | null on every row (nothing to test) |
| **NBM v2 quantiles `v2_p10..v2_p90`** | **never read by any registered rule** | **screened: C-L7-V2Q** (same source as MG-1; a form variant) |

External free sources the swarm acquired (NBH, NBS, MOS/NBE, Single-Runs HRRR, ECMWF IFS, soundings, neighbours,
GOES/METAR cloud, NWS revisions) are tested (EF §10q; registry t5-t14, ladder-inc-t5..t14) and are not re-tested.

**But lever 7 cannot be closed as "every captured free source tested".** EXHAUSTION_REGISTER §2 lists six sources
production captures whose own increment was never scored: S9 GEFS (`global_ensemble`), S11 ECMWF AIFS and S29
AIGFS/GraphCast (inside the `open_meteo_global_models` vote), S13 GEM/HRDPS (Toronto), S26 MRMS precipitation and S32
NAM (US multimodel feed). EF §10q's "no external free source adds information" covers the sources the swarm
*acquired*, not these. None of their per-source values is in the workstation's dev table (they sit in the host's
captured payloads), so they cannot be screened here without a host extract; no download was made.

## 6. Scoring run and controls

Run `score_20261019T123125` through the heavy wrapper at code `efcd93dadc9d91957d51ffe42fe07cc874b32dcd` (the
declaring commit; `check_declared` passed, doc sha256 at that commit `a837040d…`). `HARNESS_V3_SHA256`
`b1e8fb167e3e4a331d3dad12e8ba8144a4f252ca9ca257e81d1a7403e818fd48` (unchanged from the harness record). Sealed
single-shot pass: prereg sha256 `955d5643f8e0576c52b5194d063a8f2badc44589a196e84a3021a5aca999ac39`, result
`C:\swarm\out\mescr\score_20261019T123125\sealed\955d5643f8e0576c.result.json`, sha256
`b83ac660910d0ff395ebf2ac21317ace9306ca20f8639835bd45327520820be1`, read-only, verified; label ledger written; **no
leakage suspects**; planted-label screen passed. Screen output `screens.json` sha256
`af95b8db8cd7666114fe3f0cdd6b211b426fcfddf28ff16f227c08f27ac3de21` (workstation, not committed). Scored: 57 dates
2026-08-01..09-29, 626 market-days, 11 markets.

Controls inside the run (all reproduce, so the screen machinery matches HARNESS v3 / swarm v2):
- MG-1-like arm, 00-16 − served = **−0.0100457 [−0.01693, −0.00406]**, 10/11: the harness record's −0.0100457.
- Tail lens on this table: **6.0749% of band rows carry 70.376% of the positive excess** (74,046 of 1,218,877
  rows): EF §10q's 6.075% / 70.38%.
- Every input-removed twin of an input-reading arm scores exactly 0.0 − served in every block (it falls back).

## 7. Results per candidate (development; equal market-day cells, crossed W 95% intervals)

### C-L7-V2Q (lever 7, captured NBM v2 quantiles)

| Block | candidate − served | markets < 0 | candidate − market |
| --- | --- | --- | --- |
| 00-05 | −0.01282 [−0.02137, −0.00579] | 11/11 | +0.01138 |
| 06-09 | −0.01356 [−0.02171, −0.00660] | 11/11 | +0.01279 |
| 10-12 | −0.00906 [−0.01518, −0.00333] | 10/11 | +0.01488 |
| 13-16 | +0.00081 [−0.00622, +0.00707] | 2/11 | +0.02508 |
| 17-23 | +0.00794 [−0.00553, +0.01827] | 2/11 | +0.03901 |
| **00-16 (declared)** | **−0.00906 [−0.01606, −0.00322]** | **11/11** | +0.01556 |

Twin −served 0.0 (share 0). **Kill rule: SURVIVES.** Declared secondary: paired increment over the MG-1-like arm,
00-16 **+0.00099 [−0.00094, +0.00292], 4/11 negative** (06-09 +0.00169; 13-16 −0.00180 [−0.00446, +0.00096]; 17-23
−0.00778 [−0.01024, −0.00539], the evening leg where MG-1 itself harms). The quantile shape adds nothing over the
mean/stddev read in the declared block, so by the declared rule it is **not an A1 candidate**: it is the MG-1 family
(S1, signed `b044e0f1`), not a new source. H3 (for the record): 20 dates MDE80 0.0099, power 0.27; 45 dates MDE80
0.0084, power 0.35; TESTABLE.

### C-L13-BT (lever-5 open stage 9, bucket transition, stage-level approximation)

| Block | candidate − served | markets < 0 | coverage |
| --- | --- | --- | --- |
| 00-05 | −0.000087 [−0.00020, −0.00001] | 8/11 | 0.169 |
| 06-09 | −0.000083 [−0.00020, −0.00001] | 8/11 | 0.169 |
| 10-12 | −0.000068 [−0.00019, −0.00001] | 8/11 | 0.142 |
| 13-16 | −0.000040 [−0.00009, −0.00001] | 9/11 | 0.104 |
| 17-23 | −0.000088 [−0.00021, −0.00002] | 8/11 | 0.092 |
| **00-16 (declared)** | **−0.000073 [−0.00016, −0.00001]** | **8/11** | 0.149 |

Twin 0.0 (share 0). **Kill rule: SURVIVES** — but the effect is tiny: about **0.3%** of the 00-16 served − market
gap on this table (+0.0246), against a 5% bar of about −0.0012 and EF §1d's 3.2% floor. It is a stage-level
approximation on the final served vector; serving blends earlier, before the floors, lock-ins and calibration, so
the real final-vector effect needs lever 5's host replay. H3 at one half of the effect (−0.000037): 20 dates MDE80
0.000107, power **0.19** (simulated; analytic 0.16), GO given null 0.030; 45 dates MDE80 0.000100, power **0.20**;
**TESTABLE by the v3 rule** (MDE80 <= 0.0133) **but underpowered**: the market component (var_market 1.24e-8 vs
var_date 6.6e-9) caps power near 20% at any season length.

### Lever 8: the E2 frozen blend — CLOSED

Weights per block on the 0.00..1.00 grid, fit on dev dates only (`v3_score.fit_blend_weights`):

| Blend | full-dev weights (00-05/06-09/10-12/13-16/17-23/00-16) | fold A fit | fold B fit |
| --- | --- | --- | --- |
| C-L8-E2S served + market | 0.00 everywhere | 0.00 everywhere | 0.00 everywhere |
| C-L8-E2M MG-1-like + market | 0.01 / 0.02 / 0.02 / 0.00 / 0.00 / **0.00** | 0.02 / 0.00 / 0.02 / 0 / 0 / 0 | 0.01 / 0.04 / 0.02 / 0 / 0 / 0 |

Out-of-fold blend − market: C-L8-E2S is the market itself in every block (0.0 exactly, R = 1.0 [1.0, 1.0]);
C-L8-E2M 00-16 0.0 exactly (weight 0), and the only non-zero blocks are 00-05 −0.000004 [−0.00006, +0.00005] (5/11),
06-09 +0.000011 [−0.00007, +0.00009] (4/11), 10-12 −0.000011 [−0.00009, +0.00008] (4/11); out-of-fold R 0.9989-1.0003,
every interval containing 1. **Both KILLED** (point >= 0 in 00-16; 0/11 markets). Neither the served model nor the
MG-1-like read adds complementary information to the market price on these dates, in or out of fold; this
quantifies the harness controls' "weights 0.00-0.02". **Lever 8 is closed** for the served and MG-1-like arms.

## 8. Lever 13: tail diagnostic (descriptive, development)

Tail (EF §1/§1f lens, this table): 74,046 band rows (6.07%) carry 70.38% of the positive served − market excess.
Who owns it (share of all tail excess):

- **Band position and direction:** the winner band, under-weighted by served relative to the market, owns 62.2%
  (above the floor bucket by > 2 °F: 31.6%; the band holding the floor bucket: 26.7%; just above it: 3.3%).
  Over-weighted losing bands own 37.8%, mostly within 2 °F above the floor (16.5%) or further above (13.4%) or the
  floor-bucket band (7.2%). Bands below the floor own 0.5% (the 81a mask already removes them). The band holding the
  floor bucket is in the tail on 23.6% of its rows, bands up to 2 °F above it on 20.4%, bands further above on 4.3%,
  bands below the floor on 0.1%.
- **Hours:** 17-23 owns 32.4% (tail rate 7.5%, highest 17-18 h at 8.0-8.4%); 00-05 22.2%, 06-09 16.9%, 10-12 12.1%,
  13-16 16.3%. These served vectors predate the evening lock-in restoration (PR #191, landed after the table), so most
  of the 17-23 share is the EF §10e/§10q serving defect, not missing information.
- **Markets:** Los Angeles owns 18.6% (tail rate 11.1%, the highest), Dallas 13.1%, Chicago 10.6%, Austin 9.5%; the
  other seven 5.1-8.4% each.
- **Strata:** before 08-23 39.6% (rate 6.9%), from 08-23 60.4% (rate 5.6%).
- **MG-1 coverage:** 99.2% of tail excess sits on snapshots the MG-1-like read covers.

Does anything screened here move it? Share of tail excess removed (cell-clustered W interval):

| Arm | 00-16 | 17-23 | all |
| --- | --- | --- | --- |
| MG-1-like (context) | 69.3% [61.8, 75.9] | 33.3% [10.2, 50.3] | 57.7% [46.5, 66.6] |
| C-L7-V2Q | 69.0% [61.5, 75.8] | 43.9% [22.8, 58.6] | 60.8% [50.8, 69.0] |
| C-L13-BT | 0.22% [0.05, 0.48] | 0.28% [0.05, 0.67] | 0.24% [0.06, 0.51] |
| served with the 81a floor only | 0.2% [−0.6, 1.2] | 0.7% [−1.5, 4.1] | 0.4% [−0.8, 2.0] |

The NBM v2 reads remove most of the 00-16 tail excess on tail rows, but EF §10q already says the tail sign cannot rank
candidates here (98 of 99 v2 candidate vectors improve the tail; the non-tail cost separates them), and their net
00-16 effect is the −0.009/−0.010 above. The bucket-transition stage does not move the tail. Trusted current max
(lever-5 stage 13) cannot be screened here: `trusted_current_max` is null on every row and the restored input (METAR
max since 07:00 validated against the station high) is not in the table; its floor part is the registered METAR
fast-floor rule t17-r1 and the remaining-rise family (t3-r3), which are not re-tested. Its final-vector effect needs
the lever-5 host replay.

## 9. Kill / survive summary

| Candidate | Lever | 00-16 estimate | Markets | Twin share | Verdict | H3 (20 / 45 dates, half effect) |
| --- | --- | --- | --- | --- | --- | --- |
| C-L7-V2Q | 7 | −0.00906 [−0.01606, −0.00322] | 11/11 | 0 | SURVIVES the kill rule; **not A1** (increment over MG-1 +0.00099 [−0.00094, +0.00292], 4/11) | 0.27 / 0.35, TESTABLE |
| C-L13-BT | 13 / lever 5 stage 9 | −0.000073 [−0.00016, −0.00001] | 8/11 | 0 | **SURVIVES** (tiny; stage-level approximation) | 0.19 / 0.20, TESTABLE but underpowered |
| C-L8-E2S | 8 | 0.0 (weight 0) | 0/11 | — | **KILLED** | — |
| C-L8-E2M | 8 | 0.0 (weight 0) | 0/11 | 0 | **KILLED** | — |
| Lever 6 (Toronto GEM/HRDPS, ensemble members) | 6 | — | — | — | **NOT SCREENABLE here** (input only on the capture host) | — |
| Lever 7 captured-not-scored sources S9, S11, S13, S26, S29, S32 | 7 | — | — | — | **NOT SCREENABLE here** (per-source values only in host payloads) | — |

## 10. A1 survivor list (for the EDGE-1 annex; deadline Thu 2026-10-22 12:00 local)

One candidate. It is frozen by hash as screened; any change makes it a different candidate.

**A1-1 = C-L13-BT, bucket-transition stage re-pointed on the observed station high at the cutoff.**

| Field | Frozen value |
| --- | --- |
| Arm file | `tools/research/model_parity/me_arm_l13_bt.py`, sha256 `9bcfdd258981e7e0b265abcc6d18757b034948bf8362dc75b6e5e7dbe039f41c` (branch `claude/model-edge-screens-20261019`, first at `169512b4b360ce570216a2b593200cef7297bf60`) |
| Definition | p = (1 − w)·p_served + w·P_prior(band) where the prior and w are serving's own `bucket_transition_model` / `bucket_transition_blend_weight` with the observed bucket = round_half_up(captured `high_so_far`) and cutoff = captured `cutoff_hour`; `BUCKET_TRANSITION_MIN_SAMPLE` 20, `BUCKET_TRANSITION_BLEND_MAX` 0.12; rows with w = 0 fall back to served; then the 81a floor mask |
| Serving code read (sha256 at `74a85c7f6`) | `model_features.py` `16df3a3d…c32e5`; `model_distribution_signals.py` `4f3952b2…51dd`; `model_distribution_constants.py` `4c99ce64…4048`; `model_climatology.py` `2d69cb04…f43d`; `model_distribution.py` `a8d36e46…7251` |
| Climatology input | prior-year rows only (the serving cache drops the target year) from `data\wunderground\<icao>\` on the workstation; `daily_summary.csv` sha256: KATL `1f013bb6…`, KAUS `05852251…`, KBKF `52ee5938…`, KDAL `db631cf6…`, KHOU `2ba8271c…`, KLAX `7e05d5d8…`, KLGA `90e89fb6…`, KMIA `a3d2c6d9…`, KORD `1eff2c8a…`, KSEA `c2c5eebc…`, KSFO `5f1560c0…` (the hourly partitions it also reads must be fingerprinted when the prereg is written) |
| Family / NBM | `serving_stage_bucket_transition`, `READS_NBM_GUIDANCE = False` |
| Declared block and estimand | 00-16, candidate − served Brier |
| Development read | −0.000073 [−0.00016, −0.00001], 8/11, twin 0; 13.2% of snapshots active |
| H3 | power 0.19 (20 dates) / 0.20 (45 dates) at half effect; TESTABLE by the v3 rule, underpowered |

Conditions the annex should carry with A1-1: (1) the lever-5 host replay must give the final-vector form before a
pre-registration is written, because this screen applies the stage after the later stages; (2) its effect is about
0.3% of the 00-16 gap, below the 5% bar and EF §1d's 3.2% floor, so a forward read can at best show it is real, not
that it matters; (3) it is a serving-stage restoration (lever 5), not new information.

Not on A1: C-L7-V2Q (no increment over MG-1, declared rule), both E2 blends (killed), lever 6 and the six
captured-not-scored lever-7 sources (not screenable on the workstation).

## 11. Lever 13 follow-up: tail re-split (descriptive, development; master-agent request 2026-10-20)

**How it ran.** Phase `tail` of `test_me_screens_dev.py` through `workstation_heavy.ps1 -Kind pytest -Queue`, code
`tools/research/model_parity/me_tail_resplit.py` at `d8e3af7c6b35d293c13f106f4c84d2f3fda46755`; output
`C:\swarm\out\mescr\tail_20261020T174023\tail_resplit.json`, sha256
`9d5b46b360a8b76321dbb3a99d9a95e04adbbf8da4cbf3ae49e1d3e344b8a1aa` (an earlier run at `318b9b098`,
`tail_20261020T173842`, gave identical sections 11.1-11.3; the rerun only added the correlate baselines of 11.4).
Gate family `model_edge_tail_resplit`, purpose `development`, dates 2026-07-31..09-29 (57 dates 08-01..09-29, 626
market-days). Nothing is scored for a decision; no new candidate.

Vectors (all with the 81a floor mask and served fallback):
- **served** = what ran; every dev date is pre-#191 (PR #191 landed 2026-10-06), so "served before #191" is the
  whole table and there is no observed post-#191 serving on these dates.
- **r1 (post-#191 emulation)** = the v2 swarm ladder rung 1 = registered rule d-defect-r2 (S1 heuristic + S2 learned
  late-day lock-in restored on the served final bands, production constants, anchor
  `max(history_max, guidance_floor)` per EF §10q, not the v3 anchor #191 actually serves). Rebuilt with
  `ladder_parity` / `d_defect_evening_stage` unchanged; its per-snapshot Brier equals the swarm's saved
  `C:\swarm\out\ladder\snapb_ladder-r1.npy` exactly (max |diff| 0.0 over 110,807 snapshots).
- **MG-1-like** = the HARNESS v3 arm; **c1** = the ladder's MG-1 read in H = max(B, X) form; **r2** = ladder rung 2
  (c1 where covered + the restored lock-in), equal to `snapb_ladder-r2.npy` exactly (max |diff| 0.0).
- Tail = band rows with served SE > market SE and |p_served − p_market| >= 0.30: 74,046 rows (6.075%) carrying
  70.38% of the positive excess, as before. Band position: **winner**, **adjacent** (one band from the winner),
  **far** (two or more). "Share" = share of all tail excess unless stated; "removed" = share of the tail excess on
  those rows that the vector removes, with a cell-clustered crossed W 95% interval.

### 11.1 Re-split: hour block x market x band position

By position: winner 62.2% (tail on 34.2% of winner rows), adjacent 25.1% (9.9%), far 12.7% (1.6%).

| Block | winner | adjacent | far | block total |
| --- | --- | --- | --- | --- |
| 00-05 | 14.1% | 3.5% | 4.6% | 22.2% |
| 06-09 | 11.0% | 2.6% | 3.3% | 16.9% |
| 10-12 | 7.7% | 2.4% | 2.1% | 12.1% |
| 13-16 | 9.7% | 5.2% | 1.4% | 16.3% |
| 17-23 | 19.7% | 11.4% | 1.3% | 32.4% |

Largest block x market cells: 17-23 Los Angeles 6.7% (tail rate 13.2% of its rows), 00-05 Los Angeles 4.4%, 17-23
Dallas 3.8%, 17-23 Denver 3.6%, 00-05 Dallas 3.4%, 06-09 Los Angeles 3.3%, 17-23 NYC 3.1%, 17-23 Austin 3.0%, 17-23
Chicago 3.0%, 00-05 Chicago 2.8%. Largest block x market x position cells: 17-23 Los Angeles winner 3.7% (72% of
those winner rows are in the tail), 17-23 Los Angeles adjacent 2.9%, 00-05 Los Angeles winner 2.7%, 00-05 Dallas
winner 2.5%, 17-23 Denver winner 2.3%, 17-23 Dallas winner 2.2%. Los Angeles carries the most tail in every block.

### 11.2 Before vs after #191 (17-23, emulated)

All dev snapshots are pre-#191. The emulated post-#191 lock-in (r1) **removes 85.9% [80.5, 90.3] of the 17-23 tail
excess** (26,229 tail rows; the lock-in is active on 96.5% of them); r2 (adding the MG-1 read) removes 89.5% [82.8,
93.9]. By position: winner 86.0%, adjacent 85.9%, far 84.3%. By hour: 17 h 63.9% [47.8, 79.0], 18 h 79.1%, 19-23 h
90.0-92.4%. By market: San Francisco 96.5%, Houston 95.3%, Chicago 90.4%, Los Angeles 88.7%, Denver 87.9%, Austin
87.2%, Atlanta 84.1%, Miami 83.2% [49.2, 97.1], Dallas 79.5%, NYC 76.7%, Seattle 71.8% [64.3, 76.9]. So roughly a
third of the whole tail (32.4% x 0.86 ≈ 28% of all tail excess) is the evening serving defect that #191 fixes,
assuming the v3 anchor acts like the emulated one; a host read of post-#191 served vectors would confirm it.

### 11.3 Attribution of the 00-16 tail (67.6% of all tail excess)

Share of the block's tail excess removed:

| Block (share of all tail excess) | floor mask only | MG-1-like | c1 | lock-in r1 | r2 (c1 + lock-in) | residual after r2 |
| --- | --- | --- | --- | --- | --- | --- |
| 00-05 (22.2%) | 0.2% | 77.4% [68.3, 84.6] | 77.4% | 0.2% | 77.4% [68.3, 84.8] | 22.6% |
| 06-09 (16.9%) | 0.2% | 75.3% [68.0, 82.0] | 75.4% | 0.2% | 75.4% [68.2, 82.3] | 24.6% |
| 10-12 (12.1%) | −0.1% | 70.0% [62.3, 76.7] | 70.0% | −0.1% | 70.0% [62.1, 76.9] | 30.0% |
| 13-16 (16.3%) | 0.5% | 51.7% [42.6, 60.1] | 57.2% | 2.6% [0.6, 4.6] | 58.2% [49.8, 65.9] | 41.8% |
| **00-16 (67.6%)** | 0.2% | **69.3% [61.8, 75.9]** | 70.7% | 0.7% | **70.9% [64.0, 77.6]** | **29.1%** |

Point decomposition of 00-16: floor mask 0.2%, NBM read (MG-1-like beyond the floor) 69.1%, c1 form over MG-1-like
1.4% (all in 13-16: 5.5%), lock-in on top of c1 0.2% (13-16: 1.0%), residual 29.1%. The ~69% NBM share is confirmed
in every block (77/75/70/52%) and every market: MG-1-like removes 50.7% (San Francisco) to 87.2% (Miami) of each
market's 00-16 tail excess (Atlanta 59.6, Austin 66.6, Chicago 76.7, Dallas 77.3, Denver 63.4, Houston 62.4, Los
Angeles 73.0, NYC 51.9, Seattle 67.2%). Floor and lock-in stages remove almost nothing before 13 h; NYC is the only
market where the floor mask alone removes a visible share (3.6%).

### 11.4 The residual tail after MG-1 + restored lock-in (r2)

Re-defining the tail on r2 itself (r2 SE > market SE and |p_r2 − p_market| >= 0.30): **25,514 rows (2.09%) carrying
42.2% of r2's positive excess**; its excess is 32.4% of the served tail's. Who owns it:
- **Hours:** 13-16 39.8% (tail rate 4.9%; 15-16 h alone 23.5%), then 17-23 15.7%, 00-05 15.3%, 10-12 15.2%, 06-09
  14.1%. Every market's 13-16 cell is in the top 15 (San Francisco 4.7%, NYC 4.1%, Denver 3.9%, Dallas 3.9%, Miami
  3.6%, ...); outside 13-16 the largest cells are Los Angeles 00-05 3.6%, 10-12 3.1%, 06-09 3.0% and Dallas 00-05 2.7%.
- **Markets:** Los Angeles 14.2%, Dallas 12.2%, Denver 10.6%, NYC 10.3%; Houston lowest at 5.5%.
- **Position and direction:** 72.5% is the winner band with r2 **below** the market; the rest is r2 over-weighting
  adjacent (17.6%) or far (9.9%) losing bands. r2 never sits above the market on a winner tail row.

**Do non-NBM captured columns on the workstation correlate with it?** (00-16 snapshots, Spearman; "market gap" =
market centre − r2 centre, "settled gap" = settled high − r2 centre, band-midpoint centres; "baseline" = the same
column shuffled within market x block, seed 20261020.)

| Column | vs market gap (baseline) | vs settled gap (baseline) | sign agrees with market gap when |x| >= 1 °F | 13-16: vs settled gap |
| --- | --- | --- | --- | --- |
| `hrrr_high` − r2 centre | +0.46 (−0.03) | +0.30 (0.00) | 74% | +0.30 |
| `forecast_high` − r2 centre | +0.50 (−0.04) | +0.26 (0.00) | 77% | +0.34 |
| `nws_grid_high_raw` − r2 centre | +0.33 (−0.04) | +0.18 (+0.01) | 71% | +0.02 |
| `hrrr_high` − v2_mean | +0.47 (+0.05) | +0.29 (0.00) | 72% | +0.36 |
| `forecast_high` − v2_mean | +0.48 (+0.09) | +0.23 (−0.01) | 74% | +0.39 |
| r2 centre − floor | −0.13 (+0.07) | −0.05 (+0.06) | — | **−0.53** |
| `v2_age_hours` | −0.09 (−0.10) | −0.12 (−0.12) | — | −0.07 |

Reading, with caveats: where captured HRRR and the served consensus `forecast_high` disagree with the NBM-centred r2,
the market and the settled high tend to sit on their side (correlations +0.2 to +0.5, shuffled baselines near 0).
In 13-16 the strongest signal is r2's centre sitting far above the floor when the high ends lower (−0.53 with the
settled gap): r2 still expects a remaining rise the afternoon does not deliver. These are descriptive. The shuffled
baseline is weak (it scrambles day-to-day temperature, not only the shared r2 term), and every column here was already
tested as a source: HRRR (t8-c2, t9-c2), `forecast_high` and NWS grid (t15-r1..r4, t12-r1/r2), and all three
together with v2 in the fitted EMOS t18-r1 (EF §10q: fitted forms differ from MG-1 "by spread modelling on captured v2,
not by a source", RV-1 − MG-1 00-16 −0.0034 [−0.0078, +0.0007]). The 13-16 remaining-rise pattern is the t3-r3 family
(EF §10q; fragile, WEAK at +1 h staleness).

**Prereg-only candidates for the template (not scored; each overlaps a registered family, cited):**
- **P-T1 (13-16 remaining-rise cap):** in 13-16, shrink r2's mass above the floor bucket by the station x hour
  historical remaining-rise distribution (IEM METAR history <= 2026-07-31). Family t3-r3 / D2 draft; must carry
  t3-r3's staleness sensitivity (t3-r3s) and the D2 power caveat.
- **P-T2 (consensus disagreement re-centre, 00-16):** when |`forecast_high` − v2_mean| >= 1 °F and `hrrr_high` agrees
  in sign, move the MG-1 centre a fixed fraction (declared in the prereg, not fitted on these dates) toward their
  mean. Family t18-r1 / RV-1; the prereg must state its paired increment over MG-1 as the primary estimand.
- **P-T3 (Los Angeles overnight/morning):** LA owns the most residual tail outside 13-16 (00-12). A per-market
  question, not a rule: what LA's marine-layer days look like in captured inputs (EXHAUSTION_REGISTER S27 marine
  data is dark since 2026-06-13) — a capture question before any candidate.

## Update when

Never rewrite this record after the A1 list is frozen; add a dated follow-up instead.
