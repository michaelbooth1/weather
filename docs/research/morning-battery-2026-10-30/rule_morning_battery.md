# Morning P0 battery at 00-06 and 07-12 (ledger row 81, lane L8, 2026-10-30)

This rule is pre-registered before any dev-window feature, outcome or price is read for it. One run.
Development evidence (dev window, provisional).

**Question:** at the morning hours, do model disagreement and the observed rise rate predict the market's error at
the same hour? That would be market under-reaction.

The battery comes from master, relayed by the coordinator on 2026-10-30. **Cheapest killer first:** S1 (inputs
only), then P0 directly on the dev window. There is no LOYO build.

## 1. Population and data (as rule 85f8192c §1)

- **Layout:** `C:/swarm/v3layout` (manifest `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`),
  loaded with `mr_gate.build_tables`.
  - Fit table: burn-in 08-01..08-14 plus the scored dates.
  - Score table: the scored dates 08-15..09-29.
  - 11 US markets, °F. Nothing after 2026-09-29 is read.
- **Blocks:** by the layout's `local_hour`: **00-06** (0..6) and **07-12** (7..12). An arm's values are NaN
  outside its block.
- **Market:** m = `Table.p_market` = the layout's `p_market_yes` (Gamma YES). The tapes' CLOB
  `last_trade_price` is never used.
- **Inputs:** receipt-dated only (§2). Replay inputs are `data/inbox/replay-inputs-le0929`, read by row 79's
  seek-bisect extraction.

## 2. Capture-time validity

Each source must have `ok` true and a `fetched_at` at or before the capture time t_c. A snapshot without that is
uncovered for every arm using the source.

| source | fields |
| --- | --- |
| Open-Meteo multimodel | `day_model_highs.ncep_hrrr_conus` (H) and `day_model_highs.ncep_nbm_conus` (N), from the same fetch |
| global_ensemble | `day_max_native` (G), the sweep's GEFS-CONTROL value |
| METAR | as row 79 §2 (see below) |

METAR handling, as row 79 §2:

- Source: `station_observations` rows, else `metar` rows. The receipt is at or before t_c.
- Observation time comes from the raw DDHHMMZ group, and only observations of local date D at or before t_c
  are used.
- Temperature is the T-group, else `temp_native`.
- The last row per observation time is kept.
- The latest observation must be at most 75 min before t_c.

## 3. Arms (fixed; K = 5 before the S1 screen)

Types are those of rule 85f8192c §4:

- **S:** s = g_z((z − μ)² − σ²)/σ².
- **D:** s = σ · g_z · (z − μ)/σ_m.
- g_z is standardised within market over the arm's covered fit-table snapshots, within its block.

| # | id | block | type | value |
| --- | --- | --- | --- | --- |
| 1 | DIS-HN-0006 | 00-06 | S, σ = +1 | \|H − N\| |
| 2 | DIS-HN-0712 | 07-12 | S, σ = +1 | \|H − N\| |
| 3 | DIS-NG-0006 | 00-06 | S, σ = +1 | \|N − G\| |
| 4 | DIS-NG-0712 | 07-12 | S, σ = +1 | \|N − G\| |
| 5 | RATE-0712 | 07-12 | D, σ = +1 | (T_obs − T_sr) / Δh |

- **Sign of the disagreement arms:** σ = +1 widens the market's distribution when the models disagree. The
  hypothesis is that the market under-prices uncertainty.
- **RATE-0712, the morning rise rate since sunrise:**
  - **Sunrise:** the NOAA solar-calculator sunrise (zenith 90.833°) for the station's latitude and longitude
    (`C:\swarm\stations.json`) on D.
  - **T_sr:** the temperature of the latest METAR observation at or before sunrise, observed no more than 75 min
    before sunrise.
  - **Δh:** t_obs − t_sr in hours, which must be at least 0.5 h. Otherwise the snapshot is uncovered.
  - **Sign:** σ = +1, so a fast rise tilts mass toward higher bands.
  - **No 00-06 arm:** sunrise is after 06:00 local on most dev dates, so there is no 00-06 rise-rate arm.
- **Parameters:** none is fitted.

### Arms not tested, decided before any read

- **Open-Meteo Previous Runs drift (latest minus the prior run's high): UNTESTABLE at registration, not in K.**
  - **Capture code at the pin:** `model_sources.py` writes `run_to_run_high_change: None` with
    `run_to_run_change_status: "requires_previous_run_archive"`, and `model_run_age_status:
    "not_exposed_by_open_meteo_*"` (lines 1908-1910 and 2411-2413).
  - **Replay:** it has no previous-runs source.
  - **Archive caches:** `open_meteo_archives` and `forecast_history` carry no capture-time receipt, and the
    interim cache rule forbids rebuilding them.
  - **Conclusion:** no issue time or receipt time is provable.
- **Cloud cover and dewpoint depression: dropped.**
  - **Levels:** row 78 tested MET-COVER and MET-DEWDEP as levels at all hours 00-23, and both were KILL. A
    morning-only level test is a subset of a killed test.
  - **Changes since sunrise:**
    - The change in dewpoint depression is (ΔT − ΔTd). Its ΔT part is RATE-0712's numerator, so it is not a
      clearly different construction.
    - Cover is a 0-4 ordinal from the first layer only. A change in it is coarse and mostly zero.
  - **Conclusion:** neither is added, and K does not count them.

## 4. Overlap with rows 78 and 79, stated explicitly

- **OM-MM-SPREAD** (row 78, S): the range (max − min) of the GFS, HRRR, NBM and NAM day highs from the same
  Open-Meteo multimodel fetch (`model_sources.py` line 2406, models at line 2322).
  - |H − N| is one pairwise component of that range, so it is never above it.
  - **This is the strongest overlap**, and the §5 screen tests it.
- **OM-GM-SPREAD** (row 78, S): the range of IFS, AIFS, GraphCast and AIGFS. These are different models, but the
  construction is related to DIS-NG (a scale signal from cross-model disagreement). It is screened in §5.
- **GEFS-CONTROL** (row 78, C): the same G series as DIS-NG. That arm is a location signal; DIS-NG is a scale
  signal (|N − G|).
- **OM-HRRR** (row 78, C): the same H series. Again, location against scale.
- **NBM-SKEW** (row 78, D): NBP quantile skew, a different product and a different construction. No overlap.
- **MET-COOLING** (row 78, D: T − running max): it uses the same T_obs as RATE-0712. In the morning the running
  max is often the overnight value, whereas RATE-0712 references the temperature at sunrise. Screened in §5.
- **MET-MAX, MET-DEWDEP, MET-COVER** (row 78): no arm uses them (§3).
- **Row 79** (13-16 only): there is no shared block. RATE-0712 and the row 79 arms share the METAR parse code only.

## 5. S1 (inputs only: no label, no price, no statistic)

- **Coverage and receipts:** per arm, the covered scored snapshots and dates, the receipt audit, and the share of
  snapshots dropped by the freshness and sunrise rules.
- **Redundancy screen (pre-registered):** on covered fit-table snapshots in the arm's block, compute the Spearman
  ρ between the arm's value and the capture-time value of each screened row 78 candidate:
  - DIS-HN and DIS-NG against `mm_spread` and `gm_spread`;
  - RATE-0712 against `met_cooling`.

  The row 78 values use the same receipts. **If |ρ| >= 0.80 for any screened pair, the arm is REDUNDANT**: it is
  dropped before P0 and removed from K. Every ρ is reported.
  The screened values are computed by the pinned `mr_sweep.record_features` and `mr_sweep.candidate_values`,
  the sweep's own code. No sweep result file is opened.
- **UNTESTABLE:** fewer than 20 covered scored dates or fewer than 1,000 covered scored snapshots. The same floor
  is applied again by `p0_candidate` (`MIN_DATES`, `MIN_SNAPS`) to the donor-covered population. Its p is set to 1,
  and it stays in K.
- **S1 kill:** if no arm remains testable, the rule stops.

## 6. P0 and the decision (rule 85f8192c §5 exactly, at pin `8bb0f9563582885c4d01d34b67476f2563260e43`)

- **Machinery:** `mr_sweep.p0_candidate` per remaining arm.
  - Calibration-matched disagreement placebo: J = 20, seeds 20260921 + j, donors within (market, local hour).
  - B = 10,000 date-cluster draws, seed 20261024.
  - Population: covered snapshots whose donors are also covered.
  - Statistic: Δ = ρ_c − mean ρ_pl, with its one-sided p.
- **Benjamini-Hochberg** at q = 0.10 over K = the arms remaining after the redundancy screen.
- **Survivor** iff BH rejects and Δ's lower 95% bound > 0.
- **Also reported:** ρ_c and mean ρ_pl with their intervals, the c-deranged diagnostic, and Δ by market and by
  block.
- **Survivors only:**
  - `market_blend.w0_identity` must hold; a miss refuses the run.
  - Then `mr_gate.gate_candidate(arm, block, …, p_placebo_fit = the j = 0 placebo)`. The pinned `mr_gate.BLOCKS`
    has no "00-06", so the driver adds `"00-06": (0, 6)` in-process. That is the only change, and it only
    selects hours.
  - **PASS iff all four** (rule 37cb46be): mean w >= 0.05; blend R date upper < 1; blend − placebo upper < 0;
    blend − floor-only upper < 0.
  - A tradability replay follows only for a PASS, under its own clarification.

## 7. Outputs and execution

- **Receipt:** run-env HEAD (the pin, clean), driver sha, layout manifest sha, replay SHA256SUMS sha, malformed
  lines, S1 coverage and screen, and every statistic and verdict.
- **Per-date rows:** from `p0_candidate`, per arm and date; for survivors, also w and the paired Brier.
- **Features:** a parquet of the arm values and receipts.
- **Execution:** light stages run directly with their shas recorded. A stage that would exceed 1 min or 1 GB goes
  through `workstation_heavy -Queue`, or the lane stops and asks.

## 8. Disclosures

- **Further reads of the US dev window, in addition to:**
  - the parity swarm;
  - MG-1 (07-12);
  - R-PD / R-N (00-06);
  - the MR gate (37cb46be);
  - the MR sweep (row 78), which tested OM-MM-SPREAD, OM-GM-SPREAD, GEFS-CONTROL, OM-HRRR, NBM-SKEW and MET-* at
    all hours on this window;
  - row 79.
- **Sweep results:** L8 has not opened them. The coordinator relayed that MET-COVER and MET-DEWDEP were KILL.
- **Morning data:** the 07-12 and 00-06 blocks have been the most-read morning hours on this window.
