# Weather universe and settlement diagnostics

Status: canonical expansion-foundation contract. Owner: `weather.market`.

- **Owns:** the inactive city/family registry, deterministic generation, raw
  settlement parsing, daily bounds and public read-only diagnostic command.
- **Read when:** adding a weather city or family, parsing venue bins, or using
  running METAR extrema to rule out a bin.
- **Read instead:** [venue-rule labels](venue-rule-labels.md) for existing
  training labels; [agent context](AGENT_CONTEXT.md) for serving and WU floors.

## Registry

[`config/weather_universe.json`](../../config/weather_universe.json) is generated
by `weather.market.generate_weather_universe`. It describes expansion candidates
without activating capture, models, credentials, or trading. `locations.json`
and the built-in `MarketSpec` registry retain their existing roles.

```powershell
python -m weather.market.generate_weather_universe
```

The default inputs are the supplied public survey under
`tests/fixtures/weather_expansion/inputs/`. The generator accepts `--inputs`
and `--out`, sorts cities/families, uses no clock/network, and records hashes of
its source files. Station coordinates and elevations come from the station
survey; HKO's coordinates are the existing `locations.json` station metadata.
Geographic IANA zone assignments live in the generator and are verified for
every city against independent January/July UTC offsets. They are never derived
from the workstation's timezone or a fixed current UTC offset.

`weather_universe_rule_pins.json` binds each city/family to a reviewed normalized
rule variant and independently pins each city's settlement station ICAO/id.
Generation asserts source kind, native unit, family coverage and
the resolution-source/named-station ICAO, then verifies its rule-text hash.
Normalization removes encoding damage, whitespace and event-specific dates,
airport names and AWC query dates/ICAOs; other rule words and URLs remain pinned.
Rule/source drift fails generation. Updating pins requires review of the changed
contract; regenerating the universe never blesses new hashes automatically.
A consistent station replacement across the entire survey still fails unless
the separately reviewed station pin changes.

The per-city rules determine available families. The loader rejects duplicate
slugs, invalid ICAOs/zones, wrong native units and inconsistent slug templates.
`WeatherCitySpec.event_slug` uses an English month table, independent of locale.
`WeatherCitySpec.resolution_source_url(local_date)` fills the source template.
For METAR this is **inferred from the supplied samples**: the end is 03:00 on
the next station-local date, rendered in UTC, with `hours=30`. The three hours
are wall-clock hours: NYC on 2026-03-07 queries through 07:00Z on the 2026-03-08
spring-transition date. It is a query
window convention, not an additional venue finality rule. The sample-URL test
checks every nonempty source URL, including the two static WU history URLs,
and the DST test checks coverage of a 25-hour local day.
`parse_bin_label` reuses `weather.units.parse_temperature_band`; integer bins
have closed endpoints, including negative ranges and unbounded tails. HKO's
`continuous=True` maps whole-degree labels to half-open degree intervals,
preserving the actual tenth-degree reading rather than rounding it.

## Routine METAR rule

`weather.market.metar_reports` resolves each raw `DDHHMMZ` against an explicit,
timezone-aware fetch window. Ambiguous dates or competing temperature groups
are unusable and counted in parse diagnostics. Malformation affects the field
that contains it, rather than voiding a usable value elsewhere in the report.
SPECI is excluded; unlabelled, AUTO, COR and off-hour routine reports count.
Only the exact eight-digit remark T-group is accepted. Its temperature is an
exact Decimal in tenths C; without that group the body temperature governs.
A malformed or shortened T-token is not a valid hourly remark: use a single
usable body temperature and record `body_t_group_malformed`. A malformed body
does not defeat a valid T-group. The four dew-point digits are not interpreted.
An ambiguous body is irrelevant when a valid T-group governs. An observation
with no temperature at either location is true absence. If a routine day report
is unusable because of a parse defect, the engine records `routine_day_parse_defect`
and returns `parse_incomplete` with running-style bounds, never a final single-bin
collapse; without any usable bound it returns `source_unavailable`. A malformed
report replaced by an eligible valid revision no longer makes the day incomplete.
Syntactically valid reports outside the fetch window are excluded separately.
Only settlement-critical fields can make an attributed report incomplete;
unrelated tokens such as TAF validity ranges (`0703/0803`), TX/TN forecasts and
runway visibility do not. A line without a readable station belongs to no
station, even in a single-station fetch: `unattributed_lines` counts it in
fetch diagnostics, and it cannot affect any station-day.

Unreadable observation times are counted as `unreadable_time_lines`. Without a
receipt time they affect no date (`unreadable_time_without_receipt` diagnostics).
With a receipt, a potentially qualifying routine line can affect only that
station's receipt-local date and, through exactly two elapsed hours after local
midnight, the preceding date. Receipt times after the evaluation instant or at
or after the publication cutoff cannot affect the day. True temperature absence
still does not count as a defect, even when its observation time is unreadable.

`MetarSettlementAdapter.evaluate` selects the latest eligible receipt for each
observation time, assigns station-local dates with DST, and returns both
running extrema and their original observations. A revision can lower a
previous running maximum or raise a previous minimum: always recompute from
the captured source view. `possible_bins` returns each interval's possibility,
the bound and its witness observation; these bounds are conditional on the
source view remaining unchanged until the venue cutoff. Each `BinPossibility`
carries `conditional_until`, `witness_observation_time` and `invalidating_events`.
An AWC COR or unmarked replacement can change the witness, and the rules permit
a clearly-erroneous-print correction even after the ordinary cutoff. Snapshot
responses containing distinct reports at one observation key are flagged as
ambiguous when receipt order is unknown or the latest receipt has conflicting
payloads. This guard lives in `evaluate()` too, so injected replay cannot bypass
it. Only routine reports and normalized tokens enter the conflict key; SPECI,
whitespace differences and conflicts on another local date cannot void the day.
The result is independent of caller list order.

A past `conditional_until` with status `final` is **not a settled-outcome claim**:
the clearly-erroneous-print clause has no deadline. WU and HKO paths carry their
own source-publication/revision events. WU/lowest fallbacks use the fallback
deadline; a verified HKO print uses its captured read time when supplied, and a
missing-family HKO fallback uses D+7's deadline.

The shared `venue_settlement_rules.settlement_bucket` converts C to F when
required and applies exact `floor(value + 0.5)`. Negative ties move toward the
higher integer. The legacy label path uses the same bucket/revision functions
with its existing parsing and correction-preference compatibility policy.

A day closes on the next local day's first routine report or 23:59 New York
time on that following date, whichever is earlier. The named minute is implemented
as 23:59:00 New York time. Receipt-bearing replay
rejects revisions received at or after the cutoff. Raw API text has no receipt
times: its result explicitly says `publication_cutoff_unverified_without_receipt_times`.
It cannot reconstruct what the source showed at an earlier publication cutoff.
Without qualifying temperatures the fallback clause is separately gated on
23:59:00 New York time on D+1, even if the next day's first routine report has
already arrived. `wu_values=None` means unknown, never empty. Until the deadline,
or while WU remains unknown, the result is unresolved (`missing` or
`awaiting_wu_fallback`) and eliminates no bins. After that deadline, supplied
native-unit WU extrema produce `wu_fallback`; only explicit `wu_empty=True`
with no qualifying AWC value and `fallback_deadline <= wu_read_at <= as_of`
permits the lowest bracket. Unknown/stale/future emptiness stays unresolved.
Contradictory WU
empty/populated input is refused. There is no automatic WU fetcher.

## Public diagnostic command

```powershell
python -m weather.market.metar_settlement now --family highest --cities toronto london
python -m weather.market.metar_settlement now --family lowest --cities nyc,munich
```

The command prints one JSON row per city: local date, current event slug,
running value, still-possible bins, witness and explicit source/event status.
It reads today's bin labels from Gamma's public `/events?slug=...` endpoint;
prices, token identifiers and trading endpoints are never consumed. Missing
events or unavailable families are explicit. No bin list is copied from an
older event. Errors are separate from a legitimate empty stream.

AWC requests retrieve the last 30 hours, initially five stations per call,
with starts spaced by at least one second. Near-cap responses are discarded
and split by station, then time; persistent single-station saturation fails
closed. The client stops the AWC run on HTTP failure, including 429, and
reports the incomplete fetch. GETs have a timeout, bounded response size,
host/path allowlist and no redirects, credentials or background service.
Gamma and HKO GET starts are also spaced by at least one second per host.
Three consecutive HTTP 429 responses disable that host for the client lifetime;
a successful response resets its counter. AWC stops its fetch on the first HTTP
failure; continuing city output never continues requests to a disabled host.
The API's own [documentation](https://aviationweather.gov/data/api/) states
that maximum-result and rate limits apply (accessed 2026-11-08).

`HKODailyExtractAdapter` reads the named free official
`https://www.weather.gov.hk/cis/dailyExtract/dailyExtract_YYYYMM.xml` endpoint.
Despite the suffix it serves a JSON `stn.data[].dayData` document; the parser
reads Absolute Daily Max and Min (columns 2 and 4, with day at column 0), skips
monthly summaries and preserves tenth-degree values. The
[official development-date extract](https://www.weather.gov.hk/cis/dailyExtract/dailyExtract_202001.xml)
is retained as a schema fixture (accessed 2026-11-09). Climate-series
`CLMMAXT`/`CLMMINT` data is not accepted as this source.

An extract that does not yet cover the requested date returns
`source_unavailable`, regardless of elapsed time; it rules out no bins. Only a
covered date with no sufficient Daily Extract value can use the lowest bracket,
and only after D+7 at 23:59:00 New York time. A later fetch cannot certify the
initial publication: its default status is `initial_publication_unverified`
and rules out no bins. Only a
caller with initial-publication evidence may set `initial_publication_verified`.
Capturing and retaining that evidence is future service work. The WU adapter
returns `not_implemented` explicitly.

High and low are independent: `family_statuses` and `status_for(family)` keep a
missing minimum from affecting a published maximum, and vice versa. The adapter's
`family` argument selects its top-level status; `possible_bins` always uses the
requested family's status. A no-data fallback also requires the snapshot's
`read_at` to be at or after its deadline and no later than `as_of`. An old or
undated empty snapshot cannot prove deadline-time absence. The public reader
stamps its completed read; parsing a retained payload requires the caller to
provide its actual captured read time, rather than inventing one at replay.

Existing training labels and incremental finalization keep their legacy path.
The scheduled Stage-A contract is WU mode, so this branch merge re-finalizes
**zero folders today**. The future runbook step 4 venue switch re-finalizes
post-cutover folders anyway; a separate branch-induced pass arises only if the
merge happens after venue mode is already live. See [venue-rule labels](venue-rule-labels.md).

The diagnostic is not an eligibility, promotion or execution gate. Its results
do not change serving floors, existing label ledgers or live-session records.

## Verification and updates

Focused owner tests cover all supplied raw station files and bin labels,
fixed-date zone offsets, exact rounding examples, corrections, off-hour/SPECI,
midnight, synthetic spring/fall DST, missing days and API-cap recovery.
The built-in registry source is hash-pinned for parity; every existing venue
label fixture call is compared as serialized JSON against frozen pre-extraction
functions. These are synthetic/parser fixtures, not an edge evaluation.

Update this document when registry generation, parsing, finality, fallback,
bin semantics or the diagnostic CLI changes. Production roll classification
always comes from `scripts/ops/roll_verdict.ps1`, using fresh capture closures.
