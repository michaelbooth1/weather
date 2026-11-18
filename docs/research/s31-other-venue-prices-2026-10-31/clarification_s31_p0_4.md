# S31 P0 Clarification 4 (2026-10-31): pre-cutoff jobs, resume by receipt, ForecastEx staging

Status: fourth clarification to `rule_s31_p0.md` (sha256
`d50112ccf2a22b2f02140e06c68bbbe36936a2ac9dc8e16351a7188ee2ea856e`, approved by master 2026-10-31). It sits
beside Clarification 1, `clarification_s31_p0_1.md` (sha256
`b7bb9f2aafb654bd68389c170416f3efae64b33696723a6c54572ce22e177e5d`), Clarification 2,
`clarification_s31_p0_2.md` (sha256 `798dfaa912c7e94da97c0c99340d12726bb9c606b7279324b92ef4b8c670bd26`), and
Clarification 3, `clarification_s31_p0_3.md` (sha256
`654408acbc40fa981b30947547863ae7140694f530f559f1bb9fefe94db0a340`), all approved. None of those four files is
edited, and the DECISION_LOG is not edited. This file records master's ruling on the S31 V0 clean stop: options
(a) and (c), not (b). Lane L14, outcome-free: no venue price or outcome was read to write this file, and no
archived raw body was read.

The ruling keeps the 30-minute hard kill. The work is split into runs of at most 30 minutes each, and each run
resumes from the receipts of the runs before it. Option (b), N = 32, was not taken because it would make the P0
descriptive.

## 1. Scope sentence

The DECISION_LOG row dated 2026-10-30 that approves S31 says: "only metadata endpoints with field allowlists".
The phrase "metadata endpoints only", used in the rule and in Clarifications 1-3, is master's paraphrase of that
row. It means structured API endpoints read through field allowlists, never rendered venue pages. Candle prices
were already approved under rule `d50112cc` (§6, allowlist B) and stay approved here. Nothing in this file widens
the embargo: prices are read only for target dates up to 2026-09-29 and only on released cells.

## 2. New paths (ruling (a))

The V0 stop showed why these are needed. Kalshi moves settled markets to a historical tier: the live `/markets`
call returned no markets for events before the cutoff. Three jobs are added. Each is pinned in the module to an
exact host/path pattern. No wildcard is added.

| Job id | Exact path (host `api.elections.kalshi.com`) | Allowlist | Notes |
| --- | --- | --- | --- |
| `event_meta:{event}` | `/trade-api/v2/events/{t}/metadata` | M: `event_ticker`, `market_ticker` | Each market ticker must start with `{event}-`, or the body is refused (FormatRefused). Extract: `event_markets.jsonl`. |
| `hist_markets:{event}` | `/trade-api/v2/historical/markets` | A: the same 9 fields as live `/markets` | Every other field is dropped without being parsed. Extract: `v0_markets_hist.jsonl`. |
| `candles:historical:{market}` | `/trade-api/v2/historical/markets/{m}/candlesticks` | B | Refused before the request unless the window starts before the historical cutoff, `2026-08-31T00:00Z` (`HISTORICAL_CUTOFF_UTC`). |

Every existing guard applies unchanged to all three:

- **Date bound before the request.** Target dates are checked against 2026-09-29, and candle windows against
  `GLOBAL_BOUND_UTC` and the series zone in `SERIES_TZ`. Both checks run before any request is made.
- **Late items quarantined.** Late candles are dropped unparsed and counted.
- **Auth means STOP.** A 401 or 403, or a non-200 body with an auth marker, quarantines the body and raises
  AuthRequired, which ends the run.
- **Rate.** At most 1 request per second, through the shared limiter.
- **Raw archive.** Bodies are written exclusive-create, never overwritten.

**Added to the stop rule.** A 429 or 5xx answer is archived to `_quarantine_refused`, the job is left incomplete,
and the run stops with HttpStop (exit code 4). Retries are not made inside the run.

## 3. Resume by receipt

- **One `run_id` per run.** Each run has a new `run_id` and its own archive folder, `raw/<run_id>/`, created with
  `exist_ok=False`. A `run_id` that already appears in the journal or the receipts is refused.
- **Journal before request.** `journal.jsonl` records each job's start before the limiter or transport is called.
  A receipt is written last, after the extract rows. `complete` is true for a 200 or 404 answer, and for a body
  refused by a parser.
- **Skip.** A job with a complete receipt from any earlier run is skipped. The run summary in `runs.jsonl`
  counts it under `skipped_done`.
- **Re-fetch whole.** A job that started in an earlier run but has no complete receipt is re-fetched in full. Its
  receipt carries `refetched_after_partial`, the list of the earlier `run_id`s.
- **One run per job when reading.** `load_extract` keeps, for each job, only the rows written by the run that
  completed it. Rows from a partial run are never mixed with rows from the re-fetch.

## 4. ForecastEx staging (ruling (c))

Steps run in this order. A pairs file is not requested until every earlier step has passed.

1. **Station confirmation (V0.3), before any pairs row is read.**
   - `fex_stations` reads only text extractions of archived public ForecastEx contract filings or specs.
   - The files sit under `<archive>/forecastex/`, with names starting `pf_` or `ptc` and ending `.txt`. Notices
     are refused.
   - A city is confirmed only if some line names both its station and its region code, and that station equals
     the twin station the module pins for the city (`FEX_TWIN_STATIONS`).
   - The result is written once to `fex_stations.json`, with each source's sha256 and byte count, and to a
     receipt.
   - `fex_pairs` refuses (OrderRefused) before the request if that receipt is missing or confirms no city.
2. **First-file check (V0.4).**
   - On the first pairs file, `fex_v04_check` verifies four things: the header, the first row, a pair_time with
     at least minute resolution, and that the first `event_contract` decodes.
   - The decode rule, stated here before any row is seen, is `[U|S][H|L|A][three-letter region]`, then a date,
     then a threshold. It comes from the product code in the 2026-08-06 filing's Appendix A.
   - On failure the file is refused and `fex_v04.json` records `passed: false`. Every later pairs request is
     then refused.
3. **City filter.**
   - In `fex_pairs`, each row's `event_contract` is decoded first.
   - Rows that do not decode, rows that are not `U`/`H`, and rows whose region is not a confirmed twin are
     dropped and counted. None of their other fields is parsed, including prices.
   - The per-row expiry and pair_time bound checks then run unchanged, before any price field is read.

**Disclosure.** I checked the filings already archived under S31:

- `ptc01232637912`
- `ptc08062614351` (`pf_Daily-Temperature`)
- `ptc08272622411`
- `pf_Daily_Temperature_Celsius`

None names a per-city station. The 2026-08-06 terms say only "the specified station and city". As things stand,
V0.3 would confirm no city, so ForecastEx would be UNTESTABLE. A V0.3 run would also need the text extractions of
these filings archived first, under `<archive>/forecastex/`. No other spec source is used without master's
approval.

## 5. N

N stays as the rule sets it. If V0 coverage forces a change, the change is reported to master BEFORE the P0 runs,
not after.

## 6. Network

This clarification and its code were built and tested offline. No further network run is made until master
re-approves.
