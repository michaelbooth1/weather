# Morning P0 battery: result (ledger row 81, lane L8, 2026-10-30)

**Verdict: KILL on all 5 arms.** None was redundant, and none was UNTESTABLE. The P0 ran once, under rule
`rule_morning_battery.md` (sha256 `2479f3bed09bbd038cf3bb39b6fade3c2327353412a8bf76f2f06896fd770a5f`, prereg
commit `073b635239e8f13f0a10e4df03f060e870b79be5`).

This is development evidence (dev window 08-15..09-29, provisional). No date after 2026-09-29 was read.

## Run identity

- **Run env:** `C:/wt/l3loyoenv` at `8bb0f9563582885c4d01d34b67476f2563260e43`, clean.
- **Module shas:**
  - mr_sweep `eab89868…4f2f`
  - mr_gate `5bdc3fa8…1852`
  - market_blend `b2a2f597…b5c3`
- **Driver:** `C:/t/l8mb/mb.py`, sha256 `d6d2a50309f53013611320794cf2394bcc93cb90c3cc9a267ed6469281c8d09a`. It imports
  row 79's `C:/t/l8ftr/ftr.py` (`ab8ced55…aeaf`, sha checked) for the METAR parse.
- **Layout manifest:** `4d53fdbd…5f22`.
- **Replay SHA256SUMS:** `d9c2ed46…8b82`.
- **Receipts:**

  | file | sha256 |
  | --- | --- |
  | `s1.json` | `fe37167f1ad9898a63fb780c0775d087b2d1e4bdde694d5a4a177d84cabdf10e` |
  | `features.parquet` | `51f0646d7740183954363988cd2b953ad27afb45b684292514f4f9325943b295` |
  | `p0_receipt.json` | `95e16baebf0baaad574a7d67b1740f87cf759ee4df290817d5d81d0973429bc4` |
  | `p0_rows.jsonl` (215 per-date rows: 5 arms × 43 dates) | `6edb36646ae1d8087fc97c507c07c85ee50d47233e5b7099e18479b6e2455edb` |

  All are in `C:/t/l8mb/out`.
- **Execution:** every stage was light and ran directly, serially.
  - Extract: 8-10 s per market, about 22 GB read in total, 0 malformed lines.
  - S1: 8 s.
  - P0: 19 s.

## S1 (inputs only)

- **Snapshots:** 60,203 at 00-12 across fit and burn-in; 6 had no replay record.
- **Receipt audit:** no source had its receipt after the capture time.
  - Not ok: Open-Meteo multimodel 81, global_ensemble 29.
  - METAR: 388 stale, 48 with no source.
  - RATE-0712 drops: 1,514 snapshots before sunrise, 40 with no observation in the pre-sunrise window, 77 with
    Δh < 0.5 h.
- **Coverage:** every arm covered all 43 scored dates.

  | arm | scored covered snapshots |
  | --- | --- |
  | DIS-HN-0006 | 23,906 |
  | DIS-HN-0712 | 21,663 |
  | DIS-NG-0006 | 23,906 |
  | DIS-NG-0712 | 21,663 |
  | RATE-0712 | 19,967 |

- **Redundancy screen** (Spearman ρ on covered fit snapshots in the arm's block; REDUNDANT if |ρ| >= 0.80):

  | arm | vs OM-MM-SPREAD | vs OM-GM-SPREAD | vs MET-COOLING |
  | --- | --- | --- | --- |
  | DIS-HN-0006 | 0.713 | 0.059 | |
  | DIS-HN-0712 | 0.698 | 0.051 | |
  | DIS-NG-0006 | 0.199 | 0.046 | |
  | DIS-NG-0712 | 0.166 | 0.075 | |
  | RATE-0712 | | | 0.559 |

  - No arm reached the threshold, so K = 5.
  - DIS-HN is strongly but not fully collinear with OM-MM-SPREAD, as rule §4 expected.

## P0 (L3 §5, BH q = 0.10 over K = 5)

| arm | population (snapshots / dates) | ρ_c | Δ [95%] | one-sided p | BH q | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| DIS-HN-0006 | 23,342 / 43 | +0.0007 | −0.0004 [−0.0208, +0.0224] | 0.508 | 0.882 | KILL |
| DIS-HN-0712 | 21,183 / 43 | −0.0102 | −0.0098 [−0.0279, +0.0061] | 0.894 | 0.894 | KILL |
| DIS-NG-0006 | 23,342 / 43 | −0.0057 | −0.0097 [−0.0422, +0.0123] | 0.822 | 0.894 | KILL |
| DIS-NG-0712 | 21,183 / 43 | +0.0034 | +0.0016 [−0.0178, +0.0226] | 0.412 | 0.882 | KILL |
| RATE-0712 | 14,820 / 43 | −0.0001 | −0.0015 [−0.0456, +0.0444] | 0.529 | 0.882 | KILL |

- **Placebo diagnostic:** for every arm, the c-deranged placebo diagnostic covers 0.
- **No survivor**, so neither the w gate nor the 00-06 `BLOCKS` addition was exercised.
- **Per market:** single markets with a positive lower bound are listed for completeness only. They are not
  claims: these are 3 of about 55 market cells with no correction.
  - DIS-NG at both blocks: san-francisco.
  - RATE-0712: chicago.

## Reading

- **These are clean nulls, not near misses.**
  - Every point estimate is within ±0.01 of zero.
  - Four of five are at or below zero.
  - The intervals are tight for the DIS arms.
- **Conclusion:** at the morning hours, the market's error is not predicted by model disagreement (HRRR vs NBM,
  NBM vs GEFS control) or by the rise rate since sunrise, beyond the calibration-matched placebo.
- **Untested:** Previous Runs drift was UNTESTABLE at registration (rule §3). Cloud cover and dewpoint depression
  were dropped (rule §3).
