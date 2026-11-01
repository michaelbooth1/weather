# Forecast-tracking residual: S1 and P0 result (ledger row 79, lane L8, 2026-10-30)

**Verdict: KILL at P0, all five arms.** No arm survives BH at q = 0.10, and no Δ lower bound is above 0.
The w gate, the w = 0 identity check and the tradability replay were not run (they apply to survivors only).
Development evidence (dev window, provisional).

**Rule:** `rule_forecast_tracking.md`, sha256 `6c4c28aa16fe1f1365a685267c4452e10724995c782b706401c07a85e8a5270d`.
It was committed and pushed at `00ca053edb409c2605e99813c8811d1f1873ab9b` before any dev feature, outcome or
price was read.

**P0 machinery:** L3 `rule_mr_sweep.md` §5 (`85f8192c…1956`), run through `mr_sweep.p0_candidate` and
`bh_adjust` verbatim.

## Run

- **Run env:** `C:/wt/l3loyoenv` @ `8bb0f9563582885c4d01d34b67476f2563260e43`, clean (checked by the script).
- **Driver:** `C:/t/l8ftr/ftr.py`, sha256 `ab8ced550699d74d734fcd73cfde152e46922ab0983d5228e92086425abaaeaf`, outside the
  repo, imports only.
- **Stages, each light and run once in order:**

  | stage | time | memory |
  | --- | --- | --- |
  | t3 | 0.5 s | |
  | extract (×11 markets) | 3-6 s each | |
  | s1 | 6.7 s | |
  | p0 | 17.4 s | < 1 GB |

- **Replay read:** the extract stage seeks and bisects each market-day replay file by `captured_at_utc`, then
  decodes only the 13-16 local records. That is 10.2 GB in total, against 54 GB for a full scan.

### Inputs

| input | sha256 |
| --- | --- |
| layout manifest | `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22` |
| replay SHA256SUMS | `d9c2ed46a72442c68deb6f6b36784fcf081edc52e2a0d8f024cd6cc1a5a38b82` |
| NBH manifest | `5d2c82ad1df560d97d2271055bded53e9311ab08a0b914af50a2d0b46b18752a` |
| t3-r3 table | `9abe688250a2289c72cda54c75924652656a80bed58e51f9862d1db243040e4e` |

The t3-r3 table has 88 cells (11 stations × months 8-9 × hours 13-16). Its history is Aug-Sep 2024-25, and its
last date is 2025-09-30.

### Outputs (`C:/t/l8ftr/out/`)

| file | sha256 | contents |
| --- | --- | --- |
| `s1.json` | `c778a2c978c517c2d3d0a919ebba1af2c60d5552d2ac4633946946faf900320b` | S1 coverage and audit |
| `features.parquet` | `96b84ea727138fce617064581a6e4fcb1af4b809107ac35cbaed6a2853978054` | every arm's value and receipts per snapshot |
| `p0_receipt.json` | `084a980880b5b79f9305de4f020a4826e8e132e1d34143edbeea4277cbd63950` | P0 receipt |
| `p0_rows.jsonl` | `1a95f25ee6f861600ac8ddff7b85a1eb240bf0bac5efb4a8c0af427507e2139f` | per-date rows, 5 arms × 43 dates |

## S1 (inputs only; run before P0)

- **Population:** 18,599 layout snapshots at local hours 13-16 on 08-01..09-29, of which 13,984 are scored
  (08-15..09-29).
- **Records:** 18,597 have a replay record. Two NYC snapshots have none: 1 malformed (truncated) replay line,
  listed in the extract meta.
- **Receipt audit:** 0 METAR receipts after capture, 0 HRRR receipts after capture and 0 observations after their
  receipt.
- **NBH receipts:** every cycle used satisfies issued <= LastModified <= t_c. No cycle was issued after its
  LastModified.
- **Snapshots not covered, by reason:**

  | reason | snapshots |
  | --- | --- |
  | no METAR source | 22 |
  | METAR older than 75 min | 148 |
  | no METAR row today | 1 |
  | Open-Meteo not ok | 4 |
  | NBH not bracketing t_obs | 9,058 |

- **NBH bracketing loss** (disclosed, as registered): the newest NBH cycle received by t_c starts at
  issue + 1 h. So whenever the cycle has landed (about 42 min after issue) but t_c is before the next :51
  observation, t_obs falls before the first valid hour. The rule leaves those snapshots uncovered rather than
  falling back to an older cycle, so the NBH arms keep about half their snapshots.
- **Covered scored snapshots / dates:**

  | arm | covered |
  | --- | --- |
  | TRK-HRRR | 13,893 / 43 |
  | PROJ-HRRR | 13,893 / 43 |
  | TRK-NBH | 7,043 / 43 |
  | PROJ-NBH | 7,043 / 43 |
  | RISE-T3R3 | 13,897 / 43 |

  All five are testable, so the S1 kill does not apply.
- **Sanity check (inputs only):**
  - τ_H median −0.04 °F (5-95%: −5.5 to +4.3);
  - τ_N median +0.15 °F;
  - PROJ-HRRR − RM median 0.23 °F;
  - RISE − RM median 1.0 °F.

## P0 (rule 85f8192c §5; K = 5, BH q = 0.10)

Scored dates 2026-08-15..09-29 (43); burn-in 08-01..08-14; 11 US markets; m = layout `p_market_yes`.
Population = covered snapshots whose 20 donors are also covered.

| arm | type | population snaps / dates | ρ_c [95%] | mean ρ_pl | Δ [95%] | p (1-sided) | BH q | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TRK-HRRR | D+ | 12,216 / 43 | +0.0095 [−0.0197, +0.0395] | −0.0085 | +0.0181 [−0.0201, +0.0555] | 0.173 | 0.216 | KILL |
| TRK-NBH | D+ | 4,290 / 43 | +0.0206 [−0.0450, +0.1049] | −0.0100 | +0.0305 [−0.0481, +0.1252] | 0.221 | 0.221 | KILL |
| PROJ-HRRR | C | 12,216 / 43 | +0.0301 [−0.0075, +0.0796] | −0.0019 | +0.0320 [−0.0120, +0.0861] | 0.078 | 0.155 | KILL |
| PROJ-NBH | C | 4,290 / 43 | +0.0589 [−0.0141, +0.1400] | −0.0022 | +0.0611 [−0.0290, +0.1586] | 0.093 | 0.155 | KILL |
| RISE-T3R3 | C | 12,274 / 43 | +0.0360 [−0.0041, +0.0814] | −0.0087 | +0.0447 [−0.0040, +0.0965] | 0.035 | 0.155 | KILL |

**Diagnostics:**

- **c-deranged placebo:** ρ is about −0.04 to −0.05 for every arm, with an interval that excludes 0. This is
  the parent's diagnostic, which the rule only reports. It does not enter the decision.
- **Per-market Δ:** in `p0_receipt.json`. No arm has a consistent sign across markets.
- **Pattern:** all five point estimates are positive, and the C-type arms are nearest to the bar. RISE-T3R3,
  which is MET-MAX shifted per station/month/hour, has the smallest raw p. None clears BH or a positive lower
  bound.
- **Interpretation (dev evidence only):** at 13-16, neither the tracking error against HRRR or NBM hourly nor
  the remaining-rise climatology predicts the Gamma YES price's error beyond the calibration-matched placebo
  on this window.

## Disclosures

- This is a dev-window read; nothing after 2026-09-29 was read.
- The per-date rows were written before this note.
- L8 has not opened the MR sweep's results (row 78).
