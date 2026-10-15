# D-RUNG1C: restoring the 13-19h lock-in stages S3-S5 (rung ladder-r1c). Development only.

(The agent's own write of report.md was blocked by a tool guard; this text is result.json report_md.)

## Verdict: NO. Restoring S3-S5 does not recover the 15-16 residual

The evening fix does **not** become a 13-23 fix without a new rule.

**What restoring S3-S5 does at 15-16.** On top of rung 2 it helps, consistently but by a small amount:
- r1c − r2 = −0.0032 [−0.0051, −0.0017], from stratum.
- 11/11 markets are negative, and the before stratum agrees (−0.0042).
- The 15-16 gap to the market only moves from +0.0270 to +0.0238 [+0.0172, +0.0305]. The ratio goes from 2.53x to
  2.35x.

**The no-source METAR rung t3-r3 is still far better.** It beats r1c at 15-16 by −0.0149 [−0.0219, −0.0082]
(r1c − t3-r3 = +0.0149, 0/11 markets favour r1c, before stratum +0.0103). At 13-16 the margin is −0.0087
[−0.0146, −0.0030].

**The other afternoon blocks barely move:**
- 13-14: −0.0007 [−0.0029, +0.0010], 6/11 markets. Not distinguishable from 0.
- 17-23: −0.0001.
- 00-12: exactly 0. The stages are inactive there by their own production hours.

**Why the stages cannot close it.** Each of S3, S4 and S5 requires the current METAR to have rolled at least
0.45 °F below the high. At 15-16, 58% of snapshots have not rolled over, and those snapshots carry 73% of r1c's
15-16 excess, where no stage acts by design. So the 15-16 residual is a remaining-rise problem while the
temperature is still at the high, not a missing lock-in. t3-r3 beats r1c both:
- on snapshots with no stage active: −0.0182 [−0.0264, −0.0104], 11/11;
- on snapshots with a stage active: −0.0146 [−0.0225, −0.0072], 10/11. There, S4's strength (0.25-0.85) is mild
  and the c1 base is stale.

**Proxy dependence.**
- The result depends on a declared forecast proxy, because production's hourly forecast rows are not in the
  extract. It is insensitive to which proxy is used: P2 gives 15-16 −0.0031 [−0.0052, −0.0016].
- With the forecast conditions switched off (diagnostic only), S3 harms 13-14: +0.0052 [−0.0013, +0.0112], 2/11.
  The forecast-ceiling gate is what keeps S3 safe, and even an unblocked stage recovers only −0.0041 at 15-16.

All numbers are development reads. The from stratum (08-23..09-29) was read before, so it is not a holdout.

Run facts:
- HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74.
- Rows with a target after 09-29: 0. Leakage-suspect groups: none.
- Rung 2 rebuilt exactly from ladder_parity (max abs snapshot-Brier difference to snapb_ladder-r2.npy = 0.0).
- Nothing was tuned.

## 1. Registered rule (registered 02:38:26, before the first score)

Three registry ids. Full text and sha256 are in C:\swarm\registry.jsonl.

**ladder-r1c (primary).** Rung 2 exactly, plus three restored stages:
- S3 high_has_stood_lockin_context (model_distribution_signals.py:476).
- S4 expanded_late_day_lockin_context (:581).
- S5 standing_high_partial_lockin_context (:709) with apply_standing_high_partial_lockin (:904).

Constants and wiring are production's:
- Constants: model_distribution_constants.py:144-168, with Celsius deltas × 9/5.
- Hard strength = max(S1, S2, S3, S4), applied with the apply_late_day_lockin retention.
- S5 runs only where that maximum is 0 (model_distribution.py:1245-1283).

Re-anchoring is the same as rung 1:
- lockin_high = max(history_max (None), guidance_floor), which is the harness 81a floor F; B = round_half_up(F).
- max_times[0] comes from PIT METAR (valid + 10 min ≤ t, COR excluded, T1 loader): the first row of the local day
  with round_half_up(tmpf) ≥ B. This held on 91.6% of 13-19 snapshots. Otherwise it is the first row at the PIT
  running maximum (8.4%).
- Third-party and official current readings are both the latest PIT METAR. Production's US station_observations
  source is metar.
- official_current_stale = False.

The lock-in is applied to the final c1/served bands, uniform within each band, as in rungs 1 and 2. S7 is not
re-emulated.

**No new hour gate.** S3 (13-15h), S4 (15-19h) and S5 (13-19h) are production's own afternoon stages, used with
their production hours. No gate was chosen on this table, and none was added (rule 8).

**ladder-r1c-p2.** Proxy sensitivity (section 2).

**d-rung1c-d-nofc.** Diagnostic, not a candidate: every forecast condition is treated as met.

## 2. The forecast object production passes, and the proxy

distribution_late_day_lockin_stage (model_distribution.py:1176) passes five objects to S3-S5:

| Object | What it is | On US markets |
|---|---|---|
| weather_forecast | weather.com | Paid, disabled; source_data returns {} |
| open_meteo | api.open-meteo.com/v1/forecast best_match hourly temperature_2m | Live |
| nws_hourly | api.weather.gov forecastHourly | Live |
| global_ensemble | Open-Meteo GFS-ensemble mean | Live |
| eccc_city | Environment Canada | Not a US source, so {} |

So production has 3 live sources: rows of today with hour ≥ fetch time, first 12, in model_sources.py:1451, :1651
and :2135.

remaining_forecast_context (model_distribution_signals.py:431) counts the sources that have remaining values. When
rows are empty it falls back to day_rows, then to the whole-day day_max.

**None of these hourly rows are in the 111h extract.** The extract has only the scalars forecast_high, hrrr_high and
nws_grid_high. Production data was not pulled.

**Proxy P1, declared before scoring.** Three free PIT sources, one per live source:

| Live source | Stand-in | Availability rule |
|---|---|---|
| open_meteo | Single-Runs ncep_hrrr_conus | run + 3 h ≤ t; latest run with non-null remaining values, ≤ 3 back |
| nws_hourly | NBH TMP hourly | S3 LastModified ≤ t |
| global_ensemble | Single-Runs ecmwf_ifs | run + 8 h ≤ t |

Coverage at 13-19: all 3 sources on 100% of snapshots.

**Proxy P2.** Single-Runs HRRR plus Single-Runs NBM (run + 6 h), so 2 sources. Coverage at 13-19: 100%.

**Not tested:** the real open_meteo best_match, NWS and GEFS rows. A live-row replay on the capture host is the
confirmation step.

## 3. Stage activity (P1, share of snapshots)

| Block | S1/S2 > 0 (rung 2) | S3 | S4 | Hard strength raised above r2 | S5 applied | Mean hard strength |
|---|---|---|---|---|---|---|
| 13-14 | 0% | 10.0% | — | 10.0% | 5.5% | 0.10 |
| 15-16 | 36.7% | 11.5% | 31.4% | 31.4% | 2.9% | 0.25 |
| 17-23 | 97.3% | — | 33.9% | 1.7% | 0% | 0.94 |

Shares across the 13-19 snapshots:
- Stood ≥ 60 min: 74.8%.
- Current ≤ F − 0.45 °F (rolled over): 55.3%.

## 4. Per block (from stratum primary, before stratum beside; all-row, served fallback, W intervals)

How to read the table:
- **closed** = the share of the ORIGINAL served − market excess closed.
- **r1c − r2** = paired marginal, with the number of markets −/+.
- Tail = this table's definition (6.075% of rows / 70.38% of excess). EF's 4.387% / 64.14% comes from a different
  panel.
- Classes are the harness LEAD classifier against served.

| block | r1c − market [95%] | before | ratio | closed [95%] (r2) | r1c − r2 [95%] | mkts −/+ | r1c − r2 before | r1c − t3-r3 [95%] (mkts r1c better) | before | tail removed (r2) | class |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 00-05 | +0.0102 [+0.0056, +0.0149] | +0.0086 | 1.181 | 58% [37, 76] (58%) | 0 | 0/0 | 0 | −0.0132 (11) | −0.0130 | 76% (76%) | LEAD |
| 06-09 | +0.0114 [+0.0062, +0.0172] | +0.0105 | 1.204 | 55% [33, 75] (55%) | 0 | 0/0 | 0 | −0.0118 (11) | −0.0125 | 75% (75%) | LEAD |
| 10-12 | +0.0137 [+0.0088, +0.0189] | +0.0123 | 1.261 | 40% [15, 62] (40%) | 0 | 0/0 | 0 | −0.0050 (10) | −0.0103 | 69% (69%) | LEAD |
| 13-14 | +0.0183 [+0.0126, +0.0242] | +0.0167 | 1.467 | 32% [−8, 59] (29%) | −0.0007 [−0.0029, +0.0010] | 6/5 | −0.0018 | +0.0024 [−0.0037, +0.0082] (3) | −0.0013 | 72% (70%) | — |
| **15-16** | **+0.0238 [+0.0172, +0.0305]** | +0.0219 | **2.348** (r2 2.53) | −10% [−61, 25] (−25%) | **−0.0032 [−0.0051, −0.0017]** | 11/0 | −0.0042 | **+0.0149 [+0.0082, +0.0219] (0)** | +0.0103 | 60% (55%) | — |
| 13-16 | +0.0211 [+0.0152, +0.0269] | +0.0194 | 1.742 | 12% [−27, 42] (4%) | −0.0020 [−0.0038, −0.0006] | 10/1 | −0.0030 | +0.0087 [+0.0030, +0.0146] (0) | +0.0045 | 67% (63%) | WEAK |
| 17-23 | +0.0062 [+0.0035, +0.0096] | +0.0038 | n.i. | 79% [64, 89] (79%) | −0.0001 [−0.0002, −0.0001] | 11/0 | −0.0001 | −0.0017 [−0.0047, +0.0019] (7) | −0.0041 | 88% (88%) | LEAD |
| 00-16 | +0.0136 [+0.0093, +0.0182] | +0.0122 | 1.278 | 44% [21, 63] (42%) | −0.0005 [−0.0009, −0.0001] | 10/1 | −0.0007 | −0.0063 (11) | −0.0082 | 72% (71%) | LEAD |
| all | +0.0115 [+0.0081, +0.0151] | +0.0098 | 1.327 | 56% [36, 71] (54%) | −0.0004 [−0.0007, −0.0001] | 10/1 | −0.0005 | −0.0050 (10) | −0.0070 | 77% (77%) | LEAD |

The negative closed share at 15-16 is inherited from rung 2: c1's stale whole-day guidance hurts 15-16, and the
restoration recovers only part of that harm.

**Sensitivity and diagnostic, r1c − r2:**

| Block | P2 | nofc (diagnostic) |
|---|---|---|
| 13-14 | −0.0007 [−0.0035, +0.0017] | +0.0052 [−0.0013, +0.0112], 2/11 |
| 15-16 | −0.0031 [−0.0052, −0.0016], 10/11 | −0.0041 [−0.0076, −0.0010] |
| 13-16 | −0.0019 [−0.0041, −0.0002] | +0.0005 |

**Paired r1c vs t3-r3:**
- 15-16: +0.0149 [+0.0082, +0.0219]. t3-r3 is better in 11/11 markets; before stratum +0.0103.
- 13-16: +0.0087 [+0.0030, +0.0146], 11/11; before stratum +0.0045.

**Where the 15-16 residual sits (descriptive, attribution.json, from stratum):**

| State | Share of snapshots | Share of r1c excess | r1c − r2 | t3-r3 − r1c |
|---|---|---|---|---|
| Not rolled over (current > F − 0.45 or missing) | 58% | 73% | 0 | −0.0185 [−0.0267, −0.0111], 11/11 |
| Rolled over | 42% | 27% | −0.0078 [−0.0119, −0.0045], 11/11 | −0.0106 [−0.0186, −0.0037], 9/11 |

## 5. Fix shape and floor interaction (PROPOSAL ONLY; owner decision; nothing changed)

**Re-anchoring S3-S5.** These stages do not take history_max as an argument. Each one calls
self.row_max_native(history) and history.get("max_times") itself. So the fix cannot be a parameter change, as it
is for S1. In distribution_late_day_lockin_stage, build one re-anchored history view and pass it to S2-S5:
- max = lockin_high = max(history_max, guidance_floor);
- max_times = the METAR rows' first time at that bucket.

The stages need no new capture: production already passes the three live hourly forecast sources and the METAR
official reading. The serveability class is "zero-parameter serving stage". The effective strength would also
feed the S7 taper, which was not re-emulated here.

**Floor interaction.** All stages act only above bucket B = round_half_up(F), and the 81a floor mask removes
mass below B:
- At strength 1, S3 collapses onto B's band and keeps the 5% one-up hedge.
- S5 deliberately keeps 55% and 30% of the one-up and two-up buckets.
- The stages never conflict with the floor, and the floor is never weakened.
- Anchoring every stage on F keeps the floor and the lock-in on one value.
- Serving's hard_floor_bucket does not include guidance_floor, so the 81a floor mask stays the stricter of the
  two.

**Recommendation for the owner's decision.**
- Restoring S3-S5 is a consistent but small 15-16 gain: −0.0032, 11/11 markets, about 1/6 of t3-r3's margin.
- It is reasonable to bundle it with the rung-1 restoration, because it repairs the same WU-anchor defect.
- It is not the 15-16 fix. That residual lives on snapshots where the temperature is still at the high, which the
  lock-in family excludes by design.
- Closing it needs a remaining-rise stage (the t3-r3 form). That is a new rule, so it belongs in a Phase-4 draft
  pre-registration only (rule 8), not in a restoration.

## 6. Caveats

- **Proxy dependence:** declared, two proxies agree, and the real rows are untested.
- **Band-level emulation:** applied post-calibration, with no S7 re-emulation. A replay through
  estimate_distribution is the confirmation step.
- **Readings:** the third-party and official readings are identical, so S5's consistency factor is always 1.
- **Stale flag:** official_current_stale is assumed False.
- **Clusters:** 11 market clusters.

## Files

- Code: C:\pt\swarm\tools\research\model_parity\d_rung1c.py, with modes register, score and attr.
- Outputs in C:\swarm\out\d-rung1c\:
  - *.score.json
  - scores.json
  - attribution.json
  - strengths.parquet
  - snapb_*.npy
  - run.log and attr.log
  - result.json
