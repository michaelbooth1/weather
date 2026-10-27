# R-J result (lane L2), 2026-10-25: KILL at gate 3

The rule is `rule_rj.md`, sha `e948c0a288f6e4a1cf4f3f143b8246cb11bc48e21cc67238187c180f58dfe171`. It was
committed at a76fef441, before any R-J row existed. This is development evidence only and makes no edge claim.
Nothing dated after 2026-09-29 was read. R-J was selected on the dev window (from R-H's cold-path afternoon cell).

## Reading

- **Gate 1 (parity): PASS.**
- **Gate 2 (LOYO, B_G beats B_N at 13-14): PASS.**
- **Gate 3 (dev, P3d_G beats P3d_N_fix at 13-14): FAIL.**
- **The pre-registered kill applies.** The trajectory family is closed for the afternoon too. No other
  trajectory, path-gap, trend or floor-feature variant is run on B_N, P3d_N_fix or any NBM-anchored arm at any
  hour under any rung name.
- The kill does not cover the separately pre-registered HRRR hourly-path variant.
- Gate 4 (against the composite's post-13 arm) was not run.

## Gate 1: parity on the h13-14 rows (the rows differ from R-G's h07-12)

| Fraction | h13-14 | Threshold | h13 | h14 | h15 | h16 |
| --- | --- | --- | --- | --- | --- | --- |
| overnight_min exact | 0.9964 | 0.95 | 0.9956 | 0.9971 | 0.9974 | 0.9972 |
| trend3 within 1 °F/h | 0.9307 | 0.90 | 0.9277 | 0.9335 | 0.9425 | 0.9071 |
| IEM training coverage | 0.9986 (6,554 rows) | 0.95 | | | | |

## Gate 2: LOYO 2021-25 (Brier, date-clustered)

| Contrast | 13-14 | 15-16 (secondary) |
| --- | --- | --- |
| **B_G − B_N** | **−0.0335 [−0.0377, −0.0295]** | −0.0146 [−0.0177, −0.0114] |
| P3d_G − P3d_N_fix | −0.0037 [−0.0063, −0.0012] | +0.0002 [−0.0031, +0.0035] |
| P3d_N_fix − B_N | −0.0632 [−0.0694, −0.0573] | −0.0563 [−0.0643, −0.0481] |

## Gate 3: dev (43 scored dates, 473 market-days, 7,000 common covered snapshots at 13-14)

Statistic: dR, date-clustered, with the crossed interval after "cx".

| Contrast | Group | dR | 95% (date-clustered) | 95% (crossed) |
| --- | --- | --- | --- | --- |
| **P3d_G − P3d_N_fix** | **13-14** | **−0.0025** | **[−0.0207, +0.0158]** | [−0.0298, +0.0260] |
| | h13 | +0.0076 | [−0.0128, +0.0276] | |
| | h14 | −0.0159 | [−0.0400, +0.0081] | |
| | 15-16 (reported) | −0.0246 | [−0.0524, +0.0047] | |
| | h15 (reported) | −0.0451 | [−0.0717, −0.0173] | [−0.0988, +0.0037] |
| | h16 (reported) | +0.0120 | [−0.0442, +0.0695] | |
| B_G − B_N (reported) | 13-14 | −0.0946 | [−0.1296, −0.0639] | |
| B_G − B_N (reported) | 15-16 | −0.1222 | [−0.1632, −0.0871] | |

- **Controls:**
  - B_N and P3d_N_fix 13-16 were byte-identical to R-H's emission.
  - The MG-1 07-12 positive control gave 0.01196.
- **The h15 cell is not readable as a result.**
  - It is reported, not a gate. Its crossed interval includes 0, it is one of many cells, and it sits in the
    secondary window.
  - Under the rule it cannot rescue the rung or seed a new one (the kill covers it).
- **The same pattern as R-G.**
  - The trajectory columns help the simple OLS arm a great deal, both in LOYO and on dev.
  - The HGB residual arm (P3d_N_fix) already captures that information: LOYO gives −0.004, and dev is null.
  - This matches R-G's gate 3b failure at 07-12.

## Reported: the incumbent at 13-14

The composite's post-13 arm is MG-2's P3d_N dev emission (`721ae2cd…`), with MG-1 fallback. On this scope the
fallback was used on 0 snapshots and P3d_N on 13,972.

| Contrast | dR | 95% (date-clustered) | 95% (crossed) |
| --- | --- | --- | --- |
| P3d_N_fix − composite post-13, 13-14 | +0.0107 | [+0.0016, +0.0210] | [−0.0085, +0.0365] |

So P3d_N_fix is, if anything, worse than the bound P3d_N in the afternoon. Any afternoon challenger built on
P3d_N_fix starts behind the incumbent.

## Files

| File | sha256 |
| --- | --- |
| `C:\t\l2\rungj\emit\rg_emit_audit.json` | `a67a1d5a1bb9c8e94ab5e71fce0e234c4d9a3146ab3c893e9cf7d06e5bcbd192` |
| `C:\t\l2\rungj\emit\loyo_rows.jsonl` | `0d5afcb3c26a0c83a719f764b9d4fd69a570d79a86bae95e3df0c1bb5ece6fab` |
| `dev_B_G.jsonl` / `dev_P3d_G.jsonl` (13-16) | `cd4afea2…` / `0b0919a6…` |
| `C:\t\l2\rungj\score\rj_score.json` | `e46dbf5dcebbc18e911762c231f067cb073d55586a1856d92f389b41d876b149` |
