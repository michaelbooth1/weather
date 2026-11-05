# Venue-rule settlement labels

Status: canonical label contract for training and evaluation. Owners:
`weather.backtesting.venue_rule_labels` (build) and
`weather.backtesting.venue_label_reader` (read).

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
| Unit and rounding | Fahrenheit: `C x 9/5 + 32`, then `weather.units.round_half_up` (`floor(x + 0.5)`). Celsius (Toronto): see [Celsius markets](#celsius-markets). Max-then-round equals round-then-max because the conversion is monotone. |
| Local day | Observation instant (IEM `valid`) in the market's zone, DST included; a 25-hour fall-back day keeps both 01:xx reports. |
| Corrections | A `COR` report replaces the original at its observation time while it is received before the next local day's first report. IEM rows carry no receipt time, so an IEM correction is accepted; a `receipt_time` column, when present, enforces the deadline. |
| Finality | A date is labelled only once the station's stream holds a later report. |
| Fallback | If the stream spans the date but holds no routine temperature, the WU Daily Observations row is used (`wu_fallback_no_routine_metar`), but only when the WU history station is the label station. Otherwise, and for dates the stream does not span, there is no row. |
| Before the cutover | The WU row passes through unchanged (`wu_history`). |
| Markets | Built-ins only (`BUILTIN_SPECS`). Hong Kong and the pilot cities are not built-ins. |

### Celsius markets

Toronto (CYYZ) is the only built-in Celsius market. Its label is the highest
routine value in degrees C, rounded half up to a whole degree with the same
`round_half_up` (`floor(x + 0.5)`): 15.5 labels 16, 15.4 labels 15, -0.5 labels
0, -2.5 labels -2 and -2.6 labels -3. Canadian METARs normally carry no remark
T-group, so CYYZ usually labels from the whole-degree body value as printed.
Toronto's post-cutover Rules text has not been read. Master accepted this
reading on 2026-10-23, and it stands until that text says otherwise.

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
counts. `row_count` is the routine report count.

- Ledger: `python -m weather.market.market_day_labels finalize --label-rule venue`
  finalizes each market's folders dated on or after the cutover against its
  venue CSV and refuses to run if one is missing. A folder dated before the
  cutover finalizes against the market's WU daily summary, exactly as under
  `--label-rule wu`, so its ledger row names the WU summary and is identical to
  a WU-rule row (`market_day_labels.venue_label_plan` owns the routing). A
  folder dated on or after the cutover is refused (reported as a
  folder failure after the others are written) when its date has no CSV row, or
  a row with fewer routine reports than the ledger's complete-day threshold
  (`COMPLETE_DAY_MIN_ROWS`). Either case would otherwise drop the ledger back
  to the tape's WU high. The default stays `--label-rule wu`. The ledger row records the CSV
  path and hash; its `resolution_source_type` field is still the legacy WU
  literal, which a ledger change would have to fix.
- Training readers that take a daily-summary path (for example
  `python -m weather.calibration.forecast_error_model train --daily-summary <csv>`)
  read the CSV unchanged.

## Label reader

`weather.backtesting.venue_label_reader.read_venue_labels` is the one reader
for training, evaluation and the B/MG-2 one-time label transfer (owner
2026-10-25, "Switching to the venue's own labels"). It returns the venue's own
label for each market-date:

| Target date | Source | `label_policy` |
| --- | --- | --- |
| before the cutover | the market's WU daily summary row (the venue paid the WU band on every measured day) | `wu_history` |
| from the cutover | the venue CSV row, `label_source` `metar_routine` | `venue_rule` |
| from the cutover | the venue CSV row, `label_source` `wu_fallback_no_routine_metar` | `venue_rule_wu_fallback` |

```python
from datetime import date
from weather.backtesting.venue_label_reader import read_venue_labels
records, refusals = read_venue_labels("nyc", dates, read_through=date(2026, 9, 29))
```

- **Fallback.** WU is used only as the venue's own rule uses it: the build
  writes a `wu_fallback_no_routine_metar` row when the stream spans the date
  with no routine temperature and the WU station is the label station. A
  post-cutover date with no venue CSV, no row, a row below
  `COMPLETE_DAY_MIN_ROWS`, or a row whose `label_source`, `label_rule_version`
  or `label_cutover_date` is foreign is refused, never refilled from WU.
- **Provenance.** Each record is a `venue_label_record_v1` (schema family
  `weather/schema_families/venue_labels.py`) carrying `label_policy`,
  `label_source`, `label_station`, `label_station_basis`, `label_rule_version`,
  `label_cutover_date`, `label_row_count`, `source_path`, `source_sha256` (the
  whole file) and `source_row_sha256` (the row). Consumers bind the last two.
- **Embargo.** `read_through` is required. A `read_through` after 2026-09-29
  raises unless `allow_reserved_window=True`, which a caller may pass only under
  an open [reserved-window contract](reserved-confirmation-window.md). Rows dated
  after `read_through` are dropped before they are parsed.
- **Denver.** With `model_scoring=True` (the default) Denver dates from the
  cutover are refused (`market_unsupported_for_model_scoring`): the label
  station is KDEN and no KDEN model has passed the gates. B and MG-2 exclude
  Denver.
- **Not changed.** Pre-cutover dates are not relabelled with the routine-only
  rule: on 08-11..09-29 that rule disagrees with WU on 13 of 517 market-days
  and moves the band on 8, and the venue paid the WU band on all 8.

## Forward-look labels

Master ruling R24 (2026-11-01) owns how the forward looks get their post-cutover
labels: MG-1, B/MG-2, L6_G, row 72, T+1 and F8-MH (PT-1 is not runnable and
claims no date). The evening-fix read keeps its signed ledger labels. Module:
`weather.backtesting.venue_label_audit`. It runs on the host only, 00:30-09:00
under the shared workload lease, and it fetches from the network, so it runs
directly, never through the workstation wrapper (like `venue_rule_labels`).

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit refresh --through 2026-11-09
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit freeze --look mg1 --through 2026-11-29
.\venv\Scripts\python.exe -m weather.backtesting.venue_label_audit audit [--run <utcRunId>]
```

- **`refresh --through D [--start 2026-10-22]`** refuses a `D` after today. It
  creates a new `data/venue_rule_labels/runs/<utcRunId>/` (an existing folder is
  refused, never reused) and copies `config/location_market_events.json` and
  `config/venue_rule_stations.json` into it. It fetches routine-only IEM METAR
  for every label station, serially and 5 s apart, into the run
  (`<run>/<icao>/routine/`). The label stations are the 12 `BUILTIN_SPECS`
  ICAOs, every built-in station in the station config (KDEN) and the
  `resolutionSource` ICAO of built-in events only (`slug_prefix` match), so a
  non-built-in city's station is never fetched. It builds all 12 markets from
  the run and the snapshots into `<run>/labels/<market>/` and writes
  `refresh_receipt.json` (`venue_label_refresh_receipt_v1`: shas and counts).
  Then it runs the audit. A run that fails mid-fetch has no receipt; start a
  new run.
- **`freeze --look ID`** refreshes, then copies each market's CSV, manifest
  and the WU daily summary its manifest names to
  `data/venue_rule_labels/frozen/ID/<market>/` as `daily/daily_summary.csv`,
  `manifest.json` and `wu/daily_summary.csv`, with `freeze_receipt.json`
  (`venue_label_freeze_receipt_v1`). A look is frozen once; an existing `ID`
  is refused. The layout is the reader's: a look reads only that copy, through
  `read_venue_labels(..., label_root=frozen/ID,
  wu_daily_summary=frozen/ID/<market>/wu/daily_summary.csv)`, inside its
  registered entry point. Log the receipt's shas before the look starts.
- **`audit`** (default: the newest finished run) prints counts only and writes
  `audit.json` (`venue_label_audit_v1`). Per market: `label_source` counts,
  skipped dates by reason, predicted reader refusals (with and without
  `model_scoring`), thin rows (`row_count` below `COMPLETE_DAY_MIN_ROWS`),
  `body`-basis rows, Denver KDEN/`config_override` rows and Denver fallback rows
  (expected 0), pre-cutover pass-through mismatches against the WU summary,
  and the station-config sha against the checked-in one. It reads manifests,
  provenance columns and `row_count`. A label value is evaluated only to a
  yes/no (present; same WU bucket) and is never printed. **`STATION_DRIFT`** (an
  active built-in event dated from `--start` names an ICAO other than the
  config station for that date, or the registry station when no entry
  applies) exits 3. Rule it outcome-blind the same day; for a real station
  change, add a dated `venue_rule_stations.json` entry.

Embargo: before a look, master reads only stdout, receipts, manifests and the
audit, never a CSV, a METAR file or a label value. The module never imports the
reader, never passes `allow_reserved_window`, and never writes a label value,
bucket or winner. `refresh` replaces the step-1 and step-2 CLI calls for the
looks. It does not change Stage A, which stays on the WU rule (runbook step 4
waits until after B).

## Known gap: ledger source fields

A ledger row finalized with `--label-rule venue` still says
`resolution_source_type: wunderground_history` and records the WU history id,
because `weather.backtesting.settlement_ledger.resolution_spec_for` hard-codes
them. The row's `rounding` and `daily_max_window` text is also the WU wording,
and Denver's `resolution_station` still says KBKF on rows labelled from KDEN.
Master ruled on 2026-10-23 that these fields stay as they are for now:
`settlement_ledger.py` sits in the capture closure, so changing it is
roll-sensitive.

Until that changes, the label's real source is the CSV named in the row's
`daily_summary_path`, whose hash is in
`evidence.raw_resolution_hashes.daily_summary_sha256`. That CSV's
`label_source`, `label_station` and `label_rule_version` columns say what
labelled the date. Readers must not take `resolution_source_type` or
`resolution_station` as the source of a venue-rule row.

## Production cutover runbook (plan, not executed)

Status: **draft plan.** It runs only after master's host WU-vs-venue
measurement, and only if that measurement leaves the cutover date and the rule
unchanged. Steps 1-2 first ran on the host on 2026-11-03 (receipt below); steps 3-4 have not run. Window and heavy-work rules come from the
[host load policy](HOST_LOAD_POLICY.md). The fetch and build are light, but keep
them out of the 12:00-18:00 graded window.

### First production run, steps 1-2 (2026-11-03, master)

Receipt (master's host log, relayed by the coordinator): steps 1-2 ran on the host with the existing CLI,
07:20:09-07:21:41, rc 0, under lease `r24_venue_rule_labels_first_run` (released), head `99fff6c48`. Fetch 13/13
rc 0, window 10-22..11-03, 282-302 lines per station (KBKF 282, KORD 292, the rest 300-302). Build 12/12 rc 0,
`skipped=0` in every market; `metar_routine` 11 rows per market (10-23..11-02); Denver has 2 inputs (KBKF and
KDEN), every other market 1. Events snapshot sha256
`99220d4d8362180d1ae51268198889eeab055d010195570bd17b16ebf6ee6900` (1,976,585 bytes). No label CSV was opened and no label value was read;
the embargo is unchanged. Steps 3 and 4 have not run. Under the R24 ruling ([decision log](DECISION_LOG.md),
2026-11-01, paragraphs (3) and (5)) a look reads only its look-morning frozen copy, through `read_venue_labels`
inside its registered entry point, and Stage A stays `wu`; step 4 waits until after B.

| Market | `wu_history` rows | `output_sha256` | `manifest_sha256` |
| --- | --- | --- | --- |
| toronto | 16,298 | `04380c3a0196ebb864e3142bb0e882d309b794577ee4224a1e5169378827e594` | `58fda7491777886f81b7df272204e9243f9e5022b4316664238b145af2bb8381` |
| nyc | 5,161 | `187695340b9ed16de3161c3b68696bc76430b35d367d80acecc087fc617a5ffa` | `aadd02dfb0ba7852f70def587605e2784abbf8ae648a87b27f7c1027f26973a7` |
| atlanta | 5,161 | `b1c541f115658bc2480759868267322d365a5847ac63cb95357a88825aa69909` | `983e6354b0b1209ec15186b0f970940a8eec1739c9cf099fdaad670e1357b230` |
| austin | 5,076 | `bbe68186930f3280de3394be74a39c021ad6631aca6176ea8bf163713c6973dd` | `6098824b1d876badd1341ffa1c72b35dd7250fdfb2ddc3a22c39d3673d5633eb` |
| chicago | 5,161 | `7231e80fb6ca44f145f3277daf6941dc338b6265c477027750d61438017c417b` | `4378b651e6178f8c32c817503fb7b80f0cdbeb20c25f405c53151e51a8850588` |
| dallas | 5,161 | `02d0f758fc7b0958b22bd963c494708609b645971a4c4dd8baa49336c79c5f4c` | `b7e117ac76b03b2a73ac7c59561ebe411dfe38f4fd98c821603a80fa6acf8373` |
| denver | 5,152 | `2e6ad1ab930348c8c57397c3a65f42ac7c55b9bdfe30a088ed190143de9df3f3` | `b6e6d0216b1e8887f8ddf9a2544de96f4527e337d40505adfb567ec4c6e6fb75` |
| houston | 5,161 | `45344d835242223000f62bfdc7e148fac0fa8812be18c906d4e1b0e99f2509db` | `257491ae962e13d30323949b208ed1b194636598ee3d62dfa931fe4794ac797d` |
| los-angeles | 5,160 | `5f49c228b011c52538a1342e155e1088ac597f4768ea9fdcd99f2b7617475c83` | `b8032de05fcffe4f2e779d2e8cda7333ee5c87a763b8f586c2d46be2759e87f2` |
| miami | 5,161 | `4b8b081f37cbf9091bb49a079b98a5b443e721cae07d8a4e791d381912c9209d` | `325571cda47890aa920ce1bc38d40fc59a063d19edd373c34bd81592c8180e53` |
| san-francisco | 5,160 | `497d9cb6acea675193bbc249e8eb3c45c026ea7e1d4dfc0cdf372f7dbb8ab46c` | `4908a9502b6da5128a7fc386c87bef6176c974a68452f2adecc9a2bbbc6d16f3` |
| seattle | 5,160 | `8d06ce4580f2ee874a1a802e4b212e9d69495732e0f950b2eedc6d646307c410` | `fc2db319abc105218e49c19cfeb0430b1adb387d3cfd7e4ec2942d501499cf9e` |

### 1. Fetch routine METAR on the host

The routine-only request with raw text is
`MetarClient.fetch(icao, start, end, report_types=(3,), include_metar_text=True)`
in `weather.sources.metar_history`. The `metar_history` CLI does not expose those
two parameters. The command that calls the client with them is this module's
`fetch` subcommand:

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_rule_labels fetch --station KLGA --start 2026-10-22 --end 2026-10-24
```

- Run it once per label station, serially, a few seconds apart. The stations
  are the built-in registry ICAOs plus every station in
  `config/venue_rule_stations.json` (KDEN today).
- Start one day before the first target date and end one day after the last.
  The venue resolves a date at the next day's first report, so a date with no
  later report stays unlabelled. The client already requests one extra UTC day.
- Each run writes one file under `data/venue_rule_labels/metar/<icao>/routine/`.
  Do not copy in files from the ordinary `MetarStore` backfill: they mix routine
  reports with SPECIs and have no raw text.

### 2. Build each market

```powershell
.\venv\Scripts\python.exe -m weather.backtesting.venue_rule_labels build --market nyc --events config\location_market_events.json
```

Run it for every built-in market. `--events` records each event's
`resolutionSource` ICAO in `label_event_station`. A dated config entry still
wins over the event.

### 3. Verify before any ledger write

For each market, read `data/venue_rule_labels/<market>/manifest.json` and the
CSV beside it:

1. **Before the cutover:** every row dated before the cutover has `label_source`
   `wu_history`, and its `max_temp_bucket` equals the WU daily summary's bucket
   for that date.
2. **From the cutover:** every date to be finalized has a row with
   `label_source` `metar_routine`, or `wu_fallback_no_routine_metar`. A date
   listed in `skipped_dates` blocks that market's cutover until its reason is
   resolved: fetch the missing span, or accept the missing label.
3. **Station:** Denver rows from 2026-10-23 say `label_station` KDEN with
   `label_station_basis` `config_override`, and Denver has no WU-fallback rows
   from that date. In every other market, `label_station` equals
   `label_event_station` wherever the latter is present. Investigate any
   disagreement before going on.
4. **Report quality:** `row_count` is at least the ledger's complete-day
   threshold (18) on each finalized date. Count the rows whose
   `label_value_basis` contains `body`. Lane F found malformed T-groups at
   KDEN, so a few are expected; a large share means the parse should be
   checked.
5. **Inputs:** every `metar_inputs` entry has a hash, and
   `station_config_sha256` matches the checked-in config.
6. **Agreement:** read the comparison master's host measurement prescribes
   (venue-rule bucket against the venue's resolved band) before trusting the
   labels for scoring.

Then trial the finalize against scratch state, never the production ledger:

```powershell
.\venv\Scripts\python.exe -m weather.market.market_day_labels finalize <folders> --label-rule venue --labels-csv <scratch>\labels.csv --ledger-root <scratch>\ledger
```

Check that each ledger row's `daily_summary_path` names the venue CSV, that the
buckets match step 3, and that `reconciliation_status` is no worse than under
WU.

### 4. Add `--label-rule venue` to the daily chain

The ledger is finalized by step `market_day_labels_finalize` in the `settlement`
stage (Stage A). That stage is run by `weather.operations.daily_refresh run`,
built from the `$tokens` list in `scripts/ops/daily_refresh_contract.ps1`. The
step is `run_market_day_labels_finalize` in
`src/weather/operations/daily_refresh_source_steps.py`. It calls the
finalize code in process rather than running the `market_day_labels` CLI.

1. **Code (branch `claude/venue-rule-labels-chain-20261023`):**
   `weather.operations.daily_refresh run` takes `--label-rule {wu,venue}`
   (default `wu`, behaviour unchanged), `--venue-labels-root`,
   `--venue-metar-root` and `--skip-venue-label-build`. With `venue`, the
   finalize step first builds the label CSV of every market among the folders
   (`run_venue_rule_label_build`). The build reads only routine METAR already
   fetched under `--venue-metar-root` and never downloads, so step 1's fetch
   stays outside Stage A. The step then finalizes **incrementally**, as the WU
   rule does (`daily_refresh_incremental_finalize.venue_label_sources` feeding
   `finalize_incrementally`; an explicit `--folders` list or
   `--skip-polymarket-reconciliation` keeps the direct
   `market_day_labels.finalize_with_venue_labels` call). Its result carries
   `label_rule`, the per-market `venue_label_build` summary and
   `finalize_mode`/`finalize_plan` (with `refused_folder_count`).
   A missing CSV (with `--skip-venue-label-build`) returns `BLOCK` with reason
   `venue_rule_labels_unavailable`. A `--daily-summary` override returns `BLOCK`
   too. Missing or thin post-cutover rows fail the step as folder failures;
   they are re-decided on every run and never reused or indexed.
   No step was added to the registry, so a default run's step list is
   unchanged.

   **Reuse key.** A pre-cutover folder keeps exactly the WU-rule key (WU
   summary path and target-date row), so switching the rule never re-finalizes
   it. A post-cutover folder's key names the venue CSV as its daily summary and
   adds a `venue_label` entry: the SHA-256 of the CSV's whole target-date row
   (every provenance column, so a station or basis change counts even when the
   bucket does not), `VENUE_RULE_VERSION`, the cutover date, the SHA-256 of
   `config/venue_rule_stations.json` and the one the CSV's manifest recorded,
   `COMPLETE_DAY_MIN_ROWS`, and the source bytes of `venue_rule_labels` and
   `market_day_labels`. A changed row re-finalizes only its folder; a row added
   for another date does not; switching `wu` and `venue` re-finalizes every
   post-cutover folder once. Every other reuse condition (tape, ledger,
   sidecar, terminal reconciliation, recheck window, `--finalize-full`) is the
   WU rule's, in the incremental module's docstring.
2. **Scheduled change:** in `scripts/ops/daily_refresh_contract.ps1`, add
   `"--label-rule", "venue"` to `$tokens` inside the `if ($Stage -eq
   "settlement")` block, next to the other settlement-stage flags. The `.ps1` edit
   is roll-free. If the registered task's argument contract is checked against
   this script, re-register it as its runbook requires.

### Rollback

- Remove the `"--label-rule", "venue"` tokens from
  `scripts/ops/daily_refresh_contract.ps1`. The default is `wu`, so the next
  chain run labels from WU again.
- For dates already finalized under the venue rule, run
  `python -m weather.market.market_day_labels finalize <folders>` with the
  default `--label-rule wu`. The ledger is append-only, so this writes new WU
  revisions; the venue revisions stay in history and nothing is deleted.
- Keep the venue CSVs, manifests and fetched METAR files as evidence.

## Update this file when

Update when the rule, cutover, station precedence, output columns, or a label
consumer's wiring changes.
