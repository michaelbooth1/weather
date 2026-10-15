# R-T5-INC: targeted refuter for T5 (t5-r1, NBH latest cycle, remaining-hours max). Development only.

(Written to disk by the orchestrator from the agent's returned text; the agent's own write was blocked by a tool guard.)

## Verdict: **T5-00-16 INCREMENT-NULL** (PIT clean; T5's 00-16 gain does not survive as an increment over the captured NBM v2_mean)

- **PIT: no defect.** 0 of 110,103 snapshot-cycle uses came before the object's S3 LastModified. All 85 HEAD re-checks match the manifest. The LEAD classes do not change at LastModified + 15 min or + 60 min.
- **Increment: null in 00-16.** Paired T5 − c1 in 00-16 is **+0.0027 [−0.0037, +0.0098]** (from stratum, all rows), 5/11 markets negative; before stratum **+0.0044**. Wrong sign, so it fails every LEAD condition. The captured v2_mean control (c1) alone scores **−0.0100 [−0.0179, −0.0035]** against served in 00-16, compared with T5's **−0.0073**, so **c1 carries 137% of T5's 00-16 gain** [57%, 567%] (W ratio of sums; before stratum 158%). In 00-05, 06-09 and 10-12, T5 is worse than v2_mean (+0.0055 to +0.0069; the 00-05 both-covered interval excludes 0 on the harm side).
- **Where T5 does add over v2_mean:** **13-16 −0.0092 [−0.0164, −0.0019]** (10/11; before −0.0071 [−0.0163, +0.0015]; classifier LEAD) and **17-23 −0.0364 [−0.0451, −0.0282]** (11/11). Both come from the remaining-hours form, which collapses mass to the floor once the high is in. That is the T1/T2 decided-band family, and NBH guidance skill is not shown to be the cause. For 13-16 the attribution is unverified.

HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. Rows after 2026-09-29: 0. Leakage tripwire: none. Reproduction of T5's own score file is exact (00-16 −0.0072953, 17-23 −0.0282341, 13-16 −0.0097060).

Registered before scoring: `r-t5-inc-c1` (control), `r-t5-inc-p1` (paired T5 − c1), `r-t5-inc-d1` (PIT stress diagnostic), `r-t5-inc-d2` (c1 on T5-covered rows, diagnostic).

## Check 1: PIT per cycle

- **Manifest integrity:** `available_utc` in `nbh_tidy.parquet` equals the ledger's `s3_last_modified` for all 1,608 cycles.
- **HEAD re-verification:** 85 requests (3 random dates per cycle hour 00-23, seed 20261004, plus all of 2026-09-24 00-12Z): 0 mismatches in Last-Modified or ETag, all 200. The 09-24 late objects are confirmed (00Z uploaded 14:17:11Z, +857 min; 12Z 16:10:12Z, +250 min).
- **Use vs LastModified:** 110,103 snapshot-cycle uses, all from the latest eligible cycle, 0 fallbacks, **0 uses before LastModified**. The 09-24 00-12Z station-cycles were never used: newer 13Z+ cycles were already available when they landed.
- **First use minus LastModified per cycle hour:** minimum 0.0-0.1 min, median 3.6-6.0 min, 90th percentile 7.4-8.7 min, maxima 9.2-51.7 min (snapshot gaps). Full table in `result.json` (`pit.first_use_minus_lastmodified_by_cycle_hour`).

T5 re-scored with later availability (from stratum, all rows, candidate − served):

| Block | LM + 0 | LM + 15 min | LM + 60 min | Class (0 / 15 / 60) |
|---|---|---|---|---|
| 00-05 | −0.0073 [−0.0140, −0.0006] 8/11, b −0.0064 | −0.0072 [−0.0139, −0.0008] | −0.0064 [−0.0123, −0.0006] | LEAD/LEAD/LEAD |
| 06-09 | −0.0084 [−0.0149, −0.0015] 9/11, b −0.0094 | −0.0083 [−0.0148, −0.0015] | −0.0082 [−0.0144, −0.0016] | LEAD/LEAD/LEAD |
| 10-12 | −0.0029 [−0.0104, +0.0053] 7/11 | −0.0029 | −0.0029 | WEAK |
| 13-16 | −0.0097 [−0.0195, −0.0010] 9/11, b −0.0087 | −0.0097 [−0.0195, −0.0009] | −0.0096 [−0.0194, −0.0008] | LEAD |
| 17-23 | −0.0282 [−0.0400, −0.0188] 11/11, b −0.0320 | −0.0282 | −0.0282 | LEAD |
| **00-16** | **−0.0073 [−0.0136, −0.0009]** 8/11, b −0.0077 | −0.0073 [−0.0135, −0.0009] | −0.0069 [−0.0129, −0.0008] | LEAD |

Coverage: 109,399 at LM + 0; 109,177 at + 15 min; 106,079 at + 60 min (730 snapshots have no floor). No disqualifying PIT defect.

## Check 2: increment over the captured NBM v2_mean

c1 (`r-t5-inc-c1`) has exactly t5-r1's form: centre = captured `v2_mean`, sigma = max(captured `v2_stddev`, 1), X ~ N(mu, sigma) integer-discretised, H = max(B, X) with B the rule-4 floor bucket; eligible only when `v2_available_at` <= `captured_at_utc` (asserted), otherwise served. Coverage 99.34% (T5 98.73%; every T5-covered row is c1-covered). Zero parameters, already-captured information only.

| Block | T5 − served | c1 − served | **T5 − c1 (paired)** | mkts neg | before T5 − c1 | Increment class | c1 share of T5 gain |
|---|---|---|---|---|---|---|---|
| 00-05 | −0.0073 [−0.0140, −0.0006] | −0.0142 [−0.0234, −0.0068] 11/11 | **+0.0069 [−0.0000, +0.0145]** | 2/11 | +0.0088 [+0.0013, +0.0172] | NULL (wrong sign) | 196% |
| 06-09 | −0.0084 [−0.0149, −0.0015] | −0.0139 [−0.0228, −0.0062] 11/11 | **+0.0055 [−0.0018, +0.0139]** | 5/11 | +0.0082 [+0.0000, +0.0169] | NULL | 166% |
| 10-12 | −0.0029 [−0.0104, +0.0053] | −0.0091 [−0.0162, −0.0027] 10/11 | **+0.0062 [−0.0018, +0.0152]** | 5/11 | +0.0063 | NULL | 316% |
| 13-16 | −0.0097 [−0.0195, −0.0010] | −0.0005 [−0.0092, +0.0077] 3/11 | **−0.0092 [−0.0164, −0.0019]** | 10/11 | −0.0071 [−0.0163, +0.0015] | LEAD (classifier) | 5% |
| 17-23 | −0.0282 [−0.0400, −0.0188] | +0.0082 [−0.0078, +0.0205] 1/11 | **−0.0364 [−0.0451, −0.0282]** | 11/11 | −0.0340 | LEAD (decided-band family) | −29% |
| **00-16** | **−0.0073 [−0.0136, −0.0009]** | **−0.0100 [−0.0179, −0.0035]** 10/11 | **+0.0027 [−0.0037, +0.0098]** | **5/11** | **+0.0044 [−0.0029, +0.0116]** | **NULL (fails all 4)** | **137% [57%, 567%]** |
| all | −0.0133 [−0.0204, −0.0065] | −0.0048 [−0.0145, +0.0031] | −0.0085 [−0.0152, −0.0017] | 9/11 | −0.0068 | LEAD (carried by 13-23) | 36% |

- Pooled 00-16 increment: +0.0034 [−0.0011, +0.0082].
- LEAD conditions on the 00-16 increment all fail: interval includes 0; estimate positive (misses −0.0133 and the 5%-of-gap bar −0.0012); both strata positive; 5/11 markets negative.
- Per-market 00-16 increment (from): negative ATL −0.0044, AUS −0.0044, DAL −0.0036, NYC −0.0096, SFO −0.0034; positive CHI +0.0028, DEN +0.0060, HOU +0.0045, LAX +0.0131, MIA +0.0176, SEA +0.0114. Before stratum: 4/11 negative.
- Both-covered rows (secondary, selected on availability): +0.0025 [−0.0041, +0.0098]; d2: +0.0027 [−0.0037, +0.0096]. Coverage differences do not explain the result.

## Conclusions

1. T5's 00-16 LEAD (−0.0073) is real against served and PIT-clean, but **not an increment over the captured NBM v2_mean** (v2_mean carries ~137%; in 00-12 NBH is worse than v2_mean in the same form). The morning claim reduces to the T7 c1 finding: the served model under-uses its own captured v2 guidance — a zero-parameter serving stage, no NBH capture needed.
2. Surviving increments are 13-16 (−0.0092) and 17-23 (−0.0364), probably the remaining-hours / decided-band mechanism rather than NBH content; 13-16 attribution unproven (follow-up: 13-14 vs 15-16 split, or T5 − T1/T2 paired increments).
3. Retire "NBH capture is needed for the 00-16 gain". An NBH capture-cost case would have to rest on 13-16/17-23 beating the T1/T2 family, which nothing here establishes.

Files: `C:\swarm\out\r-t5-inc\result.json`, `head_verify.json`, `t5_r1_lag{0,15,60}.score.json`, `r-t5-inc-c1.score.json`. Code: `tools/research/model_parity/r-t5-inc_refute.py`, `r-t5-inc_head_verify.py`.
