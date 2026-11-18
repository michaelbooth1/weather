# MRMS echo against the market: market-residual P0 rule (ledger row 91)

Status: pre-declared before any computation (2026-10-30, lane L3). Evidence class: dev-window kill-only P0
screen. It is its own arm with its own K. It is not pooled with rows 78, 81 or 85-90. Nothing here is a release,
serving, capture or scheduling decision. Eligibility: coordinator ruling 2026-10-30 (lever map item 5, register
X7, inventory row 17), design (a) + (b) as ruled after the cover finding in section 4.

## 1. Mechanism and prior, written before any read

A convective cell with high reflectivity within 25 km of the station at 13-16 local signals outflow or rain
cooling that caps the day's maximum before the cooling or cloud reaches the station's METAR/WU prints, which the
market prices from. The informative part is the 10-60 min before the cold pool arrives, which METAR-derived
signals (MET-COOLING, MET-COVER) cannot see.

The prior is low. Weaknesses, stated now:

- radar is free and visible to every trader in common apps, so the claim that the market lacks it is weak;
- the horizon is under 1 h, and at 13-16 the running maximum is often already set;
- the METAR consequences of convection are already null against the market on these dates (section 3);
- F2 closed about 2% of the 13-16 gap, and only over t3-r3;
- the convective markets carry any effect; the Pacific markets have almost no echo.

## 2. Machinery

Identical to `docs/research/mr-sweep-2026-10-30/rule_mr_sweep.md`
(sha256 `85f8192cc260cadb9a8ec3db010016e9952515a9492de896d8907e68075b1956`), sections 1-5, except where this
file says otherwise:

- layout `C:/swarm/v3layout`; burn-in 2026-08-01..08-14; scored 2026-08-15..09-29; e = y - m; every layout market
  except toronto;
- market moments with the sigma^2 floor 0.25; the exponential tilt;
- type D band signal s_b = sigma * g_z * (z_b - mu_m) / sigma_m with sign sigma = -1 (MET-COVER's form);
- the calibration-matched disagreement placebo (J = 20, seeds 20260921+j); Delta = rho_c - mean rho_pl;
  B = 10,000 date-cluster draws, seed 20261024; one-sided p;
- UNTESTABLE below 20 covered dates or 1,000 snapshots; per-date rows and per-market per-date rows.

Only snapshots whose local hour is 13..16 inclusive are used. Nothing after 2026-09-29 is read.

## 3. Prior reads (disclosed)

- **F2** (ledger row 7, EF §10y): the same archive, the same dev dates and the same variable
  (max reflectivity >= 35 dBZ within 25 km) were read with outcomes at 13-16 as a t3-r3 conditioning:
  -0.0005 [-0.0010, -0.0001] over t3-r3, 7/11 markets. Model against model, never against the market.
- **13-16 against the market on these dates**, all killed or null: X45 R-K (HRRR P3d_H, KILL at the w gate);
  the sweep's 13-16 block lines in receipt `02c46630…` (X59 MET-MAX +0.016 [-0.041, +0.082]; X60 MET-COOLING
  -0.003 [-0.056, +0.046]; X61 MET-DEWDEP -0.018 [-0.069, +0.032]; X62 MET-COVER +0.041 [-0.013, +0.097]);
  X66-X70 forecast-tracking residuals (all null; RISE-T3R3 raw p 0.035, q 0.155).
- **Input-only reads before this rule** (no outcome, price or label): the S1 coverage audit and a per-station
  distribution of the 2026-08-01..09-29 values (share of slots >= 35 dBZ: MIA 0.48, HOU 0.28, ATL 0.19, AUS 0.11,
  BKF 0.11, ORD 0.10, LGA 0.08, LAX 0.04, SEA 0.04, DAL 0.03, SFO 0.001; -99 in 69% of slots; cover_25km below 1 in
  0.0-0.1% of slots per station).

## 4. Candidates (K = 2)

Source: `data/research/free_sources/mrms_refl/station_refl.parquet` in the main checkout, sha256
`3446d1a6d134b6059b4ca7d1e3694bc7cc3a033bae6a65ba73850c49acee97be` (NOAA `noaa-mrms-pds`
`MergedReflectivityQCComposite_00.50`, the newest object at or before each :00/:30 UTC, 16:00Z-23:30Z). The run
refuses on a sha mismatch. Rows with `valid_utc` on or after 2026-09-30 00Z are dropped.

Join (F2's, unchanged): per snapshot, the newest slot at the market's layout station with
`valid_utc + 5 min <= captured_at_utc` and `valid_utc >= captured_at_utc - 40 min`. A snapshot without one, or
whose `max_dbz_25km` is not finite, is uncovered.

| id | value g | type | sign |
| --- | --- | --- | --- |
| MRMS-MAXDBZ25 | max(`max_dbz_25km`, 0) (the -99 "no echo" code maps to 0 dBZ before z-scoring) | D | - |
| MRMS-ECHO35 | 1 if `max_dbz_25km` >= 35, else 0 (F2's construct) | D | - |

- Sign -: a high echo near the station moves mass toward the lower bands.
- g_z is standardised within market over that market's covered fit-table snapshots. **If a market's sd is below
  1e-9 there, its g_z is 0 (zero tilt, c = m) for that market.** The run reports the markets affected per
  candidate (SFO is the expected case for ECHO35).
- (a) and (b) are strongly correlated by construction. BH over K = 2 stays as declared; no correction for the
  dependence is made (BH is valid under positive dependence).
- **`cover_25km` is not a candidate.** It is radar data coverage, not echo area: `src/weather/sources/free_screens/
  mrms.py:119` sets it to the share of disk pixels that are not -999 (no coverage). It is reported as QC only.
- **Descriptive arm (not in K, no decision):** the same two values at 50 km (`max_dbz_50km`), reported only.

## 5. Serve parity

NONE. Production never captured a reflectivity value (the `mrms_precip` listing poll stored only an object
listing and was stopped on 2026-10-02, `b8e4eef1f9211d508f80629296af252da1a035dd`); the F2 capture change is held
(DECISION_LOG 2026-10-24). No forward recorder exists.

Correction: lever inventory row 17's "no 2021-25 history" is wrong. The archive holds Aug-Sep 2024 and Aug-Sep
2025 as well as 2026-07-31..09-29 (not read here).

## 6. Decision

- BH at q = 0.10 over K = 2.
- A candidate SURVIVES iff it is testable, BH-rejected and its Delta 95% lower bound is > 0. Otherwise KILL, or
  UNTESTABLE.
- Only for a survivor: the w = 0 identity control, then the sweep's w gate in block 13-16 with c_pl,0 as the
  placebo.
- One run. Outputs: a receipt JSON, per-date and per-market per-date rows, the extracted feature file.

## 7. Kill and reopen line (written now)

A KILL of both closes MRMS against the market for 13-16 echo maximum and echo flag at 25 km. It reopens only with
a new construct that needs a re-fetch of the raw grids (for example echo area, cell motion or distance), under a
new rule with its mechanism written first. A survivor is NOT promotable: it earns only the owner question on the
held capture change, raised through master.
