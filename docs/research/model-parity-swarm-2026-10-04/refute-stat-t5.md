# R-STAT-T5: statistics refuter for T5 (t5-r1, NBH latest cycle, remaining-hours max). Development only.
(report.md was blocked by the subagent tool guard, so this text is stored in result.json under report_md.)

## Verdict, judged block by block
Overall: the candidate is NOT disqualified. 17-23 and 06-09 stand. The maker-relevant 00-16 claim does NOT stand as a LEAD.

- 17-23 (hunter: LEAD) STANDS, but it is the decided-band collapse mechanism (T1 family), not NBH guidance skill.
  - It survives every test: LOMO, LOWO, Bonferroni (63 rules), 11/11 markets, both strata.
  - 97.4% of from-stratum 17-23 snapshots are collapse rows (NBH remaining max <= floor bucket - 1), and they carry 98.9% of the delta.
  - With the collapse rows set back to served, the effect is -0.0003 [-0.0016, +0.0003] with 4/11 markets negative.
  - Paired T5 - t3-r3: -0.0063 [-0.0080, -0.0046], 11/11 markets, before -0.0066.
  - Paired T5 - T1-r2: -0.0018 [-0.0036, -0.0005], 10/11 markets, before -0.0025.
  - Do not add it to T1's 17-23. Only the -0.0018 increment over T1-r2 belongs to NBH.
- 06-09 (LEAD) STANDS, with a one-week caveat.
  - Every LOMO keeps the interval below 0 and >= 8/10 markets negative. Sign test p = 0.033.
  - Dropping week W36 lifts the upper bound to +0.0005.
  - It is not Bonferroni-robust.
  - Paired vs t3-r3: -0.0062 [-0.0140, +0.0026], so no significant marginal value.
- 00-05 (LEAD) DOES NOT STAND and is downgraded to WEAK.
  - Nominal conditions hold under my computation.
  - LOMO: dropping any one of 6 markets puts the W interval across 0, and 8 of the 11 drops leave 7/10 negative.
  - LOWO: dropping W36 or W38 puts the interval across 0.
  - Sign test p = 0.11.
  - Paired vs t3-r3: -0.0062 [-0.0133, +0.0014].
- 13-16 (LEAD) is DISQUALIFIED as an NBH lead. It is the remaining-rise / floor-collapse family in disguise.
  - 51% of snapshots are collapse rows and carry 78% of the delta.
  - Non-collapse-only: -0.0022 [-0.0066, +0.0019], NULL.
  - t3-r3 alone does better: -0.0116 vs T5's -0.0097.
  - Paired T5 - t3-r3: +0.0019 [-0.0027, +0.0073], 4/11 markets negative.
  - The seed-777 crossed interval upper bound is -0.000006, i.e. on 0.
  - Dropping LA, NYC or SF crosses 0, and so does dropping W36 or W40.
- 00-16 (LEAD) DOES NOT STAND and is downgraded to WEAK (fragile).
  - Exactly 8/11 markets negative.
  - Dropping any one of 5 markets (austin, dallas, LA, nyc, SF) crosses 0, and every drop of a negative market leaves 7/10.
  - Dropping W36 crosses 0 (+0.0009).
  - Sign test p = 0.11. The Bonferroni interval crosses 0.
  - Paired vs t3-r3: -0.0030 [-0.0084, +0.0032], so no demonstrated marginal value over the remaining-rise rung.
- 10-12: WEAK confirmed (interval spans 0, 7/11 negative, T5 - t3-r3 = +0.0012).
- all: stands, but 68% of its delta comes from collapse rows (driven by 17-23).

Answer to the question I was set: yes, the 17-23 effect is a known mechanism in disguise. It is the T1 decided-band collapse, not the t3-r3 remaining-rise climatology (T5 beats t3-r3 by 0.0063).
- In 17-23 the NBH forecast for the remaining hours is almost always below the running max, so >= 93% of the mass goes to the floor band.
- In 00-09 the effect really comes from NBH guidance. Collapse rows are only 1-2% there, and non-collapse-only 00-16 = -0.0058 [-0.0109, -0.0004], 8/11.
- But only 06-09 survives the robustness checks.

## What I recomputed independently
- Probabilities: rebuilt with the hunter's own builder (t5_nbh_latest.build_candidate, sha256 bd97821b... unchanged). PIT re-derivation of the NBH inputs belongs to the PIT refuter.
  - Reasons: covered 109,399, no_floor 730, no cycle or uncovered hour 678. These match the hunter.
- Everything downstream is my own code, not the harness:
  - floor mask: agreement with the harness flag 1.000000;
  - renormalisation, per-snapshot Brier, cell means, per-market and per-week aggregation, LOMO/LOWO;
  - bootstraps: W, plus my own crossed date x market multinomial (seed 777), date-cluster only, market-cluster only, an 11-market t interval, and Bonferroni normal with z = 3.355 (63 registry rules at run).
- Both the harness re-score and my code reproduce the hunter exactly (17-23 -0.028234, 00-16 -0.007295, all -0.013343).
- Paired rungs: t3-r3 probabilities from refute-stat-t3/cand_r3.parquet and T1-r2 per-snapshot Brier from refute-stat-t1/snap_scored.parquet. Both reproduce their hunters' from-stratum estimates exactly (t3-r3 17-23 -0.021906, 13-16 -0.011643; T1-r2 17-23 -0.026412).
- Code: C:\pt\swarm\tools\research\model_parity\r_stat_t5_refute.py.
- Outputs: C:\swarm\out\refute-stat-t5\result_stats.json, snap_scored.parquet, cand_t5_r1.parquet.
- HARNESS_SHA256 8db69adc7fb9bee8c3db47707b8aea71bff825a415b950108e19e84a0fd29f74. Rows after 2026-09-29: 0.

## From-stratum all-row t5-r1 - served (development)
block | est | W 95% | seed777 crossed | date-cluster | market-cluster | Bonferroni(63) | mkts neg | sign p | before
00-05 | -0.00726 | [-0.01403,-0.00061] | [-0.01393,-0.00088] | [-0.01030,-0.00442] | [-0.01197,-0.00269] | [-0.0183,+0.0038] | 8 | 0.113 | -0.00639
06-09 | -0.00837 | [-0.01493,-0.00146] | [-0.01511,-0.00162] | [-0.01136,-0.00533] | [-0.01340,-0.00336] | [-0.0197,+0.0030] | 9 | 0.033 | -0.00936
10-12 | -0.00288 | [-0.01035,+0.00531] | [-0.01072,+0.00534] | [-0.00691,+0.00080] | [-0.00871,+0.00331] | [-0.0165,+0.0107] | 7 | 0.274 | -0.00739
13-16 | -0.00971 | [-0.01951,-0.00099] | [-0.01979,-0.00001] | [-0.01375,-0.00560] | [-0.01798,-0.00222] | [-0.0259,+0.0065] | 9 | 0.033 | -0.00870
17-23 | -0.02823 | [-0.03997,-0.01881] | [-0.04053,-0.01858] | [-0.03186,-0.02457] | [-0.03839,-0.02003] | [-0.0468,-0.0096] | 11 | <0.001 | -0.03200
00-16 | -0.00730 | [-0.01359,-0.00091] | [-0.01372,-0.00085] | [-0.01007,-0.00467] | [-0.01227,-0.00237] | [-0.0181,+0.0035] | 8 | 0.113 | -0.00772
all   | -0.01334 | [-0.02039,-0.00651] | [-0.02076,-0.00646] | [-0.01596,-0.01077] | [-0.01944,-0.00777] | [-0.0253,-0.0014] | 10 | 0.006 | -0.01487

## One market or one week? (from stratum, all-row)
block | LOMO est range | LOMO: interval crosses 0 | LOMO: <8 neg | LOWO est range | LOWO: interval crosses 0 | top market share | top week share
00-05 | -0.0060..-0.0083 | 6/11 | 8/11 drops | -0.0067..-0.0083 | W36, W38 | 25% | 24%
06-09 | -0.0071..-0.0097 | 0/11 | 0 | -0.0077..-0.0096 | W36 (+0.0005) | 23% | 21%
13-16 | -0.0066..-0.0118 | 3/11 (LA, nyc, SF) | 0 | -0.0088..-0.0105 | W36, W40 | 38% (LA) | 21%
17-23 | -0.0241..-0.0302 | 0/11 | 0 | -0.0271..-0.0301 | 0/7 | 22% | 23%
00-16 | -0.0058..-0.0086 | 5/11 | 8/11 drops | -0.0066..-0.0081 | W36 (+0.0009) | 28% (LA) | 21%

- No point estimate is carried by a single market or week.
- What does hinge on single markets or weeks is the LEAD classification (the interval and the 8/11 condition) in 00-05, 13-16 and 00-16.
- 00-16 per-market: Houston, Miami and Seattle are positive. LA (-0.022) and Dallas (-0.017) carry the most.

## Marginal value over the remaining-rise rung (paired, same W)
block | T5 - t3-r3 from [W] | mkts neg | before | t3-r3 - served (from) | T5 - T1-r2 from [W]
00-05 | -0.0062 [-0.0133,+0.0014] | 9 | -0.0041 | -0.0010 | = T5 - served (T1 inactive)
06-09 | -0.0062 [-0.0140,+0.0026] | 9 | -0.0042 | -0.0021 | = T5 - served
10-12 | +0.0012 [-0.0056,+0.0098] | 6 | -0.0040 | -0.0041 | -0.0029 [-0.0104,+0.0053]
13-16 | +0.0019 [-0.0027,+0.0073] | 4 | +0.0010 | -0.0116 | -0.0061 [-0.0139,+0.0015]
17-23 | -0.0063 [-0.0080,-0.0046] | 11 | -0.0066 | -0.0219 | -0.0018 [-0.0036,-0.0005] (10/11)
00-16 | -0.0030 [-0.0084,+0.0032] | 8 | -0.0028 | -0.0043 | -0.0064 [-0.0125,-0.0002]

## Collapse decomposition (from; collapse = NBH remaining max mu <= floor bucket - 1)
block | collapse share | mean delta collapse / other | share of delta from collapse rows | T5 with collapse rows -> served
00-05 | 1.6% | +0.014 / -0.0078 | -3% | -0.0075 [-0.0139,-0.0011], 8/11
06-09 | 1.0% | +0.001 / -0.0086 | ~0% | -0.0084 [-0.0148,-0.0015], 9/11
13-16 | 51% | -0.0147 / -0.0043 | 78% | -0.0022 [-0.0066,+0.0019], 8/11
17-23 | 97.4% | -0.0286 / -0.0122 | 99% | -0.0003 [-0.0016,+0.0003], 4/11
00-16 | 14.7% | -0.0100 / -0.0068 | 20% | -0.0058 [-0.0109,-0.0004], 8/11

## Availability vs outcome
- Coverage by block (from stratum): 95.3 / 98.0 / 99.9 / 99.9 / 99.7%.
- In 00-05 and 06-09 the served - market gap is the same on covered and fallback rows (0.0245 vs 0.0233; 0.0253 vs 0.0257).
- Matched and all-row differ by <= 0.0004.
- Delta does not depend on cycle age: 00-16 by age tercile (0.9 / 1.3 / 1.7 h) = -0.0079 / -0.0070 / -0.0076. The age-delta correlation is between -0.03 and +0.02 in every block.
- I found no association between availability and outcome.

## Forking paths
- T5 registered 3 rules: r1 is the zero-parameter headline, declared before scoring; r2 is history-calibrated; d1 is a +60 min diagnostic. All three give identical classes, so there was no within-agent selection.
- The registry held 63 rules at run time. Bonferroni over 63 leaves only 17-23 and all excluding 0.
- 00-16 (upper bound -0.0009, exactly 8/11) is the profile of a marginal pass under multiplicity.

## Defects
None in the computation: reproduction is exact and the floor mask agrees. The disqualifications are interpretive and come from robustness checks:
1. 13-16 is the remaining-rise / floor-collapse family. t3-r3 beats T5 there, and the non-collapse NBH effect is NULL.
2. 00-05 and 00-16 classifications hinge on single markets and on week W36. The sign tests are not significant, and there is no marginal value over t3-r3.
3. 17-23 belongs to the T1 decided-band mechanism and must not be counted additively. Only the -0.0018 increment over T1-r2 belongs to NBH.
