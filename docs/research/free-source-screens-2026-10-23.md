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

## Summary (2026-10-24)

| Screen | Block | Increment over control [95% crossed] | vs served [95%] | Verdict |
| --- | --- | --- | --- | --- |
| F1 1-minute ASOS (degraded, primary) | 13-16 | +0.0044 [+0.0017, +0.0076] vs t3-r3 | −0.0066 [−0.0138, −0.0000] | **KILL (harm)**; MADIS sign-up not triggered |
| F1u 1-minute ASOS (raw, sensitivity) | 13-16 | +0.0029 [+0.0004, +0.0057] | −0.0081 [−0.0156, −0.0015] | harm (reported only) |
| F2 MRMS echo flag | 13-16 | −0.0005 [−0.0010, −0.0001] vs t3-r3 | −0.0115 [−0.0192, −0.0046] | **KEEP (dev lead; below the 5% bar; needs a capture change)** |
| F3 12Z sounding cap | 13-16 | −0.0001 [−0.0003, +0.0000] vs t3-r3 | −0.0111 [−0.0188, −0.0043] | **KILL (null)** |
| F4 gfs_seamless / NAM / AIGFS | 00-12 | +0.0008 / +0.0007 / +0.0003, all spanning 0, vs MG-1 | −0.0145 / −0.0146 / −0.0150 | **KILL (null)** |
| F4 GEFS mean | 00-12 | +0.0054 [+0.0016, +0.0100] vs MG-1 | −0.0099 [−0.0185, −0.0011] | **KILL (harm)** |
| F4 AIFS, GraphCast | 00-12 | — | — | not scored: never captured |
| G2-a ECMWF ENS mean (lane G2) | 00-12 | −0.0000 [−0.0033, +0.0031] vs MG-1 | −0.0154 [−0.0230, −0.0078] | **KILL (null)** |
| G2-b ECMWF ENS gap (lane G2) | 13-16 | −0.0002 [−0.0005, +0.0001] vs t3-r3 | −0.0112 [−0.0189, −0.0043] | **KILL (null)** |
| L4 multi-model blend | 07-12 | −0.0002 [−0.0045, +0.0047] vs MG-1 | −0.0141 [−0.0211, −0.0068] | **KILL (null)**; h15-23 gain over MG-1 parked |
| DWD MOSMIX | — | — | — | not scored: the open server keeps ~2 days |
| L6 upstream ASOS ring (vs own-obs twin) | 07-12 | −0.0005 [−0.0012, +0.0003] vs twin; −0.0041 [−0.0069, −0.0015] vs MG-1 | −0.0180 [−0.0245, −0.0114] | **KILL (upstream not shown)**; own-obs stack −0.0036 vs MG-1 is a separate dev lead |

Served baseline for context (lane C, scorecard hash `3557f797…`): pooled 13-16 R = 1.862 [1.557, 2.345],
served − market = +0.0244 [+0.0181, +0.0316].

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

### F1 result (scored 2026-10-24; score `6b0179912f9b…`, `data/research/free_sources/scores/f1/`)

Population: 43 dates 2026-08-15..09-29, 11 markets, 473 market-days, 83,801 snapshots; candidate and
control cover the same 79,146 snapshots (4,392 absent, 263 missing floor: served fallback). Pooled `ALL`,
crossed date x market 95% intervals, unpowered (11 market clusters):

| Block | F1 − served | F1 − control (t3-r3) | MDE80 | control − served |
| --- | --- | --- | --- | --- |
| **13-16 (decided)** | −0.0066 [−0.0138, −0.0000] | **+0.0044 [+0.0017, +0.0076]** | 0.0042 | −0.0110 [−0.0188, −0.0041] |
| 00-12 | −0.0026 [−0.0109, +0.0051] | +0.0004 [−0.0004, +0.0012] | 0.0012 | −0.0029 [−0.0114, +0.0049] |
| 17-23 | −0.0128 [−0.0245, −0.0034] | +0.0096 [+0.0056, +0.0141] | 0.0062 | −0.0224 [−0.0329, −0.0139] |
| all | −0.0062 [−0.0145, +0.0004] | +0.0037 [+0.0021, +0.0056] | 0.0025 | −0.0099 [−0.0181, −0.0033] |

Per market at 13-16, F1 − control: 0 of 10 negative (Denver identical by construction); worst Chicago
+0.0091, San Francisco +0.0085, Austin +0.0063.

**Verdict: KILL (harm).** The fresher, degraded 1-minute running high makes the 13-16 remaining-rise pmf
worse than the hourly-METAR control, with the interval excluding zero on the harmful side; F1 − served
only reaches its bar because the control's own gain (−0.0110, reproducing t3-r3's −0.0116 of EF §10q)
carries it. The control row confirms the scorecard reproduces t3-r3. Reading (not a measured cause):
the settlement high is METAR-based, and a 1-minute (or whole-°C 5-minute) running max is a different,
noisier quantity that often sits above the eventual METAR maximum, so replacing R with it moves mass
off the settling value; the 17-23 harm points the same way. Per the owner's rule, **MADIS sign-up is
not triggered**, and the proposal's kill criterion for every paid observation feed (P1, Synoptic) is met.

**Sensitivity F1u** (every 1-minute row, whole F, valid + 2 min; score `f9633f12518f…`): 13-16 F1u − control
+0.0029 [+0.0004, +0.0057] (MDE80 0.0038), 17-23 +0.0077 [+0.0042, +0.0118], all +0.0029 [+0.0015, +0.0044];
0 of 10 markets negative at 13-16. Even the undegraded, near-real-time archive harms, so the kill is not an
artefact of the whole-°C / 5-minute / 10-minute degradation: fresher station temperature does not help this
rule.

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

### F3 result (scored 2026-10-24; score `52f20094cdfb…`, `data/research/free_sources/scores/f3/`)

Same population and coverage as F1. The history table gained 144 conditioned cells (650 vs the control's
506; Denver none, KDNR being empty at IEM), so most snapshots back off to the unconditioned t3-r3 cell.

| Block | F3 − served | F3 − control (t3-r3) | MDE80 |
| --- | --- | --- | --- |
| **13-16 (decided)** | −0.0111 [−0.0188, −0.0043] | **−0.0001 [−0.0003, +0.0000]** | 0.0002 |
| 17-23 | −0.0225 [−0.0330, −0.0139] | −0.0000 [−0.0000, +0.0000] | 0.0000 |
| all | −0.0100 [−0.0181, −0.0033] | −0.0000 [−0.0001, +0.0000] | 0.0001 |

Per market at 13-16: Atlanta −0.0006 [−0.0011, −0.0002] and Seattle −0.0004 [−0.0007, −0.0001] exclude
zero (date-clustered), Los Angeles +0.0002 [+0.0001, +0.0003] harms, six markets are exactly 0.

**Verdict: KILL (no increment demonstrated).** The pooled increment interval includes zero, and its size is
about a tenth of the 5% bar (−0.0012), so even a true effect of this size would not matter. The 2-bin
sounding cap barely changes the pmf where it applies; a richer conditioning would be a new rule on new dates.

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

### F4 result (scored 2026-10-24; `data/research/free_sources/scores/f4_<member>/`)

Members extracted from 732 captured market-day files (122,711 snapshots; `members.parquet` sha256
`bdd432ea…`). MG-1 and every F4 candidate cover the same 83,306 scored snapshots. Pooled `ALL`, 00-12
(MG-1 − served = −0.0153 [−0.0234, −0.0083], reproducing the MG-1 lead of EF §10j on this population):

| Member | Fill | F4 − served (00-12) | F4 − MG-1 (00-12) | MDE80 | markets < 0 | F4 − MG-1 (13-16) | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `gfs_seamless` | 0.91 | −0.0145 [−0.0227, −0.0064] | +0.0008 [−0.0032, +0.0055] | 0.0063 | 6/11 | −0.0014 [−0.0065, +0.0043] | KILL (null) |
| `ncep_nam_conus` | 0.91 | −0.0146 [−0.0214, −0.0082] | +0.0007 [−0.0037, +0.0052] | 0.0063 | 4/11 | −0.0045 [−0.0095, +0.0004] | KILL (null) |
| `ncep_aigfs025` | 0.999 | −0.0150 [−0.0234, −0.0064] | +0.0003 [−0.0046, +0.0056] | 0.0075 | 4/11 | −0.0007 [−0.0082, +0.0078] | KILL (null) |
| `gefs_mean` | 0.999 | −0.0099 [−0.0185, −0.0011] | **+0.0054 [+0.0016, +0.0100]** | 0.0060 | 1/11 | +0.0068 [−0.0003, +0.0143] | KILL (harm) |
| `ecmwf_aifs025` | **0.000** | — | identical to MG-1 | — | — | — | NOT SCORED: never captured (always null) |
| `gfs_graphcast025` | **0.000** | — | identical to MG-1 | — | — | — | NOT SCORED: never captured (always null) |

**Verdict: KILL for all four scoreable members.** No member's increment over MG-1 excludes zero on the
improving side at 00-12; the GEFS mean harms. The MDE80 (about 0.006) is five times the 5% bar, so the
nulls are "no increment demonstrated", consistent with the IFS result (EF §10q). The NAM 13-16 point
(−0.0045, interval to +0.0004) is outside the decided block and is not a lead. AIFS and GraphCast are
always null in the captured `open_meteo_global_models` payload for every scored snapshot, so they cannot
be screened from capture; per the brief no download was made.

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

### F2 result (scored 2026-10-24; score `511bd35de76e…`, `data/research/free_sources/scores/f2/`)

Same population and coverage as F1. Table: 681 cells (175 echo-conditioned beyond the control's 506).

| Block | F2 − served | F2 − control (t3-r3) | MDE80 | control − served |
| --- | --- | --- | --- | --- |
| **13-16 (decided)** | **−0.0115 [−0.0192, −0.0046]** | **−0.0005 [−0.0010, −0.0001]** | 0.0006 | −0.0110 [−0.0188, −0.0041] |
| 10-12 | −0.0047 [−0.0114, +0.0020] | −0.0001 [−0.0003, +0.0000] | 0.0003 | |
| 17-23 | −0.0224 [−0.0329, −0.0139] | +0.0000 [−0.0000, +0.0000] | 0.0000 | |
| 00-16 | −0.0050 [−0.0129, +0.0018] | −0.0001 [−0.0003, −0.0000] | 0.0002 | |
| all | −0.0100 [−0.0182, −0.0035] | −0.0001 [−0.0002, −0.0000] | 0.0001 | |

Per market at 13-16, F2 − control: 7 of 11 negative; the convective markets carry it — Houston −0.0021
[−0.0033, −0.0010], Miami −0.0011 [−0.0017, −0.0006], Austin −0.0009 [−0.0013, −0.0004], Atlanta −0.0008
[−0.0012, −0.0004]; Los Angeles and San Francisco exactly 0 (no echo cells); Chicago +0.0002 and NYC
+0.0001 (intervals include 0).

**Verdict: KEEP (development lead only).** Both pre-declared intervals exclude zero on the improving side.
Caveats that bound what this means: the effect (−0.0005) is under half the 5% bar (about −0.0012), so it
closes roughly 2% of the 13-16 gap; the upper end (−0.0001) barely clears zero and this is one of about ten
looks in this record (F1, F1u, F2, F3, six F4 members) with no family-wise correction; 11 market clusters
leave it unpowered; and the dates were read before. **Parity:** production captures only the MRMS object
listing, so serving this needs a capture change (nearest-pixel/disk extraction of composite reflectivity,
valid + 5 min), which is master's and the roll verdict's call. Next step if pursued: pre-register
`f2_mrms_echo25` unchanged, with t3-r3 as control, on new dates (EF §5).

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
  decoder dependency; it was not forced. **Superseded 2026-10-24:** the owner approved a research-venv decoder and the fetch, and lane G2 scored ENS (§ G2 below: both rules KILL).
- **Other EU free sources** (Met Office DataHub, Météo-France 6-minute, DWD 10-minute, AEMET) need
  accounts or keys or were out of this lane's list; not touched.

## G2: ECMWF ENS open data (2 m temperature members), blocks 00-12 and 13-16

### Pre-declaration (committed before scoring; owner approval 2026-10-23 "Yes, both")

- **Decoder:** eccodes 2.50.0 in a separate research venv `C:\venvs\research-ecmwf` (Python 3.11.9); the
  project venv, `requirements.txt` and `pyproject.toml` are untouched. `weather.sources.free_screens.ecmwf_ens`
  imports eccodes lazily and runs only in that venv; it writes `data\research\free_sources\ecmwf_ens\points.parquet`,
  which is all the scorecard (project venv, through the wrapper) reads. eccodes tests use `pytest.importorskip`.
- **Data:** 00Z ENS runs, all 51 `2t` members (control + 50), steps 18/21/24 h (target = run date) and
  42/45/48 h (target = run date + 1), bilinear at the 11 stations; runs 2024-08-15..09-30, 2025-07-31..09-30
  and 2026-07-30..09-29 (only the months the rules use; the history tables use Aug-Sep). Raw ranges are
  hashed and discarded. Mirror: the public Google Cloud copy of ECMWF open data (`ecmwf-open-data`), because the
  AWS copy answered every range request with S3 `SlowDown`. Same files, CC BY 4.0, no account.
- **ENS value at a snapshot:** ens_mean = mean over members of each member's max of the three target-date
  steps (18, 21, 00 UTC), in F. It comes from the newest 00Z run available at run + 9 h (release is about
  08Z) that carries the target date. The three-step max under-reads the true maximum, so each rule
  removes that bias without labels or reads it through a history table.
- **G2-a `g2_ens_mg1_half`, block 00-12, control MG-1:** mu = (v2_mean + ens_mean − b_station) / 2,
  sigma = max(v2_stddev, 1); b_station = median of (ens_mean − v2_mean) over the fold's training snapshots
  (inputs only, walk-forward). Without ENS or b, MG-1 is kept.
- **G2-b `g2_ens_gap_rise`, block 13-16, control t3-r3:** t3-r3 conditioned on g = ens_mean − R in bins
  (−inf, −4], (−4, 0], (0, 4], (4, inf) F; cells as F3 (>= 30 history days, else the unconditioned cell).
- **Keep/kill:** the common protocol, applied to each rule on its own block. Two rules.
- **Parity/latency:** the open-data 00Z ENS is public at about 08Z; serving it would need a forward
  capture plus eccodes on the capture host (a separate owner decision).

### G2-a result (scored 2026-10-24; score `1d72ea4b36f8…`, `data/research/free_sources/scores/g2a/`)

Coverage is identical to MG-1 (83,306 snapshots). Pooled `ALL`:

| Block | G2-a − served | G2-a − MG-1 | MDE80 |
| --- | --- | --- | --- |
| **00-12 (decided)** | −0.0154 [−0.0230, −0.0078] | **−0.0000 [−0.0033, +0.0031]** | 0.0047 |
| 06-09 | −0.0171 [−0.0252, −0.0091] | −0.0008 [−0.0044, +0.0027] | 0.0051 |
| 10-12 | −0.0123 [−0.0193, −0.0052] | −0.0008 [−0.0044, +0.0026] | 0.0050 |
| 13-16 | −0.0029 [−0.0117, +0.0051] | −0.0019 [−0.0057, +0.0019] | 0.0055 |

Per market at 00-12, G2-a − MG-1: 6 of 11 negative. Dallas −0.0096 [−0.0176, −0.0022] and Austin −0.0048
are negative; Los Angeles +0.0062 and Atlanta +0.0047 harm (date-clustered intervals).

**Verdict G2-a: KILL (no increment demonstrated).** The interval is centred on zero, and its MDE80 (about 0.005)
is four times the 5% bar.

### G2-b result (scored 2026-10-24; score `60047a9deb4d…`, `data/research/free_sources/scores/g2b/`)

Same population and coverage as F1; 891 table cells (385 ENS-gap-conditioned beyond the control's 506).
Pooled `ALL`: **13-16 (decided) G2-b − t3-r3 = −0.0002 [−0.0005, +0.0001]** (MDE80 0.0004), G2-b − served
−0.0112 [−0.0189, −0.0043]; 10-12 −0.0006 [−0.0013, +0.0000]; 17-23 −0.0000. Per market at 13-16, 8 of 11 are
negative, all small (Chicago −0.0003, Seattle −0.0005, Miami −0.0003 exclude 0; Houston +0.0004 harms).

**Verdict G2-b: KILL (no increment demonstrated).** The interval spans zero, and its size is a sixth of the 5% bar.

## L4: multi-model forecast blend (pre-registration sha256 `96dee78c7bfe8e350905c19048824ddf25729fcf3bc829bde066f16ad346a3b0`)

Rule, members and bar: [the frozen pre-registration](forecast-blend-l4-preregistration-2026-10-24.md),
committed in `144a1f582` before scoring. Data: Open-Meteo Previous Runs day-1 highs, 33 requests
(11 stations x GFS/IFS/ICON, 2026-07-30..09-29), 1.19 MB, 2,046 station-model-days, full fill
(`day1_highs.parquet` sha256 `62d68e3c…`). Score `d019d6b1fde6…` (`--hourly`), run through the W2 slot
wrapper on a local, unpushed, detached merge of `1a16c6ed3`. 264 station x hour weight cells; coverage is
identical to MG-1 (83,306 snapshots).

| Rows (pooled `ALL`) | L4 − served [crossed] | L4 − MG-1 [crossed] | MDE80 | L4 − MG-1 [date-clustered] |
| --- | --- | --- | --- | --- |
| **07-12 (headline, decided)** | −0.0141 [−0.0211, −0.0068] | **−0.0002 [−0.0045, +0.0047]** | 0.0064 | −0.0002 [−0.0031, +0.0025] |
| h07 / h08 / h09 | −0.0179 / −0.0172 / −0.0148 | −0.0005 / −0.0004 / −0.0004 (all span 0) | 0.0063 | all span 0 |
| h10 / h11 / h12 | −0.0133 / −0.0111 / −0.0100 | −0.0002 / +0.0006 / −0.0003 (all span 0) | 0.0065-0.0071 | all span 0 |
| 00-12 | −0.0153 [−0.0229, −0.0077] | +0.0000 [−0.0040, +0.0046] | 0.0060 | +0.0000 [−0.0025, +0.0025] |
| 13-16 | −0.0070 [−0.0149, +0.0005] | −0.0059 [−0.0103, −0.0014] | 0.0063 | −0.0059 [−0.0088, −0.0033] |
| 17-23 | −0.0061 [−0.0176, +0.0045] | −0.0129 [−0.0179, −0.0077] | 0.0073 | −0.0129 [−0.0157, −0.0102] |

h00-h06 all span 0 vs MG-1; h15-h23 are −0.008 to −0.013 vs MG-1 with intervals excluding 0. Per market at
07-12, L4 − MG-1: 5 of 11 negative (NYC −0.0075, Austin −0.0061, Atlanta −0.0030), San Francisco +0.0088.

**Verdict L4: KILL at the 07-12 headline (no increment over MG-1; interval centred on 0, MDE80 five times
the 5% bar).** The afternoon/evening "gain" over MG-1 is not a lead: it is outside the decided block, and it
mostly undoes MG-1's known afternoon harm (EF §10p; MG-1 − served is +0.0068 at 17-23 here). L4 − served
does not exclude zero at 13-16 or 17-23, and t3-r3 already does far better there (−0.0110 / −0.0224 vs served).

## L6: upstream and nearby ASOS observations at 07-12 (pre-registration sha256 `6687c8dfb49b0650d27bbf23164ba102de5d838ada79917df50075c61653921a`)

Rule, data, features, model and bar: [the frozen pre-registration](upstream-obs-l6-preregistration-2026-10-24.md)
(byte-identical copy of `C:\t\l6\rule.md`), committed before any validation metric or score. Branch
`claude/upstream-obs-screen-20261024`. Code: `weather.sources.free_screens.iem_upstream` (fetch, selection,
build), `weather.calibration.upstream_obs_screen` (PIT features, LOYO, nowcasts),
`free_source_candidates.l6_stack` (candidate `l6_upstream_stack`, twin `l6_own_stack`). Prior art this differs
from: T13 (EF §10q) used the closest <= 6 stations within 50 km, tercile tilts of served, and May-Jul 2026
history only; L6 uses a 50-150 km ring with flow-upwind weighting and advection, 2021-2025 history, and is
scored as an increment over MG-1 and over its own-observation twin.

### L6 result (scored 2026-10-25; scores under `data/research/upstream_obs/scores/`)

Inputs: `obs.parquet` `37d97195…`, `nowcasts.parquet` `d2453d0d…` (28,137 snapshots at 07-12; serve models fitted
on 19,693 Aug-Sep 2021-2025 history rows). Run through the W2 slot wrapper on a local, unpushed, detached merge of
`1a16c6ed3`. Coverage identical to MG-1 (83,306 snapshots; 495 missing floor). Scores: candidate vs MG-1
`9be56d93…`, candidate vs twin `e3d9d8b8…`, twin vs MG-1 `d6971121…`.

**History validation (blocked leave-one-year-out, reported only).** Adding upstream features improves the
observation-only nowcast of the day's high in history: Aug-Sep 07-12 RMSE 2.852 → 2.722 F, MSE up − own −0.72
[−0.91, −0.54] (date-clustered), every hour h07-h12, 5/5 years, 11/11 stations; Oct-Dec 3.121 → 2.918, −1.22
[−1.40, −1.06]. Upstream information about the high is real; the question is whether NBM already has it.

Pooled `ALL`, crossed date x market 95% (date-clustered in the last column):

| Rows | cand − served | **cand − MG-1** | **cand − twin (upstream's own increment)** | MDE80 (vs twin) | cand − twin [date-clustered] | twin − MG-1 |
| --- | --- | --- | --- | --- | --- | --- |
| **07-12 (decided)** | −0.0180 [−0.0245, −0.0114] | −0.0041 [−0.0069, −0.0015] | **−0.0005 [−0.0012, +0.0003]** | 0.0011 | −0.0005 [−0.0008, −0.0001] | −0.0036 [−0.0065, −0.0009] |
| h07 | −0.0196 | −0.0021 [−0.0049, +0.0008] | −0.0004 [−0.0015, +0.0005] | 0.0014 | −0.0004 [−0.0009, +0.0000] | −0.0017 [−0.0045, +0.0012] |
| h08 | −0.0194 | −0.0026 [−0.0057, +0.0004] | −0.0002 [−0.0012, +0.0008] | 0.0014 | −0.0002 [−0.0007, +0.0003] | −0.0024 [−0.0054, +0.0004] |
| h09 | −0.0176 | −0.0032 [−0.0061, −0.0004] | −0.0005 [−0.0014, +0.0004] | 0.0013 | −0.0005 [−0.0010, −0.0001] | −0.0027 [−0.0057, +0.0004] |
| h10 | −0.0173 | −0.0042 [−0.0072, −0.0011] | −0.0002 [−0.0012, +0.0007] | 0.0013 | −0.0002 [−0.0008, +0.0003] | −0.0039 [−0.0072, −0.0008] |
| h11 | −0.0178 | −0.0061 [−0.0093, −0.0030] | −0.0007 [−0.0019, +0.0006] | 0.0018 | −0.0007 [−0.0013, −0.0000] | −0.0054 [−0.0088, −0.0022] |
| h12 | −0.0163 | −0.0066 [−0.0103, −0.0032] | −0.0008 [−0.0020, +0.0003] | 0.0016 | −0.0008 [−0.0014, −0.0002] | −0.0058 [−0.0096, −0.0023] |

MG-1 − served at 07-12 is −0.0139 [−0.0212, −0.0072]. Per market at 07-12, cand − MG-1 is negative in 11/11
(Austin −0.0085, Atlanta −0.0072, San Francisco −0.0067 exclude 0); cand − twin is negative in 8/11, Dallas
−0.0019 and Los Angeles −0.0016 excluding 0, Atlanta +0.0014 the worst.

**Verdict L6: KILL for upstream (pre-declared condition 3 fails).** Candidate − served and candidate − MG-1
exclude zero, but the candidate − twin interval includes zero: the upstream ring adds about −0.0005 over the
same stack built on the station's own observations (about 12% of the candidate's gain over MG-1), below the
MDE80. The date-clustered interval excludes zero and 8/11 markets lean the right way, so this is "small, not
demonstrated", consistent with T13 (−0.0005 to −0.0007 at 13-16). The history skill of upstream features does
not carry over: NBM v2 already carries the synoptic information that the ring adds to an observation-only nowcast.

**Separate development lead (reported per the rule, not decided here): the own-observation stack.** Twin −
MG-1 at 07-12 is −0.0036 [−0.0065, −0.0009] crossed, 10/11 markets negative, growing from h07 (−0.0017) to h12
(−0.0058). Caveats: the per-hour intercept also absorbs any pooled NBM bias, so part of it may be bias
correction rather than observation information (not separated by these runs); it is a fitted rule on dates read
before; and its h10-h12 growth overlaps the remaining-rise family (t3-r3, EF §10q). It earns a pre-registration
on new dates, with an intercept-only twin as the attribution control, nothing more.

## Fetch receipts (all under `data/research/free_sources/<source>/`, sha256 per file in `receipts.jsonl`)

| Source | Requests | Bytes | Rows | Span | Notes |
| --- | --- | --- | --- | --- | --- |
| `iem_onemin` (IEM asos1min, 11 US + KDEN) | 396 monthly | 503.9 MB | 11,658,245 one-minute rows (`onemin.parquet` sha256 `e8b411d3…`) | 2024-01-01T00Z .. local midnight ending 2026-09-29 per station | KBKF: none (military, no archive). Empty months: KATL 2025-05/06, KORD 2025-04/05 and 2025-08..2026-01 (Chicago history is 2024 only), KLGA 2024-12, KSFO 2024-12/2025-01, KSEA 2025-06, KDEN 2025-05. Minute fill ~55-85%. |
| `iem_raob` (IEM raob.py, 11 nearest sites) | 363 monthly | 255.5 MB | 3,379,630 levels, 19,405 soundings (`levels.parquet` sha256 `a93a9cd7…`) | 2024-01-01 .. 2026-09-29T12Z | **KDNR returns nothing at IEM** (ids DNR, KDNR, 72469 all empty), so Denver has no sounding and keeps the control in F3. |
| `mrms_refl` (NOAA `noaa-mrms-pds`, composite reflectivity) | 183 day listings + 2,928 objects | 4,137.8 MB downloaded, not kept | 32,208 station-slot rows (`station_refl.parquet` sha256 `3446d1a6…`) | Aug-Sep 2024, Aug-Sep 2025, 2026-07-31..09-29; 16:00Z-23:30Z half-hourly | 0 decode errors; raw grids hashed then discarded. |
| `upstream_obs` (IEM asos.py, lane L6; under `data/research/upstream_obs/`) | 672 (11 market + 101 ring stations x 6 windows) + 27 network listings | 569.1 MB | 4,203,170 reports (`obs.parquet` sha256 `37d97195…`; `selection.json` `a23f4cba…`) | Aug-Dec 2021-2025 and 2026-07-30 .. local midnight ending 2026-09-29 | 0 non-200. Empty windows: JZP 2025 and 2026, GLE 2024-2025, GVW 2021, OKH 2021-2024, NEL/IMM/2IS 2026 (Miami's dev ring is LNA and MTH only). Morning prevailing resultant winds are weak (0.8-5.6 kt), so the dynamic flow weighting carries the upwind signal. |
| `dwd_mosmix` | 15 KMZ + 1 listing | 0.2 MB | 247 steps x 15 stations | latest run only (2026-10-23T21Z) | retention ~2 days |
| `ecmwf_ens` (AWS `ecmwf-forecasts`) | 1 index + 1 range | 2.0 MB | 5,559 index fields, 1 member field | run 2024-08-15 00Z, step 24 h | CCSDS (5.42) packing; not decodable here |
| `captured_openmeteo` | no download | — | built in the scorecard process from the replay-input copy | captured 2026-07-31..09-29 | see F4 |
