# LADDER: the parity ladder from no-source controls (development only)

All numbers are development reads. The from stratum (2026-08-23..09-29) was already read by 79a/81a/111h, so it
is not a holdout (rule 7).

Run checks:
- HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.
- Rows with a target after 2026-09-29: 0.
- Leakage-suspect groups: none.
- Nothing was tuned, and no hour gate was chosen or scored (rule 8).

## Headline

**Two zero-parameter serving-stage fixes take the all-hours served/market Brier ratio from 1.73x to 1.34x.** Both
use only inputs that production already captures.
- From stratum: 1.73x to 1.34x. Pooled: 1.768x to 1.328x.
- Together they close 54% [35, 70] of the original served − market excess.

**What remains after rung 2:**
- All hours: +0.0119 [+0.0085, +0.0155] above the market.
- 00-16: 1.29x (+0.0141).
- **13-16 is the largest residual block.** It is unchanged at 1.81x (+0.0231 [+0.0173, +0.0289]) and holds 32%
  of the residual excess.
- 00-05, 06-09 and 10-12 remain at 1.18-1.26x.
- 17-23 remains at +0.0063.

**Rung 1 (= d-defect-r2)** closes 85% [76, 92] of 17-23: −0.0252, 11/11 markets. 00-16 is unchanged.

**Rung 2 (MG-1 r-t5-inc-c1 with the lock-in on top)** closes 58%, 55% and 40% of 00-05, 06-09 and 10-12. Its net
effect on 13-16 is −0.0002 [−0.0086, +0.0077], because two effects cancel:
- It helps 13-14: −0.0075, 8/11 markets.
- It hurts 15-16: +0.0068 [−0.0009, +0.0146], 2/11 markets. This is stale whole-day guidance (EF 10p).

**The 13-16 residual is mostly a 15-16 truncation, and it needs no source.**
- t3-r3, the captured-METAR remaining-rise rung, beats rung 2 at 15-16 by −0.0181 [−0.0251, −0.0112], 11/11
  markets (before stratum −0.0145).
- No external source beats t3-r3 at 15-16.

**Only one source shows a possible increment over rung 2:** the MOS/NBE consensus t7-r2 at 13-14, −0.0063
[−0.0119, −0.0006], 10/11 markets (before stratum −0.0059). Against t3-r3 it is −0.0031 [−0.0077, +0.0017].

**The 17-23 residual comes from the lock-in itself, not from calibration re-spread.** Its sources are the 5% hedge
and partial lock-in strength. The S7-gate variant changes almost nothing: r1b − r1 is +0.0004 [+0.0001, +0.0010].

**Answer to "can free data reach parity?" (development):**
- Free data that is already captured reaches about 1.2x in the morning and close to the market in the evening.
  It needs two serving repairs and no new source.
- A no-source METAR remaining-rise stage at 15-16 would close most of the afternoon residual. Composing it into
  the ladder is a pre-registration question only (rule 8).
- None of the ten external sources adds anything beyond the relevant rung. The one exception is the borderline MOS
  result at 13-14. **There is no capture case.**
- Parity is not reached in 00-12. The residual there is +0.010 to +0.014 (ratio 1.18-1.26), and no tested source
  closes it beyond rung 2.

## 1. Rungs (registered 02:16:06, before the first score)

- **ladder-r0:** served, plus the harness floor.
- **ladder-r1:** d-defect-r2, reproduced exactly (17-23 −0.025366, 13-16 −0.000783, 00-16 −0.000198).
  - Strength s = max(S1 heuristic, S2 learned).
  - Anchor B = round_half_up(81a floor).
  - Above B, each band gets the factor (1−s) + s·0.05·0.15^(k−B−1). The factor is applied to the served FINAL
    bands, uniform within a band.
  - Constants and artifacts are production's (2026-07-07).
- **ladder-r1b:** a faithful emulation of restore + S7 taper + S7 gate (section 2).
- **ladder-r2:** declared before scoring. No hour gate.
  - Where r-t5-inc-c1 is covered (v2_mean, v2_stddev, v2_available_at ≤ t, floor), the base is
    N(v2_mean, max(v2_stddev, 1)), with H = max(B, X).
  - Elsewhere the base is served.
  - The rung-1 lock-in is applied on top. It acts only where s > 0.
- **ladder-r2b:** r2 with the fallback rows taken from r1b. It is identical to r2 in every scored cell.

mg1-c1-alone reproduces r-t5-inc-c1 exactly (00-16 −0.010018). c1 covers 99.3% of snapshots. s > 0 holds on
97.1% of 17-23 snapshots, 18.2% of 13-16 snapshots, and none in 00-12.

## 2. Lock-in on the served final bands vs "restore + gate S7"

**Short answer:** applying the lock-in to the served final bands is not equivalent to restoring the lock-in and
gating S7. It is an approximation, and on this table a close one.

**How production orders the stages.**
1. Lock-in.
2. Calibration: a per-bucket power transform p^(1/T). prior_weight is 0 in every artifact.
3. The temperature T tapers to T' = 1 + (T−1)(1−s).

**What each candidate computes.**
- **r1 = L_s(C_T(q)).** It keeps (1−s) + s·hedge of the above-high mass after untapered calibration. Mean T at
  17-23 is 1.16.
- **The fix = Gate(C_T'(L_s(q))).**
- At s = 1 the two differ only in the hedge base.
- At 0 < s < 1, r1 keeps a (1−s) share of the calibration re-spread, which the gate would remove.

**r1b emulates the fix:**
1. Invert the served bands to q_k ∝ (P/width)^T, using the per-market temperature_by_hour[cutoff_hour] and
   assuming mass is uniform within a band.
2. Apply the lock-in.
3. Recalibrate with T'.
4. Cap every band above B at its lock-in output, and give the excess to B's band.

**Result.**
- r1b − r1 at 17-23: +0.0004 [+0.0001, +0.0010] (before stratum +0.0002).
- r1b − r1 elsewhere: about 0.

Mass above the floor band per 17-23 snapshot:

| Source | Mass |
|---|---|
| served | 0.342 |
| r1 | 0.063 |
| r1b | 0.065 |
| r2 | 0.083 |
| market | 0.012 |
| realised | 0.006 |

So the mass left above the high is not residual calibration spread. It comes from the hedge and from rows where
s < 1.

The inversion is approximate. A replay through estimate_distribution is the confirmation step. The serving fix is
an OWNER DECISION, and this is a proposal only.

## 3. The ladder

Conventions for the table:
- From stratum, all-row primary. The before stratum is shown beside it.
- The ratio is not interpretable (n.i.) where market Brier < 0.005.
- Tail = this table's 6.075%/70.38% definition. EF's 4.387%/64.14% comes from a different panel.
- Classes are the harness LEAD classifier applied to candidate − served.

| rung | block | cand − market, from [95%] | before | ratio | gap closed [95%] | marginal vs prev [95%] | mkts −/+ | marg before | tail removed | class |
|---|---|---|---|---|---|---|---|---|---|---|
| r0 | 00-05 | +0.0244 [+0.0162, +0.0341] | +0.0238 | 1.431 | 0% | — | — | — | 0% | — |
| r0 | 06-09 | +0.0254 [+0.0168, +0.0351] | +0.0282 | 1.453 | 0% | — | — | — | 0% | — |
| r0 | 10-12 | +0.0228 [+0.0159, +0.0301] | +0.0260 | 1.436 | 0% | — | — | — | 0% | — |
| r0 | 13-16 | +0.0239 [+0.0179, +0.0304] | +0.0246 | 1.842 | 1% | — | — | — | 1% | — |
| r0 | 17-23 | +0.0296 [+0.0206, +0.0412] | +0.0332 | 35.4 n.i. | 1% | — | — | — | 1% | — |
| r0 | 00-16 | +0.0242 [+0.0176, +0.0318] | +0.0253 | 1.494 | 0% | — | — | — | 0% | — |
| r0 | all | +0.0258 [+0.0194, +0.0339] | +0.0276 | 1.733 (pooled 1.768) | 0% | — | — | — | 1% | — |
| r1 | 00-12 | as r0 | | | 0% | 0.0000 | | | 0% | NULL/WEAK |
| r1 | 13-16 | +0.0233 [+0.0174, +0.0295] | +0.0239 | 1.820 | 3% [−1, 7] | −0.0006 [−0.0010, −0.0003] | 11/0 | −0.0007 | 3% | WEAK |
| r1 | 17-23 | +0.0044 [+0.0021, +0.0077] | +0.0037 | 6.16 n.i. | 85% [76, 92] | −0.0252 [−0.0350, −0.0174] | 11/0 | −0.0295 | 84% [77, 91] | LEAD |
| r1 | 00-16 | +0.0241 [+0.0174, +0.0317] | +0.0251 | 1.490 | 1% | −0.0002 [−0.0002, −0.0001] | 11/0 | −0.0002 | 1% | WEAK |
| r1 | all | +0.0184 [+0.0133, +0.0245] | +0.0189 | 1.524 | 29% [22, 35] | −0.0073 [−0.0102, −0.0051] | 11/0 | −0.0087 | 28% [22, 34] | LEAD |
| r1b | 17-23 | +0.0049 [+0.0024, +0.0082] | +0.0039 | 6.65 n.i. | 84% [75, 90] | −0.0248 vs r0 | 11/0 | −0.0293 | 83% | LEAD |
| r2 | 00-05 | +0.0102 [+0.0056, +0.0149] | +0.0086 | 1.181 | 58% [37, 76] | −0.0141 [−0.0234, −0.0067] | 11/0 | −0.0153 | 76% [67, 85] | LEAD |
| r2 | 06-09 | +0.0114 [+0.0062, +0.0172] | +0.0105 | 1.204 | 55% [33, 75] | −0.0139 [−0.0229, −0.0063] | 11/0 | −0.0177 | 75% [65, 84] | LEAD |
| r2 | 10-12 | +0.0137 [+0.0088, +0.0189] | +0.0123 | 1.261 | 40% [15, 62] | −0.0092 [−0.0164, −0.0027] | 10/1 | −0.0137 | 69% [59, 78] | LEAD |
| r2 | 13-16 | +0.0231 [+0.0173, +0.0289] | +0.0224 | 1.812 | 4% [−36, 33] | −0.0002 [−0.0086, +0.0077] | 2/9 | −0.0015 | 63% [51, 73] | WEAK |
| r2 | 17-23 | +0.0063 [+0.0036, +0.0097] | +0.0039 | 8.30 n.i. | 79% [63, 89] | +0.0018 [−0.0015, +0.0052] | 2/9 | +0.0002 | 88% [78, 94] | LEAD |
| r2 | 00-16 | +0.0141 [+0.0098, +0.0186] | +0.0129 | 1.288 | 42% [19, 62] | −0.0099 [−0.0177, −0.0034] | 10/1 | −0.0122 | 71% [63, 79] | LEAD |
| r2 | all | +0.0119 [+0.0085, +0.0155] | +0.0103 | 1.338 (pooled 1.328) | 54% [35, 70] | −0.0066 [−0.0129, −0.0013] | 10/1 | −0.0085 | 77% [70, 83] | LEAD |

Per-market deltas are in result.json under table.<rung>.<block>.<stratum>.

**The declared composition, stated as found:**
- At 17-23, r2 is slightly worse than r1: +0.0018, not significant. The above-floor mass is 0.083 against 0.063.
- c1 helps 13-14 and hurts 15-16.
- Gating c1 by s or by hour would be an hour gate chosen on this table (rule 8). That belongs only in a Phase-4
  draft.

**Residual after rung 2.** Rung 2 keeps 46% of the original from-stratum excess (38% of the before-stratum excess).
Snapshot-weighted share of the remaining excess, from stratum (before stratum in brackets):

| Block | Share |
|---|---|
| 13-16 | 32% (36%) |
| 00-05 | 22% (20%) |
| 06-09 | 16% (17%) |
| 10-12 | 15% (16%) |
| 17-23 | 15% (11%) |

Inside 13-16:
- 13-14: +0.0190 [+0.0133, +0.0249], ratio 1.49.
- 15-16: +0.0270 [+0.0204, +0.0337], ratio 2.53. Served at 15-16 was +0.0216.

## 4. External sources: paired increment over rung 2

Registration (all before scoring):
- ladder-inc-<id> at 02:19:04.
- ladder-inc-t3 at 02:22:45.
- ladder-inc-vs-t3r3 at 02:27:18.

Method: each source's code was re-run unchanged with its outputs redirected. Every rebuilt candidate reproduces its
agent's own scores against served.

| source | claimed block: minus rung 2 (from, mkts neg, before) | 13-14 | 15-16 | 00-16 | 15-16 minus t3-r3 | verdict |
|---|---|---|---|---|---|---|
| T3 t3-r3 (context, no source) | 13-16 −0.0106 [−0.0166, −0.0051] 11/11 (b −0.0075) | −0.0032 | −0.0181 [−0.0251, −0.0112] 11/11 | +0.0058 | — | closes the 15-16 residual with no new source |
| T5 NBH t5-r1 | 13-16 −0.0087 [−0.0159, −0.0015] 10/11 (b −0.0065); 00-16 +0.0028 [−0.0036, +0.0099] 5/11 | +0.0001 | −0.0176 | +0.0028 | +0.0005 [−0.0042, +0.0055] | nothing beyond rung 2 + t3-r3 |
| T6 NBS r2/r3 | 13-16 −0.0078 / −0.0088; 06-09 +0.0030 / −0.0007 | +0.0014 / −0.0016 | −0.0171 / −0.0159 | +0.0006 / −0.0013 | +0.0010 / +0.0021 | nothing |
| T7 MOS/NBE r1/r2 | r1 06-09 −0.0034 [−0.0084, +0.0012], 10-12 −0.0044 [−0.0094, +0.0002]; r2 00-16 −0.0047 [−0.0092, −0.0004] 10/11 (b −0.0026) | r2 −0.0063 [−0.0119, −0.0006] 10/11 | r2 −0.0174 | −0.0035 / −0.0047 | r2 +0.0006 | borderline; WEAK at most (about 90% is captured-v2, per T7) |
| T8 HRRR SR t8-r2 | 06-09 +0.0060 [−0.0005, +0.0127] 2/11; 13-16 −0.0071 | +0.0015 | −0.0156 | +0.0038 | +0.0024 | nothing |
| T9 HRRR lagged t9-r1 | 06-09 +0.0060 [−0.0008, +0.0133] 2/11 | +0.0011 | −0.0164 | +0.0037 | +0.0017 | nothing |
| T10 ECMWF t10-r2 | 13-16 −0.0080 [−0.0147, −0.0010] 10/11 | +0.0016 | −0.0177 | +0.0032 | +0.0004 | nothing beyond rung 2 + t3-r3 |
| T11 soundings t11-r1 | 17-23 +0.0228 (vs r1 +0.0246) | +0.0079 | −0.0053 | +0.0103 | +0.0127 | nothing |
| T12 NWS revision t12-r1 | 00-05 +0.0127 [+0.0059, +0.0215] 0/11 | +0.0072 | −0.0040 | +0.0092 | +0.0141 | nothing |
| T13 neighbours r3/r2 | 13-16 +0.0004 / −0.0067 [−0.0131, −0.0005] | +0.0069 / −0.0014 | −0.0058 / −0.0119 | +0.0109 / +0.0081 | +0.0122 / +0.0062 | nothing |
| T14 cloud/GOES t14-r4 | 10-12 +0.0080 [+0.0018, +0.0147] 1/11 | +0.0066 | −0.0052 | +0.0096 | +0.0128 | nothing |

**17-23.** Every remaining-hours source beats rung 1 by about −0.003 (t5: −0.0029 [−0.0056, −0.0009]). The
no-source unconditional collapse does the same: d-defect-d1 is −0.0033 beyond r2. So this is the lock-in hedge,
not information from the sources.

**Served-tilt candidates** (T11, T12, T13-r3, T14) carry served's own losses. Their large positive values mean
those losses remain, not that the source adds harm.

## 5. Serveability (proposal only; nothing was changed)

**Rung 1**
- Zero-parameter serving stage with no new capture.
- Re-anchor S1, S2 and S6 on guidance_floor plus METAR max_times, and gate S7.
- This is an OWNER DECISION. It needs the estimate_distribution replay and the release gate.

**Rung 2**
- Zero parameters and no new capture.
- It depends on landing the parser-v2 repair 83a/83b. Production's v1 parser reads tomorrow's minimum after 13Z
  (EF 10k/10l), so this is a versioned train/serve parity change.
- It belongs to the known 79a/81a/111h family (EF 10h/10j/10p).
- It needs a NEW pre-registration on NEW dates. The EF 10j power cap applies: 11 clusters, about 40% power.

**15-16 remaining-rise stage (t3-r3 form)**
- Uses captured METAR.
- Composing it by hour is a Phase-4 draft only.

## 6. Caveats

- 11 market clusters, and this is a development read.
- r1 and r1b are band-level emulations, not replays.
- S3-S5 (13-19h) were not emulated. They are the untested restorations most likely to touch the 15-16 residual.
- Fitted sources carry their own before-stratum and history fits.

## Files

Code: C:\pt\swarm\tools\research\model_parity\ladder_parity.py, with modes rungs, capture <module>, inc and vs_t3.

Outputs in C:\swarm\out\ladder\:
- ladder_*.score.json and mg1_c1_alone.score.json
- rungs.json
- increments.json and increments_vs_t3r3.json
- snapb_*.npy
- cap\
- run.log, inc.log, vs_t3.log and tables.md

Registry ids (17): ladder-r0, ladder-r1, ladder-r1b, ladder-r2, ladder-r2b, ladder-inc-{t3, t5, t6, t7, t8, t9,
t10, t11, t12, t13, t14} and ladder-inc-vs-t3r3.

