# Venue-rule settlement labels

Status: canonical label contract for training and evaluation. Owner:
`weather.backtesting.venue_rule_labels`.

- **Owns:** how the built-in markets are labelled for target dates on or after
  the venue-rule cutover: report filter, temperature reading, rounding, local
  day, corrections, fallback, station choice, provenance, and how label
  consumers read the result.
- **Read when:** building or reading training targets or evaluation labels for
  dates from 2026-10-23; changing a market's label station; touching the
  routine-METAR parsers in `weather.sources.metar_history`.
- **Not here:** the evidence that the venue changed its source (EF 10x in
  [established findings](ESTABLISHED_FINDINGS.md)); the settlement hierarchy and
  unit invariants ([agent context](AGENT_CONTEXT.md#settlement-and-units)).

## Rule

From `VENUE_RULE_CUTOVER_DATE` (2026-10-23, one constant in the owner module) a
built-in market-date is labelled with the highest **routine** METAR temperature
on the market's local date. Rule tag: `VENUE_RULE_VERSION`.

| Step | Contract |
| --- | --- |
| Report filter | A line beginning `SPECI` never counts. IEM raw text has no prefix, so routine files are fetched with IEM `report_type=3` and declared routine; an explicit `METAR`/`SPECI` prefix always wins over the declaration. Undeclared, unprefixed reports do not count. |
| Temperature | The remark T-group (`TsnTTT[snTdTdTd]`) in tenths of a degree C. A missing or malformed T-group (a `T<digit>` remark token that does not parse) falls back to the whole-degree body group (`TT/TdTd`, `M` = minus). The per-day `label_value_basis` records `t_group`, `body` or `body_t_group_malformed`. |
| Unit and rounding | Fahrenheit: `C x 9/5 + 32`, then `weather.units.round_half_up` (`floor(x + 0.5)`). Celsius (Toronto): the tenths rounded the same way to a whole degree C, so -0.5 C labels 0. Toronto's post-cutover Rules text has not been read; this is the reading until it is. Max-then-round equals round-then-max because the conversion is monotone. |
| Local day | Observation instant (IEM `valid`) in the market's zone, DST included; a 25-hour fall-back day keeps both 01:xx reports. |
| Corrections | A `COR` report replaces the original at its observation time while it is received before the next local day's first report. IEM rows carry no receipt time, so an IEM correction is accepted; a `receipt_time` column, when present, enforces the deadline. |
| Finality | A date is labelled only once the station's stream holds a later report. |
| Fallback | If the stream spans the date but holds no routine temperature, the WU Daily Observations row is used (`wu_fallback_no_routine_metar`), but only when the WU history station is the label station. Otherwise, and for dates the stream does not span, there is no row. |
| Before the cutover | The WU row passes through unchanged (`wu_history`). |
| Markets | Built-ins only (`BUILTIN_SPECS`). Hong Kong and the pilot cities are not built-ins. |

Effective WU print cutoffs, intraday features, the observed floor and serving
are untouched: this is a whole-day final label, read only by training and
evaluation. Features keep train/serve parity because only the target moves.

## Station

For a market-date the first match wins:

1. the latest entry in [`config/venue_rule_stations.json`](../../config/venue_rule_stations.json)
   whose `effective_from` is on or before the date (`config_override`);
2. the ICAO in the event's `resolutionSource` (`event_resolution_source`),
   when an event snapshot is passed with `--events`;
3. the registry ICAO (`registry`).

Change a station by adding a dated entry; never rewrite an earlier one. Denver
labels on KDEN from 2026-10-23 and KBKF before (lane F): the venue names KDEN
from that event, and the two stations' daily maxima differ too often for a
fixed correction. KDEN has no WU history here, so Denver has no WU fallback
from the cutover. Model and serving inputs stay on the registry station.

## Output and consumers

```powershell
python -m weather.backtesting.venue_rule_labels fetch --station KLGA --start 2026-10-23 --end 2026-10-31
python -m weather.backtesting.venue_rule_labels build --market nyc
```

`fetch` is a network download (IEM routine-only, with raw text) into
`data/venue_rule_labels/metar/<icao>/routine/`; run it only where downloads are
approved. `build` writes `data/venue_rule_labels/<market>/daily/daily_summary.csv`
and a `manifest.json` (input hashes, station config hash, counts, skipped dates
with reasons). The CSV keeps the shared daily columns (`max_temp`,
`max_temp_bucket`, `row_count`, `max_temp_times`) and adds `label_source`,
`label_station`, `label_station_basis`, `label_event_station`,
`label_rule_version`, `label_cutover_date`, `label_value_basis` and report
counts. `row_count` is the routine report count, so a thin METAR day is graded
by the ledger's existing complete-day threshold.

- Ledger: `python -m weather.market.market_day_labels finalize --label-rule venue`
  finalizes each market against its venue CSV and refuses to run if one is
  missing. The default stays `--label-rule wu`. The ledger row records the CSV
  path and hash; its `resolution_source_type` field is still the legacy WU
  literal, which a ledger change would have to fix.
- Training readers that take a daily-summary path (for example
  `python -m weather.calibration.forecast_error_model train --daily-summary <csv>`)
  read the CSV unchanged.

## Update this file when

Update when the rule, cutover, station precedence, output columns, or a label
consumer's wiring changes.
