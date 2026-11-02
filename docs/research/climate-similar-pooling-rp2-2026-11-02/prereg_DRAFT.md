# R-P2 climate-similar station pooling: pre-registration DRAFT (not frozen)

Status: **DRAFT for master review.** Nothing is frozen, no ledger row is assigned, and no compute on outcomes has
been run. Successor to R-P (row 109, KILLED 2026-11-02; archive `C:\archive\ruled-out\station-pool-n300\`). Lane L48.

## 0. Disclosure: why this exists

This draft was **prompted by row 109's los-angeles result.** R-P pooled 300 IEM ASOS stations into one P3d_N_fix fit:

- The pooled Brier d was −0.00185 (block-3 CI [−0.00355, −0.00007]), and 5 markets were CI-better.
- But los-angeles was CI-worse at +0.0217 [0.0158, 0.0278], and its held-out residual shifted about 0.33 °F warm.

The hypothesis comes from those numbers, so the same five training years cannot confirm it (§5). The similarity rule
below uses no residual, LOYO number or per-market result. It names no market, and it is fixed here before any run.

## 1. Physical rationale and the one primary similarity rule

**Mechanism.**

- Near the open ocean, the summer daily maximum is capped by the marine boundary layer and the sea breeze. Stratus, a
  cool onshore flow and a shallow mixed layer can arrive at different times on different days, so these stations'
  highs sit below an inland-style relation to the NBM.
- Inland stations reach their maximum through dry convective mixing, with a larger and more regular diurnal range.
- A single pooled residual model, dominated by inland rows (most of the 300 are inland), learns the inland
  error-to-guidance relation. It then transfers that relation to marine-influenced stations.

The defining physical variable is **distance to the open-ocean coastline**. That is the length scale over which
summer sea-breeze and marine-layer air reaches inland (typically tens of km).

**Primary rule R-P2 (station metadata only):**

- `coast_km` is the great-circle distance from the station's IEM latitude and longitude to the nearest point of the
  **Natural Earth 1:10m `ne_10m_coastline`** layer. That layer is the ocean coastline, including connected bays and
  sounds; inland lakes are a separate layer and are excluded.
- **Class `marine`** if `coast_km ≤ 25`; otherwise **class `continental`**.
- The same computation classifies the 11 markets. The registry's hand-set `coastal` flag is **not** used.
- 25 km is fixed now as a round value inside the usual summer sea-breeze penetration range. No other threshold is
  tried for the primary arm.

**Data needed (metadata fetch; coordinator ruling required first).** One free, public-domain Natural Earth coastline
file, about 3 MB zipped. Nothing on disk carries station-to-coast distance: no GIS package or coastline file was
found; IEM metadata has only lat, lon, elevation and state. This is a geography layer, not weather data, and it is
read with -I as untrusted data. It must be recorded with its sha256 before any classification.

## 2. Arms

| Arm | Training rows per (hour, held-out year), for scoring market m | Role |
| --- | --- | --- |
| `P3d_N_11m` | R-A's rows for the 11 markets (unchanged, as in row 109) | base |
| **`P3d_N_cls`** | the same base rows **plus** the row-108 pool stations whose class equals m's class | **primary (one candidate)** |
| `P3d_N_cls100` | the base rows plus the class-matched stations among the **first 100** survivors (row-108 order, nested) | descriptive dose only, never gating |

Arm mechanics:

- Model code is identical to row 109: master's B-bound `fit_pooled(train, market_id=False, doy=True,
  raw_columns=False)`, unedited. The arm therefore makes **two fits per (hour, fold)**, one per class, and each market
  is scored by its class's fit.
- Pool rows come from the frozen row-108 corpus `a57e10a6…`, reused unchanged (no new label fetch). Its station
  filter and order were fixed before any label read.

## 3. Per-market station-count change (outcome-blind, from metadata)

Under R-P each of the 11 markets trained with all 300 pool stations. Under R-P2 each market trains with the pool
stations in its own class: (300 − n_marine) or n_marine.

**These counts can't be computed yet:** `coast_km` needs the §1 coastline file, which needs your ruling. Once ruled,
the count is a pure metadata computation over the 300 survivors' IEM coordinates and the 11 market coordinates, with
no label, residual or score read. It will be reported here before the rule freezes:

- n_marine and n_continental;
- each market's class and pool count;
- the change from 300.

If n_marine < 30, the primary arm is **refused before any run** and reported as underpowered by construction. No
threshold change is allowed.

## 4. Row-109 LOYO gate = necessary screen only

The row-109 gate is applied unchanged as a **screen**: blocked LOYO over 2021-25 Aug-Sep, h07..12, scored on the 11,
with all four kill conditions:

- point ≥ −0.0005;
- the wider 95% upper bound ≥ 0;
- any market's date-clustered lower bound > 0;
- more than 1 of 5 years with d > 0.

Gating controls C-0 and C-b also apply. **Passing the screen confirms nothing**: the same years and the same corpus
informed this design (§0). A screen failure kills R-P2. A screen pass only licenses the confirmation stage (§5).

## 5. Confirmation on data that did not inform the design, with power computed before freezing

**Variance input (already disclosed, outcome-blind for R-P2).** Row 109's LOYO per-date d (`loyo_rows.jsonl` sha256
`cb313205…`, already read and reported). No dev-window label was opened.

| Quantity | Value |
| --- | --- |
| Dates, rows per date | 300, 65.5 |
| SD of the per-date mean d | 0.01630 |
| Lag-1 autocorrelation of per-date d within a year | 0.137 |
| Variance inflation used | 1.318 (AR(1) (1+ρ)/(1−ρ); the block-3 vs clustered CI-width ratio gives 1.19) |

Script: `C:\t\l48\scripts\rp2_power_v1.py`, sha256 `4971187da6c88635f76d9a1b6795e79ac8d15ebe3f0807f9624e98a78e9fc9f2`.

Assumptions:

- The expected effect is **0.002 Brier**.
- 80% power, two-sided.
- Dev reuse is counted as a Bonferroni-style alpha cut. 0.01 corresponds to about 5 earlier reads of this window in
  the family, and 0.005 to about 10. The exact count is for master to set.

| Test | α = 0.05 | α = 0.01 (reuse ≈ 5) | α = 0.005 (reuse ≈ 10) |
| --- | --- | --- | --- |
| **Dev window 2026-08-01..09-29 (60 dates), MDE80** | 0.0068 | 0.0083 | 0.0088 |
| MDE80 ÷ expected effect | **3.4x** | 4.1x | 4.4x |
| **Forward shadow: dates needed for MDE80 = 0.002** | **≈ 690** | ≈ 1,020 | ≈ 1,170 |

**Reading.**

- The dev-window MDE80 is more than 2x the expected effect at every alpha. Under the binding rule, the deciding test
  must therefore be a **pre-registered forward shadow**.
- At 0.002 a forward shadow needs about 690 scored dates (11 markets × 6 cutoffs each) even at α = 0.05.
- P3d_N_fix trains and is served on **Aug-Sep only**. About 690 dates is far beyond one Aug-Sep season, so it would
  take about 11 seasons at 60 dates each, or an extension of the model's season (a separate lever).

Proposed forward design, for master to choose:

- (a) Forward shadow on Aug-Sep 2027, 60 dates. It is powered only for an effect of about 0.0068 (3.4x the
  expectation). There is a futility look at 30 dates: stop if the point is ≥ 0, or if conditional power for 0.002 is
  below 20%.
- (b) Do not run R-P2 confirmation at all. Register it as untestable at the expected size.

I recommend (b), unless master sets a larger expected effect from a physical argument made before any R-P2 number
is read. Both numbers are given so master can choose.

**Embargo.** No 2026-09-30..10-15 data and no sealed panel. The dev window is not opened by this draft. A forward
shadow would read only dates after its freeze.

## 6. Futility and order (if approved)

1. Coordinator ruling on the coastline fetch.
2. Compute `coast_km` and the classes; report the §3 counts; refuse the arm if n_marine < 30.
3. Master freezes this rule (with its sha), with the forward option chosen.
4. Row-109 screen via `workstation_heavy.ps1 -Queue` (training years only). A KILL is archived under
   `C:\archive\ruled-out\rp2-climate-similar-pooling\`.
5. Forward shadow per §5, only if the screen passes and master chose (a).
