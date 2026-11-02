# Market reliability by bin on US11: result (row 106)

**Status: CLOSED, KILL at edge size (2026-11-02).** This note records the single real run of the frozen
[pre-registration](README.md) (revision 2, sha256 `7619aea1…`). The README is frozen and is not edited.

- **Owns:** the row 106 run's verdict, statistics and receipt pointers.
- **Read when:** citing the US11 market-calibration result, or proposing any market-only recalibration.
- **Do not use for:** any edge, fair-value or model claim. A KILL closes the question at edge size for US11 on
  the dev window; it says nothing about the overround (maker economics are CLOSED).

## Run

- **One direct run** under the README's section 9 queue exception, launched 2026-11-02 11:06:56 EST:
  - after the L53 suite finished and the pre-flight passed (13.45 GB available, thread caps 10, no heavy mutex);
  - exit 0, 38.33 s, peak 1312 MB, stderr empty.
- **Code:** script `run_reliability.py` sha256 `df12cc8cab980b2af71c55942ce9ec9bbc8422d17c5852bdfc7ae332e421f7a3` at
  tip `e7eac94eaaa7ad79060af01a3012c067e5cb3590`.
- **Binding:** the pushed branch `claude/market-reliability-bin-prereg-20261101` at `e7eac94ea` (prereg `e541ad401`,
  ledger row 106 line sha256 `40a9b6f6…`), not master. This satisfies
  [method](../../operations/MODEL_IMPROVEMENT_METHOD.md) section 4, per master's 2026-11-02 ruling.
- **Receipt:** `real_run.json`, file sha256 `7f43359474b09e2fad5ab51b7ac06909705037eacf122c7e2ac9652b533ead5f`. The
  script printed `receipt_sha256` `ea6bca1d49a272e3f1521ea39b13d1331e6662558e02ff8479c1087f403c5a7e`, hashed over the
  JSON text before it was written.
- **Archive:** `C:\archive\ruled-out\market-reliability-bin-us11\` (workstation-local), SHA256SUMS sha256
  `cfc208b8b4282e5eed28df336bcc26fe1d9fef02f2c03739b0cb98c6a3bc657c`.

## Verdict

"US11: KILL at edge size (all three arms below Delta 0.2236)" (receipt, verbatim).

| Arm | Δ | Widest 95% interval | Kill condition | Realised power at 0.2236 |
| --- | --- | --- | --- | --- |
| A1 linear | 0.0344 | [0.0156, 0.0534] | inside (−0.2236, 0.2236) | 1.000 |
| A2 binned LODO | 0.0400 | [−0.0320, 0.0793] | upper < 0.2236 | 1.000 |
| A3 power LODO | 0.0430 | [−0.0875, 0.0868] | upper < 0.2236 | 0.9998 |

Δ is the cosine Δ on the residual y − m̃. The interval is the widest of three date bootstraps (seed 20261024).

## Controls (C2 order, all PASS)

1. **Positive control:** served versus market R 1.7739 (all hours) and 1.5263 (00-16), against 1.774 and 1.526.
2. **Synthetic controls:** identical to the revision 2 dry run.
   - Null: A1 0.0010 [−0.0051, 0.0073], A2 −0.0114 [−0.0385, 0.0122], A3 −0.0235 [−0.0444, 0.0105].
   - Planted: A1 0.0896, A2 0.1685, A3 0.1877, with A3 widest lower 0.1718.
3. **Training-score check on real labels:**
   - β̂ 1.13;
   - Brier 5451.946 at β̂ against 5466.966 at β = 1;
   - F3 relative difference 9.5e-11.
4. **Realised power:** SE (widest of three) 0.0095 / 0.0272 / 0.0404 for A1 / A2 / A3.

## Population and exclusions

- 57 dates (08-01..09-29; 08-16, 09-01 and 09-02 are absent from the layout), 11 markets, 626 market-days.
- 14,969 ladders.
- 164,659 band rows, of which 121,288 were scored. The 43,371 floor-impossible rows were excluded, with 0
  disagreements against the layout flag.
- 0 incomplete and 0 zero-price ladders were dropped. Toronto is out (no price in the layout).
- The layout manifest was unchanged.

## Descriptive (non-deciding)

- Crossed date × market 95%: A1 [0.0027, 0.0679], A2 [−0.0818, 0.1032], A3 [−0.1765, 0.1146].
- ECE 0.0067.
- Calibration line: slope 1.030 (widest [1.014, 1.045]), intercept −0.0027.
- LODO β by date: 1.11-1.14.
