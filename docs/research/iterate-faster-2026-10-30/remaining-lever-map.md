# Remaining-lever map (2026-10-30)

Status: dated research note (lane L8), not canonical. It classifies every lever row and every §6
"Reopen if" line into exactly one class. The register, state of play, digest and established findings
stay the owners. Where this note disagrees with them, they win.

No data was read for this note. It is built only from repository documents.

## Provenance (full shas)

| Source | Ref | Sha |
| --- | --- | --- |
| Lever inventory rows 1-28, flags F1-F10; register X1-X43 | origin/master | `1a78e1ba0c8f57c0d420fca96a9528cfb1d8e9de` |
| Register X44-X70, L22; method §5 rules; SoP; ledger rows 72-80 | origin/claude/docs-owner-20261030 | `e759a55d10e31dd48559ef99b9d2959c41271fd3` |
| Register X46-X62, as named by the coordinator (byte-identical to docs-owner apart from a path-escape rendering) | docs commit | `99be9e8136aac12bb0b6f938d0d6f5a46731b438` |
| Ledger row 81 | ledger-81-morning-battery | `32ece2ceb3de7edcaf9b071807bc176a918f36ca` |
| Ledger rows 85-88 (pending on the branch; the coordinator relayed the verdicts) | successor-batch | `778950b6563f6150db1e69828c4c35f8c5a8ecbc` |
| Row 85 C1 run | successor-c1-run | `105f1696b7f0130e9f5bd472fba456034eac12e4` |
| Row 86 C2 run | successor-c2-run | `73ee618f14880fb8e50071f16f58ebcbc29aade4` |
| Row 87 marine run | marine-p0-run | `93e382ae26e8dbd7a7a5bed9dcfaf2cc16bbc121` |
| Row 88 R-Q B run | rqb-spread-p0-run | `c46408d3bbaaea3dc8bbd3c7b9ef0244b03ae04e` |

The sources are [the lever inventory](../../operations/LEVER_INVENTORY_2026-10-26.md),
[the exhaustion register](../../operations/EXHAUSTION_REGISTER.md) §6 and
[the model-improvement method](../../operations/MODEL_IMPROVEMENT_METHOD.md). Method §5, rules 2, 3, 5,
9, 10 and 12, is on docs-owner only.

**Today's results, as relayed:**

| Ledger row | Batch | Lever | Verdict |
| --- | --- | --- | --- |
| 85 | C1 | R-ODC `low_so_far` and `t_minus_low` added to the season-matched L6 HGB | DROP |
| 86 | C2 | R-PD, LOYO on months 10-12 | DROP |
| 87 | | Marine MAR-SST / MAR-ONSHORE | KILL |
| 88 | | R-Q B GEFS-SPREAD80, as a market-residual P0 | KILL |

**Classes.** Each row is in exactly one:

- **KILLED** cites the X number or ledger row that kills it.
- **BLOCKED** names its blocker: a date (a §5 rule 9 claim), parity, an owner call, a recorder, or
  a399941e, which is held until after 12-21.
- **ELIGIBLE NOW** gives its cheapest tier:
  - S1 is an outcome-free audit;
  - P0 is a market-residual read on dev;
  - LOYO is leave-one-year-out on 2021-25;
  - forward is a test on forward dates.

## 1. Lever inventory rows

| Row | Lever | Class | Basis / blocker / tier |
| --- | --- | --- | --- |
| 1a | Toronto NBM | KILLED | X64, X65 (V5.0.14 days are the only reopen path; see §6 rows) |
| 1b | Toronto ECCC citypage / GEM native | ELIGIBLE NOW | P0. Toronto's only native family, never scored against the market |
| 2 | 00-06 hours | KILLED | X31, X32; ledger rows 81 and 86 |
| 3 | HRRR 13-16 (R-K) | KILLED | X45 |
| 4 | KDEN | ELIGIBLE NOW | LOYO. Adds power, not Brier |
| 5 | Per-market centre | KILLED | X36, X8 |
| 6 | NBS | BLOCKED | Diagnostic: NBS-TXN diagnostic first |
| 7 | NBH 13-16 | KILLED | X30, X67, X69 |
| 8 | t3-r3 stack | BLOCKED | Row 80 replication (owner Q3) |
| 9 | Multi-model dispersion sharpness | CLOSED BY RULE, not by measurement (corrected 2026-10-31; [lever inventory](../../operations/LEVER_INVENTORY_2026-10-26.md) row 9) | Market-residual P0 only: X54 OM-MM-SPREAD, X55 OM-GM-SPREAD (rule `85f8192c…`, ledger row 78; 07-12 blocks are already in receipt `02c46630…`); ledger row 81 |
| 10a | Overnight low, Oct-Dec | KILLED | Ledger row 85 (C1 DROP) |
| 10b | Dewpoint / trajectory, Oct-Dec | ELIGIBLE NOW | LOYO. Kill-only. Batch it with the §6 Oct-Dec lines |
| 11 | DST / standard-time audit | ELIGIBLE NOW | S1 |
| 12 | MG-2 | BLOCKED | Date: B's look on 12-13 |
| 13 | Marine | KILLED | Ledger row 87 |
| 14 | Multi-source centre | KILLED | X6, X46-X49, X53 |
| 15 | NBM freshness audit | ELIGIBLE NOW | S1 |
| 16 | Tenths aliasing | ELIGIBLE NOW | S1, batched (rule 5) |
| 17 | MRMS echo 13-16 | ELIGIBLE NOW | P0 (the same lever as X7) |
| 18 | MOS/NBE vs the market | ELIGIBLE NOW | P0. Not among the K = 17 sweep candidates |
| 19 | MOSMIX | BLOCKED | Recorder: no dev history; forward MOSMIX recorder |
| 20 | More markets | BLOCKED | Recorder: R1/R2 pilot cities (at least 30 days) |
| 21 | GEFS member mean | KILLED | X57 |
| 22a | AIFS | BLOCKED | Capture: X50 UNTESTABLE; L22 / `_single` recorder from night 10-30/31 |
| 22b-i | AIGFS | KILLED | X52 |
| 22b-ii | GraphCast | BLOCKED | Capture: X51 UNTESTABLE (null in every record) |
| 23 | Sub-MDE batching | BLOCKED | No sub-MDE survivors to batch |
| 24 | T+1 | BLOCKED | Recorder / prereg: T+1 forward prereg freezes about 11-02 |
| 25 | Station-grid offset | KILLED | Folded into R-K; X45 |
| 26 | Mesonets / WU / venues | BLOCKED | Owner call |
| 27 | Served path | BLOCKED | Owner / master call |
| 28 | Cool-season P3d_N refit | KILLED | X40 |

**Counts (32 entries):** KILLED 13, ELIGIBLE NOW 8, BLOCKED 11.

## 2. Register §6 "Reopen if" lines

There are 75 entries: X1-X70 plus ledger rows 81, 85, 86, 87 and 88.

| Lines | Class | Basis / blocker / tier |
| --- | --- | --- |
| X5 ECMWF ENS member spread | ELIGIBLE NOW | P0, after an S1 check of dev member coverage |
| X7 MRMS | ELIGIBLE NOW | P0 |
| X13 dewpoint, Oct-Dec | ELIGIBLE NOW | LOYO |
| X18 R-G, Oct-Dec | ELIGIBLE NOW | LOYO |
| X20 R-J, Oct-Dec | ELIGIBLE NOW | LOYO |
| X36 Oct-Dec per-market shift beyond ±1 °F | ELIGIBLE NOW | LOYO |
| X1, X9 | BLOCKED | a399941e (after 12-21) / retrain waived |
| X14 | BLOCKED | Owner call (R0) |
| X15 | BLOCKED | Date: a larger window means forward dates |
| X29 | BLOCKED | No dev winner exists to carry |
| X30 | BLOCKED | Recorder: NBM text |
| X31 | BLOCKED | Date |
| X32, X34, X44, X45 | BLOCKED | Recorder / parity: HRRR capture |
| X35 | BLOCKED | Diagnostic |
| X37 | BLOCKED | Recorder: NBM V5 compression |
| X38 | BLOCKED | Date: needs new evidence |
| X50, X51 | BLOCKED | Capture defect (L2); forward values must accrue |
| X64, X65 | BLOCKED | Recorder + date: at least 60 V5.0.14 days, plus labels |
| X70 | BLOCKED | Row 80 replication |
| X2, X3, X4 (with X57), X6, X8, X10, X11, X12, X16, X17, X19, X21-X28, X33, X39-X43, X46-X49, X52-X63, X66-X69 | KILLED | Their own rows. Notes below |
| Ledger rows 81, 85, 86, 87, 88 | KILLED | Row 81 KILL on all 5 arms; 85 DROP; 86 DROP; 87 KILL; 88 KILL |

Notes on the KILLED lines:

- **X19** was IN PROGRESS and is now KILLED. Spread information is covered by X37-X39, X43, X54, X55
  and rows 81 and 88. ECMWF ENS spread, which stays open at X5, is the exception.
- **X43** has two halves. A is killed at full breadth; B is killed by row 88. The GEFS recorder
  re-opens only an Oct-Dec arm of A (§4).

**Counts (75 entries):** KILLED 50, BLOCKED 19, ELIGIBLE NOW 6.

The X46-X62 check against `99be9e81…` changed the earlier plan in one place. X51 (GraphCast) is
UNTESTABLE, not null, so it moves from KILLED to BLOCKED.

## 3. ELIGIBLE NOW, ranked by EV per cost (L3 is the next taker)

There are 9 distinct items. The inventory and §6 duplicates are merged (X7 = row 17; X13 = row 10b).

| Rank | Item | Tier | Rationale |
| --- | --- | --- | --- |
| 1 | ECMWF ENS member spread (X5) | S1 coverage check, then P0 | Sharpness is about two thirds of the 07-12 excess. ENS spread is the one spread family no kill covers (NBM, GEFS, HRRR and multi-model spreads are all dead). The S1 is cheap and outcome-free. |
| 2 | DST / standard-time audit (row 11) | S1 | Protects every Nov-Dec forward test (DST ended 11-01 in the US). Hours of work, no outcome read. A defect would bias B, L6_G and PT-1 silently. |
| 3 | MOS/NBE vs the market (row 18) | P0 | The one captured family missing from the K = 17 sweep. It reuses sweep rule `85f8192c…` mechanics, so the marginal cost is low. |
| 4 | Toronto ECCC citypage / GEM native (row 1b) | P0 | Toronto's only native guidance, never scored. The market there may under-use a Canadian source (rule 2's reason). |
| 5 | MRMS echo 13-16 (X7 / row 17) | P0 | The last sub-bar lead on the afternoon. Cost is higher because the radar join is the most work. |
| 6 | Oct-Dec LOYO batch (X13 / row 10b, X18, X20, X36) | LOYO, batched under rule 5 | Kill-only. Low prior after the C1 and C2 DROPs. One run clears four lines. |
| 7 | KDEN (row 4) | LOYO | Adds test power, not Brier. Worth it only if a later forward test is underpowered. |
| 8 | NBM freshness audit (row 15) | S1 | Hygiene. Low EV unless stale reads are found. |
| 9 | Tenths aliasing (row 16) | S1, batched | Expected effect is below the MDE80. Batch it with 8. |

**Suggested L3 sequence:** run 1 (S1) and 2 together as one outcome-free morning, then 3 and 4 as one
P0 batch under a single pre-registered rule.

## 4. Forward recorders: what each feeds and when it is first readable

Rule 9 (method §5, docs-owner): no outcome, label or price on a date is read until every test claiming
that date has taken its look.

Date claims:

| Claimant | Dates claimed | Look |
| --- | --- | --- |
| MG-1 | 10-15..11-28 | After 11-28 |
| MG-2 | MG-1's dates | One look after MG-1's |
| B | 10-29..12-12 | 12-13 |
| L6_G | 45 dates from D0 10-31 | After B |
| R-ODC P1 (row 72) | 45 dates from D0 10-31 | On or after 12-15, and after B's receipt |
| PT-1 | 12-12..01-25 | After 01-25 |

As a result:

- forward dates up to about 12-14 are first readable on or after 12-15;
- 12-12..01-25 are first readable on or after 01-26;
- coverage and parity checks that read no outcome, price or label are allowed at any time.

| Recorder | Feeds | First readable for outcomes |
| --- | --- | --- |
| ECMWF ENS | X5 forward arm | ≥ 12-15 (dates up to 12-14); ≥ 01-26 for PT-1 dates |
| ECCC GEM | Toronto native (row 1b) forward arm | ≥ 12-15 |
| NBM text | X64, X65 (≥ 60 V5.0.14 days from about 10-30); X30; X35; X37 | 60 days ≈ 12-28, but those dates sit in PT-1, so ≥ 01-26 (≈ 12-28 only if rule 9 is per (date, market)) |
| MOSMIX | Row 19 | ≥ 12-15, given enough days |
| IEM MOS | X42(a) / E3 forward | ≥ 12-15 |
| GEFS x4 | X43 A, Oct-Dec arm only (B killed by row 88) | ≥ 12-15 |
| HRRR | X32, X34, X44, X45 (parity) | Parity now (outcome-free); outcomes ≥ 12-15 |
| T+1 / T+2 prices | T+1 forward prereg (freezes about 11-02) | Per its prereg, after the claims above |
| Open-Meteo Previous Runs | Forecast-drift arm (row 81's UNTESTABLE arm) | ≥ 12-15 |
| AIFS `ecmwf_aifs025_single` (from night 10-30/31) | L22, X50 | Coverage now; outcomes ≥ 12-15 |
| R1 / R2 pilot cities (R2 from 11-01; R1 slipped) | Row 20 / L9 (at least 30 days) | R2 ≥ 12-01 by days, but outcomes ≥ 12-15 under per-date claims |
| MG-2 forward pull | B | 12-13 (B's look) |

## 5. Flags for master

1. **Rule 9 scope.** Is a claim per date, or per (date, market)?
   - Per (date, market) would free non-claimed markets earlier: R1/R2 cities from about 12-01, and
     the Toronto NBM text arm.
   - This note assumes per date.
2. **Rows 85-88 are still `pending`** on successor-batch `778950b6…`. Their verdicts here are the
   coordinator's relay. The register should gain X lines for them.
3. **X51 GraphCast and X50 AIFS are UNTESTABLE, not killed.** Row 22 is split for that reason.
4. **Row 9** was IN PROGRESS in the inventory. It is KILLED per the coordinator (X54, X55, ledger
   row 78).
5. **X64 and X65 depend on the NBM text recorder's V5.0.14 days** (§4). Whether those days are first
   readable about 12-28 or about 01-26 turns on flag 1.
