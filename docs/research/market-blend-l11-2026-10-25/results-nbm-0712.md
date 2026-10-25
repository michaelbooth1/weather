# Item 5: P3d_N (NBM) log-pool blend at 07-12 vs the market (lane L11, 2026-10-25)

Development evidence only.

- Rule: `market_blend_rule_nbm0712.md`, sha256 `94b1603a407dd66ccb6137468cc3e703e00f73024209997c3181e26ed8a07e84`,
  prereg PASS. It was recorded before any row.
- Machinery: run 2's, unchanged. The candidate is P3d_N `721ae2cd…` in place of MG-1+L6.
- L9's N1 was dropped, because no 07-12 vectors exist for it.
- Code: `2691d9d36`, run through `workstation_heavy.ps1`.
- Rows: `C:\t\l11\nbm0712\market_blend_rows.json`, sha256
  `85ef656f1b5544e19745806167457e68c0968f51ccf5540f39edae8708342645`.
- Controls, all PASS: served; MG-1 excess 0.0120; MG-1's run-2 07-12 R 1.0016629 reproduced; the fit vector equals
  the score vector; the w = 0 identity. The placebo also passed: mean w 0.004, R 1.0013.
- Candidate coverage at 07-12 is 0.999.

## Reading (pre-registered): NOTHING

The mean walk-forward w at 07-12 is **0.0051**, below the 0.05 bar, and 28 of 43 dates have w = 0. **The NBM model adds
nothing to the market before 13:00.**

| Row (blend vs market) | R | crossed 95% CI | date 95% CI |
| --- | --- | --- | --- |
| 07-12 ALL (primary) | 1.0013 | [0.9992, 1.0075] | [0.9996, 1.0043] |
| 07-12 PRIMARY5 | 1.0003 | [0.9995, 1.0015] | [0.9999, 1.0009] |
| h07 / h08 / h09 ALL | 1.0006 / 1.0006 / 1.0009 | | |
| h10 / h11 / h12 ALL | 1.0014 / 1.0011 / 1.0037 | | |

The floor-only control for 07-12 ALL is R 1.0010. The MDE80 is 0.0038.

## DESCRIPTIVE only (not for a decision): P3d_N alone vs the market

This is the first 07-12 read of P3d_N; it had not been computed or seen before this run.

| Pool | 07-12 R | crossed | date |
| --- | --- | --- | --- |
| ALL | 1.1912 | [1.1024, 1.2944] | [1.1395, 1.2481] |
| PRIMARY5 | 1.1875 | [1.0335, 1.3872] | [1.0986, 1.3012] |

Per hour on ALL, R runs from 1.18 to 1.21. Unblended, P3d_N is about 19% worse than the market in Brier at 07-12, so
the walk-forward w correctly keeps it near zero. The full per-hour tables are in `market_blend.md` next to the rows.
