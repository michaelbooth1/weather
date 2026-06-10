# Gap Decomposition: Where the Model-vs-Market Brier Gap Lives

Generated: 2026-06-10 (v0.5.7 replayed over the pinned <=June-9 corpus,
finalized ledger settlements; 58,344 band rows, 51 scored market days).

## Finding zero: a replay-harness bug was 72% of the apparent gap

The decomposition's first product was not a model insight. The first pass
showed a 36.7%-of-gap cell in US evenings -- 467 rows where the winning band
got 0.007 from the "model" while the market priced 0.986, every one a band
whose UPPER value equaled settlement. Root cause: `replay.band_bin_data`
rebuilt bin_data from the tape without `value_hi`, so every replayed F range
band ("90-91") was scored as its lower bucket alone; a model correctly
locked on 91 was credited ~0. Production was never affected (market_bins
carries value_hi); outcomes were never affected (backtest parses the label);
all session A/B gates compared bug-symmetric runs, so every promotion stands.
Fixed (value_hi parsed from the range label, regression test added).

Corrected headline:

| | Brier (58,344 rows) |
| :--- | ---: |
| Market | 0.0325 |
| Replayed model (v0.5.7, true) | **0.0386** |
| Replayed model (with bug) | 0.0544 |
| Recorded production (June capture code) | 0.0434 |

True gap: **+0.0061/row (~19% relative)**, not +0.0218. The week's shipped
changes are a genuine -0.0048 vs the recorded production code; the bug had
been disguising that as a "+0.011 code effect" in every report.

## 1. Family: US markets carry 88% of the (true) gap

| Family | Rows | Model | Market | Gap share |
| :--- | ---: | ---: | ---: | ---: |
| us_f | 49,544 | ~0.0379 | 0.0315 | 88.5% |
| toronto | 8,800 | 0.0428 | 0.0382 | 11.6% |

## 2. By time of day: mornings dominate; evenings are SOLVED

| Family x hours | Rows | Model | Market | Gap share |
| :--- | ---: | ---: | ---: | ---: |
| us_f night-9h | 17,952 | 0.0545 | 0.0474 | **35.8%** |
| us_f 16-18h | 6,072 | 0.0331 | 0.0222 | 18.8% |
| us_f 13-15h | 6,523 | 0.0514 | 0.0416 | 18.0% |
| toronto night-9h | 3,520 | 0.0695 | 0.0557 | 13.7% |
| us_f 10-12h | 5,808 | 0.0593 | 0.0519 | 12.0% |
| us_f 19-24h | 13,189 | 0.0014 | 0.0003 | 3.8% |
| toronto 16-24h | 2,992 | ~0.005 | ~0.005 | 0.3% |
| toronto 10-15h | 2,288 | 0.0516 | 0.0553 | **-2.4%** |

Evenings -- the cell the bug had painted as the disaster -- are essentially
at parity in both families. Toronto mid-day now BEATS the market. Half the
remaining gap is overnight/morning (forecast-only information), where the
per-row deficit is modest (0.054 vs 0.047) but the row mass is huge.

## 3. Moneyness: the model wins the tails, loses the exact call

| Band distance from settlement | Rows | Model | Market | Gap share |
| :--- | ---: | ---: | ---: | ---: |
| at-settle | 3,346 | 0.3178 | 0.2551 | 59.3% |
| 1-off | 4,796 | 0.1657 | 0.1246 | 55.8% |
| 2-off | 6,628 | 0.0334 | 0.0418 | **-15.7%** |
| 3+off | 43,574 | 0.0040 | 0.0039 | 0.7% |

The model is sharper than the market two-plus bands out, and loses the
discrimination between the central two bands (>100% of net gap, offset by
the 2-off advantage). This is a boundary-calibration problem, not a
direction problem.

## 4. Difficulty: the gap is on medium days

medium 67.0% | easy-for-market 17.0% | hard-for-market 16.0%. On hard days
the model is nearly competitive (0.0518 vs 0.0495). The deficit is
under-commitment on days the market reads confidently.

## 5. Day extremes

Top contributors: atlanta 6/08 (11.9%), toronto 6/06 (9.2%), houston 6/07
(8.3%), san-francisco 6/07 (7.9%), miami 6/08 (7.4%). The model BEAT the
market outright on 5 of 21 fully-captured days: atlanta 6/07 (-6.8%),
nyc 6/07 (-5.0%), houston 6/08 (-4.8%), toronto 6/07 (-3.0%), toronto 6/09
(-2.0%).

## Implied work order

1. **Morning/overnight price sharpness in US markets** (night-12h ~48% of
   gap): the model already finds the right region from forecasts (it led the
   market to the winner in 9/12 markets on June 9); the deficit is committed
   pricing. Candidates: per-market probability calibration (item 34) as
   complete F days accrue, morning-hour blend weights for the F-city models
   (their v0.2 artifacts have no tuned weights), and the F v0.3 retrains.
2. **At-the-money discrimination** (central two bands): per-market
   calibration first; structurally the strongest argument for item 35's
   continuous-density model (2 F-degree bands need sub-band resolution).
3. Toronto morning block (13.7%) is the last meaningful Toronto cell; its
   mid-day is already ahead of the market.

Caveats: US sample is 4 days x 11 markets (June 6-9); 7 early Toronto days
have no captured corpus. Medium-day dominance and cell shares will move as
the supervised loop accrues complete days.
