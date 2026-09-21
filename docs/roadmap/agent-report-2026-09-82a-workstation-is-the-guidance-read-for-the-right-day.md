# Workstation handback — NBM target-period trace, mission 2026-09-82a

**WRONG-PERIOD PICKS. The unchanged parser selects the next morning's minimum
for today's maximum at 13Z and 19Z. T3 STOP: an active, live-capture-enabled
artifact selects these fields, so the handoff forbids treating the repair as
capture-only. No parser fix or fix branch was created.**

Research branch: `codex/nbm-target-trace-20260921`. Exact handoff base:
`6e3206bc62124bca09de306032d6035a0118b6de`
(`origin/codex/nbm-target-trace-handoff-20260921`). Fetched master:
`e28530af67c7371fc7b2c08bbd0e26cfe72a28f9`. Implementation/evidence commit:
`c850474de1031b6da1b5c0e2e9018f60bac0b647`. This report is the following documentation commit.
Mission executed 2026-09-21 on the non-capture workstation.

## Order, authority, and retained evidence

T0 finished before T1; T1 finished before the T2 diagnostic read; the artifact
audit followed T2. Stage timestamps and source SHA-256s are in the receipts.
Reservation status was re-read as **NONE RESERVED**. No mirror was used.
The owner explicitly approved the exact-module addition to the heavy wrapper,
Codex hook, and matching tests because the handoff's original file ownership
did not include them. Every heavy command used the workstation wrapper.

[Evidence directory](../../tools/research/nbm_target_trace/evidence/):

- [T0 token table](../../tools/research/nbm_target_trace/evidence/tokens.csv):
  every token's literal FHR group, valid UTC time, NOAA period kind, date, raw
  TXN values and available observations; 2,376 tokens from 132 station blocks.
- [T1 complete table](../../tools/research/nbm_target_trace/evidence/picks.csv):
  all 396 cycle/station/target cases, including missing picks and observed max/min.
- [T2 census](../../tools/research/nbm_target_trace/evidence/t2-summary.json):
  distributions, support, exact-tail-recovery counts, and missing medians by
  local hour, market, and each retained before/from-August-23 stratum.
- [Supplement](../../tools/research/nbm_target_trace/evidence/supplement.json):
  magnitude checks, recovered-tail distributions, signature support and the
  active artifact binding.
- [Artifact selectors](../../tools/research/nbm_target_trace/evidence/artifact-selectors.json):
  read-only inventory of all 107 tracked JSON/pickle artifacts, with hashes.
- [Evidence hashes](../../tools/research/nbm_target_trace/evidence/file-manifest.json),
  [T0 receipt](../../tools/research/nbm_target_trace/evidence/t0-receipt.json),
  [T1 receipt](../../tools/research/nbm_target_trace/evidence/t1-receipt.json),
  [T2 receipt](../../tools/research/nbm_target_trace/evidence/t2-receipt.json).

Twelve public national bulletins (~417 MB) were fetched serially, once each,
and remain in ignored scratch. Only small station blocks are committed.
Published block text normalizes LF and trailing spaces; national bytes remain
unchanged, with source hashes retained.
Twenty-two small IEM station/range CSVs are cached, with request URLs and hashes.
No source was fetched from production. The retained 79a input SHA-256 is
`249a9de0da7b41cb8a2ce1f07944e4007c585f601028b73acaae0dd4bd141c2e`.

## T0 — NOAA's convention and the magnitude check

NOAA's [NBP product key](https://vlab.noaa.gov/web/mdl/nbm-textcard-v5.0)
defines the mean, standard deviation and percentile TXN rows as **minimum at
12Z, maximum at 00Z**. For these 11 mainland US stations, the 00Z maximum label
belongs to the preceding date; the 12Z minimum belongs to its labeled date.
The broader TXN definition uses an 18-hour extreme window, not an exact
local-midnight day. The groups separated by pipes are UTC dates, not guarantees
that their first token is a maximum: 01Z/07Z begin with a 00Z maximum,
whereas 13Z/19Z begin with a lone 12Z minimum. Thus the hypothesis was right
about the selection defect, but “12-hour maximum/minimum periods” was imprecise:
the output labels alternate every 12 hours; the defined extreme windows differ.

Sample: September 17, 18, 19, 2026; cycles 01Z, 07Z, 13Z, 19Z; KATL, KAUS,
KORD, KDAL, KBKF, KHOU, KLAX, KMIA, KLGA, KSFO, KSEA. Observations use
[IEM ASOS daily summaries](https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?help).
IEM warns that airport summaries typically follow standard-time days (01:00
to 01:00 in daylight time), with possible explicit daily reports overriding
computed summaries. They are supporting observations, not substituted settlement.

The available observed dates cover 330 maximum tokens (4 date clusters,
11 markets) and 264 minimum tokens (3 dates, 11 markets). Maximum-token p50
minus observed maximum: median **+2°F**, 10th–90th percentiles −1.2..+5°F;
minus observed minimum: +17°F. Minimum-token p50 minus observed minimum:
**+1°F**, 10th–90th −1..+3°F; minus observed maximum: −14°F.
These are finite token distributions with repeated forecasts, not independent
forecast-accuracy estimates. Future token labels are recorded but have no
observed outcomes, and are not included in that magnitude check.

## T1 — unchanged parser picks

Offset is relative to the issue time's station-local date. Each cell contains
33 station/date cases (3 dates × 11 markets). “Unavailable” is neither right
nor wrong. Group and token indices in the full table are zero-based.

| Cycle | Local date −1 | Local date | Local date +1 |
| --- | --- | --- | --- |
| 01Z | 33 unavailable | 33 unavailable | 33 right maximum |
| 07Z | 33 unavailable | 33 right maximum | 33 right maximum |
| 13Z | 33 unavailable | **33 wrong minimum** | 33 right maximum |
| 19Z | 33 unavailable | **33 wrong minimum** | 33 right maximum |

Total: 165 right-period picks, 66 wrong-period picks, 165 unavailable.
Every wrong pick is group 0/token 0, valid 12Z on the following UTC date.
Its median p50 is **15°F below the requested day's observed maximum** and
**1°F above the actual labeled period's observed minimum** (66 picks,
33 market-days, 3 dates, 11 markets). The corresponding 10th–90th ranges
are −25..−8.5°F and −0.7..+3°F.

Concrete slice, September 17 at 13Z, target September 17. Every row selects
group 0/token 0, valid **September 18 12Z**, NOAA **minimum**:

| Station | Returned p50 °F | Requested day's observed max / min °F |
| --- | ---: | ---: |
| KATL | 72 | 90 / 69 |
| KAUS | 73 | 97 / 73 |
| KBKF | 58 | 81 / 62.6 |
| KDAL | 80 | 100 / 83 |
| KHOU | 78 | 88 / 78 |
| KLAX | 65 | 78 / 69 |
| KLGA | 72 | 85 / 73 |
| KMIA | 78 | 84 / 76 |
| KORD | 65 | 80 / 66 |
| KSEA | 55 | 77 / 54 |
| KSFO | 59 | 72 / 60 |

The load-bearing trace is `_slot_index_for_target`: it takes group token 0,
subtracts a day regardless of valid hour, then `parse_nbp_station_tmax`
reads token 0. There is **no same-day maximum in the 13Z/19Z bulletin**:
the next maximum is tomorrow's. A future repair must reject the absent target
maximum and let the collector try an older cycle; choosing the next token or
next group would merely substitute tomorrow's maximum.

## T2 — export diagnosis, with the missing-median limit

The unchanged 79a admission yields 81,430 US snapshots, 461 market-days,
42 date clusters and 11 markets. Three have no raw feature row; they remain
explicitly counted as such. There are **55,565 explicitly NBM-floor-dropped
rows**, also 461 market-days / 42 dates / 11 markets.

**Correction to what the handoff can recover:** p75−IQR recovers p25,
and p90−spread recovers p10. Neither identity identifies p50. Of the dropped
rows, **54,863 have p50 explicitly deleted**; only 702 retain it. Exact recovery
is possible for p10 on 2,031 rows and p25 on 956. On 2,031 rows the surviving
upper tail bounds p50; the median upper-bound-minus-settled-max is −8°F.
The report does not interpolate medians or treat the survivor sample as all
dropped guidance.

A separate code-traced diagnostic is available on all 55,565 dropped rows:
`guidance_physical_floor + nbm_prob_tmax_floor_gap` recovers the recorded
**representative high**. The source code chooses raw p90 when present/nonzero,
otherwise mean/p50. This diagnostic is kept under its own name; it is not
claimed to identify the deleted p50. Its median is **14°F below the settled
maximum**, versus **2.7°F above the next day's observed minimum**.
10th–90th ranges: −23..−8°F and +1..+6°F, respectively.

The table below reports finite census medians in °F. “p50 n” is the number
whose median survived despite another quantile being dropped. The minimum
comparison is the following date's IEM minimum, matching the wrong period.
Full quantiles, each metric's denominator and stratum splits are retained.

| Local hour | Dropped n | Dates / markets | p50 n | p50 − max / next min | Representative − max / next min |
| --- | ---: | ---: | ---: | ---: | ---: |
| 00 | 83 | 9 / 3 | 75 | 0 / 14 | 3 / 17 |
| 01 | 68 | 9 / 3 | 50 | 1 / 14.5 | 3 / 17 |
| 02 | 73 | 9 / 3 | 52 | 1 / 14 | 3 / 17 |
| 03 | 67 | 9 / 3 | 49 | 1 / 15 | 3 / 17 |
| 04 | 43 | 8 / 3 | 30 | 0 / 9 | 2 / 16 |
| 05 | 42 | 6 / 3 | 29 | 1 / 9 | 2.5 / 14.5 |
| 06 | 625 | 41 / 5 | 83 | −8 / 3 | −11 / 2 |
| 07 | 1,195 | 42 / 6 | 131 | −10 / 2 | −13 / 2 |
| 08 | 2,209 | 42 / 9 | 108 | −10 / 1 | −15 / 2 |
| 09 | 3,261 | 42 / 11 | 53 | −9 / 1 | −14 / 2.6 |
| 10 | 3,720 | 42 / 11 | 27 | −8 / 1 | −14 / 2.7 |
| 11 | 3,430 | 42 / 11 | 8 | −5 / 1 | −14 / 2.7 |
| 12 | 3,540 | 42 / 11 | 7 | −5 / 1 | −14 / 3 |
| 13–23 | 37,209 | 42 / 11 | 0 | unavailable | −14 at each hour / 2–3 |

| Market | Dropped n | Market-days / dates | p50 n | p50 − max / next min | Representative − max / next min |
| --- | ---: | ---: | ---: | ---: | ---: |
| Atlanta | 4,682 | 42 / 42 | 6 | −16 / −2 | −16 / 2 |
| Austin | 4,883 | 41 / 41 | 0 | unavailable | −22 / 3 |
| Chicago | 5,185 | 42 / 42 | 237 | 0 / 9 | −12 / 3 |
| Dallas | 4,889 | 42 / 42 | 12 | −19 / 1 | −16 / 2 |
| Denver | 5,281 | 42 / 42 | 20 | −26 / −2 | −24 / 4 |
| Houston | 4,899 | 42 / 42 | 8 | −12.5 / 1 | −13 / 2 |
| Los Angeles | 5,413 | 42 / 42 | 102 | −10 / 2 | −9 / 1 |
| Miami | 4,585 | 42 / 42 | 0 | unavailable | −9 / 4 |
| NYC | 4,720 | 42 / 42 | 165 | 1 / 7.6 | −11 / 2 |
| San Francisco | 5,497 | 42 / 42 | 107 | −9 / 1 | −11 / 2 |
| Seattle | 5,531 | 42 / 42 | 45 | −5 / 1 | −17 / 2 |

Every market row has one market cluster. These distributions are a census of
the retained export, with no resampling, confidence interval, power/MDE,
alpha spend, forecast-effect estimate or pooling claim across artifact regimes.
Correct forecasts can still lose a low quantile to the floor, particularly
at hours 00–05; the result does not attribute every rejected row to the bug.

On the three T0 dates, **3,754 dropped snapshots (33 market-days, 3 dates,
11 markets)** match only minimum-period signatures among the retained candidate
bulletins; 95 match only maxima. Comparison uses every surviving quantile,
stddev, IQR, spread and the representative high where present. It restricts
issues to the preceding 26 hours (24-hour search plus 120-minute cache).
These matches corroborate the mechanism, but are not recovered payload hashes:
unsampled cycles, cache state and deleted values prevent unique provenance.

### Why these cycles reach morning snapshots

The collector searches current UTC hour back through 24 hours, newest first,
skips HTTP 403/404, and returns the first parser payload marked available.
`model_constants.py` assigns NBM a 120-minute source-cache TTL. Thus any
older matching cycle within that search can be delivered after failures;
a cached selection can persist another two hours. The actual issue is not
present in the export and is not asserted here.

Nominal transition to the same-day 13Z cycle (all dates in this sample are
daylight time), before publication delay and cache retention:

| Zone | 13Z local time | Local 06–12 newest full-TXN cycles at nominal issue time |
| --- | --- | --- |
| Pacific | 06:00 | 13Z at 06–11; 19Z at 12 |
| Mountain | 07:00 | 07Z at 06; 13Z at 07–12 |
| Central | 08:00 | 07Z at 06–07; 13Z at 08–12 |
| Eastern | 09:00 | 07Z at 06–08; 13Z at 09–12 |

Earlier 01Z/07Z or prior-date cycles remain possible fallbacks. 00Z/12Z have
partial elements and other hours limited elements according to NOAA; the
code can even mark a target slot available without checking complete TXN rows.
The table is a conditional timing explanation, not a reconstruction of fetches.
The west-to-east loss of guidance and eventual near-total rejection fit the
13Z change, with cache/publication timing shifting its onset. The hypothesis
that wrong cycles are never used in the morning is therefore falsified.

## T3 — active artifact stop condition

The audit loaded no estimator for prediction and fit nothing. It inspected
107 tracked artifact payloads read-only; existing LFS objects were SHA-256
verified and no worktree artifact was smudged or changed. Exactly one payload
selects NBM fields:

`artifacts/models/hgb/feature_model_hgb_f_pooled_v0_3.pkl`, SHA-256
`3b472bd32667256c6605a6f48c2c9c4ba7e58f140a89c504c4b4fbfcac6a497c`.
Its actual `/models/7..20/feature_names` select **all 15**
`nbm_prob_tmax_*` columns, including percentiles, mean, stddev, spreads,
forecast-high comparisons, exceedance, validity/impossible flags and floor gap.

This is an active consumer, not merely an unused pickle:
`config/model_variant_registry.json` binds it to
`pooled_f_candidate_miami_current_fallback_v0_1`, with
`lifecycle=active`, `live_capture_enabled=true`, and
`live_runtime=pooled_candidate_replay`. The tracked artifact registry calls it
`active_shadow`. Promotion is blocked and headline use is false, but neither
disables this active capture consumer. The code path is
`active_live_variants` → `_pooled_candidate_replay_payload` →
`trace_pooled_band_binary_probabilities` → the selected hourly feature bundle.
This path was inspected, not executed. The files and artifact bytes are
identical between the handoff base and fetched master. The workstation cannot
attest production's ignored release pointer or current runtime.

The handoff explicitly says: **“if one does, stop and report — that is a
train/serve parity change needing its own mission.”** That condition is met.
Neither the slot change nor new runtime diagnostics were implemented; T4
does not apply because the parser-right hypothesis is false. A new parity
mission must handle this active artifact before changing the parser. This
report grants no fitting, scoring, retirement, promotion or live authority.

## Verification, roll verdict, and publication boundary

Focused trace, cache-integrity and admission verification: **83 passed,
11 expected skips** (platform/outer-lease conditions). One initial allowlist
expectation required the same exact-module update as the hook/wrapper; after
that adjustment the suite passed. One T2 attempt encountered a missing raw
feature row; the correction counts missing rows explicitly, preserves all
79a snapshots and reuses all cached public files. No gate was relaxed.
Targeted compileall, documentation audit (18 agent files / 899 Markdown files)
and diff checks passed. Both pytest temporary trees were removed.
No broad suite was needed for a research tool and exact allowlist addition.

The required repository roll tool returned **UNDECIDABLE: no live closure
evidence**, listing absent snapshot, CLOB, observation-trigger and enrichment
status files. Every changed file's four closure memberships are therefore
unverified; the [per-file inventory](../../tools/research/nbm_target_trace/roll-files.json)
records that outcome. No closure was inferred by hand or fetched from the
frozen mirror. Production must rerun the tool. There is no fix branch to
classify and no change under `src/`, `config/` or `artifacts/`.

**Not done:** no Brier or other score, served/market comparison, new candidate,
model fit, forecast proposal, alpha allocation, reservation change, floor
weakening, production write, registration, Scheduler mutation, capture
restart, credentials, exchange calls, live trading, promotion or master merge.
Only the requested research branch is pushed; all source checkouts and prior
evidence remain intact.

Exact reproduction commands and existing workstation input/cache paths are in
the [tool README](../../tools/research/nbm_target_trace/README.md#reproduce-on-the-workstation).
The original authoritative output root is
`C:/Users/Michael/Documents/github/weather/scratch/nbm-target-trace-20260921`.
Use the documented fresh output root and shared cache; never rerun a national
download. The original checkout remains on its untouched master branch.
