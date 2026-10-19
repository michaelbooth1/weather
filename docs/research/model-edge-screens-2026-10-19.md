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
[model-edge-lever5-2026-10-19.md](model-edge-lever5-2026-10-19.md) on `claude/model-edge-codecheck-20261019`.

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

## Update when

Never rewrite this record after the A1 list is frozen; add a dated follow-up instead.
