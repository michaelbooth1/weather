# The WU settlement source went down — root-caused and fixed 2026-08-07

Status: **root cause found, fix verified on production, awaiting the quiet-window merge.**
Supersedes the framing in
[the 404 classification note](2026-06-21-wu-history-current-day-degradation.md) and every
"use `-Refetch`" instruction written on 2026-08-06.

## Root cause — we were sending an advertising key to the weather API

`public_access_from_page` scanned the history page for *any* URL carrying an `apiKey=`
parameter and took the first match. That match was
`https://weather.com/api/v1/mew/entity/ad_third_party_config/...?apiKey=...` — **the page's
third-party advertising config**. The client then used that host and that key for the
observations call.

This explains both symptoms exactly, and neither is an outage:

- **404 on `weather.com/v1/...`** — the host came from the ad URL, and it does not serve the
  observations route at all.
- **401 on `api.weather.com/v1/...`** — the correct host, presented with an advertising key.

`-09-37a` replaces the regex with a parse of the page's injected runtime config
(`const data = {... "API_URL": ..., "API_KEY": ... }`), which is what the browser itself uses.
It resolves to `https://api.weather.com` with the page's own 32-char token.

**The date-independence was the clue and it was mis-read.** Every date failing, including ones
already stored, meant the *request* was wrong, not the data. It was read as "the endpoint is
gone" instead. When a source fails uniformly across every key you vary, suspect the part you
are not varying.

## Verification on the production host, 2026-08-07

Run from an **isolated git worktree**, never the live working tree — `wu_history.py` is in the
snapshot and observation-trigger closures and a checkout would have rolled capture.

| Check | Result |
| --- | --- |
| `2026-06-15` Toronto vs stored `daily_summary.csv` | **24 observations, max 20, min 10** — stored row is `row_count 24, max_temp 20.0, min_temp 10.0` |
| `2026-08-05`, `2026-08-06` Toronto | **OK** — 24 and 34 observations |
| `2026-08-05`, `2026-08-06` NYC | **OK** — 26 and 31 observations, in °F as configured |
| Payload shape | unchanged 45-field v1 observations |
| `tests/sources/test_historical_sources.py` | 44 passed |

The 08-05 / 08-06 fetches are the dates that were actually blocking settlement.

**Rate limiting is real.** Probing five dates back-to-back drew failures that a 12-second
spacing did not. Space requests; do not read a burst failure as a route failure.

## Branch supersession

`-09-37a` **contains all of** `codex/fix-wu-404-classification-2026-08-06` —
`PAGE_BACKED_PERMANENT_NO_DATA_STATUS_CODES`, `PAGE_BACKED_EXCEPTION_ATTR`, `_raise_for_status`
and the `failure_class_for_error_row` re-derivation. **Do not merge that branch as well**; it is
superseded and would conflict.

## Original diagnosis, kept because the reasoning matters

## What is true

`weather.com/v1/location/<history_id>/observations/historical.json` returns **404 for every
date**, not for a missing day. The settlement chain has been stuck since **2026-08-04**.

| Probe (Toronto, `CYYZ:9:CA`) | Result |
| --- | --- |
| `2026-08-05`, `2026-08-06` — unsettled dates | **404** |
| `2026-08-04` — **a date already stored locally** | **404** |
| `2026-06-15`, `2026-07-10` — long-settled dates | **404** |
| `https://weather.com/v1/.../observations/historical.json` | **404** |
| `https://api.weather.com/v1/.../observations/historical.json` | **401** |
| `https://www.wunderground.com/history/daily/CYYZ/date/2026-8-5` | **HTTP 200**, 48,121 bytes |
| `public_access_from_page` on that page | **succeeds**, 32-char token |

**404 versus 401 is the whole diagnosis.** The route still exists on `api.weather.com`; it
rejects the token the history page hands out. The page-scrape half of the client still works and
the API half does not.

The page carries **no** observation payload to fall back on: `valid_time_gmt` occurs 0 times,
`__NEXT_DATA__` 0 times. The only versioned API paths it references are an ad config and a
script loader. A naive "parse the page instead" will not work.

## What this is NOT

- **Not a poisoned date.** `-Refetch` **worked**: the 01:30 recovery genuinely re-attempted all
  12 markets — fresh `recorded_at_utc` of 05:31–05:34, `transient_retry_count: 0`,
  `fetched 0`, `blocked 12`. It did not skip. The fetch was made and returned 404.
- **Not fixed by the classification branch.** `codex/fix-wu-404-classification-2026-08-06` is
  still worth merging — it stops dates being stamped `treated_as_source_unavailable` so they
  stay retryable once a route works — but **it does not restore settlement.**
- **Not a per-station outage.** All 12 markets across 3 countries fail identically.

## Blast radius

| | |
| --- | --- |
| Settlement | frozen at **2026-08-04** |
| Toronto streak | **15 / 14, banked and safe** — but frozen, and it cannot advance |
| Learning loop, promotion, MM countability | all downstream of settlement |
| Capture (snapshot, CLOB, observation-trigger) | **unaffected** — independent of WU history |

The banked 07-21 → 08-04 window survives in the ledger. What is at risk is *future* contiguity:
if 08-05 and 08-06 never settle, a later 14-day window restarts from whenever settlement resumes.

## The standing architectural risk, now realised

`AGENTS.md` makes configured Weather Underground history **the** settlement proxy. 26 source
adapters feed features; one unowned scraped source decides truth. This is the third failure of
that dependency and the first that no retry, reclassification, or flag can repair.

Any durable fix should be judged on whether it reduces that single point of failure, not only on
whether it makes today's fetch work.

## Reproduce

```powershell
$repo = 'C:\Users\micha\Desktop\github\weather'
Set-Location $repo
.\venv\Scripts\python.exe -c @"
import datetime as dt
from weather.sources.wu_history import PublicWundergroundHistoryClient
c = PublicWundergroundHistoryClient(history_id='CYYZ:9:CA', station_icao='CYYZ', units='m')
for d in ('2026-06-15','2026-08-04','2026-08-05'):
    day = dt.date.fromisoformat(d)
    try: print(d, 'OK', len(c.fetch_range(day, day)))
    except Exception as e: print(d, 'FAIL', getattr(getattr(e,'response',None),'status_code','-'))
"@
```

Never print the scraped token. `redact_api_key` exists in `weather.sources.wu_history` for
exactly this.

## Update this file when

A working route is found, the client is adapted, or the settlement proxy contract changes.
