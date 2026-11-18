# Tenths-°C to whole-°F aliasing (lever map rank 9): KILL, premise false at S1

Lane L8, 2026-10-30. A batch note for the coordinator's morning docs batch. It has no ledger row and no P0.

## Provenance

All three files are in `C:\t\l8tor\tenths\`.

| Item | File | sha256 |
| --- | --- | --- |
| Stated reason, with the kill rule written before any data read | `tenths_reason.txt` | `a378ae65a47fd1c01d3d3e3c4f77ed8d6277916bc601b1945b4fdf0f0e464805` |
| S1 script | `tenths_s1.py` | `d34329da7ef8af3c3dd6cff475e83b4a07dbe48646d77ca6b4b0f8f4629bce5e` |
| S1 output | `tenths_s1_out.json` | `ded3421c2217dfd04dcd0aa3eec61b72ecb721066ae4da350ce6091fe58bff39` |

## Kill check

The register, RETRACTED and ledger rows 85-91 have no entry by name (alias, tenths, bucket mapping).

In the settlement-mechanics family, SYNTHESIS T16 recorded that "ASOS T-groups are whole °F except at KBKF". T16
was the evening floor-headroom question, not band mass, so it predicted this result but did not kill it by name.

## Premise

LEVER_INVENTORY row 16 assumed that each whole °F is reachable from 5 or 6 METAR tenths-°C values. If so, integer
°F buckets would be mis-massed by about ±4-5% relative, which is 1e-4 to 5e-4 Brier.

## S1

The S1 checked measurement resolution only. It read 2021-2025 history files, with no maxima, labels, forecasts or
prices, and ran in 17 s. Each routine value was tested for being the exact tenths-°C image of a whole °F.

Kill rule, stated before any read: if at least 95% of values are whole-°F images at every built-in US station
other than KBKF and KDEN, the premise is false.

| Station | Source | n | Whole-°F image share |
| --- | --- | ---: | ---: |
| KDEN | raw RMK T-group | 43,771 | 0.99986 |
| KSFO | IEM tmpc | 54,559 | 0.99509 |
| KAUS | IEM tmpc | 56,570 | 0.99127 |
| KSEA | IEM tmpc | 60,691 | 0.98870 |
| KORD | IEM tmpc | 59,467 | 0.98821 |
| KATL | IEM tmpc | 57,319 | 0.98402 |
| KMIA | IEM tmpc | 56,198 | 0.98386 |
| KLAX | IEM tmpc | 57,954 | 0.98264 |
| KLGA | IEM tmpc | 56,654 | 0.98085 |
| KDAL | IEM tmpc | 57,264 | 0.97395 |
| KHOU | IEM tmpc | 58,948 | 0.96689 |
| KBKF | IEM tmpc | 53,284 | 0.31749 |
| CYYZ | IEM tmpc | 57,961 | 0.20334 |

At KDEN, 117 of 120 °F integers occur with exactly one tenths value.

- **KBKF is the discrimination control.** It is a native-°C military sensor: 84 of 120 °F integers are reached by
  5 tenths values and 17 by 6, as the premise predicts. So the test is not tautological. Denver is outside the
  gate and has settled on KDEN since the 10-23 events.
- **CYYZ is native °C.** Toronto settles in °C, so the °F mechanism does not apply.

## Verdict

**KILL, premise false.** US ASOS settlement stations report whole °F, so the half-up round trip from T-group to °F
does not alias, and an integer-bucket Gaussian is not mis-massed. No forward residual remains.

## Caveats

- **IEM tmpc, not raw text.** The US shares other than KDEN come from IEM-derived tmpc. KDEN is the only US station
  whose raw T-group text was tested directly.
- **Unexplained 1-3%.** The non-image values at US stations are not explained. They were not chased because they
  are below any effect size.
