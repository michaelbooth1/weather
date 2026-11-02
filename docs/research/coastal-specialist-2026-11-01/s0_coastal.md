# L49 S0: coastal-specialist rung, data coverage and parity (inputs only)

**Status: PARKED 2026-11-01 (master), not killed.** Reasons: the dev HRRR was refetched from AWS and is not
capture-time; a winner would be Aug-Sep only, and P3d_H's 07-12 gain did not carry into Oct-Dec; the prior is
about 0.001 pooled; the KSFO grid gap is already exploited by R-R. Reopen if either (1) at least 30
forward-recorded Oct-Dec HRRR 07-12 dates with block fields are readable under rule 9, or (2) the price-history
atlas shows a coastal-specific seasonal gap. No gate was run, no module was built, no ledger row exists.

**How much of the coastal centre gap R-R already closes on dev (recorded results only): no recorded result gives
it.** R-R recorded Brier only, not centre MAE. The market MAE gap is 1.17 vs 1.48 (SF 2.03/1.18, SEA 1.74/1.09;
`docs/research/morning-loss-diagnosis-2026-10-24.md:216-224`). The nearest recorded figures, in `rungr/rr_summary.md` on
`origin/claude/rung0712-20261025` @ `6488c7a3…`, are dev P3d_H − P3d_N_fix dR:
- ALL −0.0598 [−0.0813, −0.0401] (line 38);
- PRIMARY5 −0.0837 [−0.1272, −0.0481] (line 79);
- san-francisco −0.0534 [−0.0948, −0.0151] (line 84).

No Seattle/LA/NYC/Miami gate-3 figure is recorded there. The emitted dev rows (`C:\t\l2\rungr\emit\dev_P3d_H.jsonl`)
could give a centre MAE, but only through new scoring, which was not done.

Dated research evidence, 2026-11-01, lane L49 (WS). Not canonical. Read with `rule_cs.md` beside it.

**No outcome, label, settlement, price or market row was read or joined.** Every number below is computed
from HRRR inputs (L13 corpora and the forward recorder's message/snapshot keys) or copied from a cited
document. Dev inputs are dated ≤ 2026-09-29; forward recorder rows were counted for presence only.

Scripts and outputs: `C:\t\l49\s0\` (`SHA256SUMS`): `s0_cov.py` `9e167098…`, `s0_block.py` `4b7006a3…`,
`s0_fwd.py` `b404cba4…`; outputs `s0_cov.json` `4da97877…`, `s0_block_0712.json` `92d317dd…`. Each ran
under 2 s with `python -I`.

## 1. What the cited evidence already covers (kill check)

- **The +4.29 °F KSFO grid-point gap is already exploited.** It is Open-Meteo's land point versus the
  AWS nearest (water) cell (`docs/research/model-parity-swarm-2026-10-04/a-hrrr-aws.md`). R-R
  (rule `e3d92e1a…`, register X34) adopted RN-1's nearest-land-cell rule (KSFO block index 3), and
  R-R gate 3 moved san-francisco to −0.0534 [−0.0948, −0.0151] at 07-12, where R-K's nearest-cell
  inputs had been +0.0954 at 13-16 (`rungr/rr_summary.md`). What is left is cell choice beyond RN-1.
- **Marine-layer data sources are killed or null:** NDBC/CO-OPS SST and onshore wind KILL at P0
  (ledger row 87, wrong-signed); AFD text KILL (X10/S18); R2 METAR low cloud does not explain the
  coastal residual (morning-loss); R-H onshore tag null within each coastal market at 07-12 (X27).
  The one untouched marine-structure input is **HRRR's own within-block gradient** (land-sea at
  KSFO, along-coast elsewhere), which R-R explicitly did not use ("the stored 3x3 block is used
  only through the point rule").
- **X38 (HRRR 3x3 ln-SD anomaly as a width multiplier, 00-06/07-12) is CLOSED** and X39 closed
  13-16. Its SF ρ +0.24 lead was chosen post hoc. The rung below therefore uses block statistics
  as **centre** inputs only, never in a scale model (see §4 brief-vs-code note).
- **R-R's kill clause (no further HRRR block statistic as a 07-12 centre input) is not triggered:**
  R-R passed gates 2-4. R-J's trajectory kill excludes the HRRR hourly path. R-I closes scale maps only.
- STATE_OF_PLAY (2026-11-01) and rulings-20261101: no coastal, grid-point or marine kill by name.
- **Counter-evidence on the prize:** P3d's 07-12 excess vs the market in the coastal markets is not
  outsized: Seattle +0.0152, NYC +0.0119, San Francisco +0.0062 (null), Miami +0.0039 (null); LA not
  listed (`rungh/rh_summary.md` §4). The SF centre MAE gap (2.03 vs 1.18) does not show as Brier
  excess for P3d. Centre levers are capped near 25% of the excess (FINDINGS_DIGEST, R-H).

## 2. Coverage per market (L13 HRRR, h07-12, TMP + TCDC, 3x3 block stored per message)

Rows with a qualifying cycle / layout rows (each row = station × local date × cutoff hour):

| Corpus | Years | KSFO | KSEA | KLAX | KLGA (nyc) | KMIA |
| --- | --- | --- | --- | --- | --- | --- |
| `hrrr_0712` Aug-Sep (LOYO) | 2021-25 | 1829/1830 | 1829/1830 | 1829/1830 | 1829/1830 | 1829/1830 |
| `hrrr_0712` dev | 2026-07-30..09-29 | 372/372 | 372/372 | 372/372 | 372/372 | 372/372 |
| `hrrr_cool0712` Oct-Dec | 2024-25 only | 1101/1104 | 1101/1104 | 1101/1104 | 1097/1104 | 1097/1104 |
| forward recorder h07-16 | 2026-10-26..11-01 | 69 | 69 | 69 | 66 | 66 |

The single 2022 miss is one date shared by all stations. Every manifest message used by a coastal
row has a complete 9-cell block (0 missing rows). Oct-Dec 07-12 exists for 2024-25 only (2 folds).
Forward: all 1,452 recorded messages carry a 9-cell `block3x3` for all five stations; snapshot rows
carry the cycle, fhs and RN-1 values but no block field, so block columns are derived from
`messages.jsonl` by the snapshot's own cycle and fhs.

## 3. Which grid cells exist and how much they differ (window max over [h:00, 17:00], °F)

Land mask `land_3x3.json` `22069bee…`: only KSFO has water cells (indices 2, 4, 5, 7, 8; RN-1 = 3).
KSEA, KLAX, KLGA, KMIA are all-land blocks, RN-1 = 4 (centre). Mean cell − RN-1 cell, 2021-25 Aug-Sep
(row-major south→north, west→east; index 4 is the centre):

| Station | Block range mean / p90 | Mean cell − chosen, idx 0..8 | Day-to-day SD of offsets |
| --- | --- | --- | --- |
| KSFO | 15.7 / 22.7 | +0.8 +1.2 −11.6 · 0 −10.9 −13.2 · −1.8 −11.9 −13.6 | land 1.9-2.6; water 3.6-4.9 |
| KLAX | 6.2 / 9.9 | −3.7 −1.0 +1.6 · −2.9 0 +2.3 · −2.7 +0.3 +2.4 | 0.5-1.8 |
| KSEA | 2.9 / 4.8 | −0.3 +0.7 +1.5 · −1.1 0 +0.6 · −1.2 −0.2 +1.0 | 0.3-1.3 |
| KMIA | 2.2 / 3.7 | +0.2 −0.2 −0.7 · +0.3 0 −0.4 · +0.5 +0.1 −0.3 | 0.7-1.0 |
| KLGA | 1.4 / 2.5 | −0.1 −0.2 −0.4 · +0.1 0 −0.4 · 0.0 −0.1 −0.5 | 0.4-0.8 |

2026 dev is similar except KSFO's land-sea contrast is weaker: chosen − mean(water) 12.2 ± 4.3 °F
(2021-25) vs 10.0 ± 4.3 (2026); LA's west-east gradient 6.0 vs 5.5. HRRR v4 throughout.

Reading (no outcome): cell choice can only matter at KSFO, KLAX and perhaps KSEA. At KLGA and KMIA the
block is near-uniform. A constant offset is absorbed by P3d's (market, season) bias (LEVER_INVENTORY
row 25), so any gain must come from the day-varying part (SD 0.5-1.8 °F at LA/SEA, 2-5 °F at SF).

## 4. Train/serve parity plan

- **Training:** `hrrr_0712` Aug-Sep 2021-25 rows, L13 selection (availability = max LastModified + 10 min
  ≤ h:00), the same selections R-R used. Block columns from each message's `block3x3`.
- **Dev:** the same corpus, 2026-07-30..09-29. Disclosure: retroactive AWS fetch with point-in-time
  selection, not capture-time; dev 08-15..09-29 has been read by every rung since R-A.
- **Forward/serve:** the L13 forward recorder (running since 2026-10-26, h07-16; not touched by this lane).
  Block columns derived offline from `messages.jsonl` by the snapshot's `cycle_utc` and `fhs`. Parity
  tests before any forward use: (i) recompute `k_max_f` from `block3x3[rn1_index]` and match the
  snapshot to 1e-9 °F on every coastal row (proves the derivation path); (ii) value parity of all 9 cells
  against an independent AWS byte-range read on ≥ 200 messages covering all five stations, |Δ| ≤ 1e-6 K;
  (iii) selection parity as the R-R addendum. Land mask and `stations_json_sha256` `52e8bb5f…` pinned.
  No recorder change is needed.
- **Brief-vs-code note:** in `pooled_residual_model.py` (B-bound; branch `claude/rung0712-20261025`
  @ `6488c7a3…`) `extra_hgb` columns feed **both** the mean HGB and the HGB scale model (line 588,
  `scale.fit(np.column_stack([X, floor_gap]), …)`). Block statistics entering the scale model would be
  a width use of the 3x3 block (X38's family). The rule therefore needs a separate research module that
  imports the model read-only and keeps the new columns out of the scale inputs. That module does not
  exist yet.

## 5. Power and size, stated before any scored read

LOYO: about 305 dates × 5 markets × 6 hours ≈ 9,100 rows. Dev: 43 dates × 5 markets; at 5 clusters it is
underpowered (dev MDE80 at 07-12 is about 0.005 pooled over 11). If the rung recovered a quarter of the
coastal markets' P3d excess (about 0.009 each) it would be about 0.002 on those markets and about 0.001
pooled over 11: a batch member, not a solo test.
