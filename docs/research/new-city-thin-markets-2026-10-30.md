# New cities: where the market is thinnest (lane L3, S1, 2026-10-30)

This is a dated research note, not canonical guidance. It is outcome-free. It reads current prices of open events
only, and the survey drops every event dated before the read day before any book read. No settlement, resolution
field or resolved outcome is read. Two recorders below are drafts: built and tested, but not registered and not
running. Registration needs the owner's yes, relayed by the coordinator.

## 1. Survey: what exists now, how much it trades, how wide the books are

**Read:**
- Gamma at 2026-10-30T20:47:59Z.
- CLOB books at 20:48:27Z, 20:53:55Z and 20:59:23Z.
- 169 requests, 35.1 MB.
- Script `tools/research/temperature_market_survey.py`, sha256
  `b74b6ecc14aaf2d46984613d2071423dfb8c8ba8b1f247948aeae867f352360a`.
- Output in `C:\t\l3newcity\survey1`: `events.json`, `books_0..2.json`, `summary.csv` and `receipt.json`.

**Endpoints**, public and read-only (International Polymarket), with a URL allowlist and no credentials:
- `GET https://gamma-api.polymarket.com/events?tag_slug=daily-temperature&closed=false&limit=100&offset=<n>`
- `POST https://clob.polymarket.com/books`

**What exists:** 253 open daily-temperature events, 249 of them dated 10-30..11-02. That is 94 (family, city) series:
- `highest` in 49 cities;
- `lowest` in 45 cities.

Our 12 built-ins appear in both families. There is no other temperature family under that tag.

**Measures**, over the T+1 and T+2 events (10-31 and 11-01), so that same-day prices are left out:
- **Volume:** the event volume summed over bands, median over the series' events, in USDC; Gamma `volumeNum`,
  `volume24hr` and `liquidityNum`.
- **Spread:** the median best ask minus best bid over the two-sided band books in three snapshots.
- **Inner spread:** the same, but only over bands with a mid in [0.05, 0.95].
- **Two-sided:** the share of band-snapshots with both a bid and an ask.

| Group | Series | Volume | Vol 24h | Liquidity | Spread | Inner spread | Two-sided |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| highest, our 12 | 12 | 6,731 | 5,512 | 27,973 | 0.016 | 0.030 | 0.75 |
| highest, other cities | 37 | 9,168 | 7,998 | 34,576 | 0.015 | 0.030 | 0.73 |
| lowest, our 12 | 12 | 23 | 23 | 1,424 | 0.069 | 0.47 | 0.23 |
| lowest, other cities | 33 | 145 | 101 | 2,700 | 0.217 | 0.58 | 0.27 |

**Reading (prices only, no edge claim):**
- **Highest-temperature markets:** new cities are not thinner than our US 12. They trade a little more, and their
  inner spreads are the same 3 cents.
- **Lowest-temperature family:** this is thin everywhere. Its median 24-hour volume is under $150, and fewer than a
  third of band books are two-sided. A spread over a one-sided book is undefined, so the lowest family is thin in
  the sense of "barely quoted", not "wide but tradable".

**Thinnest highest-temperature new cities** (lowest 24-hour volume, or wide inner spread):

| City (station) | Vol 24h | Liquidity | Inner spread | Two-sided |
| --- | ---: | ---: | ---: | ---: |
| Karachi (OPKC) | 2,128 | 43,331 | 0.020 | 0.82 |
| Ankara (LTAC) | 2,730 | 35,450 | 0.031 | 0.77 |
| Qingdao (ZSQD) | 3,581 | 21,121 | 0.040 | 0.73 |
| Warsaw (EPWA) | 3,584 | 43,740 | 0.030 | 1.00 |
| Sao Paulo (SBGR) | 3,858 | 17,215 | 0.046 | 0.86 |
| Panama City (MPMG) | 4,444 | 14,369 | 0.110 | 0.64 |
| Moscow (UUWW) | 4,615 | 28,298 | 0.040 | 0.64 |
| our thinnest, Denver (KDEN) | 4,100 | 16,299 | 0.035 | 0.73 |

**Candidates picked for recording:** Panama City, Sao Paulo, Qingdao, Ankara and Moscow, in both families where
listed (Panama City has no lowest-temperature event). Each is among the thinnest by volume and has an inner spread
of at least 3 cents. Karachi and Warsaw are thin by volume but quote tightly.

**Caveat:** this is one read of about 11 minutes, at 20:48–20:59 UTC, which is night in East Asia. Spreads move with
the time of day, so the recorder data will replace this snapshot.

## 2. What the host captures today: plan against config

These readings come from repository canon at `origin/master` `1a78e1ba0`. I did not read the host; master owns the
host side.

**Plan:**
- DECISION_LOG 2026-10-23 phase-2 plan (line 258): R1 turns on the five pilot cities (London, Paris, Seoul, Tokyo,
  Shanghai) after the S2+S9 day-3 receipts. R2 adds Munich, Madrid, Beijing, Wellington and Hong Kong recorder-only
  from 11-01.
- Line 259 decision (3): R1 after the day-3 receipts.
- Line 265: R1 may use the day-1 receipt if its checks pass.
- The study (`docs/research/more-markets-phase2-scoping-2026-10-23.md`, lines 302–303) dates R1 at about 10-29. R2
  needs config rows and the post-10-31 `event_driven` cadence.
- `STATE_OF_PLAY.md` line 61: "R1 pilot cities recorder-only, R2 from 11-01".

**Config** (`config/capture_families.json`):
- Line 32 `"pilot": "off"`, line 33 `"rewards_sweep": "off"`, line 34 `"built_in_reward_cadence": "legacy"`.
- Lines 36–40 hold only the five R1 rows. No R2 city is listed.
- The block's scope text (line 31) says the switches "land off/legacy". No commit since `10728b83f` has turned the
  pilot on.

**Disagreement:** the plan's R1 trigger date (about 10-29) has passed, but the config still has the pilot off. Canon
records no R1 receipt verdict and no decision to defer R1. R2 is not due before 11-01, but its five rows and the
`event_driven` cadence are both still missing. This is reported only; I made no change.

## 3. Settlement stations for the candidates

Each venue rules text (events of 2026-11-01, read 2026-10-30T21:00Z) names:
- **Station:** a METAR station by ICAO, with `resolutionSource`
  `https://aviationweather.gov/api/data/metar?ids=<ICAO>...`.
- **Value:** the highest (or lowest) temperature from the hourly T-group of routine reports, in tenths of a degree
  Celsius.
- **Day:** the calendar day in local time, including any daylight-saving shift.

| City | Venue station | Coordinates and time zone (`config/locations.json`) | Flags |
| --- | --- | --- | --- |
| Panama City | MPMG, Marcos A. Gelabert Intl | 8.967, -79.555, America/Panama | S0 study: the nearest WMO synop is Tocumen (proxy) |
| Sao Paulo | SBGR, Guarulhos Intl | -23.432, -46.469, America/Sao_Paulo | `station_wmo` 83075 in `locations.json` differs from the DWD catalogue (83779) |
| Qingdao | ZSQD, Jiaodong Intl | 36.362, 120.087, Asia/Shanghai | The WMO 54857 catalogue entry is the old site, not Jiaodong |
| Ankara | LTAC, Esenboga Intl | 40.128, 32.995, Europe/Istanbul | none |
| Moscow | UUWW, Vnukovo Intl | 55.592, 37.261, Europe/Moscow | The DWD catalogue latitude looks wrong (S0 study) |

**Unknowns flagged:**
- The venue gives no coordinates. These come from `locations.json`, whose `settlement` blocks still say
  `wunderground_history`/`whole_degree`, which the current rules text supersedes.
- How often each of these stations reports the T-group is not measured.
- How the bands round tenths is for M1 to read from the rules text.
- All 12 built-ins' rules text now cites the same METAR API. Denver names KDEN; that is already recorded in
  `config/venue_rule_stations.json`.

## 4. Draft recorders (not registered)

**New-city price recorder:**
- Branch `claude/new-city-recorders-20261030`, worktree `C:\wt\l3newcity`.
- `tools/research/new_city_price_forward_recorder.py` reuses `t1_price_forward_recorder.py` unchanged; its blob
  stays `e73b7537`. It has the same two public reads, allowlist, integrity rules and guards.
- Markets: the 9 series above. Horizons T+0 and T+1 by default. T+2 is allowed, but some T+2 events are listed only
  later in the UTC day; in the first dry run they returned 404, which marks those cycles incomplete.
- Output `C:\t\new_city_prices\forward`; task `L3 new-city price forward recorder (logon)`.

**Price dry run** (`C:\t\new_city_prices\dryrun2`):
- Slot 2026-10-30T21:00Z; complete.
- 18/18 events with complete ladders, 198 bands, 9/18 ladder sums within [0.90, 1.10].
- 36 requests, 1.91 MB.
- 94,920 bytes kept, so about 9 MB/day at 96 cycles; download about 183 MB/day.
- rows_sha256 `5cf55732acc1fd8dc2af8bf6e545e0040b850be96b21bd1e5252d65df71d0819`.

**New-city ENS recorder:**
- Branch `claude/new-city-ens-20261030`, worktree `C:\wt\l3newens`.
- That branch merges L13's `claude/ecmwf-ens-recorder-20261030` (`4fc2b7119`); L13's worktree is untouched.
- `tools/research/new_city_ens_forward_recorder.py` reuses L13's module unchanged (blob `59056b35`). It rebinds
  only the station set (the five ICAOs above), the schema and the identity. It runs as its own instance at
  `C:\t\new_city_ens\forward` and refuses L13's root.
- It covers the highest temperature only: L13's module has no 3-hour minimum parameter.
- About 0.85 GB/day more download, because the fields are fetched per instance. Adding the five stations to L13's
  own instance would cost no extra download; that is L13's and master's choice.

**ENS dry run:** `--once` ran with no open runs, because the forward start is 2026-10-31T00Z. No step was fetched.

**Tests:**
- Both drafts parse with the PowerShell parser and are checked for control characters. Backslashes in the generated
  scripts were written with `chr(92)`.
- Registrars use the L13 import-then-stub harness with the `WEATHER_TASK_TEST` refusal, `-ExpectedLauncherSha256`,
  task-name validation, and creation of the working directory before registration.
