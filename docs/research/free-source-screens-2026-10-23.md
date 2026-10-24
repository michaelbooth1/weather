# Free-source screens on the development scorecard (lane G, 2026-10-23)

**Status:** dated research record. Each section's pre-declaration was committed **before** that source
was scored; results are appended below it. Every number is **development** evidence (dates <= 2026-09-29,
already read by earlier lanes); nothing here is confirmation, edge or promotion evidence. A KEEP earns a
pre-registration on new dates (EF §5), nothing more.

- **Owns:** the pre-declared rules, fetch receipts, keep/kill verdicts and unscoreable reasons for the
  free sources screened by lane G (F1-F5 of the
  [information-gap proposal](https://github.com/michaelbooth1/weather/blob/claude/research-information-gap-20261023/docs/research/information-gap-sources-2026-10-23.md)).
- **Read when:** proposing a new free source, the MADIS sign-up, or any paid observation feed.
- **Do not use for:** the scorecard design ([dev scorecard record](dev-scorecard-2026-10-23.md)); measured
  conclusions once landed belong to the findings digest and EF.
- **Owner direction (2026-10-23, via master):** test all free sources now, dev scorecard only, F1 first;
  MADIS sign-up only after F1 shows a gain, and the owner creates that account.

## Common protocol (every source)

- **Scorer:** `python -m weather.reporting.scorecards.dev_scorecard score --layout C:\swarm\v3layout
  --from 2026-08-01 --to 2026-09-29` with the default folds (7-day, gap 1, min 7 train dates; scoring
  starts 08-15), run through `scripts\ops\workstation_heavy.ps1 -Kind weather_heavy` from this worktree.
- **Paired control.** This branch adds `--control-module` / `--control-vectors` to the scorecard: the
  control is scored on the same rows with the same crossed weights (2,000 draws, seed 20260921), so
  `model_minus_control` is the paired increment of the source over its no-source rule. Scoring a source
  only against `served` would credit it with the control's own gain (t3-r3 alone already beats served at
  13-16, EF §10q).
- **Keep/kill bar (pre-declared, owner wording made paired):** KEEP only if, for the targeted block on the
  pooled `ALL` row, the 95% crossed date x market interval of **model − served excludes zero below**
  **and** the interval of **model − control excludes zero below**. Otherwise KILL. The proposal's 5% bar
  (about −0.0012 at 13-16) and MDE80 are reported, not used to keep.
- **Power caveat:** 11 US market clusters (< 12) mean no pooled row is `powered` (EF §10j); a KILL at a
  small effect is "no increment demonstrated", not "no effect".
- **Parity:** a source counts only if a point-in-time equivalent exists at serve. Latency is recorded
  per source; an archive that arrives late is a training proxy and is scored only after degrading it to
  the live product.

## F1: high-frequency ASOS (IEM 1-minute archive), block 13-16

### Pre-declaration (committed before scoring)

- **Control `control_t3r3_metar`** = t3-r3 (EF §10q, `docs/research/model-parity-swarm-2026-10-04/t3.md`):
  R = PIT running max of routine non-COR METAR (half-up T-group F; available = valid + 10 min) on the
  station-local date; P(high = R + e) from the history pmf of e = dmax − R at local H:30 by station x
  target month x local hour; history = local dates <= 2026-07-31 (Aug and Sep of 2024 and 2025);
  complete day >= 20 routine rows; discrete Gaussian smoothing sd 1 F; cells with < 30 days are absent.
  Absent snapshots fall back to served (scorecard rule).
- **Candidate `f1_onemin_hf5c_lat10` (primary)** = the control with R replaced by the fresh running high
  R* = max(R, R_hf). R_hf = running max of the IEM 1-minute archive **degraded to the live product**:
  minutes divisible by 5 only, rounded to whole °C and back to integer F, available = valid + 10 min.
  The history pmf is of e* = dmax − R* built identically (train/serve parity), may be negative, and mass
  below R is folded onto R. A station-day without 1-minute data uses R* = R.
- **Sensitivity `f1u_onemin_m1f_lat2`** (information upper bound, not a serve candidate): every 1-minute
  row, whole F, available = valid + 2 min. Reported only; the verdict is on the primary.
- **Denver:** KBKF publishes no 1-minute archive, so Denver gets R* = R (the control) in both variants.
  KDEN is fetched for the record but is not the settlement station and is not used.
- **Targeted block:** 13-16 local. Other blocks are reported, not decided.
- **Multiplicity:** two rules (primary and sensitivity); one decision (primary).
- **Latency and parity:** the NCEI 1-minute archive arrives 18-36 h late, so **F1 is a training proxy for
  live MADIS 1-/5-minute ASOS**, whose real-time latency and distribution category are unverified. A
  KEEP would justify the owner's MADIS sign-up and a 14-day latency/fill measurement, not serving.

## F3: 12Z soundings (IEM RAOB, nearest upper-air site), block 13-16

### Pre-declaration (committed before scoring)

- **Control:** `control_t3r3_metar` (as F1).
- **Candidate `f3_sounding_cap_gap`:** T_cap = the nearest site's 12Z 850 hPa temperature (700 hPa at
  KDNR) brought dry-adiabatically to the sounding's surface pressure (a full-mixing afternoon cap), in F.
  Gap g = T_cap − R (R = PIT METAR running max) in bins (−inf, 0], (0, 4], (4, 8], (8, inf) F, fixed a
  priori. The t3-r3 pmf is taken from the (station, month, hour, bin) history cell when it has >= 30
  days, otherwise the unconditioned t3-r3 cell. The sounding is used only from valid + 2 h (14:00Z), in
  history and at serve (before 13:00 local in every US market).
- **Sites and distances** (`python -m weather.sources.free_screens.iem_raob sites`): KATL-FFC 32 km,
  KAUS-CRP 268, KORD-DVN 223, KDAL-FWD 43, KBKF-DNR 12, KHOU-LCH 206, KLAX-NKX 169, KMIA-MFL 8,
  KLGA-OKX 86, KSFO-OAK 18, KSEA-UIL 177. Far sites dilute the signal; no site is re-chosen after scoring.
- **Latency/parity:** RAOB is public within about 1-2 h of launch at no cost; the 14:00Z bound is used
  in history and at serve, so parity holds.
- **Targeted block 13-16; one rule; keep/kill bar as in the common protocol.**

## F4: per-model Open-Meteo members (captured), block 00-12

### Inventory and pre-declaration (committed before scoring)

- **Captured coverage (no download):** every captured snapshot <= 09-29 carries `open_meteo_multimodel`
  (`gfs_seamless`, `ncep_hrrr_conus`, `ncep_nam_conus`, `ncep_nbm_conus`), `open_meteo_global_models`
  (`ecmwf_ifs025`, `ecmwf_aifs025`, `ncep_aigfs025`, `gfs_graphcast025`) `day_model_highs`, and the
  GFS-ensemble day mean high (`global_ensemble`). ICON is not captured, so it is not screened (no fetch,
  per the brief). Already tested and excluded: HRRR, IFS, NBM (EF §10q). Extracted from the workstation
  replay-input copy by `weather.sources.free_screens.captured_openmeteo` inside the scorecard process.
- **Control `control_mg1`** = MG-1 verbatim (`r-t5-inc-c1`, EF §10h/§10j) from the layout's captured
  `v2_mean`, `v2_stddev`, `v2_available_at` and floor.
- **Candidates `f4_<member>`** for `gfs_seamless`, `ncep_nam_conus`, `ecmwf_aifs025`, `ncep_aigfs025`,
  `gfs_graphcast025`, `gefs_mean`: MG-1 with mu = (v2_mean + member day high) / 2 (fixed 50/50, zero
  parameters, sigma unchanged); a snapshot without the member keeps MG-1.
- **Targeted block 00-12** (the scorecard gains a `00-12` aggregate row for this; MG-1's block).
  Six rules; the keep bar applies to each, and with six looks a lone marginal KEEP is read as a lead only.
- **Latency/parity:** captured at `captured_at_utc` by production, so point in time by construction.

## F2: MRMS composite reflectivity (NOAA archive), block 13-16

### Inventory and pre-declaration (committed before scoring)

- **Local capture:** production records only the `PrecipRate_00.00` object listing; every sampled
  snapshot (25 of 732 market-day files) has `row_count 0` and "nearest MRMS extraction is not
  configured". So no value is captured for any date, and the archive is the only source.
- **Fetched** (`weather.sources.free_screens.mrms`): `MergedReflectivityQCComposite_00.50`, the newest
  object at or before each UTC :00/:30 from 16:00Z to 23:30Z, for Aug-Sep 2024, Aug-Sep 2025 and
  2026-07-31..09-29; reduced on the fly to max dBZ within 25 and 50 km of each station (raw grids are
  hashed in the receipts and not kept).
- **Candidate `f2_mrms_echo25`:** t3-r3 conditioned on an echo flag: bin 1 if the newest slot with
  valid + 5 min <= t and valid >= t − 40 min has max reflectivity >= 35 dBZ within 25 km, bin 0 if that
  slot is below 35 dBZ, no bin (unconditioned t3-r3) if no such slot. Cells as F3 (>= 30 days, else back off).
- **Control:** `control_t3r3_metar`. **Targeted block 13-16; one rule.**
- **Latency/parity:** MRMS objects reach the public bucket ~1-2 min after valid; valid + 5 min is used in
  history and at serve.

## F5: ECMWF ENS open data and DWD MOSMIX (incl. the EU cities), forward only

Not scored, by the brief and by measurement. Parsers built on small pulls (`weather.sources.free_screens.forward_only`).

- **DWD MOSMIX_L** (15 stations: 11 US plus EGLC, LFPB, EDDM, LEMD; ids from S0(e)): one latest KMZ each
  (9.9-19.1 KB), issue 2026-10-23T21Z, 247 hourly steps; TTT parses for all; TX (12 h max) is present
  only on the 06/18 UTC steps (20-41 values per file). **Retention:** the single-station directory keeps
  the last 8 runs (about 2 days, 6-hourly), so no development date can be reconstructed. Scoring needs
  forward shadow capture (owner decision 4 of the proposal; master schedules it under the roll verdict).
- **ECMWF ENS open data.** The brief's premise (short public retention) is **wrong for the AWS mirror**:
  `ecmwf-forecasts` (public, no account) holds `enfo` 0.25° runs at least back to 2024-08-15 (listing
  checked for 20240815 and 20260901), with a JSON `.index` per step that allows byte-range pulls of a
  single member field (2 m temperature member: 0.66 MB; one step's index: 1.3 MB, 5,559 fields, 51 `2t`
  members). **Blocker: packing.** The 2t members use GRIB2 data representation **5.42 (CCSDS/AEC)**; this
  environment has no decoder (no eccodes, cfgrib or libaec, and no requirements change is allowed), so
  values cannot be read here. No `mx2t` is in the step's parameter list, so a daily max would be built
  from 3/6-hourly 2t. A historical ENS screen is therefore feasible in principle (decoder plus about
  51 members x ~8 steps x ~0.66 MB ≈ 270 MB per run per day), but it needs an owner decision on a
  decoder dependency; it was not forced.
- **Other EU free sources** (Met Office DataHub, Météo-France 6-minute, DWD 10-minute, AEMET) need
  accounts or keys or were out of this lane's list; not touched.
