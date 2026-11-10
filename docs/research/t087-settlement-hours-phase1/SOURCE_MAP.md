# T087 Phase 1 source trace — code and documentation only

DERIVED from source commit `73140b20eed0f81c8fa26bb5faf6defcb269533a`.
No runtime store or public endpoint was opened. Paths below are exact
repository-owned paths, resolved by `weather.paths.data_path/config_path` on
the capture host. The host's absolute checkout root and present file sizes
have not been observed; the master records that root in its extraction receipt.
The workstation checkout's absolute root is not asserted to be production's.

| Input | Exact production path / pattern | Source fields and reduction | Availability / authority |
| --- | --- | --- | --- |
| Routine observations, original label fetch | `data/venue_rule_labels/metar/<icao-lower>/routine/asos_routine_<start-ISO>_<end-ISO>.csv` | CSV `valid`, `metar`; file's routine-only request establishes `declared_report_type=3`. `valid` is observation UTC, not nominal reportTime. Optional `receipt_time` only if present. | Capture-host existence of the initial 10-22..11-03 files is documented by the first-run receipt in `docs/operations/venue-rule-labels.md`; not independently inspected. Historical observations are public IEM ASOS data. |
| Routine observations, subsequent refresh | `data/venue_rule_labels/runs/<utcRunId>/<icao-lower>/routine/asos_routine_<start-ISO>_<through-ISO>.csv` | Same two required CSV columns; same declaration 3. Select one completed, adequate run, using its `refresh_receipt.json` and manifest input paths. Do not concatenate overlapping runs and guess revision order. | Production layout proven by `venue_label_audit.refresh` and `venue_rule_labels.fetch_routine`. Current run IDs, coverage through 11-09 and bytes are UNKNOWN in Phase 1. Master verifies coverage; missing is missing, never silently backfilled. |
| Dated station override | `config/venue_rule_stations.json` | `markets.<market>[].effective_from`, `station_icao`; latest effective override. | Tracked config, safely read here; Denver KDEN from cutover. |
| Dated source link and event band menu | `config/location_market_events.json`, or `data/venue_rule_labels/runs/<utcRunId>/location_market_events.json` | Projected event fields are `locations[].active_events[].event_date`, `event_slug`, `resolution_source_url`; match built-in slug prefix and target date. Historical snapshot may lack a required day. Obtain the actual dated link and complete band menu from the master's Gamma response when absent. | Public event metadata; capture-host snapshot layout is documented/code-derived, not opened. Do not copy whole snapshots. |
| Final paid band | No authoritative persisted Gamma-resolution input is guaranteed for this task. Master reads `https://gamma-api.polymarket.com/events/slug/<event-slug>` | Event `slug`, `resolutionSource`; each market's `groupItemTitle`, `closed`, `umaResolutionStatus`, `outcomes`, terminal `outcomePrices` identify the final unique YES-paid band. Export only its band label and all event band labels, never payout arrays, interim probabilities or other market fields. | Public Gamma resolution, read by master only in Phase 2. Require final resolved status and unambiguous terminal payout; no >0.5 heuristic. Unresolved, disputed, canceled or nonunique result remains null/refused. |

The complete band menu is necessary metadata: a rounded degree change is not
necessarily a band change, and the menu's parity and tails are event-specific.
The link's complete `date` and `hours` query fields are also necessary; hour
count alone cannot determine the start. These contain no forecast or price.

The IEM fetch code requests UTC and `report_type=3`, with raw `metar` text.
The raw report is needed for its T-group, whole-degree body fallback, explicit
METAR/SPECI prefix and COR marker. `tmpc` alone would lose this contract, and
is deliberately not copied. `normalize_csv` is not needed for this minimal
extract: the analysis reuses `classify_report_type`, `report_temperature_c`,
`is_corrected_report`, `select_reports`, `native_value`, `round_half_up`,
`parse_temperature_band`, and `resolve_station` directly from the repo.

An IEM file has no original receipt timing; COR acceptance therefore follows
the repository's IEM convention. If a source really records receipt_time,
the minimal optional extra is the next local day's first routine observation
timestamp, solely to set COR's deadline. No temperature or raw observation
after the target date is copied. Multiple distinct corrections at one valid
time with no defensible order are refused.

These stores cannot substitute for the extract:

- `data/venue_rule_labels/<market>/daily/daily_summary.csv` and
  `data/venue_rule_labels/runs/<utcRunId>/labels/<market>/daily/daily_summary.csv`
  hold `local_date`, `max_temp`, `max_temp_bucket`, `max_temp_times`,
  `label_source`, `label_station`, counts and provenance. They have already
  collapsed the previous evening away. They also include unrelated history.
- `data/settlements/<market>/ledger.jsonl` holds revised local/proxy labels;
  it is not a guaranteed Gamma paid-band source. Stage A remains on WU per
  the R24 runbook. `data/backtest/market_day_labels.csv` is a projection, not
  settlement authority (RF, “market_day_labels.csv is NOT the settlement authority”).
- Ordinary `data/metar/<icao>/raw/asos_<start>_<end>.csv` backfills may mix
  routine reports and SPECIs and may lack raw text. The digest says that host
  store stopped at 06-30; it is not proof of this task's post-cutover coverage.
- Snapshot/model bundles, last-good-source caches, maker stores, book tapes,
  expansion-study receipt/history stores and own-session records are excluded.

Built-in label stations / zones / units, derived from BUILTIN_SPECS plus the
dated station config (not an observed event census):

| market_id | station | timezone | unit |
| --- | --- | --- | --- |
| toronto | CYYZ | America/Toronto | C |
| nyc | KLGA | America/New_York | F |
| atlanta | KATL | America/New_York | F |
| austin | KAUS | America/Chicago | F |
| chicago | KORD | America/Chicago | F |
| dallas | KDAL | America/Chicago | F |
| denver | KDEN | America/Denver | F |
| houston | KHOU | America/Chicago | F |
| los-angeles | KLAX | America/Los_Angeles | F |
| miami | KMIA | America/New_York | F |
| san-francisco | KSFO | America/Los_Angeles | F |
| seattle | KSEA | America/Los_Angeles | F |

Source owners: `src/weather/backtesting/venue_rule_labels.py` (paths, parser,
station and COR selection); `venue_label_audit.py` (run layout);
`src/weather/sources/metar_history.py` (IEM fields and filter);
`src/weather/market/market_registry.py` (built-ins);
`src/weather/units.py` (native rounding and band grammar);
`src/weather/backtesting/settlement_ledger.py:polymarket_winning_markets`
(Gamma field names; its permissive live-price winner test is NOT used);
`docs/operations/venue-rule-labels.md` (first-run existence receipt);
`docs/operations/ESTABLISHED_FINDINGS.md` §10x (dated URL examples).
