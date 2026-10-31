# R-L2 summary: NBS TXN at 07-12, format-defined cycle choice — KILLED at gate 3

- **Evidence class:** development evidence only.
- **Rule:** `rule_rl2.md`, sha256 `a1f95786d439bf619bce793d3958373f8bd0d79cd6aa6c25580546f90b4bf2b3`, registered
  and pushed (`528b3b0ed`) before any fit.
- **Corpora:** L12's sealed corpora. SHA256SUMS `2c5fc33a…7b86` (training) and `dd2b7ac4…7887` (dev), pinned and
  verified in code.
- **Code:** `RlNbsCorpus(cycle_rule="txn_bearing")` and `--variant R-L2` on `rung-l-loyo`, `rung-l-dev-emit` and
  `rung-l-score`; test `test_rl2_cycle_rule.py`.
- **Data limits:** nothing dated after 2026-09-29 was read.

## Gates (in the registered order)

| Gate | Result |
| --- | --- |
| 1a parity, training | PASS: coverage 19,657/19,657 (1.000); zero sha, parse, identity or range failures; median \|n_txn − nbm\| 1.0 °F |
| Control: R-A 07-12 LOYO reproduction | PASS: same keys, max \|Δ\| 0 |
| 2 LOYO, B_L − B_N, 07-12 | **PASS**: −0.0279 [−0.0308, −0.0248]; every hour from h07 to h12 excludes 0 |
| 1b parity, dev | PASS: coverage 28,455/28,755 (0.990), with 217 `no_cycle` and 83 `no_txn_cycle`; median \|n_txn − nbm\| **0.0 °F** |
| Controls: R-A dev files byte-identical (`83cf9bbe`, `cd0034b9`); MG-1 0.012 | hold |
| 3 dev, P3d_L − P3d_N_fix dR, ALL, 07-12 (21,664 snapshots) | **FAIL**: −0.0123 [−0.0283, +0.0038] |

**Pre-registered KILL:** NBS TXN is closed as a 07-12 centre input under R-L's and R-L2's cycle rules alike. No other
TXN or XND transform, cycle rule, margin, column or age bound runs as a 07-12 centre input on any NBM-anchored arm.
Gate 4 was not read.

## Reported only

- **LOYO P3d_L − P3d_N_fix, 07-12:** −0.0287 [−0.0318, −0.0256].
- **Dev gate 3 per hour:**

  | Hour | dR |
  | --- | --- |
  | h07 | +0.0042 |
  | h08 | −0.0089 |
  | h09 | +0.0036 |
  | h10 | −0.0087 |
  | h11 | −0.0257 [−0.0478, −0.0052] |
  | h12 | −0.0441 [−0.0730, −0.0150] |

- **Dev B_L − B_N, 07-12:** −0.0151 [−0.0301, −0.0014].
- **Gate 3 per market:** nyc −0.1126 [−0.1975, −0.0414] is the only interval below 0. los-angeles is +0.0443 and
  chicago +0.0286.
- **Staleness (the cost stated in the rule).** At h10-h12 the selected cycle is 12Z on almost every row. The newest
  eligible cycle was skipped on 72% (h10), 99.6% (h11) and 100% (h12) of dev rows. Median selected age is 3, 4 and
  5 h, against about 1 h for the newest cycle. At h07 nothing was skipped.
- **Train/dev anchor difference (observation; not a gate and not a reopening).** The median |n_txn − anchor| is
  1.0 °F in training, where the anchor is L9's `nbm_at_cutoff`. On dev it is 0.0 °F, where the anchor is the
  captured `usable_v2_mean`.
  - So `n_gap` is near 0 on most dev rows but is not in training.
  - That is one plausible reason the large LOYO gain did not carry over to dev.
  - Both anchors are R-L's registered ones. Under the kill, no re-anchored NBS variant may be run at 07-12.
- **The rule's limits:** R-L2 cannot test R-H hypothesis 2's freshness claim, and this result does not adjudicate it.

## Artifacts (`C:\t\l2\rungl2\`)

| File | sha256 |
| --- | --- |
| `loyo/rl_loyo_audit.json` | `5821ef01…28f0` |
| `loyo/loyo_rows.jsonl` | `b0129c3d…c4d1` |
| `emit/rl_emit_audit.json` | `8e987186…d27e` |
| `emit/dev_B_L.jsonl` | `451c392a…b98d` |
| `emit/dev_P3d_L.jsonl` | `00b5fbd1…bd2c` |
| `score/rl2_score.json` | `a0a56910…3f55` |
