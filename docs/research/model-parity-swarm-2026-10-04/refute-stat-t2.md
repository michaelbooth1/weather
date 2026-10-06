# R-STAT-T2: statistics refutation of T2 (t2-r1 remaining-rise nowcast) - development

**Verdict: NOT DISQUALIFIED.** The 17-23 LEAD survives every independent inference I ran. The 13-16 LEAD holds
under independent computation of all four DESIGN section 1 conditions, but it is **family-wise fragile**: it does
not survive Bonferroni over the registry x 7 groups, its estimate sits 0.00003 above the -0.0133 line and qualifies
only through the 5%-of-gap bar, and its paired marginal gain over the T3-r3 rung is small (-0.0016). No load-bearing
claim failed verification. All numbers are development reads on the 111h table; the from stratum is a development
read on previously inspected dates, not a holdout.

Lens: statistics refuter (DESIGN section 5). Candidate: t2-r1, from stratum, all-row estimand with served fallback.
HARNESS_SHA256 `8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74` (unchanged).
Candidate code sha256 `0851103e4161242a808c2f9c66d6f6d366e1d729a8dff5efe8488e3a4df83521` (matches T2's result.json).
Rows dated after 2026-09-29 in anything I scored: 0. No new rule registered. Finished ~01:06 local (deadline 06:45).

Code: `C:\pt\swarm\tools\research\model_parity\r-stat-t2_refute.py` (independent scoring and inference) and
`r-stat-t2_marginal.py` (paired rung comparison, coverage audit). Outputs in `C:\swarm\out\refute-stat-t2\`:
`result.json`, `marginal_vs_t3r3.json`, `t2_r1_p_unfloored.npy`, `t2_state.parquet`, `run.log`, `marginal.log`.

## 1. What was done independently

- The t2-r1 candidate was regenerated with the hunter's own functions (same registered rule, no re-tuning). This
  lens checks scoring and inference; PIT is R-PIT-T2's lens.
- Scoring re-implemented without `harness.score`: own rule-4 floor mask (81a definition) and renormalisation, own
  per-snapshot Brier (mean over bands), own (date, market) cells, served fallback for uncovered snapshots. Coverage
  reproduced exactly: candidate 104,800 / absent 5,285 / missing_floor 382 / zero_mass_after_floor 340 (share 0.9458).
- Intervals computed directly from `C:\swarm\cache\W.npy` (sha256 verified against `cache_receipt.json`,
  `61321701...`; shape 2000 x 626; mean weight 1.000; 58.4% zero entries, as a crossed multinomial should have).
- Alternative inferences: fresh crossed bootstraps (3 seeds, 4,000 draws), date-cluster-only bootstrap,
  market-cluster-only bootstrap, t-interval on the 36 per-date means, winsorised (5/95) and 10% trimmed means,
  leave-one-market-out, leave-one-ISO-week-out, leave-one-date-out, concentration of the gain in the top market-days,
  per-date and per-week signs.
- Multiplicity counted from `C:\swarm\registry.jsonl` at 00:56 local: 40 registered rules across 9 agents (T2: 4).
  Bonferroni over 40 x 7 groups = 280 tests needs |z| > 3.75; T2's own 4 x 7 = 28 tests needs |z| > 3.12.
- Availability-vs-outcome: covered vs uncovered snapshots compared on served Brier, market Brier, gap, and on the
  realised remaining rise above the captured floor (`settlement_high - floor_bucket`; a label used only here, in the
  refutation, never in the candidate).
- Paired marginal gain of t2-r1 over the registered T3-r3 rung (floor + remaining rise), both regenerated, same floor,
  identical rows, W intervals on the paired per-market-day difference.

## 2. Reproduction of the hunter's numbers (from stratum, all-row)

| block | mine: cand - served [W 95%] | hunter | abs diff | mkts neg | before stratum (mine) |
|---|---|---|---|---|---|
| 17-23 | -0.028232 [-0.039502, -0.019114] | -0.028232 [-0.039502, -0.019114] | < 1e-9 | 11/11 | -0.033100 [-0.044013, -0.022218], 11/11 |
| 13-16 | -0.013274 [-0.020906, -0.006744] | -0.013274 [-0.020906, -0.006744] | < 1e-9 | 11/11 | -0.012040 [-0.021858, -0.003507], 9/11 |
| 00-16 | -0.004444 [-0.012048, +0.001561] | -0.004444 [-0.012048, +0.001561] | < 1e-9 | 6/11 | -0.005831 [-0.013015, +0.000070] |

Served - market gap (from): 17-23 0.029814 (gap closed 94.7%), 13-16 0.024056 (55.2%). Candidate - market in 17-23:
+0.001582 [+0.000131, +0.004090], so the candidate is still measurably worse than the market there. The hunter's
numbers are exact under independent code.

## 3. Independent inference: does the interval exclude 0 under other resampling?

| block | W (harness) | crossed, seeds 1/2/3 (4k draws) | date-cluster only | market-cluster only | t on 36 dates | z (W se) | boot p (2-sided) |
|---|---|---|---|---|---|---|---|
| 17-23 | [-0.0395, -0.0191] | [-0.0395,-0.0191] / [-0.0394,-0.0189] / [-0.0395,-0.0191] | [-0.0323, -0.0242] | [-0.0377, -0.0207] | [-0.0326, -0.0239] | -5.30 | < 0.0005 |
| 13-16 | [-0.0209, -0.0067] | [-0.0213,-0.0061] / [-0.0214,-0.0064] / [-0.0210,-0.0063] | [-0.0162, -0.0105] | [-0.0198, -0.0079] | [-0.0163, -0.0102] | -3.54 | 0.001 |
| 00-16 | [-0.0120, +0.0016] | all three include 0 | [-0.0064, -0.0024] | [-0.0113, +0.0008] | [-0.0065, -0.0023] | - | - |

Every resampling scheme excludes 0 for 17-23 and 13-16. The crossed W interval is the widest because it adds the
11-market cluster, as it should. 00-16 is a caution for the synthesis: a date-only bootstrap would call it
significant, the crossed scheme does not, and the markets split 6/11, so WEAK is the right class.

Robust-location checks (from): 17-23 winsorised mean -0.0281, 10% trimmed mean -0.0211, median market-day delta
-0.0105; 13-16 winsorised -0.0127, trimmed -0.0119, median -0.0101. All stay far below the 5%-of-gap bars
(-0.0015 / -0.0012); the trimmed 17-23 value is still below the -0.0133 line, the 13-16 values are not.

## 4. One market or one week?

**17-23.** Per-market deltas all negative, from Seattle -0.0087 to LA -0.0669. Leave-one-market-out: estimates
-0.0244 (drop LA) to -0.0302 (drop Seattle); worst upper bound -0.0175 (drop LA). All 36 from-stratum dates are
negative (36/36) and every ISO week is negative (w34 -0.0168 [1 date], w35 -0.0334, w36 -0.0278, w37 -0.0209,
w38 -0.0241, w39 -0.0338, w40 -0.0377 [2 dates]). Leave-one-week-out worst upper bound -0.0180; leave-one-date-out
moves the estimate only within [-0.0289, -0.0275]. 94.7% of market-days are negative. The gain is moderately
concentrated (top 5% of market-days carry 24.6% of the net gain, top 10% carry 43.7%), but dropping the top 5% still
leaves -0.0224. Largest market-days: nyc 09-28 -0.172, dallas 08-24 -0.166, los-angeles 09-28 -0.155, nyc 09-10
-0.146, dallas 09-12 -0.146. **Not one market, not one week.**

**13-16.** Per-market deltas all negative, but three are tiny (Atlanta -0.0018, Miami -0.0026, Seattle -0.0035); the
mass is in LA -0.0391, SF -0.0231, NYC -0.0182. Leave-one-market-out: -0.0107 (drop LA) to -0.0144; worst upper
bound -0.0053. Dates negative 34/36 (positives: 09-17 +0.0043, 09-22 +0.0029); all 7 weeks negative, w34 (one date)
only -0.0018. Leave-one-week-out worst upper bound -0.0051. More concentrated than 17-23: top 5% of market-days
carry 36% of the net gain, top 10% carry 60%; dropping the top 5% leaves -0.0089 (7x the 5% bar, above the -0.0133
line). 63.9% of market-days negative, 35.6% positive. **Not one market or one week, but a heavier-tailed gain.**

**Before stratum.** 17-23 -0.0331 [-0.0440, -0.0222], 11/11 markets. 13-16 -0.0120 [-0.0219, -0.0035], 9/11.
Both strata agree in sign and roughly in size under my computation.

## 5. Multiplicity (forking paths)

- Registry at 00:56 local: 40 rules (t2 4, t11 5, t12 4, t3 4, t1 4, t15 4, t4 4, t14 6, t7 5). The count is
  still growing; the synthesis must recount at freeze.
- T2's registration (00:43:30) precedes its first score file (t2_diag.json, 00:45:34). Within T2 the forking is 4
  variants (r1, r2, r3, r1s60 stress) x 7 groups. Implementation details present in the code but not in the
  registry text: history days need >= 18 rows; the R support is clipped at 40 F; history limited to calendar
  months 7-10 (implied by the m-1..m+1 window). None is a tuned parameter and none plausibly moves the result;
  recorded for completeness.
- 17-23: z = -5.30. Survives Bonferroni over 280 tests (needs 3.75) and any plausible correction.
- 13-16: z = -3.54, bootstrap two-sided p = 0.001. Survives T2's own 28-test correction (3.12) but **does not
  survive Bonferroni over registry x groups (3.75)**. Bonferroni is conservative here (many registry entries are
  sensitivities or controls of the same family, and the tests are strongly correlated), so this is a caution, not
  a refutation. Label the 13-16 LEAD "family-wise fragile" in the synthesis.
- 13-16 size bar: estimate -0.013274 vs line -0.0133 (misses by 0.00003); it qualifies through the 5%-of-gap bar
  (-0.0012) by a factor of 11. Under the trimmed and winsorised means and every leave-one-out it stays far below the
  5% bar but above the line. The 13-16 LEAD rests on the gap bar, not the line.

## 6. Availability-vs-outcome (is coverage selected on outcome?)

- **17-23 (from).** Covered 19,905 snapshots, uncovered 290 (1.4%): 231 `zero_mass_after_floor`, 59
  `missing_floor`, 0 `absent`. Uncovered snapshots have a larger served Brier (0.056 vs 0.030), a near-zero market
  Brier (0.00008), and 100% of them settled at or below the captured floor bucket (covered: 99.2%). Mann-Whitney on
  remaining rise vs floor p ~ 1e-138, on served Brier p ~ 1e-18. The uncovered rows ARE different, but the mechanism
  is the floor, not the label: `zero_mass_after_floor` happens when the climatology puts its mass at or just above the
  METAR running max M while the captured production floor (high_so_far / trusted_current_max) sits above that
  support, so the masked candidate has no mass left. Both inputs are PIT-available at serve time, and the harness
  scores these rows as served (rule 6), so no gain is claimed on them. Mean remaining rise vs floor on these rows is
  negative (-0.18 F): some production floors sat above the eventual settlement, a production-floor oddity for
  T20/F2, not a T2 defect. Fully covered market-days (372) have delta -0.0293, the 24 partially covered -0.0124;
  correlation between a market-day's coverage share and its delta is -0.10 (more coverage, more gain, as a fallback
  estimand should behave). Per-market coverage 0.978-0.998 except Miami 0.890; no date below 0.907.
  **No selection on outcome; the all-row estimand is honest and the fallback dilutes rather than inflates.**
- **13-16 (from).** Covered 11,714, uncovered 52 (0.4%): 39 `zero_mass_after_floor`, 10 `missing_floor`, 3 `absent`.
  Served-market gap identical in both groups (0.0240 vs 0.0240). Per-market coverage >= 0.96. Negligible.
- **00-16 (from).** Uncovered 3,674 (7.3%), 3,446 of them `absent` (no target-date METAR yet, local hours 0-1).
  Uncovered rows have a larger remaining rise (10.9 F vs 7.6 F) because they are earlier in the day: time-of-day
  structure of availability, not outcome selection. 00-16 is WEAK anyway.

## 7. Marginal gain over the T3-r3 rung (floor + remaining rise), paired on identical rows

The DESIGN LEAD rule is relative to served, so this is context for the parity ladder, not a disqualification test.
t3-r3 regenerated from `t3_baselines.build()`; both candidates floored by the same code; paired per-market-day
difference t2 - t3, W intervals. Rows covered by both: 104,546 (t2 104,800; t3 104,805).

| block | stratum | t2 - served | t3-r3 - served | **t2 - t3-r3 (paired)** | mkts neg (paired) |
|---|---|---|---|---|---|
| 17-23 | from | -0.0282 [-0.0395, -0.0191] | -0.0219 [-0.0327, -0.0131] | **-0.0063 [-0.0084, -0.0035]** | 11/11 |
| 17-23 | before | -0.0331 [-0.0440, -0.0222] | -0.0254 [-0.0359, -0.0150] | **-0.0077 [-0.0093, -0.0062]** | 11/11 |
| 13-16 | from | -0.0133 [-0.0209, -0.0067] | -0.0116 [-0.0190, -0.0052] | **-0.0016 [-0.0030, -0.0001]** | 8/11 |
| 13-16 | before | -0.0120 [-0.0219, -0.0035] | -0.0097 [-0.0186, -0.0018] | -0.0023 [-0.0043, -0.0003] | 10/11 |
| 00-16 | from | -0.0044 [-0.0120, +0.0016] | -0.0043 [-0.0121, +0.0017] | -0.0001 [-0.0007, +0.0006] | 6/11 |
| all | from | -0.0113 [-0.0191, -0.0053] | -0.0094 [-0.0172, -0.0033] | -0.0019 [-0.0027, -0.0008] | 11/11 |

Reading: in 17-23 the deficit/slope conditioning and the 15-minute grid add a real, consistent -0.006 over the
zero-fit rung (11/11 markets in both strata; 21% of the 17-23 gap). In 13-16 the extra is -0.0016 (7% of the gap),
8/11 markets, interval barely excluding 0: most of T2's 13-16 effect is the rung's. The "marginal" also bundles the
other design differences between the two implementations (routine+SPECI vs routine only, tmpf vs T-group, 15-min grid
vs H:30 cut), so it is an upper bound on what the conditioning alone contributes.

## 8. Defects found (none disqualifying)

1. 13-16 LEAD is family-wise fragile: z = -3.54 fails Bonferroni over 280 registry x group tests (needs 3.75);
   estimate misses the -0.0133 line by 0.00003 and qualifies only via the 5%-of-gap bar; marginal gain over the
   T3-r3 rung is -0.0016 [-0.0030, -0.0001], 8/11 markets; 36% of the net gain sits in 5% of market-days.
2. Unregistered implementation details (>= 18 history rows per day, R clipped at 40 F, months 7-10 filter). Not
   tuned, no plausible effect; should be added to the rule text if T2 goes to a draft pre-registration.
3. `zero_mass_after_floor` fallbacks (231 snapshots in 17-23) are the rows where the candidate's belief conflicts
   with the production floor; the fallback is PIT-legitimate and scored as served, but a serving-stage form must
   specify the same fallback. Some of those floors exceeded the settlement (production-floor oddity, hand to T20/F2).
4. 00-16 would read as significant under a date-only bootstrap; keep the crossed W scheme and the WEAK class.

## 9. What this refutation did not do

- Did not re-derive METAR availability from primary sources or re-run at +1 h/+2 h (R-PIT-T2's lens; the hunter's
  own +60 min stress kept both LEADs).
- Did not test the WU-settlement vs METAR-hourly-row label mismatch (F2/T16).
- Did not compute per-market intervals in 13-16 for the three near-zero markets (Atlanta, Miami, Seattle); their
  signs are negative but should be treated as ties.