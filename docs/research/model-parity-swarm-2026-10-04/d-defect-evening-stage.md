# D-DEFECT: the evening loss is a serving-path defect (development only)

(Written to disk by the orchestrator from the agent's returned text; the agent's own write was blocked by a tool guard.)

## Verdict: DEFECT-CONFIRMED by code trace and by the shape of the served output. One served payload still has to be read.

**The defect.**
- All five late-day lock-in stages and the calibration taper depend on the WU printed history. That input has been empty since `PAID_WEATHER_PROVIDER_ACCESS_ENABLED = False` (`src/weather/model/model_constants.py:19`, 2026-06-30).
- So every lock-in strength is 0, and the overconfidence calibration's evening temperature (1.0-1.3) is applied untapered, which flattens the distribution and pushes mass back above the high.
- The captured inputs already hold a substitute anchor (`guidance_physical_floor`, the observed METAR maximum) and a current reading (the METAR temperature).

**The emulation.** Fed these inputs, with production code and constants unchanged, the restored stage closes 71% (S1 alone) to 85% (S1+S2) of the from-stratum 17-23 served-market gap. All 11 markets are negative, both strata agree, and 00-16 is unchanged.

**What is not yet proven.** The 111h table has no stage metadata, so a served `lockin_strength` of 0 is inferred, not read. Consistent facts: `trusted_current_max` is null on all 110,807 rows (`feature_store.py:396-399` returns `None` exactly when WU history is missing); served keeps 0.341 of its probability above the floor band in 17-23, whereas at the strengths computed here (mean 0.81-0.93) that mass would be 0.06-0.11.

**One read settles it:** `component_payload.lockin_strength` and `high_has_stood_lockin.stage_attribution` from any captured evening snapshot.

### Production payload evidence (added 01:45 local, read by master-agent on the capture host)

master-agent read one real served payload on production, read-only, from a closed day:
`data\snapshots\highest-temperature-in-atlanta-on-september-20-2026\components.jsonl`, last snapshot
`20260920T235554` (23:55 local). Probability on the running-high band 88-89 °F after each stage:

| Stage | P(88-89 °F) |
| --- | --- |
| post_live_signals | 0.845 |
| current_observed_floor | 0.969 |
| wu_floor_residual | 0.969 |
| settlement_lag_adjusted | 0.969 |
| late_day_lockin | 0.969 (unchanged: **no-op**) |
| pre_calibration | 0.969 |
| overconfidence_calibration | 0.913 |
| final | 0.913 |
| market | 0.9995 |

The bands above the running high hold 0.031 before calibration and **0.087 after**, so at 23:55 the S7 calibration
re-spreads mass above the high. This confirms the defect on a served payload: `late_day_lockin` is a no-op, and the
untapered overconfidence calibration pushes mass back above a high that is already in. This is a single-snapshot
read and was not scored; the table-wide numbers below remain development emulations.

### Production multi-payload evidence (added 2026-10-04 morning, read by master-agent on the capture host)

A descriptive read: read-only, closed days only, development, no scoring.
- **Method:** the last snapshot at or after 21:00 local in `components.jsonl`, for 11 markets × 3 dates (2026-08-12,
  09-14, 09-27): 33 snapshots. Running-high band = the first band where `current_observed_floor` > 1e-6. Six were
  excluded because the market put more than 0.5 above that band: the captured floor lags the real high there, so the
  mass above it is not a lock-in error. n = 27.
- **`late_day_lockin` is a no-op in all 27:** the maximum per-band change versus `settlement_lag_adjusted` is min
  3.4e-10, median 8.4e-9, max 1.2e-7 (numerical noise).
- **Mean mass above the running-high band:**

  | Stage | Mass |
  | --- | --- |
  | before lock-in (settlement_lag_adjusted) | 0.253 |
  | after late_day_lockin | 0.253 |
  | pre_calibration | 0.253 |
  | final | 0.276 |
  | market | 0.002 |

- This supports the code-trace claim (lock-in strength 0) beyond the single ATL payload. Calibration adds +0.023 in
  the defect state, consistent with the T27 amendment on S7.

Run facts: HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`. Rows after 2026-09-29: 0. Leakage-suspect groups: none. The from stratum was read before, so it is not a holdout.

## 1. EF 10e and where the stages live

- EF 10e's 13-stage list lives in a host-local audit file not in this worktree (`gap-what-production-serves.md`); the evening subset was re-traced from code.
- Serving path: `TorontoModel.build` (`toronto_model.py:303`) → `_estimate_distribution_result` (`model_distribution.py:139`). Model v0.5.10 HGBC on all rows; `residual_distribution_v1` is shadow only; `model_stage_retirement.py` is a non-mutating gate, so `late_day_lockin` is still called.
- How the empty input spreads: `history = wu_history` is empty (`:147`); `history_max = history_high` is WU-only, so `None` (`:183`, `model_base.py:58`, `:120`); the station fallback exists only in `effective_observed_high` (`model_base.py:78-80`), which feeds the `high_so_far` feature and the hard floor, not the lock-in; `trusted_current_max` is `None`; `observed_bucket` is `None` (`:285`); `guidance_floor` (`:217`, built by `model_features.py:222-252`, the METAR rows maximum) **is** populated but used only for guidance physical-validity checks.

## 2. The no-op stages

| # | Stage | file:line | Needs | Gets now | What it does if fed |
|---|---|---|---|---|---|
| S1 | heuristic lock-in | `model_distribution_signals.py:377`, `:880` | `history_max`, current reading | `None` → 0.0 (line 382) | Ramp 15→17h × drop 0-3.6 °F. At strength 1 keeps 5% at +1, 0.75% at +2, then ×0.15 per degree. |
| S2 | learned lock-in | `:408` | `wu_history` max + `max_times`; per-market revision-up rate | 0.0 | From 17h once the high has stood 90 min: strength = 1 − rate (~0.9 at 17h, >0.98 from 19h). |
| S3 | high-has-stood | `:476` | same + >= 2 remaining forecasts | 0.0 | 1.0 in 13-15h. |
| S4 | expanded lock-in | `:581` | same | 0.0 | 15-19h, 0.25-0.85. |
| S5 | standing-high partial | `:709`, `:904` | same + official METAR | 0.0 | 13-19h, at most 0.55. |
| S6 | late-day continuation | `model_distribution.py:1128` (gate `:1149`) | `observed_bucket` | skipped | Blends the continuation tail with weight 0.35-0.45 from 15h. |
| S7 | calibration taper | `:540-546`, `calibration_runtime.py:351-383` | `lockin_strength` | 0 → full temperature | Fed: temperature tapers to 1. Unfed: evening temperature 1.0-1.3 flattens the distribution. |

Wiring: served strength = `max(S1..S4)`; S5 runs only when that maximum is 0 (`:1245-1283`).

## 3. Restorable from captured data?

Yes for S1, S2, S7; partly for S3-S5.
- Anchor: `guidance_physical_floor` (captured every snapshot, computed in serving; >= `high_so_far` wherever both present, 0.9934 of rows; the rest have no floor).
- Current reading: `metar_temp`, already passed to the stage (`:520-534`); not in the 111h extract, so T1's PIT METAR join was used (valid + 10 min, COR excluded, audited by the T1 refuters).
- High-first-reached time: derivable from captured METAR rows; here, the first earlier snapshot of the market-day at the current floor bucket.
- S3-S5 also need remaining hourly forecast rows (not emulated).
- Parity: HGBC was trained while WU was live, so restoring these post-processing stages moves serving back toward training; feature parity untouched.
- Rule 3: revision-up and calibration artifacts generated 2026-07-07 from June-early July data, before 07-31.

## 4. Scores on the 111h table (development; all-row primary estimand)

Registered: d-defect-r1 (restore S1, production constants, anchor B = round_half_up(81a floor), PIT METAR reading, applied to served final bands uniform within band, served fallback); d-defect-r2 (r1 + S2); d-defect-d1 (unconditional collapse diagnostic; reproduces refute-stat-t1 exactly, −0.02870 / −0.03285); d-defect-d2/d3 (T5 attribution diagnostics, §7).

**17-23:**

| Rule | Class | cand − served, from [95%] | before | cand − market, from [95%] | gap closed | markets − | tail excess removed |
|---|---|---|---|---|---|---|---|
| served | — | 0 | 0 | +0.0298 | 0% | — | 0% |
| r1 (restore S1) | LEAD | −0.0213 [−0.0308, −0.0138] | −0.0248 | +0.0085 [+0.0048, +0.0132] | 71% | 11/11 | 70% [58, 80] |
| r2 (restore S1+S2) | LEAD | −0.0254 [−0.0353, −0.0175] | −0.0296 | +0.0044 [+0.0021, +0.0077] | 85% | 11/11 | 84% [78, 91] |
| d1 (unconditional collapse) | LEAD | −0.0287 [−0.0404, −0.0194] | −0.0328 | +0.0011 [+0.0000, +0.0035] | 96% | 11/11 | 97% |
| t3-r3 (information rung) | LEAD | −0.0219 [−0.0327, −0.0131] | −0.0254 | +0.0079 | 74% | 11/11 | 85% |
| t1-r2 (decided band) | LEAD | −0.0264 [−0.0379, −0.0175] | −0.0295 | +0.0034 | 89% | 11/11 | 89% |

Mass above the floor band per 17-23 snapshot: served 0.341, r1 0.113, r2 0.063, market 0.012, realised 0.006.
Stage strength in 17-23: S1 positive on 94% of snapshots and >= 0.95 on 69%; with S2: 97% and 86%.

**00-16:** r1/r2: 00-05 −0.0001, 06-09 +0.0000, 10-12 +0.0001, 13-16 −0.0008 [−0.0017, +0.0002] → WEAK. t3-r3: −0.0010 / −0.0021 / −0.0041 / −0.0116 (13-16 LEAD) → 00-16 WEAK.

Restoring S1 alone reproduces t3-r3 in 17-23; S1+S2 beats t3-r3 and comes close to T1. d1's extra 0.003 comes from the stage's deliberate 5% one-up hedge (realised 0.6%) and the uniform-within-band approximation. The refuter's unconditional result therefore means the evening loss is the missing lock-in, not an information gap.

## 5. Fix shape and the 81a floor

**PROPOSAL ONLY — the serving fix is an owner decision (morning of 2026-10-04); nothing has been changed.**

**Two parts, both required** (amended after the production payload read):
1. Restore the lock-in (S1/S2, with S6) by re-anchoring, as below.
2. **Gate S7:** the overconfidence-calibration taper must not re-spread mass onto bands above `lockin_high`. Even a
   correctly fed lock-in is partly undone if calibration re-flattens afterwards: the payload shows calibration moving
   the above-high mass from 0.031 to 0.087 at 23:55. Gate calibration so bands above `lockin_high` receive no mass
   beyond what the lock-in left, or apply calibration only within the at-or-below-high support.

**Amendment (T27, 2026-10-04 about 04:00 local; S-REVISE).** Part 2 is corrected: the S7 gate is **not required**.
The taper reads the same `lockin_strength` (`model_distribution.py:544`), so restoring the strength restores the taper,
and at strength 1 calibration is the identity. Across 17-23 untapered calibration would add 0.0098 above the high, the
production taper adds 0.0011, and a gate removes that last 0.0011 for −0.00008 Brier (helpful, negligible). The 23:55
payload's 0.031 → 0.087 is the s = 0 defect state itself, not evidence that a restored lock-in needs a gate. The
required condition is that the restored strength reaches the taper; an explicit S7 gate above `lockin_high` is
optional. The payload evidence above stands. See `t27.md` §3.

**Restore S1, S2, S7 (and S6) by changing their anchor, not their logic.** In `distribution_late_day_lockin_stage` (`model_distribution.py:1176`) use `lockin_high = max(history_max, guidance_floor)` (= the 81a floor value F while `trusted_current_max` is null); take `max_times` from METAR rows when WU rows are empty; current reading unchanged. S6 gates on the same anchor; S7 follows automatically (taper reuses `lockin_strength`). Alternative: replace S1-S5 with one evening collapse onto the floor band — a new rule needing its own pre-registration.

**Interaction with the 81a floor mask** (max of `guidance_physical_floor`, `high_so_far`, `trusted_current_max`): on this table the floor is in effect `guidance_physical_floor`. Both act on bucket B = round_half_up(F): the floor removes mass below B, the lock-in shrinks mass above B, and as strength → 1 they collapse onto B's band. They never conflict and the floor is never weakened; anchoring on F keeps both on one value. Serving order: lock-in (`:518`), then calibration, which zeroes buckets below `hard_floor_bucket` (`calibration_runtime.py:368-372`). Serving's `hard_floor_bucket` (`:290-302`) does not include `guidance_floor`, so the 81a floor is the stricter of the two.

**Serveability:** zero-parameter serving stage, no new capture; still needs the payload read and the release gate. No serving or config change was made.

## 6. Caveats
- The emulation is post-hoc on the final bands. In serving the lock-in runs before calibration and the taper would remove the softening, so a faithful replay through `estimate_distribution` on captured inputs would likely score at least as well; that replay is the confirmation step.
- The first r2 run had an alignment bug (strength arrays combined after a sort); fixed and re-run under the same registered rule; earlier output overwritten.
- S3-S5 not emulated.

## 7. Addendum: is NBH's 13-16 increment over v2_mean the same mechanism?

Paired T5 − c1 at 13-16 reproduces R-T5-INC: −0.0092 [−0.0164, −0.0019].

| Comparison | 13-14 | 15-16 |
|---|---|---|
| T5 − c1 (from) | +0.0002 [−0.0076, +0.0083] | −0.0185 [−0.0260, −0.0109], 10/11 |
| T5 − c1 (before) | — | −0.0136 [−0.0231, −0.0047] |
| restored S1+S2 − served | −0.0002 | −0.0014 [−0.0026, +0.0000] |
| T1-r2 − served | 0 | −0.0072 [−0.0133, −0.0022] |
| T5 − T1-r2 | −0.0076 (n.s.) | −0.0050 [−0.0105, +0.0009], 10/11 |
| T5 − restored S1+S2 | — | −0.0108 [−0.0182, −0.0037] |

At 15-16 by T5's state (collapsed = NBH remaining max below the floor bucket; 65% of 15-16 rows): collapsed −0.0097 [−0.0168, −0.0033]; open −0.0088 [−0.0140, −0.0042].

Answer: same family (upper-side truncation once the peak is passing, concentrated in 15-16) but not the evening defect. S1+S2 recover almost none of it (S1 is 0 at 15h, 0.5 at 16h). Half sits on rows where NBH's remaining max is still >= the floor (truncating past hours, possibly some NBH content). T5's edge over T1-r2 at 15-16 is not significant. The 13-19h defect stages S3-S5 (need remaining hourly forecasts) are the untested restoration candidates for this piece.

Files: `C:\swarm\out\d-defect\` (d_defect_{r1,r2,d1}.score.json, d-defect-{r1,r2,d1}.md, result.json, t5_attribution.json, run.log, t5_attr.log). Code: `tools/research/model_parity/d_defect_evening_stage.py`, `d_defect_t5_attribution.py`.
