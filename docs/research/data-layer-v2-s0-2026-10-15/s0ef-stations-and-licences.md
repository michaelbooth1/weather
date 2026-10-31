# S0(e) + S0(f) receipt: station maps, AWC ceilings, licence sheet

Desk items S0(e) and S0(f) of `docs/operations/DATA_LAYER_V2_PLAN.md`. Read on 2026-10-15 (workstation).
The code at commit `9fc1ff062` (master plus the 10-15 docs batch) was read only. Nothing was committed.

**Embargo compliance:** no observation, METAR, TAF, forecast or settlement payload was fetched (GET). I downloaded these items:

- station catalogues: the DWD MOSMIX `.cfg` and JMA `amedastable.json`, which hold station metadata only;
- the AWC OpenAPI YAML and documentation pages;
- terms pages;
- data.gouv.fr dataset metadata.

I made HEAD requests only, with no body, to:

- the DWD MOSMIX single-station KMZ URLs, to prove each station id exists;
- two AWC cache files, for their sizes.

I opened no `data/` file, no `.env*` file and nothing under `config/local/`.

The settlement airports are the 51 rows of `config/locations.json` (`settlement.station_id`). They include the 12 built-ins in `BUILTIN_SPECS` in `src/weather/market/market_registry.py` and the pilot tranche EGLC, ZSPD, LFPB, RKSI, RJTT and HKO/VHHH.

---

## (e)1 DWD MOSMIX station-id map

Sources:

- Catalogue: https://www.dwd.de/DE/leistungen/met_verfahren_mosmix/mosmix_stationskatalog.cfg?view=nasPublication&nn=16102 (HTTP 200, 299,502 B, 5,651 lines). Its coordinates are in degrees.minutes; I converted them to decimal before computing distances.
- Existence check: a `HEAD https://opendata.dwd.de/weather/local_forecasts/mos/MOSMIX_L/single_stations/<id>/kml/MOSMIX_L_LATEST_<id>.kmz` request for each id. 200 means the station is served. Every file showed Last-Modified Thu 15 Oct 2026 04:16:20 GMT, and the KMZ sizes are listed below.
- km = distance from the catalogue point to the coordinates in `config/locations.json`.

Match column: **exact** means the catalogue row carries the ICAO and lies within 5 km. **tagged-far** means the row carries the ICAO, but its coordinates are more than 5 km off, so the MOS point is not at the airport. **proxy** means there is no row for that ICAO and the nearest served station is given.

| Market | ICAO (cfg) | MOSMIX id | Catalogue name | km | Match | HEAD | KMZ B |
|---|---|---|---|---:|---|---|---:|
| amsterdam | EHAM | 06240 | AMSTERDAM | 2.3 | exact | 200 | 17142 |
| ankara | LTAC | 17128 | ANKARA | 1.6 | exact | 200 | 14021 |
| atlanta* | KATL | 72219 | ATLANTA GA. | 3.3 | exact | 200 | 9967 |
| austin* | KAUS | 72254 | AUSTIN | 13.1 | tagged-far | 200 | 9675 |
| beijing | ZBAA | 54511 | PEKING | 31.9 | tagged-far (city obs site) | 200 | 15023 |
| buenos-aires | SAEZ | 87576 | BUENOS AIRES AERO | 0.6 | exact | 200 | 15706 |
| busan | RKPK | 47153 | PUSAN | 0.6 | exact | 200 | 14176 |
| cape-town | FACT | 68816 | KAPSTADT | 2.0 | exact | 200 | 14391 |
| chengdu | ZUUU (WMO 56294 not served: 404) | 56187 | WENJIANG | 17.7 | proxy | 200 | 14639 |
| chicago* | KORD | 72530 | CHICAGO | 3.7 | exact | 200 | 10361 |
| chongqing | ZUCK | 57516 | CHONGQING (no ICAO) | 27.0 | proxy | 200 | 14629 |
| dallas* | KDAL | 72259 | KDFW DALLAS | 19.7 | proxy (DFW, not Love Field) | 200 | 10215 |
| denver* | KBKF | 72469 | DENVER (no ICAO) | 10.2 | proxy (alt 72565 KDEN, 18.8 km, 200) | 200 | 10354 |
| guangzhou | ZGGG | 59287 | GUANGZHOU | 28.8 | tagged-far | 200 | 15108 |
| helsinki | EFHK | 02974 | HELSINKI/VANTAA | 1.3 | exact | 200 | 17235 |
| hong-kong | HKO (WMO 45005 not in cfg) | 45007 | VHHH HONGKONG | 3.6 from HKO HQ | proxy. The row is tagged VHHH, but its coordinates (22°20'N 114°11'E) are in Kowloon, not at Chek Lap Kok | 200 | 13739 |
| houston* | KHOU | 72243 | KIAH HOUSTON TX. | 36.3 | proxy (IAH, not Hobby) | 200 | 10029 |
| istanbul | LTFM | F9731 | ISTANBUL AIRPORT | 1.0 | exact | 200 | 17256 |
| jeddah | OEJN | 41024 | JEDDAH/KING ABDUL | 2.4 | exact | 200 | 9784 |
| jinan | ZSJN | 54823 | ZSTN JINAN | 31.7 | proxy | 200 | 14503 |
| karachi | OPKC | 41780 | KARACHI | 0.6 | exact | 200 | 9091 |
| kuala-lumpur | WMKK (WMO 48650 not served: 404) | 48647 | WMKK KUALA LUMPUR | 45.0 | tagged-far (Subang site) | 200 | 15459 |
| london | EGLC | P0478 | LONDON/CITY INTL | 7.7 | tagged-far (catalogue coordinates off; still the EGLC point) | 200 | 16998 |
| los-angeles* | KLAX | 72295 | LOS ANGELES | 1.3 | exact | 200 | 10084 |
| lucknow | VILK | 42369 | LUCKNOW | 1.3 | exact | 200 | 9213 |
| madrid | LEMD | 08221 | MADRID/BARAJAS | 1.8 | exact | 200 | 15813 |
| manila | RPLL | 98429 | NINOY AQUINO/INTL. (no ICAO tag) | 1.2 | exact by coordinates (98425 "RPLL MANILA" is 8.8 km) | 200 | 12134 |
| mexico-city | MMMX | 76679 | MEXICO INT. | 1.2 | exact | 200 | 14118 |
| miami* | KMIA | 72202 | MIAMI | 4.6 | exact | 200 | 13588 |
| milan | LIMC | 16066 | MILANO/MALPENSA | 1.6 | exact | 200 | 18387 |
| moscow | UUWW | P0567 | MOSKVA/VNUKOVO | ~45 | tagged-far. The catalogue latitude is 56°00', but Vnukovo is about 55°36' (possible typo) | 200 | 13999 |
| munich | EDDM | 10870 | MUENCHEN-FL. | 2.3 | exact (note: locations.json WMO 10866 ≠ 10870) | 200 | 18542 |
| nyc* | KLGA | 72503 | NEW YORK | 2.2 | exact | 200 | 10556 |
| panama-city | MPMG | 78792 | MPTO PANAMA TOCUMEN | 22.6 | proxy | 200 | 6934 |
| paris | LFPB | 07150 | PARIS-LE BOURGET | 0.4 | exact | 200 | 18511 |
| qingdao | ZSQD | 54857 | QUINGDAO | 39.6 | tagged-far (old site, not Jiaodong) | 200 | 14589 |
| san-francisco* | KSFO | 72494 | SAN FRANCISCO | 1.6 | exact | 200 | 10372 |
| sao-paulo | SBGR | 83779 | SAO PAULO/INTL. | 0.3 | exact (locations.json WMO 83075 ≠ 83779) | 200 | 15192 |
| seattle* | KSEA | 72793 | SEATTLE | 1.2 | exact | 200 | 13991 |
| seoul | RKSI | 47113 | INCHEON/INTL. | 1.6 | exact | 200 | 14918 |
| shanghai | ZSPD | 58362 | SHANGHAI PUDONG | 42.4 | **tagged-far**. Its coordinates are identical to 58367 ZSSS (31°24'N 121°28'E, the Baoshan area), not Pudong airport | 200 | 14802 |
| shenzhen | ZGSZ | 59493 | SHENZHEN HUANGTIAN | 1.5 | exact | 200 | 14520 |
| singapore | WSSS | 48698 | SINGAPUR | 0.2 | exact | 200 | 15830 |
| taipei | RCSS (WMO 46696 not served: 404) | 58968 | "RCTP TAIBEI" | 5.3 | proxy. The row is tagged RCTP, but its coordinates are in Taipei city | 200 | 13563 |
| tel-aviv | LLBG | 40180 | TEL AVIV | 1.7 | exact | 200 | 11946 |
| tokyo | RJTT | **47671** | TOKYO INTERNATIONAL | 1.3 | exact (known example confirmed) | 200 | 13656 |
| toronto* | CYYZ | 71624 | TORONTO | 1.4 | exact | 200 | 17087 |
| warsaw | EPWA | 12375 | WARSCHAU | 0.6 | exact | 200 | 15034 |
| wellington | NZWN | 93436 | WELLINGTON AIRPORT | 0.6 | exact | 200 | 11178 |
| wuhan | ZHHH | 57494 | WUHAN (no ICAO) | 19.7 | proxy | 200 | 15612 |
| zhengzhou | ZHCC | 57083 | ZHENGZHOU | 27.6 | tagged-far | 200 | 14712 |

\* = one of the 12 built-ins.

Summary:

- All 51 markets have a served MOSMIX_L id.
- 32 are **exact**.
- 9 are **tagged-far**: KAUS, ZBAA, ZGGG, WMKK, EGLC (7.7 km), UUWW, ZSQD, ZSPD, ZHCC.
- 10 are **proxy**: ZUUU, ZUCK, KDAL, KBKF, HKO, KHOU, ZSJN, MPMG, RCSS, ZHHH.

Among the pilot cities, Paris, Seoul and Tokyo are exact. London is acceptable (7.7 km). **Shanghai's MOSMIX point is 42 km from Pudong**, so FC-4 for ZSPD is a regional guide, not station MOS.

KMZ sizes from HEAD are 6.9–18.5 KB (the plan's measured 13.3–13.6 KB per run is in range). Full table: 51 × ~14 KB × 4 runs ≈ 2.9 MB/day (est.).

Side finding: `config/locations.json` `station_wmo` differs from the DWD catalogue for these stations: EDDM (10866 vs 10870), SBGR (83075 vs 83779), WMKK (48650 not served), RPLL (98429 is fine), ZUUU (56294 not served) and RCSS (46696 not served). This needs a review; I did not edit the file.

## (e)2 JMA AMeDAS station for RJTT

Source: https://www.jma.go.jp/bosai/amedas/const/amedastable.json (station metadata, HTTP 200, 187,742 B).

| AMeDAS id | Name | Type | elems | Lat / Lon | Alt |
|---|---|---|---|---|---|
| **44166** | 羽田 Haneda (ハネダ：東京国際空港) | C | `11110000` | 35°33.2'N 139°46.8'E | 6 m |
| 44132 | 東京 Tokyo (Otemachi/Kitanomaru) | A | `11111111` | 35°41.5'N 139°45.0'E | 25 m |

44166 is the RJTT AMeDAS point, consistent with the ICAO coordinates 35.553, 139.781. Its `elems` flags show temperature present. The flag order (temp, precip, wind, sun, ...) is my reading and is **unverified**.

The bosai 10-min feed id is 44166. The obsdl history `prec_no`/`block_no` for Haneda is **unverified**: I did not read the obsdl station selector.

## (e)3 TAF TX/TN availability (documentation only; no TAF fetched)

ICAO Annex 3 / WMO FM 51 rule: the TX/TN group is optional and is included "when required by regional air navigation agreement". The HKO decode page states this wording.

AWC's TAF JSON schema has a parsed `temp[]` array with `maxOrMin: MAX|MIN` (openapi.yaml, TAFJSON). So when a TAF carries TX/TN, AWC exposes it already parsed.

| Airports | TX/TN in TAF? | Basis |
|---|---|---|
| VHHH (Hong Kong) | **Yes**: one TX and one TN per 30 h TAF, at the end of the main group | HKO: https://www.hko.gov.hk/en/aviat/decode_taf.htm ; https://www.hko.gov.hk/en/aviat/outreach/AMIDS/19th/NewTAF_Table1.htm |
| KBKF (Denver, Buckley SFB, USAF) | **Yes**: all military TAFs carry TX/TN in °C with UTC times | NWS SCN 25-78 (KBAF TAF transfer to USAF), https://www.weather.gov/media/notification/pdf_2025/scn25-78_KBAF_TAF_transfer_to_USAF.pdf ; AFMAN 15-124 |
| KATL KAUS KORD KDAL KHOU KLAX KMIA KLGA KSFO KSEA (NWS civil) | **No** | The same NWS SCN shows the NWS TAF without TX/TN. NWSI 10-813 was downloaded, but its text could not be extracted, so "no" is **unverified against the directive text** |
| CYYZ (Canada) | No (**unverified**). MANAIR did not show an explicit exclusion | |
| EGLC (UK) | No (**unverified**). UK AIP GEN 3.5 (first 100k chars) has no TX/TN mention | |
| LFPB (France) | Yes in at least some (long) TAFs (**unverified**; ENM Toulouse course pages document the group, not Météo-France policy) | |
| RKSI, RKPK (Korea) | Likely yes (**unverified**; one RKSM example only) | |
| China (ZSPD, ZBAA, ZGGG, ZGSZ, ZUUU, ZUCK, ZSQD, ZSJN, ZHHH, ZHCC), RJTT, Europe ex-FR, RU, TR, Middle East, South Asia, SE Asia, LatAm, NZ, ZA | **unverified**. No national document was found | |

Proposed verification once the embargo has lifted (after 10-15): one GET of `/data/cache/tafs.cache.xml.gz`, which holds all current TAFs, refreshes every 10 min and is 346,444 B gz by HEAD. Count the `max_temp`/`min_temp` (TX/TN) elements per ICAO. That single request answers the question for all 51 airports, and it is also the cheapest FC-6 fetch.

## (e)4 AWC Data API ceilings

Sources:

- https://aviationweather.gov/data/api/ (read 2026-10-15)
- https://aviationweather.gov/data/schema/openapi.yaml (v4.0, 93,075 B)

| Item | Documented value | Status |
|---|---|---|
| Rate limit | "All requests are rate limited to 100 requests per minute." Exceeding it "will result in access being blocked." | documented |
| Max results | "Most endpoints return a maximum of 400 entries (please consider using cache files for larger requests)." | documented |
| History depth | "allows access to up to the previous 30 days of data" | documented. A third-party search summary said 15 days; the current page says 30 |
| `hours` on /metar | number, default 1.5. **No documented maximum.** The effective ceiling is 30 days by depth and 400 rows by cap | max undocumented |
| `hours` on /taf | **Not a parameter.** /taf takes `ids`, `bbox`, `format`, `metar`, `time` (valid/issue) and `date`. The page warns: "Undocumented query parameter requests are restricted and will result in an error." | documented (absence) |
| Max `ids` per request | **Not documented.** The schema shows only a comma-separated list | undocumented |
| User-Agent | "Set a custom user agent…" (recommended, not required) | documented |
| CORS | not permitted | documented |
| Cache files (bulk, gz) | `metars.cache.csv.gz` every minute, HEAD 266,468 B. `tafs.cache.xml.gz` every 10 min, HEAD 346,444 B | documented + HEAD |
| Bytes per API request | No documentation exists, and I made no HEAD on /api (it would execute a live query). Estimate: ~1–1.5 KB per JSON METAR row, so 51 ids × hours=2 (~110–160 rows) ≈ 120–240 KB uncompressed | **est., unverified** |

Implications for OB-1:

- The 400-row cap binds before any hour cap. A 36 h sweep returns about 40–60 rows per station, so a request can carry **at most ~6–8 stations**. A single 51-id `hours=36` call would be silently truncated.
- The per-minute 51-id `hours=2` poll (≤ ~160 rows) fits.
- FC-6 should use the TAF cache file, or `/taf?ids=<list>` without `hours`.

## (e)5 Synoptic vs AWC report-set difference

The WRH timeseries backend (Synoptic `api.synopticdata.com`) needs a token. We have none and do not qualify for Open Access (`.edu`, non-commercial; see free-registration-signup-list.md). The WRH page's embedded browser token must **not** be scraped or reused.

I did not run anything for this item.

Proposed no-token alternative: compare the IEM ASOS/METAR archive with the AWC API for the same pre-09-30 station-days.

1. **Stations and days:** 6 stations (EGLC, LFPB, RKSI, RJTT, ZSPD, KLGA) × 3 days in 2026-09-24..09-29. All are pre-embargo.
2. **IEM side:** `mesonet.agron.iastate.edu/cgi-bin/request/asos.py` with `data=metar`, `report_type=3,4` (routine + specials) and `tz=Etc/UTC`, at 15 s spacing.
3. **AWC side:** `/api/data/metar?ids=<≤6>&date=<D+1 00Z>&hours=<≤30>&format=json`, with requests kept under the 400-row cap.
4. **Join and output:** join on (station, obs_time, normalized raw hash). Report the reports present only in IEM, only in AWC, or COR-differing, plus the effect on the daily max.
5. **Deadline:** AWC holds only 30 days, so this must run **before ~2026-10-24**. After that, 09-24 drops out of the AWC window and only IEM remains.

Caveats:

- This measures IEM vs AWC, not Synoptic. The venue's WRH = Synoptic ingest stays a proxy (EF §10c's 50/50 agreement is the existing evidence).
- The run counts as a fetch of settlement-instrument history. It needs the owner or master to confirm that pre-embargo dates are permitted once the embargo ends; until then it is a desk proposal only.

---

## (f) Licence sheet (read 2026-10-15)

| Source | Licence | Commercial use | Attribution | Rate limits | Terms URL |
|---|---|---|---|---|---|
| **Open-Meteo** (free API) | API data: **CC BY 4.0** | **Free API is non-commercial only.** Examples of commercial use include "Conducting undisclosed research at commercial entities" and "Integrating our service into commercial products"; commercial use needs a paid plan (owner accepted the risk, plan §9 Q1) | Required: credit + licence link. "You must include a link next to any location Open-Meteo data are displayed" ("Weather data by Open-Meteo.com") | "Less than 10'000 API calls per day, 5'000 per hour and 600 per minute"; table: 300,000/month. IPs blocked for misuse | https://open-meteo.com/en/terms ; https://open-meteo.com/en/licence (`/en/license` returns 100 B) ; change history on GitHub |
| **DWD open data** (MOSMIX) | **CC BY 4.0**. The DWD legal notice says open spatial data and HVD services "may be re-used under the Creative Commons licence conditions" with the source acknowledged. **GeoNutzV is not mentioned on any current DWD page read**, so the plan's "GeoNutzV verified" should read **CC BY 4.0** (the switch date is unverified) | Not restricted by CC BY 4.0. Not addressed explicitly on the pages read | Required ("due acknowledgement"). Exact template on "Rules and templates for acknowledging the DWD as source" (**not read**; copyright_node URL returned 404) | None documented. Open Data Server: "service and availability levels cannot be guaranteed" | https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html ; https://opendata.dwd.de/README.txt |
| **JMA** (bosai AMeDAS, obsdl) | Public Data License (Japan) v1.0, stated compatible with CC BY 4.0 | Allowed under PDL1.0/CC BY (not stated explicitly on the page). The Meteorological Service Act Art. 17/23 limits *issuing forecasts/warnings* in Japan, which does not apply to private use | Required: "Source: Japan Meteorological Agency website (URL)"; state edits | None documented | https://www.jma.go.jp/jma/en/copyright.html (terms established 2016-01-28) |
| **HKO** | Split. (a) Via **DATA.GOV.HK**: Terms v1.2 (2025-05-26) allow "both commercial and non-commercial purposes on a free-of-charge basis". (b) HKO **website** materials: "use of the Materials for commercial purposes is strictly prohibited unless" there is prior written authorisation | Yes only for datasets obtained under DATA.GOV.HK terms. The since-midnight max/min dataset is listed there (`hk-hko-rss-max-and-min-air-temp-since-midnight`). The signup list's "free for commercial use" holds **only via that route** | Required: attribute the Government/HKO and DATA.GOV.HK | None documented | https://data.gov.hk/en/terms-and-conditions ; https://www.hko.gov.hk/en/readme/readme.htm |
| **UK Met Office DataHub** | Proprietary: "perpetual, worldwide, non-exclusive, non-transferable licence" | FAQ: "Yes. Subject to the terms of the licence" | Required: "Powered by Met Office data" | Free Land Observations: 360 calls/24 h, reset 00:00 UTC (search result citing the pricing page); site-specific quotas per plan. The T&C PDF link returned **404**, so the full terms are **unverified** | https://datahub.metoffice.gov.uk/support/faqs ; https://datahub.metoffice.gov.uk/pricing/observations |
| **UK Met Office open data** (AWS `met-office-atmospheric-model-data`) | CC BY-SA 4.0 according to the Open-Meteo licence page; the AWS listings were not read in full, so this is **unverified**. The retired legacy AWS service was non-commercial | **unverified** | CC BY-SA requires attribution and share-alike | none (S3 no-sign-request) | https://registry.opendata.aws/uk-met-office/ (legacy, retired) |
| **Meteostat** | **CC BY 4.0** for data redistributed by Meteostat. This is the current page; older PyPI text said CC BY-NC 4.0 | Allowed ("even commercially") | Required: "Source: Meteostat, <providers>" | None documented; access may be blocked without notice; no multiple accounts | https://dev.meteostat.net/license ; https://dev.meteostat.net/terms |
| **Météo-France** | Open data on data.gouv.fr: **Licence Ouverte v2.0 (Etalab)**. The data.gouv.fr API shows `license: lov2` for "Données climatologiques de base - horaires" | Allowed (LO 2.0) | Required: source + date of last update | **Portal API (portail-api.meteofrance.fr) terms and quotas unverified**; the FAQ did not render | https://www.etalab.gouv.fr/licence-ouverte-open-licence ; https://portail-api.meteofrance.fr/ |
| **KMA** | KOGL (공공누리). Type 1 materials are free with source credit. Unmarked materials need prior consultation | Type 1 allows it; per-dataset KOGL type and **API Hub terms are unverified** | Required: state the source | **unverified** (API Hub / data.go.kr quotas not read) | https://www.kma.go.kr/kmadev/guide/copyright.jsp ; https://apihub.kma.go.kr/ |
| **IEM** (Iowa State) | Public domain: "may be used freely by anyone for any lawful purpose" | Yes ("any lawful purpose") | Appreciated, not required | None documented; the repo observed HTTP 429 and uses 15 s spacing (plan §5) | https://mesonet.agron.iastate.edu/disclaimer.php |
| **AWC / NOAA NWS** | US Government: "in the public domain, unless specifically noted otherwise, and may be used without charge for any lawful purpose" | Yes | Not required; no endorsement implication; NWS logo needs permission | AWC: 100 req/min, 400 rows/request, 30-day depth. NWS: retry at ≥ 1 min intervals; blocking possible | https://www.weather.gov/disclaimer ; https://aviationweather.gov/data/api/ |

## Unverified / open items

- NWSI 10-813 text: the PDF could not be extracted locally.
- TX/TN practice for every non-HK, non-US airport.
- AMeDAS obsdl block_no for Haneda.
- Max `ids` per AWC request.
- AWC bytes per request.
- DWD attribution template and the GeoNutzV-to-CC BY switch date.
- The full Met Office DataHub T&C.
- Météo-France portal quotas.
- KMA API Hub terms and quotas.
- Licence of the Met Office AWS atmospheric data.
