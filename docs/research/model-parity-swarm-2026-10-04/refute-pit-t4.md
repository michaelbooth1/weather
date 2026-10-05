# R-PIT-T4: PIT/leakage refutation of the T4 obs-trend nowcast (development only)

## Verdict: NOT DISQUALIFIED for the headline (t4-r3, 17-23) and for 13-16 at +1 h. DISQUALIFIED as LEAD claims: t4-r3 10-12 and 00-16 (collapse to WEAK at +1 h), t4-r1 13-16 (WEAK at +1 h). 13-16 does not survive +2 h.

- No leakage found. Rules 1, 2, 3, 4, 5 and 8 are satisfied in the code (`t4_obs_trend_nowcast.py`, sha256
  `46F3C768...88F1FD`, unchanged since T4 ran) and the harness tripwire (`leakage_suspect_groups`) is empty under every lag.
- Reproduction: re-running the T4 module at its own availability basis (valid + 10 min) gives r3 17-23
  **-0.026506 [-0.037221, -0.017845]**, identical to the T4 report to 6 dp, under HARNESS_SHA256
  `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74` (recomputed from the harness bytes, matches HARNESS.md).
- Availability shifted **+1 h** (every METAR/SPECI treated as available 60 min after valid, history grid and snapshots alike):
  r3 17-23 stays LEAD at -0.025952 [-0.036593, -0.017352], 11/11 markets; r3 13-16 stays LEAD at -0.007792 [-0.014480, -0.002435],
  8/11 markets (the minimum), before stratum -0.007200; the 13-16 estimate shrinks by 41% and passes only the 5%-of-gap bar
  (-0.0012), not the twice-81a line. r3 10-12 and 00-16 and r1 13-16 fall to WEAK. r1 10-12 and 00-16 are NULL.
- **+2 h**: r3 17-23 still LEAD at -0.024031 [-0.034674, -0.015367], 11/11; r3 13-16 is WEAK (-0.003250, upper bound +0.001457).
- Serve-only +1 h (tables fitted at +10 min, snapshots lagged 60 min, the fit/feed mismatch case): 17-23 -0.026223 LEAD,
  13-16 -0.009058 [-0.016596, -0.002879] LEAD with 10/11.
- Production cross-check: at 17-23 covered snapshots the candidate's METAR running max exceeds production's own captured floor
  (max of guidance_physical_floor, high_so_far, trusted_current_max) by >= 1 F in only **0.14%** of snapshots (0.44% all hours).
  Restricting r3 to the 102,441 snapshots where the running max is at or below the captured floor bucket leaves 17-23 at
  -0.025902 [-0.036944, -0.017160], 11/11, and 13-16 at -0.012828 [-0.019667, -0.006977], 11/11. The effect therefore does not
  depend on the candidate knowing a higher running max than production had at the time.

Every number is development evidence on previously inspected dates (rule 7). HARNESS_SHA256 as above for every score.
Rows with target date after 2026-09-29: 0 in every score; max target date 2026-09-29.

## 1. Rule checks in code (`C:\pt\swarm\tools\research\model_parity\t4_obs_trend_nowcast.py`)

| Rule | Where | Finding |
|---|---|---|
| 1 point in time | `obs_features`: rows with `~is_cor & tmpf.notna()`, `searchsorted(available_utc, t)`; `build`: `h.assert_point_in_time(used_available, captured_at_utc)` on every covered snapshot and `assert cur_age_min >= 10` | Pass. Slope obs are earlier than the latest obs by construction (valid earlier, so available earlier). Running max is `cummax` over the target local date in availability order. No 1-minute/5-minute data, no daily summaries. |
| 2 no market input | Reads only `h.candidate_inputs()` (allow-listed), `C:\swarm\data\iem\metar\*.parquet`, `stations.json`. r3 mixes with `p_served` (allowed). `paired()` uses harness internals (`h.data()`) but only in the diagnostic, after scoring, to difference two already built candidates. | Pass. |
| 3 no settlement leakage; fit window | `HIST_END = "2026-07-31"`; `history_grid` keeps `d <= HIST_END` and asserts `max(ds) <= HIST_END`; labels are METAR day maxima, never winner/settlement. r3's w chosen with `where=lambda s: s.stratum == "before_20260823"`. | Pass. Fitted tables end 2026-07-31 as claimed. The only on-table parameter (w) is fitted on the before stratum (rules 3 and 7 allow). |
| 4 floor | Harness `score()` applies the 81a mask; no `unfloored=True` anywhere. | Pass. |
| 5 date guard | `assert snaps.date.max() <= "2026-09-29"`; harness re-asserts; every score reports 0 rows after 09-29. METAR parquet max local_date 2026-09-29 for all 11 stations (valid up to 2026-09-30 06:56Z is local 09-29 in the Pacific stations). | Pass. No market or settlement record for 09-30 or later is touched. |
| 8 no hour gate | No NBM/NBP input; w is one global value chosen on the 00-23 aggregate. | Pass. |

Registry: t4-r1/r2/r3 appended 00:45:17, t4-d1 at 00:47:04; first score written 00:46:49 (r1) and lag30 scores 00:47:18, so each rule precedes its first score. Rule text sha256 values match the registry lines.

## 2. Availability of the only input, re-derived

- **Primary source**: IEM ASOS download service (`asos.py`), raw CSV chunks kept in `C:\swarm\data\iem\raw_metar\` (URL and retrieval time in the first line), 220 requests at >= 2 s spacing per `metar_acquire.log`. Every parquet row has `available_utc - valid_utc = 10 min` exactly (checked on all rows, 11 stations; 0 exceptions).
- **What IEM states** (download page, fetched 2026-10-04 ~00:56 local): "Data is synced from the real-time ingest every 10 minutes", sources "Unidata IDD, NCEI ISD, and MADIS One Minute ASOS", "very little quality control is done". The METAR dataset page names NOAAPort as the main source and the T-group as the source of extra precision. Neither page gives a per-observation ingest timestamp, so the +10 min basis cannot be verified per row; it is the DESIGN rule-1 minimum and matches IEM's archive sync cadence. Routine obs are transmitted on NOAAPort within a few minutes of the :5x valid time, so +10 min is defensible for a real-time consumer; the +1 h/+2 h shifts above bound the residual uncertainty.
- **Residual that cannot be closed from the archive**: IEM back-fills gaps in its NOAAPort feed from NCEI ISD and MADIS, which are not point in time, and the download does not flag such rows. The production cross-check bounds the consequence for the running max (section 4): the candidate's M exceeds production's captured floor by >= 1 F in 0.14% of 17-23 snapshots and the effect is unchanged on the complement. Slope/sky/wind features could still come from a back-filled row, but T4's own paired test shows those features hurt (r1 - r2 > 0 everywhere), so a leak through them would work against the candidate.
- **tmpf is the raw text, not a revision**: on the 2026-07-25..09-29 window `tmpf == round(tgroup_f)` on 99.9-100% of T-group rows at ten stations. At KBKF only 36.6% match because IEM stores the unrounded T-group tenths there (e.g. 78.3 for T0257); `tmpf` equals `tgroup_f` to one decimal. Rows without a T-group agree with the body temperature within 1 F everywhere. No sign of post-hoc revision.
- COR rows (89-1,546 per station over the span; 8-214 in the window) are excluded; IEM keeps one row per valid time, so a COR leaves a gap for that hour (acquirer caveat), which is conservative.

## 3. Availability shifts via the harness (all-row primary, from stratum, 95% W intervals)

Mechanism: `EXTRA_LAG_MIN` in the T4 module, added to the +10 min for history grid and snapshots alike (same as t4-d1), except the serve-only row. r3 uses w = 0.8 fixed (the T4 before-stratum choice); re-tuning w under lag would be a new rule.

| shift | rule | 10-12 | 13-16 | 17-23 | 00-16 |
|---|---|---|---|---|---|
| +10 min (repro) | r3 | LEAD -0.006062 [-0.012195, -0.000576] 8/11 | LEAD -0.013148 [-0.020059, -0.007299] 11/11 | LEAD -0.026506 [-0.037221, -0.017845] 11/11 | LEAD -0.005320 [-0.011769, -0.000308] 9/11 |
| +1 h | r3 | **WEAK** -0.002595 [-0.008867, +0.002993] 5/11 | LEAD -0.007792 [-0.014480, -0.002435] 8/11 | LEAD -0.025952 [-0.036593, -0.017352] 11/11 | **WEAK** -0.002427 [-0.008614, +0.002354] 5/11 |
| +2 h | r3 | NULL +0.000554 | **WEAK** -0.003250 [-0.009349, +0.001457] 7/11 | LEAD -0.024031 [-0.034674, -0.015367] 11/11 | WEAK -0.000765 |
| +1 h serve-only | r3 | WEAK -0.002202 | LEAD -0.009058 [-0.016596, -0.002879] 10/11 | LEAD -0.026223 [-0.036921, -0.017548] 11/11 | WEAK -0.003460 |
| +10 min (repro) | r1 | WEAK -0.002977 | LEAD -0.011353 [-0.019670, -0.003873] 9/11 | LEAD -0.025183 [-0.037443, -0.014447] 11/11 | WEAK -0.001746 |
| +1 h | r1 | NULL +0.002128 | **WEAK** -0.003665 [-0.011808, +0.003403] 8/11 | LEAD -0.024708 [-0.036834, -0.014228] 11/11 | NULL +0.002279 |
| +2 h | r1 | NULL +0.006425 | NULL +0.002001 | LEAD -0.023026 [-0.035344, -0.013009] 11/11 | NULL +0.004082 |

Before-stratum estimates keep the same sign wherever the from-stratum class is LEAD. Coverage under +1 h: absent rises from 5,285 to 8,825 snapshots (served fallback), all still inside the all-row estimand.

Read: the 17-23 result is insensitive to availability (point estimate moves from -0.0265 to -0.0240 across a 2 h shift, interval always excludes 0, 11/11 markets); once the high is in, an hour-old running max is as good as a fresh one. 13-16 depends on freshness: it survives +1 h only via the 5%-of-gap bar with the minimum market count, and fails at +2 h. 10-12 and 00-16 do not survive +1 h and should not be carried as LEADs.

## 4. Candidate running max vs production's captured floor (covered snapshots, +10 min basis)

| block | covered | M >= floor + 1 F | M >= floor + 2 F | M <= floor - 1 F | mean M - floor |
|---|---|---|---|---|---|
| 00-05 | 21,705 | 0.04% | 0.04% | 39.8% | -0.88 |
| 06-09 | 18,419 | 0.24% | 0.13% | 37.8% | -0.87 |
| 10-12 | 14,507 | 1.72% | 1.47% | 22.9% | -0.52 |
| 13-16 | 18,574 | 0.64% | 0.41% | 10.5% | -0.23 |
| 17-23 | 31,935 | 0.14% | 0.04% | 1.7% | -0.04 |
| all | 105,140 | 0.44% | 0.32% | 20.4% | -0.46 |

`trusted_current_max` is null on every row of this table; the captured floor is max(guidance_physical_floor, high_so_far). M exceeds `high_so_far` alone by >= 1 F in 53-57% of 00-09 snapshots (F3's midnight carry-over gap), but the guidance floor covers it. The 10-12 block has the largest share of snapshots where the IEM running max is ahead of production (1.7%), consistent with its fragility under lag.

r3 re-scored on the split (17-23 / 13-16 / 00-16, from stratum): M <= floor bucket (102,441 snapshots) -0.025902 [-0.036944, -0.017160] 11/11 / -0.012828 [-0.019667, -0.006977] 11/11 / -0.005832 [-0.012671, -0.000455] 9/11; M > floor bucket (2,699 snapshots) -0.042504 [-0.131196, -0.008613] 5/11 / -0.023391 [-0.066206, -0.004932] 9/11 / -0.013359 [-0.040206, +0.002972]. The small "ahead of production" subset is noisier and more favourable, as leakage would be, but it carries 2.6% of snapshots and removing it does not move the headline.

## 5. Minor defects (not disqualifying)

1. KBKF `tmpf` is in tenths. `band_probs` computes `k = (x - M).astype(int)`, which truncates toward zero, so for M = 78.3 and a band ending at 78 it assigns P(r = 0) to a band below the running max instead of 0. Affects one market (Denver), small mass, and does not involve any future information. The history grid rounds `fmax - runmax`, so train/serve parity is approximate at that station.
2. The T4 report says "every covered snapshot has t - valid >= 10 min" and asserts it; true, but the earlier slope obs' availability is only implied, not asserted. Harmless by construction.
3. The d1 +30 min sensitivity in the T4 report understates fragility: 13-16 r1 is already WEAK at +1 h and r3 13-16 is WEAK at +2 h.
4. Serveability framing: production has no PIT METAR running max from local midnight today (`trusted_current_max` is null on all rows), so the "zero-parameter serving stage" possibility stated in the T4 report is contingent on new capture, as the report itself concludes.

## 6. Files

- Code: `C:\pt\swarm\tools\research\model_parity\r-pit-t4_refute.py` (imports the T4 module; registers nothing).
- Scores: `C:\swarm\out\refute-pit-t4\rpit_t4_{r1,r3}_{lag10_repro,lag60,lag120,lag60_serve_only}.score.json`,
  `rpit_t4_r3_M_le_floor.score.json`, `rpit_t4_r3_M_gt_floor.score.json`; summary `rpit_t4_summary.json`; log `run.log`.
- Inputs read: `C:\swarm\out\t4\*`, `C:\swarm\data\iem\metar\*.parquet` and `MANIFEST.json`, `C:\swarm\data\iem\metar_acquire.log`,
  `C:\swarm\registry.jsonl`, IEM documentation pages (download.phtml, info/datasets/metar.html). No current observations were fetched.
- Process: refuter run PID 55648 exited normally; nothing left running.
