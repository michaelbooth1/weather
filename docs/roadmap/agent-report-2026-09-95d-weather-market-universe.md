# 95d — Public weather-market universe and capture triage

**PARTIAL census; triage delivered. Propose Taipei and Jinan daily-high evidence
capture, in that order. They add 500/day of configured shared rewards to the
4,800/day baseline (+10.4%), at an assumed 0.2 GiB/day. This is not expected
income or live authority. Universal discovery completeness and settlement
timeliness are not proved.**

Historical workstation handback for the owner-requested 95d mission. Scope is
International Polymarket, public reads only, no ingestion or registry changes.
The complete bucket table with a reason and event link for **every one of 215
families** is [families.md](weather-market-universe-20260924/families.md).
The [data dictionary](weather-market-universe-20260924/README.md) defines all
fields and missing-value semantics; [families.json](weather-market-universe-20260924/families.json)
contains the machine-readable triage.

## Identity and scope

- Branch: `codex/weather-market-universe-20260924`.
- Fetched starting base: `origin/master` at `198f7ccbcd8e80271693462425582097d22b298b`.
- Handoff read from `origin/codex/reward-test-attended-handoff-20260921` at
  `dd79c11800f203d66fb97101e121752bff5c8c34`, path
  `docs/roadmap/workstation-handoff-2026-09-95d-weather-market-universe.md`.
  The handoff explicitly requires branching from master; it is not a stack on
  the attended-session branch.
- Code/evidence commit: `7d7756c7063a7c9022a166ab022e6a74d0d6ba9a`.
  The final pushed report tip is returned in the task handback. The report-only
  successor does not change measured inputs or implementation.
- Inclusion anchor: 2026-09-24 20:20 UTC; closed-time cutoff:
  2026-07-26 20:20 UTC. Retrieval timestamps are retained per observation.
  This is a sequential crawl, not an atomic exchange snapshot.
- No `.env`, credentials, authenticated endpoints, orders, production state,
  Scheduler, config, registry, training or serving changes. The frozen mirror
  was not used. The owner stated no RE-1 session was running; test execution
  also uses the workstation's shared admission wrapper.

## Discovery and support

The collector walks eight resolved tag slugs using Gamma keyset pagination,
both open events to the terminal cursor and closed events ordered by actual
closure until a whole page predates the cutoff. It also searches 30 weather
terms. Broad `temperature` and `weather` searches hit HTTP 422 at page 101,
the observed 10,000-result ceiling. Active-only and July/August/September text
partitions complete and add one event. All tag routes reach a terminal cursor
or the historical cutoff. The [route ledger](weather-market-universe-20260924/summary.json)
retains both search errors; the tag walk is the historical coverage backbone.
An untagged event with different wording can still be missed: **do not describe
this as a proof that every weather market on the venue was found**.

The final retained set has **5,492 events and 60,347 Gamma markets**, after
excluding 123 sports, business, health and other false matches. There are
60,303 distinct nonempty condition IDs; 44 undeployed/unidentified draft
markets have no order/reward contribution. Six stale open daily events remain
in the historical inventory but are excluded from opportunity totals.
The full public current-reward walk terminates after 33 pages, with 16,364
distinct condition records across the venue. Weather book enrichment samples
321 bands, at most three eligible events per family, with up to two token
books per band. It preferentially selects a rewarded band near 0.5.

There are 5,336 observed daily family/target-date keys, 67 distinct target dates
and 51 city clusters. These include future dates and old unresolved drafts;
they are not 5,336 independent completed market-days. Rewards/books were read
on **one UTC date**. This is a descriptive census and feasibility triage, with
no fitted effect, significance test, confidence interval, power claim or
forecast edge estimate. Crossed date × market inference would require a
subsequent longitudinal design; no independence assumption is made here.

The transport accepts only allowlisted public GET endpoints, rejects redirects
and credential-like parameters, disables proxy lookup, caches immutable raw
responses under ignored `data/`, and spaces network starts by at least 1.05
seconds per host. It bounds calls, response size and timeout. Rebuild and
verification are offline. Source-page spot checks are separately recorded in
[source-read-notes.json](weather-market-universe-20260924/source-read-notes.json).

## Bucket decisions

| Bucket | Families | Decision and reason |
| --- | ---: | --- |
| Ingest now | 2 | Taipei and Jinan daily highs: current WU Daily Observations rules, native °C, rewarded, existing daily-high data shape; bounded evidence capture proposal only |
| Ingest later | 147 | Other daily highs need exact primary-source/fallback alignment; lows need a minimum-temperature contract; rain, wind, storms, drought and water levels need quantity-specific adapters |
| Not worth it | 66 | No currently tradable event, compound/manual outcomes with poor reuse, or geology adjacent to the weather tag; rediscover inactive families instead of continuously recording them |

Every individual reason, source URL and current pool is in the linked complete
table. "Not worth it" is a snapshot capture decision, not a permanent ban.
The original 12 captured cities appear in the later bucket where their current
rules need source alignment; this report does not propose stopping existing
capture. Source migration is the main reason a much larger international
temperature expansion is not in the immediate shortlist.

| Priority | Proposed family | Current eligible dates / local lead | Rewarded bands; pool/day | Minimum / reward distance | Sampled spread; displayed depth per side |
| --- | --- | --- | --- | --- | --- |
| 1 | Taipei daily high | Sep 25–26; T+0/T+1 | 9; 300 | 20 shares / 4.5 cents | 3.5 cents median; 30,058 shares median across four token books |
| 2 | Jinan daily high | Sep 25; T+0 | 4; 200 | 100 shares / 4.5 cents | 13 cents; 655 shares across two token books |

Each daily event has 11 bands. Median listing lead before local target midnight
is 35.04 hours for Taipei and 11.07 hours for Jinan. At the inclusion anchor it
was already September 25 locally; T+0 is not the UTC calendar date. Both
families are negRisk. Public competitiveness medians are 11.6304 and 0
respectively. **Zero competitiveness does not establish easy earnings**;
Jinan's wide sampled book and 100-share minimum are material fill/adverse-
selection risks. Its risk score is 4/5, versus Taipei's 2/5. Taipei has a more
useful initial capture profile, but neither has a measured attainable share.

Reported 7-day/30-day event-volume sums are 37,964.35/37,964.35 for Taipei and
5,264.82/5,264.82 for Jinan. These are **partial**, with 57/62 and 49/52 event
rows missing both rolling fields. The equality of the two sums is an API
coverage artifact, not evidence of identical actual trading over both windows.
No historical public trade crawl was substituted. Likewise, the displayed
book medians are cross-sectional samples, not temporal "typical" spreads.
YES and NO liquidity can mirror and must not be added as independent capital.

## Exact additions proposed, not applied

[proposals.json](weather-market-universe-20260924/proposals.json) contains the
complete external `MarketSpec` rows, including slug prefix, source IDs,
coordinates, observation lead and settlement source. Both location rows
already exist in `config/locations.json`; duplicating them is unnecessary.
The missing action is explicit market-spec/capture selection, with normal
generated event metadata handling, after station qualification.

| Location ID | Station | Timezone | Unit | WU history ID | Coordinates |
| --- | --- | --- | --- | --- | --- |
| `taipei` | RCSS, Taipei Songshan Airport | `Asia/Taipei` | °C | `RCSS:9:TW` | 25.069, 121.552 |
| `jinan` | ZSJN, Jinan Yaoqiang International Airport | `Asia/Shanghai` | °C | `ZSJN:9:CN` | 36.856, 117.206 |

The proposed resolution source is `wu_history`, using the maximum of the
local day's Daily Observations, not the site's separate high/low card. The
current representative rules freeze revisions at the first following-date
print, and specify a next-day 23:59 ET missing-data fallback to the lowest
bracket. Exact extraction, native rounding and cutoff behavior still need
station-specific qualification before these observations count as labels.
The existing `wu_history.summarize_daily` takes observation maxima and the
settlement reader consumes normalized daily summaries; this supports shape
reuse, not proof that every missing-data/finalization clause is implemented.

Both public WU station pages displayed September 24 observation rows without
login. The web reader showed data through 17:00 local; that does not prove
real-time delivery or a completed day. An explicit dated Jinan URL failed in
the reader. Public Open-Meteo probes returned three daily forecasts in the
correct local timezones for both cities; those retained responses establish
free supporting-guidance availability only. METAR/SYNOP availability and
latency at the exact stations remain to be qualified. NBM is US-only.

Paris (LFPB), Qingdao (ZSQD) and current Zhengzhou (ZHCC) rules name NOAA
timeseries as primary with WU fallback. Readable WU pages do not remove that
adapter gap. Zhengzhou also has zero current reward pool; old unresolved WU
events must not qualify it. Hong Kong requires its Observatory Daily Extract,
one-decimal °C handling and its own finalization/fallback contract. Daily lows
cannot reuse daily-high floors: they need minimum aggregation, lower-tail
bands and corresponding observed ceilings. For non-temperature markets, the
full table identifies the free agency/index source and required adapter;
source URLs retain station/gauge identifiers where supplied. Exact non-city
station names and recurring release latency are not all independently verified.

## Reward and disk arithmetic

The 12-city daily-high baseline is 4,800/day in current configured pools.
Adding both proposed families makes **5,300/day**. Rates are summed once per
distinct condition and reward asset; the additional asset is
`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`. No multiplier is applied again
for bands or horizons already included. These are snapshot daily rates, not
a guaranteed 30-day accrual forecast. Our share is explicitly null.

All 51 daily-high families total 14,900/day; all 51 daily-low families total
2,600/day. The broad weather-category inventory totals 20,587.004/day, including
adjacent disaster/geology rows retained as taxonomy boundaries. That broad
total is not an immediately addressable meteorological opportunity. Larger
later leads include drought, liquid-precipitation thresholds and wind/gauge
families; exact rates and source/build blockers are in the family table.

EF §10m/10n remain the economic constraints: competition changes within minutes,
minimum-size fills are possible, and distinct-market capital capacity does not
establish safe simultaneous fills. No own-account or paid-session evidence
was read. Current Gamma fee fields are retained (including weather fee
schedules); the older zero-fee observation is not extrapolated to this snapshot.

Using the handoff's **unmeasured 0.1 GiB/family/day** planning figure, two new
families cost 0.2 GiB/day, about 6 GiB/30 days. If that estimate is actually per
simultaneously recorded dated event, three horizons would make the sensitivity
0.6 GiB/day or 18 GiB/30 days. Adding all 39 new high-temperature cities would
be 3.9 GiB/day or 117 GiB/30 days; adding the 51 low families as well would be
9 GiB/day or 270 GiB/30 days. Those cases are not proposed. Production free
space was not queried. Verify trough headroom and measure bytes per family
before adding even the two-city proposal; an off-PC archive does not remove
the local active-capture footprint.

## Validation, roll verdict and reproduction

The final focused public-read/parser and roadmap tests passed **20/20** under
`workstation_heavy.ps1` (eight new tool tests and twelve existing roadmap tests).
They cover endpoint refusal, offline cache misses, actual closure cutoff,
timezone conversion, grouping, false positives, stale daily events, unsorted
and one-sided books, and source/minimum-contract separation. An intermediate
rerun was refused by an occupied shared workload lease; that gate was honored
and the later admitted run passed. Portable inventory validation reconciled
all event, condition and family pool totals. All nine generated files matched
an independent offline rebuild byte for byte. The generated roadmap backlog
check passed without edits. Task-owned pytest temp was removed; workstation
free bytes before/after cleanup were both 154377949184 (no material footprint).

The required tool returned **UNDECIDABLE, exit 1**, with all four live closure
files absent ([retained output](weather-market-universe-20260924/roll-verdict.txt)).
Per-file disposition: `tools/weather_market_universe.py` and
`tools/test_weather_market_universe.py` have **unproven closure membership**;
no loaded-closure claim is made. This report and every file under
`docs/roadmap/weather-market-universe-20260924/` are docs/evidence, roll-free
under delegation §3. The branch as a whole awaits the production tool verdict.
No schema-registry family or production-imported implementation was edited.
Push is authorized at any hour; no merge or live adoption was attempted.

From a checkout of the published branch, with its standard project interpreter:

```powershell
# Portable committed-data validation; no ignored cache or network needed.
.\venv\Scripts\python.exe tools/weather_market_universe.py verify

# Workstation tests through admission; capture-host tests use its own runbook.
$root95d = (Get-Location).Path
$python95d = Join-Path $root95d 'venv/Scripts/python.exe'
New-Item -ItemType Directory -Force scratch | Out-Null
$testArgs95d = @('-m', 'pytest', 'tools/test_weather_market_universe.py', 'tests/reporting/test_roadmap_backlog.py', '-q', '--basetemp', (Join-Path $root95d 'scratch/pytest-95d'))
$encoded95d = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject $testArgs95d -Compress)))
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ops/workstation_heavy.ps1 -Kind pytest -PythonPath $python95d -ArgumentsBase64 $encoded95d -RepoRoot $root95d
# After inspecting the resolved task-owned basetemp, remove that directory.
.\venv\Scripts\python.exe -m weather.reporting.roadmap.roadmap_backlog --fail-on-lint --check

# Historical rebuild only on a host holding the retained ignored raw cache.
.\venv\Scripts\python.exe tools/weather_market_universe.py rebuild --offline

# A new public observation needs a NEW cache and a matching inclusion timestamp.
.\venv\Scripts\python.exe tools/weather_market_universe.py collect --cache data/research/weather-universe-new --asof 2026-09-24T20:20:00+00:00
.\venv\Scripts\python.exe tools/weather_market_universe.py enrich --cache data/research/weather-universe-new
.\venv\Scripts\python.exe tools/weather_market_universe.py forecast-probe --cache data/research/weather-universe-new
.\venv\Scripts\python.exe tools/weather_market_universe.py rebuild --cache data/research/weather-universe-new --output scratch/weather-universe-new

# Production only: recompute from actual live closures before integration.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/ops/roll_verdict.ps1 -Branch codex/weather-market-universe-20260924 -Base origin/master
```

The date in the new-observation example must be changed to the actual run
anchor; it does not recreate September 24 data. Collector/rebuild work on the
capture host remains subject to its admission/window policy. The historical
raw cache is ignored and retained on the producing workstation; a clean clone
can verify the committed inventory but cannot reconstruct missing raw inputs.
Input hashes are in `summary.json`; committed evidence hashes are in
`SHA256SUMS.txt`. No workstation scratch path is required by these commands.

## Open questions and falsification

The immediate proposal shrinks or disappears if either WU station cannot
deliver the named observations before the effective cutoff, if current rules
change source, if rewards disappear, or if measured disk cost exceeds available
headroom. Taipei before Jinan is a capture priority, not a return prediction.
Outstanding work is exact station/cutoff qualification, current-source migration
for the broader daily-high universe, a measured storage budget, full rolling
trade-volume reconstruction if useful, and longitudinal competition/share
measurement under separately authorized conditions. No paid data is required.

For methodology, see the official [Gamma keyset API](https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination),
[public search API](https://docs.polymarket.com/api-reference/search/search-markets-events-and-profiles),
[public reward API](https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market)
and [Open-Meteo documentation](https://open-meteo.com/en/docs). The retained
inventory, rather than those documentation pages, supports the measured values.
