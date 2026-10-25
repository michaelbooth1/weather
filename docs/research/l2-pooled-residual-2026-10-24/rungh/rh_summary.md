# R-H market-relative loss atlas (lane L2), 2026-10-25

**SELECTION EVIDENCE.** This is a descriptive dev-window atlas covering layout dates 2026-08-01..09-29, 57 dates
and 626 market-days. The reference is the captured capture-time market (`p_market_yes`, never `last_in_hour`).
It was not pre-registered and makes no edge claim. Nothing dated after 2026-09-29 was read.

## What was measured

- Two arms are scored on the snapshots both of them cover: 28,754 snapshots at 07-12 and 18,574 at 13-16.
- **L6** is the frozen MG-2 pre-13 arm. Its part sha is `07a67425…` and its nowcast sha is `3806687c…`. Outside
  07-12, L6 is MG-1. L6 is also in-sample on this window, which favours it.
- **P3d_N_fix** is the pooled residual arm. The 07-12 vectors come from R-A. The 13-16 vectors are newly emitted
  with the same code, using `dev-emit-rung --hours 13,14,15,16`.
- Excess is the arm's Brier minus the market's Brier, averaged over market-days. Intervals are date-clustered 95%
  intervals (2000 draws).
- The MG-1 positive control reproduces 0.0120.
- Regime tags come only from captured METAR rows and captured forecasts at or before each snapshot's capture
  time. The code is in `pooled_residual_model.rh_tags` and `rh_obs_tags`.
- `nbm_error_ex_post` is the day's final captured METAR maximum minus NBM. It is therefore close to the outcome
  and is descriptive only. It does not support any lever below on its own.

The full tables, including every cell with its count and n < 15 flag, are in `rh_tables.txt`.

## Headline

| Window | Arm | Excess vs market | Note |
| --- | --- | --- | --- |
| 07-12 | L6 | +0.0081 [+0.0062, +0.0101] | Excess is flat by hour: h07 +0.0086 … h12 +0.0087. |
| 07-12 | P3d_N_fix | +0.0101 [+0.0080, +0.0123] | Excess is flat by hour: h07 +0.0099 … h12 +0.0104. |
| 13-16 | L6 (= MG-1) | +0.0233 [+0.0205, +0.0264] | Excess grows by hour: h13 +0.0170, h16 +0.0294. |
| 13-16 | P3d_N_fix | +0.0083 [+0.0068, +0.0098] | Excess shrinks by hour: h13 +0.0107, h16 +0.0029. |

## Where the market wins

1. **At 07-12, the whole loss is mass on the winning bucket.** Position 0 accounts for +0.0093 of L6's +0.0081
   and +0.0122 of P3d's +0.0101.

   | Bucket mass | Market | L6 | P3d |
   | --- | --- | --- | --- |
   | On the winner | 0.415 | 0.325 | 0.292 |
   | One bucket either side | 0.22 | about 0.22 | about 0.22 |
   | Two or more buckets away | 0.16 | 0.25 | 0.28 |

   Mass one bucket either side is equal, so the extra mass we put two or more buckets away is mass the market
   puts on the winner. The market is sharper, and its sharpness is warranted.
2. **At 07-12, no regime localises the loss.** P3d's excess barely moves across any tag:

   | Tag | P3d excess at 07-12 |
   | --- | --- |
   | Front / no front | +0.0087 / +0.0100 |
   | Overcast / broken / clear | +0.0087 / +0.0099 / +0.0113 |
   | Onshore / not onshore | +0.0083 / +0.0094 |
   | HRRR−NBM cold / near / warm | +0.0105 / +0.0091 / +0.0074 |
   | NWS−NBM cold / near / warm | +0.0082 / +0.0106 / +0.0079 |
   | Obs path vs NBM cold / near / warm | +0.0103 / +0.0096 / +0.0111 |

   Every interval overlaps the window mean, and L6 shows the same pattern. The gap is already full size at h07,
   before any daytime observation exists.
3. **At 07-12, we lose most on days when NBM was right (descriptive).**

   | Ex-post NBM error | P3d excess | L6 excess |
   | --- | --- | --- |
   | Near (final within 2 °F of NBM; 373 market-days) | +0.0113 | +0.0084 |
   | Cold (final ≥ 2 °F below NBM) | +0.0118 | +0.0091 |
   | Warm (final ≥ 2 °F above NBM; 69 market-days) | −0.0014 [−0.0071, +0.0048] | +0.0045, null |

   Losing most where NBM's centre was right points to a spread that is too wide, not to missing centre
   information.
4. **At 07-12, a few markets lose more than others.** For P3d:
   - Clearly positive: Dallas +0.0173, Austin +0.0159 and Seattle +0.0152 [+0.0088, +0.0210]. NYC is +0.0119.
   - Null: Miami +0.0039, San Francisco +0.0062, Denver +0.0064 and Chicago +0.0069.
   - L6 ranks the markets the same way, but its spread is smaller: Dallas +0.0119, Austin +0.0113, Miami +0.0031.
5. **At 13-16, P3d_N_fix loses where the observed path runs below NBM's diurnal path.**

   | Obs path vs NBM | P3d excess at 13-16 | Share of window excess |
   | --- | --- | --- |
   | Cold | +0.0183 [+0.0139, +0.0225] | 47% |
   | Near | +0.0082 | |
   | Warm | +0.0045 [+0.0026, +0.0066] | |

   The cold-path interval does not overlap the warm-path interval. Two things set the remaining afternoon gap:
   - **Timing.** The gap is concentrated at h13-14: h13 +0.0107, h14 +0.0105, h16 +0.0029.
   - **Placement.** We put too much mass one bucket below the winner: 0.162 against the market's 0.141. That
     cell contributes +0.0015.

   The market judges better whether a lagging afternoon will still reach its high.
6. **At 13-16, MG-1 (L6) fails on days when NBM is too warm.**
   - On ex-post cold days its excess is +0.0545 [+0.0492, +0.0601], 69% of its window excess.
   - When HRRR is cold against NBM, its excess is +0.0355 against +0.0113 when HRRR is warm.
   - It puts 0.20 mass two or more buckets above the winner (market 0.03), and only 0.440 on the winner (market
     0.666).
   - P3d_N_fix removes most of this: +0.0083 against +0.0233.

   The composite's actual post-13 arm was not scored here.
7. **Regime-specific effects are weak or come only from L6.**
   - Overcast at 13-16 is +0.0336 for L6 against +0.0203 for clear, but P3d's +0.0111 and +0.0087 overlap.
   - Onshore cells within each coastal market overlap their market's own not-onshore cell at 07-12.
   - Front cells are never larger than no-front cells.

## Ranked hypotheses for the next lever

Each hypothesis is tied to the cells that support it.

1. **Our 07-12 predictive spread is too wide, and the gap is spread calibration rather than missing information.**
   - **Supporting cells:** findings 1 and 2, and finding 3 (descriptive).
   - **Lever:** a walk-forward spread recalibration of P3d_N_fix (and L6) per hour at 07-12, using
     dates-before-only fits. It needs no new data.
   - **Discriminating test:** a sharpen-only arm, pre-registered. If position-0 mass rises toward 0.41 and the
     excess falls in the near-NBM cells, the gap was spread. Whatever residual remains is centre information,
     which is hypothesis 2.
2. **The market holds a better pre-dawn central estimate than NBM's captured mean. The candidates are an
   NBS-style independent max with its own spread (TXN/TXNSD), or a fresher NBM or multi-model run.**
   - **Supporting cells:** finding 2 (the gap is full size at h07 and flat to h12, so it does not come from
     intraday observations) and the size of the position-0 deficit.
   - **Against captured HRRR:** the captured open-meteo HRRR high does not localise the loss. HRRR−NBM cold,
     near and warm are +0.0105, +0.0091 and +0.0074 for P3d. A market that simply followed HRRR would show a
     larger gap where HRRR disagrees with NBM.
   - **Ranking:** NBS TXN ranks above HRRR freshness. HRRR freshness at 07-12 is the weakest candidate in this
     family, because only the captured HRRR value was testable here, not a fresher run.
   - **Order:** test this after hypothesis 1 has removed the spread component.
3. **At 13-16, the market is better at afternoon remaining-rise and peak timing when the day lags NBM.**
   - **Supporting cells:** finding 5.
   - **Lever:** R-G's trajectory columns (path gap, trend3), fitted at h13-14. R-G was 07-12 only. There, B_G
     passed but P3d_G failed gate 3b, so the afternoon is untested. An hourly HRRR temperature trajectory is the
     source-side alternative.
   - **Why it is third:** the gap is smaller (+0.0083 in total), but it is the most localised cell in the atlas.
4. **Station or market-specific bias.**
   - **Supporting cells:** finding 4 (Dallas, Austin and Seattle are clearly positive; Miami, San Francisco,
     Denver and Chicago are null).
   - **Lever:** per-market bias and spread terms. Check first whether hypothesis 1 removes the gap, because
     wider-spread markets would show exactly this.
5. **Deprioritised: regime-specific bias.**
   - Front, cloud cover and marine-onshore show no cell for P3d_N_fix whose interval separates from the window
     mean (finding 7). The NWS grid against NBM cells do not separate either.
   - The one regime signal is MG-1's NBM-too-warm failure at 13-16 (finding 6). P3d_N_fix already handles it.

## Files

| File | sha256 |
| --- | --- |
| atlas `C:\t\l2\rungh\atlas\rh_atlas.json` | `ff7ee23179be2beceb9c7b883ffb3ae37fb9966e1aee7f8ee6df0744ab9fb814` |
| tags `C:\t\l2\rungh\rh_tags.parquet` | `d94ca158b935bdc71994c272775d344a33b094fef8ea2765e040814f984b91e5` |
| tags audit `rh_tags.audit.json` | `72f4424d63181ab3af6821fd3279578f555b9329b4d05a488a84399ba7affe68` |
| P3d 07-16 combined `atlas\dev_P3d_N_fix_07_16.jsonl` | `f5901246ca9bb9423dbc83b659c8c840373ccfc845b14ee86617ca06ccd77e09` |
| P3d 13-16 `emit1316\dev_P3d_N_fix.jsonl` | `abc4350724fe42a5d2423dcf5dd3f1c1b06dcea4799cb0d297bd6de465096109` |
| P3d 07-12 (R-A) `rung0712\emit\dev_P3d_N_fix.jsonl` | `cd0034b9faec0b687e1184187feeaa39ab151c5f9f8d1c905d3a49a0e7089542` |

The tagger tagged 47,412 snapshots and skipped 2 because their replay lines were corrupt. The IEM parquet
`37d97195…` was used only for the 2021-25 diurnal fractions.
