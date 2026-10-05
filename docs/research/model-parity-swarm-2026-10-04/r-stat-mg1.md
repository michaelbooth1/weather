# R-STAT-MG1: statistics refuter for MG-1 (rung 2 over rung 1) and t3-r3 at 13-16 / 15-16 (development only)

Every number is a development read. The from stratum (2026-08-23..09-29) was already read by 79a/81a/111h, so it is
not a holdout (rule 7). HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74 (cache and
W only; nothing was scored through harness.score). Rows with a target after 2026-09-29: 0. No new candidate rule.
Diagnostics r-stat-mg1-d1, -d2, -d3 were registered before the first computation (registry now 137 lines).
(The Write tool guard blocked report.md; this text lives in result.json["report_md"].)

## Verdict

**(a) MG-1 (r-t5-inc-c1; ladder r2 - r1) in 00-05, 06-09, 10-12 and 00-16: STANDS as a within-family development
read, with no disqualifying statistical defect. It DOES NOT survive registry-wide multiplicity.**
- Every resampling scheme agrees on the sign and excludes 0: crossed W, date-only, market-only, every
  leave-one-market-out and every leave-one-week-out interval. Both strata are negative, 10-11 of 11 markets are
  negative, and the 11-market t gives p <= 0.006.
- Its z is between -2.6 and -3.3 in every block, against the Bonferroni/Holm line of 4.04 (134 x 7 tests). It fails
  that line in all four blocks.
- No availability-vs-outcome association was found. No staleness dose-response was found inside any morning block.
- It is the known 79a/81a/111h family, so it is worth a pre-registration on new dates and is not established.

**(b) t3-r3 at the registered 13-16 block: STANDS within the block, and fails family-wise.**
- t3-r3 - served = -0.0116 [-0.0190, -0.0052], 10/11 markets, both strata negative, robust to LOMO and LOWO.
  z = -3.26, which does not pass Bonferroni.
- **The 15-16 figure is a POST-HOC slice of the registered 13-16 block.** It cannot be cited as a finding.
- Against served, the 15-16 slice does not pass Bonferroni either: z = -3.78.
- The headline "-0.0181 over rung 2 at 15-16" is post-hoc twice: in the hour slice and in the comparator. **About
  38% of it (+0.0068) is MG-1's own 15-16 harm.** Against rung 1, t3-r3 at 15-16 is -0.0113.

**SYNTHESIS: no number is contradicted.** Every MG-1, ladder and t3-r3 estimate, interval and market count I
recomputed matches to 4 dp. I flag four framing and approximation issues (section 5).

**Still unverified (default to "unverified", not "holds"):**
- The v2_mean values were not re-derived from primary bytes.
- The parser-v2 exclusion of the 12Z/13Z/19Z cycles as target_max_not_in_cycle was not checked. Because of it,
  MG-1 reads the 07Z NBP cycle all day from about 06 local onward (section 3).
- Neither is a statistics defect, but MG-1's serveability rests on both.

## 1. Method (independent of harness.score)

**MG-1 re-implemented from its registry text.** N(v2_mean, max(v2_stddev, 1)) is integer-discretised, H = max(B, X)
with B = floor(F + 0.5), eligible only when v2_available_at <= captured_at_utc, and served otherwise.
- I wrote my own 81a floor mask. It is asserted equal to the cache's floor_impossible on every band row.
- Renormalisation, per-snapshot Brier and market-day cells are also my own.
- **Reproduction:**
  - My MG-1 per-snapshot Brier equals LADDER snapb_mg1-c1-alone.npy to 2.8e-17.
  - My served Brier equals snapb_served.npy exactly.
  - Coverage is 110,077 of 110,807 snapshots (99.34%). All 730 fallbacks are snapshots with no floor; there are 0
    v2-missing and 0 v2-late rows.

**Rung inputs taken from other agents.**
- Rungs r1 and r2 are LADDER's per-snapshot Brier vectors. r1 is too complex to re-implement here; the MG-1 part of
  r2 is checked through the reproduction above.
- t3-r3 is the R-STAT-T3 candidate frame cand_r3.parquet, with my floor and Brier applied. It reproduces t3's
  score file: 13-16 -0.01164, 17-23 -0.02191.

**Intervals.**
- Crossed W (2,000 x 626).
- Date-only and market-only multinomial cluster bootstraps: 2,000 draws, seed 20261004.
- LOMO (11 markets) and LOWO (ISO weeks 34-40 of the from stratum, 7 weeks), each with W intervals.
- An 11-market one-sample t test.
- z = estimate / sd(W draws), the same normal approximation the synthesis uses.
- Bonferroni at 0.025/938 (one-sided, z 4.04) and at 137 x 7 (z 4.05).
- Holm: its first step equals Bonferroni. With m = 938, Holm moves the threshold by less than 1% unless hundreds of
  tests rank ahead. I also tested the case where all six synthesis "passers" rank ahead; no class changed.

Code: C:\pt\swarm\tools\research\model_parity\r-stat-mg1_refute.py. Full output: C:\swarm\out\r-stat-mg1\stats.json
and run.log.

## 2. MG-1 battery (from stratum, all rows; candidate - comparator)

The 15-16 row is labelled POST-HOC. The CI columns are 95% intervals.

| Contrast | Block | Estimate | W CI | Date-only CI | Market-only CI | LOMO range (any CI incl. 0?) | LOWO range (any?) | Before | Markets neg | 11-mkt t (p) | z | Bonferroni 938 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MG-1 - served | 00-05 | -0.0142 | [-0.0234, -0.0068] | [-0.0176, -0.0107] | [-0.0214, -0.0088] | -0.0153..-0.0114 (no) | -0.0163..-0.0123 (no) | -0.0152 | 11/11 | -4.04 (0.002) | -3.33 | fail |
| MG-1 - served | 06-09 | -0.0139 | [-0.0228, -0.0062] | [-0.0176, -0.0099] | [-0.0203, -0.0086] | -0.0150..-0.0114 (no) | -0.0155..-0.0118 (no) | -0.0176 | 11/11 | -4.27 (0.002) | -3.28 | fail |
| MG-1 - served | 10-12 | -0.0091 | [-0.0162, -0.0027] | [-0.0127, -0.0055] | [-0.0130, -0.0056] | -0.0101..-0.0077 (no) | -0.0111..-0.0074 (no) | -0.0136 | 10/11 | -4.37 (0.001) | -2.65 | fail |
| MG-1 - served | **00-16** | **-0.0100** | **[-0.0179, -0.0035]** | [-0.0133, -0.0066] | [-0.0160, -0.0057] | -0.0111..-0.0075 (no) | -0.0121..-0.0081 (no) | -0.0122 | 10/11 | -3.47 (0.006) | **-2.70** | **fail** |
| r2 - r1 | 00-05 | -0.0141 | [-0.0234, -0.0067] | [-0.0176, -0.0107] | [-0.0212, -0.0088] | (no) | (no) | -0.0153 | 11/11 | -4.07 | -3.34 | fail |
| r2 - r1 | 06-09 | -0.0139 | [-0.0229, -0.0063] | [-0.0177, -0.0099] | [-0.0204, -0.0087] | (no) | (no) | -0.0177 | 11/11 | -4.26 | -3.27 | fail |
| r2 - r1 | 10-12 | -0.0092 | [-0.0164, -0.0027] | [-0.0129, -0.0055] | [-0.0132, -0.0056] | (no) | (no) | -0.0137 | 10/11 | -4.27 | -2.62 | fail |
| r2 - r1 | **00-16** | **-0.0099** | **[-0.0177, -0.0034]** | [-0.0133, -0.0065] | [-0.0158, -0.0056] | -0.0110..-0.0074 (no) | -0.0121..-0.0080 (no) | -0.0122 | 10/11 | -3.46 (0.006) | -2.68 | fail |
| r2 - r1 | 13-14 | -0.0075 | [-0.0189, +0.0023] | [-0.0122, -0.0032] | [-0.0171, -0.0004] | - | - | -0.0065 | 8/11 | -1.67 | -1.38 | fail |
| r2 - r1 | 15-16 (POST-HOC) | **+0.0068** | [-0.0009, +0.0146] | **[+0.0020, +0.0113]** | **[+0.0020, +0.0110]** | +0.0059..+0.0087 | +0.0031..+0.0091 | +0.0033 | 2/11 | +2.75 (0.02) | +1.72 | - |
| r2 - r1 | 13-16 | -0.0002 | [-0.0086, +0.0077] | [-0.0046, +0.0040] | [-0.0073, +0.0050] | - | - | -0.0015 | 2/11 | -0.06 | -0.05 | - |
| r2 - r1 | 17-23 | +0.0018 | [-0.0015, +0.0052] | [+0.0001, +0.0037] | [-0.0006, +0.0038] | - | - | +0.0002 | 2/11 | +1.53 | +1.08 | - |
| r2 - r1 | all | -0.0066 | [-0.0129, -0.0013] | [-0.0093, -0.0038] | [-0.0114, -0.0030] | LAX-out CI incl. 0 | weeks 35/36-out CI incl. 0 | -0.0085 | 10/11 | -2.78 | -2.18 | fail |

Share of the block's gap closed (from stratum): 00-05 58.1%, 06-09 54.8%, 10-12 39.9%, 00-16 41.3%. These match the
synthesis's 58/55/40/41-42%.

**Reading.**
- In 00-12 the date-only interval is the narrowest and the market-only interval the widest. The crossed W interval is
  the binding one and still excludes 0.
- No single market or single week carries the result. The smallest LOMO estimate is about 75% of the full estimate.
- Within the MG-1 family (four blocks, Holm 0.025/4), every block passes.
- Registry-wide, nothing passes: z -2.6 to -3.3 against 4.04.
- The 11-market t statistic (p 0.001-0.006) does not rescue it at 938 tests either.
- **The 15-16 harm of MG-1 is real on the date and market resamplings**, which exclude 0 on the harm side; W
  includes 0. It holds in both strata and in 9/11 markets. Any MG-1 composition must carry it as a known cost.

## 3. Availability vs outcome, and v2 staleness (d2)

**Coverage is not related to outcome.** Coverage by block (from stratum) is 98.0% in 00-05, 99.8% in 06-09, 99.9%
in 10-12 and 99.2% in 00-16. Every fallback is a snapshot with no floor.
- Served excess on the fallback rows is 0.0316 against 0.0258 on covered rows (n = 449 fallback snapshots). These
  rows are served under both arms, so they only dilute the all-row estimate.
- Across market-day cells, Spearman rho of fallback share against served excess is between -0.06 and +0.10 by block.
  Against the MG-1 delta it is between +0.01 and +0.08.

**Which v2 cycle MG-1 actually reads (from stratum).**

| Block | v2 cycle used (issued hour UTC) | Age since issue, h (p10/p50/p90) | Age since v2_available_at, h (p50) | Newer cycle rejected as target_max_not_in_cycle |
|---|---|---|---|---|
| 00-05 | 01Z (8,602), 07Z (8,868) | 1.9 / 4.2 / 6.7 | 2.1 | none |
| 06-09 | 07Z only | 4.3 / 6.4 / 8.7 | 5.1 | 12Z/13Z on 6,166 of 11,620 |
| 10-12 | 07Z only | 8.0 / 9.9 / 12.0 | 8.6 | 12Z/13Z on 100% |
| 13-16 | 07Z only | 11.2 / 13.4 / 15.7 | 12.1 | 13Z/19Z on 100% |
| 17-23 | 07Z only | 15.7 / 18.9 / 21.9 | 17.6 | 19Z/01Z on 100% |

v2_valid_time_utc is 00Z on target + 1 for every covered row, which is the target day's daytime maximum period.

What this means:
- **MG-1 is effectively "the 07Z NBP maximum, read all day".** This agrees with DESIGN section 0 ("NBM 07Z read
  already removes about half of 00-09's excess").
- Its afternoon staleness is structural: the parser rejects every later cycle.
- **Whether that rejection is correct for the 12Z/13Z NBP is a parser-v2 decision I did not verify.** It should join
  the value-verification follow-up (COMPLETENESS section 3).

**No staleness dose-response inside a block.** MG-1 - served by tercile of age since issue:

| Block | Fresh | Mid | Stale |
|---|---|---|---|
| 00-05 | -0.0141 (2.3 h, 10/11) | -0.0147 (4.2 h, 11/11) | -0.0147 (6.2 h, 11/11) |
| 06-09 | -0.0120 (4.7 h) | -0.0149 (6.4 h) | -0.0139 (8.0 h) |
| 10-12 | -0.0089 (8.4 h) | -0.0076 (9.9 h) | -0.0095 (11.3 h) |
| 15-16 (POST-HOC) | +0.0073 (13.1 h) | +0.0123 (14.2 h) | +0.0032 (15.9 h) |

Snapshot-level Spearman rho, from stratum:
- Age against the MG-1 delta: |rho| <= 0.024 in 00-12. Inside 00-16 it is +0.107, but that is between-block (later
  hours carry older guidance and smaller gains).
- Age against |settlement_high - v2_mean| (outcome only): |rho| <= 0.04 in every block.

**Conclusion of d2.** Availability and staleness are not associated with outcome in a way that could manufacture the
morning effect. The block-level decline of the gain (00-05 -> 10-12 -> 13-16) matches guidance age. The 15-16 harm
does not grow with age inside the block. So "stale guidance hurts at 15-16" is consistent at block level, but
within-block evidence does not show it.

## 4. t3-r3: registered 13-16 block and the POST-HOC 15-16 slice (d3)

| Contrast | Block | Estimate | W CI | Date-only | Market-only | LOMO range | LOWO range | Before | Markets neg | z | Bonferroni 938 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| t3-r3 - served | **13-16 (registered)** | **-0.0116** | [-0.0190, -0.0052] | [-0.0145, -0.0086] | [-0.0179, -0.0065] | -0.0129..-0.0093 (no CI incl. 0) | -0.0125..-0.0108 (no) | -0.0097 | 10/11 | **-3.26** | **fail** |
| t3-r3 - served | 13-14 (POST-HOC) | -0.0109 | [-0.0213, -0.0024] | [-0.0142, -0.0074] | [-0.0206, -0.0039] | (no) | (no) | -0.0070 | 9/11 | -2.16 | fail |
| t3-r3 - served | 15-16 (POST-HOC) | -0.0126 | [-0.0194, -0.0065] | [-0.0161, -0.0093] | [-0.0171, -0.0082] | (no) | (no) | -0.0126 | 11/11 | -3.78 | **fail** |
| t3-r3 - r1 | 13-16 | -0.0109 | [-0.0179, -0.0050] | | | (no) | (no) | -0.0090 | 10/11 | -3.24 | fail |
| t3-r3 - r1 | 15-16 (POST-HOC) | **-0.0113** | [-0.0173, -0.0057] | | | (no) | (no) | -0.0112 | 11/11 | -3.77 | fail |
| t3-r3 - r2 | 13-16 (comparator post-hoc) | -0.0107 | [-0.0166, -0.0051] | [-0.0149, -0.0064] | [-0.0128, -0.0086] | (no) | (no) | -0.0075 | 11/11 | -3.58 | fail |
| t3-r3 - r2 | 15-16 (slice and comparator post-hoc) | **-0.0181** | [-0.0251, -0.0112] | [-0.0230, -0.0133] | [-0.0213, -0.0148] | -0.0192..-0.0172 | -0.0207..-0.0152 | -0.0145 | 11/11 | -5.07 | nominal pass, **not admissible** |
| t3-r3 - r2 | 13-14 (POST-HOC) | -0.0032 | [-0.0089, +0.0023] | | | | | -0.0005 | 9/11 | -1.10 | fail |
| t3-r3 - r1 | 17-23 | +0.0035 | [+0.0011, +0.0056] | | | | | +0.0042 | 1/11 | +2.94 | t3-r3 worse than rung 1 |
| t3-r3 - r2 | 00-16 | +0.0058 | [+0.0012, +0.0099] | | | | | +0.0074 | 0/11 | +2.62 | t3-r3 worse than rung 2 |

**What the registered 13-16 block supports.**
- A within-block development effect of t3-r3 over served of about -0.0116 (48% of the block gap). It is robust to
  every resampling, LOMO and LOWO, and holds in both strata.
- It does not pass registry-wide multiplicity (z -3.26).
- It is also availability-fragile (R-PIT-T3: WEAK at +1 h).
- Against rung 2 over the full 13-16 block it is -0.0107, 11/11. That is the admissible way to state the residual
  claim, with the comparator flagged as built after t3-r3 was read. It still fails Bonferroni (z -3.58).

**15-16 is a POST-HOC slice.**
- It was chosen after the 13-14/15-16 split was seen (LADDER), and its multiplicity is not in the registry count. Its
  nominal z of -5.07 against r2 must not be read as passing Bonferroni.
- The -0.0181 combines t3-r3's own gain (-0.0113 against r1) with the +0.0068 harm that MG-1 adds to rung 2 at 15-16.
  So the "largest residual is 15-16" framing is partly created by the rung-2 composition.

## 5. SYNTHESIS.md claims checked

Recomputed and matching (to 4 dp):
- Table A r2 delta vs r1: 00-05, 06-09, 10-12, 13-16, 13-14, 15-16, 17-23, 00-16 and all, each with its interval and
  market count.
- r2 - market at 13-16, +0.0231 [+0.0173, +0.0289], and at 15-16, +0.0270 [+0.0204, +0.0337]. The 00-16 residual is
  +0.0141 [+0.0098, +0.0186].
- MG-1 00-16 -0.0100 [-0.0179, -0.0035] 10/11, b -0.0122. MG-1 gap closed 58/55/40/41%.
- t3-r3 13-16 -0.0116 [-0.0190, -0.0052] 10/11, b -0.0097; t3-r3 15-16 -0.0126, 11/11; t3-r3 - r2 at 15-16 -0.0181
  [-0.0251, -0.0112] 11/11; t3-r3 17-23 -0.0219 [-0.0327, -0.0131].
- Section 7 "do not pass": MG-1 00-16 z -2.7 (mine -2.70) and t3-r3 13-16 z -3.3 (mine -3.26).

Flags (no contradicted number, but correct the wording):
1. **Sections 0.3 and 6.1, "t3-r3 beats rung 2 at 15-16 by -0.0181 ... the largest residual is ... mostly 15-16".**
   - This is a POST-HOC slice with a post-hoc comparator.
   - 0.0068 of the 0.0181 is MG-1's own harm. Against r1 the figure is -0.0113.
   - State the registered 13-16 figure first: t3-r3 - served -0.0116, z -3.26, fails Bonferroni; or t3-r3 - r2
     -0.0107, 11/11, z -3.58, fails.
   - Do not present 15-16 as passing multiplicity. The canon draft repeats 15-16 as the finding, and it needs the
     same correction.
2. **Section 1.2, "At 15-16, MG-1's stale whole-day guidance hurts (EF 10p)".**
   - Consistent at block level: the 07Z cycle is about 14 h old there.
   - Not supported within the block: no age gradient across the 15-16 terciles.
   - The harm's W interval includes 0; only the date-only and market-only intervals exclude it. Say "consistent with",
     not "is".
3. **Section 7 approximate z values.** Mine are r1 17-23 -5.46 (synthesis about -5.6), t3-r3 17-23 -4.22 (about
   -4.4) and r2 - served all hours -3.60 (about -3.7). None changes a pass/fail.
4. **Section 6.1 survivor wording for MG-1.**
   - It survives the statistics refutation on resampling robustness, not on multiplicity.
   - Its input is effectively a single 07Z NBP cycle from 06 local onward, because later cycles are parser-rejected.
     That rejection should be listed as an unverified validity condition beside the value re-derivation.

## 6. Files

- C:\swarm\out\r-stat-mg1\stats.json: every table, the per-market deltas, and the LOMO/LOWO detail.
- run.log, reg.py (registration).
- Code: C:\pt\swarm\tools\research\model_parity\r-stat-mg1_refute.py.
