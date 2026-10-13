# A-Soundings report (model-parity swarm v2, development data)

**Status: COMPLETE.** 12Z (and 00Z/18Z) RAOB profiles for 17 candidate upper-air sites near the 11 markets,
2026-05-01..2026-09-29 UTC, from the IEM RAOB archive. 11.8 MB on disk (< 100 MB). No scoring done (acquirer).
Data: `C:\swarm\data\soundings\` with `MANIFEST.json` (93 files, sha256, URL per file, request time).

## Key findings for T11 (read before using)
1. **Several offices do not launch at 12Z.** KCRP, KLCH, KDVN, KGJT, KLBF launch 00Z + 18Z for almost the whole window;
   KMFL mixes 12Z (83/152 days) and 18Z. So a "12Z from ~13Z" rule has primary-site coverage near 0 for AUS, HOU,
   BKF and ~55% for MIA. The 18Z sounding (basis 19Z = early afternoon local) is the only same-day sounding there.
   The previous evening's 00Z sounding (UTC date D 00Z = local evening D-1, basis 01Z) exists nearly every day for all.
2. **No Denver sounding.** 72469 (DNR) is absent from IEM after 2022-07-08 and UWyo returns 404 for 2026. BKF
   proxies KGJT (328 km, west of the Divide) and KLBF (386 km) are weak; recommend T11 exclude BKF or flag it.
3. **Coastal west caveat.** At KNKX/KVBG/KOAK the 850 hPa air sits above the marine inversion (median T850 ~19-21 C
   vs surface 14-18 C), so dry-adiabatic 850->surface or max-theta bounds are far above coastal highs (LAX/SFO);
   they are loose upper bounds, not mixed-layer predictions, at marine-layer sites.
4. KEDW (Edwards AFB, 120 km from LAX) launches irregularly (~30 soundings, odd hours, few levels): tertiary only.

## Market -> RAOB mapping (distance km; see MANIFEST market_to_raob)
ATL: KFFC 29, KBMX 223 | AUS: KCRP 269, KFWD 304 | BKF: KGJT 328, KLBF 386 | DAL: KFWD 16 | HOU: KLCH 208, KCRP 300 |
LAX: KNKX 170, KVBG 213, KEDW 120 | LGA: KOKX 86 | MIA: KMFL (IEM coords give 72 km; site is ~10 km in reality) |
ORD: KILX 209, KDVN 216 | SEA: KUIL 173, KSLE 286 | SFO: KOAK 20.

## Coverage, market-days with a sounding (2026-07-25..09-29, 67 days; full window 152 days in coverage_summary.csv)
| market | primary 12Z | primary 12Z or 18Z | any cand 12Z | any cand 12Z or 18Z | any 00Z prior evening |
|---|---|---|---|---|---|
| KATL | 67 | 67 | 67 | 67 | 67 |
| KAUS | 0 | 54 | 66 (via KFWD) | 67 | 67 |
| KBKF | 0 | 67 (KGJT 18Z) | 0 | 67 | 67 |
| KDAL | 66 | 66 | 66 | 66 | 64 |
| KHOU | 2 | 65 | 2 | 67 | 67 |
| KLAX | 60 | 61 | 66 | 66 | 67 |
| KLGA | 67 | 67 | 67 | 67 | 67 |
| KMIA | 39 | 61 | 39 | 61 | 62 |
| KORD | 65 | 65 | 65 | 67 | 67 |
| KSEA | 66 | 66 | 66 | 66 | 66 |
| KSFO | 65 | 65 | 65 | 65 | 66 |
Per station-day flags (00Z/12Z/18Z per candidate): `coverage_market_day.csv`.

## Point-in-time statement (rule 1)
- **Stated basis, not measured.** IEM provides no per-object receipt timestamp. `available_utc_basis` = nominal valid
  + 60 min (12Z -> 13:00Z, 18Z -> 19:00Z, 00Z -> 01:00Z). NWS launches ~1 h before nominal; TEMP mandatory parts
  normally go out within ~60-90 min of launch. Refuters should re-run at +2 h (14Z / 20Z / 02Z).
- IEM profiles may include post-receipt reprocessing (BUFR high-resolution vs TEMP); treat as near-real-time-equivalent.
- Window guard: asserted 0 rows dated >= 2026-09-30 UTC (fetch per month ends 2026-09-29T23:59Z; re-asserted in processing).
- Soundings are observations, not settlement values; no market data touched.

## Files
- `raw/<RAOB>_<YYYYMM>.csv.gz` (85): IEM CSV `station,validUTC,levelcode,pressure_mb,height_m,tmpc,dwpc,drct,speed_kts,...` ('M' = missing).
- `soundings_summary.csv.gz`: one row per sounding (4,718 rows incl. specials): surface p/z/T/Td, T and z at
  925/850/700/500, `t850_adiab_sfc_c/f`, `t925_adiab_sfc_c/f` (dry-adiabatic descent to surface pressure),
  `max_theta_low300_at_sfc_c/f` (max potential temperature in lowest 300 hPa at surface pressure), `available_utc_basis`.
  Note "surface" is the RAOB site surface, not the market station (elevation differs; BKF/GJT especially).
- `coverage_market_day.csv`, `coverage_summary.csv`, `RAOB_network.geojson`, `fetch_log.jsonl`, scripts.
- Code copies: `C:\pt\swarm\tools\research\model_parity\a-soundings_{fetch_raob,process_raob,manifest_raob}.py`.

## Operations
85 requests, single connection, 3 s spacing, 0 retries, 0 failures; background fetch PID 22452 ran 04:23-04:30Z and
exited (no processes left). UWyo probed with 8 requests (Denver check). Disk used 12 MB.
