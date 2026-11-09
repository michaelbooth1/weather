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

The per-city rules determine available families. The loader rejects duplicate
slugs, invalid ICAOs/zones, wrong native units and inconsistent slug templates.
`WeatherCitySpec.event_slug` uses an English month table, independent of locale.
`parse_bin_label` reuses `weather.units.parse_temperature_band`; integer bins
have closed endpoints, including negative ranges and unbounded tails. HKO's
`continuous=True` maps whole-degree labels to half-open degree intervals,
preserving the actual tenth-degree reading rather than rounding it.

## Routine METAR rule

`weather.market.metar_reports` resolves each raw `DDHHMMZ` against an explicit,
timezone-aware fetch window. Ambiguous dates, malformed temperature groups and
duplicate temperature groups are unusable and counted in parse diagnostics.
SPECI is excluded; unlabelled, AUTO, COR and off-hour routine reports count.
Only the exact eight-digit remark T-group is accepted. Its temperature is an
exact Decimal in tenths C; without that group the body temperature governs.
A malformed T-group is flagged and rejected rather than silently substituted.

`MetarSettlementAdapter.evaluate` selects the last report shown for each
observation time, assigns station-local dates with DST, and returns both
running extrema and their original observations. A revision can lower a
previous running maximum or raise a previous minimum: always recompute from
the captured source view. `possible_bins` returns each interval's possibility,
the bound and its witness observation; these bounds are conditional on the
source view remaining unchanged until the venue cutoff.

The shared `venue_settlement_rules.settlement_bucket` converts C to F when
required and applies exact `floor(value + 0.5)`. Negative ties move toward the
higher integer. The legacy label path uses the same bucket/revision functions
with its existing parsing and correction-preference compatibility policy.

A day closes on the next local day's first routine report or 23:59 New York
time on that following date, whichever is earlier. Receipt-bearing replay
rejects revisions received at or after the cutoff. Raw API text has no receipt
times: its result explicitly says `publication_cutoff_unverified_without_receipt_times`.
It cannot reconstruct what the source showed at an earlier publication cutoff.
Without qualifying temperatures, final evaluation accepts caller-supplied WU
daily high/low values in the native unit, otherwise selects the lowest bracket.
Before closure it reports missing data without asserting a fallback result.
There is no automatic WU fetcher.

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
The API's own [documentation](https://aviationweather.gov/data/api/) states
that maximum-result and rate limits apply (accessed 2026-11-08).

`HKODailyExtractAdapter` reads the free official HKO `CLMMAXT`/`CLMMINT` JSON
series for station `HKO`, with schema, completeness and tenth-degree checks.
The [official dataset listing](https://data.gov.hk/en-data/dataset/hk-hko-rss-daily-temperature-info-hko/resource/1a78c69f-d5ee-4a0d-bb76-1e52aa97ac56)
and [API documentation](https://data.weather.gov.hk/weatherAPI/doc/HKO_Open_Data_API_Documentation.pdf)
describe these public series (accessed 2026-11-08). A later climate-series
fetch cannot certify the initial Daily Extract publication: its default
status is `initial_publication_unverified` and rules out no bins. Only a
caller with initial-publication evidence may set `initial_publication_verified`.
Capturing and retaining that evidence is future service work. The WU adapter
returns `not_implemented` explicitly.

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
