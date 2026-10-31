# Free-registration sign-up list (data layer v2)

Owner decision 2026-10-14 (DECISION_LOG; [data layer v2 plan](DATA_LAYER_V2_PLAN.md) §9 Q4): free-registration keys are
allowed, and the owner does the sign-ups. Paid plans stay excluded. Checked 2026-10-14 against the providers' own pages
where they could be read. "Unverified" means no official page confirmed it; check at sign-up.

## Key storage rule (binding for every key below)

- A key lives **only** in `config/local/` (git-ignored, `.gitignore:50`) or in the process environment. Never in git,
  a commit, a log line, a status file, a captured payload, a URL written to disk, or a chat message.
- Agents never open `config/local/*` or `.env*`. Code reads a key through one loader that returns "absent" when it is
  missing, and every family that uses one degrades to "not captured, key absent" (a heartbeat row, not an error).
  No key is ever a *required* variable for capture, serving or tests (root `AGENTS.md`: no required credentials).
- Raw payloads are stored with the key redacted from the request URL and headers, as the WU restore does.
- Suggested names (the owner may choose others): `WEATHER_METOFFICE_DATAHUB_KEY`, `WEATHER_METEOFRANCE_APP_ID`,
  `WEATHER_KMA_AUTHKEY`, `WEATHER_CWA_AUTHKEY`, `WEATHER_NCEI_CDO_TOKEN`; CDS keeps its own `~/.cdsapirc`.

## Sign-up list, in priority order

| # | Provider | Sign-up | Free tier and limits | Use in v2 | Notes |
| ---: | --- | --- | --- | --- | --- |
| 1 | UK Met Office Weather DataHub | https://datahub.metoffice.gov.uk/ (Register; subscribe to *Site Specific* and *Land Observations*) | Free plan: 360 calls per 24 h per product, reset 00:00 UTC, HTTP 429 above it (DataHub FAQ); atmospheric-model plan 1 GB/month | London (EGLC) spot forecast and native observations; FC-3/OB-3 shadow | Key from "My Subscriptions"; header vs query unverified; terms not read (non-commercial/attribution unverified) |
| 2 | Météo-France API portal | https://portail-api.meteofrance.fr/ (create account; subscribe per API: observations, AROME/ARPEGE) | Free; per-API subscription; quota unverified | Paris (LFPB) observations; AROME/ARPEGE point guidance | API key or short-lived token minted from an Application ID; open-data licence Etalab 2.0 for meteo.data.gouv.fr (portal terms unverified) |
| 3 | KMA API Hub | https://apihub.kma.go.kr/ (Korean page, 회원가입) | Free; a contact phone number must be registered before use; quotas unverified | Seoul (RKSI) ASOS/AMOS surface observations | Fallback route: https://www.data.go.kr/en/ (service key, daily call quota); Korean-only UI |
| 4 | Taiwan CWA open data | https://opendata.cwa.gov.tw/ (register, then API 授權碼) | Free key; limits unverified | Taipei (RCSS) native observations; METAR≡WU check for the WU-settled city | `Authorization` query parameter (third-party guide); older examples use `opendata.cwb.gov.tw` |
| 5 | NOAA NCEI CDO token | https://www.ncei.noaa.gov/cdo-web/token (email only, token emailed) | Free; rate limits unverified | GHCN-Daily TMAX/TMIN referee for US airports (LB-1 archive referee; not same-day) | Lowest effort; archival only |
| 6 | NOAA MADIS | Application linked from https://madis-data.ncep.noaa.gov/index.html | Free; account gets a distribution category (public / public + mesonets / research); quotas unverified | QC'd US METAR/mesonet observations | Restricted categories need a government/research sponsor and may not be redistributed (madis_restrictions.shtml); request the public category |
| 7 | Copernicus CDS (ERA5) | https://cds.climate.copernicus.eu/ (register; accept each dataset's terms) | Free; queue limits unverified | Optional gridded reanalysis cross-check on the workstation only | Token in `~/.cdsapirc`; not an airport observation; lags real time |

## No sign-up needed

- **HKO** (Hong Kong): open data, free for commercial and non-commercial use (HKO open-data page); no key.
- **JMA** (Tokyo): obsdl history download and bosai AMeDAS feeds; no key found (login need unverified).
- **IEM ASOS/METAR archive**: no key or fee; 1,000 station-years per request; already the plan's label source.
- **AWC METAR/TAF, DWD MOSMIX, ECMWF open data, Open-Meteo**: no key (Open-Meteo licence risk accepted, §9 Q1).

## Not recommended

- **Synoptic Data** (the backend of weather.gov/wrh/timeseries): Open Access requires a `.edu` address at an accredited
  US institution, is non-commercial only, renews yearly and is approved by hand; we likely do not qualify.
- **CMA** (Shanghai): reportedly needs a Chinese phone number, identity checks for higher tiers and ~2 MB/day for
  foreign users (third-party reports, unverified). Shanghai settles on WRH/METAR, so it is not needed.

## Update this file when

A key is obtained (record *that* it exists and where it is configured, never the value), a limit is confirmed, or a
provider is added or dropped by the plan.
