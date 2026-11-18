# L11 market blend (2026-10-25): does a walk-forward log pool of market and candidate beat the market?

Development evidence only (C dev scorecard window; scored 2026-08-15..09-29, 43 dates x 11 markets = 473
market-days; burn-in 08-01..08-14). Rule: [`rule.md`](rule.md), sha256
`e29c9a84395d7f4f5e9a0091da99ff970597c40faa7d4cc81aa034a373f8bb8c`, committed (`e875bb4a2`) and pushed before
any blend row. Code: `weather.calibration.market_blend` (this branch). Run: `C:\t\l11\run1` through
`workstation_heavy.ps1`; rows JSON sha256 `1d9fc6d366170e91d66d67ce4229c663dd590514c83a3582c5cf00290aaa91b7`;
full rendered table: [`results-run1.md`](results-run1.md).

## Controls (all PASS)

Served vs market R 1.774 / 1.526; MG-1 07-12 excess over market 0.0120 (0.011957); L6 own-stack 07-12
Brier − MG-1 −0.0036243; w = 0 identity for both candidates (max abs diff 0.0, R = 1.0 exactly). Placebo
(vectors deranged across dates within market x hour): MG-1 mean w 0.005, R 1.0014; composite mean w 0.007,
R 1.0016 — both PASS.

## Primary (ALL 11 markets, 07-12, pooled 07-12 Brier fit), crossed [date-clustered] 95%

| Candidate | R(blend) vs market | mean w (min..max) | MDE80 | Reading |
| --- | --- | --- | --- | --- |
| MG-1 | 1.0017 [0.9990, 1.0077] [0.9995, 1.0051] | 0.008 (0.00..0.06), 25/43 dates w = 0 | 0.004 | NOTHING: the model adds nothing to the market |
| Composite pre-13 (MG-1 + L6 own-obs stack) | 0.9994 [0.9931, 1.0062] [0.9956, 1.0037] | 0.073 (0.00..0.11), rising from ~0.03 in August to ~0.10 by late September | 0.006 | INCONCLUSIVE: w > 0, no increment over the market demonstrated |

Floor-only control (market + hard floor, w -> 0+): ALL 07-12 R 1.0010 [0.9984, 1.0072].

## Secondary, in brief

- PRIMARY5 07-12: MG-1 1.0010 [0.999, 1.004]; composite 0.9988 [0.990, 1.008].
- 13-16 (MG-1 only; the composite's 13-16 waits for the L3 arm A refit, `C:\t\mg2\control_refit_armA.json`
  absent at this run): MG-1 blend ALL 0.9858 [0.965, 1.026], PRIMARY5 0.9791 [0.963, 0.991], w pinned at the
  grid's smallest positive value 0.01 — and the floor-only control is the same size (ALL 0.9845, PRIMARY5
  0.9776 [0.962, 0.989]). The afternoon "gain" is the hard floor zeroing market mass on buckets already below
  the observed high, not MG-1 information.
- Log loss: the log-fitted w is ~0 for both candidates (0.008, 0.007); log ratios at 07-12 ALL are > 1
  (1.012, 1.005), driven by Miami (floor-only log ratio ALL 07-12 1.0096; PRIMARY5 0.998), where the rule-4
  floor sometimes zeroes the settled bucket.
- Per-market w (descriptive): MG-1 largest in Miami 0.24, Denver 0.15, Los Angeles 0.14; composite in San
  Francisco, Miami, Houston, Denver ~0.25; Atlanta, Austin, Chicago, Seattle ~0.
