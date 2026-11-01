# F8-MH S0 receipt (L16, 2026-10-31, ledger row 104)

S0 ran once, after the freeze commit `61b7a470bb22902735fda5c2575a0379ee277d7f` was pushed, under `s0_spec.md`
(sha256 `795dd5091fdbaec702bd74ed650748f892e906710869140f3f8e42631ff026e8`). History only; no forward date, label,
price or daily maximum was read.

- Script: `tools/research/forward_f8/f8_mh_s0.py`, sha256 `768395c6097d630bf555e1a8cbbbf6b47fc775b2fc777771d05f41885382687e`,
  committed and pushed at `00e8c10b291fa09eb98f70b3e9bdeaf3052e0a92` before the run; never edited.
- Run: direct (light: 1.9 s wall, 212,697 rows read), cwd this tree, `PYTHONPATH=<tree>\src`.
- Receipt: `C:\t\l16\f8-s0\run1\s0_receipt.json`, sha256
  `8ec7182147f0ee7d1792c21b6473c782bfcef127a2f9f1ad527f9f5228e5fe9e`; log `C:\t\l16\f8-s0\run1.log`, sha256
  `d4a209174ba586071470c545a7f7d40f1994ae79f50b4e70e1761d3af0854947`.
- Inputs: `obs.parquet` sha256 `37d97195828d9f58d510f078e3029d53ed051fe471c4a94333bb0cc51f6d28f2`, `selection.json`
  sha256 `a23f4cba11c0ec1666e7069cc89c93f699e5573546c048be4e398070cc1fb199`. US10; 460 Oct-Dec dates 2021-25;
  5 ambiguous DST instants skipped per market.

## Result (primary, Oct-Dec rates, window D = 85)

| Quantity | Value | Floor |
| --- | --- | --- |
| Regime market-hours in history | 6,539 (of about 27,600) | |
| Cells with λ ≥ 2 | 49 of 60 | |
| Projected dates | 85.0 (every history date has a regime market-hour) | ≥ 20 |
| Projected population market-day-hours | 1,207.5 | |
| Projected snapshots | 8,631 | ≥ 1,000 |
| Projected power at deff 2 | 0.99999 | ≥ 0.5 |

Mean regime rate by hour across markets: h01 0.000, h02 0.072, h03 0.194, h04 0.324, h05 0.402, h06 0.430.
Nov-Dec-only disclosure (non-deciding): 85.0 dates, 8,016 snapshots, power 0.99999.

**Verdict: S0 PASS (arm stays open).** Nothing forward is read until the look gate (freeze §4).

## Observation for master (descriptive, not a change to the freeze)

The frozen flag fires on 32-43% of market-hours at 04-06. With the NBM gate dropped, t_H ≤ 01:59 and H − C ≥ 3 °F
also hold on ordinary nights of steady radiative cooling, when the running max is set by the first routine report
and the day later warms well above H. So the frozen regime is mostly "a normal cooling night", not only "a midnight
high from a front", and the look would test the type C tilt toward H on that wider population. Whether that still
measures the accepted mechanism is master's ruling. Any change would be a dated clarification before the look, and
no forward date has been read.
