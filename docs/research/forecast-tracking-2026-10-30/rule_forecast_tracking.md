# Forecast-tracking residual P0: does how today is tracking its forecast predict the market's error? (lane L8, 2026-10-30)

This rule is pre-registered before any dev-window feature, outcome or price is read for it. One run.
Development evidence only (dev window, provisional). It is dev-window ledger row 79.

The idea comes from master, relayed by the coordinator on 2026-10-30. At 13-16 local, the market may
under-react to whether the day is running warmer or cooler than its hourly forecast, and to how much rise
remains. If it does, a signal built from (observed temperature − hourly forecast), and from the
remaining-rise climatology, predicts the market's error at the same hour.

**Cheapest killer first:** S1 (inputs only), then P0 directly on the dev window. There is no LOYO or
history build beyond the t3-r3 table (§3.4).

## 1. Population and data (as rule 85f8192c §1, restricted to 13-16)

- **Layout:** `C:/swarm/v3layout` (manifest sha256 `4d53fdbdc551f33e331fa3b51cc425e354eec4426c8c7b52910b2e7340915f22`),
  loaded with `mr_gate.build_tables`.
  - Fit table: burn-in 2026-08-01..08-14 plus the scored dates.
  - Score table: the scored dates 08-15..09-29.
  - 11 US markets, °F. Nothing after 2026-09-29 is read.
- **Snapshots:** only snapshots with local hour 13-16 can be covered. Every other snapshot is uncovered
  (c = m) and outside every population.
- **Market:** m = `Table.p_market`, the layout's `p_market_yes`. L3's audit confirmed this is the Gamma YES
  price. The tapes' CLOB `last_trade_price` is never used.
- **Outcome:** y = the band winner indicator; e = y − m. Labels are the layout's.
- **Band geometry:** z_b, μ_m and σ_m² (floor 0.25 °F²) as in rule 85f8192c §1 (`mr_sweep.band_geometry`).

## 2. Capture-time validity (receipt-dated; Toronto standard)

A value is covered at a snapshot with capture time t_c only if every input below is receipt-dated at or
before t_c.

### METAR

- **Source:** the replay record's `station_observations.data.rows`, falling back to `metar.data.rows` when
  those are empty.
- **Receipt:** the source must have `ok` true and `fetched_at` <= t_c.
- **Observation time:** parsed from the raw METAR's `DDHHMMZ` group, not from the nominal `datetime` or
  `report_time`. This keeps the parse M0-safe (EF M0 defect).
- **Rows used:** routine and SPECI rows whose observation local date is D and whose observation time is
  <= t_c. COR duplicates are dropped by keeping the last row per observation time.
- **Temperature:** from the T-group (°C × 1.8 + 32) when present, else `temp_native`, unrounded.
- **Derived values:**
  - RM = the running max of those rows;
  - T_obs = the temperature of the latest row;
  - t_obs = that row's observation time.
- **Freshness (validity, as the t3-r3 finding requires):** t_c − t_obs <= 75 min; otherwise every arm is
  uncovered.

### HRRR hourly

- **Source:** `open_meteo_multimodel.data.day_rows[*].models.ncep_hrrr_conus.temp_native`, at each row's
  `valid_time` (local hour of D).
- **Receipt:** the source has `ok` true and `fetched_at` <= t_c, which proves the series was in hand by t_c.

### NBM hourly (NBH text)

- **Source:** the `C:\t\l12\nbs_nbh_2026dev` corpus, the station's block from the newest cycle with
  issued <= S3 `LastModified` <= t_c. This is the same per-cycle issuance receipt as row 77's
  `availability_audit.md`.
- **Values:** TMP (°F) at valid times issue + 1h … issue + 25h.

### Forecast at t_obs

- F_X(t_obs) is the linear interpolation between the two bracketing hourly values of source X.
- If t_obs is not bracketed, that arm is uncovered.

### t3-r3 table

- Built from IEM routine non-COR METAR (`C:\swarm\data\iem\metar`), using **only local dates <= 2026-07-31**
  (history: Aug-Sep 2024-25).
- Definitions are fixed by `tools/research/model_parity/t3_baselines.py`:
  - a complete day needs >= 20 routine rows;
  - the history running max is taken at local H:30;
  - integer pmf smoothed with a discrete Gaussian, sd 1 °F;
  - negative rise folded onto 0.
- Kept cells: station × month (8, 9) × local hour (13-16).

## 3. Arms (fixed; K = 5)

Types and band signals are those of rule 85f8192c §4 (`mr_sweep.band_signal`, `tilt`):

- **C:** s_b = (x − μ_m)(z_b − μ_m)/σ_m².
- **D:** s_b = σ · g_z · (z_b − μ_m)/σ_m, where g_z is standardised within market over that arm's covered
  fit-table snapshots.

| # | id | type | value |
| --- | --- | --- | --- |
| 1 | TRK-HRRR | D, σ = +1 | τ_H = T_obs − F_HRRR(t_obs) |
| 2 | TRK-NBH | D, σ = +1 | τ_N = T_obs − F_NBH(t_obs) |
| 3 | PROJ-HRRR | C | max(RM, max over v in (t_c, 23:00 local D] of F_HRRR(v) + τ_H) |
| 4 | PROJ-NBH | C | the same with NBH and τ_N |
| 5 | RISE-T3R3 | C | RM + E[rise], the mean of the t3-r3 pmf for (station, month of D, local hour of t_c) |

- **Sign:** σ = +1 for both TRK arms. Running warm (τ > 0) tilts mass toward higher bands.
- **PROJ arms:** these are the "tracking projection". The forecast's remaining-hours path is shifted by
  today's tracking error and floored at the running max. If no forecast hour remains, the value is RM.
- **Parameters:** none is fitted. Every constant above is fixed here.

### Overlap with the MR sweep (rule 85f8192c, `claude/mr-sweep-20261030`), stated explicitly

- **MET-MAX** (C, x = the METAR same-day max):
  - RISE-T3R3 is MET-MAX's centre plus a station × month × hour constant. At a fixed (market, hour) it is
    MET-MAX shifted, so it is the arm closest to a sweep candidate.
  - PROJ-HRRR and PROJ-NBH use the running max as a floor.
- **MET-COOLING** (D, current temperature − running max): the TRK arms use the same current temperature, but
  measured against a forecast rather than the running max. They are correlated whenever the forecast is flat
  at the high.
- **OM-HRRR** (C, the HRRR day high): same source series as the HRRR arms.
  - PROJ-HRRR equals OM-HRRR when τ_H = 0, the HRRR day high falls after t_c, and RM is below it.
  - TRK-HRRR uses the HRRR value at the observation hour, not the day high.
- **MET-DEWDEP, MET-COVER, NBM-SKEW, OM-\* except HRRR, GEFS-\*:** no overlap. NBH is a different NBM
  product from the layout's NBP-based v2.
- L8 has not opened the sweep's results.

## 4. S1 (inputs only: no label, no price, no statistic)

- **Coverage report:** per arm, the scored 13-16 snapshots and dates that are covered, and the per-market
  split.
- **Receipt audit:**
  - METAR, HRRR and NBH receipts are each <= t_c on every covered snapshot. A violation uncovers that
    snapshot; it does not kill the arm.
  - NBH per-cycle latency (`LastModified` − issued) by station.
  - The share of snapshots dropped by the 75-minute freshness rule.
- **UNTESTABLE:** an arm with fewer than 20 covered scored dates or 1,000 covered scored snapshots. Its p is
  set to 1 and it stays in K.
- **S1 kill:** if all five arms are UNTESTABLE, the rule stops and P0 is not run.

## 5. P0 and the decision (rule 85f8192c §5 exactly, at pin `8bb0f9563582885c4d01d34b67476f2563260e43`)

- **Machinery:** `mr_sweep.p0_candidate` per arm, the code that implements the following unchanged.
  - **Disagreement placebo:** c_pl(d) = m(d) + (c(d′) − m(d′)), with the donor from
    `market_blend.placebo_vector` on the fit table. Clip to [EPS, 1], then renormalise to sum(m).
  - **Seeds and bootstrap:** J = 20, seeds 20260921 + j; B = 10,000 date-cluster draws, seed 20261024; draw b
    uses derangement b mod 20.
  - **Population:** scored snapshots where the arm is covered and every donor is covered. Donors are drawn
    within (market, local hour), so they are 13-16 too.
  - **Statistic:** Δ = ρ_c − mean_j ρ_pl,j, with its one-sided p.
- **Benjamini-Hochberg** at q = 0.10 over K = 5 (`mr_sweep.bh_adjust`).
- **P0 survivor** iff BH rejects and the lower 95% bound of Δ > 0.
- **Also reported:** ρ_c and mean ρ_pl with their intervals; the c-deranged diagnostic; the per-market Δ
  (`p0_candidate`'s own output).
- **Survivors only:**
  - C3 identity (`market_blend.w0_identity`): the w = 0 pool equals m. A miss refuses the run.
  - Then `mr_gate.gate_candidate(arm, "13-16", fit_t, score_t, c_fit, covered, p_placebo_fit=c_pl,0)`.
  - **PASS iff all four** (rule 37cb46be): mean w >= 0.05; blend R date upper < 1; blend − placebo upper < 0;
    blend − floor-only upper < 0.
  - A tradability replay follows only for a w-gate PASS, under its own clarification.

## 6. Outputs

- **Receipt:** run-env HEAD (must be the pin, clean), script sha, layout manifest sha, replay SHA256SUMS sha,
  NBH manifest sha, t3-r3 table sha, malformed replay lines, S1 coverage, and every statistic and verdict.
- **Per-date rows:** from `p0_candidate` (per arm and date: n entries, n snapshots, the six sums for c and for
  each of the 20 placebos). For survivors, also the w gate's per-date w and paired Brier.
- **Features:** a parquet of every arm's value and receipt per snapshot.
- **Execution:** run once. The S1 and P0 stages are light scripts, run directly with their shas recorded.

## 7. Disclosures

- **Dev-window use:**
  - This is a further read of the US dev window (08-01..09-29) after the parity swarm, MG-1, the MR gate
    (37cb46be) and the MR sweep (row 78).
  - t3-r3 itself was scored on these dates against the served model (parity swarm, 13-16:
    −0.0116 vs served). It failed family-wise and is freshness-fragile (EF §10q).
  - OM-HRRR is a sweep candidate on the same window.
- **Version:** dev NBH is NBM V5.0 / V5.0.14 (SCN 26-70, 2026-07-28 12Z). No arm is trained, so there is no
  train/serve version shift.
- **t3-r3 history:** Aug-Sep 2024-25 only (the IEM corpus starts 2024-04-30). There is no dev date in the
  table.
