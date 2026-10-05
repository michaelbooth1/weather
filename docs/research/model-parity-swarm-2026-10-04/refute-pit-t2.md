# R-PIT-T2: PIT/leakage refutation of T2 (remaining-rise climatology nowcast, t2-r1)

**Verdict: NOT DISQUALIFIED for the candidate under test (t2-r1, 17-23).** The 17-23 LEAD survives
every availability stress I ran (+1 h and +2 h, shifting history and live together or live only; worst
case -0.026366 [-0.037680, -0.017081], 11/11 markets, both strata negative). No market input, no
settlement input, no row dated after 2026-09-29, floor applied by the harness, no hour gate. Rule-1 assert
re-run on every covered snapshot (the hunter sampled 2,000): passes.

**Defect (secondary claim): the 13-16 LEAD does not survive.** It holds only under the hunter's own
stress (history and live shifted together, +60 min). With the live observation alone delayed +60 min it is
WEAK (7/11 markets); at +120 min it is WEAK (both-shift; interval includes 0, before stratum positive) or
NULL (live-only). The hunter's report should carry 13-16 as fragile, not as a second LEAD. 00-16 goes NULL
and 10-12 goes HARM under live-only +120.

All numbers are development reads. HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74`.
No rule registered by this agent. Code: `C:\pt\swarm\tools\research\model_parity\r_pit_t2_rerun.py` (imports the
hunter's module unchanged; writes only to `C:\swarm\out\refute-pit-t2\`). Hunter code verified at sha256
`0851103e4161242a808c2f9c66d6f6d366e1d729a8dff5efe8488e3a4df83521` (matches result.json).

## 1. Availability stress (the required +1 h / +2 h re-runs)

From stratum, all-row primary estimand, candidate - served. Both-shift = the hunter's own switch
(`T2_LAG_MIN`: history grid and live state both use valid + lag). Live-only = history grid stays at the
manifest basis (+10 min) while the live snapshot sees METAR at valid + lag; this is the stricter case
because a serving stage fitted on the +10 basis would then be fed late observations.

| run | covered | 17-23 cand - served [95%] | class | mkts | before | 13-16 cand - served [95%] | class | mkts | before | 00-16 | all |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hunter, +10 (basis) | 94.58% | -0.028232 [-0.039502, -0.019114] | LEAD | 11/11 | -0.033100 | -0.013274 [-0.020906, -0.006744] | LEAD | 11/11 | -0.012040 | WEAK -0.004444 | LEAD -0.011311 |
| both-shift +60 (reproduces hunter r1s60 exactly) | 91.50% | -0.027940 [-0.039246, -0.018733] | LEAD | 11/11 | -0.032592 | -0.007759 [-0.015529, -0.001430] | LEAD (5%-bar) | 9/11 | -0.006570 | WEAK -0.002218 | LEAD -0.009643 |
| live-only +60 | 91.49% | -0.028161 [-0.039426, -0.019029] | LEAD | 11/11 | -0.032983 | -0.007931 [-0.017108, -0.000305] | **WEAK** | **7/11** | -0.005382 | WEAK -0.002039 | LEAD -0.009577 |
| both-shift +120 | 87.68% | -0.026366 [-0.037680, -0.017081] | LEAD | 11/11 | -0.031108 | -0.001926 [-0.009480, +0.004080] | **WEAK** | 6/11 | **+0.000387** | WEAK -0.000269 | LEAD -0.007803 |
| live-only +120 | 87.32% | -0.027889 [-0.038996, -0.018803] | LEAD | 11/11 | -0.032760 | +0.000175 [-0.011817, +0.011502] | **NULL** | 5/11 | +0.005179 | **NULL** +0.001979 | LEAD -0.006642 |

Reading: 17-23 loses at most 7% of its effect under a two-hour delay (gap closed 0.88-0.95 in every
run; candidate - market stays +0.0017..+0.0034, still worse than the market). 13-16 loses 40% at +60 and
all of it at +120. The 13-16 gain therefore depends on the freshness of the latest METAR, which is exactly
what a point-in-time refuter must treat as unproven until the serving-side latency is measured.
`leakage_suspect_groups` is empty and `rows_with_target_after_2026_09_29` is 0 in all four runs.
Score files: `rpit_t2_r1_{both_shift,live_only}_lag{60,120}.score.json` and `.summary.json`.

My both-shift +60 run reproduces the hunter's `t2_r1s60` to six decimals in every block, which validates the
wrapper against the hunter's code path.

## 2. Availability re-derivation from primary sources

The only external input is IEM `asos.py` METAR/SPECI (a-iem-1 manifest). I checked:

- **Manifest basis**: `available_utc = valid_utc + 10 min` on every one of the 24,588 KATL rows (and the
  code asserts >= 10 min for every station). `local_date` matches the station time zone on every row
  (0 mismatches against a fresh tz conversion). The raw CSV header records the request URL and retrieval
  time (2026-10-04T04:23Z), i.e. the archive was pulled after the fact; the archive carries **no ingest
  timestamp**, so the +10 min figure is an assumption from DESIGN rule 1 (the stated minimum), not a
  measured feed lag. This cannot be re-derived from IEM itself.
- **Empirical witness from production's own captures** (`feedlag_witness.json`): production's
  `high_so_far` / `trusted_current_max` are real-time, WU-derived observed maxima captured at the snapshot
  (model_base.effective_observed_high_context: cutoff-aligned WU printed rows plus the current reading).
  For the 26,306 covered snapshots whose latest available METAR row *raised* the day's running max,
  production's captured max already reflected that value in **92.1%** of cases when the snapshot was
  10-15 min after the METAR valid time, 96.2% at 15-20 min, 97.5% at 20-30 min, 98-99% beyond 30 min.
  So a real-time observer saw the same observation on roughly the same clock as the +10 min basis; the
  residual 2-8% is consistent with production's hour-cutoff semantics and WU print lag, not with the
  archive containing rows that were invisible in real time. Denver is the outlier (78.9% reflected at
  10-30 min; all other markets 97-99%).
- **Does the gain depend on information production did not have?** (`witness_attribution.json`): in
  17-23, 96.8% of covered snapshots have METAR M equal to production's captured max and only 1.1% have
  M ahead of it; of the -0.028232 delta, **-0.000299 comes from "ahead" snapshots** and -0.027934 from
  the rest. In 13-16: -0.000121 of -0.013274 from "ahead" snapshots (2.5% of rows). The effect is not
  bought with an observation production lacked. (00-16 has 37% "ahead" snapshots overnight because
  production's observed high is cutoff-aligned; that block is WEAK/NULL regardless.)
- **Slack**: capture minus latest-METAR availability has median 31 min, 5th percentile 2.7 min, 1st
  percentile 0.5 min. A +60 min shift removes the latest row for most snapshots, which is why coverage
  falls to 91.5% and the slope cell backs off more often (level-3 cells 86,637 -> 71,397).
- **COR handling**: 649 COR rows at KATL; none shares a valid time with a non-COR row, confirming the
  acquirer's caveat that IEM keeps one row per valid time and a COR replaces the original. Excluding COR
  leaves a missing hour, conservative, and applied identically in history and live (parity).
- **tmpf vs T-group**: on 1.6% of KATL rows `tmpf` differs from `round(tgroup_f)` by up to 0.6 F
  (the body integer-C field vs the tenths group). The hunter uses IEM `tmpf`; the manifest names the
  T-group as primary. Not a PIT defect; it can move the rounded running max by 1 F on rare rows and is
  the same in history and live.
- **No other sources**: no NBM/HRRR/Open-Meteo/S3 object enters t2-r1, so S3 LastModified and
  Open-Meteo publication delays are not applicable. No 1-minute ASOS data is read anywhere.

## 3. Rule checks in code (`t2_remaining_rise.py`)

| rule | check | result |
|---|---|---|
| 1 point in time | `state()` takes the latest row with `available_utc <= captured_at_utc` (searchsorted on availability, line 72); `assert (av[ok] <= cap[ok]).all()` (line 170); `h.assert_point_in_time` on a 2,000 sample (176). Slope uses a row with valid <= latest - 110 min, hence available earlier. COR excluded (38). | pass; I re-ran the harness assert on all 105,522 covered snapshots: pass |
| 2 no market input | reads only `h.candidate_inputs()` (allow-listed; harness raises on forbidden columns) plus METAR; no `p_market_yes`, bid/ask/mid anywhere | pass |
| 3 no settlement leakage | no `winner`/`settlement_*`/`is_winner` read; history labels are METAR day maxima for local dates <= 2026-07-31 (`assert (df.date <= HIST_END).all()`, line 107); live rows contribute no fitted content; MIN_DAYS=40, bins, RMAX fixed a priori and registered 00:43:30 before the first score (00:45:34) | pass |
| 4 floor | `h.score()` default applies the rule-4 mask and renormalises; no `unfloored=True` call; 340 snapshots with zero mass after the floor fall back to served | pass (note: the nowcast also puts zero mass below the METAR running max M; where M exceeded production's floor this adds information, but section 2 shows the gain does not come from there) |
| 5 dates | `assert (snaps.date <= "2026-09-29").all()` (152); harness asserts 0 rows after 09-29; METAR parquet ends at local date 2026-09-29 (UTC rows up to 2026-09-30 03:52Z are 09-29 local observations, not market or settlement records) | pass |
| 8 no hour gate | no `where=`; all hours scored; `local_hour` is a climatology conditioning key, not a gate on NBP/NBM guidance | pass |
| 7 holdout honesty | nothing fitted on the from stratum; the hunter labels the from stratum a development read | pass |

Cosmetic: the `t2-r1s60` registry line (00:46:00) was appended while its run was already executing
(start ~00:45:40, score saved 00:47:08), i.e. before the score existed but after the launch. The hunter's
code was last modified at 00:46:10 (adding the lag switch) and the final r1 scores come from the 00:48 run
of that final code, whose sha256 matches result.json.

## 4. What this means for the synthesis

1. **17-23 t2-r1 stands as a LEAD from the PIT lens.** It is the T1 "decided band" mechanism found
   without thresholds; the market still beats it (+0.0017..+0.0034 absolute, interval excludes 0).
2. **13-16 should be demoted to fragile/WEAK** in the ladder: it fails the 8/11-market condition when only
   the live observation is delayed by an hour, and vanishes at two hours. Any draft pre-registration that
   wants 13-16 needs a measured serving-side METAR latency first (production captures no current
   temperature today; the WU-derived observed high reflects a new METAR within 10-15 min in 92% of cases).
3. **Serveability caveat the hunter did not state**: the live-only stress is the relevant one for a new
   fitted lookup stage, because train/serve parity is on the *rule* (valid + 10 min), not on the actual
   poll latency. The capture plan must log the observation receipt time so the basis can be audited.
4. Denver's weaker witness agreement (79%) deserves a look by the stations/serveability agents (station
   choice KBKF vs the market's settlement station), though Denver's 17-23 delta is negative in every run.

## 5. Files

- `C:\swarm\out\refute-pit-t2\rpit_t2_r1_*_lag{60,120}.{score.json,md,summary.json}` (4 re-runs)
- `C:\swarm\out\refute-pit-t2\witness_attribution.json`, `feedlag_witness.json`, `rerun.log`, `result.json`
- Copy of this report: `C:\pt\swarm\docs\research\model-parity-swarm-2026-10-04\refute-pit-t2.md`
- No background processes left running (the sequential re-run chain exited 0 at 00:58:55).
