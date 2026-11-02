# R-P2 climate-similar station pooling: frozen pre-registration

Status: **frozen at this file's first commit**. Its sha256 is in `prereg_rp2.md.sha256`. Any later change is a
dated clarification in a separate file, committed before the rows it affects.

Lane L48. Master ruling 2026-11-02, relayed by the coordinator: R-P2 is not parked, and the cheap screen comes first.
The draft `prereg_DRAFT.md` (sha256 `68088acd38e364c5d1109551068849c29441df31c0269eb6742823250833b88a`) is
superseded by this file.

Standing boundaries:

- Research only.
- No dev-window label read: dev stays unread.
- No 2026-09-30..10-15 data and no sealed panel.
- No B-bound file edited.
- The screen runs only after master's OK, through `workstation_heavy.ps1 -Kind weather_heavy -Queue`, after the
  cleanup pass, on the coordinator's explicit GO.

## 0. Disclosure

R-P2 was **prompted by row 109's los-angeles result**. R-P (row 109, KILLED) gave:

- a pooled Brier d of −0.00185 (block-3 CI [−0.00355, −0.00007]);
- 5 markets CI-better;
- los-angeles CI-worse at +0.0217 [0.0158, 0.0278], with a held-out warm shift of about 0.33 °F.

The hypothesis is therefore **design-informed by the same five training years and the same pool corpus**. The
similarity rule uses station metadata only: no residual, no LOYO number, no per-market tuning, no market named.

## 1. Similarity rule (one primary rule, metadata only)

**Mechanism.**

- Near the open ocean, the summer maximum is capped by the marine boundary layer and the sea breeze, which arrive at
  different times on different days.
- Inland stations reach their maximum through dry convective mixing.
- A pooled residual model dominated by inland rows transfers the inland error relation to marine-influenced stations.

The physical length scale is distance to the open-ocean coastline, which bounds how far summer sea-breeze and
marine-layer air penetrates.

**Rule.**

- `coast_km` is the distance from the station's IEM latitude and longitude to the nearest segment of Natural Earth
  1:10m `ne_10m_coastline`. That layer is the ocean coastline, including connected bays and sounds; inland lakes are
  a separate layer and are excluded.
- The distance is computed in a local equirectangular projection around the station, with R = 111.195 km per degree.
  The error is a few percent at tens of km.
- **`marine` if `coast_km ≤ 25`, else `continental`.**
- The 11 markets are classified by the same computation from their IEM coordinates. The registry `coastal` flag is
  not used.

**Reference data (fetched under the master ruling, untrusted, read with `python -I` by a script kept outside the data
directory):**

| Item | Value |
| --- | --- |
| URL | `https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip` (Natural Earth official CDN, public domain) |
| Local path | `C:\t\rp2\ref\ne_10m_coastline.zip` (new empty directory) |
| Bytes | 3,069,451 |
| sha256 | `bfa04cdbcbef07ef90dfca1dabb48062eca29900a113df0f389303e255484017` |
| HTTP Last-Modified, ETag | Wed, 08 Dec 2021 00:46:48 GMT; `7b79c23ead071ef6417f9e83ebe3ab20` |
| Fetch time (WS Get-Date) | started `2026-11-02T13:13:55.8918680-05:00`; done by `2026-11-02T13:13:56.1572124-05:00` |
| Classifier | `tools/research/rp2_coast_classes_v1.py` sha256 `a790e7d45b8b09c10b8df3217e524dffc55c200092bf29d925052651a0664b43`: a plain-Python shapefile reader, no new library |
| Output | `rp2_classes.json` (this folder), sha256 `35d0090dddf7b082c5ce0d777cf488c09bbcf6baead14c786e68c39fbafe1689` |

## 2. Outcome-blind station counts (metadata only; no label, residual or score read)

The pool is the frozen row-108 set: 300 survivors, of which the first 100 are the dose subset.

| Class | Pool stations (of 300) | Dose subset (of 100) |
| --- | --- | --- |
| marine | **45** | 11 |
| continental | **255** | 89 |

| Market | ICAO | coast_km | Class | Pool stations under R-P | Under R-P2 | Change | Dose subset under R-P2 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| atlanta | KATL | 353.5 | continental | 300 | 255 | −45 | 89 |
| austin | KAUS | 189.5 | continental | 300 | 255 | −45 | 89 |
| chicago | KORD | 1186.8 | continental | 300 | 255 | −45 | 89 |
| dallas | KDAL | 383.3 | continental | 300 | 255 | −45 | 89 |
| denver | KBKF | > 800 (none within the 8° search box) | continental | 300 | 255 | −45 | 89 |
| houston | KHOU | 22.7 | marine | 300 | 45 | −255 | 11 |
| los-angeles | KLAX | 4.6 | marine | 300 | 45 | −255 | 11 |
| miami | KMIA | 9.9 | marine | 300 | 45 | −255 | 11 |
| nyc | KLGA | 0.2 | marine | 300 | 45 | −255 | 11 |
| san-francisco | KSFO | 0.8 | marine | 300 | 45 | −255 | 11 |
| seattle | KSEA | 3.8 | marine | 300 | 45 | −255 | 11 |

Notes on the counts:

- n_marine = 45 ≥ 30, so the arm is not refused.
- Pool stations within 20-30 km of the coast, disclosed only and not reclassified: KAKQ, KBGR, KBKV, KCDW, KKLS, KLBX,
  KNIP, KSAV.
- houston (22.7 km) is also near the threshold. The rule stands as frozen.
- Six markets change class pool: houston, los-angeles, miami, nyc, san-francisco and seattle. Five of them (all but
  los-angeles) were among R-P's CI-better or neutral markets.

## 3. Arms

| Arm | Training rows per (hour, held-out year), for scoring market m | Role |
| --- | --- | --- |
| `P3d_N_11m` | R-A's rows for the 11 markets (as in row 109) | base |
| **`P3d_N_cls`** | the base rows plus the row-108 pool stations whose class equals m's class | **primary** |
| `P3d_N_cls100` | the base rows plus the class-matched stations among the first 100 survivors | descriptive dose only |

Arm mechanics:

- The model code is unchanged: master's B-bound `fit_pooled(train, market_id=False, doy=True, raw_columns=False)`,
  `MeanModel.predict` and `predictive_distribution`.
- **Two fits per (hour, fold)**, one per class. Each market is scored by its class's fit, with R-A's bucket spaces
  and `p_clim`.
- The pool rows are the frozen corpus `a57e10a60fce936a98cd8478423b502496afa7347967eaaac1d452e453aad39f`, unchanged.
- C-0 is unchanged: `P3d_N_11m` must reproduce R-A to 1e-9.
- C-b: with empty class pools, `P3d_N_cls` must give results identical to `P3d_N_11m` on (h07, held-out 2021).

## 4. SCREEN = the row-109 LOYO gate (necessary only)

d = Brier(`P3d_N_cls`) − Brier(`P3d_N_11m`), over h07..h12, mean per row. Folds are blocked leave-one-year-out over
2021-25 Aug-Sep. Intervals: date-clustered bootstrap and block-3, each with 2,000 draws and seed 20261024; the wider
upper bound decides.

**KILL** if any of these holds:

1. point ≥ −0.0005;
2. the wider 95% upper bound ≥ 0;
3. any market's date-clustered 95% lower bound > 0;
4. more than one of the five years has d > 0.

**Passing the screen is necessary only. It is not confirmation**, because the screen data informed the design (§0).
Reported but never gating: log loss, per-hour, per-market and per-year tables, `P3d_N_cls100`, and D-x residuals.

## 5. Why dev is not the deciding test

The variance input is the already-read row-109 per-date d (SD 0.01630 over 300 dates, about 65.5 rows per date;
within-year lag-1 ρ 0.137, AR(1) inflation (1+ρ)/(1−ρ) = 1.318). Its file is `power_inputs.json`, and the script is
`tools/research/rp2_power_v1.py` sha256 `4971187d…`.

The dev-window (2026-08-01..09-29, 60 dates) **MDE80 is 0.0068** at two-sided α = 0.05, or 0.0083 / 0.0088 at the
reuse-cut α of 0.01 / 0.005. That is 2.3-2.9x the 0.003 planning effect, so the dev window can't decide. **Dev stays
unread.**

## 6. CONFIRMATION = pre-registered forward shadow

**Planning effect 0.003 (master's derivation).**

- If class matching only neutralises los-angeles's harm, the pooled d moves from −0.00185 to about −0.0038. LA's
  +0.0217 over one-eleventh of the rows contributed about +0.0020 of the pooled mean.
- Shrinking that by about 20%, for the winner's curse and for nyc, miami, houston, san-francisco and seattle changing
  class pools, gives 0.003.

**Length by power** at an effect of 0.003, 80% power, AR(1) inflation 1.318:

| Two-sided α | Forward dates needed |
| --- | --- |
| 0.05 | **306** |
| 0.01 | 455 |
| 0.005 | 519 |

The formula is n = ((z_{1−α/2} + z_{0.8}) · 0.01630 / 0.003)² · 1.318, with 11 markets × 6 cutoffs scored per date.

**Season scope.** Master ruled a year-round shadow *if* the row-109 LOYO dates span all seasons.

- **They do not.** The row-109 LOYO dates cover **August and September only** (2021-25, 300 dates).
- P3d_N_fix is also trained and served on Aug-Sep only.
- So the year-round condition **is not met**. The power numbers above are valid for Aug-Sep. At 60 Aug-Sep dates a
  year, 306 dates is about 5 seasons.
- Year-round, about 10 months, would need a model fitted outside Aug-Sep and a variance input from those months.
  Neither exists here.
- **The season scope of the shadow is left for master's ruling before the shadow starts.** The screen does not
  depend on it.

**Futility look at 50% (153 dates at α = 0.05).** Master's wording: KILL if the half-way estimate is ≥ 0, or if its
upper CI misses −0.0015.

- This file's operationalisation, to be confirmed by master before the shadow starts: KILL if the half-way point
  estimate is ≥ 0, **or** if the half-way 95% CI lies wholly above −0.0015 (lower bound > −0.0015).
- At 153 dates the expected SE is about 0.0015 and the CI half-width about ±0.0030.

**Start condition.** The shadow starts only if the screen passes **and** the owner OKs it; master asks at that point.
It reads only dates after its own start.

## 7. Order

1. Done: the coastline fetch and the counts in §2.
2. This freeze, committed and pushed after screening.
3. Master's OK, then the screen via `-Queue` after the cleanup pass, on the coordinator's GO.
4. The screen verdict goes to the coordinator; a KILL is archived under
   `C:\archive\ruled-out\rp2-climate-similar-pooling\`.
5. The forward shadow per §6, only with a pass and the owner's OK.
