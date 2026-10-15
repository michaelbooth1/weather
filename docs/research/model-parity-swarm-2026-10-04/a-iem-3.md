# A-IEM-3 neighbour ASOS/AWOS METAR: COMPLETE (development)

Status: COMPLETE. Nothing was scored (acquisition only), so there is no HARNESS_SHA256. No STOP condition was hit. Fetch window 00:52-00:57 local (2026-10-04). Fetch PID 53988 has exited, and no processes are left running.

## What was acquired
- Neighbours: haversine distance <= 50 km from the market station's coordinates in `C:\swarm\stations.json`. Candidates came from the GA/TX/CO/CA/NY/FL/IL/WA `_ASOS` networks plus the adjacent NJ/CT/IN/WI `_ASOS` networks. A 50 km circle reaches NJ from LGA. AWOS sites are part of these networks; `is_awos` is recorded in selection.json. The station's archive had to overlap the window, the market station itself was excluded, and only the **closest 6** were kept.
- Selected (distance in km):
  - KATL: FTY 18.2, HMP 28.6, PDK 30.2, MGE 32.5, FFC 32.7, RYY 45.0 (8 within 50 km)
  - KAUS: ATT 17.2, EDC 25.9, HYI 36.8, RYW 44.4, T74 48.9 (5 within 50 km)
  - KBKF: DEN 16.7, APA 16.9, CFO 20.5, BJC 38.8, EIK 42.6 (5 within 50 km)
  - KDAL: ADS 13.6, DFW 18.3, RBD 18.7, GPM 24.6, GKY 30.5, HQZ 32.0 (12 within 50 km)
  - KHOU: EFD 12.4, LVJ 13.8, MCJ 13.8, T41 21.4, AXH 23.8, SGR 36.2 (7 within 50 km)
  - KLAX: HHR 5.0, SMO 10.8, TOA 15.6, LGB 26.2, BUR 29.3, VNY 31.6 (11 within 50 km)
  - KLGA: NYC 7.5, JRB 13.9, TEB 17.3, JFK 18.6, EWR 26.6, HPN 35.1 (10 within 50 km)
  - KMIA: OPF 14.0, TMB 20.0, HWO 24.7, HST 34.0, FLL 35.8, FXE 48.1 (6 within 50 km)
  - KORD: 06C 14.8, PWK 18.0, MDW 24.4, DPA 26.9, LOT 41.5 (5 within 50 km; LOT is the NWS office site)
  - KSEA: RNT 9.2, BFI 9.6, TIW 27.9, PWT 34.2, TCM 36.3, PLU 38.0 (7 within 50 km)
  - KSFO: HAF 16.1, SQL 16.3, OAK 16.6, HWD 22.8, PAO 28.9, NUQ 37.3 (8 within 50 km)
- Requests: 126 to IEM asos.py (each of the 63 neighbours x routine/SPECI) plus 12 network geojson calls. One connection, at least 2 s between requests, no throttling seen.
- Output in `C:\swarm\data\iem\neighbours\` (about 20 MB):
  - `neighbours_metar.parquet`: 362,881 rows. Columns: market_station, neighbour_sid, neighbour_network, dist_km, valid_utc, available_utc_min, report_type (3 = routine, 4 = SPECI), report_type_name, is_cor, tmpf, t_group_c (tenths of a degree C, from the raw METAR T-group), metar (raw text).
  - `raw/*.csv.gz`, `selection.json`, `coverage_station_day.csv`, `MANIFEST.json` (files, bytes, sha256, URL pattern, window, availability basis, coverage summary).
- Window: valid time 2026-05-01T00:00Z to 2026-09-30T00:00Z, end exclusive. Rows with valid time >= 2026-09-30: **0** (asserted in code). As a result, local date 2026-09-29 is cut short in every zone. Pacific stations lose 17:00-23:59 PDT, which is why KLAX, KSEA and KSFO show 0 full neighbours on that one day.

## Point in time
Availability = METAR/SPECI valid time + >= 10 min (`available_utc_min`, the DESIGN rule 1 minimum). There is no per-report receipt time. 1,857 COR rows are flagged `is_cor` and must be excluded as inputs. 7,423 rows have no tmpf. This is not 1-minute data.

## Coverage (market-local days 05-01..09-29, 152 days; full day = >= 18 usable routine rows)
- Every market has >= 3 neighbours with a full day on every day except the cut-short 09-29 (Pacific stations only).
- Weak neighbours (fewer than 140 full days):
  - KSFO/PAO: 0 full days, part-time reporting (tower hours).
  - KBKF/CFO: 79. KLAX/TOA: 81. KMIA/HWO: 98.
  - KAUS/EDC: data on only 96 days. KDAL/HQZ: 103 days. KMIA/TMB: 103 days.
  - KATL/RYY: 136. KAUS/RYW: 127. KHOU/EFD: 125. KLGA/JRB: 131. KSFO/SQL: 134.
  - Per-day detail is in `coverage_station_day.csv`.
