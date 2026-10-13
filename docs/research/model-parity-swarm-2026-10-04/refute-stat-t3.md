# refute-stat:T3 report (development)

(Reconstructed by the orchestrator from the agent's returned summary; the agent did not leave a report.md. Detail files are in C:\swarm\out\refute-stat-t3.)

**Verdict/status:** disqualified=False

R-STAT-T3 verdict: NOT DISQUALIFIED (development only). 17-23 is robust; 13-16 survives but is fragile. Note: the harness blocked writing report.md and the docs copy refute-stat-t3.md, so neither exists. The full analysis is in C:\swarm\out\refute-stat-t3\result.json and the code is C:\pt\swarm\tools\research\model_parity\r-stat-t3_refute.py.

1) My own scoring (own floor mask, matching the harness on 100% of band rows; own Brier and cell means) reproduces T3 exactly: 17-23 from -0.021906 (before -0.025375); 13-16 from -0.011643 (before -0.009721). 0 rows after 2026-09-29.

2) 17-23: every interval excludes 0. Six methods: W replicate [-0.0327,-0.0131], own crossed bootstrap with seed 777123 [-0.0331,-0.0134], date-cluster, market-cluster [-0.0315,-0.0145], two-way cluster-robust, and market t(10) [-0.0322,-0.0116]. A Bonferroni interval over the 40 registry rules is [-0.0387,-0.0052]. 11/11 markets and 36/36 dates are negative, and all 7 ISO weeks are negative. Leave-one-market-out runs -0.0180 to -0.0237 and leave-one-week-out -0.0203 to -0.0238. No market carries more than 25% of the total. The +1 h variant (t3-r3s) gives -0.0216, still LEAD.

3) 13-16 r3 is LEAD under all six methods, 10/11 markets negative (sign p=0.012). Its size passes only the 5%-of-gap bar (about -0.0012), not the -0.0133 line. Bonferroni-40 excludes 0 only by a hair (upper bound -0.0001). Under t3-r3s it is -0.0071, 8/11 markets (p=0.23), fails Bonferroni, and LA carries 42% of the total. It is a lead that depends on fresh METAR.

4) Multiplicity: 40 registry rules at my run, 8 of them self-labelled controls or sensitivities. The synthesis must use the final count. T3 registered at 00:44:34, before its first score at 00:46:24. Its code matches the registered constants, and I found no unregistered variants.

5) Coverage is not selected on outcome: fallback is under 1% of rows in 13-23, matched equals all-row, and rows with METAR gaps show smaller benefit, not larger. The 00-05 fallback (20.7%) is outcome-neutral. 00-16 is WEAK under every method.

**Defects:**
- Not disqualifying: the 13-16 LEAD relies on the lax 5%-of-gap bar. It fails the -0.0133 line under every leave-one-market-out drop, and under +1 h latency it fails Bonferroni-40 and the market sign test, with LA carrying 42%.
- Not disqualifying: the 13-16 r3 Bonferroni-40 upper bound is -0.0001, which is marginal. The multiplicity count must be redone with the final registry size.
- Process: the harness refused to let this subagent write report.md and the docs copy refute-stat-t3.md. Neither file exists; result.json and the phase_log line exist.
